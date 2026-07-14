#!/usr/bin/env python3
"""
V15 经典马丁策略自动交易器
- 定时轮询8个币种信号
- 根据资金计算器决定是否开仓
- 马丁加仓：最多3次，资金不足时禁止开新仓
- 只做多模式
"""
import json, os, sys, time, math, signal as sig_module, subprocess, threading
from datetime import datetime, timezone, timedelta
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(BASE_DIR / "lib"))
sys.path.insert(0, str(BASE_DIR / "core"))

try:
    from config_loader import load_config, get_config, get_config_float, get_config_int, get_config_list, get_config_bool
    load_config("v15")
except Exception:
    pass

# 统一交易对适配层（替代散落的 f"{coin}-USDT" / f"{coin}-USDT-SWAP" 硬编码）
try:
    from symbol_mapper import to_spot, to_swap, is_supported as _coin_supported, get_category
except Exception:
    # 降级：保留原硬编码行为，保证向后兼容
    def to_spot(coin, exchange="okx"): return f"{coin}-USDT"
    def to_swap(coin, exchange="okx"): return f"{coin}-USDT-SWAP"
    def _coin_supported(coin, exchange="okx"): return True
    def get_category(coin): return "crypto"

try:
    from bounce_potential_evaluator import monitor_bounce_signals
    BOUNCE_MONITOR_ENABLED = True
except ImportError:
    BOUNCE_MONITOR_ENABLED = False

STATE_FILE = BASE_DIR / "data" / "v15_state.json"
LOG_DIR = BASE_DIR / "logs" / "v15"
LOG_DIR.mkdir(parents=True, exist_ok=True)
STATE_FILE.parent.mkdir(parents=True, exist_ok=True)

POLL_INTERVAL = int(get_config("V15_POLL_INTERVAL", "3600"))
AUTO_EXECUTE = str(get_config("V15_AUTO_EXECUTE", "true")).lower() == "true"
# 币种池：从配置加载后，用 SymbolMapper 过滤出 OKX 支持的币种
_RAW_COINS = get_config_list("V15_COINS", default=["BTC", "ETH", "SOL", "ARB", "OP", "UNI", "HYPE", "OKB"])
COINS = [c for c in _RAW_COINS if _coin_supported(c, "okx")] or _RAW_COINS
MAX_ADDONS = get_config_int("MAX_ADDONS_PER_POSITION", 3)
BASE_TP_PCT = get_config_float("BASE_TP_PCT", 0.04)
LEVERAGE = get_config_float("LEVERAGE", 5.0)


def _log(msg):
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    log_file = LOG_DIR / f"v15_{datetime.now(timezone.utc).strftime('%Y%m%d')}.log"
    with open(log_file, "a") as f:
        f.write(line + "\n")


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
        _log(f"OKX实盘客户端已连接 | simulated={client.simulated} dry_run={client.dry_run}")
        return client
    except Exception as e:
        _log(f"OKX客户端连接失败: {e}")
        return None


def load_state():
    if STATE_FILE.exists():
        try:
            with open(STATE_FILE) as f:
                state = json.load(f)
            for coin, pos in state.get("positions", {}).items():
                if "open_price" not in pos:
                    pos["open_price"] = pos.get("entry_price", 0)
                if "vol_mult" not in pos:
                    pos["vol_mult"] = 1.0
            return state
        except Exception:
            pass
    return {
        "positions": {},
        "total_trades": 0,
        "total_wins": 0,
        "daily_pnl": 0.0,
        "last_poll": "",
        "consecutive_losses": 0,
        "last_capital_rebuild": "",
    }


def save_state(state):
    state["last_poll"] = datetime.now(timezone.utc).isoformat()
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)


def get_v15_decision(coin):
    """获取单个币种的V15经典马丁策略决策"""
    try:
        from v15_signal import v15_decision
        return v15_decision(to_spot(coin))
    except Exception as e:
        _log(f"[{coin}] 决策失败: {e}")
        return {"action": "WAIT", "confidence": 0, "reasons": [str(e)]}


def check_capital():
    """检查资金是否允许开新仓"""
    try:
        from capital_manager import calculate_capital_allocation
        alloc = calculate_capital_allocation()
        return alloc["recommendations"]["allow_open_new_position"], alloc
    except Exception as e:
        _log(f"资金检查失败: {e}")
        return False, {}


