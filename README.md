<p align="center">
  <img src="Logo.png" alt="Ariadne" width="280">
</p>

<p align="center">
  <strong>A programmable research execution system.</strong><br>
  Research question in, structured literature review out — with full audit trail, knowledge graph, and LaTeX export.
</p>

<p align="center">
  <a href="https://opensource.org/licenses/MIT"><img src="https://img.shields.io/badge/License-MIT-yellow.svg" alt="License: MIT"></a>
  <a href="https://www.python.org/downloads/"><img src="https://img.shields.io/badge/python-3.11+-blue.svg" alt="Python 3.11+"></a>
  <a href="https://pypi.org/project/fastmcp/"><img src="https://img.shields.io/badge/MCP-FastMCP-purple.svg" alt="FastMCP"></a>
  <img src="https://img.shields.io/badge/tools-89-green.svg" alt="89 MCP Tools">
  <img src="https://img.shields.io/badge/APIs-S2%20%7C%20OpenAlex%20%7C%20arXiv%20%7C%20GitHub-orange.svg" alt="APIs">
  <img src="https://img.shields.io/badge/storage-SQLite%20%2B%20FTS5%20%2B%20ChromaDB-lightgrey.svg" alt="SQLite + FTS5 + ChromaDB">
</p>

<p align="center">
  Powered by <a href="https://www.semanticscholar.org/">Semantic Scholar</a> + <a href="https://openalex.org/">OpenAlex</a> + <a href="https://arxiv.org/">arXiv</a> &nbsp;&middot;&nbsp; Built on <a href="https://github.com/jlowin/fastmcp">FastMCP</a>
</p>

---

Ariadne is an open-source MCP server that turns Claude into a full academic research system. It executes every stage of a systematic literature review — multi-source discovery, PRISMA screening, structured extraction, concept graph construction, adversarial quality assessment, Oxford three-move classification, contradiction detection, and final review assembly with LaTeX export — with local persistence, semantic search, and methodological rigor.

89 tools. 12 database tables. 5 API integrations. 20 integration tests. Everything local. Everything persists across sessions.

---

## Architecture

```
                          User
                           |
                      Claude (Agent)
                     /      |      \
              Planner   Executor   Synthesizer
                           |
                   MCP Tool Layer (89 tools)
                  /    |     |      \       \
          Semantic  OpenAlex arXiv  GitHub  Internal LLM
          Scholar    API    API    API    (Haiku/Sonnet)
                  \    |     /               |
               SQLite + FTS5          ChromaDB
             (Knowledge Store)     (Vector Store)
            /    |     |     \          |
      Papers Concepts Citations  Embeddings
        |       |       |        (persistent)
   Extraction Concept  Citation      |
   + Schema   Graph   Network    Passage
   Validation  |       |        Retrieval
               |       |
          Theorem   Citation
          Dep DAG   Context
                           |
                   Synthesis Engine
                  /    |     |     \
          Review  BibTeX  LaTeX  Research
          Draft   Export  Export  Gap Gen
```

**Agent roles:**
- **Planner** — generates search strategies, proposes review outlines, suggests query refinements, identifies gaps
- **Executor** — runs searches, downloads PDFs, extracts structured data, builds citation and concept networks
- **Synthesizer** — detects contradictions, red-teams quality assessments, classifies moves, assembles the review

---

## How it works

**1. Define** — You provide a research question. Ariadne configures domain-specific pillars and extraction fields, or auto-detects them from your papers.

**2. Discover** — Queries Semantic Scholar (200M+ papers), OpenAlex (250M+), and arXiv simultaneously. Follows citation trails, maps co-author networks, discovers connected work. Deduplicates across sources using DOI, title, and semantic similarity.

**3. Screen** — PRISMA-compliant abstract screening with configurable inclusion/exclusion criteria. Automatic deduplication (DOI, exact title, fuzzy Jaccard, semantic embeddings). Full audit trail with `generate_prisma_report()`.

