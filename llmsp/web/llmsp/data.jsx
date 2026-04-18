// Mock data for LLMSP swarm — realistic fixtures
const AGENTS = [
  { id: "pr_alice_sec",    name: "Alice",    role: "security",     model: "claude-sonnet-4-5",  tier: "standard", events: 847, objections: 62,  agreement: 0.71, status: "active",    color: "amber" },
  { id: "pr_bob_arch",     name: "Bob",      role: "architecture", model: "claude-opus-4-6",    tier: "frontier", events: 1204, objections: 31, agreement: 0.83, status: "active",    color: "sage"  },
  { id: "pr_carol_perf",   name: "Carol",    role: "performance",  model: "gemini-2.0-pro",     tier: "standard", events: 692, objections: 48,  agreement: 0.68, status: "active",    color: "rust"  },
  { id: "pr_dave_data",    name: "Dave",     role: "data",         model: "grok-3",             tier: "standard", events: 403, objections: 24,  agreement: 0.74, status: "idle",      color: "amber" },
  { id: "pr_eve_audit",    name: "Eve",      role: "auditor",      model: "claude-haiku-4-5",   tier: "fast",     events: 2108, objections: 11, agreement: 0.91, status: "active",    color: "sage"  },
  { id: "pr_frank_ui",     name: "Frank",    role: "ui",           model: "gemini-2.0-flash",   tier: "fast",     events: 318, objections: 9,   agreement: 0.79, status: "idle",      color: "amber" },
  { id: "pr_grace_ml",     name: "Grace",    role: "ml",           model: "grok-3-mini",        tier: "fast",     events: 514, objections: 18,  agreement: 0.77, status: "active",    color: "rust"  },
  { id: "pr_clerk",        name: "Clerk",    role: "clerk",        model: "deterministic",       tier: "zero",     events: 186, objections: 0,   agreement: 1.00, status: "active",    color: "sage"  },
];

const MODELS = [
  { name: "claude-opus-4-6",    inTok:  412301, outTok: 98420,  calls: 1284, costIn: 6.18,  costOut: 7.38,  tier: "frontier" },
  { name: "claude-sonnet-4-5",  inTok:  981042, outTok: 220118, calls: 3891, costIn: 2.94,  costOut: 3.30,  tier: "standard" },
  { name: "claude-haiku-4-5",   inTok:  2104881, outTok: 312640, calls: 8102, costIn: 1.68, costOut: 1.25, tier: "fast" },
  { name: "gemini-2.0-pro",     inTok:  418220, outTok: 89441,  calls: 1402, costIn: 0.52,  costOut: 0.45,  tier: "standard" },
  { name: "gemini-2.0-flash",   inTok:  1102488, outTok: 180412, calls: 4118, costIn: 0.11, costOut: 0.07, tier: "fast" },
  { name: "grok-3",             inTok:  301402, outTok: 62108,  calls: 1021, costIn: 0.90,  costOut: 0.93,  tier: "standard" },
  { name: "grok-3-mini",        inTok:  620148, outTok: 91204,  calls: 2408, costIn: 0.19,  costOut: 0.05,  tier: "fast" },
];

const COUNCILS = [
  { id: "council_1744902418", channel: "crypto_design", topic: "Ed25519 vs RSA-PSS for agent signing at scale", phase: "deliberating", agents: ["Alice","Bob","Carol"], events: 24, elapsed: 48, rounds: 2 },
  { id: "council_1744902210", channel: "auth_strategy", topic: "Session tokens vs JWT for federated auth", phase: "reviewing",    agents: ["Alice","Bob","Dave"],  events: 31, elapsed: 142, rounds: 3 },
  { id: "council_1744901980", channel: "rate_limits",   topic: "Tiered rate limiting across public API",    phase: "synthesizing", agents: ["Bob","Carol","Grace"], events: 19, elapsed: 198, rounds: 2 },
  { id: "council_1744901700", channel: "db_perf",       topic: "Sharding strategy for event ledger at 10M/day", phase: "complete",  agents: ["Bob","Carol","Dave"],  events: 42, elapsed: 312, rounds: 4 },
];

