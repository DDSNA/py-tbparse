"""Share-safe export (WP12): a copy of a workbook with what identifies a person, a server or a data set taken out.

`sanitize(workbook, output_path)` removes user names and passwords, server/database/schema names, absolute
folders, custom and initial SQL, extracts and packaged data files, comments and annotations, field descriptions,
user filters, author ids, thumbnails and the repository location of a published workbook. It returns the output
path and fills `report` with a count per category and the *leftovers*: places it cannot judge (a removed value
that still appears somewhere, a calculation that calls `USERNAME()`, a connection attribute it does not know,
titles and captions it keeps as written). It is a clean-up, not a guarantee: read the report and the result before
sharing. Nothing here was opened in Tableau.

The input is never written. Running it on its own output changes nothing (the second report counts zero).
"""

from __future__ import annotations

import copy
import csv
import io
import random
import re
import zipfile
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Iterable, Optional, Union

from lxml import etree

from ._xml import ANY_RELATION
from .parser import TwbParser
from .templates import (
    DataSource,
    _csv_connection,
    _endswith_tag,
    _is_data_member,
    _object_model,
    _physical_fields,
    _replace_connection,
    _strip_extracts,
    _write_new,
)

CATEGORIES = (
    "usernames", "passwords", "servers", "databases", "schemas", "paths", "custom_sql", "extracts",
    "packaged_data", "comments", "user_filters", "user_specific", "repository", "thumbnails", "captions",
)
_DESCRIPTIONS = {
    "usernames": "user names in connections",
    "passwords": "passwords in connections",
    "servers": "server, port, warehouse, service and similar connection attributes",
    "databases": "database names",
    "schemas": "schema names",
    "paths": "folders and the folder part of file names",
    "custom_sql": "custom SQL, initial SQL and one-time SQL (replaced, never listed)",
    "extracts": "extract definitions and extract files (.hyper, .tde)",
    "packaged_data": "other data files packed in a .twbx",
    "comments": "XML comments, annotations and field descriptions",
    "user_filters": "user filters",
    "user_specific": "author ids and user names on filters",
    "repository": "the repository location of a published workbook or data source",
    "thumbnails": "thumbnail images",
    "captions": "datasource and connection captions that held a removed value",
}

# connection attribute -> (category, placeholder used with placeholders=True; None means blank)
_CONNECTION_RULES = {
    "username": ("usernames", "user"),
    "password": ("passwords", None),
    "server": ("servers", "server.example.com"),
    "port": ("servers", None),
    "warehouse": ("servers", "warehouse"),
    "service": ("servers", "service"),
    "tenant": ("servers", None),
    "odbc-connect-string-extras": ("servers", None),
    "dbname": ("databases", "database"),
    "updated-database": ("databases", "database"),
    "schema": ("schemas", "schema"),
    "directory": ("paths", "data"),
    "csvFile": ("paths", "data"),
    "ogr-grid-shift-folder": ("paths", None),
    "one-time-sql": ("custom_sql", None),
}
# Connection attributes that carry no name, folder or account; any other attribute is listed as a leftover.
_KNOWN_CONNECTION_ATTRS = {
    "class", "filename", "tablename", "validate", "update-time", "cleaning", "compat", "dataRefreshTime",
    "interpretationMode", "author-locale", "default-settings", "sslmode", "access_mode", "authentication",
    "workgroup-auth-mode", "odbc-native-protocol", "auto-extract", "character-set", "driver",
    "force-character-set", "force-header", "force-separator", "header", "separator", "source-charset",
    "server-oauth", "db-format", "max-varchar-size", "filetype", "name", "caption", "id",
}
_USER_FUNCTIONS = re.compile(r"\b(USERNAME|FULLNAME|USERDOMAIN|ISMEMBEROF|USER)\s*\(", re.IGNORECASE)
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_URL = re.compile(r"https?://(?!www\.tableausoftware\.com)[^\s'\"<>]+", re.IGNORECASE)
_ABS_PATH = re.compile(r"(?:^|[\s'\"=])(?:[A-Za-z]:[\\/]|\\\\|/(?:home|Users|var|tmp|mnt|opt|srv)/)")
_PLACEHOLDER_SQL = "SELECT 1"
_MAX_LISTED = 50


