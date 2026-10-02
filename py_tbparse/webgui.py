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


_PAGE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>py-tbparse</title>
<style>
  :root {
    color-scheme: light dark;
    --bg: #f5f6f8;
    --panel: #ffffff;
    --text: #1c222b;
    --muted: #5d6877;
    --border: #e2e5ea;
    --accent: #2c6bd9;
    --accent-text: #ffffff;
    --accent-soft: #e7effc;
    --hover: #f2f5fa;
    --code-bg: #f1f3f6;
    --danger: #c0392b;
    --mono: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  }
  @media (prefers-color-scheme: dark) {
    :root {
      --bg: #0f1216;
      --panel: #171b21;
      --text: #e5e8ed;
      --muted: #97a1b0;
      --border: #2a3039;
      --accent: #6b9dff;
      --accent-text: #0f1216;
      --accent-soft: #1c2940;
      --hover: #1d232b;
      --code-bg: #11151a;
      --danger: #ff6b5b;
    }
  }
  * { box-sizing: border-box; }
  [hidden] { display: none !important; }
  html, body { margin: 0; }
  body { font: 14px/1.45 system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
         background: var(--bg); color: var(--text); }
  :focus-visible { outline: 2px solid var(--accent); outline-offset: 1px; }

  /* top bar */
  .top { position: sticky; top: 0; z-index: 10; background: var(--panel);
         border-bottom: 1px solid var(--border); }
  .bar { display: flex; flex-wrap: wrap; gap: 10px 20px; align-items: center; padding: 10px 20px; }
  .brand { display: flex; align-items: center; gap: 9px; font-weight: 650; font-size: 15px; }
  .brand svg { color: var(--accent); }
  .brand .ver { font-weight: 400; font-size: 12px; color: var(--muted); }
  .open { flex: 1; display: flex; gap: 8px; min-width: 260px; }
  #status { padding: 0 20px 8px; margin-top: -2px; font-size: 12.5px; color: var(--muted);
            min-height: 1.4em; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  #status.err { color: var(--danger); }

  /* controls */
  .field { height: 34px; padding: 0 10px; border: 1px solid var(--border); border-radius: 7px;
           background: var(--bg); color: inherit; font: inherit; min-width: 0; }
  .open .field { flex: 1; font-family: var(--mono); font-size: 13px; }
  .btn { display: inline-flex; align-items: center; gap: 6px; height: 34px; padding: 0 14px;
         border: 1px solid var(--border); border-radius: 7px; background: var(--panel);
         color: inherit; font: inherit; text-decoration: none; cursor: pointer; white-space: nowrap; }
  .btn:hover { background: var(--hover); }
  .btn.primary { background: var(--accent); border-color: var(--accent); color: var(--accent-text);
                 font-weight: 600; }
  .btn.primary:hover { filter: brightness(1.08); }
  .btn:disabled { opacity: .6; cursor: progress; }
  .btn.small { height: 28px; padding: 0 10px; font-size: 12.5px; }
  .rename-tools { display: inline-flex; flex-wrap: wrap; gap: 8px; align-items: center; }
  .rename-tools input[type=text] { width: 260px; font-family: var(--mono); font-size: 13px; }
  .check { display: inline-flex; align-items: center; gap: 6px; font-size: 13px; color: var(--muted);
           cursor: pointer; white-space: nowrap; }
  select.field { padding-right: 4px; }

  /* start screen */
  .hero { max-width: 580px; margin: 12vh auto 0; padding: 0 20px; text-align: center; }
  .hero svg { color: var(--accent); }
  .hero h1 { font-size: 22px; margin: 14px 0 8px; }
  .hero p { color: var(--muted); margin: 6px 0; }
  code, kbd { font-family: var(--mono); font-size: 12.5px; background: var(--code-bg);
              border: 1px solid var(--border); border-radius: 5px; padding: 1px 6px; }

  /* workspace */
  .workspace { display: grid; grid-template-columns: 240px minmax(0, 1fr); gap: 16px;
               padding: 16px 20px 20px; align-items: start; }
  .side { position: sticky; top: 88px; max-height: calc(100vh - 108px); overflow: auto;
          background: var(--panel); border: 1px solid var(--border); border-radius: 10px; padding: 10px 8px; }
  .wb { padding: 4px 8px 12px; margin-bottom: 4px; border-bottom: 1px solid var(--border); }
  .label { font-size: 11px; font-weight: 600; letter-spacing: .06em; text-transform: uppercase;
           color: var(--muted); }
  .wb .name { font-weight: 600; margin-top: 2px; overflow-wrap: anywhere; }
  .nav-group { padding: 12px 8px 4px; }
  .nav-item { display: flex; justify-content: space-between; align-items: center; gap: 8px; width: 100%;
              padding: 6px 8px; border: 0; border-radius: 6px; background: none; color: inherit;
              font: inherit; text-align: left; cursor: pointer; }
  .nav-item:hover { background: var(--hover); }
  .nav-item[aria-current="page"] { background: var(--accent-soft); color: var(--accent); font-weight: 600; }
  .count { font-size: 12px; color: var(--muted); font-variant-numeric: tabular-nums; }
  .count.zero { opacity: .45; }
  .nav-item[aria-current="page"] .count { color: inherit; }

  .view { background: var(--panel); border: 1px solid var(--border); border-radius: 10px; min-width: 0; }
  .view-head { display: flex; flex-wrap: wrap; gap: 12px 16px; align-items: center;
               justify-content: space-between; padding: 14px 16px 12px; border-bottom: 1px solid var(--border); }
  .view-head h2 { margin: 0; font-size: 17px; }
  .desc { color: var(--muted); font-size: 13px; margin-top: 2px; }
  .toolbar { display: flex; flex-wrap: wrap; gap: 8px 12px; align-items: center; }
  #filter { width: 220px; }
  .subbar { display: flex; justify-content: space-between; gap: 12px; padding: 6px 16px;
            font-size: 12px; color: var(--muted); border-bottom: 1px solid var(--border); min-height: 29px; }
  .mobile-only { display: none; }

  /* tables */
  #tableWrap { overflow: auto; max-height: calc(100vh - 250px); }
  .tbl { border-collapse: separate; border-spacing: 0; width: 100%; font-size: 13px; }
  .tbl th { position: sticky; top: 0; z-index: 1; background: var(--panel); text-align: left;
            font-weight: 600; padding: 8px 12px; border-bottom: 1px solid var(--border);
            white-space: nowrap; cursor: pointer; user-select: none; }
  .tbl th:hover { color: var(--accent); }
  .tbl th .arrow { display: inline-block; width: 1em; margin-left: 2px; color: var(--accent); }
  .tbl td { padding: 7px 12px; border-bottom: 1px solid var(--border); white-space: nowrap;
            max-width: 380px; overflow: hidden; text-overflow: ellipsis; vertical-align: top; }
  .tbl tbody tr { cursor: pointer; }
  .tbl tbody tr:hover { background: var(--hover); }
  .tbl tbody tr.open td { white-space: pre-wrap; overflow-wrap: anywhere; max-width: none; }
  .tbl td.num { text-align: right; font-variant-numeric: tabular-nums; }
  .tbl td.code { font-family: var(--mono); font-size: 12px; }
  .null { color: var(--muted); opacity: .55; }
  .pill { display: inline-block; padding: 0 8px; border-radius: 999px; font-size: 11.5px;
          background: var(--code-bg); color: var(--muted); }
  .pill.yes { background: var(--accent-soft); color: var(--accent); }

  /* overview tiles */
  .cards { display: grid; grid-template-columns: repeat(auto-fill, minmax(170px, 1fr)); gap: 12px; padding: 16px; }
  .stat { display: block; text-align: left; padding: 14px 14px 12px; border: 1px solid var(--border);
          border-radius: 10px; background: var(--bg); color: inherit; font: inherit; cursor: pointer; }
  .stat:hover { border-color: var(--accent); }
  .stat .n { font-size: 26px; font-weight: 650; font-variant-numeric: tabular-nums; line-height: 1.2; }
  .stat .l { color: var(--muted); font-size: 12.5px; }
  .stat.zero .n { color: var(--muted); }

  .dot { margin: 0; padding: 16px; font: 12.5px/1.55 var(--mono); white-space: pre; background: var(--code-bg); }
  .empty-state { padding: 56px 16px; text-align: center; color: var(--muted); }
  .empty-state strong { display: block; color: var(--text); font-size: 15px; margin-bottom: 4px; }

  @media (max-width: 760px) {
    .workspace { grid-template-columns: 1fr; padding: 12px; }
    .side { display: none; }
    .mobile-only { display: inline-flex; }
    .bar, #status { padding-left: 12px; padding-right: 12px; }
    #filter { width: 100%; }
    .toolbar { width: 100%; }
    #tableWrap { max-height: none; }
  }
