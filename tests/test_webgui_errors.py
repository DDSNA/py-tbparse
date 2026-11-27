"""GUI errors: one status table (`http_status_for`), one place that turns an exception into an answer, and no
server path or traceback in any answer, in local mode and in server mode."""

from __future__ import annotations

import errno
import http.client
import json
import sys
import threading
import zipfile
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.parse import quote

import pytest

sys.path.insert(0, str(Path(__file__).parent))

from py_tbparse import webgui  # noqa: E402
from py_tbparse.errors import (  # noqa: E402
    InputError, IntegrityError, OutputRefusedError, RefusedError, UsageError, http_status_for)
from py_tbparse.library import LibraryClashError, LibraryError, LibraryUsageError  # noqa: E402
from py_tbparse.sheetcopy import SheetCopyRefused  # noqa: E402
from py_tbparse.slicer import SliceIntegrityError  # noqa: E402
from py_tbparse.style import StyleClashError  # noqa: E402
from py_tbparse.templates import TemplateError  # noqa: E402

JSON_H = {"Content-Type": "application/json"}
PUBLIC = "tbparse.example.com"


# ---- the table ----

@pytest.mark.parametrize("exc, status", [
    (UsageError("x"), 400),
    (LibraryUsageError("x"), 400),
    (InputError("x"), 400),
    (LibraryError("x"), 400),
    (TemplateError("x"), 400),
    (RefusedError("x"), 409),
    (OutputRefusedError("x"), 409),
    (LibraryClashError("x"), 409),
    (StyleClashError("x"), 409),
    (SheetCopyRefused("x"), 409),
    (IntegrityError("x"), 422),
    (SliceIntegrityError("x"), 422),
    (FileNotFoundError("x"), 400),
    (zipfile.BadZipFile("x"), 400),
    (OSError(errno.ENOSPC, "disk full"), 500),
    (ValueError("a programmer error"), 500),
    (KeyError("x"), 500),
    (RuntimeError("x"), 500),
])
def test_http_status_table(exc, status):
    assert http_status_for(exc) == status


def test_the_user_facing_value_errors_are_gone():
    import ast
    tree = ast.parse(Path(webgui.__file__).read_text(encoding="utf-8"))
    raised = [n.lineno for n in ast.walk(tree) if isinstance(n, ast.Raise) and isinstance(n.exc, ast.Call)
              and getattr(n.exc.func, "id", None) == "ValueError"]
    assert raised == []


# ---- a running server, local mode or server mode ----

def _start(server_mode: bool):
    saved = dict(webgui._CONFIG)
    webgui._STATE.base.update(parser=None, path=None, uploaded=False, report=None, audit=None, lib=None, sty=None)
    webgui._CONFIG.update(server_mode=server_mode, allowed_hosts=frozenset({PUBLIC}) if server_mode else frozenset(),
                          trust_proxy=server_mode, max_sessions=3, session_ttl=3600)
    webgui._SESSIONS.clear()
    srv = ThreadingHTTPServer(("127.0.0.1", 0), webgui.Handler)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    return srv, thread, saved


def _stop(srv, thread, saved):
    srv.shutdown()
    thread.join(timeout=2)
    webgui._clear_all_uploads()
    webgui._CONFIG.clear()
    webgui._CONFIG.update(saved)


class Client:
    """One browser: keeps its session cookie, speaks for the right Host and Origin."""

    def __init__(self, addr, server_mode):
        self.addr, self.cookie = addr, None
        self.host = PUBLIC if server_mode else f"{addr[0]}:{addr[1]}"
        self.origin = f"https://{PUBLIC}" if server_mode else f"http://{self.host}"

    def req(self, method, path, body=None, headers=None):
        hdrs = {"Host": self.host, "Origin": self.origin, **(headers or {})}
        if self.cookie:
            hdrs["Cookie"] = self.cookie
        conn = http.client.HTTPConnection(*self.addr, timeout=10)
        conn.request(method, path, body=body, headers=hdrs)
        r = conn.getresponse()
        raw = r.read()
        if r.getheader("Set-Cookie"):
            self.cookie = r.getheader("Set-Cookie").split(";")[0]
        conn.close()
        return r.status, raw

    def get(self, path):
        return self.req("GET", path)

    def post(self, path, payload):
        return self.req("POST", path, json.dumps(payload), JSON_H)

    def upload(self, path, raw: bytes, name):
        return self.req("POST", path, raw, {"Content-Type": "application/octet-stream", "X-Filename": quote(name)})


@pytest.fixture(params=["local", "server"])
def gui(request, wenjie_path):
    server_mode = request.param == "server"
    srv, thread, saved = _start(server_mode)
    try:
        c = Client(srv.server_address, server_mode)
        c.server_mode = server_mode
        if server_mode:
            status, _ = c.upload("/upload", Path(wenjie_path).read_bytes(), "wenjie.twb")
        else:
            status, _ = c.post("/load", {"path": wenjie_path})
        assert status == 200
        yield c
    finally:
        _stop(srv, thread, saved)


def _clean(raw: bytes):
    """The answer decoded, after checking it has no traceback and no server path."""
    import tempfile
    text = raw.decode("utf-8")
    assert "Traceback" not in text and 'File "' not in text
    assert tempfile.gettempdir() not in text and "py-tbparse-" not in text
    return text


