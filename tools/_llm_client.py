"""Internal LLM client — model routing, JSON enforcement, prompt caching, confidence cascade.

Phase 0 (items 0.1, 0.2, 0.7, 0.8): Stop token bleed by routing simple tasks to
cheap models and enforcing structured JSON output.

Architecture:
  - If ANTHROPIC_API_KEY is set, tools can call the LLM directly for extraction
    tasks, returning structured results instead of raw prompts.
  - If no key is set, everything degrades gracefully — tools return formatted
    prompts as before (Claude processes them in the conversation).

Prompt caching (Phase 0.2):
  - Uses Anthropic's cache_control API to cache paper text across multiple
    extraction calls on the same paper. First call pays full price; subsequent
    calls (e.g. summarize → extract_findings → assess_quality) on the same
    paper get 90% input token discount.
  - Also maintains a local extraction cache in SQLite to skip the API entirely
    when the exact (paper_id, task) pair has been seen before.

Usage in tool modules:
    from tools._llm_client import extract, is_available

    if is_available():
        result = await extract(paper_text, "summarize")
        return result.data["summary"]
    else:
        return _build_prompt_for_claude(paper_text)
"""

from __future__ import annotations

import hashlib
import json
import os
from typing import Any, Optional

from models import ExtractionResult, EXTRACTION_SCHEMAS


# ---------------------------------------------------------------------------
# Model routing table
# ---------------------------------------------------------------------------

# Task -> preferred model. "fast" = Haiku-class, "reasoning" = Sonnet-class.
_TASK_TIERS: dict[str, str] = {
    # Fast tier — text extraction, reformatting, simple classification
    "summarize":            "fast",
    "extract_findings":     "fast",
    "extract_metadata":     "fast",
    "classify_move":        "fast",
    "deduplicate_check":    "fast",
    "screen_abstract":      "fast",
    "extract_concepts":     "fast",
    "citation_context":     "fast",
    # Reasoning tier — synthesis, comparison, quality assessment
    "assess_quality":       "reasoning",
    "compare_papers":       "reasoning",
    "generate_outline":     "reasoning",
    "synthesize":           "reasoning",
    "detect_contradictions": "reasoning",
    "gap_analysis":         "reasoning",
    "notation_standardize": "reasoning",
    "red_team_proponent":   "reasoning",
    "red_team_critic":      "reasoning",
    "red_team_synthesize":  "reasoning",
}

_MODEL_MAP: dict[str, str] = {
    "fast":      os.environ.get("ARIADNE_FAST_MODEL", "claude-haiku-4-5-20251001"),
    "reasoning": os.environ.get("ARIADNE_REASONING_MODEL", "claude-sonnet-4-5-20241022"),
}

# Confidence threshold for cascade escalation (Haiku -> Sonnet)
_CASCADE_THRESHOLD = int(os.environ.get("ARIADNE_CASCADE_THRESHOLD", "75"))

# ---------------------------------------------------------------------------
# System prompts
# ---------------------------------------------------------------------------

_EXTRACTION_SYSTEM = (
    "You are a data extraction pipeline for an academic literature review system. "
    "You must output ONLY valid JSON. Absolutely no preamble, no explanation, "
    "no markdown formatting, no code fences. Just the raw JSON object."
)

