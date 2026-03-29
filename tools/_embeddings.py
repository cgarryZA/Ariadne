"""Local embedding utilities — zero-cost semantic similarity and search.

Phase 0.5: Use a local embedding model (sentence-transformers) for deduplication
and basic semantic search instead of pinging the LLM.

Graceful degradation: if sentence-transformers is not installed, falls back to
Jaccard word-set similarity (already in screening.py).
"""

from __future__ import annotations

from typing import Optional

_model = None
_available: Optional[bool] = None


def is_available() -> bool:
    """True if sentence-transformers is installed and a model is loadable."""
    global _available
    if _available is not None:
        return _available
    try:
        import sentence_transformers  # noqa: F401
        _available = True
    except ImportError:
        _available = False
    return _available


def _get_model():
    """Lazy-load the embedding model. ~90MB download on first use."""
    global _model
    if _model is not None:
        return _model
    from sentence_transformers import SentenceTransformer
    _model = SentenceTransformer("all-MiniLM-L6-v2")
    return _model


def embed_texts(texts: list[str]) -> list[list[float]]:
    """Embed a list of texts into dense vectors.

    Returns list of float vectors (384-dim for MiniLM).
    """
    model = _get_model()
    embeddings = model.encode(texts, show_progress_bar=False, normalize_embeddings=True)
    return embeddings.tolist()


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Cosine similarity between two normalized vectors (dot product)."""
    return sum(x * y for x, y in zip(a, b))


def find_semantic_duplicates(
    titles: list[str],
    threshold: float = 0.85,
) -> list[tuple[int, int, float]]:
    """Find pairs of titles that are semantically similar.

    Returns list of (idx_a, idx_b, similarity) tuples above threshold.
    """
    if not titles or len(titles) < 2:
        return []

    embeddings = embed_texts(titles)
    pairs = []

    for i in range(len(embeddings)):
        for j in range(i + 1, len(embeddings)):
            sim = cosine_similarity(embeddings[i], embeddings[j])
            if sim >= threshold:
                pairs.append((i, j, sim))

    return sorted(pairs, key=lambda x: -x[2])


def rank_by_similarity(
    query: str,
    documents: list[str],
    top_k: int = 10,
) -> list[tuple[int, float]]:
    """Rank documents by semantic similarity to a query.

    Returns list of (doc_index, similarity) sorted by descending similarity.
    """
    if not documents:
        return []

    all_texts = [query] + documents
    embeddings = embed_texts(all_texts)
    query_emb = embeddings[0]

    scores = []
    for i, doc_emb in enumerate(embeddings[1:]):
        sim = cosine_similarity(query_emb, doc_emb)
        scores.append((i, sim))

    scores.sort(key=lambda x: -x[1])
    return scores[:top_k]
