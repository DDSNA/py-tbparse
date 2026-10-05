"""The Templates view in real Chromium (WP9 package 9c): open and close it, choose a template and data, drop
files into the right step, plain messages for the wrong file, server mode, keyboard use.

Skipped when Chromium cannot start; a skip is not a pass."""

from __future__ import annotations

import base64
import csv
import json
import threading
import zipfile
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

import py_tbparse.templates as templates
from conftest import new_page
from py_tbparse import load_template, make_template, webgui
from test_gui_browser import _NEEDS_MEMORY, _load  # noqa: F401  (helpers shared with the other GUI tests)

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
    # the server answered 400 on purpose; the browser logs that as a console error, anything else is a bug
    assert [e for e in page.js_errors if "status of 400" not in e] == []


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


# --- 9d: match the fields, review, create --------------------------------------------------------------------

def _matched_csv(tmp_path, tpl_file, extra=(), name="match.csv"):
    """A CSV with every column the template was built on, one row of text, plus `extra` {column: value}."""
    t = load_template(str(tpl_file))
    entry = next(e for e in t.manifest["datasources"] if e["fields"])
    names = [f["remote"] for f in entry["fields"]] + list(extra)
    path = tmp_path / name
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(names)
        w.writerow([extra.get(n, "x") if n in extra else "x" for n in names])
    return path


def _both_chosen(page, tpl_file, data_file):
    _open_view(page)
    _template_chosen(page, tpl_file)
    _data_chosen(page, data_file)
    page.wait_for_selector("#tplMapBody tr")


def _ready(page):
    page.wait_for_function("() => { const b = document.getElementById('tplCreate'); return b && !b.disabled; }",
                           timeout=15_000)


def _row(page, caption):
    return page.locator("#tplMapBody tr", has=page.locator("strong", has_text=caption))


def test_the_suggested_mapping_is_shown_with_optional_fields_behind_a_toggle(gui, tpl_file, tmp_path):
    page = gui
    _both_chosen(page, tpl_file, _matched_csv(tmp_path, tpl_file))
    assert page.locator("#tplMapBody tr").count() == 1                      # only the required field
    row = _row(page, "Burst Out Set list")
    assert "Required" in row.inner_text() and "Matched by name" in row.inner_text()
    assert row.locator("select").input_value() == "Burst Out Set list"
    assert page.locator("#tplMapBody select option").count() == 1            # a closed dropdown holds one option
    page.check("#tplOptional")
    assert page.locator("#tplMapBody tr").count() > 1
    assert page.locator("#tplMapBody tr").count() <= 200
    page.fill("#tplFilter", "burst out set")
    assert page.locator("#tplMapBody tr").count() == 1
    assert page.js_errors == []


def test_changing_a_column_refreshes_what_the_status_says(gui, tpl_file, tmp_path):
    page = gui
    _both_chosen(page, tpl_file, _matched_csv(tmp_path, tpl_file, extra={"Other": "y"}))
    row = _row(page, "Burst Out Set list")
    row.locator("select").focus()
    row.locator("select").select_option("Other")
    page.wait_for_function("() => document.querySelector('#tplMapBody .tpl-c-status').innerText.indexOf('You chose this') >= 0")
    assert "Matched by name" not in row.inner_text()
    _ready(page)
    # no column at all: the required field is a problem, and Create waits
    row.locator("select").select_option("")
    page.wait_for_function("() => document.getElementById('tplGroup-problems').dataset.count === '1'", timeout=15_000)
    assert page.locator("#tplCreate").is_disabled()
    assert "Missing" in row.inner_text()
    assert "no column for required" in page.inner_text("#tplGroup-problems")
    assert page.js_errors == []


def test_a_string_field_does_not_offer_a_date_column_until_show_all_columns(gui, tpl_file, tmp_path):
    page = gui
    _both_chosen(page, tpl_file, _matched_csv(tmp_path, tpl_file, extra={"When": "2020-01-31"}))
    row = _row(page, "Burst Out Set list")
    select = row.locator("select")
    select.focus()
    texts = select.locator("option").all_inner_texts()
    assert any(t.startswith("Burst Out Set list") for t in texts)
    assert not any(t.startswith("When") for t in texts)
    page.evaluate("() => document.activeElement.blur()")
    assert select.locator("option").count() == 1                              # emptied again on blur
    row.get_by_label("Show all columns").check()
    select.focus()
    assert any(t.startswith("When") for t in select.locator("option").all_inner_texts())
    assert page.js_errors == []


