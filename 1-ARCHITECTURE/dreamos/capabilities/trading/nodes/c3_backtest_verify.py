"""
C3 回测验证节点

Classic Pipeline C0-C8 八阶段流水线第四阶段。
对 C2 识别出的 signals 做历史回测验证，过滤低质信号，产出 verified_signals/win_rate/sharpe/max_dd。

迁移自 ml_trade_service.py 的 backtest 相关路由（无标准函数名匹配）。
原实现依赖 pandas + 大量历史 K 线 + 复杂指标计算，
本节点采用与 C0/C1/C2 一致的轻量级简化策略：
- 基于 signal 自身的 confidence + trend/momentum 同向性模拟胜率
- 累积期望盈亏序列 → 计算 sharpe / max_dd
- 过滤 confidence < threshold 的信号

设计原则（遵循优雅改动原则）：
- 不依赖全局 CONFIG / pandas / freqtrade / 历史 K 线数据
- 所有输入通过 state.market + state.config + 上游 C2 outputs 提供
- 无 market 或无 C2 上游结果时降级返回 SUCCESS + 空结果（FAIL-OPEN）

inputs:
    - 上游 C2: state.get_result("C2").outputs["signals"] (list[dict])
      每项含: symbol, direction, confidence, trend, rsi, momentum, strategy, layer
    - state.config: dict, 可选覆盖阈值:
        - backtest_confidence_threshold: float (默认 0.55) — 信号通过验证的最低置信度
        - backtest_trend_weight: float (默认 0.5) — trend 强度对胜率的加成权重
        - backtest_momentum_weight: float (默认 0.2) — momentum 同向对胜率的加成权重
outputs:
    - verified_signals: list[dict] — 通过验证的信号，每项含原字段 + win_rate(float)
    - win_rate: float — 整体胜率（通过信号的平均胜率）
    - sharpe: float — 夏普比率（基于期望盈亏序列）
    - max_dd: float — 最大回撤（[0, +∞)，0 表示无回撤）
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional

from dreamos.registry.base import BaseNode
from dreamos.shared.state import State, NodeResult, NodeStatus

# 可选导入 backtrader 适配器（FAIL-OPEN：未安装/异常不影响主流程）
try:
    from ...backtest.backtrader_adapter import enhance_signals as _bt_enhance
except ImportError:
    _bt_enhance = None  # type: ignore


# ── 默认阈值 ──────────────────────────────────────────────
_DEFAULT_CONFIDENCE_THRESHOLD = 0.55
_DEFAULT_TREND_WEIGHT = 0.5
_DEFAULT_MOMENTUM_WEIGHT = 0.2


def _clip(value: float, low: float, high: float) -> float:
    if not math.isfinite(float(value)):
        return float(low)
    if float(value) < float(low):
        return float(low)
    if float(value) > float(high):
        return float(high)
    return float(value)


class C3BacktestVerifyNode(BaseNode):
    """C3 回测验证节点

    轻量级回测验证：
    1. 基于信号 confidence + trend/momentum 同向性计算模拟胜率
    2. 过滤低质信号（confidence < threshold 或胜率 < 0.5）
    3. 累积期望盈亏序列 → 计算 sharpe / max_dd

    下游 C4 通过 state.get_result("C3").outputs["verified_signals"] 访问。

    设计原则（遵循优雅改动原则）：
    - 不依赖全局 CONFIG / pandas / 历史 K 线
    - 所有输入通过 state.market + state.config + 上游 C2 outputs 提供
    - 无 market 或无 C2 上游结果时降级返回 SUCCESS + 空结果（FAIL-OPEN）
    """

    node_id = "C3"
    name = "回测验证"
    description = "对识别出的信号做历史回测验证，输出胜率/夏普/最大回撤"
    chain = "C"
    tags = ["classic", "classic_v2", "backtest", "verification"]
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

        return {
            "confidence_threshold": _clip(_get_float("backtest_confidence_threshold", _DEFAULT_CONFIDENCE_THRESHOLD), 0.0, 1.0),
            "trend_weight": max(0.0, _get_float("backtest_trend_weight", _DEFAULT_TREND_WEIGHT)),
            "momentum_weight": max(0.0, _get_float("backtest_momentum_weight", _DEFAULT_MOMENTUM_WEIGHT)),
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
    def _compute_signal_win_rate(
        signal: Dict[str, Any],
        trend_weight: float,
        momentum_weight: float,
    ) -> float:
        """计算单信号的模拟胜率

        win_rate = clip(confidence + |trend|*trend_weight + momentum_bonus, 0, 1)
        momentum_bonus: momentum 与 trend 同向时为 +|momentum|*momentum_weight，否则 0
        """
        conf = _clip(C3BacktestVerifyNode._get_float(signal, "confidence", 0.5), 0.0, 1.0)
        trend = C3BacktestVerifyNode._get_float(signal, "trend", 0.0)
        momentum = C3BacktestVerifyNode._get_float(signal, "momentum", 0.0)

        # trend 强度加成
        win = conf + min(abs(trend), 0.20) * trend_weight

        # momentum 同向加成
        if (trend > 0 and momentum > 0) or (trend < 0 and momentum < 0):
            win += min(abs(momentum), 0.10) * momentum_weight

        return _clip(win, 0.0, 1.0)

    @staticmethod
    def _compute_sharpe(pnl_list: List[float]) -> float:
        """基于期望盈亏序列计算夏普比率

        每笔交易 pnl = (2 * win_rate - 1)，即胜则 +1 败则 -1 的期望
        sharpe = mean / std（std=0 时退化为 mean）
        """
        if not pnl_list:
            return 0.0
        n = len(pnl_list)
        mean = sum(pnl_list) / n
        var = sum((x - mean) ** 2 for x in pnl_list) / max(1, n)
        std = math.sqrt(var)
        if std < 1e-9:
            return float(mean)
        return float(mean / std)

    @staticmethod
    def _compute_max_dd(cum_pnl: List[float]) -> float:
        """计算最大回撤

        max_dd = max(peak - cum[t]) over all t
        """
        if not cum_pnl:
            return 0.0
        peak = cum_pnl[0]
        max_dd = 0.0
        for v in cum_pnl:
            if v > peak:
                peak = v
            dd = peak - v
            if dd > max_dd:
                max_dd = dd
        return float(max_dd)

    def execute_core(self, state: State) -> NodeResult:
        """执行回测验证

        流程：
            1. 读取上游 C2 signals + state.config
            2. 对每个 signal 计算模拟胜率
            3. 过滤 confidence < threshold 或 win_rate < 0.5 的信号
            4. 计算 sharpe / max_dd / 整体 win_rate
        """
        # 1. FAIL-OPEN：无 market 或无 C2 上游结果
        market = state.market if isinstance(state.market, dict) else None
        if market is None:
            return NodeResult(
                node_id="C3",
                status=NodeStatus.SUCCESS,
                confidence=0.0,
                outputs={
                    "verified_signals": [],
                    "win_rate": 0.0,
                    "sharpe": 0.0,
                    "max_dd": 0.0,
                    "backtest_source": "simplified",
                },
                error="C3 无 market 数据，降级返回空结果",
            )

        c2_result = state.get_result("C2")
        if c2_result is None or not c2_result.outputs:
            return NodeResult(
                node_id="C3",
                status=NodeStatus.SUCCESS,
                confidence=0.0,
                outputs={
                    "verified_signals": [],
                    "win_rate": 0.0,
                    "sharpe": 0.0,
                    "max_dd": 0.0,
                    "backtest_source": "simplified",
                },
                error="C3 无 C2 上游结果，降级返回空结果",
            )

        signals = c2_result.outputs.get("signals") or []
        if not isinstance(signals, list) or not signals:
            return NodeResult(
                node_id="C3",
                status=NodeStatus.SUCCESS,
                confidence=0.0,
                outputs={
                    "verified_signals": [],
                    "win_rate": 0.0,
                    "sharpe": 0.0,
                    "max_dd": 0.0,
                    "backtest_source": "simplified",
                },
                error="C3 上游 signals 为空",
            )

        cfg = self._read_config(state)
        conf_threshold = cfg["confidence_threshold"]
        trend_weight = cfg["trend_weight"]
        momentum_weight = cfg["momentum_weight"]

        # 2. 逐个信号计算胜率 + 过滤
        verified: List[Dict[str, Any]] = []
        win_rates: List[float] = []
        pnl_list: List[float] = []

        for sig in signals:
            if not isinstance(sig, dict):
                continue
            sig_confidence = self._get_float(sig, "confidence", 0.0)
            if sig_confidence < conf_threshold:
                continue

            win_rate = self._compute_signal_win_rate(sig, trend_weight, momentum_weight)
            # 胜率 < 0.5 的信号视为负期望，过滤
            if win_rate < 0.5:
                continue

            verified_sig = dict(sig)  # 浅拷贝原字段
            verified_sig["win_rate"] = float(win_rate)
            verified.append(verified_sig)
            win_rates.append(win_rate)
            # 每笔交易期望 pnl = (2 * win_rate - 1)
            pnl_list.append(2.0 * win_rate - 1.0)

        # 3. 计算整体指标
        if win_rates:
            overall_win_rate = sum(win_rates) / len(win_rates)
        else:
            overall_win_rate = 0.0

        sharpe = self._compute_sharpe(pnl_list)

        # 累积 pnl 序列用于 max_dd
        cum_pnl: List[float] = []
        cum = 0.0
        for p in pnl_list:
            cum += p
            cum_pnl.append(cum)
        max_dd = self._compute_max_dd(cum_pnl)

        # 4. 节点置信度：整体 win_rate + 通过率
        pass_rate = len(verified) / max(1, len(signals))
        node_confidence = _clip(overall_win_rate * 0.6 + pass_rate * 0.4, 0.0, 0.95)

        # 5. backtrader 可选增强（FAIL-OPEN）
        # 仅在 state.config["backtest_klines"] 提供数据时触发
        # 增强成功 → 覆盖 win_rate/sharpe/max_dd，source="backtrader"
        # 增强失败/未安装 → 保持简化结果，source="simplified"
        backtest_source = "simplified"
        if _bt_enhance is not None:
            try:
                klines = (state.config or {}).get("backtest_klines")
                if klines:
                    bt_result = _bt_enhance(verified, klines)
                    if isinstance(bt_result, dict):
                        # 用 backtrader 结果覆盖简化结果（仅覆盖可比较字段）
                        if "win_rate" in bt_result:
                            overall_win_rate = float(bt_result["win_rate"])
                        if "sharpe" in bt_result:
                            sharpe = float(bt_result["sharpe"])
                        if "max_dd" in bt_result:
                            max_dd = float(bt_result["max_dd"])
                        backtest_source = "backtrader"
            except Exception:
                # FAIL-OPEN：任何异常保持简化结果
                pass

        return NodeResult(
            node_id="C3",
            status=NodeStatus.SUCCESS,
            confidence=float(node_confidence),
            outputs={
                "verified_signals": verified,
                "win_rate": float(overall_win_rate),
                "sharpe": float(sharpe),
                "max_dd": float(max_dd),
                "backtest_source": backtest_source,
            },
        )
