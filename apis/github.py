"""GitHub API client for code-to-math alignment.

Phase 4.2: Scrape linked GitHub repos from ML papers to extract implementation
details (hyperparameters, gradient clipping, batch norm) that were omitted
from the paper but are required for convergence.
"""

from __future__ import annotations

import os
import re
from typing import Optional

import httpx


_GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")

_client: Optional[httpx.AsyncClient] = None


def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None or _client.is_closed:
        headers = {"Accept": "application/vnd.github.v3+json"}
        if _GITHUB_TOKEN:
            headers["Authorization"] = f"token {_GITHUB_TOKEN}"
        _client = httpx.AsyncClient(timeout=30, headers=headers)
    return _client


async def close_client() -> None:
    global _client
    if _client is not None and not _client.is_closed:
        await _client.aclose()
        _client = None


def extract_github_urls(text: str) -> list[str]:
    """Find GitHub repository URLs in text."""
    pattern = r"https?://github\.com/([a-zA-Z0-9_.-]+/[a-zA-Z0-9_.-]+)"
    matches = re.findall(pattern, text)
    # Deduplicate preserving order
    seen = set()
    urls = []
    for m in matches:
        repo = m.rstrip("/").split("/tree/")[0].split("/blob/")[0]
        if repo not in seen:
            seen.add(repo)
            urls.append(repo)
    return urls


async def get_repo_info(owner_repo: str) -> Optional[dict]:
    """Get basic repo metadata."""
    client = _get_client()
    try:
        resp = await client.get(f"https://api.github.com/repos/{owner_repo}")
        if resp.status_code != 200:
            return None
        data = resp.json()
        return {
            "full_name": data.get("full_name"),
            "description": data.get("description"),
            "language": data.get("language"),
            "stars": data.get("stargazers_count"),
            "forks": data.get("forks_count"),
            "updated_at": data.get("updated_at"),
            "url": data.get("html_url"),
        }
    except Exception:
        return None


async def get_readme(owner_repo: str) -> Optional[str]:
    """Fetch the README content of a repo."""
    client = _get_client()
    try:
        resp = await client.get(
            f"https://api.github.com/repos/{owner_repo}/readme",
            headers={"Accept": "application/vnd.github.v3.raw"},
        )
        if resp.status_code != 200:
            return None
        return resp.text[:10000]  # cap at 10K chars
    except Exception:
        return None


async def get_file_content(owner_repo: str, path: str) -> Optional[str]:
    """Fetch a specific file's content from a repo."""
    client = _get_client()
    try:
        resp = await client.get(
            f"https://api.github.com/repos/{owner_repo}/contents/{path}",
            headers={"Accept": "application/vnd.github.v3.raw"},
        )
        if resp.status_code != 200:
            return None
        return resp.text[:20000]  # cap at 20K chars
    except Exception:
        return None


async def find_main_files(owner_repo: str) -> list[str]:
    """Find likely main implementation files in a repo."""
    client = _get_client()
    try:
        resp = await client.get(f"https://api.github.com/repos/{owner_repo}/contents/")
        if resp.status_code != 200:
            return []
        contents = resp.json()
    except Exception:
        return []

    # Priority patterns for ML/math code
    priority_patterns = [
        "main.py", "train.py", "model.py", "solver.py", "network.py",
        "run.py", "experiment.py", "config.py", "hyperparameters.py",
    ]
    secondary_patterns = [".py"]

    found = []
    all_files = [f["name"] for f in contents if f.get("type") == "file"]

    # Priority files first
    for pattern in priority_patterns:
        for name in all_files:
            if name.lower() == pattern:
                found.append(name)

    # Then any .py files up to a limit
    for name in all_files:
        if name.endswith(".py") and name not in found:
            found.append(name)
        if len(found) >= 10:
            break

    return found


async def analyze_repo(owner_repo: str) -> dict:
    """Full analysis of a GitHub repo for code-to-math alignment.

    Returns a dict with repo info, README summary, implementation files,
    and extracted implementation details.
    """
    info = await get_repo_info(owner_repo)
    if not info:
        return {"error": f"Repository {owner_repo} not found or inaccessible"}

    readme = await get_readme(owner_repo)
    main_files = await find_main_files(owner_repo)

    # Extract implementation details from key files
    code_snippets = {}
    for fname in main_files[:5]:  # limit to 5 files
        content = await get_file_content(owner_repo, fname)
        if content:
            code_snippets[fname] = content

    # Look for undocumented tricks in the code
    tricks = _extract_tricks(code_snippets)

    return {
        "info": info,
        "readme": readme,
        "main_files": main_files,
        "code_snippets": code_snippets,
        "undocumented_tricks": tricks,
    }


def _extract_tricks(code_snippets: dict[str, str]) -> list[str]:
    """Scan code for common ML implementation tricks not typically in papers."""
    tricks = []

    trick_patterns = {
        r"BatchNorm|batch_norm|nn\.BatchNorm": "Batch normalization used",
        r"LayerNorm|layer_norm|nn\.LayerNorm": "Layer normalization used",
        r"clip_grad_norm|clip_grad_value|gradient.clip": "Gradient clipping applied",
        r"Dropout|dropout|nn\.Dropout": "Dropout regularization",
        r"weight_decay|wd\s*=": "Weight decay / L2 regularization",
        r"lr_scheduler|StepLR|CosineAnnealing|ReduceLROnPlateau": "Learning rate scheduling",
        r"torch\.cuda\.amp|autocast|GradScaler": "Mixed precision (AMP) training",
        r"DataParallel|DistributedDataParallel": "Multi-GPU / distributed training",
        r"early_stop|EarlyStopping": "Early stopping",
        r"xavier_init|kaiming_init|orthogonal_init|nn\.init\.": "Custom weight initialization",
        r"exponential_moving_average|ema": "EMA for model weights",
        r"label_smooth|LabelSmoothing": "Label smoothing",
        r"warmup|warm_up": "Learning rate warmup",
        r"gradient_accumulation|accumulation_steps": "Gradient accumulation",
        r"SWA|stochastic_weight_averaging": "Stochastic weight averaging",
    }

    all_code = "\n".join(code_snippets.values())
    for pattern, description in trick_patterns.items():
        if re.search(pattern, all_code):
            tricks.append(description)

    # Extract hyperparameters
    lr_matches = re.findall(r"(?:lr|learning_rate)\s*=\s*([\d.e-]+)", all_code)
    if lr_matches:
        tricks.append(f"Learning rate(s): {', '.join(set(lr_matches[:5]))}")

    bs_matches = re.findall(r"(?:batch_size|bsz)\s*=\s*(\d+)", all_code)
    if bs_matches:
        tricks.append(f"Batch size(s): {', '.join(set(bs_matches[:5]))}")

    epoch_matches = re.findall(r"(?:epochs?|n_epochs?|num_epochs?)\s*=\s*(\d+)", all_code)
    if epoch_matches:
        tricks.append(f"Training epochs: {', '.join(set(epoch_matches[:5]))}")

    return tricks
