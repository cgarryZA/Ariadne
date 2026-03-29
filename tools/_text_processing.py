"""Text processing utilities — token budget management and noise stripping.

Phase 0 (items 0.3 + 0.6): Context window management and heuristic pre-filtering.

Key functions:
  strip_noise_sections(text)         — remove References, Acknowledgements, Appendix
  section_slice(text, tool_name)     — return only sections relevant to the task
  budget_text(text, tool_name)       — strip + slice + hard token cap (main entry point)
  count_tokens(text)                 — tiktoken count, falls back to char/4 estimate
"""

from __future__ import annotations

import re

# ---------------------------------------------------------------------------
# Token counting — tiktoken preferred, graceful fallback
# ---------------------------------------------------------------------------

try:
    import tiktoken as _tiktoken
    _enc = _tiktoken.get_encoding("cl100k_base")

    def count_tokens(text: str) -> int:
        return len(_enc.encode(text))

except ImportError:
    def count_tokens(text: str) -> int:  # type: ignore[misc]
        """Rough estimate: ~4 chars per token (good enough for budgeting)."""
        return max(1, len(text) // 4)


# ---------------------------------------------------------------------------
# Token budgets per tool (generous but bounded)
# ---------------------------------------------------------------------------

# How many tokens to send to Claude per tool invocation (fulltext portion only)
TOOL_BUDGETS: dict[str, int] = {
    "summarize_paper":      4_000,
    "extract_key_findings": 3_000,
    "assess_quality":       2_500,
    "get_fulltext":        12_000,  # explicit retrieval — user asked for it
    "default":              5_000,
}

# ---------------------------------------------------------------------------
# Noise section patterns — always strip, never useful for extraction
# ---------------------------------------------------------------------------

_NOISE_HEADERS = [
    r"references",
    r"bibliography",
    r"acknowledgements?",
    r"appendix\b",
    r"appendices",
    r"supplementary\s+(?:material|data|information|methods?)",
    r"author\s+contributions?",
    r"conflict\s+of\s+interest\s*(?:statement)?",
    r"funding\s*(?:information|sources?)?",
    r"data\s+availability\s*(?:statement)?",
    r"ethics\s+(?:statement|declaration|approval)",
    r"declaration\s+of\s+(?:competing\s+)?interest",
    r"disclosures?",
    r"abbreviations",
    r"glossary",
]

# Matches a noise header as a standalone line (with optional leading number like "5.")
_NOISE_RE = re.compile(
    r"(?m)^[ \t]*(?:\d+\.?\s+)?(?:" + "|".join(_NOISE_HEADERS) + r")\s*$",
    re.IGNORECASE,
)

# Also match "References\n=====" or "## References" style headers
_NOISE_MARKDOWN_RE = re.compile(
    r"(?m)^(?:#{1,4}\s+|={3,}\s*\n)?(?:" + "|".join(_NOISE_HEADERS) + r")\s*(?:\n={3,})?$",
    re.IGNORECASE,
)


def strip_noise_sections(text: str) -> str:
    """Remove References, Acknowledgements, Appendix and similar trailing noise.

    Finds the earliest noise section header and truncates everything from that
    point onward. This alone typically saves 15-25% of tokens per paper.
    """
    best_pos = len(text)

    for pattern in (_NOISE_RE, _NOISE_MARKDOWN_RE):
        m = pattern.search(text)
        if m and m.start() < best_pos:
            best_pos = m.start()

    return text[:best_pos].rstrip()


# ---------------------------------------------------------------------------
# Section-aware slicing — per tool, pull only what's needed
# ---------------------------------------------------------------------------

# Which section keywords matter for each tool
_TOOL_SECTION_KEYWORDS: dict[str, list[str]] = {
    "summarize_paper": [
        "abstract", "introduction", "background", "overview",
        "conclusion", "summary", "discussion",
    ],
    "extract_key_findings": [
        "abstract", "result", "finding", "contribution",
        "experiment", "evaluation", "conclusion", "performance",
        "benchmark", "comparison",
    ],
    "assess_quality": [
        "abstract", "method", "approach", "model", "architecture",
        "algorithm", "limitation", "discussion", "experiment",
        "dataset", "baseline",
    ],
}

# Pattern to detect a section heading line (numbered or bare)
_SECTION_HEADER_RE = re.compile(
    r"(?m)^[ \t]*(?:\d+\.?\s+)?([A-Z][^\n]{0,60})\s*$"
)


def section_slice(text: str, tool_name: str) -> str:
    """Return only the sections of `text` that are relevant for `tool_name`.

    If section detection fails or yields less than 500 chars, returns the
    original text unchanged (so we never silently lose content).
    """
    keywords = _TOOL_SECTION_KEYWORDS.get(tool_name)
    if not keywords:
        return text

    # Split into blocks on likely section headers
    # Strategy: find all header candidates, group text into sections
    blocks: list[tuple[str, str]] = []  # (header_text_lower, body)
    last_end = 0
    last_header = "preamble"

    for m in _SECTION_HEADER_RE.finditer(text):
        header_line = m.group(1).strip().lower()
        # Require the header to look like a real section (short, title-case or all-caps)
        if len(header_line) > 80:
            continue
        # Skip lines that look like body sentences (contain lowercase run > 3 words)
        words = header_line.split()
        if len(words) > 8:
            continue
        body = text[last_end:m.start()]
        blocks.append((last_header, body))
        last_header = header_line
        last_end = m.end()

    # Add the final section
    blocks.append((last_header, text[last_end:]))

    # Collect relevant sections
    relevant_parts: list[str] = []
    for header, body in blocks:
        if any(kw in header for kw in keywords):
            relevant_parts.append(body.strip())

    result = "\n\n".join(p for p in relevant_parts if p)
    if len(result) < 500:
        # Detection failed — fall back to original
        return text

    return result


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def budget_text(text: str, tool_name: str = "default") -> tuple[str, dict]:
    """Process fulltext for a tool invocation.

    Steps:
      1. Strip noise sections (references, acknowledgements, appendix)
      2. Try to slice to relevant sections for this tool
      3. Hard-cap at the tool's token budget

    Returns:
      (processed_text, stats_dict)
      stats_dict keys: original_tokens, processed_tokens, sections_stripped, truncated
    """
    original_tokens = count_tokens(text)

    # Step 1: strip noise
    stripped = strip_noise_sections(text)
    noise_stripped = len(text) > len(stripped) + 50  # meaningful reduction

    # Step 2: section slice
    sliced = section_slice(stripped, tool_name)
    sections_stripped = noise_stripped or (len(sliced) < len(stripped) - 200)

    # Step 3: hard token cap
    budget = TOOL_BUDGETS.get(tool_name, TOOL_BUDGETS["default"])
    truncated = False

    if count_tokens(sliced) > budget:
        # Binary-search a char cutoff that fits within budget
        lo, hi = 0, len(sliced)
        while hi - lo > 200:
            mid = (lo + hi) // 2
            if count_tokens(sliced[:mid]) <= budget:
                lo = mid
            else:
                hi = mid
        sliced = sliced[:lo]
        truncated = True

    processed_tokens = count_tokens(sliced)

    stats = {
        "original_tokens": original_tokens,
        "processed_tokens": processed_tokens,
        "sections_stripped": sections_stripped,
        "truncated": truncated,
        "savings_pct": round(100 * (1 - processed_tokens / max(original_tokens, 1))),
    }

    return sliced, stats
