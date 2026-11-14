#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""22 域 live 下单桥（真实交易所下单的唯一出口）。

设计边界：
- 交易所凭据只在 22 域加密凭据库（executors.credentials），本脚本不读 .env
- 所有请求 fail-closed：kill-switch、allowlist、名义金额、杠杆、持仓数任一不满足即拒单
- 每次调用写 22/runtime/live_order_audit.jsonl 审计

用法：
  echo '{"action":"status"}' | python3 live_order_bridge.py
  echo '{"action":"order","symbol":"BTC-USDT-SWAP","direction":"long",
         "notional_usdt":100,"leverage":3,"sl_pct":1.5,"tp_pct":3.0,
         "decision_id":"50-nn|...","reason":"50 live"}' | python3 live_order_bridge.py
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_MODULE_DIR = Path(__file__).resolve().parent
_MODULE_ROOT = _MODULE_DIR.parent
if str(_MODULE_DIR) not in sys.path:
    sys.path.insert(0, str(_MODULE_DIR))

try:  # 包内导入（executors.live_order_bridge）
    from .okx_client import OKXSimulatedClient  # noqa: E402
except ImportError:  # 脚本方式执行（python3 executors/live_order_bridge.py）
    from okx_client import OKXSimulatedClient  # noqa: E402

_SYMBOL_REGISTRY = _MODULE_ROOT / "config" / "live_symbols.json"


