"""Colour palette libraries (WP7, first slice) and, read side only so far, fonts and formatting rules (slice 2a).

Read named custom colour palettes from a workbook (`<preferences><color-palette>`), a `Preferences.tps` or a
`*.style.json` file; write them into a new `Preferences.tps`, a style file, or a copy of a workbook.

Slice 2a adds the version 2 style file (`fonts`, `workbook_rules`, `dashboard`, `sheet_defaults`) and
`extract_style`, which reads name-free fonts, workbook style rules and dashboard zone styles by role out of a
workbook. Nothing writes formatting onto a workbook yet (2b and later; plan: docs/wp7-style-plan-slice2.md).

What this does and does not do (design: docs/wp7-style-plan.md, evidence: docs/style-model.md):

* It makes palettes *selectable in the colour picker*. It recolours nothing: colours already in use are written
  per value into the datasource `mark` encodings, and this module never touches those.
* No input file is ever modified. Output goes to a new file; an existing `Preferences.tps` is never replaced.
* Nothing written here has been opened in Tableau. The `.tps` shape comes from Tableau's help page and from the
  `<preferences>` block of three corpus workbooks.
"""

from __future__ import annotations

import copy
import json
import os
import re
from collections import Counter
from pathlib import Path
from typing import Iterable, Optional, Union

import pandas as pd
from lxml import etree

from . import templates as _templates
from .dashboards import zone_kind
from ._xml import PathLike, PyTbparseError, parse_bytes, parse_file
from .parser import TwbParser
from .rename import _serialize_workbook

# What the palette functions take as palettes: records, a style dict, a path or workbook, or a list of those.
_Palettes = Union[PathLike, TwbParser, dict, list]


class StyleError(PyTbparseError):
    """A palette, style file or import cannot be read or done as asked."""


STYLE_FORMAT = "py-tbparse-style"
STYLE_VERSION = 2               # the newest version this module reads; 1 and 2 are accepted
PALETTE_ONLY_VERSION = 1        # what `make_style` writes while no formatting section is filled
FORMAT_SCOPES = ("workbook", "dashboards", "sheets")
FORMAT_COLUMNS = ["source", "section", "where", "attr", "scope", "value", "note"]
PALETTE_TYPES = ("regular", "ordered-sequential", "ordered-diverging")
CLASH_POLICIES = ("fail", "skip", "rename", "replace")
PALETTE_COLUMNS = ["source", "name", "type", "n_colors", "colors", "status", "reason"]
PLAN_COLUMNS = ["name", "type", "n_colors", "action", "target_name", "reason"]

_COLOR = re.compile(r"#[0-9A-Fa-f]{6}(?:[0-9A-Fa-f]{2})?")
_ATTR_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_.-]*")
_TOP_KEYS = {"format", "version", "name", "description", "created", "py_tbparse_version", "sources", "palettes"}
FORMAT_SECTIONS = ("fonts", "workbook_rules", "dashboard", "sheet_defaults")
_PALETTE_KEYS = {"name", "type", "colors", "attrs"}
_SHOWN_BY_TABLEAU = 20          # Edit Colors shows at most 20 (help page)
_SOURCE_SUFFIXES = (".twb", ".twbx", ".tps")


# ------------------------------------------------------------- validation --

def _key(p: dict) -> tuple:
    """Identity of a palette: name, type and colours (case-insensitive, ordered). `attrs` do not count."""
    return (p["name"], p["type"], tuple(c.upper() for c in p["colors"]))


def _problem(p: dict) -> tuple[Optional[str], list[str]]:
    """(why the palette cannot be used or None, warnings)."""
    name, typ, colors = p.get("name"), p.get("type"), p.get("colors")
    if not isinstance(name, str) or not name.strip():
        return "the palette has no name", []
    if typ not in PALETTE_TYPES:
        return f"type {typ!r} is not one of {', '.join(PALETTE_TYPES)}", []
    if not isinstance(colors, list) or not colors:
        return "the palette has no colours", []
    bad = [c for c in colors if not isinstance(c, str) or not _COLOR.fullmatch(c)]
    if bad:
        return f"colour {bad[0]!r} is not #RRGGBB (or #RRGGBBAA)", []
    attrs = p.get("attrs", {})
    if not isinstance(attrs, dict):
        return "attrs must be an object", []
    for k, v in attrs.items():
        if not isinstance(k, str) or not _ATTR_NAME.fullmatch(k) or k in ("name", "type") or not isinstance(v, str):
            return f"attribute {k!r} cannot be written", []
    warnings = []
    if any(len(c) == 9 for c in colors):
        warnings.append("alpha not confirmed for .tps")
    if len(colors) > _SHOWN_BY_TABLEAU:
        warnings.append(f"more than {_SHOWN_BY_TABLEAU} colours: Tableau shows the first {_SHOWN_BY_TABLEAU}")
    return None, warnings


def _clean(p: dict) -> dict:
    return {"name": p["name"], "type": p["type"], "colors": list(p["colors"]), "attrs": dict(p.get("attrs") or {})}


# ---------------------------------------------------------------- reading --

def _label(source) -> str:
    if isinstance(source, TwbParser):
        return Path(source.twbx_path or source.path).name
    return Path(source).name


def _from_element(el) -> dict:
    return {
        "name": el.get("name"),
        "type": el.get("type"),
        "colors": [(c.text or "").strip() for c in el.findall("color")],
        "attrs": {k: v for k, v in el.attrib.items() if k not in ("name", "type")},
    }


def _parse_tps(path):
    try:
        tree = parse_file(path)
    except etree.XMLSyntaxError as e:
        raise StyleError(f"{path} is not XML: {e}") from e
    if tree.getroot().tag != "workbook":
        raise StyleError(f"{path} is not a Preferences.tps (the root is <{tree.getroot().tag}>, not <workbook>)")
    return tree


def _collect(source) -> list[dict]:
    """Every palette of one source, valid or not: dicts with name/type/colors/attrs, source, status, reason."""
    label = _label(source)
    if isinstance(source, TwbParser):
        raw = [_from_element(e) for e in source.xml_doc.xpath("/workbook/preferences/color-palette")]
    else:
        suffix = Path(source).suffix.lower()
        if str(source).lower().endswith(".style.json"):
            raw = load_style(source)["palettes"]
        elif suffix in (".twb", ".twbx"):
            raw = [_from_element(e) for e in TwbParser(str(source)).xml_doc.xpath("/workbook/preferences/color-palette")]
        elif suffix == ".tps":
            if not Path(source).exists():
                raise FileNotFoundError(f"File not found: {source}")
            raw = [_from_element(e) for e in _parse_tps(source).xpath("/workbook/preferences/color-palette")]
        else:
            raise StyleError(f"{label}: expected a .twb, .twbx, .tps or .style.json file")
    return _classify(raw, label)


def _classify(raw: list[dict], label: str) -> list[dict]:
    """Give each raw palette a status (ok, warning, duplicate, invalid) and a reason."""
    out, seen = [], {}
    for p in raw:
        reason, warnings = _problem(p)
        status = "ok"
        if reason is None and p["name"] in seen:
            if seen[p["name"]] == _key(p):
                out.append({**p, "source": label, "status": "duplicate", "_skip": True,
                            "reason": "listed twice with the same definition; kept once"})
                continue
            reason = "same name as an earlier palette with different colours"
        if reason is not None:
            status = "invalid"
        else:
            seen[p["name"]] = _key(p)
            if warnings:
                status = "warning"
        out.append({**p, "source": label, "status": status, "reason": reason or "; ".join(warnings)})
    return out


def palette_records(source: Union[PathLike, TwbParser]) -> list[dict]:
    """Every palette of a source (path or `TwbParser`), valid or not, as records with `status` (ok, warning,
    duplicate, invalid) and `reason`; `palette_problems` turns them into `check` lines."""
    return _collect(source)


def palettes_from_bytes(data: bytes, filename: str) -> list[dict]:
    """Palette records read from the bytes of an uploaded `*.style.json` or `.tps` (decided by `filename`), without
    touching disk. Same records as `import_palettes` reads from a path (`name`, `type`, `colors`, `attrs`, plus
    `source`, `status`, `reason`); pass them as `palettes` to `plan_palette_import` or `build_with_palettes`."""
    label = Path(filename).name
    lower = label.lower()
    if lower.endswith(".style.json"):
        try:
            style = json.loads(data.decode("utf-8-sig"))
        except (UnicodeDecodeError, json.JSONDecodeError) as e:
            raise StyleError(f"{label} is not JSON: {e}") from e
        raw = _check_style(style)["palettes"]
    elif lower.endswith(".tps"):
        try:
            root = parse_bytes(data)
        except etree.XMLSyntaxError as e:
            raise StyleError(f"{label} is not XML: {e}") from e
        if root.tag != "workbook":
            raise StyleError(f"{label} is not a Preferences.tps (the root is <{root.tag}>, not <workbook>)")
        raw = [_from_element(e) for e in root.xpath("/workbook/preferences/color-palette")]
    else:
        raise StyleError(f"{label}: expected a .style.json or .tps file")
    return [r for r in _classify(raw, label) if not r.get("_skip")]


