"""Template manifest and answers version 2: stable ids, answers files, profiles."""

import json
import re
import shutil
import zipfile
from pathlib import Path

import pytest
from lxml import etree

from py_tbparse import TemplateError, apply_template, load_template, make_template, suggest_mapping
from py_tbparse.templates import MANIFEST_NAME, field_uid, read_data

FIXTURES = Path(__file__).parent / "fixtures"
PUBLIC = FIXTURES / "public"
V1_TEMPLATE = FIXTURES / "templates" / "filtering.v1.template.twbx"


@pytest.fixture
def filtering(tmp_path):
    dst = tmp_path / "filtering.twb"
    shutil.copy(PUBLIC / "filtering.twb", dst)
    return dst


# --- manifest version 2 -----------------------------------------------------------------------------


def test_a_version_1_template_still_loads_and_applies(tmp_path):
    """The fixture is a template as 0.4.x wrote it (manifest version 1)."""
    raw = json.loads(zipfile.ZipFile(V1_TEMPLATE).read(MANIFEST_NAME))
    assert raw["version"] == 1 and "id" not in raw and "uid" not in raw["datasources"][0]["fields"][0]
    t = load_template(str(V1_TEMPLATE))
    assert t.id is None and t.revision == 1
    fields = t.manifest["datasources"][0]["fields"]
    assert all(f["uid"] for f in fields) and len({f["uid"] for f in fields}) == len(fields)
    csv = tmp_path / "q3.csv"
    csv.write_text("burst_out_set_list,Amount\nA,1\n", encoding="utf-8")
    template = tmp_path / "v1.twbx"
    shutil.copy(V1_TEMPLATE, template)
    out = apply_template(str(template), str(csv), allow_missing=True)
    assert Path(out).exists()
    assert json.loads(zipfile.ZipFile(template).read(MANIFEST_NAME))["version"] == 1   # never rewritten


def test_make_template_writes_version_2(filtering, tmp_path):
    t = load_template(make_template(str(filtering), template_id="tpl-1"))
    assert t.manifest["version"] == 2 and t.id == "tpl-1" and t.revision == 1
    for f in t.manifest["datasources"][0]["fields"]:
        assert re.fullmatch(r"[0-9a-f]{16}", f["uid"]) and "alias" in f


def test_a_new_template_gets_its_own_id(filtering, tmp_path):
    a = load_template(make_template(str(filtering)))
    b = load_template(make_template(str(filtering), output_path=str(tmp_path / "b.twbx")))
    assert a.id and b.id and a.id != b.id


def test_a_field_keeps_its_uid_when_only_the_caption_changes(filtering, tmp_path):
    before = load_template(make_template(str(filtering)))
    doc = etree.parse(str(filtering))
    [column] = doc.xpath("/workbook/datasources/datasource/column[@name='[Burst Out Set list]']")
    column.set("caption", "A different caption")
    changed = tmp_path / "changed.twb"
    doc.write(str(changed), encoding="utf-8", xml_declaration=True)
    after = load_template(make_template(str(changed)))
    fields = lambda t: t.manifest["datasources"][0]["fields"]   # noqa: E731
    assert [f["caption"] for f in fields(before)] != [f["caption"] for f in fields(after)]
    assert {f["name"]: f["uid"] for f in fields(before)} == {f["name"]: f["uid"] for f in fields(after)}


def test_field_uid_depends_on_datasource_name_role_and_type_only():
    base = field_uid("ds", "[Sales]", "measure", "real")
    assert base == field_uid("ds", "[Sales]", "measure", "real")
    assert len({base, field_uid("other", "[Sales]", "measure", "real"), field_uid("ds", "[Profit]", "measure", "real"),
                field_uid("ds", "[Sales]", "dimension", "real"), field_uid("ds", "[Sales]", "measure", "integer")}) == 5


