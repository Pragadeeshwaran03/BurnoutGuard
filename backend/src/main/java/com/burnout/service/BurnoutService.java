package com.burnout.service;

import com.burnout.model.ActivityLog;
import com.burnout.model.BurnoutRecord;
import com.burnout.model.User;
import com.burnout.repository.ActivityLogRepository;
import com.burnout.repository.BurnoutRecordRepository;
import com.burnout.repository.UserRepository;
import lombok.RequiredArgsConstructor;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.*;
import org.springframework.stereotype.Service;
import org.springframework.web.client.ResourceAccessException;
import org.springframework.web.client.RestTemplate;

import java.time.LocalDate;
import java.time.LocalDateTime;
import java.util.*;
import java.util.stream.Collectors;

/**
 * BurnoutService — v2.0
 *
 * Changes vs v1:
 *  - All 8 behavioral features + wellnessScore are now persisted (previously only 5)
 *  - ML engine downtime is handled gracefully with a clear error message
 *  - Added getTrendAnalysis() — calls /trend on ML engine with user's last N records
 *  - Added explainLatest()   — calls /explain on ML engine for top driver breakdown
 *  - getLatestRecord() now returns full feature set for a richer frontend history view
 */
@Service
@RequiredArgsConstructor
public class BurnoutService {

    private final BurnoutRecordRepository burnoutRecordRepository;
    private final UserRepository userRepository;
    private final ActivityLogRepository activityLogRepository;

    @Value("${ml.engine.url}")
    private String mlEngineUrl;

    private final RestTemplate restTemplate = new RestTemplate();

    // ── Predict & persist ─────────────────────────────────────────────────────

    public Map<String, Object> predictBurnout(String email, Map<String, Object> behaviorData) {
        User user = findUser(email);

        Map<String, Object> mlResult = callMlEngine("/predict", behaviorData);

        BurnoutRecord record = BurnoutRecord.builder()
                .user(user)
                .riskLevel(BurnoutRecord.RiskLevel.valueOf((String) mlResult.get("risk_level")))
                .riskScore(((Number) mlResult.get("risk_score")).floatValue())
                // All 8 features — v1 only saved 5
                .avgDailyHours(getFloat(behaviorData, "avg_daily_hours"))
                .avgBreakFrequency(getFloat(behaviorData, "break_frequency"))
                .taskCompletionRate(getFloat(behaviorData, "task_completion_rate"))
                .overtimeDays(getInt(behaviorData, "overtime_days"))
                .consecutiveWorkDays(getInt(behaviorData, "consecutive_work_days"))
                .lateNightSessions(getInt(behaviorData, "late_night_sessions"))       // NEW
                .weekendWorkDays(getInt(behaviorData, "weekend_work_days"))           // NEW
                .avgSessionLength(getFloat(behaviorData, "avg_session_length"))      // NEW
                .wellnessScore(getFloat(mlResult, "wellness_score"))                 // NEW
                .build();
        burnoutRecordRepository.save(record);

        mlResult.put("record_id", record.getId());
        return mlResult;
    }

    // ── Explain latest prediction ─────────────────────────────────────────────

    /**
     * NEW: Call /explain with the user's latest saved behavioral data.
     * Returns feature-level contribution breakdown from the ML engine.
     */
    public Map<String, Object> explainLatest(String email) {
        User user = findUser(email);
        Optional<BurnoutRecord> latestOpt = burnoutRecordRepository
                .findFirstByUserOrderByPredictedAtDesc(user);

        if (latestOpt.isEmpty()) {
            return Map.of("error", "No prediction history found. Please submit your work data first.");
        }

        BurnoutRecord r = latestOpt.get();
        Map<String, Object> payload = recordToFeatureMap(r);
        return callMlEngine("/explain", payload);
    }

    // ── Trend analysis ────────────────────────────────────────────────────────

