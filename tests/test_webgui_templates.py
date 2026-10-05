"""The GUI's `/template/*` endpoints (WP9 package 9b): uploads into two slots, plan, apply, download, save beside
the template (local only), and the server-mode rules: no paths from a JSON body, no temp paths in answers."""

from __future__ import annotations

import csv
import hashlib
import http.client
import io
import json
import os
import tempfile
import threading
import time
import zipfile
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.parse import quote

import pytest

import py_tbparse.templates as templates
from py_tbparse import load_template, make_template, read_data, template_gui, webgui

PUBLIC_FIXTURES = Path(__file__).parent / "fixtures" / "public"
PUBLIC = "tbparse.example.com"


@pytest.fixture(autouse=True)
def fixed_clock(monkeypatch):
    monkeypatch.setattr(templates, "_now", lambda: "2026-10-05T00:00:00+00:00")


# --- inputs -------------------------------------------------------------------------------------------------

@pytest.fixture
def tpl_file(tmp_path):
    """The filtering workbook as a template: one datasource, one required field (`Burst Out Set list`)."""
    folder = tmp_path / "tpl"
    folder.mkdir()
    return Path(make_template(str(PUBLIC_FIXTURES / "filtering.twb"), output_path=str(folder / "f.template.twbx"),
                              template_id="tpl-1"))


def _columns(tpl_path, skip=()):
    t = load_template(str(tpl_path))
    entry = next(e for e in t.manifest["datasources"] if e["fields"])
    return [f["remote"] for f in entry["fields"] if f["name"] not in skip]


@pytest.fixture
def csv_file(tmp_path, tpl_file):
    folder = tmp_path / "data"
    folder.mkdir()
    path = folder / "data.csv"
    with open(path, "w", newline="", encoding="utf-8") as fh:
        csv.writer(fh).writerow(_columns(tpl_file))
    return path


def _required_field(tpl_path):
    t = load_template(str(tpl_path))
    entry = next(e for e in t.manifest["datasources"] if e["fields"])
    return next(f for f in entry["fields"] if f["required"])


# --- servers ------------------------------------------------------------------------------------------------

def _start():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), webgui.Handler)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    return srv, thread


@pytest.fixture
def server():
    """A local GUI (the default mode): one state for everybody, paths allowed."""
    saved = dict(webgui._CONFIG)
    webgui._clear_all_uploads()
    webgui._STATE.base.update(parser=None, path=None, uploaded=False, report=None)
    srv, thread = _start()
    try:
        yield srv.server_address
    finally:
        srv.shutdown()
        thread.join(timeout=2)
        webgui._clear_all_uploads()
        webgui._CONFIG.clear()
        webgui._CONFIG.update(saved)


@pytest.fixture
def server_mode():
    saved = dict(webgui._CONFIG)
    webgui._clear_all_uploads()
    webgui._STATE.base.update(parser=None, path=None, uploaded=False, report=None)
    webgui._CONFIG.update(
        server_mode=True, allowed_hosts=frozenset({PUBLIC}), trust_proxy=True, max_sessions=3, session_ttl=3600
    )
    srv, thread = _start()
    try:
        yield srv.server_address
    finally:
        srv.shutdown()
        thread.join(timeout=2)
        webgui._clear_all_uploads()
        webgui._CONFIG.clear()
        webgui._CONFIG.update(saved)


