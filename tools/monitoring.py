"""Watch list, citation monitoring, and citation context tools."""

from __future__ import annotations

import asyncio
from typing import Optional

import db
from apis import semantic_scholar as s2
from models import Citation
from tools._llm_client import extract, is_available as llm_available
from tools._text_processing import budget_text


def register(mcp):

    @mcp.tool()
    async def watch_add(paper_ids: str) -> str:
        """Add papers to the watch list for continuous citation monitoring.

        Args:
            paper_ids: Comma-separated paper IDs
        """
        ids = [pid.strip() for pid in paper_ids.split(",")]
        added = await db.watch_add(ids)
        total = len(await db.watch_list())
        return f"Added {added} new seed(s) to watch list. Total seeds: {total}"

    @mcp.tool()
    async def watch_remove(paper_id: str) -> str:
        """Remove a paper from the watch list.

        Args:
            paper_id: Paper ID to remove
        """
        removed = await db.watch_remove(paper_id)
        return "Removed from watch list." if removed else "Paper not in watch list."

    @mcp.tool()
    async def watch_check(limit_per_seed: int = 15) -> str:
        """Check the watch list for new papers citing your seed papers.

        Args:
            limit_per_seed: Max papers to check per seed (default 15)
        """
        seeds = await db.watch_list()
        if not seeds:
            return "Watch list is empty. Use watch_add(paper_ids) to add seed papers."

        lib_ids = await db.get_library_ids()
        new_found: list[tuple[str, object]] = []

        for seed_row in seeds:
            seed_id = seed_row["paper_id"]
            seed_paper = await db.get_paper(seed_id)
            seed_title = seed_paper.title if seed_paper else seed_id

            try:
                results = await s2.get_citations(seed_id, limit=limit_per_seed, library_ids=lib_ids)
                await asyncio.sleep(1.2)
            except Exception as e:
                new_found.append((seed_title, f"[error: {e}]"))
                continue

            for r in results:
                if not r.in_library:
                    new_found.append((seed_title, r))

            await db.watch_mark_checked(seed_id)

        if not new_found:
            return (
                f"Watch check complete - {len(seeds)} seed(s) checked.\n"
                "No new papers found outside your library."
            )

        lines = [f"Watch check: {len(new_found)} new paper(s) found\n"]
        for seed_title, result in new_found:
            if isinstance(result, str):
                lines.append(f"[{seed_title}] {result}")
            else:
                r = result
                authors = ", ".join(a.name for a in r.authors[:2])
                lines.append(f"Cited by: {seed_title}")
                lines.append(f"  **{r.title}**")
                lines.append(f"  {authors} ({r.year or '?'}) | Citations: {r.citation_count or 0} | ID: {r.id}")
                if r.tldr:
                    lines.append(f"  TLDR: {r.tldr}")
                lines.append("")

        lines.append("Use add_paper(id) or batch_add(ids) to add any of these to your library.")
        return "\n".join(lines)

    @mcp.tool()
    async def build_citation_network(
        paper_id: str,
        depth: int = 1,
        direction: str = "both",
        limit_per_level: int = 30,
        add_to_library: bool = False,
    ) -> str:
        """Recursively fetch and store citation relationships for a paper.

        Args:
            paper_id: Seed paper's ID
            depth: How many hops to traverse (1 or 2, default 1)
            direction: 'citations' (who cites this), 'references' (what it cites), or 'both'
            limit_per_level: Max papers to fetch per node (default 30)
            add_to_library: If True, add all discovered papers to library too (slower)
        """
        from bibtex import paper_to_bibtex
        from models import Paper

        seed = await db.get_paper(paper_id)
        seed_title = seed.title if seed else paper_id

        lib_ids = await db.get_library_ids()
        new_edges = 0
        new_papers = 0
        visited: set[str] = {paper_id}
        queue = [(paper_id, 0)]

        sem = asyncio.Semaphore(3)

        async def fetch_and_store(pid: str, current_depth: int):
            nonlocal new_edges, new_papers
            async with sem:
                results_cite, results_ref = [], []

                if direction in ("citations", "both"):
                    try:
                        results_cite = await s2.get_citations(pid, limit=limit_per_level)
                        await asyncio.sleep(1.2)
                    except Exception:
                        pass

                if direction in ("references", "both"):
                    try:
                        results_ref = await s2.get_references(pid, limit=limit_per_level)
                        await asyncio.sleep(1.2)
                    except Exception:
                        pass

            edges_to_store = (
                [(pid, r.id) for r in results_ref] +
                [(r.id, pid) for r in results_cite]
            )
            for citing, cited in edges_to_store:
                try:
                    await db.insert_citations([Citation(citing_id=citing, cited_id=cited)])
                    new_edges += 1
                except Exception:
                    pass

            all_found = results_cite + results_ref
            if add_to_library:
                for r in all_found:
                    if r.id not in lib_ids:
                        try:
                            data = await s2.get_paper_details(r.id)
                            fields = s2.parse_paper_to_library(data)
                            paper = Paper(**fields)
                            paper.bibtex = paper_to_bibtex(paper)
                            await db.insert_paper(paper)
                            lib_ids.add(r.id)
                            new_papers += 1
                            await asyncio.sleep(1.5)
                        except Exception:
                            pass

            if current_depth < depth:
                for r in all_found:
                    if r.id not in visited:
                        visited.add(r.id)
                        queue.append((r.id, current_depth + 1))

        while queue:
            batch = []
            while queue and len(batch) < 5:
                batch.append(queue.pop(0))
            await asyncio.gather(*[fetch_and_store(pid, d) for pid, d in batch])

        result = (
            f"Citation network built for: {seed_title}\n"
            f"Depth: {depth} | Direction: {direction}\n"
            f"Edges stored: {new_edges}\n"
            f"Papers visited: {len(visited)}\n"
        )
        if add_to_library:
            result += f"New papers added to library: {new_papers}\n"
        result += "\nRun find_bridges() to identify cross-pillar connections."
        return result

    @mcp.tool()
    async def extract_citation_context(
        citing_paper_id: str,
        cited_paper_id: str,
    ) -> str:
        """Analyze HOW one paper cites another — supporting, contrasting, or just mentioning.

        Searches the citing paper's full text for references to the cited paper and
        classifies each mention. Requires the citing paper to have full text stored
        (run download_pdf first).

        If ANTHROPIC_API_KEY is set, uses internal LLM for automated classification.

        Args:
            citing_paper_id: ID of the paper that does the citing
            cited_paper_id: ID of the paper being cited
        """
        citing = await db.get_paper(citing_paper_id)
        cited = await db.get_paper(cited_paper_id)

        if not citing:
            return f"Citing paper '{citing_paper_id}' not found in library."
        if not cited:
            return f"Cited paper '{cited_paper_id}' not found in library."

        fulltext = await db.get_fulltext(citing_paper_id)
        if not fulltext:
            return (
                f"No full text stored for '{citing.title}'.\n"
                "Run download_pdf() first to download and extract the text."
            )

        # Find references to the cited paper in the text
        # Look for author last names + year
        search_terms = []
        if cited.authors:
            for a in cited.authors[:3]:
                last = a.name.split()[-1]
                if cited.year:
                    search_terms.append(f"{last}")
        if cited.year:
            search_terms.append(str(cited.year))

        # Extract paragraphs that mention the cited paper
        paragraphs = fulltext.split("\n\n")
        relevant = []
        for para in paragraphs:
            para_lower = para.lower()
            # Check if this paragraph mentions the cited paper
            if any(term.lower() in para_lower for term in search_terms if len(term) > 3):
                # Further check: must mention year AND an author name
                has_year = str(cited.year) in para if cited.year else True
                has_author = any(
                    a.name.split()[-1].lower() in para_lower
                    for a in (cited.authors or [])[:3]
                )
                if has_year and has_author:
                    relevant.append(para.strip()[:500])

        if not relevant:
            return (
                f"Could not find references to '{cited.title}' in the text of '{citing.title}'.\n"
                "The citation may use a different naming format or may not be in the extracted text."
            )

        lines = [
            "CITATION CONTEXT ANALYSIS",
            f"Citing: {citing.title} ({citing.year or '?'})",
            f"Cited:  {cited.title} ({cited.year or '?'})",
            f"Found {len(relevant)} mention(s)",
            "",
        ]

        if llm_available():
            text = (
                f"Cited paper: {cited.title}\n\n"
                "Passages from the citing paper that reference it:\n\n"
                + "\n---\n".join(relevant[:5])
            )
            try:
                result = await extract(text, "citation_context")
                mentions = result.data.get("mentions", [])
                if mentions:
                    lines.append("Classification:")
                    for m in mentions:
                        ctx = m.get("context", "")[:150]
                        ctype = m.get("type", "mentioning")
                        lines.append(f"  [{ctype.upper()}] {ctx}")
                    lines.append(f"\n[Model: {result.model_used}]")
                    return "\n".join(lines)
            except Exception:
                pass  # Fall through to manual

        # Manual mode
        lines.append("Relevant passages:")
        for i, para in enumerate(relevant[:5], 1):
            lines.append(f"\n[{i}] {para}")

        lines += [
            "",
            "-" * 60,
            "Classify each passage as:",
            "  SUPPORTING   — builds on, agrees with, extends the cited work",
            "  CONTRASTING  — disagrees, finds problems, offers alternative",
            "  MENTIONING   — neutral reference, background citation",
        ]

        return "\n".join(lines)
