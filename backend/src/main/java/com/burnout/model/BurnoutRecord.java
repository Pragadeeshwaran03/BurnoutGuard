package com.burnout.model;

import jakarta.persistence.*;
import java.time.LocalDateTime;

/**
 * BurnoutRecord — v2.0
 * Added missing fields: lateNightSessions, weekendWorkDays, avgSessionLength, wellnessScore.
 * These were collected by the frontend but never persisted, making history views sparse.
 */
@Entity
@Table(name = "burnout_records")
public class BurnoutRecord {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @ManyToOne(fetch = FetchType.LAZY)
    @JoinColumn(name = "user_id", nullable = false)
    private User user;

    @Enumerated(EnumType.STRING)
    @Column(name = "risk_level", nullable = false)
    private RiskLevel riskLevel;

    @Column(name = "risk_score", nullable = false)
    private Float riskScore;

    // ── Behavioral metrics (all 8, previously only 5 were saved) ─────────────

    @Column(name = "avg_daily_hours")
    private Float avgDailyHours;

    @Column(name = "avg_break_frequency")
    private Float avgBreakFrequency;

    @Column(name = "task_completion_rate")
    private Float taskCompletionRate;

    @Column(name = "overtime_days")
    private Integer overtimeDays;

    @Column(name = "consecutive_work_days")
    private Integer consecutiveWorkDays;

    /** NEW: sessions after 10 PM in last 30 days */
    @Column(name = "late_night_sessions")
    private Integer lateNightSessions;

    /** NEW: weekend days worked in last 30 days */
    @Column(name = "weekend_work_days")
    private Integer weekendWorkDays;

    /** NEW: average uninterrupted session length in minutes */
    @Column(name = "avg_session_length")
    private Float avgSessionLength;

    /** NEW: composite 0–100 wellness score returned by /explain endpoint */
    @Column(name = "wellness_score")
    private Float wellnessScore;

    @Column(name = "predicted_at")
    private LocalDateTime predictedAt;

    @PrePersist
    protected void onCreate() {
        predictedAt = LocalDateTime.now();
    }

    public enum RiskLevel {
        LOW, MEDIUM, HIGH
    }

    // ── Constructors ──────────────────────────────────────────────────────────
    public BurnoutRecord() {}

    // ── Getters & Setters ─────────────────────────────────────────────────────
    public Long getId() { return id; }
    public void setId(Long id) { this.id = id; }

    public User getUser() { return user; }
    public void setUser(User user) { this.user = user; }

    public RiskLevel getRiskLevel() { return riskLevel; }
    public void setRiskLevel(RiskLevel riskLevel) { this.riskLevel = riskLevel; }

    public Float getRiskScore() { return riskScore; }
    public void setRiskScore(Float riskScore) { this.riskScore = riskScore; }

    public Float getAvgDailyHours() { return avgDailyHours; }
    public void setAvgDailyHours(Float avgDailyHours) { this.avgDailyHours = avgDailyHours; }

    public Float getAvgBreakFrequency() { return avgBreakFrequency; }
    public void setAvgBreakFrequency(Float avgBreakFrequency) { this.avgBreakFrequency = avgBreakFrequency; }

    public Float getTaskCompletionRate() { return taskCompletionRate; }
    public void setTaskCompletionRate(Float taskCompletionRate) { this.taskCompletionRate = taskCompletionRate; }

    public Integer getOvertimeDays() { return overtimeDays; }
    public void setOvertimeDays(Integer overtimeDays) { this.overtimeDays = overtimeDays; }

    public Integer getConsecutiveWorkDays() { return consecutiveWorkDays; }
    public void setConsecutiveWorkDays(Integer consecutiveWorkDays) { this.consecutiveWorkDays = consecutiveWorkDays; }

    public Integer getLateNightSessions() { return lateNightSessions; }
    public void setLateNightSessions(Integer lateNightSessions) { this.lateNightSessions = lateNightSessions; }

    public Integer getWeekendWorkDays() { return weekendWorkDays; }
    public void setWeekendWorkDays(Integer weekendWorkDays) { this.weekendWorkDays = weekendWorkDays; }

    public Float getAvgSessionLength() { return avgSessionLength; }
    public void setAvgSessionLength(Float avgSessionLength) { this.avgSessionLength = avgSessionLength; }

    public Float getWellnessScore() { return wellnessScore; }
    public void setWellnessScore(Float wellnessScore) { this.wellnessScore = wellnessScore; }

    public LocalDateTime getPredictedAt() { return predictedAt; }
    public void setPredictedAt(LocalDateTime predictedAt) { this.predictedAt = predictedAt; }

    // ── Builder ───────────────────────────────────────────────────────────────
    public static Builder builder() { return new Builder(); }

    public static class Builder {
        private User user;
        private RiskLevel riskLevel;
        private Float riskScore;
        private Float avgDailyHours;
        private Float avgBreakFrequency;
        private Float taskCompletionRate;
        private Integer overtimeDays;
        private Integer consecutiveWorkDays;
        private Integer lateNightSessions;
        private Integer weekendWorkDays;
        private Float avgSessionLength;
        private Float wellnessScore;

        public Builder user(User u)                        { this.user = u; return this; }
        public Builder riskLevel(RiskLevel rl)             { this.riskLevel = rl; return this; }
        public Builder riskScore(Float rs)                 { this.riskScore = rs; return this; }
        public Builder avgDailyHours(Float v)              { this.avgDailyHours = v; return this; }
        public Builder avgBreakFrequency(Float v)          { this.avgBreakFrequency = v; return this; }
        public Builder taskCompletionRate(Float v)         { this.taskCompletionRate = v; return this; }
        public Builder overtimeDays(Integer v)             { this.overtimeDays = v; return this; }
        public Builder consecutiveWorkDays(Integer v)      { this.consecutiveWorkDays = v; return this; }
        public Builder lateNightSessions(Integer v)        { this.lateNightSessions = v; return this; }
        public Builder weekendWorkDays(Integer v)          { this.weekendWorkDays = v; return this; }
        public Builder avgSessionLength(Float v)           { this.avgSessionLength = v; return this; }
        public Builder wellnessScore(Float v)              { this.wellnessScore = v; return this; }

        public BurnoutRecord build() {
            BurnoutRecord r = new BurnoutRecord();
            r.user = this.user;
            r.riskLevel = this.riskLevel;
            r.riskScore = this.riskScore;
            r.avgDailyHours = this.avgDailyHours;
            r.avgBreakFrequency = this.avgBreakFrequency;
            r.taskCompletionRate = this.taskCompletionRate;
            r.overtimeDays = this.overtimeDays;
            r.consecutiveWorkDays = this.consecutiveWorkDays;
            r.lateNightSessions = this.lateNightSessions;
            r.weekendWorkDays = this.weekendWorkDays;
            r.avgSessionLength = this.avgSessionLength;
            r.wellnessScore = this.wellnessScore;
            return r;
        }
    }
}