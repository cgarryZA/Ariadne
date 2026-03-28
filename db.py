"""SQLite database layer — async (used by the MCP server).

Uses a singleton connection to avoid repeated schema execution and
connection churn.  Call ``await init()`` once at startup (server.py does
this automatically) and ``await close()`` on shutdown.
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Optional

import aiosqlite

from models import Author, Citation, Move, Paper, ReadingStatus

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
    chapter TEXT,
    summary TEXT,
    key_findings TEXT,
    quality_score INTEGER,
    quality_notes TEXT,
    move TEXT,
    themes TEXT
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

CREATE TABLE IF NOT EXISTS config (
    key TEXT PRIMARY KEY,
    value TEXT
);
"""

# FTS5 virtual table — created separately because executescript cannot
# mix regular DDL with virtual-table DDL in every SQLite build.
FTS_SCHEMA = """
CREATE VIRTUAL TABLE IF NOT EXISTS papers_fts USING fts5(
    title, abstract, notes, authors,
    content='papers',
    content_rowid='rowid'
);
"""

FTS_TRIGGERS = """
CREATE TRIGGER IF NOT EXISTS papers_ai AFTER INSERT ON papers BEGIN
    INSERT INTO papers_fts(rowid, title, abstract, notes, authors)
    VALUES (new.rowid, new.title, new.abstract, new.notes, new.authors);
END;
CREATE TRIGGER IF NOT EXISTS papers_ad AFTER DELETE ON papers BEGIN
    INSERT INTO papers_fts(papers_fts, rowid, title, abstract, notes, authors)
    VALUES ('delete', old.rowid, old.title, old.abstract, old.notes, old.authors);
END;
CREATE TRIGGER IF NOT EXISTS papers_au AFTER UPDATE ON papers BEGIN
    INSERT INTO papers_fts(papers_fts, rowid, title, abstract, notes, authors)
    VALUES ('delete', old.rowid, old.title, old.abstract, old.notes, old.authors);
    INSERT INTO papers_fts(rowid, title, abstract, notes, authors)
    VALUES (new.rowid, new.title, new.abstract, new.notes, new.authors);
END;
"""

# ---------------------------------------------------------------------------
# Singleton connection
# ---------------------------------------------------------------------------

_conn: Optional[aiosqlite.Connection] = None


async def _open_connection() -> aiosqlite.Connection:
    """Open a fresh connection and run schema setup."""
    conn = await aiosqlite.connect(DB_PATH)
    conn.row_factory = aiosqlite.Row
    await conn.executescript(SCHEMA)
    # FTS5 and triggers — safe to re-run (IF NOT EXISTS)
    try:
        await conn.executescript(FTS_SCHEMA)
        await conn.executescript(FTS_TRIGGERS)
    except Exception:
        pass  # FTS5 not available — degrade gracefully
    await conn.commit()
    return conn


async def init() -> None:
    """Open the database and run schema migration (call once at startup)."""
    global _conn
    if _conn is not None:
        return
    _conn = await _open_connection()
    await _rebuild_fts()


async def close() -> None:
    """Close the singleton connection (call on shutdown)."""
    global _conn
    if _conn is not None:
        try:
            await _conn.close()
        except Exception:
            pass
        _conn = None


async def _reconnect() -> aiosqlite.Connection:
    """Drop the current connection and open a fresh one.

    Handles cases where the DB file was modified externally (e.g. ALTER TABLE
    from another process) and the cached connection is in a bad state.
    """
    global _conn
    if _conn is not None:
        try:
            await _conn.close()
        except Exception:
            pass
    _conn = await _open_connection()
    return _conn


async def get_db() -> aiosqlite.Connection:
    """Return the singleton connection, initialising if needed.

    If the connection is broken (e.g. external schema changes), automatically
    reconnects.
    """
    global _conn
    if _conn is None:
        await init()
        return _conn  # type: ignore[return-value]
    # Health check — try a trivial query; reconnect if it fails
    try:
        await _conn.execute("SELECT 1")
    except Exception:
        _conn = await _reconnect()
    return _conn  # type: ignore[return-value]


