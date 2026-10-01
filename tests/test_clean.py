from twbparser_py._clean import bracket_tokens, clean_field, clean_table, strip_brackets


def test_bracket_tokens_qualified_name():
    assert bracket_tokens("[Orders].[Customer ID]") == ["[Orders]", "[Customer ID]"]


def test_bracket_tokens_keeps_nested_calc_whole():
    # The old regex stopped at the first "]" and returned "[LOWER([x]".
    assert bracket_tokens("[LOWER([x])]") == ["[LOWER([x])]"]
    assert bracket_tokens("[IFNULL([a],[b])].[T]") == ["[IFNULL([a],[b])]", "[T]"]


def test_bracket_tokens_escaped_close_bracket():
    assert bracket_tokens("[Sales]]Q1].[Orders]") == ["[Sales]]Q1]", "[Orders]"]
    assert bracket_tokens("[[x]]") == ["[[x]]"]


def test_bracket_tokens_empty_and_unclosed():
    assert bracket_tokens(None) == []
    assert bracket_tokens("no brackets") == []
    assert bracket_tokens("[open") == []


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
