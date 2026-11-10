"""维度上下文 DimensionContext — SPEC-D1-MULTIDIM-STATE §2.6（P3-a）。

18 域临时 adapter：按 §2.6 冻结契约，把真实序列归一为 8 维上下文。
9 域官方 `engines/dimension_context.py` 上线后按 provider 替换，调用方零改动。

口径（预注册）：
  - direction  ±0.3 阈值（对齐 9 域 least_resistance）
  - strength   abs(tanh(z)) ∈ [0,1]（对齐 50 域 DimensionForce.strength）
  - 归一       滚动 window 个观测的 z / 分位，**不用全历史**
  - 前视       as_of 严格截断，只用 t 及之前
  - availability  long ≥900 / short ≥30 / none

FAIL-OPEN：任何异常返回 availability="none" 的空上下文，不抛。
"""

from __future__ import annotations

import json
import logging
import math
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from data_center.processing.factor_series_map import SERIES_MAP
from data_center.processing.news_polarity import daily_news_series

logger = logging.getLogger("data_center.processing.dimension_context")

_REPO = Path(__file__).resolve().parents[3]
DEFAULT_KLINE_DB = _REPO / "18-数据获取中心" / "data_center.db"
DEFAULT_MM_DB = _REPO / "19-数据访问层" / "data" / "dreambuddy_core.db"
DEFAULT_EVENT_JSONL = _REPO / "18-数据获取中心" / "backfill" / "events_d1.jsonl"

ALL_DIMENSIONS = ("D1", "D2", "D3", "D4", "C6", "C7", "C8", "NEWS")

# 因素大类 → 50 域维度（SPEC §2.6 维度映射表）
DIMENSION_MAP = {
    "technical": "D3",
    "flow": "D2",
    "onchain": "C7",  # 50 无链上专维，暂归 C7（待 50 侧确认）
    "macro": "D1",
    "sentiment": "D4",
    "event": "NEWS",
}

# 因子方向约定：+1 = 数值越高越利多；-1 = 越高越利空
SIGN_BULLISH = {
    "technical.trend": 1,
    "technical.momentum": 1,
    "technical.level": 1,
    "technical.ma_cross": 1,
    "technical.fib": 1,
    "technical.trendline": 1,
    "macro.rate": -1,
    "macro.inflation": -1,
    "macro.employment": -1,
    "macro.liquidity": 1,
    "macro.dollar": -1,
    "macro.treasury": 1,
    "macro.equity": 1,
    "macro.gdp": 1,
    "macro.central_bank": -1,
    "macro.credit": -1,
    "flow.funding": -1,
    "flow.oi": 1,
    "flow.long_short": 1,
    "onchain.active_addr": 1,
    "onchain.hashrate": 1,
    "onchain.tvl": 1,
    "sentiment.cycle": 1,
    "news.polarity": 1,  # 快讯聚合分本身已带方向（SPEC §2.8）
}

WINDOW = 60
DIRECTION_THRESHOLD = 0.30
LONG_DAYS = 900
SHORT_DAYS = 30

_DAY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def to_utc_day(raw: Any) -> str | None:
    """任意日期 / 时间戳 → UTC 日 `YYYY-MM-DD`；非法 → None（SPEC §2.10 D1）。

    - 纯日期串按「数据源交易日」原样采用，不二次换时区
    - 带时区 ISO（`Z` / `+08:00`）先换算到 UTC 再取日
    - epoch 秒 / 毫秒按量级判定（>1e11 视为毫秒）
    - NaN / None / "nan" / "" 一律 None —— 此前 `str(nan)` 会生成键 `'nan'`，
      该键字典序大于任何 `2026-*`，会绕过 `as_of` 截断形成前视泄漏
    """
    try:
        if raw is None:
            return None
        if isinstance(raw, float) and not math.isfinite(raw):
            return None
        if hasattr(raw, "isoformat") and not isinstance(raw, str):
            raw = raw.isoformat()
        if isinstance(raw, (int, float)):
            v = float(raw)
            ts = v / 1000.0 if v > 1e11 else v
            return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")
        s = str(raw).strip()
        if not s or s.lower() in {"nan", "none", "null", "nat"}:
            return None
        if len(s) == 10 and _DAY_RE.match(s):
            return s
        if re.fullmatch(r"\d+(\.\d+)?", s):
            return to_utc_day(float(s))
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).strftime("%Y-%m-%d")
    except (ValueError, TypeError, OverflowError, OSError):
        return None


