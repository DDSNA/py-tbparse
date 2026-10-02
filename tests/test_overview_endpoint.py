"""GET /overview: the report card as JSON."""

from __future__ import annotations

import http.client
import json
import threading
from http.server import ThreadingHTTPServer

import pytest

from py_tbparse import webgui


@pytest.fixture
def server():
    webgui._STATE.update(parser=None, path=None, uploaded=False, report=None)
    srv = ThreadingHTTPServer(("127.0.0.1", 0), webgui.Handler)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    try:
        yield srv.server_address
    finally:
        srv.shutdown()
        thread.join(timeout=2)


def _get(addr, path):
    conn = http.client.HTTPConnection(*addr, timeout=10)
    conn.request("GET", path)
    r = conn.getresponse()
    body = json.loads(r.read())
    conn.close()
    return r.status, body


def _load(addr, path):
    conn = http.client.HTTPConnection(*addr, timeout=10)
    conn.request("POST", "/load", body=json.dumps({"path": path}), headers={"Content-Type": "application/json"})
    r = conn.getresponse()
    r.read()
    conn.close()
    return r.status


def test_overview_needs_a_workbook(server):
    status, body = _get(server, "/overview")
    assert status == 400 and "No workbook" in body["error"]


def test_overview_returns_the_report(server, wenjie_path):
    assert _load(server, wenjie_path) == 200
    status, body = _get(server, "/overview")
    assert status == 200
    assert set(body) == {"summary", "counts", "worksheets", "dashboards", "health"}
    assert body["summary"].startswith("test_for_wenjie.twb has ")


def test_the_report_is_cached_until_the_next_workbook(server, wenjie_path, zip_twbx_path):
    _load(server, wenjie_path)
    _get(server, "/overview")
    first = webgui._STATE["report"]
    assert first is not None
    _get(server, "/overview")
    assert webgui._STATE["report"] is first
    _load(server, zip_twbx_path)
    assert webgui._STATE["report"] is None
    status, body = _get(server, "/overview")
    assert status == 200 and body["summary"].startswith("test_for_zip.twbx has ")


def test_opening_a_workbook_does_not_build_the_report(server, wenjie_path):
    _load(server, wenjie_path)
    assert webgui._STATE["report"] is None


def test_a_foreign_host_cannot_read_the_report(server, wenjie_path):
    _load(server, wenjie_path)
    conn = http.client.HTTPConnection(*server, timeout=10)
    conn.request("GET", "/overview", headers={"Host": "attacker.example:%d" % server[1]})
    assert conn.getresponse().status == 403
