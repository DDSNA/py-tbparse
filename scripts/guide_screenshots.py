#!/usr/bin/env python3
"""Take the screenshots of the user's guide in the README (docs/guide-*.png).

    python scripts/fetch_corpus.py            # once: the public workbooks under tests/corpus/files
    python scripts/guide_screenshots.py       # writes docs/guide-*.png
    python scripts/guide_screenshots.py --out /tmp/shots

The guide follows one public workbook, Brushing_Superstore_Sales_Map.twb from
github.com/1230harry/TeamOne_MSc_Group_Project (MIT, in the corpus). It is first run through `sanitize`
into a temporary folder, so the local file path it holds never reaches a picture; the corpus file itself
is not changed and is never committed. The other inputs (a target workbook, a palette file, a small CSV)
are made in the same temporary folder. Needs Playwright and Chromium, set up the way the browser tests are
(see AGENTS.md); `.browser-libs/` at the repo root is used when it exists, else PY_TBPARSE_BROWSER_LIBS.
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import sys
import tempfile
import threading
import time
from http.server import ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

CORPUS = ROOT / "tests" / "corpus" / "files" / "1230harry__TeamOne_MSc_Group_Project__Brushing_Superstore_Sales_Map.twb"
NAME = "superstore-sales-map.twb"
SHOWN_PATH = "C:\\Users\\you\\Documents\\Tableau\\" + NAME   # what the path box shows instead of the temporary folder
SIZE = {"width": 1360, "height": 900}

_FREEZE = ("*,*::before,*::after{caret-color:transparent!important;animation:none!important;"
           "transition:none!important;scroll-behavior:auto!important}")

_TPS = """<?xml version='1.0'?>
<workbook>
  <preferences>
    <color-palette name="Superstore Brand" type="regular">
      <color>#1F4E79</color><color>#2E86AB</color><color>#F18F01</color>
      <color>#C73E1D</color><color>#3B8B5A</color><color>#6C757D</color>
    </color-palette>
    <color-palette name="Profit Diverging" type="ordered-diverging">
      <color>#B2182B</color><color>#F7F7F7</color><color>#2166AC</color>
    </color-palette>
  </preferences>
