"""The GUI table, tested hard.

Four parts:

1. Regressions for bugs found in review (settings following column names, the filter form's keys,
   focus in the Columns menu, a column drag that ends over a header).
2. The search, filter and sort pipeline checked against an independent Python oracle on synthetic data
   full of awkward values (nulls, duplicates, unicode, booleans, opaque datasource ids).
3. Windowing invariants: for any table size, density and scroll position the rows in the page are
   exactly the ones that should be there, in the right place.
4. A seeded random walk that drives the real UI and checks, after every step, that what is on screen
   agrees with a model of what should be. A failure prints the seed and the steps, so it can be replayed.

Shares its browser fixtures and helpers with test_gui_browser.py.
"""

from __future__ import annotations

import json
import os
import random
import re
import urllib.request

import pytest

from test_gui_browser import (  # noqa: F401  (fixtures and helpers shared with the other GUI tests)
    _NEEDS_MEMORY,
    _copy_column,
    _enough_memory,
    _header,
    _last_render_ms,
    _load,
    _open,
    _open_column_menu,
    _wait_meta,
    wait_settled,
    new_page,
)

REAL_ID = "federated.0grgaor1pd01yy1f0yr380of1ags"  # the datasource of the wenjie fixture
CAPTION = "Sheet1 (test_county)"
OPAQUE = "federated.zzzzzzzzzzzzzzzzzzzzzzzz9999"  # an unreadable id nobody gave a caption
PLAIN = "plain-source"

_FEED_ROWS = """
(payload) => {
  const real = window.fetch;
  window.fetch = (u, o) => String(u).startsWith('/table?name=fields')
    ? Promise.resolve(new Response(JSON.stringify(payload), {status: 200, headers: {'Content-Type': 'application/json'}}))
    : real(u, o);
}
"""


def open_synthetic(page, wenjie_path, columns, rows):
    """Load the real workbook (so /load gives datasource captions), then make the Fields table show `rows`."""
    _load(page, wenjie_path)
    page.evaluate(_FEED_ROWS, {"columns": columns, "data": rows})
    page.click('.nav-item[data-table="fields"]')
    _wait_meta(page, f"{len(rows)} row(s)")


def render_stamp(page):
    return page.evaluate(
        "() => { const m = performance.getEntriesByName('py-tbparse:table'); return m.length ? m[m.length - 1].startTime : -1; }"
    )


def wait_render(page, stamp):
    """Wait until the table has redrawn since `stamp` (filters are debounced and sorts glide)."""
    page.wait_for_function(
        "(s) => { const m = performance.getEntriesByName('py-tbparse:table'); return m.length > 0 && m[m.length - 1].startTime !== s; }",
        arg=stamp,
        timeout=15_000,
    )
    wait_settled(page)  # the sort glide and the entrance rise move boxes until they end


# ====================================================================================== 1. regressions


def test_settings_follow_column_names_when_the_table_changes_shape(page, wenjie_path):
    """Review bug 1. Field renames gains a `kind` column at the front (internal columns come last) when widened to the whole report;
    hidden columns, filters, widths and the sort must stay with their columns, not their positions."""
    from playwright.sync_api import expect

    _load(page, wenjie_path)
    _open(page, "field-renames")
    _wait_meta(page, "3 row(s)")
    before = page.eval_on_selector_all("#tableWrap th .th-label", "els => els.map(e => e.textContent)")
    assert "datasource" in before and "kind" not in before

    _open_column_menu(page, "datasource")
    page.click("#menu >> text=Hide column")
    page.wait_for_function("(n) => document.querySelectorAll('#tableWrap th:not(.sel)').length === n - 1", arg=len(before), timeout=10_000)
    _open_column_menu(page, "current")
    page.click("#menu >> text=Filter this column")
    page.fill("#menu input", "count")
    page.keyboard.press("Enter")
    _wait_meta(page, "1 of 3 row(s)")
    _open_column_menu(page, "name")
    page.click("#menu >> text=Wider")
    page.wait_for_timeout(200)
    width_before = _header(page, "name").bounding_box()["width"]
    _header(page, "suggested").click()
    expect(_header(page, "suggested")).to_have_attribute("aria-sort", "ascending")

    # widen the table to everything in the report: a `kind` column appears first and the rows change
    page.select_option("#renameKinds", "all")
    page.wait_for_function("() => [...document.querySelectorAll('#tableWrap th .th-label')].some(e => e.textContent === 'kind')", timeout=15_000)
    labels = page.eval_on_selector_all("#tableWrap th .th-label", "els => els.map(e => e.textContent)")
    assert "kind" in labels, labels                         # the new column is visible, not hidden by position
    assert "datasource" not in labels                       # the hidden one is still hidden
    assert page.text_content("#colsBtn") == "Columns (1 hidden)"
    chip = page.locator("#chips .chip")
    assert chip.count() == 1 and chip.get_attribute("aria-label") == "Remove filter: current contains count"
    # the filter still applies to `current`, not to whatever now sits at its old position
    current = _copy_column(page, "current")
    assert current and all("count" in value.lower() for value in current), current
    # the width and the sort followed their columns too
    assert abs(_header(page, "name").bounding_box()["width"] - width_before) < 2
    expect(_header(page, "suggested")).to_have_attribute("aria-sort", "ascending")
    assert page.js_errors == []


def test_a_filter_for_a_column_the_table_no_longer_has_waits_quietly(page, wenjie_path):
    _load(page, wenjie_path)
    _open(page, "field-renames")
    _wait_meta(page, "3 row(s)")
    page.select_option("#renameKinds", "all")
    page.wait_for_function("() => [...document.querySelectorAll('#tableWrap th .th-label')].some(e => e.textContent === 'kind')", timeout=15_000)
    _open_column_menu(page, "kind")
    page.click("#menu >> text=Filter this column")
    page.fill("#menu input", "field")
    page.keyboard.press("Enter")
    page.wait_for_selector("#chips .chip", timeout=10_000)
    page.select_option("#renameKinds", "")
    page.wait_for_function("() => ![...document.querySelectorAll('#tableWrap th .th-label')].some(e => e.textContent === 'kind')", timeout=15_000)
    # `kind` is gone, so its filter is not applied, not shown and not counted
    assert page.locator("#chips .chip").count() == 0 and page.is_hidden("#chips")
    _wait_meta(page, "3 row(s)")
    page.select_option("#renameKinds", "all")
    page.wait_for_function("() => [...document.querySelectorAll('#tableWrap th .th-label')].some(e => e.textContent === 'kind')", timeout=15_000)
    assert page.locator("#chips .chip").count() == 1  # and it is back when its column is
    assert page.js_errors == []


