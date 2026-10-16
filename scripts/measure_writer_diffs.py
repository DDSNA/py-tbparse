"""How much of a workbook does each py-tbparse writer rewrite? (WP8 measurement, no design.)

For every workbook (the corpus in tests/corpus/files plus the committed demo and fixture workbooks) and for every
writer that rewrites a workbook, run the writer with inputs made from the workbook itself (no hand-made files),
then compare the output's workbook XML with the input's:

  raw lines / raw bytes   a plain line diff of the input text against the output text: added plus removed lines,
                          and the bytes of those lines. This is what a reviewer sees in `git diff`.
  normalised lines        `py_tbparse.xmldiff.diff_line_count`: the real edit, with attribute order, quotes,
                          indentation and empty-element style ignored.
  unrelated lines         max(0, raw lines - normalised lines): a rough estimate of the churn that is not the
                          edit. The two counts use different line units (the canonical form puts every element
                          open and close on its own line), so this is a proxy, not an exact figure.
  zero unrelated churn    the share of files whose unrelated lines are 0.

Only aggregates are printed: no file content, no file names of corpus workbooks.

    python scripts/measure_writer_diffs.py [--max-files N] [--timeout S] [--writers a,b] [--json OUT]
    python scripts/measure_writer_diffs.py --files A.twb B.twbx          # only these files
    touch /tmp/measure_writer_diffs.stop                                  # stop after the current file

Limits: one process, one worker, files over 20 MB skipped, a per-writer timeout, a memory cap (RLIMIT_AS), a
pause while the machine is busy (load or free memory), a stop file, a disk-space check. Run it as
`nice -n 10 ionice -c3 timeout 3600 python scripts/measure_writer_diffs.py ...`.
"""

from __future__ import annotations

import argparse
import difflib
import gc
import io
import json
import os
import resource
import shutil
import signal
import statistics
import sys
import tempfile
import time
import zipfile
from pathlib import Path
from typing import Callable, Optional

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pandas as pd  # noqa: E402

from py_tbparse import TwbParser  # noqa: E402
from py_tbparse.xmldiff import diff_line_count  # noqa: E402

MAX_FILE_BYTES = 20 * 1024 * 1024
STOP_FILE = Path(os.environ.get("MEASURE_STOP_FILE", "/tmp/measure_writer_diffs.stop"))
LOAD_PAUSE = 3.5            # pause while the 1-minute load is above this
MEM_PAUSE_MB = 1500         # pause while less than this is available
MAX_PAUSE_S = 300           # give up (stop the run) after pausing this long in a row
MIN_DISK_MB = 500


class WriterTimeout(Exception):
    pass


class NotApplicable(Exception):
    """The workbook has nothing this writer could act on (no dashboard, no calculation, ...)."""


# ---------------------------------------------------------------------------------------------- the writers
# Each takes (path, workdir) and returns the output workbook's XML as bytes. Raise NotApplicable when the
# workbook has nothing to act on; any other exception counts as a failure of that writer on that file.

def _twb_of(data_or_path) -> bytes:
    """The workbook XML of a `.twb`, or of the first `.twb` member of a `.twbx` (bytes or path)."""
    if isinstance(data_or_path, (str, os.PathLike)):
        p = Path(data_or_path)
        data = p.read_bytes()
        if p.suffix.lower() == ".twb":
            return data
    else:
        data = data_or_path
    if data[:2] != b"PK":
        return data
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        names = [n for n in z.namelist() if n.lower().endswith(".twb") and "/" not in n]
        return z.read(names[0])


def w_roundtrip(path: Path, work: Path) -> bytes:
    from py_tbparse.rename import build_renamed_workbook
    return _twb_of(build_renamed_workbook(TwbParser(str(path)), pd.DataFrame()))


def w_rename(path: Path, work: Path) -> bytes:
    from py_tbparse.rename import build_renamed_workbook, suggest_field_renames
    parser = TwbParser(str(path))
    table = suggest_field_renames(parser, only_changed=True)
    if len(table) == 0:
        # nothing to clean up: rename the first field, so the writer still does one edit
        table = suggest_field_renames(parser)
        if len(table) == 0:
            raise NotApplicable
        table = table.head(1).copy()
        table["suggested"] = table["name"].astype(str).str.strip("[]") + " X"
    rep: dict = {}
    data = build_renamed_workbook(parser, table, rep)
    if not rep.get("applied"):
        raise NotApplicable
    return _twb_of(data)