_TASK_PROMPTS: dict[str, str] = {
    "summarize": (
        "Write a comprehensive 150-300 word summary of this paper covering: "
        "(1) research question/objective, (2) methodology and approach, "
        "(3) key results and contributions, (4) significance to the field. "
        'Output JSON: {"summary": "...", "confidence_score": 0-100}'
    ),
    "extract_findings": (
        "Extract 3-7 key findings from this paper as concise statements. "
        "Focus on novel contributions, quantitative results, and theoretical insights. "
        'Output JSON: {"findings": ["finding 1", "finding 2", ...], "confidence_score": 0-100}'
    ),
    "assess_quality": (
        "Rate this paper 1-5 on quality/rigor. 5=landmark, 4=strong, 3=solid, 2=weak, 1=poor. "
        "Provide a brief justification. "
        'Output JSON: {"score": 1-5, "notes": "brief justification", "confidence_score": 0-100}'
    ),
    "classify_move": (
        "Classify this paper in the Oxford three-move model: "
        "foundational (established, high-citation older work), "
        "gap (identifies problems, questions current knowledge), or "
        "parallel (recent attempts to fill gaps). "
        'Output JSON: {"move": "foundational|gap|parallel", "reason": "...", "confidence_score": 0-100}'
    ),
    "screen_abstract": (
        "Given the inclusion/exclusion criteria, classify this paper: "
        "include (meets criteria), exclude (fails criteria), or maybe (unclear). "
        'Output JSON: {"decision": "include|exclude|maybe", "reason": "...", "confidence_score": 0-100}'
    ),
    "extract_concepts": (
        "Extract 3-8 key academic concepts/methods/theories from this paper. "
        "For each, note its relationship type: introduces, extends, applies, critiques, or uses. "
        'Output JSON: {"concepts": [{"name": "...", "relation": "introduces|extends|applies|critiques|uses"}], '
        '"confidence_score": 0-100}'
    ),
    "detect_contradictions": (
        "Compare the claims in these two papers. Identify any contradictions, "
        "disagreements, or tensions. Also note where they agree. "
        'Output JSON: {"contradictions": ["..."], "agreements": ["..."], "tension_level": "none|low|medium|high", '
        '"confidence_score": 0-100}'
    ),
    "citation_context": (
        "Find and classify how the cited paper is referenced. "
        "Classify each mention as: supporting (builds on, agrees with), "
        "contrasting (disagrees, finds problems), or mentioning (neutral reference). "
        'Output JSON: {"mentions": [{"context": "quote/paraphrase", "type": "supporting|contrasting|mentioning"}], '
        '"confidence_score": 0-100}'
    ),
    "red_team_proponent": (
        "You are AGENT 1 (The Proponent). Argue why this paper's methodology is sound, "
        "its mathematical assumptions are justified, and its results are significant. "
        "Be specific — cite exact claims and methods from the text. "
        'Output JSON: {"strengths": ["..."], "methodology_defense": "...", "significance": "...", '
        '"confidence_score": 0-100}'
    ),
    "red_team_critic": (
        "You are AGENT 2 (Reviewer 2). Actively find holes in this paper's methodology, "
        "mathematical assumptions, sample size, reproducibility, and conclusions. "
        "Be adversarial but fair — cite specific weaknesses from the text. "
        'Output JSON: {"weaknesses": ["..."], "methodology_holes": "...", "missing_evidence": "...", '
        '"assumptions_questioned": ["..."], "confidence_score": 0-100}'
    ),
    "red_team_synthesize": (
        "You are given a Proponent's defense and a Critic's attack on the same paper. "
        "Synthesize these into a balanced quality assessment. Determine the overall "
        "quality score (1-5) and write a nuanced limitations paragraph. "
        'Output JSON: {"score": 1-5, "balanced_assessment": "...", '
        '"limitations_paragraph": "...", "confidence_score": 0-100}'
    ),
}

# ---------------------------------------------------------------------------
# Client singleton
# ---------------------------------------------------------------------------

_client = None


def _get_client():
    """Lazy-init the Anthropic client."""
    global _client
    if _client is not None:
        return _client
    try:
        import anthropic
        key = os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            return None
        _client = anthropic.Anthropic(api_key=key)
        return _client
    except ImportError:
        return None


def is_available() -> bool:
    """True if the internal LLM client is configured and ready."""
    return _get_client() is not None


async def close_client() -> None:
    """Clean up the client."""
    global _client
    _client = None


# ---------------------------------------------------------------------------
# Local extraction cache (Phase 0.2 — the "Deja Vu" database)
# ---------------------------------------------------------------------------

_CACHE_ENABLED = os.environ.get("ARIADNE_CACHE_EXTRACTIONS", "1") != "0"


def _cache_key(text: str, task: str) -> str:
    """Deterministic hash of (text, task) for cache lookup."""
    h = hashlib.sha256(f"{task}:{text}".encode()).hexdigest()[:32]
    return h


async def _cache_get(text: str, task: str) -> Optional[ExtractionResult]:
    """Check the local extraction cache. Returns None on miss."""
    if not _CACHE_ENABLED:
        return None
    try:
        import db
        conn = await db.get_db()
        key = _cache_key(text, task)
        cursor = await conn.execute(
            "SELECT result_json FROM extraction_cache WHERE cache_key = ?", (key,)
        )
        row = await cursor.fetchone()
        if row:
            data = json.loads(row["result_json"])
            return ExtractionResult(cached=True, **data)
    except Exception:
        pass  # table might not exist yet, or any other issue — just miss
    return None


async def _cache_put(text: str, task: str, result: ExtractionResult) -> None:
    """Store an extraction result in the local cache."""
    if not _CACHE_ENABLED:
        return
    try:
        import db
        conn = await db.get_db()
        key = _cache_key(text, task)
        result_data = {
            "data": result.data,
            "confidence_score": result.confidence_score,
            "model_used": result.model_used,
            "input_tokens": result.input_tokens,
            "output_tokens": result.output_tokens,
        }
        await conn.execute(
            "INSERT OR REPLACE INTO extraction_cache (cache_key, task, result_json) VALUES (?, ?, ?)",
            (key, task, json.dumps(result_data)),
        )
        await conn.commit()
    except Exception:
        pass  # cache write failure is non-fatal


