import React, { useState, useEffect, useRef, createContext, useContext } from "react";

// ─── Auth Context ────────────────────────────────────────────────────────────
const AuthContext = createContext(null);
const useAuth = () => useContext(AuthContext);

// ─── API Helper ──────────────────────────────────────────────────────────────
const API = "http://localhost:8080/api";
const apiFetch = async (path, opts = {}) => {
  const token = localStorage.getItem("token");
  const res = await fetch(`${API}${path}`, {
    headers: { "Content-Type": "application/json", ...(token ? { Authorization: `Bearer ${token}` } : {}), ...opts.headers },
    ...opts,
  });
  return res.json();
};

// ─── ACTIVITY TRACKER HOOK ────────────────────────────────────────────────────
// Tracks keyboard, mouse, idle state, and screen time.
// - Browser events (keydown/mousemove) are counted locally.
// - Every 30 s we also fetch the server summary which includes data sent by
//   the desktop agent (pynput system-wide tracker). The two are merged so
//   switching to another app does NOT reset the counters.
const IDLE_THRESHOLD_MS  = 2 * 60 * 1000; // 2 minutes of no activity = idle
const SEND_INTERVAL_MS   = 60 * 1000;     // POST browser snapshot every 60 s
const SERVER_POLL_MS     = 30 * 1000;     // merge server totals every 30 s

const useActivityTracker = (enabled = true) => {
  const sessionStart      = useRef(new Date());
  const lastActivity      = useRef(Date.now());
  const isIdle            = useRef(false);
  const activeAccum       = useRef(0);   // browser-side seconds active
  const idleAccum         = useRef(0);   // browser-side seconds idle
  const screenTimeAccum   = useRef(0);   // seconds tab was visible
  const keyboardCount     = useRef(0);   // browser-side keypresses
  const mouseCount        = useRef(0);   // browser-side mouse events
  const tabVisible        = useRef(!document.hidden);
  const tickRef           = useRef(null);
  const sendRef           = useRef(null);
  const pollRef           = useRef(null);
  // Server-side totals (from desktop agent via backend summary)
  const serverActive      = useRef(0);
  const serverIdle        = useRef(0);
  const serverKeys        = useRef(0);
  const serverMouse       = useRef(0);
  const serverScreen      = useRef(0);
  const hasServerData     = useRef(false);

  const [stats, setStats] = useState({
    totalActiveTime: 0, totalIdleTime: 0,
    keyboardActivityCount: 0, mouseActivityCount: 0,
    screenTime: 0, isIdle: false, hasDesktopAgent: false,
  });

  useEffect(() => {
    if (!enabled) return;

    // ── Visibility API – track screen time ──────────────────────────────────
    const onVisibility = () => { tabVisible.current = !document.hidden; };
    document.addEventListener("visibilitychange", onVisibility);

    // ── Activity event handlers ──────────────────────────────────────────────
    const markActive = () => {
      lastActivity.current = Date.now();
      if (isIdle.current) isIdle.current = false;
    };
    const onKeyDown = () => { keyboardCount.current++; markActive(); };

    let mouseThrottle = 0;
    const onMouseMove = () => {
      const now = Date.now();
      if (now - mouseThrottle > 500) {
        mouseThrottle = now;
        mouseCount.current++;
        markActive();
      }
    };
    const onMouseClickOrScroll = () => {
      mouseCount.current++;
      markActive();
    };
    
    window.addEventListener("keydown",   onKeyDown);
    window.addEventListener("mousemove", onMouseMove);
    window.addEventListener("mousedown", onMouseClickOrScroll);
    window.addEventListener("scroll",    onMouseClickOrScroll);

    // ── Poll server every 30 s to get desktop-agent totals ───────────────────
    const fetchServerTotals = () => {
      apiFetch("/activity/summary?hours=24")
        .then(data => {
          if (data && !data.error && data.totalActiveTimeSec != null) {
            serverActive.current = Number(data.totalActiveTimeSec)  || 0;
            serverIdle.current   = Number(data.totalIdleTimeSec)    || 0;
            serverKeys.current   = Number(data.keyboardActivityCount)|| 0;
            serverMouse.current  = Number(data.mouseActivityCount)   || 0;
            serverScreen.current = Number(data.screenTimeSec)        || 0;
            hasServerData.current = (
              serverActive.current + serverIdle.current +
              serverKeys.current   + serverMouse.current > 0
            );
          }
        })
        .catch(() => {});
    };
    fetchServerTotals(); // immediate first fetch
    pollRef.current = setInterval(fetchServerTotals, SERVER_POLL_MS);

    // ── 1-second tick: classify active vs idle, accumulate screen time ───────
    tickRef.current = setInterval(() => {
      const now = Date.now();
      const idle = (now - lastActivity.current) > IDLE_THRESHOLD_MS;
      isIdle.current = idle;
      if (idle) idleAccum.current++;
      else       activeAccum.current++;
      if (tabVisible.current) screenTimeAccum.current++;

      // Merge: use whichever is larger (server or browser) for each metric
      // so the display reflects all-app activity, not just browser
      const mergedActive = Math.max(activeAccum.current, serverActive.current);
      const mergedIdle   = Math.max(idleAccum.current,   serverIdle.current);
      const mergedKeys   = Math.max(keyboardCount.current, serverKeys.current);
      const mergedMouse  = Math.max(mouseCount.current,    serverMouse.current);
      const mergedScreen = Math.max(screenTimeAccum.current, serverScreen.current);

      setStats({
        totalActiveTime:       mergedActive,
        totalIdleTime:         mergedIdle,
        keyboardActivityCount: mergedKeys,
        mouseActivityCount:    mergedMouse,
        screenTime:            mergedScreen,
        isIdle:                idle,
        hasDesktopAgent:       hasServerData.current,
      });
    }, 1000);

    // ── Send browser snapshot to backend every 60 seconds ───────────────────
    sendRef.current = setInterval(() => {
      if (!hasServerData.current) {
        // Only push browser activity logs if desktop agent is NOT active, to prevent double counting
        const payload = {
          totalActiveTime:       activeAccum.current,
          totalIdleTime:         idleAccum.current,
          keyboardActivityCount: keyboardCount.current,
          mouseActivityCount:    mouseCount.current,
          screenTime:            screenTimeAccum.current,
          sessionStart:          sessionStart.current.toISOString(),
          sessionEnd:            new Date().toISOString(),
        };
        apiFetch("/activity/log", { method: "POST", body: JSON.stringify(payload) })
          .catch(() => {});
      }
      // Always reset browser-side accumulators
      activeAccum.current     = 0;
      idleAccum.current       = 0;
      keyboardCount.current   = 0;
      mouseCount.current      = 0;
      screenTimeAccum.current = 0;
      sessionStart.current    = new Date();
    }, SEND_INTERVAL_MS);

    return () => {
      clearInterval(tickRef.current);
      clearInterval(sendRef.current);
      clearInterval(pollRef.current);
      document.removeEventListener("visibilitychange", onVisibility);
      window.removeEventListener("keydown",   onKeyDown);
      window.removeEventListener("mousemove", onMouseMove);
      window.removeEventListener("mousedown", onMouseClickOrScroll);
      window.removeEventListener("scroll",    onMouseClickOrScroll);
    };
  }, [enabled]);

  return stats;
};

// ─── FORMAT SECONDS → "Xh Ym" ─────────────────────────────────────────────────
const fmtSec = (s) => {
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = s % 60;
  if (h > 0) return `${h}h ${m}m`;
  if (m > 0) return `${m}m ${sec}s`;
  return `${sec}s`;
};

// ─── ICONS ────────────────────────────────────────────────────────────────────
const Icon = ({ d, size = 20, color = "currentColor" }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d={d} />
  </svg>
);
const icons = {
  brain: "M9.5 2C8.1 2 7 3.1 7 4.5v1C5.1 6 4 7.5 4 9.3c0 1.6.9 3 2.2 3.7-.1.3-.2.7-.2 1 0 2.2 1.8 4 4 4s4-1.8 4-4c0-.3-.1-.7-.2-1C15.1 12.3 16 10.9 16 9.3 16 7.5 14.9 6 13 5.5v-1C13 3.1 11.9 2 10.5 2h-1z",
  dashboard: "M3 13h8V3H3v10zm0 8h8v-6H3v6zm10 0h8V11h-8v10zm0-18v6h8V3h-8z",
  alert: "M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0zM12 9v4M12 17h.01",
  check: "M20 6L9 17l-5-5",
  user: "M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2M12 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8z",
  logout: "M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4M16 17l5-5-5-5M21 12H9",
  chart: "M18 20V10M12 20V4M6 20v-6",
  clock: "M12 2a10 10 0 1 0 0 20 10 10 0 0 0 0-20zM12 6v6l4 2",
  heart: "M20.84 4.61a5.5 5.5 0 0 0-7.78 0L12 5.67l-1.06-1.06a5.5 5.5 0 0 0-7.78 7.78l1.06 1.06L12 21.23l7.78-7.78 1.06-1.06a5.5 5.5 0 0 0 0-7.78z",
  shield: "M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z",
  send: "M22 2L11 13M22 2L15 22l-4-9-9-4 20-7z",
  team: "M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2M9 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8zM23 21v-2a4 4 0 0 0-3-3.87M16 3.13a4 4 0 0 1 0 7.75",
  settings: "M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z",
};

// ─── RISK BADGE ───────────────────────────────────────────────────────────────
const RiskBadge = ({ level }) => {
  const styles = {
    LOW: { bg: "#052e16", text: "#4ade80", border: "#166534" },
    MEDIUM: { bg: "#431407", text: "#fb923c", border: "#9a3412" },
    HIGH: { bg: "#3f0000", text: "#f87171", border: "#991b1b" },
    NOT_ASSESSED: { bg: "#1e1b4b", text: "#818cf8", border: "#3730a3" },
  };
  const s = styles[level] || styles.NOT_ASSESSED;
  return (
    <span style={{ background: s.bg, color: s.text, border: `1px solid ${s.border}`, padding: "3px 12px", borderRadius: 20, fontSize: 12, fontWeight: 700, letterSpacing: 1 }}>
      {level}
    </span>
  );
};

// ─── CIRCULAR GAUGE ──────────────────────────────────────────────────────────
const CircularGauge = ({ score, level }) => {
  const colors = { LOW: "#4ade80", MEDIUM: "#fb923c", HIGH: "#f87171", NOT_ASSESSED: "#818cf8" };
  const color = colors[level] || "#818cf8";
  const r = 52, cx = 60, cy = 60;
  const circ = 2 * Math.PI * r;
  const offset = circ - (score / 100) * circ;
  return (
    <svg width="120" height="120" style={{ filter: `drop-shadow(0 0 12px ${color}55)` }}>
      <circle cx={cx} cy={cy} r={r} fill="none" stroke="#1f2937" strokeWidth="10" />
      <circle cx={cx} cy={cy} r={r} fill="none" stroke={color} strokeWidth="10"
        strokeDasharray={circ} strokeDashoffset={offset}
        strokeLinecap="round" transform={`rotate(-90 ${cx} ${cy})`}
        style={{ transition: "stroke-dashoffset 1.2s ease" }} />
      <text x={cx} y={cy - 8} textAnchor="middle" fill={color} fontSize="22" fontWeight="800">{score}%</text>
      <text x={cx} y={cy + 12} textAnchor="middle" fill="#6b7280" fontSize="10" fontWeight="600">{level}</text>
    </svg>
  );
};