def execute_open_position(client, coin, decision, state):
    """执行开仓 - 使用智能资金分配"""
    inst_id = to_swap(coin)
    conf = decision.get("confidence", 0)

    if conf < 60:
        _log(f"[{coin}] 置信度不足({conf}<60), 跳过")
        return False

    try:
        params = _get_dynamic_params(client, coin, "LONG")
        price = params["current_price"]
        if price <= 0:
            _log(f"[{coin}] 价格异常: {price}")
            return False

        if params["stop_loss_triggered"]:
            _log(f"[{coin}] 价格在所有均线下({params['stop_loss_type']})，熊市禁止开多仓")
            return False

        tp_pct = params["take_profit_pct"]
        addon_pct = params["addon_pct"]
        sl_price = params["stop_loss_price"]
        sl_type = params["stop_loss_type"]

        # ── 智能资金分配 ──
        from capital_manager import calculate_per_coin_allocation
        elder_ray = params.get("elder_ray")
        alloc = calculate_per_coin_allocation(coin, conf, elder_ray)

        if not alloc.get("allowed"):
            _log(f"[{coin}] 资金分配不允许: {alloc.get('reason', '资金不足')}")
            return False

        base_margin = alloc["base_usd"]
        vol_mult = decision.get("vol_mult", 1.0)
        order_margin = base_margin * vol_mult
        order_notional = order_margin * LEVERAGE

        lot_sz, ct_val = get_contract_info(client, inst_id)
        sz = calc_lot_sz(order_notional, price, lot_sz, ct_val)
        if sz < lot_sz:
            _log(f"[{coin}] 下单数量({sz}张)小于最小单位({lot_sz}张), 跳过")
            return False

        actual_notional = sz * ct_val * price
        actual_margin = actual_notional / LEVERAGE

        adj = alloc.get("adjustments", {})
        _log(f"[{coin}] 开仓 LONG sz={sz}张 price={price} 保证金=${actual_margin:.2f} 名义=${actual_notional:.2f} "
             f"TP={tp_pct*100:.2f}% SL={sl_type}@${sl_price} conf={conf}% "
             f"资金分配: 趋势={adj.get('strength_mult', 1.0):.2f}x 置信={adj.get('conf_mult', 1.0):.2f}x "
             f"波动={adj.get('vol_adjust', 1.0):.2f}x 综合={adj.get('combined_mult', 1.0):.2f}x "
             f"EMA={adj.get('elder_ray_direction', 'N/A')} "
             f"Dir={adj.get('elder_ray_ema_trend', 'N/A')} "
             f"强度={adj.get('elder_ray_strength', 0):.1f}")

        if AUTO_EXECUTE:
            r = client.place_order(
                inst_id=inst_id,
                side="buy",
                sz=sz,
                td_mode="isolated",
                pos_side="long",
            )
            if r.get("ok"):
                _log(f"[{coin}] 开仓成功: {r.get('data', {})}")
                state["positions"][coin] = {
                    "inst_id": inst_id,
                    "entry_price": price,
                    "open_price": price,
                    "sz": sz,
                    "addons": 0,
                    "confidence": conf,
                    "open_time": datetime.now(timezone.utc).isoformat(),
                    "take_profit_pct": tp_pct,
                    "addon_pct": addon_pct,
                    "stop_loss_price": sl_price,
                    "stop_loss_type": sl_type,
                    "vol_mult": vol_mult,
                    "per_coin_budget": alloc.get("per_coin_budget", 0),
                    "base_usd": alloc.get("base_usd", 0),
                    "addon1_usd": alloc.get("addon1_usd", 0),
                    "addon2_usd": alloc.get("addon2_usd", 0),
                    "addon3_usd": alloc.get("addon3_usd", 0),
                }
                state["total_trades"] += 1
                return True
            else:
                _log(f"[{coin}] 开仓失败: {r.get('error', r)}")
                return False
        else:
            _log(f"[{coin}] 模拟模式: 不执行实盘下单")
            return False
    except Exception as e:
        _log(f"[{coin}] 开仓异常: {e}")
        return False


