"""Library management tools — add, remove, tag, rate, annotate papers."""

from __future__ import annotations

import asyncio
from typing import Optional

import db
from apis import openalex as oa
from apis import semantic_scholar as s2
from bibtex import paper_to_bibtex
from models import Paper, ReadingStatus
from tools.formatting import format_paper, format_result


def register(mcp):

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
    async def add_paper_openalex(identifier: str) -> str:
        """Add a paper from OpenAlex by DOI or OpenAlex ID.

        Use this for papers found via search_openalex() that don't have
        Semantic Scholar IDs.

        Args:
            identifier: DOI (e.g. '10.1145/3292500.3330925') or OpenAlex ID (e.g. 'W2741809807')
        """
        try:
            # If it looks like a DOI, use get_paper_by_doi
            if "/" in identifier or identifier.startswith("10."):
                data = await oa.get_paper_by_doi(identifier)
            else:
                # Try as DOI anyway (OpenAlex accepts Work IDs too)
                data = await oa.get_paper_by_doi(identifier)
        except Exception as e:
            return f"Error fetching paper from OpenAlex: {e}"

        paper = Paper(**data)
        paper.bibtex = paper_to_bibtex(paper)

        existing = await db.get_paper(paper.id)
        if existing:
            return f"Paper already in library: {existing.title}"

        await db.insert_paper(paper)
        return f"Added from OpenAlex: {paper.title} ({paper.year})\nID: {paper.id}"

    @mcp.tool()
    async def batch_add(paper_ids: str) -> str:
        """Add multiple papers at once by their IDs.

        Much faster than calling add_paper() individually. Includes rate
        limiting to respect API limits.

        Args:
            paper_ids: Comma-separated paper IDs (S2, DOI:xxx, or ARXIV:xxx)
        """
        ids = [pid.strip() for pid in paper_ids.split(",") if pid.strip()]
        if not ids:
            return "No paper IDs provided."

        added = []
        skipped = []
        failed = []

        for i, pid in enumerate(ids):
            if i > 0:
                await asyncio.sleep(1.2)  # Rate limiting

            existing = await db.get_paper(pid)
            if existing:
                skipped.append(f"{existing.title} (already in library)")
                continue

            try:
                data = await s2.get_paper_details(pid)
                fields = s2.parse_paper_to_library(data)
                paper = Paper(**fields)
                paper.bibtex = paper_to_bibtex(paper)
                await db.insert_paper(paper)
                added.append(f"{paper.title} ({paper.year})")
            except Exception as e:
                failed.append(f"{pid}: {e}")

        lines = [f"Batch add complete: {len(added)} added, {len(skipped)} skipped, {len(failed)} failed"]
        if added:
            lines.append("\nAdded:")
            lines.extend(f"  + {t}" for t in added)
        if skipped:
            lines.append("\nSkipped:")
            lines.extend(f"  ~ {t}" for t in skipped)
        if failed:
            lines.append("\nFailed:")
            lines.extend(f"  ! {t}" for t in failed)
        return "\n".join(lines)

    @mcp.tool()
    async def remove_paper(paper_id: str) -> str:
        """Remove a paper from the library.

        Args:
            paper_id: The paper's ID
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
            pillar: Filter by research pillar
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

        formatted = [await format_paper(p) for p in papers]
        return f"Library ({len(papers)} papers):\n\n" + "\n\n---\n\n".join(formatted)

    @mcp.tool()
    async def get_paper_details(paper_id: str) -> str:
        """Get full details for a paper in your library.

        Args:
            paper_id: The paper's ID
        """
        paper = await db.get_paper(paper_id)
        if not paper:
            return "Paper not found in library. Use add_paper() first."

        result = await format_paper(paper)
        if paper.abstract:
            result += f"\n\n**Abstract:**\n{paper.abstract}"
        return result

    @mcp.tool()
    async def get_fulltext(paper_id: str, max_chars: int = 5000) -> str:
        """Retrieve the stored full text of a downloaded paper's PDF.

        Use this to read the actual content of a paper after calling download_pdf().

        Args:
            paper_id: The paper's ID
            max_chars: Maximum characters to return (default 5000, use 0 for all)
        """
        paper = await db.get_paper(paper_id)
        if not paper:
            return "Paper not found in library."

        text = await db.get_fulltext(paper_id)
        if not text:
            return (
                f"No full text stored for '{paper.title}'.\n"
                "Use download_pdf() first to download and extract the text."
            )

        if max_chars > 0 and len(text) > max_chars:
            return (
                f"Full text of '{paper.title}' ({len(text):,} chars total, showing first {max_chars:,}):\n\n"
                + text[:max_chars] + "\n\n[... truncated — call with max_chars=0 for full text]"
            )
        return f"Full text of '{paper.title}' ({len(text):,} chars):\n\n{text}"

    @mcp.tool()
    async def tag_paper(paper_id: str, tags: str) -> str:
        """Add tags to a paper. New tags are appended to existing ones.

        Args:
            paper_id: The paper's ID
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
    async def remove_tag(paper_id: str, tag: str) -> str:
        """Remove a specific tag from a paper.

        Args:
            paper_id: The paper's ID
            tag: The tag to remove
        """
        paper = await db.get_paper(paper_id)
        if not paper:
            return "Paper not found in library."

        if tag not in paper.tags:
            return f"Tag '{tag}' not found on this paper. Current tags: {', '.join(paper.tags) or 'none'}"

        updated = [t for t in paper.tags if t != tag]
        await db.update_paper(paper_id, tags=updated)
        return f"Removed tag '{tag}'. Remaining tags: {', '.join(updated) or 'none'}"

    @mcp.tool()
    async def list_tags() -> str:
        """List all unique tags used across the library with paper counts."""
        papers = await db.list_papers(limit=500)
        tag_counts: dict[str, int] = {}
        for p in papers:
            for t in p.tags:
                tag_counts[t] = tag_counts.get(t, 0) + 1

        if not tag_counts:
            return "No tags in use."

        sorted_tags = sorted(tag_counts.items(), key=lambda x: -x[1])
        lines = [f"Tags in use ({len(sorted_tags)} unique):"]
        for tag, count in sorted_tags:
            lines.append(f"  {tag}: {count} paper{'s' if count != 1 else ''}")
        return "\n".join(lines)

    @mcp.tool()
    async def set_pillar(paper_id: str, pillar: str) -> str:
        """Assign a paper to a research pillar.

        Pillars are configured via setup_review(). If not configured, any
        string is accepted as a pillar name.

        Args:
            paper_id: The paper's ID
            pillar: Pillar name (e.g. 'pure_math', 'computational', 'financial')
        """
        configured = await db.get_pillars()
        if configured and pillar not in configured:
            suggestion = f" Configured pillars: {', '.join(configured)}."
            return f"Warning: '{pillar}' is not a configured pillar.{suggestion}\nUse setup_review() to update pillars, or pass a configured one."

        ok = await db.update_paper(paper_id, pillar=pillar)
        return f"Pillar set to '{pillar}'." if ok else "Paper not found."

    @mcp.tool()
    async def set_status(paper_id: str, status: str) -> str:
        """Update reading status for a paper.

        Args:
            paper_id: The paper's ID
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
            paper_id: The paper's ID
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
            paper_id: The paper's ID
            chapter: Section name (e.g. 'introduction', 'background', 'methodology') — any string is valid
        """
        ok = await db.update_paper(paper_id, chapter=chapter)
        return f"Assigned to chapter '{chapter}'." if ok else "Paper not found."

    @mcp.tool()
    async def annotate(paper_id: str, notes: str, append: bool = True) -> str:
        """Add or replace notes on a paper.

        Args:
            paper_id: The paper's ID
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
            paper_id: The paper's ID
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

    @mcp.tool()
    async def get_papers_by_chapter(chapter: str) -> str:
        """Get all papers assigned to a specific section or chapter.

        Args:
            chapter: Section name (e.g. 'introduction', 'background', 'methodology')
        """
        papers = await db.list_papers(chapter=chapter, sort_by="relevance")
        if not papers:
            return f"No papers assigned to chapter '{chapter}'."

        formatted = [await format_paper(p) for p in papers]
        return f"Chapter '{chapter}' ({len(papers)} papers):\n\n" + "\n\n---\n\n".join(formatted)

    @mcp.tool()
    async def get_papers_by_pillar(pillar: str) -> str:
        """Get all papers in a research pillar.

        Args:
            pillar: Pillar name
        """
        papers = await db.list_papers(pillar=pillar, sort_by="relevance")
        if not papers:
            return f"No papers in pillar '{pillar}'."

        formatted = [await format_paper(p) for p in papers]
        return f"Pillar '{pillar}' ({len(papers)} papers):\n\n" + "\n\n---\n\n".join(formatted)