# SPEC §4.4 P3-b2 裁决：这些维的"方向"无判别力（平衡准确率 ≤ 随机），
# 只保留 strength 供参考，不参与 dominant / agreement 判定。
DIRECTION_DISABLED = frozenset({"NEWS"})


@dataclass(frozen=True)
class DimensionContext:
    dimension: str
    as_of: str
    direction: str  # up / down / neutral
    strength: float  # [0,1]
    z: float  # [-3,3]
    percentile: float  # [0,1]
    data_points: int
    availability: str  # long / short / none
    series_id: str
    factors_used: tuple[str, ...] = ()


# ── 序列加载（带缓存）──────────────────────────────────────

_KLINE_CACHE: dict[str, tuple] = {}
_MM_CACHE: dict[tuple, tuple] = {}


def _load_kline(db: Any) -> tuple:
    key = str(db)
    if key in _KLINE_CACHE:
        return _KLINE_CACHE[key]
    out: dict[str, float] = {}
    try:
        conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        try:
            rows = conn.execute(
                "SELECT timestamp, timeseries FROM records"
                " WHERE source='yfinance' AND sub_category='BTC-USD'"
                " ORDER BY timestamp"
            ).fetchall()
        finally:
            conn.close()
        for ts, arr_raw in rows:
            try:
                arr = json.loads(arr_raw) if isinstance(arr_raw, str) else arr_raw
                el = arr[0]
                d = to_utc_day(el.get("date")) or to_utc_day(el.get("timestamp")) or to_utc_day(ts)
                if not d:
                    continue
                v = el.get("close", el.get("value"))
                if v is None or not math.isfinite(float(v)):
                    continue
                out[d] = float(v)  # 同日后者覆盖
            except (ValueError, TypeError, IndexError, KeyError):
                continue
    except Exception as e:  # noqa: BLE003  FAIL-OPEN
        logger.warning("[FAIL-OPEN] load_kline %s: %s", type(e).__name__, str(e)[:120])
    res = tuple(sorted(out.items()))
    _KLINE_CACHE[key] = res
    return res


def _load_mm(db: Any, source: str | None, sub: str | None, metric: str | None) -> tuple:
    if not source:
        return ()
    key = (str(db), source, sub, metric)
    if key in _MM_CACHE:
        return _MM_CACHE[key]
    per_day: dict[str, float] = {}
    try:
        conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        try:
            sql = (
                "SELECT timestamp, metric_value FROM mm_metrics"
                " WHERE source=? AND sub_category=?"
            )
            args: list[Any] = [source, sub]
            if metric:
                sql += " AND metric_name=?"
                args.append(metric)
            rows = conn.execute(sql + " ORDER BY timestamp", tuple(args)).fetchall()
        finally:
            conn.close()
        for ts, val in rows:
            try:
                if val is None or not math.isfinite(float(val)):
                    continue
                d = datetime.fromtimestamp(int(ts), tz=timezone.utc).date().isoformat()
                per_day[d] = float(val)
            except (ValueError, TypeError, OSError):
                continue
    except Exception as e:  # noqa: BLE003  FAIL-OPEN
        logger.warning("[FAIL-OPEN] load_mm %s/%s: %s", source, sub, type(e).__name__)
    res = tuple(sorted(per_day.items()))
    _MM_CACHE[key] = res
    return res


# ── 技术派生（仅 close，语料无 OHLCV）───────────────────────


def _sma(vals: list[float], n: int) -> list[float | None]:
    out: list[float | None] = [None] * len(vals)
    s = 0.0
    for i, v in enumerate(vals):
        s += v
        if i >= n:
            s -= vals[i - n]
        if i >= n - 1:
            out[i] = s / n
    return out


def _rsi(closes: list[float], n: int = 14) -> list[float | None]:
    out: list[float | None] = [None] * len(closes)
    gains: list[float] = []
    losses: list[float] = []
    for i in range(1, len(closes)):
        ch = closes[i] - closes[i - 1]
        gains.append(max(ch, 0.0))
        losses.append(max(-ch, 0.0))
        if len(gains) >= n:
            g = sum(gains[-n:]) / n
            avg_loss = sum(losses[-n:]) / n
            out[i] = 100.0 if avg_loss == 0 else 100.0 - 100.0 / (1.0 + g / avg_loss)
    return out


