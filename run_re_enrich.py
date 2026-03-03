#!/usr/bin/env python3
"""Re-enrich existing database articles with Semantic Scholar citation data and full text.

Run this after initial ingestion to fill in missing data:
  python run_re_enrich.py                # run both S2 + fulltext
  python run_re_enrich.py --only-s2      # only Semantic Scholar
  python run_re_enrich.py --only-fulltext # only full text retrieval
"""

import sys
import json
import argparse
from pathlib import Path
from datetime import datetime

from rich.console import Console
from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn, TimeElapsedColumn

import config
from logger import setup_logger
from database.db_manager import DBManager
from database.models import Article
from ingestion.semantic_scholar import SemanticScholarFetcher
from ingestion.fulltext_fetcher import FullTextFetcher

logger = setup_logger("re_enrich")
console = Console()

CHECKPOINT_FILE = config.CHECKPOINTS_DIR / "re_enrich_checkpoint.json"


def load_checkpoint() -> dict:
    if CHECKPOINT_FILE.exists():
        return json.loads(CHECKPOINT_FILE.read_text())
    return {"s2_done": [], "ft_done": []}


def save_checkpoint(checkpoint: dict):
    CHECKPOINT_FILE.write_text(json.dumps(checkpoint))


def enrich_semantic_scholar(db: DBManager, checkpoint: dict):
    """Enrich all articles with Semantic Scholar data using the batch API."""
    console.print("\n[bold]Semantic Scholar Enrichment (Batch API)[/bold]")
    console.print("=" * 50)

    ss = SemanticScholarFetcher()
    already_done = set(checkpoint.get("s2_done", []))

    # Get all PMIDs from DB
    all_pmids = db.get_all_pmids()
    remaining = [p for p in all_pmids if p not in already_done]

    if not remaining:
        console.print("[green]All articles already enriched via Semantic Scholar.[/green]")
        return

    console.print(f"Total articles: {len(all_pmids)}, already done: {len(already_done)}, remaining: {len(remaining)}")

    if not config.SEMANTIC_SCHOLAR_API_KEY:
        console.print("[yellow]No S2 API key — using unauthenticated access (slower). Set SEMANTIC_SCHOLAR_API_KEY in .env for faster results.[/yellow]")

    enriched_total = 0
    batch_size = SemanticScholarFetcher.BATCH_SIZE

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("{task.completed}/{task.total}"),
        TimeElapsedColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("Enriching via S2", total=len(remaining))

        for i in range(0, len(remaining), batch_size):
            batch_pmids = remaining[i : i + batch_size]
            batch_num = i // batch_size + 1
            total_batches = (len(remaining) + batch_size - 1) // batch_size

            try:
                results = ss.fetch_batch(batch_pmids)

                # Update DB for each result
                session = db.get_session()
                try:
                    for pmid, ss_data in results.items():
                        article = session.get(Article, pmid)
                        if not article:
                            continue

                        # Update citation count if S2 has higher
                        if ss_data["citation_count"] > (article.citation_count or 0):
                            article.citation_count = ss_data["citation_count"]

                        # Merge cited_by
                        existing_cited_by = article.cited_by or []
                        merged_cited_by = list(set(existing_cited_by + ss_data["cited_by"]))
                        article.cited_by = merged_cited_by

                        # Merge references
                        existing_refs = article.references or []
                        merged_refs = list(set(existing_refs + ss_data["references"]))
                        article.references = merged_refs

                        article.date_last_updated = datetime.utcnow()
                        enriched_total += 1

                    session.commit()
                except Exception:
                    session.rollback()
                    raise
                finally:
                    session.close()

                # Checkpoint after each batch
                already_done.update(batch_pmids)
                checkpoint["s2_done"] = list(already_done)
                save_checkpoint(checkpoint)

                found_pct = len(results) / len(batch_pmids) * 100 if batch_pmids else 0
                logger.info(f"S2 batch {batch_num}/{total_batches}: {len(results)}/{len(batch_pmids)} found ({found_pct:.0f}%)")

            except Exception as e:
                logger.error(f"S2 batch {batch_num} failed: {e}")
                console.print(f"[red]Batch {batch_num} failed: {e}[/red]")

            progress.update(task, advance=len(batch_pmids))

    console.print(f"\n[green]Semantic Scholar enrichment complete: {enriched_total} articles updated[/green]")


