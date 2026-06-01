"""Attempt to get full text via PubMed Central and Unpaywall APIs."""

import sys
import time
from pathlib import Path
from typing import Optional

import requests
from Bio import Entrez
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

sys.path.insert(0, str(Path(__file__).parent.parent))
import config
from logger import setup_logger

logger = setup_logger("fulltext_fetcher")

Entrez.email = config.NCBI_EMAIL
if config.NCBI_API_KEY:
    Entrez.api_key = config.NCBI_API_KEY

FULLTEXT_DIR = config.BASE_DIR / "data" / "fulltext"
FULLTEXT_DIR.mkdir(parents=True, exist_ok=True)


class FullTextFetcher:
    """Fetches full text from PMC and Unpaywall."""

    def __init__(self):
        self.session = requests.Session()
        self._pmc_rate_delay = 1.0 / config.NCBI_RATE_LIMIT
        self._unpaywall_rate_delay = 1.0 / config.UNPAYWALL_RATE_LIMIT
        self._last_pmc_request = 0.0
        self._last_unpaywall_request = 0.0

    def _pmc_rate_limit(self):
        elapsed = time.time() - self._last_pmc_request
        if elapsed < self._pmc_rate_delay:
            time.sleep(self._pmc_rate_delay - elapsed)
        self._last_pmc_request = time.time()

    def _unpaywall_rate_limit(self):
        elapsed = time.time() - self._last_unpaywall_request
        if elapsed < self._unpaywall_rate_delay:
            time.sleep(self._unpaywall_rate_delay - elapsed)
        self._last_unpaywall_request = time.time()

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(min=1, max=30),
        retry=retry_if_exception_type((IOError, requests.RequestException)),
    )
    def fetch_from_pmc(self, pmid: str) -> Optional[dict]:
        """Try to fetch full text from PubMed Central.

        Returns dict with fulltext_available, fulltext_source, fulltext_path, or None.
        """
        self._pmc_rate_limit()

        # First check if there's a PMC ID for this PMID
        try:
            handle = Entrez.elink(dbfrom="pubmed", db="pmc", id=pmid)
            result = Entrez.read(handle)
            handle.close()
        except Exception as e:
            logger.debug(f"PMC link lookup failed for {pmid}: {e}")
            return None

        pmc_ids = []
        for linkset in result:
            for linksetdb in linkset.get("LinkSetDb", []):
                for link in linksetdb.get("Link", []):
                    pmc_ids.append(link["Id"])

        if not pmc_ids:
            return None

        pmc_id = pmc_ids[0]
        logger.debug(f"Found PMC ID {pmc_id} for PMID {pmid}")

        # Fetch full text XML from PMC
        self._pmc_rate_limit()
        try:
            handle = Entrez.efetch(db="pmc", id=pmc_id, rettype="xml")
            xml_content = handle.read()
            handle.close()
        except Exception as e:
            logger.debug(f"PMC full text fetch failed for {pmc_id}: {e}")
            return None

        # Save to file
        ft_path = FULLTEXT_DIR / f"PMC_{pmc_id}.xml"
        if isinstance(xml_content, bytes):
            ft_path.write_bytes(xml_content)
        else:
            ft_path.write_text(xml_content)

        return {
            "fulltext_available": True,
            "fulltext_source": "PMC",
            "fulltext_path": str(ft_path),
        }

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(min=1, max=30),
        retry=retry_if_exception_type((requests.RequestException, ConnectionError)),
    )
    def fetch_from_unpaywall(self, doi: str) -> Optional[dict]:
        """Try to fetch full text URL from Unpaywall.

        Returns dict with fulltext info, or None.
        """
        if not doi or not config.UNPAYWALL_EMAIL:
            return None

        self._unpaywall_rate_limit()
        url = f"https://api.unpaywall.org/v2/{doi}"

        try:
            resp = self.session.get(
                url,
                params={"email": config.UNPAYWALL_EMAIL},
                timeout=30,
            )
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
        except requests.RequestException:
            raise

        data = resp.json()

        if not data.get("is_oa"):
            return None

        # Find best OA location
        best_url = None
        for location in data.get("oa_locations", []):
            pdf_url = location.get("url_for_pdf") or location.get("url")
            if pdf_url:
                best_url = pdf_url
                break

        if not best_url:
            return None

        # Download the full text
        try:
            self._unpaywall_rate_limit()
            resp = self.session.get(best_url, timeout=60, stream=True)
            resp.raise_for_status()

            ext = ".pdf" if "pdf" in resp.headers.get("content-type", "") else ".html"
            safe_doi = doi.replace("/", "_")
            ft_path = FULLTEXT_DIR / f"unpaywall_{safe_doi}{ext}"

            with open(ft_path, "wb") as f:
                for chunk in resp.iter_content(chunk_size=8192):
                    f.write(chunk)

            return {
                "fulltext_available": True,
                "fulltext_source": "Unpaywall",
                "fulltext_path": str(ft_path),
            }
        except Exception as e:
            logger.debug(f"Unpaywall download failed for {doi}: {e}")
            return None

    def fetch_fulltext(self, pmid: str, doi: str = "") -> Optional[dict]:
        """Try PMC first, then Unpaywall. Returns fulltext info dict or None."""
        # Try PMC
        result = self.fetch_from_pmc(pmid)
        if result:
            return result

        # Try Unpaywall
        if doi:
            result = self.fetch_from_unpaywall(doi)
            if result:
                return result

        return None

    def enrich_articles(self, articles: list[dict]) -> list[dict]:
        """Add full text info to articles. Modifies in-place."""
        logger.info(f"Attempting full text retrieval for {len(articles)} articles")
        found = 0

        for article in articles:
            if article.get("fulltext_available"):
                found += 1
                continue

            result = self.fetch_fulltext(article.get("pmid", ""), article.get("doi", ""))
            if result:
                article.update(result)
                found += 1

        logger.info(f"Full text available for {found}/{len(articles)} articles")
        return articles