const UsageDonutChart = ({ activeSeconds = 0, idleSeconds = 0, title = "Usage Hours" }) => {
  const total = Math.max(1, activeSeconds + idleSeconds);
  const activePct = Math.round((activeSeconds / total) * 100);
  const idlePct = 100 - activePct;
  const hours = (activeSeconds / 3600).toFixed(1);
  const r = 68;
  const cx = 90;
  const cy = 90;
  const circ = 2 * Math.PI * r;
  const activeArc = (activePct / 100) * circ;
  const idleArc = circ - activeArc;

  return (
    <div style={{ ...styles.card, minHeight: 250, animation: "fadeUp 450ms ease-out" }}>
      <h3 style={{ ...styles.cardTitle, marginBottom: 14 }}>⏱️ {title}</h3>
      <div style={{ display: "flex", alignItems: "center", gap: 20, flexWrap: "wrap" }}>
        <svg width="180" height="180" style={{ filter: "drop-shadow(0 10px 24px rgba(6,182,212,0.25))" }}>
          <circle cx={cx} cy={cy} r={r} fill="none" stroke="#1f2937" strokeWidth="18" />
          <circle
            cx={cx}
            cy={cy}
            r={r}
            fill="none"
            stroke="#06b6d4"
            strokeWidth="18"
            strokeLinecap="round"
            strokeDasharray={`${activeArc} ${idleArc}`}
            transform={`rotate(-90 ${cx} ${cy})`}
            style={{ transition: "stroke-dasharray 0.8s ease" }}
          />
          <text x={cx} y={cy - 5} textAnchor="middle" fill="#ecfeff" fontSize="26" fontWeight="800">{hours}h</text>
          <text x={cx} y={cy + 16} textAnchor="middle" fill="#67e8f9" fontSize="12">Active usage</text>
        </svg>
        <div style={{ display: "grid", gap: 10 }}>
          <div style={styles.legendItem}>
            <span style={{ ...styles.legendDot, background: "#06b6d4" }} />
            <span style={{ color: "#cffafe", fontWeight: 700 }}>Active: {activePct}% ({fmtSec(activeSeconds)})</span>
          </div>
          <div style={styles.legendItem}>
            <span style={{ ...styles.legendDot, background: "#f59e0b" }} />
            <span style={{ color: "#fde68a", fontWeight: 700 }}>Idle: {idlePct}% ({fmtSec(idleSeconds)})</span>
          </div>
          <p style={{ color: "#64748b", fontSize: 12, margin: "4px 0 0" }}>
            Auto-updated from live tracker data. No manual save needed.
          </p>
        </div>
      </div>
    </div>
  );
};

const ActiveUserPill = ({ user, context = "Dashboard" }) => (
  <div style={{ ...styles.activeUserPill, animation: "fadeUp 420ms ease-out" }}>
    <div style={styles.avatar}>{user?.name?.[0]?.toUpperCase() || "U"}</div>
    <div>
      <div style={{ color: "#67e8f9", fontSize: 11, letterSpacing: 0.7, textTransform: "uppercase", fontWeight: 700 }}>
        Active User
      </div>
      <div style={{ color: "#ecfeff", fontWeight: 700, fontSize: 14 }}>
        {user?.name || "Unknown"} <span style={{ color: "#94a3b8", fontWeight: 500 }}>({context})</span>
      </div>
      <div style={{ color: "#94a3b8", fontSize: 12 }}>{user?.email || "-"}</div>
    </div>
  </div>
);

// ─── AUTH PAGES ───────────────────────────────────────────────────────────────
const LoginPage = ({ onSwitch }) => {
  const { login } = useAuth();
  const [form, setForm] = useState({ email: "", password: "" });
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState("");

  const handleSubmit = async () => {
    setLoading(true); setErr("");
    try {
      const data = await apiFetch("/auth/login", { method: "POST", body: JSON.stringify(form) });
      if (data.token) login(data);
      else setErr(data.error || "Login failed");
    } catch { setErr("Connection error. Is the backend running?"); }
    setLoading(false);
  };

  return (
    <div style={styles.authWrap}>
      <div style={styles.authCard}>
        <div style={{ textAlign: "center", marginBottom: 32 }}>
          <div style={styles.logo}>🧠</div>
          <h1 style={styles.authTitle}>BurnoutGuard</h1>
          <p style={styles.authSub}>AI-Powered Burnout Detection System</p>
        </div>
        {err && <div style={styles.errBox}>{err}</div>}
        <input style={styles.input} placeholder="Email" value={form.email} onChange={e => setForm({ ...form, email: e.target.value })} type="email" />
        <input style={styles.input} placeholder="Password" value={form.password} onChange={e => setForm({ ...form, password: e.target.value })} type="password" onKeyDown={e => e.key === "Enter" && handleSubmit()} />
        <button style={{ ...styles.btn, opacity: loading ? 0.7 : 1 }} onClick={handleSubmit} disabled={loading}>
          {loading ? "Signing in..." : "Sign In"}
        </button>
        <p style={{ textAlign: "center", color: "#6b7280", marginTop: 16, fontSize: 14 }}>
          No account? <span style={{ color: "#6366f1", cursor: "pointer" }} onClick={onSwitch}>Register</span>
        </p>
        <div style={styles.demoBox}>
          <strong style={{ color: "#a78bfa" }}>Demo:</strong> admin@burnout.com / admin123
        </div>
      </div>
    </div>
  );
};

const RegisterPage = ({ onSwitch }) => {
  const { login } = useAuth();
  const [form, setForm] = useState({ name: "", email: "", password: "", department: "" });
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState("");

  const handleSubmit = async () => {
    setLoading(true); setErr("");
    try {
      const data = await apiFetch("/auth/register", { method: "POST", body: JSON.stringify(form) });
      if (data.token) login(data);
      else setErr(data.error || "Registration failed");
    } catch { setErr("Connection error. Is the backend running?"); }
    setLoading(false);
  };

  return (
    <div style={styles.authWrap}>
      <div style={styles.authCard}>
        <div style={{ textAlign: "center", marginBottom: 32 }}>
          <div style={styles.logo}>🧠</div>
          <h1 style={styles.authTitle}>Create Account</h1>
          <p style={styles.authSub}>Join BurnoutGuard today</p>
        </div>
        {err && <div style={styles.errBox}>{err}</div>}
        {["name", "email", "password", "department"].map(f => (
          <input key={f} style={styles.input} placeholder={f.charAt(0).toUpperCase() + f.slice(1)}
            value={form[f]} onChange={e => setForm({ ...form, [f]: e.target.value })}
            type={f === "password" ? "password" : "text"} />
        ))}
        <button style={{ ...styles.btn, opacity: loading ? 0.7 : 1 }} onClick={handleSubmit} disabled={loading}>
          {loading ? "Registering..." : "Create Account"}
        </button>
        <p style={{ textAlign: "center", color: "#6b7280", marginTop: 16, fontSize: 14 }}>
          Have account? <span style={{ color: "#6366f1", cursor: "pointer" }} onClick={onSwitch}>Sign in</span>
        </p>
      </div>
    </div>
  );
};

// ─── WELLNESS CENTER ──────────────────────────────────────────────────────────
const WellnessModal = ({ title, onClose, children }) => (
  <div style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,0.8)", zIndex: 1000, display: "flex", alignItems: "center", justifyContent: "center" }}
    onClick={onClose}>
    <div style={{ background: "#111827", border: "1px solid #374151", borderRadius: 16, padding: 32, maxWidth: 520, width: "90%", maxHeight: "80vh", overflowY: "auto", position: "relative" }}
      onClick={e => e.stopPropagation()}>
      <button onClick={onClose} style={{ position: "absolute", top: 16, right: 16, background: "none", border: "none", color: "#6b7280", fontSize: 22, cursor: "pointer" }}>✕</button>
      <h3 style={{ color: "#f3f4f6", marginTop: 0, marginBottom: 20 }}>{title}</h3>
      {children}
    </div>
  </div>
);

const BreathingTimer = ({ onClose }) => {
  const phases = [
    { label: "Inhale", duration: 4, color: "#6366f1" },
    { label: "Hold", duration: 7, color: "#f59e0b" },
    { label: "Exhale", duration: 8, color: "#22c55e" },
  ];
  const [running, setRunning] = React.useState(false);
  const [phaseIdx, setPhaseIdx] = React.useState(0);
  const [count, setCount] = React.useState(4);
  const [cycles, setCycles] = React.useState(0);
  const timerRef = React.useRef(null);

  const stop = () => {
    clearInterval(timerRef.current);
    setRunning(false); setPhaseIdx(0); setCount(4);
  };

  React.useEffect(() => {
    if (!running) return;
    timerRef.current = setInterval(() => {
      setCount(c => {
        if (c <= 1) {
          setPhaseIdx(p => {
            const next = (p + 1) % phases.length;
            if (next === 0) setCycles(cy => cy + 1);
            setCount(phases[next].duration);
            return next;
          });
          return phases[(phaseIdx + 1) % phases.length].duration;
        }
        return c - 1;
      });
    }, 1000);
    return () => clearInterval(timerRef.current);
  }, [running, phaseIdx]);

  const phase = phases[phaseIdx];
  const r = 60, circ = 2 * Math.PI * r;
  const pct = 1 - count / phase.duration;

  return (
    <WellnessModal title="🧘 Mindfulness Breathing (4-7-8 Technique)" onClose={onClose}>
      <p style={{ color: "#9ca3af", fontSize: 13, marginBottom: 24 }}>
        Inhale 4s → Hold 7s → Exhale 8s. Repeat 3–5 cycles to calm your nervous system.
      </p>
      <div style={{ textAlign: "center", marginBottom: 24 }}>
        <svg width="160" height="160" style={{ filter: `drop-shadow(0 0 20px ${phase.color}66)` }}>
          <circle cx="80" cy="80" r={r} fill="none" stroke="#1f2937" strokeWidth="10" />
          <circle cx="80" cy="80" r={r} fill="none" stroke={phase.color} strokeWidth="10"
            strokeDasharray={circ} strokeDashoffset={circ * (1 - pct)}
            strokeLinecap="round" transform="rotate(-90 80 80)"
            style={{ transition: "stroke-dashoffset 0.9s linear" }} />
          <text x="80" y="74" textAnchor="middle" fill={phase.color} fontSize="30" fontWeight="800">{count}</text>
          <text x="80" y="96" textAnchor="middle" fill="#9ca3af" fontSize="13">{phase.label}</text>
        </svg>
        <p style={{ color: "#6b7280", fontSize: 12, marginTop: 8 }}>
          Cycles completed: <strong style={{ color: "#a78bfa" }}>{cycles}</strong>
        </p>
      </div>
      <div style={{ display: "flex", gap: 12, justifyContent: "center" }}>
        {!running
          ? <button style={{ background: "linear-gradient(135deg,#6366f1,#8b5cf6)", color: "#fff", border: "none", borderRadius: 8, padding: "10px 28px", fontWeight: 700, cursor: "pointer", fontSize: 15 }}
            onClick={() => setRunning(true)}>▶ Start</button>
          : <button style={{ background: "#ef4444", color: "#fff", border: "none", borderRadius: 8, padding: "10px 28px", fontWeight: 700, cursor: "pointer", fontSize: 15 }}
            onClick={stop}>■ Stop</button>
        }
      </div>
    </WellnessModal>
  );
};

const TipList = ({ items, color }) => (
  <div>
    {items.map((s, i) => (
      <div key={i} style={{ borderBottom: "1px solid #1f2937", paddingBottom: 12, marginBottom: 12 }}>
        <strong style={{ color, display: "block", marginBottom: 4 }}>{s.heading}</strong>
        <p style={{ color: "#d1d5db", fontSize: 13, margin: 0 }}>{s.detail}</p>
      </div>
    ))}
  </div>
);

