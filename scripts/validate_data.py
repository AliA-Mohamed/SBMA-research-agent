#!/usr/bin/env python3
"""Post-ingestion data validation for the SBMA research database."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import func
from rich.console import Console
from rich.table import Table

from logger import setup_logger
from database.db_manager import DBManager
from database.models import Article, ExtractedKnowledge, TextbookSection, AuthorAnalytics

logger = setup_logger("validate_data")
console = Console()

MIN_ARTICLE_COUNT = 990
YEAR_MIN = 1960
YEAR_MAX = 2030


class ValidationResult:
    def __init__(self):
        self.checks: list[tuple[str, bool, str]] = []

    def add(self, name: str, passed: bool, detail: str):
        self.checks.append((name, passed, detail))
        level = "PASS" if passed else "FAIL"
        log_fn = logger.info if passed else logger.error
        log_fn(f"[{level}] {name}: {detail}")

    @property
    def all_passed(self) -> bool:
        return all(p for _, p, _ in self.checks)

    def print_report(self):
        table = Table(title="Data Validation Report", show_lines=True)
        table.add_column("Check", style="bold")
        table.add_column("Status", justify="center")
        table.add_column("Detail")
        for name, passed, detail in self.checks:
            status = "[green]PASS[/green]" if passed else "[red]FAIL[/red]"
            table.add_row(name, status, detail)
        console.print(table)
        passed = sum(1 for _, p, _ in self.checks if p)
        total = len(self.checks)
        if self.all_passed:
            console.print(f"\n[bold green]All {total} checks passed.[/bold green]")
        else:
            failed = total - passed
            console.print(f"\n[bold red]{failed}/{total} checks FAILED.[/bold red]")


def validate_articles(db: DBManager, result: ValidationResult):
    session = db.get_session()
    try:
        total = session.query(func.count(Article.pmid)).scalar()
        result.add("Article count", total >= MIN_ARTICLE_COUNT,
                    f"{total} articles (minimum {MIN_ARTICLE_COUNT})")

        null_pmid = session.query(func.count(Article.pmid)).filter(Article.pmid == None).scalar()
        result.add("No null PMIDs", null_pmid == 0, f"{null_pmid} null PMIDs")

        empty_title = session.query(func.count(Article.pmid)).filter(
            (Article.title == None) | (Article.title == "")
        ).scalar()
        result.add("No empty titles", empty_title == 0, f"{empty_title} empty titles")

        bad_years = session.query(func.count(Article.pmid)).filter(
            (Article.publication_year != None) &
            ((Article.publication_year < YEAR_MIN) | (Article.publication_year > YEAR_MAX))
        ).scalar()
        result.add("Publication years in range", bad_years == 0,
                    f"{bad_years} articles outside {YEAR_MIN}-{YEAR_MAX}")

        all_pmids = [r[0] for r in session.query(Article.pmid).all()]
        dup_count = len(all_pmids) - len(set(all_pmids))
        result.add("No duplicate PMIDs", dup_count == 0, f"{dup_count} duplicates")
    finally:
        session.close()


def validate_knowledge(db: DBManager, result: ValidationResult):
    session = db.get_session()
    try:
        total = session.query(func.count(ExtractedKnowledge.id)).scalar()
        result.add("Knowledge count", True, f"{total} entries")

        article_pmids = set(r[0] for r in session.query(Article.pmid).all())
        knowledge_pmids = set(r[0] for r in session.query(ExtractedKnowledge.pmid).distinct().all())
        orphaned = knowledge_pmids - article_pmids
        result.add("No orphaned knowledge", len(orphaned) == 0,
                    f"{len(orphaned)} orphaned PMIDs" + (f": {sorted(orphaned)[:5]}" if orphaned else ""))

        empty_summary = session.query(func.count(ExtractedKnowledge.id)).filter(
            (ExtractedKnowledge.summary == None) | (ExtractedKnowledge.summary == "")
        ).scalar()
        result.add("No empty summaries", empty_summary == 0, f"{empty_summary} empty summaries")

        bad_confidence = session.query(func.count(ExtractedKnowledge.id)).filter(
            (ExtractedKnowledge.confidence != None) &
            ((ExtractedKnowledge.confidence < 0.0) | (ExtractedKnowledge.confidence > 1.0))
        ).scalar()
        result.add("Confidence in [0,1]", bad_confidence == 0,
                    f"{bad_confidence} out-of-range confidence values")
    finally:
        session.close()


def validate_textbook(db: DBManager, result: ValidationResult):
    session = db.get_session()
    try:
        sections = session.query(TextbookSection).all()
        result.add("Textbook sections exist", len(sections) > 0, f"{len(sections)} sections")

        empty_content = sum(1 for s in sections if not s.content or not s.content.strip())
        result.add("No empty chapter content", empty_content == 0,
                    f"{empty_content} sections with empty content")

        seen = set()
        dups = 0
        for s in sections:
            key = (s.chapter, s.section_title)
            if key in seen:
                dups += 1
            seen.add(key)
        result.add("No duplicate chapter+section", dups == 0, f"{dups} duplicates")

        bad_version = sum(1 for s in sections if s.version is None or s.version < 1)
        result.add("Versions are positive", bad_version == 0,
                    f"{bad_version} sections with invalid version")
    finally:
        session.close()


def validate_authors(db: DBManager, result: ValidationResult):
    session = db.get_session()
    try:
        authors = session.query(AuthorAnalytics).all()
        result.add("Author analytics exist", len(authors) > 0, f"{len(authors)} authors")

        zero_papers = sum(1 for a in authors if a.total_papers is None or a.total_papers == 0)
        result.add("No authors with 0 papers", zero_papers == 0,
                    f"{zero_papers} authors with 0 total_papers")

        negative_h = sum(1 for a in authors if a.h_index_in_field is not None and a.h_index_in_field < 0)
        result.add("h_index non-negative", negative_h == 0,
                    f"{negative_h} authors with negative h_index")

        names = [a.author_name for a in authors]
        dup_names = len(names) - len(set(names))
        result.add("No duplicate author names", dup_names == 0, f"{dup_names} duplicates")
    finally:
        session.close()


def validate_cross_table(db: DBManager, result: ValidationResult):
    session = db.get_session()
    try:
        article_pmids = set(r[0] for r in session.query(Article.pmid).all())

        # Knowledge -> Articles FK integrity (redundant with orphan check, but explicit)
        knowledge_pmids = set(r[0] for r in session.query(ExtractedKnowledge.pmid).distinct().all())
        missing_k = knowledge_pmids - article_pmids
        result.add("Knowledge PMIDs exist in articles", len(missing_k) == 0,
                    f"{len(missing_k)} missing")

        # Textbook contributing_pmids -> Articles
        sections = session.query(TextbookSection.contributing_pmids).all()
        textbook_pmids: set[str] = set()
        for (pmids_json,) in sections:
            if pmids_json:
                textbook_pmids.update(pmids_json)
        missing_t = textbook_pmids - article_pmids
        result.add("Textbook PMIDs exist in articles", len(missing_t) == 0,
                    f"{len(missing_t)} missing" + (f": {sorted(missing_t)[:5]}" if missing_t else ""))
    finally:
        session.close()


def main():
    console.print("[bold green]SBMA Research Agent — Data Validation[/bold green]")
    console.print("=" * 60)

    db = DBManager()
    result = ValidationResult()

    validate_articles(db, result)
    validate_knowledge(db, result)
    validate_textbook(db, result)
    validate_authors(db, result)
    validate_cross_table(db, result)

    console.print()
    result.print_report()

    sys.exit(0 if result.all_passed else 1)


if __name__ == "__main__":
    main()
