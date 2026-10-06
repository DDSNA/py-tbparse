"""The Libraries view's endpoints: GET /library/entries, POST /library/export, /library/upload, /library/plan,
/library/add and /library/clear. Nothing here takes a path, and nothing is ever written next to a workbook."""

from __future__ import annotations

import hashlib
import http.client
import json
import sys
import threading
import zipfile
from http.server import ThreadingHTTPServer
from io import BytesIO
from pathlib import Path
from urllib.parse import quote

import pytest

sys.path.insert(0, str(Path(__file__).parent))
from test_audit import workbook  # noqa: E402

from py_tbparse import TwbParser, export_library, webgui  # noqa: E402

JSON_H = {"Content-Type": "application/json"}


@pytest.fixture
def server():
    webgui._STATE.update(parser=None, path=None, uploaded=False, report=None, audit=None, lib=None)
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
    status, data, headers = _req(addr, path, "POST", json.dumps(payload), JSON_H)
    return status, data, headers


def _postj(addr, path, payload):
    status, data, _ = _post(addr, path, payload)
    return status, json.loads(data)


def _upload(addr, raw: bytes, name="kpis.library.json", ctype="application/octet-stream"):
    status, data, _ = _req(addr, "/library/upload", "POST", raw, {"Content-Type": ctype, "X-Filename": quote(name)})
    return status, json.loads(data)


def _load(addr, path):
    assert _post(addr, "/load", {"path": path})[0] == 200


CALCS = [("[Calculation_1]", "Ratio", "[Sales] / [Profit]"),
         ("[Calculation_2]", "Double ratio", "[Calculation_1] * 2"),
         ("[Calculation_3]", "Total", "SUM([Sales])")]


@pytest.fixture
def source(tmp_path):
    return workbook(tmp_path, calcs=CALCS, params=[("[Parameter 1]", "Target")], name="source.twb")


@pytest.fixture
def clean_target(tmp_path):
    d = tmp_path / "t"
    d.mkdir()
    return workbook(d, calcs=[("[Calculation_9]", "Other", "[Sales] + 1")], name="target.twb")


@pytest.fixture
def big(tmp_path):
    return workbook(tmp_path, calcs=[(f"[Calculation_{i}]", f"Calc {i:03d}", f"[Sales] * {i}") for i in range(1, 131)],
                    name="big.twb")


def _library_of(addr, source, select):
    _load(addr, source)
    status, data, headers = _post(addr, "/library/export", {"select": select})
    assert status == 200, data
    return data, headers


def _sub(tmp_path):
    d = tmp_path / "target"
    d.mkdir(exist_ok=True)
    return d


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def test_everything_needs_a_workbook(server):
    assert _get(server, "/library/entries")[0] == 400
    assert _postj(server, "/library/export", {"select": ["x"]})[0] == 400
    assert _postj(server, "/library/plan", {})[0] == 400
    assert _postj(server, "/library/add", {})[0] == 400
    assert _upload(server, b"{}")[0] == 400


def test_entries_lists_calculations_and_parameters(server, source):
    _load(server, source)
    status, body = _get(server, "/library/entries")
    assert status == 200 and body["total"] == body["matching"] == 4
    assert {e["caption"] for e in body["entries"]} == {"Ratio", "Double ratio", "Total", "Target"}
    assert {e["kind"] for e in body["entries"]} == {"calc", "parameter"}
    assert set(body["entries"][0]) == {"name", "caption", "kind", "datatype", "folder", "formula", "truncated"}
    assert body["needs_datasource"] is False and body["names"] == []


def test_entries_filter_by_kind_and_text(server, source):
    _load(server, source)
    _, p = _get(server, "/library/entries?kind=parameter")
    assert [e["caption"] for e in p["entries"]] == ["Target"] and p["total"] == 4 and p["matching"] == 1
    _, t = _get(server, "/library/entries?q=double")
    assert [e["caption"] for e in t["entries"]] == ["Double ratio"]
    _, f = _get(server, "/library/entries?q=SUM%28")
    assert [e["caption"] for e in f["entries"]] == ["Total"]            # the formula is searched too
    assert _get(server, "/library/entries?kind=sheet")[0] == 400
    assert _get(server, "/library/entries?offset=x")[0] == 400


