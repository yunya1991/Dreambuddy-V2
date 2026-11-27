#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""50 shadow 决策调度入口（shadow 接入 crontab）。

读取 42 总线最新快照 → 50 shadow 决策 → 落盘 runtime/shadow/。
shadow 模式只产出审计信号，不执行任何交易。

行为（fail-open）：
- 50_KILL_SWITCH=1：跳过决策，记录 skipped 后正常退出
- 总线无信号：记录 no_evidences 后正常退出
- 决策结果原子写 runtime/shadow/latest.json；摘要追加 shadow_history.jsonl（滚动上限 500）
- 决策追加 runtime/decisions.jsonl（M3-2 账本）与 runtime/audit/decisions.jsonl（审计）
- trigger 防振荡裁决追加 runtime/trigger_flap.jsonl（M4-7）

用法：python3 tools/run_shadow.py [--bus-state PATH] [--out-dir PATH]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[2]
_50_ROOT = _REPO_ROOT / "50-NN主矛盾评估器"
_42_ROOT = _REPO_ROOT / "42-神经网络交易协调层"
if str(_50_ROOT) not in sys.path:
    sys.path.insert(0, str(_50_ROOT))
if str(_42_ROOT) not in sys.path:
    sys.path.insert(0, str(_42_ROOT))

from chain_events import emit_stage, new_trace_id  # noqa: E402

_RUNTIME = _50_ROOT / "runtime"

from adapters.audit_logger import log_decision  # noqa: E402
from adapters.bus_reader import load_evidences  # noqa: E402
from adapters.constraint_loader import load_constraints  # noqa: E402
from adapters.execution_writer import is_kill_switch_on  # noqa: E402
from adapters.factor_priors_provider import is_overlay_enabled, resolve_coef  # noqa: E402
from adapters.prior_reader import load_priors_summary  # noqa: E402
from core.decision import _extract_trigger, record_decision  # noqa: E402
from core.shadow_decision import build_symbol_decisions, make_shadow_decision  # noqa: E402
from core.trigger_flap import check_trigger_flap  # noqa: E402

