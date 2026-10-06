"""Palette library (WP7 slice 1): read, export, import, check. Fixtures are hand-made (tests/fixtures/style):
the corpus has no Preferences.tps and only three named palettes."""

import json
import sys
import zipfile
from pathlib import Path

import pytest
from lxml import etree

sys.path.insert(0, str(Path(__file__).parent))
from schema_check import new_schema_errors   # noqa: E402

from py_tbparse import (
    StyleError,
    TwbParser,
    build_with_palettes,
    check_style_file,
    export_palettes,
    import_palettes,
    load_style,
    make_style,
    palettes_table,
    plan_palette_import,
    read_palettes,
    save_style,
    tps_bytes,
)

FIX = Path(__file__).parent / "fixtures"
STYLE = FIX / "style"
WB = str(STYLE / "palettes.twb")
TPS = str(STYLE / "Preferences.tps")
BAD = str(STYLE / "bad.tps")
PLAIN = str(FIX / "test_for_wenjie.twb")         # has <preferences> with a <preference>, no palettes
NAMES = ["Acme Brand", "Acme Ramp", "Acme Diverging"]


def _plain_without_preferences(tmp_path):
    doc = etree.parse(PLAIN)
    for el in doc.xpath("/workbook/preferences"):
        el.getparent().remove(el)
    path = tmp_path / "nopref.twb"
    path.write_bytes(etree.tostring(doc, xml_declaration=True, encoding="utf-8"))
    return str(path)


def _tree(data: bytes) -> bytes:
    return etree.tostring(etree.fromstring(data))


def _pal(name, colors=("#112233",), typ="regular", **attrs):
    return {"name": name, "type": typ, "colors": list(colors), "attrs": attrs}


def test_read_palettes_from_workbook():
    rep = {}
    got = read_palettes(WB, rep)
    assert [p["name"] for p in got] == NAMES
    assert [p["type"] for p in got] == ["regular", "ordered-sequential", "ordered-diverging"]
    assert got[0]["attrs"] == {"custom": "true"} and got[1]["attrs"] == {}
    assert got[0]["colors"] == ["#1A3A5C", "#C9973A", "#7A9E7E", "#B5483A"]
    # the inline unnamed ramp and the built-in id in the sheet encodings are not palettes
    assert rep["found"] == 3 and rep["invalid"] == []
    assert read_palettes(TwbParser(WB)) == got


def test_read_palettes_from_tps_and_json(tmp_path):
    for src in (WB, TPS):
        want = read_palettes(src)
        j = export_palettes([src], tmp_path / "a.style.json")
        t = export_palettes([src], tmp_path / "a.tps")
        assert read_palettes(j) == want and read_palettes(t) == want
        (tmp_path / "a.style.json").unlink()
        (tmp_path / "a.tps").unlink()


def test_invalid_palettes_reported():
    rep = {}
    good = read_palettes(BAD, rep)
    assert [p["name"] for p in good] == ["Fine"]
    assert rep["found"] == 5 and len(rep["invalid"]) == 4
    assert rep["warnings"] == ["Fine"]            # the 8-digit colour
    table = palettes_table(BAD)
    bad = table[table["status"] == "invalid"]
    assert len(bad) == 4 and all(bad["reason"] != "")
    reasons = " | ".join(bad["reason"])
    for needle in ("not #RRGGBB", "rainbow", "no name", "no colours"):
        assert needle in reasons
    assert "alpha not confirmed" in table[table["name"] == "Fine"]["reason"].iloc[0]
    assert list(table.columns) == ["source", "name", "type", "n_colors", "colors", "status", "reason"]