def test_filter_form_keeps_ordinary_text_keys(page, wenjie_path):
    """Review bug 2. Tab, Home, End and the arrows belong to the text box, not to the menu."""
    from playwright.sync_api import expect

    _load(page, wenjie_path)
    _open(page, "fields")
    _wait_meta(page, "55 row(s)")
    _open_column_menu(page, "datatype")
    page.click("#menu >> text=Filter this column")
    box = page.locator("#menu input")
    assert page.evaluate("() => document.activeElement === document.querySelector('#menu input')")
    page.keyboard.type("string")
    page.keyboard.press("Home")
    page.keyboard.type("X")
    assert box.input_value() == "Xstring"           # Home moved the cursor; it did not jump to a button
    page.keyboard.press("End")
    page.keyboard.type("Y")
    assert box.input_value() == "XstringY"
    page.keyboard.press("ArrowLeft")
    page.keyboard.press("ArrowLeft")
    page.keyboard.type("Z")
    assert box.input_value() == "XstrinZgY"
    assert page.evaluate("() => document.activeElement === document.querySelector('#menu input')")
    # Tab goes on to the Apply button and the form stays open with what was typed
    page.keyboard.press("Tab")
    assert page.evaluate("() => document.activeElement.textContent.trim()") == "Apply"
    assert page.is_visible("#menu") and box.input_value() == "XstrinZgY"
    # Escape closes it and returns focus to the header it came from
    page.keyboard.press("Escape")
    assert page.is_hidden("#menu")
    assert page.evaluate("() => document.activeElement.tagName") == "TH"
    # and a form submitted with the keyboard alone works
    _open_column_menu(page, "datatype")
    page.click("#menu >> text=Filter this column")
    page.keyboard.type("integer")
    page.keyboard.press("Tab")
    page.keyboard.press("Enter")  # on the Apply button
    page.wait_for_selector("#chips .chip", timeout=10_000)
    assert set(_copy_column(page, "datatype")) == {"integer"}
    assert page.js_errors == []


def test_tabbing_out_of_the_filter_form_closes_it(page, wenjie_path):
    _load(page, wenjie_path)
    _open(page, "fields")
    _wait_meta(page, "55 row(s)")
    _open_column_menu(page, "datatype")
    page.click("#menu >> text=Filter this column")
    page.keyboard.type("abc")
    page.focus("#filter")  # focus moves to something outside the form
    page.wait_for_selector("#menu", state="hidden", timeout=5_000)


def test_columns_menu_keeps_focus_on_the_item_you_toggled(page, wenjie_path):
    """Review bug 3. Toggling an item changes which others are available; focus must not jump."""
    _load(page, wenjie_path)
    _open(page, "fields")
    _wait_meta(page, "55 row(s)")
    columns = page.eval_on_selector_all("#tableWrap th .th-label", "els => els.map(e => e.textContent)")
    page.click("#colsBtn")
    show_all = page.locator("#menu button", has_text="Show all columns")
    # nothing hidden: "Show all columns" is unavailable but reachable, and the first column item has focus
    assert show_all.get_attribute("aria-disabled") == "true"
    first = columns[0]
    assert page.evaluate("() => document.activeElement.textContent.trim().replace(/^\\u2713/, '')") == first
    page.keyboard.press("Enter")      # hide the first column
    page.wait_for_function("(n) => document.querySelectorAll('#tableWrap th:not(.sel)').length === n - 1", arg=len(columns), timeout=10_000)
    assert show_all.get_attribute("aria-disabled") is None                      # now available
    assert page.evaluate("() => document.activeElement.textContent.trim().replace(/^\\u2713/, '')") == first   # focus stayed
    page.keyboard.press("Enter")      # a second Enter toggles the SAME item back; it must not "show all"
    page.wait_for_function("(n) => document.querySelectorAll('#tableWrap th').length === n", arg=len(columns), timeout=10_000)
    assert page.evaluate("() => document.activeElement.textContent.trim().replace(/^\\u2713/, '')") == first
    assert show_all.get_attribute("aria-disabled") == "true"
    # clicking an unavailable item does nothing at all
    show_all.click(force=True)
    assert page.eval_on_selector_all("#tableWrap th", "els => els.length") == len(columns)
    assert page.is_visible("#menu")
    assert page.js_errors == []


def test_arrow_keys_visit_unavailable_menu_items(page, wenjie_path):
    _load(page, wenjie_path)
    _open(page, "fields")
    _wait_meta(page, "55 row(s)")
    _open_column_menu(page, "name")
    seen = []
    for _ in range(11):
        seen.append(page.evaluate("() => document.activeElement.textContent.trim()"))
        page.keyboard.press("ArrowDown")
    assert seen[:3] == ["Sort ascending", "Sort descending", "Clear sort"]
    assert len(set(seen[:10])) == 10             # the menu's ten items, none skipped
    assert seen[10] == "Sort ascending"          # and the list wraps around


def test_a_column_drag_that_ends_over_the_header_does_not_sort_it(page, wenjie_path):
    """Review bug 4. Drag a grip far left of its minimum width and let go over the label."""
    from playwright.sync_api import expect

    _load(page, wenjie_path)
    _open(page, "fields")
    _wait_meta(page, "55 row(s)")
    th = _header(page, "caption")
    box = th.bounding_box()
    grip = th.locator(".col-resize").bounding_box()
    x, y = grip["x"] + grip["width"] / 2, grip["y"] + grip["height"] / 2
    page.mouse.move(x, y)
    page.mouse.down()
    page.mouse.move(box["x"] + 20, y, steps=6)     # far left: the column stops at its minimum width
    page.mouse.up()                                 # released over the same header's label
    page.wait_for_timeout(150)
    assert abs(_header(page, "caption").bounding_box()["width"] - 80) < 2   # stopped at the minimum
    expect(_header(page, "caption")).to_have_attribute("aria-sort", "none")   # and it did not sort
    # a real click on the label straight afterwards still sorts (it is not swallowed)
    _header(page, "caption").click(position={"x": 12, "y": 10})
    expect(_header(page, "caption")).to_have_attribute("aria-sort", "ascending")