const WellnessCenter = () => {
  const [modal, setModal] = React.useState(null);
  const [breathingOpen, setBreathingOpen] = React.useState(false);

  const MODALS = {
    stretches: {
      title: "💪 Desk Stretches (5 minutes)",
      el: <TipList color="#8b5cf6" items={[
        { heading: "1. Neck Roll — 1 min", detail: "Slowly roll your head in full circles, 5 times each direction." },
        { heading: "2. Shoulder Shrugs — 1 min", detail: "Raise both shoulders to ears, hold 3 sec, release. Repeat 10 times." },
        { heading: "3. Chest Opener — 1 min", detail: "Clasp hands behind back, straighten arms, squeeze shoulders. Hold 15 sec × 3." },
        { heading: "4. Seated Spinal Twist — 1 min", detail: "Sit tall, twist right placing hand on chair back. Hold 20 sec each side." },
        { heading: "5. Wrist Stretch — 30 sec", detail: "Extend arm, pull fingers back gently. Hold 15 sec each hand." },
        { heading: "6. Standing Lunge — 30 sec", detail: "Step forward into a lunge, hold 20 sec each leg." },
      ]} />
    },
    sleep: {
      title: "😴 Sleep Hygiene Guide",
      el: <TipList color="#a78bfa" items={[
        { heading: "✓ Consistent Schedule", detail: "Sleep and wake at the same time every day — even weekends — to set your body clock." },
        { heading: "✓ Screen-Free 1 Hour Before Bed", detail: "Blue light suppresses melatonin. Switch to reading or stretching after 10 PM." },
        { heading: "✓ Cool Dark Room (18–20°C)", detail: "A cooler, darker room signals sleep time. Use blackout curtains." },
        { heading: "✓ No Caffeine After 2 PM", detail: "Caffeine has a 6-hour half-life — a 4 PM coffee still affects you at 10 PM." },
        { heading: "✓ Wind-Down Ritual", detail: "10 min of journaling, yoga, or breathing before bed signals your brain to relax." },
        { heading: "✓ Limit Alcohol", detail: "Even 2 drinks reduce REM sleep quality by ~25%." },
      ]} />
    },
    nutrition: {
      title: "🥗 Brain-Boosting Nutrition",
      el: <TipList color="#4ade80" items={[
        { heading: "🐟 Fatty Fish (Salmon)", detail: "Omega-3 DHA — essential for brain cell structure and reducing mental fatigue." },
        { heading: "🫐 Blueberries", detail: "Antioxidants that improve memory and delay brain aging. A handful daily." },
        { heading: "🥑 Avocado", detail: "Healthy fats improve brain blood flow and boost sustained focus." },
        { heading: "🥜 Walnuts & Almonds", detail: "Vitamin E protects against cognitive decline and improves mood." },
        { heading: "🍫 Dark Chocolate (70%+)", detail: "Flavonoids improve mood and brain blood flow. Limit to 1–2 squares daily." },
        { heading: "🥦 Broccoli & Greens", detail: "Vitamin K and antioxidants strengthen neural connections in the brain." },
        { heading: "💧 Water (2L+/day)", detail: "Even mild dehydration reduces concentration by 20%. Keep a bottle on your desk." },
      ]} />
    },
    detox: {
      title: "📵 Digital Detox Strategies",
      el: <TipList color="#fb923c" items={[
        { heading: "📌 Phone-Free Morning 30 Min", detail: "No phone for 30 min after waking. Stretch or journal instead." },
        { heading: "📌 Notification Audit", detail: "Turn off all non-essential alerts. Only allow calls and calendar notifications." },
        { heading: "📌 Hard Work Stop Time", detail: "Set a cutoff (e.g. 7 PM). Put work phone away and use an email auto-reply." },
        { heading: "📌 Social Media Time Box", detail: "Limit to 2 sessions × 15 min per day using a phone timer." },
        { heading: "📌 One-Screen Rule", detail: "When watching TV, put your phone in another room. Multiscreening raises cortisol." },
        { heading: "📌 Weekly Digital Sabbath", detail: "One evening per week go fully offline — read, cook, or go outdoors." },
      ]} />
    },
  };

  const setMovementReminder = () => {
    if (!("Notification" in window)) {
      alert("Set a 30-minute manual timer to remind yourself to stand and move!"); return;
    }
    Notification.requestPermission().then(perm => {
      if (perm === "granted") {
        alert("✅ Reminder set! You will get a notification in 30 minutes.");
        setTimeout(() => new Notification("🚶 Movement Break!", {
          body: "You've been sitting 30 minutes. Stand up, stretch, take a short walk!"
        }), 30 * 60 * 1000);
      } else {
        alert("Permission denied. Set a manual 30-minute timer to remind yourself to move.");
      }
    });
  };

  const cards = [
    { icon: "🧘", title: "Mindfulness Break", desc: "Live 4-7-8 breathing timer with animated visual to calm your nervous system.", action: "▶ Try Now", onClick: () => setBreathingOpen(true), color: "#6366f1" },
    { icon: "💪", title: "Desk Stretches", desc: "6 quick exercises at your desk in under 5 minutes to relieve tension.", action: "View Exercises", onClick: () => setModal("stretches"), color: "#8b5cf6" },
    { icon: "😴", title: "Sleep Hygiene", desc: "6 science-backed tips to improve sleep quality and ensure better recovery.", action: "Read Tips", onClick: () => setModal("sleep"), color: "#a78bfa" },
    { icon: "🥗", title: "Nutrition Tips", desc: "7 brain-boosting foods that reduce mental fatigue and improve cognitive ability.", action: "Explore Foods", onClick: () => setModal("nutrition"), color: "#4ade80" },
    { icon: "🚶", title: "Movement Breaks", desc: "Set a 30-minute browser notification reminder to stand up and move.", action: "🔔 Set Reminder", onClick: setMovementReminder, color: "#fb923c" },
    { icon: "📵", title: "Digital Detox", desc: "6 actionable strategies to disconnect from screens and recharge mentally.", action: "Learn Strategies", onClick: () => setModal("detox"), color: "#f87171" },
  ];

  return (
    <div>
      <h2 style={{ color: "#f3f4f6", fontSize: 24, fontWeight: 800, marginBottom: 6, marginTop: 0 }}>Wellness Center</h2>
      <p style={{ color: "#6b7280", marginBottom: 24 }}>Interactive tools and guides to protect your mental wellbeing.</p>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
        {cards.map((w, i) => (
          <div key={i} style={{ background: "#111827", border: "1px solid #1f2937", borderTop: `3px solid ${w.color}`, borderRadius: 12, padding: 20 }}>
            <div style={{ fontSize: 32, marginBottom: 8 }}>{w.icon}</div>
            <h4 style={{ color: "#f3f4f6", marginBottom: 6, marginTop: 0 }}>{w.title}</h4>
            <p style={{ color: "#9ca3af", fontSize: 13, marginBottom: 16, lineHeight: 1.5 }}>{w.desc}</p>
            <button onClick={w.onClick}
              style={{ background: `${w.color}22`, border: `1px solid ${w.color}55`, color: w.color, borderRadius: 6, padding: "8px 16px", fontSize: 13, cursor: "pointer", fontWeight: 600 }}
              onMouseEnter={e => { e.currentTarget.style.background = `${w.color}44`; }}
              onMouseLeave={e => { e.currentTarget.style.background = `${w.color}22`; }}
            >{w.action}</button>
          </div>
        ))}
      </div>
      {breathingOpen && <BreathingTimer onClose={() => setBreathingOpen(false)} />}
      {modal && MODALS[modal] && (
        <WellnessModal title={MODALS[modal].title} onClose={() => setModal(null)}>
          {MODALS[modal].el}
        </WellnessModal>
      )}
    </div>
  );
};

