#!/usr/bin/env python3
"""X1 纸面成交记录器（22 执行层 / DEC-BCL-07）。

架构落位（用户 2026-11-13 纠正）：40 是周期/意图/验证场，**执行层是 22**。
因此成交事实（order/fill/pnl）只能由 22 产生，40 的 X0 意图流只是输入。

链路：
  40/execution_trades.jsonl（X0 意图，含 decision_id）
    → TradeExecutionGateway（13 PreTradeGate fail-closed → 16 定容）
    → PaperPriceClient（18 统一价格源纸面撮合，含滑点/手续费）
    → 22-执行引擎中心/audit/x1_paper_fills.jsonl

落盘字段（供 48 D1 证据链严格 join）：
  decision_id / order_id / fill_id / fill_px / exit_px / pnl / status / venue

红线：
  - venue 恒为 paper，只取 18 统一价格源，绝不调用交易所下单接口；
  - 被风控拒绝或取价失败照实记录 status=rejected / no_price，不虚报 fill；
  - 同一 (intent_date, symbol, direction) 只开一次（state 幂等）。
"""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Optional

BASE = Path(__file__).resolve().parent
REPO_ROOT = BASE.parent
_18_DIR = REPO_ROOT / "18-数据获取中心"

if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))

from trade_execution_gateway import FinalDecisionSignal, TradeExecutionGateway  # noqa: E402

DIRECTION_MAP = {"UP": "long", "DOWN": "short", "LONG": "long", "SHORT": "short"}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _load_json(path: Path) -> Dict[str, Any]:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _load_jsonl(path: Path) -> list[Dict[str, Any]]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def _append_jsonl(path: Path, obj: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False, sort_keys=True) + "\n")


def last_price(symbol: str) -> float:
    """18 统一价格源最新日线收盘价（G10：禁止本模块直连交易所）。"""
    if str(_18_DIR) not in sys.path:
        sys.path.insert(0, str(_18_DIR))
    from data_center.market import price_source  # noqa: E402

    result = price_source.fetch_daily(symbol, days=5)
    bars = result.get("bars") or []
    if not bars:
        raise RuntimeError(f"no_bars:{symbol}")
    return float(bars[-1]["close"])


class PaperPriceClient:
    """纸面撮合客户端：用 18 价格源成交，返回 gateway 需要的 order_result 结构。"""

    def __init__(
        self,
        slippage_bps: float = 5.0,
        fee_bps: float = 5.0,
        price_fn: Optional[Callable[[str], float]] = None,
    ) -> None:
        self.slippage_bps = float(slippage_bps)
        self.fee_bps = float(fee_bps)
        self._price_fn = price_fn or last_price
        self._cache: Dict[str, float] = {}

    def price(self, symbol: str) -> float:
        key = str(symbol)
        if key not in self._cache:
            self._cache[key] = float(self._price_fn(key))
        return self._cache[key]

    def place_order(self, **kwargs: Any) -> Dict[str, Any]:
        inst_id = str(kwargs.get("inst_id") or "MULTI")
        side = str(kwargs.get("side") or "buy").lower()
        sz = float(kwargs.get("sz") or 0.0)
        try:
            px_ref = float(kwargs.get("px") or self.price(inst_id))
        except Exception as exc:  # noqa: BLE001 — 取价失败如实返回，不伪造成交
            return {"ok": False, "error": f"no_price:{exc}", "venue": "paper"}
        if sz <= 0 or px_ref <= 0:
            return {"ok": False, "error": "invalid_sz_or_px", "venue": "paper"}

        slip = px_ref * self.slippage_bps / 10000.0
        fill_px = px_ref + slip if side == "buy" else px_ref - slip
        fee = fill_px * sz * self.fee_bps / 10000.0
        return {
            "ok": True,
            "venue": "paper",
            "order_id": f"pap-{uuid.uuid4().hex[:12]}",
            "fill_id": f"fil-{uuid.uuid4().hex[:12]}",
            "avg_px": round(fill_px, 8),
            "px_ref": px_ref,
            "filled_sz": sz,
            "fee": round(fee, 8),
            "side": side,
        }


def _latest_intents(rows: list[Dict[str, Any]]) -> list[Dict[str, Any]]:
    """同一 (symbol, direction) 只保留最新一条意图，避免补跑重复开仓。"""
    latest: Dict[tuple, Dict[str, Any]] = {}
    for row in rows:
        sym = row.get("symbol")
        intent = row.get("intent") or {}
        if not sym or not intent:
            continue
        key = (sym, intent.get("direction"))
        prev = latest.get(key)
        if prev is None or str(row.get("ts") or "") > str(prev.get("ts") or ""):
            latest[key] = row
    return list(latest.values())


