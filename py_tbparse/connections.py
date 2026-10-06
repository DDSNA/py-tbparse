"""Database connection classes, and the target files that describe a table in one.

Data first. Every entry of `CLASSES` is **copied from workbooks Tableau wrote** (`scripts/survey_connections.py` prints
what the corpus holds; `tests/test_targets.py` checks this table against it), and says so in `evidence`:

* `"corpus"`: measured in the 200-workbook example corpus (all four classes below);
* `"sample"`: measured in a workbook the owner supplied;
* `"docs"`: from documentation only. Such a class refuses to write unless `experimental=True`.

Within a class, a type's remote code is `measured` only if the corpus holds a column of that class and type; every
other code is copied from a sibling class and reported as unverified (`unverified_types`), because Tableau's reaction
to a wrong `remote-type` is not known. Nothing here is a credential: `username` and `password` are never written.
"""

from __future__ import annotations

import json
import re
import warnings
from dataclasses import dataclass, field as _field
from pathlib import Path
from typing import Optional

from .schema import _TABLEAU_TYPE, read_schema, sql_family, sql_to_tableau_type
from .templates import TemplateError

TARGET_FORMAT = "py-tbparse-target"
TARGET_VERSION = 1
_CREDENTIAL_KEYS = ("password", "username", "token", "secret")
_TARGET_KEYS = {"format", "version", "class", "server", "port", "dbname", "schema", "table", "warehouse",
                "authentication", "columns", "schema_file"}


@dataclass(frozen=True)
class RemoteType:
    remote: int          # Tableau's remote-type code
    debug: str = ""      # DebugRemoteType, when the class writes one for this type
    wire: str = ""       # DebugWireType
    measured: bool = True


@dataclass(frozen=True)
class ConnClass:
    name: str
    evidence: str
    attributes: dict                       # the named connection's attributes in Tableau's order; "$key" = from the target
    default_port: Optional[str] = None     # None: Tableau writes no `port` for this class
    authentication: tuple = ()             # the values seen in the corpus, the first is the default; () = no attribute
    schema: str = "forbidden"              # "required" or "forbidden": does the target name a schema?
    relation: tuple = ("table",)           # the parts of the relation's `table` attribute, each a target key
    needs: tuple = ()                      # target keys beyond server, dbname and table
    # family (see schema.sql_family) -> (remote code, DebugRemoteType, DebugWireType), measured in the corpus
    types: dict = _field(default_factory=dict)
    aliases: dict = _field(default_factory=dict)   # family -> family of this class's own (Snowflake: int = NUMBER(38,0))
    writes_debug: bool = True              # Tableau writes DebugRemoteType/DebugWireType for the class (Postgres: no)


