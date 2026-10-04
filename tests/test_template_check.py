"""`template check`: the template rules (T001...) on top of the findings engine, and its CLI."""

import io
import json
import shutil
import zipfile
from pathlib import Path

import pandas as pd
import pytest
from lxml import etree

from py_tbparse import findings
from py_tbparse.cli import main
from py_tbparse.findings import FINDING_COLUMNS
from py_tbparse.template_check import RESERVED, check_template, template_rule_ids, _suspicious_literals
from py_tbparse.templates import MANIFEST_NAME, load_template, make_template

FIXTURES = Path(__file__).parent / "fixtures"
PUBLIC = FIXTURES / "public"


def _rewrite(path, manifest_fn=None, workbook_fn=None):
    """Rewrite a template's zip with an edited manifest and/or workbook (a hand-edited template)."""
    with zipfile.ZipFile(path) as z:
        members = [(i, z.read(i.filename)) for i in z.infolist()]
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for info, data in members:
            if info.filename == MANIFEST_NAME and manifest_fn:
                m = json.loads(data)
                manifest_fn(m)
                data = json.dumps(m).encode("utf-8")
            elif info.filename.endswith(".twb") and workbook_fn:
                doc = etree.fromstring(data)
                workbook_fn(doc)
                data = etree.tostring(doc, xml_declaration=True, encoding="utf-8")
            z.writestr(info, data)
    Path(path).write_bytes(out.getvalue())
    return str(path)


def _template(tmp_path, fixture="filtering.twb", **kw):
    src = tmp_path / fixture
    shutil.copy(PUBLIC / fixture, src)
    return make_template(str(src), **kw)


@pytest.fixture
def clean(tmp_path):
    """A template none of the rules complains about."""
    path = _template(tmp_path, "Cache.twbx", name="Quota", description="Sales quota model")

    def tidy(m):
        for ds in m["datasources"]:
            ds["connections"] = []
        for ds in m["datasources"]:
            for f in ds["fields"]:
                if not f["required"]:
                    f["used_by"] = ["Some sheet"]     # so T006 has nothing to say either
    return _rewrite(path, tidy)


def ids(df, rule=None):
    rows = df if rule is None else df[df["rule"] == rule]
    return list(rows["object"])


def test_the_template_rules_have_stable_ids():
    assert template_rule_ids() == ["T001", "T002", "T003", "T004", "T005", "T006", "T007", "T008", "T010"]
    assert "T009" in RESERVED         # the token rule (WP19): reserved, so the number is never reused


def test_a_clean_template_has_no_findings(clean):
    df = check_template(clean)
    assert df.empty, df.to_string()
    assert list(df.columns) == FINDING_COLUMNS


def test_check_accepts_a_loaded_template(clean):
    assert check_template(load_template(clean)).empty


def test_reserved_id_is_explained(clean):
    with pytest.raises(ValueError, match="T009.*token"):
        check_template(clean, only=["T009"])


# --- T001 -------------------------------------------------------------------

def test_t001_hard_coded_connection(tmp_path):
    df = check_template(_template(tmp_path), only=["T001"])
    assert len(df) == 1 and df.iloc[0]["severity"] == "warning"
    assert "b5dpm3ihhu.database.windows.net" in df.iloc[0]["detail"]
    assert "server" in df.iloc[0]["detail"] and "dbname" in df.iloc[0]["detail"]


def test_t001_absolute_path_and_passing_case(clean, tmp_path):
    def local(m):
        m["datasources"][0]["connections"] = [{"class": "textscan", "directory": "/home/ann/data",
                                               "filename": "C:\\Users\\ann\\sales.csv"}]
    bad = _rewrite(shutil.copy(clean, tmp_path / "bad.twbx"), local)
    df = check_template(bad, only=["T001"])
    assert "directory" in df.iloc[0]["detail"] and "filename" in df.iloc[0]["detail"]
    assert check_template(clean, only=["T001"]).empty


# --- T002 -------------------------------------------------------------------

def test_t002_version_1_manifest_cannot_be_updated():
    df = check_template(str(FIXTURES / "templates" / "filtering.v1.template.twbx"), only=["T002"])
    assert len(df) == 1 and df.iloc[0]["severity"] == "info"
    assert "template update" in df.iloc[0]["detail"]


def test_t002_missing_id(clean, tmp_path):
    bad = _rewrite(shutil.copy(clean, tmp_path / "noid.twbx"), lambda m: m.pop("id"))
    assert len(check_template(bad, only=["T002"])) == 1
    assert check_template(clean, only=["T002"]).empty


# --- T003 -------------------------------------------------------------------