    /**
     * NEW: Send the user's last N records to /trend and return
     * whether they are IMPROVING, WORSENING, or STABLE.
     */
    public Map<String, Object> getTrendAnalysis(String email, int limit) {
        User user = findUser(email);
        List<BurnoutRecord> history = burnoutRecordRepository
                .findByUserOrderByPredictedAtDesc(user);

        if (history.size() < 2) {
            return Map.of(
                "trend",   "INSUFFICIENT_DATA",
                "summary", "You need at least 2 assessments before trend analysis is available."
            );
        }

        // Send oldest-first (reverse the desc list), take up to `limit`
        List<BurnoutRecord> records = history.stream()
                .limit(limit)
                .collect(Collectors.toList());
        Collections.reverse(records);

        List<Map<String, Object>> payload = records.stream()
                .map(this::recordToFeatureMap)
                .collect(Collectors.toList());

        return callMlEngine("/trend", payload);
    }

    // ── History ───────────────────────────────────────────────────────────────

    public List<Map<String, Object>> getUserBurnoutHistory(String email) {
        User user = findUser(email);
        return burnoutRecordRepository.findByUserOrderByPredictedAtDesc(user)
                .stream()
                .map(this::recordToDetailMap)
                .collect(Collectors.toList());
    }

    // ── Latest record ─────────────────────────────────────────────────────────

    public Map<String, Object> getLatestRecord(String email) {
        User user = findUser(email);
        Optional<BurnoutRecord> latest = burnoutRecordRepository
                .findFirstByUserOrderByPredictedAtDesc(user);

        if (latest.isEmpty()) {
            return Map.of("message", "No records found. Please submit your work data.");
        }
        return recordToDetailMap(latest.get());
    }

    // ── Admin overview ────────────────────────────────────────────────────────

    public Map<String, Object> getAdminOverview() {
        List<User> regularUsers = userRepository.findAll().stream()
                .filter(u -> u.getRole() != User.Role.ADMIN)
                .collect(Collectors.toList());

        long totalUsers = regularUsers.size();
        long highRisk   = burnoutRecordRepository.countLatestByRiskLevel(BurnoutRecord.RiskLevel.HIGH);
        long mediumRisk = burnoutRecordRepository.countLatestByRiskLevel(BurnoutRecord.RiskLevel.MEDIUM);
        long lowRisk    = burnoutRecordRepository.countLatestByRiskLevel(BurnoutRecord.RiskLevel.LOW);

        LocalDateTime since24h = LocalDateTime.now().minusHours(24);

        List<Map<String, Object>> userSummaries = new ArrayList<>();
        for (User user : regularUsers) {
            Optional<BurnoutRecord> latestBurnout = burnoutRecordRepository
                    .findFirstByUserOrderByPredictedAtDesc(user);

            String activeTab = "—";
            Optional<ActivityLog> latestLog = activityLogRepository.findFirstByUserOrderByLoggedAtDesc(user);
            if (latestLog.isPresent() && latestLog.get().getActiveTab() != null) {
                activeTab = latestLog.get().getActiveTab();
            }

            long activeTimeSec  = activityLogRepository.sumActiveTimeSince(user, since24h);
            long idleTimeSec    = activityLogRepository.sumIdleTimeSince(user, since24h);
            long keyboardCount  = activityLogRepository.sumKeyboardCountSince(user, since24h);
            long mouseCount     = activityLogRepository.sumMouseCountSince(user, since24h);
            long screenTimeSec  = activityLogRepository.sumScreenTimeSince(user, since24h);
            long logCount       = activityLogRepository.countLogsSince(user, since24h);

            String lastSeen = activityLogRepository.findFirstByUserOrderByLoggedAtDesc(user)
                    .map(log -> log.getLoggedAt() != null ? log.getLoggedAt().toString() : null)
                    .orElse(null);

            Map<String, Object> summary = new HashMap<>();
            summary.put("id",              user.getId());
            summary.put("name",            user.getName());
            summary.put("email",           user.getEmail());
            summary.put("department",      user.getDepartment());
            summary.put("has_activity",    logCount > 0);
            summary.put("last_seen",       lastSeen);
            summary.put("active_tab",      activeTab);
            summary.put("active_time_sec", activeTimeSec);
            summary.put("idle_time_sec",   idleTimeSec);
            summary.put("keyboard_count",  keyboardCount);
            summary.put("mouse_count",     mouseCount);
            summary.put("screen_time_sec", screenTimeSec);

            if (latestBurnout.isPresent()) {
                BurnoutRecord br = latestBurnout.get();
                summary.put("risk_level",    br.getRiskLevel().name());
                summary.put("risk_score",    br.getRiskScore());
                summary.put("wellness_score", br.getWellnessScore() != null ? br.getWellnessScore() : 0);
            } else {
                summary.put("risk_level",    "NOT_ASSESSED");
                summary.put("risk_score",    0);
                summary.put("wellness_score", 0);
            }
            userSummaries.add(summary);
        }

        return Map.of(
                "total_users",  totalUsers,
                "high_risk",    highRisk,
                "medium_risk",  mediumRisk,
                "low_risk",     lowRisk,
                "users",        userSummaries
        );
    }

