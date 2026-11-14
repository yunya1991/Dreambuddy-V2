# -*- coding: utf-8 -*-
"""三项可执行能力（对应 hooks 的第 2/3/4 项）。

  1. `leader_gap`          同赛道龙头对照：同期涨跌幅差 + 日变动相关
  2. `top_correlated`      与目标资产相关性最高的指标（Pearson + BH-FDR）
  3. `persistence_strength` 趋势延续性强度（Hurst / VR / AR1 / 连涨连跌）

全部只读、确定性、纯 stdlib；口径统一走 `align`（UTC 日轴 + asof 前向填充）。
"""

from __future__ import annotations

from datetime import date as _date
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

from . import align
from .hooks import group_of, label_of, peer_of, short_of
from .methods.stats_core import bh_fdr, corr_p
from .persistence._stats import pearson


class RelationError(ValueError):
    """相关性/对照能力不可用（数据不足或标的不存在）。"""


def _diff(values: List[float]) -> List[float]:
    return [b - a for a, b in zip(values, values[1:], strict=False)]


def _corr(xs: List[float], ys: List[float]) -> Tuple[Optional[float], Optional[float], int]:
    n = min(len(xs), len(ys))
    if n < 3:
        return None, None, n
    try:
        r = pearson(xs[:n], ys[:n])
    except Exception:  # 常数序列等退化情况
        return None, None, n
    return r, corr_p(r, n), n


def leader_gap(
    db_path: str,
    symbol: str,
    *,
    peer: Optional[str] = None,
    days: int = 365,
    min_n: int = 30,
) -> Dict[str, object]:
    """同期涨跌幅对照：目标资产 vs 同赛道龙头（默认基准）。

    Raises:
        RelationError: 任一侧无数据或重叠样本不足。
    """
    sym = (symbol or "").upper()
    other = (peer or peer_of(sym)).upper()
    try:
        a = align.load_leader(db_path, sym, days=days)
        b = align.load_leader(db_path, other, days=days)
    except align.AlignError as exc:
        raise RelationError(str(exc)) from exc

    common = sorted(set(a) & set(b))
    if len(common) < min_n:
        raise RelationError(f"{sym} 与 {other} 重叠样本 {len(common)} < {min_n}，无法对照")

    av = [a[d] for d in common]
    bv = [b[d] for d in common]
    a_pct = (av[-1] / av[0] - 1.0) * 100.0 if av[0] else None
    b_pct = (bv[-1] / bv[0] - 1.0) * 100.0 if bv[0] else None
    r, p, n = _corr(_diff(av), _diff(bv))

    gap = None if (a_pct is None or b_pct is None) else a_pct - b_pct
    span = f"{common[0]}~{common[-1]}"

    def _fmt(x: Optional[float]) -> str:
        return "N/A" if x is None else f"{x:+.2f}%"

    text = (
        f"{label_of(sym)} vs {label_of(other)}（{span}，{n} 个日变动）："
        f"{short_of(sym)} {_fmt(a_pct)}，{short_of(other)} {_fmt(b_pct)}，"
        f"强弱差 {_fmt(gap)}；日变动相关 r="
        f"{'N/A' if r is None else f'{r:.3f}'}"
        f"（{'p=N/A' if p is None else f'p={p:.2g}'}）。"
    )
    return {
        "capability": "leader_compare",
        "symbol": sym,
        "peer": other,
        "span": span,
        "sample_n": n,
        "symbol_pct": None if a_pct is None else round(a_pct, 4),
        "peer_pct": None if b_pct is None else round(b_pct, 4),
        "gap_pp": None if gap is None else round(gap, 4),
        "corr": None if r is None else round(r, 6),
        "p_value": p,
        "align_method": align.ALIGN_METHOD,
        "timezone": align.TIMEZONE,
        "text": text,
    }


_PRICE_METRICS = {
    "volume_usd",
    "last",
    "open",
    "high",
    "low",
    "bid",
    "ask",
    "vwap",
}


