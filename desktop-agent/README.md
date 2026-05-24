# BurnoutGuard Desktop Background Agent

A Python background agent that tracks keyboard/mouse activity, detects idle time, and sends activity data to the BurnoutGuard Spring Boot backend every 60 seconds.

---

## Architecture

```
┌─────────────────────────────────────────────────────┐
│            Desktop Background Agent                 │
│                                                     │
│  tracker.py  ──► activity counters + idle detection │
│  sender.py   ──► JWT auth + HTTP POST + offline queue│
│  agent.py    ──► scheduler + shutdown logic         │
│  config.json ──► user credentials + tuning          │
└──────────────────┬──────────────────────────────────┘
                   │  POST /api/activity/log
                   │  every 60 seconds
                   ▼
        Spring Boot REST API (:8080)
                   │
                   ▼
         MySQL  ──► ActivityLog table
```

---

## Files

| File | Purpose |
|------|---------|
| `agent.py` | Main entry point — scheduler, logging, graceful shutdown |
| `tracker.py` | Keyboard/mouse listener — idle detection, activity counters |
| `sender.py` | JWT login, HTTP POST, offline queue (saves to disk if backend is down) |
| `config.json` | User credentials and settings |
| `install.bat` | One-click installer — installs deps + registers Windows startup task |
| `stop.bat` | Kill the running agent |
| `status.bat` | Check if agent is running, show last log lines |
| `requirements.txt` | Python dependencies |

---

## Quick Start

### Step 1 — Edit `config.json`

```json
{
  "api_url": "http://localhost:8080",
  "email": "your-account@email.com",
  "password": "your-password",
  "send_interval_seconds": 60,
  "idle_threshold_seconds": 120
}
```

> ⚠️ Use the same email/password you registered with in the BurnoutGuard web app.

### Step 2 — Install (one time only)

Double-click **`install.bat`** — it will:
1. Install Python dependencies (`pynput`, `requests`, `schedule`)
2. Register a Windows Task Scheduler job so the agent **auto-starts at login**

### Step 3 — Run now (for testing)

```bat
# Visible (debug mode - shows a console window with live logs)
python agent.py

# Silent (production mode - no window)
start "" pythonw agent.py
```

---

## Management

| Task | Command |
|------|---------|
| Start (silent) | `start "" pythonw agent.py` |
| Start (visible) | `python agent.py` |
| Stop | `stop.bat` |
| Check status | `status.bat` |
| View logs | Open `agent.log` in any text editor |

---

## How It Works

### Activity Tracking (`tracker.py`)
- Uses **pynput** to listen for keyboard keypresses and mouse events
- Mouse moves are **throttled to 1 event/second** to avoid noise
- All counters are **thread-safe** (protected by `threading.Lock`)
- Uses **monotonic clock** (immune to system time changes/NTP jumps)

### Idle Detection
- If there is **no keyboard or mouse activity for ≥ `idle_threshold_seconds`** (default: 120s), the current interval is marked as idle
- The idle threshold is configurable in `config.json`

### Data Sending (`sender.py`)
- Every 60 seconds, sends a JSON snapshot to `POST /api/activity/log`
- **JWT authentication**: logs in once, refreshes token on 401
- **Offline queue**: if the backend is unreachable, snapshots are saved to `offline_queue.json` and automatically flushed when connectivity returns
- Queue is capped at 1440 entries (~24h at 60s intervals)

### Startup (`install.bat` + Task Scheduler)
- Registers a Windows Task Scheduler job that runs at **user login** with a 1-minute delay
- No admin rights required
- Uses `pythonw.exe` (silent — no console window)

---

## Payload Format

Each snapshot sent to the API:

```json
{
  "totalActiveTime":       45,
  "totalIdleTime":          0,
  "keyboardActivityCount": 87,
  "mouseActivityCount":    23,
  "screenTime":            45,
  "sessionStart": "2026-03-22T09:00:00",
  "sessionEnd":   "2026-03-22T09:01:00"
}
```

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| `Authentication failed` | Check email/password in `config.json`. Make sure the backend is running on port 8080. |
| `No module named pynput` | Run `pip install -r requirements.txt` |
| Task not auto-starting | Re-run `install.bat`; check Task Scheduler → `BurnoutGuardAgent` |
| Agent crashes silently | Open `agent.log` to see the error |
| Backend unreachable | Agent queues data in `offline_queue.json`; it will send when backend is back |