</style>
</head>
<body>
<header class="top">
  <div class="bar">
    <div class="brand">
      <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><path d="M17.5 14v7M14 17.5h7"/></svg>
      py-tbparse <span class="ver" id="version"></span>
    </div>
    <div class="open">
      <input id="path" class="field" type="text" placeholder="/path/to/workbook.twb or .twbx"
             aria-label="Workbook path" spellcheck="false" autocomplete="off">
      <button id="loadBtn" class="btn primary" type="button">Load</button>
    </div>
  </div>
  <div id="status" role="status" aria-live="polite"></div>
</header>

<section id="empty" class="hero">
  <svg width="44" height="44" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" aria-hidden="true"><path d="M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z"/><path d="M14 3v6h6M8 13h8M8 17h5"/></svg>
  <h1>Open a Tableau workbook</h1>
  <p>Paste the path to a <code>.twb</code> or <code>.twbx</code> file above and press Load.</p>
  <p>Parsing happens locally; the workbook never leaves this machine.</p>
  <p>Tip: start with <code>py-tbparse-gui path/to/book.twbx</code> to open one directly.</p>
</section>

<div id="controls" class="workspace" hidden>
  <aside class="side" aria-label="Tables">
    <div class="wb">
      <div class="label">Workbook</div>
      <div class="name" id="wbName"></div>
    </div>
    <nav id="nav"></nav>
  </aside>

  <main class="view">
    <div class="view-head">
      <div>
        <h2 id="viewTitle"></h2>
        <div class="desc" id="viewDesc"></div>
      </div>
      <div class="toolbar">
        <label class="mobile-only" aria-label="Table">
          <select id="tableSel" class="field"></select>
        </label>
        <input id="filter" class="field" type="search" placeholder="Filter rows  ( / )" aria-label="Filter rows">
        <label id="dashboardWrap" class="check" hidden>Dashboard
          <select id="dashboardSel" class="field"><option value="">(all)</option></select>
        </label>
        <label id="paramsWrap" class="check" hidden>
          <input type="checkbox" id="includeParams"> Include parameters
        </label>
        <label id="inferredWrap" class="check" hidden>
          <input type="checkbox" id="includeInferred"> Include inferred (dashed)
        </label>
        <span id="renameTools" class="rename-tools" hidden>
          <select id="renameStyle" class="field" aria-label="Naming style">
            <option value="title">Title Case</option><option value="snake">snake_case</option>
            <option value="lower">lower case</option><option value="keep">Keep case</option>
          </select>
          <select id="renameDs" class="field" aria-label="Datasource">
            <option value="">(all datasources)</option>
          </select>
          <select id="renameKinds" class="field" aria-label="What to rename">
            <option value="">Fields only</option><option value="all">Everything in the report</option>
          </select>
          <input id="renameRef" class="field" type="text" spellcheck="false"
                 placeholder="Reference workbook path (optional)" aria-label="Reference workbook path">
          <label class="check"><input type="checkbox" id="renameChanged" checked> Only changes</label>
          <button id="createBtn" class="btn primary" type="button">Create fixed workbook</button>
          <a id="downloadBtn" class="btn" href="#" download>Download fixed workbook</a>
        </span>
        <button id="copyBtn" class="btn" type="button" hidden>Copy</button>
        <a id="exportLink" class="btn" href="#" download><span id="exportBtn">Export CSV</span></a>
      </div>
    </div>
    <div class="subbar">
      <span id="meta"></span>
      <span id="hint">Click a column to sort, a row to expand it.</span>
    </div>
    <div id="tableWrap"></div>
  </main>
