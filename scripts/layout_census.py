#!/usr/bin/env python3
"""Census of dashboard layouts in the example-workbook corpus (WP0 of docs/plan-84-layout-preview.md).

    nice -n 10 ionice -c3 timeout 900 python scripts/layout_census.py [--files DIR] [--cap N] [--timeout S]
                                                                       [--stop-file PATH] [--log PATH]

Reads every .twb/.twbx in tests/corpus/files (fetch with scripts/fetch_corpus.py), one file in memory at a
time, one worker, and prints aggregate Markdown tables for the main layout of each dashboard: zones per
dashboard, missing or odd sizes, positions outside Tableau's 0 to 100000 grid, overlapping leaf zones
(split by floating and not), nesting depth, leaves that stick out of their container, the extent against the
grid and against a fixed dashboard size, and how small zones get at 500 px wide.

Only counts are printed. No workbook name, sheet name, dashboard name or zone text ever reaches the output or
the log; failures are listed by number. Read-only.

Limits: a per-file timeout (--timeout, Unix only), files over --max-mb (default 20) are skipped (zip members
too), --cap N stops after N files, creating the file given by --stop-file ends the run after the current file,
the run pauses while free memory or the load average is tight and stops when its own memory or the free disk
space of the log folder gets too low. Peak memory and the highest load seen are reported at the end.
"""
from __future__ import annotations

import argparse
import collections
import os
import signal
import sys
import time
import zipfile
from pathlib import Path

from lxml import etree

ROOT = Path(__file__).resolve().parent.parent
GRID = 100000
SCREEN_PX = 500            # width of the planned drawing
NAME_MIN_PX = 40           # a zone narrower than this would get a letter instead of a name (plan, "Phone layout")
CONTAINERS = ("layout-basic", "layout-flow")
BUCKETS = (1, 2, 5, 10, 20, 40, 100, 200)
FLOAT_ATTRS = ("is-floating", "floating")
LN = lambda e: etree.QName(e).localname if isinstance(e.tag, str) else ""


class Skip(Exception):
    pass


def zone_kind(z) -> str:
    """Same reading as py_tbparse.dashboards.zone_kind for the cases that matter here (type-v2, type, sheet)."""
    kind = z.get("type-v2") or z.get("type")
    if kind == "worksheet":
        return "sheet"
    return kind or ("sheet" if (z.get("name") or z.get("worksheet")) else "unknown")


def _int(z, attr):
    try:
        return int(z.get(attr))
    except (TypeError, ValueError):
        return None


def _rect(z):
    v = [_int(z, a) for a in ("x", "y", "w", "h")]
    return None if None in v else tuple(v)


def is_floating(z) -> bool:
    return any((z.get(a) or "").lower() == "true" for a in FLOAT_ATTRS)


def overlap_area(a, b) -> int:
    w = min(a[0] + a[2], b[0] + b[2]) - max(a[0], b[0])
    h = min(a[1] + a[3], b[1] + b[3]) - max(a[1], b[1])
    return w * h if w > 0 and h > 0 else 0


def contains(a, b) -> bool:
    return a[0] <= b[0] and a[1] <= b[1] and a[0] + a[2] >= b[0] + b[2] and a[1] + a[3] >= b[1] + b[3]


