"""The Templates view in real Chromium (WP9 package 9c): open and close it, choose a template and data, drop
files into the right step, plain messages for the wrong file, server mode, keyboard use.

Skipped when Chromium cannot start; a skip is not a pass."""

from __future__ import annotations

import base64
import csv
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

import py_tbparse.templates as templates
from conftest import new_page
from py_tbparse import load_template, make_template, webgui
from test_gui_browser import _load  # noqa: F401  (helper shared with the other GUI tests)

PUBLIC_FIXTURES = Path(__file__).parent / "fixtures" / "public"

# Drop a file on the element matching `sel` (or on the page when `sel` is empty), the way a browser does:
# dragenter, dragover, drop, bubbling up to the page-level handlers.
DROP_ON = """([b64, name, sel]) => {
  const bytes = Uint8Array.from(atob(b64), (c) => c.charCodeAt(0));
  const dt = new DataTransfer();
  dt.items.add(new File([bytes], name, {type: 'application/octet-stream'}));
  const target = sel ? document.querySelector(sel) : document.body;
  for (const kind of ['dragenter', 'dragover', 'drop']) {
    target.dispatchEvent(new DragEvent(kind, {dataTransfer: dt, bubbles: true, cancelable: true}));
  }
}"""


@pytest.fixture(autouse=True)
def fixed_clock(monkeypatch):
    monkeypatch.setattr(templates, "_now", lambda: "2026-10-05T00:00:00+00:00")


@pytest.fixture
def tpl_file(tmp_path):
    folder = tmp_path / "tpl"
    folder.mkdir()
    return Path(make_template(str(PUBLIC_FIXTURES / "filtering.twb"), output_path=str(folder / "f.template.twbx"),
                              template_id="tpl-1"))


@pytest.fixture
def csv_file(tmp_path, tpl_file):
    t = load_template(str(tpl_file))
    entry = next(e for e in t.manifest["datasources"] if e["fields"])
    path = tmp_path / "data.csv"
    with open(path, "w", newline="", encoding="utf-8") as fh:
        csv.writer(fh).writerow([f["remote"] for f in entry["fields"]])
    return path


@pytest.fixture
def gui(browser):
    """A local GUI with no template or workbook in it, and a page on it."""
    webgui._clear_all_uploads()
    webgui._STATE.base.update(parser=None, path=None, uploaded=False, report=None)
    srv = ThreadingHTTPServer(("127.0.0.1", 0), webgui.Handler)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    url = "http://%s:%d" % srv.server_address
    pg = new_page(browser, url)
    pg.url_base = url
    try:
        yield pg
    finally:
        pg.ctx.close()
        srv.shutdown()
        thread.join(timeout=2)
        webgui._clear_all_uploads()


@pytest.fixture
def server_url():
    saved = dict(webgui._CONFIG)
    webgui._clear_all_uploads()
    webgui._STATE.base.update(parser=None, path=None, uploaded=False, report=None)
    webgui._CONFIG.update(server_mode=True)
    webgui._SESSIONS.clear()
    srv = ThreadingHTTPServer(("127.0.0.1", 0), webgui.Handler)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    try:
        yield "http://%s:%d" % srv.server_address
    finally:
        srv.shutdown()
        thread.join(timeout=2)
        webgui._clear_all_uploads()
        webgui._CONFIG.clear()
        webgui._CONFIG.update(saved)


def _b64(path) -> str:
    return base64.b64encode(Path(path).read_bytes()).decode()


def _open_view(page):
    page.click("#tplBtn")
    page.wait_for_selector("#templatesView:not([hidden])")


def _template_chosen(page, path):
    page.set_input_files("#tplTemplatePick", str(path))
    page.wait_for_selector("#tplCard1[data-state=done]", timeout=15_000)


def _data_chosen(page, path):
    page.set_input_files("#tplDataPick", str(path))
    page.wait_for_selector("#tplCard2[data-state=done]", timeout=15_000)


def _error_shown(page):
    page.wait_for_function("() => document.getElementById('status').classList.contains('err')")
    return page.inner_text("#status")


# --- 1. open and close -------------------------------------------------------------------------------


