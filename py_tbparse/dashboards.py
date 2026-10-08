"""Dashboard listing and worksheet-placement extraction.

Port of R/dashboard_details.R (`twb_dashboard_sheets`). `list_dashboards`
is a deliberately simplified name-only lister for this v1 subset, not a
full port of R's `.ins_dashboards` (which also reports per-dashboard
worksheet/zone counts) -- see AGENTS.md's v2 scope.
"""

from __future__ import annotations

import re
from typing import Optional

import pandas as pd

_DASHBOARD_COLUMNS = ["name"]
_SUMMARY_COLUMNS = ["name", "worksheets", "sheets", "size", "filters", "parameters", "actions",
                    "images", "texts", "webs", "filter_fields", "parameter_names"]
_SHEETS_COLUMNS = ["dashboard", "sheet", "zone_id", "x", "y", "w", "h"]
# Zones of these kinds are named after the worksheet they show or control (`sheet` and `worksheet` are what some
# generated workbooks write; Tableau itself writes no type for a sheet).
_SHEET_ZONE_TYPES = {"sheet", "filter", "color", "size", "shape", "highlighter", "map", "legend"}
CONTAINER_KINDS = ("layout-basic", "layout-flow")
_FCP = "_.fcp."


def zone_kind(z) -> str:
    """What a `<zone>` is: `sheet`, `filter`, `color`, `size`, `paramctrl`, `text`, `title`, `empty`, `bitmap`,
    `web`, `layout-basic`, `layout-flow`, ... or `unknown`. Tableau stores the kind in `type-v2` (newer files),
    `type` (older ones), or, in some files, only in a feature-flag attribute such as
    `_.fcp.SetMembershipControl.true...type-v2`. A zone with a name and none of these is a sheet; `worksheet`
    (written by some generators) is read as `sheet`."""
    kind = z.get("type-v2") or z.get("type")
    if not kind:
        flagged = {k: v for k, v in z.attrib.items() if k.startswith(_FCP) and v}
        for suffix in ("type-v2", "type"):
            hit = sorted(k for k in flagged if k.endswith("..." + suffix))
            if hit:
                kind = flagged[hit[0]]
                break
    if kind == "worksheet":
        return "sheet"
    if kind:
        return kind
    return "sheet" if (z.get("name") or z.get("worksheet")) else "unknown"


def _zone_sheet(z) -> str:
    return z.get("worksheet") or z.get("name")


def dashboard_zones(db) -> list:
    """The zones of a `<dashboard>` element that show or control a sheet (or dashboard), in document order.
    A zone names it in `@worksheet` or, in some files, only in `@name`; layout containers, text and the
    like are skipped."""
    return [z for z in db.xpath(".//zone[@name or @worksheet]")
            if zone_kind(z) in _SHEET_ZONE_TYPES]


def dashboard_targets(db) -> list[str]:
    """The sheet names `dashboard_zones` shows, in document order (repeats kept)."""
    return [_zone_sheet(z) for z in dashboard_zones(db)]


def _int_attr(node, name) -> Optional[int]:
    """Port of `.int_attr`.

    R's `as.integer(xml_attr(...))` parses the string as a double first and
    truncates, so a fractional coordinate like "682.666" (Tableau does emit
    these for some floating-layout zones) becomes 682 rather than failing.
    """
    val = node.get(name)
    if val is None:
        return None
    try:
        return int(val)
    except ValueError:
        try:
            return int(float(val))
        except (TypeError, ValueError):
            return None


def _xpath_string_literal(s: str) -> str:
    """Build an XPath 1.0 string literal for `s`, safe for names containing
    a `'`, a `"`, or both.

    XPath 1.0 has no in-literal escape character, so a value containing
    both quote characters can't be wrapped in either on its own -- it has
    to be assembled with `concat()`, splitting on `'` and substituting a
    double-quoted `'` for each occurrence.
    """
    if "'" not in s:
        return f"'{s}'"
    if '"' not in s:
        return f'"{s}"'
    parts = s.split("'")
    pieces = []
    for i, part in enumerate(parts):
        if part:
            pieces.append(f"'{part}'")
        if i < len(parts) - 1:
            pieces.append("\"'\"")
    return f"concat({','.join(pieces)})"


