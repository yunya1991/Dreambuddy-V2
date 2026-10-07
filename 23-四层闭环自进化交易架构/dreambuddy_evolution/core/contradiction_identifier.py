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

import json
import logging
import math
import os
import time
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)


class ContradictionWeightLearner:
    """W6: 深度学习驱动矛盾权重 — 自动样本累积 + 延迟标注 + 阈值触发.

    工作流:
    1. 每次 identify() 记录 4 维分数 + 方向 (未标注样本)
    2. 下次调用时用实际收益标注上一个样本 (延迟标注)
    3. 标注样本 ≥ MIN_SAMPLES → 自动触发最小二乘权重学习
    4. 学到的权重替代硬编码 0.40/0.15/0.25/0.20

    FAIL-OPEN: 学习失败或不满足条件 → 使用硬编码默认权重
    """

    MIN_SAMPLES = 500  # 最少标注样本数
    DEFAULT_WEIGHTS = np.array([0.40, 0.15, 0.25, 0.20])  # power, time, consistency, market_weight
    LEARNING_INTERVAL = 86400  # 每 24h 最多学一次

    def __init__(self, storage_path: str | None = None):
        self._storage_path = storage_path or os.path.join(
            os.path.dirname(__file__), "..", "data", "contradiction_samples.json"
        )
        self._samples: list[dict] = []
        self._learned_weights: np.ndarray | None = None
        self._last_learn_ts: float = 0.0
        self._load()

    def _load(self) -> None:
        """从磁盘加载历史样本和已学权重."""
        try:
            if os.path.exists(self._storage_path):
                with open(self._storage_path, "r") as f:
                    data = json.load(f)
                self._samples = data.get("samples", [])
                w = data.get("learned_weights")
                if w and len(w) == 4:
                    self._learned_weights = np.array(w)
                self._last_learn_ts = float(data.get("last_learn_ts", 0.0))
                logger.info(
                    "[W6] loaded %d samples, weights=%s",
                    len(self._samples),
                    self._learned_weights,
                )
        except Exception as e:
            logger.debug("[W6] load FAIL-OPEN: %s", e)

    def _save(self) -> None:
        """持久化样本和权重到磁盘."""
        try:
            os.makedirs(os.path.dirname(self._storage_path), exist_ok=True)
            with open(self._storage_path, "w") as f:
                json.dump({
                    "samples": self._samples[-2000:],  # 只保留最近 2000 条
                    "learned_weights": self._learned_weights.tolist() if self._learned_weights is not None else None,
                    "last_learn_ts": self._last_learn_ts,
                }, f)
        except Exception as e:
            logger.debug("[W6] save FAIL-OPEN: %s", e)

    def record_prediction(
        self,
        scores: dict,
        direction: str,
        confidence: float,
        timestamp: float | None = None,
    ) -> None:
        """记录一次矛盾识别的 4 维分数（未标注）."""
        ts = timestamp or time.time()
        self._samples.append({
            "ts": ts,
            "power": float(scores.get("power", 0.0)),
            "time": float(scores.get("time", 0.0)),
            "consistency": float(scores.get("consistency", 0.0)),
            "market_weight": float(scores.get("market_weight", 0.0)),
            "direction": direction,
            "confidence": confidence,
            "actual_return": None,  # 延迟标注
        })
        if len(self._samples) % 100 == 0:
            self._save()

    def label_previous(self, actual_return: float) -> None:
        """用实际收益标注最近一个未标注样本."""
        for s in reversed(self._samples):
            if s.get("actual_return") is None:
                s["actual_return"] = float(actual_return)
                break
        # 有新标注 → 尝试学习
        self._try_learn()

    def _try_learn(self) -> None:
        """标注样本 ≥ MIN_SAMPLES 且距上次学习 > 24h → 自动学习."""
        labeled = [s for s in self._samples if s.get("actual_return") is not None]
        if len(labeled) < self.MIN_SAMPLES:
            return
        now = time.time()
        if now - self._last_learn_ts < self.LEARNING_INTERVAL:
            return
        try:
            # X: 4 维分数, y: actual_return
            X = np.array([
                [s["power"], s["time"], s["consistency"], s["market_weight"]]
                for s in labeled
            ])
            y = np.array([s["actual_return"] for s in labeled])
            # 最小二乘: w = (X^T X)^-1 X^T y
            # 加 L2 正则防止过拟合
            XtX = X.T @ X
            ridge = 0.01 * np.eye(4)
            w = np.linalg.solve(XtX + ridge, X.T @ y)
            # 归一化到 [0, 1]，保证 sum=1
            w_abs = np.abs(w)
            w_sum = w_abs.sum()
            if w_sum > 0:
                w_norm = w_abs / w_sum
            else:
                w_norm = self.DEFAULT_WEIGHTS
            # 平滑过渡：新权重 = 0.7 * 学习权重 + 0.3 * 默认权重
            self._learned_weights = 0.7 * w_norm + 0.3 * self.DEFAULT_WEIGHTS
            self._last_learn_ts = now
            logger.info(
                "[W6] auto-learned weights: %s (from %d samples)",
                self._learned_weights,
                len(labeled),
            )
            self._save()
        except Exception as e:
            logger.warning("[W6] weight learning failed, using defaults: %s", e)

    def get_weights(self) -> np.ndarray:
        """获取当前权重（学习到的或默认的）."""
        if self._learned_weights is not None:
            return self._learned_weights
        return self.DEFAULT_WEIGHTS

    @property
    def is_active(self) -> bool:
        """是否已自动激活（学习到权重）."""
        return self._learned_weights is not None

    @property
    def labeled_count(self) -> int:
        """已标注样本数."""
        return sum(1 for s in self._samples if s.get("actual_return") is not None)


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

    def __init__(self, weight_learner: ContradictionWeightLearner | None = None):
        """W6: 注入权重学习器（可选，None 时创建默认实例）."""
        self._weight_learner = weight_learner or ContradictionWeightLearner()

    def identify(
        self,
        paths: list[dict] | Any,
        market_data: dict | None = None,
        r_out: dict | None = None,
        weight_factor: float | dict = 1.0,
        causal_engine=None,
        meta_cognition_gate=None,
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
            causal_engine: W4 CausalEngine 实例，用于因果 ATE 增强"力量对比"维度
            meta_cognition_gate: W5 MetaCognitionGate 实例，用于二阶校验 confidence

        HC-AGI-18: 异常 FAIL-OPEN
        HC-AGI-23: < 2 路径返回 neutral
        """
        try:
            if not isinstance(paths, (list, tuple)) or len(paths) < self.MIN_PATHS_FOR_ANALYSIS:
                return self._neutral_default()

            # W6: 延迟标注 — 用上次预测后的实际收益标注上一个样本
            self._label_previous_from_market(market_data)

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

            # W4: CausalEngine ATE 增强 — 因果显著性调整力量评分
            primary = self._enhance_with_causal_ate(primary, paths, market_data, causal_engine)

            # W5: MetaCognitionGate 二阶校验
            primary = self._meta_cognition_verify(primary, meta_cognition_gate, market_data)

            # W6: 记录本次预测的 4 维分数（待下次延迟标注）
            self._record_from_primary(primary, dominance)

            return primary

        except Exception as e:  # noqa: BLE001  HC-AGI-18
            logger.warning("[FO-AGI][Contradiction] FAIL-OPEN: %s", e)
            return self._neutral_default()

    def _label_previous_from_market(self, market_data: dict | None) -> None:
        """W6: 从 market_data 提取实际收益标注上一个未标注样本."""
        try:
            if not market_data:
                return
            # 优先用 close 序列的最近变动作为 actual_return
            closes = market_data.get("close") or market_data.get("closes")
            if closes and isinstance(closes, (list, tuple)) and len(closes) >= 2:
                prev_close = float(closes[-2])
                curr_close = float(closes[-1])
                if prev_close > 0:
                    actual_return = (curr_close - prev_close) / prev_close
                    self._weight_learner.label_previous(actual_return)
                    return
            # 备用: 直接用 change_pct 字段
            chg = market_data.get("change_pct")
            if chg is not None:
                self._weight_learner.label_previous(float(chg) / 100.0)
        except Exception as e:
            logger.debug("[W6] label_previous FAIL-OPEN: %s", e)

    def _record_from_primary(self, primary: dict, dominance: dict) -> None:
        """W6: 从矛盾识别结果提取 4 维分数并记录."""
        try:
            direction = primary.get("direction", "neutral")
            confidence = float(primary.get("confidence", 0.5))
            # 从 dominance 提取 long_score/short_score（冲突裁决路径）
            if "long_score" in dominance:
                winner = dominance.get("long_score" if direction == "long" else "short_score", {})
            else:
                # 共振路径: 构造简化 scores
                winner = {
                    "power": float(primary.get("strength", 0.5)),
                    "time": 1.0,
                    "consistency": 1.0,
                    "market_weight": 0.15,
                }
            self._weight_learner.record_prediction(winner, direction, confidence)
        except Exception as e:
            logger.debug("[W6] record_prediction FAIL-OPEN: %s", e)

    def _enhance_with_causal_ate(
        self,
        primary: dict,
        paths: list[dict],
        market_data: dict | None,
        causal_engine,
    ) -> dict:
        """W4: 用 CausalEngine ATE 因果效应增强矛盾力量评分.

        当 ATE 显著且方向一致时提升 power，不显著时衰减。
        FAIL-OPEN: causal_engine=None 或 ATE 估计失败 → 不调整。
        """
        try:
            if causal_engine is None:
                return primary
            from dreambuddy_evolution.agi_config import get_switch
            if not get_switch("enable_causal_engine", False):
                return primary
            import numpy as np
            # 构造简化 ATE 输入：用路径 confidence 作为 treatment，expected_return 作为 y
            confidences = np.array([float(p.get("confidence", 0.5)) for p in paths])
            returns = np.array([float(p.get("expected_return", 0.0)) for p in paths])
            # treatment: 高 confidence vs 低 confidence (中位数分割)
            median_conf = np.median(confidences) if len(confidences) > 0 else 0.5
            treatment = (confidences > median_conf).astype(np.int32)
            X = confidences.reshape(-1, 1)
            ate_result = causal_engine.estimate_ate(X, treatment, returns, method="dml")
            primary["causal_ate"] = ate_result
            # 调整 strength：ATE 显著且同方向 → 增强，不显著 → 轻微衰减
            ate = float(ate_result.get("ate", 0.0))
            significant = ate_result.get("significant", False)
            base_strength = float(primary.get("strength", 0.5))
            if significant and abs(ate) > 1e-6:
                # ATE 同方向 → 增强
                direction = primary.get("direction", "neutral")
                if (direction == "long" and ate > 0) or (direction == "short" and ate < 0):
                    primary["strength"] = min(1.0, base_strength * 1.15)
                else:
                    primary["strength"] = max(0.0, base_strength * 0.85)
            elif not significant:
                # ATE 不显著 → 轻微衰减
                primary["strength"] = max(0.0, base_strength * 0.95)
            return primary
        except Exception as e:
            logger.debug("[W4] causal ATE enhancement FAIL-OPEN: %s", e)
            return primary

    def _meta_cognition_verify(
        self,
        primary: dict,
        meta_cognition_gate,
        market_data: dict | None,
    ) -> dict:
        """W5: MetaCognitionGate 对矛盾识别结果做二阶校验.

        当 uncertainty > 0.4 时降低 confidence（HC-AGI-06）。
        FAIL-OPEN: gate=None 或 evaluate 失败 → 原始 confidence 不变。
        """
        try:
            if meta_cognition_gate is None:
                return primary
            from dreambuddy_evolution.agi_config import get_switch
            if not get_switch("enable_meta_cognition", False):
                return primary
            original_conf = float(primary.get("confidence", 0.5))
            context = {
                "direction": primary.get("direction", "neutral"),
                "dimension": primary.get("dimension", "unknown"),
                "market_data": market_data or {},
            }
            mc_result = meta_cognition_gate.evaluate(original_conf, context)
            primary["meta_cognition"] = mc_result
            adjusted_conf = float(mc_result.get("adjusted_confidence", original_conf))
            uncertainty = float(mc_result.get("uncertainty", 0.0))
            # HC-AGI-06: uncertainty > 0.4 → 强制降仓位
            if uncertainty > 0.4:
                primary["confidence"] = max(0.0, adjusted_conf * 0.5)
                primary["position_multiplier"] = 0.5
            else:
                primary["confidence"] = adjusted_conf
                primary["position_multiplier"] = 1.0
            return primary
        except Exception as e:
            logger.debug("[W5] meta cognition verify FAIL-OPEN: %s", e)
            return primary

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

        # W6: 使用学习到的权重（自动激活）或硬编码默认值
        _w = self._weight_learner.get_weights()
        total = (
            power * float(_w[0])
            + time_urgency * float(_w[1])
            + consistency * float(_w[2])
            + market_weight * float(_w[3])
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
