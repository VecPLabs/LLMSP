#!/usr/bin/env python3
"""RAG Retrieval Benchmark for LLMSP.

Simulates 8 weeks of multi-domain deliberation notes, indexes them with the
TF-IDF RAG engine, and measures retrieval quality against ground-truth
relevance judgments.

Metrics reported:
- Precision@K  : fraction of top-K results that are relevant
- Recall@K     : fraction of relevant docs found in top-K
- MRR          : Mean Reciprocal Rank (position of first relevant hit)
- NDCG@K       : Normalized Discounted Cumulative Gain

Usage:
    python -m benchmarks.rag_benchmark
    python -m benchmarks.rag_benchmark --max-features 256 --top-k 5
"""

from __future__ import annotations

import argparse
import math
import time
from dataclasses import dataclass, field

from llmsp.event_store import EventStore
from llmsp.models import ClaimBlock, EventType, TextBlock
from llmsp.principal import AgentPrincipal
from llmsp.rag import RAGEngine


# ---------------------------------------------------------------------------
# Simulated 8-week corpus — topics covering the entire LLMSP design space
# ---------------------------------------------------------------------------

# Each entry: (week, domain, content, tags_for_relevance)
_CORPUS: list[tuple[int, str, str, list[str]]] = [
    # --- Week 1: Cryptographic foundations ---
    (1, "crypto", "Ed25519 provides 128-bit security with 64-byte signatures, making it ideal for high-throughput event signing in the LLMSP protocol", ["crypto", "signing", "ed25519"]),
    (1, "crypto", "RSA-PSS with 2048-bit keys offers broader compatibility but 256-byte signatures create storage overhead in the append-only ledger", ["crypto", "signing", "rsa"]),
    (1, "crypto", "Key rotation policy: agent principals should rotate Ed25519 keypairs every 90 days, with the old public key retained in the registry for historical verification", ["crypto", "key-management"]),
    (1, "design", "The append-only constraint means we cannot delete events. Content hashes chain integrity like a simplified blockchain without the consensus overhead", ["ledger", "integrity"]),

    # --- Week 2: Protocol architecture ---
    (2, "arch", "The five content block types (text, claim, code, task, decision) cover the full semantic space of multi-agent deliberation", ["protocol", "content-blocks"]),
    (2, "arch", "SignedEvent is the atomic unit. Immutability after creation prevents retroactive manipulation of deliberation history", ["protocol", "events"]),
    (2, "arch", "Channel-scoped events allow multiple concurrent deliberations without cross-contamination of context", ["protocol", "channels"]),
    (2, "security", "Signature verification at ingestion time prevents unsigned or tampered events from entering the ledger", ["security", "signing"]),

    # --- Week 3: Council deliberation patterns ---
    (3, "council", "The four-phase council (deliberate, review, object, synthesize) mirrors academic peer review with faster iteration", ["council", "deliberation"]),
    (3, "council", "Objection rounds prevent groupthink. When Agent A objects to Agent B, the objection event references B's event via parent_event_id", ["council", "objections"]),
    (3, "council", "The Clerk is the most constrained component: non-generative synthesis means it can only reorganize what agents actually said", ["clerk", "synthesis"]),
    (3, "council", "Limiting objection rounds to 2 prevents infinite loops while still allowing substantive disagreement to surface", ["council", "objections"]),

    # --- Week 4: Routing and context ---
    (4, "routing", "Keyword-based routing rules are fast but brittle. A security query containing code snippets might not match the security keyword rule", ["routing", "context"]),
    (4, "routing", "The broadcast strategy (all agents participate) is the safest default but scales poorly beyond 5 agents", ["routing", "scaling"]),
    (4, "routing", "Context window management: the router should retrieve the last 20 events from the channel plus any RAG-retrieved events from related channels", ["routing", "context", "rag"]),
    (4, "performance", "SQLite WAL mode provides concurrent reads during writes, essential for the auditor daemon scanning while councils are running", ["performance", "sqlite"]),

    # --- Week 5: LLM adapter design ---
    (5, "adapters", "The BaseAdapter pattern lets us swap LLM backends without changing council logic. Claude, Gemini, and Grok all share the same generate/review interface", ["adapters", "llm"]),
    (5, "adapters", "Temperature 0.7 for generation, 0.3 for review. Lower temperature during review reduces spurious objections", ["adapters", "llm", "parameters"]),
    (5, "adapters", "JSON response parsing needs fallback: if the LLM doesn't produce valid JSON blocks, wrap the entire response as a TextBlock", ["adapters", "parsing"]),
    (5, "security", "API keys must never appear in the event log. The adapter holds them in memory only, passed via environment variables", ["security", "api-keys"]),

    # --- Week 6: RAG and embeddings ---
    (6, "rag", "TF-IDF embeddings are surprisingly effective for domain-specific retrieval when the vocabulary is constrained to protocol terminology", ["rag", "embeddings"]),
    (6, "rag", "Cosine similarity over L2-normalized TF-IDF vectors gives a natural 0-1 relevance score", ["rag", "similarity"]),
    (6, "rag", "The RAG engine should re-fit the TF-IDF vocabulary when the corpus grows by more than 20 percent to avoid stale vocabulary", ["rag", "indexing"]),
    (6, "performance", "Incremental indexing (index_event) is O(V) per event where V is vocabulary size. Full rebuild is O(N*V) but only needed for vocabulary refresh", ["rag", "performance"]),

    # --- Week 7: Security and auditing ---
    (7, "security", "Prompt injection is the primary threat vector. An attacker could inject instructions into a TextBlock that manipulate downstream agents", ["security", "prompt-injection"]),
    (7, "security", "The security auditor uses regex pattern matching for known injection signatures. This catches crude attacks but not sophisticated paraphrasing", ["security", "auditor"]),
    (7, "security", "Data exfiltration via CodeBlock: an agent could embed curl commands in code blocks that send ledger data to external endpoints", ["security", "exfiltration"]),
    (7, "security", "Flood detection: if an agent emits more than 20 events per minute, flag it as potential DoS against the council pipeline", ["security", "flooding"]),

    # --- Week 8: Deployment and operations ---
    (8, "ops", "Docker Compose provides single-command deployment. The init service creates schemas, the auditor runs continuously, councils run on-demand", ["deployment", "docker"]),
    (8, "ops", "SQLite databases mount as Docker volumes for persistence across container restarts", ["deployment", "persistence"]),
    (8, "ops", "The CLI entry point (llmsp) exposes init, register, agents, council, log, search, and stats commands", ["deployment", "cli"]),
    (8, "performance", "With 10K events in the ledger, full RAG index rebuild takes under 2 seconds on a single core. TF-IDF is fast enough for this scale", ["rag", "performance", "benchmarking"]),
]


