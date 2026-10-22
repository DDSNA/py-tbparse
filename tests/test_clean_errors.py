"""A malformed .twb or a corrupt .twbx gives one `error:` line, not a traceback, and the exit code each command
already had (1 for the plain table commands, `diff` and `rename`)."""

import sys
import zipfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

from py_tbparse import cli

GOOD = str(Path(__file__).parent / "fixtures" / "test_for_wenjie.twb")


def broken(tmp_path, kind):
    if kind == "empty":
        p = tmp_path / "empty.twb"
        p.write_bytes(b"")
    elif kind == "truncated":
        p = tmp_path / "trunc.twb"
        p.write_text("<workbook", encoding="utf-8")
    elif kind == "not-zip":
        p = tmp_path / "notzip.twbx"
        p.write_text("this is not a zip", encoding="utf-8")
    else:  # zip with no workbook inside would be a different error; a damaged zip header is enough here
        p = tmp_path / "damaged.twbx"
        good = tmp_path / "g.zip"
        with zipfile.ZipFile(good, "w") as z:
            z.writestr("a.twb", "<workbook/>")
        p.write_bytes(good.read_bytes()[:30])
    return str(p)


KINDS = ["empty", "truncated", "not-zip", "damaged-zip"]


def check(capsys, code, path):
    err = capsys.readouterr().err
    assert code == 1
    assert "Traceback" not in err
    lines = err.strip().splitlines()
    assert len(lines) == 1
    assert lines[0].startswith("error: ")
    assert f"{path}: not a readable Tableau workbook (" in lines[0] and lines[0].endswith(")")


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("table", ["overview", "validate", "graph", "fields"])
def test_table_commands(tmp_path, capsys, kind, table):
    path = broken(tmp_path, kind)
    check(capsys, cli.main([path, table]), path)


@pytest.mark.parametrize("kind", KINDS)
def test_rename(tmp_path, capsys, kind):
    path = broken(tmp_path, kind)
    check(capsys, cli.main(["rename", path]), path)


@pytest.mark.parametrize("kind", KINDS)
def test_rename_missing(tmp_path, capsys, kind):
    path = broken(tmp_path, kind)
    check(capsys, cli.main(["rename", path, "--missing", "--reference", GOOD]), path)


@pytest.mark.parametrize("kind", KINDS)
def test_rename_reference(tmp_path, capsys, kind):
    path = broken(tmp_path, kind)
    code = cli.main(["rename", GOOD, "--reference", path])
    err = capsys.readouterr().err
    assert code == 1 and "Traceback" not in err
    assert err.startswith("error: reference workbook: ") and "not a readable Tableau workbook" in err


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("first", [True, False])
def test_diff(tmp_path, capsys, kind, first):
    path = broken(tmp_path, kind)
    argv = ["diff", path, GOOD] if first else ["diff", GOOD, path]
    check(capsys, cli.main(argv), path)


def test_missing_file_message_is_unchanged(tmp_path, capsys):
    code = cli.main([str(tmp_path / "nope.twb"), "overview"])
    err = capsys.readouterr().err
    assert code == 1 and err.startswith("error: ") and "not a readable" not in err
