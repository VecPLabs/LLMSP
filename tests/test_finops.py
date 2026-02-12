"""Tests for LLMSP FinOps — token budgets, cost tracking, model routing."""

from llmsp.finops import (
    BudgetStatus,
    CostTracker,
    ModelConfig,
    ModelRouter,
    ModelTier,
    TokenBudget,
    estimate_cost,
)


# ---------------------------------------------------------------------------
# TokenBudget tests
# ---------------------------------------------------------------------------


def test_budget_creation():
    budget = TokenBudget(
        scope_id="session_1",
        max_input_tokens=10000,
        max_output_tokens=5000,
        max_total_tokens=15000,
    )
    assert budget.status == BudgetStatus.OK
    assert budget.remaining_total == 15000


def test_budget_consume():
    budget = TokenBudget(
        scope_id="s1",
        max_input_tokens=1000,
        max_output_tokens=500,
        max_total_tokens=1500,
    )
    ok = budget.consume(input_tokens=500, output_tokens=200)
    assert ok
    assert budget.used_input == 500
    assert budget.used_output == 200
    assert budget.used_total == 700
    assert budget.remaining_total == 800


def test_budget_hard_limit_blocks():
    budget = TokenBudget(
        scope_id="s1",
        max_input_tokens=100,
        max_output_tokens=50,
        max_total_tokens=150,
        hard=True,
    )
    ok = budget.consume(input_tokens=200)
    assert not ok
    assert budget.used_input == 0  # Not consumed


def test_budget_soft_limit_allows():
    budget = TokenBudget(
        scope_id="s1",
        max_input_tokens=100,
        max_output_tokens=50,
        max_total_tokens=150,
        hard=False,
    )
    ok = budget.consume(input_tokens=200)
    assert ok  # Soft limit allows
    assert budget.used_input == 200
    assert budget.status == BudgetStatus.OVERRUN


def test_budget_warning_threshold():
    budget = TokenBudget(
        scope_id="s1",
        max_input_tokens=10000,
        max_output_tokens=5000,
        max_total_tokens=10000,
    )
    budget.consume(input_tokens=8100)
    assert budget.status == BudgetStatus.WARNING


def test_budget_exhausted():
    budget = TokenBudget(
        scope_id="s1",
        max_input_tokens=10000,
        max_output_tokens=5000,
        max_total_tokens=10000,
    )
    budget.consume(input_tokens=10000)
    assert budget.status == BudgetStatus.EXHAUSTED


def test_budget_reset():
    budget = TokenBudget(
        scope_id="s1",
        max_input_tokens=1000,
        max_output_tokens=500,
        max_total_tokens=1500,
    )
    budget.consume(input_tokens=500, output_tokens=200)
    budget.reset()
    assert budget.used_total == 0
    assert budget.status == BudgetStatus.OK


def test_budget_usage_pct():
    budget = TokenBudget(
        scope_id="s1",
        max_input_tokens=10000,
        max_output_tokens=5000,
        max_total_tokens=10000,
    )
    budget.consume(input_tokens=5000)
    assert budget.usage_pct == 0.5


# ---------------------------------------------------------------------------
# Cost estimation
# ---------------------------------------------------------------------------


def test_estimate_cost_known_model():
    cost = estimate_cost("claude-opus-4-6", 1000, 1000)
    # Input: 1K * 0.015 = 0.015, Output: 1K * 0.075 = 0.075
    assert cost == 0.09


def test_estimate_cost_cheap_model():
    cost = estimate_cost("gemini-2.0-flash", 10000, 1000)
    # Input: 10K * 0.0001 = 0.001, Output: 1K * 0.0004 = 0.0004
    assert cost == 0.0014


def test_estimate_cost_unknown_model():
    cost = estimate_cost("unknown-model", 1000, 1000)
    # Uses default mid-range pricing
    assert cost > 0


# ---------------------------------------------------------------------------
# CostTracker tests
# ---------------------------------------------------------------------------


def test_cost_tracker_record():
    tracker = CostTracker()
    usage = tracker.record(
        model="claude-sonnet-4-5-20250929",
        input_tokens=1000,
        output_tokens=500,
        agent_id="pr_alice_dev",
        session_id="session_1",
    )
    assert usage.cost_usd > 0
    assert tracker.usage_count() == 1
    assert tracker.total_tokens == 1500


def test_cost_tracker_totals():
    tracker = CostTracker()
    tracker.record("claude-opus-4-6", 1000, 1000)
    tracker.record("gemini-2.0-flash", 5000, 1000)

    assert tracker.usage_count() == 2
    assert tracker.total_cost > 0
    assert tracker.total_tokens == 8000


def test_cost_tracker_by_model():
    tracker = CostTracker()
    tracker.record("claude-opus-4-6", 1000, 1000)
    tracker.record("claude-opus-4-6", 1000, 1000)
    tracker.record("gemini-2.0-flash", 1000, 1000)

    by_model = tracker.cost_by_model()
    assert "claude-opus-4-6" in by_model
    assert "gemini-2.0-flash" in by_model
    assert by_model["claude-opus-4-6"] > by_model["gemini-2.0-flash"]


