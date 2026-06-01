"""Enrich article metadata via CrossRef API (citation counts, references)."""

import sys
import time
from pathlib import Path
from typing import Optional

import requests
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

sys.path.insert(0, str(Path(__file__).parent.parent))
import config
from logger import setup_logger

logger = setup_logger("crossref_fetcher")


class CrossRefFetcher:
    """Fetches citation and reference data from the CrossRef API."""

    BASE_URL = "https://api.crossref.org/works"

    def __init__(self):
        self.rate_delay = 1.0 / config.CROSSREF_RATE_LIMIT
        self._last_request_time = 0.0
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": f"SBMAResearchAgent/1.0 (mailto:{config.NCBI_EMAIL})",
        })

    def _rate_limit(self):
        elapsed = time.time() - self._last_request_time
        if elapsed < self.rate_delay:
            time.sleep(self.rate_delay - elapsed)
        self._last_request_time = time.time()

    @retry(
        stop=stop_after_attempt(config.RETRY_MAX_ATTEMPTS),
        wait=wait_exponential(min=config.RETRY_WAIT_MIN, max=config.RETRY_WAIT_MAX),
        retry=retry_if_exception_type((requests.RequestException, ConnectionError)),
    )
    def fetch_by_doi(self, doi: str) -> Optional[dict]:
        """Fetch CrossRef metadata for a given DOI.

        Returns dict with citation_count, references, etc.
        """
        if not doi:
            return None

        self._rate_limit()
        url = f"{self.BASE_URL}/{doi}"

        try:
            resp = self.session.get(url, timeout=30)
            if resp.status_code == 404:
                logger.debug(f"DOI not found in CrossRef: {doi}")
                return None
            resp.raise_for_status()
        except requests.RequestException as e:
            logger.warning(f"CrossRef request failed for {doi}: {e}")
            raise

        data = resp.json().get("message", {})

        citation_count = data.get("is-referenced-by-count", 0)

        references = []
        for ref in data.get("reference", []):
            ref_doi = ref.get("DOI", "")
            if ref_doi:
                references.append(ref_doi)

        return {
            "citation_count": citation_count,
            "references": references,
        }

    def enrich_articles(self, articles: list[dict]) -> list[dict]:
        """Enrich a list of article dicts with CrossRef data.

        Modifies articles in-place and returns them.
        """
        logger.info(f"Enriching {len(articles)} articles via CrossRef")
        enriched = 0
        failed = 0

        for article in articles:
            doi = article.get("doi")
            if not doi:
                continue

            try:
                cr_data = self.fetch_by_doi(doi)
                if cr_data:
                    article["citation_count"] = cr_data["citation_count"]
                    if cr_data["references"]:
                        existing_refs = article.get("references") or []
                        article["references"] = list(set(existing_refs + cr_data["references"]))
                    enriched += 1
            except Exception as e:
                logger.debug(f"CrossRef enrichment failed for {doi}: {e}")
                failed += 1

        logger.info(f"CrossRef enrichment: {enriched} succeeded, {failed} failed")
        return articles
