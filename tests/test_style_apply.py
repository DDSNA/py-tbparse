"""`style apply` for the workbook scope (WP7 slice 2b): plan_style, build_styled, apply_style. A format the target
already has is explicit and is kept unless force; the output is always a new file. Nothing here was opened in
Tableau; the schema check proves structure only. Fixtures: tests/fixtures/style/format-*.twb (hand made)."""

import json
import sys
import zipfile
from pathlib import Path

import pytest
from lxml import etree

sys.path.insert(0, str(Path(__file__).parent))

from schema_check import new_schema_errors   # noqa: E402

from py_tbparse import (   # noqa: E402
    StyleError,
    TwbParser,
    apply_style,
    build_styled,
    cli,
    extract_style,
    load_style,
    plan_style,
    read_palettes,
)

FIX = Path(__file__).parent / "fixtures"
STYLE = FIX / "style"
SRC = str(STYLE / "format-source.twb")
TARGET = str(STYLE / "format-target.twb")
BARE = str(STYLE / "format-bare.twb")
V2 = STYLE / "format.style.json"
TWBX = str(FIX / "test_for_zip.twbx")

FONTS = {"all": {"font-family": "Segoe UI", "font-size": "10"}}


def _style(**sections):
    base = json.loads(V2.read_text(encoding="utf-8"))
    base.update(sections)
    return base


def _fonts_only(fonts=None, rules=None):
    return _style(fonts=fonts if fonts is not None else FONTS, workbook_rules=rules or [], dashboard={}, sheet_defaults=[])


def _doc(data: bytes):
    return etree.fromstring(data).getroottree()


def _rule(doc, element):
    return doc.xpath("/workbook/style/style-rule[@element=$e]", e=element)


def _formats(doc, element):
    return [(f.get("attr"), f.get("value"), f.get("scope")) for f in _rule(doc, element)[0].findall("format")]


def _c14n(path_or_bytes):
    root = etree.fromstring(path_or_bytes if isinstance(path_or_bytes, bytes) else Path(path_or_bytes).read_bytes())
    return etree.tostring(root, method="c14n")


def _actions(plan):
    return list(zip(plan["where"], plan["attr"], plan["action"]))


def test_apply_adds_missing_style_block(tmp_path):
    data = build_styled(BARE, _fonts_only(), scopes=("workbook",))
    doc = _doc(data)
    children = [c.tag for c in doc.getroot() if isinstance(c.tag, str)]
    i = children.index("style")
    assert children[i - 1] == "preferences" and children[i + 1] == "datasources"
    assert _formats(doc, "all") == [("font-family", "Segoe UI", None), ("font-size", "10", None)]
    out = tmp_path / "bare_styled.twb"
    out.write_bytes(data)
    assert new_schema_errors(BARE, str(out)) == []
    assert len(TwbParser(str(out)).get_datasources()) == len(TwbParser(BARE).get_datasources())
    # the rest of the workbook is as it was: dropping the new block gives back the input
    again = _doc(data)
    again.getroot().remove(again.getroot().find("style"))
    assert _c14n(etree.tostring(again)) == _c14n(BARE)
    # the block is indented like its neighbours
    text = data.decode("utf-8")
    assert "\n  <style>\n    <style-rule element=\"all\">\n      <format attr=\"font-family\" value=\"Segoe UI\"/>" in text


def test_apply_adds_rule_and_format():
    rep = {}
    data = build_styled(TARGET, _fonts_only(fonts={"title": {"font-family": "Arial", "color": "#1A3A5C"}, "tooltip": {"font-size": "9"}}),
                        scopes=("workbook",), report=rep)
    doc = _doc(data)
    assert _formats(doc, "title") == [("font-family", "Arial", None), ("color", "#1A3A5C", None)]   # appended at the end
    assert _formats(doc, "tooltip") == [("font-size", "9", None)]
    elements = [r.get("element") for r in doc.xpath("/workbook/style/style-rule")]
    assert elements == ["title", "tooltip"]                                                          # new rule after the last real one
    assert rep["added"] == ["workbook: title/color", "workbook: tooltip/font-size"] and rep["same"] == ["workbook: title/font-family"]
    assert new_schema_errors(TARGET, data) == []


