"""`template check`: lint a template before it is shared.

Not part of the R package. The rules (T001...) are functions registered with the findings engine
(`findings.py`) in the scope `"template"`. Ids are stable and never reused; a rule that is retired
keeps its number. To add a rule, write one more function with `@rule("T0xx", "template", ...)`
below, add a test with a passing and a failing case, and add the id to the list in
`tests/test_template_check.py`.

T009 is reserved for the token rule of WP19 (a declared token never used, or `{{x}}` present but
undeclared). Tokens are not merged yet, so the rule does not exist; it is one function that reads
`template.manifest["tokens"]` and the workbook's text, and nothing else here changes.

Every rule is a heuristic about what a template author probably did not mean; none of them says
Tableau will refuse the file (that is what `docs/verify-in-tableau.md` is for).
"""

from __future__ import annotations

import re
import zipfile
from typing import Iterable, Optional, Union

import pandas as pd

from .findings import Subject, finding, rule, rule_ids, rules, run_rules
from .templates import (
    ANSWERS_NAME,
    MANIFEST_NAME,
    MANIFEST_VERSION,
    Template,
    _FILE_CLASSES,
    _connections,
    _is_data_member,
    _non_parameter_datasources,
    _physical_fields,
    _usage_of,
    load_template,
    safe_connection,
)
from .verify import validate_workbook

SCOPE = "template"
RESERVED = {"T009": "the template-token rule (WP19), not built yet"}

# Connection attributes that say where one particular copy of the data lives.
_PLACES = ("server", "dbname", "filename", "directory", "warehouse", "service")
_LONG_LITERAL = 50


def template_rule_ids() -> list[str]:
    return rule_ids(SCOPE)


def check_template(source: Union[str, Template], only: Optional[Iterable[str]] = None,
                   skip: Iterable[str] = ()) -> pd.DataFrame:
    """Lint a template (a path or a loaded `Template`); return the findings
    (`findings.FINDING_COLUMNS`), sorted so the same template always gives the same frame.
    `only`/`skip` take rule ids; an unknown id is an error. Nothing is read beyond the template and
    nothing is written."""
    only = [only] if isinstance(only, str) else only
    skip = [skip] if isinstance(skip, str) else skip
    for chosen in (only or (), skip):
        for i in chosen:
            if i.strip().upper() in RESERVED:
                raise ValueError(f"{i.strip().upper()} is reserved for {RESERVED[i.strip().upper()]}")
    template = source if isinstance(source, Template) else load_template(str(source))
    return run_rules(Subject(parser=template.parser, template=template, path=template.path),
                     SCOPE, only=only, skip=skip)


def _label(ds: dict) -> str:
    return ds.get("caption") or ds["name"]


def _size(n: int) -> str:
    if n < 10_000:
        return f"{n} bytes"
    if n < 10_000_000:
        return f"{n / 1024:.0f} KB"
    return f"{n / 1024 / 1024:.1f} MB"


def _strip(name: str) -> str:
    return name.strip("[]")


def _absolute(path: str) -> bool:
    return path.startswith(("/", "\\\\", "~")) or bool(re.match(r"[A-Za-z]:[\\/]", path))


def _hard_coded(conn: dict) -> list[str]:
    """The place attributes of a connection that tie it to one machine, customer or environment. A file
    connection (text, Excel, extract) that points at a relative path (`Data/Sales.tde`, how a .twbx packages
    its files) is quiet; an absolute path, or any other kind of connection with a place, is not."""
    found = [k for k in _PLACES if conn.get(k)]
    if conn.get("class") in _FILE_CLASSES:
        return [k for k in found if k in ("filename", "dbname", "directory") and _absolute(str(conn[k]))
                or k in ("server", "warehouse", "service")]
    return found


@rule("T001", SCOPE, severity="warning",
      fix="Applying a template replaces the connection, so this only matters if the template is shared as it is; "
          "remove the connection details from the workbook you make the template from, or ignore this")
