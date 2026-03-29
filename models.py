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


class ExtractionResult(BaseModel):
    """Structured result from an internal LLM extraction call (Phase 0).

    Returned by tools/_llm_client.py:extract().  Carries the parsed data,
    confidence score (for cascade routing), model provenance, and token usage.
    """
    data: dict = Field(default_factory=dict)
    confidence_score: int = 100   # 0-100; <75 triggers cascade to stronger model
    model_used: str = ""
    cached: bool = False
    input_tokens: int = 0
    output_tokens: int = 0


class ProcessedText(BaseModel):
    """Fulltext after noise stripping and token-budget capping.

    Returned by tools/_text_processing.py:budget_text() and stored
    alongside tool outputs so callers can see what was trimmed.
    """
    content: str
    original_tokens: int
    processed_tokens: int
    sections_stripped: bool = False
    truncated: bool = False
    savings_pct: int = 0


# ---------------------------------------------------------------------------
# Strict extraction schemas (Phase 2.4)
# Tools using the internal LLM validate responses against these schemas.
# ---------------------------------------------------------------------------

class ExtractedMethodology(BaseModel):
    """Structured methodology extraction."""
    approach: str = Field(description="Core methodological approach")
    assumptions: list[str] = Field(default_factory=list, description="Key assumptions made")
    failure_modes: list[str] = Field(default_factory=list, description="Known failure modes")


class ExtractedMath(BaseModel):
    """Structured math framework extraction."""
    equations: list[str] = Field(default_factory=list, description="Key equations in LaTeX")
    theorems: list[str] = Field(default_factory=list, description="Theorem statements")
    convergence: Optional[str] = Field(None, description="Convergence rate/bound if stated")


class ExtractedFindings(BaseModel):
    """Validated key findings extraction."""
    findings: list[str] = Field(min_length=1, max_length=10, description="Key findings")
    confidence_score: int = Field(ge=0, le=100, default=100)


class ExtractedQuality(BaseModel):
    """Validated quality assessment."""
    score: int = Field(ge=1, le=5, description="Quality score 1-5")
    notes: str = Field(description="Brief justification")
    confidence_score: int = Field(ge=0, le=100, default=100)


class StructuredClaim(BaseModel):
    """A single falsifiable claim extracted from a paper.

    Structured for algorithmic comparison — two claims can be compared
    by matching on (metric, dataset, conditions) and checking direction/value.
    """
    claim: str = Field(description="Natural language claim statement")
    metric: Optional[str] = Field(None, description="What is measured (e.g. accuracy, convergence rate, L2 error)")
    value: Optional[str] = Field(None, description="Reported value (e.g. '0.87', '1/sqrt(N)', 'O(h^2)')")
    dataset: Optional[str] = Field(None, description="Dataset or problem setting (e.g. 'CIFAR-10', '100-dim Black-Scholes')")
    conditions: Optional[str] = Field(None, description="Key conditions/assumptions (e.g. 'batch_size=128', 'Lipschitz driver')")
    direction: Optional[str] = Field(None, description="Comparison direction if applicable (e.g. 'A > B', 'improves', 'fails')")
    claim_type: str = Field(default="result", description="One of: result, methodology, assumption, limitation")


class ExtractedClaims(BaseModel):
    """Validated structured claims extraction from a paper."""
    claims: list[StructuredClaim] = Field(default_factory=list)
    confidence_score: int = Field(ge=0, le=100, default=100)


# Map task names to their validation schemas
EXTRACTION_SCHEMAS: dict[str, type[BaseModel]] = {
    "extract_findings": ExtractedFindings,
    "assess_quality": ExtractedQuality,
    "extract_claims": ExtractedClaims,
}


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
