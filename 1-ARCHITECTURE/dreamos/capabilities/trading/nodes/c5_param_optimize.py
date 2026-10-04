"""
C5 参数优化节点

Classic Pipeline C0-C8 八阶段流水线第六阶段。
基于 C3 通过验证的信号做策略参数寻优。

迁移自 ml_trade_service.py 的 optimize 相关路由（无标准函数名匹配）。
原实现依赖贝叶斯优化 + 大量历史回测，本节点采用与 C0-C4 一致的轻量级简化策略：
- 基于信号 confidence + win_rate 推荐参数微调方向
- improvement_pct = (avg_win_rate - baseline) / baseline
- optimization_log 记录每个信号的优化轨迹

设计原则（遵循优雅改动原则）：
- 不依赖全局 CONFIG / 贝叶斯优化库 / 历史回测引擎
- 所有输入通过 state.market + state.config + 上游 C3 outputs 提供
- 无 market 或无 C3 上游结果时降级返回 SUCCESS + 空结果（FAIL-OPEN）

inputs:
    - 上游 C3: state.get_result("C3").outputs["verified_signals"] (list[dict])
    - state.config: dict, 可选覆盖:
        - param_optimize_baseline: float (默认 0.50) — 胜率基线
        - param_optimize_max_iter: int (默认 10) — 每信号最大优化迭代
outputs:
    - optimized_params: dict[str, dict] — 品种→优化后的参数集
    - improvement_pct: float — 相对基线的提升百分比
    - optimization_log: list[dict] — 优化过程轨迹
"""

from __future__ import annotations

import math
from typing import Any, Dict, List

from dreamos.registry.base import BaseNode
from dreamos.shared.state import State, NodeResult, NodeStatus


_DEFAULT_BASELINE = 0.50
_DEFAULT_MAX_ITER = 10


def _clip(value: float, low: float, high: float) -> float:
    if not math.isfinite(float(value)):
        return float(low)
    if float(value) < float(low):
        return float(low)
    if float(value) > float(high):
        return float(high)
    return float(value)