def test_cost_tracker_by_agent():
    tracker = CostTracker()
    tracker.record("claude-opus-4-6", 1000, 1000, agent_id="alice")
    tracker.record("claude-opus-4-6", 2000, 2000, agent_id="alice")
    tracker.record("claude-opus-4-6", 500, 500, agent_id="bob")

    by_agent = tracker.cost_by_agent()
    assert by_agent["alice"] > by_agent["bob"]


def test_cost_tracker_by_session():
    tracker = CostTracker()
    tracker.record("claude-opus-4-6", 1000, 1000, session_id="s1")
    tracker.record("claude-opus-4-6", 1000, 1000, session_id="s1")
    tracker.record("claude-opus-4-6", 1000, 1000, session_id="s2")

    by_session = tracker.cost_by_session()
    assert len(by_session) == 2
    assert by_session["s1"] > by_session["s2"]


def test_cost_tracker_with_budget():
    tracker = CostTracker()
    budget = TokenBudget(
        scope_id="session_1",
        max_input_tokens=2000,
        max_output_tokens=1000,
        max_total_tokens=3000,
    )
    tracker.set_budget(budget)

    tracker.record("claude-opus-4-6", 1000, 500, session_id="session_1")
    assert tracker.check_budget("session_1") == BudgetStatus.OK

    tracker.record("claude-opus-4-6", 1000, 400, session_id="session_1")
    assert tracker.check_budget("session_1") == BudgetStatus.WARNING


def test_cost_tracker_no_budget():
    tracker = CostTracker()
    assert tracker.check_budget("nonexistent") == BudgetStatus.OK


def test_cost_tracker_report():
    tracker = CostTracker()
    tracker.record("claude-opus-4-6", 1000, 1000, agent_id="alice", session_id="s1")
    tracker.record("gemini-2.0-flash", 5000, 1000, agent_id="bob", session_id="s1")

    budget = TokenBudget(
        scope_id="s1",
        max_input_tokens=100000,
        max_output_tokens=50000,
        max_total_tokens=150000,
    )
    tracker.set_budget(budget)

    report = tracker.generate_report()
    assert "FINOPS" in report
    assert "Total cost" in report
    assert "claude-opus-4-6" in report
    assert "gemini-2.0-flash" in report
    assert "alice" in report
    assert "Budget Status" in report


# ---------------------------------------------------------------------------
# ModelRouter tests
# ---------------------------------------------------------------------------


def test_model_router_synthesis():
    router = ModelRouter()
    model = router.select_model("synthesis")
    assert "opus" in model or "pro" in model  # Should pick frontier


def test_model_router_deliberation():
    router = ModelRouter()
    model = router.select_model("deliberation")
    config = router.get_model_config(model)
    assert config is not None
    assert config.tier == ModelTier.STANDARD


def test_model_router_review():
    router = ModelRouter()
    model = router.select_model("review")
    config = router.get_model_config(model)
    assert config is not None
    assert config.tier == ModelTier.FAST


def test_model_router_budget_downgrade():
    tracker = CostTracker()
    budget = TokenBudget(
        scope_id="session_1",
        max_input_tokens=10000,
        max_output_tokens=5000,
        max_total_tokens=10000,
        hard=False,  # Soft limit for testing
    )
    tracker.set_budget(budget)
    budget.consume(input_tokens=8500)  # >80% = WARNING

    router = ModelRouter(cost_tracker=tracker)
    # Synthesis normally picks frontier, but budget warning should downgrade
    model = router.select_model("synthesis", budget_scope="session_1")
    config = router.get_model_config(model)
    assert config is not None
    assert config.tier == ModelTier.STANDARD  # Downgraded from FRONTIER


def test_model_router_budget_exhausted():
    tracker = CostTracker()
    budget = TokenBudget(
        scope_id="session_1",
        max_input_tokens=100,
        max_output_tokens=50,
        max_total_tokens=100,
        hard=False,
    )
    tracker.set_budget(budget)
    budget.consume(input_tokens=100)  # Exhausted

    router = ModelRouter(cost_tracker=tracker)
    model = router.select_model("synthesis", budget_scope="session_1")
    assert model == ""  # No model — budget exhausted


def test_model_router_preferred_vendor():
    router = ModelRouter()
    model = router.select_model("deliberation", preferred_vendor="gemini")
    assert "gemini" in model


def test_model_router_available_models():
    router = ModelRouter()
    models = router.available_models()
    assert len(models) >= 5


def test_model_router_models_by_tier():
    router = ModelRouter()
    frontier = router.models_by_tier(ModelTier.FRONTIER)
    assert len(frontier) >= 1
    fast = router.models_by_tier(ModelTier.FAST)
    assert len(fast) >= 2
