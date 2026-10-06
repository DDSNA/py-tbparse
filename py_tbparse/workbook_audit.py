"""`audit`: lint a workbook (basic level of WP10).

Not part of the R package. The rules (A001...) are functions registered with the findings engine
(`findings.py`) in the scope `"workbook"`, next to the template rules (T001...) of
`template_check.py`. Ids are stable and never reused. To add a rule, write one more function with
`@rule("A0xx", SCOPE, ...)` below, add a test with a passing and a failing case and add the id to the
list in `tests/test_audit.py`.

What "used" means (A001, A005): `usage.field_usage`'s own meaning, a field is used when a worksheet
shows or filters it, directly or through the calculations, groups, sets, bins and parameters that
worksheet's fields depend on. On top of that a name that a dashboard, an action or a worksheet's text
(a title or caption that shows a parameter) mentions as `[Name]` counts as used. Not followed: a field
that only another datasource's blend, a story point caption or an external tool uses. A rule says
"probably", never "safe to delete"; nothing here removes anything (there is no `prune`).

Every rule is a heuristic about what a workbook author probably did not mean; none says Tableau will
refuse the file, and nothing here was checked by opening a workbook in Tableau.
"""

from __future__ import annotations

import re
from typing import Iterable, Iterator, Optional

import pandas as pd
from lxml import etree

from .findings import Subject, finding, rule, rule_ids, rules, run_rules
from .parser import TwbParser
from .templates import _FILE_CLASSES, _KEYED_SECRET, _USERINFO, _base_name
from .usage import _code_refs, _dashboards_of, field_usage, missing_references

SCOPE = "workbook"

LONG_FORMULA = 1000
DEEP_CALCULATION = 5
SQL_SHOWN = 80
_MAX_NAMES = 6

_DEFAULT_INTERNAL = re.compile(r"^\[Calculation_\d+\]$")
_DEFAULT_CAPTION = re.compile(r"^Calculation\s?\d*$")


def audit_rule_ids() -> list[str]:
    return rule_ids(SCOPE)


def audit(source, only: Optional[Iterable[str]] = None, skip: Iterable[str] = ()) -> pd.DataFrame:
    """Audit a workbook (a path or a `TwbParser`); return the findings (`findings.FINDING_COLUMNS`), sorted so the
    same workbook always gives the same frame. `only`/`skip` take rule ids; an unknown id is an error. Nothing is
    written."""
    parser = source if isinstance(source, TwbParser) else TwbParser(str(source))
    path = None if isinstance(source, TwbParser) else str(source)
    return run_rules(Subject(parser=parser, path=path or getattr(parser, "path", None)), SCOPE, only=only, skip=skip)


def rules_help() -> str:
    """One line per rule for the CLI help."""
    return "\n".join(f"  {r.id}  {r.severity:<8} {r.title}" for r in rules(SCOPE))


# ------------------------------------------------------------------ shared facts --

class _Calc:
    __slots__ = ("ds", "ds_label", "name", "caption", "formula", "hidden")

    def __init__(self, ds, ds_label, name, caption, formula, hidden):
        self.ds, self.ds_label, self.name, self.caption, self.formula, self.hidden = \
            ds, ds_label, name, caption, formula, hidden

    @property
    def key(self) -> tuple:
        return (self.ds, self.name)

    @property
    def label(self) -> str:
        return f"{self.ds_label}: {self.caption or self.name.strip('[]')}"


def _ds_label(ds) -> str:
    return ds.get("caption") or ds.get("name") or ""