async def _rebuild_fts() -> None:
    """Populate the FTS index from existing paper rows (migration helper)."""
    db = await get_db()
    try:
        # Check if FTS table exists
        cursor = await db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='papers_fts'"
        )
        if not await cursor.fetchone():
            return
        # Only rebuild if FTS is empty
        cnt = (await (await db.execute("SELECT COUNT(*) c FROM papers_fts")).fetchone())["c"]
        if cnt > 0:
            return
        await db.execute(
            "INSERT INTO papers_fts(rowid, title, abstract, notes, authors) "
            "SELECT rowid, title, abstract, notes, authors FROM papers"
        )
        await db.commit()
    except Exception:
        pass  # FTS not available — that's fine


# ---------------------------------------------------------------------------
# Row parsing helpers
# ---------------------------------------------------------------------------

def _safe_json_loads(value, default=None):
    """Parse JSON, returning *default* on any failure."""
    if not value:
        return default if default is not None else []
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return default if default is not None else []


def _paper_from_row(row) -> Paper:
    d = dict(row)
    d["authors"] = _safe_json_loads(d.get("authors"), [])
    d["tags"] = _safe_json_loads(d.get("tags"), [])
    d["key_findings"] = _safe_json_loads(d.get("key_findings"), [])
    d["themes"] = _safe_json_loads(d.get("themes"), [])
    return Paper(**d)


def _serialize_authors(authors: list[Author]) -> str:
    return json.dumps([a.model_dump() for a in authors])


def _serialize_tags(tags: list[str]) -> str:
    return json.dumps(tags)


# ---------------------------------------------------------------------------
# Config helpers
# ---------------------------------------------------------------------------

_DEFAULT_EXTRACTION_FIELDS = ["methodology", "limitations", "math_framework", "convergence_bounds"]


async def get_config(key: str) -> Optional[str]:
    db = await get_db()
    cursor = await db.execute("SELECT value FROM config WHERE key = ?", (key,))
    row = await cursor.fetchone()
    return row["value"] if row else None


async def set_config(key: str, value: str) -> None:
    db = await get_db()
    await db.execute(
        "INSERT OR REPLACE INTO config (key, value) VALUES (?, ?)", (key, value)
    )
    await db.commit()


async def get_config_json(key: str, default=None):
    raw = await get_config(key)
    if raw is None:
        return default
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return default


async def set_config_json(key: str, value) -> None:
    await set_config(key, json.dumps(value))


async def get_pillars() -> list[str]:
    """Return configured pillar names, or an empty list if not yet set up."""
    return await get_config_json("pillars", [])


async def get_extraction_fields() -> list[str]:
    """Return configured extraction field names."""
    return await get_config_json("extraction_fields", _DEFAULT_EXTRACTION_FIELDS)


# ---------------------------------------------------------------------------
# Paper CRUD
# ---------------------------------------------------------------------------

# Fields that come from APIs and are safe to overwrite on re-add.
_API_FIELDS = {
    "title", "authors", "year", "venue", "abstract", "doi", "arxiv_id",
    "url", "pdf_url", "citation_count", "tldr", "bibtex",
}


