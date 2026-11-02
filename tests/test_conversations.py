from app.conversations import InMemoryConversationStore


class FakeClock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def test_same_space_reuses_conversation_within_ttl():
    clock = FakeClock()
    store = InMemoryConversationStore(ttl_seconds=60, prefix="t", clock=clock)
    first = store.get_or_create("spaces/A")
    clock.now += 30
    second = store.get_or_create("spaces/A")
    assert first.is_new and not second.is_new
    assert first.conversation_id == second.conversation_id
    assert first.conversation_id.startswith("t")


def test_idle_conversation_expires():
    clock = FakeClock()
    store = InMemoryConversationStore(ttl_seconds=60, clock=clock)
    first = store.get_or_create("spaces/A")
    clock.now += 61
    second = store.get_or_create("spaces/A")
    assert second.is_new and second.conversation_id != first.conversation_id


def test_activity_refreshes_ttl():
    clock = FakeClock()
    store = InMemoryConversationStore(ttl_seconds=60, clock=clock)
    first = store.get_or_create("spaces/A")
    for _ in range(3):
        clock.now += 50
        assert store.get_or_create("spaces/A").conversation_id == first.conversation_id


def test_spaces_are_isolated_and_forget_works():
    store = InMemoryConversationStore(ttl_seconds=60)
    a = store.get_or_create("spaces/A")
    b = store.get_or_create("spaces/B")
    assert a.conversation_id != b.conversation_id
    store.forget("spaces/A")
    assert store.get_or_create("spaces/A").is_new
