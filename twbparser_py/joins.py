"""Legacy join-clause extraction (`<relation type="join">`).

Port of R/joins.R (`extract_joins`).
"""

from __future__ import annotations

import re

import pandas as pd

from ._clean import attr_safe_get, clean_field, clean_table

_BRACKET_RE = re.compile(r"\[[^\]]+\]")

_JOIN_COLUMNS = ["join_type", "left_table", "left_field", "operator", "right_table", "right_field"]


def _field_from_expr(node) -> str | None:
    """Port of `.j_field_from_expr`."""
    if node is None:
        return None
    cand = [node.get("op"), node.get("field"), node.get("value")]
    cand = [c for c in cand if c]
    if not cand:
        return None
    raw = max(cand, key=len)
    matches = _BRACKET_RE.findall(raw)
    token = matches[-1] if matches else raw
    return clean_field(token)


def extract_joins(xml_doc) -> pd.DataFrame:
    """Port of `extract_joins()`."""
    join_nodes = xml_doc.xpath(".//relation[@type='join']")
    if not join_nodes:
        return pd.DataFrame(columns=_JOIN_COLUMNS)

    rows = []
    for join_node in join_nodes:
        join_type = attr_safe_get(dict(join_node.attrib), "join")

        # 1) Preferred: clause/column style
        for cl in join_node.xpath(".//clause"):
            op = attr_safe_get(dict(cl.attrib), "op", "=")
            cols = cl.xpath(".//column")
            if len(cols) == 2:
                left_tbl = clean_table(attr_safe_get(dict(cols[0].attrib), "table"))
                left_fld = clean_field(attr_safe_get(dict(cols[0].attrib), "name"))
                right_tbl = clean_table(attr_safe_get(dict(cols[1].attrib), "table"))
                right_fld = clean_field(attr_safe_get(dict(cols[1].attrib), "name"))
                rows.append(
                    {
                        "join_type": join_type,
                        "left_table": left_tbl,
                        "left_field": left_fld,
                        "operator": op,
                        "right_table": right_tbl,
                        "right_field": right_fld,
                    }
                )

        # 2) Fallback: expression-based join conditions (binary expressions)
        for en in join_node.xpath(".//expression[@op]"):
            kids = en.xpath("./expression")
            if len(kids) != 2:
                continue
            # xpath predicate [@op] guarantees the attribute is present
            # (though possibly empty) -- preserve "" rather than forcing "="
            # (matches R, where xml_attr() already returned a non-NULL
            # string here, so `%||%` never substitutes).
            op = en.get("op")
            lf = _field_from_expr(kids[0])
            rf = _field_from_expr(kids[1])
            if not lf or not rf:
                continue

            lt = clean_table(kids[0].get("table"))
            rt = clean_table(kids[1].get("table"))

            rows.append(
                {
                    "join_type": join_type,
                    "left_table": lt,
                    "left_field": lf,
                    "operator": op,
                    "right_table": rt,
                    "right_field": rf,
                }
            )

    if not rows:
        return pd.DataFrame(columns=_JOIN_COLUMNS)

    df = pd.DataFrame(rows, columns=_JOIN_COLUMNS)
    df = df[df["left_field"].notna() & df["right_field"].notna()]
    df = df[(df["left_field"] != "") & (df["right_field"] != "")]
    df["operator"] = df["operator"].fillna("=")
    return df.drop_duplicates().reset_index(drop=True)
