"""The design tokens (py_tbparse/webui/tokens.css) must keep the GUI readable.

These read the real stylesheets, so changing a colour or fading text with `opacity` fails here
instead of shipping. Contrast is WCAG 2.x relative luminance.
"""

import re
from pathlib import Path

import pytest

WEBUI = Path(__file__).resolve().parent.parent / "py_tbparse" / "webui"
TOKENS = (WEBUI / "tokens.css").read_text(encoding="utf-8")
THEMES_CSS = (WEBUI / "themes.css").read_text(encoding="utf-8")
APP_CSS = (WEBUI / "app.css").read_text(encoding="utf-8")

_HEX = re.compile(r"--([a-z0-9-]+):\s*(#[0-9a-fA-F]{6})\s*;")


def _colours(block: str) -> dict:
    return dict(_HEX.findall(block))


_LIGHT_BLOCK, _, _REST = TOKENS.partition(':root[data-mode="dark"]')
_DARK_BLOCK, _, _REDUCED_BLOCK = _REST.partition("@media (prefers-reduced-motion")
LIGHT = _colours(_LIGHT_BLOCK)
DARK = {**LIGHT, **_colours(_DARK_BLOCK)}

# every theme in themes.css, light and dark, as complete palettes (a theme never inherits colours)
_THEME_RULE = re.compile(r'\[data-theme="([a-z]+)"\](\[data-mode="dark"\])?\s*\{([^}]*)\}')
THEMES = {}
for _name, _dark, _body in _THEME_RULE.findall(THEMES_CSS):
    THEMES.setdefault(_name, {})["dark" if _dark else "light"] = _colours(_body)


def _lum(hex_colour: str) -> float:
    r, g, b = (int(hex_colour[i:i + 2], 16) / 255 for i in (1, 3, 5))
    f = lambda c: c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4  # noqa: E731
    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b)