def test_new_rule_goes_after_the_last_real_rule_and_first_in_a_flag_only_style(tmp_path):
    # SRC has real rules after a flag tag: the new rule goes after the last real one, the flag tag stays first
    data = build_styled(SRC, _fonts_only(fonts={}, rules=[{"element": "worksheet", "formats": [{"attr": "color", "value": "#000000"}]}]),
                        scopes=("workbook",))
    doc = _doc(data)
    kids = [c.tag for c in doc.xpath("/workbook/style")[0]]
    assert kids[0].startswith("_.fcp.") and kids[1:] == ["style-rule"] * 4
    assert _formats(doc, "worksheet")[-1] == ("color", "#000000", None)
    # a <style> holding only a flag tag gets the rule first
    wb = etree.parse(BARE)
    root = wb.getroot()
    st = etree.Element("style")
    etree.SubElement(st, "_.fcp.MarkAnimation.true...style-rule", element="animation")
    root.find("datasources").addprevious(st)
    p = tmp_path / "flag.twb"
    p.write_bytes(etree.tostring(wb, xml_declaration=True, encoding="utf-8"))
    kids = [c.tag for c in _doc(build_styled(str(p), _fonts_only(), scopes=("workbook",))).xpath("/workbook/style")[0]]
    assert kids == ["style-rule", "_.fcp.MarkAnimation.true...style-rule"]


def test_explicit_format_kept():
    rep = {}
    data = build_styled(TARGET, _fonts_only(fonts={"title": {"font-family": "Segoe UI Semibold"}}), scopes=("workbook",), report=rep)
    assert rep["skipped"] == ["workbook: title/font-family"] and rep["added"] == [] and rep["forced"] == []
    assert _c14n(data) == _c14n(TARGET)                               # nothing to write: the tree is unchanged
    assert _formats(_doc(data), "title") == [("font-family", "Arial", None)]
    # the same holds for a default-looking value: any present format is explicit
    plan = plan_style(TARGET, _fonts_only(fonts={"title": {"font-family": "Tableau Book"}}), scopes=("workbook",))
    assert list(plan["action"]) == ["skip"] and plan["current"][0] == "Arial"
    assert "--force" in plan["reason"][0]


def test_force_replaces_in_place():
    rep = {}
    style = _fonts_only(fonts={"title": {"font-family": "Segoe UI Semibold", "font-size": "14"}})
    data = build_styled(TARGET, style, scopes=("workbook",), force=True, report=rep)
    doc = _doc(data)
    assert _formats(doc, "title") == [("font-family", "Segoe UI Semibold", None), ("font-size", "14", None)]   # position kept
    assert rep["forced"] == ["workbook: title/font-family"] and rep["added"] == ["workbook: title/font-size"]
    assert rep["counts"]["workbook"]["applied"] == 2
    # a clash under force is still reported as force in the plan, never as skip
    assert list(plan_style(TARGET, style, scopes=("workbook",), force=True)["action"]) == ["force", "add"]


def test_same_value_is_same():
    # colour case does not matter; other strings are compared exactly
    style = _fonts_only(fonts={"title": {"color": "#1a3a5c"}})
    assert list(plan_style(SRC, style, scopes=("workbook",))["action"]) == ["same"]
    assert list(plan_style(SRC, _fonts_only(fonts={"title": {"font-family": "tableau semibold"}}), scopes=("workbook",))["action"]) == ["skip"]
    assert list(plan_style(SRC, _fonts_only(fonts={"all": {"font-size": "10"}}), scopes=("workbook",))["action"]) == ["same"]
    assert list(plan_style(SRC, _fonts_only(fonts={"all": {"font-size": "10.0"}}), scopes=("workbook",))["action"]) == ["skip"]


def test_field_format_is_not_the_same_key():
    # SRC has worksheet/font-size bound to a field; a name-free worksheet font-size is a different key and is added
    plan = plan_style(SRC, _fonts_only(fonts={"worksheet": {"font-size": "9"}}), scopes=("workbook",))
    assert list(plan["action"]) == ["add"]
    doc = _doc(build_styled(SRC, _fonts_only(fonts={"worksheet": {"font-size": "9"}}), scopes=("workbook",)))
    fmts = doc.xpath("/workbook/style/style-rule[@element='worksheet']/format")
    assert [(f.get("attr"), f.get("field") is not None) for f in fmts] == [("background-color", False), ("font-size", True), ("font-size", False)]


