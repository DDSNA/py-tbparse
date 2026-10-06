"""Custom SQL and initial-SQL extraction.

Port of R/sql.R (`twb_custom_sql`, `twb_initial_sql`).
"""

from __future__ import annotations

import re
from typing import Iterator

import pandas as pd

_SELECT_OR_WITH_RE = re.compile(r"^\s*(select|with)\b", re.IGNORECASE)

_CUSTOM_SQL_COLUMNS = ["relation_name", "relation_type", "custom_sql", "is_custom_sql"]
_INITIAL_SQL_COLUMNS = ["connection_id", "initial_sql"]


def custom_sql_relations(xml_doc) -> Iterator[tuple]:
    """`(relation element, SQL text, is_custom_sql)` for every relation that carries a query, in document order.

    Two shapes: `<relation formula="...">` (the R package's only one; custom SQL when the text starts with SELECT
    or WITH) and `<relation type="text">query</relation>`, where Tableau keeps the query of a "New Custom SQL"
    table (custom SQL by its type; one with no text is skipped). Nothing is merged here: Tableau repeats a
    relation (in the object model, for instance), and a caller merges by whatever it names the query by."""
    for r in xml_doc.xpath("//relation[@formula or @type='text']"):
        formula = r.get("formula")
        if formula is not None:
            yield r, formula, r.get("type") == "text" or bool(_SELECT_OR_WITH_RE.match(formula))
        else:
            text = "".join(r.itertext()).strip()
            if text:
                yield r, text, True


def extract_custom_sql(xml_doc) -> pd.DataFrame:
    """Port of `twb_custom_sql()`, plus the shape Tableau writes for custom SQL (see `custom_sql_relations`).

    One row per relation that carries a query; a `type="text"` relation that the workbook repeats with the same
    name and query is listed once."""
    rows = []
    seen = set()
    for r, sql, is_custom in custom_sql_relations(xml_doc):
        if r.get("formula") is None:
            key = (r.get("name"), sql)
            if key in seen:
                continue
            seen.add(key)
        rows.append(
            {
                "relation_name": r.get("name"),
                "relation_type": r.get("type"),
                "custom_sql": sql,
                "is_custom_sql": is_custom,
            }
        )
    return pd.DataFrame(rows, columns=_CUSTOM_SQL_COLUMNS)


def extract_initial_sql(xml_doc) -> pd.DataFrame:
    """Port of `twb_initial_sql()`.

    Returns any `<initial-sql>` nodes found inside `<connection>` or
    `<named-connection>` elements.
    """
    nodes = xml_doc.xpath(
        "//connection/initial-sql | //named-connection/initial-sql"
    )
    if not nodes:
        return pd.DataFrame(columns=_INITIAL_SQL_COLUMNS)

    rows = []
    for node in nodes:
        parent = node.getparent()
        # R's `xml_attr(xml_parent(nodes), "name") %||% xml_attr(..., "caption")`
        # operates on the whole name-vector at once: since xml_attr()
        # never returns NULL for a non-empty nodeset (missing attributes
        # become NA elements, not a NULL vector), `%||%` never actually
        # substitutes the caption vector -- it's dead code in the R
        # source. Match that (quirky but real) behavior: use only `name`,
        # with no per-node caption fallback.
        conn_id = parent.get("name") if parent is not None else None
        rows.append(
            {
                "connection_id": conn_id,
                "initial_sql": "".join(node.itertext()),
            }
        )
    return pd.DataFrame(rows, columns=_INITIAL_SQL_COLUMNS)
