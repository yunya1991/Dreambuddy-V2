"""struct_vector.py — E2 判据「人未写过」口径工具（SPEC-EMERGENCE-EVOLUTION v0.3 §1/§4 E0）。

结构向量 = 开关位掩码 + 阈值分箱 + 标的集合 hash。
编辑距离 = 位掩码汉明距离 + threshold_bins 曼哈顿距离 + coins 不同则 +2。
判据：生成物向量不在 human_config_hashes.json 且与全部人工配置编辑距离 >= k（默认 2）。
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

K_MIN_DISTANCE = 2
REGISTRY_PATH = Path(__file__).parent / "human_config_hashes.json"

SWITCH_ORDER = [
    "cbr_cycle_log",
    "elder_ray_c4",
    "win_prob_factor",
    "three_layer_weighter",
    "elastic_gate_3l",
    "bcrm_continuity_obs",
    "btc_self_reflex_valve",
    "portfolio_risk_fuses",
]
BDSM_ORDER = ["independent_open", "direction_overlay", "short_trial", "war_state_check"]
ENV_ORDER = [
    "bcrm_direction_state_check",
    "strategy_independent_open",
    "rag_hotpath",
    "rag_feedback",
    "case_distill",
    "tee",
]
PHASE_ORDER = ["mode_switch", "ev_radar", "multi_horizon", "ranked_tp", "regime_macro_s5"]


def coins_hash(coins: list[str]) -> str:
    return hashlib.sha256(",".join(sorted(coins)).encode()).hexdigest()[:16]


def make_struct_vector(
    switches: dict, bdsm: dict, env: dict, phase: dict, thresholds: dict, coins: list[str]
) -> dict:
    """thresholds: {confidence, max_positions, position_pct, interval}。"""
    return {
        "switches_bitmask": "".join("1" if switches.get(k) else "0" for k in SWITCH_ORDER),
        "bdsm_flags": "".join("1" if bdsm.get(k) else "0" for k in BDSM_ORDER),
        "env_flags": "".join("1" if env.get(k) else "0" for k in ENV_ORDER),
        "phase_flags": "".join("1" if phase.get(k) else "0" for k in PHASE_ORDER),
        "threshold_bins": [
            round(thresholds["confidence"] / 0.05),
            int(thresholds["max_positions"]),
            round(thresholds["position_pct"] * 100),
            int(thresholds["interval"]) // 60,
        ],
        "coins_hash": coins_hash(coins),
    }


def vector_hash(v: dict) -> str:
    canonical = json.dumps(v, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(canonical.encode()).hexdigest()[:16]


def edit_distance(a: dict, b: dict) -> int:
    """位掩码汉明距离 + threshold_bins 曼哈顿距离 + coins 不同 +2。"""
    d = 0
    for key in ("switches_bitmask", "bdsm_flags", "env_flags", "phase_flags"):
        d += sum(1 for x, y in zip(a[key], b[key], strict=False) if x != y)
    d += sum(abs(x - y) for x, y in zip(a["threshold_bins"], b["threshold_bins"], strict=False))
    if a["coins_hash"] != b["coins_hash"]:
        d += 2
    return d


def is_human_written(v: dict, registry_path: Path = REGISTRY_PATH, k: int = K_MIN_DISTANCE) -> dict:
    """返回 {is_human_written, min_distance, nearest_config_id}。registry 缺失 → 判据悬置。"""
    if not registry_path.exists():
        return {"is_human_written": None, "reason": "registry_missing_判据悬置"}
    reg = json.loads(registry_path.read_text(encoding="utf-8"))
    vh = vector_hash(v)
    best, nearest = None, None
    for cfg in reg["human_configs"]:
        dist = edit_distance(v, cfg["struct_vector"])
        if best is None or dist < best:
            best, nearest = dist, cfg["id"]
    return {
        "is_human_written": best is not None and best < k,
        "min_distance": best,
        "nearest_config_id": nearest,
        "vector_hash": vh,
    }


if __name__ == "__main__":
    # 自检：云端实盘配置应对自身 distance=0
    reg = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    live = reg["human_configs"][0]
    v = make_struct_vector(
        switches=dict.fromkeys(SWITCH_ORDER, True),
        bdsm={
            "independent_open": True,
            "direction_overlay": True,
            "short_trial": True,
            "war_state_check": False,
        },
        env={"rag_hotpath": True, "rag_feedback": True, "case_distill": True},
        phase=dict.fromkeys(PHASE_ORDER, True),
        thresholds={
            "confidence": 0.7955,
            "max_positions": 5,
            "position_pct": 0.20,
            "interval": 300,
        },
        coins=live["struct_vector"]["coins"],
    )
    print(json.dumps(is_human_written(v), ensure_ascii=False, indent=2))
