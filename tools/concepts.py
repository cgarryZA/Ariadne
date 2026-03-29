"""Concept graph and theorem dependency tools.

Phase 2.2: Move beyond paper-level citation networks to idea-level concept maps.
Phase 4.4: Build a DAG of mathematical dependencies (Theorem X relies on Lemma Y).

Maps concept→paper and concept→concept relationships, enabling queries like
"What replaced the Deep Galerkin method?" or "Which concepts bridge these pillars?"
"""

from __future__ import annotations

import json
import re
from typing import Optional

import db
from tools._llm_client import extract, is_available as llm_available


def register(mcp):

    @mcp.tool()
    async def extract_concepts(paper_id: str) -> str:
        """Extract key academic concepts from a paper and link them to the concept graph.

        If ANTHROPIC_API_KEY is set, uses the internal LLM for automated extraction.
        Otherwise formats the paper for manual concept tagging.

        Args:
            paper_id: The paper's ID
        """
        paper = await db.get_paper(paper_id)
        if not paper:
            return "Paper not found in library."

        existing = await db.get_concepts_for_paper(paper_id)

        # Build text for extraction
        text = f"Title: {paper.title}\n"
        if paper.abstract:
            text += f"Abstract: {paper.abstract}\n"
        if paper.methodology:
            text += f"Methodology: {paper.methodology}\n"
        if paper.key_findings:
            text += f"Key findings: {'; '.join(paper.key_findings)}\n"

        # If LLM available, auto-extract
        if llm_available():
            try:
                result = await extract(text, "extract_concepts")
                concepts = result.data.get("concepts", [])

                added = []
                for c in concepts:
                    name = c.get("name", "").strip()
                    relation = c.get("relation", "uses")
                    if not name:
                        continue
                    cid = await db.upsert_concept(name)
                    await db.link_concept_to_paper(cid, paper_id, relation)
                    added.append(f"  {name} ({relation})")

                if added:
                    return (
                        f"Extracted {len(added)} concepts from '{paper.title}':\n"
                        + "\n".join(added)
                        + f"\n\n[Model: {result.model_used}, confidence: {result.confidence_score}]"
                    )
                return "No concepts extracted. The paper may need more metadata."

            except Exception as e:
                return f"LLM extraction failed: {e}\nFalling back to manual mode."

        # Manual mode — format for Claude
        lines = [
            "CONCEPT EXTRACTION",
            f"Title: {paper.title}",
            f"Year: {paper.year or '?'}",
            "",
        ]
        if paper.abstract:
            lines += ["Abstract:", paper.abstract[:500], ""]
        if paper.methodology:
            lines += [f"Methodology: {paper.methodology}", ""]

        if existing:
            lines.append("Already linked concepts:")
            for c in existing:
                lines.append(f"  {c['name']} ({c['relation']})")
            lines.append("")

        lines += [
            "-" * 60,
            "TASK: Identify 3-8 key concepts from this paper.",
            "For each, specify the relationship:",
            "  introduces — paper introduces this concept for the first time",
            "  extends — paper extends or improves on this concept",
            "  applies — paper applies this concept to a problem",
            "  critiques — paper identifies problems with this concept",
            "  uses — paper uses this as a tool/framework",
            "",
            f"Then call: add_concept('{paper_id}', 'concept_name', 'relation')",
        ]

        return "\n".join(lines)

    @mcp.tool()
    async def add_concept(
        paper_id: str,
        concept_name: str,
        relation: str = "uses",
        description: Optional[str] = None,
    ) -> str:
        """Link a concept to a paper in the concept graph.

        Args:
            paper_id: The paper's ID
            concept_name: Name of the concept (e.g. 'Deep BSDE solver', 'Hamilton-Jacobi-Bellman equation')
            relation: One of: introduces, extends, applies, critiques, uses (default: uses)
            description: Optional brief description of the concept
        """
        valid_relations = {"introduces", "extends", "applies", "critiques", "uses"}
        if relation not in valid_relations:
            return f"Invalid relation '{relation}'. Choose from: {', '.join(sorted(valid_relations))}"

        paper = await db.get_paper(paper_id)
        if not paper:
            return "Paper not found."

        cid = await db.upsert_concept(concept_name, description=description)
        await db.link_concept_to_paper(cid, paper_id, relation)

        return f"Linked concept '{concept_name}' to '{paper.title[:50]}...' as '{relation}'."

    @mcp.tool()
    async def link_concepts(
        source_concept: str,
        target_concept: str,
        relation: str,
        paper_id: Optional[str] = None,
    ) -> str:
        """Create a directed edge between two concepts in the graph.

        Use this to encode that one concept extends, replaces, or contradicts another.

        Args:
            source_concept: Name of the source concept
            target_concept: Name of the target concept
            relation: Relationship type (e.g. 'extends', 'replaces', 'contradicts', 'requires', 'generalizes')
            paper_id: Optional paper that establishes this relationship
        """
        src_id = await db.upsert_concept(source_concept)
        tgt_id = await db.upsert_concept(target_concept)
        await db.add_concept_edge(src_id, tgt_id, relation, paper_id)

        return f"Edge created: '{source_concept}' --[{relation}]--> '{target_concept}'"

    @mcp.tool()
    async def query_concept(concept_name: str) -> str:
        """Look up a concept — which papers mention it and how it relates to other concepts.

        Args:
            concept_name: The concept to look up
        """
        papers = await db.get_papers_for_concept(concept_name)
        graph = await db.get_concept_graph()

        # Find the concept's node ID
        concept_id = None
        for node in graph["nodes"]:
            if node["name"].lower() == concept_name.lower():
                concept_id = node["id"]
                break

        lines = [f"CONCEPT: {concept_name}", ""]

        if papers:
            lines.append(f"Appears in {len(papers)} papers:")
            for p in papers:
                lines.append(f"  [{p['year'] or '?'}] {p['title'][:70]} ({p['relation']})")
        else:
            lines.append("Not found in any papers. Check the spelling or use add_concept() to link it.")
            return "\n".join(lines)

        # Find related concepts
        if concept_id:
            outgoing = [e for e in graph["edges"] if e["source_id"] == concept_id]
            incoming = [e for e in graph["edges"] if e["target_id"] == concept_id]

            node_names = {n["id"]: n["name"] for n in graph["nodes"]}

            if outgoing:
                lines.append(f"\nRelated concepts (outgoing):")
                for e in outgoing:
                    target_name = node_names.get(e["target_id"], "?")
                    lines.append(f"  --[{e['relation']}]--> {target_name}")

            if incoming:
                lines.append(f"\nReferenced by concepts (incoming):")
                for e in incoming:
                    source_name = node_names.get(e["source_id"], "?")
                    lines.append(f"  {source_name} --[{e['relation']}]-->")

        return "\n".join(lines)

    @mcp.tool()
    async def list_concepts(limit: int = 50) -> str:
        """List all concepts in the concept graph, ordered by paper count.

        Args:
            limit: Maximum concepts to return (default 50)
        """
        concepts = await db.list_concepts(limit=limit)

        if not concepts:
            return (
                "No concepts in the graph yet.\n"
                "Use extract_concepts(paper_id) to auto-extract from papers, "
                "or add_concept(paper_id, name, relation) to add manually."
            )

        lines = [f"CONCEPT GRAPH: {len(concepts)} concepts\n"]
        for c in concepts:
            lines.append(
                f"  {c['name']} ({c['concept_type']}) — {c['paper_count']} papers"
                + (f"\n    {c['description']}" if c.get("description") else "")
            )

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Phase 4.4: Theorem Dependency Graph
    # ------------------------------------------------------------------

    @mcp.tool()
    async def build_theorem_graph(paper_id: str) -> str:
        """Parse a paper's text for theorem dependencies and build a DAG.

        Finds patterns like "Proof of Theorem X relies on Lemma Y" and creates
        directed edges in the concept graph. Each theorem/lemma becomes a concept
        node. Works best with LaTeX-extracted text (Nougat/Mathpix).

        Args:
            paper_id: The paper's ID (must have fulltext stored)
        """
        paper = await db.get_paper(paper_id)
        if not paper:
            return "Paper not found in library."

        fulltext = await db.get_fulltext(paper_id)
        if not fulltext:
            return "No fulltext stored. Run download_pdf() first."

        cite = (paper.authors[0].name.split()[-1] if paper.authors else "?") + str(paper.year or "")

        # Check for structured math from LaTeX extraction
        math_data = {}
        if paper.math_framework:
            try:
                math_data = json.loads(paper.math_framework)
            except (json.JSONDecodeError, TypeError):
                pass

        # Find theorem/lemma/proposition references
        thm_refs = sorted(set(re.findall(
            r"(?:Theorem|Thm\.?)\s+(\d+(?:\.\d+)?)", fulltext, re.IGNORECASE
        )))
        lem_refs = sorted(set(re.findall(
            r"(?:Lemma|Lem\.?)\s+(\d+(?:\.\d+)?)", fulltext, re.IGNORECASE
        )))
        prop_refs = sorted(set(re.findall(
            r"(?:Proposition|Prop\.?)\s+(\d+(?:\.\d+)?)", fulltext, re.IGNORECASE
        )))

        # Find dependency patterns
        dep_patterns = [
            r"(?:relies on|uses|follows from|by)\s+(?:Theorem|Lemma|Proposition)\s+(\d+(?:\.\d+)?)",
            r"(?:Theorem|Lemma|Proposition)\s+(\d+(?:\.\d+)?)\s+(?:implies|gives|yields)",
        ]
        dependencies = []
        for pattern in dep_patterns:
            for m in re.finditer(pattern, fulltext, re.IGNORECASE):
                dependencies.append(m.group(0)[:150])

        # Also find cross-paper dependencies: "Lemma 3 from [4]" or "by [Author, Year]"
        cross_deps = re.findall(
            r"((?:Theorem|Lemma|Proposition)\s+\d+(?:\.\d+)?)\s+(?:from|in|of)\s+\[([^\]]+)\]",
            fulltext, re.IGNORECASE
        )

        # Create concept graph nodes
        nodes_created = 0
        edges_created = 0

        for num in thm_refs:
            cid = await db.upsert_concept(f"Theorem {num} [{cite}]", concept_type="theorem")
            await db.link_concept_to_paper(cid, paper_id, "introduces")
            nodes_created += 1

        for num in lem_refs:
            cid = await db.upsert_concept(f"Lemma {num} [{cite}]", concept_type="lemma")
            await db.link_concept_to_paper(cid, paper_id, "introduces")
            nodes_created += 1

        for num in prop_refs:
            cid = await db.upsert_concept(f"Proposition {num} [{cite}]", concept_type="proposition")
            await db.link_concept_to_paper(cid, paper_id, "introduces")
            nodes_created += 1

        # Parse intra-paper dependency edges
        for dep in dependencies:
            m = re.search(
                r"(Theorem|Lemma|Proposition)\s+(\d+(?:\.\d+)?)"
                r".*?(Theorem|Lemma|Proposition)\s+(\d+(?:\.\d+)?)",
                dep, re.IGNORECASE
            )
            if m:
                src = await db.upsert_concept(
                    f"{m.group(1).title()} {m.group(2)} [{cite}]",
                    concept_type=m.group(1).lower()
                )
                tgt = await db.upsert_concept(
                    f"{m.group(3).title()} {m.group(4)} [{cite}]",
                    concept_type=m.group(3).lower()
                )
                await db.add_concept_edge(src, tgt, "requires", paper_id)
                edges_created += 1

        lines = [
            f"THEOREM DEPENDENCY GRAPH: {paper.title}",
            f"Theorems: {len(thm_refs)} | Lemmas: {len(lem_refs)} | Propositions: {len(prop_refs)}",
            f"Dependencies detected: {len(dependencies)}",
            f"Cross-paper references: {len(cross_deps)}",
            f"Nodes created: {nodes_created} | Edges: {edges_created}",
            "",
        ]

        if math_data.get("theorems"):
            lines.append(f"LaTeX theorems ({len(math_data['theorems'])}):")
            for t in math_data["theorems"][:3]:
                lines.append(f"  {t[:120]}")
            lines.append("")

        if cross_deps:
            lines.append("Cross-paper dependencies:")
            for result_name, ref in cross_deps[:10]:
                lines.append(f"  {result_name} from [{ref}]")
            lines.append("")

        if nodes_created == 0:
            lines.append(
                "No theorems detected. For best results:\n"
                "  1. Download the PDF: download_pdf(paper_id)\n"
                "  2. Install Nougat for LaTeX extraction: pip install nougat-ocr torch"
            )
        else:
            lines.append("Use query_concept('Theorem X [Author2020]') to trace the chain.")

        return "\n".join(lines)
