#!/usr/bin/env python3
"""
易经因子币种过滤模块 (Yijing Coin Selector)

职责：
  基于易经 risk/value 评分对候选币种做过滤和排序，作为 V15 选币的主要因子。

设计原则：
  - 独立于 YijingBridge（接收已计算好的评分，不自己推理）
  - 可被回测（批量）和实盘（单次）共用
  - 过滤策略：剔除高风险低价值币种，优先选择趋势友好币种
  - 不硬编码币种列表，接收外部候选池

用法：
  from coin_selector import YijingCoinSelector
  selector = YijingCoinSelector()
  # 批量（实盘/回测准备阶段）
  selected = selector.filter_coins({
      "BTC": {"risk_score": 0.3, "value_score": 0.8},
      "ETH": {"risk_score": 0.7, "value_score": 0.2},
  })
  # → ["BTC"]  (ETH 被过滤)
"""
from typing import Dict, List, Optional


class YijingCoinSelector:
    """基于易经 risk/value 的币种过滤

    过滤规则：
      1. DANGER（risk高+value低）→ 剔除
      2. HIGH_VALUE_RISK（risk高+value高）→ 保留但降权（标记）
      3. TREND_FRIENDLY（risk低+value高）→ 最高优先
      4. 其余 → 保留
      5. 若 max_select 指定，按 net_value(value-risk) 降序取前 N
    """

    # 风险阈值：risk > 此值视为高风险
    RISK_HIGH_THRESHOLD = 0.60
    # 价值阈值：value < 此值且 risk 高 → 剔除
    VALUE_LOW_THRESHOLD = 0.40

    def __init__(
        self,
        risk_high: float = None,
        value_low: float = None,
    ):
        if risk_high is not None:
            self.RISK_HIGH_THRESHOLD = risk_high
        if value_low is not None:
            self.VALUE_LOW_THRESHOLD = value_low

    def _classify(self, risk: float, value: float) -> str:
        """单币种分类"""
        if risk > self.RISK_HIGH_THRESHOLD and value < self.VALUE_LOW_THRESHOLD:
            return "DANGER"
        if risk > self.RISK_HIGH_THRESHOLD and value >= 0.55:
            return "HIGH_VALUE_RISK"
        if risk < 0.45 and value > 0.55:
            return "TREND_FRIENDLY"
        return "NORMAL"

    def filter_coins(
        self,
        coins_with_scores: Dict[str, Dict[str, float]],
        max_select: Optional[int] = None,
    ) -> List[str]:
        """过滤并排序币种

        Args:
            coins_with_scores: {coin: {"risk_score": 0.x, "value_score": 0.x}}
            max_select: 最多选 N 个（None=不限制）

        Returns:
            过滤后的币种列表（按 net_value 降序）
        """
        scored = []
        for coin, scores in coins_with_scores.items():
            risk = scores.get("risk_score", 0.5)
            value = scores.get("value_score", 0.5)
            category = self._classify(risk, value)

            # DANGER 币种直接剔除
            if category == "DANGER":
                continue

            net_value = value - risk
            scored.append((coin, net_value, category))

        # 按 net_value 降序排序
        scored.sort(key=lambda x: x[1], reverse=True)

        if max_select is not None and max_select > 0:
            scored = scored[:max_select]

        return [item[0] for item in scored]

    def filter_with_detail(
        self,
        coins_with_scores: Dict[str, Dict[str, float]],
        max_select: Optional[int] = None,
    ) -> List[Dict]:
        """过滤并返回详细信息（含分类和评分）

        Returns:
            [{"coin": "BTC", "risk": 0.3, "value": 0.8, "net": 0.5, "category": "TREND_FRIENDLY"}, ...]
        """
        scored = []
        for coin, scores in coins_with_scores.items():
            risk = scores.get("risk_score", 0.5)
            value = scores.get("value_score", 0.5)
            category = self._classify(risk, value)

            if category == "DANGER":
                continue

            scored.append({
                "coin": coin,
                "risk": round(risk, 3),
                "value": round(value, 3),
                "net": round(value - risk, 3),
                "category": category,
            })

        scored.sort(key=lambda x: x["net"], reverse=True)

        if max_select is not None and max_select > 0:
            scored = scored[:max_select]

        return scored
