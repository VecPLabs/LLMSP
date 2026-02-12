"""Tests for the LLMSP Planner Agent."""

import asyncio

from llmsp.planner import (
    ExecutionPlan,
    LLMPlanner,
    PlanStep,
    RuleBasedPlanner,
    TaskComplexity,
    analyze_domains,
    estimate_complexity,
    roles_for_domain,
)
from llmsp.adapters.base import ApiResult, BaseAdapter
from llmsp.models import ContentBlock, SignedEvent, TextBlock
from llmsp.principal import AgentPrincipal
from typing import Optional


# ---------------------------------------------------------------------------
# Domain analysis
# ---------------------------------------------------------------------------


def test_analyze_domains_security():
    domains = analyze_domains("We need to fix the authentication vulnerability and audit access control")
    domain_names = [d[0] for d in domains]
    assert "security" in domain_names


def test_analyze_domains_multi():
    domains = analyze_domains("Design the database schema with encryption for the deployment pipeline")
    domain_names = [d[0] for d in domains]
    assert len(domain_names) >= 2


def test_analyze_domains_no_match():
    domains = analyze_domains("Hello world how are you today")
    assert len(domains) == 0


def test_analyze_domains_scoring():
    domains = analyze_domains("security vulnerability threat attack auth encrypt injection audit")
    assert domains[0][0] == "security"
    assert domains[0][1] > 0.4  # High match ratio


# ---------------------------------------------------------------------------
# Complexity estimation
# ---------------------------------------------------------------------------


def test_complexity_trivial():
    assert estimate_complexity("Fix bug in the login page") == TaskComplexity.TRIVIAL


def test_complexity_moderate():
    assert estimate_complexity("Add feature for user notifications") == TaskComplexity.MODERATE


def test_complexity_complex():
    assert estimate_complexity("Design and implement the payment system") == TaskComplexity.COMPLEX


def test_complexity_critical():
    assert estimate_complexity("Build a full-stack production dashboard") == TaskComplexity.CRITICAL


# ---------------------------------------------------------------------------
# Role mapping
# ---------------------------------------------------------------------------


def test_roles_for_security():
    roles = roles_for_domain("security")
    assert "sec" in roles or "security" in roles


def test_roles_for_unknown_domain():
    roles = roles_for_domain("quantum_computing")
    assert roles == ["dev"]


# ---------------------------------------------------------------------------
# RuleBasedPlanner
# ---------------------------------------------------------------------------


def test_planner_simple_goal():
    planner = RuleBasedPlanner()
    plan = planner.plan("Fix bug in the login handler")
    assert isinstance(plan, ExecutionPlan)
    assert len(plan.steps) == 1
    assert plan.steps[0].complexity == TaskComplexity.TRIVIAL


def test_planner_multi_domain_goal():
    planner = RuleBasedPlanner()
    plan = planner.plan("Design the security architecture for database performance optimization and deploy to kubernetes")
    assert len(plan.steps) >= 3  # analysis + domain steps + integration
    domains = {s.domain for s in plan.steps}
    assert len(domains) >= 2


def test_planner_execution_levels():
    planner = RuleBasedPlanner()
    plan = planner.plan("Secure the database architecture and optimize deployment performance")
    levels = plan.execution_levels

    # First level should be analysis (no deps)
    assert len(levels) >= 2
    first_ids = {s.step_id for s in levels[0]}
    assert "step_analysis" in first_ids

    # Integration should be in the last level
    last_ids = {s.step_id for s in levels[-1]}
    assert "step_integration" in last_ids


def test_planner_to_sub_problems():
    planner = RuleBasedPlanner()
    plan = planner.plan("Security and performance architecture review")
    subs = plan.to_sub_problems()
    assert len(subs) == len(plan.steps)
    assert all(s.query for s in subs)


def test_planner_max_steps():
    planner = RuleBasedPlanner(max_steps=3)
    plan = planner.plan("Security architecture for database performance optimization with testing and deployment")
    # Should cap domain steps even if more domains match
    assert len(plan.steps) <= 3 + 2  # max_steps-2 domains + analysis + integration


