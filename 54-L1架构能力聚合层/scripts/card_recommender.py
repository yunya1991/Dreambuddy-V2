# -*- coding: utf-8 -*-
"""卡片模式「动态推荐」生产者（价格信号卡 · 回测打分）。

做什么：
  - 对固定候选池（8 张价格派生统计卡）按**可复现规则**逐资产回测：
    规则给出历史「触发/未触发」，再看触发后 5/20 日收益方向是否为正；
  - 汇总胜率、Wilson 下界、样本量与稳定性，按
    `score = 0.4*wilson5 + 0.6*wilson20`（样本不足扣分）排序；
  - 写出 `artifacts/cards/recommendation.json`，供 `/api/visual/cards/recommend`
    与卡片模式「动态推荐」tab 读取。

纪律：
  - 只读 DB、只写制品；不改能力层口径、不写库；
  - 只收录价格派生卡（趋势/动量/回撤/相关/状态/分位），不混入新闻/情绪；
  - 所有输出带 `n`、`win_rate`、`wilson_lb`、`stability`，并注明「历史统计，不代表未来」；
  - 样本不足（n<60）直接淘汰，不靠小样本硬推。

用法：
    python3 scripts/card_recommender.py --days 750 --json
    python3 scripts/card_recommender.py --dry-run
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import math
import os
import sys
from typing import Any, Dict, List, Optional, Sequence, Tuple

_MODULE_ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
_REPO_ROOT = os.path.normpath(os.path.join(_MODULE_ROOT, ".."))
if _MODULE_ROOT not in sys.path:
    sys.path.insert(0, _MODULE_ROOT)

from l1agg.align import load_leader  # noqa: E402

DB_PATH = os.path.join(_REPO_ROOT, "19-数据访问层", "data", "dreambuddy_core.db")
OUT_PATH = os.path.join(_MODULE_ROOT, "artifacts", "cards", "recommendation.json")
SYMBOLS = ("BTC", "ETH", "SOL", "US500", "XAU")
HORIZONS = (5, 20)
MIN_N = 60
Z = 1.96
DISCLAIMER = "历史统计，不代表未来"

# 候选池：capability_id / 标题 / 卡片形态 / 默认参数 / 一句话口径 / 规则键
CANDIDATES: Tuple[Dict[str, Any], ...] = (
    {
        "capability_id": "D-E15",
        "title": "趋势跟踪：价格 + EMA26",
        "kind": "series",
        "args": {"symbol": "BTC", "days": 750},
        "rule": "close_above_ema26",
        "desc": "收盘价站上 EMA26 视为趋势向上，观察后续 5/20 日收益方向",
    },
    {
        "capability_id": "D-G08",
        "title": "12-1 动量（跳过最近一月）",
        "kind": "table",
        "args": {"symbol": "BTC", "days": 750},
        "rule": "momentum_12_1_positive",
        "desc": "过去 12 个月（跳过最近 1 个月）累计收益为正 → 后续 20 日方向",
    },
    {
        "capability_id": "D-E01",
        "title": "20 日动量 → 后续收益",
        "kind": "table",
        "args": {"symbol": "BTC", "days": 750},
        "rule": "momentum_20_positive",
        "desc": "20 日动量为正 → 后续 5 日收益分布",
    },
    {
        "capability_id": "D-E02",
        "title": "价格分位（高位/低位）",
        "kind": "table",
        "args": {"symbol": "BTC", "days": 750},
        "rule": "price_percentile_high",
        "desc": "价格处于 250 日 80% 分位以上 → 后续 20 日方向",
    },
    {
        "capability_id": "D-E07",
        "title": "状态转移（涨跌延续）",
        "kind": "matrix",
        "args": {"symbol": "BTC", "days": 750},
        "rule": "up_state_persistence",
        "desc": "近 20 日收涨视作「涨态」→ 后续 5 日是否延续",
    },
    {
        "capability_id": "D-E10",
        "title": "回撤后修复",
        "kind": "series",
        "args": {"symbol": "BTC", "days": 750},
        "rule": "drawdown_rebound",
        "desc": "当前回撤超过 10% → 后续 20 日是否反弹",
    },
    {
        "capability_id": "D-E14",
        "title": "相关状态 → 前瞻分布",
        "kind": "table",
        "args": {"symbol": "BTC", "benchmark": "US500", "days": 750},
        "rule": "high_corr_state",
        "desc": "与基准 60 日相关 > 0.5 → 后续 20 日方向",
    },
    {
        "capability_id": "D-G20",
        "title": "动量分位胜率（最高档）",
        "kind": "table",
        "args": {"symbol": "BTC", "days": 750},
        "rule": "momentum_top_quintile",
        "desc": "20 日动量落在自身最高 20% 分位 → 后续 20 日方向",
    },
)


# ---------------------------------------------------------------- 规则（纯函数）
def _ema(values: Sequence[float], span: int) -> List[Optional[float]]:
    alpha = 2.0 / (span + 1.0)
    out: List[Optional[float]] = []
    current: Optional[float] = None
    for value in values:
        current = value if current is None else alpha * value + (1 - alpha) * current
        out.append(current)
    return out


def _rule_signals(
    rule: str, prices: Sequence[float], benchmark: Optional[Sequence[float]] = None
) -> List[Optional[bool]]:
    """返回与 prices 等长的「触发」标记；None 表示该点不可判定。"""
    n = len(prices)
    signals: List[Optional[bool]] = [None] * n
    if rule == "close_above_ema26":
        ema = _ema(prices, 26)
        for i in range(26, n):
            signals[i] = prices[i] > float(ema[i])
    elif rule == "momentum_12_1_positive":
        for i in range(252, n):
            signals[i] = prices[i - 21] / prices[i - 252] - 1.0 > 0
    elif rule == "momentum_20_positive":
        for i in range(20, n):
            signals[i] = prices[i] / prices[i - 20] - 1.0 > 0
    elif rule == "price_percentile_high":
        for i in range(249, n):
            sample = prices[i - 249 : i + 1]
            rank = sum(1 for value in sample if value <= prices[i])
            signals[i] = rank / len(sample) >= 0.8
    elif rule == "up_state_persistence":
        for i in range(20, n):
            signals[i] = prices[i] / prices[i - 20] - 1.0 > 0
    elif rule == "drawdown_rebound":
        peak = 0.0
        for i in range(1, n):
            peak = max(peak, prices[i - 1])
            if peak > 0:
                signals[i] = prices[i] / peak - 1.0 <= -0.10
    elif rule == "high_corr_state":
        if not benchmark or len(benchmark) < n:
            return signals
        window = 60
        for i in range(window, n):
            xs = prices[i - window : i + 1]
            ys = benchmark[i - window : i + 1]
            corr = _corr(xs, ys)
            signals[i] = corr is not None and corr > 0.5
    elif rule == "momentum_top_quintile":
        mom = [None] + [prices[i] / prices[i - 1] - 1.0 for i in range(1, n)]
        for i in range(60, n):
            sample = [mom[j] for j in range(i - 59, i + 1) if mom[j] is not None]
            if len(sample) < 30:
                continue
            rank = sum(1 for value in sample if value <= mom[i])
            signals[i] = rank / len(sample) >= 0.8
    return signals


def _corr(xs: Sequence[float], ys: Sequence[float]) -> Optional[float]:
    n = min(len(xs), len(ys))
    if n < 3:
        return None
    mx = sum(xs[:n]) / n
    my = sum(ys[:n]) / n
    cov = sum((xs[i] - mx) * (ys[i] - my) for i in range(n))
    vx = sum((xs[i] - mx) ** 2 for i in range(n))
    vy = sum((ys[i] - my) ** 2 for i in range(n))
    if vx <= 0 or vy <= 0:
        return None
    return cov / math.sqrt(vx * vy)


def _wilson(hits: int, n: int) -> float:
    if n == 0:
        return 0.0
    p = hits / n
    denom = 1 + Z * Z / n
    centre = p + Z * Z / (2 * n)
    margin = Z * math.sqrt(p * (1 - p) / n + Z * Z / (4 * n * n))
    return max(0.0, (centre - margin) / denom)


def _outcomes(
    prices: Sequence[float], signals: Sequence[Optional[bool]], horizon: int
) -> List[bool]:
    hits: List[bool] = []
    for i, signal in enumerate(signals):
        if signal is not True or i + horizon >= len(prices):
            continue
        base = prices[i]
        if not base:
            continue
        hits.append(prices[i + horizon] / base - 1.0 > 0)
    return hits


def _backtest_symbol(
    prices: Sequence[float],
    rule: str,
    benchmark: Optional[Sequence[float]] = None,
) -> Dict[str, Any]:
    signals = _rule_signals(rule, prices, benchmark)
    result: Dict[str, Any] = {}
    for horizon in HORIZONS:
        hits = _outcomes(prices, signals, horizon)
        n = len(hits)
        wins = sum(1 for item in hits if item)
        stability = None
        if n >= 2 * MIN_N:
            cut = int(n * 0.7)
            early = hits[:cut]
            late = hits[cut:]
            if early and late:
                stability = round(
                    sum(1 for x in late if x) / len(late) - sum(1 for x in early if x) / len(early),
                    4,
                )
        result[f"n_{horizon}d"] = n
        result[f"win_rate_{horizon}d"] = round(wins / n, 4) if n else None
        result[f"wilson_{horizon}d"] = round(_wilson(wins, n), 4)
        result[f"stability_{horizon}d"] = stability
    return result


def _aggregate(per_symbol: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    total: Dict[str, Any] = {"symbols": {}, "n_5d": 0, "n_20d": 0, "wins_5d": 0, "wins_20d": 0}
    for symbol, stats in per_symbol.items():
        total["symbols"][symbol] = stats
        for horizon in HORIZONS:
            n = int(stats.get(f"n_{horizon}d") or 0)
            rate = stats.get(f"win_rate_{horizon}d")
            total[f"n_{horizon}d"] += n
            if rate is not None:
                total[f"wins_{horizon}d"] += round(rate * n)
    for horizon in HORIZONS:
        n = total[f"n_{horizon}d"]
        total[f"win_rate_{horizon}d"] = round(total[f"wins_{horizon}d"] / n, 4) if n else None
        total[f"wilson_{horizon}d"] = round(_wilson(int(total[f"wins_{horizon}d"]), n), 4)
        stability = [
            stats.get(f"stability_{horizon}d")
            for stats in per_symbol.values()
            if stats.get(f"stability_{horizon}d") is not None
        ]
        total[f"stability_{horizon}d"] = (
            round(sum(stability) / len(stability), 4) if stability else None
        )
    return total


def recommend(days: int = 750, symbols: Sequence[str] = SYMBOLS) -> Dict[str, Any]:
    prices_cache: Dict[str, Dict[str, float]] = {}
    for symbol in symbols:
        try:
            prices_cache[symbol] = load_leader(DB_PATH, symbol, days=days)
        except Exception:  # noqa: BLE001 — 单资产失败不阻断整体推荐
            continue
    benchmark = prices_cache.get("US500")

    cards: List[Dict[str, Any]] = []
    for candidate in CANDIDATES:
        per_symbol: Dict[str, Dict[str, Any]] = {}
        for symbol, series in prices_cache.items():
            if candidate["rule"] == "high_corr_state" and symbol == "US500":
                continue
            bench = None
            if candidate["rule"] == "high_corr_state":
                if not benchmark:
                    continue
                # 相关状态按「资产 ∩ 基准」日期轴对齐，避免不同起点被整段跳过
                keys = sorted(set(series) & set(benchmark))
                bench = [benchmark[day] for day in keys]
            else:
                keys = sorted(series)
            prices = [series[day] for day in keys]
            per_symbol[symbol] = _backtest_symbol(prices, candidate["rule"], bench)
        if not per_symbol:
            continue
        total = _aggregate(per_symbol)
        if int(total["n_20d"] or 0) < MIN_N:
            continue
        score = 0.4 * float(total["wilson_5d"] or 0) + 0.6 * float(total["wilson_20d"] or 0)
        if int(total["n_20d"]) < 2 * MIN_N:
            score *= 0.9
        cards.append(
            {
                "capability_id": candidate["capability_id"],
                "title": candidate["title"],
                "kind": candidate["kind"],
                "args": candidate["args"],
                "rule": candidate["rule"],
                "desc": candidate["desc"],
                "n_5d": total["n_5d"],
                "n_20d": total["n_20d"],
                "win_rate_5d": total["win_rate_5d"],
                "win_rate_20d": total["win_rate_20d"],
                "wilson_5d": total["wilson_5d"],
                "wilson_20d": total["wilson_20d"],
                "stability_20d": total["stability_20d"],
                "score": round(score, 4),
                "symbols": sorted(per_symbol),
                "per_symbol": per_symbol,
            }
        )
    cards.sort(key=lambda item: (item["score"], item["n_20d"]), reverse=True)
    # 只推「20 日胜率 ≥ 50%」的卡；不足 6 张时放宽到得分前 6（并保留胜率披露）
    qualified = [card for card in cards if (card["win_rate_20d"] or 0) >= 0.5]
    selected = qualified if len(qualified) >= 6 else cards[:6]
    return {
        "version": 1,
        "generated_at": _dt.datetime.now().isoformat(timespec="seconds"),
        "data_version": _dt.datetime.now().strftime("db@%Y%m%d"),
        "days": int(days),
        "horizons": list(HORIZONS),
        "symbols": list(prices_cache),
        "method": "触发后 5/20 日收益方向胜率；score=0.4*wilson5+0.6*wilson20（n<120 扣 10%）",
        "disclaimer": DISCLAIMER,
        "selected_rule": "20 日胜率 ≥50%；不足 6 张时取得分前 6",
        "cards": selected,
    }


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="卡片模式动态推荐（价格信号回测打分）")
    parser.add_argument("--days", type=int, default=750)
    parser.add_argument("--out", default=OUT_PATH)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    payload = recommend(int(args.days))
    if not args.dry_run and payload["cards"]:
        os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
        tmp = args.out + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2)
        os.replace(tmp, args.out)
    summary = {
        "ok": bool(payload["cards"]),
        "out": "" if args.dry_run else args.out,
        "cards": [
            {
                "capability_id": card["capability_id"],
                "score": card["score"],
                "win_rate_20d": card["win_rate_20d"],
                "n_20d": card["n_20d"],
            }
            for card in payload["cards"]
        ],
        "generated_at": payload["generated_at"],
    }
    if args.json:
        print(json.dumps(summary, ensure_ascii=False))
    else:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if payload["cards"] else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
