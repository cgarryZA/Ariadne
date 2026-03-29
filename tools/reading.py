"""Reading and paper analysis tools — summarize, extract findings, assess quality, download PDF.

When ANTHROPIC_API_KEY is set, summarize_paper and extract_key_findings can use
the internal LLM client (Phase 0) to process papers with a cheap model (Haiku),
returning finished results instead of raw prompts.  This saves expensive
conversation tokens because Claude never sees the full paper text.

Without the key, tools behave exactly as before — returning formatted prompts
for Claude to process in the conversation.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import db
from tools._constants import PAPERS_DIR
from tools._llm_client import extract, is_available as llm_available
from tools._text_processing import budget_text
from tools.formatting import resolve_paper_id


def register(mcp):

    async def _resolve(paper_id: str):
        """Resolve paper_id with fuzzy matching. Returns (Paper, error_msg).
        The returned Paper's .id is the canonical resolved ID."""
        resolved_id, err = await resolve_paper_id(paper_id)
        if err:
            return None, err
        return await db.get_paper(resolved_id), None

    @mcp.tool()
    async def summarize_paper(paper_id: str, auto: bool = True) -> str:
        """Summarize a paper. If ANTHROPIC_API_KEY is set, auto-generates the summary
        using a cheap model and stores it. Otherwise returns paper content for you
        to summarize manually.

        Args:
            paper_id: The paper's ID
            auto: If True and LLM is available, auto-generate + store the summary
        """
        paper, err = await _resolve(paper_id)
        if err:
            return err
        paper_id = paper.id

        fulltext = await db.get_fulltext(paper_id)

        # Build text for summarization
        text_parts = [f"Title: {paper.title}"]
        if paper.abstract:
            text_parts.append(f"Abstract: {paper.abstract}")
        if fulltext:
            processed, _ = budget_text(fulltext, "summarize_paper")
            text_parts.append(f"Text:\n{processed}")
        elif paper.tldr:
            text_parts.append(f"TLDR: {paper.tldr}")
        paper_text = "\n\n".join(text_parts)

        # Auto mode: use internal LLM if available
        if auto and llm_available() and not paper.summary:
            try:
                result = await extract(paper_text, "summarize")
                summary = result.data.get("summary", "")
                if summary:
                    await db.update_paper(paper_id, summary=summary)
                    return (
                        f"Summary auto-generated for '{paper.title}':\n\n{summary}\n\n"
                        f"[Model: {result.model_used}, "
                        f"confidence: {result.confidence_score}, "
                        f"tokens: {result.input_tokens}+{result.output_tokens}]"
                    )
            except Exception as e:
                pass  # Fall through to manual mode

        # Manual mode — formatted prompt for Claude
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
            processed, stats = budget_text(fulltext, "summarize_paper")
            note = ""
            if stats["sections_stripped"] or stats["truncated"]:
                note = (
                    f" [noise stripped, {stats['savings_pct']}% token reduction: "
                    f"{stats['original_tokens']:,} → {stats['processed_tokens']:,} tokens]"
                )
            lines += [f"FULL TEXT{note}:", processed, ""]
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
    async def extract_key_findings(paper_id: str, auto: bool = True) -> str:
        """Extract key findings from a paper. If ANTHROPIC_API_KEY is set,
        auto-extracts using a cheap model and stores them. Otherwise returns
        paper content for manual extraction.

        Args:
            paper_id: The paper's ID
            auto: If True and LLM is available, auto-extract + store findings
        """
        paper, err = await _resolve(paper_id)
        if err:
            return err
        paper_id = paper.id

        fulltext = await db.get_fulltext(paper_id)

        # Build text
        text_parts = [f"Title: {paper.title}"]
        if paper.abstract:
            text_parts.append(f"Abstract: {paper.abstract}")
        if paper.summary:
            text_parts.append(f"Summary: {paper.summary}")
        if fulltext:
            processed, _ = budget_text(fulltext, "extract_key_findings")
            text_parts.append(f"Text:\n{processed}")
        if paper.methodology:
            text_parts.append(f"Methodology: {paper.methodology}")
        paper_text = "\n\n".join(text_parts)

        # Auto mode
        if auto and llm_available() and not paper.key_findings:
            try:
                result = await extract(paper_text, "extract_findings")
                findings = result.data.get("findings", [])
                if findings:
                    await db.update_paper(paper_id, key_findings=findings)
                    numbered = "\n".join(f"  {i}. {f}" for i, f in enumerate(findings, 1))
                    return (
                        f"Key findings auto-extracted for '{paper.title}':\n\n{numbered}\n\n"
                        f"[Model: {result.model_used}, "
                        f"confidence: {result.confidence_score}, "
                        f"tokens: {result.input_tokens}+{result.output_tokens}]"
                    )
            except Exception:
                pass  # Fall through to manual mode

        # Manual mode
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
            processed, stats = budget_text(fulltext, "extract_key_findings")
            note = ""
            if stats["sections_stripped"] or stats["truncated"]:
                note = (
                    f" [noise stripped, {stats['savings_pct']}% token reduction: "
                    f"{stats['original_tokens']:,} → {stats['processed_tokens']:,} tokens]"
                )
            lines += [f"Full text{note}:", processed, ""]
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
    async def red_team_assess(paper_id: str) -> str:
        """Multi-agent quality assessment — eliminates LLM confirmation bias.

        Spawns two LLM "agents" on the same paper:
        - Agent 1 (Proponent): argues the methodology is sound
        - Agent 2 (Reviewer 2): actively finds holes in the math and methods

        Their debate is synthesized into a balanced quality score + limitations
        paragraph. Requires ANTHROPIC_API_KEY.

        Falls back to standard assess_quality if LLM is not available.

        Args:
            paper_id: The paper's ID
        """
        paper, err = await _resolve(paper_id)
        if err:
            return err
        paper_id = paper.id

        if not llm_available():
            # Auto-fallback to standard assess_quality
            return await assess_quality(paper_id)

        # Build paper text
        fulltext = await db.get_fulltext(paper_id)
        text_parts = [f"Title: {paper.title}"]
        if paper.abstract:
            text_parts.append(f"Abstract: {paper.abstract}")
        if paper.methodology:
            text_parts.append(f"Methodology: {paper.methodology}")
        if fulltext:
            processed, _ = budget_text(fulltext, "assess_quality")
            text_parts.append(f"Text:\n{processed}")
        paper_text = "\n\n".join(text_parts)

        lines = [
            f"RED TEAM ASSESSMENT: {paper.title}",
            "",
        ]

        # Agent 1: The Proponent
        try:
            proponent = await extract(paper_text, "red_team_proponent", skip_cache=True)
            strengths = proponent.data.get("strengths", [])
            defense = proponent.data.get("methodology_defense", "")
            significance = proponent.data.get("significance", "")

            lines.append("=== AGENT 1 (PROPONENT) ===")
            if strengths:
                for s in strengths:
                    lines.append(f"  + {s}")
            if defense:
                lines.append(f"  Methodology defense: {defense}")
            if significance:
                lines.append(f"  Significance: {significance}")
            lines.append(f"  [Model: {proponent.model_used}]")
            lines.append("")
        except Exception as e:
            lines.append(f"Proponent failed: {e}")
            lines.append("")
            proponent = None

        # Agent 2: Reviewer 2 (the critic)
        try:
            critic = await extract(paper_text, "red_team_critic", skip_cache=True)
            weaknesses = critic.data.get("weaknesses", [])
            holes = critic.data.get("methodology_holes", "")
            missing = critic.data.get("missing_evidence", "")
            assumptions = critic.data.get("assumptions_questioned", [])

            lines.append("=== AGENT 2 (REVIEWER 2) ===")
            if weaknesses:
                for w in weaknesses:
                    lines.append(f"  - {w}")
            if holes:
                lines.append(f"  Methodology holes: {holes}")
            if missing:
                lines.append(f"  Missing evidence: {missing}")
            if assumptions:
                lines.append(f"  Assumptions questioned: {'; '.join(assumptions)}")
            lines.append(f"  [Model: {critic.model_used}]")
            lines.append("")
        except Exception as e:
            lines.append(f"Critic failed: {e}")
            lines.append("")
            critic = None

        # Synthesis: combine both perspectives
        if proponent and critic:
            synthesis_text = (
                f"Proponent's defense:\n{json.dumps(proponent.data)}\n\n"
                f"Critic's attack:\n{json.dumps(critic.data)}"
            )
            try:
                synth = await extract(
                    synthesis_text, "red_team_synthesize",
                    extra_context=f"Paper: {paper.title}",
                    skip_cache=True,
                )
                score = synth.data.get("score", 3)
                assessment = synth.data.get("balanced_assessment", "")
                limitations = synth.data.get("limitations_paragraph", "")

                lines.append("=== SYNTHESIS ===")
                lines.append(f"  Quality score: {score}/5")
                if assessment:
                    lines.append(f"  Assessment: {assessment}")
                if limitations:
                    lines.append(f"  Limitations: {limitations}")

                # Auto-store the result
                await db.update_paper(
                    paper_id,
                    quality_score=score,
                    quality_notes=f"[Red-team] {assessment[:200]}" if assessment else None,
                    limitations=limitations[:500] if limitations else paper.limitations,
                )
                lines.append(f"\n  Score and assessment auto-stored.")
            except Exception as e:
                lines.append(f"Synthesis failed: {e}")
                lines.append("Use the proponent/critic outputs above to make your own judgment.")

        return "\n".join(lines)

    @mcp.tool()
    async def assess_quality(paper_id: str) -> str:
        """Return a paper's metadata for quality and rigor assessment.

        Args:
            paper_id: The paper's ID
        """
        paper, err = await _resolve(paper_id)
        if err:
            return err
        paper_id = paper.id

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
        """Download a paper's open-access PDF and extract text.

        Uses the best available extraction method:
        1. Nougat (local, LaTeX-native — requires nougat-ocr + torch)
        2. Mathpix (API, LaTeX-native — requires MATHPIX_APP_ID + MATHPIX_APP_KEY)
        3. pdfplumber (plaintext fallback — requires pdfplumber)

        Math-aware methods (Nougat/Mathpix) also extract structured math:
        equations, theorems, lemmas, definitions, assumptions.

        Args:
            paper_id: The paper's ID
        """
        paper, err = await _resolve(paper_id)
        if err:
            return err
        paper_id = paper.id  # use resolved ID for all downstream calls
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

        # Extract text using best available method (Phase 2.1)
        from apis.math_ocr import extract_pdf
        text, method, math_structures = await extract_pdf(pdf_path)

        text_result = ""
        if text:
            from tools._text_processing import strip_noise_sections, count_tokens
            clean = strip_noise_sections(text)
            await db.store_fulltext(paper_id, clean)
            saved = round(100 * (1 - len(clean) / max(len(text), 1)))
            text_result = (
                f"\nText extracted via {method}: {len(clean):,} chars "
                f"({count_tokens(clean):,} tokens) stored"
                + (f" — {saved}% noise stripped" if saved > 2 else "") + "."
            )

            # Store structured math if extracted
            if math_structures:
                await db.update_paper(paper_id, math_framework=json.dumps(math_structures))
                counts = {k: len(v) for k, v in math_structures.items()}
                text_result += f"\nMath structures: {counts}"

            # Index into vector store for persistent semantic search (Phase 2.3b)
            from tools._vectorstore import is_available as vs_available, index_paper
            if vs_available():
                n = await index_paper(paper_id, paper.title, paper.abstract, clean)
                text_result += f"\nVector store: {n} chunks indexed."
        else:
            text_result = (
                "\nNo text extraction available. Install one of:"
                "\n  pip install pdfplumber         (basic plaintext)"
                "\n  pip install nougat-ocr torch   (LaTeX-native, math-aware)"
                "\n  Set MATHPIX_APP_ID/KEY         (LaTeX via Mathpix API)"
            )

        return (
            f"Downloaded: {paper.title}\n"
            f"Saved to: {pdf_path}\n"
            f"Size: {pdf_path.stat().st_size / 1024:.1f} KB"
            + text_result
        )
