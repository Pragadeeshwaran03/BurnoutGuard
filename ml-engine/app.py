"""
============================================================
AI-POWERED DIGITAL BURNOUT DETECTION SYSTEM
ML Engine - Python (Scikit-learn)
Author: PRAGADEESHWARAN K | Reg: 730924632031
v2.0 — Improved: fixed class imbalance bug, added /explain,
       /trend, wellness score, and input validation
============================================================
"""

from flask import Flask, request, jsonify
from flask_cors import CORS
import numpy as np
import pandas as pd
from sklearn.ensemble import GradientBoostingClassifier
from sklearn.preprocessing import StandardScaler
from sklearn.model_selection import train_test_split
from sklearn.metrics import classification_report, accuracy_score
import joblib
import os
import warnings
warnings.filterwarnings('ignore')

app = Flask(__name__)
CORS(app)

MODEL_PATH  = "burnout_model.pkl"
SCALER_PATH = "scaler.pkl"

FEATURE_ORDER = [
    'avg_daily_hours', 'break_frequency', 'task_completion_rate',
    'overtime_days', 'consecutive_work_days', 'late_night_sessions',
    'weekend_work_days', 'avg_session_length'
]

FEATURE_LABELS = {
    'avg_daily_hours':       'Daily work hours',
    'break_frequency':       'Break frequency',
    'task_completion_rate':  'Task completion rate',
    'overtime_days':         'Overtime days',
    'consecutive_work_days': 'Consecutive work days',
    'late_night_sessions':   'Late-night sessions',
    'weekend_work_days':     'Weekend work days',
    'avg_session_length':    'Avg session length',
}

# Thresholds that contribute to burnout (higher value = worse, except break_frequency & task_completion_rate)
FEATURE_RISK_DIRECTION = {
    'avg_daily_hours':       +1,   # higher = worse
    'break_frequency':       -1,   # lower = worse
    'task_completion_rate':  -1,   # lower = worse
    'overtime_days':         +1,
    'consecutive_work_days': +1,
    'late_night_sessions':   +1,
    'weekend_work_days':     +1,
    'avg_session_length':    +1,
}

# Healthy reference ranges for wellness scoring (min, max of healthy zone)
HEALTHY_RANGES = {
    'avg_daily_hours':       (4,  8),
    'break_frequency':       (3,  6),
    'task_completion_rate':  (0.75, 1.0),
    'overtime_days':         (0,  3),
    'consecutive_work_days': (1,  5),
    'late_night_sessions':   (0,  2),
    'weekend_work_days':     (0,  1),
    'avg_session_length':    (20, 60),
}


# ─────────────────────────────────────────────
# INPUT VALIDATION
# ─────────────────────────────────────────────
FEATURE_BOUNDS = {
    'avg_daily_hours':       (0,   24),
    'break_frequency':       (0,   20),
    'task_completion_rate':  (0.0, 1.0),
    'overtime_days':         (0,   31),
    'consecutive_work_days': (0,   31),
    'late_night_sessions':   (0,   31),
    'weekend_work_days':     (0,   8),
    'avg_session_length':    (0,   720),
}

def validate_features(data: dict):
    """Returns (clean_dict, error_string_or_None)."""
    errors = []
    cleaned = {}
    for feat in FEATURE_ORDER:
        if feat not in data:
            errors.append(f"Missing field: '{feat}'")
            continue
        try:
            val = float(data[feat])
        except (TypeError, ValueError):
            errors.append(f"'{feat}' must be a number, got: {data[feat]!r}")
            continue
        lo, hi = FEATURE_BOUNDS[feat]
        if not (lo <= val <= hi):
            errors.append(f"'{feat}' = {val} is out of range [{lo}, {hi}]")
        cleaned[feat] = val
    return cleaned, ("; ".join(errors) if errors else None)


