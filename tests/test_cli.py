import json

import pytest

from twbparser_py import cli


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
    assert out.splitlines()[0].startswith("datasource,")


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
    assert content.splitlines()[0].startswith("datasource,")


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
    assert out.startswith("digraph twb {")
    assert "Sheet1" in out


def test_graph_output_to_file(wenjie_path, tmp_path):
    out_file = tmp_path / "graph.dot"
    rc = cli.main([wenjie_path, "graph", "--output", str(out_file)])
    assert rc == 0
    assert out_file.read_text().startswith("digraph twb {")


def test_new_v2_tables_are_listed(capsys):
    rc = cli.main(["ignored.twb", "tables"])
    out = capsys.readouterr().out
    assert rc == 0
    for name in ("custom-sql", "initial-sql", "published-refs"):
        assert name in out
