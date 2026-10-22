"""Small workbooks for the layout preview panel (#84, WP2 of docs/plan-84-layout-preview.md). Each builder returns the
text of a `.twb` with one dashboard that makes one case; `everything_workbook()` has all of them so one page load can
select any of them. Zone positions are on Tableau's 0 to 100000 grid unless the case is about leaving it.

A leaf zone is `Z(x, y, w, h, name, kind)`; the dashboards put their leaves in one root layout container (id 1), as
Tableau does for floating zones, so the answer of GET /dashboard-layout has a parent for each."""

from __future__ import annotations

from typing import NamedTuple, Optional
from xml.sax.saxutils import quoteattr


class Z(NamedTuple):
    x: Optional[int]
    y: Optional[int]
    w: Optional[int]
    h: Optional[int]
    name: str = ""
    kind: str = "sheet"          # sheet, filter, param, text, bitmap, web


def _attrs(z: Z) -> str:
    out = []
    if z.kind == "filter":
        out.append("type-v2='filter' param='[ds1].[none:Region:nk]'")
    elif z.kind == "param":
        out.append("type-v2='paramctrl' param='[Parameters].[Parameter 1]'")
    elif z.kind in ("text", "bitmap", "web"):
        out.append(f"type-v2='{z.kind}'")
    if z.name and z.kind in ("sheet", "text", "bitmap", "web"):
        out.append("name=" + quoteattr(z.name))
    elif z.name and z.kind == "filter":
        out.append("name=" + quoteattr(z.name))
    for key in "xywh":
        v = getattr(z, key)
        if v is not None:
            out.append(f"{key}='{v}'")
    return " ".join(out)


def dashboard(name: str, zones: list, size: str = "1200x800", inner: Optional[tuple] = None) -> str:
    """One `<dashboard>`. `inner=(first, last)` puts zones[first:last] into a second container (id 10) inside the root."""
    parts, zid = [], 2
    for i, z in enumerate(zones):
        if inner and i == inner[0]:
            parts.append("<zone id='10' type-v2='layout-flow' param='horz' x='0' y='0' w='100000' h='100000'>")
        parts.append(f"<zone id='{zid}' {_attrs(z)}/>")
        zid += 1
        if inner and i == inner[1] - 1:
            parts.append("</zone>")
    w, h = size.split("x")
    return (f"<dashboard name={quoteattr(name)}><size minwidth='{w}' minheight='{h}' maxwidth='{w}' maxheight='{h}'/>"
            "<zones><zone id='1' type-v2='layout-flow' param='vert' x='0' y='0' w='100000' h='100000'>"
            + "".join(parts) + "</zone></zones></dashboard>")


def workbook(*dashboards: str) -> str:
    return ("<?xml version='1.0' encoding='utf-8' ?>\n<workbook version='18.1'>\n"
            "  <datasources>\n"
            "    <datasource name='Parameters' hasconnection='false'>\n"
            "      <column caption='Top N' name='[Parameter 1]' datatype='integer' param-domain-type='range' role='measure'>\n"
            "        <calculation class='tableau' formula='5' /></column>\n"
            "    </datasource>\n"
            "    <datasource name='ds1'><column name='[Region]' datatype='string' role='dimension' /></datasource>\n"
            "  </datasources>\n"
            "  <worksheets><worksheet name='Sheet 1'><table><view /></table></worksheet></worksheets>\n"
            "  <dashboards>" + "".join(dashboards) + "</dashboards>\n</workbook>\n")


# ---- one case each -------------------------------------------------------------------------------------------------

def nested_dashboard() -> str:
    """A big sheet with a text zone and a filter completely inside it, a sheet inside the text zone (second level), and
    one free sheet that overlaps nothing (it sits in its own container, id 10)."""
    return dashboard("Nested", [
        Z(0, 0, 60000, 60000, "Big sheet"),
        Z(5000, 5000, 30000, 20000, "Caption", "text"),
        Z(40000, 5000, 15000, 20000, "Region", "filter"),
        Z(8000, 8000, 10000, 8000, "Inner chart"),
        Z(70000, 0, 30000, 30000, "Free sheet"),
    ], inner=(4, 5))