def read_palettes(source: Union[str, os.PathLike, TwbParser], report: Optional[dict] = None) -> list[dict]:
    """The usable palettes of a workbook, `Preferences.tps` or `*.style.json`, in file order, as dicts with
    `name`, `type`, `colors` (exact text) and `attrs` (every other attribute, verbatim). A palette that cannot be
    used (no name, unknown type, no colours, a colour that is not hex) is left out and named in `report`:
    `found`, `invalid` and `warnings` (lists of names)."""
    records = _collect(source)
    if report is not None:
        report.update(
            found=len(records),
            invalid=[r["name"] or "(no name)" for r in records if r["status"] == "invalid"],
            warnings=[r["name"] for r in records if r["status"] in ("warning", "duplicate")],
        )
    return [_clean(r) for r in records if r["status"] in ("ok", "warning")]


def _row(source: str, p: dict, status: str, reason: str) -> dict:
    colors = p.get("colors") if isinstance(p.get("colors"), list) else []
    return {"source": source, "name": p.get("name") or "", "type": p.get("type") or "", "n_colors": len(colors),
            "colors": " ".join(str(c) for c in colors), "status": status, "reason": reason}


def palettes_table(source_or_palettes) -> pd.DataFrame:
    """One row per palette found, `PALETTE_COLUMNS`. Takes a source (path or `TwbParser`), a list of sources,
    or a list of palette dicts (`status` is then `ok`/`warning`/`invalid`)."""
    items = source_or_palettes
    if isinstance(items, (str, os.PathLike, TwbParser)):
        items = [items]
    rows = []
    for item in items:
        if isinstance(item, dict):
            reason, warnings = _problem(item)
            rows.append(_row("", item, "invalid" if reason else ("warning" if warnings else "ok"),
                             reason or "; ".join(warnings)))
        else:
            rows += [_row(r["source"], r, r["status"], r["reason"]) for r in _collect(item) if not r.get("_skip")]
    return pd.DataFrame(rows, columns=PALETTE_COLUMNS)


# ------------------------------------------------------------ style files --

def make_style(palettes: list[dict], name: Optional[str] = None, description: Optional[str] = None,
               sources: Iterable[Union[PathLike, TwbParser]] = (), fonts: Optional[dict] = None,
               workbook_rules: Optional[list] = None, dashboard: Optional[dict] = None,
               sheet_defaults: Optional[list] = None) -> dict:
    """A `py-tbparse-style` dict holding `palettes` and, optionally, the formatting sections (`fonts`,
    `workbook_rules`, `dashboard`, `sheet_defaults`; shapes in docs/styles.md). It is version 1 while every
    formatting section is empty, so palette-only files stay readable by older py-tbparse, and version 2 as soon
    as one holds something; a version 2 dict always carries all four sections."""
    names = set()
    for p in palettes:
        reason, _ = _problem(p)
        if reason:
            raise StyleError(f"palette {p.get('name')!r}: {reason}")
        if p["name"] in names:
            raise StyleError(f"two palettes are called {p['name']!r}")
        names.add(p["name"])
    sections = {"fonts": fonts or {}, "workbook_rules": workbook_rules or [],
                "dashboard": dashboard or {}, "sheet_defaults": sheet_defaults or []}
    formatted = any(sections.values())
    style = {
        "format": STYLE_FORMAT,
        "version": STYLE_VERSION if formatted else PALETTE_ONLY_VERSION,
        "name": name or "palettes",
        "description": description or "",
        "created": _templates._now(),
        "py_tbparse_version": _templates._version(),
        "sources": [str(s) for s in sources],
        "palettes": [_clean(p) for p in palettes],
    }
    if formatted:
        style.update(copy.deepcopy(sections))
        _check_formats(style)
    return style


def _check_style(style) -> dict:
    if not isinstance(style, dict):
        raise StyleError("a style file holds one JSON object")
    if style.get("format") != STYLE_FORMAT:
        raise StyleError(f"not a style file (format is {style.get('format')!r}, expected {STYLE_FORMAT!r})")
    version = style.get("version")
    if not isinstance(version, int) or isinstance(version, bool) or version < 1:
        raise StyleError(f"bad style version {version!r}")
    if version > STYLE_VERSION:
        raise StyleError(f"style file version {version} is newer than this py-tbparse reads (version {STYLE_VERSION})")
    allowed = _TOP_KEYS | (set(FORMAT_SECTIONS) if version >= 2 else set())
    unknown = sorted(set(style) - allowed)
    if unknown:
        late = [k for k in unknown if k in FORMAT_SECTIONS]
        hint = f" ({', '.join(late)} need style version 2; this file says version {version})" if late else ""
        raise StyleError(f"unknown key in style file: {', '.join(unknown)}{hint}")
    palettes = style.get("palettes")
    if not isinstance(palettes, list):
        raise StyleError("a style file needs a `palettes` list")
    names = set()
    for p in palettes:
        if not isinstance(p, dict) or set(p) - _PALETTE_KEYS:
            raise StyleError(f"a palette holds only {', '.join(sorted(_PALETTE_KEYS))}: {p!r}")
        reason, _ = _problem(p)
        if reason:
            raise StyleError(f"palette {p.get('name')!r}: {reason}")
        if p["name"] in names:
            raise StyleError(f"two palettes are called {p['name']!r}")
        names.add(p["name"])
    if version >= 2:
        _check_formats(style)
    return style


def _open_new(path: Path, data: bytes, overwrite: bool) -> None:
    if path.exists() and path.name.lower() == "preferences.tps":
        raise FileExistsError(f"refusing to write over {path}: write a new file and copy it into place yourself")
    if path.exists() and not overwrite:
        raise FileExistsError(f"refusing to overwrite existing file: {path}")
    with open(path, "wb" if overwrite else "xb") as fh:      # "xb" refuses a file created since the check
        fh.write(data)


