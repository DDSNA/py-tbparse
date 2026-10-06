"""`sheet copy` (WP14e): copy worksheets from one workbook into another, same-internal-name slice.

Built on `sheetcopy_core` (closure, datasource matching, rewriting, uuid and window helpers) and on the library
planner (`library._plan`) for the calculations and parameters a sheet needs and the target lacks.

Rules of this slice (owner decisions 2026-10-06):

* The target datasource must match the source one by connection AND have the same internal name; otherwise the
  sheet is refused with the message of `sheetcopy_core.match_datasource`.
* A sheet uses one datasource (a blend is refused), and every physical field, group and bin it needs must exist
  in the target under the same name. Calculations and parameters are added by the library planner.
* `on_clash` is `fail` (default), `rename` or `skip`, for calculations, parameters and sheet names. `fail`
  stops the whole run before anything is written.
* Action filters (they depend on a dashboard action that is not copied) and tooltip sheets that are not copied are
  dropped and reported; `strict=True` refuses instead.
* Not copied: dashboards, actions, thumbnails, sets/groups/bins to add, blends, datasources the target lacks.

Never opened in Tableau Desktop; keep saying so.
"""

from __future__ import annotations

import copy
import os
import re
from pathlib import Path
from typing import Iterable, Optional, Union

from lxml import etree

from . import library as _lib
from .library import CLASH_POLICIES, LibraryError, _PARAMETERS, _unbracket
from .parser import TwbParser
from .rename import _insert_column, _serialize_workbook
from .sheetcopy_core import (
    SheetCopyError, add_window, compare_to_target, copy_sheet_element, copy_window, dependency_closure,
    match_datasource, new_uuid, sheet_datasources,
)
from .usage import _datasource_fields

_ACTION_COLUMN = re.compile(r"\[Action \(")
_TOOLTIP_SHEET = re.compile(r"<Sheet\s+name=\"([^\"]+)\"[^>]*?/?>")
_NUMBERED = re.compile(r"^(.*) \((\d+)\)$")


class SheetCopyAbort(SheetCopyError):
    """The whole run stops before anything is written (a clash under `fail`, a strict refusal, an unknown sheet)."""


def _parser(x) -> TwbParser:
    return x if isinstance(x, TwbParser) else TwbParser(str(x))


def _free_name(name: str, taken: set) -> str:
    m = _NUMBERED.match(name)
    base = m.group(1) if m else name
    n = int(m.group(2)) + 1 if m else 2
    while f"{base} ({n})" in taken:
        n += 1
    return f"{base} ({n})"


def _is_action_ref(text: Optional[str]) -> bool:
    return bool(text) and bool(_ACTION_COLUMN.search(text))


def _drop_action_filters(ws) -> list[str]:
    """Remove the action filters of a copied worksheet and every cached trace of their groups; return what was
    dropped (the filtered column of each)."""
    dropped: list[str] = []
    for f in list(ws.iter("filter")):
        ui = any(k.endswith("ui-action-filter") for g in f.iter() if isinstance(g.tag, str) for k in g.attrib)
        if _is_action_ref(f.get("column")) or ui:
            dropped.append(f.get("column") or "")
            f.getparent().remove(f)
    for col in list(ws.xpath(".//datasource-dependencies/column | .//datasource-dependencies/column-instance")):
        if _is_action_ref(col.get("name")) or _is_action_ref(col.get("column")):
            col.getparent().remove(col)
    for col in list(ws.xpath(".//slices/column")):
        if _is_action_ref(col.text):
            col.getparent().remove(col)
    for el in list(ws.xpath(".//slices | .//datasource-dependencies")):      # the schema wants a child
        if len(el) == 0 and el.getparent() is not None and not (el.text or "").strip():
            el.getparent().remove(el)
    return dropped


def _fix_tooltips(ws, copied: dict) -> list[str]:
    """Point viz-in-tooltip references at the copied name, or drop the ones whose sheet is not copied."""
    dropped: list[str] = []
    for run in ws.xpath(".//customized-tooltip//run"):
        text = run.text or ""
        if "<Sheet" not in text:
            continue

        def sub(m):
            name = m.group(1)
            if name in copied:
                return m.group(0).replace(f'name="{name}"', f'name="{copied[name]}"')
            dropped.append(name)
            return ""

        run.text = _TOOLTIP_SHEET.sub(sub, text)
    return dropped


