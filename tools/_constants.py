"""Shared constants for all tool modules."""

import os
from pathlib import Path

PAPERS_DIR = Path(os.environ.get("ARIADNE_PAPERS_DIR", Path(__file__).parent.parent / "pdfs"))
EXPORT_DIR = Path(os.environ.get("ARIADNE_EXPORT_DIR", Path.cwd()))
