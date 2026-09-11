import pandas as pd

from twbparser_py import TwbParser
from twbparser_py.validators import _base_token, validate_relationships


class _FakeParser:
    def __init__(self, rels, ds, flds, calcs):
        self._rels = rels
        self._ds = ds
        self._flds = flds
        self._calcs = calcs

    def get_relationships(self):
        return self._rels

    def get_datasources(self):
        return self._ds

    def get_fields(self):
        return self._flds

    def get_calculated_fields(self):
        return self._calcs


def test_validate_relationships_ok_when_no_relationships():
    parser = _FakeParser(pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame())
    result = validate_relationships(parser)
    assert result == {"ok": True, "issues": {}}


def test_validate_relationships_flags_unknown_table():
    rels = pd.DataFrame(
        [{"left_table": "Orders", "right_table": "Ghost", "left_field": "ID", "right_field": "ID"}]
    )
    ds = pd.DataFrame({"datasource": ["Orders"]})
    flds = pd.DataFrame({"field_clean": ["ID"], "name": ["ID"], "caption": [None]})
    calcs = pd.DataFrame({"name": [], "tableau_internal_name": []})
    parser = _FakeParser(rels, ds, flds, calcs)
    result = validate_relationships(parser)
    assert result["ok"] is False
    assert "unknown_tables" in result["issues"]


def test_validate_relationships_on_real_fixture(wenjie_path):
    parser = TwbParser(wenjie_path)
    result = parser.validate()
    assert result["ok"] is True


def test_base_token_well_formed_function_call():
    assert _base_token("INT([GEOID])") == "GEOID"


def test_base_token_whitespace_padded_value_does_not_simplify():
    # R runs the anchored NAME(...) regex on the raw value first; leading/
    # trailing whitespace makes the fullmatch fail, so R falls back to the
    # (bracket-stripped, trimmed) raw string rather than unwrapping the
    # function call. Pre-trimming before the regex (as a naive port would)
    # changes the result.
    assert _base_token(" INT([GEOID]) ") == "INT(GEOID)"
