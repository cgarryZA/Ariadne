"""Persistent vector store for semantic retrieval across the paper library.

Phase 2.3b: ChromaDB integration for persistent embeddings. Papers are embedded
once at ingest time (during download_pdf or explicit index_library) and stored
persistently alongside the SQLite database. Queries are instant — no re-embedding.

Architecture:
  - ChromaDB collection "ariadne_papers" stores (paper_id, embedding, metadata)
  - Each paper gets two document entries: title+abstract and fulltext chunks
  - Falls back to transient sentence-transformer search when ChromaDB is unavailable
  - Falls back further to FTS5 keyword search when neither is available

Graceful degradation chain:
  ChromaDB (persistent, instant)
    -> sentence-transformers (transient, re-embeds per query)
      -> FTS5 keyword search (always available)
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

_client = None
_collection = None
_available: Optional[bool] = None

# ChromaDB stores its data alongside the SQLite DB
_CHROMA_DIR = Path(os.environ.get(
    "ARIADNE_CHROMA_DIR",
    Path(os.environ.get("ARIADNE_DB", "./papers.db")).parent / "chroma_db"
))

COLLECTION_NAME = "ariadne_papers"

# Chunking config
CHUNK_SIZE = 800      # chars per chunk
CHUNK_OVERLAP = 100   # overlap between consecutive chunks


def is_available() -> bool:
    """True if chromadb is installed."""
    global _available
    if _available is not None:
        return _available
    try:
        import chromadb  # noqa: F401
        _available = True
    except ImportError:
        _available = False
    return _available


def _get_collection():
    """Lazy-init ChromaDB persistent client and collection."""
    global _client, _collection
    if _collection is not None:
        return _collection

    import chromadb
    _CHROMA_DIR.mkdir(parents=True, exist_ok=True)
    _client = chromadb.PersistentClient(path=str(_CHROMA_DIR))
    _collection = _client.get_or_create_collection(
        name=COLLECTION_NAME,
        metadata={"hnsw:space": "cosine"},
    )
    return _collection


def _chunk_text(text: str, chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    """Split text into overlapping chunks for granular retrieval."""
    if len(text) <= chunk_size:
        return [text]

    chunks = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunk = text[start:end]
        if chunk.strip():
            chunks.append(chunk.strip())
        start = end - overlap

    return chunks


async def index_paper(paper_id: str, title: str, abstract: Optional[str], fulltext: Optional[str]) -> int:
    """Index a paper's content into the vector store.

    Creates embedding entries for:
    1. Title + abstract (always, if abstract available)
    2. Fulltext chunks (if fulltext is stored)

    Returns the number of chunks indexed.
    """
    if not is_available():
        return 0

    collection = _get_collection()

    # Remove any existing entries for this paper (re-index)
    try:
        existing = collection.get(where={"paper_id": paper_id})
        if existing and existing["ids"]:
            collection.delete(ids=existing["ids"])
    except Exception:
        pass

    documents = []
    metadatas = []
    ids = []

    # Entry 1: title + abstract
    if abstract:
        doc = f"{title}\n\n{abstract}"
        documents.append(doc)
        metadatas.append({"paper_id": paper_id, "chunk_type": "abstract", "chunk_idx": 0})
        ids.append(f"{paper_id}__abstract")

    # Entry 2+: fulltext chunks
    if fulltext:
        chunks = _chunk_text(fulltext)
        for i, chunk in enumerate(chunks):
            documents.append(chunk)
            metadatas.append({"paper_id": paper_id, "chunk_type": "fulltext", "chunk_idx": i})
            ids.append(f"{paper_id}__chunk_{i}")

    if not documents:
        return 0

    # ChromaDB handles embedding internally (uses its default model)
    # or we can provide our own embeddings for consistency
    try:
        collection.add(documents=documents, metadatas=metadatas, ids=ids)
    except Exception:
        # If IDs already exist (race condition), upsert instead
        collection.upsert(documents=documents, metadatas=metadatas, ids=ids)

    return len(documents)


async def remove_paper(paper_id: str) -> None:
    """Remove all entries for a paper from the vector store."""
    if not is_available():
        return
    collection = _get_collection()
    try:
        existing = collection.get(where={"paper_id": paper_id})
        if existing and existing["ids"]:
            collection.delete(ids=existing["ids"])
    except Exception:
        pass


async def search(
    query: str,
    limit: int = 10,
    paper_ids: Optional[list[str]] = None,
) -> list[dict]:
    """Semantic search across the vector store.

    Returns list of dicts with keys: paper_id, chunk_type, chunk_idx, text, distance.
    Results are sorted by relevance (lowest distance = most similar).

    Args:
        query: Natural language query
        limit: Maximum results
        paper_ids: Optional filter to specific papers
    """
    if not is_available():
        return []

    collection = _get_collection()

    where_filter = None
    if paper_ids:
        where_filter = {"paper_id": {"$in": paper_ids}}

    results = collection.query(
        query_texts=[query],
        n_results=limit,
        where=where_filter,
        include=["documents", "metadatas", "distances"],
    )

    hits = []
    if results and results["ids"] and results["ids"][0]:
        for i, doc_id in enumerate(results["ids"][0]):
            hits.append({
                "paper_id": results["metadatas"][0][i]["paper_id"],
                "chunk_type": results["metadatas"][0][i]["chunk_type"],
                "chunk_idx": results["metadatas"][0][i]["chunk_idx"],
                "text": results["documents"][0][i],
                "distance": results["distances"][0][i],
            })

    return hits


async def get_stats() -> dict:
    """Return vector store statistics."""
    if not is_available():
        return {"available": False}

    collection = _get_collection()
    count = collection.count()

    # Count unique papers
    all_meta = collection.get(include=["metadatas"])
    paper_ids = set()
    if all_meta and all_meta["metadatas"]:
        for m in all_meta["metadatas"]:
            paper_ids.add(m.get("paper_id", ""))

    return {
        "available": True,
        "total_chunks": count,
        "papers_indexed": len(paper_ids),
        "storage_path": str(_CHROMA_DIR),
    }