// ─── STRESS HEATMAP CALENDAR ──────────────────────────────────────────────────
const StressHeatmapCalendar = ({ isAdmin = false }) => {
  const [year, setYear] = React.useState(new Date().getFullYear());
  const [days, setDays] = React.useState([]);
  const [users, setUsers] = React.useState([]);
  const [selectedUserId, setSelectedUserId] = React.useState("");
  const [loading, setLoading] = React.useState(false);
  const [popup, setPopup] = React.useState(null);
  const [hovered, setHovered] = React.useState(null);

  // Fetch heatmap data
  React.useEffect(() => {
    setLoading(true);
    const url = isAdmin
      ? `/burnout/admin/heatmap?year=${year}${selectedUserId ? `&userId=${selectedUserId}` : ""}`
      : `/burnout/heatmap?year=${year}`;
    apiFetch(url)
      .then(data => {
        if (data && !data.error) {
          setDays(data.days || []);
          if (data.users) setUsers(data.users);
        } else {
          setDays([]);
        }
      })
      .catch(() => setDays([]))
      .finally(() => setLoading(false));
  }, [year, selectedUserId, isAdmin]);

  // Build day lookup: "YYYY-MM-DD" → data
  const dayMap = React.useMemo(() => {
    const m = {};
    (days || []).forEach(d => { m[d.date] = d; });
    return m;
  }, [days]);

  // Color from wellness score (client-side, matches ML engine gradient)
  const scoreToColor = (score) => {
    if (score == null) return "#1f2937";
    const s = Math.max(0, Math.min(100, score));
    let r, g, b;
    if (s >= 50) {
      const t = (s - 50) / 50;
      r = Math.round(245 + (34 - 245) * t);
      g = Math.round(158 + (197 - 158) * t);
      b = Math.round(11  + (94 - 11) * t);
    } else {
      const t = s / 50;
      r = Math.round(239 + (245 - 239) * t);
      g = Math.round(68  + (158 - 68) * t);
      b = Math.round(68  + (11 - 68) * t);
    }
    return `rgb(${r},${g},${b})`;
  };

  // Build calendar grid data: 53 columns × 7 rows (GitHub-style)
  const calendarCells = React.useMemo(() => {
    const jan1 = new Date(year, 0, 1);
    const dec31 = new Date(year, 11, 31);
    const startDow = jan1.getDay(); // 0=Sun
    const cells = [];

    // Fill from the first Sunday on or before Jan 1
    const startDate = new Date(jan1);
    startDate.setDate(startDate.getDate() - startDow);

    // Generate ~53 weeks
    const endDate = new Date(dec31);
    endDate.setDate(endDate.getDate() + (6 - dec31.getDay()));

    const cur = new Date(startDate);
    while (cur <= endDate) {
      const dateStr = cur.toISOString().split("T")[0];
      const isCurrentYear = cur.getFullYear() === year;
      cells.push({
        date: dateStr,
        dayOfWeek: cur.getDay(),
        month: cur.getMonth(),
        dayOfMonth: cur.getDate(),
        isCurrentYear,
        data: dayMap[dateStr] || null,
      });
      cur.setDate(cur.getDate() + 1);
    }
    return cells;
  }, [year, dayMap]);

  // Group cells into weeks (columns)
  const weeks = React.useMemo(() => {
    const w = [];
    for (let i = 0; i < calendarCells.length; i += 7) {
      w.push(calendarCells.slice(i, i + 7));
    }
    return w;
  }, [calendarCells]);

  // Month labels: find the first week where a month starts
  const monthLabels = React.useMemo(() => {
    const labels = [];
    const monthNames = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
    let lastMonth = -1;
    weeks.forEach((week, wIdx) => {
      for (const cell of week) {
        if (cell.isCurrentYear && cell.month !== lastMonth) {
          labels.push({ month: monthNames[cell.month], weekIdx: wIdx });
          lastMonth = cell.month;
          break;
        }
      }
    });
    return labels;
  }, [weeks]);

  const cellSize = 14;
  const cellGap = 3;
  const leftPad = 32;
  const topPad = 24;
  const gridW = weeks.length * (cellSize + cellGap) + leftPad + 8;
  const gridH = 7 * (cellSize + cellGap) + topPad + 8;

  const dayLabels = ["", "Mon", "", "Wed", "", "Fri", ""];

  const today = new Date().toISOString().split("T")[0];

  return (
    <div>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 20 }}>
        <div>
          <h2 style={{ color: "#f3f4f6", fontSize: 24, fontWeight: 800, margin: 0 }}>
            🗓️ Stress Heatmap Calendar
          </h2>
          <p style={{ color: "#6b7280", margin: "6px 0 0", fontSize: 14 }}>
            {isAdmin
              ? selectedUserId ? "Individual user's daily wellness scores" : "Team-wide average daily wellness scores"
              : "Your daily wellness scores — green is healthy, red is high stress"}
          </p>
        </div>

        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          {/* Admin user dropdown */}
          {isAdmin && (
            <select
              id="heatmap-user-select"
              value={selectedUserId}
              onChange={e => setSelectedUserId(e.target.value)}
              style={{
                background: "#1f2937", border: "1px solid #374151", color: "#f3f4f6",
                borderRadius: 8, padding: "8px 14px", fontSize: 13, outline: "none",
                cursor: "pointer", minWidth: 180
              }}
            >
              <option value="">👥 Team Average</option>
              {users.map(u => (
                <option key={u.id} value={u.id}>👤 {u.name}</option>
              ))}
            </select>
          )}

          {/* Year navigation */}
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <button
              onClick={() => setYear(y => y - 1)}
              style={{
                background: "#1f2937", border: "1px solid #374151", color: "#a78bfa",
                borderRadius: 6, padding: "6px 12px", cursor: "pointer", fontWeight: 700, fontSize: 16
              }}
            >←</button>
            <span style={{ color: "#f3f4f6", fontWeight: 800, fontSize: 16, minWidth: 50, textAlign: "center" }}>{year}</span>
            <button
              onClick={() => setYear(y => y + 1)}
              disabled={year >= new Date().getFullYear()}
              style={{
                background: "#1f2937", border: "1px solid #374151", color: year >= new Date().getFullYear() ? "#374151" : "#a78bfa",
                borderRadius: 6, padding: "6px 12px", cursor: "pointer", fontWeight: 700, fontSize: 16
              }}
            >→</button>
          </div>
        </div>
      </div>

      {/* Calendar Card */}
      <div style={{
        background: "#111827", border: "1px solid #1f2937", borderRadius: 12,
        padding: "24px 20px 20px", position: "relative", overflowX: "auto"
      }}>
        {loading ? (
          <div style={{ textAlign: "center", padding: "48px", color: "#6b7280" }}>
            <div style={{ fontSize: 32, marginBottom: 12, animation: "pulse 1.5s infinite" }}>🗓️</div>
            Loading heatmap data...
          </div>
        ) : (
          <>
            {/* Grid */}
            <svg width={gridW} height={gridH} style={{ display: "block" }}>
              {/* Month labels */}
              {monthLabels.map((ml, i) => (
                <text
                  key={i}
                  x={leftPad + ml.weekIdx * (cellSize + cellGap)}
                  y={14}
                  fill="#6b7280"
                  fontSize="11"
                  fontWeight="600"
                >{ml.month}</text>
              ))}

              {/* Day-of-week labels */}
              {dayLabels.map((label, i) => (
                label && (
                  <text
                    key={i}
                    x={0}
                    y={topPad + i * (cellSize + cellGap) + cellSize - 2}
                    fill="#4b5563"
                    fontSize="10"
                    fontWeight="500"
                  >{label}</text>
                )
              ))}

              {/* Day cells */}
              {weeks.map((week, wIdx) =>
                week.map((cell, dIdx) => {
                  if (!cell.isCurrentYear) return null;
                  const x = leftPad + wIdx * (cellSize + cellGap);
                  const y = topPad + dIdx * (cellSize + cellGap);
                  const hasData = cell.data != null;
                  const color = hasData ? scoreToColor(cell.data.wellness_score) : "#1a1a2e";
                  const isToday = cell.date === today;
                  const isHov = hovered === cell.date;

                  return (
                    <rect
                      key={cell.date}
                      x={x}
                      y={y}
                      width={cellSize}
                      height={cellSize}
                      rx={3}
                      fill={color}
                      stroke={isToday ? "#a78bfa" : isHov ? "#6366f1" : "transparent"}
                      strokeWidth={isToday ? 2 : isHov ? 1.5 : 0}
                      style={{ cursor: hasData ? "pointer" : "default", transition: "fill 0.2s" }}
                      onMouseEnter={() => setHovered(cell.date)}
                      onMouseLeave={() => setHovered(null)}
                      onClick={() => {
                        if (hasData) setPopup(popup === cell.date ? null : cell.date);
                      }}
                    >
                      <title>{cell.date}{hasData ? ` — Wellness: ${cell.data.wellness_score}` : ""}</title>
                    </rect>
                  );
                })
              )}
            </svg>

            {/* Popup */}
            {popup && dayMap[popup] && (() => {
              const d = dayMap[popup];
              const dateObj = new Date(popup + "T00:00:00");
              const riskColors = { HIGH: "#f87171", MEDIUM: "#fb923c", LOW: "#4ade80" };
              return (
                <div style={{
                  position: "absolute", top: 60, right: 20, width: 280,
                  background: "#0a0a0f", border: "1px solid #374151",
                  borderRadius: 12, padding: 20, boxShadow: "0 16px 48px rgba(0,0,0,0.6)",
                  zIndex: 10
                }}>
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 14 }}>
                    <span style={{ color: "#f3f4f6", fontWeight: 700, fontSize: 15 }}>
                      {dateObj.toLocaleDateString("en-US", { weekday: "short", month: "short", day: "numeric" })}
                    </span>
                    <button
                      onClick={() => setPopup(null)}
                      style={{ background: "none", border: "none", color: "#6b7280", fontSize: 18, cursor: "pointer" }}
                    >✕</button>
                  </div>

                  <div style={{
                    display: "flex", alignItems: "center", gap: 12, marginBottom: 14,
                    padding: "12px 14px", background: "#111827", borderRadius: 8,
                    border: `1px solid ${riskColors[d.risk_level] || "#374151"}22`
                  }}>
                    <div style={{
                      width: 48, height: 48, borderRadius: "50%",
                      background: `${riskColors[d.risk_level] || "#6366f1"}22`,
                      display: "flex", alignItems: "center", justifyContent: "center",
                      fontSize: 20, fontWeight: 800, color: riskColors[d.risk_level] || "#6366f1",
                      border: `2px solid ${riskColors[d.risk_level] || "#6366f1"}44`
                    }}>
                      {Math.round(d.wellness_score)}
                    </div>
                    <div>
                      <div style={{ color: "#f3f4f6", fontWeight: 700, fontSize: 14 }}>Wellness Score</div>
                      <div style={{
                        color: riskColors[d.risk_level] || "#818cf8",
                        fontSize: 12, fontWeight: 700, marginTop: 2
                      }}>
                        {d.risk_level} Risk
                      </div>
                    </div>
                  </div>

                  <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
                    {[
                      { label: "Risk Score", value: `${d.risk_score}%`, color: riskColors[d.risk_level] || "#818cf8" },
                      { label: "Avg Hours", value: `${d.avg_daily_hours}h`, color: "#818cf8" },
                      { label: "Predictions", value: d.predictions_count, color: "#a78bfa" },
                    ].map((item, i) => (
                      <div key={i} style={{
                        background: "#111827", borderRadius: 6, padding: "8px 10px",
                        border: "1px solid #1f2937"
                      }}>
                        <div style={{ color: "#6b7280", fontSize: 10, fontWeight: 600, textTransform: "uppercase" }}>{item.label}</div>
                        <div style={{ color: item.color, fontSize: 15, fontWeight: 800, marginTop: 2 }}>{item.value}</div>
                      </div>
                    ))}
                  </div>
                </div>
              );
            })()}

            {/* Legend */}
            <div style={{ display: "flex", alignItems: "center", gap: 12, marginTop: 16, flexWrap: "wrap" }}>
              <span style={{ color: "#6b7280", fontSize: 11, fontWeight: 600 }}>Less stress</span>
              <div style={{ display: "flex", gap: 3 }}>
                {[100, 85, 70, 55, 40, 25, 10, 0].map(score => (
                  <div
                    key={score}
                    style={{
                      width: 14, height: 14, borderRadius: 3,
                      background: scoreToColor(score)
                    }}
                    title={`Score: ${score}`}
                  />
                ))}
              </div>
              <span style={{ color: "#6b7280", fontSize: 11, fontWeight: 600 }}>More stress</span>

              <span style={{ color: "#374151", fontSize: 11, marginLeft: 8 }}>|</span>
              <div style={{ display: "flex", alignItems: "center", gap: 4 }}>
                <div style={{ width: 14, height: 14, borderRadius: 3, background: "#1a1a2e" }} />
                <span style={{ color: "#4b5563", fontSize: 11 }}>No data</span>
              </div>
              <div style={{ display: "flex", alignItems: "center", gap: 4 }}>
                <div style={{ width: 14, height: 14, borderRadius: 3, background: "#1a1a2e", border: "2px solid #a78bfa" }} />
                <span style={{ color: "#4b5563", fontSize: 11 }}>Today</span>
              </div>

              {/* Stats summary */}
              <div style={{ marginLeft: "auto", display: "flex", gap: 16 }}>
                <span style={{ color: "#4ade80", fontSize: 12, fontWeight: 700 }}>
                  {days.length} <span style={{ color: "#6b7280", fontWeight: 400 }}>days tracked</span>
                </span>
                {days.length > 0 && (
                  <span style={{ color: "#a78bfa", fontSize: 12, fontWeight: 700 }}>
                    {Math.round(days.reduce((sum, d) => sum + (d.wellness_score || 0), 0) / days.length)}
                    <span style={{ color: "#6b7280", fontWeight: 400 }}> avg score</span>
                  </span>
                )}
              </div>
            </div>
          </>
        )}
      </div>
    </div>
  );
};

// ─── ACTIVITY MONITOR WIDGET ──────────────────────────────────────────────────
const ActivityMonitorWidget = ({ stats, activeUser }) => {
  const statItems = [
    { label: "Active Time",    value: fmtSec(stats.totalActiveTime),       icon: "⚡", color: "#4ade80" },
    { label: "Idle Time",      value: fmtSec(stats.totalIdleTime),         icon: "💤", color: "#fb923c" },
    { label: "Screen Time",    value: fmtSec(stats.screenTime),            icon: "🖥️", color: "#818cf8" },
    { label: "Keystrokes",     value: stats.keyboardActivityCount.toLocaleString(), icon: "⌨️", color: "#6366f1" },
    { label: "Mouse Events",   value: stats.mouseActivityCount.toLocaleString(),    icon: "🖱️", color: "#a78bfa" },
  ];
  const total = stats.totalActiveTime + stats.totalIdleTime || 1;
  const activePct = Math.round((stats.totalActiveTime / total) * 100);
  const agentActive = stats.hasDesktopAgent;

  return (
    <div style={{ background: "#111827", border: "1px solid #1f2937", borderRadius: 12, padding: 24 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 16 }}>
        <h3 style={{ color: "#f3f4f6", margin: 0, fontSize: 16, fontWeight: 700 }}>📡 Live Activity Monitor</h3>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <span style={{ color: "#67e8f9", fontSize: 11, fontWeight: 700 }}>
            Active User: {activeUser?.name || "Unknown"}
          </span>
          {/* Desktop agent badge */}
          <span style={{
            fontSize: 10, fontWeight: 700, padding: "2px 8px", borderRadius: 12,
            background: agentActive ? "#052e16" : "#1f2937",
            color:      agentActive ? "#4ade80" : "#4b5563",
            border:     `1px solid ${agentActive ? "#166534" : "#374151"}`,
          }} title={agentActive
            ? "Desktop agent is running — counts include all apps, not just this browser"
            : "Desktop agent not detected — only browser activity is counted. Switch to another app and counts may pause."}>
            {agentActive ? "🖥️ Desktop Agent ON" : "⚠️ Browser Only"}
          </span>
          <div style={{ width: 8, height: 8, borderRadius: "50%", background: stats.isIdle ? "#fb923c" : "#4ade80",
            boxShadow: `0 0 8px ${stats.isIdle ? "#fb923c" : "#4ade80"}`, animation: "pulse 1.5s infinite" }} />
          <span style={{ color: stats.isIdle ? "#fb923c" : "#4ade80", fontSize: 12, fontWeight: 700 }}>
            {stats.isIdle ? "IDLE" : "ACTIVE"}
          </span>
        </div>
      </div>

      {/* Active vs Idle bar */}
      <div style={{ marginBottom: 16 }}>
        <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 4 }}>
          <span style={{ color: "#6b7280", fontSize: 11 }}>Focus Ratio</span>
          <span style={{ color: "#4ade80", fontSize: 11, fontWeight: 700 }}>{activePct}% active</span>
        </div>
        <div style={{ height: 6, background: "#1f2937", borderRadius: 99, overflow: "hidden" }}>
          <div style={{ height: "100%", width: `${activePct}%`, background: "linear-gradient(90deg, #4ade80, #22c55e)",
            borderRadius: 99, transition: "width 1s ease" }} />
        </div>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
        {statItems.map((s, i) => (
          <div key={i} style={{ background: "#0a0a0f", borderRadius: 8, padding: "10px 14px",
            border: `1px solid ${s.color}22` }}>
            <div style={{ fontSize: 11, color: "#6b7280", marginBottom: 2 }}>{s.icon} {s.label}</div>
            <div style={{ fontSize: 15, fontWeight: 800, color: s.color }}>{s.value}</div>
          </div>
        ))}
      </div>
      <p style={{ color: "#374151", fontSize: 10, marginTop: 12, marginBottom: 0 }}>
        {agentActive
          ? "✅ Desktop agent active — counts include all apps. Server syncs from agent every 30 s."
          : "📢 Run the desktop agent (agent.py) to track activity across ALL apps, not just this browser."}
      </p>
    </div>
  );
};

