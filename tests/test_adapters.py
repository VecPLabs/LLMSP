"""Tests for LLMSP adapter base class and response parsing."""

import json
from typing import Optional

from llmsp.adapters.base import ApiResult, BaseAdapter
from llmsp.models import (
    ClaimBlock,
    CodeBlock,
    ContentBlock,
    DecisionBlock,
    EventType,
    SignedEvent,
    TaskBlock,
    TextBlock,
)
from llmsp.principal import AgentPrincipal


# ---------------------------------------------------------------------------
# Stub adapter for testing (no real API calls)
# ---------------------------------------------------------------------------


class MockAdapter(BaseAdapter):
    """Adapter that returns canned responses for testing."""

    def __init__(self, response: str, input_tokens: int = 100, output_tokens: int = 50):
        super().__init__(model="mock", api_key="mock")
        self._response = response
        self._input_tokens = input_tokens
        self._output_tokens = output_tokens

    async def _call_api(self, system_prompt: str, user_prompt: str) -> ApiResult:
        return ApiResult(
            text=self._response,
            input_tokens=self._input_tokens,
            output_tokens=self._output_tokens,
        )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


import asyncio


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def test_parse_json_array():
    response = json.dumps([
        {"block_type": "text", "content": "Hello from mock"},
        {"block_type": "claim", "claim": "X is true", "confidence": 0.9, "evidence": ["test"]},
    ])
    adapter = MockAdapter(response)
    agent = AgentPrincipal("Test", "dev")

    blocks = _run(adapter.generate(agent, "test query", []))
    assert len(blocks) == 2
    assert isinstance(blocks[0], TextBlock)
    assert isinstance(blocks[1], ClaimBlock)
    assert blocks[1].confidence == 0.9


def test_parse_single_json_object():
    response = json.dumps({"block_type": "text", "content": "single block"})
    adapter = MockAdapter(response)
    agent = AgentPrincipal("Test", "dev")

    blocks = _run(adapter.generate(agent, "query", []))
    assert len(blocks) == 1
    assert isinstance(blocks[0], TextBlock)


def test_parse_code_block():
    response = json.dumps([
        {"block_type": "code", "language": "python", "source": "print('hi')", "description": "greeting"},
    ])
    adapter = MockAdapter(response)
    agent = AgentPrincipal("Test", "dev")

    blocks = _run(adapter.generate(agent, "query", []))
    assert len(blocks) == 1
    assert isinstance(blocks[0], CodeBlock)
    assert blocks[0].language == "python"


def test_parse_task_block():
    response = json.dumps([
        {"block_type": "task", "task": "implement feature", "assignee": "pr_alice_dev", "status": "proposed"},
    ])
    adapter = MockAdapter(response)
    agent = AgentPrincipal("Test", "dev")

    blocks = _run(adapter.generate(agent, "query", []))
    assert len(blocks) == 1
    assert isinstance(blocks[0], TaskBlock)


def test_parse_decision_block():
    response = json.dumps([
        {"block_type": "decision", "decision": "use Ed25519", "rationale": "faster", "dissenters": []},
    ])
    adapter = MockAdapter(response)
    agent = AgentPrincipal("Test", "dev")

    blocks = _run(adapter.generate(agent, "query", []))
    assert len(blocks) == 1
    assert isinstance(blocks[0], DecisionBlock)


def test_fallback_to_text_on_invalid_json():
    adapter = MockAdapter("This is just plain text, not JSON at all!")
    agent = AgentPrincipal("Test", "dev")

    blocks = _run(adapter.generate(agent, "query", []))
    assert len(blocks) == 1
    assert isinstance(blocks[0], TextBlock)
    assert "plain text" in blocks[0].content


def test_review_agree():
    response = json.dumps({"agree": True})
    adapter = MockAdapter(response)
    agent = AgentPrincipal("Reviewer", "sec")

    proposal = AgentPrincipal("Proposer", "dev").create_event(
        "ch1", EventType.MESSAGE, [TextBlock(content="proposal")]
    )

    result = _run(adapter.review(agent, "query", proposal, []))
    assert result is None  # Agreement


def test_review_object():
    response = json.dumps({
        "agree": False,
        "blocks": [{"block_type": "text", "content": "I disagree because..."}],
    })
    adapter = MockAdapter(response)
    agent = AgentPrincipal("Reviewer", "sec")

    proposal = AgentPrincipal("Proposer", "dev").create_event(
        "ch1", EventType.MESSAGE, [TextBlock(content="proposal")]
    )

    result = _run(adapter.review(agent, "query", proposal, []))
    assert result is not None
    assert len(result) == 1
    assert isinstance(result[0], TextBlock)


def test_format_context():
    adapter = MockAdapter("")
    p = AgentPrincipal("Alice", "dev")

    events = [
        p.create_event("ch1", EventType.MESSAGE, [TextBlock(content="prior context")]),
        p.create_event("ch1", EventType.MESSAGE, [ClaimBlock(claim="X is true", confidence=0.8)]),
    ]

    formatted = adapter._format_context(events)
    assert "prior context" in formatted
    assert "X is true" in formatted
    assert "pr_alice_dev" in formatted


def test_last_usage_tracked_after_generate():
    response = json.dumps([{"block_type": "text", "content": "Hello"}])
    adapter = MockAdapter(response, input_tokens=250, output_tokens=100)
    agent = AgentPrincipal("Test", "dev")

    _run(adapter.generate(agent, "test", []))
    assert adapter.last_usage is not None
    assert adapter.last_usage.input_tokens == 250
    assert adapter.last_usage.output_tokens == 100


def test_last_usage_tracked_after_review():
    response = json.dumps({"agree": True})
    adapter = MockAdapter(response, input_tokens=300, output_tokens=50)
    agent = AgentPrincipal("Test", "sec")
    proposal = AgentPrincipal("Other", "dev").create_event(
        "ch1", EventType.MESSAGE, [TextBlock(content="proposal")]
    )

    _run(adapter.review(agent, "query", proposal, []))
    assert adapter.last_usage is not None
    assert adapter.last_usage.input_tokens == 300
    assert adapter.last_usage.output_tokens == 50


def test_format_proposal():
    adapter = MockAdapter("")
    p = AgentPrincipal("Alice", "dev")

    proposal = p.create_event(
        "ch1",
        EventType.MESSAGE,
        [
            TextBlock(content="my proposal"),
            ClaimBlock(claim="this will work", confidence=0.9, evidence=["tests"]),
        ],
    )

    formatted = adapter._format_proposal(proposal)
    assert "my proposal" in formatted
    assert "this will work" in formatted
    assert "pr_alice_dev" in formatted
