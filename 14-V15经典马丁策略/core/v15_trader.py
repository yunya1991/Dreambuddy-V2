#!/usr/bin/env python3
"""
V15 经典马丁策略自动交易器
- 定时轮询币种信号
- 根据资金计算器决定是否开仓
- 马丁加仓：最多3次，资金不足时禁止开新仓
- 多空双向：DirectionGate 根据日/周 MA200 控制方向开关
  - 做多：价格在日 MA200 上方（LONG_PREFERRED）
  - 做空：跌破日 MA200 但在周 MA200 上方（SHORT_ALLOWED，反向马丁）
  - 强制做多：跌至周 MA200（LONG_ONLY_FORCE，禁止做空）
"""
import json, os, sys, time, math, signal as sig_module, subprocess, threading
from datetime import datetime, timezone, timedelta
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(BASE_DIR / "lib"))
sys.path.insert(0, str(BASE_DIR / "core"))

# L4 TradeEvent 注册（跨系统统一交易记录）
try:
    _L4_ROOT = Path(__file__).resolve().parents[1] / "11-易经推理系统"
    if str(_L4_ROOT) not in sys.path:
        sys.path.insert(0, str(_L4_ROOT))
    from scripts.memory_l4.trade_event import TradeEvent
    from scripts.memory_l4.case_registry import UnifiedCaseRegistry
    _L4_ENABLED = True
except Exception as _e:
    _L4_ENABLED = False

try:
    from config_loader import load_config, get_config, get_config_float, get_config_int, get_config_list, get_config_bool
    load_config("v15")
except Exception:
    pass

# 统一交易对适配层（替代散落的 f"{coin}-USDT" / f"{coin}-USDT-SWAP" 硬编码）
try:
    from symbol_mapper import (
        to_spot, to_swap, is_supported as _coin_supported, get_category,
        is_martin_safe as _coin_martin_safe,
    )
except Exception:
    # 降级：保留原硬编码行为，保证向后兼容
    def to_spot(coin, exchange="okx"): return f"{coin}-USDT"
    def to_swap(coin, exchange="okx"): return f"{coin}-USDT-SWAP"
    def _coin_supported(coin, exchange="okx"): return True
    def get_category(coin): return "crypto"
    def _coin_martin_safe(coin, min_tier="mid", min_history_days=365): return True

try:
    from bounce_potential_evaluator import monitor_bounce_signals, evaluate_signals
    BOUNCE_MONITOR_ENABLED = True
except ImportError:
    BOUNCE_MONITOR_ENABLED = False

BOUNCE_FILTER_ENABLED = get_config_bool("BOUNCE_FILTER_ENABLED", False)
BOUNCE_MIN_SIGNALS = get_config_int("BOUNCE_MIN_SIGNALS", 1)

# 多空方向控制开关
V15_ALLOW_SHORT = str(get_config("V15_ALLOW_SHORT", "false")).lower() == "true"

STATE_FILE = BASE_DIR / "data" / "v15_state.json"
LOG_DIR = BASE_DIR / "logs" / "v15"
LOG_DIR.mkdir(parents=True, exist_ok=True)
STATE_FILE.parent.mkdir(parents=True, exist_ok=True)

POLL_INTERVAL = int(get_config("V15_POLL_INTERVAL", "3600"))
AUTO_EXECUTE = str(get_config("V15_AUTO_EXECUTE", "true")).lower() == "true"
# 币种池：从配置加载后，用 SymbolMapper 过滤出 OKX 支持的币种
_RAW_COINS = get_config_list("V15_COINS", default=["BTC", "ETH", "SOL", "ARB", "OP", "UNI", "HYPE", "OKB"])
_OKX_SUPPORTED = [c for c in _RAW_COINS if _coin_supported(c, "okx")] or _RAW_COINS
# ── 马丁策略风控过滤：市值等级 + 上线时间 ──
# min_tier: 最低市值等级 (large/mid/small)，默认 mid（剔除 small）
# min_history_days: 最小上线天数，默认 365 天（避免新币暴涨暴跌风险）
_MARTIN_MIN_TIER = str(get_config("V15_MARTIN_MIN_TIER", "mid")).lower()
_MARTIN_MIN_HISTORY_DAYS = get_config_int("V15_MARTIN_MIN_HISTORY_DAYS", 365)
COINS = [c for c in _OKX_SUPPORTED if _coin_martin_safe(c, _MARTIN_MIN_TIER, _MARTIN_MIN_HISTORY_DAYS)]
# 记录被风控剔除的币种（供启动日志输出）
_MARTIN_REJECTED = [c for c in _OKX_SUPPORTED if c not in COINS]
MAX_ADDONS = get_config_int("MAX_ADDONS_PER_POSITION", 3)
BASE_TP_PCT = get_config_float("BASE_TP_PCT", 0.04)
LEVERAGE = get_config_float("LEVERAGE", 5.0)