def analyse_dashboard(db, min_overlap: float = 0.01) -> dict:
    """Numbers for one `<dashboard>` element, main layout only (`./zones//zone`, device layouts are separate).

    A pair of leaf zones overlaps when the shared area is more than `min_overlap` of the smaller one's area.
    A leaf is `floating` when it carries an explicit floating attribute; `in a basic container` when its parent
    is a `layout-basic` container that is not the root zone, which is where Tableau keeps free-placed items (a
    proxy, since the corpus has no explicit floating attribute at all)."""
    zones = db.xpath("./zones//zone")
    r = collections.Counter()
    leaves = []
    max_depth = 0
    for z in zones:
        depth = len(z.xpath("ancestor::zone")) + 1
        max_depth = max(max_depth, depth)
        has_children = z.find("zone") is not None
        if has_children or zone_kind(z) in CONTAINERS:
            r["containers"] += 1
            continue
        rect = _rect(z)
        parent = z.getparent()
        parent_rect = _rect(parent) if parent is not None and LN(parent) == "zone" else None
        grandparent = parent.getparent() if parent is not None else None
        in_basic = (parent is not None and LN(parent) == "zone" and zone_kind(parent) == "layout-basic"
                    and grandparent is not None and LN(grandparent) == "zone")
        leaves.append((z, rect, is_floating(z), in_basic, parent_rect))
    r["zones"] = len(zones)
    r["leaves"] = len(leaves)
    r["max_depth"] = max_depth
    r["floating_attr"] = sum(1 for lf in leaves if lf[2])
    r["in_basic"] = sum(1 for lf in leaves if lf[3])

    placed = []
    max_x = max_y = 0
    min_w_px = None
    for z, rect, fl, basic, prect in leaves:
        if rect is None:
            r["missing_pos"] += 1
            continue
        x, y, w, h = rect
        if w <= 0 or h <= 0:
            r["nonpositive_size"] += 1
            continue
        placed.append((rect, fl, basic, zone_kind(z)))
        if x < 0 or y < 0:
            r["negative_pos"] += 1
        if x > GRID or y > GRID:
            r["pos_past_grid"] += 1
        if x + w > GRID or y + h > GRID:
            r["extent_past_grid"] += 1
        max_x, max_y = max(max_x, x + w), max(max_y, y + h)
        px = w / GRID * SCREEN_PX
        min_w_px = px if min_w_px is None else min(min_w_px, px)
        r["leaves_under_name_width"] += px < NAME_MIN_PX
        r["leaves_under_5px"] += px < 5
        if prect is not None and prect[2] > 0 and prect[3] > 0:
            px_, py_, pw, ph = prect
            if x < px_ or y < py_ or x + w > px_ + pw or y + h > py_ + ph:
                r["outside_parent"] += 1
    r["placed"] = len(placed)
    r["max_x"], r["max_y"] = max_x, max_y

    order = sorted(range(len(placed)), key=lambda i: placed[i][0][0])
    for ai, i in enumerate(order):
        a, afl, abasic, akind = placed[i]
        for j in order[ai + 1:]:
            b, bfl, bbasic, bkind = placed[j]
            if b[0] >= a[0] + a[2]:
                break
            area = overlap_area(a, b)
            if area and area > min_overlap * min(a[2] * a[3], b[2] * b[3]):
                r["overlap_pairs"] += 1
                if afl or bfl:
                    r["overlap_floating_attr"] += 1
                elif abasic or bbasic:
                    r["overlap_basic_container"] += 1
                else:
                    r["overlap_neither"] += 1
                if a == b:
                    r["overlap_identical"] += 1
                elif contains(a, b) or contains(b, a):
                    r["overlap_nested"] += 1
                else:
                    r["overlap_partial"] += 1
                if "text" in (akind, bkind) or "bitmap" in (akind, bkind):
                    r["overlap_with_text_or_image"] += 1
    size = db.find("size")
    fixed = None
    if size is not None:
        vals = [size.get(k) for k in ("minwidth", "minheight", "maxwidth", "maxheight")]
        if None not in vals and vals[0] == vals[2] and vals[1] == vals[3]:
            try:
                fixed = (int(vals[0]), int(vals[1]))
            except ValueError:
                fixed = None
    r["_fixed"] = fixed
    r["_min_w_px"] = min_w_px
    return dict(r)


def load_root(path: Path, max_bytes: int):
    if path.stat().st_size > max_bytes:
        raise Skip("over size limit")
    if path.suffix == ".twbx":
        with zipfile.ZipFile(path) as z:
            member = next((i for i in z.infolist() if i.filename.endswith(".twb")), None)
            if member is None:
                raise Skip("no .twb inside")
            if member.file_size > max_bytes:
                raise Skip("over size limit")
            data = z.read(member)
    else:
        data = path.read_bytes()
    return etree.fromstring(data, etree.XMLParser(recover=True, resolve_entities=False, no_network=True))


class Timeout(Exception):
    pass


