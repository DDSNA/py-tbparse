"""A small local-browser GUI for py_tbparse.

Built entirely on the standard library (`http.server` + vanilla JS) so it
adds no new dependencies and needs no display server / GUI toolkit —
just a browser, which makes it usable headless-server-side too (you can
curl its JSON endpoints). Run `py-tbparse-gui [workbook]` and it opens
http://127.0.0.1:<port>/ in your default browser.
"""

from __future__ import annotations

import argparse
import ipaddress
import json
import os
import atexit
import collections.abc
import secrets
import shutil
import signal
import socket
import re
import tempfile
import threading
import time
import warnings
import webbrowser
from pathlib import Path
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, quote, unquote, urlparse, urlsplit

import pandas as pd

from . import __version__, template_gui
from ._tables import TABLE_NAMES, TABLE_SPECS
from .dashboards import dashboard_targets
from .docgen import workbook_markdown
from .findings import SEVERITY, exceeds, rules as _audit_rules, format_findings, summary as findings_summary
from .parser import TwbParser
from .rename import (
    KINDS,
    _drop_parameters,
    build_renamed_workbook,
    default_renamed_path,
    select_renames,
    suggest_field_renames,
    suggest_renames,
)
from .workbook_audit import audit as run_audit, SCOPE as _AUDIT_SCOPE
from . import library as _library
from . import style as _style
from .templates import TemplateError, load_template, make_template, read_data

# "tpl" is the Templates view's state (see `_tpl_new`); it stays None until the view is used. Defaults are copied
# shallowly into each session, so every default must be immutable: a fresh dict is assigned on first use.
_STATE_DEFAULTS = {"parser": None, "path": None, "uploaded": False, "report": None, "audit": None, "lib": None, "sty": None, "cpy": None, "tpl": None}

# Server mode (`--server-mode`): the page is shared by several people behind a proxy, so each browser gets its
# own workbook state, keyed by a random cookie. `_STATE` and `_UPLOAD` below look like plain dicts but read and
# write the session of the request being handled (a thread-local); outside server mode, and outside a request,
# they are the single process-wide dicts the local GUI has always used.
_CONFIG: dict = {
    "server_mode": False,
    "allowed_hosts": frozenset(),
    "trust_proxy": False,
    "max_sessions": 20,
    "session_ttl": 3600,
}
_SESSION_COOKIE = "tbparse_sid"
_SESSIONS: dict = {}
_SESSIONS_LOCK = threading.Lock()
_CTX = threading.local()


class _Scoped(collections.abc.MutableMapping):
    def __init__(self, key: str, base: dict):
        self._key = key
        self.base = base

    def _target(self) -> dict:
        session = getattr(_CTX, "session", None)
        return self.base if session is None else session[self._key]

    def __getitem__(self, k):
        return self._target()[k]

    def __setitem__(self, k, v):
        self._target()[k] = v

    def __delitem__(self, k):
        del self._target()[k]

    def __iter__(self):
        return iter(self._target())

    def __len__(self):
        return len(self._target())


_STATE = _Scoped("state", dict(_STATE_DEFAULTS))

# An uploaded workbook (drag and drop, file picker) has no path the user can name, so it is written to a
# private temp directory, kept only until the next upload, the session ending or exit.
MAX_UPLOAD_BYTES = 200 * 1024 * 1024
MAX_DRAIN_BYTES = 32 * 1024 * 1024
_UPLOAD = _Scoped("upload", {"dir": None})


def _clear_upload() -> None:
    if _UPLOAD["dir"]:
        shutil.rmtree(_UPLOAD["dir"], ignore_errors=True)
        _UPLOAD["dir"] = None


def _drop_session(session: dict) -> None:
    if session["upload"]["dir"]:
        shutil.rmtree(session["upload"]["dir"], ignore_errors=True)
        session["upload"]["dir"] = None
    _drop_tpl(session["state"].get("tpl"))
    _cpy_drop(session["state"].get("cpy"))


def _clear_all_uploads() -> None:
    _clear_upload()
    _drop_tpl(_STATE.base.get("tpl"))
    _STATE.base["tpl"] = None
    _cpy_drop(_STATE.base.get("cpy"))
    _STATE.base["cpy"] = None
    with _SESSIONS_LOCK:
        for session in _SESSIONS.values():
            _drop_session(session)
        _SESSIONS.clear()


def _new_session() -> dict:
    # A new session starts from the preloaded workbook (if the operator gave one), never from another user's.
    base = _STATE.base
    return {
        "state": dict(_STATE_DEFAULTS, parser=base["parser"], path=base["path"]),
        "upload": {"dir": None},
        "seen": time.monotonic(),
    }


def _session_for(sid: str | None, create: bool):
    """The session for cookie value `sid`, or (when `create`) a new one. Returns (id, session, is_new);
    id and session are None when there is none. Expired sessions are dropped first, and when the table is
    full the least recently used one makes room."""
    now = time.monotonic()
    with _SESSIONS_LOCK:
        for old_id in [k for k, v in _SESSIONS.items() if now - v["seen"] > _CONFIG["session_ttl"]]:
            _drop_session(_SESSIONS.pop(old_id))
        session = _SESSIONS.get(sid) if sid else None
        if session is not None:
            session["seen"] = now
            return sid, session, False
        if not create:
            return None, None, False
        while len(_SESSIONS) >= _CONFIG["max_sessions"]:
            _drop_session(_SESSIONS.pop(min(_SESSIONS, key=lambda k: _SESSIONS[k]["seen"])))
        sid = secrets.token_urlsafe(24)
        _SESSIONS[sid] = session = _new_session()
        return sid, session, True


atexit.register(_clear_all_uploads)


# ---- the Templates view (/template/*) ----
# Each session has one template slot and one data slot, each file in its own folder inside a private temp
# directory, plus at most one output. The parsed Template and DataSource are kept, so a plan reads no file again.
# In server mode nothing in a JSON body is ever opened as a file: only the routes in _PATH_ROUTES take a path,
# and they are refused there.
MAX_JSON_BYTES = 1 * 1024 * 1024
_DISK_HEADROOM = 16 * 1024 * 1024  # small: a proxy's /tmp tmpfs can be 64 MB, and a 127 KB workbook must still upload
_TPL_CREATE_LOCK = threading.Lock()  # only makes creating a session's template state atomic; holds no user data
_WARN_LOCK = threading.Lock()  # `warnings.catch_warnings` is not thread safe; holds no user data

_UPLOAD_ROUTES = frozenset({"/upload", "/template/upload-template", "/template/upload-data"})
_UPLOAD_SLOTS = {"/upload": "workbook", "/template/upload-template": "template", "/template/upload-data": "data"}
_PATH_ROUTES = frozenset({"/load", "/create-workbook", "/template/open", "/template/open-data", "/template/save"})
_LIBRARY_KEYS = {
    "/library/export": frozenset({"datasource", "select", "with_dependencies", "include_parameters", "name", "description"}),
    "/library/plan": frozenset({"datasource", "on_clash", "offset", "limit"}),
    "/library/add": frozenset({"datasource", "on_clash"}),
    "/library/clear": frozenset(),
}
_STYLE_KEYS = {
    "/style/export": frozenset({"select", "format", "name"}),
    "/style/plan": frozenset({"on_clash", "offset", "limit"}),
    "/style/add": frozenset({"on_clash"}),
    "/style/clear": frozenset(),
}
_COPY_KEYS = {
    "/copy/slice-plan": frozenset({"dashboards", "strict", "prune", "offset", "limit"}),
    "/copy/slice-download": frozenset({"dashboards", "strict", "prune"}),
    "/copy/plan": frozenset({"sheets", "on_clash", "strict", "offset", "limit"}),
    "/copy/download": frozenset({"sheets", "on_clash", "strict"}),
    "/copy/clear": frozenset(),
}
_JSON_ROUTES = _PATH_ROUTES | frozenset(_LIBRARY_KEYS) | frozenset(_STYLE_KEYS) | frozenset(_COPY_KEYS) | frozenset({"/download-workbook", "/template/select-data", "/template/plan", "/template/apply", "/template/clear",
                                         "/template/make", "/template/use-made"})

_PLAN_KEYS = frozenset({"datasource", "mapping", "params", "tokens"})
# The only keys each route accepts. Anything else (path, output_path, answers, profile, data, ...) is refused by
# name: an answers file or profile would make the server read a file, and an output path would make it write one.
_TEMPLATE_KEYS = {
    "/template/open": frozenset({"path"}),
    "/template/open-data": frozenset({"path"}),
    "/template/select-data": frozenset({"sheet", "datasource"}),
    "/template/plan": _PLAN_KEYS | {"allow_missing"},   # so "create anyway" can show what it would do
    "/template/apply": _PLAN_KEYS | {"allow_missing", "data_path"},
    "/template/save": _PLAN_KEYS | {"allow_missing", "data_path"},
    "/template/clear": frozenset(),
    # make takes no path and no option that reads one: the file is named by the server, inside the session folder
    "/template/make": frozenset({"name", "description"}),
    "/template/use-made": frozenset(),
}
MAX_NAME = 120
MAX_DESCRIPTION = 2000
_DATA_EXTENSIONS = (".csv", ".tsv", ".txt", ".xlsx", ".xlsm", ".twb", ".twbx", ".tds")


def _tpl_new() -> dict:
    return {"dir": None, "lock": threading.Lock(), "dropped": False,
            "template": None, "template_label": None, "template_path": None, "template_uploaded": False,
            "template_summary": None,
            "data": None, "data_label": None, "data_path": None, "data_uploaded": False, "data_summary": None,
            "sheets": None, "datasources": None,
            "output": None, "output_name": None,
            "made": None, "made_name": None, "made_summary": None}


def _tpl_state(create: bool = False):
    """This session's template state; with `create`, made on first use (never by a GET)."""
    tpl = _STATE["tpl"]
    if tpl is None and create:
        with _TPL_CREATE_LOCK:
            tpl = _STATE["tpl"]
            if tpl is None:
                tpl = _STATE["tpl"] = _tpl_new()
    return tpl


def _tpl_dir(tpl: dict) -> str:
    """The session's private directory, made when first needed. Call with the state's lock held."""
    if tpl["dropped"]:
        raise OSError("this session has ended; reload the page")
    if tpl["dir"] is None or not os.path.isdir(tpl["dir"]):
        tpl["dir"] = tempfile.mkdtemp(prefix="py-tbparse-tpl-")
    return tpl["dir"]


def _tpl_reset(tpl: dict) -> None:
    """Forget both slots and the output and delete their files (the lock is kept)."""
    if tpl["dir"]:
        shutil.rmtree(tpl["dir"], ignore_errors=True)
    fresh = _tpl_new()
    del fresh["lock"], fresh["dropped"]
    tpl.update(fresh)


def _drop_tpl(tpl) -> None:
    """A session ends (expired, evicted, exit): delete its files. Not under the state's lock, so a running apply
    cannot hold up the session table; that apply then fails, and nothing new can be written for this session."""
    if tpl is None:
        return
    tpl["dropped"] = True
    if tpl["dir"]:
        shutil.rmtree(tpl["dir"], ignore_errors=True)
    tpl["dir"] = None


def _free_bytes(path: str) -> int:
    return shutil.disk_usage(path).free


def _path_forms(path: str) -> set:
    forms = {path, os.path.realpath(path), os.path.abspath(path)}
    return {f for f in forms | {Path(f).as_posix() for f in forms} if f and f not in (os.sep, "/")}


def _scrub(value, tpl=None, extra=()):
    """`value` with every server temp path replaced by a label: an uploaded file's path by its file name, the
    session's directory by `(upload)`, and in server mode the whole temp root by `(temp)`. Applied to every
    /template/ answer, so a message from deep inside the template API cannot name the server's disk."""
    pairs = list(extra)
    if tpl is not None:
        for slot in ("template", "data"):
            if tpl[slot + "_uploaded"] and tpl[slot + "_path"]:
                pairs.append((tpl[slot + "_path"], tpl[slot + "_label"]))
        if tpl["dir"]:
            pairs.append((tpl["dir"], "(upload)"))
    if _CONFIG["server_mode"]:
        pairs.append((tempfile.gettempdir(), "(temp)"))
    swaps = sorted({(form, label) for path, label in pairs if path for form in _path_forms(str(path))},
                   key=lambda p: -len(p[0]))
    if not swaps:
        return value

    def clean(v):
        if isinstance(v, str):
            for form, label in swaps:
                if form in v:
                    v = v.replace(form, label)
            return v
        if isinstance(v, dict):
            return {k: clean(x) for k, x in v.items()}
        if isinstance(v, (list, tuple)):
            return [clean(x) for x in v]
        return v

    return clean(value)


