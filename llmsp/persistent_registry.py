"""SQLite-backed persistent principal registry.

Extends the in-memory PrincipalRegistry with durable storage.
Agent identities and public keys survive process restarts.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Optional

from llmsp.crypto import KeyType, Verifier, make_verifier
from llmsp.models import EventType, SignedEvent, TextBlock
from llmsp.principal import AgentPrincipal, PrincipalRecord, PrincipalRegistry


_REGISTRY_SCHEMA = """\
CREATE TABLE IF NOT EXISTS principals (
    agent_id       TEXT PRIMARY KEY,
    name           TEXT NOT NULL,
    role           TEXT NOT NULL,
    key_type       TEXT NOT NULL,
    public_key_hex TEXT NOT NULL,
    registered_at  REAL NOT NULL
);
"""


class PersistentRegistry(PrincipalRegistry):
    """SQLite-backed principal registry.

    On init, loads all previously registered principals from disk.
    New registrations are written through to both memory and SQLite.
    """

    def __init__(self, path: str | Path = ":memory:") -> None:
        super().__init__()
        self._path = str(path)
        self._conn = sqlite3.connect(self._path)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(_REGISTRY_SCHEMA)
        self._load_from_db()

    def _load_from_db(self) -> None:
        """Load all stored principals into memory and rebuild verifiers."""
        rows = self._conn.execute(
            "SELECT agent_id, name, role, key_type, public_key_hex, registered_at FROM principals"
        ).fetchall()
        for agent_id, name, role, key_type_str, pub_hex, registered_at in rows:
            key_type = KeyType(key_type_str)
            record = PrincipalRecord(
                agent_id=agent_id,
                name=name,
                role=role,
                key_type=key_type,
                public_key_hex=pub_hex,
                registered_at=registered_at,
            )
            self._agents[agent_id] = record
            pub_bytes = bytes.fromhex(pub_hex)
            self._verifiers[agent_id] = make_verifier(key_type, pub_bytes)

    def register(self, principal: AgentPrincipal) -> PrincipalRecord:
        """Register a principal in both memory and SQLite."""
        record = super().register(principal)
        self._conn.execute(
            """INSERT OR REPLACE INTO principals
               (agent_id, name, role, key_type, public_key_hex, registered_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                record.agent_id,
                record.name,
                record.role,
                record.key_type.value,
                record.public_key_hex,
                record.registered_at,
            ),
        )
        self._conn.commit()
        return record

    def remove(self, agent_id: str) -> bool:
        """Remove a principal from the registry."""
        if agent_id not in self._agents:
            return False
        del self._agents[agent_id]
        self._verifiers.pop(agent_id, None)
        self._conn.execute("DELETE FROM principals WHERE agent_id = ?", (agent_id,))
        self._conn.commit()
        return True

    def close(self) -> None:
        self._conn.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
