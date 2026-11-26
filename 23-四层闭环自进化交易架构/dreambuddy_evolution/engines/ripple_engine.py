"""
RippleEngine (§0.7 调研-观察-总结 涟漪扩散引擎)
蓝图: 四层闭环进化架构-最小阻力路径总览.md §0.7

龙头检测 + R1/R2/R3 三层涟漪扩散 → RI ∈ [0,1]
哲学根: 扔石头入水 → 龙头起 → 关联起 → 板块起 → 若可持续则成为真正趋势
"""

import logging
import math
import os
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)


class RippleEngine:
    """涟漪扩散引擎 — 外察式先验扫描，每K线触发"""

    def __init__(self, vol_ratio_threshold: float = 2.0, liq_change_threshold: float = 0.30):
        """
        龙头检测门槛（可配置）:
        - vol_ratio_threshold: vol_5/vol_20 放量倍数，默认 2.0（严格龙头）
          训练期可降至 1.3 以积累样本
        - liq_change_threshold: 清算指数变化率，默认 0.30
        """
        self._vol_ratio_threshold = float(
            os.getenv("EVOLUTION_RIPPLE_VOL_RATIO", vol_ratio_threshold)
        )
        self._liq_change_threshold = float(
            os.getenv("EVOLUTION_RIPPLE_LIQ_CHANGE", liq_change_threshold)
        )
        # 2026-11-26 用户决策：ripple 龙头扩展到 Quantum 档（代币化股票等）。
        # 默认纳入；EVOLUTION_RIPPLE_INCLUDE_QUANTUM=0 可恢复 §0.7.5 旧排除口径。
        self._include_quantum = os.getenv(
            "EVOLUTION_RIPPLE_INCLUDE_QUANTUM", "1"
        ).strip().lower() not in ("0", "false", "off", "no")

    def calibrate_vol_threshold(self, close: Any, lookback_days: int = 20) -> float:
        """按 20 日已实现波动率动态校准放量门槛。

        1H 对数收益 std × sqrt(24) → 日波动率；threshold = clamp(1.20 + 25σ_d, 1.30, 2.50)。
        低波动品种降低门槛（放量 2 倍本就更罕见），高波动品种提高门槛，避免误触发。
        数据不足 48 根 → 返回实例/环境默认值。
        """
        try:
            arr = np.asarray(close if close is not None else [], dtype=float)
            if arr.size < 48:
                return self._vol_ratio_threshold
            lr = np.diff(np.log(np.clip(arr, 1e-12, None)))
            window = lr[-min(lr.size, 24 * lookback_days) :]
            sigma_1h = float(np.std(window))
            sigma_day = sigma_1h * math.sqrt(24.0)
            return float(max(1.30, min(2.50, 1.20 + 25.0 * sigma_day)))
        except Exception as e:
            logger.debug("[FO] calibrate_vol_threshold fail: %s", e)
            return self._vol_ratio_threshold

    def detect_ripple_source(
        self, source: dict[str, Any], vol_ratio_threshold: float | None = None
    ) -> bool:
        """
        §0.7.2 Phase 0: 龙头检测
        条件: S_up簇(ESS_top方向一致) + vol_5/vol_20≥门槛 + liq_index↑≥门槛
              + Scale 默认含 {Classical,Meso,Quantum}（Quantum 排除可用环境变量恢复）

        vol_ratio_threshold: 调用方按 20 日波动率动态校准后的门槛；None 用实例默认值
        """
        try:
            threshold = (
                self._vol_ratio_threshold
                if vol_ratio_threshold is None
                else float(vol_ratio_threshold)
            )
            r_vec = source.get("r_vector") or source.get("leader_r_vector") or {}
            r_up = float(r_vec.get("R_up", 0.5))
            r_down = float(r_vec.get("R_down", 0.5))
            ess_dir = str(source.get("ess_top_direction", "")).lower()
            vol_5 = float(source.get("vol_5", 0))
            vol_20 = float(source.get("vol_20", 1e-9))
            liq_change = float(source.get("liq_index_change", 0))
            scale = str(source.get("scale_class", ""))

            # 1. 方向: R_up < R_down = 上涨有利 → ess_dir=long 一致
            is_up = r_up < r_down
            dir_match = (is_up and ess_dir == "long") or (not is_up and ess_dir == "short")
            if not dir_match:
                return False

            # 2. 放量: vol_5/vol_20 ≥ 门槛
            vol_ratio = vol_5 / max(vol_20, 1e-9)
            if vol_ratio < threshold:
                return False

            # 3. 清算指数上升 ≥ 门槛
            if liq_change < self._liq_change_threshold:
                return False

            # 4. Scale: Quantum 默认纳入（2026-11-26）；EVOLUTION_RIPPLE_INCLUDE_QUANTUM=0 时排除
            if scale == "Quantum" and not self._include_quantum:
                return False

            return True
        except Exception as e:
            logger.warning("[FO] ripple source detection fail: %s", e)
            return False

    def compute_ri(self, ripples: dict[str, Any]) -> float:
        """
        §0.7.2: RI = 0.4·score₁ + 0.35·score₂ + 0.25·score₃
        score_i = (hits/candidates) · exp(−Δt / τ)
        FAIL-OPEN: 空 ripples → RI=0.50 中性降级
        """
        try:
            if not ripples:
                return 0.50  # FO 降级

            weights = {"R1": 0.4, "R2": 0.35, "R3": 0.25}
            ri = 0.0
            for key, w in weights.items():
                r = ripples.get(key)
                if not r:
                    continue
                hits = float(r.get("hits", 0))
                cands = float(r.get("candidates", 1))
                if cands <= 0:
                    continue
                dt = float(r.get("delta_t_hours", 0))
                tau = float(r.get("tau", 1.0))
                score = (hits / cands) * math.exp(-dt / tau)
                ri += w * score

            return max(0.0, min(1.0, ri))
        except Exception as e:
            logger.warning("[FO] RI compute fail: %s", e)
            return 0.50

    def get_ri_action(self, ri: float) -> dict[str, Any]:
        """§0.7.3 RI 阈值动作表"""
        if ri < 0.30:
            return {"cbr_boost": 0.0, "ess_temp_mult": 1.0, "trigger_a2": False}
        elif ri < 0.55:
            return {"cbr_boost": 0.10, "ess_temp_mult": 1.0, "trigger_a2": False}
        elif ri < 0.75:
            return {"cbr_boost": 0.20, "ess_temp_mult": 1.05, "trigger_a2": False}
        else:
            return {"cbr_boost": 0.25, "ess_temp_mult": 1.10, "trigger_a2": True}
