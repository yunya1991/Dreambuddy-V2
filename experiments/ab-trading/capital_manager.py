#!/usr/bin/env python3
"""
资金管理计算器 - 马丁策略专用（贝叶斯优化版）

核心策略：底仓现货思维 + 黑天鹅加仓 + 三屏趋势过滤
- 底仓22%资金 + 5倍杠杆 ≈ 110%现货敞口（平时略占优，有止盈机制）
- 加仓间距保持不变（8%基准），用于黑天鹅时拉低成本
- 止盈固定4%（BTC基准，其他币种按波动率放大）
- 趋势过滤：周线+日线双周期都看空时禁止做多马丁

三大维度参数来源：
1. 波动率维度：止盈/加仓间距按币种波动率动态调整（BTC基准）
2. 趋势过滤维度：周线+日线MA104双周期趋势一致性检查
3. 资金管理维度：底仓22%/杠杆5x/加仓分配由贝叶斯优化确定

计算逻辑：
1. 单仓位完整资金需求 = 底仓 + 3次加仓
2. 底仓 = BASE_POSITION_PCT * TOTAL_BUDGET
3. 加仓1 = ADDON1_PCT * TOTAL_BUDGET
4. 加仓2 = ADDON2_PCT * TOTAL_BUDGET
5. 加仓3 = ADDON3_PCT * TOTAL_BUDGET
6. 单仓位总需求 = 底仓 + 加仓1 + 加仓2 + 加仓3

可用资金 >= 单仓位总需求 * 2 时，允许开新单
可用资金 < 单仓位总需求 时，禁止开新单
"""
import json, os, sys
from datetime import datetime, timezone
from pathlib import Path

try:
    from config_loader import load_config, get_config, get_config_float, get_config_int, get_config_list
    load_config("v15ct")
except Exception:
    pass

BASE_DIR = Path(__file__).parent

# ── 贝叶斯优化后的参数（底仓现货思维 + 黑天鹅加仓）──
TOTAL_BUDGET = get_config_float("TOTAL_BUDGET", 100)
MAX_CONCURRENT_POSITIONS = get_config_int("MAX_CONCURRENT_POSITIONS", 6)
MAX_ADDONS_PER_POSITION = get_config_int("MAX_ADDONS_PER_POSITION", 3)
ADDON_PCT = get_config_float("ADDON_PCT", 0.08)  # 加仓间距（保持不变）

# 底仓22% + 杠杆5x（现货思维）
BASE_POSITION_PCT = get_config_float("BASE_POSITION_PCT", 0.22)
LEVERAGE = get_config_float("LEVERAGE", 5.0)

# 加仓资金分配（贝叶斯优化结果）
ADDON1_PCT = get_config_float("ADDON1_PCT", 0.20)  # 加仓1：20%（黑天鹅第一档，最可能触发）
ADDON2_PCT = get_config_float("ADDON2_PCT", 0.05)  # 加仓2：5%
ADDON3_PCT = get_config_float("ADDON3_PCT", 0.10)  # 加仓3：10%

MAX_POSITION_PCT = get_config_float("MAX_POSITION_PCT", 0.60)
MIN_MARGIN_USD = get_config_float("MIN_MARGIN_USD", 20)

V15CT_COINS = get_config_list("V15CT_COINS", default=["BTC", "ETH", "SOL", "ARB", "OP", "UNI", "HYPE", "OKB"])


def _get_okx_client():
    root_path = Path(__file__).resolve().parent.parent.parent
    yijing_path = root_path / "11-易经推理系统" / "scripts" / "memory_l4"
    sys.path.insert(0, str(yijing_path))
    try:
        from okx_simulated import OKXSimulatedClient
        config = {
            "api_key": get_config("OKX_API_KEY", ""),
            "secret_key": get_config("OKX_SECRET_KEY", ""),
            "passphrase": get_config("OKX_PASSPHRASE", ""),
            "simulated": False,
            "dry_run": False,
            "base_url": "https://www.okx.com",
            "default_inst_id": "BTC-USDT-SWAP",
            "default_usdt_amount": 100,
            "default_leverage": 10,
        }
        client = OKXSimulatedClient(config=config)
        return client
    except Exception:
        return None


