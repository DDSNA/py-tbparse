"""Datasource / connection / parameter extraction.

Ports of R/datasources.R (`extract_named_connections`,
`extract_datasource_details`) and the parameter half of
R/calculated_fields.R (`extract_parameters`).
"""

from __future__ import annotations

import re

import pandas as pd

from ._clean import attr_safe_get, basename_safe, clean_table, strip_brackets


def _coalesce(*vals):
    """First non-None value, unlike Python's `or` this keeps "" (matches
    R's `dplyr::coalesce()`/`%||%`, which only substitute on NA/NULL, not
    on empty strings)."""
    for v in vals:
        if v is not None:
            return v
    return None

_ATHENA_RE = re.compile(r"athena\.", re.IGNORECASE)
_ATHENA_REGION_RE = re.compile(r".*athena\.([^.]+)\..*")
_TRAILING_HEX32 = re.compile(r"_[0-9A-Fa-f]{32}$")

_DATASOURCE_COLUMNS = [
    "datasource", "primary_table", "connection_id", "connection_caption",
    "connection_class", "connection_target", "datasource_name",
    "field_count", "connection_type", "location",
]
_PARAMETER_COLUMNS = [
    "datasource", "name", "tableau_internal_name", "datatype", "role",
    "parameter_type", "allowable_type", "current_value", "is_parameter",
    "table", "table_clean",
]

_DATASOURCE_XPATH = (
    "/workbook/datasources/datasource[@name and not(ancestor::view)]"
)


def _location_named(cls, target, dbname, schema, region, fn) -> str:
    """Port of the `case_when` block in `extract_named_connections`."""
    if cls == "athena":
        label = "Athena"
        if region:
            label += f" ({region})"
        label += ": " + (dbname or "<catalog>")
        if schema:
            label += f".{schema}"
        return label
    if cls == "ogrdirect":
        return f"Shapefile: {basename_safe(fn)}"
    if cls == "excel":
        return f"Excel: {basename_safe(fn)}"
    if cls == "textscan":
        return f"CSV: {basename_safe(fn)}"
    cls_title = (cls or "Unknown").title()
    return f"No Known File {cls_title}: {target or '<unknown>'}"


def extract_named_connections(xml_doc) -> pd.DataFrame:
    """Port of `extract_named_connections()`."""
    ncs = xml_doc.xpath("//named-connection")
    if not ncs:
        return pd.DataFrame()

    rows = []
    for nc in ncs:
        conn_id = nc.get("name")
        cap = nc.get("caption") or conn_id

        conn = nc.find("./connection")
        a = dict(conn.attrib) if conn is not None else {}

        cls = attr_safe_get(a, "class")
        server = attr_safe_get(a, "server")
        directory = attr_safe_get(a, "directory")
        fn = attr_safe_get(a, "filename")
        dbname = attr_safe_get(a, "dbname")
        schema = attr_safe_get(a, "schema")
        warehouse = attr_safe_get(a, "warehouse")

        target = _coalesce(server, directory, fn)

        region = None
        if server and _ATHENA_RE.search(server):
            # R's sub() returns the original (lowercased) string unchanged
            # when the finer region pattern doesn't match, rather than NA.
            low = server.lower()
            m = _ATHENA_REGION_RE.match(low)
            region = m.group(1) if m else low

        rows.append(
            {
                "connection_id": conn_id,
                "connection_caption": cap,
                "connection_class": cls,
                "connection_target": target,
                "dbname": dbname,
                "schema": schema,
                "warehouse": warehouse,
                "region": region,
                "filename": fn,
                "location_named": _location_named(cls, target, dbname, schema, region, fn),
            }
        )
    return pd.DataFrame(rows)