def test_a_manifest_from_the_future_is_refused(filtering, tmp_path):
    path = make_template(str(filtering))
    manifest = json.loads(zipfile.ZipFile(path).read(MANIFEST_NAME))
    manifest["version"] = 3
    future = tmp_path / "future.twbx"
    with zipfile.ZipFile(path) as src, zipfile.ZipFile(future, "w") as dst:
        for info in src.infolist():
            dst.writestr(info.filename, json.dumps(manifest) if info.filename == MANIFEST_NAME else src.read(info.filename))
    with pytest.raises(TemplateError, match="newer py-tbparse"):
        load_template(str(future))


# --- answers version 2, apply from answers, profiles ------------------------------------------------------

import py_tbparse.templates as templates   # noqa: E402
from py_tbparse import TwbParser   # noqa: E402
from py_tbparse.templates import load_answers, read_answers   # noqa: E402


@pytest.fixture
def superstore(tmp_path):
    dst = tmp_path / "Cache.twbx"
    shutil.copy(PUBLIC / "Cache.twbx", dst)
    return dst


@pytest.fixture
def setup(superstore, tmp_path, monkeypatch):
    """A template with parameters, a CSV holding every column it reads, and a fixed clock."""
    monkeypatch.setattr(templates, "_now", lambda: "2026-10-02T00:00:00+00:00")
    t = load_template(make_template(str(superstore), template_id="tpl-1"))
    ds = t.manifest["datasources"][0]
    csv = tmp_path / "d.csv"
    csv.write_text(",".join(f["remote"].replace(",", " ") for f in ds["fields"]) + "\n", encoding="utf-8")
    allowed = next(p for p in t.manifest["parameters"] if p["caption"] == "Sort by")["allowed"][-1].strip('"')
    return t, ds["name"], str(csv), allowed


def _members(path):
    with zipfile.ZipFile(path) as z:
        return {n: z.read(n) for n in z.namelist()}


def test_the_answers_a_workbook_keeps_are_version_2(setup, tmp_path):
    t, name, csv, allowed = setup
    out = apply_template(t, csv, datasource=name, allow_missing=True, params={"Sort by": allowed},
                         output_path=str(tmp_path / "out.twbx"))
    a = read_answers(out)
    assert a["version"] == 2 and a["template"]["id"] == "tpl-1" and a["template"]["revision"] == 1
    assert a["data"]["schema_fingerprint"].startswith("sha256:") and a["profiles"] == {}
    [entry] = a["datasources"]
    assert entry["datasource"] == name and entry["mapping"] == a["mapping"] and entry["data"] == a["data"]
    assert a["parameters"]["Sort by"].startswith('"')   # stored as the Tableau literal, as in version 1


def test_answers_alone_make_the_same_workbook_as_the_flags(setup, tmp_path):
    t, name, csv, allowed = setup
    flagged = apply_template(t, csv, datasource=name, allow_missing=True,
                             params={"New Quota": "750000", "Sort by": allowed}, output_path=str(tmp_path / "a.twbx"))
    again = apply_template(t, answers=flagged, allow_missing=True, output_path=str(tmp_path / "b.twbx"))
    assert _members(flagged) == _members(again)
    assert (tmp_path / "a.twbx").read_bytes() == (tmp_path / "b.twbx").read_bytes()
    from_file = tmp_path / "saved.answers.json"
    from_file.write_text(json.dumps(read_answers(flagged)), encoding="utf-8")
    third = apply_template(t, answers=str(from_file), allow_missing=True, output_path=str(tmp_path / "c.twbx"))
    [twb] = [n for n in _members(flagged) if n.endswith(".twb")]
    assert _members(flagged)[twb] == _members(third)[twb]


