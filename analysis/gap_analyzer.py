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

Please provide a comprehensive gap analysis:

1. **Under-researched Areas**: Topics with very few publications or weak evidence
2. **Unanswered Questions**: Specific scientific questions that remain open
3. **Contradictions Needing Resolution**: Findings that disagree and need further investigation
4. **Methodological Gaps**: Studies that need to be done (larger cohorts, longer follow-up, etc.)
5. **Translational Gaps**: Disconnect between basic science and clinical application
6. **Patient-Centered Gaps**: Missing research on quality of life, patient outcomes, caregiver burden
7. **Priority Rankings**: Rank the top 10 most important gaps to address

Return as structured JSON with these keys."""


class GapAnalyzer:
    """Analyzes the knowledge base to identify research gaps."""

    def __init__(self):
        self.db = DBManager()

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
                open_questions.append(ek.summary or "")
            if ek.contradicts:
                contradictions.append(f"{ek.summary} (contradicts: {ek.contradicts})")

        prompt = GAP_ANALYSIS_PROMPT.format(
            total_articles=self.db.get_article_count(),
            textbook_content=textbook_content[:60000],
            open_questions="\n".join(f"- {q}" for q in open_questions[:100]),
            contradictions="\n".join(f"- {c}" for c in contradictions[:50]),
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
                    max_tokens=8192,
                    temperature=0.3,
                )
            finally:
                config.LLM_BACKEND = original_backend

            # Try to parse as JSON
            result = parse_json_response(content)
            if result:
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
