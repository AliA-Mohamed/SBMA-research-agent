"""Use LLM to extract structured knowledge from articles (Ollama, Gemini, or Claude)."""

import sys
import json
import time
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
import config
from logger import setup_logger
from analysis.ollama_client import call_llm, parse_json_response

logger = setup_logger("knowledge_extractor")

# Context limits per backend: (knowledge_chars, fulltext_chars)
CONTEXT_LIMITS = {
    "ollama": (8000, 12000),
    "gemini": (50000, 100000),
    "claude": (100000, 150000),
}

# Rate-limit sleep per backend (seconds)
RATE_LIMIT_SLEEP = {
    "ollama": 0.5,
    "gemini": 2.0,
    "claude": 1.0,
}

CANONICAL_CHAPTERS = [
    "Chapter 1: Historical Discovery & Overview",
    "Chapter 2: Genetics & Molecular Biology",
    "Chapter 3: Pathophysiology & Disease Mechanisms",
    "Chapter 4: Clinical Features & Natural History",
    "Chapter 5: Diagnosis",
    "Chapter 6: Epidemiology",
    "Chapter 7: Animal & Cellular Models",
    "Chapter 8: Therapeutic Approaches",
    "Chapter 9: Biomarkers & Outcome Measures",
    "Chapter 10: Living with SBMA — Patient Perspectives & Quality of Life",
    "Chapter 11: Open Questions & Future Directions",
    "Chapter 12: Contradictions & Debates in the Field",
]

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

For each new finding, classify its knowledge_type as one of:
  mechanism, treatment, biomarker, clinical_feature, genetic, epidemiological,
  diagnostic, animal_model, cellular_model, case_report, review_synthesis, methodology

Return a structured JSON with:
- "new_findings": [list of objects, each with "summary", "knowledge_type", and "detail"]
  Example: {{"summary": "AR aggregates found in motor neurons", "knowledge_type": "mechanism", "detail": "..."}}
- "confirmations": [list of things that support existing knowledge]
- "contradictions": [list of things that contradict existing knowledge]
- "methodology_notes": "critical evaluation"
- "textbook_updates": {{"chapter_name": "new content to add with [PMID] citations"}}
  IMPORTANT: Use ONLY these exact canonical chapter names as keys:
{chapter_list}
  Most articles update 1-3 chapters. Do NOT default to Chapter 1 unless the article is truly about SBMA history/overview.
- "open_questions": [new questions raised by this article]
- "evidence_strength": "strong/moderate/weak/preliminary"
"""


class KnowledgeExtractor:
    """Extracts structured knowledge from articles using Ollama, Gemini, or Claude."""

    def __init__(self):
        self.backend = config.LLM_BACKEND

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

        knowledge_limit, fulltext_limit = CONTEXT_LIMITS.get(
            self.backend, (50000, 100000)
        )

        chapter_list = "\n".join(f"  - {ch}" for ch in CANONICAL_CHAPTERS)

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
            chapter_list=chapter_list,
        )

        max_retries = 5
        for attempt in range(max_retries):
            try:
                content = call_llm(
                    prompt=prompt,
                    mode="extraction",
                    json_mode=True,
                    max_tokens=config.CLAUDE_MAX_TOKENS if self.backend == "claude" else config.GEMINI_MAX_TOKENS,
                    temperature=0.3,
                )

                extracted = parse_json_response(content)
                if extracted:
                    logger.debug(f"Extracted knowledge from PMID {article.get('pmid')}")
                    return extracted
                else:
                    logger.warning(f"Failed to parse extraction for PMID {article.get('pmid')}")
                    return {"raw_response": content}

            except Exception as e:
                error_str = str(e)
                is_retryable = any(code in error_str for code in [
                    "503", "429", "UNAVAILABLE", "RESOURCE_EXHAUSTED", "overloaded"
                ])
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
