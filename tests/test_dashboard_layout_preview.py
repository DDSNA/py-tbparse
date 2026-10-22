"""GET /dashboard-layout (#84, WP1 of docs/plan-84-layout-preview.md): the zones of one dashboard with labels.
No browser. The same server fixture and workbook as tests/test_dashboard_cards.py."""

from __future__ import annotations

import http.client
import json
import sys
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlencode

import pytest

sys.path.insert(0, str(Path(__file__).parent))
from cards_fixtures import cards_workbook  # noqa: E402
from conftest import xml_from_string  # noqa: E402

from py_tbparse import webgui  # noqa: E402
from py_tbparse.dashboards import dashboard_layout, dashboard_zone_labels  # noqa: E402

ODD_NAME = "Ünï \"quoted\" & <b>bold</b> 日本語 'x'"
UNPLACED = f"""<?xml version='1.0' encoding='utf-8' ?>
<workbook version='18.1'>
  <worksheets><worksheet name='Sheet 1'><table><view /></table></worksheet></worksheets>
  <dashboards>
    <dashboard name='Half placed'>
      <zones>
        <zone id='1' type-v2='layout-flow' param='vert' x='0' y='0' w='100000' h='100000'>
          <zone id='2' name='Sheet 1' x='0' y='0' w='50000' h='50000'/>
          <zone id='3' name='Sheet 1'/>
          <zone id='4' type-v2='text' x='0' y='50000' w='0' h='5000'/>
          <zone id='5' type-v2='web' x='50000' y='0' w='-10' h='5000'/>
        </zone>
      </zones>
    </dashboard>
    <dashboard name='{ODD_NAME.replace("&", "&amp;").replace("<", "&lt;").replace("'", "&apos;")}'>
      <zones><zone id='1' name='Sheet 1' x='0' y='0' w='100' h='100'/></zones>
    </dashboard>
  </dashboards>
</workbook>
"""


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


def _request(addr, method, path, body=None):
    conn = http.client.HTTPConnection(*addr, timeout=10)
    conn.request(method, path, body=json.dumps(body) if body is not None else None,
                 headers={"Content-Type": "application/json"})
    r = conn.getresponse()
    raw = r.read()
    conn.close()
    return r.status, json.loads(raw), raw


def _open(addr, tmp_path, text=None, **kw):
    path = tmp_path / "wb.twb"
    path.write_text(text if text is not None else cards_workbook(**kw), encoding="utf-8")
    assert _request(addr, "POST", "/load", {"path": str(path)})[0] == 200


def _layout(addr, *names):
    status, body, _ = _request(addr, "GET", "/dashboard-layout?" + urlencode([("name", n) for n in names]))
    return status, body


def test_a_layout_needs_a_workbook(server):
    status, body = _layout(server, "x")
    assert status == 400 and "No workbook" in body["error"]


def test_a_mixed_dashboard_has_every_zone_with_kind_position_and_label(server, tmp_path):
    _open(server, tmp_path)
    status, body = _layout(server, "Mixed 'one'")
    assert status == 200
    assert body["name"] == "Mixed 'one'" and body["total"] == 7 and body["unplaced"] == 0 and body["unplaced_zones"] == []
    assert body["zones"] == [
        ["bitmap", 0, 0, 12000, 8000, "", "2"],
        ["text", 12000, 0, 88000, 8000, "", "3"],
        ["sheet", 0, 8000, 60000, 52000, "Sheet 1", "4"],
        ["sheet", 60000, 8000, 40000, 52000, "Sheet 2", "5"],
        ["filter", 0, 60000, 25000, 40000, "Region", "6"],       # the field, not the sheet it sits on
        ["param", 25000, 60000, 25000, 40000, "Top N", "7"],     # the parameter's caption
        ["web", 50000, 60000, 50000, 40000, "", "8"],
    ]
    assert (body["width"], body["height"], body["cap"]) == (100000, 100000, 200)
    assert "99" not in {z[6] for z in body["zones"]}             # the phone layout is left out


def test_labels_follow_the_rows_of_dashboard_layout():
    doc = xml_from_string(cards_workbook())
    df = dashboard_layout(doc, "Mixed 'one'")
    labels = dashboard_zone_labels(doc, "Mixed 'one'")
    assert len(labels) == len(df)
    assert labels == ["", "", "", "Sheet 1", "Sheet 2", "Region", "Top N", ""]
    assert dashboard_zone_labels(doc, "Nope") == []


