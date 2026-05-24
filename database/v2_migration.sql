-- ============================================================
-- Migration: v2.0 — Add missing columns to burnout_records
-- Run this ONCE against your existing database.
-- Safe to run multiple times (uses IF NOT EXISTS checks).
-- ============================================================

USE burnout_detection;

ALTER TABLE burnout_records
    ADD COLUMN IF NOT EXISTS late_night_sessions  INT          DEFAULT NULL COMMENT 'Sessions after 10 PM in last 30 days',
    ADD COLUMN IF NOT EXISTS weekend_work_days    INT          DEFAULT NULL COMMENT 'Weekend days worked in last 30 days',
    ADD COLUMN IF NOT EXISTS avg_session_length   FLOAT        DEFAULT NULL COMMENT 'Average uninterrupted session in minutes',
    ADD COLUMN IF NOT EXISTS wellness_score       FLOAT        DEFAULT NULL COMMENT 'Composite 0-100 wellness score from ML engine';

-- Verify
DESCRIBE burnout_records;
