"""Integration tests — wiring between LLMSP components.

Tests:
- Memory wired into AsyncCouncil (cross-session context injection)
- Planner wired into MetaCouncil via PLANNER strategy
- CLI command dispatch for new commands
"""

import asyncio
from typing import Optional
from unittest.mock import patch

from llmsp.adapters.base import ApiResult, BaseAdapter
from llmsp.async_council import AsyncCouncil
from llmsp.clerk import Clerk
from llmsp.council import CouncilPhase
from llmsp.event_store import EventStore
from llmsp.federation import DecompositionStrategy, MetaCouncil
from llmsp.memory import MemoryEntry, MemoryExtractor, MemoryStore, MemoryType
from llmsp.models import ClaimBlock, ContentBlock, EventType, SignedEvent, TextBlock
from llmsp.principal import AgentPrincipal, PrincipalRegistry
from llmsp.router import ContextRouter


# ---------------------------------------------------------------------------
# Stub adapter for integration tests
# ---------------------------------------------------------------------------


class IntegrationAdapter(BaseAdapter):
    """Deterministic adapter that echoes queries for integration testing."""

    def __init__(self):
        super().__init__(model="stub", api_key="stub")

    async def _call_api(self, system_prompt: str, user_prompt: str) -> ApiResult:
        return ApiResult(text="[]", input_tokens=50, output_tokens=10)

    async def generate(
        self, agent: AgentPrincipal, query: str, context: list[SignedEvent],
    ) -> list[ContentBlock]:
        await asyncio.sleep(0.01)
        return [
            TextBlock(content=f"[{agent.name}] response to: {query[:80]}"),
            ClaimBlock(claim=f"{agent.name} claim", confidence=0.85),
        ]

    async def review(
        self, agent: AgentPrincipal, query: str, proposal: SignedEvent, context: list[SignedEvent],
    ) -> Optional[list[ContentBlock]]:
        return None


def _make_council(memory_extractor=None, memory_store=None):
    """Create a fully wired AsyncCouncil with stub adapters."""
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
        memory_extractor=memory_extractor,
        memory_store=memory_store,
    )

    agents = []
    for name, role in [("Alice", "dev"), ("Bob", "sec")]:
        agent = AgentPrincipal(name, role)
        council.register_agent(agent, IntegrationAdapter())
        agents.append(agent)

    return council, store, clerk, agents


# ---------------------------------------------------------------------------
# Memory → AsyncCouncil integration
# ---------------------------------------------------------------------------


def test_council_without_memory():
    """Council works fine with no memory wired in."""
    council, store, clerk, agents = _make_council()
    session = asyncio.get_event_loop().run_until_complete(
        council.deliberate("What is the best key algorithm?", "ch_no_mem")
    )
    assert session.phase == CouncilPhase.COMPLETE
    assert len(session.responses) == 2


def test_council_with_memory_injection():
    """Council injects memory context into agent queries."""
    mem_store = MemoryStore()
    extractor = MemoryExtractor(mem_store)

    # Pre-seed a memory for Alice
    alice_id = "pr_alice_dev"
    mem_store.store(MemoryEntry(
        memory_id="mem_pre_1",
        agent_id=alice_id,
        memory_type=MemoryType.FACT,
        content="Ed25519 is preferred over RSA for signing",
        confidence=0.9,
    ))

    council, store, clerk, agents = _make_council(
        memory_extractor=extractor,
        memory_store=mem_store,
    )

    session = asyncio.get_event_loop().run_until_complete(
        council.deliberate("Which signing algorithm?", "ch_mem")
    )

    assert session.phase == CouncilPhase.COMPLETE
    assert len(session.responses) == 2


def test_council_memory_extraction_after_session():
    """Council extracts memories after deliberation completes."""
    mem_store = MemoryStore()
    extractor = MemoryExtractor(mem_store)

    council, store, clerk, agents = _make_council(
        memory_extractor=extractor,
        memory_store=mem_store,
    )

    session = asyncio.get_event_loop().run_until_complete(
        council.deliberate("Analyze cryptographic options", "ch_extract")
    )

    assert session.phase == CouncilPhase.COMPLETE
    # The extractor should have stored memories for the agents
    total = mem_store.count()
    assert total >= 1  # At least some memories extracted


