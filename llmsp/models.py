"""Core data models for the LLMSP protocol.

Defines the atomic units: ContentBlocks and SignedEvents.
All events are immutable after creation. Content blocks carry
typed semantic payloads within events.
"""

from __future__ import annotations

import hashlib
import time
import uuid
from enum import Enum
from typing import Annotated, Literal, Optional, Union

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Content Blocks — structured semantic units inside events
# ---------------------------------------------------------------------------


class BlockType(str, Enum):
    TEXT = "text"
    CLAIM = "claim"
    CODE = "code"
    TASK = "task"
    DECISION = "decision"


class TextBlock(BaseModel):
    """General-purpose textual content."""

    block_type: Literal[BlockType.TEXT] = BlockType.TEXT
    content: str


class ClaimBlock(BaseModel):
    """A verifiable assertion made by an agent."""

    block_type: Literal[BlockType.CLAIM] = BlockType.CLAIM
    claim: str
    confidence: float = Field(ge=0.0, le=1.0, description="Self-reported confidence 0-1")
    evidence: list[str] = Field(default_factory=list, description="Supporting references")


class CodeBlock(BaseModel):
    """Executable or illustrative code content."""

    block_type: Literal[BlockType.CODE] = BlockType.CODE
    language: str
    source: str
    description: str = ""


class TaskBlock(BaseModel):
    """An action item or work unit."""

    block_type: Literal[BlockType.TASK] = BlockType.TASK
    task: str
    assignee: Optional[str] = None
    status: Literal["proposed", "accepted", "in_progress", "done", "rejected"] = "proposed"


class DecisionBlock(BaseModel):
    """A resolved outcome from deliberation."""

    block_type: Literal[BlockType.DECISION] = BlockType.DECISION
    decision: str
    rationale: str
    dissenters: list[str] = Field(default_factory=list)


ContentBlock = Annotated[
    Union[TextBlock, ClaimBlock, CodeBlock, TaskBlock, DecisionBlock],
    Field(discriminator="block_type"),
]


# ---------------------------------------------------------------------------
# Event Types
# ---------------------------------------------------------------------------


class EventType(str, Enum):
    MESSAGE = "message"
    OBJECTION = "objection"
    DECISION = "decision"
    REGISTRATION = "registration"
    COUNCIL_START = "council_start"
    COUNCIL_END = "council_end"


# ---------------------------------------------------------------------------
# Signed Event — the atomic unit of the protocol
# ---------------------------------------------------------------------------


def _make_event_id() -> str:
    return f"evt_{uuid.uuid4().hex[:16]}"


def _now() -> float:
    return time.time()


class SignedEvent(BaseModel):
    """The immutable atomic record of the LLMSP protocol.

    Every interaction, objection, and decision is captured as a signed event.
    Events are append-only — once created they cannot be modified.
    """

    event_id: str = Field(default_factory=_make_event_id)
    timestamp: float = Field(default_factory=_now)
    channel_id: str = Field(description="Logical channel / conversation this event belongs to")
    author_id: str = Field(description="Principal ID of the authoring agent")
    event_type: EventType
    blocks: list[ContentBlock]
    parent_event_id: Optional[str] = Field(
        default=None,
        description="ID of the event this is responding to (threading)",
    )
    signature_hex: str = Field(default="", description="Hex-encoded cryptographic signature")

    def payload_bytes(self) -> bytes:
        """Deterministic bytes used for signing / verification.

        Excludes signature_hex itself so the signature can be computed
        over the rest of the fields.
        """
        canonical = self.model_dump(exclude={"signature_hex"}, mode="json")
        raw = _canonical_json(canonical)
        return raw.encode("utf-8")

    def content_hash(self) -> str:
        """SHA-256 digest of the canonical payload."""
        return hashlib.sha256(self.payload_bytes()).hexdigest()


def _canonical_json(obj: object) -> str:
    """Produce a deterministic JSON string (sorted keys, no extra whitespace)."""
    import json

    return json.dumps(obj, sort_keys=True, separators=(",", ":"))
