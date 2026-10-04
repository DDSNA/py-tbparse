#!/usr/bin/env python3
"""Take the screenshots the README shows, from the made-up demo workbook.

    python scripts/make_demo_workbook.py          # once: docs/demo/coffee-shop.twb
    python scripts/readme_screenshots.py          # writes docs/gui-*.png

Four views: the overview report card, field renames, the relationship graph with a table highlighted, and the
fields table in a dark theme with the theme menu open. Needs Playwright and Chromium, set up the way the
browser tests are (see AGENTS.md); `.browser-libs/` is used when it exists.
"""

from __future__ import annotations

import sys
import threading
import time
from http.server import ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from gui_screenshots import _FREEZE, _setup_env  # noqa: E402

DEMO = ROOT / "docs" / "demo" / "coffee-shop.twb"
OUT = ROOT / "docs"
SIZE = {"width": 1240, "height": 1080}


def main() -> int:
    from playwright.sync_api import sync_playwright

    from py_tbparse import webgui

    if not DEMO.exists():
        print("missing", DEMO, "- run scripts/make_demo_workbook.py first")
        return 1
    env = _setup_env()
    # the page shows the installed package's version, which in a development checkout can be stale
    import re
    webgui.__version__ = re.search(r'^version = "([^"]+)"', (ROOT / "pyproject.toml").read_text(), re.M).group(1)
    srv = ThreadingHTTPServer(("127.0.0.1", 0), webgui.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = "http://%s:%d" % srv.server_address

    def prepare(browser, theme="shop", mode="light"):
        page = browser.new_page(viewport=SIZE, color_scheme=mode)
        page.goto(url)
        page.evaluate("([t, m]) => { localStorage.setItem('py-tbparse:theme', t); localStorage.setItem('py-tbparse:mode', m); }",
                      [theme, mode])
        page.reload()
        page.add_style_tag(content=_FREEZE)
        page.fill("#path", str(DEMO))
        page.click("#loadBtn")
        page.wait_for_selector("#tableWrap .health", timeout=15000)
        page.fill("#path", "~/workbooks/coffee-shop.twb")   # not the path of this checkout
        page.evaluate("() => document.activeElement.blur()")
        time.sleep(0.5)
        return page

    def go(page, table):
        page.click(f'.nav-item[data-table="{table}"]')
        time.sleep(0.9)

    def shot(page, name):
        page.evaluate("() => { const t = document.getElementById('status'); t.classList.remove('show'); }")
        page.screenshot(path=str(OUT / name))
        print("wrote", OUT / name)

    with sync_playwright() as pw:
        browser = pw.chromium.launch(env=env)
        page = prepare(browser)
        shot(page, "gui-overview.png")
        go(page, "field-renames")
        shot(page, "gui-field-renames.png")
        go(page, "graph")
        page.locator('#tableWrap .node[data-id="Orders"]').hover()
        time.sleep(0.3)
        shot(page, "gui-graph.png")
        page.close()

        page = prepare(browser, theme="harbor", mode="dark")
        go(page, "fields")
        page.click("#themeBtn")
        time.sleep(0.4)
        shot(page, "gui-themes.png")
        page.close()
        browser.close()
    srv.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
