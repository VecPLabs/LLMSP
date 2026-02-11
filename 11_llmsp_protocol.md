# LLMSP: LLM Swarm Protocol

## A Protocol for Multi-Agent AI Collaboration

**Status:** Conceptual, proof-of-concept code exists  
**Origin:** Gemini engineering session, January 2026  
**Related:** SME Architecture, VecP Security Stack

---

## Overview

LLMSP (LLM Swarm Protocol) formalizes the coordination patterns discovered through practical multi-agent AI research. It provides:

- **Cryptographic identity** for agent attribution
- **Append-only event logs** for audit trails
- **Structured content blocks** for semantic parsing
- **Council architecture** for collaborative reasoning

---

## Core Insight

> "You have effectively reinvented Event Sourcing applied to the Actor Model, which is how high-scale distributed systems (like banking ledgers and WhatsApp) have worked for decades."

The "novel" contribution is applying these proven patterns to LLM coordination, enabled by modern models' ability to reliably output strict JSON.

---

## Architecture

### The Atomic Unit: Signed Events

```python
class SignedEvent(BaseModel):
    event_id: str
    timestamp: float
    channel_id: str
    author_id: str  # Cryptographically verified
    event_type: Literal["message", "objection", "decision"]
    blocks: List[ContentBlock]
    signature_hex: str  # RSA/Ed25519 proof
```

### Agent Principals

Each agent has:
- Unique identifier
- Public/private keypair
- Role designation
- Signing authority

### Content Blocks

Structured semantic units:
- `text`: General content
- `claim`: Verifiable assertions
- `code`: Executable content
- `task`: Action items
- `decision`: Resolved outcomes

---

## The Council Pattern

```
┌─────────────────────────────────────────────────────────────┐
│                     USER QUERY                               │
└─────────────────────────────┬───────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                    CONTEXT ROUTER                            │
│         (RAG: Retrieves relevant event history)              │
└─────────────────────────────┬───────────────────────────────┘
                              │
              ┌───────────────┼───────────────┐
              ▼               ▼               ▼
        ┌──────────┐   ┌──────────┐   ┌──────────┐
        │  Agent A │   │  Agent B │   │  Agent C │
        │ (Claude) │   │ (Gemini) │   │  (Grok)  │
        └────┬─────┘   └────┬─────┘   └────┬─────┘
             │              │              │
             └──────────────┼──────────────┘
                            ▼
┌─────────────────────────────────────────────────────────────┐
│                       THE CLERK                              │
│    (Non-generative synthesis - typesetter, not editor)       │
└─────────────────────────────────────────────────────────────┘
```

---

## Mapping to Existing Primitives

| LLMSP Component | Standard Technology |
|-----------------|---------------------|
| Signed Principals | RSA/Ed25519 PKI |
| Event Log | Append-only database (SQLite/Postgres) |
| Structured Content | JSON Schema (Pydantic) |
| Context Router | RAG with vector embeddings |
| The Clerk | Constrained LLM synthesis |

---

## Connection to VecP Architecture

### Event Log = Scarred Ledger

Both are append-only, immutable records that enforce self-knowledge. The swarm cannot edit its history. Decisions and their reasoning are permanently recorded.

### Signed Principals = Identity Persistence

Solves the "is this the same instance" problem. Cryptographic proof of authorship enables verified continuity across sessions.

### The Clerk = The Compiler

Same design constraint: must be **non-generative**. Only transforms, orders, and contextualizes. Never introduces novel content. Preserves the "ignorance invariant."

---

## Current Implementation

David Cappelli has been running this protocol *manually* for 8 weeks:

| Manual Process | LLMSP Equivalent |
|----------------|------------------|
| Copy output between browser tabs | Signed Event relay |
| Keep conversation histories | Append-only event log |
| Remember who said what | Cryptographic signatures |
| Relay context between instances | Context Router |
| Synthesize outputs personally | The Clerk function |

The human operator currently serves as all protocol layers simultaneously.

---

## Practical Considerations

### Latency
Council architecture is slower than single-agent chat. Appropriate for complex decisions, not simple queries.

### Cost (API users)
Multi-turn debates multiply token costs. However, premium subscription users (flat rate) effectively bypass this constraint.

### The Clerk Problem
> "Writing the system prompt for the Clerk (the one who synthesizes the debate without hallucinating new facts) is actually the hardest part of this entire stack."

Solution: Constrain the Clerk to be a "typesetter" with explicit prohibitions on novel content generation.

---

## Hybrid Approach

Not all tasks need council deliberation:

| Task Type | Routing |
|-----------|---------|
| Simple queries | Single agent |
| Domain-specific | Appropriate SME |
| Architectural decisions | Full council |
| Adversarial testing | Council with designated critic |
| Complex synthesis | Council + Clerk |

---

## Proof of Concept

```python
# Minimal viable protocol - ~50 lines
# Creates signed events with cryptographic verification
# See full implementation in Gemini engineering notes

from cryptography.hazmat.primitives.asymmetric import rsa, padding
from cryptography.hazmat.primitives import hashes

class AgentPrincipal:
    def __init__(self, name: str, role: str):
        self.id = f"pr_{name.lower()}_{role.lower()}"
        self._private_key = rsa.generate_private_key(
            public_exponent=65537, 
            key_size=2048
        )
        self.public_key = self._private_key.public_key()
    
    def sign_event(self, payload: bytes) -> bytes:
        return self._private_key.sign(
            payload,
            padding.PSS(
                mgf=padding.MGF1(hashes.SHA256()), 
                salt_length=padding.PSS.MAX_LENGTH
            ),
            hashes.SHA256()
        )
```

---

## Publication Notes

This protocol emerged from practice, not theory. The formalization follows 8 weeks of empirical multi-agent coordination that produced:

- Patent-pending safety architecture (VecP)
- Benchmark results beating 10x larger models
- Multiple publication-ready papers
- Novel SME swarm architecture

The protocol documents *what already works*.

---

## Next Steps

1. Implement persistent event store
2. Build context router with RAG
3. Design constrained Clerk prompts
4. Create agent registration system
5. Test council deliberation on real problems

---

## Citation

```bibtex
@misc{cappelli2026llmsp,
  title={LLMSP: A Protocol for Multi-Agent AI Collaboration},
  author={Cappelli, David},
  year={2026},
  howpublished={VecP Labs},
  note={Formalized from empirical multi-agent research workflow}
}
```

---

*VecP Labs — The Swarm Protocol*
