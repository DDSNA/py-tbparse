"""The relationship graph: layout invariants on random graphs, then the view, keyboard, drawer and export."""

from __future__ import annotations

import json
import random
import time
import xml.etree.ElementTree as ET

import pytest

from test_gui_browser import _load, _open, new_page
from test_report import WORKBOOK

LAYOUT = "(d) => VGraph.layout(d)"


def random_graph(seed, n=None, dag=False):
    rng = random.Random(seed)
    n = n or rng.randint(1, 40)
    names = [f"T{i:02d} {'x' * rng.randint(0, 25)}" for i in range(n)]
    edges = []
    for _ in range(rng.randint(0, n * 2)):
        a, b = rng.randrange(n), rng.randrange(n)
        if dag and a >= b:
            continue                                   # only low to high: acyclic by construction
        edges.append({"source": names[a], "target": names[b], "label": f"k{rng.randint(0, 9)} = k{rng.randint(0, 9)}",
                      "kind": rng.choice(["join", "relationship", "inferred"])})
    nodes = [{"id": nm} for nm in names if rng.random() < 0.9]      # some nodes only exist as edge ends
    return {"nodes": nodes, "edges": edges}


def overlaps(nodes):
    boxes = [(n["x"], n["y"], n["x"] + n["w"], n["y"] + n["h"], n["comp"]) for n in nodes]
    for i, a in enumerate(boxes):
        for b in boxes[i + 1:]:
            if a[4] == b[4] and a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]:
                return True
    return False


# --- layout --------------------------------------------------------------------------------------------

@pytest.mark.parametrize("seed", range(25))
def test_layout_places_every_table_once_without_overlap(page, seed):
    g = random_graph(seed)
    lay = page.evaluate(LAYOUT, g)
    wanted = {n["id"] for n in g["nodes"]} | {e[k] for e in g["edges"] for k in ("source", "target")}
    placed = [n["id"] for n in lay["nodes"]]
    assert sorted(placed) == sorted(wanted) and len(placed) == len(set(placed))
    assert not overlaps(lay["nodes"])
    assert len(lay["edges"]) == len(g["edges"])
    assert sum(c["size"] for c in lay["components"]) == len(wanted)
    sizes = [c["size"] for c in lay["components"]]
    assert sizes == sorted(sizes, reverse=True), "largest group first"
    for n in lay["nodes"]:
        assert n["x"] >= 0 and n["y"] >= 0
    assert page.js_errors == []


@pytest.mark.parametrize("seed", range(15))
def test_edges_point_to_the_right_in_an_acyclic_graph(page, seed):
    g = random_graph(seed, dag=True)
    lay = page.evaluate(LAYOUT, g)
    layer = {n["id"]: n["layer"] for n in lay["nodes"]}
    for e in g["edges"]:
        if e["source"] != e["target"]:
            assert layer[e["source"]] < layer[e["target"]], e


@pytest.mark.parametrize("seed", range(10))
def test_cycles_still_get_a_layout_and_a_self_loop_is_drawn(page, seed):
    names = [f"N{i}" for i in range(5)]
    g = {"nodes": [{"id": n} for n in names],
         "edges": [{"source": names[i], "target": names[(i + 1) % 5], "label": "a = b", "kind": "join"} for i in range(5)]
         + [{"source": "N0", "target": "N0", "label": "self", "kind": "join"}]}
    lay = page.evaluate(LAYOUT, g)
    assert len(lay["nodes"]) == 5 and not overlaps(lay["nodes"])
    assert len({n["layer"] for n in lay["nodes"]}) >= 2


@pytest.mark.parametrize("seed", range(10))
def test_layout_is_deterministic_and_ignores_input_order(page, seed):
    g = random_graph(seed)
    a = page.evaluate(LAYOUT, g)
    b = page.evaluate(LAYOUT, g)
    assert a == b
    shuffled = {"nodes": g["nodes"][::-1], "edges": g["edges"]}
    c = page.evaluate(LAYOUT, shuffled)
    pos = lambda lay: sorted((n["id"], n["x"], n["y"]) for n in lay["nodes"])  # noqa: E731
    assert pos(a) == pos(c)


