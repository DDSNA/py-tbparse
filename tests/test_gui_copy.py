"""The Slice and copy view in real Chromium: the paged lists of dashboards and worksheets, the slice plan and its
download, choosing a target workbook, the copy plan with the clash policy (Stop by default), the download, themes and
phone width.

Skipped when Chromium cannot start; a skip is not a pass."""

from __future__ import annotations

import hashlib
import sys
import zipfile
from pathlib import Path

import pytest
from lxml import etree

sys.path.insert(0, str(Path(__file__).parent))
from copy_fixtures import make_many, make_source, make_target  # noqa: E402
from test_gui_a11y import failures  # noqa: E402  (the rendered-contrast audit)
from test_gui_browser import _load, _open, new_page, wait_settled  # noqa: E402,F401  (shared helpers and fixtures)


@pytest.fixture
def src(tmp_path):
    d = tmp_path / "s"
    d.mkdir()
    return make_source(d)


@pytest.fixture
def tgt(tmp_path):
    d = tmp_path / "t"
    d.mkdir()
    return make_target(d)


@pytest.fixture
def many(tmp_path):
    d = tmp_path / "m"
    d.mkdir()
    return make_many(d)


def _copy(page, path):
    _load(page, path)
    _open(page, "copy")
    page.wait_for_selector("#cpyH1", timeout=10_000)
    wait_settled(page)


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _names(data_path):
    return etree.parse(str(data_path)).xpath("/workbook/worksheets/worksheet/@name")


def _target(page, tgt):
    page.set_input_files("#cpyFile", tgt)
    page.wait_for_selector("#cpyLoaded", timeout=10_000)


def _plan(page, selector="#cpyPlanSummary"):
    page.wait_for_selector(selector, timeout=10_000)


def test_copy_is_in_the_sidebar_and_lists_dashboards_and_worksheets(page, src):
    _copy(page, src)
    assert page.inner_text("#viewTitle") == "Slice and copy"
    assert page.evaluate("location.hash") == "#copy"
    assert page.locator("#filter").is_hidden() and page.locator("#exportLink").is_hidden()
    assert page.locator("#cpyDashTable th").all_inner_texts()[1:] == ["Dashboard", "Kind", "Worksheets on it"]
    assert page.locator("#cpyDashTable tbody tr").count() == 3
    assert page.locator("#cpySheetTable tbody tr").count() == 7
    first = page.locator("#cpyDashTable tbody tr").first
    assert "D1" in first.inner_text() and first.locator("td").last.inner_text() == "2"
    assert "Nothing selected" in page.inner_text("#cpyDashSelected")
    assert page.is_disabled("#cpySliceGo")
    assert page.locator("#cpyPolicy").count() == 0          # no target yet, so no policy or plan
    assert "7 worksheets" in page.inner_text("#meta")
    assert page.js_errors == []


def test_lists_are_capped_at_one_page_and_paging_works(page, many):
    _copy(page, many)
    for pre, rows in (("cpyDash", "#cpyDashTable"), ("cpySheet", "#cpySheetTable")):
        assert page.locator(f"{rows} tbody tr").count() == 100
        assert "Showing 1–100 of 250" in page.inner_text(f"#{pre}Count")
        page.click(f"#{pre}Next")
        page.wait_for_function("s => document.querySelectorAll(s + ' tbody tr').length === 100", arg=rows, timeout=10_000)
        page.click(f"#{pre}Next")
        page.wait_for_function("s => document.querySelectorAll(s + ' tbody tr').length === 50", arg=rows, timeout=10_000)
        page.click(f"#{pre}Prev")
        page.click(f"#{pre}Prev")
    page.fill("#cpySheetText", "Sheet 12")
    page.wait_for_function("() => document.querySelectorAll('#cpySheetTable tbody tr').length === 10", timeout=10_000)
    page.click("#cpySheetSelectAll")
    page.wait_for_function("() => document.getElementById('cpySheetSelected').textContent === '10 selected'")
    assert page.evaluate("document.querySelectorAll('#tableWrap tr').length") < 300      # never more than the pages
    assert page.js_errors == []