// Live deliberation — the featured one
const LIVE_COUNCIL = {
  id: "council_1744902418",
  channel: "crypto_design",
  topic: "Ed25519 vs RSA-PSS for agent signing at scale",
  phase: "deliberating",
  round: 2,
  maxRounds: 3,
  elapsed: 48,
  participants: ["Alice","Bob","Carol"],
  events: [
    { t: 0,  who: "Clerk",  role: "clerk",    type: "COUNCIL_START",  text: "Council opened. Query routed to: security, architecture, performance." },
    { t: 3,  who: "Alice",  role: "security", type: "MESSAGE",        text: "Ed25519 provides 128-bit security with 64-byte signatures, resistant to known quantum attacks via Shor's until scale.", conf: 0.88 },
    { t: 6,  who: "Bob",    role: "architecture", type: "MESSAGE",    text: "For cross-org federation we need FIPS-140 compatibility. RSA-PSS 3072 is the safer institutional choice.", conf: 0.74 },
    { t: 9,  who: "Carol",  role: "performance", type: "CLAIM",       text: "Ed25519 signs ~15x faster than RSA-3072 in benchmarks. Verification is ~3x faster.", conf: 0.92 },
    { t: 14, who: "Alice",  role: "security", type: "OBJECTION",      text: "FIPS-140-3 now validates Ed25519 (since 2023). Compatibility concern is outdated.", reply: 2 },
    { t: 18, who: "Bob",    role: "architecture", type: "MESSAGE",    text: "Acknowledged. Revise: Ed25519 acceptable if we enforce key rotation every 90d via the registry.", conf: 0.80 },
    { t: 24, who: "Carol",  role: "performance", type: "CLAIM",       text: "At 10k events/s, RSA would require ~40 cores; Ed25519 needs ~3. This is decisive for our footprint.", conf: 0.95 },
    { t: 31, who: "Alice",  role: "security", type: "MESSAGE",        text: "Concur. Proposing Ed25519 as default with RSA-PSS 3072 as opt-in for legacy partners.", conf: 0.84 },
    { t: 38, who: "Bob",    role: "architecture", type: "MESSAGE",    text: "Seconded. Include a migration path: dual-sign during transition window.", conf: 0.82 },
    { t: 45, who: "Clerk",  role: "clerk",    type: "PHASE",          text: "Round 2 complete. Entering review phase in 15s." },
  ],
  synthesis: {
    agreements: [
      "Ed25519 is the default signing algorithm for new agents",
      "RSA-PSS 3072 remains available as opt-in for legacy interop",
      "Keys rotate every 90 days, enforced by PersistentRegistry",
      "Transition window uses dual-signing for gradual migration",
    ],
    disagreements: [
      { topic: "Minimum key rotation interval", positions: [
        { agent: "Alice", view: "30 days for high-value channels" },
        { agent: "Bob",   view: "90 days uniform to reduce ops burden" },
      ]}
    ],
    decisions: [
      { decision: "Adopt Ed25519 as default with RSA-PSS 3072 fallback", rationale: "15× faster signing, FIPS-validated since 2023, 64-byte signatures", dissenters: [] },
    ],
    tasks: [
      { task: "Update AgentPrincipal default to Ed25519",      assignee: "Bob",   status: "open" },
      { task: "Draft 90-day rotation policy for the registry", assignee: "Alice", status: "open" },
      { task: "Benchmark dual-sign overhead at 10k events/s",  assignee: "Carol", status: "open" },
    ],
  }
};

// RAG index health
const RAG = {
  docs: 1284,
  chunks: 8412,
  tfidf_terms: 42108,
  last_reindex: "4m 22s ago",
  queries_24h: 3104,
  mrr: 0.900,
  ndcg10: 0.887,
  p3: 0.727,
  r10: 0.969,
  hit_rate_24h: [
    0.82,0.84,0.79,0.88,0.91,0.86,0.90,0.93,0.89,0.92,0.88,0.85,
    0.91,0.94,0.90,0.89,0.92,0.88,0.91,0.93,0.90,0.92,0.89,0.90
  ],
};

// Integrity
const INTEGRITY = {
  events_total: 128401,
  events_verified: 128401,
  hash_mismatches: 0,
  last_scan: "12s ago",
  signature_failures_24h: 0,
  threats_24h: 2,
  threats: [
    { sev: "MEDIUM", class: "EVENT_FLOOD",       agent: "Dave",  when: "2h 14m", note: "28 events in 60s on channel ch_scratch" },
    { sev: "LOW",    class: "ROLE_ESCALATION",   agent: "Grace", when: "5h 02m", note: "ClaimBlock confidence=1.0 without evidence[]" },
  ],
};

// Event stream
const LEDGER_SAMPLE = [
  { ts: "14:02:18.412", ch: "crypto_design",   who: "Alice",  type: "MESSAGE",   txt: "Ed25519 provides 128-bit security…" },
  { ts: "14:02:15.991", ch: "crypto_design",   who: "Bob",    type: "OBJECTION", txt: "FIPS concerns outdated — see NIST SP 800-186." },
  { ts: "14:02:12.338", ch: "auth_strategy",   who: "Dave",   type: "CLAIM",     txt: "Session cookies cut replay vector by 40%." },
  { ts: "14:02:08.100", ch: "rate_limits",     who: "Clerk",  type: "DECISION",  txt: "Adopt token-bucket with per-tenant quota." },
  { ts: "14:02:03.772", ch: "crypto_design",   who: "Carol",  type: "CLAIM",     txt: "Ed25519 signs ~15× faster than RSA-3072." },
  { ts: "14:02:00.119", ch: "db_perf",         who: "Bob",    type: "MESSAGE",   txt: "Hash-range sharding over ledger_ts works." },
  { ts: "14:01:57.443", ch: "crypto_design",   who: "Clerk",  type: "PHASE",     txt: "Round 1 → Round 2" },
  { ts: "14:01:52.881", ch: "auth_strategy",   who: "Alice",  type: "MESSAGE",   txt: "JWT audience must pin to agent_id." },
  { ts: "14:01:48.221", ch: "crypto_design",   who: "Bob",    type: "MESSAGE",   txt: "Key rotation every 90d via registry." },
  { ts: "14:01:42.009", ch: "rate_limits",     who: "Grace",  type: "CLAIM",     txt: "Sliding window reduces burst unfairness." },
  { ts: "14:01:38.512", ch: "db_perf",         who: "Carol",  type: "OBJECTION", txt: "Range sharding hotspots on recent writes." },
  { ts: "14:01:33.117", ch: "crypto_design",   who: "Alice",  type: "CLAIM",     txt: "Ed25519 FIPS-validated since 2023." },
];

// Budget
const BUDGET = {
  period: "Apr 2026",
  spent: 24.33,
  limit: 80.00,
  forecast: 71.40,
  prev: 68.92,
  by_day: [2.1,1.8,2.4,2.2,1.9,2.6,2.8,2.3,2.1,2.5,2.4,1.9,2.2,2.7,3.0,2.8,2.5,2.4],
};

window.LLMSP_DATA = { AGENTS, MODELS, COUNCILS, LIVE_COUNCIL, RAG, INTEGRITY, LEDGER_SAMPLE, BUDGET };