class _Facts:
    """What the rules share, computed once per run."""

    def __init__(self, parser: TwbParser):
        self.doc = parser.xml_doc
        self.parser = parser
        self.calcs: list[_Calc] = []
        for ds in self.doc.xpath("/workbook/datasources/datasource[@name]"):
            for col in ds.xpath("./column[@name][calculation[@formula]]"):
                if col.get("param-domain-type"):
                    continue                      # a parameter's formula is its current value
                self.calcs.append(_Calc(ds.get("name"), _ds_label(ds), col.get("name"), col.get("caption"),
                                        col.find("calculation").get("formula") or "", col.get("hidden") == "true"))
        self.calcs.sort(key=lambda c: (c.ds_label, c.ds, c.name))
        self.by_key = {c.key: c for c in self.calcs}
        self.ds_names = set(self.doc.xpath("/workbook/datasources/datasource/@name"))
        self._graph: Optional[dict] = None
        self._usage: Optional[pd.DataFrame] = None
        self._mentioned: Optional[set] = None

    @property
    def usage(self) -> pd.DataFrame:
        if self._usage is None:
            usage = field_usage(self.doc)
            usage = usage.astype(object).where(usage.notna(), None)    # a missing caption is None, not NaN
            usage["used"] = usage["used"].astype(bool)
            self._usage = usage
        return self._usage

    @property
    def mentioned(self) -> set:
        """Names written as `[Name]` (or inside `[ds].[none:Name:nk]`) in dashboards, actions and worksheets."""
        if self._mentioned is None:
            text = []
            for xp in ("/workbook/actions", "/workbook/dashboards", "/workbook/worksheets"):
                for el in self.doc.xpath(xp):
                    text.append(etree.tostring(el, encoding="unicode"))
            blob = "\n".join(text)
            self._mentioned = set(re.findall(r"(?<=[\[:])[^\[\]:]+(?=[\]:])", blob))
        return self._mentioned

    @property
    def graph(self) -> dict:
        """(datasource, name) of every calculation -> the calculations its formula refers to."""
        if self._graph is None:
            self._graph = {c.key: self._calc_deps(c) for c in self.calcs}
        return self._graph

    def _targets(self, calc: _Calc) -> list[tuple]:
        """(datasource, `[Name]`) of every field the formula refers to, parameters and other datasources included."""
        refs = _code_refs(calc.formula)
        out = []
        i = 0
        while i < len(refs):
            inner = refs[i][1:-1]
            if (inner == "Parameters" or inner in self.ds_names) and i + 1 < len(refs):
                dep = (inner, refs[i + 1])
                i += 2
            else:
                dep = (calc.ds, refs[i])
                i += 1
            if dep not in out:
                out.append(dep)
        return out

    def _calc_deps(self, calc: _Calc) -> list[tuple]:
        return sorted(d for d in self._targets(calc) if d in self.by_key)

    @property
    def parameter_users(self) -> dict[str, list[_Calc]]:
        """`[Parameter 1]` -> the calculations whose formula refers to it. `field_usage` does not follow a
        parameter through a formula (it reads the references from a set, so `[Parameters]` and the name after it
        lose their order), so the parameter rule asks here."""
        users: dict[str, list[_Calc]] = {}
        for c in self.calcs:
            for ds, name in self._targets(c):
                if ds == "Parameters":
                    users.setdefault(name, []).append(c)
        return users


def _facts(s: Subject) -> _Facts:
    facts = getattr(s, "_audit_facts", None)
    if facts is None:
        facts = _Facts(s.parser)
        s._audit_facts = facts
    return facts


def _names(values: list[str]) -> str:
    shown = ", ".join(values[:_MAX_NAMES])
    return shown + (f" and {len(values) - _MAX_NAMES} more" if len(values) > _MAX_NAMES else "")


def _label_of(row) -> str:
    return row["caption"] or str(row["field"]).strip("[]")


# ------------------------------------------------------------------ formulas --

