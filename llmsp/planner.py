"""Planner Agent — intelligent goal decomposition for MetaCouncil.

Replaces naive keyword-based decomposition with structured planning:

1. PlannerAgent: decomposes complex goals into a dependency DAG of
   sub-tasks with domain hints, estimated complexity, and agent
   role requirements
2. Integrates with MetaCouncil as a pluggable decomposition strategy
3. Supports both LLM-powered and rule-based planning
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from llmsp.adapters.base import BaseAdapter
from llmsp.federation import (
    DecompositionStrategy,
    FederationPlan,
    SubProblem,
)
from llmsp.models import ContentBlock, SignedEvent, TextBlock
from llmsp.principal import AgentPrincipal


# ---------------------------------------------------------------------------
# Plan structure
# ---------------------------------------------------------------------------


class TaskComplexity(str, Enum):
    TRIVIAL = "trivial"     # Single agent, one round
    MODERATE = "moderate"   # Multi-agent, may need objection round
    COMPLEX = "complex"     # Full council with synthesis
    CRITICAL = "critical"   # Federation-level, requires sub-councils


@dataclass
class PlanStep:
    """A single step in a decomposed plan."""

    step_id: str
    description: str
    domain: str
    complexity: TaskComplexity
    required_roles: list[str]
    depends_on: list[str] = field(default_factory=list)
    estimated_agents: int = 2
    query: str = ""
    metadata: dict = field(default_factory=dict)


@dataclass
class ExecutionPlan:
    """A full decomposed plan for a complex goal."""

    plan_id: str
    original_goal: str
    steps: list[PlanStep]
    total_estimated_agents: int
    created_at: float = field(default_factory=time.time)
    strategy_notes: str = ""

    def to_sub_problems(self) -> list[SubProblem]:
        """Convert plan steps into federation SubProblems."""
        return [
            SubProblem(
                sub_id=step.step_id,
                query=step.query or step.description,
                domain_hint=step.domain,
                depends_on=step.depends_on,
                priority=i,
            )
            for i, step in enumerate(self.steps)
        ]

    @property
    def execution_levels(self) -> list[list[PlanStep]]:
        """Topological sort into concurrent execution levels."""
        resolved: set[str] = set()
        levels: list[list[PlanStep]] = []
        remaining = list(self.steps)

        while remaining:
            level: list[PlanStep] = []
            still_remaining: list[PlanStep] = []

            for step in remaining:
                if all(d in resolved for d in step.depends_on):
                    level.append(step)
                else:
                    still_remaining.append(step)

            if not level:
                level = still_remaining
                still_remaining = []

            levels.append(level)
            for step in level:
                resolved.add(step.step_id)
            remaining = still_remaining

        return levels


# ---------------------------------------------------------------------------
# Domain analysis
# ---------------------------------------------------------------------------

_DOMAIN_SIGNALS: dict[str, list[str]] = {
    "security": [
        "security", "vulnerability", "threat", "attack", "auth",
        "encrypt", "injection", "audit", "permission", "access control",
        "firewall", "ssl", "tls", "oauth", "jwt", "csrf", "xss",
    ],
    "architecture": [
        "architecture", "design", "pattern", "structure", "system",
        "component", "interface", "api", "microservice", "monolith",
        "layer", "abstraction", "coupling", "cohesion",
    ],
    "performance": [
        "performance", "speed", "latency", "throughput", "optimize",
        "scale", "benchmark", "cache", "bottleneck", "profil",
        "concurren", "parallel", "async",
    ],
    "data": [
        "database", "storage", "schema", "query", "index", "migration",
        "model", "sql", "nosql", "redis", "postgres", "mongo",
        "normalization", "denormalization",
    ],
    "frontend": [
        "ui", "ux", "frontend", "react", "vue", "angular", "css",
        "html", "component", "responsive", "accessibility", "a11y",
    ],
    "infrastructure": [
        "deploy", "docker", "kubernetes", "ci/cd", "monitor",
        "infrastructure", "container", "devops", "terraform",
        "cloud", "aws", "gcp", "azure",
    ],
    "testing": [
        "test", "coverage", "assertion", "mock", "fixture",
        "integration", "unit", "e2e", "regression", "qa",
    ],
    "ml": [
        "machine learning", "model", "training", "inference",
        "neural", "embedding", "transformer", "fine-tun", "prompt",
        "llm", "ai", "agent",
    ],
}


def analyze_domains(text: str) -> list[tuple[str, float]]:
    """Score a text against domain categories. Returns (domain, score) pairs."""
    text_lower = text.lower()
    results: list[tuple[str, float]] = []

    for domain, signals in _DOMAIN_SIGNALS.items():
        hits = sum(1 for s in signals if s in text_lower)
        if hits > 0:
            score = hits / len(signals)
            results.append((domain, score))

    results.sort(key=lambda x: x[1], reverse=True)
    return results


def estimate_complexity(text: str) -> TaskComplexity:
    """Estimate task complexity from goal description."""
    text_lower = text.lower()

    # Complexity indicators
    critical_signals = ["full-stack", "end-to-end", "entire system", "complete platform", "production"]
    complex_signals = ["design and implement", "refactor", "migrate", "architect", "multi-"]
    moderate_signals = ["add feature", "implement", "build", "create", "develop"]
    trivial_signals = ["fix bug", "update", "rename", "change", "tweak"]

    if any(s in text_lower for s in critical_signals):
        return TaskComplexity.CRITICAL
    if any(s in text_lower for s in complex_signals):
        return TaskComplexity.COMPLEX
    if any(s in text_lower for s in moderate_signals):
        return TaskComplexity.MODERATE
    return TaskComplexity.TRIVIAL


# ---------------------------------------------------------------------------
# Role-to-domain mapping
# ---------------------------------------------------------------------------

_DOMAIN_ROLES: dict[str, list[str]] = {
    "security": ["sec", "security", "auditor", "pentester"],
    "architecture": ["arch", "architect", "designer", "lead"],
    "performance": ["perf", "sre", "performance", "optimization"],
    "data": ["data", "dba", "database", "backend"],
    "frontend": ["frontend", "ui", "ux", "designer"],
    "infrastructure": ["ops", "devops", "infra", "sre", "platform"],
    "testing": ["qa", "test", "quality"],
    "ml": ["ml", "ai", "data-scientist", "researcher"],
}


def roles_for_domain(domain: str) -> list[str]:
    """Get recommended agent roles for a domain."""
    return _DOMAIN_ROLES.get(domain, ["dev"])


# ---------------------------------------------------------------------------
# Rule-based Planner
# ---------------------------------------------------------------------------


class RuleBasedPlanner:
    """Decomposes goals using domain analysis and heuristic rules.

    No LLM required — uses signal-based domain detection,
    complexity estimation, and dependency inference.
    """

    def __init__(self, max_steps: int = 6) -> None:
        self._max_steps = max_steps

    def plan(self, goal: str) -> ExecutionPlan:
        """Decompose a goal into an execution plan."""
        domains = analyze_domains(goal)
        overall_complexity = estimate_complexity(goal)

        if not domains or overall_complexity == TaskComplexity.TRIVIAL:
            # Single step — no decomposition needed
            return ExecutionPlan(
                plan_id=f"plan_{int(time.time() * 1000)}",
                original_goal=goal,
                steps=[
                    PlanStep(
                        step_id="step_0",
                        description=goal,
                        domain=domains[0][0] if domains else "general",
                        complexity=overall_complexity,
                        required_roles=["dev"],
                        query=goal,
                    )
                ],
                total_estimated_agents=2,
                strategy_notes="Single-step: goal is simple enough for one council.",
            )

        steps: list[PlanStep] = []

        # Phase 1: Analysis step (always first)
        primary_domain = domains[0][0]
        steps.append(
            PlanStep(
                step_id="step_analysis",
                description=f"Analyze requirements and constraints for: {goal}",
                domain=primary_domain,
                complexity=TaskComplexity.MODERATE,
                required_roles=roles_for_domain(primary_domain),
                query=f"Analyze the requirements, constraints, and risks for: {goal}",
                estimated_agents=2,
            )
        )

        # Phase 2: Domain-specific steps (concurrent)
        for i, (domain, score) in enumerate(domains[:self._max_steps - 2]):
            steps.append(
                PlanStep(
                    step_id=f"step_{domain}",
                    description=f"Address {domain} aspects of: {goal}",
                    domain=domain,
                    complexity=TaskComplexity.COMPLEX if score > 0.3 else TaskComplexity.MODERATE,
                    required_roles=roles_for_domain(domain),
                    depends_on=["step_analysis"],
                    query=f"From a {domain} perspective, address: {goal}",
                    estimated_agents=max(2, int(score * 5)),
                )
            )

        # Phase 3: Integration step (depends on all domain steps)
        domain_step_ids = [s.step_id for s in steps if s.step_id != "step_analysis"]
        steps.append(
            PlanStep(
                step_id="step_integration",
                description=f"Integrate findings and produce unified recommendations for: {goal}",
                domain="architecture",
                complexity=TaskComplexity.COMPLEX,
                required_roles=["arch", "lead"],
                depends_on=domain_step_ids,
                query=f"Integrate all domain findings into a unified plan for: {goal}",
                estimated_agents=3,
            )
        )

        total_agents = sum(s.estimated_agents for s in steps)

        return ExecutionPlan(
            plan_id=f"plan_{int(time.time() * 1000)}",
            original_goal=goal,
            steps=steps,
            total_estimated_agents=total_agents,
            strategy_notes=(
                f"Multi-domain decomposition: {len(domains)} domains detected "
                f"({', '.join(d for d, _ in domains)}). "
                f"Overall complexity: {overall_complexity.value}. "
                f"{len(steps)} steps across {len(set(s.domain for s in steps))} domains."
            ),
        )


# ---------------------------------------------------------------------------
# LLM-Powered Planner
# ---------------------------------------------------------------------------

_PLANNER_SYSTEM_PROMPT = """\
You are a Planning Agent in the LLMSP (LLM Swarm Protocol) system.

