"""Libraries of calculated fields and parameters: export them from one workbook, add them to another.

Not part of the R package. A library is a small JSON file (`*.library.json`, format in
`docs/wp6-library-design.md` and `docs/libraries.md`) that holds the calculated fields and parameters of one
datasource, with the fields they need. `import_library` writes a copy of another workbook with those
calculations and parameters added; the fields they need are mapped to the target's fields first, and a name
or caption that is already taken is handled by a policy (`rename`, `skip` or `fail`).

The output follows what Tableau writes for these objects (checked against the 200-workbook test corpus),
but it was never opened in Tableau. Only calculations (`class='tableau'`) and parameters are handled. A
calculation that refers to a set, group or bin keeps the reference, and the target must already have that
object under the same name.
"""

from __future__ import annotations

import copy
import hashlib
import heapq
import json
import os
import re
from pathlib import Path
from typing import Iterable, Optional, Union

import pandas as pd
from lxml import etree

from ._clean import is_missing
from .parser import TwbParser
from .rename import _insert_column, _serialize_workbook
from .templates import (
    DataSource,
    _match_fields,
    _now,
    _physical_fields,
    _role,
    _tableau_datasource,
    _version,
    field_uid,
    load_mapping,
)
from .usage import _INSTANCE, _base_field, _code_ref_spans, _datasource_fields

FORMAT = "py-tbparse-library"
VERSION = 1
CLASH_POLICIES = ("rename", "skip", "fail")
PLAN_COLUMNS = ["uid", "kind", "name", "caption", "action", "target_name", "target_caption", "reason"]

_USER = "{http://www.tableausoftware.com/xml/user}"
_PARAMETERS = "Parameters"
_MAPPED = ("matched", "close match")


class LibraryError(ValueError):
    """The library cannot be made, read or applied as asked."""


# ---------------------------------------------------------------- helpers --

def _bracket(text: str) -> str:
    """`Top N` -> `[Top N]`, with `]` written as `]]`."""
    return "[" + text.replace("]", "]]") + "]"


def _unbracket(name: str) -> str:
    inner = name[1:-1] if name.startswith("[") and name.endswith("]") else name
    return inner.replace("]]", "]")


def _lf(text: Optional[str]) -> str:
    return (text or "").replace("\r\n", "\n")


def _xml_string(el) -> str:
    return etree.tostring(el, encoding="unicode", with_tail=False)


def _datasources(doc) -> list:
    return doc.xpath("/workbook/datasources/datasource[@name]")


def _parameters_ds(doc):
    found = doc.xpath("/workbook/datasources/datasource[@name=$p]", p=_PARAMETERS)
    return found[0] if found else None


def _pick_datasource(doc, datasource: Optional[str], what: str = "workbook"):
    """The one datasource a library comes from or goes to, by internal name or caption."""
    others = [d for d in _datasources(doc) if d.get("name") != _PARAMETERS]
    if datasource:
        hits = [d for d in others if d.get("name") == datasource] or \
               [d for d in others if datasource in (d.get("caption"), d.get("formatted-name"))]
        if len(hits) != 1:
            names = ", ".join(d.get("caption") or d.get("name") for d in others)
            raise LibraryError(f"{what}: " + (f"no datasource {datasource!r}" if not hits
                                              else f"{datasource!r} names {len(hits)} datasources; use the internal name")
                               + (f" (it has: {names})" if names else ""))
        return hits[0]
    with_conn = [d for d in others if d.find("connection") is not None]
    if len(with_conn) != 1:
        names = ", ".join(d.get("caption") or d.get("name") for d in with_conn)
        raise LibraryError(f"{what}: expected one datasource with a connection, found {len(with_conn)}"
                           + (f" ({names}); pick one with datasource=" if names else ""))
    return with_conn[0]


def _is_auto(col) -> bool:
    """A column Tableau made on its own (record count, split field, date bin)."""
    if any(col.get(_USER + a) is not None for a in ("auto-column", "SplitFieldIndex", "SplitFieldOrigin")):
        return True
    return col.get(_USER + "ui-builder") == "date-bin-builder"


def _user_free(attrib, drop: Iterable[str]) -> dict:
    return {k: v for k, v in attrib.items() if not k.startswith(_USER) and k not in drop}


def _calc_class(col) -> Optional[str]:
    calc = col.find("calculation")
    return calc.get("class") if calc is not None else None


def _scan(formula: Optional[str], datasources: Optional[Iterable[str]] = None) -> list[tuple]:
    """The references of a formula as `(kind, a, b, span)`: `param` for `[Parameters].[X]` (a is `[Parameters]`,
    b is `[X]`), `cross` for `[other].[X]` where `other` is one of `datasources` (any bracketed pair when
    that is None), else `local` (a is the name, b None). `span` is the `(start, end)` to replace: the whole
    pair, or the one name."""
    text = formula or ""
    spans = _code_ref_spans(text)
    names = None if datasources is None else set(datasources)
    out, i = [], 0
    while i < len(spans):
        s, e, ref = spans[i]
        nxt = spans[i + 1] if i + 1 < len(spans) else None
        if nxt and nxt[0] == e + 1 and text[e] == ".":
            if ref == "[" + _PARAMETERS + "]":
                out.append(("param", ref, nxt[2], (nxt[0], nxt[1])))
                i += 2
                continue
            if names is None or _unbracket(ref) in names:
                out.append(("cross", ref, nxt[2], (s, nxt[1])))
                i += 2
                continue
        out.append(("local", ref, None, (s, e)))
        i += 1
    return out


def rewrite_formula(formula: str, names: dict, params: dict, datasources: Optional[Iterable[str]] = None) -> str:
    """Rewrite the references of a formula: `[Name]` through `names`, the `[X]` of `[Parameters].[X]` through
    `params` (both map a bracketed name, as Tableau writes it, to another). Strings are left alone because
    the references come from `usage._code_ref_spans`. A `[other].[X]` pair that names another datasource is
    left as it is (`datasources` lists the datasource names; without it any other bracketed pair counts)."""
    out = formula or ""
    for kind, a, b, (s, e) in reversed(_scan(out, datasources)):
        if kind == "param":
            new = params.get(b, b)
        elif kind == "local":
            new = names.get(a, a)
        else:
            continue
        out = out[:s] + new + out[e:]
    return out


def _rewrite_ordering(value: str, ds_name: str, names: dict) -> str:
    """`[ds].[tdy:Field:qk]` -> the target datasource and the (renamed) field, keeping derivation and suffix.
    Anything not of that shape has its field name mapped as a whole."""
    spans = _code_ref_spans(value)
    if len(spans) != 2:
        return value
    inst = spans[1][2]
    m = _INSTANCE.match(inst)
    if m:
        base = names.get(f"[{m.group(1)}]")
        if base:
            head = inst[1:inst.index(":")]
            tail = inst[inst.rindex(":") + 1:-1]
            inst = f"[{head}:{base[1:-1]}:{tail}]"
    else:
        inst = names.get(inst, inst)
    return f"{_bracket(ds_name)}.{inst}"


def _uses(entry: dict, datasources: Iterable[str]) -> dict:
    """What an entry refers to: `locals` (names in its own datasource, in order), `params` (`[X]`), `cross`
    (`[other].[X]` strings) and `ordering` (the table calculation's field, as a local name)."""
    locals_, params, cross = [], [], []
    for kind, a, b, _ in _scan(entry.get("formula"), datasources):
        if kind == "local":
            if not a[1:-1].startswith(":"):
                locals_.append(a)
        elif kind == "param":
            params.append(b)
        else:
            cross.append(f"{a}.{b}")
    of = (entry.get("table_calc") or {}).get("ordering-field")
    ordering = []
    if of:
        spans = _code_ref_spans(of)
        if len(spans) == 2 and _unbracket(spans[0][2]) in set(datasources):
            ordering.append(_base_field(spans[1][2]))
        else:
            cross.append(of)
    return {"locals": locals_, "params": params, "cross": cross, "ordering": ordering}


# ----------------------------------------------------------------- export --

def _parameter_parts(col) -> dict:
    """The definition of a parameter column, in the shape a library entry holds it."""
    calc = col.find("calculation")
    members = col.find("members")
    rng = col.find("range")
    aliases = col.find("aliases")
    return {
        "formula": calc.get("formula") if calc is not None else None,
        "value": col.get("value"),
        "domain": col.get("param-domain-type"),
        "range": dict(rng.attrib) if rng is not None else None,
        "members": [dict(m.attrib) for m in members.findall("member")] if members is not None else None,
        "aliases": [dict(a.attrib) for a in aliases.findall("alias")] if aliases is not None else None,
    }


def _comment(col) -> Optional[str]:
    desc = col.find("desc")
    return _xml_string(desc) if desc is not None else None


def _folder_of(ds) -> dict[str, str]:
    out = {}
    for folder in ds.xpath("./folder[@name]|./folders-common/folder[@name]"):
        for item in folder.findall("folder-item"):
            out.setdefault(item.get("name"), folder.get("name"))
    return out


def _calc_entry(col, ds_name: str, folders: dict) -> dict:
    calc = col.find("calculation")
    tc = calc.find("table-calc")
    aliases = col.find("aliases")
    role = col.get("role") or _role(col.get("datatype"))
    return {
        "uid": field_uid(ds_name, col.get("name"), role, col.get("datatype")),
        "kind": "calc", "name": col.get("name"), "caption": col.get("caption"),
        "datatype": col.get("datatype"), "role": col.get("role"), "type": col.get("type"),
        "formula": calc.get("formula"), "formula_display": None, "refs": [], "depends_on": [],
        "attrs": _user_free(col.attrib, ("name", "caption", "datatype", "role", "type")),
        "calc_attrs": {k: v for k, v in calc.attrib.items() if k not in ("class", "formula")},
        "table_calc": dict(tc.attrib) if tc is not None else None,
        "aliases": [dict(a.attrib) for a in aliases.findall("alias")] if aliases is not None else None,
        "comment": _comment(col), "folder": folders.get(col.get("name")),
    }


def _param_entry(col, folders: dict) -> dict:
    parts = _parameter_parts(col)
    return {
        "uid": field_uid(_PARAMETERS, col.get("name"), col.get("role"), col.get("datatype")),
        "kind": "parameter", "name": col.get("name"), "caption": col.get("caption"),
        "datatype": col.get("datatype"), "role": col.get("role"), "type": col.get("type"),
        "formula": parts["formula"], "value": parts["value"], "domain": parts["domain"],
        "range": parts["range"], "members": parts["members"], "aliases": parts["aliases"],
        "attrs": _user_free(col.attrib, ("name", "caption", "datatype", "role", "type", "value", "param-domain-type")),
        "refs": [], "depends_on": [], "comment": _comment(col), "folder": folders.get(col.get("name")),
    }


