"""Guard for the exit-code table in docs/cli.md (issue #127).

Every row of the table has at least one case here that runs a cheap failure or success path and checks that the
code it really returns is listed in that row (not "not used"). A code that changes without the table, or a row
without a case, fails. The table is the contract; 0.6.0 moves the commands to one scheme and this file follows each move."""

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
            assert len(cells) == 9, line
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
    (tmp_path / "notjson.style.json").write_text("{not json")
    return [
        ("WORKBOOK [TABLE]", [WENJIE, "overview"], 0),
        ("WORKBOOK [TABLE]", [missing], 4),
        ("WORKBOOK [TABLE]", [WENJIE, "nope"], 2),
        ("WORKBOOK validate", [WENJIE, "validate"], 0),
        ("WORKBOOK validate", [missing, "validate"], 4),
        ("diff A B", ["diff", WENJIE, WENJIE], 0),
        ("diff A B", ["diff", WENJIE, missing], 4),
        ("diff A B", ["diff", WENJIE], 2),
        ("diff-xml A B", ["diff-xml", WENJIE, WENJIE], 0),
        ("diff-xml A B", ["diff-xml", WENJIE, TEMPLATE], 1),
        ("diff-xml A B", ["diff-xml", WENJIE, missing], 4),
        ("diff-xml A B", ["diff-xml", WENJIE, WENJIE, "-o", WENJIE], 5),
        ("diff-xml A B", ["diff-xml", WENJIE], 2),
        ("batch DIR", ["batch", str(HERE / "fixtures"), "overview"], 0),
        ("batch DIR", ["batch", missing], 4),
        ("batch DIR", ["batch"], 2),
        ("rename WORKBOOK", ["rename", WENJIE], 0),
        ("rename WORKBOOK", ["rename", missing], 1),
        ("rename WORKBOOK", ["rename", WENJIE, "--missing"], 2),
        ("audit WORKBOOK", ["audit", WENJIE, "--fail-on", "never"], 0),
        ("audit WORKBOOK", ["audit", WENJIE, "--fail-on", "info"], 1),
        ("audit WORKBOOK", ["audit", missing], 4),
        ("audit WORKBOOK", ["audit", WENJIE, "--only", "Z999"], 2),
        ("audit WORKBOOK", ["audit", WENJIE, "--only", " "], 2),
        ("template check TEMPLATE", ["template", "check", TEMPLATE], 0),
        ("template check TEMPLATE", ["template", "check", TEMPLATE, "--fail-on", "info"], 1),
        ("template check TEMPLATE", ["template", "check", WENJIE], 4),
        ("template check TEMPLATE", ["template", "check", TEMPLATE, "--only", " "], 2),
        ("template drift TEMPLATE FILES", ["template", "drift", TEMPLATE, missing], 4),
        ("template drift TEMPLATE FILES", ["template", "drift", TEMPLATE, missing, "--only", " "], 2),
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
        ("style show", ["style", "show", str(STYLE / "Preferences.tps")], 0),
        ("style check FILE", ["style", "check", str(STYLE / "Preferences.tps")], 0),
        ("style check FILE", ["style", "check", str(STYLE / "bad.tps")], 1),                  # readable XML, a bad palette in it
        ("style check FILE", ["style", "check", str(STYLE / "bad-format.style.json")], 1),    # parses, breaks the schema
        ("style check FILE", ["style", "check", str(tmp_path / "none.style.json")], 4),
        ("style check FILE", ["style", "check", str(tmp_path / "notjson.style.json")], 4),
        ("style check FILE", ["style", "check", WENJIE], 2),
        ("style export", ["style", "export", str(STYLE / "bad.tps"), "-o", str(tmp_path / "b.tps")], 2),
        ("style export", ["style", "show", missing], 1),
        ("style apply", ["style", "apply", str(STYLE / "format.style.json"), str(STYLE / "format-bare.twb"), "--scope", "workbook"], 0),
        ("style apply", ["style", "apply", str(STYLE / "format.style.json"), missing], 1),
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
        ("docs WORKBOOK", ["docs", missing], 4),
        ("docs WORKBOOK", ["docs", WENJIE, "-o", WENJIE], 5),
        ("docs WORKBOOK", ["docs", WENJIE, "--nope"], 2),
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


def test_validate_broken_relationship_is_6(monkeypatch, capsys):
    from py_tbparse import TwbParser
    monkeypatch.setattr(TwbParser, "validate", lambda self: {"ok": False, "issues": {}})
    assert code_of([WENJIE, "validate"]) == 6
    assert code_of([WENJIE, "validate", "--format", "junit"]) == 6
    assert not ROWS[row("WORKBOOK validate")][6].lower().startswith("not used")


def test_diff_xml_output_that_is_an_input_leaves_it_unchanged(tmp_path):
    before = Path(WENJIE).read_bytes()
    assert code_of(["diff-xml", WENJIE, WENJIE, "-o", WENJIE]) == 5
    assert Path(WENJIE).read_bytes() == before


def test_fail_on_never_keeps_finding_0_and_crash_3(monkeypatch, capsys):
    assert code_of(["audit", WENJIE, "--fail-on", "never"]) == 0
    crash_after(monkeypatch, "audit")
    assert code_of(["audit", WENJIE, "--fail-on", "never"]) == 3


def test_sheet_copy_partial_refusal_is_2(tmp_path, capsys):
    from test_sheetcopy import SHEET, DS, workbook, target_text, write
    two = workbook().replace("</worksheets>", SHEET.replace("Sheet 1", "Sheet 2").replace(
        "<rows>", f"<rows>[{DS}].[sum:Ghost:qk]") + "</worksheets>")
    s = write(tmp_path, two, "two.twb")
    d = write(tmp_path, target_text(), "d.twb")
    assert code_of(["sheet", "copy", s, "--sheets", "Sheet 1,Sheet 2", "--to", d, "--write",
                    "-o", str(tmp_path / "p.twb")]) == 2
    assert not ROWS[row("sheet copy SRC")][2].lower().startswith("not used")


def test_style_apply_partial_is_2(tmp_path):
    out = tmp_path / "o.twb"
    assert code_of(["style", "apply", str(STYLE / "format.style.json"), str(STYLE / "format-bare.twb"), "--write",
                    "-o", str(out)]) == 2
    assert out.exists() and not ROWS[row("style apply")][2].lower().startswith("not used")


def test_every_row_has_a_case(tmp_path, monkeypatch):
    covered = {p for p, _, _ in cases(tmp_path, monkeypatch)}
    covered |= {"WORKBOOK validate", "sheet copy SRC", "audit WORKBOOK", "template check TEMPLATE"}
    uncovered = [k for k in ROWS if not any(k.startswith(f"`{p}") for p in covered)]
    # precommit is a wrapper with its own tests (test_pre_push_hook / precommit)
    assert [k for k in uncovered if "precommit" not in k] == [], uncovered


def test_table_cells_are_plain_text_of_nine_columns():
    assert len(ROWS) >= 20
    for key, cells in ROWS.items():
        assert len(cells) == 8, key


# ---- central handling in cli.main (WP4): one place maps an escaped exception to its code ----

@pytest.mark.parametrize("target", ["overview", "diff", "batch"])
def test_unexpected_exception_is_crash(target, monkeypatch, capsys, tmp_path):
    def boom(*a, **k):
        raise RuntimeError("boom")

    if target == "overview":
        monkeypatch.setitem(cli.TABLE_SPECS, "overview", boom)
        argv = [WENJIE, "overview"]
    elif target == "diff":
        monkeypatch.setattr(cli, "diff_workbooks", boom)
        argv = ["diff", WENJIE, WENJIE]
    else:
        monkeypatch.setattr(cli, "scan_folder", boom)
        argv = ["batch", str(tmp_path)]
    assert code_of(argv) == 3
    err = capsys.readouterr().err
    assert "internal error: RuntimeError: boom" in err and "Traceback" in err


def test_closed_pipe_is_exit_0_and_prints_nothing(monkeypatch, capsys):
    def closed(*a, **k):
        raise BrokenPipeError(32, "Broken pipe")

    monkeypatch.setitem(cli.TABLE_SPECS, "overview", closed)
    assert code_of([WENJIE, "overview"]) == 0
    assert capsys.readouterr().err == ""


def test_ctrl_c_is_130_without_traceback(monkeypatch, capsys):
    def interrupted(*a, **k):
        raise KeyboardInterrupt

    monkeypatch.setitem(cli.TABLE_SPECS, "overview", interrupted)
    assert code_of([WENJIE, "overview"]) == 130
    assert "Traceback" not in capsys.readouterr().err


def test_usage_and_help_pass_through_the_handler(capsys):
    assert code_of([WENJIE, "overview", "--nope"]) == 2
    assert code_of(["--help"]) == 0


def test_output_refusal_is_5_and_unwritable_output_is_4(tmp_path, capsys):
    out = tmp_path / "there.csv"
    out.write_text("keep")
    assert code_of([WENJIE, "overview", "-o", out]) == 5
    assert code_of([WENJIE, "overview", "-o", tmp_path / "no" / "such" / "x.csv"]) == 4
    err = capsys.readouterr().err
    assert "Traceback" not in err and out.read_text() == "keep"


def test_malformed_workbook_is_bad_input(tmp_path, capsys):
    bad = tmp_path / "bad.twb"
    bad.write_text("<workbook")
    assert code_of([bad, "overview"]) == 4
    err = capsys.readouterr().err
    assert err.startswith("error:") and "Traceback" not in err
    assert code_of(["docs", bad]) == 4 and code_of(["diff", bad, WENJIE]) == 4
    txt = tmp_path / "x.txt"
    txt.write_text("hello")
    assert code_of([txt, "overview"]) == 4


# ---- real processes: what the shell sees (flush at shutdown is where mock-based tests cannot look) ----

def _run_cli(argv, **kw):
    import os
    import subprocess
    import sys as _sys
    env = dict(os.environ, PYTHONPATH=str(HERE.parent) + os.pathsep + os.environ.get("PYTHONPATH", ""))
    return subprocess.Popen([_sys.executable, "-m", "py_tbparse.cli", *map(str, argv)], env=env,
                            stderr=subprocess.PIPE, **kw)


@pytest.mark.parametrize("argv", [
    [WENJIE, "fields"],
    [WENJIE, "fields", "-f", "json"],
    ["batch", str(HERE / "fixtures")],
], ids=["table", "json", "batch"])
def test_real_closed_pipe_exits_0_and_prints_nothing(argv):
    import subprocess
    p = _run_cli(argv, stdout=subprocess.PIPE)
    p.stdout.read(10)
    p.stdout.close()
    err = p.stderr.read()
    p.stderr.close()
    assert p.wait(timeout=60) == 0
    assert err == b""


@pytest.mark.skipif(sys.platform == "win32" or not Path("/dev/full").exists(), reason="needs /dev/full")
def test_real_full_disk_is_3_with_one_error_line():
    with open("/dev/full", "wb") as full:
        p = _run_cli([WENJIE, "overview"], stdout=full)
        err = p.stderr.read().decode()
        p.stderr.close()
        assert p.wait(timeout=60) == 3
    assert err.startswith("error: ") and "Traceback" not in err and "bug" not in err and "Exception ignored" not in err


def test_failed_write_leaves_no_file_behind(tmp_path, monkeypatch, capsys):
    monkeypatch.setitem(cli.TABLE_SPECS, "overview", lambda *a, **k: __import__("pandas").DataFrame({"a": ["\ud800"]}))
    out = tmp_path / "o.csv"
    assert code_of([WENJIE, "overview", "-f", "csv", "-o", out]) == 3
    assert not out.exists()


@pytest.mark.parametrize("argv", [["audit", WENJIE, "--fail-on", "never"], ["diff-xml", WENJIE, WENJIE],
                                  ["rename", WENJIE]], ids=["audit", "diff-xml", "rename"])
def test_o_existing_is_5_and_missing_folder_is_4_for_other_writers(argv, tmp_path, capsys):
    out = tmp_path / "x.out"
    out.write_text("keep")
    assert code_of([*argv, "-o", out]) == 5
    assert out.read_text() == "keep"
    assert code_of([*argv, "-o", tmp_path / "no" / "x.out"]) == 4
    assert "Traceback" not in capsys.readouterr().err
