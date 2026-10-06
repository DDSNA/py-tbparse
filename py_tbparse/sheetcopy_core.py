"""The shared core of `sheet copy` (WP14b): what a worksheet needs, and how to point it at another datasource.

Library functions only, no CLI (WP14e adds `sheet copy` on top of this). Nothing here writes a file.

* `sheet_datasources()`, `dependency_closure()`: the datasources a worksheet uses and everything it needs from
  the **source datasource**, not from the sheet's cached `datasource-dependencies` (those are not a closure:
  a calculation cached there can name a field the list lacks).
* `compare_to_target()`: for a closure and a target datasource, what is present, identical, to add, clashing
  or missing.
* `connection_signature()`, `match_datasource()`: finds the target datasource with the same connection. First
  slice rule (owner decision): the match must also have the SAME INTERNAL NAME; a different name is refused,
  never rewritten (`allow_rename=True` is there for later slices).
* `rewrite_references()`: rewrites a copied element. The datasource prefix (`[old].[x]`, `datasource='old'`)
  and a name -> name map for fields and a second one for `[Parameters].[X]`, over formulas, attributes, text,
  instance names (`[sum:Sales:qk]`) and the cached dependency copies. String literals in formulas are skipped.
* `new_uuid()`, `renew_uuids()`, `add_window()`, `copy_sheet_element()`, `copy_window()`: uuid and window
  helpers (the first and the third were lifted from `scaffold.py`, which now uses them).

Never opened in Tableau Desktop; keep saying so.
"""

from __future__ import annotations

import copy
import re
import uuid
from dataclasses import dataclass, field as _field
from typing import Iterable, Optional

from lxml import etree

from .library import _PARAMETERS, _bracket, _calc_class, _scan, _unbracket
from .templates import _base_name, _connections, _non_parameter_datasources
from .usage import _BRACKETED, _INSTANCE, _code_ref_spans, _datasource_fields

# Attributes that hold a bare `[name]` (no datasource prefix) inside a datasource-dependencies copy.
_BARE_ATTRS = ("name", "column", "formula", "ordering-field", "ordering-field-name")
_ACTION_GROUP = re.compile(r"^\[Action \(")
_FILE_ATTRS = ("filename", "directory")
_SUFFIXES = ("nk", "ok", "qk", "fn", "tn")
_DERIVATIONS = ("none", "usr", "sum", "avg", "cnt", "cntd", "min", "max", "med", "attr", "var", "stdev", "yr", "qr",
                "mn", "wk", "dy", "hr", "mt", "sc", "tyr", "tqr", "tmn", "twk", "tdy", "thr", "tmt", "tsc",
                "pcto", "pctd", "pcti", "pctn")
# Names Tableau makes up for a view; no datasource defines them, so they are neither copied nor missing.
_BUILTIN = re.compile(r"^\[(?::.*|Multiple Values|.*\(generated\)|__tableau_internal_object_id__(?:\]\.\[.*)?|AdhocCluster:.*|"
                      r"Number of Records)\]$")


class SheetCopyError(ValueError):
    """A sheet cannot be copied as asked (no or several matching datasources, a name that differs...)."""


# ------------------------------------------------------------- uuids, windows --

def new_uuid(taken: set) -> str:
    """A new `{UPPERCASE-UUID}` that is not in `taken`; it is added to `taken`."""
    while True:
        u = "{" + str(uuid.uuid4()).upper() + "}"
        if u not in taken:
            taken.add(u)
            return u


def renew_uuids(el, taken: set) -> int:
    """Give every `simple-id` under `el` a new uuid (all of them, so a copy never shares an id with its source).
    Returns how many were renewed."""
    n = 0
    for sid in el.iter("simple-id"):
        sid.set("uuid", new_uuid(taken))
        n += 1
    return n


def windows_element(doc):
    """The `<windows>` of a workbook, created (after `<dashboards>`, else at the end) when it is missing."""
    windows = doc.find("windows")
    if windows is None:
        windows = etree.Element("windows")
        anchor = doc.find("dashboards")
        if anchor is None:
            anchor = doc.find("worksheets")
        if anchor is not None:
            anchor.addnext(windows)
        else:
            (doc.getroot() if hasattr(doc, "getroot") else doc).append(windows)
    return windows


