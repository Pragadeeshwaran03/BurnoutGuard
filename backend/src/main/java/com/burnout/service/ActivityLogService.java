package com.burnout.service;

import com.burnout.model.ActivityLog;
import com.burnout.model.User;
import com.burnout.repository.ActivityLogRepository;
import com.burnout.repository.UserRepository;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;

import java.time.LocalDateTime;
import java.time.format.DateTimeFormatter;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

@Service
@RequiredArgsConstructor
public class ActivityLogService {

    private final ActivityLogRepository activityLogRepository;
    private final UserRepository userRepository;

    /**
     * Saves one activity snapshot sent from the browser every 60 seconds.
     */
    public Map<String, Object> saveActivityLog(String email, Map<String, Object> body) {
        User user = userRepository.findByEmail(email)
                .orElseThrow(() -> new RuntimeException("User not found"));

        ActivityLog log = ActivityLog.builder()
                .user(user)
                .activeTab(getString(body, "activeTab"))
                .totalActiveTime(getLong(body, "totalActiveTime"))
                .totalIdleTime(getLong(body, "totalIdleTime"))
                .keyboardActivityCount(getLong(body, "keyboardActivityCount"))
                .mouseActivityCount(getLong(body, "mouseActivityCount"))
                .screenTime(getLong(body, "screenTime"))
                .sessionStart(parseDateTime(body, "sessionStart"))
                .sessionEnd(parseDateTime(body, "sessionEnd"))
                .build();

        activityLogRepository.save(log);
        return Map.of("status", "saved", "id", log.getId());
    }

    /**
     * Returns aggregated activity metrics for the past N hours.
     * Used to auto-populate the burnout assessment sliders.
     */
    public Map<String, Object> getActivitySummary(String email, int hours) {
        User user = userRepository.findByEmail(email)
                .orElseThrow(() -> new RuntimeException("User not found"));

        LocalDateTime since = LocalDateTime.now().minusHours(hours);

        long activeTimeSec  = activityLogRepository.sumActiveTimeSince(user, since);
        long idleTimeSec    = activityLogRepository.sumIdleTimeSince(user, since);
        long keyboardCount  = activityLogRepository.sumKeyboardCountSince(user, since);
        long mouseCount     = activityLogRepository.sumMouseCountSince(user, since);
        long screenTimeSec  = activityLogRepository.sumScreenTimeSince(user, since);

        // Derived metrics that map to the ML model's expected input features
        double totalHours       = (activeTimeSec + idleTimeSec) / 3600.0;
        double activeHours      = activeTimeSec / 3600.0;
        double idleHours        = idleTimeSec  / 3600.0;
        double screenTimeHours  = screenTimeSec / 3600.0;

        // Estimate break frequency: every long idle period (>2 min) counts as a break
        // We approximate: 1 break per 20 minutes of idle time
        double breakFrequency = idleHours > 0 ? Math.round(idleHours * 3) : 0;

        // Task completion rate: ratio of active to total time (bounded 0–1)
        double taskCompletionRate = (totalHours > 0)
                ? Math.min(1.0, activeHours / totalHours)
                : 0.75;

        // Avg session length in minutes (active time divided by estimated sessions)
        double estimatedSessions = Math.max(1, breakFrequency);
        double avgSessionLength  = activeHours > 0
                ? (activeHours * 60) / estimatedSessions
                : 90;

        Map<String, Object> summary = new HashMap<>();
        summary.put("totalActiveTimeSec",     activeTimeSec);
        summary.put("totalIdleTimeSec",       idleTimeSec);
        summary.put("keyboardActivityCount",  keyboardCount);
        summary.put("mouseActivityCount",     mouseCount);
        summary.put("screenTimeSec",          screenTimeSec);
        summary.put("screenTimeHours",        Math.round(screenTimeHours * 10.0) / 10.0);
        summary.put("activeHours",            Math.round(activeHours   * 10.0) / 10.0);
        summary.put("idleHours",              Math.round(idleHours     * 10.0) / 10.0);

        // ML-ready feature estimates
        summary.put("avg_daily_hours",        Math.min(18, Math.round(activeHours * 10.0) / 10.0));
        summary.put("break_frequency",        breakFrequency);
        summary.put("task_completion_rate",   Math.round(taskCompletionRate * 100.0) / 100.0);
        summary.put("avg_session_length",     Math.round(avgSessionLength));
        summary.put("hoursAnalyzed",          hours);
        return summary;
    }

    /**
     * Returns window/app history for a specific user (admin view).
     * Pulls last 50 activity logs and extracts the activeTab field.
     */
    public Map<String, Object> getWindowHistory(Long userId) {
        User user = userRepository.findById(userId)
                .orElseThrow(() -> new RuntimeException("User not found: " + userId));

        List<ActivityLog> logs = activityLogRepository.findByUserOrderByLoggedAtDesc(user);
        DateTimeFormatter fmt = DateTimeFormatter.ofPattern("HH:mm:ss");

        List<Map<String, Object>> history = new ArrayList<>();
        String prevTab = null;
        for (ActivityLog log : logs) {
            String tab = log.getActiveTab();
            if (tab == null || tab.isBlank() || tab.equals(prevTab)) continue;
            prevTab = tab;
            Map<String, Object> entry = new HashMap<>();
            entry.put("title", tab);
            entry.put("ts", log.getLoggedAt() != null ? log.getLoggedAt().format(fmt) : "");
            history.add(entry);
            if (history.size() >= 50) break;
        }

        Map<String, Object> result = new HashMap<>();
        result.put("userId", userId);
        result.put("userName", user.getName());
        result.put("history", history);
        return result;
    }

    // ── Helpers ───────────────────────────────────────────────────────────────

    private String getString(Map<String, Object> data, String key) {
        Object val = data.get(key);
        return val != null ? val.toString() : null;
    }

    private Long getLong(Map<String, Object> data, String key) {
        Object val = data.get(key);
        if (val == null) return 0L;
        return ((Number) val).longValue();
    }

    private LocalDateTime parseDateTime(Map<String, Object> data, String key) {
        Object val = data.get(key);
        if (val == null) return null;
        try {
            return LocalDateTime.parse(val.toString().replace("Z", "")
                    .replace("T", "T").split("\\.")[0]);
        } catch (Exception e) {
            return LocalDateTime.now();
        }
    }
}
