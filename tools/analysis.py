"""Analysis tools — statistics, gap identification, evidence synthesis, comparison, code alignment."""

from __future__ import annotations

from typing import Optional

import db
from tools.formatting import format_paper, validate_pillar, resolve_paper_id
from apis import github as gh


def register(mcp):

    @mcp.tool()
    async def compare_papers(paper_ids: str) -> str:
        """Compare multiple papers side by side on structured extraction fields.

        Args:
            paper_ids: Comma-separated paper IDs
        """
        ids = [pid.strip() for pid in paper_ids.split(",")]
        papers = []
        for pid in ids:
            p = await db.get_paper(pid)
            if p:
                papers.append(p)

        if not papers:
            return "No papers found."

        extraction_fields = await db.get_extraction_fields()
        field_labels = {
            "methodology": "Methodology",
            "limitations": "Limitations",
            "math_framework": "Math Framework",
            "convergence_bounds": "Convergence",
        }

        lines = []
        for p in papers:
            lines.append(f"### {p.title} ({p.year})")
            lines.append(f"- Pillar: {p.pillar or 'unassigned'}")
            for field in extraction_fields:
                val = getattr(p, field, None) or "not extracted"
                label = field_labels.get(field, field.replace("_", " ").title())
                lines.append(f"- {label}: {val}")
            lines.append(f"- Citations: {p.citation_count or 0}")
            lines.append("")

        return "\n".join(lines)

    @mcp.tool()
    async def find_bridges() -> str:
        """Find papers that cite across research pillars (cross-pillar bridge papers).

        Bridge papers are the connective tissue between fields.
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

        # Show configured pillars
        pillars = await db.get_pillars()
        if pillars:
            lines.append(f"\nConfigured pillars: {', '.join(pillars)}")
        else:
            lines.append("\nNo pillars configured yet. Run setup_review() to set up your review.")

        return "\n".join(lines)

    @mcp.tool()
    async def search_library_local(query: str) -> str:
        """Search your local library by title, abstract, notes, or author name.

        Uses full-text search (FTS5) when available for fast, ranked results.

        Args:
            query: Search text
        """
        papers = await db.search_library(query)
        if not papers:
            return "No papers in your library match that query."

        formatted = [await format_paper(p) for p in papers]
        return f"Found {len(papers)} matching papers:\n\n" + "\n\n---\n\n".join(formatted)

    @mcp.tool()
    async def identify_gaps(
        research_question: Optional[str] = None,
        pillar: Optional[str] = None,
        chapter: Optional[str] = None,
    ) -> str:
        """Format your library for research gap identification.

        Args:
            research_question: Focusing question for the gap analysis (optional — uses configured question if not provided)
            pillar: Limit to papers in this pillar
            chapter: Limit to papers in this chapter
        """
        pillar_err = await validate_pillar(pillar)
        if pillar_err:
            return pillar_err

        # Fall back to configured research question
        if not research_question:
            research_question = await db.get_config("research_question")

        papers = await db.list_papers(pillar=pillar, chapter=chapter, sort_by="year", limit=200)

        if not papers:
            scope = f" in pillar '{pillar}'" if pillar else (f" in chapter '{chapter}'" if chapter else "")
            return f"No papers found{scope}. Add papers first."

        lines = ["RESEARCH GAP ANALYSIS", ""]
        if research_question:
            lines += [f"Research Question: {research_question}", ""]

        lines += [
            f"Library scope: {len(papers)} papers"
            + (f" | Pillar: {pillar}" if pillar else "")
            + (f" | Chapter: {chapter}" if chapter else ""),
            "",
        ]

        by_pillar: dict[str, int] = {}
        by_year: dict[int, int] = {}
        methods: list[str] = []
        frameworks: list[str] = []
        missing_extraction = 0

        extraction_fields = await db.get_extraction_fields()

        for p in papers:
            pl = p.pillar or "unassigned"
            by_pillar[pl] = by_pillar.get(pl, 0) + 1
            if p.year:
                by_year[p.year] = by_year.get(p.year, 0) + 1
            if p.methodology:
                methods.append(f"  [{p.authors[0].name.split()[-1] if p.authors else '?'} {p.year}] {p.methodology}")
            if p.math_framework:
                frameworks.append(f"  [{p.authors[0].name.split()[-1] if p.authors else '?'} {p.year}] {p.math_framework}")
            if not any(getattr(p, f, None) for f in extraction_fields if hasattr(p, f)):
                missing_extraction += 1

        lines.append("-- COVERAGE SUMMARY --")
        lines.append("By pillar: " + ", ".join(f"{k}={v}" for k, v in by_pillar.items()))
        if by_year:
            y_min, y_max = min(by_year), max(by_year)
            lines.append(f"Year range: {y_min}-{y_max}")
            all_years = set(range(y_min, y_max + 1))
            covered = set(by_year.keys())
            gaps = sorted(all_years - covered)
            if gaps:
                lines.append(f"Year gaps: {gaps}")
        lines.append(f"Extraction completeness: {len(papers) - missing_extraction}/{len(papers)} papers have structured data")
        if missing_extraction > 0:
            lines.append(f"  -> Run bulk_extract() to fill in the {missing_extraction} missing papers")

        if methods:
            lines.append("\n-- METHODS CATALOGUE --")
            lines += methods

        if frameworks:
            lines.append("\n-- MATHEMATICAL FRAMEWORKS --")
            lines += frameworks

        lines.append("\n-- FULL PAPER LIST (for gap analysis) --")
        for p in papers:
            authors = ", ".join(a.name for a in p.authors[:2])
            lines.append(f"\n{p.title} ({p.year or '?'})")
            lines.append(f"  Authors: {authors}")
            lines.append(f"  Pillar: {p.pillar or 'unassigned'} | Citations: {p.citation_count or 0}")
            if p.tldr:
                lines.append(f"  TLDR: {p.tldr}")
            if p.methodology:
                lines.append(f"  Method: {p.methodology}")
            if p.limitations:
                lines.append(f"  Limitations: {p.limitations}")

        lines += [
            "",
            "-" * 60,
            "[MANUAL MODE — analyze the data above and respond below]",
            "",
            "TASK: Based on the above, identify:",
            "1. Methods used in one pillar but not applied to others",
            "2. Temporal gaps -- active periods followed by silence",
            "3. Contradictions between papers on the same question",
            "4. Settings/assumptions no paper has challenged",
            "5. Cross-pillar bridge opportunities",
        ]
        if research_question:
            lines.append(f"6. Specifically: what does the literature NOT yet answer about '{research_question}'?")

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

        Args:
            question: A focused yes/no or directional research question
            pillar: Limit to a research pillar
            tag: Limit to papers with this tag
            limit: Max papers to include (default 50)
        """
        pillar_err = await validate_pillar(pillar)
        if pillar_err:
            return pillar_err
        papers = await db.list_papers(pillar=pillar, tag=tag, sort_by="citation_count", limit=limit)

        if not papers:
            return "No papers in library to synthesise."

        lines = [
            "EVIDENCE SYNTHESIS TASK",
            f"Question: {question}",
            "",
            "For each paper, classify as one of:",
            "  SUPPORTS   -- evidence suggests the answer is yes / the claim holds",
            "  OPPOSES    -- evidence suggests no / the claim fails",
            "  MIXED      -- evidence is conditional or contradictory",
            "  IRRELEVANT -- paper does not address this question",
            "",
            "After classifying, synthesise:",
            '  "The balance of N papers [strongly supports / is mixed on / opposes] the claim..."',
            "-" * 60,
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
    async def generate_synthesis_matrix(
        paper_ids: Optional[str] = None,
        pillar: Optional[str] = None,
        chapter: Optional[str] = None,
        dimensions: Optional[str] = None,
    ) -> str:
        """Generate a structured synthesis matrix comparing papers across dimensions.

        Args:
            paper_ids: Comma-separated IDs (or use pillar/chapter to select a group)
            pillar: Select all papers in this pillar
            chapter: Select all papers in this chapter
            dimensions: Comma-separated fields to compare (default: configured extraction fields + key_findings)
        """
        pillar_err = await validate_pillar(pillar)
        if pillar_err:
            return pillar_err

        if paper_ids:
            ids = [pid.strip() for pid in paper_ids.split(",")]
            papers = [p for pid in ids if (p := await db.get_paper(pid))]
        else:
            papers = await db.list_papers(pillar=pillar, chapter=chapter, sort_by="year", limit=50)

        if not papers:
            return "No papers found."

        if dimensions:
            dims = [d.strip() for d in dimensions.split(",")]
        else:
            dims = (await db.get_extraction_fields()) + ["key_findings"]

        lines = [
            f"SYNTHESIS MATRIX - {len(papers)} papers x {len(dims)} dimensions",
            "-" * 60,
        ]

        for p in papers:
            cite = (p.authors[0].name.split()[-1] if p.authors else "?") + str(p.year or "")
            lines.append(f"\n[{cite}] {p.title}")
            for dim in dims:
                if dim == "key_findings":
                    val = "; ".join(p.key_findings) if p.key_findings else "-"
                else:
                    val = getattr(p, dim, None) or "-"
                lines.append(f"  {dim}: {val}")

        lines += [
            "",
            "-" * 60,
            "Use this matrix to identify:",
            "  - Common methodological approaches vs. outliers",
            "  - Contradictions between papers on the same question",
            "  - Dimensions where most cells are empty (under-explored areas)",
            "  - Patterns that suggest thematic groupings",
        ]

        return "\n".join(lines)

    @mcp.tool()
    async def github_reality_check(paper_id: str) -> str:
        """Cross-reference a paper with its linked GitHub repository.

        Finds GitHub URLs in the paper's text/abstract/notes, scrapes the
        repo, and extracts undocumented implementation tricks (batch norm,
        gradient clipping, hyperparameters) that were omitted from the paper
        but are required for convergence.

        Args:
            paper_id: The paper's ID
        """
        resolved_id, err = await resolve_paper_id(paper_id)
        if err:
            return err
        paper_id = resolved_id
        paper = await db.get_paper(paper_id)

        # Find GitHub URLs in all available text
        search_text = " ".join(filter(None, [
            paper.abstract, paper.notes, paper.url,
            await db.get_fulltext(paper_id),
        ]))

        repos = gh.extract_github_urls(search_text)

        if not repos:
            return (
                f"No GitHub repository found in '{paper.title}'.\n"
                "Check the paper's PDF or supplementary materials for a repo link,\n"
                "then call github_reality_check_url(paper_id, 'owner/repo')."
            )

        lines = [f"GITHUB REALITY CHECK: {paper.title}", ""]

        for repo in repos[:3]:  # limit to 3 repos
            analysis = await gh.analyze_repo(repo)

            if "error" in analysis:
                lines.append(f"[{repo}] {analysis['error']}")
                continue

            info = analysis["info"]
            lines.append(f"=== {info['full_name']} ===")
            lines.append(f"  {info['description'] or 'No description'}")
            lines.append(f"  Language: {info['language']} | Stars: {info['stars']} | Forks: {info['forks']}")
            lines.append(f"  URL: {info['url']}")
            lines.append("")

            tricks = analysis.get("undocumented_tricks", [])
            if tricks:
                lines.append("  UNDOCUMENTED IMPLEMENTATION TRICKS:")
                for trick in tricks:
                    lines.append(f"    * {trick}")
                lines.append("")

            main_files = analysis.get("main_files", [])
            if main_files:
                lines.append(f"  Key files: {', '.join(main_files[:8])}")
                lines.append("")

        if any(analysis.get("undocumented_tricks") for repo in repos[:3]
               if (analysis := {})):  # this was just for the conditional
            pass

        lines += [
            "-" * 60,
            "Compare these implementation details against the paper's methodology.",
            "Common gaps: hyperparameter tuning, normalization, gradient management.",
        ]

        return "\n".join(lines)

    @mcp.tool()
    async def github_reality_check_url(paper_id: str, repo_url: str) -> str:
        """Cross-reference a paper with a specific GitHub repository.

        Args:
            paper_id: The paper's ID
            repo_url: GitHub repo in 'owner/repo' format (e.g. 'pytorch/pytorch')
        """
        resolved_id, err = await resolve_paper_id(paper_id)
        if err:
            return err
        paper_id = resolved_id
        paper = await db.get_paper(paper_id)

        # Clean the repo URL
        repo = repo_url.replace("https://github.com/", "").strip("/")

        analysis = await gh.analyze_repo(repo)
        if "error" in analysis:
            return f"Error: {analysis['error']}"

        info = analysis["info"]
        lines = [
            f"GITHUB REALITY CHECK: {paper.title}",
            f"Repository: {info['full_name']}",
            f"  {info['description'] or 'No description'}",
            f"  Language: {info['language']} | Stars: {info['stars']}",
            "",
        ]

        tricks = analysis.get("undocumented_tricks", [])
        if tricks:
            lines.append("UNDOCUMENTED IMPLEMENTATION TRICKS:")
            for trick in tricks:
                lines.append(f"  * {trick}")
            lines.append("")

        # Show code summary
        snippets = analysis.get("code_snippets", {})
        if snippets:
            lines.append(f"Analyzed {len(snippets)} files: {', '.join(snippets.keys())}")

        # Paper claims vs code reality
        lines += [
            "",
            "-" * 60,
            "TASK: Compare these implementation details against the paper's claims:",
        ]
        if paper.methodology:
            lines.append(f"  Paper methodology: {paper.methodology}")
        if paper.convergence_bounds:
            lines.append(f"  Paper convergence: {paper.convergence_bounds}")

        lines += [
            "",
            "Flag any tricks found in code but absent from the paper.",
            "These are potential reproducibility gaps.",
        ]

        return "\n".join(lines)
