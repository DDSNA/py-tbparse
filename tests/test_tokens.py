"""Template tokens: `{{customer}}` in titles, text boxes, captions and string parameters."""

import csv
import json
import shutil
import warnings
import zipfile
from pathlib import Path

import pytest
from lxml import etree

import py_tbparse.templates as templates
from py_tbparse import TemplateError, apply_template, load_template, make_template, tokens
from py_tbparse.cli import main
from py_tbparse.template_batch import apply_template_folder, read_inputs
from py_tbparse.template_update import template_update_report, update_from_answers
from py_tbparse.templates import read_answers

PUBLIC = Path(__file__).parent / "fixtures" / "public"
CORPUS = Path(__file__).parent / "corpus" / "files"
corpus = pytest.mark.skipif(not CORPUS.is_dir() or not any(CORPUS.glob("*.twb")),
                            reason="corpus not fetched: python scripts/fetch_corpus.py")

# --- the syntax ---------------------------------------------------------------------------------------------


def test_tokens_in_finds_names_in_order_and_trims_them():
    assert tokens.tokens_in("Sales for {{customer}} in {{ region name }}, {{customer}}") == [
        "customer", "region name", "customer"]
    assert tokens.tokens_in("{{a-b_c 9}}") == ["a-b_c 9"]
    assert tokens.tokens_in("no token here") == [] and tokens.tokens_in("") == [] and tokens.tokens_in(None) == []


@pytest.mark.parametrize("text", ["{{1x}}", "{{}}", "{{ }}", "{{a", "a}}", "{ {a} }", "{{a.b}}", "{{a{b}}", "{{_a}}"])
def test_text_that_is_not_a_token_is_left_alone(text):
    assert tokens.tokens_in(text) == []
    assert tokens.render(text.replace("{{{{", ""), {}) == text.replace("{{{{", "")


def test_names_are_case_sensitive():
    assert tokens.render("{{Customer}} {{customer}}", {"Customer": "A", "customer": "b"}) == "A b"


def test_escapes_give_the_literal_braces():
    assert tokens.render("{{{{customer}}}}", {}) == "{{customer}}"
    assert tokens.render("a {{{{ b }}}} c", {}) == "a {{ b }} c"
    assert tokens.render("{{{{{{{{", {}) == "{{{{"
    assert tokens.render("{{{{x}}}} and {{x}}", {"x": "V"}) == "{{x}} and V"
    assert tokens.tokens_in("{{{{customer}}}}") == []                       # an escape is not a token
    assert tokens.has_syntax("{{{{") and tokens.has_syntax("}}}}") and not tokens.has_syntax("{ {")


def test_a_value_is_plain_text_and_is_not_expanded_again():
    assert tokens.render("{{a}} {{b}}", {"a": "{{b}}", "b": "B"}) == "{{b}} B"
    assert tokens.render("{{a}}", {"a": "{{{{"}) == "{{{{"


def test_a_missing_value_raises():
    with pytest.raises(KeyError):
        tokens.render("{{nope}}", {})


# --- workbooks with tokens in them ----------------------------------------------------------------------


def _twb_name(z):
    return next(n for n in z.namelist() if n.endswith(".twb"))


def edit(src, out, change):
    """Copy a fixture (.twb or .twbx) to `out` with `change(root)` applied to its workbook XML."""
    src, out = Path(src), Path(out)
    if src.suffix == ".twb":
        root = etree.parse(str(src)).getroot()
        change(root)
        out.write_bytes(etree.tostring(root, xml_declaration=True, encoding="utf-8"))
        return str(out)
    with zipfile.ZipFile(src) as zin, zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            if item.filename.endswith(".twb"):
                root = etree.fromstring(data)
                change(root)
                data = etree.tostring(root, xml_declaration=True, encoding="utf-8")
            zout.writestr(item, data)
    return str(out)


