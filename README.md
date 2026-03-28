<p align="center">
  <img src="Logo.png" alt="Ariadne" width="280">
</p>

<p align="center">
  <strong>Research question → complete literature review, powered by Claude Code.</strong><br>
  An open-source MCP server that turns Claude into a full academic research assistant.
</p>

<p align="center">
  Powered by <a href="https://www.semanticscholar.org/">Semantic Scholar</a> + <a href="https://openalex.org/">OpenAlex</a> + <a href="https://arxiv.org/">arXiv</a> &nbsp;·&nbsp; Built on <a href="https://github.com/jlowin/fastmcp">FastMCP</a>
</p>

---

## How it works

You give Claude a research question. Ariadne handles the rest.

**1. You ask a question** — *"What deep learning methods exist for solving high-dimensional BSDEs?"*

**2. Claude searches the literature** — Queries Semantic Scholar, OpenAlex, and arXiv simultaneously. Finds relevant papers, follows citation trails, discovers connected work you'd never find manually.

**3. You screen and filter** — Claude reads every abstract and applies your criteria: what's relevant, what's not, what needs a closer look. Papers that don't make the cut are tagged out. A PRISMA audit trail is generated automatically.

**4. Claude reads and analyses** — For each paper that passes screening, Claude writes a comprehensive summary, extracts key findings, evaluates methodological quality, and fills in structured comparison fields (methodology, limitations, convergence bounds, mathematical framework).

**5. You organise the literature** — Papers are classified into the Oxford three-move framework:
- **Foundational** — the established, uncontroversial work everyone cites
- **Gap** — papers that identify what's missing or broken
- **Parallel** — recent attempts to fill those gaps

Papers are also grouped by theme, so multi-topic reviews are natively supported.