def test_scope_attribute_keyed_separately():
    rules = [{"element": "worksheet", "formats": [{"attr": "color", "value": "#111111", "scope": "rows"},
                                                   {"attr": "color", "value": "#222222", "scope": "cols"}]}]
    data = build_styled(BARE, _fonts_only(fonts={}, rules=rules), scopes=("workbook",))
    assert _formats(_doc(data), "worksheet") == [("color", "#111111", "rows"), ("color", "#222222", "cols")]
    one = [{"element": "worksheet", "formats": [{"attr": "color", "value": "#111111", "scope": "rows"}]}]
    plan = plan_style(_write_tmp(data), _fonts_only(fonts={}, rules=one), scopes=("workbook",))
    assert list(plan["action"]) == ["same"] and plan["where"][0] == "worksheet (rows)"
    other = [{"element": "worksheet", "formats": [{"attr": "color", "value": "#333333", "scope": "cols"}]}]
    assert list(plan_style(_write_tmp(data), _fonts_only(fonts={}, rules=other), scopes=("workbook",))["action"]) == ["skip"]
    plain = [{"element": "worksheet", "formats": [{"attr": "color", "value": "#333333"}]}]
    assert list(plan_style(_write_tmp(data), _fonts_only(fonts={}, rules=plain), scopes=("workbook",))["action"]) == ["add"]


_TMP: list = []


def _write_tmp(data: bytes) -> str:
    import tempfile
    d = tempfile.mkdtemp(dir=_TMP[0]) if _TMP else tempfile.mkdtemp()
    p = Path(d) / "t.twb"
    p.write_bytes(data)
    return str(p)


@pytest.fixture(autouse=True)
def _tmpdir(tmp_path):
    _TMP[:] = [str(tmp_path)]
    yield
    _TMP.clear()


def test_on_clash_fail_writes_nothing(tmp_path, capsys):
    style = _fonts_only(fonts={"title": {"font-family": "Segoe UI Semibold"}, "all": {"font-size": "10"}})
    plan = plan_style(TARGET, style, scopes=("workbook",), on_clash="fail")
    assert list(plan["action"]) == ["fail", "add"]
    with pytest.raises(StyleError, match=r"title/font-family \(target has 'Arial'"):
        build_styled(TARGET, style, scopes=("workbook",), on_clash="fail")
    out = tmp_path / "x_styled.twb"
    with pytest.raises(StyleError):
        apply_style(TARGET, style, out, scopes=("workbook",), on_clash="fail")
    assert not out.exists()
    sj = tmp_path / "s.style.json"
    sj.write_text(json.dumps(style), encoding="utf-8")
    assert cli.main(["style", "apply", str(sj), TARGET, "--scope", "workbook", "--on-clash", "fail", "--write", "-o", str(out)]) == 1
    assert not out.exists() and "writes nothing" in capsys.readouterr().err
    with pytest.raises(StyleError, match="contradict"):
        plan_style(TARGET, style, force=True, on_clash="fail")
    with pytest.raises(StyleError, match="on_clash must be"):
        plan_style(TARGET, style, on_clash="rename")
    assert cli.main(["style", "apply", str(sj), TARGET, "--on-clash", "fail", "--force"]) == 1


def test_fcp_elements_byte_equal():
    before = etree.tostring(etree.parse(SRC).xpath("/workbook/style/*[starts-with(local-name(), '_.fcp.')]")[0])
    data = build_styled(SRC, _fonts_only(fonts={"all": {"font-family": "Arial"}, "tooltip": {"color": "#000000"}}),
                        scopes=("workbook",), force=True)
    after = _doc(data).xpath("/workbook/style/*[starts-with(local-name(), '_.fcp.')]")
    assert len(after) == 1 and etree.tostring(after[0]) == before
    # the manifest's flags and the datasource rules are untouched too
    assert _c14n(etree.tostring(_doc(data).xpath("/workbook/document-format-change-manifest")[0])) == \
        _c14n(etree.tostring(etree.parse(SRC).xpath("/workbook/document-format-change-manifest")[0]))


