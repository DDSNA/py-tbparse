"""The Dashboards view as cards (#84): the Cards / Table switch, the sketches, paging, the empty states, the phone
layout and the keyboard. The zone list behind it is tested without a browser in test_dashboard_cards.py."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
from cards_fixtures import cards_workbook  # noqa: E402
from test_gui_a11y import failures, settle  # noqa: E402,F401
from test_gui_browser import _load, _open, _wait_meta, new_page  # noqa: E402,F401


@pytest.fixture
def cards_path(tmp_path):
    path = tmp_path / "cards.twb"
    path.write_text(cards_workbook(many_zones=60), encoding="utf-8")
    return str(path)


@pytest.fixture
def lots_path(tmp_path):
    path = tmp_path / "lots.twb"
    path.write_text(cards_workbook(many_zones=3, extra_dashboards=60), encoding="utf-8")
    return str(path)


def _cards(page, path):
    _load(page, path)
    _open(page, "dashboards")
    page.click("#viewCards")
    page.wait_for_selector("#dashCards .dcard", timeout=10_000)


def _card(page, name):
    return page.locator("#dashCards .dcard").filter(has=page.locator(".dcard-name", has_text=name)).first


def test_the_table_is_the_default_and_the_switch_only_shows_on_dashboards(page, cards_path):
    _load(page, cards_path)
    assert page.locator("#dashViewWrap").is_hidden()
    _open(page, "dashboards")
    assert page.locator("#dashViewWrap").is_visible()
    assert page.get_attribute("#viewTable", "aria-pressed") == "true"
    assert page.get_attribute("#viewCards", "aria-pressed") == "false"
    assert page.locator("#tableWrap table, #tableWrap [role=grid]").count() > 0
    assert page.locator("#dashCards").count() == 0
    _open(page, "dashboard-sheets")
    assert page.locator("#dashViewWrap").is_hidden()
    assert page.js_errors == []


def test_a_card_has_chips_names_a_sketch_and_a_link(page, cards_path):
    _cards(page, cards_path)
    card = _card(page, "Mixed 'one'")
    assert card.locator(".dcard-name small").inner_text() == "1200 x 800"
    chips = card.locator(".dchip").all_inner_texts()
    assert chips == ["2 worksheets", "1 filter", "1 parameter", "1 image", "1 text", "1 web page"]
    text = card.locator(".dlist").inner_text()
    assert "Sheet 1, Sheet 2" in text and "Region" in text and "Top N" in text
    # 7 zones drawn (the container is not); a letter goes only into a shape big enough for it, so the thin image
    # and text strips have none (the legend and the colours still tell them apart)
    assert card.locator("svg rect").count() == 7
    letters = card.locator("svg text").evaluate_all("els => els.map(e => e.textContent)")
    assert sorted(set(letters)) == ["F", "P", "S", "W"]
    assert card.locator("svg rect.dk-bitmap, svg rect.dk-text").count() == 2
    assert "Layout sketch of Mixed 'one': 7 zones" in card.locator("svg").get_attribute("aria-label")
    assert card.locator("button").count() == 1
    assert page.locator("#meta").inner_text() == "3 dashboard(s)"
    assert page.js_errors == []


def test_a_dashboard_with_no_positions_says_so_instead_of_an_empty_picture(page, cards_path):
    _cards(page, cards_path)
    card = _card(page, "No positions")
    assert card.locator("svg").count() == 0
    assert "No positions are stored" in card.locator(".dthumb").inner_text()
    assert "Nothing placed on it" in card.locator(".dchips").inner_text()


def test_a_busy_sketch_is_capped_and_says_how_many_zones_there_were(page, cards_path):
    _cards(page, cards_path)
    card = _card(page, "Many zones")
    assert card.locator("svg rect").count() == 40
    assert "Sketch shows the 40 largest of 60 zones." in card.locator(".dcap").inner_text()
    assert _card(page, "Mixed").locator(".dcap").count() == 0


def test_the_choice_of_cards_or_table_is_remembered(page, cards_path):
    _cards(page, cards_path)
    assert page.get_attribute("#viewCards", "aria-pressed") == "true"
    _open(page, "datasources")
    _open(page, "dashboards")
    page.wait_for_selector("#dashCards .dcard")
    page.reload()
    _load(page, cards_path)
    _open(page, "dashboards")
    page.wait_for_selector("#dashCards .dcard")
    page.click("#viewTable")
    page.wait_for_selector("#tableWrap table")
    assert page.locator("#dashCards").count() == 0
    assert page.get_attribute("#viewTable", "aria-pressed") == "true"
    page.reload()
    _load(page, cards_path)
    _open(page, "dashboards")
    page.wait_for_selector("#tableWrap table")
    assert page.locator("#dashCards").count() == 0
    assert page.js_errors == []


def test_the_filter_box_narrows_the_cards_and_escape_brings_them_back(page, cards_path):
    _cards(page, cards_path)
    page.fill("#filter", "mixed")
    page.wait_for_function("() => document.querySelectorAll('#dashCards .dcard').length === 1")
    assert page.locator("#meta").inner_text() == "1 of 3 dashboard(s)"
    page.fill("#filter", "zzz")
    page.wait_for_selector("#tableWrap .empty-state")
    assert "No matches" in page.inner_text("#tableWrap .empty-state")
    page.press("#filter", "Escape")
    page.wait_for_function("() => document.querySelectorAll('#dashCards .dcard').length === 3")


def test_the_link_opens_dashboard_sheets_filtered_to_that_dashboard_from_the_keyboard(page, cards_path):
    _cards(page, cards_path)
    button = _card(page, "Many zones").locator("button")
    button.focus()
    page.keyboard.press("Enter")
    page.wait_for_function("() => document.querySelector('.nav-item[aria-current=page]').dataset.table === 'dashboard-sheets'")
    assert page.input_value("#dashboardSel") == "Many zones"
    _wait_meta(page, "60 row(s)")
    assert page.locator("#dashViewWrap").is_hidden()
    assert page.js_errors == []


def test_paging_draws_24_cards_at_a_time_never_all(page, lots_path):
    _cards(page, lots_path)             # 63 dashboards
    assert page.locator("#dashCards .dcard").count() == 24
    assert page.inner_text(".dpager .note") == "Showing 1 to 24 of 63 dashboards"
    assert page.is_disabled("#cardsPrev") and not page.is_disabled("#cardsNext")
    names = page.locator("#dashCards .dcard-name").all_inner_texts()
    page.click("#cardsNext")
    page.wait_for_function("() => document.querySelector('.dpager .note').textContent.startsWith('Showing 25')")
    assert page.locator("#dashCards .dcard").count() == 24
    assert page.locator("#dashCards .dcard-name").all_inner_texts()[0] not in [n.split("\n")[0] for n in names]
    assert page.evaluate("() => document.activeElement.id") == "dashCards"
    page.click("#cardsNext")
    page.wait_for_function("() => document.querySelector('.dpager .note').textContent.startsWith('Showing 49')")
    assert page.locator("#dashCards .dcard").count() == 15
    assert page.is_disabled("#cardsNext")
    page.click("#cardsPrev")
    page.wait_for_function("() => document.querySelector('.dpager .note').textContent.startsWith('Showing 25')")
    # a filter goes back to the first page
    page.fill("#filter", "extra 00")
    page.wait_for_function("() => document.querySelectorAll('#dashCards .dcard').length === 10")
    assert page.locator(".dpager").count() == 0
    assert page.js_errors == []


def test_on_a_phone_the_cards_are_one_column_with_no_sideways_scroll(browser, gui_server, cards_path):
    page = new_page(browser, gui_server, viewport={"width": 375, "height": 800})
    try:
        _load(page, cards_path)
        page.select_option("#tableSel", "dashboards")
        page.wait_for_selector("#viewCards")
        page.click("#viewCards")
        page.wait_for_selector("#dashCards .dcard")
        boxes = [page.locator("#dashCards .dcard").nth(i).bounding_box() for i in range(3)]
        assert len({round(b["x"]) for b in boxes}) == 1          # one column
        assert all(b["x"] >= 0 and b["x"] + b["width"] <= 375 for b in boxes)
        assert page.evaluate("() => document.documentElement.scrollWidth <= window.innerWidth")
        assert page.evaluate("() => document.getElementById('tableWrap').scrollWidth <= document.getElementById('tableWrap').clientWidth")
        assert page.js_errors == []
    finally:
        page.ctx.close()


def test_on_a_wide_window_the_cards_sit_side_by_side(browser, gui_server, cards_path):
    page = new_page(browser, gui_server, viewport={"width": 1360, "height": 900})
    try:
        _cards(page, cards_path)
        settle(page)
        a, b = (page.locator("#dashCards .dcard").nth(i).bounding_box() for i in range(2))
        assert abs(a["y"] - b["y"]) < 1 and b["x"] > a["x"]
    finally:
        page.ctx.close()


@pytest.mark.parametrize("mode", ["light", "dark"])
def test_the_cards_view_passes_the_accessibility_checks_in_both_modes(browser, gui_server, cards_path, mode):
    page = new_page(browser, gui_server, color_scheme=mode)
    try:
        _cards(page, cards_path)
        settle(page)
        assert failures(page, "cards " + mode) == []
        names = page.locator("#dashCards [role=listitem]").count()
        assert names == 3
        assert page.get_attribute("#dashCards", "role") == "list"
    finally:
        page.ctx.close()
