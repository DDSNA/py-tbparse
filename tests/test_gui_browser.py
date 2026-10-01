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
import re
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from twbparser_py import webgui

_playwright_sync_api = pytest.importorskip("playwright.sync_api", reason="playwright not installed")
sync_playwright = _playwright_sync_api.sync_playwright
_PlaywrightError = _playwright_sync_api.Error

_REPO_ROOT = Path(__file__).resolve().parent.parent
_LOCAL_LIBS = _REPO_ROOT / ".browser-libs" / "root" / "usr" / "lib" / "x86_64-linux-gnu"
_LOCAL_XKB = _REPO_ROOT / ".browser-libs" / "root" / "usr" / "share" / "X11" / "xkb"
_LOCAL_FONTS_CONF = _REPO_ROOT / ".browser-libs" / "fonts.conf"


def _browser_env() -> dict:
    """Chromium needs a handful of system libraries. On a machine where
    they're installed system-wide (CI) the plain environment is fine; on
    one where they were unpacked locally instead of apt-installed (see
    scripts/setup-browser-libs.sh), point the loader at them."""
    env = dict(os.environ)
    if _LOCAL_LIBS.is_dir():
        existing = env.get("LD_LIBRARY_PATH", "")
        env["LD_LIBRARY_PATH"] = f"{_LOCAL_LIBS}:{existing}" if existing else str(_LOCAL_LIBS)
    # Keyboard layouts and fonts unpacked by the same script, if the host
    # has none of its own (otherwise key input is dropped / text can't render).
    if _LOCAL_XKB.is_dir():
        env.setdefault("XKB_CONFIG_ROOT", str(_LOCAL_XKB))
    if _LOCAL_FONTS_CONF.is_file():
        env.setdefault("FONTCONFIG_FILE", str(_LOCAL_FONTS_CONF))
    return env


@pytest.fixture(scope="session")
def browser():
    with sync_playwright() as pw:
        try:
            instance = pw.chromium.launch(env=_browser_env())
        except _PlaywrightError as e:
            # Playwright's own exception type for "the browser process
            # didn't come up" (missing binary, missing system libs, etc).
            # Deliberately NOT a bare `except Exception`: that would also
            # swallow bugs in this fixture itself (a bad kwarg, a renamed
            # API) as a silent, green "skipped" -- which is exactly the
            # false-confidence failure mode this whole test file exists to
            # catch for the GUI itself. Let anything else propagate as a
            # real test error.
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


def _open(page, name):
    """Switch tables the way a user does: via the sidebar."""
    page.click(f'.nav-item[data-table="{name}"]')
    page.wait_for_function(
        "n => document.querySelector('.nav-item[aria-current=page]').dataset.table === n",
        arg=name,
        timeout=10_000,
    )