def test_slice_plan_then_download_gives_only_the_chosen_dashboard(page, src, tmp_path):
    before = sorted(p.name for p in Path(src).parent.iterdir())
    digest = _sha(src)
    _copy(page, src)
    page.check("#cpyDashRow1")                                          # D2
    _plan(page, "#cpySliceSummary")
    assert "keep 1 dashboard and 3 worksheets, remove 2 dashboards and 4 worksheets" in page.inner_text("#cpySliceSummary")
    rows = {tr.get_attribute("data-action") + ":" + tr.locator("td").nth(1).inner_text()
            for tr in page.locator("#cpySliceTable tbody tr").all()}
    assert {"keep:D2", "remove:D1", "keep:S3", "remove:S1"} <= rows
    assert page.locator("#cpySliceActions tbody tr").count() >= 1       # the actions that do not survive are listed
    assert not page.is_disabled("#cpySliceGo")
    with page.expect_download() as info:
        page.click("#cpySliceGo")
    assert info.value.suggested_filename == "source_sliced.twb"
    out = tmp_path / "sliced.twb"
    info.value.save_as(str(out))
    assert _names(out) == ["S3", "S4", "HiddenOnD2"]
    assert etree.parse(str(out)).xpath("/workbook/dashboards/dashboard/@name") == ["D2"]
    page.wait_for_function("() => document.getElementById('status').textContent.includes('open workbook is unchanged')")
    assert _sha(src) == digest and sorted(p.name for p in Path(src).parent.iterdir()) == before
    assert page.js_errors == []


def test_slice_strict_shows_the_refusal_and_disables_the_download(page, src):
    _copy(page, src)
    page.check("#cpyDashRow0")
    _plan(page, "#cpySliceSummary")
    page.check("#cpySliceStrict")
    page.wait_for_selector("#cpySliceError", timeout=10_000)
    assert "--strict" in page.inner_text("#cpySliceError") and page.is_disabled("#cpySliceGo")
    page.uncheck("#cpySliceStrict")
    _plan(page, "#cpySliceSummary")
    assert not page.is_disabled("#cpySliceGo")


def test_copy_defaults_to_stop_lists_the_clash_and_blocks_the_download(page, src, tgt):
    _copy(page, src)
    assert page.locator("#cpyFile").count() == 1
    _target(page, tgt)
    assert "target.twb" in page.inner_text("#cpyLoaded")
    assert page.is_checked('#cpyPolicy input[value="fail"]')
    assert page.is_disabled("#cpyGo")
    page.check("#cpySheetRow2")                                         # S3, already in the target
    page.check("#cpySheetRow0")                                         # S1
    _plan(page)
    assert page.get_attribute("#cpyPlanSummary", "data-blocked") == "true"
    assert "already a sheet or dashboard of the target" in page.inner_text("#cpyPlanSummary")
    assert page.locator("#cpyPlan tbody tr").count() == 2
    assert "Not copied (stops)" in page.inner_text("#cpyPlan tbody tr")
    assert page.is_disabled("#cpyGo") and "Choose Rename or Skip" in page.inner_text(".lib-go >> nth=1")


