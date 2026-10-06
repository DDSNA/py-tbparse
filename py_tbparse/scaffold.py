"""Dashboard scaffolds (WP16 slices 16a and 16b): the layout of one dashboard, without its sheets.

`make_scaffold()` takes a dashboard whose layout is a single tiled root and keeps what makes the layout:
the container tree (`layout-basic`, `layout-flow`), text, title and blank zones, zone styles, the dashboard's
size and style, and one numbered *slot* per sheet zone. Filters, legends, parameter controls, images, buttons,
web pages, device layouts and the rest are dropped and listed in `scaffold["dropped"]`. `apply_scaffold()`
puts the scaffold into a workbook as a NEW dashboard (zone ids renumbered 1..n, new `simple-id` uuids for the
dashboard and its window) showing the sheets you choose for the slots. An existing dashboard is never changed.

Evidence is `docs/scaffolds.md` and the research behind it: shapes measured on the 200-workbook corpus.
Nothing written here was ever opened in Tableau Desktop.
"""

from __future__ import annotations

import copy
import json
import os
import uuid
from pathlib import Path
from typing import Optional, Union

import pandas as pd
from lxml import etree

from .dashboards import CONTAINER_KINDS, _dashboard_xpath, integrity_check, zone_kind
from .parser import TwbParser
from .rename import _serialize_workbook

FORMAT = "py-tbparse-scaffold"
VERSION = 1
SLOT_ATTR = "slot"          # marks a sheet zone in the stored layout; never written into a workbook
KEPT_KINDS = CONTAINER_KINDS + ("text", "title", "empty")
SLOT_COLUMNS = ["slot", "hint", "w", "h"]
DROPPED_COLUMNS = ["id", "kind", "name", "reason"]
_TYPE_ATTRS = ("type", "type-v2")


class ScaffoldError(ValueError):
    """A dashboard cannot be a scaffold, or a scaffold cannot be applied as asked."""


def _parser(wb) -> TwbParser:
    return wb if isinstance(wb, TwbParser) else TwbParser(str(wb))


def _text(el) -> str:
    return etree.tostring(el, encoding="unicode")


def _strip_kind(attrib: dict) -> dict:
    """The attributes of a zone without any of the places that hold its kind."""
    return {k: v for k, v in attrib.items()
            if k not in _TYPE_ATTRS and not (k.startswith("_.fcp.") and k.endswith(("...type", "...type-v2")))}


def _copy_zone(z, kind: str, slots: list, dropped: list) -> Optional[etree._Element]:
    """The kept copy of a zone (with its kept children), or None when it is dropped (and listed)."""
    zid, name = z.get("id") or "", z.get("name") or z.get("param") or ""
    if kind == "sheet":
        out = etree.Element("zone", _strip_kind(dict(z.attrib)))
        hint = out.attrib.pop("name", None) or out.attrib.pop("worksheet", None) or ""
        if out.attrib.pop("param", None) is not None:
            dropped.append({"id": zid, "kind": "sheet-control", "name": hint,
                            "reason": "the sheet zone's own param (a set control) is not kept"})
        out.attrib.pop("id", None)
        slots.append({"slot": len(slots) + 1, "hint": hint, "w": z.get("w"), "h": z.get("h")})
        out.set(SLOT_ATTR, str(len(slots)))
    elif kind in KEPT_KINDS:
        out = etree.Element("zone", {k: v for k, v in z.attrib.items() if k != "id"})
    else:
        reason = ("bound to a sheet's field, so it may not fit the sheets you choose" if kind in
                  ("filter", "color", "size", "paramctrl", "shape", "highlighter", "map", "legend")
                  else "not part of the first scaffold slice")
        dropped.append({"id": zid, "kind": kind, "name": name, "reason": reason})
        return None
    for child in z:
        if child.tag == "zone-style":
            out.append(copy.deepcopy(child))
        elif child.tag == "formatted-text" and kind == "text":
            out.append(copy.deepcopy(child))
        elif child.tag == "zone":
            sub = _copy_zone(child, zone_kind(child), slots, dropped)
            if sub is not None:
                out.append(sub)
    if kind in CONTAINER_KINDS and not len(out.findall("zone")):
        dropped.append({"id": zid, "kind": kind, "name": name, "reason": "container left empty by the dropped zones"})
        return None
    return out


