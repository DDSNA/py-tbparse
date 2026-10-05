"""Consistency checks on a workbook: does every part still point at something that exists?

Not part of the R package. The checks answer one question for a workbook py-tbparse has written
(a renamed copy, a template, a template applied to new data): did the edit leave a dangling
reference? They read the XML only and cannot say that Tableau will open the file; the schema
check in `tests/schema_check.py` and `docs/verify-in-tableau.md` are the other two layers.

Every finding is one row: which check, how serious, where, and what is wrong. An empty frame means
no check found anything. A workbook Tableau itself wrote can have findings too (a calculation that
names a deleted field, say), so compare a written workbook with the one it came from.
"""

from __future__ import annotations

import os
from typing import Union

import pandas as pd

from .parser import TwbParser
from .usage import _datasource_fields, _sheet_uses, missing_references

VERIFY_COLUMNS = ["check", "severity", "datasource", "object", "detail"]

# What Tableau writes as remote-type for each local type of a text file's column
# (counted over the corpus; the first is the one this package writes).
_TEXT_REMOTE_TYPES = {
    "string": ("129", "130"),
    "integer": ("20", "2", "3"),
    "real": ("5", "131"),
    "boolean": ("11",),
    "date": ("133", "7"),
    "datetime": ("135", "7"),
}
_AUTO_COLUMN = "{http://www.tableausoftware.com/xml/user}auto-column"
# Zones of these kinds are named after the worksheet they show or control.
_SHEET_ZONE_TYPES = {None, "filter", "color", "size", "shape", "highlighter", "map", "legend"}


def _row(check: str, severity: str, datasource: str, obj: str, detail: str) -> dict:
    return {"check": check, "severity": severity, "datasource": datasource, "object": obj, "detail": detail}


def _fields_with_tables(ds) -> dict:
    """The datasource's fields plus its object-model table columns, which a worksheet references
    (for a record count) and which the prefixed form writes under a feature-flag tag."""
    fields = dict(_datasource_fields(ds))
    for el in ds:
        if isinstance(el.tag, str) and el.tag.endswith("column") and el.get("name"):
            fields.setdefault(el.get("name"), {})
    return fields


def _sheet_fields(doc, by_ds) -> list[dict]:
    rows = []
    for sheet, per_ds in _sheet_uses(doc).items():
        for ds_name, names in sorted(per_ds.items()):
            known = by_ds.get(ds_name)
            if known is None:
                continue                      # a datasource this workbook does not define (published)
            local = set()
            for ws in doc.xpath("/workbook/worksheets/worksheet[@name=$n]", n=sheet):
                for col in ws.xpath(".//datasource-dependencies[@datasource=$d]/column[calculation]", d=ds_name):
                    local.add(col.get("name"))        # a calculation that lives in the sheet only
            for name in sorted(n for n in names if n and not n.startswith("[:")):
                if name not in known and name not in local:
                    rows.append(_row("sheet-field", "error", ds_name, sheet,
                                     f"worksheet uses {name}, which the datasource does not have"))
    return rows


def dashboard_targets(db) -> list[str]:
    """The sheets (or dashboards) a `<dashboard>` element shows, in document order: a zone names one in
    `@worksheet` or, in some files, only in `@name` (layout containers, text and the like are skipped)."""
    return [z.get("worksheet") or z.get("name") for z in db.xpath(".//zone[@name or @worksheet]")
            if (z.get("type-v2") or z.get("type")) in _SHEET_ZONE_TYPES]


def _dashboard_sheets(doc) -> list[dict]:
    rows = []
    sheets = set(doc.xpath("/workbook/worksheets/worksheet/@name"))
    known = sheets | set(doc.xpath("/workbook/dashboards/dashboard/@name"))
    for db in doc.xpath("/workbook/dashboards/dashboard[@name]"):
        for target in dashboard_targets(db):
            if target not in known:
                rows.append(_row("dashboard-sheet", "error", "", db.get("name"),
                                 f"a zone shows {target!r}, which is not a worksheet or dashboard"))
    return rows


