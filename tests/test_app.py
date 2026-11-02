from dataclasses import replace

import pytest

from app.auth import ChatRequestAuthenticator
from app.bot import GENERIC_ERROR, WORKING_ON_IT, ChatBot
from app.chat_client import LoggingChatPoster
from app.config import Settings
from app.main import create_app
from app.response_parser import AgentAnswer, Table


class StubAgent:
    def __init__(self, answer=None, error=False):
        self.answer = answer or AgentAnswer(text="**42**")
        self.error = error

    def ask(self, question, space):
        if self.error:
            raise RuntimeError("boom")
        return self.answer


class StubCharts:
    def publish(self, spec):
        return "https://charts/x.png"


def inline_runner(job):
    job()


@pytest.fixture
def make_app(profile):
    def _make(agent=None, skip_auth=True, mode="mock", verifier=None):
        settings = replace(Settings(), agent_mode=mode, skip_auth=skip_auth,
                           chat_audience="aud", profile=profile)
        poster = LoggingChatPoster()
        bot = ChatBot(profile, agent or StubAgent(), poster, StubCharts(), runner=inline_runner)
        auth = ChatRequestAuthenticator("aud", settings.chat_issuer_email,
                                        verifier=verifier or (lambda t, a: {}))
        app = create_app(settings, bot=bot, authenticator=auth)
        return app.test_client(), poster
    return _make


def addon_event(text, space="spaces/A"):
    return {"chat": {"messagePayload": {"message": {"text": text}, "space": {"name": space}}}}


def test_health(make_app):
    client, _ = make_app()
    assert client.get("/").json["status"] == "ok"


def test_rejects_without_token_when_auth_enabled(make_app):
    client, _ = make_app(skip_auth=False)
    assert client.post("/", json=addon_event("hi")).status_code == 401


def test_skip_auth_is_ignored_outside_mock_mode(make_app):
    client, _ = make_app(skip_auth=True, mode="gemini")
    assert client.post("/", json=addon_event("hi")).status_code == 401


def test_accepts_valid_token(make_app):
    claims = {"aud": "aud", "email": "chat@system.gserviceaccount.com", "email_verified": True}
    client, _ = make_app(skip_auth=False, verifier=lambda t, a: claims)
    resp = client.post("/", json=addon_event("hi"), headers={"Authorization": "Bearer x"})
    assert resp.status_code == 200


def test_addon_message_replies_now_and_posts_answer_later(make_app):
    client, poster = make_app()
    resp = client.post("/", json=addon_event("how are sales?"))
    text = resp.json["hostAppDataAction"]["chatDataAction"]["createMessageAction"]["message"]["text"]
    assert text == WORKING_ON_IT
    assert poster.sent == [("spaces/A", {"text": "*42*"})]


def test_rich_answer_is_posted_as_card(make_app):
    agent = StubAgent(AgentAnswer(text="t", table=Table(["a"], [["1"]]), chart_spec={"mark": "bar"}))
    client, poster = make_app(agent=agent)
    client.post("/", json=addon_event("q"))
    card = poster.sent[0][1]["cardsV2"][0]["card"]
    assert card["sections"][-1]["widgets"][0]["image"]["imageUrl"] == "https://charts/x.png"


def test_agent_error_posts_friendly_message(make_app):
    client, poster = make_app(agent=StubAgent(error=True))
    client.post("/", json=addon_event("q"))
    assert poster.sent[0][1]["text"] == GENERIC_ERROR


def test_empty_question(make_app, profile):
    client, poster = make_app()
    resp = client.post("/", json=addon_event("   "))
    msg = resp.json["hostAppDataAction"]["chatDataAction"]["createMessageAction"]["message"]["text"]
    assert msg == profile.empty_question_message and not poster.sent


def test_added_to_space_sends_welcome(make_app, profile):
    client, _ = make_app()
    resp = client.post("/", json={"chat": {"addedToSpacePayload": {}}})
    msg = resp.json["hostAppDataAction"]["chatDataAction"]["createMessageAction"]["message"]["text"]
    assert msg == profile.welcome_message


def test_classic_format_returns_text_not_dict(make_app):
    # Regression: the classic path must send the answer *text*, not the whole answer object.
    client, _ = make_app()
    resp = client.post("/", json={"type": "MESSAGE", "message": {"text": "q"}, "space": {"name": "s"}})
    assert resp.json == {"text": "*42*"}


def test_non_json_body_is_ignored(make_app):
    client, _ = make_app()
    resp = client.post("/", data="not json", content_type="text/plain")
    assert resp.status_code == 200 and resp.json == {}


def test_dev_endpoint_with_real_mock_agent(profile):
    settings = replace(Settings(), agent_mode="mock", skip_auth=True, profile=profile)
    client = create_app(settings).test_client()
    resp = client.post("/dev/ask", json={"question": "worst shrinkage stores"})
    assert "cardsV2" in resp.json
