"""WP2 of the 0.6.0 plan: every deliberate "refusing to overwrite" raises OutputRefusedError (still a FileExistsError)."""

import re
import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

from py_tbparse import TwbParser, cli, export_library, import_library, prune, sanitize, slice_workbook  # noqa: E402
from py_tbparse.dashboardcopy import copy_dashboards  # noqa: E402
from py_tbparse.errors import OutputRefusedError  # noqa: E402
from py_tbparse.scaffold import save_scaffold  # noqa: E402
from py_tbparse.sheetcopy import copy_sheets  # noqa: E402
from py_tbparse.style import export_palettes, import_palettes  # noqa: E402
from py_tbparse.templates import make_template  # noqa: E402
from test_audit import workbook as audit_workbook  # noqa: E402
from test_dashboardcopy import dst as dash_dst, src as dash_src  # noqa: E402,F401
from test_sheetcopy import dst as sheet_dst, src as sheet_src  # noqa: E402,F401
from test_scaffold import scaffold, wb_path  # noqa: E402,F401
from test_slice import build as slice_build  # noqa: E402
from test_template_update import made  # noqa: E402,F401
from test_templates import filtering  # noqa: E402,F401

HERE = Path(__file__).parent
WENJIE = HERE / "fixtures" / "test_for_wenjie.twb"
FILTERING = HERE / "fixtures" / "public" / "filtering.twb"
LIB = HERE / "fixtures" / "library"
STYLE = HERE / "fixtures" / "style"
EXISTING = "refusing to overwrite existing file: "


def test_no_bare_file_exists_error_left():
    for path in sorted((HERE.parent / "py_tbparse").glob("*.py")):
        if path.name == "errors.py":
            continue
        assert "raise FileExistsError" not in path.read_text(encoding="utf-8"), path.name


def check(call, message):
    with pytest.raises(OutputRefusedError, match=re.escape(message)) as info:
        call()
    assert isinstance(info.value, FileExistsError)
    with pytest.raises(FileExistsError):
        call()


def existing(tmp_path, name="out.twb"):
    out = tmp_path / name
    out.write_text("keep me")
    return out


def test_rename_refuses(tmp_path):
    src = tmp_path / "book.twb"
    shutil.copy(WENJIE, src)
    parser = TwbParser(str(src))
    check(lambda: parser.write_renamed_workbook(str(src), overwrite=True), "refusing to overwrite")
    parser.write_renamed_workbook()
    check(lambda: parser.write_renamed_workbook(), EXISTING)


def test_prune_refuses(tmp_path):
    path = audit_workbook(tmp_path, calcs=[("[Calculation_1]", "Margin", "[Sales] - [Profit]")])
    check(lambda: prune(path, path, overwrite=True), "refusing to overwrite the input workbook: ")
    out = existing(tmp_path)
    check(lambda: prune(path, str(out)), EXISTING + str(out) + " (use --overwrite)")


def test_slice_refuses(tmp_path):
    path = slice_build(tmp_path)
    check(lambda: slice_workbook(path, "D1", path), "refusing to overwrite the input workbook: ")
    out = existing(tmp_path)
    check(lambda: slice_workbook(path, "D1", str(out)), EXISTING + str(out) + " (use --overwrite)")


def test_sanitize_refuses(tmp_path):
    src = tmp_path / "in.twb"
    shutil.copy(WENJIE, src)
    check(lambda: sanitize(str(src), str(src), overwrite=True), "refusing to overwrite the input workbook: ")


def test_library_refuses(tmp_path):
    src = tmp_path / "t.twb"
    shutil.copy(LIB / "target.twb", src)
    parser = TwbParser(str(src))
    library = export_library(TwbParser(str(LIB / "source.twb")))
    out = existing(tmp_path, "o.twb")
    check(lambda: import_library(parser, library, output_path=str(out)), EXISTING + str(out))


def test_style_refuses(tmp_path):
    tps = tmp_path / "Preferences.tps"
    tps.write_bytes((STYLE / "Preferences.tps").read_bytes())
    wb = str(STYLE / "palettes.twb")
    check(lambda: import_palettes(str(tps), wb, output_path=tps, on_clash="skip", overwrite=True),
          "refusing to overwrite the input: ")
    real = tmp_path / "elsewhere" / "Preferences.tps"
    real.parent.mkdir()
    real.write_text("<workbook/>")
    check(lambda: import_palettes(str(tps), wb, output_path=real, on_clash="skip", overwrite=True),
          f"refusing to write over {real}: ")
    out = existing(tmp_path, "pal.tps")
    check(lambda: export_palettes([wb], out), EXISTING + str(out))


def test_scaffold_refuses(tmp_path, scaffold):
    out = existing(tmp_path, "o.scaffold.json")
    check(lambda: save_scaffold(scaffold, out), EXISTING + str(out))


def test_sheetcopy_refuses(tmp_path, sheet_src, sheet_dst):
    o = str(tmp_path / "o.twb")
    copy_sheets(sheet_src, sheet_dst, ["Sheet 1"], o)
    check(lambda: copy_sheets(sheet_src, sheet_dst, ["Sheet 1"], o), EXISTING + o)
    check(lambda: copy_sheets(sheet_src, sheet_dst, ["Sheet 1"], sheet_dst, overwrite=True),
          "refusing to overwrite an input: ")


def test_dashboardcopy_refuses(tmp_path, dash_src, dash_dst):
    o = str(tmp_path / "o.twb")
    copy_dashboards(dash_src, dash_dst, ["Dash"], o)
    check(lambda: copy_dashboards(dash_src, dash_dst, ["Dash"], o), EXISTING + o)
    check(lambda: copy_dashboards(dash_src, dash_dst, ["Dash"], dash_dst, overwrite=True),
          "refusing to overwrite an input: ")


def test_templates_refuse(filtering):
    make_template(str(filtering))
    check(lambda: make_template(str(filtering)), EXISTING)


def test_template_update_refuses(made):
    from py_tbparse.template_update import update_from_answers
    from test_template_update import field, revise

    v2 = revise(made["v1"], made["dir"] / "v2.twbx", lambda m: field(m, "[Segment]").update(caption="Seg"))
    update_from_answers(v2, made["out"])
    check(lambda: update_from_answers(v2, made["out"]), "refusing to overwrite")
    check(lambda: update_from_answers(v2, made["out"], output_path=made["out"], overwrite=True),
          "refusing to overwrite an input: ")


def test_cli_overwrite_refusals_unchanged(tmp_path, capsys):
    out = str(tmp_path / "o.twb")
    assert cli.main(["sanitize", str(WENJIE), out]) == 0
    capsys.readouterr()
    assert cli.main(["sanitize", str(WENJIE), out]) == 2
    assert capsys.readouterr().err.startswith("error: refusing to overwrite")
    existing_out = existing(tmp_path, "s.twb")
    assert cli.main(["slice", str(FILTERING), "-d", "setTest", "--write", "-o", str(existing_out)]) == 2
    assert capsys.readouterr().err.startswith("error: refusing to overwrite")
