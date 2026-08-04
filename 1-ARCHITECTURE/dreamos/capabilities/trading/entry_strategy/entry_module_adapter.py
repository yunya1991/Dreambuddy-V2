#!/usr/bin/env python3
"""
入场模块统一适配器 (Entry Module Adapter)
==========================================

将多个入场子能力封装为统一接口，输出 UnifiedEntryDecision。
所有子能力都基于 DreamOS 原生节点（BaseNode/NodeResult），不自创信号：

    a2_fusion       — A2 综合分析节点（跨链多维度加权融合：技术面 30% / 子系统 25% / 基本面 20% / 研究面 15% / 情绪面 10%）
    c2_momentum     — C2 动量分析节点（RSI / MACD / 24h 涨跌幅 / 价格动量）
    s3_trend        — C_S3_TREND 三屏趋势系统节点（周/日/H1 多周期共振）
    yj_infer        — A_YJ_INFER 易经卦象推理节点（易经推理系统卦象 → 方向）
    martin_v15      — C_MARTIN_V15 V15 经典马丁信号节点（基于马丁触发条）
    scenario_ema    — 基线信号（ScenarioClassifier 分类 + EMA20/50 交叉 + RSI 过滤），作为 default fallback

统一输出: UnifiedEntryDecision
    direction:    LONG / SHORT / HOLD
    confidence:   [0, 1]
    source:       模块名（a2_fusion / c2_momentum / ...）
    entry_reason: 人类可读理由（如"EMA20 上穿 EMA50 + RSI>55"）
    node_id:      节点真实 node_id（调试用）
    raw:          原始 NodeResult（调试用）
"""

from __future__ import annotations

import math
import logging
from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional, Callable

logger = logging.getLogger("entry_module_adapter")


# ============================================================
# 统一入场决策结构
# ============================================================

@dataclass
class UnifiedEntryDecision:
    """统一入场决策（跨模块）"""
    direction: str = "HOLD"               # LONG / SHORT / HOLD
    confidence: float = 0.0               # [0, 1]
    source: str = "unknown"               # a2_fusion / c2_momentum / s3_trend / yj_infer / martin_v15 / scenario_ema
    entry_reason: str = ""                # 人类可读理由
    node_id: str = ""                     # 真实 node_id（调试用）
    raw: Optional[Any] = None             # 原始 NodeResult（调试用）
    metadata: Dict[str, Any] = field(default_factory=dict)  # 扩展字段


# ============================================================
# 辅助：EMA / RSI 计算（基线 scenario_ema 用，避免重复造轮子）
# ============================================================

def _ema_series(values: List[float], period: int) -> List[float]:
    if len(values) < period:
        return []
    k = 2.0 / (period + 1)
    ema = [sum(values[:period]) / period]
    for v in values[period:]:
        ema.append(v * k + ema[-1] * (1 - k))
    return ema


def _rsi(closes: List[float], period: int = 14) -> float:
    if len(closes) < period + 1:
        return 50.0
    gains, losses = 0.0, 0.0
    for i in range(1, period + 1):
        diff = closes[-i] - closes[-i - 1]
        if diff >= 0:
            gains += diff
        else:
            losses -= diff
    if gains == 0 and losses == 0:
        return 50.0
    if losses == 0:
        return 100.0
    if gains == 0:
        return 0.0
    rs = (gains / period) / (losses / period)
    return 100 - 100 / (1 + rs)


def _atr_pct(highs: List[float], lows: List[float], closes: List[float], period: int = 14) -> float:
    if len(closes) < period + 1:
        return 0.02
    trs = []
    for i in range(1, len(closes)):
        tr = max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1]))
        trs.append(tr)
    if not trs:
        return 0.02
    atr = sum(trs[-period:]) / min(period, len(trs))
    return atr / closes[-1] if closes[-1] > 0 else 0.02


# ============================================================
# 基类
# ============================================================