def test_style_json_roundtrip(tmp_path):
    style = make_style(read_palettes(WB), name="Acme", sources=["palettes.twb"])
    path = tmp_path / "x.style.json"
    assert save_style(style, path) == str(path)
    assert load_style(path) == style
    text = path.read_text(encoding="utf-8")
    assert text.startswith('{\n  "created"') and text.endswith("\n")        # sorted keys, indent 2
    with pytest.raises(FileExistsError):
        save_style(style, path)
    save_style(style, path, overwrite=True)

    def bad(**change):
        s = {**style, **change}
        p = tmp_path / "bad.json"
        p.write_text(json.dumps(s), encoding="utf-8")
        return p

    with pytest.raises(StyleError, match="not a style file"):
        load_style(bad(format="other"))
    with pytest.raises(StyleError, match="newer"):
        load_style(bad(version=2))
    with pytest.raises(StyleError, match="unknown key"):
        load_style(bad(surprise=1))
    with pytest.raises(StyleError, match="reserved"):
        load_style(bad(fonts=[]))
    dup = [_pal("A"), _pal("A", ("#000000",))]
    with pytest.raises(StyleError, match="two palettes"):
        load_style(bad(palettes=dup))
    with pytest.raises(StyleError, match="two palettes"):
        make_style(dup)
    with pytest.raises(StyleError, match="not JSON"):
        (tmp_path / "t.json").write_text("{nope")
        load_style(tmp_path / "t.json")


def test_tps_bytes_shape(tmp_path):
    palettes = read_palettes(WB)
    data = tps_bytes(palettes)
    assert data.startswith(b"<?xml")
    root = etree.fromstring(data, etree.XMLParser(resolve_entities=False, no_network=True))
    assert root.tag == "workbook" and len(root.findall("preferences")) == 1
    assert [e.get("name") for e in root.findall("preferences/color-palette")] == NAMES
    assert root.find("preferences/color-palette").get("custom") == "true"
    path = tmp_path / "Prefs.tps"
    path.write_bytes(data)
    assert check_style_file(path) == []


def test_check_style_file_finds_problems(tmp_path):
    problems = check_style_file(BAD)
    assert len([p for p in problems if not p.startswith("warning:")]) == 4
    assert any(p.startswith("warning:") for p in problems)
    assert check_style_file(tmp_path / "missing.tps")[0].startswith("file not found")
    (tmp_path / "x.tps").write_text("<workbook/>")
    assert "no <color-palette>" in check_style_file(tmp_path / "x.tps")[0]
    (tmp_path / "y.tps").write_text("<other/>")
    assert "not a Preferences.tps" in check_style_file(tmp_path / "y.tps")[0]
    (tmp_path / "z.tps").write_text("<workbook>")
    assert "not XML" in check_style_file(tmp_path / "z.tps")[0]
    (tmp_path / "w.txt").write_text("")
    assert check_style_file(tmp_path / "w.txt")


def test_tps_does_not_read_external_entities(tmp_path):
    secret = tmp_path / "secret.txt"
    secret.write_text("LEAKED")
    p = tmp_path / "e.tps"
    p.write_text(f'<?xml version="1.0"?><!DOCTYPE workbook [<!ENTITY x SYSTEM "{secret}">]><workbook><preferences>'
                 '<color-palette name="a" type="regular"><color>#000000</color></color-palette>'
                 '<color-palette name="b" type="regular"><color>&x;</color></color-palette></preferences></workbook>')
    rep = {}
    read_palettes(p, rep)
    assert "LEAKED" not in repr(palettes_table(p).to_dict("records")) and rep["invalid"] == ["b"]


def test_import_into_workbook_without_preferences(tmp_path):
    target = _plain_without_preferences(tmp_path)
    rep = {}
    data = build_with_palettes(target, WB, report=rep)
    assert rep["counts"]["added"] == 3
    doc = etree.fromstring(data)
    tags = [c.tag for c in doc]
    assert tags.index("preferences") == tags.index("document-format-change-manifest") + 1
    assert tags.index("preferences") < tags.index("datasources")
    assert [e.get("name") for e in doc.findall("preferences/color-palette")] == NAMES
    # compared with the original, which has <preferences> in the same place: wenjie has a pre-existing schema error
    # whose message lists "expected elements" and so depends on whether <preferences> is already there
    assert new_schema_errors(PLAIN, data) == []
    out = tmp_path / "out.twb"
    out.write_bytes(data)
    assert [p["name"] for p in read_palettes(TwbParser(str(out)))] == NAMES
    assert b"\n  <preferences>\n    <color-palette" in data        # indentation follows the file


