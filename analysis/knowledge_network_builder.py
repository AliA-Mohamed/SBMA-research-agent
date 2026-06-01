"""Build knowledge networks, pathways, and hypotheses from the extracted knowledge base.

For each textbook chapter (cluster), this module:
1. Collects all knowledge entries linked to that chapter's contributing PMIDs
2. Sends the cluster to Claude to generate:
   - Knowledge network (nodes + edges)
   - Molecular/clinical pathways
   - Testable hypotheses
   - Gaps visible from the network structure
3. Runs a cross-cluster synthesis to find inter-chapter gaps
"""

import sys
import json
import time
from pathlib import Path
from collections import defaultdict

sys.path.insert(0, str(Path(__file__).parent.parent))
import config
from logger import setup_logger
from database.db_manager import DBManager
from analysis.ollama_client import call_llm, parse_json_response

logger = setup_logger("knowledge_network_builder")

# ── Prompt for per-chapter network analysis ──────────────────────────────

CHAPTER_NETWORK_PROMPT = """You are an expert SBMA (Spinal and Bulbar Muscular Atrophy) researcher performing a deep knowledge-network analysis of a specific research domain.

CHAPTER: {chapter_name}

Below are {n_entries} extracted knowledge entries from {n_articles} articles contributing to this chapter.
Each entry has a type, summary, confidence score, and source PMID.

{knowledge_entries}

CITATION TABLE (use for in-text references):
{citation_table}

──────────────────────────────────────────────
YOUR TASKS — analyze this knowledge cluster and produce:

1. **knowledge_network**: Build a network of concepts and their relationships.
   Return as:
   - "nodes": array of objects, each with:
     - "id": short unique identifier (e.g., "ar_aggregation", "cag_repeat_length")
     - "label": human-readable name
     - "type": one of "molecule", "gene", "pathway", "phenotype", "biomarker", "treatment", "cell_type", "animal_model", "clinical_feature", "mechanism", "concept"
     - "evidence_strength": "strong" | "moderate" | "weak" (based on how many studies support it)
     - "key_pmids": array of up to 5 most relevant PMIDs
   - "edges": array of objects, each with:
     - "source": node id
     - "target": node id
     - "relationship": verb phrase (e.g., "causes", "inhibits", "correlates_with", "is_biomarker_for", "treats")
     - "evidence_strength": "strong" | "moderate" | "weak"
     - "pmids": array of supporting PMIDs

2. **pathways**: Identify the key molecular/clinical/biological pathways relevant to this chapter.
   For each pathway:
   - "name": pathway name
   - "steps": ordered array of step descriptions with citations
   - "key_molecules": array of molecules/genes involved
   - "therapeutic_targets": any known or potential drug targets in this pathway
   - "evidence_level": "well_established" | "emerging" | "hypothetical"
   - "pmids": supporting PMIDs

3. **hypotheses**: Generate testable research hypotheses based on patterns, weak edges, or incomplete pathways you observe.
   For each hypothesis:
   - "hypothesis": clear statement of the hypothesis
   - "rationale": why the knowledge network suggests this (with citations)
   - "supporting_evidence": what existing data supports this
   - "type": "mechanistic" | "therapeutic" | "biomarker" | "clinical" | "translational"
   - "testability": "immediate" (can test with existing tools) | "near_term" (1-3 years) | "long_term" (requires new tech/methods)
   - "priority": "high" | "medium" | "low"
   - "related_pmids": PMIDs of studies that partially address this

4. **cluster_gaps**: Gaps visible FROM THE NETWORK STRUCTURE — look for:
   - Nodes with very few connections (isolated concepts)
   - Missing edges that should logically exist
   - Pathways with missing steps
   - Strong nodes connected only by weak edges
   - Concepts mentioned but never experimentally validated
   For each gap:
   - "gap": description
   - "type": "missing_link" | "weak_evidence" | "untested_hypothesis" | "isolated_concept" | "incomplete_pathway"
   - "between_nodes": array of node IDs this gap connects (if applicable)
   - "suggested_experiment": what experiment could fill this gap
   - "priority": "critical" | "high" | "moderate"
   - "related_pmids": relevant existing PMIDs

Return ONLY valid JSON with keys: knowledge_network, pathways, hypotheses, cluster_gaps"""


