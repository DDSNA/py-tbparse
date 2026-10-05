"""Findings of the independent review of the token feature (issues #24, #25, #26 and #27)."""

from __future__ import annotations

import shutil
import warnings
from pathlib import Path

import pytest
from lxml import etree

import py_tbparse.templates as templates
from py_tbparse import TemplateError, apply_template, load_template, make_template, tokens
from py_tbparse.cli import main
from py_tbparse.template_batch import read_inputs
from py_tbparse.template_update import template_update_report, update_from_answers
from py_tbparse.templates import read_answers

from test_tokens import CORPUS, PUBLIC, apply, book, corpus, csv_for, edit, make, param_book, twb_of  # noqa: F401


def _param_apply(t, tmp_path, name, **kw):
    entry = t.manifest["datasources"][-1]["name"]
    data = tmp_path / "d.csv"
    data.write_text(",".join(f["remote"] for f in t.manifest["datasources"][-1]["fields"]) + "\n", encoding="utf-8")
    return apply_template(t, str(data), datasource=entry, allow_missing=True, output_path=str(tmp_path / name), **kw)


def _param_revision(tmp_path, old, name="r2"):
    """A second revision of the parameter workbook (an allowed value fewer, so the manifest differs)."""
    def change(root):
        col = root.xpath("//datasource[@name='Parameters']/column[@caption='State']")[0]
        col.set("value", '"{{customer}} HQ"')
        col.find("calculation").set("formula", '"{{customer}} HQ"')
        members = col.find("members")
        for member in list(members)[2:]:
            members.remove(member)
        members[0].set("value", '"{{customer}} HQ"')
    src = edit(PUBLIC / "Cache.twbx", tmp_path / f"{name}.twbx", change)
    return load_template(make_template(src, output_path=str(tmp_path / f"{name}.template.twbx"), revision_of=old))


# --- #24 ----------------------------------------------------------------------------------------------------


def test_24_update_keeps_a_saved_string_parameter_whose_allowed_list_has_a_token(param_book, tmp_path):
    t = make(param_book, tmp_path, "p.template.twbx")
    first = _param_apply(t, tmp_path, "first.twbx", tokens={"customer": "ACME"}, params={"State": "ACME HQ"})
    new = _param_revision(tmp_path, t)
    info: dict = {}
    out = update_from_answers(new, first, output_path=str(tmp_path / "updated.twbx"), allow_missing=True, report=info)
    assert info["dropped_parameters"] == []
    assert read_answers(out)["parameters"] == {"State": '"ACME HQ"'}
    assert not (info["changes"]["impact"] == "type-conflict").any()
    # the report with no "before" does not call the filled value "not allowed" either
    rows = template_update_report(new, first, old=None)
    assert "value not allowed" not in set(rows["change"])


def test_24_reapplying_the_answers_with_another_token_value_keeps_the_saved_value(param_book, tmp_path):
    t = make(param_book, tmp_path, "p.template.twbx")
    first = _param_apply(t, tmp_path, "first.twbx", tokens={"customer": "ACME"}, params={"State": "ACME HQ"})
    out = _param_apply(t, tmp_path, "second.twbx", answers=first, tokens={"customer": "Globex"})
    col = etree.fromstring(twb_of(out)).xpath("//datasource[@name='Parameters']/column[@caption='State']")[0]
    assert col.get("value") == '"ACME HQ"'                                  # the saved value, not the token's new one
    assert col.findall("members/member")[0].get("value") == '"Globex HQ"'
    # an explicit value is still checked against the allowed list as it is filled now
    with pytest.raises(TemplateError, match="'ACME HQ' is not one of its allowed values"):
        _param_apply(t, tmp_path, "third.twbx", tokens={"customer": "Globex"}, params={"State": "ACME HQ"})


# --- #25 ----------------------------------------------------------------------------------------------------


@pytest.fixture
def copy_book(tmp_path, monkeypatch):
    """The parameter workbook with the sheet-level copy of the string parameter that Tableau keeps."""
    monkeypatch.setattr(templates, "_now", lambda: "2026-10-04T00:00:00+00:00")

    def change(root):
        col = root.xpath("//datasource[@name='Parameters']/column[@caption='State']")[0]
        col.set("value", '"{{customer}} HQ"')
        col.find("calculation").set("formula", '"{{customer}} HQ"')
        view = root.xpath("//worksheet/table/view")[0]
        deps = etree.Element("datasource-dependencies", {"datasource": "Parameters"})
        copy_col = etree.SubElement(deps, "column", dict(col.attrib))
        etree.SubElement(copy_col, "calculation", {"class": "tableau", "formula": '"{{customer}} HQ"'})
        view.insert(0, deps)
    return edit(PUBLIC / "Cache.twbx", tmp_path / "copy.twbx", change)


