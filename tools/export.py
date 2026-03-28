"""BibTeX import/export tools."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Optional

import db
from apis import semantic_scholar as s2
from bibtex import (
    bibtex_authors_to_list,
    export_bibtex as _export_bib,
    paper_to_bibtex,
    parse_bibtex_file,
)
from models import Paper
from tools._constants import EXPORT_DIR


def register(mcp):

    @mcp.tool()
    async def export_bibtex(
        paper_ids: Optional[str] = None,
        output_path: Optional[str] = None,
    ) -> str:
        """Export papers as BibTeX. If no IDs given, exports the entire library.

        Args:
            paper_ids: Comma-separated paper IDs (optional -- exports all if omitted)
            output_path: Output file path (default: references.bib in current directory)
        """
        if paper_ids:
            ids = [pid.strip() for pid in paper_ids.split(",")]
            papers = []
            for pid in ids:
                p = await db.get_paper(pid)
                if p:
                    papers.append(p)
        else:
            papers = await db.list_papers(limit=500)

        if not papers:
            return "No papers to export."

        out = Path(output_path) if output_path else EXPORT_DIR / "references.bib"
        out.parent.mkdir(parents=True, exist_ok=True)
        path = _export_bib(papers, out)
        return f"Exported {len(papers)} papers to {path}"

    @mcp.tool()
    async def import_from_bibtex(bib_path: str) -> str:
        """Import papers from a BibTeX file. Looks up each entry on Semantic Scholar
        by title to enrich with full metadata.

        Args:
            bib_path: Absolute path to the .bib file to import
        """
        path = Path(bib_path)
        if not path.exists():
            return f"File not found: {path}\nTip: use an absolute path, e.g. C:/Users/you/refs.bib"

        entries = parse_bibtex_file(path)
        if not entries:
            return "No entries found in the BibTeX file."

        imported = []
        failed = []

        for i, entry in enumerate(entries):
            title = entry.get("title", "")
            if not title:
                failed.append(entry.get("cite_key", "unknown"))
                continue

            if i > 0:
                await asyncio.sleep(3)

            try:
                results = await s2.search_papers(title, limit=1)
                if results:
                    data = await s2.get_paper_details(results[0].id)
                    fields = s2.parse_paper_to_library(data)
                    paper = Paper(**fields)
                    paper.bibtex = paper_to_bibtex(paper)
                    await db.insert_paper(paper)
                    imported.append(f"{paper.title} ({paper.year})")
                else:
                    authors = bibtex_authors_to_list(entry.get("author", ""))
                    paper = Paper(
                        id=f"bib_{entry['cite_key']}",
                        title=title,
                        authors=authors,
                        year=int(entry["year"]) if "year" in entry else None,
                        venue=entry.get("journal"),
                        doi=entry.get("doi"),
                    )
                    await db.insert_paper(paper)
                    imported.append(f"{title} (BibTeX only -- not found on Semantic Scholar)")
            except Exception as e:
                failed.append(f"{title}: {e}")

        result = f"Imported {len(imported)} papers:\n"
        result += "\n".join(f"  - {t}" for t in imported)
        if failed:
            result += f"\n\nFailed ({len(failed)}):\n"
            result += "\n".join(f"  - {f}" for f in failed)
        return result