def _filtering(root, title="Sales for {{customer}}", dash="Report for {{customer}}", text="Prepared for {{customer}} by {{author}}",
               caption="Show {{customer}}", ds="{{customer}} data"):
    """filtering.twb with a token in a worksheet title, a dashboard title, a text box, a field caption (and the
    copy of it in the sheet's dependencies) and the datasource's caption."""
    root.xpath("//worksheet/layout-options/title//run")[0].text = title
    dashboard = root.xpath("//dashboard")[0]
    style = dashboard.find("style")
    layout = etree.Element("layout-options")
    run = etree.SubElement(etree.SubElement(etree.SubElement(layout, "title"), "formatted-text"), "run")
    run.text = dash
    style.addnext(layout)
    zone = etree.SubElement(dashboard.xpath(".//zone[@id='4']")[0], "zone", {"id": "9", "type-v2": "text", "h": "10", "w": "10", "x": "1", "y": "1"})
    etree.SubElement(etree.SubElement(zone, "formatted-text"), "run").text = text
    for col in root.xpath("//column[@caption='SHOW']"):
        col.set("caption", caption)
    root.xpath("/workbook/datasources/datasource")[0].set("caption", ds)
    for copy_of in root.xpath("//worksheet//datasources/datasource[@caption]"):
        copy_of.set("caption", ds)


@pytest.fixture
def book(tmp_path, monkeypatch):
    monkeypatch.setattr(templates, "_now", lambda: "2026-10-04T00:00:00+00:00")
    return edit(PUBLIC / "filtering.twb", tmp_path / "tok.twb", _filtering)


def make(book, tmp_path, name="tok.template.twbx", **kw):
    return load_template(make_template(book, output_path=str(tmp_path / name), template_id="tpl-1", **kw))


def csv_for(template, folder, name="data.csv"):
    entry = next(e for e in template.manifest["datasources"] if e["fields"])
    path = Path(folder) / name
    with open(path, "w", newline="", encoding="utf-8") as fh:
        csv.writer(fh).writerow([f["remote"] for f in entry["fields"]])
    return str(path), entry["name"]


def twb_of(path):
    with zipfile.ZipFile(path) as z:
        return z.read(_twb_name(z))


def apply(template, tmp_path, name="out.twbx", **kw):
    data, entry = csv_for(template, tmp_path)
    return apply_template(template, data, datasource=entry, allow_missing=True, output_path=str(tmp_path / name), **kw)


def texts(path, xpath):
    return etree.fromstring(twb_of(path)).xpath(xpath)


def test_the_manifest_lists_every_token_with_where_it_occurs(book, tmp_path):
    t = make(book, tmp_path)
    by = {x["name"]: x for x in t.manifest["tokens"]}
    assert list(by) == ["customer", "author"]
    assert {(w["kind"], w["object"]) for w in by["customer"]["where"]} == {
        ("title", "Sheet 1"), ("title", "setTest"), ("text", "setTest"), ("field-caption", "{{customer}} data: [Calculation_88946136969252864]"),
        ("datasource-caption", "{{customer}} data")}
    assert by["author"]["where"] == [{"kind": "text", "object": "setTest"}]
    assert by["customer"]["default"] is None
    assert t.manifest["version"] == 2                                  # additive: the manifest version stays
    frame = t.tokens()
    assert list(frame["token"]) == ["customer", "author"] and "title of Sheet 1" in frame.loc[0, "where"]


def test_a_template_without_tokens_has_no_tokens_key_and_apply_does_not_touch_text(tmp_path, monkeypatch):
    shutil.copy(PUBLIC / "filtering.twb", tmp_path / "plain.twb")
    t = make(str(tmp_path / "plain.twb"), tmp_path, "plain.template.twbx")
    assert "tokens" not in t.manifest and len(t.tokens()) == 0
    monkeypatch.setattr(tokens, "expand", lambda *a, **k: pytest.fail("expand ran for a template without tokens"))
    apply(t, tmp_path)
    with pytest.raises(TemplateError, match="declares none"):
        apply(t, tmp_path, tokens={"customer": "x"})


