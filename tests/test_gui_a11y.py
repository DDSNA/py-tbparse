"""Accessibility of the GUI, checked in a real browser.

These go beyond the token test (which checks the palette): they check the page that is actually drawn.

- the keyboard: a sensible tab order, no traps, every shortcut the hint promises, one tab stop per table
- focus: a visible focus indicator on every stop
- names and structure: every control has an accessible name, ids are unique, landmarks and headings are right,
  the windowed table's ARIA (row and column counts and indexes) stays consistent while scrolling
- contrast: every piece of rendered text, in light and dark, in a dozen states (hovered, focused, menu open,
  drawer open, toast showing, error showing, compact...), measured from computed colours with alpha blending
- motion: with reduced motion requested, nothing animates and no view transition is started
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
)
from test_gui_table import _FEED_ROWS, open_synthetic, render_stamp, wait_render
from test_audit import workbook


# ====================================================================================== keyboard and focus

DESCRIBE = """() => {
  const e = document.activeElement;
  const cs = getComputedStyle(e);
  return {tag: e.tagName, id: e.id, cls: e.className || '', text: (e.textContent || '').trim().slice(0, 30),
          pos: e.dataset ? (e.dataset.pos || e.dataset.table || '') : '',
          outlineStyle: cs.outlineStyle, outlineWidth: parseFloat(cs.outlineWidth), boxShadow: cs.boxShadow,
          visible: e.getClientRects().length > 0};
}"""


def tab_stops(page, key="Tab", limit=140):
    """Record every tab stop, starting at the first one (the skip link) until focus leaves the page or cycles.
    (The browser continues from the last element clicked, so the walk starts from the skip link explicitly.)"""
    page.evaluate("() => window.scrollTo(0, 0)")
    page.focus("#path")
    page.keyboard.press("Shift+Tab")  # reach the skip link the way a keyboard user does (a script focus shows no ring)
    stops = [page.evaluate(DESCRIBE)] if key == "Tab" else []
    for _ in range(limit):
        page.keyboard.press(key)
        info = page.evaluate(DESCRIBE)
        if info["tag"] == "BODY":
            break
        stops.append(info)
        if len(stops) > 1 and (info["id"], info["cls"], info["text"], info["pos"]) == (
            stops[0]["id"], stops[0]["cls"], stops[0]["text"], stops[0]["pos"]
        ):
            stops.pop()
            break
    return stops


def label(stop):
    return f"{stop['tag'].lower()}#{stop['id']}.{str(stop['cls']).split(' ')[0]}:{stop['text'][:14]}"


@pytest.fixture
def fields_page(page, wenjie_path):
    _load(page, wenjie_path)
    _open(page, "fields")
    _wait_meta(page, "55 row(s)")
    return page


def test_tab_order_follows_the_page_and_never_traps(fields_page):
    page = fields_page
    stops = tab_stops(page)
    names = [label(s) for s in stops]
    assert 15 < len(stops) < 100, f"{len(stops)} tab stops: {names}"          # no trap, nothing missing
    order = [
        lambda s: s["cls"] == "skip",
        lambda s: s["id"] == "path",
        lambda s: s["id"] == "loadBtn",
        lambda s: "nav-item" in str(s["cls"]),
        lambda s: s["id"] == "filter",
        lambda s: s["id"] == "colsBtn",
        lambda s: s["id"] == "densityBtn",
        lambda s: s["id"] == "exportLink",
        lambda s: s["tag"] == "TH",
        lambda s: s["tag"] == "TR",
    ]
    at = 0
    for want in order:
        while at < len(stops) and not want(stops[at]):
            at += 1
        assert at < len(stops), f"tab order is not skip, path, load, nav, filter, columns, density, export, header, row: {names}"
        at += 1
    assert sum(1 for s in stops if s["tag"] == "TH") == 1 and sum(1 for s in stops if s["tag"] == "TR") == 1
    nav_buttons = page.locator("nav#nav button.nav-item").count()
    assert sum(1 for s in stops if "nav-item" in str(s["cls"])) == nav_buttons
    assert all(s["visible"] for s in stops), "a hidden element is in the tab order"
    assert not any(s["id"] in ("menu", "drawer", "tableWrap") for s in stops)


def test_shift_tab_walks_the_same_stops_backwards(fields_page):
    page = fields_page
    forward = [label(s) for s in tab_stops(page)]
    # go to the end, then back
    page.evaluate("() => document.activeElement.blur()")
    backward = []
    for _ in range(len(forward)):
        page.keyboard.press("Shift+Tab")
        info = page.evaluate(DESCRIBE)
        if info["tag"] == "BODY":
            break
        backward.append(label(info))
    assert backward == list(reversed(forward))


def test_every_tab_stop_has_a_visible_focus_indicator(fields_page):
    stops = tab_stops(fields_page)
    bad = [label(s) for s in stops if not ((s["outlineStyle"] != "none" and s["outlineWidth"] >= 2) or s["boxShadow"] != "none")]
    assert not bad, f"no visible focus indicator on: {bad}"


def test_the_promised_shortcuts_work(fields_page):
    page = fields_page
    page.locator("h1#viewTitle").click()
    page.keyboard.press("/")
    assert page.evaluate("() => document.activeElement.id") == "filter"       # "/" jumps to the search box
    page.fill("#filter", "zzz-nothing")
    page.wait_for_selector("#tableWrap .empty-state", timeout=10_000)
    page.press("#filter", "Escape")                                           # Escape clears it
    _wait_meta(page, "55 row(s)")
    for key in ("Alt+ArrowDown", "ContextMenu", "Shift+F10"):                 # three ways to open column options
        _header(page, "name").focus()
        page.keyboard.press(key)
        page.wait_for_selector("#menu:not([hidden])", timeout=5_000)
        assert page.get_attribute("#menu", "aria-label") == "Options for column name", key
        page.keyboard.press("Escape")
        page.wait_for_selector("#menu", state="hidden", timeout=5_000)
        assert page.evaluate("() => document.activeElement.tagName") == "TH", key   # focus comes back
    # Enter and Space on a row open the details; Escape closes them
    row = page.locator("#tableWrap tbody tr[data-pos]").first
    for key in ("Enter", "Space"):
        row.focus()
        page.keyboard.press(key)
        page.wait_for_selector("#drawer.show", timeout=10_000)
        page.keyboard.press("Escape")
        page.wait_for_selector("#drawer", state="hidden", timeout=10_000)
    assert page.js_errors == []


def test_menu_trigger_buttons_report_whether_their_menu_is_open(fields_page):
    page = fields_page
    assert page.get_attribute("#colsBtn", "aria-expanded") == "false"
    page.click("#colsBtn")
    assert page.get_attribute("#colsBtn", "aria-expanded") == "true"
    page.keyboard.press("Escape")
    assert page.get_attribute("#colsBtn", "aria-expanded") == "false"
    # the column options button inside a header does the same
    _open_column_menu(page, "name")
    button = _header(page, "name").locator(".col-menu-btn")
    assert button.get_attribute("aria-haspopup") == "menu"
    assert button.get_attribute("aria-expanded") == "true"
    page.keyboard.press("Escape")
    assert _header(page, "name").locator(".col-menu-btn").get_attribute("aria-expanded") == "false"


# ====================================================================================== names and structure

NAMES = """() => {
  const visible = (e) => e.getClientRects().length > 0 && getComputedStyle(e).visibility !== 'hidden';
  const text = (e) => (e.textContent || '').replace(/\\s+/g, ' ').trim();
  const nameOf = (e) => {
    if (e.getAttribute('aria-label')) return e.getAttribute('aria-label').trim();
    const by = e.getAttribute('aria-labelledby');
    if (by) return by.split(/\\s+/).map((id) => text(document.getElementById(id) || document.body.appendChild(document.createElement('i')))).join(' ').trim();
    if (e.labels && e.labels.length) return [...e.labels].map(text).join(' ').trim();
    if (e.tagName === 'INPUT' || e.tagName === 'SELECT' || e.tagName === 'TEXTAREA') return '';
    return text(e) || (e.getAttribute('title') || '').trim();
  };
  const sel = 'button, a[href], input:not([type=hidden]), select, textarea, [role=menuitem], [role=menuitemcheckbox], th[tabindex], tr[tabindex], [tabindex="0"]';
  return [...document.querySelectorAll(sel)].filter(visible).map((e) => ({
    el: e.tagName.toLowerCase() + (e.id ? '#' + e.id : '') + (e.className ? '.' + String(e.className).split(' ')[0] : ''),
    name: nameOf(e),
  }));
}"""


def unnamed(page):
    return [e["el"] for e in page.evaluate(NAMES) if not e["name"]]


def test_every_control_has_an_accessible_name_in_every_state(fields_page):
    page = fields_page
    assert unnamed(page) == []
    page.click("#colsBtn")
    assert unnamed(page) == []                                  # the Columns menu
    page.keyboard.press("Escape")
    _open_column_menu(page, "datatype")
    assert unnamed(page) == []                                  # a column menu
    page.click("#menu >> text=Filter this column")
    assert unnamed(page) == []                                  # the filter form
    page.fill("#menu input", "string")
    page.keyboard.press("Enter")
    page.wait_for_selector("#chips .chip", timeout=10_000)
    assert unnamed(page) == []                                  # chips
    page.locator("#tableWrap tbody tr[data-pos]").first.focus()
    page.keyboard.press("Enter")
    page.wait_for_selector("#drawer.show", timeout=10_000)
    assert unnamed(page) == []                                  # the drawer
    page.keyboard.press("Escape")
    _open(page, "field-renames")
    _wait_meta(page, "3 row(s)")
    assert unnamed(page) == []                                  # the renames toolbar
    _open(page, "graph")
    page.wait_for_selector("#tableWrap svg.graph .node", timeout=10_000)
    assert unnamed(page) == []
    _open(page, "overview")
    page.wait_for_selector("#tableWrap .stat", timeout=10_000)
    assert unnamed(page) == []


def test_ids_are_unique_and_the_landmarks_and_headings_are_right(fields_page):
    page = fields_page
    ids = page.eval_on_selector_all("[id]", "els => els.map(e => e.id)")
    assert len(ids) == len(set(ids)), [i for i in ids if ids.count(i) > 1]
    assert page.get_attribute("html", "lang") == "en"
    assert page.title().strip()
    # the drawer has a <header> of its own, which is not a page banner
    assert page.locator("body > header").count() == 1 and page.locator("main#main").count() == 1
    assert page.get_attribute("nav#nav", "aria-label") == "Tables"
    assert page.locator(".skip").get_attribute("href") == "#main" and page.locator("#main").count() == 1
    # one visible h1; the drawer's h2 appears with the drawer
    assert page.locator("h1:visible").count() == 1
    levels = page.eval_on_selector_all("h1:not([hidden]), h2:not([hidden]), h3", "els => els.filter(e => e.getClientRects().length).map(e => e.tagName)")
    assert levels == ["H1"]
    for region in ("status", "announce"):
        assert page.get_attribute(f"#{region}", "role") == "status"
        assert page.get_attribute(f"#{region}", "aria-live") == "polite"
    assert page.get_attribute("#drawer", "role") == "dialog" and page.get_attribute("#drawer", "aria-labelledby") == "drawerTitle"


TABLE_ARIA = """() => {
  const table = document.querySelector('#tableWrap table');
  const heads = [...table.querySelectorAll('thead th')];
  const rows = [...table.querySelectorAll('tbody tr[data-pos]')];
  const sorts = heads.map((h) => h.getAttribute('aria-sort'));
  return {
    rowcount: Number(table.getAttribute('aria-rowcount')), colcount: Number(table.getAttribute('aria-colcount')),
    colindex: heads.map((h) => Number(h.getAttribute('aria-colindex'))),
    sorts, rowindex: rows.map((r) => Number(r.getAttribute('aria-rowindex'))), pos: rows.map((r) => Number(r.dataset.pos)),
    cellsPerRow: [...new Set(rows.map((r) => r.cells.length))],
    spacers: [...table.querySelectorAll('tr.spacer')].map((r) => r.getAttribute('aria-hidden')),
    headerRowIndex: table.querySelector('thead tr').getAttribute('aria-rowindex'),
  };
}"""


@pytest.mark.parametrize("sort_first", [False, True])
def test_table_aria_stays_consistent_while_scrolling(page, wenjie_path, sort_first):
    n = 800
    open_synthetic(page, wenjie_path, ["name", "n", "x"], [[f"r{i}", i, i / 2] for i in range(n)])
    if sort_first:
        stamp = render_stamp(page)
        _header(page, "n").focus()
        page.keyboard.press("Space")
        wait_render(page, stamp)
    for target in (0, 500, 9000, 16000, 31000):
        page.evaluate("(t) => { document.getElementById('tableWrap').scrollTop = t; }", target)
        page.wait_for_function("() => new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(() => r(true))))")
        f = page.evaluate(TABLE_ARIA)
        assert f["rowcount"] == n + 1 and f["colcount"] == 3
        assert f["colindex"] == [1, 2, 3] and f["headerRowIndex"] == "1"
        assert f["rowindex"] == [p + 2 for p in f["pos"]]
        assert f["cellsPerRow"] == [3], "every rendered row must have one cell per column"
        assert set(f["spacers"]) == {"true"}
        assert set(f["sorts"]) <= {"none", "ascending", "descending"} and sum(s != "none" for s in f["sorts"]) == (1 if sort_first else 0)


# ====================================================================================== contrast of what is drawn

AUDIT = """() => {
  const parse = (c) => { const m = c.match(/rgba?\\(([^)]+)\\)/); if (!m) return null;
    const p = m[1].split(',').map((x) => parseFloat(x)); return {r: p[0], g: p[1], b: p[2], a: p.length > 3 ? p[3] : 1}; };
  const over = (top, bottom) => { const a = top.a + bottom.a * (1 - top.a);
    return a === 0 ? {r: 0, g: 0, b: 0, a: 0} : {r: (top.r * top.a + bottom.r * bottom.a * (1 - top.a)) / a,
      g: (top.g * top.a + bottom.g * bottom.a * (1 - top.a)) / a, b: (top.b * top.a + bottom.b * bottom.a * (1 - top.a)) / a, a}; };
  const background = (el) => {
    const chain = []; for (let e = el; e; e = e.parentElement) chain.push(e);
    let acc = {r: 255, g: 255, b: 255, a: 1}; let image = false;
    for (let i = chain.length - 1; i >= 0; i--) { const cs = getComputedStyle(chain[i]); const c = parse(cs.backgroundColor);
      if (c && c.a > 0) acc = over(c, acc); if (cs.backgroundImage !== 'none') image = true; }
    return {acc, image}; };
  const opacity = (el) => { let o = 1; for (let e = el; e; e = e.parentElement) o *= parseFloat(getComputedStyle(e).opacity); return o; };
  const out = [];
  const describe = (e) => e.tagName.toLowerCase() + (e.id ? '#' + e.id : '') + (e.className && typeof e.className === 'string' ? '.' + e.className.split(' ')[0] : '');
  const consider = (el, text, color, size, weight, extra) => {
    const bg = background(el); const fg = parse(color); if (!fg || bg.image) return;
    const o = opacity(el); const blended = over({...fg, a: fg.a * o}, bg.acc);
    out.push({el: describe(el) + (extra || ''), text: text.slice(0, 40), fg: [blended.r, blended.g, blended.b], bg: [bg.acc.r, bg.acc.g, bg.acc.b], size, weight}); };
  for (const el of document.body.querySelectorAll('*')) {
    if (['SCRIPT', 'STYLE', 'SVG', 'PATH', 'LINK'].includes(el.tagName.toUpperCase())) continue;
    const cs = getComputedStyle(el);
    if (cs.display === 'none' || cs.visibility === 'hidden' || !el.getClientRects().length) continue;
    if (el.closest('[hidden], .sr-only, [aria-hidden="true"]')) continue;
    if (el.disabled || el.getAttribute('aria-disabled') === 'true') continue;       // inactive controls are exempt
    if (opacity(el) < 0.99) continue;                                              // mid-transition
    const own = [...el.childNodes].filter((n) => n.nodeType === 3 && n.textContent.trim()).map((n) => n.textContent.trim()).join(' ');
    if (own) consider(el, own, cs.color, parseFloat(cs.fontSize), parseInt(cs.fontWeight, 10) || 400);
    if ((el.tagName === 'INPUT' || el.tagName === 'TEXTAREA') && el.placeholder && !el.value) {
      const ph = getComputedStyle(el, '::placeholder');
      consider(el, el.placeholder, ph.color, parseFloat(cs.fontSize), 400, '::placeholder');
    }
  }
  return out;
}"""


def luminance(rgb):
    def channel(c):
        c = c / 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = (channel(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a, b):
    hi, lo = sorted((luminance(a), luminance(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def failures(page, state):
    bad = []
    for item in page.evaluate(AUDIT):
        large = item["size"] >= 24 or (item["size"] >= 18.66 and item["weight"] >= 700)
        need = 3.0 if large else 4.5
        ratio = contrast(item["fg"], item["bg"])
        if ratio < need:
            bad.append(f"[{state}] {item['el']} {item['text']!r}: {ratio:.2f}:1 (needs {need})")
    return bad


def settle(page):
    page.wait_for_timeout(450)  # let fades, slides and view transitions finish before measuring


@pytest.mark.parametrize("scheme", ["light", "dark"])
def test_all_rendered_text_has_enough_contrast(browser, gui_server, wenjie_path, scheme):
    pg = new_page(browser, gui_server, color_scheme=scheme, viewport={"width": 1366, "height": 800})
    found = []
    try:
        settle(pg)
        found += failures(pg, "start screen")
        _load(pg, wenjie_path)
        pg.wait_for_selector("#tableWrap .stat", timeout=10_000)
        settle(pg)
        found += failures(pg, "overview, toast showing")
        _open(pg, "fields")
        _wait_meta(pg, "55 row(s)")
        settle(pg)
        found += failures(pg, "fields")
        pg.locator("#tableWrap tbody tr[data-pos]").nth(2).hover()
        found += failures(pg, "a hovered row")
        pg.locator("#tableWrap tbody tr[data-pos]").nth(3).focus()
        found += failures(pg, "a focused row")
        _open_column_menu(pg, "datatype")
        settle(pg)
        found += failures(pg, "column menu (with an unavailable item)")
        pg.click("#menu >> text=Filter this column")
        found += failures(pg, "filter form")
        pg.fill("#menu input", "string")
        pg.keyboard.press("Enter")
        pg.wait_for_selector("#chips .chip", timeout=10_000)
        settle(pg)
        found += failures(pg, "filter chip")
        pg.locator("#tableWrap tbody tr[data-pos]").first.click(position={"x": 20, "y": 8})
        pg.wait_for_selector("#drawer.show", timeout=10_000)
        settle(pg)
        found += failures(pg, "details drawer")
        pg.keyboard.press("Escape")
        pg.wait_for_selector("#drawer", state="hidden", timeout=10_000)
        pg.click("#densityBtn")
        settle(pg)
        found += failures(pg, "compact rows")
        pg.click("#colsBtn")
        found += failures(pg, "Columns menu")
        pg.keyboard.press("Escape")
        _open(pg, "field-renames")
        _wait_meta(pg, "3 row(s)")
        settle(pg)
        found += failures(pg, "field renames")
        _open(pg, "graph")
        pg.wait_for_selector("#tableWrap svg.graph .node", timeout=10_000)
        settle(pg)
        found += failures(pg, "graph")
        pg.fill("#path", "/no/such/workbook.twb")
        pg.click("#loadBtn")
        pg.wait_for_function("() => document.getElementById('status').classList.contains('err')", timeout=10_000)
        settle(pg)
        found += failures(pg, "error toast")
        # the bad path is the point of the last state, and Chromium logs the 400 it answers with
        assert [e for e in pg.js_errors if "400" not in e and "Bad Request" not in e] == []
    finally:
        pg.ctx.close()
    assert not found, f"{len(found)} text elements fall below WCAG AA in the {scheme} theme:\n  " + "\n  ".join(found[:25])


def test_the_contrast_audit_really_catches_a_bad_colour(page, wenjie_path):
    """The audit itself is checked: make some text unreadable and it must be reported."""
    _load(page, wenjie_path)
    _open(page, "fields")
    _wait_meta(page, "55 row(s)")
    settle(page)
    assert failures(page, "baseline") == []
    page.add_style_tag(content=".desc { color: #cccccc !important; }")
    bad = failures(page, "sabotaged")
    assert any(".desc" in item for item in bad), bad


# ====================================================================================== motion


def test_reduced_motion_stops_every_animation_and_every_view_transition(browser, gui_server, wenjie_path):
    pg = new_page(browser, gui_server, reduced_motion="reduce", viewport={"width": 1366, "height": 800})
    try:
        _load(pg, wenjie_path)
        _open(pg, "fields")
        _wait_meta(pg, "55 row(s)")
        pg.evaluate(
            "() => { window.__vt = 0; if (document.startViewTransition) { const f = document.startViewTransition.bind(document);"
            " document.startViewTransition = (cb) => { window.__vt++; return f(cb); }; } }"
        )
        stamp = render_stamp(pg)
        _header(pg, "name").click()
        wait_render(pg, stamp)
        _open_column_menu(pg, "datatype")
        pg.click("#menu >> text=Sort descending")
        pg.locator("#tableWrap tbody tr[data-pos]").first.click(position={"x": 20, "y": 8})
        pg.wait_for_selector("#drawer.show", timeout=10_000)
        assert pg.evaluate("() => window.__vt") == 0, "a view transition was started although reduced motion was requested"
        slow = pg.evaluate(
            """() => {
              const secs = (s) => s.split(',').map((x) => parseFloat(x) * (x.trim().endsWith('ms') ? 0.001 : 1));
              return [...document.querySelectorAll('body *')].filter((e) => e.getClientRects().length).flatMap((e) => {
                const cs = getComputedStyle(e);
                const t = Math.max(...secs(cs.transitionDuration)); const a = cs.animationName === 'none' ? 0 : Math.max(...secs(cs.animationDuration));
                return Math.max(t, a) > 0.001 ? [e.tagName.toLowerCase() + (e.id ? '#' + e.id : '') + '.' + String(e.className).split(' ')[0] + ' ' + Math.max(t, a) + 's'] : [];
              });
            }"""
        )
        assert slow == [], f"animations still running under reduced motion: {slow[:8]}"
        assert pg.js_errors == []
    finally:
        pg.ctx.close()


def test_normal_motion_does_use_view_transitions_where_available(browser, gui_server, wenjie_path):
    pg = new_page(browser, gui_server, viewport={"width": 1366, "height": 800})
    try:
        if not pg.evaluate("() => !!document.startViewTransition"):
            pytest.skip("this browser has no View Transitions API")
        _load(pg, wenjie_path)
        _open(pg, "fields")
        _wait_meta(pg, "55 row(s)")
        pg.evaluate(
            "() => { window.__vt = 0; const f = document.startViewTransition.bind(document);"
            " document.startViewTransition = (cb) => { window.__vt++; return f(cb); }; }"
        )
        stamp = render_stamp(pg)
        _header(pg, "name").click()
        wait_render(pg, stamp)
        assert pg.evaluate("() => window.__vt") >= 1
    finally:
        pg.ctx.close()


# ====================================================================================== disabled controls

BUTTON_LOOK = """sel => { const cs = getComputedStyle(document.querySelector(sel));
  return {bg: cs.backgroundColor, color: cs.color, border: cs.borderStyle, cursor: cs.cursor}; }"""


@pytest.mark.parametrize("scheme", ["light", "dark"])
def test_a_disabled_primary_button_does_not_look_enabled(browser, gui_server, tmp_path, scheme):
    # "Export library file" is a primary button that is off until a row is ticked; off, it used to keep its
    # filled look, and in dark mode read as enabled (#143)
    path = workbook(tmp_path, calcs=[("[Calculation_1]", "Ratio", "[Sales] / [Profit]")], name="one.twb")
    pg = new_page(browser, gui_server, color_scheme=scheme, viewport={"width": 1280, "height": 900})
    try:
        _load(pg, path)
        _open(pg, "libraries")
        pg.wait_for_selector("#libTable", timeout=10_000)
        settle(pg)
        assert pg.is_disabled("#libExport")
        off = pg.evaluate(BUTTON_LOOK, "#libExport")
        load = pg.evaluate(BUTTON_LOOK, "#loadBtn")             # an enabled primary button for comparison
        pg.check("#libRow0")
        pg.wait_for_function("() => !document.getElementById('libExport').disabled", timeout=10_000)
        settle(pg)
        on = pg.evaluate(BUTTON_LOOK, "#libExport")
        assert on["bg"] == load["bg"] and on["color"] == load["color"]
        assert off["bg"] != on["bg"] and off["color"] != on["color"], (off, on)
        assert off["border"] == "dashed" and on["border"] == "solid"
        assert off["cursor"] == "not-allowed" and on["cursor"] == "pointer"
        assert pg.js_errors == []
    finally:
        pg.ctx.close()
