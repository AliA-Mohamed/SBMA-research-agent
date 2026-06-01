"""Weekly PubMed check for new SBMA articles."""

import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from Bio import Entrez

sys.path.insert(0, str(Path(__file__).parent.parent))
import config
from logger import setup_logger
from database.db_manager import DBManager
from ingestion.pubmed_fetcher import PubMedFetcher
from ingestion.crossref_fetcher import CrossRefFetcher
from ingestion.semantic_scholar import SemanticScholarFetcher
from ingestion.fulltext_fetcher import FullTextFetcher
from analysis.llm_relevance import classify_article_relevance

logger = setup_logger("new_article_checker")

Entrez.email = config.NCBI_EMAIL
if config.NCBI_API_KEY:
    Entrez.api_key = config.NCBI_API_KEY


class NewArticleChecker:
    """Checks for new SBMA articles published in the last week."""

    def __init__(self):
        self.db = DBManager()
        self.pubmed = PubMedFetcher()
        self.crossref = CrossRefFetcher()
        self.semantic_scholar = SemanticScholarFetcher()
        self.fulltext = FullTextFetcher()

    def check_new_articles(
        self,
        days_back: int = 7,
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
    ) -> list[dict]:
        """Search for articles published in a date range.

        If start/end are provided they take precedence over days_back.
        Returns list of new article dicts (not already in DB).
        """
        if start and end:
            start_date, end_date = start, end
        else:
            end_date = datetime.now()
            start_date = end_date - timedelta(days=days_back)

        date_range = f"{start_date.strftime('%Y/%m/%d')}:{end_date.strftime('%Y/%m/%d')}[dp]"
        query = f"({config.PUBMED_SEARCH_QUERY}) AND ({date_range})"

        logger.info(f"Checking for new articles from {start_date.date()} to {end_date.date()}")

        # Search PubMed
        pmids = self.pubmed.search_all_pmids(query)
        logger.info(f"Found {len(pmids)} articles in date range")

        # Filter out already-known articles
        existing_pmids = set(self.db.get_all_pmids())
        new_pmids = [p for p in pmids if p not in existing_pmids]
        logger.info(f"New articles not in database: {len(new_pmids)}")

        if not new_pmids:
            return []

        # Fetch full details (keyword pre-filter applied during parsing)
        articles = self.pubmed.fetch_article_details(new_pmids)
        logger.info(
            f"After keyword pre-filter: {len(articles)}/{len(new_pmids)} articles kept"
        )

        if not articles:
            logger.info("No new SBMA-relevant articles after keyword filtering")
            return []

        # LLM-based relevance filter (more accurate than keyword-only)
        llm_kept = []
        for art in articles:
            result = classify_article_relevance(art.get("title", ""), art.get("abstract", ""))
            if result["relevant"]:
                llm_kept.append(art)
            else:
                logger.info(
                    f"LLM rejected PMID {art.get('pmid')}: {result['reason']}"
                )
            # Rate limit for Gemini free tier
            if config.LLM_BACKEND == "gemini":
                time.sleep(4)

        logger.info(
            f"After LLM relevance filter: {len(llm_kept)}/{len(articles)} articles kept"
        )
        articles = llm_kept

        if not articles:
            logger.info("No new SBMA-relevant articles after LLM filtering")
            return []

        # Enrich
        articles = self.crossref.enrich_articles(articles)
        articles = self.semantic_scholar.enrich_articles(articles)
        articles = self.fulltext.enrich_articles(articles)

        # Store in database
        self.db.upsert_articles_bulk(articles)
        logger.info(f"Stored {len(articles)} new articles in database")

        return articles