def test_import_keeps_existing_preferences():
    data = build_with_palettes(PLAIN, WB)
    prefs = etree.fromstring(data).find("preferences")
    kinds = [c.tag for c in prefs]
    assert kinds == ["preference", "preference", "color-palette", "color-palette", "color-palette"]
    assert new_schema_errors(PLAIN, data) == []
    # a second import puts new palettes after the last palette
    out = build_with_palettes(TwbParser(PLAIN), [_pal("Zed")])
    assert [c.get("name") for c in etree.fromstring(out).find("preferences")][-1] == "Zed"
    again = etree.fromstring(build_with_palettes(WB, [_pal("Zed")])).find("preferences")
    assert [c.get("name") for c in again.findall("color-palette")] == NAMES + ["Zed"]
    assert again[0].tag == "preference"


def test_self_import_is_noop():
    plan = plan_palette_import(WB, WB)
    assert list(plan["action"]) == ["skip-identical"] * 3
    data = build_with_palettes(WB, WB)
    assert _tree(data) == etree.tostring(TwbParser(WB).xml_doc.getroot())


def test_clash_fail_writes_nothing(tmp_path):
    out = tmp_path / "o.tps"
    with pytest.raises(StyleError, match="Acme Brand") as exc:
        import_palettes(TPS, WB, output_path=out)
    assert "replace" in str(exc.value) and "rename" in str(exc.value)
    assert not out.exists() and not (STYLE / "Preferences_palettes.tps").exists()
    plan = plan_palette_import(TPS, WB)         # the dry run shows it instead of raising
    assert list(plan["action"]) == ["fail", "add", "add"]


def test_clash_skip():
    rep = {}
    data = build_with_palettes(TPS, WB, on_clash="skip", report=rep)
    assert rep["skipped"] == ["Acme Brand"] and rep["added"] == ["Acme Ramp", "Acme Diverging"]
    root = etree.fromstring(data)
    brand = root.xpath("//color-palette[@name='Acme Brand']")
    assert len(brand) == 1 and brand[0].findtext("color") == "#112233"


def test_clash_rename():
    rep = {}
    data = build_with_palettes(TPS, WB, on_clash="rename", report=rep)
    assert rep["renamed"] == ["Acme Brand -> Acme Brand (2)"]
    names = [e.get("name") for e in etree.fromstring(data).findall("preferences/color-palette")]
    assert "Acme Brand" in names and "Acme Brand (2)" in names
    mid = tps_bytes([_pal("X"), _pal("X (2)", ("#000000",))])
    rep = {}
    data = build_with_palettes(_write(mid, "mid.tps"), [_pal("X", ("#FFFFFF",))], on_clash="rename", report=rep)
    assert rep["renamed"] == ["X -> X (3)"]


def _write(data, name):
    import tempfile
    d = Path(tempfile.mkdtemp())
    (d / name).write_bytes(data)
    return str(d / name)


def test_clash_replace_keeps_position():
    rep = {}
    data = build_with_palettes(TPS, WB, on_clash="replace", report=rep)
    assert rep["replaced"] == ["Acme Brand"]
    root = etree.fromstring(data)
    names = [e.get("name") for e in root.findall("preferences/color-palette")]
    assert names == ["Acme Brand", "Retail Teal", "Acme Ramp", "Acme Diverging"]
    brand = root.find("preferences/color-palette")
    assert brand.get("custom") == "true" and brand.findtext("color") == "#1A3A5C"


def test_case_only_difference_warns():
    rep = {}
    plan = plan_palette_import(TPS, [_pal("acme brand")])
    assert list(plan["action"]) == ["add"] and "only in case" in plan["reason"].iloc[0]
    build_with_palettes(TPS, [_pal("acme brand")], report=rep)
    assert rep["added"] == ["acme brand"] and "only in case" in rep["warnings"][0]


