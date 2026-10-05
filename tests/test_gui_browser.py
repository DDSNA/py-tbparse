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

import json
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

from conftest import new_page  # noqa: F401  (the fixtures themselves live in conftest.py)


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



def _copy_column(page, column):
    """Every value of a column in the order the table shows it, via its own "Copy column values"
    menu item. The table is windowed, so most rows are not in the page to read directly."""
    page.evaluate("() => { document.getElementById('status').textContent = ''; }")
    th = page.locator("#tableWrap th").filter(has=page.locator(".th-label", has_text=re.compile(rf"^{column}$"))).first
    th.focus()
    page.keyboard.press("Alt+ArrowDown")
    page.click("#menu >> text=Copy column values")
    page.wait_for_function("() => document.getElementById('status').textContent.startsWith('Copied')", timeout=10_000)
    text = page.evaluate("() => navigator.clipboard.readText()")
    return text.split("\n") if text else []  # a table with no rows copies nothing


def _header(page, column):
    return page.locator("#tableWrap th").filter(has=page.locator(".th-label", has_text=re.compile(rf"^{column}$"))).first


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
    # the table is windowed: the page holds the visible rows, and aria-rowcount holds the true size
    assert page.eval_on_selector_all("#tableWrap tbody tr[data-pos]", "els => els.length") == shown
    assert page.get_attribute("#tableWrap table", "aria-rowcount") == str(shown + 1)
    page.press("#filter", "Escape")
    _wait_meta(page, "55 row(s)")


def test_slash_key_focuses_the_filter(page, wenjie_path):
    _load(page, wenjie_path)
    _open(page, "fields")
    page.click("#viewTitle")
    page.keyboard.press("/")
    assert page.evaluate("() => document.activeElement.id") == "filter"


def test_clicking_a_header_sorts_the_column(page, wenjie_path):
    from playwright.sync_api import expect

    _load(page, wenjie_path)
    _open(page, "fields")
    _wait_meta(page, "55 row(s)")
    header = _header(page, "name")
    before = _copy_column(page, "name")
    assert len(before) == 55
    header.click()
    expect(header).to_have_attribute("aria-sort", "ascending")
    asc = _copy_column(page, "name")
    # Locale collation (what the page uses) and Python ordering disagree on punctuation, so compare
    # against the page itself: same rows, and descending mirrors ascending at both ends.
    assert sorted(asc) == sorted(before)
    assert asc != before
    header.click()
    expect(header).to_have_attribute("aria-sort", "descending")
    desc = _copy_column(page, "name")
    assert desc[0] == asc[-1] and desc[-1] == asc[0]
    header.click()
    expect(header).to_have_attribute("aria-sort", "none")
    assert _copy_column(page, "name") == before


def test_clicking_a_row_opens_its_details(page, wenjie_path):
    _load(page, wenjie_path)
    _open(page, "relations")
    _wait_meta(page, "6 row(s)")
    row = "#tableWrap tbody tr[data-pos] >> nth=2"
    page.click(row)
    page.wait_for_selector("#drawer.show", timeout=10_000)
    assert page.get_attribute(row, "aria-current") == "true"
    # the drawer lists every column of that row, in order
    columns = page.eval_on_selector_all("#tableWrap th .th-label", "els => els.map(e => e.textContent)")
    assert page.eval_on_selector_all("#drawerBody dt", "els => els.map(e => e.textContent)") == columns
    page.click("#drawerClose")
    page.wait_for_selector("#drawer", state="hidden", timeout=10_000)
    assert page.get_attribute(row, "aria-current") is None
    # focus goes back to the row that opened it
    assert page.evaluate("() => document.activeElement.dataset.pos") == "2"


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


