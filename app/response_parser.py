"""Turns the Conversational Analytics API response into a simple structure.

The :chat endpoint returns a stream of system messages (thinking steps,
schema, data rows, charts, final text). We keep only what the bot shows:
the final answer, the last data table and the last chart spec.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class Table:
    columns: list[str]
    rows: list[list[str]]


@dataclass
class AgentAnswer:
    text: str
    table: Table | None = None
    chart_spec: dict | None = None
    extras: dict = field(default_factory=dict)

    @property
    def is_rich(self) -> bool:
        return self.table is not None or self.chart_spec is not None


def format_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, float) and not value.is_integer():
        return f"{value:,.2f}"
    if isinstance(value, (int, float)):
        return f"{int(value):,}"
    return str(value)


def strip_label_prefix(label: str, prefixes: tuple[str, ...]) -> str:
    """Remove the view prefix BI tools add to display names ("orders Revenue" -> "Revenue")."""
    for prefix in prefixes:  # expected longest-first
        if label.startswith(prefix):
            return label[len(prefix):]
    return label


def build_table(
    raw_rows: list[dict], labels: dict[str, str], prefixes: tuple[str, ...] = ()
) -> Table | None:
    if not raw_rows or not isinstance(raw_rows[0], dict):
        return None

    keys: list[str] = []
    for row in raw_rows:
        for key in row:
            if key not in keys:
                keys.append(key)

    rows = []
    for row in raw_rows:
        values = [row.get(k) for k in keys]
        if all(v is None or v == "" for v in values):
            continue
        rows.append([format_value(v) for v in values])
    if not rows:
        return None

    columns = [strip_label_prefix(labels.get(k, k), prefixes) for k in keys]
    return Table(columns=columns, rows=rows)


def _messages(payload: Any) -> list:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        return payload.get("messages", [payload])
    return []


def _result(section: Any) -> dict:
    if isinstance(section, dict) and isinstance(section.get("result"), dict):
        return section["result"]
    return {}


def parse_agent_response(
    payload: Any, label_prefixes: tuple[str, ...] = (), fallback_text: str = ""
) -> AgentAnswer:
    text = None
    last_rows = None
    chart = None
    labels: dict[str, str] = {}

    for message in _messages(payload):
        system = message.get("systemMessage") if isinstance(message, dict) else None
        if not isinstance(system, dict):
            continue

        text_block = system.get("text")
        if isinstance(text_block, dict) and text_block.get("textType") == "FINAL_RESPONSE":
            parts = [str(p) for p in text_block.get("parts", []) if p]
            if parts:
                text = "\n".join(parts)

        for source in _result(system.get("schema")).get("datasources") or []:
            for fld in (source.get("schema") or {}).get("fields") or []:
                if fld.get("name") and fld.get("displayName"):
                    labels[fld["name"]] = fld["displayName"]

        rows = _result(system.get("data")).get("data")
        if isinstance(rows, list) and rows:
            last_rows = rows

        spec = _result(system.get("chart")).get("vegaConfig")
        if isinstance(spec, dict):
            chart = spec

    if not text:
        logger.warning("No FINAL_RESPONSE found in agent response")
        text = fallback_text or "I got an answer but couldn't read it. Try rephrasing."

    table = build_table(last_rows, labels, label_prefixes) if last_rows else None
    return AgentAnswer(text=text, table=table, chart_spec=chart)
