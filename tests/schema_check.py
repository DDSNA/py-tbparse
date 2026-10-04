"""Check workbook XML against Tableau's published schema (tests/schemas).

The XSD is Tableau's own (Apache-2.0, github.com/tableau/tableau-document-schemas) and only checks
structure: passing does not prove a workbook opens in Tableau. It also describes the newest format
(2026.2), so most real, older workbooks do not pass it. Hence the check is differential: errors the
input already had are noise, errors the output has and the input did not are ours.

Not part of the package; tests and scripts import it as a top-level module.
"""

from __future__ import annotations

import io
import re
import zipfile
from functools import lru_cache
from pathlib import Path
from typing import Union

from lxml import etree

SCHEMA_DIR = Path(__file__).parent / "schemas"
XSD_NAME = "twb_2026.2.0.xsd"

_XS = "{http://www.w3.org/2001/XMLSchema}"
# The XSD imports two namespaces without saying where they are defined.
_STUBS = {"/xml/user": "user-stub.xsd", "/XML/1998/namespace": "xml-stub.xsd"}


@lru_cache(maxsize=1)
def _schema() -> etree.XMLSchema:
    tree = etree.parse(str(SCHEMA_DIR / XSD_NAME))
    for imp in tree.getroot().iter(_XS + "import"):
        for tail, stub in _STUBS.items():
            if imp.get("namespace", "").endswith(tail):
                imp.set("schemaLocation", stub)
    # base_url makes the relative stub locations resolve beside the XSD
    return etree.XMLSchema(etree.fromstring(etree.tostring(tree), base_url=str(SCHEMA_DIR / XSD_NAME)))


def twb_bytes(source: Union[str, Path, bytes]) -> bytes:
    """The workbook XML of a .twb, a .twbx, or bytes already holding XML."""
    if isinstance(source, bytes):
        if not source.startswith(b"PK"):
            return source
        source = io.BytesIO(source)               # a packaged workbook held in memory
    elif Path(source).suffix.lower() != ".twbx":
        return Path(source).read_bytes()
    with zipfile.ZipFile(source) as z:
        return z.read(sorted(n for n in z.namelist() if n.endswith(".twb"))[0])


def _signature(error) -> tuple[str, str]:
    # indices and the quoted values vary between workbooks; element and attribute names do not
    path = re.sub(r"\[\d+\]", "", error.path or "")
    message = re.sub(r"\{[^}]*\}", "", error.message)
    # uniqueness and reference errors quote the offending name, which a rename changes
    message = re.sub(r"key-sequence \[.*?\]", "key-sequence [_]", message)
    return path, message


def schema_errors(source: Union[str, Path, bytes]) -> set[tuple[str, str]]:
    """The distinct (path, message) errors of a workbook against the schema; empty when valid."""
    schema = _schema()
    doc = etree.parse(io.BytesIO(twb_bytes(source)))
    if schema.validate(doc):
        return set()
    return {_signature(e) for e in schema.error_log}


def new_schema_errors(before, after) -> list[tuple[str, str]]:
    """Errors `after` has that `before` did not: what a transformation introduced."""
    return sorted(schema_errors(after) - schema_errors(before))