async def insert_paper(paper: Paper) -> None:
    """Insert a paper. If it already exists, only update API-sourced metadata
    — user-managed fields (pillar, tags, notes, extraction, etc.) are preserved."""
    db = await get_db()
    # Try inserting first (IGNORE if already exists)
    await db.execute(
        """INSERT OR IGNORE INTO papers
        (id, title, authors, year, venue, abstract, doi, arxiv_id, url,
         pdf_url, pdf_local_path, citation_count, tldr, bibtex, added_at,
         pillar, tags, status, relevance, notes,
         methodology, limitations, math_framework, convergence_bounds, chapter,
         summary, key_findings, quality_score, quality_notes, move, themes)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            paper.id, paper.title, _serialize_authors(paper.authors),
            paper.year, paper.venue, paper.abstract, paper.doi,
            paper.arxiv_id, paper.url, paper.pdf_url, paper.pdf_local_path,
            paper.citation_count, paper.tldr, paper.bibtex,
            paper.added_at or datetime.now().isoformat(),
            paper.pillar,
            _serialize_tags(paper.tags), paper.status.value,
            paper.relevance, paper.notes,
            paper.methodology, paper.limitations,
            paper.math_framework, paper.convergence_bounds, paper.chapter,
            paper.summary, json.dumps(paper.key_findings),
            paper.quality_score, paper.quality_notes,
            paper.move.value if paper.move else None,
            json.dumps(paper.themes),
        ),
    )
    # Update only API-sourced metadata on existing rows
    await db.execute(
        """UPDATE papers SET
            title = ?, authors = ?, year = ?, venue = ?, abstract = ?,
            doi = ?, arxiv_id = ?, url = ?, pdf_url = ?,
            citation_count = ?, tldr = ?, bibtex = ?
        WHERE id = ?""",
        (
            paper.title, _serialize_authors(paper.authors),
            paper.year, paper.venue, paper.abstract, paper.doi,
            paper.arxiv_id, paper.url, paper.pdf_url,
            paper.citation_count, paper.tldr, paper.bibtex,
            paper.id,
        ),
    )
    await db.commit()


async def get_paper(paper_id: str) -> Optional[Paper]:
    db = await get_db()
    cursor = await db.execute("SELECT * FROM papers WHERE id = ?", (paper_id,))
    row = await cursor.fetchone()
    return _paper_from_row(row) if row else None


async def search_library(query: str) -> list[Paper]:
    """Full-text search across titles, abstracts, notes, and authors."""
    db = await get_db()
    # Try FTS5 first
    try:
        cursor = await db.execute(
            """SELECT p.* FROM papers_fts fts
               JOIN papers p ON p.rowid = fts.rowid
               WHERE papers_fts MATCH ?
               ORDER BY rank
               LIMIT 50""",
            (query,),
        )
        rows = await cursor.fetchall()
        if rows:
            return [_paper_from_row(r) for r in rows]
    except Exception:
        pass  # FTS not available, fall through to LIKE

    # Fallback: LIKE search
    cursor = await db.execute(
        """SELECT * FROM papers
        WHERE title LIKE ? OR abstract LIKE ? OR notes LIKE ? OR authors LIKE ?
        ORDER BY relevance DESC, citation_count DESC
        LIMIT 50""",
        (f"%{query}%", f"%{query}%", f"%{query}%", f"%{query}%"),
    )
    rows = await cursor.fetchall()
    return [_paper_from_row(r) for r in rows]


async def list_papers(
    status: Optional[str] = None,
    pillar: Optional[str] = None,
    tag: Optional[str] = None,
    chapter: Optional[str] = None,
    sort_by: str = "added_at",
    limit: int = 50,
) -> list[Paper]:
    db = await get_db()
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


async def update_paper(paper_id: str, **fields) -> bool:
    db = await get_db()
    if "authors" in fields and isinstance(fields["authors"], list):
        fields["authors"] = _serialize_authors(fields["authors"])
    if "tags" in fields and isinstance(fields["tags"], list):
        fields["tags"] = _serialize_tags(fields["tags"])
    if "status" in fields and isinstance(fields["status"], ReadingStatus):
        fields["status"] = fields["status"].value
    if "key_findings" in fields and isinstance(fields["key_findings"], list):
        fields["key_findings"] = json.dumps(fields["key_findings"])
    if "themes" in fields and isinstance(fields["themes"], list):
        fields["themes"] = json.dumps(fields["themes"])
    if "move" in fields and isinstance(fields["move"], Move):
        fields["move"] = fields["move"].value
    # Pillar is now a plain string — no enum conversion needed

    sets = ", ".join(f"{k} = ?" for k in fields)
    vals = list(fields.values()) + [paper_id]
    result = await db.execute(f"UPDATE papers SET {sets} WHERE id = ?", vals)
    await db.commit()
    return result.rowcount > 0


async def delete_paper(paper_id: str) -> bool:
    db = await get_db()
    result = await db.execute("DELETE FROM papers WHERE id = ?", (paper_id,))
    await db.execute(
        "DELETE FROM citations WHERE citing_id = ? OR cited_id = ?",
        (paper_id, paper_id),
    )
    await db.commit()
    return result.rowcount > 0


# ---------------------------------------------------------------------------
# Citations
# ---------------------------------------------------------------------------

async def insert_citations(citations: list[Citation]) -> None:
    if not citations:
        return
    db = await get_db()
    await db.executemany(
        "INSERT OR IGNORE INTO citations (citing_id, cited_id, is_influential) VALUES (?, ?, ?)",
        [(c.citing_id, c.cited_id, c.is_influential) for c in citations],
    )
    await db.commit()


# ---------------------------------------------------------------------------
# Library queries
# ---------------------------------------------------------------------------

async def get_library_ids() -> set[str]:
    db = await get_db()
    cursor = await db.execute("SELECT id FROM papers")
    rows = await cursor.fetchall()
    return {row["id"] for row in rows}


async def get_library_dois() -> set[str]:
    """Return all DOIs in the library, lowercased, for cross-source matching."""
    db = await get_db()
    cursor = await db.execute("SELECT doi FROM papers WHERE doi IS NOT NULL")
    rows = await cursor.fetchall()
    return {row["doi"].lower() for row in rows if row["doi"]}


async def library_stats() -> dict:
    db = await get_db()
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


async def log_search(query: str, source: str, result_count: int) -> None:
    db = await get_db()
    await db.execute(
        "INSERT INTO search_history (query, source, result_count) VALUES (?, ?, ?)",
        (query, source, result_count),
    )
    await db.commit()


async def find_bridges() -> list[dict]:
    """Find papers that cite across pillars (bridge papers)."""
    db = await get_db()
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


# ---------------------------------------------------------------------------
# Watch list
# ---------------------------------------------------------------------------

async def watch_add(paper_ids: list[str]) -> int:
    """Add paper IDs to the watch list. Returns number of new seeds added."""
    db = await get_db()
    added = 0
    for pid in paper_ids:
        result = await db.execute(
            "INSERT OR IGNORE INTO watch_seeds (paper_id) VALUES (?)", (pid,)
        )
        added += result.rowcount
    await db.commit()
    return added


async def watch_list() -> list[dict]:
    """Return all watch-list seeds with last_checked timestamps."""
    db = await get_db()
    cursor = await db.execute("SELECT * FROM watch_seeds ORDER BY added_at DESC")
    return [dict(r) for r in await cursor.fetchall()]


async def watch_remove(paper_id: str) -> bool:
    db = await get_db()
    result = await db.execute("DELETE FROM watch_seeds WHERE paper_id = ?", (paper_id,))
    await db.commit()
    return result.rowcount > 0


async def watch_mark_checked(paper_id: str) -> None:
    db = await get_db()
    await db.execute(
        "UPDATE watch_seeds SET last_checked = ? WHERE paper_id = ?",
        (datetime.now().isoformat(), paper_id),
    )
    await db.commit()


# ---------------------------------------------------------------------------
# PDF full-text
# ---------------------------------------------------------------------------

async def store_fulltext(paper_id: str, text: str) -> None:
    db = await get_db()
    await db.execute(
        "INSERT OR REPLACE INTO pdf_fulltext (paper_id, text) VALUES (?, ?)",
        (paper_id, text),
    )
    await db.commit()


async def get_fulltext(paper_id: str) -> Optional[str]:
    db = await get_db()
    cursor = await db.execute(
        "SELECT text FROM pdf_fulltext WHERE paper_id = ?", (paper_id,)
    )
    row = await cursor.fetchone()
    return row["text"] if row else None


# ---------------------------------------------------------------------------
# Search history
# ---------------------------------------------------------------------------

async def get_search_history(limit: int = 20) -> list[dict]:
    db = await get_db()
    cursor = await db.execute(
        "SELECT * FROM search_history ORDER BY timestamp DESC LIMIT ?", (limit,)
    )
    return [dict(r) for r in await cursor.fetchall()]