def test_bad_requests_answer_400_with_the_same_words(gui):
    status, raw = gui.get("/style/palettes?offset=x")
    assert status == 400 and json.loads(raw)["error"] == "offset and limit must be whole numbers"
    status, raw = gui.post("/style/export", {"select": []})
    assert status == 400 and json.loads(raw)["error"] == "Tick at least one palette to export."
    status, raw = gui.post("/library/plan", {})
    assert status == 400 and json.loads(raw)["error"] == "Add a library file first."


def test_a_library_that_is_not_a_library_is_an_input_error_400(gui):
    status, raw = gui.upload("/library/upload", b"not json", "bad.library.json")
    assert status == 400 and "is not a library file" in json.loads(raw)["error"]


@pytest.mark.parametrize("route, patched", [
    ("/style/palettes", "_style_palettes_answer"),
    ("/library/entries", "_library_entries_answer"),
    ("/overview", None),
    ("/audit", "_audit_answer"),
])
def test_an_unexpected_error_is_a_500_without_path_or_traceback(gui, monkeypatch, route, patched):
    import tempfile
    secret = str(Path(tempfile.gettempdir()) / "py-tbparse-secret" / "w.twb")

    def boom(*a, **k):
        raise RuntimeError(f"cannot open {secret}")
    if patched:
        monkeypatch.setattr(webgui, patched, boom)
    else:
        monkeypatch.setattr(webgui.TwbParser, "get_report", boom)
    status, raw = gui.get(route)
    assert status == 500
    err = json.loads(raw)["error"]
    assert err.startswith("could not") and "Traceback" not in err
    if gui.server_mode:
        assert secret not in err and "(temp)" in err
    # the connection and the session survive
    assert gui.get("/dashboards")[0] == 200


def test_a_plain_value_error_from_inside_is_a_500_not_a_400(gui, monkeypatch):
    monkeypatch.setattr(webgui, "_style_palettes_answer", lambda qs: (_ for _ in ()).throw(ValueError("bug")))
    status, raw = gui.get("/style/palettes")
    assert status == 500 and "bug" in json.loads(raw)["error"]


def test_an_error_in_a_download_is_plain_text_and_scrubbed(gui, monkeypatch):
    import tempfile
    secret = str(Path(tempfile.gettempdir()) / "py-tbparse-secret")
    monkeypatch.setattr(webgui.Handler, "_renamed_workbook",
                        lambda self, *a: (_ for _ in ()).throw(OSError(errno.EIO, f"read failed in {secret}")))
    status, raw = gui.get("/download-workbook")
    text = raw.decode()
    assert status == 500 and "Traceback" not in text
    if gui.server_mode:
        assert secret not in text


def test_a_refusal_is_409_and_an_integrity_error_422(gui, monkeypatch):
    def refuse(payload):
        raise LibraryClashError("'Ratio' is already in the target datasource (on_clash='fail')")

    def broken(payload):
        raise IntegrityError("the result would have a broken reference")
    monkeypatch.setattr(webgui, "_library_add", refuse)
    monkeypatch.setattr(webgui, "_library_export", broken)
    gui.post("/library/clear", {})
    assert gui.post("/library/add", {})[0] == 409
    assert gui.post("/library/export", {"select": ["a"]})[0] == 422


def test_an_upload_that_does_not_parse_is_400_and_names_no_folder(gui):
    status, raw = gui.upload("/upload", b"<?xml version='1.0'?><workbook><broken", "broken.twb")
    assert status == 400
    _clean(raw)
    err = json.loads(raw)["error"]
    assert err
    # the earlier workbook is replaced by nothing partial: the session still answers
    assert gui.get("/tables")[0] == 200


def test_a_target_workbook_that_does_not_parse_is_400_and_names_no_folder(gui):
    status, raw = gui.upload("/copy/upload", b"PK\x03\x04 not really a zip", "target.twbx")
    assert status == 400
    _clean(raw)


def test_unknown_route_and_bad_json_stay_as_they_were(gui):
    assert gui.post("/nope", {})[0] == 404
    status, raw = gui.req("POST", "/library/plan", b"{", JSON_H)
    assert status == 400 and json.loads(raw)["error"] == "malformed JSON body"


# ---- the library clash retry still works ----

def test_the_plan_still_retries_as_rename_on_a_clash_but_add_refuses(tmp_path, wenjie_path):
    from test_audit import workbook
    calcs = [("[Calculation_1]", "Ratio", "[Sales] / [Profit]")]
    src = workbook(tmp_path, calcs=calcs, name="src.twb")
    other = tmp_path / "o"
    other.mkdir()
    clash = other / "clash.twb"
    clash.write_text(Path(src).read_text(encoding="utf-8").replace("[Sales] / [Profit]", "[Profit] / [Sales]"), encoding="utf-8")

    srv, thread, saved = _start(False)
    try:
        c = Client(srv.server_address, False)
        assert c.post("/load", {"path": src})[0] == 200
        status, lib = c.post("/library/export", {"select": ["[Calculation_1]"]})
        assert status == 200
        assert c.post("/load", {"path": str(clash)})[0] == 200
        assert c.upload("/library/upload", lib, "x.library.json")[0] == 200
        status, raw = c.post("/library/plan", {})
        plan = json.loads(raw)
        assert status == 200 and plan["blocked"] and plan["will_add"] == 0
        status, raw = c.post("/library/add", {})
        assert status == 409 and "already in the target" in json.loads(raw)["error"]
        status, raw = c.post("/library/plan", {"on_clash": "nope"})
        assert status == 400 and json.loads(raw)["error"].startswith("on_clash: use")
    finally:
        _stop(srv, thread, saved)
