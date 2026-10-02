"""The page in server mode, in real Chromium: no path box, uploads work, each browser has its own workbook."""

from __future__ import annotations

import threading
from http.server import ThreadingHTTPServer

import pytest

from conftest import new_page
from py_tbparse import webgui


@pytest.fixture
def server_url():
    saved = dict(webgui._CONFIG)
    webgui._STATE.base.update(parser=None, path=None, uploaded=False, report=None)
    webgui._CONFIG.update(server_mode=True)
    webgui._SESSIONS.clear()
    srv = ThreadingHTTPServer(("127.0.0.1", 0), webgui.Handler)
    host, port = srv.server_address
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://{host}:{port}"
    finally:
        srv.shutdown()
        thread.join(timeout=2)
        webgui._clear_all_uploads()
        webgui._CONFIG.clear()
        webgui._CONFIG.update(saved)


def _opened(page):
    page.wait_for_function(
        "() => document.getElementById('status').textContent.startsWith('Opened')", timeout=10_000
    )


def test_path_controls_are_hidden_and_the_page_is_clean(browser, server_url):
    page = new_page(browser, server_url)
    try:
        assert page.is_hidden("#path") and page.is_hidden("#loadBtn")
        assert page.is_visible("#pickBtn")
        assert page.js_errors == []
    finally:
        page.ctx.close()


def test_upload_works_and_stays_private_to_its_browser(browser, server_url, wenjie_path):
    first = new_page(browser, server_url)
    second = new_page(browser, server_url)
    try:
        first.set_input_files("#filePick", wenjie_path)
        _opened(first)
        assert first.js_errors == []
        # the second browser has its own cookie, so it still sees the start screen with nothing loaded
        status = second.evaluate("fetch('/table?name=datasources').then(r => r.status)")
        assert status == 400
        assert first.evaluate("fetch('/table?name=datasources').then(r => r.status)") == 200
    finally:
        first.ctx.close()
        second.ctx.close()