def _alarm(signum, frame):
    raise Timeout()


def analyse_file(path: Path, max_bytes: int, timeout: float, min_overlap: float) -> list[dict]:
    use_alarm = hasattr(signal, "setitimer")
    if use_alarm:
        signal.signal(signal.SIGALRM, _alarm)
        signal.setitimer(signal.ITIMER_REAL, timeout)
    try:
        root = load_root(path, max_bytes)
        return [analyse_dashboard(db, min_overlap) for db in root.xpath("//dashboards/dashboard")]
    finally:
        if use_alarm:
            signal.setitimer(signal.ITIMER_REAL, 0)


# ---- the machine watchdog (Linux; each check is skipped where /proc is missing) ----

def mem_available_mb():
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            if line.startswith("MemAvailable:"):
                return int(line.split()[1]) // 1024
    except OSError:
        pass
    return None


def own_rss_mb():
    try:
        for line in Path("/proc/self/status").read_text().splitlines():
            if line.startswith("VmRSS:"):
                return int(line.split()[1]) // 1024
    except OSError:
        pass
    return None


def load1():
    try:
        return os.getloadavg()[0]
    except (OSError, AttributeError):
        return None


def peak_rss_mb():
    try:
        import resource
        return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss // 1024
    except ImportError:
        return None


def bucket(n: int) -> str:
    lo = 0
    for b in BUCKETS:
        if n <= b:
            return f"{lo + 1}-{b}" if b > lo + 1 else f"{b}"
        lo = b
    return f"over {BUCKETS[-1]}"


def bucket_order():
    lo, out = 0, []
    for b in BUCKETS:
        out.append(f"{lo + 1}-{b}" if b > lo + 1 else f"{b}")
        lo = b
    return ["0"] + out + [f"over {BUCKETS[-1]}"]


def table(title, head, rows, out):
    out.append(f"\n### {title}\n")
    out.append("| " + " | ".join(head) + " |")
    out.append("|" + "---|" * len(head))
    for r in rows:
        out.append("| " + " | ".join(str(c) for c in r) + " |")


def pct(n, d):
    return f"{100 * n / d:.1f}%" if d else "-"


