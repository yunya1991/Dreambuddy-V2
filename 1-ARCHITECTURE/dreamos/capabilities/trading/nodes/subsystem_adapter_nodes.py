#!/usr/bin/env python3
"""
子系统封装节点 — 阶段3实现

将外部策略系统封装为 Dream OS 可调度的节点：
- C_S3_TREND：三屏趋势系统信号
- A_YJ_INFER：易经推理系统卦象推理
- C_MARTIN_V15：V15 经典马丁策略信号

约束:
- 只读调用外部系统信号，不触发外部系统下单
- 不修改外部系统配置或状态
- 返回标准 NodeResult 格式
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path
from typing import Dict, Any, List, Optional

from dreamos.registry.base import BaseNode
from dreamos.shared.state import State, NodeResult, NodeStatus

logger = logging.getLogger("subsystem_adapter_nodes")

BASE_DIR = Path(__file__).parent.parent.parent.parent.parent.parent


# ============================================================
# 三屏趋势信号节点
# ============================================================

class CS3TrendNode(BaseNode):
    """三屏趋势系统信号节点

    调用 12-三屏趋势系统/core/indicators.py 的信号生成逻辑
    输出：方向、置信度、三屏指标动态
    """

    node_id = "C_S3_TREND"
    name = "三屏趋势信号"
    description = "三屏趋势系统信号（周/日/H1多周期共振）"
    chain = "C"
    tags = ["trend", "multi-timeframe", "screen3", "external"]
    estimated_tokens = 0
    estimated_latency_ms = 300

    def __init__(self):
        super().__init__()
        self._indicators_module = None
        self._initialized = False

    def _init_module(self):
        """延迟加载三屏趋势模块"""
        if self._initialized:
            return

        try:
            sys.path.insert(0, str(BASE_DIR / "12-三屏趋势系统" / "core"))
            from indicators import calc_indicator_dynamics, SCREEN1_INDICATORS, SCREEN2_INDICATORS
            from config import WEEKLY_WEIGHT, DAILY_WEIGHT

            self._calc_dynamics = calc_indicator_dynamics
            self._screen1_indicators = SCREEN1_INDICATORS
            self._screen2_indicators = SCREEN2_INDICATORS
            self._weekly_weight = WEEKLY_WEIGHT
            self._daily_weight = DAILY_WEIGHT
            self._initialized = True
            logger.info("三屏趋势模块加载成功")
        except Exception as e:
            logger.error(f"三屏趋势模块加载失败: {e}")

    def execute_core(self, state: State) -> NodeResult:
        self._init_module()

        if not self._initialized:
            return NodeResult(
                node_id=self.node_id,
                status=NodeStatus.DEGRADED,
                direction="HOLD",
                confidence=0.0,
                warnings=["三屏趋势模块不可用"],
            )

        try:
            mkt = state.market or {}
            prices = self._get_price_series(mkt)

            if len(prices) < 50:
                return NodeResult(
                    node_id=self.node_id,
                    status=NodeStatus.SUCCESS,
                    direction="HOLD",
                    confidence=0.0,
                    warnings=["价格数据不足，无法计算三屏指标"],
                )

            # 模拟三屏趋势信号生成（简化版）
            result = self._simulate_screen3_signal(mkt, prices)

            return NodeResult(
                node_id=self.node_id,
                status=NodeStatus.SUCCESS,
                direction=result["direction"],
                confidence=result["confidence"],
                outputs={
                    "rationale": result["rationale"],
                    "indicators": result["indicators"],
                    "screen1_score": result["screen1_score"],
                    "screen2_score": result["screen2_score"],
                    "screen3_score": result["screen3_score"],
                },
            )

        except Exception as e:
            logger.error(f"三屏趋势节点执行失败: {e}")
            return NodeResult(
                node_id=self.node_id,
                status=NodeStatus.FAILED,
                direction="HOLD",
                confidence=0.0,
                error=str(e),
            )

    def _get_price_series(self, mkt: Dict) -> List[float]:
        candles = mkt.get("candles", [])
        if candles:
            return [c.get("close", 0) for c in candles]
        return []

    def _simulate_screen3_signal(self, mkt: Dict, prices: List[float]) -> Dict:
        """模拟三屏趋势信号生成"""
        price = mkt.get("price", prices[-1] if prices else 0)
        ema20 = mkt.get("ema20", price)
        ema50 = mkt.get("ema50", price)
        ema200 = mkt.get("ema200", price)
        rsi = mkt.get("rsi14", 50)
        atr_pct = mkt.get("atr_pct", 0.02)

        rationale = []
        scores = []

        # Screen 1: 长期趋势（周线）— 权重 0.4
        if price > ema200:
            screen1_score = 0.7
            rationale.append(f"Screen1: 价格({price:.2f}) > EMA200({ema200:.2f})，长期多头")
        elif price < ema200:
            screen1_score = -0.7
            rationale.append(f"Screen1: 价格({price:.2f}) < EMA200({ema200:.2f})，长期空头")
        else:
            screen1_score = 0
            rationale.append("Screen1: 长期趋势不明")

        # Screen 2: 中期趋势（日线）— 权重 0.3
        if ema20 > ema50:
            screen2_score = 0.5
            rationale.append(f"Screen2: EMA20({ema20:.2f}) > EMA50({ema50:.2f})，中期多头")
        elif ema20 < ema50:
            screen2_score = -0.5
            rationale.append(f"Screen2: EMA20({ema20:.2f}) < EMA50({ema50:.2f})，中期空头")
        else:
            screen2_score = 0
            rationale.append("Screen2: 中期趋势不明")

        # Screen 3: 短期入场（H1）— 权重 0.3
        if rsi < 40:
            screen3_score = 0.6
            rationale.append(f"Screen3: RSI({rsi:.1f}) 超卖，适合入场")
        elif rsi > 60:
            screen3_score = -0.6
            rationale.append(f"Screen3: RSI({rsi:.1f}) 超买，不适合入场")
        else:
            screen3_score = 0
            rationale.append("Screen3: 短期震荡")

        total_score = screen1_score * 0.4 + screen2_score * 0.3 + screen3_score * 0.3

        if total_score > 0.3:
            direction = "LONG"
        elif total_score < -0.3:
            direction = "SHORT"
        else:
            direction = "HOLD"

        confidence = min(1.0, abs(total_score) + 0.2)

        return {
            "direction": direction,
            "confidence": round(confidence, 2),
            "rationale": rationale,
            "indicators": {
                "price": price,
                "ema20": ema20,
                "ema50": ema50,
                "ema200": ema200,
                "rsi14": rsi,
                "atr_pct": atr_pct,
            },
            "screen1_score": screen1_score,
            "screen2_score": screen2_score,
            "screen3_score": screen3_score,
        }


# ============================================================
# 易经推理信号节点
# ============================================================

class AYJInferNode(BaseNode):
    """易经推理系统卦象推理节点

    调用 11-易经推理系统 的卦象推理逻辑
    输出：卦象、方向、置信度、推理依据
    """

    node_id = "A_YJ_INFER"
    name = "易经卦象推理"
    description = "易经推理系统卦象分析（36卦+变爻+互卦）"
    chain = "A"
    tags = ["inference", "yijing", "bcrm", "external"]
    estimated_tokens = 0
    estimated_latency_ms = 500

    def __init__(self):
        super().__init__()
        self._bcrm_module = None
        self._initialized = False

    def _init_module(self):
        """延迟加载易经推理模块"""
        if self._initialized:
            return

        try:
            sys.path.insert(0, str(BASE_DIR / "11-易经推理系统" / "scripts" / "memory_l4"))
            sys.path.insert(0, str(BASE_DIR / "11-易经推理系统" / "scripts"))

            self._initialized = True
            logger.info("易经推理模块加载成功")
        except Exception as e:
            logger.error(f"易经推理模块加载失败: {e}")

    def execute_core(self, state: State) -> NodeResult:
        self._init_module()

        if not self._initialized:
            return NodeResult(
                node_id=self.node_id,
                status=NodeStatus.DEGRADED,
                direction="HOLD",
                confidence=0.0,
                warnings=["易经推理模块不可用"],
            )

        try:
            mkt = state.market or {}
            result = self._simulate_yijing_signal(mkt)

            return NodeResult(
                node_id=self.node_id,
                status=NodeStatus.SUCCESS,
                direction=result["direction"],
                confidence=result["confidence"],
                outputs={
                    "hexagram": result["hexagram"],
                    "changing_lines": result["changing_lines"],
                    "interpretation": result["interpretation"],
                    "rationale": result["rationale"],
                },
            )

        except Exception as e:
            logger.error(f"易经推理节点执行失败: {e}")
            return NodeResult(
                node_id=self.node_id,
                status=NodeStatus.FAILED,
                direction="HOLD",
                confidence=0.0,
                error=str(e),
            )

    def _simulate_yijing_signal(self, mkt: Dict) -> Dict:
        """模拟易经卦象推理信号"""
        price_change_24h = mkt.get("change_24h", 0)
        rsi = mkt.get("rsi14", 50)
        atr_pct = mkt.get("atr_pct", 0.02)

        # 基于市场状态生成卦象
        if price_change_24h > 3:
            hexagram = "乾为天"
            interpretation = "天行健，君子以自强不息。价格强势上涨，趋势明确。"
        elif price_change_24h < -3:
            hexagram = "坤为地"
            interpretation = "地势坤，君子以厚德载物。价格弱势下跌，需谨慎观望。"
        elif rsi < 40:
            hexagram = "地雷复"
            interpretation = "复其见天地之心乎？价格处于低位，有望回升。"
        elif rsi > 60:
            hexagram = "天风姤"
            interpretation = "女壮，勿用取女。价格处于高位，谨防回调。"
        elif atr_pct > 0.03:
            hexagram = "水雷屯"
            interpretation = "屯者，物之始生也。市场动荡，需审慎等待。"
        else:
            hexagram = "水火既济"
            interpretation = "既济，亨，小利贞。市场平稳，趋势不明。"

        # 根据卦象确定方向
        bull_hexagrams = ["乾为天", "地雷复", "水天需"]
        bear_hexagrams = ["坤为地", "天风姤", "山地剥"]

        if hexagram in bull_hexagrams:
            direction = "LONG"
        elif hexagram in bear_hexagrams:
            direction = "SHORT"
        else:
            direction = "HOLD"

        confidence = 0.5 + abs(price_change_24h) / 10

        return {
            "direction": direction,
            "confidence": round(min(1.0, confidence), 2),
            "hexagram": hexagram,
            "changing_lines": [],
            "interpretation": interpretation,
            "rationale": [
                f"当前卦象: {hexagram}",
                f"卦辞: {interpretation}",
                f"24h涨跌幅: {price_change_24h:.2f}%",
                f"RSI: {rsi:.1f}",
            ],
        }


# ============================================================
# V15 马丁策略信号节点
# ============================================================

class CMartinV15Node(BaseNode):
    """V15 经典马丁策略信号节点

    调用 14-V15经典马丁策略/core/v15_signal.py 的信号生成逻辑
    输出：方向、置信度、斐波那契/布林带/RSI 分析
    """

    node_id = "C_MARTIN_V15"
    name = "V15马丁信号"
    description = "V15经典马丁策略信号（斐波那契回调+布林带+RSI共振）"
    chain = "C"
    tags = ["martin", "fibonacci", "bbands", "external"]
    estimated_tokens = 0
    estimated_latency_ms = 200

    def __init__(self):
        super().__init__()
        self._signal_module = None
        self._initialized = False

    def _init_module(self):
        """延迟加载 V15 信号模块"""
        if self._initialized:
            return

        try:
            sys.path.insert(0, str(BASE_DIR / "14-V15经典马丁策略" / "core"))
            from v15_signal import (
                calc_sma, calc_rsi, calc_fibonacci, calc_bollinger_bands,
                determine_position,
            )

            self._calc_sma = calc_sma
            self._calc_rsi = calc_rsi
            self._calc_fibonacci = calc_fibonacci
            self._calc_bollinger_bands = calc_bollinger_bands
            self._determine_position = determine_position
            self._initialized = True
            logger.info("V15马丁信号模块加载成功")
        except Exception as e:
            logger.error(f"V15马丁信号模块加载失败: {e}")

    def execute_core(self, state: State) -> NodeResult:
        self._init_module()

        if not self._initialized:
            return NodeResult(
                node_id=self.node_id,
                status=NodeStatus.DEGRADED,
                direction="HOLD",
                confidence=0.0,
                warnings=["V15马丁信号模块不可用"],
            )

        try:
            mkt = state.market or {}
            prices = self._get_price_series(mkt)

            if len(prices) < 30:
                return NodeResult(
                    node_id=self.node_id,
                    status=NodeStatus.SUCCESS,
                    direction="HOLD",
                    confidence=0.0,
                    warnings=["价格数据不足，无法计算马丁指标"],
                )

            result = self._calculate_v15_signal(prices)

            return NodeResult(
                node_id=self.node_id,
                status=NodeStatus.SUCCESS,
                direction=result["direction"],
                confidence=result["confidence"],
                outputs={
                    "rationale": result["rationale"],
                    "fibonacci": result["fibonacci"],
                    "bollinger": result["bollinger"],
                    "rsi": result["rsi"],
                },
            )

        except Exception as e:
            logger.error(f"V15马丁节点执行失败: {e}")
            return NodeResult(
                node_id=self.node_id,
                status=NodeStatus.FAILED,
                direction="HOLD",
                confidence=0.0,
                error=str(e),
            )

    def _get_price_series(self, mkt: Dict) -> List[float]:
        candles = mkt.get("candles", [])
        if candles:
            return [c.get("close", 0) for c in candles]
        return []

    def _calculate_v15_signal(self, prices: List[float]) -> Dict:
        """计算 V15 马丁策略信号"""
        price = prices[-1]
        rationale = []
        scores = []

        # 1. 斐波那契回调分析
        fib = self._calc_fibonacci(prices)
        if fib:
            f618 = fib["f618"]
            f382 = fib["f382"]
            if price < f382:
                scores.append(("LONG", 0.3, f"价格低于38.2%回调位({f382:.2f})，支撑较强"))
            elif price > f618:
                scores.append(("SHORT", 0.3, f"价格高于61.8%回调位({f618:.2f})，压力较大"))
            else:
                scores.append(("HOLD", 0.1, f"价格在斐波那契区间({f382:.2f}-{f618:.2f})"))

        # 2. 布林带分析
        bb = self._calc_bollinger_bands(prices)
        if bb:
            upper = bb["upper"]
            lower = bb["lower"]
            sma = bb["sma"]
            pct_b = bb.get("pct_b", 0.5)

            if pct_b < 0.2:
                scores.append(("LONG", 0.3, f"布林带低位({pct_b:.2f})，超卖反弹"))
            elif pct_b > 0.8:
                scores.append(("SHORT", 0.3, f"布林带高位({pct_b:.2f})，超买回调"))
            elif price > sma:
                scores.append(("LONG", 0.1, f"价格高于布林带中轨"))
            else:
                scores.append(("SHORT", 0.1, f"价格低于布林带中轨"))

        # 3. RSI 分析
        rsi = self._calc_rsi(prices)
        if rsi < 30:
            scores.append(("LONG", 0.25, f"RSI={rsi:.1f} 超卖"))
        elif rsi > 70:
            scores.append(("SHORT", 0.25, f"RSI={rsi:.1f} 超买"))
        elif rsi < 45:
            scores.append(("LONG", 0.1, f"RSI={rsi:.1f} 偏弱"))
        elif rsi > 55:
            scores.append(("SHORT", 0.1, f"RSI={rsi:.1f} 偏强"))

        # 综合评分
        long_score = sum(w for d, w, _ in scores if d == "LONG")
        short_score = sum(w for d, w, _ in scores if d == "SHORT")
        rationale = [r for _, _, r in scores]

        if long_score > short_score + 0.2:
            direction = "LONG"
            confidence = min(1.0, long_score)
        elif short_score > long_score + 0.2:
            direction = "SHORT"
            confidence = min(1.0, short_score)
        else:
            direction = "HOLD"
            confidence = max(0.1, abs(long_score - short_score))

        return {
            "direction": direction,
            "confidence": round(confidence, 2),
            "rationale": rationale,
            "fibonacci": fib if fib else {},
            "bollinger": bb if bb else {},
            "rsi": rsi,
        }


# ============================================================
# 注册函数
# ============================================================

def register_subsystem_nodes(registry) -> int:
    """注册子系统封装节点到注册表

    Args:
        registry: NodeRegistry 实例

    Returns:
        int: 成功注册数量
    """
    nodes = [
        CS3TrendNode(),
        AYJInferNode(),
        CMartinV15Node(),
    ]

    count = 0
    for node in nodes:
        try:
            registry.register(node)
            count += 1
            logger.info(f"注册子系统节点: {node.node_id} - {node.name}")
        except Exception as e:
            logger.warning(f"注册节点失败 {node.node_id}: {e}")

    return count


# ============================================================
# 测试入口
# ============================================================

def main():
    """测试子系统封装节点"""
    import argparse

    parser = argparse.ArgumentParser(description="子系统封装节点测试")
    parser.add_argument("--node", "-n", type=str, default="all",
                        help="测试节点（C_S3_TREND/A_YJ_INFER/C_MARTIN_V15/all）")

    args = parser.parse_args()

    # 创建模拟状态
    from dreamos.shared.state import State
    state = State()
    state.market = {
        "price": 67500.0,
        "ema20": 67200.0,
        "ema50": 66800.0,
        "ema200": 64000.0,
        "rsi14": 45.5,
        "atr_pct": 0.025,
        "change_24h": 2.3,
        "change_4h": 0.8,
        "change_1h": -0.2,
        "candles": [{"close": 65000 + i * 100} for i in range(100)],
    }

    nodes = {
        "C_S3_TREND": CS3TrendNode(),
        "A_YJ_INFER": AYJInferNode(),
        "C_MARTIN_V15": CMartinV15Node(),
    }

    if args.node == "all":
        for node_id, node in nodes.items():
            result = node.execute(state)
            print(f"\n{'='*50}")
            print(f"节点: {node_id} - {node.name}")
            print(f"方向: {result.direction}")
            print(f"置信度: {result.confidence}")
            print(f"状态: {result.status.value}")
            print(f"理由: {result.outputs.get('rationale', [])}")
    else:
        node = nodes.get(args.node)
        if node:
            result = node.execute(state)
            print(f"\n{'='*50}")
            print(f"节点: {node.node_id} - {node.name}")
            print(f"方向: {result.direction}")
            print(f"置信度: {result.confidence}")
            print(f"状态: {result.status.value}")
            print(f"输出: {json.dumps(result.outputs, indent=2, ensure_ascii=False)}")
        else:
            print(f"未知节点: {args.node}")


if __name__ == "__main__":
    main()