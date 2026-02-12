"""Tests for LLMSP agent memory layer."""

from llmsp.memory import (
    MemoryEntry,
    MemoryExtractor,
    MemoryStore,
    MemoryType,
    _make_memory_id,
)
from llmsp.models import ClaimBlock, DecisionBlock, EventType, TextBlock
from llmsp.principal import AgentPrincipal


# ---------------------------------------------------------------------------
# MemoryStore tests
# ---------------------------------------------------------------------------


def test_store_and_recall():
    ms = MemoryStore()
    entry = MemoryEntry(
        memory_id="mem_test_1",
        agent_id="pr_alice_dev",
        memory_type=MemoryType.FACT,
        content="Ed25519 is fast for signing",
        confidence=0.9,
        tags=["crypto"],
    )
    ms.store(entry)
    recalled = ms.recall("pr_alice_dev")
    assert len(recalled) == 1
    assert recalled[0].content == "Ed25519 is fast for signing"


def test_recall_by_type():
    ms = MemoryStore()
    ms.store(MemoryEntry(
        memory_id="mem_1", agent_id="pr_a_dev",
        memory_type=MemoryType.FACT, content="fact 1",
    ))
    ms.store(MemoryEntry(
        memory_id="mem_2", agent_id="pr_a_dev",
        memory_type=MemoryType.POSITION, content="position 1",
    ))
    ms.store(MemoryEntry(
        memory_id="mem_3", agent_id="pr_a_dev",
        memory_type=MemoryType.FACT, content="fact 2",
    ))

    facts = ms.recall("pr_a_dev", memory_type=MemoryType.FACT)
    assert len(facts) == 2
    positions = ms.recall("pr_a_dev", memory_type=MemoryType.POSITION)
    assert len(positions) == 1


def test_recall_updates_access_count():
    ms = MemoryStore()
    ms.store(MemoryEntry(
        memory_id="mem_1", agent_id="pr_a_dev",
        memory_type=MemoryType.FACT, content="test",
    ))
    # First recall
    ms.recall("pr_a_dev")
    # Second recall
    results = ms.recall("pr_a_dev")
    assert results[0].access_count >= 1


def test_recall_by_tags():
    ms = MemoryStore()
    ms.store(MemoryEntry(
        memory_id="mem_1", agent_id="pr_a_dev",
        memory_type=MemoryType.FACT, content="crypto fact",
        tags=["crypto", "signing"],
    ))
    ms.store(MemoryEntry(
        memory_id="mem_2", agent_id="pr_a_dev",
        memory_type=MemoryType.FACT, content="database fact",
        tags=["database", "sqlite"],
    ))

    crypto = ms.recall_by_tags("pr_a_dev", ["crypto"])
    assert len(crypto) == 1
    assert "crypto" in crypto[0].content


def test_min_confidence_filter():
    ms = MemoryStore()
    ms.store(MemoryEntry(
        memory_id="mem_1", agent_id="pr_a_dev",
        memory_type=MemoryType.FACT, content="high conf",
        confidence=0.9,
    ))
    ms.store(MemoryEntry(
        memory_id="mem_2", agent_id="pr_a_dev",
        memory_type=MemoryType.FACT, content="low conf",
        confidence=0.2,
    ))

    high = ms.recall("pr_a_dev", min_confidence=0.5)
    assert len(high) == 1
    assert high[0].content == "high conf"


def test_count():
    ms = MemoryStore()
    ms.store(MemoryEntry(
        memory_id="mem_1", agent_id="pr_a_dev",
        memory_type=MemoryType.FACT, content="test",
    ))
    ms.store(MemoryEntry(
        memory_id="mem_2", agent_id="pr_b_sec",
        memory_type=MemoryType.FACT, content="test",
    ))
    assert ms.count() == 2
    assert ms.count("pr_a_dev") == 1


def test_forget_low_confidence():
    ms = MemoryStore()
    ms.store(MemoryEntry(
        memory_id="mem_1", agent_id="pr_a_dev",
        memory_type=MemoryType.FACT, content="keep",
        confidence=0.9,
    ))
    ms.store(MemoryEntry(
        memory_id="mem_2", agent_id="pr_a_dev",
        memory_type=MemoryType.FACT, content="forget",
        confidence=0.05,
    ))
    ms.forget("pr_a_dev", min_confidence=0.1)
    assert ms.count("pr_a_dev") == 1


def test_persistence():
    import tempfile
    import os

    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "memory.db")

        ms1 = MemoryStore(db_path)
        ms1.store(MemoryEntry(
            memory_id="mem_1", agent_id="pr_a_dev",
            memory_type=MemoryType.FACT, content="persistent fact",
        ))
        ms1.close()

        ms2 = MemoryStore(db_path)
        recalled = ms2.recall("pr_a_dev")
        assert len(recalled) == 1
        assert recalled[0].content == "persistent fact"
        ms2.close()


