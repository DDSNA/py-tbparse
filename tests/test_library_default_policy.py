"""Issue #128: `on_clash` defaults to 'fail' in the library API (since 0.6.0), as in the CLI, the GUI, sheet copy
and dashboard copy. The warning that announced the change (0.5.5 to 0.5.7) is gone. Style keeps 'fail' too."""

import inspect
import sys
import warnings
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

import py_tbparse  # noqa: E402
from py_tbparse import (  # noqa: E402
    LibraryError, TwbParser, build_imported_workbook, cli, export_library, import_library, library, plan_import, style,
)
from test_webgui_libraries import (  # noqa: E402,F401  (the fixtures and helpers of the GUI half)
    _library_of, _load, _postj, _upload, server, source,
)

FIX = Path(__file__).parent / "fixtures" / "library"
FUNCTIONS = ["plan_import", "build_imported_workbook", "import_library"]


@pytest.fixture
def target():
    return TwbParser(str(FIX / "target.twb"))


@pytest.fixture
def lib():
    return export_library(TwbParser(str(FIX / "source.twb")))


def _calls(target, lib, tmp_path, **kw):
    return {
        "plan_import": lambda: plan_import(target, lib, **kw),
        "build_imported_workbook": lambda: build_imported_workbook(target, lib, **kw),
        "import_library": lambda: import_library(target, lib, output_path=str(tmp_path / "o.twb"), **kw),
    }


@pytest.mark.parametrize("name", FUNCTIONS)
def test_omitted_on_clash_fails(name, target, lib, tmp_path):
    with pytest.raises(LibraryError, match="on_clash='fail'"):
        _calls(target, lib, tmp_path)[name]()
    assert not (tmp_path / "o.twb").exists()          # for import_library: nothing was written


@pytest.mark.parametrize("name", FUNCTIONS)
def test_no_deprecation_warning_left(name, target, lib, tmp_path):
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        with pytest.raises(LibraryError):
            _calls(target, lib, tmp_path)[name]()


@pytest.mark.parametrize("name", FUNCTIONS)
@pytest.mark.parametrize("policy", ["rename", "skip"])
def test_api_is_silent_when_on_clash_is_passed(name, policy, target, lib, tmp_path):
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        _calls(target, lib, tmp_path, on_clash=policy)[name]()


def test_default_is_fail_in_every_entry_point(target, lib, tmp_path, capsys, server, source):
    # the API
    with pytest.raises(LibraryError, match="Profit Ratio"):
        plan_import(target, lib)
    # the CLI: the same pair of files, no --on-clash; exit 1 (an error) and no file
    lib_file = tmp_path / "k.library.json"
    t_file = tmp_path / "t.twb"
    t_file.write_bytes((FIX / "target.twb").read_bytes())
    assert cli.main(["library", "export", str(FIX / "source.twb"), "-o", str(lib_file)]) == 0
    rc = cli.main(["library", "import", str(t_file), str(lib_file), "--write", "-o", str(tmp_path / "out.twb")])
    assert rc != 0 and rc == 1
    assert not (tmp_path / "out.twb").exists()
    capsys.readouterr()
    # the GUI: /library/plan with no on_clash is blocked on a clash (a library from `source`, a target that
    # holds "Ratio" under another formula), and renaming is what the view asks for to list every clash
    data, _ = _library_of(server, source, ["[Calculation_1]"])
    other = Path(source).with_name("clash.twb")
    other.write_text(Path(source).read_text(encoding="utf-8").replace("[Sales] / [Profit]", "[Profit] / [Sales]"),
                     encoding="utf-8")
    _load(server, str(other))
    assert _upload(server, data)[0] == 200
    status, plan = _postj(server, "/library/plan", {})
    assert status == 200 and plan["policy"] == "fail" and plan["blocked"] and "Ratio" in plan["blocked"]
    with pytest.raises(LibraryError, match="Ratio"):             # the API stops on the same clash
        plan_import(TwbParser(str(other)), data_to_library(data))


def data_to_library(raw):
    import json
    return json.loads(raw)


@pytest.mark.parametrize("func", [plan_import, build_imported_workbook, import_library])
def test_signatures_default_to_fail(func):
    assert inspect.signature(func).parameters["on_clash"].default == "fail"
    assert func is getattr(library, func.__name__)


def test_the_sentinel_and_the_helper_are_gone():
    assert not hasattr(py_tbparse.library, "_resolve_on_clash")
    assert not hasattr(py_tbparse.library, "_NOT_PASSED")
    assert not hasattr(py_tbparse.library, "_NotPassed")


@pytest.mark.parametrize("func", [style.plan_palette_import, style.build_with_palettes, style.import_palettes])
def test_style_defaults_stay_fail(func):
    assert inspect.signature(func).parameters["on_clash"].default == "fail"
