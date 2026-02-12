"""Base adapter with shared logic for all LLM backends.

Handles event-to-prompt conversion, response parsing, and the review loop.
Subclasses only need to implement `_call_api()` for their specific backend.
"""

from __future__ import annotations

import json
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Optional

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
# System prompts
# ---------------------------------------------------------------------------

_AGENT_SYSTEM_PROMPT = """\
You are {agent_name}, a {agent_role} participating in a multi-agent council deliberation under the LLMSP (LLM Swarm Protocol).

Your responses MUST be structured as JSON arrays of content blocks. Each block has a "block_type" field.

Available block types:
- {{"block_type": "text", "content": "your analysis or commentary"}}
- {{"block_type": "claim", "claim": "a specific verifiable assertion", "confidence": 0.0-1.0, "evidence": ["references"]}}
- {{"block_type": "code", "language": "python", "source": "code here", "description": "what it does"}}
- {{"block_type": "task", "task": "action item description", "assignee": "agent_id or null", "status": "proposed"}}
- {{"block_type": "decision", "decision": "the resolved outcome", "rationale": "why", "dissenters": []}}

Respond with a JSON array of blocks. Be precise, cite evidence for claims, and assign confidence levels honestly.

Context from the event log will be provided. Reference prior events when relevant.
"""

_REVIEW_SYSTEM_PROMPT = """\
You are {agent_name}, a {agent_role} reviewing another agent's proposal in a council deliberation.

Your task: Review the proposal critically from your area of expertise ({agent_role}).

If you AGREE with the proposal, respond with exactly: {{"agree": true}}
If you OBJECT, respond with:
{{"agree": false, "blocks": [<array of content blocks explaining your objection>]}}

Only object if there is a substantive issue from your domain perspective. Minor style differences are not grounds for objection.
"""


# ---------------------------------------------------------------------------
# API result with token usage
# ---------------------------------------------------------------------------


@dataclass
class ApiResult:
    """Result from a single LLM API call, bundling text and token usage."""

    text: str
    input_tokens: int = 0
    output_tokens: int = 0


# ---------------------------------------------------------------------------
# Base Adapter
# ---------------------------------------------------------------------------


