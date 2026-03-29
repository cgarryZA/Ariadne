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
    async def extract_structured_claims(paper_id: str) -> str:
        """Extract structured, falsifiable claims from a paper.

        Each claim is stored with: metric, value, dataset, conditions, direction,
        and claim type. This enables algorithmic contradiction detection —
        comparing specific numbers under specific conditions, not just vibes.

        Requires ANTHROPIC_API_KEY for auto-extraction. Without it, formats
        the paper for manual claim extraction.

        Args:
            paper_id: The paper's ID
        """
        paper = await db.get_paper(paper_id)
        if not paper:
            return f"Paper '{paper_id}' not found."

        existing = await db.get_claims(paper_id)
        if existing:
            lines = [f"Paper already has {len(existing)} structured claims:"]
            for c in existing:
                parts = [f"  {c['claim']}"]
                if c.get("metric"):
                    parts.append(f"    metric={c['metric']}, value={c.get('value', '?')}")
                if c.get("dataset"):
                    parts.append(f"    dataset={c['dataset']}")
                if c.get("conditions"):
                    parts.append(f"    conditions={c['conditions']}")
                lines.extend(parts)
            lines.append(f"\nTo re-extract, delete existing claims first.")
            return "\n".join(lines)

        # Build text
        text_parts = [f"Title: {paper.title}"]
        if paper.abstract:
            text_parts.append(f"Abstract: {paper.abstract}")
        if paper.key_findings:
            text_parts.append(f"Key findings: {'; '.join(paper.key_findings)}")
        if paper.methodology:
            text_parts.append(f"Methodology: {paper.methodology}")
        if paper.convergence_bounds:
            text_parts.append(f"Convergence: {paper.convergence_bounds}")
        if paper.limitations:
            text_parts.append(f"Limitations: {paper.limitations}")

        fulltext = await db.get_fulltext(paper_id)
        if fulltext:
            processed, _ = budget_text(fulltext, "extract_key_findings")
            text_parts.append(f"Text:\n{processed}")

        paper_text = "\n\n".join(text_parts)

        if llm_available():
            try:
                result = await extract(paper_text, "extract_claims")
                claims = result.data.get("claims", [])
                if claims:
                    stored = await db.store_claims(paper_id, claims)
                    lines = [
                        f"Extracted {stored} structured claims from '{paper.title}':",
                        "",
                    ]
                    for c in claims:
                        parts = [f"  [{c.get('claim_type', 'result')}] {c['claim']}"]
                        details = []
                        if c.get("metric"):
                            details.append(f"metric={c['metric']}")
                        if c.get("value"):
                            details.append(f"value={c['value']}")
                        if c.get("dataset"):
                            details.append(f"dataset={c['dataset']}")
                        if c.get("direction"):
                            details.append(f"direction={c['direction']}")
                        if details:
                            parts.append(f"    {', '.join(details)}")
                        if c.get("conditions"):
                            parts.append(f"    conditions: {c['conditions']}")
                        lines.extend(parts)
                    lines.append(f"\n[Model: {result.model_used}, confidence: {result.confidence_score}]")
                    return "\n".join(lines)
                return "No structured claims could be extracted. Paper may need more metadata."
            except Exception as e:
                pass  # fall through

        # Manual mode
        cite = (paper.authors[0].name.split()[-1] if paper.authors else "?") + str(paper.year or "")
        lines = [
            f"[MANUAL MODE] Extract structured claims from [{cite}] {paper.title}",
            "",
        ]
        for part in text_parts[:5]:
            lines.append(f"  {part[:200]}")
        lines += [
            "",
            "-" * 60,
            "For each claim, provide structured JSON then call store_claims():",
            '  {"claim": "Method X achieves 0.87 accuracy", "metric": "accuracy",',
            '   "value": "0.87", "dataset": "CIFAR-10", "conditions": "batch=128",',
            '   "direction": "X > baseline", "claim_type": "result"}',
        ]
        return "\n".join(lines)

    @mcp.tool()
    async def detect_contradictions(
        paper_ids: Optional[str] = None,
        pillar: Optional[str] = None,
        chapter: Optional[str] = None,
    ) -> str:
        """Detect contradictions across papers using structured claim comparison.

        Three-layer detection:
        1. Algorithmic: match claims by (metric, dataset) and check conflicting values/directions
        2. LLM-assisted: for claims that share a metric but differ in conditions, use LLM to assess
        3. Manual: format remaining claims for human review

        Run extract_structured_claims() on papers first for best results.
        Falls back to free-text comparison when no structured claims exist.

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

        paper_ids_set = {p.id for p in papers}
        paper_map = {p.id: p for p in papers}

        def _cite(p):
            return (p.authors[0].name.split()[-1] if p.authors else "?") + str(p.year or "")

        lines = [
            "CONTRADICTION & DISAGREEMENT ANALYSIS",
            f"Papers: {len(papers)}",
            "",
        ]

        # Collect all structured claims for these papers
        all_claims = []
        for p in papers:
            claims = await db.get_claims(p.id)
            for c in claims:
                c["_cite"] = _cite(p)
                c["_title"] = p.title
            all_claims.extend(claims)

        # === Layer 1: Algorithmic comparison on structured claims ===
        algorithmic_conflicts = []
        if len(all_claims) >= 2:
            # Group claims by (metric, dataset) for direct comparison
            claim_groups: dict[str, list] = {}
            for c in all_claims:
                if c.get("metric"):
                    key = (c["metric"].lower().strip(), (c.get("dataset") or "").lower().strip())
                    claim_groups.setdefault(key, []).append(c)

            for (metric, dataset), group in claim_groups.items():
                if len(group) < 2:
                    continue
                # Check for conflicting values/directions from different papers
                by_paper: dict[str, list] = {}
                for c in group:
                    by_paper.setdefault(c["paper_id"], []).append(c)

                if len(by_paper) < 2:
                    continue

                paper_list = list(by_paper.items())
                for i, (pid_a, claims_a) in enumerate(paper_list):
                    for pid_b, claims_b in paper_list[i + 1:]:
                        for ca in claims_a:
                            for cb in claims_b:
                                # Check direction conflict
                                dir_a = (ca.get("direction") or "").lower()
                                dir_b = (cb.get("direction") or "").lower()
                                val_a = ca.get("value")
                                val_b = cb.get("value")

                                is_conflict = False
                                reason = ""

                                if dir_a and dir_b and dir_a != dir_b:
                                    is_conflict = True
                                    reason = f"Opposite directions: '{dir_a}' vs '{dir_b}'"
                                elif val_a and val_b and val_a != val_b:
                                    # Different values — could be conflict or just different conditions
                                    is_conflict = True
                                    reason = f"Different values: {val_a} vs {val_b}"

                                if is_conflict:
                                    ds = f" on {dataset}" if dataset else ""
                                    algorithmic_conflicts.append(
                                        f"  [{ca['_cite']}] vs [{cb['_cite']}] — {metric}{ds}\n"
                                        f"    {ca['_cite']}: {ca['claim']}\n"
                                        f"    {cb['_cite']}: {cb['claim']}\n"
                                        f"    Conflict: {reason}"
                                    )

        if algorithmic_conflicts:
            lines.append(f"=== STRUCTURAL CONFLICTS ({len(algorithmic_conflicts)}) ===")
            lines.append("(Detected algorithmically from structured claims)")
            lines.append("")
            lines.extend(algorithmic_conflicts)
            lines.append("")

        # === Layer 2: LLM comparison for ambiguous cases ===
        llm_conflicts = []
        if llm_available() and len(all_claims) >= 4:
            # Find claim pairs that share a metric but we couldn't compare algorithmically
            import json as _json
            ungrouped_pairs = []
            by_metric: dict[str, list] = {}
            for c in all_claims:
                if c.get("metric"):
                    by_metric.setdefault(c["metric"].lower().strip(), []).append(c)

            for metric, group in by_metric.items():
                by_paper = {}
                for c in group:
                    by_paper.setdefault(c["paper_id"], []).append(c)
                if len(by_paper) >= 2:
                    pids = list(by_paper.keys())
                    for i in range(len(pids)):
                        for j in range(i + 1, len(pids)):
                            # Only send to LLM if not already caught algorithmically
                            ungrouped_pairs.append((pids[i], by_paper[pids[i]], pids[j], by_paper[pids[j]]))

            for pid_a, claims_a, pid_b, claims_b in ungrouped_pairs[:10]:
                pa = paper_map.get(pid_a)
                pb = paper_map.get(pid_b)
                if not pa or not pb:
                    continue
                text = (
                    f"Paper A [{_cite(pa)}]: {pa.title}\n"
                    f"Claims: {_json.dumps([{k: c[k] for k in ('claim','metric','value','dataset','conditions','direction') if c.get(k)} for c in claims_a])}\n\n"
                    f"Paper B [{_cite(pb)}]: {pb.title}\n"
                    f"Claims: {_json.dumps([{k: c[k] for k in ('claim','metric','value','dataset','conditions','direction') if c.get(k)} for c in claims_b])}"
                )
                try:
                    result = await extract(text, "compare_claims_structured")
                    conflicts = result.data.get("conflicts", [])
                    for conf in conflicts:
                        if conf.get("severity") in ("high", "medium"):
                            llm_conflicts.append(
                                f"  [{_cite(pa)}] vs [{_cite(pb)}] — {conf.get('type', '?')}\n"
                                f"    {conf.get('explanation', '')}"
                            )
                except Exception:
                    pass

        if llm_conflicts:
            lines.append(f"=== LLM-DETECTED CONFLICTS ({len(llm_conflicts)}) ===")
            lines.append("(Ambiguous cases assessed by reasoning model)")
            lines.append("")
            lines.extend(llm_conflicts)
            lines.append("")

        # === Layer 3: Summary + manual fallback ===
        total = len(algorithmic_conflicts) + len(llm_conflicts)
        if total > 0:
            lines.append(f"Total: {total} conflicts detected ({len(algorithmic_conflicts)} structural, {len(llm_conflicts)} LLM-assessed)")
        elif all_claims:
            lines.append("No contradictions detected in structured claims.")
            lines.append(f"({len(all_claims)} claims compared across {len(papers)} papers)")
        else:
            # No structured claims — fall back to free-text comparison
            lines.append("No structured claims found. Run extract_structured_claims() first for best results.")
            lines.append("")

            # Still provide what we can from free-text fields
            lines.append("[MANUAL MODE — free-text claims for comparison]")
            lines.append("-" * 60)
            for p in papers:
                cite = _cite(p)
                lines.append(f"\n[{cite}] {p.title}")
                if p.key_findings:
                    for f in p.key_findings:
                        lines.append(f"  - {f}")
                if p.methodology:
                    lines.append(f"  Method: {p.methodology}")
                if p.convergence_bounds:
                    lines.append(f"  Convergence: {p.convergence_bounds}")
                if not p.key_findings and not p.methodology:
                    lines.append("  [no data — run extract_key_findings first]")

            lines += [
                "",
                "-" * 60,
                "TASK: Compare claims and identify:",
                "  1. Direct result contradictions (same metric, different values)",
                "  2. Methodological disagreements (different approaches to same problem)",
                "  3. Assumption conflicts (incompatible preconditions)",
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
