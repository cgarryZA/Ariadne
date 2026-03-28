"""Shared formatting helpers used by multiple tool modules."""

from __future__ import annotations

from models import Paper


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