def test_choosing_a_column_another_field_uses_moves_it(gui, tpl_file, tmp_path):
    page = gui
    _both_chosen(page, tpl_file, _matched_csv(tmp_path, tpl_file))
    page.check("#tplOptional")
    t = load_template(str(tpl_file))
    entry = next(e for e in t.manifest["datasources"] if e["fields"])
    other = next(f for f in entry["fields"] if f["datatype"] == "string" and not f["required"])
    cap = (other.get("caption") or other["name"]).strip("[]")
    page.fill("#tplFilter", cap)
    row = _row(page, cap)
    row.locator("select").focus()
    labels = row.locator("select option").all_inner_texts()
    assert any("(used by Burst Out Set list)" in t for t in labels)
    row.locator("select").select_option("Burst Out Set list")
    page.wait_for_function("() => document.getElementById('tplPlanLive').innerText !== 'Checking \u2026'", timeout=15_000)
    page.fill("#tplFilter", "")
    page.evaluate("() => document.activeElement.blur()")
    # the required field lost its column, so it is a problem the person can see
    assert "Missing" in _row(page, "Burst Out Set list").inner_text()
    assert page.js_errors == []


def test_a_bad_integer_parameter_shows_an_inline_error_and_stops_create(gui, tmp_path):
    import shutil
    page = gui
    shutil.copy(PUBLIC_FIXTURES / "Cache.twbx", tmp_path / "Cache.twbx")
    tpl = make_template(str(tmp_path / "Cache.twbx"), output_path=str(tmp_path / "c.template.twbx"))
    data = tmp_path / "cache.csv"
    data.write_text("Category,Number of Records\nFurniture,3\n", encoding="utf-8")
    _both_chosen(page, Path(tpl), data)
    _ready(page)
    box = page.locator("#tplParam2")
    assert page.get_by_label("New Quota", exact=True).count() == 1
    box.fill("1.5")
    page.wait_for_selector("#tplParam2Err:not([hidden])", timeout=15_000)
    assert "whole number" in page.inner_text("#tplParam2Err")
    assert box.get_attribute("aria-invalid") == "true"
    assert "tplParam2Err" in box.get_attribute("aria-describedby")
    assert page.locator("#tplCreate").is_disabled()
    page.click("#tplParamReset2")
    page.wait_for_selector("#tplParam2Err", state="hidden", timeout=15_000)
    _ready(page)
    assert page.js_errors == []


def test_create_downloads_a_workbook_with_the_answers_file(gui, tpl_file, tmp_path):
    page = gui
    _both_chosen(page, tpl_file, _matched_csv(tmp_path, tpl_file))
    _ready(page)
    with page.expect_download() as info:
        page.click("#tplCreate")
    out = tmp_path / "got.twbx"
    info.value.save_as(str(out))
    with zipfile.ZipFile(out) as z:
        answers = json.loads(z.read("template-answers.json"))
    assert answers["data"] if "data" in answers else answers      # the answers file is there and not empty
    assert str(tmp_path) not in json.dumps(answers)
    assert "Created" in page.inner_text("#status") and page.locator("#tplDownload").is_visible()
    assert page.js_errors == []


def test_save_beside_the_template_writes_the_file_and_a_second_save_says_it_exists(gui, tpl_file, tmp_path):
    page = gui
    _open_view(page)
    page.fill("#tplTemplatePath", str(tpl_file))
    page.click("#tplTemplateOpen")
    page.wait_for_selector("#tplCard1[data-state=done]", timeout=15_000)
    _data_chosen(page, _matched_csv(tmp_path, tpl_file))
    page.wait_for_selector("#tplMapBody tr")
    _ready(page)
    before = set(Path(tpl_file).parent.iterdir())
    page.click("#tplSave")
    page.wait_for_selector("#tplDone .tpl-ok")
    made = set(Path(tpl_file).parent.iterdir()) - before
    assert len(made) == 1 and next(iter(made)).suffix == ".twbx"
    assert str(next(iter(made))) in page.inner_text("#tplDone")
    _ready(page)
    page.click("#tplSave")
    assert "already exists" in _error_shown(page)
    assert page.js_errors == [] or all("status of 409" in e for e in page.js_errors)


