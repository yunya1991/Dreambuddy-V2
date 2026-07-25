#!/usr/bin/env python3
"""
五角校验器 — BCRM2(ML) × 力学引擎(物理) × A0(矛盾) × Ising(相变) × TDA(拓扑) 交叉验证。

核心思想：
    五个独立推理源各给出方向判断，通过投票/加权/分歧检测，
    生成最终置信度调整和风险预警。

五角校验逻辑：
    1. 五源方向一致 → 强信号，置信度增强
    2. 多数一致少数分歧 → 中信号，置信度略降 + 预警
    3. 严重分歧 → 弱信号，置信度大幅降低 + fail_closed 候选

预警机制：
    - 力学引擎反转预警 + A0 矛盾张力 → 强反转预警
    - Ising 相变预警(能量突变/临界相) → 趋势衰竭预警
    - TDA 拓扑突变预警(Betti突增/瓶颈距离) → 转折最早预警（拓扑先于动力学）
"""
from dataclasses import dataclass, field
from typing import Dict, Optional, Any, List
import logging
import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class TriangleVerificationResult:
    """五角校验结果（保留类名向后兼容）"""
    # 五源方向 (-1=空, 0=中性, +1=多)
    bcrm2_direction: int = 0
    force_direction: int = 0
    a0_direction: int = 0
    ising_direction: int = 0        # Ising相变方向（P1新增）
    tda_direction: int = 0          # TDA拓扑方向（P2新增）

    # 校验结果
    agreement_score: float = 0.0     # 一致性得分 0-1
    confidence_adjustment: float = 0.0  # 置信度调整 -0.2~+0.2
    reversal_alert: bool = False     # 强反转预警
    reversal_strength: float = 0.0   # 反转强度
    risk_warnings: List[str] = field(default_factory=list)
    should_fail_closed: bool = False  # 是否建议 fail_closed

    # 各源详情
    force_result_dict: Optional[dict] = None
    ising_result_dict: Optional[dict] = None
    tda_result_dict: Optional[dict] = None  # TDA拓扑详情（P2新增）

    # 校验模式
    verdict: str = ""  # STRONG_AGREE / MAJORITY_AGREE / DIVERGENT / CONFLICT

    # P3预警联动策略（新增）
    position_factor: float = 1.0     # 仓位系数（1.0=正常, 0.5=降仓50%, 0=空仓）
    sl_tighten_factor: float = 1.0   # 止损收紧系数（1.0=正常, 0.6=收紧40%）
    early_exit_signal: bool = False  # 提前退出信号（TDA+Ising双重预警）

    def to_dict(self) -> dict:
        return {
            "bcrm2_direction": self.bcrm2_direction,
            "force_direction": self.force_direction,
            "a0_direction": self.a0_direction,
            "ising_direction": self.ising_direction,
            "tda_direction": self.tda_direction,
            "agreement_score": round(self.agreement_score, 4),
            "confidence_adjustment": round(self.confidence_adjustment, 4),
            "reversal_alert": self.reversal_alert,
            "reversal_strength": round(self.reversal_strength, 4),
            "risk_warnings": self.risk_warnings,
            "should_fail_closed": self.should_fail_closed,
            "force_result": self.force_result_dict,
            "ising_result": self.ising_result_dict,
            "tda_result": self.tda_result_dict,
            "verdict": self.verdict,
            "position_factor": round(self.position_factor, 2),
            "sl_tighten_factor": round(self.sl_tighten_factor, 2),
            "early_exit_signal": self.early_exit_signal,
        }


