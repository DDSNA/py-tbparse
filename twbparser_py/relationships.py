"""`<relation>` dump and modern (2020.2+) `<relationships>` extraction.

Ports of R/relationships.R (`extract_relations`,
`build_object_table_mapping`, `extract_relationships`).
"""

from __future__ import annotations

import re
from typing import Optional

import pandas as pd

from ._clean import attr_safe_get, clean_table

_BRACKET_RE = re.compile(r"\[[^\]]+\]")
_FUNC_START_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*\s*\(")
_FUNC_CALL_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\([^)]*\)")

_RELATION_COLUMNS = ["name", "table", "connection", "type", "join", "custom_sql"]
_RELATIONSHIP_COLUMNS = [
    "relationship_type", "left_table", "right_table", "left_field",
    "operator", "right_field", "left_is_calc", "right_is_calc",
]


def extract_relations(xml_doc) -> pd.DataFrame:
    """Port of `extract_relations()`."""
    nodes = xml_doc.xpath(".//relation")
    if not nodes:
        return pd.DataFrame(columns=_RELATION_COLUMNS)

    rows = []
    for node in nodes:
        attrs = dict(node.attrib)
        rows.append(
            {
                "name": attr_safe_get(attrs, "name"),
                "table": attr_safe_get(attrs, "table"),
                "connection": attr_safe_get(attrs, "connection"),
                "type": attr_safe_get(attrs, "type"),
                "join": attr_safe_get(attrs, "join"),
                # R's xml_text() always returns a string (never NULL), so
                # a relation with no text keeps "" rather than becoming NA.
                "custom_sql": "".join(node.itertext()),
            }
        )
    return pd.DataFrame(rows, columns=_RELATION_COLUMNS).drop_duplicates()


def _rel_field_expr(node) -> Optional[str]:
    """Port of `.rel_field_expr`."""
    if node is None:
        return None

    vals: list[str] = []
    vals.extend(dict(node.attrib).values())
    op = node.get("op")
    if op:
        vals.append(op)
    value = node.get("value")
    if value:
        vals.append(value)
    for expr in node.xpath(".//expression"):
        v = expr.get("op")
        if v:
            vals.append(v)
        v = expr.get("value")
        if v:
            vals.append(v)
    for calc in node.xpath(".//calculation"):
        v = calc.get("formula")
        if v:
            vals.append(v)

    vals = [v for v in vals if v]
    if not vals:
        return None

    br: list[str] = []
    for v in vals:
        br.extend(_BRACKET_RE.findall(v))

    if br:
        clean = [b.strip("[]") for b in br]
        idx_fun = [c for c in clean if _FUNC_START_RE.match(c)]
        if idx_fun:
            return idx_fun[-1]
        return clean[-1]

    fn: list[str] = []
    for v in vals:
        fn.extend(_FUNC_CALL_RE.findall(v))
    if fn:
        return fn[-1]
    return None


def build_object_table_mapping(xml_doc) -> dict:
    """Port of `build_object_table_mapping()`."""
    mapping: dict = {}

    objs = xml_doc.xpath("//*[contains(local-name(), 'object-graph')]//object[@id]")
    for obj in objs:
        obj_id = obj.get("id")
        cap = obj.get("caption")
        if obj_id and cap:
            mapping[obj_id] = clean_table(cap)

    for lt in xml_doc.xpath("//logical-table[@id]"):
        lt_id = lt.get("id")
        nm = lt.get("name")
        if lt_id and nm:
            mapping[lt_id] = clean_table(nm)

    for rel in xml_doc.xpath("//relation[@name]"):
        nm = rel.get("name")
        tb = rel.get("table")
        if nm:
            mapping[nm] = clean_table(tb or nm)

    return mapping


def extract_relationships(xml_doc) -> pd.DataFrame:
    """Port of `extract_relationships()` (Tableau 2020.2+ relationships)."""
    rel_nodes = xml_doc.xpath("//relationships/relationship")
    if not rel_nodes:
        return pd.DataFrame(columns=_RELATIONSHIP_COLUMNS)

    id_map = build_object_table_mapping(xml_doc)

    rows = []
    for rel_node in rel_nodes:
        first_ep = rel_node.find(".//first-end-point")
        second_ep = rel_node.find(".//second-end-point")
        e1 = first_ep.get("object-id") if first_ep is not None else None
        e2 = second_ep.get("object-id") if second_ep is not None else None
        left_table = clean_table(id_map.get(e1, e1))
        right_table = clean_table(id_map.get(e2, e2))

        candidates = rel_node.xpath(".//expression[@op][count(./expression) >= 2]")
        ex = candidates[0] if candidates else None
        if ex is None:
            continue

        # xpath predicate [@op] guarantees the attribute is present (though
        # possibly empty) -- preserve "" rather than forcing "=".
        op = ex.get("op")
        expr_children = ex.findall("./expression")
        lhs = expr_children[0] if len(expr_children) > 0 else None
        rhs = expr_children[1] if len(expr_children) > 1 else None
        left_field = _rel_field_expr(lhs)
        right_field = _rel_field_expr(rhs)

        rows.append(
            {
                "relationship_type": "Relationship",
                "left_table": left_table,
                "right_table": right_table,
                "left_field": left_field,
                "operator": op,
                "right_field": right_field,
                "left_is_calc": bool(left_field and _FUNC_START_RE.match(left_field)),
                "right_is_calc": bool(right_field and _FUNC_START_RE.match(right_field)),
            }
        )

    if not rows:
        return pd.DataFrame(columns=_RELATIONSHIP_COLUMNS)

    df = pd.DataFrame(rows, columns=_RELATIONSHIP_COLUMNS)
    df = df[df["left_field"].notna() & df["right_field"].notna()]
    df = df[(df["left_field"] != "") & (df["right_field"] != "")]
    return df.drop_duplicates().reset_index(drop=True)
