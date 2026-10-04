"""
BCRM2.0 节点 — 辩证ML引擎信号生成

封装 BCRM 2.0 适配器，输出与经典分析兼容的方向/置信度信号。
BCRM2.0 基于辩证ML引擎，融合易经推理与机器学习，提供多周期趋势预测。

输入: state.market_data (klines, symbol, timeframe)
输出: direction / confidence / rationale / hexagram

FAIL-OPEN: BCRM2.0 不可用时返回 HOLD 方向 + 低置信度，不阻塞主流程
"""

from __future__ import annotations

import logging
from typing import Dict, Any, Optional

from dreamos.registry.base import BaseNode
from dreamos.shared.state import State, NodeResult

logger = logging.getLogger(__name__)


class BCRM2Node(BaseNode):
    """BCRM2.0 辩证ML引擎节点

    调用 BCRM2.0 适配器进行趋势推理，输出方向和置信度。
    属于 B 链（易经推理）的核心节点。
    """

    node_id = "BCRM2"
    name = "BCRM2.0 辩证ML引擎"
    description = "基于辩证ML引擎的多周期趋势预测，融合易经推理"
    chain = "B"
    tags = ["bcrm", "ml", "yijing", "trend"]
    estimated_tokens = 0
    estimated_latency_ms = 500

    def execute_core(self, state: State) -> NodeResult:
        mkt = self._get_market_data(state)
        symbol = mkt.get("symbol", "BTC")
        timeframe = mkt.get("timeframe", "1H")
        klines = mkt.get("klines")

        rationale = []

        # 尝试调用 BCRM2.0 适配器
        try:
            result = self._call_bcrm2(symbol, timeframe, klines)
            if result and result.get("direction"):
                direction = result["direction"].upper()
                if direction == "UP":
                    direction = "LONG"
                elif direction == "DOWN":
                    direction = "SHORT"
                else:
                    direction = "HOLD"

                confidence = float(result.get("confidence", 0.3))
                hexagram = result.get("hexagram", {})

                rationale.append(f"[BCRM2.0] {symbol} {timeframe} 辩证ML推理")
                if hexagram:
                    rationale.append(f"  卦象: {hexagram.get('name', 'N/A')} ({hexagram.get('symbol', 'N/A')})")
                rationale.append(f"  方向: {direction} | 置信度: {confidence:.1%}")

                return NodeResult(
                    node_id="BCRM2",
                    confidence=round(min(max(confidence, 0.3), 0.95), 3),
                    direction=direction,
                    outputs={
                        "direction": direction,
                        "confidence": confidence,
                        "hexagram": hexagram,
                        "rationale": rationale,
                    },
                )
        except Exception as e:
            logger.warning(f"[BCRM2Node] BCRM2.0 调用失败，FAIL-OPEN: {e}")
            rationale.append(f"[BCRM2.0] 调用失败: {e}")

        # FAIL-OPEN: BCRM2.0 不可用时返回中性结果
        rationale.append("[BCRM2.0] 不可用，返回中性信号（FAIL-OPEN）")
        return NodeResult(
            node_id="BCRM2",
            confidence=0.3,
            direction="HOLD",
            outputs={
                "direction": "HOLD",
                "confidence": 0.3,
                "rationale": rationale,
            },
        )

    def _call_bcrm2(self, symbol: str, timeframe: str, klines: Optional[list]) -> Optional[Dict[str, Any]]:
        """调用 BCRM2.0 适配器

        动态导入避免在未安装依赖时阻塞。
        """
        try:
            import sys
            import os

            # 添加 BCRM2.0 所在路径
            bcrm_path = os.path.join(
                os.path.dirname(__file__),
                "..", "..", "..", "..", "..",
                "11-易经推理系统", "scripts", "memory_l4"
            )
            bcrm_path = os.path.abspath(bcrm_path)
            if bcrm_path not in sys.path:
                sys.path.insert(0, bcrm_path)

            from bcrm2_adapter import BCRM2Adapter

            adapter = BCRM2Adapter(symbol=symbol, timeframe=timeframe)

            # 如果有 klines 数据，使用它训练/推理
            if klines:
                # 简化接口：直接调用 infer
                result = adapter.infer(klines=klines)
                return result
            else:
                # 无数据时返回空，触发 FAIL-OPEN
                return None
        except ImportError:
            logger.debug("[BCRM2Node] BCRM2Adapter 未安装，跳过")
            return None
        except Exception as e:
            logger.debug(f"[BCRM2Node] BCRM2 推理异常: {e}")
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
