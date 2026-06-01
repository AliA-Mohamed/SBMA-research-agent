#!/usr/bin/env python3
"""Re-synthesize textbook chapters from clean checkpoint data using Claude.

This script:
1. Loads the existing checkpoint (chapter_updates accumulated during extraction)
2. Filters out updates from PMIDs no longer in the database (removed false positives)
3. Filters out any updates containing material science contamination terms
4. Re-synthesizes all 12 chapters using Claude (higher quality than Gemini Flash Lite)
5. Stores results in the database and exports as markdown files
"""

import sys
import json
import re
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config
from logger import setup_logger
from database.db_manager import DBManager
from analysis.textbook_builder import CHAPTERS, CHAPTER_SECTIONS

logger = setup_logger("resynthesize_textbook")

# Terms that indicate material science contamination (NOT the disease SBMA)
CONTAMINATION_TERMS = [
    "sulfobetaine", "methacrylate", "zwitterionic", "antifouling",
    "antimicrobial peptide uptake", "polyzwitterion", "dental varnish",
    "wound dressing", "contact lens", "biofilm resistance",
    "antibacterial coating", "hemodialysis membrane",
    "vascular stent", "hydrogel coating",
    "sbma transporter",  # bacterial SbmA protein
]

SYNTHESIS_PROMPT = """You are a world-class SBMA (Spinal and Bulbar Muscular Atrophy / Kennedy's Disease) researcher writing a comprehensive medical textbook chapter.

CHAPTER: "{chapter}"

You have been given accumulated knowledge updates extracted from {n_updates} primary research articles about SBMA. Synthesize them into a polished, authoritative textbook chapter.

CRITICAL INSTRUCTIONS:
1. Write in clear academic prose suitable for a medical textbook aimed at neurologists, geneticists, and biomedical researchers
2. Organize content with clear subsections using markdown headers (###, ####)
3. Maintain chronological awareness — note when key discoveries were made
4. Cite ALL claims using [PMID:xxxxx] format
5. Distinguish between well-established facts and preliminary findings
6. Flag contradictions or ongoing debates explicitly
7. NEVER include content about:
   - Sulfobetaine methacrylate (a polymer also abbreviated "SBMA")
   - Zwitterionic polymers, antifouling coatings, or material science
   - The bacterial SbmA transporter
   - Any content unrelated to the neurodegenerative disease SBMA
8. If updates mention non-SBMA content, silently ignore those updates
9. Be thorough — aim for 3000-5000 words for major chapters

{sections_instruction}

KNOWLEDGE UPDATES:
{updates}

Write the synthesized chapter content in Markdown format. Start with the chapter content directly (no "# Chapter N" header — that will be added automatically)."""


def clean_updates(chapter_updates: dict, valid_pmids: set) -> dict:
    """Remove updates from deleted articles and contamination."""
    cleaned = {}
    total_removed = 0

    for chapter, updates in chapter_updates.items():
        clean = []
        for update in updates:
            # Extract PMID from update
            pmid_match = re.search(r'PMID:(\d+)', update)
            if pmid_match:
                pmid = pmid_match.group(1)
                if pmid not in valid_pmids:
                    total_removed += 1
                    continue

            # Check for contamination
            update_lower = update.lower()
            if any(term in update_lower for term in CONTAMINATION_TERMS):
                total_removed += 1
                continue

            clean.append(update)
        cleaned[chapter] = clean

    logger.info(f"Removed {total_removed} contaminated/orphaned updates")
    return cleaned


def synthesize_chapter(chapter: str, updates: list[str]) -> str:
    """Synthesize a single chapter using Claude."""
    import anthropic

    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)

    # Build sections instruction
    sections_instruction = ""
    if chapter in CHAPTER_SECTIONS:
        sections = CHAPTER_SECTIONS[chapter]
        sections_instruction = (
            f"This chapter should include these sections: {', '.join(sections)}. "
            "You may add additional subsections as appropriate."
        )

    updates_text = "\n\n".join(updates)
    # Truncate to fit context (Claude can handle much more than Gemini)
    if len(updates_text) > 150000:
        updates_text = updates_text[:150000] + "\n\n[...additional updates truncated...]"

    prompt = SYNTHESIS_PROMPT.format(
        chapter=chapter,
        n_updates=len(updates),
        sections_instruction=sections_instruction,
        updates=updates_text,
    )

    message = client.messages.create(
        model=config.CLAUDE_SYNTHESIS_MODEL,
        max_tokens=8192,
        temperature=0.4,
        system=(
            "You are an expert SBMA researcher and medical textbook author. "
            "Write authoritative, well-cited content about Spinal and Bulbar Muscular Atrophy "
            "(Kennedy's Disease). NEVER include material science content."
        ),
        messages=[{"role": "user", "content": prompt}],
    )
    return message.content[0].text


