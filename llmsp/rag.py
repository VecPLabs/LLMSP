"""RAG (Retrieval-Augmented Generation) layer for LLMSP.

Provides semantic search over the event log using vector embeddings.
Supports pluggable embedding backends — ships with a lightweight
TF-IDF fallback that requires no external dependencies, plus hooks
for OpenAI/Anthropic/local embedding models.
"""

from __future__ import annotations

import hashlib
import math
import re
from abc import ABC, abstractmethod
from collections import Counter
from dataclasses import dataclass, field
from typing import Optional, Protocol

from llmsp.event_store import EventStore
from llmsp.models import (
    ClaimBlock,
    CodeBlock,
    ContentBlock,
    DecisionBlock,
    SignedEvent,
    TaskBlock,
    TextBlock,
)


# ---------------------------------------------------------------------------
# Embedding provider protocol
# ---------------------------------------------------------------------------


class EmbeddingProvider(Protocol):
    """Produces vector embeddings from text."""

    @property
    def dimensions(self) -> int: ...

    def embed(self, text: str) -> list[float]: ...

    def embed_batch(self, texts: list[str]) -> list[list[float]]: ...


# ---------------------------------------------------------------------------
# TF-IDF Embedder (zero-dependency fallback)
# ---------------------------------------------------------------------------


def _tokenize(text: str) -> list[str]:
    """Simple whitespace + punctuation tokenizer."""
    return re.findall(r'\b\w+\b', text.lower())


class TFIDFEmbedder:
    """Lightweight TF-IDF embedder. No external dependencies required.

    Builds a vocabulary from indexed documents and produces sparse-ish
    embeddings. Good enough for basic semantic retrieval over event logs.
    """

    def __init__(self, max_features: int = 512) -> None:
        self.max_features = max_features
        self._vocab: dict[str, int] = {}
        self._idf: dict[str, float] = {}
        self._doc_count: int = 0
        self._doc_freq: Counter = Counter()
        self._frozen = False

    @property
    def dimensions(self) -> int:
        return min(len(self._vocab), self.max_features)

    def fit(self, documents: list[str]) -> None:
        """Build vocabulary and IDF weights from a corpus."""
        self._doc_count = len(documents)
        self._doc_freq = Counter()

        all_tokens: Counter = Counter()
        for doc in documents:
            tokens = set(_tokenize(doc))
            for t in tokens:
                self._doc_freq[t] += 1
            all_tokens.update(_tokenize(doc))

        # Take top-N tokens by frequency as vocabulary
        top_tokens = [t for t, _ in all_tokens.most_common(self.max_features)]
        self._vocab = {t: i for i, t in enumerate(top_tokens)}

        # Compute IDF
        for token, idx in self._vocab.items():
            df = self._doc_freq.get(token, 0)
            self._idf[token] = math.log((self._doc_count + 1) / (df + 1)) + 1

        self._frozen = True

    def embed(self, text: str) -> list[float]:
        """Produce a TF-IDF vector for a single text."""
        tokens = _tokenize(text)
        tf = Counter(tokens)
        vec = [0.0] * self.dimensions

        for token, count in tf.items():
            if token in self._vocab:
                idx = self._vocab[token]
                idf = self._idf.get(token, 1.0)
                vec[idx] = count * idf

        # L2 normalize
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [v / norm for v in vec]

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [self.embed(t) for t in texts]


# ---------------------------------------------------------------------------
# Vector index (in-memory, cosine similarity)
# ---------------------------------------------------------------------------


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a)) or 1.0
    norm_b = math.sqrt(sum(x * x for x in b)) or 1.0
    return dot / (norm_a * norm_b)


@dataclass
class IndexEntry:
    event_id: str
    text: str
    embedding: list[float]


@dataclass
class SearchResult:
    event_id: str
    score: float
    event: Optional[SignedEvent] = None


