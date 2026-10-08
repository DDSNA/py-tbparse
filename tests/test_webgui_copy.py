"""The Slice and copy view's endpoints: GET /copy/dashboards, /copy/sheets, /copy/state, POST /copy/upload,
/copy/slice-plan, /copy/slice-download, /copy/plan, /copy/download and /copy/clear. Nothing here takes a path, and
nothing is written next to a workbook."""

from __future__ import annotations

import hashlib
import http.client
import io
import json
import sys
import threading
import zipfile
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.parse import quote

import pytest
from lxml import etree

sys.path.insert(0, str(Path(__file__).parent))
from copy_fixtures import make_many, make_source, make_target  # noqa: E402

from py_tbparse import webgui  # noqa: E402

JSON_H = {"Content-Type": "application/json"}


@pytest.fixture
def server():
    webgui._cpy_clear()
    webgui._STATE.update(parser=None, path=None, uploaded=False, report=None, audit=None, lib=None, sty=None)
    srv = ThreadingHTTPServer(("127.0.0.1", 0), webgui.Handler)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    try:
        yield srv.server_address
    finally:
        srv.shutdown()
        thread.join(timeout=2)
        webgui._cpy_clear()


def _req(addr, path, method="GET", body=None, headers=None):
    conn = http.client.HTTPConnection(*addr, timeout=20)
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
    status, data, _ = _req(addr, "/copy/upload", "POST", raw, {"Content-Type": ctype, "X-Filename": quote(name)})
    return status, json.loads(data)


def _load(addr, path):
    assert _post(addr, "/load", {"path": str(path)})[0] == 200


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _doc(data: bytes):
    return etree.fromstring(data)


@pytest.fixture
def src(tmp_path):
    d = tmp_path / "s"
    d.mkdir()
    return make_source(d)


@pytest.fixture
def tgt(tmp_path):
    d = tmp_path / "t"
    d.mkdir()
    return make_target(d)


def _with_target(server, src, tgt):
    _load(server, src)
    status, d = _upload(server, Path(tgt).read_bytes(), "target.twb")
    assert status == 200, d
    return d["target"]


def test_everything_needs_a_workbook(server):
    assert _get(server, "/copy/dashboards")[0] == 400
    assert _get(server, "/copy/sheets")[0] == 400
    assert _post(server, "/copy/slice-plan", {"dashboards": ["D1"]})[0] == 400
    assert _post(server, "/copy/plan", {"sheets": ["S1"]})[0] == 400
    assert _req(server, "/copy/upload", "POST", b"<workbook/>", {"Content-Type": "application/octet-stream", "X-Filename": "a.twb"})[0] == 400


def test_dashboards_and_sheets_are_listed(server, src):
    _load(server, src)
    _, d = _get(server, "/copy/dashboards")
    assert d["total"] == 3 and [r["name"] for r in d["rows"]] == ["D1", "D2", "D3"]
    assert [r["n_sheets"] for r in d["rows"]] == [2, 3, 1]
    assert d["rows"][0]["kind"] == "dashboard"
    _, d = _get(server, "/copy/dashboards?q=d2&names=1")
    assert d["matching"] == 1 and d["names"] == ["D2"]
    _, d = _get(server, "/copy/sheets?names=1")
    assert d["total"] == 7 and d["names"][:3] == ["S1", "S2", "S3"]
    assert d["rows"][0] == {"name": "S1", "datasources": ["ds1"]}
    assert [r["datasources"] for r in _get(server, "/copy/sheets?q=S4")[1]["rows"]] == [["ds2"]]


def test_lists_are_paged_and_capped_at_100(server, tmp_path):
    _load(server, make_many(tmp_path))
    for kind in ("dashboards", "sheets"):
        _, d = _get(server, f"/copy/{kind}?limit=5000")
        assert d["total"] == 250 and len(d["rows"]) == 100 and d["limit"] == 100
        assert len(_get(server, f"/copy/{kind}?offset=200")[1]["rows"]) == 50
        assert len(_get(server, f"/copy/{kind}?names=1")[1]["names"]) == 250
        assert _get(server, f"/copy/{kind}?offset=x")[0] == 400