def test_graph_view_draws_the_graph_and_keeps_the_dot(page, wenjie_path):
    # The DOT text stays available (a collapsed section), and the picture is drawn from the same data.
    _load(page, wenjie_path)
    _open(page, "graph")
    page.wait_for_function(
        "() => document.querySelector('#tableWrap pre') !== null", timeout=10_000
    )
    dot = page.text_content("#tableWrap pre")
    assert dot.startswith('digraph "twb" {')
    assert "Sheet1" in dot

    page.wait_for_selector("#tableWrap svg.graph .node", timeout=10_000)
    meta = page.text_content("#meta")
    assert re.fullmatch(r"\d+ tables?, \d+ connections?", meta), meta
    assert int(meta.split()[0]) == page.locator("#tableWrap svg.graph .node").count()
    assert dot.count(" -> ") == page.locator("#tableWrap svg.graph .edge").count()
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
    from playwright.sync_api import expect

    page.focus("#path")
    page.keyboard.type(wenjie_path)
    page.keyboard.press("Enter")
    page.wait_for_selector("#controls", state="visible", timeout=10_000)

    # the sidebar is made of real buttons: Enter on one opens that table
    page.focus('.nav-item[data-table="fields"]')
    page.keyboard.press("Enter")
    _wait_meta(page, "55 row(s)")
    assert page.evaluate("() => document.activeElement.dataset.table") == "fields"  # focus stays put

    # one tab stop in the header; arrows move along it; Space and Enter sort
    first_header = page.locator("#tableWrap th").first
    assert page.eval_on_selector_all('#tableWrap th[tabindex="0"]', "els => els.length") == 1
    first_header.focus()
    page.keyboard.press("ArrowRight")
    assert page.evaluate("() => document.activeElement === document.querySelectorAll('#tableWrap th')[1]")
    page.keyboard.press("ArrowLeft")
    page.keyboard.press("Space")
    expect(page.locator("#tableWrap th").first).to_have_attribute("aria-sort", "ascending")
    # the table was rebuilt, but focus is back on the same header, so Enter flips the direction
    assert page.evaluate("() => document.activeElement === document.querySelector('#tableWrap th')")
    page.keyboard.press("Enter")
    expect(page.locator("#tableWrap th").first).to_have_attribute("aria-sort", "descending")

    # rows: one tab stop, arrows move, End and Home reach the true last and first row,
    # Enter opens the details drawer, Escape closes it and puts focus back on the row
    assert page.eval_on_selector_all('#tableWrap tbody tr[tabindex="0"]', "els => els.length") == 1
    page.focus('#tableWrap tbody tr[tabindex="0"]')
    page.keyboard.press("ArrowDown")
    assert page.evaluate("() => document.activeElement.dataset.pos") == "1"
    assert page.eval_on_selector_all('#tableWrap tbody tr[tabindex="0"]', "els => els.length") == 1
    page.keyboard.press("End")
    assert page.evaluate("() => document.activeElement.dataset.pos") == "54"  # row 55 of 55, scrolled into view
    page.keyboard.press("Home")
    assert page.evaluate("() => document.activeElement.dataset.pos") == "0"
    page.keyboard.press("Enter")
    page.wait_for_selector("#drawer.show", timeout=10_000)
    assert page.evaluate("() => document.activeElement.id") == "drawerTitle"
    page.keyboard.press("Escape")
    page.wait_for_selector("#drawer", state="hidden", timeout=10_000)
    assert page.evaluate("() => document.activeElement.dataset.pos") == "0"
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
    assert page.locator("h1").count() == 3  # the start screen's, the view's and the Templates view's (two hidden)
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
    text = page.text_content("#empty")
    assert "Everything stays on this computer" in text and "Nothing leaves it" in text


# --- phase 2 of the redesign: a windowed, column-aware table ----------------------------------------------


def _enough_memory(mb):
    """Skip the heavy tests on a machine that is short of memory (this sandbox has about 3 GB spare)."""
    try:
        with open("/proc/meminfo") as fh:
            for line in fh:
                if line.startswith("MemAvailable:"):
                    return int(line.split()[1]) / 1024 >= mb
    except OSError:
        pass
    return True  # not Linux: assume it can take it


