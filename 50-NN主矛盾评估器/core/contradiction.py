"""N2 主矛盾识别（50 复刻 23 contradiction_identifier 三步法设计口径）。

不 import 23，独立实现。

三步法：
  Step1 共振：非中性维度中 majority 方向占比 ≥ 0.6 → type="resonance"
  Step2 冲突（<0.6）：4 维评分仲裁，选 leader
         power(strength)×0.40 + urgency×0.15 + consistency×0.25 + impact×0.20
  Step3 主导：leader_score / sum(scores) > 0.55 → dominant=True

M2 扩展（SPEC-M2 §2.2）：三类逐标的矛盾对象
  - macro_micro_conflict：同标的同维度 sign(F_macro)≠sign(F_micro)，|双方|≥0.3
  - temporal_conflict：宏观力未到达(now<t_arrive)但微观已反向，微观置信度按到达窗口衰减
  - inter_dimension_conflict：D1 vs D2/D4 反向
  - deduplicate_conflicts：同标的同维度只保留一个矛盾对象（优先 temporal_conflict）
"""

from __future__ import annotations

from core.dimension_forces import DimensionForce
from core.macro_force import CONFLICT_THRESHOLD, MacroForce, normalize_symbol

RESONANCE_THRESHOLD = 0.6
DOMINANCE_THRESHOLD = 0.55

# 仲裁权重
W_POWER = 0.40
W_URGENCY = 0.15
W_CONSISTENCY = 0.25
W_IMPACT = 0.20

DEFAULT_URGENCY = 0.5  # 暂无 horizon 紧迫性输入时的默认值
DEFAULT_IMPACT = 1.0  # 暂无市场影响权重输入时的默认值

# horizon → 天数（用于宏微观 horizon 仲裁）
HORIZON_DAYS: dict[str, float] = {
    "minutes": 1.0 / 1440,
    "hours": 1.0 / 24,
    "days": 1.0,
    "weeks": 7.0,
}

# SPEC-M2 §2.2 horizon 仲裁阈值
MICRO_DOMINANT_HORIZON_DAYS = 1.0  # ≤1d 微观主导 0.7
MACRO_DOMINANT_HORIZON_DAYS = 5.0  # ≥5d 宏观主导 0.7


def _arbitration_score(force: DimensionForce, max_path_count: int) -> float:
    power = force.strength
    urgency = DEFAULT_URGENCY
    consistency = force.path_count / max_path_count if max_path_count > 0 else 0.0
    impact = DEFAULT_IMPACT
    return power * W_POWER + urgency * W_URGENCY + consistency * W_CONSISTENCY + impact * W_IMPACT


def identify_primary_contradiction(forces: dict[str, DimensionForce]) -> dict:
    """识别主矛盾，返回结果字典。"""
    # 空输入 → neutral
    if not forces:
        return {"type": "neutral", "direction": "neutral", "strength": 0.0}

    # 过滤掉中性维度
    active = {d: f for d, f in forces.items() if f.direction != "neutral"}

    # 全部中性 → neutral
    if not active:
        return {"type": "neutral", "direction": "neutral", "strength": 0.0}

    # Step1: 共振检测 — 非中性维度中 majority 方向占比
    total = len(active)
    long_count = sum(1 for f in active.values() if f.direction == "long")
    short_count = total - long_count
    majority_count = max(long_count, short_count)
    resonance = majority_count / total if total > 0 else 0.0

    if resonance >= RESONANCE_THRESHOLD:
        majority_direction = "long" if long_count >= short_count else "short"
        return {
            "type": "resonance",
            "direction": majority_direction,
            "resonance": resonance,
            "strength": resonance,
            "active_dimensions": total,
            "long_count": long_count,
            "short_count": short_count,
        }

    # Step2: 冲突裁决 — 4 维评分选 leader
    max_path_count = max((f.path_count for f in active.values()), default=1)
    scores: dict[str, float] = {}
    for dim, f in active.items():
        scores[dim] = _arbitration_score(f, max_path_count)

    leader_dim = max(scores, key=scores.get)
    leader = active[leader_dim]
    leader_score = scores[leader_dim]
    total_score = sum(scores.values())

    # Step3: 主导性
    dominant = (leader_score / total_score) > DOMINANCE_THRESHOLD if total_score > 0 else False

    return {
        "type": "conflict",
        "direction": leader.direction,
        "leader_dimension": leader_dim,
        "leader_score": leader_score,
        "total_score": total_score,
        "dominant": dominant,
        "resonance": resonance,
        "active_dimensions": total,
        "long_count": long_count,
        "short_count": short_count,
    }


