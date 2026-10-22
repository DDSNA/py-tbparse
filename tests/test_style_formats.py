"""Style file version 2 and `style extract` (WP7 slice 2a): fonts, workbook rules and dashboard roles are read
from a workbook into a style file. Nothing here writes formatting onto a workbook (that is 2b onwards).
Fixtures are hand-made (tests/fixtures/style/format-*.twb): no committed workbook has a workbook font."""

import json
import re
import sys
from pathlib import Path

import pytest
from lxml import etree

sys.path.insert(0, str(Path(__file__).parent))

from py_tbparse import (   # noqa: E402
    StyleError,
    TwbParser,
    check_style_file,
    cli,
    extract_style,
    format_table,
    load_style,
    make_style,
    save_style,
    style_warnings,
)
import py_tbparse.style as style_mod   # noqa: E402

FIX = Path(__file__).parent / "fixtures"
STYLE = FIX / "style"
SRC = str(STYLE / "format-source.twb")
TARGET = str(STYLE / "format-target.twb")
BARE = str(STYLE / "format-bare.twb")
V2 = STYLE / "format.style.json"
BAD_V2 = STYLE / "bad-format.style.json"
XSD = Path(__file__).parent / "schemas" / "twb_2026.2.0.xsd"


def _write(tmp_path, **change):
    style = json.loads(V2.read_text(encoding="utf-8"))
    for k, v in change.items():
        if v is None:
            style.pop(k, None)
        else:
            style[k] = v
    p = tmp_path / "x.style.json"
    p.write_text(json.dumps(style, ensure_ascii=False), encoding="utf-8")
    return p


def _wb_with_zone_styles(tmp_path, margins):
    """A copy of the bare workbook whose sheet zones carry the given margins (document order)."""
    doc = etree.parse(BARE)
    for z in doc.xpath("//dashboard//zone[@name and not(@type-v2) and not(@param)]"):
        z.getparent().remove(z)
    parent = doc.xpath("//dashboard/zones/zone")[0]
    for i, m in enumerate(margins):
        z = etree.SubElement(parent, "zone", id=str(100 + i), name="Sheet 1", h="1", w="1", x="0", y="0")
        zs = etree.SubElement(z, "zone-style")
        etree.SubElement(zs, "format", attr="margin", value=m)
    p = tmp_path / "wb.twb"
    p.write_bytes(etree.tostring(doc, xml_declaration=True, encoding="utf-8"))
    return str(p)


def test_v1_files_still_load(tmp_path):
    v1 = {"format": "py-tbparse-style", "version": 1, "name": "old", "description": "", "created": "x",
          "py_tbparse_version": "0", "sources": [], "palettes": [{"name": "A", "type": "regular", "colors": ["#112233"], "attrs": {}}]}
    p = tmp_path / "old.style.json"
    p.write_text(json.dumps(v1), encoding="utf-8")
    assert load_style(p) == v1
    assert check_style_file(p) == []
    # palette-only styles are still written as version 1
    assert make_style(v1["palettes"])["version"] == 1
    assert "fonts" not in make_style(v1["palettes"])
    # and a workbook without formatting extracts to version 1
    assert extract_style(BARE)["version"] == 1


def test_load_style_accepts_a_utf8_bom(tmp_path):
    v1 = {"format": "py-tbparse-style", "version": 1, "name": "bom", "description": "", "created": "x",
          "py_tbparse_version": "0", "sources": [], "palettes": [{"name": "A", "type": "regular", "colors": ["#112233"], "attrs": {}}]}
    p = tmp_path / "bom.style.json"
    p.write_bytes(b"\xef\xbb\xbf" + json.dumps(v1).encode("utf-8"))
    assert load_style(p) == v1
    assert check_style_file(p) == []