**4. Analyse** — For each paper: comprehensive summary, key findings extraction, quality scoring, and structured field extraction. When `ANTHROPIC_API_KEY` is set, these run automatically on cheap models (Haiku) — Claude never sees the full paper text. For critical papers, `red_team_assess()` spawns adversarial agents that debate the paper's quality and produce a balanced limitations paragraph.

**5. Organise** — Oxford three-move classification (foundational/gap/parallel), thematic tagging, concept graph construction. `build_theorem_graph()` parses mathematical proof dependencies into a DAG. `extract_concepts()` maps idea-level relationships (introduces, extends, critiques, replaces).

**6. Synthesize** — `detect_contradictions()` finds conflicting claims across papers. `auto_synthesize()` identifies methodological camps and tracks their evolution. `generate_future_research_gaps()` cross-references computational limitations against theoretical frameworks to propose PhD-level open problems. `standardize_notation()` translates math notation across papers into your glossary.

**7. Verify** — `github_reality_check()` scrapes linked repos and extracts undocumented implementation tricks (batch norm, gradient clipping, hyperparameters) that were omitted from the paper. `extract_citation_context()` classifies how each paper cites another: supporting, contrasting, or mentioning.

**8. Search** — `semantic_search()` finds papers by meaning, not keywords. `passage_search()` finds exact text passages across your entire library. Three-tier fallback: ChromaDB (instant, persistent) -> sentence-transformers (transient) -> FTS5 keywords.

**9. Write** — Choose Block, Parallel, or Mixed structure per the Oxford guide. Approve an outline. Ariadne assembles the complete review with `[AuthorYear]` citations and smooth transitions between sections.

**10. Export** — BibTeX with disambiguated cite keys. LaTeX export with `\cite{}` commands in article, IEEE, or ACM templates. Upload to Overleaf and compile.

Everything persists locally in SQLite + ChromaDB across sessions.

---

## The Pipeline

Three tiers of deterministic, logged review pipelines:

| Pipeline | Papers | Depth | Time |
|----------|--------|-------|------|
| `quick-review` | 15-30 | Key papers, overview | ~30 min |
| `standard-review` | 30-80 | Structured extraction, contradiction analysis | ~2 hrs |
| `deep-review` | 80-150+ | Full extraction, concept graph, red-teaming, code verification | ~4+ hrs |

Each pipeline follows a fixed tool sequence with logging. Every step is recorded in `pipeline_runs` — use `explain_pipeline_run()` to see exactly what happened.

```
 1. DEFINE      setup_review() + generate_search_strategy()
 2. DISCOVER    multi_search() + batch_add() + build_citation_network()
 3. SCREEN      screen_papers() + deduplicate_library() -> generate_prisma_report()
 4. EXTRACT     extract_structured_claims() + bulk_extract()
 5. ANALYSE     summarize_paper() + extract_key_findings() + red_team_assess()
 6. ORGANISE    classify_moves() + extract_concepts() + build_theorem_graph()
 7. SYNTHESIZE  detect_contradictions() + auto_synthesize() + generate_future_research_gaps()
 8. VERIFY      github_reality_check() + extract_citation_context()
 9. SEARCH      semantic_search() + passage_search()
10. STRUCTURE   generate_review_outline(style) + assign_chapter()
11. WRITE       assemble_review() + draft_section()
12. EXPORT      export_bibtex() + compile_to_latex()
```

---

## Quick Start

### 1. Install

```bash
# Core (required)
pip install fastmcp httpx aiosqlite pydantic bibtexparser tiktoken

# PDF text extraction (recommended)
pip install pdfplumber

# Internal LLM for auto-extraction (recommended — saves conversation tokens)
pip install anthropic

# Semantic search + dedup (recommended)
pip install sentence-transformers

# Persistent vector store for instant passage retrieval
pip install chromadb

# Math-aware PDF extraction (LaTeX-native, extracts equations/theorems)
pip install nougat-ocr torch

# Visual dashboard
pip install streamlit networkx pyvis

# Or install everything:
pip install -e ".[all]"
```

### 2. Connect to Claude Code

