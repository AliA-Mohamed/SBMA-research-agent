#!/usr/bin/env python3
"""SBMA Research Dashboard — Interactive web UI for all agent outputs."""

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

from flask import Flask, jsonify, render_template, request

import plotly
import plotly.graph_objects as go
import networkx as nx
from sqlalchemy import or_

# Ensure project root on path for config / database imports
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config
from database.db_manager import DBManager
from database.models import Article

PROJECT_ROOT = Path(__file__).resolve().parent.parent
app = Flask(__name__, template_folder=str(PROJECT_ROOT / "templates"))
db = DBManager()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def plotly_json(fig):
    """Serialize a Plotly figure to JSON-safe dict."""
    return json.loads(json.dumps(fig, cls=plotly.utils.PlotlyJSONEncoder))


def article_to_dict(a):
    return {
        "pmid": a.pmid,
        "title": a.title,
        "authors": a.authors or [],
        "journal": a.journal,
        "year": a.publication_year,
        "citation_count": a.citation_count or 0,
        "article_type": a.article_type,
        "doi": a.doi,
    }


def knowledge_to_dict(k):
    return {
        "id": k.id,
        "pmid": k.pmid,
        "knowledge_type": k.knowledge_type,
        "summary": k.summary,
        "details": k.details,
        "confidence": k.confidence,
    }


def report_to_dict(r):
    return {
        "id": r.id,
        "report_date": str(r.report_date) if r.report_date else None,
        "new_articles_found": r.new_articles_found,
        "summary": r.summary,
        "novelty_analysis": r.novelty_analysis,
    }


def author_analytics_to_dict(a):
    return {
        "author_name": a.author_name,
        "total_papers": a.total_papers,
        "first_author_papers": a.first_author_papers,
        "last_author_papers": a.last_author_papers,
        "h_index_in_field": a.h_index_in_field,
        "affiliations": a.affiliations or [],
        "active_years": a.active_years,
    }


# ---------------------------------------------------------------------------
# Page route
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    return render_template("dashboard.html")


# ---------------------------------------------------------------------------
# API routes
# ---------------------------------------------------------------------------

@app.route("/api/overview")
def api_overview():
    article_count = db.get_article_count()
    knowledge_count = db.get_knowledge_count()
    fulltext_count = db.get_fulltext_count()
    latest_report = db.get_latest_report()
    by_year = db.get_articles_by_year()

    return jsonify({
        "article_count": article_count,
        "knowledge_count": knowledge_count,
        "fulltext_count": fulltext_count,
        "latest_report": report_to_dict(latest_report) if latest_report else None,
        "articles_by_year": by_year,
    })


@app.route("/api/publications-by-year")
def api_publications_by_year():
    by_year = db.get_articles_by_year()
    years = sorted(by_year.keys())
    counts = [by_year[y] for y in years]

    cumulative = []
    total = 0
    for c in counts:
        total += c
        cumulative.append(total)

    fig = {
        "data": [
            {
                "x": years,
                "y": counts,
                "type": "bar",
                "name": "Articles per Year",
                "marker": {"color": "#4e79a7"},
            },
            {
                "x": years,
                "y": cumulative,
                "type": "scatter",
                "mode": "lines+markers",
                "name": "Cumulative",
                "yaxis": "y2",
                "line": {"color": "#e15759", "width": 2},
            },
        ],
        "layout": {
            "title": "SBMA Publications by Year",
            "xaxis": {"title": "Year"},
            "yaxis": {"title": "Articles"},
            "yaxis2": {
                "title": "Cumulative",
                "overlaying": "y",
                "side": "right",
            },
            "legend": {"x": 0.01, "y": 0.99},
            "margin": {"t": 40},
        },
    }
    return jsonify({"chart": plotly_json(fig)})


@app.route("/api/top-authors")
def api_top_authors():
    top = db.get_top_authors(30)
    analytics = db.get_all_author_analytics()
    analytics_map = {a.author_name: author_analytics_to_dict(a) for a in analytics}

    rows = []
    for name, count in top:
        row = {"name": name, "pub_count": count}
        if name in analytics_map:
            row.update(analytics_map[name])
        rows.append(row)

    return jsonify({"authors": rows})


