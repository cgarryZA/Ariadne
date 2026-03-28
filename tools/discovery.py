"""Discovery tools — search across academic databases."""

from __future__ import annotations

import asyncio
import re
from typing import Optional

import db
from apis import arxiv_client as arxiv
from apis import openalex as oa
from apis import semantic_scholar as s2
from models import Citation
from tools.formatting import format_result


def register(mcp):

    @mcp.tool()
    async def search_papers(
        query: str,
        limit: int = 10,
        year_range: Optional[str] = None,
        fields_of_study: Optional[str] = None,
    ) -> str:
        """Search Semantic Scholar for academic papers.

        Args:
            query: Natural language search (e.g. 'transformer attention mechanism survey')
            limit: Max results (1-100, default 10)
            year_range: Filter by year range (e.g. '2018-2024', '2020-', '-2015')
            fields_of_study: Comma-separated fields (e.g. 'Mathematics,Computer Science')
        """
        lib_ids = await db.get_library_ids()
        fos = [f.strip() for f in fields_of_study.split(",")] if fields_of_study else None

        results = await s2.search_papers(
            query=query, limit=limit, year_range=year_range,
            fields_of_study=fos, library_ids=lib_ids,
        )
        await db.log_search(query, "semantic_scholar", len(results))

        if not results:
            return "No papers found for that query."

        formatted = [format_result(r) for r in results]
        return f"Found {len(results)} papers:\n\n" + "\n\n---\n\n".join(formatted)

    async def _resolve_s2_id(paper_id: str) -> str:
        """Resolve a paper ID to a Semantic Scholar ID if needed.

        If the paper is in the library with a DOI, tries DOI: prefix.
        If it has an arxiv_id, tries ARXIV: prefix.
        Returns the best ID to use with S2 API calls.
        """
        # Already looks like an S2 hash or has a known prefix
        if len(paper_id) >= 30 or paper_id.startswith(("DOI:", "ARXIV:", "OA:")):
            return paper_id

        # Look up in library for DOI or arXiv ID
        paper = await db.get_paper(paper_id)
        if paper:
            if paper.doi:
                return f"DOI:{paper.doi}"
            if paper.arxiv_id:
                return f"ARXIV:{paper.arxiv_id}"
        return paper_id

    @mcp.tool()
    async def get_citations(paper_id: str, limit: int = 20) -> str:
        """Get papers that cite a given paper (who cited this?).

        Also stores citation edges in the database for find_bridges() and
        the citation graph.

        Args:
            paper_id: Semantic Scholar paper ID, DOI:xxx, or ARXIV:xxx
            limit: Max results (default 20)
        """
        resolved_id = await _resolve_s2_id(paper_id)
        lib_ids = await db.get_library_ids()
        results = await s2.get_citations(resolved_id, limit=limit, library_ids=lib_ids)

        if not results:
            return "No citations found."

        # Store citation edges for find_bridges() / citation graph
        edges = [Citation(citing_id=r.id, cited_id=paper_id) for r in results]
        await db.insert_citations(edges)

        formatted = [format_result(r) for r in results]
        return f"Found {len(results)} citing papers:\n\n" + "\n\n---\n\n".join(formatted)

    @mcp.tool()
    async def get_references(paper_id: str, limit: int = 20) -> str:
        """Get papers referenced by a given paper (what did this paper cite?).

        Also stores citation edges in the database for find_bridges() and
        the citation graph.

        Args:
            paper_id: Semantic Scholar paper ID, DOI:xxx, or ARXIV:xxx
            limit: Max results (default 20)
        """
        resolved_id = await _resolve_s2_id(paper_id)
        lib_ids = await db.get_library_ids()
        results = await s2.get_references(resolved_id, limit=limit, library_ids=lib_ids)

        if not results:
            return "No references found."

        # Store citation edges
        edges = [Citation(citing_id=paper_id, cited_id=r.id) for r in results]
        await db.insert_citations(edges)

        formatted = [format_result(r) for r in results]
        return f"Found {len(results)} referenced papers:\n\n" + "\n\n---\n\n".join(formatted)

    @mcp.tool()
    async def find_related(paper_id: str, limit: int = 10) -> str:
        """Get AI-recommended papers similar to a given paper (Semantic Scholar recommendations).

        Args:
            paper_id: Semantic Scholar paper ID, DOI:xxx, or ARXIV:xxx
            limit: Max results (default 10)
        """
        resolved_id = await _resolve_s2_id(paper_id)
        lib_ids = await db.get_library_ids()
        results = await s2.find_related(resolved_id, limit=limit, library_ids=lib_ids)

        if not results:
            return "No recommendations found."

        formatted = [format_result(r) for r in results]
        return f"Found {len(results)} related papers:\n\n" + "\n\n---\n\n".join(formatted)

    @mcp.tool()
    async def seed_library(author_name: str, limit: int = 20) -> str:
        """Find papers by a specific author and preview them (does NOT auto-add to library).

        Args:
            author_name: Author name (e.g. 'Yann LeCun', 'Yoshua Bengio')
            limit: Max papers to return (default 20)
        """
        lib_ids = await db.get_library_ids()
        results = await s2.search_by_author(author_name, limit=limit, library_ids=lib_ids)

        if not results:
            return f"No papers found for author '{author_name}'."

        formatted = [format_result(r) for r in results]
        return (
            f"Found {len(results)} papers by {author_name}.\n"
            "Use add_paper(paper_id) to add specific ones to your library.\n\n"
            + "\n\n---\n\n".join(formatted)
        )

    @mcp.tool()
    async def search_openalex(
        query: str,
        limit: int = 10,
        year_range: Optional[str] = None,
    ) -> str:
        """Search OpenAlex for academic papers (250M+ papers, fully open, no key needed).

        Complements search_papers() (Semantic Scholar). Good for:
        - Papers with strong concept/field tagging
        - Open-access papers
        - Papers not yet indexed in Semantic Scholar

        Results include a DOI when available — use add_paper('DOI:10.xxx') to add.

        Args:
            query: Natural language search query
            limit: Max results (1-100, default 10)
            year_range: Filter by year (e.g. '2018-2024', '2020-')
        """
        lib_ids = await db.get_library_ids()
        lib_dois = await db.get_library_dois()
        try:
            results = await oa.search_papers(
                query=query, limit=limit, year_range=year_range,
                library_ids=lib_ids, library_dois=lib_dois,
            )
        except Exception as e:
            return f"OpenAlex search failed: {e}"

        await db.log_search(query, "openalex", len(results))

        if not results:
            return "No papers found on OpenAlex for that query."

        formatted = [format_result(r) for r in results]
        return f"OpenAlex: {len(results)} papers\n\n" + "\n\n---\n\n".join(formatted)

    @mcp.tool()
    async def search_arxiv(
        query: str,
        categories: Optional[str] = None,
        max_results: int = 10,
    ) -> str:
        """Search arXiv for preprints (math, CS, quantitative finance, physics, etc.).

        Essential for cutting-edge research not yet peer-reviewed or indexed in S2.
        Results have ARXIV: IDs — use add_paper('ARXIV:2103.01234') to add.

        Common categories:
          cs.LG  — Machine Learning
          math.PR — Probability
          math.NA — Numerical Analysis
          q-fin.TR — Trading and Market Microstructure
          q-fin.MF — Mathematical Finance
          stat.ML — Statistics / Machine Learning

        Args:
            query: Search terms
            categories: Comma-separated arXiv category codes (e.g. 'cs.LG,math.PR')
            max_results: Max results (default 10)
        """
        lib_ids = await db.get_library_ids()
        cats = [c.strip() for c in categories.split(",")] if categories else None

        try:
            results = await arxiv.search_arxiv(query=query, categories=cats, max_results=max_results, library_ids=lib_ids)
        except Exception as e:
            return f"arXiv search failed: {e}"

        await db.log_search(query, "arxiv", len(results))

        if not results:
            return "No papers found on arXiv for that query."

        formatted = [format_result(r) for r in results]
        return f"arXiv: {len(results)} preprints\n\n" + "\n\n---\n\n".join(formatted)

    @mcp.tool()
    async def multi_search(
        query: str,
        limit: int = 10,
        year_range: Optional[str] = None,
        sources: str = "semantic_scholar,openalex,arxiv",
    ) -> str:
        """Search across multiple academic databases simultaneously.

        Runs the same query on Semantic Scholar, OpenAlex, and/or arXiv in parallel
        and returns deduplicated, merged results.

        Args:
            query: Search query
            limit: Results per source (default 10)
            year_range: Year filter (e.g. '2018-2024')
            sources: Comma-separated sources to query (default: all three)
        """
        lib_ids = await db.get_library_ids()
        lib_dois = await db.get_library_dois()
        src_list = [s.strip() for s in sources.split(",")]

        tasks = {}
        if "semantic_scholar" in src_list:
            tasks["S2"] = s2.search_papers(query=query, limit=limit, year_range=year_range, library_ids=lib_ids)
        if "openalex" in src_list:
            tasks["OpenAlex"] = oa.search_papers(query=query, limit=limit, year_range=year_range, library_ids=lib_ids, library_dois=lib_dois)
        if "arxiv" in src_list:
            tasks["arXiv"] = arxiv.search_arxiv(query=query, max_results=limit, library_ids=lib_ids)

        gathered = await asyncio.gather(*tasks.values(), return_exceptions=True)
        source_results = dict(zip(tasks.keys(), gathered))

        # Improved dedup: normalize titles (strip punctuation, collapse whitespace)
        # and also match on DOI when available
        seen_titles: set[str] = set()
        seen_dois: set[str] = set()
        all_results = []
        for source, results in source_results.items():
            if isinstance(results, Exception):
                continue
            for r in results:
                # Normalize title for comparison
                key = re.sub(r"[^\w\s]", "", r.title.lower()).strip()
                key = " ".join(key.split())[:80]

                # Check DOI-based dedup (extract DOI from result if available)
                doi_key = None
                if hasattr(r, "doi") and r.doi:
                    doi_key = r.doi.lower()

                if key in seen_titles:
                    continue
                if doi_key and doi_key in seen_dois:
                    continue

                seen_titles.add(key)
                if doi_key:
                    seen_dois.add(doi_key)
                all_results.append((source, r))

        await db.log_search(query, "multi", len(all_results))

        if not all_results:
            return "No results found across any source."

        lines = [f"Multi-source search: {len(all_results)} unique papers\n"]
        for source, r in all_results:
            authors = ", ".join(a.name for a in r.authors[:3])
            if len(r.authors) > 3:
                authors += " et al."
            lib = " [IN LIBRARY]" if r.in_library else ""
            lines.append(f"[{source}] **{r.title}**{lib}")
            lines.append(f"  {authors} ({r.year or '?'}) | Citations: {r.citation_count or '-'} | ID: {r.id}")
            if r.tldr:
                lines.append(f"  TLDR: {r.tldr}")
            lines.append("")

        return "\n".join(lines)