class SanitizeError(ValueError):
    """The workbook cannot be sanitized as asked."""


def _is_absolute(value: str) -> bool:
    return bool(re.match(r"^(?:[A-Za-z]:[\\/]|\\\\|/|~)", value))


def _basename(value: str) -> str:
    return re.split(r"[\\/]", value)[-1]


def _drop(el) -> None:
    """Remove `el` from its parent but keep the text that follows it."""
    parent = el.getparent()
    if parent is None:
        return
    if el.tail:
        prev = el.getprevious()
        if prev is not None:
            prev.tail = (prev.tail or "") + el.tail
        else:
            parent.text = (parent.text or "") + el.tail
    parent.remove(el)


def _label(el) -> str:
    """A short location: the tag, and the name of the element or of its nearest named ancestor."""
    tag = el.tag if isinstance(el.tag, str) else "comment"
    node = el
    while node is not None:
        name = node.get("caption") or node.get("name")
        if name:
            return f"{tag} '{name}'" if node is el else f"{tag} in {node.tag} '{name}'"
        node = node.getparent()
    return tag


class _Run:
    """What one sanitize run did: counts, the values it took out (never printed), and the leftovers."""

    def __init__(self, keep: set, placeholders: bool):
        self.keep = keep
        self.placeholders = placeholders
        self.removed = {c: 0 for c in CATEGORIES}
        self.secrets: set[str] = set()
        self.qualifiers: dict[str, str] = {}   # a removed database or schema name -> the marker for table names
        self.leftovers: list[dict] = []
        self.details: dict[str, list[str]] = {"custom_sql": []}

    def active(self, category: str) -> bool:
        return category not in self.keep

    def leftover(self, kind: str, where: str, note: str) -> None:
        self.leftovers.append({"kind": kind, "where": where, "note": note})


def _scrub_connections(doc, run: _Run) -> None:
    unknown: dict[str, int] = {}
    for conn in doc.iter("connection"):
        for attr, (category, placeholder) in _CONNECTION_RULES.items():
            if conn.get(attr) is None or not run.active(category):
                continue
            value = conn.get(attr)
            new = placeholder if (run.placeholders and placeholder) else ""
            if attr in ("directory", "csvFile") and not _is_absolute(value):
                continue   # a relative folder names no machine
            if value == new or not value:
                continue
            if category != "custom_sql":
                run.secrets.add(value)
            if category in ("databases", "schemas"):
                run.qualifiers[value] = "database" if category == "databases" else "schema"
            run.removed[category] += 1
            conn.set(attr, new)
        filename = conn.get("filename")
        if filename and run.active("paths") and re.search(r"[\\/]", filename):
            run.secrets.add(filename)
            conn.set("filename", _basename(filename))
            run.removed["paths"] += 1
        for attr in conn.attrib:
            if attr not in _KNOWN_CONNECTION_ATTRS and attr not in _CONNECTION_RULES:
                unknown[attr] = unknown.get(attr, 0) + 1
    for attr, n in sorted(unknown.items()):
        run.leftover("connection attribute", attr, f"kept, not judged: {n} connection(s) have it")


_TABLE_PARTS = re.compile(r"(?<=\])\.(?=\[)")


def _scrub_table_names(doc, run: _Run) -> None:
    """`[acme_dw].[orders]` -> `[schema].[orders]`: a relation's table name is qualified with the database and
    schema that were removed from the connection. The relation's `name` and the object model's ids are not
    rewritten (other parts of the workbook refer to them); they show up in the leftovers."""
    if not run.qualifiers:
        return
    for rel in doc.xpath(f"//{ANY_RELATION}[@table]"):
        pieces = _TABLE_PARTS.split(rel.get("table"))
        changed = False
        for i, piece in enumerate(pieces[:-1]):   # the last piece is the table itself
            marker = run.qualifiers.get(piece[1:-1] if piece[:1] == "[" and piece[-1:] == "]" else piece)
            if marker:
                pieces[i] = f"[{marker}]"
                run.removed["databases" if marker == "database" else "schemas"] += 1
                changed = True
        if changed:
            rel.set("table", ".".join(pieces))