def _record_base(row: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "ts": _now_iso(),
        "venue": "paper",
        "decision_id": row.get("decision_id"),
        "decision_ts": row.get("decision_ts"),
        "intent_date": row.get("intent_date"),
        "symbol": row.get("symbol"),
        "source": (row.get("signal_snapshot") or {}).get("source"),
    }


def _open_one(
    gateway: TradeExecutionGateway,
    client: PaperPriceClient,
    row: Dict[str, Any],
    cfg: Dict[str, Any],
) -> Dict[str, Any]:
    rec = _record_base(row)
    intent = row.get("intent") or {}
    direction = DIRECTION_MAP.get(str(intent.get("direction") or "").upper())
    rec["side"] = direction
    rec["action"] = "open"
    if direction is None:
        rec.update(
            status="rejected", reason_code="NEUTRAL_NO_EXECUTION", reason="方向非 long/short"
        )
        return rec

    notional = min(
        float(intent.get("notional_usdt") or cfg["notional_usdt"]), float(cfg["notional_usdt"])
    )
    if str(intent.get("leverage") or "1x") != "1x":
        rec.update(status="rejected", reason_code="LEVERAGE_FORBIDDEN", reason="X1 禁用杠杆")
        return rec
    try:
        px = client.price(str(row.get("symbol")))
    except Exception as exc:  # noqa: BLE001
        rec.update(status="no_price", reason_code="NO_PRICE", reason=str(exc)[:200])
        return rec

    qty = round(notional / px, 10)
    sig = FinalDecisionSignal(
        signal_id=f"x1-open|{row.get('intent_date')}|{row.get('symbol')}",
        source=str(rec.get("source") or "40_main"),
        symbol=str(row.get("symbol")),
        direction=direction,
        decision_id=row.get("decision_id"),
        confidence=float(intent.get("confidence") or 0.0),
        action="open",
        sz=qty,
        reason="x1_paper_entry",
    )
    result = gateway.submit(sig)
    if not result.executed:
        rec.update(
            status="rejected",
            risk_decision="reject",
            reason_code=result.reason_code,
            reason=result.reason,
        )
        return rec

    order = result.order_result or {}
    rec.update(
        status="open",
        risk_decision="allow",
        reason_code=result.reason_code,
        reason=result.reason,
        order_id=order.get("order_id"),
        fill_id=order.get("fill_id"),
        qty=qty,
        notional_usdt=notional,
        fill_px=order.get("avg_px"),
        exit_px=None,
        pnl=None,
        fee=order.get("fee"),
    )
    return rec


def _close_one(
    gateway: TradeExecutionGateway,
    client: PaperPriceClient,
    symbol: str,
    pos: Dict[str, Any],
) -> Dict[str, Any]:
    rec = {
        "ts": _now_iso(),
        "venue": "paper",
        "decision_id": pos.get("decision_id"),
        "decision_ts": pos.get("decision_ts"),
        "intent_date": pos.get("intent_date"),
        "symbol": symbol,
        "source": pos.get("source"),
        "side": pos.get("side"),
        "action": "close",
        "status": "closed",
        "risk_decision": "allow",
        "qty": pos.get("qty"),
        "notional_usdt": pos.get("notional_usdt"),
        "fill_px": pos.get("fill_px"),
        "entry_order_id": pos.get("order_id"),
        "entry_fill_id": pos.get("fill_id"),
    }
    sig = FinalDecisionSignal(
        signal_id=f"x1-close|{date.today().isoformat()}|{symbol}",
        source="x1-paper",
        symbol=symbol,
        direction=str(pos.get("side") or "long"),
        decision_id=pos.get("decision_id"),
        confidence=1.0,
        action="close",
        sz=float(pos.get("qty") or 0.0),
        reason="x1_paper_exit",
    )
    result = gateway.submit(sig)
    if not result.executed:
        rec.update(
            status="close_failed",
            risk_decision="reject",
            reason_code=result.reason_code,
            reason=result.reason,
            exit_px=None,
            pnl=None,
        )
        return rec

    order = result.order_result or {}
    exit_px = order.get("avg_px")
    entry_px = pos.get("fill_px")
    qty = float(pos.get("qty") or 0.0)
    fee_total = float(pos.get("fee") or 0.0) + float(order.get("fee") or 0.0)
    pnl = None
    if exit_px is not None and entry_px is not None:
        sign = 1.0 if str(pos.get("side")) == "long" else -1.0
        pnl = round((float(exit_px) - float(entry_px)) * qty * sign - fee_total, 8)
    rec.update(
        order_id=order.get("order_id"),
        fill_id=order.get("fill_id"),
        exit_px=exit_px,
        pnl=pnl,
        fee=fee_total,
        reason_code=result.reason_code,
        reason=result.reason,
        holding_days=(date.today() - date.fromisoformat(str(pos.get("entry_date")))).days,
    )
    return rec