# ══════════════════════════════════════════════════════════════════
# M2：三类逐标的矛盾（SPEC-M2 §2.2）
# ══════════════════════════════════════════════════════════════════


def _horizon_arbitration(micro_horizon_days: float) -> tuple[float, float]:
    """宏微观 horizon 仲裁权重（SPEC-M2 §2.2 / SPEC-M1 M6）。

    返回 (macro_weight, micro_weight)。
    - micro_horizon ≤ 1d → 微观主导 (0.3, 0.7)
    - micro_horizon ≥ 5d → 宏观主导 (0.7, 0.3)
    - 过渡带 → 各半 (0.5, 0.5)
    """
    if micro_horizon_days <= MICRO_DOMINANT_HORIZON_DAYS:
        return 0.3, 0.7
    if micro_horizon_days >= MACRO_DOMINANT_HORIZON_DAYS:
        return 0.7, 0.3
    return 0.5, 0.5


def _macro_components(mf: MacroForce) -> dict[str, float]:
    return {"D1": mf.d1_trend, "D2": mf.d2_fund, "D4": mf.d4_sentiment}


def detect_macro_micro_conflicts(
    macro_forces: dict[str, MacroForce],
    micro_forces: dict[str, dict[str, float]],
    micro_horizon: str = "hours",
) -> list[dict]:
    """宏微观矛盾：同标的同维度 sign 相反且 |双方| ≥ CONFLICT_THRESHOLD。

    Args:
        macro_forces: {symbol: MacroForce}（symbol 已 normalize）
        micro_forces: {symbol: {dimension: signed_force}}
        micro_horizon: 微观力的 horizon 名称，用于仲裁权重
    """
    micro_h_days = HORIZON_DAYS.get(micro_horizon, 1.0)
    macro_w, micro_w = _horizon_arbitration(micro_h_days)
    conflicts: list[dict] = []

    # 归一化微观标的符号（BTC-USDT-SWAP → BTC）以匹配宏观侧
    norm_micro = {normalize_symbol(s): v for s, v in micro_forces.items()}

    for sym, mf in macro_forces.items():
        micro = norm_micro.get(sym, {})
        for dim, f_macro in _macro_components(mf).items():
            f_micro = micro.get(dim, 0.0)
            if (
                abs(f_macro) >= CONFLICT_THRESHOLD
                and abs(f_micro) >= CONFLICT_THRESHOLD
                and (f_macro * f_micro) < 0
            ):
                conflicts.append(
                    {
                        "type": "macro_micro_conflict",
                        "symbol": sym,
                        "dimension": dim,
                        "f_macro": round(f_macro, 6),
                        "f_micro": round(f_micro, 6),
                        "macro_weight": macro_w,
                        "micro_weight": micro_w,
                        "resolution": "macro" if macro_w > micro_w else "micro",
                    }
                )
    return conflicts