def test_copy_with_rename_downloads_the_target_with_the_sheets_added(page, src, tgt, tmp_path):
    digests = (_sha(src), _sha(tgt))
    before = sorted(p.name for p in Path(tgt).parent.iterdir())
    _copy(page, src)
    _target(page, tgt)
    page.check("#cpySheetRow0")                                         # S1: needs Calc A, which the target lacks
    page.check("#cpySheetRow2")                                         # S3: the name is taken
    page.check('#cpyPolicy input[value="rename"]')
    page.wait_for_function("() => (document.getElementById('cpyPlanSummary') || {dataset: {}}).dataset.blocked === 'false'", timeout=10_000)
    assert "2 sheets to copy, 0 skipped, 0 refused" in page.inner_text("#cpyPlanSummary")
    assert "copied as S3 (2)" in page.inner_text("#cpyPlan")
    assert "Dropped: action filter" in page.inner_text("#cpyPlan")
    assert "Calc A" in page.inner_text("#cpyLibrary") and "Add to the target" in page.inner_text("#cpyLibrary")
    page.wait_for_function("() => !document.getElementById('cpyGo').disabled")
    with page.expect_download() as info:
        page.click("#cpyGo")
    assert info.value.suggested_filename == "target_sheetcopy.twb"
    out = tmp_path / "copied.twb"
    info.value.save_as(str(out))
    assert _names(out) == ["S3", "S4", "HiddenOnD2", "S1", "S3 (2)"]
    assert "[Calc A]" in etree.parse(str(out)).xpath("//datasource[@name='ds1']/column/@name")
    assert (_sha(src), _sha(tgt)) == digests and sorted(p.name for p in Path(tgt).parent.iterdir()) == before
    page.wait_for_function("() => document.getElementById('status').textContent.includes('not opened in Tableau')")
    assert page.js_errors == []


def test_copy_with_skip_keeps_the_target_and_a_plan_with_nothing_to_copy_cannot_download(page, src, tgt):
    _copy(page, src)
    _target(page, tgt)
    page.check("#cpySheetRow2")                                         # S3 only
    page.check('#cpyPolicy input[value="skip"]')
    page.wait_for_function("() => document.getElementById('cpyPlanSummary') && document.getElementById('cpyPlanSummary').textContent.includes('1 skipped')", timeout=10_000)
    assert "Skipped" in page.inner_text("#cpyPlan tbody tr")
    assert page.is_disabled("#cpyGo") and "No sheet can be copied" in page.inner_text("#cpyGo >> xpath=..")


def test_a_file_that_is_not_a_workbook_is_refused_with_a_reason(page, src, tmp_path):
    bad = tmp_path / "notes.twb"
    bad.write_text("<workbook", encoding="utf-8")
    _copy(page, src)
    page.set_input_files("#cpyFile", str(bad))
    page.wait_for_function("() => document.getElementById('status').textContent.includes('Nothing was copied')", timeout=10_000)
    assert page.locator("#cpyPolicy").count() == 0 and page.locator("#cpyLoaded").count() == 0


def test_a_twbx_target_keeps_its_package(page, src, tgt, tmp_path):
    twbx = tmp_path / "pack.twbx"
    with zipfile.ZipFile(twbx, "w") as z:
        z.write(tgt, "pack.twb")
        z.writestr("Data/a.csv", "Sales\n1\n")
    _copy(page, src)
    _target(page, str(twbx))
    page.check("#cpySheetRow0")
    page.wait_for_function("() => document.getElementById('cpyPlanSummary') && !document.getElementById('cpyGo').disabled", timeout=10_000)
    with page.expect_download() as info:
        page.click("#cpyGo")
    assert info.value.suggested_filename == "pack_sheetcopy.twbx"
    with zipfile.ZipFile(info.value.path()) as z:
        assert "Data/a.csv" in z.namelist()


def test_opening_another_workbook_resets_the_view(page, src, tgt, many):
    _copy(page, src)
    _target(page, tgt)
    page.check("#cpyDashRow0")
    page.check("#cpySheetRow0")
    _plan(page)
    _load(page, many)
    page.wait_for_function("() => document.querySelectorAll('#cpyDashTable tbody tr').length === 100", timeout=10_000)
    assert "Nothing selected" in page.inner_text("#cpyDashSelected") and "Nothing selected" in page.inner_text("#cpySheetSelected")
    assert page.locator("#cpyLoaded").count() == 0 and page.locator("#cpyPolicy").count() == 0