def summarise(dashes: list[dict], meta: dict) -> str:
    """Markdown for the list of per-dashboard results."""
    out: list[str] = []
    n = len(dashes)
    g = lambda d, k: d.get(k, 0)
    s = lambda k: sum(g(d, k) for d in dashes)
    out.append("## Layout census\n")
    table("Files and dashboards", ["", "count"], [
        ("workbooks read", meta["read"]), ("skipped: over size limit", meta["too_big"]),
        ("skipped: unreadable or timed out", meta["failed"]), ("with no dashboards", meta["no_dashboards"]),
        ("dashboards", n), ("dashboards with no leaf zones at all", sum(1 for d in dashes if not g(d, "leaves"))),
    ], out)
    cnt = collections.Counter(bucket(g(d, "leaves")) if g(d, "leaves") else "0" for d in dashes)
    table("Leaf zones per dashboard (containers not counted)", ["leaf zones", "dashboards"],
          [(b, cnt[b]) for b in bucket_order() if cnt[b]], out)
    leaves = sorted(g(d, "leaves") for d in dashes)
    if leaves:
        table("Leaf zones: summary", ["", "value"], [
            ("maximum", leaves[-1]), ("median", leaves[len(leaves) // 2]), ("total", sum(leaves)),
            ("dashboards over 40 (the card sketch cap)", sum(1 for v in leaves if v > 40)),
            ("dashboards over 200 (the preview cap)", sum(1 for v in leaves if v > 200)),
            ("zones (containers included), maximum on one dashboard", max(g(d, "zones") for d in dashes)),
        ], out)

    def row(label, key):
        k = sum(1 for d in dashes if g(d, key))
        return (label, s(key), k, pct(k, n))
    table("Odd sizes and positions (leaf zones; all counted separately)", ["case", "zones", "dashboards", "of dashboards"], [
        row("no full x, y, w, h", "missing_pos"), row("w or h zero or negative", "nonpositive_size"),
        row("x or y negative", "negative_pos"), row("x or y past 100000", "pos_past_grid"),
        row("x+w or y+h past 100000", "extent_past_grid"),
        row("sticks out of its parent container's rectangle", "outside_parent"),
    ], out)
    table("Overlap (pairs of placed leaf zones sharing more than "
          f"{meta['min_overlap']:.0%} of the smaller one)", ["pairs where", "pairs", "dashboards", "of dashboards"], [
        row("any (total)", "overlap_pairs"),
        row("one zone has an explicit floating attribute", "overlap_floating_attr"),
        row("no floating attribute, one zone sits in a non-root layout-basic container", "overlap_basic_container"),
        row("neither", "overlap_neither"),
    ], out)
    table("Shape of the overlap (same pairs, split another way)", ["pairs where", "pairs", "dashboards", "of dashboards"], [
        row("the two rectangles are identical", "overlap_identical"),
        row("one rectangle lies completely inside the other", "overlap_nested"),
        row("they cross each other only partly", "overlap_partial"),
        row("one of the two is a text or image zone", "overlap_with_text_or_image"),
    ], out)
    table("Floating and nesting", ["", "value"], [
        ("leaf zones with an explicit floating attribute (is-floating, floating)", s("floating_attr")),
        ("leaf zones directly in a non-root layout-basic container", s("in_basic")),
        ("nesting depth: maximum", max((g(d, "max_depth") for d in dashes), default=0)),
        ("nesting depth: median", sorted(g(d, "max_depth") for d in dashes)[n // 2] if n else 0),
        ("dashboards nested deeper than 6", sum(1 for d in dashes if g(d, "max_depth") > 6)),
        ("containers in total", s("containers")),
    ], out)
    fixed = [d for d in dashes if d.get("_fixed")]
    wide = sum(1 for d in dashes if g(d, "max_x") > GRID or g(d, "max_y") > GRID)
    short = sum(1 for d in dashes if d.get("placed") and (g(d, "max_x") < 0.99 * GRID or g(d, "max_y") < 0.99 * GRID))
    table("Extent against the grid and the dashboard size", ["", "dashboards"], [
        ("with placed zones", sum(1 for d in dashes if g(d, "placed"))),
        ("extent past 100000 in x or y", wide),
        ("extent under 99% of 100000 in x or y (drawing would not fill a square-grid frame)", short),
        ("with a fixed pixel size (min equals max)", len(fixed)),
        ("fixed size and extent past 100000 (positions may be pixels)", sum(1 for d in fixed if g(d, "max_x") > GRID or g(d, "max_y") > GRID)),
    ], out)
    placed = s("placed")
    table(f"Smallest zones at {SCREEN_PX} px wide", ["", "zones", "of placed leaves"], [
        (f"narrower than {NAME_MIN_PX} px (letter instead of a name)", s("leaves_under_name_width"),
         pct(s("leaves_under_name_width"), placed)),
        ("narrower than 5 px (nothing readable)", s("leaves_under_5px"), pct(s("leaves_under_5px"), placed)),
        ("dashboards with at least one zone narrower than 40 px",
         sum(1 for d in dashes if g(d, "leaves_under_name_width")), pct(sum(1 for d in dashes if g(d, "leaves_under_name_width")), n)),
    ], out)
    widths = sorted(d["_min_w_px"] for d in dashes if d.get("_min_w_px") is not None)
    if widths:
        out.append(f"\nNarrowest zone per dashboard, px at {SCREEN_PX}: minimum {widths[0]:.2f}, "
                   f"median {widths[len(widths) // 2]:.2f}, maximum {widths[-1]:.2f}.")
    return "\n".join(out)


def run(files: list[Path], *, cap: int | None = None, timeout: float = 20, max_mb: int = 20,
        min_overlap: float = 0.01, stop_file: Path | None = None, log=None, min_free_mb: int = 1500,
        max_rss_mb: int = 1200, max_load: float = 3.5, log_dir: Path | None = None, delay: float = 0.0):
    """Analyse `files` (at most `cap`) and return (per-dashboard results, meta). Stops early on the stop file,
    on low disk space or on the process using too much memory; waits (up to 10 min per check) while the machine
    is busy."""
    meta = collections.Counter(min_overlap=min_overlap, peak_load=0.0, peak_rss=0, stopped="")
    dashes: list[dict] = []
    say = log or (lambda msg: None)
    for i, path in enumerate(files):
        if cap is not None and i >= cap:
            meta["stopped"] = f"cap of {cap} files"
            break
        if stop_file is not None and stop_file.exists():
            meta["stopped"] = "stop file"
            break
        if log_dir is not None and os.statvfs(log_dir).f_bavail * os.statvfs(log_dir).f_frsize < 200 * 2**20:
            meta["stopped"] = "disk space low"
            break
        waited = 0
        while waited < 600:
            avail, ld = mem_available_mb(), load1()
            if (avail is None or avail >= min_free_mb) and (ld is None or ld <= max_load):
                break
            time.sleep(5)
            waited += 5
        else:
            meta["stopped"] = "machine stayed busy"
            break
        ld = load1()
        meta["peak_load"] = max(meta["peak_load"], ld or 0.0)
        rss = own_rss_mb()
        if rss is not None and rss > max_rss_mb:
            meta["stopped"] = f"memory over {max_rss_mb} MB"
            break
        try:
            found = analyse_file(path, max_mb * 2**20, timeout, min_overlap)
        except Skip:
            meta["too_big"] += 1
            say(f"file {i + 1}: skipped (size or content)")
            continue
        except Timeout:
            meta["failed"] += 1
            say(f"file {i + 1}: timed out")
            continue
        except Exception as exc:  # noqa: BLE001
            meta["failed"] += 1
            say(f"file {i + 1}: failed ({type(exc).__name__})")
            continue
        meta["read"] += 1
        if not found:
            meta["no_dashboards"] += 1
        dashes.extend(found)
        if (i + 1) % 25 == 0:
            say(f"{i + 1} files, {len(dashes)} dashboards, rss {own_rss_mb()} MB, load {ld}")
        if delay:
            time.sleep(delay)
    meta["peak_rss"] = peak_rss_mb() or 0
    return dashes, meta


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--files", default=str(ROOT / "tests/corpus/files"))
    ap.add_argument("--cap", type=int, default=None, help="read at most this many files")
    ap.add_argument("--timeout", type=float, default=20, help="seconds per file (Unix)")
    ap.add_argument("--max-mb", type=int, default=20, help="skip files larger than this")
    ap.add_argument("--min-overlap", type=float, default=0.01, help="share of the smaller zone that counts as overlap")
    ap.add_argument("--stop-file", default=None, help="the run ends after the current file once this path exists")
    ap.add_argument("--log", default=None, help="append progress lines (counts only) to this file")
    ap.add_argument("--delay", type=float, default=0.05, help="pause between files, seconds")
    args = ap.parse_args(argv)
    files = sorted(p for p in Path(args.files).iterdir() if p.suffix in (".twb", ".twbx"))
    if not files:
        sys.exit("no workbooks; run scripts/fetch_corpus.py")
    logf = open(args.log, "a", encoding="utf-8") if args.log else None

    def log(msg):
        if logf:
            logf.write(time.strftime("%H:%M:%S ") + msg + "\n")
            logf.flush()

    log(f"start: {len(files)} files, cap {args.cap}, load {load1()}, mem available {mem_available_mb()} MB")
    dashes, meta = run(files, cap=args.cap, timeout=args.timeout, max_mb=args.max_mb, min_overlap=args.min_overlap,
                       stop_file=Path(args.stop_file) if args.stop_file else None, log=log, delay=args.delay,
                       log_dir=Path(args.log).parent if args.log else None)
    print(summarise(dashes, meta))
    tail = (f"\nRun: peak memory {meta['peak_rss']} MB, highest load seen at file starts {meta['peak_load']:.2f}"
            + (f", stopped early: {meta['stopped']}" if meta["stopped"] else "") + ".")
    print(tail)
    log("done" + tail.replace("\n", " "))
    return 0


if __name__ == "__main__":
    sys.exit(main())