def test_palette_output_that_is_a_hard_link_to_the_input_is_refused(tmp_path):
    import os
    from py_tbparse import export_palettes, import_palettes
    pal = tmp_path / "Preferences.tps"
    pal.write_bytes((Path(__file__).parent / "fixtures" / "style" / "Preferences.tps").read_bytes())
    link = tmp_path / "Link.tps"
    wb = tmp_path / "wb.twb"
    wb.write_bytes(Path(BARE).read_bytes())
    wlink = tmp_path / "wlink.twb"
    try:
        os.link(pal, link)
        os.link(wb, wlink)
    except (OSError, NotImplementedError, AttributeError):
        pytest.skip("hard links are not available here")
    before, wbefore = pal.read_bytes(), wb.read_bytes()
    with pytest.raises(FileExistsError, match="the input"):
        export_palettes([str(pal)], link, overwrite=True)
    with pytest.raises(FileExistsError, match="the input"):
        import_palettes(str(wb), str(pal), output_path=wlink, overwrite=True)
    assert pal.read_bytes() == before and wb.read_bytes() == wbefore


def test_v2_roundtrip(tmp_path):
    style = load_style(V2)
    assert style["version"] == 2
    out = tmp_path / "copy.style.json"
    save_style(style, out)
    assert load_style(out) == style
    assert json.loads(out.read_text(encoding="utf-8")) == style
    extracted = extract_style(SRC, name="Src")
    save_style(extracted, tmp_path / "e.style.json")
    assert load_style(tmp_path / "e.style.json") == extracted
    assert extracted["version"] == 2


def test_v2_sections_rejected_in_v1(tmp_path):
    for section, value in (("fonts", {}), ("workbook_rules", []), ("dashboard", {}), ("sheet_defaults", [])):
        p = _write(tmp_path, version=1, **{section: value})
        with pytest.raises(StyleError, match="need style version 2"):
            load_style(p)
    with pytest.raises(StyleError, match="newer"):
        load_style(_write(tmp_path, version=3))


def test_extract_fonts_and_rules():
    style = extract_style(SRC)
    assert style["fonts"] == {
        "all": {"font-family": "Segoe UI", "font-size": "10"},
        "title": {"font-family": "Tableau Semibold", "font-size": "14", "color": "#1A3A5C"},
        "tooltip": {"font-family": "Segoe UI"},
    }
    assert style["workbook_rules"] == [{"element": "worksheet", "formats": [{"attr": "background-color", "value": "#FFFFFF"}]}]
    assert style["dashboard"]["rules"] == [{"element": "dash-title", "formats": [
        {"attr": "font-family", "value": "Segoe UI Semibold"}, {"attr": "color", "value": "#1A3A5C"}]}]
    # the target has only an explicit title font
    assert extract_style(TARGET)["fonts"] == {"title": {"font-family": "Arial"}}
    assert extract_style(TARGET)["workbook_rules"] == []


def test_extract_skips_field_and_fcp():
    rep = {}
    style = extract_style(SRC, report=rep)
    text = json.dumps(style)
    assert "_.fcp" not in text and "animation" not in text and "[federated" not in text
    assert rep["fcp_skipped"] == 1
    assert rep["field_skipped"] == ["workbook: worksheet/font-size"]
    assert all(f["attr"] != "font-size" for r in style["workbook_rules"] for f in r["formats"])
    assert rep["unsupported"] == ["dashboard setTest: table"]
    assert rep["counts"]["field_skipped"] == 1 and rep["counts"]["fcp_skipped"] == 1
    # sheet rules and the unnamed zones (filter, text) are not read as style
    assert "99" not in text and "77" not in text and style["sheet_defaults"] == []
    assert "line-visibility" not in text and "font-weight" not in text


def test_extract_dashboard_roles_modal(tmp_path):
    rep = {}
    roles = extract_style(SRC, report=rep)["dashboard"]["roles"]
    assert set(roles) == {"root", "container", "sheet", "title"}
    assert roles["sheet"]["margin"] == "4"                  # 4, 4, 6: the most frequent
    assert roles["container"]["margin"] == "8"              # 8 and 10: a tie goes to the first in document order
    assert roles["root"]["margin"] == "8"
    assert "dashboard sheet/margin: 4, 6" in rep["mixed"]
    assert "dashboard container/margin: 8, 10" in rep["mixed"]
    assert not any("root" in m for m in rep["mixed"])
    # the root background is the shorthand, and only there
    dash = extract_style(SRC)["dashboard"]
    assert dash["background"] == "#F5F5F5" and "background-color" not in roles["root"]
    assert roles["title"]["background-color"] == "#1A3A5C"
    # a tie in the other direction: the first seen wins
    for margins, want in ((["6", "4"], "6"), (["4", "6", "6", "4"], "4"), (["6", "4", "4"], "4")):
        assert extract_style(_wb_with_zone_styles(tmp_path, margins))["dashboard"]["roles"]["sheet"]["margin"] == want
    one = extract_style(SRC, dashboard="setTest")
    assert one["dashboard"] == dash
    with pytest.raises(StyleError, match="no dashboard called"):
        extract_style(SRC, dashboard="Nope")