class BaseEntryAdapter:
    """入场模块适配器基类"""

    source_name: str = "base"
    node_id: str = ""

    def __init__(self):
        self.is_available: bool = True
        self._init_error: Optional[str] = None

    def evaluate(
        self,
        symbol: str,
        scenario_id: str,
        window_klines: List[tuple],       # [(t,o,h,l,c,v), ...]（WINDOW_SIZE=48 根 1h）
        market_data: Dict[str, Any],      # {price, rsi14, change_1h/4h/24h, atr_pct, candles_1h, ...}
        extra_state: Optional[Dict[str, Any]] = None,
    ) -> UnifiedEntryDecision:
        raise NotImplementedError


# ============================================================
# Adapter 1: scenario_ema 基线（36 场景分类 + EMA20/50 + RSI）
# ============================================================

class ScenarioEmaAdapter(BaseEntryAdapter):
    """基线入场信号：ScenarioClassifier 场景分类 + EMA20/50 交叉 + RSI 过滤"""

    source_name = "scenario_ema"
    node_id = "SCENARIO_EMA_BASELINE"

    def __init__(self):
        super().__init__()
        try:
            from dreamos.core.sense.scenario_classifier import ScenarioClassifier
            self._classifier = ScenarioClassifier()
            self.is_available = True
        except Exception as e:
            self._init_error = str(e)
            self.is_available = False
            logger.warning(f"scenario_ema adapter不可用: {e}")

    def evaluate(self, symbol, scenario_id, window_klines, market_data, extra_state=None):
        closes = [k[4] for k in window_klines]
        if len(closes) < 50:
            return UnifiedEntryDecision(
                direction="HOLD", confidence=0.0, source=self.source_name,
                entry_reason=f"K线不足({len(closes)}/50)", node_id=self.node_id,
            )
        ema20 = _ema_series(closes, 20)
        ema50 = _ema_series(closes, 50)
        if len(ema20) < 2 or len(ema50) < 2:
            return UnifiedEntryDecision(direction="HOLD", confidence=0.0, source=self.source_name, node_id=self.node_id)
        e20_curr, e20_prev = ema20[-1], ema20[-2]
        e50_curr, e50_prev = ema50[-1], ema50[-2]
        spread_pct = (e20_curr - e50_curr) / e50_curr * 100.0 if e50_curr else 0
        rsi = market_data.get("rsi14") or _rsi(closes, 14)
        atr_pct_v = market_data.get("atr_pct") or _atr_pct([k[2] for k in window_klines], [k[3] for k in window_klines], closes, 14)

        direction, confidence, reason = "HOLD", 0.0, ""
        # 金叉
        if e20_prev <= e50_prev and e20_curr > e50_curr:
            direction = "LONG"
            # 置信度: 0.4 基础 + EMA spread% × 20 + ATR% × 5
            confidence = 0.4 + max(0.0, min(spread_pct, 3.0)) * 0.20 / 0.03 + min(atr_pct_v, 0.05) * 5
            if rsi < 55:
                confidence *= 0.7  # 震荡惩罚
            reason = f"EMA20 上穿 EMA50, spread={spread_pct:.2f}%, RSI={rsi:.0f}"
        # 死叉
        elif e20_prev >= e50_prev and e20_curr < e50_curr:
            direction = "SHORT"
            confidence = 0.4 + max(0.0, min(-spread_pct, 3.0)) * 0.20 / 0.03 + min(atr_pct_v, 0.05) * 5
            if rsi > 45:
                confidence *= 0.7
            reason = f"EMA20 下穿 EMA50, spread={spread_pct:.2f}%, RSI={rsi:.0f}"
        # 未交叉，按多头/空头排列给弱信号
        elif e20_curr > e50_curr and rsi > 50:
            direction = "LONG"
            confidence = 0.3 + min(abs(spread_pct), 2.0) * 0.05
            reason = f"EMA多头排列, spread={spread_pct:.2f}%, RSI={rsi:.0f}"
        elif e20_curr < e50_curr and rsi < 50:
            direction = "SHORT"
            confidence = 0.3 + min(abs(spread_pct), 2.0) * 0.05
            reason = f"EMA空头排列, spread={spread_pct:.2f}%, RSI={rsi:.0f}"
        else:
            return UnifiedEntryDecision(direction="HOLD", confidence=0.0, source=self.source_name,
                                        entry_reason="EMA无方向+RSI中性", node_id=self.node_id)
        confidence = max(0.0, min(1.0, confidence))
        return UnifiedEntryDecision(direction=direction, confidence=confidence, source=self.source_name,
                                    entry_reason=reason, node_id=self.node_id)