def hard_coded_connection(s: Subject):
    """A connection still names a server, database, or a file on one machine."""
    seen = set()
    entries = [(_label(ds), c) for ds in s.template.manifest.get("datasources", []) for c in ds.get("connections") or []]
    entries += [(ds.get("caption") or ds.get("name"), c) for ds in _non_parameter_datasources(s.parser.xml_doc)
                for c in _connections(ds)]
    for label, conn in entries:
        places = _hard_coded(conn)
        key = (label, tuple(sorted((k, str(conn[k])) for k in places)))
        if not places or key in seen:
            continue
        seen.add(key)
        shown = safe_connection(conn)
        yield finding(label, "the template's connection still has "
                      + ", ".join(f"{k}={shown[k]}" if k in shown else f"{k} (a local folder, not shown)" for k in places))


@rule("T002", SCOPE, severity="info",
      fix="Make the template again with `template make` (from the same workbook) to get a version 2 manifest with an id")
def not_updatable(s: Subject):
    """A version 1 manifest, or one with no id: `template update` cannot match it."""
    m = s.template.manifest
    if int(m.get("version") or 1) < MANIFEST_VERSION or not m.get("id"):
        yield finding(s.template.name, f"manifest version {m.get('version', 1)} has no template id, so workbooks "
                                       "made from it cannot be brought up to date with `template update`")


def _same(a, b) -> bool:
    if a == b:
        return True
    try:
        return float(a) == float(b)
    except (TypeError, ValueError):
        return False


@rule("T003", SCOPE, severity="error",
      fix="Set the parameter to a value, and one from its list of allowed values, in the workbook and make the template again")
def parameter_values(s: Subject):
    """A parameter has no value, or one that is not in its allowed list."""
    for p in s.template.manifest.get("parameters", []):
        name = p.get("caption") or _strip(p["name"])
        value = p.get("value")
        if value in (None, ""):
            yield finding(name, "the parameter has no value")
        elif p.get("allowed") and not any(_same(value, a) for a in p["allowed"]):
            yield finding(name, f"the value {value} is not one of the {len(p['allowed'])} allowed values")


@rule("T004", SCOPE, severity="info",
      fix="A CSV or one Excel sheet feeds one table; use a workbook or .tds as the data so its joins come along")
def several_tables(s: Subject):
    """A datasource takes its fields from several tables."""
    for ds in _non_parameter_datasources(s.parser.xml_doc):
        tables = sorted({f["table"] for f in _physical_fields(ds) if f["table"]})
        if len(tables) > 1:
            yield finding(ds.get("caption") or ds.get("name"),
                          f"the datasource has {len(tables)} tables ({', '.join(tables[:6])}"
                          f"{', ...' if len(tables) > 6 else ''})")


@rule("T005", SCOPE, severity="warning",
      fix="Make the template without --keep-data, or delete the file from the .twbx, unless sample data is wanted")
def packaged_data(s: Subject):
    """Data or an extract is still packaged in the template."""
    with zipfile.ZipFile(s.template.path) as z:
        for info in z.infolist():
            if info.filename in (MANIFEST_NAME, ANSWERS_NAME) or info.is_dir():
                continue
            if _is_data_member(info.filename):
                yield finding(info.filename, f"data packaged in the template ({_size(info.file_size)})")
    for ds in _non_parameter_datasources(s.parser.xml_doc):
        if any(isinstance(el.tag, str) and (el.tag == "extract" or el.tag.endswith("...extract")) for el in ds):
            yield finding(ds.get("caption") or ds.get("name"), "the workbook still holds an extract definition")


@rule("T006", SCOPE, severity="info",
      fix="Optional fields cost nothing, but dropping them from the source workbook keeps the template small")
def unused_fields(s: Subject):
    """A required field no sheet uses, or optional fields nothing uses."""
    usage, _ = _usage_of(s.template)
    for ds in s.template.manifest.get("datasources", []):
        optional = []
        for f in ds["fields"]:
            if f["used_by"]:
                continue
            if not f["required"]:
                optional.append(f.get("caption") or _strip(f["name"]))
                continue
            u = usage.get((ds["name"], f["name"]))
            if u is None or not (len(u.dashboards) or len(u.calculations)):
                yield finding(f"{_label(ds)}: {_strip(f['name'])}",
                              "the field is marked required but no sheet, dashboard or calculation uses it",
                              fix="Mark it optional in the manifest, or drop it from the workbook")
        if optional:
            shown = ", ".join(sorted(optional)[:8]) + (", ..." if len(optional) > 8 else "")
            yield finding(_label(ds), f"{len(optional)} optional field(s) are used by nothing: {shown}",
                          fix="These are candidates to drop from the template; they are never required")