def normalise_formula(formula: str) -> str:
    """A formula without what does not change its meaning: comments (`//` to the end of the line and
    `/* ... */`) removed, runs of whitespace collapsed and dropped around punctuation, and the text outside
    string literals and `[bracketed names]` lower-cased (keywords are case-insensitive). String literals and
    names are kept as written. Two calculations with the same result here are the same calculation written
    twice."""
    parts: list[tuple[bool, str]] = []        # (is code, text)
    code: list[str] = []

    def flush():
        if code:
            parts.append((True, "".join(code)))
            code.clear()

    text, i = formula or "", 0
    while i < len(text):
        c = text[i]
        if c in "\"'" or c == "[":
            close = "]" if c == "[" else c
            j = i + 1
            while j < len(text):
                if c != "[" and text[j] == "\\":
                    j += 2
                    continue
                if text[j] == close:
                    if text[j + 1:j + 2] == close:
                        j += 2
                        continue
                    break
                j += 1
            flush()
            parts.append((False, text[i:j + 1]))
            i = j + 1
        elif text.startswith("//", i):
            j = text.find("\n", i)
            i = len(text) if j < 0 else j
        elif text.startswith("/*", i):
            j = text.find("*/", i + 2)
            i = len(text) if j < 0 else j + 2
            code.append(" ")
        else:
            code.append(c.lower())
            i += 1
    flush()
    out = []
    for n, (is_code, piece) in enumerate(parts):
        if is_code:
            piece = re.sub(r"\s+", " ", piece)
            piece = re.sub(r" ?([^\w\s]) ?", r"\1", piece)
            if n and not parts[n - 1][0]:
                piece = piece.lstrip(" ")
            if n + 1 < len(parts) and not parts[n + 1][0]:
                piece = piece.rstrip(" ")
        out.append(piece)
    return "".join(out).strip()


# ------------------------------------------------------------------ the rules --

@rule("A001", SCOPE, severity="info",
      fix="If nothing needs it, delete the calculation or hide it; check first that no other workbook or "
          "published datasource uses it, py-tbparse only sees this workbook")
def unused_calculation(s: Subject):
    """A calculated field that no worksheet uses, not even through another calculation."""
    f = _facts(s)
    for _, row in f.usage[(f.usage["kind"] == "calculated") & ~f.usage["used"]].iterrows():
        calc = f.by_key.get((row["datasource"], row["field"]))
        if calc is None or calc.hidden or row["field"].strip("[]") in f.mentioned:
            continue
        by = [c for c in row["calculations"] if c != _label_of(row)]
        yield finding(calc.label,
                      f"no worksheet uses it; only the calculation(s) {_names(by)} refer to it, and no worksheet uses those"
                      if by else "no worksheet, dashboard or other calculation uses it")


@rule("A002", SCOPE, severity="warning",
      fix="Keep one of the calculations and point the worksheets at it, or give the copies different formulas "
          "if they were meant to differ")
def duplicate_calculation(s: Subject):
    """Two calculations of one datasource have the same formula (comments, spacing and keyword case aside)."""
    f = _facts(s)
    groups: dict[tuple, list[_Calc]] = {}
    for c in f.calcs:
        if not _code_refs(c.formula):
            continue                              # `1`, `"x"`: a constant is written twice on purpose
        groups.setdefault((c.ds, normalise_formula(c.formula)), []).append(c)
    for calcs in groups.values():
        if len(calcs) < 2:
            continue
        names = [c.caption or c.name.strip("[]") for c in calcs]
        for i, c in enumerate(calcs):
            yield finding(c.label, f"same formula as {_names(names[:i] + names[i + 1:])}")


@rule("A003", SCOPE, severity="error",
      fix="Point the formula at a field that exists, or restore the field; Tableau shows the calculation as "
          "invalid until then")
def missing_reference(s: Subject):
    """A calculation refers to a field the workbook does not have."""
    f = _facts(s)
    for _, row in missing_references(f.doc).iterrows():
        calc = f.by_key.get((row["datasource"], row["calculation"]))
        label = calc.label if calc else f"{row['datasource']}: {row['caption'] or row['calculation']}"
        yield finding(label, f"refers to {row['missing']}, which does not exist")


