"""Tests for LLMSP Clerk (non-generative synthesis)."""

from llmsp.clerk import Clerk
from llmsp.models import (
    ClaimBlock,
    DecisionBlock,
    EventType,
    SignedEvent,
    TaskBlock,
    TextBlock,
)
from llmsp.principal import AgentPrincipal


def _make_clerk() -> Clerk:
    return Clerk(AgentPrincipal("Clerk", "clerk"))


def test_synthesize_empty():
    clerk = _make_clerk()
    result = clerk.synthesize([], "ch1")
    assert result.channel_id == "ch1"
    assert len(result.summary_blocks) == 1  # fallback message
    assert result.participating_agents == []


def test_synthesize_messages_only():
    clerk = _make_clerk()
    p1 = AgentPrincipal("Alice", "dev")
    p2 = AgentPrincipal("Bob", "sec")

    events = [
        p1.create_event("ch1", EventType.MESSAGE, [TextBlock(content="I think X")]),
        p2.create_event("ch1", EventType.MESSAGE, [TextBlock(content="I agree with X")]),
    ]
    result = clerk.synthesize(events, "ch1")
    assert len(result.participating_agents) == 2
    assert len(result.source_event_ids) == 2


def test_synthesize_finds_agreements():
    clerk = _make_clerk()
    p1 = AgentPrincipal("Alice", "dev")
    p2 = AgentPrincipal("Bob", "sec")

    # Both agents make the same claim
    events = [
        p1.create_event("ch1", EventType.MESSAGE, [ClaimBlock(claim="Ed25519 is fast", confidence=0.9)]),
        p2.create_event("ch1", EventType.MESSAGE, [ClaimBlock(claim="Ed25519 is fast", confidence=0.85)]),
    ]
    result = clerk.synthesize(events, "ch1")
    assert len(result.agreements) == 1
    assert "ed25519 is fast" in result.agreements[0]


def test_synthesize_captures_decisions():
    clerk = _make_clerk()
    p = AgentPrincipal("Alice", "dev")

    events = [
        p.create_event(
            "ch1",
            EventType.DECISION,
            [DecisionBlock(decision="Use SQLite", rationale="Simple and reliable")],
        ),
    ]
    result = clerk.synthesize(events, "ch1")
    assert len(result.decisions) == 1
    assert result.decisions[0].decision == "Use SQLite"


def test_synthesize_captures_action_items():
    clerk = _make_clerk()
    p = AgentPrincipal("Alice", "dev")

    events = [
        p.create_event(
            "ch1",
            EventType.MESSAGE,
            [TaskBlock(task="implement event store", assignee="pr_bob_dev")],
        ),
    ]
    result = clerk.synthesize(events, "ch1")
    assert len(result.action_items) == 1
    assert result.action_items[0].assignee == "pr_bob_dev"


def test_synthesize_detects_objections():
    clerk = _make_clerk()
    p1 = AgentPrincipal("Alice", "dev")
    p2 = AgentPrincipal("Bob", "sec")

    proposal = p1.create_event("ch1", EventType.MESSAGE, [TextBlock(content="Let's use HTTP")])
    objection = p2.create_event(
        "ch1",
        EventType.OBJECTION,
        [TextBlock(content="HTTP is insecure, use HTTPS")],
        parent_event_id=proposal.event_id,
    )

    result = clerk.synthesize([proposal, objection], "ch1")
    assert len(result.disagreements) == 1
    assert p1.agent_id in result.disagreements[0].positions
    assert p2.agent_id in result.disagreements[0].positions


def test_emit_synthesis_event():
    clerk = _make_clerk()
    p = AgentPrincipal("Alice", "dev")

    events = [
        p.create_event(
            "ch1",
            EventType.MESSAGE,
            [ClaimBlock(claim="Test claim", confidence=0.9)],
        ),
    ]
    result = clerk.synthesize(events, "ch1")
    synthesis_event = clerk.emit_synthesis_event(result)

    assert synthesis_event.event_type == EventType.DECISION
    assert synthesis_event.channel_id == "ch1"
    assert synthesis_event.signature_hex != ""
