#!/usr/bin/env python3
"""Extract knowledge from articles that haven't been processed yet.

Runs extraction only (no textbook synthesis) on unprocessed articles.
After this, run resynthesize_textbook.py to regenerate chapters.
"""

import sys
import json
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config
from logger import setup_logger
from database.db_manager import DBManager
from database.models import Article, ExtractedKnowledge
from analysis.knowledge_extractor import KnowledgeExtractor, RATE_LIMIT_SLEEP
from analysis.ollama_client import call_llm

from tqdm import tqdm

logger = setup_logger("extract_remaining")


def main():
    db = DBManager()
    extractor = KnowledgeExtractor()
    session = db.get_session()

    # Find unprocessed articles
    all_pmids = set(r[0] for r in session.query(Article.pmid).all())
    processed_pmids = set(r[0] for r in session.query(ExtractedKnowledge.pmid).distinct().all())
    unprocessed_pmids = all_pmids - processed_pmids

    if not unprocessed_pmids:
        print("All articles already processed!")
        return

    # Get articles in chronological order
    articles = (
        session.query(Article)
        .filter(Article.pmid.in_(unprocessed_pmids))
        .order_by(Article.publication_year)
        .all()
    )
    session.close()

    total_in_db = len(all_pmids)
    print(f"Found {len(articles)} unprocessed articles out of {total_in_db}")

    # Build current knowledge summary from existing extractions
    current_knowledge = _build_knowledge_summary(db)

    # Also load checkpoint updates for context
    checkpoint_file = config.CHECKPOINTS_DIR / "textbook_builder_checkpoint.json"
    chapter_updates = {}
    if checkpoint_file.exists():
        checkpoint = json.loads(checkpoint_file.read_text())
        chapter_updates = checkpoint.get("chapter_updates", {})

    backend = config.LLM_BACKEND
    processed = 0

    for article in tqdm(articles, desc="Extracting remaining articles"):
        # Read fulltext if available
        fulltext = ""
        if article.fulltext_available and article.fulltext_path:
            try:
                ft_path = Path(article.fulltext_path)
                if ft_path.exists():
                    fulltext = ft_path.read_text(errors="replace")[:100000]
            except Exception:
                pass

        article_dict = {
            "pmid": article.pmid,
            "title": article.title,
            "abstract": article.abstract,
            "authors": article.authors or [],
            "journal": article.journal,
            "publication_year": article.publication_year,
        }

        extraction = extractor.extract_from_article(
            article_dict,
            processed + 1,
            len(articles),
            current_knowledge,
            fulltext,
        )

        if extraction:
            _store_extraction(db, article.pmid, extraction)

            # Accumulate chapter updates for checkpoint
            for chapter, update_content in extraction.get("textbook_updates", {}).items():
                if update_content:
                    matched = _match_chapter(chapter)
                    if matched:
                        chapter_updates.setdefault(matched, [])
                        chapter_updates[matched].append(
                            f"[From PMID:{article.pmid}, {article.publication_year}]: {update_content}"
                        )

            processed += 1
            print(f"  Extracted {article.pmid} ({article.publication_year}): "
                  f"{len(extraction.get('new_findings', []))} findings")

        time.sleep(RATE_LIMIT_SLEEP.get(backend, 1.0))

    # Save updated checkpoint
    if chapter_updates:
        serializable = {ch: updates[-200:] for ch, updates in chapter_updates.items()}
        checkpoint_file.write_text(json.dumps({
            "last_processed_idx": 9999,
            "chapter_updates": serializable,
            "timestamp": __import__("datetime").datetime.now().isoformat(),
        }))
        print(f"Checkpoint updated with new extractions")

    print(f"\nDone! Processed {processed}/{len(articles)} articles")
    print(f"Run resynthesize_textbook.py to regenerate chapters with new data")


def _build_knowledge_summary(db: DBManager, max_length: int = 30000) -> str:
    """Build knowledge summary from existing DB entries."""
    session = db.get_session()
    from sqlalchemy import func

    # Get recent knowledge by type
    sections = []
    for ktype in ["mechanism", "genetic", "clinical_feature", "treatment", "biomarker"]:
        entries = (
            session.query(ExtractedKnowledge)
            .filter(ExtractedKnowledge.knowledge_type == ktype)
            .order_by(ExtractedKnowledge.id.desc())
            .limit(20)
            .all()
        )
        if entries:
            summaries = [f"- {e.summary[:300]}" for e in entries]
            sections.append(f"### {ktype.title()}\n" + "\n".join(summaries))

    session.close()
    summary = "\n\n".join(sections)
    return summary[:max_length] if summary else "Building initial knowledge base."


def _store_extraction(db: DBManager, pmid: str, extraction: dict):
    """Store extraction results."""
    evidence = extraction.get("evidence_strength", "moderate")
    confidence_map = {"strong": 0.9, "moderate": 0.7, "weak": 0.4, "preliminary": 0.3}
    confidence = confidence_map.get(evidence.lower(), 0.5)

    for finding in extraction.get("new_findings", []):
        if isinstance(finding, dict):
            db.add_extracted_knowledge({
                "pmid": pmid,
                "knowledge_type": finding.get("knowledge_type", "finding"),
                "summary": finding.get("summary", "")[:500],
                "details": json.dumps(finding),
                "confidence": confidence,
                "novelty_at_publication": "new",
                "contradicts": [],
                "supports": [],
            })
        else:
            db.add_extracted_knowledge({
                "pmid": pmid,
                "knowledge_type": "finding",
                "summary": str(finding)[:500],
                "details": str(finding),
                "confidence": confidence,
                "novelty_at_publication": "new",
                "contradicts": [],
                "supports": [],
            })

    for conf in extraction.get("confirmations", []):
        if isinstance(conf, dict):
            db.add_extracted_knowledge({
                "pmid": pmid,
                "knowledge_type": conf.get("knowledge_type", "finding"),
                "summary": conf.get("summary", "")[:500],
                "details": json.dumps(conf),
                "confidence": confidence,
                "novelty_at_publication": "confirmatory",
                "contradicts": [],
                "supports": [],
            })


def _match_chapter(chapter_key: str):
    """Match chapter key to canonical name."""
    from analysis.textbook_builder import CHAPTERS
    key_lower = chapter_key.lower()
    for chapter in CHAPTERS:
        if key_lower in chapter.lower() or chapter.lower() in key_lower:
            return chapter
    keywords = {
        "histor": "Chapter 1", "genet": "Chapter 2", "molecular": "Chapter 2",
        "pathophys": "Chapter 3", "mechanism": "Chapter 3", "clinical": "Chapter 4",
        "diagnos": "Chapter 5", "epidemiol": "Chapter 6", "animal": "Chapter 7",
        "model": "Chapter 7", "therap": "Chapter 8", "treatment": "Chapter 8",
        "biomarker": "Chapter 9", "patient": "Chapter 10", "quality": "Chapter 10",
        "open question": "Chapter 11", "future": "Chapter 11",
        "contradiction": "Chapter 12", "debate": "Chapter 12",
    }
    for kw, ch_prefix in keywords.items():
        if kw in key_lower:
            for ch in CHAPTERS:
                if ch.startswith(ch_prefix):
                    return ch
    return None


if __name__ == "__main__":
    main()