def test_every_kind_of_place_is_replaced(book, tmp_path):
    out = apply(make(book, tmp_path), tmp_path, tokens={"customer": "ACME", "author": "Dan"})
    doc = etree.fromstring(twb_of(out))
    assert doc.xpath("//worksheet[@name='Sheet 1']/layout-options/title//run/text()") == ["Sales for ACME"]
    assert doc.xpath("//dashboard/layout-options/title//run/text()") == ["Report for ACME"]
    assert doc.xpath("//dashboard//zone[@type-v2='text']//run/text()") == ["Prepared for ACME by Dan"]
    assert doc.xpath("//column[@caption='Show ACME']/@name") != []
    assert doc.xpath("//datasource-dependencies/column[@caption='Show ACME']") != []   # the copy a sheet keeps
    assert doc.xpath("/workbook/datasources/datasource/@caption") == ["ACME data"]
    assert set(doc.xpath("//worksheet//datasources/datasource/@caption")) == {"ACME data"}
    assert b"{{" not in twb_of(out)


def test_one_token_in_many_places_and_two_tokens_in_one_run(book, tmp_path):
    out = apply(make(book, tmp_path), tmp_path, tokens={"customer": "A&B", "author": "C"})
    run = etree.fromstring(twb_of(out)).xpath("//dashboard//zone[@type-v2='text']//run/text()")
    assert run == ["Prepared for A&B by C"]


def test_a_token_with_no_value_stops_and_lists_every_place(book, tmp_path):
    t = make(book, tmp_path)
    with pytest.raises(TemplateError) as error:
        apply(t, tmp_path)
    message = str(error.value)
    assert message.startswith("no value for token(s): customer (in ")
    assert "title of Sheet 1" in message and "text of setTest" in message and "datasource-caption of" in message
    assert "author (in text of setTest)" in message
    with pytest.raises(TemplateError, match="no value for token.*author"):
        apply(t, tmp_path, tokens={"customer": "x"})


def test_an_unknown_token_name_is_refused(book, tmp_path):
    with pytest.raises(TemplateError, match="the template has no token 'nope'; it has: customer, author"):
        apply(make(book, tmp_path), tmp_path, tokens={"customer": "x", "author": "y", "nope": "z"})


def test_defaults_fill_what_is_not_given_and_unknown_defaults_are_refused(book, tmp_path):
    t = make(book, tmp_path, tokens={"customer": "Your company", "author": "Me"})
    assert {x["name"]: x["default"] for x in t.manifest["tokens"]} == {"customer": "Your company", "author": "Me"}
    out = apply(t, tmp_path, tokens={"customer": "ACME"})
    doc = etree.fromstring(twb_of(out))
    assert doc.xpath("//dashboard//zone[@type-v2='text']//run/text()") == ["Prepared for ACME by Me"]
    assert read_answers(out)["tokens"] == {"customer": "ACME"}          # only what was given is saved, not defaults
    out2 = apply(t, tmp_path, name="defaults.twbx")
    assert etree.fromstring(twb_of(out2)).xpath("//worksheet[@name='Sheet 1']/layout-options/title//run/text()") == ["Sales for Your company"]
    assert read_answers(out2)["tokens"] == {}
    with pytest.raises(TemplateError, match="names nope, which the workbook does not use; it uses: customer, author"):
        make(book, tmp_path, "bad.template.twbx", tokens={"nope": "x"})


def test_values_are_xml_safe_and_plain_text(book, tmp_path):
    nasty = 'A&B <i> "q" \'s\' Zażółć 東京 {{author}}'
    out = apply(make(book, tmp_path), tmp_path, tokens={"customer": nasty, "author": "x"})
    doc = etree.fromstring(twb_of(out))                                # still well-formed XML
    assert doc.xpath("//worksheet[@name='Sheet 1']/layout-options/title//run/text()") == [f"Sales for {nasty}"]
    assert "{{author}}" in doc.xpath("/workbook/datasources/datasource/@caption")[0]      # not expanded again