def test_25_a_sheet_level_copy_of_a_string_parameter_is_filled_and_is_not_a_formula_hit(copy_book, tmp_path):
    assert tokens.formula_hits(etree.fromstring(twb_of(copy_book))) == []
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        t = make(copy_book, tmp_path, "c.template.twbx", tokens={"customer": "Your company"})
    out = _param_apply(t, tmp_path, "c.twbx", tokens={"customer": "ACME"})
    xml = twb_of(out)
    assert b"{{" not in xml
    copy_col = etree.fromstring(xml).xpath(
        "//datasource-dependencies[@datasource='Parameters']/column[@caption='State']")[0]
    assert copy_col.get("value") == '"ACME HQ"' and copy_col.find("calculation").get("formula") == '"ACME HQ"'


def test_25_a_token_in_a_real_calculation_is_still_a_hit(copy_book, tmp_path):
    def change(root):
        ds = root.xpath("//datasource[@name!='Parameters']")[0]
        col = etree.SubElement(ds, "column", {"caption": "Calc", "datatype": "string", "name": "[Calc]", "role": "dimension",
                                              "type": "nominal"})
        etree.SubElement(col, "calculation", {"class": "tableau", "formula": '"{{customer}}"'})
    src = edit(copy_book, tmp_path / "f.twbx", change)
    assert len(tokens.formula_hits(etree.fromstring(twb_of(src)))) == 1


# --- #26 ----------------------------------------------------------------------------------------------------


def _reserved_template(tmp_path, monkeypatch):
    monkeypatch.setattr(templates, "_now", lambda: "2026-10-04T00:00:00+00:00")

    def change(root):
        root.xpath("//worksheet/layout-options/title//run")[0].text = "Report {{file}} / {{sheet}}"
    src = edit(PUBLIC / "filtering.twb", tmp_path / "res.twb", change)
    return load_template(make_template(src, output_path=str(tmp_path / "res.template.twbx"),
                                       tokens={"file": "x", "sheet": "y"}))


def test_26_a_token_named_file_or_sheet_is_refused_in_a_sidecar_with_that_column(tmp_path, monkeypatch):
    t = _reserved_template(tmp_path, monkeypatch)
    both = tmp_path / "both.csv"
    both.write_text("file,sheet\na.csv,S1\n", encoding="utf-8")
    with pytest.raises(TemplateError, match="file, sheet are reserved"):
        read_inputs(both, t)
    only_file = tmp_path / "only.csv"
    only_file.write_text("file\na.csv\n", encoding="utf-8")
    with pytest.raises(TemplateError, match="file are reserved"):
        read_inputs(only_file, t)


def test_26_other_token_columns_still_work(book, tmp_path):
    t = make(book, tmp_path)
    side = tmp_path / "side.csv"
    side.write_text("file,sheet,customer\na.csv,S1,ACME\n", encoding="utf-8")
    assert read_inputs(side, t)["a.csv"] == {"sheet": "S1", "params": {}, "tokens": {"customer": "ACME"}}


# --- #27 ----------------------------------------------------------------------------------------------------


def _tooltip(root):
    sheet = root.xpath("//worksheet")[0]
    run = etree.SubElement(etree.SubElement(etree.SubElement(sheet, "tooltip"), "formatted-text"), "run")
    run.text = "For {{customer}}"


def test_27_a_token_in_a_place_that_is_not_scanned_is_reported_by_make_template(book, tmp_path):
    src = edit(book, tmp_path / "tip.twb", _tooltip)
    with pytest.warns(UserWarning, match=r"Sheet 1.*\{\{customer\}\}.*not a place.*left as typed"):
        t = make(src, tmp_path, "tip.template.twbx")
    assert [x["name"] for x in t.manifest["tokens"]] == ["customer", "author"]    # the scanned places are unchanged
    assert tokens.unscanned_hits(etree.parse(book).getroot()) == []     # a scanned token is not a hit


def test_27_an_unscanned_place_alone_declares_nothing_but_warns(tmp_path):
    src = edit(PUBLIC / "filtering.twb", tmp_path / "only.twb", _tooltip)
    with pytest.warns(UserWarning, match="not a place"):
        t = load_template(make_template(src, output_path=str(tmp_path / "only.template.twbx")))
    assert "tokens" not in t.manifest


