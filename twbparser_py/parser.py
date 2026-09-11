"""The main `TwbParser` façade, ported from R6 class `TwbParser` in
R/twb_parser.R.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

import pandas as pd
from lxml import etree

from ._xml import extract_twb_from_twbx
from .calculated_fields import extract_calculated_fields, extract_raw_fields
from .dashboards import dashboard_sheets, list_dashboards
from .datasources import extract_datasource_details
from .fields import extract_columns_with_table_source, infer_implicit_relationships
from .graph import to_dot
from .joins import extract_joins
from .published import extract_published_refs
from .relationships import extract_relations, extract_relationships
from .sql import extract_custom_sql, extract_initial_sql
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
            info = extract_twb_from_twbx(path, extract_all=False)
            twb_path = info["twb_path"]
            self.twbx_dir = info["exdir"]
            self.twbx_path = info["twbx_path"]
            self.twbx_manifest = info["manifest"]
        elif ext == "twb":
            twb_path = path
            self.twbx_manifest = pd.DataFrame(columns=["name", "size_bytes", "modified", "type"])
        else:
            raise ValueError(f"Unsupported file type: {ext}")

        self.path = twb_path
        self.xml_doc = etree.parse(str(twb_path))

        self.relations = _safe_call(extract_relations, pd.DataFrame(), self.xml_doc)
        self.joins = _safe_call(extract_joins, pd.DataFrame(), self.xml_doc)
        self.relationships = _safe_call(extract_relationships, pd.DataFrame(), self.xml_doc)
        self.fields = _safe_call(extract_columns_with_table_source, pd.DataFrame(), self.xml_doc)
        self.inferred_relationships = _safe_call(
            infer_implicit_relationships, pd.DataFrame(), self.fields
        )
        self.datasource_details = _safe_call(
            extract_datasource_details,
            {"data_sources": pd.DataFrame(), "parameters": pd.DataFrame(), "all_sources": pd.DataFrame()},
            self.xml_doc,
        )
        # Cache with include_parameters=True so get_calculated_fields()'s
        # own include_parameters flag can actually restore Parameters rows
        # later -- caching with the extractor's default (False) would drop
        # them permanently and make that flag a no-op (a bug present in the
        # upstream R package, not reproduced here).
        self.calculated_fields = _safe_call(
            extract_calculated_fields, pd.DataFrame(), self.xml_doc, include_parameters=True
        )
        self.custom_sql = _safe_call(extract_custom_sql, pd.DataFrame(), self.xml_doc)
        self.initial_sql = _safe_call(extract_initial_sql, pd.DataFrame(), self.xml_doc)
        self.published_refs = _safe_call(extract_published_refs, pd.DataFrame(), self.xml_doc)
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
        return self.relations

    def get_joins(self) -> pd.DataFrame:
        return self.joins

    def get_relationships(self) -> pd.DataFrame:
        return self.relationships

    def get_inferred_relationships(self) -> pd.DataFrame:
        return self.inferred_relationships

    def get_datasources(self) -> pd.DataFrame:
        return self.datasource_details["data_sources"]

    def get_parameters(self) -> pd.DataFrame:
        return self.datasource_details["parameters"]

    def get_datasources_all(self) -> pd.DataFrame:
        return self.datasource_details["all_sources"]

    def get_fields(self) -> pd.DataFrame:
        return self.fields

    def get_calculated_fields(
        self,
        include_parameters: bool = False,
    ) -> pd.DataFrame:
        df = self.calculated_fields
        if not include_parameters and not df.empty and "datasource" in df.columns:
            df = df[df["datasource"] != "Parameters"]
        return df

    def get_raw_fields(self) -> pd.DataFrame:
        return _safe_call(extract_raw_fields, pd.DataFrame(), self.xml_doc)

    def get_custom_sql(self) -> pd.DataFrame:
        return self.custom_sql

    def get_initial_sql(self) -> pd.DataFrame:
        return self.initial_sql

    def get_published_refs(self) -> pd.DataFrame:
        return self.published_refs

    def get_dashboards(self) -> pd.DataFrame:
        return _safe_call(list_dashboards, pd.DataFrame(columns=["name"]), self.xml_doc)

    def get_dashboard_sheets(self, dashboard: Optional[str] = None) -> pd.DataFrame:
        return _safe_call(
            dashboard_sheets,
            pd.DataFrame(columns=["dashboard", "sheet", "zone_id", "x", "y", "w", "h"]),
            self.xml_doc,
            dashboard,
        )

    def get_relationship_graph_dot(self, include_inferred: bool = False) -> str:
        """Render joins + relationships (and optionally inferred
        relationships) as a Graphviz DOT digraph string."""
        return to_dot(
            self.get_joins(),
            self.get_relationships(),
            self.get_inferred_relationships() if include_inferred else None,
        )

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
