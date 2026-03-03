-- Run this in the Supabase SQL Editor to create all tables

-- Articles table
CREATE TABLE IF NOT EXISTS articles (
    pmid TEXT PRIMARY KEY,
    doi TEXT,
    title TEXT,
    abstract TEXT,
    authors JSONB DEFAULT '[]',
    journal TEXT,
    publication_year INTEGER,
    article_type TEXT,
    citation_count INTEGER DEFAULT 0,
    keywords JSONB DEFAULT '[]',
    mesh_terms JSONB DEFAULT '[]',
    fulltext_available BOOLEAN DEFAULT FALSE
);

-- Extracted knowledge
CREATE TABLE IF NOT EXISTS extracted_knowledge (
    id SERIAL PRIMARY KEY,
    pmid TEXT REFERENCES articles(pmid),
    knowledge_type TEXT,
    summary TEXT,
    details TEXT,
    confidence REAL,
    novelty_at_publication TEXT,
    extraction_date TIMESTAMPTZ DEFAULT NOW()
);

-- Textbook sections
CREATE TABLE IF NOT EXISTS textbook_sections (
    id SERIAL PRIMARY KEY,
    chapter TEXT,
    section_title TEXT,
    content TEXT,
    contributing_pmids JSONB DEFAULT '[]',
    version INTEGER DEFAULT 1,
    last_updated TIMESTAMPTZ DEFAULT NOW()
);

-- Weekly reports
CREATE TABLE IF NOT EXISTS weekly_reports (
    id SERIAL PRIMARY KEY,
    report_date DATE,
    new_articles_found INTEGER DEFAULT 0,
    summary TEXT,
    novelty_analysis TEXT
);

-- Author analytics
CREATE TABLE IF NOT EXISTS authors_analytics (
    author_name TEXT PRIMARY KEY,
    total_papers INTEGER DEFAULT 0,
    first_author_papers INTEGER DEFAULT 0,
    last_author_papers INTEGER DEFAULT 0,
    h_index_in_field INTEGER DEFAULT 0,
    affiliations JSONB DEFAULT '[]',
    active_years TEXT
);

-- Pre-computed stats for the dashboard
CREATE TABLE IF NOT EXISTS stats_overview (
    id INTEGER PRIMARY KEY DEFAULT 1,
    total_articles INTEGER,
    total_knowledge INTEGER,
    total_fulltext INTEGER,
    articles_by_year JSONB,
    article_type_distribution JSONB,
    top_journals JSONB,
    top_authors JSONB,
    topic_evolution JSONB,
    processing_progress JSONB,
    last_updated TIMESTAMPTZ DEFAULT NOW()
);

-- Gap analysis
CREATE TABLE IF NOT EXISTS gap_analysis (
    id SERIAL PRIMARY KEY,
    content TEXT,
    raw_json JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_articles_year ON articles(publication_year);
CREATE INDEX IF NOT EXISTS idx_articles_type ON articles(article_type);
CREATE INDEX IF NOT EXISTS idx_articles_journal ON articles(journal);
CREATE INDEX IF NOT EXISTS idx_knowledge_pmid ON extracted_knowledge(pmid);
CREATE INDEX IF NOT EXISTS idx_knowledge_type ON extracted_knowledge(knowledge_type);
CREATE INDEX IF NOT EXISTS idx_textbook_chapter ON textbook_sections(chapter);

-- Enable Row Level Security but allow public read access
ALTER TABLE articles ENABLE ROW LEVEL SECURITY;
ALTER TABLE extracted_knowledge ENABLE ROW LEVEL SECURITY;
ALTER TABLE textbook_sections ENABLE ROW LEVEL SECURITY;
ALTER TABLE weekly_reports ENABLE ROW LEVEL SECURITY;
ALTER TABLE authors_analytics ENABLE ROW LEVEL SECURITY;
ALTER TABLE stats_overview ENABLE ROW LEVEL SECURITY;
ALTER TABLE gap_analysis ENABLE ROW LEVEL SECURITY;

-- Public read-only policies
CREATE POLICY "Public read" ON articles FOR SELECT USING (true);
CREATE POLICY "Public read" ON extracted_knowledge FOR SELECT USING (true);
CREATE POLICY "Public read" ON textbook_sections FOR SELECT USING (true);
CREATE POLICY "Public read" ON weekly_reports FOR SELECT USING (true);
CREATE POLICY "Public read" ON authors_analytics FOR SELECT USING (true);
CREATE POLICY "Public read" ON stats_overview FOR SELECT USING (true);
CREATE POLICY "Public read" ON gap_analysis FOR SELECT USING (true);
