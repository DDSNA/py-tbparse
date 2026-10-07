"""The Libraries view in real Chromium: the paged list with a selection, export, adding a library with a clash
policy, the clash report, themes and phone width.

Skipped when Chromium cannot start; a skip is not a pass."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
from test_audit import workbook  # noqa: E402
from test_gui_a11y import failures, settle  # noqa: E402,F401  (the rendered-contrast audit)
from test_gui_browser import _load, _open, new_page  # noqa: E402,F401  (helpers and fixtures shared with the other GUI tests)

from py_tbparse import TwbParser, export_library, save_library  # noqa: E402

CALCS = [(f"[Calculation_{i}]", f"Calc {i:03d}", f"[Sales] * {i}") for i in range(1, 131)]


@pytest.fixture
def big(tmp_path):
    """130 calculations and one parameter: 131 rows, more than one page."""
    return workbook(tmp_path, calcs=CALCS, params=[("[Parameter 1]", "Target")], name="big.twb")


@pytest.fixture
def target(tmp_path):
    d = tmp_path / "target"
    d.mkdir()
    return workbook(d, calcs=[("[Calculation_900]", "Calc 001", "[Profit] - 1")], name="target.twb")   # clashes with "Calc 001"


@pytest.fixture
def library_file(tmp_path, big):
    lib = export_library(TwbParser(big), select=["[Calculation_1]", "[Calculation_2]", "[Parameter 1]"], name="Mini")
    out = tmp_path / "libs"
    out.mkdir()
    return save_library(lib, out / "mini.library.json")


def _libraries(page, path):
    _load(page, path)
    _open(page, "libraries")
    page.wait_for_selector("#libTable", timeout=10_000)


def _rows(page, n):
    page.wait_for_function("n => document.querySelectorAll('#libTable tbody tr').length === n", arg=n, timeout=10_000)


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def test_libraries_is_in_the_sidebar_and_lists_the_fields(page, big):
    _libraries(page, big)
    assert page.inner_text("#viewTitle") == "Libraries"
    assert page.evaluate("location.hash") == "#libraries"
    assert page.locator("#libTable th").all_inner_texts()[1:] == ["Name", "Kind", "Type", "Formula or value"]
    assert page.locator("#libTable tbody tr").count() == 100          # one page, never more
    assert page.locator("#filter").is_hidden() and page.locator("#exportLink").is_hidden()
    assert "Nothing selected" in page.inner_text("#libSelected")
    assert page.is_disabled("#libExport")
    assert page.js_errors == []


def test_rows_are_capped_at_one_page_and_paging_works(page, big):
    _libraries(page, big)
    assert "Showing 1–100 of 131" in page.inner_text("#libPageCount")
    assert page.is_disabled("#libPrev") and not page.is_disabled("#libNext")
    page.click("#libNext")
    _rows(page, 31)
    assert "Showing 101–131 of 131" in page.inner_text("#libPageCount")
    page.click("#libPrev")
    _rows(page, 100)


def test_the_selection_survives_paging_and_filters_and_select_all_takes_every_match(page, big):
    _libraries(page, big)
    page.check("#libRow0")
    page.check("#libRow1")
    assert page.inner_text("#libSelected") == "2 selected"
    page.click("#libNext")
    _rows(page, 31)
    page.check("#libRow0")
    assert page.inner_text("#libSelected") == "3 selected"
    page.click("#libPrev")
    _rows(page, 100)
    assert page.is_checked("#libRow0") and page.is_checked("#libRow1") and not page.is_checked("#libRow2")
    page.click("#libClear")
    assert "Nothing selected" in page.inner_text("#libSelected")
    page.fill("#libText", "Calc 01")                                  # Calc 010 .. Calc 019
    _rows(page, 10)
    page.click("#libSelectAll")
    page.wait_for_function("() => document.getElementById('libSelected').textContent === '10 selected'")
    page.fill("#libText", "")
    _rows(page, 100)
    page.click("#libPageBox")                                         # this page's 100 on top of the 10 chosen
    page.wait_for_function("() => /^1\\d\\d selected|^[89]\\d selected/.test(document.getElementById('libSelected').textContent)")
    assert page.evaluate("document.getElementById('libPageBox').checked") is True
    page.select_option("#libKind", "parameter")
    _rows(page, 1)
    assert page.inner_text("#libTable tbody tr .lib-name") == "Target"


def test_export_downloads_the_selection_as_a_library_file(page, big):
    _libraries(page, big)
    page.check("#libRow2")
    page.check("#libRow3")
    page.fill("#libName", "Two calcs")
    with page.expect_download() as info:
        page.click("#libExport")
    assert info.value.suggested_filename == "Two_calcs.library.json"
    lib = json.loads(Path(info.value.path()).read_text(encoding="utf-8"))
    assert lib["format"] == "py-tbparse-library" and lib["name"] == "Two calcs"
    assert {e["caption"] for e in lib["entries"]} == {"Calc 003", "Calc 004"}
    page.wait_for_function("() => document.getElementById('status').textContent.startsWith('Saved')")
    assert page.js_errors == []


def test_adding_a_library_defaults_to_fail_shows_the_clash_and_blocks_the_download(page, target, library_file):
    _libraries(page, target)
    assert page.locator("#libFile").count() == 1 and page.locator("#libPolicy").count() == 0
    page.set_input_files("#libFile", library_file)
    page.wait_for_selector("#libPlanSummary", timeout=10_000)
    assert page.is_checked('#libPolicy input[value="fail"]')                      # the default, as in the CLI
    assert "Mini" in page.inner_text("#libLoaded") and "2 calculations" in page.inner_text("#libLoaded")
    assert page.get_attribute("#libPlanSummary", "data-blocked") == "true"
    assert "Calc 001" in page.inner_text("#libPlanSummary")
    assert page.locator("#libClashes tbody tr").count() == 1
    assert "Stops the import" in page.inner_text("#libClashes tbody tr")
    assert page.is_disabled("#libAdd")
    assert page.locator("#libPlan tbody tr").count() >= 3


def test_rename_policy_adds_a_copy_the_open_workbook_is_untouched_and_nothing_is_written(page, target, library_file, tmp_path):
    before = sorted(p.name for p in Path(target).parent.iterdir())
    digest = _sha(target)
    _libraries(page, target)
    page.set_input_files("#libFile", library_file)
    page.wait_for_selector("#libPlanSummary", timeout=10_000)
    page.check('#libPolicy input[value="rename"]')
    page.wait_for_function("() => document.getElementById('libPlanSummary').dataset.blocked === 'false'", timeout=10_000)
    assert "Added as Calc 001 (2)" in page.inner_text("#libClashes tbody tr")
    page.wait_for_function("() => !document.getElementById('libAdd').disabled")
    with page.expect_download() as info:
        page.click("#libAdd")
    assert info.value.suggested_filename == "target_library.twb"
    out = tmp_path / "saved.twb"
    info.value.save_as(str(out))
    captions = {e["caption"] for e in export_library(TwbParser(str(out)))["entries"]}
    assert {"Calc 001", "Calc 001 (2)", "Calc 002", "Target"} <= captions
    assert _sha(target) == digest and sorted(p.name for p in Path(target).parent.iterdir()) == before
    page.wait_for_function("() => document.getElementById('status').textContent.includes('open workbook is unchanged')")


def test_skip_policy_keeps_the_workbooks_field(page, target, library_file):
    _libraries(page, target)
    page.set_input_files("#libFile", library_file)
    page.wait_for_selector("#libPlanSummary", timeout=10_000)
    page.check('#libPolicy input[value="skip"]')
    page.wait_for_function("() => document.getElementById('libPlanSummary').textContent.includes('skipped for a clash')", timeout=10_000)
    assert "Skipped; the workbook keeps its own field" in page.inner_text("#libClashes tbody tr")
    assert not page.is_disabled("#libAdd")


def test_a_file_that_is_not_a_library_is_refused_with_a_reason(page, big, tmp_path):
    bad = tmp_path / "notes.json"
    bad.write_text('{"hello": 1}', encoding="utf-8")
    _libraries(page, big)
    page.set_input_files("#libFile", str(bad))
    page.wait_for_function("() => document.getElementById('status').textContent.includes('not a py-tbparse library')", timeout=10_000)
    assert page.locator("#libPolicy").count() == 0
    assert page.locator("#libLoaded").count() == 0


def test_nothing_to_add_disables_the_download(page, big, library_file):
    _libraries(page, big)                      # the library came from this very workbook: all identical
    page.set_input_files("#libFile", library_file)
    page.wait_for_selector("#libPlanSummary", timeout=10_000)
    assert "identical" in page.inner_text("#libPlanSummary") and page.is_disabled("#libAdd")
    assert "nothing to add" in page.inner_text(".lib-go").lower()


def test_an_empty_list_says_why_the_counted_calculation_is_not_there(page, tmp_path):
    # the sidebar counts one calculated field; the list is empty because it is Tableau's own record count (#144)
    _load(page, str(Path(__file__).parent / "fixtures" / "public" / "TABLEAU_10_TWBX.twbx"))
    _open(page, "libraries")
    page.wait_for_selector("#libEmpty", timeout=10_000)
    text = page.inner_text("#libEmpty")
    assert "no calculated fields or parameters that a library can hold" in text
    assert "1 calculation not listed because Tableau made it itself" in text and "Number of Records" in text
    assert page.locator("#libNotListed").count() == 0
    assert page.js_errors == []


def test_a_list_with_rows_also_names_what_it_leaves_out(page, tmp_path):
    extra = ("<column caption='Region (group)' datatype='string' name='[Region (group)]' role='dimension' type='nominal'>"
             "<calculation class='categorical-bin' column='[Region]' new-bin='true'/></column>")
    path = workbook(tmp_path, calcs=CALCS[:2], ds_extra=extra, name="groups.twb")
    _libraries(page, path)
    _rows(page, 2)
    assert page.inner_text("#libNotListed") == "1 group or bin not listed because it is not a formula: Region (group)."
    assert page.js_errors == []


def test_opening_another_workbook_resets_the_view(page, big, target, library_file):
    _libraries(page, big)
    page.check("#libRow0")
    page.set_input_files("#libFile", library_file)
    page.wait_for_selector("#libPlanSummary", timeout=10_000)
    _load(page, target)                        # still on Libraries: redrawn for the new workbook
    page.wait_for_function("() => document.querySelectorAll('#libTable tbody tr').length === 1", timeout=10_000)
    assert "Nothing selected" in page.inner_text("#libSelected")
    assert page.locator("#libLoaded").count() == 0


@pytest.mark.parametrize("scheme", ["light", "dark"])
def test_contrast_in_both_themes_with_a_clash_report(browser, gui_server, target, library_file, scheme):
    pg = new_page(browser, gui_server, color_scheme=scheme, viewport={"width": 1280, "height": 900})
    try:
        _libraries(pg, target)
        pg.check("#libRow0")
        pg.set_input_files("#libFile", library_file)
        pg.wait_for_selector("#libClashes", timeout=10_000)
        settle(pg)
        found = failures(pg, f"libraries ({scheme}), blocked by a clash")
        pg.check('#libPolicy input[value="rename"]')
        pg.wait_for_function("() => document.getElementById('libPlanSummary').dataset.blocked === 'false'", timeout=10_000)
        settle(pg)
        found += failures(pg, f"libraries ({scheme}), rename")
        assert found == []
        assert pg.js_errors == []
    finally:
        pg.ctx.close()


def test_a_phone_gets_a_readable_page_without_sideways_scroll(browser, gui_server, target, library_file):
    pg = new_page(browser, gui_server, viewport={"width": 390, "height": 800})
    try:
        _load(pg, target)
        pg.select_option("#tableSel", "libraries")           # the sidebar is a select on a phone
        pg.wait_for_selector("#libTable", timeout=10_000)
        pg.set_input_files("#libFile", library_file)
        pg.wait_for_selector("#libClashes", timeout=10_000)
        assert pg.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
        assert pg.evaluate("() => getComputedStyle(document.querySelector('#libTable tr')).display") == "block"
        labels = pg.evaluate("() => Array.from(document.querySelector('#libTable tbody tr').cells, (td) => getComputedStyle(td, '::before').content)")
        assert labels == ["none", "none", '"Kind: "', '"Type: "', '"Formula or value: "']   # #142
        assert pg.evaluate("() => document.getElementById('tableWrap').scrollWidth <= document.getElementById('tableWrap').clientWidth + 1")
        assert pg.is_visible("#libAdd") and pg.is_visible("#libExport")
        assert pg.js_errors == []
    finally:
        pg.ctx.close()