class Client:
    """One browser: the right Host and Origin for the mode, and the session cookie once it has one."""

    def __init__(self, addr, server_mode=False):
        self.addr = addr
        self.server_mode = server_mode
        self.host = PUBLIC if server_mode else f"{addr[0]}:{addr[1]}"
        self.origin = f"https://{PUBLIC}" if server_mode else f"http://{self.host}"
        self.cookie = None
        self.bodies = []  # every response body, to look for leaked paths

    def request(self, method, path, body=None, headers=None):
        conn = http.client.HTTPConnection(*self.addr, timeout=30)
        hdrs = {"Host": self.host}
        if self.cookie:
            hdrs["Cookie"] = self.cookie
        hdrs.update(headers or {})
        try:
            conn.putrequest(method, path, skip_host=True, skip_accept_encoding=True)
            for k, v in hdrs.items():
                if v is not None:
                    conn.putheader(k, v)
            if body is not None and "Content-Length" not in hdrs:
                conn.putheader("Content-Length", str(len(body)))
            conn.endheaders(body)
            r = conn.getresponse()
            raw = r.read()
            cookie = r.getheader("Set-Cookie")
            if cookie:
                self.cookie = cookie.split(";")[0]
            self.bodies.append(raw)
            return r.status, raw, r
        finally:
            conn.close()

    def upload(self, route, data: bytes, name, ctype="application/octet-stream", headers=None):
        hdrs = {"Content-Type": ctype, "X-Filename": quote(name), "Origin": self.origin}
        hdrs.update(headers or {})
        status, raw, _ = self.request("POST", route, data, hdrs)
        return status, _json(raw)

    def upload_file(self, route, path, name=None):
        path = Path(path)
        return self.upload(route, path.read_bytes(), name or path.name)

    def post(self, route, payload, headers=None):
        hdrs = {"Content-Type": "application/json", "Origin": self.origin}
        hdrs.update(headers or {})
        body = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
        status, raw, _ = self.request("POST", route, body, hdrs)
        return status, _json(raw)

    def get(self, route, headers=None):
        return self.request("GET", route, None, headers)


def _json(raw):
    try:
        return json.loads(raw)
    except ValueError:
        return {"error": raw.decode("utf-8", "replace")}


def _session_tpl(cookie=None):
    """The template state of the local GUI, or of the server-mode session with this cookie."""
    if cookie is None:
        return webgui._STATE.base["tpl"]
    return webgui._SESSIONS[cookie.split("=", 1)[1]]["state"]["tpl"]


def _temp_markers():
    roots = {tempfile.gettempdir(), os.path.realpath(tempfile.gettempdir())}
    return [r.encode() for r in roots] + [json.dumps(r)[1:-1].encode() for r in roots]


def _assert_no_temp_path(bodies):
    for raw in bodies:
        for marker in _temp_markers():
            assert marker not in raw, f"a server temp path leaked: {raw[:300]!r}"


def _answers(zip_bytes):
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as z:
        return json.loads(z.read("template-answers.json"))


# --- 1. the whole round trip --------------------------------------------------------------------------------

@pytest.mark.parametrize("mode", ["local", "server"])
def test_upload_plan_apply_download(request, mode, tpl_file, csv_file, tmp_path):
    addr = request.getfixturevalue("server" if mode == "local" else "server_mode")
    c = Client(addr, server_mode=mode == "server")
    original = tpl_file.read_bytes()

    status, data = c.upload_file("/template/upload-template", tpl_file)
    assert status == 200, data
    assert data["template"]["name"] == "filtering" and data["template"]["label"] == "f.template.twbx"
    assert data["template"]["id"] == "tpl-1" and isinstance(data["template"]["findings"], list)

    status, data = c.upload_file("/template/upload-data", csv_file)
    assert status == 200, data
    assert data["data"]["kind"] == "csv" and data["data"]["label"] == "data.csv"
    assert len(data["data"]["columns"]) == len(_columns(tpl_file))

    status, plan = c.post("/template/plan", {})
    assert status == 200, plan
    assert plan["ready"] is True and plan["problems"] == []
    assert plan["mapping"]["total"] > 0

    status, applied = c.post("/template/apply", {})
    assert status == 200, applied
    assert applied["ok"] is True and applied["name"] == "f_data.twbx" and applied["size"] > 0
    assert "path" not in applied

    status, body, resp = c.get("/template/output")
    assert status == 200
    assert resp.getheader("Content-Type") == "application/octet-stream"
    assert "f_data.twbx" in resp.getheader("Content-Disposition")
    answers = _answers(body)
    assert answers["data"]["file"] == "data.csv", "the answers name the data label, never a temp path"
    assert answers["template"]["file"] == "f.template.twbx"

    # the same bytes the API gives for the same inputs
    t = load_template(str(tpl_file))
    d = read_data(str(csv_file))
    out = tmp_path / "direct"
    out.mkdir()
    direct = template_gui.apply(t, d, str(out), data_path="data.csv")
    assert Path(direct["path"]).read_bytes() == body

    # the uploaded template in the session dir is unchanged
    state = _session_tpl(c.cookie if mode == "server" else None)
    assert Path(state["template_path"]).read_bytes() == original
    assert hashlib.sha256(Path(state["template_path"]).read_bytes()).digest() == hashlib.sha256(original).digest()
    if mode == "server":
        _assert_no_temp_path(c.bodies)