# ── 移动止盈参数（从贝叶斯优化活跃参数加载）──
def _load_trailing_params():
    """从 active_params.json 加载移动止盈参数，失败则用默认值"""
    try:
        from bayesian_optimizer import load_active_params
        params = load_active_params()
        return {
            "enabled": get_config_bool("V15_USE_TRAILING_TP", True),
            "atr_mult": params.get("trailing_atr_mult", 1.0),
            "start_ratio": params.get("trailing_start_ratio", 0.8),
        }
    except Exception:
        return {
            "enabled": get_config_bool("V15_USE_TRAILING_TP", True),
            "atr_mult": 1.0,
            "start_ratio": 0.8,
        }

_TRAILING = _load_trailing_params()


def _log(msg):
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    log_file = LOG_DIR / f"v15_{datetime.now(timezone.utc).strftime('%Y%m%d')}.log"
    with open(log_file, "a") as f:
        f.write(line + "\n")


def _register_martin_trade_to_l4(
    coin: str,
    pos: dict,
    exit_price: float,
    exit_reason: str,
    pnl: float = None,
    pnl_pct: float = None,
):
    """将马丁策略交易记录注册到 L4 统一案例库"""
    if not _L4_ENABLED:
        return None, False
    
    try:
        trade_id = f"martin_{int(datetime.now(timezone.utc).timestamp())}_{coin}"
        
        direction = pos.get("direction", "LONG")
        addons = pos.get("addons", 0)
        entry_price = pos.get("entry_price", 0)
        
        if pnl_pct is None:
            if direction == "SHORT":
                pnl_pct = (entry_price - exit_price) / entry_price if entry_price > 0 else 0
            else:
                pnl_pct = (exit_price - entry_price) / entry_price if entry_price > 0 else 0
        
        if pnl is None:
            pnl = pnl_pct * pos.get("sz", 0) * entry_price
        
        event = TradeEvent(
            event_id=TradeEvent.generate_event_id(),
            system_source="martin_v15",
            trade_id=trade_id,
            ts_entry=pos.get("open_time", datetime.now(timezone.utc).isoformat()),
            ts_exit=datetime.now(timezone.utc).isoformat(),
            symbol=pos.get("inst_id", to_swap(coin)),
            direction=direction.lower(),
            entry_price=entry_price,
            exit_price=exit_price,
            position_size=pos.get("sz", 0),
            pnl=pnl,
            pnl_pct=pnl_pct * 100 if abs(pnl_pct) < 10 else pnl_pct,
            exit_reason=exit_reason,
            decision_context={
                "addon_level": addons,
                "martin_config": {
                    "max_addons": MAX_ADDONS,
                    "base_tp_pct": BASE_TP_PCT,
                    "leverage": LEVERAGE,
                },
                "grid_params": pos.get("grid_params", {}),
                "take_profit_pct": pos.get("take_profit_pct"),
                "stop_loss_price": pos.get("stop_loss_price"),
            },
            market_snapshot={
                "regime": pos.get("regime", "unknown"),
                "volatility": pos.get("volatility", 0.02),
            },
            leverage=LEVERAGE,
            margin_usdt=pos.get("margin_usdt", 0),
        )
        
        registry = UnifiedCaseRegistry()
        case_id, success = registry.register_trade_event(event)
        
        if success:
            _log(f"[{coin}] L4 案例已注册: {case_id}")
        else:
            _log(f"[{coin}] L4 案例注册失败")
        
        return case_id, success
    except Exception as e:
        _log(f"[{coin}] L4 注册异常: {e}")
        return None, False


# ── 启动日志：币种池风控过滤结果 ──
_log(f"马丁策略币种池: 原始={len(_RAW_COINS)}个, OKX支持={len(_OKX_SUPPORTED)}个, "
     f"风控通过={len(COINS)}个 (min_tier={_MARTIN_MIN_TIER}, min_history_days={_MARTIN_MIN_HISTORY_DAYS})")
if _MARTIN_REJECTED:
    _log(f"马丁风控剔除币种({len(_MARTIN_REJECTED)}个): {','.join(_MARTIN_REJECTED)} - 原因: 小市值或上线时间不足")
_log(f"最终马丁币种池: {','.join(COINS)}")


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
    """获取单个币种的V15经典马丁策略决策（含多空方向控制）"""
    try:
        from v15_signal import v15_decision

        # 获取方向控制上下文
        direction_ctx = None
        if V15_ALLOW_SHORT:
            direction_ctx = _get_direction_ctx(coin)

        return v15_decision(to_spot(coin), direction_ctx=direction_ctx)
    except Exception as e:
        _log(f"[{coin}] 决策失败: {e}")
        return {"action": "WAIT", "confidence": 0, "reasons": [str(e)]}


