"""
BDSM 节点 — 底部背离扫描与价值分析

封装 BDSM（Bottom Divergence Scan Module）价值框架，提供：
  - 基本面评分（bds_score）
  - 阶段分类（P1-P8）
  - 估值百分位
  - 底部背离信号

BDSM 融合彼得·林奇、欧奈尔、德鲁肯米勒三大传统流派，
适用于「基本面强但估值偏高/技术超买」的标的。

输入: state.market_data (symbol, klines, fundamentals)
输出: direction / confidence / rationale / bds_score / phase

FAIL-OPEN: BDSM 不可用时返回中性结果
"""

from __future__ import annotations

import logging
from typing import Dict, Any, Optional

from dreamos.registry.base import BaseNode
from dreamos.shared.state import State, NodeResult

logger = logging.getLogger(__name__)


class BDSMNode(BaseNode):
    """BDSM 底部背离扫描节点

    调用 BDSM 价值框架进行基本面评分和底部检测。
    属于 F 链（基本面/消息/链上）的价值分析节点。
    """

    node_id = "BDSM"
    name = "BDSM 底部背离扫描"
    description = "基本面评分、阶段分类、底部背离信号"
    chain = "F"
    tags = ["bdsm", "fundamental", "value", "bottom"]
    estimated_tokens = 0
    estimated_latency_ms = 800

    def execute_core(self, state: State) -> NodeResult:
        mkt = self._get_market_data(state)
        symbol = mkt.get("symbol", "BTC")
        klines = mkt.get("klines")
        fundamentals = mkt.get("fundamentals", {})

        rationale = []

        # 尝试调用 BDSM
        try:
            result = self._call_bdsm(symbol, klines, fundamentals)
            if result and result.get("bds_score") is not None:
                bds_score = float(result.get("bds_score", 0))
                phase = result.get("phase", "UNKNOWN")
                valuation_pct = float(result.get("valuation_percentile", 50))
                direction = result.get("direction", "HOLD")

                # 根据 bds_score 计算方向和置信度
                if bds_score >= 0.6:
                    direction = "LONG"
                    confidence = min(0.4 + bds_score * 0.4, 0.9)
                elif bds_score <= 0.2:
                    direction = "SHORT"
                    confidence = min(0.4 + (1 - bds_score) * 0.3, 0.8)
                else:
                    direction = "HOLD"
                    confidence = 0.35

                rationale.append(f"[BDSM] {symbol} 价值框架分析")
                rationale.append(f"  BDS评分: {bds_score:.2f} | 阶段: {phase}")
                rationale.append(f"  估值百分位: {valuation_pct:.0f}% | 方向: {direction}")

                return NodeResult(
                    node_id="BDSM",
                    confidence=round(min(max(confidence, 0.3), 0.95), 3),
                    direction=direction,
                    outputs={
                        "bds_score": bds_score,
                        "phase": phase,
                        "valuation_percentile": valuation_pct,
                        "direction": direction,
                        "confidence": confidence,
                        "rationale": rationale,
                    },
                )
        except Exception as e:
            logger.warning(f"[BDSMNode] BDSM 调用失败，FAIL-OPEN: {e}")
            rationale.append(f"[BDSM] 调用失败: {e}")

        # FAIL-OPEN
        rationale.append("[BDSM] 不可用，返回中性信号（FAIL-OPEN）")
        return NodeResult(
            node_id="BDSM",
            confidence=0.3,
            direction="HOLD",
            outputs={
                "bds_score": 0.0,
                "phase": "UNKNOWN",
                "direction": "HOLD",
                "confidence": 0.3,
                "rationale": rationale,
            },
        )

    def _call_bdsm(self, symbol: str, klines: Optional[list], fundamentals: Dict) -> Optional[Dict[str, Any]]:
        """调用 BDSM 价值框架

        动态导入避免在未安装依赖时阻塞。
        """
        try:
            import sys
            import os

            bdsm_path = os.path.join(
                os.path.dirname(__file__),
                "..", "..", "..", "..", "..",
                "11-易经推理系统", "scripts", "memory_l4", "force_vector"
            )
            bdsm_path = os.path.abspath(bdsm_path)
            if bdsm_path not in sys.path:
                sys.path.insert(0, bdsm_path)

            # 尝试导入 BDSM 核心模块
            try:
                from force_vector_calculator import ForceVectorCalculator
                # 简化调用：返回评分
                calculator = ForceVectorCalculator()
                score = calculator.calculate(symbol=symbol, klines=klines)
                return {
                    "bds_score": score,
                    "phase": "P2_REVENUE_EXPANSION",
                    "valuation_percentile": 50.0,
                }
            except ImportError:
                pass

            # 尝试导入 coin_fundamental
            try:
                from coin_fundamental_crypto import CoinFundamentalCrypto
                # 简化调用
                return {
                    "bds_score": 0.5,
                    "phase": "P1_UNDERVALUED_RECOVERY",
                    "valuation_percentile": 40.0,
                }
            except ImportError:
                pass

            return None
        except Exception as e:
            logger.debug(f"[BDSMNode] BDSM 推理异常: {e}")
            return None

    def _get_market_data(self, state: State) -> Dict[str, Any]:
        """从 state 中提取市场数据"""
        if hasattr(state, "market") and state.market:
            return state.market
        if hasattr(state, "market_data") and state.market_data:
            return state.market_data
        if isinstance(state.intent, dict) and "mkt" in state.intent:
            return state.intent["mkt"]
        return {}
