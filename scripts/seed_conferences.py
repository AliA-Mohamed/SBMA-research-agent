"""Seed script to populate conference events in the database."""

import sys
from datetime import date
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from database.db_manager import DBManager

# Use the current date to set relative test dates for the "Recent Conference" feature
# We will make AAN a recent conference that ended 10 days ago.
# We will make the others future conferences.
today = date.today()
from datetime import timedelta

CONFERENCES = [
    {
        "name": "MDA Clinical & Scientific Conference",
        "short_name": "MDA",
        "organizer": "Muscular Dystrophy Association",
        "url": "https://www.mda.org/science/scientific-conferences",
        "relevance": "Annual neuromuscular disease conference with regular SBMA sessions.",
        "start_date": date(2027, 3, 15),
        "end_date": date(2027, 3, 18),
        "location": "Location TBA",
        "registration_status": "TBA",
        "abstract_status": "TBA",
        "image_url": "/conferences/mda.png",
    },
    {
        "name": "AAN Annual Meeting",
        "short_name": "AAN",
        "organizer": "American Academy of Neurology",
        "url": "https://www.aan.com/conferences-community/annual-meeting/",
        "relevance": "Premier neurology congress featuring motor neuron disease research.",
        # Make this a RECENT conference (ended 10 days ago)
        "start_date": today - timedelta(days=14),
        "end_date": today - timedelta(days=10),
        "location": "San Diego, CA",
        "registration_status": "Closed",
        "abstract_status": "Closed",
        "image_url": "/conferences/aan.png",
    },
    {
        "name": "EAN Congress",
        "short_name": "EAN",
        "organizer": "European Academy of Neurology",
        "url": "https://www.ean.org/congress",
        "relevance": "Leading European neurology meeting with SBMA and MND coverage.",
        "start_date": date(2026, 6, 21),
        "end_date": date(2026, 6, 24),
        "location": "Helsinki, Finland",
        "registration_status": "Open",
        "abstract_status": "Closed",
        "image_url": "/conferences/ean.png",
    },
    {
        "name": "International Symposium on ALS/MND",
        "short_name": "ALS/MND",
        "organizer": "Motor Neurone Disease Association",
        "url": "https://symposium.mndassociation.org/",
        "relevance": "Dedicated motor neuron disease symposium — SBMA is a core topic.",
        "start_date": date(2026, 12, 9),
        "end_date": date(2026, 12, 11),
        "location": "Amsterdam, Netherlands",
        "registration_status": "TBA",
        "abstract_status": "TBA",
        "image_url": "/conferences/als_mnd.png",
    },
    {
        "name": "PNS Annual Meeting",
        "short_name": "PNS",
        "organizer": "Peripheral Nerve Society",
        "url": "https://www.pnsociety.com/meetings",
        "relevance": "Covers peripheral neuropathy and motor neuron disease research.",
        "start_date": date(2026, 7, 15),
        "end_date": date(2026, 7, 18),
        "location": "Location TBA",
        "registration_status": "TBA",
        "abstract_status": "TBA",
        "image_url": "/conferences/pns.png",
    },
    {
        "name": "WMS Congress",
        "short_name": "WMS",
        "organizer": "World Muscle Society",
        "url": "https://www.worldmusclesociety.org/congress",
        "relevance": "International neuromuscular congress with Kennedy disease sessions.",
        "start_date": date(2026, 10, 7),
        "end_date": date(2026, 10, 11),
        "location": "Location TBA",
        "registration_status": "TBA",
        "abstract_status": "TBA",
        "image_url": "/conferences/wms.png",
    },
    {
        "name": "KDA Annual Conference",
        "short_name": "KDA",
        "organizer": "Kennedy's Disease Association",
        "url": "https://www.kennedysdisease.org/",
        "relevance": "The only conference dedicated entirely to SBMA/Kennedy disease.",
        # Make this a PAST conference that was more than 30 days ago
        "start_date": date(2026, 2, 27),
        "end_date": date(2026, 3, 2),
        "location": "Orlando, FL, USA",
        "registration_status": "Closed",
        "abstract_status": "Closed",
        "image_url": "/conferences/kda.png",
    },
]

def seed_db():
    print("Initializing Database Manager...")
    db = DBManager()
    
    print(f"Seeding {len(CONFERENCES)} conferences...")
    for conf_data in CONFERENCES:
        conf = db.upsert_conference(conf_data)
        print(f"  Upserted: {conf.short_name} ({conf.start_date} to {conf.end_date})")

    print("\nVerifying DB records:")
    future = db.get_future_conferences(today)
    recent = db.get_recent_conferences(today, days_back=30)
    
    print(f"  Future Conferences: {len(future)}")
    for c in future:
        print(f"    - {c.short_name}")
        
    print(f"  Recent Conferences (last 30 days): {len(recent)}")
    for c in recent:
        print(f"    - {c.short_name}")

if __name__ == "__main__":
    seed_db()
