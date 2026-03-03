"""SQLAlchemy models for the SBMA Research database."""

from datetime import datetime, date
from sqlalchemy import (
    Column, String, Integer, Float, Boolean, Text, Date, DateTime,
    ForeignKey, JSON, create_engine
)
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


class Article(Base):
    __tablename__ = "articles"

    pmid = Column(String, primary_key=True)
    doi = Column(String, index=True)
    title = Column(Text)
    abstract = Column(Text)
    authors = Column(JSON)  # [{"name": "", "affiliation": "", "orcid": ""}]
    journal = Column(String)
    publication_date = Column(Date)
    publication_year = Column(Integer, index=True)
    volume = Column(String)
    issue = Column(String)
    pages = Column(String)
    keywords = Column(JSON)  # [str]
    mesh_terms = Column(JSON)  # [str]
    article_type = Column(String)  # review, original research, case report, clinical trial, etc.
    citation_count = Column(Integer, default=0)
    references = Column(JSON)  # [PMIDs/DOIs]
    cited_by = Column(JSON)  # [PMIDs]
    fulltext_available = Column(Boolean, default=False)
    fulltext_source = Column(String)  # PMC, Unpaywall, etc.
    fulltext_path = Column(String)
    date_added_to_db = Column(DateTime, default=datetime.utcnow)
    date_last_updated = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    extracted_knowledge = relationship(
        "ExtractedKnowledge", back_populates="article", cascade="all, delete-orphan"
    )

    def __repr__(self):
        return f"<Article(pmid={self.pmid}, title={self.title[:60]}...)>"


class ExtractedKnowledge(Base):
    __tablename__ = "extracted_knowledge"

    id = Column(Integer, primary_key=True, autoincrement=True)
    pmid = Column(String, ForeignKey("articles.pmid"), index=True)
    knowledge_type = Column(String, index=True)
    # finding, mechanism, treatment, biomarker, clinical_feature,
    # genetics, epidemiology, model_system, methodology
    summary = Column(Text)
    details = Column(Text)
    confidence = Column(Float)  # 0.0 - 1.0
    novelty_at_publication = Column(Text)
    contradicts = Column(JSON)  # [PMIDs]
    supports = Column(JSON)  # [PMIDs]
    extraction_date = Column(DateTime, default=datetime.utcnow)

    # Relationships
    article = relationship("Article", back_populates="extracted_knowledge")

    def __repr__(self):
        return f"<ExtractedKnowledge(id={self.id}, type={self.knowledge_type}, pmid={self.pmid})>"


class TextbookSection(Base):
    __tablename__ = "textbook_sections"

    id = Column(Integer, primary_key=True, autoincrement=True)
    chapter = Column(String, index=True)
    section_title = Column(String)
    content = Column(Text)
    contributing_pmids = Column(JSON)  # [PMIDs]
    last_updated = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    version = Column(Integer, default=1)

    def __repr__(self):
        return f"<TextbookSection(chapter={self.chapter}, section={self.section_title})>"


class WeeklyReport(Base):
    __tablename__ = "weekly_reports"

    id = Column(Integer, primary_key=True, autoincrement=True)
    report_date = Column(Date, index=True)
    new_articles_found = Column(Integer, default=0)
    articles = Column(JSON)  # [PMIDs]
    summary = Column(Text)
    novelty_analysis = Column(Text)
    report_path = Column(String)

    def __repr__(self):
        return f"<WeeklyReport(date={self.report_date}, new={self.new_articles_found})>"


class AuthorAnalytics(Base):
    __tablename__ = "authors_analytics"

    id = Column(Integer, primary_key=True, autoincrement=True)
    author_name = Column(String, index=True, unique=True)
    total_papers = Column(Integer, default=0)
    first_author_papers = Column(Integer, default=0)
    last_author_papers = Column(Integer, default=0)
    h_index_in_field = Column(Integer, default=0)
    affiliations = Column(JSON)  # [str]
    active_years = Column(String)  # e.g. "1991-2024"

    def __repr__(self):
        return f"<AuthorAnalytics(name={self.author_name}, papers={self.total_papers})>"
