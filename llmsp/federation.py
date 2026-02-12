"""Multi-Council Federation — orchestrating swarms of councils.

The Federation layer turns LLMSP from "one council" into a true swarm:

- MetaCouncil: decomposes complex queries into sub-problems, spawns
  child councils for each, and merges their syntheses
- FederationRouter: routes sub-problems to specialized council clusters
- SessionGraph: tracks parent/child relationships between councils

This is where "LLM Swarm" actually becomes a swarm.
"""

from __future__ import annotations

import asyncio
import re
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from llmsp.async_council import AsyncCouncil
from llmsp.clerk import Clerk, SynthesisResult, Disagreement
from llmsp.council import CouncilPhase, CouncilSession
from llmsp.event_store import EventStore
from llmsp.models import (
    ClaimBlock,
    ContentBlock,
    DecisionBlock,
    EventType,
    SignedEvent,
    TaskBlock,
    TextBlock,
)
from llmsp.principal import AgentPrincipal, PrincipalRegistry
from llmsp.router import ContextRouter


# ---------------------------------------------------------------------------
# Sub-problem decomposition
# ---------------------------------------------------------------------------


class DecompositionStrategy(str, Enum):
    KEYWORD = "keyword"     # Split by domain keywords
    EXPLICIT = "explicit"   # User provides sub-problems
    SEQUENTIAL = "sequential"  # Chain: each council gets prior council's output
    PLANNER = "planner"     # LLM/rule-based planner decomposes the goal


@dataclass
class SubProblem:
    """A decomposed piece of a larger query."""

    sub_id: str
    query: str
    domain_hint: Optional[str] = None
    depends_on: list[str] = field(default_factory=list)
    priority: int = 0


@dataclass
class FederationPlan:
    """Execution plan for a federated multi-council deliberation."""

    plan_id: str
    original_query: str
    sub_problems: list[SubProblem]
    strategy: DecompositionStrategy
    created_at: float = field(default_factory=time.time)


# ---------------------------------------------------------------------------
# Keyword-based decomposer
# ---------------------------------------------------------------------------

# Domain keyword mappings for automatic decomposition
_DOMAIN_KEYWORDS: dict[str, list[str]] = {
    "security": ["security", "vulnerability", "threat", "attack", "auth", "encrypt", "injection", "audit"],
    "architecture": ["architecture", "design", "pattern", "structure", "system", "component", "interface"],
    "performance": ["performance", "speed", "latency", "throughput", "optimize", "scale", "benchmark"],
    "data": ["database", "storage", "schema", "query", "index", "migration", "model"],
    "operations": ["deploy", "docker", "ci/cd", "monitor", "infrastructure", "container", "devops"],
    "testing": ["test", "coverage", "assertion", "mock", "fixture", "integration", "unit"],
}


def decompose_by_keywords(query: str) -> list[SubProblem]:
    """Split a query into sub-problems based on domain keywords."""
    query_lower = query.lower()
    matched_domains: list[tuple[str, int]] = []

    for domain, keywords in _DOMAIN_KEYWORDS.items():
        score = sum(1 for kw in keywords if kw in query_lower)
        if score > 0:
            matched_domains.append((domain, score))

    matched_domains.sort(key=lambda x: x[1], reverse=True)

    if len(matched_domains) <= 1:
        # Single domain or no matches — don't decompose
        return [SubProblem(sub_id="sub_0", query=query)]

    sub_problems = []
    for i, (domain, _) in enumerate(matched_domains[:4]):
        sub_problems.append(
            SubProblem(
                sub_id=f"sub_{i}",
                query=f"[{domain.upper()} perspective] {query}",
                domain_hint=domain,
                priority=i,
            )
        )

    return sub_problems


def decompose_explicit(queries: list[str]) -> list[SubProblem]:
    """Create sub-problems from an explicit list of queries."""
    return [
        SubProblem(sub_id=f"sub_{i}", query=q, priority=i)
        for i, q in enumerate(queries)
    ]


def decompose_sequential(queries: list[str]) -> list[SubProblem]:
    """Create a sequential chain where each depends on the previous."""
    subs = []
    for i, q in enumerate(queries):
        depends = [f"sub_{i-1}"] if i > 0 else []
        subs.append(
            SubProblem(sub_id=f"sub_{i}", query=q, depends_on=depends, priority=i)
        )
    return subs


# ---------------------------------------------------------------------------
# Session Graph
# ---------------------------------------------------------------------------


@dataclass
class SessionNode:
    """A node in the federation session graph."""

    session: CouncilSession
    sub_problem: SubProblem
    parent_id: Optional[str] = None
    children: list[str] = field(default_factory=list)


