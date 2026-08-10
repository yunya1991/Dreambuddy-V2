"""Phase E: PPO-LSTM 强化学习闸门 + 确定性风控盾

路线图 §5 Phase E 核心模块。封装 PPO policy 推理 → 5 维动作 → §3.3 边界 clamp →
§5.2 DS1-DS6 确定性风控盾 → 最终生效动作。

设计原则（与 PhaseDGateway 一致）：
- enabled=False 时所有方法返回基线原值（铁律 1 字节级等价）
- MVP 桥接模式：_mock_action 支持测试注入，真实 PPO 权重加载后替换
- K_bound 初始 0.80（§5.3 Phase E 从收紧起跑）
"""
from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Tuple

# ── §3.3 动作空间默认边界（LOWER / UPPER 相对倍率） ──
ACTION_BOUNDS = {
    "addon_pct_mult":      {"lo": 0.80, "hi": 1.30, "abs_lo": 0.375, "abs_hi": 3.125},   # 绝对: addon_pct∈[3%,25%] / base 8%
    "addon_size_mult":     {"lo": 0.60, "hi": 1.50, "abs_lo": 0.60, "abs_hi": 1.50},
    "tp_pct_mult":         {"lo": 0.80, "hi": 1.30, "abs_lo": 0.375, "abs_hi": 3.00},      # 绝对: tp∈[1.5%,12%] / base 4%
    "base_position_mult":  {"lo": 0.70, "hi": 1.20, "abs_lo": 0.50, "abs_hi": 2.00},       # 绝对: pct∈[5%,40%] / base 22%
    "max_addons_delta":    {"lo": -1,   "hi": 0,    "abs_lo": -1,   "abs_hi": 0},          # 只可缩档
}

# §3.3 铁壳：总加仓预算不超过原 ×1.10
TOTAL_BUDGET_CEIL_MULT = 1.10

# §5.3 Phase E K_bound 起始
PHASE_E_DEFAULT_K_BOUND = 0.80


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def _apply_k_bound_to_bounds(lo: float, hi: float, k_bound: float) -> Tuple[float, float]:
    """§3.4 K_bound 缩放边界。
    K_bound > 1 → LOWER 更靠近 1（更宽），UPPER 更远离 1（更宽）
    K_bound < 1 → LOWER 更远离 1（更紧），UPPER 更靠近 1（更紧）
    """
    if k_bound <= 0:
        k_bound = 0.50
    # LOWER: 1 - (1 - lo) / k_bound  （k_bound > 1 时 lo_eff 更靠近 1）
    if lo < 1.0:
        lo_eff = 1.0 - (1.0 - lo) / k_bound
    else:
        lo_eff = lo
    # UPPER: 1 + (hi - 1) * k_bound
    if hi > 1.0:
        hi_eff = 1.0 + (hi - 1.0) * k_bound
    else:
        hi_eff = hi
    return lo_eff, hi_eff


