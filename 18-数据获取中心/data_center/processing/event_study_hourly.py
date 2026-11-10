"""事件研究（小时级）：快讯 → 价格敏感度 sens_f — P3-c1h。

为什么有日线版还要小时级：P3-c1 用 UTC 日聚合，post_24h 是一个日收益，
事件发布在 D 日 00:00 还是 23:00 完全不可分辨；若真实反应在数小时内衰减，
日线口径必然把效应摊平为零。本模块把事件对到**发布小时**，用 1h K 线测短窗反应。

方法（预注册，与日线版差异只在对齐粒度 + 标准误）：
  1. 事件强度：count per UTC hour（floor(published_ms/3600e3)）
  2. 强度做扩张窗 z（只用 t 之前信息；warmup 720 小时 = 30 天）
  3. 对每个窗口 y_W 做含全部族强度的 OLS：
         r_t = α + Σ_f β_f·z_f(t) + Σ_d γ_d·hour_of_day_d + ε_t
     控制 hour-of-day 是因为快讯发布时段不均匀，而 BTC 有日内季节性。
  4. **Newey-West (Bartlett) HAC 标准误**，lag = 窗口跨度：
     24h 窗口的重叠观测天然是 MA(24)，不校正会把 t 值抬高数倍（日线版 P1 遗留问题）。
  5. 判据：pre/post 同号且都过 5bp（classify_sensitivity）+ n_event_hours ≥100
     + Holm p<0.10 → eligible

窗口（小时偏移，r_t 表示 (t-1h, t] 的收益）：
  pre_1h   = r[h]                post_1h  = r[h+1]
  pre_24h  = r[h-23..h]          post_24h = r[h+1..h+24]
  post_4h  = r[h+1..h+4]

口径限制（如实记录）：
  - 单一价格源（binance BTC/USDT）→ validation_type = same_source_review
  - 映射仍为维度级，同维度因子共享事件 → 只出族/维级 sens
  - 快讯无精确交易所落地时刻，用报道时间近似

FAIL-OPEN：任何异常返回空行 + degraded 诊断，不抛。
"""

from __future__ import annotations

import csv
import json
import logging
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from data_center.processing.factor_sensitivity import classify_sensitivity
from data_center.processing.newsflash_events import (
    EVENT_TYPE_FACTOR_DIMS,
    MAPPING_VERSION,
    map_event_to_dims,
)

logger = logging.getLogger("data_center.processing.event_study_hourly")

_REPO = Path(__file__).resolve().parents[3]
DEFAULT_1H_CSV = _REPO / "18-数据获取中心" / "backfill" / "p3c1" / "btc_1h.csv"
DEFAULT_NEWSFLASH = _REPO / "18-数据获取中心" / "backfill" / "newsflash_history.jsonl"

HOUR_MS = 3_600_000
# 窗口 → (起始小时偏移, 结束小时偏移)，偏移相对事件小时 h，闭区间
WINDOW_HOURS = {
    "pre_1h": (0, 0),
    "post_1h": (1, 1),
    "pre_24h": (-23, 0),
    "post_24h": (1, 24),
    "post_4h": (1, 4),
}
# 用作 sens 主判据的两个窗口
PRIMARY_PRE = "pre_24h"
PRIMARY_POST = "post_24h"

MIN_EVENT_HOURS = 100
MIN_HOURS = 720
WARMUP_HOURS = 720
HOLM_ALPHA = 0.10
SENSITIVITY_THRESHOLD = 0.0005


# ── 价格 ───────────────────────────────────────────────────


def load_hourly_closes(csv_path: Any = None) -> dict[int, float]:
    """ts_ms → close。读 P3-c1h 的 1h K 线 CSV，非法行跳过。"""
    path = Path(csv_path or DEFAULT_1H_CSV)
    out: dict[int, float] = {}
    try:
        with path.open(encoding="utf-8") as f:
            for row in csv.DictReader(f):
                try:
                    ts = int(row["ts_ms"])
                    c = float(row["close"])
                except (KeyError, TypeError, ValueError):
                    continue
                if ts > 0 and math.isfinite(c) and c > 0:
                    out[ts] = c
    except FileNotFoundError:
        logger.warning("[FAIL-OPEN] 1h csv missing: %s", path)
        return {}
    return out


