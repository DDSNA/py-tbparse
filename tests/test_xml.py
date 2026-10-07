import os
import zipfile

from py_tbparse import extract_twb_from_twbx, twbx_list
from py_tbparse._xml import twbx_extract_files


def test_twbx_list_lists_members(zip_twbx_path):
    man = twbx_list(zip_twbx_path)
    assert not man.empty
    assert set(["name", "size_bytes", "modified", "type"]) <= set(man.columns)
    assert (man["type"] == "workbook").sum() == 1


def test_extract_twb_from_twbx_picks_largest_twb(zip_twbx_path):
    info = extract_twb_from_twbx(zip_twbx_path, extract_all=False)
    assert info["twb_path"].endswith(".twb")
    assert os.path.exists(info["twb_path"])
    assert not info["manifest"].empty


def test_extract_twb_from_twbx_path_matches_traversal_sanitized_member(tmp_path):
    # zipfile.extract() strips '..'/absolute segments out of a member name
    # before writing, so os.path.join(extract_dir, name) can point
    # somewhere the file was never actually written -- extract_twb_from_twbx
    # must report wherever zipfile really put it, not a recomputed guess.
    twbx = tmp_path / "traversal.twbx"
    with zipfile.ZipFile(twbx, "w") as zf:
        zf.writestr("../../evil.twb", "<workbook/>")

    extract_dir = tmp_path / "out"
    info = extract_twb_from_twbx(str(twbx), extract_dir=str(extract_dir), extract_all=False)

    assert os.path.exists(info["twb_path"]), (
        f"reported twb_path does not exist: {info['twb_path']}"
    )
    # The sanitized destination must stay inside extract_dir.
    assert os.path.commonpath([os.path.abspath(info["twb_path"]), str(extract_dir)]) == str(
        extract_dir
    )


def test_twbx_extract_files_path_matches_traversal_sanitized_member(tmp_path):
    twbx = tmp_path / "traversal.twbx"
    with zipfile.ZipFile(twbx, "w") as zf:
        zf.writestr("../../sneaky.csv", "a,b\n1,2\n")

    exdir = tmp_path / "out"
    result = twbx_extract_files(str(twbx), exdir=str(exdir))

    assert len(result) == 1
    out_path = result.iloc[0]["out_path"]
    assert os.path.exists(out_path), f"reported out_path does not exist: {out_path}"
    assert os.path.commonpath([os.path.abspath(out_path), str(exdir)]) == str(exdir)


# --- zip bomb limits (#121) -------------------------------------------------

import pytest

from py_tbparse import TwbParser, _xml
from py_tbparse._xml import PackageTooLargeError, read_twb_from_twbx

_TWB = b'<?xml version="1.0"?><workbook><datasources/></workbook>'


def _pack(path, **members):
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("w.twb", _TWB)
        for name, data in members.items():
            zf.writestr(name, data)
    return str(path)


def test_a_member_over_the_cap_is_refused_before_it_is_read(tmp_path, monkeypatch):
    monkeypatch.setattr(_xml, "MAX_MEMBER_BYTES", 10_000)
    p = _pack(tmp_path / "big.twbx", **{"Data/x.csv": b"0" * 50_000})
    with pytest.raises(PackageTooLargeError, match="too large when unpacked"):
        read_twb_from_twbx(p)
    with pytest.raises(ValueError):
        TwbParser(p)


def test_the_total_and_the_ratio_are_capped(tmp_path, monkeypatch):
    p = _pack(tmp_path / "two.twbx", **{"a.csv": b"0" * 30_000, "b.csv": b"0" * 30_000})
    monkeypatch.setattr(_xml, "MAX_TOTAL_BYTES", 50_000)
    with pytest.raises(PackageTooLargeError, match="in all"):
        read_twb_from_twbx(p)
    monkeypatch.setattr(_xml, "MAX_TOTAL_BYTES", 10**9)
    monkeypatch.setattr(_xml, "_RATIO_FLOOR", 1000)
    monkeypatch.setattr(_xml, "MAX_RATIO", 10)
    with pytest.raises(PackageTooLargeError, match="compressed more than"):
        read_twb_from_twbx(p)


def test_a_normal_package_is_untouched(zip_twbx_path):
    assert not read_twb_from_twbx(zip_twbx_path)["manifest"].empty


def test_a_server_upload_of_a_bomb_is_a_clean_400(tmp_path, monkeypatch):
    import http.client
    import threading
    from http.server import ThreadingHTTPServer

    from py_tbparse import webgui

    monkeypatch.setattr(_xml, "MAX_MEMBER_BYTES", 10_000)
    body = open(_pack(tmp_path / "bomb.twbx", **{"Data/x.csv": b"0" * 50_000}), "rb").read()
    webgui._STATE.update(parser=None, path=None, uploaded=False)
    srv = ThreadingHTTPServer(("127.0.0.1", 0), webgui.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        conn = http.client.HTTPConnection(*srv.server_address, timeout=10)
        conn.request("POST", "/upload", body=body, headers={
            "Content-Type": "application/octet-stream", "X-Filename": "bomb.twbx",
            "Content-Length": str(len(body))})
        r = conn.getresponse()
        data = r.read().decode()
        conn.close()
    finally:
        srv.shutdown()
        webgui._clear_upload()
    assert r.status == 400 and "too large when unpacked" in data
