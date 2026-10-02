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
import threading
import webbrowser
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, quote, urlparse, urlsplit

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

_STATE: dict = {"parser": None, "path": None}


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
    bound_host, bound_port = server_address[0], server_address[1]
    if port != bound_port:
        return False
    if hostname in _LOOPBACK_NAMES or hostname == str(bound_host).lower():
        return True
    return bound_host in _WILDCARD_ADDRS and _is_ip_literal(hostname)


# The page lives in real files under webui/ (index.html plus tokens.css, app.css and app.js),
# so it can be linted, diffed and tested like any other front-end code. Only these names are
# served under /static/, so a request can never reach another file.
_WEBUI = Path(__file__).parent / "webui"
_ASSETS = {
    "tokens.css": "text/css; charset=utf-8",
    "app.css": "text/css; charset=utf-8",
    "app.js": "text/javascript; charset=utf-8",
    "table.js": "text/javascript; charset=utf-8",
}


def _read_webui(name: str) -> str:
    return (_WEBUI / name).read_text(encoding="utf-8")


def _render_index() -> str:
    """index.html with the server-side values spliced in as one inline script.

    Every value goes through `_json_for_script()`: `json.dumps` leaves `/` alone, so a workbook
    path containing `</script>` would otherwise close the tag early (see
    `test_preload_path_cannot_break_out_of_script_tag`). This is the only inline script."""
    config = (
        "<script>\n"
        f"window.TABLE_NAMES = {_json_for_script(TABLE_NAMES)};\n"
        f"window.PRELOAD_PATH = {_json_for_script(_STATE['path'])};\n"
        f"window.APP_VERSION = {_json_for_script(__version__)};\n"
        "</script>"
    )
    return _read_webui("index.html").replace("<!--APP_CONFIG-->", config)


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

    def do_GET(self):  # noqa: N802 (stdlib method name)
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
            dot = _STATE["parser"].get_relationship_graph_dot(include_inferred=include_inferred)
            if (qs.get("download") or ["0"])[0] == "1":
                self._send(
                    200,
                    dot,
                    "text/vnd.graphviz; charset=utf-8",
                    {"Content-Disposition": 'attachment; filename="relationships.dot"'},
                )
                return
            self._send_json({"dot": dot})
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

    def do_POST(self):  # noqa: N802
        if self._reject_foreign_host():
            return
        if self.path not in ("/load", "/create-workbook"):
            self._send(404, "not found", "text/plain")
            return

        # A cross-site form/fetch can only POST without a CORS preflight
        # using a "simple" content type (text/plain, form encodings);
        # requiring application/json forces a preflight, which this
        # server never answers. The Origin check is belt and braces.
        ctype = (self.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        if ctype != "application/json":
            self._send_json({"error": "Content-Type must be application/json"}, 415)
            return
        origin = self.headers.get("Origin")
        if origin is not None and origin.lower() != "http://" + self.headers["Host"].strip().lower():
            self._send_json({"error": "cross-origin request rejected"}, 403)
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

        _STATE["parser"] = parser
        _STATE["path"] = path
        dashboards_df = parser.get_dashboards()
        self._send_json(
            {
                "ok": True,
                "path": path,
                "name": os.path.basename(path),
                "counts": _table_counts(parser),
                "datasources": _datasource_names(parser),
                "datasource_labels": _datasource_labels(parser),
                "dashboards": dashboards_df["name"].tolist()
                if "name" in dashboards_df.columns
                else [],
            }
        )


def build_arg_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="py-tbparse-gui", description="Local browser GUI for py_tbparse."
    )
    ap.add_argument("workbook", nargs="?", help="optional .twb/.twbx path to preload")
    ap.add_argument("--port", type=int, default=0, help="port to bind (default: pick a free one)")
    ap.add_argument("--host", default="127.0.0.1", help="host to bind (default: 127.0.0.1)")
    ap.add_argument("--no-browser", action="store_true", help="don't auto-open a browser tab")
    return ap


def main(argv=None) -> int:
    args = build_arg_parser().parse_args(argv)

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

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
