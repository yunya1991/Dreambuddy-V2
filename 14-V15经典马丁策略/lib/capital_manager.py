#!/usr/bin/env python3
"""
资金管理计算器 - 马丁策略专用（贝叶斯优化版）

核心策略：底仓现货思维 + 黑天鹅加仓 + 三屏趋势过滤
- 底仓22%资金 + 5倍杠杆 ≈ 110%现货敞口（平时略占优，有止盈机制）
- 加仓间距保持不变（8%基准），用于黑天鹅时拉低成本
- 止盈固定4%（BTC基准，其他币种按波动率放大）
- 趋势过滤：周线+日线MA104双周期都看空时禁止做多马丁

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

BASE_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(BASE_DIR / "lib"))

try:
    from config_loader import load_config, get_config, get_config_float, get_config_int, get_config_list
    load_config("v15")
except Exception:
    pass

# 统一交易对适配层
try:
    from symbol_mapper import to_swap, is_supported as _coin_supported
except Exception:
    def to_swap(coin, exchange="okx"): return f"{coin}-USDT-SWAP"
    def _coin_supported(coin, exchange="okx"): return True

# ── 贝叶斯优化后的参数（底仓现货思维 + 黑天鹅加仓）──
TOTAL_BUDGET = get_config_float("TOTAL_BUDGET", 100)
MAX_CONCURRENT_POSITIONS = get_config_int("MAX_CONCURRENT_POSITIONS", 6)
MAX_ADDONS_PER_POSITION = get_config_int("MAX_ADDONS_PER_POSITION", 3)
ADDON_PCT = get_config_float("ADDON_PCT", 0.08)  # 加仓间距（保持不变）

# 底仓22% + 杠杆5x（现货思维）
BASE_POSITION_PCT = get_config_float("BASE_POSITION_PCT", 0.22)
LEVERAGE = get_config_float("LEVERAGE", 5.0)

# 加仓资金分配（金字塔结构：越跌加仓越大，经典马丁）
ADDON1_PCT = get_config_float("ADDON1_PCT", 0.05)  # 加仓1：5%（黑天鹅第一档）
ADDON2_PCT = get_config_float("ADDON2_PCT", 0.10)  # 加仓2：10%
ADDON3_PCT = get_config_float("ADDON3_PCT", 0.20)  # 加仓3：20%（最深处加仓最大）

MAX_POSITION_PCT = get_config_float("MAX_POSITION_PCT", 0.60)
MIN_MARGIN_USD = get_config_float("MIN_MARGIN_USD", 20)

# 币种池：用 SymbolMapper 过滤出 OKX 支持的币种
_RAW_COINS = get_config_list("V15_COINS", default=["BTC", "ETH", "SOL", "ARB", "OP", "UNI", "HYPE", "OKB"])
FILTERED_COINS = [c for c in _RAW_COINS if _coin_supported(c, "okx")] or _RAW_COINS
V15CT_COINS = FILTERED_COINS


def _get_okx_client():
    try:
        from okx_client import OKXSimulatedClient
        config = {
            "api_key": get_config("OKX_API_KEY", ""),
            "secret_key": get_config("OKX_SECRET_KEY", ""),
            "passphrase": get_config("OKX_PASSPHRASE", ""),
            "simulated": False,
            "dry_run": False,
            "base_url": "https://www.okx.com",
            "default_inst_id": "BTC-USDT-SWAP",
            "default_usdt_amount": 100,
            "default_leverage": 5.0,
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
    """获取账户所有持仓（一次性查询，不局限于 V15_COINS 配置列表）

    使用 get_all_positions() 避免：
    1. 逐个查询触发 API 限流
    2. 遗漏不在 V15_COINS 中的持仓（如外部开仓的 NEAR、ZEC）
    """
    client = _get_okx_client()
    positions = []

    if not client:
        return positions

    try:
        r = client.get_all_positions()
        if not r.get("ok"):
            return positions

        pos_map = r.get("positions", {})
        for coin, p in pos_map.items():
            pos_sz = float(p.get("pos", 0))
            if pos_sz == 0:
                continue
            pos_side = p.get("pos_side", "net")
            is_long = pos_side == "long" or (pos_side == "net" and pos_sz > 0)
            inst_id = p.get("inst_id", to_swap(coin))
            positions.append({
                "symbol": coin,
                "inst_id": inst_id,
                "direction": "LONG" if is_long else "SHORT",
                "pos_side": pos_side,
                "pos_sz": abs(pos_sz),
                "entry_price": float(p.get("avg_px", 0)),
                "mark_price": float(p.get("mark_px", 0)),
                "margin": float(p.get("margin", 0)),
                "unrealized_pnl": float(p.get("upl", 0)),
                "upl_ratio": float(p.get("upl_ratio", 0)),
                "lever": p.get("lever", ""),
            })
    except Exception:
        pass

    return positions


def calculate_single_position_cost(budget=None):
    """计算单个仓位完整资金需求（底仓+所有加仓）

    动态预算模式：当 budget=None 时，使用 OKX 实际账户余额作为预算
    贝叶斯优化后的资金分配：
    - 底仓 = BASE_POSITION_PCT(22%) * budget
    - 加仓1 = ADDON1_PCT(20%) * budget  ← 黑天鹅第一档
    - 加仓2 = ADDON2_PCT(5%) * budget
    - 加仓3 = ADDON3_PCT(10%) * budget
    """
    if budget is None:
        budget = _get_dynamic_budget()

    base_usd = budget * BASE_POSITION_PCT

    addon1_usd = budget * ADDON1_PCT
    addon2_usd = budget * ADDON2_PCT
    addon3_usd = budget * ADDON3_PCT
    addon_total = addon1_usd + addon2_usd + addon3_usd

    total_cost = base_usd + addon_total
    return {
        "base_usd": round(base_usd, 2),
        "addon_total_usd": round(addon_total, 2),
        "total_cost_usd": round(total_cost, 2),
        "budget_source": "dynamic" if budget != TOTAL_BUDGET else "static",
        "budget_value": round(budget, 2),
        "addon_details": [
            {"addon": 1, "cost_usd": round(addon1_usd, 2), "pct": ADDON1_PCT, "label": "黑天鹅第一档"},
            {"addon": 2, "cost_usd": round(addon2_usd, 2), "pct": ADDON2_PCT, "label": "黑天鹅第二档"},
            {"addon": 3, "cost_usd": round(addon3_usd, 2), "pct": ADDON3_PCT, "label": "黑天鹅第三档"},
        ]
    }


def calculate_per_coin_allocation(symbol, confidence=60, elder_ray=None, available_budget=None):
    """基于趋势强度+置信度+波动率的智能资金分配

    资金管理器三大职责：
    1. 最大持仓币种数控制
    2. 各币种总预算管理（基于 Elder-ray 趋势强度 + 信号置信度）
    3. 3次加仓资金预算分配

    固定参数（不参与优化）：
    - BTC 基础仓 22%
    - 5x 杠杆
    - 加仓间距 8%（按波动率放大）
    其他币种按波动率放大

    动态参数（由贝叶斯优化确定）：
    - addon1/2/3_pct: 加仓资金比例
    - max_concurrent_positions: 最大持仓数

    分配逻辑：
    1. per_coin_budget = available_budget / remaining_slots
    2. 根据 Elder-ray 趋势强度调整 (0.5x - 1.5x)
    3. 根据信号置信度调整 (0.5x - 1.5x)
    4. 扣除基础仓占用 + 下跌带来保证金占用
    """
    # 获取可用预算
    if available_budget is None:
        balance = get_account_balance()
        available_budget = balance.get("avail_balance", TOTAL_BUDGET) if balance.get("ok") else TOTAL_BUDGET

    # 获取当前持仓数
    positions = get_current_positions()
    current_count = len(positions)
    remaining_slots = MAX_CONCURRENT_POSITIONS - current_count

    if remaining_slots <= 0:
        return {
            "allowed": False,
            "reason": f"已达最大持仓数({MAX_CONCURRENT_POSITIONS})",
            "current_positions": current_count,
            "remaining_slots": 0,
        }

    # 获取币种波动率
    try:
        from strategy_params import get_coin_strategy_params
        params = get_coin_strategy_params(symbol, "LONG")
        vol_ratio = params.get("volatility", {}).get("vol_ratio", 1.0)
    except Exception:
        vol_ratio = 1.0
    vol_ratio = max(0.5, min(2.0, vol_ratio))

    # ── Elder-ray 趋势强度调整 (0.3x - 1.5x) ──
    if elder_ray:
        strength = elder_ray.get("strength", 50)
        direction = elder_ray.get("direction", "BULL_TREND")
        ema_trend = elder_ray.get("ema_trend", "flat")
        both_weakening = elder_ray.get("both_weakening", False)
        bullish_div = elder_ray.get("bullish_divergence", False)

        # 基于 EMA 趋势方向 + Elder-ray 状态决定乘数
        if ema_trend == "up":
            if direction == "STRONG_BULL":
                strength_mult = 1.2 + (strength / 100) * 0.3  # 1.2 - 1.5
            elif direction == "BULL_TREND":
                strength_mult = 1.0 + (strength / 100) * 0.3  # 1.0 - 1.3
            elif direction == "BULL_REVERSAL":
                strength_mult = 0.5 + (strength / 100) * 0.3  # 0.5 - 0.8
            else:
                strength_mult = 0.8 + (strength / 100) * 0.2  # 0.8 - 1.0
        elif ema_trend == "down":
            if direction == "STRONG_BEAR":
                strength_mult = 0.3 + (strength / 100) * 0.2  # 0.3 - 0.5
            elif direction == "BEAR_TREND":
                strength_mult = 0.4 + (strength / 100) * 0.2  # 0.4 - 0.6
            elif direction == "BEAR_REVERSAL":
                strength_mult = 0.7 + (strength / 100) * 0.3  # 0.7 - 1.0
            else:
                strength_mult = 0.5 + (strength / 100) * 0.2  # 0.5 - 0.7
        else:  # flat
            strength_mult = 0.7 + (strength / 100) * 0.3  # 0.7 - 1.0

        # 看涨背离 + EMA上升 → 强做多信号 → 加成
        if bullish_div and ema_trend == "up":
            strength_mult *= 1.2

        # 多空都减弱 → 变盘风险 → 降仓
        if both_weakening:
            strength_mult *= 0.7
    else:
        strength_mult = 1.0

    # ── 信号置信度调整 (0.5x - 1.5x) ──
    # conf=60 → 0.8x, conf=80 → 1.2x, conf=100 → 1.5x
    conf_mult = 0.5 + (confidence / 100) * 1.0
    conf_mult = max(0.5, min(1.5, conf_mult))

    # ── 波动率反向调整：高波动率币种减小仓位 ──
    # BTC vol_ratio=1.0 → 1.0x, 高波动币种 vol_ratio=2.0 → 0.7x
    vol_adjust = 1.0 / (0.5 + vol_ratio * 0.5)  # vol=1→1.0, vol=2→0.67, vol=0.5→1.33
    vol_adjust = max(0.5, min(1.5, vol_adjust))

    # ── 综合调整因子 ──
    combined_mult = strength_mult * conf_mult * vol_adjust
    combined_mult = max(0.2, min(2.0, combined_mult))

    # ── 每币种预算 ──
    base_per_coin = available_budget / remaining_slots
    per_coin_budget = base_per_coin * combined_mult

    # 不超过可用资金的 MAX_POSITION_PCT (60%)
    max_per_coin = available_budget * MAX_POSITION_PCT
    per_coin_budget = min(per_coin_budget, max_per_coin)

    # 不低于 MIN_MARGIN_USD / BASE_POSITION_PCT（确保底仓 >= MIN_MARGIN_USD）
    min_budget = MIN_MARGIN_USD / BASE_POSITION_PCT if BASE_POSITION_PCT > 0 else MIN_MARGIN_USD * 5
    per_coin_budget = max(per_coin_budget, min_budget) if per_coin_budget > 0 else 0

    # ── 资金分配 ──
    # 固定：底仓22%，5x杠杆
    # 动态（贝叶斯优化）：addon1/2/3
    base_usd = per_coin_budget * BASE_POSITION_PCT
    addon1_usd = per_coin_budget * ADDON1_PCT
    addon2_usd = per_coin_budget * ADDON2_PCT
    addon3_usd = per_coin_budget * ADDON3_PCT
    total_needed = base_usd + addon1_usd + addon2_usd + addon3_usd

    # ── 检查资金充足性（扣除基础仓 + 下跌保证金）──
    # 下跌8%时，5x杠杆的保证金需求增加约 8% * 5 = 40% 的 base_usd
    # 加仓1触发时需要 addon1_usd + 浮亏保证金
    drawdown_margin = base_usd * 0.4 * LEVERAGE / LEVERAGE  # 简化：base_usd * 0.4
    total_with_drawdown = total_needed + drawdown_margin

    if total_with_drawdown > available_budget * 0.85:
        # 按比例缩减，保留15%缓冲
        scale = available_budget * 0.85 / total_with_drawdown
        base_usd *= scale
        addon1_usd *= scale
        addon2_usd *= scale
        addon3_usd *= scale
        total_needed = base_usd + addon1_usd + addon2_usd + addon3_usd
        drawdown_margin *= scale

    remaining_after = available_budget - total_needed - drawdown_margin
    allowed = remaining_after > MIN_MARGIN_USD and base_usd >= MIN_MARGIN_USD

    return {
        "allowed": allowed,
        "symbol": symbol,
        "per_coin_budget": round(per_coin_budget, 2),
        "base_usd": round(base_usd, 2),
        "addon1_usd": round(addon1_usd, 2),
        "addon2_usd": round(addon2_usd, 2),
        "addon3_usd": round(addon3_usd, 2),
        "total_usd": round(total_needed, 2),
        "drawdown_margin": round(drawdown_margin, 2),
        "remaining_after": round(remaining_after, 2),
        "adjustments": {
            "strength_mult": round(strength_mult, 3),
            "conf_mult": round(conf_mult, 3),
            "vol_adjust": round(vol_adjust, 3),
            "combined_mult": round(combined_mult, 3),
            "elder_ray_direction": elder_ray.get("direction") if elder_ray else "N/A",
            "elder_ray_ema_trend": elder_ray.get("ema_trend") if elder_ray else "N/A",
            "elder_ray_strength": elder_ray.get("strength") if elder_ray else 0,
            "elder_ray_both_weakening": elder_ray.get("both_weakening") if elder_ray else False,
            "elder_ray_bullish_div": elder_ray.get("bullish_divergence") if elder_ray else False,
            "confidence": confidence,
            "vol_ratio": round(vol_ratio, 3),
        },
        "current_positions": current_count,
        "remaining_slots": remaining_slots,
        "available_budget": round(available_budget, 2),
    }


def _get_dynamic_budget():
    """获取动态预算：优先使用 OKX 实际账户余额，失败时回退到配置的 TOTAL_BUDGET"""
    try:
        balance = get_account_balance()
        if balance.get("ok") and balance.get("total_eq", 0) > 0:
            return balance["total_eq"]
    except Exception:
        pass
    return TOTAL_BUDGET


def calculate_capital_allocation():
    balance = get_account_balance()
    positions = get_current_positions()

    # 动态预算：用实际账户余额替代配置的 TOTAL_BUDGET
    dynamic_budget = balance.get("total_eq", TOTAL_BUDGET) if balance.get("ok") else TOTAL_BUDGET
    single_cost = calculate_single_position_cost(budget=dynamic_budget)

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
            "total_budget": round(dynamic_budget, 2),
            "total_budget_config": TOTAL_BUDGET,
            "budget_mode": "dynamic" if balance.get("ok") else "static_fallback",
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
            "trend_filter": params.get("trend_filter", {}),
        }
    except Exception as e:
        return {"error": str(e)}


if __name__ == "__main__":
    alloc = calculate_capital_allocation()
    print(json.dumps(alloc, indent=2, ensure_ascii=False))
    
    print("\n=== 信号触发状态 ===")
    trigger = get_signal_trigger_status()
    print(json.dumps(trigger, indent=2, ensure_ascii=False))
