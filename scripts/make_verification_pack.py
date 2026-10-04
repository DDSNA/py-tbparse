#!/usr/bin/env python3
"""Write the three workbooks to open in Tableau by hand, with a sample CSV, and report what was checked.

    python scripts/make_verification_pack.py OUT_DIR [--workbook PATH]

Everything py-tbparse writes has been checked against Tableau's schema and for dangling references,
but never opened in Tableau itself. This makes the files that answer that, from a workbook real
Tableau wrote (default: tests/fixtures/public/filtering.twb). Run it on the machine that has Tableau:
the CSV connection holds the CSV's absolute path. What to look at is in docs/verify-in-tableau.md.

    0-original            the workbook as it was (the baseline: it must open the way it always did)
    1-renamed             every rename py-tbparse suggests, applied
    2-template-on-csv     a template made from it, applied to a CSV with every column the template needs
    3-template-on-workbook  the same template applied to workbook 2 (its connection is borrowed)
    4-template-on-excel   the same template applied to an .xlsx with the same rows (only with openpyxl)
    data/                 the sample CSV and .xlsx, with made-up values
"""

from __future__ import annotations

import argparse
import csv
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from py_tbparse import TwbParser, apply_template, load_template, make_template, suggest_renames  # noqa: E402
from py_tbparse.rename import build_renamed_workbook  # noqa: E402
from py_tbparse.verify import validate_workbook  # noqa: E402

DEFAULT = ROOT / "tests" / "fixtures" / "public" / "filtering.twb"
ROWS = 6


def sample_value(datatype: str, row: int):
    return {
        "integer": row + 1,
        "real": round((row + 1) * 1.5, 2),
        "boolean": "true" if row % 2 == 0 else "false",
        "date": f"2026-01-{row + 1:02d}",
        "datetime": f"2026-01-{row + 1:02d} 08:30:00",
    }.get(datatype, f"value {row + 1}")


def write_sample_csv(entry: dict, path: Path) -> None:
    with open(path, "w", newline="", encoding="utf-8") as fh:
        out = csv.writer(fh)
        out.writerow([f["remote"] for f in entry["fields"]])
        for row in range(ROWS):
            out.writerow([sample_value(f["datatype"], row) for f in entry["fields"]])


def write_sample_xlsx(entry: dict, path: Path) -> None:
    """The same rows as the CSV, with real Excel dates, numbers and booleans in one sheet called Data."""
    import datetime as dt

    import openpyxl

    def cell(datatype, row):
        value = sample_value(datatype, row)
        if datatype == "boolean":
            return value == "true"
        if datatype == "date":
            return dt.datetime.strptime(value, "%Y-%m-%d")
        if datatype == "datetime":
            return dt.datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
        return value

    book = openpyxl.Workbook()
    sheet = book.active
    sheet.title = "Data"
    sheet.append([f["remote"] for f in entry["fields"]])
    for row in range(ROWS):
        sheet.append([cell(f["datatype"], row) for f in entry["fields"]])
    book.save(str(path))


def schema_summary(original: Path, produced: Path) -> str:
    try:
        from schema_check import new_schema_errors
    except ImportError:
        return "not run (tests/ not found)"
    new = new_schema_errors(str(original), str(produced))
    return "no new errors" if not new else f"{len(new)} NEW: " + "; ".join(m[:80] for _, m in new[:3])


def reference_summary(original: Path, produced: Path) -> str:
    before = set(zip(*[validate_workbook(str(original))[c] for c in ("check", "datasource", "detail")]))
    after = validate_workbook(str(produced))
    new = [r for r in after.itertuples() if (r.check, r.datasource, r.detail) not in before]
    return "no new findings" if not new else f"{len(new)} NEW: " + "; ".join(f"{r.check} {r.detail[:60]}" for r in new[:3])


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Make the workbooks to open in Tableau by hand.")
    ap.add_argument("out_dir", help="a new or empty folder")
    ap.add_argument("--workbook", default=str(DEFAULT), help="a .twb/.twbx Tableau wrote (default: %(default)s)")
    args = ap.parse_args(argv)

    out = Path(args.out_dir).resolve()
    if out.exists() and any(out.iterdir()):
        print(f"{out} is not empty; give a new folder", file=sys.stderr)
        return 2
    (out / "data").mkdir(parents=True, exist_ok=True)
    work = out / "_work"
    work.mkdir()
    src = Path(args.workbook)
    ext = src.suffix.lower()

    original = out / f"0-original{ext}"
    shutil.copy(src, original)

    parser = TwbParser(str(original))
    report: dict = {}
    renamed = out / f"1-renamed{ext}"
    renamed.write_bytes(build_renamed_workbook(parser, suggest_renames(parser), report))

    template = load_template(make_template(str(original), output_path=str(work / "template.twbx")))
    entry = next((e for e in template.manifest["datasources"] if e["fields"]), None)
    if entry is None:
        print("the workbook has no datasource with fields to apply a template to", file=sys.stderr)
        return 1
    csv_path = out / "data" / f"{src.stem}-sample.csv"
    write_sample_csv(entry, csv_path)
    on_csv = out / "2-template-on-csv.twbx"
    apply_template(template, str(csv_path), datasource=entry["name"], output_path=str(on_csv))
    on_workbook = out / "3-template-on-workbook.twbx"
    apply_template(template, str(on_csv), datasource=entry["name"], output_path=str(on_workbook))

    files = [renamed, on_csv, on_workbook]
    try:
        import openpyxl  # noqa: F401
    except ImportError:
        print("openpyxl is not installed: no Excel file (pip install 'py-tbparse[excel]')", file=sys.stderr)
    else:
        xlsx_path = out / "data" / f"{src.stem}-sample.xlsx"
        write_sample_xlsx(entry, xlsx_path)
        on_excel = out / "4-template-on-excel.twbx"
        apply_template(template, str(xlsx_path), datasource=entry["name"], output_path=str(on_excel))
        files.append(on_excel)

    print(f"Pack in {out}\n")
    print(f"renames applied: {report.get('applied', '?')} (skipped {report.get('skipped', '?')})")
    for path in files:
        print(f"\n{path.name}")
        print(f"  schema:     {schema_summary(original, path)}")
        print(f"  references: {reference_summary(original, path)}")
    print("\nNext: open each file in Tableau and follow docs/verify-in-tableau.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
