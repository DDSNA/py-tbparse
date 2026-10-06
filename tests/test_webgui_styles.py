"""The Styles view's endpoints: GET /style/palettes, /style/state, POST /style/upload, /style/plan, /style/add,
/style/export and /style/clear. Nothing here takes a path, and nothing is written next to a workbook or over a
Preferences.tps."""

from __future__ import annotations

import hashlib
import http.client
import json
import shutil
import threading
import zipfile
from http.server import ThreadingHTTPServer
from io import BytesIO
from pathlib import Path
from urllib.parse import quote

import pytest

from py_tbparse import TwbParser, read_palettes, webgui

FIX = Path(__file__).parent / "fixtures"
STYLE = FIX / "style"
JSON_H = {"Content-Type": "application/json"}
NAMES = ["Acme Brand", "Acme Ramp", "Acme Diverging"]


@pytest.fixture
def server():
    webgui._STATE.update(parser=None, path=None, uploaded=False, report=None, audit=None, lib=None, sty=None)
    srv = ThreadingHTTPServer(("127.0.0.1", 0), webgui.Handler)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    try:
        yield srv.server_address
    finally:
        srv.shutdown()
        thread.join(timeout=2)


def _req(addr, path, method="GET", body=None, headers=None):
    conn = http.client.HTTPConnection(*addr, timeout=10)
    conn.request(method, path, body=body, headers=headers or {})
    r = conn.getresponse()
    data = r.read()
    out = (r.status, data, dict(r.getheaders()))
    conn.close()
    return out


def _get(addr, path):
    status, data, _ = _req(addr, path)
    return status, json.loads(data)


def _post(addr, path, payload):
    return _req(addr, path, "POST", json.dumps(payload), JSON_H)


def _postj(addr, path, payload):
    status, data, _ = _post(addr, path, payload)
    return status, json.loads(data)


def _upload(addr, raw: bytes, name, ctype="application/octet-stream"):
    status, data, _ = _req(addr, "/style/upload", "POST", raw, {"Content-Type": ctype, "X-Filename": quote(name)})
    return status, json.loads(data)


def _load(addr, path):
    assert _post(addr, "/load", {"path": str(path)})[0] == 200


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


@pytest.fixture
def wb(tmp_path):
    p = tmp_path / "palettes.twb"
    shutil.copy(STYLE / "palettes.twb", p)
    return p


@pytest.fixture
def plain(tmp_path):
    p = tmp_path / "plain.twb"
    shutil.copy(FIX / "test_for_wenjie.twb", p)
    return p


def _style_file(addr_wb_path):
    """A style.json holding the palettes of the fixture workbook, as bytes."""
    import tempfile
    from py_tbparse import export_palettes
    with tempfile.TemporaryDirectory() as d:
        out = Path(d) / "x.style.json"
        export_palettes([str(addr_wb_path)], out)
        return out.read_bytes()


def test_everything_needs_a_workbook(server):
    assert _get(server, "/style/palettes")[0] == 400
    assert _post(server, "/style/export", {"select": ["a"]})[0] == 400
    assert _post(server, "/style/plan", {})[0] == 400
    assert _req(server, "/style/upload", "POST", b"{}", {"Content-Type": "application/octet-stream", "X-Filename": "a.style.json"})[0] == 400


def test_palettes_are_listed_with_colours_and_type(server, wb):
    _load(server, wb)
    status, d = _get(server, "/style/palettes")
    assert status == 200 and d["total"] == 3 and d["problem_count"] == 0
    assert [r["name"] for r in d["rows"]] == NAMES
    assert [r["type"] for r in d["rows"]] == ["regular", "ordered-sequential", "ordered-diverging"]
    assert d["rows"][0]["colors"][0] == "#1A3A5C" and d["rows"][0]["n_colors"] == 4
    status, d = _get(server, "/style/palettes?q=ramp&names=1")
    assert d["matching"] == 1 and d["names"] == ["Acme Ramp"]


def test_a_workbook_without_palettes_lists_nothing(server, plain):
    _load(server, plain)
    status, d = _get(server, "/style/palettes")
    assert status == 200 and d["total"] == 0 and d["rows"] == [] and d["problems"] == []


