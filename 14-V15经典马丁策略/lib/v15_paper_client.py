#!/usr/bin/env python3
"""
v15_paper_client.py — V15 Paper 执行客户端（Hyperliquid 数据 + 本地账本）
PROP-20260816C 模块2（用户批准 2026-08-16）

职责：在 V15_EXECUTION=paper 时替换 OKXSimulatedClient，为 v15_trader 提供
OKX 接口兼容的 Paper 执行层。行情读 Hyperliquid 真实数据（hl_data_adapter），
订单/持仓/止盈止损记录在本地账本 data/v15_paper_ledger.json。

设计原则（v1 范围，按批准提案）：
- 市价单：立即按 HL 中间价 ± 滑点成交，扣 taker 手续费
- 限价单：价格穿越时模拟成交（马丁加仓网格的核心机制，必须模拟）
- 止盈止损 algo 单：仅记录（v15_trader 自身价格轮询驱动平仓，账本与策略状态机保持一致；
  OCO 在纸面环境的安全网角色 = 记录在案，不自动触发，避免与策略状态机双头平仓）
- 不做资金费率（v2 再加）；slippage 5bps、taker fee 4.5bps（HL 档位近似）

硬安全：本客户端无任何真实下单通道——构造真实 OKX/HL 签名请求的能力为零，
paper 模式下物理不可能误发实盘单。
"""
import fcntl
import json
import os
import time
from datetime import datetime, timezone
from typing import Dict, List, Optional

# ── 常量 ────────────────────────────────────────────────────
SLIPPAGE = 0.0005          # 5 bps 单边滑点
TAKER_FEE = 0.00045        # HL taker ~0.045%
FILL_EPS = 1e-12           # 浮点容差
MAX_FILL_HISTORY = 500     # fills 审计上限

_HERE = os.path.dirname(os.path.abspath(__file__))
_V15_ROOT = os.path.dirname(_HERE)
LEDGER_PATH = os.path.join(_V15_ROOT, "data", "v15_paper_ledger.json")

