#!/usr/bin/env python3
"""Run the knowledge network analysis pipeline.

Analyzes each textbook chapter cluster to produce:
- Knowledge networks (nodes + edges)
- Molecular/clinical pathways
- Testable hypotheses
- Per-cluster and cross-cluster gaps

Usage:
    python scripts/run_knowledge_networks.py                    # all chapters
    python scripts/run_knowledge_networks.py --chapter "Chapter 3: Pathophysiology & Disease Mechanisms"
    python scripts/run_knowledge_networks.py --chapters 2 3 8   # by chapter number
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from analysis.knowledge_network_builder import KnowledgeNetworkBuilder
from analysis.knowledge_extractor import CANONICAL_CHAPTERS


def main():
    parser = argparse.ArgumentParser(description="SBMA Knowledge Network Analysis")
    parser.add_argument(
        "--chapter", type=str, help="Analyze a single chapter (full name)"
    )
    parser.add_argument(
        "--chapters",
        type=int,
        nargs="+",
        help="Analyze specific chapters by number (e.g., 2 3 8)",
    )
    parser.add_argument(
        "--skip-cross-cluster",
        action="store_true",
        help="Skip the cross-cluster synthesis step",
    )
    args = parser.parse_args()

    builder = KnowledgeNetworkBuilder()

    # Resolve chapter filter
    chapters = None
    if args.chapter:
        chapters = [args.chapter]
    elif args.chapters:
        chapters = []
        for num in args.chapters:
            if 1 <= num <= len(CANONICAL_CHAPTERS):
                chapters.append(CANONICAL_CHAPTERS[num - 1])
            else:
                print(f"Warning: Chapter {num} out of range (1-{len(CANONICAL_CHAPTERS)})")

    result = builder.run(chapters=chapters)

    # Print summary
    print("\n" + "=" * 60)
    print("KNOWLEDGE NETWORK ANALYSIS COMPLETE")
    print("=" * 60)

    for ch_name, ch_data in sorted(result.get("chapters", {}).items()):
        if not isinstance(ch_data, dict) or "raw_response" in ch_data:
            print(f"  {ch_name}: FAILED")
            continue
        meta = ch_data.get("_meta", {})
        net = ch_data.get("knowledge_network", {})
        print(
            f"  {ch_name}: "
            f"{len(net.get('nodes', []))} nodes, "
            f"{len(net.get('edges', []))} edges, "
            f"{len(ch_data.get('pathways', []))} pathways, "
            f"{len(ch_data.get('hypotheses', []))} hypotheses, "
            f"{len(ch_data.get('cluster_gaps', []))} gaps"
        )

    cross = result.get("cross_cluster", {})
    if cross and "raw_response" not in cross:
        print(f"\n  Cross-cluster: "
              f"{len(cross.get('cross_cluster_gaps', []))} gaps, "
              f"{len(cross.get('integrative_hypotheses', []))} hypotheses, "
              f"{len(cross.get('research_roadmap', []))} roadmap items")

    print(f"\nOutputs saved to: outputs/analytics/knowledge_networks/")


if __name__ == "__main__":
    main()
