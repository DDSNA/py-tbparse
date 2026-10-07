"""The Styles view in real Chromium: the palette list with colour chips, the check results, export of the ticked
palettes (style file and Preferences.tps), adding palettes from a file with a clash policy, themes and phone width.

Skipped when Chromium cannot start; a skip is not a pass."""

from __future__ import annotations

import hashlib
import json
import shutil
import sys
from pathlib import Path

import pytest
from lxml import etree

sys.path.insert(0, str(Path(__file__).parent))
from test_gui_a11y import failures, settle  # noqa: E402,F401  (the rendered-contrast audit)
from test_gui_browser import _load, _open, new_page  # noqa: E402,F401  (helpers and fixtures shared with the other GUI tests)

from py_tbparse import TwbParser, read_palettes  # noqa: E402

FIX = Path(__file__).parent / "fixtures"
STYLE = FIX / "style"


@pytest.fixture
def wb(tmp_path):
    """Acme Brand, Acme Ramp, Acme Diverging."""
    d = tmp_path / "wb"
    d.mkdir()
    path = d / "palettes.twb"
    shutil.copy(STYLE / "palettes.twb", path)
    return str(path)


@pytest.fixture
def big(tmp_path):
    """130 palettes: more than one page."""
    root = etree.Element("workbook")
    prefs = etree.SubElement(root, "preferences")
    for i in range(130):
        pal = etree.SubElement(prefs, "color-palette", name=f"Palette {i:03d}", type="regular")
        for c in range(3):
            etree.SubElement(pal, "color").text = f"#{(i * 7 + c * 40) % 256:02X}{c * 50:02X}AA"
    d = tmp_path / "big"
    d.mkdir()
    path = d / "big.twb"
    path.write_bytes(etree.tostring(etree.ElementTree(root), xml_declaration=True, encoding="utf-8"))
    return str(path)


@pytest.fixture
def tps():
    return str(STYLE / "Preferences.tps")        # Acme Brand (other colours: a clash) and Retail Teal


def _styles(page, path):
    _load(page, path)
    _open(page, "styles")
    page.wait_for_selector("#styH1", timeout=10_000)


def _rows(page, n):
    page.wait_for_function("n => document.querySelectorAll('#styTable tbody tr').length === n", arg=n, timeout=10_000)


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def test_styles_is_in_the_sidebar_and_lists_the_palettes_with_chips(page, wb):
    _styles(page, wb)
    assert page.inner_text("#viewTitle") == "Styles"
    assert page.evaluate("location.hash") == "#styles"
    assert page.locator("#styTable th").all_inner_texts()[1:] == ["Name", "Type", "Colours", "Count"]
    assert page.locator("#styTable tbody tr").count() == 3
    assert page.locator("#filter").is_hidden() and page.locator("#exportLink").is_hidden()
    first = page.locator("#styTable tbody tr").first
    assert "Acme Brand" in first.inner_text() and "Regular" in first.inner_text()
    assert first.locator(".sty-n").inner_text() == "4"
    chips = first.locator(".sty-chip")
    assert chips.count() == 4
    # the hex is the accessible name, not the colour alone
    assert [chips.nth(i).get_attribute("aria-label") for i in range(4)] == ["#1A3A5C", "#C9973A", "#7A9E7E", "#B5483A"]
    assert chips.nth(0).get_attribute("title") == "#1A3A5C"
    assert page.evaluate("() => getComputedStyle(document.querySelector('.sty-chip')).backgroundColor") == "rgb(26, 58, 92)"
    assert "#1A3A5C #C9973A" in first.locator(".sty-hex").inner_text() or first.locator(".sty-hex code").count() == 1
    assert "no problems" in page.inner_text("#styCheck").lower()
    assert "Nothing selected" in page.inner_text("#stySelected") and page.is_disabled("#styExport") and page.is_disabled("#styExportTps")
    assert page.js_errors == []


def test_rows_are_capped_at_one_page_and_paging_works(page, big):
    _styles(page, big)
    assert page.locator("#styTable tbody tr").count() == 100
    assert "Showing 1–100 of 130" in page.inner_text("#styCount")
    page.click("#styNext")
    _rows(page, 30)
    page.click("#styPrev")
    _rows(page, 100)
    page.fill("#styText", "Palette 12")
    _rows(page, 10)
    page.click("#stySelectAll")
    page.wait_for_function("() => document.getElementById('stySelected').textContent === '10 selected'")