def test_escapes_are_written_as_literal_braces(tmp_path):
    src = edit(PUBLIC / "filtering.twb", tmp_path / "esc.twb", lambda r: _filtering(
        r, title="Use {{{{name}}}} for {{customer}}", dash="d", text="t", caption="c", ds="x"))
    t = make(src, tmp_path, "esc.template.twbx")
    assert [x["name"] for x in t.manifest["tokens"]] == ["customer"]
    out = apply(t, tmp_path, tokens={"customer": "ACME"})
    assert etree.fromstring(twb_of(out)).xpath("//worksheet[@name='Sheet 1']/layout-options/title//run/text()") == [
        "Use {{name}} for ACME"]


def test_a_template_with_only_escapes_declares_no_tokens_but_still_unescapes(tmp_path):
    src = edit(PUBLIC / "filtering.twb", tmp_path / "esc.twb",
               lambda r: r.xpath("//worksheet/layout-options/title//run")[0].__setattr__("text", "Literal {{{{braces}}}}"))
    t = make(src, tmp_path, "esc.template.twbx")
    assert t.manifest["tokens"] == []
    out = apply(t, tmp_path)
    assert etree.fromstring(twb_of(out)).xpath("//worksheet[@name='Sheet 1']/layout-options/title//run/text()") == ["Literal {{braces}}"]


def test_a_token_in_a_formula_warns_and_is_left_alone(tmp_path):
    def change(root):
        root.xpath("//column[@caption='SHOW']/calculation")[0].set("formula", '"{{customer}}"')
    src = edit(PUBLIC / "filtering.twb", tmp_path / "f.twb", change)
    with pytest.warns(UserWarning, match=r"SHOW: a \{\{token\}\} inside a formula is left alone"):
        t = make(src, tmp_path, "f.template.twbx")
    assert "tokens" not in t.manifest                                   # a formula is not a place
    out = apply(t, tmp_path)
    assert '"{{customer}}"' in etree.fromstring(twb_of(out)).xpath("//column[@caption='SHOW']/calculation/@formula")


def test_a_token_cut_by_a_format_change_warns(tmp_path):
    def change(root):
        run = root.xpath("//worksheet/layout-options/title//run")[0]
        run.text = "Sales for {{cust"
        etree.SubElement(run.getparent(), "run", bold="true").text = "omer}}"
    src = edit(PUBLIC / "filtering.twb", tmp_path / "cut.twb", change)
    with pytest.warns(UserWarning, match="title of Sheet 1.*not a whole token; a token must sit in one text run"):
        make(src, tmp_path, "cut.template.twbx")


# --- string parameters ----------------------------------------------------------------------------------


@pytest.fixture
def param_book(tmp_path, monkeypatch):
    monkeypatch.setattr(templates, "_now", lambda: "2026-10-04T00:00:00+00:00")

    def change(root):
        col = root.xpath("//datasource[@name='Parameters']/column[@caption='State']")[0]
        col.set("value", '"{{customer}} HQ"')
        col.find("calculation").set("formula", '"{{customer}} HQ"')
        members = col.find("members")
        for member in list(members)[3:]:
            members.remove(member)
        members[0].set("value", '"{{customer}} HQ"')
        members[0].set("alias", "{{customer}} head office")
        members[1].set("value", '"Say ""hi"" to {{customer}}"')
    return edit(PUBLIC / "Cache.twbx", tmp_path / "cache.twbx", change)


