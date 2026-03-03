"""Weekly PubMed check for new SBMA articles."""

import sys
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

    def check_new_articles(self, days_back: int = 7) -> list[dict]:
        """Search for articles published in the last N days.

        Returns list of new article dicts (not already in DB).
        """
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

        # Fetch full details (relevance filter is applied automatically during parsing)
        articles = self.pubmed.fetch_article_details(new_pmids)
        logger.info(
            f"After SBMA relevance filtering: {len(articles)}/{len(new_pmids)} articles kept"
        )

        if not articles:
            logger.info("No new SBMA-relevant articles after filtering")
            return []

        # Enrich
        articles = self.crossref.enrich_articles(articles)
        articles = self.semantic_scholar.enrich_articles(articles)
        articles = self.fulltext.enrich_articles(articles)

        # Store in database
        self.db.upsert_articles_bulk(articles)
        logger.info(f"Stored {len(articles)} new articles in database")

        return articles
