"""`template update`: a newer revision of a template against the workbook made from an older one."""

import copy
import json
import shutil
import zipfile
from pathlib import Path

import pandas as pd
import pytest

import py_tbparse.templates as templates
from py_tbparse import (
    TemplateError,
    apply_template,
    diff_template_revisions,
    load_template,
    make_template,
    template_update_report,
    update_from_answers,
)
from py_tbparse.templates import MANIFEST_NAME, read_answers

PUBLIC = Path(__file__).parent / "fixtures" / "public"
V1_TEMPLATE = Path(__file__).parent / "fixtures" / "templates" / "filtering.v1.template.twbx"


def revise(template_path, out, edit, keep_id=True):
    """A copy of a template whose manifest is one revision on and changed by `edit(manifest)`."""
    with zipfile.ZipFile(template_path) as src:
        members = {i.filename: src.read(i.filename) for i in src.infolist()}
    manifest = json.loads(members[MANIFEST_NAME])
    manifest["revision"] += 1
    edit(manifest)
    members[MANIFEST_NAME] = json.dumps(manifest, indent=2).encode("utf-8")
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as dst:
        for name, data in members.items():
            dst.writestr(name, data)
    return str(out)


def fields(manifest):
    return manifest["datasources"][0]["fields"]


def field(manifest, name):
    return next(f for f in fields(manifest) if f["name"] == name)


@pytest.fixture
def made(tmp_path, monkeypatch):
    """Revision 1 of a template, a CSV with every column, and the workbook applied from them."""
    monkeypatch.setattr(templates, "_now", lambda: "2026-10-02T00:00:00+00:00")
    book = tmp_path / "Cache.twbx"
    shutil.copy(PUBLIC / "Cache.twbx", book)
    v1 = make_template(str(book), output_path=str(tmp_path / "cache.template.twbx"), template_id="tpl-1")
    t = load_template(v1)
    header = [f["remote"] for f in fields(t.manifest)]
    csv = tmp_path / "data.csv"
    sample = {"string": "x", "date": "2026-01-31"}
    csv.write_text(",".join(header) + "\n" + ",".join(sample.get(f["datatype"], "1") for f in fields(t.manifest)) + "\n",
                   encoding="utf-8")
    sort_by = next(p for p in t.manifest["parameters"] if p["caption"] == "Sort by")["allowed"][-1]
    out = apply_template(t, str(csv), datasource=t.manifest["datasources"][0]["name"], allow_missing=True,
                         params={"Sort by": sort_by.strip('"'), "New Quota": "750000"},
                         output_path=str(tmp_path / "cache_data.twbx"))
    return {"dir": tmp_path, "v1": v1, "t": t, "csv": csv, "out": out, "book": book}


# --- revisions ----------------------------------------------------------------------------------------


def test_a_revision_keeps_the_id_and_counts_up(made):
    v2 = load_template(make_template(str(made["book"]), output_path=str(made["dir"] / "v2.twbx"),
                                     revision_of=made["v1"]))
    assert v2.id == "tpl-1" and v2.revision == 2
    v3 = load_template(make_template(str(made["book"]), output_path=str(made["dir"] / "v3.twbx"), revision_of=v2))
    assert v3.id == "tpl-1" and v3.revision == 3


def test_revision_of_refuses_a_different_id(made):
    with pytest.raises(TemplateError, match="contradicts"):
        make_template(str(made["book"]), output_path=str(made["dir"] / "v2.twbx"), revision_of=made["v1"],
                      template_id="another")


def test_a_revision_of_a_version_1_template_gets_a_fresh_id(tmp_path):
    book = tmp_path / "filtering.twb"
    shutil.copy(PUBLIC / "filtering.twb", book)
    v2 = load_template(make_template(str(book), output_path=str(tmp_path / "v2.twbx"), revision_of=str(V1_TEMPLATE)))
    assert v2.id and v2.revision == 2


def test_the_answers_keep_what_the_template_needed_and_the_columns(made):
    a = read_answers(made["out"])
    assert a["template"]["manifest"] == made["t"].manifest
    assert a["data"]["columns"] == [f["remote"] for f in fields(made["t"].manifest)]


# --- stage A: the report ------------------------------------------------------------------------------


