"""Tests for LLMSP event store."""

import pytest

from llmsp.event_store import EventStore
from llmsp.models import EventType, SignedEvent, TextBlock
from llmsp.principal import AgentPrincipal


def _make_event(channel: str = "ch1", author: str = "pr_test_dev", text: str = "hello") -> SignedEvent:
    p = AgentPrincipal("test", "dev")
    return p.create_event(
        channel_id=channel,
        event_type=EventType.MESSAGE,
        blocks=[TextBlock(content=text)],
    )


def test_append_and_get():
    with EventStore() as store:
        event = _make_event()
        store.append(event)
        retrieved = store.get(event.event_id)
        assert retrieved is not None
        assert retrieved.event_id == event.event_id


def test_append_duplicate_raises():
    with EventStore() as store:
        event = _make_event()
        store.append(event)
        with pytest.raises(ValueError, match="Duplicate"):
            store.append(event)


def test_get_channel():
    with EventStore() as store:
        for i in range(5):
            store.append(_make_event(channel="ch1", text=f"msg {i}"))
        store.append(_make_event(channel="ch2", text="other"))

        ch1_events = store.get_channel("ch1")
        assert len(ch1_events) == 5
        ch2_events = store.get_channel("ch2")
        assert len(ch2_events) == 1


def test_get_channel_with_limit():
    with EventStore() as store:
        for i in range(10):
            store.append(_make_event(text=f"msg {i}"))
        events = store.get_channel("ch1", limit=3)
        assert len(events) == 3


def test_get_by_author():
    with EventStore() as store:
        # Different principals produce different author_ids
        p1 = AgentPrincipal("Alice", "dev")
        p2 = AgentPrincipal("Bob", "sec")
        store.append(p1.create_event("ch", EventType.MESSAGE, [TextBlock(content="a")]))
        store.append(p2.create_event("ch", EventType.MESSAGE, [TextBlock(content="b")]))
        store.append(p1.create_event("ch", EventType.MESSAGE, [TextBlock(content="c")]))

        alice_events = store.get_by_author("pr_alice_dev")
        assert len(alice_events) == 2


def test_get_thread():
    with EventStore() as store:
        parent = _make_event(text="parent")
        store.append(parent)

        p = AgentPrincipal("reply", "dev")
        reply1 = p.create_event("ch1", EventType.MESSAGE, [TextBlock(content="reply 1")], parent_event_id=parent.event_id)
        reply2 = p.create_event("ch1", EventType.MESSAGE, [TextBlock(content="reply 2")], parent_event_id=parent.event_id)
        store.append(reply1)
        store.append(reply2)

        thread = store.get_thread(parent.event_id)
        assert len(thread) == 2


def test_count():
    with EventStore() as store:
        assert store.count() == 0
        store.append(_make_event())
        store.append(_make_event())
        assert store.count() == 2
        assert store.count("ch1") == 2
        assert store.count("nonexistent") == 0


def test_latest():
    with EventStore() as store:
        e1 = _make_event(text="first")
        e2 = _make_event(text="second")
        store.append(e1)
        store.append(e2)
        latest = store.latest("ch1")
        assert latest is not None
        assert latest.event_id == e2.event_id


def test_len():
    with EventStore() as store:
        assert len(store) == 0
        store.append(_make_event())
        assert len(store) == 1


def test_integrity_check_passes():
    with EventStore() as store:
        store.append(_make_event(text="integrity"))
        mismatches = store.verify_integrity()
        assert mismatches == []


def test_get_nonexistent():
    with EventStore() as store:
        assert store.get("evt_doesnotexist") is None


def test_latest_empty_channel():
    with EventStore() as store:
        assert store.latest("empty") is None
