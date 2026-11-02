from app.response_parser import build_table, format_value, parse_agent_response, strip_label_prefix

API_RESPONSE = [
    {"systemMessage": {"text": {"textType": "THOUGHT", "parts": ["thinking..."]}}},
    {"systemMessage": {"schema": {"result": {"datasources": [{"schema": {"fields": [
        {"name": "stores.store_name", "displayName": "stores Store Name"},
        {"name": "inv.rate", "displayName": "inventory_counts Shrink Rate"},
    ]}}]}}}},
    {"systemMessage": {"data": {"result": {"data": [
        {"stores.store_name": "Oak River", "inv.rate": 0.0412},
        {"stores.store_name": None, "inv.rate": None},
        {"stores.store_name": "Pine Lake", "inv.rate": 0.031},
    ]}}}},
    {"systemMessage": {"chart": {"result": {"vegaConfig": {"mark": "bar"}}}}},
    {"systemMessage": {"text": {"textType": "FINAL_RESPONSE", "parts": ["**Oak River** is worst."]}}},
]
PREFIXES = ("inventory_counts ", "stores ")


def test_parses_text_table_and_chart():
    answer = parse_agent_response(API_RESPONSE, PREFIXES)
    assert answer.text == "**Oak River** is worst."
    assert answer.table.columns == ["Store Name", "Shrink Rate"]
    assert answer.table.rows == [["Oak River", "0.04"], ["Pine Lake", "0.03"]]  # empty row dropped
    assert answer.chart_spec == {"mark": "bar"}
    assert answer.is_rich


def test_accepts_dict_wrapper():
    answer = parse_agent_response({"messages": API_RESPONSE}, PREFIXES)
    assert answer.text.startswith("**Oak River**")


def test_missing_final_response_uses_fallback():
    answer = parse_agent_response([], fallback_text="fallback")
    assert answer.text == "fallback" and not answer.is_rich


def test_format_value():
    assert format_value(None) == ""
    assert format_value(True) == "Yes"
    assert format_value(1234567) == "1,234,567"
    assert format_value(2.0) == "2"
    assert format_value(1234.567) == "1,234.57"
    assert format_value("x") == "x"


def test_longest_prefix_wins():
    prefixes = ("sales_daily ", "sales ")
    assert strip_label_prefix("sales_daily Revenue", prefixes) == "Revenue"
    assert strip_label_prefix("sales Units", prefixes) == "Units"
    assert strip_label_prefix("Other", prefixes) == "Other"


def test_build_table_handles_ragged_rows():
    table = build_table([{"a": 1}, {"a": 2, "b": 3}], {})
    assert table.columns == ["a", "b"]
    assert table.rows == [["1", ""], ["2", "3"]]