def test_a_cancelled_column_drag_lets_go_cleanly(page, wenjie_path):
    _load(page, wenjie_path)
    _open(page, "fields")
    _wait_meta(page, "55 row(s)")
    th = _header(page, "name")
    grip = th.locator(".col-resize").bounding_box()
    x, y = grip["x"] + grip["width"] / 2, grip["y"] + grip["height"] / 2
    page.mouse.move(x, y)
    page.mouse.down()
    page.mouse.move(x + 30, y, steps=3)
    during = _header(page, "name").bounding_box()["width"]
    page.evaluate("() => window.dispatchEvent(new PointerEvent('pointercancel', {bubbles: true}))")
    page.mouse.move(x + 120, y, steps=3)            # a leaked listener would keep resizing
    assert abs(_header(page, "name").bounding_box()["width"] - during) < 2
    page.mouse.up()
    assert page.js_errors == []


def test_a_menu_opened_right_after_focusing_an_offscreen_header_stays_open(page, wenjie_path):
    """Focusing a header that is out of view scrolls the table; that scroll event arrives after the menu
    has opened and must not close it. (Found by the random walk.)"""
    _load(page, wenjie_path)
    _open(page, "fields")
    _wait_meta(page, "55 row(s)")
    last = page.eval_on_selector_all("#tableWrap th .th-label", "els => els[els.length - 1].textContent")
    page.evaluate("() => { document.getElementById('tableWrap').scrollLeft = 0; }")
    assert page.evaluate("() => document.getElementById('tableWrap').scrollWidth > document.getElementById('tableWrap').clientWidth")
    page.wait_for_function("() => document.getElementById('tableWrap').scrollLeft === 0")
    _header(page, last).focus()
    page.keyboard.press("Alt+ArrowDown")
    page.wait_for_timeout(400)
    assert page.is_visible("#menu"), "the menu was closed by the scroll that focusing the header caused"
    # but a real scroll, by the user, still closes it
    page.evaluate("() => { document.getElementById('tableWrap').scrollLeft = 0; }")
    page.wait_for_selector("#menu", state="hidden", timeout=5_000)


def test_a_late_scroll_event_from_a_redraw_does_not_close_a_menu_opened_meanwhile(page, wenjie_path):
    """A sort redraws the table inside a view transition and restores its scroll position; the scroll
    event for that can arrive late, after a quick user has opened a column menu. (Found by the random walk.)"""
    from playwright.sync_api import expect

    _load(page, wenjie_path)
    _open(page, "fields")
    _wait_meta(page, "55 row(s)")
    page.evaluate("() => { document.getElementById('tableWrap').scrollLeft = 200; }")
    page.wait_for_function("() => document.getElementById('tableWrap').scrollLeft === 200")
    for _ in range(2):
        _header(page, "role").focus()
        page.keyboard.press("Space")                 # redraw (glides), keeping scrollLeft = 200
        _header(page, "datatype").focus()
        page.keyboard.press("Alt+ArrowDown")         # and open a menu straight away
        page.wait_for_timeout(700)                   # well after the transition and the late scroll event
        assert page.is_visible("#menu"), "a scroll event from the redraw closed the menu"
        page.keyboard.press("Escape")
    expect(_header(page, "role")).to_have_attribute("aria-sort", "descending")   # two presses: asc, then desc


def test_only_sorting_glides_and_the_page_takes_clicks_once_the_glide_is_over(page, wenjie_path):
    """While a view transition runs the browser sends clicks to the page root, and CSS cannot change that. So
    only a sort starts one (typing in the filter or adding a chip never does), it is short, and a click after it
    works."""
    if not page.evaluate("() => !!document.startViewTransition"):
        pytest.skip("this browser has no View Transitions API")
    _load(page, wenjie_path)
    _open(page, "fields")
    _wait_meta(page, "55 row(s)")
    page.evaluate(
        "() => { window.__vt = 0; const f = document.startViewTransition.bind(document);"
        " document.startViewTransition = (cb) => { window.__vt++; return f(cb); }; }"
    )
    set_search(page, "a")
    set_search(page, "")
    _open_column_menu(page, "datatype")
    page.click("#menu >> text=Filter this column")
    page.fill("#menu input", "string")
    stamp = render_stamp(page)
    page.keyboard.press("Enter")
    wait_render(page, stamp)
    page.click("#chips .chip")
    _wait_meta(page, "55 row(s)")
    assert page.evaluate("() => window.__vt") == 0, "filtering must not start a view transition"
    stamp = render_stamp(page)
    _header(page, "name").focus()
    page.keyboard.press("Space")
    wait_render(page, stamp)
    assert page.evaluate("() => window.__vt") == 1
    page.wait_for_timeout(500)                     # the glide is 120 ms plus the browser's setup
    page.locator("#tableWrap tbody tr[data-pos]").nth(1).click(position={"x": 14, "y": 8})
    page.wait_for_selector("#drawer.show", timeout=5_000)
    assert page.js_errors == []


# ====================================================================================== 2. pipeline vs oracle


def js_str(value):
    """What the page's String(value) gives for a JSON value."""
    if value is None:
        return ""
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, float) and value == int(value):
        return str(int(value))
    return str(value)


def shown_datasource(value):
    if value == REAL_ID:
        return CAPTION
    if re.fullmatch(r"[a-z]+\.[0-9a-z]{20,}", value):
        dot = value.index(".")
        return value[: dot + 7] + "…" + value[-4:]
    return value


def search_text(column, value):
    raw = js_str(value)
    return shown_datasource(raw) + " " + raw if column == "datasource" and value is not None else raw


def natural_key(text):
    return [(0, int(t)) if t.isdigit() else (1, t.lower()) for t in re.findall(r"\d+|\D+", text)]


COLUMNS = ["datasource", "name", "n", "x", "flag", "text"]


