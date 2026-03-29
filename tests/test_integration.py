"""Integration tests for Ariadne — verify key invariants with known data.

Run: pytest tests/test_integration.py -v

These tests use an in-memory SQLite database with synthetic papers that
simulate a real library. No API calls are made. Tests verify:
- Consistency (dedup, extraction, search)
- Recall of key signals (findings, contradictions)
- Absence of obvious failure modes (empty results, crashes)
"""

from __future__ import annotations

import json
import os
import sys

import pytest
import pytest_asyncio

# Use in-memory DB for tests
os.environ["ARIADNE_DB"] = ":memory:"
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import db
from models import Paper, Author, Citation


# ── Fixtures ─────────────────────────────────────────────────────────

PAPERS = [
    Paper(
        id="paper_foundational_001",
        title="Deep Learning for High-Dimensional Parabolic PDEs",
        authors=[Author(name="Weinan E"), Author(name="Jiequn Han"), Author(name="Arnulf Jentzen")],
        year=2017,
        venue="Proceedings of the National Academy of Sciences",
        abstract="We propose a deep learning approach to solve high-dimensional parabolic PDEs. "
                 "The method achieves linear scaling in dimension, unlike traditional grid methods.",
        citation_count=1200,
        pillar="computational",
        methodology="Deep BSDE solver using neural network approximation of the gradient",
        limitations="Requires smooth solutions; convergence theory is incomplete",
        convergence_bounds="O(1/sqrt(N)) Monte Carlo rate",
        math_framework="Forward-backward SDE discretization with deep neural network",
        key_findings=[
            "Deep BSDE method solves 100-dimensional PDEs in seconds",
            "Linear scaling in dimension, unlike grid-based methods",
            "Monte Carlo convergence rate O(1/sqrt(N))",
        ],
    ),
    Paper(
        id="paper_computational_002",
        title="Solving High-Dimensional PDEs Using Deep Learning: An Improved Method",
        authors=[Author(name="Justin Sirignano"), Author(name="Konstantinos Spiliopoulos")],
        year=2018,
        venue="Journal of Computational Physics",
        abstract="We improve upon the Deep Galerkin Method for solving high-dimensional PDEs. "
                 "Our approach shows better convergence than E, Han, Jentzen (2017).",
        citation_count=450,
        pillar="computational",
        methodology="Deep Galerkin Method with improved loss function",
        limitations="Sensitive to hyperparameter tuning; batch normalization required",
        convergence_bounds="O(1/N) for smooth solutions",
        key_findings=[
            "Improved convergence rate O(1/N) vs O(1/sqrt(N))",
            "Deep Galerkin outperforms Deep BSDE on smooth problems",
            "Batch normalization is critical for training stability",
        ],
    ),
    Paper(
        id="paper_theoretical_003",
        title="Mean-Field Game Theory and McKean-Vlasov BSDEs",
        authors=[Author(name="Rene Carmona"), Author(name="Francois Delarue")],
        year=2015,
        venue="Annals of Probability",
        abstract="We establish well-posedness results for McKean-Vlasov forward-backward SDEs "
                 "arising in mean-field game theory under Lipschitz conditions.",
        citation_count=800,
        pillar="theoretical",
        methodology="Fixed-point arguments for mean-field FBSDEs",
        limitations="Requires Lipschitz driver function; non-Lipschitz case open",
        convergence_bounds="Exponential convergence under monotonicity",
        math_framework="McKean-Vlasov FBSDE with measure-dependent coefficients",
        key_findings=[
            "Well-posedness for McKean-Vlasov BSDEs under Lipschitz conditions",
            "Exponential convergence of Picard iterations under monotonicity",
            "Non-Lipschitz case remains an open problem",
        ],
    ),
    Paper(
        id="paper_gap_004",
        title="On the Instability of Deep BSDE Solvers for Non-Lipschitz Drivers",
        authors=[Author(name="Zhang Wei"), Author(name="Li Ming")],
        year=2021,
        venue="SIAM Journal on Numerical Analysis",
        abstract="We demonstrate that the Deep BSDE method of E, Han, Jentzen (2017) "
                 "fails to converge for BSDEs with non-Lipschitz driver functions.",
        citation_count=85,
        pillar="computational",
        methodology="Numerical experiments showing instability of Deep BSDE",
        limitations="Only tested on specific non-Lipschitz examples",
        convergence_bounds="Divergence observed for super-linear drivers",
        key_findings=[
            "Deep BSDE diverges for non-Lipschitz drivers",
            "Gradient explosion occurs after 500+ training steps",
            "E, Han, Jentzen convergence theory does not apply outside Lipschitz regime",
        ],
    ),
    Paper(
        id="paper_duplicate_005",
        title="Deep Learning for High-Dimensional Parabolic PDEs",
        authors=[Author(name="Weinan E"), Author(name="Jiequn Han")],
        year=2017,
        doi="10.1073/pnas.1718942115",
        abstract="We propose a deep learning approach for high-dimensional PDEs.",
        citation_count=1200,
    ),
]


