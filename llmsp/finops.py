"""FinOps — token budgets, cost tracking, and dynamic model routing.

Multi-agent systems can 10x your token bill if not managed:

1. TokenBudget: hard limits at the CouncilSession level to prevent
   infinite objection loops
2. CostTracker: tracks token usage and cost per agent, per session,
   per model across the swarm
3. ModelRouter: selects models based on task complexity — uses small
   models for fast-feedback rounds, reserves frontier models for
   final synthesis
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


# ---------------------------------------------------------------------------
# Token Budget
# ---------------------------------------------------------------------------


class BudgetStatus(str, Enum):
    OK = "ok"
    WARNING = "warning"       # >80% consumed
    EXHAUSTED = "exhausted"   # Budget fully consumed
    OVERRUN = "overrun"       # Exceeded budget (if soft limit)


@dataclass
class TokenBudget:
    """Hard/soft token limit for a scope (session, agent, channel).

    When hard=True, operations that would exceed the budget are rejected.
    When hard=False, operations continue but emit warnings.
    """

    scope_id: str
    max_input_tokens: int
    max_output_tokens: int
    max_total_tokens: int
    hard: bool = True
    used_input: int = 0
    used_output: int = 0

    @property
    def used_total(self) -> int:
        return self.used_input + self.used_output

    @property
    def remaining_total(self) -> int:
        return max(0, self.max_total_tokens - self.used_total)

    @property
    def remaining_input(self) -> int:
        return max(0, self.max_input_tokens - self.used_input)

    @property
    def remaining_output(self) -> int:
        return max(0, self.max_output_tokens - self.used_output)

    @property
    def status(self) -> BudgetStatus:
        pct = self.used_total / self.max_total_tokens if self.max_total_tokens > 0 else 1.0
        if pct > 1.0:
            return BudgetStatus.OVERRUN
        if pct >= 1.0:
            return BudgetStatus.EXHAUSTED
        if pct >= 0.8:
            return BudgetStatus.WARNING
        return BudgetStatus.OK

    @property
    def usage_pct(self) -> float:
        if self.max_total_tokens == 0:
            return 1.0
        return self.used_total / self.max_total_tokens

    def consume(self, input_tokens: int = 0, output_tokens: int = 0) -> bool:
        """Record token consumption. Returns False if budget exceeded (hard limit)."""
        if self.hard:
            new_input = self.used_input + input_tokens
            new_output = self.used_output + output_tokens
            if (new_input > self.max_input_tokens
                    or new_output > self.max_output_tokens
                    or new_input + new_output > self.max_total_tokens):
                return False

        self.used_input += input_tokens
        self.used_output += output_tokens
        return True

    def reset(self) -> None:
        self.used_input = 0
        self.used_output = 0


# ---------------------------------------------------------------------------
# Cost tracking
# ---------------------------------------------------------------------------


@dataclass
class TokenUsage:
    """Token usage for a single API call."""

    model: str
    input_tokens: int
    output_tokens: int
    cost_usd: float
    agent_id: str = ""
    session_id: str = ""
    timestamp: float = field(default_factory=time.time)


# Per-model pricing (USD per 1K tokens)
_MODEL_PRICING: dict[str, tuple[float, float]] = {
    # (input_per_1k, output_per_1k)
    # Frontier models
    "claude-opus-4-6": (0.015, 0.075),
    "claude-sonnet-4-5-20250929": (0.003, 0.015),
    "claude-haiku-4-5-20251001": (0.0008, 0.004),
    "gemini-2.0-pro": (0.00125, 0.005),
    "gemini-2.0-flash": (0.0001, 0.0004),
    "grok-3": (0.003, 0.015),
    "grok-3-mini": (0.0003, 0.0005),
    # Small models (for refinement rounds)
    "gemini-2.0-flash-lite": (0.00004, 0.00015),
    "claude-haiku-3-5": (0.0008, 0.004),
}


def estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    """Estimate cost in USD for a given model and token counts."""
    pricing = _MODEL_PRICING.get(model)
    if not pricing:
        # Default to mid-range pricing
        pricing = (0.003, 0.015)

    input_cost = (input_tokens / 1000) * pricing[0]
    output_cost = (output_tokens / 1000) * pricing[1]
    return round(input_cost + output_cost, 6)


class CostTracker:
    """Tracks token usage and costs across the swarm.

    Aggregates by agent, session, model, and time window.
    """

    def __init__(self) -> None:
        self._usages: list[TokenUsage] = []
        self._budgets: dict[str, TokenBudget] = {}

    def record(
        self,
        model: str,
        input_tokens: int,
        output_tokens: int,
        agent_id: str = "",
        session_id: str = "",
    ) -> TokenUsage:
        """Record a token usage event."""
        cost = estimate_cost(model, input_tokens, output_tokens)
        usage = TokenUsage(
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost,
            agent_id=agent_id,
            session_id=session_id,
        )
        self._usages.append(usage)

        # Check budgets
        for scope_id in [session_id, agent_id]:
            if scope_id and scope_id in self._budgets:
                self._budgets[scope_id].consume(input_tokens, output_tokens)

        return usage

    def set_budget(self, budget: TokenBudget) -> None:
        """Set a token budget for a scope."""
        self._budgets[budget.scope_id] = budget

    def get_budget(self, scope_id: str) -> Optional[TokenBudget]:
        return self._budgets.get(scope_id)

    def check_budget(self, scope_id: str) -> BudgetStatus:
        """Check budget status. Returns OK if no budget set."""
        budget = self._budgets.get(scope_id)
        if not budget:
            return BudgetStatus.OK
        return budget.status

    @property
    def total_cost(self) -> float:
        return round(sum(u.cost_usd for u in self._usages), 6)

    @property
    def total_tokens(self) -> int:
        return sum(u.input_tokens + u.output_tokens for u in self._usages)

    def cost_by_model(self) -> dict[str, float]:
        by_model: dict[str, float] = {}
        for u in self._usages:
            by_model[u.model] = by_model.get(u.model, 0) + u.cost_usd
        return {k: round(v, 6) for k, v in by_model.items()}

    def cost_by_agent(self) -> dict[str, float]:
        by_agent: dict[str, float] = {}
        for u in self._usages:
            if u.agent_id:
                by_agent[u.agent_id] = by_agent.get(u.agent_id, 0) + u.cost_usd
        return {k: round(v, 6) for k, v in by_agent.items()}

    def cost_by_session(self) -> dict[str, float]:
        by_session: dict[str, float] = {}
        for u in self._usages:
            if u.session_id:
                by_session[u.session_id] = by_session.get(u.session_id, 0) + u.cost_usd
        return {k: round(v, 6) for k, v in by_session.items()}

    def tokens_by_agent(self) -> dict[str, int]:
        by_agent: dict[str, int] = {}
        for u in self._usages:
            if u.agent_id:
                by_agent[u.agent_id] = by_agent.get(u.agent_id, 0) + u.input_tokens + u.output_tokens
        return by_agent

    def usage_count(self) -> int:
        return len(self._usages)

    def generate_report(self) -> str:
        """Generate a human-readable cost report."""
        lines = [
            "=" * 60,
            "LLMSP FINOPS REPORT",
            "=" * 60,
            f"Total API calls: {self.usage_count()}",
            f"Total tokens: {self.total_tokens:,}",
            f"Total cost: ${self.total_cost:.4f}",
            "",
        ]

        by_model = self.cost_by_model()
        if by_model:
            lines.append("--- Cost by Model ---")
            for model, cost in sorted(by_model.items(), key=lambda x: x[1], reverse=True):
                lines.append(f"  {model}: ${cost:.4f}")
            lines.append("")

        by_agent = self.cost_by_agent()
        if by_agent:
            lines.append("--- Cost by Agent ---")
            for agent, cost in sorted(by_agent.items(), key=lambda x: x[1], reverse=True):
                lines.append(f"  {agent}: ${cost:.4f}")
            lines.append("")

        # Budget status
        if self._budgets:
            lines.append("--- Budget Status ---")
            for scope_id, budget in self._budgets.items():
                lines.append(
                    f"  {scope_id}: {budget.status.value} "
                    f"({budget.used_total:,}/{budget.max_total_tokens:,} tokens, "
                    f"{budget.usage_pct:.0%})"
                )

        lines.append("=" * 60)
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Dynamic Model Router
# ---------------------------------------------------------------------------


class ModelTier(str, Enum):
    """Model tiers by capability/cost tradeoff."""
    FRONTIER = "frontier"    # Best quality, highest cost
    STANDARD = "standard"    # Good quality, moderate cost
    FAST = "fast"           # Lower quality, very cheap
    MINI = "mini"           # Minimal quality, near-free


@dataclass
class ModelConfig:
    """Configuration for a model in the routing table."""

    model_id: str
    tier: ModelTier
    input_price_per_1k: float
    output_price_per_1k: float
    max_context: int = 128000
    speed_factor: float = 1.0  # Relative speed (higher = faster)

    @property
    def cost_score(self) -> float:
        """Normalized cost score (0=free, 1=most expensive)."""
        return (self.input_price_per_1k + self.output_price_per_1k) / 0.1  # Normalize to opus range


_DEFAULT_MODELS: list[ModelConfig] = [
    ModelConfig("claude-opus-4-6", ModelTier.FRONTIER, 0.015, 0.075, 200000, 0.5),
    ModelConfig("claude-sonnet-4-5-20250929", ModelTier.STANDARD, 0.003, 0.015, 200000, 1.0),
    ModelConfig("claude-haiku-4-5-20251001", ModelTier.FAST, 0.0008, 0.004, 200000, 3.0),
    ModelConfig("gemini-2.0-pro", ModelTier.STANDARD, 0.00125, 0.005, 2000000, 1.0),
    ModelConfig("gemini-2.0-flash", ModelTier.FAST, 0.0001, 0.0004, 1000000, 5.0),
    ModelConfig("grok-3", ModelTier.STANDARD, 0.003, 0.015, 131072, 1.0),
    ModelConfig("grok-3-mini", ModelTier.FAST, 0.0003, 0.0005, 131072, 4.0),
]


class ModelRouter:
    """Dynamically selects models based on task requirements and budget.

    Routes to:
    - MINI/FAST models for refinement rounds, simple reviews, formatting
    - STANDARD models for normal deliberation
    - FRONTIER models for final synthesis, critical decisions, complex reasoning

    Also respects budget constraints — downgrades to cheaper models
    when budget is running low.
    """

    def __init__(
        self,
        models: Optional[list[ModelConfig]] = None,
        cost_tracker: Optional[CostTracker] = None,
    ) -> None:
        self._models = {m.model_id: m for m in (models or _DEFAULT_MODELS)}
        self._tier_models: dict[ModelTier, list[ModelConfig]] = {}
        for m in self._models.values():
            self._tier_models.setdefault(m.tier, []).append(m)
        self._cost_tracker = cost_tracker

    def select_model(
        self,
        task_type: str,
        budget_scope: Optional[str] = None,
        preferred_vendor: Optional[str] = None,
    ) -> str:
        """Select the best model for a given task type.

        Task types:
        - "synthesis": final synthesis → FRONTIER
        - "deliberation": main response → STANDARD
        - "review": objection review → FAST
        - "refinement": iterative refinement → FAST
        - "planning": goal decomposition → STANDARD
        - "formatting": output formatting → MINI
        """
        # Map task type to ideal tier
        tier_map = {
            "synthesis": ModelTier.FRONTIER,
            "critical_decision": ModelTier.FRONTIER,
            "deliberation": ModelTier.STANDARD,
            "planning": ModelTier.STANDARD,
            "review": ModelTier.FAST,
            "refinement": ModelTier.FAST,
            "formatting": ModelTier.FAST,
            "simple_query": ModelTier.FAST,
        }

        target_tier = tier_map.get(task_type, ModelTier.STANDARD)

        # Check budget — downgrade if running low
        if budget_scope and self._cost_tracker:
            budget = self._cost_tracker.get_budget(budget_scope)
            if budget:
                if budget.status == BudgetStatus.EXHAUSTED:
                    return ""  # No model — budget exhausted
                if budget.status == BudgetStatus.WARNING:
                    # Downgrade one tier
                    target_tier = self._downgrade_tier(target_tier)

        # Find best model in tier
        candidates = self._tier_models.get(target_tier, [])

        if preferred_vendor:
            vendor_match = [c for c in candidates if preferred_vendor.lower() in c.model_id.lower()]
            if vendor_match:
                candidates = vendor_match

        if not candidates:
            # Fall back to any tier
            all_models = list(self._models.values())
            if not all_models:
                return ""
            candidates = all_models

        # Sort by speed (prefer faster within same tier)
        candidates.sort(key=lambda m: m.speed_factor, reverse=True)
        return candidates[0].model_id

    def _downgrade_tier(self, tier: ModelTier) -> ModelTier:
        """Downgrade to a cheaper tier."""
        downgrades = {
            ModelTier.FRONTIER: ModelTier.STANDARD,
            ModelTier.STANDARD: ModelTier.FAST,
            ModelTier.FAST: ModelTier.MINI,
            ModelTier.MINI: ModelTier.MINI,
        }
        return downgrades[tier]

    def get_model_config(self, model_id: str) -> Optional[ModelConfig]:
        return self._models.get(model_id)

    def available_models(self) -> list[str]:
        return list(self._models.keys())

    def models_by_tier(self, tier: ModelTier) -> list[str]:
        return [m.model_id for m in self._tier_models.get(tier, [])]
