"""Tests for the LLMSP Red Team SafeEval Agent."""

from llmsp.event_store import EventStore
from llmsp.models import ClaimBlock, EventType, TextBlock
from llmsp.principal import AgentPrincipal, PrincipalRegistry
from llmsp.red_team import (
    AttackCategory,
    BehaviorAnalyzer,
    SafeEvalRunner,
    _generate_claim_inflation_tests,
    _generate_context_manipulation_tests,
    _generate_decision_poisoning_tests,
    _generate_injection_tests,
)
from llmsp.security_auditor import SecurityAuditor, ThreatSeverity


# ---------------------------------------------------------------------------
# Attack generator tests
# ---------------------------------------------------------------------------


def test_injection_tests_generated():
    attacker = AgentPrincipal("Red", "attacker")
    tests = _generate_injection_tests(attacker, "test_ch")
    assert len(tests) >= 9
    assert all(t.category == AttackCategory.PROMPT_INJECTION for t in tests)
    # Difficulty should span 1-9+
    difficulties = {t.difficulty for t in tests}
    assert min(difficulties) <= 2
    assert max(difficulties) >= 8


def test_claim_inflation_tests():
    attacker = AgentPrincipal("Red", "attacker")
    tests = _generate_claim_inflation_tests(attacker, "test_ch")
    assert len(tests) >= 3
    assert all(t.category == AttackCategory.CLAIM_INFLATION for t in tests)


def test_decision_poisoning_tests():
    attacker = AgentPrincipal("Red", "attacker")
    tests = _generate_decision_poisoning_tests(attacker, "test_ch")
    assert len(tests) >= 3
    assert all(t.category == AttackCategory.DECISION_POISONING for t in tests)


def test_context_manipulation_tests():
    attacker = AgentPrincipal("Red", "attacker")
    tests = _generate_context_manipulation_tests(attacker, "test_ch")
    assert len(tests) >= 2
    assert all(t.category == AttackCategory.CONTEXT_MANIPULATION for t in tests)


# ---------------------------------------------------------------------------
# SafeEvalRunner tests
# ---------------------------------------------------------------------------


def test_runner_generates_suite():
    store = EventStore()
    registry = PrincipalRegistry()
    auditor = SecurityAuditor(store, registry=registry)
    runner = SafeEvalRunner(store, auditor)

    suite = runner.generate_test_suite()
    assert len(suite) > 0
    categories = {t.category for t in suite}
    assert AttackCategory.PROMPT_INJECTION in categories


def test_runner_generates_specific_categories():
    store = EventStore()
    auditor = SecurityAuditor(store)
    runner = SafeEvalRunner(store, auditor)

    suite = runner.generate_test_suite(
        categories=[AttackCategory.PROMPT_INJECTION]
    )
    assert all(t.category == AttackCategory.PROMPT_INJECTION for t in suite)


def test_runner_evaluation():
    store = EventStore()
    registry = PrincipalRegistry()
    auditor = SecurityAuditor(store, registry=registry)
    runner = SafeEvalRunner(store, auditor)

    report = runner.run_evaluation()

    assert report.total_tests > 0
    assert report.detection_rate >= 0.0
    assert report.detection_rate <= 1.0
    assert report.detected + report.missed == report.total_tests


def test_runner_detects_obvious_injections():
    store = EventStore()
    registry = PrincipalRegistry()
    auditor = SecurityAuditor(store, registry=registry)
    runner = SafeEvalRunner(store, auditor)

    # Only test injection category
    suite = runner.generate_test_suite(categories=[AttackCategory.PROMPT_INJECTION])
    report = runner.run_evaluation(test_suite=suite)

    # Should catch all 9 injection levels now
    assert report.detected >= 8


def test_runner_detects_decision_poisoning():
    store = EventStore()
    auditor = SecurityAuditor(store)
    runner = SafeEvalRunner(store, auditor)

    suite = runner.generate_test_suite(categories=[AttackCategory.DECISION_POISONING])
    report = runner.run_evaluation(test_suite=suite)

    assert report.detected >= 3


def test_runner_detects_context_manipulation():
    store = EventStore()
    auditor = SecurityAuditor(store)
    runner = SafeEvalRunner(store, auditor)

    suite = runner.generate_test_suite(categories=[AttackCategory.CONTEXT_MANIPULATION])
    report = runner.run_evaluation(test_suite=suite)

    assert report.detected >= 2