def test_state_restores_the_cards_after_a_reload(server, tpl_file, csv_file):
    c = Client(server)
    status, raw, _ = c.get("/template/state")
    assert status == 200 and json.loads(raw) == {"template": None, "data": None, "sheets": None,
                                                 "datasources": None, "output": None}
    c.upload_file("/template/upload-template", tpl_file)
    c.upload_file("/template/upload-data", csv_file)
    state = json.loads(c.get("/template/state")[1])
    assert state["template"]["label"] == "f.template.twbx" and state["data"]["label"] == "data.csv"
    assert state["output"] is None
    c.post("/template/apply", {})
    state = json.loads(c.get("/template/state")[1])
    assert state["output"]["name"] == "f_data.twbx" and state["output"]["size"] > 0


def test_one_output_is_kept_and_a_new_upload_replaces_the_slot(server, tpl_file, csv_file):
    c = Client(server)
    c.upload_file("/template/upload-template", tpl_file)
    c.upload_file("/template/upload-data", csv_file)
    assert c.post("/template/apply", {})[0] == 200
    first = _session_tpl()["output"]
    assert c.post("/template/apply", {})[0] == 200
    second = _session_tpl()["output"]
    assert not os.path.exists(first) and os.path.exists(second)
    outputs = [p for p in Path(_session_tpl()["dir"]).rglob("*_data*.twbx")]
    assert outputs == [Path(second)]

    old_data = _session_tpl()["data_path"]
    c.upload("/template/upload-data", b"a,b\n1,2\n", "other.csv")
    assert not os.path.exists(old_data), "a new upload into a slot deletes the previous file"
    assert _session_tpl()["data_label"] == "other.csv"


def test_clear_drops_the_files_and_the_state(server, tpl_file, csv_file):
    c = Client(server)
    c.upload_file("/template/upload-template", tpl_file)
    c.upload_file("/template/upload-data", csv_file)
    c.post("/template/apply", {})
    folder = _session_tpl()["dir"]
    assert os.path.isdir(folder)
    status, data = c.post("/template/clear", {})
    assert status == 200 and data["ok"] is True
    assert not os.path.exists(folder)
    assert c.get("/template/output")[0] == 404
    assert json.loads(c.get("/template/state")[1])["template"] is None
    assert c.post("/template/plan", {})[0] == 400


def test_output_is_404_before_any_apply(server):
    status, raw, _ = Client(server).get("/template/output")
    assert status == 404


def test_apply_with_an_edited_mapping_params_and_tokens_is_kept_in_the_answers(server, tpl_file, csv_file):
    c = Client(server)
    c.upload_file("/template/upload-template", tpl_file)
    c.upload_file("/template/upload-data", csv_file)
    field = _required_field(tpl_file)
    status, plan = c.post("/template/plan", {"mapping": {field["name"]: ""}})
    assert status == 200 and plan["ready"] is False and plan["problems"]
    assert c.post("/template/apply", {"mapping": {field["name"]: ""}})[0] == 400
    status, applied = c.post("/template/apply", {"mapping": {field["name"]: ""}, "allow_missing": True})
    assert status == 200, applied
    answers = _answers(c.get("/template/output")[1])
    assert field["name"] in answers["missing"]


def test_a_column_mapped_twice_is_a_problem_not_an_error(server, tpl_file, csv_file):
    c = Client(server)
    c.upload_file("/template/upload-template", tpl_file)
    c.upload_file("/template/upload-data", csv_file)
    t = load_template(str(tpl_file))
    entry = next(e for e in t.manifest["datasources"] if e["fields"])
    a, b = entry["fields"][0], entry["fields"][1]
    status, plan = c.post("/template/plan", {"mapping": {a["name"]: a["remote"], b["name"]: a["remote"]}})
    assert status == 200 and plan["ready"] is False and plan["problems"]