def test_export_downloads_a_style_file_and_a_preferences_tps(page, wb, tmp_path):
    before = sorted(p.name for p in Path(wb).parent.iterdir())
    _styles(page, wb)
    page.check("#styRow0")
    page.check("#styRow2")
    page.fill("#styName", "Two palettes")
    with page.expect_download() as info:
        page.click("#styExport")
    assert info.value.suggested_filename == "Two_palettes.style.json"
    style = json.loads(Path(info.value.path()).read_text(encoding="utf-8"))
    assert [p["name"] for p in style["palettes"]] == ["Acme Brand", "Acme Diverging"]
    with page.expect_download() as info:
        page.click("#styExportTps")
    assert info.value.suggested_filename == "Preferences_palettes.tps"
    root = etree.fromstring(Path(info.value.path()).read_bytes())
    assert [e.get("name") for e in root.xpath("/workbook/preferences/color-palette")] == ["Acme Brand", "Acme Diverging"]
    page.wait_for_function("() => document.getElementById('status').textContent.includes('never replaces your Preferences.tps')")
    assert sorted(p.name for p in Path(wb).parent.iterdir()) == before
    assert page.js_errors == []


def test_adding_palettes_defaults_to_fail_shows_the_clash_and_blocks_the_download(page, wb, tps):
    _styles(page, wb)
    assert page.locator("#styFile").count() == 1 and page.locator("#stylePolicy").count() == 0
    page.set_input_files("#styFile", tps)
    page.wait_for_selector("#styPlanSummary", timeout=10_000)
    assert page.is_checked('#stylePolicy input[value="fail"]')
    assert page.get_attribute("#styPlanSummary", "data-blocked") == "true"
    assert page.locator("#styClashes tbody tr").count() == 1
    assert "Acme Brand" in page.inner_text("#styClashes tbody tr") and "Stops the import" in page.inner_text("#styClashes tbody tr")
    assert page.is_disabled("#styAdd")
    assert page.locator("#styPlan tbody tr").count() == 2
    assert page.locator("#styPlan .sty-chip").count() == 4              # chips in the plan too, with names


def test_rename_adds_a_copy_the_open_workbook_is_untouched_and_nothing_is_written(page, wb, tps, tmp_path):
    before = sorted(p.name for p in Path(wb).parent.iterdir())
    digest = _sha(wb)
    _styles(page, wb)
    page.set_input_files("#styFile", tps)
    page.wait_for_selector("#styPlanSummary", timeout=10_000)
    page.check('#stylePolicy input[value="rename"]')
    page.wait_for_function("() => document.getElementById('styPlanSummary').dataset.blocked === 'false'", timeout=10_000)
    assert "Added as Acme Brand (2)" in page.inner_text("#styClashes tbody tr")
    page.wait_for_function("() => !document.getElementById('styAdd').disabled")
    with page.expect_download() as info:
        page.click("#styAdd")
    assert info.value.suggested_filename == "palettes_palettes.twb"
    out = tmp_path / "saved.twb"
    info.value.save_as(str(out))
    names = [p["name"] for p in read_palettes(TwbParser(str(out)))]
    assert names == ["Acme Brand", "Acme Ramp", "Acme Diverging", "Acme Brand (2)", "Retail Teal"]
    assert _sha(wb) == digest and sorted(p.name for p in Path(wb).parent.iterdir()) == before
    page.wait_for_function("() => document.getElementById('status').textContent.includes('open workbook is unchanged')")


def test_replace_and_skip_policies(page, wb, tps):
    _styles(page, wb)
    page.set_input_files("#styFile", tps)
    page.wait_for_selector("#styPlanSummary", timeout=10_000)
    page.check('#stylePolicy input[value="skip"]')
    page.wait_for_function("() => document.getElementById('styPlanSummary').textContent.includes('skipped for a clash')", timeout=10_000)
    assert "Skip, keep existing" in page.inner_text("#styClashes tbody tr") and not page.is_disabled("#styAdd")
    page.check('#stylePolicy input[value="replace"]')
    page.wait_for_function("() => document.getElementById('styPlanSummary').textContent.includes('to replace')", timeout=10_000)
    assert "Replace existing" in page.inner_text("#styClashes tbody tr")