def w_sanitize(path: Path, work: Path) -> bytes:
    from py_tbparse.sanitize import sanitize
    out = work / ("sanitized" + path.suffix)
    sanitize(TwbParser(str(path)), out)
    return _twb_of(out)


def _dashboards(parser: TwbParser) -> list[str]:
    return [d.get("name") for d in parser.xml_doc.xpath("/workbook/dashboards/dashboard") if d.get("name")]


def _sheets(parser: TwbParser) -> list[str]:
    return [d.get("name") for d in parser.xml_doc.xpath("/workbook/worksheets/worksheet") if d.get("name")]


def w_slice(path: Path, work: Path) -> bytes:
    from py_tbparse.slicer import slice_workbook
    dash = _dashboards(TwbParser(str(path)))
    if not dash:
        raise NotApplicable
    out = work / ("sliced" + path.suffix)
    slice_workbook(path, dash[0], output_path=out)
    return _twb_of(out)


def w_prune(path: Path, work: Path) -> bytes:
    from py_tbparse.prune import prune
    out = work / ("pruned" + path.suffix)
    rep = prune(path, output_path=out)
    if not out.exists():
        raise NotApplicable
    return _twb_of(out)


def w_sheet_copy(path: Path, work: Path) -> bytes:
    from py_tbparse.sheetcopy import build_sheet_copy
    sheets = _sheets(TwbParser(str(path)))
    if not sheets:
        raise NotApplicable
    data, rep = build_sheet_copy(path, path, sheets[:1], on_clash="rename")
    if not rep.get("copied"):
        raise NotApplicable
    return _twb_of(data)


def w_dashboard_copy(path: Path, work: Path) -> bytes:
    from py_tbparse.dashboardcopy import build_dashboard_copy
    dash = _dashboards(TwbParser(str(path)))
    if not dash:
        raise NotApplicable
    data, rep = build_dashboard_copy(path, path, dash[:1], on_clash="rename")
    if not rep.get("copied"):
        raise NotApplicable
    return _twb_of(data)


def w_scaffold(path: Path, work: Path) -> bytes:
    from py_tbparse.scaffold import build_scaffold_workbook, make_scaffold
    parser = TwbParser(str(path))
    dash = _dashboards(parser)
    if not dash:
        raise NotApplicable
    scaffold = make_scaffold(parser, dash[0])
    return _twb_of(build_scaffold_workbook(parser, scaffold, "Measured copy", allow_empty=True))


def w_style_import(path: Path, work: Path) -> bytes:
    from py_tbparse.style import build_with_palettes
    palettes = [{"name": "Measured palette", "type": "regular",
                 "colors": ["#4E79A7", "#F28E2B", "#E15759", "#76B7B2"], "attrs": {"custom": "true"}}]
    rep: dict = {}
    data = build_with_palettes(path, palettes, on_clash="rename", report=rep)
    if not (rep.get("added") or rep.get("renamed")):
        raise NotApplicable
    return _twb_of(data)


def w_library_import(path: Path, work: Path) -> bytes:
    from py_tbparse.library import build_imported_workbook, export_library
    parser = TwbParser(str(path))
    ds = [d for d in parser.xml_doc.xpath("/workbook/datasources/datasource[connection]")
          if d.get("name") and d.get("hasconnection") != "false"]
    if not ds:
        raise NotApplicable
    rep: dict = {}
    library = export_library(parser, datasource=ds[0].get("name"), report=rep)
    if not library.get("entries"):
        raise NotApplicable
    for entry in library["entries"]:     # the same workbook would only skip every entry as identical
        if entry.get("kind") == "calc" and entry.get("formula"):
            entry["formula"] = f"({entry['formula']})"
            entry["formula_display"] = entry["formula"]
    rep2: dict = {}
    data = build_imported_workbook(parser, library, datasource=ds[0].get("name"), on_clash="rename", report=rep2)
    if not (rep2.get("added") or rep2.get("renamed")):
        raise NotApplicable
    return _twb_of(data)


