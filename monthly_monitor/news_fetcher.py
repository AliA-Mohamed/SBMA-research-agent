"""Fetch SBMA-related news from ClinicalTrials.gov and other sources."""

import sys
import time
import requests
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from datetime import date
from logger import setup_logger
from database.db_manager import DBManager

logger = setup_logger("news_fetcher")

CLINICALTRIALS_API = "https://clinicaltrials.gov/api/v2/studies"

# Search terms for ClinicalTrials.gov
SBMA_CT_QUERY = (
    "spinal bulbar muscular atrophy OR kennedy disease OR SBMA OR bulbospinal muscular atrophy"
)



class NewsFetcher:
    """Fetches SBMA-related clinical trials and news."""

    def fetch_clinical_trials(self) -> list[dict]:
        """Fetch active/recruiting SBMA clinical trials from ClinicalTrials.gov v2 API.

        Returns list of trial dicts with nctId, title, status, phase, conditions,
        interventions, sponsor, lastUpdate, url.
        """
        trials = []
        params = {
            "query.cond": SBMA_CT_QUERY,
            "filter.overallStatus": "RECRUITING,NOT_YET_RECRUITING,ACTIVE_NOT_RECRUITING,ENROLLING_BY_INVITATION",
            "fields": "NCTId,BriefTitle,OverallStatus,Phase,Condition,InterventionName,LeadSponsorName,LastUpdatePostDate,StartDate,PrimaryCompletionDate",
            "pageSize": 100,
            "format": "json",
        }

        try:
            resp = requests.get(CLINICALTRIALS_API, params=params, timeout=30)
            resp.raise_for_status()
            data = resp.json()

            studies = data.get("studies", [])
            logger.info(f"ClinicalTrials.gov returned {len(studies)} studies")

            for study in studies:
                proto = study.get("protocolSection", {})
                ident = proto.get("identificationModule", {})
                status_mod = proto.get("statusModule", {})
                design = proto.get("designModule", {})
                conds = proto.get("conditionsModule", {})
                arms = proto.get("armsInterventionsModule", {})
                sponsor = proto.get("sponsorCollaboratorsModule", {})

                nct_id = ident.get("nctId", "")
                conditions = conds.get("conditions", [])
                interventions = [
                    i.get("interventionName", "")
                    for i in arms.get("interventions", [])
                ]

                # Only keep if clearly SBMA-related
                condition_str = " ".join(conditions).lower()
                sbma_terms = [
                    "spinal and bulbar", "spinal bulbar", "kennedy",
                    "sbma", "bulbospinal",
                ]
                if not any(t in condition_str for t in sbma_terms):
                    continue

                trials.append({
                    "nct_id": nct_id,
                    "title": ident.get("briefTitle", ""),
                    "status": status_mod.get("overallStatus", ""),
                    "phase": design.get("phases", []),
                    "conditions": conditions,
                    "interventions": interventions[:5],
                    "sponsor": sponsor.get("leadSponsor", {}).get("name", ""),
                    "start_date": status_mod.get("startDateStruct", {}).get("date", ""),
                    "completion_date": status_mod.get("primaryCompletionDateStruct", {}).get("date", ""),
                    "last_update": status_mod.get("lastUpdatePostDateStruct", {}).get("date", ""),
                    "url": f"https://clinicaltrials.gov/study/{nct_id}",
                })

            logger.info(f"Filtered to {len(trials)} SBMA-specific trials")

        except Exception as e:
            logger.error(f"ClinicalTrials.gov fetch failed: {e}")

        return trials

    def get_future_conferences(self) -> list[dict]:
        """Return future conferences from the database."""
        db = DBManager()
        confs = db.get_future_conferences(date.today())
        return [
            {
                "name": c.name,
                "short_name": c.short_name,
                "organizer": c.organizer,
                "url": c.url,
                "relevance": c.relevance,
                "start_date": c.start_date.isoformat() if c.start_date else None,
                "end_date": c.end_date.isoformat() if c.end_date else None,
                "location": c.location,
                "registration_status": c.registration_status,
                "abstract_status": c.abstract_status,
                "image_url": c.image_url,
            }
            for c in confs
        ]

    def get_recent_conferences(self) -> list[dict]:
        """Return recent conferences (last 30 days) from the database."""
        db = DBManager()
        confs = db.get_recent_conferences(date.today(), days_back=30)
        return [
            {
                "name": c.name,
                "short_name": c.short_name,
                "organizer": c.organizer,
                "url": c.url,
                "relevance": c.relevance,
                "start_date": c.start_date.isoformat() if c.start_date else None,
                "end_date": c.end_date.isoformat() if c.end_date else None,
                "location": c.location,
                "registration_status": c.registration_status,
                "abstract_status": c.abstract_status,
                "image_url": c.image_url,
            }
            for c in confs
        ]
