"""Rename review: leaving suggested renames out. The server honours the excluded set for Create and Download."""

import json
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from py_tbparse import TwbParser, webgui
from py_tbparse.rename import (
    build_renamed_workbook,
    rename_id,
    select_renames,
    suggest_renames,
)
from test_rename_all import WORKBOOK


@pytest.fixture
def report(tmp_path):
    path = tmp_path / "report.twb"
    path.write_text(WORKBOOK, encoding="utf-8")
    return path


@pytest.fixture
def server():
    webgui._STATE["parser"] = None
    webgui._STATE["path"] = None
    srv = ThreadingHTTPServer(("127.0.0.1", 0), webgui.Handler)
    host, port = srv.server_address
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://{host}:{port}"
    finally:
        srv.shutdown()
        thread.join(timeout=2)


def _post(base, path, payload, raw=False):
    req = urllib.request.Request(
        base + path, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"}, method="POST"
    )
    try:
        with urllib.request.urlopen(req) as r:
            body = r.read()
            return r.status, (body if raw else json.loads(body))
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def _sheet_id(df, name):
    row = df[(df["kind"] == "worksheet") & (df["name"] == name)].iloc[0]
    return rename_id("worksheet", row["datasource"], name)


def _build(parser, df):
    report = {}
    data = build_renamed_workbook(parser, df, report)
    return data.decode("utf-8"), report


# --- the library ------------------------------------------------------------------------------


def test_excluded_sheet_keeps_its_name_everywhere(report):
    parser = TwbParser(str(report))
    df = suggest_renames(parser)
    left_out = _sheet_id(df, "sales by region")
    text, rep = _build(parser, select_renames(df, [left_out]))
    # every reference to the left-out sheet still points at it, so the workbook stays consistent
    assert "Sales By Region" not in text
    for needle in ("<worksheet name='sales by region'", "worksheet='sales by region'", "name='sales by region'"):
        assert needle in text.replace('"', "'")
    # the others were renamed everywhere
    assert "Order Details" in text and "ORDER_DETAILS" not in text
    assert "My Dashboard" in text and "my dashboard" not in text
    assert rep["skipped"] == 0
    # the right number was applied
    full = _build(parser, df)[1]["applied"]
    assert rep["applied"] == full - 1


def test_excluded_field_is_left_without_a_caption_change(report):
    parser = TwbParser(str(report))
    df = suggest_renames(parser)
    field = df[(df["kind"] == "field")].iloc[0]
    left_out = rename_id("field", field["datasource"], field["name"])
    text, _ = _build(parser, select_renames(df, [left_out]))
    assert "caption='ORDER_ID'" in text.replace('"', "'")


def test_output_reparses(report, tmp_path):
    parser = TwbParser(str(report))
    df = suggest_renames(parser)
    data, _ = _build(parser, select_renames(df, [_sheet_id(df, "ORDER_DETAILS")]))
    out = tmp_path / "out.twb"
    out.write_text(data, encoding="utf-8")
    again = TwbParser(str(out))
    names = set(again.xml_doc.xpath("/workbook/worksheets/worksheet/@name"))
    assert names == {"Sales By Region", "ORDER_DETAILS"}


def test_unknown_id_is_rejected(report):
    df = suggest_renames(TwbParser(str(report)))
    with pytest.raises(ValueError, match="not one of the suggested renames"):
        select_renames(df, ["worksheet\x1f\x1fno such sheet"])


def test_an_unchanged_row_is_not_a_known_id(wenjie_path):
    # only renames that would be applied can be left out; naming anything else is a mistake worth reporting
    from py_tbparse import suggest_field_renames

    df = suggest_field_renames(TwbParser(str(wenjie_path)))
    unchanged = df[~df["changed"].astype(bool)]
    assert not unchanged.empty
    row = unchanged.iloc[0]
    with pytest.raises(ValueError, match="not one of the suggested renames"):
        select_renames(df, [rename_id(None, row["datasource"], row["name"])])


def test_leaving_everything_out_is_refused(report):
    df = suggest_renames(TwbParser(str(report)))
    everything = [rename_id(r["kind"], r["datasource"], r["name"]) for r in df.to_dict("records") if r["changed"]]
    with pytest.raises(ValueError, match="Every rename is left out"):
        select_renames(df, everything)


def test_exclusions_must_be_a_list_of_strings(report):
    df = suggest_renames(TwbParser(str(report)))
    for bad in ("worksheet", {"a": 1}, [1], [None], [["a"]]):
        with pytest.raises(ValueError):
            select_renames(df, bad)


def test_no_exclusions_changes_nothing(report):
    df = suggest_renames(TwbParser(str(report)))
    assert select_renames(df, None).equals(df)
    assert select_renames(df, []).equals(df)