# ─────────────────────────────────────────────
# TRAINING DATA GENERATION  (BUG FIX v2)
# ─────────────────────────────────────────────
def generate_training_data(n_samples=3000):
    """
    Generate synthetic behavioral data with correct, balanced class labels.

    BUG FIXED: The original code used nested np.random.rand() checks
    which made MEDIUM/HIGH class probabilities dependent on earlier draws,
    resulting in ~40% LOW / ~39% MEDIUM / ~21% HIGH — badly imbalanced.
    We now assign class labels explicitly via np.random.choice first.
    """
    np.random.seed(42)

    # Explicit balanced class distribution: 40% LOW, 35% MEDIUM, 25% HIGH
    labels = np.random.choice([0, 1, 2], size=n_samples, p=[0.40, 0.35, 0.25])

    rows = []
    for label in labels:
        if label == 0:  # LOW RISK
            row = [
                np.random.uniform(4, 7),        # avg_daily_hours
                np.random.uniform(3, 6),         # break_frequency
                np.random.uniform(0.75, 1.0),    # task_completion_rate
                np.random.randint(0, 4),         # overtime_days
                np.random.randint(1, 4),         # consecutive_work_days
                np.random.randint(0, 3),         # late_night_sessions
                np.random.randint(0, 2),         # weekend_work_days
                np.random.uniform(20, 60),       # avg_session_length
            ]
        elif label == 1:  # MEDIUM RISK
            row = [
                np.random.uniform(7, 10),
                np.random.uniform(1, 3),
                np.random.uniform(0.55, 0.80),
                np.random.randint(4, 10),
                np.random.randint(4, 7),
                np.random.randint(3, 8),
                np.random.randint(2, 4),
                np.random.uniform(60, 120),
            ]
        else:  # HIGH RISK
            row = [
                np.random.uniform(10, 16),
                np.random.uniform(0, 1),
                np.random.uniform(0.3, 0.60),
                np.random.randint(10, 22),
                np.random.randint(7, 14),
                np.random.randint(8, 20),
                np.random.randint(4, 8),
                np.random.uniform(120, 240),
            ]
        rows.append(row + [label])

    columns = FEATURE_ORDER + ['risk_level']
    return pd.DataFrame(rows, columns=columns)


# ─────────────────────────────────────────────
# WELLNESS SCORE  (NEW in v2)
# ─────────────────────────────────────────────
def compute_wellness_score(features: dict) -> float:
    """
    Compute a 0–100 wellness score (100 = fully healthy).
    Each feature is scored against its healthy range, then averaged.
    """
    scores = []
    for feat in FEATURE_ORDER:
        val = features[feat]
        lo, hi = HEALTHY_RANGES[feat]
        direction = FEATURE_RISK_DIRECTION[feat]

        if direction == +1:
            # Lower is better: score = 100 when val <= lo, 0 when val >= hi*1.5
            upper = hi * 1.5
            if val <= lo:
                s = 100.0
            elif val >= upper:
                s = 0.0
            else:
                s = 100.0 * (upper - val) / (upper - lo)
        else:
            # Higher is better: score = 100 when val >= hi, 0 when val <= 0
            if val >= hi:
                s = 100.0
            elif val <= 0:
                s = 0.0
            else:
                s = 100.0 * val / hi

        scores.append(max(0.0, min(100.0, s)))

    return round(float(np.mean(scores)), 1)


# ─────────────────────────────────────────────
# FEATURE IMPORTANCE EXPLANATION  (NEW in v2)
# ─────────────────────────────────────────────
def explain_prediction(features: dict, risk_level: int) -> list:
    """
    Return per-feature contribution to risk using a simple
    deviation-from-healthy scoring (no extra dependencies needed).
    Each item: { feature, label, contribution, direction, value }
    Sorted by absolute contribution descending.
    """
    contributions = []
    for feat in FEATURE_ORDER:
        val = features[feat]
        lo, hi = HEALTHY_RANGES[feat]
        direction = FEATURE_RISK_DIRECTION[feat]

        # How far outside the healthy range is this value?
        if direction == +1:
            deviation = max(0.0, val - hi) / max(hi, 1)
        else:
            deviation = max(0.0, lo - val) / max(lo, 1e-6)

        contributions.append({
            "feature":      feat,
            "label":        FEATURE_LABELS[feat],
            "value":        val,
            "contribution": round(float(deviation * 100), 1),
            "risk_impact":  "increases" if deviation > 0 else "within normal range",
        })

    contributions.sort(key=lambda x: x["contribution"], reverse=True)
    return contributions