def contrast(a: str, b: str) -> float:
    hi, lo = sorted((_lum(a), _lum(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


# (foreground token, background token, where the GUI puts it)
TEXT_PAIRS = [
    ("text", "panel", "body text, table cells"),
    ("text", "bg", "text on the page background"),
    ("text", "hover", "table row and nav hover"),
    ("text", "code-bg", "inline code"),
    ("text", "primary-soft", "an expanded table row"),
    ("text", "danger-soft", "an error toast"),
    ("muted", "panel", "descriptions, labels, counts"),
    ("muted", "bg", "tile captions, placeholders"),
    ("muted", "hover", "counts on a hovered nav item"),
    ("muted", "code-bg", "the default pill"),
    ("faint", "panel", "zero counts, empty cells, zero tiles"),
    ("faint", "hover", "an empty cell in a hovered row"),
    ("faint", "primary-soft", "an empty cell in an expanded row"),
    ("primary-text", "primary", "the label on a primary button"),
    ("primary-on-soft", "primary-soft", "the active nav item, the yes pill"),
    ("primary", "panel", "sort arrow and header hover"),
    ("accent", "panel", "accent used as text"),
    ("accent", "accent-soft", "accent on its soft background"),
    ("success", "panel", "success text"),
    ("warning", "panel", "warning text"),
    ("danger", "panel", "error text"),
    ("danger", "danger-soft", "error text on its soft background"),
]


ALL_PALETTES = [("shop", "light", LIGHT), ("shop", "dark", DARK)] + [
    (name, mode, pal) for name, modes in THEMES.items() for mode, pal in modes.items()
]
MIN_TEXT = {"contrast": 7.0}   # the High contrast theme promises AAA


@pytest.mark.parametrize("name,mode,palette", ALL_PALETTES, ids=[f"{n}-{m}" for n, m, _ in ALL_PALETTES])
def test_every_text_pair_meets_wcag_aa(name, mode, palette):
    need = MIN_TEXT.get(name, 4.5)
    failures = []
    for fg, bg, where in TEXT_PAIRS:
        ratio = contrast(palette[fg], palette[bg])
        if ratio < need:
            failures.append(f"{fg} on {bg} = {ratio:.2f}:1 ({where})")
    assert not failures, f"{name} {mode} fails {need}:1: {failures}"


@pytest.mark.parametrize("name,mode,palette", ALL_PALETTES, ids=[f"{n}-{m}" for n, m, _ in ALL_PALETTES])
def test_focus_ring_and_borders_you_must_see_have_3_to_1(name, mode, palette):
    # the focus ring is drawn in --primary against panel and page background
    for bg in ("panel", "bg"):
        assert contrast(palette["primary"], palette[bg]) >= 3.0, bg


def test_there_are_five_extra_themes_and_each_has_both_modes():
    assert set(THEMES) == {"matcha", "fjord", "pastel", "neon", "contrast"}   # Shop is the default in tokens.css
    for name, modes in THEMES.items():
        assert set(modes) == {"light", "dark"}, name


@pytest.mark.parametrize("name", sorted(THEMES))
def test_a_theme_defines_every_colour_in_both_modes(name):
    # a theme never inherits a colour from Shop, or switching themes would leave stray warm colours behind
    for mode, palette in THEMES[name].items():
        assert set(palette) == set(LIGHT), f"{name}/{mode}: {sorted(set(LIGHT) ^ set(palette))}"


def test_only_neon_glows_and_only_in_the_dark():
    assert "--glow: 0 0 0 0 transparent" in TOKENS
    glowing = re.findall(r'\[data-theme="([a-z]+)"\](\[data-mode="dark"\])?\s*\{[^}]*--glow:', THEMES_CSS)
    assert glowing == [("neon", '[data-mode="dark"]')]


def test_themes_are_picked_up_by_the_server():
    from py_tbparse import webgui
    assert set(webgui.THEMES) == {"shop"} | set(THEMES)
    assert "themes.css" in webgui._ASSETS


def test_the_dark_theme_defines_every_colour_the_light_one_does():
    assert set(LIGHT) == set(DARK)
    assert "color-scheme: dark" in _DARK_BLOCK and "color-scheme: light;" in _LIGHT_BLOCK
    overridden = set(_colours(_DARK_BLOCK))
    # every colour except the ones that are the same in both themes is redefined for dark
    assert overridden >= set(LIGHT) - {"shadow-color"}, sorted(set(LIGHT) - overridden)


def test_reduced_motion_makes_every_duration_instant():
    for name in ("dur-fast", "dur-base", "dur-slow"):
        assert re.search(rf"--{name}:\s*0\.01ms", _REDUCED_BLOCK), name


def test_comfortable_density_targets():
    assert re.search(r"--target:\s*40px", TOKENS)
    assert re.search(r"--row-h:\s*40px", TOKENS)
    assert re.search(r'\[data-density="compact"\]\s*\{\s*--row-h:\s*32px', TOKENS)
    assert int(re.search(r"--nav-h:\s*(\d+)px", TOKENS).group(1)) >= 38


def test_every_variable_the_stylesheet_uses_is_defined():
    defined = set(re.findall(r"(--[a-z0-9-]+)\s*:", TOKENS + THEMES_CSS + APP_CSS))
    used = set(re.findall(r"var\((--[a-z0-9-]+)", APP_CSS))
    assert not used - defined, f"undefined CSS variables: {sorted(used - defined)}"


def test_text_is_never_faded_with_opacity():
    # `opacity` on text silently lowers contrast below AA; use the --faint colour instead. The only
    # places it is fine: disabled buttons (exempt), the toast and its fade, and animation keyframes.
    # (::placeholder sets opacity:1 to undo the browser's own fade, which is the opposite of fading.)
    allowed = {".btn:disabled", ".toast", ".toast.show", ".drawer", ".drawer.show", "from", "to", "::placeholder"}
    offenders = []
    css = re.sub(r"/\*.*?\*/", "", APP_CSS, flags=re.S)  # comments are not selectors
    for selector, body in re.findall(r"([^{}]+)\{([^{}]*)\}", css):
        if re.search(r"(^|[;\s])opacity\s*:", body):
            names = {part.strip() for part in selector.split(",")}
            if not names <= allowed:
                offenders.append(selector.strip())
    assert not offenders, f"opacity used on: {offenders}"


def test_placeholders_use_a_readable_colour():
    assert re.search(r"::placeholder\s*\{[^}]*color:\s*var\(--muted\)", APP_CSS)