def test_a_file_that_is_not_a_palette_file_is_refused_with_a_reason(page, wb, tmp_path):
    bad = tmp_path / "notes.json"
    bad.write_text('{"hello": 1}', encoding="utf-8")
    _styles(page, wb)
    page.set_input_files("#styFile", str(bad))
    page.wait_for_function("() => document.getElementById('status').textContent.includes('expected a .style.json')", timeout=10_000)
    assert page.locator("#stylePolicy").count() == 0 and page.locator("#styLoaded").count() == 0


def test_check_results_show_unusable_palettes_and_they_cannot_be_ticked(page, tmp_path):
    root = etree.parse(str(STYLE / "bad.tps")).getroot()
    doc = etree.parse(str(FIX / "test_for_wenjie.twb"))
    prefs = doc.xpath("/workbook/preferences")[0]
    for el in root.xpath("/workbook/preferences/color-palette"):
        prefs.append(el)
    path = tmp_path / "badpal.twb"
    doc.write(str(path), xml_declaration=True, encoding="utf-8")
    _styles(page, str(path))
    assert "problem" in page.inner_text("#styCheck") and "Bad colour" in page.inner_text("#styCheck")
    bad = page.locator('#styTable tbody tr[data-status="invalid"]').first
    assert bad.locator("input[type=checkbox]").is_disabled()
    assert "Not usable" in bad.inner_text()


def test_opening_another_workbook_resets_the_view(page, wb, big, tps):
    _styles(page, wb)
    page.check("#styRow0")
    page.set_input_files("#styFile", tps)
    page.wait_for_selector("#styPlanSummary", timeout=10_000)
    _load(page, big)
    page.wait_for_function("() => document.querySelectorAll('#styTable tbody tr').length === 100", timeout=10_000)
    assert "Nothing selected" in page.inner_text("#stySelected") and page.locator("#styLoaded").count() == 0


@pytest.mark.parametrize("scheme", ["light", "dark"])
def test_contrast_in_both_themes_with_a_clash_report(browser, gui_server, wb, tps, scheme):
    pg = new_page(browser, gui_server, color_scheme=scheme, viewport={"width": 1280, "height": 900})
    try:
        _styles(pg, wb)
        pg.check("#styRow0")
        pg.set_input_files("#styFile", tps)
        pg.wait_for_selector("#styClashes", timeout=10_000)
        settle(pg)
        found = failures(pg, f"styles ({scheme}), blocked by a clash")
        pg.check('#stylePolicy input[value="rename"]')
        pg.wait_for_function("() => document.getElementById('styPlanSummary').dataset.blocked === 'false'", timeout=10_000)
        settle(pg)
        found += failures(pg, f"styles ({scheme}), rename")
        assert found == []
        assert pg.js_errors == []
    finally:
        pg.ctx.close()


def test_a_phone_gets_a_readable_page_without_sideways_scroll(browser, gui_server, wb, tps):
    pg = new_page(browser, gui_server, viewport={"width": 390, "height": 800})
    try:
        _load(pg, wb)
        pg.select_option("#tableSel", "styles")           # the sidebar is a select on a phone
        pg.wait_for_selector("#styTable", timeout=10_000)
        pg.set_input_files("#styFile", tps)
        pg.wait_for_selector("#styClashes", timeout=10_000)
        assert pg.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
        assert pg.evaluate("() => getComputedStyle(document.querySelector('#styTable tr')).display") == "block"
        labels = pg.evaluate("() => Array.from(document.querySelector('#styTable tbody tr').cells, (td) => getComputedStyle(td, '::before').content)")
        assert labels == ["none", "none", '"Type: "', '"Colours: "', '"Count: "']   # #142
        assert pg.evaluate("() => document.getElementById('tableWrap').scrollWidth <= document.getElementById('tableWrap').clientWidth + 1")
        assert pg.is_visible("#styAdd") and pg.is_visible("#styExport")
        assert pg.js_errors == []
    finally:
        pg.ctx.close()
