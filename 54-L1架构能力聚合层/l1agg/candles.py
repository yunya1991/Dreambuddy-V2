# -*- coding: utf-8 -*-
"""D-B00：K 线获取与适配（L0 `market.candles` → L1 方法层输入）。

口径（TECHNICAL_DESIGN §2.2 / METHOD_LIBRARY §6）：
  - 数据源唯一：L0 scope `market.candles`（1D/1W/1M 日频派生），本模块**不新采集**；
  - 有 high/low 时才置 `has_ohlc=True`；库内无 OHLC 时保持 `False`，
    依赖高低点的 I 组方法由编排层显式返回 `insufficient_history`（禁止 close 伪造）；
  - 时效：`now - 末根 > MAX_STALE_DAYS` → `is_stale=True`，但如实回显；
  - 纯解析/校验，默认取数走惰性导入的 34 `L0Foundation`，可注入 fetcher 做测试。
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

TIMEZONE = "UTC"
ALIGN_METHOD = "utc_daily"
MAX_STALE_DAYS = 3
DEFAULT_BAR = "1d"
DEFAULT_SYMBOL = "BTC"
DAY = 86400

_L0_ROOT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "..",
    "34-前端应用训练系统",
    "core",
)


class CandleError(ValueError):
    """K 线契约/数据源错误（结构非法、来源不可用）。"""


@dataclass
class CandleSet:
    """等长 K 线序列（各字段按时间升序，索引一一对应）。"""

    symbol: str
    bar: str
    ts: Tuple[int, ...] = ()
    close: Tuple[float, ...] = ()
    high: Tuple[float, ...] = ()
    low: Tuple[float, ...] = ()
    volume: Tuple[float, ...] = ()
    source: str = "l0.market.candles"
    has_ohlc: bool = False
    stale_days: int = 0
    is_stale: bool = False
    meta: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        n = len(self.close)
        for name in ("ts", "high", "low", "volume"):
            values = getattr(self, name)
            if values and len(values) != n:
                raise CandleError(f"{name} length {len(values)} != close length {n}")

    @property
    def sample_n(self) -> int:
        return len(self.close)

    @property
    def span(self) -> Optional[str]:
        if not self.ts:
            return None
        return f"{_iso(self.ts[0])[:10]}~{_iso(self.ts[-1])[:10]}"

    def to_method_data(self) -> Dict[str, List[float]]:
        """方法层输入：`{"close": [...], "high": [...], ...}`（缺失腿不出现）。"""
        data: Dict[str, List[float]] = {"close": list(self.close)}
        if self.has_ohlc:
            data["high"] = list(self.high)
            data["low"] = list(self.low)
        if self.volume:
            data["volume"] = list(self.volume)
        return data

    @property
    def close_anchor(self) -> str:
        """1d 收盘锚点（`bar_close` 真实日线 / `snapshot_last` 日频快照）。

        跨资产相关性/领先滞后等横截面方法必须要求两边锚点一致，否则同期相关会被系统性低估。
        """
        return str(self.meta.get("close_anchor") or "")


def _iso(ts: int) -> str:
    from datetime import datetime, timezone

    return datetime.fromtimestamp(int(ts), timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _payload(envelope: Mapping[str, Any]) -> Mapping[str, Any]:
    """兼容完整 L0 信封（ok/data/meta）与裸 data。"""
    if not isinstance(envelope, Mapping):
        raise CandleError("envelope must be a mapping")
    if "data" in envelope:
        data = envelope["data"]
        if not isinstance(data, Mapping):
            raise CandleError("envelope.data must be a mapping")
        return data
    return envelope


def from_l0_envelope(
    envelope: Mapping[str, Any],
    *,
    symbol: Optional[str] = None,
    bar: Optional[str] = None,
    now_ts: Optional[int] = None,
) -> CandleSet:
    """解析 L0 `market.candles` 输出为 `CandleSet`。

    结构非法（无 points / point 缺 close）抛 `CandleError`；
    `points=[]` 属合法空集，返回 `sample_n=0`。
    """
    data = _payload(envelope)
    points = data.get("points")
    if points is None or not isinstance(points, Sequence):
        raise CandleError("missing points[] in market.candles payload")

    ts: List[int] = []
    closes: List[float] = []
    highs: List[float] = []
    lows: List[float] = []
    volumes: List[float] = []
    ohlc_complete = bool(points)
    volume_complete = bool(points)
    for p in points:
        if not isinstance(p, Mapping) or p.get("close") is None or p.get("ts") is None:
            raise CandleError("each point requires ts and close")
        ts.append(int(p["ts"]))
        closes.append(float(p["close"]))
        if p.get("high") is None or p.get("low") is None:
            ohlc_complete = False
        else:
            highs.append(float(p["high"]))
            lows.append(float(p["low"]))
        if p.get("volume") is None:
            volume_complete = False
        else:
            volumes.append(float(p["volume"]))

    if now_ts is None:
        import time

        now_ts = int(time.time())
    stale_days = max(0, (int(now_ts) - ts[-1]) // DAY) if ts else 0
    meta = envelope.get("meta") if isinstance(envelope.get("meta"), Mapping) else {}

    return CandleSet(
        symbol=str(symbol or data.get("symbol") or DEFAULT_SYMBOL).upper(),
        bar=str(bar or data.get("bar") or DEFAULT_BAR).lower(),
        ts=tuple(ts),
        close=tuple(closes),
        high=tuple(highs) if ohlc_complete else (),
        low=tuple(lows) if ohlc_complete else (),
        volume=tuple(volumes) if volume_complete else (),
        source=str(meta.get("source") or "l0.market.candles"),
        has_ohlc=ohlc_complete,
        stale_days=stale_days,
        is_stale=stale_days > MAX_STALE_DAYS,
        meta=dict(meta),
    )


def _default_fetcher(params: Mapping[str, Any]) -> Mapping[str, Any]:
    """惰性接入 34 `L0Foundation.fetch_context("market.candles")`（唯一数据源）。"""
    if _L0_ROOT not in sys.path:
        sys.path.insert(0, _L0_ROOT)
    try:
        from l0_foundation import L0Foundation  # noqa: WPS433
    except Exception as e:  # noqa: BLE001
        raise CandleError(f"L0Foundation unavailable: {type(e).__name__}: {e}") from e
    env = L0Foundation().fetch_context("market.candles", dict(params))
    if isinstance(env, Mapping) and env.get("ok") is False:
        raise CandleError(f"market.candles degraded: {env.get('reason') or env.get('error')}")
    return env


def load(
    symbol: str = DEFAULT_SYMBOL,
    *,
    bar: str = DEFAULT_BAR,
    days: int = 365,
    source_policy: str = "auto",
    fetcher: Optional[Callable[[Mapping[str, Any]], Mapping[str, Any]]] = None,
    now_ts: Optional[int] = None,
) -> CandleSet:
    """取 K 线：默认经 L0 scope，`fetcher` 可注入（测试/离线）。

    `source_policy` 透传 L0：`auto`（默认，真实日线优先）/ `snapshot`（强制日频快照）/
    `bars`（只允许真实日线）。跨资产配对比较应统一传 `snapshot`，确保同一收盘锚点。
    """
    params = {"symbol": symbol, "bar": bar, "days": int(days), "source_policy": source_policy}
    envelope = (fetcher or _default_fetcher)(params)
    return from_l0_envelope(envelope, symbol=symbol, bar=bar, now_ts=now_ts)