</div>

<script>
const $ = (id) => document.getElementById(id);
const statusEl = $('status');

// Sidebar grouping. Tables missing here (new ones added to _tables.py)
// still show up, under "Other", so the registry stays the source of truth.
const GROUPS = [
  ['Workbook', ['overview', 'published-refs']],
  ['Data', ['datasources', 'parameters', 'fields', 'raw-fields', 'calculated-fields', 'field-renames']],
  ['Data model', ['relationships', 'joins', 'relations', 'inferred-relationships', 'graph']],
  ['Dashboards', ['dashboards', 'dashboard-sheets']],
  ['SQL', ['custom-sql', 'initial-sql']],
];

const INFO = {
  'overview': ['Overview', 'Counts of everything parsed from the workbook.'],
  'datasources': ['Datasources', 'Connections and their primary tables.'],
  'parameters': ['Parameters', 'Workbook parameters and their current values.'],
  'fields': ['Fields', 'Every column across all datasources.'],
  'raw-fields': ['Raw fields', 'Columns that come straight from the source.'],
  'calculated-fields': ['Calculated fields', 'Calculations and their formulas.'],
  'field-renames': ['Field renames', 'Suggested clean names. Create a copy of the workbook with them applied.'],
  'joins': ['Joins', 'Join clauses from the physical layer.'],
  'relations': ['Relations', 'Physical tables and custom SQL relations.'],
  'relationships': ['Relationships', 'Logical-layer relationships (Tableau 2020.2+).'],
  'inferred-relationships': ['Inferred relationships', 'Likely links guessed from matching field names.'],
  'dashboards': ['Dashboards', 'Dashboards defined in the workbook.'],
  'dashboard-sheets': ['Dashboard sheets', 'Sheets placed on each dashboard, with positions.'],
  'custom-sql': ['Custom SQL', 'Relations defined by custom SQL.'],
  'initial-sql': ['Initial SQL', 'SQL run when a connection opens.'],
  'published-refs': ['Published sources', 'References to published datasources.'],
  'graph': ['Relationship graph', 'Joins and relationships as Graphviz DOT.'],
};

