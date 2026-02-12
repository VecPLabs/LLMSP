"""Tests for LLMSP council deliberation engine."""

from typing import Optional

from llmsp.clerk import Clerk
from llmsp.council import AgentAdapter, Council, CouncilPhase
from llmsp.event_store import EventStore
from llmsp.models import (
    ClaimBlock,
    ContentBlock,
    EventType,
    SignedEvent,
    TextBlock,
)
from llmsp.principal import AgentPrincipal, PrincipalRegistry
from llmsp.router import ContextRouter


# ---------------------------------------------------------------------------
# Stub adapter for testing (no real LLM calls)
# ---------------------------------------------------------------------------


class StubAdapter:
    """Deterministic adapter that returns fixed responses for testing."""

    def __init__(self, response_text: str, will_object: bool = False):
        self._response_text = response_text
        self._will_object = will_object

    def generate(
        self,
        agent: AgentPrincipal,
        query: str,
        context: list[SignedEvent],
    ) -> list[ContentBlock]:
        return [
            TextBlock(content=f"[{agent.name}] {self._response_text}"),
            ClaimBlock(claim=f"{agent.name}'s claim about: {query}", confidence=0.8),
        ]

    def review(
        self,
        agent: AgentPrincipal,
        query: str,
        proposal: SignedEvent,
        context: list[SignedEvent],
    ) -> Optional[list[ContentBlock]]:
        if self._will_object:
            return [TextBlock(content=f"[{agent.name}] objects to {proposal.author_id}")]
        return None


def _setup_council(agent_configs: list[tuple[str, str, str, bool]]):
    """Helper to set up a council with stub agents.

    agent_configs: list of (name, role, response_text, will_object)
    """
    store = EventStore()
    registry = PrincipalRegistry()
    router = ContextRouter(store)
    clerk_principal = AgentPrincipal("Clerk", "clerk")
    clerk = Clerk(clerk_principal)
    registry.register(clerk_principal)

    council = Council(
        event_store=store,
        registry=registry,
        router=router,
        clerk=clerk,
    )

    agents = []
    for name, role, response, will_object in agent_configs:
        agent = AgentPrincipal(name, role)
        adapter = StubAdapter(response, will_object=will_object)
        council.register_agent(agent, adapter)
        agents.append(agent)

    return council, store, agents


def test_council_basic_deliberation():
    council, store, agents = _setup_council([
        ("Alice", "dev", "I suggest using Python", False),
        ("Bob", "security", "Security looks good", False),
    ])

    session = council.deliberate("What language should we use?", "ch1")
    assert session.phase == CouncilPhase.COMPLETE
    assert len(session.responses) == 2
    assert len(session.objections) == 0
    assert session.synthesis is not None
    assert session.completed_at is not None


def test_council_with_objections():
    council, store, agents = _setup_council([
        ("Alice", "dev", "Use HTTP", False),
        ("Bob", "security", "Use HTTPS", True),  # Bob will object
    ])

    session = council.deliberate("How should we handle connections?", "ch1")
    assert session.phase == CouncilPhase.COMPLETE
    assert len(session.objections) > 0


def test_council_records_to_event_store():
    council, store, agents = _setup_council([
        ("Alice", "dev", "response A", False),
        ("Bob", "sec", "response B", False),
    ])

    session = council.deliberate("test query", "ch1")

    # Should have: council_start + 2 responses + synthesis + council_end = 5 events min
    assert store.count("ch1") >= 5


def test_council_session_tracking():
    council, store, agents = _setup_council([
        ("Alice", "dev", "test", False),
    ])

    session = council.deliberate("query", "ch1")
    retrieved = council.get_session(session.session_id)
    assert retrieved is not None
    assert retrieved.session_id == session.session_id


def test_council_three_agents():
    council, store, agents = _setup_council([
        ("Alice", "dev", "Python is great", False),
        ("Bob", "security", "Security first", False),
        ("Carol", "architect", "Microservices", False),
    ])

    session = council.deliberate("Design the system", "ch1")
    assert len(session.participants) == 3
    assert len(session.responses) == 3
    assert session.synthesis is not None
    assert len(session.synthesis.participating_agents) == 3


def test_council_synthesis_has_source_events():
    council, store, agents = _setup_council([
        ("Alice", "dev", "my thoughts", False),
        ("Bob", "sec", "my perspective", False),
    ])

    session = council.deliberate("discuss", "ch1")
    assert len(session.synthesis.source_event_ids) == 2