def _source_dashboard(parser: TwbParser, dashboard: Optional[str]):
    names = [d.get("name") for d in parser.xml_doc.xpath("/workbook/dashboards/dashboard[@name]")]
    if dashboard is None:
        if len(names) != 1:
            raise ScaffoldError("name the dashboard to take the layout from: "
                                + (", ".join(repr(n) for n in names) if names else "the workbook has none"))
        dashboard = names[0]
    found = parser.xml_doc.xpath(_dashboard_xpath(dashboard))
    if not found:
        raise ScaffoldError(f"no dashboard named {dashboard!r}")
    return found[0]


def make_scaffold(wb: Union[TwbParser, str, os.PathLike], dashboard: Optional[str] = None, name: Optional[str] = None,
                  description: str = "") -> dict:
    """The scaffold of one dashboard (a dict `save_scaffold` writes as JSON). The dashboard must have exactly one
    top-level zone, a tiled `layout-basic` root (a floating or older layout, and a storyboard, raise
    `ScaffoldError`). `dashboard` may be left out when the workbook has only one."""
    parser = _parser(wb)
    db = _source_dashboard(parser, dashboard)
    if db.get("type") == "storyboard":
        raise ScaffoldError(f"{db.get('name')!r} is a storyboard, not a dashboard layout")
    tops = db.xpath("./zones/zone")
    if len(tops) != 1:
        raise ScaffoldError(f"{db.get('name')!r} has {len(tops)} top-level zones; only a layout with one tiled "
                            "root is supported (floating objects are not)")
    if zone_kind(tops[0]) != "layout-basic":
        raise ScaffoldError(f"{db.get('name')!r} has no tiled root (its top zone is {zone_kind(tops[0])!r}, not "
                            "'layout-basic')")
    slots: list = []
    dropped: list = []
    root = _copy_zone(tops[0], "layout-basic", slots, dropped)
    if not slots:
        raise ScaffoldError(f"{db.get('name')!r} shows no sheet zone that could become a slot")
    for tag, why in (("devicelayouts", "device layouts are not kept; Tableau makes the phone layout again"),
                     ("datasources", "dashboard data sources belong to filters and legends, which are dropped"),
                     ("datasource-dependencies", "columns used by filters and legends, which are dropped")):
        for el in db.findall(tag):
            note = f"{len(el)} device layout(s): " if tag == "devicelayouts" else ""
            dropped.append({"id": "", "kind": tag, "name": "", "reason": note + why})
    attrs = {k: v for k, v in db.attrib.items() if k != "name"}
    parts = {tag: _text(el) for tag in ("layout-options", "style", "size") for el in db.findall(tag)}
    return {
        "format": FORMAT, "version": VERSION,
        "name": name or db.get("name"), "description": description,
        "source": {"dashboard": db.get("name")},
        "attributes": attrs, "dashboard": parts,
        "slots": slots, "dropped": dropped,
        "layout": _text(root),
    }


def _check(scaffold: dict) -> dict:
    if not isinstance(scaffold, dict) or scaffold.get("format") != FORMAT:
        raise ScaffoldError(f"not a {FORMAT} file")
    if scaffold.get("version") != VERSION:
        raise ScaffoldError(f"unsupported scaffold version {scaffold.get('version')!r} (this tool reads {VERSION})")
    for key in ("layout", "slots", "dashboard"):
        if key not in scaffold:
            raise ScaffoldError(f"scaffold has no {key!r}")
    return scaffold