def test_identity_ignores_colour_case_and_attrs():
    other = [_pal("Acme Brand", ("#1a3a5c", "#c9973a", "#7a9e7e", "#b5483a"), custom="false")]
    plan = plan_palette_import(WB, other)
    assert list(plan["action"]) == ["skip-identical"]
    assert list(plan_palette_import(WB, [_pal("Acme Brand", ("#1A3A5C", "#C9973A", "#7A9E7E"))])["action"]) == ["fail"]


def test_select_palettes():
    rep = {}
    data = build_with_palettes(PLAIN, WB, select=["Acme Ramp"], report=rep)
    assert rep["added"] == ["Acme Ramp"]
    assert len(etree.fromstring(data).xpath("//preferences/color-palette")) == 1
    with pytest.raises(StyleError, match="Nope"):
        build_with_palettes(PLAIN, WB, select=["Nope"])


def test_export_merges_sources(tmp_path):
    with pytest.raises(StyleError, match="Acme Brand"):
        export_palettes([WB, TPS], tmp_path / "m.tps")
    assert not (tmp_path / "m.tps").exists()
    out = export_palettes([WB, TPS], tmp_path / "skip.style.json", on_clash="skip", name="Merged")
    style = load_style(out)
    assert style["name"] == "Merged" and style["sources"] == ["palettes.twb", "Preferences.tps"]
    assert [p["name"] for p in style["palettes"]] == NAMES + ["Retail Teal"]
    assert style["palettes"][0]["colors"][0] == "#1A3A5C"
    out = export_palettes([WB, TPS], tmp_path / "replace.tps", on_clash="replace")
    got = {p["name"]: p for p in read_palettes(out)}
    assert got["Acme Brand"]["colors"] == ["#112233", "#445566"] and list(got)[0] == "Acme Brand"
    rep = {}
    out = export_palettes([WB, TPS], tmp_path / "rename.tps", on_clash="rename", report=rep)
    assert "Acme Brand (2)" in [p["name"] for p in read_palettes(out)]
    out = export_palettes([WB], tmp_path / "one.tps", select=["Acme Ramp"])
    assert [p["name"] for p in read_palettes(out)] == ["Acme Ramp"]
    with pytest.raises(StyleError, match="must end"):
        export_palettes([WB], tmp_path / "x.json")
    with pytest.raises(StyleError, match="no usable"):
        export_palettes([str(STYLE / "bad.tps")], tmp_path / "e.tps", select=["Bad type"])


def test_import_into_tps_keeps_unknown_content(tmp_path):
    data = build_with_palettes(TPS, WB, on_clash="skip")
    root = etree.fromstring(data)
    assert root.find("unknown-thing").get("keep") == "me"
    prefs = root.find("preferences")
    assert prefs[0].tag == "preference" and prefs[0].get("value") == "30"
    assert data.startswith(b"<?xml")
    out = tmp_path / "new.tps"
    out.write_bytes(data)
    assert check_style_file(out) == []


