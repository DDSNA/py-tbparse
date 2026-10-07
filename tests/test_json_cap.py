"""Every JSON POST route is size-checked the same way (#123): too big is 413, a bad Content-Length is 400."""

from __future__ import annotations

import http.client
import json
import threading
from http.server import ThreadingHTTPServer

import pytest

from py_tbparse import webgui


@pytest.fixture
def addr():
    webgui._STATE.update(parser=None, path=None, uploaded=False)
    srv = ThreadingHTTPServer(("127.0.0.1", 0), webgui.Handler)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    try:
        yield srv.server_address
    finally:
        srv.shutdown()
        thread.join(timeout=2)


def _post(addr, route, body: bytes, length=None):
    conn = http.client.HTTPConnection(*addr, timeout=10)
    conn.putrequest("POST", route)
    conn.putheader("Content-Type", "application/json")
    conn.putheader("Content-Length", str(len(body) if length is None else length))
    conn.endheaders()
    conn.send(body)
    r = conn.getresponse()
    raw = r.read()
    conn.close()
    return r.status, json.loads(raw)


def test_download_workbook_over_the_cap_is_413(addr):
    body = json.dumps({"pad": "a" * (webgui.MAX_JSON_BYTES + 10)}).encode()
    status, data = _post(addr, "/download-workbook", body)
    assert status == 413 and "too big" in data["error"]


@pytest.mark.parametrize("route", sorted(webgui._JSON_ROUTES))
def test_every_json_route_has_the_cap(addr, route, monkeypatch):
    monkeypatch.setattr(webgui, "MAX_JSON_BYTES", 1024)
    status, data = _post(addr, route, json.dumps({"pad": "a" * 4096}).encode())
    assert status == 413, route


@pytest.mark.parametrize("route", ["/download-workbook", "/create-workbook", "/template/plan", "/copy/plan"])
@pytest.mark.parametrize("length", ["-5", "abc"])
def test_a_bad_content_length_is_400(addr, route, length):
    status, data = _post(addr, route, b"{}", length=length)
    assert status == 400 and "Content-Length" in data["error"]


def test_a_normal_body_still_works(addr):
    status, data = _post(addr, "/download-workbook", b"{}")
    assert status == 400 and data["error"] == "No workbook loaded"
