"""Score new articles against the existing knowledge base for novelty."""

import sys
import json
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
import config
from logger import setup_logger
from database.db_manager import DBManager
from analysis.ollama_client import OllamaClient, parse_json_response

logger = setup_logger("novelty_scorer")

NOVELTY_PROMPT = """You are an expert SBMA (Spinal and Bulbar Muscular Atrophy) researcher evaluating a newly published article.

EXISTING KNOWLEDGE BASE SUMMARY:
{knowledge_summary}

NEW ARTICLE:
Title: {title}
Authors: {authors}
Journal: {journal}
Year: {year}
Abstract: {abstract}

EVALUATE THIS ARTICLE:
1. **Novelty Score (1-10)**: How genuinely new is the information? (1=entirely confirmatory, 10=paradigm shifting)
2. **Category**: Classify as one of: "high_impact", "confirmatory", "contradiction", "review", "clinical_trial", "case_report", "methodology"
3. **New Information**: What specific new information does this add?
4. **Confirms**: What existing knowledge does it support?
5. **Contradicts**: Does it challenge any existing findings?
6. **Clinical Relevance**: Direct relevance to patient care (1-10)
7. **Methodology Assessment**: Brief critical evaluation of study design
8. **Key Takeaway**: One-sentence summary of what this means for the field
9. **Textbook Updates Needed**: Which chapters of our SBMA textbook should be updated?
10. **New Questions Raised**: Any new research questions this opens up?

Return as structured JSON."""


class NoveltyScorer:
    """Scores new articles for novelty against the existing knowledge base."""

    def __init__(self):
        self.db = DBManager()
        self._use_ollama = config.LLM_BACKEND == "ollama"
        if self._use_ollama:
            self.client = OllamaClient(model=config.OLLAMA_EXTRACTION_MODEL)
        else:
            from google import genai
            self.client = genai.Client(api_key=config.GEMINI_API_KEY)

    def score_article(self, article: dict) -> Optional[dict]:
        """Score a single article for novelty.

        Args:
            article: Article dict with title, abstract, authors, etc.

        Returns:
            Dict with novelty scoring results.
        """
        # Build knowledge summary
        textbook = self.db.get_textbook_as_dict()
        knowledge_summary = "\n".join(
            f"### {ch}\n{content[:2000]}"
            for ch, content in textbook.items()
        )

        if not knowledge_summary:
            knowledge_summary = "Knowledge base is empty or not yet built."

        authors_str = ", ".join(
            a.get("name", "") if isinstance(a, dict) else str(a)
            for a in (article.get("authors") or [])[:10]
        )

        prompt = NOVELTY_PROMPT.format(
            knowledge_summary=knowledge_summary[:40000],
            title=article.get("title", ""),
            authors=authors_str,
            journal=article.get("journal", ""),
            year=article.get("publication_year", ""),
            abstract=article.get("abstract", "No abstract available"),
        )

        try:
            if self._use_ollama:
                content = self.client.generate(
                    prompt=prompt,
                    max_tokens=2048,
                    temperature=0.3,
                    json_mode=True,
                )
            else:
                response = self.client.models.generate_content(
                    model=config.GEMINI_EXTRACTION_MODEL,
                    contents=prompt,
                    config={
                        "max_output_tokens": 2048,
                        "response_mime_type": "application/json",
                    },
                )
                content = response.text

            result = parse_json_response(content)
            if result:
                result["pmid"] = article.get("pmid", "")
                return result
            return {"raw_response": content, "pmid": article.get("pmid", "")}

        except Exception as e:
            logger.error(f"Novelty scoring failed for {article.get('pmid')}: {e}")
            return None

    def score_articles(self, articles: list[dict]) -> list[dict]:
        """Score multiple articles. Returns list of scoring results."""
        results = []
        for article in articles:
            score = self.score_article(article)
            if score:
                results.append(score)
        return results
