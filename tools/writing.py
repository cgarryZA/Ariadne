"""Writing pipeline tools — draft sections, outline, assemble review."""

from __future__ import annotations

import json
from typing import Optional

import db


def register(mcp):

    @mcp.tool()
    async def generate_search_strategy(
        research_question: str,
        field: str = "general",
        num_themes: int = 3,
    ) -> str:
        """Generate a systematic search strategy from a research question.

        Args:
            research_question: The central research question driving the review
            field: Academic field (e.g. 'mathematics', 'computer_science', 'finance')
            num_themes: Number of thematic strands to search (default 3)
        """
        stats = await db.library_stats()

        # Store the research question in config for later use
        await db.set_config("research_question", research_question)

        arx_categories = {
            "mathematics": "math.PR, math.NA, math.AP, math.OC",
            "computer_science": "cs.LG, cs.AI, cs.NE, cs.CE",
            "finance": "q-fin.TR, q-fin.MF, q-fin.CP, q-fin.RM",
            "physics": "physics.comp-ph, cond-mat.stat-mech",
            "statistics": "stat.ML, stat.ME, stat.TH",
            "biology": "q-bio.BM, q-bio.GN, q-bio.QM",
            "engineering": "eess.SP, eess.SY, cs.CE",
        }
        suggested_cats = arx_categories.get(field, "cs.LG, math.NA")

        lines = [
            "SEARCH STRATEGY GENERATOR",
            f"Research Question: {research_question}",
            f"Field: {field}",
            f"Current library: {stats['total']} papers",
            "",
            "-" * 60,
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
            "  3. Add relevant papers with add_paper() or batch_add()",
            "  4. Build citation links with build_citation_network() on 3-4 seed papers",
            "  5. Deduplicate with deduplicate_library()",
            "  6. Screen with screen_papers(include_criteria, exclude_criteria)",
        ]

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

        Args:
            chapter: Papers assigned to this chapter/section
            pillar: Papers in this research pillar
            research_question: The section's driving question
            word_target: Target word count (default 600)
            style: 'critical' (default) | 'descriptive' | 'thematic' | 'chronological'
        """
        if not research_question:
            research_question = await db.get_config("research_question")

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

        style_guide = {
            "critical": (
                "Write critically: don't just describe what each paper does - compare, contrast, and critique. "
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
                "Show how early foundational work was extended, challenged, or superseded. "
                "Make the narrative of scientific progress explicit."
            ),
        }
        lines += [f"Writing guidance: {style_guide.get(style, style_guide['critical'])}", ""]

        lines += [
            "Citation format: [AuthorYear] - e.g. [Han2018], [Weinan2017], [Carmona2018]",
            "-" * 60,
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
                lines.append(f"  Pillar: {p.pillar}")
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
            "-" * 60,
            f"Now write the ~{word_target}-word {style} literature review section.",
            "Use [AuthorYear] citations throughout. Do not pad - be precise and critical.",
        ]
        if research_question:
            lines.append(f"Ensure the section builds toward answering: {research_question}")

        return "\n".join(lines)

    @mcp.tool()
    async def generate_review_outline(
        research_question: str,
        structure_style: str = "parallel",
        themes: Optional[str] = None,
    ) -> str:
        """Generate a literature review outline following the Oxford model.

        Three Oxford organisational styles:
        - BLOCK:    Topic A (found->gap->parallel), Topic B (found->gap->parallel), Conclude
        - PARALLEL: All foundational (A+B), All gaps (A+B), All parallel (A+B), Conclude
        - MIXED:    Topic A (found+gap), Topic B (found+gap), Parallel (A+B), Conclude

        Args:
            research_question: The central question driving the review
            structure_style: 'block', 'parallel', or 'mixed' (default: parallel)
            themes: Comma-separated theme names to structure around (auto-detected if omitted)
        """
        papers = await db.list_papers(sort_by="year", limit=200)
        stats = await db.library_stats()

        if not papers:
            return "Library is empty. Add papers first."

        move_counts: dict[str, int] = {"foundational": 0, "gap": 0, "parallel": 0, "unclassified": 0}
        for p in papers:
            m = p.move.value if p.move else "unclassified"
            move_counts[m] = move_counts.get(m, 0) + 1

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
            "-- MOVE DISTRIBUTION --",
            f"  Foundational: {move_counts['foundational']}",
            f"  Gap:          {move_counts['gap']}",
            f"  Parallel:     {move_counts['parallel']}",
            f"  Unclassified: {move_counts['unclassified']}",
        ]

        if move_counts["unclassified"] > 0:
            lines.append(f"  -> Run classify_moves() to classify the {move_counts['unclassified']} unclassified papers")

        lines += ["", "-- THEMES --"]
        if requested_themes:
            for t in requested_themes:
                lines.append(f"  {t}: {all_themes.get(t, 0)} papers")
        else:
            lines.append("  No themes assigned yet. Use set_themes() to assign thematic tags.")

        lines += ["", "-- PILLAR DISTRIBUTION --"]
        for pillar, count in stats["by_pillar"].items():
            lines.append(f"  {pillar}: {count}")

        style_desc = {
            "block": (
                "BLOCK STYLE: Complete each theme before moving to the next.\n"
                "  Section 1: Introduction (general foundations)\n"
                "  Section 2: Theme A - foundational -> gap -> parallel research\n"
                "  Section 3: Theme B - foundational -> gap -> parallel research\n"
                "  Section N: Conclusion - link knowns, summarise unknowns, justify your research"
            ),
            "parallel": (
                "PARALLEL STYLE: Group by move type across all themes.\n"
                "  Section 1: Introduction (general foundations)\n"
                "  Section 2: Foundational knowledge (Theme A + B + ...)\n"
                "  Section 3: Establishing gaps (Theme A + B + ...)\n"
                "  Section 4: Parallel research (Theme A + B + ...)\n"
                "  Section 5: Conclusion - link knowns, summarise unknowns, justify your research"
            ),
            "mixed": (
                "MIXED STYLE: Foundational + gap per theme, then parallel across all.\n"
                "  Section 1: Introduction (general foundations)\n"
                "  Section 2: Theme A - foundational + gap identification\n"
                "  Section 3: Theme B - foundational + gap identification\n"
                "  Section 4: Parallel research across all themes\n"
                "  Section 5: Conclusion - link knowns, summarise unknowns, justify your research"
            ),
        }
        lines += [
            "",
            "-- RECOMMENDED STRUCTURE --",
            style_desc.get(structure_style, style_desc["parallel"]),
        ]

        lines += [
            "",
            "-" * 60,
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

        Args:
            sections_json: JSON array like:
                [
                  {"chapter": "introduction", "question": "What is the research landscape?", "words": 400},
                  {"chapter": "bsde_methods", "question": "How have deep learning methods been applied?", "words": 800},
                  ...
                ]
            word_target: Total target word count across all sections (default 3000)
            research_question: The overarching research question
        """
        try:
            sections = json.loads(sections_json)
        except json.JSONDecodeError:
            return "Invalid JSON. Provide a JSON array of {chapter, question, words} objects."

        if not sections:
            return "Empty sections list."

        if not research_question:
            research_question = await db.get_config("research_question")

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
            "The overall arc should follow: established knowledge -> gaps -> recent advances -> justification for new research.",
            "-" * 60,
            "",
        ]

        for i, section in enumerate(sections):
            chap = section.get("chapter", f"section_{i}")
            question = section.get("question", "")
            words = section.get("words", word_target // len(sections))

            papers = await db.list_papers(chapter=chap, sort_by="year", limit=50)

            lines.append(f"=== SECTION {i+1}: {chap.replace('_', ' ').title()} (~{words} words) ===")
            if question:
                lines.append(f"Driving question: {question}")
            lines.append("")

            if not papers:
                lines.append(f"  [No papers assigned to chapter '{chap}'. Use assign_chapter() first.]")
                lines.append("")
                continue

            by_move: dict[str, list] = {"foundational": [], "gap": [], "parallel": [], "unclassified": []}
            for p in papers:
                m = p.move.value if p.move else "unclassified"
                by_move[m].append(p)

            for move_name, move_papers in by_move.items():
                if not move_papers:
                    continue
                lines.append(f"  -- {move_name.upper()} ({len(move_papers)} papers) --")
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
            "-" * 60,
            "Now write the complete literature review as one continuous document.",
            "Include all sections with smooth transitions between them.",
            "End with a conclusion that synthesises the gaps and justifies further research.",
        ]

        return "\n".join(lines)