@app.route("/api/author-network")
def api_author_network():
    session = db.get_session()
    try:
        articles = session.query(
            __import__("database.models", fromlist=["Article"]).Article.authors
        ).all()
    finally:
        session.close()

    G = nx.Graph()
    for (authors_json,) in articles:
        if not authors_json:
            continue
        names = []
        for a in authors_json:
            name = a.get("name", "") if isinstance(a, dict) else str(a)
            if name:
                names.append(name)
        for i, n1 in enumerate(names):
            G.add_node(n1)
            for n2 in names[i + 1:]:
                if G.has_edge(n1, n2):
                    G[n1][n2]["weight"] += 1
                else:
                    G.add_edge(n1, n2, weight=1)

    # Keep only nodes with >= 2 papers for readability
    nodes_to_keep = [n for n in G.nodes() if G.degree(n) >= 2]
    G = G.subgraph(nodes_to_keep).copy()

    if len(G.nodes()) == 0:
        return jsonify({"chart": None, "message": "Not enough co-authorship data to build a network."})

    pos = nx.spring_layout(G, seed=42, k=0.5)

    edge_x, edge_y = [], []
    for u, v in G.edges():
        x0, y0 = pos[u]
        x1, y1 = pos[v]
        edge_x += [x0, x1, None]
        edge_y += [y0, y1, None]

    node_x = [pos[n][0] for n in G.nodes()]
    node_y = [pos[n][1] for n in G.nodes()]
    node_text = list(G.nodes())
    node_size = [min(5 + G.degree(n) * 2, 40) for n in G.nodes()]

    fig = {
        "data": [
            {
                "x": edge_x, "y": edge_y,
                "mode": "lines",
                "line": {"width": 0.5, "color": "#888"},
                "hoverinfo": "none",
                "type": "scatter",
            },
            {
                "x": node_x, "y": node_y,
                "mode": "markers+text",
                "text": node_text,
                "textposition": "top center",
                "textfont": {"size": 8},
                "marker": {"size": node_size, "color": "#4e79a7", "line": {"width": 1, "color": "#fff"}},
                "hovertext": [f"{n} ({G.degree(n)} connections)" for n in G.nodes()],
                "hoverinfo": "text",
                "type": "scatter",
            },
        ],
        "layout": {
            "title": "Author Co-authorship Network",
            "showlegend": False,
            "xaxis": {"visible": False},
            "yaxis": {"visible": False},
            "margin": {"t": 40, "l": 10, "r": 10, "b": 10},
        },
    }
    return jsonify({"chart": plotly_json(fig)})


@app.route("/api/citations")
def api_citations():
    articles = db.get_top_cited_articles(50)
    rows = [article_to_dict(a) for a in articles]

    if rows:
        display = rows[:25]
        fig = {
            "data": [{
                "y": [r["title"][:50] + "..." if len(r["title"]) > 50 else r["title"] for r in display],
                "x": [r["citation_count"] for r in display],
                "type": "bar",
                "orientation": "h",
                "marker": {"color": "#59a14f"},
            }],
            "layout": {
                "title": "Top Cited SBMA Articles",
                "xaxis": {"title": "Citations"},
                "margin": {"l": 300, "t": 40},
                "height": max(400, len(display) * 25),
            },
        }
    else:
        fig = None

    return jsonify({"chart": plotly_json(fig) if fig else None, "articles": rows})


@app.route("/api/journals")
def api_journals():
    journals = db.get_top_journals(25)
    names = [j for j, _ in journals]
    counts = [c for _, c in journals]

    fig = {
        "data": [{
            "y": names,
            "x": counts,
            "type": "bar",
            "orientation": "h",
            "marker": {"color": "#f28e2b"},
        }],
        "layout": {
            "title": "Top Journals for SBMA Research",
            "xaxis": {"title": "Articles"},
            "margin": {"l": 300, "t": 40},
            "height": max(400, len(names) * 25),
        },
    }
    return jsonify({"chart": plotly_json(fig)})


@app.route("/api/topic-evolution")
def api_topic_evolution():
    raw = db.get_topic_evolution_data()
    if not raw:
        return jsonify({"chart": None, "message": "No MeSH term data available."})

    # Aggregate: find top 20 terms overall
    term_totals = defaultdict(int)
    for decade_terms in raw.values():
        for term, count in decade_terms.items():
            term_totals[term] += count
    top_terms = [t for t, _ in sorted(term_totals.items(), key=lambda x: x[1], reverse=True)[:20]]

    decades = sorted(raw.keys())
    z = []
    for term in top_terms:
        row = [raw.get(d, {}).get(term, 0) for d in decades]
        z.append(row)

    fig = {
        "data": [{
            "z": z,
            "x": decades,
            "y": top_terms,
            "type": "heatmap",
            "colorscale": "YlOrRd",
        }],
        "layout": {
            "title": "Topic Evolution (MeSH Terms by Decade)",
            "margin": {"l": 200, "t": 40},
            "height": max(400, len(top_terms) * 25),
        },
    }
    return jsonify({"chart": plotly_json(fig)})


