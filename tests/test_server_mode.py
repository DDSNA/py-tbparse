"""Server mode: one private session per browser, host/origin handling behind a TLS proxy, no server paths."""

from __future__ import annotations

import http.client
import json
import threading
import time
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.parse import quote

import pytest

from py_tbparse import webgui

PUBLIC = "tbparse.example.com"


@pytest.fixture
def server(wenjie_path):
    saved = dict(webgui._CONFIG)
    webgui._STATE.base.update(parser=None, path=None, uploaded=False, report=None)
    webgui._CONFIG.update(
        server_mode=True, allowed_hosts=frozenset({PUBLIC}), trust_proxy=True, max_sessions=3, session_ttl=3600
    )
    webgui._SESSIONS.clear()
    srv = ThreadingHTTPServer(("127.0.0.1", 0), webgui.Handler)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    try:
        yield srv.server_address
    finally:
        srv.shutdown()
        thread.join(timeout=2)
        webgui._clear_all_uploads()
        webgui._CONFIG.clear()
        webgui._CONFIG.update(saved)


def _request(addr, method, path, body=None, headers=None, host=PUBLIC):
    conn = http.client.HTTPConnection(*addr, timeout=10)
    hdrs = {"Host": host}
    hdrs.update(headers or {})
    conn.request(method, path, body=body, headers=hdrs)
    r = conn.getresponse()
    raw = r.read()
    cookie = r.getheader("Set-Cookie")
    conn.close()
    return r.status, raw, cookie


def _sid(cookie):
    return cookie.split(";")[0]


def _upload(addr, path, cookie=None, origin=f"https://{PUBLIC}", host=PUBLIC):
    path = Path(path)
    body = path.read_bytes()
    hdrs = {
        "Content-Type": "application/octet-stream",
        "X-Filename": quote(path.name),
        "Content-Length": str(len(body)),
        "Origin": origin,
    }
    if cookie:
        hdrs["Cookie"] = cookie
    return _request(addr, "POST", "/upload", body=body, headers=hdrs, host=host)


def test_healthz_needs_no_host_and_makes_no_session(server):
    status, raw, cookie = _request(server, "GET", "/healthz", host="anything.invalid")
    assert (status, raw, cookie) == (200, b"ok", None)
    assert webgui._SESSIONS == {}


def test_allowed_host_is_accepted_on_any_port_and_others_refused(server):
    assert _request(server, "GET", "/", host=PUBLIC)[0] == 200
    assert _request(server, "GET", "/", host=f"{PUBLIC}:8443")[0] == 200
    assert _request(server, "GET", "/", host="evil.example.com")[0] == 403


def test_page_sets_a_hardened_session_cookie(server):
    status, _, cookie = _request(server, "GET", "/")
    assert status == 200
    assert "HttpOnly" in cookie and "SameSite=Strict" in cookie and "Path=/" in cookie
    assert "Secure" not in cookie
    _, _, secure = _request(server, "GET", "/", headers={"X-Forwarded-Proto": "https"})
    assert "Secure" in secure


def test_static_files_and_foreign_hosts_do_not_create_sessions(server):
    _request(server, "GET", "/static/app.js")
    _request(server, "GET", "/", host="evil.example.com")
    assert webgui._SESSIONS == {}


def test_upload_over_https_origin_works_behind_a_proxy(server, wenjie_path):
    status, raw, cookie = _upload(server, wenjie_path)
    assert status == 200 and json.loads(raw)["ok"]
    assert cookie


def test_https_origin_is_refused_without_trust_proxy(server, wenjie_path):
    webgui._CONFIG["trust_proxy"] = False
    status, raw, _ = _upload(server, wenjie_path)
    assert status == 403 and "cross-origin" in json.loads(raw)["error"]


def test_foreign_origin_is_refused(server, wenjie_path):
    status, _, _ = _upload(server, wenjie_path, origin="https://evil.example.com")
    assert status == 403


def test_sessions_are_isolated(server, wenjie_path):
    _, _, cookie_a = _upload(server, wenjie_path)
    a = _sid(cookie_a)
    status, raw, _ = _request(server, "GET", "/tables", headers={"Cookie": a})
    assert status == 200
    status, raw, _ = _request(server, "GET", "/table?name=datasources", headers={"Cookie": a})
    assert status == 200 and json.loads(raw)["rows"] > 0

    _, _, cookie_b = _request(server, "GET", "/")
    b = _sid(cookie_b)
    status, raw, _ = _request(server, "GET", "/table?name=datasources", headers={"Cookie": b})
    assert status == 400 and "No workbook" in json.loads(raw)["error"]

    # B uploading does not replace A's workbook or temp dir
    _upload(server, wenjie_path, cookie=b)
    dirs = {s["upload"]["dir"] for s in webgui._SESSIONS.values()}
    assert len(dirs) == 2 and None not in dirs


def test_no_cookie_means_no_workbook(server, wenjie_path):
    _upload(server, wenjie_path)
    status, _, _ = _request(server, "GET", "/table?name=datasources")
    assert status == 400


def test_oldest_session_is_evicted_and_its_upload_deleted(server, wenjie_path):
    import os

    _, _, first = _upload(server, wenjie_path)
    first_dir = next(iter(webgui._SESSIONS.values()))["upload"]["dir"]
    assert os.path.isdir(first_dir)
    for _ in range(3):
        time.sleep(0.01)
        _upload(server, wenjie_path)
    assert len(webgui._SESSIONS) == 3
    assert _sid(first).split("=")[1] not in webgui._SESSIONS
    assert not os.path.exists(first_dir)


def test_expired_sessions_are_dropped(server, wenjie_path):
    import os

    _upload(server, wenjie_path)
    folder = next(iter(webgui._SESSIONS.values()))["upload"]["dir"]
    webgui._CONFIG["session_ttl"] = 0.01
    time.sleep(0.05)
    _request(server, "GET", "/")
    assert len(webgui._SESSIONS) == 1  # only the new one
    assert not os.path.exists(folder)


def test_server_paths_are_not_openable(server, wenjie_path):
    for route, body in (("/load", {"path": str(wenjie_path)}), ("/create-workbook", {})):
        status, raw, _ = _request(
            server, "POST", route, body=json.dumps(body),
            headers={"Content-Type": "application/json", "Origin": f"https://{PUBLIC}"},
        )
        assert status == 403 and "server" in json.loads(raw)["error"]


def test_page_flags_server_mode_and_hides_any_preload(server):
    _, raw, _ = _request(server, "GET", "/")
    html = raw.decode()
    assert "window.SERVER_MODE = true;" in html and "window.PRELOAD_PATH = null;" in html


def test_local_mode_is_unchanged(wenjie_path):
    assert webgui._CONFIG["server_mode"] is False
    assert webgui._origin_ok("https://tbparse.example.com", "tbparse.example.com") is False
    assert webgui._origin_ok(None, "x") is True


def test_cli_options_and_env(monkeypatch):
    monkeypatch.setenv("PY_TBPARSE_ALLOWED_HOSTS", "a.example, b.example")
    monkeypatch.setenv("PY_TBPARSE_SERVER_MODE", "1")
    args = webgui.build_arg_parser().parse_args(["--allowed-host", "c.example", "--trust-proxy"])
    assert args.server_mode and args.trust_proxy
    assert args.allowed_host == ["a.example", "b.example", "c.example"]
