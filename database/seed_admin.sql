-- Seed admin and default user accounts
-- Password for both: admin123 (BCrypt encoded)
USE burnout_detection;

INSERT INTO users (name, email, password, role, department)
VALUES (
    'Admin User',
    'admin@burnout.com',
    '$2a$10$N9qo8uLOickgx2ZMRZoMyeIjZAgcfl7p92ldGxad68LJZdL17lhWy',
    'ADMIN',
    'IT'
)
ON DUPLICATE KEY UPDATE
    password = '$2a$10$N9qo8uLOickgx2ZMRZoMyeIjZAgcfl7p92ldGxad68LJZdL17lhWy',
    role = 'ADMIN';

INSERT INTO users (name, email, password, role, department)
VALUES (
    'Pragadeeshwaran K',
    'praga@burnout.com',
    '$2a$10$N9qo8uLOickgx2ZMRZoMyeIjZAgcfl7p92ldGxad68LJZdL17lhWy',
    'USER',
    'MCA'
)
ON DUPLICATE KEY UPDATE
    password = '$2a$10$N9qo8uLOickgx2ZMRZoMyeIjZAgcfl7p92ldGxad68LJZdL17lhWy',
    role = 'USER';

SELECT id, name, email, role FROM users;