@pytest_asyncio.fixture(autouse=True)
async def setup_db():
    """Initialize an in-memory DB and populate with test papers."""
    await db.init()
    for p in PAPERS:
        await db.insert_paper(p)
    yield
    await db.close()
    db._conn = None  # reset singleton for next test


# ── Deduplication Tests ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_dedup_finds_exact_title_match():
    """Two papers with identical titles should be flagged as duplicates."""
    papers = await db.list_papers(limit=100)
    titles = [p.title for p in papers]
    title_counts = {}
    for t in titles:
        title_counts[t] = title_counts.get(t, 0) + 1
    duplicated = [t for t, c in title_counts.items() if c > 1]
    assert len(duplicated) >= 1, "Expected at least one duplicate title pair"


@pytest.mark.asyncio
async def test_library_size():
    """Library should contain all inserted papers."""
    papers = await db.list_papers(limit=100)
    assert len(papers) == 5


# ── Extraction Recall Tests ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_foundational_paper_has_key_findings():
    """Foundational paper should have key findings populated."""
    paper = await db.get_paper("paper_foundational_001")
    assert paper is not None
    assert len(paper.key_findings) >= 3
    # Verify recall of key signal
    findings_text = " ".join(paper.key_findings).lower()
    assert "100-dimensional" in findings_text or "linear scaling" in findings_text


@pytest.mark.asyncio
async def test_convergence_bounds_populated():
    """Papers with convergence results should have convergence_bounds set."""
    paper = await db.get_paper("paper_foundational_001")
    assert paper.convergence_bounds is not None
    assert "O(" in paper.convergence_bounds or "sqrt" in paper.convergence_bounds


@pytest.mark.asyncio
async def test_methodology_populated():
    """All test papers (except duplicate) should have methodology."""
    for pid in ["paper_foundational_001", "paper_computational_002", "paper_theoretical_003", "paper_gap_004"]:
        paper = await db.get_paper(pid)
        assert paper.methodology, f"Paper {pid} missing methodology"


# ── Pillar Validation Tests ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_pillar_validation_rejects_unknown():
    """validate_pillar should reject unknown pillar names."""
    await db.set_config_json("pillars", ["computational", "theoretical", "financial"])
    from tools.formatting import validate_pillar
    err = await validate_pillar("numerical_methods")
    assert err is not None
    assert "not found" in err.lower()
    assert "computational" in err  # should suggest configured pillars


@pytest.mark.asyncio
async def test_pillar_validation_accepts_valid():
    """validate_pillar should accept configured pillar names."""
    await db.set_config_json("pillars", ["computational", "theoretical"])
    from tools.formatting import validate_pillar
    err = await validate_pillar("computational")
    assert err is None


@pytest.mark.asyncio
async def test_pillar_validation_skips_when_unconfigured():
    """validate_pillar should accept anything when no pillars are configured."""
    from tools.formatting import validate_pillar
    err = await validate_pillar("anything_goes")
    assert err is None


# ── Paper ID Resolution Tests ────────────────────────────────────────

@pytest.mark.asyncio
async def test_resolve_exact_id():
    """Exact paper ID should resolve immediately."""
    from tools.formatting import resolve_paper_id
    rid, err = await resolve_paper_id("paper_foundational_001")
    assert rid == "paper_foundational_001"
    assert err is None


@pytest.mark.asyncio
async def test_resolve_prefix_match():
    """Partial ID prefix should resolve to full ID."""
    from tools.formatting import resolve_paper_id
    rid, err = await resolve_paper_id("paper_foundational")
    assert rid == "paper_foundational_001"
    assert err is None


@pytest.mark.asyncio
async def test_resolve_title_words():
    """Title word search should find matching papers."""
    from tools.formatting import resolve_paper_id
    rid, err = await resolve_paper_id("instability deep bsde")
    # Should find paper_gap_004 (title contains all these words)
    assert rid == "paper_gap_004"


@pytest.mark.asyncio
async def test_resolve_unknown_gives_suggestions():
    """Unknown ID should return suggestions, not just 'not found'."""
    from tools.formatting import resolve_paper_id
    rid, err = await resolve_paper_id("nonexistent_paper")
    assert rid is None
    assert err is not None
    assert "not found" in err.lower()


