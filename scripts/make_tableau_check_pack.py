#!/usr/bin/env python3
"""Write one of every kind of file py-tbparse produces into one folder, to open in Tableau Desktop by hand.

    python scripts/make_tableau_check_pack.py OUT_DIR

Nothing here has been opened in Tableau. The inputs are committed files, no corpus is needed:

    docs/demo/coffee-shop.twb               rename, prune, slice, sanitize, palettes (hand-made: no connection)
    tests/fixtures/public/filtering.twb     sheet copy, dashboard copy, scaffold, sanitize --fake-data, templates
                                            (a workbook Tableau wrote; one CSV-style table)
    tests/fixtures/library/*.twb            library import
    tests/fixtures/style/palettes.twb       the palettes
    tests/fixtures/style/format-*.twb       the fonts (copies of filtering.twb, hand-edited) and format.style.json

The files are numbered; the list of what to look at is docs/tableau-check.md. A `results.csv` with one row per
file is written for the person at Tableau to fill in, and `commands.txt` lists the exact command behind each
file. The template files (2x-5x) come from scripts/make_verification_pack.py, run into OUT_DIR/templates.
"""

from __future__ import annotations

import argparse
import contextlib
import csv
import io
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from py_tbparse import cli  # noqa: E402

DEMO = "docs/demo/coffee-shop.twb"
FILTERING = "tests/fixtures/public/filtering.twb"
LIB_SOURCE = "tests/fixtures/library/source.twb"
LIB_TARGET = "tests/fixtures/library/target.twb"
PALETTES = "tests/fixtures/style/palettes.twb"
FORMAT_STYLE = "tests/fixtures/style/format.style.json"
FORMAT_BARE = "tests/fixtures/style/format-bare.twb"
FORMAT_TARGET = "tests/fixtures/style/format-target.twb"


INPUTS = (DEMO, FILTERING, LIB_SOURCE, LIB_TARGET, PALETTES, FORMAT_STYLE, FORMAT_BARE, FORMAT_TARGET)


def steps(out: Path) -> list[tuple[str, list[str]]]:
    """(output file, py-tbparse arguments) in the order the checklist uses. Paths in the arguments are relative to
    the repository root for the inputs and `out` for the outputs."""
    o = str
    DEMO, FILTERING, LIB_SOURCE, LIB_TARGET, PALETTES, STYLE, BARE, TARGET = (str(ROOT / p) for p in INPUTS)
    return [
        ("10-rename.twb", ["rename", DEMO, "--all", "--write-workbook", o(out / "10-rename.twb")]),
        ("11-prune.twb", ["prune", DEMO, "--sheets", "--write", "-o", o(out / "11-prune.twb")]),
        ("12-slice.twb", ["slice", DEMO, "-d", "Weekly Overview", "--write", "-o", o(out / "12-slice.twb")]),
        ("13-sanitize.twb", ["sanitize", FILTERING, o(out / "13-sanitize.twb"), "--placeholders"]),
        ("14-sanitize-fake-data.twbx", ["sanitize", FILTERING, o(out / "14-sanitize-fake-data.twbx"), "--fake-data"]),
        ("20-sheet-copy.twb", ["sheet", "copy", FILTERING, "--sheets", "Sheet 1", "--to", FILTERING,
                               "--on-clash", "rename", "--write", "-o", o(out / "20-sheet-copy.twb")]),
        ("21-dashboard-copy.twb", ["dashboard", "copy", FILTERING, "--dashboards", "setTest", "--to", FILTERING,
                                   "--on-clash", "rename", "--write", "-o", o(out / "21-dashboard-copy.twb")]),
        ("22-scaffold.scaffold.json", ["scaffold", "make", FILTERING, "-o", o(out / "22-scaffold.scaffold.json")]),
        ("22-scaffold.twb", ["scaffold", "apply", FILTERING, o(out / "22-scaffold.scaffold.json"),
                             "--name", "Scaffold Check", "--sheets", "Sheet 2,Sheet 1", "--write",
                             "-o", o(out / "22-scaffold.twb")]),
        ("30-library.json", ["library", "export", LIB_SOURCE, "-o", o(out / "30-library.json")]),
        ("30-library.twb", ["library", "import", LIB_TARGET, o(out / "30-library.json"), "--on-clash", "rename",
                            "--write", "-o", o(out / "30-library.twb")]),
        ("40-palettes.twb", ["style", "import", PALETTES, DEMO, "--write", "-o", o(out / "40-palettes.twb")]),
        ("41-Preferences_new.tps", ["style", "export", PALETTES, "-o", o(out / "41-Preferences_new.tps")]),
        ("42-fonts.twb", ["style", "apply", STYLE, BARE, "--scope", "workbook", "--write", "-o", o(out / "42-fonts.twb")]),
        ("44-fonts-keep.twb", ["style", "apply", STYLE, TARGET, "--scope", "workbook", "--write",
                               "-o", o(out / "44-fonts-keep.twb")]),
        ("44-fonts-force.twb", ["style", "apply", STYLE, TARGET, "--scope", "workbook", "--force", "--write",
                                "-o", o(out / "44-fonts-force.twb")]),
    ]