// ─── USER DASHBOARD ───────────────────────────────────────────────────────────
const UserDashboard = () => {
  const { user, logout } = useAuth();
  const activityStats = useActivityTracker(true); // ← start tracking on login
  const [latest, setLatest] = useState(null);
  const [submitting, setSubmitting] = useState(false);
  const [result, setResult] = useState(null);
  const [view, setView] = useState("dashboard");
  const [autoFilling, setAutoFilling] = useState(false);
  const [autoFillMsg, setAutoFillMsg] = useState("");
  const [form, setForm] = useState({
    avg_daily_hours: 8, break_frequency: 3, task_completion_rate: 0.75,
    overtime_days: 5, consecutive_work_days: 5, late_night_sessions: 3,
    weekend_work_days: 2, avg_session_length: 90
  });

  useEffect(() => {
    apiFetch("/burnout/latest").then(d => setLatest(d)).catch(() => { });
  }, []);

  const submitData = async () => {
    setSubmitting(true);
    try {
      const data = await apiFetch("/burnout/predict", { method: "POST", body: JSON.stringify(form) });
      setResult(data);
      setLatest({ risk_level: data.risk_level, risk_score: data.risk_score });
      setView("result");
    } catch { alert("Error connecting to server."); }
    setSubmitting(false);
  };

  // Auto-fill sliders from 8 hours of tracked activity data
  const autoFillFromTracking = async () => {
    setAutoFilling(true); setAutoFillMsg("");
    try {
      const summary = await apiFetch("/activity/summary?hours=8");
      if (summary.error) { setAutoFillMsg("⚠️ No tracking data yet. Use the app for a while first."); return; }
      setForm(prev => ({
        ...prev,
        avg_daily_hours:      summary.avg_daily_hours      || prev.avg_daily_hours,
        break_frequency:      summary.break_frequency      || prev.break_frequency,
        task_completion_rate: summary.task_completion_rate || prev.task_completion_rate,
        avg_session_length:   summary.avg_session_length   || prev.avg_session_length,
      }));
      setAutoFillMsg(`✅ Sliders auto-filled from ${summary.hoursAnalyzed}h of tracked activity!`);
    } catch { setAutoFillMsg("⚠️ Could not load activity data."); }
    setAutoFilling(false);
    setTimeout(() => setAutoFillMsg(""), 4000);
  };

  const sliders = [
    { key: "avg_daily_hours", label: "Avg Daily Work Hours", min: 1, max: 18, step: 0.5, unit: "hrs" },
    { key: "break_frequency", label: "Breaks Per Day", min: 0, max: 10, step: 0.5, unit: "" },
    { key: "task_completion_rate", label: "Task Completion Rate", min: 0, max: 1, step: 0.05, unit: "%" },
    { key: "overtime_days", label: "Overtime Days (last 30)", min: 0, max: 30, step: 1, unit: "d" },
    { key: "consecutive_work_days", label: "Consecutive Work Days", min: 1, max: 14, step: 1, unit: "d" },
    { key: "late_night_sessions", label: "Late Night Sessions", min: 0, max: 20, step: 1, unit: "" },
    { key: "weekend_work_days", label: "Weekend Days Worked", min: 0, max: 8, step: 1, unit: "d" },
    { key: "avg_session_length", label: "Avg Session Length", min: 15, max: 300, step: 5, unit: "min" },
  ];

  return (
    <div style={styles.dashWrap}>
      {/* SIDEBAR */}
      <aside style={styles.sidebar}>
        <div style={styles.sidelogo}>🧠 BurnoutGuard</div>
        <nav style={{ flex: 1, marginTop: 32 }}>
          {[
            { id: "dashboard", label: "Dashboard",    icon: icons.dashboard },
            { id: "activity", label: "Activity",      icon: icons.clock },
            { id: "assess",   label: "Assessment",    icon: icons.brain },
            { id: "result",   label: "Results",       icon: icons.chart },
            { id: "heatmap",  label: "Heatmap",       icon: icons.shield },
            { id: "wellness", label: "Wellness Tips", icon: icons.heart },
          ].map(item => (
            <div key={item.id} style={{ ...styles.navItem, ...(view === item.id ? styles.navItemActive : {}) }} onClick={() => setView(item.id)}>
              <Icon d={item.icon} size={18} />
              <span>{item.label}</span>
              {item.id === "activity" && (
                <div style={{ marginLeft: "auto", width: 7, height: 7, borderRadius: "50%",
                  background: activityStats.isIdle ? "#fb923c" : "#4ade80",
                  boxShadow: `0 0 6px ${activityStats.isIdle ? "#fb923c" : "#4ade80"}` }} />
              )}
            </div>
          ))}
        </nav>
        <div style={{ ...styles.sideUser, cursor: "pointer", borderTop: "1px solid #1f2937" }} onClick={logout}>
          <Icon d={icons.logout} size={18} color="#f87171" />
          <span style={{ color: "#f87171", fontSize: 13 }}>Logout</span>
        </div>
      </aside>

      {/* MAIN */}
      <main style={styles.main}>
        <div style={{ marginBottom: 18 }}>
          <ActiveUserPill user={user} context="User Dashboard" />
        </div>
        {view === "dashboard" && (
          <div>
            <h2 style={styles.pageTitle}>Welcome back, {user?.name?.split(" ")[0]} 👋</h2>
            <p style={{ color: "#6b7280", marginBottom: 24 }}>Here's your current mental wellness overview.</p>
            <div style={styles.cardRow}>
              <div style={styles.statCard}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                  <div>
                    <p style={styles.cardLabel}>Burnout Risk</p>
                    <RiskBadge level={latest?.risk_level || "NOT_ASSESSED"} />
                  </div>
                  <CircularGauge score={Math.round(latest?.risk_score || 0)} level={latest?.risk_level || "NOT_ASSESSED"} />
                </div>
              </div>
              <div style={styles.statCard}>
                <p style={styles.cardLabel}>Active Time Today</p>
                <p style={styles.bigNum}>
                  {Math.floor(activityStats.totalActiveTime / 3600)}
                  <span style={{ fontSize: 16, color: "#6b7280" }}>h </span>
                  {Math.floor((activityStats.totalActiveTime % 3600) / 60)}
                  <span style={{ fontSize: 16, color: "#6b7280" }}>m</span>
                </p>
                <p style={{ color: activityStats.isIdle ? "#fb923c" : "#4ade80", fontSize: 13, fontWeight: 600 }}>
                  {activityStats.isIdle ? "💤 Currently Idle" : "⚡ Currently Active"}
                </p>
              </div>
              <div style={styles.statCard}>
                <p style={styles.cardLabel}>Last Assessment</p>
                <p style={{ color: "#a78bfa", fontSize: 14, marginTop: 8 }}>{latest?.predicted_at ? new Date(latest.predicted_at).toLocaleDateString() : "Not assessed yet"}</p>
                <button style={styles.btnSm} onClick={() => setView("assess")}>Run Assessment →</button>
              </div>
            </div>

            {/* Live Activity Mini-Widget */}
            <div style={{ marginTop: 24 }}>
              <ActivityMonitorWidget stats={activityStats} activeUser={user} />
            </div>
            <div style={{ marginTop: 24 }}>
              <UsageDonutChart
                activeSeconds={activityStats.totalActiveTime}
                idleSeconds={activityStats.totalIdleTime}
                title="Today's Stress/Usage Split"
              />
            </div>

            <div style={{ ...styles.card, marginTop: 24 }}>
              <h3 style={styles.cardTitle}>🎯 Quick Tips</h3>
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12, marginTop: 16 }}>
                {[
                  { icon: "⏰", tip: "Take a 5-min break every hour" },
                  { icon: "💧", tip: "Stay hydrated throughout the day" },
                  { icon: "🧘", tip: "Try a short breathing exercise" },
                  { icon: "🚶", tip: "A short walk improves focus" },
                ].map((t, i) => (
                  <div key={i} style={styles.tipCard}>{t.icon} {t.tip}</div>
                ))}
              </div>
            </div>
          </div>
        )}

        {/* ─── ACTIVITY VIEW ─────────────────────────────────────────────── */}
        {view === "activity" && (
          <div>
            <h2 style={styles.pageTitle}>📡 Activity Tracking</h2>
            <p style={{ color: "#6b7280", marginBottom: 24 }}>Real-time browser activity monitoring. Data auto-syncs to server every 60 seconds.</p>

            <ActivityMonitorWidget stats={activityStats} activeUser={user} />

            {/* Detailed stats grid */}
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 16, marginTop: 24 }}>
              {[
                { label: "Keystrokes",   value: activityStats.keyboardActivityCount.toLocaleString(), icon: "⌨️", sub: "total key presses",     color: "#6366f1" },
                { label: "Mouse Events", value: activityStats.mouseActivityCount.toLocaleString(),    icon: "🖱️", sub: "throttled move events",  color: "#a78bfa" },
                { label: "Screen Time",  value: fmtSec(activityStats.screenTime),                    icon: "🖥️", sub: "tab focused & visible",  color: "#818cf8" },
                { label: "Active Time",  value: fmtSec(activityStats.totalActiveTime),               icon: "⚡", sub: "typing or clicking",     color: "#4ade80" },
                { label: "Idle Time",    value: fmtSec(activityStats.totalIdleTime),                 icon: "💤", sub: ">2 min no activity",     color: "#fb923c" },
                { label: "Focus Score",
                  value: `${Math.round((activityStats.totalActiveTime / Math.max(1, activityStats.totalActiveTime + activityStats.totalIdleTime)) * 100)}%`,
                  icon: "🎯", sub: "active / total time", color: "#f59e0b" },
              ].map((s, i) => (
                <div key={i} style={{ ...styles.statCard, borderTop: `3px solid ${s.color}` }}>
                  <p style={styles.cardLabel}>{s.icon} {s.label}</p>
                  <p style={{ ...styles.bigNum, color: s.color, fontSize: 28 }}>{s.value}</p>
                  <p style={{ color: "#6b7280", fontSize: 11, margin: 0 }}>{s.sub}</p>
                </div>
              ))}
            </div>

            <div style={{ ...styles.card, marginTop: 24, borderLeft: "3px solid #6366f1" }}>
              <h3 style={{ ...styles.cardTitle, marginBottom: 12 }}>🤖 How This Improves Burnout Prediction</h3>
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
                {[
                  { feature: "avg_daily_hours",      desc: "Derived from total active + idle time per session" },
                  { feature: "break_frequency",      desc: "Estimated from idle bursts (>2 min, counted as breaks)" },
                  { feature: "task_completion_rate", desc: "Active time ratio — high focus = higher completion" },
                  { feature: "avg_session_length",   desc: "Average uninterrupted active work block" },
                ].map((m, i) => (
                  <div key={i} style={{ background: "#0a0a0f", borderRadius: 8, padding: 14, border: "1px solid #1f2937" }}>
                    <code style={{ color: "#a78bfa", fontSize: 12, fontFamily: "monospace" }}>{m.feature}</code>
                    <p style={{ color: "#9ca3af", fontSize: 12, margin: "6px 0 0" }}>{m.desc}</p>
                  </div>
                ))}
              </div>
              <div style={{ marginTop: 16, padding: "10px 14px", background: "#1a1033", borderRadius: 8, border: "1px solid #312e81" }}>
                <p style={{ color: "#a78bfa", fontSize: 12, margin: 0 }}>
                  ⚡ Data is sent to <code style={{ fontFamily: "monospace" }}>POST /api/activity/log</code> every 60 seconds.
                  Use <strong>Auto-Fill Assessment</strong> in the Assessment tab to pre-populate sliders with your real data.
                </p>
              </div>
            </div>
          </div>
        )}

        {view === "assess" && (
          <div>
            <h2 style={styles.pageTitle}>Work Behavior Assessment</h2>
            <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 20 }}>
              <p style={{ color: "#6b7280", margin: 0, fontSize: 14 }}>Adjust the sliders manually or auto-fill from your tracked activity.</p>
              <button
                id="auto-fill-btn"
                style={{ ...styles.btnSm, background: "linear-gradient(135deg,#6366f1,#8b5cf6)",
                  color: "#fff", border: "none", whiteSpace: "nowrap",
                  opacity: autoFilling ? 0.7 : 1 }}
                onClick={autoFillFromTracking}
                disabled={autoFilling}
              >
                {autoFilling ? "Loading..." : "🤖 Auto-Fill from Activity"}
              </button>
            </div>
            {autoFillMsg && (
              <div style={{ background: autoFillMsg.startsWith("✅") ? "#052e16" : "#431407",
                border: `1px solid ${autoFillMsg.startsWith("✅") ? "#166534" : "#9a3412"}`,
                color: autoFillMsg.startsWith("✅") ? "#4ade80" : "#fb923c",
                borderRadius: 8, padding: "10px 14px", marginBottom: 16, fontSize: 13 }}>
                {autoFillMsg}
              </div>
            )}
            <div style={styles.card}>
              {sliders.map(s => (
                <div key={s.key} style={{ marginBottom: 20 }}>
                  <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 6 }}>
                    <label style={{ color: "#d1d5db", fontSize: 14 }}>{s.label}</label>
                    <span style={{ color: "#6366f1", fontWeight: 700, fontSize: 14 }}>
                      {s.key === "task_completion_rate" ? `${Math.round(form[s.key] * 100)}%` : `${form[s.key]}${s.unit}`}
                    </span>
                  </div>
                  <input type="range" min={s.min} max={s.max} step={s.step}
                    value={form[s.key]} onChange={e => setForm({ ...form, [s.key]: parseFloat(e.target.value) })}
                    style={styles.slider} />
                </div>
              ))}
              <button style={{ ...styles.btn, marginTop: 12, opacity: submitting ? 0.7 : 1 }} onClick={submitData} disabled={submitting}>
                {submitting ? "Analyzing..." : "🚀 Analyze My Burnout Risk"}
              </button>
            </div>
          </div>
        )}

        {view === "result" && (
          <div>
            <h2 style={styles.pageTitle}>Assessment Results</h2>
            {result ? (
              <div>
                <div style={{ ...styles.card, textAlign: "center", marginBottom: 24 }}>
                  <CircularGauge score={Math.round(result.risk_score)} level={result.risk_level} />
                  <h3 style={{ color: "#f3f4f6", marginTop: 16, fontSize: 22 }}>Burnout Risk: <span style={{ color: result.risk_level === "HIGH" ? "#f87171" : result.risk_level === "MEDIUM" ? "#fb923c" : "#4ade80" }}>{result.risk_level}</span></h3>
                  <div style={{ display: "flex", justifyContent: "center", gap: 20, marginTop: 20 }}>
                    {["LOW", "MEDIUM", "HIGH"].map(l => (
                      <div key={l} style={styles.probBox}>
                        <div style={{ color: l === "HIGH" ? "#f87171" : l === "MEDIUM" ? "#fb923c" : "#4ade80", fontSize: 18, fontWeight: 800 }}>{result.probabilities[l]}%</div>
                        <div style={{ color: "#6b7280", fontSize: 11 }}>{l}</div>
                      </div>
                    ))}
                  </div>
                </div>
                <div style={styles.card}>
                  <h3 style={styles.cardTitle}>💡 Personalized Recommendations</h3>
                  {result.recommendations?.map((r, i) => (
                    <div key={i} style={styles.recItem}>
                      <span style={styles.recBadge}>{r.category}</span>
                      <span style={{ color: "#d1d5db", fontSize: 14 }}>{r.text}</span>
                    </div>
                  ))}
                </div>
              </div>
            ) : (
              <div style={styles.emptyState}>
                <p>No results yet. Go to <strong style={{ color: "#6366f1" }}>Assessment</strong> to analyze your burnout risk.</p>
                <button style={styles.btnSm} onClick={() => setView("assess")}>Start Assessment</button>
              </div>
            )}
          </div>
        )}

        {view === "heatmap" && (
          <StressHeatmapCalendar isAdmin={false} />
        )}

        {view === "wellness" && (
          <WellnessCenter />
        )}
      </main>
    </div>
  );
};