def hourly_returns(closes: dict[int, float]) -> dict[int, float]:
    """ts → 该小时的 close-to-close 收益；前一小时缺失则不产出（不补 0）。"""
    out: dict[int, float] = {}
    for ts, c in closes.items():
        prev = closes.get(ts - HOUR_MS)
        if prev and prev > 0:
            out[ts] = c / prev - 1.0
    return out


def window_hours(hour: int, window: str) -> list[int]:
    """事件小时 → 该窗口覆盖的小时列表（闭区间）。"""
    lo, hi = WINDOW_HOURS[window]
    return [hour + k * HOUR_MS for k in range(lo, hi + 1)]


def window_return(rets: dict[int, float], hour: int, window: str) -> float | None:
    """窗口累计收益；任一构成小时缺失 → None（缺口不补 0）。"""
    if window not in WINDOW_HOURS:
        return None
    total = 0.0
    for h in window_hours(hour, window):
        v = rets.get(h)
        if v is None:
            return None
        total += v
    return total


# ── 事件强度 ───────────────────────────────────────────────


def _hour_of(ms: Any) -> int | None:
    try:
        ts = int(ms)
    except (TypeError, ValueError):
        return None
    if ts <= 0:
        return None
    return (ts // 1000) // 3600 * 3600 * 1000


def build_counts(
    recs: Iterable[Any], mapping: str = "v1"
) -> tuple[dict[str, dict[int, int]], dict[str, dict[int, int]]]:
    """一次遍历产出 (事件族小时计数, 维度小时计数)，同一套映射。"""
    fam: dict[str, dict[int, int]] = {}
    dim: dict[str, dict[int, int]] = {}
    for rec in recs:
        if not isinstance(rec, dict):
            continue
        dims, _ = map_event_to_dims(rec, mapping)
        if not dims:
            continue
        hour = _hour_of(rec.get("published_ms"))
        if hour is None:
            continue
        family = str(rec.get("od_event_type") or "")
        fb = fam.setdefault(family, {})
        fb[hour] = fb.get(hour, 0) + 1
        for d in dims:
            db = dim.setdefault(d, {})
            db[hour] = db.get(hour, 0) + 1
    return fam, dim


def _expanding_z(vals: list[float], warmup: int = WARMUP_HOURS) -> list[float]:
    out: list[float] = []
    s = s2 = 0.0
    n = 0
    for v in vals:
        if n < warmup:
            out.append(0.0)
        else:
            mean = s / n
            var = max(s2 / n - mean * mean, 0.0)
            sd = math.sqrt(var)
            out.append((v - mean) / sd if sd > 1e-12 else 0.0)
        s += v
        s2 += v * v
        n += 1
    return out


# ── OLS + Newey-West ───────────────────────────────────────


def hac_ols(
    x: list[list[float]], y: list[float], lag: int = 1
) -> tuple[list[float], list[float]] | None:
    """OLS + Newey-West(Bartlett) HAC 标准误。"""
    try:
        import numpy as np

        a = np.asarray(x, dtype=float)
        b = np.asarray(y, dtype=float)
        n, k = a.shape
        if n <= k + 1:
            return None
        xtx = a.T @ a
        xtx_inv = np.linalg.pinv(xtx)
        beta = xtx_inv @ (a.T @ b)
        resid = b - a @ beta
        # meat = Σ_l w_l * Σ_t x_t x_{t-l}' e_t e_{t-l}（向量化，避免逐点 outer）
        z = a * resid[:, None]
        meat = z.T @ z
        lag = max(0, min(int(lag), n - 2))
        for i in range(1, lag + 1):
            w = 1.0 - i / (lag + 1.0)
            s = (a[i:] * resid[i:, None]).T @ (a[:-i] * resid[:-i, None])
            meat += w * (s + s.T)
        cov = xtx_inv @ meat @ xtx_inv
        se = np.sqrt(np.maximum(np.diag(cov), 1e-24))
        return [float(v) for v in beta], [float(v) for v in se]
    except Exception as e:  # noqa: BLE003  FAIL-OPEN
        logger.warning("[FAIL-OPEN] hac_ols %s: %s", type(e).__name__, str(e)[:120])
        return None


def p_two_sided(t: float) -> float:
    return math.erfc(abs(t) / math.sqrt(2.0))


def holm(pvals: dict[str, float], alpha: float = HOLM_ALPHA) -> dict[str, float]:
    if not pvals:
        return {}
    items = sorted(pvals.items(), key=lambda kv: kv[1])
    m = len(items)
    adj: dict[str, float] = {}
    running = 0.0
    for i, (k, p) in enumerate(items):
        running = max(running, min(1.0, (m - i) * p))
        adj[k] = running
    return adj


# ── 回归主体 ───────────────────────────────────────────────


def _hour_of_day_dummies(hours: list[int], skip: int = 0) -> list[list[float]]:
    """23 个小时虚拟变量（以 skip 点为基准，避免与截距共线）。"""
    cols = []
    for h in hours:
        hod = datetime.fromtimestamp(h / 1000, timezone.utc).hour
        cols.append([1.0 if hod == k else 0.0 for k in range(24) if k != skip])
    return cols


def regress_window(
    hours: list[int],
    rets: dict[int, float],
    groups: dict[str, dict[int, int]],
    window: str,
    *,
    control_hour_of_day: bool = True,
) -> dict[str, dict]:
    """单窗口回归 → {group: {beta, se, t, p, n_hours, n_events}}。"""
    usable = [(h, window_return(rets, h, window)) for h in hours]
    usable = [(h, v) for h, v in usable if v is not None]
    if len(usable) < MIN_HOURS:
        return {}
    cols: dict[str, list[float]] = {}
    for k, bucket in groups.items():
        seq = _expanding_z([float(bucket.get(h, 0)) for h, _ in usable])
        if any(abs(v) > 1e-12 for v in seq):
            cols[k] = seq
    if not cols:
        return {}
    keys = list(cols)
    hod = _hour_of_day_dummies([h for h, _ in usable]) if control_hour_of_day else None
    x = []
    for i in range(len(usable)):
        row = [1.0] + [cols[k][i] for k in keys]
        if hod is not None:
            row += hod[i]
        x.append(row)
    y = [v for _, v in usable]
    lo, hi = WINDOW_HOURS[window]
    lag = max(1, hi - lo + 1)
    fit = hac_ols(x, y, lag=lag)
    if fit is None:
        return {}
    beta, se = fit
    out: dict[str, dict] = {}
    for i, k in enumerate(keys):
        b, s = beta[i + 1], se[i + 1]
        t = b / s if s > 0 else 0.0
        out[k] = {
            "beta": round(b, 8),
            "se": round(s, 8),
            "t": round(t, 3),
            "p": round(p_two_sided(t), 6),
            "n_hours": len(usable),
            "n_event_hours": sum(1 for v in groups[k].values() if v > 0),
        }
    return out


def run_event_study_hourly(
    *,
    newsflash_path: Any = None,
    kline_csv: Any = None,
    mapping: str = "v1",
    min_event_hours: int = MIN_EVENT_HOURS,
    returns: dict[int, float] | None = None,
    records: Iterable[Any] | None = None,
    control_hour_of_day: bool = True,
) -> dict:
    """小时级事件研究 → {rows, diagnostics}。"""
    diag: dict[str, Any] = {
        "granularity": "1h",
        "mapping": mapping,
        "mapping_version": MAPPING_VERSION,
        "degraded": False,
        "n_records": 0,
        "n_hours": 0,
        "n_event_hours_by_family": {},
        "n_dropped_insufficient": [],
        "hac_lag_by_window": {w: abs(b - a) + 1 for w, (a, b) in WINDOW_HOURS.items()},
    }
    try:
        rets = returns if returns is not None else hourly_returns(load_hourly_closes(kline_csv))
        if not rets:
            diag.update(degraded=True, reason="no_returns")
            return {"rows": [], "diagnostics": diag}

        if records is None:
            path = Path(newsflash_path or DEFAULT_NEWSFLASH)
            seen = {"n": 0}

            def _counted(it: Iterable[Any]):
                for r in it:
                    seen["n"] += 1
                    yield r

            events, dims = build_counts(_counted(_iter_jsonl(path)), mapping)
            diag["n_records"] = seen["n"]
        else:
            records = list(records)
            diag["n_records"] = len(records)
            events, dims = build_counts(records, mapping)

        hours = sorted(rets)
        diag["n_hours"] = len(hours)
        events = {
            k: v
            for k, v in events.items()
            if sum(1 for c in v.values() if c > 0) >= min_event_hours
        }
        diag["n_dropped_insufficient"] = sorted(set(EVENT_TYPE_FACTOR_DIMS) - set(events))
        diag["n_event_hours_by_family"] = {
            k: sum(1 for c in v.values() if c > 0) for k, v in sorted(events.items())
        }
        if not events:
            diag.update(degraded=True, reason="no_family_with_enough_events")
            return {"rows": [], "diagnostics": diag}

        fam_w = {
            w: regress_window(hours, rets, events, w, control_hour_of_day=control_hour_of_day)
            for w in WINDOW_HOURS
        }
        fam_holm = holm(
            {k: v["p"] for k, v in fam_w[PRIMARY_POST].items()} if fam_w[PRIMARY_POST] else {}
        )

        rows: list[dict] = []
        for fam in events:
            pre = fam_w[PRIMARY_PRE].get(fam)
            post = fam_w[PRIMARY_POST].get(fam)
            if not pre or not post:
                continue
            verdict = classify_sensitivity(pre["beta"], post["beta"], SENSITIVITY_THRESHOLD)
            hp = fam_holm.get(fam, 1.0)
            rows.append(
                _row(
                    unit="event_family",
                    key=fam,
                    extra={"dims": list(EVENT_TYPE_FACTOR_DIMS.get(fam, ()))},
                    pre=pre,
                    post=post,
                    windows=fam_w,
                    holm_p=hp,
                    verdict=verdict,
                    mapping=mapping,
                    min_event_hours=min_event_hours,
                )
            )

        dims = {
            k: v for k, v in dims.items() if sum(1 for c in v.values() if c > 0) >= min_event_hours
        }
        dim_w = {
            w: regress_window(hours, rets, dims, w, control_hour_of_day=control_hour_of_day)
            for w in WINDOW_HOURS
        }
        dim_holm = holm(
            {k: v["p"] for k, v in dim_w[PRIMARY_POST].items()} if dim_w[PRIMARY_POST] else {}
        )
        from data_center.processing.newsflash_events import _factors_by_dim

        fbd = _factors_by_dim()
        for dim in dims:
            pre = dim_w[PRIMARY_PRE].get(dim)
            post = dim_w[PRIMARY_POST].get(dim)
            if not pre or not post:
                continue
            verdict = classify_sensitivity(pre["beta"], post["beta"], SENSITIVITY_THRESHOLD)
            hp = dim_holm.get(dim, 1.0)
            rows.append(
                _row(
                    unit="dim",
                    key=dim,
                    extra={"dims": [dim], "factor_ids": list(fbd.get(dim, ()))},
                    pre=pre,
                    post=post,
                    windows=dim_w,
                    holm_p=hp,
                    verdict=verdict,
                    mapping=mapping,
                    min_event_hours=min_event_hours,
                )
            )

        rows.sort(key=lambda r: (r["unit"], -abs(r["sens_f"])))
        return {"rows": rows, "diagnostics": diag}
    except Exception as e:  # noqa: BLE003  FAIL-OPEN
        logger.warning("[FAIL-OPEN] run_event_study_hourly %s: %s", type(e).__name__, str(e)[:120])
        diag.update(degraded=True, reason=f"error:{type(e).__name__}")
        return {"rows": [], "diagnostics": diag}


def _row(
    *,
    unit: str,
    key: str,
    extra: dict,
    pre: dict,
    post: dict,
    windows: dict,
    holm_p: float,
    verdict: dict,
    mapping: str,
    min_event_hours: int,
) -> dict:
    short = windows.get("post_1h", {}).get(key)
    mid = windows.get("post_4h", {}).get(key)
    return {
        "unit": unit,
        "key": key,
        **extra,
        "n_events": post["n_event_hours"],
        "n_hours": post["n_hours"],
        "mean_excess_pre": pre["beta"],
        "mean_excess_post": post["beta"],
        "mean_excess_post_1h": short["beta"] if short else None,
        "mean_excess_post_4h": mid["beta"] if mid else None,
        "sens_f": post["beta"],
        "t_pre": pre["t"],
        "t_post": post["t"],
        "p_value": post["p"],
        "p_post_1h": short["p"] if short else None,
        "p_post_4h": mid["p"] if mid else None,
        "p_holm": round(holm_p, 6),
        "verdict": verdict["verdict"],
        "eligible": bool(
            verdict["eligible"] and post["n_event_hours"] >= min_event_hours and holm_p < HOLM_ALPHA
        ),
        "direction": verdict["direction"],
        "granularity": "1h",
        "mapping": mapping,
        "mapping_version": MAPPING_VERSION,
    }


def _iter_jsonl(path: Path):
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue
