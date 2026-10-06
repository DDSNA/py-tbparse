"""`prune`: remove what the audit proves unused, safely (WP10b).

Not part of the R package. It takes its candidates from the audit's own lists, so the two cannot disagree:
`workbook_audit.unused_calculations` (A001), `unused_parameters` (A005) and, only on request,
`sheets_in_no_dashboard` (A006). No rule logic is repeated here.

A candidate is removed only if nothing that stays refers to it. The check is deliberately cruder than the
audit's: after the candidates' own traces are set aside, every attribute value and text of the rest of the
workbook is read for `[Name]` (also inside `[ds].[Name]` and `[none:Name:nk]`), so a calculation, set, group,
bin, action, filter, dashboard, window entry or extract that still names a candidate keeps it. A candidate
that is kept goes back in the pool and what it refers to is checked again, until nothing changes (a fixpoint).
The check is by name over the whole workbook, not by datasource: a same-named field of another datasource
keeps a candidate too. Wrong in that direction means "not removed", never "removed wrongly".

Own traces of a calculation or parameter, removed with it: its `<column>` (captions, aliases and the
calculation inside it), the `<column-instance>` of it, a `metadata-record` of it outside an extract, its
`folder-item`, its field in a hierarchy (`drill-path`), its colour or format entry in the datasource's
`<style>`, and its entry in a datasource's `<datasource-dependencies>`. A hierarchy that loses a field stays,
even with one field left; an emptied folder stays. A worksheet's traces are the worksheet, its window and its
thumbnail record. A field stored in an extract (`extract/connection`) is never removed: the extract file
would still have it.

What is not known: whether Tableau opens the result (nothing was tried in Tableau Desktop), whether another
workbook or a published datasource uses the field, and what the `.twbx` members (thumbnails, extracts) hold.
"""

from __future__ import annotations

import copy
import io
import re
from pathlib import Path
from typing import Optional, Union

from lxml import etree

from .findings import Subject
from .parser import TwbParser
from .rename import _serialize_workbook
from .templates import _write_new
from .workbook_audit import _Facts, sheets_in_no_dashboard, unused_calculations, unused_parameters

CATEGORIES = ("calculations", "parameters", "sheets")

TRACE_KINDS = ("columns", "column_instances", "metadata_records", "folder_items", "hierarchy_fields",
               "style_entries", "dependency_entries", "sheets", "windows", "thumbnails")


class PruneError(ValueError):
    pass


class _DocParser:
    """Just enough of a `TwbParser` for the audit's `_Facts`: the XML document."""

    def __init__(self, doc):
        self.xml_doc = doc


_BRACKETED = re.compile(r"\[((?:[^\]]|\]\])+)\]")
_SHEET_IN_TEXT = re.compile(r"<Sheet\s+name=\"([^\"]+)\"")


def _names_in(text: Optional[str]) -> set:
    """Names a value or text mentions: `[Name]` and the middle of `[none:Name:nk]` or `[pcrk:sum:Name:qk]`."""
    out: set = set()
    for m in _BRACKETED.finditer(text or ""):
        inner = m.group(1)
        out.add(inner)
        parts = inner.split(":")
        for i in range(1, len(parts) - 1):
            out.add(":".join(parts[i:-1]))
    return out


def _el_names(el) -> set:
    """Names mentioned by one element's own attribute values and text (not its children's)."""
    out: set = set()
    for v in el.attrib.values():
        if "[" in v:
            out |= _names_in(v)
    if el.text and "[" in el.text:
        out |= _names_in(el.text)
    return out


def _el_values(el) -> set:
    """Exact attribute values and stripped text of one element, for sheet names."""
    out = set(el.attrib.values())
    if el.text and el.text.strip():
        out.add(el.text.strip())
        out |= set(_SHEET_IN_TEXT.findall(el.text))
    return out


def _where(el) -> str:
    """Where an element is: the tag, and the name of it or of its nearest named ancestor."""
    tag = el.tag if isinstance(el.tag, str) else "comment"
    for a in [el, *el.iterancestors()]:
        if isinstance(a.tag, str) and a.get("name") and a.tag in (
                "column", "group", "worksheet", "dashboard", "window", "action", "datasource", "folder",
                "drill-path", "story-point", "thumbnail"):
            who = a.get("caption") or a.get("name")
            return f"<{tag}> in {a.tag} {who}"
    return f"<{tag}>"


def _drop(el) -> None:
    """Remove `el` and keep the indentation of what follows (a tail that is only whitespace is not doubled)."""
    parent = el.getparent()
    if parent is None:
        return
    tail = el.tail
    if tail and tail.strip():
        prev = el.getprevious()
        if prev is not None:
            prev.tail = (prev.tail or "") + tail
        else:
            parent.text = (parent.text or "") + tail
    elif tail and el.getnext() is None:           # the last child: the closing tag takes the dedent
        prev = el.getprevious()
        if prev is not None:
            prev.tail = tail
        else:
            parent.text = tail
    parent.remove(el)


def _inner(name: str) -> str:
    return name[1:-1] if name.startswith("[") and name.endswith("]") else name


