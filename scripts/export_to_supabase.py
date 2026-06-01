#!/usr/bin/env python3
"""Export SQLite data to Supabase for the public website."""

import sys
import json
import os
import time
from pathlib import Path
from datetime import datetime

from supabase import create_client, Client
from tqdm import tqdm

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config
from database.db_manager import DBManager

# --- Supabase config ---
SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY", "")

BATCH_SIZE = 50  # smaller batches to avoid HTTP/2 connection drops


def upsert_with_retry(table, rows, on_conflict, max_retries=5):
    """Upsert a batch with exponential backoff on transient connection errors."""
    for attempt in range(max_retries):
        try:
            table.upsert(rows, on_conflict=on_conflict).execute()
            return
        except Exception as e:
            err = str(e)
            if attempt < max_retries - 1 and any(x in err for x in [
                "RemoteProtocolError", "ConnectionTerminated", "RemoteDisconnected",
                "ConnectionReset", "BrokenPipe", "timeout", "Timeout"
            ]):
                wait = 2 ** attempt
                print(f"\n  Connection error (attempt {attempt+1}/{max_retries}), retrying in {wait}s...")
                time.sleep(wait)
            else:
                raise


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
        current_pmids = set()
        for a in articles:
            current_pmids.add(a.pmid)
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
            upsert_with_retry(sb.table("articles"), batch, "pmid")

        # Delete stale articles not in current DB
        all_sb_pmids = set()
        offset = 0
        while True:
            resp = sb.table("articles").select("pmid").range(offset, offset + 999).execute()
            if not resp.data:
                break
            for row in resp.data:
                all_sb_pmids.add(row["pmid"])
            if len(resp.data) < 1000:
                break
            offset += 1000

        stale_pmids = all_sb_pmids - current_pmids
        if stale_pmids:
            print(f"  Removing {len(stale_pmids)} stale articles from Supabase...")
            stale_list = list(stale_pmids)
            for i in range(0, len(stale_list), BATCH_SIZE):
                batch = stale_list[i:i + BATCH_SIZE]
                sb.table("extracted_knowledge").delete().in_("pmid", batch).execute()
                sb.table("articles").delete().in_("pmid", batch).execute()

        print(f"  Done: {len(rows)} articles exported")
    finally:
        session.close()


def export_knowledge(sb: Client, db: DBManager):
    """Export extracted knowledge to Supabase via upsert."""
    print("\n--- Exporting extracted knowledge ---")
    session = db.get_session()
    try:
        from database.models import ExtractedKnowledge
        knowledge = session.query(ExtractedKnowledge).all()
        print(f"  {len(knowledge)} knowledge entries to export")

        if not knowledge:
            return

        rows = []
        seen_keys = set()
        for k in knowledge:
            key = (k.pmid, k.knowledge_type, k.summary)
            if key in seen_keys:
                continue
            seen_keys.add(key)
            
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
            upsert_with_retry(sb.table("extracted_knowledge"), batch, "pmid,knowledge_type,summary")

        print(f"  Done: {len(rows)} knowledge entries exported")
    finally:
        session.close()


def export_textbook(sb: Client, db: DBManager):
    """Export textbook sections to Supabase, archiving previous versions."""
    print("\n--- Exporting textbook sections ---")
    sections = db.get_textbook_sections()
    print(f"  {len(sections)} sections to export")

    if not sections:
        print("  No textbook sections yet — skipping")
        return

    # Archive current versions before overwriting
    existing = sb.table("textbook_sections").select("*").execute()
    if existing.data:
        archives = []
        for s in existing.data:
            archives.append({
                "chapter": s["chapter"],
                "section_title": s["section_title"],
                "content": s["content"],
                "contributing_pmids": s.get("contributing_pmids", []),
                "version": s.get("version", 1),
                "synthesized_at": s.get("last_updated", datetime.utcnow().isoformat()),
            })
        for i in range(0, len(archives), BATCH_SIZE):
            batch = archives[i:i + BATCH_SIZE]
            sb.table("textbook_versions").insert(batch).execute()
        print(f"  Archived {len(archives)} previous versions")

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

    for i in tqdm(range(0, len(rows), BATCH_SIZE), desc="  textbook"):
        batch = rows[i:i + BATCH_SIZE]
        upsert_with_retry(sb.table("textbook_sections"), batch, "chapter,section_title")

    print(f"  Done: {len(rows)} textbook sections exported")


def export_weekly_reports(sb: Client, db: DBManager):
    """Export weekly reports to Supabase via upsert."""
    print("\n--- Exporting weekly reports ---")
    reports = db.get_all_weekly_reports()
    print(f"  {len(reports)} reports to export")

    if not reports:
        print("  No weekly reports yet — skipping")
        return

    rows = []
    for r in reports:
        rows.append({
            "report_date": str(r.report_date) if r.report_date else None,
            "new_articles_found": r.new_articles_found,
            "summary": r.summary,
            "novelty_analysis": r.novelty_analysis,
        })

    for i in tqdm(range(0, len(rows), BATCH_SIZE), desc="  reports"):
        batch = rows[i:i + BATCH_SIZE]
        upsert_with_retry(sb.table("weekly_reports"), batch, "report_date")

    print(f"  Done: {len(rows)} reports exported")