</workbook>
"""

_CSV = ("State,Region,Category,Sub_Category,Sales Amount,Order Date\n"
        "Ohio,East,Furniture,Chairs,120.5,2026-01-03\n"
        "Texas,Central,Technology,Phones,99.0,2026-01-04\n")


def _env() -> dict:
    libs = ROOT / ".browser-libs"
    if not libs.is_dir() and os.environ.get("PY_TBPARSE_BROWSER_LIBS"):
        libs = Path(os.environ["PY_TBPARSE_BROWSER_LIBS"])
    env = dict(os.environ)
    if libs.is_dir():
        os.environ.setdefault("FONTCONFIG_FILE", str(libs / "fonts.conf"))
        os.environ.setdefault("XKB_CONFIG_ROOT", str(libs / "root/usr/share/X11/xkb"))
        env.update(FONTCONFIG_FILE=os.environ["FONTCONFIG_FILE"], XKB_CONFIG_ROOT=os.environ["XKB_CONFIG_ROOT"],
                   LD_LIBRARY_PATH=str(libs / "root/usr/lib/x86_64-linux-gnu"))
    return env


def _inputs(tmp: Path) -> dict:
    from py_tbparse import sanitize

    wb = tmp / NAME
    sanitize(str(CORPUS), str(wb))
    target = tmp / "target" / "superstore-copy.twb"
    target.parent.mkdir()
    shutil.copyfile(wb, target)
    tps = tmp / "brand-palettes.tps"
    tps.write_text(_TPS, encoding="utf-8")
    csv = tmp / "new-sales.csv"
    csv.write_text(_CSV, encoding="utf-8")
    return {"wb": wb, "target": target, "tps": tps, "csv": csv}


def capture(out: Path, files: dict) -> list[str]:
    from playwright.sync_api import sync_playwright

    from py_tbparse import webgui

    out.mkdir(parents=True, exist_ok=True)
    env = _env()
    webgui.__version__ = re.search(r'^version = "([^"]+)"', (ROOT / "pyproject.toml").read_text(), re.M).group(1)
    srv = ThreadingHTTPServer(("127.0.0.1", 0), webgui.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = "http://%s:%d" % srv.server_address
    names: list[str] = []

    def shot(page, name):
        page.add_style_tag(content=_FREEZE)
        page.evaluate("() => { const t = document.getElementById('status'); if (t) t.classList.remove('show');"
                      " if (document.activeElement && document.activeElement.blur) document.activeElement.blur(); }")
        time.sleep(0.3)
        page.screenshot(path=str(out / name))
        names.append(name)
        print("wrote", out / name)

    def new_page(browser, mode="light", height=None):
        page = browser.new_page(viewport=dict(SIZE, height=height or SIZE["height"]), color_scheme=mode)
        page.goto(url)
        page.evaluate("(m) => { localStorage.setItem('py-tbparse:theme', 'shop'); localStorage.setItem('py-tbparse:mode', m); }", mode)
        page.reload()
        return page

    def load(page):
        page.fill("#path", str(files["wb"]))
        page.click("#loadBtn")
        page.wait_for_selector("#tableWrap .health", timeout=20000)
        page.fill("#path", SHOWN_PATH)
        time.sleep(0.5)

    def go(page, table):
        page.click(f'.nav-item[data-table="{table}"]')
        time.sleep(1.0)

    def scroll_to(page, selector, margin=24):
        # scroll only the panel that holds the element, so the page itself (header, sidebar) stays put
        page.evaluate("""([s, m]) => {
            window.scrollTo(0, 0);
            const el = document.querySelector(s);
            let box = el.parentElement;
            while (box && !(box.scrollHeight > box.clientHeight + 1 && /(auto|scroll)/.test(getComputedStyle(box).overflowY))) {
                box = box.parentElement;
            }
            if (!box) { window.scrollBy(0, el.getBoundingClientRect().top - 67 - m); return; }   // 67: the top bar
            box.scrollTop += el.getBoundingClientRect().top - box.getBoundingClientRect().top - m;
        }""", [selector, margin])
        time.sleep(0.4)

    with sync_playwright() as pw:
        browser = pw.chromium.launch(env=env)

        page = new_page(browser)
        time.sleep(0.4)
        shot(page, "guide-start.png")
        load(page)
        shot(page, "guide-overview.png")
        go(page, "calculated-fields")
        page.locator("#tableWrap tbody tr", has_text="Profit Ratio").first.click()
        page.wait_for_selector("#drawer.show", timeout=5000)
        time.sleep(0.5)
        shot(page, "guide-tables.png")
        page.click("#drawerClose")
        time.sleep(0.5)
        go(page, "field-renames")
        shot(page, "guide-renames.png")
        go(page, "graph")
        page.locator('#tableWrap .node[data-id="Orders"]').hover()
        time.sleep(0.3)
        shot(page, "guide-graph.png")
        go(page, "audit")
        shot(page, "guide-audit.png")

        go(page, "libraries")
        page.check("#libRow0")
        page.check("#libRow2")
        time.sleep(0.4)
        scroll_to(page, "#libExport", margin=420)
        shot(page, "guide-libraries.png")

        go(page, "styles")
        page.set_input_files("#styFile", str(files["tps"]))
        page.wait_for_selector("#styPlanBox", timeout=15000)
        time.sleep(0.8)
        scroll_to(page, "#styFile", margin=140)
        shot(page, "guide-styles.png")

        go(page, "copy")
        page.check("#cpyDashRow0")
        time.sleep(1.2)
        scroll_to(page, "#cpySliceSummary", margin=90)
        shot(page, "guide-slice.png")
        page.set_input_files("#cpyFile", str(files["target"]))
        time.sleep(1.5)
        page.check("#cpySheetRow0")
        time.sleep(1.5)
        scroll_to(page, "#cpyPolicy")
        page.check('#cpyPolicy input[value="rename"]')
        time.sleep(1.5)
        scroll_to(page, "#cpyPolicy")
        shot(page, "guide-copy-rename.png")
        page.close()

        page = new_page(browser, height=520)
        load(page)
        go(page, "dashboards")
        shot(page, "guide-dashboards.png")
        page.close()

        page = new_page(browser, mode="dark")
        load(page)
        page.click("#themeBtn")
        page.wait_for_selector("#menu:not([hidden])", timeout=5000)
        time.sleep(0.4)
        shot(page, "guide-dark.png")
        page.close()

        page = new_page(browser)
        load(page)
        page.click("#tplBtn") if page.locator("#tplBtn").count() else page.goto(url + "/#templates")
        page.wait_for_selector("#tplMakeBtn")
        time.sleep(0.8)
        shot(page, "guide-templates.png")
        page.fill("#tplMakeName", "Superstore sales map") if page.locator("#tplMakeName").count() else None
        page.click("#tplMakeBtn")
        page.wait_for_selector("#tplMadeUse", timeout=30000)
        scroll_to(page, "#tplMakeTitle", margin=16)
        shot(page, "guide-template-make.png")
        page.click("#tplMadeUse")
        page.wait_for_selector("#tplCard1[data-state=done]", timeout=15000)
        page.set_input_files("#tplDataPick", str(files["csv"]))
        page.wait_for_selector("#tplMapBody tr", timeout=15000)
        time.sleep(1.5)
        scroll_to(page, "#tplCard3", margin=16)
        shot(page, "guide-template-mapping.png")
        for field, column in (("State/Province", "State"), ("Sales", "Sales Amount")):
            sel = page.locator(f'select[aria-label="Column for {field}"]')
            sel.focus()   # the page fills a column menu when it gets focus
            time.sleep(0.3)
            value = sel.evaluate("(s, c) => [...s.options].find(o => o.textContent.trim().startsWith(c)).value", column)
            sel.select_option(value=value)
            time.sleep(1.5)
        time.sleep(1.5)
        scroll_to(page, "#tplCreate", margin=560)
        shot(page, "guide-template-create.png")
        page.close()
        browser.close()
    srv.shutdown()
    return names


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=str(ROOT / "docs"), help="folder for the PNGs (default: docs/)")
    args = ap.parse_args()
    if not CORPUS.exists():
        print("missing", CORPUS, "- run scripts/fetch_corpus.py first")
        return 1
    with tempfile.TemporaryDirectory() as tmp:
        names = capture(Path(args.out), _inputs(Path(tmp)))
    print(f"captured {len(names)} screenshots in {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
