<p align="center">
  <img src="Logo.png" alt="Ariadne" width="280">
</p>

<h1 align="center">Ariadne</h1>

<p align="center">
  <strong>A local, self-hosted literature review system for Claude Code.</strong><br>
  Search papers, build an annotated library, map citation networks, extract structured information, and export BibTeX — all from inside Claude without switching to Elicit, SciSpace, Connected Papers, or Zotero.
</p>

<p align="center">
  Powered by <a href="https://www.semanticscholar.org/">Semantic Scholar</a> + <a href="https://openalex.org/">OpenAlex</a> + <a href="https://arxiv.org/">arXiv</a> &nbsp;·&nbsp; Built on <a href="https://github.com/jlowin/fastmcp">FastMCP</a>
</p>

---

## What it replaces

| Tool | Ariadne equivalent |
|------|-------------------|
| **Elicit** | `search_papers` + `set_extraction` (methodology, limitations, convergence bounds) |
| **Connected Papers / LitMaps** | `get_citations`, `get_references`, `find_related`, `find_bridges` |
| **SciSpace** | `get_paper_details` + Claude reading the abstract directly |
| **Paper Digest** | Semantic Scholar TLDR exposed on every search result |
| **Zotero** | SQLite library + `export_bibtex`, `import_from_bibtex` |
| **NotebookLM** | `annotate`, `compare_papers` + Claude synthesis |

---

## Quick Start

### 1. Install dependencies

```bash
pip install fastmcp httpx aiosqlite pydantic

# Optional: Streamlit dashboard
pip install streamlit networkx pyvis
```

### 2. Configure Claude Code

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

> **Semantic Scholar API key** is optional but recommended — it raises your rate limit from 1 RPS to 10 RPS. Get a free key at [semanticscholar.org/product/api](https://www.semanticscholar.org/product/api).

### 3. Start using it

In Claude Code, just ask naturally:

```
Search for papers on transformer attention mechanisms from 2020 onwards
```
```
Add this paper to my library: ARXIV:1706.03762
```
```
What are the most cited papers that cite Han et al. 2018?
```

---

## MCP Tools Reference (39 tools)

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
