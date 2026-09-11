import pandas as pd

from twbparser_py import TwbParser
from twbparser_py.validators import validate_relationships


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
