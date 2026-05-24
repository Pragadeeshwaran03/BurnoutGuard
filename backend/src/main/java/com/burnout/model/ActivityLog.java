package com.burnout.model;

import jakarta.persistence.*;
import java.time.LocalDateTime;

@Entity
@Table(name = "activity_logs")
public class ActivityLog {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @ManyToOne(fetch = FetchType.LAZY)
    @JoinColumn(name = "user_id", nullable = false)
    private User user;

    @Column(name = "total_active_time")
    private Long totalActiveTime;

    @Column(name = "total_idle_time")
    private Long totalIdleTime;

    @Column(name = "keyboard_activity_count")
    private Long keyboardActivityCount;

    @Column(name = "mouse_activity_count")
    private Long mouseActivityCount;

    @Column(name = "screen_time")
    private Long screenTime;

    @Column(name = "session_start")
    private LocalDateTime sessionStart;

    @Column(name = "session_end")
    private LocalDateTime sessionEnd;

    @Column(name = "logged_at")
    private LocalDateTime loggedAt;

    @Column(name = "active_tab", length = 512)
    private String activeTab;

    @PrePersist
    protected void onCreate() {
        loggedAt = LocalDateTime.now();
    }

    // ── Constructors ─────────────────────────────────────────────────────────

    public ActivityLog() {}

    // ── Getters & Setters ────────────────────────────────────────────────────

    public Long getId() { return id; }
    public void setId(Long id) { this.id = id; }

    public User getUser() { return user; }
    public void setUser(User user) { this.user = user; }

    public Long getTotalActiveTime() { return totalActiveTime; }
    public void setTotalActiveTime(Long totalActiveTime) { this.totalActiveTime = totalActiveTime; }

    public Long getTotalIdleTime() { return totalIdleTime; }
    public void setTotalIdleTime(Long totalIdleTime) { this.totalIdleTime = totalIdleTime; }

    public Long getKeyboardActivityCount() { return keyboardActivityCount; }
    public void setKeyboardActivityCount(Long keyboardActivityCount) { this.keyboardActivityCount = keyboardActivityCount; }

    public Long getMouseActivityCount() { return mouseActivityCount; }
    public void setMouseActivityCount(Long mouseActivityCount) { this.mouseActivityCount = mouseActivityCount; }

    public Long getScreenTime() { return screenTime; }
    public void setScreenTime(Long screenTime) { this.screenTime = screenTime; }

    public LocalDateTime getSessionStart() { return sessionStart; }
    public void setSessionStart(LocalDateTime sessionStart) { this.sessionStart = sessionStart; }

    public LocalDateTime getSessionEnd() { return sessionEnd; }
    public void setSessionEnd(LocalDateTime sessionEnd) { this.sessionEnd = sessionEnd; }

    public LocalDateTime getLoggedAt() { return loggedAt; }
    public void setLoggedAt(LocalDateTime loggedAt) { this.loggedAt = loggedAt; }

    public String getActiveTab() { return activeTab; }
    public void setActiveTab(String activeTab) { this.activeTab = activeTab; }

    // ── Builder ──────────────────────────────────────────────────────────────

    public static Builder builder() { return new Builder(); }

    public static class Builder {
        private User user;
        private Long totalActiveTime;
        private Long totalIdleTime;
        private Long keyboardActivityCount;
        private Long mouseActivityCount;
        private Long screenTime;
        private LocalDateTime sessionStart;
        private LocalDateTime sessionEnd;
        private String activeTab;

        public Builder user(User user) { this.user = user; return this; }
        public Builder totalActiveTime(Long v) { this.totalActiveTime = v; return this; }
        public Builder totalIdleTime(Long v) { this.totalIdleTime = v; return this; }
        public Builder keyboardActivityCount(Long v) { this.keyboardActivityCount = v; return this; }
        public Builder mouseActivityCount(Long v) { this.mouseActivityCount = v; return this; }
        public Builder screenTime(Long v) { this.screenTime = v; return this; }
        public Builder sessionStart(LocalDateTime v) { this.sessionStart = v; return this; }
        public Builder sessionEnd(LocalDateTime v) { this.sessionEnd = v; return this; }
        public Builder activeTab(String v) { this.activeTab = v; return this; }

        public ActivityLog build() {
            ActivityLog a = new ActivityLog();
            a.user = this.user;
            a.totalActiveTime = this.totalActiveTime;
            a.totalIdleTime = this.totalIdleTime;
            a.keyboardActivityCount = this.keyboardActivityCount;
            a.mouseActivityCount = this.mouseActivityCount;
            a.screenTime = this.screenTime;
            a.sessionStart = this.sessionStart;
            a.sessionEnd = this.sessionEnd;
            a.activeTab = this.activeTab;
            return a;
        }
    }
}