def test_slice_plan_lists_what_stays_and_goes(server, src):
    _load(server, src)
    status, d = _postj(server, "/copy/slice-plan", {"dashboards": ["D1"]})
    assert status == 200 and "error" not in d
    assert d["kept_dashboards"] == 1 and d["removed_dashboards"] == 2
    assert d["kept_sheets"] == 3                         # S1, S2 and the tooltip sheet Tip
    rows = {(r["kind"], r["name"]): r["action"] for r in d["rows"]}
    assert rows[("Dashboard", "D1")] == "keep" and rows[("Dashboard", "D2")] == "remove" and rows[("Worksheet", "S3")] == "remove"
    assert d["total"] == len(d["rows"]) == 10
    assert d["action_count"] == len(d["actions"]) >= 1
    assert d["integrity_count"] == 0


def test_slice_plan_pages_its_rows(server, tmp_path):
    _load(server, make_many(tmp_path))
    status, d = _postj(server, "/copy/slice-plan", {"dashboards": [f"Dash {i:03d}" for i in range(250)][:3]})
    assert status == 200 and d["total"] == 500          # 250 dashboards and 250 worksheets, each kept or removed
    assert len(d["rows"]) == 100
    _, d2 = _postj(server, "/copy/slice-plan", {"dashboards": ["Dash 000"], "offset": 400})
    assert len(d2["rows"]) == d2["total"] - 400


def test_slice_plan_errors_are_messages_not_crashes(server, src):
    _load(server, src)
    _, d = _postj(server, "/copy/slice-plan", {"dashboards": ["Nope"]})
    assert "unknown dashboard" in d["error"]
    _, d = _postj(server, "/copy/slice-plan", {"dashboards": ["D1"], "strict": True})
    assert "--strict" in d["error"]
    assert _post(server, "/copy/slice-plan", {"dashboards": []})[0] == 400
    assert _post(server, "/copy/slice-plan", {"dashboards": "D1"})[0] == 400
    assert _post(server, "/copy/slice-plan", {"dashboards": ["D1"], "strict": "yes"})[0] == 400


def test_slice_download_is_the_workbook_with_only_those_dashboards(server, src):
    before = _sha(src)
    _load(server, src)
    status, data, headers = _post(server, "/copy/slice-download", {"dashboards": ["D2"]})
    assert status == 200 and 'filename="source_sliced.twb"' in headers["Content-Disposition"]
    assert headers["X-Copy-Count"] == "1"
    doc = _doc(data)
    assert doc.xpath("/workbook/dashboards/dashboard/@name") == ["D2"]
    assert doc.xpath("/workbook/worksheets/worksheet/@name") == ["S3", "S4", "HiddenOnD2"]
    assert _sha(src) == before
    assert sorted(p.name for p in Path(src).parent.iterdir()) == ["source.twb"]
    status, _, _ = _post(server, "/copy/slice-download", {"dashboards": ["Nope"]})
    assert status == 400


def test_slice_download_of_a_twbx_keeps_the_package(server, tmp_path):
    from py_tbparse import TwbParser
    src = make_source(tmp_path)
    twbx = tmp_path / "pack.twbx"
    with zipfile.ZipFile(twbx, "w") as z:
        z.write(src, "pack.twb")
        z.writestr("Data/a.csv", "Sales\n1\n")
    _load(server, twbx)
    status, data, headers = _post(server, "/copy/slice-download", {"dashboards": ["D1"]})
    assert status == 200 and headers["Content-Disposition"].startswith('attachment; filename="pack_sliced.twbx"')
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        assert "Data/a.csv" in z.namelist()


def test_target_upload_checks_type_and_content(server, src, tgt):
    _load(server, src)
    assert _upload(server, b"x", "t.twb", "application/json")[0] == 415
    assert _upload(server, b"hello", "t.txt")[0] == 400
    assert _upload(server, b"PK\x03\x04junk", "t.twb")[0] == 400           # a .twb is XML
    assert _upload(server, b"<workbook", "t.twb")[0] == 400                # not parsable
    assert _get(server, "/copy/state")[1]["target"] is None
    summary = _with_target(server, src, tgt)
    assert summary["file"] == "target.twb" and summary["worksheets"] == 3 and summary["dashboards"] == 1
    assert _get(server, "/copy/state")[1]["target"]["file"] == "target.twb"


