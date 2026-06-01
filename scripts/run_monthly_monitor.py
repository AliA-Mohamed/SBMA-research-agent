#!/usr/bin/env python3
"""Monthly SBMA newsletter generation — checks PubMed, ClinicalTrials.gov, and writes newsletter."""

import sys
import argparse
import calendar
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rich.console import Console

import config
from logger import setup_logger
from database.db_manager import DBManager
from weekly_monitor.new_article_checker import NewArticleChecker
from weekly_monitor.novelty_scorer import NoveltyScorer
from monthly_monitor.news_fetcher import NewsFetcher
from monthly_monitor.newsletter_generator import NewsletterGenerator

logger = setup_logger("run_monthly_monitor")
console = Console()

NEWSLETTERS_DIR = config.OUTPUTS_DIR / "newsletters"
NEWSLETTERS_DIR.mkdir(parents=True, exist_ok=True)


def run_monthly_newsletter(
    days_back: int = 30,
    skip_scoring: bool = False,
    month: int | None = None,
    year: int | None = None,
):
    """Run the full monthly newsletter pipeline.

    Args:
        days_back: Days to look back for new articles (default 30, ignored if month/year set).
        skip_scoring: Skip LLM novelty scoring to save API costs.
        month: Specific month (1-12). If set with year, overrides days_back.
        year: Specific year. If set with month, overrides days_back.
    """
    console.print("[bold green]SBMA Research Agent — Monthly Newsletter[/bold green]")
    console.print("=" * 60)

    if month and year:
        period_start = date(year, month, 1)
        last_day = calendar.monthrange(year, month)[1]
        period_end = date(year, month, last_day)
    else:
        period_end = date.today()
        period_start = period_end - timedelta(days=days_back)
    period_label = period_start.strftime("%B %Y")

    console.print(f"Period: [bold]{period_start}[/bold] → [bold]{period_end}[/bold]")

    # ── Step 1: New PubMed articles ──────────────────────────────────────────
    console.print(f"\n[bold]Step 1:[/bold] Checking PubMed for new articles ({period_start} → {period_end})…")
    checker = NewArticleChecker()
    if month and year:
        new_articles = checker.check_new_articles(
            start=datetime.combine(period_start, datetime.min.time()),
            end=datetime.combine(period_end, datetime.max.time()),
        )
    else:
        new_articles = checker.check_new_articles(days_back=days_back)
    console.print(f"  Found [bold]{len(new_articles)}[/bold] new articles")

    # ── Step 2: Novelty scoring ──────────────────────────────────────────────
    novelty_scores = []
    if new_articles and not skip_scoring:
        console.print("\n[bold]Step 2:[/bold] Scoring article novelty…")
        scorer = NoveltyScorer()
        novelty_scores = scorer.score_articles(new_articles)
        console.print(f"  Scored {len(novelty_scores)} articles")
    else:
        console.print("\n[yellow]Step 2: Skipping novelty scoring[/yellow]")

    # ── Step 3: Clinical trials & conferences ────────────────────────────────
    console.print("\n[bold]Step 3:[/bold] Fetching clinical trials from ClinicalTrials.gov…")
    fetcher = NewsFetcher()
    clinical_trials = fetcher.fetch_clinical_trials()
    future_conferences = fetcher.get_future_conferences()
    recent_conferences = fetcher.get_recent_conferences()
    console.print(f"  Found [bold]{len(clinical_trials)}[/bold] active SBMA trials")
    console.print(f"  Loaded [bold]{len(future_conferences)}[/bold] future and [bold]{len(recent_conferences)}[/bold] recent conferences")

    # ── Step 4: Generate newsletter with Claude ──────────────────────────────
    console.print("\n[bold]Step 4:[/bold] Generating newsletter with Claude…")
    generator = NewsletterGenerator()
    newsletter_md = generator.generate(
        new_articles=new_articles,
        novelty_scores=novelty_scores,
        clinical_trials=clinical_trials,
        future_conferences=future_conferences,
        recent_conferences=recent_conferences,
        period_start=period_start,
        period_end=period_end,
    )

    # ── Step 5: Save to file ─────────────────────────────────────────────────
    filename = f"newsletter_{period_start.strftime('%Y_%m')}.md"
    file_path = NEWSLETTERS_DIR / filename
    file_path.write_text(newsletter_md)
    console.print(f"  Saved: [bold]{file_path}[/bold]")

    # ── Step 6: Store in database ────────────────────────────────────────────
    console.print("\n[bold]Step 6:[/bold] Storing in database…")
    db = DBManager()
    db.upsert_monthly_newsletter({
        "period_label": period_label,
        "period_start": period_start,
        "period_end": period_end,
        "new_articles_count": len(new_articles),
        "article_pmids": [a.get("pmid", "") for a in new_articles],
        "clinical_trials_json": clinical_trials,
        "future_conferences_json": future_conferences,
        "recent_conferences_json": recent_conferences,
        "content_markdown": newsletter_md,
    })
    console.print("  Stored in local database")

    # ── Done ─────────────────────────────────────────────────────────────────
    console.print(f"\n[bold green]Newsletter generated![/bold green]")
    console.print(f"  Period: {period_label}")
    console.print(f"  New articles: {len(new_articles)}")
    console.print(f"  Active trials: {len(clinical_trials)}")
    console.print(f"  File: {file_path}")
    console.print(
        "\n[dim]Next step: run export_to_supabase.py to publish to the website.[/dim]"
    )

    return str(file_path)


def main():
    parser = argparse.ArgumentParser(description="SBMA Monthly Newsletter Generator")
    parser.add_argument(
        "--days", type=int, default=30,
        help="Days to look back for new articles (default: 30)"
    )
    parser.add_argument(
        "--skip-scoring", action="store_true",
        help="Skip LLM novelty scoring (saves API costs, newsletter will have less detail)"
    )
    parser.add_argument(
        "--month", type=int, choices=range(1, 13), metavar="1-12",
        help="Target month (1-12). Use with --year to generate a newsletter for a specific month."
    )
    parser.add_argument(
        "--year", type=int,
        help="Target year (e.g. 2026). Use with --month."
    )
    args = parser.parse_args()
    if (args.month and not args.year) or (args.year and not args.month):
        parser.error("--month and --year must be used together")
    run_monthly_newsletter(
        days_back=args.days,
        skip_scoring=args.skip_scoring,
        month=args.month,
        year=args.year,
    )


if __name__ == "__main__":
    main()