def _is_price_like(symbol: str, sub: str, metric: str) -> bool:
    """同质价格类序列：自身价格/成交量/盘口、市值等价格衍生量。

    跨资产价格（黄金、铜、美股指数）**不算**同质价格——它们是用户要的「多维数据」。
    """
    if sub.upper() == symbol:
        return True
    if sub.upper().startswith(symbol + "/"):
        return True
    if metric in _PRICE_METRICS:
        return True
    if "market_cap" in metric or "price" in metric:
        return True
    if metric == "close_usd":
        return group_of(sub) == "crypto"
    return False


_EXTRA_LABELS = {
    ("long_short_ratio", "long_account_pct"): "合约多头账户占比",
    ("long_short_ratio", "short_account_pct"): "合约空头账户占比",
    ("long_short_ratio", "long_short_ratio"): "合约多空账户比",
    ("open_interest", "open_interest"): "未平仓合约",
    ("open_interest", "open_interest_value_binance"): "币安未平仓合约",
    ("open_interest", "open_interest_value"): "未平仓合约（名义）",
    ("BTC_FUTURES_CME", "noncomm_net"): "CME 非商业净持仓",
    ("BTC_FUTURES_CME", "comm_short"): "CME 商业空头持仓",
    ("BTC_FUTURES_CME", "comm_long"): "CME 商业多头持仓",
    ("XCU", "close_usd"): "铜价（LME）",
    ("XAG", "close_usd"): "白银价格",
    ("XAU", "close_usd"): "黄金价格",
    ("CL", "close_usd"): "WTI 原油价格",
    ("BZ", "close_usd"): "布伦特原油价格",
    ("NG", "close_usd"): "天然气价格",
}


def _label_index() -> Dict[Tuple[str, str], str]:
    """(sub, metric) → 中文名（METRIC_ALIASES + CURATED_SERIES + 兜底）。"""
    from .series_catalog import CURATED_SERIES, METRIC_ALIASES

    idx: Dict[Tuple[str, str], str] = {}
    for (sub, metric), _aliases, label, _unit, _days in METRIC_ALIASES:
        idx[(sub, metric)] = label
    for item in CURATED_SERIES:
        key = (item["sub_category"], item["metric_name"])
        idx[key] = item.get("label") or idx.get(key, f"{key[0]}::{key[1]}")
    for key, label in _EXTRA_LABELS.items():
        idx.setdefault(key, label)
    return idx


def _fallback_label(sub: str, metric: str) -> str:
    """未登记序列名的兜底：FRED 代码类标注来源，其余保持 sub::metric。"""
    if sub == "macro_us_stocks" and metric.startswith("us_") and metric.endswith("_value"):
        return f"FRED {metric[3:-6]}"
    if metric == "value" and sub.isupper() and any(ch.isdigit() for ch in sub):
        return f"FRED {sub}"
    return f"{sub}::{metric}"


def _load_series(db_path: str, start_ts: int) -> Dict[Tuple[str, str], Dict[str, float]]:
    """一次 SQL 读取窗口内全部序列的「日聚合值」，返回 {(sub, metric): {day: value}}。"""
    import sqlite3

    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        rows = conn.execute(
            """
            SELECT sub_category, metric_name, date(timestamp, 'unixepoch') AS d,
                   AVG(metric_value)
            FROM mm_metrics
            WHERE timestamp >= ?
            GROUP BY 1, 2, 3
            """,
            (int(start_ts),),
        ).fetchall()
    finally:
        conn.close()

    out: Dict[Tuple[str, str], Dict[str, float]] = {}
    for sub, metric, day, value in rows:
        if value is None:
            continue
        out.setdefault((sub, metric), {})[day] = float(value)
    return out


def _freq_of(median_gap: float) -> str:
    if median_gap <= 4:
        return "daily"
    if median_gap <= 20:
        return "weekly"
    return "monthly"


_FREQ_MIN_N = {"daily": 120, "weekly": 52, "monthly": 36}
_FREQ_GROUP_MIN_N = {"daily": 20, "weekly": 16, "monthly": 24}


def top_correlated(
    db_path: str,
    symbol: str,
    *,
    top_k: int = 3,
    days: int = 1095,
    min_n: int = 120,
) -> Dict[str, object]:
    """多维指标 × 价格：按「指标观测区间 Δ vs 价格同期 Δ」计算相关（BH-FDR）。

    设计口径（2026-11-14 用户纠正后）：
      - **排除同质价格**（ETH/SOL/市值/盘口/成交量），不把「币价 vs 币价」当指标；
      - 指标按自身观测频率分组（daily/weekly/monthly），**不做日频 ffill**，
        避免低频指标被重复值稀释出伪相关；
      - 每组独立 BH-FDR（不同频率的 p 值不可混合校正）；
      - 样本不足 `_FREQ_MIN_N` 的单列 `low_sample`，仅作参考、不参与排名；
      - 资产价格相关性单列 `price_baseline`（同赛道对照，不称「指标」）。
    """
    import statistics

    sym = (symbol or "").upper()
    try:
        price = align.load_leader(db_path, sym, days=days)
    except align.AlignError as exc:
        raise RelationError(str(exc)) from exc
    if len(price) < min_n:
        raise RelationError(f"{sym} 价格样本 {len(price)} < {min_n}，无法计算相关性")

    now_ts = int(datetime.now(tz=timezone.utc).timestamp()) + 86400
    start_ts = now_ts - int(days) * 86400
    series = _load_series(db_path, start_ts)
    labels = _label_index()
    price_days = set(price)

    ranked: List[Dict[str, object]] = []
    prices: List[Dict[str, object]] = []
    low: List[Dict[str, object]] = []

    for (sub, metric), values in series.items():
        if (sub, metric) == (sym, "close_usd"):
            continue
        obs = sorted(values)
        if len(obs) < 24:
            continue
        gaps = [
            (_date.fromisoformat(b) - _date.fromisoformat(a)).days
            for a, b in zip(obs, obs[1:], strict=False)
        ]
        median_gap = statistics.median(gaps) if gaps else 1
        freq = _freq_of(median_gap)
        pairs = [
            (p, d)
            for p, d in zip(obs, obs[1:], strict=False)
            if p in price_days and d in price_days
        ]
        n = len(pairs)
        if n < _FREQ_GROUP_MIN_N[freq]:
            continue
        r, p, _ = _corr(
            [values[d] - values[p] for p, d in pairs],
            [price[d] - price[p] for p, d in pairs],
        )
        if r is None:
            continue
        row = {
            "sub_category": sub,
            "metric_name": metric,
            "label": labels.get((sub, metric)) or _fallback_label(sub, metric),
            "r": round(r, 6),
            "p_value": p,
            "sample_n": n,
            "freq": freq,
            "median_gap_days": median_gap,
            "span": f"{pairs[0][0]}~{pairs[-1][1]}",
        }
        if _is_price_like(sym, sub, metric):
            # 对照只保留其他资产的收盘价；自身盘口/成交量/市值等噪音直接丢弃
            if (
                metric == "close_usd"
                and sub.upper() != sym
                and not sub.upper().startswith(sym + "/")
            ):
                prices.append(row)
        elif n < _FREQ_MIN_N[freq]:
            low.append(row)
        else:
            ranked.append(row)

    if not ranked and not low:
        raise RelationError(f"未找到与 {sym} 可对齐的多维指标（days={days}）")

    def _dedupe(items: List[Dict[str, object]]) -> List[Dict[str, object]]:
        """同一 sub_category 只保留 |r| 最大的一条（避免多空镜像等重复计数）。"""
        best: Dict[str, Dict[str, object]] = {}
        for it in items:
            key = str(it["sub_category"])
            if key not in best or abs(float(it["r"])) > abs(float(best[key]["r"])):
                best[key] = it
        return list(best.values())

    groups: Dict[str, List[Dict[str, object]]] = {}
    for freq in ("daily", "weekly", "monthly"):
        bucket = _dedupe([x for x in ranked if x["freq"] == freq])
        if not bucket:
            continue
        fdr = bh_fdr([1.0 if x["p_value"] is None else float(x["p_value"]) for x in bucket])
        for row, q, reject in zip(bucket, fdr["q"], fdr["reject"], strict=False):
            row["q_value"] = q
            row["significant"] = bool(reject)
            row["alpha"] = fdr["alpha"]
        bucket.sort(key=lambda x: abs(float(x["r"])), reverse=True)
        groups[freq] = bucket

    prices.sort(key=lambda x: abs(float(x["r"])), reverse=True)
    low.sort(key=lambda x: abs(float(x["r"])), reverse=True)

    main_freq = "daily" if "daily" in groups else ("weekly" if "weekly" in groups else "monthly")
    main = groups.get(main_freq, [])[: max(1, int(top_k))]
    _FREQ_CN = {"daily": "日频", "weekly": "周频", "monthly": "月频"}

    def _fmt(x: Dict[str, object]) -> str:
        q = x.get("q_value")
        qs = "q=N/A" if q is None else ("q<1e-4" if q < 1e-4 else f"q={q:.3g}")
        return (
            f"{x['label']} r={x['r']:+.3f}（n={x['sample_n']}，{qs}"
            f"{'，显著' if x.get('significant') else ''}）"
        )

    if main:
        seg = "；".join(_fmt(x) for x in main)
        text = (
            f"与{label_of(sym)}日变动相关性最高的多维指标（{_FREQ_CN[main_freq]}，"
            f"n≥{_FREQ_MIN_N[main_freq]}，BH-FDR α=0.05）：{seg}。"
        )
    else:
        text = f"与{label_of(sym)}可对齐的多维指标样本均不足，暂无可排名结果。"

    monthly = list(groups.get("monthly", [])[:2])
    if monthly and main_freq != "monthly":
        text += f"月频指标：{'；'.join(_fmt(x) for x in monthly)}。"
    if low:
        text += f"样本不足（仅供参考）：{_fmt(low[0])}。"
    if prices:
        text += f"资产价格对照（不参与指标排名）：{_fmt(prices[0])}。"

    return {
        "capability": "top_correlation",
        "symbol": sym,
        "scanned": len(ranked) + len(low) + len(prices),
        "method": "delta_pearson_by_observation_freq",
        "groups": groups,
        "topk": main,
        "monthly": monthly,
        "low_sample": low[:3],
        "price_baseline": prices[:3],
        "alpha": 0.05,
        "align_method": "observation_delta",
        "timezone": align.TIMEZONE,
        "text": text,
    }


