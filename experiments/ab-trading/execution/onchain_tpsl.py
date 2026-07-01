#!/usr/bin/env python3
"""
链上止盈止损模块 On-Chain TP/SL Module
==========================================

系统级统一能力：基于 Hyperliquid 原生 Trigger Order 实现链上止盈止损。

任何 Agent（A / B / 未来的 C/D/E...）都可以直接调用，
不需要各自实现一套。

核心 API：
    ensure_tpsl(client, coin, sl_price, tp_price) -> Dict
        确保某仓位有对应的链上止盈止损（有则更新，无则创建）

    update_tpsl(client, coin, new_sl=None, new_tp=None) -> Dict
        更新止盈止损（智能方向校验，只允许向有利方向移动止损）

    remove_tpsl(client, coin) -> Dict
        移除某仓位的所有链上条件单

    sync_all_tpsl(client, active_positions) -> Dict
        从 memory.active_positions 全量同步到链上（冷启动/恢复用）

    get_position_tpsl_status(client, coin) -> Dict
        查询某仓位当前链上条件单状态

设计原则：
    1. 幂等：重复调用不会出错
    2. 容错：失败不影响主流程，返回错误信息
    3. 向后兼容：不依赖调用方修改，可渐进式接入
    4. 方向安全：止损只允许向有利方向移动（防误操作）
"""
import sys
from pathlib import Path
from typing import Dict, Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from execution.aster_spot import HyperliquidClient


# ── 核心 API ────────────────────────────────────────────────────────────────

def ensure_tpsl(
    client: HyperliquidClient,
    coin: str,
    sl_price: Optional[float] = None,
    tp_price: Optional[float] = None,
    is_market: bool = True,
) -> Dict:
    """
    确保某仓位有对应的链上止盈止损条件单。

    流程：
      1. 查询当前挂单
      2. 如果已有，对比价格：价格相同则跳过，不同则更新
      3. 如果没有，则创建

    返回: {
        "ok": bool,
        "coin": str,
        "action": "created" | "updated" | "skipped" | "error",
        "sl_price": float | None,
        "tp_price": float | None,
        "oids": list,
        "error": str (仅失败时有),
    }
    """
    if sl_price is None and tp_price is None:
        return {"ok": False, "coin": coin, "action": "error", "error": "no_sl_or_tp"}

    try:
        # 1. 获取当前仓位信息
        acct = client.get_account()
        pos = acct["positions"].get(coin)
        if not pos:
            return {"ok": False, "coin": coin, "action": "error", "error": "no_position"}

        is_long = pos["size"] > 0

        # 2. 获取当前链上条件单
        existing = _get_tpsl_orders(client, coin, is_long)
        curr_sl_px = existing["sl_px"]
        curr_tp_px = existing["tp_px"]

        # 3. 判断是否需要操作
        sl_same = (sl_price is None) or (curr_sl_px is not None and abs(curr_sl_px - sl_price) < 0.0001)
        tp_same = (tp_price is None) or (curr_tp_px is not None and abs(curr_tp_px - tp_price) < 0.0001)

        if sl_same and tp_same and (curr_sl_px or curr_tp_px):
            return {
                "ok": True,
                "coin": coin,
                "action": "skipped",
                "sl_price": curr_sl_px,
                "tp_price": curr_tp_px,
                "oids": existing["oids"],
            }

        # 4. 需要设置/更新：先取消所有旧的，再设置新的
        if existing["oids"]:
            client.cancel_all_tpsl(coin)

        final_sl = sl_price if sl_price else curr_sl_px
        final_tp = tp_price if tp_price else curr_tp_px

        result = client.set_tpsl_orders(
            coin,
            stop_loss_price=final_sl,
            take_profit_price=final_tp,
            is_market=is_market,
        )

        if result.get("ok"):
            action = "updated" if (curr_sl_px or curr_tp_px) else "created"
            return {
                "ok": True,
                "coin": coin,
                "action": action,
                "sl_price": final_sl,
                "tp_price": final_tp,
                "oids": result.get("oids", []),
            }
        else:
            return {
                "ok": False,
                "coin": coin,
                "action": "error",
                "error": result.get("error", "unknown"),
            }

    except Exception as e:
        return {"ok": False, "coin": coin, "action": "error", "error": str(e)}