def add_window(doc, klass: str, name: str, viewpoints: Iterable[str], win_uuid: str):
    """Append a plain window (`<active id="-1"/>`, which the schema wants, and a viewpoint per name) and return it."""
    win = etree.SubElement(windows_element(doc), "window", {"class": klass, "name": name})
    vps = etree.SubElement(win, "viewpoints")
    for sheet in viewpoints:
        etree.SubElement(vps, "viewpoint", name=sheet)
    etree.SubElement(win, "active", id="-1")
    etree.SubElement(win, "simple-id", uuid=win_uuid)
    return win


def copy_window(src_doc, dst_doc, sheet: str, new_name: str, taken: set, hidden: bool = False):
    """Append a copy of the sheet's worksheet window (renamed, with a new uuid, `hidden` only when asked) to the
    target's windows and return it; None when the source has no window for the sheet."""
    found = src_doc.xpath("/workbook/windows/window[@class='worksheet'][@name=$n]", n=sheet)
    if not found:
        return None
    win = copy.deepcopy(found[0])
    win.set("name", new_name)
    if hidden:
        win.set("hidden", "true")
    else:
        win.attrib.pop("hidden", None)
    renew_uuids(win, taken)
    windows_element(dst_doc).append(win)
    return win


# ------------------------------------------------------------------ reading --

def _worksheet(doc, name: str):
    found = doc.xpath("/workbook/worksheets/worksheet[@name=$n]", n=name)
    if not found:
        raise SheetCopyError(f"no worksheet named {name!r}")
    return found[0]


def _datasource(doc, name: str):
    found = doc.xpath("/workbook/datasources/datasource[@name=$n]", n=name)
    if not found:
        raise SheetCopyError(f"no datasource named {name!r}")
    return found[0]


def sheet_datasources(doc, sheet: str) -> list[str]:
    """Internal names of the non-Parameters datasources a worksheet uses, from its own `datasources` list
    (more than one is a blend)."""
    ws = _worksheet(doc, sheet)
    names = [n for n in ws.xpath("./table/view/datasources/datasource/@name") if n != _PARAMETERS]
    return list(dict.fromkeys(names))


def _tokens_of(el) -> Iterable[str]:
    for node in el.iter():
        if not isinstance(node.tag, str):
            continue
        yield from node.attrib.values()
        if node.text and node.text.strip():
            yield node.text


def _scan_any(text: str, literal_aware: bool) -> list[tuple]:
    """`library._scan(text, None)`'s rows `(kind, a, b, span)`. With `literal_aware` false quotes are ordinary
    characters: in an attribute such as a filter's `member='"[ds].[avg:Sales:qk]"'` the quotes belong to the
    value and the reference inside is a real one, whereas in a formula a quoted `[x]` is text."""
    if literal_aware:
        return _scan(text, None)
    spans = [(m.start(), m.end(), m.group(0)) for m in _BRACKETED.finditer(text)]
    out, i = [], 0
    while i < len(spans):
        s, e, ref = spans[i]
        nxt = spans[i + 1] if i + 1 < len(spans) else None
        if nxt and nxt[0] == e + 1 and text[e] == ".":
            out.append(("param" if ref == "[" + _PARAMETERS + "]" else "cross", ref, nxt[2],
                        (nxt[0], nxt[1]) if ref == "[" + _PARAMETERS + "]" else (s, nxt[1])))
            i += 2
            continue
        out.append(("local", ref, None, (s, e)))
        i += 1
    return out


def _pairs(text: str) -> list[tuple[str, str]]:
    """The `([a], [b])` pairs of an attribute or text (quotes are not special), `([a], "")` for a lone reference."""
    return [(a, b or "") for _, a, b, _ in _scan_any(text, False)]


def _base_of_instance(ref: str) -> str:
    """`[sum:Sales:qk]` -> `[Sales]`; `[Calculation_1:qk]` -> `[Calculation_1]`; else the reference itself."""
    m = _INSTANCE.match(ref)
    if m:
        return "[" + m.group(1) + "]"
    inner = ref[1:-1]
    if inner.count(":") == 1 and not inner.startswith(":"):
        left, right = inner.split(":")
        if right in _SUFFIXES:
            return "[" + left + "]"
        if left in _DERIVATIONS:
            return "[" + right + "]"
    return ref