def test_the_list_is_paged_and_capped_at_100(server, tmp_path):
    pals = "".join(f'<color-palette name="P{i:03d}" type="regular"><color>#{i % 256:02X}2233</color></color-palette>' for i in range(230))
    text = (FIX / "test_for_wenjie.twb").read_text(encoding="utf-8")
    import re
    big = tmp_path / "big.twb"
    big.write_text(re.sub(r"</preferences>", pals + "</preferences>", text, count=1), encoding="utf-8")
    _load(server, big)
    _, d = _get(server, "/style/palettes?limit=5000")
    assert d["total"] == 230 and len(d["rows"]) == 100 and d["limit"] == 100
    _, d = _get(server, "/style/palettes?offset=200")
    assert len(d["rows"]) == 30
    _, d = _get(server, "/style/palettes?names=1")
    assert len(d["names"]) == 230
    assert _get(server, "/style/palettes?offset=x")[0] == 400


def test_many_colours_are_cut_in_the_list(server, tmp_path):
    cols = "".join(f"<color>#{i:02X}2233</color>" for i in range(200))
    text = (FIX / "test_for_wenjie.twb").read_text(encoding="utf-8")
    p = tmp_path / "wide.twb"
    p.write_text(text.replace("</preferences>", f'<color-palette name="Wide" type="regular">{cols}</color-palette></preferences>', 1), encoding="utf-8")
    _load(server, p)
    _, d = _get(server, "/style/palettes")
    assert d["rows"][0]["n_colors"] == 200 and len(d["rows"][0]["colors"]) == 40


def test_check_results_name_the_invalid_palettes(server, tmp_path):
    text = (FIX / "test_for_wenjie.twb").read_text(encoding="utf-8")
    p = tmp_path / "bad.twb"
    p.write_text(text.replace("</preferences>", '<color-palette name="Bad" type="regular"><color>blue</color></color-palette></preferences>', 1), encoding="utf-8")
    _load(server, p)
    _, d = _get(server, "/style/palettes")
    assert d["rows"][0]["status"] == "invalid" and d["problem_count"] == 1 and "Bad" in d["problems"][0]


def test_export_as_style_file_and_as_tps(server, wb):
    _load(server, wb)
    status, raw, h = _post(server, "/style/export", {"select": ["Acme Brand", "Acme Ramp"]})
    assert status == 200 and h["Content-Disposition"].startswith("attachment")
    style = json.loads(raw)
    assert style["format"] == "py-tbparse-style" and [p["name"] for p in style["palettes"]] == ["Acme Brand", "Acme Ramp"]
    status, raw, h = _post(server, "/style/export", {"select": ["Acme Ramp"], "format": "tps"})
    assert status == 200 and "Preferences_palettes.tps" in h["Content-Disposition"] and "Preferences.tps\"" not in h["Content-Disposition"]
    assert raw.startswith(b"<?xml") and b'name="Acme Ramp"' in raw and b"Acme Brand" not in raw


@pytest.mark.parametrize("payload", [{}, {"select": []}, {"select": "Acme Brand"}, {"select": [1]}, {"select": ["Nope"]},
                                     {"select": ["Acme Brand"], "format": "xml"}])
def test_export_needs_a_real_selection(server, wb, payload):
    _load(server, wb)
    status, data, _ = _post(server, "/style/export", payload)
    assert status == 400 and b"error" in data


@pytest.mark.parametrize("route", ["/style/export", "/style/plan", "/style/add", "/style/clear"])
@pytest.mark.parametrize("key", ["path", "output_path", "output", "target", "overwrite"])
def test_no_route_accepts_a_path_or_an_output(server, wb, route, key):
    _load(server, wb)
    status, data, _ = _post(server, route, {key: "/tmp/x"})
    assert status == 400 and key.encode() in data