def test_plan_defaults_to_fail_lists_the_clash_and_blocks(server, src, tgt):
    _with_target(server, src, tgt)
    status, d = _postj(server, "/copy/plan", {"sheets": ["S3", "S1"]})
    assert status == 200 and d["policy"] == "fail" and d["blocked"] is True
    assert "already a sheet or dashboard of the target" in d["blocked_reason"]
    by = {r["sheet"]: r for r in d["rows"]}
    assert set(by) == {"S3", "S1"} and by["S3"]["new_name"] == "S3 (2)"          # every clash listed, as in a rename run
    assert d["will_copy"] == 0
    assert str(Path(tgt).parent) not in json.dumps(d)


def test_rename_and_skip_and_the_dropped_things(server, src, tgt):
    _with_target(server, src, tgt)
    _, d = _postj(server, "/copy/plan", {"sheets": ["S1"]})
    assert d["blocked"] is False and d["copied"] == 1 and d["will_copy"] == 1
    assert d["rows"][0]["status"] == "copy" and d["rows"][0]["datasource"] == "ds1"
    assert any("action filter" in x for x in d["rows"][0]["dropped"])
    assert [(r["name"], r["action"]) for r in d["library"]] == [("[Calc A]", "add")]
    _, d = _postj(server, "/copy/plan", {"sheets": ["S3"], "on_clash": "rename"})
    assert d["blocked"] is False and d["rows"][0]["new_name"] == "S3 (2)"
    _, d = _postj(server, "/copy/plan", {"sheets": ["S3"], "on_clash": "skip"})
    assert d["rows"][0]["status"] == "skipped" and d["will_copy"] == 0 and d["skipped"] == 1
    _, d = _postj(server, "/copy/plan", {"sheets": ["S1"], "strict": True})
    assert d["blocked"] is True and "--strict" in d["blocked_reason"] and d["will_copy"] == 0
    assert d["rows"][0]["status"] == "copy"            # the rows are still listed


def test_refused_sheets_are_listed_with_the_reason(server, src, tgt):
    _with_target(server, src, tgt)
    _, d = _postj(server, "/copy/plan", {"sheets": ["S1", "Lonely"]})   # Lonely is in no dashboard but exists in the source
    by = {r["sheet"]: r for r in d["rows"]}
    assert by["S1"]["status"] == "copy"
    assert d["copied"] + d["refused"] + d["skipped"] == 2


def test_a_sheet_whose_datasource_the_target_lacks_is_refused_and_named(server, src, tmp_path):
    from test_slice import DS1, ws
    other = DS1.replace("a.csv", "elsewhere.csv")
    path = tmp_path / "other.twb"
    path.write_text(f"<?xml version='1.0' encoding='utf-8'?><workbook version='18.1'><datasources>{other}</datasources>"
                    f"<worksheets>{ws('Mine')}</worksheets></workbook>", encoding="utf-8")
    _load(server, src)
    assert _upload(server, path.read_bytes(), "other.twb")[0] == 200
    _, d = _postj(server, "/copy/plan", {"sheets": ["S1", "S2"]})
    assert d["refused"] == 2 and d["copied"] == 0 and d["will_copy"] == 0
    assert all(r["status"] == "refused" and r["reason"] for r in d["rows"])
    assert str(tmp_path) not in json.dumps(d)
    status, body, _ = _post(server, "/copy/download", {"sheets": ["S1"]})
    assert status == 400 and "nothing was made" in json.loads(body)["error"]


def test_the_plan_needs_a_target_and_names_and_a_known_policy(server, src, tgt):
    _load(server, src)
    assert _post(server, "/copy/plan", {"sheets": ["S1"]})[0] == 400
    _with_target(server, src, tgt)
    assert _post(server, "/copy/plan", {"sheets": []})[0] == 400
    assert _post(server, "/copy/plan", {"sheets": ["S1"], "on_clash": "overwrite"})[0] == 400
    assert _post(server, "/copy/plan", {"sheets": ["S1"], "overwrite": True})[0] == 400      # no overwrite option
    assert _post(server, "/copy/plan", {"sheets": ["S1"], "path": "/etc/passwd"})[0] == 400
    assert _post(server, "/copy/download", {"sheets": ["S1"], "output_path": "x.twb"})[0] == 400


