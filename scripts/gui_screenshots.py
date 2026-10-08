#!/usr/bin/env python3
"""Screenshot the GUI in its main states, for before/after comparisons while redesigning it.

    python scripts/gui_screenshots.py WORKBOOK OUT_DIR            # capture
    python scripts/gui_screenshots.py WORKBOOK OUT_DIR --compare BASELINE_DIR

States: start screen, overview (light and dark), fields (light and dark), field renames, relationship
graph, the overview and fields at phone width (390 px), the Templates view, and Audit, Libraries, Styles and
Slice and copy, each in light, dark and at phone width (files 12 to 23). Needs Playwright and Chromium (see the
browser-test setup in AGENTS.md); if `.browser-libs/` exists at the repo root its libraries, fonts and
keyboard data are used, exactly as the browser tests do.

--compare reports each state as identical (same bytes, or same pixels when Pillow is installed) or
different, and exits 1 if any differ. A pure refactor must report all identical; a redesign is expected
to differ, so re-capture the baseline after reviewing the new look.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import sys
import threading
import time
from http.server import ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _setup_env() -> dict:
    libs = ROOT / ".browser-libs"
    env = dict(os.environ)
    if libs.is_dir():
        os.environ.setdefault("FONTCONFIG_FILE", str(libs / "fonts.conf"))
        os.environ.setdefault("XKB_CONFIG_ROOT", str(libs / "root/usr/share/X11/xkb"))
        env.update(FONTCONFIG_FILE=os.environ["FONTCONFIG_FILE"], XKB_CONFIG_ROOT=os.environ["XKB_CONFIG_ROOT"],
                   LD_LIBRARY_PATH=str(libs / "root/usr/lib/x86_64-linux-gnu"))
    return env


# A blinking caret or a running animation would make two captures of the same page differ.
_FREEZE = "*,*::before,*::after{caret-color:transparent!important;animation:none!important;transition:none!important;scroll-behavior:auto!important}"


def _templates_states(browser, url, shot) -> None:
    """The Templates view: empty, the field matching, the review panel, and making a template from the open
    workbook (WP9). The last one needs a workbook open on the server, which `capture` has done by then."""
    import csv
    import tempfile

    from py_tbparse import load_template, make_template

    fixtures = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "public"
    with tempfile.TemporaryDirectory() as tmp:
        tpl = make_template(str(fixtures / "filtering.twb"), output_path=str(Path(tmp) / "filtering.template.twbx"),
                            template_id="screenshot-template")
        entry = next(e for e in load_template(tpl).manifest["datasources"] if e["fields"])
        data = Path(tmp) / "new-data.csv"
        with open(data, "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            names = [f["remote"] for f in entry["fields"] if f["name"] != "[Burst Out Set list]"] + ["Burst Out Set"]
            w.writerow(names)
            w.writerow(["x"] * len(names))
        page = browser.new_page(viewport={"width": 1360, "height": 900}, color_scheme="light")
        page.goto(url + "/#templates")
        page.wait_for_selector("#templatesView:not([hidden])")
        shot(page, "08-templates-empty.png")
        page.set_input_files("#tplTemplatePick", str(tpl))
        page.wait_for_selector("#tplCard1[data-state=done]")
        page.set_input_files("#tplDataPick", str(data))
        page.wait_for_selector("#tplMapBody tr")
        time.sleep(1.0)
        page.locator("#tplCard3").scroll_into_view_if_needed()
        shot(page, "09-templates-mapping.png")
        page.locator("#tplGroup-explain summary").click()
        page.locator("#tplPlanTitle").scroll_into_view_if_needed()
        time.sleep(0.4)
        shot(page, "10-templates-review.png")
        page.close()
        page = browser.new_page(viewport={"width": 1360, "height": 900}, color_scheme="light")
        page.goto(url + "/#templates")
        page.wait_for_selector("#tplMakeBtn")
        page.click("#tplMakeBtn")
        page.wait_for_selector("#tplMadeUse")
        page.click("#status")   # the toast hides on a click, so it does not cover the card
        page.evaluate("() => document.getElementById('tplMakeTitle').scrollIntoView()")
        time.sleep(0.4)
        shot(page, "11-templates-make.png")
        page.close()


def _wait_settled(page) -> None:
    """The tests' `wait_settled` (tests/test_gui_browser.py): wait until nothing is animating any more."""
    sys.path.insert(0, str(ROOT / "tests"))
    try:
        from test_gui_browser import wait_settled
    except ImportError:   # pytest or Playwright test helpers missing: a fixed pause is the best we can do
        time.sleep(1.0)
    else:
        wait_settled(page)
    finally:
        sys.path.pop(0)


_STYLES_TPS = """<?xml version='1.0'?>
<workbook><preferences>
<color-palette name="Screenshot Brand" type="regular"><color>#1F4E79</color><color>#2E86AB</color><color>#F18F01</color></color-palette>
</preferences></workbook>
"""