def test_unsupported_reported(tmp_path):
    plan = plan_style(BARE, V2)                                    # default scopes: workbook and dashboards
    by = {}
    for r in plan.itertuples():
        by.setdefault(r.scope, set()).add(r.action)
    assert by == {"workbook": {"add"}, "dashboards": {"unsupported"}}
    assert "WP7-2c" in plan[plan["scope"] == "dashboards"]["reason"].iloc[0]
    sheets = plan_style(BARE, V2, scopes=("sheets",))
    assert list(sheets["action"]) == ["unsupported"] and "WP7-2d" in sheets["reason"][0]
    rep = {}
    apply_style(BARE, V2, tmp_path / "o.twb", report=rep)
    assert rep["counts"]["dashboards"]["unsupported"] == 10 and rep["counts"]["workbook"]["added"] == 6
    assert rep["unsupported"][0].startswith("dashboards: ")
    # nothing of the dashboard section reached the file: the zones are as they were
    assert _doc((tmp_path / "o.twb").read_bytes()).xpath("count(//dashboard//zone-style)") == \
        etree.parse(BARE).xpath("count(//dashboard//zone-style)")
    with pytest.raises(StyleError, match="unknown scope"):
        plan_style(BARE, V2, scopes=("everything",))


def test_self_apply_is_noop(tmp_path):
    for wb in (SRC, TARGET, BARE):
        style = extract_style(wb)
        rep = {}
        data = build_styled(wb, style, scopes=("workbook",), report=rep)
        assert rep["added"] == [] and rep["skipped"] == [] and rep["forced"] == []
        assert _c14n(data) == _c14n(wb), wb
        plan = plan_style(wb, style)                                # default scopes: only same / unsupported
        assert set(plan["action"]) <= {"same", "unsupported"}
        assert not (plan["scope"].eq("workbook") & plan["action"].eq("skip")).any()
    # a workbook given directly as the style is extracted on the fly: the same thing
    assert set(plan_style(SRC, SRC, scopes=("workbook",))["action"]) == {"same"}


def test_apply_extracted_style_to_other_workbook(tmp_path):
    out = apply_style(BARE, SRC, tmp_path / "bare_from_src.twb", scopes=("workbook",))
    assert extract_style(out, scopes=("workbook",))["fonts"] == extract_style(SRC, scopes=("workbook",))["fonts"]
    assert extract_style(out, scopes=("workbook",))["workbook_rules"] == extract_style(SRC, scopes=("workbook",))["workbook_rules"]
    assert new_schema_errors(BARE, out) == []


def test_never_overwrites_files(tmp_path):
    work = tmp_path / "t.twb"
    work.write_bytes(Path(BARE).read_bytes())
    before = work.read_bytes()
    style = _fonts_only()
    with pytest.raises(FileExistsError, match="the input"):
        apply_style(str(work), style, work, overwrite=True)
    with pytest.raises(FileExistsError, match="the input"):
        apply_style(str(work), style, work)
    assert work.read_bytes() == before
    default = apply_style(str(work), style, scopes=("workbook",))
    assert Path(default).name == "t_styled.twb" and Path(default).parent == tmp_path
    with pytest.raises(FileExistsError, match="refusing to overwrite"):
        apply_style(str(work), style)
    first = Path(default).read_bytes()
    apply_style(str(work), _fonts_only(fonts={"all": {"font-size": "12"}}), overwrite=True, scopes=("workbook",))
    assert Path(default).read_bytes() != first and work.read_bytes() == before
    with pytest.raises(StyleError, match="must end in .twb"):
        apply_style(str(work), style, tmp_path / "o.twbx")
    tps = STYLE / "Preferences.tps"
    with pytest.raises(StyleError, match="no formatting"):
        apply_style(str(tps), style, tmp_path / "o.tps")
    with pytest.raises(StyleError, match="no formatting"):
        plan_style(str(tps), style)
    assert not (tmp_path / "o.tps").exists() and not (tmp_path / "o.twbx").exists()
    with pytest.raises(StyleError, match="style must be"):
        plan_style(BARE, str(tps))


def test_twbx_members_copied(tmp_path):
    out = apply_style(TWBX, _fonts_only(), tmp_path / "zip_styled.twbx", scopes=("workbook",))
    with zipfile.ZipFile(TWBX) as a, zipfile.ZipFile(out) as b:
        assert a.namelist() == b.namelist()
        twb = next(n for n in a.namelist() if n.endswith(".twb"))
        for n in a.namelist():
            if n != twb:
                assert a.read(n) == b.read(n), n
        assert b.read(twb) != a.read(twb)
        assert b"font-family" in b.read(twb)
    assert TwbParser(out).xml_doc.xpath("/workbook/style/style-rule[@element='all']")


