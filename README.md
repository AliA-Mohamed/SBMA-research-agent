# SBMA Research Agent

An AI-powered research agent that acts as a dedicated **SBMA (Spinal and Bulbar Muscular Atrophy / Kennedy's Disease) researcher**. It ingests all published SBMA literature, builds a living knowledge base, generates a comprehensive textbook, and monitors new publications weekly.

## Setup

### 1. Install dependencies

```bash
cd sbma-research-agent
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 2. Configure API keys

```bash
cp .env.example .env
# Edit .env with your API keys
```

Required API keys:
- **NCBI_API_KEY**: Register at https://www.ncbi.nlm.nih.gov/account/ — needed for PubMed access
- **NCBI_EMAIL**: Your email (required by NCBI)
- **GEMINI_API_KEY**: Your Google Gemini API key — needed for knowledge extraction and textbook building
- **UNPAYWALL_EMAIL**: Your email — used for open-access full text retrieval

Optional:
- **SEMANTIC_SCHOLAR_API_KEY**: Increases rate limits for citation data

## Usage

### Initial Ingestion (run once)

Fetches all SBMA articles from PubMed, enriches with citation data, and stores in the database.

```bash
# Test with 20 articles first
python run_initial_ingestion.py --test

# Full ingestion (will take time — ~2000+ articles)
python run_initial_ingestion.py

# Skip enrichment for faster initial fetch
python run_initial_ingestion.py --skip-enrichment --skip-fulltext
```

### Build Textbook (run after ingestion)

Processes articles chronologically and builds a comprehensive SBMA textbook using Gemini.

```bash
python run_textbook_builder.py

# Start fresh (discard previous progress)
python run_textbook_builder.py --no-resume
```

Output: `outputs/textbook/SBMA_Textbook.md` and individual chapter files.

### Field Analytics (on-demand)

Generates visualizations and analytics about the SBMA research field.

```bash
python run_analytics.py

# Skip gap analysis to avoid Gemini API costs
python run_analytics.py --skip-gaps
```

Output: `outputs/analytics/` — PNG charts, HTML interactive plots, CSV data.

### Weekly Monitor (scheduled)

Checks for new SBMA publications and generates a digest report.

```bash
python run_weekly_monitor.py

# Look back 14 days instead of 7
python run_weekly_monitor.py --days 14

# Skip novelty scoring to save API costs
python run_weekly_monitor.py --skip-scoring
```

Output: `outputs/weekly_reports/weekly_digest_YYYY-MM-DD.md`

#### Cron Job Setup

To run automatically every Monday at 8 AM:

```bash
crontab -e
# Add this line:
0 8 * * 1 cd /path/to/sbma-research-agent && /path/to/venv/bin/python run_weekly_monitor.py
```

## Project Structure

```
sbma-research-agent/
├── config.py                  # Configuration and API keys
├── logger.py                  # Centralized logging
├── requirements.txt
├── .env.example
│
├── ingestion/
│   ├── pubmed_fetcher.py      # PubMed Entrez API
│   ├── crossref_fetcher.py    # CrossRef citation data
│   ├── semantic_scholar.py    # Semantic Scholar citations
│   └── fulltext_fetcher.py    # PMC + Unpaywall full text
│
├── database/
│   ├── models.py              # SQLAlchemy models
│   └── db_manager.py          # CRUD operations
│
├── analysis/
│   ├── knowledge_extractor.py # Gemini-powered extraction
│   ├── textbook_builder.py    # Chronological textbook builder
│   ├── gap_analyzer.py        # Research gap identification
│   └── field_analytics.py     # Visualizations and stats
│
├── weekly_monitor/
│   ├── new_article_checker.py # New article detection
│   ├── novelty_scorer.py      # Novelty scoring
│   └── report_generator.py    # Weekly digest generation
│
├── run_initial_ingestion.py   # One-time full ingestion
├── run_textbook_builder.py    # Build the textbook
├── run_analytics.py           # Generate analytics
└── run_weekly_monitor.py      # Weekly monitoring
```

## Database

SQLite database at `database/sbma_research.db` with tables:
- **articles**: All article metadata (PMID, DOI, authors, abstract, citations, etc.)
- **extracted_knowledge**: AI-extracted findings from each article
- **textbook_sections**: Generated textbook chapters
- **weekly_reports**: Weekly monitoring reports
- **authors_analytics**: Author publication statistics

## Cost Considerations

- **PubMed/CrossRef/Unpaywall**: Free APIs (respect rate limits)
- **Semantic Scholar**: Free tier, optional API key for higher limits
- **Google Gemini API**: Main cost driver
  - Gemini 2.0 Flash used for bulk article extraction (~2000 articles) — very cost-efficient
  - Gemini 2.5 Pro used only for chapter synthesis (~12 chapters)
  - Gemini offers a generous free tier; check Google AI pricing for current rates
  - Use `--skip-scoring` and `--skip-gaps` flags to reduce API calls
