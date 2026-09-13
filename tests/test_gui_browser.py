"""End-to-end GUI tests that drive a real headless Chromium via Playwright.

These exist because the endpoint-level tests in `test_webgui.py` cannot
see the page's JavaScript at all: a syntax error that killed the entire
<script> block (and with it the whole UI) once shipped with the full
suite green. Anything asserted here is asserted against a browser that
actually parsed and ran the page.

Skipped automatically when Playwright or its browser binary isn't
available, so the default `pytest` run still works without a ~115MB
browser download:

    pip install -e ".[browser]"
    playwright install chromium
    # on a machine without root, see scripts/setup-browser-libs.sh
"""

from __future__ import annotations

import os
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from twbparser_py import webgui

sync_playwright = pytest.importorskip(
    "playwright.sync_api", reason="playwright not installed"
).sync_playwright

_REPO_ROOT = Path(__file__).resolve().parent.parent
_LOCAL_LIBS = _REPO_ROOT / ".browser-libs" / "root" / "usr" / "lib" / "x86_64-linux-gnu"


def _browser_env() -> dict:
    """Chromium needs a handful of system libraries. On a machine where
    they're installed system-wide (CI) the plain environment is fine; on
    one where they were unpacked locally instead of apt-installed (see
    scripts/setup-browser-libs.sh), point the loader at them."""
    env = dict(os.environ)
    if _LOCAL_LIBS.is_dir():
        existing = env.get("LD_LIBRARY_PATH", "")
        env["LD_LIBRARY_PATH"] = f"{_LOCAL_LIBS}:{existing}" if existing else str(_LOCAL_LIBS)
    return env


@pytest.fixture(scope="session")
def browser():
    with sync_playwright() as pw:
        try:
            instance = pw.chromium.launch(env=_browser_env())
        except Exception as e:  # browser binary or system libs missing
            pytest.skip(f"chromium could not launch: {str(e)[:200]}")
        yield instance
        instance.close()


@pytest.fixture
def gui_server():
    webgui._STATE["parser"] = None
    webgui._STATE["path"] = None
    srv = ThreadingHTTPServer(("127.0.0.1", 0), webgui.Handler)
    host, port = srv.server_address
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://{host}:{port}"
    finally:
        srv.shutdown()
        thread.join(timeout=2)


@pytest.fixture
def page(browser, gui_server):
    """A page on the running GUI, with JS errors recorded on `page.js_errors`."""
    ctx = browser.new_context()
    pg = ctx.new_page()
    pg.js_errors = []
    pg.on("pageerror", lambda e: pg.js_errors.append(str(e)))
    pg.on(
        "console",
        lambda msg: pg.js_errors.append(f"console.{msg.type}: {msg.text}")
        if msg.type == "error"
        else None,
    )
    pg.goto(gui_server)
    yield pg
    ctx.close()


def _load(page, path):
    page.fill("#path", path)
    page.click("#loadBtn")
    page.wait_for_function(
        "() => document.getElementById('status').textContent.startsWith('Loaded:')",
        timeout=10_000,
    )


# --- the regression that motivated this file ---------------------------------


def test_page_loads_with_no_js_errors(page):
    # A SyntaxError anywhere in the inline <script> aborts the whole
    # block, leaving a page that renders but does nothing.
    assert page.js_errors == []


def test_table_dropdown_is_populated(page):
    # Empty dropdown == populateTables() never ran == dead script.
    options = page.eval_on_selector_all("#tableSel option", "els => els.map(e => e.value)")
    assert "overview" in options
    assert "graph" in options
    assert len(options) > 10


# --- core interaction flow ---------------------------------------------------


def test_load_workbook_renders_a_table(page, wenjie_path):
    _load(page, wenjie_path)
    assert page.is_visible("#controls")
    assert page.eval_on_selector("#tableWrap", "el => el.querySelectorAll('table').length") == 1
    assert "row(s)" in page.text_content("#meta")
    assert page.js_errors == []


def test_switching_table_updates_the_view(page, wenjie_path):
    _load(page, wenjie_path)
    page.select_option("#tableSel", "datasources")
    page.wait_for_function(
        "() => document.getElementById('meta').textContent === '2 row(s)'", timeout=10_000
    )
    body = page.text_content("#tableWrap")
    assert "Municipal_Boundaries_of_NJ" in body
    assert page.js_errors == []


def test_dashboard_filter_only_shows_for_dashboard_sheets(page, wenjie_path):
    _load(page, wenjie_path)
    assert not page.is_visible("#dashboardWrap")
    page.select_option("#tableSel", "dashboard-sheets")
    page.wait_for_selector("#dashboardWrap", state="visible", timeout=10_000)
    page.select_option("#tableSel", "fields")
    page.wait_for_selector("#dashboardWrap", state="hidden", timeout=10_000)


def test_include_parameters_only_shows_for_calculated_fields(page, wenjie_path):
    _load(page, wenjie_path)
    assert not page.is_visible("#paramsWrap")
    page.select_option("#tableSel", "calculated-fields")
    page.wait_for_selector("#paramsWrap", state="visible", timeout=10_000)


# --- graph view: the exact code path the syntax error lived in ---------------


def test_graph_view_renders_dot_and_counts_lines(page, wenjie_path):
    # The broken line was the `split('\n')` that produces this line count,
    # so this asserts on the specific statement that was malformed.
    _load(page, wenjie_path)
    page.select_option("#tableSel", "graph")
    page.wait_for_function(
        "() => document.querySelector('#tableWrap pre') !== null", timeout=10_000
    )
    dot = page.text_content("#tableWrap pre")
    assert dot.startswith('digraph "twb" {')
    assert "Sheet1" in dot

    meta = page.text_content("#meta")
    assert meta.endswith("line(s)")
    assert int(meta.split()[0]) == len(dot.splitlines())
    assert page.js_errors == []


def test_graph_view_relabels_export_button(page, wenjie_path):
    _load(page, wenjie_path)
    assert page.text_content("#exportBtn") == "Export CSV"
    page.select_option("#tableSel", "graph")
    page.wait_for_function(
        "() => document.getElementById('exportBtn').textContent === 'Export DOT'",
        timeout=10_000,
    )
    assert page.is_visible("#inferredWrap")
    assert "download=1" in page.get_attribute("#exportLink", "href")


def test_export_link_points_at_the_current_table(page, wenjie_path):
    _load(page, wenjie_path)
    page.select_option("#tableSel", "fields")
    page.wait_for_function(
        "() => document.getElementById('exportLink').href.includes('name=fields')",
        timeout=10_000,
    )
    assert "/export?" in page.get_attribute("#exportLink", "href")


# --- error handling ----------------------------------------------------------


def test_bad_path_surfaces_an_error_in_the_ui(page):
    page.fill("#path", "/definitely/not/a/workbook.twb")
    page.click("#loadBtn")
    page.wait_for_function(
        "() => document.getElementById('status').textContent.startsWith('Error:')",
        timeout=10_000,
    )
    assert "err" in (page.get_attribute("#status", "class") or "")
    assert not page.is_visible("#controls")


def test_empty_path_is_rejected_client_side(page):
    page.click("#loadBtn")
    page.wait_for_function(
        "() => document.getElementById('status').textContent.includes('Enter a workbook path')",
        timeout=10_000,
    )
    assert not page.is_visible("#controls")
