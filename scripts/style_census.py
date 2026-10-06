#!/usr/bin/env python3
"""Census of where style lives in the example-workbook corpus (WP7 phase 0).

    nice -n 10 timeout 300 python scripts/style_census.py [--files DIR] [--examples]

Reads every .twb/.twbx in tests/corpus/files (fetch with scripts/fetch_corpus.py), counts the
style-bearing elements per scope and prints Markdown tables. Read-only, one file in memory at a
time, stdlib + lxml. Results feed docs/style-model.md.
"""
from __future__ import annotations

import argparse
import collections
import re
import sys
import zipfile
from pathlib import Path

from lxml import etree

ROOT = Path(__file__).resolve().parent.parent
LN = lambda e: etree.QName(e).localname if isinstance(e.tag, str) else ""
HEX = re.compile(r"^#[0-9a-fA-F]{6}")


def load(path: Path):
    data = path.read_bytes()
    if path.suffix == ".twbx":
        with zipfile.ZipFile(path) as z:
            data = z.read(next(n for n in z.namelist() if n.endswith(".twb")))
    return etree.fromstring(data, etree.XMLParser(recover=True, resolve_entities=False, no_network=True))


def ancestors(e):
    a = e.getparent()
    while a is not None:
        yield LN(a)
        a = a.getparent()


def scope_of(style_rule):
    """Where a <style-rule> lives: workbook / datasource / sheet / pane / dashboard."""
    anc = list(ancestors(style_rule))
    if "pane" in anc:
        return "sheet pane"
    if "table" in anc and "worksheet" in anc:
        return "sheet table"
    if "dashboard" in anc:
        return "dashboard"
    if "datasource" in anc:
        return "datasource"
    if "worksheet" in anc:
        return "sheet (direct)"
    return "workbook"


class Tab:
    """Counter that also remembers which workbooks hit each key."""
    def __init__(self):
        self.n = collections.Counter()
        self.w = collections.defaultdict(set)
        self.ex = {}

    def add(self, key, wb, el=None):
        self.n[key] += 1
        self.w[key].add(wb)
        if el is not None and key not in self.ex:
            self.ex[key] = el

    def rows(self, top=None):
        for k, v in sorted(self.n.items(), key=lambda x: (-len(self.w[x[0]]), -x[1], str(x[0])))[:top]:
            yield k, v, len(self.w[k])


def table(title, head, rows):
    print(f"\n### {title}\n")
    print("| " + " | ".join(head) + " |")
    print("|" + "---|" * len(head))
    for r in rows:
        print("| " + " | ".join(str(c) for c in r) + " |")


