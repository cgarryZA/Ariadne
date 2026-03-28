"""arXiv API client for paper search.

Uses the arXiv Atom XML API — no key required.
Rate limit: 3 seconds between calls (enforced via asyncio.sleep).
"""

from __future__ import annotations

import asyncio
import re
import xml.etree.ElementTree as ET
from typing import Optional

import httpx

from models import Author, SearchResult


BASE_URL = "http://export.arxiv.org/api/query"

# XML namespaces used by the arXiv Atom feed
NS_ATOM = "{http://www.w3.org/2005/Atom}"
NS_ARXIV = "{http://arxiv.org/schemas/atom}"

# Recommended delay between requests (arXiv ToS)
_REQUEST_DELAY = 3.0  # seconds


def _extract_arxiv_id(id_url: str) -> str:
    """Strip the arXiv URL prefix and version suffix from an entry id.

    E.g. ``'http://arxiv.org/abs/2103.01234v2'`` -> ``'2103.01234'``.
    """
    bare = id_url.rstrip("/").split("/abs/")[-1]
    # Remove trailing version suffix like 'v2'
    return re.sub(r"v\d+$", "", bare)


def _parse_entry(entry: ET.Element, library_ids: set[str] | None = None) -> SearchResult:
    """Parse a single ``<entry>`` element from the arXiv Atom feed."""
    # ID
    id_el = entry.find(f"{NS_ATOM}id")
    raw_id = id_el.text.strip() if id_el is not None and id_el.text else ""
    arxiv_id = _extract_arxiv_id(raw_id) if raw_id else ""
    prefixed_id = f"ARXIV:{arxiv_id}"

    # Title — collapse internal whitespace
    title_el = entry.find(f"{NS_ATOM}title")
    title = " ".join((title_el.text or "").split()) if title_el is not None else ""

    # Authors
    authors: list[Author] = []
    for author_el in entry.findall(f"{NS_ATOM}author"):
        name_el = author_el.find(f"{NS_ATOM}name")
        if name_el is not None and name_el.text:
            authors.append(Author(name=name_el.text.strip()))

    # Abstract
    summary_el = entry.find(f"{NS_ATOM}summary")
    abstract = " ".join((summary_el.text or "").split()) if summary_el is not None else None

    # Year from published date ("2021-03-01T00:00:00Z")
    published_el = entry.find(f"{NS_ATOM}published")
    year: int | None = None
    if published_el is not None and published_el.text:
        try:
            year = int(published_el.text[:4])
        except (ValueError, IndexError):
            year = None

    # Primary category (venue)
    category_el = entry.find(f"{NS_ARXIV}primary_category")
    primary_category = category_el.get("term") if category_el is not None else None
    venue = f"arXiv:{primary_category}" if primary_category else "arXiv"

    # PDF link
    pdf_url: str | None = None
    for link_el in entry.findall(f"{NS_ATOM}link"):
        if link_el.get("title") == "pdf":
            pdf_url = link_el.get("href")
            break

    return SearchResult(
        id=prefixed_id,
        title=title,
        authors=authors,
        year=year,
        venue=venue,
        abstract=abstract,
        citation_count=None,  # arXiv does not provide citation counts
        is_open_access=True,  # arXiv is always open access
        in_library=prefixed_id in (library_ids or set()),
    )


async def search_arxiv(
    query: str,
    categories: Optional[list[str]] = None,
    max_results: int = 10,
    library_ids: Optional[set[str]] = None,
) -> list[SearchResult]:
    """Search arXiv for papers matching *query*.

    Args:
        query: Free-text search string, searched across all fields.
        categories: Optional list of arXiv category codes to restrict results,
            e.g. ``['cs.LG', 'stat.ML']``. Multiple categories are ORed.
            Common codes: ``cs.LG``, ``math.PR``, ``math.NA``,
            ``q-fin.TR``, ``q-fin.MF``, ``stat.ML``.
        max_results: Maximum number of results to return.
        library_ids: Set of prefixed IDs already in the local library,
            used to populate ``in_library`` on each result.

    Returns:
        List of :class:`SearchResult` objects.
    """
    # Respect arXiv's recommended 3-second inter-request delay
    await asyncio.sleep(_REQUEST_DELAY)

    # Build search_query string
    if categories:
        cat_expr = " OR ".join(f"cat:{c}" for c in categories)
        search_query = f"({cat_expr}) AND all:{query}"
    else:
        search_query = f"all:{query}"

    params = {
        "search_query": search_query,
        "start": 0,
        "max_results": max_results,
        "sortBy": "relevance",
        "sortOrder": "descending",
    }

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(BASE_URL, params=params)
    resp.raise_for_status()

    root = ET.fromstring(resp.text)

    results: list[SearchResult] = []
    for entry in root.findall(f"{NS_ATOM}entry"):
        results.append(_parse_entry(entry, library_ids))

    return results