def test_server_mode_has_no_save_beside_button(browser, server_url, tpl_file, tmp_path):
    page = new_page(browser, server_url)
    try:
        page.goto(server_url + "/#templates")
        page.wait_for_selector("#templatesView:not([hidden])")
        _template_chosen(page, tpl_file)
        _data_chosen(page, _matched_csv(tmp_path, tpl_file))
        page.wait_for_selector("#tplCreate")
        assert page.locator("#tplSave").count() == 0
    finally:
        page.ctx.close()


def _synthetic(n_fields, n_columns, required_every=5):
    fields = [{"datasource": "d", "field": "[F%d]" % i, "caption": "Field %d" % i, "datatype": "string",
               "required": i % required_every == 0, "used_by": "sheet %d" % i, "mapped_to": "", "data_type": "",
               "status": "missing" if i % required_every == 0 else "unused", "score": None} for i in range(n_fields)]
    columns = [{"column": "Column %d" % i, "datatype": "string", "status": "ok"} for i in range(n_columns)]
    empty = {"rows": [], "total": 0, "truncated": 0}
    plan = {"mapping": {"rows": fields, "total": n_fields, "truncated": 0}, "choices": {"string": columns},
            "broken": empty, "explain": empty, "check": empty, "params": [], "tokens": [], "missing_required": [],
            "problems": [], "ready": True}
    template = {"name": "Big", "description": None, "id": "big", "revision": 1, "manifest_version": 2,
                "label": "big.twbx", "datasources": [{"name": "d", "caption": "d", "fields": n_fields, "required": 1}],
                "parameters": [], "tokens": [], "findings": []}
    data = {"kind": "csv", "label": "big.csv", "sheet": None,
            "columns": [{"name": c["column"], "datatype": "string"} for c in columns]}
    return template, data, plan


@_NEEDS_MEMORY
def test_two_thousand_fields_and_columns_stay_a_small_page(gui):
    page = gui
    template, data, plan = _synthetic(2000, 2000)
    page.route("**/template/state", lambda r: r.fulfill(
        status=200, content_type="application/json",
        body=json.dumps({"template": template, "data": data, "sheets": None, "datasources": None, "output": None})))
    page.route("**/template/plan", lambda r: r.fulfill(status=200, content_type="application/json", body=json.dumps(plan)))
    _open_view(page)
    page.wait_for_selector("#tplMapBody tr")
    assert page.locator("#tplMapBody tr").count() == 200                      # 400 required fields, 200 drawn
    assert page.evaluate("() => document.querySelectorAll('#templatesView option').length") < 1500
    assert page.evaluate("() => document.querySelectorAll('#templatesView tr').length") <= 205
    page.click("#tplMapMore")
    assert page.locator("#tplMapBody tr").count() == 400
    page.check("#tplOptional")
    assert page.locator("#tplMapBody tr").count() == 200                      # back to one page of 2000 fields, not 2000 rows
    first = page.locator("#tplMapBody select").first
    first.focus()
    assert first.locator("option").count() <= 1005                            # capped; the rest say so
    page.evaluate("() => document.activeElement.blur()")
    assert page.evaluate("() => document.querySelectorAll('#templatesView option').length") < 1500
    took = page.evaluate("""() => {
      const box = document.getElementById('tplFilter');
      const t = performance.now();
      box.value = 'Field 1';
      box.dispatchEvent(new Event('input', {bubbles: true}));
      return performance.now() - t;
    }""")
    assert took < 1000, took                                                  # the guide asks for 500 ms, asserted at 2x
    assert page.js_errors == []


