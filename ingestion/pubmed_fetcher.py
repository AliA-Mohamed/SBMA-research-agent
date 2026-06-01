"""Fetch all SBMA articles from PubMed via NCBI Entrez API."""

import re
import sys
import time
import json
import xml.etree.ElementTree as ET
from datetime import date
from pathlib import Path
from typing import Optional

from Bio import Entrez
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from tqdm import tqdm

sys.path.insert(0, str(Path(__file__).parent.parent))
import config
from logger import setup_logger

logger = setup_logger("pubmed_fetcher")

# Configure Entrez
Entrez.email = config.NCBI_EMAIL
if config.NCBI_API_KEY:
    Entrez.api_key = config.NCBI_API_KEY


class PubMedFetcher:
    """Fetches and parses SBMA articles from PubMed."""

    def __init__(self):
        self.rate_delay = 1.0 / config.NCBI_RATE_LIMIT
        self._last_request_time = 0.0

    def _rate_limit(self):
        """Enforce rate limiting between API calls."""
        elapsed = time.time() - self._last_request_time
        if elapsed < self.rate_delay:
            time.sleep(self.rate_delay - elapsed)
        self._last_request_time = time.time()

    @retry(
        stop=stop_after_attempt(config.RETRY_MAX_ATTEMPTS),
        wait=wait_exponential(min=config.RETRY_WAIT_MIN, max=config.RETRY_WAIT_MAX),
        retry=retry_if_exception_type((IOError, RuntimeError)),
    )
    def search_all_pmids(self, query: Optional[str] = None) -> list[str]:
        """Search PubMed and return all matching PMIDs."""
        query = query or config.PUBMED_SEARCH_QUERY
        logger.info(f"Searching PubMed with query: {query[:100]}...")

        self._rate_limit()
        handle = Entrez.esearch(db="pubmed", term=query, retmax=0, usehistory="y")
        result = Entrez.read(handle)
        handle.close()

        total_count = int(result["Count"])
        web_env = result["WebEnv"]
        query_key = result["QueryKey"]
        logger.info(f"Found {total_count} articles in PubMed")

        all_pmids = []
        batch_size = 10000

        for start in tqdm(range(0, total_count, batch_size), desc="Fetching PMIDs"):
            self._rate_limit()
            handle = Entrez.esearch(
                db="pubmed",
                term=query,
                retstart=start,
                retmax=batch_size,
                usehistory="y",
                WebEnv=web_env,
                query_key=query_key,
            )
            batch_result = Entrez.read(handle)
            handle.close()
            all_pmids.extend(batch_result["IdList"])

        logger.info(f"Retrieved {len(all_pmids)} unique PMIDs")
        return list(set(all_pmids))

    @retry(
        stop=stop_after_attempt(config.RETRY_MAX_ATTEMPTS),
        wait=wait_exponential(min=config.RETRY_WAIT_MIN, max=config.RETRY_WAIT_MAX),
        retry=retry_if_exception_type((IOError, RuntimeError)),
    )
    def fetch_article_details(self, pmids: list[str], save_xml: bool = True) -> list[dict]:
        """Fetch full article metadata for a batch of PMIDs."""
        if not pmids:
            return []

        self._rate_limit()
        handle = Entrez.efetch(
            db="pubmed",
            id=",".join(pmids),
            rettype="xml",
            retmode="xml",
        )
        raw_xml = handle.read()
        handle.close()

        # Save raw XML backup
        if save_xml:
            xml_path = config.RAW_XML_DIR / f"batch_{pmids[0]}_{pmids[-1]}.xml"
            if isinstance(raw_xml, bytes):
                xml_path.write_bytes(raw_xml)
            else:
                xml_path.write_text(raw_xml)

        return self._parse_xml(raw_xml)

    def _parse_xml(self, xml_data, filter_relevance: bool = True) -> list[dict]:
        """Parse PubMed XML into article dictionaries.

        Args:
            filter_relevance: If True, apply SBMA relevance filter to exclude
                articles not primarily about SBMA.
        """
        if isinstance(xml_data, bytes):
            xml_data = xml_data.decode("utf-8", errors="replace")

        articles = []
        rejected_count = 0
        try:
            root = ET.fromstring(xml_data)
        except ET.ParseError as e:
            logger.error(f"XML parse error: {e}")
            return articles

        for article_elem in root.findall(".//PubmedArticle"):
            try:
                parsed = self._parse_single_article(article_elem)
                if parsed:
                    if filter_relevance and not self.is_sbma_relevant(parsed):
                        rejected_count += 1
                        continue
                    articles.append(parsed)
            except Exception as e:
                pmid = article_elem.findtext(".//PMID", "unknown")
                logger.warning(f"Failed to parse article PMID={pmid}: {e}")

        if rejected_count > 0:
            logger.info(f"Filtered out {rejected_count} non-SBMA articles from batch")

        return articles

    def _parse_single_article(self, elem) -> Optional[dict]:
        """Parse a single PubmedArticle XML element."""
        pmid = elem.findtext(".//PMID")
        if not pmid:
            return None

        medline = elem.find(".//MedlineCitation")
        article = medline.find("Article") if medline is not None else None
        if article is None:
            return None

        # Title
        title = article.findtext("ArticleTitle", "")

        # Abstract
        abstract_parts = []
        abstract_elem = article.find("Abstract")
        if abstract_elem is not None:
            for text_elem in abstract_elem.findall("AbstractText"):
                label = text_elem.get("Label", "")
                text_content = "".join(text_elem.itertext())
                if label:
                    abstract_parts.append(f"{label}: {text_content}")
                else:
                    abstract_parts.append(text_content)
        abstract = "\n".join(abstract_parts)

        # Authors
        authors = []
        author_list = article.find("AuthorList")
        if author_list is not None:
            for author_elem in author_list.findall("Author"):
                last = author_elem.findtext("LastName", "")
                fore = author_elem.findtext("ForeName", "")
                name = f"{last} {fore}".strip() if last else author_elem.findtext("CollectiveName", "")

                affiliation = ""
                aff_elem = author_elem.find("AffiliationInfo")
                if aff_elem is not None:
                    affiliation = aff_elem.findtext("Affiliation", "")

                orcid = ""
                for id_elem in author_elem.findall("Identifier"):
                    if id_elem.get("Source") == "ORCID":
                        orcid = id_elem.text or ""

                if name:
                    authors.append({
                        "name": name,
                        "affiliation": affiliation,
                        "orcid": orcid,
                    })

        # Journal
        journal_elem = article.find("Journal")
        journal = ""
        volume = ""
        issue = ""
        if journal_elem is not None:
            journal = journal_elem.findtext("Title", "") or journal_elem.findtext("ISOAbbreviation", "")
            ji = journal_elem.find("JournalIssue")
            if ji is not None:
                volume = ji.findtext("Volume", "")
                issue = ji.findtext("Issue", "")

        pages = article.findtext("Pagination/MedlinePgn", "")

        # Publication date
        pub_date, pub_year = self._parse_pub_date(article, journal_elem)

        # DOI
        doi = ""
        for id_elem in elem.findall(".//ArticleId"):
            if id_elem.get("IdType") == "doi":
                doi = id_elem.text or ""
                break

        # Article type
        pub_types = []
        for pt in article.findall("PublicationTypeList/PublicationType"):
            if pt.text:
                pub_types.append(pt.text)
        article_type = self._classify_article_type(pub_types)

        # Keywords
        keywords = []
        for kw in medline.findall(".//Keyword"):
            if kw.text:
                keywords.append(kw.text)

        # MeSH terms
        mesh_terms = []
        for mesh in medline.findall(".//MeshHeading/DescriptorName"):
            if mesh.text:
                mesh_terms.append(mesh.text)

        return {
            "pmid": pmid,
            "doi": doi,
            "title": title,
            "abstract": abstract,
            "authors": authors,
            "journal": journal,
            "publication_date": pub_date,
            "publication_year": pub_year,
            "volume": volume,
            "issue": issue,
            "pages": pages,
            "keywords": keywords,
            "mesh_terms": mesh_terms,
            "article_type": article_type,
        }

    def _parse_pub_date(self, article_elem, journal_elem) -> tuple[Optional[date], Optional[int]]:
        """Extract publication date from article XML."""
        # Try ArticleDate first (electronic pub date)
        for ad in article_elem.findall("ArticleDate"):
            year = ad.findtext("Year")
            month = ad.findtext("Month", "1")
            day = ad.findtext("Day", "1")
            if year:
                try:
                    return date(int(year), int(month), int(day)), int(year)
                except (ValueError, TypeError):
                    pass

        # Try Journal PubDate
        if journal_elem is not None:
            pd_elem = journal_elem.find(".//PubDate")
            if pd_elem is not None:
                year = pd_elem.findtext("Year")
                month = pd_elem.findtext("Month", "1")
                day = pd_elem.findtext("Day", "1")
                if year:
                    # Month might be text like "Jan"
                    month_map = {
                        "jan": 1, "feb": 2, "mar": 3, "apr": 4,
                        "may": 5, "jun": 6, "jul": 7, "aug": 8,
                        "sep": 9, "oct": 10, "nov": 11, "dec": 12,
                    }
                    try:
                        m = int(month)
                    except ValueError:
                        m = month_map.get(month[:3].lower(), 1)
                    try:
                        d = int(day)
                    except ValueError:
                        d = 1
                    try:
                        return date(int(year), m, d), int(year)
                    except (ValueError, TypeError):
                        return date(int(year), 1, 1), int(year)

        # Try MedlineDate as fallback
        medline_date = article_elem.findtext(".//MedlineDate") or ""
        if medline_date:
            for part in medline_date.split():
                if part.isdigit() and len(part) == 4:
                    return date(int(part), 1, 1), int(part)

        return None, None

    @staticmethod
    def is_sbma_relevant(article: dict) -> bool:
        """Validate that an article is truly about SBMA, not a related disease.

        Returns True if the article should be kept, False if it should be excluded.
        """
        title = (article.get("title") or "").lower()
        abstract = (article.get("abstract") or "").lower()
        mesh_terms = [t.lower() for t in (article.get("mesh_terms") or [])]
        keywords = [k.lower() for k in (article.get("keywords") or [])]

        combined_text = f"{title} {abstract}"
        combined_with_mesh = f"{combined_text} {' '.join(mesh_terms)} {' '.join(keywords)}"

        # Step 1: Check if any SBMA-specific positive term appears anywhere
        has_sbma_term = False
        for term in config.SBMA_POSITIVE_TERMS:
            if term == "sbma":
                # "SBMA" needs word-boundary matching to avoid matching inside other words
                if re.search(r'\bsbma\b', combined_with_mesh):
                    has_sbma_term = True
                    break
            elif term in combined_with_mesh:
                has_sbma_term = True
                break

        if not has_sbma_term:
            # Article matched PubMed query but doesn't mention SBMA at all — reject
            logger.debug(f"REJECTED (no SBMA term): {article.get('pmid')} — {title[:80]}")
            return False

        # Step 2: Check if SBMA appears in the TITLE (strong signal)
        sbma_in_title = False
        for term in config.SBMA_POSITIVE_TERMS:
            if term == "sbma":
                if re.search(r'\bsbma\b', title):
                    sbma_in_title = True
                    break
            elif term in title:
                sbma_in_title = True
                break

        # Step 3: Check if the article is primarily about another disease
        exclude_in_title = False
        for disease in config.SBMA_EXCLUDE_PRIMARY_DISEASES:
            if disease in title:
                exclude_in_title = True
                break

        # If the title is about another disease AND SBMA is NOT in the title,
        # this article is likely about the other disease and only mentions SBMA in passing
        if exclude_in_title and not sbma_in_title:
            logger.debug(
                f"REJECTED (primary disease mismatch): {article.get('pmid')} — {title[:80]}"
            )
            return False

        # Step 4: For articles that only mention "SBMA" in abstract (not title),
        # ensure it's a substantive mention, not just a passing reference in a list
        if not sbma_in_title:
            # Count how many times SBMA-specific terms appear in abstract
            sbma_mentions = 0
            for term in config.SBMA_POSITIVE_TERMS:
                if term == "sbma":
                    sbma_mentions += len(re.findall(r'\bsbma\b', abstract))
                else:
                    sbma_mentions += abstract.count(term)

            # If SBMA is mentioned only once and abstract is long, it's likely a passing reference
            if sbma_mentions <= 1 and len(abstract) > 500:
                # Check if the abstract discusses multiple NMDs — a sign of a review/comparison
                other_disease_count = 0
                # Tuples of (pattern, use_word_boundary). Short abbreviations need
                # word-boundary matching to avoid false positives inside longer words.
                check_diseases = [
                    ("amyotrophic lateral sclerosis", False),
                    ("\\bals\\b", True),
                    ("spinal muscular atrophy", False),
                    ("\\bsma\\b", True),
                    ("huntington", False),
                    ("spinocerebellar ataxia", False),
                    ("duchenne", False),
                    ("myotonic dystrophy", False),
                ]
                for pattern, is_regex in check_diseases:
                    if is_regex:
                        if re.search(pattern, abstract):
                            other_disease_count += 1
                    elif pattern in abstract:
                        other_disease_count += 1

                if other_disease_count >= 2:
                    logger.debug(
                        f"REJECTED (passing mention in multi-NMD article): "
                        f"{article.get('pmid')} — {title[:80]}"
                    )
                    return False

        return True

    def _classify_article_type(self, pub_types: list[str]) -> str:
        """Classify article type from PubMed publication types."""
        pub_types_lower = [pt.lower() for pt in pub_types]
        if any("review" in pt for pt in pub_types_lower):
            return "review"
        if any("clinical trial" in pt for pt in pub_types_lower):
            return "clinical_trial"
        if any("case report" in pt for pt in pub_types_lower):
            return "case_report"
        if any("meta-analysis" in pt for pt in pub_types_lower):
            return "meta_analysis"
        if any("letter" in pt for pt in pub_types_lower):
            return "letter"
        if any("editorial" in pt for pt in pub_types_lower):
            return "editorial"
        if any("comment" in pt for pt in pub_types_lower):
            return "comment"
        return "original_research"

    def fetch_all_articles(self, batch_size: int = 100, checkpoint_file: Optional[Path] = None) -> list[dict]:
        """Fetch all SBMA articles with checkpointing.

        Returns list of parsed article dicts.
        """
        checkpoint_file = checkpoint_file or config.CHECKPOINTS_DIR / "pubmed_fetch_checkpoint.json"

        # Load checkpoint if exists
        fetched_pmids = set()
        all_articles = []
        if checkpoint_file.exists():
            checkpoint = json.loads(checkpoint_file.read_text())
            fetched_pmids = set(checkpoint.get("fetched_pmids", []))
            logger.info(f"Resuming from checkpoint: {len(fetched_pmids)} articles already fetched")

        # Get all PMIDs
        all_pmids = self.search_all_pmids()
        remaining = [p for p in all_pmids if p not in fetched_pmids]
        logger.info(f"Total PMIDs: {len(all_pmids)}, remaining to fetch: {len(remaining)}")

        # Fetch in batches
        for i in tqdm(range(0, len(remaining), batch_size), desc="Fetching articles"):
            batch = remaining[i:i + batch_size]
            try:
                articles = self.fetch_article_details(batch)
                all_articles.extend(articles)
                fetched_pmids.update(batch)

                # Save checkpoint
                if (i // batch_size + 1) % 5 == 0:
                    checkpoint_file.write_text(json.dumps({
                        "fetched_pmids": list(fetched_pmids),
                        "total_found": len(all_pmids),
                    }))
                    logger.info(f"Checkpoint saved: {len(fetched_pmids)}/{len(all_pmids)}")

            except Exception as e:
                logger.error(f"Failed to fetch batch starting at {i}: {e}")
                # Save checkpoint on error
                checkpoint_file.write_text(json.dumps({
                    "fetched_pmids": list(fetched_pmids),
                    "total_found": len(all_pmids),
                }))
                continue

        # Final checkpoint
        checkpoint_file.write_text(json.dumps({
            "fetched_pmids": list(fetched_pmids),
            "total_found": len(all_pmids),
            "completed": True,
        }))

        logger.info(f"Fetched {len(all_articles)} articles total")
        return all_articles