def extract_parameters(xml_doc) -> pd.DataFrame:
    """Port of `extract_parameters()`."""
    ds_nodes = xml_doc.xpath(_DATASOURCE_XPATH)
    if not ds_nodes:
        return pd.DataFrame(columns=_PARAMETER_COLUMNS)

    rows = []
    for ds in ds_nodes:
        ds_name = ds.get("name")
        nodes = ds.xpath(".//column[@param-domain-type]")
        for node in nodes:
            a = dict(node.attrib)
            internal = attr_safe_get(a, "name")
            caption = attr_safe_get(a, "caption")
            raw_tbl = attr_safe_get(a, "table")

            cur = node.find(".//current-value")
            cur_val = cur.get("value") if cur is not None else None

            rows.append(
                {
                    "datasource": ds_name,
                    "name": caption if caption else strip_brackets(internal),
                    "tableau_internal_name": internal,
                    "datatype": attr_safe_get(a, "datatype"),
                    "role": attr_safe_get(a, "role"),
                    "parameter_type": attr_safe_get(a, "param-domain-type"),
                    "allowable_type": attr_safe_get(a, "data-type"),
                    "current_value": cur_val,
                    "is_parameter": True,
                    "table": raw_tbl,
                    "table_clean": clean_table(raw_tbl),
                }
            )
    return pd.DataFrame(rows, columns=_PARAMETER_COLUMNS).drop_duplicates()


def extract_datasource_details(xml_doc) -> dict:
    """Port of `extract_datasource_details()`.

    Returns a dict with `data_sources`, `parameters`, `all_sources`.
    """
    rels = xml_doc.xpath(
        "//*[contains(local-name(), 'object-graph')]"
        "//object//properties[@context='']/relation[@type='table']"
    )
    if rels:
        runtime_ds = pd.DataFrame(
            {
                "datasource": [r.get("name") for r in rels],
                "primary_table": [r.get("table") for r in rels],
                "connection_id": [r.get("connection") for r in rels],
            }
        ).drop_duplicates()
    else:
        runtime_ds = pd.DataFrame(
            columns=["datasource", "primary_table", "connection_id"]
        )

    conn_meta = extract_named_connections(xml_doc)
    need_conn_cols = [
        "connection_id", "connection_class", "connection_caption",
        "connection_target", "location_named",
    ]
    for col in need_conn_cols:
        if col not in conn_meta.columns:
            conn_meta[col] = pd.Series(dtype="object")
    conn_meta = conn_meta[[c for c in need_conn_cols if c in conn_meta.columns]]

    defs = xml_doc.xpath(_DATASOURCE_XPATH)
    meta_rows = []
    for ds in defs:
        nm = ds.get("name")
        ncol = len(ds.findall(".//column"))

        tbl = ds.find(".//relation[@type='table']")
        pt = tbl.get("table") if tbl is not None else None

        conn = ds.find(".//connection")
        a = dict(conn.attrib) if conn is not None else {}

        cls = attr_safe_get(a, "class", "inline")
        server = attr_safe_get(a, "server")
        filename = attr_safe_get(a, "filename")

        server_label = server if server else "<unknown>"

        def _file_label(x):
            return basename_safe(x) if x else "<unknown>"

        if cls == "excel":
            location = f"Excel: {_file_label(filename)}"
        elif cls == "textscan":
            location = f"CSV: {_file_label(filename)}"
        elif cls == "federated":
            location = f"Federated: {server_label}"
        else:
            location = "Unknown"

        meta_rows.append(
            {
                "datasource_name": nm,
                "primary_table": pt,
                "field_count": ncol,
                "connection_type": cls,
                "location": location,
            }
        )

    need_meta_cols = [
        "primary_table", "datasource_name", "field_count",
        "connection_type", "location",
    ]
    meta = pd.DataFrame(meta_rows, columns=need_meta_cols)

    final = runtime_ds.merge(conn_meta, on="connection_id", how="left")
    final = final.merge(meta, on="primary_table", how="left")

    if "location_named" in final.columns:
        final["location"] = final["location"].where(
            final["location"].notna(), final["location_named"]
        )
    if "connection_class" in final.columns:
        final["connection_type"] = final["connection_type"].where(
            final["connection_type"].notna(), final["connection_class"]
        )
    final["field_count"] = final.get("field_count", pd.Series(dtype="float64")).fillna(0).astype(int)
    if "connection_caption" in final.columns:
        final["datasource_name"] = final["datasource_name"].where(
            final["datasource_name"].notna(), final["connection_caption"]
        )

    for c in _DATASOURCE_COLUMNS:
        if c not in final.columns:
            final[c] = pd.Series(dtype="object")
    final = final[_DATASOURCE_COLUMNS]

    try:
        params = extract_parameters(xml_doc)
    except Exception:
        params = pd.DataFrame()

    return {"data_sources": final, "parameters": params, "all_sources": final}
