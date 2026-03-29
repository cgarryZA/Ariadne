# Ariadne — Developer Guide

## Architecture

```
server.py          Thin entry point: creates FastMCP, registers tools, defines resources/prompts
tools/             MCP tool modules (each exports register(mcp))
  __init__.py      register_all() orchestrator
  _constants.py    Shared paths (PAPERS_DIR, EXPORT_DIR)
  _text_processing.py  Token budget management, noise stripping, section slicing (Phase 0)
  _llm_client.py   Internal LLM client — model routing, JSON enforcement, cascade (Phase 0)
  formatting.py    Shared display helpers (format_result, format_paper)
  setup.py         First-run wizard, auto-detect pillars, config management
  discovery.py     Multi-source search (Semantic Scholar, OpenAlex, arXiv)
  library.py       Paper CRUD, tagging, rating, annotation
  screening.py     PRISMA screening, bulk extraction, dedup
  analysis.py      Gap analysis, evidence synthesis, comparison, stats
  reading.py       Summarize, extract findings, quality assessment, PDF download
  classification.py  Oxford three-move model (foundational/gap/parallel)
  synthesis.py     Contradiction detection, auto-synthesis, iterative research loop (Phase 3)
  concepts.py      Concept graph — extract, link, query academic concepts (Phase 2)
  network.py       Author/institution network mapping via OpenAlex (Phase 4)
  latex.py         LaTeX export with \cite{} commands (Phase 4)
  writing.py       Draft sections, review outline, assemble review
  monitoring.py    Watch list, citation network building, citation context extraction
  export.py        BibTeX import/export
apis/              External API clients
  semantic_scholar.py  S2 API (search, citations, references, recommendations)
  openalex.py      OpenAlex API (search, DOI lookup, author search, co-author networks)
  arxiv_client.py  arXiv Atom XML API
db.py              Async SQLite layer (singleton connection, FTS5, concept graph)
db_sync.py         Sync SQLite mirror for Streamlit dashboard
models.py          Pydantic models (Paper, Author, Citation, SearchResult, ExtractionResult, enums)
bibtex.py          BibTeX import (bibtexparser) / export
app.py             Streamlit dashboard
```

## Key patterns

- **Tool registration**: Each `tools/*.py` module exports `register(mcp)` which decorates async functions with `@mcp.tool()`.
- **Database**: Singleton async connection via `db.init()` / `db.get_db()`. Schema runs once. FTS5 for full-text search. Health-check auto-reconnect.
- **Config**: `config` table in SQLite stores pillars, extraction fields, research question as JSON. Use `db.get_pillars()`, `db.get_extraction_fields()`.
- **Pillars**: Free-text strings (not an enum). Configured via `setup_review()` or `auto_detect_pillars()`.
- **INSERT safety**: `insert_paper()` uses INSERT OR IGNORE + UPDATE of API fields only. User annotations are never overwritten.
- **HTTP clients**: Module-level singletons with connection pooling. Call `close_client()` on shutdown.
- **Text processing**: All fulltext passes through `_text_processing.py` before being returned to Claude. Strips noise sections, slices to relevant sections per tool, hard-caps at token budget.
- **LLM client**: Optional internal Anthropic client (`_llm_client.py`). When available, tools auto-extract using cheap models (Haiku) instead of consuming conversation tokens. Confidence cascade escalates to Sonnet when Haiku is unsure.
- **Concept graph**: `concepts`, `concept_paper_links`, `concept_edges` tables. Concepts link to papers with relation types (introduces, extends, applies, critiques, uses). Concept-to-concept edges (extends, replaces, contradicts).
- **Graceful degradation**: All optional features degrade gracefully. No ANTHROPIC_API_KEY -> tools return prompts as before. No pdfplumber -> download without text extraction. No tiktoken -> char/4 estimate. No bibtexparser -> regex fallback.

## Running

```bash
# MCP server
python server.py

# Dashboard
python -m streamlit run app.py

# Install with all optional deps
pip install -e ".[all]"
```

## Adding a new tool

1. Choose the appropriate module in `tools/` (or create a new one)
2. Add your async function inside the module's `register(mcp)` function
3. Decorate with `@mcp.tool()`
4. If creating a new module, add it to `tools/__init__.py`'s `_MODULES` list and imports

## Database

SQLite with 9 tables: `papers`, `citations`, `concepts`, `concept_paper_links`, `concept_edges`, `search_history`, `watch_seeds`, `pdf_fulltext`, `config`.
FTS5 virtual table `papers_fts` for full-text search (degrades gracefully if unavailable).

## Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `S2_API_KEY` | *(none)* | Semantic Scholar API key |
| `OPENALEX_MAILTO` | *(none)* | Email for OpenAlex polite pool |
| `ANTHROPIC_API_KEY` | *(none)* | Internal LLM client |
| `ARIADNE_DB` | `./papers.db` | SQLite database path |
| `ARIADNE_PAPERS_DIR` | `./pdfs/` | PDF storage |
| `ARIADNE_EXPORT_DIR` | `./` | Export directory |
| `ARIADNE_FAST_MODEL` | `claude-haiku-4-5-20251001` | Fast-tier model |
| `ARIADNE_REASONING_MODEL` | `claude-sonnet-4-5-20241022` | Reasoning-tier model |
| `ARIADNE_CASCADE_THRESHOLD` | `75` | Haiku->Sonnet escalation threshold |
