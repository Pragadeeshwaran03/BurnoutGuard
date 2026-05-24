# 🧠 AI-Powered Digital Burnout Detection & Workload Balancing System

**Author:** PRAGADEESHWARAN K  
**Reg No:** 730924632031  
**Department:** MCA  

---

## 📁 Project Structure

```
FINALYEAR PROJECT/
├── README.md                    ← this file
├── start.ps1                    ← one-command launcher
├── database/
│   ├── schema.sql               ← MySQL database schema
│   ├── seed_admin.py
│   └── seed_admin.sql
├── ml-engine/
│   ├── app.py                   ← Python Flask ML API
│   ├── burnout_model.pkl
│   ├── scaler.pkl
│   └── requirements.txt         ← Python dependencies
├── backend/
│   ├── pom.xml                  ← Maven build file
│   └── src/main/
│       ├── java/com/burnout/
│       │   ├── BurnoutDetectionApplication.java
│       │   ├── controller/      ← REST controllers
│       │   ├── service/         ← Business logic
│       │   ├── model/           ← JPA entities
│       │   ├── repository/      ← Data access
│       │   └── config/          ← Security config
│       └── resources/
│           └── application.properties
└── frontend/
    ├── package.json
    ├── vite.config.js
    └── src/
        ├── App.jsx              ← Full React application
        ├── main.jsx
        └── index.css
```

---

## 🚀 Quick Start (One Command)

```powershell
powershell -ExecutionPolicy Bypass -File start.ps1
```

This installs all dependencies and starts all 3 services automatically.

---

## 🚀 Manual Setup Instructions

### 1. Database Setup (MySQL)

```sql
-- Open MySQL and run:
source database/schema.sql;
```

### 2. Backend Configuration

Edit `backend/src/main/resources/application.properties`:

```properties
spring.datasource.username=root
spring.datasource.password=YOUR_MYSQL_PASSWORD
```

### 3. Run Python ML Engine

```bash
cd ml-engine
pip install -r requirements.txt
python app.py
# ML Engine starts on http://localhost:5001
```

### 4. Run Spring Boot Backend

```bash
cd backend
mvn spring-boot:run
# Backend starts on http://localhost:8080
```

### 5. Run React Frontend

```bash
cd frontend
npm install
npm run dev
# Frontend opens at http://localhost:3000
```

---

## 🔑 Default Login

| Email | Password | Role |
|-------|----------|------|
| admin@burnout.com | admin123 | ADMIN |
| praga@burnout.com | admin123 | USER |

---

## 🌐 API Endpoints

### Auth
| Method | URL | Description |
|--------|-----|-------------|
| POST | /api/auth/register | Register new user |
| POST | /api/auth/login | Login |
| GET | /api/auth/me | Get current user |

### Burnout
| Method | URL | Description |
|--------|-----|-------------|
| POST | /api/burnout/predict | Predict burnout risk |
| GET | /api/burnout/history | Get user history |
| GET | /api/burnout/latest | Get latest record |
| GET | /api/burnout/admin/overview | Admin team overview |

### ML Engine
| Method | URL | Description |
|--------|-----|-------------|
| GET | /health | Health check |
| POST | /predict | Single prediction |
| POST | /batch-predict | Batch prediction |

---

## 🤖 ML Model Details

- **Algorithm:** Gradient Boosting Classifier (Scikit-learn)
- **Features:** 8 behavioral metrics
- **Output:** LOW / MEDIUM / HIGH risk with confidence probabilities
- **Accuracy:** ~92%+ on synthetic test data

### Input Features
| Feature | Description |
|---------|-------------|
| avg_daily_hours | Average work hours per day |
| break_frequency | Number of breaks per day |
| task_completion_rate | % tasks completed (0.0–1.0) |
| overtime_days | Overtime days in last 30 days |
| consecutive_work_days | Max consecutive days worked |
| late_night_sessions | Sessions after 10 PM (last 30 days) |
| weekend_work_days | Weekend days worked (last 30 days) |
| avg_session_length | Average uninterrupted session (minutes) |

---

## 🧩 System Architecture

```
User Browser (React :3000)
       ↓
Spring Boot Backend (Port 8080)
       ↓              ↓
   MySQL DB     Python ML Engine (Port 5001)
                       ↓
              GradientBoostingClassifier
                       ↓
            Risk Level + Recommendations
```

---

## 📊 Modules

1. **User Management** – Registration, Login, JWT Auth, Role-Based Access
2. **Behavioral Data Collection** – Work session tracking via sliders/API
3. **ML Burnout Prediction** – Gradient Boosting 3-class classifier
4. **Recommendation Engine** – Personalized wellness suggestions
5. **Workload Balancing** – Admin insights on team cognitive load
6. **User Dashboard** – Risk score, history, wellness tips
7. **Admin Dashboard** – Team overview, user risk table, reports
8. **Privacy & Security** – BCrypt passwords, JWT tokens, CORS

---

## 🛠 Tech Stack

| Layer | Technology |
|-------|-----------| 
| Frontend | React.js 18, Vite, HTML/CSS/JS |
| Backend | Java 17, Spring Boot 3.2 |
| ML Engine | Python 3.10+, Flask, Scikit-learn |
| Database | MySQL 8.0 |
| Auth | JWT (JJWT 0.12) + BCrypt |
| Build | Maven, npm |