def test_runner_overall_detection_rate():
    """After hardening, overall detection rate should be >= 80%."""
    store = EventStore()
    auditor = SecurityAuditor(store)
    runner = SafeEvalRunner(store, auditor)

    report = runner.run_evaluation()
    assert report.detection_rate >= 0.80, (
        f"Detection rate {report.detection_rate:.1%} is below 80% target"
    )


def test_runner_report_has_categories():
    store = EventStore()
    auditor = SecurityAuditor(store)
    runner = SafeEvalRunner(store, auditor)

    report = runner.run_evaluation()
    assert len(report.results_by_category) > 0
    for cat, stats in report.results_by_category.items():
        assert "total" in stats
        assert "detected" in stats
        assert "missed" in stats


def test_runner_report_has_difficulty():
    store = EventStore()
    auditor = SecurityAuditor(store)
    runner = SafeEvalRunner(store, auditor)

    report = runner.run_evaluation()
    assert len(report.difficulty_distribution) > 0


def test_runner_report_has_recommendations():
    store = EventStore()
    auditor = SecurityAuditor(store)
    runner = SafeEvalRunner(store, auditor)

    report = runner.run_evaluation()
    assert len(report.recommendations) > 0


def test_runner_format_report():
    store = EventStore()
    auditor = SecurityAuditor(store)
    runner = SafeEvalRunner(store, auditor)

    report = runner.run_evaluation()
    text = runner.format_report(report)

    assert "RED TEAM" in text
    assert "Detection rate" in text
    assert "By Category" in text
    assert "By Difficulty" in text
    assert "Recommendations" in text


def test_runner_history():
    store = EventStore()
    auditor = SecurityAuditor(store)
    runner = SafeEvalRunner(store, auditor)

    runner.run_evaluation()
    runner.run_evaluation()

    assert len(runner.history) == 2


# ---------------------------------------------------------------------------
# BehaviorAnalyzer tests
# ---------------------------------------------------------------------------


def test_behavior_analyzer_empty():
    store = EventStore()
    analyzer = BehaviorAnalyzer(store)
    patterns = analyzer.analyze_agent("nonexistent")
    assert patterns == []


def test_behavior_analyzer_always_agrees():
    store = EventStore()
    agent = AgentPrincipal("YesMan", "dev")

    # Create 6 messages, 0 objections
    for i in range(6):
        event = agent.create_event("ch1", EventType.MESSAGE, [TextBlock(content=f"I agree {i}")])
        store.append(event)

    analyzer = BehaviorAnalyzer(store)
    patterns = analyzer.analyze_agent(agent.agent_id)

    pattern_types = [p.pattern_type for p in patterns]
    assert "always_agrees" in pattern_types


def test_behavior_analyzer_always_objects():
    store = EventStore()
    agent = AgentPrincipal("Contrarian", "sec")

    # 1 message, 4 objections
    msg = agent.create_event("ch1", EventType.MESSAGE, [TextBlock(content="Initial")])
    store.append(msg)

    for i in range(4):
        obj = agent.create_event(
            "ch1", EventType.OBJECTION,
            [TextBlock(content=f"I object {i}")],
            parent_event_id=msg.event_id,
        )
        store.append(obj)

    analyzer = BehaviorAnalyzer(store)
    patterns = analyzer.analyze_agent(agent.agent_id)

    pattern_types = [p.pattern_type for p in patterns]
    assert "always_objects" in pattern_types


def test_behavior_analyzer_unsupported_claims():
    store = EventStore()
    agent = AgentPrincipal("Bluffer", "expert")

    for i in range(4):
        event = agent.create_event("ch1", EventType.MESSAGE, [
            ClaimBlock(claim=f"Trust me claim {i}", confidence=0.95, evidence=[]),
        ])
        store.append(event)

    analyzer = BehaviorAnalyzer(store)
    patterns = analyzer.analyze_agent(agent.agent_id)

    pattern_types = [p.pattern_type for p in patterns]
    assert "unsupported_high_confidence" in pattern_types


def test_behavior_analyzer_all_agents():
    store = EventStore()
    a1 = AgentPrincipal("Alice", "dev")
    a2 = AgentPrincipal("Bob", "sec")

    for i in range(6):
        store.append(a1.create_event("ch1", EventType.MESSAGE, [TextBlock(content=f"msg {i}")]))
    for i in range(6):
        store.append(a2.create_event("ch1", EventType.MESSAGE, [TextBlock(content=f"msg {i}")]))

    analyzer = BehaviorAnalyzer(store)
    patterns = analyzer.analyze_all()

    # Both should be flagged as always_agrees
    agent_ids = {p.agent_id for p in patterns}
    assert a1.agent_id in agent_ids
    assert a2.agent_id in agent_ids