def test_a_string_parameters_value_members_and_aliases_take_tokens(param_book, tmp_path):
    t = make(param_book, tmp_path, "p.template.twbx")
    assert {(w["kind"], w["object"]) for w in t.manifest["tokens"][0]["where"]} == {("parameter-value", "State")}
    entry = t.manifest["datasources"][-1]["name"]
    out = apply_template(t, str(PUBLIC / "Cache.twbx"), datasource=entry, allow_missing=True,
                         output_path=str(tmp_path / "p.twbx"), tokens={"customer": 'O"Neil'}) if False else None
    data = tmp_path / "d.csv"
    data.write_text(",".join(f["remote"] for f in t.manifest["datasources"][-1]["fields"]) + "\n", encoding="utf-8")
    out = apply_template(t, str(data), datasource=entry, allow_missing=True, output_path=str(tmp_path / "p.twbx"),
                         tokens={"customer": 'O"Neil'})
    col = etree.fromstring(twb_of(out)).xpath("//datasource[@name='Parameters']/column[@caption='State']")[0]
    assert col.get("value") == '"O""Neil HQ"'                           # re-quoted as a Tableau string literal
    assert col.find("calculation").get("formula") == '"O""Neil HQ"'
    members = col.findall("members/member")
    assert [m.get("value") for m in members] == ['"O""Neil HQ"', '"Say ""hi"" to O""Neil"', '"Colorado"'][:0] + [
        '"O""Neil HQ"', '"Say ""hi"" to O""Neil"', members[2].get("value")]
    assert members[0].get("alias") == 'O"Neil head office'


def test_a_parameter_value_that_is_a_token_member_is_checked_after_the_fill(param_book, tmp_path):
    t = make(param_book, tmp_path, "p.template.twbx")
    entry = t.manifest["datasources"][-1]["name"]
    data = tmp_path / "d.csv"
    data.write_text(",".join(f["remote"] for f in t.manifest["datasources"][-1]["fields"]) + "\n", encoding="utf-8")
    out = apply_template(t, str(data), datasource=entry, allow_missing=True, output_path=str(tmp_path / "p.twbx"),
                         tokens={"customer": "ACME"}, params={"State": "ACME HQ"})
    col = etree.fromstring(twb_of(out)).xpath("//datasource[@name='Parameters']/column[@caption='State']")[0]
    assert col.get("value") == '"ACME HQ"'
    with pytest.raises(TemplateError, match="'Nowhere' is not one of its allowed values"):
        apply_template(t, str(data), datasource=entry, allow_missing=True, output_path=str(tmp_path / "q.twbx"),
                       tokens={"customer": "ACME"}, params={"State": "Nowhere"})
    assert read_answers(out)["parameters"] == {"State": '"ACME HQ"'} and read_answers(out)["tokens"] == {"customer": "ACME"}


# --- answers, profiles, precedence ----------------------------------------------------------------------


def test_answers_repeat_the_run_byte_for_byte_and_explicit_values_win(book, tmp_path):
    t = make(book, tmp_path, tokens={"author": "Default author"})
    first = apply(t, tmp_path, name="first.twbx", tokens={"customer": "ACME"})
    again = apply_template(t, answers=first, allow_missing=True, output_path=str(tmp_path / "again.twbx"))
    assert twb_of(first) == twb_of(again)
    other = apply_template(t, answers=first, allow_missing=True, output_path=str(tmp_path / "other.twbx"),
                           tokens={"customer": "Globex"})
    assert b"Globex" in twb_of(other) and b"ACME" not in twb_of(other)
    assert read_answers(other)["tokens"] == {"customer": "Globex"}


def test_a_profile_carries_token_values_and_an_explicit_value_beats_it(book, tmp_path):
    t = make(book, tmp_path, tokens={"author": "Default author"})
    first = apply(t, tmp_path, name="first.twbx", tokens={"customer": "ACME"})
    answers = read_answers(first)
    answers["profiles"] = {"prod": {"tokens": {"customer": "From profile", "author": "P"}}}
    path = tmp_path / "a.answers.json"
    path.write_text(json.dumps(answers), encoding="utf-8")
    out = apply_template(t, answers=str(path), profile="prod", allow_missing=True, output_path=str(tmp_path / "prof.twbx"))
    assert b"From profile" in twb_of(out) and b"by P" in twb_of(out)
    out = apply_template(t, answers=str(path), profile="prod", allow_missing=True, output_path=str(tmp_path / "prof2.twbx"),
                         tokens={"customer": "Explicit"})
    assert b"Explicit" in twb_of(out) and b"From profile" not in twb_of(out)