// ─── ADMIN WINDOW HISTORY ────────────────────────────────────────────────────
const AdminWindowHistory = ({ users, activeAdmin }) => {
  const [expanded, setExpanded] = React.useState(null);
  const [histories, setHistories] = React.useState({});
  const [loading, setLoading] = React.useState({});
  const [search, setSearch] = React.useState("");

  const fetchHistory = async (userId, forceRefresh = false) => {
    if (histories[userId] && !forceRefresh) { setExpanded(expanded === userId ? null : userId); return; }
    setLoading(l => ({ ...l, [userId]: true }));
    setExpanded(userId);
    try {
      const data = await apiFetch(`/activity/window-history/${userId}`);
      setHistories(h => ({ ...h, [userId]: data.history || data || [] }));
    } catch {
      setHistories(h => ({ ...h, [userId]: [] }));
    }
    setLoading(l => ({ ...l, [userId]: false }));
  };

  React.useEffect(() => {
    if (!expanded) return;
    const interval = setInterval(() => {
      fetchHistory(expanded, true);
    }, 15000);
    return () => clearInterval(interval);
  }, [expanded]);

  const appColor = (title) => {
    const t = (title || "").toLowerCase();
    if (t.includes("chrome") || t.includes("edge") || t.includes("firefox")) return "#3b82f6";
    if (t.includes("code") || t.includes("visual studio") || t.includes("intellij")) return "#6366f1";
    if (t.includes("slack") || t.includes("teams") || t.includes("zoom")) return "#10b981";
    if (t.includes("excel") || t.includes("word") || t.includes("powerpoint") || t.includes("office")) return "#f59e0b";
    if (t.includes("terminal") || t.includes("cmd") || t.includes("powershell")) return "#a78bfa";
    if (t.includes("youtube") || t.includes("netflix") || t.includes("spotify")) return "#ef4444";
    return "#6b7280";
  };

  const filteredUsers = (users || []).filter(u =>
    !search || u.name?.toLowerCase().includes(search.toLowerCase()) ||
    u.department?.toLowerCase().includes(search.toLowerCase())
  );

  return (
    <div>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 20 }}>
        <div>
          <h2 style={{ color: "#f3f4f6", fontSize: 24, fontWeight: 800, margin: 0 }}>🪟 Window Activity History</h2>
          <p style={{ color: "#6b7280", margin: "6px 0 0", fontSize: 14 }}>
            Auto-Save is enabled. Window history updates automatically every 15 seconds.
          </p>
          <p style={{ color: "#67e8f9", margin: "4px 0 0", fontSize: 12 }}>
            Active User (Admin): {activeAdmin?.name || "Unknown"}
          </p>
        </div>
        <input
          style={{ background: "#1f2937", border: "1px solid #374151", color: "#f3f4f6",
            borderRadius: 8, padding: "8px 14px", fontSize: 13, outline: "none", width: 220 }}
          placeholder="🔍 Search users..."
          value={search} onChange={e => setSearch(e.target.value)}
        />
      </div>

      {filteredUsers.length === 0 && (
        <div style={{ textAlign: "center", padding: "48px", color: "#6b7280", background: "#111827",
          border: "1px solid #1f2937", borderRadius: 12 }}>No users found.</div>
      )}

      {filteredUsers.map((u, idx) => {
        const isOpen = expanded === u.id;
        const hist = histories[u.id] || [];
        const isLoad = loading[u.id];
        return (
          <div key={idx} style={{ marginBottom: 10, background: "#111827",
            border: `1px solid ${isOpen ? "#6366f1" : "#1f2937"}`,
            borderRadius: 12, overflow: "hidden",
            boxShadow: isOpen ? "0 0 0 1px #6366f133" : "none",
            transition: "border-color 0.2s" }}>

            {/* Row header */}
            <div
              onClick={() => fetchHistory(u.id)}
              style={{ display: "flex", alignItems: "center", padding: "14px 20px",
                cursor: "pointer", gap: 14, userSelect: "none" }}
            >
              {/* Avatar */}
              <div style={{ width: 36, height: 36, borderRadius: "50%",
                background: "linear-gradient(135deg,#6366f1,#8b5cf6)",
                display: "flex", alignItems: "center", justifyContent: "center",
                color: "#fff", fontWeight: 800, fontSize: 15, flexShrink: 0 }}>
                {u.name?.[0]?.toUpperCase()}
              </div>
              <div style={{ flex: 1 }}>
                <div style={{ color: "#f3f4f6", fontWeight: 700, fontSize: 14 }}>{u.name}</div>
                <div style={{ color: "#6b7280", fontSize: 12 }}>{u.department || "—"} · {u.email}</div>
              </div>
              {/* Stats chips */}
              <div style={{ display: "flex", gap: 8 }}>
                {u.has_activity && (
                  <span style={{ fontSize: 11, padding: "3px 10px", borderRadius: 20,
                    background: "#052e16", color: "#4ade80", border: "1px solid #166534",
                    fontWeight: 700 }}>Active</span>
                )}
                <span style={{ fontSize: 11, padding: "3px 10px", borderRadius: 20,
                  background: "#082f49", color: "#67e8f9", border: "1px solid #155e75", fontWeight: 700 }}>
                  Active User: {u.name}
                </span>
                {u.active_tab && (
                  <span style={{ fontSize: 11, padding: "3px 10px", borderRadius: 20,
                    background: "#1e1b4b", color: "#818cf8", border: "1px solid #3730a3",
                    fontWeight: 600, maxWidth: 180, overflow: "hidden",
                    textOverflow: "ellipsis", whiteSpace: "nowrap" }}
                    title={u.active_tab}>🪟 {u.active_tab}</span>
                )}
              </div>
              <div style={{ color: "#6b7280", fontSize: 18, transition: "transform 0.2s",
                transform: isOpen ? "rotate(90deg)" : "none" }}>›</div>
            </div>

            {/* Expandable history */}
            {isOpen && (
              <div style={{ borderTop: "1px solid #1f2937", padding: "16px 20px" }}>
                {isLoad ? (
                  <p style={{ color: "#6b7280", textAlign: "center", padding: "20px 0" }}>Loading history…</p>
                ) : hist.length === 0 ? (
                  <div style={{ textAlign: "center", padding: "20px 0" }}>
                    <div style={{ fontSize: 32, marginBottom: 8 }}>🪟</div>
                    <p style={{ color: "#6b7280", fontSize: 13 }}>No window history available yet.<br/>The desktop agent will populate this as the user works.</p>
                  </div>
                ) : (
                  <div>
                    <div style={{ fontSize: 11, color: "#6b7280", fontWeight: 700,
                      letterSpacing: 1, marginBottom: 12 }}>RECENT WINDOW SWITCHES ({hist.length})</div>
                    <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                      {hist.slice().reverse().map((entry, i) => {
                        const title = entry.title || entry.window || entry;
                        const ts    = entry.ts || entry.timestamp || "";
                        const dur   = entry.duration;
                        const color = appColor(title);
                        return (
                          <div key={i} style={{ display: "flex", alignItems: "center",
                            gap: 12, padding: "8px 12px", borderRadius: 8,
                            background: "#0a0a0f", border: `1px solid ${color}22` }}>
                            <div style={{ width: 3, height: 32, background: color,
                              borderRadius: 2, flexShrink: 0 }} />
                            <div style={{ flex: 1, minWidth: 0 }}>
                              <div style={{ color: "#e5e7eb", fontSize: 13, fontWeight: 600,
                                overflow: "hidden", textOverflow: "ellipsis",
                                whiteSpace: "nowrap" }} title={title}>{title}</div>
                              {ts && <div style={{ color: "#4b5563", fontSize: 11 }}>{ts}</div>}
                            </div>
                            {dur != null && (
                              <div style={{ color: color, fontSize: 12,
                                fontWeight: 700, flexShrink: 0 }}>{dur}s</div>
                            )}
                          </div>
                        );
                      })}
                    </div>
                  </div>
                )}
              </div>
            )}
          </div>
        );
      })}

      <p style={{ color: "#374151", fontSize: 11, marginTop: 16 }}>
        ⚡ Window history is recorded by the desktop agent (agent.py) and stored via the backend. Data appears within 30s of each switch.
      </p>
    </div>
  );
};

// ─── ADMIN DASHBOARD ──────────────────────────────────────────────────────────
// Helper: format seconds to "Xh Ym Zs"
const fmtSecAdmin = (s) => {
  if (!s || s === 0) return "0s";
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = s % 60;
  if (h > 0) return `${h}h ${m}m`;
  if (m > 0) return `${m}m ${sec}s`;
  return `${sec}s`;
};

