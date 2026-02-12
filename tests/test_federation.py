"""Tests for LLMSP multi-council federation."""

import asyncio
from typing import Optional

from llmsp.adapters.base import ApiResult, BaseAdapter
from llmsp.async_council import AsyncCouncil
from llmsp.clerk import Clerk
from llmsp.council import CouncilPhase
from llmsp.event_store import EventStore
from llmsp.federation import (
    DecompositionStrategy,
    FederationPlan,
    MetaCouncil,
    SessionGraph,
    SubProblem,
    decompose_by_keywords,
    decompose_explicit,
    decompose_sequential,
)
from llmsp.models import ClaimBlock, ContentBlock, EventType, SignedEvent, TextBlock
from llmsp.principal import AgentPrincipal, PrincipalRegistry
from llmsp.router import ContextRouter


class StubFederationAdapter(BaseAdapter):
    """Deterministic adapter for federation testing."""

    def __init__(self):
        super().__init__(model="stub", api_key="stub")

    async def _call_api(self, system_prompt: str, user_prompt: str) -> ApiResult:
        return ApiResult(text='[]', input_tokens=50, output_tokens=10)

    async def generate(
        self, agent: AgentPrincipal, query: str, context: list[SignedEvent],
    ) -> list[ContentBlock]:
        await asyncio.sleep(0.01)
        return [
            TextBlock(content=f"[{agent.name}] analyzing: {query[:50]}"),
            ClaimBlock(claim=f"{agent.name} perspective on query", confidence=0.8),
        ]

    async def review(
        self, agent: AgentPrincipal, query: str, proposal: SignedEvent, context: list[SignedEvent],
    ) -> Optional[list[ContentBlock]]:
        return None


def _setup_federation():
    store = EventStore()
    registry = PrincipalRegistry()
    router = ContextRouter(store)
    clerk_principal = AgentPrincipal("Clerk", "clerk")
    clerk = Clerk(clerk_principal)
    registry.register(clerk_principal)

    council = AsyncCouncil(
        event_store=store, registry=registry, router=router, clerk=clerk,
    )

    # Register agents
    for name, role in [("Alice", "dev"), ("Bob", "sec"), ("Carol", "arch")]:
        agent = AgentPrincipal(name, role)
        council.register_agent(agent, StubFederationAdapter())

    meta = MetaCouncil(council=council, event_store=store, clerk=clerk)
    return meta, store


# ---------------------------------------------------------------------------
# Decomposition tests
# ---------------------------------------------------------------------------


def test_decompose_by_keywords_multi_domain():
    subs = decompose_by_keywords(
        "Design the security architecture for database performance optimization"
    )
    assert len(subs) >= 2
    domains = {s.domain_hint for s in subs if s.domain_hint}
    assert "security" in domains or "architecture" in domains


def test_decompose_by_keywords_single_domain():
    subs = decompose_by_keywords("Fix the database schema migration")
    # Single domain shouldn't decompose
    assert len(subs) == 1


def test_decompose_by_keywords_no_match():
    subs = decompose_by_keywords("Hello world")
    assert len(subs) == 1
    assert subs[0].query == "Hello world"


def test_decompose_explicit():
    subs = decompose_explicit(["How fast is Ed25519?", "Is RSA more compatible?", "What about hybrid?"])
    assert len(subs) == 3
    assert subs[0].sub_id == "sub_0"
    assert subs[2].sub_id == "sub_2"


def test_decompose_sequential():
    subs = decompose_sequential(["First design the API", "Then implement it", "Finally test it"])
    assert len(subs) == 3
    assert subs[0].depends_on == []
    assert subs[1].depends_on == ["sub_0"]
    assert subs[2].depends_on == ["sub_1"]


# ---------------------------------------------------------------------------
# SessionGraph tests
# ---------------------------------------------------------------------------


def test_session_graph():
    graph = SessionGraph()

    from llmsp.council import CouncilSession
    import time

    s1 = CouncilSession(session_id="s1", channel_id="ch1", query="q1")
    s2 = CouncilSession(session_id="s2", channel_id="ch2", query="q2")

    sp1 = SubProblem(sub_id="sub_0", query="q1")
    sp2 = SubProblem(sub_id="sub_1", query="q2")

    graph.add_root(s1, sp1)
    graph.add_child("s1", s2, sp2)

    assert len(graph) == 2
    assert graph.roots == ["s1"]
    node = graph.get_node("s1")
    assert node is not None
    assert "s2" in node.children


# ---------------------------------------------------------------------------
# MetaCouncil federation tests
# ---------------------------------------------------------------------------


def test_federation_keyword():
    meta, store = _setup_federation()
    result = asyncio.get_event_loop().run_until_complete(
        meta.federate(
            "Design the security architecture for database performance",
            "fed_test",
            strategy=DecompositionStrategy.KEYWORD,
        )
    )
    assert result.total_responses > 0
    assert result.merged_synthesis is not None
    assert len(result.sub_results) >= 2
    assert result.elapsed_sec >= 0


def test_federation_explicit():
    meta, store = _setup_federation()
    result = asyncio.get_event_loop().run_until_complete(
        meta.federate(
            "Analyze the protocol",
            "fed_explicit",
            strategy=DecompositionStrategy.EXPLICIT,
            explicit_sub_queries=[
                "What are the cryptographic requirements?",
                "What are the performance requirements?",
            ],
        )
    )
    assert len(result.sub_results) == 2
    assert result.merged_synthesis is not None


def test_federation_sequential():
    meta, store = _setup_federation()
    result = asyncio.get_event_loop().run_until_complete(
        meta.federate(
            "Build incrementally",
            "fed_seq",
            strategy=DecompositionStrategy.SEQUENTIAL,
            explicit_sub_queries=[
                "First: design the data model",
                "Then: implement the API",
            ],
        )
    )
    assert len(result.sub_results) == 2
    assert result.merged_synthesis is not None


def test_federation_merged_synthesis():
    meta, store = _setup_federation()
    result = asyncio.get_event_loop().run_until_complete(
        meta.federate(
            "Security and architecture review",
            "fed_merge",
            strategy=DecompositionStrategy.EXPLICIT,
            explicit_sub_queries=["Security review", "Architecture review"],
        )
    )
    syn = result.merged_synthesis
    assert len(syn.summary_blocks) > 0
    assert len(syn.participating_agents) > 0


def test_federation_stores_events():
    meta, store = _setup_federation()
    initial = len(store)
    asyncio.get_event_loop().run_until_complete(
        meta.federate(
            "Security and architecture",
            "fed_events",
            strategy=DecompositionStrategy.EXPLICIT,
            explicit_sub_queries=["Security", "Architecture"],
        )
    )
    # Should have added: fed_start + sub_council events + merged synthesis + fed_end
    assert len(store) > initial


def test_federation_result_retrieval():
    meta, store = _setup_federation()
    result = asyncio.get_event_loop().run_until_complete(
        meta.federate("Test retrieval", "fed_retrieve",
                      strategy=DecompositionStrategy.EXPLICIT,
                      explicit_sub_queries=["Sub 1"])
    )
    retrieved = meta.get_result(result.federation_id)
    assert retrieved is not None
    assert retrieved.federation_id == result.federation_id