def _get_direction_ctx(coin):
    """获取币种的多空方向控制上下文（含BTC风向标机制）"""
    try:
        from direction_gate import DirectionGate
        from strategy_params import get_coin_strategy_params, calc_daily_ma128

        # 先获取BTC的方向控制结果作为风向标
        btc_short_enabled = False
        if V15_ALLOW_SHORT:
            try:
                btc_params = get_coin_strategy_params("BTC", "LONG")
                if "error" not in btc_params:
                    btc_klines_1d = btc_params.get("klines_1d", [])
                    btc_daily_ma128 = calc_daily_ma128(btc_klines_1d)
                    if btc_daily_ma128 is not None:
                        btc_recent_closes = [float(k["c"]) for k in btc_klines_1d[-5:] if "c" in k]
                        btc_gate = DirectionGate(allow_short=True)
                        btc_result = btc_gate.evaluate(
                            current_price=btc_params["current_price"],
                            daily_ma128=btc_daily_ma128,
                            weekly_ma200=btc_params["stop_loss"].get("weekly_ma200"),
                            recent_daily_closes=btc_recent_closes,
                            btc_short_enabled=True,
                        )
                        btc_short_enabled = btc_result.short_enabled
            except Exception as e:
                _log(f"[BTC风向标] 获取失败: {e}")

        # 获取当前币种的方向控制
        params = get_coin_strategy_params(coin, "LONG")
        if "error" in params:
            return {"short_enabled": False, "long_enabled": True, "regime": "unknown"}

        # 计算当前币种的MA128
        klines_1d = params.get("klines_1d", [])
        daily_ma128 = calc_daily_ma128(klines_1d)
        recent_closes = [float(k["c"]) for k in klines_1d[-5:] if "c" in k]

        sl = params["stop_loss"]
        gate = DirectionGate(allow_short=True)
        result = gate.evaluate(
            current_price=params["current_price"],
            daily_ma128=daily_ma128,
            weekly_ma200=sl.get("weekly_ma200"),
            recent_daily_closes=recent_closes,
            btc_short_enabled=btc_short_enabled,
        )
        ctx = result.to_dict()
        ctx["btc_short_enabled"] = btc_short_enabled
        return ctx
    except Exception as e:
        _log(f"[{coin}] 方向控制评估失败: {e}, 默认只做多")
        return {"short_enabled": False, "long_enabled": True, "regime": "error"}


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
    """执行开仓 - 支持多空方向"""
    inst_id = to_swap(coin)
    conf = decision.get("confidence", 0)
    action = decision.get("action", "WAIT")

    # 判断多空方向
    is_short = (action == "OPEN_BEAR")
    direction = "SHORT" if is_short else "LONG"

    if conf < 60:
        _log(f"[{coin}] 置信度不足({conf}<60), 跳过")
        return False

    try:
        params = _get_dynamic_params(client, coin, direction)
        price = params["current_price"]
        if price <= 0:
            _log(f"[{coin}] 价格异常: {price}")
            return False

        effective_conf = conf
        if BOUNCE_FILTER_ENABLED and BOUNCE_MONITOR_ENABLED and not is_short:
            klines_4h = params.get("klines_4h")
            if klines_4h:
                bounce_signal = evaluate_signals(coin, klines_4h, lookback=60)
                if bounce_signal["valid"] and bounce_signal["n_triggered"] >= BOUNCE_MIN_SIGNALS:
                    triggers = ", ".join(bounce_signal["triggered_list"])
                    effective_conf = conf + bounce_signal["n_triggered"] * 10
                    _log(f"[{coin}] 反弹信号加持({triggers}): n_triggered={bounce_signal['n_triggered']}, 置信度从{conf}%增强至{effective_conf}%")
                else:
                    _log(f"[{coin}] 无反弹信号(n_triggered={bounce_signal.get('n_triggered', 0)})，保持原始置信度{conf}%")
            else:
                _log(f"[{coin}] 无4H K线数据，保持原始置信度{conf}%")
        else:
            _log(f"[{coin}] 反弹检测未启用或做空方向，保持原始置信度{conf}%")

        if params["stop_loss_triggered"]:
            _log(f"[{coin}] 止损触发({params['stop_loss_type']})，禁止开{direction}仓")
            return False

        tp_pct = params["take_profit_pct"]
        addon_pct = params["addon_pct"]
        sl_price = params["stop_loss_price"]
        sl_type = params["stop_loss_type"]

        # ── 智能资金分配（使用增强置信度）──
        from capital_manager import calculate_per_coin_allocation
        elder_ray = params.get("elder_ray")
        alloc = calculate_per_coin_allocation(coin, effective_conf, elder_ray)

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
        _log(f"[{coin}] 开仓 {direction} sz={sz}张 price={price} 保证金=${actual_margin:.2f} 名义=${actual_notional:.2f} "
             f"TP={tp_pct*100:.2f}% SL={sl_type}@${sl_price} conf={conf}% "
             f"资金分配: 趋势={adj.get('strength_mult', 1.0):.2f}x 置信={adj.get('conf_mult', 1.0):.2f}x "
             f"波动={adj.get('vol_adjust', 1.0):.2f}x 综合={adj.get('combined_mult', 1.0):.2f}x "
             f"EMA={adj.get('elder_ray_direction', 'N/A')} "
             f"Dir={adj.get('elder_ray_ema_trend', 'N/A')} "
             f"强度={adj.get('elder_ray_strength', 0):.1f}")

        if AUTO_EXECUTE:
            # 做空: side="sell", pos_side="short"; 做多: side="buy", pos_side="long"
            side = "sell" if is_short else "buy"
            pos_side = "short" if is_short else "long"
            r = client.place_order(
                inst_id=inst_id,
                side=side,
                sz=sz,
                td_mode="isolated",
                pos_side=pos_side,
            )
            if r.get("ok"):
                _log(f"[{coin}] 开仓成功: {r.get('data', {})}")
                state["positions"][coin] = {
                    "inst_id": inst_id,
                    "direction": direction,
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
                    # 移动止盈状态
                    "trailing_active": False,
                    "trailing_price": None,
                    "peak_price": price,
                }
                state["total_trades"] += 1
                _sync_tp_sl_orders(client, coin, state["positions"][coin], price, tp_pct, sl_price)
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
    """执行加仓 - 使用持仓时分配的加仓预算（支持多空方向）

    做多：价格下跌到加仓间距时加仓（经典马丁）
    做空：价格上涨到加仓间距时加仓（反向马丁）
    """
    inst_id = pos["inst_id"]
    addons = pos.get("addons", 0)
    direction = pos.get("direction", "LONG")
    is_short = (direction == "SHORT")

    if addons >= MAX_ADDONS:
        _log(f"[{coin}] 已达最大加仓次数({MAX_ADDONS})")
        return False

    try:
        from capital_manager import calculate_capital_allocation
        alloc = calculate_capital_allocation()
        if not alloc["recommendations"]["allow_addon"]:
            _log(f"[{coin}] 资金不足, 跳过加仓")
            return False

        params = _get_dynamic_params(client, coin, direction)
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
        target_pct = addon_pct * (addons + 1)
        if is_short:
            # 做空：价格上涨才加仓（反向马丁）
            move_pct = (current_price - open_price) / open_price
            if move_pct < target_pct:
                _log(f"[{coin}] 涨幅不足({move_pct:.2%}<{target_pct:.2%}), 跳过加空 (第{addons+1}层)")
                return False
        else:
            # 做多：价格下跌才加仓（经典马丁）
            move_pct = (open_price - current_price) / open_price
            if move_pct < target_pct:
                _log(f"[{coin}] 跌幅不足({move_pct:.2%}<{target_pct:.2%}), 跳过加仓 (第{addons+1}层)")
                return False

        lot_sz, ct_val = get_contract_info(client, inst_id)
        sz = calc_lot_sz(addon_notional, current_price, lot_sz, ct_val)
        if sz < lot_sz:
            _log(f"[{coin}] 加仓数量({sz}张)小于最小单位({lot_sz}张), 跳过")
            return False

        actual_notional = sz * ct_val * current_price
        actual_margin = actual_notional / LEVERAGE
        move_label = "涨幅" if is_short else "跌幅"
        _log(f"[{coin}] 加仓#{addons+1} {direction} sz={sz}张 price={current_price} 保证金=${actual_margin:.2f} 名义=${actual_notional:.2f} "
             f"开仓价=${open_price:.2f} {move_label}={move_pct:.2%} 预算=${addon_usd:.2f}")

        if AUTO_EXECUTE:
            # 做空加仓: side="sell", pos_side="short"; 做多加仓: side="buy", pos_side="long"
            side = "sell" if is_short else "buy"
            pos_side = "short" if is_short else "long"
            r = client.place_order(
                inst_id=inst_id,
                side=side,
                sz=sz,
                td_mode="isolated",
                pos_side=pos_side,
            )
            if r.get("ok"):
                pos["addons"] = addons + 1
                pos["entry_price"] = (pos["entry_price"] * pos["sz"] + current_price * sz) / (pos["sz"] + sz)
                pos["sz"] += sz
                pos["last_addon_time"] = datetime.now(timezone.utc).isoformat()
                _log(f"[{coin}] 加仓成功, 总仓位={pos['sz']} 均价=${pos['entry_price']:.2f}")
                tp_pct = pos.get("take_profit_pct", addon_pct)
                sl_price = pos.get("stop_loss_price", params.get("stop_loss_price"))
                _sync_tp_sl_orders(client, coin, pos, pos["entry_price"], tp_pct, sl_price)
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
        "klines_4h": params.get("klines_4h"),
    }


