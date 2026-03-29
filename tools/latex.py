"""LaTeX pipeline tools — compile literature review to .tex file.

Phase 4.6: Export the complete literature review directly into an academic
.tex file with \\cite{} commands, ready for Overleaf upload.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

import db
from tools._constants import EXPORT_DIR


def _citation_key(paper) -> str:
    """Generate a consistent LaTeX cite key from a Paper object."""
    if paper.authors:
        last = paper.authors[0].name.split()[-1].lower()
        # Strip non-alpha chars
        last = re.sub(r"[^a-z]", "", last)
    else:
        last = "anon"
    return f"{last}{paper.year or 'nd'}"


def _escape_latex(text: str) -> str:
    """Escape special LaTeX characters in text."""
    replacements = {
        "&": r"\&",
        "%": r"\%",
        "$": r"\$",
        "#": r"\#",
        "_": r"\_",
        "~": r"\textasciitilde{}",
        "^": r"\textasciicircum{}",
    }
    for char, replacement in replacements.items():
        text = text.replace(char, replacement)
    return text


def _convert_inline_citations(text: str, key_map: dict[str, str]) -> str:
    """Convert [AuthorYear] inline citations to \\cite{key} commands.

    Handles patterns like [Han2018], [Weinan2017], [Carmona2018a].
    """
    def replace_cite(match):
        ref = match.group(1)
        # Look up in our key map
        for paper_key, cite_key in key_map.items():
            if ref.lower() == paper_key.lower():
                return f"\\cite{{{cite_key}}}"
        # If not found, still wrap in cite
        return f"\\cite{{{ref.lower()}}}"

    return re.sub(r"\[([A-Z][a-z]+\d{4}[a-z]?)\]", replace_cite, text)


def register(mcp):

    @mcp.tool()
    async def compile_to_latex(
        review_text: str,
        title: Optional[str] = None,
        author: Optional[str] = None,
        template: str = "article",
        output_path: Optional[str] = None,
    ) -> str:
        """Compile a literature review into a LaTeX .tex file.

        Takes the review text (with [AuthorYear] citations) and produces a
        complete .tex file with \\cite{} commands and a \\bibliography{} directive.
        Upload the .tex + .bib files to Overleaf for instant formatting.

        Args:
            review_text: The full literature review text with [AuthorYear] citations
            title: Document title (default: from research question config)
            author: Author name (default: 'Author')
            template: LaTeX template: 'article' (default), 'ieee', or 'acm'
            output_path: Output .tex file path (default: review.tex in export dir)
        """
        if not title:
            rq = await db.get_config("research_question")
            title = rq or "Literature Review"

        if not author:
            author = "Author"

        # Build cite key map from library
        papers = await db.list_papers(limit=500)
        key_map: dict[str, str] = {}  # AuthorYear → cite_key
        key_counts: dict[str, int] = {}

        for p in papers:
            author_year = (
                (p.authors[0].name.split()[-1] if p.authors else "Anon")
                + str(p.year or "nd")
            )
            base_key = _citation_key(p)

            if base_key in key_counts:
                key_counts[base_key] += 1
                suffix = chr(ord("a") + key_counts[base_key] - 1)
                cite_key = f"{base_key}{suffix}"
            else:
                key_counts[base_key] = 0
                cite_key = base_key

            key_map[author_year] = cite_key

        # Escape LaTeX special chars first, then convert [AuthorYear] citations
        # (brackets aren't special in LaTeX, so citations survive escaping)
        latex_body = _escape_latex(review_text)
        latex_body = _convert_inline_citations(latex_body, key_map)

        # Build the full .tex document
        templates = {
            "article": {
                "class": "article",
                "options": "12pt,a4paper",
                "packages": [
                    r"\usepackage[utf8]{inputenc}",
                    r"\usepackage[T1]{fontenc}",
                    r"\usepackage{natbib}",
                    r"\usepackage{hyperref}",
                    r"\usepackage{geometry}",
                    r"\geometry{margin=2.5cm}",
                ],
                "bibstyle": "plainnat",
            },
            "ieee": {
                "class": "IEEEtran",
                "options": "conference",
                "packages": [
                    r"\usepackage[utf8]{inputenc}",
                    r"\usepackage{cite}",
                    r"\usepackage{hyperref}",
                ],
                "bibstyle": "IEEEtran",
            },
            "acm": {
                "class": "acmart",
                "options": "sigconf",
                "packages": [
                    r"\usepackage{natbib}",
                    r"\usepackage{hyperref}",
                ],
                "bibstyle": "ACM-Reference-Format",
            },
        }

        tmpl = templates.get(template, templates["article"])

        # Split body into sections if it has markdown-style headers
        body_lines = []
        for line in latex_body.split("\n"):
            stripped = line.strip()
            if stripped.startswith("## "):
                section_title = _escape_latex(stripped[3:].strip())
                body_lines.append(f"\n\\section{{{section_title}}}")
            elif stripped.startswith("### "):
                section_title = _escape_latex(stripped[4:].strip())
                body_lines.append(f"\n\\subsection{{{section_title}}}")
            else:
                body_lines.append(line)

        formatted_body = "\n".join(body_lines)

        tex_content = (
            f"\\documentclass[{tmpl['options']}]{{{tmpl['class']}}}\n"
            + "\n".join(tmpl["packages"]) + "\n"
            + "\n"
            + f"\\title{{{_escape_latex(title)}}}\n"
            + f"\\author{{{_escape_latex(author)}}}\n"
            + "\\date{\\today}\n"
            + "\n"
            + "\\begin{document}\n"
            + "\\maketitle\n"
            + "\n"
            + formatted_body + "\n"
            + "\n"
            + f"\\bibliographystyle{{{tmpl['bibstyle']}}}\n"
            + "\\bibliography{references}\n"
            + "\n"
            + "\\end{document}\n"
        )

        out = Path(output_path) if output_path else EXPORT_DIR / "review.tex"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(tex_content, encoding="utf-8")

        bib_path = out.parent / "references.bib"
        bib_exists = bib_path.exists()

        result = f"LaTeX file written: {out}\n"
        result += f"Template: {template} ({tmpl['class']})\n"
        result += f"Citations converted: {latex_body.count(chr(92) + 'cite')}\n"
        if not bib_exists:
            result += f"\nNote: Run export_bibtex(output_path='{bib_path}') to generate the .bib file.\n"
        result += "Upload both .tex and .bib to Overleaf for instant formatting."

        return result