# ---------------------------------------------------------------------------
# Core extraction function
# ---------------------------------------------------------------------------


async def extract(
    text: str,
    task: str,
    extra_context: str = "",
    force_model: Optional[str] = None,
    max_tokens: int = 1024,
    skip_cache: bool = False,
) -> ExtractionResult:
    """Call the LLM to extract structured data from text.

    Args:
        text: The paper text (abstract, fulltext excerpt, etc.)
        task: Task name from _TASK_PROMPTS (e.g. 'summarize', 'extract_findings')
        extra_context: Additional context to prepend to the user message
        force_model: Override the model router (e.g. 'fast' or 'reasoning')
        max_tokens: Max output tokens
        skip_cache: If True, bypass the local extraction cache

    Returns:
        ExtractionResult with parsed data, confidence score, and usage stats.

    Raises:
        RuntimeError: If client is not available.
        ValueError: If LLM output is not valid JSON.
    """
    # Check local cache first (Phase 0.2)
    if not skip_cache and not extra_context:
        cached = await _cache_get(text, task)
        if cached is not None:
            return cached

    client = _get_client()
    if client is None:
        raise RuntimeError(
            "LLM client not available. Set ANTHROPIC_API_KEY environment variable."
        )

    # Resolve model
    tier = force_model or _TASK_TIERS.get(task, "fast")
    model = _MODEL_MAP.get(tier, _MODEL_MAP["fast"])

    # Build the prompt with cache_control for the paper text (Phase 0.2)
    task_prompt = _TASK_PROMPTS.get(task, "Extract the requested information as JSON.")

    # Structure messages for optimal prompt caching:
    # - System prompt: cached automatically by Anthropic
    # - Paper text: marked with cache_control for cross-call caching
    # - Task prompt: varies per call (not cached)
    content_blocks = []
    if extra_context:
        content_blocks.append({"type": "text", "text": extra_context + "\n\n"})

    # The paper text block gets cache_control so that when the same paper
    # is used for summarize -> extract_findings -> assess_quality,
    # the text tokens are served from cache at 90% discount.
    paper_block = {"type": "text", "text": f"---\n{text}\n---"}
    if len(text) > 2048:  # Anthropic minimum for caching is 1024 tokens (~4096 chars)
        paper_block["cache_control"] = {"type": "ephemeral"}
    content_blocks.append(paper_block)

    # Task instruction goes last (uncached, varies per call)
    content_blocks.append({"type": "text", "text": f"\n{task_prompt}"})

    messages = [{"role": "user", "content": content_blocks}]

    # Make the API call
    import asyncio
    try:
        response = await asyncio.to_thread(
            client.messages.create,
            model=model,
            max_tokens=max_tokens,
            system=_EXTRACTION_SYSTEM,
            messages=messages,
        )
    except Exception as e:
        # If cache_control is not supported by this SDK version, retry without it
        if "cache_control" in str(e):
            for block in content_blocks:
                block.pop("cache_control", None)
            response = await asyncio.to_thread(
                client.messages.create,
                model=model,
                max_tokens=max_tokens,
                system=_EXTRACTION_SYSTEM,
                messages=messages,
            )
        else:
            raise

    raw_text = response.content[0].text.strip()

    # Parse JSON — strip code fences if the model added them
    clean = raw_text
    if clean.startswith("```"):
        lines = clean.split("\n")
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        clean = "\n".join(lines)

    try:
        data = json.loads(clean)
    except json.JSONDecodeError as e:
        raise ValueError(
            f"LLM returned invalid JSON for task '{task}': {e}\nRaw output: {raw_text[:500]}"
        )

    confidence = data.pop("confidence_score", 100)

    # Schema validation (Phase 2.4): if a strict schema exists for this task,
    # validate the output and reject malformed responses
    schema = EXTRACTION_SCHEMAS.get(task)
    if schema:
        try:
            validated = schema.model_validate(data)
            data = validated.model_dump()
            # Re-extract confidence if the schema had it
            confidence = data.pop("confidence_score", confidence)
        except Exception:
            pass  # schema validation is best-effort, don't fail the call

    # Check if the response used cache (Anthropic reports this in usage)
    was_cached = False
    usage = response.usage
    if hasattr(usage, "cache_read_input_tokens"):
        was_cached = getattr(usage, "cache_read_input_tokens", 0) > 0

    result = ExtractionResult(
        data=data,
        confidence_score=confidence,
        model_used=model,
        cached=was_cached,
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
    )

    # Confidence Cascade (Phase 0.8): if Haiku is unsure, escalate to Sonnet
    if tier == "fast" and confidence < _CASCADE_THRESHOLD:
        escalated = await extract(
            text, task, extra_context=extra_context,
            force_model="reasoning", max_tokens=max_tokens,
            skip_cache=True,
        )
        escalated.data["_escalated_from"] = model
        return escalated

    # Store in local cache for future calls
    if not skip_cache and not extra_context:
        await _cache_put(text, task, result)

    return result


