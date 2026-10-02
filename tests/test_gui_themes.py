"""Colour themes: the picker, persistence, the system setting, no flash, and rendered contrast in every one."""

from __future__ import annotations

import pytest

from test_gui_a11y import failures, settle  # noqa: F401  (the rendered-contrast audit)
from test_gui_browser import _load, _open, _open_column_menu, _wait_meta, new_page

from py_tbparse import webgui

ALL_THEMES = list(webgui.THEMES)
# The heavy per-theme browser tests run on the original six plus a spread of the later ones; the contrast of every
# theme, in both modes, is checked from the stylesheet itself in test_webui_tokens.py.
THEMES = ["shop", "matcha", "fjord", "pastel", "neon", "contrast", "harbor", "graphite", "rose", "peacock"]
LABELS = {"contrast": "High contrast"}


def label(theme):
    return LABELS.get(theme, theme.capitalize())


ROOT = "() => ({theme: document.documentElement.dataset.theme, mode: document.documentElement.dataset.mode,"\
       " pref: document.documentElement.dataset.pref})"
VAR = "(n) => getComputedStyle(document.documentElement).getPropertyValue(n).trim()"


def _stored(page, theme=None, mode=None):
    page.evaluate(
        "([t, m]) => { if (t) localStorage.setItem('py-tbparse:theme', t); if (m) localStorage.setItem('py-tbparse:mode', m); }",
        [theme, mode],
    )
    page.reload()


def _pick(page, label):
    if not page.locator("#menu").is_visible():     # a pick keeps the menu open, so a second pick must not toggle it shut
        page.click("#themeBtn")
    page.click(f'#menu [role="menuitemradio"]:has-text("{label}")')


def test_the_default_is_shop_and_follows_the_system(browser, gui_server):
    for scheme in ("light", "dark"):
        pg = new_page(browser, gui_server, color_scheme=scheme)
        try:
            assert pg.evaluate(ROOT) == {"theme": "shop", "mode": scheme, "pref": "auto"}
            assert pg.evaluate("() => getComputedStyle(document.body).colorScheme") == scheme
            assert pg.js_errors == []
        finally:
            pg.ctx.close()


def test_the_theme_menu_lists_every_theme_and_mode_as_radios(page):
    page.click("#themeBtn")
    assert page.get_attribute("#themeBtn", "aria-expanded") == "true"
    names = page.locator('#menu [role="menuitemradio"]').evaluate_all("els => els.map(e => e.textContent.replace('✓', '').trim())")
    assert names == [label(t) for t in ALL_THEMES] + ["Auto (follow my system)", "Light", "Dark"]
    checked = page.locator('#menu [aria-checked="true"]').evaluate_all("els => els.map(e => e.textContent.replace('✓', '').trim())")
    assert checked == ["Shop", "Auto (follow my system)"]
    assert page.locator("#menu .menu-swatch").count() == len(ALL_THEMES) == 36
    page.keyboard.press("Escape")
    assert page.get_attribute("#themeBtn", "aria-expanded") == "false"
    assert page.evaluate("() => document.activeElement.id") == "themeBtn"


def test_choosing_a_theme_changes_the_colours_at_once_and_keeps_the_menu_open(page):
    before = page.evaluate(VAR, "--primary")
    _pick(page, "Matcha")
    assert page.evaluate(ROOT)["theme"] == "matcha"
    assert page.evaluate(VAR, "--primary") != before
    assert page.locator("#menu").is_visible()
    assert page.locator('#menu [aria-checked="true"]').first.inner_text().replace("✓", "").strip() == "Matcha"
    bg = page.evaluate("() => getComputedStyle(document.body).backgroundColor")
    assert bg == "rgb(243, 244, 236)", bg          # matcha's light --bg (#f3f4ec); the page was emulated light
    assert page.js_errors == []


@pytest.mark.parametrize("theme", THEMES)
def test_every_theme_applies_and_survives_a_reload(page, theme):
    _pick(page, label(theme))
    page.keyboard.press("Escape")
    page.reload()
    assert page.evaluate(ROOT)["theme"] == theme
    assert page.evaluate("() => localStorage.getItem('py-tbparse:theme')") == theme


def test_mode_can_be_forced_and_auto_follows_the_system(browser, gui_server):
    pg = new_page(browser, gui_server, color_scheme="light")
    try:
        _pick(pg, "Dark")
        assert pg.evaluate(ROOT) == {"theme": "shop", "mode": "dark", "pref": "dark"}
        pg.emulate_media(color_scheme="light")
        assert pg.evaluate(ROOT)["mode"] == "dark", "a forced mode ignores the system"
        _pick(pg, "Auto")
        assert pg.evaluate(ROOT) == {"theme": "shop", "mode": "light", "pref": "auto"}
        pg.emulate_media(color_scheme="dark")
        pg.wait_for_function("() => document.documentElement.dataset.mode === 'dark'")
        pg.emulate_media(color_scheme="light")
        pg.wait_for_function("() => document.documentElement.dataset.mode === 'light'")
        _pick(pg, "Light")
        pg.emulate_media(color_scheme="dark")
        pg.wait_for_timeout(100)
        assert pg.evaluate(ROOT)["mode"] == "light"
        assert pg.js_errors == []
    finally:
        pg.ctx.close()


