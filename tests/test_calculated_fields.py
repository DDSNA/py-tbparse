from twbparser_py import extract_calculated_fields, extract_raw_fields


def test_extract_calculated_fields(wenjie_xml):
    calcs = extract_calculated_fields(wenjie_xml)
    assert len(calcs) == 1
    row = calcs.iloc[0]
    assert row["tableau_internal_name"] == "[Calculation_2139209847776120832]"
    assert "ISNULL" in row["formula"]
    assert row["is_table_calc"] == False  # noqa: E712


def test_extract_raw_fields_excludes_calc_and_params(wenjie_xml):
    raw = extract_raw_fields(wenjie_xml)
    assert not raw.empty
    assert (raw["is_parameter"] == False).all()  # noqa: E712
    # the calculated field's internal name must not appear among raw fields
    assert "Calculation_2139209847776120832" not in raw["tableau_internal_name"].apply(
        lambda x: (x or "").strip("[]")
    ).values
