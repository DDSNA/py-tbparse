"""Sanitize over the 200 real workbooks of `tests/corpus` (skipped when not fetched): it must not raise, the
output must parse, a second run must change nothing, and no server or user name may survive in a connection."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

from py_tbparse import TwbParser
from py_tbparse.sanitize import sanitize

CORPUS = Path(__file__).parent / "corpus"
FILES = sorted((CORPUS / "files").glob("*.twb")) if (CORPUS / "files").is_dir() else []

pytestmark = pytest.mark.skipif(not FILES, reason="corpus not fetched: python scripts/fetch_corpus.py")


def test_every_workbook_sanitizes_reparses_and_is_idempotent(tmp_path):
    for i, path in enumerate(FILES):
        out, again = tmp_path / f"{i}.twb", tmp_path / f"{i}b.twb"
        report = {}
        sanitize(str(path), str(out), report=report)
        TwbParser(str(out))
        second = {}
        sanitize(str(out), str(again), report=second)
        assert out.read_bytes() == again.read_bytes(), path.name
        assert sum(second["removed"].values()) == 0, path.name
        text = out.read_text(encoding="utf-8")
        conns = list(TwbParser(str(path)).xml_doc.iter("connection"))
        classes = {c.get("class", "").lower() for c in conns}
        for conn in conns:
            for attr in ("server", "username", "password"):
                value = conn.get(attr)
                # a user name that is also a connection class (`postgres`) stays: it is the class
                if value and len(value) >= 5 and value.lower() not in classes and value != "localhost":
                    assert value not in text, (path.name, attr)