def test_27_a_control_character_in_a_value_is_a_template_error(book, tmp_path):
    t = make(book, tmp_path)
    with pytest.raises(TemplateError, match="token 'customer'.*XML"):
        apply(t, tmp_path, tokens={"customer": "a\x0bb", "author": "x"})
    with pytest.raises(TemplateError, match="token 'author'.*XML"):
        apply(t, tmp_path, tokens={"customer": "ok", "author": "￾"})
    assert apply(t, tmp_path, tokens={"customer": "tab\there\nnew", "author": "x"})     # tab and newline are legal


def test_27_a_json_null_token_value_is_refused_not_turned_into_the_word_None(book, tmp_path):
    t = make(book, tmp_path)
    data, entry = csv_for(t, tmp_path)
    with pytest.raises(TemplateError, match="token 'customer'.*null"):
        templates.resolve_apply(t, data, datasource=entry, answers={"format": templates.ANSWERS_FORMAT, "tokens": {"customer": None}})
    with pytest.raises(TemplateError, match="token 'author'.*null"):
        templates.resolve_apply(t, data, datasource=entry, tokens={"author": None})


def test_27_apply_without_write_reports_a_token_that_would_stop_the_write(book, tmp_path, capsys):
    out = tmp_path / "dry.template.twbx"
    assert main(["template", "make", book, "-o", str(out), "--token", "author=Team"]) == 0
    data, entry = csv_for(load_template(str(out)), tmp_path)
    capsys.readouterr()
    assert main(["template", "apply", str(out), "--data", data]) == 0
    err = capsys.readouterr().err
    assert "customer" in err and "--write would stop" in err
    assert main(["template", "apply", str(out), "--data", data, "--token", "customer=ACME"]) == 0
    assert "--write would stop" not in capsys.readouterr().err
    assert main(["template", "apply", str(out), "--data", data, "--token", "customer=ACME", "--token", "nope=1"]) == 0
    err = capsys.readouterr().err
    assert "--write would stop" in err and "nope" in err


def test_27_a_control_character_does_not_crash_the_command_line(book, tmp_path, capsys):
    out = tmp_path / "cc.template.twbx"
    main(["template", "make", book, "-o", str(out), "--token", "author=Team"])
    data, entry = csv_for(load_template(str(out)), tmp_path)
    capsys.readouterr()
    rc = main(["template", "apply", str(out), "--data", data, "--token", "customer=a\x0bb", "--write",
               str(tmp_path / "x.twbx")])
    assert rc == 1 and "XML" in capsys.readouterr().err


def test_27_three_braces_are_one_literal_brace_around_a_token():
    assert tokens.render("{{{customer}}}", {"customer": "ACME"}) == "{ACME}"


# --- the corpus: the claim in docs/templates.md is backed here --------------------------------------------


@corpus
def test_every_filled_corpus_output_adds_no_schema_or_reference_errors(tmp_path):
    """A token in the first title of each corpus workbook that has one, filled: no schema error beyond what the
    workbook itself has, and the same dangling references as the same workbook applied with no token (the empty
    CSV cannot feed every field, so some references dangle with or without a token)."""
    from schema_check import new_schema_errors, twb_bytes
    from py_tbparse.verify import validate_workbook

    def refs(path):
        return {(r.check, r.datasource, r.detail) for r in validate_workbook(str(path)).itertuples()}

    checked = 0
    problems = []
    for n, path in enumerate(sorted(CORPUS.glob("*.twb"))):
        root = etree.parse(str(path)).getroot()
        runs = root.xpath("//worksheet/layout-options/title//run | //dashboard/layout-options/title//run")
        if not runs:
            continue
        work = tmp_path / f"w{n}"
        work.mkdir()
        shutil.copy(path, work / "plain.twb")
        runs[0].text = (runs[0].text or "") + " {{customer}}"
        (work / "tok.twb").write_bytes(etree.tostring(root, xml_declaration=True, encoding="utf-8"))
        outs = {}
        for name in ("plain", "tok"):
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                t = load_template(make_template(str(work / f"{name}.twb")))
            if next((e for e in t.manifest["datasources"] if e["fields"]), None) is None:
                break
            data, ds = csv_for(t, work)
            outs[name] = apply_template(t, data, datasource=ds, allow_missing=True, output_path=str(work / f"{name}.twbx"),
                                        **({"tokens": {"customer": "ACME & Sons"}} if name == "tok" else {}))
        if len(outs) == 2:
            for name, out in outs.items():
                (work / f"{name}_out.twb").write_bytes(twb_bytes(out))
            errors = new_schema_errors(str(path), twb_bytes(outs["tok"]))
            extra = refs(work / "tok_out.twb") - refs(work / "plain_out.twb")
            if errors or extra:
                problems.append((path.name, errors[:1], sorted(extra)[:1]))
            checked += 1
        shutil.rmtree(work)
    assert problems == []
    assert checked > 100
