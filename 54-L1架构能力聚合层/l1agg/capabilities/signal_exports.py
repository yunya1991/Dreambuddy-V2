# -*- coding: utf-8 -*-
"""S6 信号只读出口 D-K03（SPEC-20261116 §5.7 / T6-3）。

只读 `relationship_eval` 的门禁通过行 → `signal.synthesize_signals` → `apply_gating`。
纪律：
  - 只出 signal / gating / blocked / ablation，**不含 order/position/仓位/买卖指令**；
  - 不写库、不下单、不调用 LLM；
  - 注册表缺失或上下文缺失一律 FAIL-OPEN/FAIL-CLOSED 到可解释状态。
"""

from __future__ import annotations

import os
import sqlite3
from typing import Any, Dict, List, Mapping, Optional

from ..signal import apply_gating, synthesize_signals
from .envelope import STATUS_GOOD, STATUS_PARTIAL, build, quality, unavailable
from .eval_exports import REGISTRY_FILE, _readonly_connect

CAPABILITY_SIGNAL = "D-K03"
INTENT_SIGNAL = "signal_query"
DEFAULT_TOP_PER_HORIZON = 3

_SIGNAL_SQL = """
SELECT eval_id, method, transform, target, horizon, n, n_eff, rank_ic,
       excess_hit, base_rate, hit_rate_lb, effect_bps, cost_bps, p_adj,
       status, eval_at, data_version
  FROM relationship_eval
 WHERE gate_pass = 1 AND status IN ('stable', 'candidate')
 ORDER BY target, horizon, ABS(rank_ic) DESC, n DESC
"""


def _top_per_horizon(rows: List[Dict[str, Any]], top: int) -> List[Dict[str, Any]]:
    buckets: Dict[tuple, List[Dict[str, Any]]] = {}
    for row in rows:
        key = (str(row.get("target") or ""), int(row.get("horizon") or 0))
        buckets.setdefault(key, []).append(row)
    picked: List[Dict[str, Any]] = []
    for key in sorted(buckets):
        picked.extend(buckets[key][: max(1, int(top))])
    return picked


def signal_query(
    *,
    db_path: Optional[str] = None,
    target: Optional[str] = None,
    as_of: str = "",
    context: Optional[Mapping[str, Mapping[str, Any]]] = None,
    gate: bool = True,
    thresholds: Optional[Mapping[str, float]] = None,
    limits: Optional[Mapping[str, float]] = None,
    top: int = DEFAULT_TOP_PER_HORIZON,
    capability_id: str = CAPABILITY_SIGNAL,
    intent: str = INTENT_SIGNAL,
    trace_id: Optional[str] = None,
) -> Dict[str, Any]:
    path = db_path or REGISTRY_FILE
    if not os.path.isfile(path):
        return unavailable(
            capability=capability_id,
            intent=intent,
            reason="关系评估注册表尚未生成",
            sources=["registry.relationship_eval"],
            trace_id=trace_id,
        )
    try:
        with _readonly_connect(path) as conn:
            rows = [dict(row) for row in conn.execute(_SIGNAL_SQL)]
    except sqlite3.Error as exc:
        return unavailable(
            capability=capability_id,
            intent=intent,
            reason=f"关系评估注册表不可读（{type(exc).__name__}）",
            sources=["registry.relationship_eval"],
            trace_id=trace_id,
        )

    if target and str(target).strip():
        rows = [row for row in rows if str(row.get("target")) == str(target)]
    picked = _top_per_horizon(rows, top)
    base = synthesize_signals(picked, as_of=as_of, thresholds=thresholds)

    if gate:
        gated = apply_gating(base, context or {}, limits=limits)
        signals = gated["allowed"]
        blocked = gated["blocked"]
        ablation = gated["ablation"]
        caps = gated["limits"]
    else:
        signals = base["signals"]
        blocked = []
        ablation = {
            "no_gate": {
                "signals": len(signals),
                "targets": sorted({str(s.get("target")) for s in signals}),
            },
            "with_gate": {
                "signals": len(signals),
                "targets": sorted({str(s.get("target")) for s in signals}),
            },
            "delta": 0,
            "by_reason": {},
        }
        caps = None

    sample_n = max((int(row.get("n") or 0) for row in picked), default=0)
    if signals:
        head = signals[0]
        answer = (
            f"本期 {len(base['signals'])} 个基信号，门控后 {len(signals)} 个可用"
            f"（blocked {len(blocked)}）；首个为 {head['target']} h{head['horizon']} "
            f"{'偏多' if head['direction'] > 0 else '偏空'}（{head['strength']}）。"
            "仅为历史统计信号，不含下单指令。"
        )
        status = STATUS_GOOD
        degraded = None
    else:
        reasons = sorted({reason for item in blocked for reason in item["gating"]["reasons"]})
        answer = (
            f"本期 {len(base['signals'])} 个基信号均未通过门控（blocked {len(blocked)}："
            f"{'、'.join(reasons) or '无基信号'}）；样本不足或信号被门控降级，不做方向推断。"
        )
        status = STATUS_PARTIAL
        degraded = "no_signal"

    return build(
        capability=capability_id,
        intent=intent,
        answer=answer,
        data={
            "params": {
                "target": target or "",
                "as_of": as_of,
                "gate": bool(gate),
                "top_per_horizon": int(top),
            },
            "signals": signals,
            "blocked": blocked,
            "conflicts": base["conflicts"],
            "ablation": ablation,
            "limits": caps,
            "thresholds": base["thresholds"],
            "signal_count": len(signals),
            "blocked_count": len(blocked),
            "conflict_count": base["conflict_count"],
            "skipped": base["skipped"],
            "schema_version": base["schema_version"],
        },
        quality_block=quality(
            status=status,
            sample_n=sample_n,
            degraded_reason=degraded,
            sources=["registry.relationship_eval"],
            align_method="rank_ic_on_aligned_pairs",
            timezone="UTC",
        ),
        trace_id=trace_id,
    )
