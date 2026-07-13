#!/usr/bin/env python3
"""
V15-CT 马丁策略自动交易器
- 定时轮询8个币种信号
- 根据资金计算器决定是否开仓
- 马丁加仓：最多3次，资金不足时禁止开新仓
- 只做多模式
"""
import json, os, sys, time, math, subprocess
import signal as sig_module
from datetime import datetime, timezone
from pathlib import Path

try:
    from config_loader import load_config, get_config, get_config_float, get_config_int, get_config_list, get_config_bool
    load_config("v15ct")
except Exception:
    pass

try:
    from bounce_potential_evaluator import evaluate_signals, monitor_bounce_signals, SIGNAL_THRESHOLDS, ACTIVE_SIGNALS
    BOUNCE_MONITOR_ENABLED = True
except ImportError:
    BOUNCE_MONITOR_ENABLED = False
    _log("警告: 无法导入 bounce_potential_evaluator, 信号监控功能禁用")

BASE_DIR = Path(__file__).parent
STATE_FILE = BASE_DIR / "data" / "v15ct_state.json"
LOG_DIR = BASE_DIR / "logs" / "v15ct"
LOG_DIR.mkdir(parents=True, exist_ok=True)
STATE_FILE.parent.mkdir(parents=True, exist_ok=True)

POLL_INTERVAL = int(get_config("V15CT_POLL_INTERVAL", "3600"))
AUTO_EXECUTE = str(get_config("V15CT_AUTO_EXECUTE", "true")).lower() == "true"
COINS = get_config_list("V15CT_COINS", default=["BTC", "ETH", "SOL", "ARB", "OP", "UNI", "HYPE", "OKB"])
MAX_ADDONS = get_config_int("MAX_ADDONS_PER_POSITION", 3)
BASE_TP_PCT = get_config_float("BASE_TP_PCT", 0.04)
CONFIDENCE_THRESHOLD = get_config_int("V15CT_CONFIDENCE_THRESHOLD", 60)
TEST_MODE = str(get_config("V15CT_TEST_MODE", "false")).lower() == "true"

# 三屏趋势过滤配置
TREND_FILTER_MODE = get_config("TREND_FILTER_MODE", "both_bear")
TREND_FILTER_PERIOD = get_config_int("TREND_FILTER_PERIOD", 104)


def _log(msg):
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    log_file = LOG_DIR / f"v15ct_{datetime.now(timezone.utc).strftime('%Y%m%d')}.log"
    with open(log_file, "a") as f:
        f.write(line + "\n")


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
        "consecutive_losses": 0,
        "daily_pnl": 0.0,
        "last_poll": "",
        "last_capital_rebuild": None,
    }


def save_state(state):
    state["last_poll"] = datetime.now(timezone.utc).isoformat()
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)


def _trigger_capital_rebuild(state):
    """连续亏损触发资金管理引擎重新优化（异步子进程）"""
    try:
        engine_script = str(BASE_DIR / "capital_manager_engine.py")
        log_file = str(BASE_DIR / "logs" / "capital_rebuild_triggered.log")
        subprocess.Popen(
            [sys.executable, engine_script, "monthly"],
            stdout=open(log_file, "a"),
            stderr=subprocess.STDOUT,
            cwd=str(BASE_DIR),
            start_new_session=True,
        )
        state["consecutive_losses"] = 0  # 重置计数
        state["last_capital_rebuild"] = datetime.now(timezone.utc).isoformat()
        _log(f"资金管理引擎已触发，日志: {log_file}")
    except Exception as e:
        _log(f"触发资金管理引擎失败: {e}")


def get_v15ct_decision(coin):
    """获取单个币种的V15-CT决策"""
    try:
        sys.path.insert(0, str(BASE_DIR))
        from v15ct_signal import v15_real_decision
        screen1 = {"spot_inst": f"{coin}-USDT"}
        return v15_real_decision(screen1, {})
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
    """执行开仓"""
    inst_id = f"{coin}-USDT-SWAP"
    conf = decision.get("confidence", 0)
    
    if conf < 60:
        _log(f"[{coin}] 置信度不足({conf}<60), 跳过")
        return False
    
    try:
        from capital_manager import calculate_capital_allocation
        alloc = calculate_capital_allocation()
        base_margin = alloc["single_position_cost"]["base_usd"]
        
        params = _get_dynamic_params(client, coin, "LONG")
        price = params["current_price"]
        if price <= 0:
            _log(f"[{coin}] 价格异常: {price}")
            return False
        
        if params["stop_loss_triggered"]:
            _log(f"[{coin}] 价格在所有均线下({params['stop_loss_type']})，熊市禁止开多仓")
            return False
        
        # 三屏趋势过滤：周线+日线双周期都看空时禁止做多
        tf = params.get("trend_filter", {})
        if tf.get("blocked", False):
            _log(f"[{coin}] 趋势过滤拦截: {tf.get('reason', '')}")
            return False
        
        tp_pct = params["take_profit_pct"]
        addon_pct = params["addon_pct"]
        sl_price = params["stop_loss_price"]
        sl_type = params["stop_loss_type"]
        
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
        _log(f"[{coin}] 开仓 LONG sz={sz}张 price={price} 保证金=${actual_margin:.2f} 名义=${actual_notional:.2f} TP={tp_pct*100:.2f}% SL={sl_type}@${sl_price} conf={conf}%")
        
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
    """执行加仓"""
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
        
        base_margin = alloc["single_position_cost"]["base_usd"]
        vol_mult = pos.get("vol_mult", 1.0)
        addon_margin = base_margin * vol_mult * (addon_pct * (addons + 1))
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
        _log(f"[{coin}] 加仓#{addons+1} sz={sz}张 price={current_price} 保证金=${actual_margin:.2f} 名义=${actual_notional:.2f} 开仓价=${open_price:.2f} 跌幅={drop_pct:.2%}")
        
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
                    state["total_trades"] += 1
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
                    state["total_trades"] += 1
                    state["consecutive_losses"] = state.get("consecutive_losses", 0) + 1
                    _log(f"[{coin}] 连续亏损: {state['consecutive_losses']}次")
                    del state["positions"][coin]
                    
                    # 连续亏损3次，触发资金管理引擎重新优化
                    if state["consecutive_losses"] >= 3:
                        _log(f"⚠️ 连续亏损{state['consecutive_losses']}次，触发资金管理引擎重新优化")
                        _trigger_capital_rebuild(state)
                    
                    return True
                else:
                    _log(f"[{coin}] 止损平仓失败: {r.get('error', r)}")
            return False
        
        return False
    except Exception as e:
        _log(f"[{coin}] 止盈止损检查异常: {e}")
        return False


