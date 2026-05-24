"""
tracker.py  –  BurnoutGuard Desktop Background Agent
=====================================================
Tracks keyboard keypresses, mouse moves, clicks, and scrolls using pynput.

Key design points:
- All counter access is protected by threading.Lock (thread-safe)
- Mouse moves are throttled to 1 count/second (avoids noise)
- Idle detection: no *meaningful* activity for >= idle_threshold_seconds.
  Mouse *movement* does NOT reset the idle clock (only keys, clicks, wheel do),
  otherwise pointer micro-drift keeps the user "active" forever and idle stays 0.
- On Windows, idle vs active uses GetLastInputInfo (session-wide last input) so
  time in elevated IDEs (VS Code / terminals run as admin) still counts correctly;
  low-level hooks often miss input to higher-integrity processes.
- A 1 Hz accumulator thread splits each second into active vs idle so snapshots
  match real usage within long send intervals (e.g. 30s).
"""

import sys
import time
import threading
from pynput import keyboard
import mouse


def _win_seconds_since_last_input():
    """Return seconds since last keyboard/mouse input for this session, or None if unavailable."""
    if sys.platform != "win32":
        return None
    try:
        import ctypes

        class LASTINPUTINFO(ctypes.Structure):
            _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]

        li = LASTINPUTINFO()
        li.cbSize = ctypes.sizeof(LASTINPUTINFO)
        if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(li)):
            return None
        tick = ctypes.windll.kernel32.GetTickCount() & 0xFFFFFFFF
        last = li.dwTime & 0xFFFFFFFF
        return ((tick - last) & 0xFFFFFFFF) / 1000.0
    except Exception:
        return None


class ActivityTracker:
    """
    Runs pynput listeners in background daemon threads.
    Call start() to begin, stop() to clean up.
    Call get_and_reset() every interval to retrieve and reset interval counters.
    """

    def __init__(self, idle_threshold_seconds: int = 120):
        self._lock = threading.Lock()
        self._idle_threshold = idle_threshold_seconds

        # --- Interval counters (reset on every get_and_reset call) ---
        self._key_count: int = 0
        self._mouse_count: int = 0

        # --- Per-second active/idle (accumulated between get_and_reset) ---
        self._active_accum: int = 0
        self._idle_accum: int = 0

        # --- Timing ---
        self._last_activity_for_idle: float = time.monotonic()  # keys / click / wheel only
        self._last_mouse_throttle: float = 0.0
        self._session_start: float = time.time()       # wall-clock for API payload
        self._interval_start: float = time.monotonic() # legacy; unused for idle split

        # --- Listener handles ---
        self._kb_listener = None
        self._mo_listener = None
        self._running = False
        self._accum_thread: threading.Thread | None = None

    # ── Public API ──────────────────────────────────────────────────────────────

    def start(self):
        """Start keyboard and mouse listeners (run in daemon threads)."""
        if self._running:
            return
        self._running = True
        self._kb_listener = keyboard.Listener(on_press=self._on_key_press)
        self._kb_listener.start()

        # Using "mouse" library hook instead of pynput due to Python 3.13 bugs
        mouse.hook(self._on_mouse_event)

        self._accum_thread = threading.Thread(
            target=self._accum_loop, daemon=True, name="activity-accum"
        )
        self._accum_thread.start()

    def stop(self):
        """Stop listeners cleanly."""
        self._running = False
        if self._kb_listener:
            try:
                self._kb_listener.stop()
            except Exception:
                pass
        try:
            mouse.unhook_all()
        except Exception:
            pass

    def get_and_reset(self) -> dict:
        """
        Returns a snapshot of activity that occurred since the LAST call
        to this method, then resets interval counters.

        Returns:
            {
                "keyboardActivityCount": int,
                "mouseActivityCount":    int,
                "totalActiveTime":       int,   # seconds active in interval
                "totalIdleTime":         int,   # seconds idle in interval
                "screenTime":            int,
                "isIdle":                bool,
            }
        """
        with self._lock:
            idle_now = self._is_idle_unlocked()
            snapshot = {
                "keyboardActivityCount": self._key_count,
                "mouseActivityCount":    self._mouse_count,
                "totalActiveTime":       self._active_accum,
                "totalIdleTime":         self._idle_accum,
                "screenTime":            self._active_accum + self._idle_accum,
                "isIdle":                idle_now,
            }
            self._key_count = 0
            self._mouse_count = 0
            self._active_accum = 0
            self._idle_accum = 0
            self._interval_start = time.monotonic()

        return snapshot

    def is_idle(self) -> bool:
        """Thread-safe idle check."""
        with self._lock:
            return self._is_idle_unlocked()

    def session_start_time(self) -> float:
        """Wall-clock timestamp when the agent session started (for API payload)."""
        return self._session_start

    # ── Private helpers ──────────────────────────────────────────────────────────

    def _is_idle_unlocked(self) -> bool:
        """Must be called with self._lock held."""
        os_idle = _win_seconds_since_last_input()
        if os_idle is not None:
            return os_idle >= self._idle_threshold
        return (time.monotonic() - self._last_activity_for_idle) >= self._idle_threshold

    def _mark_meaningful_activity(self):
        """Reset idle clock — call only for keys / clicks / wheel (not mouse move)."""
        self._last_activity_for_idle = time.monotonic()

    def _accum_loop(self):
        """1 Hz: classify each second as active or idle for accurate totals."""
        while self._running:
            time.sleep(1.0)
            try:
                with self._lock:
                    if self._is_idle_unlocked():
                        self._idle_accum += 1
                    else:
                        self._active_accum += 1
            except Exception:
                pass

    # ── Listener callbacks ────────────────────────────────────────────────────────

    def _on_key_press(self, key):
        with self._lock:
            self._key_count += 1
            self._mark_meaningful_activity()

    def _on_mouse_event(self, event):
        now = time.monotonic()
        with self._lock:
            if isinstance(event, mouse.MoveEvent):
                # Throttle mouse moves to 1 count per second to avoid noise
                if now - self._last_mouse_throttle >= 1.0:
                    self._mouse_count += 1
                    self._last_mouse_throttle = now
                    # Do NOT update idle clock on pointer movement — prevents idle=0 forever
            elif isinstance(event, mouse.WheelEvent):
                self._mouse_count += 1
                self._mark_meaningful_activity()
            elif isinstance(event, mouse.ButtonEvent):
                if event.event_type == "down":
                    self._mouse_count += 1
                    self._mark_meaningful_activity()
