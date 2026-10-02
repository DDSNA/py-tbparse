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

from py_tbparse import webgui

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
        "() => document.getElementById('status').textContent.startsWith('Opened')",
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
        "() => document.getElementById('status').textContent.startsWith('That didn’t work')",
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


# --- field renames: create / download fixed workbook buttons ------------------


def test_field_renames_buttons_create_a_workbook(page, wenjie_path, tmp_path):
    import shutil

    book = tmp_path / "book.twb"
    shutil.copy(wenjie_path, book)
    _load(page, str(book))
    _open(page, "field-renames")
    assert page.is_visible("#createBtn")
    assert page.is_visible("#downloadBtn")
    assert "style=title" in page.get_attribute("#downloadBtn", "href")

    # Changing the style re-fetches the table and updates the download link.
    page.select_option("#renameStyle", "snake")
    page.wait_for_function(
        "() => document.getElementById('downloadBtn').href.includes('style=snake')",
        timeout=10_000,
    )

    page.select_option("#renameStyle", "title")
    page.click("#createBtn")
    page.wait_for_function(
        "() => document.getElementById('status').textContent.startsWith('Saved')",
        timeout=10_000,
    )
    assert (tmp_path / "book_renamed.twb").exists()

    # A second click must not overwrite the first copy.
    page.click("#createBtn")
    page.wait_for_function(
        "() => document.getElementById('status').textContent.includes('already exists')",
        timeout=10_000,
    )
    # Chromium logs the deliberate 409 as a console error; nothing else may appear.
    assert [e for e in page.js_errors if "409" not in e] == []


def test_rename_tools_only_show_on_the_field_renames_view(page, wenjie_path):
    _load(page, wenjie_path)
    assert not page.is_visible("#renameTools")
    _open(page, "field-renames")
    assert page.is_visible("#renameTools")
    _open(page, "fields")
    assert not page.is_visible("#renameTools")


def test_rename_everything_switch(page, tmp_path):
    from test_rename_all import WORKBOOK

    book = tmp_path / "report.twb"
    book.write_text(WORKBOOK, encoding="utf-8")
    _load(page, str(book))
    _open(page, "field-renames")
    assert not page.inner_text("body").count("My Dashboard")  # fields only until switched

    page.select_option("#renameKinds", "all")
    page.wait_for_function(
        "() => document.getElementById('downloadBtn').href.includes('kinds=all')", timeout=10_000
    )
    page.wait_for_function("() => document.body.innerText.includes('My Dashboard')", timeout=10_000)
    page.click("#createBtn")
    page.wait_for_function(
        "() => document.getElementById('status').textContent.startsWith('Saved')", timeout=10_000
    )
    text = (tmp_path / "report_renamed.twb").read_text(encoding="utf-8")
    assert "my dashboard" not in text and "My Dashboard" in text
    assert page.js_errors == []


# --- phase 1 of the redesign: keyboard, motion, loading, toasts, phone ------------------------------


def _status_classes(page):
    return (page.get_attribute("#status", "class") or "").split()


