"""explain, check_data and the extended broken_sheets, on a small workbook with a calculation, a filter and a dashboard."""

import pandas as pd
import pytest

from py_tbparse import load_template, make_template, suggest_mapping
from py_tbparse.templates import (
    BROKEN_COLUMNS,
    CHECK_COLUMNS,
    EXPLAIN_COLUMNS,
    broken_sheets,
    check_data,
    explain,
    read_data,
)

BOOK = """<?xml version='1.0' encoding='utf-8'?>
<workbook version='18.1'>
  <datasources>
    <datasource name='federated.1' inline='true'>
      <connection class='federated'>
        <named-connections><named-connection name='textscan.1' caption='sales'>
          <connection class='textscan' directory='/d' filename='sales.csv'/>
        </named-connection></named-connections>
        <relation connection='textscan.1' name='sales.csv' table='[sales#csv]' type='table'>
          <columns header='yes'>
            <column datatype='integer' name='Amount' ordinal='0'/>
            <column datatype='string' name='Region' ordinal='1'/>
            <column datatype='string' name='order_id' ordinal='2'/>
            <column datatype='string' name='Notes' ordinal='3'/>
          </columns>
        </relation>
        <metadata-records>
          <metadata-record class='column'><remote-name>Amount</remote-name><remote-type>20</remote-type>
            <local-name>[Amount]</local-name><parent-name>[sales.csv]</parent-name><local-type>integer</local-type></metadata-record>
          <metadata-record class='column'><remote-name>Region</remote-name><remote-type>129</remote-type>
            <local-name>[Region]</local-name><parent-name>[sales.csv]</parent-name><local-type>string</local-type></metadata-record>
          <metadata-record class='column'><remote-name>order_id</remote-name><remote-type>129</remote-type>
            <local-name>[order_id]</local-name><parent-name>[sales.csv]</parent-name><local-type>string</local-type></metadata-record>
          <metadata-record class='column'><remote-name>Notes</remote-name><remote-type>129</remote-type>
            <local-name>[Notes]</local-name><parent-name>[sales.csv]</parent-name><local-type>string</local-type></metadata-record>
        </metadata-records>
      </connection>
      <column name='[Amount]' datatype='integer' role='measure' type='quantitative'/>
      <column name='[Region]' datatype='string' role='dimension' type='nominal'/>
      <column name='[order_id]' datatype='string' role='dimension' type='nominal'/>
      <column name='[Double]' caption='Double Amount' datatype='integer' role='measure' type='quantitative'>
        <calculation class='tableau' formula='[Amount] * 2'/>
      </column>
    </datasource>
  </datasources>
  <worksheets>
    <worksheet name='Totals'><table><view>
      <datasource-dependencies datasource='federated.1'>
        <column name='[Double]' datatype='integer' role='measure' type='quantitative'/>
        <column-instance column='[Double]' derivation='Sum' name='[sum:Double:qk]' pivot='key' type='quantitative'/>
        <column-instance column='[order_id]' derivation='None' name='[none:order_id:nk]' pivot='key' type='nominal'/>
      </datasource-dependencies>
    </view></table></worksheet>
    <worksheet name='By Region'><table><view>
      <datasource-dependencies datasource='federated.1'>
        <column name='[Region]' datatype='string' role='dimension' type='nominal'/>
        <column-instance column='[Region]' derivation='None' name='[none:Region:nk]' pivot='key' type='nominal'/>
      </datasource-dependencies>
      <filter class='categorical' column='[federated.1].[none:Region:nk]'><groupfilter function='member' level='[none:Region:nk]'/></filter>
    </view></table></worksheet>
  </worksheets>
  <dashboards>
    <dashboard name='Board'><zones><zone name='Totals' id='1'/><zone name='By Region' id='2'/></zones></dashboard>
  </dashboards>
</workbook>
"""


@pytest.fixture
def template(tmp_path):
    book = tmp_path / "sales.twb"
    book.write_text(BOOK, encoding="utf-8")
    return load_template(make_template(str(book)))


def data(tmp_path, text, name="d.csv"):
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return read_data(str(path))


def rows(frame, **where):
    keep = frame
    for column, value in where.items():
        keep = keep[keep[column] == value]
    return keep


# --- broken_sheets ----------------------------------------------------------------------------------

def test_broken_sheets_names_what_the_missing_field_breaks(template, tmp_path):
    d = data(tmp_path, "Region,order_id\nEast,o1\n")             # no Amount
    broken = broken_sheets(template, suggest_mapping(template, d))
    assert list(broken.columns) == BROKEN_COLUMNS
    [row] = broken.to_dict("records")
    assert row["field"] == "[Amount]" and row["sheets"] == "Totals"
    assert row["dashboards"] == "Board" and row["calculations"] == "Double Amount"


def test_broken_sheets_names_the_sheets_that_filter_on_a_missing_field(template, tmp_path):
    d = data(tmp_path, "Amount,order_id\n1,o1\n")                 # no Region
    [row] = broken_sheets(template, suggest_mapping(template, d)).to_dict("records")
    assert row["field"] == "[Region]" and row["filters"] == "By Region" and row["dashboards"] == "Board"


def test_nothing_is_broken_when_every_required_field_has_a_column(template, tmp_path):
    d = data(tmp_path, "Amount,Region,order_id\n1,East,o1\n")
    assert broken_sheets(template, suggest_mapping(template, d)).empty


# --- explain ----------------------------------------------------------------------------------------