def test_entries_are_paged_and_capped_at_100(server, big):
    _load(server, big)
    _, first = _get(server, "/library/entries")
    assert len(first["entries"]) == 100 and first["matching"] == 130
    _, second = _get(server, "/library/entries?offset=100")
    assert len(second["entries"]) == 30
    _, huge = _get(server, "/library/entries?limit=100000")
    assert len(huge["entries"]) == 100 and huge["limit"] == 100            # the cap cannot be asked away
    _, names = _get(server, "/library/entries?names=1&q=Calc%2001")
    assert len(names["names"]) == names["matching"] == 10 and len(names["entries"]) == 10


def test_long_formulas_are_cut_in_the_list(server, tmp_path):
    long = "[Sales] + " + " + ".join(["1"] * 400)
    path = workbook(tmp_path, calcs=[("[Calculation_1]", "Long", long)], name="long.twb")
    _load(server, path)
    _, body = _get(server, "/library/entries")
    e = body["entries"][0]
    assert len(e["formula"]) == webgui._FORMULA_SHOWN and e["truncated"] is True


def test_export_is_a_library_file_with_the_dependencies(server, source):
    data, headers = _library_of(server, source, ["[Calculation_2]"])
    assert 'filename="source.library.json"' in headers["Content-Disposition"]
    assert headers["Content-Type"].startswith("application/json")
    lib = json.loads(data)
    assert lib["format"] == "py-tbparse-library"
    assert {e["caption"] for e in lib["entries"]} == {"Ratio", "Double ratio"}        # Double ratio uses Ratio


def test_export_without_dependencies_and_with_a_name(server, source):
    _load(server, source)
    status, data, headers = _post(server, "/library/export",
                                  {"select": ["[Calculation_2]"], "with_dependencies": False, "name": "My KPIs"})
    assert status == 200
    lib = json.loads(data)
    assert [e["caption"] for e in lib["entries"]] == ["Double ratio"] and lib["name"] == "My KPIs"
    assert "My_KPIs.library.json" in headers["Content-Disposition"]


@pytest.mark.parametrize("payload", [
    {}, {"select": []}, {"select": "x"}, {"select": [1]}, {"select": ["[Nope]"]}])
def test_export_needs_a_real_selection(server, source, payload):
    _load(server, source)
    status, body = _postj(server, "/library/export", payload)
    assert status == 400 and body["error"]


@pytest.mark.parametrize("key", ["path", "output_path", "output", "library", "mapping", "overwrite"])
def test_no_route_accepts_a_path_or_an_output(server, source, key):
    _load(server, source)
    for route in ("/library/export", "/library/plan", "/library/add"):
        status, body = _postj(server, route, {"select": ["[Calculation_1]"], key: "/tmp/x"})
        assert status == 400 and key in body["error"]


def test_a_library_file_is_checked_on_upload(server, source):
    _load(server, source)
    assert "not a library file" in _upload(server, b"not json")[1]["error"]
    assert "not a py-tbparse library" in _upload(server, b'{"format": "other"}')[1]["error"]
    assert "newer" in _upload(server, json.dumps({"format": "py-tbparse-library", "version": 99, "entries": [], "required": []}).encode())[1]["error"]
    assert "no 'entries' list" in _upload(server, json.dumps({"format": "py-tbparse-library", "version": 1}).encode())[1]["error"]
    assert _upload(server, b"{}", ctype="application/json")[0] == 415
    assert _get(server, "/library/state")[1]["library"] is None


def test_upload_has_a_size_limit(server, source, monkeypatch):
    _load(server, source)
    monkeypatch.setattr(webgui, "MAX_LIBRARY_BYTES", 100)
    status, body = _upload(server, b" " * 1000)
    assert status == 413 and "at most" in body["error"]


def test_plan_needs_a_library_first(server, source):
    _load(server, source)
    status, body = _postj(server, "/library/plan", {})
    assert status == 400 and "library file first" in body["error"]


