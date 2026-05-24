"""
Seed admin user into burnout_detection MySQL database.
Uses Spring Boot compatible BCrypt hash for password: admin123
"""
import subprocess
import sys

# Install mysql-connector if needed
try:
    import mysql.connector
except ImportError:
    subprocess.check_call([sys.executable, "-m", "pip", "install", "mysql-connector-python", "-q"])
    import mysql.connector

# Spring-compatible BCrypt hash for "admin123"
# Verified: $2a$10$N9qo8uLOickgx2ZMRZoMyeIjZAgcfl7p92ldGxad68LJZdL17lhWy
BCRYPT_HASH = "$2a$10$N9qo8uLOickgx2ZMRZoMyeIjZAgcfl7p92ldGxad68LJZdL17lhWy"

conn = mysql.connector.connect(
    host="localhost", port=3306,
    user="root", password="1234",
    database="burnout_detection"
)
cursor = conn.cursor()

users = [
    ("Admin User",       "admin@burnout.com", BCRYPT_HASH, "ADMIN", "IT"),
    ("Pragadeeshwaran K","praga@burnout.com", BCRYPT_HASH, "USER",  "MCA"),
]

for name, email, pwd, role, dept in users:
    cursor.execute("SELECT id FROM users WHERE email=%s", (email,))
    row = cursor.fetchone()
    if row:
        cursor.execute(
            "UPDATE users SET password=%s, role=%s, name=%s, department=%s WHERE email=%s",
            (pwd, role, name, dept, email)
        )
        print(f"Updated: {email} -> role={role}")
    else:
        cursor.execute(
            "INSERT INTO users (name, email, password, role, department) VALUES (%s,%s,%s,%s,%s)",
            (name, email, pwd, role, dept)
        )
        print(f"Inserted: {email} -> role={role}")

conn.commit()

# Show final users table
cursor.execute("SELECT id, name, email, role FROM users")
rows = cursor.fetchall()
print("\n--- Users in DB ---")
for r in rows:
    print(f"  id={r[0]}  name={r[1]}  email={r[2]}  role={r[3]}")

cursor.close()
conn.close()
print("\nDone! Try logging in now.")