def _cycles(graph: dict) -> list[list[tuple]]:
    """Strongly connected components with a cycle (Tarjan, iterative), each sorted, in a stable order."""
    index: dict = {}
    low: dict = {}
    on: set = set()
    stack: list = []
    found: list[list[tuple]] = []
    counter = 0
    for root in sorted(graph):
        if root in index:
            continue
        work = [(root, iter(graph.get(root, ())))]
        index[root] = low[root] = counter
        counter += 1
        stack.append(root)
        on.add(root)
        while work:
            node, it = work[-1]
            advanced = False
            for nxt in it:
                if nxt not in index:
                    index[nxt] = low[nxt] = counter
                    counter += 1
                    stack.append(nxt)
                    on.add(nxt)
                    work.append((nxt, iter(graph.get(nxt, ()))))
                    advanced = True
                    break
                if nxt in on:
                    low[node] = min(low[node], index[nxt])
            if advanced:
                continue
            work.pop()
            if work:
                low[work[-1][0]] = min(low[work[-1][0]], low[node])
            if low[node] == index[node]:
                comp = []
                while True:
                    top = stack.pop()
                    on.discard(top)
                    comp.append(top)
                    if top == node:
                        break
                if len(comp) > 1 or node in graph.get(node, ()):
                    found.append(sorted(comp))
    return sorted(found)


@rule("A004", SCOPE, severity="error",
      fix="Break the loop: one of the calculations must stop referring to the next; Tableau refuses a circular "
          "calculation")
def circular_calculation(s: Subject):
    """Calculations that refer to each other in a circle (or to themselves)."""
    f = _facts(s)
    for comp in _cycles(f.graph):
        names = [f.by_key[k].caption or f.by_key[k].name.strip("[]") for k in comp]
        for key in comp:
            yield finding(f.by_key[key].label,
                          "refers to itself" if len(comp) == 1 else f"part of a circular dependency: {_names(names)}")


@rule("A005", SCOPE, severity="info",
      fix="If nothing needs the parameter, delete it; check first that no title, action or other workbook does "
          "(this rule follows a parameter through calculations, which `field_usage` itself does not yet)")
def unused_parameter(s: Subject):
    """A parameter that no worksheet, calculation or text uses."""
    f = _facts(s)
    users = f.parameter_users
    used_calcs = {(r["datasource"], r["field"]) for _, r in f.usage.iterrows()
                  if r["kind"] == "calculated" and (r["used"] or r["field"].strip("[]") in f.mentioned)}
    for _, row in f.usage[(f.usage["kind"] == "parameter") & ~f.usage["used"]].iterrows():
        if row["field"].strip("[]") in f.mentioned:
            continue
        refs = users.get(row["field"], [])
        if any(c.key in used_calcs for c in refs):
            continue
        names = sorted({c.caption or c.name.strip("[]") for c in refs})
        yield finding(f"Parameters: {_label_of(row)}",
                      f"no worksheet uses it; only the calculation(s) {_names(names)} refer to it, and no worksheet uses those"
                      if names else "no worksheet, dashboard, action or calculation uses it")


def _hidden_sheets(doc) -> set:
    return set(doc.xpath("/workbook/windows/window[@class='worksheet'][@hidden='true']/@name"))


@rule("A006", SCOPE, severity="info",
      fix="Add the worksheet to a dashboard or story, hide it if it only feeds another sheet, or delete it")
def sheet_in_no_dashboard(s: Subject):
    """A worksheet that is on no dashboard and not hidden."""
    doc = _facts(s).doc
    shown = set(_dashboards_of(doc))
    shown |= set(doc.xpath("//story-point/@captured-sheet"))
    hidden = _hidden_sheets(doc)
    for name in sorted(doc.xpath("/workbook/worksheets/worksheet/@name")):
        if name not in shown and name not in hidden:
            yield finding(name, "not on any dashboard or story, and not hidden")


def _sql_snippet(text: str) -> str:
    flat = " ".join(text.split())
    flat = _KEYED_SECRET.sub(lambda m: m.group(1) + "=***", _USERINFO.sub("***@", flat))
    return flat if len(flat) <= SQL_SHOWN else flat[:SQL_SHOWN] + "..."


@rule("A007", SCOPE, severity="info",
      fix="Custom SQL runs as written on every refresh and Tableau cannot optimise around it; a view or a table in "
          "the database is often easier to maintain. Check it for credentials and for hard-coded dates")