def _entry_key(row: dict) -> str:
    return ("[Parameters]." + row["name"]) if row["kind"] == "parameter" else row["name"]


def _run(source, target, sheets: Iterable[str], on_clash: str = "fail", strict: bool = False,
         ctx: Optional[dict] = None, report_actions: bool = True, allow_empty: bool = False):
    """Do everything on a copy of the target's XML. Returns `(doc, report)`. `ctx`, when given, is filled with what
    `dashboardcopy` needs afterwards (`results`, `names`, `params`, `taken`, `copied`, `src`, `dst`);
    `report_actions=False` leaves out the "dashboard actions are not copied" note; `allow_empty` accepts no sheets."""
    if on_clash not in CLASH_POLICIES:
        raise SheetCopyAbort(f"on_clash must be one of {', '.join(CLASH_POLICIES)}, got {on_clash!r}")
    src, dst = _parser(source), _parser(target)
    sdoc = src.xml_doc
    doc = copy.deepcopy(dst.xml_doc)
    wanted = list(dict.fromkeys(sheets))
    if not wanted and not allow_empty:
        raise SheetCopyAbort("no sheets named; use --sheets A,B")
    have = set(sdoc.xpath("/workbook/worksheets/worksheet/@name"))
    unknown = [s for s in wanted if s not in have]
    if unknown:
        raise SheetCopyAbort("the source has no worksheet named " + ", ".join(repr(s) for s in unknown))

    results: dict[str, dict] = {s: {"sheet": s, "status": "copy", "new_name": s, "datasource": "", "reason": "",
                                    "dropped": []} for s in wanted}
    closures: dict = {}

    def refuse(s, why):
        results[s].update(status="refused", reason=why)

    # 1. per sheet: datasource, closure, fit with the target
    for s in wanted:
        used = sheet_datasources(sdoc, s)
        if not used:
            refuse(s, "the sheet uses no datasource")
            continue
        if len(used) > 1:
            refuse(s, f"blend of {len(used)} datasources ({', '.join(used)}); not supported")
            continue
        ds = used[0]
        results[s]["datasource"] = ds
        try:
            match_datasource(sdoc, ds, doc)
        except SheetCopyError as e:
            refuse(s, str(e))
            continue
        c = dependency_closure(sdoc, s)
        if c.unresolved or c.cross_datasource:
            refuse(s, "needs names the datasource does not define or another datasource: "
                      + ", ".join(c.unresolved + c.cross_datasource))
            continue
        cmp = compare_to_target(sdoc, c, doc)
        if cmp["missing"]:
            refuse(s, "the target datasource lacks: " + ", ".join(cmp["missing"]))
            continue
        bins = [n for n in cmp["clash"] if n in c.bins]
        if bins:
            refuse(s, "a bin of the same name differs in the target: " + ", ".join(bins))
            continue
        if cmp["clash"] and on_clash == "fail":
            raise SheetCopyAbort(f"{s!r}: already in the target with another definition (on_clash='fail'): "
                                 + ", ".join(cmp["clash"]))
        closures[s] = c

    # 2. sheet names
    tw = set(doc.xpath("/workbook/worksheets/worksheet/@name")) | set(doc.xpath("/workbook/dashboards/dashboard/@name"))
    for s in wanted:
        if results[s]["status"] != "copy":
            continue
        if s in tw:
            if on_clash == "fail":
                raise SheetCopyAbort(f"{s!r} is already a sheet or dashboard of the target (on_clash='fail')")
            if on_clash == "skip":
                results[s].update(status="skipped", reason="the target already has a sheet or dashboard of that name")
                continue
            results[s]["new_name"] = _free_name(s, tw)
        tw.add(results[s]["new_name"])

    # 3. calculations and parameters, one library for all sheets that still go
    plan_rows: list[dict] = []
    names: dict[str, dict] = {}
    params: dict[str, dict] = {}
    caps: dict[tuple, str] = {}
    live = [s for s in wanted if results[s]["status"] == "copy"]
    by_ds: dict[str, list] = {}
    for s in live:
        by_ds.setdefault(results[s]["datasource"], []).append(s)
    tparser = _FakeParser(dst, doc)
    for ds, group in by_ds.items():
        select = list(dict.fromkeys(n for s in group for n in closures[s].calcs + closures[s].parameters))
        names[ds], params[ds] = {}, {}
        if not select:
            continue
        lib = _lib.export_library(src, datasource=ds, select=select, include_parameters=True)
        try:
            plan, actions, T = _lib._plan(tparser, lib, ds, None, on_clash)
        except LibraryError as e:
            raise SheetCopyAbort(str(e)) from e
        rows = plan[plan["uid"] != ""].to_dict("records")
        plan_rows += [dict(r, datasource=ds) for r in rows]
        pds = _lib._parameters_ds(doc)
        for a in actions:
            if a["entry"]["kind"] == "parameter":
                if pds is None:
                    pds = _lib._new_parameters_ds(doc)
                _insert_column(pds, _lib._build_param(a))
            else:
                _insert_column(doc.xpath("/workbook/datasources/datasource[@name=$n]", n=ds)[0], _lib._build_calc(a))
        failed = {_entry_key(r): r for r in rows if r["action"].startswith("fail")}
        for r in rows:
            if r["action"].startswith("fail") or not r["target_name"]:
                continue
            mp = params[ds] if r["kind"] == "parameter" else names[ds]
            if r["target_name"] != r["name"]:
                mp[r["name"]] = r["target_name"]
            if r["action"] == "add-renamed" and r.get("target_caption"):
                caps[(ds, r["kind"] == "parameter", r["target_name"])] = r["target_caption"]
        for s in group:
            hit = [k for k in closures[s].calcs + [("[Parameters]." + p) for p in closures[s].parameters]
                   if k in failed]
            if hit:
                refuse(s, "not importable: " + "; ".join(f"{k} ({failed[k]['reason']})" for k in hit))

    # 4. copy the sheets
    taken = set(doc.xpath("//simple-id/@uuid"))
    copied = {s: results[s]["new_name"] for s in wanted if results[s]["status"] == "copy"}
    tws = doc.find("worksheets")
    if tws is None:
        tws = etree.Element("worksheets")
        anchor = doc.find("datasources")
        anchor.addnext(tws)
    for s, new in copied.items():
        res = results[s]
        ds = res["datasource"]
        cap = (doc.xpath("/workbook/datasources/datasource[@name=$n]/@caption", n=ds) or [None])[0]
        ws = copy_sheet_element(sdoc, s, new, taken, ds_map={ds: ds}, names=names[ds], params=params[ds],
                                captions={ds: cap} if cap else None)
        for (cds, is_p, nm), newcap in caps.items():
            if cds != ds:
                continue
            for col in ws.xpath(".//datasource-dependencies[@datasource=$d]/column[@name=$n][@caption]",
                                d=_PARAMETERS if is_p else ds, n=nm):
                col.set("caption", newcap)
        res["dropped"] += [f"action filter on {c}" for c in _drop_action_filters(ws)]
        res["dropped"] += [f"tooltip sheet {n}" for n in _fix_tooltips(ws, copied)]
        tws.append(ws)
        if copy_window(sdoc, doc, s, new, taken) is None:
            add_window(doc, "worksheet", new, [], new_uuid(taken))
        win = doc.xpath("/workbook/windows/window[@class='worksheet'][@name=$n]", n=new)[-1]
        for vp in win.xpath("./viewpoints/viewpoint"):
            if vp.get("name") == s:
                vp.set("name", new)
        n_actions = len(sdoc.xpath("/workbook/actions/action[source/@worksheet=$n or .//param[@value=$n]]", n=s))
        if n_actions and report_actions:
            res["dropped"].append(f"{n_actions} dashboard action(s) naming the sheet (actions are not copied)")
    if strict and any(r["dropped"] for r in results.values() if r["status"] == "copy"):
        what = "; ".join(f"{s}: {', '.join(r['dropped'])}" for s, r in results.items() if r["dropped"])
        raise SheetCopyAbort("--strict: the copy would drop " + what)

    # 5. the result must hold together
    from .dashboards import integrity_check
    problems = integrity_check(doc)
    before = integrity_check(dst.xml_doc)
    new = [p for p in problems if p not in before]
    if new:
        raise SheetCopyAbort("integrity check failed on the result: " + "; ".join(p["check"] + " " + p["detail"] for p in new))

    if ctx is not None:
        ctx.update(results=results, names=names, params=params, taken=taken, copied=copied, src=src, dst=dst,
                   closures=closures)
    sheets_out = [results[s] for s in wanted]
    report = {
        "source": str(src.twbx_path or src.path), "target": str(dst.twbx_path or dst.path), "on_clash": on_clash,
        "sheets": sheets_out, "library": plan_rows,
        "copied": sum(r["status"] == "copy" for r in sheets_out),
        "skipped": sum(r["status"] == "skipped" for r in sheets_out),
        "refused": sum(r["status"] == "refused" for r in sheets_out),
        "added": [{"kind": r["kind"], "name": r["name"], "target_name": r["target_name"],
                   "caption": r["target_caption"]} for r in plan_rows if r["action"] in ("add", "add-renamed")],
    }
    return doc, report


