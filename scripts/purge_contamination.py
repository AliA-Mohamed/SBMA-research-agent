#!/usr/bin/env python3
"""One-time script to remove contaminated knowledge entries.

These entries were hallucinated by the LLM — it inserted polymer chemistry content
(sulfobetaine methacrylate, zwitterionic polymers, bacterial SbmA transporter)
into knowledge entries extracted from legitimate SBMA articles.

The source articles themselves are correct; only the knowledge entries are bad.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from database.db_manager import DBManager
from database.models import ExtractedKnowledge
from sqlalchemy import or_

db = DBManager()
session = db.get_session()

# Precise contamination terms — NOT "polymer" or "nanoparticle" which appear in
# legitimate molecular biology (RNA polymerase, lipid nanoparticle drug delivery)
CONTAMINATION_PATTERNS = [
    "%sulfobetaine%",
    "%zwitterionic polymer%",
    "%antifouling%",
    "%antimicrobial peptide uptake%",
    "%distinguishing SBMA (disease) from SBMA (sulfobetaine%",
]

filters = []
for pattern in CONTAMINATION_PATTERNS:
    filters.append(ExtractedKnowledge.summary.ilike(pattern))
    filters.append(ExtractedKnowledge.details.ilike(pattern))

contaminated = session.query(ExtractedKnowledge).filter(or_(*filters)).all()

print(f"Found {len(contaminated)} contaminated knowledge entries:")
for entry in contaminated:
    print(f"  ID:{entry.id} PMID:{entry.pmid} — {entry.summary[:120]}")

if contaminated:
    for entry in contaminated:
        session.delete(entry)
    session.commit()
    print(f"\nDeleted {len(contaminated)} contaminated entries.")
else:
    print("\nNo contamination found — database is clean.")

session.close()
