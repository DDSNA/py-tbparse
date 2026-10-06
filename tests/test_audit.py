"""`audit`: the workbook rules (A001...) on top of the findings engine, and its CLI.

Every rule has a minimal synthetic workbook that fails it and one that passes it. The corpus run (200 real
workbooks, skipped when they are not fetched) is in `test_audit_corpus.py`.
"""

import json
from xml.sax.saxutils import quoteattr
from pathlib import Path

import pandas as pd
import pytest

from py_tbparse import TwbParser, audit
from py_tbparse.workbook_audit import _cycles, audit_rule_ids, calculation_depths, normalise_formula, _Facts
from py_tbparse.cli import main
from py_tbparse.findings import FINDING_COLUMNS, SEVERITY

RULES = ["A001", "A002", "A003", "A004", "A005", "A006", "A007", "A008", "A009", "A010", "A011"]
PUBLIC = Path(__file__).parent / "fixtures" / "public"


def workbook(tmp_path, calcs=(), params=(), sheets=None, dashboards=None, hidden=(), conn=None, ds_extra="",
             name="wb.twb", ds_caption="Orders", texts=()):
    """A small workbook. `calcs` are (internal name, caption or None, formula[, hidden]); `params` are (internal
    name, caption); `sheets` maps a worksheet to the columns it uses (`[Name]`); `dashboards` maps a dashboard
    to its worksheets; `texts` are extra worksheet XML (a title that shows a parameter)."""
    conn = conn if conn is not None else "<connection class='textscan' directory='Data' filename='sales.csv'/>"
    cols = "".join(
        f"<column datatype='integer' name='{c[0]}'" + (f" caption={quoteattr(c[1])}" if c[1] else "")
        + (" hidden='true'" if len(c) > 3 and c[3] else "")
        + f"><calculation class='tableau' formula={quoteattr(c[2], {chr(10): '&#10;'})}/></column>" for c in calcs)
    pcols = "".join(
        f"<column caption='{p[1]}' datatype='integer' name='{p[0]}' param-domain-type='range' role='measure' "
        f"value='10'><calculation class='tableau' formula='10'/><range min='1' max='50'/></column>" for p in params)
    meta = ("<metadata-records>"
            + "".join(f"<metadata-record class='column'><local-name>[{n}]</local-name><local-type>integer</local-type>"
                      f"</metadata-record>" for n in ("Sales", "Profit"))
            + "</metadata-records>")
    conn_xml = conn.replace("/>", f">{meta}</connection>", 1) if conn.endswith("/>") and "</connection>" not in conn else conn
    sheets = {"Sheet 1": ["[Sales]"]} if sheets is None else sheets
    dashboards = {"Dash": ["Sheet 1"]} if dashboards is None else dashboards
    ws = ""
    for sheet, used in sheets.items():
        deps = "".join(f"<column name='{u}'/>" for u in used)
        ws += (f"<worksheet name='{sheet}'><table><view><datasources><datasource name='ds1'/></datasources>"
               f"<datasource-dependencies datasource='ds1'>{deps}</datasource-dependencies></view></table>"
               f"{''.join(texts)}</worksheet>")
    db = "".join(f"<dashboard name='{d}'><zones>" + "".join(f"<zone id='{i}' name='{s}'/>" for i, s in enumerate(ss))
                 + "</zones></dashboard>" for d, ss in dashboards.items())
    windows = "".join(f"<window class='worksheet' name='{h}' hidden='true'/>" for h in hidden)
    xml = (f"<?xml version='1.0' encoding='utf-8'?><workbook version='18.1'><datasources>"
           f"<datasource name='ds1' caption='{ds_caption}'>{conn_xml}{cols}{ds_extra}</datasource>"
           f"<datasource name='Parameters' hasconnection='false'>{pcols}</datasource></datasources>"
           f"<worksheets>{ws}</worksheets><dashboards>{db}</dashboards><windows>{windows}</windows></workbook>")
    path = tmp_path / name
    path.write_text(xml, encoding="utf-8")
    return str(path)


def found(path, rule):
    return audit(path, only=rule)


def objects(df):
    return list(df["object"])


def test_rule_ids_are_the_documented_ones():
    assert audit_rule_ids() == RULES


def test_every_rule_has_a_title_and_a_fix():
    from py_tbparse.findings import rules
    for r in rules("workbook"):
        assert r.title and r.fix and r.severity in SEVERITY, r.id


