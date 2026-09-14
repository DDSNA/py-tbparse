"""Relationship validation against known datasources/fields.

Port of R/validators.R (`validate_relationships`).
"""

from __future__ import annotations

import re

import pandas as pd

from ._clean import is_missing

_FUNC_CALL_FULL_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\((.*)\)")


def _clean_str(x) -> str:
    if is_missing(x):
        return ""
    return re.sub(r"[\[\]]", "", str(x)).strip()


def _clean_pool(series: pd.Series) -> list[str]:
    return [c for c in (_clean_str(v) for v in series) if c]


def _base_token(x) -> str:
    # R's base_token() runs the function-call regex on the raw value
    # first, and only strips brackets/whitespace afterward -- do the same
    # order here, since pre-trimming changes which values match the
    # anchored NAME(...) pattern (e.g. a whitespace-padded raw value would
    # no longer match after pre-trimming in R, but would in Python if we
    # cleaned first).
    if is_missing(x):
        raw = ""
    else:
        raw = str(x)
    m = _FUNC_CALL_FULL_RE.fullmatch(raw)
    inside = m.group(1) if m else raw
    inside = re.sub(r"[\[\]]", "", inside).strip()
    parts = [p for p in inside.split(".") if p]
    return parts[-1] if parts else inside


def validate_relationships(parser, strict: bool = False) -> dict:
    """Port of `validate_relationships()`.

    `parser` must expose `get_relationships()`, `get_datasources()`,
    `get_fields()`, and `get_calculated_fields()`.
    """
    rels = parser.get_relationships()
    ds = parser.get_datasources()
    flds = parser.get_fields()
    calcs = parser.get_calculated_fields()

    if rels is None or rels.empty:
        return {"ok": True, "issues": {}}

    known_tables = set(ds["datasource"].dropna().unique()) if "datasource" in ds.columns else set()

    field_pool = set()
    if "field_clean" in flds.columns:
        field_pool.update(_clean_pool(flds["field_clean"]))
    if "name" in flds.columns:
        field_pool.update(_clean_pool(flds["name"]))
    if "caption" in flds.columns:
        field_pool.update(_clean_pool(flds["caption"]))
    if "name" in calcs.columns:
        field_pool.update(_clean_pool(calcs["name"]))
    if "tableau_internal_name" in calcs.columns:
        field_pool.update(_clean_pool(calcs["tableau_internal_name"]))
    field_pool = {p.lower() for p in field_pool}

    unknown_tables = rels[
        ~rels["left_table"].isin(known_tables) | ~rels["right_table"].isin(known_tables)
    ]

    rels2 = rels.copy()
    rels2["left_tok"] = rels2["left_field"].apply(lambda v: _clean_str(v).lower())
    rels2["right_tok"] = rels2["right_field"].apply(lambda v: _clean_str(v).lower())
    rels2["left_base"] = rels2["left_field"].apply(lambda v: _base_token(v).lower())
    rels2["right_base"] = rels2["right_field"].apply(lambda v: _base_token(v).lower())

    left_ok = rels2["left_tok"].isin(field_pool) | rels2["left_base"].isin(field_pool)
    right_ok = rels2["right_tok"].isin(field_pool) | rels2["right_base"].isin(field_pool)

    unknown_fields = rels2[~left_ok | ~right_ok][
        ["left_table", "left_field", "right_table", "right_field"]
    ].copy()
    unknown_fields["left_ok"] = left_ok[~left_ok | ~right_ok]
    unknown_fields["right_ok"] = right_ok[~left_ok | ~right_ok]

    issues = {}
    if not unknown_tables.empty:
        issues["unknown_tables"] = unknown_tables
    if not unknown_fields.empty:
        issues["unknown_fields"] = unknown_fields

    return {"ok": len(issues) == 0, "issues": issues}
