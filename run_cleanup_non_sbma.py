#!/usr/bin/env python3
"""Audit and remove non-SBMA articles from the existing database.

This script applies the SBMA relevance filter to all articles already in the DB,
identifies those that are NOT primarily about SBMA, and optionally removes them.

Usage:
    python run_cleanup_non_sbma.py --dry-run     # Preview what would be removed
    python run_cleanup_non_sbma.py --remove       # Actually remove non-SBMA articles
    python run_cleanup_non_sbma.py --export-csv   # Export flagged articles to CSV for review
"""

import sys
import csv
import argparse
from pathlib import Path

from rich.console import Console
from rich.table import Table

import config
from logger import setup_logger
from database.db_manager import DBManager
from ingestion.pubmed_fetcher import PubMedFetcher

logger = setup_logger("cleanup_non_sbma")
console = Console()


def audit_articles(db: DBManager) -> tuple[list[dict], list[dict]]:
    """Scan all articles and classify as SBMA-relevant or not.

    Returns (relevant, not_relevant) lists of article dicts.
    """
    session = db.get_session()
    try:
        from database.models import Article
        articles = session.query(Article).all()
        console.print(f"Scanning [bold]{len(articles)}[/bold] articles for SBMA relevance...\n")

        relevant = []
        not_relevant = []

        for art in articles:
            article_dict = {
                "pmid": art.pmid,
                "title": art.title or "",
                "abstract": art.abstract or "",
                "mesh_terms": art.mesh_terms or [],
                "keywords": art.keywords or [],
                "journal": art.journal or "",
                "publication_year": art.publication_year,
            }

            if PubMedFetcher.is_sbma_relevant(article_dict):
                relevant.append(article_dict)
            else:
                not_relevant.append(article_dict)

        return relevant, not_relevant
    finally:
        session.close()


def print_flagged_articles(not_relevant: list[dict]):
    """Print a table of articles flagged for removal."""
    table = Table(title="Articles Flagged as NOT SBMA-Relevant", show_lines=True)
    table.add_column("PMID", style="dim", width=10)
    table.add_column("Year", width=6)
    table.add_column("Title", max_width=80)
    table.add_column("Journal", max_width=30)

    for art in sorted(not_relevant, key=lambda x: x.get("publication_year") or 0):
        table.add_row(
            art["pmid"],
            str(art.get("publication_year", "?")),
            art["title"][:80],
            art.get("journal", "")[:30],
        )

    console.print(table)


def export_csv(not_relevant: list[dict], output_path: Path):
    """Export flagged articles to CSV for manual review."""
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["pmid", "publication_year", "title", "journal"])
        writer.writeheader()
        for art in sorted(not_relevant, key=lambda x: x.get("publication_year") or 0):
            writer.writerow({
                "pmid": art["pmid"],
                "publication_year": art.get("publication_year", ""),
                "title": art["title"],
                "journal": art.get("journal", ""),
            })
    console.print(f"Exported to [bold]{output_path}[/bold]")


def remove_articles(db: DBManager, pmids: list[str]):
    """Remove articles and their extracted knowledge from the database."""
    session = db.get_session()
    try:
        from database.models import Article, ExtractedKnowledge

        # Delete extracted knowledge first (foreign key constraint)
        ek_deleted = session.query(ExtractedKnowledge).filter(
            ExtractedKnowledge.pmid.in_(pmids)
        ).delete(synchronize_session="fetch")

        # Delete articles
        art_deleted = session.query(Article).filter(
            Article.pmid.in_(pmids)
        ).delete(synchronize_session="fetch")

        session.commit()
        console.print(
            f"Removed [bold red]{art_deleted}[/bold red] articles and "
            f"[bold red]{ek_deleted}[/bold red] extracted knowledge entries"
        )
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def main():
    parser = argparse.ArgumentParser(description="Audit and clean non-SBMA articles from DB")
    parser.add_argument("--dry-run", action="store_true", help="Preview only, no changes")
    parser.add_argument("--remove", action="store_true", help="Remove flagged articles from DB")
    parser.add_argument("--export-csv", action="store_true", help="Export flagged articles to CSV")
    args = parser.parse_args()

    if not args.dry_run and not args.remove and not args.export_csv:
        args.dry_run = True
        console.print("[yellow]No action specified — defaulting to --dry-run[/yellow]\n")

    db = DBManager()
    relevant, not_relevant = audit_articles(db)

    console.print(f"\n[bold green]SBMA-relevant:[/bold green] {len(relevant)} articles")
    console.print(f"[bold red]NOT SBMA-relevant:[/bold red] {len(not_relevant)} articles")
    console.print(
        f"[bold]Rejection rate:[/bold] "
        f"{len(not_relevant) / (len(relevant) + len(not_relevant)) * 100:.1f}%\n"
    )

    if not not_relevant:
        console.print("[green]All articles appear to be SBMA-relevant![/green]")
        return

    if args.dry_run or args.remove:
        print_flagged_articles(not_relevant)

    if args.export_csv:
        csv_path = config.OUTPUTS_DIR / "non_sbma_articles_flagged.csv"
        export_csv(not_relevant, csv_path)

    if args.remove:
        console.print(f"\n[bold red]Removing {len(not_relevant)} non-SBMA articles...[/bold red]")
        pmids_to_remove = [a["pmid"] for a in not_relevant]
        remove_articles(db, pmids_to_remove)

        # Update checkpoint to reflect removed PMIDs
        checkpoint_file = config.CHECKPOINTS_DIR / "pubmed_fetch_checkpoint.json"
        if checkpoint_file.exists():
            import json
            checkpoint = json.loads(checkpoint_file.read_text())
            old_pmids = set(checkpoint.get("fetched_pmids", []))
            new_pmids = old_pmids - set(pmids_to_remove)
            checkpoint["fetched_pmids"] = list(new_pmids)
            checkpoint["cleanup_removed"] = len(pmids_to_remove)
            checkpoint_file.write_text(json.dumps(checkpoint))
            console.print("Updated checkpoint file")

        remaining = db.get_article_count()
        console.print(f"\n[bold green]Articles remaining in DB: {remaining}[/bold green]")


if __name__ == "__main__":
    main()