def export_library(
    parser: TwbParser,
    datasource: Optional[str] = None,
    select: Optional[Iterable[str]] = None,
    folder: Optional[str] = None,
    with_dependencies: bool = True,
    include_parameters: bool = True,
    name: Optional[str] = None,
    description: Optional[str] = None,
    report: Optional[dict] = None,
) -> dict:
    """Collect calculated fields and parameters of one datasource into a library (a dict; `save_library`
    writes it).

    `datasource` is the internal name or caption (optional when only one datasource has a connection).
    `select` (internal names or captions) and `folder` (a folder of the datasource) pick calculations and
    parameters; with neither, every calculation the user made (not the record count, split fields and date
    bins Tableau makes, unless something uses them) is exported, plus every parameter when
    `include_parameters` is on. `with_dependencies` also takes the calculations (and parameters) a selected
    calculation uses; without it they are listed as required. A calculation that refers to another
    datasource is not exported (nor what depends on it); it is counted in `report['unsupported']`.

    `report`, if a dict, receives `exported`, `required`, `unsupported` (counts) and `unsupported_names`.
    """
    doc = parser.xml_doc
    ds = _pick_datasource(doc, datasource, Path(parser.twbx_path or parser.path).name)
    ds_name = ds.get("name")
    ds_names = [d.get("name") for d in _datasources(doc)]
    pds = _parameters_ds(doc)
    folders = _folder_of(ds)
    fields = _datasource_fields(ds)
    physical = {f["name"]: f for f in _physical_fields(ds)}

    cols = {c.get("name"): c for c in ds.xpath("./column[@name]")
            if _calc_class(c) == "tableau" and not c.get("param-domain-type")}
    pcols = {c.get("name"): c for c in (pds.xpath("./column[@name][@param-domain-type]") if pds is not None else [])}
    entries = {n: _calc_entry(c, ds_name, folders) for n, c in cols.items()}
    pentries = {n: _param_entry(c, folders) for n, c in pcols.items()}
    uses = {n: _uses(e, ds_names) for n, e in entries.items()}

    # entries that cannot be exported: another datasource, or something that depends on one
    unsupported = {n for n, u in uses.items() if u["cross"]}
    changed = True
    while changed:
        changed = False
        for n, u in uses.items():
            if n not in unsupported and any(r in unsupported for r in u["locals"] + u["ordering"] if r in cols):
                unsupported.add(n)
                changed = True

    # what was asked for
    if select is None and folder is None:
        chosen = [n for n, c in cols.items() if not _is_auto(c)]
        chosen_params = list(pentries) if include_parameters else []
    else:
        wanted = set(select or [])
        found: set = set()
        chosen, chosen_params = [], []
        for pool, picked in ((entries, chosen), (pentries, chosen_params)):
            for n, e in pool.items():
                hit = {w for w in wanted if w in (n, e["caption"])}
                if hit or (folder and e["folder"] == folder):
                    picked.append(n)
                    found |= hit
        missing = wanted - found
        if missing:
            raise LibraryError(f"nothing named {', '.join(map(repr, sorted(missing)))} in {ds.get('caption') or ds_name}")
        if not chosen and not chosen_params:
            raise LibraryError(f"folder {folder!r} holds no calculation or parameter of {ds.get('caption') or ds_name}")
    out_calcs = {n for n in chosen if n not in unsupported}

    def pull(calc_names: set, param_names: set) -> None:
        """Add the calculations and parameters the chosen ones use."""
        todo = list(calc_names)
        while todo:
            u = uses[todo.pop()]
            for r in u["locals"] + u["ordering"]:
                if r in cols and r not in calc_names and r not in unsupported:
                    calc_names.add(r)
                    todo.append(r)
        for n in calc_names:
            for p in uses[n]["params"]:
                if p in pcols:
                    param_names.add(p)

    out_params = set(chosen_params)
    if with_dependencies:
        pull(out_calcs, out_params)
        if not include_parameters:
            out_params &= set(chosen_params)

    # the fields and other objects they need
    uid_of = {n: entries[n]["uid"] for n in out_calcs} | {n: pentries[n]["uid"] for n in out_params}
    required: dict[tuple, dict] = {}

    def need(kind: str, nm: str, user: str) -> None:
        key = (kind == "parameter", nm)
        r = required.get(key)
        if r is None:
            r = required[key] = _required_item(kind, nm, ds, fields, physical, pcols)
        r["used_by"].append(user)

    for n in sorted(out_calcs):
        e, u = entries[n], uses[n]
        depends = []
        for r in u["locals"] + u["ordering"]:
            if r in out_calcs:
                depends.append(uid_of[r])
            else:
                need(_kind_of(r, cols, fields, ds), r, e["uid"])
        for p in u["params"]:
            if p in out_params:
                depends.append(uid_of[p])
            else:
                need("parameter", p, e["uid"])
        e["depends_on"] = list(dict.fromkeys(depends))
        e["refs"] = list(dict.fromkeys(
            [f"{a}.{b}" if kind == "param" else a for kind, a, b, _ in _scan(e["formula"], ds_names) if kind != "cross"]
            + [(e["table_calc"] or {}).get("ordering-field")] * bool((e["table_calc"] or {}).get("ordering-field"))))
    # display formulas: calculation and parameter names swapped for captions
    cap_names = {n: _bracket(entries[n]["caption"]) for n in out_calcs if entries[n]["caption"]}
    cap_params = {n: _bracket(pentries[n]["caption"]) for n in out_params if pentries[n]["caption"]}
    for n in out_calcs:
        entries[n]["formula_display"] = rewrite_formula(entries[n]["formula"], cap_names, cap_params, ds_names)
    for n in out_params:
        pentries[n]["formula_display"] = pentries[n]["formula"]
    for key in required.values():
        key["used_by"] = sorted(set(key["used_by"]))

    result = {
        "format": FORMAT, "version": VERSION,
        "name": name or Path(parser.twbx_path or parser.path).stem,
        "description": description or "",
        "created": _now(), "py_tbparse_version": _version(),
        "source": {"workbook": Path(parser.twbx_path or parser.path).name, "datasource": ds_name,
                   "datasource_caption": ds.get("caption")},
        "required": sorted(required.values(), key=lambda r: (r["kind"], r["name"])),
        "entries": [entries[n] for n in cols if n in out_calcs] + [pentries[n] for n in pcols if n in out_params],
    }
    for e in result["entries"]:
        e.setdefault("formula_display", e["formula"])
    if report is not None:
        names = sorted(_unbracket(n) for n in unsupported if n in set(chosen) | _closure_names(chosen, uses, cols))
        report.update(exported=len(result["entries"]), required=len(result["required"]),
                      unsupported=len(names), unsupported_names=names)
    return result