**6. Claude writes the review** — You choose a structure (Block, Parallel, or Mixed style per the [Oxford guide](https://lifelong-learning.ox.ac.uk/about/writing-literature-reviews)), approve an outline, and Claude drafts the complete literature review with inline `[AuthorYear]` citations and smooth transitions between sections.

**7. You export** — BibTeX file generated for every cited paper.

Everything Claude discovers and writes is stored locally in a SQLite database — summaries, findings, quality scores, and move classifications persist across sessions and compound over time.

---

## What it replaces

| Paid tool | What Ariadne does instead |
|-----------|--------------------------|
| **Elicit** | Searches 680M+ papers across 3 databases, extracts structured fields, builds comparison matrices |
| **Connected Papers / LitMaps** | Crawls citation networks, finds cross-pillar bridge papers, monitors for new citations |
| **SciSpace DeepReview** | Drafts complete review sections from your library with full context and citations |
| **Consensus** | Synthesises evidence across papers on yes/no research questions |
| **Paper Digest** | Auto-summarises every paper with AI-generated TLDR + your own Claude summaries |
| **Zotero** | Local SQLite library with tags, pillars, chapters, reading status, BibTeX export |
| **NotebookLM** | Annotates papers, compares approaches, identifies research gaps |

---

## Quick Start

### 1. Install

```bash
pip install fastmcp httpx aiosqlite pydantic

# Optional: visual dashboard
pip install streamlit networkx pyvis
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
        "S2_API_KEY": "your_optional_key_here"
      }
    }
  }
}
```

> **Semantic Scholar API key** is optional but recommended — raises your rate limit from 1 to 10 requests/second. Get one free at [semanticscholar.org/product/api](https://www.semanticscholar.org/product/api).

### 3. Start using it

Just talk to Claude naturally:

```
Search for papers on transformer attention mechanisms from 2020 onwards
```
```
Add this paper to my library: ARXIV:1706.03762
```
```
Do a full literature review on mean-field game theory applied to financial markets
```

---

## The Pipeline (technical detail)

For those who want to understand or customise the workflow:

```
1. DEFINE     →  generate_search_strategy(question)
2. DISCOVER   →  multi_search() + add_paper() + build_citation_network()
3. SCREEN     →  screen_papers(include/exclude criteria) → generate_prisma_report()
4. ANALYSE    →  summarize_paper() → extract_key_findings() → assess_quality()
5. ORGANISE   →  set_themes() → classify_moves() → generate_synthesis_matrix()
6. STRUCTURE  →  generate_review_outline(question, style) → assign_chapter()
7. WRITE      →  assemble_review(outline) → complete literature review with citations
8. EXPORT     →  export_bibtex()
```

The Oxford three-move model structures the output:
- **Foundational** — established facts, widely-cited older work
- **Gap** — papers questioning current knowledge, identifying problems
- **Parallel** — recent research attempting to fill gaps

Three organisational styles: **Block** (complete each topic before the next), **Parallel** (all foundational, then all gaps, then all parallel), **Mixed** (foundational+gap per topic, parallel across all). Based on the [Oxford guide for multi-topic literature reviews](https://lifelong-learning.ox.ac.uk/about/writing-literature-reviews).

---

## MCP Tools Reference (52 tools)

### Discovery — Find phase
| Tool | Description |
|------|-------------|
| `search_papers(query, limit, year_range, fields_of_study)` | Search Semantic Scholar (180M+ papers) |
| `search_openalex(query, limit, year_range)` | Search OpenAlex (250M+ papers, fully open) |
| `search_arxiv(query, categories, max_results)` | Search arXiv preprints (cs.LG, math.PR, q-fin.TR…) |
| `multi_search(query, limit, year_range, sources)` | Search all three sources simultaneously, deduplicated |
| `get_citations(paper_id, limit)` | Papers that cite this paper |
| `get_references(paper_id, limit)` | Papers this paper cites |
| `find_related(paper_id, limit)` | S2 AI recommendations |
| `seed_library(author_name, limit)` | Browse an author's full catalogue |
| `build_citation_network(paper_id, depth, direction, add_to_library)` | Recursively crawl and store citation graph |

### Library Management — Filter phase
| Tool | Description |
|------|-------------|
| `add_paper(paper_id)` | Add by S2 ID, `DOI:xxx`, or `ARXIV:xxx` |
| `remove_paper(paper_id)` | Remove from library |
| `list_library(status, pillar, tag, chapter, sort_by)` | Browse with filters |
| `get_paper_details(paper_id)` | Full metadata for a library paper |
| `tag_paper(paper_id, tags)` | Add comma-separated tags |
| `set_pillar(paper_id, pillar)` | Assign to `pure_math` / `computational` / `financial` |
| `set_status(paper_id, status)` | `unread` → `skimmed` → `read` → `deep_read` |
| `rate_paper(paper_id, relevance)` | 1–5 relevance score |
| `assign_chapter(paper_id, chapter)` | Map to a writing section |
| `annotate(paper_id, notes, append)` | Add free-form notes |
| `deduplicate_library()` | Find and report duplicate papers (DOI or title match) |

### Screening — Filter/PRISMA phase
| Tool | Description |
|------|-------------|
| `screen_papers(paper_ids, include_criteria, exclude_criteria)` | Format papers for systematic abstract screening |
| `generate_prisma_report()` | PRISMA 2020-style flow diagram from search history + statuses |

### Structured Extraction — Read phase
| Tool | Description |
|------|-------------|
| `set_extraction(paper_id, methodology, limitations, math_framework, convergence_bounds)` | Populate Elicit-style columns |
| `bulk_extract(paper_ids, pillar, chapter, fields)` | Format multiple papers for batch extraction |
| `compare_papers(paper_ids)` | Side-by-side comparison of extraction fields |
| `search_library_local(query)` | Full-text search within your library |

### Analysis — Map phase
| Tool | Description |
|------|-------------|
| `find_bridges()` | Papers that cite across research pillars |
| `identify_gaps(research_question, pillar, chapter)` | Format library for gap identification |
| `evidence_consensus(question, pillar, tag)` | Consensus-style evidence synthesis on a yes/no question |
| `library_stats()` | Counts by status, pillar, chapter |
| `get_papers_by_pillar(pillar)` | All papers in a pillar |
| `get_papers_by_chapter(chapter)` | All papers mapped to a section |

### Writing — Structure/Write phase
| Tool | Description |
|------|-------------|
| `draft_section(chapter, pillar, research_question, word_target, style)` | Structured context for drafting a review section |
| `export_bibtex(paper_ids, output_path)` | Export library or selection as `.bib` |
| `import_from_bibtex(bib_path)` | Bulk-import from `.bib`, enriched via S2 |

### Monitoring — Continuous awareness
| Tool | Description |
|------|-------------|
| `watch_add(paper_ids)` | Add seed papers to the citation watch list |
| `watch_remove(paper_id)` | Remove from watch list |
| `watch_check(limit_per_seed)` | Check for new papers citing your seed set |

### PDF
| Tool | Description |
|------|-------------|
| `download_pdf(paper_id)` | Download open-access PDF; extracts text if pdfplumber installed |

### Pipeline — Define
| Tool | Description |
|------|-------------|
| `generate_search_strategy(research_question, field, num_themes)` | Generate systematic search strategy with queries per theme |

### Pipeline — Read & Analyse
| Tool | Description |
|------|-------------|
| `summarize_paper(paper_id)` | Format paper for comprehensive summarisation |
| `store_summary(paper_id, summary)` | Persist Claude-generated summary |
| `extract_key_findings(paper_id)` | Format paper for key-findings extraction |
| `store_key_findings(paper_id, findings)` | Persist extracted findings |
| `assess_quality(paper_id)` | Format paper for quality/rigor assessment |
| `store_quality(paper_id, score, notes)` | Persist quality score (1-5) and justification |

### Pipeline — Organise (Oxford three-move)
| Tool | Description |
|------|-------------|
| `classify_moves(pillar, chapter)` | Format papers for foundational/gap/parallel classification |
| `set_move(paper_id, move)` | Store Oxford move classification |
| `set_themes(paper_id, themes)` | Assign thematic tags (separate from regular tags) |
| `generate_synthesis_matrix(paper_ids, dimensions)` | Cross-paper comparison table |

### Pipeline — Structure & Write
| Tool | Description |
|------|-------------|
| `generate_review_outline(research_question, structure_style, themes)` | Propose outline using Block/Parallel/Mixed Oxford style |
| `assemble_review(sections_json, word_target, research_question)` | Draft complete literature review from structured outline |

---

## Streamlit Dashboard

A visual dashboard for browsing and editing your library.

```bash
python -m streamlit run app.py
```

Opens at **http://localhost:8501** with four pages:

- **Dashboard** — library stats, reading pipeline, top-cited papers, priority queue
- **Papers** — filterable/searchable list with inline quick-edit
- **Citation Graph** — interactive network (node size ∝ citation count, colour ∝ pillar)
- **Edit Paper** — full metadata + structured extraction form

---

## Configuration

All settings via environment variables (or a `.env` file):

| Variable | Default | Description |
|----------|---------|-------------|
| `S2_API_KEY` | *(none)* | Semantic Scholar API key |
| `ARIADNE_DB` | `./papers.db` | Path to SQLite database |
| `ARIADNE_PAPERS_DIR` | `./pdfs/` | Directory for local PDFs |
| `ARIADNE_EXPORT_DIR` | `./` | Default BibTeX export directory |

---

## Research Pillars

Papers can be assigned to one of three pillars, which drive colour-coding in the dashboard and the `find_bridges()` analysis:

| Pillar | Colour | Icon |
|--------|--------|------|
| `pure_math` | Blue `#58a6ff` | ∂ |
| `computational` | Green `#3fb950` | λ |
| `financial` | Red `#f78166` | ₿ |

You can use these for any classification scheme that makes sense for your field.

---

## Database Schema

Papers are stored in `papers.db` (SQLite). The schema includes:

- **Bibliographic**: `title`, `authors`, `year`, `venue`, `doi`, `arxiv_id`, `url`, `pdf_url`
- **S2 metadata**: `citation_count`, `tldr`, `abstract`, `bibtex`
- **User fields**: `pillar`, `tags`, `status`, `relevance`, `notes`, `chapter`
- **Extraction**: `methodology`, `limitations`, `math_framework`, `convergence_bounds`

The database is gitignored by default. Back it up manually if needed.

---

## License

MIT