# Ground-truth relevance judgments: query -> set of relevant tags
_QUERIES: list[tuple[str, list[str]]] = [
    ("How does Ed25519 signing work in the protocol?", ["crypto", "signing", "ed25519"]),
    ("What security measures prevent prompt injection?", ["security", "prompt-injection", "auditor"]),
    ("How does the council deliberation process work?", ["council", "deliberation", "objections"]),
    ("What is the Clerk and what constraints does it operate under?", ["clerk", "synthesis"]),
    ("How are LLM adapters designed and what parameters do they use?", ["adapters", "llm", "parameters"]),
    ("How does RAG retrieval and vector indexing work?", ["rag", "embeddings", "similarity", "indexing"]),
    ("How is the system deployed with Docker?", ["deployment", "docker", "persistence"]),
    ("What routing strategies exist for query distribution?", ["routing", "context", "scaling"]),
    ("How does the append-only ledger ensure integrity?", ["ledger", "integrity", "signing"]),
    ("What are the performance characteristics of the system?", ["performance", "sqlite", "benchmarking"]),
    ("How does the security auditor detect data exfiltration?", ["security", "exfiltration", "auditor"]),
    ("What content block types does the protocol define?", ["protocol", "content-blocks", "events"]),
    ("How does key management and rotation work?", ["crypto", "key-management"]),
    ("What prevents event flooding and DoS attacks?", ["security", "flooding"]),
    ("How does the context router select agents for a query?", ["routing", "context", "rag"]),
]


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------


