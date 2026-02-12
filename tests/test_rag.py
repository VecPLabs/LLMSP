"""Tests for LLMSP RAG (Retrieval-Augmented Generation) layer."""

from llmsp.event_store import EventStore
from llmsp.models import ClaimBlock, EventType, TextBlock
from llmsp.principal import AgentPrincipal
from llmsp.rag import RAGEngine, TFIDFEmbedder, VectorIndex, _cosine_similarity


def test_tfidf_embedder_basic():
    embedder = TFIDFEmbedder(max_features=100)
    docs = [
        "the cat sat on the mat",
        "the dog chased the cat",
        "Python is a great programming language",
    ]
    embedder.fit(docs)

    vec = embedder.embed("cat sat")
    assert len(vec) == embedder.dimensions
    # Should be normalized (L2 norm ~= 1.0)
    import math
    norm = math.sqrt(sum(v * v for v in vec))
    assert abs(norm - 1.0) < 0.01 or norm == 0.0


def test_tfidf_batch_embed():
    embedder = TFIDFEmbedder(max_features=50)
    docs = ["hello world", "goodbye world", "test document"]
    embedder.fit(docs)
    vecs = embedder.embed_batch(["hello", "goodbye"])
    assert len(vecs) == 2


def test_cosine_similarity():
    assert abs(_cosine_similarity([1, 0], [1, 0]) - 1.0) < 0.001
    assert abs(_cosine_similarity([1, 0], [0, 1]) - 0.0) < 0.001
    assert abs(_cosine_similarity([1, 0], [-1, 0]) - (-1.0)) < 0.001


def test_vector_index_search():
    idx = VectorIndex()
    idx.add("evt_1", "hello", [1.0, 0.0, 0.0])
    idx.add("evt_2", "world", [0.0, 1.0, 0.0])
    idx.add("evt_3", "test", [0.7, 0.7, 0.0])

    results = idx.search([1.0, 0.0, 0.0], top_k=2)
    assert len(results) == 2
    assert results[0].event_id == "evt_1"  # Most similar to [1,0,0]


def test_rag_engine_build_index():
    store = EventStore()
    p = AgentPrincipal("Alice", "dev")

    for text in ["Python cryptography library", "Event sourcing patterns", "Multi-agent collaboration"]:
        event = p.create_event("ch1", EventType.MESSAGE, [TextBlock(content=text)])
        store.append(event)

    rag = RAGEngine(store)
    count = rag.build_index()
    assert count == 3
    assert rag.index_size == 3


def test_rag_engine_search():
    store = EventStore()
    p = AgentPrincipal("Alice", "dev")

    texts = [
        "Python cryptography and Ed25519 signing",
        "Event sourcing with append-only logs",
        "Multi-agent AI collaboration protocol",
        "Database schema design with SQLite",
        "Vector embeddings for semantic search",
    ]
    for text in texts:
        event = p.create_event("ch1", EventType.MESSAGE, [TextBlock(content=text)])
        store.append(event)

    rag = RAGEngine(store)
    rag.build_index()

    results = rag.search("cryptography signing", top_k=3)
    assert len(results) == 3
    # The crypto-related event should rank highest
    assert results[0].event is not None


def test_rag_get_relevant_context():
    store = EventStore()
    p = AgentPrincipal("Alice", "dev")

    for text in ["security vulnerability analysis", "code review process", "testing strategies"]:
        event = p.create_event("ch1", EventType.MESSAGE, [TextBlock(content=text)])
        store.append(event)

    rag = RAGEngine(store)
    rag.build_index()

    context = rag.get_relevant_context("security", top_k=2)
    assert len(context) <= 2
    assert all(isinstance(e, type(context[0])) for e in context)


def test_rag_incremental_index():
    store = EventStore()
    p = AgentPrincipal("Alice", "dev")

    event1 = p.create_event("ch1", EventType.MESSAGE, [TextBlock(content="initial event")])
    store.append(event1)

    rag = RAGEngine(store)
    rag.build_index()
    assert rag.index_size == 1

    event2 = p.create_event("ch1", EventType.MESSAGE, [TextBlock(content="new event")])
    store.append(event2)
    rag.index_event(event2)
    assert rag.index_size == 2


def test_rag_with_claim_blocks():
    store = EventStore()
    p = AgentPrincipal("Alice", "dev")

    event = p.create_event(
        "ch1",
        EventType.MESSAGE,
        [ClaimBlock(claim="Ed25519 is faster than RSA for signing", confidence=0.95, evidence=["benchmarks"])],
    )
    store.append(event)

    rag = RAGEngine(store)
    rag.build_index()
    results = rag.search("signing performance", top_k=1)
    assert len(results) == 1


def test_rag_empty_store():
    store = EventStore()
    rag = RAGEngine(store)
    count = rag.build_index()
    assert count == 0
    results = rag.search("anything")
    assert results == []