def test_data_path_goes_into_the_output_only(server_mode, tpl_file, csv_file):
    c = Client(server_mode, server_mode=True)
    c.upload_file("/template/upload-template", tpl_file)
    c.upload_file("/template/upload-data", csv_file)
    status, applied = c.post("/template/apply", {"data_path": "C:\\Users\\me\\Downloads\\data.csv"})
    assert status == 200, applied
    answers = _answers(c.get("/template/output")[1])
    assert answers["data"]["file"] == "C:/Users/me/Downloads/data.csv"
    status, data = c.post("/template/apply", {"data_path": "/home/me/other.csv"})
    assert status == 400 and "data.csv" in data["error"]
    # a folder is only written into the output, never opened or listed
    status, applied = c.post("/template/apply", {"data_path": "/etc/passwd"})
    assert status == 200
    assert _answers(c.get("/template/output")[1])["data"]["file"] == "/etc/passwd/data.csv"
    _assert_no_temp_path(c.bodies)


# --- 2. refusals --------------------------------------------------------------------------------------------

UPLOAD_ROUTES = ["/template/upload-template", "/template/upload-data"]


@pytest.mark.parametrize("route", UPLOAD_ROUTES)
def test_upload_refusals(server, route, tpl_file, monkeypatch):
    c = Client(server)
    body = tpl_file.read_bytes()
    assert c.upload(route, body, "f.template.twbx", ctype="text/plain")[0] == 415
    assert c.upload(route, body, "f.template.twbx", headers={"Origin": "http://evil.example"})[0] == 403
    assert c.upload(route, body, "f.template.twbx", headers={"Host": "attacker.example:%d" % server[1]})[0] == 403
    assert c.upload(route, body, "")[0] == 400
    assert c.upload(route, b"", "f.template.twbx")[0] == 400
    monkeypatch.setattr(webgui, "MAX_UPLOAD_BYTES", 100)
    status, data = c.upload(route, b"PK" + b"x" * 200, "f.template.twbx")
    assert status == 413 and "limit" in data["error"]


def test_the_template_slot_takes_only_a_twbx_zip(server, wenjie_path):
    c = Client(server)
    status, data = c.upload("/template/upload-template", b"a,b\n1,2\n", "x.twbx")
    assert status == 400 and "zip" in data["error"]
    status, data = c.upload_file("/template/upload-template", wenjie_path)
    assert status == 400 and ".twbx" in data["error"]
    status, data = c.upload("/template/upload-template", b"a,b\n", "x.csv")
    assert status == 400


def test_a_packaged_workbook_without_a_manifest_is_refused_with_its_label(server_mode, zip_twbx_path):
    c = Client(server_mode, server_mode=True)
    status, data = c.upload_file("/template/upload-template", zip_twbx_path, name="book.twbx")
    assert status == 400 and "book.twbx" in data["error"]
    assert _session_tpl(c.cookie)["template"] is None
    _assert_no_temp_path(c.bodies)


@pytest.mark.parametrize("name,body,needle", [
    ("x.csv", b"a,b\x00\x00", "text"),
    ("x.tsv", b"\x00\x01\x02", "text"),
    ("x.xlsx", b"a,b\n1,2\n", "zip"),
    ("x.xlsm", b"<xml/>", "zip"),
    ("x.twbx", b"<xml/>", "zip"),
    ("x.twb", b"PK\x03\x04", "XML"),
    ("x.tds", b"\x00PK", "XML"),
    ("x.json", b'{"format": "py-tbparse-target"}', ".json"),
    ("x.xls", b"\xd0\xcf\x11\xe0", ".xls"),
    ("x.xlsb", b"PK\x03\x04", ".xls"),
    ("x.exe", b"MZ", ".csv"),
])
def test_the_data_slot_checks_extension_and_content(server, name, body, needle):
    status, data = Client(server).upload("/template/upload-data", body, name)
    assert status == 400 and needle in data["error"], data


def test_a_low_disk_refuses_an_upload_with_507(server, tpl_file, monkeypatch):
    monkeypatch.setattr(webgui, "_free_bytes", lambda path: 10 * 1024 * 1024)
    status, data = Client(server).upload_file("/template/upload-template", tpl_file)
    assert status == 507 and "space" in data["error"]
    assert webgui._STATE.base["tpl"] is None or webgui._STATE.base["tpl"]["template"] is None


