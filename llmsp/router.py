"""Context Router — routes queries to appropriate agents and retrieves context.

The router is the entry point for user queries. It determines which agents
should participate and retrieves relevant event history to provide context.
This is where RAG integration plugs in.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Optional

from llmsp.event_store import EventStore
from llmsp.models import EventType, SignedEvent
from llmsp.principal import AgentPrincipal


class RouteStrategy(str, Enum):
    """How to route a query to agents."""

    SINGLE = "single"           # One agent handles it
    BROADCAST = "broadcast"     # All agents respond
    COUNCIL = "council"         # Full council deliberation
    DESIGNATED = "designated"   # Specific named agents


@dataclass
class RouteDecision:
    """The router's decision on how to handle a query."""

    strategy: RouteStrategy
    agents: list[str]           # agent_ids to participate
    context_events: list[SignedEvent] = field(default_factory=list)
    channel_id: str = ""
    metadata: dict = field(default_factory=dict)


class ContextRouter:
    """Routes queries and retrieves relevant context.

    The router maintains a mapping of roles to agents and applies
    routing rules based on query classification.
    """

    def __init__(
        self,
        event_store: EventStore,
        agents: Optional[dict[str, AgentPrincipal]] = None,
    ) -> None:
        self._store = event_store
        self._agents: dict[str, AgentPrincipal] = agents or {}
        self._role_index: dict[str, list[str]] = {}
        self._routing_rules: list[RoutingRule] = []

        # Build role index
        for agent_id, agent in self._agents.items():
            self._role_index.setdefault(agent.role, []).append(agent_id)

    def register_agent(self, agent: AgentPrincipal) -> None:
        """Add an agent to the router's pool."""
        self._agents[agent.agent_id] = agent
        self._role_index.setdefault(agent.role, []).append(agent.agent_id)

    def add_rule(self, rule: RoutingRule) -> None:
        """Add a routing rule. Rules are evaluated in order; first match wins."""
        self._routing_rules.append(rule)

    def route(
        self,
        query: str,
        channel_id: str,
        context_limit: int = 20,
    ) -> RouteDecision:
        """Route a query to the appropriate agent(s) with context.

        Evaluates routing rules in order. If no rule matches,
        falls back to broadcasting to all agents.
        """
        # Retrieve recent context from the channel
        context_events = self._store.get_channel(channel_id, limit=context_limit)

        # Try each rule
        for rule in self._routing_rules:
            decision = rule.evaluate(query, self._agents, self._role_index)
            if decision is not None:
                decision.context_events = context_events
                decision.channel_id = channel_id
                return decision

        # Default: broadcast to all agents
        return RouteDecision(
            strategy=RouteStrategy.BROADCAST,
            agents=list(self._agents.keys()),
            context_events=context_events,
            channel_id=channel_id,
        )

    def get_context(
        self,
        channel_id: str,
        limit: int = 20,
        after_ts: Optional[float] = None,
    ) -> list[SignedEvent]:
        """Retrieve context events for a channel."""
        return self._store.get_channel(channel_id, limit=limit, after_ts=after_ts)

    def get_thread_context(self, parent_event_id: str) -> list[SignedEvent]:
        """Retrieve all events in a thread."""
        return self._store.get_thread(parent_event_id)


# ---------------------------------------------------------------------------
# Routing Rules
# ---------------------------------------------------------------------------


@dataclass
class RoutingRule:
    """A rule that maps query patterns to routing strategies."""

    name: str
    matcher: Callable[[str], bool]
    strategy: RouteStrategy
    target_roles: list[str] = field(default_factory=list)
    target_agents: list[str] = field(default_factory=list)

    def evaluate(
        self,
        query: str,
        agents: dict[str, AgentPrincipal],
        role_index: dict[str, list[str]],
    ) -> Optional[RouteDecision]:
        """Evaluate whether this rule matches the query.

        Returns a RouteDecision if matched, None otherwise.
        """
        if not self.matcher(query):
            return None

        # Resolve target agents
        resolved: list[str] = list(self.target_agents)
        for role in self.target_roles:
            resolved.extend(role_index.get(role, []))

        if not resolved:
            resolved = list(agents.keys())

        return RouteDecision(
            strategy=self.strategy,
            agents=resolved,
        )


def keyword_matcher(*keywords: str) -> Callable[[str], bool]:
    """Create a matcher that triggers if any keyword is found in the query."""
    kw_lower = [k.lower() for k in keywords]

    def _match(query: str) -> bool:
        q = query.lower()
        return any(k in q for k in kw_lower)

    return _match