def _make_template(path: Path, work: Path, name: str, revision_of=None) -> Path:
    from py_tbparse.templates import make_template
    return Path(make_template(TwbParser(str(path)), work / f"{name}.template.twbx", name=name,
                              revision_of=revision_of))


def _csv_for(template_path: Path, work: Path) -> Path:
    """A one-row CSV with a column per field of the template's first datasource (the field's remote name),
    so `apply_template` swaps the connection to a CSV, the usual use. Content is synthetic."""
    from py_tbparse.templates import load_template
    manifest = load_template(template_path).manifest
    fields = manifest["datasources"][0]["fields"]
    names = [f.get("remote") or f["name"].strip("[]") for f in fields if f.get("remote") or f.get("name")]
    names = list(dict.fromkeys(n.replace(",", " ").replace('"', "") for n in names if n)) or ["a"]
    csv = work / "data.csv"
    csv.write_text(",".join(names) + "\n" + ",".join("1" for _ in names) + "\n", encoding="utf-8")
    return csv


def w_template_apply(path: Path, work: Path) -> bytes:
    from py_tbparse.templates import apply_template
    tpl = _make_template(path, work, "t1")
    out = apply_template(tpl, data=_csv_for(tpl, work), output_path=work / "applied.twbx", allow_missing=True)
    return _twb_of(out)


def w_template_update(path: Path, work: Path) -> bytes:
    from py_tbparse.template_update import update_from_answers
    from py_tbparse.templates import apply_template, load_template
    v1 = _make_template(path, work, "t1")
    csv = _csv_for(v1, work)
    applied = apply_template(v1, data=csv, output_path=work / "applied.twbx", allow_missing=True)
    v2 = _make_template(path, work, "t2", revision_of=load_template(v1))
    out = update_from_answers(v2, applied, output_path=work / "updated.twbx", allow_missing=True, data=csv)
    if out is None:
        raise NotApplicable
    return _twb_of(out)


WRITERS: dict[str, Callable[[Path, Path], bytes]] = {
    "roundtrip": w_roundtrip,
    "rename": w_rename,
    "sanitize": w_sanitize,
    "slice": w_slice,
    "prune": w_prune,
    "sheet-copy": w_sheet_copy,
    "dashboard-copy": w_dashboard_copy,
    "scaffold": w_scaffold,
    "style-import": w_style_import,
    "library-import": w_library_import,
    "template-apply": w_template_apply,
    "template-update": w_template_update,
}


# ---------------------------------------------------------------------------------------------- measuring

def raw_diff(a: bytes, b: bytes) -> tuple[int, int]:
    """(differing lines, bytes of those lines): added plus removed lines of a plain line diff."""
    la, lb = a.decode("utf-8", "replace").splitlines(), b.decode("utf-8", "replace").splitlines()
    lines = nbytes = 0
    for d in difflib.unified_diff(la, lb, n=0, lineterm=""):
        if d[:1] in "+-" and not d.startswith(("+++", "---")):
            lines += 1
            nbytes += len(d[1:].encode("utf-8")) + 1
    return lines, nbytes


def percentile(values: list[float], q: float) -> float:
    s = sorted(values)
    if not s:
        return 0.0
    k = (len(s) - 1) * q
    lo, hi = int(k), min(int(k) + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


def summarise(rows: list[dict]) -> dict:
    """Aggregate numbers for one writer over the files where it ran."""
    out: dict = {"ran": len(rows)}
    for key in ("raw_lines", "raw_bytes", "norm_lines", "unrelated_lines"):
        vals = [r[key] for r in rows]
        out[key] = {"median": statistics.median(vals) if vals else 0, "p90": percentile(vals, 0.9),
                    "max": max(vals) if vals else 0}
    out["zero_unrelated_share"] = (sum(1 for r in rows if r["unrelated_lines"] == 0) / len(rows)) if rows else 0.0
    out["zero_norm_share"] = (sum(1 for r in rows if r["norm_lines"] == 0) / len(rows)) if rows else 0.0
    return out


class _Alarm:
    def __init__(self, seconds: float) -> None:
        self.seconds = seconds

    def __enter__(self):
        def boom(signum, frame):
            raise WriterTimeout
        self._old = signal.signal(signal.SIGALRM, boom)
        signal.setitimer(signal.ITIMER_REAL, self.seconds)

    def __exit__(self, *exc):
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, self._old)
        return False