def test_the_default_policy_is_fail_and_the_clash_report_is_whole(server, source, clean_target):
    data, _ = _library_of(server, source, ["[Calculation_2]", "[Parameter 1]"])
    _load(server, source)           # add the library to the workbook it came from, then to a clean one
    assert _upload(server, data)[0] == 200
    status, plan = _postj(server, "/library/plan", {})
    assert status == 200 and plan["policy"] == "fail"
    assert plan["blocked"] is None and plan["counts"].get("skip-identical") == 3 and plan["will_add"] == 0
    # a target that already has "Ratio" under another formula
    other = Path(clean_target).with_name("clash.twb")
    other.write_text(Path(source).read_text(encoding="utf-8").replace("[Sales] / [Profit]", "[Profit] / [Sales]"), encoding="utf-8")
    _load(server, str(other))
    assert _upload(server, data)[0] == 200
    status, plan = _postj(server, "/library/plan", {})
    assert status == 200 and plan["policy"] == "fail"
    assert plan["blocked"] and "Ratio" in plan["blocked"] and plan["will_add"] == 0
    assert plan["clash_count"] >= 1 and {c["action"] for c in plan["clashes"]} == {"add-renamed"}
    assert all(c["caption"] for c in plan["clashes"])
    status, plan = _postj(server, "/library/plan", {"on_clash": "rename"})
    assert plan["blocked"] is None and plan["will_add"] >= 1
    status, plan = _postj(server, "/library/plan", {"on_clash": "skip"})
    assert plan["blocked"] is None and plan["counts"].get("skip-clash", 0) >= 1
    assert _postj(server, "/library/plan", {"on_clash": "overwrite"})[0] == 400


def test_plan_rows_are_paged_and_capped(server, big, tmp_path):
    _load(server, big)
    status, data, _ = _post(server, "/library/export", {"select": [f"[Calculation_{i}]" for i in range(1, 131)]})
    assert status == 200
    empty = workbook(_sub(tmp_path), calcs=[], name="empty_target.twb")
    _load(server, empty)
    assert _upload(server, data)[0] == 200
    _, plan = _postj(server, "/library/plan", {})
    assert plan["blocked"] is None and plan["will_add"] == 130
    assert len(plan["rows"]) == 100 and plan["total"] > 130
    _, huge = _postj(server, "/library/plan", {"limit": 100000})
    assert len(huge["rows"]) == 100
    _, second = _postj(server, "/library/plan", {"offset": 100})
    assert len(second["rows"]) == plan["total"] - 100
    assert _postj(server, "/library/plan", {"offset": "x"})[0] == 400


def test_add_returns_a_new_workbook_and_writes_nothing(server, source, tmp_path):
    data, _ = _library_of(server, source, ["[Calculation_2]", "[Parameter 1]"])
    target = workbook(_sub(tmp_path), calcs=[], name="plain_target.twb")
    before = sorted(p.name for p in Path(target).parent.iterdir())
    digest = _sha(target)
    _load(server, target)
    assert _upload(server, data)[0] == 200
    status, wb, headers = _post(server, "/library/add", {})
    assert status == 200, wb
    assert 'filename="plain_target_library.twb"' in headers["Content-Disposition"]
    assert headers["X-Library-Added"] == "3"
    out = tmp_path / "out.twb"
    out.write_bytes(wb)
    captions = {e["caption"] for e in export_library(TwbParser(str(out)))["entries"]}
    assert {"Ratio", "Double ratio"} <= captions
    assert _sha(target) == digest                                                    # the open workbook is untouched
    assert sorted(p.name for p in Path(target).parent.iterdir()) == before          # and no file appeared beside it
    # the server still has the original open
    _, e = _get(server, "/library/entries")
    assert e["total"] == 0


def test_add_with_fail_stops_on_a_clash_and_sends_no_workbook(server, source, tmp_path):
    data, _ = _library_of(server, source, ["[Calculation_1]"])
    clash = tmp_path / "clash.twb"
    clash.write_text(Path(source).read_text(encoding="utf-8").replace("[Sales] / [Profit]", "[Profit] / [Sales]"), encoding="utf-8")
    _load(server, str(clash))
    assert _upload(server, data)[0] == 200
    status, body = _postj(server, "/library/add", {})
    assert status == 400 and "already in the target" in body["error"]
    status, wb, headers = _post(server, "/library/add", {"on_clash": "rename"})
    assert status == 200 and headers["X-Library-Added"] == "1" and wb.startswith(b"<?xml")


def test_add_to_a_twbx_keeps_the_other_members(server, source, tmp_path):
    data, _ = _library_of(server, source, ["[Calculation_1]"])
    tw = tmp_path / "pack.twbx"
    with zipfile.ZipFile(tw, "w") as z:
        z.write(workbook(_sub(tmp_path), calcs=[], name="inner.twb"), "inner.twb")
        z.writestr("Data/sales.csv", "Sales,Profit\n1,2\n")
    _load(server, str(tw))
    assert _upload(server, data)[0] == 200
    status, wb, headers = _post(server, "/library/add", {})
    assert status == 200 and headers["Content-Disposition"].count("pack_library.twbx") >= 1
    with zipfile.ZipFile(BytesIO(wb)) as z:
        assert z.read("Data/sales.csv").startswith(b"Sales,Profit")


