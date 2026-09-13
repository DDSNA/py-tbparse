"""A small local-browser GUI for twbparser_py.

Built entirely on the standard library (`http.server` + vanilla JS) so it
adds no new dependencies and needs no display server / GUI toolkit —
just a browser, which makes it usable headless-server-side too (you can
curl its JSON endpoints). Run `twbparser-gui [workbook]` and it opens
http://127.0.0.1:<port>/ in your default browser.
"""

from __future__ import annotations

import argparse
import json
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import pandas as pd

from ._tables import TABLE_NAMES, TABLE_SPECS
from .parser import TwbParser

_STATE: dict = {"parser": None, "path": None}


def _df_to_html(df: pd.DataFrame) -> str:
    if df is None or df.empty:
        return "<p class='empty'>(empty)</p>"
    return df.to_html(index=False, na_rep="", classes="tbl", border=0, escape=True)


_PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>twbparser</title>
<style>
  :root { color-scheme: light dark; }
  body { font-family: -apple-system, Segoe UI, Roboto, sans-serif; margin: 0;
         padding: 16px; background: Canvas; color: CanvasText; }
  h1 { font-size: 1.1rem; margin: 0 0 12px; }
  .row { display: flex; gap: 8px; flex-wrap: wrap; align-items: center; margin-bottom: 10px; }
  input[type=text] { flex: 1; min-width: 220px; padding: 6px 8px; font-size: 0.9rem; }
  select, button, label { font-size: 0.9rem; }
  button { padding: 6px 12px; cursor: pointer; }
  #status { font-size: 0.85rem; opacity: 0.75; margin-bottom: 10px; min-height: 1.2em; }
  #status.err { color: #c0392b; opacity: 1; }
  .tbl { border-collapse: collapse; width: 100%; font-size: 0.85rem; }
  .tbl th, .tbl td { border: 1px solid #8884; padding: 4px 8px; text-align: left;
                      white-space: nowrap; max-width: 360px; overflow: hidden; text-overflow: ellipsis; }
  .tbl th { position: sticky; top: 0; background: Canvas; }
  #tableWrap { overflow: auto; max-height: 72vh; border: 1px solid #8884; }
  .empty { opacity: 0.6; font-style: italic; }
  #meta { font-size: 0.8rem; opacity: 0.7; margin: 6px 0; }
</style>
</head>
<body>
<h1>twbparser</h1>

<div class="row">
  <input id="path" type="text" placeholder="/path/to/workbook.twb or .twbx">
  <button id="loadBtn">Load</button>
</div>
<div id="status"></div>

<div class="row" id="controls" style="display:none">
  <label>Table:
    <select id="tableSel"></select>
  </label>
  <label id="dashboardWrap" style="display:none">Dashboard:
    <select id="dashboardSel"><option value="">(all)</option></select>
  </label>
  <label id="paramsWrap" style="display:none">
    <input type="checkbox" id="includeParams"> include Parameters
  </label>
  <label id="inferredWrap" style="display:none">
    <input type="checkbox" id="includeInferred"> include inferred (dashed)
  </label>
  <a id="exportLink" href="#" download>
    <button type="button" id="exportBtn">Export CSV</button>
  </a>
</div>
<div id="meta"></div>
<div id="tableWrap"><p class="empty">Load a workbook to begin.</p></div>

<script>
const $ = (id) => document.getElementById(id);
const statusEl = $('status');

function setStatus(msg, isErr) {
  statusEl.textContent = msg || '';
  statusEl.classList.toggle('err', !!isErr);
}

async function fetchJSON(url, opts) {
  const res = await fetch(url, opts);
  const data = await res.json();
  if (!res.ok) throw new Error(data.error || res.statusText);
  return data;
}

function populateTables() {
  const sel = $('tableSel');
  sel.innerHTML = '';
  const names = (window.TABLE_NAMES || []).concat(['graph']);
  names.forEach((name) => {
    const opt = document.createElement('option');
    opt.value = name; opt.textContent = name;
    sel.appendChild(opt);
  });
}

function escapeHtml(s) {
  const div = document.createElement('div');
  div.textContent = s;
  return div.innerHTML;
}

