# Ariadne — Developer Guide

## Architecture

```
server.py          Thin entry point: creates FastMCP, registers tools, defines resources/prompts
tools/             MCP tool modules (each exports register(mcp))
  __init__.py      register_all() orchestrator
  _constants.py    Shared paths (PAPERS_DIR, EXPORT_DIR)
  formatting.py    Shared display helpers (format_result, format_paper)
  setup.py         First-run wizard, auto-detect pillars, config management
  discovery.py     Multi-source search (Semantic Scholar, OpenAlex, arXiv)
  library.py       Paper CRUD, tagging, rating, annotation
  screening.py     PRISMA screening, bulk extraction, dedup
  analysis.py      Gap analysis, evidence synthesis, comparison, stats
  reading.py       Summarize, extract findings, quality assessment, PDF download
  classification.py  Oxford three-move model (foundational/gap/parallel)
  writing.py       Draft sections, review outline, assemble review
  monitoring.py    Watch list, citation network building
  export.py        BibTeX import/export
apis/              External API clients
  semantic_scholar.py  S2 API (search, citations, references, recommendations)
  openalex.py      OpenAlex API (search, DOI lookup)
  arxiv_client.py  arXiv Atom XML API
db.py              Async SQLite layer (singleton connection, FTS5)
db_sync.py         Sync SQLite mirror for Streamlit dashboard
models.py          Pydantic models (Paper, Author, Citation, SearchResult, enums)
bibtex.py          BibTeX import (bibtexparser) / export
app.py             Streamlit dashboard
```

## Key patterns

- **Tool registration**: Each `tools/*.py` module exports `register(mcp)` which decorates async functions with `@mcp.tool()`.
- **Database**: Singleton async connection via `db.init()` / `db.get_db()`. Schema runs once. FTS5 for full-text search.
- **Config**: `config` table in SQLite stores pillars, extraction fields, research question as JSON. Use `db.get_pillars()`, `db.get_extraction_fields()`.
- **Pillars**: Free-text strings (not an enum). Configured via `setup_review()` or `auto_detect_pillars()`.
- **INSERT safety**: `insert_paper()` uses INSERT OR IGNORE + UPDATE of API fields only. User annotations are never overwritten.
- **HTTP clients**: Module-level singletons with connection pooling. Call `close_client()` on shutdown.

## Running

```bash
# MCP server
python server.py

# Dashboard
python -m streamlit run app.py

# Install with optional deps
pip install -e ".[all]"
```

## Adding a new tool

1. Choose the appropriate module in `tools/` (or create a new one)
2. Add your async function inside the module's `register(mcp)` function
3. Decorate with `@mcp.tool()`
4. If creating a new module, add it to `tools/__init__.py`'s `_MODULES` list

## Database

SQLite with 6 tables: `papers`, `citations`, `search_history`, `watch_seeds`, `pdf_fulltext`, `config`.
FTS5 virtual table `papers_fts` for full-text search (degrades gracefully if unavailable).