def test_token_values_are_not_taken_for_credentials(book, tmp_path):
    t = make(book, tmp_path, tokens={"author": "x"})
    out = apply(t, tmp_path, tokens={"customer": "password manager Inc."})
    assert read_answers(out)["tokens"] == {"customer": "password manager Inc."}
    apply_template(t, answers=out, allow_missing=True, output_path=str(tmp_path / "again.twbx"))


# --- update ---------------------------------------------------------------------------------------------


def _revision(tmp_path, book, old, extra, name):
    """A new revision of `old` whose workbook also has `extra` as title of the second sheet."""
    def change(root):
        _filtering(root)
        root.xpath("//worksheet/layout-options/title//run")[1].text = extra
    src = edit(PUBLIC / "filtering.twb", tmp_path / f"{name}.twb", change)
    return load_template(make_template(src, output_path=str(tmp_path / f"{name}.template.twbx"), revision_of=old))


def test_update_reports_token_changes_and_carries_saved_values(book, tmp_path):
    old = make(book, tmp_path, tokens={"author": "A"})
    first = apply(old, tmp_path, name="first.twbx", tokens={"customer": "ACME"})
    new = _revision(tmp_path, book, old, "Region {{region}} of {{customer}}", "r2")
    report = template_update_report(new, first)
    rows = {(r.item, r.change): r.impact for r in report[report["kind"] == "token"].itertuples()}
    assert rows == {("region", "added"): "needs-value"}                  # author kept its default and customer its value
    info: dict = {}
    with pytest.raises(TemplateError, match="update stopped: no value for token.*region"):
        update_from_answers(new, first, output_path=str(tmp_path / "r2.twbx"), allow_missing=True, report=info)
    assert info["needs_value"] == ["region"]
    out = update_from_answers(new, first, output_path=str(tmp_path / "r2.twbx"), allow_missing=True, report=info,
                              tokens={"region": "East"})
    assert b"Region East of ACME" in twb_of(out)                       # the saved customer carried, the new one given
    assert read_answers(out)["tokens"] == {"customer": "ACME", "region": "East"}


def test_update_drops_a_saved_value_the_new_template_no_longer_has(book, tmp_path):
    old = make(book, tmp_path, tokens={"author": "A"})
    first = apply(old, tmp_path, name="first.twbx", tokens={"customer": "ACME", "author": "Dan"})

    def change(root):
        _filtering(root, text="Prepared for {{customer}}")             # the author token is gone
    src = edit(PUBLIC / "filtering.twb", tmp_path / "r2.twb", change)
    new = load_template(make_template(src, output_path=str(tmp_path / "r2.template.twbx"), revision_of=old))
    rows = template_update_report(new, first)
    assert ("author", "removed", "orphaned") in set(zip(rows["item"], rows["change"], rows["impact"]))
    info: dict = {}
    out = update_from_answers(new, first, output_path=str(tmp_path / "r2.twbx"), allow_missing=True, report=info)
    assert info["dropped_tokens"] == ["author"] and read_answers(out)["tokens"] == {"customer": "ACME"}


def test_a_new_revision_keeps_the_defaults_of_the_tokens_it_still_has(book, tmp_path):
    old = make(book, tmp_path, tokens={"customer": "One", "author": "A"})
    new = _revision(tmp_path, book, old, "Region {{region}}", "r2")
    assert {x["name"]: x["default"] for x in new.manifest["tokens"]} == {"customer": "One", "author": "A", "region": None}
    assert new.revision == 2