def impacts(df):
    return {(r.kind, r.item, r.change): r.impact for r in df.itertuples()}


def test_an_unchanged_template_reports_nothing(made):
    same = revise(made["v1"], made["dir"] / "v2.twbx", lambda m: None)
    assert template_update_report(same, made["out"]).empty
    assert diff_template_revisions(made["v1"], same).empty


def test_a_caption_change_keeps_the_mapping(made):
    def edit(m):
        field(m, "[Segment]")["caption"] = "Customer segment"
    v2 = revise(made["v1"], made["dir"] / "v2.twbx", edit)
    report = template_update_report(v2, made["out"])
    assert impacts(report) == {("field", "[Segment]", "caption"): "auto-carry"}
    assert list(report.columns) == ["kind", "datasource", "item", "change", "old", "new", "impact"]


def test_a_new_required_field_needs_a_mapping_and_a_new_optional_one_does_not(made):
    def edit(m):
        base = field(m, "[Segment]")
        fields(m).append({**base, "name": "[Region]", "uid": "r1", "remote": "Region", "caption": None, "required": True})
        fields(m).append({**base, "name": "[Notes]", "uid": "n1", "remote": "Notes", "caption": None, "required": False})
    report = template_update_report(revise(made["v1"], made["dir"] / "v2.twbx", edit), made["out"])
    assert impacts(report) == {("field", "[Region]", "added"): "needs-mapping", ("field", "[Notes]", "added"): "optional"}


def test_removing_a_mapped_field_orphans_it(made):
    def edit(m):
        m["datasources"][0]["fields"] = [f for f in fields(m) if f["name"] != "[Order Date]"]
    report = template_update_report(revise(made["v1"], made["dir"] / "v2.twbx", edit), made["out"])
    assert impacts(report) == {("field", "[Order Date]", "removed"): "orphaned"}


def test_a_field_that_became_required_while_unmapped_needs_a_mapping(made):
    # answers saved with a mapping that leaves [Segment] out
    answers = read_answers(made["out"])
    for entry in [answers, *answers["datasources"]]:
        entry["mapping"].pop("[Segment]", None)

    def edit(m):
        field(m, "[Segment]")["required"] = True
    report = template_update_report(revise(made["v1"], made["dir"] / "v2.twbx", edit), answers)
    assert impacts(report) == {("field", "[Segment]", "required"): "needs-mapping"}


def test_a_type_change_conflicts_only_when_the_column_cannot_feed_it(made):
    def edit(m):
        f = field(m, "[Order Date]")
        f["datatype"] = f["physical_type"] = "string"
        g = field(m, "[Sales Target]")
        g["datatype"] = g["physical_type"] = "real"
    report = template_update_report(revise(made["v1"], made["dir"] / "v2.twbx", edit), made["out"], data=str(made["csv"]))
    got = impacts(report)
    # the CSV's Order Date column holds dates: a string field cannot take it
    assert got[("field", "[Sales Target]", "type")] == "auto-carry"        # integer column for a real field: converts
    assert got[("field", "[Order Date]", "type")] == "type-conflict"


def test_a_type_change_with_unreadable_data_is_flagged_as_unknown(made):
    def edit(m):
        field(m, "[Sales Target]")["physical_type"] = "string"
    answers = read_answers(made["out"])
    answers["data"]["file"] = str(made["dir"] / "gone.csv")
    answers["datasources"][0]["data"]["file"] = str(made["dir"] / "gone.csv")
    report = template_update_report(revise(made["v1"], made["dir"] / "v2.twbx", edit), answers)
    assert impacts(report)[("field", "[Sales Target]", "type")] == "type-conflict"


def test_a_field_renamed_in_the_template_is_found_by_its_source_column(made):
    def edit(m):
        f = field(m, "[Segment]")
        f["name"] = "[Customer Segment]"
        f["uid"] = "new-uid"
    report = template_update_report(revise(made["v1"], made["dir"] / "v2.twbx", edit), made["out"])
    assert impacts(report) == {("field", "[Customer Segment]", "renamed"): "auto-carry"}
    [row] = report.itertuples()
    assert (row.old, row.new) == ("[Segment]", "[Customer Segment]")


