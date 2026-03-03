#!/usr/bin/env python3
"""Export SQLite data to Supabase for the public website."""

import sys
import json
import os
from pathlib import Path
from datetime import datetime

from supabase import create_client, Client
from tqdm import tqdm

sys.path.insert(0, str(Path(__file__).parent))
import config
from database.db_manager import DBManager

# --- Supabase config ---
SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY", "")

BATCH_SIZE = 200  # rows per upsert batch


def get_supabase() -> Client:
    if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
        print("ERROR: Set SUPABASE_URL and SUPABASE_SERVICE_KEY in .env")
        sys.exit(1)
    return create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)


def export_articles(sb: Client, db: DBManager):
    """Export all articles to Supabase."""
    print("\n--- Exporting articles ---")
    session = db.get_session()
    try:
        from database.models import Article
        articles = session.query(Article).all()
        print(f"  {len(articles)} articles to export")

        rows = []
        for a in articles:
            rows.append({
                "pmid": a.pmid,
                "doi": a.doi,
                "title": a.title,
                "abstract": a.abstract,
                "authors": a.authors or [],
                "journal": a.journal,
                "publication_year": a.publication_year,
                "article_type": a.article_type,
                "citation_count": a.citation_count or 0,
                "keywords": a.keywords or [],
                "mesh_terms": a.mesh_terms or [],
                "fulltext_available": a.fulltext_available or False,
            })

        for i in tqdm(range(0, len(rows), BATCH_SIZE), desc="  articles"):
            batch = rows[i:i + BATCH_SIZE]
            sb.table("articles").upsert(batch, on_conflict="pmid").execute()

        print(f"  Done: {len(rows)} articles exported")
    finally:
        session.close()


def export_knowledge(sb: Client, db: DBManager):
    """Export extracted knowledge to Supabase."""
    print("\n--- Exporting extracted knowledge ---")
    session = db.get_session()
    try:
        from database.models import ExtractedKnowledge
        knowledge = session.query(ExtractedKnowledge).all()
        print(f"  {len(knowledge)} knowledge entries to export")

        if not knowledge:
            return

        # Clear existing and re-insert (simpler than upserting with auto-increment IDs)
        sb.table("extracted_knowledge").delete().neq("id", 0).execute()

        rows = []
        for k in knowledge:
            rows.append({
                "pmid": k.pmid,
                "knowledge_type": k.knowledge_type,
                "summary": k.summary,
                "details": k.details,
                "confidence": k.confidence,
                "novelty_at_publication": k.novelty_at_publication,
            })

        for i in tqdm(range(0, len(rows), BATCH_SIZE), desc="  knowledge"):
            batch = rows[i:i + BATCH_SIZE]
            sb.table("extracted_knowledge").insert(batch).execute()

        print(f"  Done: {len(rows)} knowledge entries exported")
    finally:
        session.close()


def export_textbook(sb: Client, db: DBManager):
    """Export textbook sections to Supabase."""
    print("\n--- Exporting textbook sections ---")
    sections = db.get_textbook_sections()
    print(f"  {len(sections)} sections to export")

    if not sections:
        print("  No textbook sections yet — skipping")
        return

    sb.table("textbook_sections").delete().neq("id", 0).execute()

    rows = []
    for s in sections:
        rows.append({
            "chapter": s.chapter,
            "section_title": s.section_title,
            "content": s.content,
            "contributing_pmids": s.contributing_pmids or [],
            "version": s.version or 1,
            "last_updated": s.last_updated.isoformat() if s.last_updated else datetime.utcnow().isoformat(),
        })

    sb.table("textbook_sections").insert(rows).execute()
    print(f"  Done: {len(rows)} textbook sections exported")


def export_weekly_reports(sb: Client, db: DBManager):
    """Export weekly reports to Supabase."""
    print("\n--- Exporting weekly reports ---")
    reports = db.get_all_weekly_reports()
    print(f"  {len(reports)} reports to export")

    if not reports:
        print("  No weekly reports yet — skipping")
        return

    sb.table("weekly_reports").delete().neq("id", 0).execute()

    rows = []
    for r in reports:
        rows.append({
            "report_date": str(r.report_date) if r.report_date else None,
            "new_articles_found": r.new_articles_found,
            "summary": r.summary,
            "novelty_analysis": r.novelty_analysis,
        })

    sb.table("weekly_reports").insert(rows).execute()
    print(f"  Done: {len(rows)} reports exported")