def export_author_analytics(sb: Client, db: DBManager):
    """Export author analytics to Supabase via upsert."""
    print("\n--- Exporting author analytics ---")
    authors = db.get_all_author_analytics()
    print(f"  {len(authors)} author analytics to export")

    if not authors:
        top = db.get_top_authors(100)
        if top:
            rows = [{"author_name": name, "total_papers": count} for name, count in top]
            for i in range(0, len(rows), BATCH_SIZE):
                batch = rows[i:i + BATCH_SIZE]
                upsert_with_retry(sb.table("authors_analytics"), batch, "author_name")
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
        upsert_with_retry(sb.table("authors_analytics"), batch, "author_name")

    # Remove authors no longer in the local DB
    current_names = {a.author_name for a in authors}
    all_sb_names = set()
    offset = 0
    while True:
        resp = sb.table("authors_analytics").select("author_name").range(offset, offset + 999).execute()
        if not resp.data:
            break
        for row in resp.data:
            all_sb_names.add(row["author_name"])
        if len(resp.data) < 1000:
            break
        offset += 1000

    stale_names = all_sb_names - current_names
    if stale_names:
        stale_list = list(stale_names)
        for i in range(0, len(stale_list), BATCH_SIZE):
            batch = stale_list[i:i + BATCH_SIZE]
            sb.table("authors_analytics").delete().in_("author_name", batch).execute()
        print(f"  Removed {len(stale_names)} stale author entries")

    print(f"  Done: {len(rows)} author analytics exported")


def export_stats_overview(sb: Client, db: DBManager):
    """Compute and export pre-aggregated stats."""
    print("\n--- Computing stats overview ---")

    articles_by_year = db.get_articles_by_year()
    article_types = db.get_article_type_distribution()
    top_journals = db.get_top_journals(25)
    top_authors = db.get_top_authors(30)
    processed_pmids = db.get_processed_pmids()

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

    upsert_with_retry(sb.table("stats_overview"), [stats], "id")
    print(f"  Done: stats exported (articles={stats['total_articles']}, "
          f"knowledge={stats['total_knowledge']}, "
          f"processed={stats['processing_progress']['processed']}/{stats['processing_progress']['total']})")


def export_coauthorship_network(sb: Client):
    """Export co-authorship network edges to Supabase via upsert."""
    print("\n--- Exporting co-authorship network ---")

    gexf_path = config.ANALYTICS_DIR / "author_network.gexf"
    if not gexf_path.exists():
        print("  No author_network.gexf found — skipping")
        return

    import networkx as nx
    G = nx.read_gexf(str(gexf_path))
    print(f"  Network: {len(G.nodes)} nodes, {len(G.edges)} edges")

    rows = []
    for a1, a2, data in G.edges(data=True):
        rows.append({
            "author1": a1,
            "author2": a2,
            "weight": int(data.get("weight", 1)),
        })

    for i in range(0, len(rows), BATCH_SIZE):
        batch = rows[i:i + BATCH_SIZE]
        upsert_with_retry(sb.table("coauthorship_edges"), batch, "author1,author2")

    # Remove stale edges
    current_pairs = {(r["author1"], r["author2"]) for r in rows}
    all_sb_edges = []
    offset = 0
    while True:
        resp = sb.table("coauthorship_edges").select("id,author1,author2").range(offset, offset + 999).execute()
        if not resp.data:
            break
        all_sb_edges.extend(resp.data)
        if len(resp.data) < 1000:
            break
        offset += 1000

    stale_ids = [e["id"] for e in all_sb_edges if (e["author1"], e["author2"]) not in current_pairs]
    if stale_ids:
        for i in range(0, len(stale_ids), BATCH_SIZE):
            batch = stale_ids[i:i + BATCH_SIZE]
            sb.table("coauthorship_edges").delete().in_("id", batch).execute()
        print(f"  Removed {len(stale_ids)} stale edges")

    print(f"  Done: {len(rows)} edges exported")


def export_monthly_newsletters(sb: Client, db: DBManager):
    """Export monthly newsletters to Supabase via upsert."""
    print("\n--- Exporting monthly newsletters ---")
    newsletters = db.get_all_newsletters()
    print(f"  {len(newsletters)} newsletters to export")

    if not newsletters:
        print("  No newsletters yet — skipping")
        return

    rows = []
    for n in newsletters:
        rows.append({
            "period_label": n.period_label,
            "period_start": str(n.period_start) if n.period_start else None,
            "period_end": str(n.period_end) if n.period_end else None,
            "new_articles_count": n.new_articles_count,
            "article_pmids": n.article_pmids or [],
            "clinical_trials_json": n.clinical_trials_json or [],
            "future_conferences_json": getattr(n, "future_conferences_json", []),
            "recent_conferences_json": getattr(n, "recent_conferences_json", []),
            "content_markdown": n.content_markdown,
            "created_at": n.created_at.isoformat() if n.created_at else datetime.utcnow().isoformat(),
        })

    for i in tqdm(range(0, len(rows), BATCH_SIZE), desc="  newsletters"):
        batch = rows[i:i + BATCH_SIZE]
        upsert_with_retry(sb.table("monthly_newsletters"), batch, "period_label")

    print(f"  Done: {len(rows)} newsletters exported")


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

    # Gap analysis is a singleton — upsert with id=1
    sb.table("gap_analysis").upsert({
        "id": 1,
        "content": content,
        "raw_json": raw_json,
    }, on_conflict="id").execute()
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
    export_monthly_newsletters(sb, db)
    export_author_analytics(sb, db)
    export_stats_overview(sb, db)
    export_coauthorship_network(sb)
    export_gap_analysis(sb)

    print("\n" + "=" * 60)
    print("Export complete! Your website should now show updated data.")
    print("=" * 60)


if __name__ == "__main__":
    main()
