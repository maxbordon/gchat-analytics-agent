"""Flask entry point (served by gunicorn on Cloud Run)."""
from __future__ import annotations

import logging
import os

from flask import Flask, jsonify, request

from .agent_client import GeminiAgentClient, MockAgentClient
from .auth import ChatRequestAuthenticator
from .bot import ChatBot
from .charts import GcsChartPublisher, LocalChartPublisher
from .chat_client import GoogleChatPoster, LoggingChatPoster
from .config import Settings
from .conversations import InMemoryConversationStore

logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))
logger = logging.getLogger(__name__)


def build_bot(settings: Settings) -> ChatBot:
    if settings.is_mock:
        return ChatBot(settings.profile, MockAgentClient(), LoggingChatPoster(), LocalChartPublisher())

    conversations = InMemoryConversationStore(
        ttl_seconds=settings.conversation_ttl_seconds,
        prefix=settings.profile.conversation_prefix,
    )
    return ChatBot(
        settings.profile,
        GeminiAgentClient(settings, conversations),
        GoogleChatPoster(settings.chat_app_sa_email),
        GcsChartPublisher(settings.charts_bucket, settings.chart_url_ttl_days),
    )


def create_app(
    settings: Settings | None = None,
    bot: ChatBot | None = None,
    authenticator: ChatRequestAuthenticator | None = None,
) -> Flask:
    settings = settings or Settings.from_env()
    for problem in settings.validate():
        logger.warning("Config: %s", problem)

    bot = bot or build_bot(settings)
    authenticator = authenticator or ChatRequestAuthenticator(
        settings.chat_audience, settings.chat_issuer_email
    )

    app = Flask(__name__)
    app.config["BOT"] = bot

    @app.get("/")
    def health():
        return jsonify(status="ok", bot=settings.profile.bot_name, mode=settings.agent_mode)

    @app.post("/")
    def chat_event():
        if not settings.auth_disabled:
            result = authenticator.check(request.headers.get("Authorization"))
            if not result.ok:
                return jsonify(error="unauthorized"), 401

        event = request.get_json(silent=True)
        if not isinstance(event, dict):
            logger.warning("Request without a JSON object body")
            return jsonify({}), 200

        return jsonify(bot.handle_event(event)), 200

    if settings.is_mock:
        @app.post("/dev/ask")
        def dev_ask():
            """Local-only helper: returns exactly what would be posted to Chat."""
            question = (request.get_json(silent=True) or {}).get("question", "")
            answer = bot.ask(question, "spaces/local-dev")
            return jsonify(bot.build_reply(answer))

    return app


if __name__ == "__main__":
    create_app().run(host="0.0.0.0", port=int(os.environ.get("PORT", "8080")))
