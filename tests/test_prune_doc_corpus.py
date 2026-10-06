"""`prune_doc(datasources=True)` over the corpus (skipped when `tests/corpus/files` is missing): no exception,
the result re-parses, schema errors do not rise, no datasource name is left referenced after a datasource was
removed, A003 does not rise, and a second run is a no-op. The corpus is never committed."""

import copy
import sys
from pathlib import Path

import pytest
from lxml import etree

sys.path.insert(0, str(Path(__file__).parent))

from schema_check import new_schema_errors

from py_tbparse import TwbParser, audit, prune_doc

CORPUS = Path(__file__).parent / "corpus"
FILES = sorted((CORPUS / "files").glob("*.twb")) if (CORPUS / "files").is_dir() else []

pytestmark = pytest.mark.skipif(not FILES, reason="corpus not fetched: python scripts/fetch_corpus.py")


def test_corpus_datasource_prune(tmp_path):
    dropped = parameters = 0
    for i, path in enumerate(FILES):
        parser = TwbParser(str(path))
        doc = copy.deepcopy(parser.xml_doc)
        report = prune_doc(doc, sheets=True, datasources=True)
        gone = [r for r in report["removed"] if r["category"] == "datasources"]
        dropped += len(gone)
        parameters += sum(1 for r in gone if r["name"] == "Parameters")
        out = tmp_path / f"{i}.twb"
        out.write_bytes(etree.tostring(doc, encoding="utf-8", xml_declaration=True))
        TwbParser(str(out))
        assert new_schema_errors(str(path), str(out)) == [], path.name
        text = out.read_text(encoding="utf-8")
        for r in gone:
            assert f"'{r['name']}'" not in text and f"\"{r['name']}\"" not in text, (path.name, r["name"])
        assert len(audit(str(out), only=["A003"])) <= len(audit(str(path), only=["A003"])), path.name
        assert prune_doc(copy.deepcopy(doc), sheets=True, datasources=True)["removed"] == [], path.name
    print(f"datasources dropped: {dropped} (Parameters: {parameters}) in {len(FILES)} workbooks")