def snippet(el, limit=420):
    el = etree.fromstring(etree.tostring(el))
    for e in el.iter():
        if isinstance(e.tag, str):
            e.tail = None
    s = etree.tostring(el).decode()
    s = re.sub(r" xmlns:\w+=\"[^\"]*\"", "", s)
    s = re.sub(r">\s+<", "><", s)
    return s if len(s) <= limit else s[:limit] + "..."


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--files", default=str(ROOT / "tests/corpus/files"))
    ap.add_argument("--examples", action="store_true", help="print one short XML example per element")
    args = ap.parse_args()
    files = sorted(p for p in Path(args.files).iterdir() if p.suffix in (".twb", ".twbx"))
    if not files:
        sys.exit("no workbooks; run scripts/fetch_corpus.py")

    tot = collections.Counter()
    rules = Tab()          # (scope, element)
    fmt_attr = Tab()       # (scope, attr)
    name_ref = Tab()       # (scope, kind)
    palettes = Tab()       # (where, type, custom)
    pal_names = Tab()
    pal_sizes = collections.Counter()
    pal_ref = Tab()
    prefs = Tab()
    zone_fmt = Tab()       # (zone kind, attr)
    zone_kinds = Tab()
    fonts = Tab()          # (scope, family)
    sizes = Tab()          # (scope, size)
    runs = Tab()
    misc = Tab()
    examples = {}

    for path in files:
        wb = path.name
        try:
            root = load(path)
        except Exception as exc:  # noqa: BLE001
            print(f"skip {wb}: {exc}", file=sys.stderr)
            continue
        tot["workbooks"] += 1
        sheets = root.findall(".//worksheets/worksheet")
        tot["worksheets"] += len(sheets)
        for s in sheets:
            st = s.find("table/style")
            if st is not None and st.find("style-rule") is not None:
                tot["worksheets with explicit table/style rules"] += 1
            if any(p.find("style/style-rule") is not None for p in s.findall("table/panes/pane")):
                tot["worksheets with explicit pane style rules"] += 1
        dashes = root.findall(".//dashboards/dashboard")
        tot["dashboards"] += len(dashes)
        for d in dashes:
            if d.find("style/style-rule") is not None:
                tot["dashboards with dashboard-level style-rule"] += 1
            if d.find(".//zone-style") is not None:
                tot["dashboards with any zone-style"] += 1
        tot["datasources"] += len(root.findall("datasources/datasource"))

        for e in root.iter():
            tag = LN(e)
            if not tag:
                continue
            if tag == "style-rule":
                sc, el = scope_of(e), e.get("element", "?")
                rules.add((sc, el), wb, e)
                for ch in e:
                    c = LN(ch)
                    if c == "format":
                        fmt_attr.add((sc, ch.get("attr")), wb, ch)
                        if ch.get("field") or ch.get("scope") or ch.get("ref"):
                            name_ref.add((sc, "format with field/scope/ref"), wb, ch)
                        v = ch.get("value", "")
                        if ch.get("attr") == "font-family":
                            fonts.add((sc, v), wb)
                        if ch.get("attr") == "font-size":
                            sizes.add((sc, v), wb)
                    elif c == "encoding":
                        kind = f"encoding attr={ch.get('attr')} type={ch.get('type')}"
                        name_ref.add((sc, kind), wb, ch)
                        if ch.get("palette"):
                            pal_ref.add(ch.get("palette"), wb, ch)
                        if ch.find("map") is not None:
                            name_ref.add((sc, "encoding with <map>/<bucket> data values"), wb, ch)
            elif tag == "color-palette":
                where = LN(e.getparent())
                n = len(e.findall("color"))
                palettes.add((where, e.get("type"), e.get("custom")), wb, e)
                pal_names.add((where, e.get("name")), wb)
                pal_sizes[n] += 1
            elif tag == "preference" and LN(e.getparent()) == "preferences":
                prefs.add(e.get("name"), wb, e)
            elif tag == "zone-style":
                z = e.getparent()
                kind = z.get("type-v2") or z.get("type") or ("leaf-sheet" if z.get("name") else "other")
                zone_kinds.add(kind, wb, z)
                for f in e.findall("format"):
                    zone_fmt.add((kind, f.get("attr")), wb, f)
                    if f.get("attr") == "font-family":
                        fonts.add(("zone-style", f.get("value")), wb)
            elif tag == "run":
                if e.get("fontname"):
                    fonts.add(("formatted-text run", e.get("fontname")), wb)
                if e.get("fontsize"):
                    sizes.add(("formatted-text run", e.get("fontsize")), wb)
                runs.add(("run", "bold/italic/fontcolor"), wb) if any(e.get(k) for k in ("bold", "italic", "fontcolor")) else None
            elif tag == "style-theme":
                misc.add(("style-theme", e.get("name")), wb, e)
            elif tag == "devicelayout":
                misc.add(("devicelayout", e.get("name")), wb, e)
                if e.get("auto-generated") == "true":
                    misc.add(("devicelayout", "auto-generated=true"), wb)
            elif tag == "device-preview":
                misc.add(("device-preview (window)", "-"), wb, e)
            elif tag == "document-format-change-manifest":
                misc.add(("document-format-change-manifest", "-"), wb, e)
            elif tag == "column" and e.get("default-format"):
                misc.add(("datasource column@default-format", "-"), wb, e)
            elif tag == "layout-options" and LN(e.getparent()) in ("worksheet", "dashboard", "devicelayout"):
                misc.add(("layout-options", LN(e.getparent())), wb, e)
                if e.find("title") is not None:
                    misc.add(("layout-options/title", LN(e.getparent())), wb)
            elif tag == "zone" and (e.get("type-v2") or e.get("type")) in ("bitmap", "image", "title"):
                misc.add(("zone", e.get("type-v2") or e.get("type")), wb, e)
            elif tag == "image" and LN(e.getparent()) in ("zone",):
                misc.add(("zone image", "-"), wb, e)
            elif tag == "size" and LN(e.getparent()) == "dashboard":
                misc.add(("dashboard size", e.get("sizing-mode") or "?"), wb, e)
            if tag in ("style-rule", "color-palette", "zone-style", "style-theme", "devicelayout", "preferences") and tag not in examples:
                examples[tag] = e

    W = tot["workbooks"]
    print(f"# Style census\n\n{W} workbooks, scanned from `{args.files}`.\n")
    table("Totals", ["what", "count"], tot.items())
    table("style-rule by scope and element (workbooks = how many workbooks have at least one)",
          ["scope", "element", "count", "workbooks"], [(k[0], k[1], n, w) for k, n, w in rules.rows()])
    table("format attributes under style-rule (top 60)", ["scope", "attr", "count", "workbooks"],
          [(k[0], k[1], n, w) for k, n, w in fmt_attr.rows(60)])
    table("style-rule children that reference names or data", ["scope", "kind", "count", "workbooks"],
          [(k[0], k[1], n, w) for k, n, w in name_ref.rows()])
    table("color-palette elements", ["parent", "type", "custom", "count", "workbooks"],
          [(*k, n, w) for k, n, w in palettes.rows()])
    table("palette names", ["parent", "name", "count", "workbooks"], [(*k, n, w) for k, n, w in pal_names.rows(25)])
    table("colours per palette", ["colours", "palettes"], sorted(pal_sizes.items()))
    table("encoding palette= references", ["palette value", "count", "workbooks"], [(k, n, w) for k, n, w in pal_ref.rows(25)])
    table("<preferences> entries", ["name", "count", "workbooks"], [(k, n, w) for k, n, w in prefs.rows(25)])
    table("zone-style by zone kind", ["zone kind", "zones", "workbooks"], [(k, n, w) for k, n, w in zone_kinds.rows()])
    table("zone-style format attrs", ["zone kind", "attr", "count", "workbooks"], [(*k, n, w) for k, n, w in zone_fmt.rows(40)])
    table("font families", ["scope", "family", "count", "workbooks"], [(*k, n, w) for k, n, w in fonts.rows(40)])
    table("font sizes", ["scope", "size", "count", "workbooks"], [(*k, n, w) for k, n, w in sizes.rows(30)])
    table("misc", ["element", "detail", "count", "workbooks"], [(*k, n, w) for k, n, w in misc.rows()])

    if args.examples:
        print("\n### Examples\n")
        for k, el in examples.items():
            print(f"- `{k}`: `{snippet(el)}`")
        for tab in (rules, name_ref, zone_fmt, misc):
            for k, el in list(tab.ex.items())[:0]:
                pass


if __name__ == "__main__":
    main()
