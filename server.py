#!/usr/bin/env python3
"""
Ariadne — Academic Literature Review MCP Server

Provides tools for searching, managing, and analysing academic papers
via Semantic Scholar, OpenAlex, and arXiv. Designed to be used from
Claude Code or any MCP-compatible client.

Run directly:  python server.py
Or via MCP:    configure in your Claude Code .mcp.json (see mcp.json.example)
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from fastmcp import FastMCP

# Ensure local modules are importable regardless of working directory
sys.path.insert(0, str(Path(__file__).parent))

import db
from tools import register_all

mcp = FastMCP(
    "ariadne",
    instructions=(
        "Ariadne is a local literature review system backed by Semantic Scholar, "
        "OpenAlex, and arXiv. Use it to search for papers, manage a personal library, "
        "map citation networks, extract structured information, and draft literature reviews.\n\n"
        "First-time users: call setup_review() to configure your research domain "
        "(pillars, extraction fields, research question). Or just start searching — "
        "you can configure later and use auto_detect_pillars() once you have ~10 papers.\n\n"
        "For a full guided review, use the quick-review, standard-review, or deep-review prompts."
    ),
)

# Register all tool modules
register_all(mcp)


# ── MCP Resources ────────────────────────────────────────────────────

@mcp.resource("ariadne://config")
async def resource_config() -> str:
    """Current review configuration (pillars, extraction fields, research question)."""
    from tools.setup import get_review_config_internal
    return await get_review_config_internal()


@mcp.resource("ariadne://stats")
async def resource_stats() -> str:
    """Library statistics summary."""
    stats = await db.library_stats()
    lines = [f"Total papers: {stats['total']}"]
    for k, v in stats["by_status"].items():
        lines.append(f"  {k}: {v}")
    for k, v in stats["by_pillar"].items():
        lines.append(f"  {k}: {v}")
    return "\n".join(lines)


# ── Pipeline Prompts ─────────────────────────────────────────────────
# These are deterministic, inspectable review pipelines. Each one fixes
# tool order, parameters, and logging. Claude follows the checklist.

@mcp.prompt()
def start_review() -> str:
    """Guided walkthrough for starting a new literature review from scratch."""
    return (
        "I'd like to start a new literature review. Please guide me through:\n\n"
        "1. First, call setup_review() to configure my research domain\n"
        "2. Then call generate_search_strategy() to plan systematic searches\n"
        "3. Execute the searches with multi_search() and add papers with batch_add()\n"
        "4. Build citation networks with build_citation_network()\n"
        "5. Screen papers with screen_papers()\n"
        "6. Extract structured data with bulk_extract()\n"
        "7. Classify using classify_moves() for the Oxford three-move model\n"
        "8. Generate an outline with generate_review_outline()\n"
        "9. Draft the review with assemble_review()\n"
        "10. Export bibliography with export_bibtex()\n\n"
        "Let's start with step 1 — ask me about my research question and domain."
    )


@mcp.prompt()
def quick_review() -> str:
    """Quick literature review — 15-30 papers, key papers only, ~30 min."""
    return (
        "Run a QUICK literature review. Follow this checklist exactly, logging each step:\n\n"
        "1. Call log_pipeline_start('quick', '<research question from user>')\n"
        "2. Call setup_review() — ask user for research question, suggest 2-3 pillars\n"
        "3. Call multi_search(question, limit=30) — single broad query\n"
        "4. Call batch_add() on the top 15-20 results by citation count\n"
        "5. Call deduplicate_library()\n"
        "6. Call screen_papers() — apply basic relevance criteria\n"
        "7. For each included paper: call summarize_paper() and extract_key_findings()\n"
        "8. Call classify_moves() — assign foundational/gap/parallel\n"
        "9. Call identify_gaps() — check what's missing\n"
        "10. Call generate_review_outline(style='parallel')\n"
        "11. Call assemble_review() — draft the review\n"
        "12. Call export_bibtex()\n"
        "13. Call log_pipeline_complete() with paper count and outcome summary\n\n"
        "Target: 15-30 papers, overview-level depth.\n"
        "Start by asking: What is your research question?"
    )


@mcp.prompt()
def standard_review() -> str:
    """Standard systematic review — 30-80 papers, structured extraction, ~2 hrs."""
    return (
        "Run a STANDARD systematic literature review. Follow this checklist exactly:\n\n"
        "1. Call log_pipeline_start('standard', '<research question>')\n"
        "2. Call setup_review() — research question, 3-4 pillars, extraction fields\n"
        "3. Call generate_search_strategy(question, num_themes=3)\n"
        "4. For each theme: call multi_search() with theme-specific queries\n"
        "5. Call batch_add() on all relevant results (aim for 60-100 candidates)\n"
        "6. For 3-4 key papers: call build_citation_network(depth=1)\n"
        "7. Call deduplicate_library()\n"
        "8. Call screen_papers(include_criteria, exclude_criteria)\n"
        "9. Call generate_prisma_report()\n"
        "10. Call bulk_extract() on all included papers\n"
        "11. For each paper: call extract_structured_claims()\n"
        "12. Call classify_moves()\n"
        "13. Call extract_concepts() on the 10 most-cited papers\n"
        "14. Call detect_contradictions()\n"
        "15. Call auto_synthesize()\n"
        "16. Call identify_gaps()\n"
        "17. Call suggest_new_queries() — fill any blind spots, repeat 4-7 if needed\n"
        "18. Call generate_review_outline(style='mixed')\n"
        "19. Call assemble_review()\n"
        "20. Call export_bibtex() + compile_to_latex()\n"
        "21. Call log_pipeline_complete() with full summary\n\n"
        "Target: 30-80 papers, structured extraction, contradiction analysis.\n"
        "Start by asking: What is your research question?"
    )


@mcp.prompt()
def deep_review() -> str:
    """Deep systematic review — 80-150+ papers, full analysis pipeline, ~4+ hrs."""
    return (
        "Run a DEEP systematic literature review. Follow this checklist exactly:\n\n"
        "1. Call log_pipeline_start('deep', '<research question>')\n"
        "2. Call setup_review() — research question, 4-5 pillars, custom extraction fields\n"
        "3. Call generate_search_strategy(question, num_themes=5)\n"
        "4. For each theme: call multi_search() across all sources\n"
        "5. Call batch_add() on all results (aim for 150+ candidates)\n"
        "6. For 5-8 seed papers: call build_citation_network(depth=2, direction='both')\n"
        "7. Call seed_library() for 3-5 key authors\n"
        "8. Call deduplicate_library()\n"
        "9. Call screen_papers() with strict criteria, tag screened-in/out\n"
        "10. Call generate_prisma_report()\n"
        "11. For each included paper with PDF: call download_pdf()\n"
        "12. Call bulk_extract() + extract_structured_claims() on all included\n"
        "13. Call classify_moves() per pillar\n"
        "14. Call extract_concepts() on all included papers\n"
        "15. For 5-10 key papers: call build_theorem_graph()\n"
        "16. Call detect_contradictions() per pillar\n"
        "17. Call auto_synthesize() per pillar\n"
        "18. For the 5 most controversial papers: call red_team_assess()\n"
        "19. For papers with GitHub links: call github_reality_check()\n"
        "20. Call map_author_network() on 2-3 key researchers\n"
        "21. Call identify_gaps()\n"
        "22. Call generate_future_research_gaps()\n"
        "23. Call suggest_new_queries() — iterate if gaps found\n"
        "24. Call refine_research_question() — verify scope is right\n"
        "25. Call generate_review_outline(style='mixed')\n"
        "26. For each section: call draft_section() with appropriate style\n"
        "27. Call assemble_review()\n"
        "28. Call export_bibtex() + compile_to_latex()\n"
        "29. Call log_pipeline_complete() with full summary\n\n"
        "Target: 80-150+ papers, full extraction + concept graph + contradiction analysis.\n"
        "Start by asking: What is your research question?"
    )


# ── Pipeline Logging Tools ───────────────────────────────────────────

@mcp.tool()
async def log_pipeline_start(run_type: str, research_question: str) -> str:
    """Start logging a pipeline run. Call at the beginning of any review pipeline.

    Args:
        run_type: One of 'quick', 'standard', 'deep', or any custom name
        research_question: The research question driving this review
    """
    run_id = await db.create_pipeline_run(run_type, research_question)
    return f"Pipeline run #{run_id} started (type: {run_type}). Log steps with log_pipeline_step()."


@mcp.tool()
async def log_pipeline_step(run_id: int, step_name: str, result_json: str = "{}") -> str:
    """Log a completed step in the current pipeline run.

    Args:
        run_id: The pipeline run ID from log_pipeline_start
        step_name: Name of the step (e.g. 'multi_search', 'screen_papers')
        result_json: JSON string with step results (e.g. '{"papers_found": 42}')
    """
    try:
        result = json.loads(result_json)
    except json.JSONDecodeError:
        result = {"raw": result_json}

    await db.log_pipeline_step(run_id, step_name, result)
    return f"Step '{step_name}' logged for run #{run_id}."


@mcp.tool()
async def log_pipeline_complete(run_id: int, summary_json: str = "{}") -> str:
    """Mark a pipeline run as completed and store the final summary.

    Args:
        run_id: The pipeline run ID
        summary_json: JSON summary (e.g. '{"papers_reviewed": 42, "contradictions": 3}')
    """
    try:
        summary = json.loads(summary_json)
    except json.JSONDecodeError:
        summary = {"raw": summary_json}

    await db.complete_pipeline_run(run_id, summary)
    return f"Pipeline run #{run_id} completed."


@mcp.tool()
async def explain_pipeline_run(run_id: int) -> str:
    """Show what happened during a pipeline run — every step, what was filtered, where uncertainty is highest.

    Args:
        run_id: The pipeline run ID (from log_pipeline_start)
    """
    run = await db.get_pipeline_run(run_id)
    if not run:
        runs = await db.list_pipeline_runs()
        if runs:
            lines = ["Run not found. Recent runs:"]
            for r in runs:
                lines.append(f"  #{r['id']} ({r['run_type']}) — {r['status']} — {r['started_at']}")
            return "\n".join(lines)
        return "No pipeline runs found. Start one with log_pipeline_start()."

    lines = [
        f"PIPELINE RUN #{run['id']}",
        f"Type: {run['run_type']}",
        f"Question: {run['research_question'] or '(not set)'}",
        f"Status: {run['status']}",
        f"Started: {run['started_at']}",
        f"Completed: {run['completed_at'] or 'in progress'}",
        "",
        f"Steps ({len(run['steps'])}):",
    ]

    for step in run["steps"]:
        ts = step.get("timestamp", "?")
        name = step.get("step", "?")
        # Show key metrics from each step
        detail_parts = []
        for k, v in step.items():
            if k not in ("step", "timestamp") and v is not None:
                detail_parts.append(f"{k}={v}")
        detail = ", ".join(detail_parts[:5]) if detail_parts else ""
        lines.append(f"  [{ts}] {name}" + (f" — {detail}" if detail else ""))

    if run["summary"]:
        lines.append("")
        lines.append("Summary:")
        for k, v in run["summary"].items():
            lines.append(f"  {k}: {v}")

    return "\n".join(lines)


@mcp.tool()
async def list_pipeline_runs() -> str:
    """List all pipeline runs with their status and timestamps."""
    runs = await db.list_pipeline_runs()
    if not runs:
        return "No pipeline runs yet. Use a review prompt (quick-review, standard-review, deep-review) to start one."

    lines = ["Pipeline runs:"]
    for r in runs:
        lines.append(
            f"  #{r['id']} [{r['run_type']}] — {r['status']} — {r['started_at']}"
            + (f"\n    Question: {r['research_question']}" if r.get("research_question") else "")
        )
    return "\n".join(lines)


# ── Entry point ──────────────────────────────────────────────────────

def main():
    mcp.run()


if __name__ == "__main__":
    main()
