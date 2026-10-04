"""
C2 信号识别节点

Classic Pipeline C0-C8 八阶段流水线第三阶段。
对 C1 筛选出的 candidates 做多策略信号识别，产出 signals/signal_count/dominant_direction。

迁移自 ml_trade_service.py L36996-L39882 (/signals/v1 及 /signals/hyperliquid/* 路由)。
原实现依赖 freqtrade/Strategy005 + pandas + 大量内部指标计算，单文件 89000+ 行，
无法直接抽取。本节点采用与 C0/C1 一致的轻量级简化策略：
- 从 state.market["market_data"][coin] 读取每个币种的 trend/rsi/momentum 等基础指标
- 用 trend 方向 + rsi/momentum 修正生成信号
- 多数信号方向决定 dominant_direction

设计原则（遵循优雅改动原则）：
- 不依赖全局 CONFIG / Strategy005 / freqtrade / pandas
- 所有输入通过 state.market + state.config 提供
- 无 market 或无 C1 上游结果时降级返回 SUCCESS + 空 signals（FAIL-OPEN）

inputs:
    - 上游 C1: state.get_result("C1").outputs["candidates"] (list[str])
    - state.market: dict, 必须包含:
        - market_data: dict[str, dict], 币种→指标数据
          每项含: trend(float,如0.05表示+5%), rsi(float,0-100), momentum(float,可负)
    - state.config: dict, 可选覆盖阈值:
        - signal_detect_trend_threshold: float (默认 0.01) — 趋势方向阈值，|trend|>threshold 才生成信号
        - signal_detect_base_confidence: float (默认 0.5) — 基础置信度
        - signal_detect_max_confidence: float (默认 0.95) — 置信度上限
outputs:
    - signals: list[dict] — 识别出的信号清单，每项含:
        - symbol: str — 币种
        - direction: str — LONG / SHORT
        - confidence: float — [0,1]
        - strategy: str — 策略名（"trend_momentum"）
        - layer: str — 信号层（"trend"/"momentum"/"rsi"）
    - signal_count: int — 信号总数
    - dominant_direction: str — LONG / SHORT / NEUTRAL（无信号或等量时）
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Tuple

from dreamos.registry.base import BaseNode
from dreamos.shared.state import State, NodeResult, NodeStatus


# ── 默认阈值 ──────────────────────────────────────────────
_DEFAULT_TREND_THRESHOLD = 0.01
_DEFAULT_BASE_CONFIDENCE = 0.5
_DEFAULT_MAX_CONFIDENCE = 0.95


def _clip(value: float, low: float, high: float) -> float:
    """将 value 截断到 [low, high]"""
    if not math.isfinite(float(value)):
        return float(low)
    if float(value) < float(low):
        return float(low)
    if float(value) > float(high):
        return float(high)
    return float(value)


class C2SignalDetectNode(BaseNode):
    """C2 信号识别节点

    多策略信号生成逻辑（简化版）：
    - 基于 trend 方向判定 LONG/SHORT
    - rsi > 55 加强 LONG，rsi < 45 加强 SHORT
    - momentum 与 trend 同向时加强置信度
    下游 C3 通过 state.get_result("C2").outputs["signals"] 访问。

    设计原则（遵循优雅改动原则）：
    - 不依赖全局 CONFIG / Strategy005 / freqtrade / pandas
    - 所有输入通过 state.market + state.config 提供
    - 无 market 或无 C1 上游结果时降级返回 SUCCESS + 空 signals（FAIL-OPEN）
    """

    node_id = "C2"
    name = "信号识别"
    description = "16 层信号体系 + 多策略信号生成"
    chain = "C"
    tags = ["classic", "classic_v2", "signal", "16-layer", "multi-strategy"]
    estimated_tokens = 0
    estimated_latency_ms = 0

    @staticmethod
    def _read_config(state: State) -> Dict[str, float]:
        """从 state.config 读取阈值"""
        cfg = state.config or {}

        def _get_float(key: str, default: float) -> float:
            try:
                v = float(cfg.get(key, default))
                if not math.isfinite(v):
                    return float(default)
                return v
            except Exception:
                return float(default)

        return {
            "trend_threshold": max(0.0, _get_float("signal_detect_trend_threshold", _DEFAULT_TREND_THRESHOLD)),
            "base_confidence": _clip(_get_float("signal_detect_base_confidence", _DEFAULT_BASE_CONFIDENCE), 0.0, 1.0),
            "max_confidence": _clip(_get_float("signal_detect_max_confidence", _DEFAULT_MAX_CONFIDENCE), 0.01, 1.0),
        }

    @staticmethod
    def _get_float(d: Dict[str, Any], key: str, default: float = 0.0) -> float:
        """安全读取 dict 中的 float 字段"""
        try:
            v = float(d.get(key, default) or default)
            if not math.isfinite(v):
                return float(default)
            return v
        except Exception:
            return float(default)

    @staticmethod
    def _compute_confidence(
        trend: float,
        rsi: float,
        momentum: float,
        base: float,
        max_conf: float,
    ) -> float:
        """计算单信号置信度

        基础置信度 + trend 强度加成 + momentum 同向加成 + rsi 顺势加成
        """
        conf = float(base)

        # trend 强度加成（|trend| 越大越自信，最高 +0.20）
        trend_strength = min(abs(trend), 0.20)  # 限制在 [0, 0.20]
        conf += trend_strength

        # momentum 与 trend 同向时加成（最高 +0.10）
        if (trend > 0 and momentum > 0) or (trend < 0 and momentum < 0):
            conf += min(abs(momentum), 0.10)

        # rsi 顺势加成（LONG 时 rsi>55 加成，SHORT 时 rsi<45 加成，最高 +0.10）
        if trend > 0 and rsi > 55.0:
            conf += min((rsi - 55.0) / 100.0, 0.10)
        elif trend < 0 and rsi < 45.0:
            conf += min((45.0 - rsi) / 100.0, 0.10)

        return _clip(conf, 0.0, max_conf)

    @staticmethod
    def _pick_layer(trend: float, rsi: float, momentum: float) -> str:
        """选择主信号层（用于 trace/debug）"""
        if abs(trend) >= 0.05:
            return "trend"
        if abs(momentum) >= 0.03:
            return "momentum"
        if rsi >= 60 or rsi <= 40:
            return "rsi"
        return "trend"

    @staticmethod
    def _compute_signal_from_ohlcv(
        symbol: str,
        ohlcv: List[List[float]],
        cfg: Dict[str, float],
    ) -> Optional[Dict[str, Any]]:
        """从 OHLCV 数据调用 classic_pipeline.signals 生成信号。

        Args:
            symbol: 币种代码
            ohlcv: [[ts, open, high, low, close, volume], ...]
            cfg: 配置

        Returns:
            信号 dict 或 None（无信号时）
        """
        try:
            import pandas as pd
            from classic_pipeline.signals.quant_signal import compute as quant_compute

            # 转换 OHLCV 行为 DataFrame
            df = pd.DataFrame(ohlcv, columns=["ts", "open", "high", "low", "close", "volume"])

            # 调用 quant_signal.compute
            result = quant_compute(df, config={
                "ema_fast": 12,
                "ema_slow": 26,
            })

            direction = str(result.get("dominant_direction") or "neutral").strip().lower()
            if direction not in ("long", "short"):
                return None

            confidence = float(result.get("confidence") or 0.0)
            if confidence <= 0:
                return None

            return {
                "symbol": symbol,
                "direction": direction.upper(),
                "confidence": _clip(confidence, 0.0, cfg.get("max_confidence", 0.95)),
                "strategy": "quant_multi_strategy",
                "layer": "quant",
            }
        except Exception:
            # FAIL-OPEN: 调用失败时返回 None，由调用方降级
            return None

    def execute_core(self, state: State) -> NodeResult:
        """执行信号识别

        流程：
            1. 读取 state.market + state.config + 上游 C1 candidates
            2. 遍历 candidates，从 market_data 取指标
            3. 按 trend 方向生成 LONG/SHORT 信号，|trend|<=threshold 跳过
            4. 统计 LONG/SHORT 数量决定 dominant_direction
        """
        # 1. FAIL-OPEN：无 market 或无 C1 上游结果
        market = state.market if isinstance(state.market, dict) else None
        if market is None:
            return NodeResult(
                node_id="C2",
                status=NodeStatus.SUCCESS,
                confidence=0.0,
                outputs={
                    "signals": [],
                    "signal_count": 0,
                    "dominant_direction": "NEUTRAL",
                },
                error="C2 无 market 数据，降级返回空 signals",
            )

        c1_result = state.get_result("C1")
        if c1_result is None or not c1_result.outputs:
            return NodeResult(
                node_id="C2",
                status=NodeStatus.SUCCESS,
                confidence=0.0,
                outputs={
                    "signals": [],
                    "signal_count": 0,
                    "dominant_direction": "NEUTRAL",
                },
                error="C2 无 C1 上游结果，降级返回空 signals",
            )

        candidates = c1_result.outputs.get("candidates") or []
        if not isinstance(candidates, list) or not candidates:
            return NodeResult(
                node_id="C2",
                status=NodeStatus.SUCCESS,
                confidence=0.0,
                outputs={
                    "signals": [],
                    "signal_count": 0,
                    "dominant_direction": "NEUTRAL",
                },
                error="C2 上游 candidates 为空",
            )

        market_data = market.get("market_data") or {}
        if not isinstance(market_data, dict):
            market_data = {}

        cfg = self._read_config(state)
        trend_threshold = cfg["trend_threshold"]
        base_conf = cfg["base_confidence"]
        max_conf = cfg["max_confidence"]

        # 2. 遍历 candidates 生成信号
        signals: List[Dict[str, Any]] = []
        long_count = 0
        short_count = 0

        for coin in candidates:
            name = str(coin or "").strip().upper()
            if not name:
                continue
            coin_data = market_data.get(name)
            if not isinstance(coin_data, dict):
                # 该币种无数据，跳过（不生成信号）
                continue

            # ── 优先路径：有 OHLCV 数据时调用 classic_pipeline.signals ──
            ohlcv = coin_data.get("ohlcv")
            if isinstance(ohlcv, list) and len(ohlcv) >= 20:
                sig = self._compute_signal_from_ohlcv(name, ohlcv, cfg)
                if sig is not None:
                    signals.append(sig)
                    if sig["direction"] == "LONG":
                        long_count += 1
                    elif sig["direction"] == "SHORT":
                        short_count += 1
                    continue

            # ── 降级路径：使用 trend/rsi/momentum 简化逻辑 ──
            trend = self._get_float(coin_data, "trend", 0.0)
            rsi = self._get_float(coin_data, "rsi", 50.0)
            momentum = self._get_float(coin_data, "momentum", 0.0)

            # 趋势方向判定
            if trend > trend_threshold:
                direction = "LONG"
                long_count += 1
            elif trend < -trend_threshold:
                direction = "SHORT"
                short_count += 1
            else:
                # |trend| <= threshold，NEUTRAL 区间，不生成信号
                continue

            confidence = self._compute_confidence(
                trend=trend,
                rsi=rsi,
                momentum=momentum,
                base=base_conf,
                max_conf=max_conf,
            )
            layer = self._pick_layer(trend, rsi, momentum)

            signals.append({
                "symbol": name,
                "direction": direction,
                "confidence": float(confidence),
                "strategy": "trend_momentum",
                "layer": layer,
                "trend": float(trend),
                "rsi": float(rsi),
                "momentum": float(momentum),
            })

        # 3. 决定 dominant_direction
        if long_count > short_count:
            dominant = "LONG"
        elif short_count > long_count:
            dominant = "SHORT"
        else:
            dominant = "NEUTRAL"  # 等量或无信号

        # 4. 节点置信度：信号数/candidates 的占比 + dominant 方向强度
        if candidates:
            coverage = len(signals) / max(1, len(candidates))
        else:
            coverage = 0.0
        # dominant 优势越强，节点置信度越高
        if signals:
            dominance = abs(long_count - short_count) / max(1, len(signals))
        else:
            dominance = 0.0
        node_confidence = _clip(coverage * 0.5 + dominance * 0.5, 0.0, max_conf)

        return NodeResult(
            node_id="C2",
            status=NodeStatus.SUCCESS,
            confidence=float(node_confidence),
            outputs={
                "signals": signals,
                "signal_count": len(signals),
                "dominant_direction": dominant,
            },
        )