class _FakeParser:
    """Just enough of a TwbParser for `library._plan`: the target's path and the working XML copy."""

    def __init__(self, parser: TwbParser, doc):
        self.xml_doc = doc
        self.path = parser.path
        self.twbx_path = parser.twbx_path


def plan_sheet_copy(source, target, sheets: Iterable[str], on_clash: str = "fail", strict: bool = False) -> dict:
    """What `build_sheet_copy` would do: a report dict (`sheets`, `library`, `added`, counts). Nothing is
    written. Raises `SheetCopyAbort` for what stops a whole run."""
    return _run(source, target, sheets, on_clash, strict)[1]


def build_sheet_copy(source, target, sheets: Iterable[str], on_clash: str = "fail", strict: bool = False):
    """`(bytes, report)`: the target workbook with the sheets added, in the target's format."""
    tp = _parser(target)
    doc, report = _run(source, tp, sheets, on_clash, strict)
    return _serialize_workbook(tp, doc), report


def copy_sheets(source, target, sheets: Iterable[str], output_path: Optional[str] = None, on_clash: str = "fail",
                strict: bool = False, overwrite: bool = False):
    """Write the result next to the target (`<name>_sheetcopy.<ext>` by default). Never writes over the target
    or the source; an existing output only with `overwrite=True`. Returns `(path, report)`."""
    tp = _parser(target)
    tpath = Path(tp.twbx_path or tp.path)
    out = Path(output_path) if output_path else tpath.with_name(f"{tpath.stem}_sheetcopy{tpath.suffix}")
    if out.suffix.lower() != tpath.suffix.lower():
        raise SheetCopyAbort(f"output must end in {tpath.suffix}, got {out.suffix or 'no extension'}")
    sp = _parser(source)
    for p in (tpath, Path(sp.twbx_path or sp.path)):
        if out.exists() and out.resolve() == p.resolve():
            raise FileExistsError(f"refusing to overwrite an input: {out}")
    if out.exists() and not overwrite:
        raise FileExistsError(f"refusing to overwrite existing file: {out}")
    data, report = build_sheet_copy(sp, tp, sheets, on_clash, strict)
    if report["copied"] == 0:
        raise SheetCopyAbort("no sheet could be copied; nothing written")
    with open(out, "wb" if overwrite else "xb") as fh:
        fh.write(data)
    return str(out), report


def format_report(report: dict) -> str:
    lines = [f"sheet copy: {report['source']} -> {report['target']} (on clash: {report['on_clash']})", ""]
    for r in report["sheets"]:
        shown = r["sheet"] + (f" -> {r['new_name']}" if r["new_name"] != r["sheet"] and r["status"] == "copy" else "")
        lines.append(f"  {r['status']:8} {shown}" + (f"  [{r['datasource']}]" if r["datasource"] else ""))
        if r["reason"]:
            lines.append(f"           {r['reason']}")
        for d in r["dropped"]:
            lines.append(f"           dropped: {d}")
    if report["library"]:
        lines += ["", "calculations and parameters:"]
        for r in report["library"]:
            lines.append(f"  {r['action']:15} {r['kind']:11} {r['caption'] or _unbracket(r['name'])}"
                         + (f"  ({r['reason']})" if r["reason"] else ""))
    lines += ["", f"{report['copied']} to copy, {report['skipped']} skipped, {report['refused']} refused"]
    return "\n".join(lines)