def test_explain_lists_every_consequence_of_a_dropped_field(template, tmp_path):
    d = data(tmp_path, "Region,order_id\nEast,o1\n")
    out = explain(template, d, suggest_mapping(template, d))
    assert list(out.columns) == EXPLAIN_COLUMNS
    assert rows(out, change="field-dropped", kind="field")["object"].tolist() == ["Amount"]
    affected = {(r.kind, r.object) for r in rows(out, change="affected").itertuples()}
    assert affected == {("sheet", "Totals"), ("dashboard", "Board"), ("calculation", "Double Amount")}
    assert out["severity"].tolist() == sorted(out["severity"], key=["error", "warning", "info"].index)   # worst first
    assert rows(out, change="field-dropped", kind="fields")["object"].tolist() == ["1 fields no sheet uses"]


def test_explain_names_the_filter_and_a_type_change(template, tmp_path):
    d = data(tmp_path, "Amount,order_id\n1.5,o1\n")               # no Region; Amount arrives as a decimal
    out = explain(template, d, suggest_mapping(template, d))
    assert {(r.kind, r.object) for r in rows(out, change="affected").itertuples()} == {
        ("sheet", "By Region"), ("filter", "By Region"), ("dashboard", "Board")}
    [typed] = rows(out, change="type-changed").to_dict("records")
    assert typed["object"] == "Amount" and typed["detail"].startswith("integer -> real") and typed["severity"] == "info"


def test_explain_is_empty_when_nothing_changes(template, tmp_path):
    d = data(tmp_path, "Amount,Region,order_id,Notes\n1,East,o1,x\n")
    assert explain(template, d, suggest_mapping(template, d)).empty


def test_explain_notes_a_close_match(template, tmp_path):
    d = data(tmp_path, "Amount,Regionn,order_id\n1,East,o1\n")
    out = explain(template, d, suggest_mapping(template, d))
    [note] = rows(out, change="mapping-note").to_dict("records")
    assert note["object"] == "Region" and "close match" in note["detail"]


def test_explain_follows_an_edited_mapping(template, tmp_path):
    d = data(tmp_path, "Amount,Zone,order_id\n1,East,o1\n")
    mapping = suggest_mapping(template, d)
    assert "Region" in rows(explain(template, d, mapping), change="field-dropped")["object"].tolist()
    mapping.loc[mapping["field"] == "[Region]", ["mapped_to", "data_type"]] = ["Zone", "string"]
    assert "Region" not in rows(explain(template, d, mapping), change="field-dropped")["object"].tolist()


# --- check_data -------------------------------------------------------------------------------------

def test_check_data_warns_of_a_missing_dimension(template, tmp_path):
    d = data(tmp_path, "Amount,order_id\n1,o1\n")
    out = check_data(template, d, suggest_mapping(template, d))
    assert list(out.columns) == CHECK_COLUMNS
    [hit] = rows(out, check="dimension-missing").to_dict("records")
    assert hit["field"] == "[Region]" and hit["severity"] == "warning" and "By Region" in hit["detail"]


def test_check_data_finds_an_empty_required_column(template, tmp_path):
    d = data(tmp_path, "Amount,Region,order_id\n,East,o1\n ,West,o2\n")
    out = check_data(template, d, suggest_mapping(template, d))
    [hit] = rows(out, check="empty-column").to_dict("records")
    assert hit["column"] == "Amount" and "no values" in hit["detail"]


def test_check_data_finds_a_repeated_key(template, tmp_path):
    d = data(tmp_path, "Amount,Region,order_id\n1,East,o7\n2,West,o7\n3,West,o8\n")
    out = check_data(template, d, suggest_mapping(template, d))
    [hit] = rows(out, check="duplicate-key").to_dict("records")
    assert hit["column"] == "order_id" and hit["severity"] == "info" and "2 of 3" in hit["detail"]


def test_a_repeat_beyond_the_sample_is_found_only_by_deep(template, tmp_path):
    lines = ["Amount,Region,order_id"] + [f"1,East,o{i}" for i in range(2500)] + ["1,East,o3"]
    d = data(tmp_path, "\n".join(lines) + "\n")
    mapping = suggest_mapping(template, d)
    assert rows(check_data(template, d, mapping), check="duplicate-key").empty
    [hit] = rows(check_data(template, d, mapping, deep=True), check="duplicate-key").to_dict("records")
    assert "in all 2501 rows" in hit["detail"]


def test_a_header_with_trailing_space_survives_a_mapping_file(template, tmp_path):
    """load_mapping trims what a person typed; the data's own column name must still be found."""
    from py_tbparse import apply_template, load_mapping

    d = data(tmp_path, "Amount,Region ,order_id,Notes\n1,East,o1,x\n")
    assert "Region " in d.names()
    path = tmp_path / "map.csv"
    suggest_mapping(template, d).to_csv(path, index=False)
    mapping = load_mapping(str(path))
    assert d.column("Region") == "Region " and d.column("Amount") == "Amount" and d.column("nope") == "nope"
    assert check_data(template, d, mapping).empty and explain(template, d, mapping).empty
    out = apply_template(template, d, mapping=mapping, output_path=str(tmp_path / "o.twbx"))
    assert out.endswith("o.twbx")


def test_check_data_is_quiet_about_clean_data(template, tmp_path):
    d = data(tmp_path, "Amount,Region,order_id\n1,East,o1\n2,West,o2\n")
    assert check_data(template, d, suggest_mapping(template, d)).empty


def test_check_data_cannot_read_values_of_a_tableau_data_source(template, tmp_path):
    d = data(tmp_path, "Amount,order_id\n1,o1\n")
    d.kind = "tableau"                                            # no values to read; the grain check still runs
    out = check_data(template, d, suggest_mapping(template, d))
    assert set(out["check"]) == {"dimension-missing"}
    assert isinstance(out, pd.DataFrame)
