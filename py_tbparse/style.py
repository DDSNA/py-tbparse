"""Colour palette libraries (WP7, first slice).

Read named custom colour palettes from a workbook (`<preferences><color-palette>`), a `Preferences.tps` or a
`*.style.json` file; write them into a new `Preferences.tps`, a style file, or a copy of a workbook.

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
from pathlib import Path
from typing import Optional, Union

import pandas as pd
from lxml import etree

from . import templates as _templates
from .parser import TwbParser
from .rename import _serialize_workbook


class StyleError(ValueError):
    """A palette, style file or import cannot be read or done as asked."""


STYLE_FORMAT = "py-tbparse-style"
STYLE_VERSION = 1
PALETTE_TYPES = ("regular", "ordered-sequential", "ordered-diverging")
CLASH_POLICIES = ("fail", "skip", "rename", "replace")
PALETTE_COLUMNS = ["source", "name", "type", "n_colors", "colors", "status", "reason"]
PLAN_COLUMNS = ["name", "type", "n_colors", "action", "target_name", "reason"]

_COLOR = re.compile(r"#[0-9A-Fa-f]{6}(?:[0-9A-Fa-f]{2})?")
_ATTR_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_.-]*")
_TOP_KEYS = {"format", "version", "name", "description", "created", "py_tbparse_version", "sources", "palettes"}
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
        tree = etree.parse(str(path), etree.XMLParser(resolve_entities=False, no_network=True))
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


def palette_records(source) -> list[dict]:
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
            root = etree.fromstring(data, etree.XMLParser(resolve_entities=False, no_network=True))
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
               sources=()) -> dict:
    """A `py-tbparse-style` dict (version 1) holding `palettes`."""
    names = set()
    for p in palettes:
        reason, _ = _problem(p)
        if reason:
            raise StyleError(f"palette {p.get('name')!r}: {reason}")
        if p["name"] in names:
            raise StyleError(f"two palettes are called {p['name']!r}")
        names.add(p["name"])
    return {
        "format": STYLE_FORMAT,
        "version": STYLE_VERSION,
        "name": name or "palettes",
        "description": description or "",
        "created": _templates._now(),
        "py_tbparse_version": _templates._version(),
        "sources": [str(s) for s in sources],
        "palettes": [_clean(p) for p in palettes],
    }


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
    unknown = sorted(set(style) - _TOP_KEYS)
    if unknown:
        reserved = [k for k in unknown if k in ("fonts", "workbook_rules", "dashboard", "sheet_defaults")]
        hint = f" ({', '.join(reserved)} are reserved for a later version)" if reserved else ""
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
    """Read and check a `*.style.json` file. Raises `StyleError` for anything but a valid version 1 file."""
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


def plan_palette_import(target, palettes, on_clash: str = "fail", select=None) -> pd.DataFrame:
    """What importing `palettes` into `target` would do, one row per palette (`PLAN_COLUMNS`). Actions: `add`,
    `skip-identical`, `skip`, `rename`, `replace`, `invalid`, and `fail` (a clash under `on_clash="fail"`).
    Nothing is written. A name that differs only in case from another is not a clash; it is noted in `reason`."""
    _, _, _, doc = _load_target(target)
    rows, _ = _plan(_existing(doc.getroot()), _incoming(palettes), on_clash, select)
    return pd.DataFrame(rows, columns=PLAN_COLUMNS)


def build_with_palettes(target, palettes, on_clash: str = "fail", select=None, report: Optional[dict] = None) -> bytes:
    """Bytes of a copy of `target` (a `.tps`, `.twb` or `.twbx`) with `palettes` added. Existing content,
    including unknown elements and the workbook's marks and formats, is kept as it is. A `.twbx` keeps every
    other member untouched. With `on_clash="fail"` any clash raises `StyleError` before anything is built."""
    kind, parser, path, doc = _load_target(target)
    doc = copy.deepcopy(doc)
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
    if kind == "tps":
        return etree.tostring(doc, xml_declaration=True, encoding="utf-8")
    return _serialize_workbook(parser, doc)


def import_palettes(target, palettes, output_path=None, on_clash: str = "fail", select=None,
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


def export_palettes(sources: list, output_path, select=None, on_clash: str = "fail", name: Optional[str] = None,
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
            load_style(path)
        except StyleError as e:
            return [str(e)]
        return []
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
