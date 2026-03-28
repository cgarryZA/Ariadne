"""OpenAlex API client for paper search and lookup.

OpenAlex is a free, open academic database with 250M+ papers.
No API key required. Uses the polite pool via OPENALEX_MAILTO env var.
"""

from __future__ import annotations

import asyncio
import os
from typing import Optional

import httpx

from models import Author, SearchResult


MAX_RETRIES = 5
BASE_DELAY = 2.0  # seconds

BASE_URL = "https://api.openalex.org"

OPENALEX_MAILTO = os.environ.get("OPENALEX_MAILTO", "research@ariadne.local")

WORK_FIELDS = (
    "id,title,authorships,publication_year,primary_location,"
    "abstract_inverted_index,cited_by_count,doi,ids,open_access,best_oa_location"
)


async def _request_with_retry(method: str, url: str, **kwargs) -> httpx.Response:
    """Make an HTTP request with exponential backoff on 429 rate limits."""
    for attempt in range(MAX_RETRIES):
        async with httpx.AsyncClient(timeout=30) as client:
            if method == "GET":
                resp = await client.get(url, **kwargs)
            else:
                resp = await client.post(url, **kwargs)
        if resp.status_code == 429 and attempt < MAX_RETRIES - 1:
            delay = BASE_DELAY * (2 ** attempt)
            await asyncio.sleep(delay)
            continue
        resp.raise_for_status()
        return resp
    resp.raise_for_status()
    return resp


def _reconstruct_abstract(inverted_index: dict | None) -> str | None:
    """Reconstruct plain-text abstract from OpenAlex inverted index format.

    OpenAlex stores abstracts as a dict mapping word -> [list of positions].
    We invert this to recover the original word order.
    """
    if not inverted_index:
        return None
    position_map: dict[int, str] = {}
    for word, positions in inverted_index.items():
        for pos in positions:
            position_map[pos] = word
    if not position_map:
        return None
    return " ".join(position_map[i] for i in sorted(position_map))


def _extract_oa_id(openalex_url: str) -> str:
    """Extract the bare OpenAlex work ID (e.g. 'W2741809807') from a full URL."""
    return openalex_url.rstrip("/").split("/")[-1]


def _parse_work(data: dict, library_ids: set[str] | None = None) -> SearchResult:
    """Convert an OpenAlex work dict into a SearchResult."""
    raw_id = data.get("id", "")
    bare_id = _extract_oa_id(raw_id) if raw_id else raw_id
    prefixed_id = f"OA:{bare_id}"

    authors = [
        Author(
            name=a.get("author", {}).get("display_name", ""),
            author_id=a.get("author", {}).get("id"),
        )
        for a in (data.get("authorships") or [])
    ]

    primary_location = data.get("primary_location") or {}
    source = primary_location.get("source") or {}
    venue = source.get("display_name") or None

    abstract = _reconstruct_abstract(data.get("abstract_inverted_index"))

    oa_info = data.get("open_access") or {}
    is_oa = bool(oa_info.get("is_oa", False))

    return SearchResult(
        id=prefixed_id,
        title=data.get("title", ""),
        authors=authors,
        year=data.get("publication_year"),
        venue=venue,
        abstract=abstract,
        citation_count=data.get("cited_by_count"),
        is_open_access=is_oa,
        in_library=prefixed_id in (library_ids or set()),
    )


def _base_params() -> dict[str, str]:
    """Return params shared by all requests (polite pool mailto)."""
    return {"mailto": OPENALEX_MAILTO}


async def search_papers(
    query: str,
    limit: int = 10,
    year_range: Optional[str] = None,
    library_ids: Optional[set[str]] = None,
) -> list[SearchResult]:
    """Search OpenAlex for papers matching *query*.

    Args:
        query: Free-text search string.
        limit: Maximum number of results to return (capped at 200).
        year_range: Optional year filter, e.g. ``'2018-2024'`` or ``'2020-'``.
            Passed as ``filter=publication_year:<range>``.
        library_ids: Set of prefixed IDs already in the local library,
            used to populate ``in_library`` on each result.

    Returns:
        List of :class:`SearchResult` objects.
    """
    params: dict = {
        **_base_params(),
        "search": query,
        "per-page": min(limit, 200),
        "select": WORK_FIELDS,
        "sort": "cited_by_count:desc",
    }

    filters: list[str] = []
    if year_range:
        # Accept '2018-2024', '2020-', or '-2024'
        filters.append(f"publication_year:{year_range}")
    if filters:
        params["filter"] = ",".join(filters)

    resp = await _request_with_retry("GET", f"{BASE_URL}/works", params=params)
    data = resp.json()

    return [_parse_work(item, library_ids) for item in data.get("results", [])]


async def get_paper_by_doi(doi: str) -> dict:
    """Fetch a single paper by DOI and return fields compatible with ``parse_paper_to_library``.

    Args:
        doi: A bare DOI string, e.g. ``'10.1145/3219819.3219943'``.

    Returns:
        Dict with keys: id, title, authors, year, venue, abstract, doi,
        arxiv_id, url, pdf_url, citation_count, tldr.
        ``tldr`` is always ``None`` (OpenAlex does not provide TLDRs).
    """
    encoded_doi = f"doi:{doi}"
    params = {
        **_base_params(),
        "select": WORK_FIELDS,
    }
    resp = await _request_with_retry("GET", f"{BASE_URL}/works/{encoded_doi}", params=params)
    data = resp.json()

    raw_id = data.get("id", "")
    bare_id = _extract_oa_id(raw_id) if raw_id else raw_id
    prefixed_id = f"OA:{bare_id}"

    authors = [
        Author(
            name=a.get("author", {}).get("display_name", ""),
            author_id=a.get("author", {}).get("id"),
        )
        for a in (data.get("authorships") or [])
    ]

    primary_location = data.get("primary_location") or {}
    source = primary_location.get("source") or {}
    venue = source.get("display_name") or None

    abstract = _reconstruct_abstract(data.get("abstract_inverted_index"))

    # Extract ArXiv ID from ids dict if present
    ids = data.get("ids") or {}
    arxiv_url = ids.get("arxiv")
    arxiv_id: str | None = None
    if arxiv_url:
        # ids.arxiv is like "https://arxiv.org/abs/2103.01234"
        arxiv_id = arxiv_url.rstrip("/").split("/")[-1]

    # PDF URL — prefer best_oa_location, fall back to primary_location
    best_oa = data.get("best_oa_location") or {}
    pdf_url = best_oa.get("pdf_url") or primary_location.get("pdf_url") or None

    return {
        "id": prefixed_id,
        "title": data.get("title", ""),
        "authors": authors,
        "year": data.get("publication_year"),
        "venue": venue,
        "abstract": abstract,
        "doi": data.get("doi"),
        "arxiv_id": arxiv_id,
        "url": raw_id or None,  # OpenAlex canonical URL
        "pdf_url": pdf_url,
        "citation_count": data.get("cited_by_count"),
        "tldr": None,
    }
