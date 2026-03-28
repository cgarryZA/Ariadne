"""Oxford three-move classification tools."""

from __future__ import annotations

from typing import Optional

import db
from models import Move


def register(mcp):

    @mcp.tool()
    async def classify_moves(
        pillar: Optional[str] = None,
        chapter: Optional[str] = None,
    ) -> str:
        """Format papers for Oxford three-move classification.

        The Oxford model organises papers into:
        - FOUNDATIONAL: Established work, uncontroversial, high citations, older
        - GAP: Identifies problems, questions current knowledge, highlights limitations
        - PARALLEL: Recent attempts to address gaps, newer methodologies

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
            "  1. FOUNDATIONAL - Established facts, frameworks, widely-cited older work",
            "  2. GAP - Papers questioning current knowledge, identifying problems/limitations",
            "  3. PARALLEL - Recent research attempting to fill gaps, newer methodologies",
            "",
            "This ordering creates a narrative: established knowledge -> what's missing -> what's new.",
            "-" * 60,
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
            "-" * 60,
            "For each paper, assign: foundational | gap | parallel",
            "Then call set_move(paper_id, 'foundational') etc. for each.",
        ]

        return "\n".join(lines)

    @mcp.tool()
    async def set_move(paper_id: str, move: str) -> str:
        """Classify a paper into an Oxford three-move category.

        Args:
            paper_id: The paper's ID
            move: One of: foundational, gap, parallel
        """
        try:
            m = Move(move)
        except ValueError:
            return f"Invalid move. Choose from: {', '.join(m.value for m in Move)}"

        ok = await db.update_paper(paper_id, move=m)
        return f"Move set to '{move}'." if ok else "Paper not found."

    @mcp.tool()
    async def set_themes(paper_id: str, themes: str) -> str:
        """Assign thematic tags to a paper (separate from regular tags).

        Themes represent the conceptual strands running through your review.

        Args:
            paper_id: The paper's ID
            themes: Comma-separated theme names (e.g. 'BSDE solvers,convergence theory,neural networks')
        """
        parsed = [t.strip() for t in themes.split(",") if t.strip()]
        ok = await db.update_paper(paper_id, themes=parsed)
        return f"Themes set: {', '.join(parsed)}" if ok else "Paper not found."
