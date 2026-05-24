"""
BurnoutGuard Launcher  ─  Enhanced Edition
===========================================
What's new vs original:
  • Completely redesigned UI  (dark glassmorphism, Syne-inspired spacing)
  • FIXED idle-time counter   (was broken — now correctly uses monotonic clock)
  • App history tab           (full foreground-window journal, persisted to JSON)
  • Burnout flowchart tab     (tkinter canvas, animated, live signal overlay)
  • Extra detections:         HRV index, cognitive-load score, keystroke dynamics,
                              circadian-rhythm alert, stress-surge detector

Usage:
  python launcher.py
"""

import customtkinter as ctk
import subprocess, threading, time, os, sys, signal
import psutil, webbrowser, queue, re, json, math
import hashlib
import urllib.request as _ureq
import urllib.error as _uerr
from pathlib import Path
from datetime import datetime, timedelta
from collections import deque

# ── Sound helper (Windows) ────────────────────────────────────────────────────
try:
    import winsound as _ws
    def _play_tone(kind="break"):
        try:
            if kind == "break":
                for f, d in [(440,130),(550,130),(660,260)]: _ws.Beep(f,d); time.sleep(0.05)
            elif kind == "eye":
                for f, d in [(523,110),(523,110)]: _ws.Beep(f,d); time.sleep(0.06)
            else:
                _ws.Beep(880, 200)
        except Exception: pass
except ImportError:
    def _play_tone(kind="break"): print("\a", end="", flush=True)

# ── Optional pynput / mouse ───────────────────────────────────────────────────
try:
    from pynput import keyboard as _kb
    import mouse as _mo
    TRACKERS_OK = True
except ImportError:
    TRACKERS_OK = False

# ── Active-window helper (Windows) ────────────────────────────────────────────
try:
    import ctypes as _ct

    class _LASTINPUTINFO(_ct.Structure):
        _fields_ = [("cbSize", _ct.c_uint), ("dwTime", _ct.c_uint)]

    def get_active_window():
        hwnd   = _ct.windll.user32.GetForegroundWindow()
        length = _ct.windll.user32.GetWindowTextLengthW(hwnd)
        buf    = _ct.create_unicode_buffer(length + 1)
        _ct.windll.user32.GetWindowTextW(hwnd, buf, length + 1)
        return buf.value or "Unknown"

    def _win_idle_seconds():
        """
        Seconds since last keyboard/mouse/touch input for this Windows session
        (GetLastInputInfo). Matches Task Manager idle and works when low-level hooks
        miss events (e.g. elevated VS Code / terminals).
        """
        if sys.platform != "win32":
            return None
        try:
            li = _LASTINPUTINFO()
            li.cbSize = _ct.sizeof(_LASTINPUTINFO)
            if not _ct.windll.user32.GetLastInputInfo(_ct.byref(li)):
                return None
            tick = _ct.windll.kernel32.GetTickCount() & 0xFFFFFFFF
            last = li.dwTime & 0xFFFFFFFF
            return ((tick - last) & 0xFFFFFFFF) / 1000.0
        except Exception:
            return None
except Exception:
    def get_active_window():
        return "Unknown"

    def _win_idle_seconds():
        return None

# ── Paths ─────────────────────────────────────────────────────────────────────
ROOT      = Path(__file__).parent.resolve()
ML_DIR    = ROOT / "ml-engine"
BE_DIR    = ROOT / "backend"
FE_DIR    = ROOT / "frontend"
AGENT_DIR = ROOT / "desktop-agent"
HIST_FILE = ROOT / "app_history.json"   # persisted window-use history
USER_FILE = ROOT / "user_profile.json"  # user account & break schedule

# ── App-wide theme ────────────────────────────────────────────────────────────
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

C = {
    "bg":      "#04060d",
    "panel":   "#080c18",
    "card":    "#0d1424",
    "card2":   "#0a1020",
    "border":  "#141d33",
    "hi":      "#1e2d50",
    "accent":  "#00d4ff",
    "purple":  "#b06cff",
    "green":   "#00f5a0",
    "amber":   "#ffb020",
    "red":     "#ff4d6d",
    "blue":    "#4d9fff",
    "text":    "#e8eaf0",
    "muted":   "#5a6580",
    "dim":     "#1e2840",
}

# ── Services ──────────────────────────────────────────────────────────────────
SERVICES = [
    {"id":"ml",      "name":"ML Engine",     "desc":"Flask  •  :5001",       "color":"#00d4ff",
     "cmd":[sys.executable,"app.py"],        "cwd":ML_DIR,
     "url":"http://localhost:5001/health",   "ready_pattern":"running on",
     "shell":False,  "extra_env":{"PYTHONIOENCODING":"utf-8"}},
    {"id":"backend", "name":"Backend",       "desc":"Spring Boot  •  :8080", "color":"#ffb020",
     "cmd":"mvn spring-boot:run",            "cwd":BE_DIR,
     "url":"http://localhost:8080",          "ready_pattern":"started.*burnout|tomcat.*started|started on port",
     "shell":True,   "extra_env":{}},
    {"id":"frontend","name":"Frontend",      "desc":"Vite  •  :3000",        "color":"#00f5a0",
     "cmd":"npm run dev",                    "cwd":FE_DIR,
     "url":"http://localhost:3000",          "ready_pattern":"local.*localhost|ready in",
     "shell":True,   "extra_env":{}},
    {"id":"agent",   "name":"Desktop Agent", "desc":"Activity Tracker",      "color":"#b06cff",
     "cmd":[sys.executable,"agent.py"],      "cwd":AGENT_DIR,
     "url":None,                             "ready_pattern":"scheduler active|input listeners started",
     "shell":False,  "extra_env":{"PYTHONIOENCODING":"utf-8"}},
]


# ══════════════════════════════════════════════════════════════════════════════
# Utility helpers
# ══════════════════════════════════════════════════════════════════════════════
def fmt_sec(s: int) -> str:
    s = int(s)
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    if h:   return f"{h}h {m}m"
    if m:   return f"{m}m {sec}s"
    return  f"{sec}s"

def hex_to_rgb(h: str):
    h = h.lstrip("#")
    return tuple(int(h[i:i+2], 16) for i in (0, 2, 4))

def blend(c1, c2, t):
    r1,g1,b1 = hex_to_rgb(c1)
    r2,g2,b2 = hex_to_rgb(c2)
    return f"#{int(r1+(r2-r1)*t):02x}{int(g1+(g2-g1)*t):02x}{int(b1+(b2-b1)*t):02x}"


