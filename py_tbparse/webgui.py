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
import tempfile
import threading
import time
import webbrowser
from pathlib import Path
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, quote, unquote, urlparse, urlsplit

import pandas as pd

from . import __version__
from ._tables import TABLE_NAMES, TABLE_SPECS
from .parser import TwbParser
from .rename import (
    KINDS,
    _drop_parameters,
    build_renamed_workbook,
    default_renamed_path,
    suggest_field_renames,
    suggest_renames,
)

_STATE_DEFAULTS = {"parser": None, "path": None, "uploaded": False, "report": None}

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


def _clear_all_uploads() -> None:
    _clear_upload()
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


def _upload_problem(name: str, head: bytes) -> str | None:
    """Why these bytes are not a workbook named `name`, or None. The extension and the content must agree,
    so a renamed .exe or a text file is refused before the parser sees it."""
    ext = os.path.splitext(name)[1].lower()
    if ext == ".twbx":
        return None if head[:2] == b"PK" else "That file is not a packaged workbook (a .twbx is a zip archive)."
    if ext == ".twb":
        return None if head.lstrip(b"\xef\xbb\xbf \t\r\n")[:1] == b"<" else "That file is not a Tableau workbook (a .twb is XML)."
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
                data, filename, _n = self._renamed_workbook(_rename_options(qs))
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

        self._send(404, "not found", "text/plain")

    @staticmethod
    def _renamed_workbook(opts: dict):
        parser = _STATE["parser"]
        renames = (suggest_renames if "kinds" in opts else suggest_field_renames)(parser, **opts)
        filename = os.path.basename(default_renamed_path(parser))
        report: dict = {}
        data = build_renamed_workbook(parser, renames, report)
        return data, filename, report["applied"]

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
            data, _, renamed = self._renamed_workbook(_rename_options(payload))
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

    def _upload(self) -> None:
        """Receive a workbook as raw bytes (the file name in `X-Filename`). Neither the content type nor the
        header is CORS-safelisted, so another site cannot send this without a preflight the server never
        answers; the Origin check is belt and braces. Streamed to disk in 1 MB pieces, never held whole."""
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
        problem = _upload_problem(name, head)
        if problem:
            self._drain(length - len(head))
            self._send_json({"error": problem}, 400)
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

    def _refuse_post(self, status: int, message: str, *, as_json: bool = True) -> None:
        """Refuse a POST before its body is read: drain the body first (see `_drain`), then answer."""
        self._drain(self._declared_length())
        if as_json:
            self._send_json({"error": message}, status)
        else:
            self._send(status, message, "text/plain")

    def _do_post(self) -> None:
        if not _host_allowed(self.headers.get("Host"), self.server.server_address):
            self._refuse_post(403, "forbidden: unrecognized Host header", as_json=False)
            return
        if self.path == "/upload":
            self._upload()
            return
        if self.path not in ("/load", "/create-workbook"):
            self._refuse_post(404, "not found", as_json=False)
            return
        if _CONFIG["server_mode"]:
            # Both take a path on this machine's disk; on a shared server only uploads are allowed.
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

        length = int(self.headers.get("Content-Length", 0) or 0)
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