def test_opening_another_workbook_drops_the_library(server, source, clean_target):
    data, _ = _library_of(server, source, ["[Calculation_1]"])
    assert _upload(server, data)[0] == 200
    assert _get(server, "/library/state")[1]["library"]["calcs"] == 1
    _load(server, clean_target)
    assert _get(server, "/library/state")[1]["library"] is None
    assert _postj(server, "/library/plan", {})[0] == 400


def test_clear_forgets_the_library(server, source):
    data, _ = _library_of(server, source, ["[Calculation_1]"])
    assert _upload(server, data)[0] == 200
    assert _postj(server, "/library/clear", {})[0] == 200
    assert _get(server, "/library/state")[1]["library"] is None


def test_several_datasources_need_a_choice(server, tmp_path):
    two = workbook(tmp_path, calcs=[("[Calculation_1]", "Ratio", "[Sales] / [Profit]")], name="two.twb")
    text = Path(two).read_text(encoding="utf-8")
    ds = text[text.index("<datasource name='ds1'"):text.index("<datasource name='Parameters'")]
    second = ds.replace("name='ds1'", "name='ds2'").replace("caption='Orders'", "caption='Returns'").replace("Ratio", "Other").replace("Calculation_1", "Calculation_7")
    Path(two).write_text(text.replace(ds, ds + second), encoding="utf-8")
    _load(server, two)
    _, body = _get(server, "/library/entries")
    assert body["needs_datasource"] is True and body["entries"] == []
    assert [d["caption"] for d in body["datasources"] if d["has_connection"]] == ["Orders", "Returns"]
    _, one = _get(server, "/library/entries?datasource=ds2")
    assert [e["caption"] for e in one["entries"]] == ["Other"]
    status, err = _postj(server, "/library/export", {"select": ["[Calculation_1]"]})
    assert status == 400 and "datasource" in err["error"]
    assert _post(server, "/library/export", {"select": ["[Calculation_7]"], "datasource": "ds2"})[0] == 200


def test_the_script_is_served_and_static_names_are_fixed(server):
    status, data, headers = _req(server, "/static/libraries.js")
    assert status == 200 and headers["Content-Type"].startswith("text/javascript") and b"LibrariesView" in data


# ---- server mode: no paths, one private library per browser ----

PUBLIC = "tbparse.example.com"


@pytest.fixture
def shared():
    saved = dict(webgui._CONFIG)
    webgui._STATE.base.update(parser=None, path=None, uploaded=False, report=None, audit=None, lib=None)
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


def _open_upload(addr, path):
    p = Path(path)
    status, _, cookie = _sreq(addr, "/upload", "POST", p.read_bytes(),
                              {"Content-Type": "application/octet-stream", "X-Filename": quote(p.name)})
    assert status == 200
    return cookie.split(";")[0]


def test_server_mode_has_no_paths_and_keeps_each_browsers_library_private(shared, source, clean_target):
    a = _open_upload(shared, source)
    b = _open_upload(shared, clean_target)
    status, raw, _ = _sreq(shared, "/library/export", "POST", json.dumps({"select": ["[Calculation_1]"]}), {"Content-Type": "application/json"}, a)
    assert status == 200
    status, raw2, _ = _sreq(shared, "/library/upload", "POST", raw, {"Content-Type": "application/octet-stream", "X-Filename": "k.library.json"}, a)
    assert status == 200
    assert json.loads(_sreq(shared, "/library/state", cookie=a)[1])["library"]["calcs"] == 1
    assert json.loads(_sreq(shared, "/library/state", cookie=b)[1])["library"] is None      # not shared
    status, raw3, _ = _sreq(shared, "/library/add", "POST", json.dumps({}), {"Content-Type": "application/json"}, a)
    assert status == 200 or b"already" in raw3          # the source already has it: identical, nothing to add
    status, body, _ = _sreq(shared, "/library/plan", "POST", json.dumps({"path": "/etc/passwd"}), {"Content-Type": "application/json"}, a)
    assert status == 400 and b"path" in body