def run(
    cfg: Dict[str, Any],
    intents_path: Path,
    ledger_path: Path,
    state_path: Path,
    price_fn: Optional[Callable[[str], float]] = None,
    audit_path: Optional[Path] = None,
) -> Dict[str, Any]:
    client = PaperPriceClient(
        slippage_bps=cfg.get("slippage_bps", 5),
        fee_bps=cfg.get("fee_bps", 5),
        price_fn=price_fn,
    )
    gw = TradeExecutionGateway(okx_client=client, audit_path=audit_path)
    holding_days = int(cfg.get("holding_period_days", 7))
    max_positions = int(cfg.get("max_positions", 3))

    state = _load_json(state_path) if state_path.exists() else {}
    positions: Dict[str, Dict[str, Any]] = state.get("positions") or {}
    processed = set(state.get("processed") or [])
    stats = {"opened": 0, "closed": 0, "rejected": 0, "skipped": 0}

    # 1) 先处理到期平仓（持仓周期 target ± tolerance 取 target，纪律优先）
    for symbol in list(positions):
        pos = positions[symbol]
        try:
            entry_date = date.fromisoformat(str(pos.get("entry_date")))
        except ValueError:
            continue
        if (date.today() - entry_date).days < holding_days:
            continue
        rec = _close_one(gw, client, symbol, pos)
        _append_jsonl(ledger_path, rec)
        if rec["status"] == "closed":
            positions.pop(symbol, None)
            stats["closed"] += 1
        else:
            stats["rejected"] += 1

    # 2) 再处理新意图开仓（幂等 + 并发上限）
    for row in sorted(_latest_intents(_load_jsonl(intents_path)), key=lambda r: str(r.get("ts"))):
        symbol = str(row.get("symbol"))
        intent = row.get("intent") or {}
        key = f"{row.get('intent_date')}|{symbol}|{intent.get('direction')}"
        if key in processed or symbol in positions:
            stats["skipped"] += 1
            continue
        if len(positions) >= max_positions:
            stats["skipped"] += 1
            continue
        rec = _open_one(gw, client, row, cfg)
        _append_jsonl(ledger_path, rec)
        processed.add(key)
        if rec["status"] == "open":
            positions[symbol] = {
                "decision_id": rec.get("decision_id"),
                "decision_ts": rec.get("decision_ts"),
                "intent_date": rec.get("intent_date"),
                "source": rec.get("source"),
                "side": rec.get("side"),
                "qty": rec.get("qty"),
                "notional_usdt": rec.get("notional_usdt"),
                "fill_px": rec.get("fill_px"),
                "fee": rec.get("fee"),
                "order_id": rec.get("order_id"),
                "fill_id": rec.get("fill_id"),
                "entry_date": date.today().isoformat(),
            }
            stats["opened"] += 1
        else:
            stats["rejected"] += 1

    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(
        json.dumps(
            {
                "version": "x1-v0.1",
                "updated_at": _now_iso(),
                "positions": positions,
                "processed": sorted(processed),
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return {
        "venue": "paper",
        "intents": str(intents_path),
        "ledger": str(ledger_path),
        "open_positions": len(positions),
        "stats": stats,
    }


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="X1 纸面成交记录（22 执行层）")
    ap.add_argument("--config", default=str(BASE / "x1_paper_config.json"))
    args = ap.parse_args(argv)

    cfg = _load_json(Path(args.config))
    intents = Path(cfg["intent_source"])
    if not intents.is_absolute():
        intents = REPO_ROOT / intents
    ledger = Path(cfg["ledger"])
    if not ledger.is_absolute():
        ledger = REPO_ROOT / ledger
    state = Path(cfg["state"])
    if not state.is_absolute():
        state = REPO_ROOT / state

    if not intents.exists():
        print(
            json.dumps({"ok": True, "skipped": f"no intent stream: {intents}"}, ensure_ascii=False)
        )
        return 0
    print(json.dumps(run(cfg, intents, ledger, state), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
