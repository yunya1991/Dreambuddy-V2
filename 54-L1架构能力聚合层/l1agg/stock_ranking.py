# -*- coding: utf-8 -*-
"""美股龙头动态排名（SPEC-54-L1 §2.5）。

口径（用户 2026-11-16 确认）：
  - 候选池：已回填 3 年成交额的 7 只美股龙头
  - 分数：`rank_score = z(20日均成交额) + z(20日动量)`
  - 冻结：周度 W-MON（每周一开盘前用上周五收盘数据算一次，周内不变）
  - 版本：`pool_version = sha1(freeze_week|top...)` 用于 params_hash 回放
  - 降级：成交额缺失/样本不足 → `rank_degraded=True` + `rank_source=static`

设计约束：
  - 纯函数 + 可注入 loader，单测完全离线（不依赖真实 DB）
  - 只读 mm_metrics，不写库；调用方（图表/统计层）自行缓存
"""

from __future__ import annotations

import datetime
import hashlib
import math
from typing import Callable, Dict, List, Optional, Sequence, Tuple

# 候选池：与 backfill_cross_asset_leaders.TARGETS 里已回填 volume/amount 的 7 只对齐
CANDIDATES: Tuple[str, ...] = ("NVDA", "AAPL", "MSFT", "TSLA", "AMZN", "GOOGL", "META")
TOP_N = 3
LOOKBACK = 20
# 静态兜底（降级时使用，与 DEFAULT_POOL 的 NVDA 一致）
STATIC_TOP: Tuple[str, ...] = ("NVDA", "AAPL", "MSFT")

Row = Tuple[datetime.date, float]
Loader = Callable[[str, str], List[Row]]


class StockRankingError(RuntimeError):
    """排名计算不可继续（调用方需显式降级）。"""


def freeze_week(as_of: datetime.date) -> datetime.date:
    """返回 as_of 所在周的周一（W-MON 冻结锚点）。"""
    return as_of - datetime.timedelta(days=as_of.weekday())


def zscore(values: Sequence[float]) -> List[float]:
    """截面 z-score；样本 <2 或标准差为 0 时全 0（避免除零放大噪声）。"""
    n = len(values)
    if n == 0:
        return []
    if n == 1:
        return [0.0]
    mean = sum(values) / n
    var = sum((v - mean) ** 2 for v in values) / n
    std = math.sqrt(var)
    if std < 1e-12:
        return [0.0] * n
    return [(v - mean) / std for v in values]


def _tail(rows: List[Row], n: int) -> List[Row]:
    return rows[-n:] if n > 0 else []


def _momentum(closes: List[Row], lookback: int) -> Optional[float]:
    """20 日动量 = close[-1] / close[-1-lookback] - 1；样本不足返回 None。"""
    if len(closes) < lookback + 1:
        return None
    last = closes[-1][1]
    base = closes[-(lookback + 1)][1]
    if base <= 0:
        return None
    return last / base - 1.0


def _avg(values: Sequence[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def compute(
    loader: Loader,
    *,
    as_of: Optional[datetime.date] = None,
    candidates: Sequence[str] = CANDIDATES,
    top_n: int = TOP_N,
    lookback: int = LOOKBACK,
) -> Dict:
    """计算某一周的龙头 Top N。

    Args:
        loader: `(symbol, metric_name) -> [(date, value), ...]` 升序；
                metric_name ∈ {"close_usd", "amount_usd"}
    """
    as_of = as_of or datetime.date.today()
    week = freeze_week(as_of)
    # 周一重排 → 数据窗口截止到上周日（即上周五收盘）
    cutoff = week - datetime.timedelta(days=1)

    details: List[Dict] = []
    degraded_reasons: List[str] = []
    for symbol in candidates:
        closes = [r for r in loader(symbol, "close_usd") if r[0] <= cutoff]
        amounts = [r for r in loader(symbol, "amount_usd") if r[0] <= cutoff]
        mom = _momentum(closes, lookback)
        amount_window = [v for _, v in _tail(amounts, lookback) if v > 0]
        avg_amount = _avg(amount_window)
        available = mom is not None and len(amount_window) >= lookback
        if mom is None:
            degraded_reasons.append(f"{symbol}:close_lt_{lookback + 1}")
        elif len(amount_window) < lookback:
            degraded_reasons.append(f"{symbol}:amount_lt_{lookback}")
        details.append(
            {
                "symbol": symbol,
                "available": available,
                "close": closes[-1][1] if closes else None,
                "momentum_20d": round(mom, 6) if mom is not None else None,
                "avg_amount_usd": round(avg_amount, 2) if available else None,
                "score": None,
            }
        )

    usable = [d for d in details if d["available"]]
    rank_degraded = len(usable) < top_n
    rank_source = "dynamic"
    if rank_degraded:
        rank_source = "static"
        top_symbols = list(STATIC_TOP[:top_n])
    else:
        z_amount = zscore([d["avg_amount_usd"] for d in usable])
        z_mom = zscore([d["momentum_20d"] for d in usable])
        for d, za, zm in zip(usable, z_amount, z_mom, strict=True):
            d["score"] = round(za + zm, 6)
        usable.sort(key=lambda d: (-d["score"], d["symbol"]))
        top_symbols = [d["symbol"] for d in usable[:top_n]]

    if not degraded_reasons:
        degraded_reason = ""
    elif rank_degraded:
        degraded_reason = "insufficient_candidates: " + ";".join(degraded_reasons)
    else:
        degraded_reason = "partial_candidates: " + ";".join(degraded_reasons)

    ordered = [d for s in top_symbols for d in details if d["symbol"] == s]
    top = [dict(d, rank=i + 1) for i, d in enumerate(ordered)]
    for item in top:
        if item["score"] is None:
            item["score"] = 0.0

    version = hashlib.sha1(f"{week.isoformat()}|{'|'.join(top_symbols)}".encode()).hexdigest()[:12]
    return {
        "as_of": as_of.isoformat(),
        "freeze_week": week.isoformat(),
        "data_cutoff": cutoff.isoformat(),
        "top_n": top_n,
        "lookback": lookback,
        "rank_source": rank_source,
        "rank_degraded": rank_degraded,
        "degraded_reason": degraded_reason,
        "pool_version": version,
        "top": top,
        "candidates": details,
    }


# ============================================================
# 默认 loader（真实 DB）
# ============================================================


def default_loader(db_path: str, days: int = 400) -> Loader:
    """构造基于 mm_metrics 的 loader；`days` 需覆盖 `lookback + 缓冲`。"""
    from l1agg.align import load_daily
    from l1agg.leader_registry import resolve

    cache: Dict[Tuple[str, str], List[Row]] = {}

    def _load(symbol: str, metric_name: str) -> List[Row]:
        key = (symbol, metric_name)
        if key in cache:
            return cache[key]
        binding = resolve(symbol)
        if binding is None:
            cache[key] = []
            return []
        end_ts = int(datetime.datetime.now(tz=datetime.timezone.utc).timestamp()) + 86400
        series = load_daily(
            db_path,
            binding.sub_category,
            metric_name,
            start_ts=end_ts - days * 86400,
            end_ts=end_ts,
        )
        rows = sorted(
            (datetime.date.fromisoformat(str(d)), float(v)) for d, v in (series or {}).items()
        )
        cache[key] = rows
        return rows

    return _load
