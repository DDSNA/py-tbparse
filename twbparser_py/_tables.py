"""Shared table registry used by both the CLI and the web GUI.

Keeping this in one place means the CLI and GUI can never drift out of
sync on which tables exist or how their optional parameters
(`dashboard`, `include_parameters`) are threaded through to `TwbParser`.
"""

from __future__ import annotations

from typing import Callable

import pandas as pd

from .parser import TwbParser


def _overview(p: TwbParser, **_kw) -> pd.DataFrame:
    return p.get_overview()


def _datasources(p: TwbParser, **_kw) -> pd.DataFrame:
    return p.get_datasources()


def _parameters(p: TwbParser, **_kw) -> pd.DataFrame:
    return p.get_parameters()


def _fields(p: TwbParser, **_kw) -> pd.DataFrame:
    return p.get_fields()


def _raw_fields(p: TwbParser, **_kw) -> pd.DataFrame:
    return p.get_raw_fields()


def _calculated_fields(p: TwbParser, include_parameters: bool = False, **_kw) -> pd.DataFrame:
    return p.get_calculated_fields(include_parameters=include_parameters)


def _joins(p: TwbParser, **_kw) -> pd.DataFrame:
    return p.get_joins()


def _relations(p: TwbParser, **_kw) -> pd.DataFrame:
    return p.get_relations()


def _relationships(p: TwbParser, **_kw) -> pd.DataFrame:
    return p.get_relationships()


def _inferred_relationships(p: TwbParser, **_kw) -> pd.DataFrame:
    return p.get_inferred_relationships()


def _dashboards(p: TwbParser, **_kw) -> pd.DataFrame:
    return p.get_dashboards()


def _dashboard_sheets(p: TwbParser, dashboard: str | None = None, **_kw) -> pd.DataFrame:
    return p.get_dashboard_sheets(dashboard=dashboard or None)


def _custom_sql(p: TwbParser, **_kw) -> pd.DataFrame:
    return p.get_custom_sql()


def _initial_sql(p: TwbParser, **_kw) -> pd.DataFrame:
    return p.get_initial_sql()


def _published_refs(p: TwbParser, **_kw) -> pd.DataFrame:
    return p.get_published_refs()


# Order here is display order in both the CLI's `tables` listing and the
# GUI's table dropdown.
TABLE_SPECS: dict[str, Callable[..., pd.DataFrame]] = {
    "overview": _overview,
    "datasources": _datasources,
    "parameters": _parameters,
    "fields": _fields,
    "raw-fields": _raw_fields,
    "calculated-fields": _calculated_fields,
    "joins": _joins,
    "relations": _relations,
    "relationships": _relationships,
    "inferred-relationships": _inferred_relationships,
    "dashboards": _dashboards,
    "dashboard-sheets": _dashboard_sheets,
    "custom-sql": _custom_sql,
    "initial-sql": _initial_sql,
    "published-refs": _published_refs,
}

TABLE_NAMES = list(TABLE_SPECS)
