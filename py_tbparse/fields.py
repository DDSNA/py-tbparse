"""Raw field extraction and implicit-relationship inference.

Ports of R/fields.R (`extract_columns_with_table_source`,
`infer_implicit_relationships`).
"""

from __future__ import annotations

import warnings

import pandas as pd

from ._clean import _TRAILING_HEX32, attr_safe_get, clean_field, clean_table

_DATASOURCE_XPATH = (
    "/workbook/datasources/datasource[@name and not(ancestor::view)]"
)

_FIELDS_COLUMNS = [
    "datasource", "name", "caption", "datatype", "role", "semantic_role",
    "table", "table_clean", "field_clean", "is_parameter",
]


def extract_columns_with_table_source(xml_doc) -> pd.DataFrame:
    """Port of `extract_columns_with_table_source()`."""
    ds_nodes = xml_doc.xpath(_DATASOURCE_XPATH)
    if not ds_nodes:
        return pd.DataFrame(columns=_FIELDS_COLUMNS)

    rows = []
    for ds_node in ds_nodes:
        ds_name = ds_node.get("name")
        cols = ds_node.xpath(".//column[@name]")
        for col in cols:
            a = dict(col.attrib)
            raw_table = attr_safe_get(a, "table")
            raw_name = attr_safe_get(a, "name")
            cap = attr_safe_get(a, "caption")

            rows.append(
                {
                    "datasource": ds_name,
                    "name": raw_name,
                    "caption": cap,
                    "datatype": attr_safe_get(a, "datatype"),
                    "role": attr_safe_get(a, "role"),
                    "semantic_role": attr_safe_get(a, "semantic-role"),
                    "table": _TRAILING_HEX32.sub("", raw_table) if raw_table else raw_table,
                    "table_clean": clean_table(raw_table),
                    "field_clean": clean_field(raw_name),
                    "is_parameter": attr_safe_get(a, "param-domain-type") is not None,
                }
            )

    if not rows:
        return pd.DataFrame(columns=_FIELDS_COLUMNS)
    return pd.DataFrame(rows, columns=_FIELDS_COLUMNS).drop_duplicates()


_INFERRED_COLUMNS = ["left_table", "left_field", "right_table", "right_field", "reason"]


def infer_implicit_relationships(fields_df: pd.DataFrame, max_pairs: int = 50000) -> pd.DataFrame:
    """Port of `infer_implicit_relationships()`.

    Suggests candidate join pairs by matching `semantic_role` and by
    matching (case-insensitive) field names across different tables.
    """
    empty = pd.DataFrame(columns=_INFERRED_COLUMNS)
    if fields_df is None or fields_df.empty:
        return empty

    df = fields_df.copy()
    if "is_parameter" not in df.columns:
        df["is_parameter"] = False
    for col in ("table_clean", "field_clean", "table", "name", "semantic_role"):
        if col not in df.columns:
            df[col] = None

    df["table_use"] = df["table_clean"].where(df["table_clean"].notna() & (df["table_clean"] != ""), None)
    df["table_use"] = df["table_use"].fillna(df["table"].apply(clean_table))
    df["field_use"] = df["field_clean"].where(df["field_clean"].notna() & (df["field_clean"] != ""), None)
    df["field_use"] = df["field_use"].fillna(df["name"].apply(clean_field))

    f = df[~df["is_parameter"].fillna(False).astype(bool)]
    f = f[f["table_use"].notna() & f["field_use"].notna()]
    f = f[(f["table_use"] != "") & (f["field_use"] != "")]
    f = f[["table_use", "field_use", "semantic_role"]].rename(
        columns={"table_use": "table", "field_use": "field"}
    ).drop_duplicates()

    if f.empty:
        return empty

    # --- match by semantic_role ---
    f_role = f[f["semantic_role"].notna() & (f["semantic_role"] != "")].rename(
        columns={"semantic_role": "role"}
    )
    if not f_role.empty:
        merged = f_role.merge(f_role, on="role", suffixes=("_l", "_r"))
        merged = merged[merged["table_l"] != merged["table_r"]]
        by_role = pd.DataFrame(
            {
                "left_table": merged["table_l"],
                "left_field": merged["field_l"],
                "right_table": merged["table_r"],
                "right_field": merged["field_r"],
                "reason": "matched semantic-role",
            }
        )
    else:
        by_role = pd.DataFrame(columns=_INFERRED_COLUMNS)

    # --- match by lowercased field name (dedup first to avoid blowup) ---
    f2 = f.copy()
    f2["field_lower"] = f2["field"].str.lower()
    f2 = f2.drop_duplicates(subset=["table", "field_lower"], keep="first")

    merged2 = f2.merge(f2, on="field_lower", suffixes=("_l", "_r"))
    merged2 = merged2[merged2["table_l"] != merged2["table_r"]]
    by_name = pd.DataFrame(
        {
            "left_table": merged2["table_l"],
            "left_field": merged2["field_l"],
            "right_table": merged2["table_r"],
            "right_field": merged2["field_r"],
            "reason": "matched field name",
        }
    )

    out = pd.concat([by_role, by_name], ignore_index=True)
    if out.empty:
        return empty

    def _key(row):
        a = f"{row['left_table']}.{row['left_field']}"
        b = f"{row['right_table']}.{row['right_field']}"
        return "||".join(sorted([a, b]))

    out["key"] = out.apply(_key, axis=1)
    out = out.drop_duplicates(subset="key", keep="first").drop(columns="key").reset_index(drop=True)

    if len(out) > max_pairs:
        out = out.head(max_pairs)
        warnings.warn(f"infer_implicit_relationships(): capped at max_pairs = {max_pairs}")

    return out