def _dashboard_xpath(dashboard: Optional[str]) -> str:
    if dashboard is None:
        return ".//dashboard"
    return f".//dashboard[@name={_xpath_string_literal(dashboard)}]"


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
        for z in dashboard_zones(d):
            rows.append(
                {
                    "dashboard": d_name,
                    "sheet": _zone_sheet(z),
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


def _size_text(db) -> str:
    """`1000 x 800` for a fixed-size dashboard, `automatic` when the size is a range or not stored."""
    size = db.find("size")
    if size is None:
        return "automatic"
    w, h = size.get("minwidth"), size.get("minheight")
    if w and h and w == size.get("maxwidth") and h == size.get("maxheight"):
        return f"{w} x {h}"
    return "automatic"


_PARAM_REF = re.compile(r"^\[([^\]]*)\]\.\[(.*)\]$")
_INSTANCE = re.compile(r"^[a-z]{2,5}:(.+):[a-z]{2}$")


def _zone_field_name(xml_doc, param: str) -> str:
    """The name a filter or parameter-control zone's `param` stands for: `[ds].[none:Category:nk]` is
    `Category`; a field with a caption (a calculation, a parameter) reads as its caption."""
    m = _PARAM_REF.match(param)
    if not m:
        return param
    ds_name, inner = m.groups()
    inst = _INSTANCE.match(inner)
    base = inst.group(1) if inst else inner
    for ds in xml_doc.xpath("//datasource[@name=$n]", n=ds_name):
        for col in ds.xpath("column[@name=$c]", c=f"[{base}]"):
            if col.get("caption"):
                return col.get("caption")
    return base


def _zone_names(xml_doc, db, kind: str) -> str:
    """Names of the fields (or parameters) the `kind` zones of a dashboard's main layout point at,
    `; `-separated, each once, in layout order."""
    names = []
    for z in db.xpath("./zones//zone"):
        if zone_kind(z) == kind and z.get("param"):
            n = _zone_field_name(xml_doc, z.get("param"))
            if n not in names:
                names.append(n)
    return "; ".join(names)


def dashboard_summary(xml_doc) -> pd.DataFrame:
    """One row per dashboard: how many distinct worksheets it shows (and which), its size, and how many
    quick filters, parameter controls and workbook actions it has, how many image (`bitmap`), text and web page
    zones its main layout has (`images`, `texts`, `webs`; a `title` zone is not counted as text), plus the fields the filters are on
    (`filter_fields`) and the parameters the controls set (`parameter_names`). `list_dashboards` stays the name-only list."""
    action_counts: dict[str, int] = {}
    for src in xml_doc.xpath(".//actions/action/source[@dashboard]"):
        action_counts[src.get("dashboard")] = action_counts.get(src.get("dashboard"), 0) + 1
    rows = []
    for name in list_dashboards(xml_doc)["name"]:
        for db in xml_doc.xpath(_dashboard_xpath(name))[:1]:
            sheets = sorted({t for t in dashboard_targets(db) if t})
            # the main layout only: a device layout repeats the same filters and controls
            kinds = [zone_kind(z) for z in db.xpath("./zones//zone")]
            rows.append({
                "name": name, "worksheets": len(sheets), "sheets": "; ".join(sheets), "size": _size_text(db),
                "filters": kinds.count("filter"), "parameters": kinds.count("paramctrl"),
                "actions": action_counts.get(name, 0),
                "images": kinds.count("bitmap"), "texts": kinds.count("text"), "webs": kinds.count("web"),
                "filter_fields": _zone_names(xml_doc, db, "filter"),
                "parameter_names": _zone_names(xml_doc, db, "paramctrl"),
            })
    return pd.DataFrame(rows, columns=_SUMMARY_COLUMNS)


def _uuid_owners(xml_doc) -> dict[str, list[str]]:
    owners: dict[str, list[str]] = {}
    for el in xml_doc.xpath("//simple-id[@uuid]"):
        parent = el.getparent()
        label = f"{parent.tag} {parent.get('name')!r}" if parent is not None and parent.get("name") else (
            parent.tag if parent is not None else "?")
        owners.setdefault(el.get("uuid"), []).append(label)
    return owners


def integrity_check(xml_doc, dashboard: Optional[str] = None, require_window: bool = False) -> list[dict]:
    """Reference checks on the dashboards of a workbook (all of them, or one by name); an empty list means none
    failed. The schema does not check any of this. Each problem is a dict with `check`, `dashboard` and `detail`:

    - `zone-id-duplicate`: two zones of one `<zones>` tree (the main layout, or one device layout) share an id.
      Zones without an id are not counted.
    - `sheet-unresolved`: a sheet, filter or legend zone names something that is not a worksheet or dashboard.
    - `viewpoint-unresolved`: the dashboard's window has a viewpoint for a sheet that does not exist.
    - `active-zone-missing`: the window's `<active id>` is neither -1 nor a zone id of the dashboard.
    - `simple-id-shared`: the dashboard and its window carry the same `simple-id` uuid.
    - `uuid-duplicate`: a `simple-id` uuid of the dashboard or its window is used twice in the workbook.
    - `window-missing`: the dashboard has no window (only with `require_window=True`; real workbooks lack
      one in about one dashboard in nine).
    """
    sheets = set(xml_doc.xpath("/workbook/worksheets/worksheet/@name"))
    names = sheets | set(xml_doc.xpath("/workbook/dashboards/dashboard/@name"))
    owners = _uuid_owners(xml_doc)
    problems: list[dict] = []

    def add(check, db_name, detail):
        problems.append({"check": check, "dashboard": db_name, "detail": detail})

    for db in xml_doc.xpath(_dashboard_xpath(dashboard)):
        name = db.get("name")
        for zones in db.xpath(".//zones"):
            seen: dict[str, int] = {}
            for z in zones.iter("zone"):
                if z.get("id") is not None:
                    seen[z.get("id")] = seen.get(z.get("id"), 0) + 1
            where = "" if zones.getparent() is db else f" in the {zones.getparent().get('name')!r} device layout"
            for zid in sorted((i for i, n in seen.items() if n > 1), key=lambda i: (len(i), i)):
                add("zone-id-duplicate", name, f"zone id {zid} is used {seen[zid]} times{where}")
        for z in db.xpath(".//zone[@name or @worksheet]"):
            if zone_kind(z) in _SHEET_ZONE_TYPES and _zone_sheet(z) not in names:
                add("sheet-unresolved", name, f"zone {z.get('id')} ({zone_kind(z)}) names {_zone_sheet(z)!r}, "
                                              "which is not a worksheet or dashboard")
        ids = {z.get("id") for z in db.xpath("./zones//zone")}
        own = [u.get("uuid") for u in db.xpath("./simple-id[@uuid]")]
        windows = xml_doc.xpath("/workbook/windows/window[@class='dashboard'][@name=$n]", n=name)
        if not windows and require_window:
            add("window-missing", name, "no <window class='dashboard'> with this name")
        for w in windows[:1]:
            for vp in w.xpath("./viewpoints/viewpoint[@name]"):
                if vp.get("name") not in sheets:
                    add("viewpoint-unresolved", name, f"viewpoint {vp.get('name')!r} is not a worksheet")
            active = w.find("active")
            if active is not None and active.get("id") not in (None, "-1") and active.get("id") not in ids:
                add("active-zone-missing", name, f"the window's active zone {active.get('id')} is not in the dashboard")
            wid = [u.get("uuid") for u in w.xpath("./simple-id[@uuid]")]
            if set(wid) & set(own):
                add("simple-id-shared", name, "the dashboard and its window share one simple-id uuid")
            own += wid
        for u in sorted(set(own)):
            if len(owners.get(u, [])) > 1:
                add("uuid-duplicate", name, f"simple-id {u} is used by {', '.join(owners[u])}")
    return problems
