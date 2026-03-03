"""Get citation graphs, influential citations, and embeddings from Semantic Scholar."""

import sys
import time
from pathlib import Path
from typing import Optional

import requests
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

sys.path.insert(0, str(Path(__file__).parent.parent))
import config
from logger import setup_logger

logger = setup_logger("semantic_scholar")


class SemanticScholarFetcher:
    """Fetches citation data from the Semantic Scholar API.

    Supports both single-paper and batch (up to 500 papers) fetching.
    Handles rate limits with exponential backoff.
    """

    BASE_URL = "https://api.semanticscholar.org/graph/v1/paper"
    BATCH_SIZE = 500  # S2 batch API limit

    def __init__(self):
        self.session = requests.Session()
        has_key = bool(config.SEMANTIC_SCHOLAR_API_KEY)
        if has_key:
            self.session.headers["x-api-key"] = config.SEMANTIC_SCHOLAR_API_KEY
        # Without API key: ~1 req/sec is safe; with key: ~10 req/sec
        self.rate_delay = 0.1 if has_key else 1.2
        self._last_request_time = 0.0
        self._consecutive_429s = 0

    def _rate_limit(self):
        elapsed = time.time() - self._last_request_time
        if elapsed < self.rate_delay:
            time.sleep(self.rate_delay - elapsed)
        self._last_request_time = time.time()

    def _handle_rate_limit(self, resp: requests.Response):
        """Exponential backoff on 429. Raises to trigger tenacity retry."""
        self._consecutive_429s += 1
        # Exponential backoff: 5, 10, 20, 40, 60 (capped) seconds
        backoff = min(5 * (2 ** (self._consecutive_429s - 1)), 60)
        logger.warning(f"Rate limited (429). Backing off {backoff}s (consecutive: {self._consecutive_429s})")
        time.sleep(backoff)
        raise requests.RequestException("Rate limited")

    def _reset_backoff(self):
        self._consecutive_429s = 0

    @retry(
        stop=stop_after_attempt(config.RETRY_MAX_ATTEMPTS),
        wait=wait_exponential(min=config.RETRY_WAIT_MIN, max=config.RETRY_WAIT_MAX),
        retry=retry_if_exception_type((requests.RequestException, ConnectionError)),
    )
    def fetch_by_pmid(self, pmid: str) -> Optional[dict]:
        """Fetch Semantic Scholar data for a single PubMed ID.

        Returns dict with citation_count, cited_by, references, influential_citation_count.
        """
        self._rate_limit()
        url = f"{self.BASE_URL}/PMID:{pmid}"
        fields = "citationCount,influentialCitationCount,citations.externalIds,references.externalIds"

        try:
            resp = self.session.get(url, params={"fields": fields}, timeout=30)
            if resp.status_code == 404:
                logger.debug(f"PMID not found in Semantic Scholar: {pmid}")
                self._reset_backoff()
                return None
            if resp.status_code == 429:
                self._handle_rate_limit(resp)
            resp.raise_for_status()
        except requests.RequestException:
            raise

        self._reset_backoff()
        return self._parse_paper_data(data=resp.json())

    @retry(
        stop=stop_after_attempt(config.RETRY_MAX_ATTEMPTS),
        wait=wait_exponential(min=2, max=120),
        retry=retry_if_exception_type((requests.RequestException, ConnectionError)),
    )
    def fetch_batch(self, pmids: list[str]) -> dict[str, dict]:
        """Fetch Semantic Scholar data for up to 500 PMIDs in a single request.

        Returns {pmid: parsed_data} for papers found.
        """
        if not pmids:
            return {}

        self._rate_limit()
        url = f"{self.BASE_URL}/batch"
        fields = "externalIds,citationCount,influentialCitationCount,citations.externalIds,references.externalIds"
        ids = [f"PMID:{pmid}" for pmid in pmids]

        try:
            resp = self.session.post(
                url,
                params={"fields": fields},
                json={"ids": ids},
                timeout=120,
            )
            if resp.status_code == 429:
                self._handle_rate_limit(resp)
            resp.raise_for_status()
        except requests.RequestException:
            raise

        self._reset_backoff()
        results = {}
        for paper in resp.json():
            if paper is None:
                continue
            # Extract PMID from externalIds
            ext_ids = paper.get("externalIds") or {}
            pmid = ext_ids.get("PubMed")
            if pmid:
                results[pmid] = self._parse_paper_data(paper)

        return results

    def _parse_paper_data(self, data: dict) -> dict:
        """Parse a Semantic Scholar paper response into our format."""
        # Extract citing PMIDs
        cited_by = []
        for citation in data.get("citations", []) or []:
            ext_ids = (citation.get("externalIds") or {}) if citation else {}
            citing_pmid = ext_ids.get("PubMed")
            if citing_pmid:
                cited_by.append(citing_pmid)

        # Extract reference PMIDs
        references = []
        for ref in data.get("references", []) or []:
            ext_ids = (ref.get("externalIds") or {}) if ref else {}
            ref_pmid = ext_ids.get("PubMed")
            if ref_pmid:
                references.append(ref_pmid)

        return {
            "citation_count": data.get("citationCount", 0),
            "cited_by": cited_by,
            "references": references,
            "influential_citation_count": data.get("influentialCitationCount", 0),
        }

    def enrich_articles(self, articles: list[dict]) -> list[dict]:
        """Enrich articles with Semantic Scholar citation data using batch API.

        Modifies articles in-place and returns them.
        """
        logger.info(f"Enriching {len(articles)} articles via Semantic Scholar")

        # Build PMID -> article index
        pmid_to_article = {}
        pmids_to_fetch = []
        for article in articles:
            pmid = article.get("pmid")
            if pmid:
                pmid_to_article[pmid] = article
                pmids_to_fetch.append(pmid)

        enriched = 0
        failed_batches = 0

        # Process in batches of 500
        for i in range(0, len(pmids_to_fetch), self.BATCH_SIZE):
            batch = pmids_to_fetch[i : i + self.BATCH_SIZE]
            batch_num = i // self.BATCH_SIZE + 1
            total_batches = (len(pmids_to_fetch) + self.BATCH_SIZE - 1) // self.BATCH_SIZE
            logger.info(f"Batch {batch_num}/{total_batches}: fetching {len(batch)} papers")

            try:
                results = self.fetch_batch(batch)
                for pmid, ss_data in results.items():
                    article = pmid_to_article.get(pmid)
                    if not article:
                        continue
                    self._merge_data(article, ss_data)
                    enriched += 1
            except Exception as e:
                logger.error(f"Batch {batch_num} failed: {e}")
                failed_batches += 1
                # Fall back to individual fetching for this batch
                for pmid in batch:
                    try:
                        ss_data = self.fetch_by_pmid(pmid)
                        if ss_data:
                            self._merge_data(pmid_to_article[pmid], ss_data)
                            enriched += 1
                    except Exception:
                        pass

        logger.info(f"Semantic Scholar enrichment: {enriched} succeeded, {failed_batches} batches failed")
        return articles

    def _merge_data(self, article: dict, ss_data: dict):
        """Merge Semantic Scholar data into an article dict."""
        # Use S2 citation count if higher than existing
        if ss_data["citation_count"] > (article.get("citation_count") or 0):
            article["citation_count"] = ss_data["citation_count"]

        # Merge cited_by
        existing_cited_by = article.get("cited_by") or []
        article["cited_by"] = list(set(existing_cited_by + ss_data["cited_by"]))

        # Merge references
        existing_refs = article.get("references") or []
        article["references"] = list(set(existing_refs + ss_data["references"]))