def test_never_overwrites(tmp_path):
    src = tmp_path / "Preferences.tps"
    src.write_bytes(Path(TPS).read_bytes())
    before = src.read_bytes()
    with pytest.raises(FileExistsError):
        import_palettes(str(src), WB, output_path=src, on_clash="skip")
    with pytest.raises(FileExistsError):
        import_palettes(str(src), WB, output_path=src, on_clash="skip", overwrite=True)
    other = tmp_path / "elsewhere" 
    other.mkdir()
    real = other / "Preferences.tps"
    real.write_text("<workbook/>")
    with pytest.raises(FileExistsError, match="Preferences.tps"):
        import_palettes(str(src), WB, output_path=real, on_clash="skip", overwrite=True)
    with pytest.raises(FileExistsError):
        export_palettes([WB], real, overwrite=True)
    assert real.read_text() == "<workbook/>"
    with pytest.raises(StyleError, match="must end"):
        import_palettes(str(src), WB, output_path=tmp_path / "o.twb", on_clash="skip")
    # default output, then an existing output
    out = import_palettes(str(src), WB, on_clash="skip")
    assert Path(out).name == "Preferences_palettes.tps"
    with pytest.raises(FileExistsError):
        import_palettes(str(src), WB, on_clash="skip")
    import_palettes(str(src), WB, on_clash="skip", overwrite=True)
    assert src.read_bytes() == before
    # the input workbook is never the output either
    wb = tmp_path / "w.twb"
    wb.write_bytes(Path(PLAIN).read_bytes())
    with pytest.raises(FileExistsError):
        import_palettes(str(wb), WB, output_path=wb, overwrite=True)
    with pytest.raises(FileExistsError):
        export_palettes([str(src)], src, overwrite=True)


def test_twbx_members_copied(zip_twbx_path, tmp_path):
    out = import_palettes(zip_twbx_path, [_pal("Zip Palette")], output_path=tmp_path / "z.twbx")
    with zipfile.ZipFile(zip_twbx_path) as a, zipfile.ZipFile(out) as b:
        assert a.namelist() == b.namelist()
        twb = next(n for n in a.namelist() if n.endswith(".twb"))
        for n in a.namelist():
            if n != twb:
                assert a.read(n) == b.read(n), n
    assert [p["name"] for p in read_palettes(out)] == ["Zip Palette"]
    assert new_schema_errors(zip_twbx_path, Path(out).read_bytes()) == []


def test_does_not_touch_marks(tmp_path):
    target = _plain_without_preferences(tmp_path)
    after = etree.fromstring(build_with_palettes(target, WB))
    before = etree.parse(target).getroot()
    for xp in ("//datasource/style", "//worksheet//style", "//dashboard//style", "document-format-change-manifest"):
        a = [etree.tostring(e) for e in before.xpath(xp)]
        b = [etree.tostring(e) for e in after.xpath(xp)]
        assert a == b, xp
    assert len(before.xpath("//datasource/style")) > 0
    # the source workbook (with the inline ramp) is also unchanged apart from <preferences>
    rest = lambda r: [etree.tostring(c) for c in r if c.tag != "preferences"]        # noqa: E731
    wb_after = etree.fromstring(build_with_palettes(WB, [_pal("More")]))
    assert rest(wb_after) == rest(TwbParser(WB).xml_doc.getroot())


def test_non_latin_palette_name(tmp_path):
    p = _pal("品牌色", ("#102030", "#405060"))
    t = export_palettes([[p]], tmp_path / "n.tps")
    j = export_palettes([[p]], tmp_path / "n.style.json")
    assert "品牌色" in Path(j).read_text(encoding="utf-8")
    assert read_palettes(t)[0]["name"] == "品牌色" and read_palettes(j)[0]["name"] == "品牌色"
    wb = tmp_path / "n.twb"
    wb.write_bytes(build_with_palettes(PLAIN, t))
    assert read_palettes(TwbParser(str(wb)))[0]["name"] == "品牌色"
    assert read_palettes(export_palettes([str(wb)], tmp_path / "back.tps"))[0]["name"] == "品牌色"


def test_invalid_palettes_are_not_written(tmp_path):
    rep = {}
    data = build_with_palettes(PLAIN, BAD, report=rep)
    assert rep["added"] == ["Fine"] and len(rep["invalid"]) == 4
    assert len(etree.fromstring(data).xpath("//color-palette")) == 1
    with pytest.raises(StyleError):
        tps_bytes([_pal("Bad", ("nope",))])


def test_workbook_bytes_refactor_is_shared():
    # slice 1 reuses rename._serialize_workbook (the helper WP6 added); there is only one
    import py_tbparse.library as lib, py_tbparse.rename as ren, py_tbparse.style as st
    assert lib._serialize_workbook is ren._serialize_workbook is st._serialize_workbook
