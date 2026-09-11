"""Heuristic detection of published (server-side) data source references.

Port of R/published.R (`twb_published_refs`).
"""

from __future__ import annotations

import re

import pandas as pd

_PUBLISHED_MARKER_RE = re.compile(
    r"published|tableau server|tableau cloud|catalog-id|content-url", re.IGNORECASE
)

_PUBLISHED_COLUMNS = ["name", "caption", "hasconn", "likely_published", "hints"]


def extract_published_refs(xml_doc) -> pd.DataFrame:
    """Port of `twb_published_refs()`.

    Inspects `<datasource>` nodes and heuristically flags those that
    reference a published (server-side) source rather than an embedded
    one.
    """
    dsn = xml_doc.xpath("//datasource")
    if not dsn:
        return pd.DataFrame(columns=_PUBLISHED_COLUMNS)

    rows = []
    for ds in dsn:
        hasconn = ds.get("hasconnection")
        raw = "".join(ds.itertext())

        likely_published = hasconn in ("false", "0") or bool(_PUBLISHED_MARKER_RE.search(raw))
        hints = (
            "hasconnection=false or published markers present"
            if likely_published
            else "embedded or no published markers"
        )

        rows.append(
            {
                "name": ds.get("name"),
                "caption": ds.get("caption"),
                "hasconn": hasconn,
                "likely_published": likely_published,
                "hints": hints,
            }
        )

    return pd.DataFrame(rows, columns=_PUBLISHED_COLUMNS)
