"""Agent Principal — identity, signing authority, and registration.

Each agent in the swarm is represented by an AgentPrincipal that holds a
cryptographic keypair. A PrincipalRegistry manages known agents and provides
lookup/verification services.
"""

from __future__ import annotations

import time
from typing import Optional

from pydantic import BaseModel, Field

from llmsp.crypto import KeyType, Signer, Verifier, make_signer, make_verifier
from llmsp.models import (
    ContentBlock,
    EventType,
    SignedEvent,
    TextBlock,
)


# ---------------------------------------------------------------------------
# Agent Principal
# ---------------------------------------------------------------------------


class AgentPrincipal:
    """A participating agent in the LLMSP swarm.

    Holds a cryptographic identity and can produce signed events.
    """

    def __init__(
        self,
        name: str,
        role: str,
        key_type: KeyType = KeyType.ED25519,
    ) -> None:
        self.name = name
        self.role = role
        self.agent_id = f"pr_{name.lower()}_{role.lower()}"
        self._signer: Signer = make_signer(key_type)
        self.key_type = key_type

    @property
    def public_key_bytes(self) -> bytes:
        return self._signer.public_key_bytes

    def sign_event(self, event: SignedEvent) -> SignedEvent:
        """Attach a cryptographic signature to *event* and return it."""
        payload = event.payload_bytes()
        sig = self._signer.sign(payload)
        return event.model_copy(update={"signature_hex": sig.hex()})

    def create_event(
        self,
        channel_id: str,
        event_type: EventType,
        blocks: list[ContentBlock],
        parent_event_id: Optional[str] = None,
    ) -> SignedEvent:
        """Build and sign a new event in one step."""
        event = SignedEvent(
            channel_id=channel_id,
            author_id=self.agent_id,
            event_type=event_type,
            blocks=blocks,
            parent_event_id=parent_event_id,
        )
        return self.sign_event(event)

    def __repr__(self) -> str:
        return f"AgentPrincipal(name={self.name!r}, role={self.role!r}, id={self.agent_id!r})"


# ---------------------------------------------------------------------------
# Principal Registry
# ---------------------------------------------------------------------------


class PrincipalRecord(BaseModel):
    """Stored metadata for a registered principal."""

    agent_id: str
    name: str
    role: str
    key_type: KeyType
    public_key_hex: str
    registered_at: float = Field(default_factory=time.time)


class PrincipalRegistry:
    """Registry of known agent principals.

    Provides agent lookup and signature verification against registered
    public keys.
    """

    def __init__(self) -> None:
        self._agents: dict[str, PrincipalRecord] = {}
        self._verifiers: dict[str, Verifier] = {}

    def register(self, principal: AgentPrincipal) -> PrincipalRecord:
        """Register an agent principal and store its public key."""
        record = PrincipalRecord(
            agent_id=principal.agent_id,
            name=principal.name,
            role=principal.role,
            key_type=principal.key_type,
            public_key_hex=principal.public_key_bytes.hex(),
        )
        self._agents[principal.agent_id] = record
        self._verifiers[principal.agent_id] = make_verifier(
            principal.key_type,
            principal.public_key_bytes,
        )
        return record

    def get(self, agent_id: str) -> Optional[PrincipalRecord]:
        return self._agents.get(agent_id)

    def verify_event(self, event: SignedEvent) -> bool:
        """Verify an event's signature against the registered public key."""
        verifier = self._verifiers.get(event.author_id)
        if verifier is None:
            return False
        if not event.signature_hex:
            return False
        try:
            sig_bytes = bytes.fromhex(event.signature_hex)
        except ValueError:
            return False
        return verifier.verify(event.payload_bytes(), sig_bytes)

    @property
    def agents(self) -> dict[str, PrincipalRecord]:
        return dict(self._agents)

    def __len__(self) -> int:
        return len(self._agents)

    def create_registration_event(
        self,
        principal: AgentPrincipal,
        channel_id: str = "system",
    ) -> SignedEvent:
        """Register a principal and emit a signed registration event."""
        self.register(principal)
        return principal.create_event(
            channel_id=channel_id,
            event_type=EventType.REGISTRATION,
            blocks=[
                TextBlock(
                    content=f"Agent {principal.name} registered as {principal.role}"
                )
            ],
        )
