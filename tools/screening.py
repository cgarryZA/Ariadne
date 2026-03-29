"""Screening, PRISMA reporting, and deduplication tools."""

from __future__ import annotations

import re
from typing import Optional

import db
from tools.formatting import format_paper, validate_pillar
from tools._embeddings import is_available as embeddings_available


def _jaccard_similarity(a: str, b: str) -> float:
    """Word-level Jaccard similarity between two strings."""
    words_a = set(a.lower().split())
    words_b = set(b.lower().split())
    if not words_a or not words_b:
        return 0.0
    intersection = words_a & words_b
    union = words_a | words_b
    return len(intersection) / len(union)


def register(mcp):

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
            f"SCREENING TASK - {len(papers)} paper{'s' if len(papers) != 1 else ''}",
            "",
        ]
        if include_criteria:
            lines.append(f"INCLUDE if: {include_criteria}")
        if exclude_criteria:
            lines.append(f"EXCLUDE if: {exclude_criteria}")
        if include_criteria or exclude_criteria:
            lines.append("")

        lines.append("For each paper below, decide: INCLUDE / EXCLUDE / MAYBE (with brief reason)")
        lines.append("Then call tag_paper(id, 'screened-in') or tag_paper(id, 'screened-out')")
        lines.append("-" * 60)

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
        fields: Optional[str] = None,
    ) -> str:
        """Format multiple papers for bulk structured extraction.

        Returns abstracts + existing extraction data for all specified papers,
        ready for you to fill in the missing fields. After reviewing each paper,
        call set_extraction() to populate the fields.

        Args:
            paper_ids: Comma-separated IDs (optional — use pillar/chapter to select a group)
            pillar: Extract all papers in this pillar
            chapter: Extract all papers in this chapter
            fields: Comma-separated fields to extract (default: configured extraction fields)
        """
        pillar_err = await validate_pillar(pillar)
        if pillar_err:
            return pillar_err
        if paper_ids:
            ids = [pid.strip() for pid in paper_ids.split(",")]
            papers = [p for pid in ids if (p := await db.get_paper(pid))]
        elif pillar or chapter:
            papers = await db.list_papers(pillar=pillar, chapter=chapter, limit=100)
        else:
            papers = await db.list_papers(limit=100)

        if not papers:
            return "No papers found."

        # Use configured fields or provided override
        if fields:
            requested_fields = [f.strip() for f in fields.split(",")]
        else:
            requested_fields = await db.get_extraction_fields()

        field_names = {
            "methodology": "Methodology",
            "limitations": "Limitations",
            "math_framework": "Math Framework",
            "convergence_bounds": "Convergence Bounds",
        }

        lines = [
            f"BULK EXTRACTION TASK - {len(papers)} papers",
            f"Fields to extract: {', '.join(requested_fields)}",
            "",
            "For each paper, fill in the missing fields, then call:",
            "  set_extraction(paper_id, methodology=..., limitations=..., ...)",
            "-" * 60,
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
                status = f"  {current}" if current else "MISSING"
                display = field_names.get(field, field.replace("_", " ").title())
                lines.append(f"     {display}: {status}")

        filled = sum(
            1 for p in papers
            if all(getattr(p, f, None) for f in requested_fields if hasattr(p, f))
        )
        lines.append(f"\n{'-'*60}")
        lines.append(f"Coverage: {filled}/{len(papers)} papers fully extracted")

        return "\n".join(lines)

    @mcp.tool()
    async def generate_prisma_report() -> str:
        """Generate a PRISMA 2020-style flow report of your literature review process.

        Reads search history, paper counts, and screening tags to produce a
        structured audit trail showing: identified -> screened -> assessed -> included.
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

        return "\n".join(lines)

    @mcp.tool()
    async def deduplicate_library() -> str:
        """Find duplicate papers using DOI matching, exact title matching,
        fuzzy title similarity, and semantic embedding similarity.

        Uses local embeddings (sentence-transformers) when available for
        higher-quality dedup. Falls back to Jaccard word-set similarity.

        Returns suspected duplicates for review. Does not auto-delete anything.
        """
        papers = await db.list_papers(limit=500)

        # Check by DOI
        doi_map: dict[str, list] = {}
        for p in papers:
            if p.doi:
                doi_map.setdefault(p.doi.lower(), []).append(p)

        # Check by exact normalized title
        title_map: dict[str, list] = {}
        for p in papers:
            key = " ".join(p.title.lower().split())[:80]
            title_map.setdefault(key, []).append(p)

        duplicates = []
        seen_ids: set = set()

        for doi, group in doi_map.items():
            if len(group) > 1:
                ids = frozenset(p.id for p in group)
                if ids not in seen_ids:
                    duplicates.append(("DOI", doi, group))
                    seen_ids.add(ids)

        for title_key, group in title_map.items():
            if len(group) > 1:
                ids = frozenset(p.id for p in group)
                if ids not in seen_ids:
                    duplicates.append(("Title", title_key[:60], group))
                    seen_ids.add(ids)

        # Semantic or fuzzy title matching
        if embeddings_available() and len(papers) >= 2:
            from tools._embeddings import find_semantic_duplicates
            titles = [p.title for p in papers]
            semantic_pairs = find_semantic_duplicates(titles, threshold=0.85)
            for i, j, sim in semantic_pairs:
                pair_ids = frozenset((papers[i].id, papers[j].id))
                if pair_ids not in seen_ids:
                    duplicates.append(("Semantic", f"{sim:.0%} similar", [papers[i], papers[j]]))
                    seen_ids.add(pair_ids)
        else:
            # Fallback: Jaccard on word sets
            for i, p1 in enumerate(papers):
                for p2 in papers[i+1:]:
                    if p1.id == p2.id:
                        continue
                    pair_ids = frozenset((p1.id, p2.id))
                    if pair_ids in seen_ids:
                        continue
                    sim = _jaccard_similarity(p1.title, p2.title)
                    if sim > 0.85:
                        duplicates.append(("Fuzzy title", f"{sim:.0%} similar", [p1, p2]))
                        seen_ids.add(pair_ids)

        if not duplicates:
            method = "semantic embeddings" if embeddings_available() else "Jaccard similarity"
            return f"No duplicates found in {len(papers)}-paper library (checked via {method})."

        lines = [f"Found {len(duplicates)} duplicate group(s):\n"]
        for reason, key, group in duplicates:
            lines.append(f"[{reason} match: {key}]")
            for p in group:
                lines.append(f"  ID: {p.id} | {p.title[:70]} ({p.year})")
            lines.append("  -> Keep one, remove others with remove_paper(id)")
            lines.append("")

        return "\n".join(lines)