def test_the_whole_flow_works_from_the_keyboard(page, wenjie_path):
    page.focus("#path")
    page.keyboard.type(wenjie_path)
    page.keyboard.press("Enter")
    page.wait_for_selector("#controls", state="visible", timeout=10_000)

    # the sidebar is made of real buttons: Enter on one opens that table
    page.focus('.nav-item[data-table="fields"]')
    page.keyboard.press("Enter")
    _wait_meta(page, "55 row(s)")
    assert page.evaluate("() => document.activeElement.dataset.table") == "fields"  # focus stays put

    # Space and Enter both sort a column from its header
    first_header = page.locator("#tableWrap th").first
    first_header.focus()
    page.keyboard.press("Space")
    assert page.locator("#tableWrap th").first.get_attribute("aria-sort") == "ascending"
    # the table was rebuilt, but focus is back on the same header, so Enter flips the direction
    assert page.evaluate("() => document.activeElement === document.querySelector('#tableWrap th')")
    page.keyboard.press("Enter")
    assert page.locator("#tableWrap th").first.get_attribute("aria-sort") == "descending"

    # rows: one tab stop, arrows move, Enter / Space expand and collapse
    stops = page.eval_on_selector_all('#tableWrap tbody tr[tabindex="0"]', "els => els.length")
    assert stops == 1
    page.focus('#tableWrap tbody tr[tabindex="0"]')
    page.keyboard.press("ArrowDown")
    assert page.evaluate("() => Array.from(document.querySelectorAll('#tableWrap tbody tr')).indexOf(document.activeElement)") == 1
    assert page.eval_on_selector_all('#tableWrap tbody tr[tabindex="0"]', "els => els.length") == 1
    page.keyboard.press("Enter")
    assert page.evaluate("() => document.activeElement.getAttribute('aria-expanded')") == "true"
    assert page.evaluate("() => document.activeElement.classList.contains('open')")
    page.keyboard.press("Space")
    assert page.evaluate("() => document.activeElement.getAttribute('aria-expanded')") == "false"
    page.keyboard.press("End")
    assert page.evaluate("() => { const r = document.querySelectorAll('#tableWrap tbody tr'); return document.activeElement === r[r.length - 1]; }")
    page.keyboard.press("Home")
    assert page.evaluate("() => document.activeElement === document.querySelector('#tableWrap tbody tr')")
    assert page.js_errors == []


def test_skip_link_moves_focus_to_the_table_and_keeps_the_url(page, wenjie_path):
    _load(page, wenjie_path)
    _open(page, "fields")
    before = page.evaluate("() => location.hash")
    page.focus(".skip")
    page.wait_for_function(  # it slides into view over about 120 ms
        "() => document.querySelector('.skip').getBoundingClientRect().top >= 0", timeout=5_000
    )
    page.keyboard.press("Enter")
    assert page.evaluate("() => document.activeElement.id") == "main"
    assert page.evaluate("() => location.hash") == before == "#fields"


def test_switching_views_announces_where_you_landed(page, wenjie_path):
    _load(page, wenjie_path)
    _open(page, "fields")
    page.wait_for_function(
        "() => document.getElementById('announce').textContent === 'Showing Fields, 55 rows'", timeout=10_000
    )
    # an animation class on the view, not on every filter keystroke
    assert "enter" in (page.get_attribute("#tableWrap", "class") or "")


def test_a_slow_view_shows_a_skeleton_then_the_table(page, wenjie_path):
    _load(page, wenjie_path)
    # make the next requests slow, in the page, so the skeleton has time to appear
    page.evaluate(
        "() => { const f = window.fetch; "
        "window.fetch = (u, o) => new Promise((r) => setTimeout(r, 900)).then(() => f(u, o)); }"
    )
    page.click('.nav-item[data-table="fields"]')
    page.wait_for_selector("#tableWrap .skeleton", timeout=5_000)
    assert page.get_attribute("#tableWrap .skeleton", "aria-hidden") == "true"
    page.wait_for_selector("#tableWrap table.tbl", timeout=10_000)
    assert page.locator("#tableWrap .skeleton").count() == 0


def test_a_quick_view_never_flashes_a_skeleton(page, wenjie_path):
    _load(page, wenjie_path)
    page.evaluate(
        "() => { window.__skeletons = 0; "
        "new MutationObserver((ms) => ms.forEach((m) => m.addedNodes.forEach((n) => "
        "{ if (n.classList && n.classList.contains('skeleton')) window.__skeletons++; })))"
        ".observe(document.getElementById('tableWrap'), {childList: true}); }"
    )
    _open(page, "fields")
    _wait_meta(page, "55 row(s)")
    assert page.evaluate("() => window.__skeletons") == 0


