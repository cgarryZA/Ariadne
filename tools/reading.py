"""Reading and paper analysis tools — summarize, extract findings, assess quality, download PDF."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import db
from tools._constants import PAPERS_DIR


def register(mcp):

    @mcp.tool()
    async def summarize_paper(paper_id: str) -> str:
        """Return a paper's full content for comprehensive summarisation.

        Args:
            paper_id: The paper's ID
        """
        paper = await db.get_paper(paper_id)
        if not paper:
            return "Paper not found in library."

        fulltext = await db.get_fulltext(paper_id)

        authors = ", ".join(a.name for a in paper.authors[:4])
        if len(paper.authors) > 4:
            authors += " et al."

        lines = [
            "SUMMARISATION TASK",
            f"Title: {paper.title}",
            f"Authors: {authors} ({paper.year or '?'})",
            f"Venue: {paper.venue or 'Unknown'}",
            f"Citations: {paper.citation_count or 0}",
            "",
        ]

        if paper.summary:
            lines += [f"[Existing summary]: {paper.summary}", ""]
        if paper.tldr:
            lines += [f"S2 TLDR: {paper.tldr}", ""]
        if paper.abstract:
            lines += ["ABSTRACT:", paper.abstract, ""]
        if fulltext:
            lines += [
                "FULL TEXT (excerpt):",
                fulltext[:3000] + ("..." if len(fulltext) > 3000 else ""),
                "",
            ]
        if paper.notes:
            lines += [f"Your notes: {paper.notes[:500]}", ""]

        lines += [
            "-" * 60,
            "Write a comprehensive 150-300 word summary covering:",
            "  1. Research question / objective",
            "  2. Methodology and approach",
            "  3. Key results and contributions",
            "  4. Significance to the field",
            "",
            f"Then call: store_summary('{paper_id}', '<your summary>')",
        ]

        return "\n".join(lines)

    @mcp.tool()
    async def store_summary(paper_id: str, summary: str) -> str:
        """Store a Claude-generated comprehensive summary for a paper.

        Args:
            paper_id: The paper's ID
            summary: The comprehensive summary text
        """
        ok = await db.update_paper(paper_id, summary=summary)
        return "Summary stored." if ok else "Paper not found."

    @mcp.tool()
    async def extract_key_findings(paper_id: str) -> str:
        """Return a paper's content for key-findings extraction.

        Args:
            paper_id: The paper's ID
        """
        paper = await db.get_paper(paper_id)
        if not paper:
            return "Paper not found in library."

        fulltext = await db.get_fulltext(paper_id)
        authors = ", ".join(a.name for a in paper.authors[:3])

        lines = [
            "KEY FINDINGS EXTRACTION",
            f"Title: {paper.title}",
            f"Authors: {authors} ({paper.year or '?'})",
            "",
        ]

        if paper.abstract:
            lines += ["Abstract:", paper.abstract, ""]
        if paper.summary:
            lines += ["Summary:", paper.summary, ""]
        if fulltext:
            lines += ["Full text (excerpt):", fulltext[:2000] + "...", ""]
        if paper.methodology:
            lines += [f"Methodology: {paper.methodology}"]
        if paper.convergence_bounds:
            lines += [f"Convergence bounds: {paper.convergence_bounds}"]

        if paper.key_findings:
            lines += ["", "Existing findings:", ""]
            for i, f in enumerate(paper.key_findings, 1):
                lines.append(f"  {i}. {f}")

        lines += [
            "",
            "-" * 60,
            "Extract 3-7 key findings as a pipe-separated (|) list of concise statements.",
            "Focus on: novel contributions, quantitative results, theoretical insights.",
            "",
            f"Then call: store_key_findings('{paper_id}', 'finding 1 | finding 2 | ...')",
        ]

        return "\n".join(lines)

    @mcp.tool()
    async def store_key_findings(paper_id: str, findings: str) -> str:
        """Store key findings for a paper.

        Args:
            paper_id: The paper's ID
            findings: Pipe-separated (|) key findings. Commas are also accepted as
                      separators if no pipes are present.
        """
        # Prefer pipe delimiter (findings often contain commas)
        if "|" in findings:
            parsed = [f.strip() for f in findings.split("|") if f.strip()]
        else:
            parsed = [f.strip() for f in findings.split(",") if f.strip()]
        ok = await db.update_paper(paper_id, key_findings=parsed)
        return f"Stored {len(parsed)} key findings." if ok else "Paper not found."

    @mcp.tool()
    async def assess_quality(paper_id: str) -> str:
        """Return a paper's metadata for quality and rigor assessment.

        Args:
            paper_id: The paper's ID
        """
        paper = await db.get_paper(paper_id)
        if not paper:
            return "Paper not found in library."

        authors = ", ".join(a.name for a in paper.authors[:4])

        lines = [
            "QUALITY ASSESSMENT",
            f"Title: {paper.title}",
            f"Authors: {authors} ({paper.year or '?'})",
            f"Venue: {paper.venue or 'Unknown venue'}",
            f"Citation count: {paper.citation_count or 0}",
            f"Is open access: {'Yes' if paper.pdf_url else 'Unknown'}",
            "",
        ]

        if paper.abstract:
            lines += ["Abstract:", paper.abstract[:500], ""]
        if paper.methodology:
            lines += [f"Methodology: {paper.methodology}"]
        if paper.limitations:
            lines += [f"Known limitations: {paper.limitations}"]
        if paper.math_framework:
            lines += [f"Math framework: {paper.math_framework}"]

        if paper.quality_score:
            lines += [f"\n[Existing assessment]: {paper.quality_score}/5 - {paper.quality_notes}"]

        lines += [
            "",
            "-" * 60,
            "Rate this paper 1-5 on overall quality/rigor:",
            "  5 = Landmark paper, rigorous methodology, highly reproducible",
            "  4 = Strong contribution, sound methodology, minor gaps",
            "  3 = Solid work, standard methodology, some limitations",
            "  2 = Weak methodology or limited evidence, significant gaps",
            "  1 = Poor quality, unreliable, or methodologically flawed",
            "",
            f"Then call: store_quality('{paper_id}', <score>, '<brief justification>')",
        ]

        return "\n".join(lines)

    @mcp.tool()
    async def store_quality(paper_id: str, score: int, notes: str) -> str:
        """Store a quality assessment score and justification.

        Args:
            paper_id: The paper's ID
            score: Quality score 1-5
            notes: Brief justification for the score
        """
        if score < 1 or score > 5:
            return "Score must be 1-5."
        ok = await db.update_paper(paper_id, quality_score=score, quality_notes=notes)
        return f"Quality assessment stored: {score}/5." if ok else "Paper not found."

    @mcp.tool()
    async def download_pdf(paper_id: str) -> str:
        """Download a paper's open-access PDF and store it locally.

        Uses the pdf_url stored in the library. Only works for open-access papers.
        Optionally extracts full text if pdfplumber is installed.

        Args:
            paper_id: The paper's ID
        """
        paper = await db.get_paper(paper_id)
        if not paper:
            return "Paper not found in library."
        if not paper.pdf_url:
            return f"No PDF URL stored for '{paper.title}'. Check if it's open access."

        PAPERS_DIR.mkdir(parents=True, exist_ok=True)
        safe_name = "".join(c if c.isalnum() or c in "._-" else "_" for c in paper_id)
        pdf_path = PAPERS_DIR / f"{safe_name}.pdf"

        import httpx
        try:
            async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
                resp = await client.get(paper.pdf_url)
                resp.raise_for_status()
                pdf_path.write_bytes(resp.content)
        except Exception as e:
            return f"Download failed: {e}"

        await db.update_paper(paper_id, pdf_local_path=str(pdf_path))

        text_result = ""
        try:
            import pdfplumber
            with pdfplumber.open(pdf_path) as pdf:
                text = "\n\n".join(
                    page.extract_text() or "" for page in pdf.pages
                ).strip()
            if text:
                await db.store_fulltext(paper_id, text)
                text_result = f"\nFull text extracted: {len(text):,} characters stored."
        except ImportError:
            text_result = "\n(Install pdfplumber for automatic text extraction: pip install pdfplumber)"
        except Exception as e:
            text_result = f"\nText extraction failed: {e}"

        return (
            f"Downloaded: {paper.title}\n"
            f"Saved to: {pdf_path}\n"
            f"Size: {pdf_path.stat().st_size / 1024:.1f} KB"
            + text_result
        )