# ------------------------------------------------------------------ traces --

class _Candidate:
    __slots__ = ("category", "key", "label", "detail", "traces", "names")

    def __init__(self, category, key, label, detail):
        self.category, self.key, self.label, self.detail = category, key, label, detail
        self.traces: list[tuple[str, object]] = []        # (kind, element)
        self.names: set = set()

    @property
    def roots(self) -> list:
        return [el for _, el in self.traces]


def _field_traces(doc, cand: _Candidate) -> None:
    """The elements that are only about the field `cand.key` (datasource name, `[Name]`)."""
    ds_name, name = cand.key
    inner = _inner(name)
    for ds in doc.xpath("/workbook/datasources/datasource[@name=$n]", n=ds_name):
        for col in ds.xpath("./column[@name=$f]", f=name):
            cand.traces.append(("columns", col))
        for ci in ds.xpath("./column-instance[@column=$f]", f=name):
            cand.traces.append(("column_instances", ci))
        for rec in ds.xpath("./connection//metadata-record[@class='column'][not(ancestor::extract)]"):
            if rec.findtext("local-name") == name and rec.find("remote-name") is None:
                cand.traces.append(("metadata_records", rec))
        for item in ds.xpath(".//folder-item[@name=$f]", f=name):
            cand.traces.append(("folder_items", item))
        for fld in ds.xpath("./drill-paths/drill-path/field"):
            toks = _BRACKETED.findall(fld.text or "")
            if toks and toks[-1] == inner:
                cand.traces.append(("hierarchy_fields", fld))
        for el in ds.xpath("./style/style-rule/*[@field]"):
            if inner in _names_in(el.get("field")):
                cand.traces.append(("style_entries", el))
    for dep in doc.xpath("/workbook/datasources/datasource/datasource-dependencies[@datasource=$n]", n=ds_name):
        for col in dep.xpath("./column[@name=$f]", f=name):
            cand.traces.append(("dependency_entries", col))
        for ci in dep.xpath("./column-instance[@column=$f]", f=name):
            cand.traces.append(("dependency_entries", ci))
    cand.names = {inner}


def _sheet_traces(doc, cand: _Candidate) -> None:
    _, name = cand.key
    for ws in doc.xpath("/workbook/worksheets/worksheet[@name=$n]", n=name):
        cand.traces.append(("sheets", ws))
    for w in doc.xpath("/workbook/windows/window[@class='worksheet'][@name=$n]", n=name):
        cand.traces.append(("windows", w))
    for t in doc.xpath("/workbook/thumbnails/thumbnail[@name=$n]", n=name):
        cand.traces.append(("thumbnails", t))
    cand.names = {name}


def _referrers(doc, cands: list[_Candidate], sheets: bool) -> dict:
    """name -> the first element outside the candidates' own traces that mentions it (only for the names
    the candidates have). `sheets` reads exact values and tooltip text, otherwise bracketed names."""
    own = {id(el) for c in cands for el in c.roots}
    wanted = set().union(*(c.names for c in cands)) if cands else set()
    seen: dict = {}
    stack = [doc.getroot()]
    while stack and len(seen) < len(wanted):
        el = stack.pop()
        if id(el) in own or not isinstance(el.tag, str):
            continue
        for n in (_el_values(el) if sheets else _el_names(el)) & wanted:
            seen.setdefault(n, el)
        stack.extend(reversed(list(el)))
    return seen


def _settle(doc, cands: list[_Candidate], sheets: bool) -> tuple[list[_Candidate], list[tuple]]:
    """Fixpoint: drop every candidate that something staying still names, until nothing changes.
    Returns (removable, [(candidate, referrer element)])."""
    current = list(cands)
    kept: dict = {}
    while True:
        seen = _referrers(doc, current, sheets)
        blocked = [c for c in current if c.names & set(seen)]
        if not blocked:
            return current, [(c, kept[id(c)]) for c in cands if id(c) in kept]
        for c in blocked:
            kept[id(c)] = seen[sorted(c.names & set(seen))[0]]
        current = [c for c in current if id(c) not in kept]


# ------------------------------------------------------------------ the engine --

def _tidy(doc, parents: set) -> None:
    """Remove what a removal left empty and nothing else: dependency lists and style rules."""
    for el in list(parents):
        while el is not None and el.getparent() is not None and el.tag in (
                "datasource-dependencies", "style-rule", "style") and len(el) == 0 and not (el.text or "").strip():
            up = el.getparent()
            _drop(el)
            el = up


def _apply(doc, removable: list[_Candidate], counts: dict) -> None:
    parents: set = set()
    for c in removable:
        for kind, el in c.traces:
            parent = el.getparent()
            if parent is None:
                continue
            if kind != "hierarchy_fields":            # a hierarchy that lost a field stays
                parents.add(parent)
            _drop(el)
            counts[kind] += 1
    _tidy(doc, parents)


def _facts(doc) -> _Facts:
    return _Facts(_DocParser(doc))


