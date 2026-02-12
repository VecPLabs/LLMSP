"""Tests for LLMSP context router."""

from llmsp.event_store import EventStore
from llmsp.models import EventType, TextBlock
from llmsp.principal import AgentPrincipal
from llmsp.router import (
    ContextRouter,
    RouteStrategy,
    RoutingRule,
    keyword_matcher,
)


def test_default_broadcast():
    store = EventStore()
    alice = AgentPrincipal("Alice", "dev")
    bob = AgentPrincipal("Bob", "security")
    router = ContextRouter(store, {alice.agent_id: alice, bob.agent_id: bob})

    decision = router.route("how does auth work?", "ch1")
    assert decision.strategy == RouteStrategy.BROADCAST
    assert set(decision.agents) == {alice.agent_id, bob.agent_id}


def test_keyword_rule_matches():
    store = EventStore()
    alice = AgentPrincipal("Alice", "dev")
    bob = AgentPrincipal("Bob", "security")
    router = ContextRouter(store, {alice.agent_id: alice, bob.agent_id: bob})

    rule = RoutingRule(
        name="security_queries",
        matcher=keyword_matcher("security", "vulnerability", "CVE"),
        strategy=RouteStrategy.DESIGNATED,
        target_roles=["security"],
    )
    router.add_rule(rule)

    decision = router.route("Is there a security vulnerability?", "ch1")
    assert decision.strategy == RouteStrategy.DESIGNATED
    assert bob.agent_id in decision.agents


def test_keyword_rule_no_match_falls_through():
    store = EventStore()
    alice = AgentPrincipal("Alice", "dev")
    router = ContextRouter(store, {alice.agent_id: alice})

    rule = RoutingRule(
        name="security_only",
        matcher=keyword_matcher("security"),
        strategy=RouteStrategy.SINGLE,
        target_roles=["security"],
    )
    router.add_rule(rule)

    decision = router.route("how do I write a for loop?", "ch1")
    assert decision.strategy == RouteStrategy.BROADCAST  # fell through


def test_context_retrieval():
    store = EventStore()
    p = AgentPrincipal("Test", "dev")

    for i in range(5):
        event = p.create_event("ch1", EventType.MESSAGE, [TextBlock(content=f"msg {i}")])
        store.append(event)

    router = ContextRouter(store)
    decision = router.route("what's happening?", "ch1", context_limit=3)
    assert len(decision.context_events) == 3


def test_register_agent_dynamically():
    store = EventStore()
    router = ContextRouter(store)

    alice = AgentPrincipal("Alice", "dev")
    router.register_agent(alice)

    decision = router.route("hello", "ch1")
    assert alice.agent_id in decision.agents


def test_council_strategy_rule():
    store = EventStore()
    alice = AgentPrincipal("Alice", "dev")
    bob = AgentPrincipal("Bob", "security")
    carol = AgentPrincipal("Carol", "architect")
    agents = {a.agent_id: a for a in [alice, bob, carol]}
    router = ContextRouter(store, agents)

    rule = RoutingRule(
        name="architecture_council",
        matcher=keyword_matcher("architecture", "design", "system design"),
        strategy=RouteStrategy.COUNCIL,
    )
    router.add_rule(rule)

    decision = router.route("let's discuss the system design", "ch1")
    assert decision.strategy == RouteStrategy.COUNCIL
    assert len(decision.agents) == 3  # all agents
