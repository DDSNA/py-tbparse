"""A3 of the 0.6.0 plan: every library ValueError has a category, and the refusal, integrity and usage cases
have feature subclasses. No message and no command exit code changes here (the CLI still picks by `except`)."""

import ast
import shutil
import sys
from collections import Counter
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

import test_dashboardcopy as _dc  # noqa: E402
from test_library import library, source, target  # noqa: E402,F401
from test_sanitize import twb  # noqa: E402,F401
from test_sheetcopy import datasource, dst, src, target_text, write  # noqa: E402,F401
from test_slice import build, doc_of  # noqa: E402
from test_style import TPS, WB  # noqa: E402

import importlib  # noqa: E402

import py_tbparse  # noqa: E402
from py_tbparse import (  # noqa: E402
    InputError, IntegrityError, LibraryError, PruneError, RefusedError, SanitizeError, SliceError, TwbParser,
    UsageError, import_library, import_palettes, plan_import, prune, sanitize, slice_doc, slice_workbook,
)
from py_tbparse.errors import exit_code_for  # noqa: E402
from py_tbparse.sheetcopy import SheetCopyAbort, plan_sheet_copy  # noqa: E402

# the package re-exports functions named like their modules (sanitize, prune, library ...), so import the modules by name
dashboardcopy, library_mod, prune_mod, sanitize_mod, scaffold, sheetcopy, slicer, style = (
    importlib.import_module(f"py_tbparse.{n}")
    for n in ("dashboardcopy", "library", "prune", "sanitize", "scaffold", "sheetcopy", "slicer", "style"))

PKG = Path(py_tbparse.__file__).parent
WENJIE = str(Path(__file__).parent / "fixtures" / "test_for_wenjie.twb")


def test_no_plain_value_error_outside_the_allow_list():
    found = Counter()
    for path in PKG.glob("*.py"):
        if path.name in ("webgui.py", "errors.py"):
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Raise) and isinstance(node.exc, ast.Call) \
                    and getattr(node.exc.func, "id", None) == "ValueError":
                found[path.name] += 1
    # programmer errors only: a rule registered twice, a scope name in code, a heading level, a table row width
    assert dict(found) == {"findings.py": 2, "docgen.py": 2}


def test_usage_examples(tmp_path):
    findings, rename, batch, diff = (importlib.import_module(f"py_tbparse.{n}") for n in ("findings", "rename", "batch", "diff"))
    cases = [
        lambda: findings.run_rules(None, "workbook", only=["NOPE999"]),
        lambda: rename.suggest_renames(TwbParser(WENJIE), style="nope"),
        lambda: rename.suggest_renames(TwbParser(WENJIE), fuzzy_cutoff=2),
        lambda: batch.scan_folder(str(tmp_path), table="nope"),
        lambda: diff.diff_workbooks(WENJIE, WENJIE, table="nope"),
    ]
    for case in cases:
        with pytest.raises(UsageError):
            try:
                case()
            except UsageError as e:
                assert isinstance(e, ValueError)
                raise


def test_input_examples(tmp_path):
    bad = tmp_path / "x.txt"
    bad.write_text("hello", encoding="utf-8")
    with pytest.raises(InputError, match="Unsupported file type"):
        TwbParser(str(bad))
    import zipfile
    z = tmp_path / "no_twb.twbx"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("data.csv", "a,b\n1,2\n")
    with pytest.raises(InputError, match="No .twb"):
        TwbParser(str(z))
    from py_tbparse import rename
    mapping = tmp_path / "m.csv"
    mapping.write_text("foo,bar\n1,2\n", encoding="utf-8")
    with pytest.raises(InputError, match="missing column"):
        rename.load_rename_mapping(str(mapping))


def test_validate_error_true_raises_integrity(monkeypatch):
    monkeypatch.setattr("py_tbparse.parser.validate_relationships", lambda p: {"ok": False, "issues": {}})
    with pytest.raises(IntegrityError) as e:
        TwbParser(WENJIE).validate(error=True)
    assert isinstance(e.value, ValueError) and exit_code_for(e.value) == 6


def test_refusal_subclasses(tmp_path, src):
    with pytest.raises(slicer.SliceStrictError) as e:
        slice_doc(doc_of(build(tmp_path)), "D1", strict=True)
    assert isinstance(e.value, SliceError) and isinstance(e.value, RefusedError)

    clash = write(tmp_path, target_text(ds=datasource(calc_formula="[Sales] * 3")), "clash.twb")
    with pytest.raises(sheetcopy.SheetCopyRefused) as e:
        plan_sheet_copy(src, clash, ["Sheet 1"])
    assert isinstance(e.value, SheetCopyAbort) and isinstance(e.value, RefusedError)

    other = write(tmp_path, target_text(ds=datasource(path="C:/x/other.xlsx")), "o2.twb")
    with pytest.raises(sheetcopy.SheetCopyRefused, match="nothing written"):
        sheetcopy.copy_sheets(src, other, ["Sheet 1"], str(tmp_path / "x.twb"))


def test_dashboard_copy_clash_is_refused(tmp_path):
    s = write(tmp_path, _dc.only_dashboard_source(), "od.twb")
    clash = _dc.datasource(calcs=False).replace("<column name='[Size]'", "<column name='[Extra]' datatype='real' "
        "role='measure'><calculation class='tableau' formula='[Sales] * 4'/></column><column name='[Size]'")
    t = write(tmp_path, _dc.target_text(ds=clash).replace(_dc.PARAMS, ""), "t.twb")
    with pytest.raises(sheetcopy.SheetCopyRefused):
        dashboardcopy.plan_dashboard_copy(s, t, ["Dash"])


