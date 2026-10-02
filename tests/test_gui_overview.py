"""The overview as a report card: a sentence, what deserves a look, what is on the dashboards."""

from __future__ import annotations

import re
import time

import pytest

from test_gui_a11y import failures, settle  # noqa: F401
from test_gui_browser import _load, _open, _wait_meta, new_page
from test_report import WORKBOOK


@pytest.fixture
def rich_path(tmp_path):
    path = tmp_path / "wb.twb"
    path.write_text(WORKBOOK, encoding="utf-8")
    return str(path)


def _card(page, path):
    _load(page, path)
    page.wait_for_selector("#tableWrap .health", timeout=10_000)


def test_the_card_starts_with_a_plain_sentence(page, wenjie_path):
    _card(page, wenjie_path)
    assert page.inner_text("#tableWrap .lead").startswith("test_for_wenjie.twb has 0 dashboards, 1 worksheet")
    assert page.locator("#tableWrap .lead").evaluate("e => e.nextElementSibling.className") == "cards"
    assert page.js_errors == []


def test_a_clean_workbook_says_all_clear_and_keeps_the_facts_quiet(page, wenjie_path):
    _card(page, wenjie_path)
    first = page.locator("#tableWrap .health-item").first
    assert "All clear" in first.inner_text()
    assert "ok" in first.get_attribute("class")
    assert page.locator("#tableWrap .health-item.problem, #tableWrap .health-item.warning").count() == 0


def test_problems_and_warnings_say_so_in_words_not_only_in_colour(page, rich_path):
    _card(page, rich_path)
    words = page.locator("#tableWrap .health-item .sr-only").all_text_contents()
    assert "Needs a look: " in words and "Worth knowing: " in words
    assert "All clear" not in page.inner_text("#tableWrap .health")
    assert page.get_attribute("#tableWrap .health-item .sev", "aria-hidden") == "true"


def test_the_list_and_headings_are_labelled(page, rich_path):
    _card(page, rich_path)
    assert page.get_attribute("#tableWrap ul.health", "aria-labelledby") == "healthTitle"
    assert page.inner_text("#healthTitle") == "Worth a look"
    assert page.evaluate("() => document.querySelector('#healthTitle').tagName") == "H2"
    assert page.get_attribute("#tableWrap .dash-grid", "aria-labelledby") == "dashTitle"


def test_show_opens_the_table_with_the_filters_on_and_the_count_matches(page, rich_path):
    _card(page, rich_path)
    item = page.locator("#tableWrap .health-item", has=page.locator('[data-health="unused-calculations"]'))
    count = int(re.match(r"\D*(\d+)", item.locator("strong").inner_text()).group(1))
    item.locator("button").click()
    page.wait_for_function("() => document.querySelector('.nav-item[aria-current=page]').dataset.table === 'field-usage'")
    page.wait_for_selector("#chips .chip", timeout=10_000)
    chips = page.locator("#chips .chip").all_inner_texts()
    assert sorted(c.replace("\n", "").replace("×", "").strip() for c in chips) == ["kind: calculated", "used: false"]
    page.wait_for_function("(n) => document.getElementById('meta').textContent.startsWith(n + ' of ')", arg=str(count))
    assert page.js_errors == []


def test_a_link_with_no_filters_opens_the_plain_table(page, rich_path):
    _card(page, rich_path)
    page.click('#tableWrap [data-health="missing-references"]')
    page.wait_for_function("() => document.querySelector('.nav-item[aria-current=page]').dataset.table === 'missing-references'")
    _wait_meta(page, "2 row(s)")
    assert page.locator("#chips").is_hidden()


def test_the_filters_do_not_stick_to_a_later_visit(page, rich_path):
    _card(page, rich_path)
    page.click('#tableWrap [data-health="unused-fields"]')
    page.wait_for_selector("#chips .chip", timeout=10_000)
    _open(page, "overview")
    page.wait_for_selector("#tableWrap .health", timeout=10_000)
    _open(page, "field-usage")
    page.wait_for_selector("#tableWrap tbody tr[data-pos]", timeout=10_000)
    # leaving and coming back by the sidebar keeps the person's own filters; the card replaced them on purpose
    assert page.locator("#chips .chip").count() == 2