def test_the_saved_theme_is_on_the_page_before_it_first_paints(browser, gui_server):
    ctx = browser.new_context()
    try:
        ctx.add_init_script(
            "localStorage.setItem('py-tbparse:theme', 'neon'); localStorage.setItem('py-tbparse:mode', 'dark');"
            "window.__seen = null;"
            "new MutationObserver(() => { if (document.body && window.__seen === null)"
            " window.__seen = document.documentElement.dataset.theme + '/' + document.documentElement.dataset.mode; })"
            ".observe(document, {childList: true, subtree: true});"
        )
        pg = ctx.new_page()
        pg.goto(gui_server)
        assert pg.evaluate("() => window.__seen") == "neon/dark"
    finally:
        ctx.close()


@pytest.mark.parametrize("theme,mode", [("nonsense", "auto"), ("matcha", "sepia"), ("<script>", "dark"), ("", "")])
def test_bad_saved_values_fall_back_to_the_defaults(page, theme, mode):
    page.evaluate("([t, m]) => { localStorage.setItem('py-tbparse:theme', t); localStorage.setItem('py-tbparse:mode', m); }", [theme, mode])
    page.reload()
    state = page.evaluate(ROOT)
    assert state["theme"] == (theme if theme in THEMES else "shop")
    assert state["pref"] == (mode if mode in ("auto", "light", "dark") else "auto")
    assert state["mode"] in ("light", "dark")
    assert page.js_errors == []


def test_a_blocked_localstorage_does_not_break_the_page(browser, gui_server):
    ctx = browser.new_context()
    try:
        ctx.add_init_script(
            "Object.defineProperty(window, 'localStorage', {get() { throw new Error('blocked'); }});"
        )
        pg = ctx.new_page()
        errors = []
        pg.on("pageerror", lambda e: errors.append(str(e)))
        pg.goto(gui_server)
        assert pg.evaluate(ROOT)["theme"] == "shop"
        pg.click("#themeBtn")
        pg.click('#menu [role="menuitemradio"]:has-text("Fjord")')     # still switches for this visit
        assert pg.evaluate(ROOT)["theme"] == "fjord"
        assert errors == []
    finally:
        ctx.close()


def test_only_neon_in_the_dark_glows(page):
    # the button eases its shadow (--dur-fast), so wait for the transition before reading it
    def glow():
        page.wait_for_timeout(300)
        return page.evaluate("() => getComputedStyle(document.querySelector('#loadBtn')).boxShadow")

    _pick(page, "Neon")
    _pick(page, "Light")
    assert "169, 139, 255" not in glow()
    _pick(page, "Dark")
    assert "169, 139, 255" in glow()
    _pick(page, "Shop")
    assert "169, 139, 255" not in glow()


def test_the_keyboard_can_drive_the_theme_menu(page):
    page.focus("#themeBtn")
    page.keyboard.press("Enter")
    page.keyboard.press("ArrowDown")
    page.keyboard.press("Enter")                       # the second item: Matcha
    assert page.evaluate(ROOT)["theme"] == "matcha"
    assert page.locator("#menu").is_visible()
    page.keyboard.press("Escape")
    assert page.locator("#menu").is_hidden()
    assert page.evaluate("() => document.activeElement.id") == "themeBtn"


def test_a_theme_choice_does_not_reload_or_reset_the_open_workbook(page, wenjie_path):
    _load(page, wenjie_path)
    _open(page, "fields")
    _wait_meta(page, "55 row(s)")
    page.fill("#filter", "string")
    page.wait_for_function("() => /of 55/.test(document.getElementById('meta').textContent) && !/^55 of/.test(document.getElementById('meta').textContent)")
    meta = page.inner_text("#meta")
    _pick(page, "Pastel")
    page.keyboard.press("Escape")
    assert page.input_value("#filter") == "string"
    assert page.inner_text("#meta") == meta, "the table was redrawn or reloaded"
    assert page.locator("#tableWrap tbody tr[data-pos]").count() > 0


def test_every_theme_still_fits_the_top_bar_on_a_phone(browser, gui_server):
    pg = new_page(browser, gui_server, viewport={"width": 320, "height": 640})
    try:
        assert pg.evaluate("() => document.documentElement.scrollWidth <= window.innerWidth")
        assert pg.locator("#themeBtn").is_visible() and pg.locator("#pickBtn").is_visible()
    finally:
        pg.ctx.close()


@pytest.mark.parametrize("theme", THEMES)
@pytest.mark.parametrize("mode", ["light", "dark"])
def test_all_rendered_text_is_readable_in_every_theme(browser, gui_server, wenjie_path, theme, mode):
    pg = new_page(browser, gui_server, viewport={"width": 1366, "height": 800})
    found = []
    try:
        _stored(pg, theme, mode)
        settle(pg)
        found += failures(pg, "start screen")
        pg.click("#themeBtn")
        found += failures(pg, "theme menu")
        pg.keyboard.press("Escape")
        _load(pg, wenjie_path)
        pg.wait_for_selector("#tableWrap .stat", timeout=10_000)
        settle(pg)
        found += failures(pg, "overview")
        _open(pg, "fields")
        _wait_meta(pg, "55 row(s)")
        settle(pg)
        found += failures(pg, "fields")
        pg.locator("#tableWrap tbody tr[data-pos]").nth(2).hover()
        found += failures(pg, "a hovered row")
        _open_column_menu(pg, "datatype")
        settle(pg)
        found += failures(pg, "column menu")
        pg.keyboard.press("Escape")
        pg.locator("#tableWrap tbody tr[data-pos]").first.click(position={"x": 20, "y": 8})
        pg.wait_for_selector("#drawer.show", timeout=10_000)
        settle(pg)
        found += failures(pg, "details drawer")
        assert pg.js_errors == []
    finally:
        pg.ctx.close()
    assert not found, f"{theme}/{mode}: " + "; ".join(found[:12])
