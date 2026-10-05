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
    text = re.sub(r"\b(?:character\s+set|charset|collate)\s+[\w.$\"`]+", " ", text)
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

_CONSTRAINTS = {"primary", "foreign", "unique", "constraint", "check", "key", "index", "fulltext", "spatial", "exclude", "like"}
_STOPS = {"not", "null", "primary", "default", "references", "unique", "check", "collate", "generated", "auto_increment",
          "autoincrement", "identity", "comment", "constraint", "as", "encode", "key", "on"}
_IDENT = re.compile(r'\s*(?:"((?:[^"]|"")+)"|`((?:[^`]|``)+)`|\[((?:[^\]]|\]\])+)\]|([A-Za-z_][\w$]*))')


def _quoted_end(text: str, i: int, backslash: bool = False) -> Optional[int]:
    """If a quoted region (`'..'`, `".."`, `` `..` `` or `[..]`, where `]]` is an escaped bracket) starts at `i`, the
    index just after it (the end of the text when it is never closed); else None. A `[` is an identifier quote only
    where an identifier can start, so `int[]` and `text[3]` are not. With `backslash` (MySQL), a backslash in a
    `'..'` or `".."` string escapes the next character, so `'it\\'s'` is one string."""
    c = text[i]
    if backslash and c in "'\"":
        j = i + 1
        while j < len(text):
            if text[j] == "\\":
                j += 2
            elif text[j] == c:
                return j + 1
            else:
                j += 1
        return len(text)
    if c in "'\"`":
        j = text.find(c, i + 1)
        return len(text) if j < 0 else j + 1
    if c == "[" and (i == 0 or not (text[i - 1].isalnum() or text[i - 1] in "_$]\")")):
        j = i + 1
        while j < len(text):
            if text[j] == "]":
                if text[j + 1:j + 2] == "]":
                    j += 2
                    continue
                return j + 1
            j += 1
        return len(text)
    return None


def _blank_comments(sql: str, backslash: bool = False) -> str:
    """The statement with `--` and `/* */` comments replaced by spaces (newlines kept, so line numbers hold),
    leaving quoted text alone."""
    out, i, n = [], 0, len(sql)
    while i < n:
        j = _quoted_end(sql, i, backslash)
        if j is not None:
            out.append(sql[i:j])
            i = j
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
            out.append(sql[i])
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
    elif m.group(3):
        name = name.replace("]]", "]")
    return name, m.end()


def _top_level_items(body: str, offset: int, backslash: bool = False) -> list[tuple[str, int]]:
    """The comma-separated items of a table body, each with the position it starts at in the whole text."""
    items, depth, start, i = [], 0, 0, 0
    while i < len(body):
        j = _quoted_end(body, i, backslash)
        if j is not None:
            i = j
            continue
        c = body[i]
        if c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
        elif c == "," and depth == 0:
            items.append((body[start:i], offset + start))
            start = i + 1
        i += 1
    items.append((body[start:], offset + start))
    return items


_TYPE_WORDS = {n.split()[0] for n in _FAMILY_OF} | {
    "time", "timetz", "json", "jsonb", "blob", "tinyblob", "mediumblob", "longblob", "binary", "varbinary", "enum", "set",
    "year", "geometry", "geography", "bytea", "interval", "array", "variant", "object", "xml", "image", "datetime"}
_TOKEN = re.compile(r'"(?:[^"]|"")*"|`(?:[^`]|``)*`|\[(?:[^\]]|\]\])*\]|\(|[A-Za-z_][\w$]*|\S')


def _is_constraint(item: str) -> bool:
    """Whether a table-body item is a constraint or index (skipped), not a column. An unquoted first word such as
    `key`, `index`, `check`, `like` or `primary` can also be a column's name, so the next token decides."""
    toks = [m.group(0) for m in _TOKEN.finditer(item)]
    first = toks[0].lower()
    if first not in _CONSTRAINTS:
        return False
    nxt = toks[1].lower() if len(toks) > 1 else ""
    after = toks[2] if len(toks) > 2 else ""
    if first in ("key", "index", "unique", "fulltext", "spatial"):
        if nxt == "(":
            return True
        if first != "key" and first != "index" and nxt in ("key", "index"):
            return True
        if nxt in _TYPE_WORDS and nxt not in ("key", "index"):
            return False
        return after == "("
    if first in ("primary", "foreign"):
        return nxt == "key"
    if first == "check":
        return nxt == "("
    if first == "exclude":
        return nxt in ("(", "using")
    if first == "constraint":
        kinds = ("check", "primary", "foreign", "unique")
        return nxt in kinds or after.lower() in kinds
    if first == "like":
        return bool(nxt) and nxt not in _TYPE_WORDS
    return False


