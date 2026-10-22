"""The layout preview panel of the Dashboards table (#84, WP2 of docs/plan-84-layout-preview.md): the drawing, the zone
list, linked hover and selection, draw order, nested and crossing zones, labels, the visible note, scaling, tiny zones
and the caps. Needs Chromium (see test_gui_browser.py). The panel is reached by picking a row of the Dashboards table.
Workbooks come from tests/layout_fixtures.py (one dashboard per case, all in `everything_workbook()`)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
import layout_fixtures as lf  # noqa: E402
from test_gui_a11y import failures, settle  # noqa: E402,F401
from test_gui_browser import _load, _open, new_page  # noqa: E402,F401

WIDE = {"width": 1360, "height": 900}


@pytest.fixture(scope="module")
def wb_text():
    return lf.everything_workbook()


@pytest.fixture
def wb_path(tmp_path, wb_text):
    path = tmp_path / "layout.twb"
    path.write_text(wb_text, encoding="utf-8")
    return str(path)


@pytest.fixture
def wide(browser, gui_server, wb_path):
    pg = new_page(browser, gui_server, viewport=WIDE)
    _load(pg, wb_path)
    _open(pg, "dashboards")
    pg.wait_for_selector("#tableWrap tbody tr[data-pos]", timeout=10_000)
    yield pg
    pg.ctx.close()


def _pick(page, name):
    """Click the row of a dashboard and wait for its panel to be drawn (or listed, when nothing is placed)."""
    page.locator("#tableWrap tbody tr[data-pos]").filter(has=page.get_by_text(name, exact=True)).first.click()
    page.wait_for_function(
        "n => { const t = document.getElementById('lpTitle'); const b = document.querySelector('#layoutPanel .lp-body');"
        " return t && t.textContent === n && b && b.querySelector('.lp-list, .lp-empty') }", arg=name, timeout=10_000)
    page.wait_for_function(                                # the size check after drawing has run (no drawing, nothing to wait for)
        "() => { const f = document.querySelector('#layoutPanel .lp-fig'); return !f || f.dataset.settled === '1' }", timeout=10_000)


def _lines(page):
    return page.locator("#layoutPanel ol.lp-list:not(.lp-unplaced) > li")


def _shape_names(page):
    """Names of the zones in the order their shapes are in the DOM (the draw order)."""
    return page.evaluate("""() => [...document.querySelectorAll('#layoutPanel .lp-z')].map(
        (r) => document.querySelector('#layoutPanel ol.lp-list li[data-i="' + r.dataset.i + '"] .lp-name').textContent)""")


def _line(page, name):
    """The list line of a zone: the name matched exactly, or, when no line has exactly that name, as a prefix."""
    lines = page.locator("#layoutPanel ol.lp-list:not(.lp-unplaced) > li")
    exact = lines.filter(has=page.locator(".lp-name").get_by_text(name, exact=True))
    return exact.first if exact.count() else lines.filter(has=page.locator(".lp-name", has_text=name)).first


def _shape(page, name):
    i = _line(page, name).get_attribute("data-i")
    return page.locator(f"#layoutPanel .lp-z[data-i='{i}']")


def _hint(page, name):
    return _line(page, name).locator(".lp-hint").inner_text()


def _note(page):
    return page.locator("#layoutPanel .lp-note").inner_text()


def _conds(page):
    return page.locator("#layoutPanel .lp-note-extra").evaluate_all("els => els.map(e => e.dataset.cond)")


def _frame_dashed(page):
    return page.locator("#layoutPanel .lp-frame").evaluate("e => e.classList.contains('lp-provisional') && getComputedStyle(e).borderStyle")


# ---- basic panel ---------------------------------------------------------------------------------------------------

def test_the_panel_has_one_shape_and_one_line_for_each_zone(wide):
    _pick(wide, "Mixed overlap")
    assert wide.locator("#layoutPanel svg").count() == 1
    assert wide.locator("#layoutPanel .lp-z").count() == 9 == _lines(wide).count()
    shapes = wide.locator("#layoutPanel .lp-z").evaluate_all("els => els.map(e => e.dataset.i).sort()")
    lines = _lines(wide).evaluate_all("els => els.map(e => e.dataset.i).sort()")
    assert shapes == lines
    first = _lines(wide).first.inner_text()
    assert "Outer" in first and "Worksheet" in first and "position" in first
    assert wide.locator("#layoutPanel .lp-count").inner_text() == "9 zones"
    assert wide.locator("#layoutPanel [role=status]").inner_text() == "Layout of Mixed overlap: 9 zones"
    assert wide.js_errors == []


def test_picking_a_row_keeps_focus_on_the_row_and_does_not_open_the_drawer(wide):
    row = wide.locator("#tableWrap tbody tr[data-pos]").filter(has=wide.get_by_text("Grid", exact=True)).first
    row.focus()
    wide.keyboard.press("Enter")
    wide.wait_for_selector("#layoutPanel .lp-list")
    assert wide.evaluate("() => document.activeElement.tagName + ':' + document.activeElement.dataset.pos") == \
        "TR:" + row.get_attribute("data-pos")
    assert wide.locator("#drawer").is_hidden()
    wide.keyboard.press("ArrowDown")                           # the arrow keys still move through the table
    assert wide.evaluate("() => document.activeElement.tagName") == "TR"
    assert wide.locator("#layoutPanel").get_attribute("aria-labelledby") == "lpTitle"


def test_all_columns_opens_the_details_drawer_and_closing_it_returns_to_the_button(wide):
    _pick(wide, "Grid")
    wide.get_by_role("button", name="All columns of Grid").click()
    wide.wait_for_selector("#drawer.show")
    assert "Grid" in wide.locator("#drawerTitle").inner_text()
    assert "worksheets" in wide.locator("#drawerBody").inner_text()
    wide.click("#drawerClose")
    assert wide.evaluate("() => document.activeElement.textContent") == "All columns"
    assert wide.locator("#layoutPanel .lp-list").count() == 1          # the panel stays


def test_other_tables_keep_the_drawer_and_no_panel(wide):
    _open(wide, "dashboard-sheets")
    wide.wait_for_selector("#tableWrap tbody tr[data-pos]")
    wide.locator("#tableWrap tbody tr[data-pos]").first.click()
    wide.wait_for_selector("#drawer.show")
    assert wide.locator("#layoutPanel").is_hidden()


def test_changing_table_closes_the_panel(wide):
    _pick(wide, "Grid")
    _open(wide, "dashboard-sheets")
    assert wide.locator("#layoutPanel").is_hidden() and wide.locator("#layoutPanel .lp-list").count() == 0


def test_hovering_and_focusing_link_the_shape_and_the_line(wide):
    _pick(wide, "Mixed overlap")
    _shape(wide, "Cross 1").hover(position={"x": 5, "y": 5})
    assert "lp-hot" in _line(wide, "Cross 1").get_attribute("class")
    _line(wide, "Same 1").hover()
    assert "lp-hot" in _shape(wide, "Same 1").get_attribute("class")
    assert "lp-hot" not in _line(wide, "Cross 1").get_attribute("class")
    _line(wide, "Tie A").focus()
    assert "lp-hot" in _shape(wide, "Tie A").get_attribute("class")
    wide.mouse.move(5, 5)
    wide.locator("#tableWrap").first.focus()
    assert wide.locator("#layoutPanel .lp-hot").count() == 0


def test_enter_and_click_select_and_escape_clears(wide):
    _pick(wide, "Mixed overlap")
    line = _line(wide, "Tie B")
    line.focus()
    wide.keyboard.press("Enter")
    assert line.get_attribute("aria-current") == "true"
    assert "lp-selected" in _shape(wide, "Tie B").get_attribute("class")
    wide.keyboard.press("Escape")
    assert wide.locator("#layoutPanel [aria-current]").count() == 0
    assert wide.evaluate("() => document.activeElement.classList.contains('lp-line')")      # focus stays in the list
    _shape(wide, "Tie A").click()
    assert _line(wide, "Tie A").get_attribute("aria-current") == "true"
    assert wide.locator("#layoutPanel [aria-current]").count() == 1


def test_escape_closes_the_panel_when_nothing_is_selected_and_clears_a_selection_first(wide):
    _pick(wide, "Mixed overlap")
    row = wide.locator("#tableWrap tbody tr[data-pos]").filter(has=wide.get_by_text("Mixed overlap", exact=True)).first
    row.focus()
    _line(wide, "Tie B").click()                                    # select a zone, then go back to the row
    assert wide.locator("#layoutPanel [aria-current]").count() == 1
    row.focus()
    wide.keyboard.press("Escape")                                   # first press: the selection goes, the panel stays
    assert wide.locator("#layoutPanel [aria-current]").count() == 0
    assert wide.locator("#layoutPanel").is_visible() and wide.locator("#layoutPanel .lp-list").count() == 1
    wide.keyboard.press("Escape")                                   # second press: nothing selected, the panel closes
    assert wide.locator("#layoutPanel").is_hidden() and wide.locator("#layoutPanel .lp-list").count() == 0
    assert wide.evaluate("() => document.activeElement.tagName + ':' + document.activeElement.dataset.pos") == \
        "TR:" + row.get_attribute("data-pos")
    assert wide.js_errors == []


def test_escape_in_the_zone_list_clears_the_selection_then_closes_the_panel(wide):
    _pick(wide, "Mixed overlap")
    line = _line(wide, "Tie B")
    line.focus()
    wide.keyboard.press("Enter")
    wide.keyboard.press("Escape")
    assert wide.locator("#layoutPanel .lp-list").count() == 1                 # cleared the selection only
    wide.keyboard.press("Escape")
    assert wide.locator("#layoutPanel").is_hidden()
    assert wide.evaluate("() => document.activeElement.tagName") == "TR"


def test_escape_with_the_drawer_open_closes_the_drawer_and_keeps_the_panel(wide):
    _pick(wide, "Grid")
    wide.get_by_role("button", name="All columns of Grid").click()
    wide.wait_for_selector("#drawer.show")
    wide.keyboard.press("Escape")
    wide.wait_for_selector("#drawer", state="hidden")
    assert wide.locator("#layoutPanel .lp-list").count() == 1
    wide.keyboard.press("Escape")
    assert wide.locator("#layoutPanel").is_hidden()


def test_picking_another_dashboard_closes_the_all_columns_drawer(wide):
    _pick(wide, "Grid")
    wide.get_by_role("button", name="All columns of Grid").click()
    wide.wait_for_selector("#drawer.show")
    assert "Grid" in wide.locator("#drawerTitle").inner_text()
    other = wide.locator("#tableWrap tbody tr[data-pos]").filter(has=wide.get_by_text("Mixed overlap", exact=True)).first
    other.focus()
    wide.keyboard.press("Enter")                                  # the panel moves to another dashboard
    wide.wait_for_function("() => document.getElementById('lpTitle').textContent === 'Mixed overlap'")
    wide.wait_for_selector("#drawer", state="hidden")             # the drawer did not stay behind with Grid's columns
    assert wide.locator("#layoutPanel .lp-list").count() == 1
    # focus stays on the row that was picked, not on the row of the old dashboard or the vanished button
    assert wide.evaluate("() => document.activeElement.dataset.pos") == other.get_attribute("data-pos")
    assert wide.evaluate("() => [...document.querySelectorAll('#tableWrap tr[aria-current=true]')].map(t => t.dataset.pos)") == \
        [other.get_attribute("data-pos")]
    # and the drawer can be opened again for the new dashboard
    wide.get_by_role("button", name="All columns of Mixed overlap").click()
    wide.wait_for_selector("#drawer.show")
    assert "Mixed overlap" in wide.locator("#drawerTitle").inner_text()
    wide.click("#drawerClose")
    assert wide.evaluate("() => document.activeElement.textContent") == "All columns"
    assert wide.js_errors == []


def test_arrow_keys_move_through_the_list_with_one_tab_stop(wide):
    _pick(wide, "Mixed overlap")
    stops = "#layoutPanel ol.lp-list:not(.lp-unplaced) > li[tabindex='0']"
    assert wide.locator(stops).count() == 1
    _lines(wide).first.focus()
    wide.keyboard.press("ArrowDown")
    assert wide.evaluate("() => document.activeElement.dataset.i") == "1"
    assert wide.locator(stops).count() == 1
    wide.keyboard.press("End")
    assert wide.evaluate("() => document.activeElement.dataset.i") == "8"
    wide.keyboard.press("ArrowDown")                                  # no wrap past the end
    assert wide.evaluate("() => document.activeElement.dataset.i") == "8"
    wide.keyboard.press("Home")
    assert wide.evaluate("() => document.activeElement.dataset.i") == "0"
    wide.keyboard.press("ArrowUp")
    assert wide.evaluate("() => document.activeElement.dataset.i") == "0"
    assert wide.locator(stops).count() == 1


def test_the_drawing_is_an_image_with_hidden_shapes_and_the_list_has_a_name(wide):
    _pick(wide, "Mixed overlap")
    svg = wide.locator("#layoutPanel svg")
    assert svg.get_attribute("role") == "img"
    assert svg.get_attribute("aria-label") == "Layout of Mixed overlap: 9 zones; the zone list has them all"
    assert wide.locator("#layoutPanel .lp-z[aria-hidden=true]").count() == 9
    assert wide.locator("#layoutPanel .lp-shapes[aria-hidden=true], #layoutPanel .lp-labels[aria-hidden=true]").count() == 2
    assert wide.locator("#layoutPanel ol.lp-list").first.get_attribute("aria-label") == "Zones of Mixed overlap"


def test_hostile_names_are_text_and_a_long_name_is_cut_with_the_full_name_in_a_title(wide):
    _pick(wide, "Hostile names")
    assert wide.evaluate("() => window.__pwned") is None
    assert wide.locator("#layoutPanel script, #layoutPanel b").count() == 0
    assert "<script>window.__pwned = 1</script>" in _lines(wide).nth(0).inner_text()
    assert "日本語" in _lines(wide).nth(2).inner_text()
    long = _lines(wide).nth(3).locator(".lp-name")
    assert len(long.inner_text()) == 60 and long.inner_text().endswith("…")
    assert long.get_attribute("title") == "L" * 300
    assert wide.js_errors == []


@pytest.mark.parametrize("mode", ["light", "dark"])
def test_overlapping_zones_pass_the_accessibility_checks(browser, gui_server, wb_path, mode):
    pg = new_page(browser, gui_server, color_scheme=mode, viewport=WIDE)
    try:
        _load(pg, wb_path)
        _open(pg, "dashboards")
        pg.wait_for_selector("#tableWrap tbody tr[data-pos]")
        _pick(pg, "Busy overlap")
        settle(pg)
        assert failures(pg, "panel " + mode) == []
        _line(pg, "Busy inner").focus()
        pg.keyboard.press("Enter")
        settle(pg)
        assert failures(pg, "panel with a selection " + mode) == []
        assert pg.js_errors == []
    finally:
        pg.ctx.close()


# ---- draw order -----------------------------------------------------------------------------------------------------

def test_shapes_are_in_the_dom_largest_first_and_equal_areas_in_layout_order(wide):
    _pick(wide, "Mixed overlap")
    names = _shape_names(wide)
    areas = wide.evaluate("""() => [...document.querySelectorAll('#layoutPanel .lp-z')].map(
        (r) => +r.getAttribute('width') * +r.getAttribute('height'))""")
    assert areas == sorted(areas, reverse=True)
    assert names.index("Same 1") < names.index("Same 2") and names.index("Tie A") < names.index("Tie B")
    assert names.index("Outer") < names.index("Inner")


def test_clicking_where_zones_overlap_selects_the_topmost(wide):
    _pick(wide, "Mixed overlap")
    inner = _shape(wide, "Inner").bounding_box()
    outer = _shape(wide, "Outer").bounding_box()
    wide.mouse.click(inner["x"] + inner["width"] / 2, inner["y"] + inner["height"] / 2)
    assert _line(wide, "Inner").get_attribute("aria-current") == "true"
    wide.mouse.click(outer["x"] + outer["width"] * 0.9, outer["y"] + outer["height"] * 0.9)
    assert _line(wide, "Outer").get_attribute("aria-current") == "true"
    assert wide.locator("#layoutPanel [aria-current]").count() == 1


def test_the_list_stays_in_layout_order_and_the_overlay_is_last_and_changes_no_order(wide):
    _pick(wide, "Mixed overlap")
    before = _shape_names(wide)
    listed = _lines(wide).locator(".lp-name").all_inner_texts()
    assert listed == ["Outer", "Inner", "Cross 1", "Cross 2", "Same 1", "Same 2", "Tie A", "Tie B", "Late big"]
    assert listed != before
    _line(wide, "Cross 2").focus()
    wide.keyboard.press("Enter")
    assert _shape_names(wide) == before
    assert wide.evaluate("() => document.querySelector('#layoutPanel .lp-shapes').lastElementChild.classList.contains('lp-seloverlay')")
    overlay = wide.locator("#layoutPanel .lp-seloverlay")
    shape = _shape(wide, "Cross 2")
    for attr in ("x", "y", "width", "height"):
        assert overlay.get_attribute(attr) == shape.get_attribute(attr)


# ---- nested versus crossing ---------------------------------------------------------------------------------------

def test_nested_zones_say_inside_and_contains(wide):
    _pick(wide, "Nested")
    assert _hint(wide, "Big sheet") == "contains 3 zones"
    assert "inside Big sheet" in _hint(wide, "Caption") and "contains 1 zone" in _hint(wide, "Caption")
    assert _hint(wide, "Region") == "inside Big sheet"
    assert _hint(wide, "Inner chart") == "inside Caption and 1 more"            # the smallest enclosing zone is named
    assert _hint(wide, "Free sheet") == ""
    assert "lp-cross" not in _shape(wide, "Big sheet").get_attribute("class")


def test_crossing_zones_say_crosses_and_get_a_transparent_fill_with_a_full_outline(wide):
    _pick(wide, "Crossing")
    assert _hint(wide, "Cross A") == "crosses Cross B and Cross C"
    assert _hint(wide, "Cross B") == "crosses Cross A and Cross C"
    assert _hint(wide, "Alone") == ""
    for name in ("Cross A", "Cross B", "Cross C"):
        style = _shape(wide, name).evaluate("e => { const s = getComputedStyle(e); return [s.fillOpacity, s.strokeOpacity]; }")
        assert float(style[0]) < 1 and float(style[1]) == 1, name
    alone = _shape(wide, "Alone").evaluate("e => getComputedStyle(e).fillOpacity")
    assert float(alone) == 1


def test_identical_rectangles_say_same_position(wide):
    _pick(wide, "Mixed overlap")
    assert _hint(wide, "Same 1") == "same position as Same 2"
    assert _hint(wide, "Same 2") == "same position as Same 1"
    assert _hint(wide, "Tie A") == "" and _hint(wide, "Tie B") == ""


def test_the_one_percent_line_touching_under_and_over(wide):
    _pick(wide, "Threshold")
    assert _hint(wide, "Edge 1") == "" and _hint(wide, "Edge 2") == ""         # sharing only an edge
    assert _hint(wide, "Under 1") == "" and _hint(wide, "Under 2") == ""       # 0.9 percent of the smaller zone
    assert _hint(wide, "Over 1") == "crosses Over 2" and _hint(wide, "Over 2") == "crosses Over 1"   # 1.2 percent


# ---- labels ------------------------------------------------------------------------------------------------------------

LABELS = """() => [...document.querySelectorAll('#layoutPanel .lp-label')].map((t) => {
  const b = t.getBBox(); const z = document.querySelector('#layoutPanel .lp-z[data-i="' + t.dataset.i + '"]');
  return {i: +t.dataset.i, text: t.textContent, kind: t.classList.contains('lp-name') ? 'name' : 'letter',
          x: b.x, y: b.y, w: b.width, h: b.height,
          zx: +z.getAttribute('x'), zy: +z.getAttribute('y'), zw: +z.getAttribute('width'), zh: +z.getAttribute('height')}; })"""


def _scale(page):
    return page.evaluate("""() => { const s = document.querySelector('#layoutPanel svg');
        return s.getBoundingClientRect().width / s.viewBox.baseVal.width; }""")


def test_no_two_labels_overlap_and_each_lies_inside_its_zone(wide):
    for name in ("Label collision", "Mixed overlap", "Nested", "Busy overlap", "Tiny zones"):
        _pick(wide, name)
        labels = wide.evaluate(LABELS)
        tol = 1.5 / _scale(wide)
        assert labels, name
        for a in labels:
            assert a["zx"] - tol <= a["x"] and a["x"] + a["w"] <= a["zx"] + a["zw"] + tol, (name, a)
            assert a["zy"] - tol <= a["y"] and a["y"] + a["h"] <= a["zy"] + a["zh"] + tol, (name, a)
        for n, a in enumerate(labels):
            for b in labels[n + 1:]:
                apart = a["x"] + a["w"] <= b["x"] or b["x"] + b["w"] <= a["x"] or a["y"] + a["h"] <= b["y"] or b["y"] + b["h"] <= a["y"]
                assert apart, (name, a, b)


def test_the_inner_label_wins_a_collision_and_the_outer_name_stays_in_the_list(wide):
    _pick(wide, "Label collision")
    shown = {l["text"]: l for l in wide.evaluate(LABELS)}
    assert any(t.startswith("Inner zone with a long") for t in shown)
    assert not any(t.startswith("Outer") for t in shown)
    assert "Outer zone with a rather long name" in _lines(wide).first.inner_text()


def test_long_small_and_tiny_zones_get_a_cut_name_a_letter_or_nothing(wide):
    _pick(wide, "Label collision")
    labels = {l["i"]: l for l in wide.evaluate(LABELS)}
    index = {n: int(_line(wide, n).get_attribute("data-i")) for n in ("A name far longer", "Narrow sheet", "Sliver")}
    cut = labels[index["A name far longer"]]
    assert cut["kind"] == "name" and cut["text"].endswith("…") and len(cut["text"]) < len("A name far longer than its small zone")
    assert "A name far longer than its small zone" in _line(wide, "A name far longer").inner_text()
    assert labels[index["Narrow sheet"]]["text"] == "S" and labels[index["Narrow sheet"]]["kind"] == "letter"
    assert index["Sliver"] not in labels


def test_the_count_of_names_not_shown_matches_the_drawing(wide):
    for name in ("Label collision", "Busy overlap"):
        _pick(wide, name)
        labelled = wide.evaluate("() => [...document.querySelectorAll('#layoutPanel ol.lp-list:not(.lp-unplaced) > li')]"
                                 ".filter(l => !l.querySelector('.lp-name').textContent.startsWith('Worksheet ')).map(l => +l.dataset.i)")
        drawn = {l["i"] for l in wide.evaluate(LABELS)}
        missing = len([i for i in labelled if i not in drawn])
        words = wide.locator("#layoutPanel .lp-note-extra[data-cond=names]")
        if missing:
            text = words.inner_text()
            assert text.strip().startswith(str(missing)) and "not shown in the drawing; the list has" in text, (name, text)
        else:
            assert words.count() == 0
    _pick(wide, "Label collision")
    assert wide.locator("#layoutPanel .lp-note-extra[data-cond=names]").inner_text().strip().startswith("2 names are not shown")


# ---- the visible note -------------------------------------------------------------------------------------------------

STANDING = "A sketch from stored positions, not how Tableau draws it."


def test_a_clean_dashboard_has_the_standing_sentence_and_a_solid_frame(wide):
    _pick(wide, "Grid")
    assert _note(wide) == STANDING
    assert _conds(wide) == [] and _frame_dashed(wide) is False
    assert wide.locator("#layoutPanel .lp-marker").count() == 0


def test_the_overlap_sentence_appears_only_above_the_threshold_of_crossing_pairs(wide):
    assert wide.evaluate("() => LayoutPanel.OVERLAP_NOTE_MIN") == 5            # the fixtures are built around this number
    _pick(wide, "Edge five")                                                    # 5 crossing pairs: at the threshold
    assert _conds(wide) == [] and _frame_dashed(wide) is False
    assert _hint(wide, "Link 1") == "crosses Link 2"                            # the hints are there all the same
    _pick(wide, "Edge six")                                                     # 6 crossing pairs: above it
    assert _conds(wide) == ["overlap"] and _frame_dashed(wide) == "dashed"
    assert "6 pairs of zones overlap (0 inside another, 6 crossing). The order and look here is for reading; Tableau may draw them differently." in _note(wide)
    _pick(wide, "Mixed overlap")                                                # nested pairs alone never trigger it
    assert "overlap" not in _conds(wide)


def test_the_overlap_counts_equal_the_hints_in_the_list(wide):
    _pick(wide, "Busy overlap")
    counts = wide.evaluate("""() => { const t = {inside: 0, same: 0, crosses: 0};
        document.querySelectorAll('#layoutPanel ol.lp-list:not(.lp-unplaced) > li').forEach((l) => {
          t.inside += +l.dataset.inside; t.same += +l.dataset.same; t.crosses += +l.dataset.crosses; });
        return t; }""")
    nested, crossing = counts["inside"] + counts["same"] // 2, counts["crosses"] // 2
    assert (nested, crossing) == (1, 6)
    assert f"7 pairs of zones overlap ({nested} inside another, {crossing} crossing)" in _note(wide)


def test_each_condition_adds_its_own_sentence_and_a_dashed_frame(wide):
    _pick(wide, "Huge extent")
    assert "extent" in _conds(wide) and "overlap" not in _conds(wide) and _frame_dashed(wide) == "dashed"
    assert ("Positions go past the 100000 grid (to 250000 by 180000) or start below 0; they are drawn as stored and their "
            "unit is not known.") in _note(wide)
    _pick(wide, "Half placed")
    assert _conds(wide) == ["unplaced"]
    assert "3 zones have no stored position and are only in the list." in _note(wide)
    _pick(wide, "Many overlap")
    assert "cap" in _conds(wide)
    assert ("Showing the 200 largest of 250 zones; the smallest are not drawn, so some overlaps may be missing.") in _note(wide)
    assert _frame_dashed(wide) == "dashed"
    _pick(wide, "Grid")                                                         # nothing of it is left on the next dashboard
    assert _note(wide) == STANDING and _frame_dashed(wide) is False


def test_the_note_is_plain_text_outside_the_hidden_part_and_visible_without_scrolling(wide):
    for name in ("Busy overlap", "Mixed overlap"):
        _pick(wide, name)
        note = wide.locator("#layoutPanel .lp-note")
        assert note.get_attribute("role") == "note"
        assert note.evaluate("e => !e.closest('[aria-hidden=true]') && !e.closest('[aria-live]') && !e.hasAttribute('aria-live')")
        box, panel = note.bounding_box(), wide.locator("#layoutPanel").bounding_box()
        assert panel["y"] <= box["y"] and box["y"] + box["height"] <= panel["y"] + panel["height"]
        assert box["y"] + box["height"] <= WIDE["height"]


def test_a_late_answer_for_the_previous_dashboard_changes_nothing(wide):
    # the answer for "Busy" is held back; __late is set once the page's own code has read that answer, so the check
    # below runs after the stale response was handled (and ignored), not after a guessed delay
    wide.evaluate("""() => { const real = window.fetch; window.__late = false;
        window.fetch = (u, o) => {
          if (!/Busy/.test(String(u))) return real(u, o);
          return new Promise((r) => setTimeout(r, 1500)).then(() => real(u, o)).then((res) => {
            const json = res.json.bind(res);
            res.json = () => json().then((d) => { setTimeout(() => { window.__late = true; }, 0); return d; });
            return res;
          });
        }; }""")
    wide.locator("#tableWrap tbody tr[data-pos]").filter(has=wide.get_by_text("Busy overlap", exact=True)).first.click()
    _pick(wide, "Grid")
    wide.wait_for_function("() => window.__late === true", timeout=10_000)
    assert wide.locator("#lpTitle").inner_text() == "Grid"
    assert _note(wide) == STANDING and _conds(wide) == [] and _frame_dashed(wide) is False
    assert wide.locator("#layoutPanel .lp-z").count() == 3


# ---- scaling --------------------------------------------------------------------------------------------------------------

def test_the_view_box_holds_every_zone_and_the_marker_is_only_on_a_huge_extent(wide):
    _pick(wide, "Huge extent")
    box = wide.evaluate("() => { const v = document.querySelector('#layoutPanel svg').viewBox.baseVal; return [v.x, v.y, v.width, v.height]; }")
    assert box == [-5000, -3000, 255000, 183000]
    rects = wide.evaluate("() => [...document.querySelectorAll('#layoutPanel .lp-z')].map(r => [+r.getAttribute('x'), +r.getAttribute('y'), +r.getAttribute('width'), +r.getAttribute('height')])")
    assert len(rects) == 3
    for x, y, w, h in rects:
        assert box[0] <= x and x + w <= box[0] + box[2] and box[1] <= y and y + h <= box[1] + box[3]
    assert wide.locator("#layoutPanel .lp-marker").count() == 1
    assert wide.locator("#layoutPanel .lp-marker text").text_content() == "100000"
    _pick(wide, "Grid")
    assert wide.locator("#layoutPanel .lp-marker").count() == 0
    grid_box = wide.evaluate("() => { const v = document.querySelector('#layoutPanel svg').viewBox.baseVal; return [v.x, v.y, v.width, v.height]; }")
    assert grid_box == [0, 0, 100000, 100000]


def test_outlines_and_label_text_keep_their_screen_size_whatever_the_extent(wide):
    sizes = {}
    for name in ("Grid", "Huge extent"):
        _pick(wide, name)
        stroke = wide.locator("#layoutPanel .lp-z").first.evaluate("e => { const s = getComputedStyle(e); return [s.strokeWidth, s.vectorEffect]; }")
        assert stroke[1] == "non-scaling-stroke" and 1 <= float(stroke[0][:-2]) <= 2
        sizes[name] = wide.evaluate("""() => { const s = document.querySelector('#layoutPanel svg');
            const k = s.getBoundingClientRect().width / s.viewBox.baseVal.width;
            return [...document.querySelectorAll('#layoutPanel .lp-label')].map((t) => +t.getAttribute('font-size') * k); }""")
        assert sizes[name]
    for name, px in sizes.items():
        assert all(abs(p - 12) < 0.05 for p in px), (name, px)


def test_the_drawing_keeps_its_proportion_and_stays_under_70_percent_of_the_window_height(browser, gui_server, wb_path):
    pg = new_page(browser, gui_server, viewport={"width": 1360, "height": 500})
    try:
        _load(pg, wb_path)
        _open(pg, "dashboards")
        pg.wait_for_selector("#tableWrap tbody tr[data-pos]")
        for name in ("Grid", "Huge extent", "Label collision"):
            _pick(pg, name)
            r = pg.evaluate("""() => { const s = document.querySelector('#layoutPanel svg'); const b = s.getBoundingClientRect();
                const v = s.viewBox.baseVal; return [b.width, b.height, v.width / v.height]; }""")
            assert r[1] <= 500 * 0.7 + 1, name
            assert abs(r[0] / r[1] - r[2]) < 0.02, name
    finally:
        pg.ctx.close()


def test_the_extent_comes_from_all_placed_zones_before_the_cap(wide):
    _pick(wide, "Many overlap")
    box = wide.evaluate("() => { const v = document.querySelector('#layoutPanel svg').viewBox.baseVal; return [v.x + v.width, v.y + v.height]; }")
    assert box[0] == 190500                                  # the dropped zone at x = 190000 still reaches the frame
    assert box[1] == 99000


# ---- tiny zones -----------------------------------------------------------------------------------------------------------

def test_tiny_zones_are_drawn_at_least_three_pixels_without_fill_and_flagged(wide):
    _pick(wide, "Tiny zones")
    k = _scale(wide)
    for name, flagged in (("Tiny 100", True), ("Tiny 10", True), ("Tiny 1000", False), ("Tiny inside", True)):
        shape = _shape(wide, name)
        w, h = (float(shape.get_attribute(a)) * k for a in ("width", "height"))
        assert w >= 3 - 0.01 and h >= 3 - 0.01, name
        flag = _line(wide, name).locator(".lp-flag").inner_text()
        assert (flag == "drawn larger than stored") == flagged, name
        assert ("lp-tiny" in shape.get_attribute("class")) == flagged, name
        if flagged:
            assert shape.evaluate("e => getComputedStyle(e).fill") == "none"
    assert _shape(wide, "Tiny 100").evaluate("e => e.getBBox().width") * k < 3.5            # not grown beyond the minimum
    assert wide.locator("#layoutPanel .lp-note-extra[data-cond=tiny]").inner_text().strip() == "3 tiny zones are drawn larger than they are."
    assert _lines(wide).count() == 5                                                       # every tiny zone is still a line


def _drawn_width(page):
    return page.evaluate("() => +document.querySelector('#layoutPanel svg').getAttribute('width')")


def _resize(page, width, drawn):
    """Set the window width and wait until the drawing has been redrawn at a size on the wanted side of `drawn`."""
    page.set_viewport_size({"width": width, "height": 900})
    test = "w => { const s = document.querySelector('#layoutPanel svg'); return s && +s.getAttribute('width') %s w }"
    page.wait_for_function(test % ("<" if width < WIDE["width"] else ">="), arg=drawn, timeout=10_000)
    page.wait_for_selector("#layoutPanel .lp-fig[data-settled='1']", timeout=10_000)


def test_resizing_the_window_recomputes_the_tiny_zones_and_the_labels(wide):
    # The drawing is at most 560 px wide (and here height-capped to about 446), so only a window narrow enough to
    # squeeze it changes the scale. Tiny 1000 is 1000/100000 of the width: 4.5 px at full size, under the 3 px
    # minimum once the drawing is under 300 px wide.
    _pick(wide, "Tiny zones")
    full = _drawn_width(wide)
    assert 400 < full <= 560
    assert "3 tiny zones" in _note(wide)
    assert "lp-tiny" not in _shape(wide, "Tiny 1000").get_attribute("class")
    assert _line(wide, "Tiny 1000").locator(".lp-flag").inner_text() == ""
    before = len(wide.evaluate(LABELS))
    _resize(wide, 280, 300)
    assert _drawn_width(wide) < 300
    assert "4 tiny zones are drawn larger than they are." in _note(wide)
    assert "lp-tiny" in _shape(wide, "Tiny 1000").get_attribute("class")
    assert _line(wide, "Tiny 1000").locator(".lp-flag").inner_text() == "drawn larger than stored"
    _resize(wide, 1360, 400)
    assert _drawn_width(wide) == full
    assert "3 tiny zones are drawn larger than they are." in _note(wide)
    assert "lp-tiny" not in _shape(wide, "Tiny 1000").get_attribute("class")
    assert len(wide.evaluate(LABELS)) == before
    assert wide.js_errors == []


# ---- caps and the empty state -----------------------------------------------------------------------------------------

def test_a_250_zone_dashboard_shows_200_shapes_and_200_lines_and_says_so(wide):
    _pick(wide, "Many overlap")
    assert wide.locator("#layoutPanel .lp-z").count() == 200 == _lines(wide).count()
    assert "200 largest of 250" in wide.locator("#layoutPanel .lp-count").inner_text()
    assert wide.evaluate("() => document.querySelectorAll('#layoutPanel *').length") < 2200
    widths = wide.evaluate("() => [...document.querySelectorAll('#layoutPanel .lp-z')].map(r => +r.getAttribute('width'))")
    assert min(widths) >= 3000                                                              # the 50 tiny ones are the dropped ones
    hints = _lines(wide).locator(".lp-hint").all_inner_texts()
    assert set(hints) == {""}                                                              # the overlays are gone, so no hint


def test_a_dashboard_with_no_positions_shows_the_empty_state_and_still_lists_its_zones(wide):
    _pick(wide, "All unplaced")
    assert "No positions are stored for this dashboard." in wide.locator("#layoutPanel .lp-empty").inner_text()
    assert wide.locator("#layoutPanel svg").count() == 0 and wide.locator("#layoutPanel .lp-note").count() == 0
    names = wide.locator("#layoutPanel ol.lp-unplaced .lp-name").all_inner_texts()
    assert names == ["Lost one", "Lost two"]
    _pick(wide, "Half placed")
    assert wide.locator("#layoutPanel ol.lp-unplaced li").count() == 3
    assert _lines(wide).count() == 1
    assert wide.locator("#layoutPanel ol.lp-unplaced li[tabindex]").count() == 0
