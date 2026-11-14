#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""M4-4 live 归因报告：50 outbox 决策 × 22 成交台账 join。

用途：小额实盘期间随时复盘"overlay 到底改变了什么、有没有真的成交"，
      为后续调系数 / 关开关 / 回滚提供数据依据。

输入（只读）：
- 50 `runtime/live/outbox.jsonl`：每条含 payload.factor_priors_overlay
  （enabled / coef / degraded / attribution 反事实基线）
- 22 `audit/x1_live_fills.jsonl`：每条含 decision_id / order_placed / reference_px

输出：JSON 到 stdout（或 --out 落盘）。
局限：台账只有开仓侧，PnL 需平仓回报，故本次不给收益归因，只给"影响面 + 成交面"。
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

_50_ROOT = Path(__file__).resolve().parents[1]
_REPO_ROOT = _50_ROOT.parent
DEFAULT_OUTBOX = _50_ROOT / "runtime" / "live" / "outbox.jsonl"
DEFAULT_LEDGER = _REPO_ROOT / "22-执行引擎中心" / "audit" / "x1_live_fills.jsonl"


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            rows.append(obj)
    return rows


def _load_ledger(path: Path) -> dict[str, dict[str, Any]]:
    """decision_id -> 最后一条成交记录（同 id 重复执行以最新为准）。"""
    ledger: dict[str, dict[str, Any]] = {}
    for row in _read_jsonl(path):
        key = str(row.get("decision_id") or "")
        if key:
            ledger[key] = row
    return ledger


def _overlay_of(decision: dict[str, Any]) -> dict[str, Any]:
    payload = decision.get("payload")
    audit = payload.get("factor_priors_overlay") if isinstance(payload, dict) else None
    return audit if isinstance(audit, dict) else {}


def build_report(outbox: Path, ledger_path: Path) -> dict[str, Any]:
    decisions = _read_jsonl(outbox)
    ledger = _load_ledger(ledger_path)

    rows: list[dict[str, Any]] = []
    coef_counter: Counter[str] = Counter()
    degraded_counter: Counter[str] = Counter()
    flips = 0
    delta_conf: list[float] = []
    delta_pos: list[float] = []
    filled = 0

    for decision in decisions:
        did = str(decision.get("decision_id") or decision.get("signal_id") or "")
        overlay = _overlay_of(decision)
        attribution = (
            overlay.get("attribution") if isinstance(overlay.get("attribution"), dict) else {}
        )
        delta = attribution.get("delta") if isinstance(attribution.get("delta"), dict) else {}
        fill = ledger.get(did, {})

        enabled = bool(overlay.get("enabled"))
        coef = overlay.get("coef")
        if enabled:
            coef_counter[f"coef={coef}"] += 1
            for item in overlay.get("degraded") or []:
                degraded_counter[str(item)] += 1
            try:
                delta_conf.append(float(delta.get("confidence") or 0.0))
                delta_pos.append(float(delta.get("position_pct") or 0.0))
            except (TypeError, ValueError):
                pass
            if attribution.get("direction_flip"):
                flips += 1
        if fill.get("order_placed"):
            filled += 1

        rows.append(
            {
                "decision_id": did,
                "ts": decision.get("ts"),
                "symbol": decision.get("symbol"),
                "direction": decision.get("direction"),
                "confidence": decision.get("confidence"),
                "position_pct": decision.get("position_pct"),
                "notional_usdt": decision.get("notional_usdt"),
                "overlay": {
                    "enabled": enabled,
                    "coef": coef,
                    "coef_source": overlay.get("coef_source"),
                    "modulated_paths": overlay.get("modulated_paths"),
                    "modulation_rate": overlay.get("modulation_rate"),
                    "degraded": overlay.get("degraded") or [],
                    "attribution": attribution or None,
                },
                "execution": decision.get("execution"),
                "fill": {
                    "order_placed": bool(fill.get("order_placed")),
                    "order_id": fill.get("order_id"),
                    "fill_px": fill.get("fill_px"),
                    "venue": fill.get("venue"),
                },
            }
        )

    def _mean(values: list[float]) -> float | None:
        return round(sum(values) / len(values), 6) if values else None

    return {
        "source": {
            "outbox": str(outbox),
            "ledger": str(ledger_path),
        },
        "summary": {
            "decisions_total": len(decisions),
            "overlay_enabled": sum(1 for r in rows if r["overlay"]["enabled"]),
            "overlay_disabled": sum(1 for r in rows if not r["overlay"]["enabled"]),
            "coef_distribution": dict(coef_counter),
            "degraded_distribution": dict(degraded_counter),
            "direction_flips": flips,
            "mean_delta_confidence": _mean(delta_conf),
            "mean_delta_position_pct": _mean(delta_pos),
            "filled_orders": filled,
            "pnl_available": False,
            "pnl_gap": "22 台账仅开仓侧；收益归因需平仓回报（fill/close join）后补充",
        },
        "decisions": rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="M4-4 live 归因报告")
    parser.add_argument("--outbox", default=str(DEFAULT_OUTBOX))
    parser.add_argument("--ledger", default=str(DEFAULT_LEDGER))
    parser.add_argument("--out", default="", help="可选：报告落盘路径（JSON）")
    args = parser.parse_args()

    report = build_report(Path(args.outbox), Path(args.ledger))
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.out:
        Path(args.out).write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
