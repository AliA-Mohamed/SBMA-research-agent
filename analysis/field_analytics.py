"""Author networks, journal stats, citation analysis, and field trends."""

import sys
import json
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

import pandas as pd
import matplotlib
matplotlib.use("Agg")  # Non-interactive backend
import matplotlib.pyplot as plt
import plotly.express as px
import plotly.graph_objects as go
import networkx as nx

sys.path.insert(0, str(Path(__file__).parent.parent))
import config
from logger import setup_logger
from database.db_manager import DBManager

logger = setup_logger("field_analytics")


class FieldAnalytics:
    """Generates field-level analytics and visualizations."""

    def __init__(self):
        self.db = DBManager()
        self.output_dir = config.ANALYTICS_DIR
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def run_all(self):
        """Run all analytics."""
        logger.info("Running field analytics...")
        self.publication_timeline()
        self.journal_distribution()
        self.author_network()
        self.citation_analysis()
        self.topic_evolution()
        self.article_type_trends()
        self.author_stats()
        logger.info(f"All analytics saved to {self.output_dir}")

    def publication_timeline(self):
        """Articles per year showing growth of the field."""
        articles_by_year = self.db.get_articles_by_year()
        if not articles_by_year:
            logger.warning("No data for publication timeline")
            return

        years = sorted(articles_by_year.keys())
        counts = [articles_by_year[y] for y in years]

        # Matplotlib version
        fig, ax = plt.subplots(figsize=(14, 6))
        ax.bar(years, counts, color="#2196F3", alpha=0.8)
        ax.set_xlabel("Year")
        ax.set_ylabel("Number of Publications")
        ax.set_title("SBMA Research Publications Over Time")
        ax.grid(axis="y", alpha=0.3)

        # Add cumulative line
        cumulative = []
        total = 0
        for c in counts:
            total += c
            cumulative.append(total)
        ax2 = ax.twinx()
        ax2.plot(years, cumulative, color="#FF5722", linewidth=2, label="Cumulative")
        ax2.set_ylabel("Cumulative Publications")
        ax2.legend(loc="upper left")

        plt.tight_layout()
        fig.savefig(self.output_dir / "publication_timeline.png", dpi=150)
        plt.close(fig)

        # Plotly interactive version
        fig_plotly = go.Figure()
        fig_plotly.add_trace(go.Bar(x=years, y=counts, name="Publications"))
        fig_plotly.add_trace(go.Scatter(x=years, y=cumulative, name="Cumulative", yaxis="y2"))
        fig_plotly.update_layout(
            title="SBMA Research Publications Over Time",
            yaxis=dict(title="Publications per Year"),
            yaxis2=dict(title="Cumulative", overlaying="y", side="right"),
        )
        fig_plotly.write_html(self.output_dir / "publication_timeline.html")

        logger.info("Publication timeline generated")

    def journal_distribution(self):
        """Where SBMA research is published."""
        journals = self.db.get_top_journals(25)
        if not journals:
            return

        names, counts = zip(*journals)

        fig, ax = plt.subplots(figsize=(10, 10))
        ax.barh(range(len(names)), counts, color="#4CAF50", alpha=0.8)
        ax.set_yticks(range(len(names)))
        ax.set_yticklabels(names, fontsize=8)
        ax.set_xlabel("Number of Publications")
        ax.set_title("Top 25 Journals Publishing SBMA Research")
        ax.invert_yaxis()
        plt.tight_layout()
        fig.savefig(self.output_dir / "journal_distribution.png", dpi=150)
        plt.close(fig)

        logger.info("Journal distribution generated")

    def author_network(self):
        """Co-authorship network."""
        session = self.db.get_session()
        try:
            from database.models import Article
            articles = session.query(Article.authors).all()
        finally:
            session.close()

        G = nx.Graph()
        co_author_counts = Counter()

        for (authors_json,) in articles:
            if not authors_json:
                continue
            names = []
            for a in authors_json:
                name = a.get("name", "") if isinstance(a, dict) else str(a)
                if name:
                    names.append(name)

            # Add edges between co-authors
            for i in range(len(names)):
                for j in range(i + 1, len(names)):
                    pair = tuple(sorted([names[i], names[j]]))
                    co_author_counts[pair] += 1

        # Add only edges with multiple co-authorships for readability
        for (a1, a2), weight in co_author_counts.items():
            if weight >= 2:
                G.add_edge(a1, a2, weight=weight)

        if len(G.nodes) == 0:
            logger.warning("No co-authorship data for network")
            return

        # Keep only the largest connected component for cleaner viz
        if nx.number_connected_components(G) > 1:
            largest_cc = max(nx.connected_components(G), key=len)
            G = G.subgraph(largest_cc).copy()

        # Limit to top nodes by degree for readability
        if len(G.nodes) > 100:
            top_nodes = sorted(G.degree(), key=lambda x: x[1], reverse=True)[:100]
            G = G.subgraph([n for n, _ in top_nodes]).copy()

        fig, ax = plt.subplots(figsize=(16, 16))
        pos = nx.spring_layout(G, k=2, iterations=50, seed=42)
        degrees = dict(G.degree())
        node_sizes = [degrees[n] * 20 + 50 for n in G.nodes]
        nx.draw_networkx(
            G, pos, ax=ax,
            node_size=node_sizes,
            node_color=[degrees[n] for n in G.nodes],
            cmap=plt.cm.YlOrRd,
            font_size=6,
            edge_color="gray",
            alpha=0.7,
            width=0.5,
        )
        ax.set_title("SBMA Research Co-authorship Network")
        plt.tight_layout()
        fig.savefig(self.output_dir / "author_network.png", dpi=150)
        plt.close(fig)

        # Save network data
        nx.write_gexf(G, self.output_dir / "author_network.gexf")
        logger.info(f"Author network: {len(G.nodes)} nodes, {len(G.edges)} edges")

    def citation_analysis(self):
        """Most cited papers and citation statistics."""
        session = self.db.get_session()
        try:
            from database.models import Article
            articles = (
                session.query(Article.pmid, Article.title, Article.citation_count, Article.publication_year)
                .filter(Article.citation_count != None, Article.citation_count > 0)
                .order_by(Article.citation_count.desc())
                .limit(50)
                .all()
            )
        finally:
            session.close()

        if not articles:
            logger.warning("No citation data available")
            return

        # Top cited papers
        data = []
        for pmid, title, citations, year in articles:
            data.append({
                "pmid": pmid,
                "title": (title or "")[:80],
                "citations": citations,
                "year": year,
            })

        df = pd.DataFrame(data)

        fig, ax = plt.subplots(figsize=(12, 10))
        bars = ax.barh(range(min(30, len(df))), df["citations"][:30], color="#9C27B0", alpha=0.8)
        ax.set_yticks(range(min(30, len(df))))
        ax.set_yticklabels(
            [f"[{r['pmid']}] {r['title']}" for _, r in df.head(30).iterrows()],
            fontsize=6,
        )
        ax.set_xlabel("Citation Count")
        ax.set_title("Most Cited SBMA Research Papers (Top 30)")
        ax.invert_yaxis()
        plt.tight_layout()
        fig.savefig(self.output_dir / "top_cited_papers.png", dpi=150)
        plt.close(fig)

        # Save as CSV
        df.to_csv(self.output_dir / "top_cited_papers.csv", index=False)
        logger.info("Citation analysis generated")

    def topic_evolution(self):
        """How research focus has shifted over decades using MeSH terms and keywords."""
        session = self.db.get_session()
        try:
            from database.models import Article
            articles = session.query(
                Article.publication_year, Article.mesh_terms, Article.keywords, Article.article_type
            ).filter(Article.publication_year != None).all()
        finally:
            session.close()

        if not articles:
            return

        # Group keywords by decade
        decade_topics: dict[str, Counter] = defaultdict(Counter)
        for year, mesh, keywords, _ in articles:
            decade = f"{(year // 10) * 10}s"
            all_terms = (mesh or []) + (keywords or [])
            for term in all_terms:
                if isinstance(term, str) and len(term) > 2:
                    decade_topics[decade][term.lower()] += 1

        # Get top topics per decade
        topic_data = {}
        for decade in sorted(decade_topics.keys()):
            top = decade_topics[decade].most_common(15)
            topic_data[decade] = {term: count for term, count in top}

        # Save as JSON
        (self.output_dir / "topic_evolution.json").write_text(
            json.dumps(topic_data, indent=2)
        )

        logger.info("Topic evolution analysis generated")

    def article_type_trends(self):
        """Methodology trends over time."""
        session = self.db.get_session()
        try:
            from database.models import Article
            articles = session.query(
                Article.publication_year, Article.article_type
            ).filter(Article.publication_year != None).all()
        finally:
            session.close()

        if not articles:
            return

        year_types: dict[int, Counter] = defaultdict(Counter)
        for year, atype in articles:
            year_types[year][atype or "unknown"] += 1

        years = sorted(year_types.keys())
        all_types = set()
        for counts in year_types.values():
            all_types.update(counts.keys())

        fig, ax = plt.subplots(figsize=(14, 6))
        bottom = [0] * len(years)
        colors = plt.cm.Set3.colors

        for i, atype in enumerate(sorted(all_types)):
            values = [year_types[y].get(atype, 0) for y in years]
            ax.bar(years, values, bottom=bottom, label=atype,
                   color=colors[i % len(colors)], alpha=0.8)
            bottom = [b + v for b, v in zip(bottom, values)]

        ax.set_xlabel("Year")
        ax.set_ylabel("Number of Publications")
        ax.set_title("SBMA Research Article Types Over Time")
        ax.legend(fontsize=7, loc="upper left")
        plt.tight_layout()
        fig.savefig(self.output_dir / "article_type_trends.png", dpi=150)
        plt.close(fig)

        logger.info("Article type trends generated")

    def author_stats(self):
        """Compute and store author analytics including h-index."""
        session = self.db.get_session()
        try:
            from database.models import Article
            articles = session.query(Article).all()
        finally:
            session.close()

        author_data: dict[str, dict] = {}

        for article in articles:
            authors = article.authors or []
            citation_count = article.citation_count or 0

            for idx, author in enumerate(authors):
                name = author.get("name", "") if isinstance(author, dict) else str(author)
                if not name:
                    continue

                if name not in author_data:
                    author_data[name] = {
                        "author_name": name,
                        "total_papers": 0,
                        "first_author_papers": 0,
                        "last_author_papers": 0,
                        "affiliations": set(),
                        "years": set(),
                        "citation_counts": [],
                    }

                ad = author_data[name]
                ad["total_papers"] += 1
                ad["citation_counts"].append(citation_count)
                if idx == 0:
                    ad["first_author_papers"] += 1
                if idx == len(authors) - 1 and len(authors) > 1:
                    ad["last_author_papers"] += 1

                affiliation = author.get("affiliation", "") if isinstance(author, dict) else ""
                if affiliation:
                    ad["affiliations"].add(affiliation)
                if article.publication_year:
                    ad["years"].add(article.publication_year)

        # Store in database
        for name, data in author_data.items():
            years = sorted(data["years"])
            active_years = f"{years[0]}-{years[-1]}" if years else ""

            # Compute h-index: h papers with >= h citations each
            citations_sorted = sorted(data["citation_counts"], reverse=True)
            h_index = 0
            for i, c in enumerate(citations_sorted):
                if c >= i + 1:
                    h_index = i + 1
                else:
                    break

            self.db.upsert_author_analytics({
                "author_name": name,
                "total_papers": data["total_papers"],
                "first_author_papers": data["first_author_papers"],
                "last_author_papers": data["last_author_papers"],
                "h_index_in_field": h_index,
                "affiliations": list(data["affiliations"])[:10],
                "active_years": active_years,
            })

        logger.info(f"Author stats computed for {len(author_data)} authors")
