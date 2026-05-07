-- Migration: add unique constraints for idempotent upserts + textbook versioning
-- Run this in Supabase SQL Editor on existing databases.
-- Safe to run multiple times (IF NOT EXISTS).

-- 1. Unique constraint on extracted_knowledge for upsert conflict target
ALTER TABLE extracted_knowledge
    ADD CONSTRAINT uq_knowledge_pmid_type_summary UNIQUE (pmid, knowledge_type, summary);

-- 2. Unique constraint on textbook_sections
ALTER TABLE textbook_sections
    ADD CONSTRAINT uq_textbook_chapter_section UNIQUE (chapter, section_title);

-- 3. Unique constraint on weekly_reports
ALTER TABLE weekly_reports
    ADD CONSTRAINT uq_weekly_report_date UNIQUE (report_date);

-- 4. Unique constraint on coauthorship_edges
ALTER TABLE coauthorship_edges
    ADD CONSTRAINT uq_coauthorship_pair UNIQUE (author1, author2);

-- 5. Textbook version history table
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

CREATE INDEX IF NOT EXISTS idx_textbook_versions_chapter ON textbook_versions(chapter);
CREATE INDEX IF NOT EXISTS idx_coauthorship_authors ON coauthorship_edges(author1, author2);

-- 6. RLS + public read for textbook_versions
ALTER TABLE textbook_versions ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Public read" ON textbook_versions FOR SELECT USING (true);
