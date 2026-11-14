"""S1-b: 时间轴对齐层 —— 所有 D2/D3 方法（相关性/条件收益/IC）的唯一前置。

设计约束（METHOD_LIBRARY §0/§15）：
  - 统一 **UTC 日收盘**口径：同一日多观测取最后一个；
  - 跨源重复按 source 字典序去重（与 L0 `datacenter.series` 一致）；
  - 低频指标按「前向填充」对齐到价格轴，但填充超过阈值即视为缺失（防陈旧值污染）；
  - 任何输出必须携带 `sample_n / span / align_method / timezone / stale_ratio`；
  - 样本不足只给 `gate="insufficient_samples"`，**禁止静默输出相关系数**。

纯 stdlib 实现，同输入同输出（无随机、无 pandas 依赖差异）。
"""

from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from statistics import median
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

TIMEZONE = "UTC"
ALIGN_METHOD = "daily_last+ffill"
# 日频/周频/月频的默认最大陈旧天数（未显式指定时按指标自身中位间隔推断）
_STALE_BY_FREQ = {"daily": 3, "weekly": 10, "monthly": 45}


class AlignError(ValueError):
    """对齐层参数/数据错误。"""


@dataclass
class Aligned:
    """对齐结果：价格轴上的因子值与价格值（等长、同序）。"""

    dates: List[str] = field(default_factory=list)
    factor: List[float] = field(default_factory=list)
    price: List[float] = field(default_factory=list)
    meta: Dict[str, object] = field(default_factory=dict)

    @property
    def n(self) -> int:
        return len(self.dates)

    def gate(self, min_n: int) -> str:
        """样本门禁：ok / insufficient_samples。"""
        return "ok" if self.n >= min_n else "insufficient_samples"


# ============================================================
# 取数（只读）
# ============================================================


def load_daily(
    db_path: str,
    sub_category: str,
    metric_name: str,
    *,
    start_ts: Optional[int] = None,
    end_ts: Optional[int] = None,
) -> Dict[str, float]:
    """从 `mm_metrics` 读日频序列，返回 {YYYY-MM-DD: value}（同日取最后观测）。"""
    if not os.path.isfile(db_path):
        raise AlignError(f"db not found: {db_path}")
    sql = (
        "SELECT source, metric_value, timestamp FROM mm_metrics "
        "WHERE sub_category = ? AND metric_name = ? AND metric_value IS NOT NULL"
    )
    args: List[object] = [sub_category, metric_name]
    if start_ts is not None:
        sql += " AND timestamp >= ?"
        args.append(int(start_ts))
    if end_ts is not None:
        sql += " AND timestamp < ?"
        args.append(int(end_ts))
    sql += " ORDER BY timestamp ASC, source ASC"

    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=5)
    try:
        rows = conn.execute(sql, args).fetchall()
    finally:
        conn.close()

    out: Dict[str, float] = {}
    seen_ts: set = set()
    for _src, value, ts in rows:
        ts = int(ts)
        if ts in seen_ts:  # 跨源重复：保留 source 字典序最小者
            continue
        seen_ts.add(ts)
        day = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")
        out[day] = float(value)  # 同日多观测：ASC 顺序下后写覆盖 → 取最后
    return out


def load_price(db_path: str, symbol: str = "BTC", days: int = 365) -> Dict[str, float]:
    """读 `{symbol}.close_usd` 日频收盘（默认近 365 天）。仅适用于加密/贵金属类直采序列。"""
    end_ts = int(datetime.now(tz=timezone.utc).timestamp()) + 86400
    return load_daily(
        db_path,
        symbol.upper(),
        "close_usd",
        start_ts=end_ts - int(days) * 86400,
        end_ts=end_ts,
    )


def load_leader(db_path: str, symbol: str, days: int = 1200) -> Dict[str, float]:
    """按 40 层龙头注册表读日频序列（跨资产统一入口）。

    Raises:
        AlignError: 未绑定/未采集（`not_collected`）—— 强制上层显式降级，
                    禁止把它当成「空序列」静默跳过。
    """
    from l1agg.leader_registry import resolve, unbound_reason

    binding = resolve(symbol)
    if binding is None:
        reason = unbound_reason(symbol)
        raise AlignError(f"not_collected: {symbol} — {reason or '未在龙头注册表登记'}")
    end_ts = int(datetime.now(tz=timezone.utc).timestamp()) + 86400
    series = load_daily(
        db_path,
        binding.sub_category,
        binding.metric_name,
        start_ts=end_ts - int(days) * 86400,
        end_ts=end_ts,
    )
    if not series:
        raise AlignError(f"not_collected: {symbol} — {binding.series_id} 无历史点")
    return series


# ============================================================
# 对齐
# ============================================================


def _infer_max_stale(dates: Sequence[str]) -> int:
    """按指标自身中位间隔推断最大陈旧天数（日 3 / 周 10 / 月 45）。"""
    if len(dates) < 2:
        return _STALE_BY_FREQ["daily"]
    days = [datetime.strptime(d, "%Y-%m-%d").toordinal() for d in dates]
    gaps = [b - a for a, b in zip(days, days[1:], strict=False) if b > a]
    if not gaps:
        return _STALE_BY_FREQ["daily"]
    mid = median(gaps)
    if mid <= 1.5:
        return _STALE_BY_FREQ["daily"]
    if mid <= 10:  # 周频：允许 2 周
        return max(_STALE_BY_FREQ["daily"], min(int(mid * 2), 14))
    return _STALE_BY_FREQ["monthly"]


