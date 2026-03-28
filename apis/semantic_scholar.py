"""Semantic Scholar API client for paper search and citation data."""

from __future__ import annotations

import asyncio
import os
from typing import Optional

import httpx


MAX_RETRIES = 6
BASE_DELAY = 5.0  # seconds — generous for free tier


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

from models import Author, Citation, SearchResult

BASE_URL = "https://api.semanticscholar.org/graph/v1"
RECS_URL = "https://api.semanticscholar.org/recommendations/v1"

PAPER_FIELDS = (
    "paperId,title,authors,year,venue,abstract,citationCount,"
    "referenceCount,tldr,externalIds,isOpenAccess,openAccessPdf,"
    "url"
)

CITATION_FIELDS = (
    "paperId,title,authors,year,venue,citationCount,"
    "isOpenAccess,contexts,isInfluential"
)


def _headers() -> dict[str, str]:
    key = os.environ.get("S2_API_KEY")
    if key:
        return {"x-api-key": key}
    return {}


def _parse_search_result(data: dict, library_ids: set[str] | None = None) -> SearchResult:
    authors = [
        Author(name=a.get("name", ""), author_id=a.get("authorId"))
        for a in (data.get("authors") or [])
    ]
    tldr = data.get("tldr")
    if isinstance(tldr, dict):
        tldr = tldr.get("text")

    return SearchResult(
        id=data["paperId"],
        title=data.get("title", ""),
        authors=authors,
        year=data.get("year"),
        venue=data.get("venue"),
        abstract=data.get("abstract"),
        citation_count=data.get("citationCount"),
        tldr=tldr,
        is_open_access=data.get("isOpenAccess", False),
        in_library=data["paperId"] in (library_ids or set()),
    )


async def search_papers(
    query: str,
    limit: int = 10,
    year_range: Optional[str] = None,
    fields_of_study: Optional[list[str]] = None,
    library_ids: Optional[set[str]] = None,
) -> list[SearchResult]:
    """Search Semantic Scholar. year_range: e.g. '2018-2024' or '2020-'."""
    params: dict = {
        "query": query,
        "limit": min(limit, 100),
        "fields": PAPER_FIELDS,
    }
    if year_range:
        params["year"] = year_range
    if fields_of_study:
        params["fieldsOfStudy"] = ",".join(fields_of_study)

    resp = await _request_with_retry("GET", f"{BASE_URL}/paper/search", params=params, headers=_headers())
    data = resp.json()

    return [_parse_search_result(p, library_ids) for p in data.get("data", [])]


async def get_paper_details(paper_id: str) -> dict:
    """Fetch full details. paper_id can be S2 ID, DOI:xxx, or ARXIV:xxx."""
    resp = await _request_with_retry("GET", f"{BASE_URL}/paper/{paper_id}", params={"fields": PAPER_FIELDS}, headers=_headers())
    return resp.json()


async def get_citations(
    paper_id: str, limit: int = 20, library_ids: Optional[set[str]] = None,
) -> list[SearchResult]:
    """Get papers that cite the given paper."""
    resp = await _request_with_retry("GET", f"{BASE_URL}/paper/{paper_id}/citations", params={"fields": CITATION_FIELDS, "limit": min(limit, 500)}, headers=_headers())
    data = resp.json()

    results = []
    for item in data.get("data", []):
        citing = item.get("citingPaper", {})
        if citing.get("paperId"):
            results.append(_parse_search_result(citing, library_ids))
    return results


async def get_references(
    paper_id: str, limit: int = 20, library_ids: Optional[set[str]] = None,
) -> list[SearchResult]:
    """Get papers referenced by the given paper."""
    resp = await _request_with_retry("GET", f"{BASE_URL}/paper/{paper_id}/references", params={"fields": CITATION_FIELDS, "limit": min(limit, 500)}, headers=_headers())
    data = resp.json()

    results = []
    for item in data.get("data", []):
        cited = item.get("citedPaper", {})
        if cited.get("paperId"):
            results.append(_parse_search_result(cited, library_ids))
    return results


async def find_related(
    paper_id: str, limit: int = 10, library_ids: Optional[set[str]] = None,
) -> list[SearchResult]:
    """Get S2 recommended papers based on a given paper."""
    resp = await _request_with_retry("POST", f"{RECS_URL}/papers/", json={"positivePaperIds": [paper_id]}, params={"fields": PAPER_FIELDS, "limit": min(limit, 100)}, headers=_headers())
    data = resp.json()

    return [_parse_search_result(p, library_ids) for p in data.get("recommendedPapers", [])]


async def search_by_author(
    author_name: str, limit: int = 20, library_ids: Optional[set[str]] = None,
) -> list[SearchResult]:
    """Search for papers by a specific author."""
    resp = await _request_with_retry("GET", f"{BASE_URL}/author/search", params={"query": author_name, "limit": 1}, headers=_headers())
    author_data = resp.json()

    authors = author_data.get("data", [])
    if not authors:
        return []

    author_id = authors[0]["authorId"]

    resp = await _request_with_retry("GET", f"{BASE_URL}/author/{author_id}/papers", params={"fields": PAPER_FIELDS, "limit": min(limit, 100)}, headers=_headers())
    data = resp.json()

    return [_parse_search_result(p, library_ids) for p in data.get("data", [])]


def parse_paper_to_library(data: dict) -> dict:
    """Convert S2 API response to fields suitable for Paper model."""
    authors = [
        Author(name=a.get("name", ""), author_id=a.get("authorId"))
        for a in (data.get("authors") or [])
    ]
    tldr = data.get("tldr")
    if isinstance(tldr, dict):
        tldr = tldr.get("text")

    ext_ids = data.get("externalIds") or {}
    pdf_info = data.get("openAccessPdf") or {}

    return {
        "id": data["paperId"],
        "title": data.get("title", ""),
        "authors": authors,
        "year": data.get("year"),
        "venue": data.get("venue"),
        "abstract": data.get("abstract"),
        "doi": ext_ids.get("DOI"),
        "arxiv_id": ext_ids.get("ArXiv"),
        "url": data.get("url"),
        "pdf_url": pdf_info.get("url"),
        "citation_count": data.get("citationCount"),
        "tldr": tldr,
    }
