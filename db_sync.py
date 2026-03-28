"""Synchronous SQLite helpers for the Streamlit dashboard.

Mirrors the async db.py API but uses sqlite3 directly — Streamlit's
event loop doesn't support asyncio so we keep this completely separate.
"""

from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path
from typing import Optional

DB_PATH = Path(os.environ.get("ARIADNE_DB", Path(__file__).parent / "papers.db"))

SCHEMA = """
CREATE TABLE IF NOT EXISTS papers (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    authors TEXT,
    year INTEGER,
    venue TEXT,
    abstract TEXT,
    doi TEXT,
    arxiv_id TEXT,
    url TEXT,
    pdf_url TEXT,
    pdf_local_path TEXT,
    citation_count INTEGER,
    tldr TEXT,
    bibtex TEXT,
    added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    pillar TEXT,
    tags TEXT,
    status TEXT DEFAULT 'unread',
    relevance INTEGER,
    notes TEXT,
    methodology TEXT,
    limitations TEXT,
    math_framework TEXT,
    convergence_bounds TEXT,
    chapter TEXT
);

CREATE TABLE IF NOT EXISTS citations (
    citing_id TEXT,
    cited_id TEXT,
    is_influential BOOLEAN DEFAULT 0,
    PRIMARY KEY (citing_id, cited_id)
);

CREATE TABLE IF NOT EXISTS search_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    query TEXT,
    source TEXT,
    result_count INTEGER,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS watch_seeds (
    paper_id TEXT PRIMARY KEY,
    added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_checked TIMESTAMP
);

CREATE TABLE IF NOT EXISTS pdf_fulltext (
    paper_id TEXT PRIMARY KEY,
    text TEXT,
    extracted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def _parse(row: sqlite3.Row) -> dict:
    d = dict(row)
    d["authors"] = json.loads(d["authors"]) if d["authors"] else []
    d["tags"] = json.loads(d["tags"]) if d["tags"] else []
    return d


def get_all_papers(
    status: Optional[str] = None,
    pillar: Optional[str] = None,
    chapter: Optional[str] = None,
    tag: Optional[str] = None,
    sort_by: str = "citation_count",
) -> list[dict]:
    with get_conn() as conn:
        conditions, params = [], []
        if status:
            conditions.append("status = ?"); params.append(status)
        if pillar:
            conditions.append("pillar = ?"); params.append(pillar)
        if chapter:
            conditions.append("chapter = ?"); params.append(chapter)
        if tag:
            conditions.append("tags LIKE ?"); params.append(f'%"{tag}"%')

        where = (" WHERE " + " AND ".join(conditions)) if conditions else ""
        allowed = {"citation_count", "year", "relevance", "title", "added_at"}
        col = sort_by if sort_by in allowed else "citation_count"
        desc = " DESC" if col in ("citation_count", "year", "relevance", "added_at") else ""
        rows = conn.execute(
            f"SELECT * FROM papers{where} ORDER BY {col} IS NULL, {col}{desc}",
            params
        ).fetchall()
    return [_parse(r) for r in rows]


def get_paper(paper_id: str) -> Optional[dict]:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM papers WHERE id = ?", (paper_id,)).fetchone()
    return _parse(row) if row else None


def update_paper(paper_id: str, **fields) -> bool:
    if not fields:
        return False
    if "tags" in fields and isinstance(fields["tags"], list):
        fields["tags"] = json.dumps(fields["tags"])
    with get_conn() as conn:
        sets = ", ".join(f"{k} = ?" for k in fields)
        vals = list(fields.values()) + [paper_id]
        cur = conn.execute(f"UPDATE papers SET {sets} WHERE id = ?", vals)
        conn.commit()
    return cur.rowcount > 0


def get_all_citations() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM citations").fetchall()
    return [dict(r) for r in rows]


def stats() -> dict:
    with get_conn() as conn:
        total = conn.execute("SELECT COUNT(*) FROM papers").fetchone()[0]

        by_status = {}
        for r in conn.execute("SELECT status, COUNT(*) c FROM papers GROUP BY status").fetchall():
            by_status[r["status"] or "unread"] = r["c"]

        by_pillar = {}
        for r in conn.execute("SELECT pillar, COUNT(*) c FROM papers GROUP BY pillar").fetchall():
            by_pillar[r["pillar"] or "unassigned"] = r["c"]

        by_chapter = {}
        for r in conn.execute(
            "SELECT chapter, COUNT(*) c FROM papers WHERE chapter IS NOT NULL GROUP BY chapter"
        ).fetchall():
            by_chapter[r["chapter"]] = r["c"]

        recent = conn.execute(
            "SELECT query, source, result_count, timestamp FROM search_history "
            "ORDER BY timestamp DESC LIMIT 5"
        ).fetchall()

    return {
        "total": total,
        "by_status": by_status,
        "by_pillar": by_pillar,
        "by_chapter": by_chapter,
        "recent_searches": [dict(r) for r in recent],
    }


def get_tags() -> list[str]:
    """Return all unique tags used in the library."""
    with get_conn() as conn:
        rows = conn.execute("SELECT tags FROM papers WHERE tags IS NOT NULL AND tags != '[]'").fetchall()
    tags: set[str] = set()
    for row in rows:
        for t in json.loads(row["tags"]):
            tags.add(t)
    return sorted(tags)


def db_exists() -> bool:
    return DB_PATH.exists() and DB_PATH.stat().st_size > 0


def get_watch_list() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM watch_seeds ORDER BY added_at DESC").fetchall()
    return [dict(r) for r in rows]


def get_search_history(limit: int = 20) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM search_history ORDER BY timestamp DESC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(r) for r in rows]


def get_fulltext(paper_id: str) -> Optional[str]:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT text FROM pdf_fulltext WHERE paper_id = ?", (paper_id,)
        ).fetchone()
    return row["text"] if row else None


def prisma_counts() -> dict:
    """Return counts needed for a PRISMA flow diagram."""
    with get_conn() as conn:
        identified = conn.execute(
            "SELECT COALESCE(SUM(result_count), 0) FROM search_history"
        ).fetchone()[0]
        total = conn.execute("SELECT COUNT(*) FROM papers").fetchone()[0]
        by_status = {}
        for r in conn.execute("SELECT status, COUNT(*) c FROM papers GROUP BY status").fetchall():
            by_status[r["status"] or "unread"] = r["c"]
        screened_out = conn.execute(
            "SELECT COUNT(*) FROM papers WHERE tags LIKE '%\"screened-out\"%'"
        ).fetchone()[0]
        included = by_status.get("read", 0) + by_status.get("deep_read", 0)
    return {
        "identified": int(identified),
        "screened": total,
        "screened_out": screened_out,
        "assessed": total - screened_out,
        "included": included,
    }
