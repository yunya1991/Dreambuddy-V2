#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""22 执行层 live 执行器：消费 50 live 决策 → 22 风控/审计 → 22 域下单桥真实下单。

职责边界（49 SPEC / execution_rights）：
- 22 负责：执行权复核、kill-switch、标的/名义金额/杠杆/持仓数校验、幂等、审计
- 13 负责：事前风控判定 + 真实权益 + 定容（经 risk_bridge，fail-closed）
- 22 负责：持有 OKX 凭据（加密库）并真实下单（经 executors/live_order_bridge.py）

用法：
  python3 x1_live_executor.py [--outbox PATH] [--dry-run] [--limit N]
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from risk_bridge import precheck  # noqa: E402

_REPO_ROOT = Path(__file__).resolve().parents[1]
_MODULE_DIR = Path(__file__).resolve().parent
_BRIDGE = _MODULE_DIR / "executors" / "live_order_bridge.py"
_DEFAULT_OUTBOX = _REPO_ROOT / "50-NN主矛盾评估器" / "runtime" / "live" / "outbox.jsonl"
_LEDGER_DIR = _MODULE_DIR / "audit"
_LEDGER = _LEDGER_DIR / "x1_live_fills.jsonl"
_STATE = _MODULE_DIR / "runtime" / "x1_live_processed.json"

_SYMBOL_REGISTRY = _MODULE_DIR / "config" / "live_symbols.json"


