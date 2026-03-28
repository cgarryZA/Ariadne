"""Pydantic models for the literature review system."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class ReadingStatus(str, Enum):
    UNREAD = "unread"
    SKIMMED = "skimmed"
    READ = "read"
    DEEP_READ = "deep_read"


class Move(str, Enum):
    """Oxford three-move literature review classification."""
    FOUNDATIONAL = "foundational"
    GAP = "gap"
    PARALLEL = "parallel"


class Author(BaseModel):
    name: str
    author_id: Optional[str] = None


class Paper(BaseModel):
    id: str
    title: str
    authors: list[Author] = Field(default_factory=list)
    year: Optional[int] = None
    venue: Optional[str] = None
    abstract: Optional[str] = None
    doi: Optional[str] = None
    arxiv_id: Optional[str] = None
    url: Optional[str] = None
    pdf_url: Optional[str] = None
    pdf_local_path: Optional[str] = None
    citation_count: Optional[int] = None
    tldr: Optional[str] = None
    bibtex: Optional[str] = None
    added_at: Optional[datetime] = None

    # User-managed fields
    pillar: Optional[str] = None  # Free-text — configured per review via setup_review()
    tags: list[str] = Field(default_factory=list)
    status: ReadingStatus = ReadingStatus.UNREAD
    relevance: Optional[int] = Field(None, ge=1, le=5)
    notes: Optional[str] = None

    # Structured extraction columns ("Elicit" features)
    methodology: Optional[str] = None
    limitations: Optional[str] = None
    math_framework: Optional[str] = None
    convergence_bounds: Optional[str] = None

    # Section/chapter mapping
    chapter: Optional[str] = None

    # Claude-generated analysis (persisted across sessions)
    summary: Optional[str] = None
    key_findings: list[str] = Field(default_factory=list)
    quality_score: Optional[int] = Field(None, ge=1, le=5)
    quality_notes: Optional[str] = None
    move: Optional[Move] = None
    themes: list[str] = Field(default_factory=list)


class Citation(BaseModel):
    citing_id: str
    cited_id: str
    is_influential: bool = False


class SearchResult(BaseModel):
    """A paper returned from an API search (not yet necessarily in library)."""
    id: str
    title: str
    authors: list[Author] = Field(default_factory=list)
    year: Optional[int] = None
    venue: Optional[str] = None
    abstract: Optional[str] = None
    citation_count: Optional[int] = None
    tldr: Optional[str] = None
    is_open_access: bool = False
    in_library: bool = False
