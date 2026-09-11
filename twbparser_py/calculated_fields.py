"""Calculated-field and raw-field (non-calc, non-parameter) extraction.

Ports of R/calculated_fields.R (`extract_calculated_fields`,
`extract_raw_fields`).
"""

from __future__ import annotations

import re

import pandas as pd

from ._clean import attr_safe_get, clean_table, strip_brackets

_DATASOURCE_XPATH = (
    "/workbook/datasources/datasource[@name and not(ancestor::view)]"
)

_TABLE_CALC_RE = re.compile(
    r"\b(WINDOW_|LOOKUP\(|INDEX\(|RUNNING_|RANK\(|PREVIOUS_VALUE\()"
)

_CALC_COLUMNS = [
    "datasource", "name", "tableau_internal_name", "datatype", "role",
    "formula", "calc_class", "is_table_calc", "table", "table_clean",
]

_RAW_COLUMNS = [
    "datasource", "name", "tableau_internal_name", "datatype", "role",
    "is_hidden", "is_parameter", "table", "table_clean",
]


def extract_calculated_fields(xml_doc, include_parameters: bool = False) -> pd.DataFrame:
    """Port of `extract_calculated_fields()`."""
    ds_nodes = xml_doc.xpath(_DATASOURCE_XPATH)
    if not ds_nodes:
        return pd.DataFrame(columns=_CALC_COLUMNS)

    rows = []
    for ds in ds_nodes:
        ds_name = ds.get("name")
        if not include_parameters and ds_name == "Parameters":
            continue

        cols = ds.xpath(".//column[@name and not(@param-domain-type)][.//calculation]")
        for col in cols:
            ca = dict(col.attrib)
            calc = col.find(".//calculation")
            fa = dict(calc.attrib) if calc is not None else {}

            internal = attr_safe_get(ca, "name")
            caption = attr_safe_get(ca, "caption")
            raw_tbl = attr_safe_get(ca, "table")

            formula = attr_safe_get(fa, "formula")
            calc_class = attr_safe_get(fa, "class")

            is_tbl = bool(formula) and bool(_TABLE_CALC_RE.search(formula))

            rows.append(
                {
                    "datasource": ds_name,
                    "name": caption if caption else strip_brackets(internal),
                    "tableau_internal_name": internal,
                    "datatype": attr_safe_get(ca, "datatype"),
                    "role": attr_safe_get(ca, "role"),
                    "formula": formula,
                    "calc_class": calc_class,
                    "is_table_calc": is_tbl,
                    "table": raw_tbl,
                    "table_clean": clean_table(raw_tbl),
                }
            )

    if not rows:
        return pd.DataFrame(columns=_CALC_COLUMNS)
    return pd.DataFrame(rows, columns=_CALC_COLUMNS).drop_duplicates()


def extract_raw_fields(xml_doc) -> pd.DataFrame:
    """Port of `extract_raw_fields()`."""
    ds_nodes = xml_doc.xpath(_DATASOURCE_XPATH)
    if not ds_nodes:
        return pd.DataFrame(columns=_RAW_COLUMNS)

    rows = []
    for ds in ds_nodes:
        ds_name = ds.get("name")
        nodes = ds.xpath(".//column[@name and not(.//calculation) and not(@param-domain-type)]")
        for node in nodes:
            a = dict(node.attrib)
            internal = attr_safe_get(a, "name")
            caption = attr_safe_get(a, "caption")
            raw_tbl = attr_safe_get(a, "table")

            rows.append(
                {
                    "datasource": ds_name,
                    "name": caption if caption else strip_brackets(internal),
                    "tableau_internal_name": internal,
                    "datatype": attr_safe_get(a, "datatype"),
                    "role": attr_safe_get(a, "role"),
                    "is_hidden": attr_safe_get(a, "hidden", "false") in ("true", "1"),
                    "is_parameter": False,
                    "table": raw_tbl,
                    "table_clean": clean_table(raw_tbl),
                }
            )

    if not rows:
        return pd.DataFrame(columns=_RAW_COLUMNS)
    return pd.DataFrame(rows, columns=_RAW_COLUMNS).drop_duplicates()