def test_duplicate_ids_are_fine(report):
    df = suggest_renames(TwbParser(str(report)))
    one = _sheet_id(df, "ORDER_DETAILS")
    assert len(select_renames(df, [one, one])) == len(select_renames(df, [one]))


# --- the server: Create and Download -------------------------------------------------------------


def _kind_all(**extra):
    return {"kinds": "all", **extra}


def test_create_honours_the_excluded_set(server, report, tmp_path):
    assert _post(server, "/load", {"path": str(report)})[0] == 200
    parser = TwbParser(str(report))
    df = suggest_renames(parser)
    left_out = _sheet_id(df, "sales by region")
    status, made = _post(server, "/create-workbook", _kind_all(exclude=[left_out]))
    assert status == 200
    full = _build(parser, df)[1]["applied"]
    assert made["renamed"] == full - 1
    text = (tmp_path / "report_renamed.twb").read_text(encoding="utf-8")
    assert "Sales By Region" not in text and "sales by region" in text
    assert "My Dashboard" in text
    TwbParser(str(tmp_path / "report_renamed.twb"))  # re-parses


def test_download_post_honours_the_excluded_set(server, report, tmp_path):
    assert _post(server, "/load", {"path": str(report)})[0] == 200
    df = suggest_renames(TwbParser(str(report)))
    status, data = _post(server, "/download-workbook", _kind_all(exclude=[_sheet_id(df, "ORDER_DETAILS")]), raw=True)
    assert status == 200
    text = data.decode()
    assert "ORDER_DETAILS" in text and "Order Details" not in text and "Sales By Region" in text
    assert not (tmp_path / "report_renamed.twb").exists()  # a download writes nothing


def test_download_get_honours_the_excluded_set(server, report):
    from urllib.parse import quote

    assert _post(server, "/load", {"path": str(report)})[0] == 200
    df = suggest_renames(TwbParser(str(report)))
    q = "&exclude=" + quote(_sheet_id(df, "ORDER_DETAILS"))
    with urllib.request.urlopen(server + "/download-workbook?kinds=all" + q) as r:
        text = r.read().decode()
    assert "ORDER_DETAILS" in text and "Sales By Region" in text


def test_server_rejects_unknown_id(server, report, tmp_path):
    assert _post(server, "/load", {"path": str(report)})[0] == 200
    status, err = _post(server, "/create-workbook", _kind_all(exclude=["worksheet\x1f\x1fnope"]))
    assert status == 400 and "not one of the suggested renames" in err["error"]
    assert not (tmp_path / "report_renamed.twb").exists()
    status, err = _post(server, "/download-workbook", _kind_all(exclude=["worksheet\x1f\x1fnope"]))
    assert status == 400


def test_server_refuses_an_empty_selection_with_a_message(server, report, tmp_path):
    assert _post(server, "/load", {"path": str(report)})[0] == 200
    df = suggest_renames(TwbParser(str(report)))
    everything = [rename_id(r["kind"], r["datasource"], r["name"]) for r in df.to_dict("records") if r["changed"]]
    for route in ("/create-workbook", "/download-workbook"):
        status, err = _post(server, route, _kind_all(exclude=everything))
        assert status == 400
        assert "Tick at least one rename" in err["error"]
    assert not (tmp_path / "report_renamed.twb").exists()


def test_malformed_exclude_is_a_400(server, report):
    assert _post(server, "/load", {"path": str(report)})[0] == 200
    for bad in ("worksheet", 3, [1], {"a": 1}):
        status, err = _post(server, "/create-workbook", _kind_all(exclude=bad))
        assert status == 400 and "exclude" in err["error"]


def test_table_endpoint_ignores_exclude(server, report):
    from urllib.parse import quote

    assert _post(server, "/load", {"path": str(report)})[0] == 200
    with urllib.request.urlopen(server + "/table?name=field-renames&kinds=all&exclude=" + quote("x\x1fy\x1fz")) as r:
        assert r.status == 200  # the preview always lists everything; exclusion is only for the workbook


def test_leaving_out_cannot_make_two_sheets_share_a_name():
    import pandas as pd

    from py_tbparse.rename import OBJECT_COLUMNS

    # a hand-made frame: A -> B while B -> C; leaving B out would make A's new name clash with B
    rows = [
        ["worksheet", "", "A", "A", "B", "normalized", None, True],
        ["worksheet", "", "B", "B", "C", "normalized", None, True],
        ["worksheet", "", "D", "D", "E", "normalized", None, True],
    ]
    df = pd.DataFrame(rows, columns=OBJECT_COLUMNS)
    with pytest.raises(ValueError, match="two sheets or dashboards"):
        select_renames(df, [rename_id("worksheet", "", "B")])
    assert len(select_renames(df, [rename_id("worksheet", "", "D")])) == 2
