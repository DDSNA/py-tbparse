"""Error categories and the exit code each one maps to.

Imports nothing from the rest of the package: other modules import this one.
"""

from __future__ import annotations

import enum
import json
import zipfile
from typing import Iterable


class ExitCode(enum.IntEnum):
    """The exit codes of the command line: 0 ok, 1 finding, 2 usage, 3 crash, 4 bad input, 5 refused, 6 integrity, 7 partial."""

    OK = 0
    FINDING = 1
    USAGE = 2
    CRASH = 3
    BAD_INPUT = 4
    REFUSED = 5
    INTEGRITY = 6
    PARTIAL = 7


PRECEDENCE: tuple[ExitCode, ...] = (
    ExitCode.CRASH,
    ExitCode.USAGE,
    ExitCode.BAD_INPUT,
    ExitCode.REFUSED,
    ExitCode.INTEGRITY,
    ExitCode.PARTIAL,
    ExitCode.FINDING,
    ExitCode.OK,
)


class PyTbparseError(ValueError):
    """Common base of the library's own exception classes (SliceError, TemplateError, StyleError, ...).

    It is a ``ValueError`` on purpose: existing ``except ValueError`` handlers keep working. Many checks
    still raise a plain ``ValueError`` or ``FileExistsError``; those are not instances of this class.
    Messages are unchanged and carry no error codes. The subclasses in this module say which exit code
    the command line gives.
    """


class UsageError(PyTbparseError):
    """A bad argument value, known without opening a file (exit code 2)."""


class InputError(PyTbparseError):
    """A file, or a name in it, cannot be used (exit code 4)."""


class RefusedError(PyTbparseError):
    """Declined on purpose; nothing was written (exit code 5)."""


class OutputRefusedError(RefusedError, FileExistsError):
    """The output file exists or is also an input; nothing was written (exit code 5)."""


class IntegrityError(PyTbparseError):
    """The result has, or would have, broken references (exit code 6)."""


def _input_types() -> tuple[type, ...]:
    from lxml import etree
    import pandas.errors

    return (
        OSError,
        zipfile.BadZipFile,
        json.JSONDecodeError,
        etree.XMLSyntaxError,
        pandas.errors.ParserError,
    )


def exit_code_for(exc: BaseException) -> int:
    """Exit code the command line gives for ``exc``: 2 usage, 5 refused, 6 integrity, 4 bad input, 3 anything else."""
    if isinstance(exc, UsageError):
        return int(ExitCode.USAGE)
    if isinstance(exc, RefusedError):
        return int(ExitCode.REFUSED)
    if isinstance(exc, IntegrityError):
        return int(ExitCode.INTEGRITY)
    if isinstance(exc, PyTbparseError):
        return int(ExitCode.BAD_INPUT)
    if isinstance(exc, _input_types()):
        return int(ExitCode.BAD_INPUT)
    return int(ExitCode.CRASH)


def first_by_precedence(codes: Iterable[int]) -> int:
    """The code from ``codes`` that comes first in ``PRECEDENCE`` (unknown codes count as crash; empty gives 0)."""
    seen = set()
    for c in codes:
        try:
            seen.add(ExitCode(c))
        except ValueError:
            seen.add(ExitCode.CRASH)
    for c in PRECEDENCE:
        if c in seen:
            return int(c)
    return int(ExitCode.OK)
