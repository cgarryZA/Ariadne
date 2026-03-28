"""BibTeX import/export utilities."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from models import Author, Paper


def parse_bibtex_file(bib_path: str | Path) -> list[dict]:
    """Parse a .bib file into a list of entry dicts.

    Returns list of dicts with keys: cite_key, entry_type, title, author,
    year, journal, volume, number, pages, publisher, doi.
    """
    text = Path(bib_path).read_text(encoding="utf-8")
    entries = []

    # Split on @ entries
    raw_entries = re.findall(
        r"@(\w+)\s*\{([^,]+),\s*(.*?)\n\}", text, re.DOTALL
    )

    for entry_type, cite_key, body in raw_entries:
        entry = {"cite_key": cite_key.strip(), "entry_type": entry_type.strip().lower()}

        # Extract fields
        for match in re.finditer(r"(\w+)\s*=\s*\{([^}]*)\}", body):
            field_name = match.group(1).lower()
            field_value = match.group(2).strip()
            entry[field_name] = field_value

        entries.append(entry)

    return entries


def bibtex_authors_to_list(author_str: str) -> list[Author]:
    """Convert BibTeX author string to list of Author objects."""
    if not author_str:
        return []
    # Split on " and "
    names = [n.strip() for n in author_str.split(" and ")]
    authors = []
    for name in names:
        if "," in name:
            # "Last, First" format
            parts = name.split(",", 1)
            full_name = f"{parts[1].strip()} {parts[0].strip()}"
        else:
            full_name = name
        authors.append(Author(name=full_name))
    return authors


def paper_to_bibtex(paper: Paper, cite_key: Optional[str] = None) -> str:
    """Convert a Paper to a BibTeX entry string."""
    if paper.bibtex:
        return paper.bibtex

    # Generate cite key from first author last name + year
    if not cite_key:
        if paper.authors:
            last_name = paper.authors[0].name.split()[-1].lower()
            cite_key = f"{last_name}{paper.year or 'nd'}"
        else:
            cite_key = f"paper_{paper.id[:8]}"

    fields = []
    fields.append(f"  title={{{paper.title}}}")

    if paper.authors:
        author_str = " and ".join(a.name for a in paper.authors)
        fields.append(f"  author={{{author_str}}}")

    if paper.year:
        fields.append(f"  year={{{paper.year}}}")
    if paper.venue:
        fields.append(f"  journal={{{paper.venue}}}")
    if paper.doi:
        fields.append(f"  doi={{{paper.doi}}}")
    if paper.url:
        fields.append(f"  url={{{paper.url}}}")

    fields_str = ",\n".join(fields)
    return f"@article{{{cite_key},\n{fields_str}\n}}"


def export_bibtex(papers: list[Paper], output_path: str | Path) -> str:
    """Export a list of papers to a .bib file. Returns the path."""
    entries = []
    for paper in papers:
        entries.append(paper_to_bibtex(paper))

    content = "\n\n".join(entries) + "\n"
    Path(output_path).write_text(content, encoding="utf-8")
    return str(output_path)
