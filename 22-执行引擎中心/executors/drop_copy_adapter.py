"""drop-copy 成交适配器（SPEC-LEDGER-DOMAIN-ATTRIBUTION §5.1-6 / §6.3 A−，P1-7）。

定位：22 账本由两条通道共同喂养——
  - order entry：`TradeExecutionGateway._record_ledger`（11/23/6）；
  - drop copy：本适配器把 50 审计流水与交易所成交按 `exchange_fill_id` 幂等写入。
账本唯一，而非网关唯一；同一笔成交无论被哪条通道先看到，只入账一次。

用法：
  adapter = DropCopyAdapter(ledger)
  adapter.import_jsonl("22-执行引擎中心/audit/x1_live_fills.jsonl", domain="50")
  adapter.import_exchange_fills(okx, "BTC-USDT-SWAP", domain="50")
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

_EPS = 1e-9

# (pos_side, order side) → 账本 action
_ACTION_BY_SIDE = {
    ("long", "buy"): "open",
    ("long", "sell"): "reduce",
    ("short", "sell"): "open",
    ("short", "buy"): "reduce",
}


def infer_action(pos_side: Any, side: Any) -> Optional[str]:
    """由持仓方向 + 买卖方向推断 open/reduce；无法判定返回 None。"""
    return _ACTION_BY_SIDE.get((str(pos_side or "").lower(), str(side or "").lower()))


class DropCopyAdapter:
    """以 exchange_fill_id 为幂等键导入成交（重放安全）。"""

    def __init__(self, ledger: Any) -> None:
        self._ledger = ledger

    def import_fill(self, fill: Dict[str, Any], *, domain: str, source: str) -> Dict[str, Any]:
        efid = str(fill.get("exchange_fill_id") or fill.get("trade_id") or "")
        if not efid:
            return {"ok": False, "reason": "missing_exchange_fill_id"}
        pos_side = str(fill.get("pos_side") or "").lower()
        action = str(fill.get("action") or "").lower() or infer_action(pos_side, fill.get("side"))
        if action not in ("open", "reduce", "close"):
            return {"ok": False, "reason": "unknown_action", "exchange_fill_id": efid}
        qty = float(fill.get("qty") or fill.get("fill_sz") or fill.get("sz") or 0.0)
        px = float(fill.get("px") or fill.get("fill_px") or 0.0)
        if qty <= _EPS or (action == "open" and px <= _EPS):
            return {"ok": False, "reason": "invalid_qty_or_px", "exchange_fill_id": efid}
        if pos_side not in ("long", "short"):
            return {"ok": False, "reason": "invalid_pos_side", "exchange_fill_id": efid}
        out = self._ledger.record_fill(
            inst_id=str(fill.get("inst_id") or fill.get("symbol") or ""),
            pos_side=pos_side,
            action=action,
            qty=qty,
            px=px,
            domain=domain,
            source=source,
            decision_id=str(fill.get("decision_id") or ""),
            exchange_fill_id=efid,
            parent_fill_id=fill.get("parent_fill_id"),
            fee=float(fill.get("fee") or 0.0),
            ratio=1.0 if action == "close" else None,
            exit_reason=str(fill.get("exit_reason") or ""),
            ts=fill.get("ts") if isinstance(fill.get("ts"), str) else None,
        )
        if out.get("duplicate"):
            return {"ok": True, "duplicate": True, "exchange_fill_id": efid}
        return {**out, "exchange_fill_id": efid}

    def import_fills(
        self, fills: Iterable[Dict[str, Any]], *, domain: str, source: str
    ) -> Dict[str, Any]:
        stats = {"imported": 0, "duplicate": 0, "skipped": 0}
        details: List[Dict[str, Any]] = []
        for f in fills or []:
            out = self.import_fill(f, domain=domain, source=source)
            if out.get("duplicate"):
                stats["duplicate"] += 1
            elif out.get("ok"):
                stats["imported"] += 1
            else:
                stats["skipped"] += 1
            details.append(out)
        return {"ok": True, **stats, "details": details}

    def import_jsonl(
        self, path: str | Path, *, domain: str = "50", source: str = "50-dropcopy"
    ) -> Dict[str, Any]:
        """导入 22/audit/x1_live_fills.jsonl。

        该文件为 50 live 执行的审计流水，字段扁平：`symbol/direction/order_id/fill_px/
        request/result`。仅当行内能确定成交数量与幂等键时才入账，其余计 skipped。
        """
        p = Path(path)
        if not p.exists():
            return {"ok": False, "reason": "file_not_found", "path": str(p)}
        records: List[Dict[str, Any]] = []
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            if not rec.get("order_placed") or not str(rec.get("order_id") or ""):
                continue
            req = rec.get("request") if isinstance(rec.get("request"), dict) else {}
            res = rec.get("result") if isinstance(rec.get("result"), dict) else {}
            records.append(
                {
                    "inst_id": rec.get("symbol"),
                    "pos_side": rec.get("direction"),
                    "side": rec.get("side") or req.get("side"),
                    "exchange_fill_id": rec.get("trade_id") or rec.get("order_id"),
                    "qty": res.get("fill_sz") or rec.get("fill_sz") or req.get("sz"),
                    "px": rec.get("fill_px") or res.get("avg_px"),
                    "fee": res.get("fee"),
                    "decision_id": rec.get("decision_id"),
                    "ts": rec.get("ts") if isinstance(rec.get("ts"), str) else None,
                    # x1_live_fills 是 50 入场执行流水；显式 action 优先，缺省按开仓处理
                    "action": rec.get("action") or "open",
                }
            )
        out = self.import_fills(records, domain=domain, source=source)
        out["path"] = str(p)
        return out

    def import_exchange_fills(
        self,
        okx: Any,
        inst_id: str,
        *,
        domain: str,
        source: str = "",
        limit: int = 50,
    ) -> Dict[str, Any]:
        """从交易所成交接口拉取并导入（最可靠的 drop copy 流）。"""
        fn = getattr(okx, "get_recent_fills", None)
        if not callable(fn):
            return {"ok": False, "reason": "okx_get_recent_fills_missing"}
        data = fn(inst_id, limit=limit) or {}
        fills = []
        for f in data.get("fills") or []:
            fills.append(
                {
                    "inst_id": inst_id,
                    "pos_side": f.get("pos_side"),
                    "side": f.get("side"),
                    "exchange_fill_id": f.get("trade_id") or f.get("fill_id"),
                    "qty": f.get("fill_sz"),
                    "px": f.get("fill_px"),
                    "fee": f.get("fee"),
                    "ts": None,
                }
            )
        return self.import_fills(fills, domain=domain, source=source or f"{domain}-dropcopy")


def main(argv: Optional[List[str]] = None) -> int:
    """CLI：把 50 审计流水/交易所成交幂等导入 22 账本。

    用法：
      python -m executors.drop_copy_adapter --jsonl 22-执行引擎中心/audit/x1_live_fills.jsonl
      python -m executors.drop_copy_adapter --okx-inst BTC-USDT-SWAP --okx-inst ETH-USDT-SWAP
    """
    import argparse
    import json
    import os
    import sys

    parser = argparse.ArgumentParser(description="22 账本 drop-copy 导入（P1-7/P2-3）")
    parser.add_argument("--db", default=os.getenv("POSITION_LEDGER_PATH"))
    parser.add_argument("--jsonl", action="append", default=[], help="审计流水 JSONL 路径")
    parser.add_argument("--okx-inst", action="append", default=[], help="从交易所成交导入的标的")
    parser.add_argument("--domain", default="50")
    parser.add_argument("--source", default="")
    args = parser.parse_args(argv)

    here = Path(__file__).resolve().parent.parent
    if str(here) not in sys.path:
        sys.path.insert(0, str(here))
    from position_ledger import PositionLedger  # noqa: PLC0415

    ledger = PositionLedger(args.db)
    adapter = DropCopyAdapter(ledger)
    results = []
    for path in args.jsonl:
        results.append(adapter.import_jsonl(path, domain=args.domain, source=args.source or ""))
    if args.okx_inst:
        lib = here.parent / "14-V15经典马丁策略" / "lib"
        if str(lib) not in sys.path:
            sys.path.insert(0, str(lib))
        from okx_client import OKXSimulatedClient  # noqa: PLC0415

        okx = OKXSimulatedClient()
        for inst in args.okx_inst:
            results.append(
                adapter.import_exchange_fills(
                    okx, inst, domain=args.domain, source=args.source or ""
                )
            )
    print(json.dumps(results, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
