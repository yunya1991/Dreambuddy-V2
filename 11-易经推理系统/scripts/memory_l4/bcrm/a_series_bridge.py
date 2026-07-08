"""
BCRM A 股专属桥梁。

针对 A 股市场特性的适配：
- T+1 制度
- 涨跌停限制
- 北向资金
- 两融数据
- 行业板块联动
- A 股特有的情绪指标
"""

from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional


@dataclass
class AShareSnapshot:
    """A 股市场快照。"""
    price: float = 0.0
    volume: float = 0.0
    turnover_rate: float = 0.0
    pe_ratio: float = 0.0
    pb_ratio: float = 0.0
    market_cap: float = 0.0
    north_bound_flow: float = 0.0  # 北向资金
    south_bound_flow: float = 0.0  # 南向资金
    margin_balance: float = 0.0  # 融资余额
    margin_buy: float = 0.0  # 融资买入
    short_balance: float = 0.0  # 融券余额
    limit_up: bool = False  # 是否涨停
    limit_down: bool = False  # 是否跌停
    sector: str = ""  # 所属行业
    sector_index_change: float = 0.0  # 行业指数涨跌幅
    index_change: float = 0.0  # 大盘涨跌幅
    limit_up_count: int = 0  # 涨停数
    limit_down_count: int = 0  # 跌停数
    sentiment_index: float = 0.5  # 情绪指数

    def to_dict(self) -> Dict[str, Any]:
        return {
            "price": self.price,
            "volume": self.volume,
            "turnover_rate": self.turnover_rate,
            "pe_ratio": self.pe_ratio,
            "pb_ratio": self.pb_ratio,
            "market_cap": self.market_cap,
            "north_bound_flow": self.north_bound_flow,
            "south_bound_flow": self.south_bound_flow,
            "margin_balance": self.margin_balance,
            "margin_buy": self.margin_buy,
            "short_balance": self.short_balance,
            "limit_up": self.limit_up,
            "limit_down": self.limit_down,
            "sector": self.sector,
            "sector_index_change": self.sector_index_change,
            "index_change": self.index_change,
            "limit_up_count": self.limit_up_count,
            "limit_down_count": self.limit_down_count,
            "sentiment_index": self.sentiment_index,
        }