def test_library_clash_is_refused(target, library, tmp_path):
    with pytest.raises(library_mod.LibraryClashError, match="Profit Ratio") as e:
        plan_import(target, library, on_clash="fail")
    assert isinstance(e.value, LibraryError) and isinstance(e.value, RefusedError)
    fix = Path(__file__).parent / "fixtures" / "library"
    shutil.copy(next(fix.glob("target.twb")), tmp_path / "t.twb")
    with pytest.raises(library_mod.LibraryClashError):
        import_library(TwbParser(str(tmp_path / "t.twb")), library, on_clash="fail", output_path=str(tmp_path / "o.twb"))
    # a LibraryError that is not a clash stays a plain category-4 error
    with pytest.raises(LibraryError) as e2:
        plan_import(target, library, on_clash="whatever")
    assert not isinstance(e2.value, library_mod.LibraryClashError) and exit_code_for(e2.value) == 4


def test_style_clash_is_refused(tmp_path):
    with pytest.raises(style.StyleClashError, match="Acme Brand") as e:
        import_palettes(TPS, WB, output_path=tmp_path / "o.tps")
    assert isinstance(e.value, style.StyleError) and isinstance(e.value, RefusedError)


def test_a_selection_with_no_worksheet_is_refused_with_its_own_class(tmp_path):
    path = Path(build(tmp_path))
    path.write_text(path.read_text(encoding="utf-8").replace(
        "<dashboard name='D3'><zones><zone id='0' name='S2'/></zones></dashboard>",
        "<dashboard name='D3' type='storyboard'><zones/></dashboard>"), encoding="utf-8")
    with pytest.raises(slicer.SliceRefused):
        slice_doc(doc_of(str(path)), "D3")


def test_unknown_dashboard_stays_bad_input(tmp_path):
    with pytest.raises(SliceError) as e:
        slice_doc(doc_of(build(tmp_path)), "Nope")
    assert type(e.value) is SliceError and exit_code_for(e.value) == 4


def test_integrity_subclasses(tmp_path, monkeypatch):
    path = build(tmp_path)
    real, calls = slicer.integrity_check, []

    def fake(doc):                      # the first call is the input, the second the sliced result
        calls.append(1)
        found = real(doc)
        return found + [{"check": "X", "dashboard": "D1", "detail": "made up", "element": None}] if len(calls) % 2 == 0 else found

    monkeypatch.setattr(slicer, "integrity_check", fake)
    out = tmp_path / "bad.twb"
    with pytest.raises(slicer.SliceIntegrityError) as e:
        slice_workbook(path, "D1", str(out))
    assert isinstance(e.value, SliceError) and isinstance(e.value, IntegrityError) and not out.exists()


def test_usage_subclasses(twb, tmp_path, src, dst):
    with pytest.raises(sanitize_mod.SanitizeUsageError, match="unknown category") as e:
        sanitize(str(twb), str(tmp_path / "o.twb"), keep=["nope"])
    assert isinstance(e.value, SanitizeError)
    with pytest.raises(sanitize_mod.SanitizeUsageError, match="output is a"):
        sanitize(str(twb), str(tmp_path / "o.csv"))
    with pytest.raises(sanitize_mod.SanitizeUsageError, match="must be a"):
        sanitize(str(twb), str(tmp_path / "o.twbx"))
    wb = build(tmp_path)
    with pytest.raises(slicer.SliceUsageError, match="must end in") as e:
        slice_workbook(wb, "D1", str(tmp_path / "o.twbx"))
    assert isinstance(e.value, SliceError)
    with pytest.raises(slicer.SliceUsageError):
        slice_doc(doc_of(wb), [])
    with pytest.raises(prune_mod.PruneUsageError, match="must end in") as e:
        prune(wb, str(tmp_path / "p.twbx"))
    assert isinstance(e.value, PruneError)
    with pytest.raises(sheetcopy.SheetCopyUsageError, match="must end in") as e:
        sheetcopy.copy_sheets(src, dst, ["Sheet 1"], str(tmp_path / "c.twbx"))
    assert isinstance(e.value, SheetCopyAbort)
    with pytest.raises(style.StyleUsageError, match="must end in"):
        import_palettes(TPS, WB, output_path=tmp_path / "o.csv", on_clash="skip")


@pytest.mark.parametrize("cls,code", [
    (slicer.SliceStrictError, 5), (slicer.SliceRefused, 5), (sheetcopy.SheetCopyRefused, 5),
    (library_mod.LibraryClashError, 5), (style.StyleClashError, 5),
    (slicer.SliceIntegrityError, 6), (sheetcopy.SheetCopyIntegrityError, 6),
    (sanitize_mod.SanitizeUsageError, 2), (prune_mod.PruneUsageError, 2), (slicer.SliceUsageError, 2),
    (style.StyleUsageError, 2), (sheetcopy.SheetCopyUsageError, 2), (library_mod.LibraryUsageError, 2),
    (scaffold.ScaffoldUsageError, 2),
])
def test_exit_code_for_new_classes(cls, code):
    assert exit_code_for(cls("x")) == code
    assert isinstance(cls("x"), ValueError)