def align(
    factor: Mapping[str, float],
    price: Mapping[str, float],
    *,
    max_stale_days: Optional[int] = None,
    min_n: int = 0,
) -> Aligned:
    """把因子对齐到价格日轴。

    Args:
        factor: {YYYY-MM-DD: value}，可为日/周/月频。
        price:  {YYYY-MM-DD: close}，价格轴（须日频）。
        max_stale_days: 前向填充上限；None 时按因子中位间隔自动推断。
        min_n: 门禁阈值，仅用于 meta.gate（n>=60 同期相关，n>=250 条件收益）。

    Returns:
        Aligned（dates/factor/price 等长 + meta）。

    Raises:
        AlignError: 价格轴为空或因子为空。
    """
    if not price:
        raise AlignError("price axis is empty")
    if not factor:
        raise AlignError("factor series is empty")

    factor_days = sorted(factor)
    stale_cap = int(max_stale_days) if max_stale_days is not None else _infer_max_stale(factor_days)
    price_days = sorted(price)

    dates: List[str] = []
    f_vals: List[float] = []
    p_vals: List[float] = []
    last_val: Optional[float] = None
    last_ord: Optional[int] = None
    filled = 0

    for day in price_days:
        ord_day = datetime.strptime(day, "%Y-%m-%d").toordinal()
        if day in factor:
            last_val = float(factor[day])
            last_ord = ord_day
        elif last_val is None or last_ord is None or (ord_day - last_ord) > stale_cap:
            continue
        else:
            filled += 1
        dates.append(day)
        f_vals.append(float(last_val))  # type: ignore[arg-type]
        p_vals.append(float(price[day]))

    n = len(dates)
    calendar_days = (
        datetime.strptime(price_days[-1], "%Y-%m-%d").toordinal()
        - datetime.strptime(price_days[0], "%Y-%m-%d").toordinal()
        + 1
    )
    meta: Dict[str, object] = {
        "sample_n": n,
        "span": f"{dates[0]}~{dates[-1]}" if dates else "",
        "missing_rate": round(1.0 - (n / calendar_days), 4) if calendar_days else 1.0,
        "stale_ratio": round(filled / n, 4) if n else 0.0,
        "align_method": ALIGN_METHOD,
        "timezone": TIMEZONE,
        "max_stale_days": stale_cap,
        "factor_span": f"{factor_days[0]}~{factor_days[-1]}",
        "price_span": f"{price_days[0]}~{price_days[-1]}",
        "gate": "ok" if n >= min_n else "insufficient_samples",
    }
    return Aligned(dates=dates, factor=f_vals, price=p_vals, meta=meta)


# ============================================================
# 收益（供 S2/S3 使用）
# ============================================================


def simple_returns(values: Sequence[float]) -> List[float]:
    """一期简单收益 r_t = P_t/P_{t-1} - 1（首点丢弃）。"""
    out: List[float] = []
    for prev, cur in zip(values, values[1:], strict=False):
        out.append(0.0 if prev == 0 else cur / prev - 1.0)
    return out


def log_returns(values: Sequence[float]) -> List[float]:
    """一期对数收益（首点丢弃）。"""
    import math

    out: List[float] = []
    for prev, cur in zip(values, values[1:], strict=False):
        if prev <= 0 or cur <= 0:
            out.append(0.0)
        else:
            out.append(math.log(cur / prev))
    return out


def forward_returns(values: Sequence[float], horizon: int) -> List[Optional[float]]:
    """未来 h 期收益 fwd[i] = P[i+h]/P[i] - 1（尾部 h 个为 None）。

    与 23 `FactorICSelector` 的旧实现不同：**不做任何额外位移**，
    `fwd[i]` 严格对应 `values[i]` 之后 h 期的收益。
    """
    if horizon < 1:
        raise AlignError(f"horizon must be >= 1, got {horizon}")
    n = len(values)
    out: List[Optional[float]] = []
    for i in range(n):
        j = i + horizon
        if j >= n or values[i] == 0:
            out.append(None)
        else:
            out.append(values[j] / values[i] - 1.0)
    return out


def overlap_free_indices(n: int, horizon: int) -> List[int]:
    """非重叠采样下标（每 h 期取 1 个），避免前瞻收益重叠导致的 t 值虚高。"""
    if horizon < 1:
        raise AlignError(f"horizon must be >= 1, got {horizon}")
    return list(range(0, max(0, n - horizon), horizon))


def paired_xy(aligned: Aligned, horizon: int) -> Tuple[List[float], List[float]]:
    """对齐结果 → (factor_t, fwd_ret_{t→t+h})，已剔除尾部 None。"""
    fwd = forward_returns(aligned.price, horizon)
    xs: List[float] = []
    ys: List[float] = []
    for f, y in zip(aligned.factor, fwd, strict=False):
        if y is None:
            continue
        xs.append(float(f))
        ys.append(float(y))
    return xs, ys
