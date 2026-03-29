"""Math-aware PDF ingestion — Nougat (local) or Mathpix (API).

Phase 2.1: Extract native LaTeX from academic PDFs instead of garbled plaintext.
Nougat is Meta's open-source visual transformer for academic PDF → LaTeX.
Mathpix is a commercial API that does the same thing.

Both are optional. If neither is available, falls back to pdfplumber plaintext.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Optional


async def extract_with_nougat(pdf_path: str | Path) -> Optional[str]:
    """Extract LaTeX from a PDF using Meta's Nougat model.

    Requires: pip install nougat-ocr torch
    Runs locally — no API key needed, but needs ~4GB GPU VRAM.

    Returns LaTeX text or None if Nougat is not available.
    """
    try:
        import asyncio
        # Nougat is a CLI tool — run it as a subprocess
        proc = await asyncio.create_subprocess_exec(
            "nougat", str(pdf_path), "--out", str(Path(pdf_path).parent),
            "--no-skipping",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()

        if proc.returncode != 0:
            return None

        # Nougat outputs a .mmd file alongside the PDF
        mmd_path = Path(pdf_path).with_suffix(".mmd")
        if mmd_path.exists():
            text = mmd_path.read_text(encoding="utf-8")
            mmd_path.unlink()  # clean up
            return text

        return None
    except (FileNotFoundError, OSError):
        return None  # Nougat not installed


async def extract_with_mathpix(pdf_path: str | Path) -> Optional[str]:
    """Extract LaTeX from a PDF using the Mathpix API.

    Requires: MATHPIX_APP_ID and MATHPIX_APP_KEY environment variables.

    Returns LaTeX text or None if Mathpix is not configured.
    """
    app_id = os.environ.get("MATHPIX_APP_ID")
    app_key = os.environ.get("MATHPIX_APP_KEY")

    if not app_id or not app_key:
        return None

    try:
        import httpx
        import asyncio

        headers = {
            "app_id": app_id,
            "app_key": app_key,
        }

        # Upload PDF to Mathpix
        async with httpx.AsyncClient(timeout=120) as client:
            with open(pdf_path, "rb") as f:
                resp = await client.post(
                    "https://api.mathpix.com/v3/pdf",
                    headers=headers,
                    files={"file": ("paper.pdf", f, "application/pdf")},
                    data={
                        "options_json": '{"conversion_formats": {"latex_styled": true}}'
                    },
                )
                resp.raise_for_status()
                result = resp.json()
                pdf_id = result.get("pdf_id")

            if not pdf_id:
                return None

            # Poll for completion
            for _ in range(60):  # up to 5 minutes
                await asyncio.sleep(5)
                status_resp = await client.get(
                    f"https://api.mathpix.com/v3/pdf/{pdf_id}",
                    headers=headers,
                )
                status = status_resp.json()
                if status.get("status") == "completed":
                    break
                if status.get("status") == "error":
                    return None

            # Download LaTeX
            latex_resp = await client.get(
                f"https://api.mathpix.com/v3/pdf/{pdf_id}.tex",
                headers=headers,
            )
            if latex_resp.status_code == 200:
                return latex_resp.text

        return None
    except Exception:
        return None


async def extract_with_pdfplumber(pdf_path: str | Path) -> Optional[str]:
    """Standard plaintext extraction via pdfplumber (fallback)."""
    try:
        import pdfplumber
        with pdfplumber.open(pdf_path) as pdf:
            text = "\n\n".join(
                page.extract_text() or "" for page in pdf.pages
            ).strip()
        return text if text else None
    except ImportError:
        return None
    except Exception:
        return None


def parse_math_structures(latex_text: str) -> dict:
    """Parse LaTeX text into structured math components.

    Extracts equations, theorems, lemmas, definitions, assumptions, and proofs
    from LaTeX source into a structured dict for storage.
    """
    structures: dict = {
        "equations": [],
        "theorems": [],
        "lemmas": [],
        "definitions": [],
        "assumptions": [],
        "proofs": [],
    }

    # Extract numbered/labeled equations
    for m in re.finditer(
        r"\\begin\{(?:equation|align|gather)\*?\}(.*?)\\end\{(?:equation|align|gather)\*?\}",
        latex_text, re.DOTALL
    ):
        eq = m.group(1).strip()
        if eq:
            structures["equations"].append(eq[:500])

    # Inline display math
    for m in re.finditer(r"\$\$(.*?)\$\$", latex_text, re.DOTALL):
        eq = m.group(1).strip()
        if eq and len(eq) > 10:  # skip trivial inline math
            structures["equations"].append(eq[:500])

    # Theorem-like environments
    env_map = {
        "theorem": "theorems",
        "thm": "theorems",
        "lemma": "lemmas",
        "lem": "lemmas",
        "definition": "definitions",
        "defn": "definitions",
        "def": "definitions",
        "assumption": "assumptions",
        "proof": "proofs",
    }

    for env_name, key in env_map.items():
        pattern = rf"\\begin\{{{env_name}\*?\}}(.*?)\\end\{{{env_name}\*?\}}"
        for m in re.finditer(pattern, latex_text, re.DOTALL):
            content = m.group(1).strip()[:800]
            if content:
                structures[key].append(content)

    return {k: v for k, v in structures.items() if v}


async def extract_pdf(pdf_path: str | Path) -> tuple[str, str, dict]:
    """Extract text from a PDF using the best available method.

    Tries in order: Nougat (local LaTeX) → Mathpix (API LaTeX) → pdfplumber (plaintext).

    Returns:
        (text, method, math_structures)
        - text: the extracted text
        - method: "nougat", "mathpix", or "pdfplumber"
        - math_structures: parsed equations/theorems (empty dict if plaintext)
    """
    # Try Nougat first (free, local, best quality)
    text = await extract_with_nougat(pdf_path)
    if text:
        structures = parse_math_structures(text)
        return text, "nougat", structures

    # Try Mathpix (paid API, good quality)
    text = await extract_with_mathpix(pdf_path)
    if text:
        structures = parse_math_structures(text)
        return text, "mathpix", structures

    # Fallback to pdfplumber (free, no math support)
    text = await extract_with_pdfplumber(pdf_path)
    if text:
        return text, "pdfplumber", {}

    return "", "none", {}