@dataclass
class Closure:
    """What one worksheet needs from its source datasource. Names are bracketed, as Tableau writes them."""
    sheet: str
    datasource: str
    fields: list = _field(default_factory=list)          # physical fields (and drill-path-only names)
    calcs: list = _field(default_factory=list)           # calculations, dependencies before dependents
    parameters: list = _field(default_factory=list)      # `[Parameter 1]` (in the Parameters datasource)
    groups: list = _field(default_factory=list)          # groups and sets, by name
    bins: list = _field(default_factory=list)            # bins and categorical bins
    action_groups: list = _field(default_factory=list)   # hidden `[Action (...)]` groups (not copied)
    builtin: list = _field(default_factory=list)         # names Tableau makes up (`[:Measure Names]`...), not copied
    unresolved: list = _field(default_factory=list)      # named, but the datasource does not have it
    cross_datasource: list = _field(default_factory=list)  # `[other].[X]` inside a needed calculation

    @property
    def needed(self) -> list:
        return self.fields + self.calcs + self.parameters + self.groups + self.bins


def _sheet_names(ws, ds_name: str) -> tuple[list, list]:
    """Field names (bracketed, instance names reduced to the field) and parameter names the worksheet uses,
    from its cached dependencies and from every `[ds].[x]` it writes anywhere."""
    names: dict = {}
    params: dict = {}
    for dep in ws.iter("datasource-dependencies"):
        target = {ds_name: names, _PARAMETERS: params}.get(dep.get("datasource"))
        if target is None:
            continue
        for col in dep:
            if not isinstance(col.tag, str):
                continue
            if col.tag == "column" and col.get("name"):
                target[_base_of_instance(col.get("name"))] = None
            elif col.tag == "column-instance" and col.get("column"):
                target[_base_of_instance(col.get("column"))] = None
    for text in _tokens_of(ws):
        if "[" not in text:
            continue
        for a, b in _pairs(text):
            if not b:
                continue
            if _unbracket(a) == ds_name:
                names[_base_of_instance(b)] = None
            elif a == "[" + _PARAMETERS + "]":
                params[b] = None
    return list(names), list(params)


def dependency_closure(doc, sheet: str, datasource: Optional[str] = None) -> Closure:
    """The closure of a worksheet taken from its source datasource: every field, calculation, parameter, group,
    set and bin it needs, with the calculations and groups those need in turn (`[Parameters].[X]` inside a
    formula too). `datasource` is needed only when the sheet uses more than one (a blend is refused with
    `SheetCopyError` when it is not named)."""
    ws = _worksheet(doc, sheet)
    used = sheet_datasources(doc, sheet)
    if datasource is None:
        if len(used) > 1:
            raise SheetCopyError(f"{sheet!r} blends {len(used)} datasources ({', '.join(used)}); name the one to follow")
        if not used:
            raise SheetCopyError(f"{sheet!r} uses no datasource")
        datasource = used[0]
    ds = _datasource(doc, datasource)
    fields = _datasource_fields(ds)
    pds = doc.xpath("/workbook/datasources/datasource[@name=$n]", n=_PARAMETERS)
    pcols = {c.get("name"): c for c in pds[0].xpath("./column[@name]")} if pds else {}
    cols = {c.get("name"): c for c in ds.xpath("./column[@name]")}
    groups = {g.get("name"): g for g in ds.xpath("./group[@name]")}

    out = Closure(sheet=sheet, datasource=datasource)
    seen: set = set()
    names, params = _sheet_names(ws, datasource)
    todo = [("n", n) for n in names] + [("p", p) for p in params]
    ordered: dict = {}
    while todo:
        kind, ref = todo.pop(0)
        if (kind, ref) in seen:
            continue
        seen.add((kind, ref))
        if kind == "p":
            if ref in pcols:
                out.parameters.append(ref)
            else:
                out.unresolved.append("[Parameters]." + ref)
            continue
        if _ACTION_GROUP.match(ref):
            out.action_groups.append(ref)
            continue
        if _BUILTIN.match(ref) and ref not in cols and ref not in fields:
            out.builtin.append(ref)
            continue
        if ref in groups:
            out.groups.append(ref)
            for gf in groups[ref].iter("groupfilter"):
                for attr in ("level", "member", "expression"):
                    for r in _refs_of(gf.get(attr)):
                        todo.append(("n", _base_of_instance(r)))
            continue
        col = cols.get(ref)
        calc = col.find("calculation") if col is not None else None
        klass = _calc_class(col) if col is not None else None
        if calc is not None and klass in ("bin", "categorical-bin"):
            out.bins.append(ref)
            base = calc.get("column")
            if base:
                todo.append(("n", _base_of_instance(base)))
            continue
        if calc is not None and klass == "tableau" and not col.get("param-domain-type"):
            ordered[ref] = None
            for k, a, b, _ in _scan(calc.get("formula"), None):
                if k == "param":
                    todo.append(("p", b))
                elif k == "cross":
                    out.cross_datasource.append(f"{a}.{b}")
                elif not a[1:-1].startswith(":"):
                    todo.append(("n", a))
            for tc in calc.iter("table-calc"):
                for k, a, b, _ in _scan(tc.get("ordering-field"), None):
                    todo.append(("n", _base_of_instance(b if k == "cross" else a)))
            continue
        if calc is not None:        # a calculation of another class: keep it visible, do not follow it
            out.unresolved.append(ref)
            continue
        if ref in fields or col is not None:
            out.fields.append(ref)
        else:
            out.unresolved.append(ref)
    out.calcs = _dependency_order(list(ordered), cols)
    out.cross_datasource = list(dict.fromkeys(out.cross_datasource))
    return out


