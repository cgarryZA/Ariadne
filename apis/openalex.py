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


async def _request_with_retry(method: str, url: str, **kwargs) -> httpx.Response:
    """Make an HTTP request with exponential backoff on 429 rate limits."""
    client = _get_client()
    for attempt in range(MAX_RETRIES):
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
    """Reconstruct plain-text abstract from OpenAlex inverted index format."""
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


def _parse_work(
    data: dict,
    library_ids: set[str] | None = None,
    library_dois: set[str] | None = None,
) -> SearchResult:
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

    # Cross-source library check: match on prefixed OA ID *or* DOI
    in_lib = prefixed_id in (library_ids or set())
    if not in_lib and library_dois:
        doi = data.get("doi")
        if doi and doi.lower().replace("https://doi.org/", "") in library_dois:
            in_lib = True

    return SearchResult(
        id=prefixed_id,
        title=data.get("title", ""),
        authors=authors,
        year=data.get("publication_year"),
        venue=venue,
        abstract=abstract,
        citation_count=data.get("cited_by_count"),
        is_open_access=is_oa,
        in_library=in_lib,
    )


def _base_params() -> dict[str, str]:
    """Return params shared by all requests (polite pool mailto)."""
    return {"mailto": OPENALEX_MAILTO}


async def search_papers(
    query: str,
    limit: int = 10,
    year_range: Optional[str] = None,
    library_ids: Optional[set[str]] = None,
    library_dois: Optional[set[str]] = None,
) -> list[SearchResult]:
    """Search OpenAlex for papers matching *query*."""
    params: dict = {
        **_base_params(),
        "search": query,
        "per-page": min(limit, 200),
        "select": WORK_FIELDS,
        "sort": "cited_by_count:desc",
    }

    filters: list[str] = []
    if year_range:
        filters.append(f"publication_year:{year_range}")
    if filters:
        params["filter"] = ",".join(filters)

    resp = await _request_with_retry("GET", f"{BASE_URL}/works", params=params)
    data = resp.json()

    return [_parse_work(item, library_ids, library_dois) for item in data.get("results", [])]


async def get_paper_by_doi(doi: str) -> dict:
    """Fetch a single paper by DOI and return fields compatible with Paper model."""
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

    ids = data.get("ids") or {}
    arxiv_url = ids.get("arxiv")
    arxiv_id: str | None = None
    if arxiv_url:
        arxiv_id = arxiv_url.rstrip("/").split("/")[-1]

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
        "url": raw_id or None,
        "pdf_url": pdf_url,
        "citation_count": data.get("cited_by_count"),
        "tldr": None,
    }