def _sync_tp_sl_orders(client, coin, pos, entry_price, tp_pct, sl_price):
    """同步设置/更新 OCO 止盈止损条件单

    开仓后立即调用，加仓后再次调用（先取消旧单，再下新单）。
    挂单止盈止损 + 软件监控止盈止损双重保障。

    Args:
        client: OKX 客户端
        coin: 币种
        pos: 持仓信息 dict
        entry_price: 当前均价
        tp_pct: 止盈比例（小数，如 0.04 = 4%）
        sl_price: 止损价格（None 表示不设止损）
    """
    if not AUTO_EXECUTE:
        return

    inst_id = pos["inst_id"]
    direction = pos.get("direction", "LONG")
    is_short = (direction == "SHORT")
    pos_side = "short" if is_short else "long"

    try:
        # 止盈价
        if is_short:
            tp_price = entry_price * (1 - tp_pct)
        else:
            tp_price = entry_price * (1 + tp_pct)

        # 先取消旧的条件单，避免多单冲突
        client.cancel_algo_orders(inst_id)

        # 止损价校验：必须与方向一致
        valid_sl = sl_price is not None and sl_price > 0
        if valid_sl:
            if is_short and sl_price <= entry_price:
                valid_sl = False
            if not is_short and sl_price >= entry_price:
                valid_sl = False

        if valid_sl:
            r = client.place_stop_loss_take_profit(
                inst_id=inst_id,
                pos_side=pos_side,
                stop_loss_px=sl_price,
                take_profit_px=tp_price,
                sz=pos["sz"],
                reason=f"v15_{direction.lower()}_tp_sl_sync",
            )
            if r.get("ok"):
                _log(f"[{coin}] {direction} OCO止盈止损挂单成功 TP=${tp_price:.4f} SL=${sl_price:.4f} sz={pos['sz']}")
            else:
                _log(f"[{coin}] {direction} OCO止盈止损挂单失败: {r.get('error', r)}")
        else:
            # 止损价无效时，只挂止盈单
            r = client.place_stop_loss_take_profit(
                inst_id=inst_id,
                pos_side=pos_side,
                take_profit_px=tp_price,
                sz=pos["sz"],
                reason=f"v15_{direction.lower()}_tp_only",
            )
            if r.get("ok"):
                _log(f"[{coin}] {direction} 仅止盈挂单成功 TP=${tp_price:.4f} sz={pos['sz']}")
            else:
                _log(f"[{coin}] {direction} 仅止盈挂单失败: {r.get('error', r)}")
    except Exception as e:
        _log(f"[{coin}] 止盈止损挂单异常: {e}")


def _update_tp_sl_dynamic(client, coin, pos):
    """每次轮询动态检查并更新止盈止损挂单

    当止盈/止损价格发生显著变化时（如动态止损线移动），
    重新同步挂单，确保挂单与策略计算一致。

    变化阈值：止损价变动 > 0.5% 或止盈价变动 > 0.5% 时才更新，避免频繁撤单。
    """
    if not AUTO_EXECUTE:
        return

    direction = pos.get("direction", "LONG")
    try:
        params = _get_dynamic_params(client, coin, direction)
        current_price = params["current_price"]
        tp_pct = pos.get("take_profit_pct", params["take_profit_pct"])
        sl_price = params["stop_loss_price"]
        if current_price <= 0:
            return

        entry_price = pos["entry_price"]
        last_sl = pos.get("last_sl_price")
        last_tp = pos.get("last_tp_price")

        # 计算当前止盈价
        is_short = (direction == "SHORT")
        if is_short:
            current_tp = entry_price * (1 - tp_pct)
        else:
            current_tp = entry_price * (1 + tp_pct)

        # 判断是否需要更新
        need_update = False
        if last_sl is None or last_tp is None:
            need_update = True
        else:
            if sl_price and last_sl and last_sl > 0:
                sl_change = abs(sl_price - last_sl) / last_sl
                if sl_change > 0.005:
                    need_update = True
            elif (sl_price is None) != (last_sl is None):
                need_update = True
            if last_tp and last_tp > 0:
                tp_change = abs(current_tp - last_tp) / last_tp
                if tp_change > 0.005:
                    need_update = True

        if need_update:
            _sync_tp_sl_orders(client, coin, pos, entry_price, tp_pct, sl_price)
            pos["last_sl_price"] = sl_price
            pos["last_tp_price"] = current_tp
    except Exception as e:
        _log(f"[{coin}] 动态更新止盈止损异常: {e}")