def test_explicit_arguments_beat_the_profile_which_beats_the_answers(setup, tmp_path):
    t, name, csv, allowed = setup
    answers = {"format": "py-tbparse-template-answers", "version": 2, "datasource": name,
               "data": {"file": csv}, "parameters": {"New Quota": "100"},
               "profiles": {"prod": {"parameters": {"New Quota": "200", "Sort by": allowed}}}}

    def quota(path):
        [col] = TwbParser(path).xml_doc.xpath("//datasource[@name='Parameters']/column[@caption='New Quota']")
        return col.get("value")

    kw = dict(allow_missing=True)
    assert quota(apply_template(t, answers=answers, output_path=str(tmp_path / "1.twbx"), **kw)) == "100"
    assert quota(apply_template(t, answers=answers, profile="prod", output_path=str(tmp_path / "2.twbx"), **kw)) == "200"
    assert quota(apply_template(t, answers=answers, profile="prod", params={"New Quota": "300"},
                                output_path=str(tmp_path / "3.twbx"), **kw)) == "300"
    out = read_answers(str(tmp_path / "2.twbx"))
    assert out["profile"] == "prod" and "prod" in out["profiles"]      # the profiles travel with the workbook


def test_a_profile_can_name_the_data_file_beside_the_answers_file(setup, tmp_path):
    t, name, csv, allowed = setup
    folder = tmp_path / "answers"
    folder.mkdir()
    shutil.copy(csv, folder / "prod.csv")
    path = folder / "prod.answers.json"
    path.write_text(json.dumps({"format": "py-tbparse-template-answers", "version": 2, "datasource": name,
                                "profiles": {"prod": {"data": "prod.csv"}}}), encoding="utf-8")
    out = apply_template(t, answers=str(path), profile="prod", allow_missing=True, output_path=str(tmp_path / "o.twbx"))
    assert read_answers(out)["data"]["file"] == str((folder / "prod.csv").resolve())


def test_profile_and_answers_mistakes_say_what_is_valid(setup, tmp_path):
    t, name, csv, allowed = setup
    answers = {"format": "py-tbparse-template-answers", "version": 2, "datasource": name, "data": {"file": csv},
               "profiles": {"prod": {}, "test": {}}}
    out = lambda n: str(tmp_path / n)   # noqa: E731
    with pytest.raises(TemplateError, match="no profile 'dev'.*prod, test"):
        apply_template(t, answers=answers, profile="dev", output_path=out("a.twbx"))
    with pytest.raises(TemplateError, match="pass answers"):
        apply_template(t, csv, profile="prod", output_path=out("b.twbx"))
    with pytest.raises(TemplateError, match="no data"):
        apply_template(t, answers={**answers, "data": {}}, output_path=out("c.twbx"))
    bad = {**answers, "profiles": {"prod": {"parameters": {"Nope": "1"}}}}
    with pytest.raises(TemplateError, match="no parameter 'Nope'.*New Quota"):
        apply_template(t, answers=bad, profile="prod", allow_missing=True, output_path=out("d.twbx"))
    with pytest.raises(TemplateError, match="another template"):
        apply_template(t, answers={**answers, "template": {"id": "someone-else"}}, allow_missing=True,
                       output_path=out("e.twbx"))
    with pytest.raises(TemplateError, match="not an answers file"):
        load_answers({"format": "something else"})


def test_answers_never_hold_credentials(setup, tmp_path):
    t, name, csv, allowed = setup
    out = apply_template(t, csv, datasource=name, allow_missing=True, output_path=str(tmp_path / "o.twbx"))

    def keys(node):
        if isinstance(node, dict):
            for k, v in node.items():
                yield k
                if k not in ("parameters", "mapping"):
                    yield from keys(v)
        elif isinstance(node, list):
            for item in node:
                yield from keys(item)

    assert not {k.lower() for k in keys(read_answers(out))} & {"password", "username", "token", "secret"}
    for bad in ({"password": "x"}, {"profiles": {"prod": {"Token": "x"}}}, {"datasources": [{"data": {"secret": "x"}}]}):
        with pytest.raises(TemplateError, match="credentials"):
            load_answers({"format": "py-tbparse-template-answers", "version": 2, **bad})
    # a parameter or field the user named "Password" is data, not a credential slot
    load_answers({"format": "py-tbparse-template-answers", "version": 2, "parameters": {"Password": "x"}})


