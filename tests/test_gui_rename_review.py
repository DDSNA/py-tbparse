"""Rename review in the Field renames view: a checkbox per suggested rename, left-out rows stay as they are.

Run one file at a time on this machine (see docs/development.md). Shares its fixtures with test_gui_browser.py.
"""

from __future__ import annotations

import re

import pytest

from test_gui_a11y import failures, settle  # noqa: F401
from test_gui_browser import _load, _open, new_page  # noqa: F401  (fixtures and helpers shared with the other GUI tests)
from test_rename_all import WORKBOOK

BOXES = "#tableWrap tbody td.sel input[type=checkbox]"


def _report(tmp_path, text=WORKBOOK):
    book = tmp_path / "report.twb"
    book.write_text(text, encoding="utf-8")
    return book


def _everything(page, path):
    _load(page, str(path))
    if page.is_visible("nav#nav"):
        _open(page, "field-renames")
    else:   # a narrow window has the dropdown instead of the sidebar
        page.select_option("#tableSel", "field-renames")
    page.select_option("#renameKinds", "all")
    # the wider table has a kind column first; until it is there the fields-only rows are still showing
    page.wait_for_function("() => [...document.querySelectorAll('#tableWrap th .th-label')].some(e => e.textContent === 'kind')",
                           timeout=10_000)
    page.wait_for_selector(BOXES, timeout=10_000)


def _create_label(page):
    return page.inner_text("#createBtn").strip()


def _row_of(page, text):
    return page.locator("#tableWrap tbody tr[data-pos]", has_text=text).first


def _status_has(page, text):
    page.wait_for_function("t => document.getElementById('status').textContent.includes(t)", arg=text, timeout=10_000)


def test_every_applicable_row_has_a_labelled_checkbox_and_the_button_shows_the_count(page, tmp_path):
    _everything(page, _report(tmp_path))
    n = page.locator(BOXES).count()
    assert n > 5
    assert _create_label(page) == f"Create with {n} of {n} renames"
    assert all(page.locator(BOXES).nth(i).is_checked() for i in range(n))
    labels = page.eval_on_selector_all(BOXES, "els => els.map(e => e.getAttribute('aria-label'))")
    assert all(re.match(r"Rename .+ to .+", t) for t in labels), labels
    assert page.inner_text("#renameCount").strip() == f"All {n} selected"
    assert page.get_attribute("table.tbl", "aria-colcount") == str(
        page.eval_on_selector_all("table.tbl thead th:not(.sel)", "e => e.length") + 1
    )
    assert page.js_errors == []


def test_rename_review_is_only_in_the_field_renames_view(page, wenjie_path):
    _load(page, wenjie_path)
    _open(page, "fields")
    assert page.locator(BOXES).count() == 0
    assert not page.is_visible("#renameSelect")


def test_unticking_a_row_updates_the_count_and_Create_leaves_it_out(page, tmp_path):
    _everything(page, _report(tmp_path))
    n = page.locator(BOXES).count()
    _row_of(page, "sales by region").locator("input").uncheck()
    assert _create_label(page) == f"Create with {n - 1} of {n} renames"
    assert page.inner_text("#renameCount").strip() == f"{n - 1} of {n} selected"
    assert "left-out" in _row_of(page, "sales by region").get_attribute("class")

    page.click("#createBtn")
    _status_has(page, "Saved a fixed copy")
    text = (tmp_path / "report_renamed.twb").read_text(encoding="utf-8")
    assert "sales by region" in text and "Sales By Region" not in text   # every reference left as it was
    assert "Order Details" in text and "My Dashboard" in text
    assert page.js_errors == []


def test_Download_honours_the_left_out_rows(page, tmp_path):
    _everything(page, _report(tmp_path))
    _row_of(page, "ORDER_DETAILS").locator("input").first.uncheck()
    with page.expect_download(timeout=10_000) as info:
        page.click("#downloadBtn")
    download = info.value
    assert download.suggested_filename == "report_renamed.twb"
    text = open(download.path(), encoding="utf-8").read()
    assert "ORDER_DETAILS" in text and "Order Details" not in text and "Sales By Region" in text
    assert not (tmp_path / "report_renamed.twb").exists()   # a download saves nothing beside the original
    assert page.js_errors == []