CLASSES: dict[str, ConnClass] = {
    "mysql": ConnClass(
        "mysql", "corpus", default_port="3306", schema="forbidden",
        attributes={"class": "mysql", "dbname": "$dbname", "odbc-native-protocol": "", "one-time-sql": "",
                    "port": "$port", "server": "$server", "source-charset": ""},
        types={"tinyint": (16, "SQL_TINYINT", "SQL_C_STINYINT"), "smallint": (18, "SQL_SMALLINT", "SQL_C_USHORT"),
               "int": (3, "SQL_INTEGER", "SQL_C_SLONG"), "decimal": (131, "SQL_DECIMAL", "SQL_C_NUMERIC"),
               "wholenum": (131, "SQL_DECIMAL", "SQL_C_NUMERIC"), "float4": (4, "SQL_REAL", "SQL_C_FLOAT"),
               "double": (5, "SQL_DOUBLE", "SQL_C_DOUBLE"), "string": (130, "SQL_WVARCHAR", "SQL_C_WCHAR"),
               "text": (129, "SQL_LONGVARCHAR", "SQL_C_CHAR"), "date": (7, "SQL_TYPE_DATE", "SQL_C_TYPE_DATE")}),
    "postgres": ConnClass(
        "postgres", "corpus", default_port="5432", authentication=("username-password",), schema="required",
        relation=("schema", "table"), writes_debug=False,
        attributes={"authentication": "$authentication", "class": "postgres", "dbname": "$dbname", "one-time-sql": "",
                    "port": "$port", "server": "$server"},
        types={"int": (3, "", ""), "bigint": (20, "", ""), "string": (129, "", ""), "decimal": (131, "", ""),
               "date": (7, "", ""), "datetime": (135, "", ""), "boolean": (11, "", "")}),
    "sqlserver": ConnClass(
        "sqlserver", "corpus", authentication=("sspi",), schema="required", relation=("schema", "table"),
        attributes={"authentication": "$authentication", "class": "sqlserver", "dbname": "$dbname",
                    "odbc-native-protocol": "yes", "one-time-sql": "", "server": "$server"},
        types={"string": (130, "SQL_WVARCHAR", "SQL_C_WCHAR"), "bigint": (20, "SQL_BIGINT", "SQL_C_SBIGINT"),
               "datetime": (7, "SQL_TYPE_TIMESTAMP", "SQL_C_TYPE_TIMESTAMP"), "float4": (4, "SQL_REAL", "SQL_C_FLOAT")}),
    "snowflake": ConnClass(
        "snowflake", "corpus", authentication=("Username Password",), schema="required", needs=("warehouse",),
        relation=("dbname", "schema", "table"),
        attributes={"authentication": "$authentication", "class": "snowflake", "dbname": "$dbname",
                    "max-varchar-size": "", "odbc-connect-string-extras": "", "one-time-sql": "", "schema": "$schema",
                    "server": "$server", "service": "", "warehouse": "$warehouse"},
        types={"wholenum": (131, "SQL_DECIMAL", "SQL_C_NUMERIC"), "string": (129, "SQL_VARCHAR", "SQL_C_CHAR"),
               "date": (7, "SQL_TYPE_DATE", "SQL_C_TYPE_DATE"), "double": (5, "SQL_DOUBLE", "SQL_C_DOUBLE"),
               "datetime": (7, "SQL_TYPE_TIMESTAMP", "SQL_C_TYPE_TIMESTAMP")},
        aliases={"tinyint": "wholenum", "smallint": "wholenum", "int": "wholenum", "bigint": "wholenum"}),
}
# The order a class borrows an unmeasured type from; a class that writes no Debug* attributes passes none on.
_SIBLINGS = ("mysql", "snowflake", "sqlserver", "postgres")
_AGGREGATION = {"integer": "Sum", "real": "Sum", "date": "Year", "datetime": "Year", "string": "Count", "boolean": "Count"}


def class_names() -> list[str]:
    return sorted(CLASSES)


def remote_type(cls: str, sql_type: str) -> tuple[RemoteType, str, str]:
    """The remote type Tableau records for a SQL type in connection class `cls`, Tableau's local type, and the
    aggregation it gives that type. `measured` says whether the code was seen for this class and type in the
    corpus, or was borrowed from a sibling class (then it is unverified)."""
    conn = CLASSES[cls]
    family = sql_family(sql_type)
    if family == "other":
        family = "string"
    own = conn.aliases.get(family, family)
    local = _TABLEAU_TYPE[family]
    if own in conn.types:
        code, debug, wire = conn.types[own]
        return RemoteType(code, debug, wire, measured=own == family), local, _AGGREGATION[local]
    for fallback in (own, "string") if own == "text" else (own,):
        for sibling in _SIBLINGS:
            other = CLASSES[sibling]
            if sibling != cls and fallback in other.types:
                code, debug, wire = other.types[fallback]
                keep = conn.writes_debug and other.writes_debug
                return RemoteType(code, debug if keep else "", wire if keep else "", measured=False), local, _AGGREGATION[local]
    raise TemplateError(f"no remote type known for {sql_type!r} in class {cls}")   # unreachable: every family has one


def relation_table(cls: str, target: dict) -> str:
    """How the relation names the table, as the class writes it: `[table]` (MySQL), `[schema].[table]` (PostgreSQL,
    SQL Server) or `[database].[schema].[table]` (Snowflake); a `]` in a name is doubled."""
    return ".".join("[" + str(target[part]).replace("]", "]]") + "]" for part in CLASSES[cls].relation)