# ── Prompt for cross-cluster gap synthesis ────────────────────────────────

CROSS_CLUSTER_PROMPT = """You are an expert SBMA researcher analyzing the COMPLETE knowledge landscape across all research domains.

Below is a summary of knowledge networks, pathways, hypotheses, and gaps from each of the 12 chapters of the SBMA textbook:

{chapter_summaries}

──────────────────────────────────────────────
YOUR TASKS — perform a cross-cluster synthesis:

1. **cross_cluster_gaps**: Identify gaps that only become visible when looking ACROSS chapters.
   Look for:
   - Pathways in one chapter that should connect to another chapter but don't
   - Biomarkers (Ch 9) not linked to mechanisms (Ch 3) or treatments (Ch 8)
   - Animal models (Ch 7) not translating to clinical features (Ch 4)
   - Treatments (Ch 8) with unclear mechanisms (Ch 3)
   - Genetic findings (Ch 2) not reflected in diagnostic criteria (Ch 5)
   For each:
   - "gap": description
   - "chapters_involved": array of chapter names
   - "type": "translation_gap" | "missing_connection" | "validation_gap" | "bidirectional_gap"
   - "priority": "critical" | "high" | "moderate"
   - "suggested_approach": how to address this

2. **integrative_hypotheses**: Hypotheses that span multiple chapters/domains.
   For each:
   - "hypothesis": statement
   - "rationale": why cross-domain evidence suggests this
   - "chapters_involved": array
   - "type": "mechanistic" | "therapeutic" | "biomarker" | "clinical" | "translational"
   - "priority": "high" | "medium" | "low"

3. **research_roadmap**: Based on all the gaps and hypotheses, suggest a prioritized research agenda.
   Return array of objects:
   - "rank": 1-15
   - "initiative": short title
   - "description": what needs to be done
   - "type": "basic_science" | "translational" | "clinical_trial" | "epidemiological" | "methodological" | "patient_centered"
   - "prerequisites": what must be done first
   - "estimated_impact": "transformative" | "high" | "moderate"
   - "chapters_addressed": which chapters this would contribute to

4. **network_statistics**: Summary statistics across all chapters.
   - "total_nodes": int
   - "total_edges": int
   - "most_connected_nodes": top 10 nodes by degree across all networks
   - "weakest_links": edges with lowest evidence that connect important nodes
   - "orphan_nodes": concepts that appear in only one chapter with few connections

Return ONLY valid JSON with keys: cross_cluster_gaps, integrative_hypotheses, research_roadmap, network_statistics"""


