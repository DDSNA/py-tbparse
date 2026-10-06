"""CI output formats for the findings engine: JUnit XML, SARIF 2.1.0 and GitHub workflow commands.

Not part of the R package. Every command that produces findings (`validate`, `template check`,
`audit`) renders through `render()` here, so the three formats look the same everywhere. Each
formatter takes the findings frame (`findings.FINDING_COLUMNS`) plus the file the findings are
about (`path`, written as given, with forward slashes, so a relative path stays relative to the
repository) and the `scope` whose rule catalog fills the SARIF `rules` array.

Mapping of severities:

- JUnit: one `<testcase>` per finding (`classname` = rule id). `error` is a `<failure>`; `warning`
  and `info` are `<skipped>` with the text in `message`, so a test report shows them without
  failing. A rule that crashed (`df.attrs["crashed"]`) is an `<error>`. No findings gives one
  passing test case, so the suite is never empty.
- SARIF: `error` -> `error`, `warning` -> `warning`, `info` -> `note`. The location is the file.
- GitHub: `::error`, `::warning`, `::notice` (for `info`) with `file=` and `title=` (the rule id).

The exit code is not decided here: it stays the one of the command (0, 1, 2, 3).
"""

from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from typing import Callable, Optional

import pandas as pd

CI_FORMATS = ("junit", "sarif", "github")

SARIF_SCHEMA = "https://json.schemastore.org/sarif-2.1.0.json"
INFORMATION_URI = "https://github.com/DDSNA/py-tbparse"
_LEVEL = {"error": "error", "warning": "warning", "info": "note"}

# characters XML 1.0 cannot hold (everything below space but tab, LF, CR; lone surrogates; FFFE/FFFF)
_XML_ILLEGAL = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f\ud800-\udfff\ufffe\uffff]")


def _tool_version() -> str:
    from . import __version__
    return __version__


def _uri(path: Optional[str]) -> str:
    """The file as a relative-friendly URI reference: forward slashes, no `..`-resolving, spaces and
    other unsafe characters percent-encoded (a Windows drive letter stays as `C:/...`)."""
    from urllib.parse import quote
    text = str(path or "").replace("\\", "/")
    return quote(text, safe="/:@!$&'()*+,;=-._~") if text else "unknown"


def _text(value) -> str:
    return "" if value is None or (isinstance(value, float) and pd.isna(value)) else str(value)


def _message(row) -> str:
    obj, detail, fix = _text(row["object"]), _text(row["detail"]), _text(row["fix"])
    out = f"{obj}: {detail}" if obj else detail
    return f"{out} (fix: {fix})" if fix else out


def catalog(scope: Optional[str]) -> list[dict]:
    """The rules of a scope as `{id, title, severity, fix}`, by id. `validate` has two fixed rules;
    `template` and `workbook` come from the findings registry (the rule modules are imported on demand)."""
    if scope == "validate":
        from .validators import VALIDATE_RULES
        return [dict(r) for r in VALIDATE_RULES]
    if scope == "template":
        from . import template_check  # noqa: F401 -- registers the rules
    elif scope == "workbook":
        from . import workbook_audit  # noqa: F401
    from .findings import rules
    try:
        return [{"id": r.id, "title": r.title, "severity": r.severity, "fix": r.fix} for r in rules(scope or "")]
    except Exception:  # noqa: BLE001 -- an unknown scope just has no catalog
        return []


# ---------------------------------------------------------------- JUnit --

def _clean(text: str) -> str:
    return _XML_ILLEGAL.sub("\ufffd", text)


def junit(df: pd.DataFrame, path: Optional[str] = None, scope: Optional[str] = None) -> str:
    """JUnit XML (`<testsuites><testsuite><testcase>`), well-formed for the standard library and CI test reporters."""
    crashed = set(df.attrs.get("crashed") or [])
    suite_name = "py-tbparse " + {"validate": "validate", "template": "template check", "workbook": "audit"}.get(scope or "", "findings")
    cases = []
    failures = errors = skipped = 0
    for _, row in df.iterrows():
        rule_id, severity = _text(row["rule"]), _text(row["severity"])
        msg = _clean(_message(row))
        case = ET.Element("testcase", {"classname": rule_id, "name": _clean(_text(row["object"]) or rule_id),
                                       "file": _clean(_uri(path))})
        if rule_id in crashed and severity == "error":
            ET.SubElement(case, "error", {"type": rule_id, "message": msg}).text = msg
            errors += 1
        elif severity == "error":
            ET.SubElement(case, "failure", {"type": rule_id, "message": msg}).text = msg
            failures += 1
        else:
            ET.SubElement(case, "skipped", {"message": f"{severity}: {msg}"})
            skipped += 1
        cases.append(case)
    if not cases:
        cases.append(ET.Element("testcase", {"classname": "py-tbparse", "name": "no findings", "file": _clean(_uri(path))}))
    suite = ET.Element("testsuite", {"name": suite_name, "tests": str(len(cases)), "failures": str(failures),
                                     "errors": str(errors), "skipped": str(skipped)})
    props = ET.SubElement(suite, "properties")
    ET.SubElement(props, "property", {"name": "file", "value": _clean(_uri(path))})
    ET.SubElement(props, "property", {"name": "py-tbparse", "value": _tool_version()})
    suite.extend(cases)
    root = ET.Element("testsuites", {"name": "py-tbparse", "tests": suite.get("tests"), "failures": str(failures),
                                     "errors": str(errors)})
    root.append(suite)
    ET.indent(root)
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(root, encoding="unicode") + "\n"


