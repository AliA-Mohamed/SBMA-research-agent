#!/usr/bin/env python3
"""On-demand: run field analytics and generate visualizations."""

import sys
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rich.console import Console

from logger import setup_logger
from analysis.field_analytics import FieldAnalytics
from analysis.gap_analyzer import GapAnalyzer
import config

logger = setup_logger("run_analytics")
console = Console()


def main():
    parser = argparse.ArgumentParser(description="SBMA Field Analytics")
    parser.add_argument("--skip-gaps", action="store_true", help="Skip gap analysis (requires Claude API)")
    args = parser.parse_args()

    console.print("[bold green]SBMA Research Agent — Field Analytics[/bold green]")
    console.print("=" * 60)

    # Run field analytics (no API calls needed)
    console.print("\n[bold]Running field analytics...[/bold]")
    analytics = FieldAnalytics()
    analytics.run_all()

    # Run gap analysis (requires Claude API)
    if not args.skip_gaps:
        console.print("\n[bold]Running gap analysis (Claude API)...[/bold]")
        gap_analyzer = GapAnalyzer()
        gaps = gap_analyzer.analyze_gaps()
        if gaps:
            console.print("[green]Gap analysis complete[/green]")
        else:
            console.print("[yellow]Gap analysis produced no results[/yellow]")
    else:
        console.print("[yellow]Skipping gap analysis[/yellow]")

    console.print(f"\n[bold green]Analytics complete![/bold green]")
    console.print(f"Output directory: {config.ANALYTICS_DIR}")


if __name__ == "__main__":
    main()