@pytest.mark.parametrize("scheme", ["light", "dark"])
def test_contrast_in_both_themes_with_both_plans_showing(browser, gui_server, src, tgt, scheme):
    pg = new_page(browser, gui_server, color_scheme=scheme, viewport={"width": 1280, "height": 900})
    try:
        _copy(pg, src)
        pg.check("#cpyDashRow0")
        _target(pg, tgt)
        pg.check("#cpySheetRow0")
        pg.check("#cpySheetRow2")
        _plan(pg, "#cpySliceSummary")
        _plan(pg)
        wait_settled(pg)
        found = failures(pg, f"copy ({scheme}), blocked by a clash")
        pg.check('#cpyPolicy input[value="rename"]')
        pg.wait_for_function("() => (document.getElementById('cpyPlanSummary') || {dataset: {}}).dataset.blocked === 'false'", timeout=10_000)
        wait_settled(pg)
        found += failures(pg, f"copy ({scheme}), rename")
        assert found == []
        assert pg.js_errors == []
    finally:
        pg.ctx.close()


def test_a_phone_gets_a_readable_page_without_sideways_scroll(browser, gui_server, src, tgt):
    pg = new_page(browser, gui_server, viewport={"width": 390, "height": 800})
    try:
        _load(pg, src)
        pg.select_option("#tableSel", "copy")             # the sidebar is a select on a phone
        pg.wait_for_selector("#cpyDashTable", timeout=10_000)
        wait_settled(pg)
        _target(pg, tgt)
        pg.check("#cpySheetRow0")
        pg.check("#cpyDashRow0")
        _plan(pg)
        _plan(pg, "#cpySliceSummary")
        wait_settled(pg)
        assert pg.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
        assert pg.evaluate("() => getComputedStyle(document.querySelector('#cpyDashTable tr')).display") == "block"
        assert pg.evaluate("() => document.getElementById('tableWrap').scrollWidth <= document.getElementById('tableWrap').clientWidth + 1")
        assert pg.is_visible("#cpySliceGo") and pg.is_visible("#cpyGo")
        assert pg.js_errors == []
    finally:
        pg.ctx.close()


# the label each cell of the first card shows before its value at phone width (`::before`), or "none"
CARD_LABELS = """sel => Array.from(document.querySelector(sel + ' tbody tr').cells)
  .map((td) => getComputedStyle(td, '::before').content)"""


@pytest.mark.parametrize("scheme", ["light", "dark"])
def test_phone_cards_name_each_value(browser, gui_server, src, tgt, scheme):
    # at 390 px the header row is hidden, so "D1 / Dashboard / 2" needs the column names to mean anything (#142)
    pg = new_page(browser, gui_server, color_scheme=scheme, viewport={"width": 390, "height": 800})
    try:
        _load(pg, src)
        pg.select_option("#tableSel", "copy")
        pg.wait_for_selector("#cpyDashTable", timeout=10_000)
        _target(pg, tgt)
        pg.check("#cpySheetRow0")
        _plan(pg)
        wait_settled(pg)
        # checkbox and name (the card heading) carry no label; every other cell does
        assert pg.evaluate(CARD_LABELS, "#cpyDashTable") == ["none", "none", '"Kind: "', '"Worksheets on it: "']
        assert pg.evaluate(CARD_LABELS, "#cpySheetTable") == ["none", "none", '"Datasource: "']
        assert pg.evaluate(CARD_LABELS, "#cpyPlan") == ["none", '"Datasource: "', '"What happens: "', '"Why or what is dropped: "']
        assert pg.evaluate("() => getComputedStyle(document.querySelector('#cpyDashTable td.lib-name')).fontWeight") == "600"
        found = failures(pg, f"copy cards ({scheme})")                 # the labels are --muted text: AA in both themes
        assert found == []
        pg.set_viewport_size({"width": 1280, "height": 900})           # a real table again: no labels drawn
        wait_settled(pg)
        assert set(pg.evaluate(CARD_LABELS, "#cpyDashTable")) == {"none"}
        assert pg.js_errors == []
    finally:
        pg.ctx.close()