def _closure_names(chosen: list, uses: dict, cols: dict) -> set:
    """The chosen calculations and everything they use (the unsupported ones among them are reported)."""
    seen, todo = set(), list(chosen)
    while todo:
        n = todo.pop()
        if n in seen:
            continue
        seen.add(n)
        todo += [r for r in uses[n]["locals"] + uses[n]["ordering"] if r in cols]
    return seen


def _kind_of(ref: str, cols: dict, fields: dict, ds) -> str:
    """What a reference in a formula names, when it is not exported: field, calc, group, set, bin or unknown."""
    if ref in cols:
        return "calc"
    groups = ds.xpath("./group[@name=$n]", n=ref)
    if groups:
        return "set" if groups[0].get(_USER + "ui-builder") == "filter-group" else "group"
    cs = ds.xpath("./column[@name=$n]", n=ref)
    if cs and _calc_class(cs[0]):
        return "group" if _calc_class(cs[0]) == "categorical-bin" else ("bin" if _calc_class(cs[0]) == "bin" else "unknown")
    if ref in fields and fields[ref]["kind"] == "physical":
        return "field"
    return "unknown"


def _required_item(kind: str, name: str, ds, fields: dict, physical: dict, pcols: dict) -> dict:
    col = pcols.get(name) if kind == "parameter" else (ds.xpath("./column[@name=$n]", n=name) or [None])[0]
    if kind == "parameter":
        info = {}
    else:
        info = fields.get(name) or {}
    datatype = (col.get("datatype") if col is not None else None) or info.get("datatype")
    role = (col.get("role") if col is not None else None) or (_role(datatype) if datatype else None)
    return {
        "name": name, "caption": (col.get("caption") if col is not None else None) or info.get("caption"),
        "remote": physical[name]["remote"] if name in physical else (name[1:-1] if kind == "field" else None),
        "datatype": datatype, "role": role, "kind": kind, "required": True, "used_by": [],
    }


# ----------------------------------------------------------- save / load --