def test_the_button_opens_the_view_with_no_workbook_and_back_restores_the_start_screen(gui):
    page = gui
    assert page.locator("#templatesView").is_hidden()
    assert page.get_attribute("#tplBtn", "aria-pressed") == "false"
    _open_view(page)
    assert page.get_attribute("#tplBtn", "aria-pressed") == "true"
    assert page.locator("#empty").is_hidden() and page.locator("#controls").is_hidden()
    assert page.url.endswith("#templates")
    assert page.locator("#tplCard1[data-state=todo]").is_visible()
    assert page.get_attribute("#tplCard2", "aria-disabled") == "true"
    assert page.get_attribute("#tplCard3", "aria-disabled") == "true"
    page.click("#tplBack")
    assert page.locator("#templatesView").is_hidden()
    assert page.locator("#empty").is_visible()
    assert "templates" not in page.url
    assert page.get_attribute("#tplBtn", "aria-pressed") == "false"
    assert page.js_errors == []


def test_back_returns_to_the_open_workbook(gui, wenjie_path):
    page = gui
    _load(page, wenjie_path)
    _open_view(page)
    assert page.locator("#controls").is_hidden()
    page.click("#tplBack")
    assert page.locator("#controls").is_visible() and page.locator("#templatesView").is_hidden()
    assert page.url.endswith("#overview")
    assert page.js_errors == []


def test_templates_in_the_address_opens_the_view_on_load(gui):
    page = gui
    page.goto(page.url_base + "/#templates")
    page.wait_for_selector("#templatesView:not([hidden])")
    assert page.get_attribute("#tplBtn", "aria-pressed") == "true"
    assert page.js_errors == []


def test_the_hash_does_not_open_a_table_by_accident(gui, wenjie_path):
    page = gui
    _load(page, wenjie_path)
    _open_view(page)
    page.evaluate("() => { location.hash = '#fields'; }")
    page.wait_for_selector("#templatesView", state="hidden")
    assert page.locator("#controls").is_visible()
    page.evaluate("() => { location.hash = '#templates'; }")
    page.wait_for_selector("#templatesView:not([hidden])")
    assert page.locator("#controls").is_hidden()
    assert page.js_errors == []


# --- 2. choose a template and data ---------------------------------------------------------------------


def test_choosing_a_template_shows_its_name_revision_counts_and_findings(gui, tpl_file):
    page = gui
    _open_view(page)
    _template_chosen(page, tpl_file)
    card = page.locator("#tplCard1")
    assert card.locator(".tpl-file").inner_text() == "f.template.twbx"
    assert card.locator(".tpl-name").inner_text().strip()
    assert "Revision" in card.locator(".tpl-rev").inner_text()
    assert "required field" in card.locator(".tpl-counts").inner_text()
    assert card.locator(".tpl-findings li").count() >= 1       # a freshly made template always has some notes
    assert card.locator(".tpl-findings li").count() <= 50
    # the data step is open now, and focus moved to its heading
    assert page.get_attribute("#tplCard2", "aria-disabled") is None
    assert page.evaluate("() => document.activeElement.id") == "tplH2"
    assert page.js_errors == []


def test_choosing_data_shows_the_kind_and_the_columns(gui, tpl_file, csv_file):
    page = gui
    _open_view(page)
    _template_chosen(page, tpl_file)
    _data_chosen(page, csv_file)
    card = page.locator("#tplCard2")
    assert card.locator(".tpl-file").inner_text() == "data.csv"
    assert "column" in card.locator(".tpl-counts").inner_text()
    assert "CSV" in card.locator(".tpl-kind").inner_text()
    assert page.locator("#tplDataPlace").is_visible()       # the optional "where will this file be" field
    assert page.get_attribute("#tplCard3", "aria-disabled") is None
    assert page.evaluate("() => document.activeElement.id") == "tplH3"
    assert page.js_errors == []


def test_the_view_comes_back_after_a_reload(gui, tpl_file, csv_file):
    page = gui
    _open_view(page)
    _template_chosen(page, tpl_file)
    _data_chosen(page, csv_file)
    page.reload()
    page.wait_for_selector("#tplCard2[data-state=done]", timeout=15_000)
    assert page.locator("#tplCard1[data-state=done]").is_visible()
    assert page.js_errors == []


def test_a_template_can_be_opened_by_its_path_on_a_local_gui(gui, tpl_file):
    page = gui
    _open_view(page)
    page.fill("#tplTemplatePath", str(tpl_file))
    page.click("#tplTemplateOpen")
    page.wait_for_selector("#tplCard1[data-state=done]", timeout=15_000)
    assert page.locator("#tplCard1 .tpl-file").inner_text() == "f.template.twbx"
    assert page.js_errors == []