def _refs_of(text: Optional[str]) -> list[str]:
    return [r for _, _, r in _code_ref_spans(text)]


def _dependency_order(names: list, cols: dict) -> list:
    """The calculations with each one after those it uses (ties keep the order they were found in)."""
    deps = {}
    for n in names:
        formula = cols[n].find("calculation").get("formula")
        deps[n] = [a for k, a, b, _ in _scan(formula, None) if k == "local" and a in cols and a != n and a in names]
    out, done = [], set()

    def visit(n, stack=()):
        if n in done or n in stack:
            return
        for d in deps[n]:
            visit(d, stack + (n,))
        done.add(n)
        out.append(n)

    for n in names:
        visit(n)
    return out


# ------------------------------------------------------- comparing with a target --

def _normal(formula: Optional[str]) -> str:
    return (formula or "").replace("\r\n", "\n").strip()


def compare_to_target(src_doc, closure: Closure, dst_doc, target: Optional[str] = None) -> dict:
    """How a closure meets a target datasource (by internal name; `target` defaults to the same name).
    Returns lists of bracketed names: `present` (a physical field the target has), `identical` (a calculation
    or parameter with the same formula or definition), `add` (a calculation, parameter, group or bin the
    target lacks and the field it needs exist), `clash` (the name is taken with another formula), `missing`
    (a physical field, group or bin the target lacks; those cannot be added here) and `blocked` (a calculation
    that needs something in `missing`, `clash` or `blocked`, whether the target has it or not: it would show
    other values there)."""
    target = target or closure.datasource
    src_ds, dst_ds = _datasource(src_doc, closure.datasource), _datasource(dst_doc, target)
    dst_fields = _datasource_fields(dst_ds)
    dst_cols = {c.get("name"): c for c in dst_ds.xpath("./column[@name]")}
    dst_groups = {g.get("name") for g in dst_ds.xpath("./group[@name]")}
    src_cols = {c.get("name"): c for c in src_ds.xpath("./column[@name]")}
    dst_p = dst_doc.xpath("/workbook/datasources/datasource[@name=$n]/column[@name]", n=_PARAMETERS)
    dst_pcols = {c.get("name"): c for c in dst_p}
    src_p = src_doc.xpath("/workbook/datasources/datasource[@name=$n]/column[@name]", n=_PARAMETERS)
    src_pcols = {c.get("name"): c for c in src_p}
    res: dict = {k: [] for k in ("present", "identical", "add", "clash", "missing", "blocked")}

    for n in closure.fields:
        (res["present"] if dst_fields.get(n, {}).get("kind") == "physical" else res["missing"]).append(n)
    for n in closure.groups:
        (res["identical"] if n in dst_groups else res["missing"]).append(n)
    for n in closure.bins:
        dc, sc = dst_cols.get(n), src_cols[n]
        if dc is None:
            res["missing"].append(n)
        elif _calc_sig(dc) == _calc_sig(sc):
            res["identical"].append(n)
        else:
            res["clash"].append(n)
    for n in closure.parameters:
        dc, sc = dst_pcols.get(n), src_pcols.get(n)
        if dc is None:
            res["add"].append("[Parameters]." + n)
        elif sc is not None and _param_sig(dc) == _param_sig(sc):
            res["identical"].append("[Parameters]." + n)
        else:
            res["clash"].append("[Parameters]." + n)
    bad = set(res["missing"]) | set(res["clash"])
    for n in closure.calcs:
        dc, sc = dst_cols.get(n), src_cols[n]
        formula = sc.find("calculation").get("formula")
        uses = {a for k, a, b, _ in _scan(formula, None) if k == "local"}
        uses |= {"[Parameters]." + b for k, a, b, _ in _scan(formula, None) if k == "param"}
        same = (dc is not None and _calc_class(dc) == "tableau"
                and _normal(dc.find("calculation").get("formula")) == _normal(formula))
        if dc is not None and not same:
            res["clash"].append(n)
            bad.add(n)
        elif uses & bad:
            res["blocked"].append(n)
            bad.add(n)
        else:
            res["identical" if same else "add"].append(n)
    return res


