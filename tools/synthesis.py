"""Active intelligence tools — contradiction detection, iterative research loop, auto-synthesis,
missing lemma generation, notation standardization.

Phase 3 (items 3.1-3.3) + Phase 4 (items 4.3, 4.5): Generate net-new academic insights,
encode iterative research, cross-reference domains, standardize notation.
"""

from __future__ import annotations

from typing import Optional

import db
from tools._llm_client import extract, is_available as llm_available
from tools._text_processing import budget_text
from tools.formatting import validate_pillar, resolve_paper_id


def register(mcp):

    @mcp.tool()
    async def detect_contradictions(
        paper_ids: Optional[str] = None,
        pillar: Optional[str] = None,
        chapter: Optional[str] = None,
    ) -> str:
        """Detect contradictions and methodological disagreements across papers.

        Compares extracted claims and findings across papers targeting the same
        problem. Flags improvements, regressions, and conflicting conclusions.

        If ANTHROPIC_API_KEY is set, uses internal LLM for automated detection.
        Otherwise formats papers for manual analysis.

        Args:
            paper_ids: Comma-separated IDs (or use pillar/chapter to select a group)
            pillar: Select papers in this pillar
            chapter: Select papers in this chapter
        """
        pillar_err = await validate_pillar(pillar)
        if pillar_err:
            return pillar_err

        if paper_ids:
            ids = [pid.strip() for pid in paper_ids.split(",")]
            papers = [p for pid in ids if (p := await db.get_paper(pid))]
        else:
            papers = await db.list_papers(pillar=pillar, chapter=chapter, sort_by="year", limit=50)

        if len(papers) < 2:
            scope = f" in pillar '{pillar}'" if pillar else (f" in chapter '{chapter}'" if chapter else "")
            return f"Need at least 2 papers{scope} to detect contradictions. Found {len(papers)}."

        # Build a summary of each paper's claims
        paper_claims = []
        for p in papers:
            cite = (p.authors[0].name.split()[-1] if p.authors else "?") + str(p.year or "")
            claims = []
            if p.key_findings:
                claims.extend(p.key_findings)
            if p.methodology:
                claims.append(f"Method: {p.methodology}")
            if p.limitations:
                claims.append(f"Limitations: {p.limitations}")
            if p.convergence_bounds:
                claims.append(f"Convergence: {p.convergence_bounds}")
            paper_claims.append((cite, p.title, p.id, claims))

        lines = [
            "CONTRADICTION & DISAGREEMENT ANALYSIS",
            f"Papers: {len(papers)}",
            "",
        ]

        # If LLM is available, do pairwise contradiction detection on high-signal pairs
        if llm_available() and any(claims for _, _, _, claims in paper_claims):
            lines.append("[Using internal LLM for automated detection]")
            lines.append("")

            contradictions_found = []
            # Compare papers pairwise (limit to avoid explosion)
            pairs = []
            for i, (cite_a, title_a, id_a, claims_a) in enumerate(paper_claims):
                for cite_b, title_b, id_b, claims_b in paper_claims[i + 1:]:
                    if claims_a and claims_b:
                        pairs.append((cite_a, title_a, claims_a, cite_b, title_b, claims_b))

            for cite_a, title_a, claims_a, cite_b, title_b, claims_b in pairs[:15]:
                text = (
                    f"Paper A [{cite_a}]: {title_a}\n"
                    f"Claims: {'; '.join(claims_a)}\n\n"
                    f"Paper B [{cite_b}]: {title_b}\n"
                    f"Claims: {'; '.join(claims_b)}"
                )
                try:
                    result = await extract(text, "detect_contradictions")
                    tension = result.data.get("tension_level", "none")
                    contras = result.data.get("contradictions", [])
                    if tension != "none" and contras:
                        contradictions_found.append(
                            f"**[{cite_a}] vs [{cite_b}]** — tension: {tension}\n"
                            + "\n".join(f"  - {c}" for c in contras)
                        )
                except Exception:
                    pass  # graceful degradation

            if contradictions_found:
                lines.append(f"Found {len(contradictions_found)} contradictions/tensions:\n")
                lines.extend(contradictions_found)
            else:
                lines.append("No significant contradictions detected in extracted claims.")
                lines.append("Note: quality depends on having key_findings and methodology extracted.")

            return "\n".join(lines)

        # Fallback: format for manual analysis by Claude
        lines.append("Paper claims summary (for manual contradiction analysis):")
        lines.append("-" * 60)

        for cite, title, pid, claims in paper_claims:
            lines.append(f"\n[{cite}] {title}")
            lines.append(f"  ID: {pid}")
            if claims:
                for c in claims:
                    lines.append(f"  - {c}")
            else:
                lines.append("  [no claims extracted — run extract_key_findings first]")

        lines += [
            "",
            "-" * 60,
            "TASK: Compare claims across papers and identify:",
            "  1. Direct contradictions (Paper A says X works; Paper B says X fails)",
            "  2. Methodological disagreements (different approaches to same problem)",
            "  3. Conflicting quantitative results (different performance numbers)",
            "  4. Implicit tensions (unstated disagreements in assumptions)",
        ]

        return "\n".join(lines)

    @mcp.tool()
    async def refine_research_question(
        pillar: Optional[str] = None,
        chapter: Optional[str] = None,
    ) -> str:
        """Analyze your library and suggest how to refine your research question.

        Based on the papers you've collected so far, identifies:
        - What your library actually covers vs what your question asks
        - Sub-questions that have strong evidence
        - Sub-questions with no coverage (blind spots)
        - Suggested refined or narrowed questions

        Args:
            pillar: Limit analysis to a specific pillar
            chapter: Limit analysis to a specific chapter
        """
        pillar_err = await validate_pillar(pillar)
        if pillar_err:
            return pillar_err

        research_question = await db.get_config("research_question")
        papers = await db.list_papers(pillar=pillar, chapter=chapter, sort_by="year", limit=200)
        stats = await db.library_stats()

        if not papers:
            scope = f" in pillar '{pillar}'" if pillar else (f" in chapter '{chapter}'" if chapter else "")
            return f"No papers found{scope}. Add papers first."

        # Collect coverage signals
        methods = set()
        themes_count: dict[str, int] = {}
        year_range = [9999, 0]
        has_extraction = 0
        has_summary = 0
        has_move = 0

        for p in papers:
            if p.methodology:
                methods.add(p.methodology[:60])
            for t in (p.themes or []):
                themes_count[t] = themes_count.get(t, 0) + 1
            if p.year:
                year_range[0] = min(year_range[0], p.year)
                year_range[1] = max(year_range[1], p.year)
            if p.methodology or p.limitations:
                has_extraction += 1
            if p.summary:
                has_summary += 1
            if p.move:
                has_move += 1

        lines = [
            "RESEARCH QUESTION REFINEMENT",
            f"Current question: {research_question or '(not set)'}",
            f"Library scope: {len(papers)} papers",
            "",
            "-- COVERAGE ANALYSIS --",
            f"Year range: {year_range[0]}-{year_range[1]}" if year_range[1] > 0 else "No years",
            f"Papers with extraction data: {has_extraction}/{len(papers)}",
            f"Papers summarised: {has_summary}/{len(papers)}",
            f"Papers classified (Oxford move): {has_move}/{len(papers)}",
            "",
        ]

        if methods:
            lines.append(f"Distinct methodologies found ({len(methods)}):")
            for m in sorted(methods)[:15]:
                lines.append(f"  - {m}")
            lines.append("")

        if themes_count:
            lines.append("Theme coverage:")
            for t, c in sorted(themes_count.items(), key=lambda x: -x[1])[:10]:
                lines.append(f"  {t}: {c} papers")
            lines.append("")

        lines.append("By pillar:")
        for pillar_name, count in stats["by_pillar"].items():
            lines.append(f"  {pillar_name}: {count}")

        lines += [
            "",
            "-" * 60,
            "TASK: Based on this coverage analysis, suggest:",
            "  1. Is the current question too broad? Suggest 2-3 narrower alternatives.",
            "  2. Is there a sub-question with zero coverage? (blind spot)",
            "  3. What additional search queries would fill the gaps?",
            "  4. Are there pillars with too few or too many papers?",
        ]

        if not research_question:
            lines.append("  5. Based on the papers, infer what the research question IS and propose it.")

        return "\n".join(lines)

    @mcp.tool()
    async def suggest_new_queries(
        max_suggestions: int = 5,
    ) -> str:
        """Analyze gaps in your library and suggest new search queries.

        Examines what your library covers well and what's missing, then
        generates targeted queries for each gap. Designed to be called
        after an initial round of searching + screening.

        Args:
            max_suggestions: Maximum number of query suggestions (default 5)
        """
        research_question = await db.get_config("research_question")
        papers = await db.list_papers(sort_by="year", limit=200)
        pillars = await db.get_pillars()

        if len(papers) < 5:
            return "Need at least 5 papers before suggesting new queries. Keep searching."

        # Analyze coverage by pillar
        pillar_counts: dict[str, int] = {}
        for p in papers:
            pl = p.pillar or "unassigned"
            pillar_counts[pl] = pillar_counts.get(pl, 0) + 1

        # Find pillars with low coverage
        if pillars:
            underserved = [pl for pl in pillars if pillar_counts.get(pl, 0) < 3]
        else:
            underserved = []

        # Find year gaps
        years = sorted(set(p.year for p in papers if p.year))
        year_gaps = []
        if len(years) >= 2:
            for i in range(len(years) - 1):
                if years[i + 1] - years[i] > 2:
                    year_gaps.append(f"{years[i]}-{years[i+1]}")

        # Find methods mentioned but not well-covered
        method_mentions: dict[str, int] = {}
        for p in papers:
            if p.methodology:
                key = p.methodology[:40].lower().strip()
                method_mentions[key] = method_mentions.get(key, 0) + 1

        rare_methods = [m for m, c in method_mentions.items() if c == 1]

        # Collect existing search terms
        history = await db.get_search_history(limit=50)
        past_queries = set(h.get("query", "") for h in history)

        lines = [
            "SUGGESTED NEW QUERIES",
            f"Research question: {research_question or '(not set)'}",
            f"Current library: {len(papers)} papers | Past searches: {len(past_queries)}",
            "",
        ]

        suggestions = []
        suggestion_num = 0

        # Pillar-gap queries
        for pl in underserved[:2]:
            if suggestion_num >= max_suggestions:
                break
            suggestion_num += 1
            suggestions.append(
                f"{suggestion_num}. **PILLAR GAP: '{pl}'** (only {pillar_counts.get(pl, 0)} papers)\n"
                f"   Suggested query: '{research_question or ''} {pl} survey'\n"
                f"   Reason: Underrepresented pillar needs more coverage."
            )

        # Year-gap queries
        for gap in year_gaps[:1]:
            if suggestion_num >= max_suggestions:
                break
            suggestion_num += 1
            suggestions.append(
                f"{suggestion_num}. **TEMPORAL GAP: {gap}**\n"
                f"   Suggested query: '{research_question or 'methods'} {gap}'\n"
                f"   Reason: No papers found in this year range."
            )

        # Rare-method queries
        for method in rare_methods[:2]:
            if suggestion_num >= max_suggestions:
                break
            suggestion_num += 1
            suggestions.append(
                f"{suggestion_num}. **METHOD DEEP-DIVE: '{method}'** (only 1 paper)\n"
                f"   Suggested query: '{method} {research_question or ''}'\n"
                f"   Reason: Method mentioned once — need more papers to compare."
            )

        if not suggestions:
            lines.append("Your library coverage looks balanced. No obvious gaps detected.")
            lines.append("Consider running identify_gaps() for a more detailed analysis.")
        else:
            lines.extend(suggestions)

        lines += [
            "",
            "-" * 60,
            "Execute suggested queries with multi_search(query, year_range=...)",
            "Then run batch_add() on relevant results.",
        ]

        return "\n".join(lines)

    @mcp.tool()
    async def auto_synthesize(
        pillar: Optional[str] = None,
        chapter: Optional[str] = None,
        dimension: Optional[str] = None,
    ) -> str:
        """Automatically generate a synthesis across papers.

        Upgrades compare_papers into an intelligent engine that detects:
        - Improvements over time (method A supersedes method B)
        - Regressions (newer method performs worse on some metric)
        - Methodological camps (groups of papers using fundamentally different approaches)
        - Consensus vs contention areas

        Args:
            pillar: Select papers in this pillar
            chapter: Select papers in this chapter
            dimension: Focus on a specific dimension (e.g. 'methodology', 'convergence_bounds')
        """
        pillar_err = await validate_pillar(pillar)
        if pillar_err:
            return pillar_err

        papers = await db.list_papers(pillar=pillar, chapter=chapter, sort_by="year", limit=50)

        if len(papers) < 3:
            scope = f" in pillar '{pillar}'" if pillar else (f" in chapter '{chapter}'" if chapter else "")
            return f"Need at least 3 papers{scope} for meaningful synthesis. Found {len(papers)}."

        extraction_fields = await db.get_extraction_fields()

        # Group papers by methodology type
        method_groups: dict[str, list] = {}
        for p in papers:
            key = (p.methodology or "unknown")[:50].lower().strip()
            method_groups.setdefault(key, []).append(p)

        # Track evolution over time
        temporal = []
        for p in sorted(papers, key=lambda x: x.year or 0):
            cite = (p.authors[0].name.split()[-1] if p.authors else "?") + str(p.year or "")
            temporal.append({
                "cite": cite,
                "year": p.year,
                "method": p.methodology or "?",
                "findings": "; ".join(p.key_findings[:2]) if p.key_findings else "?",
                "quality": p.quality_score,
                "move": p.move.value if p.move else "?",
            })

        lines = [
            "AUTO-SYNTHESIS ENGINE",
            f"Papers: {len(papers)} | Distinct methods: {len(method_groups)}",
            "",
            "-- METHODOLOGICAL CAMPS --",
        ]

        for method, group in sorted(method_groups.items(), key=lambda x: -len(x[1])):
            cites = [
                (p.authors[0].name.split()[-1] if p.authors else "?") + str(p.year or "")
                for p in group
            ]
            avg_quality = 0
            quality_papers = [p for p in group if p.quality_score]
            if quality_papers:
                avg_quality = sum(p.quality_score for p in quality_papers) / len(quality_papers)
            lines.append(
                f"  {method}: {len(group)} papers [{', '.join(cites)}]"
                + (f" | avg quality: {avg_quality:.1f}/5" if avg_quality else "")
            )

        lines += ["", "-- TEMPORAL EVOLUTION --"]
        for entry in temporal:
            lines.append(
                f"  [{entry['cite']}] ({entry['year'] or '?'}) "
                f"| {entry['move']} | method: {entry['method'][:40]}"
            )
            if entry["findings"] != "?":
                lines.append(f"    findings: {entry['findings'][:120]}")

        # Detect potential progressions/regressions
        if dimension:
            focus_fields = [dimension]
        else:
            focus_fields = [f for f in extraction_fields if any(getattr(p, f, None) for p in papers)]

        if focus_fields:
            lines += ["", f"-- FIELD-LEVEL COMPARISON ({', '.join(focus_fields)}) --"]
            for field in focus_fields:
                lines.append(f"\n  {field.replace('_', ' ').title()}:")
                for p in sorted(papers, key=lambda x: x.year or 0):
                    val = getattr(p, field, None)
                    if val:
                        cite = (p.authors[0].name.split()[-1] if p.authors else "?") + str(p.year or "")
                        lines.append(f"    [{cite}]: {val[:100]}")

        lines += [
            "",
            "-" * 60,
            "TASK: Based on the above data, synthesize:",
            "  1. Which methodological camp is winning? (most papers, highest quality, most recent)",
            "  2. Has there been clear progression over time? Or oscillation?",
            "  3. Where do camps disagree? What assumptions differ?",
            "  4. What hybrid approach would combine the best of each camp?",
        ]

        return "\n".join(lines)

    @mcp.tool()
    async def generate_future_research_gaps(
        num_proposals: int = 3,
    ) -> str:
        """Cross-reference computational limitations against theoretical frameworks
        to generate specific, viable open research problems (PhD pitch tool).

        Compares the 'limitations' of computational papers against the
        'math_framework' of theoretical papers to find proofs that exist in theory
        but haven't been coded, or code that works but lacks theory.

        Args:
            num_proposals: Number of proposals to generate (default 3)
        """
        papers = await db.list_papers(sort_by="year", limit=200)

        if len(papers) < 5:
            return "Need at least 5 papers (ideally across multiple pillars) for gap detection."

        theoretical = [p for p in papers if p.math_framework]
        computational = [p for p in papers if p.methodology and any(
            kw in (p.methodology or "").lower()
            for kw in ["neural", "deep", "algorithm", "numerical", "simulation", "implementation"]
        )]

        lines = [
            "FUTURE RESEARCH GAP GENERATOR",
            f"Library: {len(papers)} papers | Theoretical: {len(theoretical)} | Computational: {len(computational)}",
            "",
        ]

        comp_limitations = []
        for p in computational:
            if p.limitations:
                cite = (p.authors[0].name.split()[-1] if p.authors else "?") + str(p.year or "")
                comp_limitations.append(f"[{cite}] {p.limitations}")

        math_frameworks = []
        for p in theoretical:
            cite = (p.authors[0].name.split()[-1] if p.authors else "?") + str(p.year or "")
            math_frameworks.append(f"[{cite}] {p.math_framework}")

        if comp_limitations:
            lines.append("-- COMPUTATIONAL LIMITATIONS --")
            for lim in comp_limitations[:15]:
                lines.append(f"  {lim}")
            lines.append("")

        if math_frameworks:
            lines.append("-- THEORETICAL FRAMEWORKS --")
            for fw in math_frameworks[:15]:
                lines.append(f"  {fw}")
            lines.append("")

        convergence_claims = []
        for p in papers:
            if p.convergence_bounds:
                cite = (p.authors[0].name.split()[-1] if p.authors else "?") + str(p.year or "")
                convergence_claims.append(f"[{cite}] {p.convergence_bounds}")

        if convergence_claims:
            lines.append("-- CONVERGENCE CLAIMS --")
            for claim in convergence_claims[:10]:
                lines.append(f"  {claim}")
            lines.append("")

        if not comp_limitations and not math_frameworks:
            return (
                f"Insufficient extraction data for gap detection ({len(papers)} papers in library).\n"
                f"Papers with limitations: {len(comp_limitations)} | With math framework: {len(math_frameworks)}\n\n"
                "Run extract_key_findings() and set_extraction() on more papers first."
            )

        lines += [
            "-" * 60,
            "[MANUAL MODE — this is cross-reference data for Claude to analyze.",
            " Set ANTHROPIC_API_KEY for future auto-generation.]",
            "",
            f"TASK: Generate {num_proposals} specific, technically viable open problems:",
            "  1. Mathematical proofs that EXIST in theory but haven't been CODED",
            "  2. Algorithms that WORK in practice but lack THEORETICAL justification",
            "  3. Convergence rates that could be IMPROVED with different assumptions",
            "  4. Methods from one pillar that could be APPLIED to another",
            "",
            "For each: title, which papers it bridges, why it's tractable, difficulty level.",
        ]

        return "\n".join(lines)

    @mcp.tool()
    async def standardize_notation(
        paper_id: str,
        glossary: Optional[str] = None,
    ) -> str:
        """Translate a paper's math notation into your standardized dissertation notation.

        Uses a master glossary to consistently rename variables across papers.
        If ANTHROPIC_API_KEY is set, auto-translates using the LLM.

        Args:
            paper_id: The paper's ID
            glossary: Master glossary (e.g. 'mu=measure, Z=hedging, Y=backward').
                      Stored in config after first use.
        """
        paper = await db.get_paper(paper_id)
        if not paper:
            return "Paper not found in library."

        if not glossary:
            glossary = await db.get_config("notation_glossary")

        if not glossary:
            return (
                "No master glossary configured. Set one:\n"
                "  standardize_notation(paper_id, glossary='mu=measure, Z=hedging, Y=backward')\n\n"
                "Common glossaries for mathematical finance:\n"
                "  mu=measure, Z=hedging portfolio, Y=backward process, X=forward,\n"
                "  sigma=volatility, f=driver, g=terminal condition, T=maturity"
            )

        await db.set_config("notation_glossary", glossary)

        text_parts = [f"Title: {paper.title}"]
        if paper.math_framework:
            text_parts.append(f"Math framework: {paper.math_framework}")
        if paper.abstract:
            text_parts.append(f"Abstract: {paper.abstract}")
        fulltext = await db.get_fulltext(paper_id)
        if fulltext:
            processed, _ = budget_text(fulltext, "assess_quality")
            text_parts.append(f"Text:\n{processed}")
        paper_text = "\n\n".join(text_parts)

        if llm_available():
            try:
                result = await extract(
                    paper_text, "notation_standardize",
                    extra_context=f"Master glossary: {glossary}\n\nTranslate this paper's notation to match.",
                )
                lines = [f"NOTATION STANDARDIZED: {paper.title}", f"[Model: {result.model_used}]", ""]
                for key, val in result.data.items():
                    lines.append(f"  {key}: {val}")
                return "\n".join(lines)
            except Exception as e:
                pass  # fall through

        lines = [
            f"NOTATION STANDARDIZATION: {paper.title}",
            f"Glossary: {glossary}",
            "",
        ]
        if paper.math_framework:
            lines.append(f"Current: {paper.math_framework}")
        lines += [
            "", "-" * 60,
            "TASK: Translate this paper's notation to match the glossary.",
            f"Then call: set_extraction('{paper_id}', math_framework='<translated>')",
        ]
        return "\n".join(lines)
