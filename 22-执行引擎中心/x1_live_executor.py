#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""22 执行层 live 执行器：消费 50 live 决策 → 22 风控/审计 → 触发 11 域 bypass 下单。

职责边界（49 SPEC / execution_rights）：
- 22 负责：执行权复核、kill-switch、标的/名义金额/杠杆/持仓数校验、幂等、审计
- 13 负责：事前风控判定 + 真实权益 + 定容（经 risk_bridge，fail-closed）
- 11 负责：持有 OKX 密钥并真实下单（经 live_order_bridge.py，22 不接触密钥）

用法：
  python3 x1_live_executor.py [--outbox PATH] [--dry-run] [--limit N]
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from risk_bridge import precheck  # noqa: E402

_REPO_ROOT = Path(__file__).resolve().parents[1]
_MODULE_DIR = Path(__file__).resolve().parent
_BRIDGE = _REPO_ROOT / "11-易经推理系统" / "scripts" / "memory_l4" / "live_order_bridge.py"
_DEFAULT_OUTBOX = _REPO_ROOT / "50-NN主矛盾评估器" / "runtime" / "live" / "outbox.jsonl"
_LEDGER_DIR = _MODULE_DIR / "audit"
_LEDGER = _LEDGER_DIR / "x1_live_fills.jsonl"
_STATE = _MODULE_DIR / "runtime" / "x1_live_processed.json"

ALLOWED_SYMBOLS = {"BTC-USDT-SWAP"}
MAX_NOTIONAL_USDT = 100.0
MAX_LEVERAGE = 3
DEFAULT_SL_PCT = 1.5
DEFAULT_TP_PCT = 3.0


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _kill_switch_on() -> bool:
    return (
        os.environ.get("22_LIVE_KILL_SWITCH", "0") == "1"
        or os.environ.get("50_KILL_SWITCH", "0") == "1"
    )


def _load_state() -> dict[str, Any]:
    if not _STATE.exists():
        return {"processed": {}}
    try:
        return json.loads(_STATE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"processed": {}}


def _save_state(state: dict[str, Any]) -> None:
    _STATE.parent.mkdir(parents=True, exist_ok=True)
    tmp = _STATE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, _STATE)


def _append_ledger(record: dict[str, Any]) -> None:
    _LEDGER_DIR.mkdir(parents=True, exist_ok=True)
    with open(_LEDGER, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def _read_outbox(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def _check(decision: dict[str, Any]) -> str | None:
    if _kill_switch_on():
        return "kill_switch"
    if decision.get("source") != "50-nn":
        return "source_not_50"
    if decision.get("mode") != "live" or decision.get("shadow") is not False:
        return "not_live_decision"
    if decision.get("direction") not in ("long", "short"):
        return "no_direction"
    execution = decision.get("execution") or {}
    if execution.get("outcome") != "live:50-bypass" or not execution.get("allowed"):
        return "execution_rights_denied"
    if not decision.get("mandate_id"):
        return "mandate_missing"
    symbol = str(decision.get("symbol") or "").upper()
    if symbol not in ALLOWED_SYMBOLS:
        return "symbol_not_allowed"
    try:
        notional = float(
            decision.get("notional_usdt")
            or decision.get("payload", {}).get("notional_usdt")
            or MAX_NOTIONAL_USDT
        )
    except (TypeError, ValueError):
        return "invalid_notional"
    if not (0 < notional <= MAX_NOTIONAL_USDT):
        return "notional_limit"
    return None


def _bridge_call(payload: dict[str, Any], timeout: int = 90) -> dict[str, Any]:
    proc = subprocess.run(
        [sys.executable, str(_BRIDGE)],
        input=json.dumps(payload, ensure_ascii=False),
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if proc.returncode not in (0, 1):
        return {
            "ok": False,
            "error_code": "bridge_process_failed",
            "reason": (proc.stderr or proc.stdout)[-500:],
        }
    try:
        return json.loads(proc.stdout.strip().splitlines()[-1])
    except (json.JSONDecodeError, IndexError):
        return {
            "ok": False,
            "error_code": "bridge_bad_output",
            "reason": (proc.stdout or proc.stderr)[-500:],
        }


def run(outbox: Path, dry_run: bool, limit: int) -> dict[str, Any]:
    decisions = _read_outbox(outbox)
    state = _load_state()
    processed: dict[str, Any] = state.setdefault("processed", {})
    result: dict[str, Any] = {
        "run_ts": _now(),
        "status": "ok",
        "outbox_count": len(decisions),
        "executed": 0,
        "skipped": 0,
        "results": [],
    }

    for decision in decisions[-limit:]:
        decision_id = str(decision.get("decision_id") or decision.get("signal_id") or "")
        if not decision_id:
            continue
        if decision_id in processed:
            result["skipped"] += 1
            continue
        reason = _check(decision)
        if reason:
            processed[decision_id] = {"status": "skipped", "reason": reason, "ts": _now()}
            result["skipped"] += 1
            continue

        # P0-1/2/3：13 事前风控 + 真实权益 + 定容（fail-closed）
        risk = precheck(decision)
        if not risk.get("passed"):
            code = str(risk.get("reason_code") or "RISK_BLOCKED")
            processed[decision_id] = {"status": "risk_blocked", "reason": code, "ts": _now()}
            result["skipped"] += 1
            result.setdefault("risk_rejected", []).append(
                {"decision_id": decision_id, "reason_code": code, "reason": risk.get("reason")}
            )
            continue

        payload = {
            "action": "order",
            "symbol": decision.get("symbol"),
            "direction": decision.get("direction"),
            "notional_usdt": risk.get("notional_usdt") or MAX_NOTIONAL_USDT,
            "leverage": int(risk.get("leverage") or MAX_LEVERAGE),
            "sl_pct": DEFAULT_SL_PCT,
            "tp_pct": DEFAULT_TP_PCT,
            "decision_id": decision_id,
            "reason": f"50 live {decision.get('signal_id')}",
        }
        if dry_run:
            outcome = {"ok": True, "dry_run": True, "payload": payload}
        else:
            outcome = _bridge_call(payload)

        record = {
            "ts": _now(),
            "decision_id": decision_id,
            "symbol": decision.get("symbol"),
            "direction": decision.get("direction"),
            "confidence": decision.get("confidence"),
            "position_pct": decision.get("position_pct"),
            "venue": "okx_live",
            "order_placed": bool(outcome.get("ok") and not outcome.get("dry_run")),
            "order_id": outcome.get("order_id"),
            "fill_px": outcome.get("reference_px"),
            "request": payload,
            "risk": risk,
            "result": outcome,
        }
        _append_ledger(record)
        if not dry_run:
            processed[decision_id] = {
                "status": "executed" if outcome.get("ok") else "failed",
                "ts": _now(),
                "result": outcome,
            }
        result["results"].append(record)
        if outcome.get("ok"):
            result["executed"] += 1
        else:
            result["status"] = "degraded"

    _save_state(state)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="22 live 执行器（触发 11 bypass）")
    parser.add_argument("--outbox", default=str(_DEFAULT_OUTBOX))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit", type=int, default=10)
    args = parser.parse_args()

    result = run(Path(args.outbox), args.dry_run, args.limit)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