def execute_addon(client, coin, pos, state):
    """执行加仓 - 使用持仓时分配的加仓预算"""
    inst_id = pos["inst_id"]
    addons = pos.get("addons", 0)

    if addons >= MAX_ADDONS:
        _log(f"[{coin}] 已达最大加仓次数({MAX_ADDONS})")
        return False

    try:
        from capital_manager import calculate_capital_allocation
        alloc = calculate_capital_allocation()
        if not alloc["recommendations"]["allow_addon"]:
            _log(f"[{coin}] 资金不足, 跳过加仓")
            return False

        params = _get_dynamic_params(client, coin, "LONG")
        addon_pct = params["addon_pct"]
        current_price = params["current_price"]
        if current_price <= 0:
            return False

        # 使用开仓时分配的加仓预算
        addon_budgets = [
            pos.get("addon1_usd", 0),
            pos.get("addon2_usd", 0),
            pos.get("addon3_usd", 0),
        ]
        addon_usd = addon_budgets[addons] if addons < len(addon_budgets) else 0
        if addon_usd <= 0:
            # 回退到旧逻辑
            base_margin = alloc["single_position_cost"]["base_usd"]
            vol_mult = pos.get("vol_mult", 1.0)
            addon_usd = base_margin * vol_mult * (addon_pct * (addons + 1))

        vol_mult = pos.get("vol_mult", 1.0)
        addon_margin = addon_usd * vol_mult
        addon_notional = addon_margin * LEVERAGE

        open_price = pos.get("open_price", pos["entry_price"])
        target_drop_pct = addon_pct * (addons + 1)
        drop_pct = (open_price - current_price) / open_price
        if drop_pct < target_drop_pct:
            _log(f"[{coin}] 跌幅不足({drop_pct:.2%}<{target_drop_pct:.2%}), 跳过加仓 (第{addons+1}层)")
            return False

        lot_sz, ct_val = get_contract_info(client, inst_id)
        sz = calc_lot_sz(addon_notional, current_price, lot_sz, ct_val)
        if sz < lot_sz:
            _log(f"[{coin}] 加仓数量({sz}张)小于最小单位({lot_sz}张), 跳过")
            return False

        actual_notional = sz * ct_val * current_price
        actual_margin = actual_notional / LEVERAGE
        _log(f"[{coin}] 加仓#{addons+1} sz={sz}张 price={current_price} 保证金=${actual_margin:.2f} 名义=${actual_notional:.2f} "
             f"开仓价=${open_price:.2f} 跌幅={drop_pct:.2%} 预算=${addon_usd:.2f}")

        if AUTO_EXECUTE:
            r = client.place_order(
                inst_id=inst_id,
                side="buy",
                sz=sz,
                td_mode="isolated",
                pos_side="long",
            )
            if r.get("ok"):
                pos["addons"] = addons + 1
                pos["entry_price"] = (pos["entry_price"] * pos["sz"] + current_price * sz) / (pos["sz"] + sz)
                pos["sz"] += sz
                pos["last_addon_time"] = datetime.now(timezone.utc).isoformat()
                _log(f"[{coin}] 加仓成功, 总仓位={pos['sz']} 均价=${pos['entry_price']:.2f}")
                return True
            else:
                _log(f"[{coin}] 加仓失败: {r.get('error', r)}")
                return False
        return False
    except Exception as e:
        _log(f"[{coin}] 加仓异常: {e}")
        return False


def _get_dynamic_params(client, coin, direction="LONG"):
    """获取币种的动态策略参数（止盈、加仓、止损）"""
    from strategy_params import get_coin_strategy_params
    params = get_coin_strategy_params(coin, direction)
    if "error" in params:
        raise ValueError(params["error"])
    
    sl = params["stop_loss"]
    vol = params["volatility"]
    
    return {
        "current_price": params["current_price"],
        "take_profit_pct": params["take_profit_pct"] / 100,
        "addon_pct": params["addon_pct"] / 100,
        "stop_loss_price": sl["stop_loss_price"],
        "stop_loss_pct": sl["stop_loss_pct"],
        "stop_loss_type": sl["stop_type"],
        "stop_loss_triggered": sl["is_triggered"],
        "daily_ma200": sl["daily_ma200"],
        "daily_ema200": sl["daily_ema200"],
        "weekly_ma200": sl["weekly_ma200"],
        "weekly_ema200": sl["weekly_ema200"],
        "above_daily_ma200": sl["above_daily_ma200_close"],
        "above_daily_ema200": sl["above_daily_ema200_close"],
        "above_weekly_ma200": sl["above_weekly_ma200_close"],
        "above_weekly_ema200": sl["above_weekly_ema200_close"],
        "last_daily_close": params.get("last_daily_close"),
        "last_weekly_close": params.get("last_weekly_close"),
        "volatility": vol,
        "elder_ray": params.get("elder_ray"),
    }