def test_download_makes_the_copy_and_changes_neither_input(server, src, tgt):
    before = (_sha(src), _sha(tgt))
    _with_target(server, src, tgt)
    status, data, headers = _post(server, "/copy/download", {"sheets": ["S1"]})
    assert status == 200 and 'filename="target_sheetcopy.twb"' in headers["Content-Disposition"]
    assert headers["X-Copy-Count"] == "1"
    doc = _doc(data)
    assert "S1" in doc.xpath("/workbook/worksheets/worksheet/@name")
    assert "[Calc A]" in doc.xpath("//datasource[@name='ds1']/column/@name")
    assert (_sha(src), _sha(tgt)) == before
    assert sorted(p.name for p in Path(tgt).parent.iterdir()) == ["_for_target.twb", "target.twb"]
    # the stop policy stops the download too, with the clash named
    status, body, _ = _post(server, "/copy/download", {"sheets": ["S3"]})
    assert status == 400 and "on_clash='fail'" in json.loads(body)["error"]
    status, data, _ = _post(server, "/copy/download", {"sheets": ["S3"], "on_clash": "rename"})
    assert status == 200 and "S3 (2)" in _doc(data).xpath("/workbook/worksheets/worksheet/@name")
    status, body, _ = _post(server, "/copy/download", {"sheets": ["S3"], "on_clash": "skip"})
    assert status == 400 and "nothing was made" in json.loads(body)["error"]


def test_the_target_folder_goes_when_replaced_cleared_or_another_workbook_opens(server, src, tgt):
    _with_target(server, src, tgt)
    first = webgui._STATE["cpy"]["dir"]
    assert Path(first).is_dir()
    _upload(server, Path(tgt).read_bytes(), "second.twb")
    assert not Path(first).exists()
    second = webgui._STATE["cpy"]["dir"]
    assert _postj(server, "/copy/clear", {})[1] == {"ok": True}
    assert not Path(second).exists() and _get(server, "/copy/state")[1]["target"] is None
    _upload(server, Path(tgt).read_bytes(), "third.twb")
    third = webgui._STATE["cpy"]["dir"]
    _load(server, src)
    assert not Path(third).exists() and _get(server, "/copy/state")[1]["target"] is None


def test_the_script_is_served(server):
    status, data, headers = _req(server, "/static/copy.js")
    assert status == 200 and headers["Content-Type"].startswith("text/javascript") and b"CopyView" in data


# ---- server mode ----

PUBLIC = "tbparse.example.com"


@pytest.fixture
def shared():
    saved = dict(webgui._CONFIG)
    webgui._STATE.base.update(parser=None, path=None, uploaded=False, report=None, audit=None, lib=None, sty=None, cpy=None)
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
    conn = http.client.HTTPConnection(*addr, timeout=20)
    conn.request(method, path, body=body, headers=hdrs)
    r = conn.getresponse()
    data = r.read()
    out = (r.status, data, dict(r.getheaders()))
    conn.close()
    return out


def test_server_mode_works_without_paths_and_keeps_each_browsers_target_private(shared, src, tgt):
    s1, body, h = _sreq(shared, "/upload", "POST", Path(src).read_bytes(),
                        {"Content-Type": "application/octet-stream", "X-Filename": "source.twb"})
    assert s1 == 200
    c1 = h["Set-Cookie"].split(";")[0]
    s2, body, h = _sreq(shared, "/copy/upload", "POST", Path(tgt).read_bytes(),
                        {"Content-Type": "application/octet-stream", "X-Filename": "target.twb"}, cookie=c1)
    assert s2 == 200, body
    s3, body, _ = _sreq(shared, "/copy/plan", "POST", json.dumps({"sheets": ["S1"]}), JSON_H, cookie=c1)
    assert s3 == 200 and json.loads(body)["will_copy"] == 1
    assert str(Path(tgt).parent) not in body.decode()
    # a second browser has neither the workbook nor the target
    s4, body, h2 = _sreq(shared, "/copy/state")
    assert s4 == 200 and json.loads(body)["target"] is None
    # a path in the body is refused by name
    s5, body, _ = _sreq(shared, "/copy/plan", "POST", json.dumps({"sheets": ["S1"], "path": "/tmp/x.twb"}), JSON_H, cookie=c1)
    assert s5 == 400 and "path" in json.loads(body)["error"]


def test_dashboard_sheet_count_reads_worksheet_attribute(server):
    # the demo workbook writes <zone worksheet="..."> with no name; the count used to be 0 for every dashboard
    demo = Path(__file__).parent.parent / "docs" / "demo" / "coffee-shop.twb"
    _load(server, demo)
    _, d = _get(server, "/copy/dashboards")
    assert {r["name"]: r["n_sheets"] for r in d["rows"]} == {"Product Review": 2, "Weekly Overview": 2}