def get_account_balance():
    client = _get_okx_client()
    if not client:
        return {
            "ok": False,
            "error": "无法连接OKX客户端",
            "total_eq": TOTAL_BUDGET,
            "avail_balance": TOTAL_BUDGET,
            "used_margin": 0,
        }
    
    try:
        bal = client.get_balance()
        if not bal.get("ok"):
            return {
                "ok": False,
                "error": bal.get("error", "获取余额失败"),
                "total_eq": TOTAL_BUDGET,
                "avail_balance": TOTAL_BUDGET,
                "used_margin": 0,
            }
        
        total_eq = float(bal.get("total_eq", TOTAL_BUDGET))
        assets = bal.get("assets", {})
        usdt = assets.get("USDT", {})
        avail_balance = float(usdt.get("avail", total_eq))
        frozen = float(usdt.get("frozen", 0))
        used_margin = frozen
        
        return {
            "ok": True,
            "total_eq": round(total_eq, 2),
            "avail_balance": round(avail_balance, 2),
            "used_margin": round(used_margin, 2),
        }
    except Exception as e:
        return {
            "ok": False,
            "error": str(e),
            "total_eq": TOTAL_BUDGET,
            "avail_balance": TOTAL_BUDGET,
            "used_margin": 0,
        }


def get_current_positions():
    client = _get_okx_client()
    positions = []
    
    if not client:
        return positions
    
    try:
        for symbol in V15CT_COINS:
            inst_id = f"{symbol}-USDT-SWAP"
            r = client.get_positions(inst_id)
            if r.get("ok"):
                pos_data = r.get("positions", r.get("data", []))
                for p in pos_data:
                    pos_sz = float(p.get("pos", p.get("pos_sz", 0)))
                    if pos_sz != 0:
                        pos_side = p.get("pos_side", "net")
                        is_long = pos_side == "long" or (pos_side == "net" and pos_sz > 0)
                        positions.append({
                            "symbol": symbol,
                            "inst_id": inst_id,
                            "direction": "LONG" if is_long else "SHORT",
                            "pos_side": pos_side,
                            "pos_sz": abs(pos_sz),
                            "entry_price": float(p.get("avg_px", p.get("avg_entry_px", 0))),
                            "mark_price": float(p.get("mark_px", 0)),
                            "margin": float(p.get("margin", 0)),
                            "unrealized_pnl": float(p.get("upl", p.get("unrealized_pnl", 0))),
                            "upl_ratio": float(p.get("upl_ratio", 0)),
                            "lever": p.get("lever", ""),
                        })
    except Exception:
        pass
    
    return positions


def calculate_single_position_cost():
    """计算单个仓位完整资金需求（底仓+所有加仓）
    
    贝叶斯优化后的资金分配：
    - 底仓 = BASE_POSITION_PCT(22%) * TOTAL_BUDGET
    - 加仓1 = ADDON1_PCT(20%) * TOTAL_BUDGET  ← 黑天鹅第一档
    - 加仓2 = ADDON2_PCT(5%) * TOTAL_BUDGET
    - 加仓3 = ADDON3_PCT(10%) * TOTAL_BUDGET
    """
    base_usd = TOTAL_BUDGET * BASE_POSITION_PCT
    
    addon1_usd = TOTAL_BUDGET * ADDON1_PCT
    addon2_usd = TOTAL_BUDGET * ADDON2_PCT
    addon3_usd = TOTAL_BUDGET * ADDON3_PCT
    addon_total = addon1_usd + addon2_usd + addon3_usd
    
    total_cost = base_usd + addon_total
    return {
        "base_usd": round(base_usd, 2),
        "addon_total_usd": round(addon_total, 2),
        "total_cost_usd": round(total_cost, 2),
        "addon_details": [
            {"addon": 1, "cost_usd": round(addon1_usd, 2), "pct": ADDON1_PCT, "label": "黑天鹅第一档"},
            {"addon": 2, "cost_usd": round(addon2_usd, 2), "pct": ADDON2_PCT, "label": "黑天鹅第二档"},
            {"addon": 3, "cost_usd": round(addon3_usd, 2), "pct": ADDON3_PCT, "label": "黑天鹅第三档"},
        ]
    }


