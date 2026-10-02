"""POST /upload: a workbook arriving as bytes (drag and drop, file picker)."""

from __future__ import annotations

import http.client
import json
import os
import threading
from http.server import ThreadingHTTPServer
from urllib.parse import quote

import pytest

from py_tbparse import webgui


@pytest.fixture
def server():
    webgui._STATE.update(parser=None, path=None, uploaded=False)
    srv = ThreadingHTTPServer(("127.0.0.1", 0), webgui.Handler)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    try:
        yield srv.server_address
    finally:
        srv.shutdown()
        thread.join(timeout=2)
        webgui._clear_upload()


def _upload(addr, body: bytes, name="book.twb", ctype="application/octet-stream", headers=None):
    conn = http.client.HTTPConnection(*addr, timeout=10)
    hdrs = {"Content-Type": ctype, "X-Filename": quote(name), "Content-Length": str(len(body))}
    hdrs.update(headers or {})
    conn.request("POST", "/upload", body=body, headers=hdrs)
    r = conn.getresponse()
    raw = r.read()
    conn.close()
    try:
        return r.status, json.loads(raw)
    except ValueError:
        return r.status, {"error": raw.decode()}


def _get(addr, path):
    conn = http.client.HTTPConnection(*addr, timeout=10)
    conn.request("GET", path)
    r = conn.getresponse()
    body = r.read()
    conn.close()
    return r.status, body


def test_a_twb_upload_opens_the_workbook(server, wenjie_path):
    status, data = _upload(server, open(wenjie_path, "rb").read(), "test_for_wenjie.twb")
    assert status == 200 and data["ok"] and data["uploaded"] is True
    assert data["name"] == "test_for_wenjie.twb"
    assert data["path"] is None, "the temp path is never shown to the page"
    assert data["counts"]["fields"] > 0
    status, body = _get(server, "/table?name=fields")
    assert status == 200 and json.loads(body)["data"]


def test_a_twbx_upload_opens_the_workbook(server, zip_twbx_path):
    status, data = _upload(server, open(zip_twbx_path, "rb").read(), "zipped.twbx")
    assert status == 200 and data["ok"]


def test_a_new_upload_deletes_the_previous_one(server, wenjie_path):
    body = open(wenjie_path, "rb").read()
    _upload(server, body, "a.twb")
    first = webgui._UPLOAD["dir"]
    assert os.path.isdir(first)
    _upload(server, body, "b.twb")
    assert not os.path.exists(first)
    assert os.path.isdir(webgui._UPLOAD["dir"])


def test_a_failed_upload_leaves_no_temp_directory(server):
    status, data = _upload(server, b"<not really a workbook", "bad.twb")
    assert status == 400 and "error" in data
    assert webgui._UPLOAD["dir"] is None


def test_the_content_must_match_the_extension(server, wenjie_path):
    status, data = _upload(server, b"MZ\x90\x00 an executable", "x.twb")
    assert status == 400 and "not a Tableau workbook" in data["error"]
    status, data = _upload(server, open(wenjie_path, "rb").read(), "x.twbx")
    assert status == 400 and "not a packaged workbook" in data["error"]
    status, data = _upload(server, b"PK\x03\x04", "x.exe")
    assert status == 400 and "Only .twb and .twbx" in data["error"]


def test_a_path_in_the_filename_cannot_escape_the_temp_directory(server, wenjie_path):
    status, data = _upload(server, open(wenjie_path, "rb").read(), "../../evil.twb")
    assert status == 200 and data["name"] == "evil.twb"
    assert os.path.dirname(os.path.abspath(webgui._STATE["path"])) == os.path.abspath(webgui._UPLOAD["dir"])
    status, data = _upload(server, open(wenjie_path, "rb").read(), "..\\..\\evil2.twb")
    assert data["name"] == "evil2.twb"


