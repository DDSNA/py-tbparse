"""`slice`: keep selected dashboards of a workbook and drop the rest (WP14d).

Not part of the R package. The command is called `slice`, not `extract`, because `extract` means a Tableau
data extract (`.hyper`) everywhere else in this package.

What is kept: the named dashboards, every worksheet they show, and (until nothing new is added) every
dashboard or worksheet that a kept dashboard or worksheet names: a story's captured sheets, a viz in a
tooltip, a nested dashboard. This is read from exact attribute values and `<Sheet name="..">` in tooltip
text of what is kept, so doubt keeps a sheet. Everything else goes: the other dashboards, the other
worksheets (also hidden ones; the audit's A006 would spare those), and their windows and thumbnail records,
and any viewpoint of a removed sheet in a window that stays.

Actions: an action whose source or target is a dashboard or worksheet that did not stay is dropped, and so is
the `user:ui-action-filter` filter, in a kept sheet, that it drove. Both are reported. `strict=True` refuses
to slice instead of dropping anything. A removed sheet named in an action's `exclude` list is trimmed from the
list (reported as such).

Then `prune_doc` runs with sheets, calculations, parameters and datasources, so calculations, parameters and
datasources that only removed sheets used go too and nothing is left dangling (`prune=False` skips this).
The result is compared with the input by `dashboards.integrity_check`: problems that are new are returned
under `integrity_new`. The XML-schema comparison is done by the tests (`tests/schema_check.py`), not here.

What is not known: whether Tableau opens the result (nothing was opened in Tableau Desktop), and what the
`.twbx` members hold: thumbnails and extracts of removed sheets stay in the package.
"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Iterable, Optional, Union

from .dashboards import integrity_check
from .parser import TwbParser
from .prune import _drop, _el_values, prune_doc
from .rename import _serialize_workbook
from .templates import _write_new


class SliceError(ValueError):
    pass


_USER_NS = "http://www.tableausoftware.com/xml/user"
_ACTION_FILTER = f"{{{_USER_NS}}}ui-action-filter"


def _names(value: Union[str, Iterable[str]], valid: list[str]) -> list[str]:
    """Dashboard names from a list, or from one comma-separated string (a string that is itself a dashboard
    name is taken whole, so a name with a comma works when it is the only one)."""
    items = [value] if isinstance(value, str) else list(value)
    out: list[str] = []
    for item in items:
        parts = [item] if item in valid else [p.strip() for p in item.split(",")]
        out.extend(p for p in parts if p)
    return list(dict.fromkeys(out))


def _kept_closure(doc, dashboards: list[str]) -> tuple[set, set]:
    """(kept dashboards, kept worksheets): the named dashboards and everything they name, transitively."""
    sheets = set(doc.xpath("/workbook/worksheets/worksheet/@name"))
    dbs = set(doc.xpath("/workbook/dashboards/dashboard/@name"))
    known = sheets | dbs
    keep_d, keep_s = set(), set()
    todo = list(dashboards)
    while todo:
        name = todo.pop()
        if name in keep_d or name in keep_s:
            continue
        if name in dbs:
            keep_d.add(name)
            els = doc.xpath("/workbook/dashboards/dashboard[@name=$n]", n=name)
        else:
            keep_s.add(name)
            els = doc.xpath("/workbook/worksheets/worksheet[@name=$n]", n=name)
        for root in els:
            for el in root.iter():
                if isinstance(el.tag, str):
                    todo.extend(v for v in _el_values(el) if v in known and v != name)
    return keep_d, keep_s


def _param_values(action, name: str) -> list:
    return action.xpath("./command/param[@name=$n]", n=name)


def _plan_actions(doc, gone: set) -> tuple[list[dict], list[dict]]:
    """(dropped actions, trimmed actions). An action goes when its source or a target names
    something in `gone`."""
    dropped, trimmed = [], []
    for act in doc.xpath("/workbook/actions/action"):
        name = act.get("name") or ""
        label = act.get("caption") or name
        why = None
        for src in act.xpath("./source"):
            for attr in ("dashboard", "worksheet"):
                if src.get(attr) in gone:
                    why = f"its source {attr} {src.get(attr)!r} is not kept"
        for p in act.xpath("./command/param[@name='target' or @name='sheet']"):
            if why is None and p.get("value") in gone:
                why = f"its target {p.get('value')!r} is not kept"
        if why:
            dropped.append({"name": name, "caption": label, "reason": why, "element": act})
            continue
        for p in _param_values(act, "exclude"):
            toks = [t for t in (p.get("value") or "").split(",")]
            keep = [t for t in toks if t not in gone]
            if keep != toks:
                trimmed.append({"name": name, "caption": label,
                                "reason": "removed sheet(s) taken out of its exclude list: "
                                          + ", ".join(sorted(set(toks) - set(keep))),
                                "element": p, "keep": keep})
    return dropped, trimmed


def slice_doc(doc, dashboards: Union[str, Iterable[str]], strict: bool = False, prune: bool = True) -> dict:
    """Slice a parsed workbook document IN PLACE (an lxml tree or the `<workbook>` element; pass a copy to
    keep the original). Keeps `dashboards` (a list, or a comma-separated string) and what they need, drops
    the rest, then prunes (see the module text). Nothing is read or written on disk.

    Raises `SliceError` for no dashboard named, an unknown name (the message lists the valid ones), a selection that shows no worksheet, or, with
    `strict`, when any action or action filter would have to be dropped (nothing is changed then).

    Returns `kept_dashboards`, `kept_sheets`, `removed_dashboards`, `removed_sheets`, `dropped_actions`
    (`name`, `caption`, `reason`), `trimmed_actions`, `dropped_filters` (count), `prune` (the `prune_doc`
    report, or None) and `integrity_new` (integrity problems the output has and the input did not)."""
    if not hasattr(doc, "getroot"):
        doc = doc.getroottree()
    valid = doc.xpath("/workbook/dashboards/dashboard/@name")
    wanted = _names(dashboards, valid)
    if not wanted:
        raise SliceError("no dashboard named; give at least one with --dashboards")
    unknown = [n for n in wanted if n not in valid]
    if unknown:
        raise SliceError(f"unknown dashboard(s): {', '.join(repr(n) for n in unknown)}; "
                         f"valid dashboards: {', '.join(repr(n) for n in valid) or '(none)'}")
    before = {(p["check"], p["dashboard"], p["detail"]) for p in integrity_check(doc)}

    keep_d, keep_s = _kept_closure(doc, wanted)
    if not keep_s:
        raise SliceError(f"the selected dashboard(s) {', '.join(repr(n) for n in wanted)} show no worksheet "
                         "(an empty story, for one); a workbook needs at least one worksheet, so nothing is sliced")
    all_s = doc.xpath("/workbook/worksheets/worksheet/@name")
    gone_d = [n for n in valid if n not in keep_d]
    gone_s = [n for n in all_s if n not in keep_s]
    gone = set(gone_d) | set(gone_s)

    dropped, trimmed = _plan_actions(doc, gone)
    dropped_names = {d["name"] for d in dropped}
    filters = []
    if dropped_names:
        for el in doc.xpath("//*[@*[local-name()='ui-action-filter']]"):
            if el.get(_ACTION_FILTER) in dropped_names:
                f = next((a for a in el.iterancestors("filter")), None)
                if f is not None and f not in filters and not any(x in gone for x in [
                        a.get("name") for a in f.iterancestors("worksheet", "dashboard")]):
                    filters.append(f)
    if strict and (dropped or filters):
        lines = [f"{d['caption']} ({d['reason']})" for d in dropped]
        if filters:
            lines.append(f"{len(filters)} filter(s) driven by those actions")
        raise SliceError("--strict: slicing would drop " + "; ".join(lines))

    for d in dropped:
        _drop(d["element"])
    for t in trimmed:
        if t["keep"]:
            t["element"].set("value", ",".join(t["keep"]))
        else:
            _drop(t["element"])
    for f in filters:
        _drop(f)
    for name in gone_d:
        for el in doc.xpath("/workbook/dashboards/dashboard[@name=$n]", n=name):
            _drop(el)
    for name in gone_s:
        for el in doc.xpath("/workbook/worksheets/worksheet[@name=$n]", n=name):
            _drop(el)
    for name in gone:
        for el in doc.xpath("/workbook/windows/window[@name=$n] | /workbook/thumbnails/thumbnail[@name=$n]", n=name):
            _drop(el)
        for el in doc.xpath("/workbook/windows/window//viewpoint[@name=$n]", n=name):
            _drop(el)

    report = prune_doc(doc, sheets=True, datasources=True) if prune else None
    after = integrity_check(doc)
    new = [p for p in after if (p["check"], p["dashboard"], p["detail"]) not in before]
    clean = lambda rows: [{k: v for k, v in r.items() if k != "element"} for r in rows]    # noqa: E731
    return {"kept_dashboards": [n for n in valid if n in keep_d], "kept_sheets": [n for n in all_s if n in keep_s],
            "removed_dashboards": gone_d, "removed_sheets": gone_s,
            "dropped_actions": clean(dropped), "trimmed_actions": clean(trimmed),
            "dropped_filters": len(filters), "prune": report, "integrity_new": new}


def slice_workbook(
    workbook: Union[TwbParser, str],
    dashboards: Union[str, Iterable[str]],
    output_path: Optional[str] = None,
    strict: bool = False,
    prune: bool = True,
    overwrite: bool = False,
) -> dict:
    """Slice a workbook (a path or a `TwbParser`); see `slice_doc`. Without `output_path` nothing is written
    (a dry run); with it a NEW file is written, in the input's format, and the input is never touched; an
    existing output is refused unless `overwrite=True`. A result with new integrity problems is not written.
    Returns the report of `slice_doc` plus `dry_run`, `output` and `input`."""
    if not isinstance(workbook, TwbParser):
        workbook = TwbParser(str(workbook))
    out = None
    if output_path is not None:
        out = Path(output_path)
        source = Path(workbook.twbx_path or workbook.path)
        if out.suffix.lower() != source.suffix.lower():
            raise SliceError(f"the output must end in {source.suffix}, got {out.suffix or 'no extension'}")
        if out.exists() and source.exists() and (out.resolve() == source.resolve() or out.samefile(source)):
            raise FileExistsError(f"refusing to overwrite the input workbook: {out}")
        if out.exists() and not overwrite:
            raise FileExistsError(f"refusing to overwrite existing file: {out} (use --overwrite)")
    doc = copy.deepcopy(workbook.xml_doc)
    report = slice_doc(doc, dashboards, strict=strict, prune=prune)
    report.update({"dry_run": out is None, "output": None, "input": str(workbook.twbx_path or workbook.path)})
    if out is not None:
        if report["integrity_new"]:
            raise SliceError("the result has new integrity problems, nothing written: "
                             + "; ".join(f"{p['check']}: {p['detail']}" for p in report["integrity_new"]))
        _write_new(out, _serialize_workbook(workbook, doc), overwrite)
        report["output"] = str(out)
    return report


def format_report(report: dict) -> str:
    verb = "would keep" if report["dry_run"] else "kept"
    lines = [f"{verb} {len(report['kept_dashboards'])} dashboard(s): {', '.join(report['kept_dashboards'])}",
             f"{verb} {len(report['kept_sheets'])} worksheet(s)",
             f"{'would remove' if report['dry_run'] else 'removed'} {len(report['removed_dashboards'])} dashboard(s) "
             f"and {len(report['removed_sheets'])} worksheet(s)"]
    for a in report["dropped_actions"]:
        lines.append(f"dropped action  {a['caption']}: {a['reason']}")
    for a in report["trimmed_actions"]:
        lines.append(f"trimmed action  {a['caption']}: {a['reason']}")
    if report["dropped_filters"]:
        lines.append(f"dropped {report['dropped_filters']} filter(s) in kept sheets that were driven by dropped actions")
    p = report["prune"]
    if p:
        c = p["counts"]
        lines.append(f"then pruned: {c['calculations']} calculation(s), {c['parameters']} parameter(s), "
                     f"{c['sheets']} sheet(s), {c['datasources']} datasource(s)")
    for i in report["integrity_new"]:
        lines.append(f"INTEGRITY  {i['check']}: {i['detail']}")
    lines.append("dry run: nothing was written (use --write -o OUT)" if report["dry_run"]
                 else f"wrote {report['output']}")
    return "\n".join(lines)