@app.route("/api/article-types")
def api_article_types():
    raw = db.get_article_types_by_year()
    if not raw:
        return jsonify({"chart": None, "message": "No article type data available."})

    years = sorted(raw.keys())
    all_types = set()
    for year_data in raw.values():
        all_types.update(year_data.keys())
    all_types = sorted(all_types)

    colors = ["#4e79a7", "#f28e2b", "#e15759", "#76b7b2", "#59a14f",
              "#edc948", "#b07aa1", "#ff9da7", "#9c755f", "#bab0ac"]

    traces = []
    for i, atype in enumerate(all_types):
        traces.append({
            "x": years,
            "y": [raw[y].get(atype, 0) for y in years],
            "type": "bar",
            "name": atype,
            "marker": {"color": colors[i % len(colors)]},
        })

    fig = {
        "data": traces,
        "layout": {
            "title": "Article Types by Year",
            "barmode": "stack",
            "xaxis": {"title": "Year"},
            "yaxis": {"title": "Articles"},
            "margin": {"t": 40},
        },
    }
    return jsonify({"chart": plotly_json(fig)})


@app.route("/api/knowledge")
def api_knowledge():
    type_counts = db.get_knowledge_type_counts()
    ktype = request.args.get("type")
    limit = int(request.args.get("limit", 50))
    offset = int(request.args.get("offset", 0))
    items = db.get_knowledge_browse(knowledge_type=ktype, limit=limit, offset=offset)

    return jsonify({
        "type_counts": type_counts,
        "items": [knowledge_to_dict(k) for k in items],
    })


@app.route("/api/textbook")
def api_textbook():
    sections = db.get_textbook_sections()
    chapters = {}
    for s in sections:
        key = s.chapter or "Uncategorized"
        if key not in chapters:
            chapters[key] = []
        chapters[key].append({
            "id": s.id,
            "section_title": s.section_title,
            "content": s.content,
            "version": s.version,
            "contributing_pmids": s.contributing_pmids or [],
        })
    return jsonify({"chapters": chapters})


@app.route("/api/reports")
def api_reports():
    reports = db.get_all_weekly_reports()
    return jsonify({"reports": [report_to_dict(r) for r in reports]})


@app.route("/api/reports/<int:report_id>")
def api_report_detail(report_id):
    report = db.get_weekly_report_by_id(report_id)
    if not report:
        return jsonify({"error": "Report not found"}), 404
    return jsonify(report_to_dict(report))


@app.route("/api/articles")
def api_articles():
    search = request.args.get("search", "").strip()
    sort_by = request.args.get("sort", "year")
    order = request.args.get("order", "desc")
    page = max(1, int(request.args.get("page", 1)))
    per_page = min(100, max(10, int(request.args.get("per_page", 25))))

    session = db.get_session()
    try:
        q = session.query(Article)

        if search:
            pattern = f"%{search}%"
            q = q.filter(
                or_(
                    Article.title.ilike(pattern),
                    Article.journal.ilike(pattern),
                    Article.pmid.ilike(pattern),
                    Article.article_type.ilike(pattern),
                )
            )

        sort_col = {
            "year": Article.publication_year,
            "title": Article.title,
            "journal": Article.journal,
            "citations": Article.citation_count,
            "type": Article.article_type,
        }.get(sort_by, Article.publication_year)

        if order == "asc":
            q = q.order_by(sort_col.asc())
        else:
            q = q.order_by(sort_col.desc())

        total = q.count()
        articles = q.offset((page - 1) * per_page).limit(per_page).all()

        rows = []
        for a in articles:
            d = article_to_dict(a)
            d["abstract"] = (a.abstract or "")[:500]
            rows.append(d)

        return jsonify({
            "articles": rows,
            "total": total,
            "page": page,
            "per_page": per_page,
            "total_pages": max(1, (total + per_page - 1) // per_page),
        })
    finally:
        session.close()


@app.route("/api/gaps")
def api_gaps():
    gaps_file = config.ANALYTICS_DIR / "research_gaps.md"
    if gaps_file.exists():
        return jsonify({"content": gaps_file.read_text(encoding="utf-8")})
    # Try JSON variant
    gaps_json = config.ANALYTICS_DIR / "research_gaps.json"
    if gaps_json.exists():
        return jsonify({"content": gaps_json.read_text(encoding="utf-8"), "format": "json"})
    return jsonify({"content": None, "message": "No research gaps analysis found. Run `python run_analytics.py` first."})


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="SBMA Research Dashboard")
    parser.add_argument("--port", type=int, default=5000)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()

    print(f"Starting SBMA Research Dashboard at http://{args.host}:{args.port}")
    app.run(host=args.host, port=args.port, debug=args.debug)