def test_a_clean_workbook_has_no_findings(tmp_path):
    path = workbook(tmp_path, calcs=[("[Calculation_1]", "Margin", "[Sales] - [Profit]")],
                    sheets={"Sheet 1": ["[Calculation_1]"]})
    df = audit(path)
    assert list(df.columns) == FINDING_COLUMNS
    assert df.empty and df.attrs["crashed"] == []


# A001 ---------------------------------------------------------------------------------------------------------

def test_a001_unused_calculation(tmp_path):
    path = workbook(tmp_path, calcs=[("[Calculation_1]", "Margin", "[Sales] - [Profit]"),
                                     ("[Calculation_2]", "Used", "[Sales] * 2")],
                    sheets={"Sheet 1": ["[Calculation_2]"]})
    df = found(path, "A001")
    assert objects(df) == ["Orders: Margin"] and df.iloc[0]["severity"] == "info"


def test_a001_used_through_another_calculation_is_used(tmp_path):
    path = workbook(tmp_path, calcs=[("[Calculation_1]", "Inner", "[Sales] * 2"),
                                     ("[Calculation_2]", "Outer", "[Calculation_1] + 1")],
                    sheets={"Sheet 1": ["[Calculation_2]"]})
    assert found(path, "A001").empty


def test_a001_names_the_calculation_that_only_refers_to_it(tmp_path):
    path = workbook(tmp_path, calcs=[("[Calculation_1]", "Inner", "[Sales] * 2"),
                                     ("[Calculation_2]", "Outer", "[Calculation_1] + 1")])
    df = found(path, "A001")
    assert objects(df) == ["Orders: Inner", "Orders: Outer"]
    assert "Outer" in df.iloc[0]["detail"] and "no worksheet uses those" in df.iloc[0]["detail"]


def test_a001_a_hidden_calculation_is_left_alone(tmp_path):
    path = workbook(tmp_path, calcs=[("[Calculation_1]", "Quiet", "[Sales] * 2", True)])
    assert found(path, "A001").empty


def test_a001_a_name_an_action_or_title_mentions_is_used(tmp_path):
    path = workbook(tmp_path, calcs=[("[Calculation_1]", "Shown", "[Sales] * 2")],
                    texts=["<title><formatted-text><run>&lt;[ds1].[Calculation_1]&gt;</run></formatted-text></title>"])
    assert found(path, "A001").empty


# A002 ---------------------------------------------------------------------------------------------------------

def test_a002_duplicate_calculations(tmp_path):
    path = workbook(tmp_path, calcs=[("[Calculation_1]", "Margin", "[Sales] - [Profit]"),
                                     ("[Calculation_2]", "Margin copy", "[Sales]-/* same */ [Profit] // again")])
    df = found(path, "A002")
    assert objects(df) == ["Orders: Margin", "Orders: Margin copy"]
    assert df.iloc[0]["severity"] == "warning" and "Margin copy" in df.iloc[0]["detail"]


def test_a002_different_formulas_and_constants_are_quiet(tmp_path):
    path = workbook(tmp_path, calcs=[("[Calculation_1]", "A", "[Sales] - [Profit]"),
                                     ("[Calculation_2]", "B", "[Profit] - [Sales]"),
                                     ("[Calculation_3]", "One", "1"), ("[Calculation_4]", "Uno", "1")])
    assert found(path, "A002").empty


@pytest.mark.parametrize("a,b,same", [
    ("IF [Sales] > 0 THEN 1 ELSE 0 END", "if [Sales]>0\n  then 1\r\nelse 0 end", True),
    ("[Sales] // note", "[Sales]", True),
    ("[Sales] /* a\nb */ + 1", "[Sales]+1", True),
    ("IF [A] = 'x y' THEN 1 END", "IF [A] = 'x  y' THEN 1 END", False),     # string literals are kept as written
    ("IF [A] = 'X' THEN 1 END", "IF [A] = 'x' THEN 1 END", False),
    ("[Sales]", "[sales]", False),                                            # names are kept as written
    ("'// not a comment' + [A]", "'// not a comment' + [A]", True),
])
def test_normalise_formula(a, b, same):
    assert (normalise_formula(a) == normalise_formula(b)) is same


# A003 ---------------------------------------------------------------------------------------------------------

def test_a003_missing_reference_is_an_error(tmp_path):
    path = workbook(tmp_path, calcs=[("[Calculation_1]", "Broken", "[Sales] + [Gone]")])
    df = found(path, "A003")
    assert objects(df) == ["Orders: Broken"] and df.iloc[0]["severity"] == "error"
    assert "[Gone]" in df.iloc[0]["detail"]


def test_a003_existing_fields_and_string_literals_are_quiet(tmp_path):
    path = workbook(tmp_path, calcs=[("[Calculation_1]", "Fine", "IF [Sales] > 0 THEN 'see [Nothing]' END")])
    assert found(path, "A003").empty


# A004 ---------------------------------------------------------------------------------------------------------

def test_a004_circular_dependency(tmp_path):
    path = workbook(tmp_path, calcs=[("[Calculation_1]", "A", "[Calculation_2] + 1"),
                                     ("[Calculation_2]", "B", "[Calculation_3] + 1"),
                                     ("[Calculation_3]", "C", "[Calculation_1] + 1"),
                                     ("[Calculation_4]", "Fine", "[Sales]")])
    df = found(path, "A004")
    assert objects(df) == ["Orders: A", "Orders: B", "Orders: C"]
    assert df.iloc[0]["severity"] == "error" and "A, B, C" in df.iloc[0]["detail"]


def test_a004_self_reference_and_no_cycle(tmp_path):
    path = workbook(tmp_path, calcs=[("[Calculation_1]", "Self", "[Calculation_1] + 1"),
                                     ("[Calculation_2]", "Chain", "[Calculation_3] + 1"),
                                     ("[Calculation_3]", "End", "[Sales]")])
    df = found(path, "A004")
    assert objects(df) == ["Orders: Self"] and df.iloc[0]["detail"] == "refers to itself"


def test_cycles_finds_components_in_a_stable_order():
    graph = {"a": ["b"], "b": ["a"], "c": ["c"], "d": ["a"], "e": []}
    assert _cycles(graph) == [["a", "b"], ["c"]]


def test_a004_a_long_chain_does_not_exhaust_the_stack():
    graph = {i: [i + 1] for i in range(5000)}
    graph[5000] = []
    assert _cycles(graph) == []


# A005 ---------------------------------------------------------------------------------------------------------

def test_a005_unused_parameter(tmp_path):
    path = workbook(tmp_path, params=[("[Parameter 1]", "Top N")])
    df = found(path, "A005")
    assert objects(df) == ["Parameters: Top N"] and df.iloc[0]["severity"] == "info"


def test_a005_parameter_used_in_a_calculation_a_sheet_uses_is_used(tmp_path):
    path = workbook(tmp_path, params=[("[Parameter 1]", "Top N")],
                    calcs=[("[Calculation_1]", "Scaled", "[Sales] * [Parameters].[Parameter 1]")],
                    sheets={"Sheet 1": ["[Calculation_1]"]})
    assert found(path, "A005").empty


def test_a005_parameter_on_a_sheet_or_in_a_title_is_used(tmp_path):
    on_sheet = workbook(tmp_path, params=[("[Parameter 1]", "Top N")],
                        sheets={"Sheet 1": ["[Sales]"]}, name="a.twb",
                        texts=["<title><run>&lt;[Parameters].[Parameter 1]&gt;</run></title>"])
    assert found(on_sheet, "A005").empty


# A006 ---------------------------------------------------------------------------------------------------------

def test_a006_sheet_in_no_dashboard(tmp_path):
    path = workbook(tmp_path, sheets={"Sheet 1": ["[Sales]"], "Loose": ["[Sales]"]})
    df = found(path, "A006")
    assert objects(df) == ["Loose"] and df.iloc[0]["severity"] == "info"


def test_a006_hidden_sheet_and_story_sheet_are_quiet(tmp_path):
    path = workbook(tmp_path, sheets={"Sheet 1": ["[Sales]"], "Quiet": ["[Sales]"], "Told": ["[Sales]"]},
                    hidden=["Quiet"], ds_extra="")
    text = Path(path).read_text(encoding="utf-8").replace(
        "</workbook>", "<stories><story name='S'><story-points><story-point captured-sheet='Told'/></story-points></story></stories></workbook>")
    Path(path).write_text(text, encoding="utf-8")
    assert found(path, "A006").empty


# A007 ---------------------------------------------------------------------------------------------------------

SQL = ("<connection class='sqlserver' server='db.example.com' dbname='Sales'>"
       "<relation connection='sqlserver.1' name='Custom SQL Query' type='text'>"
       "SELECT order_id,   customer,\n  amount FROM dbo.orders WHERE password=hunter2 AND region = 'EU' ORDER BY 1 -- and more text after the limit"
       "</relation></connection>")


def test_a007_custom_sql_is_listed_with_its_first_80_characters_and_no_secret(tmp_path):
    path = workbook(tmp_path, conn=SQL)
    df = found(path, "A007")
    assert objects(df) == ["Orders: Custom SQL Query"]
    detail = df.iloc[0]["detail"]
    assert detail.startswith("SELECT order_id, customer, amount FROM dbo.orders WHERE password=***") or "hunter2" not in detail
    assert "hunter2" not in detail and len(detail) <= 83 and detail.endswith("...")


def test_a007_plain_table_is_quiet_and_formula_attribute_form_is_found(tmp_path):
    table = workbook(tmp_path, conn="<connection class='sqlserver'><relation name='t' table='[dbo].[t]' type='table'/></connection>")
    assert found(table, "A007").empty
    formula = workbook(tmp_path, name="f.twb", conn="<connection class='odbc'><relation name='q' type='table' formula='select 1 as x'/></connection>")
    assert objects(found(formula, "A007")) == ["Orders: q"]


# A008 ---------------------------------------------------------------------------------------------------------

def test_a008_extract_and_absolute_paths(tmp_path):
    path = workbook(tmp_path, conn="<connection class='excel-direct' filename='C:\\Users\\alice\\Desktop\\sales.xlsx'/>",
                    ds_extra="<extract enabled='true'><connection class='hyper' dbname='/home/alice/x.hyper'/></extract>")
    df = found(path, "A008")
    text = " ".join(df["detail"])
    assert len(df) == 1 and df.iloc[0]["severity"] == "info"       # one finding per datasource
    assert "extract is a file at an absolute local path" in text and "absolute filename (sales.xlsx)" in text
    assert "alice" not in text and "Desktop" not in text      # the folder is never printed


def test_a008_an_extract_alone_or_with_a_relative_path_is_quiet(tmp_path):
    # every extract workbook has an extract; only a path on one machine is a leftover
    plain = workbook(tmp_path, ds_extra="<extract enabled='true'><connection class='hyper' dbname='Data/Extracts/x.hyper'/></extract>")
    assert found(plain, "A008").empty
    bare = workbook(tmp_path, name="b.twb", ds_extra="<extract enabled='true'/>")
    assert found(bare, "A008").empty


def test_a008_a_temporary_extract_file_is_named_as_such(tmp_path):
    path = workbook(tmp_path, ds_extra="<extract enabled='true'><connection class='hyper' "
                                       "dbname='C:/Users/bob/AppData/Local/Temp/TableauTemp/#t.hyper'/></extract>")
    df = found(path, "A008")
    assert len(df) == 1 and "temporary file" in df.iloc[0]["detail"] and "bob" not in df.iloc[0]["detail"]


def test_a008_relative_paths_are_quiet(tmp_path):
    assert found(workbook(tmp_path), "A008").empty


# A009 ---------------------------------------------------------------------------------------------------------

def test_a009_default_names(tmp_path):
    path = workbook(tmp_path, calcs=[("[Calculation_111]", None, "[Sales]"), ("[Calculation_222]", "Calculation1", "[Profit]"),
                                     ("[Calculation_333]", "Margin", "[Sales] - [Profit]"),
                                     ("[Calculation_444]", "Calculation of margin", "[Sales] * [Profit]")])
    df = found(path, "A009")
    assert objects(df) == ["Orders: Calculation1", "Orders: Calculation_111"]


# A010 ---------------------------------------------------------------------------------------------------------

def _chain(n):
    calcs = [("[Calculation_1]", "L1", "[Sales]")]
    calcs += [(f"[Calculation_{i}]", f"L{i}", f"[Calculation_{i - 1}] + 1") for i in range(2, n + 1)]
    return calcs


def test_a010_deep_chain_over_five(tmp_path):
    path = workbook(tmp_path, calcs=_chain(7))
    df = found(path, "A010")
    assert objects(df) == ["Orders: L6", "Orders: L7"]
    assert "7 calculations" in df.iloc[1]["detail"]


