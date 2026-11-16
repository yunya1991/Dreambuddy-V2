#!/usr/bin/env python3
"""signal_paper.py — 信号 paper 记账 runner（TASKS-20261116 T6-4 生产侧）。

链路（只记，不接执行层）：
  relationship_registry.db（D-K03 只读出口）→ 逐日回放 → 门控 →
  `data/signal_ledger.db::signal_journal`（幂等：ledger_id 由
  as_of|target|horizon|direction|decision 派生）

context 口径（如实标注，缺就不给，让门控记 missing_context，不估算）：
  - `ma_state`  ：收盘价 vs 60 日均线（> 为 up，否则 down）
  - `vol_pct`   ：20 日已实现波动率在过去 250 日窗口中的分位（0–1）
  - `crowd_pct` ：当日成交额在过去 250 日中的分位（OHLCV 代理；**不是**资金费率/持仓量）

FAIL-OPEN：注册表缺失 / 单标的无历史 → 跳过并计数，不写空信号，不抛到调用方之外。
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
from datetime import datetime, timezone
from typing import Any, Dict, List, Mapping, Optional, Sequence

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_L1_DIR = os.path.dirname(_SCRIPT_DIR)
_REPO_ROOT = os.path.dirname(_L1_DIR)
if _L1_DIR not in sys.path:
    sys.path.insert(0, _L1_DIR)

DEFAULT_CORE_DB = os.environ.get("DREAMBUDDY_CORE_DB") or os.path.join(
    _REPO_ROOT, "19-数据访问层", "data", "dreambuddy_core.db"
)
DEFAULT_REGISTRY = os.environ.get("SIGNAL_REGISTRY") or os.path.join(
    _REPO_ROOT, "data", "mers", "registry.db"
)
VOL_WINDOW = 20
PCT_WINDOW = 250
MA_WINDOW = 60


def _percentile_rank(series: Sequence[float], value: float) -> Optional[float]:
    if not series:
        return None
    below = sum(1 for item in series if item < value)
    equal = sum(1 for item in series if item == value)
    if not series:
        return None
    return (below + 0.5 * equal) / len(series)


def _rolling_vol(prices: Mapping[str, float], dates: Sequence[str]) -> Dict[str, Optional[float]]:
    out: Dict[str, Optional[float]] = {}
    logs: List[Optional[float]] = [None]
    for prev, curr in zip(dates, dates[1:], strict=False):
        a, b = prices.get(prev), prices.get(curr)
        if not a or not b or a <= 0 or b <= 0:
            logs.append(None)
        else:
            logs.append(math.log(b / a))
    for idx, day in enumerate(dates):
        if idx + 1 < VOL_WINDOW:
            out[day] = None
            continue
        window = logs[idx - VOL_WINDOW + 1 : idx + 1]
        if any(item is None for item in window):
            out[day] = None
            continue
        mean = sum(window) / len(window)  # type: ignore[arg-type]
        var = sum((item - mean) ** 2 for item in window) / len(window)  # type: ignore[arg-type]
        out[day] = math.sqrt(var * 252)
    return out


def build_context(
    prices: Mapping[str, float],
    volumes: Optional[Mapping[str, float]],
    dates: Sequence[str],
    as_of: str,
    vol_series: Optional[Mapping[str, Optional[float]]] = None,
) -> Dict[str, Any]:
    """单标的单日 context；任一输入缺失就不给该键（门控会记原因）。"""
    idx = {day: i for i, day in enumerate(dates)}
    pos = idx.get(as_of)
    if pos is None or pos < MA_WINDOW:
        return {}
    window = [prices[dates[i]] for i in range(pos - MA_WINDOW + 1, pos + 1)]
    close = prices.get(as_of)
    if close is None or not window:
        return {}
    ma = sum(window) / len(window)
    context: Dict[str, Any] = {"ma_state": "up" if close >= ma else "down"}

    vol_series = vol_series or _rolling_vol(prices, dates)
    vol_now = vol_series.get(as_of)
    trail = [vol_series[dates[i]] for i in range(max(0, pos - PCT_WINDOW + 1), pos + 1)]
    trail = [item for item in trail if item is not None]
    if vol_now is not None and len(trail) >= 60:
        context["vol_pct"] = round(_percentile_rank(trail, vol_now), 4)

    if volumes:
        volume_now = volumes.get(as_of)
        vtrail = [
            volumes[dates[i]]
            for i in range(max(0, pos - PCT_WINDOW + 1), pos + 1)
            if dates[i] in volumes
        ]
        if volume_now is not None and len(vtrail) >= 60:
            context["crowd_pct"] = round(_percentile_rank(vtrail, volume_now), 4)
    return context


def _volume_series(db_path: str, symbol: str, days: int) -> Dict[str, float]:
    """成交额序列：按龙头绑定的 sub_category，把 close_* 换成 volume_*。"""
    from l1agg import align
    from l1agg.leader_registry import resolve

    binding = resolve(symbol)
    if binding is None or "close" not in binding.metric_name:
        return {}
    metric = binding.metric_name.replace("close", "volume")
    try:
        return align.load_daily(db_path, binding.sub_category, metric, start_ts=0, end_ts=2**40)
    except Exception:
        return {}


def run(
    *,
    days: int = 60,
    step: int = 1,
    top: int = 3,
    targets: Optional[Sequence[str]] = None,
    registry: str = DEFAULT_REGISTRY,
    db_path: str = DEFAULT_CORE_DB,
    ledger: Optional[str] = None,
    dry_run: bool = False,
) -> Dict[str, Any]:
    from l1agg import align
    from l1agg.capabilities.signal_exports import signal_query
    from l1agg.signal_ledger import record_signals

    if not os.path.isfile(registry):
        return {
            "ok": False,
            "reason": "registry_missing",
            "detail": "关系评估注册表尚未生成（先跑 MERS 网格：scripts/mers_eval.py）",
            "registry": registry,
            "recorded": {"inserted": 0, "duplicates": 0},
        }

    env = signal_query(db_path=registry, gate=False, top=top)
    base_signals = ((env.get("data") or {}).get("capabilities") or {}).get("D-K03") or {}
    candidate_targets = sorted(
        {
            str(item.get("target"))
            for item in base_signals.get("signals") or []
            if item.get("target")
        }
    )
    picked_targets = [t for t in (targets or candidate_targets) if t]
    if not picked_targets:
        return {
            "ok": True,
            "reason": "no_base_signals",
            "detail": "注册表里没有 gate_pass 的关系行，无法产信号（不补造）",
            "registry": registry,
            "recorded": {"inserted": 0, "duplicates": 0},
        }

    price_book: Dict[str, Dict[str, float]] = {}
    volume_book: Dict[str, Dict[str, float]] = {}
    skipped: List[Dict[str, str]] = []
    for symbol in picked_targets:
        try:
            price_book[symbol] = align.load_leader(db_path, symbol, days=1600)
        except Exception as exc:
            skipped.append({"target": symbol, "reason": f"{type(exc).__name__}: {exc}"})
            continue
        volume_book[symbol] = _volume_series(db_path, symbol, 1600)

    usable = sorted(price_book)
    if not usable:
        return {
            "ok": False,
            "reason": "no_price_series",
            "detail": "所有候选标的都没有日线序列",
            "skipped": skipped,
            "recorded": {"inserted": 0, "duplicates": 0},
        }

    # 频率对齐到入选标的的共同交易日，保证 context 与 as_of 一致
    common = sorted(set.intersection(*(set(price_book[s]) for s in usable)))
    common = common[-max(1, int(days)) :][:: max(1, int(step))]
    if not common:
        return {
            "ok": False,
            "reason": "no_aligned_dates",
            "skipped": skipped,
            "recorded": {"inserted": 0, "duplicates": 0},
        }

    recorded = {"inserted": 0, "duplicates": 0}
    allowed = blocked = 0
    reasons: Dict[str, int] = {}
    per_date: List[Dict[str, Any]] = []
    calendar = {symbol: sorted(price_book[symbol]) for symbol in usable}
    vol_book = {symbol: _rolling_vol(price_book[symbol], calendar[symbol]) for symbol in usable}

    for as_of in common:
        context = {
            symbol: build_context(
                price_book[symbol],
                volume_book.get(symbol),
                calendar[symbol],
                as_of,
                vol_book[symbol],
            )
            for symbol in usable
        }
        context = {symbol: value for symbol, value in context.items() if value}
        daily = signal_query(db_path=registry, as_of=as_of, context=context, gate=True, top=top)
        block = ((daily.get("data") or {}).get("capabilities") or {}).get("D-K03") or {}
        signals = []
        for item in block.get("signals") or []:
            signal = dict(item)
            signal.setdefault("as_of", as_of)
            signals.append(signal)
        blocked_items = []
        for item in block.get("blocked") or []:
            signal = dict(item)
            signal.setdefault("as_of", as_of)
            blocked_items.append(signal)
            for reason in ((signal.get("gating") or {}).get("reasons")) or []:
                reasons[str(reason)] = reasons.get(str(reason), 0) + 1
        allowed += len(signals)
        blocked += len(blocked_items)
        if not dry_run and (signals or blocked_items):
            result = record_signals(
                {"signals": signals, "blocked": blocked_items},
                db_path=ledger,
                recorded_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            )
            recorded["inserted"] += int(result.get("inserted") or 0)
            recorded["duplicates"] += int(result.get("duplicates") or 0)
        per_date.append({"as_of": as_of, "allowed": len(signals), "blocked": len(blocked_items)})

    return {
        "ok": True,
        "registry": registry,
        "targets": usable,
        "dates": {"count": len(common), "first": common[0], "last": common[-1]},
        "gate": {
            "allowed": allowed,
            "blocked": blocked,
            "by_reason": dict(sorted(reasons.items())),
        },
        "recorded": recorded,
        "dry_run": dry_run,
        "skipped": skipped,
        "per_date": per_date[-5:],
    }


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(add_help=True)
    parser.add_argument("--days", type=int, default=60)
    parser.add_argument("--step", type=int, default=1)
    parser.add_argument("--top", type=int, default=3)
    parser.add_argument("--targets", default="", help="逗号分隔；默认取注册表里 gate_pass 的标的")
    parser.add_argument("--registry", default=DEFAULT_REGISTRY)
    parser.add_argument("--db", default=DEFAULT_CORE_DB)
    parser.add_argument("--ledger", default="")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    try:
        payload = run(
            days=max(1, int(args.days)),
            step=max(1, int(args.step)),
            top=max(1, int(args.top)),
            targets=[item.strip() for item in args.targets.split(",") if item.strip()] or None,
            registry=args.registry,
            db_path=args.db,
            ledger=args.ledger or None,
            dry_run=args.dry_run,
        )
    except Exception as exc:  # FAIL-OPEN
        payload = {"ok": False, "reason": "exception", "error": f"{type(exc).__name__}: {exc}"}
    sys.stdout.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")


if __name__ == "__main__":
    main()