def _rolling(closes: list[float], n: int, fn) -> list[float | None]:
    out: list[float | None] = [None] * len(closes)
    for i in range(len(closes)):
        if i >= n - 1:
            out[i] = fn(closes[i - n + 1 : i + 1])
    return out


def _slope20(closes: list[float], n: int = 20) -> list[float | None]:
    out: list[float | None] = [None] * len(closes)
    xs = list(range(n))
    xm = (n - 1) / 2.0
    den = sum((x - xm) ** 2 for x in xs)
    for i in range(n - 1, len(closes)):
        seg = closes[i - n + 1 : i + 1]
        ym = sum(seg) / n
        num = sum((xs[k] - xm) * (seg[k] - ym) for k in range(n))
        out[i] = (num / den) / ym if ym else None
    return out


def _technical_series(kline: tuple) -> dict[str, tuple]:
    """从 close 序列派生技术/周期因子（无法派生的不伪造）。"""
    if len(kline) < 60:
        return {}
    dates = [x[0] for x in kline]
    closes = [x[1] for x in kline]
    ma20 = _sma(closes, 20)
    ma60 = _sma(closes, 60)
    ma200 = _sma(closes, 200)
    rsi14 = _rsi(closes, 14)
    hi20 = _rolling(closes, 20, max)
    lo20 = _rolling(closes, 20, min)
    slope = _slope20(closes, 20)
    rets: list[float] = [0.0] + [
        (closes[i] / closes[i - 1] - 1.0) if closes[i - 1] else 0.0 for i in range(1, len(closes))
    ]
    vol20 = _rolling(
        rets, 20, lambda w: (sum((x - sum(w) / len(w)) ** 2 for x in w) / len(w)) ** 0.5
    )

    out: dict[str, list[tuple[str, float]]] = {}

    def _put(fid: str, i: int, v: float | None) -> None:
        if v is None or not math.isfinite(v):
            return
        out.setdefault(fid, []).append((dates[i], float(v)))

    for i in range(len(closes)):
        if ma20[i] is not None and ma60[i] is not None:
            _put("technical.trend", i, (ma20[i] - ma60[i]) / closes[i])
            _put("technical.ma_cross", i, 1.0 if ma20[i] > ma60[i] else -1.0)
        if rsi14[i] is not None:
            _put("technical.momentum", i, rsi14[i] / 100.0 - 0.5)
        if hi20[i]:
            _put("technical.level", i, closes[i] / hi20[i] - 1.0)
            _put(
                "technical.fib",
                i,
                (closes[i] - lo20[i]) / (hi20[i] - lo20[i]) if hi20[i] > lo20[i] else None,
            )
        if vol20[i] is not None:
            _put("technical.volatility", i, vol20[i])
        if slope[i] is not None:
            _put("technical.trendline", i, slope[i])
        if ma200[i] is not None:
            _put("sentiment.cycle", i, closes[i] / ma200[i] - 1.0)

    return {k: tuple(v) for k, v in out.items() if len(v) >= 2}


def _series_by_dim(
    kline_db: Any, mm_db: Any, newsflash_jsonl: Any = None
) -> dict[str, dict[str, tuple]]:
    """dimension → {factor_id: ((date, value), ...)}。"""
    kline = _load_kline(kline_db)
    tech = _technical_series(kline)

    out: dict[str, dict[str, tuple]] = {d: {} for d in ALL_DIMENSIONS}
    for fid, meta in SERIES_MAP.items():
        dim = DIMENSION_MAP.get(fid.split(".")[0])
        if not dim:
            continue
        if meta["source"] == "kline":
            s = tech.get(fid)
        elif meta["source"] == "mm":
            s = _load_mm(
                mm_db, meta.get("mm_source"), meta.get("mm_sub_category"), meta.get("mm_metric")
            )
        else:
            s = None
        if s:
            out[dim][fid] = s
    news = daily_news_series(path=newsflash_jsonl)
    if news:
        out["NEWS"]["news.polarity"] = news
    return out


# ── 归一与聚合 ─────────────────────────────────────────────


def _z_pct(series: tuple, as_of: str, window: int) -> tuple[float, float, int] | None:
    obs = [v for d, v in series if d <= as_of]
    if len(obs) < 2:
        return None
    win = obs[-window:]
    mean = sum(win) / len(win)
    var = sum((x - mean) ** 2 for x in win) / len(win)
    std = var**0.5
    last = win[-1]
    z = 0.0 if std == 0 else (last - mean) / std
    z = max(-3.0, min(3.0, z))
    prior = win[:-1]
    pct = (sum(1 for x in prior if x <= last) / len(prior)) if prior else 0.5
    return z, pct, len(obs)