def test_t003_parameter_value_problems(clean, tmp_path):
    def break_params(m):
        by_name = {p["name"]: p for p in m["parameters"]}
        by_name["[Base Salary]"]["value"] = None
        by_name["[Parameter 3]"]["value"] = '"Atlantis"'
    bad = _rewrite(shutil.copy(clean, tmp_path / "params.twbx"), break_params)
    df = check_template(bad, only=["T003"])
    assert set(df["severity"]) == {"error"}
    assert ids(df) == ["Base Salary", "State"]
    assert "no value" in df.iloc[0]["detail"] and "Atlantis" in df.iloc[1]["detail"]
    assert check_template(clean, only=["T003"]).empty


# --- T004 -------------------------------------------------------------------

def test_t004_datasource_with_several_tables(tmp_path):
    src = tmp_path / "wenjie.twb"
    shutil.copy(FIXTURES / "test_for_wenjie.twb", src)
    df = check_template(make_template(str(src)), only=["T004"])
    assert len(df) == 1 and df.iloc[0]["severity"] == "info" and "2 tables" in df.iloc[0]["detail"]
    assert check_template(_template(tmp_path), only=["T004"]).empty


# --- T005 -------------------------------------------------------------------

def test_t005_packaged_data_is_flagged_with_its_size(tmp_path):
    kept = _template(tmp_path, "Cache.twbx", keep_data=True)
    df = check_template(kept, only=["T005"])
    assert len(df) >= 1 and set(df["severity"]) == {"warning"}
    assert any("Sales Target.tde" in o for o in df["object"])
    assert any(unit in df.iloc[0]["detail"] for unit in ("bytes", "KB", "MB"))
    assert MANIFEST_NAME not in " ".join(df["object"])             # the manifest is not "data"


def test_t005_a_template_without_data_passes(tmp_path):
    assert check_template(_template(tmp_path, "Cache.twbx"), only=["T005"]).empty


def test_t005_extract_left_in_the_workbook(clean, tmp_path):
    def add_extract(doc):
        ds = doc.xpath("/workbook/datasources/datasource[@name!='Parameters']")[0]
        etree.SubElement(ds, "extract", enabled="true")
    bad = _rewrite(shutil.copy(clean, tmp_path / "extract.twbx"), workbook_fn=add_extract)
    df = check_template(bad, only=["T005"])
    assert len(df) == 1 and "extract" in df.iloc[0]["detail"]


# --- T006 -------------------------------------------------------------------

def test_t006_required_field_nothing_uses(tmp_path):
    path = _template(tmp_path)

    def hand_edit(m):                      # marks a field required that nothing in the workbook uses
        f = next(f for f in m["datasources"][0]["fields"] if not f["required"] and not f["used_by"])
        f["required"] = True
        hand_edit.name = f["name"]
    bad = _rewrite(path, hand_edit)
    df = check_template(bad, only=["T006"])
    row = df[df["detail"].str.contains("required")]
    assert len(row) == 1 and row.iloc[0]["severity"] == "info"
    assert hand_edit.name.strip("[]") in row.iloc[0]["object"]


def test_t006_optional_fields_used_by_nothing_are_one_row_per_datasource(tmp_path):
    df = check_template(_template(tmp_path), only=["T006"])
    assert len(df) == 1                                # filtering has 39 fields, a few required
    assert "optional" in df.iloc[0]["detail"] and "drop" in df.iloc[0]["fix"]


# --- T007 -------------------------------------------------------------------

def test_t007_dangling_reference(clean, tmp_path):
    def dangle(doc):
        w = doc.xpath("/workbook/windows/window[@name]")[0]
        w.set("name", "No such sheet")
    bad = _rewrite(shutil.copy(clean, tmp_path / "dangling.twbx"), workbook_fn=dangle)
    df = check_template(bad, only=["T007"])
    assert len(df) == 1 and df.iloc[0]["severity"] == "error" and "window-name" in df.iloc[0]["detail"]
    assert "No such sheet" in df.iloc[0]["object"]
    assert check_template(clean, only=["T007"]).empty


# --- T008 -------------------------------------------------------------------

@pytest.mark.parametrize("formula,expected", [
    ('IF [x] = "East" THEN "A" END', []),
    ('"https://intranet.example.com/report"', ["https://intranet.example.com/report"]),
    ("'http://x.example'", ["http://x.example"]),
    (r'"\\fileserver\share\data.csv"', [r"\\fileserver\share\data.csv"]),
    (r'"C:\data\sales.csv"', [r"C:\data\sales.csv"]),
    ('"ann@example.com"', ["ann@example.com"]),
    ('"' + "a long literal " * 4 + '"', ["a long literal " * 4]),
    ('"say ""hi"" to http://x.example"', ['say "hi" to http://x.example']),
    ("SUM([Sales])", []),
])
def test_t008_literal_heuristic(formula, expected):
    assert _suspicious_literals(formula) == expected