    // ── Heatmap data ──────────────────────────────────────────────────────────

    /**
     * Returns daily heatmap entries for the logged-in user for a given year.
     * Each entry: { date, wellness_score, risk_level, risk_score, ... metrics }
     * Multiple predictions on the same day are averaged.
     */
    public List<Map<String, Object>> getHeatmapData(String email, int year) {
        User user = findUser(email);
        LocalDateTime start = LocalDate.of(year, 1, 1).atStartOfDay();
        LocalDateTime end   = LocalDate.of(year, 12, 31).atTime(23, 59, 59);

        List<BurnoutRecord> records = burnoutRecordRepository
                .findByUserAndPredictedAtBetween(user, start, end);

        return aggregateByDay(records);
    }

    /**
     * Admin heatmap: if userId is null → team-average per day.
     * If userId is provided → that specific user's daily data.
     */
    public Map<String, Object> getAdminHeatmapData(Long userId, int year) {
        LocalDateTime start = LocalDate.of(year, 1, 1).atStartOfDay();
        LocalDateTime end   = LocalDate.of(year, 12, 31).atTime(23, 59, 59);

        List<BurnoutRecord> records;
        if (userId != null) {
            records = burnoutRecordRepository
                    .findByUserIdAndPredictedAtBetween(userId, start, end);
        } else {
            records = burnoutRecordRepository
                    .findByPredictedAtBetween(start, end);
        }

        List<Map<String, Object>> days = aggregateByDay(records);

        // Build user list for the dropdown
        List<Map<String, Object>> userList = userRepository.findAll().stream()
                .filter(u -> u.getRole() != User.Role.ADMIN)
                .map(u -> {
                    Map<String, Object> m = new HashMap<>();
                    m.put("id", u.getId());
                    m.put("name", u.getName());
                    m.put("email", u.getEmail());
                    return m;
                })
                .collect(Collectors.toList());

        Map<String, Object> result = new HashMap<>();
        result.put("days", days);
        result.put("users", userList);
        result.put("year", year);
        result.put("mode", userId != null ? "individual" : "team");
        return result;
    }

    /** Group records by date (LocalDate) and average their scores per day. */
    private List<Map<String, Object>> aggregateByDay(List<BurnoutRecord> records) {
        // Group by date
        Map<LocalDate, List<BurnoutRecord>> byDay = records.stream()
                .filter(r -> r.getPredictedAt() != null)
                .collect(Collectors.groupingBy(
                        r -> r.getPredictedAt().toLocalDate()));

        List<Map<String, Object>> days = new ArrayList<>();
        for (Map.Entry<LocalDate, List<BurnoutRecord>> entry : byDay.entrySet()) {
            List<BurnoutRecord> dayRecords = entry.getValue();
            double avgWellness = dayRecords.stream()
                    .mapToDouble(r -> r.getWellnessScore() != null ? r.getWellnessScore() : 0)
                    .average().orElse(0);
            double avgRiskScore = dayRecords.stream()
                    .mapToDouble(r -> r.getRiskScore() != null ? r.getRiskScore() : 0)
                    .average().orElse(0);
            double avgHours = dayRecords.stream()
                    .mapToDouble(r -> r.getAvgDailyHours() != null ? r.getAvgDailyHours() : 0)
                    .average().orElse(0);

            // Determine dominant risk level from the latest record of the day
            BurnoutRecord latest = dayRecords.stream()
                    .max(Comparator.comparing(BurnoutRecord::getPredictedAt))
                    .orElse(dayRecords.get(0));

            Map<String, Object> day = new HashMap<>();
            day.put("date", entry.getKey().toString());
            day.put("wellness_score", Math.round(avgWellness * 10.0) / 10.0);
            day.put("risk_level", latest.getRiskLevel().name());
            day.put("risk_score", Math.round(avgRiskScore * 10.0) / 10.0);
            day.put("avg_daily_hours", Math.round(avgHours * 10.0) / 10.0);
            day.put("predictions_count", dayRecords.size());
            days.add(day);
        }

        // Sort by date
        days.sort(Comparator.comparing(m -> (String) m.get("date")));
        return days;
    }