def check_take_profit(client, coin, pos, state):
    """检查止盈和动态止损"""
    inst_id = pos["inst_id"]
    try:
        params = _get_dynamic_params(client, coin, "LONG")
        current_price = params["current_price"]
        if current_price <= 0:
            return False
        
        entry_price = pos["entry_price"]
        profit_pct = (current_price - entry_price) / entry_price
        tp_pct = params["take_profit_pct"]
        sl_price = params["stop_loss_price"]
        sl_type = params["stop_loss_type"]
        sl_triggered = params["stop_loss_triggered"]
        
        if profit_pct >= tp_pct:
            _log(f"[{coin}] 止盈触发 profit={profit_pct:.2%} >= {tp_pct:.2%}")
            
            if AUTO_EXECUTE:
                lot_sz, ct_val = get_contract_info(client, inst_id)
                close_sz = math.floor(pos["sz"] / lot_sz) * lot_sz
                decimals = len(str(lot_sz).split('.')[-1]) if '.' in str(lot_sz) else 0
                close_sz = round(close_sz, decimals)
                r = client.place_order(
                    inst_id=inst_id,
                    side="sell",
                    sz=close_sz,
                    td_mode="isolated",
                    pos_side="long",
                )
                if r.get("ok"):
                    _log(f"[{coin}] 止盈平仓成功")
                    state["total_wins"] += 1
                    state["consecutive_losses"] = 0
                    del state["positions"][coin]
                    return True
                else:
                    _log(f"[{coin}] 止盈平仓失败: {r.get('error', r)}")
            return False
        
        if sl_triggered:
            if sl_price is not None:
                _log(f"[{coin}] 动态止损触发({sl_type}) 价格=${current_price:.2f} <= 止损线=${sl_price:.2f}")
            else:
                _log(f"[{coin}] 动态止损触发({sl_type}) 价格跌破所有均线，无条件止损")
            
            if AUTO_EXECUTE:
                lot_sz, ct_val = get_contract_info(client, inst_id)
                close_sz = math.floor(pos["sz"] / lot_sz) * lot_sz
                decimals = len(str(lot_sz).split('.')[-1]) if '.' in str(lot_sz) else 0
                close_sz = round(close_sz, decimals)
                r = client.place_order(
                    inst_id=inst_id,
                    side="sell",
                    sz=close_sz,
                    td_mode="isolated",
                    pos_side="long",
                )
                if r.get("ok"):
                    _log(f"[{coin}] 止损平仓 ({sl_type})")
                    state["consecutive_losses"] = state.get("consecutive_losses", 0) + 1
                    del state["positions"][coin]
                    if state["consecutive_losses"] >= MAX_CONSECUTIVE_LOSSES_REBUILD:
                        trigger_capital_rebuild(state, reason=f"连续{state['consecutive_losses']}次亏损")
                    return True
                else:
                    _log(f"[{coin}] 止损平仓失败: {r.get('error', r)}")
            return False
        
        return False
    except Exception as e:
        _log(f"[{coin}] 止盈止损检查异常: {e}")
        return False