async function loadWorkbook() {
  const path = $('path').value.trim();
  if (!path) { setStatus('Enter a workbook path first.', true); return; }
  setStatus('Loading ' + path + ' ...');
  try {
    const data = await fetchJSON('/load', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({path}),
    });
    setStatus('Loaded: ' + data.path);
    $('controls').style.display = 'flex';
    const dashSel = $('dashboardSel');
    dashSel.innerHTML = '<option value="">(all)</option>';
    (data.dashboards || []).forEach((name) => {
      const opt = document.createElement('option');
      opt.value = name; opt.textContent = name;
      dashSel.appendChild(opt);
    });
    await showTable();
  } catch (e) {
    setStatus('Error: ' + e.message, true);
  }
}

async function showTable() {
  const name = $('tableSel').value;
  $('dashboardWrap').style.display = name === 'dashboard-sheets' ? '' : 'none';
  $('paramsWrap').style.display = name === 'calculated-fields' ? '' : 'none';
  $('inferredWrap').style.display = name === 'graph' ? '' : 'none';
  $('exportBtn').textContent = name === 'graph' ? 'Export DOT' : 'Export CSV';

  if (name === 'graph') {
    const params = new URLSearchParams();
    if ($('includeInferred').checked) params.set('include_inferred', 'true');
    try {
      const data = await fetchJSON('/graph?' + params.toString());
      $('tableWrap').innerHTML = '<pre>' + escapeHtml(data.dot) + '</pre>';
      $('meta').textContent = data.dot.split('\\n').length + ' line(s)';
      $('exportLink').href = '/graph?' + params.toString() + '&download=1';
    } catch (e) {
      setStatus('Error: ' + e.message, true);
    }
    return;
  }

  const params = new URLSearchParams({name});
  if (name === 'dashboard-sheets' && $('dashboardSel').value) {
    params.set('dashboard', $('dashboardSel').value);
  }
  if (name === 'calculated-fields' && $('includeParams').checked) {
    params.set('include_parameters', 'true');
  }
  try {
    const data = await fetchJSON('/table?' + params.toString());
    $('tableWrap').innerHTML = data.html;
    $('meta').textContent = data.rows + ' row(s)';
    $('exportLink').href = '/export?' + params.toString();
  } catch (e) {
    setStatus('Error: ' + e.message, true);
  }
}

$('loadBtn').addEventListener('click', loadWorkbook);
$('path').addEventListener('keydown', (e) => { if (e.key === 'Enter') loadWorkbook(); });
$('tableSel').addEventListener('change', showTable);
$('dashboardSel').addEventListener('change', showTable);
$('includeParams').addEventListener('change', showTable);
$('includeInferred').addEventListener('change', showTable);

populateTables();
if (window.PRELOAD_PATH) {
  $('path').value = window.PRELOAD_PATH;
  loadWorkbook();
}
</script>
</body>
</html>
"""


class Handler(BaseHTTPRequestHandler):
    server_version = "twbparser-gui/0.1"

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
        df = TABLE_SPECS[name](
            _STATE["parser"], dashboard=dashboard, include_parameters=include_parameters
        )
        return df, name

    def do_GET(self):  # noqa: N802 (stdlib method name)
        parsed = urlparse(self.path)
        qs = parse_qs(parsed.query)

        if parsed.path == "/":
            page = _PAGE.replace(
                "populateTables();",
                f"window.TABLE_NAMES = {json.dumps(TABLE_NAMES)};\n"
                f"window.PRELOAD_PATH = {json.dumps(_STATE['path'])};\n"
                "populateTables();",
            )
            self._send(200, page)
            return

        if parsed.path == "/tables":
            self._send_json({"tables": TABLE_NAMES})
            return

        if parsed.path == "/table":
            if _STATE["parser"] is None:
                self._send_json({"error": "No workbook loaded"}, 400)
                return
            df, name = self._table_df(qs)
            if df is None:
                self._send_json({"error": f"unknown table '{name}'"}, 404)
                return
            self._send_json({"html": _df_to_html(df), "rows": int(len(df))})
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
            df, name = self._table_df(qs)
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

        self._send(404, "not found", "text/plain")

    def do_POST(self):  # noqa: N802
        if self.path != "/load":
            self._send(404, "not found", "text/plain")
            return

        length = int(self.headers.get("Content-Length", 0) or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            payload = json.loads(raw or b"{}")
        except json.JSONDecodeError:
            self._send_json({"error": "malformed JSON body"}, 400)
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
                "dashboards": dashboards_df["name"].tolist()
                if "name" in dashboards_df.columns
                else [],
            }
        )


def build_arg_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="twbparser-gui", description="Local browser GUI for twbparser_py."
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
    print(f"twbparser GUI running at {url} (Ctrl+C to stop)")

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
