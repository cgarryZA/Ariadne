"""Library management tools — add, remove, tag, rate, annotate papers."""

from __future__ import annotations

import asyncio
from typing import Optional

import db
from apis import openalex as oa
from apis import semantic_scholar as s2
from bibtex import paper_to_bibtex
from models import Paper, ReadingStatus
from tools.formatting import format_paper, format_result, validate_pillar, resolve_paper_id
from tools._text_processing import budget_text, TOOL_BUDGETS


def register(mcp):

    @mcp.tool()
    async def add_paper(paper_id: str) -> str:
        """Add a paper to the library by fetching its full metadata from Semantic Scholar.

        Args:
            paper_id: Semantic Scholar paper ID, or DOI: prefix, or ARXIV: prefix
                      Examples: '649def34f8be52c8b66281af98ae884c09aef38b'
                                'DOI:10.1145/3292500.3330925'
                                'ARXIV:1706.03762'
        """
        existing = await db.get_paper(paper_id)
        if existing:
            return f"Paper already in library: {existing.title}"

        try:
            data = await s2.get_paper_details(paper_id)
        except Exception as e:
            return f"Error fetching paper: {e}"

        fields = s2.parse_paper_to_library(data)
        paper = Paper(**fields)
        paper.bibtex = paper_to_bibtex(paper)

        await db.insert_paper(paper)
        return f"Added to library: {paper.title} ({paper.year})\nID: {paper.id}"

    @mcp.tool()
    async def add_paper_openalex(identifier: str) -> str:
        """Add a paper from OpenAlex by DOI or OpenAlex ID.

        Use this for papers found via search_openalex() that don't have
        Semantic Scholar IDs.

        Args:
            identifier: DOI (e.g. '10.1145/3292500.3330925') or OpenAlex ID (e.g. 'W2741809807')
        """
        try:
            # If it looks like a DOI, use get_paper_by_doi
            if "/" in identifier or identifier.startswith("10."):
                data = await oa.get_paper_by_doi(identifier)
            else:
                # Try as DOI anyway (OpenAlex accepts Work IDs too)
                data = await oa.get_paper_by_doi(identifier)
        except Exception as e:
            return f"Error fetching paper from OpenAlex: {e}"

        paper = Paper(**data)
        paper.bibtex = paper_to_bibtex(paper)

        existing = await db.get_paper(paper.id)
        if existing:
            return f"Paper already in library: {existing.title}"

        await db.insert_paper(paper)
        return f"Added from OpenAlex: {paper.title} ({paper.year})\nID: {paper.id}"

    @mcp.tool()
    async def batch_add(paper_ids: str) -> str:
        """Add multiple papers at once by their IDs.

        Much faster than calling add_paper() individually. Includes rate
        limiting to respect API limits.

        Args:
            paper_ids: Comma-separated paper IDs (S2, DOI:xxx, or ARXIV:xxx)
        """
        ids = [pid.strip() for pid in paper_ids.split(",") if pid.strip()]
        if not ids:
            return "No paper IDs provided."

        added = []
        skipped = []
        failed = []

        for i, pid in enumerate(ids):
            if i > 0:
                await asyncio.sleep(1.2)  # Rate limiting

            existing = await db.get_paper(pid)
            if existing:
                skipped.append(f"{existing.title} (already in library)")
                continue

            try:
                data = await s2.get_paper_details(pid)
                fields = s2.parse_paper_to_library(data)
                paper = Paper(**fields)
                paper.bibtex = paper_to_bibtex(paper)
                await db.insert_paper(paper)
                added.append(f"{paper.title} ({paper.year})")
            except Exception as e:
                failed.append(f"{pid}: {e}")

        lines = [f"Batch add complete: {len(added)} added, {len(skipped)} skipped, {len(failed)} failed"]
        if added:
            lines.append("\nAdded:")
            lines.extend(f"  + {t}" for t in added)
        if skipped:
            lines.append("\nSkipped:")
            lines.extend(f"  ~ {t}" for t in skipped)
        if failed:
            lines.append("\nFailed:")
            lines.extend(f"  ! {t}" for t in failed)
        return "\n".join(lines)

    @mcp.tool()
    async def remove_paper(paper_id: str) -> str:
        """Remove a paper from the library.

        Args:
            paper_id: The paper's ID
        """
        removed = await db.delete_paper(paper_id)
        return "Paper removed." if removed else "Paper not found in library."

    @mcp.tool()
    async def list_library(
        status: Optional[str] = None,
        pillar: Optional[str] = None,
        tag: Optional[str] = None,
        chapter: Optional[str] = None,
        sort_by: str = "added_at",
        limit: int = 50,
    ) -> str:
        """List papers in your library with optional filters.

        Args:
            status: Filter by reading status (unread, skimmed, read, deep_read)
            pillar: Filter by research pillar
            tag: Filter by tag
            chapter: Filter by section/chapter name
            sort_by: Sort field (added_at, year, citation_count, relevance, title)
            limit: Max results (default 50)
        """
        pillar_err = await validate_pillar(pillar)
        if pillar_err:
            return pillar_err

        papers = await db.list_papers(
            status=status, pillar=pillar, tag=tag, chapter=chapter,
            sort_by=sort_by, limit=limit,
        )

        if not papers:
            return "No papers found matching those filters."

        formatted = [await format_paper(p) for p in papers]
        return f"Library ({len(papers)} papers):\n\n" + "\n\n---\n\n".join(formatted)

    @mcp.tool()
    async def get_paper_details(paper_id: str) -> str:
        """Get full details for a paper in your library.

        Args:
            paper_id: The paper's ID
        """
        resolved_id, err = await resolve_paper_id(paper_id)
        if err:
            return err
        paper = await db.get_paper(resolved_id)

        result = await format_paper(paper)
        if paper.abstract:
            result += f"\n\n**Abstract:**\n{paper.abstract}"
        return result

    @mcp.tool()
    async def get_fulltext(paper_id: str, raw: bool = False) -> str:
        """Retrieve the stored full text of a downloaded paper's PDF.

        By default, strips noise sections (References, Appendix, etc.) and applies
        a token budget so the output fits comfortably in Claude's context. Set
        raw=True to get the unprocessed text.

        Use this to read the actual content of a paper after calling download_pdf().

        Args:
            paper_id: The paper's ID
            raw: If True, return full unprocessed text (may be very large)
        """
        resolved_id, err = await resolve_paper_id(paper_id)
        if err:
            return err
        paper_id = resolved_id
        paper = await db.get_paper(paper_id)

        text = await db.get_fulltext(paper_id)
        if not text:
            return (
                f"No full text stored for '{paper.title}'.\n"
                "Use download_pdf() first to download and extract the text."
            )

        if raw:
            return f"Full text of '{paper.title}' ({len(text):,} chars, {len(text)//4:,} tokens est.):\n\n{text}"

        processed, stats = budget_text(text, "get_fulltext")
        header = f"Full text of '{paper.title}'"
        if stats["sections_stripped"] or stats["truncated"]:
            header += (
                f" [noise stripped, {stats['savings_pct']}% token reduction: "
                f"{stats['original_tokens']:,} → {stats['processed_tokens']:,} tokens"
            )
            if stats["truncated"]:
                header += f"; budget cap: {TOOL_BUDGETS['get_fulltext']:,} tokens"
            header += "]"
        return f"{header}:\n\n{processed}"

    @mcp.tool()
    async def semantic_search(query: str, limit: int = 10) -> str:
        """Search your library by meaning, not just keywords.

        Uses the best available method:
        1. ChromaDB persistent vector store (instant — pip install chromadb)
        2. Transient sentence-transformer embeddings (pip install sentence-transformers)
        3. FTS5 keyword search (always available)

        Finds papers whose titles, abstracts, and fulltext passages are
        semantically similar to your query, even with different terminology.

        Args:
            query: Natural language query
            limit: Maximum results (default 10)
        """
        from tools._vectorstore import is_available as vs_available, search as vs_search
        from tools._embeddings import is_available as emb_available

        papers_all = await db.list_papers(limit=500)
        if not papers_all:
            return "Library is empty."
        paper_map = {p.id: p for p in papers_all}

        # Strategy 1: ChromaDB persistent vector store (instant, chunk-level)
        if vs_available():
            hits = await vs_search(query, limit=limit * 3)  # oversample to dedup by paper
            if hits:
                # Deduplicate by paper_id, keeping best hit per paper
                seen_papers: dict[str, dict] = {}
                for h in hits:
                    pid = h["paper_id"]
                    if pid not in seen_papers or h["distance"] < seen_papers[pid]["distance"]:
                        seen_papers[pid] = h

                ranked = sorted(seen_papers.values(), key=lambda x: x["distance"])[:limit]

                lines = [f"Semantic search (ChromaDB): \"{query}\" ({len(ranked)} results)\n"]
                for h in ranked:
                    pid = h["paper_id"]
                    sim = max(0, 1 - h["distance"])  # cosine distance -> similarity
                    if sim < 0.2:
                        continue
                    p = paper_map.get(pid)
                    if not p:
                        continue
                    authors = ", ".join(a.name for a in p.authors[:2])
                    chunk_info = f" (matched in {h['chunk_type']})" if h["chunk_type"] == "fulltext" else ""
                    lines.append(
                        f"  [{sim:.0%}] **{p.title}**{chunk_info}\n"
                        f"    {authors} ({p.year or '?'}) | ID: {p.id} | "
                        f"Pillar: {p.pillar or '-'} | Citations: {p.citation_count or 0}"
                    )
                    if h["chunk_type"] == "fulltext" and h.get("text"):
                        lines.append(f"    Passage: {h['text'][:150]}...")
                    elif p.tldr:
                        lines.append(f"    TLDR: {p.tldr}")
                    lines.append("")

                if len(lines) > 1:
                    return "\n".join(lines)

        # Strategy 2: Transient sentence-transformer embeddings
        if emb_available():
            from tools._embeddings import rank_by_similarity

            docs = []
            for p in papers_all:
                text = p.title
                if p.abstract:
                    text += " " + p.abstract[:300]
                docs.append(text)

            ranked = rank_by_similarity(query, docs, top_k=limit)

            lines = [f"Semantic search (transient embeddings): \"{query}\" ({len(ranked)} results)\n"]
            for idx, sim in ranked:
                if sim < 0.2:
                    continue
                p = papers_all[idx]
                authors = ", ".join(a.name for a in p.authors[:2])
                lines.append(
                    f"  [{sim:.0%}] **{p.title}**\n"
                    f"    {authors} ({p.year or '?'}) | ID: {p.id} | "
                    f"Pillar: {p.pillar or '-'} | Citations: {p.citation_count or 0}"
                )
                if p.tldr:
                    lines.append(f"    TLDR: {p.tldr}")
                lines.append("")

            if len(lines) > 1:
                return "\n".join(lines)

        # Strategy 3: FTS5 keyword fallback
        results = await db.search_library(query)
        if not results:
            return (
                "No matches found. For semantic search, install:\n"
                "  pip install chromadb            (persistent vector store)\n"
                "  pip install sentence-transformers (transient embeddings)"
            )
        formatted = [await format_paper(p) for p in results[:limit]]
        return f"FTS5 keyword results:\n\n" + "\n\n---\n\n".join(formatted)

    @mcp.tool()
    async def index_library() -> str:
        """Index all papers into the persistent vector store for instant semantic search.

        Embeds title+abstract and fulltext (if stored) for every paper in the
        library. Run this once after installing chromadb, or after bulk-adding
        papers that weren't downloaded via download_pdf.

        Requires: pip install chromadb
        """
        from tools._vectorstore import is_available as vs_available, index_paper, get_stats

        if not vs_available():
            return (
                "ChromaDB not installed. Install it for persistent semantic search:\n"
                "  pip install chromadb"
            )

        papers = await db.list_papers(limit=1000)
        if not papers:
            return "Library is empty."

        total_chunks = 0
        indexed = 0
        for p in papers:
            fulltext = await db.get_fulltext(p.id)
            n = await index_paper(p.id, p.title, p.abstract, fulltext)
            if n > 0:
                indexed += 1
                total_chunks += n

        stats = await get_stats()
        return (
            f"Indexed {indexed}/{len(papers)} papers ({total_chunks} chunks) into ChromaDB.\n"
            f"Storage: {stats.get('storage_path', '?')}\n"
            f"Total in store: {stats.get('total_chunks', '?')} chunks from {stats.get('papers_indexed', '?')} papers.\n\n"
            "semantic_search() will now use the vector store for instant results."
        )

    @mcp.tool()
    async def passage_search(query: str, paper_id: Optional[str] = None, limit: int = 5) -> str:
        """Find exact passages across your library matching a semantic query.

        Unlike semantic_search (which returns papers), this returns the actual
        text passages — useful for finding specific mentions, quotes, or claims.

        Example: "mentions of 1/sqrt(N) convergence rate breaking down"

        Requires: pip install chromadb (passages must be indexed via download_pdf or index_library)

        Args:
            query: Natural language query
            paper_id: Optional — limit search to a single paper
            limit: Maximum passages to return (default 5)
        """
        from tools._vectorstore import is_available as vs_available, search as vs_search

        if not vs_available():
            return (
                "Passage search requires ChromaDB:\n"
                "  pip install chromadb\n"
                "Then run index_library() to index your papers."
            )

        paper_filter = [paper_id] if paper_id else None
        hits = await vs_search(query, limit=limit, paper_ids=paper_filter)

        if not hits:
            return "No matching passages found. Run index_library() if papers aren't indexed yet."

        lines = [f"Passage search: \"{query}\" ({len(hits)} results)\n"]
        for i, h in enumerate(hits, 1):
            sim = max(0, 1 - h["distance"])
            paper = await db.get_paper(h["paper_id"])
            cite = ""
            if paper:
                cite = (paper.authors[0].name.split()[-1] if paper.authors else "?") + str(paper.year or "")
            lines.append(
                f"[{i}] [{sim:.0%}] [{cite}] (paper: {h['paper_id']}, {h['chunk_type']})"
            )
            lines.append(f"    {h['text'][:300]}")
            lines.append("")

        return "\n".join(lines)

    @mcp.tool()
    async def tag_paper(paper_id: str, tags: str) -> str:
        """Add tags to a paper. New tags are appended to existing ones.

        Args:
            paper_id: The paper's ID
            tags: Comma-separated tags (e.g. 'deep-learning,convergence,key-paper')
        """
        paper = await db.get_paper(paper_id)
        if not paper:
            return "Paper not found in library."

        new_tags = [t.strip() for t in tags.split(",") if t.strip()]
        merged = list(set(paper.tags + new_tags))
        await db.update_paper(paper_id, tags=merged)
        return f"Tags updated: {', '.join(merged)}"

    @mcp.tool()
    async def remove_tag(paper_id: str, tag: str) -> str:
        """Remove a specific tag from a paper.

        Args:
            paper_id: The paper's ID
            tag: The tag to remove
        """
        paper = await db.get_paper(paper_id)
        if not paper:
            return "Paper not found in library."

        if tag not in paper.tags:
            return f"Tag '{tag}' not found on this paper. Current tags: {', '.join(paper.tags) or 'none'}"

        updated = [t for t in paper.tags if t != tag]
        await db.update_paper(paper_id, tags=updated)
        return f"Removed tag '{tag}'. Remaining tags: {', '.join(updated) or 'none'}"

    @mcp.tool()
    async def list_tags() -> str:
        """List all unique tags used across the library with paper counts."""
        papers = await db.list_papers(limit=500)
        tag_counts: dict[str, int] = {}
        for p in papers:
            for t in p.tags:
                tag_counts[t] = tag_counts.get(t, 0) + 1

        if not tag_counts:
            return "No tags in use."

        sorted_tags = sorted(tag_counts.items(), key=lambda x: -x[1])
        lines = [f"Tags in use ({len(sorted_tags)} unique):"]
        for tag, count in sorted_tags:
            lines.append(f"  {tag}: {count} paper{'s' if count != 1 else ''}")
        return "\n".join(lines)

    @mcp.tool()
    async def set_pillar(paper_id: str, pillar: str) -> str:
        """Assign a paper to a research pillar.

        Pillars are configured via setup_review(). If not configured, any
        string is accepted as a pillar name.

        Args:
            paper_id: The paper's ID
            pillar: Pillar name (e.g. 'pure_math', 'computational', 'financial')
        """
        configured = await db.get_pillars()
        if configured and pillar not in configured:
            suggestion = f" Configured pillars: {', '.join(configured)}."
            return f"Warning: '{pillar}' is not a configured pillar.{suggestion}\nUse setup_review() to update pillars, or pass a configured one."

        ok = await db.update_paper(paper_id, pillar=pillar)
        return f"Pillar set to '{pillar}'." if ok else "Paper not found."

    @mcp.tool()
    async def set_status(paper_id: str, status: str) -> str:
        """Update reading status for a paper.

        Args:
            paper_id: The paper's ID
            status: One of: unread, skimmed, read, deep_read
        """
        try:
            s = ReadingStatus(status)
        except ValueError:
            return f"Invalid status. Choose from: {', '.join(s.value for s in ReadingStatus)}"

        ok = await db.update_paper(paper_id, status=s)
        return f"Status set to '{status}'." if ok else "Paper not found."

    @mcp.tool()
    async def rate_paper(paper_id: str, relevance: int) -> str:
        """Rate a paper's relevance to your research (1-5).

        Args:
            paper_id: The paper's ID
            relevance: Rating from 1 (tangential) to 5 (essential)
        """
        if relevance < 1 or relevance > 5:
            return "Rating must be 1-5."
        ok = await db.update_paper(paper_id, relevance=relevance)
        return f"Relevance set to {relevance}/5." if ok else "Paper not found."

    @mcp.tool()
    async def assign_chapter(paper_id: str, chapter: str) -> str:
        """Assign a paper to a section or chapter.

        Args:
            paper_id: The paper's ID
            chapter: Section name (e.g. 'introduction', 'background', 'methodology') — any string is valid
        """
        ok = await db.update_paper(paper_id, chapter=chapter)
        return f"Assigned to chapter '{chapter}'." if ok else "Paper not found."

    @mcp.tool()
    async def annotate(paper_id: str, notes: str, append: bool = True) -> str:
        """Add or replace notes on a paper.

        Args:
            paper_id: The paper's ID
            notes: Your notes/annotations
            append: If True, append to existing notes. If False, replace them.
        """
        paper = await db.get_paper(paper_id)
        if not paper:
            return "Paper not found in library."

        if append and paper.notes:
            combined = paper.notes + "\n\n---\n\n" + notes
        else:
            combined = notes

        await db.update_paper(paper_id, notes=combined)
        return "Notes updated."

    @mcp.tool()
    async def set_extraction(
        paper_id: str,
        methodology: Optional[str] = None,
        limitations: Optional[str] = None,
        math_framework: Optional[str] = None,
        convergence_bounds: Optional[str] = None,
    ) -> str:
        """Set structured extraction fields for a paper.

        These are the 'Elicit-style' columns that make papers comparable at a glance.

        Args:
            paper_id: The paper's ID
            methodology: e.g. 'Deep Galerkin Method with ReLU networks'
            limitations: e.g. 'Unstable above 50 dimensions, no theoretical guarantees'
            math_framework: e.g. 'Viscosity solutions of HJB equations'
            convergence_bounds: e.g. 'O(N^{-1/2}) in L2 norm under Lipschitz assumption'
        """
        fields = {}
        if methodology is not None:
            fields["methodology"] = methodology
        if limitations is not None:
            fields["limitations"] = limitations
        if math_framework is not None:
            fields["math_framework"] = math_framework
        if convergence_bounds is not None:
            fields["convergence_bounds"] = convergence_bounds

        if not fields:
            return "No fields provided."

        ok = await db.update_paper(paper_id, **fields)
        return f"Extraction fields updated: {', '.join(fields.keys())}" if ok else "Paper not found."

    @mcp.tool()
    async def get_papers_by_chapter(chapter: str) -> str:
        """Get all papers assigned to a specific section or chapter.

        Args:
            chapter: Section name (e.g. 'introduction', 'background', 'methodology')
        """
        papers = await db.list_papers(chapter=chapter, sort_by="relevance")
        if not papers:
            return f"No papers assigned to chapter '{chapter}'."

        formatted = [await format_paper(p) for p in papers]
        return f"Chapter '{chapter}' ({len(papers)} papers):\n\n" + "\n\n---\n\n".join(formatted)

    @mcp.tool()
    async def get_papers_by_pillar(pillar: str) -> str:
        """Get all papers in a research pillar.

        Args:
            pillar: Pillar name
        """
        papers = await db.list_papers(pillar=pillar, sort_by="relevance")
        if not papers:
            return f"No papers in pillar '{pillar}'."

        formatted = [await format_paper(p) for p in papers]
        return f"Pillar '{pillar}' ({len(papers)} papers):\n\n" + "\n\n---\n\n".join(formatted)