def test_change_lets_the_person_pick_another_file(gui, tpl_file, csv_file):
    page = gui
    _open_view(page)
    _template_chosen(page, tpl_file)
    page.click("#tplCard1 .tpl-change")
    assert page.locator("#tplCard1[data-state=todo]").is_visible()
    page.click("#tplCard1 .tpl-keep")      # changed their mind
    assert page.locator("#tplCard1[data-state=done]").is_visible()
    assert page.js_errors == []


def test_a_csv_with_no_sheets_has_no_picker_and_an_excel_file_asks_for_a_sheet(gui, tpl_file, csv_file, tmp_path):
    openpyxl = pytest.importorskip("openpyxl")
    page = gui
    _open_view(page)
    _template_chosen(page, tpl_file)
    _data_chosen(page, csv_file)
    assert page.locator("#tplSheetSel").count() == 0
    book = openpyxl.Workbook()
    book.active.title = "First"
    book.active.append(["a", "b"])
    book.create_sheet("Second").append(["c", "d", "e"])
    xlsx = tmp_path / "two.xlsx"
    book.save(xlsx)
    page.click("#tplCard2 .tpl-change")
    page.set_input_files("#tplDataPick", str(xlsx))
    page.wait_for_selector("#tplSheetSel", timeout=15_000)
    assert page.locator("#tplCard2[data-state=todo]").is_visible()       # not done until a sheet is chosen
    page.select_option("#tplSheetSel", "Second")
    page.click("#tplSheetUse")
    page.wait_for_selector("#tplCard2[data-state=done]", timeout=15_000)
    assert "3 columns" in page.locator("#tplCard2 .tpl-counts").inner_text()
    assert page.js_errors == []


# --- 3. drops ---------------------------------------------------------------------------------------------


def test_a_dropped_twbx_with_no_template_is_the_template(gui, tpl_file):
    page = gui
    _open_view(page)
    page.evaluate(DROP_ON, [_b64(tpl_file), "f.template.twbx", ""])
    page.wait_for_selector("#tplCard1[data-state=done]", timeout=15_000)
    assert page.locator("#dropzone").is_hidden()
    assert page.locator("#controls").is_hidden(), "a workbook must not be opened by this drop"
    assert page.js_errors == []


def test_a_drop_on_the_data_card_lands_in_the_data_slot(gui, tpl_file, csv_file):
    page = gui
    _open_view(page)
    _template_chosen(page, tpl_file)
    page.evaluate(DROP_ON, [_b64(csv_file), "data.csv", "#tplCard2"])
    page.wait_for_selector("#tplCard2[data-state=done]", timeout=15_000)
    assert page.locator("#tplCard2 .tpl-file").inner_text() == "data.csv"
    assert page.js_errors == []


def test_a_drop_elsewhere_goes_to_the_first_empty_step(gui, tpl_file, csv_file):
    page = gui
    _open_view(page)
    _template_chosen(page, tpl_file)
    page.evaluate(DROP_ON, [_b64(csv_file), "data.csv", "#tplTitle"])
    page.wait_for_selector("#tplCard2[data-state=done]", timeout=15_000)
    assert page.js_errors == []


def test_the_overlay_says_which_step_a_drop_fills(gui, tpl_file):
    page = gui
    _open_view(page)
    page.evaluate(DROP_ON.replace("['dragenter', 'dragover', 'drop']", "['dragenter']"), [_b64(tpl_file), "x.twbx", ""])
    assert page.locator("#dropzone").is_visible()
    assert "template" in page.inner_text("#dropTitle").lower()


def test_with_the_view_closed_a_drop_still_opens_a_workbook(gui, wenjie_path):
    page = gui
    _open_view(page)
    page.click("#tplBack")
    page.evaluate(DROP_ON, [_b64(wenjie_path), "dropped.twb", ""])
    page.wait_for_function("() => document.getElementById('status').textContent.startsWith('Opened')", timeout=15_000)
    assert page.inner_text("#wbName") == "dropped.twb"
    assert page.js_errors == []


# --- 4. wrong files ---------------------------------------------------------------------------------------


def test_a_csv_in_the_template_step_gets_a_plain_message_and_the_page_stays_usable(gui, csv_file, tpl_file):
    page = gui
    _open_view(page)
    page.set_input_files("#tplTemplatePick", str(csv_file))
    text = _error_shown(page)
    assert text.startswith("That didn’t work:") and ".twbx" in text
    assert page.locator("#tplCard1[data-state=todo]").is_visible()
    _template_chosen(page, tpl_file)                      # still works afterwards
    assert page.js_errors == []


