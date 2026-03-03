#!/usr/bin/env python3
"""Scheduled: weekly new SBMA literature check and digest generation."""

import argparse
from rich.console import Console

from logger import setup_logger
from weekly_monitor.new_article_checker import NewArticleChecker
from weekly_monitor.novelty_scorer import NoveltyScorer
from weekly_monitor.report_generator import ReportGenerator

logger = setup_logger("run_weekly_monitor")
console = Console()


def run_weekly_check(days_back: int = 7, skip_scoring: bool = False):
    """Run the weekly monitoring pipeline.

    Args:
        days_back: Number of days to look back for new articles.
        skip_scoring: If True, skip novelty scoring (saves API costs).
    """
    console.print("[bold green]SBMA Research Agent — Weekly Monitor[/bold green]")
    console.print("=" * 60)

    # Step 1: Check for new articles
    console.print(f"\n[bold]Step 1: Checking for new articles (last {days_back} days)...[/bold]")
    checker = NewArticleChecker()
    new_articles = checker.check_new_articles(days_back=days_back)

    if not new_articles:
        console.print("[yellow]No new articles found this week.[/yellow]")
        # Still generate a report noting no new articles
        reporter = ReportGenerator()
        report_path = reporter.generate_report([], [])
        console.print(f"Empty report saved to: {report_path}")
        return

    console.print(f"Found [bold]{len(new_articles)}[/bold] new articles")

    # Step 2: Score novelty
    novelty_scores = []
    if not skip_scoring:
        console.print("\n[bold]Step 2: Scoring article novelty...[/bold]")
        scorer = NoveltyScorer()
        novelty_scores = scorer.score_articles(new_articles)
        console.print(f"Scored {len(novelty_scores)} articles")
    else:
        console.print("\n[yellow]Skipping novelty scoring[/yellow]")

    # Step 3: Generate report
    console.print("\n[bold]Step 3: Generating weekly digest...[/bold]")
    reporter = ReportGenerator()
    report_path = reporter.generate_report(new_articles, novelty_scores)

    console.print(f"\n[bold green]Weekly digest generated![/bold green]")
    console.print(f"Report: {report_path}")
    console.print(f"New articles: {len(new_articles)}")

    # Summary of high-impact findings
    high_impact = [s for s in novelty_scores
                   if s.get("category") == "high_impact" or
                   (s.get("novelty_score") or s.get("Novelty Score (1-10)", 0)) >= 7]
    if high_impact:
        console.print(f"\n[bold red]High-impact findings: {len(high_impact)}[/bold red]")
        for h in high_impact:
            console.print(f"  - PMID {h.get('pmid')}: {h.get('key_takeaway', 'N/A')}")


def main():
    parser = argparse.ArgumentParser(description="SBMA Weekly Literature Monitor")
    parser.add_argument("--days", type=int, default=7, help="Days to look back (default: 7)")
    parser.add_argument("--skip-scoring", action="store_true", help="Skip novelty scoring")
    args = parser.parse_args()

    run_weekly_check(days_back=args.days, skip_scoring=args.skip_scoring)


if __name__ == "__main__":
    main()