def test_too_big_is_refused_before_reading_the_body(server, monkeypatch):
    monkeypatch.setattr(webgui, "MAX_UPLOAD_BYTES", 100)
    conn = http.client.HTTPConnection(*server, timeout=10)
    conn.putrequest("POST", "/upload")
    for k, v in {"Content-Type": "application/octet-stream", "X-Filename": "big.twb", "Content-Length": "101"}.items():
        conn.putheader(k, v)
    conn.endheaders()                      # no body is ever sent
    r = conn.getresponse()
    assert r.status == 413 and "limit" in json.loads(r.read())["error"]
    conn.close()


def test_wrong_content_type_is_415(server, wenjie_path):
    status, _ = _upload(server, open(wenjie_path, "rb").read(), ctype="text/plain")
    assert status == 415
    status, _ = _upload(server, open(wenjie_path, "rb").read(), ctype="application/json")
    assert status == 415


def test_a_foreign_origin_is_refused(server, wenjie_path):
    status, data = _upload(server, open(wenjie_path, "rb").read(), headers={"Origin": "http://evil.example"})
    assert status == 403 and webgui._UPLOAD["dir"] is None


def test_a_foreign_host_is_refused(server, wenjie_path):
    status, _ = _upload(server, open(wenjie_path, "rb").read(), headers={"Host": "attacker.example:%d" % server[1]})
    assert status == 403


def test_missing_filename_or_empty_body_is_400(server):
    status, _ = _upload(server, b"x", name="")
    assert status == 400
    status, _ = _upload(server, b"", name="a.twb")
    assert status == 400


def test_uploaded_workbooks_cannot_be_saved_beside_the_original(server, wenjie_path):
    _upload(server, open(wenjie_path, "rb").read(), "u.twb")
    conn = http.client.HTTPConnection(*server, timeout=10)
    conn.request("POST", "/create-workbook", body=b"{}", headers={"Content-Type": "application/json"})
    r = conn.getresponse()
    assert r.status == 409 and "Download" in json.loads(r.read())["error"]
    # download still works
    status, body = _get(server, "/download-workbook?style=title")
    assert status == 200 and body[:1] == b"<"


def test_loading_by_path_still_reports_the_path(server, wenjie_path):
    conn = http.client.HTTPConnection(*server, timeout=10)
    conn.request("POST", "/load", body=json.dumps({"path": wenjie_path}), headers={"Content-Type": "application/json"})
    r = conn.getresponse()
    data = json.loads(r.read())
    assert data["path"] == wenjie_path and data["uploaded"] is False


# --- refusals must reach the client even when the body is large (a Windows connection reset ate them in CI) ---

BIG = b"\x00" * (6 * 1024 * 1024)


def test_every_refusal_still_delivers_its_message_with_a_large_body(server):
    cases = [
        ({"ctype": "text/plain"}, 415),
        ({"headers": {"Origin": "http://evil.example"}}, 403),
        ({"headers": {"Host": "attacker.example:%d" % server[1]}}, 403),
        ({"name": "big.exe"}, 400),
        ({"name": "x.twb"}, 400),                          # not XML
    ]
    for kwargs, want in cases:
        status, data = _upload(server, BIG, **kwargs)
        assert status == want and data["error"], (kwargs, status, data)


def test_drain_reads_what_it_refuses_and_gives_up_on_huge_bodies():
    import io

    class Stub:
        close_connection = False

    stub = Stub()
    stub.rfile = io.BytesIO(b"x" * 3_000_000)
    webgui.Handler._drain(stub, 3_000_000)
    assert stub.rfile.read() == b"" and stub.close_connection is False
    huge = Stub()
    huge.rfile = io.BytesIO(b"x" * 10)
    webgui.Handler._drain(huge, webgui.MAX_DRAIN_BYTES + 1)
    assert huge.rfile.read() == b"x" * 10 and huge.close_connection is True, "too big to read: close instead"
    webgui.Handler._drain(Stub(), 0)                       # nothing to drain is not an error
