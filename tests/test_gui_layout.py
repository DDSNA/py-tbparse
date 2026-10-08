"""Layout of the GUI, checked in a real browser at the sizes people really use.

- no sideways scrolling of the page, at seven viewport sizes (these include what 200% and 400% browser zoom
  produce on a laptop and a phone) in every kind of view
- the controls you need are on screen at every size
- popups (column menu, details drawer, toast) never run off the screen
- column widths never jump when different rows are shown, and sorting, filtering and scrolling do not move the
  furniture around the table
- the sticky header and the pinned column stay where they should
- WCAG text spacing: stretching letter, word and line spacing does not clip a single label
"""

from __future__ import annotations

import pytest

from test_gui_browser import (  # noqa: F401  (fixtures and helpers shared with the other GUI tests)
    _header,
    _load,
    _open,
    _open_column_menu,
    _wait_meta,
    new_page,
    wait_settled,
)
from test_gui_table import open_synthetic, render_stamp, wait_render

# (width, height). 640x400 is a 1280x800 laptop at 200% zoom; 320x640 is a 1280x800 laptop at 400% zoom.
VIEWPORTS = [(320, 640), (390, 800), (640, 400), (768, 1024), (1024, 768), (1366, 768), (1920, 1080)]
VIEWS = ["overview", "fields", "field-renames", "relations", "graph"]

CONTENT = "#tableWrap table, #tableWrap .empty-state, #tableWrap .cards, #tableWrap .graph-view"


def go(page, view):
    """Switch view the way a person at this width does: the sidebar when it is there, the dropdown when not."""
    if page.is_visible("nav#nav"):
        _open(page, view)
    else:
        page.select_option("#tableSel", view)
    page.wait_for_function(
        "(v) => document.querySelector('.nav-item[aria-current=page]') ? document.querySelector('.nav-item[aria-current=page]').dataset.table === v : document.getElementById('tableSel').value === v",
        arg=view,
        timeout=10_000,
    )
    page.wait_for_selector(CONTENT, timeout=10_000)
    wait_settled(page)  # fades and rises finish


OVERFLOW = """() => {
  const vw = window.innerWidth;
  const offenders = [];
  for (const el of document.body.querySelectorAll('*')) {
    if (el.closest('#tableWrap, #menu, #drawer, .toast, [hidden], .sr-only, .skip')) continue;
    const cs = getComputedStyle(el);
    if (cs.display === 'none' || cs.visibility === 'hidden') continue;
    const r = el.getBoundingClientRect();
    if (!r.width || !r.height) continue;
    if (r.right > vw + 1 || r.left < -1) {
      offenders.push(el.tagName.toLowerCase() + (el.id ? '#' + el.id : '') + '.' + String(el.className).split(' ')[0] +
                     ' ' + Math.round(r.left) + '..' + Math.round(r.right) + ' of ' + vw);
    }
  }
  return {offenders, scrollWidth: document.documentElement.scrollWidth, bodyWidth: document.body.scrollWidth, vw};
}"""


@pytest.mark.parametrize("size", VIEWPORTS, ids=lambda s: f"{s[0]}x{s[1]}")
def test_nothing_overflows_the_page_sideways(browser, gui_server, wenjie_path, size):
    pg = new_page(browser, gui_server, viewport={"width": size[0], "height": size[1]})
    problems = []
    try:
        wait_settled(pg)
        start = pg.evaluate(OVERFLOW)
        assert not start["offenders"] and start["scrollWidth"] <= start["vw"] + 1, f"start screen: {start}"
        _load(pg, wenjie_path)
        pg.wait_for_selector(CONTENT, timeout=10_000)
        for view in VIEWS:
            go(pg, view)
            r = pg.evaluate(OVERFLOW)
            if r["offenders"] or r["scrollWidth"] > r["vw"] + 1 or r["bodyWidth"] > r["vw"] + 1:
                problems.append(f"{view}: page scrollWidth {r['scrollWidth']} / body {r['bodyWidth']} in {r['vw']}px; {r['offenders'][:5]}")
        assert [e for e in pg.js_errors if "400" not in e and "Bad Request" not in e] == []
    finally:
        pg.ctx.close()
    assert not problems, f"at {size[0]}x{size[1]}:\n  " + "\n  ".join(problems)