def _scrub_sql(doc, run: _Run) -> None:
    if not run.active("custom_sql"):
        return
    for rel in doc.xpath(f"//{ANY_RELATION}"):
        text = (rel.text or "")
        is_text = rel.get("type") == "text"
        formula = rel.get("formula")
        if is_text and text.strip() and text.strip() != _PLACEHOLDER_SQL:
            run.details["custom_sql"].append(f"{rel.get('name') or '(unnamed)'} ({len(text)} characters)")
            rel.text = _PLACEHOLDER_SQL
            run.removed["custom_sql"] += 1
        if formula and re.match(r"^\s*(select|with)\b", formula, re.IGNORECASE) and formula.strip() != _PLACEHOLDER_SQL:
            run.details["custom_sql"].append(f"{rel.get('name') or '(unnamed)'} ({len(formula)} characters)")
            rel.set("formula", _PLACEHOLDER_SQL)
            run.removed["custom_sql"] += 1
    for node in doc.xpath("//initial-sql"):
        _drop(node)
        run.removed["custom_sql"] += 1


def _strip_misc(doc, run: _Run) -> None:
    if run.active("extracts"):
        run.removed["extracts"] += _strip_extracts(doc)
    if run.active("repository"):
        for el in doc.xpath("//repository-location"):
            _drop(el)
            run.removed["repository"] += 1
    if run.active("thumbnails"):
        for el in doc.xpath("//thumbnails"):
            run.removed["thumbnails"] += max(1, len(el.xpath("./thumbnail")))
            _drop(el)
    if run.active("comments"):
        root = doc.getroot()
        # comments and instructions beside the root cannot be removed in place; serializing the root alone drops them
        beside = [n for n in list(root.itersiblings(preceding=True)) + list(root.itersiblings())]
        run.removed["comments"] += len(beside)
        for el in doc.xpath("//comment()"):
            if el.getparent() is not None:
                _drop(el)
                run.removed["comments"] += 1
        for el in doc.xpath("//annotation | //comment | //column/desc"):
            if el.getparent() is not None:
                _drop(el)
                run.removed["comments"] += 1
        for el in doc.xpath("//annotations[not(*)]"):
            _drop(el)
    if run.active("user_filters"):
        for el in doc.xpath("//user-filter"):
            _drop(el)
            run.removed["user_filters"] += 1
    if run.active("user_specific"):
        for el in doc.iter():
            if not isinstance(el.tag, str):
                continue
            for attr in list(el.attrib):
                if attr.endswith("author-id") and el.get(attr):
                    run.secrets.add(el.get(attr))
                    del el.attrib[attr]
                    run.removed["user_specific"] += 1
            if el.tag == "groupfilter" and el.get("user"):
                run.secrets.add(el.get("user"))
                el.set("user", "")
                run.removed["user_specific"] += 1


def _replace_in_captions(doc, run: _Run) -> None:
    """A named connection's caption is usually the server name: the removed values go from the captions."""
    if not run.active("captions") or not run.secrets:
        return
    values = sorted((s for s in run.secrets if len(s) >= 3), key=len, reverse=True)
    for el in doc.xpath("//datasource[@caption] | //named-connection[@caption]"):
        caption = el.get("caption")
        new = caption
        for value in values:
            new = new.replace(value, "connection" if el.tag == "named-connection" else "datasource")
        if new != caption:
            el.set("caption", new)
            run.removed["captions"] += 1


def _word(value: str):
    return re.compile(r"(?<![A-Za-z0-9_])" + re.escape(value) + r"(?![A-Za-z0-9_])", re.IGNORECASE)


