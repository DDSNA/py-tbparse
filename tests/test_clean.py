from twbparser_py._clean import clean_field, clean_table, strip_brackets


def test_clean_table_strips_prefix_brackets_and_hex_suffix():
    assert clean_table("[Extract].[Orders_ABCDEF0123456789ABCDEF0123456789]") == "Orders"


def test_clean_table_plain():
    assert clean_table("[Orders]") == "Orders"


def test_clean_table_none():
    assert clean_table(None) is None


def test_clean_field_takes_last_dot_segment():
    assert clean_field("[Orders].[CustomerID]") == "CustomerID"


def test_clean_field_unwraps_derivation_wrapper():
    assert clean_field("none:Category:nk") == "Category"
    assert clean_field("clct:Geometry:ok") == "Geometry"


def test_clean_field_plain():
    assert clean_field("CustomerID") == "CustomerID"


def test_strip_brackets():
    assert strip_brackets("[Calculation_123]") == "Calculation_123"
    assert strip_brackets(None) is None
