-- ============================================================
-- Activity Tracking Migration
-- Run this to add the activity_logs table
-- ============================================================

USE burnout_detection;

CREATE TABLE IF NOT EXISTS activity_logs (
    id                      BIGINT AUTO_INCREMENT PRIMARY KEY,
    user_id                 BIGINT NOT NULL,
    total_active_time       BIGINT DEFAULT 0  COMMENT 'seconds user was actively typing/clicking',
    total_idle_time         BIGINT DEFAULT 0  COMMENT 'seconds user was idle',
    keyboard_activity_count BIGINT DEFAULT 0  COMMENT 'total keydown events',
    mouse_activity_count    BIGINT DEFAULT 0  COMMENT 'total throttled mousemove events',
    screen_time             BIGINT DEFAULT 0  COMMENT 'seconds tab was visible/focused',
    session_start           TIMESTAMP NULL,
    session_end             TIMESTAMP NULL,
    logged_at               TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    INDEX idx_user_logged (user_id, logged_at)
);