def check_time_exit(client, coin, pos, state):
    """
    分层超时触发经典离场系统评估。

    分层计时：
      - 有加仓：从最后一次加仓(last_addon_time)计时，先过黄金窗口再过超时阈值
      - 无加仓：从开仓(open_time)计时，过底仓超时阈值

    超时后调用 ClassicExitSystem.evaluate_full()：
      CLOSE    → 平仓
      REDUCE   → 减仓(reduce_frac 比例)
      RAISE_TP → 提高止盈价(new_tp_pct)
      HOLD     → 继续持有
    """
    try:
        params = _get_dynamic_params(client, coin, "LONG")
        current_price = params["current_price"]
        if current_price <= 0:
            return False

        now_utc = datetime.now(timezone.utc)
        addons = pos.get("addons", 0)

        # ── 分层计时 ──────────────────────────────────────────────
        if addons > 0 and pos.get("last_addon_time"):
            # 有加仓 → 从最后一次加仓计时
            base_time = datetime.fromisoformat(pos["last_addon_time"])
            max_hours = get_config_float("V15_MAX_POST_ADDON_HOURS", 24.0)
            golden_window = get_config_float("V15_GOLDEN_WINDOW_HOURS", 12.0)
        else:
            # 无加仓 → 从开仓计时
            open_time_str = pos.get("open_time")
            if not open_time_str:
                return False
            base_time = datetime.fromisoformat(open_time_str)
            max_hours = get_config_float("V15_MAX_BASE_HOLDING_HOURS", 48.0)
            golden_window = 0.0  # 底仓阶段无黄金窗口

        if base_time.tzinfo is None:
            base_time = base_time.replace(tzinfo=timezone.utc)

        hold_hours = (now_utc - base_time).total_seconds() / 3600.0

        # 有加仓时：黄金窗口内不触发（让黑天鹅反弹充分发展）
        if golden_window > 0 and hold_hours < golden_window:
            return False

        # 未超时不触发
        if hold_hours < max_hours:
            return False

        _log(f"[{coin}] 持仓超时 {hold_hours:.1f}h (阈值={max_hours:.0f}h, 加仓={addons}), 触发经典离场评估")

        # ── 调用经典离场系统 ──────────────────────────────────────
        try:
            classic_path = str(Path(__file__).parent.parent.parent / "10-经典指标系统")
            if classic_path not in sys.path:
                sys.path.insert(0, classic_path)
            from classic_exit_system import ClassicExitSystem, PositionState, ExitConfig
            # 禁用 L0 持仓时间硬退出（马丁策略有自己的分层超时逻辑）
            exit_cfg = ExitConfig()
            exit_cfg.l0_max_hold_sec = 999999
            system = ClassicExitSystem(config=exit_cfg)

            entry_price = pos["entry_price"]
            unrealized_pnl_pct = (current_price - entry_price) / entry_price

            pos_state = PositionState(
                coin=coin,
                side="long",
                entry_price=entry_price,
                current_price=current_price,
                position_age_sec=hold_hours * 3600.0,
                unrealized_pnl_pct=unrealized_pnl_pct,
                leverage=LEVERAGE,
                atr_pct=params.get("volatility", 0.02) / 100.0 if params.get("volatility", 0) > 1 else 0.02,
            )

            # 获取1H K线供特征计算（hold_value/hold_risk 需要技术指标）
            candles_1h = None
            try:
                from market_data import fetch_candles
                spot = to_spot(coin)
                candles_1h = fetch_candles(spot, bar="1H", limit=100)
            except Exception:
                pass

            decision = system.evaluate_full(pos_state, candles_1h=candles_1h, regime="trend")

        except Exception as e:
            _log(f"[{coin}] 经典离场系统不可用({e}), 降级保本平仓")
            _execute_close_position(client, coin, pos, state, reason="timeout_fallback")
            return True

        action = decision.action.value if hasattr(decision.action, 'value') else str(decision.action)

        # ── 处理离场动作 ──────────────────────────────────────────
        if action == "close":
            _log(f"[{coin}] 经典评估: CLOSE ({decision.reason})")
            _execute_close_position(client, coin, pos, state, reason="classic_close")
            return True

        elif action == "reduce":
            reduce_frac = decision.reduce_frac if decision.reduce_frac > 0 else 0.3
            _log(f"[{coin}] 经典评估: REDUCE frac={reduce_frac:.0%} ({decision.reason})")
            _execute_reduce_position(client, coin, pos, state, reduce_frac)
            return False

        elif action == "raise_tp":
            new_tp_pct = decision.new_tp_pct
            original_tp = pos.get("take_profit_pct", BASE_TP_PCT)
            # 不超过原始止盈的 2 倍（防止过度贪婪）
            capped_tp = min(new_tp_pct, original_tp * 2.0)
            pos["take_profit_pct"] = capped_tp
            _log(f"[{coin}] 经典评估: RAISE_TP ({decision.reason}) "
                 f"新止盈={capped_tp:.2%} (原={original_tp:.2%})")
            return False

        else:  # hold
            _log(f"[{coin}] 经典评估: HOLD ({decision.reason})")
            return False

    except Exception as e:
        _log(f"[{coin}] 超时离场检查异常: {e}")
        return False