def make_rows(count=120, seed=7):
    rnd = random.Random(seed)
    words = ["alpha", "bravo", "charlie", "delta", "echo", "foxtrot", "golf", "hotel", "india", "juliet", "kilo", "lima"]
    texts = ["apple", "Zebra", "école", "Ångström", "日本語", "naive", "ÉCOLE2", "", "mango", "Mango9", "x"]
    rows, used = [], set()
    for _ in range(count):
        name = f"{rnd.choice(words)}{rnd.randint(1, 120)}"
        while name.lower() in used:
            name = f"{rnd.choice(words)}{rnd.randint(1, 900)}"
        used.add(name.lower())
        if rnd.random() < 0.3:
            name = name.capitalize()  # case varies, but there are never two names that differ only by case
        rows.append([
            rnd.choice([REAL_ID, OPAQUE, PLAIN]), name,
            None if rnd.random() < 0.15 else rnd.randint(-20, 60),
            None if rnd.random() < 0.15 else round(rnd.uniform(-50, 50), 2),
            rnd.choice([True, False, None]), rnd.choice(texts),
        ])
    return rows


def names_after(rows, search="", chips=(), hidden=(), sort=None):
    """The `name` column the page should show: an oracle written independently of the page's code."""
    visible = [c for c in COLUMNS if c not in hidden]
    keep = []
    for r in rows:
        if search:
            hay = "\x01".join(search_text(c, r[COLUMNS.index(c)]) for c in visible).lower()
            if search.lower() not in hay:
                continue
        if any(text.lower() not in search_text(col, r[COLUMNS.index(col)]).lower() for col, text in chips):
            continue
        keep.append(r)
    if sort:
        col, direction = sort
        ci = COLUMNS.index(col)
        present = [r for r in keep if r[ci] is not None]
        missing = [r for r in keep if r[ci] is None]
        if col in ("n", "x"):
            present.sort(key=lambda r: r[ci], reverse=direction < 0)
        elif col == "name":
            present.sort(key=lambda r: natural_key(r[ci]), reverse=direction < 0)
        else:
            present.sort(key=lambda r: js_str(r[ci]), reverse=direction < 0)
        keep = present + missing  # nulls last, whichever way
    return [r[1] for r in keep]


@pytest.fixture
def synthetic(page, wenjie_path):
    rows = make_rows()
    open_synthetic(page, wenjie_path, COLUMNS, rows)
    return page, rows


def click_sort(page, column, times):
    for _ in range(times):
        stamp = render_stamp(page)
        _header(page, column).click()
        wait_render(page, stamp)


def set_search(page, text):
    stamp = render_stamp(page)
    page.fill("#filter", text)
    wait_render(page, stamp)


@pytest.mark.parametrize("column", ["n", "x"])
def test_numeric_columns_sort_numerically_with_nulls_last_both_ways(synthetic, column):
    page, rows = synthetic
    click_sort(page, column, 1)
    assert _copy_column(page, "name") == names_after(rows, sort=(column, 1))
    values = _copy_column(page, column)
    assert values[-1] == "" and values[0] != ""                       # nulls are at the end
    nums = [float(v) for v in values if v != ""]
    assert nums == sorted(nums)
    click_sort(page, column, 1)
    assert _copy_column(page, "name") == names_after(rows, sort=(column, -1))
    values = _copy_column(page, column)
    assert values[-1] == ""                                            # still last when descending
    nums = [float(v) for v in values if v != ""]
    assert nums == sorted(nums, reverse=True)
    assert page.js_errors == []


def test_text_columns_sort_naturally_and_ignore_case(synthetic):
    page, rows = synthetic
    click_sort(page, "name", 1)
    ascending = _copy_column(page, "name")
    assert ascending == names_after(rows, sort=("name", 1))
    click_sort(page, "name", 1)
    assert _copy_column(page, "name") == names_after(rows, sort=("name", -1))
    click_sort(page, "name", 1)  # third click clears the sort
    assert _copy_column(page, "name") == names_after(rows)


def test_boolean_and_nullable_text_columns_sort_with_nulls_last(synthetic):
    page, rows = synthetic
    click_sort(page, "flag", 1)
    flags = _copy_column(page, "flag")
    assert flags == sorted(f for f in flags if f != "") + [""] * flags.count("")
    assert flags[:flags.count("false")] == ["false"] * flags.count("false")
    assert _copy_column(page, "name") == names_after(rows, sort=("flag", 1))


@pytest.mark.parametrize("column", COLUMNS)
@pytest.mark.parametrize("clicks", [1, 2])
def test_any_sort_is_a_sorted_permutation(synthetic, column, clicks):
    """For every column and direction: the same rows come back, ordered by the browser's own collator,
    with empty values last. (An independent check that does not depend on how ties are ordered.)"""
    page, rows = synthetic
    click_sort(page, column, clicks)
    values = _copy_column(page, column)
    assert len(values) == len(rows)
    assert sorted(values) == sorted(js_str(r[COLUMNS.index(column)]) for r in rows)   # a permutation
    # Nulls come last whichever way the column is sorted. An empty STRING is a real value (the `text`
    # column has some) and sorts with the others, so only the true nulls are expected at the end.
    null_count = sum(1 for r in rows if r[COLUMNS.index(column)] is None)
    ok = page.evaluate(
        """([values, dir, nullCount, numeric]) => {
          const collator = new Intl.Collator(undefined, {numeric: true, sensitivity: 'base'});
          const real = values.slice(0, values.length - nullCount);
          const tail = values.slice(values.length - nullCount);
          if (!tail.every((v) => v === '')) return 'the nulls are not last';
          for (let i = 1; i < real.length; i++) {
            const c = numeric ? Number(real[i - 1]) - Number(real[i]) : collator.compare(real[i - 1], real[i]);
            if (dir * c > 0) return 'out of order at ' + i + ': ' + real[i - 1] + ' / ' + real[i];
          }
          return 'ok';
        }""",
        [values, 1 if clicks == 1 else -1, null_count, column in ("n", "x")],
    )
    assert ok == "ok", ok


SEARCHES = [
    "alpha", "ALPHA", "Alpha1", "1", "true", "false", "sheet1", "SHEET1 (TEST", "test_county", "federated.0grg",
    "federated.zzzz", "zzzzzzzzzzzzzzzzzzzz", "plain-source", "日本", "école", "ÉCOLE", "-",
    "no-such-thing-anywhere", "  alpha  ",
]


@pytest.mark.parametrize("query", SEARCHES)
def test_search_matches_what_the_oracle_says(synthetic, query):
    page, rows = synthetic
    set_search(page, query)
    assert _copy_column(page, "name") == names_after(rows, search=query.strip())
    expected = len(names_after(rows, search=query.strip()))
    assert page.get_attribute("#tableWrap table", "aria-rowcount") == str(expected + 1)
    assert page.js_errors == []


