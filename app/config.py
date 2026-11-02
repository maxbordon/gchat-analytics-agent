"""Application settings.

Two sources, with a clear split of responsibilities:

* Environment variables -> infrastructure (project, bucket, credentials, mode).
* A YAML "agent profile" -> domain wording (bot name, welcome text, label
  prefixes). Switching the bot from finance to inventory is a config change,
  not a code change.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml

DEFAULT_PROFILE_PATH = Path(__file__).resolve().parent.parent / "config" / "agent.yaml"


@dataclass(frozen=True)
class AgentProfile:
    """Domain-specific wording and display rules for one bot."""

    bot_name: str
    welcome_message: str
    empty_question_message: str
    conversation_prefix: str = "conv"
    label_prefixes: tuple[str, ...] = ()

    @classmethod
    def from_yaml(cls, path: str | Path) -> "AgentProfile":
        with open(path, encoding="utf-8") as fh:
            raw = yaml.safe_load(fh) or {}
        prefixes = raw.get("label_prefixes") or []
        # Longest first, so "sales_daily " is stripped before "sales ".
        ordered = tuple(sorted((p for p in prefixes if p), key=len, reverse=True))
        return cls(
            bot_name=raw["bot_name"],
            welcome_message=raw["welcome_message"].strip(),
            empty_question_message=raw.get(
                "empty_question_message", "I didn't get a question. Ask me something!"
            ),
            conversation_prefix=raw.get("conversation_prefix", "conv"),
            label_prefixes=ordered,
        )


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    """Runtime configuration read from environment variables."""

    agent_mode: str = "mock"                 # "mock" or "gemini"
    skip_auth: bool = False                  # only honoured in mock mode
    chat_audience: str = ""
    chat_issuer_email: str = "chat@system.gserviceaccount.com"
    chat_app_sa_email: str = ""              # SA to impersonate when posting to Chat
    data_agent_project: str = ""
    data_agent_id: str = ""
    data_agent_location: str = "global"
    api_version: str = "v1beta"
    looker_client_id: str = ""               # optional: only for Looker data sources
    looker_client_secret: str = ""
    charts_bucket: str = ""
    chart_url_ttl_days: int = 5
    conversation_ttl_seconds: int = 30 * 60
    agent_timeout_seconds: int = 90
    profile: AgentProfile = field(default=None)  # type: ignore[assignment]

    @property
    def is_mock(self) -> bool:
        return self.agent_mode == "mock"

    @property
    def auth_disabled(self) -> bool:
        # Never allow skipping auth against the real agent.
        return self.is_mock and self.skip_auth

    @classmethod
    def from_env(cls) -> "Settings":
        profile_path = os.environ.get("AGENT_PROFILE", str(DEFAULT_PROFILE_PATH))
        mode = os.environ.get("AGENT_MODE", "mock").strip().lower()
        if mode not in {"mock", "gemini"}:
            raise ValueError(f"AGENT_MODE must be 'mock' or 'gemini', got {mode!r}")
        return cls(
            agent_mode=mode,
            skip_auth=_env_bool("SKIP_AUTH"),
            chat_audience=os.environ.get("GOOGLE_CHAT_AUDIENCE", ""),
            chat_issuer_email=os.environ.get(
                "GOOGLE_CHAT_ISSUER_EMAIL", "chat@system.gserviceaccount.com"
            ),
            chat_app_sa_email=os.environ.get("CHAT_APP_SA_EMAIL", ""),
            data_agent_project=os.environ.get("DATA_AGENT_PROJECT", ""),
            data_agent_id=os.environ.get("DATA_AGENT_ID", ""),
            data_agent_location=os.environ.get("DATA_AGENT_LOCATION", "global"),
            api_version=os.environ.get("DATA_ANALYTICS_API_VERSION", "v1beta"),
            looker_client_id=os.environ.get("LOOKER_CLIENT_ID", ""),
            looker_client_secret=os.environ.get("LOOKER_CLIENT_SECRET", ""),
            charts_bucket=os.environ.get("CHARTS_BUCKET", ""),
            chart_url_ttl_days=int(os.environ.get("CHART_URL_TTL_DAYS", "5")),
            conversation_ttl_seconds=int(os.environ.get("CONVERSATION_TTL_SECONDS", "1800")),
            agent_timeout_seconds=int(os.environ.get("AGENT_TIMEOUT_SECONDS", "90")),
            profile=AgentProfile.from_yaml(profile_path),
        )

    def validate(self) -> list[str]:
        """Return human-readable problems; empty list means the config is usable."""
        problems = []
        if not self.is_mock:
            for name, value in [
                ("GOOGLE_CHAT_AUDIENCE", self.chat_audience),
                ("DATA_AGENT_PROJECT", self.data_agent_project),
                ("DATA_AGENT_ID", self.data_agent_id),
            ]:
                if not value:
                    problems.append(f"{name} is required when AGENT_MODE=gemini")
        if self.skip_auth and not self.is_mock:
            problems.append("SKIP_AUTH is ignored outside mock mode")
        return problems
