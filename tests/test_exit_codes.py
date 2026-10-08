"""Guard for the exit-code table in docs/cli.md (issue #127: the codes are documented as they are, not unified).

Every row of the table has at least one case here that runs a cheap failure or success path and checks that the
code it really returns is listed in that row (not "not used"). A code that changes without the table, or a row
without a case, fails. The table is the contract until the 0.6.0 scheme decision."""

import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

from py_tbparse import cli
from test_dashboardcopy import source_text as dash_source, target_text as dash_target, write as dash_write

HERE = Path(__file__).parent
WENJIE = str(HERE / "fixtures" / "test_for_wenjie.twb")
TEMPLATE = str(HERE / "fixtures" / "templates" / "filtering.v1.template.twbx")
LIB = HERE / "fixtures" / "library"
STYLE = HERE / "fixtures" / "style"


def table_rows():
    text = (HERE.parent / "docs" / "cli.md").read_text(encoding="utf-8")
    section = text.split("\n## Exit codes\n", 1)[1].split("\n## ", 1)[0]
    rows = {}
    for line in section.splitlines():
        if line.startswith("|") and not line.startswith("| ---") and not line.startswith("| Command"):
            cells = [c.strip() for c in re.split(r"(?<!\\)\|", line.strip().strip("|"))]
            assert len(cells) == 5, line
            rows[cells[0]] = cells[1:]
    return rows


ROWS = table_rows()


def code_of(argv):
    try:
        return cli.main([str(a) for a in argv])
    except SystemExit as e:          # argparse: usage errors and --help
        return e.code


def row(prefix):
    found = [k for k in ROWS if k.startswith(f"`{prefix}")]
    assert len(found) == 1, (prefix, found)
    return found[0]


def crash_after(monkeypatch, name):
    real = getattr(cli, name)

    def crashing(*a, **k):
        df = real(*a, **k)
        df.attrs["crashed"] = ["X001"]
        df.attrs["tracebacks"] = {"X001": "Traceback (made up)"}
        return df

    monkeypatch.setattr(cli, name, crashing)


def cases(tmp_path, monkeypatch):
    """(row prefix, argv, expected code); built lazily because some need files."""
    missing = str(tmp_path / "missing.twb")
    exists = tmp_path / "exists.twb"
    exists.write_text("x")
    lib_json = tmp_path / "k.library.json"
    cli.main(["library", "export", str(LIB / "source.twb"), "-o", str(lib_json)])
    # library import with entries that fail: remove a column the entries need
    from lxml import etree
    doc = etree.parse(str(LIB / "target.twb"))
    for rec in doc.xpath("//metadata-record[local-name='[Profit]']"):
        rec.getparent().remove(rec)
    lib_target = tmp_path / "lt.twb"
    doc.write(str(lib_target), encoding="utf-8", xml_declaration=True)
    two = dash_source().replace("</dashboards>", "<dashboard name='Lone'><zones><zone id='1' name='Nope'/></zones>"
                                "</dashboard></dashboards>")
    dsrc = dash_write(tmp_path, two, "two.twb")
    ddst = dash_write(tmp_path, dash_target(), "dst.twb")
    sanitized = tmp_path / "san.twb"
    return [
        ("WORKBOOK [TABLE]", [WENJIE, "overview"], 0),
        ("WORKBOOK [TABLE]", [missing], 1),
        ("WORKBOOK [TABLE]", [WENJIE, "nope"], 2),
        ("WORKBOOK validate", [WENJIE, "validate"], 0),
        ("WORKBOOK validate", [missing, "validate"], 1),
        ("diff A B", ["diff", WENJIE, WENJIE], 0),
        ("diff A B", ["diff", WENJIE, missing], 1),
        ("diff A B", ["diff", WENJIE], 2),
        ("diff-xml A B", ["diff-xml", WENJIE, WENJIE], 0),
        ("diff-xml A B", ["diff-xml", WENJIE, TEMPLATE], 1),
        ("diff-xml A B", ["diff-xml", WENJIE, missing], 2),
        ("batch DIR", ["batch", str(HERE / "fixtures"), "overview"], 0),
        ("batch DIR", ["batch", missing], 1),
        ("batch DIR", ["batch"], 2),
        ("rename WORKBOOK", ["rename", WENJIE], 0),
        ("rename WORKBOOK", ["rename", missing], 1),
        ("rename WORKBOOK", ["rename", WENJIE, "--missing"], 2),
        ("audit WORKBOOK", ["audit", WENJIE, "--fail-on", "never"], 0),
        ("audit WORKBOOK", ["audit", WENJIE, "--fail-on", "info"], 1),
        ("audit WORKBOOK", ["audit", missing], 2),
        ("template check TEMPLATE", ["template", "check", TEMPLATE], 0),
        ("template check TEMPLATE", ["template", "check", TEMPLATE, "--fail-on", "info"], 1),
        ("template check TEMPLATE", ["template", "check", WENJIE], 2),
        ("template drift TEMPLATE FILES", ["template", "drift", TEMPLATE, missing], 2),
        ("template make", ["template", "show", TEMPLATE], 0),
        ("template make", ["template", "show", missing], 1),
        ("template make", ["template", "target-make", "--class", "postgres", "--server", "s", "--dbname", "d",
                           "--column", "a:int", "-o", str(tmp_path / "t.target.json")], 2),
        ("template apply-folder TEMPLATE DIR", ["template", "apply-folder", TEMPLATE, str(tmp_path),
                                               "-o", str(tmp_path / "o")], 0),
        ("template apply-folder TEMPLATE DIR", ["template", "apply-folder", TEMPLATE, missing], 1),
        ("library export", ["library", "show", str(lib_json)], 0),
        ("library export", ["library", "show", str(tmp_path / "none.json")], 1),
        ("library import", ["library", "import", str(LIB / "target.twb"), str(lib_json)], 1),
        ("library import", ["library", "import", str(lib_target), str(lib_json), "--on-clash", "rename",
                            "--write", "-o", str(tmp_path / "lo.twb")], 2),
        ("style show", ["style", "check", str(STYLE / "Preferences.tps")], 0),
        ("style show", ["style", "check", str(STYLE / "bad.tps")], 1),
        ("style export", ["style", "export", str(STYLE / "bad.tps"), "-o", str(tmp_path / "b.tps")], 2),
        ("style export", ["style", "show", missing], 1),
        ("scaffold make", ["scaffold", "make", WENJIE, "-d", "nope", "-o", str(tmp_path / "s.json")], 1),
        ("sanitize IN OUT", ["sanitize", WENJIE, str(sanitized)], 0),
        ("sanitize IN OUT", ["sanitize", WENJIE, str(sanitized)], 2),       # now it exists
        ("prune WORKBOOK", ["prune", WENJIE], 0),
        ("prune WORKBOOK", ["prune", missing], 2),
        ("slice WORKBOOK", ["slice", WENJIE, "-d", "nope"], 2),
        ("sheet copy SRC", ["sheet", "copy", WENJIE, "--sheets", "nope", "--to", WENJIE], 1),
        ("dashboard copy SRC", ["dashboard", "copy", dsrc, "--dashboards", "Nope", "--to", ddst], 1),
        ("dashboard copy SRC", ["dashboard", "copy", dsrc, "--dashboards", "Dash,Lone", "--to", ddst,
                                "--write", "-o", str(tmp_path / "dc.twb")], 2),
        ("docs WORKBOOK", ["docs", WENJIE], 0),
        ("docs WORKBOOK", ["docs", missing], 2),
    ]