def _newer_views(browser, url, workbook, shot) -> None:
    """Audit, Libraries, Styles and Slice and copy, in light, dark and at 390 px (files 12 to 23). Each view is
    opened on the given workbook, a few rows are ticked or a small file is dropped so the view shows more than its
    empty state, and the tables stay at a handful of rows."""
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        tps = Path(tmp) / "brand.tps"
        tps.write_text(_STYLES_TPS, encoding="utf-8")

        def go(page, table):
            nav = page.locator(f'.nav-item[data-table="{table}"]')
            if nav.is_visible():
                nav.click()
            else:   # at phone width the sidebar is hidden and a menu takes its place
                page.select_option("#tableSel", table)
            page.wait_for_selector("#tableWrap > *", timeout=10000)
            _wait_settled(page)

        def audit(page):
            go(page, "audit")

        def libraries(page):
            go(page, "libraries")
            if page.locator("#libRow0").count():
                page.check("#libRow0")
            _wait_settled(page)

        def styles(page):
            go(page, "styles")
            page.set_input_files("#styFile", str(tps))
            page.wait_for_selector("#styPlanBox", timeout=15000)
            page.locator("#styPlanBox").scroll_into_view_if_needed()   # the plan, not the empty palette list
            _wait_settled(page)

        def copy(page):
            go(page, "copy")
            if page.locator("#cpyDashRow0").count():
                page.check("#cpyDashRow0")
                page.wait_for_selector("#cpySliceSummary", timeout=15000)
            _wait_settled(page)

        # Libraries needs a workbook with exactly one datasource, so it uses a small public fixture; the others
        # use the workbook given on the command line.
        single = str(ROOT / "tests" / "fixtures" / "public" / "filtering.twb")
        views = (("audit", audit, workbook), ("libraries", libraries, single), ("styles", styles, workbook),
                 ("slice-copy", copy, workbook))
        number = 12
        for view, drive, source in views:
            for suffix, scheme, width in (("light", "light", 1360), ("dark", "dark", 1360), ("phone", "light", 390)):
                page = browser.new_page(viewport={"width": width, "height": 800}, color_scheme=scheme)
                page.goto(url)
                page.fill("#path", source)
                page.click("#loadBtn")
                page.wait_for_selector("#tableWrap .health, #tableWrap table", timeout=20000)
                _wait_settled(page)
                drive(page)
                shot(page, f"{number}-{view}-{suffix}.png")
                number += 1
                page.close()


def capture(workbook: str, out: Path) -> list[str]:
    from playwright.sync_api import sync_playwright

    from py_tbparse import webgui

    out.mkdir(parents=True, exist_ok=True)
    env = _setup_env()
    srv = ThreadingHTTPServer(("127.0.0.1", 0), webgui.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = "http://%s:%d" % srv.server_address
    webgui.__version__ = "0.0.0"  # a fixed string, so a version bump never changes a screenshot
    names: list[str] = []

    def shot(page, name):
        page.add_style_tag(content=_FREEZE)
        page.evaluate("() => { const t = document.getElementById('status'); if (t) t.classList.remove('show'); }")
        page.evaluate("() => document.activeElement && document.activeElement.blur && document.activeElement.blur()")
        page.screenshot(path=str(out / name))
        names.append(name)

    def open_view(page, view):
        sel = f'[data-table="{view}"]'
        if page.locator(sel).count() and page.locator(sel).is_visible():
            page.click(sel)
        else:
            page.select_option("#tableSel", view)
        time.sleep(0.8)

    def load(page):
        page.fill("#path", workbook)
        page.click("#loadBtn")
        time.sleep(1.6)

    with sync_playwright() as pw:
        browser = pw.chromium.launch(env=env)
        for scheme in ("light", "dark"):
            page = browser.new_page(viewport={"width": 1360, "height": 800}, color_scheme=scheme)
            page.goto(url)
            time.sleep(0.4)
            if scheme == "light":
                shot(page, "01-start.png")
            load(page)
            shot(page, f"02-overview-{scheme}.png")
            open_view(page, "fields")
            shot(page, "03-fields.png" if scheme == "light" else "03-fields-dark.png")
            if scheme == "light":
                open_view(page, "field-renames")
                shot(page, "04-field-renames.png")
                open_view(page, "graph")
                shot(page, "05-graph.png")
            page.close()
        page = browser.new_page(viewport={"width": 390, "height": 800}, color_scheme="light")
        page.goto(url)
        load(page)
        shot(page, "06-phone-overview.png")
        open_view(page, "fields")
        shot(page, "07-phone-fields.png")
        page.close()
        _templates_states(browser, url, shot)
        _newer_views(browser, url, workbook, shot)
        browser.close()
    srv.shutdown()
    return names


def compare(new: Path, baseline: Path) -> int:
    try:
        from PIL import Image, ImageChops
    except ImportError:
        Image = None
    different = 0
    for base in sorted(baseline.glob("*.png")):
        cur = new / base.name
        if not cur.exists():
            print("MISSING  ", base.name)
            different += 1
            continue
        a, b = base.read_bytes(), cur.read_bytes()
        if hashlib.sha256(a).digest() == hashlib.sha256(b).digest():
            print("identical", base.name)
            continue
        if Image is not None:
            ia, ib = Image.open(base).convert("RGB"), Image.open(cur).convert("RGB")
            if ia.size == ib.size and ImageChops.difference(ia, ib).getbbox() is None:
                print("identical (same pixels)", base.name)
                continue
        print("DIFFERENT", base.name)
        different += 1
    print(f"{different} different")
    return 1 if different else 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("workbook")
    ap.add_argument("out_dir")
    ap.add_argument("--compare", metavar="BASELINE_DIR", help="compare the new captures with these")
    args = ap.parse_args()
    names = capture(os.path.abspath(args.workbook), Path(args.out_dir))
    print(f"captured {len(names)} screenshots in {args.out_dir}")
    return compare(Path(args.out_dir), Path(args.compare)) if args.compare else 0


if __name__ == "__main__":
    sys.exit(main())
