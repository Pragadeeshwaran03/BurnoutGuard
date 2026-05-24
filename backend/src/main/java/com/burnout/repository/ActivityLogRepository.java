package com.burnout.repository;

import com.burnout.model.ActivityLog;
import com.burnout.model.User;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;
import org.springframework.stereotype.Repository;

import java.time.LocalDateTime;
import java.util.List;
import java.util.Optional;

@Repository
public interface ActivityLogRepository extends JpaRepository<ActivityLog, Long> {

    List<ActivityLog> findByUserOrderByLoggedAtDesc(User user);

    List<ActivityLog> findByUserAndLoggedAtAfterOrderByLoggedAtDesc(User user, LocalDateTime since);

    Optional<ActivityLog> findFirstByUserOrderByLoggedAtDesc(User user);

    @Query("SELECT COALESCE(SUM(a.totalActiveTime), 0) FROM ActivityLog a WHERE a.user = :user AND a.loggedAt >= :since")
    Long sumActiveTimeSince(@Param("user") User user, @Param("since") LocalDateTime since);

    @Query("SELECT COALESCE(SUM(a.totalIdleTime), 0) FROM ActivityLog a WHERE a.user = :user AND a.loggedAt >= :since")
    Long sumIdleTimeSince(@Param("user") User user, @Param("since") LocalDateTime since);

    @Query("SELECT COALESCE(SUM(a.keyboardActivityCount), 0) FROM ActivityLog a WHERE a.user = :user AND a.loggedAt >= :since")
    Long sumKeyboardCountSince(@Param("user") User user, @Param("since") LocalDateTime since);

    @Query("SELECT COALESCE(SUM(a.mouseActivityCount), 0) FROM ActivityLog a WHERE a.user = :user AND a.loggedAt >= :since")
    Long sumMouseCountSince(@Param("user") User user, @Param("since") LocalDateTime since);

    @Query("SELECT COALESCE(SUM(a.screenTime), 0) FROM ActivityLog a WHERE a.user = :user AND a.loggedAt >= :since")
    Long sumScreenTimeSince(@Param("user") User user, @Param("since") LocalDateTime since);

    @Query("SELECT COUNT(a) FROM ActivityLog a WHERE a.user = :user AND a.loggedAt >= :since")
    Long countLogsSince(@Param("user") User user, @Param("since") LocalDateTime since);
}