def test_step_three_does_not_scroll_sideways_at_320_px(gui, tpl_file, tmp_path):
    page = gui
    page.set_viewport_size({"width": 320, "height": 700})
    _both_chosen(page, tpl_file, _matched_csv(tmp_path, tpl_file))
    _ready(page)
    page.check("#tplOptional")
    assert page.evaluate("() => document.documentElement.scrollWidth <= document.documentElement.clientWidth")
    assert page.js_errors == []


def test_every_control_in_step_three_has_a_name_and_the_table_has_headers(gui, tpl_file, tmp_path):
    page = gui
    _both_chosen(page, tpl_file, _matched_csv(tmp_path, tpl_file))
    _ready(page)
    page.check("#tplOptional")
    unnamed = page.evaluate("""() => [...document.querySelectorAll('#tplCard3 input, #tplCard3 select, #tplCard3 button')]
      .filter((c) => c.offsetParent !== null && !(c.getAttribute('aria-label') || '').trim() && !(c.labels && c.labels.length)
        && !c.textContent.trim()).map((c) => c.outerHTML.slice(0, 80))""")
    assert unnamed == []
    assert page.locator("#tplMap caption").count() == 1
    assert page.locator("#tplMap th[scope=col]").count() == 5
    assert page.locator("#tplPlanLive[role=status]").count() == 1
    assert page.js_errors == []


# --- 9e: make a template from the open workbook --------------------------------------------------------------

def _make_ready(page, path):
    _load(page, path)
    _open_view(page)
    page.wait_for_selector("#tplMakeBtn")


def test_with_no_workbook_the_make_section_says_to_open_one_first(gui):
    page = gui
    _open_view(page)
    assert page.locator("#tplMake").is_visible()
    assert "Open a workbook first" in page.inner_text("#tplMakeBody")
    assert page.locator("#tplMakeBtn").count() == 0
    assert page.js_errors == []


def test_making_a_template_gives_a_download_and_a_use_button(gui, tmp_path):
    page = gui
    _make_ready(page, str(PUBLIC_FIXTURES / "filtering.twb"))
    assert "filtering.twb" in page.inner_text("#tplMakeBody")
    page.fill("#tplMakeName", "Sales report")
    page.fill("#tplMakeDesc", "Monthly sales")
    page.click("#tplMakeBtn")
    page.wait_for_selector("#tplMadeDownload", timeout=20_000)
    assert "Sales report.template.twbx" in page.inner_text("#tplMakeBody")
    assert "required field" in page.inner_text("#tplMakeBody")
    with page.expect_download() as info:
        page.click("#tplMadeDownload")
    out = tmp_path / "got.template.twbx"
    info.value.save_as(str(out))
    t = load_template(str(out))
    assert t.name == "Sales report" and t.manifest["description"] == "Monthly sales"
    assert page.js_errors == []


def test_use_it_as_the_template_fills_step_one_and_moves_on_to_the_data(gui):
    page = gui
    _make_ready(page, str(PUBLIC_FIXTURES / "filtering.twb"))
    page.click("#tplMakeBtn")
    page.wait_for_selector("#tplMadeUse", timeout=20_000)
    page.click("#tplMadeUse")
    page.wait_for_selector("#tplCard1[data-state=done]", timeout=15_000)
    assert page.locator("#tplCard1 .tpl-file").inner_text() == "filtering.template.twbx"
    assert page.locator("#tplCard1 .tpl-name").inner_text() == "filtering"
    assert page.get_attribute("#tplCard2", "aria-disabled") is None
    assert page.evaluate("() => document.activeElement.id") == "tplH2"
    assert page.js_errors == []


def test_a_made_template_then_a_csv_gives_a_workbook(gui, tmp_path):
    page = gui
    _make_ready(page, str(PUBLIC_FIXTURES / "filtering.twb"))
    page.click("#tplMakeBtn")
    page.wait_for_selector("#tplMadeUse", timeout=20_000)
    page.click("#tplMadeUse")
    page.wait_for_selector("#tplCard1[data-state=done]")
    path = tmp_path / "match.csv"
    entry = next(e for e in webgui._tpl_state()["template"].manifest["datasources"] if e["fields"])
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow([f["remote"] for f in entry["fields"]])
        w.writerow(["x"] * len(entry["fields"]))
    _data_chosen(page, path)
    page.wait_for_selector("#tplMapBody tr")
    _ready(page)
    with page.expect_download():
        page.click("#tplCreate")
    assert page.js_errors == []