def _availability(days: int) -> str:
    if days >= LONG_DAYS:
        return "long"
    if days >= SHORT_DAYS:
        return "short"
    return "none"


def _empty(dimension: str, as_of: str) -> DimensionContext:
    return DimensionContext(
        dimension=dimension,
        as_of=as_of,
        direction="neutral",
        strength=0.0,
        z=0.0,
        percentile=0.5,
        data_points=0,
        availability="none",
        series_id=f"dim:{dimension}",
        factors_used=(),
    )


def _context_for_dim(
    dimension: str, factors: dict[str, tuple], as_of: str, window: int
) -> DimensionContext:
    zs: list[float] = []
    pcts: list[float] = []
    used: list[str] = []
    max_obs = 0
    max_days = 0
    for fid, series in factors.items():
        sign = SIGN_BULLISH.get(fid, 0)
        if sign == 0:
            continue
        r = _z_pct(series, as_of, window)
        if r is None:
            continue
        z, pct, n_obs = r
        zs.append(sign * z)
        pcts.append(pct if sign > 0 else 1.0 - pct)
        used.append(fid)
        max_obs = max(max_obs, n_obs)
        max_days = max(max_days, len(series))

    if not zs:
        return _empty(dimension, as_of)

    z_mean = max(-3.0, min(3.0, sum(zs) / len(zs)))
    direction = (
        "up"
        if z_mean > DIRECTION_THRESHOLD
        else "down" if z_mean < -DIRECTION_THRESHOLD else "neutral"
    )
    availability = _availability(max_days)
    if dimension in DIRECTION_DISABLED:
        # SPEC §4.4 P3-b2 裁决：快讯极性方向无判别力（平衡准确率 0.50），
        # 该维方向不可用、不参与 dominant/agreement 判定；强度仍保留供参考。
        direction = "neutral"
        availability = "none"
    return DimensionContext(
        dimension=dimension,
        as_of=as_of,
        direction=direction,
        strength=abs(math.tanh(z_mean)),
        z=round(z_mean, 4),
        percentile=round(sum(pcts) / len(pcts), 4),
        data_points=max_obs,
        availability=availability,
        series_id=f"dim:{dimension}",
        factors_used=tuple(sorted(used)),
    )


def get_dimension_context(
    dimension: str,
    as_of: str,
    window: int = WINDOW,
    *,
    kline_db: Any = None,
    mm_db: Any = None,
    event_jsonl: Any = None,
    newsflash_jsonl: Any = None,
) -> DimensionContext:
    """单维上下文。FAIL-OPEN。"""
    try:
        if dimension not in ALL_DIMENSIONS:
            return _empty(dimension, as_of)
        by_dim = _series_by_dim(
            kline_db or DEFAULT_KLINE_DB,
            mm_db or DEFAULT_MM_DB,
            newsflash_jsonl,
        )
        return _context_for_dim(dimension, by_dim.get(dimension, {}), as_of, window)
    except Exception as e:  # noqa: BLE003  FAIL-OPEN
        logger.warning("[FAIL-OPEN] get_dimension_context %s: %s", dimension, type(e).__name__)
        return _empty(dimension, as_of)


def get_dimension_matrix(
    as_of: str,
    dimensions: list[str] | tuple[str, ...] | None = None,
    window: int = WINDOW,
    *,
    kline_db: Any = None,
    mm_db: Any = None,
    event_jsonl: Any = None,
    newsflash_jsonl: Any = None,
) -> dict[str, DimensionContext]:
    """8 维上下文矩阵。FAIL-OPEN（异常时各维为空上下文）。"""
    dims = tuple(dimensions) if dimensions else ALL_DIMENSIONS
    try:
        by_dim = _series_by_dim(
            kline_db or DEFAULT_KLINE_DB,
            mm_db or DEFAULT_MM_DB,
            newsflash_jsonl,
        )
        return {d: _context_for_dim(d, by_dim.get(d, {}), as_of, window) for d in dims}
    except Exception as e:  # noqa: BLE003  FAIL-OPEN
        logger.warning("[FAIL-OPEN] get_dimension_matrix %s: %s", as_of, type(e).__name__)
        return {d: _empty(d, as_of) for d in dims}