# ============================================================
# Adapter 2: A2 综合分析节点（第一性原理融合）
# ============================================================

class A2FusionAdapter(BaseEntryAdapter):
    """A2 综合分析节点（技术 30% + 子系统 25% + 基本面 20% + 研究面 15% + 情绪面 10%）"""

    source_name = "a2_fusion"
    node_id = "A2"

    def __init__(self):
        super().__init__()
        self._node = None
        try:
            from dreamos.capabilities.trading.nodes.a2_comprehensive import A2ComprehensiveNode
            self._node = A2ComprehensiveNode()
            self.is_available = True
        except Exception as e:
            self._init_error = str(e)
            self.is_available = False

    def evaluate(self, symbol, scenario_id, window_klines, market_data, extra_state=None):
        if not self.is_available or self._node is None:
            return UnifiedEntryDecision(direction="HOLD", confidence=0.0, source=self.source_name,
                                        entry_reason=f"未初始化: {self._init_error}", node_id=self.node_id)
        try:
            # 组装 state：与 BaseNode.execute_core 的 state.market_data/state.results 对齐
            class _State: pass
            state = _State()
            state.market_data = market_data
            state.market = market_data
            state.inputs = {"symbol": symbol, "scenario_id": scenario_id, "mkt": market_data}
            # 预置 C链/F链/A链 前驱结果（A2 从 state.results 读取）
            closes = [k[4] for k in window_klines]
            highs = [k[2] for k in window_klines]
            lows = [k[3] for k in window_klines]
            state.results = {
                "C1": {"direction": "HOLD", "confidence": 0},
                "C2": {
                    "direction": "LONG" if market_data.get("change_24h", 0) > 0 else "SHORT",
                    "confidence": max(0.3, min(0.7, 0.5 + abs(market_data.get("change_24h", 0)) * 0.05)),
                    "rationale": [f"24h涨跌 {market_data.get('change_24h', 0):.2f}%"],
                },
                "C3": {"direction": "HOLD", "confidence": 0.35, "volatility_pct": _atr_pct(highs, lows, closes, 14)},
                "F3": {"direction": "HOLD", "confidence": 0.4},
                "F5": {"direction": "HOLD", "confidence": 0.4},
                "A1": {"direction": "HOLD", "confidence": 0.3},
                "F1": {"direction": "HOLD", "confidence": 0.4, "sentiment_score": 0.5},
                "C_S3_TREND": {"direction": "HOLD", "confidence": 0.3},
                "A_YJ_INFER": {"direction": "HOLD", "confidence": 0.3},
                "C_MARTIN_V15": {"direction": "HOLD", "confidence": 0.3},
            }
            result = self._node.execute(state)  # NodeResult
            return UnifiedEntryDecision(
                direction=result.direction or "HOLD", confidence=result.confidence or 0.0,
                source=self.source_name,
                entry_reason=("; ".join(getattr(result, 'outputs', {}) or {}).get('rationale', [])
                              if isinstance(getattr(result, 'outputs', None), dict) else f"A2融合置信度={result.confidence:.2f}"),
                node_id=self.node_id, raw=result,
            )
        except Exception as e:
            logger.debug(f"A2 evaluate 失败: {e}")
            return UnifiedEntryDecision(direction="HOLD", confidence=0.0, source=self.source_name,
                                        entry_reason=f"错误: {e}", node_id=self.node_id)


# ============================================================
# Adapter 3: C2 动量节点
# ============================================================