def _execute_close_position(client, coin, pos, state, reason=""):
    """平仓（供 check_time_exit 调用）"""
    inst_id = pos["inst_id"]
    try:
        lot_sz, ct_val = get_contract_info(client, inst_id)
        close_sz = math.floor(pos["sz"] / lot_sz) * lot_sz
        decimals = len(str(lot_sz).split('.')[-1]) if '.' in str(lot_sz) else 0
        close_sz = round(close_sz, decimals)

        if AUTO_EXECUTE:
            r = client.place_order(
                inst_id=inst_id,
                side="sell",
                sz=close_sz,
                td_mode="isolated",
                pos_side="long",
            )
            if r.get("ok"):
                _log(f"[{coin}] 平仓成功 ({reason})")
                state["consecutive_losses"] = state.get("consecutive_losses", 0) + 1
                if coin in state["positions"]:
                    del state["positions"][coin]
                return True
            else:
                _log(f"[{coin}] 平仓失败: {r.get('error', r)}")
                return False
        return False
    except Exception as e:
        _log(f"[{coin}] 平仓异常: {e}")
        return False


def _execute_reduce_position(client, coin, pos, state, reduce_frac):
    """减仓（供 check_time_exit 调用）"""
    inst_id = pos["inst_id"]
    try:
        lot_sz, ct_val = get_contract_info(client, inst_id)
        reduce_sz = math.floor((pos["sz"] * reduce_frac) / lot_sz) * lot_sz
        decimals = len(str(lot_sz).split('.')[-1]) if '.' in str(lot_sz) else 0
        reduce_sz = round(reduce_sz, decimals)

        if reduce_sz < lot_sz:
            _log(f"[{coin}] 减仓数量({reduce_sz})小于最小单位({lot_sz}), 跳过")
            return False

        if AUTO_EXECUTE:
            r = client.place_order(
                inst_id=inst_id,
                side="sell",
                sz=reduce_sz,
                td_mode="isolated",
                pos_side="long",
            )
            if r.get("ok"):
                pos["sz"] -= reduce_sz
                _log(f"[{coin}] 减仓成功 frac={reduce_frac:.0%} sz={reduce_sz} 剩余={pos['sz']}")
                return True
            else:
                _log(f"[{coin}] 减仓失败: {r.get('error', r)}")
                return False
        return False
    except Exception as e:
        _log(f"[{coin}] 减仓异常: {e}")
        return False


ADDON_PCT_CHECK = get_config_float("ADDON_PCT", 0.08)
LEVERAGE = get_config_float("LEVERAGE", 5.0)

MAX_CONSECUTIVE_LOSSES_REBUILD = get_config_int("V15_MAX_CONSECUTIVE_LOSSES", 3)
_capital_rebuild_running = False


def trigger_capital_rebuild(state, reason=""):
    """异步触发资金管理引擎月度优化（不阻塞主循环）"""
    global _capital_rebuild_running
    if _capital_rebuild_running:
        _log("[资金管理] 优化已在运行中，跳过")
        return

    def _run():
        global _capital_rebuild_running
        try:
            _capital_rebuild_running = True
            _log(f"[资金管理] 触发资金优化，原因: {reason}")
            script = BASE_DIR / "run.py"
            cmd = [sys.executable, str(script), "capital_engine", "monthly"]
            result = subprocess.run(
                cmd, capture_output=True, text=True,
                cwd=str(BASE_DIR), timeout=7200,
            )
            if result.returncode == 0:
                _log("[资金管理] 优化完成")
                state["last_capital_rebuild"] = datetime.now(timezone.utc).isoformat()
                state["consecutive_losses"] = 0
                save_state(state)
            else:
                _log(f"[资金管理] 优化失败: {result.stderr[-500:]}")
        except subprocess.TimeoutExpired:
            _log("[资金管理] 优化超时（>2小时）")
        except Exception as e:
            _log(f"[资金管理] 优化异常: {e}")
        finally:
            _capital_rebuild_running = False

    threading.Thread(target=_run, daemon=True).start()


def check_monthly_rebuild(state):
    """检查是否需要运行月度资金优化（每月1号运行一次）"""
    now = datetime.now(timezone.utc)
    last_rebuild = state.get("last_capital_rebuild", "")
    
    if now.day != 1:
        return False
    
    if last_rebuild:
        try:
            last_dt = datetime.fromisoformat(last_rebuild.replace("Z", "+00:00"))
            if last_dt.year == now.year and last_dt.month == now.month:
                return False
        except:
            pass
    
    return True

_lot_size_cache = {}
_ct_val_cache = {}

