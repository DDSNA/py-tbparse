"""docs/api.md lists exactly the names in py_tbparse.__all__, and its examples run."""
import contextlib
import inspect
import io
import os
import re
from pathlib import Path

import pytest

import py_tbparse

ROOT = Path(__file__).resolve().parent.parent
DOC = ROOT / "docs" / "api.md"
TEXT = DOC.read_text(encoding="utf-8")
# A documented name starts a bullet: "- `name`: summary".
DOCUMENTED = set(re.findall(r"^- `([A-Za-z_]\w*)`", TEXT, flags=re.M))
EXAMPLES = re.findall(r"^```python\n(.*?)^```", TEXT, flags=re.M | re.S)


def test_every_public_name_is_documented():
    missing = sorted(set(py_tbparse.__all__) - DOCUMENTED)
    assert not missing, f"in __all__ but not in docs/api.md: {missing}"


def test_every_documented_name_is_public():
    extra = sorted(DOCUMENTED - set(py_tbparse.__all__))
    assert not extra, f"in docs/api.md but not in __all__: {extra}"


def test_no_name_documented_twice():
    names = re.findall(r"^- `([A-Za-z_]\w*)`", TEXT, flags=re.M)
    assert len(names) == len(set(names))


# inspect.getdoc also takes a docstring from a base class (SliceError and PruneError
# inherit ValueError's); their own docstrings belong to the exception-class work (#186).
def test_every_public_name_has_a_docstring():
    bare = [n for n in py_tbparse.__all__ if not (inspect.getdoc(getattr(py_tbparse, n)) or "").strip()]
    assert not bare, f"public names without a docstring: {bare}"


def test_examples_found():
    assert len(EXAMPLES) >= 3


@pytest.mark.parametrize("code", EXAMPLES, ids=[f"example{i}" for i in range(len(EXAMPLES))])
def test_example_runs(code, monkeypatch):
    monkeypatch.chdir(ROOT)
    with contextlib.redirect_stdout(io.StringIO()):
        exec(compile(code, "docs/api.md", "exec"), {"__name__": "__api_doc__"})
