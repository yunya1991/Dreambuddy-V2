"""事件研究：快讯 → 价格敏感度 sens_f — SPEC §2.9.2 / §4.4 P3-c1。

方法（预注册）：
  1. 事件族 × UTC 日聚合为**事件强度** count（同日多条累加）
  2. 强度做**扩张窗标准化**（只用 t 之前的信息，避免前视）：
         z_t = (count_t − mean_{<t}) / sd_{<t}
     前 30 个观测记 0（warmup）
  3. 对每个窗口 y_W（pre_24h / post_24h / pre_72h / post_72h）做
     **含全部事件族强度的 OLS**：
         r_t = α + Σ_f β_f·z_f(t) + ε_t
     β_f = 该族强度每增加 1 个历史标准差对应的超额收益，
     已控制其它族同期共振（评审 T1 的残差化）。
  4. 判据：pre_24h 与 post_24h 的 β 同号且都过 5bp（classify_sensitivity），
     事件日 ≥30、样本日 ≥100、Holm 校正 p<0.10 → eligible
  5. 日线口径：pre_24h = r[D-1]，post_24h = r[D]，72h 为 3 日累计

为什么不用二值事件日：实测 193,300 条快讯覆盖 1,410 天，日均 137 条，
9 个族里 8 个族在 >90% 的交易日都出现（market_sentiment 1410/1410）。
二值指示变量与截距近似共线，回归不可识别 → 必须用连续强度。

口径限制（如实记录）：
  - 只有日线 → 无法做分钟级实时对齐，D 日内的先后次序不可分辨
  - 映射是**维度级**，同维度因子共享事件 → 只能出事件族/维度级 sens，
    不能出 60 细类级 sens（需要更细的因子映射）
  - 单一价格源 → validation_type = same_source_review

FAIL-OPEN：任何异常返回空行 + degraded 诊断，不抛。
"""

from __future__ import annotations

import json
import logging
import math
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

from data_center.processing.dimension_context import DEFAULT_KLINE_DB, _load_kline
from data_center.processing.factor_sensitivity import classify_sensitivity
from data_center.processing.newsflash_events import (
    EVENT_TYPE_FACTOR_DIMS,
    MAPPING_VERSION,
    map_event_to_dims,
)

logger = logging.getLogger("data_center.processing.event_study")

_REPO = Path(__file__).resolve().parents[3]
DEFAULT_NEWSFLASH = _REPO / "18-数据获取中心" / "backfill" / "newsflash_history.jsonl"

WINDOW_OFFSETS = {
    "pre_24h": (-1,),
    "post_24h": (0,),
    "pre_72h": (-3, -2, -1),
    "post_72h": (0, 1, 2),
}
MIN_EVENT_DAYS = 30
MIN_DAYS = 100
WARMUP = 30
HOLM_ALPHA = 0.10


# ── 基础工具 ───────────────────────────────────────────────


def load_daily_returns(kline_db: Any = None) -> dict[str, float]:
    """UTC 日 → 简单收益率（close_t / close_{t-1} - 1）。"""
    kline = _load_kline(kline_db or DEFAULT_KLINE_DB)
    if len(kline) < 2:
        return {}
    out: dict[str, float] = {}
    for i in range(1, len(kline)):
        d, c = kline[i]
        prev = kline[i - 1][1]
        if prev:
            out[d] = c / prev - 1.0
    return out


def _shift(day: str, n: int) -> str:
    return (date.fromisoformat(day) + timedelta(days=n)).isoformat()


def window_return(rets: dict[str, float], day: str, window: str) -> float | None:
    """事件日 day 的窗口累计收益；任一构成日缺失 → None（缺口不补 0）。"""
    offsets = WINDOW_OFFSETS.get(window)
    if offsets is None:
        return None
    total = 0.0
    for off in offsets:
        v = rets.get(_shift(day, off))
        if v is None:
            return None
        total += v
    return total


def build_counts(
    recs: Iterable[Any], mapping: str = "v1"
) -> tuple[dict[str, dict[str, int]], dict[str, dict[str, int]]]:
    """一次遍历同时产出 (事件族计数, 维度计数)，两者必须用同一套映射。"""
    fam: dict[str, dict[str, int]] = {}
    dim: dict[str, dict[str, int]] = {}
    for rec in recs:
        if not isinstance(rec, dict):
            continue
        dims, _ = map_event_to_dims(rec, mapping)
        if not dims:
            continue
        try:
            ts = int(rec.get("published_ms") or 0) // 1000
        except (TypeError, ValueError):
            continue
        if ts <= 0:
            continue
        day = datetime.fromtimestamp(ts, timezone.utc).date().isoformat()
        family = str(rec.get("od_event_type") or "")
        fb = fam.setdefault(family, {})
        fb[day] = fb.get(day, 0) + 1
        for d in dims:
            db = dim.setdefault(d, {})
            db[day] = db.get(day, 0) + 1
    return fam, dim