@dataclass
class PhaseEGateway:
    """PPO-LSTM 策略推理 + 确定性风控盾。

    核心方法:
        get_action(s_state) → 5 维动作 dict（已 clamp 边界，未过盾）
        shield_check(action, s_state, alloc, params) → 盾后动作 dict + shield_flags
        apply_size_multipliers(alloc, s_state) → 最终 allocation dict
        apply_param_multipliers(coin, params, s_state) → 最终 params dict
    """

    enabled: bool = False
    ppo_model_path: Optional[str] = None
    k_bound: float = PHASE_E_DEFAULT_K_BOUND
    # §5.2 DS 盾开关（生产不可关，测试可关）
    shield_enabled: bool = True

    # TDD 诊断
    last_shield_flags: list = field(default_factory=list, repr=False)
    _mock_action: Optional[Dict[str, Any]] = field(default=None, repr=False)
    _ppo_model: Any = field(default=None, repr=False)

    def __post_init__(self):
        if self.enabled and self.ppo_model_path and os.path.isfile(self.ppo_model_path):
            try:
                self._load_ppo_model()
            except Exception:
                pass  # 加载失败 → 降级为中性动作

    def _load_ppo_model(self):
        """加载 PPO-LSTM 权重（MVP 阶段留空，训练完成后注入）。"""
        pass  # pragma: no cover

    # ── 核心：PPO 推理 → 5 维动作 ──

    def _infer_action(self, s_state: Dict[str, Any]) -> Dict[str, Any]:
        """PPO policy 推理，返回原始 5 维动作。"""
        if self._mock_action is not None:
            return dict(self._mock_action)
        # MVP 桥接：无模型时返回中性动作（=基线）
        return {
            "addon_pct_mult": 1.0,
            "addon_size_mult": 1.0,
            "tp_pct_mult": 1.0,
            "base_position_mult": 1.0,
            "max_addons_delta": 0,
        }

    def _clamp_action(self, raw: Dict[str, Any]) -> Dict[str, Any]:
        """§3.3 + §3.4 双层 clamp：先 K_bound 相对边界，再宽安全网。
        绝对值铁壳（addon_pct∈[3%,25%] 等）由 DS3/DS4 盾在 shield_check 中检查。"""
        clamped = {}
        for key, bounds in ACTION_BOUNDS.items():
            val = raw.get(key, 1.0 if key != "max_addons_delta" else 0)
            if key == "max_addons_delta":
                clamped[key] = int(max(bounds["abs_lo"], min(bounds["abs_hi"], int(val))))
                continue

            lo_eff, hi_eff = _apply_k_bound_to_bounds(bounds["lo"], bounds["hi"], self.k_bound)
            # 相对边界 clamp
            val = _clamp(float(val), lo_eff, hi_eff)
            # 宽安全网（防止极端值，但不干涉 DS 盾的绝对值检查）
            val = _clamp(val, 0.01, 100.0)
            clamped[key] = val
        return clamped

    def get_action(self, s_state: Dict[str, Any]) -> Dict[str, Any]:
        """返回已 clamp 边界的 5 维动作（未过盾）。"""
        if not self.enabled:
            return {
                "addon_pct_mult": 1.0,
                "addon_size_mult": 1.0,
                "tp_pct_mult": 1.0,
                "base_position_mult": 1.0,
                "max_addons_delta": 0,
            }
        raw = self._infer_action(s_state)
        return self._clamp_action(raw)

    # ── §5.2 确定性风控盾 ──

    def shield_check(
        self,
        action: Dict[str, Any],
        s_state: Dict[str, Any],
        allocation: Dict[str, Any],
        base_params: Dict[str, Any],
    ) -> Dict[str, Any]:
        """DS1-DS6 六盾检查，返回盾后动作 + shield_flags 列表。"""
        if not self.enabled or not self.shield_enabled:
            action = dict(action)
            action["shield_flags"] = []
            return action

        shielded = dict(action)
        flags = []

        # ── DS1: 总保证金率安全 ──
        margin_ratio = float(s_state.get("account_margin_ratio", 0.0))
        imr = float(s_state.get("imr", 0.05))
        margin_ceil = (imr + 0.02) * 1.50
        if margin_ratio > margin_ceil:
            if shielded["addon_size_mult"] > 1.0:
                shielded["addon_size_mult"] = 1.0
                flags.append("DS1")
            shielded["max_addons_delta"] = min(shielded["max_addons_delta"], -1)
            if "DS1" not in flags:
                flags.append("DS1")

        # ── DS2: 单币种投入上限 ──
        coin_deployed = float(s_state.get("coin_total_deployed", 0.0))
        per_coin_budget = float(allocation.get("per_coin_budget", 0.0))
        if per_coin_budget > 0 and coin_deployed > per_coin_budget * TOTAL_BUDGET_CEIL_MULT:
            if shielded["addon_size_mult"] > 1.0:
                shielded["addon_size_mult"] = 1.0
            if shielded["base_position_mult"] > 1.0:
                shielded["base_position_mult"] = 1.0
            flags.append("DS2")

        # ── DS3: TP 绝对值 ──
        base_tp = float(base_params.get("tp_pct", 4.0))
        eff_tp = base_tp * shielded["tp_pct_mult"]
        if eff_tp < 1.5:
            shielded["tp_pct_mult"] = 1.5 / base_tp if base_tp > 0 else 1.0
            flags.append("DS3")
        elif eff_tp > 12.0:
            shielded["tp_pct_mult"] = 12.0 / base_tp if base_tp > 0 else 1.0
            flags.append("DS3")

        # ── DS4: addon_pct 绝对值 ──
        base_addon = float(base_params.get("addon_pct", 8.0))
        eff_addon = base_addon * shielded["addon_pct_mult"]
        if eff_addon < 3.0:
            shielded["addon_pct_mult"] = 3.0 / base_addon if base_addon > 0 else 1.0
            flags.append("DS4")
        elif eff_addon > 25.0:
            shielded["addon_pct_mult"] = 25.0 / base_addon if base_addon > 0 else 1.0
            flags.append("DS4")

        # ── DS5: 极端行情禁放大 ──
        vol_z = float(s_state.get("vol_zscore_60", 0.0))
        if vol_z > 2.5:
            for k in ["addon_pct_mult", "addon_size_mult", "tp_pct_mult", "base_position_mult"]:
                if shielded[k] > 1.0:
                    shielded[k] = 1.0
            flags.append("DS5")

        # ── DS6: 连亏熔断 ──
        win_rate = float(s_state.get("recent_10_win_rate", 0.5))
        trade_count = int(s_state.get("recent_10_count", 0))
        if win_rate < 0.20 and trade_count >= 10:
            if shielded["max_addons_delta"] != -1:
                shielded["max_addons_delta"] = -1
                flags.append("DS6")

        shielded["shield_flags"] = flags
        self.last_shield_flags = flags
        return shielded

    # ── 整合 API ──

    def apply_size_multipliers(
        self,
        allocation: Dict[str, Any],
        s_state: Dict[str, Any],
    ) -> Dict[str, Any]:
        """应用动作到 allocation dict（含盾 + 总预算 clamp）。"""
        if not self.enabled:
            return dict(allocation)

        action = self.get_action(s_state)
        action = self.shield_check(action, s_state, allocation, {"tp_pct": 4.0, "addon_pct": 8.0})

        result = dict(allocation)
        base_mult = action["base_position_mult"]
        size_mult = action["addon_size_mult"]
        max_addons_delta = action["max_addons_delta"]

        # 应用倍率
        result["base_usd"] = round(allocation.get("base_usd", 0) * base_mult, 2)
        for k in [1, 2, 3, 4]:
            key = f"addon{k}_usd"
            result[key] = round(allocation.get(key, 0) * size_mult, 2)

        # max_addons_delta=-1 → 最深档清零
        if max_addons_delta == -1:
            result["addon4_usd"] = 0.0

        # §3.3 铁壳：总预算 ≤ 原 × 1.10
        original_total = float(allocation.get("total_usd", 0))
        if original_total > 0:
            current_total = (
                result["base_usd"]
                + result["addon1_usd"]
                + result["addon2_usd"]
                + result["addon3_usd"]
                + result["addon4_usd"]
            )
            ceil = original_total * TOTAL_BUDGET_CEIL_MULT
            if current_total > ceil:
                # 按比例缩减
                ratio = ceil / current_total
                result["base_usd"] = round(result["base_usd"] * ratio, 2)
                for k in [1, 2, 3, 4]:
                    key = f"addon{k}_usd"
                    result[key] = round(result[key] * ratio, 2)

        result["total_usd"] = round(
            result["base_usd"]
            + result["addon1_usd"]
            + result["addon2_usd"]
            + result["addon3_usd"]
            + result["addon4_usd"],
            2,
        )
        result["ai_action"] = action
        return result

    def apply_param_multipliers(
        self,
        coin: str,
        base_params: Dict[str, Any],
        s_state: Dict[str, Any],
    ) -> Dict[str, Any]:
        """应用动作到 strategy params（addon_pct / tp_pct）。"""
        if not self.enabled:
            return dict(base_params)

        action = self.get_action(s_state)
        # 盾检查需要 allocation（用空 dict 占位，DS1/DS2 不依赖 params）
        action = self.shield_check(action, s_state, {"per_coin_budget": 0}, base_params)

        result = dict(base_params)
        base_addon = float(base_params.get("addon_pct", 8.0))
        base_tp = float(base_params.get("tp_pct", 4.0))

        result["addon_pct"] = round(base_addon * action["addon_pct_mult"], 2)
        result["tp_pct"] = round(base_tp * action["tp_pct_mult"], 2)
        result["ai_action"] = action
        return result
