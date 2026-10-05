"""A small findings engine: rules that look at something and report rows.

Not part of the R package. `template check` (`template_check.py`) is the first user; the
workbook audit (WP10) reuses it with another scope, and a rule for template tokens (WP19) is one
more function in `template_check.py`, nothing here changes.

A rule is a function registered with `@rule(id, scope, severity=..., fix=...)`. It receives a
`Subject` (what is being looked at: a parser, a template, or both) and yields `finding(...)`
rows. `run_rules` runs every rule of a scope and returns one deterministic frame
(`FINDING_COLUMNS`). Rule ids are stable: people put them in CI configs and suppression lists,
so an id is never renumbered or reused, and a retired rule keeps its number.

A rule that raises does not stop the run: the exception becomes one `error` finding for that
rule, so one odd file cannot hide the findings of every other rule (or of every other file in a
batch run). The frame says so in `df.attrs["crashed"]` (the rule ids) and keeps each traceback in
`df.attrs["tracebacks"]`, so a caller can tell "a rule failed" from "the rule found a real error"
(`template check` exits 3). The finding's text never holds a local path: the home directory and the
subject's own path and folder are replaced by `<path>`.

`format_findings` renders a frame through the `FORMATS` registry (`table`, `csv`, `json`); the
CI formats planned for WP18 (JUnit, SARIF, GitHub annotations) are further entries there, each a
function from the frame to text.
"""

from __future__ import annotations

import os
import traceback
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Optional

import pandas as pd

FINDING_COLUMNS = ["rule", "severity", "object", "detail", "fix"]
SEVERITY = {"error": 0, "warning": 1, "info": 2}   # same order as templates._SEVERITY


@dataclass
class Subject:
    """What the rules look at. `parser` is a TwbParser, `template` a `templates.Template`; a
    scope uses the one it needs (a template's `parser` is the workbook inside it)."""
    parser: Any = None
    template: Any = None
    path: Optional[str] = None


@dataclass
class _Rule:
    id: str
    scope: str
    severity: str
    fix: str
    func: Callable
    title: str


_RULES: dict[str, _Rule] = {}


def _check_severity(severity: str) -> str:
    if severity not in SEVERITY:
        raise ValueError(f"severity must be one of {', '.join(SEVERITY)}, got {severity!r}")
    return severity


def rule(rule_id: str, scope: str, severity: str = "info", fix: str = "") -> Callable:
    """Register a rule function. `severity` and `fix` are the defaults of its findings; the
    first line of the docstring is the rule's one-line title."""
    _check_severity(severity)

    def register(func: Callable) -> Callable:
        old = _RULES.get(rule_id)
        if old is not None and (old.func.__module__, old.func.__qualname__) != (func.__module__, func.__qualname__):
            raise ValueError(f"rule {rule_id} is already registered ({old.func.__name__})")
        # the same function registered again (`importlib.reload` of its module) replaces itself
        title = (func.__doc__ or "").strip().splitlines()[0] if func.__doc__ else ""
        _RULES[rule_id] = _Rule(rule_id, scope, severity, fix, func, title)
        return func

    return register


def finding(obj: str, detail: str, severity: Optional[str] = None, fix: Optional[str] = None) -> dict:
    """One finding as a rule yields it: the rule id and the defaults are filled in by the engine."""
    if severity is not None:
        _check_severity(severity)
    return {"object": obj, "detail": detail, "severity": severity, "fix": fix}


def rule_ids(scope: str) -> list[str]:
    return sorted(r.id for r in _RULES.values() if r.scope == scope)


def rules(scope: str) -> list[_Rule]:
    """The registered rules of a scope, by id (for `--list` style help and docs)."""
    return [_RULES[i] for i in rule_ids(scope)]


def _selected(scope: str, ids: Optional[Iterable[str]], what: str) -> Optional[set]:
    if ids is None:
        return None
    if isinstance(ids, str):          # one id as text, not its characters
        ids = [ids]
    known = rule_ids(scope)
    chosen = {i.strip().upper() for i in ids if i and i.strip()}
    unknown = sorted(chosen - set(known))
    if unknown:
        raise ValueError(f"{what}: unknown rule {', '.join(unknown)}; known: {', '.join(known)}")
    return chosen