def save_style(style: dict, path: Union[str, os.PathLike], overwrite: bool = False) -> str:
    """Write a style dict as JSON (UTF-8, indent 2, sorted keys). An existing file is kept unless `overwrite`."""
    _check_style(style)
    text = json.dumps(style, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    _open_new(Path(path), text.encode("utf-8"), overwrite)
    return str(path)


def load_style(path: Union[str, os.PathLike]) -> dict:
    """Read and check a `*.style.json` file. Raises `StyleError` for anything but a valid version 1 or 2 file."""
    try:
        with open(path, encoding="utf-8") as fh:
            style = json.load(fh)
    except json.JSONDecodeError as e:
        raise StyleError(f"{path} is not JSON: {e}") from e
    return _check_style(style)


# ---------------------------------------------------------------- writing --

def _palette_el(p: dict):
    el = etree.Element("color-palette")
    el.set("name", p["name"])
    el.set("type", p["type"])
    for k in sorted(p.get("attrs") or {}):
        el.set(k, p["attrs"][k])
    for c in p["colors"]:
        etree.SubElement(el, "color").text = c
    return el


def tps_bytes(palettes: list[dict]) -> bytes:
    """A fresh `Preferences.tps` holding `palettes`."""
    for p in palettes:
        reason, _ = _problem(p)
        if reason:
            raise StyleError(f"palette {p.get('name')!r}: {reason}")
    root = etree.Element("workbook")
    prefs = etree.SubElement(root, "preferences")
    for p in palettes:
        prefs.append(_palette_el(p))
    etree.indent(root, space="  ")
    return etree.tostring(root, xml_declaration=True, encoding="utf-8")


def _indent_of(el) -> Optional[str]:
    """The whitespace that starts `el`'s line, or None if the file is not indented."""
    prev = el.getprevious()
    before = prev.tail if prev is not None else el.getparent().text
    if before and "\n" in before:
        return before.rsplit("\n", 1)[1]
    return None


def _indent_new(el, indent: Optional[str]) -> None:
    """Indent the children of a freshly built `el` that starts at `indent` (None: leave unindented)."""
    if indent is None:
        return
    unit = "  "
    kids = list(el)
    if not kids:
        return
    el.text = "\n" + indent + unit
    for i, k in enumerate(kids):
        k.tail = "\n" + indent + (unit if i < len(kids) - 1 else "")
        _indent_new(k, indent + unit)


def _ensure_preferences(root):
    """The first `/workbook/preferences`, created at the XSD position when missing."""
    found = root.find("preferences")
    if found is not None:
        return found
    prefs = etree.Element("preferences")
    anchors = [c for c in root if c.tag in ("document-format-change-manifest", "repository-location")]
    if anchors:
        last = anchors[-1]
        indent = _indent_of(last)
        prefs.tail = last.tail
        last.addnext(prefs)
        if indent is not None:
            last.tail = "\n" + indent
    else:
        indent = None
        if len(root):
            indent = _indent_of(root[0])
        prefs.tail = root.text if indent is not None else None
        root.insert(0, prefs)
    return prefs


def _place(prefs, new, after) -> None:
    """Put `new` after the child `after` of `prefs` (None: first child), matching the file's indentation."""
    indent = _indent_of(prefs)
    inner = None if indent is None else indent + "  "
    if after is not None and _indent_of(after) is not None:
        inner = _indent_of(after)
    _indent_new(new, inner)
    if after is None:
        if len(prefs) and inner is not None:
            new.tail = "\n" + inner
        else:
            new.tail = None if inner is None else "\n" + indent
        if inner is not None and not prefs.text:
            prefs.text = "\n" + inner
        prefs.insert(0, new)
        return
    new.tail = after.tail
    if after.getnext() is None and inner is not None:
        after.tail = "\n" + inner          # `after` was last: its tail closed <preferences>, the new one takes that
    after.addnext(new)


# --------------------------------------------------------------- planning --

def _incoming(palettes) -> list[dict]:
    """Normalise what `palettes` can be -- dicts, a style dict, a path, a parser, or a list of those -- to
    records (name/type/colors/attrs plus `status` and `reason`)."""
    if isinstance(palettes, dict) and "palettes" in palettes:
        palettes = _check_style(palettes)["palettes"]
    if isinstance(palettes, (dict, str, os.PathLike, TwbParser)):
        palettes = [palettes]
    out = []
    for item in palettes:
        if isinstance(item, dict) and "status" in item and "reason" in item:      # a record from `palettes_from_bytes`
            out.append(item)
        elif isinstance(item, dict):
            reason, warnings = _problem(item)
            out.append({**item, "attrs": dict(item.get("attrs") or {}) if isinstance(item.get("attrs"), dict) else {},
                        "source": "", "status": "invalid" if reason else ("warning" if warnings else "ok"),
                        "reason": reason or "; ".join(warnings)})
        else:
            out += [r for r in _collect(item) if not r.get("_skip")]
    return out


def _plan(existing: list[dict], incoming: list[dict], on_clash: str, select) -> tuple[list[dict], list[dict]]:
    """Decide every palette before anything is written. `existing` is the target's palettes, in order, each a
    dict with name, `key` (identity or None when it is itself invalid) and `slot` (its element index).
    Returns (plan rows, final entries). Entries: {name, key, palette, slot, changed}; a new entry has slot None."""
    if on_clash not in CLASH_POLICIES:
        raise StyleError(f"on_clash must be one of {', '.join(CLASH_POLICIES)}, got {on_clash!r}")
    if select is not None:
        select = list(select)
        have = {r["name"] for r in incoming}
        missing = [n for n in select if n not in have]
        if missing:
            raise StyleError(f"no palette called {', '.join(map(repr, missing))} (found: {', '.join(sorted(map(str, have))) or 'none'})")
        incoming = [r for r in incoming if r["name"] in select]
    entries = [dict(e, palette=None, changed=False) for e in existing]
    rows = []

    def find(name):
        return next((e for e in entries if e["name"] == name), None)

    for r in incoming:
        base = {"name": r.get("name") or "", "type": r.get("type") or "",
                "n_colors": len(r["colors"]) if isinstance(r.get("colors"), list) else 0, "target_name": ""}
        if r["status"] == "invalid":
            rows.append({**base, "action": "invalid", "reason": r["reason"]})
            continue
        p, k, note = _clean(r), _key(r), r["reason"]
        hit = find(p["name"])
        if hit is None:
            lower = next((e["name"] for e in entries if e["name"].lower() == p["name"].lower()), None)
            if lower is not None:
                note = "; ".join(x for x in (note, f"differs only in case from {lower!r}") if x)
            entries.append({"name": p["name"], "key": k, "palette": p, "slot": None, "changed": True})
            rows.append({**base, "action": "add", "target_name": p["name"], "reason": note})
        elif hit["key"] == k:
            rows.append({**base, "action": "skip-identical", "target_name": p["name"], "reason": note})
        elif on_clash == "fail":
            rows.append({**base, "action": "fail", "reason": "a palette with this name and other colours exists"})
        elif on_clash == "skip":
            rows.append({**base, "action": "skip", "target_name": p["name"], "reason": "kept the existing palette"})
        elif on_clash == "replace":
            hit.update(key=k, palette=p, changed=True)
            rows.append({**base, "action": "replace", "target_name": p["name"], "reason": "the existing palette is replaced in place"})
        else:
            n = 2
            while find(f"{p['name']} ({n})") is not None:
                n += 1
            new = f"{p['name']} ({n})"
            entries.append({"name": new, "key": (new,) + k[1:], "palette": {**p, "name": new}, "slot": None, "changed": True})
            rows.append({**base, "action": "rename", "target_name": new, "reason": "same name, other colours"})
    return rows, entries


def _clash_error(rows: list[dict]) -> StyleError:
    names = ", ".join(repr(r["name"]) for r in rows if r["action"] == "fail")
    return StyleError(
        f"palette name already used with other colours: {names}. Use on_clash='replace' (--on-clash replace) for a "
        "new version of the palette, 'rename' to keep both, or 'skip' to keep the existing one")


def _fill_report(report: Optional[dict], rows: list[dict], entries: list[dict]) -> None:
    if report is None:
        return
    pick = lambda a: [r["name"] for r in rows if r["action"] == a]          # noqa: E731
    report.update(
        added=pick("add"), skipped_identical=pick("skip-identical"), skipped=pick("skip"),
        renamed=[f"{r['name']} -> {r['target_name']}" for r in rows if r["action"] == "rename"],
        replaced=pick("replace"), invalid=pick("invalid"),
        warnings=[f"{r['name']}: {r['reason']}" for r in rows if r["reason"] and r["action"] in ("add", "skip-identical")],
    )
    report["counts"] = {k: len(report[k]) for k in ("added", "skipped_identical", "skipped", "renamed", "replaced", "invalid", "warnings")}


def _target(target) -> tuple[str, Optional[TwbParser], Path]:
    """(kind, parser or None, path of the file) for a target: `.tps`, or a workbook."""
    if isinstance(target, TwbParser):
        return "workbook", target, Path(target.twbx_path or target.path)
    path = Path(target)
    suffix = path.suffix.lower()
    if suffix == ".tps":
        if not path.exists():
            raise FileNotFoundError(f"File not found: {path}")
        return "tps", None, path
    if suffix in (".twb", ".twbx"):
        return "workbook", TwbParser(str(path)), path
    raise StyleError(f"the target must be a .tps, .twb or .twbx file, got {path.name}")


def _existing(root) -> list[dict]:
    out = []
    for i, el in enumerate(root.xpath("/workbook/preferences[1]/color-palette")):
        p = _from_element(el)
        out.append({"name": p["name"] or "", "key": _key(p) if _problem(p)[0] is None else None, "slot": i})
    return out


def _load_target(target):
    kind, parser, path = _target(target)
    doc = _parse_tps(path) if kind == "tps" else parser.xml_doc
    return kind, parser, path, doc


def plan_palette_import(target: Union[PathLike, TwbParser], palettes: _Palettes, on_clash: str = "fail", select=None) -> pd.DataFrame:
    """What importing `palettes` into `target` would do, one row per palette (`PLAN_COLUMNS`). Actions: `add`,
    `skip-identical`, `skip`, `rename`, `replace`, `invalid`, and `fail` (a clash under `on_clash="fail"`).
    Nothing is written. A name that differs only in case from another is not a clash; it is noted in `reason`."""
    _, _, _, doc = _load_target(target)
    rows, _ = _plan(_existing(doc.getroot()), _incoming(palettes), on_clash, select)
    return pd.DataFrame(rows, columns=PLAN_COLUMNS)


def _add_palettes_to_doc(doc, palettes: _Palettes, on_clash: str, select, report: Optional[dict]) -> None:
    """Add `palettes` to the `<preferences>` of `doc` in place (the caller passes a copy). A clash under
    `on_clash="fail"` raises `StyleError` before anything changes."""
    root = doc.getroot()
    rows, entries = _plan(_existing(root), _incoming(palettes), on_clash, select)
    if any(r["action"] == "fail" for r in rows):
        raise _clash_error(rows)
    _fill_report(report, rows, entries)
    if any(e["changed"] for e in entries):
        prefs = _ensure_preferences(root)
        for e in entries:
            if not e["changed"]:
                continue
            new = _palette_el(e["palette"])
            if e["slot"] is not None:
                old = prefs.findall("color-palette")[e["slot"]]
                _indent_new(new, _indent_of(old))
                new.tail = old.tail
                prefs.replace(old, new)
            else:
                existing = prefs.findall("color-palette") or prefs.findall("preference")
                _place(prefs, new, existing[-1] if existing else (prefs[-1] if len(prefs) else None))


def build_with_palettes(target: Union[PathLike, TwbParser], palettes: _Palettes, on_clash: str = "fail", select=None, report: Optional[dict] = None) -> bytes:
    """Bytes of a copy of `target` (a `.tps`, `.twb` or `.twbx`) with `palettes` added. Existing content,
    including unknown elements and the workbook's marks and formats, is kept as it is. A `.twbx` keeps every
    other member untouched. With `on_clash="fail"` any clash raises `StyleError` before anything is built."""
    kind, parser, path, doc = _load_target(target)
    doc = copy.deepcopy(doc)
    _add_palettes_to_doc(doc, palettes, on_clash, select, report)
    if kind == "tps":
        return etree.tostring(doc, xml_declaration=True, encoding="utf-8")
    return _serialize_workbook(parser, doc)


def import_palettes(target: Union[PathLike, TwbParser], palettes: _Palettes, output_path: Optional[PathLike] = None, on_clash: str = "fail", select=None,
                    overwrite: bool = False, report: Optional[dict] = None) -> str:
    """Write a copy of `target` with `palettes` added and return its path. `palettes` is a list of dicts, a
    style dict, or a path to anything `read_palettes` reads. The output defaults to `<name>_palettes<ext>` beside
    the target, keeps the target's extension, and is never the input. An existing `Preferences.tps` is never
    replaced, with or without `overwrite`: copy the new file into place yourself."""
    _, _, source = _target(target)
    out = Path(output_path) if output_path else source.with_name(f"{source.stem}_palettes{source.suffix}")
    if out.suffix.lower() != source.suffix.lower():
        raise StyleError(f"output must end in {source.suffix}, got {out.suffix or 'no extension'}")
    if out.exists() and out.resolve() == source.resolve():
        raise FileExistsError(f"refusing to overwrite the input: {out}")
    data = build_with_palettes(target, palettes, on_clash=on_clash, select=select, report=report)
    _open_new(out, data, overwrite)
    return str(out)


def build_export(sources: list, fmt: str, select=None, on_clash: str = "fail", name: Optional[str] = None,
                 report: Optional[dict] = None) -> bytes:
    """The bytes of a `Preferences.tps` (`fmt="tps"`) or a style file (`fmt="json"`) holding the palettes of
    `sources` (paths, parsers, dicts or records; merged in order, `on_clash` also applies between sources).
    Nothing is written."""
    if fmt not in ("tps", "json"):
        raise StyleError("fmt must be 'tps' or 'json'")
    if isinstance(sources, (str, os.PathLike, TwbParser)):
        sources = [sources]
    incoming = []
    for s in sources:
        incoming += _incoming(s)
    rows, entries = _plan([], incoming, on_clash, select)
    if any(r["action"] == "fail" for r in rows):
        raise _clash_error(rows)
    _fill_report(report, rows, entries)
    final = [e["palette"] for e in entries]
    if not final:
        raise StyleError("no usable palettes found in " + ", ".join(_label(s) for s in sources if not isinstance(s, (dict, list))))
    if fmt == "tps":
        return tps_bytes(final)
    labels = [_label(s) for s in sources if isinstance(s, (str, os.PathLike, TwbParser))]
    style = make_style(final, name=name, sources=labels)
    _check_style(style)
    return (json.dumps(style, indent=2, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")


def export_palettes(sources: list, output_path: PathLike, select=None, on_clash: str = "fail", name: Optional[str] = None,
                    overwrite: bool = False, report: Optional[dict] = None) -> str:
    """Merge the palettes of `sources` (in argument order; `on_clash` also applies between sources) and write a
    `Preferences.tps` (output ending `.tps`) or a style file (`.style.json`). Never replaces an input or an
    existing `Preferences.tps`."""
    if isinstance(sources, (str, os.PathLike, TwbParser)):
        sources = [sources]
    out = Path(output_path)
    kind = "json" if out.name.lower().endswith(".style.json") else "tps" if out.suffix.lower() == ".tps" else None
    if kind is None:
        raise StyleError(f"the output must end in .tps or .style.json, got {out.name}")
    for s in sources:
        if not isinstance(s, (dict, list)) and out.exists() and not isinstance(s, TwbParser) and out.resolve() == Path(s).resolve():
            raise FileExistsError(f"refusing to overwrite the input: {out}")
    data = build_export(sources, kind, select=select, on_clash=on_clash, name=name, report=report)
    _open_new(out, data, overwrite)
    return str(out)


# ------------------------------------------------------------------ check --

def check_style_file(path: Union[str, os.PathLike]) -> list[str]:
    """Problems in a `.tps` or `.style.json` file; an empty list means nothing was found. A line starting
    `warning:` is worth a look but does not make the file unusable."""
    path = Path(path)
    if not path.exists():
        return [f"file not found: {path}"]
    if path.name.lower().endswith(".style.json"):
        try:
            style = load_style(path)
        except StyleError as e:
            return [str(e)]
        return [f"warning: {w}" for w in style_warnings(style)]
    if path.suffix.lower() != ".tps":
        return [f"expected a .tps or .style.json file, got {path.name}"]
    try:
        records = _collect(path)
    except StyleError as e:
        return [str(e)]
    return palette_problems(records)


def palette_problems(records: list[dict]) -> list[str]:
    """The `check` lines for palette records (as `_collect` or `palettes_from_bytes` make them), in the words of
    `check_style_file`; no palette at all is a problem."""
    problems = []
    if not records:
        problems.append("no <color-palette> found under <workbook><preferences>")
    for r in records:
        who = r["name"] or "(no name)"
        if r["status"] == "invalid":
            problems.append(f"palette {who}: {r['reason']}")
        elif r["status"] in ("warning", "duplicate") and r["reason"]:
            problems.append(f"warning: palette {who}: {r['reason']}")
    return problems


# ------------------------------------------------------ formatting (v2) --
#
# One whitelist table for the whole slice: extraction reads only these, the style file may hold only these, and
# the later apply packages write only these. `tests/test_style_formats.py::test_whitelist_matches_xsd` compares
# every name with Tableau's XSD (tests/schemas), so the package never reads the schema itself (plan Q5).

FONT_ELEMENTS = ("all", "worksheet", "title", "tooltip")
FONT_ATTRS = ("font-family", "font-size", "font-weight", "font-style", "color")
WORKBOOK_ELEMENTS = FONT_ELEMENTS
DASHBOARD_ROLES = ("root", "container", "sheet", "title")
ROLE_ATTRS = ("background-color", "border-color", "border-style", "border-width", "margin", "padding")
DASHBOARD_RULE_ELEMENTS = ("dash-title", "dash-subtitle", "dash-text")
SHEET_ELEMENTS = ("header", "label", "title", "worksheet", "cell")
SHEET_ATTRS = FONT_ATTRS + ("background-color", "border-color", "border-style", "border-width", "text-align")
FORMAT_SCOPE_ATTRS = ("rows", "cols")           # `scope` of a <format>; the XSD also allows "" (written as no scope)
# `StyleAttribute-ST` of tests/schemas/twb_2026.2.0.xsd, copied. `field` is not an attribute name here and
# `encoding` is not a <format>: neither can be written in a style file.
STYLE_ATTRIBUTES = frozenset((
    "alternate-text", "alt-mark-color", "animation-on", "animation-duration", "animation-style", "aspect",
    "auto-subtitle", "background-color", "background-transparency", "band-size", "band-color", "band-level",
    "body-type", "border-color", "border-color-top", "border-color-right", "border-color-bottom",
    "border-color-left", "border-style", "border-style-top", "border-style-right", "border-style-bottom",
    "border-style-left", "border-width", "border-width-top", "border-width-right", "border-width-bottom",
    "border-width-left", "break-on-special", "cell", "cell-w", "cell-h", "cell-q", "cell-qmark", "color",
    "color-mode", "col-levels", "col-vert-levels", "col-horiz-height", "col-vert-height", "col-height", "col-width",
    "content", "corner-radius", "corner-radius-top-left", "corner-radius-top-right", "corner-radius-bottom-right",
    "corner-radius-bottom-left", "density-color", "density-kernel-size", "density-intensity", "density-max-value",
    "display-field-labels", "display", "display-alternate-text", "div-level", "enabled", "fill-above", "fill-below",
    "fill-color", "fog-bg-color", "fog-desaturation-without-selection", "fog-desaturation-with-selection",
    "font-family", "font-size", "font-style", "font-weight", "geo-area-type", "halign", "halo-color",
    "halo-color-selected", "has-label", "has-fill", "has-stroke", "has-halo", "height", "height-header",
    "highlight-legend", "hnaxis", "hnlabel", "in-tooltip", "line-end", "line-end-size", "line-interpolation",
    "line-marker-position", "line-pattern", "line-pattern-only", "line-visibility", "map", "map-style",
    "map-snap-zoom", "margin", "margin-top", "margin-right", "margin-bottom", "margin-left", "mark-color",
    "mark-transparency", "mark-markers-mode", "mark-labels-show", "mark-labels-mode", "mark-labels-cull",
    "mark-labels-line-first", "mark-labels-line-last", "mark-labels-range-min", "mark-labels-range-max",
    "mark-labels-range-scope", "mark-labels-range-field", "mark-line-pattern", "maxheight", "max-font-size",
    "max-stroke-width", "maxwidth", "middle-stroke-width", "minheight", "min-font-size", "min-stroke-width",
    "minwidth", "nonhighlight-color", "min-length", "min-map-size", "min-size", "omit-on-special", "orientation",
    "padding", "padding-top", "padding-right", "padding-bottom", "padding-left", "palette", "render-fold-reversed",
    "reverse-palette", "rounding", "row-horiz-levels", "row-horiz-width", "row-levels", "row-vert-width",
    "separator", "shape", "show-labels", "show-null-value-warning", "size", "size-bar", "smart-auto-align", "space",
    "stroke-color", "stroke-size", "subtitle", "text-align", "text-align-default", "text-decoration", "text-indent",
    "text-orientation", "text-format", "tick-color", "tick-length", "tick-spacing", "total-label", "title",
    "washout", "width", "width-header", "wrap", "valign", "vertical-align", "vertical-align-default", "vnaxis",
    "vnlabel", "zoom", "whisker-stroke-size", "whisker-stroke-color", "whisker-end", "boxplot-style", "opacity",
))
TABLEAU_FONT_PREFIX = "Tableau "                # faces of the "Tableau *" family ship with Tableau (docs/style-model.md s.4)

_FCP = "_.fcp."
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
_FORMAT_KEYS = {"attr", "value", "scope"}
_RULE_KEYS = {"element", "formats"}
_DASHBOARD_KEYS = {"background", "roles", "rules"}


def _walk_strings(obj):
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for k, v in obj.items():
            yield from _walk_strings(k)
            yield from _walk_strings(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _walk_strings(v)


def _check_value(where: str, value) -> None:
    if not isinstance(value, str) or not value.strip():
        raise StyleError(f"{where}: the value must be a non-empty string, got {value!r}")
    if _CONTROL.search(value):
        raise StyleError(f"{where}: the value holds a control character")


def _check_rules(section: str, rules, elements, attrs, scopes_ok: bool, taken: Optional[set] = None) -> None:
    """Validate a list of `{element, formats: [{attr, value, scope?}]}` entries. `taken` is the set of
    (element, attr, scope) keys already used elsewhere (the `fonts` view)."""
    if not isinstance(rules, list):
        raise StyleError(f"{section} must be a list")
    seen = set()
    for i, rule in enumerate(rules):
        here = f"{section}[{i}]"
        if not isinstance(rule, dict) or set(rule) - _RULE_KEYS or set(rule) != _RULE_KEYS:
            raise StyleError(f"{here}: an entry holds exactly element and formats: {rule!r}")
        element = rule["element"]
        if element not in elements:
            raise StyleError(f"{here}: element {element!r} is not one of {', '.join(elements)}")
        if not isinstance(rule["formats"], list) or not rule["formats"]:
            raise StyleError(f"{here}: formats must be a non-empty list")
        for j, f in enumerate(rule["formats"]):
            where = f"{here}.formats[{j}] ({element})"
            if not isinstance(f, dict) or "attr" not in f or "value" not in f or set(f) - _FORMAT_KEYS:
                raise StyleError(f"{where}: a format holds attr, value and optionally scope: {f!r}")
            attr = f["attr"]
            if attr not in attrs:
                raise StyleError(f"{where}: attribute {attr!r} is not allowed here")
            _check_value(where, f["value"])
            scope = f.get("scope", "")
            if scope not in ("",) + FORMAT_SCOPE_ATTRS or (scope and not scopes_ok):
                raise StyleError(f"{where}: scope {scope!r} must be rows or cols")
            key = (element, attr, scope)
            if key in seen:
                raise StyleError(f"{where}: {element}/{attr} is listed twice")
            if taken is not None and key in taken:
                raise StyleError(f"{where}: {element}/{attr} is also in `fonts`; give it in one place only")
            seen.add(key)


def _check_formats(style: dict) -> None:
    """Validate the four formatting sections of a version 2 style (missing sections are empty)."""
    for text in _walk_strings({k: style[k] for k in FORMAT_SECTIONS if k in style}):
        if _FCP in text:
            raise StyleError("a style file cannot carry feature-flag (_.fcp.*) content")
    fonts = style.get("fonts", {})
    if not isinstance(fonts, dict):
        raise StyleError("fonts must be an object keyed by element")
    taken = set()
    for element, attrs in fonts.items():
        if element not in FONT_ELEMENTS:
            raise StyleError(f"fonts: element {element!r} is not one of {', '.join(FONT_ELEMENTS)}")
        if not isinstance(attrs, dict) or not attrs:
            raise StyleError(f"fonts.{element}: expected an object of attributes")
        for attr, value in attrs.items():
            if attr not in FONT_ATTRS:
                raise StyleError(f"fonts.{element}: attribute {attr!r} is not one of {', '.join(FONT_ATTRS)}")
            _check_value(f"fonts.{element}.{attr}", value)
            taken.add((element, attr, ""))
    _check_rules("workbook_rules", style.get("workbook_rules", []), WORKBOOK_ELEMENTS, STYLE_ATTRIBUTES, True, taken)
    dash = style.get("dashboard", {})
    if not isinstance(dash, dict) or set(dash) - _DASHBOARD_KEYS:
        raise StyleError(f"dashboard holds only {', '.join(sorted(_DASHBOARD_KEYS))}")
    if "background" in dash:
        _check_value("dashboard.background", dash["background"])
    roles = dash.get("roles", {})
    if not isinstance(roles, dict):
        raise StyleError("dashboard.roles must be an object keyed by role")
    for role, attrs in roles.items():
        if role not in DASHBOARD_ROLES:
            raise StyleError(f"dashboard.roles: role {role!r} is not one of {', '.join(DASHBOARD_ROLES)}")
        if not isinstance(attrs, dict) or not attrs:
            raise StyleError(f"dashboard.roles.{role}: expected an object of attributes")
        for attr, value in attrs.items():
            if attr not in ROLE_ATTRS:
                raise StyleError(f"dashboard.roles.{role}: attribute {attr!r} is not one of {', '.join(ROLE_ATTRS)}")
            _check_value(f"dashboard.roles.{role}.{attr}", value)
    if "background" in dash and "background-color" in roles.get("root", {}):
        raise StyleError("dashboard.background is the root's background-color: set it there or in "
                         "roles.root, not both")
    _check_rules("dashboard.rules", dash.get("rules", []), DASHBOARD_RULE_ELEMENTS, STYLE_ATTRIBUTES, True)
    sheet_attrs = frozenset(SHEET_ATTRS) | {a for a in STYLE_ATTRIBUTES if a.startswith("border-")}
    _check_rules("sheet_defaults", style.get("sheet_defaults", []), SHEET_ELEMENTS, sheet_attrs, True)


def _style_font_families(style: dict):
    for element, attrs in (style.get("fonts") or {}).items():
        if "font-family" in attrs:
            yield f"fonts/{element}", attrs["font-family"]
    groups = [("workbook_rules", style.get("workbook_rules") or []),
              ("dashboard.rules", (style.get("dashboard") or {}).get("rules") or []),
              ("sheet_defaults", style.get("sheet_defaults") or [])]
    for section, rules in groups:
        for rule in rules:
            for f in rule["formats"]:
                if f["attr"] == "font-family":
                    yield f"{section}/{rule['element']}", f["value"]


def style_warnings(style: dict) -> list[str]:
    """Things worth a look in a style that is still usable: a font family that is not one of the "Tableau *"
    faces may not exist on the machine that opens the result (what Tableau does then is unverified)."""
    return [f"{where}: font family {family!r} may not exist on the target machine"
            for where, family in _style_font_families(style) if not family.startswith(TABLEAU_FONT_PREFIX)]


# ------------------------------------------------------------- extraction --

def _modal(values: list) -> str:
    """The most frequent value; a tie goes to the one seen first."""
    counts = Counter(values)
    best = None
    for v in dict.fromkeys(values):
        if best is None or counts[v] > counts[best]:
            best = v
    return best


def _zone_role(z, parent_is_zones: bool) -> Optional[str]:
    """The role of a zone for restyling, or None when it is not of a named role. Uses `dashboards.zone_kind`."""
    kind = zone_kind(z)
    if kind in ("layout-basic", "layout-flow"):
        return "root" if parent_is_zones else "container"
    if kind == "sheet":
        return "sheet"
    if kind == "title":
        return "title"
    return None


def _style_rules(style_el, elements, attrs, where: str, rep: dict, store: dict) -> None:
    """Collect the name-free formats of one `<style>` into `store[(element, attr, scope)] -> [values]`, counting
    what is left out in `rep`."""
    if style_el is None:
        return
    for child in style_el:
        if not isinstance(child.tag, str):
            continue
        if child.tag != "style-rule":
            if child.tag.startswith(_FCP):
                rep["fcp_skipped"] += 1
            continue
        element = child.get("element")
        if element not in elements:
            note = f"{where}: {element}"
            if note not in rep["unsupported"]:
                rep["unsupported"].append(note)
            continue
        rep["fcp_skipped"] += sum(1 for c in child if isinstance(c.tag, str) and c.tag.startswith(_FCP))
        rep["encoding_skipped"] += sum(1 for c in child if c.tag == "encoding")
        for f in child.findall("format"):
            attr, value, scope = f.get("attr"), f.get("value"), f.get("scope") or ""
            if f.get("field") is not None:
                rep["field_skipped"].append(f"{where}: {element}/{attr}")
            elif attr not in attrs or scope not in ("",) + FORMAT_SCOPE_ATTRS or value is None or not value.strip():
                rep["unsupported"].append(f"{where}: {element}/{attr}")
            else:
                store.setdefault((element, attr, scope), []).append(value)


def _rules_from(store: dict, rep: dict, label: str) -> list[dict]:
    rules: dict[str, list] = {}
    for (element, attr, scope), values in store.items():
        if len(set(values)) > 1:
            rep["mixed"].append(f"{label}{element}/{attr}" + (f" ({scope})" if scope else "") + ": " + ", ".join(dict.fromkeys(values)))
        fmt = {"attr": attr, "value": _modal(values)}
        if scope:
            fmt["scope"] = scope
        rules.setdefault(element, []).append(fmt)
    return [{"element": e, "formats": f} for e, f in rules.items()]


def extract_style(source: Union[str, os.PathLike, TwbParser], dashboard: Optional[str] = None,
                  scopes=("workbook", "dashboards"), palettes: bool = True, name: Optional[str] = None,
                  report: Optional[dict] = None) -> dict:
    """The name-free style of one workbook as a style dict (version 2 when any formatting was found, else 1).

    * `workbook` scope: the workbook `<style><style-rule>` for `all`, `worksheet`, `title` and `tooltip`. Font
      attributes go to `fonts`, every other format to `workbook_rules`.
    * `dashboards` scope: `zone-style` formats of zones by role (`root`, `container`, `sheet`, `title`), the most
      frequent value per role and attribute (a tie goes to the first in document order), and the dashboards'
      own `dash-title`, `dash-subtitle` and `dash-text` rules. `dashboard` narrows it to one dashboard by name,
      otherwise every dashboard counts. The root's `background-color` is stored as `dashboard.background`.
    * `sheets` scope is WP7-2d and raises `StyleError` for now.

    Formats with a `field=` attribute, `encoding` children and every `_.fcp.*` element are not read; they are
    counted in `report` (`field_skipped`, `encoding_skipped`, `fcp_skipped`, with `unsupported`, `mixed` and
    `counts`). Nothing is invented: a source without such formatting gives empty sections."""
    scopes = tuple(scopes)
    bad = [x for x in scopes if x not in FORMAT_SCOPES]
    if bad:
        raise StyleError(f"unknown scope {bad[0]!r}; choose from {', '.join(FORMAT_SCOPES)}")
    if "sheets" in scopes:
        raise StyleError("the sheets scope (sheet_defaults) is not available yet: it is work package WP7-2d")
    parser = source if isinstance(source, TwbParser) else None
    if parser is None:
        if Path(source).suffix.lower() not in (".twb", ".twbx"):
            raise StyleError(f"extract_style reads a .twb or .twbx, got {Path(source).name}")
        parser = TwbParser(str(source))
    doc = parser.xml_doc
    rep = {"fcp_skipped": 0, "encoding_skipped": 0, "field_skipped": [], "unsupported": [], "mixed": [],
           "warnings": [], "dashboards": []}
    fonts: dict = {}
    wb_rules: list = []
    dash: dict = {}

    if "workbook" in scopes:
        store: dict = {}
        _style_rules(doc.getroot().find("style"), WORKBOOK_ELEMENTS, STYLE_ATTRIBUTES, "workbook", rep, store)
        plain: dict = {}
        for (element, attr, scope), values in store.items():
            if attr in FONT_ATTRS and not scope:
                if len(set(values)) > 1:
                    rep["mixed"].append(f"workbook {element}/{attr}: " + ", ".join(dict.fromkeys(values)))
                fonts.setdefault(element, {})[attr] = _modal(values)
            else:
                plain[(element, attr, scope)] = values
        wb_rules = _rules_from(plain, rep, "workbook ")

    if "dashboards" in scopes:
        dbs = doc.xpath("/workbook/dashboards/dashboard")
        if dashboard is not None:
            dbs = [d for d in dbs if d.get("name") == dashboard]
            if not dbs:
                have = ", ".join(sorted(d.get("name") or "" for d in doc.xpath("/workbook/dashboards/dashboard"))) or "none"
                raise StyleError(f"no dashboard called {dashboard!r} (found: {have})")
        by_role: dict = {}
        rule_store: dict = {}
        for db in dbs:
            rep["dashboards"].append(db.get("name") or "")
            _style_rules(db.find("style"), DASHBOARD_RULE_ELEMENTS, STYLE_ATTRIBUTES, f"dashboard {db.get('name')}", rep, rule_store)
            zones = db.find("zones")
            if zones is None:
                rep["warnings"].append(f"dashboard {db.get('name')}: no <zones>")
                continue
            stack = [(z, True) for z in reversed(zones.findall("zone"))]
            while stack:
                z, top = stack.pop()
                role = _zone_role(z, top)
                if role is not None:
                    for f in z.findall("zone-style/format"):
                        attr, value = f.get("attr"), f.get("value")
                        if f.get("field") is not None:
                            rep["field_skipped"].append(f"dashboard/{role}/{attr}")
                        elif attr not in ROLE_ATTRS or value is None or not value.strip():
                            note = f"dashboard/{role}/{attr}"
                            if note not in rep["unsupported"]:
                                rep["unsupported"].append(note)
                        else:
                            by_role.setdefault(role, {}).setdefault(attr, []).append(value)
                stack.extend((c, False) for c in reversed(z.findall("zone")))
        roles: dict = {}
        for role in DASHBOARD_ROLES:
            for attr in ROLE_ATTRS:
                values = by_role.get(role, {}).get(attr)
                if values:
                    if len(set(values)) > 1:
                        rep["mixed"].append(f"dashboard {role}/{attr}: " + ", ".join(dict.fromkeys(values)))
                    roles.setdefault(role, {})[attr] = _modal(values)
        if "background-color" in roles.get("root", {}):
            dash["background"] = roles["root"].pop("background-color")
            if not roles["root"]:
                del roles["root"]
        if roles:
            dash["roles"] = roles
        dash_rules = _rules_from(rule_store, rep, "dashboard ")
        if dash_rules:
            dash["rules"] = dash_rules

    found = read_palettes(parser) if palettes else []
    label = _label(parser)
    style = make_style(found, name=name or Path(label).stem, sources=[label], fonts=fonts, workbook_rules=wb_rules,
                       dashboard=dash)
    if report is not None:
        report.update(rep)
        report["counts"] = {
            "fonts": sum(len(v) for v in fonts.values()),
            "workbook_rules": sum(len(r["formats"]) for r in wb_rules),
            "dashboard_roles": sum(len(v) for v in dash.get("roles", {}).values()) + ("background" in dash),
            "dashboard_rules": sum(len(r["formats"]) for r in dash.get("rules", [])),
            "palettes": len(found),
            "field_skipped": len(rep["field_skipped"]), "encoding_skipped": rep["encoding_skipped"],
            "fcp_skipped": rep["fcp_skipped"], "unsupported": len(rep["unsupported"]), "mixed": len(rep["mixed"]),
        }
    return style


def _format_rows(source: str, style: dict, mixed: list[str]) -> list[dict]:
    notes = {m.split(": ", 1)[0]: "mixed: " + m.split(": ", 1)[1] for m in mixed}
    rows = []

    def add(section, where, attr, value, scope="", key=None):
        rows.append({"source": source, "section": section, "where": where, "attr": attr, "scope": scope,
                     "value": value, "note": notes.get(key, "")})

    for element, attrs in (style.get("fonts") or {}).items():
        for attr, value in attrs.items():
            add("fonts", element, attr, value, key=f"workbook {element}/{attr}")
    for rule in style.get("workbook_rules") or []:
        for f in rule["formats"]:
            s = f.get("scope", "")
            add("workbook_rules", rule["element"], f["attr"], f["value"], s,
                f"workbook {rule['element']}/{f['attr']}" + (f" ({s})" if s else ""))
    dash = style.get("dashboard") or {}
    if "background" in dash:
        add("dashboard", "root", "background-color", dash["background"], key="dashboard root/background-color")
    for role, attrs in (dash.get("roles") or {}).items():
        for attr, value in attrs.items():
            add("dashboard", role, attr, value, key=f"dashboard {role}/{attr}")
    for rule in dash.get("rules") or []:
        for f in rule["formats"]:
            s = f.get("scope", "")
            add("dashboard_rules", rule["element"], f["attr"], f["value"], s,
                f"dashboard {rule['element']}/{f['attr']}" + (f" ({s})" if s else ""))
    for rule in style.get("sheet_defaults") or []:
        for f in rule["formats"]:
            add("sheet_defaults", rule["element"], f["attr"], f["value"], f.get("scope", ""))
    return rows


def format_table(source_or_style, scopes=("workbook", "dashboards")) -> pd.DataFrame:
    """One row per format found (`FORMAT_COLUMNS`): `section` is `fonts`, `workbook_rules`, `dashboard` (by role;
    the root background is attr `background-color` on `root`), `dashboard_rules` or `sheet_defaults`. Takes a
    workbook (path or `TwbParser`; extracted on the fly with `scopes`, `note` says `mixed: ...` where a role had
    several values), a style dict, a `*.style.json` path, or a list of those."""
    items = source_or_style
    if isinstance(items, (str, os.PathLike, TwbParser, dict)):
        items = [items]
    rows = []
    for item in items:
        if isinstance(item, dict):
            rows += _format_rows("", _check_style(item), [])
        elif not isinstance(item, TwbParser) and str(item).lower().endswith(".style.json"):
            rows += _format_rows(Path(item).name, load_style(item), [])
        else:
            rep: dict = {}
            style = extract_style(item, scopes=scopes, palettes=False, report=rep)
            rows += _format_rows(_label(item), style, rep["mixed"])
    return pd.DataFrame(rows, columns=FORMAT_COLUMNS)


# ------------------------------------------------- applying formatting (2b) --
#
# `plan_style` decides every format first, `build_styled` writes a copy, `apply_style` saves it as a new file.
# Work package 2b writes the `workbook` scope only (the workbook's `<style><style-rule>`, fonts included). The
# `dashboards` and `sheets` scopes are accepted, but what the style file holds for them is reported as
# `unsupported` until 2c and 2d are built. Rules (docs/wp7-style-plan-slice2.md section 4): a format the target
# already has is explicit whatever its value and is kept unless `force`; nothing with a `field=`, no `encoding`, no
# `_.fcp.*` element and no other rule is touched; the input is never modified.

FORMAT_ACTIONS = ("add", "same", "skip", "force", "unsupported", "no-target", "fail")
STYLE_PLAN_COLUMNS = ["scope", "target", "where", "attr", "current", "new", "action", "reason"]
FORMAT_CLASH_POLICIES = ("skip", "fail")
STYLED_SUFFIX = "_styled"

# Children of `<workbook>` that the XSD puts before the workbook `<style>` (WorkbookFile-CT).
_BEFORE_STYLE = ("document-format-change-manifest", "repository-location", "preferences", "style-theme")
_NOT_BUILT = {"dashboards": "WP7-2c", "sheets": "WP7-2d"}


def _same_value(a: str, b: str) -> bool:
    """Strings are equal; colours (#RRGGBB or #RRGGBBAA) are compared without regard to case."""
    return a == b or bool(_COLOR.fullmatch(a) and _COLOR.fullmatch(b) and a.upper() == b.upper())


def _resolve_style(style, palettes: bool) -> dict:
    """A checked style dict from a dict, a `*.style.json`, or a workbook (extracted on the fly)."""
    if isinstance(style, dict):
        return _check_style(copy.deepcopy(style))
    if isinstance(style, TwbParser) or Path(style).suffix.lower() in (".twb", ".twbx"):
        return extract_style(style, palettes=palettes)
    if str(style).lower().endswith(".style.json"):
        return load_style(style)
    raise StyleError(f"the style must be a style dict, a .style.json, or a .twb/.twbx workbook, got {Path(style).name}")


def _where(element: str, scope: str) -> str:
    return f"{element} ({scope})" if scope else element


def _workbook_wants(style: dict) -> list[tuple]:
    """(element, attr, scope, value) for every workbook-level format of the style: `fonts` first, then the rules."""
    wants = []
    for element, attrs in (style.get("fonts") or {}).items():
        for attr, value in attrs.items():
            wants.append((element, attr, "", value))
    for rule in style.get("workbook_rules") or []:
        for f in rule["formats"]:
            wants.append((rule["element"], f["attr"], f.get("scope", ""), f["value"]))
    return wants


def _unbuilt_wants(style: dict, scope: str) -> list[tuple]:
    """(where, attr, new) for the formats of a scope that is not built yet."""
    out = []
    if scope == "dashboards":
        dash = style.get("dashboard") or {}
        if "background" in dash:
            out.append(("root", "background-color", dash["background"]))
        for role, attrs in (dash.get("roles") or {}).items():
            out += [(role, a, v) for a, v in attrs.items()]
        for rule in dash.get("rules") or []:
            out += [(_where(rule["element"], f.get("scope", "")), f["attr"], f["value"]) for f in rule["formats"]]
    else:
        for rule in style.get("sheet_defaults") or []:
            out += [(_where(rule["element"], f.get("scope", "")), f["attr"], f["value"]) for f in rule["formats"]]
    return out


def _find_formats(doc, element: str, attr: str, scope: str) -> list:
    """The name-free `<format>`s of the workbook `<style>` for one key (element, attr, scope attribute)."""
    found = doc.xpath("/workbook/style/style-rule[@element=$e]/format[@attr=$a]", e=element, a=attr)
    return [f for f in found if f.get("field") is None and (f.get("scope") or "") == scope]


def _names(doc, xpath: str) -> list[str]:
    return [n for n in doc.xpath(xpath) if n]


def _check_names(doc, given, xpath: str, what: str) -> None:
    if not given:
        return
    have = _names(doc, xpath)
    missing = [n for n in given if n not in have]
    if missing:
        raise StyleError(f"no {what} called {', '.join(map(repr, missing))} in the target "
                         f"(found: {', '.join(sorted(have)) or 'none'}; names are exact and case-sensitive)")


def _plan_formats(doc, style: dict, scopes, dashboards, sheets, force: bool, on_clash: str) -> list[dict]:
    scopes = tuple(scopes)
    bad = [x for x in scopes if x not in FORMAT_SCOPES]
    if bad:
        raise StyleError(f"unknown scope {bad[0]!r}; choose from {', '.join(FORMAT_SCOPES)}")
    if on_clash not in FORMAT_CLASH_POLICIES:
        raise StyleError(f"on_clash must be one of {', '.join(FORMAT_CLASH_POLICIES)}, got {on_clash!r}")
    if force and on_clash == "fail":
        raise StyleError("force and on_clash='fail' contradict each other: --force replaces what --on-clash fail refuses")
    _check_names(doc, dashboards, "/workbook/dashboards/dashboard/@name", "dashboard")
    _check_names(doc, sheets, "/workbook/worksheets/worksheet/@name", "sheet")
    rows: list[dict] = []
    if "workbook" in scopes:
        has_style = doc.getroot().find("style") is not None
        # 90 of the 200 corpus workbooks hold the style block only as a feature-flagged element
        # (`<_.fcp.X.false...style>`), which is never edited here; a plain <style> is then added beside it.
        flagged = not has_style and any(isinstance(c.tag, str) and c.tag.startswith(_FCP) and c.tag.endswith("...style")
                                        for c in doc.getroot())
        made = set()
        for element, attr, fscope, value in _workbook_wants(style):
            row = {"scope": "workbook", "target": "workbook", "where": _where(element, fscope), "attr": attr,
                   "current": "", "new": value, "_element": element, "_fscope": fscope}
            found = _find_formats(doc, element, attr, fscope)
            if not found:
                row["action"] = "add"
                if flagged:
                    row["reason"] = ("not in the target; a plain <style> is created beside the workbook's feature-flagged "
                                     "style block (_.fcp.*, left untouched); how Tableau combines them is unverified")
                elif not has_style:
                    row["reason"] = "not in the target; the workbook has no <style>, one is created"
                elif doc.xpath("/workbook/style/style-rule[@element=$e]", e=element) or element in made:
                    row["reason"] = "not in the target; added to its existing rule"
                else:
                    row["reason"] = f"not in the target; a rule for {element} is created"
                made.add(element)
            else:
                current = found[0].get("value") or ""
                row["current"] = current
                if _same_value(current, value):
                    row.update(action="same", reason="the target already has this value")
                elif force:
                    row.update(action="force", reason="replaced in place (--force)")
                else:
                    row.update(action="fail" if on_clash == "fail" else "skip",
                               reason="the target already sets this format; kept (--force replaces it)")
            rows.append(row)
    for scope in ("dashboards", "sheets"):
        if scope in scopes:
            for where, attr, value in _unbuilt_wants(style, scope):
                rows.append({"scope": scope, "target": "", "where": where, "attr": attr, "current": "", "new": value,
                             "action": "unsupported",
                             "reason": f"writing {scope} formatting is not built yet ({_NOT_BUILT[scope]})"})
    return rows


def _add_child(parent, child, index: Optional[int] = None) -> None:
    """Insert `child` into `parent` (at the end, or before the child at `index`), matching the file's indentation."""
    kids = list(parent)
    if index is None or index >= len(kids):
        index = len(kids)
    parent_indent = _indent_of(parent) if parent.getparent() is not None else ""
    if kids and _indent_of(kids[0]) is not None:
        inner = _indent_of(kids[0])
    else:
        inner = None if parent_indent is None else parent_indent + "  "
    _indent_new(child, inner)
    if inner is None:
        child.tail = None
    elif index == len(kids):
        if kids:
            child.tail = kids[-1].tail
            kids[-1].tail = "\n" + inner
        else:
            child.tail = "\n" + parent_indent
            parent.text = "\n" + inner
    else:
        child.tail = "\n" + inner
        if index == 0 and not (parent.text and "\n" in parent.text):
            parent.text = "\n" + inner
    parent.insert(index, child)


def _ensure_workbook_style(root):
    """The first `/workbook/style`, created at the XSD position (after the preferences and the style theme)."""
    found = root.find("style")
    if found is not None:
        return found
    new = etree.Element("style")
    anchors = [c for c in root if c.tag in _BEFORE_STYLE]
    if anchors:
        last = anchors[-1]
        indent = _indent_of(last)
        new.tail = last.tail
        last.addnext(new)
        if indent is not None:
            last.tail = "\n" + indent
    else:
        indent = _indent_of(root[0]) if len(root) else None
        new.tail = root.text if indent is not None else None
        root.insert(0, new)
    return new


def _write_workbook_rows(doc, rows: list[dict]) -> None:
    root = doc.getroot()
    for row in rows:
        if row["scope"] != "workbook" or row["action"] not in ("add", "force"):
            continue
        element, attr, fscope, value = row["_element"], row["attr"], row["_fscope"], row["new"]
        if row["action"] == "force":
            for f in _find_formats(doc, element, attr, fscope):
                f.set("value", value)              # in place: position and other attributes stay
            continue
        style_el = _ensure_workbook_style(root)
        rules = [r for r in style_el.findall("style-rule") if r.get("element") == element]
        if rules:
            rule = rules[0]
        else:
            rule = etree.Element("style-rule")
            rule.set("element", element)
            real = [i for i, c in enumerate(style_el) if c.tag == "style-rule"]
            _add_child(style_el, rule, real[-1] + 1 if real else 0)
        fmt = etree.Element("format")
        fmt.set("attr", attr)
        fmt.set("value", value)
        if fscope:
            fmt.set("scope", fscope)
        _add_child(rule, fmt)


def _fill_format_report(report: Optional[dict], rows: list[dict], scopes, style: dict) -> None:
    if report is None:
        return
    label = lambda r: f"{r['scope']}: {r['where']}/{r['attr']}"                       # noqa: E731
    pick = lambda a: [label(r) for r in rows if r["action"] == a]                      # noqa: E731
    report.update(added=pick("add"), same=pick("same"), skipped=pick("skip"), forced=pick("force"),
                  unsupported=pick("unsupported"), no_target=pick("no-target"), failed=pick("fail"),
                  warnings=style_warnings(style))
    if any("feature-flagged" in r["reason"] for r in rows if r["action"] == "add"):
        report["warnings"].append("workbook: the target keeps its feature-flagged <_.fcp.*...style> block and gets a plain "
                                  "<style> beside it; how Tableau combines the two has not been checked")
    counts = {}
    for scope in scopes:
        mine = [r["action"] for r in rows if r["scope"] == scope]
        n = lambda a: mine.count(a)                                                    # noqa: E731
        counts[scope] = {"added": n("add"), "same": n("same"), "skipped": n("skip"), "forced": n("force"),
                         "unsupported": n("unsupported"), "no_target": n("no-target"),
                         "applied": n("add") + n("force")}
    report["counts"] = counts


def _format_target(target):
    kind, parser, path = _target(target)
    if kind == "tps":
        raise StyleError(f"{path.name} is a .tps: it holds palettes only and has no formatting. Give a .twb or .twbx")
    return parser, path


def plan_style(target: Union[PathLike, TwbParser], style, scopes=("workbook", "dashboards"), dashboards=None, sheets=None,
               force: bool = False, on_clash: str = "skip") -> pd.DataFrame:
    """What applying the formatting of `style` to `target` would do, one row per format (`STYLE_PLAN_COLUMNS`).
    Nothing is written. `style` is a style dict, a `*.style.json` or a workbook (its formatting is extracted).

    Actions: `add` (absent, will be written), `same` (present with this value; colours compare without case),
    `skip` (present with another value; kept, because any format the target already has is explicit), `force`
    (the same, with `force=True`: replaced in place), `fail` (a `skip` under `on_clash="fail"`), `unsupported`
    (scopes that are not built yet: `dashboards` is WP7-2c, `sheets` is WP7-2d) and `no-target`.
    `dashboards` and `sheets` are exact names of the target's own dashboards and sheets; an unknown name raises
    `StyleError`. `force` with `on_clash="fail"` is refused. A `.tps` target is refused (it has no formatting)."""
    parser, _ = _format_target(target)
    rows = _plan_formats(parser.xml_doc, _resolve_style(style, False), scopes, dashboards, sheets, force, on_clash)
    return pd.DataFrame(rows, columns=STYLE_PLAN_COLUMNS)


def build_styled(target: Union[PathLike, TwbParser], style, scopes=("workbook", "dashboards"), dashboards=None, sheets=None,
                 force: bool = False, on_clash: str = "skip", palettes: bool = False, palette_on_clash: str = "fail",
                 report: Optional[dict] = None) -> bytes:
    """Bytes of a copy of `target` (`.twb` or `.twbx`) with the formatting of `style` written onto it, following
    `plan_style`. Everything else is kept as it is and a `.twbx` keeps every other member untouched. With
    `on_clash="fail"` any `skip` raises `StyleError` before anything is built. Palettes in the style are ignored
    unless `palettes=True` (then `palette_on_clash` decides name clashes, as for `build_with_palettes`).
    `report` gets `added`, `same`, `skipped`, `forced`, `unsupported`, `no_target`, `failed`, `warnings` and `counts`
    per scope (`added`, `same`, `skipped`, `forced`, `unsupported`, `no_target`, `applied`)."""
    parser, _ = _format_target(target)
    scopes = tuple(scopes)
    resolved = _resolve_style(style, palettes)
    rows = _plan_formats(parser.xml_doc, resolved, scopes, dashboards, sheets, force, on_clash)
    failed = [r for r in rows if r["action"] == "fail"]
    if failed:
        shown = ", ".join(f"{r['scope']}: {r['where']}/{r['attr']} (target has {r['current']!r}, style has {r['new']!r})"
                          for r in failed)
        raise StyleError(f"{len(failed)} format(s) already set in the target with another value: {shown}. "
                         "Use force (--force) to replace them or on_clash='skip' (--on-clash skip) to keep them")
    doc = copy.deepcopy(parser.xml_doc)
    _write_workbook_rows(doc, rows)
    if palettes:
        pal_report: dict = {}
        _add_palettes_to_doc(doc, resolved, palette_on_clash, None, pal_report)
    _fill_format_report(report, rows, scopes, resolved)
    if report is not None and palettes:
        report["palettes"] = pal_report
    return _serialize_workbook(parser, doc)


def apply_style(target: Union[PathLike, TwbParser], style, output_path: Optional[PathLike] = None,
                scopes=("workbook", "dashboards"), dashboards=None, sheets=None, force: bool = False,
                on_clash: str = "skip", palettes: bool = False, palette_on_clash: str = "fail", overwrite: bool = False,
                report: Optional[dict] = None) -> str:
    """Write a copy of `target` with the formatting of `style` applied and return its path (`build_styled` has the
    rules). The output defaults to `<name>_styled<ext>` beside the target, keeps its extension, and is never the
    input and never an existing file unless `overwrite`. The target is not modified."""
    _, source = _format_target(target)
    out = Path(output_path) if output_path else source.with_name(f"{source.stem}{STYLED_SUFFIX}{source.suffix}")
    if out.suffix.lower() != source.suffix.lower():
        raise StyleError(f"output must end in {source.suffix}, got {out.suffix or 'no extension'}")
    if out.exists() and out.resolve() == source.resolve():
        raise FileExistsError(f"refusing to overwrite the input: {out}")
    data = build_styled(target, style, scopes=scopes, dashboards=dashboards, sheets=sheets, force=force,
                        on_clash=on_clash, palettes=palettes, palette_on_clash=palette_on_clash, report=report)
    _open_new(out, data, overwrite)
    return str(out)