class AShareBridge:
    """
    A 股专属桥梁。

    负责将 A 股特有数据转换为 BCRM 可用的输入，
    并将 BCRM 输出适配为 A 股交易策略。
    """

    def __init__(self, limit_up_pct: float = 0.10, limit_down_pct: float = 0.10):
        self.limit_up_pct = limit_up_pct
        self.limit_down_pct = limit_down_pct

    def normalize_snapshot(self,
                            snapshot: Dict[str, Any],
                            a_share: AShareSnapshot = None
                            ) -> Dict[str, Any]:
        """
        将 A 股快照标准化为 BCRM 输入。

        Args:
            snapshot: 通用市场快照
            a_share: A 股专属快照

        Returns:
            增强后的市场快照
        """
        result = dict(snapshot)

        if a_share is None:
            return result

        # 涨跌停状态
        result["limit_up"] = a_share.limit_up
        result["limit_down"] = a_share.limit_down
        result["turnover_rate"] = a_share.turnover_rate
        result["pe_ratio"] = a_share.pe_ratio
        result["pb_ratio"] = a_share.pb_ratio
        result["market_cap"] = a_share.market_cap
        result["sector"] = a_share.sector

        # 北向资金评分 ( -1 到 1 → 0 到 1)
        north_score = self._normalize_flow(a_share.north_bound_flow)
        result["north_bound_score"] = north_score

        # 两融评分
        margin_score = self._normalize_margin(a_share.margin_buy,
                                               a_share.margin_balance)
        result["margin_score"] = margin_score

        # 情绪指数
        result["a_share_sentiment"] = a_share.sentiment_index

        # 市场宽度
        market_breadth = self._compute_market_breadth(
            a_share.limit_up_count, a_share.limit_down_count)
        result["market_breadth"] = market_breadth

        # 行业联动
        sector_alpha = result.get("price_change", 0) - a_share.sector_index_change
        result["sector_alpha"] = sector_alpha

        return result

    def _normalize_flow(self, flow: float) -> float:
        """标准化资金流向。"""
        # 简单归一化：假设单日最大流 100 亿
        max_flow = 1e10  # 100 亿
        normalized = max(-1.0, min(1.0, flow / max_flow))
        return (normalized + 1.0) / 2.0

    def _normalize_margin(self, margin_buy: float, margin_balance: float) -> float:
        """标准化两融数据。"""
        if margin_balance <= 0:
            return 0.5
        ratio = margin_buy / margin_balance
        # 正常范围 0-5%
        normalized = min(1.0, ratio / 0.05)
        return normalized

    def _compute_market_breadth(self,
                                 limit_up_count: int,
                                 limit_down_count: int) -> float:
        """计算市场宽度。"""
        total = limit_up_count + limit_down_count
        if total == 0:
            return 0.5
        return limit_up_count / total

    def adjust_confidence(self,
                           base_confidence: float,
                           snapshot: Dict[str, Any]) -> float:
        """
        根据 A 股特性调整置信度。

        - 涨跌停时降低置信度（无法交易）
        - 北向资金大幅流入时提高置信度
        - 两融异常时降低置信度
        """
        confidence = base_confidence

        # 涨跌停调整
        if snapshot.get("limit_up", False):
            confidence *= 0.7  # 涨停时无法买入
        if snapshot.get("limit_down", False):
            confidence *= 0.5  # 跌停时无法卖出

        # 北向资金调整
        north_score = snapshot.get("north_bound_score", 0.5)
        if north_score > 0.8:
            confidence *= 1.1
        elif north_score < 0.2:
            confidence *= 0.9

        # 换手率调整
        turnover = snapshot.get("turnover_rate", 0)
        if turnover > 20:  # 高换手
            confidence *= 0.85

        # 市场宽度调整
        breadth = snapshot.get("market_breadth", 0.5)
        if breadth > 0.9 or breadth < 0.1:
            confidence *= 0.9  # 极端行情

        return max(0.0, min(1.0, confidence))

    def adjust_position_size(self,
                              base_position: float,
                              snapshot: Dict[str, Any]) -> float:
        """
        根据 A 股特性调整仓位。

        - T+1 制度下降低仓位
        - 涨跌停时禁止开仓
        - 波动率高时降低仓位
        """
        position = base_position

        # T+1 调整：日内风险，降低 20%
        position *= 0.8

        # 涨跌停
        if snapshot.get("limit_up", False) or snapshot.get("limit_down", False):
            position = 0.0  # 涨跌停不交易

        # 波动率调整
        vol = snapshot.get("volatility", 0.02)
        if vol > 0.05:
            position *= 0.7
        elif vol > 0.03:
            position *= 0.85

        return max(0.0, min(1.0, position))

    def apply_t1_rule(self,
                       strategy: Dict[str, Any],
                       has_position: bool = False,
                       position_side: str = "LONG") -> Dict[str, Any]:
        """
        应用 T+1 规则。

        Args:
            strategy: 原始策略
            has_position: 是否持仓
            position_side: 持仓方向

        Returns:
            调整后的策略
        """
        result = dict(strategy)

        # T+1: 当日买入不能当日卖出
        action = result.get("action", "HOLD")

        if has_position and action == "SELL":
            # 如果是当日买入的，禁止卖出
            if result.get("same_day_buy", False):
                result["action"] = "HOLD"
                result["reason"] = "T+1 规则限制，当日买入不可卖出"

        if not has_position and action == "SHORT":
            # A 股做空限制多，需融券
            result["action"] = "HOLD"
            result["reason"] = "A 股做空需融券，暂不执行"

        return result

    def get_sector_rotation_signal(self,
                                    sector: str,
                                    sector_map: Dict[str, float] = None) -> float:
        """
        行业轮动信号。

        Args:
            sector: 当前行业
            sector_map: 行业涨跌幅映射

        Returns:
            轮动信号 (-1 到 1)
        """
        if not sector_map:
            return 0.0

        sectors = list(sector_map.items())
        sectors.sort(key=lambda x: x[1], reverse=True)

        current_change = sector_map.get(sector, 0)
        rank = 0
        for i, (s, c) in enumerate(sectors):
            if s == sector:
                rank = i
                break

        # 排名转换为信号
        n = len(sectors)
        if n <= 1:
            return 0.0

        normalized_rank = rank / (n - 1)  # 0 = 最强, 1 = 最弱
        signal = 1.0 - normalized_rank * 2  # 映射到 -1 ~ 1
        return signal

    def generate_ashare_strategy(self,
                                  bcrm_strategy: Dict[str, Any],
                                  snapshot: Dict[str, Any],
                                  a_share: AShareSnapshot = None,
                                  has_position: bool = False,
                                  position_side: str = "LONG"
                                  ) -> Dict[str, Any]:
        """
        生成 A 股专属策略。

        整合所有 A 股调整：
        1. 置信度调整
        2. 仓位调整
        3. T+1 规则
        4. 涨跌停限制
        5. 行业轮动
        """
        strategy = dict(bcrm_strategy)

        # 增强快照
        enhanced = self.normalize_snapshot(snapshot, a_share)

        # 调整置信度
        base_conf = strategy.get("confidence", 0.5)
        strategy["ashare_confidence"] = self.adjust_confidence(
            base_conf, enhanced)

        # 调整仓位
        base_pos = strategy.get("position_size", 0.0)
        strategy["ashare_position_size"] = self.adjust_position_size(
            base_pos, enhanced)

        # 应用 T+1
        strategy = self.apply_t1_rule(
            strategy, has_position, position_side)

        # 行业轮动信号
        sector = enhanced.get("sector", "")
        strategy["sector_rotation_signal"] = 0.0  # 默认值

        # 添加风险提示
        risk_notes = []
        if enhanced.get("limit_up", False):
            risk_notes.append("涨停无法买入")
        if enhanced.get("limit_down", False):
            risk_notes.append("跌停无法卖出")
        if enhanced.get("turnover_rate", 0) > 15:
            risk_notes.append("高换手，注意风险")

        strategy["ashare_risk_notes"] = risk_notes

        return strategy


def default_ashare_bridge() -> AShareBridge:
    """获取默认 A 股桥梁。"""
    return AShareBridge()