class SessionGraph:
    """Tracks parent/child relationships between federated councils."""

    def __init__(self) -> None:
        self._nodes: dict[str, SessionNode] = {}
        self._roots: list[str] = []

    def add_root(self, session: CouncilSession, sub_problem: SubProblem) -> None:
        node = SessionNode(session=session, sub_problem=sub_problem)
        self._nodes[session.session_id] = node
        self._roots.append(session.session_id)

    def add_child(
        self,
        parent_id: str,
        session: CouncilSession,
        sub_problem: SubProblem,
    ) -> None:
        node = SessionNode(session=session, sub_problem=sub_problem, parent_id=parent_id)
        self._nodes[session.session_id] = node
        if parent_id in self._nodes:
            self._nodes[parent_id].children.append(session.session_id)

    def get_node(self, session_id: str) -> Optional[SessionNode]:
        return self._nodes.get(session_id)

    @property
    def all_sessions(self) -> list[CouncilSession]:
        return [n.session for n in self._nodes.values()]

    @property
    def roots(self) -> list[str]:
        return list(self._roots)

    def __len__(self) -> int:
        return len(self._nodes)


# ---------------------------------------------------------------------------
# Federation Result
# ---------------------------------------------------------------------------


@dataclass
class FederationResult:
    """The merged output of a federated multi-council deliberation."""

    federation_id: str
    original_query: str
    plan: FederationPlan
    sub_results: list[CouncilSession]
    merged_synthesis: SynthesisResult
    session_graph: SessionGraph
    total_responses: int
    total_objections: int
    total_agents: int
    started_at: float
    completed_at: float
    elapsed_sec: float


# ---------------------------------------------------------------------------
# MetaCouncil
# ---------------------------------------------------------------------------