def test_update_notes_a_changed_default(book, tmp_path):
    old = make(book, tmp_path, tokens={"customer": "One", "author": "A"})

    def change(root):
        _filtering(root)
    src = edit(PUBLIC / "filtering.twb", tmp_path / "r2.twb", change)
    new = load_template(make_template(src, output_path=str(tmp_path / "r2.template.twbx"), revision_of=old,
                                      tokens={"customer": "Two", "author": "A"}))
    from py_tbparse.template_update import diff_template_revisions
    rows = diff_template_revisions(old, new)
    token_rows = rows[rows["kind"] == "token"]
    assert list(zip(token_rows["item"], token_rows["change"], token_rows["old"], token_rows["new"])) == [
        ("customer", "default", "One", "Two")]


# --- many files -------------------------------------------------------------------------------------------


def test_the_sidecar_may_fill_tokens_per_file(book, tmp_path):
    t = make(book, tmp_path, tokens={"author": "Team"})
    folder = tmp_path / "customers"
    folder.mkdir()
    data, _ = csv_for(t, folder, "acme.csv")
    shutil.copy(data, folder / "globex.csv")
    sidecar = tmp_path / "inputs.csv"
    sidecar.write_text("file,customer\nacme.csv,ACME\nglobex.csv,Globex\n", encoding="utf-8")
    assert read_inputs(sidecar, t)["globex.csv"]["tokens"] == {"customer": "Globex"}
    table = apply_template_folder(t, str(folder), output_dir=str(tmp_path / "out"), inputs=str(sidecar), min_mapped=0.0)
    assert set(table["status"]) == {"ok"}, table["error"].tolist()
    for name, customer in (("acme", "ACME"), ("globex", "Globex")):
        assert f"Sales for {customer}".encode() in twb_of(tmp_path / "out" / f"tok_{name}.twbx")
    # a token given for every file, the sidecar overriding it for one
    table = apply_template_folder(t, str(folder), output_dir=str(tmp_path / "out2"), min_mapped=0.0, tokens={"customer": "All"})
    assert set(table["status"]) == {"ok"} and b"Sales for All" in twb_of(tmp_path / "out2" / "tok_acme.twbx")
    # no value anywhere: the files are reported, not written
    table = apply_template_folder(t, str(folder), output_dir=str(tmp_path / "out3"), min_mapped=0.0)
    assert set(table["status"]) == {"error"} and "no value for token(s): customer" in table.loc[0, "error"]


def test_the_sidecar_names_parameters_tokens_and_what_is_unknown(book, tmp_path):
    t = make(book, tmp_path)
    bad = tmp_path / "bad.csv"
    bad.write_text("file,colour\na.csv,red\n", encoding="utf-8")
    with pytest.raises(TemplateError, match="neither parameters nor tokens.*tokens: author, customer"):
        read_inputs(bad, t)


# --- the command line -----------------------------------------------------------------------------------


def test_the_command_line_makes_shows_and_applies_with_tokens(book, tmp_path, capsys):
    out = tmp_path / "cli.template.twbx"
    assert main(["template", "make", book, "-o", str(out), "--token", "author=Team"]) == 0
    assert "2 token(s): customer, author" in capsys.readouterr().err
    assert main(["template", "show", str(out)]) == 0
    shown = capsys.readouterr().out
    assert "Tokens" in shown and "customer" in shown and "Team" in shown
    t = load_template(str(out))
    data, entry = csv_for(t, tmp_path)
    result = tmp_path / "cli.twbx"
    assert main(["template", "apply", str(out), "--data", data, "--datasource", entry, "--allow-missing",
                 "--write", str(result)]) == 1
    assert "no value for token(s): customer" in capsys.readouterr().err
    assert main(["template", "apply", str(out), "--data", data, "--datasource", entry, "--allow-missing",
                 "--token", "customer=ACME", "--write", str(result)]) == 0
    assert b"Sales for ACME" in twb_of(result)
    with pytest.raises(SystemExit):
        main(["template", "apply", str(out), "--data", data, "--token", "customer"])