def _scrub(text: str, subject: "Subject") -> str:
    """`text` without the local paths it may carry: the subject's file and folder and the home directory."""
    paths = {os.path.expanduser("~")}
    if subject.path:
        raw = str(subject.path)
        paths |= {raw, os.path.abspath(raw), os.path.dirname(raw), os.path.dirname(os.path.abspath(raw))}
    for p in sorted((p for p in paths if p and len(p) > 1), key=len, reverse=True):
        text = text.replace(p, "<path>")
    return text


def run_rules(subject: Subject, scope: str, only: Optional[Iterable[str]] = None,
              skip: Iterable[str] = ()) -> pd.DataFrame:
    """Run the rules of `scope` on `subject`; return the findings, sorted by rule id, severity,
    object and detail (so the same input always gives the same frame). `only` keeps just those
    rule ids, `skip` drops them; an id that is not a rule of the scope is an error."""
    if not rule_ids(scope):
        raise ValueError(f"no rules for scope {scope!r}")
    keep = _selected(scope, only, "only")
    if keep is not None and not keep:
        raise ValueError("only: no rule ids given (an empty list would run nothing; leave it out to run every rule)")
    drop = _selected(scope, skip, "skip") or set()
    chosen = [r for r in rules(scope) if (keep is None or r.id in keep) and r.id not in drop]
    if not chosen:
        raise ValueError("only and skip leave no rule to run")
    rows = []
    crashed: list[str] = []
    tracebacks: dict[str, str] = {}
    for r in chosen:
        try:
            for f in r.func(subject):
                rows.append({"rule": r.id, "severity": f["severity"] or r.severity,
                             "object": f["object"], "detail": f["detail"],
                             "fix": r.fix if f["fix"] is None else f["fix"]})
        except Exception as e:     # noqa: BLE001 -- see the module docstring
            crashed.append(r.id)
            tracebacks[r.id] = traceback.format_exc()
            rows.append({"rule": r.id, "severity": "error", "object": "",
                         "detail": _scrub(f"rule failed: {type(e).__name__}: {e}", subject),
                         "fix": "report this as a bug"})
    df = pd.DataFrame(rows, columns=FINDING_COLUMNS)
    if not df.empty:
        df["_s"] = df["severity"].map(SEVERITY)
        df = df.sort_values(["rule", "_s", "object", "detail"], kind="stable").drop(columns="_s")
        df = df.reset_index(drop=True)
    df.attrs["crashed"] = crashed
    df.attrs["tracebacks"] = tracebacks
    return df


def exceeds(df: pd.DataFrame, fail_on: str) -> bool:
    """True when a finding is at `fail_on` severity or worse (`never` is always False)."""
    if fail_on == "never":
        return False
    limit = SEVERITY[_check_severity(fail_on)]
    return bool((df["severity"].map(SEVERITY) <= limit).any()) if len(df) else False


def summary(df: pd.DataFrame) -> str:
    """`1 error, 2 warnings, 1 info`, or `no findings`."""
    if df.empty:
        return "no findings"
    counts = df["severity"].value_counts()
    parts = []
    for sev, plural in (("error", "errors"), ("warning", "warnings"), ("info", "info")):
        n = int(counts.get(sev, 0))
        if n:
            parts.append(f"{n} {sev if n == 1 or sev == 'info' else plural}")
    return ", ".join(parts)


def _table(df: pd.DataFrame) -> str:
    if df.empty:
        return "(no findings)"
    with pd.option_context("display.max_rows", None, "display.max_columns", None,
                           "display.width", 250, "display.max_colwidth", 200):
        return df.to_string(index=False)


def _csv(df: pd.DataFrame) -> str:
    """CSV with a leading `'` on a text cell a spreadsheet would run as a formula (`=`, `+`, `-`, `@`, tab, CR);
    the frame is not changed."""
    safe = df.copy()
    for col in safe.columns:
        safe[col] = safe[col].map(lambda v: "'" + v if isinstance(v, str) and v[:1] in ("=", "+", "-", "@", "\t", "\r") else v)
    return safe.to_csv(index=False)


FORMATS: dict[str, Callable[[pd.DataFrame], str]] = {
    "table": _table,
    "csv": _csv,
    "json": lambda df: df.to_json(orient="records", indent=2, force_ascii=False),
}


def format_findings(df: pd.DataFrame, fmt: str = "table") -> str:
    formatter = FORMATS.get(fmt)
    if formatter is None:
        raise ValueError(f"unknown format {fmt!r}; use {', '.join(FORMATS)}")
    return formatter(df)
