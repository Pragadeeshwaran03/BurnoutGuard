-- ============================================================
-- AI-POWERED DIGITAL BURNOUT DETECTION SYSTEM
-- Database Schema - MySQL
-- Author: PRAGADEESHWARAN K | Reg: 730924632031
-- ============================================================

CREATE DATABASE IF NOT EXISTS burnout_detection;
USE burnout_detection;

-- Users Table
CREATE TABLE users (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    email VARCHAR(150) UNIQUE NOT NULL,
    password VARCHAR(255) NOT NULL,
    role ENUM('USER', 'ADMIN') DEFAULT 'USER',
    department VARCHAR(100),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
);

-- Work Sessions Table
CREATE TABLE work_sessions (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    user_id BIGINT NOT NULL,
    session_start TIMESTAMP NOT NULL,
    session_end TIMESTAMP,
    duration_minutes INT DEFAULT 0,
    tasks_completed INT DEFAULT 0,
    break_count INT DEFAULT 0,
    idle_time_minutes INT DEFAULT 0,
    screen_active_minutes INT DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

-- Burnout Risk Records Table
CREATE TABLE burnout_records (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    user_id BIGINT NOT NULL,
    risk_level ENUM('LOW', 'MEDIUM', 'HIGH') NOT NULL,
    risk_score FLOAT NOT NULL,
    avg_daily_hours FLOAT,
    avg_break_frequency FLOAT,
    task_completion_rate FLOAT,
    overtime_days INT,
    consecutive_work_days INT,
    predicted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

-- Recommendations Table
CREATE TABLE recommendations (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    user_id BIGINT NOT NULL,
    burnout_record_id BIGINT,
    recommendation_text TEXT NOT NULL,
    category ENUM('BREAK', 'WELLNESS', 'WORKLOAD', 'LIFESTYLE') NOT NULL,
    is_read BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY (burnout_record_id) REFERENCES burnout_records(id) ON DELETE SET NULL
);

-- Behavioral Metrics Table
CREATE TABLE behavioral_metrics (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    user_id BIGINT NOT NULL,
    metric_date DATE NOT NULL,
    total_work_hours FLOAT DEFAULT 0,
    break_count INT DEFAULT 0,
    avg_session_length FLOAT DEFAULT 0,
    tasks_submitted INT DEFAULT 0,
    late_night_sessions INT DEFAULT 0,
    weekend_work_days INT DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

-- Sample Admin User
INSERT INTO users (name, email, password, role, department) VALUES
('Admin User', 'admin@burnout.com', '$2a$10$XqtroC5sX4TnpJGT5L9rBeZcq1gvUJMJx5T9gJhMc5tOp3RuK6PeK', 'ADMIN', 'IT'),
('Pragadeeshwaran K', 'praga@burnout.com', '$2a$10$XqtroC5sX4TnpJGT5L9rBeZcq1gvUJMJx5T9gJhMc5tOp3RuK6PeK', 'USER', 'MCA');
-- Default password: admin123 (BCrypt encoded)
