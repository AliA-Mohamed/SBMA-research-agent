# SBMA Research Agent

An AI-powered research platform that systematically ingests, analyzes, and synthesizes **all published literature on Spinal and Bulbar Muscular Atrophy (SBMA / Kennedy's Disease)**. It builds a living knowledge base from primary sources, generates an AI-written textbook, tracks the research field's evolution, and monitors for new publications weekly.

## What It Does

- **993 curated research articles** (1968-2026), 86% with full text
- **10,643 AI-extracted knowledge entries** across 13 categories (mechanisms, treatments, biomarkers, genetics, clinical features, etc.)
- **12-chapter AI-generated textbook** synthesized from primary literature using Claude
- **Field analytics**: publication trends, author networks, citation analysis, topic evolution
- **Research gap analysis**: AI-identified under-researched areas and open questions
- **Weekly monitoring**: automatic detection of new SBMA publications with novelty scoring

## Quick Start

```bash
# Clone and setup
git clone https://github.com/AliA-Mohamed/SBMA-research-agent.git
cd SBMA-research-agent
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# Configure API keys
cp .env.example .env
# Edit .env with your keys (see API Keys section below)
```

## Pipeline

The system runs as a multi-stage pipeline. Each stage can be run independently.

### 1. Article Ingestion

Fetches all SBMA articles from PubMed, enriches with citation data from Semantic Scholar and CrossRef, and retrieves full text from PMC/Unpaywall.

```bash
python scripts/run_initial_ingestion.py          # Full ingestion
python scripts/run_initial_ingestion.py --test    # Test with 20 articles
python scripts/run_re_enrich.py                   # Re-enrich with citations + fulltext
```

### 2. Relevance Filtering

Removes false positives (e.g., "SBMA" = sulfobetaine methacrylate in polymer science).

```bash
python scripts/run_llm_relevance_filter.py --dry-run   # Preview
python scripts/run_llm_relevance_filter.py --remove     # Remove irrelevant articles
python scripts/run_cleanup_non_sbma.py --dry-run        # Audit existing DB
```

### 3. Knowledge Extraction & Textbook Building

Processes articles chronologically, extracts structured knowledge, and builds a comprehensive textbook.

```bash
python scripts/run_textbook_builder.py            # Extract + build (resumable)
python scripts/run_textbook_builder.py --limit 50 # Process 50 articles then stop
```

To re-synthesize chapters after extraction (e.g., switching to Claude for higher quality):

```bash
python scripts/resynthesize_textbook.py
```

Output: `outputs/textbook/SBMA_Textbook.md` and individual chapter files.

### 4. Analytics & Gap Analysis

```bash
python scripts/run_analytics.py                   # Full analytics + gap analysis
python scripts/run_analytics.py --skip-gaps       # Skip gap analysis (saves API costs)
```

Output: `outputs/analytics/` — PNG charts, interactive HTML plots, CSV data, gap analysis.

### 5. Weekly Monitor

```bash
python scripts/run_weekly_monitor.py              # Check last 7 days
python scripts/run_weekly_monitor.py --days 14    # Check last 14 days
python scripts/run_weekly_monitor.py --skip-scoring  # Skip novelty scoring
```

Output: `outputs/weekly_reports/weekly_digest_YYYY-MM-DD.md`

### 6. Export to Supabase

Mirrors the SQLite database to Supabase for the public website.

```bash
python scripts/export_to_supabase.py
```

### 7. Dashboard

Local Flask dashboard with interactive visualizations.

```bash
python scripts/run_dashboard.py                   # http://localhost:5000
```

## API Keys

**Required:**
| Key | Purpose | Where to get it |
|-----|---------|-----------------|
| `NCBI_API_KEY` | PubMed article retrieval | https://www.ncbi.nlm.nih.gov/account/ |
| `NCBI_EMAIL` | Required by NCBI | Your email |
| `GEMINI_API_KEY` | Knowledge extraction (Gemini Flash Lite) | https://ai.google.dev/ |
| `ANTHROPIC_API_KEY` | Textbook synthesis + gap analysis (Claude) | https://console.anthropic.com/ |
| `UNPAYWALL_EMAIL` | Full-text retrieval | Your email |

**Optional:**
| Key | Purpose |
|-----|---------|
| `SEMANTIC_SCHOLAR_API_KEY` | Higher rate limits for citation data |
| `SUPABASE_URL` + `SUPABASE_SERVICE_KEY` | Export to Supabase for public website |

## Project Structure

```
sbma-research-agent/
├── config.py                        # Configuration, API keys, SBMA filters
├── logger.py                        # Centralized logging
├── requirements.txt
├── .env.example
├── supabase_schema.sql              # Supabase table definitions
├── false_positive_pmids.txt         # Known non-SBMA article PMIDs
│
├── scripts/                         # Entry-point scripts
│   ├── run_initial_ingestion.py     # PubMed ingestion pipeline
│   ├── run_re_enrich.py             # Citation + fulltext enrichment
│   ├── run_llm_relevance_filter.py  # AI-powered relevance filtering
│   ├── run_cleanup_non_sbma.py      # Audit and remove non-SBMA articles
│   ├── run_textbook_builder.py      # Knowledge extraction + textbook
│   ├── resynthesize_textbook.py     # Re-synthesize chapters with Claude
│   ├── extract_remaining.py         # Extract unprocessed articles only
│   ├── purge_contamination.py       # Remove contaminated entries
│   ├── run_analytics.py             # Field analytics + gap analysis
│   ├── run_weekly_monitor.py        # Weekly literature monitor
│   ├── run_dashboard.py             # Flask web dashboard
│   └── export_to_supabase.py        # Supabase data export
│
├── ingestion/                       # Data collection modules
│   ├── pubmed_fetcher.py            # PubMed Entrez API
│   ├── crossref_fetcher.py          # CrossRef citation data
│   ├── semantic_scholar.py          # Semantic Scholar API
│   └── fulltext_fetcher.py          # PMC + Unpaywall full text
│
├── database/                        # Data layer
│   ├── models.py                    # SQLAlchemy ORM models
│   └── db_manager.py                # CRUD operations
│
├── analysis/                        # AI analysis modules
│   ├── knowledge_extractor.py       # Structured knowledge extraction
│   ├── textbook_builder.py          # Chronological textbook builder
│   ├── ollama_client.py             # Unified LLM client (Gemini/Claude/Ollama)
│   ├── llm_relevance.py             # LLM-based relevance classification
│   ├── field_analytics.py           # Visualizations and author stats
│   └── gap_analyzer.py              # Research gap identification
│
├── weekly_monitor/                  # Weekly monitoring pipeline
│   ├── new_article_checker.py       # New article detection + filtering
│   ├── novelty_scorer.py            # Novelty scoring vs knowledge base
│   └── report_generator.py          # Weekly digest generation
│
├── templates/
│   └── dashboard.html               # Flask dashboard template
│
├── outputs/                         # Generated outputs (gitignored)
│   ├── textbook/                    # 12-chapter SBMA textbook
│   ├── analytics/                   # Charts, CSV, gap analysis
│   └── weekly_reports/              # Weekly digest markdowns
│
└── database/
    └── sbma_research.db             # SQLite database (gitignored)
```

## LLM Backends

The system uses two LLM tiers:

- **Extraction** (bulk processing): Gemini 2.5 Flash Lite — fast, cost-efficient, handles 1000+ articles
- **Synthesis** (quality-critical): Claude Opus — textbook chapter synthesis, gap analysis

Configured via `LLM_BACKEND` in `.env`. Supports `gemini`, `claude`, and `ollama` (local Llama 3.1).

## Database Schema

SQLite with 5 core tables:

| Table | Records | Description |
|-------|---------|-------------|
| `articles` | 993 | Article metadata, abstracts, citations, fulltext paths |
| `extracted_knowledge` | 10,643 | AI-extracted findings with type, confidence, novelty |
| `textbook_sections` | 12 | Synthesized textbook chapters with source PMIDs |
| `authors_analytics` | 3,952 | Per-author stats including SBMA-field h-index |
| `weekly_reports` | 1+ | Weekly monitoring digests |

## Knowledge Types

The AI categorizes extracted knowledge into 13 types:

| Type | Count | Description |
|------|-------|-------------|
| mechanism | 2,518 | Pathophysiological mechanisms |
| finding | 2,300 | General research findings |
| clinical_feature | 1,818 | Clinical symptoms and signs |
| genetic | 1,250 | Genetic findings |
| treatment | 1,066 | Therapeutic approaches |
| biomarker | 374 | Diagnostic/prognostic markers |
| diagnostic | 294 | Diagnostic methods |
| animal_model | 273 | Animal model findings |
| methodology | 216 | Research methodology |
| epidemiological | 206 | Epidemiology data |
| review_synthesis | 141 | Review/meta-analysis insights |
| case_report | 94 | Case report details |
| cellular_model | 93 | In vitro model findings |

## Textbook Chapters

1. Historical Discovery & Overview
2. Genetics & Molecular Biology
3. Pathophysiology & Disease Mechanisms
4. Clinical Features & Natural History
5. Diagnosis
6. Epidemiology
7. Animal & Cellular Models
8. Therapeutic Approaches
9. Biomarkers & Outcome Measures
10. Living with SBMA — Patient Perspectives & Quality of Life
11. Open Questions & Future Directions
12. Contradictions & Debates in the Field

## Cost Considerations

- **PubMed / CrossRef / Unpaywall**: Free APIs
- **Semantic Scholar**: Free tier, optional API key for higher limits
- **Gemini Flash Lite**: Free tier covers extraction of 1000+ articles
- **Claude**: Pay-per-use — used only for synthesis (~12 API calls for textbook, 1 for gap analysis)
- Use `--skip-scoring` and `--skip-gaps` flags to reduce API costs

## License

This project is for research purposes. Article metadata is sourced from public APIs (PubMed, CrossRef, Semantic Scholar). Full-text content is retrieved only from open-access sources.