def test_search_reads_the_caption_and_the_real_id_alike(synthetic):
    page, rows = synthetic
    expect_ids = {r[1] for r in rows if r[0] == REAL_ID}
    for query in ("test_county", REAL_ID[:20], "sheet1 (test"):
        set_search(page, query)
        assert set(_copy_column(page, "name")) >= expect_ids, query
    assert page.locator("#tableWrap tbody tr[data-pos] td").first.text_content() == CAPTION


def test_an_opaque_datasource_id_is_shortened_and_keeps_its_full_id_on_hover(synthetic):
    page, rows = synthetic
    set_search(page, "federated.zzzz")
    cell = page.locator("#tableWrap tbody tr[data-pos] td").first
    assert cell.text_content() == shown_datasource(OPAQUE)
    assert OPAQUE in cell.get_attribute("title")
    assert set(_copy_column(page, "datasource")) == {OPAQUE}                      # copying gives the real id


CHIP_CASES = [
    ([("flag", "true")], "", None),
    ([("text", "a"), ("flag", "false")], "", None),
    ([("datasource", "county")], "", ("n", -1)),
    ([("n", "1")], "alpha", ("name", 1)),
    ([("x", "-")], "", ("x", 1)),
    ([("name", "zzz")], "", None),
]


@pytest.mark.parametrize("chips,search,sort", CHIP_CASES)
def test_chips_search_and_sort_combine_like_the_oracle(synthetic, chips, search, sort):
    page, rows = synthetic
    for column, text in chips:
        _open_column_menu(page, column)
        page.click("#menu >> text=Filter this column")
        page.fill("#menu input", text)
        stamp = render_stamp(page)
        page.keyboard.press("Enter")
        wait_render(page, stamp)
    if search:
        set_search(page, search)
    if sort:
        column, direction = sort
        click_sort(page, column, 1 if direction == 1 else 2)
    expected = names_after(rows, search=search, chips=chips, sort=sort)
    if expected:
        assert _copy_column(page, "name") == expected
    else:
        page.wait_for_selector("#tableWrap .empty-state", timeout=10_000)
    assert page.locator("#chips .chip").count() == len(chips)
    assert page.js_errors == []


def test_hidden_columns_leave_the_search_and_come_back(synthetic):
    page, rows = synthetic
    set_search(page, "true")
    with_flag = names_after(rows, search="true")
    assert with_flag and _copy_column(page, "name") == with_flag
    _open_column_menu(page, "flag")
    stamp = render_stamp(page)
    page.click("#menu >> text=Hide column")
    wait_render(page, stamp)
    without_flag = names_after(rows, search="true", hidden={"flag"})
    page.wait_for_function("(n) => document.getElementById('meta').textContent.startsWith(n)", arg=f"{len(without_flag)} of", timeout=10_000)
    if without_flag:
        assert _copy_column(page, "name") == without_flag
    page.click("#colsBtn")
    stamp = render_stamp(page)
    page.locator("#menu button[role=menuitemcheckbox]", has_text="flag").click()
    wait_render(page, stamp)
    page.keyboard.press("Escape")
    page.wait_for_function("(n) => document.getElementById('meta').textContent.startsWith(n)", arg=f"{len(with_flag)} of", timeout=10_000)
    assert _copy_column(page, "name") == with_flag


def test_switching_tables_keeps_column_choices_but_resets_search_and_sort(synthetic):
    page, rows = synthetic
    _open_column_menu(page, "x")
    stamp = render_stamp(page)
    page.click("#menu >> text=Hide column")
    wait_render(page, stamp)
    click_sort(page, "name", 1)
    set_search(page, "alpha")
    _open(page, "relations")
    _wait_meta(page, "6 row(s)")
    assert page.input_value("#filter") == ""
    _open(page, "fields")
    page.wait_for_selector("#tableWrap table", timeout=10_000)
    # the old table stays in the page while the new one loads, and the label is reset until it renders
    page.wait_for_function("() => document.getElementById('colsBtn').textContent === 'Columns (1 hidden)'", timeout=10_000)   # kept
    assert page.input_value("#filter") == ""                                       # reset
    assert page.eval_on_selector_all("#tableWrap th[aria-sort='ascending']", "els => els.length") == 0   # reset


# ====================================================================================== 3. windowing


def window_facts(page):
    return page.evaluate(
        """() => {
          const wrap = document.getElementById('tableWrap');
          const table = wrap.querySelector('table');
          if (!table) return null;
          const rows = [...wrap.querySelectorAll('tbody tr[data-pos]')];
          const spacers = [...wrap.querySelectorAll('tbody tr.spacer td')].map((td) => parseFloat(td.style.height));
          return {
            positions: rows.map((r) => Number(r.dataset.pos)),
            rowindex: rows.map((r) => Number(r.getAttribute('aria-rowindex'))),
            first: rows.map((r) => r.cells[0].textContent),
            spacers,
            rowH: rows.length ? rows[0].getBoundingClientRect().height : 0,
            scrollTop: wrap.scrollTop,
            area: wrap.clientHeight - wrap.querySelector('thead').getBoundingClientRect().height,
            rowcount: Number(table.getAttribute('aria-rowcount')),
            tabstops: rows.filter((r) => r.tabIndex === 0).length,
          };
        }"""
    )


