"""`dashboard copy` (WP14f): copy dashboards, with every sheet on them, from one workbook into another.

Built on `sheetcopy._run` (sheets, calculations, parameters, windows: all its rules and refusals apply to the
sheets of a dashboard) and on `sheetcopy_core`. Rules of this slice (owner decisions 2026-10-06):

* Every datasource the dashboard or its sheets use must match a target datasource by connection AND internal
  name. One sheet that cannot be copied refuses the whole dashboard; sheets that only that dashboard needed are
  then not copied either.
* The dashboard's own `<datasources>` and `<datasource-dependencies>` (filter, parameter and legend zones) are
  rewritten like a sheet's; what they name must exist in the target.
* Actions are copied when their source and all their targets are in the copied set (the copied dashboards and
  sheets). Actions that touch the set but also something outside it are dropped and reported; `strict` refuses.
  The filter state an action left on a sheet (`[Action (...)]` filters) is dropped as in `sheet copy`.
* A new dashboard window (a copy of the source one: new uuids, renamed viewpoints), new uuids everywhere.
* `on_clash` is `fail` (default; no overwrite policy exists), `rename` or `skip`, for dashboard names as for
  sheet names, calculations and parameters. `fail` stops the whole run before anything is written.
* The result must pass `integrity_check` with nothing new.
* Not copied: thumbnails, stories, blends, datasources the target lacks, sets/groups/bins to add.

Never opened in Tableau Desktop; keep saying so.
"""

from __future__ import annotations

import copy
import re
import uuid
from pathlib import Path
from typing import Iterable, Optional
from urllib.parse import quote

from lxml import etree

from .dashboards import _SHEET_ZONE_TYPES, _dashboard_xpath, dashboard_targets, integrity_check, zone_kind
from .library import CLASH_POLICIES, _PARAMETERS
from .rename import _serialize_workbook
from .sheetcopy import SheetCopyAbort, _free_name, _parser, _run
from .sheetcopy_core import (
    _ACTION_GROUP, _BUILTIN, SheetCopyError, _base_of_instance, add_window, match_datasource, new_uuid,
    renew_uuids, rewrite_references, windows_element,
)
from .usage import _datasource_fields

_BAD_STATUS = ("refused", "skipped")


def _action_sets(action) -> tuple[Optional[str], Optional[str], list[str], bool]:
    """`(source dashboard, source worksheet, targets, has_source)` of an action."""
    src = action.find("source")
    sd = src.get("dashboard") if src is not None else None
    sw = src.get("worksheet") if src is not None else None
    targets = [p.get("value") for p in action.xpath("./command/param[@name='target']") if p.get("value")]
    return sd, sw, targets, bool(sd or sw)


def _plan_actions(sdoc, dashboards: set, sheets: set) -> tuple[list, list]:
    """`(carried action elements, report rows)` for the copied set of source names."""
    carried, rows = [], []
    for a in sdoc.xpath("/workbook/actions/action"):
        sd, sw, targets, has_source = _action_sets(a)
        names = {x for x in [sd, sw, *targets] if x}
        if not names & (dashboards | sheets):
            continue
        row = {"name": a.get("name"), "caption": a.get("caption") or "", "status": "copy", "reason": ""}
        outside = []
        if sd and sd not in dashboards:
            outside.append(f"source dashboard {sd!r}")
        if sw and sw not in sheets:
            outside.append(f"source sheet {sw!r}")
        outside += [f"target {t!r}" for t in targets if t not in dashboards and t not in sheets]
        if not has_source:
            outside.append("no source dashboard or sheet")
        if outside:
            row.update(status="dropped", reason="not in the copied set: " + ", ".join(outside))
        else:
            carried.append(a)
        rows.append(row)
    return carried, rows