def test_a_small_tmpfs_still_takes_a_small_upload(server, tpl_file, monkeypatch):
    # the CI container gives /tmp 64 MB; a template of a few hundred KB must not be refused for lack of room
    monkeypatch.setattr(webgui, "_free_bytes", lambda path: 64 * 1024 * 1024)
    status, data = Client(server).upload_file("/template/upload-template", tpl_file)
    assert status == 200, data


@pytest.mark.parametrize("route", ["/template/plan", "/template/apply", "/template/select-data", "/template/clear"])
def test_a_json_body_over_the_cap_is_413(server, route):
    body = json.dumps({"pad": "a" * (webgui.MAX_JSON_BYTES + 10)}).encode()
    status, data = Client(server).post(route, body)
    assert status == 413 and "too big" in data["error"]


def test_a_json_body_over_the_cap_is_413_with_a_large_body(server, monkeypatch):
    monkeypatch.setattr(webgui, "MAX_JSON_BYTES", 1024)
    body = json.dumps({"pad": "a" * (4 * 1024 * 1024)}).encode()
    status, _ = Client(server).post("/template/plan", body)
    assert status == 413


@pytest.mark.parametrize("route", ["/template/plan", "/template/apply", "/template/clear", "/template/open"])
def test_json_routes_check_content_type_and_origin(server, route):
    c = Client(server)
    assert c.post(route, {}, headers={"Content-Type": "text/plain"})[0] == 415
    assert c.post(route, {}, headers={"Origin": "http://attacker.example"})[0] == 403
    assert c.post(route, {}, headers={"Host": "attacker.example:%d" % server[1]})[0] == 403
    status, data = c.post(route, b"[1, 2]")
    assert status == 400 and "object" in data["error"]
    status, data = c.post(route, b"{not json")
    assert status == 400 and "malformed" in data["error"]


def test_unknown_template_route_is_404(server):
    assert Client(server).post("/template/nope", {})[0] == 404
    assert Client(server).get("/template/nope")[0] == 404


# --- 4. server mode -----------------------------------------------------------------------------------------

def test_server_mode_refuses_the_path_routes(server_mode, tpl_file):
    c = Client(server_mode, server_mode=True)
    for route, body in (("/template/open", {"path": str(tpl_file)}), ("/template/open-data", {"path": str(tpl_file)}),
                        ("/template/save", {})):
        status, data = c.post(route, body)
        assert status == 403 and "server" in data["error"], route


def test_two_cookies_see_different_templates(server_mode, tpl_file, csv_file, tmp_path):
    a = Client(server_mode, server_mode=True)
    b = Client(server_mode, server_mode=True)
    a.upload_file("/template/upload-template", tpl_file)
    other = tmp_path / "tpl" / "g.template.twbx"
    other.write_bytes(tpl_file.read_bytes())
    b.upload_file("/template/upload-template", other)
    assert json.loads(a.get("/template/state")[1])["template"]["label"] == "f.template.twbx"
    assert json.loads(b.get("/template/state")[1])["template"]["label"] == "g.template.twbx"
    assert _session_tpl(a.cookie)["dir"] != _session_tpl(b.cookie)["dir"]
    # no cookie: nothing, and no state is made by a GET
    anon = Client(server_mode, server_mode=True)
    assert json.loads(anon.get("/template/state")[1])["template"] is None
    assert anon.get("/template/output")[0] == 404
    # b applies; a has no output
    b.upload_file("/template/upload-data", csv_file)
    assert b.post("/template/apply", {})[0] == 200
    assert a.get("/template/output")[0] == 404
    assert b.get("/template/output")[0] == 200


def test_an_evicted_session_loses_its_template_dir(server_mode, tpl_file):
    first = Client(server_mode, server_mode=True)
    first.upload_file("/template/upload-template", tpl_file)
    folder = _session_tpl(first.cookie)["dir"]
    assert os.path.isdir(folder)
    for _ in range(3):
        time.sleep(0.01)
        Client(server_mode, server_mode=True).upload_file("/template/upload-template", tpl_file)
    assert len(webgui._SESSIONS) == 3
    assert first.cookie.split("=", 1)[1] not in webgui._SESSIONS
    assert not os.path.exists(folder)