def _find_leftovers(doc, run: _Run) -> None:
    # A connection class (`postgres`) is a word the workbook keeps on purpose, even if it was also a user name.
    classes = {c.get("class").lower() for c in doc.iter("connection") if c.get("class")}
    values = sorted({s for s in run.secrets if len(s) >= 4 and s.lower() not in classes})
    patterns = [_word(v) for v in values]
    groups: dict[tuple, list] = {}
    for el in doc.iter():
        if not isinstance(el.tag, str):
            continue
        texts = [(f"@{k}", v) for k, v in el.attrib.items()] + ([("text", el.text)] if el.text and el.text.strip() else [])
        for where, text in texts:
            if any(p.search(text) for p in patterns):
                kind = "removed value still present"
            elif _EMAIL.search(text):
                kind = "e-mail address"
            elif _URL.search(text):
                kind = "web address"
            elif _ABS_PATH.search(text):
                kind = "absolute path"
            else:
                continue
            tag = el.tag.split("...")[-1]
            groups.setdefault((kind, f"{tag} {where}"), []).append(_label(el))
    for (kind, where), labels in sorted(groups.items()):
        example = f"; first: {labels[0]}" if kind != "removed value still present" or len(labels) > 1 else f": {labels[0]}"
        run.leftover(kind, where, f"{len(labels)} place(s){example}; left as written, judge it yourself")
    for col in doc.xpath("//column[calculation/@formula]"):
        formula = col.find("calculation").get("formula") or ""
        if _USER_FUNCTIONS.search(formula):
            run.leftover("user function in a calculation", _label(col),
                         "USERNAME()/FULLNAME()/ISMEMBEROF() and the like are kept (the calculation is not rewritten)")
    tables = doc.xpath(f"//{ANY_RELATION}[@table]")
    if tables:
        run.leftover("table names", f"{len(tables)} relation(s)",
                     "table names are kept, often qualified with the database and schema name: worksheets, "
                     "calculations and the object model refer to them")


def _swap_in_fake_data(doc, seed: int, rows: int, run_report: list[dict]) -> dict[str, bytes]:
    """Replace each simple datasource's connection with one to a generated CSV (`_csv_connection`)."""
    files: dict[str, bytes] = {}
    model = _object_model(doc)
    for index, ds in enumerate(doc.xpath("/workbook/datasources/datasource[not(@name='Parameters')]")):
        name = ds.get("caption") or ds.get("name") or f"datasource{index}"
        fields = _physical_fields(ds)
        graph = ds.xpath("./*[substring(name(), string-length(name()) - 11) = 'object-graph']/objects/object/@id")
        if not fields:
            run_report.append({"datasource": name, "status": "skipped", "reason": "no physical fields recorded"})
            continue
        if len(graph) > 1 or ds.xpath(".//relation[@type='join' or @type='union']"):
            run_report.append({"datasource": name, "status": "skipped",
                               "reason": "several tables (join, union or relationships)"})
            continue
        if any(c.get("class") == "sqlproxy" for c in ds.iter("connection")):
            run_report.append({"datasource": name, "status": "skipped", "reason": "published data source"})
            continue
        columns, local_of, seen = [], {}, set()
        for f in fields:
            col = f["remote"] or f["name"].strip("[]")
            while col in seen:
                col += "_"
            seen.add(col)
            columns.append({"name": col, "datatype": f["datatype"]})
            local_of[col] = f["name"]
        stem = re.sub(r"[^0-9A-Za-z_-]+", "_", name).strip("_") or "datasource"
        path = f"Data/synthetic/{stem}_{index + 1}_synthetic.csv"
        files[path] = _fake_csv(columns, random.Random(f"{seed}:{name}"), rows)
        data = DataSource(path=path, kind="csv", fields=columns)
        conn, extras = _csv_connection(data, local_of, model=model, object_id=graph[0] if graph else None)
        _replace_connection(ds, conn, extras)
        run_report.append({"datasource": name, "status": "synthetic", "file": path, "rows": rows,
                           "columns": len(columns)})
    return files