    // ── Private helpers ───────────────────────────────────────────────────────

    private User findUser(String email) {
        return userRepository.findByEmail(email)
                .orElseThrow(() -> new RuntimeException("User not found: " + email));
    }

    /**
     * POST to an ML engine endpoint. Throws a descriptive RuntimeException
     * instead of a raw ResourceAccessException so callers get a clean message.
     */
    @SuppressWarnings("unchecked")
    private Map<String, Object> callMlEngine(String path, Object body) {
        HttpHeaders headers = new HttpHeaders();
        headers.setContentType(MediaType.APPLICATION_JSON);
        HttpEntity<Object> entity = new HttpEntity<>(body, headers);
        try {
            ResponseEntity<Map> response = restTemplate.postForEntity(
                    mlEngineUrl + path, entity, Map.class);
            return response.getBody();
        } catch (ResourceAccessException e) {
            throw new RuntimeException(
                "ML Engine is unavailable. Please ensure it is running on " + mlEngineUrl + ".");
        }
    }

    /** Convert a BurnoutRecord to the full detail map returned by the API. */
    private Map<String, Object> recordToDetailMap(BurnoutRecord r) {
        Map<String, Object> m = new HashMap<>();
        m.put("id",                    r.getId());
        m.put("risk_level",            r.getRiskLevel().name());
        m.put("risk_score",            r.getRiskScore());
        m.put("wellness_score",        r.getWellnessScore() != null ? r.getWellnessScore() : 0);
        m.put("avg_daily_hours",       orZero(r.getAvgDailyHours()));
        m.put("break_frequency",       orZero(r.getAvgBreakFrequency()));
        m.put("task_completion_rate",  orZero(r.getTaskCompletionRate()));
        m.put("overtime_days",         r.getOvertimeDays() != null ? r.getOvertimeDays() : 0);
        m.put("consecutive_work_days", r.getConsecutiveWorkDays() != null ? r.getConsecutiveWorkDays() : 0);
        m.put("late_night_sessions",   r.getLateNightSessions() != null ? r.getLateNightSessions() : 0);
        m.put("weekend_work_days",     r.getWeekendWorkDays() != null ? r.getWeekendWorkDays() : 0);
        m.put("avg_session_length",    orZero(r.getAvgSessionLength()));
        m.put("predicted_at",          r.getPredictedAt() != null ? r.getPredictedAt().toString() : null);
        return m;
    }

    /** Convert a BurnoutRecord to a feature payload map suitable for ML engine calls. */
    private Map<String, Object> recordToFeatureMap(BurnoutRecord r) {
        Map<String, Object> m = new HashMap<>();
        m.put("avg_daily_hours",       orZero(r.getAvgDailyHours()));
        m.put("break_frequency",       orZero(r.getAvgBreakFrequency()));
        m.put("task_completion_rate",  orZero(r.getTaskCompletionRate()));
        m.put("overtime_days",         r.getOvertimeDays() != null ? r.getOvertimeDays() : 0);
        m.put("consecutive_work_days", r.getConsecutiveWorkDays() != null ? r.getConsecutiveWorkDays() : 0);
        m.put("late_night_sessions",   r.getLateNightSessions() != null ? r.getLateNightSessions() : 0);
        m.put("weekend_work_days",     r.getWeekendWorkDays() != null ? r.getWeekendWorkDays() : 0);
        m.put("avg_session_length",    orZero(r.getAvgSessionLength()));
        return m;
    }

    private float orZero(Float v) { return v != null ? v : 0f; }

    private Float getFloat(Map<String, Object> data, String key) {
        Object val = data.get(key);
        if (val == null) return 0f;
        return ((Number) val).floatValue();
    }

    private Integer getInt(Map<String, Object> data, String key) {
        Object val = data.get(key);
        if (val == null) return 0;
        return ((Number) val).intValue();
    }
}