def main():
    db = DBManager()
    checkpoint_file = config.CHECKPOINTS_DIR / "textbook_builder_checkpoint.json"

    if not checkpoint_file.exists():
        print("ERROR: No checkpoint file found. Run textbook builder first.")
        sys.exit(1)

    # Load checkpoint
    checkpoint = json.loads(checkpoint_file.read_text())
    chapter_updates = checkpoint.get("chapter_updates", {})
    print(f"Loaded checkpoint from {checkpoint.get('timestamp', 'unknown')}")

    # Get valid PMIDs (still in database)
    session = db.get_session()
    from database.models import Article
    valid_pmids = set(
        row[0] for row in session.query(Article.pmid).all()
    )
    session.close()
    print(f"Valid PMIDs in database: {len(valid_pmids)}")

    # Clean updates
    cleaned_updates = clean_updates(chapter_updates, valid_pmids)

    for ch in CHAPTERS:
        orig = len(chapter_updates.get(ch, []))
        clean = len(cleaned_updates.get(ch, []))
        removed = orig - clean
        status = f" (-{removed} removed)" if removed else ""
        print(f"  {ch}: {clean} updates{status}")

    # Synthesize each chapter with Claude
    print(f"\nSynthesizing {len(CHAPTERS)} chapters with {config.CLAUDE_SYNTHESIS_MODEL}...")

    for chapter in CHAPTERS:
        updates = cleaned_updates.get(chapter, [])
        if not updates:
            print(f"  SKIP {chapter} (no updates)")
            continue

        print(f"  Synthesizing {chapter} ({len(updates)} updates)...", end=" ", flush=True)

        try:
            content = synthesize_chapter(chapter, updates)

            # Extract contributing PMIDs
            pmids = list(set(re.findall(r'PMID:(\d+)', "\n".join(updates))))

            # Store in database
            db.upsert_textbook_section(
                chapter=chapter,
                section_title=chapter,
                content=content,
                contributing_pmids=pmids,
            )
            print(f"OK ({len(content)} chars, {len(pmids)} sources)")

        except Exception as e:
            print(f"FAILED: {e}")
            logger.error(f"Failed to synthesize {chapter}: {e}")

        time.sleep(1)  # Rate limit

    # Export textbook as markdown
    print("\nExporting textbook...")
    export_textbook(db)
    print("Done!")


def export_textbook(db: DBManager):
    """Export the textbook as markdown files."""
    sections = db.get_textbook_sections()
    if not sections:
        print("No textbook sections to export")
        return

    # Full textbook
    full_path = config.TEXTBOOK_DIR / "SBMA_Textbook.md"
    lines = [
        "# The SBMA Textbook: A Comprehensive Review Built from Primary Literature\n",
        f"*Generated: {datetime.now().strftime('%Y-%m-%d')}*\n",
        f"*Built from {db.get_article_count()} primary research articles*\n\n",
        "---\n\n",
    ]

    for section in sections:
        lines.append(f"## {section.chapter}\n\n")
        lines.append(section.content or "*No content yet.*")
        lines.append("\n\n---\n\n")

    full_path.write_text("\n".join(lines))
    print(f"  Full textbook: {full_path} ({len(''.join(lines))} chars)")

    # Individual chapters
    for section in sections:
        safe_name = section.chapter.replace(":", "").replace(" ", "_").replace("/", "_")
        ch_path = config.TEXTBOOK_DIR / f"{safe_name}.md"
        ch_path.write_text(f"# {section.chapter}\n\n{section.content or ''}\n")

    print(f"  Individual chapters exported to {config.TEXTBOOK_DIR}")


if __name__ == "__main__":
    main()