# ---------------------------------------------------------------- SARIF --

def sarif(df: pd.DataFrame, path: Optional[str] = None, scope: Optional[str] = None) -> str:
    """A SARIF 2.1.0 log: one run, `tool.driver.rules` from the stable rule ids, one result per finding with its level
    and the workbook (or template) file as the location."""
    rules = [{"id": r["id"], "name": r["id"], "shortDescription": {"text": r["title"] or r["id"]},
              "defaultConfiguration": {"level": _LEVEL[r["severity"]]},
              **({"help": {"text": r["fix"]}} if r.get("fix") else {})} for r in catalog(scope)]
    index = {r["id"]: i for i, r in enumerate(rules)}
    for rule_id in dict.fromkeys(df["rule"]) if len(df) else ():       # a rule the catalog does not know
        if rule_id not in index:
            index[rule_id] = len(rules)
            rules.append({"id": rule_id, "name": rule_id, "shortDescription": {"text": rule_id}})
    uri = _uri(path)
    results = []
    for _, row in df.iterrows():
        rule_id = _text(row["rule"])
        props = {k: _text(row[k]) for k in ("object", "fix") if _text(row[k])}
        result = {"ruleId": rule_id, "ruleIndex": index[rule_id], "level": _LEVEL.get(_text(row["severity"]), "warning"),
                  "message": {"text": _message(row)},
                  "locations": [{"physicalLocation": {"artifactLocation": {"uri": uri},
                                                      "region": {"startLine": 1}}}]}
        if props:
            result["properties"] = props
        results.append(result)
    log = {"$schema": SARIF_SCHEMA, "version": "2.1.0",
           "runs": [{"tool": {"driver": {"name": "py-tbparse", "version": _tool_version(),
                                         "informationUri": INFORMATION_URI, "rules": rules}},
                     "artifacts": [{"location": {"uri": uri}}],
                     "results": results}]}
    return json.dumps(log, indent=2, ensure_ascii=False) + "\n"


# --------------------------------------------------------------- GitHub --

def _escape_data(text: str) -> str:
    return text.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def _escape_property(text: str) -> str:
    return _escape_data(text).replace(":", "%3A").replace(",", "%2C")


def github(df: pd.DataFrame, path: Optional[str] = None, scope: Optional[str] = None) -> str:
    """GitHub Actions workflow commands, one line per finding (`::error file=..,title=RULE::message`). Data and
    property values are escaped the way the runner expects (`%`, CR, LF; properties also `:` and `,`)."""
    file = _escape_property(str(path or "").replace("\\", "/"))
    kind = {"error": "error", "warning": "warning", "info": "notice"}
    lines = []
    for _, row in df.iterrows():
        props = ([f"file={file}"] if file else []) + [f"title={_escape_property(_text(row['rule']))}"]
        lines.append(f"::{kind.get(_text(row['severity']), 'warning')} {','.join(props)}::{_escape_data(_message(row))}")
    return "\n".join(lines)


FORMATTERS: dict[str, Callable[..., str]] = {"junit": junit, "sarif": sarif, "github": github}


def render(df: pd.DataFrame, fmt: str, path: Optional[str] = None, scope: Optional[str] = None) -> str:
    """Render a findings frame in a CI format. `path` is the file the findings are about; `scope` (default: the
    frame's own `attrs["scope"]`) picks the rule catalog."""
    formatter = FORMATTERS.get(fmt)
    if formatter is None:
        raise ValueError(f"unknown CI format {fmt!r}; use {', '.join(CI_FORMATS)}")
    return formatter(df, path if path is not None else df.attrs.get("path"), scope or df.attrs.get("scope"))