def test_parameters(made):
    def edit(m):
        by = {p["caption"]: p for p in m["parameters"]}
        by["Base Salary"]["value"] = "60000"                             # default moved; the saved value stays
        by["Sort by"]["allowed"] = by["Sort by"]["allowed"][:-1]         # the saved value is no longer allowed
        by["New Quota"]["datatype"] = "string"
        m["parameters"] = [p for p in m["parameters"] if p["caption"] != "Churn Rate"]
        m["parameters"].append({**by["Base Salary"], "name": "[Bonus]", "caption": "Bonus"})
    report = template_update_report(revise(made["v1"], made["dir"] / "v2.twbx", edit), made["out"])
    got = impacts(report)
    assert got[("parameter", "Sort by", "allowed values")] == "type-conflict"
    assert got[("parameter", "New Quota", "type")] == "type-conflict"
    assert got[("parameter", "Churn Rate", "removed")] == ""            # never set by the answers
    assert got[("parameter", "Bonus", "added")] == ""
    assert ("parameter", "Base Salary", "default") not in got or got[("parameter", "Base Salary", "default")] == ""


def test_sheets_and_dashboards(made):
    def edit(m):
        m["worksheets"] = m["worksheets"][1:] + ["Brand new"]
        m["dashboards"] = m["dashboards"] + ["Overview 2"]
    report = template_update_report(revise(made["v1"], made["dir"] / "v2.twbx", edit), made["out"])
    assert {(r.kind, r.change) for r in report.itertuples()} == {("worksheet", "removed"), ("worksheet", "added"),
                                                                 ("dashboard", "added")}
    assert (report["impact"] == "").all()


def test_a_snapshot_of_the_report(made):
    def edit(m):
        field(m, "[Segment]")["caption"] = "Customer segment"
        fields(m).append({**field(m, "[Segment]"), "name": "[Region]", "uid": "r1", "remote": "Region",
                          "caption": None, "required": True})
        m["datasources"][0]["fields"] = [f for f in fields(m) if f["name"] != "[Order Date]"]
    report = template_update_report(revise(made["v1"], made["dir"] / "v2.twbx", edit), made["out"])
    assert report[["kind", "item", "change", "impact"]].values.tolist() == [
        ["field", "[Order Date]", "removed", "orphaned"],
        ["field", "[Region]", "added", "needs-mapping"],
        ["field", "[Segment]", "caption", "auto-carry"],
    ]


def test_without_a_snapshot_the_new_template_is_checked_against_the_answers(made):
    answers = read_answers(made["out"])
    del answers["template"]["manifest"]
    answers["mapping"]["[Gone]"] = "gone"
    answers["datasources"][0]["mapping"]["[Gone]"] = "gone"

    def edit(m):
        base = field(m, "[Segment]")
        fields(m).append({**base, "name": "[Region]", "uid": "r1", "remote": "Region", "required": True})
    report = template_update_report(revise(made["v1"], made["dir"] / "v2.twbx", edit), answers)
    assert impacts(report) == {("field", "[Region]", "no column saved"): "needs-mapping",
                               ("field", "[Gone]", "not in the template"): "orphaned"}


def test_an_explicit_old_template_replaces_the_snapshot(made):
    answers = read_answers(made["out"])
    del answers["template"]["manifest"]

    def edit(m):
        field(m, "[Segment]")["caption"] = "Customer segment"
    v2 = revise(made["v1"], made["dir"] / "v2.twbx", edit)
    assert impacts(template_update_report(v2, answers, old=made["v1"])) == {("field", "[Segment]", "caption"): "auto-carry"}


def test_answers_from_another_template_are_refused(made):
    other = revise(made["v1"], made["dir"] / "other.twbx", lambda m: m.update(id="not-tpl-1"))
    with pytest.raises(TemplateError, match="another template"):
        template_update_report(other, made["out"])
    with pytest.raises(TemplateError, match="another template"):
        update_from_answers(other, made["out"])


# --- stage B: the update ------------------------------------------------------------------------------


def test_the_same_template_is_a_no_op(made):
    report = {}
    assert update_from_answers(made["v1"], made["out"], report=report) is None
    assert report["status"] == "unchanged" and report["output"] is None


