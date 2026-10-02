"""Opening a workbook in the page: file picker, drag and drop, recent files, error wording."""

from __future__ import annotations

import base64
import json
from pathlib import Path

import pytest

from py_tbparse import webgui
from test_gui_browser import _load, _open, _wait_meta  # noqa: F401  (helpers shared with the other GUI tests)

DROP = """([b64, name, type]) => {
  const bytes = Uint8Array.from(atob(b64), (c) => c.charCodeAt(0));
  const dt = new DataTransfer();
  dt.items.add(new File([bytes], name, {type: 'application/octet-stream'}));
  const fire = (kind) => window.dispatchEvent(new DragEvent(kind, {dataTransfer: dt, bubbles: true, cancelable: true}));
  if (type === 'enter') { fire('dragenter'); return; }
  if (type === 'enter-leave') { fire('dragenter'); fire('dragleave'); return; }
  fire('dragenter'); fire('dragover'); fire('drop');
}"""


def _b64(path) -> str:
    return base64.b64encode(Path(path).read_bytes()).decode()


def _opened(page, timeout=15_000):
    page.wait_for_function(
        "() => document.getElementById('status').textContent.startsWith('Opened')", timeout=timeout
    )


def test_the_file_picker_opens_a_workbook(page, wenjie_path):
    page.set_input_files("#filePick", wenjie_path)
    _opened(page)
    assert page.inner_text("#wbName") == "test_for_wenjie.twb"
    assert page.input_value("#path") == "", "an uploaded file has no path to show"
    assert page.title().startswith("test_for_wenjie.twb")
    _open(page, "fields")
    _wait_meta(page, "55 row(s)")
    assert page.js_errors == []


def test_a_zipped_workbook_opens_too(page, zip_twbx_path):
    page.set_input_files("#filePick", zip_twbx_path)
    _opened(page)
    assert page.inner_text("#wbName") == "test_for_zip.twbx"
    assert page.js_errors == []


def test_dropping_a_file_opens_it_and_the_overlay_goes_away(page, wenjie_path):
    page.evaluate(DROP, [_b64(wenjie_path), "dropped.twb", "drop"])
    _opened(page)
    assert page.inner_text("#wbName") == "dropped.twb"
    assert page.locator("#dropzone").is_hidden()
    assert page.js_errors == []


def test_the_overlay_shows_only_while_a_file_is_dragged_over(page, wenjie_path):
    assert page.locator("#dropzone").is_hidden()
    page.evaluate(DROP, [_b64(wenjie_path), "x.twb", "enter"])
    assert page.locator("#dropzone").is_visible()
    assert page.get_attribute("#dropzone", "aria-hidden") == "true"
    page.evaluate(DROP, [_b64(wenjie_path), "x.twb", "enter-leave"])
    # one enter from the first call, one enter and one leave from this one: still over the page
    assert page.locator("#dropzone").is_visible()
    page.evaluate(
        "() => { const dt = new DataTransfer(); dt.items.add(new File(['x'], 'x.twb'));"
        " window.dispatchEvent(new DragEvent('dragleave', {dataTransfer: dt})); }"
    )
    assert page.locator("#dropzone").is_hidden()


def test_dragging_plain_text_does_not_show_the_overlay(page):
    page.evaluate(
        "() => { const dt = new DataTransfer(); dt.setData('text/plain', 'hello');"
        " window.dispatchEvent(new DragEvent('dragenter', {dataTransfer: dt, cancelable: true})); }"
    )
    assert page.locator("#dropzone").is_hidden()


def test_a_dropped_file_that_is_not_a_workbook_gets_a_plain_message(page, tmp_path):
    bad = tmp_path / "notes.txt"
    bad.write_text("hello")
    page.evaluate(DROP, [_b64(bad), "notes.txt", "drop"])
    page.wait_for_function("() => document.getElementById('status').classList.contains('err')")
    assert "only .twb and .twbx" in page.inner_text("#status")
    assert page.locator("#controls").is_hidden()


def test_a_broken_workbook_is_refused_and_the_page_stays_usable(page, wenjie_path, tmp_path):
    page.evaluate(DROP, [base64.b64encode(b"not xml at all").decode(), "broken.twb", "drop"])
    page.wait_for_function("() => document.getElementById('status').classList.contains('err')")
    assert "That didn’t work" in page.inner_text("#status")
    _load(page, wenjie_path)                      # and opening a real one still works
    assert page.inner_text("#wbName") == "test_for_wenjie.twb"


def test_an_uploaded_workbook_offers_download_not_save_beside(page, wenjie_path):
    page.set_input_files("#filePick", wenjie_path)
    _opened(page)
    _open(page, "field-renames")
    assert page.locator("#createBtn").is_hidden()
    assert page.locator("#uploadNote").is_visible()
    assert page.locator("#downloadBtn").is_visible()
    page.set_input_files("#filePick", wenjie_path)   # opening by path again restores the button
    _opened(page)
    page.fill("#path", wenjie_path)
    page.click("#loadBtn")
    page.wait_for_function("() => !document.getElementById('createBtn').hidden")
    assert page.locator("#uploadNote").is_hidden()


def test_recent_files_are_remembered_opened_and_forgotten(page, gui_server, wenjie_path, zip_twbx_path):
    assert page.locator("#recent").is_hidden()
    _load(page, wenjie_path)
    _load(page, zip_twbx_path)
    stored = json.loads(page.evaluate("() => localStorage.getItem('py-tbparse:recent')"))
    assert stored == [zip_twbx_path, wenjie_path], "newest first, no duplicates"
    webgui._STATE["path"] = None             # a fresh start, as when the server was started without a workbook
    page.reload()
    assert page.locator("#recent").is_visible()
    names = page.locator("#recentList .open-recent").evaluate_all("els => els.map(e => e.childNodes[0].textContent)")
    assert names == ["test_for_zip.twbx", "test_for_wenjie.twb"]
    page.locator("#recentList .open-recent").nth(1).click()
    _opened(page)
    assert page.inner_text("#wbName") == "test_for_wenjie.twb"
    webgui._STATE["path"] = None
    page.reload()
    page.click('#recentList .forget >> nth=0')
    assert json.loads(page.evaluate("() => localStorage.getItem('py-tbparse:recent')")) == [zip_twbx_path]
    assert page.js_errors == []


def test_uploads_never_enter_the_recent_list(page, wenjie_path):
    page.set_input_files("#filePick", wenjie_path)
    _opened(page)
    assert page.evaluate("() => localStorage.getItem('py-tbparse:recent')") in (None, "[]")


def test_a_corrupt_recent_list_is_ignored(page, wenjie_path):
    page.evaluate("() => localStorage.setItem('py-tbparse:recent', '{not json')")
    webgui._STATE["path"] = None
    page.reload()
    assert page.locator("#recent").is_hidden()
    _load(page, wenjie_path)
    assert page.js_errors == []


def test_a_missing_path_suggests_dropping_the_file(page):
    page.fill("#path", "/no/such/workbook.twb")
    page.click("#loadBtn")
    page.wait_for_function("() => document.getElementById('status').classList.contains('err')")
    assert "drop the file" in page.inner_text("#status")


def test_the_open_controls_work_from_the_keyboard(page):
    pick = page.locator("#pickBtn")
    pick.focus()
    with page.expect_file_chooser() as chooser:
        page.keyboard.press("Enter")
    assert chooser.value is not None
    assert page.get_attribute("#filePick", "aria-hidden") == "true"
    assert page.get_attribute("#filePick", "tabindex") == "-1"