def _payload_problem(route: str, payload: dict):
    """Why this JSON body is refused, or None: an unknown key (named), or a value of the wrong type."""
    allowed = _TEMPLATE_KEYS[route]
    for key in sorted(payload, key=str):
        if key not in allowed:
            names = ", ".join(sorted(allowed)) or "none"
            return f"unknown key {key!r} (this request takes: {names})"

    def text_map(name, values_ok):
        v = payload.get(name)
        if v is None:
            return None
        if not isinstance(v, dict) or not all(isinstance(k, str) and values_ok(x) for k, x in v.items()):
            return f"{name!r} must be an object of names to values"
        return None

    for name in ("datasource", "sheet", "path", "name", "description"):
        if payload.get(name) is not None and not isinstance(payload[name], str):
            return f"{name!r} must be text"
    if len(payload.get("name") or "") > MAX_NAME:
        return f"'name' is longer than {MAX_NAME} characters"
    if any(ord(c) < 32 or ord(c) == 127 for c in payload.get("name") or ""):
        return "'name' must be one line of text"
    description = payload.get("description") or ""
    if len(description) > MAX_DESCRIPTION:
        return f"'description' is longer than {MAX_DESCRIPTION} characters"
    if any((ord(c) < 32 and c not in "\n\r\t") or ord(c) == 127 for c in description):
        return "'description' has a character that cannot be saved"
    problem = (text_map("mapping", lambda x: x is None or isinstance(x, str))
               or text_map("params", lambda x: isinstance(x, (str, int, float)))
               or text_map("tokens", lambda x: isinstance(x, str)))
    if problem:
        return problem
    if "allow_missing" in payload and not isinstance(payload["allow_missing"], bool):
        return "'allow_missing' must be true or false"
    data_path = payload.get("data_path")
    if data_path is not None:
        if not isinstance(data_path, str):
            return "'data_path' must be text"
        if len(data_path) > 1024:
            return "'data_path' is longer than 1024 characters"
        if any(c in data_path for c in "\x00\r\n"):
            return "'data_path' must be one line of text"
    return None


def _param_text(v) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    return str(v)


def _plan_args(payload: dict) -> dict:
    params = payload.get("params")
    return {"datasource": payload.get("datasource") or None,
            "mapping": payload.get("mapping") or None,
            "params": {k: _param_text(v) for k, v in params.items()} if params else None,
            "tokens": payload.get("tokens") or None}


def _read_data_slot(path: str, label: str, sheet=None, datasource=None):
    """(DataSource or None, its summary or None, {sheets, datasources}). A file with several sheets or
    datasources and no choice yet gives no DataSource: the page asks which one (`/template/select-data`)."""
    ext = os.path.splitext(path)[1].lower()
    choices = {"sheets": None, "datasources": None}
    if ext in (".xlsx", ".xlsm"):
        choices["sheets"] = template_gui.excel_sheets(path)
        if sheet is None and len(choices["sheets"]) > 1:
            return None, None, choices
    elif ext in (".twb", ".twbx", ".tds"):
        choices["datasources"] = template_gui.tableau_datasources(path)
        if datasource is None and len(choices["datasources"]) > 1:
            return None, None, choices
    elif ext not in (".csv", ".tsv", ".txt"):
        raise TemplateError(_upload_problem(label, b"", "data") or f"{label} cannot be used as data")
    data = read_data(path=path, sheet=sheet, datasource=datasource)
    if data.kind not in ("csv", "excel", "tableau"):
        raise TemplateError(f"{label} cannot be used as data in the GUI")
    return data, template_gui.data_summary(data, label=label), choices


def _template_file_name(name: str, source: str) -> str:
    """A safe file name for a made template: letters, digits, spaces, dots, dashes and underscores only, so
    the typed name can never be a path. With no usable name, the workbook's own name."""
    stem = re.sub(r"[^\w .\-]", "_", name or "").replace("..", "_").strip(" ._")[:80].strip(" ._")
    return (stem or Path(source).stem or "workbook") + ".template.twbx"


def _upload_problem(name: str, head: bytes, slot: str = "workbook") -> str | None:
    """Why these bytes are not a file named `name` for `slot` (`workbook`, `template` or `data`), or None. The
    extension and the content must agree, so a renamed .exe or a text file is refused before a parser sees it."""
    ext = os.path.splitext(name)[1].lower()
    is_zip = head[:2] == b"PK"
    is_xml = head.lstrip(b"\xef\xbb\xbf \t\r\n")[:1] == b"<"
    if slot == "template":
        if ext != ".twbx":
            return "A template is a .twbx file made with py-tbparse template make."
        return None if is_zip else "That file is not a template (a .twbx is a zip archive)."
    if slot == "data":
        if ext in (".csv", ".tsv", ".txt"):
            return None if b"\x00" not in head else "That file is not a text file (a .csv, .tsv or .txt has no NUL bytes)."
        if ext in (".xlsx", ".xlsm", ".twbx"):
            return None if is_zip else f"That file is not a zip archive, which a {ext} file is."
        if ext in (".twb", ".tds"):
            return None if is_xml else f"That file is not XML, which a {ext} file is."
        if ext == ".json":
            return "Database target files (.json) cannot be used in the GUI yet; use the command line."
        if ext in (".xls", ".xlsb"):
            return "Old-style Excel files (.xls, .xlsb) cannot be read; save the sheet as .xlsx or .csv."
        return "Data must be a " + ", ".join(_DATA_EXTENSIONS[:-1]) + " or " + _DATA_EXTENSIONS[-1] + " file."
    if ext == ".twbx":
        return None if is_zip else "That file is not a packaged workbook (a .twbx is a zip archive)."
    if ext == ".twb":
        return None if is_xml else "That file is not a Tableau workbook (a .twb is XML)."
    return "Only .twb and .twbx files can be opened."


def _df_to_html(df: pd.DataFrame) -> str:
    if df is None or df.empty:
        return "<p class='empty'>(empty)</p>"
    return df.to_html(index=False, na_rep="", classes="tbl", border=0, escape=True)


def _df_to_records(df: pd.DataFrame) -> dict:
    """Columns plus JSON-safe row lists (NaN/None -> null) for the page to
    render, sort and filter client-side."""
    split = json.loads(df.to_json(orient="split", index=False, default_handler=str))
    return {"columns": split["columns"], "data": split["data"]}


def _table_counts(parser: TwbParser) -> dict:
    """Row count per table, for the sidebar badges. A table whose extractor
    raises gets None instead of failing the whole load."""
    counts = {}
    for name, fn in TABLE_SPECS.items():
        try:
            counts[name] = int(len(fn(parser)))
        except Exception:
            counts[name] = None
    return counts


def _datasource_names(parser: TwbParser) -> list:
    df = parser.get_fields()
    if df.empty:
        return []
    names = _drop_parameters(df)["datasource"].dropna()
    return sorted(set(names))


def _datasource_labels(parser: TwbParser) -> dict:
    """Internal datasource name -> the caption people see in Tableau, only where one exists, so the
    page can show `Sales (Orders)` instead of `federated.1yoogmp19z69r21gvk5nd1r8nec2`."""
    labels = {}
    for ds in parser.xml_doc.xpath("/workbook/datasources/datasource[@name]"):
        caption = ds.get("caption")
        if caption:
            labels[ds.get("name")] = caption
    return labels


_REFERENCE_CACHE: dict = {}


def _reference_parser(path: str) -> TwbParser:
    """The reference workbook, re-parsed only when its file changes -- the
    page re-requests the table on every control change."""
    st = os.stat(path)  # FileNotFoundError propagates to the caller's 400
    key = (os.path.abspath(path), st.st_mtime_ns, st.st_size)
    hit = _REFERENCE_CACHE.get(key)
    if hit is None:
        _REFERENCE_CACHE.clear()  # keep one: a reference workbook can be large
        hit = _REFERENCE_CACHE[key] = TwbParser(path)
    return hit


def _rename_options(src: dict) -> dict:
    """Rename options from a query-string dict (values are lists) or a JSON
    body; the reference workbook path is loaded here, so a bad one raises
    ValueError/FileNotFoundError for the caller to report."""
    def one(key, default=None):
        v = src.get(key, default)
        return (v[0] if v else default) if isinstance(v, list) else v

    style = one("style") or "title"
    opts = {"style": style}
    ref_path = str(one("reference") or "").strip()
    if ref_path:
        try:
            opts["reference"] = _reference_parser(ref_path)
        except (FileNotFoundError, ValueError):
            raise
        except Exception as e:  # malformed XML, bad zip, permissions, etc.
            raise ValueError(f"failed to parse reference workbook: {e}") from e
    ds = one("datasource")
    if ds:
        opts["datasource"] = ds
    if one("kinds") == "all":  # the page offers fields only or everything, nothing in between
        opts["kinds"] = KINDS
    return opts


def _rename_exclude(src: dict):
    """The ids of the renames to leave out, from a query-string dict (repeated `exclude`) or a JSON body
    (a list). None when there are none. A malformed value raises ValueError."""
    value = src.get("exclude")
    if value is None:
        return None
    if not isinstance(value, list) or not all(isinstance(x, str) for x in value):
        raise ValueError("exclude must be a list of rename ids (strings)")
    return value


def _attachment(filename: str) -> str:
    """`Content-Disposition` value for a download. http.server encodes
    headers as latin-1 (a CJK workbook name would abort the response) and a
    `"` would end the quoted filename, so send an ASCII fallback plus the
    RFC 6266 `filename*` UTF-8 form."""
    fallback = "".join(c if 32 <= ord(c) < 127 and c not in '"\\' else "_" for c in filename)
    return f"attachment; filename=\"{fallback}\"; filename*=UTF-8''{quote(filename, safe='')}"


def _json_for_script(obj) -> str:
    """`json.dumps()` output safe to splice into an HTML `<script>` block.

    `json.dumps` doesn't escape `/`, so a loaded workbook path containing
    the literal text `</script>` would close the script tag early in the
    browser's HTML parser (parsed before any JS ever runs) and let
    arbitrary markup/script from that path follow it on the page.
    Escaping every solidus as `\\/` -- a legal JSON escape -- neutralizes
    any such closing-tag sequence regardless of case or which tag it
    targets, without changing the decoded value.
    """
    return json.dumps(obj).replace("/", "\\/")


_LOOPBACK_NAMES = {"localhost", "127.0.0.1", "::1"}
_WILDCARD_ADDRS = {"", "0.0.0.0", "::"}