@pytest.mark.parametrize("size", VIEWPORTS, ids=lambda s: f"{s[0]}x{s[1]}")
def test_the_controls_you_need_are_on_screen_at_every_size(browser, gui_server, wenjie_path, size):
    pg = new_page(browser, gui_server, viewport={"width": size[0], "height": size[1]})
    try:
        def on_screen(selector):
            box = pg.locator(selector).first.bounding_box()
            vw = pg.evaluate("() => window.innerWidth")
            return bool(box) and box["x"] >= -1 and box["x"] + box["width"] <= vw + 1 and box["width"] > 0

        assert on_screen("#path") and on_screen("#loadBtn")
        _load(pg, wenjie_path)
        pg.wait_for_selector(CONTENT, timeout=10_000)
        narrow = not pg.is_visible("nav#nav")
        assert (size[0] <= 760) == narrow, "the sidebar should give way to the dropdown on narrow screens only"
        for view in ("fields", "field-renames"):
            go(pg, view)
            assert on_screen("#filter") and on_screen("#exportLink") and on_screen("#colsBtn") and on_screen("#densityBtn"), view
            if narrow:
                assert on_screen("#tableSel")
        go(pg, "field-renames")
        assert on_screen("#createBtn") and on_screen("#downloadBtn") and on_screen("#renameStyle")
    finally:
        pg.ctx.close()


# ====================================================================================== popups stay on screen


def inside_viewport(pg, selector):
    return pg.evaluate(
        """(sel) => { const r = document.querySelector(sel).getBoundingClientRect();
          return {left: r.left, right: r.right, top: r.top, bottom: r.bottom, vw: window.innerWidth, vh: window.innerHeight}; }""",
        selector,
    )


@pytest.mark.parametrize("size", [(390, 800), (640, 400), (1366, 768)], ids=lambda s: f"{s[0]}x{s[1]}")
def test_menu_drawer_and_toast_stay_inside_the_screen(browser, gui_server, wenjie_path, size):
    pg = new_page(browser, gui_server, viewport={"width": size[0], "height": size[1]})
    try:
        _load(pg, wenjie_path)
        go(pg, "fields")
        _wait_meta(pg, "55 row(s)")
        last = pg.eval_on_selector_all("#tableWrap th .th-label", "els => els[els.length - 1].textContent")
        for column in (last, "name"):                           # the column furthest right, and one at the left
            _open_column_menu(pg, column)
            wait_settled(pg)
            r = inside_viewport(pg, "#menu")
            assert r["left"] >= -1 and r["right"] <= r["vw"] + 1 and r["top"] >= -1 and r["bottom"] <= r["vh"] + 1, (column, r)
            pg.keyboard.press("Escape")
        pg.locator("#tableWrap tbody tr[data-pos]").first.click(position={"x": 12, "y": 6})
        pg.wait_for_selector("#drawer.show", timeout=10_000)
        wait_settled(pg)
        for sel in ("#drawer", "#drawerClose", "#drawerCopy"):
            r = inside_viewport(pg, sel)
            assert r["left"] >= -1 and r["right"] <= r["vw"] + 1 and r["top"] >= -1 and r["bottom"] <= r["vh"] + 1, (sel, r)
        pg.keyboard.press("Escape")
        pg.wait_for_selector("#drawer", state="hidden", timeout=10_000)
        pg.fill("#path", "/no/such/place/" + "a-very-long-folder-name/" * 6 + "workbook.twb")
        pg.click("#loadBtn")
        pg.wait_for_function("() => document.getElementById('status').classList.contains('err')", timeout=10_000)
        wait_settled(pg)
        r = inside_viewport(pg, "#status")
        assert r["left"] >= -1 and r["right"] <= r["vw"] + 1 and r["bottom"] <= r["vh"] + 1, r
        assert [e for e in pg.js_errors if "400" not in e and "Bad Request" not in e] == []
    finally:
        pg.ctx.close()


@pytest.mark.parametrize("size", [(390, 800), (1360, 900), (1366, 768)], ids=lambda s: f"{s[0]}x{s[1]}")
def test_the_toast_does_not_cover_the_end_of_the_view(browser, gui_server, wenjie_path, size):
    # the view ends in a strip as tall as a two-line toast, so with the view scrolled to its end the toast
    # sits below the last row or hint, never on it (#143). The toast is a live region, not a tab stop.
    pg = new_page(browser, gui_server, viewport={"width": size[0], "height": size[1]})
    try:
        _load(pg, wenjie_path)
        for view in ("fields", "libraries", "copy"):
            go(pg, view)
            pg.wait_for_function("v => location.hash === '#' + v", arg=view, timeout=10_000)
            pg.fill("#path", "/no/such/workbook.twb")       # an error toast stays until it is dismissed
            pg.click("#loadBtn")
            pg.wait_for_function("() => document.getElementById('status').classList.contains('err')", timeout=10_000)
            pg.evaluate("() => { const w = document.getElementById('tableWrap'); w.scrollTop = w.scrollHeight; "
                        "window.scrollTo(0, document.documentElement.scrollHeight); }")
            wait_settled(pg)
            r = pg.evaluate("""() => ({wrap: document.getElementById('tableWrap').getBoundingClientRect().bottom,
                                       toast: document.getElementById('status').getBoundingClientRect().top,
                                       tab: document.getElementById('status').tabIndex})""")
            assert r["toast"] >= r["wrap"], (view, r)
            assert r["tab"] < 0
        assert [e for e in pg.js_errors if "400" not in e and "Bad Request" not in e] == []
    finally:
        pg.ctx.close()