_NEEDS_MEMORY = pytest.mark.skipif(not _enough_memory(1500), reason="needs about 1.5 GB of free memory")

# Makes /table?name=fields return n synthetic rows, so a test can use big tables without a big workbook.
_FEED = """
(n) => {
  const real = window.fetch;
  const cols = ['datasource', 'name', 'caption', 'datatype', 'role', 'semantic_role', 'formula', 'n'];
  const words = ['alpha', 'bravo', 'charlie', 'delta', 'echo', 'foxtrot', 'golf', 'hotel', 'india', 'juliet'];
  const data = [];
  for (let i = 0; i < n; i++) {
    data.push(['federated.' + (i % 7), words[i % 10] + '_' + i, null, i % 3 ? 'string' : 'integer',
               i % 2 ? 'dimension' : 'measure', null, 'SUM([' + words[(i * 7) % 10] + '])', i]);
  }
  window.fetch = (u, o) => String(u).startsWith('/table?name=fields')
    ? Promise.resolve(new Response(JSON.stringify({columns: cols, data}),
                                   {status: 200, headers: {'Content-Type': 'application/json'}}))
    : real(u, o);
}
"""


def _last_render_ms(page):
    return page.evaluate(
        "() => { const m = performance.getEntriesByName('py-tbparse:table'); return m.length ? m[m.length - 1].duration : null; }"
    )


def _open_column_menu(page, column):
    _header(page, column).focus()
    page.keyboard.press("Alt+ArrowDown")
    page.wait_for_selector("#menu:not([hidden])", timeout=10_000)


def _feed_and_open(page, wenjie_path, n):
    _load(page, wenjie_path)
    page.evaluate(_FEED, n)
    page.click('.nav-item[data-table="fields"]')
    _wait_meta(page, f"{n} row(s)")


@_NEEDS_MEMORY
def test_fifty_thousand_rows_stay_a_few_dozen_in_the_page(page, wenjie_path):
    _feed_and_open(page, wenjie_path, 50_000)
    assert page.get_attribute("#tableWrap table", "aria-rowcount") == "50001"
    in_page = lambda: page.eval_on_selector_all("#tableWrap tbody tr[data-pos]", "els => els.length")  # noqa: E731
    assert 10 < in_page() < 100
    # scroll to the middle: a different window, not a longer one
    page.evaluate("() => { const w = document.getElementById('tableWrap'); w.scrollTop = w.scrollHeight / 2; }")
    page.wait_for_function(
        "() => Number(document.querySelector('#tableWrap tbody tr[data-pos]').dataset.pos) > 10000", timeout=10_000
    )
    assert 10 < in_page() < 100
    # End reaches the true last row, and the sticky header never left the top of the table
    page.focus('#tableWrap tbody tr[tabindex="0"]')
    page.keyboard.press("End")
    assert page.evaluate("() => document.activeElement.dataset.pos") == "49999"
    head = page.locator("#tableWrap th").first.bounding_box()
    wrap = page.locator("#tableWrap").bounding_box()
    # a few pixels of slack for sub-pixel layout on other machines; a header that scrolled away is hundreds off
    assert abs(head["y"] - wrap["y"]) < 4
    assert page.js_errors == []


def test_first_paint_of_a_thousand_rows_is_within_budget(page, wenjie_path):
    _feed_and_open(page, wenjie_path, 1_000)
    ms = _last_render_ms(page)
    # budget 150 ms; the test fails at twice that so a slow CI machine does not flake it
    assert ms is not None and ms < 300, f"first paint of 1,000 rows took {ms} ms"