# ─────────────────────────────────────────────
# MODEL TRAINING
# ─────────────────────────────────────────────
def train_model():
    print("Generating training data (v2 — balanced classes)...")
    df = generate_training_data(3000)

    X = df.drop('risk_level', axis=1)
    y = df['risk_level'].astype(int)

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=42, stratify=y
    )

    scaler = StandardScaler()
    X_train_scaled = scaler.fit_transform(X_train)
    X_test_scaled  = scaler.transform(X_test)

    model = GradientBoostingClassifier(
        n_estimators=200,
        max_depth=4,
        learning_rate=0.08,
        subsample=0.85,
        random_state=42
    )
    model.fit(X_train_scaled, y_train)

    y_pred = model.predict(X_test_scaled)
    acc = accuracy_score(y_test, y_pred)
    print(f"Model Accuracy: {acc * 100:.2f}%")
    print(classification_report(y_test, y_pred, target_names=['LOW', 'MEDIUM', 'HIGH']))

    joblib.dump(model, MODEL_PATH)
    joblib.dump(scaler, SCALER_PATH)
    print("Model and scaler saved.")
    return model, scaler


# ─────────────────────────────────────────────
# LOAD OR TRAIN
# ─────────────────────────────────────────────
if os.path.exists(MODEL_PATH) and os.path.exists(SCALER_PATH):
    print("Loading existing model...")
    model  = joblib.load(MODEL_PATH)
    scaler = joblib.load(SCALER_PATH)
else:
    model, scaler = train_model()

RISK_LABELS = {0: "LOW", 1: "MEDIUM", 2: "HIGH"}
RISK_COLORS = {0: "#22c55e", 1: "#f59e0b", 2: "#ef4444"}


# ─────────────────────────────────────────────
# RECOMMENDATION ENGINE
# ─────────────────────────────────────────────
def generate_recommendations(risk_level, features):
    avg_daily_hours = features['avg_daily_hours']
    late_night      = features['late_night_sessions']
    weekend_work    = features['weekend_work_days']
    session_length  = features['avg_session_length']

    if risk_level == 0:
        return [
            {"category": "WELLNESS",   "text": "Great balance! Keep maintaining your current work rhythm."},
            {"category": "BREAK",      "text": "Continue taking regular breaks every 90 minutes."},
            {"category": "LIFESTYLE",  "text": "Your work-life balance looks healthy. Keep it up!"},
        ]
    elif risk_level == 1:
        recs = [
            {"category": "BREAK",     "text": f"You're averaging {avg_daily_hours:.1f}h/day. Try to cap at 8 hours."},
            {"category": "WELLNESS",  "text": "Practice 5-minute breathing exercises between tasks."},
            {"category": "WORKLOAD",  "text": "Prioritize tasks using the Eisenhower Matrix to reduce overload."},
            {"category": "LIFESTYLE", "text": "Avoid screens at least 1 hour before bedtime."},
        ]
        if session_length > 90:
            recs.append({"category": "BREAK", "text": f"Your average session is {session_length:.0f} min. Use the Pomodoro technique (25 min work + 5 min break)."})
        return recs
    else:
        recs = [
            {"category": "WELLNESS",  "text": "High burnout risk detected. Consider speaking with HR or a counselor."},
            {"category": "BREAK",     "text": f"You're working {avg_daily_hours:.1f}h/day. Immediately reduce to under 9 hours."},
            {"category": "WORKLOAD",  "text": "Delegate tasks where possible. Discuss workload redistribution with your manager."},
            {"category": "LIFESTYLE", "text": "Schedule at least one full rest day this week with zero screen time."},
            {"category": "WELLNESS",  "text": "Try progressive muscle relaxation or guided meditation daily."},
        ]
        if late_night > 5:
            recs.append({"category": "LIFESTYLE", "text": f"You had {late_night} late-night sessions. Set a hard stop time of 9 PM."})
        if weekend_work > 3:
            recs.append({"category": "WORKLOAD",  "text": f"You worked {weekend_work} weekend days. Protect your weekends for full recovery."})
        return recs