def persistence_strength(
    db_path: str,
    symbol: str,
    *,
    days: int = 1200,
) -> Dict[str, object]:
    """趋势延续性强度：Hurst / 方差比 / AR(1) 半衰期 / 连涨连跌。"""
    from .persistence import build_profile

    sym = (symbol or "").upper()
    try:
        profile = build_profile(db_path, sym, days=days)
    except Exception as exc:  # 数据缺失/样本不足统一转成可展示的降级
        raise RelationError(f"{sym} 延续性画像不可用：{exc}") from exc

    m = profile.get("metrics") or {}
    if not profile.get("sample_n"):
        raise RelationError(f"{sym} 无价格历史，无法评估延续性")
    h = m.get("hurst") or {}
    vr = m.get("variance_ratio") or []
    ar1 = m.get("ar1") or {}
    runs = m.get("runs") or {}

    hval = h.get("h")
    if hval is None:
        strength = "unknown"
    elif hval >= 0.6:
        strength = "strong"
    elif hval >= 0.55:
        strength = "medium"
    else:
        strength = "weak"

    vr5 = next((v for v in vr if v.get("q") == 5), None)
    text = (
        f"{label_of(sym)}趋势延续性强度：{strength}"
        f"（Hurst={'N/A' if hval is None else hval}"
        f"{'，' + str(h.get('regime')) if h.get('regime') else ''}"
        f"；VR(5)={'N/A' if not vr5 else vr5.get('vr')}"
        f"；AR(1) 半衰期={ar1.get('halflife_days')} 日"
        f"；最长连涨/连跌={runs.get('max_up')}/{runs.get('max_down')} 日）。"
        f"{profile.get('caveat', '')}"
    )
    return {
        "capability": "persistence_strength",
        "symbol": sym,
        "strength": strength,
        "sample_n": profile.get("sample_n"),
        "span": profile.get("span"),
        "hurst": hval,
        "regime": h.get("regime"),
        "variance_ratio": vr,
        "ar1": ar1,
        "runs": runs,
        "quality": profile.get("quality"),
        "text": text,
    }