# ---------------------------------------------------------------------------
# MemoryExtractor tests
# ---------------------------------------------------------------------------


def test_extract_positions_from_claims():
    ms = MemoryStore()
    extractor = MemoryExtractor(ms)

    p1 = AgentPrincipal("Alice", "dev")
    p2 = AgentPrincipal("Bob", "sec")

    responses = [
        p1.create_event("ch1", EventType.MESSAGE, [
            ClaimBlock(claim="Ed25519 is fast", confidence=0.9, evidence=["benchmarks"]),
        ]),
        p2.create_event("ch1", EventType.MESSAGE, [
            ClaimBlock(claim="RSA is more compatible", confidence=0.8),
        ]),
    ]

    memories = extractor.extract_from_session("session_1", responses, [])

    # Each agent should have their own position recorded
    assert p1.agent_id in memories
    assert p2.agent_id in memories
    positions_alice = [m for m in memories[p1.agent_id] if m.memory_type == MemoryType.POSITION]
    assert len(positions_alice) >= 1


def test_extract_facts_from_unchallenged_claims():
    ms = MemoryStore()
    extractor = MemoryExtractor(ms)

    p1 = AgentPrincipal("Alice", "dev")
    p2 = AgentPrincipal("Bob", "sec")

    responses = [
        p1.create_event("ch1", EventType.MESSAGE, [
            ClaimBlock(claim="Ed25519 is fast", confidence=0.9),
        ]),
        p2.create_event("ch1", EventType.MESSAGE, [
            TextBlock(content="I agree with the approach"),
        ]),
    ]

    memories = extractor.extract_from_session("session_1", responses, [])

    # Bob should learn Alice's unchallenged claim as a fact
    bob_facts = [m for m in memories.get(p2.agent_id, []) if m.memory_type == MemoryType.FACT]
    assert len(bob_facts) >= 1
    assert "Ed25519" in bob_facts[0].content


def test_extract_interactions_from_objections():
    ms = MemoryStore()
    extractor = MemoryExtractor(ms)

    p1 = AgentPrincipal("Alice", "dev")
    p2 = AgentPrincipal("Bob", "sec")

    response = p1.create_event("ch1", EventType.MESSAGE, [
        TextBlock(content="We should use plaintext storage"),
    ])

    objection = p2.create_event("ch1", EventType.OBJECTION, [
        TextBlock(content="Plaintext storage is a security risk"),
    ], parent_event_id=response.event_id)

    memories = extractor.extract_from_session("session_1", [response], [objection])

    # Bob should remember the disagreement
    bob_interactions = [m for m in memories.get(p2.agent_id, []) if m.memory_type == MemoryType.INTERACTION]
    assert len(bob_interactions) >= 1

    # Alice should remember being challenged
    alice_interactions = [m for m in memories.get(p1.agent_id, []) if m.memory_type == MemoryType.INTERACTION]
    assert len(alice_interactions) >= 1


def test_extract_skills():
    ms = MemoryStore()
    extractor = MemoryExtractor(ms)

    p1 = AgentPrincipal("Alice", "dev")
    responses = [
        p1.create_event("ch1", EventType.MESSAGE, [
            TextBlock(content="Here is my analysis of the cryptographic primitives"),
        ]),
    ]

    memories = extractor.extract_from_session("session_1", responses, [])
    skills = [m for m in memories.get(p1.agent_id, []) if m.memory_type == MemoryType.SKILL]
    assert len(skills) >= 1


def test_format_memory_context():
    ms = MemoryStore()
    extractor = MemoryExtractor(ms)

    ms.store(MemoryEntry(
        memory_id="mem_1", agent_id="pr_alice_dev",
        memory_type=MemoryType.FACT, content="Ed25519 is fast",
    ))
    ms.store(MemoryEntry(
        memory_id="mem_2", agent_id="pr_alice_dev",
        memory_type=MemoryType.POSITION, content="I prefer Ed25519 over RSA",
    ))

    context = extractor.format_memory_context("pr_alice_dev")
    assert "Memory" in context
    assert "Ed25519" in context
    assert "FACT" in context
    assert "POSITION" in context


def test_format_memory_context_empty():
    ms = MemoryStore()
    extractor = MemoryExtractor(ms)
    context = extractor.format_memory_context("pr_nobody_nothing")
    assert context == ""


def test_deterministic_memory_id():
    id1 = _make_memory_id("agent_a", "some content")
    id2 = _make_memory_id("agent_a", "some content")
    id3 = _make_memory_id("agent_b", "some content")
    assert id1 == id2  # Same agent + content = same ID
    assert id1 != id3  # Different agent = different ID