class VectorIndex:
    """In-memory vector index with cosine similarity search."""

    def __init__(self) -> None:
        self._entries: list[IndexEntry] = []

    def add(self, event_id: str, text: str, embedding: list[float]) -> None:
        self._entries.append(IndexEntry(event_id=event_id, text=text, embedding=embedding))

    def search(self, query_embedding: list[float], top_k: int = 10) -> list[SearchResult]:
        """Find the top-k most similar entries to the query."""
        scored = [
            SearchResult(event_id=e.event_id, score=_cosine_similarity(query_embedding, e.embedding))
            for e in self._entries
        ]
        scored.sort(key=lambda r: r.score, reverse=True)
        return scored[:top_k]

    def __len__(self) -> int:
        return len(self._entries)


# ---------------------------------------------------------------------------
# RAG Engine
# ---------------------------------------------------------------------------


def _event_to_text(event: SignedEvent) -> str:
    """Extract searchable text from an event's content blocks."""
    parts = []
    for block in event.blocks:
        if isinstance(block, TextBlock):
            parts.append(block.content)
        elif isinstance(block, ClaimBlock):
            parts.append(block.claim)
            parts.extend(block.evidence)
        elif isinstance(block, CodeBlock):
            parts.append(block.description)
            parts.append(block.source)
        elif isinstance(block, TaskBlock):
            parts.append(block.task)
        elif isinstance(block, DecisionBlock):
            parts.append(block.decision)
            parts.append(block.rationale)
    return " ".join(parts)


class RAGEngine:
    """Retrieval-Augmented Generation over the LLMSP event log.

    Indexes events as vector embeddings and provides semantic search
    for the context router.
    """

    def __init__(
        self,
        event_store: EventStore,
        embedder: Optional[EmbeddingProvider] = None,
        max_features: int = 512,
    ) -> None:
        self._store = event_store
        self._embedder: EmbeddingProvider = embedder or TFIDFEmbedder(max_features=max_features)
        self._index = VectorIndex()
        self._indexed_events: set[str] = set()

    def build_index(self, channel_id: Optional[str] = None) -> int:
        """Build (or rebuild) the vector index from the event store.

        Returns the number of events indexed.
        """
        if channel_id:
            events = self._store.get_channel(channel_id, limit=10000)
        else:
            # Index all channels — get events via direct query
            events = []
            rows = self._store._conn.execute(
                "SELECT payload_json FROM events ORDER BY timestamp ASC"
            ).fetchall()
            for (payload_json,) in rows:
                events.append(SignedEvent.model_validate_json(payload_json))

        if not events:
            return 0

        # Extract texts and fit the embedder (if it supports fitting)
        texts = [_event_to_text(e) for e in events]

        if hasattr(self._embedder, 'fit'):
            self._embedder.fit(texts)  # type: ignore[attr-defined]

        # Build index
        self._index = VectorIndex()
        self._indexed_events = set()
        embeddings = self._embedder.embed_batch(texts)
        for event, text, emb in zip(events, texts, embeddings):
            self._index.add(event.event_id, text, emb)
            self._indexed_events.add(event.event_id)

        return len(events)

    def index_event(self, event: SignedEvent) -> None:
        """Incrementally index a single new event."""
        if event.event_id in self._indexed_events:
            return
        text = _event_to_text(event)
        embedding = self._embedder.embed(text)
        self._index.add(event.event_id, text, embedding)
        self._indexed_events.add(event.event_id)

    def search(
        self,
        query: str,
        top_k: int = 10,
        resolve_events: bool = True,
    ) -> list[SearchResult]:
        """Semantic search over indexed events.

        Args:
            query: Natural language query
            top_k: Number of results to return
            resolve_events: If True, attach full SignedEvent objects to results
        """
        query_embedding = self._embedder.embed(query)
        results = self._index.search(query_embedding, top_k=top_k)

        if resolve_events:
            for result in results:
                result.event = self._store.get(result.event_id)

        return results

    def get_relevant_context(
        self,
        query: str,
        top_k: int = 10,
        min_score: float = 0.0,
    ) -> list[SignedEvent]:
        """Get the most relevant events for a query as context.

        Convenience method that returns resolved events filtered by score.
        """
        results = self.search(query, top_k=top_k, resolve_events=True)
        return [
            r.event
            for r in results
            if r.event is not None and r.score >= min_score
        ]

    @property
    def index_size(self) -> int:
        return len(self._index)