# ====================================================================================== stability

SHORT = "short"
LONG = "x" * 400


def boxes(page, selector):
    return page.eval_on_selector_all(
        selector, "els => els.map(e => { const r = e.getBoundingClientRect(); return [r.x, r.y, r.width, r.height].map(v => Math.round(v * 2) / 2); })"
    )


def test_column_widths_never_change_with_the_rows_on_show(page, wenjie_path):
    """The table lays out with fixed column widths, so a long value that scrolls into view, or a filter that
    hides it, cannot make the columns jump."""
    rows = [[f"{SHORT}{i}", LONG if i % 7 == 0 else SHORT] for i in range(300)]
    open_synthetic(page, wenjie_path, ["name", "text"], rows)
    wait_settled(page)                         # the view's entrance rise (--dur-slow) has finished
    before = boxes(page, "#tableWrap th")
    width = page.evaluate("() => document.querySelector('#tableWrap table').getBoundingClientRect().width")
    for target in (0, 2000, 5000, 11000):
        page.evaluate("(t) => { document.getElementById('tableWrap').scrollTop = t; }", target)
        page.wait_for_function("() => new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(() => r(true))))")
        assert boxes(page, "#tableWrap th") == before, f"columns moved at scrollTop {target}"
    stamp = render_stamp(page)
    page.fill("#filter", SHORT + "1")          # hides every long value
    wait_render(page, stamp)
    assert boxes(page, "#tableWrap th") == before, "columns moved when the long values were filtered out"
    stamp = render_stamp(page)
    page.fill("#filter", "")
    wait_render(page, stamp)
    stamp = render_stamp(page)
    _header(page, "text").click()
    wait_render(page, stamp)
    assert boxes(page, "#tableWrap th") == before, "columns moved when the table was sorted"
    assert abs(page.evaluate("() => document.querySelector('#tableWrap table').getBoundingClientRect().width") - width) < 1
    cell = page.locator("#tableWrap tbody tr[data-pos] td").nth(1).bounding_box()
    assert cell["height"] < 60, "a long value must be cut with an ellipsis, not wrapped into a tall row"


FURNITURE = ".view-head, .subbar, #tableWrap, #tableWrap thead"


def test_sorting_filtering_and_density_do_not_move_the_furniture(page, wenjie_path):
    from playwright.sync_api import expect

    _load(page, wenjie_path)
    go(page, "fields")
    _wait_meta(page, "55 row(s)")
    before = boxes(page, FURNITURE)
    stamp = render_stamp(page)
    _header(page, "caption").click()
    wait_render(page, stamp)
    assert boxes(page, FURNITURE) == before, "sorting moved the page furniture"
    stamp = render_stamp(page)
    page.fill("#filter", "a")
    wait_render(page, stamp)
    assert boxes(page, FURNITURE) == before, "filtering moved the page furniture"
    expect(page.locator("#chips")).to_be_hidden()


def test_no_layout_shift_while_sorting_filtering_and_scrolling(page, wenjie_path):
    if not page.evaluate("() => PerformanceObserver.supportedEntryTypes.includes('layout-shift')"):
        pytest.skip("this browser does not report layout shifts")
    rows = [[f"r{i}", i] for i in range(2000)]
    open_synthetic(page, wenjie_path, ["name", "n"], rows)
    wait_settled(page)
    page.evaluate(
        "() => { window.__cls = 0; new PerformanceObserver((list) => { for (const e of list.getEntries()) if (!e.hadRecentInput) window.__cls += e.value; })"
        ".observe({type: 'layout-shift', buffered: false}); }"
    )
    for action in ("sort", "scroll", "filter", "unfilter", "sort-again"):
        stamp = render_stamp(page)
        if action in ("sort", "sort-again"):
            _header(page, "n").focus()
            page.keyboard.press("Space")
            wait_render(page, stamp)
        elif action == "scroll":
            page.evaluate("() => { const w = document.getElementById('tableWrap'); for (let t = 0; t < 30000; t += 3000) w.scrollTop = t; }")
        elif action == "filter":
            page.fill("#filter", "r19")
            wait_render(page, stamp)
        else:
            page.fill("#filter", "")
            wait_render(page, stamp)
        wait_settled(page)
    assert page.evaluate("() => window.__cls") < 0.02, "the page layout shifted while the table changed"


