"""SQLite database layer — async (used by the MCP server)."""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Optional

import aiosqlite

from models import Author, Citation, Paper, Pillar, ReadingStatus

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


async def get_db() -> aiosqlite.Connection:
    db = await aiosqlite.connect(DB_PATH)
    db.row_factory = aiosqlite.Row
    await db.executescript(SCHEMA)
    return db


def _paper_from_row(row: aiosqlite.Row) -> Paper:
    d = dict(row)
    d["authors"] = json.loads(d["authors"]) if d["authors"] else []
    d["tags"] = json.loads(d["tags"]) if d["tags"] else []
    return Paper(**d)


def _serialize_authors(authors: list[Author]) -> str:
    return json.dumps([a.model_dump() for a in authors])


def _serialize_tags(tags: list[str]) -> str:
    return json.dumps(tags)


async def insert_paper(paper: Paper) -> None:
    db = await get_db()
    try:
        await db.execute(
            """INSERT OR REPLACE INTO papers
            (id, title, authors, year, venue, abstract, doi, arxiv_id, url,
             pdf_url, pdf_local_path, citation_count, tldr, bibtex, added_at,
             pillar, tags, status, relevance, notes,
             methodology, limitations, math_framework, convergence_bounds, chapter)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                paper.id, paper.title, _serialize_authors(paper.authors),
                paper.year, paper.venue, paper.abstract, paper.doi,
                paper.arxiv_id, paper.url, paper.pdf_url, paper.pdf_local_path,
                paper.citation_count, paper.tldr, paper.bibtex,
                paper.added_at or datetime.now().isoformat(),
                paper.pillar.value if paper.pillar else None,
                _serialize_tags(paper.tags), paper.status.value,
                paper.relevance, paper.notes,
                paper.methodology, paper.limitations,
                paper.math_framework, paper.convergence_bounds, paper.chapter,
            ),
        )
        await db.commit()
    finally:
        await db.close()


async def get_paper(paper_id: str) -> Optional[Paper]:
    db = await get_db()
    try:
        cursor = await db.execute("SELECT * FROM papers WHERE id = ?", (paper_id,))
        row = await cursor.fetchone()
        return _paper_from_row(row) if row else None
    finally:
        await db.close()


async def search_library(query: str) -> list[Paper]:
    """Full-text search across titles, abstracts, and notes in the local library."""
    db = await get_db()
    try:
        cursor = await db.execute(
            """SELECT * FROM papers
            WHERE title LIKE ? OR abstract LIKE ? OR notes LIKE ? OR authors LIKE ?
            ORDER BY relevance DESC, citation_count DESC
            LIMIT 50""",
            (f"%{query}%", f"%{query}%", f"%{query}%", f"%{query}%"),
        )
        rows = await cursor.fetchall()
        return [_paper_from_row(r) for r in rows]
    finally:
        await db.close()


async def list_papers(
    status: Optional[str] = None,
    pillar: Optional[str] = None,
    tag: Optional[str] = None,
    chapter: Optional[str] = None,
    sort_by: str = "added_at",
    limit: int = 50,
) -> list[Paper]:
    db = await get_db()
    try:
        conditions = []
        params: list = []

        if status:
            conditions.append("status = ?")
            params.append(status)
        if pillar:
            conditions.append("pillar = ?")
            params.append(pillar)
        if chapter:
            conditions.append("chapter = ?")
            params.append(chapter)
        if tag:
            conditions.append("tags LIKE ?")
            params.append(f'%"{tag}"%')

        where = " WHERE " + " AND ".join(conditions) if conditions else ""
        allowed_sorts = {"added_at", "year", "citation_count", "relevance", "title"}
        sort_col = sort_by if sort_by in allowed_sorts else "added_at"
        desc = " DESC" if sort_col in ("added_at", "year", "citation_count", "relevance") else ""

        query = f"SELECT * FROM papers{where} ORDER BY {sort_col}{desc} LIMIT ?"
        params.append(limit)

        cursor = await db.execute(query, params)
        rows = await cursor.fetchall()
        return [_paper_from_row(r) for r in rows]
    finally:
        await db.close()


async def update_paper(paper_id: str, **fields) -> bool:
    db = await get_db()
    try:
        if "authors" in fields and isinstance(fields["authors"], list):
            fields["authors"] = _serialize_authors(fields["authors"])
        if "tags" in fields and isinstance(fields["tags"], list):
            fields["tags"] = _serialize_tags(fields["tags"])
        if "pillar" in fields and isinstance(fields["pillar"], Pillar):
            fields["pillar"] = fields["pillar"].value
        if "status" in fields and isinstance(fields["status"], ReadingStatus):
            fields["status"] = fields["status"].value

        sets = ", ".join(f"{k} = ?" for k in fields)
        vals = list(fields.values()) + [paper_id]
        result = await db.execute(f"UPDATE papers SET {sets} WHERE id = ?", vals)
        await db.commit()
        return result.rowcount > 0
    finally:
        await db.close()


async def delete_paper(paper_id: str) -> bool:
    db = await get_db()
    try:
        result = await db.execute("DELETE FROM papers WHERE id = ?", (paper_id,))
        await db.execute(
            "DELETE FROM citations WHERE citing_id = ? OR cited_id = ?",
            (paper_id, paper_id),
        )
        await db.commit()
        return result.rowcount > 0
    finally:
        await db.close()


async def insert_citations(citations: list[Citation]) -> None:
    if not citations:
        return
    db = await get_db()
    try:
        await db.executemany(
            "INSERT OR IGNORE INTO citations (citing_id, cited_id, is_influential) VALUES (?, ?, ?)",
            [(c.citing_id, c.cited_id, c.is_influential) for c in citations],
        )
        await db.commit()
    finally:
        await db.close()


async def get_library_ids() -> set[str]:
    db = await get_db()
    try:
        cursor = await db.execute("SELECT id FROM papers")
        rows = await cursor.fetchall()
        return {row["id"] for row in rows}
    finally:
        await db.close()


async def library_stats() -> dict:
    db = await get_db()
    try:
        total = (await (await db.execute("SELECT COUNT(*) c FROM papers")).fetchone())["c"]

        by_status = {}
        cursor = await db.execute("SELECT status, COUNT(*) c FROM papers GROUP BY status")
        for row in await cursor.fetchall():
            by_status[row["status"]] = row["c"]

        by_pillar = {}
        cursor = await db.execute("SELECT pillar, COUNT(*) c FROM papers GROUP BY pillar")
        for row in await cursor.fetchall():
            by_pillar[row["pillar"] or "unassigned"] = row["c"]

        by_chapter = {}
        cursor = await db.execute(
            "SELECT chapter, COUNT(*) c FROM papers WHERE chapter IS NOT NULL GROUP BY chapter"
        )
        for row in await cursor.fetchall():
            by_chapter[row["chapter"]] = row["c"]

        return {
            "total": total,
            "by_status": by_status,
            "by_pillar": by_pillar,
            "by_chapter": by_chapter,
        }
    finally:
        await db.close()


async def log_search(query: str, source: str, result_count: int) -> None:
    db = await get_db()
    try:
        await db.execute(
            "INSERT INTO search_history (query, source, result_count) VALUES (?, ?, ?)",
            (query, source, result_count),
        )
        await db.commit()
    finally:
        await db.close()


async def find_bridges() -> list[dict]:
    """Find papers that cite across pillars (bridge papers)."""
    db = await get_db()
    try:
        cursor = await db.execute("""
            SELECT DISTINCT p1.id, p1.title, p1.pillar as p1_pillar, p2.pillar as p2_pillar
            FROM citations c
            JOIN papers p1 ON c.citing_id = p1.id
            JOIN papers p2 ON c.cited_id = p2.id
            WHERE p1.pillar IS NOT NULL AND p2.pillar IS NOT NULL
              AND p1.pillar != p2.pillar
            ORDER BY p1.title
        """)
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]
    finally:
        await db.close()


# ── Watch list ────────────────────────────────────────────────────────────────

async def watch_add(paper_ids: list[str]) -> int:
    """Add paper IDs to the watch list. Returns number of new seeds added."""
    db = await get_db()
    try:
        added = 0
        for pid in paper_ids:
            result = await db.execute(
                "INSERT OR IGNORE INTO watch_seeds (paper_id) VALUES (?)", (pid,)
            )
            added += result.rowcount
        await db.commit()
        return added
    finally:
        await db.close()


async def watch_list() -> list[dict]:
    """Return all watch-list seeds with last_checked timestamps."""
    db = await get_db()
    try:
        cursor = await db.execute("SELECT * FROM watch_seeds ORDER BY added_at DESC")
        return [dict(r) for r in await cursor.fetchall()]
    finally:
        await db.close()


async def watch_remove(paper_id: str) -> bool:
    db = await get_db()
    try:
        result = await db.execute("DELETE FROM watch_seeds WHERE paper_id = ?", (paper_id,))
        await db.commit()
        return result.rowcount > 0
    finally:
        await db.close()


async def watch_mark_checked(paper_id: str) -> None:
    db = await get_db()
    try:
        await db.execute(
            "UPDATE watch_seeds SET last_checked = ? WHERE paper_id = ?",
            (datetime.now().isoformat(), paper_id),
        )
        await db.commit()
    finally:
        await db.close()


# ── PDF full-text ─────────────────────────────────────────────────────────────

async def store_fulltext(paper_id: str, text: str) -> None:
    db = await get_db()
    try:
        await db.execute(
            "INSERT OR REPLACE INTO pdf_fulltext (paper_id, text) VALUES (?, ?)",
            (paper_id, text),
        )
        await db.commit()
    finally:
        await db.close()


async def get_fulltext(paper_id: str) -> Optional[str]:
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT text FROM pdf_fulltext WHERE paper_id = ?", (paper_id,)
        )
        row = await cursor.fetchone()
        return row["text"] if row else None
    finally:
        await db.close()


# ── Search history details ─────────────────────────────────────────────────────

async def get_search_history(limit: int = 20) -> list[dict]:
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT * FROM search_history ORDER BY timestamp DESC LIMIT ?", (limit,)
        )
        return [dict(r) for r in await cursor.fetchall()]
    finally:
        await db.close()
