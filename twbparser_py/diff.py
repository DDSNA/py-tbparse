"""Diff any two workbooks' tables.

Not part of the R package -- the R original operates on a single
workbook at a time. Reuses `_tables.TABLE_SPECS` so it works for any
registered table without extra wiring.
"""

from __future__ import annotations

import pandas as pd

from ._tables import TABLE_SPECS
from .parser import TwbParser

_DIFF_COLUMN = "_diff"


def diff_tables(a_df: pd.DataFrame, b_df: pd.DataFrame) -> pd.DataFrame:
    """Full-row-equality diff between two same-shaped tables.

    Returns only the rows that differ between `a_df` and `b_df`, tagged
    in a `_diff` column: `"added"` (row present in b, not a) or
    `"removed"` (row present in a, not b). There's no generic notion of
    "changed" across arbitrary tables without a natural key, so a row
    that changed in one field shows up as one `"removed"` row (old
    values) and one `"added"` row (new values) rather than a single
    "changed" row.
    """
    a_df = a_df.reset_index(drop=True)
    b_df = b_df.reset_index(drop=True)

    if list(a_df.columns) != list(b_df.columns):
        common = [c for c in a_df.columns if c in b_df.columns]
        a_df = a_df[common]
        b_df = b_df[common]

    if a_df.empty and b_df.empty:
        return pd.DataFrame(columns=[*a_df.columns, _DIFF_COLUMN])

    merged = a_df.merge(b_df, how="outer", indicator=True)
    merged = merged[merged["_merge"] != "both"].copy()
    merged[_DIFF_COLUMN] = merged["_merge"].map({"left_only": "removed", "right_only": "added"})
    return merged.drop(columns="_merge").reset_index(drop=True)


def diff_workbooks(a: TwbParser, b: TwbParser, table: str = "datasources", **kwargs) -> pd.DataFrame:
    """Diff one named table (see `_tables.TABLE_SPECS`) between two
    `TwbParser` instances."""
    if table not in TABLE_SPECS:
        raise ValueError(f"unknown table '{table}'")
    getter = TABLE_SPECS[table]
    a_df = getter(a, **kwargs)
    b_df = getter(b, **kwargs)
    return diff_tables(a_df, b_df)