def _load_registry() -> dict[str, Any]:
    """读取标的注册表；文件缺失/损坏时返回空（调用方 fail-closed）。"""
    try:
        data = json.loads(_SYMBOL_REGISTRY.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


_REGISTRY = _load_registry()
_SYMBOL_CLASS: dict[str, str] = {
    str(v.get("inst_id")).upper(): str(v.get("asset_class") or "")
    for v in (_REGISTRY.get("symbols") or {}).values()
    if v.get("inst_id")
}
ALLOWED_SYMBOLS = set(_SYMBOL_CLASS) or {"BTC-USDT-SWAP"}
MAX_NOTIONAL_USDT = float(_REGISTRY.get("max_notional_default") or 100)
MAX_NOTIONAL_BY_CLASS: dict[str, float] = {
    str(k): float(v) for k, v in (_REGISTRY.get("max_notional_by_class") or {}).items()
}
NOTIONAL_FLOOR_BY_CLASS: dict[str, float] = {
    str(k): float(v) for k, v in (_REGISTRY.get("notional_floor_by_class") or {}).items()
}
MAX_LEVERAGE = 3
DEFAULT_SL_PCT = 1.5
DEFAULT_TP_PCT = 3.0
COOLDOWN_HOURS = float(os.environ.get("22_LIVE_COOLDOWN_HOURS", "8"))


def _class_of(inst_id: str) -> str:
    return _SYMBOL_CLASS.get(str(inst_id).upper(), "")


def _notional_cap(inst_id: str) -> float:
    """类别名义上限：注册表 max_notional_by_class，缺失回落全局上限。"""
    return MAX_NOTIONAL_BY_CLASS.get(_class_of(inst_id), MAX_NOTIONAL_USDT)


def _notional_floor(inst_id: str) -> float:
    """类别名义下限：指数/高价 ETF 73U 定容贴近最小张数，按类别抬到 150U。"""
    return NOTIONAL_FLOOR_BY_CLASS.get(_class_of(inst_id), 0.0)


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
    if not (0 < notional <= _notional_cap(symbol)):
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


def _cooldown_remaining(symbol: str, last_entry: dict[str, Any]) -> float:
    """返回该标的冷静期剩余秒数（0 表示可开仓）。"""
    try:
        last = float(last_entry.get(symbol) or 0)
    except (TypeError, ValueError):
        return 0.0
    if last <= 0:
        return 0.0
    remaining = last + COOLDOWN_HOURS * 3600 - time.time()
    return max(remaining, 0.0)


def _position_guard(decision: dict[str, Any]) -> str | None:
    """真实下单前查 11 持仓：同标的已有仓位则跳过，避免每轮重复开仓。"""
    status = _bridge_call({"action": "status"}, timeout=30)
    if not status.get("ok"):
        return "position_query_failed"
    symbol = str(decision.get("symbol") or "").upper()
    for pos in status.get("positions") or []:
        if str(pos.get("inst_id") or "").upper() != symbol:
            continue
        try:
            size = abs(float(pos.get("pos") or 0))
        except (TypeError, ValueError):
            return "position_query_failed"
        if size > 0:
            return "symbol_already_open"
    return None


def run(outbox: Path, dry_run: bool, limit: int) -> dict[str, Any]:
    decisions = _read_outbox(outbox)
    state = _load_state()
    processed: dict[str, Any] = state.setdefault("processed", {})
    last_entry: dict[str, Any] = state.setdefault("last_entry", {})
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

        # 冷静期：同标的距上次成功开仓不足 COOLDOWN_HOURS 则不再建仓
        symbol = str(decision.get("symbol") or "").upper()
        remain = _cooldown_remaining(symbol, last_entry)
        if remain > 0:
            processed[decision_id] = {
                "status": "cooldown",
                "ts": _now(),
                "remaining_sec": int(remain),
            }
            result["skipped"] += 1
            result.setdefault("cooldown_rejected", []).append(
                {"decision_id": decision_id, "symbol": symbol, "remaining_sec": int(remain)}
            )
            continue

        # P0-1/2/3：13 事前风控 + 真实权益 + 定容（fail-closed）；指数类按类别抬名义下限
        risk = precheck(
            decision,
            notional_cap=_notional_cap(symbol),
            notional_floor=_notional_floor(symbol),
        )
        if not risk.get("passed"):
            code = str(risk.get("reason_code") or "RISK_BLOCKED")
            processed[decision_id] = {"status": "risk_blocked", "reason": code, "ts": _now()}
            result["skipped"] += 1
            result.setdefault("risk_rejected", []).append(
                {"decision_id": decision_id, "reason_code": code, "reason": risk.get("reason")}
            )
            continue

        if not dry_run:
            guard = _position_guard(decision)
            if guard:
                # 查询持仓失败属临时故障：不落幂等，下一轮重试
                if guard != "position_query_failed":
                    processed[decision_id] = {
                        "status": "position_guard",
                        "reason": guard,
                        "ts": _now(),
                    }
                result["skipped"] += 1
                result.setdefault("position_guard_rejected", []).append(
                    {"decision_id": decision_id, "reason": guard}
                )
                continue

        # M4-4：50 侧可声明更小的单笔名义上限（只降不升；仍受 22 的类别/全局硬上限约束）
        notional = float(risk.get("notional_usdt") or MAX_NOTIONAL_USDT)
        declared = decision.get("notional_usdt")
        if declared is None and isinstance(decision.get("payload"), dict):
            declared = decision["payload"].get("notional_usdt")
        try:
            if declared is not None:
                notional = min(notional, float(declared))
        except (TypeError, ValueError):
            pass
        # 指数/高价 ETF：73U 定容贴近最小张数，按类别下限抬回（低于下限时仅此一类放宽）
        floor = _notional_floor(symbol)
        if floor and notional < floor:
            notional = min(floor, _notional_cap(symbol))

        payload = {
            "action": "order",
            "symbol": decision.get("symbol"),
            "direction": decision.get("direction"),
            "notional_usdt": notional,
            "leverage": int(risk.get("leverage") or MAX_LEVERAGE),
            "sl_pct": DEFAULT_SL_PCT,
            "tp_pct": DEFAULT_TP_PCT,
            "decision_id": decision_id,
            "reason": f"50 live {decision.get('signal_id')}",
            # 50 域仓位额度只统计注册表内标的，避免被其他域的持仓挤占
            "position_scope": "registry",
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
            if outcome.get("ok"):
                last_entry[symbol] = time.time()
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
    parser.add_argument("--limit", type=int, default=20)
    args = parser.parse_args()

    result = run(Path(args.outbox), args.dry_run, args.limit)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