def test_t008_in_a_template(clean, tmp_path):
    def plant(doc):
        ds = doc.xpath("/workbook/datasources/datasource[@name!='Parameters']")[0]
        col = etree.SubElement(ds, "column", name="[Customer URL]", datatype="string", role="dimension", type="nominal")
        etree.SubElement(col, "calculation", {"class": "tableau", "formula": '"https://customer.example.com/x"'})
    bad = _rewrite(shutil.copy(clean, tmp_path / "lit.twbx"), workbook_fn=plant)
    df = check_template(bad, only=["T008"])
    assert len(df) == 1 and "heuristic" in df.iloc[0]["detail"] and df.iloc[0]["severity"] == "info"
    assert check_template(clean, only=["T008"]).empty


def test_t008_ignores_parameter_defaults(clean):
    # a parameter's value is stored as a literal formula; that is not a hard-coded customer
    assert check_template(clean, only=["T008"]).empty


# --- T010 -------------------------------------------------------------------

def test_t010_no_description_and_default_name(tmp_path):
    df = check_template(_template(tmp_path), only=["T010"])
    assert len(df) == 2 and set(df["severity"]) == {"info"}
    assert any("description" in d for d in df["detail"]) and any("name" in d for d in df["detail"])


def test_t010_passes_with_name_and_description(tmp_path):
    ok = _template(tmp_path, name="Filtering demo", description="Shows filters")
    assert check_template(ok, only=["T010"]).empty


# --- engine behaviour on templates -----------------------------------------

def test_only_skip_and_determinism(tmp_path):
    path = _template(tmp_path)
    a, b = check_template(path), check_template(path)
    pd.testing.assert_frame_equal(a, b)
    assert list(a["rule"]) == sorted(a["rule"])
    assert "T001" not in set(check_template(path, skip=["T001"])["rule"])
    assert set(check_template(path, only=["T001", "T010"])["rule"]) <= {"T001", "T010"}
    with pytest.raises(ValueError, match="T999"):
        check_template(path, only=["T999"])


def test_a_workbook_that_is_not_a_template_is_an_error(tmp_path):
    with pytest.raises(ValueError, match="template"):
        check_template(str(PUBLIC / "Cache.twbx"))


# --- CLI --------------------------------------------------------------------

def test_cli_check_default_fails_only_on_errors(tmp_path, capsys):
    path = _template(tmp_path)                       # warnings and info only
    assert main(["template", "check", path]) == 0
    out = capsys.readouterr()
    assert "T001" in out.out and "warning" in out.err


def test_cli_check_fail_on_warning(tmp_path, capsys):
    assert main(["template", "check", _template(tmp_path), "--fail-on", "warning"]) == 1
    capsys.readouterr()


def test_cli_check_fail_on_error_and_never(clean, tmp_path, capsys):
    bad = _rewrite(shutil.copy(clean, tmp_path / "bad.twbx"), lambda m: m["parameters"][0].update(value=None))
    assert main(["template", "check", bad]) == 1
    assert main(["template", "check", bad, "--fail-on", "never"]) == 0
    capsys.readouterr()


def test_cli_check_clean_template(clean, capsys):
    assert main(["template", "check", clean, "--fail-on", "info"]) == 0
    out = capsys.readouterr()
    assert "no findings" in out.err


def test_cli_check_formats(tmp_path, capsys):
    path = _template(tmp_path)
    assert main(["template", "check", path, "--format", "json", "--only", "T001,T010"]) == 0
    rows = json.loads(capsys.readouterr().out)
    assert {r["rule"] for r in rows} == {"T001", "T010"} and set(rows[0]) == set(FINDING_COLUMNS)
    assert main(["template", "check", path, "--format", "csv", "--skip", "T001,T006"]) == 0
    head = capsys.readouterr().out.splitlines()[0]
    assert head == ",".join(FINDING_COLUMNS)


def test_cli_check_usage_errors_exit_2(tmp_path, capsys):
    path = _template(tmp_path)
    assert main(["template", "check", path, "--only", "T999"]) == 2
    assert "T999" in capsys.readouterr().err
    assert main(["template", "check", str(tmp_path / "missing.twbx")]) == 2
    assert main(["template", "check", str(PUBLIC / "filtering.twb")]) == 2
    capsys.readouterr()


def test_cli_help_lists_the_rules(capsys):
    with pytest.raises(SystemExit):
        main(["template", "check", "--help"])
    text = capsys.readouterr().out
    for rid in ("T001", "T007", "T010", "--fail-on", "--only", "--skip", "--format"):
        assert rid in text
    assert "T009" in text and "reserved" in text.lower()


def test_check_leaves_the_template_untouched(tmp_path):
    path = _template(tmp_path)
    before = Path(path).read_bytes()
    check_template(path)
    assert Path(path).read_bytes() == before
    assert not findings.exceeds(pd.DataFrame(columns=FINDING_COLUMNS), "info")
