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
    extraction_date TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (pmid, knowledge_type, summary)
);

-- Textbook sections
CREATE TABLE IF NOT EXISTS textbook_sections (
    id SERIAL PRIMARY KEY,
    chapter TEXT,
    section_title TEXT,
    content TEXT,
    contributing_pmids JSONB DEFAULT '[]',
    version INTEGER DEFAULT 1,
    last_updated TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (chapter, section_title)
);

-- Textbook version history (archival of previous chapter content)
CREATE TABLE IF NOT EXISTS textbook_versions (
    id SERIAL PRIMARY KEY,
    chapter TEXT NOT NULL,
    section_title TEXT NOT NULL,
    content TEXT,
    contributing_pmids JSONB DEFAULT '[]',
    version INTEGER NOT NULL,
    model_used TEXT,
    synthesized_at TIMESTAMPTZ DEFAULT NOW()
);

-- Weekly reports
CREATE TABLE IF NOT EXISTS weekly_reports (
    id SERIAL PRIMARY KEY,
    report_date DATE UNIQUE,
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

-- Monthly newsletters
CREATE TABLE IF NOT EXISTS monthly_newsletters (
    id SERIAL PRIMARY KEY,
    period_label TEXT UNIQUE NOT NULL,          -- e.g. "March 2026"
    period_start DATE,
    period_end DATE,
    new_articles_count INTEGER DEFAULT 0,
    article_pmids JSONB DEFAULT '[]',           -- [pmid, ...]
    clinical_trials_json JSONB DEFAULT '[]',    -- [{nct_id, title, status, ...}, ...]
    content_markdown TEXT,                       -- full AI-written newsletter
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Co-authorship network edges
CREATE TABLE IF NOT EXISTS coauthorship_edges (
    id SERIAL PRIMARY KEY,
    author1 TEXT NOT NULL,
    author2 TEXT NOT NULL,
    weight INTEGER DEFAULT 1,
    UNIQUE (author1, author2)
);

-- Textbook comments (reader feedback per chapter)
CREATE TABLE IF NOT EXISTS textbook_comments (
    id SERIAL PRIMARY KEY,
    chapter TEXT NOT NULL,
    author_name TEXT NOT NULL,
    author_email TEXT,
    comment_text TEXT NOT NULL,
    comment_type TEXT DEFAULT 'comment' CHECK (comment_type IN ('comment', 'correction', 'question')),
    parent_id INTEGER REFERENCES textbook_comments(id),
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_articles_year ON articles(publication_year);
CREATE INDEX IF NOT EXISTS idx_articles_type ON articles(article_type);
CREATE INDEX IF NOT EXISTS idx_articles_journal ON articles(journal);
CREATE INDEX IF NOT EXISTS idx_knowledge_pmid ON extracted_knowledge(pmid);
CREATE INDEX IF NOT EXISTS idx_knowledge_type ON extracted_knowledge(knowledge_type);
CREATE INDEX IF NOT EXISTS idx_textbook_chapter ON textbook_sections(chapter);
CREATE INDEX IF NOT EXISTS idx_newsletters_period ON monthly_newsletters(period_start DESC);
CREATE INDEX IF NOT EXISTS idx_comments_chapter ON textbook_comments(chapter);
CREATE INDEX IF NOT EXISTS idx_comments_parent ON textbook_comments(parent_id);
CREATE INDEX IF NOT EXISTS idx_textbook_versions_chapter ON textbook_versions(chapter);
CREATE INDEX IF NOT EXISTS idx_coauthorship_authors ON coauthorship_edges(author1, author2);

-- Enable Row Level Security but allow public read access
ALTER TABLE articles ENABLE ROW LEVEL SECURITY;
ALTER TABLE extracted_knowledge ENABLE ROW LEVEL SECURITY;
ALTER TABLE textbook_sections ENABLE ROW LEVEL SECURITY;
ALTER TABLE weekly_reports ENABLE ROW LEVEL SECURITY;
ALTER TABLE authors_analytics ENABLE ROW LEVEL SECURITY;
ALTER TABLE stats_overview ENABLE ROW LEVEL SECURITY;
ALTER TABLE gap_analysis ENABLE ROW LEVEL SECURITY;
ALTER TABLE coauthorship_edges ENABLE ROW LEVEL SECURITY;
ALTER TABLE monthly_newsletters ENABLE ROW LEVEL SECURITY;

-- RLS for textbook_comments and textbook_versions
ALTER TABLE textbook_comments ENABLE ROW LEVEL SECURITY;
ALTER TABLE textbook_versions ENABLE ROW LEVEL SECURITY;

-- Public read-only policies
DROP POLICY IF EXISTS "Public read" ON articles;
CREATE POLICY "Public read" ON articles FOR SELECT USING (true);

DROP POLICY IF EXISTS "Public read" ON extracted_knowledge;
CREATE POLICY "Public read" ON extracted_knowledge FOR SELECT USING (true);

DROP POLICY IF EXISTS "Public read" ON textbook_sections;
CREATE POLICY "Public read" ON textbook_sections FOR SELECT USING (true);

DROP POLICY IF EXISTS "Public read" ON weekly_reports;
CREATE POLICY "Public read" ON weekly_reports FOR SELECT USING (true);

DROP POLICY IF EXISTS "Public read" ON authors_analytics;
CREATE POLICY "Public read" ON authors_analytics FOR SELECT USING (true);

DROP POLICY IF EXISTS "Public read" ON stats_overview;
CREATE POLICY "Public read" ON stats_overview FOR SELECT USING (true);

DROP POLICY IF EXISTS "Public read" ON gap_analysis;
CREATE POLICY "Public read" ON gap_analysis FOR SELECT USING (true);

DROP POLICY IF EXISTS "Public read" ON coauthorship_edges;
CREATE POLICY "Public read" ON coauthorship_edges FOR SELECT USING (true);

DROP POLICY IF EXISTS "Public read" ON monthly_newsletters;
CREATE POLICY "Public read" ON monthly_newsletters FOR SELECT USING (true);

DROP POLICY IF EXISTS "Public read" ON textbook_comments;
CREATE POLICY "Public read" ON textbook_comments FOR SELECT USING (true);

DROP POLICY IF EXISTS "Public read" ON textbook_versions;
CREATE POLICY "Public read" ON textbook_versions FOR SELECT USING (true);

-- Allow anyone to insert comments (with anon key)
DROP POLICY IF EXISTS "Public insert" ON textbook_comments;
CREATE POLICY "Public insert" ON textbook_comments FOR INSERT WITH CHECK (true);