def crossing_dashboard() -> str:
    """Two sheets that cross at a corner (shared area 20.25% of the smaller), and a third that crosses both."""
    return dashboard("Crossing", [
        Z(0, 0, 40000, 40000, "Cross A"),
        Z(22000, 22000, 40000, 40000, "Cross B"),
        Z(10000, 35000, 40000, 40000, "Cross C"),
        Z(80000, 0, 20000, 20000, "Alone"),
    ])


def mixed_overlap_dashboard() -> str:
    """Nested and crossing together, two identical rectangles, and two of the same area at different places (tie rule)."""
    return dashboard("Mixed overlap", [
        Z(0, 0, 50000, 50000, "Outer"),
        Z(5000, 5000, 20000, 20000, "Inner"),
        Z(60000, 0, 30000, 30000, "Cross 1"),
        Z(80000, 20000, 20000, 30000, "Cross 2"),
        Z(0, 60000, 20000, 20000, "Same 1"),
        Z(0, 60000, 20000, 20000, "Same 2"),
        Z(30000, 60000, 15000, 15000, "Tie A"),
        Z(50000, 60000, 15000, 15000, "Tie B"),
        Z(70000, 70000, 30000, 30000, "Late big"),
    ])


def threshold_dashboard() -> str:
    """Three pairs around the 1% line: touching at an edge, sharing 0.9% of the smaller zone, sharing 1.2%."""
    return dashboard("Threshold", [
        Z(0, 0, 10000, 10000, "Edge 1"), Z(10000, 0, 10000, 10000, "Edge 2"),
        Z(30000, 0, 10000, 10000, "Under 1"), Z(39910, 0, 10000, 10000, "Under 2"),
        Z(60000, 0, 10000, 10000, "Over 1"), Z(69880, 0, 10000, 10000, "Over 2"),
    ])


def _chain(name: str, n: int, extra: Optional[list] = None) -> str:
    """n zones in a row, each crossing the next one only (n - 1 crossing pairs)."""
    zones = [Z(i * 8000, 0, 10000, 20000, f"Link {i + 1}") for i in range(n)]
    return dashboard(name, zones + (extra or []))


def edge_five_dashboard() -> str:
    return _chain("Edge five", 6)           # 5 crossing pairs: at the threshold, no overlap sentence


def edge_six_dashboard() -> str:
    return _chain("Edge six", 7)            # 6 crossing pairs: just above it


def busy_overlap_dashboard() -> str:
    """6 crossing pairs and one nested pair, so the overlap sentence has both counts."""
    return _chain("Busy overlap", 7, [Z(0, 30000, 40000, 40000, "Busy outer"), Z(5000, 35000, 10000, 10000, "Busy inner")])


def label_collision_dashboard() -> str:
    """An outer and an inner zone with long names whose top-left corners are 1000 units (a few pixels) apart, and a
    narrow zone with a name much longer than it is wide, one that only has room for its letter and one with room for nothing."""
    return dashboard("Label collision", [
        Z(0, 0, 80000, 60000, "Outer zone with a rather long name"),
        Z(1000, 1000, 50000, 30000, "Inner zone with a long name too"),
        Z(85000, 0, 12000, 20000, "A name far longer than its small zone"),
        Z(85000, 30000, 5000, 20000, "Narrow sheet"),        # about 29 px wide: the letter, not the name
        Z(92000, 30000, 1500, 20000, "Sliver"),              # under 12 px: nothing
    ])


def huge_extent_dashboard() -> str:
    """Past the 100000 grid (x+w = 250000, y+h = 180000), one zone starting below 0, a fixed pixel size."""
    return dashboard("Huge extent", [
        Z(0, 0, 150000, 100000, "Huge A"),
        Z(100000, 80000, 150000, 100000, "Huge B"),
        Z(-5000, -3000, 20000, 10000, "Negative start"),
    ], size="2000x1500")


