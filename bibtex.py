"""BibTeX import/export utilities.

Uses bibtexparser for robust .bib file parsing, with string-based
export for generating clean entries.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from models import Author, Paper


def parse_bibtex_file(bib_path: str | Path) -> list[dict]:
    """Parse a .bib file into a list of entry dicts.

    Uses the bibtexparser library for robust handling of nested braces,
    multi-line fields, string concatenation, and comments.

    Returns list of dicts with keys: cite_key, entry_type, title, author,
    year, journal, volume, number, pages, publisher, doi, etc.
    """
    try:
        import bibtexparser
    except ImportError:
        # Fallback: minimal regex parser for users without bibtexparser
        return _parse_bibtex_fallback(bib_path)

    text = Path(bib_path).read_text(encoding="utf-8")
    library = bibtexparser.parse(text)

    entries = []
    for entry in library.entries:
        d = {
            "cite_key": entry.key,
            "entry_type": entry.entry_type.lower(),
        }
        for field in entry.fields:
            d[field.key.lower()] = field.value
        entries.append(d)

    return entries


def _parse_bibtex_fallback(bib_path: str | Path) -> list[dict]:
    """Minimal regex fallback when bibtexparser is not installed."""
    import re
    text = Path(bib_path).read_text(encoding="utf-8")
    entries = []

    # Find entries: handle nested braces properly
    i = 0
    while i < len(text):
        match = re.search(r"@(\w+)\s*\{", text[i:])
        if not match:
            break
        entry_type = match.group(1).lower()
        start = i + match.end()

        # Find the matching closing brace (handle nesting)
        depth = 1
        j = start
        while j < len(text) and depth > 0:
            if text[j] == "{":
                depth += 1
            elif text[j] == "}":
                depth -= 1
            j += 1

        body = text[start:j - 1]
        i = j

        # Extract cite key (everything before first comma)
        comma_pos = body.find(",")
        if comma_pos == -1:
            continue
        cite_key = body[:comma_pos].strip()
        fields_text = body[comma_pos + 1:]

        entry = {"cite_key": cite_key, "entry_type": entry_type}

        # Extract fields — handle nested braces in values
        for field_match in re.finditer(r"(\w+)\s*=\s*", fields_text):
            field_name = field_match.group(1).lower()
            val_start = field_match.end()

            # Value can be {braced}, "quoted", or a number/macro
            if val_start < len(fields_text):
                char = fields_text[val_start:val_start + 1].strip()
                if not char:
                    continue

                if fields_text[val_start] == "{":
                    # Find matching close brace
                    d = 1
                    k = val_start + 1
                    while k < len(fields_text) and d > 0:
                        if fields_text[k] == "{":
                            d += 1
                        elif fields_text[k] == "}":
                            d -= 1
                        k += 1
                    entry[field_name] = fields_text[val_start + 1:k - 1].strip()
                elif fields_text[val_start] == '"':
                    end = fields_text.find('"', val_start + 1)
                    if end != -1:
                        entry[field_name] = fields_text[val_start + 1:end].strip()

        entries.append(entry)

    return entries


def bibtex_authors_to_list(author_str: str) -> list[Author]:
    """Convert BibTeX author string to list of Author objects."""
    if not author_str:
        return []
    names = [n.strip() for n in author_str.split(" and ")]
    authors = []
    for name in names:
        if "," in name:
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
    """Export a list of papers to a .bib file with disambiguated cite keys.

    Returns the path.
    """
    # Track cite keys to disambiguate collisions (smith2024 -> smith2024a, smith2024b)
    key_counts: dict[str, int] = {}
    entries = []

    for paper in papers:
        # Generate base key
        if paper.authors:
            last_name = paper.authors[0].name.split()[-1].lower()
            base_key = f"{last_name}{paper.year or 'nd'}"
        else:
            base_key = f"paper_{paper.id[:8]}"

        # Disambiguate
        if base_key in key_counts:
            key_counts[base_key] += 1
            suffix = chr(ord("a") + key_counts[base_key] - 1)
            cite_key = f"{base_key}{suffix}"
        else:
            key_counts[base_key] = 0
            cite_key = base_key

        entries.append(paper_to_bibtex(paper, cite_key=cite_key))

    content = "\n\n".join(entries) + "\n"
    Path(output_path).write_text(content, encoding="utf-8")
    return str(output_path)