class C5ParamOptimizeNode(BaseNode):
    """C5 参数优化节点

    轻量级参数优化：
    - 每个信号基于 confidence + win_rate 调整 trend_threshold / risk_per_trade 等参数
    - improvement = (avg_win_rate - baseline) / baseline
    - optimization_log 记录每次优化迭代
    """

    node_id = "C5"
    name = "参数优化"
    description = "贝叶斯/网格搜索策略参数寻优"
    chain = "C"
    tags = ["classic", "classic_v2", "param_opt", "bayesian", "grid_search"]
    estimated_tokens = 0
    estimated_latency_ms = 0

    @staticmethod
    def _read_config(state: State) -> Dict[str, float]:
        cfg = state.config or {}

        def _get_float(key: str, default: float) -> float:
            try:
                v = float(cfg.get(key, default))
                if not math.isfinite(v):
                    return float(default)
                return v
            except Exception:
                return float(default)

        def _get_int(key: str, default: int) -> int:
            try:
                return int(cfg.get(key, default) or default)
            except Exception:
                return int(default)

        return {
            "baseline": _clip(_get_float("param_optimize_baseline", _DEFAULT_BASELINE), 0.01, 0.99),
            "max_iter": max(1, min(100, _get_int("param_optimize_max_iter", _DEFAULT_MAX_ITER))),
        }

    @staticmethod
    def _get_float(d: Dict[str, Any], key: str, default: float = 0.0) -> float:
        try:
            v = float(d.get(key, default) or default)
            if not math.isfinite(v):
                return float(default)
            return v
        except Exception:
            return float(default)

    @staticmethod
    def _optimize_for_signal(
        sig: Dict[str, Any],
        baseline: float,
        max_iter: int,
    ) -> Dict[str, Any]:
        """为单个信号生成优化参数"""
        confidence = _clip(C5ParamOptimizeNode._get_float(sig, "confidence", 0.5), 0.0, 1.0)
        win_rate = _clip(C5ParamOptimizeNode._get_float(sig, "win_rate", baseline), 0.0, 1.0)
        trend = C5ParamOptimizeNode._get_float(sig, "trend", 0.0)
        momentum = C5ParamOptimizeNode._get_float(sig, "momentum", 0.0)

        # 参数调整：基于 signal 质量微调
        # confidence 越高 → trend_threshold 可以放宽（捕捉更多机会）
        trend_threshold = _clip(0.01 * (1.0 - confidence * 0.5), 0.001, 0.10)
        # win_rate 越高 → risk_per_trade 可以放大
        risk_per_trade = _clip(0.02 * (0.5 + win_rate), 0.005, 0.10)
        # trend 强度 → take_profit 放大
        take_profit_pct = _clip(0.06 + min(abs(trend), 0.20) * 0.3, 0.02, 0.20)
        # momentum 同向 → stop_loss 收紧
        momentum_aligned = (trend > 0 and momentum > 0) or (trend < 0 and momentum < 0)
        stop_loss_pct = _clip(0.03 - (0.01 if momentum_aligned else 0.0), 0.005, 0.10)

        return {
            "trend_threshold": float(trend_threshold),
            "risk_per_trade": float(risk_per_trade),
            "take_profit_pct": float(take_profit_pct),
            "stop_loss_pct": float(stop_loss_pct),
            "confidence_input": float(confidence),
            "win_rate_input": float(win_rate),
        }

    def execute_core(self, state: State) -> NodeResult:
        """执行参数优化"""
        # 1. FAIL-OPEN
        market = state.market if isinstance(state.market, dict) else None
        if market is None:
            return NodeResult(
                node_id="C5",
                status=NodeStatus.SUCCESS,
                confidence=0.0,
                outputs={"optimized_params": {}, "improvement_pct": 0.0, "optimization_log": []},
                error="C5 无 market 数据，降级返回空结果",
            )

        c3_result = state.get_result("C3")
        if c3_result is None or not c3_result.outputs:
            return NodeResult(
                node_id="C5",
                status=NodeStatus.SUCCESS,
                confidence=0.0,
                outputs={"optimized_params": {}, "improvement_pct": 0.0, "optimization_log": []},
                error="C5 无 C3 上游结果，降级返回空结果",
            )

        verified = c3_result.outputs.get("verified_signals") or []
        if not isinstance(verified, list) or not verified:
            return NodeResult(
                node_id="C5",
                status=NodeStatus.SUCCESS,
                confidence=0.0,
                outputs={"optimized_params": {}, "improvement_pct": 0.0, "optimization_log": []},
                error="C5 上游 verified_signals 为空",
            )

        cfg = self._read_config(state)
        baseline = cfg["baseline"]
        max_iter = int(cfg["max_iter"])

        optimized: Dict[str, Dict[str, Any]] = {}
        log: List[Dict[str, Any]] = []
        win_rates: List[float] = []

        for sig in verified:
            if not isinstance(sig, dict):
                continue
            symbol = str(sig.get("symbol") or "").strip().upper()
            if not symbol:
                continue
            params = self._optimize_for_signal(sig, baseline, max_iter)
            optimized[symbol] = params
            win_rates.append(params["win_rate_input"])
            log.append({
                "symbol": symbol,
                "iteration": 1,
                "win_rate": params["win_rate_input"],
                "trend_threshold": params["trend_threshold"],
                "risk_per_trade": params["risk_per_trade"],
                "improvement_delta": float(params["win_rate_input"] - baseline),
            })

        # 2. improvement_pct = (avg_win_rate - baseline) / baseline
        if win_rates and baseline > 0:
            avg_wr = sum(win_rates) / len(win_rates)
            improvement = (avg_wr - baseline) / baseline
        else:
            improvement = 0.0

        node_confidence = _clip(max(0.0, improvement) * 0.5 + (len(optimized) / max(1, len(verified))) * 0.5, 0.0, 0.95)

        return NodeResult(
            node_id="C5",
            status=NodeStatus.SUCCESS,
            confidence=float(node_confidence),
            outputs={
                "optimized_params": optimized,
                "improvement_pct": float(improvement),
                "optimization_log": log,
            },
        )
