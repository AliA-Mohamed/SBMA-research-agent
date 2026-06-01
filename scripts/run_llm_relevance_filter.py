#!/usr/bin/env python3
"""LLM-based SBMA relevance filter.

Uses an AI model to classify each article as relevant or irrelevant to
Spinal and Bulbar Muscular Atrophy (Kennedy's disease) research,
based on title and abstract.

Usage:
    python run_llm_relevance_filter.py --dry-run       # Preview, no changes
    python run_llm_relevance_filter.py --remove         # Remove irrelevant articles
    python run_llm_relevance_filter.py --export-csv     # Export results to CSV
"""

import sys
import csv
import json
import time
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rich.console import Console
from rich.table import Table
from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn

import config
from logger import setup_logger
from database.db_manager import DBManager
from analysis.llm_relevance import classify_article_relevance

logger = setup_logger("llm_relevance_filter")
console = Console()


def audit_articles(db: DBManager) -> tuple[list[dict], list[dict]]:
    """Classify all articles using LLM and return (relevant, not_relevant)."""
    session = db.get_session()
    try:
        from database.models import Article
        articles = session.query(Article).order_by(Article.publication_year).all()
        total = len(articles)
        console.print(f"Classifying [bold]{total}[/bold] articles with LLM ({config.LLM_BACKEND})...\n")

        relevant = []
        not_relevant = []

        # Check for existing checkpoint
        checkpoint_path = config.CHECKPOINTS_DIR / "llm_relevance_checkpoint.json"
        classified = {}
        if checkpoint_path.exists():
            classified = json.loads(checkpoint_path.read_text())
            console.print(f"Resuming from checkpoint: {len(classified)} already classified\n")

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
            TextColumn("({task.completed}/{task.total})"),
            console=console,
        ) as progress:
            task = progress.add_task("Classifying...", total=total)

            for i, art in enumerate(articles):
                pmid = art.pmid

                # Use cached result if available
                if pmid in classified:
                    result = classified[pmid]
                else:
                    result = classify_article_relevance(art.title, art.abstract)
                    classified[pmid] = result

                    # Rate limit for Gemini free tier (~15 req/min)
                    if config.LLM_BACKEND == "gemini":
                        time.sleep(4)  # ~15 req/min steady pace

                    # Save checkpoint every 10 articles
                    if len(classified) % 10 == 0:
                        checkpoint_path.write_text(json.dumps(classified, indent=2))
                        console.print(f"  [dim]Checkpoint: {len(classified)} classified[/dim]")

                article_dict = {
                    "pmid": pmid,
                    "title": art.title or "",
                    "abstract": art.abstract or "",
                    "journal": art.journal or "",
                    "publication_year": art.publication_year,
                    "llm_reason": result.get("reason", ""),
                }

                if result["relevant"]:
                    relevant.append(article_dict)
                else:
                    not_relevant.append(article_dict)

                progress.update(task, advance=1)

        # Final checkpoint save
        checkpoint_path.write_text(json.dumps(classified, indent=2))
        return relevant, not_relevant

    finally:
        session.close()


def print_flagged_articles(not_relevant: list[dict]):
    """Print a table of articles flagged for removal."""
    table = Table(title="Articles Flagged as NOT SBMA-Relevant (by LLM)", show_lines=True)
    table.add_column("#", style="dim", width=4)
    table.add_column("PMID", style="dim", width=10)
    table.add_column("Year", width=6)
    table.add_column("Title", max_width=60)
    table.add_column("Reason", max_width=40, style="red")

    for idx, art in enumerate(sorted(not_relevant, key=lambda x: x.get("publication_year") or 0), 1):
        table.add_row(
            str(idx),
            art["pmid"],
            str(art.get("publication_year", "?")),
            art["title"][:60],
            art.get("llm_reason", "")[:40],
        )

    console.print(table)


def export_csv(not_relevant: list[dict], output_path: Path):
    """Export flagged articles to CSV for manual review."""
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f, fieldnames=["pmid", "publication_year", "title", "journal", "llm_reason"]
        )
        writer.writeheader()
        for art in sorted(not_relevant, key=lambda x: x.get("publication_year") or 0):
            writer.writerow({
                "pmid": art["pmid"],
                "publication_year": art.get("publication_year", ""),
                "title": art["title"],
                "journal": art.get("journal", ""),
                "llm_reason": art.get("llm_reason", ""),
            })
    console.print(f"Exported to [bold]{output_path}[/bold]")


def remove_articles(db: DBManager, pmids: list[str]):
    """Remove articles and their extracted knowledge from the database."""
    session = db.get_session()
    try:
        from database.models import Article, ExtractedKnowledge

        ek_deleted = session.query(ExtractedKnowledge).filter(
            ExtractedKnowledge.pmid.in_(pmids)
        ).delete(synchronize_session="fetch")

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
    parser = argparse.ArgumentParser(description="LLM-based SBMA relevance filter")
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
    total = len(relevant) + len(not_relevant)
    console.print(
        f"[bold]Rejection rate:[/bold] {len(not_relevant) / total * 100:.1f}%\n"
    )

    if not not_relevant:
        console.print("[green]All articles appear to be SBMA-relevant![/green]")
        return

    if args.dry_run or args.remove:
        print_flagged_articles(not_relevant)

    if args.export_csv:
        csv_path = config.OUTPUTS_DIR / "non_sbma_articles_llm_flagged.csv"
        export_csv(not_relevant, csv_path)

    if args.remove:
        console.print(f"\n[bold red]Removing {len(not_relevant)} non-SBMA articles...[/bold red]")
        pmids_to_remove = [a["pmid"] for a in not_relevant]
        remove_articles(db, pmids_to_remove)

        # Clean up checkpoint
        checkpoint_path = config.CHECKPOINTS_DIR / "llm_relevance_checkpoint.json"
        if checkpoint_path.exists():
            checkpoint_path.unlink()
            console.print("Cleared LLM relevance checkpoint")

        remaining = db.get_article_count()
        console.print(f"\n[bold green]Articles remaining in DB: {remaining}[/bold green]")


if __name__ == "__main__":
    main()