def save_library(library: dict, path: Union[str, os.PathLike], overwrite: bool = False) -> str:
    """Write a library as `*.library.json` (UTF-8, indent 2, keys sorted). An existing file is only replaced
    with `overwrite=True`."""
    text = json.dumps(library, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    with open(path, "w" if overwrite else "x", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
    return str(path)


def load_library(path: Union[str, os.PathLike]) -> dict:
    """Read a library back. Raises `LibraryError` when it is not one or is a newer format than this version
    reads."""
    with open(path, encoding="utf-8") as fh:
        try:
            lib = json.load(fh)
        except json.JSONDecodeError as e:
            raise LibraryError(f"{path}: not a library file ({e})") from None
    if not isinstance(lib, dict) or lib.get("format") != FORMAT:
        raise LibraryError(f"{path}: not a py-tbparse library (format is {lib.get('format') if isinstance(lib, dict) else None!r})")
    if not isinstance(lib.get("version"), int) or lib["version"] > VERSION:
        raise LibraryError(f"{path}: library version {lib.get('version')!r} is newer than this py-tbparse reads ({VERSION})")
    for key in ("entries", "required"):
        if not isinstance(lib.get(key), list):
            raise LibraryError(f"{path}: library has no {key!r} list")
    return lib


def _check_library(library: dict) -> dict:
    if not isinstance(library, dict) or library.get("format") != FORMAT:
        raise LibraryError("not a py-tbparse library")
    if not isinstance(library.get("version"), int) or library["version"] > VERSION:
        raise LibraryError(f"library version {library.get('version')!r} is newer than this py-tbparse reads ({VERSION})")
    return library


def _display(item: dict) -> str:
    return item.get("caption") or _unbracket(item["name"])


def library_table(library: dict) -> pd.DataFrame:
    """One row per entry and per required item: `kind, name, caption, datatype, depends_on, required_by`
    (what an entry needs, and which entries need an item, by caption or name)."""
    _check_library(library)
    by_uid = {e["uid"]: e for e in library["entries"]}
    rows = []
    for r in library["required"]:
        rows.append({"kind": r["kind"], "name": r["name"], "caption": r.get("caption"), "datatype": r.get("datatype"),
                     "depends_on": "", "required_by": ", ".join(_display(by_uid[u]) for u in r.get("used_by", []) if u in by_uid)})
    for e in library["entries"]:
        needs = [r for r in library["required"] if e["uid"] in r.get("used_by", [])]
        deps = [_display(by_uid[u]) for u in e.get("depends_on", []) if u in by_uid] + [_display(r) for r in needs]
        users = [_display(o) for o in library["entries"] if e["uid"] in o.get("depends_on", [])]
        rows.append({"kind": e["kind"], "name": e["name"], "caption": e.get("caption"), "datatype": e.get("datatype"),
                     "depends_on": ", ".join(deps), "required_by": ", ".join(users)})
    return pd.DataFrame(rows, columns=["kind", "name", "caption", "datatype", "depends_on", "required_by"])


# ----------------------------------------------------------------- import --

def _order(entries: list[dict]) -> list[dict]:
    """Entries so that each comes after what it depends on (Kahn's algorithm; of those ready, parameters
    first, then by kind and name). A cycle raises `LibraryError`."""
    by_uid = {e["uid"]: e for e in entries}
    waiting = {e["uid"]: {d for d in e.get("depends_on", []) if d in by_uid and d != e["uid"]} for e in entries}
    users: dict[str, list] = {}
    for u, deps in waiting.items():
        for d in deps:
            users.setdefault(d, []).append(u)

    def key(e):
        return (e["kind"] != "parameter", e["kind"], e["name"], e["uid"])

    ready = [(key(by_uid[u]), u) for u, deps in waiting.items() if not deps]
    heapq.heapify(ready)
    out = []
    while ready:
        _, u = heapq.heappop(ready)
        out.append(by_uid[u])
        for v in users.get(u, []):
            waiting[v].discard(u)
            if not waiting[v]:
                heapq.heappush(ready, (key(by_uid[v]), v))
    if len(out) != len(entries):
        stuck = sorted(_display(by_uid[u]) for u, deps in waiting.items() if deps)
        raise LibraryError("the library's calculations depend on each other in a circle: " + ", ".join(stuck))
    return out


def _mapping_dict(mapping, data: DataSource) -> dict[str, str]:
    """`{required name or caption: target local name}` from a dict, a mapping CSV/DataFrame, or None."""
    if mapping is None:
        return {}
    locals_ = {f["local"] for f in data.fields}
    by_remote = {f["name"]: f["local"] for f in data.fields}
    if isinstance(mapping, dict):
        pairs = {str(k): str(v) for k, v in mapping.items() if not is_missing(v) and str(v).strip()}
    else:
        df = load_mapping(mapping)
        pairs = {r["field"]: r["mapped_to"] for r in df.to_dict("records") if r["mapped_to"]}
    out = {}
    for k, v in pairs.items():
        out[k] = v if v in locals_ else by_remote.get(v, v)
    return out


def _identical_calc(col, caption, datatype, formula) -> bool:
    calc = col.find("calculation")
    return (calc is not None and calc.get("class") == "tableau" and not col.get("param-domain-type")
            and col.get("caption") == caption and col.get("datatype") == datatype
            and _lf(calc.get("formula")) == _lf(formula))


def _same_param(a: dict, b: dict) -> bool:
    keys = ("caption", "datatype", "domain", "value", "members", "range")
    return all(a.get(k) == b.get(k) for k in keys)


def _param_def(entry: dict) -> dict:
    return {k: entry.get(k) for k in ("caption", "datatype", "domain", "value", "members", "range")}


def _param_def_col(col) -> dict:
    parts = _parameter_parts(col)
    return {"caption": col.get("caption"), "datatype": col.get("datatype"), "domain": parts["domain"],
            "value": parts["value"], "members": parts["members"], "range": parts["range"]}


def _suffixed(caption: str, taken: set) -> str:
    n = 2
    while f"{caption} ({n})" in taken:
        n += 1
    return f"{caption} ({n})"


def _next_calc_name(ds_name: str, caption: Optional[str], formula: str, taken: set) -> str:
    n = int(hashlib.sha1("\x1f".join((ds_name, caption or "", formula)).encode("utf-8")).hexdigest(), 16) % 10 ** 18
    while f"[Calculation_{n:018d}]" in taken:
        n += 1
    return f"[Calculation_{n:018d}]"


def _next_param_name(name: str, taken: set) -> str:
    m = re.match(r"^\[(.*?)(\d+)\]$", name)
    prefix = m.group(1) if m else "Parameter "
    n = 1
    while f"[{prefix}{n}]" in taken:
        n += 1
    return f"[{prefix}{n}]"


def _plan(parser: TwbParser, library: dict, datasource: Optional[str], mapping, on_clash: str):
    """Work out what an import does. Returns `(plan, actions, target_el)`: the plan table, one action
    per entry that is added and the target datasource element."""
    if on_clash not in CLASH_POLICIES:
        raise LibraryError(f"on_clash must be one of {', '.join(CLASH_POLICIES)}, got {on_clash!r}")
    _check_library(library)
    doc = parser.xml_doc
    T = _pick_datasource(doc, datasource, Path(parser.twbx_path or parser.path).name)
    t_name = T.get("name")
    ds_names = [d.get("name") for d in _datasources(doc)]
    pds = _parameters_ds(doc)
    t_fields = _datasource_fields(T)
    t_cols = {c.get("name"): c for c in T.xpath("./column[@name]")}
    p_cols = {c.get("name"): c for c in (pds.xpath("./column[@name]") if pds is not None else [])}
    data = _tableau_datasource(T, str(parser.twbx_path or parser.path))
    wanted = _mapping_dict(mapping, data)
    rows: list[dict] = []

    # 1. the fields and objects the library needs
    target_of: dict[tuple, str] = {}
    open_fields = []
    for r in library["required"]:
        key = (r["kind"] == "parameter", r["name"])
        pool = p_cols if r["kind"] == "parameter" else t_fields
        hit = wanted.get(r["name"]) or (wanted.get(r["caption"]) if r.get("caption") else None)
        if hit:
            if hit in pool or (r["kind"] != "parameter" and hit in t_cols):
                target_of[key] = hit
                rows.append(_req_row(r, "mapped", hit, "mapping"))
            else:
                rows.append(_req_row(r, "unmapped", "", f"the mapping names {hit}, which the target does not have"))
        elif r["name"] in pool:
            target_of[key] = r["name"]
            rows.append(_req_row(r, "mapped", r["name"], "same name"))
        elif r["kind"] == "field":
            open_fields.append(r)
        else:
            rows.append(_req_row(r, "unmapped", "", f"the target has no {r['kind']} named {r['name']}"))
    if open_fields:
        taken_locals = set(target_of.values())
        free = DataSource(path=data.path, kind="tableau", element=T,
                          fields=[f for f in data.fields if f["local"] not in taken_locals])
        local_of = {f["name"]: f["local"] for f in data.fields}
        table = _match_fields(
            [{"name": r["name"], "caption": r.get("caption"), "remote": r.get("remote"),
              "datatype": r.get("datatype") or "string", "required": True, "role": r.get("role")} for r in open_fields],
            free, t_name)
        status = {m["field"]: m for m in table.to_dict("records")}
        for r in open_fields:
            m = status[r["name"]]
            ok = m["mapped_to"] and (m["status"] in _MAPPED or str(m["status"]).endswith("differs"))
            if ok:
                target_of[(False, r["name"])] = local_of[m["mapped_to"]]
                rows.append(_req_row(r, "mapped", local_of[m["mapped_to"]], f"{m['status']} ({m['mapped_to']})"))
            else:
                rows.append(_req_row(r, "unmapped", "", str(m["status"])))

    names: dict[str, str] = {nm: tgt for (is_p, nm), tgt in target_of.items() if not is_p}
    params: dict[str, str] = {nm: tgt for (is_p, nm), tgt in target_of.items() if is_p}
    unmapped = {(is_p, r["name"]) for r in library["required"] for is_p in [r["kind"] == "parameter"]
                if (is_p, r["name"]) not in target_of}

    # 2. entries, dependencies first
    entries = _order(list(library["entries"]))
    by_uid = {e["uid"]: e for e in entries}
    failed: set = set()
    taken_names = set(t_cols) | set(t_fields)
    taken_pnames = set(p_cols)
    taken_caps = {c.get("caption") or _unbracket(n) for n, c in t_cols.items()} | \
                 {f["caption"] or _unbracket(n) for n, f in t_fields.items()}
    taken_pcaps = {c.get("caption") or _unbracket(n) for n, c in p_cols.items()}
    actions: list[dict] = []

    def row(e, action, target_name="", target_caption="", reason=""):
        r = {"uid": e["uid"], "kind": e["kind"], "name": e["name"], "caption": e.get("caption"),
             "action": action, "target_name": target_name, "target_caption": target_caption, "reason": reason}
        rows.append(r)
        return r

    for e in entries:
        is_param = e["kind"] == "parameter"
        bad = [_display(by_uid[d]) for d in e.get("depends_on", []) if d in failed]
        if bad:
            failed.add(e["uid"])
            row(e, "fail-dependency", reason="depends on " + ", ".join(bad) + ", which was not imported")
            continue
        if is_param:
            same = p_cols.get(e["name"])
            if same is not None and _same_param(_param_def_col(same), _param_def(e)):
                params[e["name"]] = e["name"]
                row(e, "skip-identical", e["name"], same.get("caption") or "", "the target has this parameter")
                continue
        else:
            same = t_cols.get(e["name"])
            if same is not None and _identical_calc(same, e.get("caption"), e.get("datatype"), e["formula"]):
                names[e["name"]] = e["name"]
                row(e, "skip-identical", e["name"], same.get("caption") or "", "the target has this calculation")
                continue
        if not is_param:
            u = _uses(e, ds_names)
            lacking = [r for r in u["locals"] + u["ordering"] if (False, r) in unmapped]
            lacking += [f"[Parameters].{p}" for p in u["params"] if (True, p) in unmapped]
            if lacking:
                failed.add(e["uid"])
                row(e, "fail-unmapped", reason="the target has no match for " + ", ".join(dict.fromkeys(lacking)))
                continue
            formula = rewrite_formula(e["formula"], names, params, ds_names)
            if e.get("caption"):
                twin = next((c for c in t_cols.values() if c.get("caption") == e["caption"]
                             and _identical_calc(c, e["caption"], e.get("datatype"), formula)), None)
                if twin is not None:
                    names[e["name"]] = twin.get("name")
                    row(e, "skip-identical", twin.get("name"), twin.get("caption"), "the target has this calculation under another name")
                    continue
        else:
            formula = e["formula"]
            if e.get("caption"):
                twin = next((c for c in p_cols.values() if c.get("caption") == e["caption"]
                             and _same_param(_param_def_col(c), _param_def(e))), None)
                if twin is not None:
                    params[e["name"]] = twin.get("name")
                    row(e, "skip-identical", twin.get("name"), twin.get("caption"), "the target has this parameter under another name")
                    continue
        # caption clash
        caption = e.get("caption")
        shown = caption or _unbracket(e["name"])
        caps = taken_pcaps if is_param else taken_caps
        new_caption, reason = caption, []
        if shown in caps:
            if on_clash == "fail":
                raise LibraryError(f"{shown!r} is already in the target datasource (on_clash='fail')")
            if on_clash == "skip":
                other = next(((n, c) for n, c in (p_cols if is_param else t_cols).items()
                              if (c.get("caption") or _unbracket(n)) == shown), None)
                if other is None:   # a physical field or group (no column element), or one added a moment ago
                    other = next(((n, None) for n, f in t_fields.items() if (f["caption"] or _unbracket(n)) == shown), None) or \
                        next((a["name"], None) for a in actions
                             if (a["caption"] or _unbracket(a["name"])) == shown and (a["entry"]["kind"] == "parameter") == is_param)
                (params if is_param else names)[e["name"]] = other[0]
                why = f"the target already has {shown!r}"
                if other[1] is not None and other[1].get("datatype") != e.get("datatype"):
                    why += f" (datatype {other[1].get('datatype')}, the library's is {e.get('datatype')})"
                row(e, "skip-clash", other[0], shown, why)
                continue
            new_caption = _suffixed(shown, caps)
            reason.append(f"caption {shown!r} was taken")
        # internal name
        new_name = e["name"]
        used = taken_pnames if is_param else taken_names
        if new_name in used:
            new_name = _next_param_name(e["name"], used) if is_param \
                else _next_calc_name(t_name, new_caption, formula, used)
            reason.append(f"internal name {e['name']} was taken, now {new_name}")
        (params if is_param else names)[e["name"]] = new_name
        used.add(new_name)
        caps.add(new_caption or _unbracket(new_name))
        act = {"entry": e, "name": new_name, "caption": new_caption, "formula": formula}
        if not is_param and e.get("table_calc") and e["table_calc"].get("ordering-field"):
            act["ordering_field"] = _rewrite_ordering(e["table_calc"]["ordering-field"], t_name, names)
        actions.append(act)
        row(e, "add-renamed" if new_caption != caption else "add", new_name, new_caption or "", "; ".join(reason))
    return pd.DataFrame(rows, columns=PLAN_COLUMNS), actions, T


def _req_row(r: dict, action: str, target: str, reason: str) -> dict:
    return {"uid": "", "kind": r["kind"], "name": r["name"], "caption": r.get("caption"),
            "action": action, "target_name": target, "target_caption": "", "reason": reason}


def plan_import(
    parser: TwbParser,
    library: dict,
    datasource: Optional[str] = None,
    mapping: Union[dict, str, pd.DataFrame, None] = None,
    on_clash: str = "rename",
) -> pd.DataFrame:
    """What `import_library` would do, one row per required item (`action` `mapped` or `unmapped`) and per
    entry (`add`, `add-renamed`, `skip-identical`, `skip-clash`, `fail-unmapped` or `fail-dependency`), with
    why. Nothing is written. Columns are `PLAN_COLUMNS`. Raises `LibraryError` for `on_clash='fail'` when
    something clashes, or when the library's entries depend on each other in a circle."""
    return _plan(parser, library, datasource, mapping, on_clash)[0]


def _load(library: Union[dict, str, os.PathLike]) -> dict:
    return library if isinstance(library, dict) else load_library(library)


def _build_calc(a: dict):
    e = a["entry"]
    col = etree.Element("column")
    base = {"datatype": e["datatype"], "name": a["name"], "role": e.get("role"), "type": e.get("type")}
    if a["caption"]:
        col.set("caption", a["caption"])
    for k, v in base.items():
        if v is not None:
            col.set(k, v)
    for k in sorted(e.get("attrs") or {}):
        col.set(k, e["attrs"][k])
    calc = etree.SubElement(col, "calculation", {"class": "tableau", "formula": a["formula"]})
    for k in sorted(e.get("calc_attrs") or {}):
        calc.set(k, e["calc_attrs"][k])
    if e.get("table_calc") is not None:
        tc = dict(e["table_calc"])
        if "ordering_field" in a:
            tc["ordering-field"] = a["ordering_field"]
        etree.SubElement(calc, "table-calc", tc)
    _append_extras(col, e)
    return col


def _build_param(a: dict):
    e = a["entry"]
    col = etree.Element("column")
    if a["caption"]:
        col.set("caption", a["caption"])
    col.set("datatype", e["datatype"])
    col.set("name", a["name"])
    if e.get("domain"):
        col.set("param-domain-type", e["domain"])
    col.set("role", e["role"])
    col.set("type", e["type"])
    col.set("value", e["value"])
    for k in sorted(e.get("attrs") or {}):
        col.set(k, e["attrs"][k])
    etree.SubElement(col, "calculation", {"class": "tableau", "formula": e["formula"]})
    if e.get("aliases"):
        al = etree.SubElement(col, "aliases")
        for item in e["aliases"]:
            etree.SubElement(al, "alias", item)
    if e.get("range") is not None:
        etree.SubElement(col, "range", e["range"])
    if e.get("members") is not None:
        mem = etree.SubElement(col, "members")
        for item in e["members"]:
            etree.SubElement(mem, "member", item)
    if e.get("comment"):
        col.append(etree.fromstring(e["comment"]))
    return col


def _append_extras(col, e: dict) -> None:
    if e.get("aliases"):
        al = etree.SubElement(col, "aliases")
        for item in e["aliases"]:
            etree.SubElement(al, "alias", item)
    if e.get("comment"):
        col.append(etree.fromstring(e["comment"]))


def _new_parameters_ds(doc):
    """The datasource Tableau 2024 writes for parameters, as the first child of `<datasources>`."""
    pds = etree.Element("datasource", {"hasconnection": "false", "inline": "true", "name": _PARAMETERS, "version": "18.1"})
    etree.SubElement(pds, "aliases", {"enabled": "yes"})
    doc.xpath("/workbook/datasources")[0].insert(0, pds)
    return pds


def _report(report: Optional[dict], rows: pd.DataFrame) -> None:
    if report is None:
        return
    entries = rows[rows["uid"] != ""]

    def put(key: str, sel) -> None:
        names = [r["caption"] or _unbracket(r["name"]) for r in entries[sel(entries)].to_dict("records")]
        report[key] = len(names)
        report[key + "_names"] = names

    put("added", lambda d: d["action"].isin(["add", "add-renamed"]))
    put("skipped_identical", lambda d: d["action"] == "skip-identical")
    put("renamed", lambda d: d["action"] == "add-renamed")
    put("skipped", lambda d: d["action"] == "skip-clash")
    put("failed", lambda d: d["action"] == "fail-unmapped")
    put("skipped_dependents", lambda d: d["action"] == "fail-dependency")
    internal = [r["name"] for r in entries.to_dict("records")
                if r["action"].startswith("add") and r["target_name"] != r["name"]]
    report["renamed_internal"] = len(internal)
    report["renamed_internal_names"] = internal


def build_imported_workbook(
    parser: TwbParser,
    library: dict,
    datasource: Optional[str] = None,
    mapping: Union[dict, str, pd.DataFrame, None] = None,
    on_clash: str = "rename",
    report: Optional[dict] = None,
) -> bytes:
    """Bytes of a copy of the workbook with the library's calculations and parameters added (see
    `plan_import` for what is added and why). A `.twb` gives `.twb` bytes; a `.twbx` gives a `.twbx` with every
    other member copied across untouched. `report`, if a dict, receives `added`, `skipped_identical`,
    `renamed`, `skipped`, `failed`, `skipped_dependents` and `renamed_internal`, each a count with a
    `<name>_names` list."""
    plan, actions, target = _plan(parser, library, datasource, mapping, on_clash)
    _report(report, plan)
    doc = copy.deepcopy(parser.xml_doc)
    T = doc.xpath("/workbook/datasources/datasource[@name=$n]", n=target.get("name"))[0]
    pds = _parameters_ds(doc)
    for a in actions:
        if a["entry"]["kind"] == "parameter":
            if pds is None:
                pds = _new_parameters_ds(doc)
            _insert_column(pds, _build_param(a))
        else:
            _insert_column(T, _build_calc(a))
    return _serialize_workbook(parser, doc)


def import_library(
    parser: TwbParser,
    library: Union[dict, str, os.PathLike],
    datasource: Optional[str] = None,
    mapping: Union[dict, str, pd.DataFrame, None] = None,
    on_clash: str = "rename",
    output_path: Optional[str] = None,
    overwrite: bool = False,
    report: Optional[dict] = None,
) -> str:
    """Write a copy of the workbook with the library added and return its path. The output defaults to
    `<name>_library.<ext>` beside the source, must keep the source's extension, and the input is never
    overwritten (an existing output only with `overwrite=True`). `library` is a dict or a path."""
    library = _load(library)
    source = Path(parser.twbx_path or parser.path)
    out = Path(output_path) if output_path else source.with_name(f"{source.stem}_library{source.suffix}")
    if out.suffix.lower() != source.suffix.lower():
        raise LibraryError(f"output must end in {source.suffix}, got {out.suffix or 'no extension'}")
    if out.exists() and (out.resolve() == source.resolve() or not overwrite):
        raise FileExistsError(f"refusing to overwrite existing file: {out}")
    data = build_imported_workbook(parser, library, datasource, mapping, on_clash, report)
    with open(out, "wb" if overwrite else "xb") as fh:    # "xb" refuses a file created since the check
        fh.write(data)
    return str(out)