def test_a010_five_deep_is_quiet(tmp_path):
    assert found(workbook(tmp_path, calcs=_chain(5)), "A010").empty


def test_calculation_depths_on_a_diamond_and_a_cycle(tmp_path):
    path = workbook(tmp_path, calcs=[("[Calculation_1]", "Base", "[Sales]"),
                                     ("[Calculation_2]", "Left", "[Calculation_1]"),
                                     ("[Calculation_3]", "Right", "[Calculation_1]"),
                                     ("[Calculation_4]", "Top", "[Calculation_2] + [Calculation_3]"),
                                     ("[Calculation_5]", "Loop1", "[Calculation_6]"),
                                     ("[Calculation_6]", "Loop2", "[Calculation_5] + [Calculation_1]")])
    depth = calculation_depths(_Facts(TwbParser(path)))
    by = {k[1]: v for k, v in depth.items()}
    assert by == {"[Calculation_1]": 1, "[Calculation_2]": 2, "[Calculation_3]": 2, "[Calculation_4]": 3,
                  "[Calculation_5]": 1, "[Calculation_6]": 2}


# A011 ---------------------------------------------------------------------------------------------------------

def test_a011_long_formula(tmp_path):
    long = "[Sales] + " + " + ".join(["1"] * 400)
    path = workbook(tmp_path, calcs=[("[Calculation_1]", "Long", long), ("[Calculation_2]", "Short", "[Sales]")])
    df = found(path, "A011")
    assert objects(df) == ["Orders: Long"] and f"{len(long)} characters" in df.iloc[0]["detail"]
    assert "1 + 1" not in df.iloc[0]["detail"]        # the formula itself is never echoed


# engine and CLI -----------------------------------------------------------------------------------------------

def test_the_same_workbook_gives_the_same_frame(tmp_path):
    path = workbook(tmp_path, calcs=[("[Calculation_1]", "A", "[Sales]"), ("[Calculation_2]", "B", "[Sales]")],
                    params=[("[Parameter 1]", "P")])
    pd.testing.assert_frame_equal(audit(path), audit(path))


def test_audit_takes_a_parser_and_a_twbx_and_never_leaks_the_path():
    df = audit(TwbParser(str(PUBLIC / "Cache.twbx")))
    assert list(df.columns) == FINDING_COLUMNS
    assert "/home" not in df.to_string()


def test_only_skip_and_unknown_ids(tmp_path):
    path = workbook(tmp_path, calcs=[("[Calculation_1]", "A", "[Sales]")])
    assert set(audit(path, only=["A009", "A001"])["rule"]) <= {"A001", "A009"}
    assert "A001" not in set(audit(path, skip="A001")["rule"])
    with pytest.raises(ValueError, match="unknown rule A999"):
        audit(path, only="A999")
    with pytest.raises(ValueError):
        audit(path, only="T001")                   # a template rule is not a workbook rule


def test_a_rule_that_crashes_becomes_an_error_finding(tmp_path, monkeypatch):
    path = workbook(tmp_path)
    import py_tbparse.workbook_audit as audit_module
    monkeypatch.setattr(audit_module, "normalise_formula", lambda f: 1 / 0)
    path = workbook(tmp_path, calcs=[("[Calculation_1]", "A", "[Sales]")], name="c.twb")
    df = audit(path, only="A002")
    assert df.attrs["crashed"] == ["A002"] and df.iloc[0]["severity"] == "error"


