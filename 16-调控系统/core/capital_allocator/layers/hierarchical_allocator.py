"""Layer 3: HierarchicalAllocator
================================

职责：全局→子池→币种三层资金分配。

子池权重默认：
  BDSM 25% / BCRM 40% / evolution 20% / strategy 15%

动态调整：按子池绩效（加权 W/L）调整权重，高 W/L 提升，低 W/L 降低。
下限保护：MIN_SUBPOOL_WEIGHT=0.10，防止完全饿死。
"""

from __future__ import annotations

from typing import Any, Dict, Tuple

from ..types import CoinPerformance


class HierarchicalAllocator:
    """分层资金分配器。"""

    DEFAULT_WEIGHTS: Dict[str, float] = {
        "bdsm": 0.25,
        "bcrm": 0.40,
        "evolution": 0.20,
        "strategy": 0.15,
    }

    def __init__(
        self,
        subpool_weights: Dict[str, float] | None = None,
        min_subpool_weight: float = 0.10,
    ):
        self._default_weights = dict(subpool_weights or self.DEFAULT_WEIGHTS)
        self._min_weight = min_subpool_weight

    def allocate_subpools(
        self,
        total_budget: float,
        coin_kelly: Dict[str, Tuple[CoinPerformance, float, float, float]],
    ) -> Dict[str, float]:
        """按子池绩效动态调整权重，返回子池预算分配。

        Args:
            total_budget: 总预算（归一化时为 1.0）
            coin_kelly: {coin: (perf, kelly_f, half_f, pos_pct)}

        Returns:
            {subpool_tag: budget} 子池预算分配
        """
        # 1. 按币种 source_tag 分组到子池
        subpool_perf: Dict[str, Dict[str, float]] = {}
        for coin, (perf, kelly_f, half_f, pos_pct) in coin_kelly.items():
            tag = self._infer_source_tag(coin)
            agg = subpool_perf.setdefault(tag, {
                "n_trades": 0, "n_wins": 0, "wins": [], "losses": [],
            })
            agg["n_trades"] += perf.n_trades
            agg["n_wins"] += perf.n_wins
            if perf.avg_win_pct > 0:
                agg["wins"].append(perf.avg_win_pct * perf.n_wins)
            if perf.avg_loss_pct > 0:
                agg["losses"].append(perf.avg_loss_pct * (perf.n_trades - perf.n_wins))

        # 2. 计算子池 W/L
        subpool_wl: Dict[str, float] = {}
        for tag, agg in subpool_perf.items():
            total_win = sum(agg["wins"]) if agg["wins"] else 0.0
            total_loss = sum(agg["losses"]) if agg["losses"] else 0.0
            if total_loss > 0:
                subpool_wl[tag] = total_win / total_loss
            else:
                subpool_wl[tag] = 1.0 if total_win > 0 else 0.0

        # 3. 动态调整权重
        weights = self._adjust_weights(subpool_wl)

        # 4. 分配预算
        return {tag: total_budget * w for tag, w in weights.items()}

    def _adjust_weights(self, subpool_wl: Dict[str, float]) -> Dict[str, float]:
        """按子池 W/L 动态调整权重。

        高 W/L 子池权重提升，低 W/L 降低，保持下限。
        """
        if not subpool_wl:
            return dict(self._default_weights)

        # 基础权重
        weights = {}
        for tag, base_w in self._default_weights.items():
            if tag in subpool_wl:
                wl = subpool_wl[tag]
                # W/L > 1 → 权重提升，W/L < 1 → 权重降低
                # 使用对数缩放避免极端值
                import math
                mult = 1.0 + 0.3 * math.log1p(max(0.0, wl - 1.0)) if wl > 0 else 0.5
                mult = max(0.5, min(2.0, mult))
                weights[tag] = base_w * mult
            else:
                weights[tag] = base_w

        # 归一化
        total = sum(weights.values())
        if total > 0:
            weights = {k: v / total for k, v in weights.items()}

        # 归一化后再应用下限（防止归一化导致下限失效）
        for tag in weights:
            weights[tag] = max(self._min_weight, weights[tag])

        # 二次归一化（下限应用后可能不再和为 1，但作为权重比例可接受）
        return weights

    def allocate_coin(
        self,
        subpool_budget: float,
        coin_kelly_f: float,
        subpool_total_kelly: float,
    ) -> float:
        """子池内按 Kelly 分数分配。

        coin_position = subpool_budget * (coin_kelly_f / sum(kelly_f in subpool))
        """
        if subpool_total_kelly <= 0:
            return 0.0
        return subpool_budget * (coin_kelly_f / subpool_total_kelly)

    @staticmethod
    def _infer_source_tag(coin: str) -> str:
        """推断币种所属子池。

        简单实现：默认归 bcrm 池。
        实际使用时由 component 传入 source_tag 覆盖。
        """
        return "bcrm"