def _meminfo_available_mb() -> float:
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            if line.startswith("MemAvailable:"):
                return int(line.split()[1]) / 1024
    except OSError:
        pass
    return float("inf")


def _load1() -> float:
    try:
        return float(Path("/proc/loadavg").read_text().split()[0])
    except OSError:
        return 0.0


def wait_until_calm(peaks: dict) -> bool:
    """Pause while load or memory is tight. False when the run should stop (stop file, or too long a wait)."""
    waited = 0.0
    while True:
        if STOP_FILE.exists():
            return False
        load = _load1()
        peaks["load1"] = max(peaks["load1"], load)
        if load <= LOAD_PAUSE and _meminfo_available_mb() >= MEM_PAUSE_MB:
            return True
        if waited >= MAX_PAUSE_S:
            return False
        time.sleep(5)
        waited += 5


def collect_files(args) -> tuple[list[Path], list[Path]]:
    if args.files:
        return [], [Path(f) for f in args.files]
    corpus: list[Path] = []
    cdir = Path(args.corpus_dir)
    if cdir.is_dir():
        corpus = sorted(cdir.glob("*.twb"))
        if args.max_files is not None:
            corpus = corpus[: args.max_files]
    fixtures: list[Path] = []
    if not args.no_fixtures:
        for pattern, base in (("**/*.twb", ROOT / "tests" / "fixtures"), ("**/*.twbx", ROOT / "tests" / "fixtures"),
                              ("*.twb", ROOT / "docs" / "demo"), ("*.twbx", ROOT / "docs" / "demo")):
            fixtures += sorted(base.glob(pattern))
        if args.max_files is not None:
            fixtures = fixtures[: args.max_files]
    return corpus, fixtures


def measure(files: list[Path], writers: list[str], timeout: float, peaks: dict, workroot: Path) -> dict:
    """{writer: {"rows": [...], "not_applicable": n, "failed": {ErrorClass: n}, "timeout": n}} over `files`."""
    result = {w: {"rows": [], "not_applicable": 0, "failed": {}, "timeout": 0} for w in writers}
    stopped = False
    for path in files:
        if not wait_until_calm(peaks):
            stopped = True
            break
        try:
            if path.stat().st_size > MAX_FILE_BYTES:
                peaks["skipped_big"] += 1
                continue
            original = _twb_of(path)
        except Exception:
            peaks["unreadable"] += 1
            continue
        if shutil.disk_usage(workroot).free < MIN_DISK_MB * 1024 * 1024:
            stopped = True
            break
        work = Path(tempfile.mkdtemp(prefix="w-", dir=workroot))
        try:
            for w in writers:
                slot = result[w]
                try:
                    with _Alarm(timeout):
                        out = WRITERS[w](path, work)
                        raw_lines, raw_bytes = raw_diff(original, out)
                        norm = diff_line_count(original, out)
                except NotApplicable:
                    slot["not_applicable"] += 1
                    continue
                except WriterTimeout:
                    slot["timeout"] += 1
                    continue
                except MemoryError:
                    slot["failed"]["MemoryError"] = slot["failed"].get("MemoryError", 0) + 1
                    continue
                except Exception as exc:
                    name = type(exc).__name__
                    slot["failed"][name] = slot["failed"].get(name, 0) + 1
                    continue
                finally:
                    for child in work.iterdir():
                        if child.is_dir():
                            shutil.rmtree(child, ignore_errors=True)
                        else:
                            child.unlink(missing_ok=True)
                slot["rows"].append({"raw_lines": raw_lines, "raw_bytes": raw_bytes, "norm_lines": norm,
                                     "unrelated_lines": max(0, raw_lines - norm)})
        finally:
            shutil.rmtree(work, ignore_errors=True)
            gc.collect()
        peaks["load1"] = max(peaks["load1"], _load1())
        if STOP_FILE.exists():
            stopped = True
            break
    peaks["stopped_early"] = peaks.get("stopped_early", False) or stopped
    return result


