package com.burnout.controller;

import com.burnout.config.JwtUtil;
import com.burnout.model.User;
import com.burnout.repository.UserRepository;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.web.bind.annotation.*;

import java.util.List;
import java.util.Map;
import java.util.stream.Collectors;

@RestController
@RequestMapping("/api/auth")
public class AuthController {

    private final UserRepository userRepository;
    private final PasswordEncoder passwordEncoder;
    private final JwtUtil jwtUtil;

    public AuthController(UserRepository userRepository, PasswordEncoder passwordEncoder, JwtUtil jwtUtil) {
        this.userRepository = userRepository;
        this.passwordEncoder = passwordEncoder;
        this.jwtUtil = jwtUtil;
    }

    @PostMapping("/register")
    public ResponseEntity<?> register(@RequestBody Map<String, String> body) {
        String email = body.get("email");
        if (userRepository.existsByEmail(email)) {
            return ResponseEntity.badRequest().body(Map.of("error", "Email already registered"));
        }
        User user = User.builder()
                .name(body.getOrDefault("name", "User"))
                .email(email)
                .password(passwordEncoder.encode(body.get("password")))
                .department(body.getOrDefault("department", "General"))
                .role(User.Role.USER)
                .build();
        userRepository.save(user);
        String token = jwtUtil.generateToken(user.getEmail(), user.getRole().name());
        return ResponseEntity.ok(buildAuthResponse(user, token));
    }

    @PostMapping("/login")
    public ResponseEntity<?> login(@RequestBody Map<String, String> body) {
        return userRepository.findByEmail(body.get("email"))
                .filter(u -> passwordEncoder.matches(body.get("password"), u.getPassword()))
                .map(user -> {
                    String token = jwtUtil.generateToken(user.getEmail(), user.getRole().name());
                    return ResponseEntity.ok(buildAuthResponse(user, token));
                })
                .orElse(ResponseEntity.badRequest().body(Map.of("error", "Invalid credentials")));
    }

    @GetMapping("/me")
    public ResponseEntity<?> me() {
        String email = (String) SecurityContextHolder.getContext().getAuthentication().getPrincipal();
        return userRepository.findByEmail(email)
                .map(u -> ResponseEntity.ok(buildUserInfo(u)))
                .orElse(ResponseEntity.notFound().build());
    }

    @GetMapping("/users")
    public ResponseEntity<?> listUsers() {
        List<Map<String, Object>> users = userRepository.findAll().stream()
                .filter(u -> u.getRole() != User.Role.ADMIN)
                .map(u -> Map.<String, Object>of(
                        "id",         u.getId(),
                        "name",       u.getName(),
                        "email",      u.getEmail(),
                        "department", u.getDepartment() != null ? u.getDepartment() : "",
                        "role",       u.getRole().name()
                ))
                .collect(Collectors.toList());
        return ResponseEntity.ok(users);
    }

    private Map<String, Object> buildAuthResponse(User user, String token) {
        return Map.of(
                "token", token,
                "id", user.getId(),
                "name", user.getName(),
                "email", user.getEmail(),
                "role", user.getRole().name(),
                "department", user.getDepartment() != null ? user.getDepartment() : "");
    }

    private Map<String, Object> buildUserInfo(User user) {
        return Map.of(
                "id", user.getId(),
                "name", user.getName(),
                "email", user.getEmail(),
                "role", user.getRole().name(),
                "department", user.getDepartment() != null ? user.getDepartment() : "");
    }
}