def check_take_profit(client, coin, pos, state):
    """检查止盈（含移动止盈）和动态止损（支持多空方向）

    做多：价格上涨到止盈线盈利；止损线在价格下方
    做空：价格下跌到止盈线盈利；止损线在价格上方

    止盈优先级：
      1. 移动止盈（启用且激活时）：价格从峰值回撤 N×ATR → 止盈
      2. 固定止盈：profit_pct >= tp_pct（使用 pos 中 RAISE_TP 提高后的值）
    """
    inst_id = pos["inst_id"]
    direction = pos.get("direction", "LONG")
    is_short = (direction == "SHORT")
    try:
        params = _get_dynamic_params(client, coin, direction)
        current_price = params["current_price"]
        if current_price <= 0:
            return False

        entry_price = pos["entry_price"]
        if is_short:
            profit_pct = (entry_price - current_price) / entry_price
        else:
            profit_pct = (current_price - entry_price) / entry_price

        # 使用 pos 中保存的 tp_pct（RAISE_TP 提高后的值），回退到动态计算值
        tp_pct = pos.get("take_profit_pct", params["take_profit_pct"])
        sl_price = params["stop_loss_price"]
        sl_type = params["stop_loss_type"]
        sl_triggered = params["stop_loss_triggered"]

        # ── 移动止盈检查（在固定止盈之前）──
        if _TRAILING["enabled"] and profit_pct > 0:
            klines_4h = params.get("klines_4h")
            atr_pct = None
            if klines_4h:
                try:
                    from strategy_params import calc_atr_pct
                    atr_pct = calc_atr_pct(klines_4h)
                except Exception:
                    pass

            if atr_pct and atr_pct > 0:
                atr_price = current_price * (atr_pct / 100)
                start_threshold = tp_pct * _TRAILING["start_ratio"]

                # 更新峰值价格
                if is_short:
                    peak = min(pos.get("peak_price", entry_price), current_price)
                else:
                    peak = max(pos.get("peak_price", entry_price), current_price)
                pos["peak_price"] = peak

                # 计算峰值浮盈
                if is_short:
                    peak_profit_pct = (entry_price - peak) / entry_price
                else:
                    peak_profit_pct = (peak - entry_price) / entry_price

                # 浮盈达到启动阈值 → 激活移动止盈
                if peak_profit_pct >= start_threshold:
                    if is_short:
                        new_trailing = peak + _TRAILING["atr_mult"] * atr_price
                        # 做空：移动止盈价只下移不上移
                        if pos.get("trailing_price") is None or new_trailing < pos["trailing_price"]:
                            pos["trailing_price"] = new_trailing
                            _log(f"[{coin}] 移动止盈激活 peak={peak:.4g} trailing={new_trailing:.4g} ATR={atr_pct:.2f}%")
                    else:
                        new_trailing = peak - _TRAILING["atr_mult"] * atr_price
                        # 做多：移动止盈价只上移不下移
                        if pos.get("trailing_price") is None or new_trailing > pos["trailing_price"]:
                            pos["trailing_price"] = new_trailing
                            _log(f"[{coin}] 移动止盈激活 peak={peak:.4g} trailing={new_trailing:.4g} ATR={atr_pct:.2f}%")
                    pos["trailing_active"] = True

                # 检查移动止盈触发
                trailing_price = pos.get("trailing_price")
                if pos.get("trailing_active") and trailing_price is not None:
                    if (not is_short and current_price <= trailing_price) or \
                       (is_short and current_price >= trailing_price):
                        _log(f"[{coin}] {direction} 移动止盈触发 price=${current_price:.4g} 回撤至 trailing=${trailing_price:.4g} "
                             f"(peak=${peak:.4g}, profit={profit_pct:.2%})")
                        if AUTO_EXECUTE:
                            client.cancel_algo_orders(inst_id)
                            lot_sz, ct_val = get_contract_info(client, inst_id)
                            close_sz = math.floor(pos["sz"] / lot_sz) * lot_sz
                            decimals = len(str(lot_sz).split('.')[-1]) if '.' in str(lot_sz) else 0
                            close_sz = round(close_sz, decimals)
                            side = "buy" if is_short else "sell"
                            pos_side = "short" if is_short else "long"
                            r = client.place_order(
                                inst_id=inst_id, side=side, sz=close_sz,
                                td_mode="isolated", pos_side=pos_side,
                            )
                            if r.get("ok"):
                                _log(f"[{coin}] 移动止盈平仓成功")
                                state["total_wins"] += 1
                                state["consecutive_losses"] = 0
                                del state["positions"][coin]
                                return True
                            else:
                                _log(f"[{coin}] 移动止盈平仓失败: {r.get('error', r)}")
                        return False

        # ── 固定止盈检查 ──
        if profit_pct >= tp_pct:
            _log(f"[{coin}] {direction} 止盈触发 profit={profit_pct:.2%} >= {tp_pct:.2%}")

            if AUTO_EXECUTE:
                client.cancel_algo_orders(inst_id)
                lot_sz, ct_val = get_contract_info(client, inst_id)
                close_sz = math.floor(pos["sz"] / lot_sz) * lot_sz
                decimals = len(str(lot_sz).split('.')[-1]) if '.' in str(lot_sz) else 0
                close_sz = round(close_sz, decimals)
                # 做空平仓: side="buy", pos_side="short"; 做多平仓: side="sell", pos_side="long"
                side = "buy" if is_short else "sell"
                pos_side = "short" if is_short else "long"
                r = client.place_order(
                    inst_id=inst_id,
                    side=side,
                    sz=close_sz,
                    td_mode="isolated",
                    pos_side=pos_side,
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
            if is_short:
                if sl_price is not None:
                    _log(f"[{coin}] {direction} 动态止损触发({sl_type}) 价格=${current_price:.2f} >= 止损线=${sl_price:.2f}")
                else:
                    _log(f"[{coin}] {direction} 动态止损触发({sl_type}) 价格涨破所有均线，无条件止损")
            else:
                if sl_price is not None:
                    _log(f"[{coin}] {direction} 动态止损触发({sl_type}) 价格=${current_price:.2f} <= 止损线=${sl_price:.2f}")
                else:
                    _log(f"[{coin}] {direction} 动态止损触发({sl_type}) 价格跌破所有均线，无条件止损")

            if AUTO_EXECUTE:
                client.cancel_algo_orders(inst_id)
                lot_sz, ct_val = get_contract_info(client, inst_id)
                close_sz = math.floor(pos["sz"] / lot_sz) * lot_sz
                decimals = len(str(lot_sz).split('.')[-1]) if '.' in str(lot_sz) else 0
                close_sz = round(close_sz, decimals)
                side = "buy" if is_short else "sell"
                pos_side = "short" if is_short else "long"
                r = client.place_order(
                    inst_id=inst_id,
                    side=side,
                    sz=close_sz,
                    td_mode="isolated",
                    pos_side=pos_side,
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
        direction = pos.get("direction", "LONG")
        is_short = (direction == "SHORT")
        params = _get_dynamic_params(client, coin, direction)
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
            if is_short:
                # 做空：价格下跌盈利（经典指标系统内部 pnl_eff = unrealized_pnl_pct × leverage）
                unrealized_pnl_pct = (entry_price - current_price) / entry_price
            else:
                # 做多：价格上涨盈利（经典指标系统内部 pnl_eff = unrealized_pnl_pct × leverage）
                unrealized_pnl_pct = (current_price - entry_price) / entry_price

            pos_state = PositionState(
                coin=coin,
                side="short" if is_short else "long",
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
            # 同步更新交易所 OCO 挂单（撤销旧单 → 下新止盈价单）
            sl_price = params.get("stop_loss_price")
            _sync_tp_sl_orders(client, coin, pos, pos["entry_price"], capped_tp, sl_price)
            _log(f"[{coin}] 经典评估: RAISE_TP ({decision.reason}) "
                 f"新止盈={capped_tp:.2%} (原={original_tp:.2%}), OCO挂单已同步")
            return False

        else:  # hold
            _log(f"[{coin}] 经典评估: HOLD ({decision.reason})")
            return False

    except Exception as e:
        _log(f"[{coin}] 超时离场检查异常: {e}")
        return False


def _execute_close_position(client, coin, pos, state, reason="", exit_price=None):
    """平仓（支持多空方向）- 平仓前取消所有条件单"""
    inst_id = pos["inst_id"]
    direction = pos.get("direction", "LONG")
    is_short = (direction == "SHORT")
    try:
        if AUTO_EXECUTE:
            client.cancel_algo_orders(inst_id)

        lot_sz, ct_val = get_contract_info(client, inst_id)
        close_sz = math.floor(pos["sz"] / lot_sz) * lot_sz
        decimals = len(str(lot_sz).split('.')[-1]) if '.' in str(lot_sz) else 0
        close_sz = round(close_sz, decimals)

        if AUTO_EXECUTE:
            # 做空平仓: side="buy", pos_side="short"; 做多平仓: side="sell", pos_side="long"
            side = "buy" if is_short else "sell"
            pos_side = "short" if is_short else "long"
            r = client.place_order(
                inst_id=inst_id,
                side=side,
                sz=close_sz,
                td_mode="isolated",
                pos_side=pos_side,
            )
            if r.get("ok"):
                _log(f"[{coin}] {direction} 平仓成功 ({reason})")
                state["consecutive_losses"] = state.get("consecutive_losses", 0) + 1
                if coin in state["positions"]:
                    # 注册到 L4
                    _register_martin_trade_to_l4(
                        coin=coin,
                        pos=pos,
                        exit_price=exit_price or pos.get("entry_price", 0),
                        exit_reason=reason,
                    )
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
    """减仓（供 check_time_exit 调用，支持多空方向）"""
    inst_id = pos["inst_id"]
    direction = pos.get("direction", "LONG")
    is_short = (direction == "SHORT")
    try:
        lot_sz, ct_val = get_contract_info(client, inst_id)
        reduce_sz = math.floor((pos["sz"] * reduce_frac) / lot_sz) * lot_sz
        decimals = len(str(lot_sz).split('.')[-1]) if '.' in str(lot_sz) else 0
        reduce_sz = round(reduce_sz, decimals)

        if reduce_sz < lot_sz:
            _log(f"[{coin}] 减仓数量({reduce_sz})小于最小单位({lot_sz}), 跳过")
            return False

        if AUTO_EXECUTE:
            # 做空减仓: side="buy", pos_side="short"; 做多减仓: side="sell", pos_side="long"
            side = "buy" if is_short else "sell"
            pos_side = "short" if is_short else "long"
            r = client.place_order(
                inst_id=inst_id,
                side=side,
                sz=reduce_sz,
                td_mode="isolated",
                pos_side=pos_side,
            )
            if r.get("ok"):
                pos["sz"] -= reduce_sz
                _log(f"[{coin}] {direction} 减仓成功 frac={reduce_frac:.0%} sz={reduce_sz} 剩余={pos['sz']}")
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


def run_light_poll_cycle():
    """轻量轮询：只同步持仓状态+盈亏，不做交易决策

    用途：
    - 每5分钟执行一次，同步交易所真实持仓到state
    - 检测外部平仓（手动操作等）
    - 更新持仓盈亏信息（current_price, unrealized_pnl, profit_pct）
    - 为1小时完整轮询提供准确的持仓状态，避免策略基于过期持仓做决策

    与完整轮询的区别：
    - 不做信号计算（不调用 get_v15_decision）
    - 不执行交易（不开仓、不加仓、不平仓）
    - 不挂OCO条件单
    - 只查仓+对比+更新state

    防误删保护：
    - API 调用失败（限流/网络）时，保留 state 中的持仓记录，不视为"外部平仓"
    - 只有 API 明确返回成功且持仓数为 0 时，才判定为外部平仓
    """
    state = load_state()
    client = _get_okx_client()

    if not client:
        _log("[轻量轮询] OKX客户端不可用, 跳过")
        return

    _log("=== 轻量轮询开始 ===")

    # 单次 API 拉取账户所有持仓（避免 30 次循环触发 OKX 限流）
    all_resp = client.get_all_positions()
    api_ok = all_resp.get("ok", False)
    exchange_positions = all_resp.get("positions", {}) if api_ok else {}

    if not api_ok:
        # API 失败 — 保留 state 原状，只更新 last_poll
        _log(f"[轻量轮询] ⚠️ 持仓查询失败: {all_resp.get('error', 'unknown')} — 保留 state 原状，不删除任何持仓")
        state["last_poll"] = datetime.now(timezone.utc).isoformat()
        save_state(state)
        remaining = list(state.get("positions", {}).keys())
        _log(f"=== 轻量轮询完成(降级) | 持仓:{len(remaining)} (state 未变更) ===")
        for coin in remaining:
            pos = state["positions"][coin]
            pnl = pos.get("unrealized_pnl", 0)
            pnl_pct = pos.get("profit_pct", 0)
            _log(f"  [{coin}] mark=${pos.get('current_price', 0):.4f} pnl=${pnl:.2f} ({pnl_pct:+.2%}) [stale]")
        return

    state_positions = set(state.get("positions", {}).keys())
    exchange_pos_keys = set(exchange_positions.keys())

    # 1. state中有但交易所没有 → 外部平仓（手动操作等）
    externally_closed = state_positions - exchange_pos_keys
    for coin in externally_closed:
        pos = state["positions"][coin]
        _log(f"[{coin}] ⚠️ 检测到外部平仓: entry={pos['entry_price']} sz={pos['sz']}")
        # 注册外部平仓到 L4
        _register_martin_trade_to_l4(
            coin=coin,
            pos=pos,
            exit_price=pos.get("current_price", pos.get("entry_price", 0)),
            exit_reason="external_close",
        )
        del state["positions"][coin]

    # 2. 交易所中有但state中没有 → 外部开仓（策略不负责，仅记录）
    externally_opened = exchange_pos_keys - state_positions
    for coin in externally_opened:
        p = exchange_positions[coin]
        _log(f"[{coin}] ⚠️ 检测到外部开仓: avg_px={p['avg_px']:.4f} pos={p['pos']} upl={p['upl']:.2f}")

    # 3. 两边都有 → 更新盈亏信息
    for coin in (state_positions & exchange_pos_keys):
        p = exchange_positions[coin]
        pos = state["positions"][coin]
        pos["current_price"] = p.get("mark_px", 0)
        pos["unrealized_pnl"] = p.get("upl", 0)
        pos["upl_ratio"] = p.get("upl_ratio", 0)

        # 计算盈亏百分比
        entry = pos.get("entry_price", 0)
        mark = p.get("mark_px", 0)
        if entry > 0 and mark > 0:
            direction = pos.get("direction", "LONG")
            if direction == "SHORT":
                profit_pct = (entry - mark) / entry
            else:
                profit_pct = (mark - entry) / entry
            pos["profit_pct"] = profit_pct

    state["last_poll"] = datetime.now(timezone.utc).isoformat()
    save_state(state)

    # 输出监控摘要
    remaining = list(state.get("positions", {}).keys())
    _log(f"=== 轻量轮询完成 | 持仓:{len(remaining)} 外部平仓:{len(externally_closed)} 外部开仓:{len(externally_opened)} ===")
    if remaining:
        for coin in remaining:
            pos = state["positions"][coin]
            pnl = pos.get("unrealized_pnl", 0)
            pnl_pct = pos.get("profit_pct", 0)
            _log(f"  [{coin}] mark=${pos.get('current_price', 0):.4f} pnl=${pnl:.2f} ({pnl_pct:+.2%})")


def run_poll_cycle():
    """执行一次完整轮询（信号计算+交易执行）"""
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

                # 兼容旧持仓：补充移动止盈状态字段
                if "trailing_active" not in pos:
                    pos["trailing_active"] = False
                    pos["trailing_price"] = None
                    pos["peak_price"] = pos.get("entry_price", 0)

                if not check_take_profit(client, coin, pos, state):
                    if not check_time_exit(client, coin, pos, state):
                        added = execute_addon(client, coin, pos, state)
                        if not added:
                            _update_tp_sl_dynamic(client, coin, pos)
            else:
                decision = get_v15_decision(coin)
                action = decision.get("action", "WAIT")
                conf = decision.get("confidence", 0)

                # 支持多空开仓信号：OPEN_BULL（做多）和 OPEN_BEAR（做空）
                if action in ("OPEN_BULL", "OPEN_BEAR") and conf >= 60:
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
    _log(f"  允许做空: {V15_ALLOW_SHORT}")
    
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