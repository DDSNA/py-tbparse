"""The main `TwbParser` façade, ported from R6 class `TwbParser` in
R/twb_parser.R.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

import pandas as pd
from lxml import etree

from ._clean import internal_last
from ._xml import parse_file, read_twb_from_twbx
from .calculated_fields import _CALC_COLUMNS, _RAW_COLUMNS, extract_calculated_fields, extract_raw_fields
from .dashboards import (_DASHBOARD_COLUMNS, _SHEETS_COLUMNS, _SUMMARY_COLUMNS, dashboard_sheets,
                         dashboard_summary, list_dashboards)
from .datasources import (
    _DATASOURCE_COLUMNS,
    _PARAMETER_COLUMNS,
    extract_datasource_details,
)
from .fields import _FIELDS_COLUMNS, _INFERRED_COLUMNS, extract_columns_with_table_source, infer_implicit_relationships
from .graph import graph_data, to_dot
from .joins import _JOIN_COLUMNS, extract_joins
from .published import _PUBLISHED_COLUMNS, extract_published_refs
from .relationships import _RELATION_COLUMNS, _RELATIONSHIP_COLUMNS, extract_relations, extract_relationships
from .sql import _CUSTOM_SQL_COLUMNS, _INITIAL_SQL_COLUMNS, extract_custom_sql, extract_initial_sql
from .validators import validate_relationships


def _safe_call(fn, fallback, *args, **kwargs):
    """Port of `safe_call()`: evaluate and return `fallback` on error."""
    try:
        return fn(*args, **kwargs)
    except Exception:
        return fallback


class TwbParser:
    """Parse a Tableau `.twb`/`.twbx` workbook into pandas DataFrames.

    On construction, the parser reads the XML and precomputes relations,
    joins, relationships, fields, calculated fields, inferred
    relationships, and datasource details -- mirroring the R6 `TwbParser`
    class this is ported from.
    """

    def __init__(self, path: str):
        if not os.path.exists(path):
            raise FileNotFoundError(f"File not found: {path}")

        ext = Path(path).suffix.lower().lstrip(".")
        self.twbx_path: Optional[str] = None
        self.twbx_dir: Optional[str] = None
        self.twbx_manifest: pd.DataFrame

        if ext == "twbx":
            # Parsed in memory rather than via extract_twb_from_twbx(), which
            # would leave a temp directory behind on every load. twbx_dir
            # stays None (nothing is extracted); self.path points at the
            # member inside the archive so get_overview()'s "file" is
            # unchanged -- it is not a path that exists on disk.
            info = read_twb_from_twbx(path)
            self.twbx_path = info["twbx_path"]
            self.twbx_manifest = info["manifest"]
            self.twb_name = info["twb_name"]
            self.path = os.path.join(self.twbx_path, info["twb_name"])
            self.xml_doc = info["xml_doc"]
        elif ext == "twb":
            self.twbx_manifest = pd.DataFrame(columns=["name", "size_bytes", "modified", "type"])
            self.path = path
            self.xml_doc = parse_file(path)
        else:
            raise ValueError(f"Unsupported file type: {ext}")

        # Every fallback below uses the extractor's own correctly-columned
        # empty DataFrame (per AGENTS.md's "empty-input contract") rather
        # than a bare pd.DataFrame() -- a malformed-but-loadable workbook
        # should degrade to "this table has no rows" for its callers, not
        # "this table has no columns either."
        self.relations = _safe_call(extract_relations, pd.DataFrame(columns=_RELATION_COLUMNS), self.xml_doc)
        self.joins = _safe_call(extract_joins, pd.DataFrame(columns=_JOIN_COLUMNS), self.xml_doc)
        self.relationships = _safe_call(
            extract_relationships, pd.DataFrame(columns=_RELATIONSHIP_COLUMNS), self.xml_doc
        )
        self.fields = _safe_call(
            extract_columns_with_table_source, pd.DataFrame(columns=_FIELDS_COLUMNS), self.xml_doc
        )
        self.inferred_relationships = _safe_call(
            infer_implicit_relationships, pd.DataFrame(columns=_INFERRED_COLUMNS), self.fields
        )
        self.datasource_details = _safe_call(
            extract_datasource_details,
            {
                "data_sources": pd.DataFrame(columns=_DATASOURCE_COLUMNS),
                "parameters": pd.DataFrame(columns=_PARAMETER_COLUMNS),
                "all_sources": pd.DataFrame(columns=_DATASOURCE_COLUMNS),
            },
            self.xml_doc,
        )
        # Cache with include_parameters=True so get_calculated_fields()'s
        # own include_parameters flag can actually restore Parameters rows
        # later -- caching with the extractor's default (False) would drop
        # them permanently and make that flag a no-op (a bug present in the
        # upstream R package, not reproduced here).
        self.calculated_fields = _safe_call(
            extract_calculated_fields,
            pd.DataFrame(columns=_CALC_COLUMNS),
            self.xml_doc,
            include_parameters=True,
        )
        self.custom_sql = _safe_call(
            extract_custom_sql, pd.DataFrame(columns=_CUSTOM_SQL_COLUMNS), self.xml_doc
        )
        self.initial_sql = _safe_call(
            extract_initial_sql, pd.DataFrame(columns=_INITIAL_SQL_COLUMNS), self.xml_doc
        )
        self.published_refs = _safe_call(
            extract_published_refs, pd.DataFrame(columns=_PUBLISHED_COLUMNS), self.xml_doc
        )
        self.last_validation: Optional[dict] = None

    # --- TWBX helpers ---
    def get_twbx_manifest(self) -> pd.DataFrame:
        return self.twbx_manifest

    def get_twbx_extracts(self) -> pd.DataFrame:
        man = self.twbx_manifest
        if man.empty:
            return man
        return man[man["type"] == "extract"]

    def get_twbx_images(self) -> pd.DataFrame:
        man = self.twbx_manifest
        if man.empty:
            return man
        return man[man["type"] == "image"]

    # --- accessors ---
    def get_relations(self) -> pd.DataFrame:
        return internal_last(self.relations)

    def get_joins(self) -> pd.DataFrame:
        return self.joins

    def get_relationships(self) -> pd.DataFrame:
        return self.relationships

    def get_inferred_relationships(self) -> pd.DataFrame:
        return self.inferred_relationships

    def get_datasources(self) -> pd.DataFrame:
        return internal_last(self.datasource_details["data_sources"])

    def get_parameters(self) -> pd.DataFrame:
        return internal_last(self.datasource_details["parameters"])

    def get_datasources_all(self) -> pd.DataFrame:
        return self.datasource_details["all_sources"]

    def get_fields(self) -> pd.DataFrame:
        return internal_last(self.fields)

    def get_calculated_fields(
        self,
        include_parameters: bool = False,
    ) -> pd.DataFrame:
        df = self.calculated_fields
        if not include_parameters and not df.empty and "datasource" in df.columns:
            df = df[df["datasource"] != "Parameters"]
        return internal_last(df)

    def get_raw_fields(self) -> pd.DataFrame:
        return internal_last(_safe_call(extract_raw_fields, pd.DataFrame(columns=_RAW_COLUMNS), self.xml_doc))

    def get_custom_sql(self) -> pd.DataFrame:
        return self.custom_sql

    def get_initial_sql(self) -> pd.DataFrame:
        return internal_last(self.initial_sql)

    def get_published_refs(self) -> pd.DataFrame:
        return internal_last(self.published_refs)

    def get_dashboards(self) -> pd.DataFrame:
        return _safe_call(list_dashboards, pd.DataFrame(columns=_DASHBOARD_COLUMNS), self.xml_doc)

    def get_dashboard_summary(self) -> pd.DataFrame:
        """One row per dashboard with its sheet count, size, filters, parameter controls and actions."""
        return internal_last(_safe_call(dashboard_summary, pd.DataFrame(columns=_SUMMARY_COLUMNS), self.xml_doc))

    def get_dashboard_sheets(self, dashboard: Optional[str] = None) -> pd.DataFrame:
        return internal_last(_safe_call(
            dashboard_sheets,
            pd.DataFrame(columns=_SHEETS_COLUMNS),
            self.xml_doc,
            dashboard,
        ))

    def get_relationship_graph_dot(self, include_inferred: bool = False) -> str:
        """Render joins + relationships (and optionally inferred
        relationships) as a Graphviz DOT digraph string."""
        return to_dot(
            self.get_joins(),
            self.get_relationships(),
            self.get_inferred_relationships() if include_inferred else None,
        )

    def get_relationship_graph_data(self, include_inferred: bool = False) -> dict:
        """The relationship graph as `{"nodes": [...], "edges": [...]}` (see `graph.graph_data`)."""
        return graph_data(
            self.get_joins(),
            self.get_relationships(),
            self.get_inferred_relationships() if include_inferred else None,
        )

    def get_field_renames(self, reference=None, **kwargs) -> pd.DataFrame:
        """Suggested clean field names; see `rename.suggest_field_renames`."""
        from .rename import suggest_field_renames

        return internal_last(suggest_field_renames(self, reference=reference, **kwargs))

    def get_field_usage(self) -> pd.DataFrame:
        """Which sheets, dashboards and calculations use each field; see
        `usage.field_usage`."""
        from .usage import field_usage

        return internal_last(field_usage(self))

    def get_missing_references(self) -> pd.DataFrame:
        """Calculations that name a field the workbook does not have; see
        `usage.missing_references`."""
        from .usage import missing_references

        return internal_last(missing_references(self))

    def get_report(self) -> dict:
        """The workbook report card (summary, health checks); see `report.workbook_report`."""
        from .report import workbook_report

        return workbook_report(self)

    def get_renames(self, reference=None, **kwargs) -> pd.DataFrame:
        """Suggested clean names for everything in the report (fields,
        parameters, worksheets, dashboards, datasources, folders,
        hierarchies); see `rename.suggest_renames`."""
        from .rename import suggest_renames

        return internal_last(suggest_renames(self, reference=reference, **kwargs))

    def write_renamed_workbook(self, output_path=None, renames=None, overwrite=False, **kwargs) -> str:
        """Save a copy of the workbook with clean field names; returns its
        path. See `rename.apply_field_renames`."""
        from .rename import apply_field_renames

        return apply_field_renames(self, renames, output_path, overwrite, **kwargs)

    def _repr_html_(self) -> str:
        """Rich display for Jupyter/IPython: renders `get_overview()`."""
        overview_html = self.get_overview().to_html(index=False, na_rep="")
        return f"<div><b>TwbParser</b>: {os.path.basename(self.path or '')}</div>{overview_html}"

    # --- validator bridge ---
    def validate(self, error: bool = False) -> dict:
        v = validate_relationships(self)
        self.last_validation = v
        if error and not v["ok"]:
            raise ValueError("Validation failed. See parser.last_validation['issues'].")
        return v

    # --- summary ---
    def get_overview(self) -> pd.DataFrame:
        def _n(df):
            return 0 if df is None else len(df)

        n_dash = _n(self.get_dashboards())

        return pd.DataFrame(
            [
                {
                    "file": os.path.basename(self.path or ""),
                    "datasources": _n(self.get_datasources()),
                    "parameters": _n(self.get_parameters()),
                    "relationships": _n(self.relationships),
                    "calculated_fields": _n(self.get_calculated_fields()),
                    "raw_fields": _n(self.fields),
                    "inferred_relationships": _n(self.inferred_relationships),
                    "dashboards": n_dash,
                }
            ]
        )