def _windows(doc) -> list[dict]:
    known = set(doc.xpath("/workbook/worksheets/worksheet/@name | /workbook/dashboards/dashboard/@name"
                          " | /workbook/stories/story/@name"))
    return [_row("window-name", "error", "", w.get("name"), "a window names a sheet that does not exist")
            for w in doc.xpath("/workbook/windows/window[@name]") if w.get("name") not in known]


def _local_types(ds) -> list[dict]:
    """A metadata record's type against the type its column declares (unless the author changed it)."""
    rows = []
    declared = {c.get("name"): c for c in ds.xpath("./column[@name][@datatype]")}
    for rec in ds.xpath("./connection//metadata-record[@class='column']"):
        local, kind = rec.findtext("local-name"), rec.findtext("local-type")
        col = declared.get(local)
        if col is None or not kind or col.get("datatype-customized") or col.get("param-domain-type"):
            continue
        if col.get("datatype") != kind:
            rows.append(_row("local-type", "warning", ds.get("name"), local,
                             f"the data says {kind}, the column says {col.get('datatype')}"))
    return rows


def _built_in_counts(ds) -> list[dict]:
    """Tableau's own [Number of Records] needs a formula (`1`) or a data column of that name behind
    it; with neither, a worksheet that sums it has nothing to sum. All 42 built-ins of the corpus
    carry the formula."""
    rows = []
    records = {r.findtext("local-name") for r in ds.xpath("./connection//metadata-record[@class='column']")}
    for col in ds.xpath("./column[@name]"):
        if col.get(_AUTO_COLUMN) == "numrec" and col.find("calculation") is None and col.get("name") not in records:
            rows.append(_row("built-in-count", "error", ds.get("name"), col.get("name"),
                             "the built-in record count has no formula and no data column behind it"))
    return rows


def _text_file_columns(ds) -> list[dict]:
    """Columns read from a text file: each metadata record must name a column the relation
    lists, with the remote-type Tableau writes for its type."""
    if not ds.xpath(".//named-connection/connection[@class='textscan']"):
        return []
    rows, listed = [], set(ds.xpath(".//relation/columns/column/@name"))
    for rec in ds.xpath("./connection//metadata-record[@class='column']"):
        remote, local = rec.findtext("remote-name"), rec.findtext("local-name")
        if listed and remote not in listed:
            rows.append(_row("remote-name", "error", ds.get("name"), local,
                             f"maps to column {remote!r}, which the text file's columns do not list"))
        kind, code = rec.findtext("local-type"), rec.findtext("remote-type")
        if kind in _TEXT_REMOTE_TYPES and code not in _TEXT_REMOTE_TYPES[kind]:
            rows.append(_row("remote-type", "error", ds.get("name"), local,
                             f"{kind} column has remote-type {code}; Tableau writes {' or '.join(_TEXT_REMOTE_TYPES[kind])}"))
    return rows


def validate_workbook(source: Union[str, os.PathLike, TwbParser]) -> pd.DataFrame:
    """Dangling references in a workbook: one row per finding (`VERIFY_COLUMNS`).

    Checks, with their severity: `sheet-field` (a worksheet uses a field its datasource lacks),
    `calc-reference` (a calculation names a missing field; a warning, since a bracketed word in a
    string literal counts), `dashboard-sheet` and `window-name` (they name a sheet that is not
    there), `local-type` (a column's type disagrees with its data's; a warning), `built-in-count`
    (Number of Records with no formula and no data column) and, for text-file data, `remote-name`
    and `remote-type`."""
    parser = source if isinstance(source, TwbParser) else TwbParser(str(source))
    doc = parser.xml_doc
    by_ds = {ds.get("name"): _fields_with_tables(ds) for ds in doc.xpath("/workbook/datasources/datasource[@name]")}
    rows = _sheet_fields(doc, by_ds) + _dashboard_sheets(doc) + _windows(doc)
    for ds in doc.xpath("/workbook/datasources/datasource[@name]"):
        rows += _local_types(ds) + _built_in_counts(ds) + _text_file_columns(ds)
    for r in missing_references(doc).itertuples():
        rows.append(_row("calc-reference", "warning", r.datasource, r.calculation,
                         f"the formula names {r.missing}, which does not exist"))
    return pd.DataFrame(rows, columns=VERIFY_COLUMNS).sort_values(
        VERIFY_COLUMNS, kind="stable", ignore_index=True)
