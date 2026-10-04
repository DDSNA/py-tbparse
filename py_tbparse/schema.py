"""SQL-type schemas: column names with SQL types, and what Tableau makes of them.

A database cannot be reached from here, so a connection target (see `connections.py`) *describes* its table's
columns instead. The description is a JSON column list or a `CREATE TABLE` statement, read by `read_schema`. The same
reader serves anything else that needs columns with SQL types and no data.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field as _field
from pathlib import Path
from typing import Callable, Optional, Union

from .templates import TemplateError

# SQL type (lower case, no arguments) -> family. A family is finer than Tableau's type, because the
# connection writer needs the remote type code that Tableau writes for it (see connections.py).
_FAMILIES: dict[str, tuple] = {
    "tinyint": ("tinyint",),
    "smallint": ("smallint", "int2", "smallserial"),
    "int": ("int", "integer", "mediumint", "int4", "serial"),
    "bigint": ("bigint", "int8", "bigserial"),
    "decimal": ("decimal", "numeric", "number", "money", "smallmoney"),
    "float4": ("real", "float4"),
    "double": ("float", "double", "double precision", "float8"),
    "string": ("char", "varchar", "nvarchar", "nchar", "string", "citext", "uuid", "character", "character varying",
               "varchar2", "nvarchar2", "uniqueidentifier"),
    "text": ("text", "clob", "longtext", "mediumtext", "tinytext", "ntext", "nclob"),
    "date": ("date",),
    "datetime": ("timestamp", "datetime", "datetime2", "timestamptz", "timestamp_ntz", "timestamp_ltz",
                 "timestamp_tz", "smalldatetime", "timestamp with time zone", "timestamp without time zone",
                 "datetimeoffset"),
    "boolean": ("bool", "boolean", "bit"),
}
_FAMILY_OF = {name: family for family, names in _FAMILIES.items() for name in names}
_TABLEAU_TYPE = {"tinyint": "integer", "smallint": "integer", "int": "integer", "bigint": "integer",
                 "wholenum": "integer", "decimal": "real", "float4": "real", "double": "real", "string": "string",
                 "text": "string", "date": "date", "datetime": "datetime", "boolean": "boolean", "other": "string"}
_MODIFIERS = {"unsigned", "signed", "zerofill"}


def _split_type(sql_type: str) -> tuple[str, list[str]]:
    """The type's words without arguments and modifiers, and the arguments: `'Number (12, 2)'` -> `('number', ['12', '2'])`."""
    text = str(sql_type).lower().strip()
    found = re.search(r"\(([^)]*)\)", text)
    args = [a.strip() for a in found.group(1).split(",")] if found else []
    words = [w for w in re.sub(r"\([^)]*\)", " ", text).split() if w not in _MODIFIERS]
    return " ".join(words), args


def sql_family(sql_type: str) -> str:
    """The family of a SQL type: `tinyint`, `smallint`, `int`, `bigint`, `wholenum` (a decimal with no decimals),
    `decimal`, `float4`, `double`, `string`, `text`, `date`, `datetime`, `boolean`, or `other` (not known)."""
    name, args = _split_type(sql_type)
    family = _FAMILY_OF.get(name)
    if family is None:
        return "other"
    if family == "decimal" and name != "money" and name != "smallmoney" and (
            len(args) == 1 or (len(args) == 2 and args[1] == "0")):
        return "wholenum"
    return family


def sql_to_tableau_type(sql_type: str, warn: Optional[Callable[[str], None]] = None, column: str = "") -> str:
    """Tableau's type (`integer`, `real`, `string`, `date`, `datetime`, `boolean`) for a SQL type; arguments, case and
    spacing do not matter, and a `numeric(p,0)` is an integer. A type with no Tableau counterpart (json, blob,
    geometry, array, time ...) is a `string`, and `warn(message)` is told which column it was."""
    family = sql_family(sql_type)
    if family == "other" and warn is not None:
        warn(f"column {column or '?'}: type {str(sql_type).strip()!r} has no Tableau type; treated as a string")
    return _TABLEAU_TYPE[family]


@dataclass
class Schema:
    columns: list[dict] = _field(default_factory=list)   # {name, type}
    table: Optional[str] = None                           # the table's name, when a CREATE TABLE gave one


# ------------------------------------------------------------------------------------------------ DDL --

