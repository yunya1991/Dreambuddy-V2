"""
ReflexivityMonitor — 反身性监测
理论文档: 三维度矛盾论理论框架.md §10

Soros 反身性理论: 认知影响现实，现实反过来改变认知.
在交易系统中: 系统判断主矛盾→交易→交易本身影响市场→改变矛盾结构.

核心功能:
  1. 追踪系统仓位方向 vs 后续基本面变化（Granger 检验）
  2. 计算自影响系数（系统交易对市场的影响程度）
  3. 当自影响显著时，调整主矛盾力量度量（加入自影响项）

自影响模型:
  S_adjusted = S_exogenous + λ × S_self
  λ = f(market_share, position_size, holding_period)
"""
from __future__ import annotations

import logging
from collections import deque
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)

try:
    from dreambuddy_evolution.core.granger_causality_checker import GrangerCausalityChecker
    _HAS_GRANGER = True
except ImportError:
    _HAS_GRANGER = False


class ReflexivityMonitor:
    """
    反身性监测器: 追踪系统交易对矛盾结构的反馈影响.

    当系统交易规模相对于市场流动性足够大时，
    交易行为本身会改变市场结构（尤其加密市场）.
    """

    def __init__(self, lookback: int = 50, significance: float = 0.05):
        """
        Args:
            lookback: 历史窗口大小
            significance: Granger 检验显著性水平
        """
        self._lookback = lookback
        self._significance = significance

        # 历史数据
        self._position_history: deque = deque(maxlen=lookback)
        self._etf_flow_history: deque = deque(maxlen=lookback)
        self._price_history: deque = deque(maxlen=lookback)
        self._market_share_history: deque = deque(maxlen=lookback)

        # Granger 检验器
        self._granger = GrangerCausalityChecker(max_lag=5, significance=significance) if _HAS_GRANGER else None

        # 自影响系数缓存
        self._self_influence: float = 0.0
        self._last_check_time: float = 0.0

        # §19 认知函数（索罗斯认知函数 C=认知→行为）
        try:
            from dreambuddy_evolution.core.cognitive_function import CognitiveFunction
            self._cognitive_fn = CognitiveFunction(prior_strength=0.5, learning_rate=0.1)
        except ImportError:
            self._cognitive_fn = None

    def record(self, position_delta: float, etf_flow: float | None,
               price: float, market_volume: float | None = None):
        """记录一个时点的数据."""
        self._position_history.append(position_delta)
        self._etf_flow_history.append(etf_flow if etf_flow is not None else 0.0)
        self._price_history.append(price)

        # 市场份额 = 系统仓位变动 / 市场成交量
        if market_volume is not None and market_volume > 0:
            share = abs(position_delta) / market_volume
        else:
            share = 0.0
        self._market_share_history.append(min(1.0, share))

    def check_self_influence(self) -> dict[str, Any]:
        """
        检验系统交易是否 Granger-cause 后续基本面变化.

        Returns:
            {
                "self_influence_detected": bool,
                "p_value": float,
                "market_share": float,      # 系统交易占市场比例
                "influence_coefficient": float,  # 自影响系数 λ
                "adjustment_needed": bool,  # 是否需要调整力量度量
            }
        """
        if len(self._position_history) < 20 or len(self._etf_flow_history) < 20:
            return {
                "self_influence_detected": False,
                "p_value": 1.0,
                "market_share": 0.0,
                "influence_coefficient": 0.0,
                "adjustment_needed": False,
            }

        positions = np.array(self._position_history, dtype=float)
        etf_flows = np.array(self._etf_flow_history, dtype=float)
        market_shares = np.array(self._market_share_history, dtype=float)

        # 平均市场份额
        avg_market_share = float(np.mean(market_shares))

        # Granger 检验: 系统仓位 → ETF 资金流
        granger_result = None
        if self._granger is not None:
            granger_result = self._granger.check(positions.tolist(), etf_flows.tolist())

        # 自影响系数 λ
        # λ = f(market_share, position_volatility, price_impact)
        if avg_market_share > 0:
            # 市场份额越大，自影响越大
            # 价格冲击 = 仓位变动对价格的影响
            price_changes = np.diff(np.array(self._price_history, dtype=float))
            position_changes = np.diff(positions)
            if len(price_changes) > 0 and len(position_changes) > 0:
                min_len = min(len(price_changes), len(position_changes))
                pc = price_changes[:min_len]
                po = position_changes[:min_len]
                # 简单回归系数作为价格冲击代理
                if np.std(po) > 1e-9:
                    price_impact = abs(np.corrcoef(po, pc)[0, 1]) if np.std(pc) > 1e-9 else 0.0
                else:
                    price_impact = 0.0
            else:
                price_impact = 0.0

            # λ = market_share × (1 + price_impact)
            lam = avg_market_share * (1.0 + max(0.0, min(1.0, price_impact)))
        else:
            lam = 0.0

        self._self_influence = lam

        # 判断
        detected = False
        p_value = 1.0
        if granger_result is not None:
            p_value = granger_result.get("p_value", 1.0)
            detected = granger_result.get("is_granger_cause", False)

        # 市场份额 > 1% 也可视为有自影响
        if avg_market_share > 0.01:
            detected = detected or True

        adjustment_needed = detected and lam > 0.02

        return {
            "self_influence_detected": detected,
            "p_value": p_value,
            "market_share": avg_market_share,
            "influence_coefficient": round(lam, 6),
            "adjustment_needed": adjustment_needed,
        }

    def adjust_strength(self, exogenous_strength: float) -> float:
        """
        调整力量度量: 加入自影响项.

        S_adjusted = S_exogenous + λ × S_self
        其中 S_self = 系统仓位方向的一致性（系统持续同方向交易 = 自增强）

        Returns: 调整后的力量值
        """
        if self._self_influence < 0.02:
            return exogenous_strength

        # S_self: 系统仓位方向的一致性
        positions = np.array(self._position_history, dtype=float)
        if positions.size < 5:
            return exogenous_strength

        # 方向一致性: 同方向交易占比
        signs = np.sign(positions)
        nonzero_signs = signs[signs != 0]
        if nonzero_signs.size == 0:
            return exogenous_strength

        dominant_direction = np.sign(np.sum(nonzero_signs))
        consistency = np.mean(nonzero_signs == dominant_direction)
        s_self = abs(float(dominant_direction)) * consistency

        # S_adjusted = S_exogenous + λ × S_self
        adjusted = exogenous_strength + self._self_influence * s_self

        # 截断 [0, 1]
        return max(0.0, min(1.0, adjusted))

    def adjust_cognition(self, info_signals: list[dict]) -> dict:
        """§19 认知函数: 基于信息流更新认知状态.

        索罗斯反身性环 = C∘P（认知→行为→市场影响→新信息流→认知更新）
        贝叶斯信念更新: belief += lr × weight × (signal - belief)

        Args:
            info_signals: [{type: "price"/"news"/"fundamental", signal: float, weight: float}]
                          signal [0,1]: <0.5利空, >0.5利多

        Returns:
            {"cognition": float, "cognition_delta": float, "reflexivity_loop_active": bool}
        """
        if self._cognitive_fn is None or not info_signals:
            return {
                "cognition": 0.5,
                "cognition_delta": 0.0,
                "reflexivity_loop_active": False,
            }

        try:
            old_belief = self._cognitive_fn.get_cognition()
            for signal in info_signals:
                sig_val = float(signal.get("signal", 0.5))
                sig_weight = float(signal.get("weight", 1.0))
                self._cognitive_fn.update(sig_val, sig_weight)

            new_belief = self._cognitive_fn.get_cognition()
            delta = new_belief - old_belief

            return {
                "cognition": new_belief,
                "cognition_delta": round(delta, 6),
                "reflexivity_loop_active": abs(delta) > 0.01,
            }
        except Exception:
            return {
                "cognition": 0.5,
                "cognition_delta": 0.0,
                "reflexivity_loop_active": False,
            }