Add to your project's `.mcp.json`:

```json
{
  "mcpServers": {
    "ariadne": {
      "command": "python",
      "args": ["/absolute/path/to/ariadne/server.py"],
      "env": {
        "S2_API_KEY": "your_optional_key_here",
        "ANTHROPIC_API_KEY": "your_optional_key_here"
      }
    }
  }
}
```

> **Semantic Scholar API key** (free) — raises your rate limit from 1 to 10 RPS. Get one at [semanticscholar.org/product/api](https://www.semanticscholar.org/product/api).
>
> **Anthropic API key** (optional) — enables internal LLM routing. Summarization and extraction run on Haiku instead of consuming your conversation context. Cuts token costs dramatically.

### 3. Start using it

```
Search for papers on transformer attention mechanisms from 2020 onwards
```
```
Do a full literature review on mean-field game theory applied to financial markets
```
```
Red-team assess this paper and check if its GitHub repo matches the claims
```

**First-time users:** call `setup_review()` to configure your domain, or just start searching and use `auto_detect_pillars()` once you have ~10 papers.

---

## What it replaces

| Paid tool | What Ariadne does instead |
|-----------|--------------------------|
| **Elicit** ($10-49/mo) | Searches 450M+ papers across 3 databases, extracts structured fields with schema validation, builds comparison matrices |
| **Connected Papers** | Crawls citation networks, builds concept + theorem dependency graphs, finds cross-pillar bridge papers |
| **SciSpace DeepReview** | Drafts complete review sections with Oxford three-move structure, inline citations, and LaTeX export |
| **Consensus** | Synthesises evidence, detects contradictions via automated pairwise comparison, classifies supporting vs opposing |
| **Scite.ai** ($20/mo) | Extracts citation context — classifies each citation as supporting, contrasting, or mentioning |
| **Papers with Code** | GitHub reality check — scrapes repos, extracts undocumented tricks (batch norm, gradient clipping, hyperparameters) |
| **Zotero** | Local SQLite library with tags, pillars, chapters, reading status, BibTeX + LaTeX export, persistent vector store |
| **NotebookLM** | Concept graph, author network mapping, gap identification, research question refinement, passage search |
| **Semantic Scholar** | Combines S2 + OpenAlex + arXiv with federated dedup, then adds everything S2 doesn't do (screening, synthesis, writing) |

**Cost: Free.** Optional API keys for higher rate limits and internal LLM routing. All data stays local.

---

## Technical Design

### Retrieval Strategy

Multi-source querying with federated deduplication:
- **Semantic Scholar** — 200M+ papers, strong citation data, AI-generated TLDRs
- **OpenAlex** — 250M+ papers, fully open, rich author/institution metadata
- **arXiv** — Preprints, cutting-edge work not yet peer-reviewed
- **GitHub** — Implementation code linked from ML papers

Deduplication uses four layers: DOI matching, normalized title matching, Jaccard word-set similarity (>0.85), and semantic embedding similarity (when sentence-transformers installed).

### Knowledge Representation

SQLite with 12 tables:

| Table | Purpose |
|-------|---------|
| `papers` | Full metadata + user annotations (31 columns) |
| `citations` | Paper-to-paper citation edges |
| `concepts` | Academic concepts, methods, theories, theorems, lemmas |
| `concept_paper_links` | Concept-paper relationships (introduces, extends, applies, critiques, uses) |
| `concept_edges` | Concept-to-concept relationships (extends, replaces, contradicts, requires) |
| `structured_claims` | Falsifiable claims with metric/value/dataset for algorithmic comparison |
| `pipeline_runs` | Pipeline execution logs — every step, timing, results |
| `extraction_cache` | Local LLM result cache — $0 on repeat queries |
| `search_history` | Query audit trail for PRISMA reporting |
| `watch_seeds` | Citation monitoring watch list |
| `pdf_fulltext` | Extracted PDF text (noise-stripped on ingest) |
| `config` | Review configuration (pillars, fields, glossary) |

**FTS5** virtual table for ranked full-text keyword search.

**ChromaDB** (optional) persistent vector store for instant semantic search and passage retrieval. Papers auto-indexed at download time with 800-char overlapping chunks.

### Semantic Search Pipeline

Three-tier fallback chain:
1. **ChromaDB** (persistent, instant, chunk-level with passage previews) — `pip install chromadb`
2. **Sentence-transformers** (transient, re-embeds per query, paper-level) — `pip install sentence-transformers`
3. **FTS5** (keyword matching, always available)

### Math-Aware PDF Ingestion

Three-tier extraction chain:
1. **Nougat** (Meta's visual transformer, local, LaTeX-native) — `pip install nougat-ocr torch`
2. **Mathpix** (commercial API, LaTeX-native) — set `MATHPIX_APP_ID` + `MATHPIX_APP_KEY`
3. **pdfplumber** (plaintext fallback) — `pip install pdfplumber`

Math-aware methods extract structured components: equations, theorems, lemmas, definitions, assumptions, and proofs. These are stored as JSON and used by `build_theorem_graph()` and `standardize_notation()`.

### LLM Cost Orchestration

When `ANTHROPIC_API_KEY` is set, Ariadne routes extraction tasks to cheap models internally:

| Task | Model | Why |
|------|-------|-----|
| `summarize_paper` | Haiku | Text extraction, no reasoning needed |
| `extract_key_findings` | Haiku | Structured extraction |
| `extract_concepts` | Haiku | Named entity extraction |
| `assess_quality` | Sonnet | Requires judgment |
| `detect_contradictions` | Sonnet | Cross-paper comparison |
| `red_team_assess` | Sonnet | Adversarial multi-agent debate |

**Confidence Cascade:** Haiku returns a confidence score. Below threshold (default 75), the task auto-escalates to Sonnet.

**Prompt Caching:** Paper text blocks use Anthropic's `cache_control: ephemeral` — when running summarize -> extract_findings -> assess_quality on the same paper, only the first call pays full input price. Subsequent calls get 90% discount.

**Extraction Cache:** Local SQLite table stores `(hash(paper_text + task), result_json)`. Exact repeat queries cost $0 and return in milliseconds.

**Batch API:** `batch_extract()` uses Anthropic's Message Batch API for 50% cost reduction on bulk operations (5+ papers).

**Token Budget Management:**
1. Noise stripping (References, Appendix, Acknowledgements) — 15-25% savings
2. Section slicing (only relevant sections per task type) — additional 30-60%
3. Hard token cap per tool (4K summarization, 12K fulltext)
4. Schema validation (Pydantic models reject malformed LLM outputs)

Without the API key, everything works exactly as before — tools return formatted prompts and Claude processes them.

---

## MCP Tools Reference (89 tools)

### Setup & Configuration (4)
| Tool | Description |
|------|-------------|
| `setup_review()` | First-run wizard — configure pillars, fields, research question |
| `auto_detect_pillars()` | Analyze library and suggest domain pillars |
| `get_review_config()` | Show current configuration |
| `update_extraction_fields()` | Change extraction field names per domain |

### Discovery (8)
| Tool | Description |
|------|-------------|
| `search_papers()` | Search Semantic Scholar (200M+ papers) |
| `search_openalex()` | Search OpenAlex (250M+ papers, fully open) |
| `search_arxiv()` | Search arXiv preprints |
| `multi_search()` | Search all three simultaneously, deduplicated |
| `get_citations()` / `get_references()` | Citation traversal (stores edges to DB) |
| `find_related()` | S2 AI recommendations |
| `seed_library()` | Browse an author's catalogue |
| `build_citation_network()` | Recursive citation crawl with edge storage |

### Library Management (17)
| Tool | Description |
|------|-------------|
| `add_paper()` / `add_paper_openalex()` / `batch_add()` | Add papers from any source |
| `remove_paper()` | Remove from library |
| `list_library()` | Browse with filters (status, pillar, tag, chapter) |
| `get_paper_details()` / `get_fulltext()` | Retrieve paper content (budget-capped) |
| `tag_paper()` / `remove_tag()` / `list_tags()` | Tag management |
| `set_pillar()` / `set_status()` / `rate_paper()` | Classification |
| `assign_chapter()` / `annotate()` / `set_extraction()` | Metadata |
| `semantic_search()` | Search by meaning (ChromaDB -> embeddings -> FTS5) |
| `passage_search()` | Find exact passages across all papers |
| `index_library()` | Bulk-index papers into persistent vector store |

### Screening & Deduplication (4)
| Tool | Description |
|------|-------------|
| `screen_papers()` | PRISMA abstract screening with criteria |
| `bulk_extract()` | Batch structured extraction |
| `generate_prisma_report()` | PRISMA 2020 flow diagram |
| `deduplicate_library()` | DOI + title + Jaccard + semantic embedding dedup |

### Analysis & Synthesis (11)
| Tool | Description |
|------|-------------|
| `compare_papers()` | Side-by-side extraction field comparison |
| `find_bridges()` | Cross-pillar bridge papers |
| `identify_gaps()` | Coverage and gap analysis |
| `evidence_consensus()` | Evidence synthesis on yes/no questions |
| `generate_synthesis_matrix()` | Cross-paper comparison table |
| `extract_structured_claims()` | Extract falsifiable claims with metric/value/dataset/conditions |
| `detect_contradictions()` | Three-layer: algorithmic claim comparison -> LLM assessment -> manual |
| `auto_synthesize()` | Detect methodological camps, evolution, regressions |
| `refine_research_question()` | Analyze coverage and suggest refinements |
| `suggest_new_queries()` | Fill gaps with targeted searches |
| `generate_future_research_gaps()` | Cross-reference limitations vs frameworks for PhD-level proposals |
| `standardize_notation()` | Translate math notation to your master glossary |

### Reading & Quality Assessment (7)
| Tool | Description |
|------|-------------|
| `summarize_paper()` | Auto-summarize (LLM) or format for manual |
| `extract_key_findings()` | Auto-extract (LLM) or format for manual |
| `assess_quality()` | Standard quality/rigor assessment (1-5) |
| `red_team_assess()` | Adversarial multi-agent debate (Proponent vs Critic -> balanced score) |
| `download_pdf()` | Download PDF, extract text (Nougat/Mathpix/pdfplumber), auto-index |
| `store_summary()` / `store_key_findings()` / `store_quality()` | Persist assessments |

### Concept & Theorem Graph (6)
| Tool | Description |
|------|-------------|
| `extract_concepts()` | Auto-extract concepts from papers (LLM or manual) |
| `add_concept()` / `link_concepts()` | Manually build the graph |
| `query_concept()` | Look up concept across papers + related concepts |
| `list_concepts()` | Browse the full concept graph |
| `build_theorem_graph()` | Parse theorem/lemma dependencies into a DAG |

### Classification (3)
| Tool | Description |
|------|-------------|
| `classify_moves()` | Format for Oxford foundational/gap/parallel classification |
| `set_move()` / `set_themes()` | Store classifications |

### Author & Institution Networks (2)
| Tool | Description |
|------|-------------|
| `map_author_network()` | Co-author network + institutional affiliations via OpenAlex |
| `map_institution_landscape()` | Find researchers at an institution by topic |

### Code-to-Paper Alignment (2)
| Tool | Description |
|------|-------------|
| `github_reality_check()` | Auto-detect GitHub repos in paper, extract undocumented tricks |
| `github_reality_check_url()` | Analyze a specific repo against a paper's claims |

### Writing Pipeline (5)
| Tool | Description |
|------|-------------|
| `generate_search_strategy()` | Systematic multi-theme search plan |
| `draft_section()` | Context for drafting a review section (4 styles) |
| `generate_review_outline()` | Block/Parallel/Mixed Oxford outline |
| `assemble_review()` | Complete review from structured outline |
| `compile_to_latex()` | Export to .tex with `\cite{}` (article/IEEE/ACM templates) |

### Export & Import (2)
| Tool | Description |
|------|-------------|
| `export_bibtex()` | Export as `.bib` with disambiguated cite keys |
| `import_from_bibtex()` | Bulk-import from `.bib` with S2 enrichment |

### Pipeline & Logging (5)
| Tool | Description |
|------|-------------|
| `log_pipeline_start()` | Start a logged pipeline run |
| `log_pipeline_step()` | Record a step with results |
| `log_pipeline_complete()` | Mark run complete with summary |
| `explain_pipeline_run()` | Show every step, what was filtered, where uncertainty is highest |
| `list_pipeline_runs()` | List all pipeline runs with status |

### Monitoring & Citation Analysis (4)
| Tool | Description |
|------|-------------|
| `watch_add()` / `watch_remove()` / `watch_check()` | Citation monitoring |
| `extract_citation_context()` | Classify how one paper cites another (supporting/contrasting/mentioning) |

---

## Evaluation

### Capability comparison

| Feature | Ariadne | Elicit | Connected Papers | Scite.ai | Zotero |
|---------|---------|--------|-------------------|----------|--------|
| Multi-source retrieval | 3 databases | 1 | 1 | 1 | 0 |
| PRISMA workflow | Full | None | None | None | None |
| Structured extraction | Configurable + validated | Fixed fields | None | None | Manual |
| Oxford three-move model | Native | None | None | None | None |
| Concept graph | Bidirectional | None | Citation only | None | None |
| Theorem dependency DAG | From LaTeX | None | None | None | None |
| Contradiction detection | Structured claims + algorithmic + LLM | None | None | None | None |
| Red-team quality assessment | Adversarial multi-agent | None | None | None | None |
| Citation context classification | Supporting/contrasting/mentioning | None | None | Native | None |
| Code-to-paper alignment | GitHub scraping | None | None | None | None |
| Semantic search | ChromaDB + embeddings + FTS5 | Basic | None | None | Basic |
| Passage-level retrieval | Across full library | None | None | In-paper | None |
| Author network mapping | Via OpenAlex | None | None | None | None |
| Math-aware PDF extraction | Nougat/Mathpix | None | None | None | None |
| Notation standardization | LLM-powered glossary | None | None | None | None |
| PhD gap generation | Cross-domain proposals | None | None | None | None |
| LaTeX export | With `\cite{}` commands | None | None | None | BibTeX only |
| Internal LLM routing | Haiku/Sonnet cascade + caching | N/A | N/A | N/A | N/A |
| Cost | Free + optional API keys | $10-49/mo | Free tier limited | $20/mo | Free |
| Data ownership | 100% local | Cloud | Cloud | Cloud | Local |

### Token efficiency

- **Noise stripping** saves 15-25% input tokens per paper
- **Section slicing** saves additional 30-60%
- **Internal LLM routing** prevents full paper text from entering conversation
- **Confidence cascade** uses Haiku for ~80% of extractions
- **Prompt caching** gives 90% discount on multi-extraction per paper
- **Extraction cache** gives 100% discount on repeat queries
- **Batch API** gives 50% discount on bulk operations

---

## Configuration

### Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `S2_API_KEY` | *(none)* | Semantic Scholar API key (free, 10 RPS) |
| `OPENALEX_MAILTO` | *(none)* | Email for OpenAlex polite pool |
| `ANTHROPIC_API_KEY` | *(none)* | Internal LLM routing (optional) |
| `GITHUB_TOKEN` | *(none)* | GitHub API token for code-to-paper checks |
| `MATHPIX_APP_ID` | *(none)* | Mathpix API (optional math OCR) |
| `MATHPIX_APP_KEY` | *(none)* | Mathpix API key |
| `ARIADNE_DB` | `./papers.db` | SQLite database path |
| `ARIADNE_PAPERS_DIR` | `./pdfs/` | PDF storage directory |
| `ARIADNE_EXPORT_DIR` | `./` | Default export directory |
| `ARIADNE_CHROMA_DIR` | `./chroma_db/` | ChromaDB storage path |
| `ARIADNE_FAST_MODEL` | `claude-haiku-4-5-20251001` | Model for fast-tier tasks |
| `ARIADNE_REASONING_MODEL` | `claude-sonnet-4-5-20241022` | Model for reasoning-tier tasks |
| `ARIADNE_CASCADE_THRESHOLD` | `75` | Haiku-to-Sonnet escalation threshold |
| `ARIADNE_CACHE_EXTRACTIONS` | `1` | Set to `0` to disable extraction cache |

### Research pillars

Fully configurable:

```
setup_review(pillars='genomics|proteomics|metabolomics')
setup_review(pillars='theoretical|experimental|computational')
```

Or auto-detect from your library: `auto_detect_pillars()`

### Extraction fields

Also configurable per domain:

```
update_extraction_fields('methodology|sample_size|population|outcome_measure|bias_risk')
```

Default: `methodology | limitations | math_framework | convergence_bounds`

---

## Streamlit Dashboard

```bash
python -m streamlit run app.py
```

Four pages: **Dashboard** (stats, pipeline, priority queue), **Papers** (filterable list with inline edit), **Citation Graph** (interactive network), **Edit Paper** (full metadata form).

---

## Testing

```bash
pip install pytest pytest-asyncio
pytest tests/test_integration.py -v
```

20 integration tests verify key invariants with synthetic papers (no API calls):
- Deduplication detects exact title duplicates
- Extraction fields are populated correctly
- Pillar validation rejects unknown names with suggestions
- Paper ID resolution handles prefixes, title words, and author names
- Structured claims round-trip through the database
- Contradictory claims are algorithmically detectable
- Pipeline logging lifecycle works end-to-end
- Noise stripping removes references
- Token budgets are enforced
- All 89 tools register without errors

---

## Current Reliability

Ariadne is a structured reasoning environment for research, not a replacement for expert judgment. It accelerates review structure, discovery, and comparison — the human validates.

**What works well:**
- Multi-source discovery and deduplication is deterministic and reliable
- Citation network building produces ground-truth edges from APIs
- PRISMA audit trails are structurally correct by construction
- BibTeX/LaTeX export is mechanically sound

**What requires human validation:**
- Summaries and key findings are LLM-generated and may contain errors or omissions
- Quality assessments (including red-team) reflect LLM judgment, not ground truth
- Contradiction detection compares structured claims but may hallucinate disagreements or miss subtle differences in mathematical assumptions
- Concept extraction is approximate — concepts may be too broad, too narrow, or misclassified

**What is still early:**
- Mathematical content is extracted but not formally verified — notation standardization is heuristic, not symbolic
- Theorem dependency parsing relies on regex patterns and works best with LaTeX-extracted text
- GitHub code-to-paper alignment catches common ML tricks but won't find domain-specific implementation gaps

**Best practice:** Use Ariadne to build the scaffold (find papers, map connections, structure the review), then apply your domain expertise to validate every claim, especially anything quantitative or mathematical.

---

## Limitations

- **API dependence** — Search quality depends on Semantic Scholar, OpenAlex, and arXiv indexing. Papers not in these databases won't be found.
- **PDF extraction varies** — pdfplumber struggles with equations and complex layouts. Nougat produces excellent LaTeX but requires GPU and is slow. Mathpix is fast but requires a paid API key.
- **SQLite scaling** — Sufficient for individual reviews (hundreds to low thousands of papers). Not designed for institutional-scale deployment.
- **ChromaDB is optional** — Without it, semantic search re-embeds the library on each query. With it, queries are instant but storage grows.

---

## About the name

In Greek mythology, **Ariadne** gave Theseus a ball of golden thread before he entered the labyrinth to face the Minotaur. The thread let him trace his path through the maze and find his way back out.

A literature review is its own kind of labyrinth — hundreds of papers, tangled citation networks, contradictory findings, and dead ends. Ariadne is the thread that guides you through it.

---

## License

MIT
