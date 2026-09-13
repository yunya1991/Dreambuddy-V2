"""
Phase 3.1: PrimaryContradictionIdentifier — 主要矛盾识别器
SPEC-主要矛盾识别与最小阻力路径设计.md §4.2

核心哲学: 矛盾论 §主要矛盾 + §矛盾主要方面
  - 多路径来源 = 多矛盾维度并行收集
  - 共振检测 = 多矛盾指向同一方向
  - 冲突裁决 = 4维评分法识别主导者
  - 主导性评估 = Wyckoff 因果/量价 + Minervini 趋势延续增强

HC-AGI-18: 异常必须 FAIL-OPEN，返回 neutral 兜底
HC-AGI-23: 至少 2 路径才做矛盾分析，单路径返回 neutral

8 大矛盾维度(C1-C8) → 6 路径来源映射:
  C1 资金面 → bdsm
  C2 情绪面 → trend_following
  C3 技术面 → bcrm
  C4 宏观 → strategic
  C6 时序 → deep_reasoning
  C7 隐性 → synthesized
  C8 宏观交叉 → l2_gene
"""
from __future__ import annotations

import logging
import math
from typing import Any

logger = logging.getLogger(__name__)


class PrimaryContradictionIdentifier:
    """主要矛盾识别器.

    哲学: 矛盾论 §主要矛盾 + §矛盾主要方面
    输入: 6 类路径（对应 C1-C8 矛盾维度）
    输出: primary_contradiction dict
    """

    MIN_PATHS_FOR_ANALYSIS = 2  # HC-AGI-23: 至少 2 路径
    RESONANCE_THRESHOLD = 0.6   # 共振阈值：≥60% 方向一致才算共振
    DOMINANCE_THRESHOLD = 0.55  # 主导阈值：力量对比 > 0.55 才算主导

    # 路径来源 → 矛盾维度映射 (SPEC §2.1)
    SOURCE_DIM_MAP = {
        "bdsm": "C1",
        "trend_following": "C2",
        "grid_trading": "C2",
        "bcrm": "C3",
        "strategic": "C4",
        "deep_reasoning": "C6",
        "synthesized": "C7",
        "l2_gene": "C8",
    }

    # 市场影响权重 (矛盾分析法.md §三 Step2)
    SOURCE_WEIGHT_MAP = {
        "strategic": 0.30,
        "bdsm": 0.25,
        "bcrm": 0.20,
        "trend_following": 0.15,
        "l2_gene": 0.10,
        "deep_reasoning": 0.10,
        "synthesized": 0.10,
    }

    def identify(
        self,
        paths: list[dict] | Any,
        market_data: dict | None = None,
        r_out: dict | None = None,
        weight_factor: float | dict = 1.0,
    ) -> dict:
        """识别主要矛盾.

        三步法：
        1. 共振检测：多路径方向一致 → 矛盾强度高
        2. 冲突裁决：方向冲突时 → 4维评分法识别主导者
        3. 主导性评估：量化 dominance_score + Wyckoff/Minervini 增强

        Args:
            weight_factor: Phase 3.5 验证回流权重因子。
                           float: 全局标量 [0.3, 1.5]（向后兼容）
                           dict: 按维度独立的权重 {dimension: wf}（Fix 3）

        HC-AGI-18: 异常 FAIL-OPEN
        HC-AGI-23: < 2 路径返回 neutral
        """
        try:
            if not isinstance(paths, (list, tuple)) or len(paths) < self.MIN_PATHS_FOR_ANALYSIS:
                return self._neutral_default()

            # Step 1: 共振检测
            resonance = self._detect_resonance(paths)

            # Step 2: 冲突裁决（仅共振 < 阈值时）
            if resonance["score"] < self.RESONANCE_THRESHOLD:
                dominance = self._arbitrate_conflicts(paths, market_data or {}, r_out or {})
            else:
                dominance = resonance  # 共振即主导

            # Step 3: 主导性评估
            primary = self._evaluate_dominance(dominance, paths, market_data or {})

            # Fix 3: 按维度独立取权重（支持 dict 和 float 两种格式）
            _dim = primary.get("dimension", "unknown")
            if isinstance(weight_factor, dict):
                wf = max(0.3, min(1.5, float(weight_factor.get(_dim, 1.0))))
            else:
                wf = max(0.3, min(1.5, float(weight_factor)))
            primary["strength"] = min(1.0, primary["strength"] * wf)

            return primary

        except Exception as e:  # noqa: BLE001  HC-AGI-18
            logger.warning("[FO-AGI][Contradiction] FAIL-OPEN: %s", e)
            return self._neutral_default()

    # ------------------------------------------------------------------
    # Step 1: 共振检测
    # ------------------------------------------------------------------
    def _detect_resonance(self, paths: list[dict]) -> dict:
        """共振检测：多路径方向对立度.

        Fix 4: 矛盾强度 = 对立程度而非一致程度
        - 多空各半（balance≈1.0）→ 矛盾激化 → strength 高
        - 单方压倒（balance≈0.0）→ 共识极强 → strength 低
        - 矛盾论 §矛盾主要方面: 优势方即方向
        """
        long_weight = sum(
            float(p.get("confidence", 0.5))
            for p in paths
            if p.get("direction") == "long"
        )
        short_weight = sum(
            float(p.get("confidence", 0.5))
            for p in paths
            if p.get("direction") == "short"
        )
        total_weight = long_weight + short_weight

        if total_weight <= 0:
            return {"score": 0.0, "direction": "neutral", "strength": 0.0,
                    "consensus_penalty": 0.0}

        if long_weight >= short_weight:
            direction = "long"
            score = long_weight / total_weight
        else:
            direction = "short"
            score = short_weight / total_weight

        # Fix 4: strength = 对立度 × 路径数调制
        # balance = min(L,S)/max(L,S): 1.0=完美对立, 0.0=单方压倒
        _max_w = max(long_weight, short_weight)
        balance = min(long_weight, short_weight) / _max_w if _max_w > 0 else 0.0
        strength = min(1.0, balance * min(1.0, len(paths) / 3.0))

        # consensus_penalty: 共识越强 → 惩罚越大（反拥挤信号）
        # score > 0.8 → 高共识 → penalty > 0; score=1.0 → penalty=1.0
        consensus_penalty = max(0.0, (score - 0.8) / 0.2) if score > 0.8 else 0.0

        return {
            "score": float(score),
            "direction": direction,
            "strength": float(strength),
            # confidence = 对主导方向的置信度（基于共识度，非矛盾强度）
            "confidence": float(score * min(1.0, len(paths) / 3.0)),
            "consensus_penalty": float(consensus_penalty),
        }

    # ------------------------------------------------------------------
    # Step 2: 冲突裁决
    # ------------------------------------------------------------------
    def _arbitrate_conflicts(
        self,
        paths: list[dict],
        market_data: dict,
        r_out: dict,
    ) -> dict:
        """冲突裁决：4维评分法识别主导者.

        矛盾论 A0-IRON-2: 主要矛盾只有一个，4维评分法识别
        维度: 力量对比 + 时间紧迫性 + 证据一致性 + 市场影响权重
        """
        long_paths = [p for p in paths if p.get("direction") == "long"]
        short_paths = [p for p in paths if p.get("direction") == "short"]

        long_score = self._score_side(long_paths)
        short_score = self._score_side(short_paths)

        power_diff = abs(long_score["total"] - short_score["total"])
        if long_score["total"] >= short_score["total"]:
            direction, winner_score = "long", long_score
        else:
            direction, winner_score = "short", short_score

        total = long_score["total"] + short_score["total"]
        confidence = power_diff / total if total > 0 else 0.0

        return {
            "direction": direction,
            "confidence": float(min(1.0, confidence)),
            "strength": float(min(1.0, winner_score["power"])),
            "long_score": long_score,
            "short_score": short_score,
        }

    def _score_side(self, side_paths: list[dict]) -> dict:
        """4维评分: 力量对比 + 时间紧迫性 + 证据一致性 + 市场影响权重.

        对齐 矛盾分析法.md §三 Step2
        """
        if not side_paths:
            return {"power": 0.0, "time": 0.0, "consistency": 0.0,
                    "market_weight": 0.0, "total": 0.0}

        # 力量对比: Σ(confidence × expected_return)
        power = sum(
            float(p.get("confidence", 0.5)) * float(p.get("expected_return", 0.0))
            for p in side_paths
        )

        # 时间紧迫性: 短期信号(bcrm/bdsm)权重高
        time_urgency = sum(
            1.0 if p.get("source") in ("bcrm", "bdsm") else 0.5
            for p in side_paths
        )

        # 证据一致性: 同向路径数占比
        consistency = len(side_paths) / max(1, len(side_paths) + 1)

        # 市场影响权重
        market_weight = sum(
            self.SOURCE_WEIGHT_MAP.get(p.get("source", ""), 0.05)
            for p in side_paths
        )

        total = (
            power * 0.40
            + time_urgency * 0.15
            + consistency * 0.25
            + market_weight * 0.20
        )

        return {
            "power": float(power),
            "time": float(time_urgency),
            "consistency": float(consistency),
            "market_weight": float(market_weight),
            "total": float(total),
        }

    # ------------------------------------------------------------------
    # Step 3: 主导性评估
    # ------------------------------------------------------------------
    def _evaluate_dominance(
        self,
        dominance: dict,
        paths: list[dict],
        market_data: dict,
    ) -> dict:
        """主导性评估 + Wyckoff/Minervini 指标融合."""
        # Wyckoff Cause & Effect（累积期长度→后续行情规模）
        cause_score = self._compute_cause_score(market_data)

        # Wyckoff Effort vs Result（量价背离检测）
        effort_result = self._compute_effort_result_ratio(market_data)

        # Minervini 趋势模板 + VCP
        continuation = self._compute_continuation_score(market_data, dominance["direction"])

        # 综合强度 = 基础矛盾强度 × (1 + 因果加成 + 量价加成 + 趋势延续加成)
        base_strength = float(dominance.get("strength", 0.0))
        enhanced = base_strength * (
            1.0 + 0.2 * cause_score + 0.2 * effort_result + 0.3 * continuation
        )
        enhanced = min(1.0, max(0.0, enhanced))  # [0, 1] 截断

        # 矛盾维度识别：权重最高路径的来源 → 映射 C1-C8
        dimension = self._identify_dimension(paths)

        return {
            "dimension": dimension,
            "direction": dominance["direction"],
            "strength": float(enhanced),
            "confidence": float(dominance.get("confidence", 0.0)),
            "cause_score": float(cause_score),
            "effort_result": float(effort_result),
            "continuation_score": float(continuation),
        }

    def _identify_dimension(self, paths: list[dict]) -> str:
        """识别主要矛盾维度: 置信度最高路径的来源 → C1-C8."""
        if not paths:
            return "C3"
        primary_path = max(paths, key=lambda p: float(p.get("confidence", 0.0)))
        source = primary_path.get("source", "bcrm")
        return self.SOURCE_DIM_MAP.get(source, "C3")

    # ------------------------------------------------------------------
    # Wyckoff / Minervini 指标 (简化版, Phase 3.2 TrendContinuationScorer 扩展)
    # ------------------------------------------------------------------
    def _compute_cause_score(self, market_data: dict) -> float:
        """Wyckoff Cause & Effect: 累积期标准化时长 → 后续行情规模.

        标准化: 20-60 bars 累积期 → 0.5-1.0
        """
        try:
            kline = market_data.get("kline_data", {})
            if not isinstance(kline, dict):
                return 0.5
            consolidation_bars = float(kline.get("consolidation_bars", 0))
            return float(min(1.0, max(0.0, (consolidation_bars - 10) / 50)))
        except Exception:  # noqa: BLE001
            return 0.5

    def _compute_effort_result_ratio(self, market_data: dict) -> float:
        """Wyckoff Effort vs Result: 量价背离检测.

        量价同向 → 0.8 (机构行为一致)
        量价背离 → 0.3 (机构吸筹/派发)
        """
        try:
            kline = market_data.get("kline_data", {})
            if not isinstance(kline, dict):
                return 0.5
            vol_change = float(kline.get("volume_change_pct", 0))
            price_change = float(kline.get("price_change_pct", 0))
            if abs(price_change) < 1e-9:
                return 0.5
            if (vol_change > 0) == (price_change > 0):
                return 0.8
            return 0.3
        except Exception:  # noqa: BLE001
            return 0.5

    def _compute_continuation_score(self, market_data: dict, direction: str) -> float:
        """Minervini 趋势模板 (8 条件) + VCP 收缩比.

        简化版: 检查 kline_data 中的均线排列
        Phase 3.2 TrendContinuationScorer 会提供完整实现

        HC-AGI-20: 趋势字段全部缺失时取 0.5 中性兜底
        """
        try:
            kline = market_data.get("kline_data", {})
            if not isinstance(kline, dict):
                return 0.5

            # HC-AGI-20: 趋势延续性字段全部缺失 → 中性 0.5
            trend_fields = ("price", "ma50", "ma150", "ma200", "ma200_slope",
                            "low_52w", "high_52w", "contractions")
            if not any(f in kline for f in trend_fields):
                return 0.5

            price = float(kline.get("price", 0))
            ma50 = float(kline.get("ma50", 0))
            ma150 = float(kline.get("ma150", 0))
            ma200 = float(kline.get("ma200", 0))
            ma200_slope = float(kline.get("ma200_slope", 0))

            passed = 0
            if price > 0 and ma150 > 0 and price > ma150:
                passed += 1
            if price > 0 and ma200 > 0 and price > ma200:
                passed += 1
            if ma150 > 0 and ma200 > 0 and ma150 > ma200:
                passed += 1
            if ma200_slope > 0:
                passed += 1
            if ma50 > 0 and ma150 > 0 and ma50 > ma150:
                passed += 1
            if price > 0 and ma50 > 0 and price > ma50:
                passed += 1
            # 52周区间检查 (简化)
            low_52w = float(kline.get("low_52w", 0))
            high_52w = float(kline.get("high_52w", 0))
            if low_52w > 0 and price >= low_52w * 1.25:
                passed += 1
            if high_52w > 0 and price <= high_52w * 1.25:
                passed += 1

            template_score = passed / 8.0

            # VCP 收缩比
            vcp_score = self._vcp_contraction(kline)

            return float(template_score * 0.6 + vcp_score * 0.4)
        except Exception:  # noqa: BLE001
            return 0.5

    def _vcp_contraction(self, kline: dict) -> float:
        """VCP: T2/T1 ≤ 0.75, T3/T2 ≤ 0.75 → 1.0."""
        contractions = kline.get("contractions", [])
        if not isinstance(contractions, (list, tuple)) or len(contractions) < 2:
            return 0.5
        try:
            ratios = []
            for i in range(1, len(contractions)):
                prev = float(contractions[i - 1])
                curr = float(contractions[i])
                if prev > 0:
                    r = curr / prev
                    ratios.append(1.0 if r <= 0.75 else max(0.0, 1.0 - (r - 0.75)))
            return float(sum(ratios) / len(ratios)) if ratios else 0.5
        except (TypeError, ValueError, ZeroDivisionError):
            return 0.5

    # ------------------------------------------------------------------
    # FAIL-OPEN 兜底
    # ------------------------------------------------------------------
    def _neutral_default(self) -> dict:
        """HC-AGI-18: FAIL-OPEN neutral 兜底."""
        return {
            "dimension": "C3",
            "direction": "neutral",
            "strength": 0.0,
            "confidence": 0.0,
            "cause_score": 0.5,
            "effort_result": 0.5,
            "continuation_score": 0.5,
        }
