"""CI output formats (py_tbparse/ci_formats.py): JUnit, SARIF 2.1.0 and GitHub commands for
`validate`, `template check` and `audit`, and the exit codes that must not change."""

import json
import shutil
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).parent))
from test_audit import workbook  # noqa: E402

from py_tbparse import TwbParser, ci_formats, findings  # noqa: E402
from py_tbparse.cli import main  # noqa: E402
from py_tbparse.findings import FINDING_COLUMNS, format_findings  # noqa: E402
from py_tbparse.templates import make_template  # noqa: E402
from py_tbparse.validators import validation_findings  # noqa: E402

PUBLIC = Path(__file__).parent / "fixtures" / "public"


def frame(rows, **attrs):
    df = pd.DataFrame(rows, columns=FINDING_COLUMNS)
    df.attrs.update({"crashed": [], "tracebacks": {}, "scope": "workbook", "path": "wb.twb", **attrs})
    return df


ROWS = [
    ("A003", "error", "[Calc]", "refers to [Gone]", "fix it"),
    ("A001", "warning", "[Old]", "unused", ""),
    ("A005", "info", "P", "unused parameter", "delete it"),
]


@pytest.fixture
def broken(tmp_path):
    return workbook(tmp_path, calcs=[("[Calculation_1]", "Broken", "[Sales] + [Gone]")])


@pytest.fixture
def template(tmp_path):
    src = tmp_path / "filtering.twb"
    shutil.copy(PUBLIC / "filtering.twb", src)
    return make_template(str(src))


# ---------------------------------------------------------------- JUnit --

def test_junit_is_well_formed_and_counts_severities():
    root = ET.fromstring(format_findings(frame(ROWS), "junit"))
    assert root.tag == "testsuites"
    suite = root.find("testsuite")
    assert (suite.get("tests"), suite.get("failures"), suite.get("errors"), suite.get("skipped")) == ("3", "1", "0", "2")
    cases = suite.findall("testcase")
    assert [c.get("classname") for c in cases] == ["A003", "A001", "A005"]
    assert cases[0].find("failure").get("type") == "A003"
    assert "refers to [Gone]" in cases[0].find("failure").get("message")
    assert cases[1].find("skipped").get("message").startswith("warning:")
    assert cases[0].get("file") == "wb.twb"


def test_junit_no_findings_is_one_passing_case():
    suite = ET.fromstring(format_findings(frame([]), "junit")).find("testsuite")
    cases = suite.findall("testcase")
    assert len(cases) == 1 and list(cases[0]) == [] and suite.get("failures") == "0"


def test_junit_crashed_rule_is_an_error_element():
    df = frame([("A002", "error", "", "rule failed: ZeroDivisionError", "report this as a bug")], crashed=["A002"])
    suite = ET.fromstring(format_findings(df, "junit")).find("testsuite")
    assert suite.get("errors") == "1" and suite.get("failures") == "0"
    assert suite.find("testcase/error") is not None


def test_junit_survives_xml_special_and_control_characters():
    df = frame([("A003", "error", "<a & \"b\">", "bad \x00\x08 char ]]> and \ud800 <tag>", "")])
    case = ET.fromstring(format_findings(df, "junit")).find("testsuite/testcase")
    assert case.get("name") == "<a & \"b\">"
    assert "<tag>" in case.find("failure").get("message") and "\x00" not in case.find("failure").get("message")


# ---------------------------------------------------------------- SARIF --

def check_sarif_structure(text, scope, expected_results):
    """The parts of the SARIF 2.1.0 schema a consumer (GitHub code scanning) needs; there is no
    jsonschema package here, so the required keys and types are checked by hand."""
    log = json.loads(text)
    assert log["version"] == "2.1.0" and log["$schema"].endswith("sarif-2.1.0.json")
    assert isinstance(log["runs"], list) and len(log["runs"]) == 1
    run = log["runs"][0]
    driver = run["tool"]["driver"]
    assert driver["name"] == "py-tbparse" and driver["version"]
    rules = driver["rules"]
    ids = [r["id"] for r in rules]
    assert len(ids) == len(set(ids)) and ids == sorted(ids)
    assert ids == [r["id"] for r in ci_formats.catalog(scope)]
    for r in rules:
        assert r["shortDescription"]["text"]
        assert r["defaultConfiguration"]["level"] in ("error", "warning", "note", "none")
    assert len(run["results"]) == expected_results
    for res in run["results"]:
        assert res["level"] in ("error", "warning", "note")
        assert rules[res["ruleIndex"]]["id"] == res["ruleId"]
        assert res["message"]["text"]
        loc = res["locations"][0]["physicalLocation"]
        assert loc["artifactLocation"]["uri"]
        assert loc["region"]["startLine"] >= 1
    return run


def test_sarif_levels_rules_and_location():
    run = check_sarif_structure(format_findings(frame(ROWS), "sarif"), "workbook", 3)
    assert [r["level"] for r in run["results"]] == ["error", "warning", "note"]
    assert {r["locations"][0]["physicalLocation"]["artifactLocation"]["uri"] for r in run["results"]} == {"wb.twb"}
    assert run["results"][0]["properties"]["object"] == "[Calc]"
    assert {r["id"] for r in run["tool"]["driver"]["rules"]} >= {"A001", "A003", "A005", "A011"}


def test_sarif_no_findings_still_lists_the_rules():
    run = check_sarif_structure(format_findings(frame([]), "sarif"), "workbook", 0)
    assert run["results"] == [] and run["tool"]["driver"]["rules"]


def test_sarif_uri_is_a_forward_slash_reference():
    log = json.loads(format_findings(frame(ROWS[:1]), "sarif", path="dir\\my book.twb"))
    assert log["runs"][0]["results"][0]["locations"][0]["physicalLocation"]["artifactLocation"]["uri"] == "dir/my%20book.twb"


def test_sarif_keeps_a_rule_the_catalog_does_not_know():
    df = frame([("Z999", "error", "o", "d", "")])
    run = json.loads(format_findings(df, "sarif"))["runs"][0]
    assert run["results"][0]["ruleId"] == "Z999"
    assert run["tool"]["driver"]["rules"][run["results"][0]["ruleIndex"]]["id"] == "Z999"


# --------------------------------------------------------------- GitHub --

def test_github_commands_and_escaping():
    df = frame([("A003", "error", "[Calc]", "100% bad\nsecond line\r", "fix: it, now"),
                ("A001", "warning", "", "unused", ""),
                ("A005", "info", "P", "note", "")])
    lines = format_findings(df, "github", path="a,b:c.twb").splitlines()
    assert lines[0].startswith("::error file=a%2Cb%3Ac.twb,title=A003::")
    assert "100%25 bad%0Asecond line%0D" in lines[0] and "\n" not in lines[0]
    assert lines[1] == "::warning file=a%2Cb%3Ac.twb,title=A001::unused"
    assert lines[2].startswith("::notice ")
    assert len(lines) == 3


def test_github_no_findings_is_empty():
    assert format_findings(frame([]), "github") == ""


def test_unknown_ci_format_is_a_value_error():
    with pytest.raises(ValueError, match="unknown"):
        format_findings(frame([]), "xml")
    with pytest.raises(ValueError, match="unknown CI format"):
        ci_formats.render(frame([]), "xml")


# ---------------------------------------------------------- audit (CLI) --

def run_cli(argv, capsys):
    rc = main(argv)
    out = capsys.readouterr()
    return rc, out.out, out.err


def test_audit_formats_and_exit_codes(broken, capsys):
    rc, out, err = run_cli(["audit", broken, "--format", "junit"], capsys)
    assert rc == 1 and "1 error" in err
    suite = ET.fromstring(out).find("testsuite")
    assert int(suite.get("failures")) >= 1
    assert any(c.get("classname") == "A003" for c in suite.findall("testcase"))

    rc, out, _ = run_cli(["audit", broken, "--format", "sarif"], capsys)
    assert rc == 1
    run = check_sarif_structure(out, "workbook", len(json.loads(out)["runs"][0]["results"]))
    uris = {r["locations"][0]["physicalLocation"]["artifactLocation"]["uri"] for r in run["results"]}
    assert uris == {Path(broken).as_posix()} and any(r["ruleId"] == "A003" for r in run["results"])

    rc, out, _ = run_cli(["audit", broken, "--format", "github", "--fail-on", "never"], capsys)
    assert rc == 0
    assert any(l.startswith("::error ") and "title=A003" in l for l in out.splitlines())
    assert all(l.startswith(("::error ", "::warning ", "::notice ")) for l in out.splitlines())

    rc, _, _ = run_cli(["audit", broken, "--format", "sarif", "--skip", "A003", "--fail-on", "warning"], capsys)
    assert rc == 0


def test_audit_output_file_and_errors_keep_their_exit_codes(broken, tmp_path, capsys):
    target = tmp_path / "audit.sarif"
    assert main(["audit", broken, "--format", "sarif", "-o", str(target)]) == 1
    json.loads(target.read_text(encoding="utf-8"))
    assert main(["audit", str(tmp_path / "missing.twb"), "--format", "junit"]) == 2
    assert main(["audit", broken, "--format", "sarif", "--only", "A999"]) == 2


def test_audit_crashed_rule_exits_3_in_every_format(broken, monkeypatch, capsys):
    import py_tbparse.workbook_audit as audit_module
    monkeypatch.setattr(audit_module, "normalise_formula", lambda f: 1 / 0)
    for fmt in ("junit", "sarif", "github"):
        rc, out, err = run_cli(["audit", broken, "--only", "A002", "--format", fmt, "--fail-on", "never"], capsys)
        assert rc == 3 and "A002" in out and "crashed" in err
    suite = ET.fromstring(run_cli(["audit", broken, "--only", "A002", "--format", "junit"], capsys)[1]).find("testsuite")
    assert suite.get("errors") == "1"


# ------------------------------------------------------ template check --

def test_template_check_formats_and_exit_codes(template, capsys):
    rc, out, _ = run_cli(["template", "check", template, "--format", "junit"], capsys)
    assert rc == 0                                           # warnings only, --fail-on error
    suite = ET.fromstring(out).find("testsuite")
    assert suite.get("name") == "py-tbparse template check"
    assert suite.get("failures") == "0" and int(suite.get("skipped")) >= 1

    rc, out, _ = run_cli(["template", "check", template, "--format", "sarif", "--fail-on", "warning"], capsys)
    assert rc == 1
    run = check_sarif_structure(out, "template", len(json.loads(out)["runs"][0]["results"]))
    assert len(run["tool"]["driver"]["rules"]) == 10
    assert {r["ruleId"] for r in run["results"]} >= {"T001"}
    assert {r["locations"][0]["physicalLocation"]["artifactLocation"]["uri"] for r in run["results"]} == {Path(template).as_posix()}

    rc, out, _ = run_cli(["template", "check", template, "--format", "github", "--only", "T001"], capsys)
    assert rc == 0 and out.startswith("::warning file=") and "title=T001" in out


def test_template_check_unreadable_is_exit_2(tmp_path, capsys):
    assert main(["template", "check", str(tmp_path / "nope.twbx"), "--format", "sarif"]) == 2


# ------------------------------------------------------------ validate --

def _broken_result():
    rels = pd.DataFrame([{"left_table": "Orders", "right_table": "Ghost", "left_field": "ID", "right_field": "ID"}])
    fields = rels.assign(left_ok=False, right_ok=True)[["left_table", "left_field", "right_table", "right_field", "left_ok", "right_ok"]]
    return {"ok": False, "issues": {"unknown_tables": rels, "unknown_fields": fields}}


def test_validation_findings_frame():
    df = validation_findings(_broken_result(), "wb.twb")
    assert list(df.columns) == FINDING_COLUMNS
    assert list(df["rule"]) == ["V001", "V002"] and set(df["severity"]) == {"error"}
    assert df.attrs["scope"] == "validate" and df.attrs["path"] == "wb.twb"
    assert validation_findings({"ok": True, "issues": {}}).empty


def test_validate_ci_formats_keep_exit_codes(wenjie_path, monkeypatch, capsys):
    rc, out, _ = run_cli([wenjie_path, "validate", "--format", "junit"], capsys)
    assert rc == 0 and ET.fromstring(out).find("testsuite").get("failures") == "0"
    rc, out, _ = run_cli([wenjie_path, "validate", "--format", "sarif"], capsys)
    assert rc == 0
    check_sarif_structure(out, "validate", 0)
    rc, out, _ = run_cli([wenjie_path, "validate", "--format", "github"], capsys)
    assert rc == 0 and out.strip() == ""

    monkeypatch.setattr(TwbParser, "validate", lambda self, error=False: _broken_result())
    rc, out, _ = run_cli([wenjie_path, "validate", "--format", "junit"], capsys)
    assert rc == 2
    assert ET.fromstring(out).find("testsuite").get("failures") == "2"
    rc, out, _ = run_cli([wenjie_path, "validate", "--format", "sarif"], capsys)
    assert rc == 2
    run = check_sarif_structure(out, "validate", 2)
    assert [r["ruleId"] for r in run["results"]] == ["V001", "V002"]
    rc, out, _ = run_cli([wenjie_path, "validate", "--format", "github"], capsys)
    assert rc == 2 and out.count("::error ") == 2 and "title=V001" in out
    rc, out, _ = run_cli([wenjie_path, "validate", "--format", "json"], capsys)    # the old formats are unchanged
    assert rc == 2 and json.loads(out)["ok"] is False


def test_validate_unreadable_workbook_is_still_exit_1(tmp_path, capsys):
    assert main([str(tmp_path / "missing.twb"), "validate", "--format", "sarif"]) == 1


def test_ci_format_on_another_table_is_a_usage_error(wenjie_path, capsys):
    with pytest.raises(SystemExit) as e:
        main([wenjie_path, "fields", "--format", "sarif"])
    assert e.value.code == 2
    assert "validate" in capsys.readouterr().err


def test_help_mentions_the_ci_formats(capsys):
    for argv in (["audit", "--help"], ["template", "check", "--help"], ["--help"]):
        with pytest.raises(SystemExit):
            main(argv)
        assert "sarif" in capsys.readouterr().out


# ------------------------------------------------------- pre-commit hook --

def test_precommit_runs_every_file_and_returns_the_worst_code(broken, tmp_path, capsys):
    from py_tbparse import precommit
    clean = workbook(tmp_path, name="clean.twb")
    assert precommit.main(["audit", "--fail-on", "never", broken, clean]) == 0
    assert precommit.main(["audit", clean, broken]) == 1                       # the second file has an error
    assert precommit.main(["audit", "--format", "github", str(tmp_path / "missing.twb")]) == 2
    assert precommit.main(["audit", "--bogus", clean]) == 2
    assert precommit.main(["nope", clean]) == 2 and precommit.main([]) == 2
    assert precommit.main(["validate", clean]) == 0
    capsys.readouterr()


def test_precommit_template_check(template, capsys):
    from py_tbparse import precommit
    assert precommit.main(["template-check", "--fail-on", "warning", template]) == 1
    assert precommit.main(["template-check", "--fail-on", "never", template]) == 0
    capsys.readouterr()


def test_hooks_file_names_existing_entry_points():
    text = (Path(__file__).parent.parent / ".pre-commit-hooks.yaml").read_text(encoding="utf-8")
    for hook in ("py-tbparse-audit", "py-tbparse-validate", "py-tbparse-template-check"):
        assert f"id: {hook}" in text
    assert text.count("entry: python -m py_tbparse.precommit") == 3


def test_sample_workflow_is_not_in_the_repos_own_workflows():
    root = Path(__file__).parent.parent
    assert (root / "docs" / "examples" / "py-tbparse-ci.yml").is_file()
    assert not list((root / ".github" / "workflows").glob("*tbparse-ci*"))