# ══════════════════════════════════════════════════════════════════════════════
# AppHistoryStore  —  persisted JSON log of foreground windows
# ══════════════════════════════════════════════════════════════════════════════
class AppHistoryStore:
    """Thread-safe store of {app_title: total_seconds_used} + ordered log."""

    def __init__(self, path: Path):
        self._path   = path
        self._lock   = threading.Lock()
        self._totals = {}      # title -> seconds
        self._log    = []      # [{ts, title, duration}]
        self._current_app   = ""
        self._current_start = time.monotonic()
        self._load()

    # ── Public ────────────────────────────────────────────────────────────────
    def switch(self, new_title: str):
        """Call when foreground window changes."""
        with self._lock:
            now = time.monotonic()
            if self._current_app and self._current_app != "Unknown":
                dur = int(now - self._current_start)
                self._totals[self._current_app] = self._totals.get(self._current_app, 0) + dur
                ts  = datetime.now().strftime("%H:%M:%S")
                self._log.append({"ts": ts, "title": self._current_app, "duration": dur})
                if len(self._log) > 500:
                    self._log = self._log[-400:]
            self._current_app   = new_title
            self._current_start = now

    def get_totals(self):
        with self._lock:
            # Include current running app
            now = time.monotonic()
            result = dict(self._totals)
            if self._current_app and self._current_app != "Unknown":
                result[self._current_app] = result.get(self._current_app, 0) + int(now - self._current_start)
            return sorted(result.items(), key=lambda x: x[1], reverse=True)

    def get_log(self, n=50):
        with self._lock:
            return list(self._log[-n:])

    def save(self):
        with self._lock:
            try:
                data = {"totals": self._totals, "log": self._log[-200:]}
                with open(self._path, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2)
            except Exception:
                pass

    # ── Private ───────────────────────────────────────────────────────────────
    def _load(self):
        try:
            if self._path.exists():
                with open(self._path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self._totals = data.get("totals", {})
                self._log    = data.get("log", [])
        except Exception:
            pass


# ══════════════════════════════════════════════════════════════════════════════
# UserProfile  —  account data + break-schedule preferences
# ══════════════════════════════════════════════════════════════════════════════
class UserProfile:
    """Stores user account and preferred break schedule."""
    SCHEDULES = {
        "student": {
            "Pomodoro 25-5":  {"work": 25*60, "break":  5*60, "label": "25 min study / 5 min break"},
            "Extended 50-10": {"work": 50*60, "break": 10*60, "label": "50 min study / 10 min break"},
        },
        "employee": {
            "Standard 60-10": {"work": 60*60, "break": 10*60, "label": "60 min work / 10 min break"},
            "Extended 90-20": {"work": 90*60, "break": 20*60, "label": "90 min work / 20 min break"},
        },
    }
    EYE_CARE_INTERVAL = 20 * 60   # 20-20-20 rule: nudge every 20 min

    def __init__(self, path: Path):
        self._path        = path
        self.name         = ""
        self.email        = ""
        self.role         = ""      # "student" | "employee"
        self.schedule_key = ""
        self.eye_care     = True
        self.password_hash = ""
        self._load()

    @property
    def is_registered(self) -> bool:
        return bool(self.name and self.role and self.schedule_key)

    @property
    def schedule(self):
        return self.SCHEDULES.get(self.role, {}).get(self.schedule_key)

    def save(self, **kwargs):
        for k, v in kwargs.items(): setattr(self, k, v)
        try:
            with open(self._path, "w", encoding="utf-8") as f:
                json.dump({"name": self.name, "email": self.email,
                           "role": self.role, "schedule_key": self.schedule_key,
                           "eye_care": self.eye_care,
                           "password_hash": self.password_hash}, f, indent=2)
        except Exception: pass

    def _load(self):
        try:
            if self._path.exists():
                d = json.loads(self._path.read_text(encoding="utf-8"))
                self.name         = d.get("name", "")
                self.email        = d.get("email", "")
                self.role         = d.get("role", "")
                self.schedule_key = d.get("schedule_key", "")
                self.eye_care     = d.get("eye_care", True)
                self.password_hash = d.get("password_hash", "")
        except Exception: pass


# ══════════════════════════════════════════════════════════════════════════════
# BreakScheduler  —  1-Hz countdown; fires callbacks on phase transitions
# ══════════════════════════════════════════════════════════════════════════════
class BreakScheduler:
    """Background timer that tracks work/break phases and calls back to UI."""
    def __init__(self, profile: UserProfile, on_break_due, on_eye_care_due, on_tick):
        self._profile     = profile
        self._cb_break    = on_break_due
        self._cb_eye      = on_eye_care_due
        self._cb_tick     = on_tick
        self._running     = False
        self._in_break    = False
        self._elapsed     = 0
        self._break_count = 0
        self._eye_elapsed = 0

    @property
    def phase(self) -> str:   return "break" if self._in_break else "work"
    @property
    def elapsed(self) -> int:  return self._elapsed
    @property
    def total(self) -> int:
        s = self._profile.schedule
        return (s["break"] if self._in_break else s["work"]) if s else 0
    @property
    def remaining(self) -> int: return max(0, self.total - self._elapsed)
    @property
    def break_count(self) -> int: return self._break_count

    def start(self):
        if self._running: return
        self._running = True
        threading.Thread(target=self._run, daemon=True, name="break-sched").start()

    def stop(self):   self._running = False
    def reset(self):  self._elapsed = 0; self._in_break = False; self._break_count = 0; self._eye_elapsed = 0
    def skip_break(self):  self._in_break = False; self._elapsed = 0
    def begin_break(self): self._in_break = True;  self._elapsed = 0

    def _run(self):
        while self._running:
            time.sleep(1)
            s = self._profile.schedule
            if not s: continue
            self._elapsed     += 1
            self._eye_elapsed += 1
            # Eye-care nudge every 20 min during work
            if (not self._in_break and self._profile.eye_care
                    and self._eye_elapsed >= UserProfile.EYE_CARE_INTERVAL):
                self._eye_elapsed = 0
                try: self._cb_eye()
                except Exception: pass
            # Phase transition
            limit = s["break"] if self._in_break else s["work"]
            if self._elapsed >= limit:
                self._elapsed = 0
                if self._in_break:
                    self._in_break = False          # break → work
                else:
                    self._in_break = True           # work  → BREAK!
                    self._break_count += 1
                    self._eye_elapsed  = 0
                    try: self._cb_break()
                    except Exception: pass
            try: self._cb_tick()
            except Exception: pass


# ══════════════════════════════════════════════════════════════════════════════
# LiveTracker  ─  fixed idle detection + extra signals
# ══════════════════════════════════════════════════════════════════════════════
class LiveTracker:
    IDLE_THRESHOLD = 120.0    # 2 minutes (matches desktop-agent default)
    SURGE_WINDOW   = 10       # seconds window for keystroke surge detection

    def __init__(self, history: AppHistoryStore):
        self._lock             = threading.Lock()
        self._history          = history
        self._key_count        = 0
        self._mouse_count      = 0
        # ── FIXED: use separate last_activity monotonic ──────────────────────
        self._last_activity    = time.monotonic()  # updated on every input event
        self._last_mouse_move  = 0.0
        self._last_mouse_pos   = None              # (x, y) for movement threshold
        # ── Accumulators ─────────────────────────────────────────────────────
        self._active_secs      = 0
        self._idle_secs        = 0
        self._screen_secs      = 0
        self._session_start    = datetime.now()
        # ── Per-second keystroke ring for surge detection ─────────────────────
        self._kps_ring         = deque(maxlen=60)   # 60-sec ring
        self._kps_current      = 0                  # keys in current second
        # ── Thread handles ───────────────────────────────────────────────────
        self._kb_listener      = None
        self._running          = False
        self._last_win         = ""

    # ── Start / stop ──────────────────────────────────────────────────────────
    def start(self):
        if self._running:
            return
        self._running = True
        if TRACKERS_OK:
            try:
                self._kb_listener = _kb.Listener(on_press=self._on_key)
                self._kb_listener.start()
                _mo.hook(self._on_mouse)
            except Exception:
                pass
        threading.Thread(target=self._tick, daemon=True, name="tracker-tick").start()

    def stop(self):
        self._running = False
        if self._kb_listener:
            try: self._kb_listener.stop()
            except Exception: pass
        try: _mo.unhook_all()
        except Exception: pass
        self._history.save()

    # ── Snapshot (read-only, thread-safe) ─────────────────────────────────────
    def snapshot(self) -> dict:
        with self._lock:
            now  = time.monotonic()
            # ── Idle: prefer OS last-input (elevated IDEs); else hook-based clock ──
            w_idle = _win_idle_seconds()
            idle = (
                w_idle >= self.IDLE_THRESHOLD
                if w_idle is not None
                else (now - self._last_activity) >= self.IDLE_THRESHOLD
            )
            total = max(1, self._active_secs + self._idle_secs)
            focus = int(self._active_secs / total * 100)

            # HRV proxy: higher idle ratio → lower stress → higher RMSSD
            idle_ratio   = self._idle_secs / total
            hrv_rmssd    = max(15, min(90, int(45 + idle_ratio * 35 - (self._key_count % 200) * 0.05)))
            hrv_sdnn     = max(10, int(hrv_rmssd * 1.15))
            pnn50        = max(5,  int(hrv_rmssd * 0.55))

            # Cognitive load from KPS
            kps = sum(self._kps_ring) / max(1, len(self._kps_ring))
            cog_load = min(100, int(kps * 18))
            cog_label = "LOW" if cog_load < 30 else "MODERATE" if cog_load < 65 else "HIGH" if cog_load < 85 else "CRITICAL"

            # Keystroke surge (last 10 sec vs baseline)
            recent_kps = sum(list(self._kps_ring)[-self.SURGE_WINDOW:]) / self.SURGE_WINDOW if len(self._kps_ring) >= self.SURGE_WINDOW else 0
            baseline_kps = sum(self._kps_ring) / max(1, len(self._kps_ring))
            surge = recent_kps > baseline_kps * 2.5 and recent_kps > 3

            # Stress index composite
            stress = min(100, int((100 - hrv_rmssd) * 0.5 + cog_load * 0.5))

            # Circadian alert level for current hour
            hour = datetime.now().hour
            circ_scores = [20,15,15,18,22,38,55,70,88,92,90,85,75,80,88,90,85,72,60,50,40,32,25,20]
            circ_alert = circ_scores[hour]

            return {
                "key_count":    self._key_count,
                "mouse_count":  self._mouse_count,
                "active_secs":  self._active_secs,
                "idle_secs":    self._idle_secs,   # ← now correctly non-zero after 2 min idle
                "screen_secs":  self._screen_secs,
                "is_idle":      idle,
                "focus_pct":    focus,
                "session_start":self._session_start,
                "kps":          round(kps, 2),
                "hrv_rmssd":    hrv_rmssd,
                "hrv_sdnn":     hrv_sdnn,
                "pnn50":        pnn50,
                "cog_load":     cog_load,
                "cog_label":    cog_label,
                "stress":       stress,
                "surge":        surge,
                "circ_alert":   circ_alert,
                "kps_ring":     list(self._kps_ring),
            }

    # ── Tick (1 Hz) ───────────────────────────────────────────────────────────
    def _tick(self):
        while self._running:
            time.sleep(1)
            with self._lock:
                now  = time.monotonic()
                w_idle = _win_idle_seconds()
                idle = (
                    w_idle >= self.IDLE_THRESHOLD
                    if w_idle is not None
                    else (now - self._last_activity) >= self.IDLE_THRESHOLD
                )
                # ── Correctly accumulate active vs idle ─────────────────────
                if idle:
                    self._idle_secs   += 1
                else:
                    self._active_secs += 1
                self._screen_secs += 1
                # KPS ring
                self._kps_ring.append(self._kps_current)
                self._kps_current = 0

            # Window tracking (outside lock to avoid blocking)
            try:
                w = get_active_window()
                if w and w != self._last_win and w != "Unknown":
                    self._history.switch(w)
                    self._last_win = w
            except Exception:
                pass

        self._history.save()

    # ── Input callbacks ───────────────────────────────────────────────────────
    def _on_key(self, key):
        with self._lock:
            self._key_count    += 1
            self._kps_current  += 1
            self._last_activity = time.monotonic()

    def _on_mouse(self, event):
        now = time.monotonic()
        with self._lock:
            if isinstance(event, _mo.MoveEvent):
                # Ignore tiny cursor jitter; count only meaningful movement.
                # Do NOT reset idle clock on pointer movement — only keys/clicks/wheel
                # should end an idle period (matches desktop-agent tracker).
                x = getattr(event, "x", None)
                y = getattr(event, "y", None)
                moved_enough = False
                if x is not None and y is not None:
                    if self._last_mouse_pos is None:
                        self._last_mouse_pos = (x, y)
                    else:
                        px, py = self._last_mouse_pos
                        dx, dy = abs(x - px), abs(y - py)
                        # Threshold keeps idle detection accurate when mouse sensor jitters.
                        moved_enough = (dx + dy) >= 8 or dx >= 5 or dy >= 5
                        self._last_mouse_pos = (x, y)
                if moved_enough and (now - self._last_mouse_move) >= 0.5:
                    self._mouse_count += 1
                    self._last_mouse_move = now
            elif isinstance(event, _mo.ButtonEvent):
                if event.event_type == "down":
                    self._mouse_count  += 1
                    self._last_activity = now
            elif isinstance(event, _mo.WheelEvent):
                self._mouse_count  += 1
                self._last_activity = now


# ══════════════════════════════════════════════════════════════════════════════
# ServiceProcess
# ══════════════════════════════════════════════════════════════════════════════
class ServiceProcess:
    def __init__(self, svc: dict, log_q: queue.Queue):
        self.svc     = svc
        self.log_q   = log_q
        self.proc    = None
        self.state   = "stopped"
        self._thread = None

    def start(self):
        if self.proc and self.proc.poll() is None:
            return
        self.state = "starting"
        self._log(f"▶ Starting {self.svc['name']}…")
        env   = os.environ.copy()
        env.update(self.svc.get("extra_env", {}))
        flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" and not self.svc.get("shell") else 0
        try:
            self.proc = subprocess.Popen(
                self.svc["cmd"], cwd=str(self.svc["cwd"]),
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding="utf-8", errors="replace",
                bufsize=1, shell=self.svc.get("shell", False),
                env=env, creationflags=flags,
            )
        except (FileNotFoundError, OSError) as e:
            self.state = "error"
            self._log(f"✖ Could not start {self.svc['name']}: {e}")
            return
        self._thread = threading.Thread(target=self._read, daemon=True)
        self._thread.start()

    def stop(self):
        self._log(f"⏹ Stopping {self.svc['name']}…")
        self.state = "stopped"
        if not self.proc:
            return
        try:
            if sys.platform == "win32":
                subprocess.call(["taskkill","/F","/T","/PID",str(self.proc.pid)],
                                creationflags=subprocess.CREATE_NO_WINDOW)
            else:
                os.killpg(os.getpgid(self.proc.pid), signal.SIGTERM)
        except Exception:
            try: self.proc.terminate()
            except Exception: pass
        try: self.proc.wait(timeout=5)
        except Exception: pass

    def is_running(self):
        return self.state in ("running", "starting")

    def _read(self):
        pat = re.compile(self.svc["ready_pattern"], re.IGNORECASE)
        for line in self.proc.stdout:
            line = line.rstrip()
            if line:
                self._log(f"  {line}")
                if (
                    self.svc.get("id") == "backend"
                    and "port 8080 was already in use" in line.lower()
                    and self._is_service_reachable(self.svc.get("url"))
                ):
                    self.state = "running"
                    self._log("✔ Backend already running on :8080 (using existing instance).")
                if self.state == "starting" and pat.search(line):
                    self.state = "running"
                    self._log(f"✔ {self.svc['name']} is ready!")
        rc = self.proc.wait()
        if self.state != "stopped":
            if rc != 0:
                if self._is_service_reachable(self.svc.get("url")):
                    self.state = "running"
                    self._log(f"✔ {self.svc['name']} already active on {self.svc.get('url')} (existing process).")
                else:
                    self.state = "error"
            else:
                self.state = "stopped"

    def _is_service_reachable(self, url: str) -> bool:
        if not url:
            return False
        try:
            with _ureq.urlopen(url, timeout=2) as resp:
                code = getattr(resp, "status", 200)
                return int(code) < 500
        except _uerr.HTTPError as e:
            # Backend may return 401/403 on root when security is enabled.
            # That still means service is alive and reachable.
            return int(getattr(e, "code", 500)) < 500
        except Exception:
            return False

    def _log(self, msg):
        self.log_q.put(f"[{datetime.now().strftime('%H:%M:%S')}]  {msg}")


# ══════════════════════════════════════════════════════════════════════════════
# BurnoutLauncher  ─  main window
# ══════════════════════════════════════════════════════════════════════════════
class BurnoutLauncher(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("BurnoutGuard — Activity Monitor")
        self.geometry("1340x860")
        self.minsize(1100, 720)
        self.configure(fg_color=C["bg"])

        self._history  = AppHistoryStore(HIST_FILE)
        self.tracker   = LiveTracker(self._history)
        self._tracker_started = False

        self.log_q     = queue.Queue()
        self.services  = {s["id"]: ServiceProcess(s, self.log_q) for s in SERVICES}
        self.dot_lbl   = {}
        self.sta_lbl   = {}
        self.card_frm  = {}
        self._mon      = {}

        self._kps_canvas_pts   = []   # for sparkline in monitor tab
        self._hrv_history      = deque(maxlen=40)
        self._stress_history   = deque(maxlen=40)

        # ── Break timer system ────────────────────────────────────────────────
        self._profile      = UserProfile(USER_FILE)
        self._session      = {
            "is_authenticated": False,
            "token": "",
            "name": "",
            "email": "",
            "role": "",
        }
        self._alert_open   = False
        self._bt_eye_lines = []
        self._scheduler    = BreakScheduler(
            self._profile,
            on_break_due    = lambda: self.after(0, self._on_break_due),
            on_eye_care_due = lambda: self.after(0, self._on_eye_care_due),
            on_tick         = lambda: self.after(0, self._on_sched_tick),
        )

        self._build_ui()
        self.after(500,  self._poll_states)
        self.after(200,  self._poll_logs)
        self.after(1000, self._poll_monitor)
        self.after(5000, self._autosave)

        # Start Spring Boot in background so login can use the real API immediately.
        self.after(350, self._auto_start_backend_if_needed)

        self.withdraw()
        self.after(150, lambda: self._show_create_account_dlg(auth_gate=True))

    # ══════════════════════════════════════════════════════════════════════════
    # TOP-LEVEL LAYOUT
    # ══════════════════════════════════════════════════════════════════════════
    def _build_ui(self):
        # ── Title bar ─────────────────────────────────────────────────────────
        hdr = ctk.CTkFrame(self, fg_color=C["panel"], corner_radius=0, height=58)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)

        # Logo
        logo_f = ctk.CTkFrame(hdr, fg_color="transparent")
        logo_f.pack(side="left", padx=18)
        ctk.CTkLabel(logo_f, text="🧠", font=ctk.CTkFont(size=24)).pack(side="left", padx=(0,8))
        ctk.CTkLabel(logo_f, text="BurnoutGuard",
                     font=ctk.CTkFont("Segoe UI", 18, weight="bold"),
                     text_color=C["text"]).pack(side="left")
        ctk.CTkLabel(logo_f, text="  AI-Powered Burnout Detection System",
                     font=ctk.CTkFont(size=11), text_color=C["muted"]).pack(side="left")

        # Action buttons
        btn_f = ctk.CTkFrame(hdr, fg_color="transparent")
        btn_f.pack(side="right", padx=16)

        self._hdr_buttons = {}
        def mkcbtn(key, parent, text, cmd, fg, hv, w=120):
            btn = ctk.CTkButton(parent, text=text, command=cmd,
                                fg_color=fg, hover_color=hv,
                                font=ctk.CTkFont(size=13, weight="bold"),
                                width=w, height=34, corner_radius=8)
            btn.pack(side="right", padx=5)
            self._hdr_buttons[key] = btn

        mkcbtn("open", btn_f, "🌐  Open App",   self._open_browser, C["accent"],  "#009bbf")
        mkcbtn("logout", btn_f, "🚪  Logout",   self._logout,       "#3b4a6b",    "#4d6080")
        mkcbtn("stop_all", btn_f, "⏹  Stop All", self._stop_all,    "#2a3550",    "#3b4a6b")
        mkcbtn("start_all", btn_f, "▶  Start All", self._start_all, C["purple"],  "#8855cc")

        # ── Tab view ──────────────────────────────────────────────────────────
        self.tabs = ctk.CTkTabview(
            self, fg_color=C["bg"],
            segmented_button_fg_color=C["panel"],
            segmented_button_selected_color=C["purple"],
            segmented_button_selected_hover_color="#8855cc",
            segmented_button_unselected_color=C["panel"],
            segmented_button_unselected_hover_color=C["dim"],
            text_color=C["text"],
        )
        self.tabs.pack(fill="both", expand=True, padx=14, pady=(10, 0))

        for tab in ["📡  Live Monitor", "📊  Detections", "🧭  Usage Chart",
                    "📂  App History", "⏰  Break Timer", "⚙️  Services"]:
            self.tabs.add(tab)

        self._build_monitor_tab(self.tabs.tab("📡  Live Monitor"))
        self._build_detections_tab(self.tabs.tab("📊  Detections"))
        self._build_usage_tab(self.tabs.tab("🧭  Usage Chart"))
        self._build_history_tab(self.tabs.tab("📂  App History"))
        self._build_breaktimer_tab(self.tabs.tab("⏰  Break Timer"))
        self._build_services_tab(self.tabs.tab("⚙️  Services"))

        # ── Status bar ────────────────────────────────────────────────────────
        bar = ctk.CTkFrame(self, fg_color=C["panel"], corner_radius=0, height=28)
        bar.pack(fill="x", side="bottom")
        bar.pack_propagate(False)
        self.status_bar = ctk.CTkLabel(bar,
            text="Backend starts automatically. Log in, then use Start All for ML / Frontend / Agent.",
            font=ctk.CTkFont(size=11), text_color=C["muted"])
        self.status_bar.pack(side="left", padx=16)
        ctk.CTkLabel(bar, text="http://localhost:3000",
                     font=ctk.CTkFont(size=11),
                     text_color=C["accent"]).pack(side="right", padx=16)
        self._set_service_controls_enabled(False)

    # ══════════════════════════════════════════════════════════════════════════
    # TAB 1 — LIVE MONITOR  (redesigned)
    # ══════════════════════════════════════════════════════════════════════════
    def _build_monitor_tab(self, parent):
        # Scrollable container
        scroll = ctk.CTkScrollableFrame(parent, fg_color="transparent")
        scroll.pack(fill="both", expand=True, padx=0, pady=0)

        # ── Header row ────────────────────────────────────────────────────────
        hdr = ctk.CTkFrame(scroll, fg_color="transparent")
        hdr.pack(fill="x", pady=(6, 4), padx=6)

        ctk.CTkLabel(hdr, text="⚡  Live Activity Monitor",
                     font=ctk.CTkFont("Segoe UI", 20, weight="bold"),
                     text_color=C["text"]).pack(side="left")
        self._mon["live_user_lbl"] = ctk.CTkLabel(
            hdr, text="Active User: Not logged in",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color=C["accent"])
        self._mon["live_user_lbl"].pack(side="left", padx=(12, 0))

        self._mon["status_pill"] = ctk.CTkLabel(
            hdr, text="● ACTIVE",
            font=ctk.CTkFont("Segoe UI", 13, weight="bold"),
            text_color=C["green"])
        self._mon["status_pill"].pack(side="right", padx=8)

        badge = "🖥️ Desktop Agent ON" if TRACKERS_OK else "⚠️  Trackers Missing"
        ctk.CTkLabel(hdr, text=badge,
                     font=ctk.CTkFont(size=11, weight="bold"),
                     text_color=C["green"] if TRACKERS_OK else C["amber"]
                     ).pack(side="right", padx=12)

        # ── Focus progress bar ────────────────────────────────────────────────
        bf = ctk.CTkFrame(scroll, fg_color=C["card"], corner_radius=10,
                          border_color=C["border"], border_width=1)
        bf.pack(fill="x", padx=6, pady=4)
        bfi = ctk.CTkFrame(bf, fg_color="transparent")
        bfi.pack(fill="x", padx=14, pady=10)

        ctk.CTkLabel(bfi, text="Focus Ratio",
                     font=ctk.CTkFont(size=11), text_color=C["muted"]).pack(anchor="w")

        self._mon["focus_bar"] = ctk.CTkProgressBar(
            bfi, height=10, corner_radius=5,
            fg_color=C["border"], progress_color=C["green"])
        self._mon["focus_bar"].set(1.0)
        self._mon["focus_bar"].pack(fill="x", pady=(4, 2))

        self._mon["focus_pct_lbl"] = ctk.CTkLabel(
            bfi, text="100% active",
            font=ctk.CTkFont(size=11, weight="bold"), text_color=C["green"])
        self._mon["focus_pct_lbl"].pack(anchor="e")

        # ── Primary stat cards (2-column) ─────────────────────────────────────
        row1 = self._row_frame(scroll)
        self._stat_card(row1, 0, "⚡", "Active Time",  "active_t",  C["green"],  "0s")
        self._stat_card(row1, 1, "💤", "Idle Time",    "idle_t",    C["amber"],  "0s")

        row2 = self._row_frame(scroll)
        self._stat_card(row2, 0, "🖥️", "Screen Time",  "screen_t",  C["blue"],   "0s")
        self._stat_card(row2, 1, "⌨️", "Keystrokes",   "keys",      C["purple"], "0")

        row3 = self._row_frame(scroll)
        self._stat_card(row3, 0, "🖱️", "Mouse Events", "mouse",     C["purple"], "0")
        self._stat_card(row3, 1, "🪟", "Active App",   "active_app",C["accent"], "—", sub="foreground window")

        # ── Divider ───────────────────────────────────────────────────────────
        ctk.CTkFrame(scroll, height=1, fg_color=C["border"]).pack(fill="x", padx=6, pady=8)

        # ── 3-column detail cards ─────────────────────────────────────────────
        det = ctk.CTkFrame(scroll, fg_color="transparent")
        det.pack(fill="x", padx=6, pady=4)
        for i in range(3): det.columnconfigure(i, weight=1)

        detail_items = [
            ("⌨️","KEYSTROKES",  "dk_keys",  C["purple"],"0",   "total key presses"),
            ("🖱️","MOUSE EVENTS","dk_mouse", C["purple"],"0",   "throttled move events"),
            ("🖥️","SCREEN TIME", "dk_scrn",  C["blue"],  "0s",  "tab focused & visible"),
            ("⚡","ACTIVE TIME", "dk_act",   C["green"], "0s",  "typing or clicking"),
            ("💤","IDLE TIME",   "dk_idle",  C["amber"], "0s",  ">2 min no activity"),
            ("🎯","FOCUS SCORE", "dk_focus", C["accent"],"100%","active / total time"),
        ]
        for i,(ic,lb,ky,co,df,su) in enumerate(detail_items):
            r,c = divmod(i, 3)
            self._big_card(det, r, c, ic, lb, ky, co, df, su)

        # ── System stats ──────────────────────────────────────────────────────
        ctk.CTkFrame(scroll, height=1, fg_color=C["border"]).pack(fill="x", padx=6, pady=8)
        sys_row = self._row_frame(scroll, cols=3)
        self._sys_card(sys_row, 0, "🖧",  "CPU Usage",  "cpu",  C["blue"],   "—%")
        self._sys_card(sys_row, 1, "🧠",  "RAM Usage",  "ram",  C["purple"], "—%")
        self._sys_card(sys_row, 2, "🔋",  "Battery",    "bat",  C["green"],  "—%")

        # ── Top Processes ─────────────────────────────────────────────────────
        ctk.CTkLabel(scroll, text="TOP PROCESSES  (by CPU %)",
                     font=ctk.CTkFont(size=10, weight="bold"),
                     text_color=C["muted"]).pack(anchor="w", padx=6, pady=(6,2))
        self._mon["proc_box"] = self._textbox(scroll, height=90)

        # ── Recent window log (last 12) ───────────────────────────────────────
        ctk.CTkLabel(scroll, text="RECENT ACTIVE WINDOWS  (last 12 switches)",
                     font=ctk.CTkFont(size=10, weight="bold"),
                     text_color=C["muted"]).pack(anchor="w", padx=6, pady=(6,2))
        self._mon["win_box"] = self._textbox(scroll, height=90, color="#b06cff")

    # ══════════════════════════════════════════════════════════════════════════
    # TAB 2 — EXTRA DETECTIONS
    # ══════════════════════════════════════════════════════════════════════════
    def _build_detections_tab(self, parent):
        scroll = ctk.CTkScrollableFrame(parent, fg_color="transparent")
        scroll.pack(fill="both", expand=True)

        ctk.CTkLabel(scroll, text="📊  Advanced Burnout Detection Signals",
                     font=ctk.CTkFont("Segoe UI", 18, weight="bold"),
                     text_color=C["text"]).pack(anchor="w", padx=6, pady=(8,2))
        ctk.CTkLabel(scroll, text="Live biometric-inference, cognitive-load, and circadian signals",
                     font=ctk.CTkFont(size=11), text_color=C["muted"]).pack(anchor="w", padx=6, pady=(0,10))

        # ── HRV Block ─────────────────────────────────────────────────────────
        self._sec_header(scroll, "💓  Heart Rate Variability (Inferred)")
        hrv_row = self._row_frame(scroll, cols=3)
        self._det_card(hrv_row, 0, "RMSSD",  "hrv_rmssd", "—ms",  C["green"],  "Root mean square — lower=stressed")
        self._det_card(hrv_row, 1, "SDNN",   "hrv_sdnn",  "—ms",  C["blue"],   "SD of RR intervals")
        self._det_card(hrv_row, 2, "pNN50",  "hrv_pnn50", "—%",   C["purple"], "% successive diffs >50ms")

        # HRV sparkline canvas
        self._sec_header(scroll, "HRV Trend  (last 40 samples)")
        self._mon["hrv_canvas"] = ctk.CTkCanvas(scroll, height=80,
                                                bg=C["card"], highlightthickness=0)
        self._mon["hrv_canvas"].pack(fill="x", padx=6, pady=4)

        # ── Cognitive Load ────────────────────────────────────────────────────
        self._sec_header(scroll, "🧠  Cognitive Load Index")
        cog_row = self._row_frame(scroll, cols=3)
        self._det_card(cog_row, 0, "Load Score",  "cog_score", "—%",  C["amber"],  "From keystroke velocity")
        self._det_card(cog_row, 1, "KPS",         "kps",       "—",   C["accent"], "Keys per second (60s avg)")
        self._det_card(cog_row, 2, "Level",        "cog_label", "—",   C["purple"], "LOW/MODERATE/HIGH/CRITICAL")

        # ── Keystroke Dynamics ────────────────────────────────────────────────
        self._sec_header(scroll, "⌨️  Keystroke Dynamics")
        kd_row = self._row_frame(scroll, cols=3)
        self._det_card(kd_row, 0, "Surge Alert",    "surge",    "—",  C["red"],    "Frantic input burst (>2.5× avg)")
        self._det_card(kd_row, 1, "Stress Index",   "stress",   "—%", C["red"],    "HRV+Cognitive composite")
        self._det_card(kd_row, 2, "Recovery Score", "recovery", "—%", C["green"],  "100 - Stress Index")

        # Stress sparkline
        self._sec_header(scroll, "Stress Index Trend  (last 40 samples)")
        self._mon["stress_canvas"] = ctk.CTkCanvas(scroll, height=80,
                                                   bg=C["card"], highlightthickness=0)
        self._mon["stress_canvas"].pack(fill="x", padx=6, pady=4)

        # ── Circadian rhythm ──────────────────────────────────────────────────
        self._sec_header(scroll, "🕐  Circadian Rhythm Alignment")
        circ_row = self._row_frame(scroll, cols=2)
        self._det_card(circ_row, 0, "Alertness Now",  "circ_alert", "—%", C["green"],  "Expected alertness for this hour")
        self._det_card(circ_row, 1, "Circadian Phase", "circ_phase", "—",  C["blue"],   "Current biological phase")

        # 24-hour alertness bar
        self._sec_header(scroll, "24-Hour Alertness Curve  (your current position: ▲)")
        self._mon["circ_canvas"] = ctk.CTkCanvas(scroll, height=80,
                                                 bg=C["card"], highlightthickness=0)
        self._mon["circ_canvas"].pack(fill="x", padx=6, pady=4)
        self._draw_circadian_curve()

    # ══════════════════════════════════════════════════════════════════════════
    # TAB 3 — BURNOUT FLOWCHART
    # ══════════════════════════════════════════════════════════════════════════
    def _build_flowchart_tab(self, parent):
        scroll = ctk.CTkScrollableFrame(parent, fg_color="transparent")
        scroll.pack(fill="both", expand=True)

        ctk.CTkLabel(scroll, text="🔀  Burnout Detection Algorithm — System Flowchart",
                     font=ctk.CTkFont("Segoe UI", 18, weight="bold"),
                     text_color=C["text"]).pack(anchor="w", padx=6, pady=(8,2))
        ctk.CTkLabel(scroll, text="How raw desktop signals flow into ML predictions and personalized actions",
                     font=ctk.CTkFont(size=11), text_color=C["muted"]).pack(anchor="w", padx=6, pady=(0,10))

        # ── Main flowchart canvas ─────────────────────────────────────────────
        canvas_h = 580
        self._fc = ctk.CTkCanvas(scroll, height=canvas_h,
                                 bg=C["card"], highlightthickness=0)
        self._fc.pack(fill="x", padx=6, pady=4)
        self._fc.bind("<Configure>", lambda e: self._draw_flowchart(e.width, canvas_h))

        # ── Legend / explanation cards ────────────────────────────────────────
        self._sec_header(scroll, "Detection Layers Explained")
        layers = [
            ("Layer 1 — Input Collection", C["accent"],
             "Desktop Agent tracks all keyboard events, mouse movements, clicks, scrolls\n"
             "and scrolls system-wide via pynput. Active window captured every second."),
            ("Layer 2 — Behavioral Analysis", C["purple"],
             "KPS (keys/sec), mouse velocity, idle burst frequency, and session length\n"
             "are computed from raw events to build behavioral feature vectors."),
            ("Layer 3 — Biometric Inference", C["green"],
             "HRV metrics (RMSSD, SDNN, pNN50) inferred from activity-stress correlation.\n"
             "Circadian alignment checked against time-of-day alertness model."),
            ("Layer 4 — ML Prediction (RF + XGBoost)", C["amber"],
             "8 engineered features passed to Random Forest + XGBoost ensemble.\n"
             "Output: risk score 0–100 + probability distribution (LOW/MEDIUM/HIGH)."),
            ("Layer 5 — Adaptive Actions", C["red"],
             "Personalized recommendations, wellness alerts, and admin notifications\n"
             "triggered based on risk level and trend direction."),
        ]
        for title, color, desc in layers:
            card = ctk.CTkFrame(scroll, fg_color=C["card2"],
                                corner_radius=10, border_color=color, border_width=1)
            card.pack(fill="x", padx=6, pady=4)
            inner = ctk.CTkFrame(card, fg_color="transparent")
            inner.pack(fill="x", padx=16, pady=12)
            ctk.CTkLabel(inner, text=title,
                         font=ctk.CTkFont(size=13, weight="bold"),
                         text_color=color).pack(anchor="w")
            ctk.CTkLabel(inner, text=desc,
                         font=ctk.CTkFont(size=11),
                         text_color=C["muted"],
                         justify="left").pack(anchor="w", pady=(4,0))

        # ── High-risk indicator list ───────────────────────────────────────────
        self._sec_header(scroll, "🚨  High-Risk Indicators")
        risk_grid = ctk.CTkFrame(scroll, fg_color="transparent")
        risk_grid.pack(fill="x", padx=6, pady=4)
        for i in range(3): risk_grid.columnconfigure(i, weight=1)

        indicators = [
            "RMSSD < 20ms", "Cognitive Load > 85%", "Screen Time > 10h/day",
            "Break Frequency < 1/day", "Consecutive Work Days > 10", "Late-Night Sessions > 5/wk",
            "Keystroke Surge > 5 min", "Focus Score < 20%", "Stress Index > 80%",
        ]
        for i, ind in enumerate(indicators):
            r, c = divmod(i, 3)
            f = ctk.CTkFrame(risk_grid, fg_color=C["card2"],
                             corner_radius=8,
                             border_color=C["red"], border_width=1)
            f.grid(row=r, column=c, padx=4, pady=4, sticky="ew")
            ctk.CTkLabel(f, text=f"⚠  {ind}",
                         font=ctk.CTkFont("Consolas", 11, weight="bold"),
                         text_color=C["red"]).pack(padx=10, pady=8)

    # ══════════════════════════════════════════════════════════════════════════
    # TAB 4 — APP HISTORY
    # ══════════════════════════════════════════════════════════════════════════
    def _build_history_tab(self, parent):
        # Header + refresh button
        top = ctk.CTkFrame(parent, fg_color="transparent")
        top.pack(fill="x", padx=6, pady=(8,4))
        ctk.CTkLabel(top, text="📂  Application Usage History",
                     font=ctk.CTkFont("Segoe UI", 18, weight="bold"),
                     text_color=C["text"]).pack(side="left")

        ctk.CTkButton(top, text="🗑  Clear History",
                      command=self._clear_history,
                      fg_color=C["dim"], hover_color=C["border"],
                      font=ctk.CTkFont(size=12), width=130, height=30,
                      corner_radius=8).pack(side="right", padx=4)
        self._mon["hist_user_lbl"] = ctk.CTkLabel(
            top, text="Active User: Not logged in",
            font=ctk.CTkFont(size=11, weight="bold"), text_color=C["accent"])
        self._mon["hist_user_lbl"].pack(side="right", padx=(0, 8))

        ctk.CTkLabel(parent, text="Window history is auto-saved with timestamps to app_history.json",
                     font=ctk.CTkFont(size=11), text_color=C["muted"]
                     ).pack(anchor="w", padx=6, pady=(0,8))

        # Split: left = totals, right = recent log
        body = ctk.CTkFrame(parent, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=6, pady=4)
        body.columnconfigure(0, weight=1)
        body.columnconfigure(1, weight=1)

        # Left — Usage totals table
        left = ctk.CTkFrame(body, fg_color="transparent")
        left.grid(row=0, column=0, sticky="nsew", padx=(0,6))

        ctk.CTkLabel(left, text="APP USAGE TOTALS",
                     font=ctk.CTkFont(size=10, weight="bold"),
                     text_color=C["muted"]).pack(anchor="w", pady=(0,4))
        self._mon["hist_totals"] = ctk.CTkTextbox(
            left, font=ctk.CTkFont("Consolas", 11),
            fg_color=C["card"], text_color="#e8eaf0",
            corner_radius=10, border_color=C["border"], border_width=1)
        self._mon["hist_totals"].pack(fill="both", expand=True)
        self._mon["hist_totals"].configure(state="disabled")

        # Right — Activity log
        right = ctk.CTkFrame(body, fg_color="transparent")
        right.grid(row=0, column=1, sticky="nsew")

        ctk.CTkLabel(right, text="RECENT ACTIVITY LOG  (newest last)",
                     font=ctk.CTkFont(size=10, weight="bold"),
                     text_color=C["muted"]).pack(anchor="w", pady=(0,4))
        self._mon["hist_log"] = ctk.CTkTextbox(
            right, font=ctk.CTkFont("Consolas", 11),
            fg_color=C["card"], text_color="#b06cff",
            corner_radius=10, border_color=C["border"], border_width=1)
        self._mon["hist_log"].pack(fill="both", expand=True)
        self._mon["hist_log"].configure(state="disabled")

    def _build_usage_tab(self, parent):
        card = ctk.CTkFrame(parent, fg_color=C["card"], corner_radius=12,
                            border_color=C["border"], border_width=1)
        card.pack(fill="both", expand=True, padx=10, pady=10)
        ctk.CTkLabel(card, text="🧭  User Stress / Usage Chart",
                     font=ctk.CTkFont("Segoe UI", 20, weight="bold"),
                     text_color=C["text"]).pack(anchor="w", padx=18, pady=(14, 4))
        self._mon["usage_user_lbl"] = ctk.CTkLabel(
            card, text="Active User: Not logged in",
            font=ctk.CTkFont(size=12, weight="bold"), text_color=C["accent"])
        self._mon["usage_user_lbl"].pack(anchor="w", padx=18, pady=(0, 8))
        self._mon["usage_canvas"] = ctk.CTkCanvas(card, width=420, height=300, bg=C["card"], highlightthickness=0)
        self._mon["usage_canvas"].pack(pady=8)
        self._mon["usage_hours_lbl"] = ctk.CTkLabel(
            card, text="0.0h active", font=ctk.CTkFont("Segoe UI", 16, weight="bold"), text_color=C["green"])
        self._mon["usage_hours_lbl"].pack()
        self._mon["usage_meta_lbl"] = ctk.CTkLabel(
            card, text="Auto-calculated from usage logs and saved automatically.",
            font=ctk.CTkFont(size=11), text_color=C["muted"])
        self._mon["usage_meta_lbl"].pack(pady=(4, 12))

    def _build_admin_tab(self, parent):
        outer = ctk.CTkFrame(parent, fg_color="transparent")
        outer.pack(fill="both", expand=True, padx=8, pady=8)
        ctk.CTkLabel(outer, text="🛡  Admin Panel",
                     font=ctk.CTkFont("Segoe UI", 20, weight="bold"),
                     text_color=C["text"]).pack(anchor="w", pady=(2, 8))
        self._mon["admin_user_lbl"] = ctk.CTkLabel(
            outer, text="Active User: Not logged in",
            font=ctk.CTkFont(size=12, weight="bold"), text_color=C["accent"])
        self._mon["admin_user_lbl"].pack(anchor="w", pady=(0, 8))
        self._mon["admin_live_lbl"] = ctk.CTkLabel(
            outer, text="Live Window Activity: —",
            font=ctk.CTkFont(size=12), text_color=C["text"])
        self._mon["admin_live_lbl"].pack(anchor="w", pady=(0, 8))
        self._mon["admin_hist_box"] = ctk.CTkTextbox(
            outer, font=ctk.CTkFont("Consolas", 11),
            fg_color=C["card"], text_color="#b06cff",
            corner_radius=10, border_color=C["border"], border_width=1)
        self._mon["admin_hist_box"].pack(fill="both", expand=True)
        self._mon["admin_hist_box"].configure(state="disabled")

    # ══════════════════════════════════════════════════════════════════════════
    # TAB 5 — SERVICES
    # ══════════════════════════════════════════════════════════════════════════
    def _build_services_tab(self, parent):
        body = ctk.CTkFrame(parent, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=4, pady=4)

        left = ctk.CTkFrame(body, fg_color="transparent", width=340)
        left.pack(side="left", fill="y", padx=(0,12))
        left.pack_propagate(False)

        ctk.CTkLabel(left, text="SERVICES",
                     font=ctk.CTkFont(size=10, weight="bold"),
                     text_color=C["muted"]).pack(anchor="w", pady=(0,8))
        for svc in SERVICES:
            self._svc_card(left, svc)

        right = ctk.CTkFrame(body, fg_color="transparent")
        right.pack(side="left", fill="both", expand=True)

        log_hdr = ctk.CTkFrame(right, fg_color="transparent", height=28)
        log_hdr.pack(fill="x")
        log_hdr.pack_propagate(False)
        ctk.CTkLabel(log_hdr, text="LIVE OUTPUT",
                     font=ctk.CTkFont(size=10, weight="bold"),
                     text_color=C["muted"]).pack(side="left")
        ctk.CTkButton(log_hdr, text="Clear", command=self._clear_log,
                      fg_color="transparent", hover_color=C["border"],
                      text_color=C["muted"], font=ctk.CTkFont(size=11),
                      width=50, height=24, corner_radius=6).pack(side="right")

        self.log_box = ctk.CTkTextbox(
            right, font=ctk.CTkFont("Consolas", 11),
            fg_color=C["card"], text_color="#94a3b8",
            corner_radius=10, border_color=C["border"], border_width=1, wrap="word")
        self.log_box.pack(fill="both", expand=True, pady=(8,0))
        self.log_box.configure(state="disabled")

    def _svc_card(self, parent, svc):
        card = ctk.CTkFrame(parent, fg_color=C["card"], corner_radius=12,
                            border_color=C["border"], border_width=1)
        card.pack(fill="x", pady=5)
        self.card_frm[svc["id"]] = card
        inner = ctk.CTkFrame(card, fg_color="transparent")
        inner.pack(fill="x", padx=16, pady=12)

        ll = ctk.CTkFrame(inner, fg_color="transparent")
        ll.pack(side="left", fill="x", expand=True)
        dot = ctk.CTkLabel(ll, text="●", font=ctk.CTkFont(size=14), text_color=C["muted"])
        dot.pack(side="left", padx=(0,10))
        self.dot_lbl[svc["id"]] = dot
        info = ctk.CTkFrame(ll, fg_color="transparent")
        info.pack(side="left")
        ctk.CTkLabel(info, text=svc["name"],
                     font=ctk.CTkFont(size=14, weight="bold"),
                     text_color=C["text"]).pack(anchor="w")
        ctk.CTkLabel(info, text=svc["desc"],
                     font=ctk.CTkFont(size=11),
                     text_color=C["muted"]).pack(anchor="w")

        rr = ctk.CTkFrame(inner, fg_color="transparent")
        rr.pack(side="right")
        sl = ctk.CTkLabel(rr, text="Stopped",
                          font=ctk.CTkFont(size=11), text_color=C["muted"], width=70)
        sl.pack(anchor="e")
        self.sta_lbl[svc["id"]] = sl
        btn = ctk.CTkButton(rr, text="Start",
                            command=lambda s=svc: self._toggle_svc(s["id"]),
                            fg_color=C["purple"], hover_color="#8855cc",
                            font=ctk.CTkFont(size=11), width=70, height=26, corner_radius=6)
        btn.pack(anchor="e", pady=(4,0))
        svc["_btn"] = btn

    # ══════════════════════════════════════════════════════════════════════════
    # UI HELPER WIDGETS
    # ══════════════════════════════════════════════════════════════════════════
    def _row_frame(self, parent, cols=2):
        f = ctk.CTkFrame(parent, fg_color="transparent")
        f.pack(fill="x", padx=6, pady=3)
        for i in range(cols): f.columnconfigure(i, weight=1)
        return f

    def _stat_card(self, parent, col, icon, label, key, color, default, sub=""):
        card = ctk.CTkFrame(parent, fg_color=C["card"], corner_radius=12,
                            border_color=C["border"], border_width=1)
        card.grid(row=0, column=col, padx=4, pady=2, sticky="nsew")
        inner = ctk.CTkFrame(card, fg_color="transparent")
        inner.pack(fill="both", padx=14, pady=10)
        ctk.CTkLabel(inner, text=f"{icon}  {label}",
                     font=ctk.CTkFont(size=10), text_color=C["muted"]).pack(anchor="w")
        lbl = ctk.CTkLabel(inner, text=default,
                           font=ctk.CTkFont("Segoe UI", 24, weight="bold"),
                           text_color=color)
        lbl.pack(anchor="w")
        if sub:
            ctk.CTkLabel(inner, text=sub,
                         font=ctk.CTkFont(size=9), text_color=C["dim"]).pack(anchor="w")
        self._mon[key] = lbl

    def _big_card(self, parent, row, col, icon, label, key, color, default, sub):
        card = ctk.CTkFrame(parent, fg_color=C["card2"], corner_radius=10,
                            border_color=C["border"], border_width=1)
        card.grid(row=row, column=col, padx=4, pady=4, sticky="nsew")
        inner = ctk.CTkFrame(card, fg_color="transparent")
        inner.pack(fill="both", padx=14, pady=12)
        ctk.CTkLabel(inner, text=f"{icon}  {label}",
                     font=ctk.CTkFont(size=10, weight="bold"), text_color=C["muted"]).pack(anchor="w")
        lbl = ctk.CTkLabel(inner, text=default,
                           font=ctk.CTkFont("Segoe UI", 30, weight="bold"),
                           text_color=color)
        lbl.pack(anchor="w")
        ctk.CTkLabel(inner, text=sub,
                     font=ctk.CTkFont(size=10), text_color=C["muted"]).pack(anchor="w")
        self._mon[key] = lbl

    def _sys_card(self, parent, col, icon, label, key, color, default):
        card = ctk.CTkFrame(parent, fg_color=C["card"], corner_radius=12,
                            border_color=C["border"], border_width=1)
        card.grid(row=0, column=col, padx=4, pady=2, sticky="nsew")
        inner = ctk.CTkFrame(card, fg_color="transparent")
        inner.pack(fill="both", padx=12, pady=10)
        ctk.CTkLabel(inner, text=f"{icon}  {label}",
                     font=ctk.CTkFont(size=10), text_color=C["muted"]).pack(anchor="w")
        lbl = ctk.CTkLabel(inner, text=default,
                           font=ctk.CTkFont("Segoe UI", 20, weight="bold"),
                           text_color=color)
        lbl.pack(anchor="w")
        self._mon[key] = lbl

    def _det_card(self, parent, col, label, key, default, color, desc):
        card = ctk.CTkFrame(parent, fg_color=C["card"], corner_radius=12,
                            border_color=C["border"], border_width=1)
        card.grid(row=0, column=col, padx=4, pady=3, sticky="nsew")
        inner = ctk.CTkFrame(card, fg_color="transparent")
        inner.pack(fill="both", padx=14, pady=10)
        ctk.CTkLabel(inner, text=label,
                     font=ctk.CTkFont(size=10, weight="bold"), text_color=C["muted"]).pack(anchor="w")
        lbl = ctk.CTkLabel(inner, text=default,
                           font=ctk.CTkFont("Segoe UI", 26, weight="bold"),
                           text_color=color)
        lbl.pack(anchor="w")
        ctk.CTkLabel(inner, text=desc,
                     font=ctk.CTkFont(size=9), text_color=C["muted"],
                     wraplength=200, justify="left").pack(anchor="w", pady=(2,0))
        self._mon[key] = lbl

    def _sec_header(self, parent, text):
        ctk.CTkLabel(parent, text=text,
                     font=ctk.CTkFont(size=11, weight="bold"),
                     text_color=C["muted"]).pack(anchor="w", padx=6, pady=(10,2))

    def _textbox(self, parent, height=80, color="#94a3b8"):
        tb = ctk.CTkTextbox(parent, height=height,
                            font=ctk.CTkFont("Consolas", 11),
                            fg_color=C["card"], text_color=color,
                            corner_radius=8, border_color=C["border"], border_width=1)
        tb.pack(fill="x", padx=6, pady=(0,6))
        tb.configure(state="disabled")
        return tb

    # ══════════════════════════════════════════════════════════════════════════
    # CANVAS DRAWINGS
    # ══════════════════════════════════════════════════════════════════════════
    def _draw_sparkline(self, canvas, data, color, width=None):
        canvas.delete("all")
        w = width or canvas.winfo_width() or 600
        h = canvas.winfo_height() or 80
        if not data or len(data) < 2:
            return
        mn, mx = min(data), max(data)
        rng = max(1, mx - mn)
        pts = []
        for i, v in enumerate(data):
            x = int(i / (len(data)-1) * (w-20)) + 10
            y = int((1 - (v - mn)/rng) * (h-16)) + 8
            pts.extend([x, y])
        if len(pts) >= 4:
            canvas.create_line(*pts, fill=color, width=2, smooth=True)
        # Fill under
        fill_pts = [10, h-4] + pts + [pts[-2], h-4]
        canvas.create_polygon(*fill_pts, fill=color, stipple="gray25", outline="")

    def _draw_circadian_curve(self):
        circ_scores = [20,15,15,18,22,38,55,70,88,92,90,85,75,80,88,90,85,72,60,50,40,32,25,20]
        hour = datetime.now().hour
        self.after(100, lambda: self._render_circadian(circ_scores, hour))

    def _render_circadian(self, scores, cur_hour):
        canvas = self._mon.get("circ_canvas")
        if not canvas:
            return
        canvas.delete("all")
        w = canvas.winfo_width() or 600
        h = canvas.winfo_height() or 80
        pts = []
        for i, v in enumerate(scores):
            x = int(i / 23 * (w-20)) + 10
            y = int((1 - v/100) * (h-16)) + 8
            pts.extend([x, y])
        fill_pts = [10, h-4] + pts + [pts[-2], h-4]
        canvas.create_polygon(*fill_pts, fill=C["accent"], stipple="gray25", outline="")
        if len(pts) >= 4:
            canvas.create_line(*pts, fill=C["accent"], width=2, smooth=True)
        # Current hour marker
        cx = int(cur_hour / 23 * (w-20)) + 10
        cy = int((1 - scores[cur_hour]/100) * (h-16)) + 8
        canvas.create_oval(cx-6, cy-6, cx+6, cy+6, fill=C["green"], outline=C["card"])
        canvas.create_text(cx, cy-16, text="▲", fill=C["green"], font=("Segoe UI", 8, "bold"))

    def _draw_flowchart(self, w, h):
        fc = self._fc
        fc.delete("all")
        pad = 30
        mid = w // 2

        def box(x, y, bw, bh, text, color, shape="rect", sub=""):
            if shape == "diamond":
                pts = [x+bw//2,y, x+bw,y+bh//2, x+bw//2,y+bh, x,y+bh//2]
                fc.create_polygon(pts, fill=blend(C["card"], color, 0.13), outline=color, width=2)
            else:
                fc.create_rectangle(x, y, x+bw, y+bh,
                                    fill=blend(C["card"], color, 0.09), outline=color, width=2)
                # Rounded look via extra rect
            fc.create_text(x+bw//2, y+bh//2-(8 if sub else 0),
                           text=text, fill=color,
                           font=("Consolas", 10, "bold"), anchor="center")
            if sub:
                fc.create_text(x+bw//2, y+bh//2+10, text=sub,
                               fill=C["muted"], font=("Consolas", 8), anchor="center")

        def arrow(x1, y1, x2, y2, color=C["dim"]):
            fc.create_line(x1, y1, x2, y2, fill=color, width=1, arrow="last",
                           arrowshape=(8,10,4))

        # Layout
        bw, bh = 150, 40
        gutter  = 30

        # Row 0 — title
        fc.create_text(mid, 20, text="BurnoutGuard Detection Pipeline",
                       fill=C["text"], font=("Segoe UI", 13, "bold"), anchor="center")

        # Row 1 — input sources
        y1 = 48
        sources = [
            ("Keyboard\nEvents", C["purple"]),
            ("Mouse\nEvents",    C["accent"]),
            ("Active\nWindow",   C["blue"]),
            ("Session\nTime",    C["green"]),
        ]
        src_xs = []
        step = (w - 2*pad) // len(sources)
        for i,(txt,col) in enumerate(sources):
            x = pad + i*step + step//2 - 70
            box(x, y1, 140, 44, txt, col)
            src_xs.append(x+70)

        # Row 2 — tracker
        y2 = y1 + 44 + gutter
        box(mid-100, y2, 200, 40, "Desktop Agent\n+ LiveTracker", C["accent"])
        for sx in src_xs:
            arrow(sx, y1+44, mid, y2)

        # Row 3 — feature engineering
        y3 = y2 + 40 + gutter
        box(mid-110, y3, 220, 40, "Feature Engineering\nKPS · HRV · Circadian", C["purple"])
        arrow(mid, y2+40, mid, y3)

        # Row 4 — ML
        y4 = y3 + 40 + gutter
        ml_x = mid - 90
        box(ml_x, y4, 180, 44, "ML Ensemble\nRF + XGBoost", C["amber"], shape="diamond")
        arrow(mid, y3+40, mid, y4)

        # Row 5 — risk levels
        y5 = y4 + 50 + gutter
        risk_cols = [C["green"], C["amber"], C["red"]]
        risk_lbls = ["LOW RISK", "MEDIUM RISK", "HIGH RISK"]
        step5 = (w - 2*pad) // 3
        rx = []
        for i,(rl,rc) in enumerate(zip(risk_lbls, risk_cols)):
            x = pad + i*step5 + step5//2 - 70
            box(x, y5, 140, 36, rl, rc)
            rx.append(x+70)
            arrow(mid, y4+50, x+70, y5)

        # Row 6 — action
        y6 = y5 + 36 + gutter
        box(mid-100, y6, 200, 40, "Personalized Actions\n& Wellness Alerts", C["purple"])
        for x in rx:
            arrow(x, y5+36, mid, y6)

        # Row 7 — admin
        y7 = y6 + 40 + gutter
        box(mid-90, y7, 180, 36, "Admin Dashboard\nTeam Overview", C["accent"])
        arrow(mid, y6+40, mid, y7)

    # ══════════════════════════════════════════════════════════════════════════
    # POLLING — monitor tab
    # ══════════════════════════════════════════════════════════════════════════
    def _poll_monitor(self):
        try:
            snap = self.tracker.snapshot()
            idle = snap["is_idle"]

            # Status pill
            self._mon["status_pill"].configure(
                text="● IDLE" if idle else "● ACTIVE",
                text_color=C["amber"] if idle else C["green"])

            # Focus bar
            pct = snap["focus_pct"] / 100
            bar_c = C["amber"] if pct < 0.3 else (C["accent"] if pct < 0.6 else C["green"])
            self._mon["focus_bar"].configure(progress_color=bar_c)
            self._mon["focus_bar"].set(max(0.0, min(1.0, pct)))
            self._mon["focus_pct_lbl"].configure(
                text=f"{snap['focus_pct']}% active", text_color=bar_c)

            # Small cards
            self._mon["active_t"].configure(text=fmt_sec(snap["active_secs"]))
            self._mon["idle_t"].configure(text=fmt_sec(snap["idle_secs"]))
            self._mon["screen_t"].configure(text=fmt_sec(snap["screen_secs"]))
            self._mon["keys"].configure(text=f"{snap['key_count']:,}")
            self._mon["mouse"].configure(text=f"{snap['mouse_count']:,}")

            # Active app
            app = get_active_window()
            self._mon["active_app"].configure(text=(app[:32]+"…" if len(app)>32 else app) or "—")
            active_user_name = self._session.get("name") or "Not logged in"
            active_user_text = f"Active User: {active_user_name}"
            for k in ("live_user_lbl", "hist_user_lbl", "usage_user_lbl", "admin_user_lbl"):
                if k in self._mon:
                    self._mon[k].configure(text=active_user_text)

            # Big detail cards
            self._mon["dk_keys"].configure(text=f"{snap['key_count']:,}")
            self._mon["dk_mouse"].configure(text=f"{snap['mouse_count']:,}")
            self._mon["dk_scrn"].configure(text=fmt_sec(snap["screen_secs"]))
            self._mon["dk_act"].configure(text=fmt_sec(snap["active_secs"]))
            self._mon["dk_idle"].configure(text=fmt_sec(snap["idle_secs"]))
            self._mon["dk_focus"].configure(text=f"{snap['focus_pct']}%")

            # Focus score colour
            fs = snap["focus_pct"]
            fc_col = C["red"] if fs < 30 else (C["amber"] if fs < 60 else C["green"])
            self._mon["dk_focus"].configure(text_color=fc_col)

            # System stats
            cpu = psutil.cpu_percent(interval=None)
            mem = psutil.virtual_memory()
            bat = psutil.sensors_battery()

            cpu_c = C["red"] if cpu > 85 else (C["amber"] if cpu > 60 else C["blue"])
            self._mon["cpu"].configure(text=f"{cpu:.0f}%", text_color=cpu_c)
            ram_p = mem.percent
            ram_c = C["red"] if ram_p > 85 else (C["amber"] if ram_p > 60 else C["purple"])
            self._mon["ram"].configure(text=f"{ram_p:.0f}%  ({mem.used/1024**3:.1f}GB)", text_color=ram_c)
            if bat:
                bat_c = C["red"] if bat.percent<15 else (C["amber"] if bat.percent<30 else C["green"])
                self._mon["bat"].configure(text=f"{int(bat.percent)}%{'⚡' if bat.power_plugged else ''}", text_color=bat_c)
            else:
                self._mon["bat"].configure(text="Desktop PC")

            # Top processes
            try:
                procs = []
                for p in psutil.process_iter(["name","cpu_percent","memory_percent"]):
                    try: procs.append((p.info["name"] or "?", p.info["cpu_percent"] or 0.0, p.info["memory_percent"] or 0.0))
                    except (psutil.NoSuchProcess, psutil.AccessDenied): pass
                procs.sort(key=lambda x: x[1], reverse=True)
                lines = [f"  {'Process':<26}  {'CPU%':>5}  {'RAM%':>5}",
                         "  " + "─"*42]
                for nm,cp,mp in procs[:5]:
                    lines.append(f"  {nm[:24]:<26}  {cp:>4.1f}%  {mp:>4.1f}%")
                self._set_textbox(self._mon["proc_box"], "\n".join(lines))
            except Exception: pass

            # Window history (last 12)
            log = self._history.get_log(12)
            if log:
                lines = [f"  [{e['ts']}]  {e['title'][:60]}  ({e['duration']}s)" for e in reversed(log)]
                self._set_textbox(self._mon["win_box"], "\n".join(lines))
            else:
                self._set_textbox(self._mon["win_box"], "  No windows tracked yet.")

            # ── Update detections tab ─────────────────────────────────────────
            self._mon["hrv_rmssd"].configure(text=f"{snap['hrv_rmssd']}ms",
                text_color=C["green"] if snap["hrv_rmssd"]>50 else (C["amber"] if snap["hrv_rmssd"]>35 else C["red"]))
            self._mon["hrv_sdnn"].configure(text=f"{snap['hrv_sdnn']}ms")
            self._mon["hrv_pnn50"].configure(text=f"{snap['pnn50']}%")
            self._hrv_history.append(snap["hrv_rmssd"])
            self._draw_sparkline(self._mon["hrv_canvas"], list(self._hrv_history), C["green"])

            cl = snap["cog_load"]
            cl_c = C["green"] if cl<30 else (C["amber"] if cl<65 else C["red"])
            self._mon["cog_score"].configure(text=f"{cl}%", text_color=cl_c)
            self._mon["kps"].configure(text=str(snap["kps"]))
            self._mon["cog_label"].configure(text=snap["cog_label"],
                text_color=C["green"] if snap["cog_label"]=="LOW" else (C["amber"] if snap["cog_label"]=="MODERATE" else C["red"]))

            surge_txt = "🔴 SURGE!" if snap["surge"] else "✅ Normal"
            surge_c   = C["red"] if snap["surge"] else C["green"]
            self._mon["surge"].configure(text=surge_txt, text_color=surge_c)
            st = snap["stress"]
            st_c = C["green"] if st<40 else (C["amber"] if st<70 else C["red"])
            self._mon["stress"].configure(text=f"{st}%", text_color=st_c)
            self._mon["recovery"].configure(text=f"{100-st}%",
                text_color=C["green"] if (100-st)>60 else C["amber"])
            self._stress_history.append(st)
            self._draw_sparkline(self._mon["stress_canvas"], list(self._stress_history), C["red"])

            ca = snap["circ_alert"]
            ca_c = C["green"] if ca>70 else (C["amber"] if ca>40 else C["red"])
            self._mon["circ_alert"].configure(text=f"{ca}%", text_color=ca_c)
            hour = datetime.now().hour
            phases = {range(0,6):"Rest 🌙", range(6,9):"Wake-Up ☀️",
                      range(9,12):"Peak Alert 🎯", range(12,14):"Post-Lunch Dip 😴",
                      range(14,17):"Afternoon Peak ⚡", range(17,20):"Wind-Down 🌇",
                      range(20,24):"Rest 🌙"}
            phase = next((v for r,v in phases.items() if hour in r), "—")
            self._mon["circ_phase"].configure(text=phase)
            self._render_circadian([20,15,15,18,22,38,55,70,88,92,90,85,75,80,88,90,85,72,60,50,40,32,25,20], hour)

            # ── Update history tab ────────────────────────────────────────────
            totals = self._history.get_totals()
            tot_lines = [f"  {'Application':<45}  {'Time':>10}",
                         "  " + "─"*60]
            for title, secs in totals[:20]:
                short = title[:43] if len(title)>43 else title
                tot_lines.append(f"  {short:<45}  {fmt_sec(secs):>10}")
            self._set_textbox(self._mon["hist_totals"], "\n".join(tot_lines))

            full_log = self._history.get_log(40)
            log_lines = [f"  [{e['ts']}]  {e['duration']:>4}s  {e['title'][:55]}" for e in full_log]
            self._set_textbox(self._mon["hist_log"], "\n".join(log_lines) if log_lines else "  No history yet.")
            if "admin_live_lbl" in self._mon:
                self._mon["admin_live_lbl"].configure(text=f"Live Window Activity: {app or '—'}")
            if "admin_hist_box" in self._mon:
                self._set_textbox(self._mon["admin_hist_box"], "\n".join(log_lines[-20:]) if log_lines else "  No history yet.")

            total_logged_seconds = sum(secs for _, secs in totals)
            active_hours = total_logged_seconds / 3600.0
            idle_hours = max(0.0, (snap["idle_secs"] / 3600.0))
            if "usage_hours_lbl" in self._mon:
                self._mon["usage_hours_lbl"].configure(text=f"{active_hours:.1f}h active")
            if "usage_canvas" in self._mon:
                self._draw_usage_donut(self._mon["usage_canvas"], active_hours, idle_hours)

        except Exception as exc:
            pass  # never crash the UI

        self.after(2000, self._poll_monitor)

    def _set_textbox(self, tb, text):
        tb.configure(state="normal")
        tb.delete("1.0", "end")
        tb.insert("end", text)
        tb.configure(state="disabled")

    def _draw_usage_donut(self, canvas, active_hours: float, idle_hours: float):
        canvas.delete("all")
        w = int(canvas.cget("width")); h = int(canvas.cget("height"))
        cx, cy = w // 2, h // 2
        radius = min(w, h) // 2 - 28
        total = max(0.1, active_hours + idle_hours)
        active_extent = (active_hours / total) * 360.0
        box = (cx - radius, cy - radius, cx + radius, cy + radius)
        canvas.create_oval(*box, outline=C["border"], width=18)
        canvas.create_arc(*box, start=90, extent=-active_extent, style="arc", outline=C["accent"], width=18)
        canvas.create_text(cx, cy - 8, text=f"{active_hours:.1f}h", fill=C["text"], font=("Segoe UI", 24, "bold"))
        canvas.create_text(cx, cy + 15, text="Active usage", fill=C["muted"], font=("Segoe UI", 10))

    # ══════════════════════════════════════════════════════════════════════════
    # SERVICE CONTROL
    # ══════════════════════════════════════════════════════════════════════════
    def _sync_agent_credentials(self, email: str, password: str):
        if not email or not password:
            return
        cfg_path = AGENT_DIR / "config.json"
        try:
            cfg = {}
            if cfg_path.exists():
                with open(cfg_path, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
            cfg["email"] = email.strip()
            cfg["password"] = password.strip()
            with open(cfg_path, "w", encoding="utf-8") as f:
                json.dump(cfg, f, indent=2)
            self._log_svc(f"✔ Desktop Agent account synced to: {email}")
            ag = self.services.get("agent")
            if ag and ag.is_running():
                threading.Thread(target=ag.stop, daemon=True).start()
                self.after(1500, lambda: threading.Thread(target=ag.start, daemon=True).start())
        except Exception as exc:
            self._log_svc(f"⚠ Could not sync Desktop Agent account: {exc}")

    def _on_auth_success(self, name: str, email: str, role: str, token: str, password: str = ""):
        self._session.update({
            "is_authenticated": True,
            "token": token or "",
            "name": name or "",
            "email": email or "",
            "role": role or "",
        })
        if password:
            self._sync_agent_credentials(email, password)
        self._set_service_controls_enabled(True)
        if not self._tracker_started:
            self.tracker.start()
            self._tracker_started = True
        self._scheduler.stop()
        time.sleep(0.05)
        self._scheduler.reset()
        self._scheduler.start()
        self._update_bt_profile_labels()
        self.deiconify()
        self.lift()
        self.focus_force()

    def _logout(self):
        # Keep backend running so the next login can still reach http://localhost:8080
        self._stop_all(keep_backend=True)
        self._session.update({
            "is_authenticated": False,
            "token": "",
            "name": "",
            "email": "",
            "role": "",
        })
        self._scheduler.stop()
        if self._tracker_started:
            self.tracker.stop()
            self._tracker_started = False
        self._set_service_controls_enabled(False)
        self.withdraw()
        self.after(150, lambda: self._show_create_account_dlg(auth_gate=True))

    def _set_service_controls_enabled(self, enabled: bool):
        state = "normal" if enabled else "disabled"
        for k in ("open", "start_all", "stop_all"):
            btn = self._hdr_buttons.get(k) if hasattr(self, "_hdr_buttons") else None
            if btn:
                btn.configure(state=state)
        for svc in SERVICES:
            btn = svc.get("_btn")
            if btn:
                btn.configure(state=state)
        if not enabled:
            self.status_bar.configure(
                text="Please log in. Backend starts automatically; Start All enables after login.",
                text_color=C["amber"],
            )

    def _auto_start_backend_if_needed(self):
        """Start Spring Boot on launcher startup (no login required). Idempotent."""
        try:
            backend_svc = next((s for s in SERVICES if s["id"] == "backend"), None)
            if not backend_svc:
                return
            sp = self.services.get("backend")
            if not sp:
                return
            if self._is_url_reachable(backend_svc.get("url")):
                sp.state = "running"
                try:
                    self._log_svc("ℹ Backend already running at http://localhost:8080")
                except Exception:
                    pass
                return
            if sp.is_running():
                return
            try:
                self._log_svc("▶ Auto-starting Backend (Spring Boot on :8080)…")
            except Exception:
                pass
            threading.Thread(target=sp.start, daemon=True).start()
        except Exception as exc:
            try:
                self._log_svc(f"⚠ Auto-start backend: {exc}")
            except Exception:
                pass

    def _start_all(self):
        if not self._session.get("is_authenticated"):
            self.status_bar.configure(
                text="Login required before starting backend/frontend/ML services.",
                text_color=C["amber"],
            )
            return
        self._log_svc("═"*55 + "\n  Starting all BurnoutGuard services…\n" + "═"*55)
        for svc in SERVICES:
            sp = self.services[svc["id"]]
            # If backend is already live on :8080, don't spawn a duplicate run.
            if svc["id"] == "backend" and self._is_url_reachable(svc.get("url")):
                sp.state = "running"
                self._log_svc("ℹ Backend already running on :8080, skipping duplicate start.")
                continue
            if not sp.is_running():
                threading.Thread(target=sp.start, daemon=True).start()
                time.sleep(1.5)

    def _stop_all(self, keep_backend=False):
        self._log_svc("─"*55 + "\n  Stopping all services…")
        for svc in reversed(SERVICES):
            if keep_backend and svc["id"] == "backend":
                continue
            threading.Thread(target=self.services[svc["id"]].stop, daemon=True).start()

    def _toggle_svc(self, sid):
        if not self._session.get("is_authenticated"):
            self.status_bar.configure(
                text="Login required before starting services.",
                text_color=C["amber"],
            )
            return
        sp = self.services[sid]
        if sp.is_running():
            threading.Thread(target=sp.stop, daemon=True).start()
        else:
            svc = next((s for s in SERVICES if s["id"] == sid), None)
            if svc and sid == "backend" and self._is_url_reachable(svc.get("url")):
                sp.state = "running"
                self._log_svc("ℹ Backend already running on :8080.")
                return
            threading.Thread(target=sp.start, daemon=True).start()

    def _open_browser(self):
        # Open in a private window to avoid stale cached web login (e.g., always "vetri")
        # and show a fresh web app session.
        try:
            subprocess.Popen(["cmd", "/c", "start", "msedge", "--inprivate", "http://localhost:3000"],
                             creationflags=subprocess.CREATE_NO_WINDOW)
            return
        except Exception:
            pass
        try:
            subprocess.Popen(["cmd", "/c", "start", "chrome", "--incognito", "http://localhost:3000"],
                             creationflags=subprocess.CREATE_NO_WINDOW)
            return
        except Exception:
            pass
        webbrowser.open("http://localhost:3000")

    def _clear_history(self):
        self._history._totals = {}
        self._history._log    = []
        self._history.save()

    # ══════════════════════════════════════════════════════════════════════════
    # TAB — BREAK TIMER
    # ══════════════════════════════════════════════════════════════════════════
    def _build_breaktimer_tab(self, parent):
        scroll = ctk.CTkScrollableFrame(parent, fg_color="transparent")
        scroll.pack(fill="both", expand=True)

        hdr = ctk.CTkFrame(scroll, fg_color="transparent")
        hdr.pack(fill="x", padx=6, pady=(8, 4))
        ctk.CTkLabel(hdr, text="⏰  Break Timer & Schedule",
                     font=ctk.CTkFont("Segoe UI", 20, weight="bold"),
                     text_color=C["text"]).pack(side="left")

        info = ctk.CTkFrame(scroll, fg_color=C["card"], corner_radius=12,
                            border_color=C["accent"], border_width=1)
        info.pack(fill="x", padx=6, pady=6)
        ii = ctk.CTkFrame(info, fg_color="transparent")
        ii.pack(fill="x", padx=20, pady=14)
        self._mon["bt_user_lbl"] = ctk.CTkLabel(
            ii, text="No account yet — click ⚙ Edit Account above to get started",
            font=ctk.CTkFont("Segoe UI", 15, weight="bold"), text_color=C["accent"])
        self._mon["bt_user_lbl"].pack(anchor="w")
        self._mon["bt_sched_lbl"] = ctk.CTkLabel(
            ii, text="", font=ctk.CTkFont(size=12), text_color=C["muted"])
        self._mon["bt_sched_lbl"].pack(anchor="w", pady=(2, 0))

        ring_sec = ctk.CTkFrame(scroll, fg_color=C["card2"], corner_radius=14,
                                border_color=C["border"], border_width=1)
        ring_sec.pack(fill="x", padx=6, pady=6)

        self._mon["bt_canvas"] = ctk.CTkCanvas(
            ring_sec, width=300, height=300, bg=C["card2"], highlightthickness=0)
        self._mon["bt_canvas"].pack(pady=(20, 6))

        self._mon["bt_phase"] = ctk.CTkLabel(
            ring_sec, text="💻  WORK SESSION",
            font=ctk.CTkFont("Segoe UI", 14, weight="bold"), text_color=C["green"])
        self._mon["bt_phase"].pack()
        self._mon["bt_countdown"] = ctk.CTkLabel(
            ring_sec, text="--:--",
            font=ctk.CTkFont("Segoe UI", 44, weight="bold"), text_color=C["text"])
        self._mon["bt_countdown"].pack()
        self._mon["bt_breaks"] = ctk.CTkLabel(
            ring_sec, text="Breaks taken today: 0",
            font=ctk.CTkFont(size=12), text_color=C["muted"])
        self._mon["bt_breaks"].pack(pady=(4, 20))

        btn_row = ctk.CTkFrame(scroll, fg_color="transparent")
        btn_row.pack(fill="x", padx=50, pady=8)
        for i in range(4): btn_row.columnconfigure(i, weight=1)

        def mk(col, txt, cmd, fg, hv):
            ctk.CTkButton(btn_row, text=txt, command=cmd, fg_color=fg,
                          hover_color=hv, font=ctk.CTkFont(size=13, weight="bold"),
                          height=40, corner_radius=10).grid(
                row=0, column=col, padx=5, sticky="ew")

        mk(0, "☕ Take Break",  self._take_break_now, C["green"],  "#00ba78")
        mk(1, "⏭ Skip Break",  self._skip_break,     C["amber"],  "#cc8a00")
        mk(2, "🔄 Reset",       self._reset_timer,    C["blue"],   "#3a80cc")
        mk(3, "⏹ Stop Timer",  self._stop_timer,     C["dim"],    C["border"])

        self._mon["bt_start_btn"] = ctk.CTkButton(
            scroll, text="▶  Start Break Timer", command=self._start_timer,
            fg_color=C["purple"], hover_color="#8855cc",
            font=ctk.CTkFont(size=14, weight="bold"),
            height=46, corner_radius=10, width=320)
        self._mon["bt_start_btn"].pack(pady=10)

        self._sec_header(scroll, "👁️  Eye-Care Reminders Log  (20-20-20 Rule)")
        self._mon["bt_eye_log"] = self._textbox(scroll, height=90, color=C["accent"])

        self.after(300, self._draw_bt_ring)

    # ── Ring canvas ───────────────────────────────────────────────────────────
    def _draw_bt_ring(self):
        canvas = self._mon.get("bt_canvas")
        if not canvas:
            return
        try:
            canvas.delete("all")
        except Exception:
            return
        cx, cy, r = 150, 150, 108

        sched = self._profile.schedule
        if not sched:
            canvas.create_arc(cx-r, cy-r, cx+r, cy+r, start=0, extent=359.9,
                              outline=C["border"], width=14, style="arc")
            canvas.create_text(cx, cy, text="Set up your\naccount first",
                               fill=C["muted"], font=("Segoe UI", 13, "bold"),
                               justify="center")
            return

        total    = self._scheduler.total
        elapsed  = self._scheduler.elapsed
        phase    = self._scheduler.phase
        progress = min(1.0, elapsed / total) if total > 0 else 0
        ring_c   = C["amber"] if phase == "break" else C["green"]

        canvas.create_arc(cx-r, cy-r, cx+r, cy+r, start=0, extent=359.9,
                          outline=C["border"], width=14, style="arc")
        if progress > 0.001:
            canvas.create_arc(cx-r, cy-r, cx+r, cy+r,
                              start=90, extent=-(progress * 359.9),
                              outline=ring_c, width=14, style="arc")
        rem  = self._scheduler.remaining
        canvas.create_text(cx, cy - 14, text=f"{rem//60:02d}:{rem%60:02d}",
                           fill=C["text"], font=("Segoe UI", 34, "bold"))
        canvas.create_text(cx, cy + 26, text="BREAK" if phase=="break" else "WORK",
                           fill=ring_c, font=("Segoe UI", 13, "bold"))

    # ── Scheduler callbacks (called via self.after → main thread) ─────────────
    def _on_sched_tick(self):
        try:
            self._draw_bt_ring()
            if not self._profile.schedule:
                return
            rem   = self._scheduler.remaining
            phase = self._scheduler.phase
            c     = C["amber"] if phase == "break" else C["green"]
            self._mon["bt_phase"].configure(
                text="☕  BREAK TIME" if phase=="break" else "💻  WORK SESSION",
                text_color=c)
            self._mon["bt_countdown"].configure(
                text=f"{rem//60:02d}:{rem%60:02d}", text_color=c)
            self._mon["bt_breaks"].configure(
                text=f"Breaks taken today: {self._scheduler.break_count}")
        except Exception:
            pass

    def _on_break_due(self):
        if self._alert_open:
            return
        threading.Thread(target=lambda: _play_tone("break"), daemon=True).start()
        self._show_break_alert()

    def _on_eye_care_due(self):
        threading.Thread(target=lambda: _play_tone("eye"), daemon=True).start()
        ts = datetime.now().strftime("%H:%M")
        self._bt_eye_lines.append(
            f"  [{ts}]  👁 Look 20 ft away for 20 seconds — 20-20-20 rule")
        try:
            self._set_textbox(self._mon["bt_eye_log"],
                              "\n".join(self._bt_eye_lines[-8:]))
        except Exception:
            pass

    # ── Break alert popup ─────────────────────────────────────────────────────
    def _show_break_alert(self):
        self._alert_open = True
        dlg = ctk.CTkToplevel(self)
        dlg.title("⏰ Break Time! — BurnoutGuard")
        dlg.geometry("500x510")
        dlg.resizable(False, False)
        dlg.attributes("-topmost", True)
        dlg.configure(fg_color=C["bg"])
        dlg.update_idletasks()
        sw, sh = dlg.winfo_screenwidth(), dlg.winfo_screenheight()
        dlg.geometry(f"500x510+{(sw-500)//2}+{(sh-510)//2}")

        ctk.CTkFrame(dlg, fg_color=C["amber"], corner_radius=0, height=6).pack(fill="x")

        main = ctk.CTkFrame(dlg, fg_color="transparent")
        main.pack(fill="both", expand=True, padx=34, pady=14)

        ctk.CTkLabel(main, text="🔔", font=ctk.CTkFont(size=58)).pack(pady=(4, 2))

        name     = self._profile.name or "there"
        sched    = self._profile.schedule
        brk_mins = (sched["break"] // 60) if sched else 5

        ctk.CTkLabel(main, text=f"Hey {name}, it's break time!",
                     font=ctk.CTkFont("Segoe UI", 22, weight="bold"),
                     text_color=C["text"]).pack()
        ctk.CTkLabel(main, text=f"You have earned a {brk_mins}-minute break 🌿",
                     font=ctk.CTkFont("Segoe UI", 15),
                     text_color=C["amber"]).pack(pady=(4, 6))

        tips = {"student": "👁 Rest eyes  ·  🚶 Stretch  ·  💧 Hydrate",
                "employee": "🧘 Step away  ·  💧 Hydrate  ·  🌿 Breathe"}
        ctk.CTkLabel(main, text=tips.get(self._profile.role,
                     "💧 Hydrate  ·  🚶 Stretch  ·  👁 Rest eyes"),
                     font=ctk.CTkFont(size=13), text_color=C["muted"]).pack(pady=(0, 8))

        if self._profile.role == "student" and self._profile.eye_care:
            ctk.CTkLabel(main, text="👁️  20-20-20: Look 20ft away for 20 seconds",
                         font=ctk.CTkFont(size=12, weight="bold"),
                         text_color=C["accent"]).pack(pady=(0, 6))

        ctk.CTkFrame(main, height=1, fg_color=C["border"]).pack(fill="x", pady=10)

        br = ctk.CTkFrame(main, fg_color="transparent")
        br.pack(fill="x")
        br.columnconfigure(0, weight=1); br.columnconfigure(1, weight=1)

        def start_break():
            self._scheduler.begin_break()
            self._alert_open = False; dlg.destroy()

        def skip_break():
            self._scheduler.skip_break()
            self._alert_open = False; dlg.destroy()

        dlg.protocol("WM_DELETE_WINDOW", skip_break)

        ctk.CTkButton(br, text="☕  Start Break", command=start_break,
                      fg_color=C["green"], hover_color="#00ba78",
                      font=ctk.CTkFont(size=14, weight="bold"),
                      height=46, corner_radius=11).grid(
            row=0, column=0, padx=(0, 8), sticky="ew")
        ctk.CTkButton(br, text="⏭  Skip Break", command=skip_break,
                      fg_color=C["dim"], hover_color=C["border"],
                      font=ctk.CTkFont(size=14, weight="bold"),
                      height=46, corner_radius=11).grid(
            row=0, column=1, padx=(8, 0), sticky="ew")

        self._pulse_alert(dlg, 0)

    def _pulse_alert(self, dlg, count):
        try:
            if not dlg.winfo_exists(): return
            dlg.configure(fg_color="#0a1020" if count % 2 == 0 else C["bg"])
            if count < 6:
                self.after(280, lambda: self._pulse_alert(dlg, count + 1))
        except Exception:
            pass

    # ── Create / Edit Account dialog ──────────────────────────────────────────
    def _show_create_account_dlg(self, auth_gate: bool = False):
        import urllib.request as _ureq, urllib.error as _uerr, json as _ujson
        def _hash_pw(pw: str) -> str:
            return hashlib.sha256((pw or "").encode("utf-8")).hexdigest()

        dlg = ctk.CTkToplevel(self)
        dlg.title("Login / Register — BurnoutGuard" if auth_gate else "Account — BurnoutGuard")
        dlg.geometry("560x800")
        dlg.resizable(False, False)
        dlg.attributes("-topmost", True)
        dlg.configure(fg_color=C["bg"])
        dlg.update_idletasks()
        x = self.winfo_x() + self.winfo_width()//2 - 280
        y = max(10, self.winfo_y() + self.winfo_height()//2 - 400)
        dlg.geometry(f"+{x}+{y}")
        if auth_gate:
            dlg.protocol("WM_DELETE_WINDOW", self.on_closing)

        ctk.CTkFrame(dlg, fg_color=C["purple"], corner_radius=0, height=6).pack(fill="x")

        # ── Tab switcher (Login / Register) ─────────────────────────────────
        tab_bar = ctk.CTkFrame(dlg, fg_color=C["panel"], corner_radius=0, height=46)
        tab_bar.pack(fill="x")
        tab_bar.pack_propagate(False)

        mode_v         = ctk.StringVar(value="login")
        tab_login_btn  = [None]
        tab_reg_btn    = [None]
        content_frames = {}

        def switch_mode(m):
            mode_v.set(m)
            for k, f in content_frames.items():
                if k == m:
                    f.pack(fill="both", expand=True)
                else:
                    f.pack_forget()
            if tab_login_btn[0]:
                tab_login_btn[0].configure(
                    fg_color=C["purple"] if m=="login" else "transparent",
                    text_color=C["text"] if m=="login" else C["muted"])
            if tab_reg_btn[0]:
                tab_reg_btn[0].configure(
                    fg_color=C["purple"] if m=="register" else "transparent",
                    text_color=C["text"] if m=="register" else C["muted"])

        tb = ctk.CTkButton(
            tab_bar, text="🔑  Sign In", command=lambda: switch_mode("login"),
            fg_color=C["purple"] if mode_v.get()=="login" else "transparent",
            hover_color=C["dim"],
            text_color=C["text"] if mode_v.get()=="login" else C["muted"],
            font=ctk.CTkFont(size=13, weight="bold"),
            width=250, height=42, corner_radius=0)
        tb.pack(side="left")
        tab_login_btn[0] = tb

        rb = ctk.CTkButton(
            tab_bar, text="✨  Create Account", command=lambda: switch_mode("register"),
            fg_color=C["purple"] if mode_v.get()=="register" else "transparent",
            hover_color=C["dim"],
            text_color=C["text"] if mode_v.get()=="register" else C["muted"],
            font=ctk.CTkFont(size=13, weight="bold"),
            width=250, height=42, corner_radius=0)
        rb.pack(side="left")
        tab_reg_btn[0] = rb

        container = ctk.CTkFrame(dlg, fg_color="transparent")
        container.pack(fill="both", expand=True)

        # ════════════════════════════════════════════════════════════════════
        # LOGIN PANEL
        # ════════════════════════════════════════════════════════════════════
        login_frame = ctk.CTkScrollableFrame(container, fg_color="transparent")
        content_frames["login"] = login_frame

        lin = ctk.CTkFrame(login_frame, fg_color="transparent")
        lin.pack(fill="both", padx=28, pady=10)

        ctk.CTkLabel(lin, text="👋  Welcome Back",
                     font=ctk.CTkFont("Segoe UI", 22, weight="bold"),
                     text_color=C["text"]).pack(anchor="w", pady=(14, 2))
        ctk.CTkLabel(lin, text="Sign in to your BurnoutGuard account to sync with the admin panel",
                     font=ctk.CTkFont(size=12), text_color=C["muted"]).pack(anchor="w", pady=(0, 14))

        # When backend is down, offline login must use the same email/password stored on this PC.
        if auth_gate and self._profile.is_registered:
            hint = ctk.CTkFrame(lin, fg_color=C["card2"], corner_radius=10,
                                border_color=C["amber"], border_width=1)
            hint.pack(fill="x", pady=(0, 12))
            hi = ctk.CTkFrame(hint, fg_color="transparent")
            hi.pack(fill="x", padx=12, pady=10)
            ctk.CTkLabel(
                hi,
                text=f"💡 Offline login on this PC: use email  {self._profile.email}  and the password you saved here.\n"
                     f"   The launcher starts Backend automatically; wait ~30s if Sign In says unreachable. "
                     f"When the API is up, any server account works.",
                font=ctk.CTkFont(size=11),
                text_color=C["amber"],
                justify="left",
                anchor="w",
            ).pack(anchor="w")

        if self._profile.is_registered and not auth_gate:
            info_f = ctk.CTkFrame(lin, fg_color=C["card"], corner_radius=10,
                                  border_color=C["accent"], border_width=1)
            info_f.pack(fill="x", pady=(0, 12))
            info_i = ctk.CTkFrame(info_f, fg_color="transparent")
            info_i.pack(fill="x", padx=14, pady=10)
            ctk.CTkLabel(info_i,
                         text=f"✔  Active profile: {self._profile.name}  ({self._profile.email})",
                         font=ctk.CTkFont(size=11, weight="bold"),
                         text_color=C["green"]).pack(anchor="w")

        ctk.CTkLabel(lin, text="Email",
                     font=ctk.CTkFont(size=12, weight="bold"),
                     text_color=C["muted"]).pack(anchor="w")
        li_email_v = ctk.StringVar(value="" if auth_gate else self._profile.email)
        ctk.CTkEntry(lin, textvariable=li_email_v, placeholder_text="your@email.com",
                     width=490, height=38, corner_radius=8,
                     fg_color=C["card"], border_color=C["border"],
                     text_color=C["text"]).pack(anchor="w", pady=(4, 12))

        ctk.CTkLabel(lin, text="Password",
                     font=ctk.CTkFont(size=12, weight="bold"),
                     text_color=C["muted"]).pack(anchor="w")
        li_pass_v = ctk.StringVar(value="")
        ctk.CTkEntry(lin, textvariable=li_pass_v, placeholder_text="Your password",
                     show="*", width=490, height=38, corner_radius=8,
                     fg_color=C["card"], border_color=C["border"],
                     text_color=C["text"]).pack(anchor="w", pady=(4, 18))

        li_status = ctk.CTkLabel(lin, text="",
                                 font=ctk.CTkFont(size=11), text_color=C["green"], wraplength=460)
        li_status.pack(anchor="w", pady=(0, 8))

        def do_login():
            em = li_email_v.get().strip()
            pw = li_pass_v.get().strip()
            if not em:
                li_status.configure(text="⚠  Please enter your email.", text_color=C["red"]); return
            if not pw:
                li_status.configure(text="⚠  Please enter your password.", text_color=C["red"]); return

            li_status.configure(text="⟳  Signing in…", text_color=C["accent"])
            dlg.update_idletasks()

            try:
                payload = _ujson.dumps({"email": em, "password": pw}).encode()
                req = _ureq.Request("http://localhost:8080/api/auth/login",
                                    data=payload,
                                    headers={"Content-Type": "application/json"},
                                    method="POST")
                with _ureq.urlopen(req, timeout=5) as resp:
                    data = _ujson.loads(resp.read())

                # Determine local role mapping
                backend_role = data.get("role", "")
                local_role   = self._profile.role or (
                    "student" if "student" in backend_role.lower() else "employee")
                local_sched  = self._profile.schedule_key
                if not local_sched:
                    keys = list(UserProfile.SCHEDULES.get(local_role, {}).keys())
                    local_sched = keys[0] if keys else ""

                self._profile.save(
                    name=data.get("name", em.split("@")[0]),
                    email=em, role=local_role, schedule_key=local_sched,
                    eye_care=self._profile.eye_care,
                    password_hash=_hash_pw(pw))
                self._scheduler.stop(); time.sleep(0.05)
                self._scheduler.reset(); self._scheduler.start()
                self._update_bt_profile_labels()
                self._on_auth_success(
                    name=data.get("name", em.split("@")[0]),
                    email=em,
                    role=data.get("role", local_role),
                    token=data.get("token", ""),
                    password=pw,
                )
                li_status.configure(
                    text=f"✔  Signed in as {data.get('name', em)}! Welcome back 🎉",
                    text_color=C["green"])
                dlg.after(1800, dlg.destroy)

            except _uerr.HTTPError as e:
                try:
                    err_data = _ujson.loads(e.read())
                    li_status.configure(text=f"✖  {err_data.get('error','Login failed')}",
                                        text_color=C["red"])
                except Exception:
                    li_status.configure(text=f"✖  Login failed (HTTP {e.code})",
                                        text_color=C["red"])
            except Exception:
                # Offline/local login fallback: allows "login first, start services later".
                local_ok = (
                    self._profile.is_registered
                    and em.lower() == (self._profile.email or "").lower()
                    and (
                        not self._profile.password_hash
                        or self._profile.password_hash == _hash_pw(pw)
                    )
                )
                if local_ok:
                    self._on_auth_success(
                        name=self._profile.name or em.split("@")[0],
                        email=em,
                        role=self._profile.role or "employee",
                        token="LOCAL_SESSION",
                        password=pw,
                    )
                    li_status.configure(
                        text="✔  Logged in locally (backend offline). Start services after entering app.",
                        text_color=C["green"])
                    dlg.after(1500, dlg.destroy)
                else:
                    if not self._profile.is_registered:
                        msg = (
                            "⚠  Cannot reach backend (http://localhost:8080).\n"
                            "   Use Create Account to register locally, then start Backend from the app."
                        )
                    elif em.lower() != (self._profile.email or "").lower():
                        msg = (
                            f"⚠  Backend unreachable. For offline login use this email:\n"
                            f"   {self._profile.email}"
                        )
                    elif self._profile.password_hash and self._profile.password_hash != _hash_pw(pw):
                        msg = "⚠  Wrong password for this PC’s saved account. Try again or use Create Account."
                    else:
                        msg = "⚠  Cannot sign in offline. Check email/password or start Backend."
                    li_status.configure(text=msg, text_color=C["amber"])

        ctk.CTkButton(lin, text="🔑  Sign In", command=do_login,
                      fg_color=C["purple"], hover_color="#8855cc",
                      font=ctk.CTkFont(size=14, weight="bold"),
                      height=46, corner_radius=10).pack(fill="x", pady=(4, 6))

        ctk.CTkLabel(lin,
                     text="Don't have an account? Click '✨ Create Account' above.",
                     font=ctk.CTkFont(size=11), text_color=C["muted"]).pack(pady=(6, 20))

        # ════════════════════════════════════════════════════════════════════
        # REGISTER PANEL
        # ════════════════════════════════════════════════════════════════════
        reg_frame = ctk.CTkScrollableFrame(container, fg_color="transparent")
        content_frames["register"] = reg_frame

        inner = ctk.CTkFrame(reg_frame, fg_color="transparent")
        inner.pack(fill="both", padx=28, pady=10)

        ctk.CTkLabel(inner, text="🧠  Create Your Account",
                     font=ctk.CTkFont("Segoe UI", 22, weight="bold"),
                     text_color=C["text"]).pack(anchor="w", pady=(14, 2))
        ctk.CTkLabel(inner,
                     text="Register on the server so your data appears in the admin panel",
                     font=ctk.CTkFont(size=12), text_color=C["muted"]).pack(anchor="w", pady=(0, 14))

        ctk.CTkLabel(inner, text="Full Name",
                     font=ctk.CTkFont(size=12, weight="bold"),
                     text_color=C["muted"]).pack(anchor="w")
        name_v = ctk.StringVar(value=self._profile.name)
        ctk.CTkEntry(inner, textvariable=name_v, placeholder_text="Your name",
                     width=490, height=38, corner_radius=8,
                     fg_color=C["card"], border_color=C["border"],
                     text_color=C["text"]).pack(anchor="w", pady=(4, 12))

        ctk.CTkLabel(inner, text="Email",
                     font=ctk.CTkFont(size=12, weight="bold"),
                     text_color=C["muted"]).pack(anchor="w")
        email_v = ctk.StringVar(value=self._profile.email)
        ctk.CTkEntry(inner, textvariable=email_v, placeholder_text="your@email.com",
                     width=490, height=38, corner_radius=8,
                     fg_color=C["card"], border_color=C["border"],
                     text_color=C["text"]).pack(anchor="w", pady=(4, 12))

        ctk.CTkLabel(inner, text="Password",
                     font=ctk.CTkFont(size=12, weight="bold"),
                     text_color=C["muted"]).pack(anchor="w")
        pass_v = ctk.StringVar(value="")
        ctk.CTkEntry(inner, textvariable=pass_v, placeholder_text="Choose a password (min 6 chars)",
                     show="*", width=490, height=38, corner_radius=8,
                     fg_color=C["card"], border_color=C["border"],
                     text_color=C["text"]).pack(anchor="w", pady=(4, 14))

        # ── Role cards ───────────────────────────────────────────────────────
        ctk.CTkLabel(inner, text="Select Your Role",
                     font=ctk.CTkFont(size=12, weight="bold"),
                     text_color=C["muted"]).pack(anchor="w")

        role_v     = ctk.StringVar(value=self._profile.role or "")
        role_frame = ctk.CTkFrame(inner, fg_color="transparent")
        role_frame.pack(fill="x", pady=(4, 14))
        role_frame.columnconfigure(0, weight=1)
        role_frame.columnconfigure(1, weight=1)
        role_cards = {}
        sched_v    = ctk.StringVar(value=self._profile.schedule_key or "")
        sched_menu = [None]
        sched_desc = [None]

        def update_schedules():
            r    = role_v.get()
            opts = list(UserProfile.SCHEDULES.get(r, {}).keys())
            if sched_menu[0]:
                sched_menu[0].configure(values=opts if opts else ["—"])
                if opts and sched_v.get() not in opts:
                    sched_v.set(opts[0])
                update_sched_desc()

        def update_sched_desc(*_):
            s = UserProfile.SCHEDULES.get(role_v.get(), {}).get(sched_v.get())
            if sched_desc[0]:
                sched_desc[0].configure(text=f"  \u2192 {s['label']}" if s else "")

        def select_role(r):
            role_v.set(r)
            for rk, (card, lbl) in role_cards.items():
                sel = rk == r
                card.configure(border_color=C["purple"] if sel else C["border"])
                lbl.configure(text_color=C["text"] if sel else C["muted"])
            update_schedules()

        for col, (rk, icon, title, desc) in enumerate([
            ("student",  "🎓", "Student",  "25-5 / 50-10 cycles\n+ Eye-care reminders"),
            ("employee", "💼", "Employee", "60-10 / 90-20 cycles\n+ Structured breaks"),
        ]):
            sel  = self._profile.role == rk
            card = ctk.CTkFrame(role_frame, fg_color=C["card"], corner_radius=12,
                                border_color=C["purple"] if sel else C["border"],
                                border_width=2)
            card.grid(row=0, column=col, padx=4, sticky="nsew", pady=2)
            ci    = ctk.CTkFrame(card, fg_color="transparent")
            ci.pack(fill="both", padx=14, pady=14)
            ico_l = ctk.CTkLabel(ci, text=icon, font=ctk.CTkFont(size=30)); ico_l.pack()
            ttl_l = ctk.CTkLabel(ci, text=title,
                                 font=ctk.CTkFont(size=15, weight="bold"),
                                 text_color=C["text"] if sel else C["muted"]); ttl_l.pack()
            ctk.CTkLabel(ci, text=desc, font=ctk.CTkFont(size=10),
                         text_color=C["dim"], justify="center", wraplength=180).pack(pady=(2, 0))
            role_cards[rk] = (card, ttl_l)
            for w in [card, ci, ico_l, ttl_l]:
                w.bind("<Button-1>", lambda e, _r=rk: select_role(_r))
                w.configure(cursor="hand2")

        # ── Schedule selector ────────────────────────────────────────────────
        ctk.CTkLabel(inner, text="Break Schedule",
                     font=ctk.CTkFont(size=12, weight="bold"),
                     text_color=C["muted"]).pack(anchor="w")

        init_opts = list(UserProfile.SCHEDULES.get(self._profile.role, {}).keys()) or ["Select a role first"]
        sm = ctk.CTkOptionMenu(inner, variable=sched_v, values=init_opts,
                               width=490, height=38, corner_radius=8,
                               fg_color=C["card"], button_color=C["purple"],
                               button_hover_color="#8855cc", text_color=C["text"],
                               dropdown_fg_color=C["card2"])
        sm.pack(anchor="w", pady=(4, 2))
        sched_menu[0] = sm

        sd = ctk.CTkLabel(inner, text="", font=ctk.CTkFont(size=11), text_color=C["accent"])
        sd.pack(anchor="w", pady=(0, 12))
        sched_desc[0] = sd
        sched_v.trace_add("write", update_sched_desc)
        update_sched_desc()

        # ── Eye-care toggle ──────────────────────────────────────────────────
        eye_v  = ctk.BooleanVar(value=self._profile.eye_care)
        eye_fr = ctk.CTkFrame(inner, fg_color=C["card2"], corner_radius=10,
                              border_color=C["border"], border_width=1)
        eye_fr.pack(fill="x", pady=(0, 14))
        eye_in = ctk.CTkFrame(eye_fr, fg_color="transparent")
        eye_in.pack(fill="x", padx=14, pady=10)
        ctk.CTkSwitch(eye_in, text="👁️  Enable 20-20-20 Eye Care Reminders",
                      variable=eye_v, font=ctk.CTkFont(size=12),
                      text_color=C["text"], progress_color=C["accent"],
                      button_color=C["accent"]).pack(anchor="w")
        ctk.CTkLabel(eye_in,
                     text="Nudge every 20 min to look 20 ft away for 20 seconds",
                     font=ctk.CTkFont(size=10), text_color=C["muted"]).pack(anchor="w", pady=(4, 0))

        status_lbl = ctk.CTkLabel(inner, text="",
                                  font=ctk.CTkFont(size=11), text_color=C["green"],
                                  wraplength=460)
        status_lbl.pack(anchor="w")

        # ── Register & Save ──────────────────────────────────────────────────
        def save_profile():
            nm = name_v.get().strip()
            em = email_v.get().strip()
            pw = pass_v.get().strip()
            if not nm:
                status_lbl.configure(text="⚠  Please enter your name.", text_color=C["red"]); return
            if not em:
                status_lbl.configure(text="⚠  Please enter your email.", text_color=C["red"]); return
            if not pw:
                status_lbl.configure(text="⚠  Please enter a password.", text_color=C["red"]); return
            if not role_v.get():
                status_lbl.configure(text="⚠  Please select a role.", text_color=C["red"]); return
            sk = sched_v.get()
            if not sk or sk == "Select a role first":
                status_lbl.configure(text="⚠  Please select a break schedule.", text_color=C["red"]); return

            status_lbl.configure(text="⟳  Registering with server…", text_color=C["accent"])
            dlg.update_idletasks()

            dept = "Student" if role_v.get() == "student" else "General"
            backend_ok = False

            try:
                payload = _ujson.dumps(
                    {"name": nm, "email": em, "password": pw, "department": dept}
                ).encode()
                req = _ureq.Request("http://localhost:8080/api/auth/register",
                                    data=payload,
                                    headers={"Content-Type": "application/json"},
                                    method="POST")
                with _ureq.urlopen(req, timeout=5) as resp:
                    _ujson.loads(resp.read())
                backend_ok = True
                status_lbl.configure(text="✔  Registered on server! Saving local profile…",
                                     text_color=C["green"])
                dlg.update_idletasks()

            except _uerr.HTTPError as e:
                try:
                    err_data = _ujson.loads(e.read())
                    err_msg  = err_data.get("error", "Registration failed")
                except Exception:
                    err_msg = f"Server error (code {e.code})"

                if "already" in err_msg.lower():
                    backend_ok = True   # user exists, treat as ok
                    status_lbl.configure(
                        text="ℹ  Email already registered. Saving local profile…",
                        text_color=C["amber"])
                    dlg.update_idletasks()
                else:
                    status_lbl.configure(text=f"✖  {err_msg}", text_color=C["red"]); return

            except Exception:
                status_lbl.configure(
                    text="⚠  Backend offline — saving local profile only.\n"
                         "Start the backend to sync with admin panel.",
                    text_color=C["amber"])
                dlg.update_idletasks()

            # Always save locally (even if backend offline)
            self._profile.save(name=nm, email=em, role=role_v.get(),
                               schedule_key=sk, eye_care=eye_v.get(),
                               password_hash=_hash_pw(pw))
            self._scheduler.stop(); time.sleep(0.05)
            self._scheduler.reset(); self._scheduler.start()
            self._update_bt_profile_labels()

            if backend_ok:
                status_lbl.configure(
                    text=f"✔  Account created & synced! Break timer started for {nm} 🎉",
                    text_color=C["green"])
            else:
                status_lbl.configure(
                    text=f"✔  Local account created. You can start backend/frontend/ML after login.",
                    text_color=C["green"])
            self._on_auth_success(name=nm, email=em, role=role_v.get(), token="", password=pw)
            dlg.after(2000, dlg.destroy)

        ctk.CTkButton(inner, text="✨  Create Account & Start Timer",
                      command=save_profile,
                      fg_color=C["purple"], hover_color="#8855cc",
                      font=ctk.CTkFont(size=14, weight="bold"),
                      height=46, corner_radius=10).pack(fill="x", pady=(4, 6))

        ctk.CTkLabel(inner,
                     text="Already have an account? Click '🔑 Sign In' above.",
                     font=ctk.CTkFont(size=11), text_color=C["muted"]).pack(pady=(4, 20))

        # ── Activate the correct panel ────────────────────────────────────────
        switch_mode(mode_v.get())
        # Second nudge: first auto-start may race UI init; also helps after logout if backend stopped.
        if auth_gate:
            self.after(500, self._auto_start_backend_if_needed)

    # ── Update Break Timer tab labels from profile ────────────────────────────
    def _update_bt_profile_labels(self):
        p = self._profile
        if self._session.get("is_authenticated") and p.is_registered:
            icon = {"student": "🎓", "employee": "💼"}.get(p.role, "👤")
            self._mon["bt_user_lbl"].configure(
                text=f"{icon}  {p.name}   ·   {p.role.capitalize()}")
            s = p.schedule
            self._mon["bt_sched_lbl"].configure(
                text=f"Schedule: {p.schedule_key}  —  {s['label'] if s else ''}")
        else:
            self._mon["bt_user_lbl"].configure(
                text="No active session. Please sign in.")
            self._mon["bt_sched_lbl"].configure(text="")

    # ── Timer button commands ─────────────────────────────────────────────────
    def _take_break_now(self):
        if not self._session.get("is_authenticated"):
            self._logout(); return
        self._scheduler.begin_break()

    def _skip_break(self):    self._scheduler.skip_break()
    def _reset_timer(self):   self._scheduler.reset()
    def _stop_timer(self):    self._scheduler.stop()

    def _start_timer(self):
        if not self._session.get("is_authenticated"):
            self._logout(); return
        self._scheduler.start()

    # ── Login dialog ──────────────────────────────────────────────────────────
    def _show_login_dlg(self):

        dlg = ctk.CTkToplevel(self)
        dlg.title("Configure Tracking Account")
        dlg.geometry("420x320")
        dlg.resizable(False, False)
        dlg.attributes("-topmost", True)
        dlg.configure(fg_color=C["bg"])
        dlg.update_idletasks()
        x = self.winfo_x() + self.winfo_width()//2 - 210
        y = self.winfo_y() + self.winfo_height()//2 - 160
        dlg.geometry(f"+{x}+{y}")

        ctk.CTkLabel(dlg, text="👤  Desktop Agent Login",
                     font=ctk.CTkFont("Segoe UI", 18, weight="bold"),
                     text_color=C["text"]).pack(pady=(20,6))
        ctk.CTkLabel(dlg, text="Enter the employee account credentials:",
                     font=ctk.CTkFont(size=12), text_color=C["muted"]).pack(pady=(0,16))

        cfg_path = AGENT_DIR / "config.json"
        email_v  = ctk.StringVar(value="")
        pass_v   = ctk.StringVar(value="")
        try:
            if cfg_path.exists():
                with open(cfg_path, "r") as f:
                    cfg = json.load(f)
                email_v.set(cfg.get("email",""))
                pass_v.set(cfg.get("password",""))
        except Exception: pass

        for var, ph, show in [(email_v,"Email",""), (pass_v,"Password","*")]:
            ctk.CTkEntry(dlg, textvariable=var, placeholder_text=ph,
                         show=show, width=300, height=36, corner_radius=8,
                         fg_color=C["card"], border_color=C["border"],
                         text_color=C["text"]).pack(pady=6)

        def save():
            try:
                cfg = {}
                if cfg_path.exists():
                    with open(cfg_path, "r") as f: cfg = json.load(f)
                cfg["email"] = email_v.get().strip()
                cfg["password"] = pass_v.get().strip()
                with open(cfg_path, "w") as f: json.dump(cfg, f, indent=2)
            except Exception as e:
                self._log_svc(f"✖ Config error: {e}")
            dlg.destroy()
            self._log_svc(f"✔ Tracking account updated → {email_v.get()}")
            ag = self.services["agent"]
            if ag.is_running():
                ag.stop()
                self.after(1500, lambda: threading.Thread(target=ag.start, daemon=True).start())

        ctk.CTkButton(dlg, text="Save & Apply", command=save,
                      fg_color=C["purple"], hover_color="#8855cc",
                      font=ctk.CTkFont(weight="bold"),
                      width=300, height=40, corner_radius=8).pack(pady=(16,0))

    # ── Log helpers ───────────────────────────────────────────────────────────
    def _poll_logs(self):
        try:
            while True:
                self._log_svc(self.log_q.get_nowait())
        except queue.Empty: pass
        self.after(150, self._poll_logs)

    def _log_svc(self, msg):
        self.log_box.configure(state="normal")
        self.log_box.insert("end", msg + "\n")
        self.log_box.see("end")
        self.log_box.configure(state="disabled")

    def _clear_log(self):
        self.log_box.configure(state="normal")
        self.log_box.delete("1.0","end")
        self.log_box.configure(state="disabled")

    # ── Service-state polling ─────────────────────────────────────────────────
    def _poll_states(self):
        running = 0
        for svc in SERVICES:
            sp = self.services[svc["id"]]
            # Self-heal backend state: if process errored but server is reachable, mark running.
            if svc["id"] == "backend" and sp.state == "error" and self._is_url_reachable(svc.get("url")):
                sp.state = "running"
            st = sp.state
            if st == "running":
                col, txt, dc = C["green"], "Running",   C["green"]; running += 1
            elif st == "starting":
                col, txt, dc = C["amber"], "Starting…", C["amber"]
            elif st == "error":
                col, txt, dc = C["red"],   "Error",     C["red"]
            else:
                col, txt, dc = C["muted"], "Stopped",   C["muted"]

            self.sta_lbl[svc["id"]].configure(text=txt, text_color=col)
            self.dot_lbl[svc["id"]].configure(text_color=dc)
            self.card_frm[svc["id"]].configure(
                border_color=dc if st != "stopped" else C["border"])

            btn = svc.get("_btn")
            if btn:
                if sp.is_running():
                    btn.configure(text="Stop", fg_color="#2a3550", hover_color="#3b4a6b")
                else:
                    btn.configure(text="Start", fg_color=C["purple"], hover_color="#8855cc")

        msg = f"✔  All {len(SERVICES)} services running — click Open App" if running==len(SERVICES) \
            else (f"⟳  {running}/{len(SERVICES)} services running…" if running else
                  "Ready — click ▶ Start All to launch all services")
        col = C["green"] if running==len(SERVICES) else (C["amber"] if running else C["muted"])
        self.status_bar.configure(text=msg, text_color=col)

        self.after(500, self._poll_states)

    def _is_url_reachable(self, url: str) -> bool:
        if not url:
            return False
        try:
            with _ureq.urlopen(url, timeout=2) as resp:
                code = int(getattr(resp, "status", 200))
                return code < 500
        except _uerr.HTTPError as e:
            return int(getattr(e, "code", 500)) < 500
        except Exception:
            return False

    def _autosave(self):
        self._history.save()
        self.after(30_000, self._autosave)   # save every 30s

    # ── Close ─────────────────────────────────────────────────────────────────
    def on_closing(self):
        self._scheduler.stop()
        self.tracker.stop()
        self._stop_all()
        time.sleep(0.8)
        self.destroy()


# ── Entry point ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    psutil.cpu_percent(interval=None)   # prime counter
    app = BurnoutLauncher()
    app.protocol("WM_DELETE_WINDOW", app.on_closing)
    app.mainloop()