@_NEEDS_MEMORY
def test_filter_and_sort_of_fifty_thousand_rows_are_within_budget(page, wenjie_path):
    _feed_and_open(page, wenjie_path, 50_000)
    # the search index is built in small slices right after the table is drawn
    page.wait_for_function("() => state.hay !== null", timeout=30_000)
    page.evaluate("() => performance.clearMeasures('py-tbparse:table')")
    page.focus("#filter")
    page.keyboard.type("echo_4", delay=0)
    page.wait_for_function("() => /of 50000 row/.test(document.getElementById('meta').textContent)", timeout=30_000)
    filter_ms = _last_render_ms(page)
    # budget 100 ms of main-thread time per keystroke; the test fails at twice that
    assert filter_ms is not None and filter_ms < 200, f"filtering 50,000 rows took {filter_ms} ms"
    page.press("#filter", "Escape")
    _wait_meta(page, "50000 row(s)")
    page.evaluate("() => performance.clearMeasures('py-tbparse:table')")
    _header(page, "name").click()
    page.wait_for_function(
        "() => document.querySelector(\"#tableWrap th[aria-sort='ascending']\")", timeout=30_000
    )
    sort_ms = _last_render_ms(page)
    # the old table needed over 4 s to sort 20,000 rows; a regression guard, not a budget
    assert sort_ms is not None and sort_ms < 1500, f"sorting 50,000 rows took {sort_ms} ms"


def test_column_menu_opens_from_the_keyboard_and_closes_cleanly(page, wenjie_path):
    _load(page, wenjie_path)
    _open(page, "fields")
    _wait_meta(page, "55 row(s)")
    _open_column_menu(page, "name")
    assert page.get_attribute("#menu", "role") == "menu"
    assert page.get_attribute("#menu", "aria-label") == "Options for column name"
    roles = page.eval_on_selector_all("#menu button", "els => els.map(e => e.getAttribute('role'))")
    assert set(roles) == {"menuitem"}
    assert page.evaluate("() => document.activeElement.textContent.trim()") == "Sort ascending"
    page.keyboard.press("ArrowDown")
    assert page.evaluate("() => document.activeElement.textContent.trim()") == "Sort descending"
    page.keyboard.press("ArrowDown")  # "Clear sort" is unavailable but stays reachable (aria-disabled)
    assert page.evaluate("() => document.activeElement.textContent.trim()") == "Clear sort"
    assert page.evaluate("() => document.activeElement.getAttribute('aria-disabled')") == "true"
    page.keyboard.press("ArrowDown")
    assert "Filter this column" in page.evaluate("() => document.activeElement.textContent")
    page.keyboard.press("End")
    assert page.evaluate("() => document.activeElement.textContent.trim()") == "Copy column values"
    page.keyboard.press("Escape")
    assert page.is_hidden("#menu")
    assert page.evaluate("() => document.activeElement.textContent.startsWith('name')")  # back on the header
    # the visible options button opens it too
    page.click("#tableWrap th .col-menu-btn >> nth=1")
    page.wait_for_selector("#menu:not([hidden])")
    page.keyboard.press("Tab")
    assert page.is_hidden("#menu")
    assert page.js_errors == []


def test_sorting_from_the_column_menu(page, wenjie_path):
    from playwright.sync_api import expect

    _load(page, wenjie_path)
    _open(page, "fields")
    _wait_meta(page, "55 row(s)")
    _open_column_menu(page, "name")
    page.click("#menu >> text=Sort descending")
    expect(_header(page, "name")).to_have_attribute("aria-sort", "descending")
    desc = _copy_column(page, "name")
    _open_column_menu(page, "name")
    page.click("#menu >> text=Sort ascending")
    expect(_header(page, "name")).to_have_attribute("aria-sort", "ascending")
    # focus is back on the header the menu was opened from (the sort rebuilt the table under it)
    page.wait_for_function(
        "() => document.activeElement.tagName === 'TH' && document.activeElement.querySelector('.th-label').textContent === 'name'",
        timeout=10_000,
    )
    asc = _copy_column(page, "name")
    assert len(asc) == len(desc) == 55 and sorted(asc) == sorted(desc)
    assert asc[0] == desc[-1] and asc[-1] == desc[0] and asc != desc
    # Copy does not redraw the table, but focus still comes back to the header, not to the page
    assert page.evaluate("() => document.activeElement.tagName") == "TH"
    assert page.evaluate("() => document.activeElement.querySelector('.th-label').textContent") == "name"
    _open_column_menu(page, "name")
    page.click("#menu >> text=Clear sort")
    expect(_header(page, "name")).to_have_attribute("aria-sort", "none")