@rule("T007", SCOPE, severity="error",
      fix="Fix the reference in the workbook, make the template again, and compare with `validate_workbook`")
def dangling_references(s: Subject):
    """A sheet, dashboard, calculation or window names something that does not exist (some checks only warn)."""
    for r in validate_workbook(s.parser).itertuples(index=False):
        yield finding(f"{r.datasource}: {r.object}" if r.datasource else r.object, f"{r.check}: {r.detail}",
                      severity=r.severity)


# In order of appearance, so a quote inside a [field name] or a comment never starts a literal.
_SCAN = re.compile(r"\[(?:[^\]]|\]\])*\]|/\*.*?\*/|//[^\n]*|(?P<dq>\"(?:[^\"\\]|\\.|\"\")*\")|(?P<sq>'(?:[^'\\]|\\.|'')*')", re.S)
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)*\.[A-Za-z]{2,}\b")
_URL = re.compile(r"(?i)\b(?:https?|ftps?|sftp|file|s3|gs|wasbs?|abfss?|hdfs)://|\bjdbc:|\bmailto:|(?<![\w.])www\.[\w-]+\.")


def _scan_literals(formula: str) -> list[tuple[str, str]]:
    """`(kind, text)` for each string literal in a formula that looks like a customer or an environment: a
    `url` (a scheme such as https, file, s3, jdbc, mailto, or www.), a `path` (UNC or drive), an `address`
    (e-mail) or `long text`."""
    found = []
    for m in _SCAN.finditer(formula or ""):
        text = m.group("dq") or m.group("sq")
        if not text:
            continue
        quote = text[0]
        lit = text[1:-1].replace(quote * 2, quote)
        if _URL.search(lit):
            found.append(("URL", lit))
        elif lit.startswith("\\\\") or re.match(r"[A-Za-z]:[\\/]", lit):
            found.append(("path", lit))
        elif _EMAIL.search(lit):
            found.append(("address", lit))
        elif len(lit) > _LONG_LITERAL:
            found.append(("long text", lit))
    return found


def _suspicious_literals(formula: str) -> list[str]:
    """The text of the literals `_scan_literals` finds (for tests; a finding never shows it)."""
    return [lit for _, lit in _scan_literals(formula)]


@rule("T008", SCOPE, severity="info",
      fix="Move the value into a parameter so each customer or environment can set its own")
def literals_in_calculations(s: Subject):
    """A calculation holds a string that looks like a customer or environment (a heuristic)."""
    for ds in _non_parameter_datasources(s.parser.xml_doc):
        for col in ds.xpath("./column[calculation][not(@param-domain-type)]"):
            lits = _scan_literals(col.find("calculation").get("formula"))
            if lits:
                # the value itself is never shown: a URL or path can hold a key or a password
                shown = "; ".join(f"{kind} *** ({len(lit)} characters)" for kind, lit in lits[:3])
                more = f"; and {len(lits) - 3} more" if len(lits) > 3 else ""
                yield finding(f"{ds.get('caption') or ds.get('name')}: {col.get('caption') or _strip(col.get('name'))}",
                              f"the formula has a string that looks like a URL, path, address or long text "
                              f"(heuristic, value hidden): {shown}{more}")


@rule("T010", SCOPE, severity="info",
      fix="Give the template a name and a description with `template make --name ... --description ...`")
def documented(s: Subject):
    """No description, or the name is just the source file's name."""
    m = s.template.manifest
    if not (m.get("description") or "").strip():
        yield finding(s.template.name, "the template has no description")
    source = m.get("source") or ""
    if m.get("name") in (source, source.rsplit(".", 1)[0]) and source:
        yield finding(s.template.name, f"the name is the source file's name ({source}); people will not recognise it")


def rules_help() -> str:
    """One line per rule, for the CLI help and the docs."""
    lines = [f"  {r.id}  {r.severity:<8}{r.title}" for r in rules(SCOPE)]
    lines += [f"  {i}  reserved for {what}" for i, what in sorted(RESERVED.items())]
    return "\n".join(sorted(lines))