// Overview columns that have a table of their own to jump to.
const OVERVIEW_LINKS = {
  datasources: 'datasources', parameters: 'parameters', relationships: 'relationships',
  // raw_fields counts every field (as upstream R does), so it opens Fields.
  calculated_fields: 'calculated-fields', raw_fields: 'fields',
  inferred_relationships: 'inferred-relationships', dashboards: 'dashboards',
};

const CODE_COLUMNS = new Set(['formula', 'custom_sql', 'initial_sql', 'connection_target']);

const state = { table: 'overview', columns: [], data: [], sortCol: -1, sortDir: 0,
                loaded: false, req: 0, dot: '' };

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

function titleOf(name) { return (INFO[name] || [name])[0]; }

function allTables() { return (window.TABLE_NAMES || []).concat(['graph']); }

function el(tag, cls, text) {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text !== undefined) node.textContent = text;
  return node;
}

function populateTables() {
  const names = allTables();
  const sel = $('tableSel');
  sel.innerHTML = '';
  names.forEach((name) => {
    const opt = document.createElement('option');
    opt.value = name; opt.textContent = titleOf(name);
    sel.appendChild(opt);
  });

  const nav = $('nav');
  nav.innerHTML = '';
  const placed = new Set();
  const groups = GROUPS.map(([title, items]) => {
    const present = items.filter((n) => names.includes(n));
    present.forEach((n) => placed.add(n));
    return [title, present];
  });
  const other = names.filter((n) => !placed.has(n));
  if (other.length) groups.push(['Other', other]);

  groups.forEach(([title, items]) => {
    if (!items.length) return;
    nav.appendChild(el('div', 'label nav-group', title));
    items.forEach((name) => {
      const item = el('button', 'nav-item');
      item.type = 'button';
      item.dataset.table = name;
      item.appendChild(el('span', '', titleOf(name)));
      // The overview is always one row and the graph is not a table.
      if (name !== 'overview' && name !== 'graph') {
        const count = el('span', 'count');
        count.dataset.countFor = name;
        item.appendChild(count);
      }
      item.addEventListener('click', () => selectTable(name));
      nav.appendChild(item);
    });
  });
  if (window.APP_VERSION) $('version').textContent = 'v' + window.APP_VERSION;
}