def test_extract_no_invention():
    rep = {}
    style = extract_style(BARE, report=rep)
    assert not any(k in style for k in ("fonts", "workbook_rules", "dashboard", "sheet_defaults"))   # version 1: no sections
    assert style["palettes"] == [] and style["version"] == 1
    assert rep["counts"]["fonts"] == rep["counts"]["dashboard_roles"] == 0
    assert format_table(BARE).empty
    assert extract_style(SRC, scopes=("workbook",))["dashboard"] == {}
    assert extract_style(SRC, scopes=("dashboards",))["fonts"] == {}
    with pytest.raises(StyleError, match="WP7-2d"):
        extract_style(SRC, scopes=("sheets",))
    with pytest.raises(StyleError, match="unknown scope"):
        extract_style(SRC, scopes=("everything",))
    with pytest.raises(StyleError, match="extract_style reads"):
        extract_style(str(V2))


def test_extract_keeps_palettes_unless_asked():
    wb = str(STYLE / "palettes.twb")
    assert len(extract_style(wb)["palettes"]) == 3
    assert extract_style(wb, palettes=False)["palettes"] == []
    assert extract_style(TwbParser(SRC))["fonts"]["all"]["font-size"] == "10"


def test_check_rejects(tmp_path):
    def bad(match, **change):
        with pytest.raises(StyleError, match=match):
            load_style(_write(tmp_path, **change))

    load_style(_write(tmp_path))
    bad("role 'footer'", dashboard={"roles": {"footer": {"margin": "1"}}})
    bad("element 'nope'", workbook_rules=[{"element": "nope", "formats": [{"attr": "color", "value": "#000000"}]}])
    bad("element 'mark'", workbook_rules=[{"element": "mark", "formats": [{"attr": "color", "value": "#000000"}]}])
    bad("attribute 'nope'", workbook_rules=[{"element": "all", "formats": [{"attr": "nope", "value": "1"}]}])
    bad("attribute 'field'", workbook_rules=[{"element": "all", "formats": [{"attr": "field", "value": "1"}]}])
    bad("a format holds", workbook_rules=[{"element": "all", "formats": [{"attr": "color", "value": "#000000", "field": "[x]"}]}])
    bad("not one of font-family", fonts={"all": {"padding": "1"}})
    bad("attribute 'padding-top'", dashboard={"roles": {"sheet": {"padding-top": "1"}}})
    bad("non-empty string", fonts={"all": {"font-size": ""}})
    bad("non-empty string", fonts={"all": {"font-size": 10}})
    bad("non-empty string", dashboard={"background": "  "})
    bad("control character", fonts={"all": {"font-family": "Seg\x00oe"}})
    bad("control character", fonts={"all": {"font-family": "Seg\noe"}})
    bad("feature-flag", workbook_rules=[{"element": "all", "formats": [{"attr": "color", "value": "_.fcp.X"}]}])
    bad("listed twice", workbook_rules=[{"element": "all", "formats": [
        {"attr": "color", "value": "#000000"}, {"attr": "color", "value": "#111111"}]}])
    bad("listed twice", dashboard={"rules": [{"element": "dash-title", "formats": [
        {"attr": "color", "value": "#000000"}]}, {"element": "dash-title", "formats": [{"attr": "color", "value": "#111111"}]}]})
    bad("also in `fonts`", workbook_rules=[{"element": "title", "formats": [{"attr": "font-family", "value": "Arial"}]}])
    bad("not both", dashboard={"background": "#F5F5F5", "roles": {"root": {"background-color": "#FFFFFF"}}})
    bad("dashboard holds only", dashboard={"size": "1"})
    bad("scope 'both'", workbook_rules=[{"element": "all", "formats": [{"attr": "color", "value": "#000000", "scope": "both"}]}])
    bad("element 'mark'", sheet_defaults=[{"element": "mark", "formats": [{"attr": "color", "value": "#000000"}]}])
    bad("attribute 'text-format'", sheet_defaults=[{"element": "cell", "formats": [{"attr": "text-format", "value": "#"}]}])
    # a scope is fine where the plan allows it, and the same attribute in another scope is another key
    ok = [{"element": "all", "formats": [{"attr": "color", "value": "#000000", "scope": "rows"},
                                          {"attr": "color", "value": "#111111", "scope": "cols"}]}]
    assert load_style(_write(tmp_path, workbook_rules=ok))["workbook_rules"] == ok
    # the shipped bad fixture is refused and `check` says why
    assert any("footer" in line for line in check_style_file(BAD_V2))
    with pytest.raises(StyleError):
        make_style([], fonts={"all": {"nope": "1"}})