def template_steps(out: Path) -> list[tuple[str, list[str]]]:
    """The template files that need the pack's template (templates/_work/template.twbx) and its sample data."""
    t = out / "templates"
    data = t / "data"
    new_template = t / "_work" / "template-rev2.twbx"
    return [
        ("templates/56-template-update.twbx", ["template", "update", o_(new_template), o_(t / "2-template-on-csv.twbx"),
                                               "--old", o_(t / "_work" / "template.twbx"), "--write",
                                               o_(t / "56-template-update.twbx")]),
        ("templates/57-apply-folder/", ["template", "apply-folder", o_(t / "_work" / "template.twbx"), o_(data),
                                        "-o", o_(t / "57-apply-folder")]),
    ]


def o_(path: Path) -> str:
    return str(path)


def run(argv: list[str]) -> tuple[int, str]:
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
        try:
            code = cli.main(argv)
        except SystemExit as exc:
            code = exc.code if isinstance(exc.code, int) else 1
    return int(code or 0), buf.getvalue().strip()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Make every kind of output to open in Tableau by hand.")
    ap.add_argument("out_dir", help="a new or empty folder")
    args = ap.parse_args(argv)

    out = Path(args.out_dir).resolve()
    if out.exists() and any(out.iterdir()):
        print(f"{out} is not empty; give a new folder", file=sys.stderr)
        return 2
    out.mkdir(parents=True, exist_ok=True)

    shutil.copy(ROOT / DEMO, out / "00-demo-original.twb")
    shutil.copy(ROOT / FILTERING, out / "00-filtering-original.twb")
    rows: list[tuple[str, str]] = [("00-demo-original.twb", "baseline"), ("00-filtering-original.twb", "baseline")]
    commands: list[str] = []
    failed = 0

    def go(name: str, argv: list[str]) -> None:
        nonlocal failed
        code, text = run(argv)
        line = "py-tbparse " + " ".join(f'"{a}"' if " " in a else a for a in argv)
        # forward slashes everywhere, so commands.txt reads the same on Windows
        line = line.replace("\\", "/").replace(out.as_posix(), "OUT").replace(ROOT.as_posix() + "/", "")
        commands.append(line)
        status = "ok" if code == 0 else f"EXIT {code}"
        if code:
            failed += 1
        print(f"{status:8} {name}" + (f"\n         {text.splitlines()[-1]}" if code and text else ""))
        if not name.endswith((".json", "/")):
            rows.append((name, status))

    for name, argv in steps(out):
        go(name, argv)

    import make_verification_pack

    report = io.StringIO()
    with contextlib.redirect_stdout(report):
        code = make_verification_pack.main([str(out / "templates")])
    (out / "templates" / "report.txt").write_text(report.getvalue(), encoding="utf-8")
    if code:
        print(f"template pack failed (exit {code})", file=sys.stderr)
        return 1
    for template_file in sorted((out / "templates").glob("[0-5]-*")):
        rows.append((f"templates/{template_file.name}", "ok"))
    commands.append(f"python scripts/make_verification_pack.py OUT/templates   # templates/0-5")

    from py_tbparse import make_template

    make_template(str(ROOT / FILTERING), output_path=str(out / "templates" / "_work" / "template-rev2.twbx"),
                  revision_of=str(out / "templates" / "_work" / "template.twbx"))
    for name, argv in template_steps(out):
        go(name, argv)

    for made in sorted((out / "templates" / "57-apply-folder").glob("*.twbx")):
        rows.append((f"templates/57-apply-folder/{made.name}", "ok"))

    (out / "commands.txt").write_text("\n".join(commands) + "\n", encoding="utf-8")
    with open(out / "results.csv", "w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["file", "made", "opens (yes / with a message / no)", "what you saw"])
        for name, status in rows:
            writer.writerow([name, status, "", ""])
    print(f"\nPack in {out} ({len(rows)} files, {failed} failed to be made).")
    print("Open each one in Tableau Desktop and follow docs/tableau-check.md; write what you see in results.csv.")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
