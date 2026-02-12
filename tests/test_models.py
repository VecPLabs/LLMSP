"""Tests for LLMSP core data models."""

from llmsp.models import (
    BlockType,
    ClaimBlock,
    CodeBlock,
    DecisionBlock,
    EventType,
    SignedEvent,
    TaskBlock,
    TextBlock,
)


def test_text_block():
    b = TextBlock(content="hello world")
    assert b.block_type == BlockType.TEXT
    assert b.content == "hello world"


def test_claim_block():
    b = ClaimBlock(claim="The sky is blue", confidence=0.95, evidence=["observation"])
    assert b.block_type == BlockType.CLAIM
    assert b.confidence == 0.95
    assert len(b.evidence) == 1


def test_code_block():
    b = CodeBlock(language="python", source="print('hi')", description="greeting")
    assert b.block_type == BlockType.CODE


def test_task_block():
    b = TaskBlock(task="implement feature X", assignee="pr_alice_dev")
    assert b.status == "proposed"


def test_decision_block():
    b = DecisionBlock(decision="Use Ed25519", rationale="Faster than RSA", dissenters=["pr_bob_security"])
    assert b.block_type == BlockType.DECISION
    assert len(b.dissenters) == 1


def test_signed_event_creation():
    event = SignedEvent(
        channel_id="test-channel",
        author_id="pr_alice_dev",
        event_type=EventType.MESSAGE,
        blocks=[TextBlock(content="test message")],
    )
    assert event.event_id.startswith("evt_")
    assert event.timestamp > 0
    assert event.channel_id == "test-channel"
    assert event.signature_hex == ""


def test_signed_event_payload_deterministic():
    event = SignedEvent(
        event_id="evt_fixed",
        timestamp=1000.0,
        channel_id="ch",
        author_id="pr_test_role",
        event_type=EventType.MESSAGE,
        blocks=[TextBlock(content="deterministic")],
    )
    # Same event should produce same payload bytes
    assert event.payload_bytes() == event.payload_bytes()


def test_signed_event_content_hash():
    event = SignedEvent(
        event_id="evt_fixed",
        timestamp=1000.0,
        channel_id="ch",
        author_id="pr_test_role",
        event_type=EventType.MESSAGE,
        blocks=[TextBlock(content="hash me")],
    )
    h = event.content_hash()
    assert len(h) == 64  # SHA-256 hex
    assert h == event.content_hash()  # deterministic


def test_signed_event_payload_excludes_signature():
    event = SignedEvent(
        event_id="evt_fixed",
        timestamp=1000.0,
        channel_id="ch",
        author_id="pr_test_role",
        event_type=EventType.MESSAGE,
        blocks=[TextBlock(content="test")],
    )
    p1 = event.payload_bytes()
    signed = event.model_copy(update={"signature_hex": "deadbeef"})
    p2 = signed.payload_bytes()
    assert p1 == p2  # signature should not affect payload


def test_event_with_multiple_block_types():
    event = SignedEvent(
        channel_id="ch",
        author_id="pr_test_role",
        event_type=EventType.MESSAGE,
        blocks=[
            TextBlock(content="Here's my analysis"),
            ClaimBlock(claim="X is true", confidence=0.8),
            CodeBlock(language="python", source="x = 1"),
            TaskBlock(task="verify X"),
            DecisionBlock(decision="accept X", rationale="evidence supports it"),
        ],
    )
    assert len(event.blocks) == 5


def test_event_serialization_roundtrip():
    event = SignedEvent(
        channel_id="ch",
        author_id="pr_test_role",
        event_type=EventType.DECISION,
        blocks=[DecisionBlock(decision="go", rationale="because")],
    )
    json_str = event.model_dump_json()
    restored = SignedEvent.model_validate_json(json_str)
    assert restored.event_id == event.event_id
    assert restored.blocks[0].decision == "go"  # type: ignore[union-attr]