def enrich_fulltext(db: DBManager, checkpoint: dict):
    """Fetch full text (PMC + Unpaywall) for articles that don't have it."""
    console.print("\n[bold]Full Text Retrieval (PMC + Unpaywall)[/bold]")
    console.print("=" * 50)

    ft = FullTextFetcher()
    already_done = set(checkpoint.get("ft_done", []))

    # Get articles without full text
    session = db.get_session()
    try:
        articles = (
            session.query(Article.pmid, Article.doi)
            .filter(
                (Article.fulltext_available == False) | (Article.fulltext_available == None)
            )
            .all()
        )
    finally:
        session.close()

    candidates = [(pmid, doi) for pmid, doi in articles if pmid not in already_done]

    if not candidates:
        console.print("[green]All articles already checked for full text.[/green]")
        return

    console.print(f"Articles without full text: {len(articles)}, already checked: {len(already_done)}, remaining: {len(candidates)}")

    if not config.UNPAYWALL_EMAIL:
        console.print("[yellow]No UNPAYWALL_EMAIL set — Unpaywall lookups will be skipped. Set it in .env for open-access full text.[/yellow]")

    found = 0

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("{task.completed}/{task.total}"),
        TimeElapsedColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("Fetching full text", total=len(candidates))

        for idx, (pmid, doi) in enumerate(candidates):
            try:
                result = ft.fetch_fulltext(pmid, doi or "")
                if result:
                    # Update DB
                    db.upsert_article({
                        "pmid": pmid,
                        "fulltext_available": result["fulltext_available"],
                        "fulltext_source": result["fulltext_source"],
                        "fulltext_path": result["fulltext_path"],
                    })
                    found += 1
                    logger.debug(f"Full text found for {pmid} via {result['fulltext_source']}")
            except Exception as e:
                logger.debug(f"Full text retrieval failed for {pmid}: {e}")

            # Checkpoint every 50 articles
            already_done.add(pmid)
            if (idx + 1) % 50 == 0:
                checkpoint["ft_done"] = list(already_done)
                save_checkpoint(checkpoint)

            progress.update(task, advance=1)

    # Final checkpoint
    checkpoint["ft_done"] = list(already_done)
    save_checkpoint(checkpoint)

    total_ft = db.get_fulltext_count()
    console.print(f"\n[green]Full text retrieval complete: {found} new articles found[/green]")
    console.print(f"Total articles with full text: {total_ft}/{db.get_article_count()}")


def main():
    parser = argparse.ArgumentParser(description="Re-enrich existing articles with S2 + full text")
    parser.add_argument("--only-s2", action="store_true", help="Only run Semantic Scholar enrichment")
    parser.add_argument("--only-fulltext", action="store_true", help="Only run full text retrieval")
    parser.add_argument("--reset", action="store_true", help="Reset checkpoint and start fresh")
    args = parser.parse_args()

    console.print("[bold green]SBMA Research Agent — Re-Enrichment[/bold green]")
    console.print("=" * 60)

    db = DBManager()
    total = db.get_article_count()
    console.print(f"Database contains [bold]{total}[/bold] articles")

    if args.reset and CHECKPOINT_FILE.exists():
        CHECKPOINT_FILE.unlink()
        console.print("[yellow]Checkpoint reset.[/yellow]")

    checkpoint = load_checkpoint()

    run_s2 = not args.only_fulltext
    run_ft = not args.only_s2

    if run_s2:
        enrich_semantic_scholar(db, checkpoint)

    if run_ft:
        enrich_fulltext(db, checkpoint)

    console.print("\n[bold green]Re-enrichment complete![/bold green]")

    # Print summary
    ft_count = db.get_fulltext_count()
    console.print(f"\nFinal stats:")
    console.print(f"  Articles with full text: {ft_count}/{total}")


if __name__ == "__main__":
    main()
