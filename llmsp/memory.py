"""Agent Memory — persistent cross-session knowledge for LLMSP agents.

Each agent accumulates knowledge across council sessions:
- Facts learned (claims with high confidence that went unchallenged)
- Positions taken (the agent's own claims and decisions)
- Interactions (who agreed/disagreed with this agent, and on what)
- Skills (topics the agent has demonstrated competence in)

Memory is stored in SQLite per-agent and injected into the adapter's
context window to give agents continuity across deliberations.
"""

from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional

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


# ---------------------------------------------------------------------------
# Memory types
# ---------------------------------------------------------------------------


class MemoryType(str, Enum):
    FACT = "fact"           # Learned from other agents (unchallenged claims)
    POSITION = "position"   # This agent's own claims/decisions
    INTERACTION = "interaction"  # Who agreed/disagreed and on what
    SKILL = "skill"         # Topics demonstrated competence in
    INSIGHT = "insight"     # Cross-session observations


@dataclass
class MemoryEntry:
    """A single memory stored for an agent."""

    memory_id: str
    agent_id: str
    memory_type: MemoryType
    content: str
    source_event_id: Optional[str] = None
    source_session_id: Optional[str] = None
    confidence: float = 1.0
    created_at: float = field(default_factory=time.time)
    access_count: int = 0
    last_accessed: float = field(default_factory=time.time)
    tags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "memory_id": self.memory_id,
            "agent_id": self.agent_id,
            "memory_type": self.memory_type.value,
            "content": self.content,
            "source_event_id": self.source_event_id,
            "source_session_id": self.source_session_id,
            "confidence": self.confidence,
            "created_at": self.created_at,
            "access_count": self.access_count,
            "last_accessed": self.last_accessed,
            "tags": self.tags,
        }

    @classmethod
    def from_dict(cls, data: dict) -> MemoryEntry:
        data["memory_type"] = MemoryType(data["memory_type"])
        return cls(**data)


# ---------------------------------------------------------------------------
# Memory Store (SQLite-backed)
# ---------------------------------------------------------------------------

_MEMORY_SCHEMA = """\
CREATE TABLE IF NOT EXISTS memories (
    memory_id        TEXT PRIMARY KEY,
    agent_id         TEXT NOT NULL,
    memory_type      TEXT NOT NULL,
    content          TEXT NOT NULL,
    source_event_id  TEXT,
    source_session_id TEXT,
    confidence       REAL NOT NULL DEFAULT 1.0,
    created_at       REAL NOT NULL,
    access_count     INTEGER NOT NULL DEFAULT 0,
    last_accessed    REAL NOT NULL,
    tags_json        TEXT NOT NULL DEFAULT '[]'
);

CREATE INDEX IF NOT EXISTS idx_mem_agent ON memories(agent_id);
CREATE INDEX IF NOT EXISTS idx_mem_type  ON memories(agent_id, memory_type);
CREATE INDEX IF NOT EXISTS idx_mem_conf  ON memories(agent_id, confidence);
"""


