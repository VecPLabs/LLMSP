"""Tests for LLMSP async council deliberation."""

import asyncio
from typing import Optional

from llmsp.adapters.base import ApiResult, BaseAdapter
from llmsp.async_council import AsyncCouncil
from llmsp.clerk import Clerk
from llmsp.council import CouncilPhase
from llmsp.event_store import EventStore
from llmsp.models import ClaimBlock, ContentBlock, SignedEvent, TextBlock
from llmsp.principal import AgentPrincipal, PrincipalRegistry
from llmsp.router import ContextRouter


class StubAsyncAdapter(BaseAdapter):
    """Deterministic async adapter for testing."""

    def __init__(self, response_text: str, will_object: bool = False):
        super().__init__(model="stub", api_key="stub")
        self._response_text = response_text
        self._will_object = will_object

    async def _call_api(self, system_prompt: str, user_prompt: str) -> ApiResult:
        # Simulate some latency
        await asyncio.sleep(0.01)
        return ApiResult(text=self._response_text, input_tokens=100, output_tokens=50)

    async def generate(
        self,
        agent: AgentPrincipal,
        query: str,
        context: list[SignedEvent],
    ) -> list[ContentBlock]:
        await asyncio.sleep(0.01)
        return [
            TextBlock(content=f"[{agent.name}] {self._response_text}"),
            ClaimBlock(claim=f"{agent.name} says: {query}", confidence=0.8),
        ]

    async def review(
        self,
        agent: AgentPrincipal,
        query: str,
        proposal: SignedEvent,
        context: list[SignedEvent],
    ) -> Optional[list[ContentBlock]]:
        await asyncio.sleep(0.01)
        if self._will_object:
            return [TextBlock(content=f"[{agent.name}] objects")]
        return None


def _setup_async_council(configs: list[tuple[str, str, str, bool]]):
    store = EventStore()
    registry = PrincipalRegistry()
    router = ContextRouter(store)
    clerk_principal = AgentPrincipal("Clerk", "clerk")
    clerk = Clerk(clerk_principal)
    registry.register(clerk_principal)

    council = AsyncCouncil(
        event_store=store,
        registry=registry,
        router=router,
        clerk=clerk,
    )

    agents = []
    for name, role, response, will_object in configs:
        agent = AgentPrincipal(name, role)
        adapter = StubAsyncAdapter(response, will_object=will_object)
        council.register_agent(agent, adapter)
        agents.append(agent)

    return council, store, agents


def test_async_basic_deliberation():
    council, store, agents = _setup_async_council([
        ("Alice", "dev", "async response A", False),
        ("Bob", "sec", "async response B", False),
    ])

    session = asyncio.get_event_loop().run_until_complete(
        council.deliberate("test async", "ch1")
    )
    assert session.phase == CouncilPhase.COMPLETE
    assert len(session.responses) == 2
    assert len(session.objections) == 0
    assert session.synthesis is not None


def test_async_with_objections():
    council, store, agents = _setup_async_council([
        ("Alice", "dev", "proposal", False),
        ("Bob", "sec", "objection", True),
    ])

    session = asyncio.get_event_loop().run_until_complete(
        council.deliberate("controversial topic", "ch1")
    )
    assert session.phase == CouncilPhase.COMPLETE
    assert len(session.objections) > 0


def test_async_three_agents_concurrent():
    council, store, agents = _setup_async_council([
        ("Alice", "dev", "code perspective", False),
        ("Bob", "sec", "security perspective", False),
        ("Carol", "arch", "architecture perspective", False),
    ])

    session = asyncio.get_event_loop().run_until_complete(
        council.deliberate("design the system", "ch1")
    )
    assert len(session.responses) == 3
    assert len(session.participants) == 3
    assert session.synthesis is not None


def test_async_records_to_store():
    council, store, agents = _setup_async_council([
        ("Alice", "dev", "response", False),
        ("Bob", "sec", "response", False),
    ])

    asyncio.get_event_loop().run_until_complete(
        council.deliberate("test storage", "ch1")
    )

    # council_start + 2 responses + synthesis + council_end = 5 minimum
    assert store.count("ch1") >= 5


def test_async_session_tracking():
    council, store, agents = _setup_async_council([
        ("Alice", "dev", "track me", False),
    ])

    session = asyncio.get_event_loop().run_until_complete(
        council.deliberate("session test", "ch1")
    )
    retrieved = council.get_session(session.session_id)
    assert retrieved is not None
    assert retrieved.session_id == session.session_id


# ---------------------------------------------------------------------------
# Cost tracking integration
# ---------------------------------------------------------------------------


class CostTrackingAdapter(BaseAdapter):
    """Adapter that uses base generate() so _call_api → last_usage flows through."""

    def __init__(self):
        super().__init__(model="claude-sonnet-4-5-20250929", api_key="stub")

    async def _call_api(self, system_prompt: str, user_prompt: str) -> ApiResult:
        await asyncio.sleep(0.01)
        return ApiResult(
            text='[{"block_type": "text", "content": "tracked response"}]',
            input_tokens=500,
            output_tokens=200,
        )


def test_cost_tracker_records_during_deliberation():
    from llmsp.finops import CostTracker

    store = EventStore()
    registry = PrincipalRegistry()
    router = ContextRouter(store)
    clerk_principal = AgentPrincipal("Clerk", "clerk")
    clerk = Clerk(clerk_principal)
    registry.register(clerk_principal)

    tracker = CostTracker()
    council = AsyncCouncil(
        event_store=store,
        registry=registry,
        router=router,
        clerk=clerk,
        cost_tracker=tracker,
    )

    agent = AgentPrincipal("Alice", "dev")
    adapter = CostTrackingAdapter()
    council.register_agent(agent, adapter)

    asyncio.get_event_loop().run_until_complete(
        council.deliberate("test cost tracking", "ch1")
    )

    # Should have recorded at least one API call (generate)
    assert tracker.usage_count() >= 1
    assert tracker.total_tokens > 0
    assert tracker.total_cost > 0

    # Verify model and agent attribution
    by_model = tracker.cost_by_model()
    assert "claude-sonnet-4-5-20250929" in by_model

    by_agent = tracker.cost_by_agent()
    assert agent.agent_id in by_agent