def calculate_capital_allocation():
    balance = get_account_balance()
    positions = get_current_positions()
    single_cost = calculate_single_position_cost()
    
    total_eq = balance["total_eq"]
    avail_balance = balance["avail_balance"]
    used_margin = balance["used_margin"]
    
    current_positions_count = len(positions)
    max_positions_allowed = MAX_CONCURRENT_POSITIONS - current_positions_count
    
    total_cost_per_position = single_cost["total_cost_usd"]
    base_usd = single_cost["base_usd"]
    
    positions_can_open = 0
    if total_cost_per_position > 0:
        positions_can_open = int(avail_balance / total_cost_per_position)
    positions_can_open = min(positions_can_open, max_positions_allowed)
    
    remaining_after_open = avail_balance - (positions_can_open * total_cost_per_position)
    
    margin_usage_pct = (used_margin / total_eq) * 100 if total_eq > 0 else 0
    
    allocation = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "balance": balance,
        "positions": positions,
        "coins_monitored": V15CT_COINS,
        "single_position_cost": single_cost,
        "parameters": {
            "total_budget": TOTAL_BUDGET,
            "max_concurrent_positions": MAX_CONCURRENT_POSITIONS,
            "max_addons_per_position": MAX_ADDONS_PER_POSITION,
            "addon_pct": ADDON_PCT,
            "base_position_pct": BASE_POSITION_PCT,
            "addon1_pct": ADDON1_PCT,
            "addon2_pct": ADDON2_PCT,
            "addon3_pct": ADDON3_PCT,
            "max_position_pct": MAX_POSITION_PCT,
            "leverage": LEVERAGE,
            "min_margin_usd": MIN_MARGIN_USD,
            "strategy": "底仓现货思维 + 黑天鹅加仓 + 三屏趋势过滤",
        },
        "calculations": {
            "current_positions_count": current_positions_count,
            "max_positions_allowed": max_positions_allowed,
            "total_cost_per_position_usd": total_cost_per_position,
            "base_usd": base_usd,
            "positions_can_open": positions_can_open,
            "remaining_after_open_usd": round(remaining_after_open, 2),
            "margin_usage_pct": round(margin_usage_pct, 2),
            "avail_balance_pct": round((avail_balance / total_eq) * 100, 2),
        },
        "recommendations": {
            "allow_open_new_position": positions_can_open > 0 and remaining_after_open > MIN_MARGIN_USD,
            "allow_addon": remaining_after_open > MIN_MARGIN_USD,
            "risk_level": _assess_risk_level(margin_usage_pct, current_positions_count),
            "advice": _generate_advice(positions_can_open, margin_usage_pct, current_positions_count, total_cost_per_position),
        }
    }
    
    return allocation


def _assess_risk_level(margin_pct, position_count):
    if margin_pct > 80 or position_count >= MAX_CONCURRENT_POSITIONS:
        return "HIGH"
    elif margin_pct > 50 or position_count >= MAX_CONCURRENT_POSITIONS * 0.75:
        return "MEDIUM"
    else:
        return "LOW"


def _generate_advice(positions_can_open, margin_pct, position_count, total_cost_per_position):
    if margin_pct > 80:
        return f"⚠️ 保证金使用率过高({margin_pct:.0f}%)，建议平仓或等待"
    if position_count >= MAX_CONCURRENT_POSITIONS:
        return f"⚠️ 已达最大持仓数({position_count}/{MAX_CONCURRENT_POSITIONS})，无法开新仓"
    if positions_can_open == 0:
        return f"⚠️ 可用资金不足，无法开新仓（单仓位需${total_cost_per_position}）"
    if positions_can_open >= 2:
        return f"⚠️ 资金过于充足，建议只开1个仓位确保加仓空间"
    return f"✅ 可开1个新仓位（单仓位需${total_cost_per_position}，包含3次加仓）"


def check_can_open_position(symbol=None):
    allocation = calculate_capital_allocation()
    return allocation["recommendations"]["allow_open_new_position"]


def check_can_addon():
    allocation = calculate_capital_allocation()
    return allocation["recommendations"]["allow_addon"]


def get_coin_allocation(symbol):
    allocation = calculate_capital_allocation()
    base_usd = allocation["single_position_cost"]["base_usd"]
    
    for pos in allocation["positions"]:
        if pos["symbol"] == symbol:
            return {
                "symbol": symbol,
                "has_position": True,
                "current_margin": pos["margin"],
                "base_position_usd": base_usd,
                "can_addon": allocation["recommendations"]["allow_addon"],
                "unrealized_pnl": pos["unrealized_pnl"],
            }
    
    return {
        "symbol": symbol,
        "has_position": False,
        "current_margin": 0,
        "base_position_usd": base_usd,
        "can_open": allocation["recommendations"]["allow_open_new_position"],
        "can_addon": False,
        "unrealized_pnl": 0,
    }


def get_signal_trigger_status():
    allocation = calculate_capital_allocation()
    can_open = allocation["recommendations"]["allow_open_new_position"]
    
    trigger_status = {}
    for symbol in V15CT_COINS:
        has_position = any(pos["symbol"] == symbol for pos in allocation["positions"])
        trigger_status[symbol] = {
            "can_trigger": can_open and not has_position,
            "has_position": has_position,
            "can_addon": has_position and allocation["recommendations"]["allow_addon"],
        }
    
    return {
        "can_open_new_position": can_open,
        "current_positions_count": allocation["calculations"]["current_positions_count"],
        "max_positions_allowed": allocation["calculations"]["max_positions_allowed"],
        "coins": trigger_status,
    }


def get_coin_strategy_params(symbol, direction="LONG"):
    try:
        from strategy_params import get_coin_strategy_params as _get_params
        return _get_params(symbol, direction)
    except Exception as e:
        return {"error": str(e)}


def get_all_coins_strategy_params():
    result = {}
    for symbol in V15CT_COINS:
        try:
            result[symbol] = get_coin_strategy_params(symbol, "LONG")
        except Exception as e:
            result[symbol] = {"error": str(e)}
    return result


def calculate_position_risk(pos):
    """计算单个仓位的风险参数"""
    try:
        symbol = pos["symbol"]
        direction = pos.get("direction", "LONG")
        entry = pos.get("entry_price", 0)
        open_price = pos.get("open_price", entry)
        current = pos.get("mark_price", 0)
        
        params = get_coin_strategy_params(symbol, direction)
        if "error" in params:
            return {"error": params["error"]}
        
        sl = params.get("stop_loss", {})
        tp_pct = params.get("take_profit_pct", 0) / 100
        addon_pct = params.get("addon_pct", 0) / 100
        
        tp_price = entry * (1 + tp_pct) if direction == "LONG" else entry * (1 - tp_pct)
        
        addon_levels = []
        for i in range(1, 4):
            target_drop = addon_pct * i
            if direction == "LONG":
                level_price = open_price * (1 - target_drop)
            else:
                level_price = open_price * (1 + target_drop)
            addon_levels.append({
                "level": i,
                "price": round(level_price, 4),
                "drop_pct": round(target_drop * 100, 2),
            })
        
        profit_pct = (current - entry) / entry if direction == "LONG" else (entry - current) / entry
        distance_to_tp = (tp_price - current) / current if direction == "LONG" else (current - tp_price) / current
        
        sl_price = sl.get("stop_loss_price")
        if sl_price is not None and sl_price > 0:
            distance_to_sl = (current - sl_price) / current if direction == "LONG" else (sl_price - current) / current
            distance_to_sl_pct = round(distance_to_sl * 100, 2)
        else:
            distance_to_sl_pct = None
        
        return {
            "symbol": symbol,
            "direction": direction,
            "entry_price": entry,
            "open_price": open_price,
            "current_price": current,
            "profit_pct": round(profit_pct * 100, 2),
            "take_profit_price": round(tp_price, 4),
            "take_profit_pct": params.get("take_profit_pct", 0),
            "stop_loss_price": sl_price,
            "stop_loss_pct": sl.get("stop_loss_pct"),
            "stop_loss_type": sl.get("stop_type"),
            "stop_loss_triggered": sl.get("is_triggered", False),
            "addon_pct": params.get("addon_pct", 0),
            "addon_levels": addon_levels,
            "distance_to_tp_pct": round(distance_to_tp * 100, 2),
            "distance_to_sl_pct": distance_to_sl_pct,
            "volatility": params.get("volatility", {}),
            "last_daily_close": params.get("last_daily_close"),
            "last_weekly_close": params.get("last_weekly_close"),
        }
    except Exception as e:
        return {"error": str(e)}


if __name__ == "__main__":
    alloc = calculate_capital_allocation()
    print(json.dumps(alloc, indent=2, ensure_ascii=False))
    
    print("\n=== 信号触发状态 ===")
    trigger = get_signal_trigger_status()
    print(json.dumps(trigger, indent=2, ensure_ascii=False))