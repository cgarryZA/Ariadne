"""arXiv API client for paper search.

Uses the arXiv Atom XML API — no key required.
Rate limit: 3 seconds between calls (enforced via smart delay tracking).
"""

from __future__ import annotations

import asyncio
import re
import time
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
_last_request_time: float = 0.0

# ---------------------------------------------------------------------------
# Shared HTTP client
# ---------------------------------------------------------------------------

_client: Optional[httpx.AsyncClient] = None


def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(timeout=30)
    return _client


async def close_client() -> None:
    global _client
    if _client is not None and not _client.is_closed:
        await _client.aclose()
        _client = None


async def _respect_rate_limit() -> None:
    """Sleep only the remaining time needed to respect the 3-second inter-request delay."""
    global _last_request_time
    now = time.monotonic()
    elapsed = now - _last_request_time
    if elapsed < _REQUEST_DELAY:
        await asyncio.sleep(_REQUEST_DELAY - elapsed)
    _last_request_time = time.monotonic()


def _extract_arxiv_id(id_url: str) -> str:
    """Strip the arXiv URL prefix and version suffix from an entry id."""
    bare = id_url.rstrip("/").split("/abs/")[-1]
    return re.sub(r"v\d+$", "", bare)


def _parse_entry(entry: ET.Element, library_ids: set[str] | None = None) -> SearchResult:
    """Parse a single ``<entry>`` element from the arXiv Atom feed."""
    id_el = entry.find(f"{NS_ATOM}id")
    raw_id = id_el.text.strip() if id_el is not None and id_el.text else ""
    arxiv_id = _extract_arxiv_id(raw_id) if raw_id else ""
    prefixed_id = f"ARXIV:{arxiv_id}"

    title_el = entry.find(f"{NS_ATOM}title")
    title = " ".join((title_el.text or "").split()) if title_el is not None else ""

    authors: list[Author] = []
    for author_el in entry.findall(f"{NS_ATOM}author"):
        name_el = author_el.find(f"{NS_ATOM}name")
        if name_el is not None and name_el.text:
            authors.append(Author(name=name_el.text.strip()))

    summary_el = entry.find(f"{NS_ATOM}summary")
    abstract = " ".join((summary_el.text or "").split()) if summary_el is not None else None

    published_el = entry.find(f"{NS_ATOM}published")
    year: int | None = None
    if published_el is not None and published_el.text:
        try:
            year = int(published_el.text[:4])
        except (ValueError, IndexError):
            year = None

    category_el = entry.find(f"{NS_ARXIV}primary_category")
    primary_category = category_el.get("term") if category_el is not None else None
    venue = f"arXiv:{primary_category}" if primary_category else "arXiv"

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
        citation_count=None,
        is_open_access=True,
        in_library=prefixed_id in (library_ids or set()),
    )


async def search_arxiv(
    query: str,
    categories: Optional[list[str]] = None,
    max_results: int = 10,
    library_ids: Optional[set[str]] = None,
) -> list[SearchResult]:
    """Search arXiv for papers matching *query*."""
    await _respect_rate_limit()

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

    client = _get_client()
    resp = await client.get(BASE_URL, params=params)
    resp.raise_for_status()

    root = ET.fromstring(resp.text)

    results: list[SearchResult] = []
    for entry in root.findall(f"{NS_ATOM}entry"):
        results.append(_parse_entry(entry, library_ids))

    return results