def test_a_text_file_renamed_to_twbx_is_refused_by_the_server_in_plain_words(gui, tmp_path):
    page = gui
    fake = tmp_path / "fake.twbx"
    fake.write_text("just words")
    _open_view(page)
    page.set_input_files("#tplTemplatePick", str(fake))
    assert "not a template" in _error_shown(page)
    assert page.locator("#tplCard1[data-state=todo]").is_visible()
    assert page.js_errors == []


def test_an_unknown_data_file_is_refused_before_it_is_sent(gui, tpl_file, tmp_path):
    page = gui
    other = tmp_path / "notes.json"
    other.write_text("{}")
    _open_view(page)
    _template_chosen(page, tpl_file)
    page.set_input_files("#tplDataPick", str(other))
    text = _error_shown(page)
    assert "notes.json" in text and "csv" in text.lower()
    assert page.locator("#tplCard2[data-state=todo]").is_visible()
    assert page.js_errors == []


def test_a_drop_when_both_steps_are_filled_asks_for_a_card(gui, tpl_file, csv_file):
    page = gui
    _open_view(page)
    _template_chosen(page, tpl_file)
    _data_chosen(page, csv_file)
    page.evaluate(DROP_ON, [_b64(csv_file), "data.csv", "#tplTitle"])
    page.wait_for_function("() => document.getElementById('status').textContent.includes('card')")
    assert page.js_errors == []


# --- 5. server mode ---------------------------------------------------------------------------------------


def test_server_mode_has_no_path_boxes_and_uploads_work(browser, server_url, tpl_file, csv_file):
    page = new_page(browser, server_url)
    try:
        _open_view(page)
        assert page.locator("#tplTemplatePath").count() == 0 and page.locator("#tplDataPath").count() == 0
        _template_chosen(page, tpl_file)
        _data_chosen(page, csv_file)
        assert page.js_errors == []
    finally:
        page.ctx.close()


def test_two_browsers_in_server_mode_keep_their_own_choices(browser, server_url, tpl_file):
    first = new_page(browser, server_url)
    second = new_page(browser, server_url)
    try:
        _open_view(first)
        _template_chosen(first, tpl_file)
        _open_view(second)
        second.wait_for_selector("#tplCard1[data-state=todo]")
        assert second.locator("#tplCard1[data-state=done]").count() == 0
        assert first.js_errors == [] and second.js_errors == []
    finally:
        first.ctx.close()
        second.ctx.close()


# --- 6. keyboard and names --------------------------------------------------------------------------------


def test_every_control_has_a_name_and_tab_reaches_them_in_order(gui, tpl_file):
    page = gui
    _open_view(page)
    names = page.evaluate(
        """() => Array.from(document.querySelectorAll('#templatesView button, #templatesView input, #templatesView select'))
              .filter((n) => n.type !== 'file')
              .map((n) => (n.getAttribute('aria-label') || n.labels && n.labels[0] && n.labels[0].textContent || n.textContent || '').trim())"""
    )
    assert names and all(names), names
    page.focus("#tplBack")
    seen = []
    for _ in range(6):
        page.keyboard.press("Tab")
        seen.append(page.evaluate("() => document.activeElement.id"))
    assert "tplTemplateChoose" in seen
    if not page.evaluate("() => window.SERVER_MODE"):
        assert seen.index("tplTemplatePath") < seen.index("tplTemplateOpen")
    # the locked cards offer nothing to tab to
    assert page.locator("#tplCard2 button, #tplCard2 input").count() == 0
    assert page.js_errors == []


def test_enter_on_the_choose_button_opens_the_picker_and_headings_take_focus(gui, tpl_file):
    page = gui
    _open_view(page)
    with page.expect_file_chooser() as chooser:
        page.focus("#tplTemplateChoose")
        page.keyboard.press("Enter")
    chooser.value.set_files(str(tpl_file))
    page.wait_for_selector("#tplCard1[data-state=done]", timeout=15_000)
    assert page.evaluate("() => document.activeElement.id") == "tplH2"
    assert page.js_errors == []


def test_no_horizontal_scroll_at_320_px(browser, gui, tpl_file):
    page = gui
    page.set_viewport_size({"width": 320, "height": 700})
    _open_view(page)
    _template_chosen(page, tpl_file)
    assert page.evaluate("() => document.documentElement.scrollWidth <= document.documentElement.clientWidth")
    assert page.js_errors == []