def _fake_csv(columns: list[dict], rng: random.Random, rows: int) -> bytes:
    start = date(2024, 1, 1)
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow([c["name"] for c in columns])
    for i in range(rows):
        row = []
        for c in columns:
            kind = c["datatype"]
            if kind == "integer":
                row.append(rng.randint(1, 1000))
            elif kind == "real":
                row.append(f"{rng.uniform(0, 1000):.2f}")
            elif kind == "boolean":
                row.append(rng.choice(["true", "false"]))
            elif kind == "date":
                row.append((start + timedelta(days=rng.randint(0, 365))).isoformat())
            elif kind == "datetime":
                moment = datetime(2024, 1, 1) + timedelta(days=rng.randint(0, 365), seconds=rng.randint(0, 86399))
                row.append(moment.strftime("%Y-%m-%d %H:%M:%S"))
            else:
                row.append(f"{c['name'][:20]} {i % 7 + 1}")
        writer.writerow(row)
    return out.getvalue().encode("utf-8")


def _member_category(name: str) -> Optional[str]:
    low = name.lower()
    if low.startswith("thumbnails/"):
        return "thumbnails"
    if low.endswith((".hyper", ".tde")):
        return "extracts"
    if _is_data_member(name):
        return "packaged_data"
    return None


def _write_zip(parser: TwbParser, twb: bytes, extra: dict[str, bytes], run: _Run) -> bytes:
    out = io.BytesIO()
    twb_name = parser.twb_name if parser.twbx_path else Path(parser.path).name
    kept_other: dict[str, int] = {}
    with zipfile.ZipFile(out, "w") as dst:
        if parser.twbx_path:
            with zipfile.ZipFile(parser.twbx_path) as src:
                for info in src.infolist():
                    if info.filename == twb_name:
                        dst.writestr(info, twb, compress_type=info.compress_type)
                        continue
                    if info.is_dir():
                        continue
                    category = _member_category(info.filename)
                    if category and run.active(category):
                        run.removed[category] += 1
                        continue
                    suffix = Path(info.filename).suffix.lower() or "(no extension)"
                    kept_other[suffix] = kept_other.get(suffix, 0) + 1
                    dst.writestr(info, src.read(info.filename), compress_type=info.compress_type)
        else:
            info = zipfile.ZipInfo(twb_name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            dst.writestr(info, twb)
        for name, data in extra.items():
            if name in (getattr(i, "filename", None) for i in dst.infolist()):
                continue
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            dst.writestr(info, data)
    for suffix, n in sorted(kept_other.items()):
        kind = "workbook or data source" if suffix in (".twb", ".tds", ".tdsx", ".twbx") else "file"
        run.leftover(f"packaged {kind}", f"{n} member(s) {suffix}", "kept, not opened or judged")
    return out.getvalue()


def sanitize(
    workbook: Union[TwbParser, str],
    output_path: str,
    keep: Iterable[str] = (),
    placeholders: bool = False,
    fake_data: bool = False,
    seed: int = 0,
    fake_rows: int = 20,
    overwrite: bool = False,
    report: Optional[dict] = None,
) -> str:
    """Write a share-safe copy of `workbook` to `output_path`; return that path.

    Taken out (counted per category in `report["removed"]`, see `CATEGORIES`): user names and passwords,
    server, port, database and schema names, absolute folders (a file name stays, without its folder), custom,
    initial and one-time SQL (replaced by `SELECT 1`), extracts and packaged data files, XML comments,
    annotations and field descriptions, user filters, author ids, thumbnails and a repository location.
    `placeholders=True` writes stand-in values (`server.example.com`, `database`, `schema`, `user`) instead of
    blanks. `keep` names categories to leave alone. `fake_data=True` also generates a small seeded CSV per
    simple datasource from its field list and connects the workbook to it (a `.twbx` output; datasources with
    joins, relationships or a published source are skipped and listed): synthetic, never the real data.

    `report` (a dict) is filled with `removed` (count per category), `leftovers` (what it could not judge: a
    removed value that still appears, a `USERNAME()` calculation, an unknown connection attribute, kept
    titles), `custom_sql` (where the SQL was, never the text), `fake_data` and `output`. The input is never
    written; an existing output is refused unless `overwrite=True`. A second run on the output removes nothing.
    """
    keep = set(keep)
    unknown = keep - set(CATEGORIES)
    if unknown:
        raise SanitizeError(f"unknown categor{'y' if len(unknown) == 1 else 'ies'} to keep: {', '.join(sorted(unknown))} "
                            f"(choose from {', '.join(CATEGORIES)})")
    if not isinstance(workbook, TwbParser):
        workbook = TwbParser(str(workbook))
    source = Path(workbook.twbx_path or workbook.path)
    out = Path(output_path)
    if out.suffix.lower() not in (".twb", ".twbx"):
        raise SanitizeError(f"the output is a .twb or .twbx file, got {out.suffix or 'no extension'}")
    if out.exists() and source.exists() and (out.resolve() == source.resolve() or out.samefile(source)):
        raise FileExistsError(f"refusing to overwrite the input workbook: {out}")
    twbx = bool(workbook.twbx_path) or fake_data
    if (out.suffix.lower() == ".twbx") != twbx:
        raise SanitizeError(
            f"the output must be a {'.twbx' if twbx else '.twb'} file"
            + (" (fake data is packed in it)" if fake_data and not workbook.twbx_path else " (the input's format)"))

    run = _Run(keep, placeholders)
    doc = copy.deepcopy(workbook.xml_doc)
    _strip_misc(doc, run)
    _scrub_connections(doc, run)
    _scrub_table_names(doc, run)
    _scrub_sql(doc, run)
    _replace_in_captions(doc, run)
    fake_report: list[dict] = []
    files: dict[str, bytes] = {}
    if fake_data:
        files = _swap_in_fake_data(doc, seed, fake_rows, fake_report)
    _find_leftovers(doc, run)
    run.leftover("kept as written", "titles, captions, names, formulas and text boxes",
                 "the sanitizer does not read these for personal or company information")
    twb = etree.tostring(doc if "comments" in keep else doc.getroot(), xml_declaration=True, encoding="utf-8")
    data = _write_zip(workbook, twb, files, run) if twbx else twb
    _write_new(out, data, overwrite)
    if report is not None:
        report.update(output=str(out), removed=dict(run.removed), leftovers=list(run.leftovers),
                      custom_sql=run.details["custom_sql"], fake_data=fake_report, placeholders=placeholders,
                      keep=sorted(keep))
    return str(out)


def format_report(report: dict) -> str:
    """The report of `sanitize` as text: the count per category, the custom SQL it replaced and the leftovers."""
    lines = [f"sanitized copy: {report['output']}", "", "removed:"]
    for category in CATEGORIES:
        n = report["removed"][category]
        kept = " (kept: --keep)" if category in report.get("keep", []) else ""
        lines.append(f"  {category:<14}{n:>5}  {_DESCRIPTIONS[category]}{kept}")
    lines.append(f"  {'total':<14}{sum(report['removed'].values()):>5}")
    if report["custom_sql"]:
        lines += ["", "custom SQL replaced:"] + [f"  {s}" for s in report["custom_sql"]]
    for entry in report.get("fake_data") or []:
        if entry["status"] == "synthetic":
            lines.append(f"fake data: {entry['datasource']}: {entry['rows']} synthetic rows x {entry['columns']} columns in {entry['file']}")
        else:
            lines.append(f"fake data: {entry['datasource']}: skipped ({entry['reason']})")
    left = report["leftovers"]
    lines += ["", f"leftovers it could not judge ({len(left)}):"]
    for item in left[:_MAX_LISTED]:
        lines.append(f"  [{item['kind']}] {item['where']}: {item['note']}")
    if len(left) > _MAX_LISTED:
        lines.append(f"  ... and {len(left) - _MAX_LISTED} more")
    lines += ["", "Read the leftovers and the result before sharing. Nothing was opened in Tableau."]
    return "\n".join(lines)