Your job is to decompose complex goals into a structured execution plan.
Each step should be a focused sub-problem that can be addressed by a
specialized council of agents.

Respond with a JSON object:
{{
  "steps": [
    {{
      "step_id": "step_0",
      "description": "what this step accomplishes",
      "domain": "security|architecture|performance|data|frontend|infrastructure|testing|ml",
      "complexity": "trivial|moderate|complex|critical",
      "required_roles": ["sec", "dev"],
      "depends_on": [],
      "query": "the specific question for the council to deliberate"
    }}
  ],
  "strategy_notes": "brief explanation of the decomposition strategy"
}}

Rules:
- Maximum {max_steps} steps
- First step should be analysis/requirements
- Last step should be integration/synthesis
- Middle steps can run concurrently if independent
- Use depends_on to express ordering constraints
- Each step's query should be self-contained and specific
"""


class LLMPlanner:
    """Decomposes goals using an LLM adapter for intelligent planning.

    Falls back to RuleBasedPlanner if the LLM response can't be parsed.
    """

    def __init__(
        self,
        adapter: BaseAdapter,
        principal: AgentPrincipal,
        max_steps: int = 6,
    ) -> None:
        self._adapter = adapter
        self._principal = principal
        self._max_steps = max_steps
        self._fallback = RuleBasedPlanner(max_steps)

    async def plan(self, goal: str, context: list[SignedEvent] | None = None) -> ExecutionPlan:
        """Decompose a goal using the LLM."""
        system = _PLANNER_SYSTEM_PROMPT.format(max_steps=self._max_steps)
        context_text = ""
        if context:
            context_text = "\n\nRelevant context from prior sessions:\n"
            for event in context[-10:]:
                for block in event.blocks:
                    if hasattr(block, "content"):
                        context_text += f"  - {block.content[:200]}\n"

        user_prompt = f"Decompose this goal into an execution plan:\n\n{goal}{context_text}"

        try:
            result = await self._adapter._call_api(system, user_prompt)
            return self._parse_plan(result.text, goal)
        except Exception:
            return self._fallback.plan(goal)

    def _parse_plan(self, raw: str, goal: str) -> ExecutionPlan:
        """Parse LLM response into an ExecutionPlan."""
        json_match = re.search(r'\{.*\}', raw.strip(), re.DOTALL)
        if not json_match:
            return self._fallback.plan(goal)

        try:
            data = json.loads(json_match.group())
        except json.JSONDecodeError:
            return self._fallback.plan(goal)

        steps_data = data.get("steps", [])
        if not steps_data:
            return self._fallback.plan(goal)

        steps: list[PlanStep] = []
        for s in steps_data[:self._max_steps]:
            steps.append(
                PlanStep(
                    step_id=s.get("step_id", f"step_{len(steps)}"),
                    description=s.get("description", ""),
                    domain=s.get("domain", "general"),
                    complexity=TaskComplexity(s.get("complexity", "moderate")),
                    required_roles=s.get("required_roles", ["dev"]),
                    depends_on=s.get("depends_on", []),
                    query=s.get("query", s.get("description", "")),
                    estimated_agents=len(s.get("required_roles", ["dev"])) + 1,
                )
            )

        return ExecutionPlan(
            plan_id=f"plan_{int(time.time() * 1000)}",
            original_goal=goal,
            steps=steps,
            total_estimated_agents=sum(s.estimated_agents for s in steps),
            strategy_notes=data.get("strategy_notes", "LLM-generated plan"),
        )