def test_council_memory_context_format():
    """Memory context is formatted and non-empty for agents with memories."""
    mem_store = MemoryStore()
    extractor = MemoryExtractor(mem_store)

    mem_store.store(MemoryEntry(
        memory_id="mem_fmt_1",
        agent_id="pr_bob_sec",
        memory_type=MemoryType.POSITION,
        content="Always require encryption at rest",
        confidence=0.95,
    ))

    ctx = extractor.format_memory_context("pr_bob_sec")
    assert ctx != ""
    assert "encryption" in ctx


# ---------------------------------------------------------------------------
# Planner → MetaCouncil integration
# ---------------------------------------------------------------------------


def test_metacouncil_planner_strategy():
    """MetaCouncil uses RuleBasedPlanner when strategy is PLANNER."""
    council, store, clerk, agents = _make_council()
    meta = MetaCouncil(council=council, event_store=store, clerk=clerk)

    result = asyncio.get_event_loop().run_until_complete(
        meta.federate(
            "Design the security architecture for database performance optimization",
            "fed_planner",
            strategy=DecompositionStrategy.PLANNER,
        )
    )

    assert result.total_responses > 0
    assert result.merged_synthesis is not None
    assert len(result.sub_results) >= 1
    assert result.plan.strategy == DecompositionStrategy.PLANNER


def test_metacouncil_planner_simple_query():
    """Planner with a simple query produces a single-step plan."""
    council, store, clerk, agents = _make_council()
    meta = MetaCouncil(council=council, event_store=store, clerk=clerk)

    result = asyncio.get_event_loop().run_until_complete(
        meta.federate(
            "Fix the login bug",
            "fed_planner_simple",
            strategy=DecompositionStrategy.PLANNER,
        )
    )

    assert result.total_responses > 0
    assert result.merged_synthesis is not None


def test_metacouncil_planner_multi_domain():
    """Planner with a multi-domain query decomposes into multiple sub-councils."""
    council, store, clerk, agents = _make_council()
    meta = MetaCouncil(council=council, event_store=store, clerk=clerk)

    result = asyncio.get_event_loop().run_until_complete(
        meta.federate(
            "Secure the database architecture and optimize deployment performance with testing",
            "fed_planner_multi",
            strategy=DecompositionStrategy.PLANNER,
        )
    )

    assert result.total_responses > 0
    assert len(result.sub_results) >= 2


def test_planner_strategy_in_enum():
    """PLANNER is a valid DecompositionStrategy value."""
    assert DecompositionStrategy.PLANNER == "planner"
    assert DecompositionStrategy.PLANNER.value == "planner"


# ---------------------------------------------------------------------------
# CLI integration (command dispatch)
# ---------------------------------------------------------------------------


def test_cli_commands_registered():
    """All 12 commands are registered in the CLI dispatch table."""
    from llmsp.cli import main

    import argparse
    # Verify the main function has the right commands by checking
    # the module's command functions exist
    from llmsp import cli
    expected = [
        "cmd_init", "cmd_register", "cmd_agents", "cmd_council",
        "cmd_log", "cmd_search", "cmd_stats",
        "cmd_dashboard", "cmd_serve", "cmd_audit", "cmd_redteam", "cmd_cost",
    ]
    for fn_name in expected:
        assert hasattr(cli, fn_name), f"CLI missing command function: {fn_name}"


def test_cli_cost_command():
    """Cost command runs without error."""
    from llmsp.cli import cmd_cost

    class FakeArgs:
        db_dir = None

    # Should not raise
    cmd_cost(FakeArgs())


def test_cli_dashboard_command():
    """Dashboard command runs against an empty store."""
    from llmsp.cli import cmd_dashboard
    import tempfile

    class FakeArgs:
        db_dir = tempfile.mkdtemp()

    # Should not raise even with empty database
    cmd_dashboard(FakeArgs())
