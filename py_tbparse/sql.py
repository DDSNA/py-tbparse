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
    """Port of `twb_custom_sql()`, plus the shape Tableau writes for custom SQL.

    Finds every `<relation formula="...">` node (the R package's only shape; `is_custom_sql` says whether
    it starts with SELECT or WITH) and every `<relation type="text">node text</relation>`, which is where
    Tableau keeps the query of a "New Custom SQL" table. A text relation is custom SQL by its type, so
    `is_custom_sql` is True. A text relation that the workbook repeats (the same name and query, for
    instance in the object model) is listed once; one with no text is left out.
    """
    rels = xml_doc.xpath("//relation[@formula or @type='text']")
    if not rels:
        return pd.DataFrame(columns=_CUSTOM_SQL_COLUMNS)

    rows = []
    seen = set()
    for r in rels:
        custom_sql = r.get("formula")
        if custom_sql is not None:
            is_custom = bool(_SELECT_OR_WITH_RE.match(custom_sql))
        else:
            custom_sql = "".join(r.itertext()).strip()
            key = (r.get("name"), custom_sql)
            if not custom_sql or key in seen:
                continue
            seen.add(key)
            is_custom = True
        rows.append(
            {
                "relation_name": r.get("name"),
                "relation_type": r.get("type"),
                "custom_sql": custom_sql,
                "is_custom_sql": is_custom,
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
