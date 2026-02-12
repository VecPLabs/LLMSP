"""Constrained Clerk prompts for LLM-powered synthesis.

The Clerk prompt is the hardest part of the entire LLMSP stack. It must
constrain the LLM to be a TYPESETTER — reorganizing and structuring content
from source events without hallucinating novel claims or opinions.

This module provides the system prompts and an LLM-powered Clerk that
uses them, alongside the existing deterministic Clerk.
"""

from __future__ import annotations

from typing import Optional

from llmsp.adapters.base import BaseAdapter
from llmsp.clerk import Clerk, Disagreement, SynthesisResult, _extract_text
from llmsp.models import (
    ClaimBlock,
    ContentBlock,
    DecisionBlock,
    EventType,
    SignedEvent,
    TaskBlock,
    TextBlock,
)
from llmsp.principal import AgentPrincipal


# ---------------------------------------------------------------------------
# The Clerk System Prompt — the most constrained prompt in the stack
# ---------------------------------------------------------------------------

CLERK_SYSTEM_PROMPT = """\
You are THE CLERK of an LLMSP (LLM Swarm Protocol) council deliberation.

## YOUR ROLE
You are a TYPESETTER, not an editor. You ORGANIZE and STRUCTURE the outputs \
of a multi-agent deliberation. You NEVER introduce novel content.

## ABSOLUTE CONSTRAINTS — VIOLATION OF ANY IS A PROTOCOL FAILURE

1. **NO NOVEL CONTENT**: You must NEVER generate claims, opinions, analyses, \
or assertions that do not appear in the source events. Every statement in your \
output must be directly traceable to a specific agent's contribution.

2. **NO PARAPHRASING THAT CHANGES MEANING**: When summarizing, preserve the \
original meaning exactly. If you cannot summarize without risk of distortion, \
QUOTE DIRECTLY.

3. **NO EVALUATION**: You do not judge which agent is "right." You report \
positions faithfully. If Agent A says X and Agent B says Y, you report both \
without preference.

4. **NO GAP-FILLING**: If the agents did not address a topic, you do NOT \
address it. Silence in the source means silence in the synthesis.

5. **ATTRIBUTION IS MANDATORY**: Every claim, position, or recommendation \
must be attributed to the agent(s) who made it, using their agent_id.

## YOUR OUTPUT FORMAT

Respond with a JSON object containing these fields:
{
  "agreements": [
    {"claim": "text of agreed claim", "agents": ["agent_id_1", "agent_id_2"]}
  ],
  "disagreements": [
    {
      "topic": "subject of disagreement",
      "positions": {"agent_id_1": "their position", "agent_id_2": "their position"}
    }
  ],
  "decisions": [
    {"decision": "what was decided", "rationale": "why", "proposed_by": "agent_id"}
  ],
  "action_items": [
    {"task": "what needs to be done", "assignee": "agent_id or null", "proposed_by": "agent_id"}
  ],
  "unresolved": [
    "topic or question that was raised but not resolved"
  ],
  "summary": "A factual summary of the deliberation using ONLY content from the source events."
}

## SELF-CHECK

Before responding, verify:
- Does every statement trace to a source event? If not, DELETE IT.
- Did I introduce any novel analysis? If so, DELETE IT.
- Did I evaluate or rank agent positions? If so, REWRITE as neutral reporting.
- Did I fill in any gaps the agents left? If so, DELETE IT.

You are a mirror, not a lamp. Reflect, do not illuminate.
"""


# ---------------------------------------------------------------------------
# LLM-Powered Clerk
# ---------------------------------------------------------------------------


class LLMClerk(Clerk):
    """Clerk implementation that uses an LLM with the constrained prompt.

    Falls back to the deterministic Clerk for the structured extraction,
    then optionally enhances with LLM-generated natural language synthesis
    (still under the strict non-generative constraint).
    """

    def __init__(
        self,
        principal: AgentPrincipal,
        adapter: BaseAdapter,
    ) -> None:
        super().__init__(principal)
        self._adapter = adapter

    async def synthesize_with_llm(
        self,
        events: list[SignedEvent],
        channel_id: str,
    ) -> SynthesisResult:
        """Synthesize using both deterministic extraction and LLM structuring.

        1. Run deterministic synthesis first (guaranteed non-generative)
        2. Format events for the LLM
        3. Ask the LLM to produce a structured synthesis under constraint
        4. Merge LLM output with deterministic results
        """
        # Step 1: Deterministic baseline
        baseline = self.synthesize(events, channel_id)

        if not events:
            return baseline

        # Step 2: Format events for the LLM
        event_text = self._format_events_for_clerk(events)

        # Step 3: LLM synthesis under constraint
        user_prompt = (
            f"=== COUNCIL DELIBERATION EVENTS ===\n\n"
            f"{event_text}\n\n"
            f"=== END OF EVENTS ===\n\n"
            f"Synthesize this deliberation following your constraints exactly. "
            f"Remember: you are a typesetter. Report only what the agents said."
        )

        result = await self._adapter._call_api(CLERK_SYSTEM_PROMPT, user_prompt)
        self._adapter.last_usage = result
        raw = result.text

        # Step 4: Parse LLM output and merge with baseline
        import json
        import re

        llm_summary_text = ""
        json_match = re.search(r'\{.*\}', raw.strip(), re.DOTALL)
        if json_match:
            try:
                data = json.loads(json_match.group())
                llm_summary_text = data.get("summary", "")

                # Merge any additional agreements found by LLM
                for agreement in data.get("agreements", []):
                    claim_text = agreement.get("claim", "").strip().lower()
                    if claim_text and claim_text not in baseline.agreements:
                        baseline.agreements.append(claim_text)

                # Merge unresolved items as text blocks
                unresolved = data.get("unresolved", [])
                if unresolved:
                    baseline.summary_blocks.append(
                        TextBlock(
                            content="Unresolved items:\n"
                            + "\n".join(f"- {u}" for u in unresolved)
                        )
                    )
            except (json.JSONDecodeError, Exception):
                llm_summary_text = raw.strip()

        # Add LLM summary if it exists (attributed to the Clerk)
        if llm_summary_text:
            baseline.summary_blocks.insert(
                0,
                TextBlock(content=f"Synthesis (by Clerk): {llm_summary_text}"),
            )

        return baseline

    def _format_events_for_clerk(self, events: list[SignedEvent]) -> str:
        """Format events for the Clerk LLM prompt."""
        lines = []
        for event in events:
            author = event.author_id
            etype = event.event_type.value
            parent = f" (replying to {event.parent_event_id})" if event.parent_event_id else ""
            lines.append(f"[{etype}] {author}{parent}:")

            for block in event.blocks:
                if isinstance(block, TextBlock):
                    lines.append(f"  {block.content}")
                elif isinstance(block, ClaimBlock):
                    lines.append(
                        f"  CLAIM (confidence={block.confidence}): {block.claim}"
                    )
                    if block.evidence:
                        lines.append(f"    Evidence: {', '.join(block.evidence)}")
                elif isinstance(block, DecisionBlock):
                    lines.append(f"  DECISION: {block.decision}")
                    lines.append(f"    Rationale: {block.rationale}")
                elif isinstance(block, TaskBlock):
                    lines.append(
                        f"  TASK: {block.task}"
                        + (f" (assigned: {block.assignee})" if block.assignee else "")
                    )
            lines.append("")

        return "\n".join(lines)
