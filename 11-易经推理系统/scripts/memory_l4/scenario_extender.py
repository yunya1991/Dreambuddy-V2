"""
场景推演器 — 基于真实 case 生成假设场景扩展案例库。

核心思路：
1. 从真实 case 提取基线场景（liangyi_state + scale_params + 市场指标）
2. 对关键参数进行合理扰动（波动率、趋势强度、价格位置、相位偏移）
3. 用 XGBoost 预测器预测假设场景的结果
4. 生成扩展 case，标记为 hypothetical 来源

扰动策略：
- 波动率: 0.5x ~ 2x 随机因子
- 趋势强度: ±30%
- 价格位置: ±20%
- 两仪相位: 相邻相位偏移
- 权重: 重新归一化随机分配
"""
import json
import random
import uuid
import time
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from .qmm.xgb_predictor import QMMPredictor, extract_features_from_case, LABEL_MAP, LABEL_INVERSE


PHASE_TRANSITIONS = {
    "macro": {
        "recession": ["recovery"],
        "recovery": ["recession", "overheat"],
        "overheat": ["recovery", "stagflation"],
        "stagflation": ["overheat", "recession"],
    },
    "micro": {
        "sprout": ["growth"],
        "growth": ["sprout", "mature"],
        "mature": ["growth", "decline"],
        "decline": ["mature", "sprout"],
    },
}


def perturb_scalar(value: float, factor: float = 0.3) -> float:
    """对数值进行扰动，保持在合理范围。"""
    if value <= 0:
        return value
    perturbed = value * (1 + random.uniform(-factor, factor))
    return max(0.01, min(2.0, perturbed))


def perturb_weight_vector(weights: List[float], noise: float = 0.2) -> List[float]:
    """扰动权重向量，保持归一化。"""
    new_weights = [max(0.01, w * (1 + random.uniform(-noise, noise))) for w in weights]
    total = sum(new_weights)
    return [w / total for w in new_weights]


def perturb_phase(liangyi_state: Dict[str, Any]) -> Dict[str, Any]:
    """扰动两仪相位，选择相邻相位。"""
    new_state = dict(liangyi_state)
    macro = liangyi_state.get("macro_phase", "recovery")
    micro = liangyi_state.get("micro_phase", "sprout")

    if random.random() < 0.4:
        transitions = PHASE_TRANSITIONS["macro"].get(macro, [macro])
        new_state["macro_phase"] = random.choice(transitions)

    if random.random() < 0.4:
        transitions = PHASE_TRANSITIONS["micro"].get(micro, [micro])
        new_state["micro_phase"] = random.choice(transitions)

    # 更新季节文字
    macro_season_map = {"recovery": "春", "overheat": "夏", "stagflation": "秋", "recession": "冬"}
    micro_season_map = {"sprout": "春", "growth": "夏", "mature": "秋", "decline": "冬"}
    new_state["macro_season"] = macro_season_map.get(new_state["macro_phase"], "春")
    new_state["micro_season"] = micro_season_map.get(new_state["micro_phase"], "春")

    # 更新 resonance/conflict 标志（基于相位关系）
    new_macro = new_state["macro_phase"]
    new_micro = new_state["micro_phase"]
    is_resonance = (new_macro == new_micro) or (
        (new_macro == "recovery" and new_micro in ["sprout", "growth"]) or
        (new_macro == "overheat" and new_micro in ["growth", "mature"]) or
        (new_macro == "stagflation" and new_micro in ["mature", "decline"]) or
        (new_macro == "recession" and new_micro in ["decline", "sprout"])
    )
    new_state["is_resonance"] = is_resonance
    new_state["is_conflict"] = not is_resonance
    new_state["resonance_factor"] = float(is_resonance) * random.uniform(0.6, 1.0)

    return new_state


def perturb_case(case: Dict[str, Any], perturbation_type: str = "full") -> Dict[str, Any]:
    """对单个 case 进行扰动，生成假设场景。"""
    new_case = dict(case)

    # 扰动 liangyi_state
    ly = case.get("liangyi_state", {})
    if ly:
        new_case["liangyi_state"] = perturb_phase(ly)

    # 扰动 scale_params
    sp = case.get("scale_params", {})
    if sp:
        new_sp = dict(sp)

        # 扰动权重
        weights = [
            sp.get("weight_time", 0.2),
            sp.get("weight_space", 0.15),
            sp.get("weight_surface", 0.3),
            sp.get("weight_core", 0.35),
        ]
        if sum(weights) > 0:
            new_weights = perturb_weight_vector(weights, noise=0.3)
            new_sp["weight_time"], new_sp["weight_space"], new_sp["weight_surface"], new_sp["weight_core"] = new_weights

        # 扰动力学参数
        new_sp["market_mass_base"] = perturb_scalar(sp.get("market_mass_base", 1.0), 0.4)
        new_sp["velocity_decay"] = perturb_scalar(sp.get("velocity_decay", 0.85), 0.2)
        new_sp["confidence_threshold"] = perturb_scalar(sp.get("confidence_threshold", 0.375), 0.3)
        new_sp["reversal_threshold"] = perturb_scalar(sp.get("reversal_threshold", 0.175), 0.3)

        new_case["scale_params"] = new_sp

    # 扰动 environment_snapshot
    env = case.get("environment_snapshot", {})
    if env:
        new_env = dict(env)
        new_env["volatility"] = perturb_scalar(env.get("volatility", 0.5), 0.5)
        new_env["trend_strength"] = perturb_scalar(env.get("trend_strength", 0.5), 0.4)
        new_env["price_position"] = max(0.0, min(1.0, env.get("price_position", 0.5) + random.uniform(-0.2, 0.2)))
        new_env["volume_ratio"] = perturb_scalar(env.get("volume_ratio", 1.0), 0.6)
        new_case["environment_snapshot"] = new_env

    # 扰动 quadrant
    q = case.get("quadrant", {})
    if q:
        new_case["quadrant"] = {
            "x": q.get("x", 0) + random.uniform(-0.3, 0.3),
            "y": max(0.1, min(0.9, q.get("y", 0.5) + random.uniform(-0.2, 0.2))),
        }

    # 更新 case_id 和标记
    new_case["case_id"] = f"bcrm_hypo_{int(time.time())}_{uuid.uuid4().hex[:8]}"
    new_case["source"] = "hypothetical"
    new_case["parent_case_id"] = case.get("case_id", "")
    new_case["perturbation_type"] = perturbation_type

    # 清除旧的 outcome（需要预测）
    new_case.pop("decision_outcome", None)
    new_case.pop("actual_outcome", None)

    return new_case