const AdminDashboard = () => {
  const { user, logout } = useAuth();
  const [view, setView] = useState("overview");
  const [overview, setOverview] = useState(null);

  // Fetch overview AND full user list, merge so every newly registered
  // account shows up in the panel immediately (even before activity data).
  useEffect(() => {
    const fetchOverview = async () => {
      try {
        // Fetch both in parallel
        const [overviewData, allUsers] = await Promise.all([
          apiFetch("/burnout/admin/overview"),
          apiFetch("/auth/users"),
        ]);

        if (!overviewData || overviewData.error) return;

        // Build a set of user IDs already present in the burnout overview
        const overviewIds = new Set((overviewData.users || []).map(u => u.id));

        // Add any registered users not yet in the burnout overview
        // (they have no activity yet, so the overview query might miss them)
        const missingUsers = (Array.isArray(allUsers) ? allUsers : [])
          .filter(u => !overviewIds.has(u.id))
          .map(u => ({
            id:              u.id,
            name:            u.name,
            email:           u.email,
            department:      u.department,
            has_activity:    false,
            last_seen:       null,
            active_tab:      "—",
            active_time_sec: 0,
            idle_time_sec:   0,
            keyboard_count:  0,
            mouse_count:     0,
            screen_time_sec: 0,
            risk_level:      "NOT_ASSESSED",
            risk_score:      0,
          }));

        setOverview({
          ...overviewData,
          total_users: (overviewData.total_users || 0) + missingUsers.length,
          users: [...(overviewData.users || []), ...missingUsers],
        });
      } catch (_) {}
    };

    fetchOverview();
    const interval = setInterval(fetchOverview, 10000); // refresh every 10 s
    return () => clearInterval(interval);
  }, []);

  const riskColor = (level) => ({ HIGH: "#f87171", MEDIUM: "#fb923c", LOW: "#4ade80", NOT_ASSESSED: "#818cf8" }[level] || "#818cf8");

  // Online means currently active from desktop app snapshots.
  // Agent posts frequently, so keep this window strict.
  const isRecentlyActive = (lastSeen) => {
    if (!lastSeen) return false;
    const diff = (Date.now() - new Date(lastSeen).getTime()) / 1000;
    return diff < 90; // 90 seconds
  };

  return (
    <div style={styles.dashWrap}>
      <aside style={styles.sidebar}>
        <div style={styles.sidelogo}>⚙️ Admin Panel</div>
        <nav style={{ flex: 1, marginTop: 32 }}>
          {[
            { id: "overview",  label: "Team Overview",   icon: icons.team },
            { id: "activity",  label: "Live Activity",   icon: icons.clock },
            { id: "windows",   label: "Window History",  icon: icons.settings },
            { id: "users",     label: "Risk Table",      icon: icons.user },
            { id: "heatmap",   label: "Stress Heatmap",  icon: icons.shield },
            { id: "reports",   label: "Reports",         icon: icons.chart },
          ].map(item => (
            <div key={item.id} style={{ ...styles.navItem, ...(view === item.id ? styles.navItemActive : {}) }} onClick={() => setView(item.id)}>
              <Icon d={item.icon} size={18} />
              <span>{item.label}</span>
              {item.id === "activity" && (
                <div style={{ marginLeft: "auto", width: 7, height: 7, borderRadius: "50%",
                  background: "#4ade80", boxShadow: "0 0 6px #4ade80", animation: "pulse 1.5s infinite" }} />
              )}
              {item.id === "windows" && (
                <span style={{ marginLeft: "auto", fontSize: 10, background: "#1e1b4b",
                  color: "#818cf8", border: "1px solid #3730a3", borderRadius: 10,
                  padding: "1px 7px", fontWeight: 700 }}>NEW</span>
              )}
            </div>
          ))}
        </nav>
        <div style={{ ...styles.sideUser, cursor: "pointer" }} onClick={logout}>
          <Icon d={icons.logout} size={18} color="#f87171" />
          <span style={{ color: "#f87171", fontSize: 13 }}>Logout</span>
        </div>
      </aside>

      <main style={styles.main}>
        <div style={{ marginBottom: 18 }}>
          <ActiveUserPill user={user} context="Admin Panel" />
        </div>
        {view === "overview" && (
          <div>
            <h2 style={styles.pageTitle}>Team Burnout Overview</h2>
            <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 24 }}>
              <p style={{ color: "#6b7280", margin: 0 }}>Monitor your team's mental wellness at a glance.</p>
              <span style={{ fontSize: 11, color: "#4ade80", background: "#052e16", border: "1px solid #166534",
                padding: "2px 8px", borderRadius: 10, fontWeight: 700 }}>🔄 Auto-refresh 15s</span>
            </div>
            <div style={styles.cardRow}>
              {[
                { label: "Total Users",  value: overview?.total_users || 0,  color: "#818cf8" },
                { label: "High Risk",    value: overview?.high_risk   || 0,  color: "#f87171" },
                { label: "Medium Risk",  value: overview?.medium_risk || 0,  color: "#fb923c" },
                { label: "Low Risk",     value: overview?.low_risk    || 0,  color: "#4ade80" },
              ].map((s, i) => (
                <div key={i} style={{ ...styles.statCard, borderTop: `3px solid ${s.color}` }}>
                  <p style={styles.cardLabel}>{s.label}</p>
                  <p style={{ ...styles.bigNum, color: s.color }}>{s.value}</p>
                </div>
              ))}
            </div>

            {overview && overview.total_users > 0 && (
              <div style={{ marginTop: 24 }}>
                <UsageDonutChart
                  activeSeconds={(overview.users || []).reduce((sum, u) => sum + (u.active_time_sec || 0), 0)}
                  idleSeconds={(overview.users || []).reduce((sum, u) => sum + (u.idle_time_sec || 0), 0)}
                  title="Team Stress/Usage Hours (24h)"
                />
              </div>
            )}
          </div>
        )}

        {/* ─── LIVE ACTIVITY TAB ────────────────────────────────────────────────── */}
        {view === "activity" && (
          <div>
            <h2 style={styles.pageTitle}>📡 Live User Activity</h2>
            <p style={{ color: "#6b7280", marginBottom: 24 }}>
              Real-time activity data from desktop agents (last 24h). Refreshes every 15 seconds.
            </p>

            {/* Summary bar */}
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 16, marginBottom: 24 }}>
              {[
                {
                  label: "Active Users (24h)",
                  value: (overview?.users || []).filter(u => u.has_activity).length,
                  color: "#4ade80"
                },
                {
                  label: "Online Now (<5 min)",
                  value: (overview?.users || []).filter(u => isRecentlyActive(u.last_seen)).length,
                  color: "#6366f1"
                },
                {
                  label: "No Activity Today",
                  value: (overview?.users || []).filter(u => !u.has_activity).length,
                  color: "#fb923c"
                },
              ].map((s, i) => (
                <div key={i} style={{ ...styles.statCard, borderTop: `3px solid ${s.color}` }}>
                  <p style={styles.cardLabel}>{s.label}</p>
                  <p style={{ ...styles.bigNum, color: s.color, fontSize: 32 }}>{s.value}</p>
                </div>
              ))}
            </div>

            <div style={styles.card}>
              <table style={{ width: "100%", borderCollapse: "collapse" }}>
                <thead>
                  <tr>
                    {["Status", "Active User", "Department", "Last Seen", "Active Window", "Active Time", "Idle Time", "⌨ Keys", "🖱 Mouse"].map(h => (
                      <th key={h} style={{ textAlign: "left", color: "#6b7280", fontSize: 11, fontWeight: 600,
                        padding: "8px 10px", borderBottom: "1px solid #1f2937", letterSpacing: 0.5,
                        textTransform: "uppercase" }}>{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {(overview?.users || []).length === 0 ? (
                    <tr><td colSpan={9} style={{ color: "#6b7280", textAlign: "center", padding: 32 }}>No users found.</td></tr>
                  ) : (
                    (overview?.users || []).map((u, i) => {
                      const online = isRecentlyActive(u.last_seen);
                      const statusColor = online ? "#4ade80" : "#4b5563";
                      const statusLabel = online ? "ONLINE" : "OFFLINE";
                      const lastSeenStr = u.last_seen
                        ? new Date(u.last_seen).toLocaleString([], {
                            year: "numeric",
                            month: "short",
                            day: "2-digit",
                            hour: "2-digit",
                            minute: "2-digit",
                            second: "2-digit",
                          })
                        : "—";
                      return (
                        <tr key={i} style={{ borderBottom: "1px solid #111827" }}>
                          <td style={{ ...styles.td, padding: "10px 10px" }}>
                            <span style={{
                              fontSize: 10, fontWeight: 700, padding: "2px 8px", borderRadius: 10,
                              background: `${statusColor}18`, color: statusColor, border: `1px solid ${statusColor}44`
                            }}>{statusLabel}</span>
                          </td>
                          <td style={{ ...styles.td, color: "#67e8f9", fontWeight: 700 }}>{u.name}</td>
                          <td style={{ ...styles.td, color: "#6b7280" }}>{u.department || "—"}</td>
                          <td style={{ ...styles.td, color: "#9ca3af", fontSize: 12 }}>{lastSeenStr}</td>
                          <td style={{ ...styles.td, color: "#9ca3af", maxWidth: 150, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }} title={u.active_tab}>{u.active_tab || "—"}</td>
                          <td style={{ ...styles.td, color: "#4ade80", fontWeight: 700 }}>{fmtSecAdmin(u.active_time_sec)}</td>
                          <td style={{ ...styles.td, color: "#fb923c" }}>{fmtSecAdmin(u.idle_time_sec)}</td>
                          <td style={{ ...styles.td, color: "#6366f1", fontWeight: 600 }}>{(u.keyboard_count || 0).toLocaleString()}</td>
                          <td style={{ ...styles.td, color: "#a78bfa", fontWeight: 600 }}>{(u.mouse_count || 0).toLocaleString()}</td>
                        </tr>
                      );
                    })
                  )}
                </tbody>
              </table>
            </div>
            <p style={{ color: "#374151", fontSize: 11, marginTop: 12 }}>
              ⚡ Data sent by the desktop agent (agent.py) appears here within 15 seconds of each snapshot.
              When the agent stops, the final snapshot is sent immediately.
            </p>
          </div>
        )}

        {view === "windows" && (
          <AdminWindowHistory users={overview?.users || []} activeAdmin={user} />
        )}

        {view === "users" && (
          <div>
            <h2 style={styles.pageTitle}>User Risk Table</h2>
            <div style={styles.card}>
              <table style={{ width: "100%", borderCollapse: "collapse" }}>
                <thead>
                  <tr>{["Name", "Email", "Department", "Risk Level", "Risk Score"].map(h => (
                    <th key={h} style={{ textAlign: "left", color: "#6b7280", fontSize: 12, fontWeight: 600, padding: "8px 12px", borderBottom: "1px solid #1f2937", letterSpacing: 0.5 }}>{h.toUpperCase()}</th>
                  ))}</tr>
                </thead>
                <tbody>
                  {(overview?.users || []).map((u, i) => (
                    <tr key={i} style={{ borderBottom: "1px solid #111827" }}>
                      <td style={styles.td}>{u.name}</td>
                      <td style={{ ...styles.td, color: "#6b7280" }}>{u.email}</td>
                      <td style={styles.td}>{u.department || "-"}</td>
                      <td style={styles.td}><RiskBadge level={u.risk_level} /></td>
                      <td style={{ ...styles.td, color: riskColor(u.risk_level), fontWeight: 700 }}>{u.risk_score ? `${u.risk_score.toFixed(1)}%` : "-"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {(!overview?.users || overview.users.length === 0) && (
                <p style={{ color: "#6b7280", textAlign: "center", padding: 32 }}>No user data available yet.</p>
              )}
            </div>
          </div>
        )}

        {view === "reports" && (
          <div>
            <h2 style={styles.pageTitle}>Organizational Reports</h2>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
              {[
                {
                  title: "Weekly Burnout Summary",
                  desc: "Summary of team burnout risk levels this week.",
                  content: () => `
                    <h2>Weekly Burnout Summary</h2>
                    <p>Generated: ${new Date().toLocaleString()}</p>
                    <hr/>
                    <p><b>Total Users:</b> ${overview?.total_users ?? 0}</p>
                    <p><b>High Risk:</b> ${overview?.high_risk ?? 0}</p>
                    <p><b>Medium Risk:</b> ${overview?.medium_risk ?? 0}</p>
                    <p><b>Low Risk:</b> ${overview?.low_risk ?? 0}</p>
                    <hr/>
                    <h3>User Details</h3>
                    <table border="1" cellpadding="6" style="border-collapse:collapse;width:100%">
                      <thead><tr><th>Name</th><th>Email</th><th>Department</th><th>Risk Level</th><th>Score</th></tr></thead>
                      <tbody>${(overview?.users || []).map(u => `<tr><td>${u.name}</td><td>${u.email}</td><td>${u.department || '-'}</td><td>${u.risk_level}</td><td>${u.risk_score ? u.risk_score.toFixed(1) + '%' : '-'}</td></tr>`).join('')}</tbody>
                    </table>
                  `
                },
                {
                  title: "Workload Distribution",
                  desc: "Distribution of workload across the team.",
                  content: () => `
                    <h2>Workload Distribution Report</h2>
                    <p>Generated: ${new Date().toLocaleString()}</p>
                    <hr/>
                    <p><b>Total Users Tracked:</b> ${overview?.total_users ?? 0}</p>
                    <table border="1" cellpadding="6" style="border-collapse:collapse;width:100%">
                      <thead><tr><th>Name</th><th>Department</th><th>Risk Level</th></tr></thead>
                      <tbody>${(overview?.users || []).map(u => `<tr><td>${u.name}</td><td>${u.department || '-'}</td><td>${u.risk_level}</td></tr>`).join('')}</tbody>
                    </table>
                  `
                },
                {
                  title: "Department Risk Analysis",
                  desc: "Risk breakdown grouped by department.",
                  content: () => {
                    const depts = {};
                    (overview?.users || []).forEach(u => {
                      const d = u.department || 'General';
                      if (!depts[d]) depts[d] = { HIGH: 0, MEDIUM: 0, LOW: 0, NOT_ASSESSED: 0 };
                      depts[d][u.risk_level] = (depts[d][u.risk_level] || 0) + 1;
                    });
                    return `
                      <h2>Department Risk Analysis</h2>
                      <p>Generated: ${new Date().toLocaleString()}</p><hr/>
                      <table border="1" cellpadding="6" style="border-collapse:collapse;width:100%">
                        <thead><tr><th>Department</th><th>High</th><th>Medium</th><th>Low</th><th>Not Assessed</th></tr></thead>
                        <tbody>${Object.entries(depts).map(([d, v]) => `<tr><td>${d}</td><td>${v.HIGH}</td><td>${v.MEDIUM}</td><td>${v.LOW}</td><td>${v.NOT_ASSESSED}</td></tr>`).join('')}</tbody>
                      </table>`;
                  }
                },
                {
                  title: "Trend Forecast",
                  desc: "Current burnout trend and forecast for the team.",
                  content: () => `
                    <h2>Trend Forecast Report</h2>
                    <p>Generated: ${new Date().toLocaleString()}</p>
                    <hr/>
                    <p><b>Current High Risk Users:</b> ${overview?.high_risk ?? 0} (${overview?.total_users ? Math.round((overview.high_risk / overview.total_users) * 100) : 0}%)</p>
                    <p><b>Current Medium Risk Users:</b> ${overview?.medium_risk ?? 0}</p>
                    <p><b>Current Low Risk Users:</b> ${overview?.low_risk ?? 0}</p>
                    <p><b>Recommendation:</b> ${(overview?.high_risk ?? 0) > 0 ? 'Immediate intervention needed for high-risk employees. Schedule 1:1 meetings.' : 'Team wellness is stable. Maintain current workload policies.'}</p>
                    <hr/>
                    <h3>All Users Status</h3>
                    <table border="1" cellpadding="6" style="border-collapse:collapse;width:100%">
                      <thead><tr><th>Name</th><th>Email</th><th>Risk Level</th><th>Score</th></tr></thead>
                      <tbody>${(overview?.users || []).map(u => `<tr><td>${u.name}</td><td>${u.email}</td><td>${u.risk_level}</td><td>${u.risk_score ? u.risk_score.toFixed(1) + '%' : '-'}</td></tr>`).join('')}</tbody>
                    </table>
                  `
                },
              ].map((r, i) => (
                <div key={i} style={styles.wellCard}>
                  <h4 style={{ color: "#f3f4f6", marginBottom: 8 }}>{r.title}</h4>
                  <p style={{ color: "#9ca3af", fontSize: 13, marginBottom: 12 }}>{r.desc}</p>
                  <button style={styles.btnSm} onClick={() => {
                    const win = window.open('', '_blank');
                    win.document.write(`<html><head><title>${r.title}</title><style>body{font-family:Arial,sans-serif;padding:24px;color:#111}table{width:100%;border-collapse:collapse}th,td{border:1px solid #ccc;padding:8px;text-align:left}th{background:#f3f4f6}</style></head><body>${r.content()}</body></html>`);
                    win.document.close();
                    win.print();
                  }}>📄 Generate PDF</button>
                </div>
              ))}
            </div>
          </div>
        )}

        {view === "heatmap" && (
          <StressHeatmapCalendar isAdmin={true} />
        )}
      </main>
    </div>
  );
};

// ─── STYLES ───────────────────────────────────────────────────────────────────
const styles = {
  authWrap: { minHeight: "100vh", background: "radial-gradient(ellipse at top left, #0f172a 0%, #020617 62%)", display: "flex", alignItems: "center", justifyContent: "center", fontFamily: "'Segoe UI', sans-serif" },
  authCard: { background: "rgba(15,23,42,0.85)", backdropFilter: "blur(8px)", border: "1px solid #1e293b", borderRadius: 16, padding: 40, width: 380, boxShadow: "0 25px 60px rgba(2,6,23,0.75)", animation: "fadeUp 420ms ease-out" },
  logo: { fontSize: 48, marginBottom: 8 },
  authTitle: { color: "#f3f4f6", fontSize: 26, fontWeight: 800, margin: 0 },
  authSub: { color: "#6b7280", fontSize: 14, margin: "6px 0 0" },
  errBox: { background: "#3f0000", border: "1px solid #7f1d1d", color: "#f87171", padding: "10px 14px", borderRadius: 8, marginBottom: 16, fontSize: 13 },
  input: { width: "100%", background: "#1f2937", border: "1px solid #374151", color: "#f3f4f6", borderRadius: 8, padding: "12px 14px", marginBottom: 12, fontSize: 14, outline: "none", boxSizing: "border-box" },
  btn: { width: "100%", background: "linear-gradient(135deg, #06b6d4, #8b5cf6)", color: "#fff", border: "none", borderRadius: 8, padding: "13px", fontSize: 15, fontWeight: 700, cursor: "pointer", transition: "transform 180ms ease, box-shadow 180ms ease" },
  btnSm: { background: "#1f2937", border: "1px solid #374151", color: "#a78bfa", borderRadius: 6, padding: "6px 14px", fontSize: 13, cursor: "pointer", fontWeight: 600 },
  demoBox: { background: "#1a1033", border: "1px solid #312e81", borderRadius: 8, padding: "10px 14px", marginTop: 16, fontSize: 12, color: "#9ca3af" },
  dashWrap: { display: "flex", minHeight: "100vh", background: "linear-gradient(145deg,#020617,#0b1120 45%,#0f172a)", fontFamily: "'Segoe UI', sans-serif" },
  sidebar: { width: 230, background: "rgba(15,23,42,0.85)", backdropFilter: "blur(10px)", borderRight: "1px solid #1e293b", display: "flex", flexDirection: "column", padding: "24px 0" },
  sidelogo: { color: "#f3f4f6", fontWeight: 800, fontSize: 16, padding: "0 20px 20px", borderBottom: "1px solid #1f2937" },
  navItem: { display: "flex", alignItems: "center", gap: 12, padding: "11px 20px", color: "#94a3b8", cursor: "pointer", fontSize: 14, transition: "all 0.2s ease" },
  navItemActive: { color: "#67e8f9", background: "rgba(8,47,73,0.45)", borderRight: "2px solid #06b6d4" },
  sideUser: { padding: "16px 20px", display: "flex", alignItems: "center", gap: 10, borderTop: "1px solid #1f2937" },
  avatar: { width: 32, height: 32, borderRadius: "50%", background: "linear-gradient(135deg,#6366f1,#8b5cf6)", display: "flex", alignItems: "center", justifyContent: "center", color: "#fff", fontWeight: 800, fontSize: 13 },
  main: { flex: 1, padding: 32, overflowY: "auto" },
  pageTitle: { color: "#f3f4f6", fontSize: 24, fontWeight: 800, marginBottom: 6, marginTop: 0 },
  cardRow: { display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 16 },
  card: { background: "rgba(15,23,42,0.76)", border: "1px solid #1e293b", borderRadius: 12, padding: 24, boxShadow: "0 10px 28px rgba(2,6,23,0.45)" },
  statCard: { background: "rgba(15,23,42,0.8)", border: "1px solid #1e293b", borderRadius: 12, padding: 20, transition: "transform 180ms ease, box-shadow 180ms ease" },
  cardLabel: { color: "#6b7280", fontSize: 12, fontWeight: 600, letterSpacing: 0.5, textTransform: "uppercase", margin: "0 0 8px" },
  cardTitle: { color: "#f3f4f6", fontSize: 16, fontWeight: 700, margin: 0 },
  bigNum: { color: "#f3f4f6", fontSize: 36, fontWeight: 800, margin: "4px 0" },
  slider: { width: "100%", accentColor: "#6366f1", height: 4, cursor: "pointer" },
  recItem: { display: "flex", alignItems: "flex-start", gap: 12, padding: "12px 0", borderBottom: "1px solid #1f2937" },
  recBadge: { background: "#1a1033", color: "#a78bfa", border: "1px solid #3730a3", borderRadius: 4, padding: "2px 8px", fontSize: 10, fontWeight: 700, whiteSpace: "nowrap", marginTop: 2 },
  probBox: { textAlign: "center", background: "#1f2937", borderRadius: 8, padding: "12px 20px" },
  tipCard: { background: "#1f2937", borderRadius: 8, padding: "12px 16px", color: "#d1d5db", fontSize: 13 },
  wellCard: { background: "#111827", border: "1px solid #1f2937", borderRadius: 12, padding: 20 },
  emptyState: { background: "#111827", border: "1px solid #1f2937", borderRadius: 12, padding: 48, textAlign: "center", color: "#6b7280" },
  td: { padding: "12px 12px", color: "#d1d5db", fontSize: 14 },
  activeUserPill: { display: "flex", alignItems: "center", gap: 12, background: "linear-gradient(120deg, rgba(8,47,73,0.5), rgba(14,116,144,0.28))", border: "1px solid #155e75", borderRadius: 12, padding: "10px 14px", width: "fit-content", boxShadow: "0 8px 24px rgba(8,47,73,0.35)" },
  legendItem: { display: "flex", alignItems: "center", gap: 8 },
  legendDot: { width: 10, height: 10, borderRadius: "50%" },
};

// ─── ROOT APP ────────────────────────────────────────────────────────────────
export default function App() {
  const [authUser, setAuthUser] = useState(() => {
    try { return JSON.parse(localStorage.getItem("burnout_user")); } catch { return null; }
  });
  const [page, setPage] = useState("login");

  const login = (data) => {
    localStorage.setItem("token", data.token);
    localStorage.setItem("burnout_user", JSON.stringify(data));
    setAuthUser(data);
  };
  const logout = () => {
    localStorage.removeItem("token");
    localStorage.removeItem("burnout_user");
    setAuthUser(null);
  };

  if (!authUser) {
    return (
      <AuthContext.Provider value={{ login, logout, user: null }}>
        {page === "login" ? <LoginPage onSwitch={() => setPage("register")} /> : <RegisterPage onSwitch={() => setPage("login")} />}
      </AuthContext.Provider>
    );
  }

  return (
    <AuthContext.Provider value={{ user: authUser, login, logout }}>
      {authUser.role === "ADMIN" ? <AdminDashboard /> : <UserDashboard />}
    </AuthContext.Provider>
  );
}