@dataclass
class QueryMetrics:
    query: str
    precision_at_k: float
    recall_at_k: float
    mrr: float
    ndcg_at_k: float
    top_scores: list[float]


@dataclass
class BenchmarkResult:
    corpus_size: int
    index_time_ms: float
    query_count: int
    avg_precision: float
    avg_recall: float
    avg_mrr: float
    avg_ndcg: float
    per_query: list[QueryMetrics]
    max_features: int
    top_k: int


def _dcg(relevances: list[float], k: int) -> float:
    """Discounted Cumulative Gain."""
    return sum(
        rel / math.log2(i + 2)
        for i, rel in enumerate(relevances[:k])
    )


def _ndcg(relevances: list[float], k: int) -> float:
    """Normalized DCG."""
    dcg = _dcg(relevances, k)
    ideal = _dcg(sorted(relevances, reverse=True), k)
    return dcg / ideal if ideal > 0 else 0.0


# ---------------------------------------------------------------------------
# Benchmark runner
# ---------------------------------------------------------------------------


def run_benchmark(max_features: int = 512, top_k: int = 5) -> BenchmarkResult:
    """Run the full RAG retrieval benchmark."""

    # 1. Build corpus as LLMSP events
    store = EventStore()
    agents = {
        "crypto": AgentPrincipal("CryptoExpert", "cryptographer"),
        "arch": AgentPrincipal("Architect", "architect"),
        "security": AgentPrincipal("SecurityAuditor", "security"),
        "council": AgentPrincipal("CouncilDesigner", "designer"),
        "routing": AgentPrincipal("RouterExpert", "routing"),
        "adapters": AgentPrincipal("AdapterDev", "developer"),
        "rag": AgentPrincipal("RAGSpecialist", "ml_engineer"),
        "ops": AgentPrincipal("DevOps", "operations"),
        "design": AgentPrincipal("Designer", "designer"),
        "performance": AgentPrincipal("PerfEngineer", "performance"),
    }

    event_tags: dict[str, list[str]] = {}  # event_id -> tags
    for week, domain, content, tags in _CORPUS:
        agent = agents.get(domain, agents["arch"])
        channel = f"week_{week}"
        event = agent.create_event(
            channel_id=channel,
            event_type=EventType.MESSAGE,
            blocks=[
                TextBlock(content=content),
                ClaimBlock(claim=content[:80], confidence=0.85),
            ],
        )
        store.append(event)
        event_tags[event.event_id] = tags

    # 2. Build RAG index
    rag = RAGEngine(store, max_features=max_features)

    t0 = time.perf_counter()
    rag.build_index()
    index_time_ms = (time.perf_counter() - t0) * 1000

    # 3. Run queries and measure metrics
    per_query: list[QueryMetrics] = []

    for query_text, relevant_tags in _QUERIES:
        results = rag.search(query_text, top_k=top_k, resolve_events=True)

        # Build relevance vector
        relevances: list[float] = []
        for result in results:
            if result.event_id in event_tags:
                result_tags = set(event_tags[result.event_id])
                query_tags = set(relevant_tags)
                overlap = len(result_tags & query_tags)
                relevances.append(1.0 if overlap > 0 else 0.0)
            else:
                relevances.append(0.0)

        # Count total relevant docs in corpus
        total_relevant = sum(
            1 for eid, tags in event_tags.items()
            if set(tags) & set(relevant_tags)
        )

        # Precision@K
        relevant_found = sum(relevances)
        precision = relevant_found / top_k if top_k > 0 else 0.0

        # Recall@K
        recall = relevant_found / total_relevant if total_relevant > 0 else 0.0

        # MRR (reciprocal rank of first relevant result)
        mrr = 0.0
        for i, rel in enumerate(relevances):
            if rel > 0:
                mrr = 1.0 / (i + 1)
                break

        # NDCG@K
        ndcg = _ndcg(relevances, top_k)

        per_query.append(
            QueryMetrics(
                query=query_text,
                precision_at_k=precision,
                recall_at_k=recall,
                mrr=mrr,
                ndcg_at_k=ndcg,
                top_scores=[r.score for r in results],
            )
        )

    # 4. Aggregate
    n = len(per_query)
    return BenchmarkResult(
        corpus_size=len(event_tags),
        index_time_ms=index_time_ms,
        query_count=n,
        avg_precision=sum(q.precision_at_k for q in per_query) / n,
        avg_recall=sum(q.recall_at_k for q in per_query) / n,
        avg_mrr=sum(q.mrr for q in per_query) / n,
        avg_ndcg=sum(q.ndcg_at_k for q in per_query) / n,
        per_query=per_query,
        max_features=max_features,
        top_k=top_k,
    )


