"""Custom SQL and initial-SQL extraction.

Port of R/sql.R (`twb_custom_sql`, `twb_initial_sql`).
"""

from __future__ import annotations

import re

import pandas as pd

_SELECT_OR_WITH_RE = re.compile(r"^\s*(select|with)\b", re.IGNORECASE)

_CUSTOM_SQL_COLUMNS = ["relation_name", "relation_type", "custom_sql", "is_custom_sql"]
_INITIAL_SQL_COLUMNS = ["connection_id", "initial_sql"]


def extract_custom_sql(xml_doc) -> pd.DataFrame:
    """Port of `twb_custom_sql()`.

    Finds every `<relation formula="...">` node that looks like a SQL
    statement.
    """
    rels = xml_doc.xpath("//relation[@formula]")
    if not rels:
        return pd.DataFrame(columns=_CUSTOM_SQL_COLUMNS)

    rows = []
    for r in rels:
        custom_sql = r.get("formula")
        if custom_sql is None:
            continue
        rows.append(
            {
                "relation_name": r.get("name"),
                "relation_type": r.get("type"),
                "custom_sql": custom_sql,
                "is_custom_sql": bool(_SELECT_OR_WITH_RE.match(custom_sql)),
            }
        )

    if not rows:
        return pd.DataFrame(columns=_CUSTOM_SQL_COLUMNS)
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