def test_parallel_edges_fan_out_and_are_all_kept(page):
    g = {"nodes": [{"id": "A"}, {"id": "B"}],
         "edges": [{"source": "A", "target": "B", "label": f"k{i}", "kind": "join"} for i in range(4)]
         + [{"source": "B", "target": "A", "label": "back", "kind": "relationship"}]}
    lay = page.evaluate(LAYOUT, g)
    assert [e["slot"] for e in lay["edges"]] == [0, 1, 2, 3, 4] and {e["slots"] for e in lay["edges"]} == {5}


def test_empty_and_single_node_graphs(page):
    assert page.evaluate(LAYOUT, {"nodes": [], "edges": []})["nodes"] == []
    one = page.evaluate(LAYOUT, {"nodes": [{"id": "Only"}], "edges": []})
    assert len(one["nodes"]) == 1 and one["components"][0]["size"] == 1


def test_layout_speed_budget(page):
    g = random_graph(7, n=300)
    g["edges"] = (g["edges"] * 4)[:600]
    started = time.time()
    page.evaluate(LAYOUT, g)
    ms = page.evaluate("(d) => { const t = performance.now(); VGraph.layout(d); return performance.now() - t; }", g)
    assert ms < 400, f"300 tables, 600 edges: {ms:.0f} ms (budget 200 ms, enforced at twice that)"
    assert time.time() - started < 10


# --- the view ------------------------------------------------------------------------------------------

@pytest.fixture
def graph_page(page, wenjie_path):
    _load(page, wenjie_path)
    _open(page, "graph")
    page.wait_for_selector("#tableWrap svg.graph .node", timeout=10_000)
    page.wait_for_timeout(250)                    # the first fit runs on the next frame
    return page


def test_the_graph_is_drawn_inside_its_box_and_fitted(graph_page):
    page = graph_page
    box = page.locator("#tableWrap .graph-box").bounding_box()
    for node in page.locator("#tableWrap svg.graph .node").all():
        b = node.bounding_box()
        assert b["x"] >= box["x"] - 1 and b["x"] + b["width"] <= box["x"] + box["width"] + 1, "node outside the box"
        assert b["y"] >= box["y"] - 1 and b["y"] + b["height"] <= box["y"] + box["height"] + 1
    assert page.js_errors == []


def test_tables_have_names_and_one_tab_stop(graph_page):
    page = graph_page
    labels = page.locator("#tableWrap .node").evaluate_all("els => els.map(e => e.getAttribute('aria-label'))")
    assert all(", " in label and "connection" in label for label in labels)
    stops = page.locator("#tableWrap .node[tabindex='0']").count()
    assert stops == 1


def test_the_keyboard_walks_the_graph_and_enter_tells_about_a_table(graph_page):
    page = graph_page
    page.locator("#tableWrap .node[tabindex='0']").focus()
    first = page.evaluate("() => document.activeElement.dataset.id")
    seen = {first}
    for key in ("ArrowRight", "ArrowDown", "ArrowLeft", "ArrowUp", "End", "Home"):
        page.keyboard.press(key)
        seen.add(page.evaluate("() => document.activeElement.dataset.id"))
    assert page.evaluate("() => document.activeElement.classList.contains('node')")
    assert page.locator("#tableWrap .node[tabindex='0']").count() == 1, "roving tab stop"
    focused = page.evaluate("() => document.activeElement.dataset.id")
    page.keyboard.press("Enter")
    page.wait_for_selector("#drawer.show", timeout=5_000)
    assert page.inner_text("#drawerTitle") == focused
    assert "Connections" in page.inner_text("#drawerBody")
    page.keyboard.press("Escape")
    page.wait_for_selector("#drawer", state="hidden", timeout=5_000)
    assert page.evaluate("() => document.activeElement.classList.contains('node')"), "focus returns to the table"
    assert page.js_errors == []


