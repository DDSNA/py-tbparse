"""Which sheets, dashboards and calculations use each field.

Not part of the R package's v1 subset (the R package has a field-usage
helper among its analytics functions, not yet ported). Templates need it to
know which fields a workbook really depends on: a field used only inside a
calculation that a sheet shows is just as required as one on a shelf.
"""

from __future__ import annotations

import re
from typing import Optional

import pandas as pd

from .parser import TwbParser

USAGE_COLUMNS = [
    "datasource", "field", "caption", "kind", "datatype", "used",
    "sheets", "dashboards", "calculations",
]

# `[Field]`, `[Parameters].[Parameter 1]`; `]]` escapes a `]` inside a name.
_BRACKETED = re.compile(r"\[((?:[^\]]|\]\])+)\]")


def _refs(text: Optional[str]) -> list[str]:
    """Bracketed names in a formula or attribute, as `[Name]`."""
    if not text:
        return []
    return ["[" + m.group(1) + "]" for m in _BRACKETED.finditer(text)]


def _datasource_fields(ds) -> dict[str, dict]:
    """Every field-like thing a datasource defines, by local name."""
    fields: dict[str, dict] = {}
    for rec in ds.xpath("./connection//metadata-record[@class='column']"):
        local = rec.findtext("local-name")
        if local:
            fields[local] = {"kind": "physical", "caption": None,
                             "datatype": rec.findtext("local-type"), "deps": set()}
    for col in ds.xpath("./column[@name]"):
        name = col.get("name")
        calc = col.find("calculation")
        entry = fields.setdefault(name, {"kind": "physical", "caption": None,
                                         "datatype": col.get("datatype"), "deps": set()})
        entry["caption"] = col.get("caption")
        entry["datatype"] = col.get("datatype") or entry["datatype"]
        if calc is not None:
            entry["kind"] = "parameter" if col.get("param-domain-type") else "calculated"
            entry["deps"] |= set(_refs(calc.get("formula")))
            entry["deps"] |= set(_refs(calc.get("column")))  # bins: <calculation class='bin' column='[Sales]'>
    for grp in ds.xpath("./group[@name]"):
        entry = fields.setdefault(grp.get("name"), {"kind": "group", "caption": grp.get("caption"),
                                                    "datatype": None, "deps": set()})
        entry["kind"] = "group"
        for gf in grp.iter("groupfilter"):
            for attr in ("level", "member", "expression"):
                entry["deps"] |= set(_refs(gf.get(attr)))
    for path in ds.xpath("./drill-paths/drill-path"):
        for f in path.iter("field"):
            fields.setdefault(f.text or "", {"kind": "physical", "caption": None, "datatype": None, "deps": set()})
    fields.pop("", None)
    return fields


def _sheet_uses(doc) -> dict[str, dict[str, set]]:
    """worksheet -> datasource -> local names it uses directly."""
    out: dict[str, dict[str, set]] = {}
    for ws in doc.xpath("/workbook/worksheets/worksheet[@name]"):
        per_ds: dict[str, set] = {}
        for dep in ws.xpath(".//datasource-dependencies[@datasource]"):
            names = per_ds.setdefault(dep.get("datasource"), set())
            names.update(c.get("name") for c in dep.xpath("./column[@name]"))
            names.update(ci.get("column") for ci in dep.xpath("./column-instance[@column]"))
        out[ws.get("name")] = per_ds
    return out


def _dashboards_of(doc) -> dict[str, set]:
    """worksheet -> dashboards that show it."""
    out: dict[str, set] = {}
    for db in doc.xpath("/workbook/dashboards/dashboard[@name]"):
        for z in db.xpath(".//zone"):
            sheet = z.get("worksheet") or z.get("name")
            if sheet:
                out.setdefault(sheet, set()).add(db.get("name"))
    return out


def field_usage(parser_or_doc) -> pd.DataFrame:
    """One row per field of every datasource (parameters included): which
    worksheets, dashboards and calculations use it, directly or through
    other calculations, groups and sets.

    Returns `datasource, field, caption, kind, datatype, used, sheets,
    dashboards, calculations`. `kind` is `physical`, `calculated`, `group`
    or `parameter`; the last three columns are sorted lists of names."""
    doc = parser_or_doc.xml_doc if isinstance(parser_or_doc, TwbParser) else parser_or_doc
    by_ds = {ds.get("name"): _datasource_fields(ds)
             for ds in doc.xpath("/workbook/datasources/datasource[@name]")}
    sheets = _sheet_uses(doc)
    dashboards = _dashboards_of(doc)

    # sheets[field] / calcs[field] for every (datasource, field)
    used_by_sheet: dict[tuple, set] = {}
    used_by_calc: dict[tuple, set] = {}

    def resolve(ds: str, ref: str, from_ds_fields: dict) -> Optional[tuple]:
        if ref in from_ds_fields:
            return ds, ref
        return None

    def walk(ds: str, name: str, seen: set) -> set:
        """All (ds, field) a field depends on, itself included."""
        key = (ds, name)
        if key in seen:
            return set()
        seen.add(key)
        out = {key}
        fields = by_ds.get(ds, {})
        entry = fields.get(name)
        if not entry:
            return out
        deps = list(entry["deps"])
        i = 0
        while i < len(deps):
            ref = deps[i]
            # `[Parameters].[Parameter 1]`: the formula text has both parts
            if ref == "[Parameters]" and i + 1 < len(deps):
                out |= walk("Parameters", deps[i + 1], seen)
                i += 2
                continue
            if ref in by_ds and i + 1 < len(deps):  # `[other ds].[field]`
                out |= walk(ref, deps[i + 1], seen)
                i += 2
                continue
            hit = resolve(ds, ref, fields)
            if hit:
                out |= walk(hit[0], hit[1], seen)
            i += 1
        return out

    for ws, per_ds in sheets.items():
        for ds, names in per_ds.items():
            for n in names:
                for dep in walk(ds, n, set()):
                    used_by_sheet.setdefault(dep, set()).add(ws)
    for ds, fields in by_ds.items():
        for name, entry in fields.items():
            if entry["kind"] in ("calculated", "group"):
                for dep in walk(ds, name, set()) - {(ds, name)}:
                    used_by_calc.setdefault(dep, set()).add(entry["caption"] or name.strip("[]"))

    rows = []
    for ds, fields in by_ds.items():
        for name, entry in fields.items():
            ws = used_by_sheet.get((ds, name), set())
            dbs = set().union(*(dashboards.get(s, set()) for s in ws)) if ws else set()
            rows.append({
                "datasource": ds, "field": name, "caption": entry["caption"], "kind": entry["kind"],
                "datatype": entry["datatype"], "used": bool(ws),
                "sheets": sorted(ws), "dashboards": sorted(dbs),
                "calculations": sorted(used_by_calc.get((ds, name), set())),
            })
    return pd.DataFrame(rows, columns=USAGE_COLUMNS)