class C2MomentumAdapter(BaseEntryAdapter):
    """C2 动量分析节点（RSI/MACD/24h 涨跌）"""

    source_name = "c2_momentum"
    node_id = "C2"

    def __init__(self):
        super().__init__()
        self._node = None
        try:
            from dreamos.capabilities.trading.nodes.c2_momentum import C2MomentumNode
            self._node = C2MomentumNode()
            self.is_available = True
        except Exception as e:
            self._init_error = str(e)
            self.is_available = False

    def evaluate(self, symbol, scenario_id, window_klines, market_data, extra_state=None):
        if not self.is_available or self._node is None:
            return UnifiedEntryDecision(direction="HOLD", confidence=0.0, source=self.source_name,
                                        entry_reason=f"未初始化: {self._init_error}", node_id=self.node_id)
        try:
            class _State: pass
            state = _State()
            state.market_data = market_data
            state.inputs = {"symbol": symbol, "mkt": market_data}
            result = self._node.execute(state)
            out = getattr(result, 'outputs', {}) or {}
            rationale = out.get('rationale', [])
            if isinstance(rationale, list):
                reason = "; ".join([str(r) for r in rationale[:3]])
            else:
                reason = str(rationale)[:80]
            return UnifiedEntryDecision(
                direction=result.direction or "HOLD", confidence=result.confidence or 0.0,
                source=self.source_name, entry_reason=reason or f"C2动量置信度={result.confidence:.2f}",
                node_id=self.node_id, raw=result,
            )
        except Exception as e:
            logger.debug(f"C2 evaluate 失败: {e}")
            return UnifiedEntryDecision(direction="HOLD", confidence=0.0, source=self.source_name,
                                        entry_reason=f"错误: {e}", node_id=self.node_id)


# ============================================================
# Adapter 4: S3 三屏趋势节点
# ============================================================

class S3TrendAdapter(BaseEntryAdapter):
    """C_S3_TREND 三屏趋势系统（周/日/H1 多周期共振）"""

    source_name = "s3_trend"
    node_id = "C_S3_TREND"

    def __init__(self):
        super().__init__()
        self._node = None
        try:
            from dreamos.capabilities.trading.nodes.subsystem_adapter_nodes import CS3TrendNode
            self._node = CS3TrendNode()
            self.is_available = True
        except Exception as e:
            self._init_error = str(e)
            self.is_available = False

    def evaluate(self, symbol, scenario_id, window_klines, market_data, extra_state=None):
        if not self.is_available or self._node is None:
            return UnifiedEntryDecision(direction="HOLD", confidence=0.0, source=self.source_name,
                                        entry_reason=f"未初始化: {self._init_error}", node_id=self.node_id)
        try:
            class _State: pass
            state = _State()
            closes = [k[4] for k in window_klines]
            prices = closes + [market_data.get("price", closes[-1])]
            state.market = {
                **market_data,
                "prices": prices,
                "weekly_prices": closes[-168::24] if len(closes) >= 168 else closes,
                "daily_prices": closes[-24::1] if len(closes) >= 24 else closes,
            }
            state.market_data = state.market  # 与 subsystem_adapter_nodes.CS3TrendNode 对齐（从 state.market 读）
            state.inputs = {"symbol": symbol, "market": state.market}
            result = self._node.execute(state)
            out = getattr(result, 'outputs', {}) or {}
            rationale = out.get("rationale", [])
            reason = "; ".join([str(r) for r in (rationale if isinstance(rationale, list) else [rationale])[:3]])
            return UnifiedEntryDecision(
                direction=result.direction or "HOLD", confidence=result.confidence or 0.0,
                source=self.source_name, entry_reason=reason or f"S3三屏置信度={result.confidence:.2f}",
                node_id=self.node_id, raw=result,
            )
        except Exception as e:
            logger.debug(f"S3 evaluate 失败: {e}")
            return UnifiedEntryDecision(direction="HOLD", confidence=0.0, source=self.source_name,
                                        entry_reason=f"错误: {e}", node_id=self.node_id)


# ============================================================
# Adapter 5: A_YJ_INFER 易经卦象推理（复用易经节点）
# ============================================================