def check_window(facts, n, label=""):
    pos = facts["positions"]
    where = f"{label}: {pos[:2]}..{pos[-2:]} of {n}"
    assert facts["rowcount"] == n + 1, where
    assert pos == list(range(pos[0], pos[0] + len(pos))), "rows are not consecutive " + where
    assert facts["rowindex"] == [p + 2 for p in pos], "aria-rowindex is off " + where
    assert facts["first"] == [f"r{p}" for p in pos], "a row shows the wrong data " + where
    assert len(pos) <= 100, "too many rows in the page " + where
    h = facts["rowH"]
    total = sum(facts["spacers"]) + len(pos) * h
    assert abs(total - n * h) <= 2, f"spacers and rows do not add up to the table height {where}: {total} vs {n * h}"
    first_visible = int(facts["scrollTop"] // h)
    last_visible = min(n, int(-(-(facts["scrollTop"] + facts["area"]) // h)))
    assert pos[0] <= first_visible and pos[-1] + 1 >= last_visible, "the viewport is not covered " + where
    assert facts["tabstops"] == 1, "the table must have exactly one row tab stop " + where


@pytest.mark.parametrize("density", ["comfortable", "compact"])
@pytest.mark.parametrize("n", [1, 2, 22, 23, 24, 57, 300, 1000])
def test_window_is_exactly_the_right_rows_at_every_scroll_position(page, wenjie_path, n, density):
    rows = [[f"r{i}", i] for i in range(n)]
    open_synthetic(page, wenjie_path, ["name", "n"], rows)
    if density == "compact":
        page.click("#densityBtn")
        page.wait_for_function("() => document.documentElement.dataset.density === 'compact'", timeout=10_000)
        page.wait_for_function("() => Math.abs(document.querySelector('#tableWrap tbody tr[data-pos]').getBoundingClientRect().height - 32) < 1", timeout=10_000)
    check_window(window_facts(page), n, "initial")
    rnd = random.Random(n)
    height = page.evaluate("() => document.getElementById('tableWrap').scrollHeight")
    targets = sorted({0, 1, height // 3, height // 2, height - 1, *(rnd.randrange(0, max(1, height)) for _ in range(4))})
    for target in targets:
        page.evaluate("(t) => { document.getElementById('tableWrap').scrollTop = t; }", target)
        page.wait_for_function("() => new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(() => r(true))))")
        facts = window_facts(page)
        check_window(facts, n, f"scrollTop={target}")
    assert page.js_errors == []


@pytest.mark.parametrize("n", [3, 30, 400])
def test_keyboard_movement_through_a_windowed_table(page, wenjie_path, n):
    rows = [[f"r{i}", i] for i in range(n)]
    open_synthetic(page, wenjie_path, ["name", "n"], rows)
    page.focus('#tableWrap tbody tr[tabindex="0"]')
    at = lambda: int(page.evaluate("() => document.activeElement.dataset.pos"))  # noqa: E731
    assert at() == 0
    page.keyboard.press("ArrowUp")
    assert at() == 0                                   # does not run off the top
    page.keyboard.press("End")
    assert at() == n - 1
    page.keyboard.press("ArrowDown")
    assert at() == n - 1                               # nor off the bottom
    page.keyboard.press("PageUp")
    page_size = (n - 1) - at()
    assert page_size >= 1 or n == 1
    if n > 30:
        assert page_size > 5                           # a page is a screenful, not one row
        page.keyboard.press("PageDown")
        assert at() == n - 1
    page.keyboard.press("Home")
    assert at() == 0
    for expected in range(1, min(n, 6)):
        page.keyboard.press("ArrowDown")
        assert at() == expected
    check_window(window_facts(page), n, "after keyboard")
    assert page.js_errors == []


def test_an_empty_table_has_no_window_and_a_friendly_message(page, wenjie_path):
    _load(page, wenjie_path)
    page.evaluate(_FEED_ROWS, {"columns": ["name", "n"], "data": []})
    page.click('.nav-item[data-table="fields"]')
    page.wait_for_selector("#tableWrap .empty-state", timeout=10_000)
    assert page.text_content("#meta") == "0 row(s)"
    assert page.locator("#tableWrap tbody tr[data-pos]").count() == 0


def test_a_single_column_table_works(page, wenjie_path):
    open_synthetic(page, wenjie_path, ["name"], [[f"r{i}"] for i in range(40)])
    check_window(window_facts(page), 40, "one column")
    _open_column_menu(page, "name")
    assert page.locator("#menu button", has_text="Hide column").get_attribute("aria-disabled") == "true"


def test_density_change_in_the_middle_keeps_the_window_correct(page, wenjie_path):
    n = 500
    open_synthetic(page, wenjie_path, ["name", "n"], [[f"r{i}", i] for i in range(n)])
    page.evaluate("() => { document.getElementById('tableWrap').scrollTop = 8000; }")
    page.wait_for_function("() => Number(document.querySelector('#tableWrap tbody tr[data-pos]').dataset.pos) > 100", timeout=10_000)
    page.click("#densityBtn")
    page.wait_for_function("() => Math.abs(document.querySelector('#tableWrap tbody tr[data-pos]').getBoundingClientRect().height - 32) < 1", timeout=10_000)
    check_window(window_facts(page), n, "after density change")
    page.click("#densityBtn")
    page.wait_for_function("() => Math.abs(document.querySelector('#tableWrap tbody tr[data-pos]').getBoundingClientRect().height - 40) < 1", timeout=10_000)
    check_window(window_facts(page), n, "back to comfortable")


# ====================================================================================== 4. random walk

# The default walk is short enough for every run. For a deeper hunt:
#   PYTBPARSE_WALK_SEEDS=40 PYTBPARSE_WALK_STEPS=40 pytest tests/test_gui_table.py -k random_walk
STEPS = int(os.environ.get("PYTBPARSE_WALK_STEPS", "22"))
SEEDS = list(range(1, int(os.environ["PYTBPARSE_WALK_SEEDS"]) + 1)) if os.environ.get("PYTBPARSE_WALK_SEEDS") else [11, 23, 37, 41]


def fetch_fields(url):
    with urllib.request.urlopen(url + "/table?name=fields") as r:
        payload = json.loads(r.read().decode())
    return payload["columns"], payload["data"]


class Model:
    """What the table should show, computed in Python from the data, independently of the page."""

    def __init__(self, columns, data):
        self.columns, self.data = columns, data
        self.search, self.chips, self.hidden = "", [], set()
        self.pinned, self.sort, self.density, self.drawer = None, None, "comfortable", False

    def visible(self):
        cols = [c for c in self.columns if c not in self.hidden]
        if self.pinned in cols:
            cols = [self.pinned] + [c for c in cols if c != self.pinned]
        return cols

    def text(self, col, row):
        value = row[self.columns.index(col)]
        raw = js_str(value)
        return shown_datasource(raw) + " " + raw if col == "datasource" and value is not None else raw

    def rows(self):
        out = []
        search_cols = [c for c in self.columns if c not in self.hidden]
        for r in self.data:
            if self.search:
                hay = "\x01".join(self.text(c, r) for c in search_cols).lower()
                if self.search.lower() not in hay:
                    continue
            if any(t.lower() not in self.text(c, r).lower() for c, t in self.chips):
                continue
            out.append(r)
        return out

    def names(self):
        rows = self.rows()
        if self.sort:
            col, direction = self.sort
            ci = self.columns.index(col)
            present = [r for r in rows if r[ci] is not None]
            missing = [r for r in rows if r[ci] is None]
            present.sort(key=lambda r: js_str(r[ci]).lower(), reverse=direction < 0)
            rows = present + missing
        return [js_str(r[self.columns.index("name")]) for r in rows]


FACTS = """() => {
  const q = (s) => [...document.querySelectorAll(s)];
  const wrap = document.getElementById('tableWrap');
  const table = wrap.querySelector('table');
  const rows = q('#tableWrap tbody tr[data-pos]');
  const heads = q('#tableWrap th');
  return {
    meta: document.getElementById('meta').textContent,
    hasTable: !!table,
    rowcount: table ? Number(table.getAttribute('aria-rowcount')) : null,
    colcount: table ? Number(table.getAttribute('aria-colcount')) : null,
    labels: heads.map((h) => h.querySelector('.th-label').textContent),
    pinned: heads.map((h) => h.classList.contains('pin')),
    sorted: heads.map((h) => h.getAttribute('aria-sort')),
    headStops: heads.filter((h) => h.tabIndex === 0).length,
    positions: rows.map((r) => Number(r.dataset.pos)),
    rowindex: rows.map((r) => Number(r.getAttribute('aria-rowindex'))),
    rowStops: rows.filter((r) => r.tabIndex === 0).length,
    current: q('#tableWrap tr[aria-current="true"]').length,
    chips: q('#chips .chip').map((c) => c.getAttribute('aria-label')),
    chipsHidden: document.getElementById('chips').hidden,
    colsBtn: document.getElementById('colsBtn').textContent,
    drawerOpen: document.getElementById('drawer').classList.contains('show'),
    density: document.documentElement.dataset.density,
    pressed: document.getElementById('densityBtn').getAttribute('aria-pressed'),
    widths: heads.map((h) => h.getBoundingClientRect().width),
    empty: !!wrap.querySelector('.empty-state'),
  };
}"""


def check_invariants(page, model, trace):
    f = page.evaluate(FACTS)
    where = "\n  ".join(trace[-8:])
    shown = len(model.rows())
    assert page.js_errors == [], f"JS errors {page.js_errors}\n  {where}"
    assert f["hasTable"], f"no table\n  {where}"
    assert f["rowcount"] == shown + 1, f"aria-rowcount {f['rowcount']} != {shown + 1}\n  {where}"
    filtered = bool(model.search) or bool(model.chips)
    expect_meta = f"{shown} of {len(model.data)} row(s)" if filtered else f"{len(model.data)} row(s)"
    assert f["meta"] == expect_meta, f"meta {f['meta']!r} != {expect_meta!r}\n  {where}"
    cols = model.visible()
    assert f["labels"] == cols, f"columns {f['labels']} != {cols}\n  {where}"
    assert f["colcount"] == len(cols), where
    assert f["pinned"] == [bool(model.pinned) and c == model.pinned for c in cols], f"pin state\n  {where}"
    sorted_cols = [c for c, s in zip(f["labels"], f["sorted"]) if s != "none"]
    assert sorted_cols == ([model.sort[0]] if model.sort else []), f"sort state {f['sorted']}\n  {where}"
    if model.sort:
        want = "ascending" if model.sort[1] == 1 else "descending"
        assert want in f["sorted"], where
    assert f["headStops"] == 1, f"{f['headStops']} header tab stops\n  {where}"
    if shown:
        pos = f["positions"]
        assert pos and pos == list(range(pos[0], pos[0] + len(pos))) and pos[-1] < shown, f"rows {pos[:3]}..\n  {where}"
        assert f["rowindex"] == [p + 2 for p in pos], where
        assert len(pos) <= 100 and f["rowStops"] == 1, f"rows/stops {len(pos)}/{f['rowStops']}\n  {where}"
    else:
        assert f["positions"] == [] and f["empty"], f"expected the empty state\n  {where}"
    assert len(f["chips"]) == len(model.chips) and f["chipsHidden"] == (not model.chips), f"chips {f['chips']}\n  {where}"
    hidden = len(model.hidden)
    assert f["colsBtn"] == (f"Columns ({hidden} hidden)" if hidden else "Columns"), f["colsBtn"]
    assert f["drawerOpen"] == model.drawer, f"drawer {f['drawerOpen']} != {model.drawer}\n  {where}"
    assert f["current"] <= (1 if model.drawer else 0), f"{f['current']} current rows\n  {where}"
    assert f["density"] == model.density and f["pressed"] == ("true" if model.density == "compact" else "false"), where
    assert all(80 - 1 <= w <= 900 + 1 for w in f["widths"]), f"column widths {f['widths']}\n  {where}"
    return f


def check_contents(page, model, trace):
    if "name" in model.visible():
        got = _copy_column(page, "name")
        want = model.names()
        where = "\n  ".join(trace[-8:])
        assert sorted(got) == sorted(want), f"rows differ ({len(got)} vs {len(want)})\n  {where}"
        if not model.sort or model.sort[0] != "name":
            if not model.sort:
                assert got == want, f"order differs\n  {where}"
        else:
            ok = page.evaluate(
                """([vals, dir]) => { const c = new Intl.Collator(undefined, {numeric: true, sensitivity: 'base'});
                   for (let i = 1; i < vals.length; i++) if (dir * c.compare(vals[i - 1], vals[i]) > 0) return false;
                   return true; }""",
                [got, model.sort[1]],
            )
            assert ok, f"sorted by name but out of order: {got[:6]}\n  {where}"


def walk(page, gui_server, seed):
    rnd = random.Random(seed)
    columns, data = fetch_fields(gui_server)
    model = Model(columns, data)
    trace = [f"seed={seed}"]

    def visible():
        return model.visible()

    def after_render(action, *args):
        stamp = render_stamp(page)
        action(*args)
        wait_render(page, stamp)

    # Headers and toolbar buttons are driven from the keyboard: the details drawer overlays the right
    # side of the screen, so a mouse click there would be blocked by the drawer, not by a bug.
    def activate(selector):
        page.focus(selector)
        page.keyboard.press("Enter")

    def press_on_header(col, key="Space"):
        _header(page, col).focus()
        page.keyboard.press(key)

    def do_sort_click():
        col = rnd.choice(visible())
        trace.append(f"click header {col}")
        after_render(lambda: press_on_header(col))
        if not model.sort or model.sort[0] != col:
            model.sort = (col, 1)
        elif model.sort[1] == 1:
            model.sort = (col, -1)
        else:
            model.sort = None

    def do_sort_menu():
        col, direction = rnd.choice(visible()), rnd.choice([1, -1])
        trace.append(f"menu sort {col} {direction}")

        def go():
            _open_column_menu(page, col)
            page.click("#menu >> text=" + ("Sort ascending" if direction == 1 else "Sort descending"))
        after_render(go)
        model.sort = (col, direction)

    def do_search():
        text = rnd.choice(["", "a", "count", "mun", "string", "dimension", "zzzz", "sheet1", "ce", "county"])
        if text == model.search:
            return
        trace.append(f"search {text!r}")
        after_render(lambda: page.fill("#filter", text))
        model.search = text

    def do_chip():
        col = rnd.choice(visible())
        text = rnd.choice(["a", "e", "string", "mun", "true", "false", "county", "zzz"])
        trace.append(f"chip {col} contains {text!r}")

        def go():
            _open_column_menu(page, col)
            page.click("#menu >> text=Filter this column")
            page.fill("#menu input", text)
            page.keyboard.press("Enter")
        after_render(go)
        model.chips = [c for c in model.chips if c[0] != col] + [(col, text)]

    def do_chip_remove():
        if not model.chips:
            return
        trace.append("remove first chip")
        after_render(lambda: activate("#chips .chip >> nth=0"))
        model.chips.pop(0)

    def do_clear_filters():
        if not model.chips:
            return
        trace.append("clear filters")
        after_render(lambda: activate("#chips .chip-clear"))
        model.chips, model.search = [], ""

    def do_hide():
        if len(visible()) <= 1:
            return
        col = rnd.choice(visible())
        trace.append(f"hide {col}")

        def go():
            _open_column_menu(page, col)
            page.click("#menu >> text=Hide column")
        after_render(go)
        model.hidden.add(col)
        if model.pinned == col:
            model.pinned = None
        if model.sort and model.sort[0] == col:
            model.sort = None

    def do_show():
        if not model.hidden:
            return
        col = rnd.choice(sorted(model.hidden))
        trace.append(f"show {col} via the Columns menu")

        def go():
            activate("#colsBtn")
            page.locator("#menu button[role=menuitemcheckbox]", has_text=re.compile(rf"^[✓\s]*{col}$")).click()
        after_render(go)
        page.keyboard.press("Escape")
        model.hidden.discard(col)

    def do_show_all():
        if not model.hidden:
            return
        trace.append("show all columns")

        def go():
            activate("#colsBtn")
            page.click("#menu >> text=Show all columns")
        after_render(go)
        page.keyboard.press("Escape")
        model.hidden.clear()

    def do_pin():
        col = rnd.choice(visible())
        trace.append(f"toggle pin {col}")

        def go():
            _open_column_menu(page, col)
            page.click("#menu >> text=" + ("Unpin column" if model.pinned == col else "Pin to the left"))
        after_render(go)
        model.pinned = None if model.pinned == col else col

    def do_resize():
        col = rnd.choice(visible())
        which = rnd.choice(["Wider", "Narrower", "Reset width"])
        trace.append(f"{which} {col}")

        def go():
            _open_column_menu(page, col)
            page.click("#menu >> text=" + which)
        after_render(go)

    def do_density():
        trace.append("toggle density")
        after_render(lambda: activate("#densityBtn"))
        model.density = "compact" if model.density == "comfortable" else "comfortable"

    def do_open_drawer():
        if not model.rows():
            return
        trace.append("open drawer")
        page.evaluate("() => { document.getElementById('tableWrap').scrollTop = 0; }")
        page.wait_for_selector("#tableWrap tbody tr[data-pos]")
        page.locator("#tableWrap tbody tr[data-pos]").first.click(position={"x": 24, "y": 8})
        page.wait_for_selector("#drawer.show", timeout=10_000)
        model.drawer = True

    def do_close_drawer():
        if not model.drawer:
            return
        trace.append("close drawer (Escape)")
        page.focus("#drawerTitle")  # Escape in the search box clears the search instead
        page.keyboard.press("Escape")
        page.wait_for_selector("#drawer", state="hidden", timeout=10_000)
        model.drawer = False

    def do_scroll():
        trace.append("scroll")
        page.evaluate("(t) => { document.getElementById('tableWrap').scrollTop = t; }", rnd.randrange(0, 4000))
        page.wait_for_function("() => new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(() => r(true))))")

    def do_roundtrip():
        trace.append("leave to Relations and come back")
        _open(page, "relations")
        _wait_meta(page, "6 row(s)")
        stamp = render_stamp(page)
        _open(page, "fields")
        wait_render(page, stamp)
        model.search, model.sort, model.drawer = "", None, False

    actions = [
        (do_sort_click, 4), (do_sort_menu, 2), (do_search, 4), (do_chip, 3), (do_chip_remove, 1), (do_clear_filters, 1),
        (do_hide, 2), (do_show, 2), (do_show_all, 1), (do_pin, 2), (do_resize, 2), (do_density, 1),
        (do_open_drawer, 2), (do_close_drawer, 2), (do_scroll, 2), (do_roundtrip, 1),
    ]
    population = [a for a, weight in actions for _ in range(weight)]
    try:
        check_invariants(page, model, trace)
        for step in range(STEPS):
            rnd.choice(population)()
            check_invariants(page, model, trace)
            if step % 3 == 2:
                check_contents(page, model, trace)
        check_contents(page, model, trace)
    except AssertionError:
        raise
    except Exception as e:  # a timeout or a Playwright error: say where in the walk it happened
        raise AssertionError(f"{type(e).__name__}: {str(e).splitlines()[0][:200]}\n  steps so far:\n    " + "\n    ".join(trace)) from e


@pytest.mark.parametrize("seed", SEEDS)
def test_random_walk_keeps_the_screen_consistent_with_the_model(page, gui_server, wenjie_path, seed):
    _load(page, wenjie_path)
    _open(page, "fields")
    _wait_meta(page, "55 row(s)")
    walk(page, gui_server, seed)