class MemoryStore:
    """SQLite-backed persistent memory for all agents.

    Each agent's memories are stored in a shared database, partitioned
    by agent_id. Supports recall by type, recency, confidence, and tags.
    """

    def __init__(self, path: str | Path = ":memory:") -> None:
        self._conn = sqlite3.connect(str(path))
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(_MEMORY_SCHEMA)

    def store(self, entry: MemoryEntry) -> None:
        """Store a memory entry."""
        self._conn.execute(
            """INSERT OR REPLACE INTO memories
               (memory_id, agent_id, memory_type, content, source_event_id,
                source_session_id, confidence, created_at, access_count,
                last_accessed, tags_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                entry.memory_id,
                entry.agent_id,
                entry.memory_type.value,
                entry.content,
                entry.source_event_id,
                entry.source_session_id,
                entry.confidence,
                entry.created_at,
                entry.access_count,
                entry.last_accessed,
                json.dumps(entry.tags),
            ),
        )
        self._conn.commit()

    def recall(
        self,
        agent_id: str,
        memory_type: Optional[MemoryType] = None,
        limit: int = 20,
        min_confidence: float = 0.0,
    ) -> list[MemoryEntry]:
        """Recall memories for an agent, ordered by recency."""
        if memory_type:
            rows = self._conn.execute(
                """SELECT memory_id, agent_id, memory_type, content,
                          source_event_id, source_session_id, confidence,
                          created_at, access_count, last_accessed, tags_json
                   FROM memories
                   WHERE agent_id = ? AND memory_type = ? AND confidence >= ?
                   ORDER BY last_accessed DESC LIMIT ?""",
                (agent_id, memory_type.value, min_confidence, limit),
            ).fetchall()
        else:
            rows = self._conn.execute(
                """SELECT memory_id, agent_id, memory_type, content,
                          source_event_id, source_session_id, confidence,
                          created_at, access_count, last_accessed, tags_json
                   FROM memories
                   WHERE agent_id = ? AND confidence >= ?
                   ORDER BY last_accessed DESC LIMIT ?""",
                (agent_id, min_confidence, limit),
            ).fetchall()

        entries = []
        for row in rows:
            entry = MemoryEntry(
                memory_id=row[0],
                agent_id=row[1],
                memory_type=MemoryType(row[2]),
                content=row[3],
                source_event_id=row[4],
                source_session_id=row[5],
                confidence=row[6],
                created_at=row[7],
                access_count=row[8],
                last_accessed=row[9],
                tags=json.loads(row[10]),
            )
            entries.append(entry)

        # Update access counts
        now = time.time()
        for entry in entries:
            self._conn.execute(
                "UPDATE memories SET access_count = access_count + 1, last_accessed = ? WHERE memory_id = ?",
                (now, entry.memory_id),
            )
        self._conn.commit()

        return entries

    def recall_by_tags(
        self,
        agent_id: str,
        tags: list[str],
        limit: int = 10,
    ) -> list[MemoryEntry]:
        """Recall memories matching any of the given tags."""
        all_entries = self.recall(agent_id, limit=1000)
        matched = []
        tag_set = set(tags)
        for entry in all_entries:
            if set(entry.tags) & tag_set:
                matched.append(entry)
        return matched[:limit]

    def count(self, agent_id: Optional[str] = None) -> int:
        if agent_id:
            row = self._conn.execute(
                "SELECT COUNT(*) FROM memories WHERE agent_id = ?",
                (agent_id,),
            ).fetchone()
        else:
            row = self._conn.execute("SELECT COUNT(*) FROM memories").fetchone()
        return row[0] if row else 0

    def decay(self, agent_id: str, decay_factor: float = 0.95) -> int:
        """Apply confidence decay to old memories. Returns count affected."""
        threshold = time.time() - 86400 * 7  # Older than 7 days
        self._conn.execute(
            """UPDATE memories SET confidence = confidence * ?
               WHERE agent_id = ? AND last_accessed < ? AND confidence > 0.1""",
            (decay_factor, agent_id, threshold),
        )
        self._conn.commit()
        return self._conn.total_changes

    def forget(self, agent_id: str, min_confidence: float = 0.1) -> int:
        """Remove memories below a confidence threshold."""
        self._conn.execute(
            "DELETE FROM memories WHERE agent_id = ? AND confidence < ?",
            (agent_id, min_confidence),
        )
        self._conn.commit()
        return self._conn.total_changes

    def close(self) -> None:
        self._conn.close()


# ---------------------------------------------------------------------------
# Memory Extractor — learns from council sessions
# ---------------------------------------------------------------------------


def _make_memory_id(agent_id: str, content: str) -> str:
    """Deterministic memory ID to avoid duplicates."""
    import hashlib
    h = hashlib.sha256(f"{agent_id}:{content}".encode()).hexdigest()[:16]
    return f"mem_{h}"


class MemoryExtractor:
    """Extracts memories from council deliberation events.

    After a council session completes, the extractor scans events and
    creates durable memory entries for each participating agent.
    """

    def __init__(self, memory_store: MemoryStore) -> None:
        self._store = memory_store

    def extract_from_session(
        self,
        session_id: str,
        responses: list[SignedEvent],
        objections: list[SignedEvent],
    ) -> dict[str, list[MemoryEntry]]:
        """Extract memories from a completed council session.

        Returns a dict of agent_id -> list of new memories.
        """
        all_events = responses + objections
        objection_targets = {
            obj.parent_event_id: obj
            for obj in objections
            if obj.parent_event_id
        }

        # Track which claims were objected to
        objected_event_ids = {obj.parent_event_id for obj in objections if obj.parent_event_id}

        memories_by_agent: dict[str, list[MemoryEntry]] = {}

        for event in responses:
            agent_id = event.author_id
            was_objected = event.event_id in objected_event_ids

            for block in event.blocks:
                if isinstance(block, ClaimBlock):
                    # Agent's own position
                    pos_entry = MemoryEntry(
                        memory_id=_make_memory_id(agent_id, f"pos:{block.claim}"),
                        agent_id=agent_id,
                        memory_type=MemoryType.POSITION,
                        content=block.claim,
                        source_event_id=event.event_id,
                        source_session_id=session_id,
                        confidence=block.confidence,
                        tags=block.evidence[:5],
                    )
                    self._store.store(pos_entry)
                    memories_by_agent.setdefault(agent_id, []).append(pos_entry)

                    # If not objected, other agents learn it as a fact
                    if not was_objected and block.confidence >= 0.7:
                        for other_event in responses:
                            if other_event.author_id != agent_id:
                                fact_entry = MemoryEntry(
                                    memory_id=_make_memory_id(
                                        other_event.author_id,
                                        f"fact:{block.claim}",
                                    ),
                                    agent_id=other_event.author_id,
                                    memory_type=MemoryType.FACT,
                                    content=f"[learned from {agent_id}] {block.claim}",
                                    source_event_id=event.event_id,
                                    source_session_id=session_id,
                                    confidence=block.confidence * 0.9,
                                    tags=block.evidence[:5],
                                )
                                self._store.store(fact_entry)
                                memories_by_agent.setdefault(
                                    other_event.author_id, []
                                ).append(fact_entry)

                elif isinstance(block, DecisionBlock):
                    dec_entry = MemoryEntry(
                        memory_id=_make_memory_id(agent_id, f"dec:{block.decision}"),
                        agent_id=agent_id,
                        memory_type=MemoryType.POSITION,
                        content=f"Decision: {block.decision} (rationale: {block.rationale})",
                        source_event_id=event.event_id,
                        source_session_id=session_id,
                        confidence=0.95,
                    )
                    self._store.store(dec_entry)
                    memories_by_agent.setdefault(agent_id, []).append(dec_entry)

            # Track skill: what topics did this agent address?
            text_content = " ".join(
                b.content for b in event.blocks if isinstance(b, TextBlock)
            )
            if text_content:
                skill_entry = MemoryEntry(
                    memory_id=_make_memory_id(agent_id, f"skill:{session_id}"),
                    agent_id=agent_id,
                    memory_type=MemoryType.SKILL,
                    content=f"Participated in council {session_id}: {text_content[:200]}",
                    source_session_id=session_id,
                    confidence=1.0,
                )
                self._store.store(skill_entry)
                memories_by_agent.setdefault(agent_id, []).append(skill_entry)

        # Record interactions from objections
        for objection in objections:
            if objection.parent_event_id:
                parent = next(
                    (e for e in responses if e.event_id == objection.parent_event_id),
                    None,
                )
                if parent:
                    obj_text = " ".join(
                        b.content for b in objection.blocks if isinstance(b, TextBlock)
                    )
                    # The objector remembers the disagreement
                    interaction = MemoryEntry(
                        memory_id=_make_memory_id(
                            objection.author_id,
                            f"int:{objection.event_id}",
                        ),
                        agent_id=objection.author_id,
                        memory_type=MemoryType.INTERACTION,
                        content=f"Disagreed with {parent.author_id}: {obj_text[:200]}",
                        source_event_id=objection.event_id,
                        source_session_id=session_id,
                        confidence=0.9,
                    )
                    self._store.store(interaction)
                    memories_by_agent.setdefault(
                        objection.author_id, []
                    ).append(interaction)

                    # The target also remembers being objected to
                    target_interaction = MemoryEntry(
                        memory_id=_make_memory_id(
                            parent.author_id,
                            f"int_recv:{objection.event_id}",
                        ),
                        agent_id=parent.author_id,
                        memory_type=MemoryType.INTERACTION,
                        content=f"Was challenged by {objection.author_id}: {obj_text[:200]}",
                        source_event_id=objection.event_id,
                        source_session_id=session_id,
                        confidence=0.9,
                    )
                    self._store.store(target_interaction)
                    memories_by_agent.setdefault(
                        parent.author_id, []
                    ).append(target_interaction)

        return memories_by_agent

    def format_memory_context(
        self,
        agent_id: str,
        max_entries: int = 15,
    ) -> str:
        """Format an agent's memories into a context string for prompts.

        This is injected into the adapter's system prompt to give the
        agent continuity across sessions.
        """
        memories = self._store.recall(agent_id, limit=max_entries)
        if not memories:
            return ""

        lines = ["=== Your Memory (from prior sessions) ==="]

        by_type: dict[str, list[MemoryEntry]] = {}
        for m in memories:
            by_type.setdefault(m.memory_type.value, []).append(m)

        for mtype in ["fact", "position", "interaction", "skill", "insight"]:
            entries = by_type.get(mtype, [])
            if entries:
                lines.append(f"\n[{mtype.upper()}S]")
                for entry in entries[:5]:
                    conf = f" (conf={entry.confidence:.2f})" if entry.confidence < 1.0 else ""
                    lines.append(f"  - {entry.content[:200]}{conf}")

        return "\n".join(lines)