def test_Download_with_nothing_left_out_is_still_a_plain_link(page, tmp_path):
    _everything(page, _report(tmp_path))
    with page.expect_download(timeout=10_000) as info:
        page.click("#downloadBtn")
    assert "Order Details" in open(info.value.path(), encoding="utf-8").read()


def test_select_none_and_select_all(page, tmp_path):
    _everything(page, _report(tmp_path))
    n = page.locator(BOXES).count()
    page.click("#renameNone")
    assert page.locator(BOXES).evaluate_all("els => els.every(e => !e.checked)")
    assert _create_label(page) == f"Create with 0 of {n} renames"
    assert page.is_disabled("#createBtn")
    assert page.get_attribute("#downloadBtn", "aria-disabled") == "true"
    assert "Tick at least one" in page.inner_text("#renameCount")
    # a click on the disabled link saves nothing and starts no download
    page.click("#downloadBtn", force=True)   # Playwright treats aria-disabled as not clickable
    page.wait_for_timeout(300)
    assert not (tmp_path / "report_renamed.twb").exists()

    page.click("#renameAll")
    assert page.locator(BOXES).evaluate_all("els => els.every(e => e.checked)")
    assert _create_label(page) == f"Create with {n} of {n} renames"
    assert page.is_enabled("#createBtn") and page.get_attribute("#downloadBtn", "aria-disabled") == "false"
    assert page.js_errors == []


def test_the_selection_survives_sorting_and_the_filter(page, tmp_path):
    _everything(page, _report(tmp_path))
    n = page.locator(BOXES).count()
    _row_of(page, "sales by region").locator("input").uncheck()
    page.click("th[data-col]:has-text('suggested')")
    assert not _row_of(page, "sales by region").locator("input").is_checked()
    page.fill("#filter", "region")
    page.wait_for_function("() => document.getElementById('meta').textContent.includes(' of ')", timeout=10_000)
    assert _create_label(page) == f"Create with {n - 1} of {n} renames"
    page.fill("#filter", "")
    assert not _row_of(page, "sales by region").locator("input").is_checked()


def test_left_out_rows_are_forgotten_when_the_suggestions_change(page, tmp_path):
    _everything(page, _report(tmp_path))
    page.click("#renameNone")
    page.select_option("#renameKinds", "")           # fields only: a shorter list
    page.wait_for_function("() => !document.getElementById('createBtn').textContent.includes(' 0 of ')"
                           " || document.getElementById('createBtn').textContent.includes('of 1')", timeout=10_000)
    page.wait_for_function("() => document.querySelectorAll('#tableWrap td.sel input').length <= 3", timeout=10_000)
    assert page.js_errors == []


def test_the_server_message_shows_if_a_request_is_refused(page, tmp_path):
    _everything(page, _report(tmp_path))
    # a stale id (here made up by the page) is answered with a clear message, nothing is written
    page.evaluate("""async () => {
      const r = await fetch('/create-workbook', {method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({kinds: 'all', exclude: ['worksheet\\u001f\\u001fno such sheet']})});
      window.__answer = await r.json();
    }""")
    assert "not one of the suggested renames" in page.evaluate("window.__answer.error")
    assert not (tmp_path / "report_renamed.twb").exists()
    page.js_errors.clear()  # the 400 is logged by Chromium on purpose


# --- keyboard and screen reader -----------------------------------------------------------------


def test_keyboard_toggles_a_checkbox_in_a_sensible_order(page, tmp_path):
    _everything(page, _report(tmp_path))
    n = page.locator(BOXES).count()
    page.focus("#tableWrap tbody tr[data-pos='0']")
    page.keyboard.press("Tab")                         # row -> its own checkbox
    assert page.evaluate("document.activeElement.type") == "checkbox"
    assert page.evaluate("document.activeElement.closest('tr').dataset.pos") == "0"
    page.keyboard.press("Space")
    assert _create_label(page) == f"Create with {n - 1} of {n} renames"
    assert page.is_visible("#drawer") is False         # Space on the checkbox does not open the details
    page.keyboard.press("Space")
    assert _create_label(page) == f"Create with {n} of {n} renames"
    # only the active row has its checkbox in the tab order, so Tab never walks through every row
    assert page.locator(BOXES + "[tabindex='0']").count() == 1
    # the arrow keys still move between rows
    page.focus("#tableWrap tbody tr[data-pos='0']")
    page.keyboard.press("ArrowDown")
    assert page.evaluate("document.activeElement.dataset.pos") == "1"
    page.keyboard.press("Tab")
    assert page.evaluate("document.activeElement.closest('tr').dataset.pos") == "1"
    assert page.js_errors == []