def export_author_analytics(sb: Client, db: DBManager):
    """Export author analytics to Supabase."""
    print("\n--- Exporting author analytics ---")
    authors = db.get_all_author_analytics()
    print(f"  {len(authors)} author analytics to export")

    if not authors:
        # Compute from articles directly
        top = db.get_top_authors(100)
        if top:
            rows = [{"author_name": name, "total_papers": count} for name, count in top]
            for i in range(0, len(rows), BATCH_SIZE):
                batch = rows[i:i + BATCH_SIZE]
                sb.table("authors_analytics").upsert(batch, on_conflict="author_name").execute()
            print(f"  Done: {len(rows)} author stats computed and exported")
        return

    rows = []
    for a in authors:
        rows.append({
            "author_name": a.author_name,
            "total_papers": a.total_papers,
            "first_author_papers": a.first_author_papers,
            "last_author_papers": a.last_author_papers,
            "h_index_in_field": a.h_index_in_field,
            "affiliations": a.affiliations or [],
            "active_years": a.active_years,
        })

    for i in range(0, len(rows), BATCH_SIZE):
        batch = rows[i:i + BATCH_SIZE]
        sb.table("authors_analytics").upsert(batch, on_conflict="author_name").execute()

    print(f"  Done: {len(rows)} author analytics exported")


def export_stats_overview(sb: Client, db: DBManager):
    """Compute and export pre-aggregated stats."""
    print("\n--- Computing stats overview ---")

    articles_by_year = db.get_articles_by_year()
    article_types = db.get_article_type_distribution()
    top_journals = db.get_top_journals(25)
    top_authors = db.get_top_authors(30)
    processed_pmids = db.get_processed_pmids()

    # Topic evolution
    topic_data = db.get_topic_evolution_data()

    stats = {
        "id": 1,
        "total_articles": db.get_article_count(),
        "total_knowledge": db.get_knowledge_count(),
        "total_fulltext": db.get_fulltext_count(),
        "articles_by_year": {str(k): v for k, v in articles_by_year.items()},
        "article_type_distribution": article_types,
        "top_journals": [{"name": j, "count": c} for j, c in top_journals],
        "top_authors": [{"name": a, "count": c} for a, c in top_authors],
        "topic_evolution": topic_data,
        "processing_progress": {
            "processed": len(processed_pmids),
            "total": db.get_article_count(),
        },
        "last_updated": datetime.utcnow().isoformat(),
    }

    sb.table("stats_overview").upsert(stats, on_conflict="id").execute()
    print(f"  Done: stats exported (articles={stats['total_articles']}, "
          f"knowledge={stats['total_knowledge']}, "
          f"processed={stats['processing_progress']['processed']}/{stats['processing_progress']['total']})")


def export_gap_analysis(sb: Client):
    """Export gap analysis if available."""
    print("\n--- Exporting gap analysis ---")

    gap_json_path = config.ANALYTICS_DIR / "gap_analysis.json"
    gap_md_path = config.ANALYTICS_DIR / "gap_analysis.md"

    content = None
    raw_json = None

    if gap_json_path.exists():
        raw_json = json.loads(gap_json_path.read_text())
    if gap_md_path.exists():
        content = gap_md_path.read_text()

    if not content and not raw_json:
        print("  No gap analysis found — skipping")
        return

    sb.table("gap_analysis").delete().neq("id", 0).execute()
    sb.table("gap_analysis").insert({
        "content": content,
        "raw_json": raw_json,
    }).execute()
    print("  Done: gap analysis exported")


def main():
    print("=" * 60)
    print("SBMA Research — Export to Supabase")
    print("=" * 60)

    sb = get_supabase()
    db = DBManager()

    export_articles(sb, db)
    export_knowledge(sb, db)
    export_textbook(sb, db)
    export_weekly_reports(sb, db)
    export_author_analytics(sb, db)
    export_stats_overview(sb, db)
    export_gap_analysis(sb)

    print("\n" + "=" * 60)
    print("Export complete! Your website should now show updated data.")
    print("=" * 60)


if __name__ == "__main__":
    main()