def test_focusing_or_hovering_a_table_highlights_its_connections(graph_page):
    page = graph_page
    if page.locator("#tableWrap .edge").count() == 0:
        pytest.skip("fixture has no edges")
    node = page.locator("#tableWrap .node").first
    node.focus()
    assert page.locator("#tableWrap .node.on").count() >= 1
    assert page.locator("#tableWrap .edge.on").count() >= 1
    page.evaluate("() => document.activeElement.blur()")
    assert page.locator("#tableWrap .node.on").count() == 0 and page.locator("#tableWrap .node.dim").count() == 0


def test_clicking_a_connection_shows_its_keys(graph_page):
    page = graph_page
    if page.locator("#tableWrap .edge").count() == 0:
        pytest.skip("fixture has no edges")
    page.locator("#tableWrap .edge .hit").first.dispatch_event("click")
    page.wait_for_selector("#drawer.show", timeout=5_000)
    body = page.inner_text("#drawerBody")
    assert "Keys" in body and "From" in body and "To" in body
    page.click("#drawerCopy")
    assert json.loads(page.evaluate("() => navigator.clipboard.readText()"))["from"]


def test_zoom_buttons_wheel_and_drag_move_the_view(graph_page):
    page = graph_page
    svg = page.locator("#tableWrap svg.graph")
    k0 = float(page.evaluate("() => document.querySelector('.viewport').getAttribute('transform')").split("scale(")[1].rstrip(")"))
    page.click('button[aria-label="Zoom in"]')
    k1 = float(page.evaluate("() => document.querySelector('.viewport').getAttribute('transform')").split("scale(")[1].rstrip(")"))
    assert k1 > k0
    page.click('button[aria-label="Zoom out"]')
    page.click('button[aria-label="Zoom out"]')
    k2 = float(page.evaluate("() => document.querySelector('.viewport').getAttribute('transform')").split("scale(")[1].rstrip(")"))
    assert k2 < k1
    page.click('button[aria-label="Fit the whole graph in view"]')
    k3 = float(page.evaluate("() => document.querySelector('.viewport').getAttribute('transform')").split("scale(")[1].rstrip(")"))
    assert abs(k3 - k0) < 0.02, "Fit returns to the fitted view"
    box = svg.bounding_box()
    before = page.evaluate("() => document.querySelector('.viewport').getAttribute('transform')")
    page.mouse.move(box["x"] + 8, box["y"] + 8)
    page.mouse.down()
    page.mouse.move(box["x"] + 60, box["y"] + 40, steps=4)
    page.mouse.up()
    assert page.evaluate("() => document.querySelector('.viewport').getAttribute('transform')") != before
    page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    page.mouse.wheel(0, -400)
    page.wait_for_timeout(100)
    k4 = float(page.evaluate("() => document.querySelector('.viewport').getAttribute('transform')").split("scale(")[1].rstrip(")"))
    assert k4 > k3
    assert page.js_errors == []


def test_the_list_view_has_every_connection(graph_page):
    page = graph_page
    edges = page.locator("#tableWrap .edge").count()
    page.click("text=View as list")
    assert page.locator("#tableWrap .graph-box").is_hidden()
    assert page.locator("#tableWrap .graph-table tbody tr").count() == edges
    assert page.get_attribute("text=View as graph", "aria-pressed") == "true"
    assert page.locator("#tableWrap .graph-table th[scope=col]").count() == 4
    page.click("text=View as graph")
    assert page.locator("#tableWrap .graph-box").is_visible()


def test_save_as_svg_gives_a_standalone_valid_file(graph_page, tmp_path):
    page = graph_page
    with page.expect_download() as info:
        page.click("text=Save as SVG")
    out = tmp_path / "g.svg"
    info.value.save_as(out)
    text = out.read_text(encoding="utf-8")
    root = ET.fromstring(text)                         # well-formed XML
    assert root.tag.endswith("svg") and root.get("viewBox")
    assert "var(--" not in text, "colours must be literal in a file that leaves the page"
    assert text.count('<g class="node"') == page.locator("#tableWrap .node").count()
    assert info.value.suggested_filename == "relationships.svg"


