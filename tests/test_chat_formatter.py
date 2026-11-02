from app.chat_formatter import MAX_TABLE_ROWS, addon_message, answer_card, markdown_to_chat, table_widgets
from app.response_parser import AgentAnswer, Table


def test_markdown_plain_message():
    md = "## Summary\n- **Oak** is worst\n* second"
    assert markdown_to_chat(md) == "*Summary*\n• *Oak* is worst\n• second"


def test_markdown_card_uses_html():
    assert markdown_to_chat("# Title\n**bold**", for_card=True) == "<b>Title</b><br><b>bold</b>"


def test_addon_message_shape():
    msg = addon_message("hi")
    assert msg["hostAppDataAction"]["chatDataAction"]["createMessageAction"]["message"]["text"] == "hi"


def test_table_is_truncated_with_note():
    table = Table(columns=["n"], rows=[[str(i)] for i in range(25)])
    widgets = table_widgets(table)
    assert len(widgets) == 1 + MAX_TABLE_ROWS + 1
    assert "Showing 10 of 25" in widgets[-1]["textParagraph"]["text"]


def test_card_contains_sections_and_clickable_chart():
    answer = AgentAnswer(text="hi", table=Table(["a"], [["1"]]), chart_spec={"mark": "bar"})
    card = answer_card(answer, "Bot", chart_url="https://img")
    sections = card["cardsV2"][0]["card"]["sections"]
    assert len(sections) == 3
    image = sections[2]["widgets"][0]["image"]
    assert image["onClick"]["openLink"]["url"] == "https://img"
