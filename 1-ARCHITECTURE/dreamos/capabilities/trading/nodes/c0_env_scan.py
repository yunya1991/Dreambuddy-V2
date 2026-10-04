"""
C0 环境扫描节点

Classic Pipeline C0-C8 八阶段流水线的起点。
基于 BTC/ETH 价格趋势和波动率判断市场状态，产出 env_state/regime/macro_flags
供下游 C1 品种筛选消费。

迁移自 ml_trade_service.py _quant_pairs_macro_eval (L129905+) 的简化版：
- 原实现依赖 _entry_macro_btceth_tf_std_at / _macro_trend_at 等多个内部函数，
  返回 risk_budget_tier (risk_on/risk_off/risk_off_pre/neutral)。
- C0 节点采用 spec 定义的更抽象层级：regime (bull/bear/range) + macro_flags。
- 简化策略：从 state.market 读取 btc_trend/btc_volatility/eth_trend/eth_volatility
  直接分类，避免依赖复杂的 BTC/ETH 加权计算。

inputs:
    - state.market: dict, 必须包含:
        - btc_trend: float, BTC 价格趋势（如 0.05 表示 +5%）
        - btc_volatility: float, BTC 波动率
        - eth_trend: float, ETH 价格趋势（可选）
        - eth_volatility: float, ETH 波动率（可选）
    - state.config: dict, 可选覆盖阈值:
        - env_scan_volatility_threshold: float (默认 0.10) — 高波动阈值
        - env_scan_trend_threshold: float (默认 0.0) — 趋势方向阈值
outputs:
    - env_state: str — 环境状态摘要（如 "bull_low_vol" / "bear_low_vol" / "range_high_vol"）
    - regime: str — bull / bear / range
    - macro_flags: dict — 含 risk_on / risk_off / volatility_regime 三个 key
"""

from __future__ import annotations

import math
from typing import Any, Dict

from dreamos.registry.base import BaseNode
from dreamos.shared.state import State, NodeResult, NodeStatus


# ── 默认阈值 ──────────────────────────────────────────────
_DEFAULT_VOLATILITY_THRESHOLD = 0.10
_DEFAULT_TREND_THRESHOLD = 0.0


class C0EnvScanNode(BaseNode):
    """C0 环境扫描节点

    简化版环境扫描：基于 BTC 趋势 + 波动率分类 regime。
    下游 C1 通过 state.get_result("C0").outputs["env_state"] / ["regime"] 访问。

    设计原则（遵循优雅改动原则）：
    - 不依赖全局 CONFIG / _entry_macro_btceth_tf_std_at / _macro_trend_at
    - 所有输入通过 state.market + state.config 提供
    - 无 market 时降级返回 SUCCESS + None outputs（FAIL-OPEN）
    """

    node_id = "C0"
    name = "环境扫描"
    description = "宏观环境/市场状态扫描，产出 env_state/regime/macro_flags"
    chain = "C"
    tags = ["classic", "classic_v2", "env_scan", "macro", "pipeline_start"]
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
            "volatility_threshold": max(0.001, _get_float("env_scan_volatility_threshold", _DEFAULT_VOLATILITY_THRESHOLD)),
            "trend_threshold": _get_float("env_scan_trend_threshold", _DEFAULT_TREND_THRESHOLD),
        }

    @staticmethod
    def _get_float(market: Dict[str, Any], key: str, default: float = 0.0) -> float:
        """安全读取 market 中的 float 字段"""
        try:
            v = float(market.get(key, default) or default)
            if not math.isfinite(v):
                return float(default)
            return v
        except Exception:
            return float(default)

    def execute_core(self, state: State) -> NodeResult:
        """执行环境扫描

        流程：
            1. 读取 state.market + state.config
            2. 计算 BTC 趋势方向 + 波动率分类
            3. 计算 regime (bull/bear/range) + macro_flags
            4. 组装 env_state 摘要
        """
        market = state.market if isinstance(state.market, dict) else None
        if market is None:
            return NodeResult(
                node_id="C0",
                status=NodeStatus.SUCCESS,
                confidence=0.0,
                outputs={
                    "env_state": None,
                    "regime": None,
                    "macro_flags": {},
                },
                error="C0 无 market 数据，降级返回空 outputs",
            )

        cfg = self._read_config(state)
        vol_threshold = cfg["volatility_threshold"]
        trend_threshold = cfg["trend_threshold"]

        btc_trend = self._get_float(market, "btc_trend", 0.0)
        btc_vol = self._get_float(market, "btc_volatility", 0.0)
        eth_trend = self._get_float(market, "eth_trend", 0.0)
        eth_vol = self._get_float(market, "eth_volatility", 0.0)

        # 加权趋势（BTC 权重 0.7, ETH 权重 0.3，与原 _macro_btceth_input_weights 默认一致）
        weighted_trend = 0.7 * btc_trend + 0.3 * eth_trend
        weighted_vol = 0.7 * btc_vol + 0.3 * eth_vol

        # 分类 regime
        is_high_vol = weighted_vol >= vol_threshold
        if is_high_vol:
            regime = "range"
            vol_label = "high_vol"
            volatility_regime = "high"
        else:
            volatility_regime = "low"
            if weighted_trend > trend_threshold:
                regime = "bull"
                vol_label = "low_vol"
            elif weighted_trend < -abs(trend_threshold) or (trend_threshold == 0.0 and weighted_trend < 0.0):
                regime = "bear"
                vol_label = "low_vol"
            else:
                regime = "range"
                vol_label = "low_vol"

        # macro_flags
        risk_on = (regime == "bull")
        risk_off = (regime == "bear")
        macro_flags = {
            "risk_on": bool(risk_on),
            "risk_off": bool(risk_off),
            "volatility_regime": str(volatility_regime),
        }

        # env_state 摘要
        env_state = f"{regime}_{vol_label}"

        # confidence（高波动时低 confidence，趋势明确时高 confidence）
        if regime == "range" and is_high_vol:
            confidence = 0.3  # 高波动+震荡，不确定性高
        elif regime in ("bull", "bear"):
            confidence = 0.8  # 明确趋势
        else:
            confidence = 0.5  # 低波动震荡

        return NodeResult(
            node_id="C0",
            status=NodeStatus.SUCCESS,
            confidence=confidence,
            outputs={
                "env_state": env_state,
                "regime": regime,
                "macro_flags": macro_flags,
            },
        )
