"""The zone list behind the Dashboards cards (#84): `dashboard_layout`, `get_dashboard_layout` and
GET /dashboard-cards. No browser here; tests/test_gui_cards.py draws the cards."""

from __future__ import annotations

import http.client
import json
import sys
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
from cards_fixtures import cards_workbook  # noqa: E402
from conftest import xml_from_string  # noqa: E402

from py_tbparse import TwbParser, webgui  # noqa: E402
from py_tbparse.dashboards import dashboard_layout  # noqa: E402


def _layout(name=None, **kw):
    return dashboard_layout(xml_from_string(cards_workbook(**kw)), name)


def test_layout_lists_every_zone_of_the_main_layout_with_kind_and_position():
    df = _layout("Mixed 'one'")
    assert list(df.columns) == ["dashboard", "zone_id", "kind", "name", "x", "y", "w", "h"]
    # the container is listed too, and the zone of the Phone layout (id 99) is not
    assert list(df["zone_id"]) == ["1", "2", "3", "4", "5", "6", "7", "8"]
    assert list(df["kind"]) == ["layout-flow", "bitmap", "text", "sheet", "sheet", "filter", "paramctrl", "web"]
    assert "99" not in set(df["zone_id"])
    sheet = df[df["zone_id"] == "5"].iloc[0]
    assert (sheet["x"], sheet["y"], sheet["w"], sheet["h"]) == (60000, 8000, 40000, 52000)


def test_layout_is_more_than_the_worksheets_that_dashboard_sheets_returns():
    from py_tbparse import dashboard_sheets
    doc = xml_from_string(cards_workbook())
    assert len(dashboard_layout(doc, "Mixed 'one'")) > len(dashboard_sheets(doc, "Mixed 'one'"))


def test_layout_of_all_dashboards_and_of_an_unknown_one():
    df = _layout()
    assert set(df["dashboard"]) == {"Mixed 'one'", "No positions", "Many zones"}
    empty = _layout("Nope")
    assert empty.empty and list(empty.columns) == list(df.columns)


def test_a_zone_without_a_position_has_missing_numbers_not_zeros():
    df = _layout("No positions")
    assert len(df) == 1 and df.iloc[0][["x", "y", "w", "h"]].isna().all()


def test_the_parser_method_gives_the_same_frame(tmp_path):
    path = tmp_path / "wb.twb"
    path.write_text(cards_workbook(), encoding="utf-8")
    p = TwbParser(str(path))
    got = p.get_dashboard_layout("Mixed 'one'")     # the parser puts id columns last, like its other tables
    assert got[list(_layout().columns)].equals(_layout("Mixed 'one'"))
    assert set(p.get_dashboard_layout()["dashboard"]) == set(_layout()["dashboard"])


# --- GET /dashboard-cards ---------------------------------------------------------------------------------


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
    data = json.loads(r.read())
    conn.close()
    return r.status, data


def _open(addr, tmp_path, **kw):
    path = tmp_path / "wb.twb"
    path.write_text(cards_workbook(**kw), encoding="utf-8")
    assert _request(addr, "POST", "/load", {"path": str(path)})[0] == 200


def _cards(addr, *names):
    from urllib.parse import urlencode
    return _request(addr, "GET", "/dashboard-cards?" + urlencode([("name", n) for n in names]))


def test_cards_need_a_workbook(server):
    status, body = _cards(server, "x")
    assert status == 400 and "No workbook" in body["error"]


def test_a_card_has_zones_without_containers_and_the_extent(server, tmp_path):
    _open(server, tmp_path)
    status, body = _cards(server, "Mixed 'one'")
    assert status == 200
    (card,) = body["cards"]
    assert card["total"] == 7 and len(card["zones"]) == 7           # the layout-flow container is not drawn
    assert [z[0] for z in card["zones"]] == ["bitmap", "text", "sheet", "sheet", "filter", "param", "web"]
    assert card["zones"][3] == ["sheet", 60000, 8000, 40000, 52000]
    assert (card["width"], card["height"]) == (100000, 100000)


def test_a_dashboard_with_no_stored_positions_has_no_zones(server, tmp_path):
    _open(server, tmp_path)
    (card,) = _cards(server, "No positions")[1]["cards"]
    assert card["total"] == 0 and card["zones"] == []


def test_a_sketch_is_capped_to_the_largest_zones_and_says_how_many_there_were(server, tmp_path):
    _open(server, tmp_path, many_zones=60)
    status, body = _cards(server, "Many zones")
    (card,) = body["cards"]
    assert card["total"] == 60 and len(card["zones"]) == webgui.CARD_ZONES_MAX == 40
    # the 20 smallest (the first ones in the fixture) are the ones left out, the rest keep layout order
    assert card["zones"][0][3] == 1000 + 20 * 10
    assert card["zones"] == sorted(card["zones"], key=lambda z: z[3])
    assert body["zone_cap"] == 40


def test_the_page_of_names_is_limited_and_unknown_names_are_skipped(server, tmp_path):
    _open(server, tmp_path, extra_dashboards=60)
    status, body = _cards(server, *[f"Extra {i:03d}" for i in range(webgui.CARD_PAGE_MAX + 1)])
    assert status == 400 and str(webgui.CARD_PAGE_MAX) in body["error"]
    status, body = _cards(server, *[f"Extra {i:03d}" for i in range(webgui.CARD_PAGE_MAX - 1)], "Not there")
    assert status == 200 and len(body["cards"]) == webgui.CARD_PAGE_MAX - 1
    assert _cards(server)[1] == {"cards": [], "zone_cap": 40}