def detect_temporal_conflicts(
    macro_forces: dict[str, MacroForce],
    micro_forces: dict[str, dict[str, float]],
    now_offset_days: float = 0.0,
) -> list[dict]:
    """时序矛盾：宏观力到达窗口内的宏微观反向（SPEC-M2 §2.2）。

    - now < t_arrive：微观方向仍有效但置信度按 (1-(t_arrive-now)/lag) 衰减
    - now ≥ t_arrive：宏观主导，微观置信度归零
    仅在存在有效 lead-lag（t_arrive 非 None）时触发。
    """
    conflicts: list[dict] = []
    # 归一化微观标的符号
    norm_micro = {normalize_symbol(s): v for s, v in micro_forces.items()}
    for sym, mf in macro_forces.items():
        t_arrive = mf.t_arrive_days
        if t_arrive is None or t_arrive <= 0:
            continue
        lag = t_arrive  # 总滞后窗口
        micro = norm_micro.get(sym, {})
        for dim, f_macro in _macro_components(mf).items():
            f_micro = micro.get(dim, 0.0)
            if abs(f_macro) < CONFLICT_THRESHOLD or abs(f_micro) < CONFLICT_THRESHOLD:
                continue
            if (f_macro * f_micro) >= 0:
                continue  # 同向不构成时序矛盾

            if now_offset_days < t_arrive:
                decay = max(0.0, 1.0 - (t_arrive - now_offset_days) / lag)
                resolution = "micro_transition" if decay < 0.5 else "converging"
            else:
                decay = 0.0
                resolution = "macro_dominant"

            conflicts.append(
                {
                    "type": "temporal_conflict",
                    "symbol": sym,
                    "dimension": dim,
                    "f_macro": round(f_macro, 6),
                    "f_micro": round(f_micro, 6),
                    "t_arrive": t_arrive,
                    "now_offset_days": now_offset_days,
                    "micro_decay": round(decay, 6),
                    "resolution": resolution,
                }
            )
    return conflicts


def detect_inter_dimension_conflicts(
    macro_forces: dict[str, MacroForce],
) -> list[dict]:
    """维度间矛盾：D1 趋势 vs D2 资金 / D4 情绪 反向（|双方| ≥ 阈值）。

    防御性共振（down_corr 高）时 D2 空头力放大 1.3× 由调用方在 macro_force 侧处理，
    此处只做方向对撞。
    """
    conflicts: list[dict] = []
    for sym, mf in macro_forces.items():
        d1 = mf.d1_trend
        for dim, f in (("D2", mf.d2_fund), ("D4", mf.d4_sentiment)):
            if abs(d1) >= CONFLICT_THRESHOLD and abs(f) >= CONFLICT_THRESHOLD and (d1 * f) < 0:
                conflicts.append(
                    {
                        "type": "inter_dimension_conflict",
                        "symbol": sym,
                        "dimensions": ["D1", dim],
                        "f_d1": round(d1, 6),
                        f"f_{dim.lower()}": round(f, 6),
                        "resolution": "D1" if abs(d1) >= abs(f) else dim,
                    }
                )
    return conflicts


def deduplicate_conflicts(conflicts: list[dict]) -> list[dict]:
    """矛盾去重（SPEC-M2 §1.2 评审增补）。

    同一 (symbol, dimension) 只允许一个矛盾对象：
    - 存在有效 lead-lag → 保留 temporal_conflict
    - 否则保留 macro_micro_conflict
    inter_dimension_conflict 按 (symbol, sorted_dimensions) 去重，不与前两类冲突。
    """
    by_key: dict[tuple, dict] = {}
    for c in conflicts:
        if c["type"] == "inter_dimension_conflict":
            key = (c["symbol"], tuple(sorted(c.get("dimensions", []))))
        else:
            key = (c["symbol"], c.get("dimension"))

        existing = by_key.get(key)
        if existing is None:
            by_key[key] = c
        else:
            # 同 key 冲突：优先 temporal_conflict
            priority = {"temporal_conflict": 2, "macro_micro_conflict": 1}
            if priority.get(c["type"], 0) > priority.get(existing["type"], 0):
                by_key[key] = c
    return list(by_key.values())


def detect_all_conflicts(
    macro_forces: dict[str, MacroForce],
    micro_forces: dict[str, dict[str, float]],
    micro_horizon: str = "hours",
    now_offset_days: float = 0.0,
) -> list[dict]:
    """一次性生成三类矛盾并去重。"""
    raw = (
        detect_macro_micro_conflicts(macro_forces, micro_forces, micro_horizon)
        + detect_temporal_conflicts(macro_forces, micro_forces, now_offset_days)
        + detect_inter_dimension_conflicts(macro_forces)
    )
    return deduplicate_conflicts(raw)