def connection_attributes(target: dict) -> dict:
    """The attributes of the named connection for a loaded target: exactly what Tableau writes for the class,
    never `username` or `password`."""
    conn = CLASSES[target["class"]]
    values = {"server": target["server"], "dbname": target["dbname"], "schema": target.get("schema", ""),
              "warehouse": target.get("warehouse", ""), "port": str(target.get("port") or conn.default_port or ""),
              "authentication": target.get("authentication") or (conn.authentication[0] if conn.authentication else "")}
    return {k: values[v[1:]] if v.startswith("$") else v for k, v in conn.attributes.items()}


# `user:password@host` in any string (a connection URL or a bare login); a guard against a pasted login, not a guarantee.
_LOGIN_IN_TEXT = re.compile(r"[^\s/@:]+:[^\s/@]+@")
_PLAIN_NAME = re.compile(r"[A-Za-z0-9_.-]+")


def _reject_credentials(node, path: str = "") -> None:
    """Refuse credential keys, and strings that look like `user:password@host`. The message names the key, never
    echoes the value."""
    if isinstance(node, dict):
        for key, value in node.items():
            if str(key).lower() in _CREDENTIAL_KEYS:
                raise TemplateError(f"a target file must not hold credentials, but has {path}{key!r}; "
                                    "Tableau asks for them when the workbook opens")
            _reject_credentials(value, f"{path}{key}.")
    elif isinstance(node, list):
        for i, item in enumerate(node):
            _reject_credentials(item, f"{path}{i}.")
    elif isinstance(node, str) and _LOGIN_IN_TEXT.search(node):
        raise TemplateError(f"a target file must not hold credentials, but the value of {path.rstrip('.') or 'a key'!r} "
                            "looks like user:password@host; Tableau asks for the login when the workbook opens")