class BaseAdapter(ABC):
    """Abstract base for LLM backend adapters.

    Subclasses implement `_call_api()` for their specific provider.
    The base class handles prompt construction, response parsing,
    and the generate/review interface.
    """

    def __init__(
        self,
        model: str,
        api_key: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> None:
        self.model = model
        self.api_key = api_key
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.last_usage: Optional[ApiResult] = None

    @abstractmethod
    async def _call_api(
        self,
        system_prompt: str,
        user_prompt: str,
    ) -> ApiResult:
        """Make an API call to the LLM backend. Returns text + token usage."""
        ...

    def _format_context(self, context: list[SignedEvent]) -> str:
        """Format event log context into a readable prompt section."""
        if not context:
            return "No prior context available."

        lines = ["=== Event Log Context ==="]
        for event in context[-20:]:  # Last 20 events max
            author = event.author_id
            etype = event.event_type.value
            blocks_summary = []
            for block in event.blocks:
                if isinstance(block, TextBlock):
                    blocks_summary.append(f"[text] {block.content[:200]}")
                elif isinstance(block, ClaimBlock):
                    blocks_summary.append(
                        f"[claim, confidence={block.confidence}] {block.claim[:200]}"
                    )
                elif isinstance(block, CodeBlock):
                    blocks_summary.append(
                        f"[code:{block.language}] {block.description or block.source[:100]}"
                    )
                elif isinstance(block, TaskBlock):
                    blocks_summary.append(f"[task:{block.status}] {block.task[:200]}")
                elif isinstance(block, DecisionBlock):
                    blocks_summary.append(f"[decision] {block.decision[:200]}")

            content = " | ".join(blocks_summary) if blocks_summary else "(empty)"
            lines.append(f"[{etype}] {author}: {content}")

        return "\n".join(lines)

    def _format_proposal(self, proposal: SignedEvent) -> str:
        """Format a proposal event for review."""
        lines = [f"=== Proposal from {proposal.author_id} ==="]
        for block in proposal.blocks:
            if isinstance(block, TextBlock):
                lines.append(f"[text] {block.content}")
            elif isinstance(block, ClaimBlock):
                lines.append(f"[claim, confidence={block.confidence}] {block.claim}")
                if block.evidence:
                    lines.append(f"  evidence: {', '.join(block.evidence)}")
            elif isinstance(block, CodeBlock):
                lines.append(f"[code:{block.language}] {block.description}")
                lines.append(block.source)
            elif isinstance(block, TaskBlock):
                lines.append(f"[task] {block.task} (assignee: {block.assignee})")
            elif isinstance(block, DecisionBlock):
                lines.append(f"[decision] {block.decision}")
                lines.append(f"  rationale: {block.rationale}")
        return "\n".join(lines)

    def _parse_blocks(self, raw: str) -> list[ContentBlock]:
        """Parse LLM response into typed content blocks.

        Attempts JSON parsing first, falls back to wrapping as text.
        """
        # Try to extract JSON array from response
        raw_stripped = raw.strip()

        # Look for JSON array pattern
        json_match = re.search(r'\[.*\]', raw_stripped, re.DOTALL)
        if json_match:
            try:
                data = json.loads(json_match.group())
                if isinstance(data, list):
                    return [self._parse_single_block(item) for item in data]
            except (json.JSONDecodeError, Exception):
                pass

        # Try parsing as a single JSON object
        json_obj_match = re.search(r'\{.*\}', raw_stripped, re.DOTALL)
        if json_obj_match:
            try:
                data = json.loads(json_obj_match.group())
                if isinstance(data, dict):
                    return [self._parse_single_block(data)]
            except (json.JSONDecodeError, Exception):
                pass

        # Fallback: wrap the entire response as a text block
        return [TextBlock(content=raw_stripped)]

    def _parse_single_block(self, data: dict[str, Any]) -> ContentBlock:
        """Parse a single block dict into a typed ContentBlock."""
        block_type = data.get("block_type", "text")

        if block_type == "claim":
            return ClaimBlock(
                claim=data.get("claim", ""),
                confidence=float(data.get("confidence", 0.5)),
                evidence=data.get("evidence", []),
            )
        elif block_type == "code":
            return CodeBlock(
                language=data.get("language", "text"),
                source=data.get("source", ""),
                description=data.get("description", ""),
            )
        elif block_type == "task":
            return TaskBlock(
                task=data.get("task", ""),
                assignee=data.get("assignee"),
                status=data.get("status", "proposed"),
            )
        elif block_type == "decision":
            return DecisionBlock(
                decision=data.get("decision", ""),
                rationale=data.get("rationale", ""),
                dissenters=data.get("dissenters", []),
            )
        else:
            return TextBlock(content=data.get("content", str(data)))

    async def generate(
        self,
        agent: AgentPrincipal,
        query: str,
        context: list[SignedEvent],
    ) -> list[ContentBlock]:
        """Generate response blocks for a query with context."""
        system = _AGENT_SYSTEM_PROMPT.format(
            agent_name=agent.name,
            agent_role=agent.role,
        )
        context_text = self._format_context(context)
        user_prompt = f"{context_text}\n\n=== Current Query ===\n{query}\n\nRespond with a JSON array of content blocks."

        result = await self._call_api(system, user_prompt)
        self.last_usage = result
        return self._parse_blocks(result.text)

    async def review(
        self,
        agent: AgentPrincipal,
        query: str,
        proposal: SignedEvent,
        context: list[SignedEvent],
    ) -> Optional[list[ContentBlock]]:
        """Review a proposal. Returns objection blocks or None if agreed."""
        system = _REVIEW_SYSTEM_PROMPT.format(
            agent_name=agent.name,
            agent_role=agent.role,
        )
        context_text = self._format_context(context)
        proposal_text = self._format_proposal(proposal)
        user_prompt = (
            f"{context_text}\n\n{proposal_text}\n\n"
            f"Original query: {query}\n\n"
            f"Do you agree or object? Respond with JSON."
        )

        result = await self._call_api(system, user_prompt)
        self.last_usage = result
        raw = result.text

        # Parse agreement/objection
        try:
            json_match = re.search(r'\{.*\}', raw.strip(), re.DOTALL)
            if json_match:
                data = json.loads(json_match.group())
                if data.get("agree", True):
                    return None
                if "blocks" in data and isinstance(data["blocks"], list):
                    return [self._parse_single_block(b) for b in data["blocks"]]
                return [TextBlock(content=raw.strip())]
        except (json.JSONDecodeError, Exception):
            pass

        # If we can't parse, assume agreement
        return None