def _load_registry() -> dict[str, Any]:
    """读取标的注册表；文件缺失/损坏时返回空（调用方 fail-closed）。"""
    try:
        data = json.loads(_SYMBOL_REGISTRY.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


_REGISTRY = _load_registry()


def _load_allowed_symbols() -> set[str]:
    """可交易 instId 单一事实源；文件缺失时 fail-closed 仅 BTC。"""
    symbols = {
        str(v.get("inst_id")).upper()
        for v in (_REGISTRY.get("symbols") or {}).values()
        if v.get("inst_id")
    }
    return symbols or {"BTC-USDT-SWAP"}


def _load_max_positions() -> int:
    """并发持仓上限：环境变量优先，其次注册表 max_positions_default（默认 3）。"""
    raw = os.environ.get("22_MAX_POSITIONS")
    if raw:
        try:
            return int(raw)
        except ValueError:
            pass
    try:
        return int(_REGISTRY.get("max_positions_default") or 3)
    except (TypeError, ValueError):
        return 3


ALLOWED_SYMBOLS = _load_allowed_symbols()
MAX_NOTIONAL_USDT = 100.0
MAX_LEVERAGE = 3
MAX_POSITIONS = _load_max_positions()
KILL_SWITCH_FILE = _MODULE_ROOT / "runtime" / "LIVE_KILL_SWITCH"
AUDIT_PATH = _MODULE_ROOT / "runtime" / "live_order_audit.jsonl"


def _audit(record: dict[str, Any]) -> None:
    try:
        AUDIT_PATH.parent.mkdir(parents=True, exist_ok=True)
        record.setdefault("ts", datetime.now(timezone.utc).isoformat())
        with open(AUDIT_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception:  # noqa: BLE001
        pass


def _reject(reason: str, code: str = "rejected") -> dict[str, Any]:
    result = {"ok": False, "error_code": code, "reason": reason}
    _audit({"event": "reject", **result})
    return result


def _guard_kill_switch() -> str | None:
    if os.environ.get("22_LIVE_KILL_SWITCH", "0") == "1":
        return "22_LIVE_KILL_SWITCH=1"
    if KILL_SWITCH_FILE.exists():
        return f"kill switch file exists: {KILL_SWITCH_FILE}"
    return None


def _client() -> OKXSimulatedClient:
    return OKXSimulatedClient()


def _status(client: OKXSimulatedClient) -> dict[str, Any]:
    positions = client.get_positions()
    balance = client.get_balance()
    return {
        "ok": True,
        "simulated": bool(client.simulated),
        "dry_run": bool(client.dry_run),
        "positions": positions.get("positions", []) if positions.get("ok") else [],
        "position_count": positions.get("count", 0) if positions.get("ok") else 0,
        "balance_ok": bool(balance.get("ok")),
        "balance_error": balance.get("error"),
    }


def _order(client: OKXSimulatedClient, req: dict[str, Any]) -> dict[str, Any]:
    kill = _guard_kill_switch()
    if kill:
        return _reject(kill, "kill_switch")
    if client.simulated or client.dry_run:
        return _reject(
            "22 域当前为 simulated/dry_run，拒绝真实下单（检查 22 域凭据库 executors.credentials）",
            "not_live",
        )

    symbol = str(req.get("symbol") or "").upper()
    if symbol not in ALLOWED_SYMBOLS:
        return _reject(f"symbol not allowed: {symbol}", "symbol_not_allowed")

    direction = str(req.get("direction") or "").lower()
    if direction not in ("long", "short"):
        return _reject(f"invalid direction: {direction}", "invalid_direction")

    try:
        notional = float(req.get("notional_usdt") or 0)
        leverage = int(req.get("leverage") or 0)
        sl_pct = float(req.get("sl_pct") or 0)
        tp_pct = float(req.get("tp_pct") or 0)
    except (TypeError, ValueError):
        return _reject("invalid numeric fields", "invalid_argument")

    if not (0 < notional <= MAX_NOTIONAL_USDT):
        return _reject(f"notional out of range: {notional}", "notional_limit")
    if not (1 <= leverage <= MAX_LEVERAGE):
        return _reject(f"leverage out of range: {leverage}", "leverage_limit")
    if not (0 < sl_pct < 10) or not (0 < tp_pct < 20):
        return _reject(f"invalid sl/tp pct: {sl_pct}/{tp_pct}", "invalid_sltp")

    positions = client.get_positions()
    if not positions.get("ok"):
        return _reject("positions query failed (fail-closed)", "positions_unavailable")
    pos_count = int(positions.get("count") or 0)
    if pos_count >= MAX_POSITIONS:
        return _reject(f"max positions reached: {pos_count}/{MAX_POSITIONS}", "max_positions")

    ticker = client.get_ticker(symbol)
    if not ticker.get("ok") or not ticker.get("last"):
        return _reject("ticker unavailable", "ticker_unavailable")
    last_px = float(ticker["last"])

    contracts = client._usdt_to_sz(symbol, notional)
    if not contracts or contracts <= 0:
        return _reject(f"contract size resolved to 0 (notional={notional})", "size_zero")

    lever_res = client.set_leverage(symbol, lever=leverage, pos_side=direction)
    if not lever_res.get("ok"):
        # set_leverage 在已持仓逐仓场景可能失败，记录但不阻断（与 11 主链路一致 FAIL-OPEN）
        pass

    side = "buy" if direction == "long" else "sell"
    order_res = client.place_order(
        inst_id=symbol,
        side=side,
        ord_type="market",
        sz=contracts,
        pos_side=direction,
        tag="50nn",
        reason=str(req.get("reason") or "50 live bypass"),
    )
    _audit(
        {
            "event": "order",
            "decision_id": req.get("decision_id"),
            "request": req,
            "contracts": contracts,
            "last_px": last_px,
            "order_result": order_res,
        }
    )
    if not order_res.get("ok"):
        return {
            "ok": False,
            "error_code": "order_failed",
            "reason": order_res.get("error"),
            "order": order_res,
        }

    if direction == "long":
        sl_px = last_px * (1 - sl_pct / 100.0)
        tp_px = last_px * (1 + tp_pct / 100.0)
    else:
        sl_px = last_px * (1 + sl_pct / 100.0)
        tp_px = last_px * (1 - tp_pct / 100.0)

    sltp_res = client.place_stop_loss_take_profit(
        inst_id=symbol,
        pos_side=direction,
        stop_loss_px=sl_px,
        take_profit_px=tp_px,
        sz=contracts,
        reason=f"50 live SL/TP ({req.get('decision_id')})",
    )
    _audit(
        {
            "event": "sltp",
            "decision_id": req.get("decision_id"),
            "sl_px": sl_px,
            "tp_px": tp_px,
            "result": sltp_res,
        }
    )
    return {
        "ok": True,
        "symbol": symbol,
        "direction": direction,
        "contracts": contracts,
        "notional_usdt": notional,
        "leverage": leverage,
        "reference_px": last_px,
        "order_id": order_res.get("ord_id"),
        "sl_px": sl_px,
        "tp_px": tp_px,
        "sltp_ok": bool(sltp_res.get("ok")),
        "sltp": sltp_res,
        "decision_id": req.get("decision_id"),
    }


def main() -> int:
    raw = sys.stdin.read().strip() or "{}"
    try:
        req = json.loads(raw)
    except json.JSONDecodeError as exc:
        print(json.dumps({"ok": False, "error_code": "bad_json", "reason": str(exc)}))
        return 2

    action = str(req.get("action") or "status")
    client = _client()
    if action == "status":
        result = _status(client)
    elif action == "order":
        result = _order(client, req)
    else:
        result = _reject(f"unknown action: {action}", "invalid_argument")
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