ADDON_PCT_CHECK = get_config_float("ADDON_PCT", 0.08)
LEVERAGE = get_config_float("LEVERAGE", 10)

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
    """执行一次轮询（两阶段：先处理持仓，再按置信度排序开仓）"""
    state = load_state()
    client = _get_okx_client()
    
    if not client:
        _log("OKX客户端不可用, 跳过本轮")
        save_state(state)
        return
    
    _log(f"=== 开始轮询 ({len(COINS)}币种) ===")
    
    # 第一阶段：处理已有持仓（止盈/加仓/止损）
    _log("--- 阶段1: 处理持仓 ---")
    for coin in list(state["positions"].keys()):
        try:
            pos = state["positions"].get(coin)
            if not pos:
                continue
            if not check_take_profit(client, coin, pos, state):
                execute_addon(client, coin, pos, state)
        except Exception as e:
            _log(f"[{coin}] 持仓处理异常: {e}")
    
    save_state(state)
    
    # 第二阶段：收集所有未持仓币种的信号，按置信度排序开仓
    _log("--- 阶段2: 信号收集与排序开仓 ---")
    
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
    
    candidates = []
    for coin in COINS:
        if coin in state["positions"]:
            continue
        try:
            decision = get_v15ct_decision(coin)
            action = decision.get("action", "WAIT")
            conf = decision.get("confidence", 0)
            
            if action == "OPEN_BULL" and conf >= CONFIDENCE_THRESHOLD:
                params = _get_dynamic_params(client, coin, "LONG")
                if params["stop_loss_triggered"]:
                    _log(f"[{coin}] 信号触发但止损禁止({params['stop_loss_type']}), 跳过")
                    continue
                candidates.append({
                    "coin": coin,
                    "confidence": conf,
                    "decision": decision,
                })
                _log(f"[{coin}] 候选开仓: conf={conf}%")
            else:
                _log(f"[{coin}] 等待: {action} conf={conf}%")
        except Exception as e:
            _log(f"[{coin}] 信号获取异常: {e}")
    
    # 按置信度从高到低排序
    candidates.sort(key=lambda x: x["confidence"], reverse=True)
    
    if candidates:
        cand_str = ', '.join('{}({}%)'.format(c['coin'], c['confidence']) for c in candidates)
        _log(f"候选币种 {len(candidates)} 个，按置信度排序: {cand_str}")
    else:
        _log("本轮无符合条件的开仓信号")
    
    # 依次尝试开仓，直到资金不足或达到持仓上限
    for cand in candidates:
        coin = cand["coin"]
        conf = cand["confidence"]
        decision = cand["decision"]
        
        can_open, alloc = check_capital()
        if not can_open:
            _log(f"[{coin}] 资金/仓位不足，跳过后续候选")
            break
        
        _log(f"[{coin}] 尝试开仓 (conf={conf}%)")
        execute_open_position(client, coin, decision, state)
        save_state(state)
    
    win_rate = (state["total_wins"] / state["total_trades"] * 100) if state["total_trades"] > 0 else 0
    _log(f"=== 轮询完成 | 持仓:{len(state['positions'])} 总交易:{state['total_trades']} 胜率:{win_rate:.1f}% ===")
    save_state(state)


def main():
    import argparse
    parser = argparse.ArgumentParser(description="V15-CT 马丁策略自动交易器")
    parser.add_argument("--poll-once", action="store_true", help="只运行一轮轮询后退出（供 master_daemon 调用）")
    args = parser.parse_args()

    _log(f"V15-CT 马丁策略自动交易器启动")
    _log(f"  币种: {COINS}")
    _log(f"  轮询间隔: {POLL_INTERVAL}s")
    _log(f"  自动执行: {AUTO_EXECUTE}")
    _log(f"  最大加仓: {MAX_ADDONS}次")
    _log(f"  止盈: {BASE_TP_PCT:.0%}")
    _log(f"  止损: MA200动态止损")

    def handle_signal(signum, frame):
        _log("收到退出信号, 保存状态...")
        state = load_state()
        save_state(state)
        sys.exit(0)

    sig_module.signal(sig_module.SIGINT, handle_signal)
    sig_module.signal(sig_module.SIGTERM, handle_signal)

    if args.poll_once:
        # 单次模式：供 master_daemon 定时调用
        try:
            run_poll_cycle()
        except Exception as e:
            _log(f"轮询周期异常: {e}")
        return

    while True:
        try:
            run_poll_cycle()
        except Exception as e:
            _log(f"轮询周期异常: {e}")

        _log(f"等待 {POLL_INTERVAL}s 后下一轮...")
        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()