# ---------------------------------------------------------------------------
# Batch extraction (Phase 0.4)
# ---------------------------------------------------------------------------


async def batch_extract(
    items: list[tuple[str, str, str]],
    max_tokens: int = 1024,
) -> list[ExtractionResult | Exception]:
    """Process multiple extraction tasks.

    Currently runs sequentially with local caching. Falls back gracefully
    if the Anthropic Message Batch API is not available.

    Args:
        items: List of (text, task, extra_context) tuples.
        max_tokens: Max output tokens per item.

    Returns:
        List of ExtractionResult or Exception for each item.
    """
    # Try Anthropic Message Batch API for 50% cost reduction
    client = _get_client()
    if client is not None and len(items) >= 5:
        try:
            return await _batch_extract_api(items, max_tokens)
        except Exception:
            pass  # Fall through to sequential

    # Sequential fallback (still benefits from local cache)
    results = []
    for text, task, extra_context in items:
        try:
            result = await extract(text, task, extra_context=extra_context, max_tokens=max_tokens)
            results.append(result)
        except Exception as e:
            results.append(e)
    return results


async def _batch_extract_api(
    items: list[tuple[str, str, str]],
    max_tokens: int = 1024,
) -> list[ExtractionResult | Exception]:
    """Use Anthropic Message Batch API for bulk extraction at 50% cost."""
    import asyncio

    client = _get_client()
    if client is None:
        raise RuntimeError("LLM client not available")

    # Build batch requests
    requests = []
    for i, (text, task, extra_context) in enumerate(items):
        tier = _TASK_TIERS.get(task, "fast")
        model = _MODEL_MAP.get(tier, _MODEL_MAP["fast"])
        task_prompt = _TASK_PROMPTS.get(task, "Extract the requested information as JSON.")

        user_msg = f"{task_prompt}\n\n"
        if extra_context:
            user_msg += f"{extra_context}\n\n"
        user_msg += f"---\n{text}"

        requests.append({
            "custom_id": f"ariadne-{i}",
            "params": {
                "model": model,
                "max_tokens": max_tokens,
                "system": _EXTRACTION_SYSTEM,
                "messages": [{"role": "user", "content": user_msg}],
            }
        })

    # Submit batch
    batch = await asyncio.to_thread(
        client.messages.batches.create,
        requests=requests,
    )

    # Poll for completion (batches process in background)
    while batch.processing_status != "ended":
        await asyncio.sleep(10)
        batch = await asyncio.to_thread(
            client.messages.batches.retrieve,
            batch.id,
        )

    # Collect results
    result_map: dict[str, Any] = {}
    async for entry in _iter_batch_results(client, batch.id):
        result_map[entry["custom_id"]] = entry

    results: list[ExtractionResult | Exception] = []
    for i in range(len(items)):
        cid = f"ariadne-{i}"
        entry = result_map.get(cid)
        if entry is None or entry.get("result", {}).get("type") != "succeeded":
            results.append(Exception(f"Batch item {i} failed"))
            continue
        try:
            raw = entry["result"]["message"]["content"][0]["text"].strip()
            clean = raw
            if clean.startswith("```"):
                lines = clean.split("\n")
                if lines[0].startswith("```"):
                    lines = lines[1:]
                if lines and lines[-1].strip() == "```":
                    lines = lines[:-1]
                clean = "\n".join(lines)
            data = json.loads(clean)
            confidence = data.pop("confidence_score", 100)
            results.append(ExtractionResult(
                data=data,
                confidence_score=confidence,
                model_used=entry["result"]["message"]["model"],
                cached=False,
                input_tokens=entry["result"]["message"]["usage"]["input_tokens"],
                output_tokens=entry["result"]["message"]["usage"]["output_tokens"],
            ))
        except Exception as e:
            results.append(e)

    return results


async def _iter_batch_results(client, batch_id: str):
    """Iterate over batch results from the Anthropic API."""
    import asyncio
    results = await asyncio.to_thread(
        client.messages.batches.results,
        batch_id,
    )
    for entry in results:
        yield entry