def test_an_update_keeps_the_mapping_and_the_parameters(made):
    def edit(m):
        field(m, "[Segment]")["caption"] = "Customer segment"
        by = {p["caption"]: p for p in m["parameters"]}
        by["Base Salary"]["value"] = "60000"
    v2 = revise(made["v1"], made["dir"] / "v2.twbx", edit)
    report = {}
    out = update_from_answers(v2, made["out"], report=report)
    assert Path(out) == made["dir"] / "cache_data_r2.twbx" and Path(out).exists()
    assert report["status"] == "updated" and report["needs_mapping"] == [] and report["id_checked"] is True
    assert report["columns_added"] == [] and report["columns_removed"] == []
    a, b = read_answers(made["out"]), read_answers(out)
    assert b["mapping"] == a["mapping"] and b["parameters"] == a["parameters"]
    assert b["template"]["revision"] == 2 and b["template"]["manifest_sha256"] != a["template"]["manifest_sha256"]
    assert b["template"]["manifest"]["revision"] == 2   # the next update has its "before"
    assert zipfile.ZipFile(made["out"]).testzip() is None


def test_a_new_required_field_stops_the_update_and_a_mapping_resolves_it(made):
    def edit(m):
        fields(m).append({**field(m, "[Segment]"), "name": "[Region]", "uid": "r1", "remote": "Region",
                          "caption": None, "required": True, "used_by": ["Some sheet"]})
    v2 = revise(made["v1"], made["dir"] / "v2.twbx", edit)
    report = {}
    with pytest.raises(TemplateError, match=r"update stopped: no column for required field\(s\) Region; sheets that would break: Some sheet"):
        update_from_answers(v2, made["out"], report=report)
    assert report["needs_mapping"] == ["[Region]"]
    assert not (made["dir"] / "cache_data_r2.twbx").exists()
    out = update_from_answers(v2, made["out"], allow_missing=True)
    assert read_answers(out)["missing"] == ["[Region]"]


def test_a_new_column_in_the_data_resolves_a_new_field_and_is_reported(made):
    def edit(m):
        fields(m).append({**field(m, "[Segment]"), "name": "[Region]", "uid": "r1", "remote": "Region",
                          "caption": None, "required": True})
    v2 = revise(made["v1"], made["dir"] / "v2.twbx", edit)
    newer = made["dir"] / "newer.csv"
    newer.write_text("Category,Number of Records,Order Date,Sales Target,Segment,Region\nx,1,1,1,x,north\n",
                     encoding="utf-8")
    report = {}
    out = update_from_answers(v2, made["out"], data=str(newer), report=report)
    assert report["columns_added"] == ["Region"] and report["needs_mapping"] == []
    assert read_answers(out)["mapping"]["[Region]"] == "Region"      # suggested for the new field only
    assert read_answers(out)["mapping"]["[Category]"] == read_answers(made["out"])["mapping"]["[Category]"]


def test_a_field_renamed_in_the_template_keeps_its_saved_column(made):
    def edit(m):
        f = field(m, "[Segment]")
        f["name"], f["uid"] = "[Customer Segment]", "new-uid"
    v2 = revise(made["v1"], made["dir"] / "v2.twbx", edit)
    out = update_from_answers(v2, made["out"])
    mapping = read_answers(out)["mapping"]
    assert mapping["[Customer Segment]"] == "Segment" and "[Segment]" not in mapping


def test_a_saved_parameter_value_the_template_no_longer_takes_is_dropped_and_reported(made):
    def edit(m):
        by = {p["caption"]: p for p in m["parameters"]}
        by["Sort by"]["allowed"] = by["Sort by"]["allowed"][:-1]
        m["parameters"] = [p for p in m["parameters"] if p["caption"] != "New Quota"]
    v2 = revise(made["v1"], made["dir"] / "v2.twbx", edit)
    report = {}
    out = update_from_answers(v2, made["out"], report=report)
    assert sorted(report["dropped_parameters"]) == ["New Quota", "Sort by"]
    assert "Sort by" not in read_answers(out)["parameters"] and "New Quota" not in read_answers(out)["parameters"]


