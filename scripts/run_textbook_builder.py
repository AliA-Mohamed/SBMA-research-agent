#!/usr/bin/env python3
"""One-time: generate the SBMA textbook from the article database."""

import sys
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rich.console import Console

from logger import setup_logger
from analysis.textbook_builder import TextbookBuilder

logger = setup_logger("run_textbook_builder")
console = Console()


def main():
    parser = argparse.ArgumentParser(description="Build the SBMA Textbook from primary literature")
    parser.add_argument("--no-resume", action="store_true", help="Start fresh instead of resuming")
    parser.add_argument("--limit", type=int, default=0, help="Process only N articles then stop (0 = all)")
    args = parser.parse_args()

    console.print("[bold green]SBMA Research Agent — Textbook Builder[/bold green]")
    console.print("=" * 60)

    if args.limit:
        console.print(f"[yellow]Processing {args.limit} articles then stopping. Re-run to continue.[/yellow]")

    builder = TextbookBuilder()
    builder.build_textbook(resume=not args.no_resume, limit=args.limit)

    processed = len(builder.db.get_processed_pmids())
    total = builder.db.get_article_count()
    console.print(f"\n[bold green]Batch complete![/bold green]")
    console.print(f"Progress: {processed}/{total} articles processed ({processed*100//total}%)")
    console.print(f"Textbook chapters: {len(builder.db.get_textbook_sections())}")
    console.print(f"\nRun again to continue from where you left off.")


if __name__ == "__main__":
    main()