def _calc_sig(col) -> tuple:
    calc = col.find("calculation")
    return (col.get("datatype"), tuple(sorted(calc.attrib.items())) if calc is not None else ())


def _param_sig(col) -> tuple:
    calc = col.find("calculation")
    return (col.get("datatype"), col.get("param-domain-type"), col.get("value"),
            calc.get("formula") if calc is not None else None)


# ------------------------------------------------------- connection matching --

def connection_signature(ds) -> tuple:
    """Where a datasource's data lives, as a comparable tuple: for each connection its class, server, database,
    schema, port, warehouse, service and the file's base name (the folder differs between machines), plus the
    names of the tables it reads. Credentials are not part of it."""
    parts = []
    for conn in _connections(ds):
        info = {k: v for k, v in conn.items() if k not in ("authentication",)}
        for k in _FILE_ATTRS:
            if info.get(k):
                info[k] = _base_name(info[k]) if k == "filename" else ""
        parts.append(tuple(sorted((k, v) for k, v in info.items() if v)))
    tables = sorted({t.get("table") or t.get("name") or ""
                     for t in ds.xpath(".//relation[@type='table' or @table]")})
    return (tuple(sorted(parts)), tuple(t for t in tables if t))


def match_datasource(src_doc, source: str, dst_doc, explicit: Optional[str] = None,
                     allow_rename: bool = False) -> str:
    """The internal name of the target datasource a sheet of `source` should use.

    With `explicit`, that datasource must exist. Without it, the target datasources with the same
    `connection_signature` are the candidates; none, or several, is an error. First slice rule: the match must
    have the same internal name as `source` (a different one raises `SheetCopyError` that names it), unless
    `allow_rename` is true. A datasource with no connection (an empty signature) never matches by itself."""
    src = _datasource(src_doc, source)
    dst = {d.get("name"): d for d in _non_parameter_datasources(dst_doc)}
    if explicit is not None:
        if explicit not in dst:
            raise SheetCopyError(f"the target has no datasource {explicit!r}")
        chosen = explicit
    else:
        sig = connection_signature(src)
        if not sig[0]:
            raise SheetCopyError(f"datasource {source!r} has no connection to match by; name the target datasource")
        found = [n for n, d in dst.items() if connection_signature(d) == sig]
        if not found:
            raise SheetCopyError(f"the target has no datasource with the connection of {source!r}")
        if len(found) > 1:
            raise SheetCopyError(f"{len(found)} datasources of the target match the connection of {source!r} "
                                 f"({', '.join(found)}); name one")
        chosen = found[0]
    if chosen != source and not allow_rename:
        raise SheetCopyError(f"the target's matching datasource is named {chosen!r}, not {source!r}; "
                             "only the same internal name is supported in this version")
    return chosen


# ----------------------------------------------------------------- rewriting --

def _map_instance(ref: str, names: dict) -> str:
    """A bracketed name through the map: whole first, then as an instance (`[sum:Sales:qk]`, `[Calc_1:qk]`) with
    its derivation and suffix kept."""
    if ref in names:
        return names[ref]
    inner = ref[1:-1]
    first, last = inner.find(":"), inner.rfind(":")
    if first < 0:
        return ref
    if first == last:
        base, head, tail = inner[:first], "", inner[first:]
        if inner[last + 1:] not in _SUFFIXES:
            return ref
    else:
        head, base, tail = inner[:first + 1], inner[first + 1:last], inner[last:]
    new = names.get(_bracket(_unbracket("[" + base + "]")))
    if new is None:
        return ref
    return "[" + head + new[1:-1] + tail + "]"