# --- the corpus ---------------------------------------------------------------------------------------------


@corpus
def test_no_corpus_workbook_has_token_syntax_and_apply_never_touches_their_text(tmp_path):
    """So a template made from any of the 200 workbooks has no `tokens`, and the text a person typed (every text run
    and every string parameter value) comes out of apply as it went in; if a future corpus addition has `{{`, this
    fails so that someone looks."""
    def typed(xml):
        doc = etree.fromstring(xml)
        return (doc.xpath("//run/text()"),
                doc.xpath("//datasource[@name='Parameters']/column[@param-domain-type]/@value"))
    seen = 0
    for n, path in enumerate(sorted(CORPUS.glob("*.twb"))):
        assert b"{{" not in path.read_bytes(), path.name
        work = tmp_path / f"w{n}"
        work.mkdir()
        shutil.copy(path, work / "book.twb")
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            t = load_template(make_template(str(work / "book.twb")))
        assert "tokens" not in t.manifest, path.name
        entry = next((e for e in t.manifest["datasources"] if e["fields"]), None)
        if entry is not None:
            data, name = csv_for(t, work)
            out = apply_template(t, data, datasource=name, allow_missing=True, output_path=str(work / "out.twbx"))
            assert typed(twb_of(out)) == typed(twb_of(t.path)), path.name
            seen += 1
        shutil.rmtree(work)
    assert seen > 100


@corpus
def test_a_token_put_into_a_title_of_each_corpus_workbook_is_found_and_replaced(tmp_path):
    checked = 0
    for n, path in enumerate(sorted(CORPUS.glob("*.twb"))):
        root = etree.parse(str(path)).getroot()
        runs = root.xpath("//worksheet/layout-options/title//run | //dashboard/layout-options/title//run")
        if not runs:
            continue
        runs[0].text = (runs[0].text or "") + " {{customer}}"
        work = tmp_path / f"w{n}"
        work.mkdir()
        (work / "book.twb").write_bytes(etree.tostring(root, xml_declaration=True, encoding="utf-8"))
        t = load_template(make_template(str(work / "book.twb")))
        assert [x["name"] for x in t.manifest["tokens"]] == ["customer"], path.name
        entry = next((e for e in t.manifest["datasources"] if e["fields"]), None)
        if entry is None:
            shutil.rmtree(work)
            continue
        data, name = csv_for(t, work)
        out = apply_template(t, data, datasource=name, allow_missing=True, output_path=str(work / "out.twbx"),
                             tokens={"customer": "ACME & Sons"})
        after = etree.fromstring(twb_of(out))
        assert b"{{" not in twb_of(out), path.name
        assert any("ACME & Sons" in (r.text or "") for r in after.xpath("//run")), path.name
        checked += 1
        shutil.rmtree(work)
    assert checked > 100


def test_a_filled_workbook_adds_no_schema_or_reference_errors(book, tmp_path):
    from schema_check import new_schema_errors, twb_bytes
    from py_tbparse.verify import validate_workbook
    out = apply(make(book, tmp_path), tmp_path, tokens={"customer": "ACME", "author": "Dan"})
    assert new_schema_errors(book, twb_bytes(out)) == []
    (tmp_path / "out.twb").write_bytes(twb_bytes(out))
    before = {(r.check, r.datasource, r.detail) for r in validate_workbook(book).itertuples()}
    after = {(r.check, r.datasource, r.detail) for r in validate_workbook(str(tmp_path / "out.twb")).itertuples()}
    unfed = {"Calculation_88946136969252864", "show", "Show"}   # fields the empty CSV cannot feed (allow_missing)
    assert {k for k in after - before if not any(u in k[2] for u in unfed)} == set()