function setCounts(counts) {
  document.querySelectorAll('[data-count-for]').forEach((node) => {
    const n = counts ? counts[node.dataset.countFor] : undefined;
    node.textContent = (n === undefined || n === null) ? '' : String(n);
    node.classList.toggle('zero', n === 0);
  });
}

function markCurrent() {
  document.querySelectorAll('.nav-item').forEach((item) => {
    if (item.dataset.table === state.table) item.setAttribute('aria-current', 'page');
    else item.removeAttribute('aria-current');
  });
  $('tableSel').value = state.table;
}

function selectTable(name) {
  if (!allTables().includes(name)) return;
  const changed = name !== state.table;
  state.table = name;
  if (changed) { $('filter').value = ''; state.sortCol = -1; state.sortDir = 0; }
  markCurrent();
  if (location.hash !== '#' + name) history.replaceState(null, '', '#' + name);
  showTable();
}

async function loadWorkbook() {
  const path = $('path').value.trim();
  if (!path) { setStatus('Enter a workbook path first.', true); return; }
  setStatus('Loading ' + path + ' ...');
  const btn = $('loadBtn');
  btn.disabled = true; btn.textContent = 'Loading';
  try {
    const data = await fetchJSON('/load', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({path}),
    });
    setStatus('Loaded: ' + data.path);
    state.loaded = true;
    $('empty').hidden = true;
    $('controls').hidden = false;
    $('wbName').textContent = data.name || data.path;
    $('wbName').title = data.path;
    document.title = (data.name || 'workbook') + ' - py-tbparse';
    setCounts(data.counts);
    const dsSel = $('renameDs');
    dsSel.innerHTML = '<option value="">(all datasources)</option>';
    (data.datasources || []).forEach((name) => {
      const opt = document.createElement('option');
      opt.value = name; opt.textContent = name;
      dsSel.appendChild(opt);
    });
    const dashSel = $('dashboardSel');
    dashSel.innerHTML = '<option value="">(all)</option>';
    (data.dashboards || []).forEach((name) => {
      const opt = document.createElement('option');
      opt.value = name; opt.textContent = name;
      dashSel.appendChild(opt);
    });
    const fromHash = decodeURIComponent(location.hash.slice(1));
    if (allTables().includes(fromHash)) state.table = fromHash;
    markCurrent();
    await showTable();
  } catch (e) {
    setStatus('Error: ' + e.message, true);
  } finally {
    btn.disabled = false; btn.textContent = 'Load';
  }
}