def _rewrite_code(text: str, ds_map: dict, names: dict, params: dict, bare: Optional[dict],
                  formula: bool = False) -> str:
    """Rewrite `text`. A pair `[ds].[x]` whose ds is in `ds_map` gets the new ds and `[x]` through `names`; a
    `[Parameters].[X]` pair gets `[X]` through `params`. A lone `[x]` is touched only when `bare` is a map. With
    `formula` true quoted text is skipped, otherwise quotes are ordinary characters."""
    spans = _scan_any(text, formula)
    for kind, a, b, (s, e) in reversed(spans):
        if kind == "param":
            new = _map_instance(b, params) if params else b
            if new != b:
                text = text[:s] + new + text[e:]
        elif kind == "cross":
            ds = _unbracket(a)
            if ds in ds_map:
                text = text[:s] + _bracket(ds_map[ds]) + "." + _map_instance(b, names) + text[e:]
        elif bare is not None:
            new = _map_instance(a, bare)
            if new != a:
                text = text[:s] + new + text[e:]
    return text


def rewrite_references(el, ds_map: Optional[dict] = None, names: Optional[dict] = None,
                       params: Optional[dict] = None, captions: Optional[dict] = None) -> int:
    """Rewrite, in place, everything under `el` (a deep copy of a worksheet, say) that names a datasource or a
    field of it. Returns the number of changes.

    `ds_map` maps an old internal datasource name to the new one (`{"federated.a": "federated.b"}`, plain names
    without brackets); `names` maps a bracketed field name to another (`{"[Parameter 1]": ...}` is for `params`
    instead, the fields of the `Parameters` datasource); `captions` maps an old datasource name to its new
    caption. The map `names` is for the datasources in `ds_map`, and it renames the field inside instance
    names too (`[sum:Sales:qk]` -> `[sum:Revenue:qk]`).

    What is touched: `[old].[x]` pairs in any attribute or text (formulas, `rows`, `cols`, filter `column`,
    encodings, titles' `<[old].[x]>` tokens), `datasource` attributes, the `name` of `datasource` entries, and
    inside a `datasource-dependencies` copy of a mapped datasource the bare names (`name`, `column`, `formula`,
    `ordering-field`); in the `Parameters` copy the same with `params`. Not touched: string literals in formulas,
    attributes such as `caption`, and a pair that names another datasource."""
    ds_map = dict(ds_map or {})
    names = dict(names or {})
    params = dict(params or {})
    captions = dict(captions or {})
    count = 0

    def set_attr(node, key, value):
        nonlocal count
        if node.get(key) != value:
            node.set(key, value)
            count += 1

    deps_of: dict = {}
    for dep in el.iter("datasource-dependencies"):
        which = dep.get("datasource")
        bare = names if which in ds_map else (params if which == _PARAMETERS and params else None)
        for node in dep.iter():
            deps_of[node] = bare
    for node in el.iter():
        if not isinstance(node.tag, str):
            continue
        bare = deps_of.get(node)
        for key, value in list(node.attrib.items()):
            if key == "datasource" and value in ds_map:
                set_attr(node, key, ds_map[value])
            elif key == "name" and node.tag == "datasource" and value in ds_map:
                set_attr(node, key, ds_map[value])
                if value in captions and node.get("caption") is not None:
                    set_attr(node, "caption", captions[value])
            elif "[" in value:
                use_bare = bare if key in _BARE_ATTRS else None
                new = _rewrite_code(value, ds_map, names, params, use_bare, key == "formula")
                if new != value:
                    set_attr(node, key, new)
        if node.text and "[" in node.text:
            new = _rewrite_code(node.text, ds_map, names, params, None)
            if new != node.text:
                node.text = new
                count += 1
        if node.tail and "[" in node.tail and node.tail.strip():
            new = _rewrite_code(node.tail, ds_map, names, params, None)
            if new != node.tail:
                node.tail = new
                count += 1
    return count


def copy_sheet_element(src_doc, sheet: str, new_name: Optional[str], taken: set, ds_map: Optional[dict] = None,
                       names: Optional[dict] = None, params: Optional[dict] = None,
                       captions: Optional[dict] = None):
    """A deep copy of a worksheet, renamed (when `new_name` is given), with every `simple-id` renewed against
    `taken` and its references rewritten (`rewrite_references`). It is not inserted anywhere."""
    ws = copy.deepcopy(_worksheet(src_doc, sheet))
    if new_name:
        ws.set("name", new_name)
    renew_uuids(ws, taken)
    rewrite_references(ws, ds_map, names, params, captions)
    return ws