def custom_sql(s: Subject):
    """Custom SQL is present (the first 80 characters are shown)."""
    doc = _facts(s).doc
    seen = set()
    for rel in doc.xpath("//relation[@type='text' or @formula]"):
        text = rel.get("formula") if rel.get("formula") is not None else "".join(rel.itertext())
        text = (text or "").strip()
        if not text or (rel.get("type") != "text" and not re.match(r"(?i)^\s*(select|with)\b", text)):
            continue
        ds = next(iter(rel.xpath("ancestor::datasource[1]")), None)
        label = _ds_label(ds) if ds is not None else ""
        name = rel.get("name") or "Custom SQL"
        key = (label, name, text)
        if key in seen:
            continue
        seen.add(key)
        yield finding(f"{label}: {name}", _sql_snippet(text))


def _absolute(path: str) -> bool:
    return path.startswith(("/", "\\\\", "~")) or bool(re.match(r"[A-Za-z]:[\\/]", path))


@rule("A008", SCOPE, severity="info",
      fix="Remove the extract (or refresh and republish it) and point file connections at a folder next to the "
          "workbook or at a shared location; `template make` strips extracts for you")
def extract_or_path_leftover(s: Subject):
    """A datasource keeps an extract, or a file connection with an absolute local path."""
    doc = _facts(s).doc
    for ds in doc.xpath("/workbook/datasources/datasource[@name]"):
        label = _ds_label(ds)
        if any(isinstance(el.tag, str) and etree.QName(el).localname == "extract" for el in ds):
            yield finding(label, "keeps an extract (a copy of the data, which can show data the workbook was shared without)")
        seen = set()
        for conn in ds.xpath(".//connection[@class][not(ancestor::*[local-name()='extract'])]"):
            if conn.get("class") not in _FILE_CLASSES:
                continue
            for attr in ("filename", "directory", "dbname"):
                value = conn.get(attr)
                if value and _absolute(value) and (attr, value) not in seen:
                    seen.add((attr, value))
                    shown = _base_name(value) if attr == "filename" else "a local folder, not shown"
                    yield finding(label, f"a {conn.get('class')} connection has an absolute {attr} ({shown})")


@rule("A009", SCOPE, severity="info",
      fix="Give the calculation a name that says what it does; the formulas and worksheets keep working (the "
          "caption is display text)")
def default_name(s: Subject):
    """A calculation still has Tableau's default name (`Calculation1`, `Calculation_123...`)."""
    for c in _facts(s).calcs:
        if (c.caption is None and _DEFAULT_INTERNAL.match(c.name)) or (c.caption and _DEFAULT_CAPTION.match(c.caption)):
            yield finding(c.label, "has the default name")


def calculation_depths(f: _Facts) -> dict[tuple, int]:
    """Longest chain of calculations below each calculation, itself included (a calculation of fields only is 1).
    A reference back into the circle a calculation belongs to (A004) is not followed, so the count stays finite."""
    circle: dict = {}
    for n, comp in enumerate(_cycles(f.graph)):
        for key in comp:
            circle[key] = n
    depth: dict = {}
    for root in sorted(f.graph):
        stack = [(root, False)]
        while stack:
            key, done = stack.pop()
            deps = [d for d in f.graph.get(key, ()) if not (key in circle and circle.get(d) == circle[key])]
            if done:
                depth[key] = 1 + max((depth[d] for d in deps), default=0)
            elif key not in depth:
                stack.append((key, True))
                stack.extend((d, False) for d in deps if d not in depth)
    return depth


@rule("A010", SCOPE, severity="info",
      fix="Fold the inner calculations together or compute the intermediate result once in the data; long chains "
          "are hard to read and slow to change")
def deep_calculation(s: Subject):
    """A calculation sits on a chain of more than 5 calculations."""
    f = _facts(s)
    for key, d in sorted(calculation_depths(f).items()):
        if d > DEEP_CALCULATION:
            yield finding(f.by_key[key].label, f"depends on a chain of {d} calculations (more than {DEEP_CALCULATION})")


@rule("A011", SCOPE, severity="info",
      fix="Split the formula into smaller calculations with names, or move the logic into the data")
def long_formula(s: Subject):
    """A formula is longer than 1000 characters."""
    for c in _facts(s).calcs:
        n = len(c.formula.strip())
        if n > LONG_FORMULA:
            yield finding(c.label, f"the formula has {n} characters (more than {LONG_FORMULA})")
