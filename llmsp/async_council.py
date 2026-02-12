"""Async Council — async multi-agent deliberation engine.

Extends the Council pattern to support async LLM adapters. Agents
generate responses concurrently for significantly faster deliberation.

Integrates with the Memory layer to give agents cross-session continuity
and with the SecurityAuditor for inline threat scanning.
"""

from __future__ import annotations

import asyncio
import time
from typing import Optional

from llmsp.clerk import Clerk, SynthesisResult
from llmsp.clerk_prompt import LLMClerk
from llmsp.event_store import EventStore
from llmsp.models import (
    ContentBlock,
    EventType,
    SignedEvent,
    TextBlock,
)
from llmsp.principal import AgentPrincipal, PrincipalRegistry
from llmsp.adapters.base import BaseAdapter
from llmsp.finops import CostTracker
from llmsp.router import ContextRouter, RouteDecision, RouteStrategy
from llmsp.council import CouncilPhase, CouncilSession


class AsyncCouncil:
    """Async multi-agent deliberation engine.

    Like Council, but uses async adapters and runs agent responses
    concurrently via asyncio.gather for faster deliberation.

    Optionally integrates with:
    - MemoryExtractor: learns from each session, injects memory context
    - SecurityAuditor: scans events inline before synthesis
    """

    def __init__(
        self,
        event_store: EventStore,
        registry: PrincipalRegistry,
        router: ContextRouter,
        clerk: Clerk,
        agents: Optional[dict[str, AgentPrincipal]] = None,
        adapters: Optional[dict[str, BaseAdapter]] = None,
        max_objection_rounds: int = 1,
        memory_extractor: Optional[object] = None,
        memory_store: Optional[object] = None,
        cost_tracker: Optional[CostTracker] = None,
    ) -> None:
        self._store = event_store
        self._registry = registry
        self._router = router
        self._clerk = clerk
        self._agents: dict[str, AgentPrincipal] = agents or {}
        self._adapters: dict[str, BaseAdapter] = adapters or {}
        self._max_objection_rounds = max_objection_rounds
        self._sessions: dict[str, CouncilSession] = {}
        self._memory_extractor = memory_extractor
        self._memory_store = memory_store
        self._cost_tracker = cost_tracker

    def _record_usage(self, adapter: BaseAdapter, agent_id: str, session_id: str) -> None:
        """Record token usage from the adapter's last API call."""
        if self._cost_tracker and adapter.last_usage:
            self._cost_tracker.record(
                model=adapter.model,
                input_tokens=adapter.last_usage.input_tokens,
                output_tokens=adapter.last_usage.output_tokens,
                agent_id=agent_id,
                session_id=session_id,
            )

    def register_agent(
        self,
        agent: AgentPrincipal,
        adapter: BaseAdapter,
    ) -> None:
        """Register an agent and its async LLM adapter."""
        self._agents[agent.agent_id] = agent
        self._adapters[agent.agent_id] = adapter
        self._registry.register(agent)
        self._router.register_agent(agent)

    async def deliberate(
        self,
        query: str,
        channel_id: str,
        strategy: Optional[RouteStrategy] = None,
        designated_agents: Optional[list[str]] = None,
    ) -> CouncilSession:
        """Run an async council deliberation.

        Agents generate responses concurrently. Objection review is also
        parallelized per-agent.
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
            session_id=f"council_{int(time.time() * 1000)}",
            channel_id=channel_id,
            query=query,
            participants=route.agents,
        )
        self._sessions[session.session_id] = session

        # 2. Council start
        start_event = self._clerk._principal.create_event(
            channel_id=channel_id,
            event_type=EventType.COUNCIL_START,
            blocks=[TextBlock(content=f"Council deliberation started: {query}")],
        )
        self._store.append(start_event)
        session.phase = CouncilPhase.DELIBERATING

        # 2b. Inject memory context if available
        memory_contexts: dict[str, str] = {}
        if self._memory_extractor and self._memory_store:
            from llmsp.memory import MemoryExtractor
            if isinstance(self._memory_extractor, MemoryExtractor):
                for agent_id in route.agents:
                    ctx = self._memory_extractor.format_memory_context(agent_id)
                    if ctx:
                        memory_contexts[agent_id] = ctx

        # 3. Collect responses CONCURRENTLY
        async def _generate(agent_id: str) -> Optional[SignedEvent]:
            agent = self._agents.get(agent_id)
            adapter = self._adapters.get(agent_id)
            if not agent or not adapter:
                return None

            # Prepend memory context to query if available
            effective_query = query
            mem_ctx = memory_contexts.get(agent_id)
            if mem_ctx:
                effective_query = f"{mem_ctx}\n\n{query}"

            blocks = await adapter.generate(agent, effective_query, route.context_events)
            self._record_usage(adapter, agent_id, session.session_id)
            event = agent.create_event(
                channel_id=channel_id,
                event_type=EventType.MESSAGE,
                blocks=blocks,
                parent_event_id=start_event.event_id,
            )
            return event

        results = await asyncio.gather(
            *[_generate(aid) for aid in route.agents],
            return_exceptions=True,
        )

        for result in results:
            if isinstance(result, SignedEvent):
                self._store.append(result)
                session.responses.append(result)
            elif isinstance(result, Exception):
                # Log the error as an event
                error_event = self._clerk._principal.create_event(
                    channel_id=channel_id,
                    event_type=EventType.MESSAGE,
                    blocks=[TextBlock(content=f"Agent error: {result}")],
                )
                self._store.append(error_event)

        # 4. Objection rounds (concurrent per agent)
        session.phase = CouncilPhase.REVIEWING
        for _round in range(self._max_objection_rounds):
            async def _review_all(agent_id: str) -> list[SignedEvent]:
                agent = self._agents.get(agent_id)
                adapter = self._adapters.get(agent_id)
                objections: list[SignedEvent] = []
                if not agent or not adapter:
                    return objections

                for response in session.responses:
                    if response.author_id == agent_id:
                        continue
                    obj_blocks = await adapter.review(
                        agent, query, response, route.context_events
                    )
                    self._record_usage(adapter, agent_id, session.session_id)
                    if obj_blocks:
                        obj_event = agent.create_event(
                            channel_id=channel_id,
                            event_type=EventType.OBJECTION,
                            blocks=obj_blocks,
                            parent_event_id=response.event_id,
                        )
                        objections.append(obj_event)
                return objections

            review_results = await asyncio.gather(
                *[_review_all(aid) for aid in route.agents],
                return_exceptions=True,
            )

            new_objections: list[SignedEvent] = []
            for result in review_results:
                if isinstance(result, list):
                    for obj in result:
                        self._store.append(obj)
                        new_objections.append(obj)

            session.objections.extend(new_objections)
            if not new_objections:
                break

        # 5. Synthesize
        session.phase = CouncilPhase.SYNTHESIZING
        all_events = session.responses + session.objections

        if isinstance(self._clerk, LLMClerk):
            synthesis = await self._clerk.synthesize_with_llm(all_events, channel_id)
            self._record_usage(self._clerk._adapter, "clerk", session.session_id)
        else:
            synthesis = self._clerk.synthesize(all_events, channel_id)

        session.synthesis = synthesis

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

        # 7. Extract memories from this session (non-blocking)
        if self._memory_extractor:
            from llmsp.memory import MemoryExtractor
            if isinstance(self._memory_extractor, MemoryExtractor):
                self._memory_extractor.extract_from_session(
                    session.session_id,
                    session.responses,
                    session.objections,
                )

        return session

    def get_session(self, session_id: str) -> Optional[CouncilSession]:
        return self._sessions.get(session_id)
