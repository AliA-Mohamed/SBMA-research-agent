"""Basic tests for database operations."""

import sys
import tempfile
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from database.db_manager import DBManager


def test_article_crud():
    """Test article insert, read, update."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db = DBManager(db_path=Path(tmpdir) / "test.db")

        # Insert
        article = db.upsert_article({
            "pmid": "12345",
            "doi": "10.1000/test",
            "title": "Test SBMA Article",
            "abstract": "This is a test abstract about SBMA.",
            "authors": [{"name": "Smith John", "affiliation": "MIT", "orcid": ""}],
            "journal": "Test Journal",
            "publication_date": date(2020, 1, 1),
            "publication_year": 2020,
            "keywords": ["SBMA", "Kennedy disease"],
            "mesh_terms": ["Muscular Atrophy"],
            "article_type": "original_research",
        })
        assert article.pmid == "12345"
        assert article.title == "Test SBMA Article"

        # Read
        fetched = db.get_article("12345")
        assert fetched is not None
        assert fetched.journal == "Test Journal"

        # Update
        db.upsert_article({
            "pmid": "12345",
            "citation_count": 42,
        })
        updated = db.get_article("12345")
        assert updated.citation_count == 42
        assert updated.title == "Test SBMA Article"  # unchanged

        # Count
        assert db.get_article_count() == 1

        # Bulk insert
        db.upsert_articles_bulk([
            {"pmid": "11111", "title": "Article A", "publication_year": 2019, "journal": "J1", "authors": [{"name": "Alice"}]},
            {"pmid": "22222", "title": "Article B", "publication_year": 2021, "journal": "J2", "authors": [{"name": "Bob"}]},
        ])
        assert db.get_article_count() == 3

        # By year
        by_year = db.get_articles_by_year()
        assert 2020 in by_year

        # Top authors
        top = db.get_top_authors(5)
        assert len(top) > 0

        # Top journals
        journals = db.get_top_journals(5)
        assert len(journals) > 0

        print("All article CRUD tests passed!")


def test_knowledge_crud():
    """Test extracted knowledge operations."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db = DBManager(db_path=Path(tmpdir) / "test.db")

        # Need an article first
        db.upsert_article({"pmid": "99999", "title": "Test"})

        # Add knowledge
        ek = db.add_extracted_knowledge({
            "pmid": "99999",
            "knowledge_type": "finding",
            "summary": "CAG repeat length correlates with age of onset",
            "details": "Longer CAG repeats lead to earlier onset...",
            "confidence": 0.85,
            "novelty_at_publication": "new",
            "contradicts": [],
            "supports": ["88888"],
        })
        assert ek.id is not None
        assert ek.knowledge_type == "finding"

        # Retrieve
        knowledge = db.get_knowledge_for_article("99999")
        assert len(knowledge) == 1

        # Processed PMIDs
        processed = db.get_processed_pmids()
        assert "99999" in processed

        print("All knowledge CRUD tests passed!")


def test_textbook_crud():
    """Test textbook section operations."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db = DBManager(db_path=Path(tmpdir) / "test.db")

        # Add section
        section = db.upsert_textbook_section(
            chapter="Chapter 1: Historical Discovery & Overview",
            section_title="Chapter 1: Historical Discovery & Overview",
            content="SBMA was first described by Kennedy in 1968...",
            contributing_pmids=["12345"],
        )
        assert section.version == 1

        # Update section
        updated = db.upsert_textbook_section(
            chapter="Chapter 1: Historical Discovery & Overview",
            section_title="Chapter 1: Historical Discovery & Overview",
            content="SBMA was first described by Kennedy in 1968. The genetic basis was identified in 1991...",
            contributing_pmids=["67890"],
        )
        assert updated.version == 2
        assert "12345" in updated.contributing_pmids
        assert "67890" in updated.contributing_pmids

        # Get all
        sections = db.get_textbook_sections()
        assert len(sections) == 1

        # As dict
        td = db.get_textbook_as_dict()
        assert len(td) == 1

        print("All textbook CRUD tests passed!")


if __name__ == "__main__":
    test_article_crud()
    test_knowledge_crud()
    test_textbook_crud()
    print("\nAll tests passed!")