def test_an_upload_is_checked(server, wb):
    _load(server, wb)
    assert _upload(server, b"not json", "a.style.json")[0] == 400
    assert _upload(server, b'{"format": "other"}', "a.style.json")[0] == 400
    assert _upload(server, b"<x/>", "a.tps")[0] == 400
    assert _upload(server, b"hello", "a.txt")[0] == 400
    assert _upload(server, b"{}", "a.style.json", ctype="application/json")[0] == 415
    assert _upload(server, (STYLE / "bad.tps").read_bytes(), "bad.tps")[1]["file"]["invalid"] == 4


def test_upload_has_a_size_limit(server, wb, monkeypatch):
    _load(server, wb)
    monkeypatch.setattr(webgui, "MAX_STYLE_BYTES", 10)
    status, d = _upload(server, b"x" * 50, "a.style.json")
    assert status == 413 and "can be at most" in d["error"]


def test_plan_needs_a_file_first(server, wb):
    _load(server, wb)
    status, d = _postj(server, "/style/plan", {})
    assert status == 400 and "Add a palette file" in d["error"]


def test_the_default_policy_is_fail_and_every_clash_is_listed(server, plain):
    _load(server, plain)
    # Preferences.tps holds "Acme Brand" #112233,#445566; the open workbook gets a different "Acme Brand"
    text = plain.read_text(encoding="utf-8")
    other = plain.with_name("other.twb")
    other.write_text(text.replace("</preferences>", '<color-palette name="Acme Brand" type="regular"><color>#999999</color></color-palette></preferences>', 1), encoding="utf-8")
    _load(server, other)
    status, d = _upload(server, (STYLE / "Preferences.tps").read_bytes(), "Preferences.tps")
    assert status == 200 and d["file"]["usable"] == 2
    status, plan = _postj(server, "/style/plan", {})
    assert plan["policy"] == "fail" and plan["blocked"] is True and plan["will_add"] == 0
    assert plan["counts"] == {"fail": 1, "add": 1} and plan["clash_count"] == 1
    assert plan["clashes"][0]["name"] == "Acme Brand"
    assert plan["rows"][0]["colors"] == ["#112233", "#445566"]
    status, d, _ = _post(server, "/style/add", {})
    assert status == 400 and b"Acme Brand" in d
    for policy, will_add in (("skip", 1), ("rename", 2), ("replace", 2)):
        _, plan = _postj(server, "/style/plan", {"on_clash": policy})
        assert plan["blocked"] is False and plan["will_add"] == will_add, policy
    assert _postj(server, "/style/plan", {"on_clash": "overwrite"})[0] == 400


def test_add_returns_a_new_workbook_and_writes_nothing(server, plain, tmp_path):
    _load(server, plain)
    before = _sha(plain)
    names = {p.name for p in tmp_path.iterdir()}
    _upload(server, (STYLE / "Preferences.tps").read_bytes(), "Preferences.tps")
    status, data, h = _post(server, "/style/add", {})
    assert status == 200 and h["X-Style-Added"] == "2" and "plain_palettes.twb" in h["Content-Disposition"]
    out = tmp_path / "new" / "plain_palettes.twb"
    out.parent.mkdir()
    out.write_bytes(data)
    assert [p["name"] for p in read_palettes(str(out))] == ["Acme Brand", "Retail Teal"]
    assert _sha(plain) == before and {p.name for p in tmp_path.iterdir()} == names | {"new"}
    # the open workbook in memory is untouched too
    assert read_palettes(TwbParser(str(plain))) == []


def test_add_to_a_twbx_keeps_the_other_members(server, plain, tmp_path):
    pkg = tmp_path / "pkg.twbx"
    with zipfile.ZipFile(pkg, "w") as z:
        z.write(plain, "plain.twb")
        z.writestr("Data/extra.txt", "keep me")
    _load(server, pkg)
    _upload(server, (STYLE / "Preferences.tps").read_bytes(), "Preferences.tps")
    status, data, h = _post(server, "/style/add", {})
    assert status == 200 and "pkg_palettes.twbx" in h["Content-Disposition"]
    with zipfile.ZipFile(BytesIO(data)) as z:
        assert z.read("Data/extra.txt") == b"keep me"
        assert b"Retail Teal" in z.read("plain.twb")


