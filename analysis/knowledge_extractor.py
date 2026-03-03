"""Use LLM to extract structured knowledge from articles (Ollama or Gemini)."""

import sys
import json
import time
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
import config
from logger import setup_logger
from analysis.ollama_client import OllamaClient, parse_json_response

logger = setup_logger("knowledge_extractor")


EXTRACTION_SYSTEM_PROMPT = """You are an expert SBMA researcher building a comprehensive textbook about Spinal and Bulbar Muscular Atrophy. You have deep knowledge of neuroscience, genetics, molecular biology, and clinical medicine.

You are reviewing article #{article_num} of {total} in chronological order.

HERE IS THE CURRENT STATE OF KNOWLEDGE (everything established by previous articles):
{current_knowledge}

NOW REVIEW THIS NEW ARTICLE:
Title: {title}
Authors: {authors}
Journal: {journal}
Year: {year}
Abstract: {abstract}
Full Text: {fulltext}

YOUR TASKS:
1. EXTRACT all factual claims, findings, and conclusions from this article
2. IDENTIFY what is GENUINELY NEW — information not already in our knowledge base
3. IDENTIFY if anything CONTRADICTS existing knowledge — flag it clearly
4. IDENTIFY if anything SUPPORTS/CONFIRMS existing knowledge — note the additional evidence
5. CRITICALLY EVALUATE the methodology and strength of evidence
6. UPDATE the relevant textbook chapters with new information, citing this article

Return a structured JSON with:
- "new_findings": [list of genuinely new information]
- "confirmations": [list of things that support existing knowledge]
- "contradictions": [list of things that contradict existing knowledge]
- "methodology_notes": "critical evaluation"
- "textbook_updates": {{"chapter_name": "new content to add with [PMID] citations"}}
- "open_questions": [new questions raised by this article]
- "evidence_strength": "strong/moderate/weak/preliminary"
"""


class KnowledgeExtractor:
    """Extracts structured knowledge from articles using Ollama or Gemini."""

    def __init__(self):
        if config.LLM_BACKEND == "ollama":
            self.client = OllamaClient(model=config.OLLAMA_EXTRACTION_MODEL)
            self._use_ollama = True
        else:
            from google import genai
            self.client = genai.Client(api_key=config.GEMINI_API_KEY)
            self._use_ollama = False

    def extract_from_article(
        self,
        article: dict,
        article_num: int,
        total: int,
        current_knowledge: str,
        fulltext: str = "",
    ) -> Optional[dict]:
        """Extract knowledge from a single article.

        Args:
            article: Article dict with pmid, title, abstract, authors, etc.
            article_num: Position in chronological order.
            total: Total number of articles.
            current_knowledge: Summary of knowledge accumulated so far.
            fulltext: Full text content if available.

        Returns:
            Parsed JSON dict with extraction results, or None on failure.
        """
        authors_str = ", ".join(
            a.get("name", "") if isinstance(a, dict) else str(a)
            for a in (article.get("authors") or [])[:10]
        )

        # Ollama uses smaller context truncation for better quality with 8B model
        if self._use_ollama:
            knowledge_limit = 8000
            fulltext_limit = 12000
        else:
            knowledge_limit = 50000
            fulltext_limit = 100000

        prompt = EXTRACTION_SYSTEM_PROMPT.format(
            article_num=article_num,
            total=total,
            current_knowledge=current_knowledge[:knowledge_limit],
            title=article.get("title", ""),
            authors=authors_str,
            journal=article.get("journal", ""),
            year=article.get("publication_year", ""),
            abstract=article.get("abstract", "No abstract available"),
            fulltext=fulltext[:fulltext_limit] if fulltext else "Not available",
        )

        max_retries = 5
        for attempt in range(max_retries):
            try:
                if self._use_ollama:
                    content = self.client.generate(
                        prompt=prompt,
                        max_tokens=config.GEMINI_MAX_TOKENS,
                        temperature=0.3,
                        json_mode=True,
                    )
                else:
                    response = self.client.models.generate_content(
                        model=config.GEMINI_EXTRACTION_MODEL,
                        contents=prompt,
                        config={
                            "max_output_tokens": config.GEMINI_MAX_TOKENS,
                            "response_mime_type": "application/json",
                        },
                    )
                    content = response.text

                extracted = parse_json_response(content)
                if extracted:
                    logger.debug(f"Extracted knowledge from PMID {article.get('pmid')}")
                    return extracted
                else:
                    logger.warning(f"Failed to parse extraction for PMID {article.get('pmid')}")
                    return {"raw_response": content}

            except Exception as e:
                error_str = str(e)
                is_retryable = any(code in error_str for code in ["503", "429", "UNAVAILABLE", "RESOURCE_EXHAUSTED"])
                if is_retryable and attempt < max_retries - 1:
                    wait_time = min(2 ** attempt * 5, 60)
                    logger.warning(
                        f"Retryable error for PMID {article.get('pmid')} "
                        f"(attempt {attempt + 1}/{max_retries}), waiting {wait_time}s: {error_str[:100]}"
                    )
                    time.sleep(wait_time)
                    continue
                logger.error(f"LLM API error for PMID {article.get('pmid')}: {e}")
                return None

        return None
