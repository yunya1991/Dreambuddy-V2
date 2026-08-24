"""DalSink — SilverRecord → 19-DAL 写入桥。

将 20-数据清洗中心的 SilverRecord 按 sub_category 路由到
19-数据访问层 MarketMacroRepository 的对应 upsert_* 方法。

设计原则：
  - gate_passed=False → 不写 DAL（仅 Bronze 审计）
  - 未知 sub_category → 跳过 + log.warning
  - upsert 异常 → fail-open（跳过该行，继续写入其余行）
  - 返回成功写入行数
"""
from __future__ import annotations

import logging
from datetime import datetime
from decimal import Decimal
from typing import Any, Optional

import pandas as pd

from data_cleaning.contract import SilverRecord

logger = logging.getLogger(__name__)

# sub_category → (upsert 方法名, 所需列名列表)
_ROUTE_MAP: dict[str, tuple[str, list[str]]] = {
    "fear_greed": (
        "upsert_fear_greed",
        ["value", "value_classification", "timestamp"],
    ),
    "funding": (
        "upsert_funding_rate",
        ["funding_rate", "timestamp"],
    ),
    "open_interest": (
        "upsert_open_interest",
        ["open_interest", "sum_open_interest_value", "timestamp"],
    ),
    "long_short_ratio": (
        "upsert_long_short_ratio",
        ["long_account", "short_account", "long_short_ratio", "timestamp"],
    ),
    "taker_volume": (
        "upsert_taker_volume",
        ["buy_vol", "sell_vol", "buy_sell_volume_diff", "buy_sell_volume_ratio", "timestamp"],
    ),
    "liquidation": (
        "upsert_liquidation",
        ["order_quantity", "side", "price", "total_quantity", "timestamp"],
    ),
}

# 需要 asset/symbol 列的 sub_category
_NEEDS_SYMBOL = {"funding", "open_interest", "long_short_ratio", "taker_volume", "liquidation"}


class DalSink:
    """SilverRecord → DAL 写入桥。

    Args:
        mm_repo: MarketMacroRepository 实例。None 时尝试从 dreambuddy_dal 获取。
    """

    def __init__(self, mm_repo: Optional[Any] = None) -> None:
        if mm_repo is None:
            try:
                from dreambuddy_dal import get_market_macro_repo
                mm_repo = get_market_macro_repo()
            except Exception:
                logger.warning("[DalSink] 无法从 dreambuddy_dal 获取默认 repo，DAL 写入将不可用")
                mm_repo = None
        self.mm_repo = mm_repo

    def write_silver(
        self,
        silver: SilverRecord,
        *,
        source: str,
        category: str,
        sub_category: str,
    ) -> int:
        """将 SilverRecord.df 按行写入 DAL。

        Returns:
            成功写入的行数。
        """
        if not silver.gate_passed:
            return 0
        if silver.df is None or silver.df.empty:
            return 0
        if self.mm_repo is None:
            return 0

        route_key = sub_category.lower()
        if route_key not in _ROUTE_MAP:
            logger.warning("[DalSink] 未知 sub_category=%r，跳过 DAL 写入", sub_category)
            return 0

        method_name, required_cols = _ROUTE_MAP[route_key]
        method = getattr(self.mm_repo, method_name, None)
        if method is None:
            logger.warning("[DalSink] repo 缺少方法 %s，跳过", method_name)
            return 0

        df = silver.df
        written = 0
        for _, row in df.iterrows():
            try:
                kwargs = self._build_kwargs(route_key, row, source, category, sub_category)
                if kwargs is not None:
                    method(**kwargs)
                    written += 1
            except Exception as exc:
                logger.warning(
                    "[DalSink] %s 写入失败（行跳过）: %s",
                    method_name, exc,
                )

        return written

    def _build_kwargs(
        self,
        route_key: str,
        row: pd.Series,
        source: str,
        category: str,
        sub_category: str,
    ) -> Optional[dict[str, Any]]:
        """从 DataFrame 行构建 upsert 方法参数。"""
        _, required_cols = _ROUTE_MAP[route_key]

        # 检查必需列
        for col in required_cols:
            if col not in row.index:
                return None

        # 解析 timestamp
        ts = _parse_ts(row["timestamp"])

        if route_key == "fear_greed":
            return dict(
                value=int(row["value"]),
                value_classification=str(row["value_classification"]),
                ts=ts,
            )

        # 以下需要 symbol
        symbol = str(row.get("asset", row.get("symbol", "")))

        if route_key == "funding":
            return dict(
                symbol=symbol,
                funding_rate=Decimal(str(row["funding_rate"])),
                funding_ts=ts,
            )

        if route_key == "open_interest":
            return dict(
                symbol=symbol,
                open_interest=Decimal(str(row["open_interest"])),
                sum_open_interest_value=Decimal(str(row["sum_open_interest_value"])),
                ts=ts,
            )

        if route_key == "long_short_ratio":
            return dict(
                symbol=symbol,
                long_account=Decimal(str(row["long_account"])),
                short_account=Decimal(str(row["short_account"])),
                long_short_ratio=Decimal(str(row["long_short_ratio"])),
                ts=ts,
            )

        if route_key == "taker_volume":
            return dict(
                symbol=symbol,
                buy_vol=Decimal(str(row["buy_vol"])),
                sell_vol=Decimal(str(row["sell_vol"])),
                buy_sell_volume_diff=Decimal(str(row["buy_sell_volume_diff"])),
                buy_sell_volume_ratio=Decimal(str(row["buy_sell_volume_ratio"])),
                ts=ts,
            )

        if route_key == "liquidation":
            return dict(
                symbol=symbol,
                order_quantity=Decimal(str(row["order_quantity"])),
                side=str(row["side"]),
                price=Decimal(str(row["price"])),
                total_quantity=Decimal(str(row["total_quantity"])),
                ts=ts,
            )

        return None


def _parse_ts(v) -> datetime:
    """将各种时间类型解析为 datetime。"""
    if isinstance(v, datetime):
        return v
    if isinstance(v, pd.Timestamp):
        return v.to_pydatetime()
    if isinstance(v, str):
        return datetime.fromisoformat(v.replace("Z", "+00:00"))
    return datetime.utcnow()
