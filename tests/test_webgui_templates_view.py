"""The Templates view's page files (WP9 package 9c), checked without a browser: what index.html, templates.js
and the hooks in app.js promise each other. The behaviour itself is in `tests/test_gui_templates.py`, which needs
Chromium; these cheap checks catch a renamed id or a missing hook where a browser is not available."""

from __future__ import annotations

import re
import urllib.request
from pathlib import Path

import pytest

from py_tbparse import webgui
from test_webgui import _page_script, server  # noqa: F401  (the fixture and helper of the page tests)

WEBUI = Path(webgui.__file__).parent / "webui"


@pytest.fixture(scope="module")
def html() -> str:
    return (WEBUI / "index.html").read_text(encoding="utf-8")


def _ids(text: str) -> set[str]:
    return set(re.findall(r'\bid="([^"]+)"', text))


def test_the_page_has_the_templates_button_and_the_view(html):
    ids = _ids(html)
    for needed in ("tplBtn", "templatesView", "tplBack", "tplTitle", "tplTemplatePick", "tplDataPick",
                   "tplCard1", "tplCard2", "tplCard3", "tplBody1", "tplBody2", "tplBody3", "dropTitle", "dropNote"):
        assert needed in ids, needed
    assert re.search(r'<button id="tplBtn"[^>]*aria-pressed="false"', html)
    assert re.search(r'<section id="templatesView"[^>]*\bhidden\b', html)
    # the button sits in the top bar, with the Theme button
    assert html.index('id="tplBtn"') < html.index('id="themeBtn"') < html.index("</header>")
    # the view comes after the workbook workspace
    assert html.index('id="controls"') < html.index('id="templatesView"')


def test_ids_are_unique(html):
    found = re.findall(r'\bid="([^"]+)"', html)
    assert len(found) == len(set(found)), sorted({i for i in found if found.count(i) > 1})


def test_the_file_inputs_take_only_what_each_step_takes(html):
    template = re.search(r'<input id="tplTemplatePick"[^>]*>', html).group(0)
    data = re.search(r'<input id="tplDataPick"[^>]*>', html).group(0)
    assert 'accept=".twbx"' in template
    assert 'accept=".csv,.tsv,.txt,.xlsx,.xlsm,.twb,.twbx,.tds"' in data
    for tag in (template, data):
        assert "hidden" in tag and 'tabindex="-1"' in tag and 'aria-hidden="true"' in tag


def test_the_steps_are_a_list_in_order_and_the_later_ones_start_locked(html):
    cards = re.findall(r'<li id="(tplCard\d)"([^>]*)>', html)
    assert [c[0] for c in cards] == ["tplCard1", "tplCard2", "tplCard3"]
    assert 'data-slot="template"' in cards[0][1]
    assert 'data-slot="data"' in cards[1][1]
    assert 'data-slot="review"' in cards[2][1]


def test_scripts_load_in_order(html):
    order = [html.index(f'<script src="/static/{n}.js">') for n in ("table", "graph", "templates", "app")]
    assert order == sorted(order)


def test_templates_js_is_served_and_defines_the_view(server):  # noqa: F811
    with urllib.request.urlopen(server + "/static/templates.js") as r:
        assert r.headers["Content-Type"].startswith("text/javascript")
    js = _page_script(server, "templates.js")
    assert "window.TemplatesView = " in js
    for member in ("init", "show", "hide", "acceptDrop", "dropHint", "getState"):
        assert re.search(rf"\b{member}\b", js), member
    # it uses the endpoints of 9b and nothing else
    routes = set(re.findall(r"'(/template/[a-z-]+)'", js))
    assert routes == {"/template/state", "/template/upload-template", "/template/upload-data", "/template/open",
                      "/template/open-data", "/template/select-data"}


def test_templates_js_keeps_to_the_page_rules(server):  # noqa: F811
    js = _page_script(server, "templates.js")
    # one scope: nothing it declares can collide with app.js, whose top-level consts are shared by every script
    assert js.lstrip().startswith(("//", "(function")) and js.rstrip().endswith("})();")
    assert "innerHTML" not in js, "text reaches the page through textContent only"
    assert "localStorage" not in js
    # colours come from the style sheets, never from the script
    assert not re.search(r"#[0-9a-fA-F]{3,6}\b", js)
    # it never draws every row of anything: lists are cut off
    for cap in ("SHOW_STEP", "SHOW_MAX", "COLUMN_CAP"):
        assert cap in js, cap


def test_app_js_has_the_hooks_and_nothing_more(server):  # noqa: F811
    js = _page_script(server)
    for hook in ("TemplatesView.init(", "TemplatesView.acceptDrop(", "TemplatesView.dropHint(",
                 "function setTemplatesMode(", "'#templates'", "tplBtn"):
        assert hook in js, hook
    # the page-level drop hands files to the view while it is open, and opens a workbook otherwise
    drop = js[js.index("window.addEventListener('drop'"):]
    assert drop.index("tplOpen") < drop.index("uploadFile(files[0])")


def test_css_uses_tokens_for_the_view():
    css = (WEBUI / "app.css").read_text(encoding="utf-8")
    block = css[css.index("/* templates view */"):]
    block = block[: block.index("/* end templates view */")]
    assert ".tpl-card" in block
    assert not re.search(r"#[0-9a-fA-F]{3,6}\b", block), "colours come from tokens.css and the themes"
    assert not re.search(r"\d+m?s\b", re.sub(r"var\(--dur-[a-z]+\)", "", block)), "motion uses the --dur tokens"