def print_report(result: BenchmarkResult) -> None:
    """Print a formatted benchmark report."""
    print("=" * 70)
    print("LLMSP RAG RETRIEVAL BENCHMARK")
    print("=" * 70)
    print(f"Corpus:         {result.corpus_size} events (simulated 8-week deliberation log)")
    print(f"Index build:    {result.index_time_ms:.1f}ms")
    print(f"TF-IDF features:{result.max_features}")
    print(f"Top-K:          {result.top_k}")
    print(f"Queries:        {result.query_count}")
    print()
    print(f"{'Metric':<20} {'Score':>10}")
    print("-" * 30)
    print(f"{'Precision@K':<20} {result.avg_precision:>10.3f}")
    print(f"{'Recall@K':<20} {result.avg_recall:>10.3f}")
    print(f"{'MRR':<20} {result.avg_mrr:>10.3f}")
    print(f"{'NDCG@K':<20} {result.avg_ndcg:>10.3f}")
    print()
    print("--- Per-Query Breakdown ---")
    print(f"{'Query':<55} {'P@K':>5} {'R@K':>5} {'MRR':>5} {'NDCG':>5}")
    print("-" * 75)
    for q in result.per_query:
        query_short = q.query[:52] + "..." if len(q.query) > 55 else q.query
        print(f"{query_short:<55} {q.precision_at_k:>5.2f} {q.recall_at_k:>5.2f} {q.mrr:>5.2f} {q.ndcg_at_k:>5.2f}")

    print()
    print("--- Score distributions (top-K cosine similarities) ---")
    for q in result.per_query:
        scores_str = ", ".join(f"{s:.3f}" for s in q.top_scores[:3])
        query_short = q.query[:40] + "..." if len(q.query) > 43 else q.query
        print(f"  {query_short:<43} [{scores_str}]")

    print()
    # Verdict
    if result.avg_mrr >= 0.7:
        verdict = "STRONG — first relevant result usually in top 2"
    elif result.avg_mrr >= 0.4:
        verdict = "ACCEPTABLE — relevant results generally in top 5"
    else:
        verdict = "NEEDS IMPROVEMENT — consider upgrading to neural embeddings"
    print(f"Verdict: {verdict}")
    print("=" * 70)


# ---------------------------------------------------------------------------
# Sweep: test multiple configurations
# ---------------------------------------------------------------------------


def run_sweep() -> None:
    """Run the benchmark across multiple configurations to find optimal params."""
    print("\n" + "=" * 70)
    print("PARAMETER SWEEP")
    print("=" * 70)
    print(f"{'Features':>10} {'Top-K':>6} {'P@K':>8} {'R@K':>8} {'MRR':>8} {'NDCG':>8} {'Index(ms)':>10}")
    print("-" * 60)

    for max_features in [64, 128, 256, 512]:
        for top_k in [3, 5, 10]:
            result = run_benchmark(max_features=max_features, top_k=top_k)
            print(
                f"{max_features:>10} {top_k:>6} "
                f"{result.avg_precision:>8.3f} {result.avg_recall:>8.3f} "
                f"{result.avg_mrr:>8.3f} {result.avg_ndcg:>8.3f} "
                f"{result.index_time_ms:>10.1f}"
            )
    print()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="LLMSP RAG Retrieval Benchmark")
    parser.add_argument("--max-features", type=int, default=512, help="TF-IDF vocabulary size")
    parser.add_argument("--top-k", type=int, default=5, help="Number of results to retrieve")
    parser.add_argument("--sweep", action="store_true", help="Run parameter sweep across configurations")
    args = parser.parse_args()

    result = run_benchmark(max_features=args.max_features, top_k=args.top_k)
    print_report(result)

    if args.sweep:
        run_sweep()
