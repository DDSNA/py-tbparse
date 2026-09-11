"""Dashboard listing and worksheet-placement extraction.

Port of R/dashboard_details.R (`twb_dashboard_sheets`) plus a simple
dashboard-name lister (mirrors `.ins_dashboards`).
"""

from __future__ import annotations

from typing import Optional

import pandas as pd

_DASHBOARD_COLUMNS = ["name"]
_SHEETS_COLUMNS = ["dashboard", "sheet", "zone_id", "x", "y", "w", "h"]


def _int_attr(node, name) -> Optional[int]:
    """Port of `.int_attr`."""
    val = node.get(name)
    if val is None:
        return None
    try:
        return int(val)
    except (TypeError, ValueError):
        return None


def _dashboard_xpath(dashboard: Optional[str]) -> str:
    if dashboard is None:
        return ".//dashboard"
    safe = dashboard.replace("'", "")
    return f".//dashboard[@name='{safe}']"


def list_dashboards(xml_doc) -> pd.DataFrame:
    """List dashboard names in the workbook."""
    nodes = xml_doc.xpath(".//dashboard")
    names = [n.get("name") for n in nodes if n.get("name")]
    return pd.DataFrame({"name": sorted(set(names))}, columns=_DASHBOARD_COLUMNS)


def dashboard_sheets(xml_doc, dashboard: Optional[str] = None) -> pd.DataFrame:
    """Port of `twb_dashboard_sheets()` / `.ins_dashboard_sheets`."""
    d_nodes = xml_doc.xpath(_dashboard_xpath(dashboard))
    if not d_nodes:
        return pd.DataFrame(columns=_SHEETS_COLUMNS)

    rows = []
    for d in d_nodes:
        d_name = d.get("name")
        ws_zones = d.xpath(".//zone[@worksheet]")
        for z in ws_zones:
            rows.append(
                {
                    "dashboard": d_name,
                    "sheet": z.get("worksheet"),
                    "zone_id": z.get("id"),
                    "x": _int_attr(z, "x"),
                    "y": _int_attr(z, "y"),
                    "w": _int_attr(z, "w"),
                    "h": _int_attr(z, "h"),
                }
            )

    if not rows:
        return pd.DataFrame(columns=_SHEETS_COLUMNS)

    df = pd.DataFrame(rows, columns=_SHEETS_COLUMNS)
    return df.sort_values(["dashboard", "sheet"]).reset_index(drop=True)
