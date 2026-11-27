"""Every command that writes a user-chosen -o file refuses an existing file and the input workbook."""

import os
import shutil
import stat
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

from py_tbparse.cli import main  # noqa: E402
from test_templates import filtering  # noqa: E402,F401

FIX = Path(__file__).parent / "fixtures"
WENJIE = FIX / "test_for_wenjie.twb"
LIB = FIX / "library"
REFUSED = "already exists; move or delete it first"


@pytest.fixture
def wb(tmp_path):
    dest = tmp_path / "demo.twb"
    shutil.copy(WENJIE, dest)
    return dest


def run(capsys, *argv):
    try:
        rc = main([str(a) for a in argv])
    except SystemExit as e:
        rc = e.code
    return rc, capsys.readouterr().err


def commands(wb, out):
    """Name -> argv for each command that writes `-o out` through the shared helper or its own path."""
    other = wb.with_name("other.twb")
    shutil.copy(WENJIE, other)
    return {
        "fields": [wb, "fields", "-f", "csv", "-o", out],
        "graph": [wb, "graph", "-o", out],
        "validate": [wb, "validate", "-o", out],
        "diff": ["diff", wb, other, "overview", "-o", out],
        "batch": ["batch", wb.parent, "overview", "-o", out],
        "audit": ["audit", wb, "--fail-on", "never", "-o", out],
        "docs": ["docs", wb, "-o", out],
        "dictionary": ["dictionary", wb, "-o", out],
        "diff-xml": ["diff-xml", wb, other, "-o", out],
        "rename": [wb, "field-renames", "-o", out],
        "library-export": ["library", "export", LIB / "source.twb", "-o", out],
    }


NAMES = ["fields", "graph", "validate", "diff", "batch", "audit", "docs", "dictionary", "diff-xml", "rename",
         "library-export"]


@pytest.mark.parametrize("name", NAMES)
def test_existing_output_is_refused_and_untouched(name, wb, tmp_path, capsys):
    out = tmp_path / "keep.out"
    out.write_bytes(b"keep me")
    rc, err = run(capsys, *commands(wb, out)[name])
    assert rc not in (0, None)
    assert REFUSED in err and err.startswith("error: ")
    assert "Traceback" not in err and "Errno" not in err
    assert out.read_bytes() == b"keep me"


@pytest.mark.parametrize("name", NAMES)
def test_fresh_output_is_written(name, wb, tmp_path, capsys):
    out = tmp_path / "new.out"
    rc, err = run(capsys, *commands(wb, out)[name])
    assert rc in (0, 1, 2), err
    assert out.is_file() and (name == "diff-xml" or out.stat().st_size > 0)   # identical inputs: empty diff
    assert REFUSED not in err


@pytest.mark.parametrize("name", ["fields", "graph", "validate", "audit", "docs", "rename", "diff", "diff-xml"])
def test_output_equal_to_the_input_is_refused(name, wb, capsys):
    before = wb.read_bytes()
    rc, err = run(capsys, *commands(wb, wb)[name])
    assert rc not in (0, None)
    assert "input" in err or "workbook" in err
    assert "Traceback" not in err
    assert wb.read_bytes() == before


def test_output_reached_by_another_path_to_the_input_is_refused(wb, tmp_path, capsys):
    before = wb.read_bytes()
    sneaky = tmp_path / "sub" / ".." / wb.name
    (tmp_path / "sub").mkdir()
    rc, err = run(capsys, wb, "fields", "-f", "csv", "-o", sneaky)
    assert rc == 1 and "input" in err
    assert wb.read_bytes() == before


def test_template_show_markdown_refuses_existing(filtering, tmp_path, capsys):
    from py_tbparse.templates import make_template
    tpl = make_template(str(filtering), output_path=str(tmp_path / "f.template.twbx"))
    out = tmp_path / "SHOW.md"
    out.write_text("keep me")
    rc, err = run(capsys, "template", "show", tpl, "--markdown", "-o", out)
    assert rc == 1 and REFUSED in err and "Traceback" not in err
    assert out.read_text() == "keep me"
    fresh = tmp_path / "fresh.md"
    rc, err = run(capsys, "template", "show", tpl, "--markdown", "-o", fresh)
    assert rc == 0 and fresh.read_text()
    before = Path(tpl).read_bytes()
    rc, err = run(capsys, "template", "show", tpl, "--markdown", "-o", tpl)
    assert rc == 1 and Path(tpl).read_bytes() == before


def test_library_export_overwrite_flag_still_replaces(tmp_path, capsys):
    out = tmp_path / "keep.json"
    out.write_text("old")
    rc, err = run(capsys, "library", "export", LIB / "source.twb", "-o", out)
    assert rc == 1 and "Errno" not in err and REFUSED in err and out.read_text() == "old"
    rc, err = run(capsys, "library", "export", LIB / "source.twb", "-o", out, "--overwrite")
    assert rc == 0 and out.read_text() != "old"


def test_save_library_raises_output_refused(tmp_path):
    from py_tbparse import TwbParser, export_library, save_library
    from py_tbparse.errors import OutputRefusedError
    out = tmp_path / "l.json"
    out.write_text("x")
    with pytest.raises(OutputRefusedError, match="already exists"):
        save_library(export_library(TwbParser(str(LIB / "source.twb"))), out)
    assert out.read_text() == "x"


def test_missing_folder_is_a_clean_error(wb, tmp_path, capsys):
    rc, err = run(capsys, wb, "fields", "-f", "csv", "-o", tmp_path / "nodir" / "x.csv")
    assert rc == 1
    assert err.startswith("error: cannot write ") and "No such file" in err and "Traceback" not in err


@pytest.mark.skipif(os.name == "nt" or (hasattr(os, "geteuid") and os.geteuid() == 0), reason="needs permissions")
def test_read_only_folder_is_a_clean_error(wb, tmp_path, capsys):
    ro = tmp_path / "ro"
    ro.mkdir()
    ro.chmod(stat.S_IRUSR | stat.S_IXUSR)
    try:
        rc, err = run(capsys, wb, "fields", "-f", "csv", "-o", ro / "x.csv")
    finally:
        ro.chmod(stat.S_IRWXU)
    assert rc == 1 and "Permission denied" in err and "Traceback" not in err
