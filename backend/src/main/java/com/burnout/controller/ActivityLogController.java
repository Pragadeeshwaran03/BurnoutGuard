package com.burnout.controller;

import com.burnout.service.ActivityLogService;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.web.bind.annotation.*;

import java.util.Map;

@RestController
@RequestMapping("/api/activity")
public class ActivityLogController {

    private final ActivityLogService activityLogService;

    public ActivityLogController(ActivityLogService activityLogService) {
        this.activityLogService = activityLogService;
    }

    /**
     * POST /api/activity/log
     * Called by the browser tracker every 60 seconds.
     */
    @PostMapping("/log")
    public ResponseEntity<?> logActivity(@RequestBody Map<String, Object> body) {
        try {
            String email = (String) SecurityContextHolder.getContext()
                    .getAuthentication().getPrincipal();
            return ResponseEntity.ok(activityLogService.saveActivityLog(email, body));
        } catch (Exception e) {
            return ResponseEntity.badRequest().body(Map.of("error", e.getMessage()));
        }
    }

    /**
     * GET /api/activity/summary?hours=8
     * Returns aggregated metrics + ML-ready feature estimates for the past N hours.
     */
    @GetMapping("/summary")
    public ResponseEntity<?> getSummary(@RequestParam(defaultValue = "8") int hours) {
        try {
            String email = (String) SecurityContextHolder.getContext()
                    .getAuthentication().getPrincipal();
            return ResponseEntity.ok(activityLogService.getActivitySummary(email, hours));
        } catch (Exception e) {
            return ResponseEntity.badRequest().body(Map.of("error", e.getMessage()));
        }
    }

    /**
     * GET /api/activity/window-history/{userId}
     * Admin-only: returns the recent activeTab (window/app title) log for a specific user.
     */
    @GetMapping("/window-history/{userId}")
    public ResponseEntity<?> getWindowHistory(@PathVariable Long userId) {
        try {
            return ResponseEntity.ok(activityLogService.getWindowHistory(userId));
        } catch (Exception e) {
            return ResponseEntity.badRequest().body(Map.of("error", e.getMessage()));
        }
    }
}