def _is_ip_literal(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return False
    return True


def _host_allowed(host_header, server_address) -> bool:
    """Whether a request's `Host` header names this server.

    Defends against DNS rebinding: a page on attacker.example that
    re-resolves its own name to 127.0.0.1 becomes same-origin with this
    server in the browser's eyes, so it could read /table or /export --
    but its requests still carry `Host: attacker.example:<port>`.

    Allowed: loopback names or the bound address, with the bound port.
    When bound to a wildcard (0.0.0.0 / ::) the reachable address isn't
    knowable, so any IP-literal host is accepted instead -- an IP literal
    can't be the product of rebinding, only a DNS name can.
    """
    if not host_header:
        return False
    try:
        parts = urlsplit("//" + host_header.strip())
        hostname, port = parts.hostname, parts.port or 80
    except ValueError:
        return False
    if not hostname:
        return False
    # Names the operator listed (`--allowed-host`) are accepted on any port: behind a proxy the browser's
    # Host carries the public port (or none), not the one this process listens on.
    if hostname.lower() in _CONFIG["allowed_hosts"]:
        return True
    bound_host, bound_port = server_address[0], server_address[1]
    if port != bound_port:
        return False
    if hostname in _LOOPBACK_NAMES or hostname == str(bound_host).lower():
        return True
    return bound_host in _WILDCARD_ADDRS and _is_ip_literal(hostname)


def _origin_ok(origin, host) -> bool:
    """Whether a POST's `Origin` header (absent for non-browser clients) names this same host. Behind a
    TLS-terminating proxy (`--trust-proxy`) the browser's origin is https while the proxy forwards plain
    http, so the https form of the same Host is accepted too."""
    if origin is None:
        return True
    origin, host = origin.lower(), (host or "").strip().lower()
    if origin == "http://" + host:
        return True
    return _CONFIG["trust_proxy"] and origin == "https://" + host


# The page lives in real files under webui/ (index.html plus tokens.css, app.css and app.js),
# so it can be linted, diffed and tested like any other front-end code. Only these names are
# served under /static/, so a request can never reach another file.
_WEBUI = Path(__file__).parent / "webui"
_ASSETS = {
    "tokens.css": "text/css; charset=utf-8",
    "themes.css": "text/css; charset=utf-8",
    "app.css": "text/css; charset=utf-8",
    "app.js": "text/javascript; charset=utf-8",
    "table.js": "text/javascript; charset=utf-8",
    "graph.js": "text/javascript; charset=utf-8",
    "templates.js": "text/javascript; charset=utf-8",
    "rename.js": "text/javascript; charset=utf-8",
    "audit.js": "text/javascript; charset=utf-8",
    "libraries.js": "text/javascript; charset=utf-8",
    "styles.js": "text/javascript; charset=utf-8",
    "copy.js": "text/javascript; charset=utf-8",
}


def _read_webui(name: str) -> str:
    return (_WEBUI / name).read_text(encoding="utf-8")


THEMES = [
    "shop", "matcha", "fjord", "contrast",
    "harbor", "meadow", "lagoon", "slate", "graphite", "paper",
    "glacier", "pine", "olive", "citrus", "ocean", "cobalt",
    "navy", "midnight", "rose", "berry", "mint", "jade",
    "moss", "steel", "mono", "ink", "frost", "birch",
    "peacock", "marine", "canopy", "tide", "cornflower", "spruce",
]

# Runs in <head>, before anything is painted, so the page never shows the wrong colours first. It reads
# the saved theme and mode (the localStorage read can throw in a private window), resolves Auto against
# the system setting, and puts the result on <html>. app.js keeps Auto in step with the system afterwards.
_THEME_BOOT = (
    "(function(){var d=document.documentElement,t='shop',m='auto';"
    "try{t=localStorage.getItem('py-tbparse:theme')||t;m=localStorage.getItem('py-tbparse:mode')||m;}catch(e){}"
    "if(window.THEMES.indexOf(t)<0)t='shop';if(['auto','light','dark'].indexOf(m)<0)m='auto';"
    "d.dataset.theme=t;d.dataset.pref=m;"
    "d.dataset.mode=m==='auto'?(matchMedia('(prefers-color-scheme: dark)').matches?'dark':'light'):m;})();"
)


def _render_index() -> str:
    """index.html with the server-side values spliced in as one inline script.

    Every value goes through `_json_for_script()`: `json.dumps` leaves `/` alone, so a workbook
    path containing `</script>` would otherwise close the tag early (see
    `test_preload_path_cannot_break_out_of_script_tag`). This is the only inline script."""
    config = (
        "<script>\n"
        f"window.TABLE_NAMES = {_json_for_script(TABLE_NAMES)};\n"
        f"window.PRELOAD_PATH = {_json_for_script(None if _CONFIG['server_mode'] else _STATE['path'])};\n"
        f"window.SERVER_MODE = {_json_for_script(bool(_CONFIG['server_mode']))};\n"
        f"window.APP_VERSION = {_json_for_script(__version__)};\n"
        f"window.THEMES = {_json_for_script(THEMES)};\n"
        f"{_THEME_BOOT}\n"
        "</script>"
    )
    return _read_webui("index.html").replace("<!--APP_CONFIG-->", config)


def _open_response(parser: TwbParser, path: str, uploaded: bool = False, name: str | None = None) -> dict:
    """Make `parser` the loaded workbook and describe it for the page."""
    _STATE["parser"] = parser
    _STATE["path"] = path
    _STATE["uploaded"] = uploaded
    _STATE["report"] = None
    _STATE["audit"] = None
    _STATE["lib"] = None
    _STATE["sty"] = None
    _cpy_clear()
    dashboards_df = parser.get_dashboards()
    return {
        "ok": True,
        "path": None if uploaded else path,
        "name": name or os.path.basename(path),
        "uploaded": uploaded,
        "counts": _table_counts(parser),
        "datasources": _datasource_names(parser),
        "datasource_labels": _datasource_labels(parser),
        "dashboards": dashboards_df["name"].tolist() if "name" in dashboards_df.columns else [],
    }


# ---- the Audit view (/audit, /audit/export, /dictionary) ----
# The audit of the open workbook (`workbook_audit.audit`), run on request and kept for the last set of skipped
# rules, so paging and filtering do not run the rules again. The page only ever gets one page of rows
# (AUDIT_PAGE, at most AUDIT_PAGE_MAX); the download has them all. Nothing here takes a path.
AUDIT_PAGE = 100
AUDIT_PAGE_MAX = 500


def _audit_ids(qs: dict, key: str) -> list[str]:
    known = {r.id for r in _audit_rules(_AUDIT_SCOPE)}
    ids = [i.strip().upper() for part in (qs.get(key) or []) for i in part.split(",") if i.strip()]
    unknown = sorted(set(ids) - known)
    if unknown:
        raise ValueError(f"{key}: unknown rule {', '.join(unknown)}; known: {', '.join(sorted(known))}")
    return ids


def _audit_frame(qs: dict):
    """(all findings with the skipped rules left out, skipped ids); runs the rules unless the last run had the
    same skip set. Raises ValueError for an unknown rule or when everything is skipped."""
    skip = tuple(sorted(set(_audit_ids(qs, "skip"))))
    cached = _STATE["audit"]
    if cached is not None and cached[0] == skip:
        return cached[1], skip
    found = run_audit(_STATE["parser"], skip=skip)
    _STATE["audit"] = (skip, found)
    return found, skip


def _audit_filtered(found: pd.DataFrame, qs: dict) -> pd.DataFrame:
    severities = [v.strip().lower() for part in (qs.get("severity") or []) for v in part.split(",") if v.strip()]
    bad = sorted(set(severities) - set(SEVERITY))
    if bad:
        raise ValueError(f"severity: unknown {', '.join(bad)}; use {', '.join(SEVERITY)}")
    rules_ = _audit_ids(qs, "rule")
    if severities:
        found = found[found["severity"].isin(severities)]
    if rules_:
        found = found[found["rule"].isin(rules_)]
    text = (qs.get("q") or [""])[0].strip().lower()
    if text:
        hay = found[["rule", "severity", "object", "detail"]].astype(str).agg(" ".join, axis=1).str.lower()
        found = found[hay.str.contains(text, regex=False)]
    return found


def _audit_answer(qs: dict) -> dict:
    found, skip = _audit_frame(qs)
    counts = {sev: int((found["severity"] == sev).sum()) for sev in SEVERITY}
    crashed = list(found.attrs.get("crashed") or [])
    by_rule = {r: int(n) for r, n in found["rule"].value_counts().items()}
    shown = _audit_filtered(found, qs)
    try:
        offset = max(0, int((qs.get("offset") or ["0"])[0]))
        limit = min(AUDIT_PAGE_MAX, max(1, int((qs.get("limit") or [str(AUDIT_PAGE)])[0])))
    except ValueError:
        raise ValueError("offset and limit must be whole numbers")
    page = shown.iloc[offset:offset + limit]
    exit_code = 3 if crashed else (1 if exceeds(found, "error") else 0)
    return {
        "rules": [{"id": r.id, "severity": r.severity, "title": r.title, "count": by_rule.get(r.id, 0),
                   "skipped": r.id in skip} for r in _audit_rules(_AUDIT_SCOPE)],
        "skipped": list(skip),
        "total": int(len(found)),
        "counts": counts,
        "summary": findings_summary(found),
        "crashed": crashed,
        "exit_code": exit_code,
        "matching": int(len(shown)),
        "offset": offset,
        "limit": limit,
        "findings": page.to_dict(orient="records"),
    }


def _workbook_stem() -> str:
    name = os.path.basename(str(_STATE["path"] or "workbook"))
    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", os.path.splitext(name)[0]).strip("._") or "workbook"
    return stem[:80]


# ---- the Libraries view (/library/*) ----
# Lists the open workbook's calculated fields and parameters, exports a selection as a library file, and adds an
# uploaded library to the open workbook. The library is kept in memory (`_STATE["lib"]`, at most MAX_LIBRARY_BYTES
# of JSON) and the new workbook is only ever built as bytes and sent as a download: nothing here takes a path or
# writes a file, so it cannot touch the open workbook or any other file, and it is allowed in server mode.
LIBRARY_PAGE = 100
LIBRARY_PAGE_MAX = 100
MAX_LIBRARY_BYTES = 8 * 1024 * 1024
_FORMULA_SHOWN = 300


def _lib_state() -> dict:
    if _STATE["lib"] is None:
        _STATE["lib"] = {"library": None, "name": None, "entries": {}}
    return _STATE["lib"]


def _lib_datasource(value) -> str | None:
    if value in (None, ""):
        return None
    if not isinstance(value, str):
        raise ValueError("datasource must be text")
    return value


def _lib_source(parser: TwbParser, datasource: str | None) -> dict:
    """What the workbook can export from one datasource: the library of everything exportable (kept per
    datasource, so paging does not scan the workbook again) and the calculations that cannot be exported."""
    st = _lib_state()
    key = datasource or ""
    if key not in st["entries"]:
        report: dict = {}
        lib = _library.export_library(parser, datasource=datasource, report=report)
        st["entries"][key] = {"entries": lib["entries"], "unsupported": report.get("unsupported_names", []),
                              "auto": report.get("auto_names", []), "not_formula": report.get("not_formula_names", []),
                              "datasource": lib["source"]["datasource"], "caption": lib["source"]["datasource_caption"]}
    return st["entries"][key]


def _library_datasources(parser: TwbParser) -> list:
    return [{"name": n, "caption": c, "has_connection": conn} for n, c, conn in _library.datasource_choices(parser)]


def _library_entries_answer(qs: dict) -> dict:
    parser = _STATE["parser"]
    choices = _library_datasources(parser)
    ds = _lib_datasource((qs.get("datasource") or [""])[0])
    if ds is None and sum(1 for c in choices if c["has_connection"]) > 1:
        # several datasources: the page must choose one (the CLI asks the same)
        return {"datasources": choices, "datasource": None, "needs_datasource": True, "entries": [], "matching": 0,
                "total": 0, "offset": 0, "limit": LIBRARY_PAGE, "unsupported": [], "names": [],
                "auto": [], "auto_count": 0, "not_formula": [], "not_formula_count": 0}
    src = _lib_source(parser, ds)
    kind = (qs.get("kind") or [""])[0]
    if kind not in ("", "calc", "parameter"):
        raise ValueError("kind: use calc or parameter")
    text = (qs.get("q") or [""])[0].strip().lower()
    rows = src["entries"]
    if kind:
        rows = [e for e in rows if e["kind"] == kind]
    if text:
        rows = [e for e in rows if text in " ".join(str(e.get(k) or "") for k in ("caption", "name", "formula", "folder")).lower()]
    try:
        offset = max(0, int((qs.get("offset") or ["0"])[0]))
        limit = min(LIBRARY_PAGE_MAX, max(1, int((qs.get("limit") or [str(LIBRARY_PAGE)])[0])))
    except ValueError:
        raise ValueError("offset and limit must be whole numbers")
    page = [{
        "name": e["name"], "caption": e.get("caption") or e["name"].strip("[]"), "kind": e["kind"],
        "datatype": e.get("datatype") or "", "folder": e.get("folder") or "",
        "formula": (e.get("formula") or "")[:_FORMULA_SHOWN], "truncated": len(e.get("formula") or "") > _FORMULA_SHOWN,
    } for e in rows[offset:offset + limit]]
    return {
        "datasources": choices, "datasource": src["datasource"], "needs_datasource": False,
        "total": len(src["entries"]), "matching": len(rows), "offset": offset, "limit": limit, "entries": page,
        "unsupported": src["unsupported"][:50], "unsupported_count": len(src["unsupported"]),
        # calculations never listed, so the page can say why the sidebar counts more than it shows
        "auto": src["auto"][:50], "auto_count": len(src["auto"]),
        "not_formula": src["not_formula"][:50], "not_formula_count": len(src["not_formula"]),
        # every matching internal name, for "select all that match" (names only, a few bytes each)
        "names": [e["name"] for e in rows] if (qs.get("names") or [""])[0] == "1" else [],
    }


def _library_json(library: dict) -> str:
    return json.dumps(library, indent=2, ensure_ascii=False, sort_keys=True) + "\n"


def _library_filename(name: str) -> str:
    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", name or "").strip("._") or "library"
    return stem[:80] + ".library.json"


def _library_export(payload: dict) -> tuple[str, str]:
    parser = _STATE["parser"]
    select = payload.get("select")
    if not isinstance(select, list) or not all(isinstance(x, str) for x in select) or not select:
        raise ValueError("Tick at least one calculation or parameter to export.")
    if len(select) > 50_000:
        raise ValueError("Too many items selected.")
    name = payload.get("name") or ""
    description = payload.get("description") or ""
    if not isinstance(name, str) or not isinstance(description, str):
        raise ValueError("name and description must be text")
    if len(name) > MAX_NAME:
        raise ValueError(f"'name' is longer than {MAX_NAME} characters")
    if len(description) > MAX_DESCRIPTION:
        raise ValueError(f"'description' is longer than {MAX_DESCRIPTION} characters")
    lib = _library.export_library(
        parser, datasource=_lib_datasource(payload.get("datasource")), select=select,
        with_dependencies=payload.get("with_dependencies", True) is not False,
        include_parameters=True, name=name or None, description=description or None)
    return _library_json(lib), _library_filename(lib["name"])


def _library_upload_ok(raw: bytes, name: str) -> dict:
    try:
        lib = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        raise ValueError(f"{name} is not a library file ({e})")
    if not isinstance(lib, dict) or lib.get("format") != _library.FORMAT:
        raise ValueError(f"{name} is not a py-tbparse library (it has no format \"{_library.FORMAT}\")")
    if not isinstance(lib.get("version"), int) or lib["version"] > _library.VERSION:
        raise ValueError(f"{name}: library version {lib.get('version')!r} is newer than this py-tbparse reads ({_library.VERSION})")
    for key in ("entries", "required"):
        if not isinstance(lib.get(key), list):
            raise ValueError(f"{name}: the library has no {key!r} list")
    return lib


def _library_summary(lib: dict, name: str) -> dict:
    kinds = [e.get("kind") for e in lib["entries"] if isinstance(e, dict)]
    src = lib.get("source") if isinstance(lib.get("source"), dict) else {}
    return {
        "file": name, "name": str(lib.get("name") or ""), "description": str(lib.get("description") or "")[:MAX_DESCRIPTION],
        "calcs": kinds.count("calc"), "parameters": kinds.count("parameter"), "required": len(lib["required"]),
        "source_workbook": str(src.get("workbook") or ""), "created": str(lib.get("created") or ""),
    }


def _library_loaded() -> dict:
    st = _lib_state()
    if st["library"] is None:
        raise ValueError("Add a library file first.")
    return st["library"]


def _library_plan(payload: dict) -> dict:
    parser = _STATE["parser"]
    lib = _library_loaded()
    ds = _lib_datasource(payload.get("datasource"))
    policy = payload.get("on_clash", "fail")
    if policy not in _library.CLASH_POLICIES:
        raise ValueError(f"on_clash: use {', '.join(_library.CLASH_POLICIES)}")
    blocked = None
    try:
        plan = _library.plan_import(parser, lib, datasource=ds, on_clash=policy)
    except _library.LibraryError as e:
        if policy != "fail":
            raise
        # `fail` stops at the first clash. Show every clash (as `rename` would plan them) so the report is whole.
        plan = _library.plan_import(parser, lib, datasource=ds, on_clash="rename")
        if not (plan["action"] == "add-renamed").any():
            raise e
        blocked = str(e)
    try:
        offset = max(0, int(payload.get("offset", 0)))
        limit = min(LIBRARY_PAGE_MAX, max(1, int(payload.get("limit", LIBRARY_PAGE))))
    except (TypeError, ValueError):
        raise ValueError("offset and limit must be whole numbers")
    clash_actions = ("add-renamed", "skip-clash")
    clashes = plan[plan["action"].isin(clash_actions)]
    counts = {a: int(n) for a, n in plan["action"].value_counts().items()}
    rows = plan.iloc[offset:offset + limit].fillna("").to_dict(orient="records")
    return {
        "policy": policy, "blocked": blocked, "counts": counts, "total": int(len(plan)),
        "clashes": clashes.head(LIBRARY_PAGE_MAX).fillna("").to_dict(orient="records"), "clash_count": int(len(clashes)),
        "offset": offset, "limit": limit, "rows": rows,
        "will_add": 0 if blocked else int(plan["action"].isin(["add", "add-renamed"]).sum()),
    }


def _library_add(payload: dict) -> tuple[bytes, str, dict]:
    """The open workbook plus the library, as bytes (never written to disk here)."""
    parser = _STATE["parser"]
    lib = _library_loaded()
    policy = payload.get("on_clash", "fail")
    if policy not in _library.CLASH_POLICIES:
        raise ValueError(f"on_clash: use {', '.join(_library.CLASH_POLICIES)}")
    report: dict = {}
    data = _library.build_imported_workbook(parser, lib, datasource=_lib_datasource(payload.get("datasource")),
                                            on_clash=policy, report=report)
    ext = os.path.splitext(str(parser.twbx_path or parser.path))[1] or ".twb"
    return data, f"{_workbook_stem()}_library{ext}", report


# ---- the Styles view (/style/*) ----
# Lists the open workbook's custom colour palettes, exports a selection as a style file or a Preferences.tps, and
# adds the palettes of an uploaded file to the open workbook. The uploaded file is kept in memory
# (`_STATE["sty"]`, at most MAX_STYLE_BYTES) and everything sent back is built as bytes: nothing here takes a path or
# writes a file, so it can touch neither the open workbook nor a real Preferences.tps, and it works in server mode.
STYLE_PAGE = 100
MAX_STYLE_BYTES = 2 * 1024 * 1024
_CHIPS_SHOWN = 40


def _sty_state() -> dict:
    if _STATE["sty"] is None:
        _STATE["sty"] = {"records": None, "summary": None}
    return _STATE["sty"]


def _sty_page(qs_or_payload, get) -> tuple[int, int]:
    try:
        offset = max(0, int(get("offset", 0)))
        limit = min(STYLE_PAGE, max(1, int(get("limit", STYLE_PAGE))))
    except (TypeError, ValueError):
        raise ValueError("offset and limit must be whole numbers")
    return offset, limit


def _sty_row(r: dict) -> dict:
    colors = r.get("colors") if isinstance(r.get("colors"), list) else []
    return {"name": r.get("name") or "", "type": r.get("type") or "", "n_colors": len(colors),
            "colors": [str(c) for c in colors[:_CHIPS_SHOWN]], "status": r["status"], "reason": r.get("reason") or ""}


def _style_palettes_answer(qs: dict) -> dict:
    records = [r for r in _style.palette_records(_STATE["parser"]) if not r.get("_skip")]
    text = (qs.get("q") or [""])[0].strip().lower()
    rows = [r for r in records if text in (r.get("name") or "").lower()] if text else records
    offset, limit = _sty_page(qs, lambda k, d: (qs.get(k) or [d])[0])
    problems = _style.palette_problems(_style.palette_records(_STATE["parser"]))
    if not records:
        problems = []          # a workbook without palettes is normal; the "none found" line is for a .tps
    return {
        "total": len(records), "matching": len(rows), "offset": offset, "limit": limit,
        "rows": [_sty_row(r) for r in rows[offset:offset + limit]],
        # names that can be exported (valid palettes) for "select all that match"
        "names": [r["name"] for r in rows if r["status"] in ("ok", "warning")] if (qs.get("names") or [""])[0] == "1" else [],
        "problems": problems[:100], "problem_count": len(problems),
    }


def _style_filename(name: str, fmt: str) -> str:
    if fmt == "tps":
        return "Preferences_palettes.tps"
    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", name or "").strip("._") or "palettes"
    return stem[:80] + ".style.json"


def _style_export(payload: dict) -> tuple[bytes, str]:
    select = payload.get("select")
    if not isinstance(select, list) or not all(isinstance(x, str) for x in select) or not select:
        raise ValueError("Tick at least one palette to export.")
    if len(select) > 50_000:
        raise ValueError("Too many palettes selected.")
    fmt = payload.get("format", "style")
    if fmt not in ("style", "tps"):
        raise ValueError("format: use style or tps")
    name = payload.get("name") or ""
    if not isinstance(name, str):
        raise ValueError("name must be text")
    if len(name) > MAX_NAME:
        raise ValueError(f"'name' is longer than {MAX_NAME} characters")
    data = _style.build_export([_STATE["parser"]], "tps" if fmt == "tps" else "json", select=select, name=name or None)
    return data, _style_filename(name or _workbook_stem(), fmt)


def _style_loaded() -> list:
    st = _sty_state()
    if st["records"] is None:
        raise ValueError("Add a palette file first.")
    return st["records"]


def _style_policy(payload: dict) -> str:
    policy = payload.get("on_clash", "fail")
    if policy not in _style.CLASH_POLICIES:
        raise ValueError(f"on_clash: use {', '.join(_style.CLASH_POLICIES)}")
    return policy


def _style_plan(payload: dict) -> dict:
    records = _style_loaded()
    policy = _style_policy(payload)
    plan = _style.plan_palette_import(_STATE["parser"], records, on_clash=policy)
    offset, limit = _sty_page(payload, payload.get)
    counts = {a: int(n) for a, n in plan["action"].value_counts().items()}
    colors = {r["name"]: r["colors"] for r in records if isinstance(r.get("colors"), list)}
    rows = plan.iloc[offset:offset + limit].fillna("").to_dict(orient="records")
    for r in rows:
        r["colors"] = [str(c) for c in colors.get(r["name"], [])[:_CHIPS_SHOWN]]
    clashes = plan[plan["action"].isin(["fail", "skip", "rename", "replace"])]
    blocked = bool(counts.get("fail"))
    return {
        "policy": policy, "blocked": blocked, "counts": counts, "total": int(len(plan)), "offset": offset, "limit": limit,
        "rows": rows, "clash_count": int(len(clashes)),
        "clashes": clashes.head(STYLE_PAGE).fillna("").to_dict(orient="records"),
        "will_add": 0 if blocked else int(plan["action"].isin(["add", "rename", "replace"]).sum()),
    }


def _style_add(payload: dict) -> tuple[bytes, str, dict]:
    parser = _STATE["parser"]
    records = _style_loaded()
    report: dict = {}
    data = _style.build_with_palettes(parser, records, on_clash=_style_policy(payload), report=report)
    ext = os.path.splitext(str(parser.twbx_path or parser.path))[1] or ".twb"
    return data, f"{_workbook_stem()}_palettes{ext}", report


# ---- the Copy view (/copy/*) ----
# Slice (keep chosen dashboards of the open workbook) and sheet copy (copy chosen worksheets of the open workbook
# into an uploaded target workbook). Both call the library functions (`slice_workbook`, `plan_sheet_copy`,
# `build_sheet_copy`) and send the result as a download: no endpoint takes a path or writes next to a workbook, so
# it works in server mode. The target workbook is parsed from a private temp folder (a .twbx has to be read again
# when the result is made), kept for this session and deleted when it is replaced, cleared or the session ends.
# There is no overwrite policy: the clash policy is fail (default), rename or skip.
COPY_PAGE = 100
_COPY_POLICIES = ("fail", "rename", "skip")
_COPY_MAX_PICK = 50_000


def _cpy_drop(cpy) -> None:
    if cpy and cpy.get("dir"):
        shutil.rmtree(cpy["dir"], ignore_errors=True)
        cpy["dir"] = None


def _cpy_clear() -> None:
    _cpy_drop(_STATE["cpy"])
    _STATE["cpy"] = None


def _cpy_page(get) -> tuple[int, int]:
    try:
        offset = max(0, int(get("offset", 0)))
        limit = min(COPY_PAGE, max(1, int(get("limit", COPY_PAGE))))
    except (TypeError, ValueError):
        raise ValueError("offset and limit must be whole numbers")
    return offset, limit


def _cpy_names(payload: dict, key: str) -> list:
    names = payload.get(key)
    if (not isinstance(names, list) or not names or not all(isinstance(x, str) for x in names)):
        raise ValueError("Tick at least one dashboard." if key == "dashboards" else "Tick at least one worksheet.")
    if len(names) > _COPY_MAX_PICK:
        raise ValueError("Too many items selected.")
    return list(dict.fromkeys(names))


def _cpy_flag(payload: dict, key: str, default: bool) -> bool:
    v = payload.get(key, default)
    if not isinstance(v, bool):
        raise ValueError(f"{key} must be true or false")
    return v


def _cpy_dashboards_answer(qs: dict) -> dict:
    doc = _STATE["parser"].xml_doc
    sheets = set(doc.xpath("/workbook/worksheets/worksheet/@name"))
    text = (qs.get("q") or [""])[0].strip().lower()
    els = doc.xpath("/workbook/dashboards/dashboard[@name]")
    rows = [e for e in els if text in e.get("name").lower()] if text else els
    offset, limit = _cpy_page(lambda k, d: (qs.get(k) or [d])[0])
    out = []
    for e in rows[offset:offset + limit]:
        # same zones as the Dashboards table: a sheet zone names its sheet in @worksheet or, in some files, @name
        shown = ({n for n in dashboard_targets(e) if n in sheets}
                 | {n for n in e.xpath(".//@sheet") if n in sheets})
        out.append({"name": e.get("name"), "kind": "story" if e.get("type") == "storyboard" else "dashboard",
                    "n_sheets": len(shown)})
    names = [e.get("name") for e in rows] if (qs.get("names") or [""])[0] == "1" else []
    return {"total": len(els), "matching": len(rows), "offset": offset, "limit": limit, "rows": out, "names": names}


def _cpy_sheets_answer(qs: dict) -> dict:
    from .sheetcopy_core import sheet_datasources
    doc = _STATE["parser"].xml_doc
    text = (qs.get("q") or [""])[0].strip().lower()
    els = doc.xpath("/workbook/worksheets/worksheet[@name]")
    rows = [e for e in els if text in e.get("name").lower()] if text else els
    offset, limit = _cpy_page(lambda k, d: (qs.get(k) or [d])[0])
    out = [{"name": e.get("name"), "datasources": sheet_datasources(doc, e.get("name"))}
           for e in rows[offset:offset + limit]]
    names = [e.get("name") for e in rows] if (qs.get("names") or [""])[0] == "1" else []
    return {"total": len(els), "matching": len(rows), "offset": offset, "limit": limit, "rows": out, "names": names}


def _cpy_ext(parser: TwbParser) -> str:
    return os.path.splitext(str(parser.twbx_path or parser.path))[1] or ".twb"


def _cpy_slice_report(payload: dict, write: bool):
    """`(report, bytes or None)` of the library's `slice_workbook`; a write goes to a private temp folder and is read back."""
    from .slicer import slice_workbook
    names = _cpy_names(payload, "dashboards")
    strict, prune = _cpy_flag(payload, "strict", False), _cpy_flag(payload, "prune", True)
    parser = _STATE["parser"]
    if not write:
        return slice_workbook(parser, names, None, strict=strict, prune=prune), None
    with tempfile.TemporaryDirectory(prefix="py-tbparse-slice-") as folder:
        out = os.path.join(folder, "sliced" + _cpy_ext(parser))
        report = slice_workbook(parser, names, out, strict=strict, prune=prune)
        with open(out, "rb") as fh:
            return report, fh.read()


def _cpy_slice_plan(payload: dict) -> dict:
    from .slicer import SliceError
    offset, limit = _cpy_page(payload.get)
    try:
        r, _ = _cpy_slice_report(payload, False)
    except SliceError as e:
        return {"error": str(e)}
    rows = ([{"kind": "Dashboard", "name": n, "action": "keep", "why": ""} for n in r["kept_dashboards"]]
            + [{"kind": "Worksheet", "name": n, "action": "keep", "why": ""} for n in r["kept_sheets"]]
            + [{"kind": "Dashboard", "name": n, "action": "remove", "why": ""} for n in r["removed_dashboards"]]
            + [{"kind": "Worksheet", "name": n, "action": "remove", "why": ""} for n in r["removed_sheets"]])
    actions = ([{"caption": a["caption"], "action": "drop", "why": a["reason"]} for a in r["dropped_actions"]]
               + [{"caption": a["caption"], "action": "trim", "why": a["reason"]} for a in r["trimmed_actions"]])
    prune = (r["prune"] or {}).get("counts") or {}
    return {
        "kept_dashboards": len(r["kept_dashboards"]), "kept_sheets": len(r["kept_sheets"]),
        "removed_dashboards": len(r["removed_dashboards"]), "removed_sheets": len(r["removed_sheets"]),
        "total": len(rows), "offset": offset, "limit": limit, "rows": rows[offset:offset + limit],
        "action_count": len(actions), "actions": actions[:COPY_PAGE], "dropped_filters": r["dropped_filters"],
        "pruned": {k: int(prune.get(k, 0)) for k in ("calculations", "parameters", "sheets", "datasources")},
        "integrity": [f"{p['check']}: {p['detail']}" for p in r["integrity_new"]][:COPY_PAGE],
        "integrity_count": len(r["integrity_new"]),
    }


def _cpy_slice_download(payload: dict) -> tuple[bytes, str, dict]:
    report, data = _cpy_slice_report(payload, True)
    return data, f"{_workbook_stem()}_sliced{_cpy_ext(_STATE['parser'])}", report


def _cpy_target():
    cpy = _STATE["cpy"]
    if not cpy or not cpy.get("parser") or not cpy.get("dir"):
        raise ValueError("Choose the target workbook first.")
    return cpy


def _cpy_policy(payload: dict) -> str:
    policy = payload.get("on_clash", "fail")
    if policy not in _COPY_POLICIES:
        raise ValueError(f"on_clash: use {', '.join(_COPY_POLICIES)}")
    return policy


def _cpy_scrub(text: str) -> str:
    """A message from the planner without the server's file names: the open workbook and the target by label."""
    cpy = _STATE["cpy"] or {}
    for path, label in ((str(_STATE["path"] or ""), "the open workbook"),
                        (str((cpy.get("parser") and (cpy["parser"].twbx_path or cpy["parser"].path)) or ""), "the target")):
        if path:
            text = text.replace(path, label)
    return text


def _cpy_copy_plan(payload: dict) -> dict:
    from .sheetcopy import SheetCopyAbort, SheetCopyError, plan_sheet_copy
    cpy = _cpy_target()
    sheets, policy = _cpy_names(payload, "sheets"), _cpy_policy(payload)
    strict = _cpy_flag(payload, "strict", False)
    offset, limit = _cpy_page(payload.get)
    blocked = ""
    try:
        rep = plan_sheet_copy(_STATE["parser"], cpy["parser"], sheets, policy, strict)
    except SheetCopyAbort as e:
        blocked = _cpy_scrub(str(e))
        try:
            # list every sheet and library row anyway, as the plan of `library add` does for a clash
            rep = plan_sheet_copy(_STATE["parser"], cpy["parser"], sheets, "rename" if policy == "fail" else policy, False)
        except SheetCopyError:
            return {"error": blocked}
    rows = [{"sheet": r["sheet"], "new_name": r["new_name"], "status": r["status"], "datasource": r["datasource"],
             "reason": _cpy_scrub(r["reason"]), "dropped": r["dropped"]} for r in rep["sheets"]]
    def text(v):
        return "" if v is None or (isinstance(v, float) and v != v) else str(v)

    lib = [{"kind": text(r["kind"]), "name": text(r["name"]), "caption": text(r["caption"]), "action": text(r["action"]),
            "reason": text(r["reason"]), "datasource": text(r["datasource"])} for r in rep["library"]]
    return {
        "policy": policy, "blocked": bool(blocked), "blocked_reason": blocked,
        "copied": rep["copied"], "skipped": rep["skipped"], "refused": rep["refused"],
        "total": len(rows), "offset": offset, "limit": limit, "rows": rows[offset:offset + limit],
        "library_count": len(lib), "library": lib[:COPY_PAGE],
        "will_copy": 0 if blocked else rep["copied"],
    }


def _cpy_copy_download(payload: dict) -> tuple[bytes, str, dict]:
    from .sheetcopy import SheetCopyAbort, build_sheet_copy
    cpy = _cpy_target()
    sheets, policy = _cpy_names(payload, "sheets"), _cpy_policy(payload)
    strict = _cpy_flag(payload, "strict", False)
    try:
        data, report = build_sheet_copy(_STATE["parser"], cpy["parser"], sheets, policy, strict)
    except SheetCopyAbort as e:
        raise ValueError(_cpy_scrub(str(e))) from e
    if not report["copied"]:
        raise ValueError("No sheet can be copied with these choices, so nothing was made.")
    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", os.path.splitext(cpy["name"])[0]).strip("._") or "target"
    return data, f"{stem[:80]}_sheetcopy{_cpy_ext(cpy['parser'])}", report


class Handler(BaseHTTPRequestHandler):
    server_version = "py-tbparse-gui/0.1"

    def log_message(self, fmt, *args):  # quiet the default stderr access log
        pass

    def _send(self, code: int, body, ctype: str = "text/html; charset=utf-8", headers=None):
        data = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        if getattr(self, "_new_sid", None):
            secure = "; Secure" if self.headers.get("X-Forwarded-Proto", "").lower() == "https" and _CONFIG["trust_proxy"] else ""
            self.send_header(
                "Set-Cookie",
                f"{_SESSION_COOKIE}={self._new_sid}; Path=/; HttpOnly; SameSite=Strict; Max-Age={_CONFIG['session_ttl']}{secure}",
            )
            self._new_sid = None
        self.end_headers()
        self.wfile.write(data)

    def _send_json(self, obj, code: int = 200):
        self._send(code, json.dumps(obj), "application/json; charset=utf-8")

    def _table_df(self, qs: dict):
        name = (qs.get("name") or [""])[0]
        if name not in TABLE_SPECS:
            return None, name
        dashboard = (qs.get("dashboard") or [None])[0] or None
        include_parameters = (qs.get("include_parameters") or ["false"])[0] == "true"
        extra = {}
        if name == "field-renames":
            extra = _rename_options(qs)
            extra["only_changed"] = (qs.get("only_changed") or ["false"])[0] == "true"
        df = TABLE_SPECS[name](
            _STATE["parser"], dashboard=dashboard, include_parameters=include_parameters, **extra
        )
        return df, name

    def _reject_foreign_host(self) -> bool:
        if _host_allowed(self.headers.get("Host"), self.server.server_address):
            return False
        self._send(403, "forbidden: unrecognized Host header", "text/plain")
        return True

    def _bind_session(self) -> None:
        """Point `_STATE`/`_UPLOAD` at this request's session (server mode only). A session is created only
        for the page itself and for POSTs, and only for an accepted Host, so health checks, static files and
        foreign requests cannot fill the table."""
        _CTX.session = None
        self._new_sid = None
        if not _CONFIG["server_mode"]:
            return
        jar = SimpleCookie()
        try:
            jar.load(self.headers.get("Cookie") or "")
        except Exception:
            jar = SimpleCookie()
        morsel = jar.get(_SESSION_COOKIE)
        create = (
            self.command == "POST" or urlparse(self.path).path == "/"
        ) and _host_allowed(self.headers.get("Host"), self.server.server_address)
        sid, session, is_new = _session_for(morsel.value if morsel else None, create)
        if session is None:
            session = _new_session()  # unregistered: reads see the preload or nothing, writes are dropped
        elif is_new:
            self._new_sid = sid
        _CTX.session = session

    def do_GET(self):  # noqa: N802 (stdlib method name)
        self._bind_session()
        try:
            self._do_get()
        finally:
            _CTX.session = None

    def do_POST(self):  # noqa: N802
        self._bind_session()
        try:
            self._do_post()
        finally:
            _CTX.session = None

    def _do_get(self) -> None:
        if urlparse(self.path).path == "/healthz":
            self._send(200, "ok", "text/plain", headers={"Cache-Control": "no-store"})
            return
        if self._reject_foreign_host():
            return
        parsed = urlparse(self.path)
        qs = parse_qs(parsed.query)

        if parsed.path == "/":
            self._send(200, _render_index(), headers={"Cache-Control": "no-cache"})
            return

        if parsed.path.startswith("/static/"):
            name = parsed.path[len("/static/"):]
            if name not in _ASSETS:
                self._send(404, "not found", "text/plain")
                return
            self._send(200, _read_webui(name), _ASSETS[name], headers={"Cache-Control": "no-cache"})
            return

        if parsed.path == "/tables":
            self._send_json({"tables": TABLE_NAMES})
            return

        if parsed.path == "/table":
            if _STATE["parser"] is None:
                self._send_json({"error": "No workbook loaded"}, 400)
                return
            try:
                df, name = self._table_df(qs)
            except (FileNotFoundError, ValueError) as e:
                self._send_json({"error": str(e)}, 400)
                return
            if df is None:
                self._send_json({"error": f"unknown table '{name}'"}, 404)
                return
            self._send_json(
                {"html": _df_to_html(df), "rows": int(len(df)), **_df_to_records(df)}
            )
            return

        if parsed.path == "/graph":
            if _STATE["parser"] is None:
                self._send_json({"error": "No workbook loaded"}, 400)
                return
            include_inferred = (qs.get("include_inferred") or ["false"])[0] == "true"
            parser = _STATE["parser"]
            dot = parser.get_relationship_graph_dot(include_inferred=include_inferred)
            if (qs.get("download") or ["0"])[0] == "1":
                self._send(
                    200,
                    dot,
                    "text/vnd.graphviz; charset=utf-8",
                    {"Content-Disposition": 'attachment; filename="relationships.dot"'},
                )
                return
            self._send_json({"dot": dot, "graph": parser.get_relationship_graph_data(include_inferred=include_inferred)})
            return

        if parsed.path == "/overview":
            if _STATE["parser"] is None:
                self._send_json({"error": "No workbook loaded"}, 400)
                return
            # computed on first request, so opening a workbook is no slower, then kept until the next one
            if _STATE["report"] is None:
                try:
                    _STATE["report"] = _STATE["parser"].get_report()
                except Exception as e:
                    self._send_json({"error": f"could not build the report: {e}"}, 500)
                    return
            self._send_json(_STATE["report"])
            return

        if parsed.path in ("/audit", "/audit/export", "/dictionary"):
            if _STATE["parser"] is None:
                if parsed.path == "/audit":
                    self._send_json({"error": "No workbook loaded"}, 400)
                else:
                    self._send(400, "No workbook loaded", "text/plain")
                return
            try:
                if parsed.path == "/audit":
                    self._send_json(_audit_answer(qs))
                elif parsed.path == "/audit/export":
                    fmt = (qs.get("format") or ["csv"])[0]
                    if fmt not in ("csv", "json"):
                        raise ValueError("format: use csv or json")
                    found, _skip = _audit_frame(qs)
                    body = format_findings(_audit_filtered(found, qs), fmt)
                    ctype = "text/csv; charset=utf-8" if fmt == "csv" else "application/json; charset=utf-8"
                    self._send(200, body, ctype, {
                        "Content-Disposition": f'attachment; filename="{_workbook_stem()}-audit.{fmt}"'})
                else:
                    page = workbook_markdown(_STATE["parser"])
                    self._send(200, page, "text/markdown; charset=utf-8", {
                        "Content-Disposition": f'attachment; filename="{_workbook_stem()}-dictionary.md"'})
            except ValueError as e:
                if parsed.path == "/audit":
                    self._send_json({"error": str(e)}, 400)
                else:
                    self._send(400, str(e), "text/plain")
            except Exception as e:  # a rule or the page builder failed: say so, do not drop the connection
                if parsed.path == "/audit":
                    self._send_json({"error": f"could not audit the workbook: {e}"}, 500)
                else:
                    self._send(500, f"could not build the file: {e}", "text/plain")
            return

        if parsed.path == "/library/entries":
            if _STATE["parser"] is None:
                self._send_json({"error": "No workbook loaded"}, 400)
                return
            try:
                self._send_json(_library_entries_answer(qs))
            except ValueError as e:
                self._send_json({"error": str(e)}, 400)
            except Exception as e:
                self._send_json({"error": f"could not read the workbook's fields: {e}"}, 500)
            return

        if parsed.path == "/library/state":
            st = _STATE["lib"]
            self._send_json({"library": st.get("summary") if st else None})
            return

        if parsed.path == "/style/palettes":
            if _STATE["parser"] is None:
                self._send_json({"error": "No workbook loaded"}, 400)
                return
            try:
                self._send_json(_style_palettes_answer(qs))
            except ValueError as e:
                self._send_json({"error": str(e)}, 400)
            except Exception as e:
                self._send_json({"error": f"could not read the workbook's palettes: {e}"}, 500)
            return

        if parsed.path == "/style/state":
            st = _STATE["sty"]
            self._send_json({"file": st.get("summary") if st else None})
            return

        if parsed.path in ("/copy/dashboards", "/copy/sheets"):
            if _STATE["parser"] is None:
                self._send_json({"error": "No workbook loaded"}, 400)
                return
            try:
                self._send_json((_cpy_dashboards_answer if parsed.path.endswith("dashboards") else _cpy_sheets_answer)(qs))
            except ValueError as e:
                self._send_json({"error": str(e)}, 400)
            except Exception as e:
                self._send_json({"error": f"could not read the workbook: {e}"}, 500)
            return

        if parsed.path == "/copy/state":
            cpy = _STATE["cpy"]
            self._send_json({"target": cpy.get("summary") if cpy else None})
            return

        if parsed.path == "/dashboards":
            if _STATE["parser"] is None:
                self._send_json({"dashboards": []})
                return
            df = _STATE["parser"].get_dashboards()
            self._send_json({"dashboards": df["name"].tolist() if "name" in df.columns else []})
            return

        if parsed.path == "/export":
            if _STATE["parser"] is None:
                self._send(400, "No workbook loaded", "text/plain")
                return
            try:
                df, name = self._table_df(qs)
            except (FileNotFoundError, ValueError) as e:
                self._send(400, str(e), "text/plain")
                return
            if df is None:
                self._send(404, f"unknown table '{name}'", "text/plain")
                return
            csv_text = df.to_csv(index=False)
            self._send(
                200,
                csv_text,
                "text/csv; charset=utf-8",
                {"Content-Disposition": f'attachment; filename="{name}.csv"'},
            )
            return

        if parsed.path == "/download-workbook":
            if _STATE["parser"] is None:
                self._send(400, "No workbook loaded", "text/plain")
                return
            try:
                data, filename, _n = self._renamed_workbook(_rename_options(qs), _rename_exclude(qs))
            except (FileNotFoundError, ValueError) as e:
                self._send(400, str(e), "text/plain")
                return
            self._send(
                200,
                data,
                "application/octet-stream",
                {"Content-Disposition": _attachment(filename)},
            )
            return

        if parsed.path == "/template/state":
            self._template_state()
            return

        if parsed.path == "/template/output":
            self._template_download("output", "No workbook has been created yet")
            return

        if parsed.path == "/template/made":
            self._template_download("made", "No template has been made yet")
            return

        self._send(404, "not found", "text/plain")

    @staticmethod
    def _renamed_workbook(opts: dict, exclude=None):
        parser = _STATE["parser"]
        renames = (suggest_renames if "kinds" in opts else suggest_field_renames)(parser, **opts)
        renames = select_renames(renames, exclude)
        filename = os.path.basename(default_renamed_path(parser))
        report: dict = {}
        data = build_renamed_workbook(parser, renames, report)
        return data, filename, report["applied"]

    def _download_workbook(self, payload: dict) -> None:
        """The same fixed copy as GET /download-workbook, asked for in a JSON body so that a long list of
        left-out renames is not squeezed into a URL."""
        if _STATE["parser"] is None:
            self._send_json({"error": "No workbook loaded"}, 400)
            return
        try:
            data, filename, _n = self._renamed_workbook(_rename_options(payload), _rename_exclude(payload))
        except (FileNotFoundError, ValueError) as e:
            self._send_json({"error": str(e)}, 400)
            return
        self._send(200, data, "application/octet-stream", {"Content-Disposition": _attachment(filename)})

    def _create_workbook(self, payload: dict) -> None:
        """Save `<name>_renamed.<ext>` beside the loaded workbook (never over
        an existing file), with the suggested renames applied."""
        if _STATE["parser"] is None:
            self._send_json({"error": "No workbook loaded"}, 400)
            return
        if _STATE["uploaded"]:
            self._send_json(
                {"error": "This workbook was dropped in, so it has no folder to save beside. Use Download instead."},
                409,
            )
            return
        out = default_renamed_path(_STATE["parser"])
        try:
            data, _, renamed = self._renamed_workbook(_rename_options(payload), _rename_exclude(payload))
            # "xb" refuses an existing file atomically, so nothing is overwritten.
            with open(out, "xb") as fh:
                fh.write(data)
        except FileExistsError:
            self._send_json({"error": f"{out} already exists; move or delete it first"}, 409)
            return
        except (FileNotFoundError, ValueError, OSError) as e:
            self._send_json({"error": str(e)}, 400)
            return
        self._send_json({"ok": True, "path": out, "renamed": renamed})

    def _declared_length(self) -> int:
        try:
            return int(self.headers.get("Content-Length") or 0)
        except ValueError:
            return -1

    def _linger_close(self, limit: int = 1024 * 1024, wait: float = 2.0) -> None:
        """Close politely after answering a request whose body could not be drained first (a Content-Length that
        is not a number or is negative, or one too big to read). Closing a socket that still has unread bytes
        makes Windows send a reset, and the client then fails with a connection abort instead of reading the
        error. So: flush the answer, half-close our side (the client sees the end of the response), and read
        what is still arriving, at most `limit` bytes and `wait` seconds, until the client closes."""
        self.close_connection = True
        try:
            self.wfile.flush()
            self.connection.shutdown(socket.SHUT_WR)
            self.connection.settimeout(wait)
            left = limit
            while left > 0:
                chunk = self.connection.recv(min(65536, left))
                if not chunk:
                    break
                left -= len(chunk)
        except OSError:
            pass

    def _drain(self, left: int) -> None:
        """Read and throw away an unread request body (up to MAX_DRAIN_BYTES) before refusing it. Answering
        first and closing with bytes still arriving makes some systems, Windows in particular, reset the
        connection, and then the client never sees the error message. A body too big to drain is not read;
        the connection is closed and the client may see a network error instead of the message."""
        if left <= 0:
            return
        if left > MAX_DRAIN_BYTES:
            self.close_connection = True
            return
        while left > 0:
            chunk = self.rfile.read(min(1024 * 1024, left))
            if not chunk:
                break
            left -= len(chunk)

    def _upload(self, slot: str = "workbook") -> None:
        """Receive a file as raw bytes (the file name in `X-Filename`): a workbook to open (`/upload`), or the
        Templates view's template or data (`slot`). Neither the content type nor the header is CORS-safelisted,
        so another site cannot send this without a preflight the server never answers; the Origin check is belt
        and braces. Streamed to disk in 1 MB pieces, never held whole."""
        length = self._declared_length()
        ctype = (self.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        if ctype != "application/octet-stream":
            self._drain(length)
            self._send_json({"error": "Content-Type must be application/octet-stream"}, 415)
            return
        if not _origin_ok(self.headers.get("Origin"), self.headers.get("Host")):
            self._drain(length)
            self._send_json({"error": "cross-origin request rejected"}, 403)
            return
        name = os.path.basename(unquote(self.headers.get("X-Filename") or "").replace("\\", "/"))
        if not name or length <= 0:
            self._drain(length)
            self._send_json({"error": "Send the file bytes with an X-Filename header."}, 400)
            return
        if length > MAX_UPLOAD_BYTES:
            self._send_json(
                {"error": f"That file is {length // (1024 * 1024)} MB; the limit is {MAX_UPLOAD_BYTES // (1024 * 1024)} MB."},
                413,
            )
            self.close_connection = True
            return
        head = self.rfile.read(min(length, 16))
        problem = _upload_problem(name, head, slot)
        if problem:
            self._drain(length - len(head))
            self._send_json({"error": problem}, 400)
            return
        if _free_bytes(tempfile.gettempdir()) < 2 * length + _DISK_HEADROOM:
            self._drain(length - len(head))
            self._send_json({"error": "The server is short of disk space; try again later or with a smaller file."}, 507)
            return
        if slot != "workbook":
            self._template_upload(slot, name, length, head)
            return
        _clear_upload()
        folder = tempfile.mkdtemp(prefix="py-tbparse-")
        _UPLOAD["dir"] = folder
        dest = os.path.join(folder, name)
        try:
            with open(dest, "wb") as fh:
                fh.write(head)
                left = length - len(head)
                while left > 0:
                    chunk = self.rfile.read(min(1024 * 1024, left))
                    if not chunk:
                        raise OSError("the upload ended early")
                    fh.write(chunk)
                    left -= len(chunk)
            parser = TwbParser(dest)
        except (FileNotFoundError, ValueError, OSError) as e:
            _clear_upload()
            self._send_json({"error": str(e)}, 400)
            return
        except Exception as e:  # malformed workbook, broken zip
            _clear_upload()
            self._send_json({"error": f"failed to parse workbook: {e}"}, 400)
            return
        self._send_json(_open_response(parser, dest, uploaded=True, name=name))

    def _receive(self, dest: str, head: bytes, length: int) -> None:
        with open(dest, "wb") as fh:
            fh.write(head)
            left = length - len(head)
            while left > 0:
                chunk = self.rfile.read(min(1024 * 1024, left))
                if not chunk:
                    raise OSError("the upload ended early")
                fh.write(chunk)
                left -= len(chunk)

    def _library_upload(self) -> None:
        """Receive a library file as raw bytes (X-Filename) into memory, at most MAX_LIBRARY_BYTES. It is parsed
        as JSON and kept for this session; it is never written to disk and never opened as a path."""
        length = self._declared_length()
        ctype = (self.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        if ctype != "application/octet-stream":
            self._refuse_post(415, "Content-Type must be application/octet-stream")
            return
        if not _origin_ok(self.headers.get("Origin"), self.headers.get("Host")):
            self._refuse_post(403, "cross-origin request rejected")
            return
        if _STATE["parser"] is None:
            self._refuse_post(400, "Open a workbook first; the library is added to it.")
            return
        name = os.path.basename(unquote(self.headers.get("X-Filename") or "").replace("\\", "/"))
        if not name or length <= 0:
            self._refuse_post(400, "Send the file bytes with an X-Filename header.")
            return
        if length > MAX_LIBRARY_BYTES:
            self._refuse_post(413, f"That file is {length // (1024 * 1024)} MB; a library can be at most "
                                   f"{MAX_LIBRARY_BYTES // (1024 * 1024)} MB.")
            return
        raw = self.rfile.read(length)
        try:
            lib = _library_upload_ok(raw, name)
            summary = _library_summary(lib, name)
        except ValueError as e:
            self._send_json({"error": str(e)}, 400)
            return
        st = _lib_state()
        st["library"] = lib
        st["summary"] = summary
        self._send_json({"ok": True, "library": summary})

    def _library_post(self, path: str, payload: dict) -> None:
        unknown = sorted(set(payload) - _LIBRARY_KEYS[path])
        if unknown:
            self._send_json({"error": f"not accepted here: {', '.join(unknown)}"}, 400)
            return
        if _STATE["parser"] is None:
            self._send_json({"error": "No workbook loaded"}, 400)
            return
        try:
            if path == "/library/clear":
                _STATE["lib"] = None
                self._send_json({"ok": True})
            elif path == "/library/plan":
                self._send_json(_library_plan(payload))
            elif path == "/library/export":
                text, filename = _library_export(payload)
                self._send(200, text, "application/json; charset=utf-8", {"Content-Disposition": _attachment(filename)})
            else:
                data, filename, report = _library_add(payload)
                self._send(200, data, "application/octet-stream", {
                    "Content-Disposition": _attachment(filename),
                    "X-Library-Added": str(report.get("added", 0)),
                    "Access-Control-Expose-Headers": "X-Library-Added, Content-Disposition"})
        except (ValueError, FileNotFoundError) as e:  # LibraryError is a ValueError
            self._send_json({"error": str(e)}, 400)
        except Exception as e:
            self._send_json({"error": f"could not complete this: {e}"}, 500)

    def _style_upload(self) -> None:
        """Receive a palette file (.style.json or .tps) as raw bytes (X-Filename) into memory, at most
        MAX_STYLE_BYTES. It is parsed and kept for this session; it is never written to disk or opened as a path."""
        length = self._declared_length()
        ctype = (self.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        if ctype != "application/octet-stream":
            self._refuse_post(415, "Content-Type must be application/octet-stream")
            return
        if not _origin_ok(self.headers.get("Origin"), self.headers.get("Host")):
            self._refuse_post(403, "cross-origin request rejected")
            return
        if _STATE["parser"] is None:
            self._refuse_post(400, "Open a workbook first; the palettes are added to it.")
            return
        name = os.path.basename(unquote(self.headers.get("X-Filename") or "").replace("\\", "/"))
        if not name or length <= 0:
            self._refuse_post(400, "Send the file bytes with an X-Filename header.")
            return
        if length > MAX_STYLE_BYTES:
            self._refuse_post(413, f"That file is {length // 1024} KB; a palette file can be at most "
                                   f"{MAX_STYLE_BYTES // (1024 * 1024)} MB.")
            return
        raw = self.rfile.read(length)
        try:
            records = _style.palettes_from_bytes(raw, name)
        except ValueError as e:
            self._send_json({"error": str(e)}, 400)
            return
        usable = [r for r in records if r["status"] in ("ok", "warning")]
        summary = {"file": name, "palettes": len(records), "usable": len(usable),
                   "invalid": sum(1 for r in records if r["status"] == "invalid"),
                   "problems": _style.palette_problems(records)[:100] if records else ["no palette found in this file"]}
        st = _sty_state()
        st["records"] = records
        st["summary"] = summary
        self._send_json({"ok": True, "file": summary})

    def _style_post(self, path: str, payload: dict) -> None:
        unknown = sorted(set(payload) - _STYLE_KEYS[path])
        if unknown:
            self._send_json({"error": f"not accepted here: {', '.join(unknown)}"}, 400)
            return
        if _STATE["parser"] is None:
            self._send_json({"error": "No workbook loaded"}, 400)
            return
        try:
            if path == "/style/clear":
                _STATE["sty"] = None
                self._send_json({"ok": True})
            elif path == "/style/plan":
                self._send_json(_style_plan(payload))
            elif path == "/style/export":
                data, filename = _style_export(payload)
                ctype = "application/xml; charset=utf-8" if filename.endswith(".tps") else "application/json; charset=utf-8"
                self._send(200, data, ctype, {"Content-Disposition": _attachment(filename)})
            else:
                data, filename, report = _style_add(payload)
                self._send(200, data, "application/octet-stream", {
                    "Content-Disposition": _attachment(filename),
                    "X-Style-Added": str(len(report.get("added", [])) + len(report.get("renamed", [])) + len(report.get("replaced", []))),
                    "Access-Control-Expose-Headers": "X-Style-Added, Content-Disposition"})
        except (ValueError, FileNotFoundError) as e:  # StyleError is a ValueError
            self._send_json({"error": str(e)}, 400)
        except Exception as e:
            self._send_json({"error": f"could not complete this: {e}"}, 500)

    def _copy_upload(self) -> None:
        """Receive the target workbook (.twb or .twbx) as raw bytes (X-Filename), streamed into a private temp folder
        and parsed there. At most MAX_UPLOAD_BYTES; the folder goes when it is replaced, cleared or the session ends."""
        length = self._declared_length()
        ctype = (self.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        if ctype != "application/octet-stream":
            self._refuse_post(415, "Content-Type must be application/octet-stream")
            return
        if not _origin_ok(self.headers.get("Origin"), self.headers.get("Host")):
            self._refuse_post(403, "cross-origin request rejected")
            return
        if _STATE["parser"] is None:
            self._refuse_post(400, "Open a workbook first; its sheets are copied into the target.")
            return
        name = os.path.basename(unquote(self.headers.get("X-Filename") or "").replace("\\", "/"))
        if not name or length <= 0:
            self._refuse_post(400, "Send the file bytes with an X-Filename header.")
            return
        if length > MAX_UPLOAD_BYTES:
            self._refuse_post(413, f"That file is {length // (1024 * 1024)} MB; the limit is {MAX_UPLOAD_BYTES // (1024 * 1024)} MB.")
            return
        head = self.rfile.read(min(length, 16))
        problem = _upload_problem(name, head, "workbook")
        if problem:
            self._drain(length - len(head))
            self._send_json({"error": problem}, 400)
            return
        if _free_bytes(tempfile.gettempdir()) < 2 * length + _DISK_HEADROOM:
            self._drain(length - len(head))
            self._send_json({"error": "The server is short of disk space; try again later or with a smaller file."}, 507)
            return
        _cpy_clear()
        folder = tempfile.mkdtemp(prefix="py-tbparse-copy-")
        dest = os.path.join(folder, name)
        try:
            self._receive(dest, head, length)
            parser = TwbParser(dest)
        except (FileNotFoundError, ValueError, OSError) as e:
            shutil.rmtree(folder, ignore_errors=True)
            self._send_json({"error": str(e).replace(dest, name)}, 400)
            return
        except Exception as e:  # malformed workbook, broken zip
            shutil.rmtree(folder, ignore_errors=True)
            self._send_json({"error": f"failed to parse workbook: {str(e).replace(dest, name)}"}, 400)
            return
        doc = parser.xml_doc
        summary = {"file": name, "worksheets": len(doc.xpath("/workbook/worksheets/worksheet")),
                   "dashboards": len(doc.xpath("/workbook/dashboards/dashboard")),
                   "datasources": [d for d in doc.xpath("/workbook/datasources/datasource[@name!='Parameters']/@name")][:50]}
        _STATE["cpy"] = {"dir": folder, "parser": parser, "name": name, "summary": summary}
        self._send_json({"ok": True, "target": summary})

    def _copy_post(self, path: str, payload: dict) -> None:
        from .slicer import SliceError
        unknown = sorted(set(payload) - _COPY_KEYS[path])
        if unknown:
            self._send_json({"error": f"not accepted here: {', '.join(unknown)}"}, 400)
            return
        if _STATE["parser"] is None:
            self._send_json({"error": "No workbook loaded"}, 400)
            return
        try:
            if path == "/copy/clear":
                _cpy_clear()
                self._send_json({"ok": True})
            elif path == "/copy/slice-plan":
                self._send_json(_cpy_slice_plan(payload))
            elif path == "/copy/plan":
                self._send_json(_cpy_copy_plan(payload))
            else:
                data, filename, report = (_cpy_slice_download if path == "/copy/slice-download" else _cpy_copy_download)(payload)
                self._send(200, data, "application/octet-stream", {
                    "Content-Disposition": _attachment(filename),
                    "X-Copy-Count": str(report["copied"] if "copied" in report else len(report["kept_dashboards"])),
                    "Access-Control-Expose-Headers": "X-Copy-Count, Content-Disposition"})
        except (ValueError, FileNotFoundError) as e:  # SliceError and SheetCopyError are ValueErrors
            self._send_json({"error": _cpy_scrub(str(e))}, 400)
        except Exception as e:
            self._send_json({"error": f"could not complete this: {_cpy_scrub(str(e))}"}, 500)

    # ---- the Templates view ----

    def _tpl_send(self, obj, code: int = 200, tpl=None, extra=()) -> None:
        self._send_json(_scrub(obj, tpl, extra), code)

    def _template_upload(self, slot: str, name: str, length: int, head: bytes) -> None:
        tpl = _tpl_state(create=True)
        try:
            with tpl["lock"]:
                folder = tempfile.mkdtemp(prefix=slot + "-", dir=_tpl_dir(tpl))
        except OSError as e:
            self._drain(length - len(head))
            self._tpl_send({"error": str(e)}, 400, tpl)
            return
        dest = os.path.join(folder, name)
        extra = [(dest, name), (folder, "(upload)")]
        try:
            self._receive(dest, head, length)
            if slot == "template":
                obj = load_template(dest)
                summary, choices = template_gui.template_summary(obj, label=name), {}
            else:
                obj, summary, choices = _read_data_slot(dest, name)
        except (TemplateError, ValueError, FileNotFoundError, OSError) as e:
            shutil.rmtree(folder, ignore_errors=True)
            self._tpl_send({"error": str(e)}, 400, tpl, extra)
            return
        except Exception as e:  # a broken zip, malformed XML, an unreadable spreadsheet
            shutil.rmtree(folder, ignore_errors=True)
            self._tpl_send({"error": f"could not read {name}: {e}"}, 400, tpl, extra)
            return
        with tpl["lock"]:
            if tpl["dropped"] or not os.path.isfile(dest):  # cleared or ended while the file arrived
                shutil.rmtree(folder, ignore_errors=True)
                self._tpl_send({"error": "The upload was cancelled; choose the file again."}, 409, tpl, extra)
                return
            self._tpl_fill(tpl, slot, obj, summary, choices, dest, name, uploaded=True)
            answer = {"ok": True, slot: summary, **choices}
        self._tpl_send(answer, 200, tpl)

    @staticmethod
    def _tpl_fill(tpl, slot, obj, summary, choices, path, label, uploaded) -> None:
        """Put a new file into `slot`, deleting the previous uploaded one. Call with the lock held."""
        old = tpl[slot + "_path"] if tpl[slot + "_uploaded"] else None
        tpl.update({slot: obj, slot + "_summary": summary, slot + "_path": path, slot + "_label": label,
                    slot + "_uploaded": uploaded})
        if slot == "data":
            tpl.update(sheets=choices.get("sheets"), datasources=choices.get("datasources"))
        if old and old != path:
            shutil.rmtree(os.path.dirname(old), ignore_errors=True)

    def _template_post(self, route: str, payload: dict) -> None:
        problem = _payload_problem(route, payload)
        if problem:
            self._tpl_send({"error": problem}, 400)
            return
        if route in ("/template/open", "/template/open-data"):
            self._template_open("template" if route == "/template/open" else "data", payload)
        elif route == "/template/clear":
            tpl = _tpl_state()
            if tpl is not None:
                with tpl["lock"]:
                    _tpl_reset(tpl)
            self._tpl_send({"ok": True})
        elif route == "/template/select-data":
            self._template_select(payload)
        elif route == "/template/plan":
            self._template_plan(payload)
        elif route == "/template/make":
            self._template_make(payload)
        elif route == "/template/use-made":
            self._template_use_made()
        else:
            self._template_apply(payload, save=route == "/template/save")

    def _template_open(self, slot: str, payload: dict) -> None:
        """Local GUI only (a path route): open the template or the data by its path on this computer."""
        path = (payload.get("path") or "").strip()
        if not path:
            self._tpl_send({"error": "path is required"}, 400)
            return
        name = os.path.basename(path.replace("\\", "/"))
        try:
            with open(path, "rb") as fh:
                head = fh.read(16)
            problem = _upload_problem(name, head, slot)
            if problem:
                raise TemplateError(problem)
            if slot == "template":
                obj = load_template(path)
                summary, choices = template_gui.template_summary(obj, label=name), {}
            else:
                obj, summary, choices = _read_data_slot(path, name)
        except (TemplateError, ValueError, OSError) as e:
            self._tpl_send({"error": str(e)}, 400)
            return
        except Exception as e:
            self._tpl_send({"error": f"could not read {name}: {e}"}, 400)
            return
        tpl = _tpl_state(create=True)
        with tpl["lock"]:
            self._tpl_fill(tpl, slot, obj, summary, choices, path, name, uploaded=False)
        self._tpl_send({"ok": True, slot: summary, "path": path, **choices}, 200, tpl)

    def _template_select(self, payload: dict) -> None:
        """Re-read the chosen data file with a sheet (Excel) or datasource (workbook, .tds)."""
        tpl = _tpl_state()
        if tpl is None or not tpl["data_path"]:
            self._tpl_send({"error": "Choose the data first."}, 400, tpl)
            return
        with tpl["lock"]:
            label = tpl["data_label"]
            try:
                data, summary, choices = _read_data_slot(tpl["data_path"], label, sheet=payload.get("sheet"),
                                                         datasource=payload.get("datasource"))
                if data is None:
                    raise TemplateError(f"{label} has several; choose one")
            except (TemplateError, ValueError, OSError) as e:
                self._tpl_send({"error": str(e)}, 400, tpl)
                return
            except Exception as e:
                self._tpl_send({"error": f"could not read {label}: {e}"}, 400, tpl)
                return
            tpl.update(data=data, data_summary=summary, sheets=choices["sheets"], datasources=choices["datasources"])
            answer = {"ok": True, "data": summary, **choices}
        self._tpl_send(answer, 200, tpl)

    @staticmethod
    def _tpl_missing(tpl):
        """Why there is nothing to plan yet, or None."""
        if tpl is None or tpl["template"] is None:
            return "Choose a template first."
        if tpl["data"] is None:
            if tpl["data_path"] and tpl["sheets"]:
                return f"Choose a sheet of {tpl['data_label']} first."
            if tpl["data_path"] and tpl["datasources"]:
                return f"Choose a datasource of {tpl['data_label']} first."
            return "Choose the data first."
        return None

    def _template_plan(self, payload: dict) -> None:
        tpl = _tpl_state()
        missing = self._tpl_missing(tpl)
        if missing:
            self._tpl_send({"error": missing}, 400, tpl)
            return
        with tpl["lock"]:
            try:
                answer = template_gui.plan(tpl["template"], tpl["data"], allow_missing=bool(payload.get("allow_missing")),
                                           **_plan_args(payload))
            except (TemplateError, ValueError, FileNotFoundError) as e:
                self._tpl_send({"error": str(e)}, 400, tpl)
                return
            except Exception as e:
                self._tpl_send({"error": f"could not check the mapping: {e}"}, 500, tpl)
                return
        self._tpl_send(answer, 200, tpl)

    def _template_apply(self, payload: dict, save: bool) -> None:
        """Make the workbook in a fresh folder of the session directory, keeping only this one output. With
        `save` (local GUI, path-opened template only) also copy it beside the template, never over a file."""
        tpl = _tpl_state()
        missing = self._tpl_missing(tpl)
        if missing:
            self._tpl_send({"error": missing}, 400, tpl)
            return
        if save and tpl["template_uploaded"]:
            self._tpl_send({"error": "This template was dropped in, so it has no folder to save beside. "
                                     "Use Download instead."}, 409, tpl)
            return
        # One apply at a time per session: a double click must not race two writes into the same folder.
        with tpl["lock"]:
            t, d = tpl["template"], tpl["data"]
            try:
                raw = payload.get("data_path")
                if tpl["data_uploaded"]:
                    data_path = template_gui.output_data_path(raw or "", d)  # never the temp path (Q2)
                else:
                    data_path = template_gui.output_data_path(raw, d) if raw else None
            except (TemplateError, ValueError) as e:
                self._tpl_send({"error": str(e)}, 400, tpl)
                return
            if tpl["output"]:
                shutil.rmtree(os.path.dirname(tpl["output"]), ignore_errors=True)
                tpl.update(output=None, output_name=None)
            try:
                out = tempfile.mkdtemp(prefix="out-", dir=_tpl_dir(tpl))
            except OSError as e:
                self._tpl_send({"error": str(e)}, 400, tpl)
                return
            try:
                result = template_gui.apply(t, d, out, data_path=data_path,
                                            allow_missing=bool(payload.get("allow_missing")), **_plan_args(payload))
            except (TemplateError, ValueError, FileNotFoundError) as e:
                shutil.rmtree(out, ignore_errors=True)
                self._tpl_send({"error": str(e)}, 400, tpl)
                return
            except Exception as e:
                shutil.rmtree(out, ignore_errors=True)
                self._tpl_send({"error": f"could not create the workbook: {e}"}, 500, tpl)
                return
            tpl.update(output=result["path"], output_name=result["name"])
            answer = {"ok": True, "name": result["name"], "size": result["size"], "report": result["report"]}
            if save:
                final = os.path.join(os.path.dirname(os.path.abspath(tpl["template_path"])), result["name"])
                try:
                    with open(result["path"], "rb") as src:
                        data = src.read()
                    # "xb" refuses an existing file atomically, so nothing is overwritten.
                    with open(final, "xb") as fh:
                        fh.write(data)
                except FileExistsError:
                    self._tpl_send({"error": f"{final} already exists; move or delete it first"}, 409, tpl)
                    return
                except OSError as e:
                    self._tpl_send({"error": str(e)}, 400, tpl)
                    return
                answer["path"] = final
        self._tpl_send(answer, 200, tpl)

    def _template_make(self, payload: dict) -> None:
        """Make a template from the open workbook into the session folder (never a path from the page), keeping
        only the newest one. The answer is the new template's summary, so the page can offer to use it."""
        parser, source = _STATE["parser"], _STATE["path"]
        if parser is None:
            self._tpl_send({"error": "Open a workbook first; the template is made from it."}, 400)
            return
        label = os.path.basename(str(source).replace("\\", "/"))
        extra = [(source, label)]
        tpl = _tpl_state(create=True)
        name = (payload.get("name") or "").strip()
        description = (payload.get("description") or "").strip()
        try:
            size = os.path.getsize(parser.twbx_path or parser.path)
        except OSError:
            size = 0
        if _free_bytes(tempfile.gettempdir()) < 2 * size + _DISK_HEADROOM:
            self._tpl_send({"error": "The server is short of disk space; try again later."}, 507, tpl, extra)
            return
        file_name = _template_file_name(name, label)
        with tpl["lock"]:
            try:
                folder = tempfile.mkdtemp(prefix="made-", dir=_tpl_dir(tpl))
            except OSError as e:
                self._tpl_send({"error": str(e)}, 400, tpl, extra)
                return
            dest = os.path.join(folder, file_name)
            extra += [(dest, file_name), (folder, "(upload)")]
            try:
                with _WARN_LOCK, warnings.catch_warnings(record=True) as caught:
                    warnings.simplefilter("always")
                    make_template(parser, output_path=dest, name=name or None, description=description or None)
                notes = [str(w.message) for w in caught if issubclass(w.category, UserWarning)][:20]
                made = load_template(dest)
                summary = template_gui.template_summary(made, label=file_name)
            except (TemplateError, ValueError, FileExistsError, OSError) as e:
                shutil.rmtree(folder, ignore_errors=True)
                self._tpl_send({"error": str(e)}, 400, tpl, extra)
                return
            except Exception as e:
                shutil.rmtree(folder, ignore_errors=True)
                self._tpl_send({"error": f"could not make the template: {e}"}, 500, tpl, extra)
                return
            if tpl["made"]:
                shutil.rmtree(os.path.dirname(tpl["made"]), ignore_errors=True)
            tpl.update(made=dest, made_name=file_name, made_summary=summary)
            answer = {"ok": True, "name": file_name, "size": os.path.getsize(dest), "template": summary,
                      "notes": notes}
        self._tpl_send(answer, 200, tpl, extra)

    def _template_use_made(self) -> None:
        """Put a copy of the made template into the template slot, as if it had been dropped there. It is a
        copy, so choosing another template later does not delete the made file."""
        tpl = _tpl_state()
        if tpl is None or not tpl["made"] or not os.path.isfile(tpl["made"]):
            self._tpl_send({"error": "Make a template first."}, 400, tpl)
            return
        with tpl["lock"]:
            name = tpl["made_name"]
            try:
                folder = tempfile.mkdtemp(prefix="template-", dir=_tpl_dir(tpl))
            except OSError as e:
                self._tpl_send({"error": str(e)}, 400, tpl)
                return
            dest = os.path.join(folder, name)
            extra = [(dest, name), (folder, "(upload)")]
            try:
                shutil.copyfile(tpl["made"], dest)
                obj = load_template(dest)
                summary = template_gui.template_summary(obj, label=name)
            except Exception as e:
                shutil.rmtree(folder, ignore_errors=True)
                self._tpl_send({"error": f"could not use {name}: {e}"}, 400, tpl, extra)
                return
            self._tpl_fill(tpl, "template", obj, summary, {}, dest, name, uploaded=True)
        self._tpl_send({"ok": True, "template": summary}, 200, tpl)

    def _template_state(self) -> None:
        """What a reloaded page needs to restore the view: the two summaries, the data choices, the output."""
        tpl = _tpl_state()
        if tpl is None:
            self._tpl_send({"template": None, "data": None, "sheets": None, "datasources": None, "output": None,
                            "workbook": self._open_workbook_name(), "made": None})
            return
        output = None
        if tpl["output"] and os.path.isfile(tpl["output"]):
            output = {"name": tpl["output_name"], "size": os.path.getsize(tpl["output"])}
        made = None
        if tpl["made"] and os.path.isfile(tpl["made"]):
            made = {"name": tpl["made_name"], "size": os.path.getsize(tpl["made"]), "template": tpl["made_summary"]}
        self._tpl_send({"template": tpl["template_summary"], "data": tpl["data_summary"], "sheets": tpl["sheets"],
                        "datasources": tpl["datasources"], "output": output, "workbook": self._open_workbook_name(),
                        "made": made}, 200, tpl)

    @staticmethod
    def _open_workbook_name():
        """The open workbook as the Templates view needs it: its file name only, or None."""
        if _STATE["parser"] is None:
            return None
        return {"name": os.path.basename(str(_STATE["path"]).replace("\\", "/"))}

    def _template_download(self, key: str, missing: str) -> None:
        """Send this session's output workbook (`output`) or made template (`made`), or a 404."""
        tpl = _tpl_state()
        data = name = None
        if tpl is not None:
            with tpl["lock"]:
                if tpl[key] and os.path.isfile(tpl[key]):
                    with open(tpl[key], "rb") as fh:
                        data = fh.read()
                    name = tpl[key + "_name"]
        if data is None:
            self._send(404, missing, "text/plain")
            return
        self._send(200, data, "application/octet-stream", {"Content-Disposition": _attachment(name)})

    def _refuse_post(self, status: int, message: str, *, as_json: bool = True) -> None:
        """Refuse a POST before its body is read: drain the body first (see `_drain`), then answer."""
        length = self._declared_length()
        self._drain(length)
        if as_json:
            self._send_json({"error": message}, status)
        else:
            self._send(status, message, "text/plain")
        if length < 0 or length > MAX_DRAIN_BYTES:
            self._linger_close()

    def _do_post(self) -> None:
        if not _host_allowed(self.headers.get("Host"), self.server.server_address):
            self._refuse_post(403, "forbidden: unrecognized Host header", as_json=False)
            return
        if self.path in _UPLOAD_ROUTES:
            self._upload(_UPLOAD_SLOTS[self.path])
            return
        if self.path == "/library/upload":
            self._library_upload()
            return
        if self.path == "/style/upload":
            self._style_upload()
            return
        if self.path == "/copy/upload":
            self._copy_upload()
            return
        if self.path not in _JSON_ROUTES:
            self._refuse_post(404, "not found", as_json=False)
            return
        if _CONFIG["server_mode"] and self.path in _PATH_ROUTES:
            # These read or write a path on this machine's disk (open a workbook, a template or data by path,
            # save beside the original or the template); on a shared server only uploads are allowed.
            self._refuse_post(403, "Opening a path on the server is turned off here. Drop a file onto the page instead.")
            return

        # A cross-site form/fetch can only POST without a CORS preflight
        # using a "simple" content type (text/plain, form encodings);
        # requiring application/json forces a preflight, which this
        # server never answers. The Origin check is belt and braces.
        ctype = (self.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        if ctype != "application/json":
            self._refuse_post(415, "Content-Type must be application/json")
            return
        if not _origin_ok(self.headers.get("Origin"), self.headers.get("Host")):
            self._refuse_post(403, "cross-origin request rejected")
            return

        # Every JSON route is checked here, once, so a new route cannot forget it.
        length = self._declared_length()
        if length < 0:
            self._refuse_post(400, "bad Content-Length")
            return
        if length > MAX_JSON_BYTES:
            self._refuse_post(413, f"That request is too big (the limit is {MAX_JSON_BYTES // 1024} KB).")
            return

        raw = self.rfile.read(length) if length else b"{}"
        try:
            payload = json.loads(raw or b"{}")
        except json.JSONDecodeError:
            self._send_json({"error": "malformed JSON body"}, 400)
            return
        if not isinstance(payload, dict):
            self._send_json({"error": "JSON body must be an object"}, 400)
            return

        if self.path == "/create-workbook":
            self._create_workbook(payload)
            return
        if self.path == "/download-workbook":
            self._download_workbook(payload)
            return
        if self.path.startswith("/template/"):
            self._template_post(self.path, payload)
            return
        if self.path in _LIBRARY_KEYS:
            self._library_post(self.path, payload)
            return
        if self.path in _STYLE_KEYS:
            self._style_post(self.path, payload)
            return
        if self.path in _COPY_KEYS:
            self._copy_post(self.path, payload)
            return

        path = str(payload.get("path", "")).strip()
        if not path:
            self._send_json({"error": "path is required"}, 400)
            return

        try:
            parser = TwbParser(path)
        except (FileNotFoundError, ValueError) as e:
            self._send_json({"error": str(e)}, 400)
            return
        except Exception as e:  # malformed workbook, permissions, etc.
            self._send_json({"error": f"failed to parse workbook: {e}"}, 400)
            return

        self._send_json(_open_response(parser, path))


def build_arg_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="py-tbparse-gui", description="Local browser GUI for py_tbparse."
    )
    ap.add_argument("workbook", nargs="?", help="optional .twb/.twbx path to preload")
    ap.add_argument("--port", type=int, default=0, help="port to bind (default: pick a free one)")
    ap.add_argument("--host", default="127.0.0.1", help="host to bind (default: 127.0.0.1)")
    ap.add_argument("--no-browser", action="store_true", help="don't auto-open a browser tab")
    server = ap.add_argument_group(
        "server mode",
        "for running behind a reverse proxy (see docs/deployment.md); each option also has a "
        "PY_TBPARSE_* environment variable",
    )
    server.add_argument(
        "--server-mode", action="store_true", default=_env_flag("PY_TBPARSE_SERVER_MODE"),
        help="one private session per browser; opening server paths and saving beside the original are off",
    )
    server.add_argument(
        "--allowed-host", action="append", metavar="NAME",
        default=[h for h in os.environ.get("PY_TBPARSE_ALLOWED_HOSTS", "").replace(",", " ").split() if h],
        help="public host name the proxy forwards (repeatable; any port)",
    )
    server.add_argument(
        "--trust-proxy", action="store_true", default=_env_flag("PY_TBPARSE_TRUST_PROXY"),
        help="accept https Origins for an allowed host and mark the session cookie Secure (TLS ends at the proxy)",
    )
    server.add_argument(
        "--max-sessions", type=int, default=int(os.environ.get("PY_TBPARSE_MAX_SESSIONS", "20")),
        help="most browsers held at once; the least recently used is dropped (default: 20)",
    )
    server.add_argument(
        "--session-ttl", type=int, default=int(os.environ.get("PY_TBPARSE_SESSION_TTL", "3600")),
        help="seconds a session lives without a request (default: 3600)",
    )
    return ap


def _env_flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _raise_interrupt(signum, frame):
    raise KeyboardInterrupt


def main(argv=None) -> int:
    args = build_arg_parser().parse_args(argv)

    _CONFIG.update(
        server_mode=args.server_mode,
        allowed_hosts=frozenset(h.lower() for h in args.allowed_host),
        trust_proxy=args.trust_proxy,
        max_sessions=max(1, args.max_sessions),
        session_ttl=max(1, args.session_ttl),
    )
    if args.server_mode and args.workbook:
        print("warning: a preloaded workbook is ignored in server mode (visitors drop their own files)")
        args.workbook = None
    if args.server_mode and not args.allowed_host and args.host in _WILDCARD_ADDRS:
        print("note: no --allowed-host given; only requests addressed by IP are accepted")

    if args.workbook:
        try:
            _STATE["parser"] = TwbParser(args.workbook)
            _STATE["path"] = args.workbook
        except Exception as e:
            print(f"warning: could not preload {args.workbook}: {e}")

    server = ThreadingHTTPServer((args.host, args.port), Handler)
    host, port = server.server_address
    url = f"http://{host}:{port}/"
    print(f"py-tbparse GUI running at {url} (Ctrl+C to stop)")

    if not args.no_browser:
        threading.Timer(0.3, lambda: webbrowser.open(url)).start()

    # `docker stop` sends SIGTERM, which a process running as PID 1 ignores unless it has a handler.
    if threading.current_thread() is threading.main_thread():
        signal.signal(signal.SIGTERM, _raise_interrupt)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