class MetaCouncil:
    """Orchestrates federated multi-council deliberations.

    Given a complex query, the MetaCouncil:
    1. Decomposes it into sub-problems
    2. Spawns a child AsyncCouncil for each sub-problem
    3. Runs them concurrently (respecting dependency chains)
    4. Merges all sub-syntheses into a unified federation result
    """

    def __init__(
        self,
        council: AsyncCouncil,
        event_store: EventStore,
        clerk: Clerk,
        max_sub_problems: int = 4,
    ) -> None:
        self._council = council
        self._store = event_store
        self._clerk = clerk
        self._max_sub_problems = max_sub_problems
        self._results: dict[str, FederationResult] = {}

    async def federate(
        self,
        query: str,
        channel_id: str,
        strategy: DecompositionStrategy = DecompositionStrategy.KEYWORD,
        explicit_sub_queries: Optional[list[str]] = None,
    ) -> FederationResult:
        """Run a federated multi-council deliberation.

        Steps:
        1. Decompose query into sub-problems
        2. Build execution plan (respecting dependencies)
        3. Run councils concurrently where possible
        4. Merge all syntheses
        """
        t0 = time.time()
        fed_id = f"fed_{int(t0 * 1000)}"
        graph = SessionGraph()

        # 1. Decompose
        if strategy == DecompositionStrategy.PLANNER:
            from llmsp.planner import RuleBasedPlanner
            planner = RuleBasedPlanner(max_steps=self._max_sub_problems)
            plan_result = planner.plan(query)
            sub_problems = plan_result.to_sub_problems()
        elif strategy == DecompositionStrategy.EXPLICIT and explicit_sub_queries:
            sub_problems = decompose_explicit(explicit_sub_queries)
        elif strategy == DecompositionStrategy.SEQUENTIAL and explicit_sub_queries:
            sub_problems = decompose_sequential(explicit_sub_queries)
        else:
            sub_problems = decompose_by_keywords(query)

        sub_problems = sub_problems[:self._max_sub_problems]

        plan = FederationPlan(
            plan_id=fed_id,
            original_query=query,
            sub_problems=sub_problems,
            strategy=strategy,
        )

        # Emit federation start event
        start_event = self._clerk._principal.create_event(
            channel_id=channel_id,
            event_type=EventType.COUNCIL_START,
            blocks=[
                TextBlock(
                    content=f"Federation started: {query} -> "
                    f"{len(sub_problems)} sub-councils"
                )
            ],
        )
        self._store.append(start_event)

        # 2. Execute sub-councils
        sub_sessions: list[CouncilSession] = []

        # Group by dependency level for execution ordering
        levels = self._resolve_execution_order(sub_problems)

        for level in levels:
            # All problems in this level can run concurrently
            tasks = [
                self._run_sub_council(sp, channel_id, fed_id)
                for sp in level
            ]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            for sp, result in zip(level, results):
                if isinstance(result, CouncilSession):
                    sub_sessions.append(result)
                    graph.add_root(result, sp)

        # 3. Merge syntheses
        merged = self._merge_syntheses(sub_sessions, channel_id)

        # Emit merged synthesis
        merge_event = self._clerk._principal.create_event(
            channel_id=channel_id,
            event_type=EventType.DECISION,
            blocks=merged.summary_blocks,
        )
        self._store.append(merge_event)

        # Emit federation end
        end_event = self._clerk._principal.create_event(
            channel_id=channel_id,
            event_type=EventType.COUNCIL_END,
            blocks=[
                TextBlock(
                    content=f"Federation complete: {len(sub_sessions)} sub-councils, "
                    f"{sum(len(s.responses) for s in sub_sessions)} total responses"
                )
            ],
        )
        self._store.append(end_event)

        t1 = time.time()

        total_agents: set[str] = set()
        for s in sub_sessions:
            total_agents.update(s.participants)

        result = FederationResult(
            federation_id=fed_id,
            original_query=query,
            plan=plan,
            sub_results=sub_sessions,
            merged_synthesis=merged,
            session_graph=graph,
            total_responses=sum(len(s.responses) for s in sub_sessions),
            total_objections=sum(len(s.objections) for s in sub_sessions),
            total_agents=len(total_agents),
            started_at=t0,
            completed_at=t1,
            elapsed_sec=t1 - t0,
        )

        self._results[fed_id] = result
        return result

    async def _run_sub_council(
        self,
        sub_problem: SubProblem,
        parent_channel: str,
        federation_id: str,
    ) -> CouncilSession:
        """Run a single sub-council for one sub-problem."""
        sub_channel = f"{parent_channel}__{sub_problem.sub_id}"
        return await self._council.deliberate(sub_problem.query, sub_channel)

    def _resolve_execution_order(
        self, sub_problems: list[SubProblem]
    ) -> list[list[SubProblem]]:
        """Topological sort of sub-problems into execution levels.

        Level 0: no dependencies (run first, concurrently)
        Level 1: depends on level 0 results
        etc.
        """
        by_id = {sp.sub_id: sp for sp in sub_problems}
        resolved: set[str] = set()
        levels: list[list[SubProblem]] = []

        remaining = list(sub_problems)
        while remaining:
            level: list[SubProblem] = []
            still_remaining: list[SubProblem] = []

            for sp in remaining:
                deps_met = all(d in resolved for d in sp.depends_on)
                if deps_met:
                    level.append(sp)
                else:
                    still_remaining.append(sp)

            if not level:
                # Circular dependency — force-resolve remaining
                level = still_remaining
                still_remaining = []

            levels.append(level)
            for sp in level:
                resolved.add(sp.sub_id)
            remaining = still_remaining

        return levels

    def _merge_syntheses(
        self,
        sessions: list[CouncilSession],
        channel_id: str,
    ) -> SynthesisResult:
        """Merge multiple council syntheses into one unified result."""
        all_agreements: list[str] = []
        all_disagreements: list[Disagreement] = []
        all_decisions: list[DecisionBlock] = []
        all_actions: list[TaskBlock] = []
        all_agents: set[str] = set()
        all_event_ids: list[str] = []
        summary_parts: list[str] = []

        for session in sessions:
            if not session.synthesis:
                continue

            syn = session.synthesis
            all_agreements.extend(syn.agreements)
            all_disagreements.extend(syn.disagreements)
            all_decisions.extend(syn.decisions)
            all_actions.extend(syn.action_items)
            all_agents.update(syn.participating_agents)
            all_event_ids.extend(syn.source_event_ids)

            for block in syn.summary_blocks:
                if isinstance(block, TextBlock):
                    summary_parts.append(
                        f"[{session.channel_id}] {block.content}"
                    )

        # Build merged summary blocks
        summary_blocks: list[ContentBlock] = []

        summary_blocks.append(
            TextBlock(
                content=f"Federation synthesis across {len(sessions)} sub-councils, "
                f"{len(all_agents)} agents"
            )
        )

        if summary_parts:
            summary_blocks.append(
                TextBlock(content="Sub-council summaries:\n" + "\n".join(f"  - {s}" for s in summary_parts))
            )

        if all_agreements:
            # Deduplicate
            unique = list(dict.fromkeys(all_agreements))
            summary_blocks.append(
                TextBlock(content="Cross-council agreements:\n" + "\n".join(f"  - {a}" for a in unique))
            )

        if all_disagreements:
            lines = []
            for d in all_disagreements:
                lines.append(f"  {d.topic}")
                for aid, pos in d.positions.items():
                    lines.append(f"    [{aid}]: {pos}")
            summary_blocks.append(
                TextBlock(content="Cross-council disagreements:\n" + "\n".join(lines))
            )

        if all_decisions:
            summary_blocks.append(
                TextBlock(
                    content="Decisions:\n" + "\n".join(
                        f"  - {d.decision} ({d.rationale})" for d in all_decisions
                    )
                )
            )

        if all_actions:
            summary_blocks.append(
                TextBlock(
                    content="Action items:\n" + "\n".join(
                        f"  - {t.task}" + (f" [{t.assignee}]" if t.assignee else "")
                        for t in all_actions
                    )
                )
            )

        return SynthesisResult(
            channel_id=channel_id,
            summary_blocks=summary_blocks,
            agreements=list(dict.fromkeys(all_agreements)),
            disagreements=all_disagreements,
            decisions=all_decisions,
            action_items=all_actions,
            participating_agents=sorted(all_agents),
            source_event_ids=all_event_ids,
        )

    def get_result(self, federation_id: str) -> Optional[FederationResult]:
        return self._results.get(federation_id)