def _wait_meta(page, text):
    page.wait_for_function(
        "t => document.getElementById('meta').textContent === t", arg=text, timeout=10_000
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


def test_sidebar_lists_every_table(page):
    items = page.eval_on_selector_all(".nav-item", "els => els.map(e => e.dataset.table)")
    options = page.eval_on_selector_all("#tableSel option", "els => els.map(e => e.value)")
    assert sorted(items) == sorted(options)


def test_start_screen_shows_until_a_workbook_loads(page, wenjie_path):
    assert page.is_visible("#empty")
    assert not page.is_visible("#controls")
    _load(page, wenjie_path)
    assert not page.is_visible("#empty")
    assert page.is_visible("#controls")


# --- core interaction flow ---------------------------------------------------


def test_load_workbook_shows_overview_tiles(page, wenjie_path):
    _load(page, wenjie_path)
    _wait_meta(page, "Summary")
    assert page.text_content("#wbName") == "test_for_wenjie.twb"
    assert page.text_content("#viewTitle") == "Overview"
    tiles = page.eval_on_selector_all(
        "#tableWrap .stat", "els => els.map(e => e.querySelector('.n').textContent)"
    )
    assert len(tiles) == 7
    assert "55" in tiles
    assert page.js_errors == []


def test_sidebar_shows_row_counts_after_load(page, wenjie_path):
    _load(page, wenjie_path)
    assert page.text_content('[data-count-for="fields"]') == "55"
    assert page.text_content('[data-count-for="datasources"]') == "2"
    assert "zero" in page.get_attribute('[data-count-for="joins"]', "class")


def test_overview_tile_opens_its_table(page, wenjie_path):
    _load(page, wenjie_path)
    _wait_meta(page, "Summary")
    page.click('.stat[data-goto="datasources"]')
    _wait_meta(page, "2 row(s)")
    assert page.get_attribute('.nav-item[data-table="datasources"]', "aria-current") == "page"


def test_overview_tile_counts_match_the_table_they_open(page, wenjie_path):
    _load(page, wenjie_path)
    _wait_meta(page, "Summary")
    for card in page.query_selector_all("#tableWrap .stat[data-goto]"):
        target = card.get_attribute("data-goto")
        n = card.query_selector(".n").text_content()
        assert page.text_content(f'[data-count-for="{target}"]') == n, target


def test_switching_table_updates_the_view(page, wenjie_path):
    _load(page, wenjie_path)
    _open(page, "datasources")
    _wait_meta(page, "2 row(s)")
    body = page.text_content("#tableWrap")
    assert "Municipal_Boundaries_of_NJ" in body
    assert page.eval_on_selector("#tableWrap", "el => el.querySelectorAll('table').length") == 1
    assert page.js_errors == []


def test_filter_narrows_rows_and_escape_clears_it(page, wenjie_path):
    _load(page, wenjie_path)
    _open(page, "fields")
    _wait_meta(page, "55 row(s)")
    page.fill("#filter", "pop20")
    page.wait_for_function(
        "() => document.getElementById('meta').textContent.endsWith('of 55 row(s)')",
        timeout=10_000,
    )
    shown = int(page.text_content("#meta").split()[0])
    assert 0 < shown < 55
    assert page.eval_on_selector_all("#tableWrap tbody tr", "els => els.length") == shown
    page.press("#filter", "Escape")
    _wait_meta(page, "55 row(s)")


def test_slash_key_focuses_the_filter(page, wenjie_path):
    _load(page, wenjie_path)
    _open(page, "fields")
    page.click("#viewTitle")
    page.keyboard.press("/")
    assert page.evaluate("() => document.activeElement.id") == "filter"


def test_clicking_a_header_sorts_the_column(page, wenjie_path):
    _load(page, wenjie_path)
    _open(page, "fields")
    _wait_meta(page, "55 row(s)")
    names_js = (
        "() => { const i = [...document.querySelectorAll('#tableWrap th')]"
        ".findIndex(th => th.textContent.startsWith('name'));"
        " return [...document.querySelectorAll('#tableWrap tbody tr')]"
        ".map(tr => tr.children[i].textContent); }"
    )
    header = "#tableWrap th:has-text('name') >> nth=0"
    before = page.evaluate(names_js)
    page.click(header)
    assert page.get_attribute(header, "aria-sort") == "ascending"
    asc = page.evaluate(names_js)
    # Locale collation (what the page uses) and Python ordering disagree
    # on punctuation, so compare against the page itself: same rows, and
    # descending mirrors ascending at both ends.
    assert sorted(asc) == sorted(before)
    assert asc != before
    page.click(header)
    assert page.get_attribute(header, "aria-sort") == "descending"
    desc = page.evaluate(names_js)
    assert desc[0] == asc[-1] and desc[-1] == asc[0]
    page.click(header)
    assert page.get_attribute(header, "aria-sort") == "none"
    assert page.evaluate(names_js) == before


def test_clicking_a_row_expands_it(page, wenjie_path):
    _load(page, wenjie_path)
    _open(page, "relations")
    _wait_meta(page, "6 row(s)")
    row = "#tableWrap tbody tr >> nth=2"
    page.click(row)
    assert "open" in page.get_attribute(row, "class")


def test_url_hash_picks_the_initial_table(page, wenjie_path):
    page.goto(page.url.split("#")[0] + "#relations")
    _load(page, wenjie_path)
    _wait_meta(page, "6 row(s)")
    _open(page, "datasources")
    assert page.url.endswith("#datasources")


def test_dashboard_filter_only_shows_for_dashboard_sheets(page, wenjie_path):
    _load(page, wenjie_path)
    assert not page.is_visible("#dashboardWrap")
    _open(page, "dashboard-sheets")
    page.wait_for_selector("#dashboardWrap", state="visible", timeout=10_000)
    _open(page, "fields")
    page.wait_for_selector("#dashboardWrap", state="hidden", timeout=10_000)


def test_include_parameters_only_shows_for_calculated_fields(page, wenjie_path):
    _load(page, wenjie_path)
    assert not page.is_visible("#paramsWrap")
    _open(page, "calculated-fields")
    page.wait_for_selector("#paramsWrap", state="visible", timeout=10_000)


def test_empty_table_shows_an_empty_state(page, wenjie_path):
    _load(page, wenjie_path)
    _open(page, "joins")
    _wait_meta(page, "0 row(s)")
    assert page.is_visible("#tableWrap .empty-state")


def test_narrow_viewport_switches_tables_with_the_dropdown(page, wenjie_path):
    page.set_viewport_size({"width": 420, "height": 800})
    _load(page, wenjie_path)
    assert not page.is_visible(".side")
    assert page.is_visible("#tableSel")
    page.select_option("#tableSel", "datasources")
    _wait_meta(page, "2 row(s)")
    assert page.js_errors == []


# --- graph view: the exact code path the syntax error lived in ---------------


def test_graph_view_renders_dot_and_counts_lines(page, wenjie_path):
    # The broken line was the `split('\n')` that produces this line count,
    # so this asserts on the specific statement that was malformed.
    _load(page, wenjie_path)
    _open(page, "graph")
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
    _open(page, "graph")
    page.wait_for_function(
        "() => document.getElementById('exportBtn').textContent === 'Export DOT'",
        timeout=10_000,
    )
    assert page.is_visible("#inferredWrap")
    assert page.is_visible("#copyBtn")
    assert not page.is_visible("#filter")
    assert "download=1" in page.get_attribute("#exportLink", "href")


def test_export_link_updates_before_the_data_arrives(page, wenjie_path):
    # Hold the graph request open: the link must already point at the graph
    # download, not linger on the previous view until the response lands.
    _load(page, wenjie_path)
    held = []
    page.route(re.compile(r"/graph\?"), lambda route: held.append(route))
    _open(page, "graph")
    for _ in range(100):
        if held:
            break
        page.wait_for_timeout(50)
    assert held, "graph request was never made"
    assert "download=1" in page.get_attribute("#exportLink", "href")
    held[0].continue_()
    page.wait_for_function(
        "() => document.querySelector('#tableWrap pre') !== null", timeout=10_000
    )


def test_export_link_points_at_the_current_table(page, wenjie_path):
    _load(page, wenjie_path)
    _open(page, "fields")
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
    assert page.is_enabled("#loadBtn")


def test_empty_path_is_rejected_client_side(page):
    page.click("#loadBtn")
    page.wait_for_function(
        "() => document.getElementById('status').textContent.includes('Enter a workbook path')",
        timeout=10_000,
    )
    assert not page.is_visible("#controls")
