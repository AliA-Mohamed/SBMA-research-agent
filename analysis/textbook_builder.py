"""Chronological knowledge accumulation → textbook builder."""

import sys
import json
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

from tqdm import tqdm

sys.path.insert(0, str(Path(__file__).parent.parent))
import config
from logger import setup_logger
from database.db_manager import DBManager
from analysis.knowledge_extractor import KnowledgeExtractor
from analysis.ollama_client import OllamaClient

logger = setup_logger("textbook_builder")

# Chapter structure
CHAPTERS = [
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

CHAPTER_SECTIONS = {
    "Chapter 2: Genetics & Molecular Biology": [
        "2.1 The Androgen Receptor Gene",
        "2.2 CAG Repeat Expansion",
        "2.3 Genotype-Phenotype Correlations",
    ],
    "Chapter 3: Pathophysiology & Disease Mechanisms": [
        "3.1 Protein Misfolding & Aggregation",
        "3.2 Transcriptional Dysregulation",
        "3.3 Mitochondrial Dysfunction",
        "3.4 Muscle vs. Neuronal Pathology",
    ],
    "Chapter 4: Clinical Features & Natural History": [
        "4.1 Motor Symptoms",
        "4.2 Sensory Involvement",
        "4.3 Endocrine Features",
        "4.4 Disease Progression",
    ],
    "Chapter 5: Diagnosis": [
        "5.1 Clinical Criteria",
        "5.2 Genetic Testing",
        "5.3 Electrophysiology",
        "5.4 Biomarkers",
        "5.5 Differential Diagnosis",
    ],
    "Chapter 8: Therapeutic Approaches": [
        "8.1 Hormonal Therapies",
        "8.2 Gene Therapy",
        "8.3 Small Molecules",
        "8.4 Clinical Trials (with outcomes)",
        "8.5 Symptomatic Management",
    ],
}

SYNTHESIS_PROMPT = """You are an expert SBMA researcher synthesizing a comprehensive textbook chapter.

Given the following accumulated knowledge updates for the chapter "{chapter}", synthesize them into a cohesive, well-structured chapter section.

The content should:
1. Be written in clear academic prose suitable for a medical textbook
2. Maintain chronological awareness (note when discoveries were made)
3. Cite articles using [PMID:xxxxx] format
4. Flag any contradictions or debates
5. Distinguish between well-established facts and preliminary findings

KNOWLEDGE UPDATES:
{updates}

Write the synthesized chapter content in Markdown format."""


class TextbookBuilder:
    """Builds the SBMA textbook by processing articles chronologically."""

    def __init__(self):
        self.db = DBManager()
        self.extractor = KnowledgeExtractor()
        self._use_ollama = config.LLM_BACKEND == "ollama"
        if self._use_ollama:
            self.client = OllamaClient(model=config.OLLAMA_SYNTHESIS_MODEL)
        else:
            from google import genai
            self.client = genai.Client(api_key=config.GEMINI_API_KEY)
        self.checkpoint_file = config.CHECKPOINTS_DIR / "textbook_builder_checkpoint.json"

    def build_textbook(self, resume: bool = True, limit: int = 0):
        """Main entry: process all articles chronologically and build the textbook.

        Args:
            resume: If True, resume from last checkpoint.
            limit: If > 0, process only this many articles then stop.
        """
        articles = self.db.get_articles_chronological()
        total = len(articles)
        logger.info(f"Building textbook from {total} articles (chronological order)")

        # Load checkpoint
        start_idx = 0
        chapter_updates: dict[str, list[str]] = {ch: [] for ch in CHAPTERS}

        if resume and self.checkpoint_file.exists():
            checkpoint = json.loads(self.checkpoint_file.read_text())
            start_idx = checkpoint.get("last_processed_idx", 0) + 1
            chapter_updates = checkpoint.get("chapter_updates", chapter_updates)
            logger.info(f"Resuming from article index {start_idx}")

        already_processed = self.db.get_processed_pmids()
        processed_this_run = 0

        end_idx = total
        desc = "Processing articles"
        if limit > 0:
            desc = f"Processing articles (batch of {limit})"

        for idx in tqdm(range(start_idx, end_idx), desc=desc, initial=start_idx, total=end_idx):
            article = articles[idx]
            pmid = article.pmid

            # Skip if already extracted
            if pmid in already_processed:
                continue

            # Check if we've hit the limit for this run
            if limit > 0 and processed_this_run >= limit:
                logger.info(f"Reached batch limit of {limit} articles. Saving checkpoint.")
                self._save_checkpoint(idx - 1, chapter_updates)
                self._export_textbook()
                return

            # Build current knowledge summary (truncated)
            current_knowledge = self._build_knowledge_summary(chapter_updates)

            # Read fulltext if available
            fulltext = ""
            if article.fulltext_available and article.fulltext_path:
                try:
                    ft_path = Path(article.fulltext_path)
                    if ft_path.exists():
                        fulltext = ft_path.read_text(errors="replace")[:100000]
                except Exception:
                    pass

            # Build article dict from ORM object
            article_dict = {
                "pmid": article.pmid,
                "title": article.title,
                "abstract": article.abstract,
                "authors": article.authors or [],
                "journal": article.journal,
                "publication_year": article.publication_year,
            }

            # Extract knowledge
            extraction = self.extractor.extract_from_article(
                article_dict, idx + 1, total, current_knowledge, fulltext
            )

            if extraction:
                # Store extracted knowledge
                self._store_extraction(pmid, extraction)

                # Accumulate textbook updates
                textbook_updates = extraction.get("textbook_updates", {})
                for chapter, update_content in textbook_updates.items():
                    if update_content:
                        matched_chapter = self._match_chapter(chapter)
                        if matched_chapter:
                            chapter_updates.setdefault(matched_chapter, [])
                            chapter_updates[matched_chapter].append(
                                f"[From PMID:{pmid}, {article.publication_year}]: {update_content}"
                            )

            processed_this_run += 1

            # Checkpoint
            if (idx + 1) % config.CHECKPOINT_INTERVAL == 0:
                self._save_checkpoint(idx, chapter_updates)

            # Delay to respect rate limits (longer for cloud APIs)
            if self._use_ollama:
                time.sleep(0.5)
            else:
                time.sleep(2)

        # Final checkpoint
        self._save_checkpoint(total - 1 if not limit else idx, chapter_updates)

        # Synthesize chapters using Gemini Pro
        logger.info("Synthesizing final textbook chapters with Gemini Pro...")
        self._synthesize_chapters(chapter_updates)

        # Export to markdown files
        self._export_textbook()

        logger.info("Textbook building complete!")

    def _build_knowledge_summary(self, chapter_updates: dict[str, list[str]], max_length: int = 30000) -> str:
        """Build a summary of current knowledge from chapter updates."""
        sections = []
        for chapter, updates in chapter_updates.items():
            if updates:
                # Take only the last N updates to fit in context
                recent = updates[-20:]
                sections.append(f"### {chapter}\n" + "\n".join(f"- {u[:500]}" for u in recent))

        summary = "\n\n".join(sections)
        if len(summary) > max_length:
            summary = summary[:max_length] + "\n\n[...truncated...]"
        return summary or "No knowledge accumulated yet. This may be one of the earliest SBMA publications."

    def _match_chapter(self, chapter_key: str) -> Optional[str]:
        """Match a chapter key from Claude's response to our canonical chapter names."""
        key_lower = chapter_key.lower()
        for chapter in CHAPTERS:
            chapter_lower = chapter.lower()
            # Check various matching strategies
            if key_lower in chapter_lower or chapter_lower in key_lower:
                return chapter
            # Keyword matching
            keywords = {
                "histor": "Chapter 1",
                "overview": "Chapter 1",
                "genet": "Chapter 2",
                "molecular": "Chapter 2",
                "pathophys": "Chapter 3",
                "mechanism": "Chapter 3",
                "clinical": "Chapter 4",
                "natural history": "Chapter 4",
                "symptom": "Chapter 4",
                "diagnos": "Chapter 5",
                "epidemiol": "Chapter 6",
                "animal": "Chapter 7",
                "model": "Chapter 7",
                "cellular model": "Chapter 7",
                "therap": "Chapter 8",
                "treatment": "Chapter 8",
                "trial": "Chapter 8",
                "biomarker": "Chapter 9",
                "outcome": "Chapter 9",
                "patient": "Chapter 10",
                "quality of life": "Chapter 10",
                "open question": "Chapter 11",
                "future": "Chapter 11",
                "contradiction": "Chapter 12",
                "debate": "Chapter 12",
            }
            for kw, ch_prefix in keywords.items():
                if kw in key_lower and chapter.startswith(ch_prefix):
                    return chapter

        # Default to Chapter 1 if no match
        logger.debug(f"No chapter match for '{chapter_key}', defaulting to Chapter 1")
        return CHAPTERS[0]

    def _store_extraction(self, pmid: str, extraction: dict):
        """Store extraction results in the database."""
        # Store new findings
        for finding in extraction.get("new_findings", []):
            self.db.add_extracted_knowledge({
                "pmid": pmid,
                "knowledge_type": "finding",
                "summary": finding[:500] if isinstance(finding, str) else str(finding)[:500],
                "details": json.dumps(finding) if not isinstance(finding, str) else finding,
                "confidence": self._evidence_to_confidence(extraction.get("evidence_strength", "moderate")),
                "novelty_at_publication": "new",
                "contradicts": extraction.get("contradictions", [])[:5] if isinstance(extraction.get("contradictions"), list) else [],
                "supports": [],
            })

        # Store confirmations
        for conf in extraction.get("confirmations", []):
            self.db.add_extracted_knowledge({
                "pmid": pmid,
                "knowledge_type": "finding",
                "summary": conf[:500] if isinstance(conf, str) else str(conf)[:500],
                "details": json.dumps(conf) if not isinstance(conf, str) else conf,
                "confidence": self._evidence_to_confidence(extraction.get("evidence_strength", "moderate")),
                "novelty_at_publication": "confirmatory",
                "contradicts": [],
                "supports": [],
            })

    def _evidence_to_confidence(self, evidence_strength: str) -> float:
        mapping = {"strong": 0.9, "moderate": 0.7, "weak": 0.4, "preliminary": 0.3}
        return mapping.get(evidence_strength.lower(), 0.5)

    def _synthesize_chapters(self, chapter_updates: dict[str, list[str]]):
        """Use Claude Opus to synthesize accumulated updates into polished chapters."""
        for chapter in CHAPTERS:
            updates = chapter_updates.get(chapter, [])
            if not updates:
                continue

            logger.info(f"Synthesizing {chapter} ({len(updates)} updates)")

            # Truncate updates to fit context
            updates_text = "\n\n".join(updates)
            if len(updates_text) > 80000:
                updates_text = updates_text[:80000] + "\n\n[...additional updates truncated...]"

            prompt = SYNTHESIS_PROMPT.format(chapter=chapter, updates=updates_text)

            try:
                if self._use_ollama:
                    content = self.client.generate(
                        prompt=prompt,
                        max_tokens=8192,
                        temperature=0.4,
                        json_mode=False,
                    )
                else:
                    response = self.client.models.generate_content(
                        model=config.GEMINI_SYNTHESIS_MODEL,
                        contents=prompt,
                        config={"max_output_tokens": 8192},
                    )
                    content = response.text

                # Get contributing PMIDs from updates
                pmids = []
                for u in updates:
                    if "PMID:" in u:
                        start = u.index("PMID:") + 5
                        end = u.index("]", start) if "]" in u[start:] else start + 20
                        pmid = u[start:end].strip().rstrip(",")
                        pmids.append(pmid)

                # Store in database
                self.db.upsert_textbook_section(
                    chapter=chapter,
                    section_title=chapter,
                    content=content,
                    contributing_pmids=list(set(pmids)),
                )

            except Exception as e:
                logger.error(f"Failed to synthesize {chapter}: {e}")

            time.sleep(1)  # Rate limit pause

    def _export_textbook(self):
        """Export the textbook as markdown files."""
        sections = self.db.get_textbook_sections()
        if not sections:
            logger.warning("No textbook sections to export")
            return

        # Full textbook as single file
        full_textbook_path = config.TEXTBOOK_DIR / "SBMA_Textbook.md"
        lines = [
            "# The SBMA Textbook: A Comprehensive Review Built from Primary Literature\n",
            f"*Generated: {datetime.now().strftime('%Y-%m-%d')}*\n",
            f"*Built from {self.db.get_article_count()} primary research articles*\n\n",
            "---\n\n",
        ]

        for section in sections:
            lines.append(f"## {section.chapter}\n\n")
            lines.append(section.content or "*No content yet.*")
            lines.append("\n\n---\n\n")

        full_textbook_path.write_text("\n".join(lines))
        logger.info(f"Textbook exported to {full_textbook_path}")

        # Individual chapter files
        for section in sections:
            safe_name = section.chapter.replace(":", "").replace(" ", "_").replace("/", "_")
            ch_path = config.TEXTBOOK_DIR / f"{safe_name}.md"
            ch_path.write_text(f"# {section.chapter}\n\n{section.content or ''}\n")

        logger.info(f"Individual chapter files exported to {config.TEXTBOOK_DIR}")

    def _save_checkpoint(self, idx: int, chapter_updates: dict[str, list[str]]):
        """Save progress checkpoint."""
        # Serialize chapter_updates (truncate long lists to save space)
        serializable = {}
        for ch, updates in chapter_updates.items():
            serializable[ch] = updates[-200:]  # Keep last 200 per chapter

        self.checkpoint_file.write_text(json.dumps({
            "last_processed_idx": idx,
            "chapter_updates": serializable,
            "timestamp": datetime.now().isoformat(),
        }))
        logger.debug(f"Checkpoint saved at index {idx}")