def test_hide_show_and_remember_columns_per_table(page, wenjie_path):
    _load(page, wenjie_path)
    _open(page, "fields")
    _wait_meta(page, "55 row(s)")
    count = lambda: page.eval_on_selector_all("#tableWrap th", "els => els.length")  # noqa: E731
    total = count()
    assert page.get_attribute("#tableWrap table", "aria-colcount") == str(total)
    _open_column_menu(page, "caption")
    page.click("#menu >> text=Hide column")
    page.wait_for_function("(n) => document.querySelectorAll('#tableWrap th').length === n - 1", arg=total, timeout=10_000)
    assert page.get_attribute("#tableWrap table", "aria-colcount") == str(total - 1)
    assert page.text_content("#colsBtn") == "Columns (1 hidden)"
    # the Columns menu brings it back; it stays open so several can be toggled
    page.click("#colsBtn")
    item = page.locator("#menu button[role=menuitemcheckbox]", has_text="caption")
    assert item.get_attribute("aria-checked") == "false"
    item.click()
    page.wait_for_function("(n) => document.querySelectorAll('#tableWrap th').length === n", arg=total, timeout=10_000)
    assert page.is_visible("#menu")
    assert page.locator("#menu button[role=menuitemcheckbox]", has_text="caption").get_attribute("aria-checked") == "true"
    page.keyboard.press("Escape")
    assert page.is_hidden("#menu")
    assert page.evaluate("() => document.activeElement.id") == "colsBtn"
    # hide it again, leave the table and come back: the choice is remembered for that table only
    _open_column_menu(page, "caption")
    page.click("#menu >> text=Hide column")
    page.wait_for_function("(n) => document.querySelectorAll('#tableWrap th').length === n - 1", arg=total, timeout=10_000)
    _open(page, "datasources")
    page.wait_for_function("() => document.querySelector('#tableWrap table') && document.getElementById('meta').textContent.includes('row')")
    assert page.text_content("#colsBtn") == "Columns"
    _open(page, "fields")
    page.wait_for_function("(n) => document.querySelectorAll('#tableWrap th').length === n - 1", arg=total, timeout=10_000)
    assert page.text_content("#colsBtn") == "Columns (1 hidden)"
    assert page.js_errors == []


def test_the_last_visible_column_cannot_be_hidden(page, wenjie_path):
    _load(page, wenjie_path)
    _open(page, "fields")
    _wait_meta(page, "55 row(s)")
    columns = page.eval_on_selector_all("#tableWrap th .th-label", "els => els.map(e => e.textContent)")
    page.click("#colsBtn")
    for name in columns:
        if name != "name":
            page.locator("#menu button[role=menuitemcheckbox]", has_text=re.compile(rf"^[\u2713\s]*{name}$")).click()
    page.wait_for_function("() => document.querySelectorAll('#tableWrap th').length === 1", timeout=10_000)
    last = page.locator("#menu button[role=menuitemcheckbox]", has_text=re.compile(r"^[\u2713\s]*name$"))
    assert last.is_disabled() and last.get_attribute("aria-checked") == "true"
    page.keyboard.press("Escape")
    _open_column_menu(page, "name")
    assert page.locator("#menu button", has_text="Hide column").is_disabled()