DEFAULT_LEDGER = {
    "version": 1,
    "created_at": "",
    "updated_at": "",
    "initial_capital_usdt": 260.0,
    "balance_usdt": 260.0,      # 现金 = 初始资金 + 已实现盈亏 - 累计手续费
    "fee_paid_usdt": 0.0,
    "realized_pnl_usdt": 0.0,
    "positions": {},            # coin -> {inst_id,pos_side,pos,avg_px,leverage,opened_at}
    "pending_orders": {},       # ord_id -> {...}
    "algo_orders": {},          # algo_id -> {...}
    "fills": [],                # 成交流水（审计）
    "closed_trades": [],        # 平仓记录
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _coin(inst_id: str) -> str:
    return (inst_id or "").split("-")[0].upper()


class V15PaperClient:
    """OKX 客户端鸭子类型兼容的 Paper 执行客户端"""

    simulated = True
    dry_run = False

    def __init__(self, ledger_path: str = None):
        self.ledger_path = ledger_path or LEDGER_PATH
        self.cfg = {
            "default_inst_id": "BTC-USDT-SWAP",
            "dry_run": False,
            "simulated": True,
        }
        # 行情复用 HL 适配器
        from hl_data_adapter import HLDataAdapter
        self._data = HLDataAdapter()
        self._sz_decimals: Optional[Dict[str, int]] = None

    # ── 账本 IO（原子写 + 文件锁）──────────────────────────

    def _load_ledger(self) -> Dict:
        if not os.path.exists(self.ledger_path):
            led = json.loads(json.dumps(DEFAULT_LEDGER))
            led["created_at"] = _now_iso()
            led["updated_at"] = _now_iso()
            self._save_ledger(led)
            return led
        with open(self.ledger_path, "r") as f:
            fcntl.flock(f, fcntl.LOCK_SH)
            try:
                return json.load(f)
            finally:
                fcntl.flock(f, fcntl.LOCK_UN)

    def _save_ledger(self, led: Dict):
        os.makedirs(os.path.dirname(self.ledger_path), exist_ok=True)
        led["updated_at"] = _now_iso()
        tmp = self.ledger_path + ".tmp"
        with open(tmp, "w") as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            try:
                json.dump(led, f, ensure_ascii=False, indent=1)
            finally:
                fcntl.flock(f, fcntl.LOCK_UN)
        os.replace(tmp, self.ledger_path)

    def _record_fill(self, led: Dict, fill: Dict):
        led["fills"].append(fill)
        if len(led["fills"]) > MAX_FILL_HISTORY:
            led["fills"] = led["fills"][-MAX_FILL_HISTORY:]

    # ── 行情 ──────────────────────────────────────────────

    def get_kline(self, inst_id: str = None, bar: str = "1H",
                  limit: int = 100) -> Dict:
        return self._data.get_kline(inst_id, bar=bar, limit=limit)

    def get_ticker(self, inst_id: str = None) -> Dict:
        return self._data.get_ticker(inst_id)

    def get_instrument(self, inst_id: str = None) -> Dict:
        lot, ct = self._lot_and_ct(inst_id)
        return {"ok": True, "inst_id": inst_id, "lot_sz": lot, "ct_val": ct}

    def _get(self, path: str, params: Optional[Dict] = None,
             auth: bool = True) -> Dict:
        """兼容 v15_trader.get_contract_info 的裸 GET 调用（仅 instruments 端点）"""
        if "instruments" in path:
            inst_id = (params or {}).get("instId", "")
            lot, ct = self._lot_and_ct(inst_id)
            return {"code": "0", "msg": "",
                    "data": [{"instId": inst_id, "lotSz": str(lot),
                              "ctVal": str(ct), "lever": "3"}]}
        return {"code": "1", "msg": f"paper client 不支持该端点: {path}", "data": []}

    def _lot_and_ct(self, inst_id: str):
        """ctVal=1.0（sz 即币数）；lotSz 取 HL szDecimals 对应精度"""
        coin = _coin(inst_id)
        lot = 0.01  # 兜底（与 v15_trader.get_contract_info 异常回退一致）
        try:
            if self._sz_decimals is None:
                aster = self._data._ensure_aster()
                meta = aster.get_meta() or {}
                dec = {}
                for u in meta.get("universe", []):
                    name = u.get("name", "")
                    if name:
                        dec[name] = int(u.get("szDecimals", 2))
                self._sz_decimals = dec
            if coin in self._sz_decimals:
                lot = round(10 ** (-self._sz_decimals[coin]), 12)
        except Exception:
            pass
        return lot, 1.0

    # ── 价格工具 ──────────────────────────────────────────

    def _mid(self, coin: str) -> Optional[float]:
        try:
            aster = self._data._ensure_aster()
            mids = aster.get_all_mids()
            px = mids.get(coin)
            px = float(px) if px is not None else None
            return px if (px and px > 0) else None
        except Exception:
            return None

    def _fill_px(self, mid: float, side: str) -> float:
        """买入向上滑、卖出向下滑（对挂单方不利的保守方向）"""
        return mid * (1 + SLIPPAGE) if side == "buy" else mid * (1 - SLIPPAGE)

    # ── 持仓账本核心 ──────────────────────────────────────

    def _apply_fill_to_position(self, led: Dict, coin: str, inst_id: str,
                                side: str, pos_side: str, sz: float,
                                px: float, reason: str):
        """把一笔成交应用到账本持仓（开仓/加仓/减仓/平仓），返回 realized pnl"""
        pos = led["positions"].get(coin)
        notional = sz * px
        fee = notional * TAKER_FEE
        led["fee_paid_usdt"] = led.get("fee_paid_usdt", 0.0) + fee
        led["balance_usdt"] = led.get("balance_usdt", 0.0) - fee

        realized = 0.0
        opening = (side == "buy" and pos_side == "long") or \
                  (side == "sell" and pos_side == "short")

        if opening:
            if pos and pos.get("pos_side") == pos_side and pos.get("pos", 0) > 0:
                # 同向加仓：加权均价
                old_sz, old_px = pos["pos"], pos["avg_px"]
                new_sz = old_sz + sz
                pos["avg_px"] = (old_sz * old_px + sz * px) / new_sz
                pos["pos"] = new_sz
            else:
                if pos and pos.get("pos", 0) > FILL_EPS:
                    # 存在反向持仓：先平反向（V15 hedge 模式下理论不发生，防御性处理）
                    realized += self._close_position(led, coin, pos["pos"], px,
                                                     f"reverse_fill:{reason}")
                led["positions"][coin] = {
                    "inst_id": inst_id, "pos_side": pos_side,
                    "pos": sz, "avg_px": px, "leverage": 3,
                    "opened_at": _now_iso(),
                }
        else:
            # 减仓/平仓方向
            if pos and pos.get("pos_side") == pos_side and pos.get("pos", 0) > FILL_EPS:
                realized += self._close_position(led, coin, min(sz, pos["pos"]), px, reason)
            else:
                # 无持仓可减：记为异常开仓的反向裸单（不应发生）
                self._record_fill(led, {
                    "ts": _now_iso(), "coin": coin, "side": side,
                    "pos_side": pos_side, "sz": sz, "px": px,
                    "reason": f"orphan_fill:{reason}", "warning": True,
                })
                return realized

        self._record_fill(led, {
            "ts": _now_iso(), "coin": coin, "inst_id": inst_id,
            "side": side, "pos_side": pos_side, "sz": sz, "px": round(px, 8),
            "fee": round(fee, 6), "realized_pnl": round(realized, 6),
            "reason": reason,
        })
        if abs(realized) > FILL_EPS:
            led["realized_pnl_usdt"] = led.get("realized_pnl_usdt", 0.0) + realized
            led["balance_usdt"] = led.get("balance_usdt", 0.0) + realized
        return realized

    def _close_position(self, led: Dict, coin: str, sz_close: float,
                        px: float, reason: str) -> float:
        """内部平仓（不减手续费，手续费由调用方统一计）"""
        pos = led["positions"].get(coin)
        if not pos:
            return 0.0
        direction = 1.0 if pos.get("pos_side") == "long" else -1.0
        pnl = (px - pos["avg_px"]) * sz_close * direction
        pos["pos"] = pos.get("pos", 0) - sz_close
        led.setdefault("closed_trades", []).append({
            "ts": _now_iso(), "coin": coin, "pos_side": pos.get("pos_side"),
            "sz": sz_close, "entry_px": pos["avg_px"], "exit_px": round(px, 8),
            "pnl": round(pnl, 6), "reason": reason,
        })
        if pos["pos"] <= FILL_EPS:
            del led["positions"][coin]
        return pnl

    def _check_limit_fills(self, led: Dict) -> bool:
        """限价单穿越成交检查（马丁加仓网格核心机制）"""
        changed = False
        if not led.get("pending_orders"):
            return False
        coins = {_coin(o.get("inst_id", "")) for o in led["pending_orders"].values()
                 if o.get("state") == "live"}
        mids = {}
        for c in coins:
            if c:
                mids[c] = self._mid(c)
        for oid, o in list(led["pending_orders"].items()):
            if o.get("state") != "live":
                continue
            coin = _coin(o.get("inst_id", ""))
            mid = mids.get(coin)
            if not mid:
                continue
            px = float(o.get("px", 0))
            side = o.get("side")
            filled = (side == "buy" and mid <= px) or (side == "sell" and mid >= px)
            if not filled:
                continue
            # 限价单按限价成交（不叠加滑点：挂单是 maker）
            self._apply_fill_to_position(
                led, coin, o.get("inst_id", ""), side,
                o.get("pos_side", "net"), float(o.get("sz", 0)), px,
                f"limit_fill:{o.get('tag', '')}:{o.get('reason', '')}")
            o["state"] = "filled"
            o["avg_px"] = px
            o["filled_sz"] = float(o.get("sz", 0))
            o["fill_ts"] = _now_iso()
            changed = True
        return changed

    # ── OKX 兼容接口：账户 ────────────────────────────────

    def get_balance(self) -> Dict:
        led = self._load_ledger()
        return {"ok": True, "balance": led.get("balance_usdt", 0.0),
                "initial_capital": led.get("initial_capital_usdt", 0.0),
                "realized_pnl": led.get("realized_pnl_usdt", 0.0),
                "fee_paid": led.get("fee_paid_usdt", 0.0)}

    def get_all_positions(self) -> Dict:
        led = self._load_ledger()
        if self._check_limit_fills(led):
            self._save_ledger(led)
        positions_by_coin = {}
        for coin, pos in led.get("positions", {}).items():
            mid = self._mid(coin) or pos.get("avg_px", 0.0)
            direction = 1.0 if pos.get("pos_side") == "long" else -1.0
            upl = (mid - pos.get("avg_px", 0.0)) * pos.get("pos", 0.0) * direction
            notional = mid * pos.get("pos", 0.0)
            positions_by_coin[coin] = {
                "inst_id": pos.get("inst_id", f"{coin}-USDT-SWAP"),
                "pos_side": pos.get("pos_side", "net"),
                "side": "long" if direction > 0 else "short",
                "pos": pos.get("pos", 0.0),
                "avg_px": pos.get("avg_px", 0.0),
                "upl": round(upl, 6),
                "upl_ratio": round(upl / notional, 6) if notional else 0.0,
                "lever": str(pos.get("leverage", 3)),
                "liq_px": 0.0,
                "mark_px": mid,
            }
        return {"ok": True, "positions": positions_by_coin,
                "count": len(positions_by_coin)}

    def get_positions(self, inst_id: str = None) -> Dict:
        all_r = self.get_all_positions()
        if not all_r.get("ok"):
            return all_r
        coin = _coin(inst_id) if inst_id else None
        plist = []
        for c, p in all_r.get("positions", {}).items():
            if coin and c != coin:
                continue
            plist.append({
                "inst_id": p["inst_id"], "pos_side": p["pos_side"],
                "side": p["side"], "pos": p["pos"], "avg_px": p["avg_px"],
                "upl": p["upl"], "mark_px": p["mark_px"],
            })
        return {"ok": True, "positions": plist, "count": len(plist)}

    # ── OKX 兼容接口：下单 ────────────────────────────────

    def place_order(self, inst_id: str, side: str, ord_type: str = "market",
                    sz: float = None, px: float = None,
                    td_mode: str = "isolated", pos_side: str = "net",
                    tag: str = "v15paper", reason: str = "") -> Dict:
        if not inst_id or sz is None or float(sz) <= 0:
            return {"ok": False, "error": f"参数非法: inst_id={inst_id} sz={sz}"}
        coin = _coin(inst_id)
        led = self._load_ledger()
        # 先结算已有穿越成交，保持账本时序
        self._check_limit_fills(led)

        if ord_type == "market":
            mid = self._mid(coin)
            if not mid:
                self._save_ledger(led)
                return {"ok": False, "error": f"无法获取 {coin} HL 中间价"}
            fill = self._fill_px(mid, side)
            self._apply_fill_to_position(led, coin, inst_id, side, pos_side,
                                         float(sz), fill, reason or "market_order")
            self._save_ledger(led)
            return {
                "ok": True, "dry_run": False, "simulated": True, "paper": True,
                "ord_id": f"paper_mkt_{int(time.time()*1000)}",
                "inst_id": inst_id, "side": side, "pos_side": pos_side,
                "sz": float(sz), "avg_px": round(fill, 8),
                "estimated_price": round(fill, 8), "reason": reason,
                "data": {"paper": True, "fill_px": round(fill, 8)},
            }

        # 限价单：入账本等待穿越
        oid = f"paper_lmt_{int(time.time()*1000)}"
        led["pending_orders"][oid] = {
            "ord_id": oid, "inst_id": inst_id, "coin": coin,
            "side": side, "pos_side": pos_side, "ord_type": "limit",
            "sz": float(sz), "px": float(px or 0), "tag": tag,
            "reason": reason, "state": "live", "created_at": _now_iso(),
        }
        # 挂单瞬间若已穿越（如挂单价优于现价），立即成交
        self._check_limit_fills(led)
        self._save_ledger(led)
        st = led["pending_orders"].get(oid, {}).get("state", "live")
        return {
            "ok": True, "dry_run": False, "simulated": True, "paper": True,
            "ord_id": oid, "inst_id": inst_id, "side": side,
            "pos_side": pos_side, "sz": float(sz), "px": float(px or 0),
            "state": st, "reason": reason,
        }

    def place_stop_loss_take_profit(self, inst_id: str = None,
                                    pos_side: str = "long",
                                    stop_loss_px: float = 0,
                                    take_profit_px: float = 0,
                                    sz: float = None, reason: str = "") -> Dict:
        inst_id = inst_id or self.cfg["default_inst_id"]
        if not stop_loss_px and not take_profit_px:
            return {"ok": False, "error": "需指定止损价或止盈价"}
        led = self._load_ledger()
        coin = _coin(inst_id)
        if sz is None:
            pos = led.get("positions", {}).get(coin)
            if not pos or pos.get("pos_side") != pos_side or pos.get("pos", 0) <= 0:
                return {"ok": False, "error": f"无 {pos_side} 持仓可设置止盈止损"}
            sz = pos["pos"]
        aid = f"paper_algo_{int(time.time()*1000)}"
        ord_type = "oco" if (stop_loss_px and take_profit_px) else "conditional"
        led["algo_orders"][aid] = {
            "algo_id": aid, "inst_id": inst_id, "coin": coin,
            "pos_side": pos_side, "ord_type": ord_type,
            "sl_trigger_px": float(stop_loss_px or 0),
            "tp_trigger_px": float(take_profit_px or 0),
            "sz": float(sz), "state": "live",
            "created_at": _now_iso(), "reason": reason,
        }
        self._save_ledger(led)
        result = {"ok": True, "dry_run": False, "paper": True, "type": ord_type,
                  "stop_loss_px": float(stop_loss_px or 0),
                  "take_profit_px": float(take_profit_px or 0),
                  "sz": float(sz),
                  "side": "sell" if pos_side == "long" else "buy",
                  "algo_id": aid}
        return {"orders": [result], "stop_loss": result, "take_profit": result,
                "ok": True, "reason": reason or "v15_paper_sltp"}

    # ── OKX 兼容接口：查询/撤单 ──────────────────────────

    def get_algo_orders(self, inst_id: str = None) -> Dict:
        led = self._load_ledger()
        coin = _coin(inst_id) if inst_id else None
        orders = []
        for a in led.get("algo_orders", {}).values():
            if a.get("state") != "live":
                continue
            if coin and a.get("coin") != coin:
                continue
            orders.append({
                "algo_id": a.get("algo_id"), "ord_type": a.get("ord_type"),
                "side": "sell" if a.get("pos_side") == "long" else "buy",
                "pos_side": a.get("pos_side"), "sz": a.get("sz", 0),
                "trigger_px": 0, "sl_trigger_px": a.get("sl_trigger_px", 0),
                "tp_trigger_px": a.get("tp_trigger_px", 0),
                "order_px": None, "state": "live", "actual_px": 0,
                "tag": "v15paper",
            })
        return {"ok": True, "orders": orders, "count": len(orders)}

    def cancel_algo_orders(self, inst_id: str = None) -> Dict:
        led = self._load_ledger()
        coin = _coin(inst_id) if inst_id else None
        cancelled = 0
        for aid, a in led.get("algo_orders", {}).items():
            if a.get("state") != "live":
                continue
            if coin and a.get("coin") != coin:
                continue
            a["state"] = "cancelled"
            a["cancel_ts"] = _now_iso()
            cancelled += 1
        self._save_ledger(led)
        return {"ok": True, "cancelled": cancelled,
                "msg": "paper algo orders cancelled"}

    def get_pending_orders(self, inst_id: str = None) -> Dict:
        led = self._load_ledger()
        if self._check_limit_fills(led):
            self._save_ledger(led)
        coin = _coin(inst_id) if inst_id else None
        orders = []
        for o in led.get("pending_orders", {}).values():
            if o.get("state") != "live":
                continue
            if coin and o.get("coin") != coin:
                continue
            orders.append({
                "ord_id": o.get("ord_id"), "side": o.get("side"),
                "pos_side": o.get("pos_side"), "ord_type": o.get("ord_type"),
                "sz": float(o.get("sz", 0)), "px": float(o.get("px", 0)),
                "state": "live", "tag": o.get("tag", ""),
            })
        return {"ok": True, "orders": orders, "count": len(orders)}

    def get_order(self, inst_id: str, ord_id: str) -> Dict:
        led = self._load_ledger()
        if self._check_limit_fills(led):
            self._save_ledger(led)
        o = led.get("pending_orders", {}).get(ord_id)
        if not o:
            return {"ok": False, "error": f"paper 订单不存在: {ord_id}"}
        state_map = {"live": "live", "filled": "filled",
                     "cancelled": "canceled", "canceled": "canceled"}
        return {
            "ok": True, "ord_id": ord_id,
            "state": state_map.get(o.get("state"), o.get("state")),
            "side": o.get("side"), "pos_side": o.get("pos_side"),
            "filled_sz": float(o.get("filled_sz", 0)),
            "avg_px": float(o.get("avg_px", 0)),
            "fee": 0.0, "pnl": 0.0,
        }

    def cancel_order(self, inst_id: str, ord_id: str) -> Dict:
        led = self._load_ledger()
        o = led.get("pending_orders", {}).get(ord_id)
        if not o:
            return {"ok": False, "error": f"paper 订单不存在: {ord_id}"}
        if o.get("state") != "live":
            return {"ok": False, "error": f"订单状态不可撤: {o.get('state')}"}
        o["state"] = "cancelled"
        o["cancel_ts"] = _now_iso()
        self._save_ledger(led)
        return {"ok": True, "ord_id": ord_id}