def get_contract_info(client, inst_id):
    """获取合约信息（lotSz, ctVal）带缓存"""
    if inst_id in _lot_size_cache and inst_id in _ct_val_cache:
        return _lot_size_cache[inst_id], _ct_val_cache[inst_id]
    try:
        r = client._get('/api/v5/public/instruments', {'instId': inst_id, 'instType': 'SWAP'}, auth=False)
        if r.get('code') == '0' and r.get('data'):
            lot_sz = float(r['data'][0].get('lotSz', 1))
            ct_val = float(r['data'][0].get('ctVal', 1))
            _lot_size_cache[inst_id] = lot_sz
            _ct_val_cache[inst_id] = ct_val
            return lot_sz, ct_val
    except Exception:
        pass
    _lot_size_cache[inst_id] = 0.01
    _ct_val_cache[inst_id] = 1.0
    return 0.01, 1.0

def calc_lot_sz(notional_usd, price, lot_sz, ct_val):
    """根据名义价值计算张数（OKX合约sz是张数，不是币数）"""
    if ct_val <= 0 or price <= 0:
        return 0
    sz_raw = notional_usd / (ct_val * price)
    sz_adj = math.floor(sz_raw / lot_sz) * lot_sz
    if sz_adj < lot_sz:
        return 0
    decimals = len(str(lot_sz).split('.')[-1]) if '.' in str(lot_sz) else 0
    return round(sz_adj, decimals)


def run_poll_cycle():
    """执行一次轮询"""
    state = load_state()
    client = _get_okx_client()
    
    if not client:
        _log("OKX客户端不可用, 跳过本轮")
        save_state(state)
        return
    
    if check_monthly_rebuild(state):
        trigger_capital_rebuild(state, reason="月度定时优化（每月1号）")
    
    _log(f"=== 开始轮询 ({len(COINS)}币种) ===")
    
    # 异常信号监控（影子模式：只输出不决策）
    if BOUNCE_MONITOR_ENABLED:
        _log("--- 反弹潜力监控（影子模式）---")
        try:
            signal_result = monitor_bounce_signals(COINS, lookback=60, min_signals=1)
            if signal_result["highlighted_count"] > 0:
                for r in signal_result["highlighted"]:
                    triggers = ", ".join(r["triggered_list"])
                    _log(f"[{r['coin']}] 信号触发({triggers}): n_triggered={r['n_triggered']}")
                highlighted_coins = ", ".join([r["coin"] for r in signal_result["highlighted"]])
                _log(f"潜在高价值币种({signal_result['highlighted_count']}个): {highlighted_coins}")
            else:
                _log("无信号触发币种")
        except Exception as e:
            _log(f"信号监控异常: {e}")
        _log("--- 监控结束 ---")
    
    for coin in COINS:
        try:
            if coin in state["positions"]:
                pos = state["positions"][coin]
                
                if not check_take_profit(client, coin, pos, state):
                    if not check_time_exit(client, coin, pos, state):
                        execute_addon(client, coin, pos, state)
            else:
                decision = get_v15_decision(coin)
                action = decision.get("action", "WAIT")
                conf = decision.get("confidence", 0)

                if action == "OPEN_BULL" and conf >= 60:
                    _log(f"[{coin}] 信号触发: {action} conf={conf}%")
                    execute_open_position(client, coin, decision, state)
                else:
                    _log(f"[{coin}] 等待: {action} conf={conf}%")
            
            save_state(state)
            
        except Exception as e:
            _log(f"[{coin}] 轮询异常: {e}")
    
    win_rate = (state["total_wins"] / state["total_trades"] * 100) if state["total_trades"] > 0 else 0
    _log(f"=== 轮询完成 | 持仓:{len(state['positions'])} 总交易:{state['total_trades']} 胜率:{win_rate:.1f}% ===")
    save_state(state)


def main():
    _log(f"V15 经典马丁策略自动交易器启动")
    _log(f"  币种: {COINS}")
    _log(f"  轮询间隔: {POLL_INTERVAL}s")
    _log(f"  自动执行: {AUTO_EXECUTE}")
    _log(f"  最大加仓: {MAX_ADDONS}次")
    _log(f"  止盈: {BASE_TP_PCT:.0%}")
    
    def handle_signal(signum, frame):
        _log("收到退出信号, 保存状态...")
        state = load_state()
        save_state(state)
        sys.exit(0)
    
    sig_module.signal(sig_module.SIGINT, handle_signal)
    sig_module.signal(sig_module.SIGTERM, handle_signal)
    
    while True:
        try:
            run_poll_cycle()
        except Exception as e:
            _log(f"轮询周期异常: {e}")
        
        _log(f"等待 {POLL_INTERVAL}s 后下一轮...")
        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()