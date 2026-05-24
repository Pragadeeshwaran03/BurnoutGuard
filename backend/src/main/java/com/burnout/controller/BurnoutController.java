package com.burnout.controller;

import com.burnout.service.BurnoutService;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.web.bind.annotation.*;

import java.util.List;
import java.util.Map;

/**
 * BurnoutController — v2.0
 *
 * New endpoints:
 *   GET  /api/burnout/explain  — Feature-level breakdown of the latest prediction
 *   GET  /api/burnout/trend    — IMPROVING / WORSENING / STABLE analysis over history
 *   GET  /api/burnout/heatmap  — Daily wellness score data for calendar heatmap
 *   GET  /api/burnout/admin/heatmap — Admin heatmap (team or individual)
 */
@RestController
@RequestMapping("/api/burnout")
public class BurnoutController {

    private final BurnoutService burnoutService;

    public BurnoutController(BurnoutService burnoutService) {
        this.burnoutService = burnoutService;
    }

    @PostMapping("/predict")
    public ResponseEntity<?> predict(@RequestBody Map<String, Object> body) {
        try {
            String email = currentUserEmail();
            return ResponseEntity.ok(burnoutService.predictBurnout(email, body));
        } catch (Exception e) {
            return ResponseEntity.badRequest().body(Map.of("error", e.getMessage()));
        }
    }

    @GetMapping("/history")
    public ResponseEntity<?> history() {
        try {
            return ResponseEntity.ok(burnoutService.getUserBurnoutHistory(currentUserEmail()));
        } catch (Exception e) {
            return ResponseEntity.badRequest().body(Map.of("error", e.getMessage()));
        }
    }

    @GetMapping("/latest")
    public ResponseEntity<?> latest() {
        try {
            return ResponseEntity.ok(burnoutService.getLatestRecord(currentUserEmail()));
        } catch (Exception e) {
            return ResponseEntity.badRequest().body(Map.of("error", e.getMessage()));
        }
    }

    /**
     * NEW: Returns feature-level contribution breakdown for the user's
     * latest prediction so they can see WHICH habit is driving their risk.
     */
    @GetMapping("/explain")
    public ResponseEntity<?> explain() {
        try {
            return ResponseEntity.ok(burnoutService.explainLatest(currentUserEmail()));
        } catch (Exception e) {
            return ResponseEntity.badRequest().body(Map.of("error", e.getMessage()));
        }
    }

    /**
     * NEW: Returns trend direction (IMPROVING / WORSENING / STABLE)
     * based on the user's last N assessments.
     *
     * @param limit how many past records to consider (default 5, max 20)
     */
    @GetMapping("/trend")
    public ResponseEntity<?> trend(@RequestParam(defaultValue = "5") int limit) {
        try {
            int safeLimit = Math.min(Math.max(limit, 2), 20);
            return ResponseEntity.ok(burnoutService.getTrendAnalysis(currentUserEmail(), safeLimit));
        } catch (Exception e) {
            return ResponseEntity.badRequest().body(Map.of("error", e.getMessage()));
        }
    }

    /**
     * Heatmap data for the logged-in user.
     * Returns daily aggregated wellness scores for a given year.
     */
    @GetMapping("/heatmap")
    public ResponseEntity<?> heatmap(@RequestParam(defaultValue = "2026") int year) {
        try {
            List<Map<String, Object>> data = burnoutService.getHeatmapData(currentUserEmail(), year);
            return ResponseEntity.ok(Map.of("days", data, "year", year));
        } catch (Exception e) {
            return ResponseEntity.badRequest().body(Map.of("error", e.getMessage()));
        }
    }

    @GetMapping("/admin/overview")
    public ResponseEntity<?> adminOverview() {
        try {
            return ResponseEntity.ok(burnoutService.getAdminOverview());
        } catch (Exception e) {
            return ResponseEntity.internalServerError().body(Map.of("error", e.getMessage()));
        }
    }

    /**
     * Admin heatmap: team-wide average or individual user.
     * If userId is omitted → team average. If provided → that user's data.
     */
    @GetMapping("/admin/heatmap")
    public ResponseEntity<?> adminHeatmap(
            @RequestParam(required = false) Long userId,
            @RequestParam(defaultValue = "2026") int year) {
        try {
            return ResponseEntity.ok(burnoutService.getAdminHeatmapData(userId, year));
        } catch (Exception e) {
            return ResponseEntity.badRequest().body(Map.of("error", e.getMessage()));
        }
    }

    private String currentUserEmail() {
        return (String) SecurityContextHolder.getContext().getAuthentication().getPrincipal();
    }
}