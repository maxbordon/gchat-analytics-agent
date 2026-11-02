from dataclasses import replace

import pytest

from app.agent_client import AgentError, GeminiAgentClient, MockAgentClient
from app.config import Settings
from app.conversations import InMemoryConversationStore


class FakeResponse:
    def __init__(self, status, body=None):
        self.status_code = status
        self._body = body or []
        self.text = str(body)

    def json(self):
        return self._body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)


class FakeHttp:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def post(self, url, headers, json, timeout):
        self.calls.append((url, json))
        return self.responses.pop(0)


FINAL = [{"systemMessage": {"text": {"textType": "FINAL_RESPONSE", "parts": ["42"]}}}]


@pytest.fixture
def settings(profile):
    return replace(Settings(), agent_mode="gemini", data_agent_project="proj",
                   data_agent_id="agent", profile=profile)


def make_client(settings, responses):
    http = FakeHttp(responses)
    store = InMemoryConversationStore(ttl_seconds=60)
    client = GeminiAgentClient(settings, store, token_provider=lambda: "tok", http=http)
    return client, http, store


def test_first_question_creates_conversation_then_chats(settings):
    client, http, _ = make_client(settings, [FakeResponse(200), FakeResponse(200, FINAL)])
    assert client.ask("q", "spaces/A").text == "42"
    assert "/conversations?conversationId=" in http.calls[0][0]
    assert http.calls[1][0].endswith(":chat")
    assert "credentials" not in http.calls[1][1]  # BigQuery: no Looker creds


def test_follow_up_reuses_conversation(settings):
    client, http, _ = make_client(settings, [FakeResponse(200), FakeResponse(200, FINAL), FakeResponse(200, FINAL)])
    client.ask("q1", "spaces/A")
    client.ask("q2", "spaces/A")
    assert len(http.calls) == 3  # only one create
    conv1 = http.calls[1][1]["conversationReference"]["conversation"]
    conv2 = http.calls[2][1]["conversationReference"]["conversation"]
    assert conv1 == conv2


def test_409_on_create_is_tolerated(settings):
    client, _, _ = make_client(settings, [FakeResponse(409), FakeResponse(200, FINAL)])
    assert client.ask("q", "spaces/A").text == "42"


def test_404_forgets_conversation(settings):
    client, _, store = make_client(settings, [FakeResponse(200), FakeResponse(404)])
    with pytest.raises(AgentError):
        client.ask("q", "spaces/A")
    assert store.get_or_create("spaces/A").is_new


def test_failed_create_forgets_conversation(settings):
    client, _, store = make_client(settings, [FakeResponse(500)])
    with pytest.raises(AgentError):
        client.ask("q", "spaces/A")
    assert store.get_or_create("spaces/A").is_new


def test_looker_credentials_are_sent_when_configured(settings):
    s = replace(settings, looker_client_id="id", looker_client_secret="secret")
    client, http, _ = make_client(s, [FakeResponse(200), FakeResponse(200, FINAL)])
    client.ask("q", "spaces/A")
    assert http.calls[1][1]["credentials"]["oauth"]["secret"]["clientId"] == "id"


def test_mock_client_answers_from_sample_data():
    mock = MockAgentClient()
    shrink = mock.ask("Which stores have the worst shrinkage?", "s")
    assert shrink.table and len(shrink.table.rows) == 5 and shrink.chart_spec
    ebit = mock.ask("EBIT margin by region", "s")
    assert ebit.table and ebit.table.columns[0] == "Region"
    assert not mock.ask("hello", "s").is_rich