class KnowledgeNetworkBuilder:
    """Builds knowledge networks, pathways, and hypotheses from the knowledge base."""

    def __init__(self):
        self.db = DBManager()

    def _build_citation_table(self) -> tuple[str, dict]:
        """Build PMID -> 'Author et al., Year' citation lookup."""
        session = self.db.get_session()
        try:
            from database.models import Article
            articles = session.query(
                Article.pmid, Article.authors, Article.publication_year, Article.title
            ).all()
        finally:
            session.close()

        citation_map = {}
        lines = []
        for a in articles:
            authors = a.authors or []
            if not authors:
                first_author = "Unknown"
            else:
                name = authors[0].get("name", "Unknown")
                parts = name.split()
                first_author = parts[0] if parts else "Unknown"

            label = (
                f"{first_author} et al., {a.publication_year}"
                if len(authors) > 1
                else f"{first_author}, {a.publication_year}"
            )
            citation_map[a.pmid] = label
            lines.append(f"PMID:{a.pmid} = [{label}] — {(a.title or '')[:80]}")

        return "\n".join(lines), citation_map

    def _get_chapter_knowledge(self) -> dict[str, list[dict]]:
        """Group knowledge entries by textbook chapter via contributing_pmids.

        Returns:
            {chapter_name: [knowledge_entry_dicts]}
        """
        # Get textbook sections with their contributing PMIDs
        sections = self.db.get_textbook_sections()
        chapter_pmids = {}
        for s in sections:
            chapter_pmids[s.chapter] = set(s.contributing_pmids or [])

        # Get all knowledge entries
        session = self.db.get_session()
        try:
            from database.models import ExtractedKnowledge
            all_knowledge = session.query(ExtractedKnowledge).all()

            # Build PMID -> knowledge entries index
            pmid_knowledge = defaultdict(list)
            for ek in all_knowledge:
                pmid_knowledge[ek.pmid].append({
                    "id": ek.id,
                    "pmid": ek.pmid,
                    "knowledge_type": ek.knowledge_type,
                    "summary": ek.summary,
                    "confidence": ek.confidence,
                    "novelty": ek.novelty_at_publication,
                })
        finally:
            session.close()

        # Map knowledge to chapters
        chapter_knowledge = {}
        for chapter, pmids in chapter_pmids.items():
            entries = []
            for pmid in pmids:
                entries.extend(pmid_knowledge.get(pmid, []))
            chapter_knowledge[chapter] = entries

        return chapter_knowledge

    def _format_knowledge_entries(self, entries: list[dict], max_chars: int = 80000) -> str:
        """Format knowledge entries for the prompt."""
        lines = []
        total = 0
        for e in entries:
            line = (
                f"- [{e['knowledge_type']}] (conf={e['confidence']:.1f}, PMID:{e['pmid']}) "
                f"{e['summary']}"
            )
            total += len(line)
            if total > max_chars:
                lines.append(f"... ({len(entries) - len(lines)} more entries truncated)")
                break
            lines.append(line)
        return "\n".join(lines)

    def analyze_chapter(
        self, chapter_name: str, entries: list[dict], citation_table: str
    ) -> dict:
        """Analyze a single chapter cluster and return its knowledge network."""
        logger.info(f"Analyzing chapter: {chapter_name} ({len(entries)} entries)")

        if not entries:
            logger.warning(f"No knowledge entries for {chapter_name} — skipping")
            return {}

        # Deduplicate by summary to reduce noise
        seen = set()
        unique_entries = []
        for e in entries:
            key = (e["summary"] or "")[:100]
            if key not in seen:
                seen.add(key)
                unique_entries.append(e)

        # Count unique articles
        article_pmids = set(e["pmid"] for e in unique_entries)

        formatted = self._format_knowledge_entries(unique_entries)

        prompt = CHAPTER_NETWORK_PROMPT.format(
            chapter_name=chapter_name,
            n_entries=len(unique_entries),
            n_articles=len(article_pmids),
            knowledge_entries=formatted,
            citation_table=citation_table[:20000],
        )

        # Force Claude for quality
        original_backend = config.LLM_BACKEND
        config.LLM_BACKEND = "claude"
        try:
            content = call_llm(
                prompt=prompt,
                mode="synthesis",
                json_mode=True,
                max_tokens=32768,
                temperature=0.3,
            )
        finally:
            config.LLM_BACKEND = original_backend

        result = parse_json_response(content)
        if not result:
            logger.error(f"Failed to parse network for {chapter_name}")
            return {"raw_response": content}

        # Attach metadata
        result["_meta"] = {
            "chapter": chapter_name,
            "total_entries": len(entries),
            "unique_entries": len(unique_entries),
            "articles": len(article_pmids),
        }

        return result

    def cross_cluster_synthesis(self, chapter_results: dict) -> dict:
        """Run cross-cluster gap analysis across all chapter networks."""
        logger.info("Running cross-cluster synthesis...")

        # Build chapter summaries for the prompt
        summaries = []
        for chapter, result in chapter_results.items():
            if not result or "raw_response" in result:
                continue

            meta = result.get("_meta", {})
            network = result.get("knowledge_network", {})
            n_nodes = len(network.get("nodes", []))
            n_edges = len(network.get("edges", []))
            n_pathways = len(result.get("pathways", []))
            n_hypotheses = len(result.get("hypotheses", []))
            n_gaps = len(result.get("cluster_gaps", []))

            # Summarize top nodes
            top_nodes = sorted(
                network.get("nodes", []),
                key=lambda n: len(n.get("key_pmids", [])),
                reverse=True,
            )[:10]
            node_summary = ", ".join(n.get("label", n.get("id", "?")) for n in top_nodes)

            # Summarize pathways
            pathway_names = [p.get("name", "?") for p in result.get("pathways", [])]

            # Summarize hypotheses
            hyp_summaries = [h.get("hypothesis", "")[:100] for h in result.get("hypotheses", [])]

            # Summarize gaps
            gap_summaries = [g.get("gap", "")[:100] for g in result.get("cluster_gaps", [])]

            summary = (
                f"## {chapter}\n"
                f"Articles: {meta.get('articles', '?')}, "
                f"Knowledge entries: {meta.get('unique_entries', '?')}\n"
                f"Network: {n_nodes} nodes, {n_edges} edges\n"
                f"Key concepts: {node_summary}\n"
                f"Pathways ({n_pathways}): {'; '.join(pathway_names)}\n"
                f"Hypotheses ({n_hypotheses}):\n"
                + "\n".join(f"  - {h}" for h in hyp_summaries)
                + f"\nGaps ({n_gaps}):\n"
                + "\n".join(f"  - {g}" for g in gap_summaries)
            )
            summaries.append(summary)

        prompt = CROSS_CLUSTER_PROMPT.format(
            chapter_summaries="\n\n".join(summaries)
        )

        original_backend = config.LLM_BACKEND
        config.LLM_BACKEND = "claude"
        try:
            content = call_llm(
                prompt=prompt,
                mode="synthesis",
                json_mode=True,
                max_tokens=32768,
                temperature=0.3,
            )
        finally:
            config.LLM_BACKEND = original_backend

        result = parse_json_response(content)
        if not result:
            logger.error("Failed to parse cross-cluster synthesis")
            return {"raw_response": content}

        return result

    def run(self, chapters: list[str] = None) -> dict:
        """Run the full knowledge network analysis pipeline.

        Args:
            chapters: Optional list of chapter names to analyze. If None, all chapters.

        Returns:
            Full analysis dict with per-chapter and cross-cluster results.
        """
        logger.info("=" * 60)
        logger.info("Starting Knowledge Network Analysis")
        logger.info("=" * 60)

        # Build citation table (shared across all chapters)
        citation_table, citation_map = self._build_citation_table()
        logger.info(f"Citation table: {len(citation_map)} articles")

        # Get knowledge grouped by chapter
        chapter_knowledge = self._get_chapter_knowledge()
        logger.info(
            f"Chapters: {len(chapter_knowledge)}, "
            f"total entries: {sum(len(v) for v in chapter_knowledge.values())}"
        )

        # Filter to requested chapters
        if chapters:
            chapter_knowledge = {
                ch: entries
                for ch, entries in chapter_knowledge.items()
                if ch in chapters
            }

        # Analyze each chapter
        chapter_results = {}
        output_dir = config.ANALYTICS_DIR / "knowledge_networks"
        output_dir.mkdir(parents=True, exist_ok=True)

        for i, (chapter, entries) in enumerate(sorted(chapter_knowledge.items()), 1):
            logger.info(f"\n[{i}/{len(chapter_knowledge)}] {chapter}")

            result = self.analyze_chapter(chapter, entries, citation_table)
            chapter_results[chapter] = result

            # Save per-chapter result
            safe_name = chapter.replace(" ", "_").replace("/", "_").replace("&", "and")
            chapter_path = output_dir / f"{safe_name}.json"
            chapter_path.write_text(json.dumps(result, indent=2))
            logger.info(f"  Saved to {chapter_path.name}")

            # Rate limit between chapters
            if i < len(chapter_knowledge):
                time.sleep(2)

        # Cross-cluster synthesis
        cross_cluster = self.cross_cluster_synthesis(chapter_results)

        # Save cross-cluster result
        cross_path = output_dir / "cross_cluster_synthesis.json"
        cross_path.write_text(json.dumps(cross_cluster, indent=2))
        logger.info(f"Cross-cluster synthesis saved to {cross_path.name}")

        # Assemble full output
        full_result = {
            "chapters": chapter_results,
            "cross_cluster": cross_cluster,
            "_citation_map": citation_map,
            "_meta": {
                "total_chapters": len(chapter_results),
                "total_knowledge_entries": sum(
                    r.get("_meta", {}).get("unique_entries", 0)
                    for r in chapter_results.values()
                    if isinstance(r, dict)
                ),
            },
        }

        # Save consolidated output
        full_path = output_dir / "knowledge_networks_full.json"
        full_path.write_text(json.dumps(full_result, indent=2))
        logger.info(f"\nFull analysis saved to {full_path}")

        # Generate markdown summary
        self._write_markdown_summary(full_result, output_dir)

        return full_result

    def _write_markdown_summary(self, result: dict, output_dir: Path):
        """Write a human-readable markdown summary."""
        lines = ["# SBMA Knowledge Network Analysis\n"]

        for chapter, data in sorted(result.get("chapters", {}).items()):
            if not isinstance(data, dict) or "raw_response" in data:
                continue

            meta = data.get("_meta", {})
            network = data.get("knowledge_network", {})
            lines.append(f"\n## {chapter}")
            lines.append(
                f"*{meta.get('articles', '?')} articles, "
                f"{meta.get('unique_entries', '?')} knowledge entries, "
                f"{len(network.get('nodes', []))} network nodes, "
                f"{len(network.get('edges', []))} edges*\n"
            )

            # Pathways
            pathways = data.get("pathways", [])
            if pathways:
                lines.append("### Pathways")
                for p in pathways:
                    level = p.get("evidence_level", "")
                    lines.append(f"- **{p.get('name', '?')}** ({level})")
                    for step in p.get("steps", []):
                        lines.append(f"  1. {step}")
                lines.append("")

            # Hypotheses
            hypotheses = data.get("hypotheses", [])
            if hypotheses:
                lines.append("### Hypotheses")
                for h in hypotheses:
                    pri = h.get("priority", "")
                    htype = h.get("type", "")
                    lines.append(f"- **[{pri}/{htype}]** {h.get('hypothesis', '?')}")
                    lines.append(f"  *Rationale:* {h.get('rationale', '')}")
                lines.append("")

            # Gaps
            gaps = data.get("cluster_gaps", [])
            if gaps:
                lines.append("### Gaps")
                for g in gaps:
                    pri = g.get("priority", "")
                    gtype = g.get("type", "")
                    lines.append(f"- **[{pri}/{gtype}]** {g.get('gap', '?')}")
                    exp = g.get("suggested_experiment", "")
                    if exp:
                        lines.append(f"  *Suggested experiment:* {exp}")
                lines.append("")

        # Cross-cluster section
        cross = result.get("cross_cluster", {})
        if cross and "raw_response" not in cross:
            lines.append("\n---\n## Cross-Cluster Analysis\n")

            for gap in cross.get("cross_cluster_gaps", []):
                chapters_str = ", ".join(gap.get("chapters_involved", []))
                lines.append(
                    f"- **[{gap.get('priority', '')}]** {gap.get('gap', '?')} "
                    f"({chapters_str})"
                )
            lines.append("")

            lines.append("### Integrative Hypotheses")
            for h in cross.get("integrative_hypotheses", []):
                lines.append(f"- **{h.get('hypothesis', '?')}**")
                lines.append(f"  *Rationale:* {h.get('rationale', '')}")
            lines.append("")

            roadmap = cross.get("research_roadmap", [])
            if roadmap:
                lines.append("### Research Roadmap")
                for item in roadmap:
                    lines.append(
                        f"{item.get('rank', '?')}. **{item.get('initiative', '?')}** "
                        f"({item.get('type', '')})"
                    )
                    lines.append(f"   {item.get('description', '')}")
                    lines.append(f"   *Impact:* {item.get('estimated_impact', '')}")

        md_path = output_dir / "knowledge_networks_summary.md"
        md_path.write_text("\n".join(lines))
        logger.info(f"Markdown summary saved to {md_path}")
