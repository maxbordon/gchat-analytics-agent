"""Clients that turn a question into an AgentAnswer.

* GeminiAgentClient -> Gemini Data Analytics (Conversational Analytics) API.
* MockAgentClient   -> answers from the synthetic CSVs in data/sample, so the
                       whole bot can be run and demoed with no cloud account.
"""
from __future__ import annotations

import csv
import logging
from collections import defaultdict
from pathlib import Path
from typing import Callable, Protocol

import requests

from .config import Settings
from .conversations import ConversationStore
from .response_parser import AgentAnswer, Table, format_value, parse_agent_response

logger = logging.getLogger(__name__)

CLOUD_PLATFORM_SCOPE = "https://www.googleapis.com/auth/cloud-platform"


class AgentClient(Protocol):
    def ask(self, question: str, space: str) -> AgentAnswer: ...


def default_token_provider() -> str:
    """Access token for the runtime service account (Application Default Credentials)."""
    import google.auth
    import google.auth.transport.requests

    credentials, _ = google.auth.default(scopes=[CLOUD_PLATFORM_SCOPE])
    credentials.refresh(google.auth.transport.requests.Request())
    return credentials.token


class AgentError(RuntimeError):
    pass


class GeminiAgentClient:
    def __init__(
        self,
        settings: Settings,
        conversations: ConversationStore,
        token_provider: Callable[[], str] = default_token_provider,
        http: requests.Session | None = None,
    ):
        self.s = settings
        self.conversations = conversations
        self._token = token_provider
        self._http = http or requests.Session()

        host = (
            "geminidataanalytics.googleapis.com"
            if settings.data_agent_location == "global"
            else f"{settings.data_agent_location}-geminidataanalytics.googleapis.com"
        )
        self._parent = f"projects/{settings.data_agent_project}/locations/{settings.data_agent_location}"
        self._base = f"https://{host}/{settings.api_version}/{self._parent}"
        self.agent_resource = f"{self._parent}/dataAgents/{settings.data_agent_id}"

    # -- public -----------------------------------------------------------
    def ask(self, question: str, space: str) -> AgentAnswer:
        token = self._token()
        handle = self.conversations.get_or_create(space)

        if handle.is_new:
            try:
                self._create_conversation(handle.conversation_id, token)
            except Exception:
                logger.exception("Could not create conversation for %s", space)
                self.conversations.forget(space)  # retry with a fresh id next time
                raise AgentError("could not start a conversation with the agent")

        response = self._post(
            f"{self._base}:chat",
            token,
            self._chat_body(question, handle.conversation_id),
            timeout=self.s.agent_timeout_seconds,
        )
        if response.status_code != 200:
            logger.error("Agent returned %s: %s", response.status_code, response.text[:500])
            if response.status_code == 404:
                self.conversations.forget(space)  # conversation vanished remotely
            raise AgentError(f"agent returned HTTP {response.status_code}")

        return parse_agent_response(response.json(), self.s.profile.label_prefixes)

    # -- internals ----------------------------------------------------------
    def _chat_body(self, question: str, conversation_id: str) -> dict:
        body: dict = {
            "project": f"projects/{self.s.data_agent_project}",
            "messages": [{"userMessage": {"text": question}}],
            "conversationReference": {
                "conversation": f"{self._parent}/conversations/{conversation_id}",
                "dataAgentContext": {"dataAgent": self.agent_resource},
            },
        }
        # Looker data sources need their own OAuth client; BigQuery uses the SA.
        if self.s.looker_client_id and self.s.looker_client_secret:
            body["credentials"] = {
                "oauth": {
                    "secret": {
                        "clientId": self.s.looker_client_id,
                        "clientSecret": self.s.looker_client_secret,
                    }
                }
            }
        return body

    def _create_conversation(self, conversation_id: str, token: str) -> None:
        response = self._post(
            f"{self._base}/conversations?conversationId={conversation_id}",
            token,
            {"agents": [self.agent_resource]},
            timeout=30,
        )
        if response.status_code == 409:  # already exists -> reuse it
            return
        if response.status_code >= 400:
            logger.error("Create conversation failed %s: %s", response.status_code, response.text[:500])
            response.raise_for_status()

    def _post(self, url: str, token: str, body: dict, timeout: int):
        return self._http.post(
            url,
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json=body,
            timeout=timeout,
        )


# ---------------------------------------------------------------------------
# Mock client
# ---------------------------------------------------------------------------
SAMPLE_DIR = Path(__file__).resolve().parent.parent / "data" / "sample"


