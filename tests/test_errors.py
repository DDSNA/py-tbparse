"""py_tbparse.errors: categories and exit codes (A1 of the 0.6.0 plan; no command changes)."""

import errno
import json
import pickle
import zipfile

import pandas.errors
import pytest
from lxml import etree

import py_tbparse
from py_tbparse import errors
from py_tbparse.errors import (
    ExitCode,
    InputError,
    IntegrityError,
    OutputRefusedError,
    PyTbparseError,
    RefusedError,
    UsageError,
    exit_code_for,
    first_by_precedence,
)

CATEGORIES = [UsageError, InputError, RefusedError, OutputRefusedError, IntegrityError]


def _xml_error():
    try:
        etree.fromstring(b"<a>")
    except etree.XMLSyntaxError as e:
        return e


def test_base_is_the_same_object_everywhere():
    from py_tbparse import _xml

    assert py_tbparse.PyTbparseError is _xml.PyTbparseError is errors.PyTbparseError


@pytest.mark.parametrize("cls", CATEGORIES)
def test_categories_are_pytbparse_errors_and_value_errors(cls):
    assert issubclass(cls, PyTbparseError) and issubclass(cls, ValueError)


@pytest.mark.parametrize("old", [FileExistsError, ValueError, OSError, PyTbparseError, RefusedError])
def test_output_refused_is_caught_by_every_old_handler(old):
    with pytest.raises(old):
        raise OutputRefusedError("refusing to overwrite existing file: out.twb")


@pytest.mark.parametrize("cls", [PyTbparseError] + CATEGORIES)
def test_pickle_round_trip_keeps_type_and_message(cls):
    e = cls("some message")
    f = pickle.loads(pickle.dumps(e))
    assert type(f) is cls and str(f) == str(e) and f.args == e.args == ("some message",)


@pytest.mark.parametrize(
    "exc,code",
    [
        (UsageError("x"), 2),
        (InputError("x"), 4),
        (RefusedError("x"), 5),
        (OutputRefusedError("x"), 5),
        (IntegrityError("x"), 6),
        (PyTbparseError("x"), 4),
    ],
)
def test_exit_code_for_each_class(exc, code):
    assert exit_code_for(exc) == code


@pytest.mark.parametrize(
    "exc",
    [
        FileNotFoundError("x"),
        IsADirectoryError("x"),
        PermissionError("x"),
        OSError("x"),
        zipfile.BadZipFile("x"),
        json.JSONDecodeError("x", "", 0),
        _xml_error(),
        pandas.errors.ParserError("x"),
        pandas.errors.EmptyDataError("x"),
        zipfile.LargeZipFile("x"),
        UnicodeDecodeError("utf-8", b"\xff", 0, 1, "invalid start byte"),
        OSError(errno.ENOENT, "x"),
        OSError(errno.EACCES, "x"),
    ],
)
def test_exit_code_for_builtins(exc):
    assert exit_code_for(exc) == 4


@pytest.mark.parametrize(
    "exc",
    [
        OSError(errno.ENOSPC, "No space left on device"),
        OSError(errno.EDQUOT, "Disk quota exceeded"),
        OSError(errno.EIO, "Input/output error"),
        TimeoutError("x"),
        ConnectionResetError("x"),
        UnicodeEncodeError("ascii", "\u00e9", 0, 1, "ordinal not in range"),
        MemoryError(),
    ],
)
def test_exit_code_for_machine_failures_are_crashes(exc):
    assert exit_code_for(exc) == 3


def test_a_closed_pipe_is_not_an_error():
    assert exit_code_for(BrokenPipeError(errno.EPIPE, "Broken pipe")) == 0


def test_ctrl_c_is_130_and_beats_everything():
    assert exit_code_for(KeyboardInterrupt()) == errors.INTERRUPTED == 130
    assert first_by_precedence([4, 130, 3]) == 130


@pytest.mark.parametrize("exc", [KeyError("x"), RuntimeError("x"), ValueError("x"), TypeError("x")])
def test_exit_code_for_unknown_is_crash(exc):
    assert exit_code_for(exc) == 3


def test_two_parent_subclass_takes_the_category_code():
    class Feat(PyTbparseError):
        pass

    class X(Feat, IntegrityError):
        pass

    class Y(Feat, RefusedError):
        pass

    assert exit_code_for(X("x")) == 6
    assert exit_code_for(Y("x")) == 5
    assert exit_code_for(Feat("x")) == 4


@pytest.mark.parametrize("codes,want", [([], 0), ([1, 0], 1), ([7, 1], 7), ([4, 3], 3), ([2, 4], 2), ([9], 3)])
def test_first_by_precedence(codes, want):
    assert first_by_precedence(codes) == want


def test_exit_code_enum_values():
    assert {c.name: int(c) for c in ExitCode} == {
        "OK": 0,
        "FINDING": 1,
        "USAGE": 2,
        "CRASH": 3,
        "BAD_INPUT": 4,
        "REFUSED": 5,
        "INTEGRITY": 6,
        "PARTIAL": 7,
    }