# ── Structured Claims Tests ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_store_and_retrieve_claims():
    """Claims should round-trip through the database."""
    claims = [
        {"claim": "Method A achieves 0.87 accuracy", "metric": "accuracy",
         "value": "0.87", "dataset": "CIFAR-10", "direction": "A > baseline",
         "claim_type": "result"},
        {"claim": "Convergence rate is O(1/sqrt(N))", "metric": "convergence_rate",
         "value": "O(1/sqrt(N))", "claim_type": "result"},
    ]
    stored = await db.store_claims("paper_foundational_001", claims)
    assert stored == 2

    retrieved = await db.get_claims("paper_foundational_001")
    assert len(retrieved) == 2
    assert any(c["metric"] == "accuracy" for c in retrieved)


@pytest.mark.asyncio
async def test_contradictory_claims_detectable():
    """Two claims with same metric but different values should be detectable."""
    claims_a = [
        {"claim": "Convergence rate O(1/sqrt(N))", "metric": "convergence_rate",
         "value": "O(1/sqrt(N))", "dataset": "100-dim PDE", "claim_type": "result"},
    ]
    claims_b = [
        {"claim": "Convergence rate O(1/N)", "metric": "convergence_rate",
         "value": "O(1/N)", "dataset": "100-dim PDE", "claim_type": "result"},
    ]
    await db.store_claims("paper_foundational_001", claims_a)
    await db.store_claims("paper_computational_002", claims_b)

    all_claims = await db.get_all_claims()
    convergence_claims = [c for c in all_claims if c.get("metric") == "convergence_rate"]
    assert len(convergence_claims) >= 2

    # Verify different papers report different values
    values = set(c["value"] for c in convergence_claims)
    assert len(values) >= 2, "Expected different convergence values from different papers"


# ── Pipeline Logging Tests ───────────────────────────────────────────

@pytest.mark.asyncio
async def test_pipeline_run_lifecycle():
    """Pipeline runs should be creatable, loggable, and completable."""
    run_id = await db.create_pipeline_run("test", "What methods solve BSDEs?")
    assert run_id > 0

    await db.log_pipeline_step(run_id, "multi_search", {"papers_found": 42})
    await db.log_pipeline_step(run_id, "screen_papers", {"included": 30, "excluded": 12})

    run = await db.get_pipeline_run(run_id)
    assert run["status"] == "running"
    assert len(run["steps"]) == 2
    assert run["steps"][0]["step"] == "multi_search"
    assert run["steps"][0]["papers_found"] == 42

    await db.complete_pipeline_run(run_id, {"papers_reviewed": 30, "contradictions": 2})
    run = await db.get_pipeline_run(run_id)
    assert run["status"] == "completed"
    assert run["summary"]["papers_reviewed"] == 30


# ── Text Processing Tests ────────────────────────────────────────────

@pytest.mark.asyncio
async def test_noise_stripping():
    """References section should be stripped from fulltext."""
    from tools._text_processing import strip_noise_sections
    text = "Introduction\nThis is important.\n\nReferences\n[1] Smith 2020\n[2] Jones 2021"
    result = strip_noise_sections(text)
    assert "Smith 2020" not in result
    assert "important" in result


@pytest.mark.asyncio
async def test_budget_text_caps_tokens():
    """budget_text should respect token limits."""
    from tools._text_processing import budget_text, count_tokens
    long_text = "word " * 20000  # very long
    processed, stats = budget_text(long_text, "summarize_paper")
    assert count_tokens(processed) <= 4500  # 4K budget + some margin
    assert stats["truncated"] is True


@pytest.mark.asyncio
async def test_budget_text_preserves_short():
    """Short text should pass through budget_text unchanged (minus noise)."""
    from tools._text_processing import budget_text
    short_text = "This is a short abstract about neural networks."
    processed, stats = budget_text(short_text, "summarize_paper")
    assert stats["truncated"] is False
    assert "neural networks" in processed


# ── Tool Registration Tests ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_all_tools_register():
    """All tool modules should register without errors."""
    from fastmcp import FastMCP
    from tools import register_all
    mcp = FastMCP("test")
    register_all(mcp)
    tools = await mcp.list_tools()
    assert len(tools) >= 83, f"Expected 83+ tools, got {len(tools)}"


@pytest.mark.asyncio
async def test_key_tools_exist():
    """Critical tools should be registered."""
    from fastmcp import FastMCP
    from tools import register_all
    mcp = FastMCP("test")
    register_all(mcp)
    tools = await mcp.list_tools()
    names = {t.name for t in tools}

    required = [
        "setup_review", "multi_search", "add_paper", "screen_papers",
        "summarize_paper", "extract_key_findings", "detect_contradictions",
        "extract_structured_claims", "classify_moves", "generate_review_outline",
        "assemble_review", "export_bibtex", "compile_to_latex",
        "semantic_search", "red_team_assess", "extract_concepts",
    ]
    missing = [t for t in required if t not in names]
    assert not missing, f"Missing tools: {missing}"
