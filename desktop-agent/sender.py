"""
sender.py  –  BurnoutGuard Desktop Agent
=========================================
Handles JWT authentication and HTTP POST to the Spring Boot API.

Features:
- Auto-retries on 401 (token expiry) by re-logging in once
- Offline queue: if the backend is unreachable, snapshots are saved
  to a local JSON file and flushed when connectivity is restored
- Max queue size: 1440 entries (~24h at 60s intervals) to prevent
  unbounded disk growth
"""

import json
import logging
import os
from datetime import datetime
from pathlib import Path

import requests

log = logging.getLogger("agent.sender")

# ── JWT token cache ────────────────────────────────────────────────────────────
_jwt_token: str | None = None

# ── Offline queue (list of payload dicts) ─────────────────────────────────────
_QUEUE_FILE = Path(__file__).parent / "offline_queue.json"
_MAX_QUEUE_SIZE = 1440   # 24 hours at 60 s interval


# ── Startup: reload any queued payloads from disk ─────────────────────────────
def _load_queue() -> list:
    if _QUEUE_FILE.exists():
        try:
            with open(_QUEUE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    return data
        except Exception as exc:
            log.warning("[QUEUE] Could not read offline queue: %s", exc)
    return []


def _save_queue(queue: list):
    try:
        with open(_QUEUE_FILE, "w", encoding="utf-8") as f:
            json.dump(queue, f)
    except Exception as exc:
        log.warning("[QUEUE] Could not save offline queue: %s", exc)


_offline_queue: list = _load_queue()


# ── Authentication ─────────────────────────────────────────────────────────────
def login(api_url: str, email: str, password: str) -> bool:
    """
    POST /api/auth/login and store the JWT token.
    Returns True on success.
    """
    global _jwt_token
    try:
        resp = requests.post(
            f"{api_url}/api/auth/login",
            json={"email": email, "password": password},
            timeout=10,
        )
        if resp.status_code == 200:
            data = resp.json()
            _jwt_token = data.get("token")
            log.info("[AUTH] Logged in as %s", email)
            return True
        log.error("[AUTH] Login failed %s: %s", resp.status_code, resp.text[:200])
        return False
    except requests.RequestException as exc:
        log.error("[AUTH] Login error: %s", exc)
        return False


# ── Send helper ────────────────────────────────────────────────────────────────
def _post_payload(api_url: str, payload: dict) -> bool:
    """
    POST a single payload to /api/activity/log.
    Returns True on HTTP 200.
    """
    try:
        resp = requests.post(
            f"{api_url}/api/activity/log",
            json=payload,
            headers={"Authorization": f"Bearer {_jwt_token}"},
            timeout=10,
        )
        return resp.status_code == 200, resp
    except requests.RequestException as exc:
        log.error("[SEND] Request error: %s", exc)
        return False, None


# ── Public send function ───────────────────────────────────────────────────────
def send_snapshot(
    api_url: str,
    email: str,
    password: str,
    snapshot: dict,
    session_start_ts: float,
) -> bool:
    """
    Build payload from snapshot and send to /api/activity/log.
    On failure, queues payload locally and flushes queued entries
    when the connection is restored.
    """
    global _jwt_token, _offline_queue

    now = datetime.now()
    session_start_dt = datetime.fromtimestamp(session_start_ts)

    # Window title for admin "Window History" (DB column max 512 chars)
    tab = snapshot.get("activeTab") or "Unknown"
    if isinstance(tab, str) and len(tab) > 500:
        tab = tab[:497] + "..."

    payload = {
        "activeTab":             tab,
        "totalActiveTime":       snapshot.get("totalActiveTime", 0),
        "totalIdleTime":         snapshot.get("totalIdleTime", 0),
        "keyboardActivityCount": snapshot.get("keyboardActivityCount", 0),
        "mouseActivityCount":    snapshot.get("mouseActivityCount", 0),
        "screenTime":            snapshot.get("screenTime", 0),
        "sessionStart":          session_start_dt.strftime("%Y-%m-%dT%H:%M:%S"),
        "sessionEnd":            now.strftime("%Y-%m-%dT%H:%M:%S"),
    }

    # Ensure we have a token
    if _jwt_token is None:
        if not login(api_url, email, password):
            _enqueue(payload)
            return False

    # Try to send
    ok, resp = _post_payload(api_url, payload)

    # Handle 401 — token expired, re-login once
    if resp is not None and resp.status_code == 401:
        log.warning("[SEND] 401 — refreshing token…")
        _jwt_token = None
        if login(api_url, email, password):
            ok, resp = _post_payload(api_url, payload)

    if ok:
        log.info(
            "[SENT] OK | keys=%d mouse=%d active=%ds idle=%ds",
            payload["keyboardActivityCount"],
            payload["mouseActivityCount"],
            payload["totalActiveTime"],
            payload["totalIdleTime"],
        )
        # Flush any previously queued payloads now that we're online
        _flush_queue(api_url)
        return True
    else:
        log.warning("[SEND] Backend unreachable — queuing payload locally.")
        _enqueue(payload)
        return False


# ── Offline queue helpers ──────────────────────────────────────────────────────
def _enqueue(payload: dict):
    global _offline_queue
    _offline_queue.append(payload)
    # Trim to max size (drop oldest)
    if len(_offline_queue) > _MAX_QUEUE_SIZE:
        dropped = len(_offline_queue) - _MAX_QUEUE_SIZE
        _offline_queue = _offline_queue[dropped:]
        log.warning("[QUEUE] Queue trimmed — dropped %d old entries.", dropped)
    _save_queue(_offline_queue)
    log.info("[QUEUE] %d payload(s) queued locally.", len(_offline_queue))


def _flush_queue(api_url: str):
    """Attempt to send all queued payloads. Remove successfully sent ones."""
    global _offline_queue
    if not _offline_queue:
        return

    log.info("[QUEUE] Flushing %d queued payload(s)…", len(_offline_queue))
    remaining = []
    for p in _offline_queue:
        ok, _ = _post_payload(api_url, p)
        if not ok:
            remaining.append(p)   # still offline, keep it

    flushed = len(_offline_queue) - len(remaining)
    _offline_queue = remaining
    _save_queue(_offline_queue)
    if flushed:
        log.info("[QUEUE] Flushed %d queued payload(s). %d still pending.",
                 flushed, len(remaining))
