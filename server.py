#!/usr/bin/env python3
"""
Ariadne — Academic Literature Review MCP Server

Provides tools for searching, managing, and analysing academic papers
via Semantic Scholar. Designed to be used from Claude Code or any
MCP-compatible client.

Run directly:  python server.py
Or via MCP:    configure in your Claude Code .mcp.json (see mcp.json.example)
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Optional

from fastmcp import FastMCP

# Ensure local modules are importable regardless of working directory
sys.path.insert(0, str(Path(__file__).parent))

import db
from apis import semantic_scholar as s2
from apis import openalex as oa
from apis import arxiv_client as arxiv
from bibtex import export_bibtex as _export_bib, parse_bibtex_file, bibtex_authors_to_list, paper_to_bibtex
from models import Author, Paper, Pillar, ReadingStatus, Citation, Move

# Configurable directories (override via environment variables)
PAPERS_DIR = Path(os.environ.get("ARIADNE_PAPERS_DIR", Path(__file__).parent / "pdfs"))
EXPORT_DIR = Path(os.environ.get("ARIADNE_EXPORT_DIR", Path.cwd()))

mcp = FastMCP(
    "ariadne",
    instructions=(
        "Ariadne is a local literature review system backed by Semantic Scholar. "
        "Use it to search for papers, manage a personal library, map citation networks, "
        "extract structured information (methodology, limitations, convergence bounds), "
        "and export BibTeX. Papers are organised into three research pillars: "
        "pure_math, computational, and financial."
    ),
)


# ── Helpers ──────────────────────────────────────────────────────────


def _format_result(r) -> str:
    """Format a SearchResult for display."""
    authors = ", ".join(a.name for a in r.authors[:3])
    if len(r.authors) > 3:
        authors += " et al."
    lib = " [IN LIBRARY]" if r.in_library else ""
    oa = " [OA]" if r.is_open_access else ""
    lines = [f"**{r.title}**{lib}{oa}"]
    lines.append(f"  {authors} ({r.year or '?'})")
    if r.venue:
        lines.append(f"  {r.venue}")
    lines.append(f"  Citations: {r.citation_count or 0} | ID: {r.id}")
    if r.tldr:
        lines.append(f"  TLDR: {r.tldr}")
    return "\n".join(lines)


def _format_paper(p: Paper) -> str:
    """Format a Paper for display."""
    authors = ", ".join(a.name for a in p.authors[:3])
    if len(p.authors) > 3:
        authors += " et al."
    lines = [f"**{p.title}**"]
    lines.append(f"  {authors} ({p.year or '?'})")
    if p.venue:
        lines.append(f"  Venue: {p.venue}")
    lines.append(f"  ID: {p.id}")
    lines.append(f"  Status: {p.status} | Pillar: {p.pillar or 'unassigned'} | Relevance: {p.relevance or '-'}/5")
    if p.tags:
        lines.append(f"  Tags: {', '.join(p.tags)}")
    if p.chapter:
        lines.append(f"  Chapter: {p.chapter}")
    if p.tldr:
        lines.append(f"  TLDR: {p.tldr}")
    if p.doi:
        lines.append(f"  DOI: {p.doi}")
    if p.pdf_url:
        lines.append(f"  PDF: {p.pdf_url}")
    if p.pdf_local_path:
        lines.append(f"  Local PDF: {p.pdf_local_path}")
    if p.methodology:
        lines.append(f"  Methodology: {p.methodology}")
    if p.limitations:
        lines.append(f"  Limitations: {p.limitations}")
    if p.math_framework:
        lines.append(f"  Math Framework: {p.math_framework}")
    if p.convergence_bounds:
        lines.append(f"  Convergence: {p.convergence_bounds}")
    if p.notes:
        lines.append(f"  Notes: {p.notes[:200]}{'...' if len(p.notes or '') > 200 else ''}")
    return "\n".join(lines)


# ── Discovery Tools ──────────────────────────────────────────────────


@mcp.tool()
async def search_papers(
    query: str,
    limit: int = 10,
    year_range: Optional[str] = None,
    fields_of_study: Optional[str] = None,
) -> str:
    """Search Semantic Scholar for academic papers.

    Args:
        query: Natural language search (e.g. 'transformer attention mechanism survey')
        limit: Max results (1-100, default 10)
        year_range: Filter by year range (e.g. '2018-2024', '2020-', '-2015')
        fields_of_study: Comma-separated fields (e.g. 'Mathematics,Computer Science')
    """
    lib_ids = await db.get_library_ids()
    fos = [f.strip() for f in fields_of_study.split(",")] if fields_of_study else None

    results = await s2.search_papers(
        query=query, limit=limit, year_range=year_range,
        fields_of_study=fos, library_ids=lib_ids,
    )
    await db.log_search(query, "semantic_scholar", len(results))

    if not results:
        return "No papers found for that query."

    formatted = [_format_result(r) for r in results]
    return f"Found {len(results)} papers:\n\n" + "\n\n---\n\n".join(formatted)


@mcp.tool()
async def get_citations(paper_id: str, limit: int = 20) -> str:
    """Get papers that cite a given paper (who cited this?).

    Args:
        paper_id: Semantic Scholar paper ID
        limit: Max results (default 20)
    """
    lib_ids = await db.get_library_ids()
    results = await s2.get_citations(paper_id, limit=limit, library_ids=lib_ids)

    if not results:
        return "No citations found."

    formatted = [_format_result(r) for r in results]
    return f"Found {len(results)} citing papers:\n\n" + "\n\n---\n\n".join(formatted)


@mcp.tool()
async def get_references(paper_id: str, limit: int = 20) -> str:
    """Get papers referenced by a given paper (what did this paper cite?).

    Args:
        paper_id: Semantic Scholar paper ID
        limit: Max results (default 20)
    """
    lib_ids = await db.get_library_ids()
    results = await s2.get_references(paper_id, limit=limit, library_ids=lib_ids)

    if not results:
        return "No references found."

    formatted = [_format_result(r) for r in results]
    return f"Found {len(results)} referenced papers:\n\n" + "\n\n---\n\n".join(formatted)


@mcp.tool()
async def find_related(paper_id: str, limit: int = 10) -> str:
    """Get AI-recommended papers similar to a given paper (Semantic Scholar recommendations).

    Args:
        paper_id: Semantic Scholar paper ID
        limit: Max results (default 10)
    """
    lib_ids = await db.get_library_ids()
    results = await s2.find_related(paper_id, limit=limit, library_ids=lib_ids)

    if not results:
        return "No recommendations found."

    formatted = [_format_result(r) for r in results]
    return f"Found {len(results)} related papers:\n\n" + "\n\n---\n\n".join(formatted)


@mcp.tool()
async def seed_library(author_name: str, limit: int = 20) -> str:
    """Find papers by a specific author and preview them (does NOT auto-add to library).

    Args:
        author_name: Author name (e.g. 'Yann LeCun', 'Yoshua Bengio')
        limit: Max papers to return (default 20)
    """
    lib_ids = await db.get_library_ids()
    results = await s2.search_by_author(author_name, limit=limit, library_ids=lib_ids)

    if not results:
        return f"No papers found for author '{author_name}'."

    formatted = [_format_result(r) for r in results]
    return (
        f"Found {len(results)} papers by {author_name}.\n"
        "Use add_paper(paper_id) to add specific ones to your library.\n\n"
        + "\n\n---\n\n".join(formatted)
    )


# ── Library Management Tools ─────────────────────────────────────────


@mcp.tool()
async def add_paper(paper_id: str) -> str:
    """Add a paper to the library by fetching its full metadata from Semantic Scholar.

    Args:
        paper_id: Semantic Scholar paper ID, or DOI: prefix, or ARXIV: prefix
                  Examples: '649def34f8be52c8b66281af98ae884c09aef38b'
                            'DOI:10.1145/3292500.3330925'
                            'ARXIV:1706.03762'
    """
    existing = await db.get_paper(paper_id)
    if existing:
        return f"Paper already in library: {existing.title}"

    try:
        data = await s2.get_paper_details(paper_id)
    except Exception as e:
        return f"Error fetching paper: {e}"

    fields = s2.parse_paper_to_library(data)
    paper = Paper(**fields)
    paper.bibtex = paper_to_bibtex(paper)

    await db.insert_paper(paper)
    return f"Added to library: {paper.title} ({paper.year})\nID: {paper.id}"


@mcp.tool()
async def remove_paper(paper_id: str) -> str:
    """Remove a paper from the library.

    Args:
        paper_id: The paper's Semantic Scholar ID
    """
    removed = await db.delete_paper(paper_id)
    return "Paper removed." if removed else "Paper not found in library."


@mcp.tool()
async def list_library(
    status: Optional[str] = None,
    pillar: Optional[str] = None,
    tag: Optional[str] = None,
    chapter: Optional[str] = None,
    sort_by: str = "added_at",
    limit: int = 50,
) -> str:
    """List papers in your library with optional filters.

    Args:
        status: Filter by reading status (unread, skimmed, read, deep_read)
        pillar: Filter by research pillar (pure_math, computational, financial)
        tag: Filter by tag
        chapter: Filter by section/chapter name
        sort_by: Sort field (added_at, year, citation_count, relevance, title)
        limit: Max results (default 50)
    """
    papers = await db.list_papers(
        status=status, pillar=pillar, tag=tag, chapter=chapter,
        sort_by=sort_by, limit=limit,
    )

    if not papers:
        return "No papers found matching those filters."

    formatted = [_format_paper(p) for p in papers]
    return f"Library ({len(papers)} papers):\n\n" + "\n\n---\n\n".join(formatted)


@mcp.tool()
async def get_paper_details(paper_id: str) -> str:
    """Get full details for a paper in your library.

    Args:
        paper_id: The paper's Semantic Scholar ID
    """
    paper = await db.get_paper(paper_id)
    if not paper:
        return "Paper not found in library. Use add_paper() first."

    result = _format_paper(paper)
    if paper.abstract:
        result += f"\n\n**Abstract:**\n{paper.abstract}"
    return result


@mcp.tool()
async def tag_paper(paper_id: str, tags: str) -> str:
    """Add tags to a paper. New tags are appended to existing ones.

    Args:
        paper_id: The paper's Semantic Scholar ID
        tags: Comma-separated tags (e.g. 'deep-learning,convergence,key-paper')
    """
    paper = await db.get_paper(paper_id)
    if not paper:
        return "Paper not found in library."

    new_tags = [t.strip() for t in tags.split(",") if t.strip()]
    merged = list(set(paper.tags + new_tags))
    await db.update_paper(paper_id, tags=merged)
    return f"Tags updated: {', '.join(merged)}"


@mcp.tool()
async def set_pillar(paper_id: str, pillar: str) -> str:
    """Assign a paper to a research pillar.

    Args:
        paper_id: The paper's Semantic Scholar ID
        pillar: One of: pure_math, computational, financial
    """
    try:
        p = Pillar(pillar)
    except ValueError:
        return f"Invalid pillar. Choose from: {', '.join(p.value for p in Pillar)}"

    ok = await db.update_paper(paper_id, pillar=p)
    return f"Pillar set to '{pillar}'." if ok else "Paper not found."


@mcp.tool()
async def set_status(paper_id: str, status: str) -> str:
    """Update reading status for a paper.

    Args:
        paper_id: The paper's Semantic Scholar ID
        status: One of: unread, skimmed, read, deep_read
    """
    try:
        s = ReadingStatus(status)
    except ValueError:
        return f"Invalid status. Choose from: {', '.join(s.value for s in ReadingStatus)}"

    ok = await db.update_paper(paper_id, status=s)
    return f"Status set to '{status}'." if ok else "Paper not found."


@mcp.tool()
async def rate_paper(paper_id: str, relevance: int) -> str:
    """Rate a paper's relevance to your research (1-5).

    Args:
        paper_id: The paper's Semantic Scholar ID
        relevance: Rating from 1 (tangential) to 5 (essential)
    """
    if relevance < 1 or relevance > 5:
        return "Rating must be 1-5."
    ok = await db.update_paper(paper_id, relevance=relevance)
    return f"Relevance set to {relevance}/5." if ok else "Paper not found."


@mcp.tool()
async def assign_chapter(paper_id: str, chapter: str) -> str:
    """Assign a paper to a section or chapter.

    Args:
        paper_id: The paper's Semantic Scholar ID
        chapter: Section name (e.g. 'introduction', 'background', 'methodology',
                 'results', 'conclusion') — any string is valid
    """
    ok = await db.update_paper(paper_id, chapter=chapter)
    return f"Assigned to chapter '{chapter}'." if ok else "Paper not found."


@mcp.tool()
async def annotate(paper_id: str, notes: str, append: bool = True) -> str:
    """Add or replace notes on a paper.

    Args:
        paper_id: The paper's Semantic Scholar ID
        notes: Your notes/annotations
        append: If True, append to existing notes. If False, replace them.
    """
    paper = await db.get_paper(paper_id)
    if not paper:
        return "Paper not found in library."

    if append and paper.notes:
        combined = paper.notes + "\n\n---\n\n" + notes
    else:
        combined = notes

    await db.update_paper(paper_id, notes=combined)
    return "Notes updated."


@mcp.tool()
async def set_extraction(
    paper_id: str,
    methodology: Optional[str] = None,
    limitations: Optional[str] = None,
    math_framework: Optional[str] = None,
    convergence_bounds: Optional[str] = None,
) -> str:
    """Set structured extraction fields for a paper.

    These are the 'Elicit-style' columns that make papers comparable at a glance.

    Args:
        paper_id: The paper's Semantic Scholar ID
        methodology: e.g. 'Deep Galerkin Method with ReLU networks'
        limitations: e.g. 'Unstable above 50 dimensions, no theoretical guarantees'
        math_framework: e.g. 'Viscosity solutions of HJB equations'
        convergence_bounds: e.g. 'O(N^{-1/2}) in L2 norm under Lipschitz assumption'
    """
    fields = {}
    if methodology is not None:
        fields["methodology"] = methodology
    if limitations is not None:
        fields["limitations"] = limitations
    if math_framework is not None:
        fields["math_framework"] = math_framework
    if convergence_bounds is not None:
        fields["convergence_bounds"] = convergence_bounds

    if not fields:
        return "No fields provided."

    ok = await db.update_paper(paper_id, **fields)
    return f"Extraction fields updated: {', '.join(fields.keys())}" if ok else "Paper not found."


# ── Analysis Tools ───────────────────────────────────────────────────


@mcp.tool()
async def compare_papers(paper_ids: str) -> str:
    """Compare multiple papers side by side on structured extraction fields.

    Args:
        paper_ids: Comma-separated Semantic Scholar paper IDs
    """
    ids = [pid.strip() for pid in paper_ids.split(",")]
    papers = []
    for pid in ids:
        p = await db.get_paper(pid)
        if p:
            papers.append(p)

    if not papers:
        return "No papers found."

    lines = []
    for p in papers:
        lines.append(f"### {p.title} ({p.year})")
        lines.append(f"- Pillar: {p.pillar or 'unassigned'}")
        lines.append(f"- Methodology: {p.methodology or 'not extracted'}")
        lines.append(f"- Math Framework: {p.math_framework or 'not extracted'}")
        lines.append(f"- Convergence: {p.convergence_bounds or 'not extracted'}")
        lines.append(f"- Limitations: {p.limitations or 'not extracted'}")
        lines.append(f"- Citations: {p.citation_count or 0}")
        lines.append("")

    return "\n".join(lines)


@mcp.tool()
async def find_bridges() -> str:
    """Find papers that cite across research pillars (cross-pillar bridge papers).

    Bridge papers are the connective tissue between fields — they often
    represent the most interesting and novel contributions.
    """
    bridges = await db.find_bridges()

    if not bridges:
        return (
            "No cross-pillar bridges found yet. "
            "This requires papers with assigned pillars and citation data. "
            "Try: 1) Assign pillars to papers, 2) Use get_citations/get_references to populate links."
        )

    lines = ["Cross-pillar bridge papers:"]
    for b in bridges:
        lines.append(f"- **{b['title']}** (pillar: {b['p1_pillar']}) cites into {b['p2_pillar']}")

    return "\n".join(lines)


@mcp.tool()
async def library_stats() -> str:
    """Get summary statistics for your paper library."""
    stats = await db.library_stats()

    lines = [f"**Library: {stats['total']} papers**"]

    lines.append("\nBy reading status:")
    for status, count in stats["by_status"].items():
        lines.append(f"  {status}: {count}")

    lines.append("\nBy research pillar:")
    for pillar, count in stats["by_pillar"].items():
        lines.append(f"  {pillar}: {count}")

    if stats["by_chapter"]:
        lines.append("\nBy chapter:")
        for chapter, count in stats["by_chapter"].items():
            lines.append(f"  {chapter}: {count}")

    return "\n".join(lines)


@mcp.tool()
async def search_library_local(query: str) -> str:
    """Search your local library by title, abstract, notes, or author name.

    Unlike search_papers (which queries Semantic Scholar), this only searches
    papers already in your library.

    Args:
        query: Search text
    """
    papers = await db.search_library(query)
    if not papers:
        return "No papers in your library match that query."

    formatted = [_format_paper(p) for p in papers]
    return f"Found {len(papers)} matching papers:\n\n" + "\n\n---\n\n".join(formatted)


# ── Export / Import Tools ────────────────────────────────────────────


@mcp.tool()
async def export_bibtex(
    paper_ids: Optional[str] = None,
    output_path: Optional[str] = None,
) -> str:
    """Export papers as BibTeX. If no IDs given, exports the entire library.

    Args:
        paper_ids: Comma-separated paper IDs (optional — exports all if omitted)
        output_path: Output file path (default: references.bib in current directory)
    """
    if paper_ids:
        ids = [pid.strip() for pid in paper_ids.split(",")]
        papers = []
        for pid in ids:
            p = await db.get_paper(pid)
            if p:
                papers.append(p)
    else:
        papers = await db.list_papers(limit=500)

    if not papers:
        return "No papers to export."

    out = Path(output_path) if output_path else EXPORT_DIR / "references.bib"
    out.parent.mkdir(parents=True, exist_ok=True)
    path = _export_bib(papers, out)
    return f"Exported {len(papers)} papers to {path}"


@mcp.tool()
async def import_from_bibtex(bib_path: str) -> str:
    """Import papers from a BibTeX file. Looks up each entry on Semantic Scholar
    by title to enrich with full metadata (citation count, abstract, TLDR, etc.).

    Args:
        bib_path: Absolute path to the .bib file to import
    """
    path = Path(bib_path)
    if not path.exists():
        return f"File not found: {path}\nTip: use an absolute path, e.g. C:/Users/you/refs.bib"

    entries = parse_bibtex_file(path)
    if not entries:
        return "No entries found in the BibTeX file."

    imported = []
    failed = []

    for i, entry in enumerate(entries):
        title = entry.get("title", "")
        if not title:
            failed.append(entry.get("cite_key", "unknown"))
            continue

        # Delay between papers to avoid rate limiting (free tier: 1 RPS)
        if i > 0:
            await asyncio.sleep(3)

        try:
            results = await s2.search_papers(title, limit=1)
            if results:
                data = await s2.get_paper_details(results[0].id)
                fields = s2.parse_paper_to_library(data)
                paper = Paper(**fields)
                paper.bibtex = paper_to_bibtex(paper)
                await db.insert_paper(paper)
                imported.append(f"{paper.title} ({paper.year})")
            else:
                # Not found on S2 — add from BibTeX metadata alone
                authors = bibtex_authors_to_list(entry.get("author", ""))
                paper = Paper(
                    id=f"bib_{entry['cite_key']}",
                    title=title,
                    authors=authors,
                    year=int(entry["year"]) if "year" in entry else None,
                    venue=entry.get("journal"),
                    doi=entry.get("doi"),
                )
                await db.insert_paper(paper)
                imported.append(f"{title} (BibTeX only — not found on Semantic Scholar)")
        except Exception as e:
            failed.append(f"{title}: {e}")

    result = f"Imported {len(imported)} papers:\n"
    result += "\n".join(f"  - {t}" for t in imported)
    if failed:
        result += f"\n\nFailed ({len(failed)}):\n"
        result += "\n".join(f"  - {f}" for f in failed)
    return result


@mcp.tool()
async def get_papers_by_chapter(chapter: str) -> str:
    """Get all papers assigned to a specific section or chapter.

    Args:
        chapter: Section name (e.g. 'introduction', 'background', 'methodology')
    """
    papers = await db.list_papers(chapter=chapter, sort_by="relevance")
    if not papers:
        return f"No papers assigned to chapter '{chapter}'."

    formatted = [_format_paper(p) for p in papers]
    return f"Chapter '{chapter}' ({len(papers)} papers):\n\n" + "\n\n---\n\n".join(formatted)


@mcp.tool()
async def get_papers_by_pillar(pillar: str) -> str:
    """Get all papers in a research pillar.

    Args:
        pillar: One of: pure_math, computational, financial
    """
    papers = await db.list_papers(pillar=pillar, sort_by="relevance")
    if not papers:
        return f"No papers in pillar '{pillar}'."

    formatted = [_format_paper(p) for p in papers]
    return f"Pillar '{pillar}' ({len(papers)} papers):\n\n" + "\n\n---\n\n".join(formatted)


# ═══════════════════════════════════════════════════════════════════════════════
# PHASE A — Screening, Bulk Extraction, Citation Network, Gap Analysis
# ═══════════════════════════════════════════════════════════════════════════════


@mcp.tool()
async def screen_papers(
    paper_ids: Optional[str] = None,
    status_filter: Optional[str] = None,
    include_criteria: str = "",
    exclude_criteria: str = "",
) -> str:
    """Format papers for systematic PRISMA-style abstract screening.

    Returns each paper's title + abstract in a structured format for you to
    review and classify as include / exclude / maybe. After screening:
    - Call tag_paper(id, 'screened-in') or tag_paper(id, 'screened-out')
    - Call set_status(id, 'skimmed') for papers you've screened

    Args:
        paper_ids: Comma-separated IDs to screen (default: all unread papers)
        status_filter: Only screen papers with this status (e.g. 'unread')
        include_criteria: What a paper must have to be included
        exclude_criteria: What disqualifies a paper
    """
    if paper_ids:
        ids = [pid.strip() for pid in paper_ids.split(",")]
        papers = [p for pid in ids if (p := await db.get_paper(pid))]
    else:
        papers = await db.list_papers(
            status=status_filter or "unread", sort_by="citation_count", limit=100
        )

    if not papers:
        return "No papers found to screen."

    lines = [
        f"SCREENING TASK — {len(papers)} paper{'s' if len(papers) != 1 else ''}",
        "",
    ]
    if include_criteria:
        lines.append(f"✅ INCLUDE if: {include_criteria}")
    if exclude_criteria:
        lines.append(f"❌ EXCLUDE if: {exclude_criteria}")
    if include_criteria or exclude_criteria:
        lines.append("")

    lines.append("For each paper below, decide: INCLUDE / EXCLUDE / MAYBE (with brief reason)")
    lines.append("Then call tag_paper(id, 'screened-in') or tag_paper(id, 'screened-out')")
    lines.append("─" * 60)

    for i, p in enumerate(papers, 1):
        authors = ", ".join(a.name for a in p.authors[:3])
        if len(p.authors) > 3:
            authors += " et al."
        lines.append(f"\n[{i}] ID: {p.id}")
        lines.append(f"Title: {p.title}")
        lines.append(f"Authors: {authors} ({p.year or '?'})")
        if p.venue:
            lines.append(f"Venue: {p.venue}")
        lines.append(f"Citations: {p.citation_count or 0}")
        if p.abstract:
            lines.append(f"Abstract: {p.abstract[:400]}{'...' if len(p.abstract) > 400 else ''}")
        elif p.tldr:
            lines.append(f"TLDR: {p.tldr}")
        else:
            lines.append("Abstract: [not available]")
        lines.append("Decision: ?")

    return "\n".join(lines)


@mcp.tool()
async def bulk_extract(
    paper_ids: Optional[str] = None,
    pillar: Optional[str] = None,
    chapter: Optional[str] = None,
    fields: str = "methodology,limitations,math_framework,convergence_bounds",
) -> str:
    """Format multiple papers for bulk structured extraction.

    Returns abstracts + existing extraction data for all specified papers,
    ready for you to fill in the missing fields. After reviewing each paper,
    call set_extraction() to populate the fields.

    Args:
        paper_ids: Comma-separated IDs (optional — use pillar/chapter to select a group)
        pillar: Extract all papers in this pillar (e.g. 'computational')
        chapter: Extract all papers in this chapter
        fields: Comma-separated fields to extract (default: all four extraction fields)
    """
    if paper_ids:
        ids = [pid.strip() for pid in paper_ids.split(",")]
        papers = [p for pid in ids if (p := await db.get_paper(pid))]
    elif pillar or chapter:
        papers = await db.list_papers(pillar=pillar, chapter=chapter, limit=100)
    else:
        papers = await db.list_papers(limit=100)

    if not papers:
        return "No papers found."

    requested_fields = [f.strip() for f in fields.split(",")]
    field_names = {
        "methodology": "Methodology",
        "limitations": "Limitations",
        "math_framework": "Math Framework",
        "convergence_bounds": "Convergence Bounds",
    }

    lines = [
        f"BULK EXTRACTION TASK — {len(papers)} papers",
        f"Fields to extract: {', '.join(requested_fields)}",
        "",
        "For each paper, fill in the missing fields, then call:",
        "  set_extraction(paper_id, methodology=..., limitations=..., ...)",
        "─" * 60,
    ]

    for i, p in enumerate(papers, 1):
        authors = ", ".join(a.name for a in p.authors[:2])
        lines.append(f"\n[{i}] {p.title} ({p.year or '?'})")
        lines.append(f"     ID: {p.id}")
        lines.append(f"     Authors: {authors}")
        if p.abstract:
            lines.append(f"     Abstract: {p.abstract[:350]}{'...' if len(p.abstract) > 350 else ''}")
        elif p.tldr:
            lines.append(f"     TLDR: {p.tldr}")

        for field in requested_fields:
            current = getattr(p, field, None) if hasattr(p, field) else None
            status = f"✓ {current}" if current else "✗ MISSING"
            display = field_names.get(field, field)
            lines.append(f"     {display}: {status}")

    filled = sum(
        1 for p in papers
        if all(getattr(p, f, None) for f in requested_fields if hasattr(p, f))
    )
    lines.append(f"\n{'─'*60}")
    lines.append(f"Coverage: {filled}/{len(papers)} papers fully extracted")

    return "\n".join(lines)


@mcp.tool()
async def build_citation_network(
    paper_id: str,
    depth: int = 1,
    direction: str = "both",
    limit_per_level: int = 30,
    add_to_library: bool = False,
) -> str:
    """Recursively fetch and store citation relationships for a paper.

    Crawls citations and/or references to the given depth, storing edges in
    the citations table. This makes find_bridges() and the Citation Graph
    work with real data. Use depth=1 for quick mapping, depth=2 for thorough
    (will be slower — makes many API calls).

    Args:
        paper_id: Seed paper's Semantic Scholar ID
        depth: How many hops to traverse (1 or 2, default 1)
        direction: 'citations' (who cites this), 'references' (what it cites), or 'both'
        limit_per_level: Max papers to fetch per node (default 30)
        add_to_library: If True, add all discovered papers to library too (slower)
    """
    seed = await db.get_paper(paper_id)
    seed_title = seed.title if seed else paper_id

    lib_ids = await db.get_library_ids()
    new_edges = 0
    new_papers = 0
    visited: set[str] = {paper_id}
    queue = [(paper_id, 0)]

    # Semaphore to limit concurrency and respect rate limits
    sem = asyncio.Semaphore(3)

    async def fetch_and_store(pid: str, current_depth: int):
        nonlocal new_edges, new_papers
        async with sem:
            results_cite, results_ref = [], []

            if direction in ("citations", "both"):
                try:
                    results_cite = await s2.get_citations(pid, limit=limit_per_level)
                    await asyncio.sleep(1.2)
                except Exception:
                    pass

            if direction in ("references", "both"):
                try:
                    results_ref = await s2.get_references(pid, limit=limit_per_level)
                    await asyncio.sleep(1.2)
                except Exception:
                    pass

        # Store edges: pid → cited (reference), cited → pid (citation)
        edges_to_store = (
            [(pid, r.id) for r in results_ref] +   # pid cites r
            [(r.id, pid) for r in results_cite]     # r cites pid
        )
        for citing, cited in edges_to_store:
            try:
                await db.insert_citations([Citation(citing_id=citing, cited_id=cited)])
                new_edges += 1
            except Exception:
                pass

        all_found = results_cite + results_ref
        if add_to_library:
            for r in all_found:
                if r.id not in lib_ids:
                    try:
                        data = await s2.get_paper_details(r.id)
                        fields = s2.parse_paper_to_library(data)
                        paper = Paper(**fields)
                        paper.bibtex = paper_to_bibtex(paper)
                        await db.insert_paper(paper)
                        lib_ids.add(r.id)
                        new_papers += 1
                        await asyncio.sleep(1.5)
                    except Exception:
                        pass

        if current_depth < depth:
            for r in all_found:
                if r.id not in visited:
                    visited.add(r.id)
                    queue.append((r.id, current_depth + 1))

    while queue:
        batch = []
        while queue and len(batch) < 5:
            batch.append(queue.pop(0))
        await asyncio.gather(*[fetch_and_store(pid, d) for pid, d in batch])

    result = (
        f"Citation network built for: {seed_title}\n"
        f"Depth: {depth} | Direction: {direction}\n"
        f"Edges stored: {new_edges}\n"
        f"Papers visited: {len(visited)}\n"
    )
    if add_to_library:
        result += f"New papers added to library: {new_papers}\n"
    result += "\nRun find_bridges() to identify cross-pillar connections."
    return result


@mcp.tool()
async def identify_gaps(
    research_question: Optional[str] = None,
    pillar: Optional[str] = None,
    chapter: Optional[str] = None,
) -> str:
    """Format your library for research gap identification.

    Returns a structured summary of all extraction fields, methodologies, and
    coverage across your papers — ready for you to identify:
    - Methods applied in one domain but not another
    - Understudied settings or populations
    - Contradictions between papers
    - Missing cross-pillar connections

    Args:
        research_question: Focusing question for the gap analysis (optional)
        pillar: Limit to papers in this pillar
        chapter: Limit to papers in this chapter
    """
    papers = await db.list_papers(pillar=pillar, chapter=chapter, sort_by="year", limit=200)

    if not papers:
        return "No papers in library. Add papers first."

    lines = ["RESEARCH GAP ANALYSIS", ""]
    if research_question:
        lines += [f"Research Question: {research_question}", ""]

    lines += [
        f"Library scope: {len(papers)} papers"
        + (f" | Pillar: {pillar}" if pillar else "")
        + (f" | Chapter: {chapter}" if chapter else ""),
        "",
    ]

    # Coverage summary
    by_pillar: dict[str, int] = {}
    by_year: dict[int, int] = {}
    methods: list[str] = []
    frameworks: list[str] = []
    missing_extraction = 0

    for p in papers:
        pl = p.pillar.value if p.pillar else "unassigned"
        by_pillar[pl] = by_pillar.get(pl, 0) + 1
        if p.year:
            by_year[p.year] = by_year.get(p.year, 0) + 1
        if p.methodology:
            methods.append(f"  [{p.authors[0].name.split()[-1] if p.authors else '?'} {p.year}] {p.methodology}")
        if p.math_framework:
            frameworks.append(f"  [{p.authors[0].name.split()[-1] if p.authors else '?'} {p.year}] {p.math_framework}")
        if not any([p.methodology, p.limitations, p.math_framework, p.convergence_bounds]):
            missing_extraction += 1

    lines.append("── COVERAGE SUMMARY ──")
    lines.append("By pillar: " + ", ".join(f"{k}={v}" for k, v in by_pillar.items()))
    if by_year:
        y_min, y_max = min(by_year), max(by_year)
        lines.append(f"Year range: {y_min}–{y_max}")
        # Sparse years
        all_years = set(range(y_min, y_max + 1))
        covered = set(by_year.keys())
        gaps = sorted(all_years - covered)
        if gaps:
            lines.append(f"Year gaps: {gaps}")
    lines.append(f"Extraction completeness: {len(papers) - missing_extraction}/{len(papers)} papers have structured data")
    if missing_extraction > 0:
        lines.append(f"  → Run bulk_extract() to fill in the {missing_extraction} missing papers")

    if methods:
        lines.append("\n── METHODS CATALOGUE ──")
        lines += methods

    if frameworks:
        lines.append("\n── MATHEMATICAL FRAMEWORKS ──")
        lines += frameworks

    lines.append("\n── FULL PAPER LIST (for gap analysis) ──")
    for p in papers:
        authors = ", ".join(a.name for a in p.authors[:2])
        lines.append(f"\n{p.title} ({p.year or '?'})")
        lines.append(f"  Authors: {authors}")
        lines.append(f"  Pillar: {p.pillar.value if p.pillar else 'unassigned'} | Citations: {p.citation_count or 0}")
        if p.tldr:
            lines.append(f"  TLDR: {p.tldr}")
        if p.methodology:
            lines.append(f"  Method: {p.methodology}")
        if p.limitations:
            lines.append(f"  Limitations: {p.limitations}")

    lines += [
        "",
        "─" * 60,
        "TASK: Based on the above, identify:",
        "1. Methods used in one pillar but not applied to others",
        "2. Temporal gaps — active periods followed by silence",
        "3. Contradictions between papers on the same question",
        "4. Settings/assumptions no paper has challenged",
        "5. Cross-pillar bridge opportunities",
    ]
    if research_question:
        lines.append(f"6. Specifically: what does the literature NOT yet answer about '{research_question}'?")

    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════════════
# PHASE B — Multi-source Search, Evidence Synthesis, Section Drafting
# ═══════════════════════════════════════════════════════════════════════════════


@mcp.tool()
async def search_openalex(
    query: str,
    limit: int = 10,
    year_range: Optional[str] = None,
) -> str:
    """Search OpenAlex for academic papers (250M+ papers, fully open, no key needed).

    Complements search_papers() (Semantic Scholar). Good for:
    - Papers with strong concept/field tagging
    - Open-access papers
    - Papers not yet indexed in Semantic Scholar

    Results include a DOI when available — use add_paper('DOI:10.xxx') to add.

    Args:
        query: Natural language search query
        limit: Max results (1-100, default 10)
        year_range: Filter by year (e.g. '2018-2024', '2020-')
    """
    lib_ids = await db.get_library_ids()
    try:
        results = await oa.search_papers(query=query, limit=limit, year_range=year_range, library_ids=lib_ids)
    except Exception as e:
        return f"OpenAlex search failed: {e}"

    await db.log_search(query, "openalex", len(results))

    if not results:
        return "No papers found on OpenAlex for that query."

    formatted = [_format_result(r) for r in results]
    return f"OpenAlex: {len(results)} papers\n\n" + "\n\n---\n\n".join(formatted)


@mcp.tool()
async def search_arxiv(
    query: str,
    categories: Optional[str] = None,
    max_results: int = 10,
) -> str:
    """Search arXiv for preprints (math, CS, quantitative finance, physics, etc.).

    Essential for cutting-edge research not yet peer-reviewed or indexed in S2.
    Results have ARXIV: IDs — use add_paper('ARXIV:2103.01234') to add.

    Common categories:
      cs.LG  — Machine Learning
      math.PR — Probability
      math.NA — Numerical Analysis
      q-fin.TR — Trading and Market Microstructure
      q-fin.MF — Mathematical Finance
      stat.ML — Statistics / Machine Learning

    Args:
        query: Search terms
        categories: Comma-separated arXiv category codes (e.g. 'cs.LG,math.PR')
        max_results: Max results (default 10)
    """
    lib_ids = await db.get_library_ids()
    cats = [c.strip() for c in categories.split(",")] if categories else None

    try:
        results = await arxiv.search_arxiv(query=query, categories=cats, max_results=max_results, library_ids=lib_ids)
    except Exception as e:
        return f"arXiv search failed: {e}"

    await db.log_search(query, "arxiv", len(results))

    if not results:
        return "No papers found on arXiv for that query."

    formatted = [_format_result(r) for r in results]
    return f"arXiv: {len(results)} preprints\n\n" + "\n\n---\n\n".join(formatted)


@mcp.tool()
async def multi_search(
    query: str,
    limit: int = 10,
    year_range: Optional[str] = None,
    sources: str = "semantic_scholar,openalex,arxiv",
) -> str:
    """Search across multiple academic databases simultaneously.

    Runs the same query on Semantic Scholar, OpenAlex, and/or arXiv in parallel
    and returns deduplicated, merged results.

    Args:
        query: Search query
        limit: Results per source (default 10)
        year_range: Year filter (e.g. '2018-2024')
        sources: Comma-separated sources to query (default: all three)
    """
    lib_ids = await db.get_library_ids()
    src_list = [s.strip() for s in sources.split(",")]

    tasks = {}
    if "semantic_scholar" in src_list:
        tasks["S2"] = s2.search_papers(query=query, limit=limit, year_range=year_range, library_ids=lib_ids)
    if "openalex" in src_list:
        tasks["OpenAlex"] = oa.search_papers(query=query, limit=limit, year_range=year_range, library_ids=lib_ids)
    if "arxiv" in src_list:
        tasks["arXiv"] = arxiv.search_arxiv(query=query, max_results=limit, library_ids=lib_ids)

    gathered = await asyncio.gather(*tasks.values(), return_exceptions=True)
    source_results = dict(zip(tasks.keys(), gathered))

    # Deduplicate by title similarity (simple: exact lowercase match)
    seen_titles: set[str] = set()
    all_results = []
    for source, results in source_results.items():
        if isinstance(results, Exception):
            continue
        for r in results:
            key = r.title.lower().strip()[:60]
            if key not in seen_titles:
                seen_titles.add(key)
                all_results.append((source, r))

    await db.log_search(query, "multi", len(all_results))

    if not all_results:
        return "No results found across any source."

    lines = [f"Multi-source search: {len(all_results)} unique papers\n"]
    for source, r in all_results:
        authors = ", ".join(a.name for a in r.authors[:3])
        if len(r.authors) > 3:
            authors += " et al."
        lib = " [IN LIBRARY]" if r.in_library else ""
        lines.append(f"[{source}] **{r.title}**{lib}")
        lines.append(f"  {authors} ({r.year or '?'}) | Citations: {r.citation_count or '–'} | ID: {r.id}")
        if r.tldr:
            lines.append(f"  TLDR: {r.tldr}")
        lines.append("")

    return "\n".join(lines)


@mcp.tool()
async def evidence_consensus(
    question: str,
    pillar: Optional[str] = None,
    tag: Optional[str] = None,
    limit: int = 50,
) -> str:
    """Format library papers for Consensus-style evidence synthesis.

    Returns abstracts formatted for you to classify each paper as:
    SUPPORTS / OPPOSES / MIXED / IRRELEVANT

    Then synthesise: "The balance of evidence [supports/opposes/is mixed on] the claim that..."

    Args:
        question: A focused yes/no or directional research question
                  e.g. 'Do deep learning BSDE solvers outperform classical methods in high dimensions?'
        pillar: Limit to a research pillar
        tag: Limit to papers with this tag
        limit: Max papers to include (default 50)
    """
    papers = await db.list_papers(pillar=pillar, tag=tag, sort_by="citation_count", limit=limit)

    if not papers:
        return "No papers in library to synthesise."

    lines = [
        "EVIDENCE SYNTHESIS TASK",
        f"Question: {question}",
        "",
        "For each paper, classify as one of:",
        "  SUPPORTS   — evidence suggests the answer is yes / the claim holds",
        "  OPPOSES    — evidence suggests no / the claim fails",
        "  MIXED      — evidence is conditional or contradictory",
        "  IRRELEVANT — paper does not address this question",
        "",
        "After classifying, synthesise:",
        '  "The balance of N papers [strongly supports / is mixed on / opposes] the claim..."',
        "─" * 60,
    ]

    for i, p in enumerate(papers, 1):
        authors = ", ".join(a.name for a in p.authors[:2])
        lines.append(f"\n[{i}] {p.title} ({p.year or '?'})")
        lines.append(f"     ID: {p.id} | Citations: {p.citation_count or 0}")
        lines.append(f"     Authors: {authors}")
        if p.abstract:
            lines.append(f"     Abstract: {p.abstract[:350]}{'...' if len(p.abstract) > 350 else ''}")
        elif p.tldr:
            lines.append(f"     TLDR: {p.tldr}")
        if p.methodology:
            lines.append(f"     Method: {p.methodology}")
        lines.append("     Classification: ?")

    return "\n".join(lines)


@mcp.tool()
async def draft_section(
    chapter: Optional[str] = None,
    pillar: Optional[str] = None,
    research_question: Optional[str] = None,
    word_target: int = 600,
    style: str = "critical",
) -> str:
    """Prepare structured context for drafting a literature review section.

    Returns all relevant papers with their full extraction data, structured
    for you to write a {word_target}-word critical literature review section
    with inline citations [AuthorYear].

    Args:
        chapter: Papers assigned to this chapter/section
        pillar: Papers in this research pillar
        research_question: The section's driving question (sharpens the output)
        word_target: Target word count (default 600)
        style: 'critical' (default) | 'descriptive' | 'thematic' | 'chronological'
    """
    papers = await db.list_papers(chapter=chapter, pillar=pillar, sort_by="year", limit=100)

    if not papers:
        return (
            f"No papers found"
            + (f" for chapter '{chapter}'" if chapter else "")
            + (f" in pillar '{pillar}'" if pillar else "")
            + ".\nUse assign_chapter() or set_pillar() to map papers to sections first."
        )

    lines = [
        f"DRAFT SECTION TASK",
        f"{'Chapter: ' + chapter if chapter else ''}{'Pillar: ' + pillar if pillar else ''}".strip(),
        f"Style: {style} | Target: ~{word_target} words",
        f"Papers: {len(papers)}",
        "",
    ]

    if research_question:
        lines += [f"Driving question: {research_question}", ""]

    # Style guidance
    style_guide = {
        "critical": (
            "Write critically: don't just describe what each paper does — compare, contrast, and critique. "
            "Highlight where papers agree, where they contradict, and where they fall short. "
            "End with a synthesis paragraph identifying what remains unresolved."
        ),
        "descriptive": (
            "Describe each major contribution clearly. Organise by sub-theme. "
            "Provide context for each approach and note its reception in the field (citation counts)."
        ),
        "thematic": (
            "Organise by theme/method rather than by paper. "
            "Group papers that use similar approaches or address similar sub-questions. "
            "Show how the field has fragmented into distinct methodological camps."
        ),
        "chronological": (
            "Trace the evolution of ideas over time. "
            "Show how early foundational work (lowest-year papers) was extended, challenged, or superseded. "
            "Make the narrative of scientific progress explicit."
        ),
    }
    lines += [f"Writing guidance: {style_guide.get(style, style_guide['critical'])}", ""]

    lines += [
        "Citation format: [AuthorYear] — e.g. [Han2018], [EWeinon2017], [Carmona2018]",
        "─" * 60,
        "=== PAPER LIBRARY FOR THIS SECTION ===",
        "",
    ]

    for p in papers:
        cite_key = (
            (p.authors[0].name.split()[-1] if p.authors else "Unknown")
            + str(p.year or "")
        )
        authors = ", ".join(a.name for a in p.authors[:3])
        if len(p.authors) > 3:
            authors += " et al."

        lines.append(f"[{cite_key}]  {p.title}")
        lines.append(f"  Authors: {authors} | Year: {p.year or '?'} | Citations: {p.citation_count or 0}")
        if p.pillar:
            lines.append(f"  Pillar: {p.pillar.value}")
        if p.venue:
            lines.append(f"  Venue: {p.venue}")
        if p.tldr:
            lines.append(f"  TLDR: {p.tldr}")
        if p.abstract:
            lines.append(f"  Abstract: {p.abstract[:300]}{'...' if len(p.abstract) > 300 else ''}")
        if p.methodology:
            lines.append(f"  Methodology: {p.methodology}")
        if p.math_framework:
            lines.append(f"  Math framework: {p.math_framework}")
        if p.convergence_bounds:
            lines.append(f"  Convergence: {p.convergence_bounds}")
        if p.limitations:
            lines.append(f"  Limitations: {p.limitations}")
        if p.notes:
            lines.append(f"  Your notes: {p.notes[:200]}{'...' if len(p.notes) > 200 else ''}")
        lines.append("")

    lines += [
        "─" * 60,
        f"Now write the ~{word_target}-word {style} literature review section.",
        "Use [AuthorYear] citations throughout. Do not pad — be precise and critical.",
    ]
    if research_question:
        lines.append(f"Ensure the section builds toward answering: {research_question}")

    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════════════
# PHASE C — PDF Download, Watch List, PRISMA Report, Deduplication
# ═══════════════════════════════════════════════════════════════════════════════


@mcp.tool()
async def download_pdf(paper_id: str) -> str:
    """Download a paper's open-access PDF and store it locally.

    Uses the pdf_url stored in the library. Only works for open-access papers.
    Optionally extracts full text if pdfplumber is installed.

    Args:
        paper_id: The paper's Semantic Scholar ID
    """
    paper = await db.get_paper(paper_id)
    if not paper:
        return "Paper not found in library."
    if not paper.pdf_url:
        return f"No PDF URL stored for '{paper.title}'. Check if it's open access."

    PAPERS_DIR.mkdir(parents=True, exist_ok=True)
    safe_name = "".join(c if c.isalnum() or c in "._-" else "_" for c in paper_id)
    pdf_path = PAPERS_DIR / f"{safe_name}.pdf"

    import httpx
    try:
        async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
            resp = await client.get(paper.pdf_url)
            resp.raise_for_status()
            pdf_path.write_bytes(resp.content)
    except Exception as e:
        return f"Download failed: {e}"

    await db.update_paper(paper_id, pdf_local_path=str(pdf_path))

    # Try full-text extraction if pdfplumber available
    text_result = ""
    try:
        import pdfplumber
        with pdfplumber.open(pdf_path) as pdf:
            text = "\n\n".join(
                page.extract_text() or "" for page in pdf.pages
            ).strip()
        if text:
            await db.store_fulltext(paper_id, text)
            text_result = f"\nFull text extracted: {len(text):,} characters stored."
    except ImportError:
        text_result = "\n(Install pdfplumber for automatic text extraction: pip install pdfplumber)"
    except Exception as e:
        text_result = f"\nText extraction failed: {e}"

    return (
        f"Downloaded: {paper.title}\n"
        f"Saved to: {pdf_path}\n"
        f"Size: {pdf_path.stat().st_size / 1024:.1f} KB"
        + text_result
    )


@mcp.tool()
async def watch_add(paper_ids: str) -> str:
    """Add papers to the watch list for continuous citation monitoring.

    Papers in the watch list are checked by watch_check() for new papers
    citing them — equivalent to LitMaps monitoring.

    Args:
        paper_ids: Comma-separated Semantic Scholar paper IDs
    """
    ids = [pid.strip() for pid in paper_ids.split(",")]
    added = await db.watch_add(ids)
    total = len(await db.watch_list())
    return f"Added {added} new seed(s) to watch list. Total seeds: {total}"


@mcp.tool()
async def watch_remove(paper_id: str) -> str:
    """Remove a paper from the watch list.

    Args:
        paper_id: Semantic Scholar paper ID to remove
    """
    removed = await db.watch_remove(paper_id)
    return "Removed from watch list." if removed else "Paper not in watch list."


@mcp.tool()
async def watch_check(limit_per_seed: int = 15) -> str:
    """Check the watch list for new papers citing your seed papers.

    Queries Semantic Scholar for recent papers citing each watched paper.
    Returns newly discovered papers not already in your library.

    Args:
        limit_per_seed: Max papers to check per seed (default 15)
    """
    seeds = await db.watch_list()
    if not seeds:
        return "Watch list is empty. Use watch_add(paper_ids) to add seed papers."

    lib_ids = await db.get_library_ids()
    new_found: list[tuple[str, object]] = []   # (seed_title, result)

    for seed_row in seeds:
        seed_id = seed_row["paper_id"]
        seed_paper = await db.get_paper(seed_id)
        seed_title = seed_paper.title if seed_paper else seed_id

        try:
            results = await s2.get_citations(seed_id, limit=limit_per_seed, library_ids=lib_ids)
            await asyncio.sleep(1.2)
        except Exception as e:
            new_found.append((seed_title, f"[error: {e}]"))
            continue

        for r in results:
            if not r.in_library:
                new_found.append((seed_title, r))

        await db.watch_mark_checked(seed_id)

    if not new_found:
        return (
            f"Watch check complete — {len(seeds)} seed(s) checked.\n"
            "No new papers found outside your library."
        )

    lines = [f"Watch check: {len(new_found)} new paper(s) found\n"]
    for seed_title, result in new_found:
        if isinstance(result, str):
            lines.append(f"[{seed_title}] {result}")
        else:
            r = result
            authors = ", ".join(a.name for a in r.authors[:2])
            lines.append(f"Cited by: {seed_title}")
            lines.append(f"  **{r.title}**")
            lines.append(f"  {authors} ({r.year or '?'}) | Citations: {r.citation_count or 0} | ID: {r.id}")
            if r.tldr:
                lines.append(f"  TLDR: {r.tldr}")
            lines.append("")

    lines.append("Use add_paper(id) to add any of these to your library.")
    return "\n".join(lines)


@mcp.tool()
async def generate_prisma_report() -> str:
    """Generate a PRISMA 2020-style flow report of your literature review process.

    Reads search history, paper counts, and screening tags to produce a
    structured audit trail showing: identified → screened → assessed → included.
    Required for systematic reviews; useful for transparency in any review.
    """
    stats = await db.library_stats()
    history = await db.get_search_history(limit=100)

    total_identified = sum(h.get("result_count", 0) or 0 for h in history)
    searches_by_source: dict[str, int] = {}
    for h in history:
        src = h.get("source") or "unknown"
        searches_by_source[src] = searches_by_source.get(src, 0) + 1

    total_in_library = stats["total"]
    by_status = stats["by_status"]

    # Screening counts from tags
    screened_out = 0
    screened_in = 0
    all_papers = await db.list_papers(limit=500)
    for p in all_papers:
        tags = p.tags or []
        if "screened-out" in tags:
            screened_out += 1
        if "screened-in" in tags:
            screened_in += 1

    included = by_status.get("read", 0) + by_status.get("deep_read", 0)
    excluded_fulltext = total_in_library - screened_out - included

    lines = [
        "# PRISMA 2020 Flow Diagram",
        "",
        "## Identification",
        f"  Records identified via database searches: {total_identified}",
        "  Sources searched:",
    ]
    for src, count in searches_by_source.items():
        lines.append(f"    - {src}: {count} searches")

    lines += [
        "",
        "## Screening",
        f"  Records added to library (after deduplication): {total_in_library}",
        f"  Records screened (abstract review): {total_in_library}",
        f"  Records excluded at screening: {screened_out}",
        f"    (tagged 'screened-out')",
        f"  Records assessed for eligibility: {total_in_library - screened_out}",
        "",
        "## Included",
        f"  Studies included in review: {included}",
        f"    - Read: {by_status.get('read', 0)}",
        f"    - Deep read: {by_status.get('deep_read', 0)}",
        "",
        "## Library snapshot",
        f"  Unread: {by_status.get('unread', 0)}",
        f"  Skimmed: {by_status.get('skimmed', 0)}",
        f"  Read: {by_status.get('read', 0)}",
        f"  Deep read: {by_status.get('deep_read', 0)}",
        "",
        "## By research pillar",
    ]
    for pillar, count in stats["by_pillar"].items():
        lines.append(f"  {pillar}: {count}")

    if stats["by_chapter"]:
        lines += ["", "## By chapter/section"]
        for chapter, count in stats["by_chapter"].items():
            lines.append(f"  {chapter}: {count}")

    lines += [
        "",
        "─" * 60,
        "Note: To improve PRISMA accuracy:",
        "  - Tag screened papers: tag_paper(id, 'screened-in') / tag_paper(id, 'screened-out')",
        "  - Update reading status: set_status(id, 'read') / set_status(id, 'deep_read')",
        "  - Run screen_papers() to do systematic abstract screening",
    ]

    return "\n".join(lines)


@mcp.tool()
async def deduplicate_library() -> str:
    """Find and report duplicate papers in the library (same DOI or very similar titles).

    Returns a list of suspected duplicates for you to review and remove with remove_paper().
    Does not auto-delete anything.
    """
    papers = await db.list_papers(limit=500)

    # Check by DOI
    doi_map: dict[str, list] = {}
    for p in papers:
        if p.doi:
            doi_map.setdefault(p.doi.lower(), []).append(p)

    # Check by title similarity (exact normalised title match)
    title_map: dict[str, list] = {}
    for p in papers:
        key = " ".join(p.title.lower().split())[:80]
        title_map.setdefault(key, []).append(p)

    duplicates = []
    for doi, group in doi_map.items():
        if len(group) > 1:
            duplicates.append(("DOI", doi, group))
    for title_key, group in title_map.items():
        if len(group) > 1:
            # Avoid double-reporting DOI dupes
            if not any(p.doi for p in group):
                duplicates.append(("Title", title_key[:60], group))

    if not duplicates:
        return f"No duplicates found in {len(papers)}-paper library. ✓"

    lines = [f"Found {len(duplicates)} duplicate group(s):\n"]
    for reason, key, group in duplicates:
        lines.append(f"[{reason} match: {key}]")
        for p in group:
            lines.append(f"  ID: {p.id} | {p.title[:70]} ({p.year})")
        lines.append("  → Keep one, remove others with remove_paper(id)")
        lines.append("")

    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════════════
# PIPELINE — Full Literature Review Workflow (Research Question → Final Review)
# ═══════════════════════════════════════════════════════════════════════════════


# ── Stage 1: Define ──────────────────────────────────────────────────


@mcp.tool()
async def generate_search_strategy(
    research_question: str,
    field: str = "general",
    num_themes: int = 3,
) -> str:
    """Generate a systematic search strategy from a research question.

    Returns a structured template with suggested search queries, databases,
    year ranges, and Boolean operators — the first step in a full literature
    review pipeline. Review the strategy, adjust as needed, then execute
    each query using multi_search().

    Args:
        research_question: The central research question driving the review
        field: Academic field (e.g. 'mathematics', 'computer_science', 'finance')
        num_themes: Number of thematic strands to search (default 3)
    """
    # Get library stats for context
    stats = await db.library_stats()

    arx_categories = {
        "mathematics": "math.PR, math.NA, math.AP, math.OC",
        "computer_science": "cs.LG, cs.AI, cs.NE, cs.CE",
        "finance": "q-fin.TR, q-fin.MF, q-fin.CP, q-fin.RM",
        "physics": "physics.comp-ph, cond-mat.stat-mech",
        "statistics": "stat.ML, stat.ME, stat.TH",
    }
    suggested_cats = arx_categories.get(field, "cs.LG, math.NA")

    lines = [
        "SEARCH STRATEGY GENERATOR",
        f"Research Question: {research_question}",
        f"Field: {field}",
        f"Current library: {stats['total']} papers",
        "",
        "─" * 60,
        "",
        f"TASK: Generate a {num_themes}-theme search strategy for this research question.",
        "",
        "For each theme, provide:",
        "  1. Theme name (e.g. 'Deep learning BSDE solvers')",
        "  2. Primary query for Semantic Scholar (natural language)",
        "  3. arXiv query with categories (suggested: " + suggested_cats + ")",
        "  4. OpenAlex query",
        "  5. Year range (e.g. '2015-' for recent, '2000-2024' for comprehensive)",
        "  6. Key authors to seed (use seed_library later)",
        "",
        "Also specify:",
        "  - Inclusion criteria (for screen_papers later)",
        "  - Exclusion criteria (for screen_papers later)",
        "  - Expected total papers after screening (~20-50 for a section, ~50-150 for a full review)",
        "",
        "After generating the strategy, execute it step by step:",
        "  1. Run multi_search() for each theme's queries",
        "  2. Run seed_library() for each key author",
        "  3. Add relevant papers with add_paper()",
        "  4. Build citation links with build_citation_network() on 3-4 seed papers",
        "  5. Deduplicate with deduplicate_library()",
        "  6. Screen with screen_papers(include_criteria, exclude_criteria)",
    ]

    return "\n".join(lines)


# ── Stage 2: Read & Analyse ─────────────────────────────────────────


@mcp.tool()
async def summarize_paper(paper_id: str) -> str:
    """Return a paper's full content for comprehensive summarisation.

    Returns the abstract, TLDR, full text (if downloaded), and existing notes
    formatted for you to write a thorough summary. After reviewing, call
    store_summary(paper_id, summary) to persist your summary.

    Args:
        paper_id: The paper's Semantic Scholar ID
    """
    paper = await db.get_paper(paper_id)
    if not paper:
        return "Paper not found in library."

    fulltext = await db.get_fulltext(paper_id)

    authors = ", ".join(a.name for a in paper.authors[:4])
    if len(paper.authors) > 4:
        authors += " et al."

    lines = [
        "SUMMARISATION TASK",
        f"Title: {paper.title}",
        f"Authors: {authors} ({paper.year or '?'})",
        f"Venue: {paper.venue or 'Unknown'}",
        f"Citations: {paper.citation_count or 0}",
        "",
    ]

    if paper.summary:
        lines += [f"[Existing summary]: {paper.summary}", ""]

    if paper.tldr:
        lines += [f"S2 TLDR: {paper.tldr}", ""]

    if paper.abstract:
        lines += ["ABSTRACT:", paper.abstract, ""]

    if fulltext:
        # Include first 3000 chars of full text for richer summaries
        lines += [
            "FULL TEXT (excerpt):",
            fulltext[:3000] + ("..." if len(fulltext) > 3000 else ""),
            "",
        ]

    if paper.notes:
        lines += [f"Your notes: {paper.notes[:500]}", ""]

    lines += [
        "─" * 60,
        "Write a comprehensive 150-300 word summary covering:",
        "  1. Research question / objective",
        "  2. Methodology and approach",
        "  3. Key results and contributions",
        "  4. Significance to the field",
        "",
        f"Then call: store_summary('{paper_id}', '<your summary>')",
    ]

    return "\n".join(lines)


@mcp.tool()
async def store_summary(paper_id: str, summary: str) -> str:
    """Store a Claude-generated comprehensive summary for a paper.

    Args:
        paper_id: The paper's Semantic Scholar ID
        summary: The comprehensive summary text
    """
    ok = await db.update_paper(paper_id, summary=summary)
    return "Summary stored." if ok else "Paper not found."


@mcp.tool()
async def extract_key_findings(paper_id: str) -> str:
    """Return a paper's content for key-findings extraction.

    Returns abstract + summary + extraction data formatted for you to
    identify the 3-7 most important findings. After extracting, call
    store_key_findings(paper_id, findings) to persist them.

    Args:
        paper_id: The paper's Semantic Scholar ID
    """
    paper = await db.get_paper(paper_id)
    if not paper:
        return "Paper not found in library."

    fulltext = await db.get_fulltext(paper_id)
    authors = ", ".join(a.name for a in paper.authors[:3])

    lines = [
        "KEY FINDINGS EXTRACTION",
        f"Title: {paper.title}",
        f"Authors: {authors} ({paper.year or '?'})",
        "",
    ]

    if paper.abstract:
        lines += ["Abstract:", paper.abstract, ""]
    if paper.summary:
        lines += ["Summary:", paper.summary, ""]
    if fulltext:
        lines += ["Full text (excerpt):", fulltext[:2000] + "...", ""]
    if paper.methodology:
        lines += [f"Methodology: {paper.methodology}"]
    if paper.convergence_bounds:
        lines += [f"Convergence bounds: {paper.convergence_bounds}"]

    if paper.key_findings:
        lines += ["", "Existing findings:", ""]
        for i, f in enumerate(paper.key_findings, 1):
            lines.append(f"  {i}. {f}")

    lines += [
        "",
        "─" * 60,
        "Extract 3-7 key findings as a comma-separated list of concise statements.",
        "Focus on: novel contributions, quantitative results, theoretical insights.",
        "",
        f"Then call: store_key_findings('{paper_id}', 'finding 1, finding 2, ...')",
    ]

    return "\n".join(lines)


@mcp.tool()
async def store_key_findings(paper_id: str, findings: str) -> str:
    """Store key findings for a paper.

    Args:
        paper_id: The paper's Semantic Scholar ID
        findings: Comma-separated key findings
    """
    parsed = [f.strip() for f in findings.split(",") if f.strip()]
    ok = await db.update_paper(paper_id, key_findings=parsed)
    return f"Stored {len(parsed)} key findings." if ok else "Paper not found."


@mcp.tool()
async def assess_quality(paper_id: str) -> str:
    """Return a paper's metadata for quality and rigor assessment.

    Returns bibliometric data + abstract for you to evaluate the paper's
    methodological rigor, reproducibility, and scholarly impact.
    After assessing, call store_quality(paper_id, score, notes).

    Args:
        paper_id: The paper's Semantic Scholar ID
    """
    paper = await db.get_paper(paper_id)
    if not paper:
        return "Paper not found in library."

    authors = ", ".join(a.name for a in paper.authors[:4])

    lines = [
        "QUALITY ASSESSMENT",
        f"Title: {paper.title}",
        f"Authors: {authors} ({paper.year or '?'})",
        f"Venue: {paper.venue or 'Unknown venue'}",
        f"Citation count: {paper.citation_count or 0}",
        f"Is open access: {'Yes' if paper.pdf_url else 'Unknown'}",
        "",
    ]

    if paper.abstract:
        lines += ["Abstract:", paper.abstract[:500], ""]
    if paper.methodology:
        lines += [f"Methodology: {paper.methodology}"]
    if paper.limitations:
        lines += [f"Known limitations: {paper.limitations}"]
    if paper.math_framework:
        lines += [f"Math framework: {paper.math_framework}"]

    if paper.quality_score:
        lines += [f"\n[Existing assessment]: {paper.quality_score}/5 — {paper.quality_notes}"]

    lines += [
        "",
        "─" * 60,
        "Rate this paper 1-5 on overall quality/rigor:",
        "  5 = Landmark paper, rigorous methodology, highly reproducible",
        "  4 = Strong contribution, sound methodology, minor gaps",
        "  3 = Solid work, standard methodology, some limitations",
        "  2 = Weak methodology or limited evidence, significant gaps",
        "  1 = Poor quality, unreliable, or methodologically flawed",
        "",
        "Consider: venue reputation, citation trajectory, methodological rigor,",
        "reproducibility, theoretical soundness, empirical validation.",
        "",
        f"Then call: store_quality('{paper_id}', <score>, '<brief justification>')",
    ]

    return "\n".join(lines)


@mcp.tool()
async def store_quality(paper_id: str, score: int, notes: str) -> str:
    """Store a quality assessment score and justification.

    Args:
        paper_id: The paper's Semantic Scholar ID
        score: Quality score 1-5
        notes: Brief justification for the score
    """
    if score < 1 or score > 5:
        return "Score must be 1-5."
    ok = await db.update_paper(paper_id, quality_score=score, quality_notes=notes)
    return f"Quality assessment stored: {score}/5." if ok else "Paper not found."


# ── Stage 3: Organise (Oxford Three-Move + Themes) ──────────────────


@mcp.tool()
async def classify_moves(
    pillar: Optional[str] = None,
    chapter: Optional[str] = None,
) -> str:
    """Format papers for Oxford three-move classification.

    Returns all papers in scope with their metadata, summaries, and citation
    counts, formatted for you to classify each as:

    - FOUNDATIONAL: Established work, uncontroversial, high citations, older
    - GAP: Identifies problems, questions current knowledge, highlights limitations
    - PARALLEL: Recent attempts to address gaps, newer methodologies, unverified conclusions

    After classifying, call set_move(paper_id, move) for each paper.

    Args:
        pillar: Limit to a research pillar
        chapter: Limit to a chapter/section
    """
    papers = await db.list_papers(pillar=pillar, chapter=chapter, sort_by="year", limit=200)

    if not papers:
        return "No papers found. Add papers first."

    lines = [
        "OXFORD THREE-MOVE CLASSIFICATION",
        "",
        "The Oxford literature review model organises papers into three moves:",
        "  1. FOUNDATIONAL — Established facts, frameworks, widely-cited older work",
        "  2. GAP — Papers questioning current knowledge, identifying problems/limitations",
        "  3. PARALLEL — Recent research attempting to fill gaps, newer methodologies",
        "",
        "This ordering creates a narrative: established knowledge → what's missing → what's new.",
        "─" * 60,
    ]

    for i, p in enumerate(papers, 1):
        authors = ", ".join(a.name for a in p.authors[:2])
        current_move = f" [currently: {p.move.value}]" if p.move else ""

        lines.append(f"\n[{i}] {p.title} ({p.year or '?'}){current_move}")
        lines.append(f"     Authors: {authors} | Citations: {p.citation_count or 0}")
        if p.summary:
            lines.append(f"     Summary: {p.summary[:200]}...")
        elif p.tldr:
            lines.append(f"     TLDR: {p.tldr}")
        if p.methodology:
            lines.append(f"     Method: {p.methodology}")
        lines.append(f"     Classification: ?")

    lines += [
        "",
        "─" * 60,
        "For each paper, assign: foundational | gap | parallel",
        "Then call set_move(paper_id, 'foundational') etc. for each.",
    ]

    return "\n".join(lines)


@mcp.tool()
async def set_move(paper_id: str, move: str) -> str:
    """Classify a paper into an Oxford three-move category.

    Args:
        paper_id: The paper's Semantic Scholar ID
        move: One of: foundational, gap, parallel
    """
    try:
        m = Move(move)
    except ValueError:
        return f"Invalid move. Choose from: {', '.join(m.value for m in Move)}"

    ok = await db.update_paper(paper_id, move=move)
    return f"Move set to '{move}'." if ok else "Paper not found."


@mcp.tool()
async def set_themes(paper_id: str, themes: str) -> str:
    """Assign thematic tags to a paper (separate from regular tags).

    Themes represent the conceptual strands running through your review,
    corresponding to the 'multiple research topics' in the Oxford model.

    Args:
        paper_id: The paper's Semantic Scholar ID
        themes: Comma-separated theme names (e.g. 'BSDE solvers,convergence theory,neural networks')
    """
    parsed = [t.strip() for t in themes.split(",") if t.strip()]
    ok = await db.update_paper(paper_id, themes=parsed)
    return f"Themes set: {', '.join(parsed)}" if ok else "Paper not found."


@mcp.tool()
async def generate_synthesis_matrix(
    paper_ids: Optional[str] = None,
    pillar: Optional[str] = None,
    chapter: Optional[str] = None,
    dimensions: str = "methodology,math_framework,limitations,convergence_bounds,key_findings",
) -> str:
    """Generate a structured synthesis matrix comparing papers across dimensions.

    Returns a formatted comparison table showing how each paper addresses
    each dimension. Essential for identifying patterns, contradictions,
    and gaps across the literature.

    Args:
        paper_ids: Comma-separated IDs (or use pillar/chapter to select a group)
        pillar: Select all papers in this pillar
        chapter: Select all papers in this chapter
        dimensions: Comma-separated fields to compare (default: all extraction fields + key_findings)
    """
    if paper_ids:
        ids = [pid.strip() for pid in paper_ids.split(",")]
        papers = [p for pid in ids if (p := await db.get_paper(pid))]
    else:
        papers = await db.list_papers(pillar=pillar, chapter=chapter, sort_by="year", limit=50)

    if not papers:
        return "No papers found."

    dims = [d.strip() for d in dimensions.split(",")]

    lines = [
        f"SYNTHESIS MATRIX — {len(papers)} papers × {len(dims)} dimensions",
        "─" * 60,
    ]

    for p in papers:
        cite = (p.authors[0].name.split()[-1] if p.authors else "?") + str(p.year or "")
        lines.append(f"\n[{cite}] {p.title}")
        for dim in dims:
            if dim == "key_findings":
                val = "; ".join(p.key_findings) if p.key_findings else "—"
            else:
                val = getattr(p, dim, None) or "—"
            lines.append(f"  {dim}: {val}")

    lines += [
        "",
        "─" * 60,
        "Use this matrix to identify:",
        "  - Common methodological approaches vs. outliers",
        "  - Contradictions between papers on the same question",
        "  - Dimensions where most cells are empty (under-explored areas)",
        "  - Patterns that suggest thematic groupings",
    ]

    return "\n".join(lines)


# ── Stage 4: Structure & Write ──────────────────────────────────────


@mcp.tool()
async def generate_review_outline(
    research_question: str,
    structure_style: str = "parallel",
    themes: Optional[str] = None,
) -> str:
    """Generate a literature review outline following the Oxford model.

    Returns your library statistics, move classifications, and theme
    distribution, then asks you to propose a structured outline.

    Three Oxford organisational styles:
    - BLOCK:    Topic A (found→gap→parallel), Topic B (found→gap→parallel), Conclude
    - PARALLEL: All foundational (A+B), All gaps (A+B), All parallel (A+B), Conclude
    - MIXED:    Topic A (found+gap), Topic B (found+gap), Parallel (A+B), Conclude

    After proposing the outline, use assign_chapter() to map papers to sections,
    then run assemble_review() to draft the complete review.

    Args:
        research_question: The central question driving the review
        structure_style: 'block', 'parallel', or 'mixed' (default: parallel)
        themes: Comma-separated theme names to structure around (auto-detected if omitted)
    """
    papers = await db.list_papers(sort_by="year", limit=200)
    stats = await db.library_stats()

    if not papers:
        return "Library is empty. Add papers first."

    # Count by move
    move_counts: dict[str, int] = {"foundational": 0, "gap": 0, "parallel": 0, "unclassified": 0}
    for p in papers:
        m = p.move.value if p.move else "unclassified"
        move_counts[m] = move_counts.get(m, 0) + 1

    # Discover themes
    all_themes: dict[str, int] = {}
    for p in papers:
        for t in (p.themes or []):
            all_themes[t] = all_themes.get(t, 0) + 1

    if themes:
        requested_themes = [t.strip() for t in themes.split(",")]
    else:
        requested_themes = sorted(all_themes.keys(), key=lambda t: -all_themes[t])[:5]

    lines = [
        "LITERATURE REVIEW OUTLINE GENERATOR",
        f"Research Question: {research_question}",
        f"Structure Style: {structure_style.upper()}",
        f"Library: {len(papers)} papers",
        "",
        "── MOVE DISTRIBUTION ──",
        f"  Foundational: {move_counts['foundational']}",
        f"  Gap:          {move_counts['gap']}",
        f"  Parallel:     {move_counts['parallel']}",
        f"  Unclassified: {move_counts['unclassified']}",
    ]

    if move_counts["unclassified"] > 0:
        lines.append(f"  → Run classify_moves() to classify the {move_counts['unclassified']} unclassified papers")

    lines += ["", "── THEMES ──"]
    if requested_themes:
        for t in requested_themes:
            lines.append(f"  {t}: {all_themes.get(t, 0)} papers")
    else:
        lines.append("  No themes assigned yet. Use set_themes() to assign thematic tags.")

    lines += ["", "── PILLAR DISTRIBUTION ──"]
    for pillar, count in stats["by_pillar"].items():
        lines.append(f"  {pillar}: {count}")

    # Style explanation
    style_desc = {
        "block": (
            "BLOCK STYLE: Complete each theme before moving to the next.\n"
            "  Section 1: Introduction (general foundations)\n"
            "  Section 2: Theme A — foundational → gap → parallel research\n"
            "  Section 3: Theme B — foundational → gap → parallel research\n"
            "  Section N: Conclusion — link knowns, summarise unknowns, justify your research"
        ),
        "parallel": (
            "PARALLEL STYLE: Group by move type across all themes.\n"
            "  Section 1: Introduction (general foundations)\n"
            "  Section 2: Foundational knowledge (Theme A + B + ...)\n"
            "  Section 3: Establishing gaps (Theme A + B + ...)\n"
            "  Section 4: Parallel research (Theme A + B + ...)\n"
            "  Section 5: Conclusion — link knowns, summarise unknowns, justify your research"
        ),
        "mixed": (
            "MIXED STYLE: Foundational + gap per theme, then parallel across all.\n"
            "  Section 1: Introduction (general foundations)\n"
            "  Section 2: Theme A — foundational + gap identification\n"
            "  Section 3: Theme B — foundational + gap identification\n"
            "  Section 4: Parallel research across all themes\n"
            "  Section 5: Conclusion — link knowns, summarise unknowns, justify your research"
        ),
    }
    lines += [
        "",
        "── RECOMMENDED STRUCTURE ──",
        style_desc.get(structure_style, style_desc["parallel"]),
    ]

    lines += [
        "",
        "─" * 60,
        "TASK: Propose a detailed outline with ~4-7 sections.",
        "For each section, specify:",
        "  - Section title",
        "  - Driving question",
        "  - Which papers belong (by ID or theme/move/pillar)",
        "  - Approximate word target",
        "",
        "After the outline is approved, run assign_chapter() for each paper,",
        "then run assemble_review() to draft the complete review.",
    ]

    return "\n".join(lines)


@mcp.tool()
async def assemble_review(
    sections_json: str,
    word_target: int = 3000,
    research_question: Optional[str] = None,
) -> str:
    """Assemble a complete literature review from a structured outline.

    Takes a JSON array of sections, each with a chapter name and driving
    question. For each section, pulls the relevant papers from the library
    and formats the full context for drafting.

    Args:
        sections_json: JSON array like:
            [
              {"chapter": "introduction", "question": "What is the research landscape?", "words": 400},
              {"chapter": "bsde_methods", "question": "How have deep learning methods been applied?", "words": 800},
              ...
            ]
        word_target: Total target word count across all sections (default 3000)
        research_question: The overarching research question (for intro/conclusion framing)
    """
    try:
        sections = json.loads(sections_json)
    except json.JSONDecodeError:
        return "Invalid JSON. Provide a JSON array of {chapter, question, words} objects."

    if not sections:
        return "Empty sections list."

    lines = [
        "COMPLETE LITERATURE REVIEW ASSEMBLY",
        f"Sections: {len(sections)}",
        f"Target: ~{word_target} words total",
        "",
    ]

    if research_question:
        lines += [f"Overarching question: {research_question}", ""]

    lines += [
        "INSTRUCTIONS:",
        "Write the complete literature review as a single, cohesive document.",
        "Use [AuthorYear] inline citations throughout.",
        "Each section should flow naturally into the next with transition sentences.",
        "The overall arc should follow: established knowledge → gaps → recent advances → justification for new research.",
        "─" * 60,
        "",
    ]

    for i, section in enumerate(sections):
        chap = section.get("chapter", f"section_{i}")
        question = section.get("question", "")
        words = section.get("words", word_target // len(sections))

        # Fetch papers for this section
        papers = await db.list_papers(chapter=chap, sort_by="year", limit=50)

        lines.append(f"═══ SECTION {i+1}: {chap.replace('_', ' ').title()} (~{words} words) ═══")
        if question:
            lines.append(f"Driving question: {question}")
        lines.append("")

        if not papers:
            lines.append(f"  [No papers assigned to chapter '{chap}'. Use assign_chapter() first.]")
            lines.append("")
            continue

        # Group by move
        by_move: dict[str, list] = {"foundational": [], "gap": [], "parallel": [], "unclassified": []}
        for p in papers:
            m = p.move.value if p.move else "unclassified"
            by_move[m].append(p)

        for move_name, move_papers in by_move.items():
            if not move_papers:
                continue
            lines.append(f"  ── {move_name.upper()} ({len(move_papers)} papers) ──")
            for p in move_papers:
                cite = (p.authors[0].name.split()[-1] if p.authors else "?") + str(p.year or "")
                lines.append(f"  [{cite}] {p.title}")
                if p.summary:
                    lines.append(f"    Summary: {p.summary[:250]}...")
                elif p.abstract:
                    lines.append(f"    Abstract: {p.abstract[:250]}...")
                if p.key_findings:
                    lines.append(f"    Key findings: {'; '.join(p.key_findings[:3])}")
                if p.methodology:
                    lines.append(f"    Method: {p.methodology}")
                if p.limitations:
                    lines.append(f"    Limitations: {p.limitations}")
                lines.append("")

        lines.append("")

    lines += [
        "─" * 60,
        "Now write the complete literature review as one continuous document.",
        "Include all sections with smooth transitions between them.",
        "End with a conclusion that synthesises the gaps and justifies further research.",
    ]

    return "\n".join(lines)


# ── Entry point ──────────────────────────────────────────────────────

def main():
    mcp.run()

if __name__ == "__main__":
    main()