def build_family_counts(recs: Iterable[Any], mapping: str = "v1") -> dict[str, dict[str, int]]:
    """事件族 → {UTC 日: 条数}。只保留能映射到维度的族。"""
    return build_counts(recs, mapping)[0]


def _expanding_z(vals: list[float]) -> list[float]:
    """扩张窗 z（只用过去信息）；前 WARMUP 个记 0。"""
    out: list[float] = []
    s = 0.0
    s2 = 0.0
    n = 0
    for v in vals:
        if n < WARMUP:
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


def _ols(x: list[list[float]], y: list[float]) -> tuple[list[float], list[float]] | None:
    try:
        import numpy as np

        a = np.asarray(x, dtype=float)
        b = np.asarray(y, dtype=float)
        beta, *_ = np.linalg.lstsq(a, b, rcond=None)
        resid = b - a @ beta
        dof = max(1, len(b) - a.shape[1])
        sigma2 = float(resid @ resid) / dof
        xtx_inv = np.linalg.pinv(a.T @ a)
        se = np.sqrt(np.maximum(np.diag(xtx_inv) * sigma2, 1e-24))
        return [float(v) for v in beta], [float(v) for v in se]
    except Exception as e:  # noqa: BLE003  FAIL-OPEN
        logger.warning("[FAIL-OPEN] _ols %s: %s", type(e).__name__, str(e)[:120])
        return None


def p_two_sided(t: float) -> float:
    return math.erfc(abs(t) / math.sqrt(2.0))


def holm(pvals: dict[str, float], alpha: float = HOLM_ALPHA) -> dict[str, float]:
    """Holm 校正 → key → adjusted p（单调化）。"""
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


def spearman(a: dict[str, float], b: dict[str, float]) -> float | None:
    common = [k for k in a if k in b and math.isfinite(a[k]) and math.isfinite(b[k])]
    if len(common) < 3:
        return None

    def _rank(vals: list[float]) -> list[float]:
        order = sorted(range(len(vals)), key=lambda i: vals[i])
        r = [0.0] * len(vals)
        i = 0
        while i < len(order):
            j = i
            while j + 1 < len(order) and vals[order[j + 1]] == vals[order[i]]:
                j += 1
            avg = (i + j) / 2.0 + 1.0
            for k in range(i, j + 1):
                r[order[k]] = avg
            i = j + 1
        return r

    ra = _rank([a[k] for k in common])
    rb = _rank([b[k] for k in common])
    ma, mb = sum(ra) / len(ra), sum(rb) / len(rb)
    num = sum((x - ma) * (y - mb) for x, y in zip(ra, rb, strict=False))
    da = math.sqrt(sum((x - ma) ** 2 for x in ra))
    db = math.sqrt(sum((y - mb) ** 2 for y in rb))
    if da == 0 or db == 0:
        return None
    return round(num / (da * db), 4)


# ── 回归主体 ───────────────────────────────────────────────


def _regress_window(
    days: list[str],
    rets: dict[str, float],
    groups: dict[str, dict[str, int]],
    window: str,
) -> dict[str, dict]:
    usable = [(d, window_return(rets, d, window)) for d in days]
    usable = [(d, v) for d, v in usable if v is not None]
    if len(usable) < MIN_DAYS:
        return {}
    cols: dict[str, list[float]] = {}
    for k, bucket in groups.items():
        seq = _expanding_z([float(bucket.get(d, 0)) for d, _ in usable])
        if any(abs(v) > 1e-12 for v in seq):
            cols[k] = seq
    if not cols:
        return {}
    keys = list(cols)
    x = [[1.0] + [cols[k][i] for k in keys] for i in range(len(usable))]
    y = [v for _, v in usable]
    fit = _ols(x, y)
    if fit is None:
        return {}
    beta, se = fit
    out: dict[str, dict] = {}
    for i, k in enumerate(keys):
        b, s = beta[i + 1], se[i + 1]
        t = b / s if s > 0 else 0.0
        out[k] = {
            "beta": round(b, 6),
            "se": round(s, 6),
            "t": round(t, 3),
            "p": round(p_two_sided(t), 6),
            "n_days": len(usable),
            "n_events": sum(1 for v in groups[k].values() if v > 0),
        }
    return out


