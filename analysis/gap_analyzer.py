"""Identify research gaps, unanswered questions, and contradictions."""

import sys
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
import config
from logger import setup_logger
from database.db_manager import DBManager
from analysis.ollama_client import call_llm, parse_json_response

logger = setup_logger("gap_analyzer")

GAP_ANALYSIS_PROMPT = """You are an expert SBMA (Spinal and Bulbar Muscular Atrophy) researcher analyzing the state of the field to identify knowledge gaps.

Here is the current state of the SBMA textbook, built from {total_articles} primary research articles:

{textbook_content}

Here are the open questions raised during knowledge extraction:
{open_questions}

Here are identified contradictions:
{contradictions}

Here is a citation lookup table mapping PMIDs to in-text citation labels. Use these to cite specific articles throughout your analysis:
{citation_table}

IMPORTANT CITATION INSTRUCTIONS:
- Throughout your analysis, cite specific articles using the format [Author et al., Year](PMID:12345678) where the PMID matches an entry from the citation table above.
- Every claim, contradiction, or gap should reference at least one relevant article from the knowledge base when possible.
- Use the citation table to find the correct author name and year for each PMID.
- If you mention a study's sample size, findings, or conclusions, ALWAYS cite it.

Please provide a comprehensive gap analysis:

1. **Under-researched Areas**: Topics with very few publications or weak evidence
   For each entry include: topic, description (with in-text citations), evidence_strength (absent/very_weak/weak), current_publications_estimate, related_pmids (array of PMIDs of the few existing studies)

2. **Unanswered Questions**: Specific scientific questions that remain open
   For each entry include: question, context (with in-text citations referencing specific studies), importance (critical/high/moderate), related_pmids

3. **Contradictions Needing Resolution**: Findings that disagree and need further investigation
   For each entry include: topic, contradiction (with in-text citations to the conflicting studies), possible_explanations (array), resolution_needed, priority (critical/high/moderate), study_a (object with pmid, finding), study_b (object with pmid, finding)

4. **Methodological Gaps**: Studies that need to be done (larger cohorts, longer follow-up, etc.)
   For each entry include: gap, description (with in-text citations), recommended_approach, related_pmids

5. **Translational Gaps**: Disconnect between basic science and clinical application
   For each entry include: gap, description (with in-text citations), recommended_actions (array), related_pmids

6. **Patient-Centered Gaps**: Missing research on quality of life, patient outcomes, caregiver burden
   For each entry include: gap, description (with in-text citations where applicable), priority (high/moderate), related_pmids

7. **Priority Rankings**: Rank the top 10 most important gaps to address
   For each entry include: rank, gap, rationale (with in-text citations), type (basic_science/translational/clinical/clinical_and_translational/epidemiological/patient_centered/patient_centered_and_basic_science), related_pmids

Return as structured JSON with these keys."""


class GapAnalyzer:
    """Analyzes the knowledge base to identify research gaps."""

    def __init__(self):
        self.db = DBManager()

    def _build_citation_table(self) -> tuple[str, dict]:
        """Build a PMID -> 'Author et al., Year' citation lookup table.

        Returns:
            Tuple of (formatted citation table string, pmid->citation dict)
        """
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
                # Extract last name (name format is "LastName FirstName")
                parts = name.split()
                first_author = parts[0] if parts else "Unknown"

            if len(authors) > 1:
                label = f"{first_author} et al., {a.publication_year}"
            else:
                label = f"{first_author}, {a.publication_year}"

            citation_map[a.pmid] = label
            lines.append(f"PMID:{a.pmid} = [{label}] — {(a.title or '')[:80]}")

        return "\n".join(lines), citation_map

    def analyze_gaps(self) -> dict:
        """Run full gap analysis on the knowledge base."""
        logger.info("Running research gap analysis...")

        # Get textbook content
        textbook = self.db.get_textbook_as_dict()
        textbook_content = "\n\n".join(
            f"### {chapter}\n{content[:3000]}"
            for chapter, content in textbook.items()
        )

        # Get open questions from extracted knowledge
        session = self.db.get_session()
        try:
            from database.models import ExtractedKnowledge
            knowledge = session.query(ExtractedKnowledge).all()
        finally:
            session.close()

        open_questions = []
        contradictions = []
        for ek in knowledge:
            if ek.novelty_at_publication and "question" in (ek.novelty_at_publication or "").lower():
                open_questions.append(f"{ek.summary or ''} (PMID:{ek.pmid})")
            if ek.contradicts:
                contradictions.append(
                    f"{ek.summary} (PMID:{ek.pmid}, contradicts: {ek.contradicts})"
                )

        # Build citation table
        citation_table, citation_map = self._build_citation_table()
        logger.info(f"Built citation table with {len(citation_map)} articles")

        prompt = GAP_ANALYSIS_PROMPT.format(
            total_articles=self.db.get_article_count(),
            textbook_content=textbook_content[:60000],
            open_questions="\n".join(f"- {q}" for q in open_questions[:100]),
            contradictions="\n".join(f"- {c}" for c in contradictions[:50]),
            citation_table=citation_table[:30000],
        )

        try:
            # Force Claude for gap analysis — higher quality than Gemini Flash Lite
            original_backend = config.LLM_BACKEND
            config.LLM_BACKEND = "claude"
            try:
                content = call_llm(
                    prompt=prompt,
                    mode="synthesis",
                    json_mode=True,
                    max_tokens=16384,
                    temperature=0.3,
                )
            finally:
                config.LLM_BACKEND = original_backend

            # Try to parse as JSON
            result = parse_json_response(content)
            if result:
                # Inject the citation_map so the frontend can resolve PMIDs to labels
                result["_citation_map"] = citation_map

                # Save report
                report_path = config.ANALYTICS_DIR / "gap_analysis.json"
                report_path.write_text(json.dumps(result, indent=2))

                # Also save markdown version
                md_path = config.ANALYTICS_DIR / "gap_analysis.md"
                md_path.write_text(f"# SBMA Research Gap Analysis\n\n{content}\n")

                logger.info(f"Gap analysis saved to {report_path}")
                return result
            else:
                # Save raw response
                md_path = config.ANALYTICS_DIR / "gap_analysis.md"
                md_path.write_text(f"# SBMA Research Gap Analysis\n\n{content}\n")
                logger.info(f"Gap analysis (raw) saved to {md_path}")
                return {"raw_analysis": content}

        except Exception as e:
            logger.error(f"Gap analysis failed: {e}")
            return {}
