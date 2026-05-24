"""
agent.py  -  BurnoutGuard Desktop Background Agent
====================================================
Entry point. Reads config.json, starts the activity tracker IMMEDIATELY
(system-wide keyboard + mouse via pynput, works in ALL apps including Notepad),
then logs in to the backend in the background with retry/backoff.

Snapshots are sent every `send_interval_seconds` (default: 30).
If the backend is unavailable, payloads are queued locally and flushed
automatically when connectivity is restored.

Usage
-----
  Run visibly (console window, useful for testing):
      python agent.py

  Run silently (no window, for production):
      pythonw agent.py

  Stop it:
      stop.bat   (or kill pythonw.exe via Task Manager)
"""

import json
import logging
import logging.handlers
import os
import signal
import sys
import time
import threading
from datetime import datetime
from pathlib import Path

import schedule

import sender
from tracker import ActivityTracker

# Suppress noisy pynput mouse listener warning on Python 3.13
logging.getLogger("pynput.mouse.Listener").setLevel(logging.CRITICAL)

# -- Resolve paths relative to this script's directory -----------------------
BASE_DIR    = Path(__file__).parent.resolve()
CONFIG_PATH = BASE_DIR / "config.json"
PID_FILE    = BASE_DIR / "agent.pid"


# -- Config loading -----------------------------------------------------------
def load_config() -> dict:
    if not CONFIG_PATH.exists():
        print(f"[ERROR] config.json not found at {CONFIG_PATH}")
        sys.exit(1)
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        cfg = json.load(f)

    for key in ("api_url", "email", "password"):
        if not cfg.get(key):
            print(f"[ERROR] config.json is missing required key: '{key}'")
            sys.exit(1)

    if cfg.get("email") == "your-email@example.com":
        print("[WARNING] config.json still has placeholder credentials!")

    return cfg


# -- Logging setup ------------------------------------------------------------
def setup_logging(cfg: dict):
    log_file     = BASE_DIR / cfg.get("log_file", "agent.log")
    max_bytes    = cfg.get("log_max_bytes", 5 * 1024 * 1024)
    backup_count = cfg.get("log_backup_count", 3)

    handlers = [
        logging.handlers.RotatingFileHandler(
            log_file,
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding="utf-8",
        ),
        logging.StreamHandler(sys.stdout),
    ]
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=handlers,
        force=True,
    )


# -- PID file helpers ---------------------------------------------------------
def write_pid():
    try:
        PID_FILE.write_text(str(os.getpid()), encoding="utf-8")
    except Exception:
        pass


def remove_pid():
    try:
        PID_FILE.unlink(missing_ok=True)
    except Exception:
        pass


# -- Background auth with retry -----------------------------------------------
def login_with_retry(api_url: str, email: str, password: str,
                     log: logging.Logger,
                     stop_event: threading.Event,
                     max_wait: int = 300):
    """
    Try to log in every few seconds until success or stop_event is set.
    Uses exponential backoff: 5s, 10s, 20s, ... capped at 30s.
    Returns True if login succeeded, False if stop_event was set first.
    """
    wait = 5
    elapsed = 0
    while not stop_event.is_set():
        if sender.login(api_url, email, password):
            log.info("[AUTH] Authentication successful as %s", email)
            return True
        log.warning("[AUTH] Login failed — retrying in %ds... (backend may still be starting)", wait)
        # Sleep in small chunks so stop_event is responsive
        for _ in range(wait):
            if stop_event.is_set():
                return False
            time.sleep(1)
        elapsed += wait
        wait = min(wait * 2, 30)
        if elapsed >= max_wait:
            log.error("[AUTH] Could not authenticate after %ds. Will keep trying in background.", max_wait)
            wait = 30  # keep retrying every 30s indefinitely
    return False


# -- Main ---------------------------------------------------------------------
def main():
    cfg = load_config()
    setup_logging(cfg)
    log = logging.getLogger("agent")

    api_url  = cfg["api_url"].rstrip("/")
    email    = cfg["email"]
    password = cfg["password"]
    interval = int(cfg.get("send_interval_seconds", 30))   # default 30s
    idle_thr = int(cfg.get("idle_threshold_seconds", 120))

    log.info("=" * 60)
    log.info("BurnoutGuard Desktop Agent starting  (PID %d)", os.getpid())
    log.info("API: %s  |  User: %s", api_url, email)
    log.info("Send every %ds  |  Idle threshold %ds", interval, idle_thr)
    log.info("Tracking: system-wide keyboard + mouse (all applications)")
    log.info("=" * 60)

    write_pid()

    # -- Start activity listeners IMMEDIATELY --------------------------------
    # pynput tracks ALL system keyboard/mouse events, including Notepad,
    # browsers, games, etc. -- any application running on Windows.
    tracker = ActivityTracker(idle_threshold_seconds=idle_thr)
    tracker.start()
    log.info("[TRACKER] Input listeners started. Tracking all applications.")

    # -- Graceful shutdown flag ----------------------------------------------
    stop_event = threading.Event()
    running    = True

    # -- Authenticate in background thread (non-blocking) -------------------
    auth_done = threading.Event()

    def auth_thread_fn():
        login_with_retry(api_url, email, password, log, stop_event)
        auth_done.set()

    auth_thread = threading.Thread(target=auth_thread_fn, daemon=True, name="auth-retry")
    auth_thread.start()
    log.info("[AUTH] Authenticating in background — tracking started immediately.")

    # -- Snapshot callback ---------------------------------------------------
    def send_snapshot():
        snapshot = tracker.get_and_reset()
        
        # Capture current active window locally
        try:
            import ctypes
            hwnd = ctypes.windll.user32.GetForegroundWindow()
            length = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
            buf = ctypes.create_unicode_buffer(length + 1)
            ctypes.windll.user32.GetWindowTextW(hwnd, buf, length + 1)
            active_win = buf.value or "Unknown"
        except Exception:
            active_win = "Unknown"
            
        snapshot["activeTab"] = active_win

        status   = "IDLE" if snapshot["isIdle"] else "ACTIVE"
        now_str  = datetime.now().strftime("%H:%M:%S")
        log.info(
            "[%s] %s | keys=%d  mouse=%d  active=%ds  idle=%ds",
            now_str, status,
            snapshot["keyboardActivityCount"],
            snapshot["mouseActivityCount"],
            snapshot["totalActiveTime"],
            snapshot["totalIdleTime"],
        )

        # If not yet authenticated, queue locally via sender
        sender.send_snapshot(api_url, email, password, snapshot,
                             tracker.session_start_time())

    # -- Graceful shutdown ---------------------------------------------------
    def shutdown(signum, frame):
        nonlocal running
        log.info("Shutdown signal received - sending final snapshot...")
        stop_event.set()
        try:
            send_snapshot()
        except Exception as exc:
            log.error("Error sending final snapshot: %s", exc)
        tracker.stop()
        remove_pid()
        running = False

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT,  shutdown)

    # -- Schedule and run ----------------------------------------------------
    schedule.every(interval).seconds.do(send_snapshot)
    log.info("[SCHEDULER] Active - sending every %d seconds.", interval)
    log.info("[READY] Agent is running. Tracking keyboard/mouse across ALL apps.")

    while running:
        schedule.run_pending()
        time.sleep(1)

    log.info("Agent stopped cleanly.")


if __name__ == "__main__":
    main()
