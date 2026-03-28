"""First-run wizard and review configuration tools."""

from __future__ import annotations

import json
from collections import Counter
from typing import Optional

import db


def register(mcp):

    @mcp.tool()
    async def setup_review(
        research_question: Optional[str] = None,
        pillars: Optional[str] = None,
        extraction_fields: Optional[str] = None,
    ) -> str:
        """Set up your literature review — define your research domain.

        Call this at the start of a new review to configure your pillars
        (research sub-domains) and extraction fields. If you're unsure about
        pillars, you can:
        - Leave pillars blank and call auto_detect_pillars() after adding ~10+ papers
        - Or describe your topic and let Claude suggest appropriate pillars

        Args:
            research_question: The central question driving your review
                               (e.g. 'How do deep learning methods compare to classical PDE solvers?')
            pillars: Pipe-separated pillar/domain names
                     (e.g. 'pure_math|computational|financial')
                     Leave empty to configure later or use auto_detect_pillars()
            extraction_fields: Pipe-separated extraction field names
                               (default: methodology|limitations|math_framework|convergence_bounds)
                               Customise for your domain, e.g. 'methodology|sample_size|population|outcome_measure'
        """
        config_updates = []

        if research_question:
            await db.set_config("research_question", research_question)
            config_updates.append(f"Research question: {research_question}")

        if pillars:
            pillar_list = [p.strip() for p in pillars.split("|") if p.strip()]
            await db.set_config_json("pillars", pillar_list)
            config_updates.append(f"Pillars: {', '.join(pillar_list)}")

        if extraction_fields:
            field_list = [f.strip() for f in extraction_fields.split("|") if f.strip()]
            await db.set_config_json("extraction_fields", field_list)
            config_updates.append(f"Extraction fields: {', '.join(field_list)}")

        if config_updates:
            return "Review configured:\n" + "\n".join(f"  {u}" for u in config_updates)

        # No args — show current config and help
        current = await get_review_config_internal()
        lines = [
            "REVIEW SETUP WIZARD",
            "",
            "Current configuration:",
            current,
            "",
            "-" * 60,
            "To configure your review, call setup_review() with:",
            "",
            "  research_question: Your central research question",
            "    Example: 'How do deep learning methods solve high-dimensional PDEs?'",
            "",
            "  pillars: Your research sub-domains (pipe-separated)",
            "    Example: 'theoretical|computational|applied'",
            "    Example: 'genomics|proteomics|metabolomics'",
            "    Example: 'qualitative|quantitative|mixed_methods'",
            "    Leave blank and use auto_detect_pillars() after adding papers",
            "",
            "  extraction_fields: Structured fields to extract from each paper (pipe-separated)",
            "    Default: methodology|limitations|math_framework|convergence_bounds",
            "    Biomedical: methodology|sample_size|population|outcome_measure|bias_risk",
            "    Social science: methodology|sample_size|population|effect_size|limitations",
            "",
            "Or just tell me about your research topic and I'll suggest a configuration.",
        ]
        return "\n".join(lines)

    @mcp.tool()
    async def auto_detect_pillars(num_pillars: int = 3) -> str:
        """Analyze your library papers and suggest research pillars/domains.

        Examines venues, abstracts, tags, and keywords to identify natural
        groupings in your paper collection. Requires at least 5 papers in
        the library for meaningful results.

        After reviewing suggestions, call setup_review(pillars='a|b|c') to confirm.

        Args:
            num_pillars: Number of pillar groups to suggest (default 3)
        """
        papers = await db.list_papers(sort_by="citation_count", limit=200)

        if len(papers) < 5:
            return (
                f"Only {len(papers)} papers in library — need at least 5 for meaningful analysis.\n"
                "Add more papers first, then try again."
            )

        # Collect signals: venues, tags, title/abstract keywords
        venue_counts = Counter()
        tag_counts = Counter()
        word_counts = Counter()

        # Common academic stop words to filter out
        stop_words = {
            "the", "a", "an", "of", "in", "for", "and", "or", "to", "on", "with",
            "by", "from", "is", "are", "was", "were", "be", "been", "this", "that",
            "we", "our", "their", "its", "it", "as", "at", "which", "has", "have",
            "not", "can", "using", "based", "via", "new", "approach", "method",
            "paper", "study", "results", "show", "propose", "problem", "model",
            "models", "data", "these", "than", "also", "between", "two", "used",
        }

        for p in papers:
            if p.venue:
                venue_counts[p.venue] += 1
            for t in p.tags:
                tag_counts[t] += 1

            # Extract meaningful words from title + abstract
            text = (p.title or "") + " " + (p.abstract or "")[:200]
            words = text.lower().split()
            for w in words:
                w = w.strip(".,;:!?()[]{}\"'")
                if len(w) > 3 and w not in stop_words and w.isalpha():
                    word_counts[w] += 1

        # Analyze existing pillars if any are already assigned
        pillar_counts = Counter()
        for p in papers:
            if p.pillar:
                pillar_counts[p.pillar] += 1

        lines = [
            f"AUTO-DETECT PILLARS — Analyzing {len(papers)} papers",
            "",
        ]

        if pillar_counts:
            lines.append("Already-assigned pillars:")
            for pillar, count in pillar_counts.most_common():
                lines.append(f"  {pillar}: {count} papers")
            lines.append("")

        # Top venues (suggest domain clusters)
        if venue_counts:
            lines.append("Top venues (suggest domain clusters):")
            for venue, count in venue_counts.most_common(10):
                lines.append(f"  {venue}: {count} papers")
            lines.append("")

        # Top keywords
        if word_counts:
            lines.append("Top keywords:")
            for word, count in word_counts.most_common(20):
                lines.append(f"  {word}: {count}")
            lines.append("")

        # Top tags
        if tag_counts:
            lines.append("Existing tags:")
            for tag, count in tag_counts.most_common(10):
                lines.append(f"  {tag}: {count}")
            lines.append("")

        lines += [
            "-" * 60,
            f"TASK: Based on the above signals, suggest {num_pillars} research pillars",
            "that capture the main sub-domains in this library.",
            "",
            "Good pillars are:",
            "  - Mutually exclusive (a paper belongs to at most one)",
            "  - Collectively exhaustive (every paper fits somewhere)",
            "  - Meaningful for structuring a literature review",
            "",
            "After deciding, call:",
            "  setup_review(pillars='pillar_a|pillar_b|pillar_c')",
        ]

        return "\n".join(lines)

    @mcp.tool()
    async def get_review_config() -> str:
        """Show the current review configuration (pillars, extraction fields, research question)."""
        return await get_review_config_internal()

    @mcp.tool()
    async def update_extraction_fields(fields: str) -> str:
        """Update the list of structured extraction fields.

        These are the fields extracted from each paper (shown in bulk_extract,
        compare_papers, synthesis_matrix, etc.).

        Args:
            fields: Pipe-separated field names (e.g. 'methodology|sample_size|effect_size|limitations')
        """
        field_list = [f.strip() for f in fields.split("|") if f.strip()]
        if not field_list:
            return "No fields provided."

        await db.set_config_json("extraction_fields", field_list)
        return f"Extraction fields updated: {', '.join(field_list)}"


async def get_review_config_internal() -> str:
    """Internal helper to format the current config."""
    rq = await db.get_config("research_question")
    pillars = await db.get_pillars()
    fields = await db.get_extraction_fields()

    lines = []
    lines.append(f"  Research question: {rq or '(not set)'}")
    lines.append(f"  Pillars: {', '.join(pillars) if pillars else '(not set — run setup_review or auto_detect_pillars)'}")
    lines.append(f"  Extraction fields: {', '.join(fields)}")
    return "\n".join(lines)