async function showTable() {
  const name = state.table;
  const isGraph = name === 'graph';
  const isOverview = name === 'overview';
  $('viewTitle').textContent = titleOf(name);
  $('viewDesc').textContent = (INFO[name] || ['', ''])[1];
  $('dashboardWrap').hidden = name !== 'dashboard-sheets';
  $('paramsWrap').hidden = name !== 'calculated-fields';
  $('inferredWrap').hidden = !isGraph;
  $('copyBtn').hidden = !isGraph;
  $('renameTools').hidden = name !== 'field-renames';
  $('filter').hidden = isGraph || isOverview;
  $('hint').hidden = isGraph || isOverview;
  $('exportBtn').textContent = isGraph ? 'Export DOT' : 'Export CSV';
  const req = ++state.req;

  if (isGraph) {
    const params = new URLSearchParams();
    if ($('includeInferred').checked) params.set('include_inferred', 'true');
    // Set before the request so the link never points at the previous view.
    $('exportLink').href = '/graph?' + params.toString() + '&download=1';
    try {
      const data = await fetchJSON('/graph?' + params.toString());
      if (req !== state.req) return;
      state.dot = data.dot;
      const wrap = $('tableWrap');
      wrap.innerHTML = '';
      wrap.appendChild(el('pre', 'dot', data.dot));
      $('meta').textContent = data.dot.split('\n').length + ' line(s)';
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
  if (name === 'field-renames') {
    const opts = renameOptions();
    Object.entries(opts).forEach(([k, v]) => { if (v) params.set(k, v); });
    if ($('renameChanged').checked) params.set('only_changed', 'true');
    $('downloadBtn').href = '/download-workbook?' + new URLSearchParams(opts).toString();
  }
  $('exportLink').href = '/export?' + params.toString();
  try {
    const data = await fetchJSON('/table?' + params.toString());
    if (req !== state.req) return;
    state.columns = data.columns || [];
    state.data = data.data || [];
    if (isOverview) renderOverview(); else renderTable();
  } catch (e) {
    setStatus('Error: ' + e.message, true);
  }
}

function renameOptions() {
  const opts = {style: $('renameStyle').value};
  if ($('renameDs').value) opts.datasource = $('renameDs').value;
  if ($('renameKinds').value) opts.kinds = $('renameKinds').value;
  const ref = $('renameRef').value.trim();
  if (ref) opts.reference = ref;
  return opts;
}

async function createWorkbook() {
  const btn = $('createBtn');
  btn.disabled = true;
  setStatus('Creating workbook ...');
  try {
    const data = await fetchJSON('/create-workbook', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(renameOptions()),
    });
    setStatus('Saved ' + data.renamed + ' rename(s) to ' + data.path);
  } catch (e) {
    setStatus('Error: ' + e.message, true);
  } finally {
    btn.disabled = false;
  }
}

function renderOverview() {
  const wrap = $('tableWrap');
  wrap.innerHTML = '';
  $('meta').textContent = 'Summary';
  const row = state.data[0] || [];
  const cards = el('div', 'cards');
  state.columns.forEach((col, i) => {
    if (col === 'file') return;
    const target = OVERVIEW_LINKS[col];
    const value = row[i];
    const card = el(target ? 'button' : 'div', 'stat');
    if (target) {
      card.type = 'button';
      card.dataset.goto = target;
      card.addEventListener('click', () => selectTable(target));
    }
    if (value === 0) card.classList.add('zero');
    card.append(el('div', 'n', value === null ? '-' : String(value)),
                el('div', 'l', col.split('_').join(' ')));
    cards.appendChild(card);
  });
  wrap.appendChild(cards);
}

function compareValues(a, b) {
  if (typeof a === 'number' && typeof b === 'number') return a - b;
  return String(a).localeCompare(String(b), undefined, {numeric: true, sensitivity: 'base'});
}

function visibleRows() {
  const q = $('filter').value.trim().toLowerCase();
  let rows = state.data;
  if (q) {
    rows = rows.filter((r) => r.some((v) => v !== null && String(v).toLowerCase().includes(q)));
  }
  if (state.sortCol >= 0) {
    const i = state.sortCol;
    const dir = state.sortDir;
    rows = rows.slice().sort((a, b) => {
      const x = a[i], y = b[i];
      if (x === null || y === null) return (x === null) - (y === null);
      return dir * compareValues(x, y);
    });
  }
  return rows;
}

function toggleSort(i) {
  if (state.sortCol !== i) { state.sortCol = i; state.sortDir = 1; }
  else if (state.sortDir === 1) { state.sortDir = -1; }
  else { state.sortCol = -1; state.sortDir = 0; }
  renderTable();
}

function cellNode(col, value) {
  const td = el('td');
  if (value === null || value === '') {
    td.appendChild(el('span', 'null', '-'));
  } else if (typeof value === 'boolean') {
    td.appendChild(el('span', value ? 'pill yes' : 'pill', value ? 'yes' : 'no'));
  } else {
    if (typeof value === 'number') td.className = 'num';
    else if (CODE_COLUMNS.has(col)) td.className = 'code';
    td.textContent = String(value);
    td.title = String(value);
  }
  return td;
}

function emptyState(title, text) {
  const box = el('div', 'empty-state');
  box.append(el('strong', '', title), el('span', '', text));
  return box;
}

function renderTable() {
  const wrap = $('tableWrap');
  wrap.innerHTML = '';
  const total = state.data.length;
  if (!total) {
    $('meta').textContent = '0 row(s)';
    wrap.appendChild(emptyState('Nothing here', 'This workbook has no rows in this table.'));
    return;
  }
  const rows = visibleRows();
  const filtered = $('filter').value.trim() !== '';
  $('meta').textContent = filtered ? rows.length + ' of ' + total + ' row(s)' : total + ' row(s)';

  const table = el('table', 'tbl');
  const headRow = el('tr');
  state.columns.forEach((col, i) => {
    const th = el('th');
    th.tabIndex = 0;
    const sorted = state.sortCol === i;
    th.setAttribute('aria-sort', sorted ? (state.sortDir === 1 ? 'ascending' : 'descending') : 'none');
    th.append(el('span', '', col), el('span', 'arrow', sorted ? (state.sortDir === 1 ? '▲' : '▼') : ''));
    th.addEventListener('click', () => toggleSort(i));
    th.addEventListener('keydown', (e) => { if (e.key === 'Enter') toggleSort(i); });
    headRow.appendChild(th);
  });
  table.appendChild(el('thead')).appendChild(headRow);

  const body = el('tbody');
  rows.forEach((r) => {
    const tr = el('tr');
    r.forEach((v, i) => tr.appendChild(cellNode(state.columns[i], v)));
    tr.addEventListener('click', () => tr.classList.toggle('open'));
    body.appendChild(tr);
  });
  table.appendChild(body);
  wrap.appendChild(table);
  if (!rows.length) wrap.appendChild(emptyState('No matches', 'No rows contain that text.'));
}

async function copyDot() {
  try {
    await navigator.clipboard.writeText(state.dot);
    $('copyBtn').textContent = 'Copied';
  } catch (e) {
    $('copyBtn').textContent = 'Copy failed';
  }
  setTimeout(() => { $('copyBtn').textContent = 'Copy'; }, 1500);
}

$('loadBtn').addEventListener('click', loadWorkbook);
$('path').addEventListener('keydown', (e) => { if (e.key === 'Enter') loadWorkbook(); });
$('tableSel').addEventListener('change', () => selectTable($('tableSel').value));
$('dashboardSel').addEventListener('change', showTable);
$('includeParams').addEventListener('change', showTable);
$('includeInferred').addEventListener('change', showTable);
$('copyBtn').addEventListener('click', copyDot);
$('filter').addEventListener('input', renderTable);
['renameStyle', 'renameDs', 'renameKinds', 'renameRef', 'renameChanged'].forEach((id) =>
  $(id).addEventListener('change', showTable));
$('createBtn').addEventListener('click', createWorkbook);
$('filter').addEventListener('keydown', (e) => {
  if (e.key === 'Escape') { $('filter').value = ''; renderTable(); }
});
document.addEventListener('keydown', (e) => {
  const typing = ['INPUT', 'SELECT', 'TEXTAREA'].includes(document.activeElement.tagName);
  if (e.key === '/' && !typing && state.loaded && !$('filter').hidden) {
    e.preventDefault();
    $('filter').focus();
  }
});
window.addEventListener('hashchange', () => {
  const name = decodeURIComponent(location.hash.slice(1));
  if (state.loaded && name !== state.table) selectTable(name);
});

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
            page = _PAGE.replace(
                "populateTables();",
                f"window.TABLE_NAMES = {_json_for_script(TABLE_NAMES)};\n"
                f"window.PRELOAD_PATH = {_json_for_script(_STATE['path'])};\n"
                f"window.APP_VERSION = {_json_for_script(__version__)};\n"
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
