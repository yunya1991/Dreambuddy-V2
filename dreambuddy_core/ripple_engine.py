"""
RippleEngine (§0.7 调研-观察-总结 涟漪扩散引擎)
蓝图: 四层闭环进化架构-最小阻力路径总览.md §0.7

龙头检测 + R1/R2/R3 三层涟漪扩散 → RI ∈ [0,1]
哲学根: 扔石头入水 → 龙头起 → 关联起 → 板块起 → 若可持续则成为真正趋势
"""
import math
import logging
from typing import Any

logger = logging.getLogger(__name__)


class RippleEngine:
    """涟漪扩散引擎 — 外察式先验扫描，每K线触发"""

    def detect_ripple_source(self, source: dict[str, Any]) -> bool:
        """
        §0.7.2 Phase 0: 龙头检测
        条件: S_up簇(ESS_top方向一致) + vol_5/vol_20≥2.0 + liq_index↑≥30% + Scale∈{Classical,Meso}
        """
        try:
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

            # 2. 放量: vol_5/vol_20 ≥ 2.0
            vol_ratio = vol_5 / max(vol_20, 1e-9)
            if vol_ratio < 2.0:
                return False

            # 3. 清算指数上升 ≥ 30%
            if liq_change < 0.30:
                return False

            # 4. Scale: Quantum 排除 (§0.7.5)
            if scale == "Quantum":
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