def _read_csv(name: str, data_dir: Path) -> list[dict]:
    path = data_dir / name
    if not path.exists():
        return []
    with open(path, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def _bar_chart(rows: list[dict], x: str, y: str, title: str) -> dict:
    return {
        "$schema": "https://vega.github.io/schema/vega-lite/v5.json",
        "title": title,
        "data": {"values": rows},
        "mark": "bar",
        "encoding": {
            "x": {"field": x, "type": "nominal", "sort": "-y"},
            "y": {"field": y, "type": "quantitative"},
        },
        "width": 400,
        "height": 250,
    }


class MockAgentClient:
    """Keyword-routed answers computed from the synthetic dataset."""

    def __init__(self, data_dir: Path = SAMPLE_DIR):
        self.data_dir = data_dir

    def ask(self, question: str, space: str) -> AgentAnswer:
        q = question.lower()
        if any(w in q for w in ("shrink", "loss", "merma")):
            return self._worst_shrink_stores()
        if any(w in q for w in ("ebit", "profit", "margin", "margen")):
            return self._ebit_by_region()
        return AgentAnswer(
            text=(
                "*Mock mode* — try asking:\n"
                "• Which 5 stores have the highest shrinkage rate?\n"
                "• What's the EBIT margin by region?"
            )
        )

    def _worst_shrink_stores(self) -> AgentAnswer:
        counts = _read_csv("inventory_counts.csv", self.data_dir)
        stores = {s["store_id"]: s for s in _read_csv("stores.csv", self.data_dir)}
        if not counts:
            return AgentAnswer(text="No sample data found. Run `python data/generate_data.py` first.")

        shrink = defaultdict(float)
        expected = defaultdict(float)
        for row in counts:
            shrink[row["store_id"]] += float(row["shrink_value"])
            expected[row["store_id"]] += float(row["expected_value"])

        ranked = sorted(shrink, key=lambda sid: shrink[sid] / expected[sid], reverse=True)[:5]
        chart_rows, table_rows = [], []
        for sid in ranked:
            rate = 100 * shrink[sid] / expected[sid]
            name = stores.get(sid, {}).get("store_name", sid)
            chart_rows.append({"store": name, "shrink_rate_pct": round(rate, 2)})
            table_rows.append([name, stores.get(sid, {}).get("region", ""), f"{rate:.2f}%", format_value(round(shrink[sid], 2))])

        top = chart_rows[0]
        return AgentAnswer(
            text=f"**{top['store']}** has the highest shrinkage rate ({top['shrink_rate_pct']}%). Top 5 below.",
            table=Table(columns=["Store", "Region", "Shrink rate", "Shrink value"], rows=table_rows),
            chart_spec=_bar_chart(chart_rows, "store", "shrink_rate_pct", "Shrinkage rate by store (%)"),
        )

    def _ebit_by_region(self) -> AgentAnswer:
        pnl = _read_csv("pnl_monthly.csv", self.data_dir)
        stores = {s["store_id"]: s for s in _read_csv("stores.csv", self.data_dir)}
        if not pnl:
            return AgentAnswer(text="No sample data found. Run `python data/generate_data.py` first.")

        revenue = defaultdict(float)
        ebit = defaultdict(float)
        for row in pnl:
            region = stores.get(row["store_id"], {}).get("region", "Unknown")
            revenue[region] += float(row["revenue"])
            ebit[region] += float(row["ebit"])

        regions = sorted(revenue, key=lambda r: ebit[r] / revenue[r], reverse=True)
        chart_rows = [{"region": r, "ebit_margin_pct": round(100 * ebit[r] / revenue[r], 2)} for r in regions]
        table_rows = [
            [r, format_value(round(revenue[r], 2)), format_value(round(ebit[r], 2)), f"{100 * ebit[r] / revenue[r]:.2f}%"]
            for r in regions
        ]
        best, worst = chart_rows[0], chart_rows[-1]
        return AgentAnswer(
            text=(
                f"Best EBIT margin: **{best['region']}** ({best['ebit_margin_pct']}%). "
                f"Lowest: **{worst['region']}** ({worst['ebit_margin_pct']}%)."
            ),
            table=Table(columns=["Region", "Revenue", "EBIT", "EBIT margin"], rows=table_rows),
            chart_spec=_bar_chart(chart_rows, "region", "ebit_margin_pct", "EBIT margin by region (%)"),
        )