def test_every_documented_case_returns_a_code_the_table_lists(tmp_path, monkeypatch, capsys):
    for prefix, argv, expected in cases(tmp_path, monkeypatch):
        got = code_of(argv)
        capsys.readouterr()
        assert got == expected, f"{argv[:3]}: returned {got}, expected {expected}"
        cell = ROWS[row(prefix)][expected]
        assert not cell.lower().startswith("not used"), f"{argv[:3]}: code {expected} is 'not used' in the table"


def test_rule_crash_is_3_where_the_table_says_so(monkeypatch, capsys):
    crash_after(monkeypatch, "audit")
    assert code_of(["audit", WENJIE, "--fail-on", "never"]) == 3
    assert not ROWS[row("audit WORKBOOK")][3].lower().startswith("not used")
    monkeypatch.undo()
    crash_after(monkeypatch, "check_template")
    assert code_of(["template", "check", TEMPLATE]) == 3
    assert not ROWS[row("template check TEMPLATE")][3].lower().startswith("not used")


def test_validate_broken_relationship_is_2(monkeypatch, capsys):
    from py_tbparse import TwbParser
    monkeypatch.setattr(TwbParser, "validate", lambda self: {"ok": False, "issues": {}})
    assert code_of([WENJIE, "validate"]) == 2
    assert code_of([WENJIE, "validate", "--format", "junit"]) == 2
    assert not ROWS[row("WORKBOOK validate")][2].lower().startswith("not used")


def test_sheet_copy_partial_refusal_is_2(tmp_path, capsys):
    from test_sheetcopy import SHEET, DS, workbook, target_text, write
    two = workbook().replace("</worksheets>", SHEET.replace("Sheet 1", "Sheet 2").replace(
        "<rows>", f"<rows>[{DS}].[sum:Ghost:qk]") + "</worksheets>")
    s = write(tmp_path, two, "two.twb")
    d = write(tmp_path, target_text(), "d.twb")
    assert code_of(["sheet", "copy", s, "--sheets", "Sheet 1,Sheet 2", "--to", d, "--write",
                    "-o", str(tmp_path / "p.twb")]) == 2
    assert not ROWS[row("sheet copy SRC")][2].lower().startswith("not used")


def test_every_row_has_a_case(tmp_path, monkeypatch):
    covered = {p for p, _, _ in cases(tmp_path, monkeypatch)}
    covered |= {"WORKBOOK validate", "sheet copy SRC", "audit WORKBOOK", "template check TEMPLATE"}
    uncovered = [k for k in ROWS if not any(k.startswith(f"`{p}") for p in covered)]
    # precommit is a wrapper with its own tests (test_pre_push_hook / precommit)
    assert [k for k in uncovered if "precommit" not in k] == [], uncovered


def test_table_cells_are_plain_text_of_five_columns():
    assert len(ROWS) >= 20
    for key, cells in ROWS.items():
        assert len(cells) == 4, key