def grid_dashboard() -> str:
    """Inside the grid, no overlap, no tiny zone: the control that has no marker and no extra sentence."""
    return dashboard("Grid", [
        Z(0, 0, 50000, 50000, "Left sheet"),
        Z(50000, 0, 50000, 50000, "Right sheet"),
        Z(0, 50000, 100000, 50000, "Bottom sheet"),
    ])


def tiny_zones_dashboard() -> str:
    """Widths 1000, 100 and 10 (5, 0.5 and 0.05 px at 500 px wide), and one of them inside a bigger zone."""
    return dashboard("Tiny zones", [
        Z(0, 0, 100000, 50000, "Base sheet"),
        Z(10000, 60000, 1000, 5000, "Tiny 1000"),
        Z(20000, 60000, 100, 5000, "Tiny 100"),
        Z(30000, 60000, 10, 5000, "Tiny 10"),
        Z(50000, 10000, 100, 2000, "Tiny inside"),
    ])


def many_overlap_dashboard(n: int = 250) -> str:
    """n zones; every fifth is a tiny zone inside the one before it, and the last one sticks out to x = 190500. With
    n = 250 the cap of 200 drops exactly the 50 tiny ones (the smallest)."""
    zones = []
    for i in range(n):
        x0, y0 = (i % 10) * 4000, (i // 10) * 4000
        if i % 5 == 4 and i == n - 1:
            zones.append(Z(190000, 2000, 500, 500, f"Tiny {i}"))
        elif i % 5 == 4:
            px, py = (zones[-1].x, zones[-1].y)
            zones.append(Z(px + 1000, py + 1000, 500, 500, f"Tiny {i}"))
        else:
            zones.append(Z(x0, y0, 3000, 3000, f"Zone {i}"))
    return dashboard("Many overlap", zones)


def unplaced_dashboards() -> str:
    return (dashboard("Half placed", [
        Z(0, 0, 50000, 50000, "Placed one"), Z(None, None, None, None, "No position"),
        Z(0, 50000, 0, 5000, "Zero width", "text"), Z(50000, 0, -10, 5000, "", "web"),
    ]) + dashboard("All unplaced", [Z(None, None, None, None, "Lost one"), Z(None, None, None, None, "Lost two", "text")]))


def hostile_names_dashboard() -> str:
    return dashboard("Hostile names", [
        Z(0, 0, 40000, 40000, "<script>window.__pwned = 1</script>"),
        Z(50000, 0, 40000, 40000, "Quote \" and ' and <b>bold</b> & more"),
        Z(0, 50000, 40000, 40000, "Ünï côdé 日本語"),
        Z(50000, 50000, 40000, 40000, "L" * 300),
    ])


# ---- one workbook per case, and one with everything ------------------------------------------------------------------

def nested_workbook() -> str: return workbook(nested_dashboard())
def crossing_workbook() -> str: return workbook(crossing_dashboard())
def mixed_overlap_workbook() -> str: return workbook(mixed_overlap_dashboard())
def label_collision_workbook() -> str: return workbook(label_collision_dashboard())
def huge_extent_workbook() -> str: return workbook(huge_extent_dashboard())
def grid_workbook() -> str: return workbook(grid_dashboard())
def tiny_zones_workbook() -> str: return workbook(tiny_zones_dashboard())
def many_overlap_workbook(n: int = 250) -> str: return workbook(many_overlap_dashboard(n))
def unplaced_workbook() -> str: return workbook(unplaced_dashboards())
def hostile_names_workbook() -> str: return workbook(hostile_names_dashboard())


def everything_workbook() -> str:
    return workbook(
        nested_dashboard(), crossing_dashboard(), mixed_overlap_dashboard(), threshold_dashboard(),
        edge_five_dashboard(), edge_six_dashboard(), busy_overlap_dashboard(), label_collision_dashboard(),
        huge_extent_dashboard(), grid_dashboard(), tiny_zones_dashboard(), many_overlap_dashboard(),
        unplaced_dashboards(), hostile_names_dashboard())