def update_tpsl(
    client: HyperliquidClient,
    coin: str,
    new_sl: Optional[float] = None,
    new_tp: Optional[float] = None,
    is_market: bool = True,
) -> Dict:
    """
    更新止盈止损（带方向安全校验）。

    安全规则：
      - LONG 仓位：止损只能向上移动（保护利润）
      - SHORT 仓位：止损只能向下移动（保护利润）
      - 止盈可以上下调整

    返回格式同 ensure_tpsl。
    """
    try:
        acct = client.get_account()
        pos = acct["positions"].get(coin)
        if not pos:
            return {"ok": False, "coin": coin, "action": "error", "error": "no_position"}

        is_long = pos["size"] > 0
        existing = _get_tpsl_orders(client, coin, is_long)
        curr_sl = existing["sl_px"]
        curr_tp = existing["tp_px"]

        final_sl = curr_sl
        if new_sl is not None and new_sl > 0:
            if curr_sl is None:
                final_sl = new_sl
            elif is_long:
                final_sl = max(curr_sl, new_sl)
            else:
                final_sl = min(curr_sl, new_sl)

        final_tp = new_tp if (new_tp is not None and new_tp > 0) else curr_tp

        sl_unchanged = (final_sl is None and curr_sl is None) or \
                       (final_sl is not None and curr_sl is not None and abs(final_sl - curr_sl) < 0.0001)
        tp_unchanged = (final_tp is None and curr_tp is None) or \
                       (final_tp is not None and curr_tp is not None and abs(final_tp - curr_tp) < 0.0001)

        if sl_unchanged and tp_unchanged and (curr_sl or curr_tp):
            return {
                "ok": True,
                "coin": coin,
                "action": "skipped",
                "sl_price": curr_sl,
                "tp_price": curr_tp,
                "oids": existing["oids"],
            }

        return ensure_tpsl(client, coin, final_sl, final_tp, is_market)

    except Exception as e:
        return {"ok": False, "coin": coin, "action": "error", "error": str(e)}


def remove_tpsl(client: HyperliquidClient, coin: str) -> Dict:
    """
    移除某仓位的所有链上条件单。

    返回: {"ok": bool, "coin": str, "cancelled": int}
    """
    try:
        result = client.cancel_all_tpsl(coin)
        return {
            "ok": result.get("ok", False),
            "coin": coin,
            "cancelled": result.get("cancelled", 0),
        }
    except Exception as e:
        return {"ok": False, "coin": coin, "cancelled": 0, "error": str(e)}


def sync_all_tpsl(
    client: HyperliquidClient,
    active_positions: Dict,
) -> Dict:
    """
    从 memory.active_positions 全量同步到链上。

    用途：冷启动、异常恢复、一致性校验。

    返回: {
        "ok": bool,
        "results": {coin: result_dict, ...},
        "total": int,
        "success": int,
        "failed": int,
    }
    """
    results = {}
    success = 0
    failed = 0

    for coin, pos in active_positions.items():
        sl = pos.get("stop_loss_price")
        tp = pos.get("take_profit_price")
        if sl is None and tp is None:
            continue

        result = ensure_tpsl(client, coin, sl, tp)
        results[coin] = result
        if result.get("ok"):
            success += 1
        else:
            failed += 1

    return {
        "ok": failed == 0,
        "results": results,
        "total": len(results),
        "success": success,
        "failed": failed,
    }


def get_position_tpsl_status(client: HyperliquidClient, coin: str) -> Dict:
    """
    查询某仓位当前链上条件单状态。

    返回: {
        "ok": bool,
        "coin": str,
        "has_position": bool,
        "is_long": bool | None,
        "sl_price": float | None,
        "tp_price": float | None,
        "orders": list,
        "count": int,
    }
    """
    try:
        acct = client.get_account()
        pos = acct["positions"].get(coin)
        if not pos:
            return {"ok": True, "coin": coin, "has_position": False,
                    "is_long": None, "sl_price": None, "tp_price": None,
                    "orders": [], "count": 0}

        is_long = pos["size"] > 0
        info = _get_tpsl_orders(client, coin, is_long)

        return {
            "ok": True,
            "coin": coin,
            "has_position": True,
            "is_long": is_long,
            "sl_price": info["sl_px"],
            "tp_price": info["tp_px"],
            "orders": info["orders"],
            "count": len(info["orders"]),
        }
    except Exception as e:
        return {"ok": False, "coin": coin, "error": str(e)}


# ── 内部工具函数 ────────────────────────────────────────────────────────────

def _get_tpsl_orders(
    client: HyperliquidClient,
    coin: str,
    is_long: bool,
) -> Dict:
    """
    从 openOrders 中筛选出当前仓位的 SL/TP 条件单。

    判断逻辑（基于价格相对当前价的位置）：
      - LONG 仓位：价格低于当前价的是 SL，高于的是 TP
      - SHORT 仓位：价格高于当前价的是 SL，低于的是 TP

    返回: {"sl_px": float|None, "tp_px": float|None, "oids": list, "orders": list}
    """
    orders = client.get_open_orders(coin)
    ro_orders = [o for o in orders if o.get("reduceOnly")]

    if not ro_orders:
        return {"sl_px": None, "tp_px": None, "oids": [], "orders": []}

    try:
        mid_px = client.get_mid_price(coin)
    except Exception:
        mid_px = None

    sl_px = None
    tp_px = None
    oids = []

    for o in ro_orders:
        px = float(o.get("limitPx", 0))
        if px <= 0:
            continue
        oids.append(o["oid"])

        if mid_px:
            if is_long:
                if px < mid_px:
                    sl_px = px if sl_px is None else max(sl_px, px)
                else:
                    tp_px = px if tp_px is None else min(tp_px, px)
            else:
                if px > mid_px:
                    sl_px = px if sl_px is None else min(sl_px, px)
                else:
                    tp_px = px if tp_px is None else max(tp_px, px)
        else:
            if sl_px is None:
                sl_px = px
            elif tp_px is None:
                tp_px = px

    return {"sl_px": sl_px, "tp_px": tp_px, "oids": oids, "orders": ro_orders}