def test_include_inferred_adds_dashed_connections(graph_page):
    page = graph_page
    assert page.locator("#tableWrap .edge.inferred").count() == 0
    data = page.evaluate("() => fetch('/graph?include_inferred=true').then((r) => r.json())")["graph"]
    inferred = [e for e in data["edges"] if e["kind"] == "inferred"]
    page.check("#includeInferred")
    page.wait_for_function("(n) => document.querySelectorAll('#tableWrap .edge').length === n", arg=len(data["edges"]))
    assert page.locator("#tableWrap .edge.inferred").count() == len(inferred)
    assert page.locator("#tableWrap .node").count() == len(data["nodes"])


def test_the_dot_source_is_still_there_and_collapsed(graph_page):
    page = graph_page
    assert page.locator("#tableWrap details.dot-source").get_attribute("open") is None
    assert page.text_content("#tableWrap pre.dot").startswith('digraph "twb" {')
    page.click("#copyBtn")


def test_a_workbook_without_relationships_says_so(page, tmp_path):
    path = tmp_path / "plain.twb"
    path.write_text(WORKBOOK, encoding="utf-8")
    _load(page, str(path))
    _open(page, "graph")
    page.wait_for_selector("#tableWrap .empty-state", timeout=10_000)
    assert "No joins or relationships" in page.inner_text("#tableWrap .empty-state")
    assert page.locator("#tableWrap svg.graph").count() == 0
    assert page.locator("#tableWrap details.dot-source").count() == 1
    assert page.js_errors == []


def _big(n_groups=6, per=70):
    nodes, edges = [], []
    for g in range(n_groups):
        for i in range(per):
            nodes.append({"id": f"G{g}T{i:02d}"})
            if i:
                edges.append({"source": f"G{g}T{i // 2:02d}", "target": f"G{g}T{i:02d}", "label": "id = id", "kind": "join"})
    return {"dot": "digraph {}", "graph": {"nodes": nodes, "edges": edges}}


def test_a_large_graph_draws_one_group_at_a_time(page, wenjie_path):
    _load(page, wenjie_path)
    page.route("**/graph?*", lambda route: route.fulfill(status=200, content_type="application/json", body=json.dumps(_big())))
    _open(page, "graph")
    page.wait_for_selector("#tableWrap svg.graph .node", timeout=10_000)
    assert page.locator("#tableWrap .node").count() == 70, "only the first group of 420 tables is drawn"
    select = page.locator("#tableWrap .graph-tools select")
    assert select.locator("option").count() == 6
    assert "Large graph" in page.inner_text("#tableWrap .graph-tools")
    select.select_option("3")
    page.wait_for_function("() => document.querySelector('#tableWrap .node').dataset.id.startsWith('G')")
    assert page.locator("#tableWrap .node").count() == 70
    assert page.locator("#tableWrap .edge").count() == 69
    assert page.get_attribute("#tableWrap .graph-tools select", "aria-label")
    assert page.js_errors == []


def test_the_graph_follows_the_theme(page, wenjie_path):
    _load(page, wenjie_path)
    _open(page, "graph")
    page.wait_for_selector("#tableWrap svg.graph .node", timeout=10_000)
    fill = "() => getComputedStyle(document.querySelector('#tableWrap .node rect')).fill"
    before = page.evaluate(fill)
    page.click("#themeBtn")
    page.click('#menu [role="menuitemradio"]:has-text("Harbor")')
    page.click('#menu [role="menuitemradio"]:has-text("Dark")')
    page.keyboard.press("Escape")
    page.wait_for_timeout(150)
    assert page.evaluate(fill) != before


def test_the_graph_view_has_no_sideways_overflow_on_a_phone(browser, gui_server, wenjie_path):
    pg = new_page(browser, gui_server, viewport={"width": 360, "height": 740})
    try:
        _load(pg, wenjie_path)
        _open(pg, "graph") if pg.locator('.nav-item[data-table="graph"]').is_visible() else pg.select_option("#tableSel", "graph")
        pg.wait_for_selector("#tableWrap svg.graph .node", timeout=10_000)
        assert pg.evaluate("() => document.documentElement.scrollWidth <= window.innerWidth")
    finally:
        pg.ctx.close()