def test_sticky_header_and_pinned_column_stay_where_they_belong(page, wenjie_path):
    rows = [[f"r{i}"] + [f"cell {i}-{c}" for c in range(11)] for i in range(300)]
    open_synthetic(page, wenjie_path, ["name"] + [f"c{c}" for c in range(11)], rows)
    _open_column_menu(page, "c2")
    page.click("#menu >> text=Pin to the left")
    page.wait_for_function("() => document.querySelector('#tableWrap th .th-label').textContent === 'c2'", timeout=10_000)
    # The view fades and rises in (translateY 8px) when a table opens, and a bounding box includes that
    # transform; measured mid-animation, wrap_box looked like the pinned corner moving (#70). Settle first.
    wait_settled(page)
    wrap_box = page.locator("#tableWrap").bounding_box()
    page.evaluate("() => { const w = document.getElementById('tableWrap'); w.scrollTop = 3000; w.scrollLeft = 400; }")
    page.wait_for_function("() => new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(() => r(true))))")
    head = page.locator("#tableWrap th").first.bounding_box()
    assert abs(head["y"] - wrap_box["y"]) < 2 and abs(head["x"] - wrap_box["x"]) < 2, "the pinned header corner moved"
    other = page.locator("#tableWrap th").nth(3).bounding_box()
    assert abs(other["y"] - wrap_box["y"]) < 2, "an ordinary header did not stay at the top"
    # what is on top at the corner is the pinned header, and beside it body cells scroll underneath
    top_at_corner = page.evaluate(
        "([x, y]) => { const e = document.elementFromPoint(x, y); return e.closest('th') ? e.closest('th').className : e.tagName; }",
        [wrap_box["x"] + 20, wrap_box["y"] + 15],
    )
    assert "pin" in top_at_corner
    pinned_cell = page.evaluate(
        "([x, y]) => { const e = document.elementFromPoint(x, y); return e.closest('td') ? e.closest('td').className : e.tagName; }",
        [wrap_box["x"] + 20, wrap_box["y"] + 80],
    )
    assert "pin" in pinned_cell, "ordinary cells scrolled over the pinned column"


# ====================================================================================== text spacing (WCAG 1.4.12)

SPACING = """* { line-height: 1.5 !important; letter-spacing: 0.12em !important; word-spacing: 0.16em !important; }
p, .desc, dd { margin-bottom: 2em !important; }"""

CLIPPED = """() => [...document.querySelectorAll('.btn, .nav-item, .chip, .menu-item, .stat, .label, h1, .brand, .check')]
  .filter((e) => e.getClientRects().length && !e.closest('[hidden]'))
  .filter((e) => e.scrollWidth > e.clientWidth + 1 || e.scrollHeight > e.clientHeight + 1)
  .map((e) => e.tagName.toLowerCase() + (e.id ? '#' + e.id : '') + '.' + String(e.className).split(' ')[0] + ' "' + (e.textContent || '').trim().slice(0, 24) + '" '
              + e.scrollWidth + 'x' + e.scrollHeight + ' in ' + e.clientWidth + 'x' + e.clientHeight)"""


@pytest.mark.parametrize("size", [(1366, 768), (390, 800)], ids=lambda s: f"{s[0]}x{s[1]}")
def test_stretched_text_spacing_clips_no_label(browser, gui_server, wenjie_path, size):
    pg = new_page(browser, gui_server, viewport={"width": size[0], "height": size[1]})
    try:
        _load(pg, wenjie_path)
        go(pg, "fields")
        _wait_meta(pg, "55 row(s)")
        pg.add_style_tag(content=SPACING)
        wait_settled(pg)
        clipped = pg.evaluate(CLIPPED)
        assert clipped == [], f"labels clipped under WCAG text spacing: {clipped}"
        pg.click("#colsBtn") if pg.is_visible("#colsBtn") else None
        wait_settled(pg)
        clipped = pg.evaluate(CLIPPED)
        assert clipped == [], f"labels clipped in the menu: {clipped}"
        go(pg, "field-renames")
        assert pg.evaluate(CLIPPED) == []
    finally:
        pg.ctx.close()
