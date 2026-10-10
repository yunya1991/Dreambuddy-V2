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

    # REDUCE_WEIGHT 冷启动阈值：样本 < 20 只收集不调整
    _REDUCE_WEIGHT_WARM_THRESHOLD = 20

    def __init__(self, case_library: Any = None, gene_library: dict[str, Any] | None = None) -> None:
        # 入场侧 REDUCE_WEIGHT 样本计数器（cluster_id|ess_id → count）
        self._reduce_weight_counter: dict[str, int] = {}
        # 事件案例库（可选，用于胜率驱动权重自适应）
        self._case_library = case_library
        # 基因库（可选，_maybe_auto_adjust_weight 调整并持久化）
        self._gene_library = gene_library or {}

    def _get_reduce_weight_count(self, cluster_id: str, ess_id: str) -> int:
        """获取 REDUCE_WEIGHT 样本计数"""
        return self._reduce_weight_counter.get(f"{cluster_id}|{ess_id}", 0)

    def _incr_reduce_weight_count(self, cluster_id: str, ess_id: str) -> None:
        """递增 REDUCE_WEIGHT 样本计数"""
        key = f"{cluster_id}|{ess_id}"
        self._reduce_weight_counter[key] = self._reduce_weight_counter.get(key, 0) + 1

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
        dimension_predictions: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """§1.6.3 A6: 开仓瞬间快照（事后反思基础）

        方向3 扩展：增加 dimension_predictions（每维度方向预测），
        供 ReverseDeriver 逆向推导使用。
        """
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
            "dimension_predictions": dimension_predictions or {},
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

        # ==================================================================
        # 入场侧 REDUCE_WEIGHT 奖励路径（软权重 ±0.01 ess_delta）
        # ==================================================================
        if outcome in ("REDUCE_WEIGHT_CORRECT", "REDUCE_WEIGHT_PREMATURE"):
            count = self._get_reduce_weight_count(cluster_id, ess_id)
            self._incr_reduce_weight_count(cluster_id, ess_id)
            # 冷启动期（样本 < 20）→ 中性，只收集不调整
            if count < self._REDUCE_WEIGHT_WARM_THRESHOLD:
                return {"ess_delta": 0.0, "gmax_mult": 1.0, "cluster_weight_mult": 1.0}
            # warm start: CORRECT → +0.01, PREMATURE → -0.01
            if outcome == "REDUCE_WEIGHT_CORRECT":
                return {"ess_delta": 0.01, "gmax_mult": 1.0, "cluster_weight_mult": 1.0}
            else:
                return {"ess_delta": -0.01, "gmax_mult": 1.0, "cluster_weight_mult": 1.0}

        # PARTIAL_REDUCE 冷启动中性（离场侧 BCRM 反向信号减仓，冷启动只收集不调整）
        if outcome == "PARTIAL_REDUCE":
            count = self._get_reduce_weight_count(cluster_id, ess_id)
            self._incr_reduce_weight_count(cluster_id, ess_id)
            if count < self._REDUCE_WEIGHT_WARM_THRESHOLD:
                return {"ess_delta": 0.0, "gmax_mult": 1.0, "cluster_weight_mult": 1.0}
            # warm start: 减仓盈利 → 小幅 -0.01（过早减仓扣分）
            return {"ess_delta": -0.01, "gmax_mult": 1.0, "cluster_weight_mult": 1.0}

        # CS≥0.9 且 TP（高信心判断准且对）→ 大步长 +0.05
        if cs >= 0.9 and outcome == "TP":
            return {"ess_delta": 0.05, "gmax_mult": 1.0, "cluster_weight_mult": 1.0}

        # 0.7≤CS<0.9 且 TP（中等信心）→ 小步长 +0.02
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

    # --------------------------------------------------------------------------
    # 权重自适应：基于案例库胜率调整组合权重并持久化
    # --------------------------------------------------------------------------
    def _maybe_auto_adjust_weight(self) -> dict[str, Any]:
        """根据事件案例库胜率自动调整基因组合权重并持久化.

        逻辑:
          - 胜率 ≥ 0.6 → 升级权重 ×1.1
          - 胜率 < 0.4 → 降级权重 ×0.9
          - 否则不变
        FAIL-OPEN: case_library/gene_library 缺失时返回空结果，不抛异常.
        """
        result: dict[str, Any] = {"adjusted": 0, "upgraded": 0, "downgraded": 0}
        if self._case_library is None or not self._gene_library:
            return result
        try:
            # 获取案例库胜率
            win_rate = 0.5
            try:
                if hasattr(self._case_library, "get_pattern_winrate"):
                    stats = self._case_library.get_pattern_winrate("event", "hike")
                    win_rate = float(stats.get("win_rate", 0.5))
                elif hasattr(self._case_library, "win_rate"):
                    win_rate = float(self._case_library.win_rate)
            except Exception:
                pass

            # 确定调整因子
            if win_rate >= 0.6:
                factor = 1.1
            elif win_rate < 0.4:
                factor = 0.9
            else:
                factor = 1.0

            if factor == 1.0:
                return result

            # 调整所有组合权重
            combos = self._gene_library.get("combinations", []) or []
            for combo in combos:
                meta = combo.get("meta") or {}
                if not isinstance(meta, dict):
                    continue
                old_weight = float(meta.get("weight", 1.0))
                new_weight = max(0.1, min(2.0, old_weight * factor))
                meta["weight"] = new_weight
                result["adjusted"] += 1
                if factor > 1.0:
                    result["upgraded"] += 1
                else:
                    result["downgraded"] += 1

            # 持久化到 library.json
            try:
                from dreambuddy_evolution.core.strategy_gene import persist_library
                persist_library(self._gene_library)
            except Exception as e:
                logger.debug("[FO] persist_library fail: %s", e)

            return result
        except Exception as e:
            logger.debug("[FO] _maybe_auto_adjust_weight fail: %s", e)
            return result