def run_event_study(
    *,
    newsflash_path: Any = None,
    kline_db: Any = None,
    mapping: str = "v1",
    min_event_days: int = MIN_EVENT_DAYS,
    returns: dict[str, float] | None = None,
    records: Iterable[Any] | None = None,
) -> dict:
    """跑一遍事件研究 → {rows, diagnostics}。"""
    diag: dict[str, Any] = {
        "mapping": mapping,
        "mapping_version": MAPPING_VERSION,
        "degraded": False,
        "n_records": 0,
        "n_days": 0,
        "n_event_days_by_family": {},
        "n_dropped_insufficient": [],
    }
    try:
        rets = returns if returns is not None else load_daily_returns(kline_db)
        if not rets:
            diag.update(degraded=True, reason="no_returns")
            return {"rows": [], "diagnostics": diag}

        if records is None:
            path = Path(newsflash_path or DEFAULT_NEWSFLASH)
            events, dims = build_counts(_iter_jsonl(path), mapping)
        else:
            records = list(records)
            diag["n_records"] = len(records)
            events, dims = build_counts(records, mapping)

        days = sorted(rets)
        diag["n_days"] = len(days)
        events = {
            k: v for k, v in events.items() if sum(1 for c in v.values() if c > 0) >= min_event_days
        }
        diag["n_dropped_insufficient"] = sorted(set(EVENT_TYPE_FACTOR_DIMS) - set(events))
        diag["n_event_days_by_family"] = {
            k: sum(1 for c in v.values() if c > 0) for k, v in sorted(events.items())
        }
        if not events:
            diag.update(degraded=True, reason="no_family_with_enough_events")
            return {"rows": [], "diagnostics": diag}

        fam_w = {
            w: _regress_window(days, rets, events, w)
            for w in ("pre_24h", "post_24h", "pre_72h", "post_72h")
        }
        holm_p = holm(
            {k: v["p"] for k, v in fam_w["post_24h"].items()} if fam_w["post_24h"] else {}
        )

        rows: list[dict] = []
        for fam in events:
            pre = fam_w["pre_24h"].get(fam)
            post = fam_w["post_24h"].get(fam)
            if not pre or not post:
                continue
            verdict = classify_sensitivity(pre["beta"], post["beta"])
            hp = holm_p.get(fam, 1.0)
            pre72 = fam_w["pre_72h"].get(fam)
            post72 = fam_w["post_72h"].get(fam)
            eligible = bool(
                verdict["eligible"] and post["n_events"] >= min_event_days and hp < HOLM_ALPHA
            )
            rows.append(
                {
                    "unit": "event_family",
                    "key": fam,
                    "dims": list(EVENT_TYPE_FACTOR_DIMS.get(fam, ())),
                    "n_events": post["n_events"],
                    "n_days": post["n_days"],
                    "mean_excess_pre": pre["beta"],
                    "mean_excess_post": post["beta"],
                    "mean_excess_pre72": pre72["beta"] if pre72 else None,
                    "mean_excess_post72": post72["beta"] if post72 else None,
                    "sens_f": post["beta"],
                    "t_pre": pre["t"],
                    "t_post": post["t"],
                    "p_value": post["p"],
                    "p_post72": post72["p"] if post72 else None,
                    "p_holm": round(hp, 6),
                    "verdict": verdict["verdict"],
                    "eligible": eligible,
                    "direction": verdict["direction"],
                    "mapping": mapping,
                    "mapping_version": MAPPING_VERSION,
                }
            )

        dims = {
            k: v for k, v in dims.items() if sum(1 for c in v.values() if c > 0) >= min_event_days
        }
        dim_w = {
            w: _regress_window(days, rets, dims, w)
            for w in ("pre_24h", "post_24h", "pre_72h", "post_72h")
        }
        dim_holm = holm(
            {k: v["p"] for k, v in dim_w["post_24h"].items()} if dim_w["post_24h"] else {}
        )
        from data_center.processing.newsflash_events import _factors_by_dim

        for dim in dims:
            pre = dim_w["pre_24h"].get(dim)
            post = dim_w["post_24h"].get(dim)
            if not pre or not post:
                continue
            verdict = classify_sensitivity(pre["beta"], post["beta"])
            hp = dim_holm.get(dim, 1.0)
            pre72 = dim_w["pre_72h"].get(dim)
            post72 = dim_w["post_72h"].get(dim)
            rows.append(
                {
                    "unit": "dim",
                    "key": dim,
                    "dims": [dim],
                    "factor_ids": list(_factors_by_dim().get(dim, ())),
                    "n_events": post["n_events"],
                    "n_days": post["n_days"],
                    "mean_excess_pre": pre["beta"],
                    "mean_excess_post": post["beta"],
                    "mean_excess_pre72": pre72["beta"] if pre72 else None,
                    "mean_excess_post72": post72["beta"] if post72 else None,
                    "sens_f": post["beta"],
                    "t_pre": pre["t"],
                    "t_post": post["t"],
                    "p_value": post["p"],
                    "p_post72": post72["p"] if post72 else None,
                    "p_holm": round(hp, 6),
                    "verdict": verdict["verdict"],
                    "eligible": bool(verdict["eligible"] and hp < HOLM_ALPHA),
                    "direction": verdict["direction"],
                    "mapping": mapping,
                    "mapping_version": MAPPING_VERSION,
                }
            )

        rows.sort(key=lambda r: (r["unit"], -abs(r["sens_f"])))
        return {"rows": rows, "diagnostics": diag}
    except Exception as e:  # noqa: BLE003  FAIL-OPEN
        logger.warning("[FAIL-OPEN] run_event_study %s: %s", type(e).__name__, str(e)[:120])
        diag.update(degraded=True, reason=f"error:{type(e).__name__}")
        return {"rows": [], "diagnostics": diag}


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