def format_table(title: str, files: int, result: dict) -> str:
    head = (f"{title}: {files} files\n"
            "| Writer | Ran | N/A | Failed | Timeout | Raw lines med/p90/max | Raw bytes med/p90/max | "
            "Normalised lines med/p90/max | Zero unrelated churn |\n|---|---|---|---|---|---|---|---|---|\n")
    rows = []
    for w, slot in result.items():
        s = summarise(slot["rows"])
        fmt = lambda k: "/".join(f"{s[k][m]:,.0f}" for m in ("median", "p90", "max"))  # noqa: E731
        failed = sum(slot["failed"].values())
        if s["ran"]:
            rows.append(f"| {w} | {s['ran']} | {slot['not_applicable']} | {failed} | {slot['timeout']} | "
                        f"{fmt('raw_lines')} | {fmt('raw_bytes')} | {fmt('norm_lines')} | "
                        f"{s['zero_unrelated_share'] * 100:.0f}% |")
        else:
            rows.append(f"| {w} | 0 | {slot['not_applicable']} | {failed} | {slot['timeout']} | - | - | - | - |")
    return head + "\n".join(rows)


def main(argv: Optional[list[str]] = None) -> int:
    old_limit = resource.getrlimit(resource.RLIMIT_AS)
    try:
        return _main(argv)
    finally:
        resource.setrlimit(resource.RLIMIT_AS, old_limit)    # callers (tests) keep their own limit


def _main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--corpus-dir", default=str(ROOT / "tests" / "corpus" / "files"))
    ap.add_argument("--max-files", type=int, default=None, help="cap on corpus files (and on fixtures)")
    ap.add_argument("--files", nargs="*", help="measure only these workbooks")
    ap.add_argument("--no-fixtures", action="store_true")
    ap.add_argument("--writers", default=",".join(WRITERS), help="comma separated; default all")
    ap.add_argument("--timeout", type=float, default=60.0, help="seconds per writer per file")
    ap.add_argument("--mem-limit-mb", type=int, default=3000, help="address-space cap for this process")
    ap.add_argument("--json", help="also write the aggregates here")
    ap.add_argument("--workdir", default=None, help="scratch folder (default: system temp)")
    args = ap.parse_args(argv)

    writers = [w.strip() for w in args.writers.split(",") if w.strip()]
    unknown = [w for w in writers if w not in WRITERS]
    if unknown:
        ap.error(f"unknown writer(s): {', '.join(unknown)}; choose from {', '.join(WRITERS)}")
    if args.mem_limit_mb > 0:
        limit = args.mem_limit_mb * 1024 * 1024
        resource.setrlimit(resource.RLIMIT_AS, (limit, resource.getrlimit(resource.RLIMIT_AS)[1]))
    corpus, fixtures = collect_files(args)
    if not corpus and not fixtures:
        print("no workbooks found (corpus: python scripts/fetch_corpus.py)", file=sys.stderr)
        return 2
    if STOP_FILE.exists():
        print(f"stop file exists: {STOP_FILE}", file=sys.stderr)
        return 3
    print(f"free MB {_meminfo_available_mb():.0f}; load {_load1():.2f}; corpus files {len(corpus)}; "
          f"fixtures {len(fixtures)}; writers {len(writers)}", flush=True)

    peaks = {"load1": _load1(), "skipped_big": 0, "unreadable": 0}
    workroot = Path(args.workdir) if args.workdir else Path(tempfile.gettempdir())
    workroot.mkdir(parents=True, exist_ok=True)
    started = time.time()
    summary: dict = {}
    tables = []
    for title, files in (("corpus", corpus), ("fixtures", fixtures)):
        if not files:
            continue
        result = measure(files, writers, args.timeout, peaks, workroot)
        tables.append(format_table(title, len(files), result))
        summary[title] = {"files": len(files), "writers": {
            w: {**summarise(slot["rows"]), "not_applicable": slot["not_applicable"], "failed": slot["failed"],
                "timeout": slot["timeout"]} for w, slot in result.items()}}
    print("\n\n".join(tables))
    peak_mb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
    summary["run"] = {"seconds": round(time.time() - started), "peak_rss_mb": round(peak_mb),
                      "peak_load1": peaks["load1"], "skipped_over_20mb": peaks["skipped_big"],
                      "unreadable": peaks["unreadable"], "stopped_early": bool(peaks.get("stopped_early"))}
    print(f"\nrun: {summary['run']}")
    if args.json:
        Path(args.json).write_text(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
