"""Append-only event store backed by SQLite.

This is the Scarred Ledger — events can only be appended, never modified
or deleted. The store enforces immutability at the application layer and
provides channel-scoped queries.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Optional

from llmsp.models import SignedEvent


_SCHEMA = """\
CREATE TABLE IF NOT EXISTS events (
    event_id     TEXT PRIMARY KEY,
    timestamp    REAL NOT NULL,
    channel_id   TEXT NOT NULL,
    author_id    TEXT NOT NULL,
    event_type   TEXT NOT NULL,
    parent_event_id TEXT,
    signature_hex TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    content_hash TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_events_channel ON events(channel_id);
CREATE INDEX IF NOT EXISTS idx_events_author  ON events(author_id);
CREATE INDEX IF NOT EXISTS idx_events_ts      ON events(timestamp);
CREATE INDEX IF NOT EXISTS idx_events_parent  ON events(parent_event_id);
"""


class EventStore:
    """SQLite-backed append-only event log.

    Instantiate with a file path for persistence, or `\":memory:\"` for
    in-memory testing.
    """

    def __init__(self, path: str | Path = ":memory:") -> None:
        self._path = str(path)
        self._conn = sqlite3.connect(self._path)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.executescript(_SCHEMA)

    # ------------------------------------------------------------------
    # Write path (append only)
    # ------------------------------------------------------------------

    def append(self, event: SignedEvent) -> SignedEvent:
        """Append a signed event to the log. Raises on duplicate event_id."""
        payload_json = event.model_dump_json()
        content_hash = event.content_hash()
        try:
            self._conn.execute(
                """INSERT INTO events
                   (event_id, timestamp, channel_id, author_id, event_type,
                    parent_event_id, signature_hex, payload_json, content_hash)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    event.event_id,
                    event.timestamp,
                    event.channel_id,
                    event.author_id,
                    event.event_type.value,
                    event.parent_event_id,
                    event.signature_hex,
                    payload_json,
                    content_hash,
                ),
            )
            self._conn.commit()
        except sqlite3.IntegrityError as exc:
            raise ValueError(f"Duplicate event: {event.event_id}") from exc
        return event

    # ------------------------------------------------------------------
    # Read paths
    # ------------------------------------------------------------------

    def get(self, event_id: str) -> Optional[SignedEvent]:
        """Retrieve a single event by ID."""
        row = self._conn.execute(
            "SELECT payload_json FROM events WHERE event_id = ?",
            (event_id,),
        ).fetchone()
        if row is None:
            return None
        return SignedEvent.model_validate_json(row[0])

    def get_channel(
        self,
        channel_id: str,
        limit: int = 100,
        after_ts: Optional[float] = None,
    ) -> list[SignedEvent]:
        """Get events for a channel, ordered by timestamp ascending."""
        if after_ts is not None:
            rows = self._conn.execute(
                """SELECT payload_json FROM events
                   WHERE channel_id = ? AND timestamp > ?
                   ORDER BY timestamp ASC LIMIT ?""",
                (channel_id, after_ts, limit),
            ).fetchall()
        else:
            rows = self._conn.execute(
                """SELECT payload_json FROM events
                   WHERE channel_id = ?
                   ORDER BY timestamp ASC LIMIT ?""",
                (channel_id, limit),
            ).fetchall()
        return [SignedEvent.model_validate_json(r[0]) for r in rows]

    def get_thread(self, parent_event_id: str) -> list[SignedEvent]:
        """Get all events that are replies to a given parent event."""
        rows = self._conn.execute(
            """SELECT payload_json FROM events
               WHERE parent_event_id = ?
               ORDER BY timestamp ASC""",
            (parent_event_id,),
        ).fetchall()
        return [SignedEvent.model_validate_json(r[0]) for r in rows]

    def get_by_author(
        self,
        author_id: str,
        limit: int = 100,
    ) -> list[SignedEvent]:
        """Get events authored by a specific principal."""
        rows = self._conn.execute(
            """SELECT payload_json FROM events
               WHERE author_id = ?
               ORDER BY timestamp ASC LIMIT ?""",
            (author_id, limit),
        ).fetchall()
        return [SignedEvent.model_validate_json(r[0]) for r in rows]

    def count(self, channel_id: Optional[str] = None) -> int:
        """Count events, optionally scoped to a channel."""
        if channel_id:
            row = self._conn.execute(
                "SELECT COUNT(*) FROM events WHERE channel_id = ?",
                (channel_id,),
            ).fetchone()
        else:
            row = self._conn.execute("SELECT COUNT(*) FROM events").fetchone()
        return row[0] if row else 0

    def latest(self, channel_id: str) -> Optional[SignedEvent]:
        """Get the most recent event on a channel."""
        row = self._conn.execute(
            """SELECT payload_json FROM events
               WHERE channel_id = ?
               ORDER BY timestamp DESC LIMIT 1""",
            (channel_id,),
        ).fetchone()
        if row is None:
            return None
        return SignedEvent.model_validate_json(row[0])

    def list_channels(self, limit: int = 50) -> list[dict]:
        """Summarize channels in the ledger, ordered by most-recent activity.

        Each row is ``{channel_id, event_count, first_ts, last_ts, agents}``
        where ``agents`` is the distinct authors that ever posted to the
        channel. Used by the dashboard to render a recent-councils list.
        """
        rows = self._conn.execute(
            """SELECT channel_id,
                      COUNT(*)          AS event_count,
                      MIN(timestamp)    AS first_ts,
                      MAX(timestamp)    AS last_ts,
                      GROUP_CONCAT(DISTINCT author_id) AS authors
               FROM events
               GROUP BY channel_id
               ORDER BY last_ts DESC
               LIMIT ?""",
            (limit,),
        ).fetchall()
        return [
            {
                "channel_id": ch,
                "event_count": n,
                "first_ts": first,
                "last_ts": last,
                "authors": (authors or "").split(","),
            }
            for ch, n, first, last, authors in rows
        ]

    # ------------------------------------------------------------------
    # Integrity
    # ------------------------------------------------------------------

    def verify_integrity(self) -> list[str]:
        """Check stored content hashes against recomputed values.

        Returns a list of event_ids with hash mismatches (empty = all good).
        """
        mismatches: list[str] = []
        rows = self._conn.execute(
            "SELECT event_id, payload_json, content_hash FROM events"
        ).fetchall()
        for event_id, payload_json, stored_hash in rows:
            event = SignedEvent.model_validate_json(payload_json)
            if event.content_hash() != stored_hash:
                mismatches.append(event_id)
        return mismatches

    def close(self) -> None:
        self._conn.close()

    def __len__(self) -> int:
        return self.count()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