def _copy_action(a, dbmap: dict, sheetmap: dict, taken_names: set):
    el = copy.deepcopy(a)
    src = el.find("source")
    if src is not None:
        if src.get("dashboard") in dbmap:
            src.set("dashboard", dbmap[src.get("dashboard")])
        if src.get("worksheet") in sheetmap:
            src.set("worksheet", sheetmap[src.get("worksheet")])
    for p in el.xpath("./command/param[@name='target']"):
        v = p.get("value")
        if v in dbmap:
            p.set("value", dbmap[v])
        elif v in sheetmap:
            p.set("value", sheetmap[v])
    for link in el.iter("link"):
        expr = link.get("expression")
        if not expr:
            continue
        for old, new in {**dbmap, **sheetmap}.items():
            if old != new:
                expr = expr.replace("tsl:" + quote(old, safe="") + "?", "tsl:" + quote(new, safe="") + "?")
        link.set("expression", expr)
    name = el.get("name")
    if name in taken_names:
        m = re.match(r"^\[Action(\d+)_", name or "")
        n = int(m.group(1)) if m else len(taken_names) + 1
        while True:
            fresh = f"[Action{n}_{uuid.uuid4().hex.upper()}]"
            if fresh not in taken_names:
                break
            n += 1
        el.set("name", fresh)
    taken_names.add(el.get("name"))
    return el


def _analyse(sdoc, name: str) -> dict:
    """What the source dashboard shows and uses; `reason` when it cannot be copied at all."""
    db = sdoc.xpath(_dashboard_xpath(name))[0]
    sheets_in_src = set(sdoc.xpath("/workbook/worksheets/worksheet/@name"))
    dashes_in_src = set(sdoc.xpath("/workbook/dashboards/dashboard/@name"))
    sheets = list(dict.fromkeys(t for t in dashboard_targets(db) if t))
    info = {"sheets": sheets, "datasources": [], "reason": ""}
    other = [s for s in sheets if s not in sheets_in_src]
    if other:
        what = "another dashboard" if all(s in dashes_in_src for s in other) else "a name that is not a worksheet"
        info["reason"] = f"a zone shows {what}: " + ", ".join(repr(s) for s in other)
        return info
    ds = [n for n in db.xpath("./datasources/datasource/@name") + db.xpath("./datasource-dependencies/@datasource")
          if n != _PARAMETERS]
    info["datasources"] = list(dict.fromkeys(ds))
    return info


def _dashboard_needs(sdoc, name: str, info: dict) -> dict:
    """The calculations and parameters the dashboard's own dependencies name (filter, parameter and legend
    zones), as `{datasource: [names]}` for `_run(extra=...)`: calculations under their datasource, parameters
    (bare names) under the dashboard's first datasource. The planner skips what the sheets already bring or
    the target already has."""
    db = sdoc.xpath(_dashboard_xpath(name))[0]
    out: dict = {}
    pcols = set(sdoc.xpath("/workbook/datasources/datasource[@name=$n]/column/@name", n=_PARAMETERS))
    first = info["datasources"][0] if info["datasources"] else None
    for dep in db.xpath("./datasource-dependencies"):
        ds = dep.get("datasource")
        bases = []
        for col in dep:
            if isinstance(col.tag, str):
                ref = col.get("name") if col.tag == "column" else col.get("column")
                if ref:
                    bases.append(_base_of_instance(ref))
        if ds == _PARAMETERS:
            if first:
                out.setdefault(first, []).extend(b for b in bases if b in pcols)
            continue
        found = sdoc.xpath("/workbook/datasources/datasource[@name=$n]", n=ds)
        if not found:
            continue
        calcs = {c.get("name") for c in found[0].xpath("./column[calculation/@class='tableau']")
                 if not c.get("param-domain-type")}
        out.setdefault(ds, []).extend(b for b in bases if b in calcs)
    return {k: list(dict.fromkeys(v)) for k, v in out.items() if v}


def _need_keys(sdoc, name: str, info: dict) -> set:
    """`_dashboard_needs` as the keys the planner reports: `[Calc]`, `[Parameters].[Param]`."""
    pcols = set(sdoc.xpath("/workbook/datasources/datasource[@name=$n]/column/@name", n=_PARAMETERS))
    out = set()
    for ns in _dashboard_needs(sdoc, name, info).values():
        out |= {("[Parameters]." + n) if n in pcols and not _is_calc_name(sdoc, n) else n for n in ns}
    return out


def _is_calc_name(sdoc, n: str) -> bool:
    return bool(sdoc.xpath("/workbook/datasources/datasource[@name!='Parameters']/column[@name=$n]"
                           "[calculation/@class='tableau']", n=n))


def _available(doc, ds: str) -> set:
    if ds == _PARAMETERS:
        return set(doc.xpath("/workbook/datasources/datasource[@name=$n]/column/@name", n=_PARAMETERS))
    node = doc.xpath("/workbook/datasources/datasource[@name=$n]", n=ds)
    if not node:
        return set()
    return (set(_datasource_fields(node[0])) | set(node[0].xpath("./column/@name"))
            | set(node[0].xpath("./group/@name")))


