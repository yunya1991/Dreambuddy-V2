#!/usr/bin/env python3
"""M3-3: PIT 回放工具（paper trading replay）。

读取 42/runtime/bus_history.jsonl 中的历史 bus snapshot，
逐条重放信号 → 50 决策流水线 → 输出方向命中/分布报告。

命中判定（A/B 方向命中）：
  - 若提供了未来价格序列（--prices 路径，JSON: {ts: price}），
    则按决策方向 vs 后续 N 根收益方向判定 hit。
  - 若无价格数据，仅输出样本数/方向分布/置信度分布（工程验证模式）。

用法：
  python3 tools/pit_replay.py [--bus-history PATH] [--prices PATH] [--horizon-bars 5]
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[2]
_50_ROOT = _REPO_ROOT / "50-NN主矛盾评估器"
_42_ROOT = _REPO_ROOT / "42-神经网络交易协调层"

if str(_50_ROOT) not in sys.path:
    sys.path.insert(0, str(_50_ROOT))

from core.decision import make_decision  # noqa: E402


def load_bus_history(path: str | Path) -> list[dict]:
    """加载 bus_history.jsonl，跳过损坏行（fail-open）。"""
    path = Path(path)
    if not path.exists():
        return []
    snapshots: list[dict] = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                snapshots.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return snapshots


def _parse_ts(value: str) -> datetime | None:
    if not value:
        return None
    try:
        text = value.replace("Z", "+00:00")
        return datetime.fromisoformat(text)
    except (ValueError, TypeError):
        return None


def load_prices(path: str | Path | None) -> dict[datetime, float]:
    """加载价格序列 JSON: {"2026-11-09T00:00:00Z": 43000.0, ...}。"""
    if not path:
        return {}
    p = Path(path)
    if not p.exists():
        return {}
    try:
        with open(p, encoding="utf-8") as f:
            raw = json.load(f)
        return {_parse_ts(k): float(v) for k, v in raw.items() if _parse_ts(k) is not None}
    except Exception:  # noqa: BLE001
        return {}


def replay_snapshot(snapshot: dict) -> dict | None:
    """重放单条 bus snapshot → 50 决策。返回 decision 或 None。"""
    signals = snapshot.get("signals") or []
    if not signals:
        return None
    evidences = []
    for sig in signals:
        evidences.append(
            {
                "evidence_id": sig.get("signal_id", ""),
                "source": sig.get("source"),
                "symbol": sig.get("symbol", "MULTI"),
                "granularity": "per_symbol",
                "direction": sig.get("direction", "neutral"),
                "confidence": sig.get("confidence", 0.0),
                "horizon": sig.get("horizon", "hours"),
                "intent": None,
                "ts": sig.get("ts"),
                "expires_at": sig.get("expires_at"),
                "provenance": "42-bus",
                "payload": sig.get("payload", {}),
            }
        )
    try:
        return make_decision(evidences)
    except Exception:  # noqa: BLE001  fail-open：单条快照失败不阻断回放
        return None


def compute_hit(decision: dict, prices: dict[datetime, float], horizon_bars: int) -> bool | None:
    """判定决策方向是否命中后续收益方向。无价格数据返回 None。"""
    if not prices:
        return None
    ts = _parse_ts(decision.get("ts", ""))
    direction = decision.get("direction")
    if ts is None or direction not in ("long", "short"):
        return None
    sorted_prices = sorted(prices.items())
    # 找决策时刻之后的价格
    future = [(t, p) for t, p in sorted_prices if t > ts]
    if len(future) < horizon_bars + 1:
        return None
    entry = future[0][1]
    exit_p = future[horizon_bars][1]
    ret = (exit_p - entry) / entry if entry else 0.0
    if direction == "long":
        return ret > 0
    return ret < 0  # short


def run_replay(
    bus_history_path: str | Path,
    prices_path: str | Path | None = None,
    horizon_bars: int = 5,
) -> dict[str, Any]:
    """执行回放并返回报告。"""
    snapshots = load_bus_history(bus_history_path)
    prices = load_prices(prices_path)

    decisions: list[dict] = []
    for snap in snapshots:
        d = replay_snapshot(snap)
        if d is not None:
            decisions.append(d)

    direction_counts = Counter(d.get("direction", "neutral") for d in decisions)
    confidence_values = [d.get("confidence", 0.0) for d in decisions]
    avg_conf = sum(confidence_values) / len(confidence_values) if confidence_values else 0.0

    # 命中统计
    hits, misses, unknown = 0, 0, 0
    for d in decisions:
        h = compute_hit(d, prices, horizon_bars)
        if h is True:
            hits += 1
        elif h is False:
            misses += 1
        else:
            unknown += 1
    total_evaluated = hits + misses
    hit_rate = (hits / total_evaluated) if total_evaluated > 0 else None

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "bus_history_path": str(bus_history_path),
        "n_snapshots": len(snapshots),
        "n_decisions": len(decisions),
        "direction_distribution": dict(direction_counts),
        "confidence_avg": round(avg_conf, 6),
        "confidence_min": round(min(confidence_values), 6) if confidence_values else 0.0,
        "confidence_max": round(max(confidence_values), 6) if confidence_values else 0.0,
        "hit_evaluation": {
            "horizon_bars": horizon_bars,
            "hits": hits,
            "misses": misses,
            "unknown": unknown,
            "hit_rate": round(hit_rate, 6) if hit_rate is not None else None,
            "note": "无价格数据时仅输出分布统计" if not prices else None,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="M3-3 PIT 回放工具")
    parser.add_argument(
        "--bus-history",
        default=str(_42_ROOT / "runtime" / "bus_history.jsonl"),
        help="bus_history.jsonl 路径",
    )
    parser.add_argument("--prices", default=None, help="价格序列 JSON 路径（可选，用于命中判定）")
    parser.add_argument("--horizon-bars", type=int, default=5, help="命中判定的未来 bar 数")
    args = parser.parse_args()

    report = run_replay(args.bus_history, args.prices, args.horizon_bars)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
