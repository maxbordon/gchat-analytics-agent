"""Posts asynchronous replies into a Google Chat space.

Chat expects a synchronous answer within ~30 s, while the analytics agent can
take longer. The bot replies "working on it" immediately and later posts the
real answer through the Chat REST API, authenticated as the Chat app.
"""
from __future__ import annotations

import logging
from typing import Protocol

import requests

logger = logging.getLogger(__name__)

CHAT_BOT_SCOPE = "https://www.googleapis.com/auth/chat.bot"


class ChatPoster(Protocol):
    def post(self, space: str, payload: dict) -> None: ...


class GoogleChatPoster:
    def __init__(self, app_service_account: str = "", http: requests.Session | None = None):
        # If set, impersonate this SA (the one registered as the Chat app).
        # Lets test/prod services post as the same app registered once.
        self.app_service_account = app_service_account
        self._http = http or requests.Session()

    def _credentials(self):
        import google.auth
        import google.auth.transport.requests
        from google.auth import impersonated_credentials

        source, _ = google.auth.default()
        own_email = getattr(source, "service_account_email", None)

        if not self.app_service_account or own_email == self.app_service_account:
            creds, _ = google.auth.default(scopes=[CHAT_BOT_SCOPE])
        else:
            creds = impersonated_credentials.Credentials(
                source_credentials=source,
                target_principal=self.app_service_account,
                target_scopes=[CHAT_BOT_SCOPE],
                lifetime=3600,
            )
        creds.refresh(google.auth.transport.requests.Request())
        return creds

    def post(self, space: str, payload: dict) -> None:
        creds = self._credentials()
        response = self._http.post(
            f"https://chat.googleapis.com/v1/{space}/messages",
            headers={"Authorization": f"Bearer {creds.token}", "Content-Type": "application/json"},
            json=payload,
            timeout=30,
        )
        if response.status_code >= 400:
            logger.error("Posting to Chat failed %s: %s", response.status_code, response.text[:500])
            response.raise_for_status()


class LoggingChatPoster:
    """Local/mock stand-in: records messages instead of calling Chat."""

    def __init__(self):
        self.sent: list[tuple[str, dict]] = []

    def post(self, space: str, payload: dict) -> None:
        self.sent.append((space, payload))
        logger.info("[mock chat] -> %s: %s", space, payload)