def test_a_saved_column_of_the_wrong_type_is_asked_for_again(made):
    def edit(m):
        f = field(m, "[Sales Target]")
        f["physical_type"] = f["datatype"] = "string"
        f["required"] = True
    v2 = revise(made["v1"], made["dir"] / "v2.twbx", edit)
    report = {}
    with pytest.raises(TemplateError, match="Sales Target"):
        update_from_answers(v2, made["out"], report=report)
    assert report["conflicts"] == ["[Sales Target]"]


def test_a_moved_data_file_is_found_again_with_data(made):
    v2 = revise(made["v1"], made["dir"] / "v2.twbx", lambda m: field(m, "[Segment]").update(caption="Seg"))
    moved = made["dir"] / "moved.csv"
    shutil.move(made["csv"], moved)
    with pytest.raises(FileNotFoundError):
        update_from_answers(v2, made["out"])
    out = update_from_answers(v2, made["out"], data=str(moved))
    assert read_answers(out)["data"]["file"] == str(moved.resolve())


def test_answers_without_a_template_id_are_accepted_and_the_report_says_it_could_not_check(made):
    answers = read_answers(made["out"])
    answers["template"]["id"] = None
    v2 = revise(made["v1"], made["dir"] / "v2.twbx", lambda m: field(m, "[Segment]").update(caption="Seg"))
    report = {}
    assert update_from_answers(v2, answers, report=report, output_path=str(made["dir"] / "o.twbx"))
    assert report["id_checked"] is False


def test_the_update_never_overwrites(made):
    v2 = revise(made["v1"], made["dir"] / "v2.twbx", lambda m: field(m, "[Segment]").update(caption="Seg"))
    out = update_from_answers(v2, made["out"])
    with pytest.raises(FileExistsError):
        update_from_answers(v2, made["out"])
    assert update_from_answers(v2, made["out"], overwrite=True) == out
    with pytest.raises(FileExistsError, match="input"):
        update_from_answers(v2, made["out"], output_path=made["out"], overwrite=True)


def test_a_workbook_made_from_several_datasources_must_say_which(made):
    answers = read_answers(made["out"])
    second = copy.deepcopy(answers["datasources"][0])
    second["datasource"] = "other"
    answers["datasources"].append(second)
    v2 = revise(made["v1"], made["dir"] / "v2.twbx", lambda m: field(m, "[Segment]").update(caption="Seg"))
    with pytest.raises(TemplateError, match="several datasources"):
        update_from_answers(v2, answers)


def test_the_report_is_a_dataframe_with_the_documented_columns(made):
    v2 = revise(made["v1"], made["dir"] / "v2.twbx", lambda m: None)
    assert isinstance(template_update_report(v2, made["out"]), pd.DataFrame)


# --- command line ------------------------------------------------------------------------------------------

from py_tbparse.cli import main   # noqa: E402


def test_cli_update_prints_the_report_and_writes_nothing(made, capsys):
    v2 = revise(made["v1"], made["dir"] / "v2.twbx", lambda m: field(m, "[Segment]").update(caption="Seg"))
    assert main(["template", "update", v2, made["out"]]) == 0
    captured = capsys.readouterr()
    assert "caption" in captured.out and "auto-carry" in captured.out
    assert not (made["dir"] / "cache_data_r2.twbx").exists()


def test_cli_update_writes_with_write_and_says_when_nothing_changed(made, capsys):
    v2 = revise(made["v1"], made["dir"] / "v2.twbx", lambda m: field(m, "[Segment]").update(caption="Seg"))
    assert main(["template", "update", v2, made["out"], "--write"]) == 0
    assert (made["dir"] / "cache_data_r2.twbx").exists()
    assert main(["template", "update", made["v1"], made["out"]]) == 0
    assert "nothing to update" in capsys.readouterr().err


def test_cli_update_stops_on_a_new_required_field(made, capsys):
    def edit(m):
        fields(m).append({**field(m, "[Segment]"), "name": "[Region]", "uid": "r1", "remote": "Region",
                          "caption": None, "required": True})
    v2 = revise(made["v1"], made["dir"] / "v2.twbx", edit)
    assert main(["template", "update", v2, made["out"], "--write"]) == 1
    assert "update stopped" in capsys.readouterr().err
    assert main(["template", "update", v2, made["out"], "--write", "--allow-missing"]) == 0
