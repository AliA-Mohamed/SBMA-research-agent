#!/usr/bin/env python3
"""One-time initial ingestion: fetch all SBMA articles, enrich, and build the database."""

import sys
import json
import argparse
from pathlib import Path

from rich.console import Console
from rich.table import Table
from tqdm import tqdm

import config
from logger import setup_logger
from database.db_manager import DBManager
from ingestion.pubmed_fetcher import PubMedFetcher
from ingestion.crossref_fetcher import CrossRefFetcher
from ingestion.semantic_scholar import SemanticScholarFetcher
from ingestion.fulltext_fetcher import FullTextFetcher

logger = setup_logger("initial_ingestion")
console = Console()


def run_ingestion(test_mode: bool = False, skip_enrichment: bool = False,
                  skip_fulltext: bool = False, batch_size: int = 20):
    """Run the full initial ingestion pipeline.

    Args:
        test_mode: If True, only fetch 20 articles for testing.
        skip_enrichment: If True, skip CrossRef and Semantic Scholar enrichment.
        skip_fulltext: If True, skip full text retrieval.
        batch_size: Number of articles to fetch per PubMed API call.
    """
    console.print("[bold green]SBMA Research Agent — Initial Ingestion[/bold green]")
    console.print("=" * 60)

    db = DBManager()

    # --- Step 1: Fetch from PubMed ---
    console.print("\n[bold]Step 1: Fetching articles from PubMed...[/bold]")
    fetcher = PubMedFetcher()

    if test_mode:
        console.print("[yellow]TEST MODE: Fetching only 20 articles[/yellow]")
        pmids = fetcher.search_all_pmids()
        pmids = pmids[:20]
        articles = fetcher.fetch_article_details(pmids)
    else:
        articles = fetcher.fetch_all_articles(batch_size=batch_size)

    console.print(f"Fetched [bold]{len(articles)}[/bold] articles from PubMed")

    # --- Step 2: Enrich via CrossRef ---
    if not skip_enrichment:
        console.print("\n[bold]Step 2: Enriching via CrossRef...[/bold]")
        crossref = CrossRefFetcher()
        articles = crossref.enrich_articles(articles)

        # --- Step 3: Enrich via Semantic Scholar ---
        console.print("\n[bold]Step 3: Enriching via Semantic Scholar (batch API)...[/bold]")
        if not config.SEMANTIC_SCHOLAR_API_KEY:
            console.print("[yellow]  No API key — using unauthenticated access (slower rate limit)[/yellow]")
        ss = SemanticScholarFetcher()
        articles = ss.enrich_articles(articles)
    else:
        console.print("\n[yellow]Skipping enrichment (CrossRef + Semantic Scholar)[/yellow]")

    # --- Step 4: Full text retrieval ---
    if not skip_fulltext:
        console.print("\n[bold]Step 4: Attempting full text retrieval...[/bold]")
        ft = FullTextFetcher()
        articles = ft.enrich_articles(articles)
    else:
        console.print("\n[yellow]Skipping full text retrieval[/yellow]")

    # --- Step 5: Store in database ---
    console.print("\n[bold]Step 5: Storing articles in database...[/bold]")
    count = db.upsert_articles_bulk(articles)
    console.print(f"Stored [bold]{count}[/bold] articles in database")

    # --- Step 6: Print summary statistics ---
    print_summary(db)

    # Save ingestion summary
    summary_path = config.OUTPUTS_DIR / "ingestion_summary.json"
    summary = {
        "total_articles": db.get_article_count(),
        "test_mode": test_mode,
        "enrichment_skipped": skip_enrichment,
        "fulltext_skipped": skip_fulltext,
    }
    summary_path.write_text(json.dumps(summary, indent=2))
    console.print(f"\nSummary saved to {summary_path}")


def print_summary(db: DBManager):
    """Print summary statistics of the database."""
    console.print("\n" + "=" * 60)
    console.print("[bold green]INGESTION SUMMARY[/bold green]")
    console.print("=" * 60)

    # Total articles
    total = db.get_article_count()
    console.print(f"\n[bold]Total articles:[/bold] {total}")

    # Date range
    articles_by_year = db.get_articles_by_year()
    if articles_by_year:
        years = sorted(articles_by_year.keys())
        console.print(f"[bold]Date range:[/bold] {years[0]} — {years[-1]}")

    # Top 20 authors
    console.print("\n[bold]Top 20 Authors by Publication Count:[/bold]")
    table = Table(show_header=True, header_style="bold")
    table.add_column("Rank", style="dim", width=5)
    table.add_column("Author")
    table.add_column("Papers", justify="right")
    for i, (name, count) in enumerate(db.get_top_authors(20), 1):
        table.add_row(str(i), name, str(count))
    console.print(table)

    # Top 10 journals
    console.print("\n[bold]Top 10 Journals:[/bold]")
    table = Table(show_header=True, header_style="bold")
    table.add_column("Rank", style="dim", width=5)
    table.add_column("Journal")
    table.add_column("Papers", justify="right")
    for i, (name, count) in enumerate(db.get_top_journals(10), 1):
        table.add_row(str(i), name, str(count))
    console.print(table)

    # Article type distribution
    console.print("\n[bold]Article Type Distribution:[/bold]")
    table = Table(show_header=True, header_style="bold")
    table.add_column("Type")
    table.add_column("Count", justify="right")
    for atype, count in sorted(db.get_article_type_distribution().items(), key=lambda x: -x[1]):
        table.add_row(atype, str(count))
    console.print(table)

    # Full text
    ft_count = db.get_fulltext_count()
    console.print(f"\n[bold]Articles with full text:[/bold] {ft_count}/{total}")

    # Articles per year (mini chart)
    if articles_by_year:
        console.print("\n[bold]Articles per Year:[/bold]")
        max_count = max(articles_by_year.values())
        for year in sorted(articles_by_year.keys()):
            count = articles_by_year[year]
            bar_len = int(40 * count / max_count) if max_count > 0 else 0
            bar = "█" * bar_len
            console.print(f"  {year} | {bar} {count}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="SBMA Research Agent — Initial Ingestion")
    parser.add_argument("--test", action="store_true", help="Test mode: only fetch 20 articles")
    parser.add_argument("--skip-enrichment", action="store_true", help="Skip CrossRef/Semantic Scholar enrichment")
    parser.add_argument("--skip-fulltext", action="store_true", help="Skip full text retrieval")
    parser.add_argument("--batch-size", type=int, default=100, help="PubMed fetch batch size")
    args = parser.parse_args()

    run_ingestion(
        test_mode=args.test,
        skip_enrichment=args.skip_enrichment,
        skip_fulltext=args.skip_fulltext,
        batch_size=args.batch_size,
    )