class YJInferAdapter(BaseEntryAdapter):
    """A_YJ_INFER 易经卦象推理节点"""

    source_name = "yj_infer"
    node_id = "A_YJ_INFER"

    def __init__(self):
        super().__init__()
        self._node_cls = None
        try:
            from dreamos.capabilities.trading.nodes.subsystem_adapter_nodes import AYJInferNode
            self._node_cls = AYJInferNode
            self.is_available = True
        except Exception as e:
            self._init_error = str(e)
            self.is_available = False

    def evaluate(self, symbol, scenario_id, window_klines, market_data, extra_state=None):
        if not self.is_available:
            return UnifiedEntryDecision(direction="HOLD", confidence=0.0, source=self.source_name,
                                        entry_reason=f"未初始化: {self._init_error}", node_id=self.node_id)
        try:
            node = self._node_cls()
            class _State: pass
            state = _State()
            state.market_data = market_data
            state.market = market_data  # 与 subsystem_adapter_nodes.AYJInferNode 对齐
            state.inputs = {"symbol": symbol, "scenario_id": scenario_id, "window_klines": window_klines}
            result = node.execute(state)
            out = getattr(result, 'outputs', {}) or {}
            gua = out.get("gua_name", "") or out.get("hexagram", "")
            direction = result.direction or "HOLD"
            conf = result.confidence or 0.0
            return UnifiedEntryDecision(
                direction=direction, confidence=conf, source=self.source_name,
                entry_reason=f"易经卦象={gua}, 方向={direction}, 置信度={conf:.2f}",
                node_id=self.node_id, raw=result,
            )
        except Exception as e:
            logger.debug(f"A_YJ_INFER evaluate 失败: {e}")
            return UnifiedEntryDecision(direction="HOLD", confidence=0.0, source=self.source_name,
                                        entry_reason=f"错误: {e}", node_id=self.node_id)


# ============================================================
# Adapter 6: C_MARTIN_V15 V15 经典马丁信号
# ============================================================

class MartinV15Adapter(BaseEntryAdapter):
    """C_MARTIN_V15 V15 经典马丁信号节点"""

    source_name = "martin_v15"
    node_id = "C_MARTIN_V15"

    def __init__(self):
        super().__init__()
        self._node_cls = None
        try:
            from dreamos.capabilities.trading.nodes.subsystem_adapter_nodes import CMartinV15Node
            self._node_cls = CMartinV15Node
            self.is_available = True
        except Exception as e:
            self._init_error = str(e)
            self.is_available = False

    def evaluate(self, symbol, scenario_id, window_klines, market_data, extra_state=None):
        if not self.is_available:
            return UnifiedEntryDecision(direction="HOLD", confidence=0.0, source=self.source_name,
                                        entry_reason=f"未初始化: {self._init_error}", node_id=self.node_id)
        try:
            node = self._node_cls()
            class _State: pass
            state = _State()
            state.market_data = market_data
            state.market = market_data  # 与 subsystem_adapter_nodes.CMartinV15Node 对齐
            state.inputs = {"symbol": symbol, "window_klines": window_klines}
            result = node.execute(state)
            out = getattr(result, 'outputs', {}) or {}
            stage = out.get("martin_stage", "") or out.get("signal_stage", "")
            direction = result.direction or "HOLD"
            conf = result.confidence or 0.0
            return UnifiedEntryDecision(
                direction=direction, confidence=conf, source=self.source_name,
                entry_reason=f"马丁V15阶段={stage}, 方向={direction}, 置信度={conf:.2f}",
                node_id=self.node_id, raw=result,
            )
        except Exception as e:
            logger.debug(f"C_MARTIN_V15 evaluate 失败: {e}")
            return UnifiedEntryDecision(direction="HOLD", confidence=0.0, source=self.source_name,
                                        entry_reason=f"错误: {e}", node_id=self.node_id)


# ============================================================
# 工厂：按 source 名取实例
# ============================================================

_ADAPTER_REGISTRY: Dict[str, Callable[[], BaseEntryAdapter]] = {
    "scenario_ema": ScenarioEmaAdapter,
    "a2_fusion": A2FusionAdapter,
    "c2_momentum": C2MomentumAdapter,
    "s3_trend": S3TrendAdapter,
    "yj_infer": YJInferAdapter,
    "martin_v15": MartinV15Adapter,
}


def get_all_entry_modules() -> List[str]:
    return list(_ADAPTER_REGISTRY.keys())


def create_entry_adapter(source: str) -> Optional[BaseEntryAdapter]:
    cls = _ADAPTER_REGISTRY.get(source)
    if cls is None:
        return None
    try:
        return cls()
    except Exception as e:
        logger.warning(f"create_entry_adapter({source}) 失败: {e}")
        return None
