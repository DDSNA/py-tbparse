"""How much does parse-and-save (no edits) change a workbook? Measured over tests/corpus/files.

For each workbook: save it with `build_renamed_workbook` and an empty rename table (the writer every
py-tbparse feature uses, `rename._serialize_workbook`), then count the lines that differ

  * raw: a plain line diff of the original file against the saved file;
  * normalised: `py_tbparse.xmldiff.diff_line_count` (attribute order, quotes, indentation ignored).

    python scripts/measure_roundtrip_diff.py [--show N]
"""

from __future__ import annotations

import argparse
import difflib
import statistics
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from py_tbparse import TwbParser  # noqa: E402
from py_tbparse.rename import build_renamed_workbook  # noqa: E402
from py_tbparse.xmldiff import diff_line_count, normalised_diff  # noqa: E402


def _raw_count(a: bytes, b: bytes) -> int:
    la, lb = a.decode("utf-8", "replace").splitlines(), b.decode("utf-8", "replace").splitlines()
    return sum(1 for d in difflib.unified_diff(la, lb, n=0, lineterm="")
               if d[:1] in "+-" and not d.startswith(("+++", "---")))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--show", type=int, default=3, help="print the normalised diff of this many worst files")
    args = ap.parse_args()
    files = sorted((ROOT / "tests" / "corpus" / "files").glob("*.twb"))
    if not files:
        print("corpus not fetched: python scripts/fetch_corpus.py", file=sys.stderr)
        return 2
    rows = []
    for path in files:
        original = path.read_bytes()
        saved = build_renamed_workbook(TwbParser(str(path)), pd.DataFrame())
        rows.append({"file": path.name, "lines": len(original.decode("utf-8", "replace").splitlines()),
                     "raw": _raw_count(original, saved), "normalised": diff_line_count(original, saved),
                     "saved": saved})
    n = len(rows)
    for key in ("raw", "normalised"):
        vals = [r[key] for r in rows]
        zero = sum(1 for v in vals if v == 0)
        print(f"{key:>10}: files with 0 differing lines {zero}/{n}; median {statistics.median(vals)}; "
              f"max {max(vals)}; total {sum(vals)}")
    worst = sorted(rows, key=lambda r: -r["normalised"])
    for r in worst[: args.show]:
        if r["normalised"]:
            print(f"\n== {r['file']}: {r['normalised']} normalised lines of {r['lines']} ==")
            print("".join(normalised_diff(ROOT / "tests" / "corpus" / "files" / r["file"], r["saved"]).splitlines(True)[:40]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