def test_font_warning_not_error(tmp_path):
    style = load_style(V2)                                    # Segoe UI is not a "Tableau *" face
    warnings = style_warnings(style)
    assert any("'Segoe UI'" in w and "may not exist" in w for w in warnings)
    assert not any("Tableau" in w for w in style_warnings(extract_style(SRC)) if "Tableau Semibold" in w)
    lines = check_style_file(V2)
    assert lines and all(line.startswith("warning:") for line in lines)
    p = _write(tmp_path, fonts={"all": {"font-family": "Tableau Book"}}, workbook_rules=[],
               dashboard={}, sheet_defaults=[])
    assert check_style_file(p) == []


def test_non_latin_font_name(tmp_path):
    doc = etree.parse(SRC)
    ff = doc.xpath("/workbook/style/style-rule[@element='all']/format[@attr='font-family']")[0]
    ff.set("value", "游ゴシック")
    wb = tmp_path / "jp.twb"
    wb.write_bytes(etree.tostring(doc, xml_declaration=True, encoding="utf-8"))
    style = extract_style(str(wb))
    assert style["fonts"]["all"]["font-family"] == "游ゴシック"
    out = tmp_path / "jp.style.json"
    save_style(style, out)
    assert "游ゴシック" in out.read_text(encoding="utf-8")          # not \u-escaped
    assert load_style(out)["fonts"]["all"]["font-family"] == "游ゴシック"
    assert any("游ゴシック" in w for w in style_warnings(style))
    assert format_table(out)["value"].eq("游ゴシック").any()


def test_whitelist_matches_xsd():
    text = XSD.read_text(encoding="utf-8")

    def enum(name):
        body = re.search(r'name="%s">(.*?)</xs:simpleType>' % name, text, re.S).group(1)
        return set(re.findall(r'value="([^"]*)"', body))

    elements, attrs, scopes = enum("StyleElement-ST"), enum("StyleAttribute-ST"), enum("StyleFieldScope-ST")
    for group in (style_mod.FONT_ELEMENTS, style_mod.WORKBOOK_ELEMENTS, style_mod.DASHBOARD_RULE_ELEMENTS, style_mod.SHEET_ELEMENTS):
        assert set(group) <= elements, set(group) - elements
    for group in (style_mod.FONT_ATTRS, style_mod.ROLE_ATTRS, style_mod.SHEET_ATTRS):
        assert set(group) <= attrs, set(group) - attrs
    assert style_mod.STYLE_ATTRIBUTES == attrs                  # the static copy has not drifted
    assert set(style_mod.FORMAT_SCOPE_ATTRS) <= scopes
    assert "field" not in style_mod.STYLE_ATTRIBUTES and "encoding" not in style_mod.STYLE_ATTRIBUTES
    # every name the extractor reads is in the whitelist the file validator uses, and vice versa
    assert set(style_mod.FONT_ATTRS) <= style_mod.STYLE_ATTRIBUTES
    assert not [e for e in style_mod.WORKBOOK_ELEMENTS if e.startswith("_.fcp")]


def test_extract_roles_use_zone_kind():
    # the fixture roots carry only `_.fcp...type-v2` attributes: reading z.get("type-v2") would find no root
    rep = {}
    roles = extract_style(SRC, report=rep)["dashboard"]["roles"]
    assert "root" in roles and "container" in roles
    src = Path(style_mod.__file__).read_text(encoding="utf-8")
    assert 'get("type-v2")' not in src and "zone_kind" in src


