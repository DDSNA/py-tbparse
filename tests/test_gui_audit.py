"""The Audit view in real Chromium: findings table, summary, filters, skipped rules, paging, downloads.

Skipped when Chromium cannot start; a skip is not a pass."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
from test_audit import workbook  # noqa: E402
from test_gui_browser import _load, _open, new_page  # noqa: E402,F401  (helpers and fixtures shared with the other GUI tests)


@pytest.fixture
def book(tmp_path):
    return workbook(tmp_path, calcs=[("[Calculation_1]", "Broken", "[Sales] + [Gone]")],
                    conn="<connection class='excel-direct' filename='C:\\Users\\alice\\Desktop\\sales.xlsx'/>")


@pytest.fixture
def big_book(tmp_path):
    """130 unused calculations: 130 A001 findings, more than one page."""
    return workbook(tmp_path, calcs=[(f"[Calculation_{i}]", f"Unused {i:03d}", f"[Sales] * {i}") for i in range(1, 131)],
                    name="big.twb")


def _audit(page, path):
    _load(page, path)
    _open(page, "audit")
    page.wait_for_selector("#tableWrap .audit-summary", timeout=10_000)


def _wait_rows(page, n):
    page.wait_for_function("n => document.querySelectorAll('#auditTable tbody tr').length === n", arg=n, timeout=10_000)


def test_audit_is_in_the_sidebar_and_shows_the_summary_and_the_exit_code(page, book):
    _audit(page, book)
    assert page.inner_text("#viewTitle") == "Audit"
    assert page.inner_text("#auditSummary").startswith("1 error")
    assert 'Exit code 1' in page.inner_text(".audit-exit")
    assert page.get_attribute("#auditSummary", "role") == "status"
    assert page.locator("#auditTable tbody tr").count() >= 3
    assert page.locator("#filter").is_hidden() and page.locator("#exportLink").is_hidden()
    heads = page.locator("#auditTable th").all_inner_texts()
    assert heads == ["Rule", "Severity", "Message", "Object"]
    assert page.js_errors == []


def test_severity_is_written_as_a_word_not_only_a_colour(page, book):
    _audit(page, book)
    row = page.locator('#auditTable tr[data-rule="A003"]')
    assert "Error" in row.locator("td").nth(1).inner_text()
    assert row.locator(".audit-sev span").first.get_attribute("aria-hidden") == "true"


def test_the_severity_and_rule_filters_narrow_the_table_but_not_the_summary(page, book):
    _audit(page, book)
    summary = page.inner_text("#auditSummary")
    page.select_option("#auditSeverity", "error")
    _wait_rows(page, 1)
    assert page.locator("#auditTable tbody tr").first.get_attribute("data-rule") == "A003"
    assert page.inner_text("#auditSummary") == summary
    page.select_option("#auditSeverity", "")
    page.select_option("#auditRule", "A008")
    page.wait_for_function("() => [...document.querySelectorAll('#auditTable tbody tr')].every(r => r.dataset.rule === 'A008')")
    assert page.locator("#auditTable tbody tr").count() == 1


def test_search_filters_and_an_empty_result_says_so(page, book):
    _audit(page, book)
    page.fill("#auditText", "gone")
    _wait_rows(page, 1)
    page.fill("#auditText", "no such words anywhere")
    page.wait_for_selector(".audit-empty", timeout=10_000)
    assert "No finding matches" in page.inner_text(".audit-empty")
    assert page.locator("#auditTable").count() == 0


def test_skipping_a_rule_removes_it_and_can_clear_the_exit_code(page, book):
    _audit(page, book)
    page.click("#auditSkip summary")
    page.check('#auditSkip input[value="A008"]')
    page.wait_for_function("() => !document.querySelector('#auditTable tr[data-rule=A008]')", timeout=10_000)
    assert "without A008" in page.inner_text("#auditSummary")
    assert page.is_visible("#auditSkip .audit-rules")           # the list stays open while you tick more
    page.check('#auditSkip input[value="A003"]')
    page.wait_for_function("() => document.querySelector('.audit-exit').dataset.exit === '0'", timeout=10_000)
    assert "Exit code 0" in page.inner_text(".audit-exit")
    assert page.locator('#auditRule option[value="A003"]').count() == 0     # a skipped rule is not a filter choice
    page.uncheck('#auditSkip input[value="A003"]')
    page.wait_for_function("() => document.querySelector('.audit-exit').dataset.exit === '1'", timeout=10_000)


def test_rows_are_capped_at_one_page_and_the_note_points_to_the_download(page, big_book):
    _audit(page, big_book)
    assert page.locator("#auditTable tbody tr").count() == 100
    assert "Showing 1\u2013100 of 130" in page.inner_text("#auditCount")
    assert "30 more" in page.inner_text("#auditMore") and "Download" in page.inner_text("#auditMore")
    assert page.is_disabled("#auditPrev") and not page.is_disabled("#auditNext")
    page.click("#auditNext")
    page.wait_for_function("() => document.querySelectorAll('#auditTable tbody tr').length === 30", timeout=10_000)
    assert "Showing 101\u2013130 of 130" in page.inner_text("#auditCount")
    assert page.is_disabled("#auditNext") and not page.is_disabled("#auditPrev")
    page.click("#auditPrev")
    _wait_rows(page, 100)


def test_the_downloads_carry_the_skip_and_filters_and_hold_every_row(page, big_book):
    _audit(page, big_book)
    csv_href = page.get_attribute("#auditCsv", "href")
    assert csv_href == "/audit/export?format=csv"
    page.select_option("#auditSeverity", "info")
    page.wait_for_function("() => document.getElementById('auditCsv').getAttribute('href').includes('severity=info')")
    assert page.get_attribute("#auditJson", "href").startswith("/audit/export?format=json")
    with page.expect_download() as info:
        page.click("#auditCsv")
    path = info.value.path()
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    assert len(lines) == 131 and lines[0] == "rule,severity,object,detail,fix"      # all 130, not the 100 on the page
    with page.expect_download() as info:
        page.click("#auditDict")
    assert info.value.suggested_filename.endswith("-dictionary.md")
    assert Path(info.value.path()).read_text(encoding="utf-8").startswith("# ")


def test_a_clean_workbook_says_so(page, wenjie_path):
    _audit(page, wenjie_path)
    text = page.inner_text("#auditSummary")
    assert text.startswith("no findings") or "error" not in text
    if text.startswith("no findings"):
        assert "No findings" in page.inner_text(".audit-empty")
        assert "Exit code 0" in page.inner_text(".audit-exit")


def test_opening_another_workbook_resets_the_choices(page, book, big_book):
    _audit(page, book)
    page.click("#auditSkip summary")
    page.check('#auditSkip input[value="A008"]')
    page.wait_for_function("() => document.getElementById('auditSummary').textContent.includes('without')")
    _load(page, big_book)          # still on the Audit view: it redraws for the new workbook on its own
    page.wait_for_function("() => document.getElementById('auditSummary').textContent.startsWith('130 info')", timeout=10_000)
    assert "without" not in page.inner_text("#auditSummary")
    assert page.is_checked('#auditSkip input[value="A008"]') is False


def test_the_url_hash_opens_the_audit_and_a_phone_gets_a_readable_list(page, book):
    _audit(page, book)
    assert page.evaluate("location.hash") == "#audit"
    page.set_viewport_size({"width": 390, "height": 800})
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    assert page.evaluate("() => getComputedStyle(document.querySelector('#auditTable tr')).display") == "block"
    labels = page.evaluate("() => Array.from(document.querySelector('#auditTable tbody tr').cells, (td) => getComputedStyle(td, '::before').content)")
    assert labels == ['"Rule: "', '"Severity: "', '"Message: "', '"Object: "']   # #142
    assert page.locator("#tableSel").is_visible()
    assert page.evaluate("document.getElementById('tableSel').value") == "audit"
