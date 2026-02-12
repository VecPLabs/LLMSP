"""Council — the multi-agent deliberation engine.

Orchestrates a structured deliberation among multiple agents:
1. A query is routed to participating agents
2. Each agent produces a response (signed event)
3. Agents may object to other agents' responses
4. The Clerk synthesizes the results

This module provides the orchestration framework. The actual LLM calls
are delegated to agent adapters (pluggable backends).
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Optional, Protocol

from llmsp.clerk import Clerk, SynthesisResult
from llmsp.event_store import EventStore
from llmsp.models import (
    ContentBlock,
    EventType,
    SignedEvent,
    TextBlock,
)
from llmsp.principal import AgentPrincipal, PrincipalRegistry
from llmsp.router import ContextRouter, RouteDecision, RouteStrategy


# ---------------------------------------------------------------------------
# Agent Adapter Protocol
# ---------------------------------------------------------------------------


class AgentAdapter(Protocol):
    """Interface for LLM backends that agents use to generate responses.

    Implementations wrap specific LLM APIs (Claude, Gemini, Grok, etc.)
    """

    def generate(
        self,
        agent: AgentPrincipal,
        query: str,
        context: list[SignedEvent],
    ) -> list[ContentBlock]:
        """Generate content blocks in response to a query with context."""
        ...

    def review(
        self,
        agent: AgentPrincipal,
        query: str,
        proposal: SignedEvent,
        context: list[SignedEvent],
    ) -> Optional[list[ContentBlock]]:
        """Review another agent's proposal. Return objection blocks, or None to agree."""
        ...


# ---------------------------------------------------------------------------
# Council State
# ---------------------------------------------------------------------------


class CouncilPhase(str, Enum):
    IDLE = "idle"
    DELIBERATING = "deliberating"
    REVIEWING = "reviewing"
    SYNTHESIZING = "synthesizing"
    COMPLETE = "complete"


@dataclass
class CouncilSession:
    """State for a single council deliberation."""

    session_id: str
    channel_id: str
    query: str
    phase: CouncilPhase = CouncilPhase.IDLE
    participants: list[str] = field(default_factory=list)
    responses: list[SignedEvent] = field(default_factory=list)
    objections: list[SignedEvent] = field(default_factory=list)
    synthesis: Optional[SynthesisResult] = None
    started_at: float = field(default_factory=time.time)
    completed_at: Optional[float] = None


# ---------------------------------------------------------------------------
# Council Engine
# ---------------------------------------------------------------------------


class Council:
    """Orchestrates multi-agent deliberation.

    The Council manages the lifecycle of a deliberation:
    1. Route query to agents (via ContextRouter)
    2. Collect initial responses
    3. Run objection round (agents review each other's responses)
    4. Synthesize via the Clerk
    5. Record everything to the event store
    """

    def __init__(
        self,
        event_store: EventStore,
        registry: PrincipalRegistry,
        router: ContextRouter,
        clerk: Clerk,
        agents: Optional[dict[str, AgentPrincipal]] = None,
        adapters: Optional[dict[str, AgentAdapter]] = None,
        max_objection_rounds: int = 1,
    ) -> None:
        self._store = event_store
        self._registry = registry
        self._router = router
        self._clerk = clerk
        self._agents: dict[str, AgentPrincipal] = agents or {}
        self._adapters: dict[str, AgentAdapter] = adapters or {}
        self._max_objection_rounds = max_objection_rounds
        self._sessions: dict[str, CouncilSession] = {}

    def register_agent(
        self,
        agent: AgentPrincipal,
        adapter: AgentAdapter,
    ) -> None:
        """Register an agent and its LLM adapter with the council."""
        self._agents[agent.agent_id] = agent
        self._adapters[agent.agent_id] = adapter
        self._registry.register(agent)
        self._router.register_agent(agent)

    def deliberate(
        self,
        query: str,
        channel_id: str,
        strategy: Optional[RouteStrategy] = None,
        designated_agents: Optional[list[str]] = None,
    ) -> CouncilSession:
        """Run a full council deliberation.

        Steps:
        1. Route the query to determine participants
        2. Emit council_start event
        3. Collect responses from each agent
        4. Run objection rounds
        5. Synthesize with the Clerk
        6. Emit council_end event
        7. Record everything to the event store
        """
        # 1. Route
        if strategy and designated_agents:
            route = RouteDecision(
                strategy=strategy,
                agents=designated_agents,
                context_events=self._router.get_context(channel_id),
                channel_id=channel_id,
            )
        else:
            route = self._router.route(query, channel_id)

        session = CouncilSession(
            session_id=f"council_{int(time.time()*1000)}",
            channel_id=channel_id,
            query=query,
            participants=route.agents,
        )
        self._sessions[session.session_id] = session

        # 2. Council start event (from first available agent, or clerk)
        start_event = self._clerk._principal.create_event(
            channel_id=channel_id,
            event_type=EventType.COUNCIL_START,
            blocks=[TextBlock(content=f"Council deliberation started: {query}")],
        )
        self._store.append(start_event)
        session.phase = CouncilPhase.DELIBERATING

        # 3. Collect initial responses
        for agent_id in route.agents:
            agent = self._agents.get(agent_id)
            adapter = self._adapters.get(agent_id)
            if not agent or not adapter:
                continue

            blocks = adapter.generate(agent, query, route.context_events)
            event = agent.create_event(
                channel_id=channel_id,
                event_type=EventType.MESSAGE,
                blocks=blocks,
                parent_event_id=start_event.event_id,
            )
            self._store.append(event)
            session.responses.append(event)

        # 4. Objection rounds
        session.phase = CouncilPhase.REVIEWING
        for _round in range(self._max_objection_rounds):
            new_objections: list[SignedEvent] = []
            for agent_id in route.agents:
                agent = self._agents.get(agent_id)
                adapter = self._adapters.get(agent_id)
                if not agent or not adapter:
                    continue

                # Each agent reviews other agents' responses
                for response in session.responses:
                    if response.author_id == agent_id:
                        continue  # Don't review your own response
                    objection_blocks = adapter.review(
                        agent, query, response, route.context_events
                    )
                    if objection_blocks:
                        obj_event = agent.create_event(
                            channel_id=channel_id,
                            event_type=EventType.OBJECTION,
                            blocks=objection_blocks,
                            parent_event_id=response.event_id,
                        )
                        self._store.append(obj_event)
                        new_objections.append(obj_event)

            session.objections.extend(new_objections)
            if not new_objections:
                break  # No objections, consensus reached

        # 5. Synthesize
        session.phase = CouncilPhase.SYNTHESIZING
        all_events = session.responses + session.objections
        synthesis = self._clerk.synthesize(all_events, channel_id)
        session.synthesis = synthesis

        # Emit synthesis as an event
        synthesis_event = self._clerk.emit_synthesis_event(synthesis)
        self._store.append(synthesis_event)

        # 6. Council end
        end_event = self._clerk._principal.create_event(
            channel_id=channel_id,
            event_type=EventType.COUNCIL_END,
            blocks=[
                TextBlock(
                    content=f"Council complete: {len(session.responses)} responses, "
                    f"{len(session.objections)} objections, "
                    f"{len(synthesis.decisions)} decisions"
                )
            ],
        )
        self._store.append(end_event)

        session.phase = CouncilPhase.COMPLETE
        session.completed_at = time.time()

        return session

    def get_session(self, session_id: str) -> Optional[CouncilSession]:
        return self._sessions.get(session_id)
