"""Every deliberate py-tbparse exception derives from PyTbparseError and stays a ValueError (#186)."""
import importlib
import inspect
import pkgutil

import pytest

import py_tbparse
from py_tbparse import PyTbparseError


def _custom_exceptions():
    found = {}
    for info in pkgutil.walk_packages(py_tbparse.__path__, "py_tbparse."):
        try:
            mod = importlib.import_module(info.name)
        except ImportError:  # optional dependency missing
            continue
        for name, obj in vars(mod).items():
            if (inspect.isclass(obj) and issubclass(obj, Exception)
                    and obj.__module__.startswith("py_tbparse") and obj is not PyTbparseError):
                found[f"{obj.__module__}.{obj.__qualname__}"] = obj
    return found


def test_discovery_finds_the_known_exceptions():
    names = {c.__name__ for c in _custom_exceptions().values()}
    assert {"TemplateError", "SanitizeError", "PruneError", "SliceError", "SheetCopyError", "ScaffoldError",
            "StyleError", "LibraryError", "PackageTooLargeError", "SheetMissing", "SheetEmpty",
            "SheetCopyAbort"} <= names


@pytest.mark.parametrize("path", sorted(_custom_exceptions()))
def test_exception_has_common_base(path):
    cls = _custom_exceptions()[path]
    assert issubclass(cls, PyTbparseError), f"{path} must derive from PyTbparseError"
    assert issubclass(cls, ValueError)


def test_base_is_exported_and_message_unchanged():
    assert "PyTbparseError" in py_tbparse.__all__
    assert issubclass(PyTbparseError, ValueError)
    assert str(py_tbparse.TemplateError("boom")) == "boom"