def test_an_expired_session_loses_its_template_dir(server_mode, tpl_file):
    c = Client(server_mode, server_mode=True)
    c.upload_file("/template/upload-template", tpl_file)
    folder = _session_tpl(c.cookie)["dir"]
    webgui._CONFIG["session_ttl"] = 0.01
    time.sleep(0.05)
    Client(server_mode, server_mode=True).get("/")
    assert not os.path.exists(folder)


def test_clear_all_uploads_removes_every_template_dir(server_mode, tpl_file):
    remote = Client(server_mode, server_mode=True)
    remote.upload_file("/template/upload-template", tpl_file)
    folder = _session_tpl(remote.cookie)["dir"]
    webgui._clear_all_uploads()
    assert not os.path.exists(folder)


# --- 5. no paths and no unknown keys in a JSON body ---------------------------------------------------------

@pytest.mark.parametrize("route", ["/template/plan", "/template/apply", "/template/select-data"])
@pytest.mark.parametrize("key", ["path", "answers", "output_path", "profile", "data", "sheet_path"])
def test_unknown_keys_are_refused_by_name(server, tpl_file, csv_file, route, key):
    c = Client(server)
    c.upload_file("/template/upload-template", tpl_file)
    c.upload_file("/template/upload-data", csv_file)
    status, data = c.post(route, {key: "/etc/passwd"})
    assert status == 400 and repr(key) in data["error"], data
    assert c.get("/template/output")[0] == 404


@pytest.mark.parametrize("payload", [
    {"mapping": ["a"]}, {"mapping": {"a": 1}}, {"params": "x"}, {"params": {"a": [1]}}, {"tokens": {"a": None}},
    {"datasource": 3}, {"allow_missing": "yes"}, {"data_path": 7}, {"data_path": "a" * 1025},
    {"data_path": "C:/x\x00/data.csv"}, {"data_path": "C:/x\n/data.csv"}, {"data_path": "C:/x\r/data.csv"},
])
def test_bad_values_are_400(server, tpl_file, csv_file, payload):
    c = Client(server)
    c.upload_file("/template/upload-template", tpl_file)
    c.upload_file("/template/upload-data", csv_file)
    status, data = c.post("/template/apply", payload)
    assert status == 400 and data["error"], data
    assert c.get("/template/output")[0] == 404


def test_plan_does_not_take_data_path(server, tpl_file, csv_file):
    c = Client(server)
    c.upload_file("/template/upload-template", tpl_file)
    c.upload_file("/template/upload-data", csv_file)
    status, data = c.post("/template/plan", {"data_path": "x"})
    assert status == 400 and "'data_path'" in data["error"]


def test_plan_takes_allow_missing_so_the_page_can_ask_what_creating_anyway_would_do(server, tpl_file, csv_file):
    c = Client(server)
    c.upload_file("/template/upload-template", tpl_file)
    c.upload_file("/template/upload-data", csv_file)
    field = _required_field(tpl_file)
    body = {"mapping": {field["name"]: ""}}
    status, strict = c.post("/template/plan", body)
    assert status == 200 and strict["ready"] is False
    status, lax = c.post("/template/plan", dict(body, allow_missing=True))
    assert status == 200 and lax["ready"] is True and lax["missing_required"]
    assert lax["broken"]["total"] >= 1      # what would break is still listed
    status, data = c.post("/template/plan", {"allow_missing": "yes"})
    assert status == 400 and "allow_missing" in data["error"]


def test_a_plan_answer_has_what_the_review_step_draws(server, tpl_file, csv_file):
    c = Client(server)
    c.upload_file("/template/upload-template", tpl_file)
    c.upload_file("/template/upload-data", csv_file)
    status, plan = c.post("/template/plan", {})
    assert status == 200
    for key in ("mapping", "choices", "broken", "explain", "check", "params", "tokens", "problems", "ready",
                "missing_required"):
        assert key in plan, key
    row = plan["mapping"]["rows"][0]
    for key in ("field", "caption", "datatype", "required", "used_by", "mapped_to", "status"):
        assert key in row, key
    # every dropdown of the page is filled from `choices[datatype]`
    assert {r["datatype"] for r in plan["mapping"]["rows"]} <= set(plan["choices"])
    assert tempfile.gettempdir() not in json.dumps(plan)


