"""Diff any two workbooks' tables.

Not part of the R package -- the R original operates on a single
workbook at a time. Reuses `_tables.TABLE_SPECS` so it works for any
registered table without extra wiring.
"""

from __future__ import annotations

import collections

import pandas as pd

from ._tables import TABLE_SPECS
from .parser import TwbParser

_DIFF_COLUMN = "_diff"


def _normalize_cell(v):
    """Collapse every "missing" representation (None, NaN, NaT, ...) to a
    single value so rows compare equal regardless of which dtype pandas
    happened to pick per-column, and so the value is hashable for the
    multiset comparison below."""
    if v is None:
        return None
    try:
        if pd.isna(v):
            return None
    except (TypeError, ValueError):
        pass
    return v


def diff_tables(a_df: pd.DataFrame, b_df: pd.DataFrame) -> pd.DataFrame:
    """Full-row-equality diff between two same-shaped tables.

    Returns only the rows that differ between `a_df` and `b_df`, tagged
    in a `_diff` column: `"added"` (row present in b more times than in
    a) or `"removed"` (row present in a more times than in b). Rows are
    compared as a multiset (via `collections.Counter`), not via
    `DataFrame.merge`, for two reasons: `merge` raises when a same-named
    column ends up with mismatched dtypes across the two frames (e.g. an
    all-missing column is `object` on one side and `int64` on the other
    -- routine for sparse Tableau attributes like zone x/y/w/h), and
    `merge`'s outer join silently Cartesian-products duplicate rows
    instead of reporting a genuine surplus/deficit in how many times a
    row appears.

    There's no generic notion of "changed" across arbitrary tables
    without a natural key, so a row that changed in one field shows up
    as one `"removed"` row (old values) and one `"added"` row (new
    values) rather than a single "changed" row.
    """
    a_df = a_df.reset_index(drop=True)
    b_df = b_df.reset_index(drop=True)

    if list(a_df.columns) != list(b_df.columns):
        common = [c for c in a_df.columns if c in b_df.columns]
        a_df = a_df[common]
        b_df = b_df[common]

    columns = list(a_df.columns)
    if not columns:
        return pd.DataFrame(columns=[_DIFF_COLUMN])

    a_rows = [tuple(_normalize_cell(v) for v in row) for row in a_df.itertuples(index=False, name=None)]
    b_rows = [tuple(_normalize_cell(v) for v in row) for row in b_df.itertuples(index=False, name=None)]

    a_counts = collections.Counter(a_rows)
    b_counts = collections.Counter(b_rows)

    out_rows = []
    for row, count in a_counts.items():
        surplus = count - b_counts.get(row, 0)
        out_rows.extend([(*row, "removed")] * max(surplus, 0))
    for row, count in b_counts.items():
        surplus = count - a_counts.get(row, 0)
        out_rows.extend([(*row, "added")] * max(surplus, 0))

    return pd.DataFrame(out_rows, columns=[*columns, _DIFF_COLUMN])


def diff_workbooks(a: TwbParser, b: TwbParser, table: str = "datasources", **kwargs) -> pd.DataFrame:
    """Diff one named table (see `_tables.TABLE_SPECS`) between two
    `TwbParser` instances."""
    if table not in TABLE_SPECS:
        raise ValueError(f"unknown table '{table}'")
    getter = TABLE_SPECS[table]
    a_df = getter(a, **kwargs)
    b_df = getter(b, **kwargs)
    return diff_tables(a_df, b_df)