def test_pin_a_column_and_widen_it(page, wenjie_path):
    _load(page, wenjie_path)
    _open(page, "fields")
    _wait_meta(page, "55 row(s)")
    _open_column_menu(page, "datatype")
    page.click("#menu >> text=Pin to the left")
    page.wait_for_function("() => document.querySelector('#tableWrap th .th-label').textContent === 'datatype'", timeout=10_000)
    assert "pin" in page.get_attribute("#tableWrap th", "class")
    assert page.eval_on_selector_all("#tableWrap tbody tr[data-pos] td.pin", "els => els.length") > 5
    # it stays at the left edge when the table scrolls sideways
    page.evaluate("() => { document.getElementById('tableWrap').scrollLeft = 300; }")
    wrap = page.locator("#tableWrap").bounding_box()
    pinned = page.locator("#tableWrap th.pin").bounding_box()
    assert abs(pinned["x"] - wrap["x"]) < 2
    _open_column_menu(page, "datatype")
    assert page.locator("#menu button", has_text="Unpin column").count() == 1
    before = page.locator("#tableWrap th.pin").bounding_box()["width"]
    page.click("#menu >> text=Wider")
    page.wait_for_function(
        "(w) => document.querySelector('#tableWrap th.pin').getBoundingClientRect().width > w + 30", arg=before, timeout=10_000
    )


def test_dragging_the_edge_of_a_header_resizes_the_column(page, wenjie_path):
    _load(page, wenjie_path)
    _open(page, "fields")
    _wait_meta(page, "55 row(s)")
    th = _header(page, "caption")
    before = th.bounding_box()["width"]
    grip = th.locator(".col-resize").bounding_box()
    x, y = grip["x"] + grip["width"] / 2, grip["y"] + grip["height"] / 2
    page.mouse.move(x, y)
    page.mouse.down()
    page.mouse.move(x + 60, y, steps=4)
    page.mouse.up()
    after = _header(page, "caption").bounding_box()["width"]
    assert 50 < after - before < 70
    # it survives a re-render (a sort rebuilds the table)
    _header(page, "caption").click()
    page.wait_for_function("() => document.querySelector(\"#tableWrap th[aria-sort='ascending']\")", timeout=10_000)
    assert abs(_header(page, "caption").bounding_box()["width"] - after) < 2


def test_column_filter_chips(page, wenjie_path):
    _load(page, wenjie_path)
    _open(page, "fields")
    _wait_meta(page, "55 row(s)")
    _open_column_menu(page, "datatype")
    page.click("#menu >> text=Filter this column")
    assert page.get_attribute("#menu", "role") == "dialog"
    page.fill("#menu input", "string")
    page.keyboard.press("Enter")
    page.wait_for_function("() => /of 55 row/.test(document.getElementById('meta').textContent)", timeout=10_000)
    assert page.is_hidden("#menu")
    chip = page.locator("#chips .chip")
    assert chip.count() == 1
    assert chip.get_attribute("aria-label") == "Remove filter: datatype contains string"
    assert set(_copy_column(page, "datatype")) == {"string"}
    # the search box and the chip work together
    page.fill("#filter", "no-such-field-anywhere")
    page.wait_for_selector("#tableWrap .empty-state", timeout=10_000)
    page.press("#filter", "Escape")
    page.wait_for_selector("#tableWrap tbody tr[data-pos]")
    # removing the chip returns every row and puts focus somewhere sensible
    page.click("#chips .chip")
    _wait_meta(page, "55 row(s)")
    assert page.is_hidden("#chips")
    assert page.evaluate("() => document.activeElement.id") == "filter"


def test_clear_filters_clears_the_search_and_the_chips(page, wenjie_path):
    _load(page, wenjie_path)
    _open(page, "fields")
    _wait_meta(page, "55 row(s)")
    _open_column_menu(page, "datatype")
    page.click("#menu >> text=Filter this column")
    page.fill("#menu input", "string")
    page.keyboard.press("Enter")
    page.wait_for_selector("#chips .chip")
    page.fill("#filter", "a")
    page.wait_for_function("() => /of 55 row/.test(document.getElementById('meta').textContent)", timeout=10_000)
    page.click("#chips .chip-clear")
    _wait_meta(page, "55 row(s)")
    assert page.input_value("#filter") == ""
    assert page.is_hidden("#chips")