# ─────────────────────────────────────────────
# SHARED PREDICTION HELPER
# ─────────────────────────────────────────────
def _run_prediction(features: dict) -> dict:
    features_array  = np.array([[features[f] for f in FEATURE_ORDER]])
    features_scaled = scaler.transform(features_array)
    prediction      = int(model.predict(features_scaled)[0])
    probabilities   = model.predict_proba(features_scaled)[0]

    return {
        "risk_level":  RISK_LABELS[prediction],
        "risk_score":  round(float(probabilities[prediction]) * 100, 2),
        "risk_color":  RISK_COLORS[prediction],
        "probabilities": {
            "LOW":    round(float(probabilities[0]) * 100, 2),
            "MEDIUM": round(float(probabilities[1]) * 100, 2),
            "HIGH":   round(float(probabilities[2]) * 100, 2),
        },
        "wellness_score":  compute_wellness_score(features),
        "recommendations": generate_recommendations(prediction, features),
        "_prediction_int": prediction,
    }


# ─────────────────────────────────────────────
# API ROUTES
# ─────────────────────────────────────────────
@app.route('/health', methods=['GET'])
def health():
    return jsonify({"status": "ML Engine running", "model": "GradientBoostingClassifier", "version": "2.0"})


@app.route('/predict', methods=['POST'])
def predict():
    """
    Predict burnout risk level with wellness score.
    All 8 feature fields are required and validated.
    """
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "Request body must be JSON"}), 400

    features, err = validate_features(data)
    if err:
        return jsonify({"error": err}), 400

    try:
        result = _run_prediction(features)
        result.pop("_prediction_int", None)
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/explain', methods=['POST'])
def explain():
    """
    NEW in v2: Return prediction + per-feature contribution breakdown.
    Tells the user WHICH features are driving their risk score.
    """
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "Request body must be JSON"}), 400

    features, err = validate_features(data)
    if err:
        return jsonify({"error": err}), 400

    try:
        result = _run_prediction(features)
        prediction_int = result.pop("_prediction_int")

        result["feature_contributions"] = explain_prediction(features, prediction_int)

        # Top driver: the single biggest contributor
        top = result["feature_contributions"][0]
        if top["contribution"] > 0:
            result["top_risk_driver"] = {
                "label":       top["label"],
                "value":       top["value"],
                "explanation": f"Your {top['label'].lower()} ({top['value']}) is outside the healthy range and is the biggest contributor to your burnout risk."
            }
        else:
            result["top_risk_driver"] = {
                "label":       "None",
                "value":       None,
                "explanation": "All your metrics are within healthy ranges."
            }

        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/trend', methods=['POST'])
def trend():
    """
    NEW in v2: Given a list of historical predictions (oldest first),
    return a trend direction and summary.

    Input: [ { ...features, "predicted_at": "ISO date" }, ... ]
    Output: { trend: "IMPROVING"|"WORSENING"|"STABLE", wellness_scores: [...], summary: "..." }
    """
    records = request.get_json(silent=True)
    if not records or not isinstance(records, list) or len(records) < 2:
        return jsonify({"error": "Provide at least 2 historical records as a JSON array"}), 400

    wellness_scores = []
    risk_ints       = []

    for rec in records:
        features, err = validate_features(rec)
        if err:
            return jsonify({"error": f"In record {records.index(rec)}: {err}"}), 400
        wellness_scores.append(compute_wellness_score(features))

        features_array  = np.array([[features[f] for f in FEATURE_ORDER]])
        features_scaled = scaler.transform(features_array)
        risk_ints.append(int(model.predict(features_scaled)[0]))

    # Trend: compare the average of the first half vs second half
    mid = len(wellness_scores) // 2
    first_half_avg  = float(np.mean(wellness_scores[:mid]))
    second_half_avg = float(np.mean(wellness_scores[mid:]))
    delta = second_half_avg - first_half_avg

    if delta >= 5:
        trend_dir = "IMPROVING"
        summary   = f"Your wellness score improved by {delta:.1f} points over the observed period. Keep going!"
    elif delta <= -5:
        trend_dir = "WORSENING"
        summary   = f"Your wellness score declined by {abs(delta):.1f} points. Consider reviewing your work habits."
    else:
        trend_dir = "STABLE"
        summary   = "Your wellness score has been relatively stable. Look for small wins to improve further."

    latest_risk_label = RISK_LABELS[risk_ints[-1]]

    return jsonify({
        "trend":          trend_dir,
        "delta":          round(delta, 1),
        "wellness_scores": [round(s, 1) for s in wellness_scores],
        "risk_levels":    [RISK_LABELS[r] for r in risk_ints],
        "current_risk":   latest_risk_label,
        "summary":        summary,
    })