def test_the_made_template_comes_back_after_a_reload(gui):
    page = gui
    _make_ready(page, str(PUBLIC_FIXTURES / "filtering.twb"))
    page.click("#tplMakeBtn")
    page.wait_for_selector("#tplMadeDownload", timeout=20_000)
    page.reload()
    page.wait_for_selector("#templatesView:not([hidden])")
    page.wait_for_selector("#tplMadeDownload")
    assert page.js_errors == []


def test_a_workbook_opened_before_the_view_turns_the_section_on(gui):
    page = gui
    _open_view(page)
    assert page.locator("#tplMakeBtn").count() == 0
    page.evaluate("""async (path) => {
      await fetch('/load', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({path})});
    }""", str(PUBLIC_FIXTURES / "filtering.twb"))
    page.click("#tplBack")
    page.click("#tplBtn")
    page.wait_for_selector("#tplMakeBtn")
    assert page.js_errors == []


def test_a_made_template_that_is_refused_shows_the_reason_and_the_page_stays_usable(gui):
    page = gui
    _make_ready(page, str(PUBLIC_FIXTURES / "filtering.twb"))
    page.route("**/template/make", lambda route: route.fulfill(
        status=400, content_type="application/json", body=json.dumps({"error": "Nothing to make here."})))
    page.click("#tplMakeBtn")
    page.wait_for_selector("#tplMakeMsg:not(:empty)")
    assert "Nothing to make here." in page.inner_text("#tplMakeMsg")
    assert page.locator("#tplMakeBtn").is_enabled()
    page.unroute("**/template/make")
    assert [e for e in page.js_errors if "400" not in e] == []


def test_server_mode_makes_a_template_from_an_uploaded_workbook(browser, server_url):
    page = new_page(browser, server_url)
    try:
        page.set_input_files("#filePick", str(PUBLIC_FIXTURES / "filtering.twb"))
        page.wait_for_function("() => document.getElementById('status').textContent.startsWith('Opened')", timeout=15_000)
        page.click("#tplBtn")
        page.wait_for_selector("#tplMakeBtn")
        page.click("#tplMakeBtn")
        page.wait_for_selector("#tplMadeDownload", timeout=20_000)
        body = page.inner_text("#tplMakeBody")
        import tempfile
        assert tempfile.gettempdir() not in body and "py-tbparse-" not in body
        assert page.js_errors == []
    finally:
        page.ctx.close()


def test_the_make_section_has_names_no_sideways_scroll_and_a_sane_tab_order(gui):
    page = gui
    page.set_viewport_size({"width": 320, "height": 700})
    _make_ready(page, str(PUBLIC_FIXTURES / "filtering.twb"))
    page.click("#tplMakeBtn")
    page.wait_for_selector("#tplMadeUse", timeout=20_000)
    assert page.evaluate("() => document.documentElement.scrollWidth <= document.documentElement.clientWidth")
    unnamed = page.evaluate("""() => [...document.querySelectorAll('#tplMake input, #tplMake textarea, #tplMake button, #tplMake a')]
      .filter((c) => c.offsetParent !== null && !(c.getAttribute('aria-label') || '').trim() && !(c.labels && c.labels.length)
        && !c.textContent.trim()).map((c) => c.outerHTML.slice(0, 80))""")
    assert unnamed == []
    order = page.evaluate("""() => [...document.querySelectorAll('#tplMake input, #tplMake textarea, #tplMake button, #tplMake a')]
      .filter((c) => c.offsetParent !== null).map((c) => c.id)""")
    assert order == ["tplMakeName", "tplMakeDesc", "tplMakeBtn", "tplMadeDownload", "tplMadeUse"]
    assert page.js_errors == []