def test_success_toasts_fade_but_errors_stay_until_dismissed(page, wenjie_path):
    page.evaluate("() => { window.TOAST_MS = 300; }")
    _load(page, wenjie_path)
    page.wait_for_function(
        "() => !document.getElementById('status').classList.contains('show')", timeout=5_000
    )
    assert page.text_content("#status").startswith("Opened")  # the text stays for assistive tech

    page.fill("#path", "/definitely/not/a/workbook.twb")
    page.click("#loadBtn")
    page.wait_for_function(
        "() => document.getElementById('status').classList.contains('err')", timeout=10_000
    )
    page.wait_for_timeout(800)  # well past TOAST_MS: an error must still be showing
    assert "show" in _status_classes(page)
    page.click("#status")
    assert "show" not in _status_classes(page)


def test_there_is_no_persistent_loaded_line_and_the_page_has_landmarks(page, wenjie_path):
    _load(page, wenjie_path)
    assert page.locator("header.top").count() == 1
    assert page.locator("main#main").count() == 1
    assert page.get_attribute("nav#nav", "aria-label") == "Tables"
    assert page.locator("h1").count() == 2  # the start screen's (hidden) and the view's
    assert page.locator("h1:visible").count() == 1


def test_the_filter_waits_for_a_pause_in_typing(page, wenjie_path):
    _load(page, wenjie_path)
    _open(page, "fields")
    _wait_meta(page, "55 row(s)")
    page.evaluate(
        "() => { window.__renders = 0; "
        "new MutationObserver(() => { window.__renders++; })"
        ".observe(document.getElementById('tableWrap'), {childList: true}); }"
    )
    page.focus("#filter")
    page.keyboard.type("county", delay=15)  # six keystrokes in well under the debounce window
    page.wait_for_function(
        "() => /of 55 row/.test(document.getElementById('meta').textContent)", timeout=10_000
    )
    assert page.evaluate("() => window.__renders") <= 3  # not one rebuild per key


def test_reduced_motion_turns_every_transition_and_animation_off(page, wenjie_path):
    _load(page, wenjie_path)
    page.emulate_media(reduced_motion="no-preference")
    normal = page.evaluate("() => parseFloat(getComputedStyle(document.getElementById('loadBtn')).transitionDuration)")
    assert normal > 0.05  # about 0.12 s
    page.emulate_media(reduced_motion="reduce")
    reduced = page.evaluate("() => parseFloat(getComputedStyle(document.getElementById('loadBtn')).transitionDuration)")
    assert reduced < 0.001
    toast = page.evaluate("() => parseFloat(getComputedStyle(document.getElementById('status')).transitionDuration)")
    assert toast < 0.001
    _open(page, "fields")
    nav = page.evaluate("() => parseFloat(getComputedStyle(document.querySelector('.nav-item')).transitionDuration)")
    assert nav < 0.001


def test_overview_tiles_sit_two_across_on_a_phone(page, wenjie_path):
    page.set_viewport_size({"width": 390, "height": 800})
    _load(page, wenjie_path)
    page.wait_for_selector("#tableWrap .stat", timeout=10_000)  # the toast appears just before the view
    boxes = page.eval_on_selector_all(
        "#tableWrap .stat", "els => els.map(e => { const r = e.getBoundingClientRect(); return [r.left, r.top, r.width]; })"
    )
    assert len(boxes) >= 3
    assert boxes[0][1] == boxes[1][1] and boxes[0][0] < boxes[1][0]  # first two share a row
    assert boxes[2][1] > boxes[0][1]  # the third starts the next one
    assert boxes[0][2] < 390 / 2  # each is under half the screen
    # nothing scrolls sideways at phone width
    assert page.evaluate("() => document.documentElement.scrollWidth <= window.innerWidth + 1")


def test_start_screen_has_the_friendly_copy(page):
    assert page.text_content("#empty h1") == "Let’s open a workbook"
    assert "Nothing is uploaded" in page.text_content("#empty")
