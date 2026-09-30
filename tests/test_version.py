from __future__ import annotations

import re
from importlib.metadata import version
from pathlib import Path

import twbparser_py

_PYPROJECT = Path(__file__).resolve().parent.parent / "pyproject.toml"


def _project_name() -> str:
    text = _PYPROJECT.read_text(encoding="utf-8")
    project = re.search(r"^\[project\]\s*$(.*?)(?=^\[|\Z)", text, re.M | re.S)
    assert project is not None
    name = re.search(r'^name\s*=\s*"([^"]+)"', project.group(1), re.M)
    assert name is not None
    return name.group(1)


def test_version_matches_installed_distribution():
    # __version__ must look up the distribution named in pyproject.toml, or
    # it silently falls back to "0.0.0+unknown" after a project rename.
    assert twbparser_py.__version__ == version(_project_name())
    assert twbparser_py.__version__ != "0.0.0+unknown"
