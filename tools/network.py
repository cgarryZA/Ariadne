"""Author and institution network mapping tools.

Phase 4.8: Map co-author networks of key researchers to identify academic
lineages, industry migration, and strategic citation opportunities.
"""

from __future__ import annotations

from typing import Optional

import db
from apis import openalex as oa


def register(mcp):

    @mcp.tool()
    async def map_author_network(
        author_name: str,
        years: int = 5,
        coauthor_limit: int = 15,
    ) -> str:
        """Map a researcher's co-author network and institutional affiliations.

        Uses OpenAlex to pull an author's recent publications, identify their
        frequent co-authors, and map which institutions those co-authors are at.
        Useful for identifying who in industry/academia cares about your topic.

        Args:
            author_name: Author name to look up (e.g. 'Rama Cont', 'Yann LeCun')
            years: How many years back to analyze (default 5)
            coauthor_limit: Max co-authors to return (default 15)
        """
        # Find the author on OpenAlex
        authors = await oa.search_authors(author_name, limit=3)
        if not authors:
            return f"Author '{author_name}' not found on OpenAlex."

        # Use the top match
        author = authors[0]
        author_id = author.get("id", "")
        display_name = author.get("display_name", author_name)
        works_count = author.get("works_count", 0)
        cited_by = author.get("cited_by_count", 0)

        institutions = author.get("last_known_institutions") or []
        inst_names = [i.get("display_name", "") for i in institutions[:3]]

        lines = [
            f"AUTHOR NETWORK: {display_name}",
            f"OpenAlex ID: {author_id}",
            f"Works: {works_count} | Cited by: {cited_by:,}",
        ]
        if inst_names:
            lines.append(f"Current: {', '.join(inst_names)}")
        lines.append("")

        # Get co-authors
        try:
            coauthors = await oa.get_coauthors(author_id, limit=coauthor_limit)
        except Exception as e:
            return "\n".join(lines) + f"\nError fetching co-authors: {e}"

        if coauthors:
            lines.append(f"-- TOP CO-AUTHORS ({len(coauthors)}) --")
            # Group by institution
            by_inst: dict[str, list] = {}
            for ca in coauthors:
                inst = ca.get("institution", "Unknown")
                by_inst.setdefault(inst or "Unknown", []).append(ca)

            for inst, cas in sorted(by_inst.items(), key=lambda x: -sum(c["count"] for c in x[1])):
                lines.append(f"\n  [{inst}]")
                for ca in sorted(cas, key=lambda x: -x["count"]):
                    lines.append(f"    {ca['name']} ({ca['count']} joint papers)")
        else:
            lines.append("No co-authors found (author may have few indexed works).")

        # Check which co-authors we already have papers from
        lib_papers = await db.list_papers(limit=500)
        lib_author_names = set()
        for p in lib_papers:
            for a in p.authors:
                lib_author_names.add(a.name.lower())

        overlap = []
        for ca in coauthors:
            if ca["name"].lower() in lib_author_names:
                overlap.append(ca["name"])

        if overlap:
            lines.append(f"\n-- ALREADY IN YOUR LIBRARY --")
            for name in overlap:
                lines.append(f"  {name}")

        lines += [
            "",
            "-" * 60,
            "Use seed_library(author_name) to browse a co-author's publications.",
            "Use add_paper() to add strategically relevant papers to your library.",
        ]

        return "\n".join(lines)

    @mcp.tool()
    async def map_institution_landscape(
        institution_name: str,
        topic: Optional[str] = None,
        limit: int = 20,
    ) -> str:
        """Find researchers at an institution working on a topic.

        Useful for identifying potential collaborators, PhD supervisors,
        or industry contacts at specific firms.

        Args:
            institution_name: Institution name (e.g. 'Oxford', 'Jane Street', 'DeepMind')
            topic: Optional topic filter (e.g. 'mean-field games')
            limit: Max results (default 20)
        """
        # Search for authors at this institution
        query = f"{institution_name}"
        if topic:
            query += f" {topic}"

        # Use works search with institution filter
        from apis.openalex import _get_client, _base_params, _request_with_retry, BASE_URL

        params: dict = {
            **_base_params(),
            "search": topic or "",
            "filter": f"authorships.institutions.display_name.search:{institution_name}",
            "per-page": min(limit, 50),
            "select": "id,title,authorships,publication_year,cited_by_count",
            "sort": "cited_by_count:desc",
        }

        try:
            resp = await _request_with_retry("GET", f"{BASE_URL}/works", params=params)
            data = resp.json()
        except Exception as e:
            return f"Search failed: {e}"

        works = data.get("results", [])
        if not works:
            return f"No results found for '{institution_name}'" + (f" on '{topic}'" if topic else "")

        # Extract researchers
        researcher_map: dict[str, dict] = {}
        for work in works:
            for authorship in work.get("authorships", []):
                author = authorship.get("author", {})
                aid = author.get("id", "")
                insts = [i.get("display_name", "") for i in (authorship.get("institutions") or [])]
                # Check if this author is at the target institution
                if any(institution_name.lower() in i.lower() for i in insts):
                    if aid not in researcher_map:
                        researcher_map[aid] = {
                            "name": author.get("display_name", ""),
                            "institution": ", ".join(insts[:2]),
                            "papers": 0,
                            "top_paper": "",
                            "max_citations": 0,
                        }
                    researcher_map[aid]["papers"] += 1
                    cites = work.get("cited_by_count", 0)
                    if cites > researcher_map[aid]["max_citations"]:
                        researcher_map[aid]["max_citations"] = cites
                        researcher_map[aid]["top_paper"] = work.get("title", "")[:80]

        if not researcher_map:
            return f"No researchers found at '{institution_name}'" + (f" on '{topic}'" if topic else "")

        researchers = sorted(researcher_map.values(), key=lambda x: -x["papers"])

        lines = [
            f"INSTITUTION LANDSCAPE: {institution_name}",
        ]
        if topic:
            lines.append(f"Topic filter: {topic}")
        lines.append(f"Researchers found: {len(researchers)}")
        lines.append("")

        for r in researchers[:limit]:
            lines.append(f"  **{r['name']}** ({r['papers']} papers, top cited: {r['max_citations']:,})")
            if r["top_paper"]:
                lines.append(f"    Top paper: {r['top_paper']}")
            lines.append(f"    At: {r['institution']}")

        lines += [
            "",
            "-" * 60,
            "Use seed_library(author_name) to browse specific researchers.",
        ]

        return "\n".join(lines)