SMALL = {"dot": "digraph {}", "graph": {
    "nodes": [{"id": n} for n in ("A", "B", "C", "D", "E")],
    "edges": [
        {"source": "A", "target": "B", "label": "a = b", "kind": "join"},
        {"source": "B", "target": "C", "label": "b = c", "kind": "relationship"},
        {"source": "A", "target": "D", "label": "a = d", "kind": "inferred"},
        {"source": "C", "target": "A", "label": "c = a", "kind": "join"},
    ]}}


def _small(page, wenjie_path):
    _load(page, wenjie_path)
    page.route("**/graph?*", lambda route: route.fulfill(status=200, content_type="application/json", body=json.dumps(SMALL)))
    _open(page, "graph")
    page.wait_for_selector("#tableWrap svg.graph .node", timeout=10_000)
    page.wait_for_timeout(250)


def _focused(page):
    return page.evaluate("() => document.activeElement.dataset.id")


def test_arrow_keys_follow_connections_exactly(page, wenjie_path):
    _small(page, wenjie_path)
    assert page.locator("#tableWrap .node").count() == 5
    page.locator('#tableWrap .node[data-id="A"]').focus()
    page.keyboard.press("ArrowRight")
    assert _focused(page) in ("B", "D"), "right follows an edge that leaves A"
    page.keyboard.press("ArrowLeft")
    assert _focused(page) == "A", "left follows an edge that enters"
    page.locator('#tableWrap .node[data-id="B"]').focus()
    page.keyboard.press("ArrowRight")
    assert _focused(page) == "C"
    page.keyboard.press("ArrowDown")                   # C is alone in its column: nothing below
    assert _focused(page) == "C"
    page.keyboard.press("Home")
    first = _focused(page)
    page.keyboard.press("End")
    assert _focused(page) != first or page.locator("#tableWrap .node").count() == 1
    assert page.locator("#tableWrap .node[tabindex='0']").count() == 1


def test_the_cycle_and_the_isolated_table_are_both_drawn(page, wenjie_path):
    _small(page, wenjie_path)
    assert page.locator("#tableWrap .edge").count() == 4
    assert page.locator('#tableWrap .node[data-id="E"]').is_visible(), "an unconnected table is still shown"
    kinds = page.locator("#tableWrap .edge").evaluate_all("els => els.map(e => e.getAttribute('class'))")
    assert sorted(k.split()[-1] for k in kinds) == ["inferred", "join", "join", "relationship"]


def test_hover_dims_what_is_not_connected(page, wenjie_path):
    _small(page, wenjie_path)
    page.locator('#tableWrap .node[data-id="D"]').hover()
    on = page.locator("#tableWrap .node.on").evaluate_all("els => els.map(e => e.dataset.id).sort()")
    assert on == ["A", "D"]
    dim = page.locator("#tableWrap .node.dim").evaluate_all("els => els.map(e => e.dataset.id).sort()")
    assert dim == ["B", "C", "E"]
    page.mouse.move(5, 5)
    assert page.locator("#tableWrap .node.on").count() == 0


@pytest.mark.parametrize("seed", range(12))
def test_every_gap_is_wide_enough_for_the_labels_that_cross_it(page, seed):
    g = random_graph(seed, dag=True)
    lay = page.evaluate(LAYOUT, g)
    pos = {n["id"]: n for n in lay["nodes"]}
    for e in g["edges"]:
        a, b = pos[e["source"]], pos[e["target"]]
        if a["id"] == b["id"] or b["layer"] != a["layer"] + 1:
            continue
        room = b["x"] - (a["x"] + a["w"])
        need = min(len(e["label"]), 40) * 6.6
        assert room >= need, f"{e['label']!r}: {room:.0f}px of gap for {need:.0f}px of text"