def test_search_ignores_hidden_columns(page, wenjie_path):
    _load(page, wenjie_path)
    _open(page, "fields")
    _wait_meta(page, "55 row(s)")
    page.fill("#filter", "integer")
    page.wait_for_function("() => /of 55 row/.test(document.getElementById('meta').textContent)", timeout=10_000)
    matching = int(page.text_content("#meta").split()[0])
    assert matching > 0
    _open_column_menu(page, "datatype")
    page.click("#menu >> text=Hide column")
    page.wait_for_function("() => document.querySelectorAll('#tableWrap th').length < 10", timeout=10_000)
    # "integer" only ever appeared in the datatype column, which is now hidden, so nothing matches
    page.wait_for_selector("#tableWrap .empty-state", timeout=10_000)
    assert page.text_content("#meta").startswith("0 of 55")


def test_details_drawer_copies_a_row_as_json_and_follows_the_selection(page, wenjie_path):
    _load(page, wenjie_path)
    _open(page, "fields")
    _wait_meta(page, "55 row(s)")
    page.click("#tableWrap tbody tr[data-pos] >> nth=0")
    page.wait_for_selector("#drawer.show", timeout=10_000)
    first_title = page.text_content("#drawerTitle")
    page.click("#tableWrap tbody tr[data-pos] >> nth=1")
    page.wait_for_function("(t) => document.getElementById('drawerTitle').textContent !== t", arg=first_title, timeout=10_000)
    assert page.eval_on_selector_all('#tableWrap tr[aria-current="true"]', "els => els.length") == 1
    page.click("#drawerCopy")
    page.wait_for_function("() => document.getElementById('status').textContent.startsWith('Copied this row')", timeout=10_000)
    copied = json.loads(page.evaluate("() => navigator.clipboard.readText()"))
    columns = page.eval_on_selector_all("#tableWrap th .th-label", "els => els.map(e => e.textContent)")
    assert list(copied) == columns
    assert copied["datasource"] == "federated.0grgaor1pd01yy1f0yr380of1ags"  # the real id, not the caption
    # opening a row in a hidden column's table does not leak: close and the row is no longer current
    page.keyboard.press("Escape")
    page.wait_for_selector("#drawer", state="hidden", timeout=10_000)
    assert page.eval_on_selector_all('#tableWrap tr[aria-current="true"]', "els => els.length") == 0


def test_datasources_read_by_caption_and_search_finds_both_names(page, wenjie_path):
    _load(page, wenjie_path)
    _open(page, "fields")
    _wait_meta(page, "55 row(s)")
    labels = page.eval_on_selector_all("#tableWrap th .th-label", "els => els.map(e => e.textContent)")
    cell = page.locator("#tableWrap tbody tr[data-pos]").first.locator("td").nth(labels.index("datasource"))
    assert cell.text_content() == "Sheet1 (test_county)"
    assert "federated.0grgaor1pd01yy1f0yr380of1ags" in cell.get_attribute("title")  # the full id on hover
    # the copied column and the drawer keep the real id
    assert set(_copy_column(page, "datasource")) == {"federated.0grgaor1pd01yy1f0yr380of1ags"}
    # search matches the readable name and the real id alike
    for query in ("test_county", "federated.0grgaor1pd01"):
        page.fill("#filter", query)
        page.wait_for_function("() => /of 55 row/.test(document.getElementById('meta').textContent)", timeout=10_000)
        assert page.text_content("#meta").startswith("55 of 55"), query
        page.press("#filter", "Escape")
        _wait_meta(page, "55 row(s)")