def test_flagged_style_block_is_kept_and_reported(tmp_path):
    # test_for_zip.twbx, like 90 of 200 corpus workbooks, has its style only as <_.fcp.X.false...style>
    flagged = "_.fcp.AnimationOnByDefault.false...style"
    with zipfile.ZipFile(TWBX) as z:
        twb = z.read(next(n for n in z.namelist() if n.endswith(".twb")))
    before = etree.tostring(etree.fromstring(twb).find(flagged))
    rep = {}
    out = apply_style(TWBX, _fonts_only(), tmp_path / "f.twbx", scopes=("workbook",), report=rep)
    with zipfile.ZipFile(out) as z:
        root = etree.fromstring(z.read(next(n for n in z.namelist() if n.endswith(".twb"))))
    assert etree.tostring(root.find(flagged)) == before                 # never edited
    tags = [c.tag for c in root if isinstance(c.tag, str)]
    assert tags.index("preferences") < tags.index("style") < tags.index(flagged) < tags.index("datasources")
    assert any("feature-flagged" in w for w in rep["warnings"])
    plan = plan_style(TWBX, _fonts_only(), scopes=("workbook",))
    assert "feature-flagged" in plan["reason"][0] and "unverified" in plan["reason"][0]


def test_report_counts():
    rep = {}
    style = _fonts_only(fonts={"all": {"font-size": "10", "font-weight": "bold"}, "title": {"font-family": "Arial", "font-size": "20"}},
                        rules=[{"element": "worksheet", "formats": [{"attr": "background-color", "value": "#fff"}]}])
    build_styled(TARGET, style, scopes=("workbook",), report=rep)
    c = rep["counts"]["workbook"]
    assert c == {"added": 4, "same": 1, "skipped": 0, "forced": 0, "unsupported": 0, "no_target": 0, "applied": 4}
    assert rep["warnings"] and all("may not exist" in w for w in rep["warnings"])
    rep = {}
    build_styled(SRC, _fonts_only(fonts={"title": {"font-family": "Arial", "color": "#1A3A5C"}}), scopes=("workbook",), report=rep)
    assert rep["counts"]["workbook"]["skipped"] == 1 and rep["counts"]["workbook"]["same"] == 1
    assert list(rep["counts"]) == ["workbook"]


def test_unknown_names_raise():
    with pytest.raises(StyleError, match="no dashboard called 'Nope'"):
        plan_style(SRC, V2, dashboards=["Nope"])
    with pytest.raises(StyleError, match="no sheet called 'Nope'"):
        plan_style(SRC, V2, sheets=["Sheet 1", "Nope"])
    assert len(plan_style(SRC, V2, dashboards=["setTest"], sheets=["Sheet 1"], scopes=("workbook",))) == 6


def test_style_from_v1_file_and_palettes(tmp_path):
    v1 = {"format": "py-tbparse-style", "version": 1, "name": "old", "description": "", "created": "x", "py_tbparse_version": "0",
          "sources": [], "palettes": [{"name": "A", "type": "regular", "colors": ["#112233"], "attrs": {}}]}
    p = tmp_path / "old.style.json"
    p.write_text(json.dumps(v1), encoding="utf-8")
    assert plan_style(BARE, p).empty
    plain = apply_style(BARE, p, tmp_path / "plain.twb")
    assert read_palettes(plain) == []                                  # palettes are ignored unless asked
    withp = apply_style(BARE, p, tmp_path / "withp.twb", palettes=True)
    assert [x["name"] for x in read_palettes(withp)] == ["A"]
    # palettes and formatting together, in one file; the palette clash policy is its own
    rep = {}
    both = apply_style(BARE, V2, tmp_path / "both.twb", scopes=("workbook",), palettes=True, report=rep)
    assert [x["name"] for x in read_palettes(both)] == ["Acme Brand"] and rep["palettes"]["added"] == ["Acme Brand"]
    assert extract_style(both, scopes=("workbook",))["fonts"]["all"]["font-size"] == "10"
    assert new_schema_errors(BARE, both) == []
    with pytest.raises(StyleError, match="palette name already used"):
        build_styled(both, _style(palettes=[{"name": "Acme Brand", "type": "regular", "colors": ["#000000"], "attrs": {}}]),
                     scopes=("workbook",), palettes=True)
    # a bad dict is refused before anything is planned
    with pytest.raises(StyleError):
        plan_style(BARE, _style(fonts={"all": {"nope": "1"}}))