SHADOW_HISTORY_CAP = 500
DEFAULT_BUS_STATE = _42_ROOT / "runtime" / "bus_state.json"
DEFAULT_OUT_DIR = _50_ROOT / "runtime" / "shadow"


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.chmod(tmp, 0o664)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    _atomic_write_text(path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")


def _append_history(path: Path, record: dict[str, Any], cap: int = SHADOW_HISTORY_CAP) -> None:
    lines: list[str] = []
    if path.exists():
        lines = [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    lines.append(json.dumps(record, ensure_ascii=False))
    _atomic_write_text(path, "\n".join(lines[-cap:]) + "\n")


def run(bus_state: Path, out_dir: Path) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    run_ts = now.isoformat().replace("+00:00", "Z")
    overlay_enabled = is_overlay_enabled()
    coef, coef_source = resolve_coef()
    result: dict[str, Any] = {
        "run_ts": run_ts,
        "status": "ok",
        "reason": None,
        # M4-4：run 级 overlay 开关留档（与 live 对齐，供 exporter 采集开关状态）
        "overlay": {
            "enabled": overlay_enabled,
            "coef": coef if overlay_enabled else 0.0,
            "coef_source": coef_source if overlay_enabled else "disabled",
        },
    }

    if is_kill_switch_on():
        result["status"] = "skipped"
        result["reason"] = "50_KILL_SWITCH=1（kill switch 开启，跳过 shadow 决策）"
        emit_stage(
            "M6",
            "bus_reader.load_evidences",
            "MULTI",
            "skip",
            reason_category="wait_constraint_freeze",
            mode="shadow",
            runtime=_RUNTIME,
            ts=now,
        )
        return result

    evidences = load_evidences(str(bus_state))
    result["evidence_count"] = len(evidences)
    trace = new_trace_id("MULTI", now)
    if not evidences:
        result["status"] = "skipped"
        result["reason"] = "no_evidences（42 总线无信号，fail-open 跳过）"
        emit_stage(
            "M6",
            "bus_reader.load_evidences",
            "MULTI",
            "skip",
            reason_category="wait_evidence_missing",
            trace_id=trace,
            mode="shadow",
            data={"evidence_count": 0},
            runtime=_RUNTIME,
            ts=now,
        )
        return result
    emit_stage(
        "M6",
        "bus_reader.load_evidences",
        "MULTI",
        "pass",
        trace_id=trace,
        mode="shadow",
        data={"evidence_count": len(evidences)},
        runtime=_RUNTIME,
        ts=now,
    )

    constraints = load_constraints()
    decision = make_shadow_decision(evidences, constraints, now=now)
    if isinstance(decision.get("payload"), dict):
        decision["payload"]["trace_id"] = trace

    # M4-7：与主决策入口一致，提取 trigger 并做防振荡裁决（写 runtime/trigger_flap.jsonl）
    proposed_trigger = _extract_trigger(evidences)
    flap = check_trigger_flap(str(decision.get("symbol") or "MULTI"), proposed_trigger, now=now)
    decision["trigger"] = flap.trigger
    payload = decision.get("payload")
    if isinstance(payload, dict):
        payload["proposed_trigger"] = proposed_trigger
        payload["trigger_flap"] = {
            "locked": flap.locked,
            "switches_in_window": flap.switches_in_window,
            "reason": flap.reason,
        }

    # G4：消费 40 域因子/矛盾先验（fail-open，缺失时跳过）
    priors_40 = load_priors_summary()
    if priors_40 is not None:
        payload = decision.get("payload")
        if isinstance(payload, dict):
            payload["priors_40"] = priors_40
    result["decision"] = decision
    # 40 域 decision_id 回写：组合级决策 symbol=MULTI 无法按标的索引，
    # 这里额外产出 per-symbol 决策（同批 path 分组聚合，不新增推断）。
    result["symbol_decisions"] = build_symbol_decisions(evidences, constraints, now=now)
    emit_stage(
        "M11",
        "shadow_decision.make_shadow_decision",
        str(decision.get("symbol") or "MULTI"),
        "pass",
        trace_id=trace,
        decision_id=str(decision.get("decision_id") or ""),
        mode="shadow",
        data={
            "direction": decision.get("direction"),
            "confidence": decision.get("confidence"),
            "symbol_decisions": len(result["symbol_decisions"]),
        },
        runtime=_RUNTIME,
        ts=now,
    )
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="50 shadow 决策调度入口")
    parser.add_argument(
        "--bus-state", default=str(DEFAULT_BUS_STATE), help="42 bus_state.json 路径"
    )
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR), help="shadow 结果输出目录")
    args = parser.parse_args()

    result = run(Path(args.bus_state), Path(args.out_dir))

    out_dir = Path(args.out_dir)
    _atomic_write_json(out_dir / "latest.json", result)

    summary: dict[str, Any] = {
        "run_ts": result["run_ts"],
        "status": result["status"],
        "reason": result.get("reason"),
        "evidence_count": result.get("evidence_count"),
    }
    decision = result.get("decision")
    if isinstance(decision, dict):
        payload = decision.get("payload") if isinstance(decision.get("payload"), dict) else {}
        summary.update(
            {
                "signal_id": decision.get("signal_id"),
                "direction": decision.get("direction"),
                "confidence": decision.get("confidence"),
                "position_pct": payload.get("position_pct"),
            }
        )
    # per-symbol 决策只入决策账本（供 40 域 decision_id 精确映射），不进审计主线
    symbol_decisions = result.get("symbol_decisions") or []
    summary["symbol_decisions"] = len(symbol_decisions)
    _append_history(out_dir / "shadow_history.jsonl", summary)

    if isinstance(decision, dict):
        # 决策账本 + 审计落盘（fail-open：写失败不影响 shadow 主流程）
        try:
            record_decision(decision)
            log_decision(decision)
        except Exception:  # noqa: BLE001
            pass

    for item in symbol_decisions:
        try:
            record_decision(item)
        except Exception:  # noqa: BLE001
            pass

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