def test_density_toggle_changes_row_height_and_is_remembered(page, wenjie_path):
    _load(page, wenjie_path)
    _open(page, "fields")
    _wait_meta(page, "55 row(s)")
    row_height = "() => document.querySelector('#tableWrap tbody tr[data-pos]').getBoundingClientRect().height"
    assert page.get_attribute("#densityBtn", "aria-pressed") == "false"
    assert abs(page.evaluate(row_height) - 40) < 1
    page.click("#densityBtn")
    page.wait_for_function("() => document.documentElement.dataset.density === 'compact'", timeout=10_000)
    assert page.get_attribute("#densityBtn", "aria-pressed") == "true"
    page.wait_for_function(f"() => Math.abs(({row_height})() - 32) < 1", timeout=10_000)
    assert page.evaluate("() => localStorage.getItem('py-tbparse.density')") == "compact"
    # windowing still covers the whole table at the new height
    page.focus('#tableWrap tbody tr[tabindex="0"]')
    page.keyboard.press("End")
    assert page.evaluate("() => document.activeElement.dataset.pos") == "54"
    # a reload keeps the choice, and the button can switch it back
    page.reload()
    _load(page, wenjie_path)
    _open(page, "fields")
    _wait_meta(page, "55 row(s)")
    assert page.evaluate("() => document.documentElement.dataset.density") == "compact"
    assert page.get_attribute("#densityBtn", "aria-pressed") == "true"
    page.click("#densityBtn")
    page.wait_for_function(f"() => Math.abs(({row_height})() - 40) < 1", timeout=10_000)
    assert page.evaluate("() => localStorage.getItem('py-tbparse.density')") == "comfortable"


def test_sorting_works_with_reduced_motion_too(page, wenjie_path):
    from playwright.sync_api import expect

    page.emulate_media(reduced_motion="reduce")
    _load(page, wenjie_path)
    _open(page, "fields")
    _wait_meta(page, "55 row(s)")
    header = _header(page, "name")
    header.click()
    expect(header).to_have_attribute("aria-sort", "ascending")
    names = _copy_column(page, "name")
    assert len(names) == 55 and names != sorted(names, reverse=True)
    assert page.js_errors == []


def test_rapid_sorting_never_raises_an_error(page, wenjie_path):
    _load(page, wenjie_path)
    _open(page, "fields")
    _wait_meta(page, "55 row(s)")
    for _ in range(6):  # a new view transition skips the one still running; that must stay silent
        _header(page, "name").click()
        _header(page, "role").click()
    page.wait_for_timeout(600)
    assert page.js_errors == []


def test_menu_closes_when_you_click_elsewhere_or_scroll(page, wenjie_path):
    _load(page, wenjie_path)
    _open(page, "fields")
    _wait_meta(page, "55 row(s)")
    _open_column_menu(page, "name")
    page.click("h1#viewTitle")
    assert page.is_hidden("#menu")
    _open_column_menu(page, "name")
    page.evaluate("() => { document.getElementById('tableWrap').scrollTop = 40; }")
    page.wait_for_selector("#menu", state="hidden", timeout=5_000)


def test_columns_button_does_not_keep_the_old_tables_hidden_count_while_the_next_loads(page, wenjie_path):
    # Found by CI: the label is rewritten when the new table arrives, so for a moment it still described the
    # previous table. Hold the response open to make that moment as long as we like.
    _load(page, wenjie_path)
    _open(page, "fields")
    _wait_meta(page, "55 row(s)")
    _open_column_menu(page, "caption")
    page.click("#menu >> text=Hide column")
    page.wait_for_function("() => document.getElementById('colsBtn').textContent === 'Columns (1 hidden)'")
    held = []
    page.route(re.compile(r"/table\?name=datasources"), lambda route: held.append(route))
    page.click('.nav-item[data-table="datasources"]')
    for _ in range(100):
        if held:
            break
        page.wait_for_timeout(50)
    assert held, "the datasources request was never made"
    assert page.text_content("#colsBtn") == "Columns"
    held[0].continue_()
    page.wait_for_function("() => document.querySelector('#tableWrap table') !== null")
    assert page.js_errors == []
