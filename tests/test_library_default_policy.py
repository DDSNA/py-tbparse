"""Issue #128: the library API still defaults `on_clash` to 'rename' but warns when it is not passed
(the default becomes 'fail' in 0.6.0). The CLI and the GUI pass the policy themselves and must stay silent
(the GUI endpoint tests in test_webgui_libraries.py and test_gui_libraries.py are also run with
`-W error::DeprecationWarning` in CI-style checks)."""

import sys
import warnings
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

from py_tbparse import TwbParser, build_imported_workbook, cli, export_library, import_library, plan_import  # noqa: E402

FIX = Path(__file__).parent / "fixtures" / "library"


@pytest.fixture
def target():
    return TwbParser(str(FIX / "target.twb"))


@pytest.fixture
def library():
    return export_library(TwbParser(str(FIX / "source.twb")))


def _calls(target, library, tmp_path, **kw):
    return {
        "plan_import": lambda: plan_import(target, library, **kw),
        "build_imported_workbook": lambda: build_imported_workbook(target, library, **kw),
        "import_library": lambda: import_library(target, library, output_path=str(tmp_path / "o.twb"), **kw),
    }


@pytest.mark.parametrize("name", ["plan_import", "build_imported_workbook", "import_library"])
def test_api_warns_when_on_clash_is_omitted(name, target, library, tmp_path):
    with pytest.warns(DeprecationWarning, match="0.6.0") as rec:
        _calls(target, library, tmp_path)[name]()     # behaviour is still rename: no LibraryError
    assert len(rec) == 1 and rec[0].filename == __file__      # points at the caller, not at library.py


@pytest.mark.parametrize("name", ["plan_import", "build_imported_workbook", "import_library"])
@pytest.mark.parametrize("policy", ["rename", "skip"])
def test_api_is_silent_when_on_clash_is_passed(name, policy, target, library, tmp_path):
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        _calls(target, library, tmp_path, on_clash=policy)[name]()


def test_omitted_still_means_rename(target, library):
    with pytest.warns(DeprecationWarning):
        omitted = plan_import(target, library)
    assert omitted.equals(plan_import(target, library, on_clash="rename"))


def test_cli_and_gui_paths_do_not_warn(tmp_path, capsys):
    lib = tmp_path / "k.library.json"
    target = tmp_path / "t.twb"
    target.write_bytes((FIX / "target.twb").read_bytes())
    with warnings.catch_warnings():
        warnings.simplefilter("error", DeprecationWarning)
        assert cli.main(["library", "export", str(FIX / "source.twb"), "-o", str(lib)]) == 0
        assert cli.main(["library", "import", str(target), str(lib)]) == 1                    # default: fail
        assert cli.main(["library", "import", str(target), str(lib), "--on-clash", "rename", "--write"]) == 0
        assert cli.main(["sheet", "copy", str(FIX / "source.twb"), "--sheet", "x", "--to", str(target)]) in (0, 1, 2)
    capsys.readouterr()