def _build_dashboard(sdoc, doc, name: str, new_name: str, info: dict, sheetmap: dict, names: dict, params: dict,
                     taken: set):
    """`(dashboard element, reason)`: a rewritten copy of the source dashboard, or why the target cannot take it."""
    el = copy.deepcopy(sdoc.xpath(_dashboard_xpath(name))[0])
    el.set("name", new_name)
    renew_uuids(el, taken)
    for z in el.xpath(".//zone[@name or @worksheet]"):
        if zone_kind(z) in _SHEET_ZONE_TYPES:
            for attr in ("name", "worksheet"):
                if z.get(attr) in sheetmap:
                    z.set(attr, sheetmap[z.get(attr)])
    merged_params: dict = {}
    for d in info["datasources"]:
        merged_params.update(params.get(d, {}))
    first = True
    for d in info["datasources"]:
        rewrite_references(el, {d: d}, names.get(d, {}), merged_params if first else None)
        first = False
    if first and merged_params:
        rewrite_references(el, {}, {}, merged_params)
    for dep in el.xpath("./datasource-dependencies"):
        ds = dep.get("datasource")
        have = _available(doc, ds)
        miss = []
        for col in dep:
            if not isinstance(col.tag, str):
                continue
            ref = col.get("name") if col.tag == "column" else col.get("column")
            if not ref:
                continue
            base = _base_of_instance(ref)
            if base in have or _ACTION_GROUP.match(base) or (_BUILTIN.match(base) and ds != _PARAMETERS):
                continue
            miss.append(base)
        if miss:
            return None, (f"the target's {ds!r} lacks " + ", ".join(dict.fromkeys(miss))
                          + " (named by a filter, parameter or legend zone of the dashboard)")
    return el, ""