_CONSTRAINTS = {"primary", "foreign", "unique", "constraint", "check", "key", "index", "fulltext", "exclude", "like"}
_STOPS = {"not", "null", "primary", "default", "references", "unique", "check", "collate", "generated", "auto_increment",
          "autoincrement", "identity", "comment", "constraint", "as", "encode", "key", "on"}
_IDENT = re.compile(r'\s*(?:"((?:[^"]|"")+)"|`((?:[^`]|``)+)`|\[([^\]]+)\]|([A-Za-z_][\w$]*))')


def _blank_comments(sql: str) -> str:
    """The statement with `--` and `/* */` comments replaced by spaces (newlines kept, so line numbers hold),
    leaving quoted text alone."""
    out, i, n = [], 0, len(sql)
    while i < n:
        c = sql[i]
        if c in "'\"`":
            j = i + 1
            while j < n and sql[j] != c:
                j += 1
            out.append(sql[i:j + 1])
            i = j + 1
        elif sql.startswith("--", i):
            j = sql.find("\n", i)
            j = n if j < 0 else j
            out.append(" " * (j - i))
            i = j
        elif sql.startswith("/*", i):
            j = sql.find("*/", i + 2)
            j = n if j < 0 else j + 2
            out.append("".join(ch if ch == "\n" else " " for ch in sql[i:j]))
            i = j
        else:
            out.append(c)
            i += 1
    return "".join(out)


def _line(text: str, pos: int) -> int:
    return text.count("\n", 0, pos) + 1


def _ident(text: str, pos: int) -> Optional[tuple[str, int]]:
    m = _IDENT.match(text, pos)
    if not m:
        return None
    name = m.group(1) or m.group(2) or m.group(3) or m.group(4)
    if m.group(1):
        name = name.replace('""', '"')
    elif m.group(2):
        name = name.replace("``", "`")
    return name, m.end()


def _top_level_items(body: str, offset: int) -> list[tuple[str, int]]:
    """The comma-separated items of a table body, each with the position it starts at in the whole text."""
    items, depth, start, quote = [], 0, 0, None
    for i, c in enumerate(body):
        if quote:
            if c == quote:
                quote = None
        elif c in "'\"`":
            quote = c
        elif c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
        elif c == "," and depth == 0:
            items.append((body[start:i], offset + start))
            start = i + 1
    items.append((body[start:], offset + start))
    return items