def generate_hypothetical_cases(
    real_cases: List[Dict[str, Any]],
    multiplier: int = 5,
    predictor: Optional[QMMPredictor] = None,
) -> List[Dict[str, Any]]:
    """
    从真实 case 生成假设 case。

    Args:
        real_cases: 真实案例列表
        multiplier: 每个真实 case 生成的假设 case 数量
        predictor: XGBoost 预测器（用于预测假设场景的结果）

    Returns:
        生成的假设案例列表
    """
    hypothetical_cases = []

    if predictor is None:
        predictor = QMMPredictor()
        train_stats = predictor.train(real_cases)
        if not train_stats.get("ok"):
            print(f"预测器训练失败: {train_stats.get('reason')}")
            return hypothetical_cases
        print(f"预测器训练完成: cv_mean={train_stats['cv_mean']}, n_samples={train_stats['n_samples']}")

    for case in real_cases:
        for _ in range(multiplier):
            hypo_case = perturb_case(case)

            # 用预测器预测结果
            direction, uncertainty = predictor.predict(hypo_case)

            # 根据预测方向生成 outcome
            if direction == "UP":
                pnl_pct = random.uniform(0.01, 0.05) * (1 - uncertainty) + random.uniform(-0.005, 0.01) * uncertainty
                is_correct = True
            elif direction == "DOWN":
                pnl_pct = random.uniform(-0.05, -0.01) * (1 - uncertainty) + random.uniform(-0.01, 0.005) * uncertainty
                is_correct = True
            else:
                pnl_pct = random.uniform(-0.01, 0.01)
                is_correct = random.random() > 0.5

            hypo_case["actual_outcome"] = {
                "is_correct": is_correct,
                "pnl_pct": round(pnl_pct, 4),
                "exit_reason": "hypothetical",
            }
            hypo_case["decision_outcome"] = {
                "is_correct": is_correct,
                "pnl_pct": round(pnl_pct, 4),
            }
            hypo_case["direction"] = direction

            # 推断象限
            qx = 1.0 if pnl_pct > 0 else (-1.0 if pnl_pct < 0 else 0.0)
            qy = 0.7 if is_correct else 0.3
            hypo_case["quadrant"] = {"x": qx, "y": qy}

            hypothetical_cases.append(hypo_case)

    return hypothetical_cases


def save_hypothetical_cases(cases: List[Dict[str, Any]]) -> int:
    """保存假设案例到 L4。"""
    from .yijing_trainer import _save_cases_to_l4
    return _save_cases_to_l4(cases, source="hypothetical")


def run_scenario_extension(
    real_cases: List[Dict[str, Any]],
    multiplier: int = 5,
    save: bool = True,
) -> Dict[str, Any]:
    """
    运行场景扩展流程。

    Args:
        real_cases: 真实案例列表
        multiplier: 扩展倍数
        save: 是否保存到 L4

    Returns:
        统计结果
    """
    print(f"\n=== 场景推演扩展 ===")
    print(f"真实案例数: {len(real_cases)}")
    print(f"扩展倍数: {multiplier}")

    # 训练预测器
    predictor = QMMPredictor()
    train_stats = predictor.train(real_cases)
    if not train_stats.get("ok"):
        return {"ok": False, "reason": train_stats.get("reason")}

    # 生成假设案例
    hypo_cases = generate_hypothetical_cases(real_cases, multiplier, predictor)
    print(f"生成假设案例: {len(hypo_cases)}")

    # 保存
    saved = 0
    if save and hypo_cases:
        saved = save_hypothetical_cases(hypo_cases)
        print(f"保存到 L4: {saved} 个")

    # 统计扩展后的组合分布
    combo_dist = {}
    for c in hypo_cases:
        ly = c.get("liangyi_state", {})
        combo = f"{ly.get('macro_phase', 'unknown')}|{ly.get('micro_phase', 'unknown')}"
        combo_dist[combo] = combo_dist.get(combo, 0) + 1

    return {
        "ok": True,
        "real_cases": len(real_cases),
        "hypo_cases": len(hypo_cases),
        "saved": saved,
        "train_stats": train_stats,
        "combo_distribution": combo_dist,
    }