_NEW_TABLE = re.compile(r"\bcreate\s+(?:or\s+replace\s+)?(?:(?:global\s+|local\s+)?(?:temp|temporary)\s+|transient\s+)?table\b", re.I)


def _end_of_statement(text: str, start: int, backslash: bool = False) -> Optional[int]:
    """The index of the first `;` at or after `start` that is outside quotes, or None."""
    i = start
    while i < len(text):
        j = _quoted_end(text, i, backslash)
        if j is not None:
            i = j
        elif text[i] == ";":
            return i
        else:
            i += 1
    return None


def parse_ddl(sql: str) -> tuple[Optional[str], list[dict]]:
    """The table name and columns of one `CREATE TABLE` statement.

    A small, documented subset: one table; `name type [(args)] [NOT NULL] [PRIMARY KEY] [DEFAULT ...]` per column;
    table constraints (`PRIMARY KEY`, `FOREIGN KEY`, `UNIQUE`, `CONSTRAINT`, `CHECK`, indexes) are skipped; `--` and
    `/* */` comments; identifiers quoted with `"x"`, `` `x` `` or `[x]` (`]]` is a literal `]`); a schema in front of the table's name is dropped;
    table options after the closing parenthesis (`ENGINE=...`, `PARTITION BY ...`) are ignored; a column may be named
    `key`, `index`, `check` ... when a type follows. A backslash in a string is a plain character, as in PostgreSQL and
    SQL Server (`'C:\\'` is a whole string); only when the statement does not read that way is it read again with MySQL's
    escapes (`'it\\'s'`), so a default value with an escaped quote parses.
    Anything else (a second table, `CREATE INDEX`, a column with no type, an unclosed parenthesis) is an error that
    names the line, never a guess."""
    try:
        return _parse_ddl(sql, False)
    except TemplateError as first:
        if "\\" not in sql:
            raise
        try:
            return _parse_ddl(sql, True)
        except TemplateError:
            raise first from None


def _parse_ddl(sql: str, backslash: bool) -> tuple[Optional[str], list[dict]]:
    text = _blank_comments(sql, backslash)
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
    depth, end, i = 0, None, pos
    while i < len(text):
        j = _quoted_end(text, i, backslash)
        if j is not None:
            i = j
            continue
        c = text[i]
        if c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                end = i
                break
        i += 1
    if end is None:
        raise TemplateError(f"line {_line(text, pos)}: unclosed parenthesis in CREATE TABLE")
    # Table options (ENGINE=..., PARTITION BY ..., WITH (...), TABLESPACE ...) may follow the closing parenthesis and
    # are ignored; a second CREATE TABLE, or any further statement after a `;`, is refused.
    stop = _end_of_statement(text, end + 1, backslash)
    options = text[end + 1:stop]
    second = _NEW_TABLE.search(options)
    if second:
        at = end + 1 + second.start()
        raise TemplateError(f"line {_line(text, at)}: only one table is supported, found a second table: "
                            f"{text[at:].strip().splitlines()[0][:40]!r}")
    if stop is not None and text[stop + 1:].strip():
        rest = text[stop + 1:]
        at = stop + 1 + (len(rest) - len(rest.lstrip()))
        what = "a second table" if _NEW_TABLE.match(rest.strip()) else "text after the table definition"
        raise TemplateError(f"line {_line(text, at)}: only one table is supported, found {what}: "
                            f"{rest.strip().splitlines()[0][:40]!r}")
    columns: list[dict] = []
    for item, at in _top_level_items(text[pos + 1:end], pos + 1, backslash):
        if not item.strip():
            continue
        lead = at + len(item) - len(item.lstrip())
        if _is_constraint(item):
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
        if col["name"].lower() in seen:
            raise TemplateError(f"{where}: column {col['name']!r} appears twice")
        seen.add(col["name"].lower())
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