def is_target_file(path: str) -> bool:
    """True if `path` is a JSON file with this module's `format` key (any other `.json` is not a target)."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return False
    return isinstance(data, dict) and data.get("format") == TARGET_FORMAT


def load_target(path: str, experimental: bool = False) -> dict:
    """Read and check a target file; return it with `columns` (name, SQL type, Tableau type) filled in from
    `columns` or from `schema_file` (a path relative to the target file: a CREATE TABLE or a JSON column list).

    Refuses, naming the problem: a file without `"format": "py-tbparse-target"`, credential keys or values that look
    like `user:password@host`, an unknown class (the known ones are listed), a class that is not verified against
    Tableau's own output unless `experimental`, missing or surplus keys for the class, an authentication value Tableau
    was not seen to write, a port outside 1-65535, control characters in a name, no columns or both kinds of column
    description."""
    p = Path(path)
    try:
        raw = json.loads(p.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as e:
        raise TemplateError(f"{p.name} is not valid JSON: {e}") from None
    return check_target(raw, p, experimental)


def check_target(raw, p: Path, experimental: bool = False) -> dict:
    """`load_target` for a target already read (or about to be written) as `raw`; `p` names it in messages and is
    what `schema_file` is relative to."""
    if not isinstance(raw, dict) or raw.get("format") != TARGET_FORMAT:
        raise TemplateError(f"{p.name} is not a target file (it needs \"format\": \"{TARGET_FORMAT}\")")
    version = raw.get("version", 1)
    if isinstance(version, bool) or not isinstance(version, int):
        raise TemplateError(f"{p.name}: \"version\" must be a whole number")
    if version > TARGET_VERSION:
        raise TemplateError(f"{p.name} was made by a newer py-tbparse (target v{raw['version']})")
    _reject_credentials(raw)
    if isinstance(raw.get("authentication"), str) and ":" in raw["authentication"]:
        raise TemplateError(f"{p.name}: \"authentication\" looks like a login (it has a colon); a target file must not "
                            "hold credentials, Tableau asks for them when the workbook opens")
    unknown = sorted(set(raw) - _TARGET_KEYS)
    if unknown:
        raise TemplateError(f"{p.name}: unknown key(s) {', '.join(unknown)}; a target has: {', '.join(sorted(_TARGET_KEYS))}")
    cls = raw.get("class")
    if cls not in CLASSES:
        raise TemplateError(f"{p.name}: unknown class {cls!r}; known classes: {', '.join(class_names())}")
    conn = CLASSES[cls]
    if conn.evidence == "docs" and not experimental:
        raise TemplateError(f"{p.name}: class {cls} is written from documentation only, never checked against a workbook "
                            "Tableau wrote; pass experimental=True (--experimental) to use it anyway")
    target = {k: v for k, v in raw.items() if k not in ("columns", "schema_file")}
    for key in ("server", "dbname", "table") + conn.needs + (("schema",) if conn.schema == "required" else ()):
        if not isinstance(raw.get(key), str) or not raw[key].strip():
            raise TemplateError(f"{p.name}: class {cls} needs \"{key}\"")
    for key in ("server", "dbname", "table", "schema", "warehouse"):
        if isinstance(raw.get(key), str) and any(ord(ch) < 32 or ord(ch) == 127 for ch in raw[key]):
            raise TemplateError(f"{p.name}: \"{key}\" holds a control character (a line break, tab or NUL)")
    if raw["table"] != raw["table"].strip():
        raise TemplateError(f"{p.name}: \"table\" has spaces at its start or end ({raw['table']!r}); "
                            "a table name written that way would not be found")
    if conn.schema == "forbidden" and raw.get("schema"):
        raise TemplateError(f"{p.name}: class {cls} has no schema (the database name is dbname); remove \"schema\"")
    if "warehouse" in raw and "warehouse" not in conn.needs:
        raise TemplateError(f"{p.name}: class {cls} has no warehouse")
    if conn.default_port is None and raw.get("port") not in (None, ""):
        raise TemplateError(f"{p.name}: Tableau writes no port for class {cls}; remove \"port\"")
    if raw.get("port") not in (None, ""):
        port = raw["port"]
        if isinstance(port, bool) or not isinstance(port, (int, str)) or not re.fullmatch(r"[0-9]{1,5}", str(port)) \
                or not 1 <= int(str(port)) <= 65535:
            raise TemplateError(f"{p.name}: port must be a number from 1 to 65535, got {port!r}")
        target["port"] = str(port)
    auth = raw.get("authentication")
    if auth is not None and auth not in conn.authentication:
        if not experimental:
            seen = ", ".join(repr(a) for a in conn.authentication) or "no authentication"
            raise TemplateError(f"{p.name}: authentication {auth!r} was not seen for class {cls} (Tableau wrote: {seen}); "
                                "pass experimental=True (--experimental) to write it anyway")
        if not isinstance(auth, str) or not _PLAIN_NAME.fullmatch(auth):
            raise TemplateError(f"{p.name}: authentication must be a plain name (letters, digits, '_', '.', '-')")
    ignored_auth = auth if auth is not None and not conn.authentication else None
    if ("columns" in raw) == ("schema_file" in raw):
        raise TemplateError(f"{p.name}: give the table's columns either as \"columns\" or as \"schema_file\", not both or neither")
    if "schema_file" in raw and (not isinstance(raw["schema_file"], str) or not raw["schema_file"].strip()):
        raise TemplateError(f"{p.name}: \"schema_file\" must be a path (text)")
    if "columns" in raw:
        schema = read_schema(raw["columns"])
    else:
        schema_path = Path(raw["schema_file"])
        schema = read_schema(str(schema_path if schema_path.is_absolute() else p.parent / schema_path))
    warned: list[str] = []
    if ignored_auth is not None:
        warned.append(f"authentication {ignored_auth!r} is not written: Tableau's {cls} connection has no authentication "
                      "attribute (none of the corpus's MySQL connections has one), so Tableau asks for the login")
    columns = []
    for col in schema.columns:
        tableau = sql_to_tableau_type(col["type"], warn=warned.append, column=col["name"])
        columns.append({"name": col["name"], "type": col["type"], "datatype": tableau})
    target["columns"] = columns
    unverified = sorted({c["type"] for c in columns if not remote_type(cls, c["type"])[0].measured})
    target["warnings"] = warned
    target["unverified_types"] = unverified
    return target


def warn_about(target: dict, path: str) -> None:
    """Tell the caller (as `UserWarning`s, which `apply-folder` collects into its summary) what is unverified."""
    for message in target.get("warnings", []):
        warnings.warn(f"{Path(path).name}: {message}", stacklevel=3)
    if target.get("unverified_types"):
        warnings.warn(f"{Path(path).name}: the remote type Tableau records for {', '.join(target['unverified_types'])} "
                      f"in class {target['class']} was not seen in Tableau's own output (copied from a sibling class); "
                      "not opened in Tableau", stacklevel=3)