def _candidates(doc, calculations: bool, parameters: bool) -> list[_Candidate]:
    f = _facts(doc)
    out: list[_Candidate] = []
    if calculations:
        for calc, detail in unused_calculations(f):
            out.append(_Candidate("calculations", calc.key, calc.label, detail))
    if parameters:
        for row, detail in unused_parameters(f):
            out.append(_Candidate("parameters", (row["datasource"], row["field"]),
                                  f"Parameters: {row['caption'] or str(row['field']).strip('[]')}", detail))
    for c in out:
        _field_traces(doc, c)
    return [c for c in out if any(k == "columns" for k, _ in c.traces)]


def prune(
    workbook: Union[TwbParser, str],
    output_path: Optional[str] = None,
    sheets: bool = False,
    calculations: bool = True,
    parameters: bool = True,
    overwrite: bool = False,
) -> dict:
    """Prune a workbook (a path or a `TwbParser`). Without `output_path` nothing is written (a dry run);
    with it a NEW file is written, in the input's format, and the input is never touched; an existing
    output is refused unless `overwrite=True`.

    Removes the calculations (A001) and parameters (A005) the audit finds unused and, with `sheets=True`
    only, the worksheets of A006, each only if nothing that stays refers to it (see the module text).
    With `sheets=True` the sheets go first, and a field only they used is then pruned as well.

    Returns a dict: `removed` (rows `category, object, name, detail, traces`; `name` is the internal name), `kept` (rows `category, object,
    reason, referrer`: a finding that was not removed, and what still names it), `counts` (per category),
    `traces` (elements removed, per kind), `dry_run` and `output`."""
    if not isinstance(workbook, TwbParser):
        workbook = TwbParser(str(workbook))
    out = None
    if output_path is not None:
        out = Path(output_path)
        source = Path(workbook.twbx_path or workbook.path)
        if out.suffix.lower() != source.suffix.lower():
            raise PruneError(f"the output must end in {source.suffix}, got {out.suffix or 'no extension'}")
        if out.exists() and source.exists() and (out.resolve() == source.resolve() or out.samefile(source)):
            raise FileExistsError(f"refusing to overwrite the input workbook: {out}")
        if out.exists() and not overwrite:
            raise FileExistsError(f"refusing to overwrite existing file: {out} (use --overwrite)")

    doc = copy.deepcopy(workbook.xml_doc)
    counts = {k: 0 for k in TRACE_KINDS}
    removed: list[dict] = []
    kept: list[dict] = []

    def run(cands: list[_Candidate], sheet_mode: bool) -> None:
        removable, blocked = _settle(doc, cands, sheet_mode)
        for c, el in blocked:
            kept.append({"category": c.category, "object": c.label,
                         "reason": "still named by " + _where(el), "referrer": _where(el)})
        for c in removable:
            removed.append({"category": c.category, "object": c.label, "name": c.key[1], "detail": c.detail,
                            "traces": sorted({k for k, _ in c.traces})})
        _apply(doc, removable, counts)

    if sheets:
        listed = sheets_in_no_dashboard(doc)
        every = doc.xpath("/workbook/worksheets/worksheet/@name")
        if listed and len(listed) >= len(every):
            for name, _ in listed:
                kept.append({"category": "sheets", "object": name,
                             "reason": "it is the last worksheet(s) of the workbook; none is removed",
                             "referrer": ""})
        else:
            cands = []
            for name, detail in listed:
                c = _Candidate("sheets", ("", name), name, detail)
                _sheet_traces(doc, c)
                cands.append(c)
            run(cands, True)
    if calculations or parameters:
        run(_candidates(doc, calculations, parameters), False)

    cat_counts = {c: sum(1 for r in removed if r["category"] == c) for c in CATEGORIES}
    report = {"removed": removed, "kept": kept, "counts": cat_counts,
              "traces": {k: v for k, v in counts.items() if v},
              "dry_run": out is None, "output": None, "input": str(workbook.twbx_path or workbook.path)}
    if out is not None:
        data = _serialize_workbook(workbook, doc)
        _write_new(out, data, overwrite)
        report["output"] = str(out)
    return report


def format_report(report: dict) -> str:
    """The report as text: what is removed (or would be) and why, what is kept and why, the counts."""
    verb = "would remove" if report["dry_run"] else "removed"
    lines = []
    for r in report["removed"]:
        lines.append(f"{verb}  {r['category'][:-1] if r['category'] != 'sheets' else 'sheet':<11} {r['object']}")
        lines.append(f"            why: {r['detail']}")
    for k in report["kept"]:
        lines.append(f"kept         {k['category'][:-1] if k['category'] != 'sheets' else 'sheet':<11} {k['object']}")
        lines.append(f"            why: {k['reason']}")
    if lines:
        lines.append("")
    c = report["counts"]
    lines.append(f"{verb}: {c['calculations']} calculation(s), {c['parameters']} parameter(s), {c['sheets']} sheet(s)"
                 f"; kept {len(report['kept'])} finding(s) that something still uses")
    if report["dry_run"]:
        lines.append("dry run: nothing was written (use --write -o OUT)")
    else:
        lines.append(f"wrote {report['output']}")
    return "\n".join(lines)
