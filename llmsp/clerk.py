"""The Clerk — non-generative synthesis engine.

The Clerk is a *typesetter*, not an editor. It takes the outputs of council
deliberation and produces a structured synthesis WITHOUT introducing novel
content. This is the hardest constraint in the system.

The Clerk:
- Collects and orders agent responses
- Identifies areas of agreement and disagreement
- Extracts decisions, claims, and action items
- Produces a structured summary faithful to the source events
- NEVER generates new claims, opinions, or content
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from llmsp.models import (
    BlockType,
    ClaimBlock,
    ContentBlock,
    DecisionBlock,
    EventType,
    SignedEvent,
    TaskBlock,
    TextBlock,
)
from llmsp.principal import AgentPrincipal


@dataclass
class SynthesisResult:
    """The Clerk's structured output from council deliberation."""

    channel_id: str
    summary_blocks: list[ContentBlock]
    agreements: list[str]
    disagreements: list[Disagreement]
    decisions: list[DecisionBlock]
    action_items: list[TaskBlock]
    participating_agents: list[str]
    source_event_ids: list[str]


@dataclass
class Disagreement:
    """A point of disagreement between agents."""

    topic: str
    positions: dict[str, str]  # agent_id -> their position


class Clerk:
    """Non-generative synthesis engine.

    Processes council deliberation events and produces a faithful synthesis.
    The Clerk operates under strict constraints: it may only reorganize,
    categorize, and reference content from source events — never introduce
    novel content.
    """

    def __init__(self, principal: AgentPrincipal) -> None:
        self._principal = principal

    def synthesize(
        self,
        events: list[SignedEvent],
        channel_id: str,
    ) -> SynthesisResult:
        """Synthesize a list of deliberation events into structured output.

        This is the core non-generative synthesis. Every piece of output
        is traceable to a source event.
        """
        agreements: list[str] = []
        disagreements: list[Disagreement] = []
        decisions: list[DecisionBlock] = []
        action_items: list[TaskBlock] = []
        agent_claims: dict[str, list[str]] = {}
        participating: set[str] = set()
        source_ids: list[str] = []

        for event in events:
            participating.add(event.author_id)
            source_ids.append(event.event_id)

            for block in event.blocks:
                if isinstance(block, ClaimBlock):
                    agent_claims.setdefault(event.author_id, []).append(block.claim)
                elif isinstance(block, DecisionBlock):
                    decisions.append(block)
                elif isinstance(block, TaskBlock):
                    action_items.append(block)

        # Identify agreements: claims made by multiple agents
        if len(agent_claims) > 1:
            all_claims_by_text: dict[str, set[str]] = {}
            for agent_id, claims in agent_claims.items():
                for claim in claims:
                    normalized = claim.strip().lower()
                    all_claims_by_text.setdefault(normalized, set()).add(agent_id)

            for claim_text, agents in all_claims_by_text.items():
                if len(agents) > 1:
                    agreements.append(claim_text)

        # Identify disagreements via objection events
        objections = [e for e in events if e.event_type == EventType.OBJECTION]
        for obj in objections:
            if obj.parent_event_id:
                parent = next(
                    (e for e in events if e.event_id == obj.parent_event_id),
                    None,
                )
                if parent:
                    obj_text = _extract_text(obj.blocks)
                    parent_text = _extract_text(parent.blocks)
                    if obj_text and parent_text:
                        disagreements.append(
                            Disagreement(
                                topic=parent_text[:120],
                                positions={
                                    parent.author_id: parent_text,
                                    obj.author_id: obj_text,
                                },
                            )
                        )

        # Build summary blocks (non-generative: just structuring what exists)
        summary_blocks: list[ContentBlock] = []

        if agreements:
            summary_blocks.append(
                TextBlock(content="Points of agreement:\n" + "\n".join(f"- {a}" for a in agreements))
            )

        if disagreements:
            lines = []
            for d in disagreements:
                lines.append(f"- {d.topic}")
                for agent_id, pos in d.positions.items():
                    lines.append(f"  [{agent_id}]: {pos}")
            summary_blocks.append(
                TextBlock(content="Points of disagreement:\n" + "\n".join(lines))
            )

        if decisions:
            summary_blocks.append(
                TextBlock(
                    content="Decisions reached:\n"
                    + "\n".join(f"- {d.decision} (rationale: {d.rationale})" for d in decisions)
                )
            )

        if action_items:
            summary_blocks.append(
                TextBlock(
                    content="Action items:\n"
                    + "\n".join(
                        f"- {t.task}" + (f" [assigned: {t.assignee}]" if t.assignee else "")
                        for t in action_items
                    )
                )
            )

        if not summary_blocks:
            # Even if there's nothing structured, summarize what we saw
            msg_count = sum(1 for e in events if e.event_type == EventType.MESSAGE)
            summary_blocks.append(
                TextBlock(
                    content=f"Council deliberation: {msg_count} messages from {len(participating)} agents. "
                    f"No structured claims, decisions, or action items were extracted."
                )
            )

        return SynthesisResult(
            channel_id=channel_id,
            summary_blocks=summary_blocks,
            agreements=agreements,
            disagreements=disagreements,
            decisions=decisions,
            action_items=action_items,
            participating_agents=sorted(participating),
            source_event_ids=source_ids,
        )

    def emit_synthesis_event(
        self,
        result: SynthesisResult,
    ) -> SignedEvent:
        """Turn a SynthesisResult into a signed event for the ledger."""
        return self._principal.create_event(
            channel_id=result.channel_id,
            event_type=EventType.DECISION,
            blocks=result.summary_blocks,
        )


def _extract_text(blocks: list[ContentBlock]) -> str:
    """Pull the first text content from a list of blocks."""
    for block in blocks:
        if isinstance(block, TextBlock):
            return block.content
        if isinstance(block, ClaimBlock):
            return block.claim
    return ""