def _run_dashboards(source, target, dashboards: Iterable[str], on_clash: str = "fail", strict: bool = False):
    if on_clash not in CLASH_POLICIES:
        raise SheetCopyAbort(f"on_clash must be one of {', '.join(CLASH_POLICIES)}, got {on_clash!r}")
    src, dst = _parser(source), _parser(target)
    sdoc = src.xml_doc
    wanted = list(dict.fromkeys(dashboards))
    if not wanted:
        raise SheetCopyAbort("no dashboards named; use --dashboards A,B")
    have = set(sdoc.xpath("/workbook/dashboards/dashboard/@name"))
    unknown = [d for d in wanted if d not in have]
    if unknown:
        raise SheetCopyAbort("the source has no dashboard named " + ", ".join(repr(d) for d in unknown))

    results = {d: {"dashboard": d, "status": "copy", "new_name": d, "sheets": [], "datasources": [], "reason": "",
                   "dropped": []} for d in wanted}
    info = {}
    target_names = set(dst.xml_doc.xpath("/workbook/worksheets/worksheet/@name")) | set(
        dst.xml_doc.xpath("/workbook/dashboards/dashboard/@name"))
    for d in wanted:
        info[d] = _analyse(sdoc, d)
        results[d].update(sheets=info[d]["sheets"], datasources=info[d]["datasources"])
        if info[d]["reason"]:
            results[d].update(status="refused", reason=info[d]["reason"])
            continue
        probe = copy.deepcopy(dst.xml_doc)
        try:
            for ds in info[d]["datasources"]:
                match_datasource(sdoc, ds, probe)
        except SheetCopyError as e:
            results[d].update(status="refused", reason=str(e))
            continue
        if d in target_names:
            if on_clash == "fail":
                raise SheetCopyAbort(f"{d!r} is already a sheet or dashboard of the target (on_clash='fail')")
            if on_clash == "skip":
                results[d].update(status="skipped", reason="the target already has a sheet or dashboard of that name")

    while True:
        live = [d for d in wanted if results[d]["status"] == "copy"]
        sheets = list(dict.fromkeys(s for d in live for s in info[d]["sheets"]))
        ctx: dict = {}
        extra: dict = {}
        for d in live:
            for ds, ns in _dashboard_needs(sdoc, d, info[d]).items():
                extra.setdefault(ds, []).extend(ns)
        doc, rep = _run(src, dst, sheets, on_clash, False, ctx, report_actions=False, allow_empty=True,
                        extra=extra)
        sres = ctx.get("results", {})
        changed = False
        failed = {k: v for f in ctx.get("failed", {}).values() for k, v in f.items()}
        for d in live:
            keys = _need_keys(sdoc, d, info[d])
            hit = [k for k in failed if k in keys]
            if hit:
                results[d].update(status="refused", reason="not importable: " + "; ".join(
                    f"{k} ({failed[k]['reason']})" for k in hit))
                changed = True
        if changed:
            continue
        for d in live:
            bad = [s for s in info[d]["sheets"] if sres[s]["status"] != "copy"]
            if bad:
                s = bad[0]
                results[d].update(status="skipped" if sres[s]["status"] == "skipped" else "refused",
                                  reason=f"sheet {s!r}: {sres[s]['reason']}")
                changed = True
        if changed:
            continue
        sheetmap = {s: sres[s]["new_name"] for s in sheets}
        taken = ctx.get("taken", set(doc.xpath("//simple-id/@uuid")))
        used = set(doc.xpath("/workbook/worksheets/worksheet/@name")) | set(
            doc.xpath("/workbook/dashboards/dashboard/@name"))
        built = {}
        for d in live:
            new = d if d not in used else _free_name(d, used)
            results[d]["new_name"] = new
            used.add(new)
            el, why = _build_dashboard(sdoc, doc, d, new, info[d], sheetmap, ctx.get("names", {}),
                                       ctx.get("params", {}), taken)
            if el is None:
                results[d].update(status="refused", reason=why)
                changed = True
            else:
                built[d] = el
        if not changed:
            break

    live = [d for d in wanted if results[d]["status"] == "copy"]
    for d in live:
        for s in info[d]["sheets"]:
            results[d]["dropped"] += [f"{s}: {x}" for x in sres[s]["dropped"]]

    # actions internal to the copied set
    dbmap = {d: results[d]["new_name"] for d in live}
    carried, action_rows = _plan_actions(sdoc, set(dbmap), set(sheetmap))
    for row in action_rows:
        if row["status"] == "dropped":
            for d in live:
                results[d]["dropped"].append(f"action {row['caption'] or row['name']}: {row['reason']}")
            break
    if strict and any(results[d]["dropped"] for d in live):
        what = "; ".join(f"{d}: {', '.join(results[d]['dropped'])}" for d in live if results[d]["dropped"])
        raise SheetCopyAbort("--strict: the copy would drop " + what)

    # write into the working copy
    if live:
        tdash = doc.find("dashboards")
        if tdash is None:
            tdash = etree.Element("dashboards")
            doc.find("worksheets").addnext(tdash)
        windows = windows_element(doc)
        for d in live:
            tdash.append(built[d])
            new = results[d]["new_name"]
            found = sdoc.xpath("/workbook/windows/window[@class='dashboard'][@name=$n]", n=d)
            if found:
                win = copy.deepcopy(found[0])
                win.set("name", new)
                renew_uuids(win, taken)
                for vp in win.xpath("./viewpoints/viewpoint[@name]"):
                    vp.set("name", sheetmap.get(vp.get("name"), vp.get("name")))
                windows.append(win)
            else:
                add_window(doc, "dashboard", new, [sheetmap[s] for s in info[d]["sheets"]], new_uuid(taken))
        for s, new in sheetmap.items():           # the sheets of a dashboard are hidden in the source, so here
            srcwin = sdoc.xpath("/workbook/windows/window[@class='worksheet'][@name=$n]", n=s)
            if srcwin and srcwin[0].get("hidden") == "true":
                for w in doc.xpath("/workbook/windows/window[@class='worksheet'][@name=$n]", n=new)[-1:]:
                    w.set("hidden", "true")
    if carried:
        acts = doc.find("actions")
        if acts is None:
            acts = etree.Element("actions")
            doc.find("worksheets").addprevious(acts)
        have_names = set(doc.xpath("/workbook/actions/action/@name"))
        for a in carried:       # the schema wants `action` before `edit-parameter-action`
            new_action = _copy_action(a, dbmap, sheetmap, have_names)
            last = acts.xpath("./action[last()]")
            if last:
                last[0].addnext(new_action)
            else:
                acts.insert(0, new_action)
    if doc.find("worksheets") is not None and len(doc.find("worksheets")) == 0 \
            and dst.xml_doc.find("worksheets") is None:
        doc.remove(doc.find("worksheets"))

    # the result must hold together
    problems = integrity_check(doc)
    before = integrity_check(dst.xml_doc)
    new = [p for p in problems if p not in before]
    if new:
        raise SheetCopyAbort("integrity check failed on the result: "
                             + "; ".join(p["check"] + " " + p["detail"] for p in new))

    out = [results[d] for d in wanted]
    report = {
        "source": str(src.twbx_path or src.path), "target": str(dst.twbx_path or dst.path), "on_clash": on_clash,
        "dashboards": out, "sheets": rep["sheets"] if live else [], "library": rep["library"] if live else [],
        "actions": action_rows if live else [], "added": rep["added"] if live else [],
        "copied": sum(r["status"] == "copy" for r in out),
        "skipped": sum(r["status"] == "skipped" for r in out),
        "refused": sum(r["status"] == "refused" for r in out),
    }
    return doc, report