class TriangleVerifier:
    """五角校验器：BCRM2 × 力学引擎 × A0 × Ising相变 × TDA拓扑"""

    def __init__(self):
        self._force_engine = None
        self._ising_detector = None
        self._tda_detector = None
        self._init_force_engine()
        self._init_ising_detector()
        self._init_tda_detector()

    def _init_force_engine(self):
        """延迟初始化力学引擎"""
        try:
            from scripts.memory_l4.bcrm.force_engine import ForceEngine
            self._force_engine = ForceEngine()
            logger.info("[五角校验] 力学引擎已加载")
        except Exception as e:
            logger.warning(f"[五角校验] 力学引擎加载失败: {e}")

    def _init_ising_detector(self):
        """延迟初始化Ising相变检测器"""
        try:
            from scripts.memory_l4.bcrm.ising_phase_detector import IsingPhaseDetector
            self._ising_detector = IsingPhaseDetector()
            logger.info("[五角校验] Ising相变检测器已加载")
        except Exception as e:
            logger.warning(f"[五角校验] Ising相变检测器加载失败: {e}")

    def _init_tda_detector(self):
        """延迟初始化TDA拓扑检测器（P2新增）"""
        try:
            from scripts.memory_l4.bcrm.tda_early_warning import TDAEarlyWarning
            self._tda_detector = TDAEarlyWarning()
            logger.info("[五角校验] TDA拓扑检测器已加载")
        except Exception as e:
            logger.warning(f"[五角校验] TDA拓扑检测器加载失败: {e}")

    def verify(
        self,
        bcrm2_direction: str,
        bcrm2_confidence: float,
        a0_result_dict: Optional[dict],
        market_snapshot: Dict[str, Any],
        df: Optional["pd.DataFrame"] = None,
    ) -> TriangleVerificationResult:
        """
        执行三角校验。

        Args:
            bcrm2_direction: BCRM2 方向 "UP"/"DOWN"/"FLAT"
            bcrm2_confidence: BCRM2 置信度
            a0_result_dict: A0 分析结果字典
            market_snapshot: 市场快照（供力学引擎使用）
            df: K线数据（供力学引擎提取特征）
        """
        result = TriangleVerificationResult()

        # BCRM2 方向
        result.bcrm2_direction = self._dir_str_to_int(bcrm2_direction)

        # A0 方向
        if a0_result_dict:
            bias = a0_result_dict.get("direction_bias", 0)
            result.a0_direction = 1 if bias > 0.1 else (-1 if bias < -0.1 else 0)
        else:
            result.a0_direction = 0

        # 力学引擎方向
        result.force_direction, force_reversal, force_strength, force_dict = \
            self._run_force_engine(market_snapshot, df)
        result.force_result_dict = force_dict

        # Ising相变方向（第四源）
        result.ising_direction, ising_alert, ising_phase, ising_dict = \
            self._run_ising_detector(market_snapshot, df)
        result.ising_result_dict = ising_dict

        # TDA拓扑方向（第五源，P2新增）
        result.tda_direction, tda_warning, tda_strength, tda_dict = \
            self._run_tda_detector(market_snapshot, df)
        result.tda_result_dict = tda_dict

        # 一致性评分（五源）
        directions = [result.bcrm2_direction, result.force_direction,
                      result.a0_direction, result.ising_direction,
                      result.tda_direction]
        result.agreement_score = self._compute_agreement(directions)

        # 置信度调整
        result.confidence_adjustment = self._compute_adjustment(
            result.agreement_score, directions, bcrm2_confidence
        )

        # 反转预警：力学减速 + A0 高张力
        a0_tension = a0_result_dict.get("overall_tension", 0) if a0_result_dict else 0
        if force_reversal and a0_tension > 0.5:
            result.reversal_alert = True
            result.reversal_strength = min(
                force_strength * 0.5 + a0_tension * 0.5, 1.0
            )
            result.risk_warnings.append(
                f"强反转预警：力学减速(强度={force_strength:.2f}) + "
                f"A0高张力({a0_tension:.2f})"
            )
            # 反转预警削弱当前方向置信度
            result.confidence_adjustment -= 0.1 * result.reversal_strength

        # Ising相变预警（P1新增）
        if ising_alert:
            ising_phase_str = ising_phase or "UNKNOWN"
            result.risk_warnings.append(
                f"Ising相变预警：相态={ising_phase_str}，市场可能发生牛熊转换"
            )
            # 相变预警削弱置信度
            result.confidence_adjustment -= 0.08

        # TDA拓扑突变预警（P2新增，最早转折信号）
        if tda_warning:
            result.risk_warnings.append(
                f"TDA拓扑突变预警：强度={tda_strength:.2f}，"
                f"拓扑结构变化领先于动力学转折"
            )
            # TDA预警削弱置信度（拓扑突变是最早信号，权重适中）
            result.confidence_adjustment -= 0.06 * tda_strength

        # P3预警联动策略：TDA+Ising双重预警 → 提前降仓+收紧止损
        # 逻辑：TDA（最早信号）+ Ising（中期信号）同时触发，说明趋势反转概率极高
        if tda_warning and ising_alert:
            result.early_exit_signal = True
            # 双重预警：降仓50%，止损收紧40%
            result.position_factor = 0.5
            result.sl_tighten_factor = 0.6
            result.risk_warnings.append(
                f"P3双重预警联动：TDA(强度={tda_strength:.2f}) + Ising(相态={ising_phase or 'UNKNOWN'})，"
                f"建议降仓至50%，止损收紧至60%"
            )
            # 双重预警大幅削弱置信度
            result.confidence_adjustment -= 0.15
        elif tda_warning or ising_alert:
            # 单一预警：轻微降仓，轻微收紧止损
            result.position_factor = 0.8
            result.sl_tighten_factor = 0.9
            if tda_warning:
                result.risk_warnings.append(f"TDA预警：建议降仓至80%")
            if ising_alert:
                result.risk_warnings.append(f"Ising预警：建议止损收紧至90%")
            result.confidence_adjustment -= 0.03

        # 力学引擎创伤重置：A0 创伤信号 → 重置力学速度
        if a0_result_dict and a0_result_dict.get("trauma_signal", False):
            if self._force_engine:
                self._force_engine.reset_velocity()
                result.risk_warnings.append("创伤信号：力学引擎速度已重置，打破惯性")

        # 判定校验模式
        result.verdict = self._determine_verdict(directions, result.agreement_score)

        # 极端分歧 → 建议 fail_closed
        if result.agreement_score < 0.34:
            result.should_fail_closed = True
            result.risk_warnings.append(
                "五源严重分歧，建议 fail_closed"
            )

        if result.risk_warnings:
            logger.debug(f"[五角校验] {result.verdict}: {result.risk_warnings}")
        logger.info(
            f"[五角校验] {result.verdict} "
            f"BCRM2={result.bcrm2_direction:+d} 力学={result.force_direction:+d} "
            f"A0={result.a0_direction:+d} Ising={result.ising_direction:+d} "
            f"TDA={result.tda_direction:+d} "
            f"一致性={result.agreement_score:.0%} "
            f"调整={result.confidence_adjustment:+.4f}"
        )

        return result

    # ================================================================
    # 力学引擎执行
    # ================================================================
    def _run_force_engine(self, snapshot: Dict, df=None):
        """运行力学引擎，返回 (方向, 反转预警, 趋势强度, 结果字典)"""
        if self._force_engine is None:
            return 0, False, 0.0, None

        try:
            # 从 df 补充快照数据
            if df is not None and len(df) >= 50:
                snapshot = self._enrich_snapshot(snapshot, df)

            force_result = self._force_engine.infer(snapshot)

            direction = 0
            if force_result.direction == "UP":
                direction = 1
            elif force_result.direction == "DOWN":
                direction = -1

            return (
                direction,
                force_result.reversal_warning,
                force_result.trend_strength,
                force_result.to_dict(),
            )
        except Exception as e:
            logger.warning(f"[四角校验] 力学引擎执行失败: {e}")
            return 0, False, 0.0, None

    # ================================================================
    # Ising相变检测执行（P1新增）
    # ================================================================
    def _run_ising_detector(self, snapshot: Dict, df=None):
        """
        运行Ising相变检测。

        Returns:
            (方向, 相变预警, 相态, 结果字典)
            方向: -1=空, 0=中性, +1=多
            相变预警: bool（能量突变 或 临界相）
            相态: "ORDERED"/"DISORDERED"/"CRITICAL"/"UNKNOWN"
        """
        if self._ising_detector is None:
            return 0, False, "UNKNOWN", None

        try:
            # 从df提取收益率序列
            returns = None
            volatility = float(snapshot.get("volatility", 0.03))

            if df is not None and len(df) >= 20:
                import numpy as np
                closes = df["close"].values.astype(float)
                if len(closes) >= 2:
                    returns = np.diff(np.log(closes[-100:]))  # 最近100根K线收益
                    returns = returns[~np.isnan(returns)]
                    # 更新波动率
                    if len(returns) > 1:
                        volatility = float(np.std(returns[-20:])) if len(returns) >= 20 else float(np.std(returns))

            if returns is None or len(returns) < 5:
                return 0, False, "UNKNOWN", None

            ising_result = self._ising_detector.detect(returns, volatility)

            # 方向转换
            direction = 0
            if ising_result.direction == "UP":
                direction = 1
            elif ising_result.direction == "DOWN":
                direction = -1

            # 相变预警：能量突变 或 临界相
            alert = ising_result.phase_transition_alert or ising_result.phase == "CRITICAL"

            return (
                direction,
                alert,
                ising_result.phase,
                ising_result.to_dict(),
            )
        except Exception as e:
            logger.warning(f"[五角校验] Ising相变检测失败: {e}")
            return 0, False, "UNKNOWN", None

    # ================================================================
    # TDA拓扑检测执行（P2新增）
    # ================================================================
    def _run_tda_detector(self, snapshot: Dict, df=None):
        """
        运行TDA拓扑检测。

        Returns:
            (方向, 拓扑预警, 预警强度, 结果字典)
            方向: -1=空, 0=中性, +1=多
            拓扑预警: bool（Betti突增 或 瓶颈距离突增）
            预警强度: [0, 1]
        """
        if self._tda_detector is None:
            return 0, False, 0.0, None

        try:
            # 从df提取价格序列
            price_series = None
            if df is not None and len(df) >= 30:
                closes = df["close"].values.astype(float)
                price_series = closes[-100:] if len(closes) >= 100 else closes

            if price_series is None or len(price_series) < 25:
                return 0, False, 0.0, None

            tda_result = self._tda_detector.detect(price_series)

            # 数据不足时跳过
            if not tda_result.has_sufficient_data:
                return 0, False, 0.0, tda_result.to_dict()

            # 方向转换
            direction = 0
            if tda_result.direction == "UP":
                direction = 1
            elif tda_result.direction == "DOWN":
                direction = -1

            return (
                direction,
                tda_result.early_warning,
                tda_result.warning_strength,
                tda_result.to_dict(),
            )
        except Exception as e:
            logger.warning(f"[五角校验] TDA拓扑检测失败: {e}")
            return 0, False, 0.0, None

    def _enrich_snapshot(self, snapshot: Dict, df) -> Dict:
        """从 K线数据补充力学引擎需要的快照字段"""
        import numpy as np
        closes = df["close"].values.astype(float)
        volumes = df["volume"].values.astype(float) if "volume" in df else np.ones(len(closes))

        if len(closes) < 50:
            return snapshot

        # 技术评分
        ma_short = np.mean(closes[-5:])
        ma_mid = np.mean(closes[-20:])
        ma_long = np.mean(closes[-50:])
        tech_score = 0.5 + (ma_short - ma_mid) / max(abs(ma_mid), 1) * 5
        tech_score = max(0, min(1, tech_score))

        # 价格位置
        recent_high = np.max(closes[-50:])
        recent_low = np.min(closes[-50:])
        price_position = (closes[-1] - recent_low) / max(recent_high - recent_low, 1e-8)

        # RSI
        deltas = np.diff(closes[-15:])
        gains = np.where(deltas > 0, deltas, 0)
        losses = np.where(deltas < 0, -deltas, 0)
        avg_gain = np.mean(gains) if len(gains) > 0 else 0
        avg_loss = np.mean(losses) if len(losses) > 0 else 0
        rsi = 100 - 100 / (1 + (avg_gain / max(avg_loss, 1e-8))) if avg_loss > 0 else 100

        # 波动率
        returns = np.diff(np.log(closes[-20:]))
        volatility = float(np.std(returns)) if len(returns) > 1 else 0.02

        # 均线方向
        ma_direction = 0
        if len(closes) >= 5:
            ma_direction = (np.mean(closes[-5:]) - np.mean(closes[-10:])) / max(abs(np.mean(closes[-10:])), 1)

        # 量比
        vol_ratio = 1.0
        if len(volumes) >= 20:
            vol_ratio = volumes[-1] / max(np.mean(volumes[-20:]), 1e-8)

        # 补充快照
        enriched = snapshot.copy()
        enriched.setdefault("technical_score", tech_score)
        enriched.setdefault("price_position", price_position)
        enriched.setdefault("rsi", rsi)
        enriched.setdefault("volatility", volatility)
        enriched.setdefault("ma_direction", ma_direction)
        enriched.setdefault("macd_signal", ma_direction * 0.8)
        enriched.setdefault("volume_ratio", vol_ratio)

        # 内驱力维度（如果没有）
        enriched.setdefault("supply_demand_score", 0.5 + (vol_ratio - 1) * 0.1)
        enriched.setdefault("capital_flow_score", 0.5 + ma_direction * 2)
        enriched.setdefault("sentiment_score", 0.5 + (rsi - 50) / 100)

        # 周期位置（如果没有）
        enriched.setdefault("long_cycle_position", 0.5 + (closes[-1] - ma_long) / max(abs(ma_long), 1) * 3)
        enriched.setdefault("mid_cycle_position", price_position)
        enriched.setdefault("short_cycle_position", 0.5 + (ma_short - ma_mid) / max(abs(ma_mid), 1) * 3)
        enriched.setdefault("trend_strength", abs(ma_direction) * 10)

        return enriched

    # ================================================================
    # 一致性计算
    # ================================================================
    def _compute_agreement(self, directions: List[int]) -> float:
        """计算三源方向一致性 0-1"""
        non_zero = [d for d in directions if d != 0]
        if len(non_zero) <= 1:
            return 0.5  # 只有一个有效源，无法交叉验证

        # 统计方向相同的比例
        positive = sum(1 for d in non_zero if d > 0)
        negative = sum(1 for d in non_zero if d < 0)

        majority = max(positive, negative)
        agreement = majority / len(non_zero)

        return agreement

    # ================================================================
    # 置信度调整
    # ================================================================
    def _compute_adjustment(
        self, agreement: float, directions: List[int], bcrm_confidence: float
    ) -> float:
        """根据一致性计算置信度调整"""
        # 三源完全一致 → 增强
        if agreement >= 1.0:
            return 0.08  # +8% 置信度

        # 多数一致 → 轻微增强
        if agreement >= 0.67:
            return 0.03  # +3%

        # 分歧 → 降低
        if agreement >= 0.5:
            return -0.05  # -5%

        # 严重分歧 → 大幅降低
        return -0.15  # -15%

    # ================================================================
    # 校验模式判定
    # ================================================================
    def _determine_verdict(self, directions: List[int], agreement: float) -> str:
        """判定校验模式"""
        non_zero = [d for d in directions if d != 0]

        if len(non_zero) <= 1:
            return "INSUFFICIENT_SOURCES"

        if agreement >= 1.0:
            return "STRONG_AGREE"
        elif agreement >= 0.67:
            return "MAJORITY_AGREE"
        elif agreement >= 0.5:
            return "DIVERGENT"
        else:
            return "CONFLICT"

    @staticmethod
    def _dir_str_to_int(direction: str) -> int:
        if direction == "UP":
            return 1
        elif direction == "DOWN":
            return -1
        return 0