def test_open_and_clear_take_only_their_keys(server, tpl_file):
    c = Client(server)
    status, data = c.post("/template/open", {"path": str(tpl_file), "answers": "x"})
    assert status == 400 and "'answers'" in data["error"]
    status, data = c.post("/template/clear", {"path": "x"})
    assert status == 400 and "'path'" in data["error"]


# --- 6. local mode: open by path and save beside the template ----------------------------------------------

def test_open_by_path_and_save_beside_the_template(server, tpl_file, csv_file):
    c = Client(server)
    status, data = c.post("/template/open", {"path": str(tpl_file)})
    assert status == 200, data
    assert data["template"]["label"] == "f.template.twbx" and data["path"] == str(tpl_file)
    status, data = c.post("/template/open-data", {"path": str(csv_file)})
    assert status == 200 and data["data"]["kind"] == "csv" and data["path"] == str(csv_file)

    status, saved = c.post("/template/save", {})
    assert status == 200, saved
    out = tpl_file.parent / "f_data.twbx"
    assert saved["path"] == str(out) and out.exists()
    assert _answers(out.read_bytes())["data"]["file"] == str(csv_file.resolve()), "a path-opened file keeps its path"
    status, data = c.post("/template/save", {})
    assert status == 409 and "already exists" in data["error"]
    assert out.exists()


def test_open_errors_are_400(server, tmp_path, wenjie_path):
    c = Client(server)
    assert c.post("/template/open", {})[0] == 400
    assert c.post("/template/open", {"path": str(tmp_path / "missing.twbx")})[0] == 400
    assert c.post("/template/open", {"path": str(wenjie_path)})[0] == 400
    assert c.post("/template/open-data", {"path": str(tmp_path / "missing.csv")})[0] == 400
    target = tmp_path / "t.json"
    target.write_text('{"format": "py-tbparse-target"}')
    status, data = c.post("/template/open-data", {"path": str(target)})
    assert status == 400 and ".json" in data["error"]


def test_an_uploaded_template_cannot_be_saved_beside(server, tpl_file, csv_file):
    c = Client(server)
    c.upload_file("/template/upload-template", tpl_file)
    c.upload_file("/template/upload-data", csv_file)
    status, data = c.post("/template/save", {})
    assert status == 409 and "Download" in data["error"]


def test_save_with_uploaded_data_writes_the_given_place(server, tpl_file, csv_file):
    c = Client(server)
    c.post("/template/open", {"path": str(tpl_file)})
    c.upload_file("/template/upload-data", csv_file)
    status, saved = c.post("/template/save", {"data_path": "/home/me/data.csv"})
    assert status == 200, saved
    assert _answers(Path(saved["path"]).read_bytes())["data"]["file"] == "/home/me/data.csv"


# --- 7. order of the steps ----------------------------------------------------------------------------------

def test_plan_needs_a_template_then_data(server, tpl_file):
    c = Client(server)
    status, data = c.post("/template/plan", {})
    assert status == 400 and data["error"] == "Choose a template first."
    assert c.post("/template/apply", {})[0] == 400
    c.upload_file("/template/upload-template", tpl_file)
    status, data = c.post("/template/plan", {})
    assert status == 400 and "data" in data["error"]
    status, data = c.post("/template/select-data", {"sheet": "x"})
    assert status == 400 and "data" in data["error"]


def test_a_workbook_with_several_sheets_needs_a_choice(server, tpl_file, tmp_path):
    openpyxl = pytest.importorskip("openpyxl")
    book = openpyxl.Workbook()
    book.active.title = "One"
    book.active.append(_columns(tpl_file))
    second = book.create_sheet("Two")
    second.append(_columns(tpl_file))
    hidden = book.create_sheet("Hidden")
    hidden.sheet_state = "hidden"
    path = tmp_path / "data.xlsx"
    book.save(path)

    c = Client(server)
    c.upload_file("/template/upload-template", tpl_file)
    status, data = c.upload_file("/template/upload-data", path)
    assert status == 200, data
    assert data["data"] is None and data["sheets"] == ["One", "Two"]
    status, err = c.post("/template/plan", {})
    assert status == 400 and "sheet" in err["error"]
    status, data = c.post("/template/select-data", {"sheet": "Two"})
    assert status == 200 and data["data"]["sheet"] == "Two" and data["sheets"] == ["One", "Two"]
    assert c.post("/template/plan", {})[0] == 200
    status, data = c.post("/template/select-data", {"sheet": "Nope"})
    assert status == 400