def test_cli_exit_codes_and_formats(tmp_path, capsys):
    path = workbook(tmp_path, calcs=[("[Calculation_1]", "Broken", "[Sales] + [Gone]")])
    assert main(["audit", path]) == 1                                 # an error finding, --fail-on error
    out = capsys.readouterr()
    assert "A003" in out.out and "1 error" in out.err
    assert main(["audit", path, "--fail-on", "never"]) == 0
    assert main(["audit", path, "--skip", "A003", "--fail-on", "warning"]) == 0   # only info findings left
    assert main(["audit", path, "--skip", "A003", "--fail-on", "info"]) == 1
    capsys.readouterr()
    assert main(["audit", path, "--format", "json", "--fail-on", "never"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert {"rule", "severity", "object", "detail", "fix"} <= set(data[0])
    assert main(["audit", path, "--format", "csv", "--only", "A003", "--fail-on", "never"]) == 0
    assert capsys.readouterr().out.startswith("rule,severity,object,detail,fix")


def test_cli_errors_are_exit_2(tmp_path, capsys):
    assert main(["audit", str(tmp_path / "missing.twb")]) == 2
    path = workbook(tmp_path)
    assert main(["audit", path, "--only", "A999"]) == 2
    assert main(["audit", path, "--only", " "]) == 2
    bad = tmp_path / "bad.twb"
    bad.write_text("not xml", encoding="utf-8")
    assert main(["audit", str(bad)]) == 2
    assert "error:" in capsys.readouterr().err


def test_cli_exit_3_when_a_rule_crashes(tmp_path, monkeypatch, capsys):
    import py_tbparse.workbook_audit as audit_module
    monkeypatch.setattr(audit_module, "normalise_formula", lambda f: 1 / 0)
    path = workbook(tmp_path, calcs=[("[Calculation_1]", "A", "[Sales]")])
    assert main(["audit", path, "--fail-on", "never"]) == 3
    assert "rule A002 crashed" in capsys.readouterr().err


def test_cli_output_file_and_help_lists_the_rules(tmp_path, capsys):
    path = workbook(tmp_path, calcs=[("[Calculation_1]", "A", "[Sales]")])
    out = tmp_path / "f.csv"
    assert main(["audit", path, "-f", "csv", "-o", str(out), "--fail-on", "never"]) == 0
    assert out.read_text(encoding="utf-8").startswith("rule,severity")
    with pytest.raises(SystemExit):
        main(["audit", "--help"])
    help_text = capsys.readouterr().out
    assert all(r in help_text for r in RULES)


def test_a_folder_named_audit_or_docs_does_not_hide_the_command(tmp_path, monkeypatch, capsys):
    path = workbook(tmp_path)
    (tmp_path / "docs").mkdir()
    (tmp_path / "audit").mkdir()
    monkeypatch.chdir(tmp_path)
    assert main(["audit", path]) == 0
    assert main(["docs", path, "-o", str(tmp_path / "out.md")]) == 0


def test_a005_parameter_only_an_unused_calculation_uses_is_reported(tmp_path):
    path = workbook(tmp_path, params=[("[Parameter 1]", "Top N")],
                    calcs=[("[Calculation_1]", "Scaled", "[Sales] * [Parameters].[Parameter 1]")])
    df = found(path, "A005")
    assert objects(df) == ["Parameters: Top N"] and "Scaled" in df.iloc[0]["detail"]


# tuning: false positives found in the corpus -------------------------------------------------------------------

def test_a001_the_number_of_records_tableau_adds_is_not_reported(tmp_path):
    auto = ("<column datatype='integer' name='[Number of Records]' role='measure' type='quantitative' "
            "xmlns:user='http://www.tableausoftware.com/xml/user' user:auto-column='numrec'>"
            "<calculation class='tableau' formula='1'/></column>")
    stripped = ("<column datatype='integer' name='[Number of Records]' role='measure' type='quantitative'>"
                "<calculation class='tableau' formula='1'/></column>")
    for n, extra in enumerate((auto, stripped)):
        path = workbook(tmp_path, name=f"n{n}.twb", ds_extra=extra)
        assert found(path, "A001").empty
    # a calculation the author wrote with the same shape is still reported
    path = workbook(tmp_path, name="own.twb", calcs=[("[Calculation_9]", "Number of Rows", "1")])
    assert objects(found(path, "A001")) == ["Orders: Number of Rows"]


def test_a001_and_a005_say_nothing_about_a_workbook_with_no_worksheets(tmp_path):
    path = workbook(tmp_path, calcs=[("[Calculation_1]", "Margin", "[Sales] - [Profit]")], params=[("[Parameter 1]", "Cut")],
                    sheets={}, dashboards={})
    assert found(path, "A001").empty and found(path, "A005").empty


def test_a005_a_parameter_a_bin_a_set_or_a_shown_control_uses(tmp_path):
    shown = workbook(tmp_path, name="s.twb", params=[("[Parameter 1]", "Top N")])
    assert objects(found(shown, "A005")) == ["Parameters: Top N"]
    shown_xml = Path(shown).read_text(encoding="utf-8").replace(
        "<windows>", "<windows><window class='worksheet' name='Sheet 1'><viewpoint><card mode='slider' "
                     "param='[Parameters].[Parameter 1]' type='parameter'/></viewpoint></window>")
    Path(shown).write_text(shown_xml, encoding="utf-8")
    assert found(shown, "A005").empty                              # the control is on a sheet

    bin_col = ("<column datatype='integer' name='[Sales (bin)]' role='dimension' type='ordinal'>"
               "<calculation class='bin' formula='[Sales]' size-parameter='[Parameters].[Parameter 1]'/></column>")
    unused_bin = workbook(tmp_path, name="b.twb", params=[("[Parameter 1]", "Bin size")], ds_extra=bin_col)
    df = found(unused_bin, "A005")
    assert len(df) == 1 and "Sales (bin)" in df.iloc[0]["detail"]   # only an unused bin uses it: still reported
    used_bin = workbook(tmp_path, name="ub.twb", params=[("[Parameter 1]", "Bin size")], ds_extra=bin_col,
                        sheets={"Sheet 1": ["[Sales (bin)]"]})
    assert found(used_bin, "A005").empty

    top_set = ("<group name='[Top Sales]' name-style='unqualified'><groupfilter count='[Parameters].[Parameter 1]' "
               "end='top' function='end' units='records'/></group>")
    used_set = workbook(tmp_path, name="us.twb", params=[("[Parameter 1]", "Top N")], ds_extra=top_set,
                        sheets={"Sheet 1": ["[Top Sales]"]})
    assert found(used_set, "A005").empty


def test_a003_names_only_the_connection_or_a_blend_declares_are_known(tmp_path):
    cols = ("<cols><map key='[SalesAmount]' value='[Extract].[SalesAmount]'/></cols>")
    path = workbook(tmp_path, calcs=[("[Calculation_1]", "Total", "SUM([SalesAmount])")],
                    conn=f"<connection class='csv'>{cols}</connection>")
    assert found(path, "A003").empty
    missing = workbook(tmp_path, name="m.twb", calcs=[("[Calculation_1]", "Total", "SUM([Gone])")])
    assert len(found(missing, "A003")) == 1
    # a field of a secondary datasource that the primary's own dependencies declare
    blend = Path(workbook(tmp_path, name="bl.twb", calcs=[("[Calculation_1]", "Diff", "SUM([ds2].[Quote])")]))
    blend.write_text(blend.read_text(encoding="utf-8").replace(
        "</datasources>", "<datasource name='ds2' caption='Targets'/></datasources>").replace(
        "<datasource name='ds1' caption='Orders'>", "<datasource name='ds1' caption='Orders'><datasource-dependencies "
        "datasource='ds2'><column datatype='integer' name='[Quote]'/></datasource-dependencies>"), encoding="utf-8")
    assert found(str(blend), "A003").empty


def test_a006_a_workbook_of_plain_sheets_has_no_dashboard_to_miss(tmp_path):
    path = workbook(tmp_path, sheets={"A": ["[Sales]"], "B": ["[Sales]"]}, dashboards={})
    assert found(path, "A006").empty


def test_a006_tooltip_sheets_typed_zones_and_named_leaf_zones_count_as_shown(tmp_path):
    tip = ("<customized-tooltip><formatted-text><run><![CDATA[<Sheet name=\"Tip\" maxwidth=\"100\" "
           "maxheight=\"100\" filter=\"<All Fields>\">]]></run></formatted-text></customized-tooltip>")
    path = workbook(tmp_path, sheets={"Sheet 1": ["[Sales]"], "Tip": ["[Sales]"], "Lonely": ["[Sales]"]},
                    texts=[tip], dashboards={"Dash": ["Sheet 1"]})
    assert objects(found(path, "A006")) == ["Lonely"]                # Tip is embedded in a tooltip

    typed = Path(workbook(tmp_path, name="t.twb", sheets={"S1": ["[Sales]"], "S2": ["[Sales]"], "S3": ["[Sales]"]},
                          dashboards={"Dash": []}))
    typed.write_text(typed.read_text(encoding="utf-8").replace(
        "<zones></zones>", "<zones><zone id='1' name='S1' type='sheet'/><zone id='2' name='S2' type-v2='worksheet'/>"
                           "<zone id='3' name='S3' type-v2='layout-basic'/></zones>"), encoding="utf-8")
    assert found(str(typed), "A006").empty