def test_a_style_file_can_be_added_and_invalid_palettes_are_not(server, plain, tmp_path):
    _load(server, plain)
    status, d = _upload(server, (STYLE / "bad.tps").read_bytes(), "bad.tps")
    assert d["file"]["usable"] == 1 and d["file"]["problems"]
    _, plan = _postj(server, "/style/plan", {})
    assert plan["counts"] == {"add": 1, "invalid": 4} and plan["will_add"] == 1
    status, data, _ = _post(server, "/style/add", {})
    assert status == 200 and b"Fine" in data and b"Bad colour" not in data


def test_a_real_preferences_file_is_never_touched(server, plain, tmp_path):
    prefs = tmp_path / "Preferences.tps"
    shutil.copy(STYLE / "Preferences.tps", prefs)
    before = _sha(prefs)
    _load(server, plain)
    _upload(server, prefs.read_bytes(), "Preferences.tps")
    _post(server, "/style/add", {})
    _post(server, "/style/export", {"select": ["Acme Brand"], "format": "tps"})
    assert _sha(prefs) == before


def test_opening_another_workbook_drops_the_file_and_clear_forgets_it(server, plain, wb):
    _load(server, plain)
    _upload(server, (STYLE / "Preferences.tps").read_bytes(), "Preferences.tps")
    assert _get(server, "/style/state")[1]["file"]["usable"] == 2
    _load(server, wb)
    assert _get(server, "/style/state")[1]["file"] is None
    _upload(server, (STYLE / "Preferences.tps").read_bytes(), "Preferences.tps")
    assert _postj(server, "/style/clear", {})[1] == {"ok": True}
    assert _get(server, "/style/state")[1]["file"] is None


def test_the_script_is_served(server):
    status, data, headers = _req(server, "/static/styles.js")
    assert status == 200 and headers["Content-Type"].startswith("text/javascript") and b"StylesView" in data


# ---- server mode ----

PUBLIC = "tbparse.example.com"


@pytest.fixture
def shared():
    saved = dict(webgui._CONFIG)
    webgui._STATE.base.update(parser=None, path=None, uploaded=False, report=None, audit=None, lib=None, sty=None)
    webgui._CONFIG.update(server_mode=True, allowed_hosts=frozenset({PUBLIC}), trust_proxy=True, max_sessions=3, session_ttl=3600)
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


def _sreq(addr, path, method="GET", body=None, headers=None, cookie=None):
    hdrs = {"Host": PUBLIC, "Origin": f"https://{PUBLIC}", **(headers or {})}
    if cookie:
        hdrs["Cookie"] = cookie
    conn = http.client.HTTPConnection(*addr, timeout=10)
    conn.request(method, path, body=body, headers=hdrs)
    r = conn.getresponse()
    data = r.read()
    out = (r.status, data, r.getheader("Set-Cookie"))
    conn.close()
    return out


def test_server_mode_works_without_paths_and_keeps_each_browsers_file_private(shared, wb, plain):
    cookies = []
    for p in (plain, wb):
        status, _, cookie = _sreq(shared, "/upload", "POST", p.read_bytes(),
                                  {"Content-Type": "application/octet-stream", "X-Filename": quote(p.name)})
        assert status == 200
        cookies.append(cookie.split(";")[0])
    a, b = cookies
    octet = {"Content-Type": "application/octet-stream", "X-Filename": "Preferences.tps"}
    assert _sreq(shared, "/style/upload", "POST", (STYLE / "Preferences.tps").read_bytes(), octet, a)[0] == 200
    assert json.loads(_sreq(shared, "/style/state", cookie=a)[1])["file"]["usable"] == 2
    assert json.loads(_sreq(shared, "/style/state", cookie=b)[1])["file"] is None
    status, data, _ = _sreq(shared, "/style/add", "POST", "{}", JSON_H, a)
    assert status == 200 and b"Retail Teal" in data
    status, data, _ = _sreq(shared, "/style/export", "POST", json.dumps({"select": ["Acme Ramp"], "format": "tps"}), JSON_H, b)
    assert status == 200 and b"Acme Ramp" in data
    status, body, _ = _sreq(shared, "/style/plan", "POST", json.dumps({"path": "/etc/passwd"}), JSON_H, a)
    assert status == 400 and b"path" in body
