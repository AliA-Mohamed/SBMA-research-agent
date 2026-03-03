"""Database manager for CRUD operations on the SBMA research database."""

import sys
from datetime import datetime, date
from typing import Optional
from pathlib import Path

from sqlalchemy import create_engine, func, text
from sqlalchemy.orm import sessionmaker, Session

# Add parent dir to path for config import
sys.path.insert(0, str(Path(__file__).parent.parent))
import config
from database.models import Base, Article, ExtractedKnowledge, TextbookSection, WeeklyReport, AuthorAnalytics


class DBManager:
    """Manages all database operations for the SBMA research database."""

    def __init__(self, db_path: Optional[Path] = None):
        db_path = db_path or config.DATABASE_PATH
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.engine = create_engine(f"sqlite:///{db_path}", echo=False)
        Base.metadata.create_all(self.engine)
        self.SessionLocal = sessionmaker(bind=self.engine)

    def get_session(self) -> Session:
        return self.SessionLocal()

    # --- Article CRUD ---

    def upsert_article(self, data: dict) -> Article:
        """Insert or update an article by PMID."""
        session = self.get_session()
        try:
            article = session.get(Article, data["pmid"])
            if article:
                for key, value in data.items():
                    if value is not None:
                        setattr(article, key, value)
                article.date_last_updated = datetime.utcnow()
            else:
                data.setdefault("date_added_to_db", datetime.utcnow())
                data.setdefault("date_last_updated", datetime.utcnow())
                article = Article(**data)
                session.add(article)
            session.commit()
            session.refresh(article)
            return article
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def upsert_articles_bulk(self, articles_data: list[dict]) -> int:
        """Bulk upsert articles. Returns count of articles upserted."""
        session = self.get_session()
        count = 0
        try:
            for data in articles_data:
                existing = session.get(Article, data["pmid"])
                if existing:
                    for key, value in data.items():
                        if value is not None:
                            setattr(existing, key, value)
                    existing.date_last_updated = datetime.utcnow()
                else:
                    data.setdefault("date_added_to_db", datetime.utcnow())
                    data.setdefault("date_last_updated", datetime.utcnow())
                    session.add(Article(**data))
                count += 1
            session.commit()
            return count
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def get_article(self, pmid: str) -> Optional[Article]:
        session = self.get_session()
        try:
            return session.get(Article, pmid)
        finally:
            session.close()

    def get_all_pmids(self) -> list[str]:
        session = self.get_session()
        try:
            return [r[0] for r in session.query(Article.pmid).all()]
        finally:
            session.close()

    def get_articles_chronological(self) -> list[Article]:
        """Return all articles sorted by publication date ascending."""
        session = self.get_session()
        try:
            return (
                session.query(Article)
                .order_by(Article.publication_date.asc())
                .all()
            )
        finally:
            session.close()

    def get_article_count(self) -> int:
        session = self.get_session()
        try:
            return session.query(func.count(Article.pmid)).scalar()
        finally:
            session.close()

    def get_articles_without_enrichment(self, source: str) -> list[Article]:
        """Get articles missing citation data (citation_count is 0 or None)."""
        session = self.get_session()
        try:
            return (
                session.query(Article)
                .filter(
                    (Article.citation_count == None) | (Article.citation_count == 0)
                )
                .all()
            )
        finally:
            session.close()

    def get_articles_by_year(self) -> dict[int, int]:
        """Return {year: count} for all articles."""
        session = self.get_session()
        try:
            rows = (
                session.query(Article.publication_year, func.count(Article.pmid))
                .group_by(Article.publication_year)
                .order_by(Article.publication_year)
                .all()
            )
            return {year: count for year, count in rows if year}
        finally:
            session.close()

    def get_top_authors(self, limit: int = 20) -> list[tuple[str, int]]:
        """Get top authors by publication count (requires computing from JSON)."""
        session = self.get_session()
        try:
            articles = session.query(Article.authors).all()
            author_counts: dict[str, int] = {}
            for (authors_json,) in articles:
                if not authors_json:
                    continue
                for author in authors_json:
                    name = author.get("name", "") if isinstance(author, dict) else str(author)
                    if name:
                        author_counts[name] = author_counts.get(name, 0) + 1
            sorted_authors = sorted(author_counts.items(), key=lambda x: x[1], reverse=True)
            return sorted_authors[:limit]
        finally:
            session.close()

    def get_top_journals(self, limit: int = 10) -> list[tuple[str, int]]:
        """Get top journals by article count."""
        session = self.get_session()
        try:
            rows = (
                session.query(Article.journal, func.count(Article.pmid))
                .group_by(Article.journal)
                .order_by(func.count(Article.pmid).desc())
                .limit(limit)
                .all()
            )
            return [(j, c) for j, c in rows if j]
        finally:
            session.close()

    def get_article_type_distribution(self) -> dict[str, int]:
        """Return {article_type: count}."""
        session = self.get_session()
        try:
            rows = (
                session.query(Article.article_type, func.count(Article.pmid))
                .group_by(Article.article_type)
                .all()
            )
            return {t or "unknown": c for t, c in rows}
        finally:
            session.close()

    def get_fulltext_count(self) -> int:
        session = self.get_session()
        try:
            return session.query(func.count(Article.pmid)).filter(Article.fulltext_available == True).scalar()
        finally:
            session.close()

    # --- Extracted Knowledge CRUD ---

    def add_extracted_knowledge(self, data: dict) -> ExtractedKnowledge:
        session = self.get_session()
        try:
            ek = ExtractedKnowledge(**data)
            session.add(ek)
            session.commit()
            session.refresh(ek)
            return ek
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def get_knowledge_for_article(self, pmid: str) -> list[ExtractedKnowledge]:
        session = self.get_session()
        try:
            return session.query(ExtractedKnowledge).filter_by(pmid=pmid).all()
        finally:
            session.close()

    def get_all_knowledge_by_type(self, knowledge_type: str) -> list[ExtractedKnowledge]:
        session = self.get_session()
        try:
            return session.query(ExtractedKnowledge).filter_by(knowledge_type=knowledge_type).all()
        finally:
            session.close()

    def get_processed_pmids(self) -> set[str]:
        """Return set of PMIDs that already have extracted knowledge."""
        session = self.get_session()
        try:
            rows = session.query(ExtractedKnowledge.pmid).distinct().all()
            return {r[0] for r in rows}
        finally:
            session.close()

    # --- Textbook Section CRUD ---

    def upsert_textbook_section(self, chapter: str, section_title: str,
                                 content: str, contributing_pmids: list[str]) -> TextbookSection:
        session = self.get_session()
        try:
            existing = (
                session.query(TextbookSection)
                .filter_by(chapter=chapter, section_title=section_title)
                .first()
            )
            if existing:
                existing.content = content
                # Merge PMIDs
                old_pmids = set(existing.contributing_pmids or [])
                old_pmids.update(contributing_pmids)
                existing.contributing_pmids = list(old_pmids)
                existing.version = (existing.version or 0) + 1
                existing.last_updated = datetime.utcnow()
                section = existing
            else:
                section = TextbookSection(
                    chapter=chapter,
                    section_title=section_title,
                    content=content,
                    contributing_pmids=contributing_pmids,
                    version=1,
                )
                session.add(section)
            session.commit()
            session.refresh(section)
            return section
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def get_textbook_sections(self) -> list[TextbookSection]:
        """Return all textbook sections ordered by chapter."""
        session = self.get_session()
        try:
            return session.query(TextbookSection).order_by(TextbookSection.chapter).all()
        finally:
            session.close()

    def get_textbook_as_dict(self) -> dict[str, str]:
        """Return {chapter: content} for the entire textbook."""
        session = self.get_session()
        try:
            sections = session.query(TextbookSection).order_by(TextbookSection.chapter).all()
            result = {}
            for s in sections:
                key = f"{s.chapter} - {s.section_title}" if s.section_title else s.chapter
                result[key] = s.content or ""
            return result
        finally:
            session.close()

    # --- Weekly Report CRUD ---

    def add_weekly_report(self, data: dict) -> WeeklyReport:
        session = self.get_session()
        try:
            report = WeeklyReport(**data)
            session.add(report)
            session.commit()
            session.refresh(report)
            return report
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def get_latest_report(self) -> Optional[WeeklyReport]:
        session = self.get_session()
        try:
            return (
                session.query(WeeklyReport)
                .order_by(WeeklyReport.report_date.desc())
                .first()
            )
        finally:
            session.close()

    # --- Author Analytics CRUD ---

    def upsert_author_analytics(self, data: dict) -> AuthorAnalytics:
        session = self.get_session()
        try:
            existing = (
                session.query(AuthorAnalytics)
                .filter_by(author_name=data["author_name"])
                .first()
            )
            if existing:
                for key, value in data.items():
                    setattr(existing, key, value)
                author = existing
            else:
                author = AuthorAnalytics(**data)
                session.add(author)
            session.commit()
            session.refresh(author)
            return author
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def get_all_author_analytics(self) -> list[AuthorAnalytics]:
        session = self.get_session()
        try:
            return (
                session.query(AuthorAnalytics)
                .order_by(AuthorAnalytics.total_papers.desc())
                .all()
            )
        finally:
            session.close()

    # --- Dashboard read-only methods ---

    def get_knowledge_count(self) -> int:
        """Total extracted knowledge entries."""
        session = self.get_session()
        try:
            return session.query(func.count(ExtractedKnowledge.id)).scalar() or 0
        finally:
            session.close()

    def get_knowledge_type_counts(self) -> dict[str, int]:
        """Return {knowledge_type: count}."""
        session = self.get_session()
        try:
            rows = (
                session.query(ExtractedKnowledge.knowledge_type, func.count(ExtractedKnowledge.id))
                .group_by(ExtractedKnowledge.knowledge_type)
                .all()
            )
            return {t or "unknown": c for t, c in rows}
        finally:
            session.close()

    def get_knowledge_browse(self, knowledge_type: Optional[str] = None,
                             limit: int = 50, offset: int = 0) -> list[ExtractedKnowledge]:
        """Paginated knowledge browsing, optionally filtered by type."""
        session = self.get_session()
        try:
            q = session.query(ExtractedKnowledge)
            if knowledge_type:
                q = q.filter_by(knowledge_type=knowledge_type)
            return q.order_by(ExtractedKnowledge.id.desc()).offset(offset).limit(limit).all()
        finally:
            session.close()

    def get_top_cited_articles(self, limit: int = 50) -> list[Article]:
        """Articles sorted by citation_count descending."""
        session = self.get_session()
        try:
            return (
                session.query(Article)
                .filter(Article.citation_count != None, Article.citation_count > 0)
                .order_by(Article.citation_count.desc())
                .limit(limit)
                .all()
            )
        finally:
            session.close()

    def get_topic_evolution_data(self) -> dict[str, dict[str, int]]:
        """Return {decade: {mesh_term: count}} for topic evolution heatmap."""
        session = self.get_session()
        try:
            articles = session.query(Article.publication_year, Article.mesh_terms).all()
            decades: dict[str, dict[str, int]] = {}
            for year, mesh_terms in articles:
                if not year or not mesh_terms:
                    continue
                decade = f"{(year // 10) * 10}s"
                if decade not in decades:
                    decades[decade] = {}
                for term in mesh_terms:
                    if isinstance(term, str) and term:
                        decades[decade][term] = decades[decade].get(term, 0) + 1
            return decades
        finally:
            session.close()

    def get_article_types_by_year(self) -> dict[int, dict[str, int]]:
        """Return {year: {article_type: count}} for stacked bar chart."""
        session = self.get_session()
        try:
            rows = (
                session.query(Article.publication_year, Article.article_type, func.count(Article.pmid))
                .group_by(Article.publication_year, Article.article_type)
                .order_by(Article.publication_year)
                .all()
            )
            result: dict[int, dict[str, int]] = {}
            for year, atype, count in rows:
                if not year:
                    continue
                if year not in result:
                    result[year] = {}
                result[year][atype or "unknown"] = count
            return result
        finally:
            session.close()

    def get_all_weekly_reports(self) -> list[WeeklyReport]:
        """All weekly reports, newest first."""
        session = self.get_session()
        try:
            return (
                session.query(WeeklyReport)
                .order_by(WeeklyReport.report_date.desc())
                .all()
            )
        finally:
            session.close()

    def get_weekly_report_by_id(self, report_id: int) -> Optional[WeeklyReport]:
        """Single weekly report by ID."""
        session = self.get_session()
        try:
            return session.get(WeeklyReport, report_id)
        finally:
            session.close()
