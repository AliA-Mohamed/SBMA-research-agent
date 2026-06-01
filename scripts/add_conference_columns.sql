-- Migration: add JSON columns for future and recent conferences to the monthly_newsletters table
-- Run this in the Supabase SQL Editor

ALTER TABLE monthly_newsletters
ADD COLUMN IF NOT EXISTS future_conferences_json JSONB DEFAULT '[]',
ADD COLUMN IF NOT EXISTS recent_conferences_json JSONB DEFAULT '[]';