# -------------------------------------------------------------------- CLI --

def test_cli_extract(tmp_path, capsys):
    out = tmp_path / "out.style.json"
    assert cli.main(["style", "extract", SRC, "-o", str(out), "--name", "Acme"]) == 0
    err = capsys.readouterr().err
    assert "wrote" in err and "1 bound to a field" in err and "mixed" in err and "not opened in Tableau" in err
    style = load_style(out)
    assert style["name"] == "Acme" and style["fonts"]["all"]["font-size"] == "10"
    assert cli.main(["style", "check", str(out)]) == 0                  # only warnings
    assert cli.main(["style", "extract", SRC, "-o", str(out)]) == 1     # exists
    assert "refusing to overwrite" in capsys.readouterr().err
    assert cli.main(["style", "extract", SRC, "-o", str(out), "--overwrite", "--scope", "workbook", "--no-palettes"]) == 0
    assert load_style(out)["dashboard"] == {}
    assert cli.main(["style", "extract", SRC, "-o", str(tmp_path / "x.json")]) == 1
    assert cli.main(["style", "extract", SRC, "-o", str(tmp_path / "s.style.json"), "--scope", "sheets"]) == 1
    assert cli.main(["style", "extract", SRC, "-o", str(tmp_path / "d.style.json"), "--dashboard", "Nope"]) == 1
    assert not (tmp_path / "d.style.json").exists() and not (tmp_path / "s.style.json").exists()
    assert cli.main(["style", "extract", str(tmp_path / "missing.twb"), "-o", str(tmp_path / "m.style.json")]) == 1
    # a bare workbook: written, empty, and it says so rather than inventing defaults
    capsys.readouterr()
    bare_out = tmp_path / "bare.style.json"
    assert cli.main(["style", "extract", BARE, "-o", str(bare_out)]) == 0
    assert "nothing to extract" in capsys.readouterr().err
    assert load_style(bare_out)["version"] == 1


def test_cli_extract_never_overwrites_input(tmp_path, capsys):
    copy = tmp_path / "a.style.json"
    copy.write_text(V2.read_text(encoding="utf-8"), encoding="utf-8")
    before = copy.read_bytes()
    assert cli.main(["style", "extract", str(copy), "-o", str(copy), "--overwrite"]) == 1
    assert copy.read_bytes() == before


def test_cli_show_what_formats(capsys):
    assert cli.main(["style", "show", SRC, "--what", "formats"]) == 0
    out = capsys.readouterr().out
    assert "font-family" in out and "Tableau Semibold" in out and "mixed: 4, 6" in out
    assert cli.main(["style", "show", SRC, "--what", "formats", "--format", "json"]) == 0
    rows = json.loads(capsys.readouterr().out)
    assert {r["section"] for r in rows} == {"fonts", "workbook_rules", "dashboard", "dashboard_rules"}
    assert cli.main(["style", "show", SRC, str(V2), "--what", "formats", "--format", "csv"]) == 0
    out = capsys.readouterr().out
    assert "format.style.json" in out and "sheet_defaults" in out
    # default is still palettes; `all` prints both; a .tps has no formatting
    assert cli.main(["style", "show", str(STYLE / "palettes.twb")]) == 0
    assert "Acme Brand" in capsys.readouterr().out
    assert cli.main(["style", "show", str(STYLE / "palettes.twb"), "--what", "all"]) == 0
    assert "Acme Brand" in capsys.readouterr().out
    assert cli.main(["style", "show", str(STYLE / "Preferences.tps"), "--what", "formats", "--format", "json"]) == 0
    assert json.loads(capsys.readouterr().out) == []
    assert cli.main(["style", "show", SRC, "--what", "formats", "--scope", "workbook", "--format", "json"]) == 0
    assert {r["section"] for r in json.loads(capsys.readouterr().out)} == {"fonts", "workbook_rules"}


def test_cli_check_v2(tmp_path, capsys):
    assert cli.main(["style", "check", str(V2)]) == 0                   # a font warning is not a problem
    cap = capsys.readouterr()
    assert "warning: fonts/all: font family 'Segoe UI'" in cap.out and "no problems found" in cap.err
    assert cli.main(["style", "check", str(BAD_V2)]) == 1
    assert "footer" in capsys.readouterr().out