def test_planner_strategy_notes():
    planner = RuleBasedPlanner()
    plan = planner.plan("Simple fix")
    assert "Single-step" in plan.strategy_notes

    plan = planner.plan("Design the security architecture for database performance")
    assert "Multi-domain" in plan.strategy_notes


# ---------------------------------------------------------------------------
# ExecutionPlan
# ---------------------------------------------------------------------------


def test_execution_plan_levels_with_chain():
    steps = [
        PlanStep(step_id="s0", description="First", domain="general",
                 complexity=TaskComplexity.MODERATE, required_roles=["dev"]),
        PlanStep(step_id="s1", description="Second", domain="general",
                 complexity=TaskComplexity.MODERATE, required_roles=["dev"],
                 depends_on=["s0"]),
        PlanStep(step_id="s2", description="Third", domain="general",
                 complexity=TaskComplexity.MODERATE, required_roles=["dev"],
                 depends_on=["s1"]),
    ]
    plan = ExecutionPlan(plan_id="test", original_goal="test", steps=steps, total_estimated_agents=3)
    levels = plan.execution_levels
    assert len(levels) == 3  # Sequential chain


def test_execution_plan_levels_concurrent():
    steps = [
        PlanStep(step_id="s0", description="Analysis", domain="general",
                 complexity=TaskComplexity.MODERATE, required_roles=["dev"]),
        PlanStep(step_id="s1", description="Security", domain="security",
                 complexity=TaskComplexity.MODERATE, required_roles=["sec"],
                 depends_on=["s0"]),
        PlanStep(step_id="s2", description="Performance", domain="performance",
                 complexity=TaskComplexity.MODERATE, required_roles=["perf"],
                 depends_on=["s0"]),
    ]
    plan = ExecutionPlan(plan_id="test", original_goal="test", steps=steps, total_estimated_agents=3)
    levels = plan.execution_levels
    assert len(levels) == 2  # s0 alone, then s1+s2 concurrent
    assert len(levels[1]) == 2


# ---------------------------------------------------------------------------
# LLMPlanner (with stub adapter)
# ---------------------------------------------------------------------------


class StubPlannerAdapter(BaseAdapter):
    def __init__(self):
        super().__init__(model="stub", api_key="stub")

    async def _call_api(self, system_prompt: str, user_prompt: str) -> ApiResult:
        return ApiResult(text='{"steps": [{"step_id": "s0", "description": "Analyze", "domain": "security", "complexity": "moderate", "required_roles": ["sec"], "depends_on": [], "query": "Analyze security"}, {"step_id": "s1", "description": "Implement", "domain": "architecture", "complexity": "complex", "required_roles": ["dev"], "depends_on": ["s0"], "query": "Implement the design"}], "strategy_notes": "Two-phase plan"}', input_tokens=200, output_tokens=100)


class BadPlannerAdapter(BaseAdapter):
    def __init__(self):
        super().__init__(model="stub", api_key="stub")

    async def _call_api(self, system_prompt: str, user_prompt: str) -> ApiResult:
        return ApiResult(text="This is not valid JSON at all, sorry!")


def test_llm_planner_success():
    adapter = StubPlannerAdapter()
    principal = AgentPrincipal("Planner", "planner")
    planner = LLMPlanner(adapter, principal)

    plan = asyncio.get_event_loop().run_until_complete(planner.plan("Design secure API"))
    assert len(plan.steps) == 2
    assert plan.steps[0].domain == "security"
    assert plan.steps[1].depends_on == ["s0"]


def test_llm_planner_fallback():
    adapter = BadPlannerAdapter()
    principal = AgentPrincipal("Planner", "planner")
    planner = LLMPlanner(adapter, principal)

    plan = asyncio.get_event_loop().run_until_complete(planner.plan("Design secure architecture for database"))
    # Should fall back to rule-based
    assert len(plan.steps) >= 1