@app.route('/batch-predict', methods=['POST'])
def batch_predict():
    """Batch predictions for admin dashboard (team analysis)."""
    users_data = request.get_json(silent=True)
    if not users_data or not isinstance(users_data, list):
        return jsonify({"error": "Expected a JSON array of user records"}), 400

    results = []
    for user in users_data:
        features, err = validate_features(user)
        if err:
            results.append({
                "user_id":   user.get("user_id"),
                "name":      user.get("name"),
                "error":     err,
            })
            continue

        try:
            pred = _run_prediction(features)
            pred.pop("_prediction_int", None)
            results.append({
                "user_id":       user.get("user_id"),
                "name":          user.get("name"),
                "risk_level":    pred["risk_level"],
                "risk_score":    pred["risk_score"],
                "wellness_score": pred["wellness_score"],
            })
        except Exception as e:
            results.append({"user_id": user.get("user_id"), "name": user.get("name"), "error": str(e)})

    valid_results = [r for r in results if "error" not in r]
    return jsonify({
        "total_users": len(results),
        "summary": {
            "HIGH":   sum(1 for r in valid_results if r['risk_level'] == 'HIGH'),
            "MEDIUM": sum(1 for r in valid_results if r['risk_level'] == 'MEDIUM'),
            "LOW":    sum(1 for r in valid_results if r['risk_level'] == 'LOW'),
        },
        "avg_wellness_score": round(float(np.mean([r['wellness_score'] for r in valid_results])), 1) if valid_results else 0,
        "results": results,
    })


@app.route('/retrain', methods=['POST'])
def retrain():
    """Retrain model with regenerated synthetic data."""
    global model, scaler
    model, scaler = train_model()
    return jsonify({"status": "Model retrained successfully (v2 balanced classes)"})


# ─────────────────────────────────────────────
# HEATMAP COLOR HELPER  (NEW)
# ─────────────────────────────────────────────
def wellness_to_hex(score: float) -> str:
    """
    Map a wellness score (0–100) to a hex color on a
    green → yellow → red gradient.
    100 = fully healthy (green #22c55e)
    50  = moderate      (yellow #f59e0b)
    0   = high stress   (red #ef4444)
    """
    score = max(0.0, min(100.0, float(score)))

    if score >= 50:
        # Green → Yellow  (score 100→50)
        t = (score - 50) / 50  # 1 at 100, 0 at 50
        r = int(245 + (34 - 245) * t)   # 245 → 34
        g = int(158 + (197 - 158) * t)  # 158 → 197
        b = int(11  + (94 - 11) * t)    # 11  → 94
    else:
        # Yellow → Red  (score 50→0)
        t = score / 50  # 1 at 50, 0 at 0
        r = int(239 + (245 - 239) * t)  # 239 → 245
        g = int(68  + (158 - 68) * t)   # 68  → 158
        b = int(68  + (11 - 68) * t)    # 68  → 11

    return f"#{r:02x}{g:02x}{b:02x}"


@app.route('/heatmap-colors', methods=['GET', 'POST'])
def heatmap_colors():
    """
    GET  /heatmap-colors?score=75    → single color
    POST /heatmap-colors  [50, 75, 90]  → batch colors
    """
    if request.method == 'GET':
        score_str = request.args.get('score')
        if score_str is None:
            return jsonify({"error": "Provide ?score=0..100"}), 400
        try:
            score = float(score_str)
        except ValueError:
            return jsonify({"error": "score must be a number"}), 400
        return jsonify({
            "score": score,
            "color": wellness_to_hex(score),
        })
    else:
        scores = request.get_json(silent=True)
        if not scores or not isinstance(scores, list):
            return jsonify({"error": "POST a JSON array of scores"}), 400
        results = []
        for s in scores:
            try:
                val = float(s)
                results.append({"score": val, "color": wellness_to_hex(val)})
            except (TypeError, ValueError):
                results.append({"score": s, "color": None, "error": "invalid"})
        return jsonify(results)


if __name__ == '__main__':
    print("Burnout Detection ML Engine v2.0 starting on port 5001...")
    app.run(host='0.0.0.0', port=5001, debug=False)