def plan_dashboard_copy(source, target, dashboards: Iterable[str], on_clash: str = "fail",
                        strict: bool = False) -> dict:
    """What `build_dashboard_copy` would do: a report dict (`dashboards`, `sheets`, `library`, `actions`, counts).
    Nothing is written. Raises `SheetCopyAbort` for what stops a whole run."""
    return _run_dashboards(source, target, dashboards, on_clash, strict)[1]


def build_dashboard_copy(source, target, dashboards: Iterable[str], on_clash: str = "fail", strict: bool = False):
    """`(bytes, report)`: the target workbook with the dashboards added, in the target's format."""
    tp = _parser(target)
    doc, report = _run_dashboards(source, tp, dashboards, on_clash, strict)
    return _serialize_workbook(tp, doc), report


def copy_dashboards(source, target, dashboards: Iterable[str], output_path: Optional[str] = None,
                    on_clash: str = "fail", strict: bool = False, overwrite: bool = False):
    """Write the result next to the target (`<name>_dashcopy.<ext>` by default). Never writes over the target or
    the source; an existing output only with `overwrite=True`. Returns `(path, report)`."""
    tp = _parser(target)
    tpath = Path(tp.twbx_path or tp.path)
    out = Path(output_path) if output_path else tpath.with_name(f"{tpath.stem}_dashcopy{tpath.suffix}")
    if out.suffix.lower() != tpath.suffix.lower():
        raise SheetCopyAbort(f"output must end in {tpath.suffix}, got {out.suffix or 'no extension'}")
    sp = _parser(source)
    for p in (tpath, Path(sp.twbx_path or sp.path)):
        if out.exists() and out.resolve() == p.resolve():
            raise FileExistsError(f"refusing to overwrite an input: {out}")
    if out.exists() and not overwrite:
        raise FileExistsError(f"refusing to overwrite existing file: {out}")
    data, report = build_dashboard_copy(sp, tp, dashboards, on_clash, strict)
    if report["copied"] == 0:
        raise SheetCopyAbort("no dashboard could be copied; nothing written")
    with open(out, "wb" if overwrite else "xb") as fh:
        fh.write(data)
    return str(out), report


def format_report(report: dict) -> str:
    lines = [f"dashboard copy: {report['source']} -> {report['target']} (on clash: {report['on_clash']})", ""]
    for r in report["dashboards"]:
        shown = r["dashboard"] + (f" -> {r['new_name']}" if r["new_name"] != r["dashboard"] and r["status"] == "copy"
                                  else "")
        lines.append(f"  {r['status']:8} {shown}  ({len(r['sheets'])} sheet(s))")
        if r["reason"]:
            lines.append(f"           {r['reason']}")
        for d in r["dropped"]:
            lines.append(f"           dropped: {d}")
    if report["sheets"]:
        lines += ["", "sheets:"]
        for r in report["sheets"]:
            lines.append(f"  {r['status']:8} {r['sheet']}"
                         + (f" -> {r['new_name']}" if r["new_name"] != r["sheet"] and r["status"] == "copy" else ""))
    if report["actions"]:
        lines += ["", "actions:"]
        for r in report["actions"]:
            lines.append(f"  {r['status']:8} {r['caption'] or r['name']}" + (f"  ({r['reason']})" if r["reason"] else ""))
    if report["added"]:
        lines += ["", "calculations and parameters added:"]
        for r in report["added"]:
            lines.append(f"  {r['kind']:11} {r['caption'] or r['name']}")
    lines += ["", f"{report['copied']} to copy, {report['skipped']} skipped, {report['refused']} refused"]
    return "\n".join(lines)
