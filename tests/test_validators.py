import pandas as pd

from py_tbparse import TwbParser
from py_tbparse.validators import _base_token, validate_relationships


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


def test_relationship_to_custom_sql_table_is_not_an_unknown_table(tmp_path):
    h = "A" * 32
    twb = tmp_path / "custom_sql.twb"
    twb.write_text(f"""<?xml version='1.0'?><workbook><datasources><datasource name='federated.1'>
<connection class='federated'><relation type='collection'>
<relation connection='sqlserver.0' name='Fact' table='[dbo].[Fact]' type='table'/>
<relation connection='sqlserver.0' name='Custom SQL Query' type='text'>select 1 as EmployeeKey</relation>
</relation></connection>
<object-graph><objects>
<object caption='Fact' id='Fact_{h}'><properties context=''><relation connection='sqlserver.0' name='Fact' table='[dbo].[Fact]' type='table'/></properties></object>
<object caption='Custom SQL Query' id='Custom SQL Query_{h}'><properties context=''><relation connection='sqlserver.0' name='Custom SQL Query' type='text'>select 1</relation></properties></object>
</objects><relationships><relationship><expression op='='><expression op='[EmployeeKey (Fact)]'/><expression op='[EmployeeKey (Custom SQL Query)]'/></expression>
<first-end-point object-id='Fact_{h}'/><second-end-point object-id='Custom SQL Query_{h}'/></relationship></relationships></object-graph>
<column name='[EmployeeKey (Fact)]' datatype='integer'/><column name='[EmployeeKey (Custom SQL Query)]' datatype='integer'/>
</datasource></datasources></workbook>""")
    result = TwbParser(str(twb)).validate()
    assert "unknown_tables" not in result["issues"]
