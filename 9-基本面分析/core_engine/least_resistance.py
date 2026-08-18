import json
import os
import math
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STORAGE_DIR = os.path.join(BASE_DIR, "storage")
TIMESERIES_FILE = os.path.join(STORAGE_DIR, "module_timeseries.json")
MAX_ENTRIES = 100


def _ensure_storage():
    if not os.path.exists(STORAGE_DIR):
        os.makedirs(STORAGE_DIR, exist_ok=True)


def _load_timeseries_all():
    _ensure_storage()
    if not os.path.exists(TIMESERIES_FILE):
        return {}
    try:
        with open(TIMESERIES_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_timeseries_all(data):
    _ensure_storage()
    with open(TIMESERIES_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def compute_resistance_3d(raw_score: float, historical_scores=None) -> dict:
    historical_scores = historical_scores or []
    if raw_score > 0.3:
        direction = "up"
    elif raw_score < -0.3:
        direction = "down"
    else:
        direction = "neutral"
    direction_score = raw_score
    if historical_scores:
        mean_hist = sum(historical_scores) / len(historical_scores)
        velocity = math.tanh((raw_score - mean_hist) / 0.3)
    else:
        velocity = 0.0
    if len(historical_scores) >= 2:
        hist_velocities = []
        for i in range(1, len(historical_scores)):
            prev_slice = historical_scores[:i]
            mean_prev = sum(prev_slice) / len(prev_slice)
            v_i = math.tanh((historical_scores[i] - mean_prev) / 0.3)
            hist_velocities.append(v_i)
        if hist_velocities:
            mean_hv = sum(hist_velocities) / len(hist_velocities)
            acceleration = math.tanh((velocity - mean_hv) / 0.2)
        else:
            acceleration = 0.0
    else:
        acceleration = 0.0
    confidence = min(1.0, 0.3 + abs(raw_score) * 0.5 + 0.2 * (1 if historical_scores else 0))
    data_points = len(historical_scores) + 1
    return {
        "direction": direction,
        "direction_score": direction_score,
        "velocity": velocity,
        "acceleration": acceleration,
        "data_points": data_points,
        "confidence": confidence,
    }


def generate_signal(r3d: dict, sentiment_index: float, flow_idx: float, heat: float, stress: str) -> dict:
    signals = []
    direction = r3d.get("direction", "neutral")
    velocity = r3d.get("velocity", 0.0)
    score = r3d.get("direction_score", 0.0)
    strength_base = min(1.0, 0.5 + abs(score) * 0.5)
    strength_soft = min(1.0, 0.3 + abs(score) * 0.4)
    if direction == "up":
        if velocity > 0.1 and (sentiment_index > 55 or flow_idx > 55):
            signals.append({
                "type": "strong_buy",
                "strength": strength_base,
                "reason": "方向向上且速度积极，市场或资金情绪偏强",
                "horizon": "medium",
            })
        if sentiment_index > 52:
            signals.append({
                "type": "buy",
                "strength": strength_soft,
                "reason": "方向向上，市场情绪温和偏多",
                "horizon": "short",
            })
    if direction == "down":
        if velocity < -0.1 and (sentiment_index < 45 or flow_idx < 45):
            signals.append({
                "type": "strong_sell",
                "strength": strength_base,
                "reason": "方向向下且速度转负，市场或资金情绪偏弱",
                "horizon": "medium",
            })
        if sentiment_index < 48:
            signals.append({
                "type": "sell",
                "strength": strength_soft,
                "reason": "方向向下，市场情绪温和偏空",
                "horizon": "short",
            })
    if stress == "high" or heat > 0.7:
        signals.append({
            "type": "reduce",
            "strength": min(1.0, 0.4 + heat * 0.6),
            "reason": "市场过热或压力偏高，建议降低仓位",
            "horizon": "risk_mgmt",
        })
    if not signals:
        signals.append({
            "type": "hold",
            "strength": 0.3,
            "reason": "信号不明确，建议观望",
            "horizon": "short",
        })
    priority = {"strong_buy": 0, "strong_sell": 1, "buy": 2, "sell": 3, "reduce": 4, "hold": 5}
    signals.sort(key=lambda s: (priority.get(s["type"], 9), -s["strength"]))
    recommendation = signals[0] if signals else None
    return {"recommendation": recommendation, "signals": signals}


def summarize_trend(direction, velocity, acceleration) -> str:
    parts = []
    if direction == "up":
        parts.append("方向向上")
    elif direction == "down":
        parts.append("方向向下")
    else:
        parts.append("方向中性")
    if velocity > 0.2:
        parts.append("速度加速")
    elif velocity < -0.2:
        parts.append("速度减速")
    else:
        parts.append("速度平稳")
    if acceleration > 0.2:
        parts.append("加速度正向")
    elif acceleration < -0.2:
        parts.append("加速度负向")
    else:
        parts.append("加速度平稳")
    return "，".join(parts)


def load_module_timeseries(module_name: str) -> list:
    all_data = _load_timeseries_all()
    return all_data.get(module_name, [])


def save_module_timeseries(module_name: str, entry: dict) -> None:
    all_data = _load_timeseries_all()
    series = all_data.get(module_name, [])
    series.append(entry)
    if len(series) > MAX_ENTRIES:
        series = series[-MAX_ENTRIES:]
    all_data[module_name] = series
    _save_timeseries_all(all_data)


def run_module_analysis(module_name: str, events, raw_score: float, sentiment_idx: float,
                        flow_idx: float, heat: float, stress: str) -> dict:
    events = events or []
    history = load_module_timeseries(module_name)
    historical_scores = [e.get("direction_score", 0.0) for e in history]
    r3d = compute_resistance_3d(raw_score, historical_scores)
    sig = generate_signal(r3d, sentiment_idx, flow_idx, heat, stress)
    ts = datetime.utcnow().isoformat() + "Z"
    entry = {
        "ts": ts,
        "direction_score": r3d["direction_score"],
        "velocity": r3d["velocity"],
    }
    save_module_timeseries(module_name, entry)
    metrics = {
        "sentiment_index": sentiment_idx,
        "flow_index": flow_idx,
        "heat": heat,
        "stress": stress,
        "summary": summarize_trend(r3d["direction"], r3d["velocity"], r3d["acceleration"]),
    }
    return {
        "ts": ts,
        "resistance_3d": r3d,
        "signals": sig,
        "metrics": metrics,
        "timeline": events[:10],
    }


if __name__ == "__main__":
    print("least_resistance 模块就绪")