def test_the_cap_keeps_the_largest_zones_in_layout_order(server, tmp_path):
    _open(server, tmp_path, many_zones=250)
    status, body = _layout(server, "Many zones")
    assert status == 200
    assert body["total"] == 250 and len(body["zones"]) == webgui.PREVIEW_ZONES_MAX == body["cap"] == 200
    # the 50 smallest are the first 50 of the fixture (sizes grow with the index); the rest keep layout order
    assert body["zones"][0][3] == 1000 + 50 * 10
    assert [z[6] for z in body["zones"]] == [str(100 + i) for i in range(50, 250)]
    assert body["zones"] == sorted(body["zones"], key=lambda z: z[3])
    assert body["zones"][0][5] == "Sheet 3"                      # 50 % 3 + 1


def test_under_the_cap_every_zone_is_returned(server, tmp_path):
    _open(server, tmp_path, many_zones=60)
    body = _layout(server, "Many zones")[1]
    assert body["total"] == 60 and len(body["zones"]) == 60


def test_zones_without_a_usable_position_are_counted_and_named_not_drawn(server, tmp_path):
    _open(server, tmp_path, text=UNPLACED)
    body = _layout(server, "Half placed")[1]
    assert body["total"] == 1 and body["zones"] == [["sheet", 0, 0, 50000, 50000, "Sheet 1", "2"]]
    assert (body["width"], body["height"]) == (50000, 50000)
    assert body["unplaced"] == 3
    assert body["unplaced_zones"] == [["sheet", "Sheet 1", "3"], ["text", "", "4"], ["web", "", "5"]]


def test_a_dashboard_with_no_stored_positions_has_total_zero(server, tmp_path):
    _open(server, tmp_path)
    body = _layout(server, "No positions")[1]
    # its only zone is a layout container, which is never counted
    assert (body["total"], body["zones"], body["unplaced"], body["width"], body["height"]) == (0, [], 0, 0, 0)


def test_an_unknown_name_is_404_and_none_or_several_names_are_400(server, tmp_path):
    _open(server, tmp_path)
    status, body = _layout(server, "Not there")
    assert status == 404 and "No dashboard" in body["error"]
    assert "Not there" not in body["error"]                      # the answer does not echo what was asked
    assert _layout(server)[0] == 400
    assert _layout(server, "")[0] == 400
    status, body = _layout(server, "Mixed 'one'", "Many zones")
    assert status == 400 and "exactly one" in body["error"]


def test_a_key_error_while_reading_a_known_dashboard_is_a_500_not_a_404(server, tmp_path, monkeypatch):
    _open(server, tmp_path)

    def broken(*args, **kw):
        raise KeyError("some column")

    monkeypatch.setattr(webgui, "_layout_zones", broken)
    status, body = _layout(server, "Many zones")
    assert status == 500 and "could not read the dashboard layout" in body["error"]
    assert _layout(server, "Not there")[0] == 404                # the name lookup is still the only 404


def test_a_name_with_quotes_and_non_ascii_characters_round_trips(server, tmp_path):
    _open(server, tmp_path, text=UNPLACED)
    status, body = _layout(server, ODD_NAME)
    assert status == 200 and body["name"] == ODD_NAME and body["total"] == 1


def test_the_cards_answer_is_what_it_was_before_the_split(server, tmp_path):
    _open(server, tmp_path)
    status, body, raw = _request(server, "GET", "/dashboard-cards?" + urlencode([("name", "Mixed 'one'")]))
    expected = {"cards": [{"name": "Mixed 'one'", "total": 7, "zones": [
        ["bitmap", 0, 0, 12000, 8000], ["text", 12000, 0, 88000, 8000], ["sheet", 0, 8000, 60000, 52000],
        ["sheet", 60000, 8000, 40000, 52000], ["filter", 0, 60000, 25000, 40000],
        ["param", 25000, 60000, 25000, 40000], ["web", 50000, 60000, 50000, 40000]],
        "width": 100000, "height": 100000}], "zone_cap": 40}
    assert status == 200 and body == expected
    assert raw == json.dumps(expected).encode()                  # same key order and spacing as before


def test_cards_and_preview_count_the_same_zones(server, tmp_path):
    _open(server, tmp_path, many_zones=250, extra_dashboards=2)
    for name in ("Mixed 'one'", "No positions", "Many zones", "Extra 000"):
        card = _request(server, "GET", "/dashboard-cards?" + urlencode([("name", name)]))[1]["cards"][0]
        pre = _layout(server, name)[1]
        assert card["total"] == pre["total"]
        assert (card["width"], card["height"]) == (pre["width"], pre["height"])
        shown = [z[:5] for z in pre["zones"]]
        assert all(z in shown for z in card["zones"])           # what a card draws is in the preview, same numbers
        if card["total"] <= 40:
            assert shown == card["zones"]
