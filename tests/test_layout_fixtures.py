"""The fixture builders of tests/layout_fixtures.py (#84, WP2), checked without a browser through
GET /dashboard-layout, plus the two additive fields of that answer (`parents`, `order`)."""

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
import layout_fixtures as lf  # noqa: E402

from py_tbparse import webgui  # noqa: E402


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


def _call(addr, method, path, body=None):
    conn = http.client.HTTPConnection(*addr, timeout=10)
    conn.request(method, path, body=json.dumps(body) if body is not None else None,
                 headers={"Content-Type": "application/json"})
    r = conn.getresponse()
    out = json.loads(r.read())
    conn.close()
    return r.status, out


@pytest.fixture
def layout(server, tmp_path):
    path = tmp_path / "everything.twb"
    path.write_text(lf.everything_workbook(), encoding="utf-8")
    assert _call(server, "POST", "/load", {"path": str(path)})[0] == 200

    def get(name):
        status, body = _call(server, "GET", "/dashboard-layout?" + urlencode([("name", name)]))
        assert status == 200, body
        return body
    return get


def _by_label(body):
    return {z[5]: z for z in body["zones"]}


def test_every_dashboard_of_the_combined_workbook_is_read(layout):
    counts = {"Nested": 5, "Crossing": 4, "Mixed overlap": 9, "Threshold": 6, "Edge five": 6, "Edge six": 7,
              "Busy overlap": 9, "Label collision": 5, "Huge extent": 3, "Grid": 3, "Tiny zones": 5,
              "Many overlap": 250, "Half placed": 1, "All unplaced": 0, "Hostile names": 4}
    for name, n in counts.items():
        assert layout(name)["total"] == n, name


def test_nested_rectangles_and_parents(layout):
    body = layout("Nested")
    z = _by_label(body)
    assert z["Inner chart"][1:5] == [8000, 8000, 10000, 8000]
    assert body["parents"] == ["1", "1", "1", "1", "10"]          # the free sheet is in the inner container
    assert body["order"] == [0, 4, 1, 2, 3]                        # areas 3.6e9, 9e8 (Free sheet), 6e8, 3e8, 8e7


def test_draw_order_is_largest_area_first_and_equal_areas_in_layout_order(layout):
    body = layout("Mixed overlap")
    areas = [body["zones"][i][3] * body["zones"][i][4] for i in body["order"]]
    assert areas == sorted(areas, reverse=True)
    names = [body["zones"][i][5] for i in body["order"]]
    assert names.index("Same 1") < names.index("Same 2") and names.index("Tie A") < names.index("Tie B")
    assert names.index("Outer") < names.index("Inner")
    assert sorted(body["order"]) == list(range(body["total"]))


def test_unplaced_and_hostile_and_huge(layout):
    half = layout("Half placed")
    assert half["unplaced"] == 3 and half["total"] == 1
    allun = layout("All unplaced")
    assert allun["total"] == 0 and allun["unplaced"] == 2 and allun["zones"] == [] and allun["order"] == []
    huge = layout("Huge extent")
    assert (huge["width"], huge["height"]) == (250000, 180000)
    assert _by_label(huge)["Negative start"][1:3] == [-5000, -3000]
    names = [z[5] for z in layout("Hostile names")["zones"]]
    assert names[0] == "<script>window.__pwned = 1</script>" and len(names[3]) == 300 and "日本語" in names[2]


def test_many_overlap_keeps_200_and_drops_the_tiny_ones(layout):
    body = layout("Many overlap")
    assert body["total"] == 250 and len(body["zones"]) == 200 and len(body["parents"]) == 200 == len(body["order"])
    assert all(z[3] >= 3000 for z in body["zones"])
    assert body["width"] == 190500                                  # the dropped zone still sets the extent


def test_threshold_pairs_sit_on_both_sides_of_one_percent(layout):
    z = _by_label(layout("Threshold"))
    def share(a, b):
        w = min(a[1] + a[3], b[1] + b[3]) - max(a[1], b[1])
        h = min(a[2] + a[4], b[2] + b[4]) - max(a[2], b[2])
        return max(w, 0) * max(h, 0) / (min(a[3] * a[4], b[3] * b[4]))
    assert share(z["Edge 1"], z["Edge 2"]) == 0
    assert 0.0089 < share(z["Under 1"], z["Under 2"]) < 0.0091
    assert 0.0119 < share(z["Over 1"], z["Over 2"]) < 0.0121
