import json
from pathlib import Path

import pytest

from py_tbparse import cli


def test_tables_lists_all(capsys):
    rc = cli.main(["ignored.twb", "tables"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "datasources" in out
    assert "dashboard-sheets" in out


def test_overview_default_table(wenjie_path, capsys):
    rc = cli.main([wenjie_path])
    out = capsys.readouterr().out
    assert rc == 0
    assert "datasources" in out
    assert "test_for_wenjie.twb" in out


def test_calculated_fields_json(wenjie_path, capsys):
    rc = cli.main([wenjie_path, "calculated-fields", "--format", "json"])
    out = capsys.readouterr().out
    assert rc == 0
    data = json.loads(out)
    assert len(data) == 1
    assert data[0]["tableau_internal_name"] == "[Calculation_2139209847776120832]"


def test_csv_format(wenjie_path, capsys):
    rc = cli.main([wenjie_path, "fields", "--format", "csv"])
    out = capsys.readouterr().out
    assert rc == 0
    assert out.splitlines()[0].startswith("caption,datatype,")


def test_validate_ok_exit_code(wenjie_path, capsys):
    rc = cli.main([wenjie_path, "validate"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "ok: True" in out


def test_missing_file_returns_1(capsys):
    rc = cli.main(["does_not_exist.twb"])
    err = capsys.readouterr().err
    assert rc == 1
    assert "error:" in err


def test_output_to_file(wenjie_path, tmp_path):
    out_file = tmp_path / "out.csv"
    rc = cli.main([wenjie_path, "datasources", "--format", "csv", "--output", str(out_file)])
    assert rc == 0
    content = out_file.read_text()
    assert content.splitlines()[0].startswith("primary_table,")


def test_dashboard_sheets_with_filter(wenjie_path, capsys):
    rc = cli.main([wenjie_path, "dashboard-sheets", "--dashboard", "Nope"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "(empty)" in out


def test_unknown_table_rejected_by_argparse(wenjie_path):
    with pytest.raises(SystemExit):
        cli.main([wenjie_path, "not-a-real-table"])


def test_graph_prints_dot(wenjie_path, capsys):
    rc = cli.main([wenjie_path, "graph"])
    out = capsys.readouterr().out
    assert rc == 0
    assert out.startswith("digraph \"twb\" {")
    assert "Sheet1" in out


def test_graph_output_to_file(wenjie_path, tmp_path):
    out_file = tmp_path / "graph.dot"
    rc = cli.main([wenjie_path, "graph", "--output", str(out_file)])
    assert rc == 0
    assert out_file.read_text().startswith("digraph \"twb\" {")


def test_new_v2_tables_are_listed(capsys):
    rc = cli.main(["ignored.twb", "tables"])
    out = capsys.readouterr().out
    assert rc == 0
    for name in ("custom-sql", "initial-sql", "published-refs"):
        assert name in out


def test_diff_subcommand_self_is_empty(wenjie_path, capsys):
    rc = cli.main(["diff", wenjie_path, wenjie_path, "datasources"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "(empty)" in out


def test_diff_subcommand_missing_file(wenjie_path, capsys):
    rc = cli.main(["diff", wenjie_path, "nope.twb"])
    err = capsys.readouterr().err
    assert rc == 1
    assert "error:" in err


def test_batch_subcommand_lists_both_fixtures(capsys):
    rc = cli.main(["batch", "tests/fixtures", "overview"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "test_for_wenjie.twb" in out
    assert "test_for_zip.twbx" in out or "test-for_zip.twb" in out


def test_batch_subcommand_not_a_directory(wenjie_path, capsys):
    rc = cli.main(["batch", wenjie_path])
    err = capsys.readouterr().err
    assert rc == 1
    assert "error:" in err


def test_diff_keyword_does_not_shadow_a_real_file_named_diff(tmp_path, monkeypatch, capsys):
    # A workbook literally named "diff" (no extension) sitting in the
    # current directory must be treated as that workbook, not hijacked
    # into the diff subcommand.
    (tmp_path / "diff").write_text("<workbook/>")
    monkeypatch.chdir(tmp_path)
    rc = cli.main(["diff"])
    err = capsys.readouterr().err
    # Reaches TwbParser("diff") and fails on the extension check, not on
    # the diff subcommand's "workbook_a/workbook_b required" usage error.
    assert rc == 1
    assert "Unsupported file type" in err


# ---------------------------------------------------------------- library --

LIB_FIX = Path(__file__).parent / "fixtures" / "library"


def test_library_export_show_import(tmp_path, capsys):
    lib = tmp_path / "k.library.json"
    assert cli.main(["library", "export", str(LIB_FIX / "source.twb"), "-o", str(lib), "--name", "KPIs"]) == 0
    err = capsys.readouterr().err
    assert "wrote" in err and "12 entries" in err
    assert json.loads(lib.read_text(encoding="utf-8"))["name"] == "KPIs"
    # an existing library is not replaced
    assert cli.main(["library", "export", str(LIB_FIX / "source.twb"), "-o", str(lib)]) == 1
    assert "error:" in capsys.readouterr().err
    assert cli.main(["library", "export", str(LIB_FIX / "source.twb"), "-o", str(lib), "--overwrite",
                     "--field", "Margin Gap"]) == 0
    capsys.readouterr()
    assert cli.main(["library", "show", str(lib)]) == 0
    out = capsys.readouterr().out
    assert "Margin Gap" in out and "[Profit Ratio] - 0.1" in out and "required_by" in out
    assert cli.main(["library", "show", str(lib), "--markdown"]) == 0
    assert capsys.readouterr().out.startswith("# source")


def test_library_import_plan_then_write(tmp_path, capsys):
    lib = tmp_path / "k.library.json"
    assert cli.main(["library", "export", str(LIB_FIX / "source.twb"), "-o", str(lib)]) == 0
    capsys.readouterr()
    target = tmp_path / "t.twb"
    target.write_bytes((LIB_FIX / "target.twb").read_bytes())
    assert cli.main(["library", "import", str(target), str(lib)]) == 0
    cap = capsys.readouterr()
    assert "add-renamed" in cap.out and "nothing written" in cap.err
    assert not (tmp_path / "t_library.twb").exists()
    assert cli.main(["library", "import", str(target), str(lib), "--write"]) == 0
    err = capsys.readouterr().err
    assert "wrote" in err and "added 12" in err
    assert (tmp_path / "t_library.twb").exists()
    # the output exists now, and --on-clash fail stops before writing
    assert cli.main(["library", "import", str(target), str(lib), "--write"]) == 1
    assert "refusing" in capsys.readouterr().err
    assert cli.main(["library", "import", str(target), str(lib), "--on-clash", "fail", "-o", str(tmp_path / "x.twb"),
                     "--write"]) == 1
    assert not (tmp_path / "x.twb").exists()


def test_library_import_exit_code_2_when_an_entry_fails(tmp_path, capsys):
    from lxml import etree
    lib = tmp_path / "k.library.json"
    cli.main(["library", "export", str(LIB_FIX / "source.twb"), "-o", str(lib)])
    doc = etree.parse(str(LIB_FIX / "target.twb"))
    for rec in doc.xpath("//metadata-record[local-name='[Profit]']"):
        rec.getparent().remove(rec)
    target = tmp_path / "t.twb"
    doc.write(str(target), encoding="utf-8", xml_declaration=True)
    capsys.readouterr()
    assert cli.main(["library", "import", str(target), str(lib), "--write"]) == 2
    err = capsys.readouterr().err
    assert "failed 2" in err and "not imported: " in err and "Margin Gap" in err
    assert (tmp_path / "t_library.twb").exists()          # the entries that could be added were


def test_library_errors_exit_1(tmp_path, capsys):
    assert cli.main(["library", "show", str(tmp_path / "missing.json")]) == 1
    bad = tmp_path / "bad.json"
    bad.write_text('{"format": "nope"}')
    assert cli.main(["library", "show", str(bad)]) == 1
    assert "not a py-tbparse library" in capsys.readouterr().err