def test_changed_data_is_reported_not_guessed(setup, tmp_path):
    t, name, csv, allowed = setup
    first = apply_template(t, csv, datasource=name, allow_missing=True, output_path=str(tmp_path / "1.twbx"))
    header = Path(csv).read_text(encoding="utf-8").splitlines()[0].split(",")
    renamed = tmp_path / "next.csv"
    renamed.write_text(",".join([header[0] + " v2"] + header[1:]) + "\n", encoding="utf-8")
    report = {}
    apply_template(t, str(renamed), answers=first, allow_missing=True, output_path=str(tmp_path / "2.twbx"), report=report)
    assert report["schema_changed"] is True and report["stale_mapping"]
    report = {}
    apply_template(t, csv, answers=first, allow_missing=True, output_path=str(tmp_path / "3.twbx"), report=report)
    assert report["schema_changed"] is False and report["stale_mapping"] == []


def test_version_1_answers_still_drive_an_apply(setup, tmp_path):
    t, name, csv, allowed = setup
    first = apply_template(t, csv, datasource=name, allow_missing=True, output_path=str(tmp_path / "1.twbx"))
    v2 = read_answers(first)
    v1 = {k: v for k, v in v2.items() if k in ("format", "created", "created_with", "datasource", "mapping", "missing",
                                               "parameters")}
    v1.update(version=1, template={"name": v2["template"]["name"], "file": "x", "manifest_sha256": "x"},
              data={"file": csv, "kind": "csv", "datasource": None})
    out = apply_template(t, answers=v1, allow_missing=True, output_path=str(tmp_path / "2.twbx"))
    assert read_answers(out)["mapping"] == v2["mapping"]


def test_cli_runs_from_answers_and_profiles_and_explains(setup, tmp_path, capsys):
    from py_tbparse.cli import main

    t, name, csv, allowed = setup
    first = str(tmp_path / "first.twbx")
    assert main(["template", "apply", t.path, "--data", csv, "-p", "New Quota=500", "--allow-missing", "--write", first]) == 0
    capsys.readouterr()

    second = str(tmp_path / "second.twbx")
    assert main(["template", "apply", t.path, "--answers", first, "--explain", "--check", "--allow-missing",
                 "--write", second]) == 0
    err = capsys.readouterr().err
    assert "What applying changes:" in err and "Data checks:" in err and "wrote" in err
    assert read_answers(second)["mapping"] == read_answers(first)["mapping"]
    assert read_answers(second)["parameters"] == read_answers(first)["parameters"]

    path = tmp_path / "t.answers.json"
    path.write_text(json.dumps({"format": "py-tbparse-template-answers", "version": 2, "datasource": name,
                                "data": {"file": csv}, "profiles": {"prod": {"parameters": {"New Quota": "900"}}}}),
                    encoding="utf-8")
    third = str(tmp_path / "third.twbx")
    assert main(["template", "apply", t.path, "--answers", str(path), "--profile", "prod", "-p", "Sort by=" + allowed,
                 "--allow-missing", "--write", third]) == 0
    capsys.readouterr()
    assert read_answers(third)["parameters"]["New Quota"] == "900" and read_answers(third)["profile"] == "prod"

    assert main(["template", "apply", t.path, "--allow-missing"]) == 1
    assert "no data" in capsys.readouterr().err
    assert main(["template", "apply", t.path, "--answers", str(path), "--profile", "dev"]) == 1
    assert "no profile 'dev'" in capsys.readouterr().err


def test_answers_for_other_datasources_are_kept(setup, tmp_path):
    t, name, csv, allowed = setup
    elsewhere = {"datasource": "federated.elsewhere", "data": {"file": "x.csv"}, "mapping": {"[A]": "a"}, "missing": []}
    here = {"datasource": name, "data": {"file": csv}, "mapping": {}, "missing": []}
    answers = {"format": "py-tbparse-template-answers", "version": 2, "datasource": name,
               "datasources": [elsewhere, here]}
    out = apply_template(t, answers=answers, allow_missing=True, output_path=str(tmp_path / "o.twbx"))
    names = [e["datasource"] for e in read_answers(out)["datasources"]]
    assert sorted(names) == sorted([name, "federated.elsewhere"])