def save_scaffold(scaffold: dict, path: Union[str, os.PathLike], overwrite: bool = False) -> str:
    _check(scaffold)
    out = Path(path)
    if out.exists() and not overwrite:
        raise FileExistsError(f"refusing to overwrite existing file: {out}")
    with open(out, "w" if overwrite else "x", encoding="utf-8") as fh:
        json.dump(scaffold, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    return str(out)


def load_scaffold(path: Union[str, os.PathLike]) -> dict:
    with open(path, encoding="utf-8") as fh:
        try:
            data = json.load(fh)
        except json.JSONDecodeError as e:
            raise ScaffoldError(f"{path} is not valid JSON: {e}") from e
    return _check(data)


def scaffold_slots(scaffold: dict) -> pd.DataFrame:
    return pd.DataFrame(_check(scaffold)["slots"], columns=SLOT_COLUMNS)


def scaffold_dropped(scaffold: dict) -> pd.DataFrame:
    return pd.DataFrame(_check(scaffold).get("dropped", []), columns=DROPPED_COLUMNS)


def _choose(scaffold: dict, sheets, worksheets: set, allow_empty: bool) -> list[Optional[str]]:
    """One sheet name (or None for a blank slot) per slot, checked."""
    n = len(scaffold["slots"])
    if isinstance(sheets, dict):
        picked: list = [None] * n
        for key, sheet in sheets.items():
            try:
                i = int(str(key).lower().removeprefix("slot"))
            except ValueError:
                raise ScaffoldError(f"{key!r} is not a slot number (1 to {n})") from None
            if not 1 <= i <= n:
                raise ScaffoldError(f"slot {i} does not exist; the scaffold has {n}")
            picked[i - 1] = sheet
    else:
        picked = list(sheets or [])
        if len(picked) > n:
            raise ScaffoldError(f"{len(picked)} sheets given for {n} slot(s)")
        picked += [None] * (n - len(picked))
    missing = [i + 1 for i, s in enumerate(picked) if s is None]
    if missing and not allow_empty:
        raise ScaffoldError(f"{n} slot(s) and no sheet for slot {', '.join(map(str, missing))} "
                            "(allow_empty / --allow-empty leaves them blank)")
    chosen = [s for s in picked if s is not None]
    unknown = [s for s in chosen if s not in worksheets]
    if unknown:
        raise ScaffoldError("not a worksheet of this workbook: " + ", ".join(repr(s) for s in unknown))
    twice = sorted({s for s in chosen if chosen.count(s) > 1})
    if twice:
        raise ScaffoldError("a sheet can fill only one slot: " + ", ".join(repr(s) for s in twice))
    if not chosen:
        raise ScaffoldError("no sheet chosen for any slot")
    return picked


def _new_uuid(taken: set) -> str:
    while True:
        u = "{" + str(uuid.uuid4()).upper() + "}"
        if u not in taken:
            taken.add(u)
            return u


def _fill(layout, picked: list, counter: list) -> None:
    """Number the zones 1..n in document order and turn slot zones into sheet (or blank) zones."""
    for z in layout.iter("zone"):
        counter[0] += 1
        z.set("id", str(counter[0]))
        slot = z.attrib.pop(SLOT_ATTR, None)
        if slot is None:
            continue
        sheet = picked[int(slot) - 1]
        if sheet is None:
            for k in [k for k in z.attrib if k not in ("x", "y", "w", "h", "is-fixed", "fixed-size", "id")]:
                del z.attrib[k]
            for child in list(z):
                z.remove(child)
            z.set("type-v2", "empty")
        else:
            z.set("name", sheet)


def _ordered(z: etree._Element) -> etree._Element:
    """The same zone with its attributes sorted, as Tableau writes them (the file is read by name, so this only
    keeps diffs quiet)."""
    items = sorted(z.attrib.items())
    z.attrib.clear()
    for k, v in items:
        z.set(k, v)
    for child in z.findall("zone"):
        _ordered(child)
    return z


def build_scaffold_workbook(parser: TwbParser, scaffold: dict, name: str, sheets=None, allow_empty: bool = False,
                            report: Optional[dict] = None) -> bytes:
    """Bytes of a copy of the workbook with a new dashboard `name`. `sheets` is a list (slot 1, 2, ...) or a dict
    `{slot number: sheet name}`. A `.twbx` gives a `.twbx` with every other member copied across untouched.
    `report`, if a dict, receives `dashboard`, `zones`, `slots` (slot -> sheet), `dashboard_uuid`, `window_uuid`."""
    _check(scaffold)
    name = (name or "").strip()
    if not name:
        raise ScaffoldError("the new dashboard needs a name")
    doc = copy.deepcopy(parser.xml_doc)
    root = doc.getroot() if hasattr(doc, "getroot") else doc
    worksheets = set(doc.xpath("/workbook/worksheets/worksheet/@name"))
    if name in worksheets or doc.xpath(_dashboard_xpath(name)):
        raise ScaffoldError(f"{name!r} is already the name of a worksheet or dashboard")
    picked = _choose(scaffold, sheets, worksheets, allow_empty)

    layout = etree.fromstring(scaffold["layout"])
    counter = [0]
    _fill(layout, picked, counter)
    _ordered(layout)

    taken = set(doc.xpath("//simple-id/@uuid"))
    db_uuid, win_uuid = _new_uuid(taken), _new_uuid(taken)

    db = etree.Element("dashboard")
    for k, v in scaffold.get("attributes", {}).items():
        db.set(k, v)
    db.set("name", name)
    parts = scaffold["dashboard"]
    for tag in ("layout-options", "style", "size"):
        if tag in parts:
            db.append(etree.fromstring(parts[tag]))
    zones = etree.SubElement(db, "zones")
    zones.append(layout)
    etree.SubElement(db, "simple-id", uuid=db_uuid)
    etree.cleanup_namespaces(db)

    dashboards = doc.find("dashboards")
    if dashboards is None:
        dashboards = etree.Element("dashboards")
        anchor = doc.find("worksheets")
        if anchor is not None:
            anchor.addnext(dashboards)
        else:
            root.append(dashboards)
    dashboards.append(db)

    windows = doc.find("windows")
    if windows is None:
        windows = etree.Element("windows")
        dashboards.addnext(windows)
    win = etree.SubElement(windows, "window", {"class": "dashboard", "name": name})
    vps = etree.SubElement(win, "viewpoints")
    for sheet in picked:
        if sheet is not None:
            etree.SubElement(vps, "viewpoint", name=sheet)
    etree.SubElement(win, "active", id="-1")      # the schema wants it; -1 is "no zone selected"
    etree.SubElement(win, "simple-id", uuid=win_uuid)

    problems = integrity_check(doc, dashboard=name, require_window=True)
    if problems:       # a bug here, never the user's mistake: refuse to write a broken dashboard
        raise ScaffoldError("the new dashboard failed its own checks: "
                            + "; ".join(f"{p['check']}: {p['detail']}" for p in problems))
    if report is not None:
        report.update(dashboard=name, zones=counter[0], dashboard_uuid=db_uuid, window_uuid=win_uuid,
                      slots={i + 1: s for i, s in enumerate(picked)})
    return _serialize_workbook(parser, doc)


def apply_scaffold(wb: Union[TwbParser, str, os.PathLike], scaffold: Union[dict, str, os.PathLike], name: str,
                   sheets=None, output_path: Optional[str] = None, overwrite: bool = False,
                   allow_empty: bool = False, report: Optional[dict] = None) -> str:
    """Write a copy of the workbook with a new dashboard `name` laid out like the scaffold, and return its path.
    The output defaults to `<name>_scaffold.<ext>` beside the source, keeps the source's extension, and the
    input is never overwritten (an existing output only with `overwrite=True`)."""
    parser = _parser(wb)
    if not isinstance(scaffold, dict):
        scaffold = load_scaffold(scaffold)
    source = Path(parser.twbx_path or parser.path)
    out = Path(output_path) if output_path else source.with_name(f"{source.stem}_scaffold{source.suffix}")
    if out.suffix.lower() != source.suffix.lower():
        raise ScaffoldError(f"output must end in {source.suffix}, got {out.suffix or 'no extension'}")
    if out.exists() and (out.resolve() == source.resolve() or not overwrite):
        raise FileExistsError(f"refusing to overwrite existing file: {out}")
    data = build_scaffold_workbook(parser, scaffold, name, sheets, allow_empty, report)
    with open(out, "wb" if overwrite else "xb") as fh:
        fh.write(data)
    return str(out)


def scaffold_plan(wb: Union[TwbParser, str, os.PathLike], scaffold: dict, name: str, sheets=None,
                  allow_empty: bool = False) -> pd.DataFrame:
    """What `apply_scaffold` would do, one row per slot (`slot`, `hint`, `sheet`); raises the same errors, writes
    nothing."""
    parser = _parser(wb)
    report: dict = {}
    build_scaffold_workbook(parser, scaffold, name, sheets, allow_empty, report)
    rows = [{"slot": s["slot"], "hint": s["hint"], "sheet": report["slots"][s["slot"]] or "(blank)"}
            for s in scaffold["slots"]]
    return pd.DataFrame(rows, columns=["slot", "hint", "sheet"])
