"""Smoke tests on real Tableau-written workbooks (tests/fixtures/public)."""

from pathlib import Path

import pytest

from py_tbparse import TwbParser, apply_field_renames, suggest_field_renames
from py_tbparse._tables import TABLE_SPECS

PUBLIC = sorted((Path(__file__).parent / "fixtures" / "public").glob("*.tw*"))


def test_public_fixtures_present():
    assert len(PUBLIC) >= 4


@pytest.mark.parametrize("path", PUBLIC, ids=lambda p: p.name)
def test_every_table_extracts(path):
    parser = TwbParser(str(path))
    for name, spec in TABLE_SPECS.items():
        spec(parser)  # must not raise


@pytest.mark.parametrize("path", PUBLIC, ids=lambda p: p.name)
def test_rename_write_round_trip(path, tmp_path):
    parser = TwbParser(str(path))
    renames = suggest_field_renames(parser)
    out = apply_field_renames(parser, renames=renames, output_path=str(tmp_path / f"out{path.suffix}"))
    again = TwbParser(out)
    wanted = set(renames[renames["changed"] & (renames["reason"] != "conflict")]["suggested"])
    assert wanted <= set(again.get_fields()["caption"].dropna())
