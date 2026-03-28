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
        "you can configure later and use auto_detect_pillars() once you have ~10 papers."
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


# ── MCP Prompts ──────────────────────────────────────────────────────

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


# ── Entry point ──────────────────────────────────────────────────────

def main():
    mcp.run()


if __name__ == "__main__":
    main()