# -------------------------------------------------------------------- CLI --

def test_cli_plan_only_writes_nothing(tmp_path, capsys):
    before = set(STYLE.iterdir())
    assert cli.main(["style", "apply", str(V2), BARE, "--scope", "workbook"]) == 0
    cap = capsys.readouterr()
    assert "font-family" in cap.out and "add" in cap.out and "plan only, nothing written" in cap.err
    assert set(STYLE.iterdir()) == before                                  # no _styled file beside the target
    assert cli.main(["style", "apply", str(V2), TARGET, "--scope", "workbook", "--format", "json"]) == 0
    cap = capsys.readouterr()
    rows = json.loads(cap.out)
    assert {r["action"] for r in rows} == {"add", "skip"} and "would be kept" in cap.err


def test_cli_write_exit_codes(tmp_path, capsys):
    out = tmp_path / "o.twb"
    assert cli.main(["style", "apply", str(V2), BARE, "--scope", "workbook", "--write", "-o", str(out)]) == 0
    err = capsys.readouterr().err
    assert "wrote" in err and "workbook: applied 6 (added 6, forced 0), same 0, skipped 0" in err
    assert "nothing here has been opened in Tableau" in err and "marks keep their colours" in err
    assert "font family 'Segoe UI' may not exist" in err
    # exit 1: existing output, the input, a missing target, an unknown dashboard, a tps target, a bad style
    assert cli.main(["style", "apply", str(V2), BARE, "--scope", "workbook", "--write", "-o", str(out)]) == 1
    assert "refusing to overwrite" in capsys.readouterr().err
    assert cli.main(["style", "apply", str(V2), BARE, "--scope", "workbook", "--write", "-o", BARE, "--overwrite"]) == 1
    assert cli.main(["style", "apply", str(V2), str(tmp_path / "missing.twb")]) == 1
    assert cli.main(["style", "apply", str(V2), BARE, "--dashboard", "Nope"]) == 1
    assert cli.main(["style", "apply", str(V2), str(STYLE / "Preferences.tps")]) == 1
    assert cli.main(["style", "apply", str(STYLE / "bad-format.style.json"), BARE]) == 1
    assert cli.main(["style", "apply", str(V2), BARE, "--scope", "elsewhere"]) == 1
    capsys.readouterr()
    # exit 2: something unsupported (dashboard formatting is not built yet) but the rest was written
    out2 = tmp_path / "o2.twb"
    assert cli.main(["style", "apply", str(V2), BARE, "--write", "-o", str(out2)]) == 2
    err = capsys.readouterr().err
    assert out2.exists() and "unsupported 10" in err and "not written (unsupported or no target)" in err
    # a skip is not an error: the format was kept and it says so
    out3 = tmp_path / "o3.twb"
    assert cli.main(["style", "apply", str(V2), TARGET, "--scope", "workbook", "--write", "-o", str(out3)]) == 0
    err = capsys.readouterr().err
    assert "skipped 1" in err and "kept (the target already sets them): workbook: title/font-family" in err
    assert cli.main(["style", "apply", str(V2), TARGET, "--scope", "workbook", "--force", "--write", "-o", str(tmp_path / "o4.twb")]) == 0
    assert "forced 1" in capsys.readouterr().err
    assert _formats(_doc((tmp_path / "o4.twb").read_bytes()), "title")[0] == ("font-family", "Segoe UI Semibold", None)


def test_cli_palettes_flag(tmp_path, capsys):
    out = tmp_path / "p.twb"
    assert cli.main(["style", "apply", str(V2), BARE, "--scope", "workbook", "--palettes", "--write", "-o", str(out)]) == 0
    assert "palettes: added 1" in capsys.readouterr().err and read_palettes(out)
    off = tmp_path / "np.twb"
    assert cli.main(["style", "apply", str(V2), BARE, "--scope", "workbook", "--write", "-o", str(off)]) == 0
    assert read_palettes(off) == [] and load_style(V2)["version"] == 2