def parse_ddl(sql: str) -> tuple[Optional[str], list[dict]]:
    """The table name and columns of one `CREATE TABLE` statement.

    A small, documented subset: one table; `name type [(args)] [NOT NULL] [PRIMARY KEY] [DEFAULT ...]` per column;
    table constraints (`PRIMARY KEY`, `FOREIGN KEY`, `UNIQUE`, `CONSTRAINT`, `CHECK`, indexes) are skipped; `--` and
    `/* */` comments; identifiers quoted with `"x"`, `` `x` `` or `[x]`; a schema in front of the table's name is dropped.
    Anything else (a second table, `CREATE INDEX`, a column with no type, an unclosed parenthesis) is an error that
    names the line, never a guess."""
    text = _blank_comments(sql)
    head = re.search(r"\bcreate\s+(?:or\s+replace\s+)?(?:(?:global\s+|local\s+)?(?:temp|temporary)\s+|transient\s+)?"
                     r"table\s+(?:if\s+not\s+exists\s+)?", text, re.I)
    if not head:
        raise TemplateError("no CREATE TABLE statement found in the schema")
    pos, parts = head.end(), []
    while True:
        got = _ident(text, pos)
        if not got:
            raise TemplateError(f"line {_line(text, pos)}: expected a table name after CREATE TABLE")
        parts.append(got[0])
        pos = got[1]
        if text[pos:pos + 1] == ".":
            pos += 1
            continue
        break
    table = parts[-1]
    pos += len(text[pos:]) - len(text[pos:].lstrip())
    if text[pos:pos + 1] != "(":
        raise TemplateError(f"line {_line(text, pos)}: expected '(' after the table name")
    depth, end, quote = 0, None, None
    for i in range(pos, len(text)):
        c = text[i]
        if quote:
            if c == quote:
                quote = None
        elif c in "'\"`":
            quote = c
        elif c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                end = i
                break
    if end is None:
        raise TemplateError(f"line {_line(text, pos)}: unclosed parenthesis in CREATE TABLE")
    tail = text[end + 1:]
    lead_in = re.match(r"\s*;?", tail).end()
    rest = tail[lead_in:]
    if rest.strip():
        at = end + 1 + lead_in + (len(rest) - len(rest.lstrip()))
        what = "a second table" if re.match(r"create\s+(or\s+replace\s+)?(temp\w*\s+)?table", rest.strip(), re.I) else "this"
        raise TemplateError(f"line {_line(text, at)}: only one table is supported, found {what}: "
                            f"{rest.strip().splitlines()[0][:40]!r}")
    columns: list[dict] = []
    for item, at in _top_level_items(text[pos + 1:end], pos + 1):
        if not item.strip():
            continue
        lead = at + len(item) - len(item.lstrip())
        first = item.split(None, 1)[0].lower().strip('"`[]')
        if first in _CONSTRAINTS and not item.lstrip().startswith(('"', "`", "[")):
            continue
        got = _ident(text, lead)
        if not got:
            raise TemplateError(f"line {_line(text, lead)}: cannot read a column from {item.strip()[:40]!r}")
        name, cur = got
        words, depth, tail = [], 0, text[cur:at + len(item)]
        for tok in re.finditer(r"\(|\)|[^\s()]+", tail):
            t = tok.group(0)
            if t == "(":
                depth += 1
                words.append(t)
            elif t == ")":
                depth -= 1
                words.append(t)
            elif depth == 0 and t.lower() in _STOPS:
                break
            else:
                words.append(t)
        type_text = re.sub(r"\s+\(", "(", " ".join(words)).replace("( ", "(").replace(" )", ")").strip()
        if not type_text or type_text.startswith("("):
            raise TemplateError(f"line {_line(text, lead)}: column {name!r} has no type")
        if name.lower() in {c["name"].lower() for c in columns}:
            raise TemplateError(f"line {_line(text, lead)}: column {name!r} appears twice")
        columns.append({"name": name, "type": type_text})
    if not columns:
        raise TemplateError(f"table {table!r} has no columns")
    return table, columns


# ----------------------------------------------------------------------------------------------- reader --

def _check_columns(columns, where: str) -> list[dict]:
    if not isinstance(columns, list) or not columns:
        raise TemplateError(f"{where}: expected a non-empty list of {{\"name\": ..., \"type\": ...}} columns")
    out, seen = [], set()
    for i, col in enumerate(columns):
        if not isinstance(col, dict) or not isinstance(col.get("name"), str) or not col["name"].strip():
            raise TemplateError(f"{where}: column {i + 1} needs a \"name\"")
        if not isinstance(col.get("type"), str) or not col["type"].strip():
            raise TemplateError(f"{where}: column {col['name']!r} needs a \"type\" (a SQL type such as varchar(80))")
        if col["name"] in seen:
            raise TemplateError(f"{where}: column {col['name']!r} appears twice")
        seen.add(col["name"])
        out.append({"name": col["name"], "type": col["type"].strip()})
    return out


def read_schema(source: Union[str, Path, list, dict]) -> Schema:
    """Columns with SQL types, from a JSON file (a list, or an object with `columns`), a `.sql` file holding one
    `CREATE TABLE` (see `parse_ddl`), or the list itself. Raises `TemplateError` for anything else."""
    if isinstance(source, (list, dict)):
        columns = source.get("columns") if isinstance(source, dict) else source
        return Schema(_check_columns(columns, "schema"))
    if not isinstance(source, (str, Path)):
        raise TemplateError("a schema is a file path or a list of {name, type} columns")
    path = Path(source)
    if not path.exists():
        raise FileNotFoundError(f"no such schema file: {source}")
    text = path.read_text(encoding="utf-8-sig")
    if path.suffix.lower() == ".json":
        try:
            data = json.loads(text)
        except json.JSONDecodeError as e:
            raise TemplateError(f"{path.name} is not valid JSON: {e}") from None
        columns = data.get("columns") if isinstance(data, dict) else data
        return Schema(_check_columns(columns, path.name), data.get("table") if isinstance(data, dict) else None)
    try:
        table, columns = parse_ddl(text)
    except TemplateError as e:
        raise TemplateError(f"{path.name}: {e}") from None
    return Schema(columns, table)