def test_controls_come_before_the_table_and_have_names(page, tmp_path):
    _everything(page, _report(tmp_path))
    order = page.evaluate("""() => ['renameAll', 'renameNone', 'createBtn', 'downloadBtn'].map((id) => {
      const e = document.getElementById(id);
      return [id, e.textContent.trim(), e.compareDocumentPosition(document.getElementById('tableWrap'))];
    })""")
    assert all(item[1] for item in order)
    assert all(item[2] & 4 for item in order)          # each one precedes the table in the document
    assert page.get_attribute("#renameSelect", "role") == "group"
    assert page.get_attribute("#renameSelect", "aria-label")
    assert page.get_attribute("#renameCount", "role") == "status"      # the count is announced
    assert page.inner_text("table.tbl thead th.sel").strip() == "Include"


# --- narrow window and dark themes ----------------------------------------------------------------


@pytest.mark.parametrize("size", [(390, 760), (700, 800), (1366, 800)])
def test_works_in_a_narrow_window(browser, gui_server, tmp_path, size):
    pg = new_page(browser, gui_server, viewport={"width": size[0], "height": size[1]})
    try:
        _everything(pg, _report(tmp_path))
        for sel in ("#renameAll", "#renameNone", "#createBtn", "#downloadBtn"):
            box = pg.locator(sel).bounding_box()
            assert box and box["x"] >= 0 and box["x"] + box["width"] <= size[0] + 1, (sel, box, size)
        assert pg.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
        pg.locator(BOXES).first.uncheck()
        assert " of " in _create_label(pg)
        assert pg.js_errors == []
    finally:
        pg.ctx.close()


@pytest.mark.parametrize("scheme", ["light", "dark"])
def test_left_out_rows_and_controls_keep_their_contrast(browser, gui_server, tmp_path, scheme):
    pg = new_page(browser, gui_server, color_scheme=scheme, viewport={"width": 1366, "height": 800})
    try:
        _everything(pg, _report(tmp_path))
        pg.locator(BOXES).nth(1).uncheck()
        pg.locator(BOXES).nth(2).uncheck()
        settle(pg)
        assert failures(pg, "rename review, rows left out") == []
        pg.click("#renameNone")
        settle(pg)
        assert failures(pg, "rename review, nothing selected") == []
    finally:
        pg.ctx.close()


# --- many rows: never all in the page ------------------------------------------------------------


def _big_workbook(n):
    cols = "".join(f"<column caption='ORDER_ITEM_{i}' datatype='integer' name='[item_{i}]' role='dimension' type='ordinal' />"
                   for i in range(n))
    return (f"<?xml version='1.0' encoding='utf-8' ?><workbook version='18.1'><datasources>"
            f"<datasource caption='SALES_DB' name='federated.0grgaor1pd01yy1f0yr380of1ags'>{cols}</datasource>"
            f"</datasources></workbook>")


def test_ten_thousand_suggestions_stay_virtualised_and_the_selection_still_counts(page, tmp_path):
    n = 10_000
    _load(page, str(_report(tmp_path, _big_workbook(n))))
    _open(page, "field-renames")
    page.wait_for_selector(BOXES, timeout=30_000)
    assert page.locator("#tableWrap tbody tr[data-pos]").count() < 120      # a window of rows, not 10,000
    assert page.locator(BOXES).count() < 120
    assert _create_label(page) == f"Create with {n} of {n} renames"
    page.click("#renameNone")
    assert _create_label(page) == f"Create with 0 of {n} renames"
    page.locator(BOXES).first.check()
    assert _create_label(page) == f"Create with 1 of {n} renames"
    page.click("#createBtn")
    _status_has(page, "Saved a fixed copy")
    assert "(1 change)" in page.inner_text("#status")
    text = (tmp_path / "report_renamed.twb").read_text(encoding="utf-8")
    assert text.count("caption='Order Item") + text.count('caption="Order Item') == 1
    assert page.js_errors == []