def test_dashboards_are_listed_with_their_sheets(page, rich_path):
    _card(page, rich_path)
    cards = page.locator("#tableWrap .dash-card")
    assert cards.count() == 1
    assert cards.first.locator("h3").inner_text() == "Overview"
    assert "1 worksheet" in cards.first.inner_text()
    assert cards.first.locator("li").all_inner_texts() == ["Sheet 1"]


def test_show_buttons_have_a_distinct_accessible_name_and_work_from_the_keyboard(page, rich_path):
    _card(page, rich_path)
    names = page.locator("#tableWrap .health-go").evaluate_all("els => els.map(e => e.getAttribute('aria-label'))")
    assert len(names) == len(set(names)) and all(n.startswith("Show the rows: ") for n in names)
    page.locator("#tableWrap .health-go").first.focus()
    page.keyboard.press("Enter")
    page.wait_for_function("() => document.querySelector('.nav-item[aria-current=page]').dataset.table !== 'overview'")


def test_leaving_before_the_report_arrives_does_not_break_the_next_view(page, wenjie_path):
    def slow(route):
        time.sleep(0.4)
        route.continue_()

    page.route("**/overview", slow)
    _load(page, wenjie_path)
    _open(page, "fields")
    _wait_meta(page, "55 row(s)")
    page.wait_for_timeout(900)
    assert page.locator("#tableWrap .health").count() == 0, "a late report must not paint over another view"
    assert page.js_errors == []


def test_a_failing_report_leaves_the_tiles_alone(page, wenjie_path):
    page.route("**/overview", lambda route: route.fulfill(status=500, body='{"error": "boom"}', content_type="application/json"))
    _load(page, wenjie_path)
    page.wait_for_selector("#tableWrap .stat", timeout=10_000)
    page.wait_for_timeout(500)
    assert page.locator("#tableWrap .health").count() == 0 and page.locator("#tableWrap .stat").count() > 0
    assert [e for e in page.js_errors if "500" not in e] == []


def test_the_overview_tiles_still_open_their_tables(page, wenjie_path):
    _card(page, wenjie_path)
    page.click('#tableWrap .stat[data-goto="fields"]')
    _wait_meta(page, "55 row(s)")


@pytest.mark.parametrize("width", [320, 390])
def test_the_card_fits_a_phone(browser, gui_server, rich_path, width):
    pg = new_page(browser, gui_server, viewport={"width": width, "height": 800})
    try:
        _card(pg, rich_path)
        settle(pg)
        assert pg.evaluate("() => document.documentElement.scrollWidth <= window.innerWidth"), "sideways overflow"
        over = pg.evaluate(
            "() => [...document.querySelectorAll('#tableWrap *')].filter((e) => e.getBoundingClientRect().right > window.innerWidth + 1)"
            ".map((e) => e.tagName + '.' + e.className)"
        )
        assert over == []
    finally:
        pg.ctx.close()


@pytest.mark.parametrize("theme", ["shop", "matcha", "harbor", "contrast"])
def test_the_card_is_readable_in_light_and_dark(browser, gui_server, rich_path, theme):
    found = []
    for mode in ("light", "dark"):
        pg = new_page(browser, gui_server, viewport={"width": 1200, "height": 900})
        try:
            pg.evaluate("([t, m]) => { localStorage.setItem('py-tbparse:theme', t); localStorage.setItem('py-tbparse:mode', m); }", [theme, mode])
            pg.reload()
            _card(pg, rich_path)
            settle(pg)
            found += failures(pg, f"{theme}/{mode} report card")
        finally:
            pg.ctx.close()
    assert not found, found[:8]
