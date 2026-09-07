"""
ReflectionEngine (§1.6 调查·反思·实践 三公理)
蓝图: 四层闭环进化架构-最小阻力路径总览.md §1.6

pre_trade_snapshot → CS 一致性得分 → 四维奖惩表 → ESS/gmax 更新
"""
import math
import logging
from typing import Any

logger = logging.getLogger(__name__)


class ReflectionEngine:
    """系统自反思进化引擎 — 后验追溯，每笔交易结算触发"""

    def create_snapshot(
        self,
        symbol: str,
        u_open: float,
        action: str,
        level0_dstar: str,
        ess_id: str,
        ess_dir: str,
        cbr_sim: float,
        cbr_top1_outcome: str,
        cluster_id: str,
    ) -> dict[str, Any]:
        """§1.6.3 A6: 开仓瞬间快照（事后反思基础）"""
        return {
            "symbol": symbol,
            "u_open": float(u_open),
            "action": action,
            "level0_dstar": level0_dstar,
            "ess_id": ess_id,
            "ess_dir": ess_dir,
            "cbr_sim": float(cbr_sim),
            "cbr_top1_outcome": cbr_top1_outcome,
            "cluster_id": cluster_id,
        }

    def calculate_cs(
        self,
        snapshot: dict[str, Any],
        outcome: dict[str, Any],
    ) -> float:
        """
        §1.6.3 公理2: CS = 0.4·cos(d*,real) + 0.3·cos(ESS,real) + 0.3·sign_match(CBR,real)
        cos(预测,实际): 同向+1, WAIT=0, 反向-1
        sign_match: cbr=TP&实际TP=+1, cbr=TP实际SL=-1, cbr=SL实际SL=+1, cbr=SL实际TP=-1
        CS ∈ [-1.0, +1.0]
        """
        try:
            d_star = str(snapshot.get("level0_dstar", "")).lower()
            ess_dir = str(snapshot.get("ess_dir", "")).lower()
            cbr_outcome = str(snapshot.get("cbr_top1_outcome", "")).upper()
            real_dir = str(outcome.get("real_direction", "")).lower()
            real_outcome = str(outcome.get("real_outcome", "")).upper()

            # cos(预测方向, 实际方向)
            def cos_dir(pred, real):
                if pred == real and pred in ("long", "short"):
                    return 1.0
                if pred == "wait" or real == "wait":
                    return 0.0
                if pred in ("long", "short") and real in ("long", "short") and pred != real:
                    return -1.0
                return 0.0

            # sign_match(CBR预测, 实际结果)
            def sign_match(cbr, real):
                if cbr == real:
                    return 1.0
                return -1.0

            cs = (0.4 * cos_dir(d_star, real_dir)
                  + 0.3 * cos_dir(ess_dir, real_dir)
                  + 0.3 * sign_match(cbr_outcome, real_outcome))

            return max(-1.0, min(1.0, cs))
        except Exception as e:
            logger.warning("[FO] CS calculation fail: %s", e)
            return 0.0  # FO 中性

    def apply_reward(
        self,
        cs: float,
        outcome: str,
        cluster_id: str,
        ess_id: str,
        gmax: float,
    ) -> dict[str, Any]:
        """
        §1.6.3 四维奖惩表:
        CS≥0.7 & TP → ESS +0.02, gmax 不变, cluster +1
        -0.2≤CS<0.7 → 不更新
        CS≤-0.2 & SL → ESS -0.05, gmax ×0.5
        CS≤-0.2 & TP → 反例保护, ESS 不更新
        CS≥0.7 & SL → 假失败, ESS 不扣, gmax ×1.2
        """
        outcome = str(outcome).upper()

        # CS≥0.7 且 TP（判断准且对）
        if cs >= 0.7 and outcome == "TP":
            return {"ess_delta": 0.02, "gmax_mult": 1.0, "cluster_weight_mult": 1.0}

        # CS≤-0.2 且 SL（判断错且亏了）
        if cs <= -0.2 and outcome == "SL":
            return {"ess_delta": -0.05, "gmax_mult": 0.5, "cluster_weight_mult": 0.8}

        # CS≤-0.2 但 TP（判断错但赚了=运气）
        if cs <= -0.2 and outcome == "TP":
            return {"ess_delta": 0.0, "gmax_mult": 1.0, "cluster_weight_mult": 1.0,
                    "anti_pattern_flag": True}

        # CS≥0.7 但 SL（方向对却被扫损=假失败）
        if cs >= 0.7 and outcome == "SL":
            return {"ess_delta": 0.0, "gmax_mult": 1.2, "cluster_weight_mult": 0.5}

        # -0.2≤CS<0.7（中性/判断一般）
        return {"ess_delta": 0.0, "gmax_mult": 1.0, "cluster_weight_mult": 1.0}
