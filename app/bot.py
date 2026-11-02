"""Event handling: decides what to answer and how to deliver it.

Kept separate from Flask so the logic can be tested without HTTP.
"""
from __future__ import annotations

import logging
import threading
from typing import Callable

from . import chat_formatter as fmt
from .agent_client import AgentClient
from .charts import ChartPublisher
from .chat_client import ChatPoster
from .config import AgentProfile
from .response_parser import AgentAnswer

logger = logging.getLogger(__name__)

GENERIC_ERROR = "I had a problem processing your question. Please try again in a few seconds."
WORKING_ON_IT = "Working on it, give me a moment…"

# Runs a callable in the background. Threads in production, inline in tests.
Runner = Callable[[Callable[[], None]], None]


def thread_runner(job: Callable[[], None]) -> None:
    threading.Thread(target=job, daemon=True).start()


class ChatBot:
    def __init__(
        self,
        profile: AgentProfile,
        agent: AgentClient,
        poster: ChatPoster,
        charts: ChartPublisher,
        runner: Runner = thread_runner,
    ):
        self.profile = profile
        self.agent = agent
        self.poster = poster
        self.charts = charts
        self.run_in_background = runner

    # -- entry point ------------------------------------------------------
    def handle_event(self, event: dict) -> dict:
        """Return the synchronous JSON response for a Chat event."""
        if "chat" in event:  # Workspace add-on format
            return self._handle_addon(event["chat"] or {})
        return self._handle_classic(event)

    # -- add-on format: reply now, answer asynchronously ---------------------
    def _handle_addon(self, chat: dict) -> dict:
        if "addedToSpacePayload" in chat:
            return fmt.addon_message(self.profile.welcome_message)
        if "messagePayload" in chat:
            payload = chat["messagePayload"]
            question = _question(payload.get("message", {}))
            space = payload.get("space", {}).get("name", "")
            if not question:
                return fmt.addon_message(self.profile.empty_question_message)
            logger.info("Question in %s (%d chars)", space, len(question))
            self.run_in_background(lambda: self.answer_async(question, space))
            return fmt.addon_message(WORKING_ON_IT)
        return {}  # removedFromSpace, appCommand, unknown -> no reply

    # -- classic format: synchronous answer ------------------------------
    def _handle_classic(self, event: dict) -> dict:
        kind = event.get("type")
        if kind == "ADDED_TO_SPACE":
            return {"text": self.profile.welcome_message}
        if kind != "MESSAGE":
            return {}
        question = _question(event.get("message", {}))
        if not question:
            return {"text": self.profile.empty_question_message}
        space = event.get("space", {}).get("name", "")
        answer = self.ask(question, space)
        # Always reply with the answer *text* (rich content needs the async path).
        return {"text": fmt.markdown_to_chat(answer.text)}

    # -- shared -----------------------------------------------------------
    def ask(self, question: str, space: str) -> AgentAnswer:
        try:
            return self.agent.ask(question, space)
        except Exception:
            logger.exception("Agent call failed")
            return AgentAnswer(text=GENERIC_ERROR)

    def build_reply(self, answer: AgentAnswer) -> dict:
        """Card when there's a table/chart, plain text otherwise (with fallback)."""
        if answer.is_rich:
            try:
                chart_url = self.charts.publish(answer.chart_spec) if answer.chart_spec else None
                return fmt.answer_card(answer, self.profile.bot_name, chart_url)
            except Exception:
                logger.exception("Building card failed; falling back to text")
        return {"text": fmt.markdown_to_chat(answer.text)}

    def answer_async(self, question: str, space: str) -> None:
        answer = self.ask(question, space)
        try:
            self.poster.post(space, self.build_reply(answer))
        except Exception:
            logger.exception("Could not post answer to %s", space)


def _question(message: dict) -> str:
    # argumentText excludes the @mention; fall back to the full text in DMs.
    return (message.get("argumentText") or message.get("text") or "").strip()
