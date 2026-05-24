package com.burnout.repository;

import com.burnout.model.BurnoutRecord;
import com.burnout.model.User;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

import java.util.List;
import java.util.Optional;
import java.time.LocalDateTime;

public interface BurnoutRecordRepository extends JpaRepository<BurnoutRecord, Long> {

    List<BurnoutRecord> findByUserOrderByPredictedAtDesc(User user);

    Optional<BurnoutRecord> findFirstByUserOrderByPredictedAtDesc(User user);

    @Query("SELECT COUNT(DISTINCT r.user) FROM BurnoutRecord r " +
            "WHERE r.riskLevel = :level AND r.predictedAt = " +
            "(SELECT MAX(r2.predictedAt) FROM BurnoutRecord r2 WHERE r2.user = r.user)")
    long countLatestByRiskLevel(@Param("level") BurnoutRecord.RiskLevel level);

    // ── Heatmap queries ──────────────────────────────────────────────────────

    /** All records for a specific user within a date range (for user heatmap). */
    List<BurnoutRecord> findByUserAndPredictedAtBetween(User user,
            LocalDateTime start, LocalDateTime end);

    /** All records across all users within a date range (for admin team heatmap). */
    List<BurnoutRecord> findByPredictedAtBetween(LocalDateTime start,
            LocalDateTime end);

    /** All records for a specific user ID within a date range (for admin single-user heatmap). */
    @Query("SELECT r FROM BurnoutRecord r WHERE r.user.id = :userId " +
            "AND r.predictedAt BETWEEN :start AND :end")
    List<BurnoutRecord> findByUserIdAndPredictedAtBetween(
            @Param("userId") Long userId,
            @Param("start") LocalDateTime start,
            @Param("end") LocalDateTime end);
}
