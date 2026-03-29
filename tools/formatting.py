"""Shared formatting and validation helpers used by multiple tool modules."""

from __future__ import annotations

from typing import Optional

from models import Paper


# ---------------------------------------------------------------------------
# Input validation helpers — prevent silent mismatches
# ---------------------------------------------------------------------------

async def validate_pillar(pillar: Optional[str]) -> Optional[str]:
    """Validate a pillar name against configured pillars.

    Returns None if pillar is None or valid.
    Returns an error message string if the pillar doesn't match any configured pillar.
    """
    if not pillar:
        return None

    import db
    configured = await db.get_pillars()
    if not configured:
        return None  # no pillars configured — accept anything

    # Exact match
    if pillar in configured:
        return None

    # Case-insensitive match
    lower_map = {p.lower(): p for p in configured}
    if pillar.lower() in lower_map:
        return None

    # Suggest closest match
    from difflib import get_close_matches
    suggestions = get_close_matches(pillar, configured, n=3, cutoff=0.4)

    msg = f"Pillar '{pillar}' not found. Configured pillars: {', '.join(configured)}"
    if suggestions:
        msg += f"\nDid you mean: {', '.join(suggestions)}?"
    return msg


async def resolve_paper_id(paper_id: str) -> tuple[Optional[str], Optional[str]]:
    """Try to resolve a paper_id, with fuzzy matching on failure.

    Returns (resolved_id, error_message).
    - If found: (paper_id, None)
    - If not found: (None, helpful error with suggestions)
    """
    import db

    # Exact match
    paper = await db.get_paper(paper_id)
    if paper:
        return paper_id, None

    # Try case-insensitive and partial ID match
    all_papers = await db.list_papers(limit=500)

    # Try partial ID match (user might have typed "han2018" instead of full S2 ID)
    partial_matches = []
    for p in all_papers:
        if paper_id.lower() in p.id.lower():
            partial_matches.append(p)

    if len(partial_matches) == 1:
        return partial_matches[0].id, None

    # Try title search (check if all query words appear in title)
    title_matches = []
    query_lower = paper_id.lower().replace("_", " ").replace("-", " ")
    query_words = [w for w in query_lower.split() if len(w) > 2]
    for p in all_papers:
        title_lower = p.title.lower()
        if query_lower in title_lower:
            title_matches.append(p)
        elif query_words and all(w in title_lower for w in query_words):
            title_matches.append(p)

    # Build error message with suggestions
    lines = [f"Paper '{paper_id}' not found in library."]

    if partial_matches:
        lines.append(f"\nPartial ID matches ({len(partial_matches)}):")
        for p in partial_matches[:5]:
            lines.append(f"  {p.id} — {p.title[:60]}")

    if title_matches:
        lines.append(f"\nTitle matches ({len(title_matches)}):")
        for p in title_matches[:5]:
            lines.append(f"  {p.id} — {p.title[:60]}")

    if not partial_matches and not title_matches:
        # Suggest by author name
        author_matches = []
        for p in all_papers:
            for a in p.authors:
                if query_lower in a.name.lower():
                    author_matches.append(p)
                    break
        if author_matches:
            lines.append(f"\nAuthor matches ({len(author_matches)}):")
            for p in author_matches[:5]:
                lines.append(f"  {p.id} — {p.title[:60]}")
        else:
            lines.append("\nTip: Use the full paper ID from add_paper() or list_library().")

    return None, "\n".join(lines)


def format_result(r) -> str:
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


async def format_paper(p: Paper) -> str:
    """Format a Paper for display, using configured extraction fields."""
    import db  # deferred to avoid circular import

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

    # Show configured extraction fields dynamically
    extraction_fields = await db.get_extraction_fields()
    field_labels = {
        "methodology": "Methodology",
        "limitations": "Limitations",
        "math_framework": "Math Framework",
        "convergence_bounds": "Convergence",
    }
    for field in extraction_fields:
        val = getattr(p, field, None)
        if val:
            label = field_labels.get(field, field.replace("_", " ").title())
            lines.append(f"  {label}: {val}")

    if p.notes:
        lines.append(f"  Notes: {p.notes[:200]}{'...' if len(p.notes or '') > 200 else ''}")
    return "\n".join(lines)


def format_paper_sync(p: Paper) -> str:
    """Synchronous format_paper for simple contexts (no config lookup)."""
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