def test_a_workbook_as_data_lists_its_datasources(server, tpl_file):
    c = Client(server)
    c.upload_file("/template/upload-template", tpl_file)
    status, data = c.upload_file("/template/upload-data", PUBLIC_FIXTURES / "filtering.twb")
    assert status == 200, data
    assert data["data"]["kind"] == "tableau"
    assert c.post("/template/plan", {})[0] == 200


# --- 8. no temp paths in server-mode messages ---------------------------------------------------------------

def test_server_mode_messages_never_name_the_temp_dir(server_mode, tpl_file, csv_file, zip_twbx_path):
    c = Client(server_mode, server_mode=True)
    c.upload_file("/template/upload-template", zip_twbx_path, name="nomanifest.twbx")
    c.upload("/template/upload-template", b"PK\x03\x04 broken zip", "broken.twbx")
    c.upload("/template/upload-data", b"a,b\n", "x.csv")       # no template yet: still stored
    c.upload_file("/template/upload-template", tpl_file)
    c.upload("/template/upload-data", b"\xff\xfe\xfa bad \xff", "bad.csv")
    c.upload("/template/upload-data", b"PK\x03\x04 broken", "bad.xlsx")
    c.upload("/template/upload-data", b"<not xml", "bad.tds")
    c.upload("/template/upload-data", b"<not xml", "bad.twb")
    c.upload_file("/template/upload-data", csv_file)
    c.post("/template/plan", {"mapping": {"[nope]": "x"}})
    c.post("/template/plan", {"params": {"nope": "1"}, "tokens": {"nope": "x"}})
    c.post("/template/apply", {"data_path": "C:/elsewhere/other.csv"})
    c.post("/template/select-data", {"sheet": "x"})
    c.get("/template/state")
    assert len(c.bodies) == 14
    _assert_no_temp_path(c.bodies)


# --- 9. GET routes check the Host -----------------------------------------------------------------------------

@pytest.mark.parametrize("route", ["/template/output", "/template/state"])
def test_template_gets_refuse_a_foreign_host(server, tpl_file, csv_file, route):
    c = Client(server)
    c.upload_file("/template/upload-template", tpl_file)
    c.upload_file("/template/upload-data", csv_file)
    c.post("/template/apply", {})
    status, _, _ = c.get(route, headers={"Host": "attacker.example:%d" % server[1]})
    assert status == 403


# --- the apply lock -----------------------------------------------------------------------------------------

def test_applies_in_one_session_never_overlap(server, tpl_file, csv_file, monkeypatch):
    c = Client(server)
    c.upload_file("/template/upload-template", tpl_file)
    c.upload_file("/template/upload-data", csv_file)
    real = template_gui.apply
    running = []
    overlap = []

    def slow(*args, **kwargs):
        running.append(1)
        if len(running) > 1:
            overlap.append(len(running))
        time.sleep(0.2)
        try:
            return real(*args, **kwargs)
        finally:
            running.pop()

    monkeypatch.setattr(template_gui, "apply", slow)
    results = []
    threads = [threading.Thread(target=lambda: results.append(Client(server).post("/template/apply", {})[0]))
               for _ in range(3)]
    for th in threads:
        th.start()
    for th in threads:
        th.join(timeout=30)
    assert results == [200, 200, 200]
    assert overlap == []
    outputs = list(Path(_session_tpl()["dir"]).rglob("*.twbx"))
    assert sorted(p.name for p in outputs) == ["f.template.twbx", "f_data.twbx"]


def test_an_unexpected_apply_error_is_a_short_500(server, tpl_file, csv_file, monkeypatch):
    c = Client(server)
    c.upload_file("/template/upload-template", tpl_file)
    c.upload_file("/template/upload-data", csv_file)

    def boom(*args, **kwargs):
        raise RuntimeError("deep inside " + str(_session_tpl()["dir"]))

    monkeypatch.setattr(template_gui, "apply", boom)
    status, data = c.post("/template/apply", {})
    assert status == 500 and "Traceback" not in data["error"]
    assert str(_session_tpl()["dir"]) not in data["error"]
    assert c.get("/template/output")[0] == 404
