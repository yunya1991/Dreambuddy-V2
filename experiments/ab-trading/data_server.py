#!/usr/bin/env python3
"""
监控页面数据服务器 — 提供 /api/state 接口
启动：python3 data_server.py
访问：http://localhost:8765
"""
import json, os, requests, warnings, subprocess, subprocess, sys
from datetime import datetime
from pathlib import Path
from http.server import HTTPServer, ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qsl

warnings.filterwarnings("ignore")
BASE_DIR = Path(__file__).parent
LOG_A    = BASE_DIR / "logs" / "agent_a"
LOG_B    = BASE_DIR / "logs" / "agent_b"
PORT     = 8765
USER     = "0x93842F1ea62E7E3c71494d9EA69EfC4F2D6e9934"

# 易经大模型仓库路径
BCRM_REPO = Path(os.environ.get(
    "BCRM_REPO",
    "/Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/11-易经推理系统",
))


def get_yijing_state():
    """调用 ab_bridge 获取易经推理模型数据"""
    try:
        result = subprocess.run(
            ["python3", "-m", "scripts.memory_l4.ab_bridge", "yijing-status"],
            capture_output=True, text=True, timeout=60,
            cwd=str(BCRM_REPO),
        )
        if result.returncode == 0:
            return json.loads(result.stdout)
        return {"error": result.stderr[:500]}
    except Exception as e:
        return {"error": str(e)}

# ── 易经推理交易状态（持仓/余额/Algo单）─────────────────────────────
YIJING_TRADE_AVAILABLE = False
try:
    _yj_trade_path = str(BCRM_REPO)
    if _yj_trade_path not in sys.path:
        sys.path.insert(0, _yj_trade_path)
    from scripts.memory_l4.okx_simulated import OKXSimulatedClient
    YIJING_TRADE_AVAILABLE = True
except Exception:
    YIJING_TRADE_AVAILABLE = False


def get_yijing_trading_state():
    """查询易经推理系统的交易状态（持仓/余额/Algo单/绩效）"""
    if not YIJING_TRADE_AVAILABLE:
        return {"error": "okx_simulated not available"}
    try:
        client = OKXSimulatedClient()
        has_creds = client._has_credentials()
        result = {
            "connection_ok": has_creds,
            "dry_run": client.dry_run,
            "simulated": client.simulated,
        }
        if has_creds:
            result["balance"] = client.get_balance()
            result["positions"] = client.get_positions()
            result["algo_orders"] = client.get_algo_orders()
            result["performance"] = client.get_performance_summary()
        return result
    except Exception as e:
        return {"error": str(e)}


sys.path.insert(0, str(BASE_DIR))
try:
    from screen_engine import get_all as get_screen_data
    SCREEN_AVAILABLE = True
except ImportError:
    SCREEN_AVAILABLE = False


def load_v15ct_state():
    state_file = BASE_DIR / "data" / "v15ct_state.json"
    if state_file.exists():
        try:
            with open(state_file) as f:
                return json.load(f)
        except Exception:
            pass
    return {
        "positions": {},
        "total_trades": 0,
        "total_wins": 0,
        "auto_execute": False,
    }


def get_v15ct_real_positions():
    """从OKX实盘获取V15-CT相关持仓并同步状态"""
    try:
        sys.path.insert(0, str(BASE_DIR))
        from v15ct_trader import _get_okx_client, COINS
        local_state = load_v15ct_state()
        local_positions = local_state.get("positions", {})
        client = _get_okx_client()
        if not client:
            return {}
        result = {}
        for coin in COINS:
            inst_id = f"{coin}-USDT-SWAP"
            try:
                r = client.get_positions(inst_id)
                if r.get("ok"):
                    pos_data = r.get("positions", r.get("data", []))
                    for p in pos_data:
                        pos_sz = float(p.get("pos", p.get("pos_sz", 0)))
                        if pos_sz != 0:
                            pos_side = p.get("pos_side", "net")
                            is_long = pos_side == "long" or (pos_side == "net" and pos_sz > 0)
                            local_pos = local_positions.get(coin, {})
                            result[coin] = {
                                "symbol": coin,
                                "inst_id": inst_id,
                                "direction": "LONG" if is_long else "SHORT",
                                "pos_side": pos_side,
                                "sz": abs(pos_sz),
                                "entry_price": float(p.get("avg_px", p.get("avg_entry_px", 0)) or 0),
                                "mark_price": float(p.get("mark_px", 0) or 0),
                                "upl": float(p.get("upl", p.get("unrealized_pnl", 0)) or 0),
                                "upl_ratio": float(p.get("upl_ratio", 0) or 0),
                                "lever": p.get("lever", ""),
                                "addons": local_pos.get("addons", 0),
                                "confidence": local_pos.get("confidence", 0),
                                "open_time": local_pos.get("open_time", ""),
                            }
            except Exception:
                continue
        return result
    except Exception as e:
        return {"error": str(e)}


def load_logs(log_dir: Path, limit: int = 30):
    logs = []
    if not log_dir.exists():
        return logs
    for f in sorted(log_dir.glob("*.json"))[-limit:]:
        try:
            with open(f) as fp:
                d = json.load(fp)
                # 提取 coin 字段（agent_a 日志里可能在不同位置）
                if "coin" not in d and d.get("entry_price"):
                    pass  # keep as-is
                logs.append(d)
        except Exception:
            pass
    return logs


USER_A = "0x93842F1ea62E7E3c71494d9EA69EfC4F2D6e9934"   # Agent A 主账户
USER_B = "0x6632da9c91A959eEBf1343f8AFAbf2807414004A"   # Agent B 子账户


def get_perp_state(user: str) -> dict:
    s = requests.Session(); s.trust_env = False
    try:
        r = s.post("https://api.hyperliquid.xyz/info",
                   json={"type": "clearinghouseState", "user": user}, timeout=8).json()
    except Exception as e:
        return {"equity": 0, "avail": 0, "positions": [], "error": str(e)}
    m = r.get("marginSummary", {})
    positions = []
    for p in r.get("assetPositions", []):
        pos = p.get("position", {})
        if float(pos.get("szi", 0)) != 0:
            positions.append({
                "coin":     pos.get("coin"),
                "size":     float(pos.get("szi", 0)),
                "entry_px": float(pos.get("entryPx") or 0),
                "upnl":     float(pos.get("unrealizedPnl") or 0),
                "leverage": float((pos.get("leverage") or {}).get("value", 1)),
            })
    equity = float(m.get("accountValue", 0))
    avail  = float(m.get("marginAvailable") or 0)

    # 统一账户模式：合约权益为0时，查现货 USDC 余额补充
    if equity == 0:
        try:
            r2 = s.post("https://api.hyperliquid.xyz/info",
                        json={"type": "spotClearinghouseState", "user": user}, timeout=8).json()
            spot_usdc = next(
                (float(b["total"]) for b in r2.get("balances", []) if b.get("coin") == "USDC"), 0
            )
            if spot_usdc > 0:
                equity = spot_usdc
                avail  = spot_usdc
        except Exception:
            pass

    return {
        "equity":    equity,
        "avail":     avail,
        "positions": positions,
    }


def get_hl_state():
    a = get_perp_state(USER_A)
    b = get_perp_state(USER_B)
    return {
        # Agent A
        "perp_equity":    a["equity"],
        "perp_avail":     a["avail"],
        "perp_positions": a["positions"],
        # Agent B
        "b_equity":       b["equity"],
        "b_avail":        b["avail"],
        "b_positions":    b["positions"],
        # 合计
        "spot_usdc":      0,  # 已全部转入合约
        "total_equity":   a["equity"] + b["equity"],
    }


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass  # 静默日志

    def do_GET(self):
        path = urlparse(self.path).path

        # ── API: 完整状态 ───────────────────────────────────────────────
        if path == "/api/state":
            hl = get_hl_state()
            data = {
                **hl,
                "logs_a": load_logs(LOG_A),
                "logs_b": load_logs(LOG_B),
            }
            self._json(data)

        # ── API: V15-CT 状态 ──────────────────────────────────────────
        elif path == "/api/v15-ct/status":
            try:
                sys.path.insert(0, str(BASE_DIR))
                state = load_v15ct_state()
                real_positions = get_v15ct_real_positions()
                v15_ct_positions = []
                for coin, pos in real_positions.items():
                    if isinstance(pos, dict) and "error" not in pos:
                        v15_ct_positions.append(pos)
                state["v15_ct_positions"] = v15_ct_positions
                state["position_count"] = len(v15_ct_positions)
                from v15ct_trader import AUTO_EXECUTE
                state["auto_execute"] = AUTO_EXECUTE
                self._json(state)
            except Exception as e:
                self._json({"error": str(e)})

        # ── API: V15-CT 单个币种决策 ──────────────────────────────────
        elif path == "/api/v15-ct/decision":
            try:
                sys.path.insert(0, str(BASE_DIR))
                from v15ct_trader import get_v15ct_decision, _get_dynamic_params, _get_okx_client
                coin = self._get_query_param("coin") or "BTC"
                decision = get_v15ct_decision(coin) or {}
                client = _get_okx_client()
                try:
                    params = _get_dynamic_params(client, coin, "LONG")
                    decision["stop_loss_type"] = params.get("stop_loss_type")
                    decision["stop_loss_price"] = params.get("stop_loss_price")
                    decision["stop_loss_triggered"] = params.get("stop_loss_triggered", False)
                    decision["take_profit_pct"] = params.get("take_profit_pct", 0) * 100
                    decision["addon_pct"] = params.get("addon_pct", 0) * 100
                    decision["current_price"] = params.get("current_price")
                    decision["above_ma200"] = params.get("above_daily_ma200") or params.get("above_weekly_ma200")
                except Exception:
                    pass
                self._json(decision)
            except Exception as e:
                self._json({"error": str(e)})

        # ── API: V15-CT 8币种决策 ────────────────────────────────────
        elif path == "/api/v15-ct/decisions":
            try:
                sys.path.insert(0, str(BASE_DIR))
                from v15ct_trader import get_v15ct_decision, COINS, _get_dynamic_params, _get_okx_client
                client = _get_okx_client()
                decisions = []
                for coin in COINS:
                    try:
                        d = get_v15ct_decision(coin) or {}
                        d["symbol"] = coin
                        try:
                            params = _get_dynamic_params(client, coin, "LONG")
                            d["stop_loss_triggered"] = params.get("stop_loss_triggered", False)
                            d["can_open_long"] = not params.get("stop_loss_triggered", True)
                            d["stop_loss_type"] = params.get("stop_loss_type")
                            d["stop_loss_price"] = params.get("stop_loss_price")
                            d["take_profit_pct"] = params.get("take_profit_pct", 0) * 100
                            d["addon_pct"] = params.get("addon_pct", 0) * 100
                            d["current_price"] = params.get("current_price")
                            vol = params.get("volatility", {})
                            d["vol_ratio"] = vol.get("vol_ratio", 1.0)
                            d["daily_ma200"] = params.get("daily_ma200")
                            d["daily_ema200"] = params.get("daily_ema200")
                            d["weekly_ma200"] = params.get("weekly_ma200")
                            d["weekly_ema200"] = params.get("weekly_ema200")
                        except Exception:
                            pass
                        decisions.append(d)
                    except Exception:
                        decisions.append({"symbol": coin, "action": "WAIT", "confidence": 0})
                self._json({"decisions": decisions, "count": len(decisions)})
            except Exception as e:
                self._json({"error": str(e)})

        # ── API: V15-CT 回测 ─────────────────────────────────────────
        elif path == "/api/v15-ct/backtest":
            try:
                coin = self._get_query_param("coin") or "BTC"
                sys.path.insert(0, str(BASE_DIR))
                try:
                    from v15_backtest import run_backtest
                    result = run_backtest(coin)
                    self._json(result)
                except ImportError:
                    self._json({
                        "coin": coin,
                        "metrics": {
                            "total_return_pct": 0,
                            "total_trades": 0,
                            "win_rate": 0,
                            "profit_factor": 0,
                            "max_drawdown_pct": 0,
                            "sharpe_ratio": 0,
                            "avg_bars_held": 0,
                        },
                        "note": "回测模块暂不可用"
                    })
            except Exception as e:
                self._json({"error": str(e)})

        # ── API: 资金计算器 - 资金分配 ────────────────────────────────
        elif path == "/api/capital/allocation":
            try:
                sys.path.insert(0, str(BASE_DIR))
                from capital_manager import calculate_capital_allocation
                result = calculate_capital_allocation()
                real_pos = get_v15ct_real_positions()
                if isinstance(real_pos, dict) and "error" not in real_pos:
                    pos_list = [v for v in real_pos.values() if isinstance(v, dict)]
                    result["calculations"]["current_positions_count"] = len(pos_list)
                self._json(result)
            except Exception as e:
                self._json({"error": str(e)})

        # ── API: 资金计算器 - 信号触发状态 ────────────────────────────
        elif path == "/api/capital/signal-trigger":
            try:
                sys.path.insert(0, str(BASE_DIR))
                from capital_manager import get_signal_trigger_status
                result = get_signal_trigger_status()
                self._json(result)
            except Exception as e:
                self._json({"error": str(e)})

        # ── API: 资金计算器 - 币种策略参数 ────────────────────────────
        elif path == "/api/capital/strategy-params":
            try:
                sys.path.insert(0, str(BASE_DIR))
                from capital_manager import get_all_coins_strategy_params
                result = get_all_coins_strategy_params()
                self._json(result)
            except Exception as e:
                self._json({"error": str(e)})

        # ── API: 易经推理模型状态 ────────────────────────────────────────
        elif path == "/api/yijing":
            yijing_data = get_yijing_state()
            trading_data = get_yijing_trading_state()
            self._json({**yijing_data, "trading": trading_data})

        # ── API: 易经推理持仓数据 ────────────────────────────────────────
        elif path == "/api/yijing-positions":
            try:
                sys.path.insert(0, str(BCRM_REPO))
                from data_server_fixed import get_yijing_positions
                result = get_yijing_positions()
                self._json(result)
            except Exception as e:
                self._json({"error": str(e)})

        # ── API: 三屏马丁交易 ───────────────────────────────────────────
        elif path == "/api/screen-trade":
            if SCREEN_AVAILABLE:
                try:
                    symbol = self._get_query_param("symbol")
                    data = get_screen_data(symbol) if symbol else get_screen_data()
                    self._json(data)
                except Exception as e:
                    self._json({"error": str(e)})
            else:
                self._json({"error": "screen_engine not available"})

        # ── API: 三屏执行器状态 ────────────────────────────────────────
        elif path == "/api/screen-executor":
            try:
                sys.path.insert(0, str(BASE_DIR))
                from screen_executor import get_executor_state
                state = get_executor_state()
                self._json(state)
            except Exception as e:
                self._json({"error": str(e)})

        # ── API: 触发三屏执行一次 ────────────────────────────────────────
        elif path == "/api/screen-trigger":
            try:
                sys.path.insert(0, str(BASE_DIR))
                from screen_executor import check_and_execute
                result = check_and_execute()
                self._json(result)
            except Exception as e:
                self._json({"error": str(e)})

        # ── API: 研报数据 ──────────────────────────────────────────────
        elif path == "/api/reports":
            try:
                sys.path.insert(0, str(BASE_DIR))
                from report_loader import get_all_reports
                reports = get_all_reports()
                self._json(reports)
            except Exception as e:
                self._json({"error": str(e)})

        # ── API: 三屏编排器状态 ────────────────────────────────────────
        elif path == "/api/screen-orchestrator":
            try:
                sys.path.insert(0, str(BASE_DIR))
                from screen_orchestrator import get_orchestrator_state
                state = get_orchestrator_state()
                self._json(state)
            except Exception as e:
                self._json({"error": str(e)})

        # ── API: 触发三屏编排器 ────────────────────────────────────────
        elif path == "/api/screen-orchestrator/trigger":
            try:
                sys.path.insert(0, str(BASE_DIR))
                from screen_orchestrator import main
                main()
                from screen_orchestrator import get_orchestrator_state
                state = get_orchestrator_state()
                self._json({"ok": True, "state": state})
            except Exception as e:
                self._json({"error": str(e)})

        # ── API: 基本面参考信号 ────────────────────────────────────────
        elif path == "/api/fundamental-signals":
            try:
                sys.path.insert(0, str(BASE_DIR))
                from fundamental_bridge import get_fundamental_signals
                symbol = self._get_query_param("symbol") or "BTC"
                data = get_fundamental_signals(symbol)
                self._json(data)
            except Exception as e:
                self._json({"error": str(e)})

        # ── API: 模式状态查询 ──────────────────────────────────────────
        elif path == "/api/mode/status":
            try:
                sys.path.insert(0, str(BASE_DIR))
                from mode_manager import get_current_state
                state = get_current_state()
                self._json(state)
            except Exception as e:
                self._json({"error": str(e)})

        # ── API: 模式切换（手动） ──────────────────────────────────────
        elif path == "/api/mode/switch":
            try:
                sys.path.insert(0, str(BASE_DIR))
                from mode_manager import set_mode_override
                content = self._read_json_body()
                mode = content.get("mode") if content else self._get_query_param("mode")
                reason = (content.get("reason") if content else None) or "API手动切换"
                if not mode:
                    self._json({"error": "缺少 mode 参数"}, status=400)
                    return
                result = set_mode_override(mode, reason)
                self._json(result)
            except Exception as e:
                self._json({"error": str(e)})

        # ── API: 模式检测（立即触发检测） ──────────────────────────────
        elif path == "/api/mode/check":
            try:
                sys.path.insert(0, str(BASE_DIR))
                from mode_manager import check_and_switch_mode
                result = check_and_switch_mode()
                self._json(result)
            except Exception as e:
                self._json({"error": str(e)})

        # ── API: 模式切换历史 ─────────────────────────────────────────
        elif path == "/api/mode/history":
            try:
                sys.path.insert(0, str(BASE_DIR))
                from mode_manager import get_mode_history
                limit = int(self._get_query_param("limit") or "20")
                history = get_mode_history(limit)
                self._json({"history": history, "count": len(history)})
            except Exception as e:
                self._json({"error": str(e)})

        # ── API: AI 指令查询 ──────────────────────────────────────────
        elif path == "/api/mode/ai-directive":
            try:
                sys.path.insert(0, str(BASE_DIR))
                from mode_manager import get_ai_directive
                directive = get_ai_directive()
                self._json(directive)
            except Exception as e:
                self._json({"error": str(e)})

        # ── API: 设置 AI 指令 ─────────────────────────────────────────
        elif path == "/api/mode/set-ai-directive":
            try:
                sys.path.insert(0, str(BASE_DIR))
                from mode_manager import set_ai_directive
                content = self._read_json_body()
                if not content:
                    self._json({"error": "缺少请求体"}, status=400)
                    return
                result = set_ai_directive(content)
                self._json(result)
            except Exception as e:
                self._json({"error": str(e)})

        # ── API: 经典指标执行器状态 ────────────────────────────────────
        elif path == "/api/classic-executor":
            try:
                sys.path.insert(0, str(BASE_DIR))
                from classic_executor import get_executor_state
                state = get_executor_state()
                self._json(state)
            except Exception as e:
                self._json({"error": str(e)})

        # ── API: 经典指标信号（指定币种） ──────────────────────────────
        elif path == "/api/classic-executor/signals":
            try:
                sys.path.insert(0, str(BASE_DIR))
                from classic_executor import generate_signals
                symbol = self._get_query_param("symbol") or "BTC"
                signals = generate_signals(symbol)
                self._json(signals)
            except Exception as e:
                self._json({"error": str(e)})

        # ── API: 代币信号（三屏算法 + Freqtrade） ──────────────────────
        elif path == "/api/token-signals":
            try:
                sys.path.insert(0, str(BASE_DIR))
                from screen_engine import compute_full_trading_signal, _fetch_freqtrade_signals

                COINS = ["BTC", "ETH", "SOL", "AVAX", "ARB", "LINK", "MATIC", "LTC"]
                signals = []

                for coin in COINS:
                    try:
                        symbol = f"{coin}-USDT"
                        result = compute_full_trading_signal(symbol, is_btc=(coin == "BTC"))

                        ft = result.get("freqtrade_signals", {})
                        fs = result.get("final_signal", {})

                        signal_entry = {
                            "symbol": coin,
                            "price": result.get("price"),
                            "direction": fs.get("direction") or "NEUTRAL",
                            "confidence": fs.get("confidence", 0),
                            "freqtrade_4h": ft.get("4h", {}).get("signal", "HOLD"),
                            "freqtrade_4h_conf": ft.get("4h", {}).get("confidence", 0),
                            "freqtrade_1h": ft.get("1h", {}).get("signal", "HOLD"),
                            "freqtrade_1h_conf": ft.get("1h", {}).get("confidence", 0),
                            "trend_consistent": fs.get("trend_consistent", False),
                            "freqtrade_consistent": fs.get("freqtrade_consistent", False),
                            "entry_ready": fs.get("entry_ready", False),
                            "strategy": ft.get("4h", {}).get("strategy", "Freqtrade"),
                        }
                        signals.append(signal_entry)
                    except Exception:
                        signals.append({
                            "symbol": coin,
                            "price": None,
                            "direction": "ERROR",
                            "confidence": 0,
                            "freqtrade_4h": "HOLD",
                            "freqtrade_4h_conf": 0,
                            "freqtrade_1h": "HOLD",
                            "freqtrade_1h_conf": 0,
                            "trend_consistent": False,
                            "freqtrade_consistent": False,
                            "entry_ready": False,
                        })

                signals.sort(key=lambda x: x.get("confidence", 0), reverse=True)

                self._json({
                    "signals": signals,
                    "count": len(signals),
                    "timestamp": datetime.now().isoformat(),
                    "bull_count": sum(1 for s in signals if s["direction"] == "BULL"),
                    "bear_count": sum(1 for s in signals if s["direction"] == "BEAR"),
                    "neutral_count": sum(1 for s in signals if s["direction"] == "NEUTRAL"),
                })
            except Exception as e:
                self._json({"error": str(e)})

        # ── API: 三屏趋势信号（单币种完整数据） ──────────────────────
        elif path == "/api/trend-screen":
            try:
                # 切换到 12-三屏趋势系统 独立模块
                trend_system_path = "/Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统"
                if trend_system_path not in sys.path:
                    sys.path.insert(0, trend_system_path)
                from engine import compute_full_trading_signal

                symbol = self._get_query_param("symbol") or "BTC"
                spot_inst = f"{symbol}-USDT"
                is_btc = symbol == "BTC"

                # 获取完整三屏信号（含K线+基本面+Freqtrade信号）
                result = compute_full_trading_signal(spot_inst, is_btc=is_btc)
                if "error" in result:
                    self._json({"error": result["error"]})
                    return

                price = result.get("price", 0)
                fs = result.get("final_signal", {})

                # 获取实时持仓（如果有）
                try:
                    from screen_executor import get_position, get_account_info
                    pos = get_position(f"{symbol}-USDT-SWAP")
                    acct = get_account_info()
                except Exception:
                    pos = None
                    acct = {"equity": 0, "available": 0}

                # 构建完整响应
                response = {
                    "symbol": symbol,
                    "price": price,
                    "generated_at": result.get("generated_at"),
                    # 第一屏：战略层
                    "trend_consistency": result.get("trend_consistency", {}),
                    "bayesian_confidence": result.get("bayesian_confidence", {}),
                    "freqtrade_signals": result.get("freqtrade_signals", {}),
                    "fundamental_data": result.get("fundamental_data", {}),
                    "fundamental_source": result.get("fundamental_source", "unknown"),
                    "technical_fundamental_fusion": result.get("technical_fundamental_fusion", {}),
                    "final_signal": result.get("final_signal", {}),
                    # 第二屏：战术层（仓位映射，无马丁策略参数）
                    "position_tiers": [
                        {"threshold": 85, "budget_pct": 0.60},
                        {"threshold": 75, "budget_pct": 0.45},
                        {"threshold": 65, "budget_pct": 0.30},
                        {"threshold": 55, "budget_pct": 0.15},
                        {"threshold": 45, "budget_pct": 0.05},
                    ],
                    # 第三屏：执行层
                    "position": pos,
                    "account": acct,
                }

                self._json(response)
            except Exception as e:
                self._json({"error": str(e)})

        # ── API: Dream OS 状态 ────────────────────────────────────────
        elif path == "/api/dreamos":
            try:
                sys.path.insert(0, "/Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/1-ARCHITECTURE")
                from dreamos.nodes import list_available_nodes, register_all
                from dreamos.registry import get_default_registry

                registry = get_default_registry()
                register_all(registry)
                nodes = registry.list_nodes()
                registered = [{"node_id": n.node_id, "name": getattr(n, "name", ""),
                               "chain": getattr(n, "chain", ""), "description": getattr(n, "description", "")}
                              for n in nodes]

                acct = {}
                memory = {}

                try:
                    from dreamos.shared.state import State, new_state
                    sys.path.insert(0, str(BASE_DIR))
                    from execution.aster_spot import HyperliquidClient
                    client = HyperliquidClient('b')
                    acct = client.get_account()
                except Exception as e:
                    acct = {"error": str(e), "equity": 0, "positions": []}

                try:
                    sys.path.insert(0, str(BASE_DIR.parent.parent))
                    from experiments.agent_c.agent_c import AgentC
                    agent_c = AgentC(agent_id='b')
                    memory = agent_c.get_memory()
                except Exception as e:
                    memory = {"error": str(e)}

                self._json({
                    "nodes": registered,
                    "total_nodes": len(registered),
                    "account": acct,
                    "memory": memory,
                    "timestamp": datetime.now().isoformat(),
                })
            except Exception as e:
                self._json({"error": str(e)})

        # ── API: Dream OS 调度历史 ────────────────────────────────────────
        elif path == "/api/dreamos/history":
            try:
                from pathlib import Path
                history_dir = BASE_DIR / "data" / "agent_c_b"
                logs = []
                if history_dir.exists():
                    for f in sorted(history_dir.glob("*.json"))[-20:]:
                        try:
                            with open(f) as fp:
                                logs.append(json.load(fp))
                        except Exception:
                            pass
                self._json({"logs": logs, "count": len(logs)})
            except Exception as e:
                self._json({"error": str(e)})

        # ── API: Dream OS 执行一次分析 ────────────────────────────────────────
        elif path == "/api/dreamos/analyze":
            try:
                symbol = self._get_query_param("symbol") or "BTC"
                sys.path.insert(0, "/Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/1-ARCHITECTURE")
                sys.path.insert(0, "/Users/zhangjiangtao/WorkBuddy/dreambuddy-v2")
                from experiments.agent_c.agent_c import AgentC

                agent_c = AgentC(agent_id='b')
                mkt_data = agent_c.fetch_market_data(symbol)
                if not mkt_data:
                    self._json({"error": f"无法获取 {symbol} 的市场数据"}, status=400)
                    return

                decision = agent_c.analyze(symbol, mkt_data)

                history_dir = BASE_DIR / "data" / "agent_c_b"
                history_dir.mkdir(parents=True, exist_ok=True)
                ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                history_file = history_dir / f"{ts}_{symbol}.json"
                with open(history_file, 'w') as f:
                    json.dump(decision, f, indent=2, default=str)

                self._json(decision)
            except Exception as e:
                import traceback
                self._json({"error": str(e), "traceback": traceback.format_exc()})

        # ── API: Dream OS 节点执行状态 ────────────────────────────────────────
        elif path == "/api/dreamos/nodes":
            try:
                sys.path.insert(0, "/Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/1-ARCHITECTURE")
                from dreamos.nodes import list_available_nodes
                nodes = list_available_nodes()
                self._json(nodes)
            except Exception as e:
                self._json({"error": str(e)})

        # ── API: Dream OS 36场景编排记忆表 ────────────────────────────────
        elif path == "/api/dreamos/scenarios":
            try:
                sys.path.insert(0, "/Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/1-ARCHITECTURE")
                from dreamos.core.memory.orchestration_memory import OrchestrationMemory
                from dreamos.core.memory.execution_feedback import ExecutionFeedbackCollector

                memory = OrchestrationMemory()
                memory.load()
                stats = memory.get_stats()

                # 列出所有 36 场景及覆盖详情
                all_sids = [
                    f"{t}_{v}_{m}"
                    for t in ["BULL", "BEAR", "NEUTRAL"]
                    for v in ["LOW", "NORMAL", "HIGH", "EXTREME"]
                    for m in ["ACCELERATING", "DECELERATING", "EXHAUSTION"]
                ]
                scenarios = memory._data.get("scenarios", {})
                scenario_list = []
                for sid in all_sids:
                    s = scenarios.get(sid)
                    if s:
                        scenario_list.append({
                            "scenario_id": sid,
                            "covered": True,
                            "best_pattern": s.get("best_pattern", ""),
                            "nodes": s.get("nodes", []),
                            "score": s.get("score", 0),
                            "sample_count": s.get("sample_count", 0),
                            "confidence": s.get("confidence", "low"),
                            "sparse": s.get("sparse", True),
                            "inferred": s.get("inferred", False),
                            "metrics": s.get("metrics", {}),
                        })
                    else:
                        scenario_list.append({
                            "scenario_id": sid,
                            "covered": False,
                            "best_pattern": "",
                            "nodes": [],
                            "score": 0,
                            "sample_count": 0,
                            "confidence": "none",
                        })

                # 反馈收集器统计
                collector = ExecutionFeedbackCollector(memory)
                feedback_stats = {}
                for sid in collector.get_all_scenario_ids():
                    feedback_stats[sid] = collector.get_stats(sid)

                # 检查是否有触发进化的场景
                trigger_scenarios = []
                for fb in collector.get_all_feedbacks():
                    if fb.trigger_evolution:
                        trigger_scenarios.append({
                            "scenario_id": fb.scenario_id,
                            "pattern_used": fb.pattern_used,
                            "actual_sharpe": fb.actual_sharpe,
                            "expected_sharpe": fb.expected_sharpe,
                            "deviation": fb.deviation,
                            "direction_accuracy": fb.direction_accuracy,
                            "trade_count": len(fb.trades),
                        })

                self._json({
                    "scenarios": scenario_list,
                    "stats": stats,
                    "feedback": feedback_stats,
                    "trigger_evolution": trigger_scenarios,
                    "total_scenarios": 36,
                    "covered": stats.get("covered_scenarios", 0),
                    "coverage_rate": stats.get("coverage_rate", 0),
                    "timestamp": datetime.now().isoformat(),
                })
            except Exception as e:
                import traceback
                self._json({"error": str(e), "traceback": traceback.format_exc()})

        # ── API: Dream OS 触发进化引擎 ────────────────────────────────────
        elif path == "/api/dreamos/evolve":
            try:
                sys.path.insert(0, "/Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/1-ARCHITECTURE")
                from dreamos.evolution.engine import EvolutionEngine

                engine = EvolutionEngine()
                # 检查并执行编排优化
                try:
                    updates = engine._check_orchestration_optimization()
                except Exception as e:
                    updates = [f"执行失败: {e}"]

                # 获取所有反馈
                collector = engine.get_feedback_collector()
                all_feedbacks = collector.get_all_feedbacks()

                self._json({
                    "evolution_triggered": len(updates) > 0,
                    "updates": updates if updates else [],
                    "feedbacks": [
                        {
                            "scenario_id": fb.scenario_id,
                            "pattern_used": fb.pattern_used,
                            "actual_sharpe": fb.actual_sharpe,
                            "expected_sharpe": fb.expected_sharpe,
                            "deviation": fb.deviation,
                            "direction_accuracy": fb.direction_accuracy,
                            "trigger_evolution": fb.trigger_evolution,
                            "trade_count": len(fb.trades),
                        } for fb in all_feedbacks
                    ],
                    "timestamp": datetime.now().isoformat(),
                })
            except Exception as e:
                import traceback
                self._json({"error": str(e), "traceback": traceback.format_exc()})

        # ── 静态文件服务 ────────────────────────────────────────────────
        elif path == "/" or path == "/index.html":
            self._file(BASE_DIR / "monitor.html", "text/html")
        else:
            self.send_response(404)
            self.end_headers()

    def _get_query_param(self, name: str) -> str:
        params = urlparse(self.path).query
        qs = dict(parse_qsl(params))
        return qs.get(name)

    def _read_json_body(self) -> dict:
        try:
            length = int(self.headers.get("Content-Length", 0))
            if length <= 0:
                return {}
            body = self.rfile.read(length).decode("utf-8")
            return json.loads(body) if body else {}
        except Exception:
            return {}

    def do_POST(self):
        path = urlparse(self.path).path

        # ── API: 模式切换（手动） ──────────────────────────────────────
        if path == "/api/mode/switch":
            try:
                sys.path.insert(0, str(BASE_DIR))
                from mode_manager import set_mode_override
                content = self._read_json_body()
                mode = content.get("mode") or self._get_query_param("mode")
                reason = content.get("reason") or "API手动切换"
                if not mode:
                    self._json({"error": "缺少 mode 参数"}, status=400)
                    return
                result = set_mode_override(mode, reason)
                self._json(result)
            except Exception as e:
                self._json({"error": str(e)})

        # ── API: 模式检测（立即触发） ──────────────────────────────────
        elif path == "/api/mode/check":
            try:
                sys.path.insert(0, str(BASE_DIR))
                from mode_manager import check_and_switch_mode
                result = check_and_switch_mode()
                self._json(result)
            except Exception as e:
                self._json({"error": str(e)})

        # ── API: 设置 AI 指令 ─────────────────────────────────────────
        elif path == "/api/mode/set-ai-directive":
            try:
                sys.path.insert(0, str(BASE_DIR))
                from mode_manager import set_ai_directive
                content = self._read_json_body()
                if not content:
                    self._json({"error": "缺少请求体"}, status=400)
                    return
                result = set_ai_directive(content)
                self._json(result)
            except Exception as e:
                self._json({"error": str(e)})

        else:
            self.send_response(404)
            self.end_headers()

    def _json(self, data, status=200):
        import numpy as np
        def default_handler(obj):
            if isinstance(obj, (np.integer, np.int64, np.int32)):
                return int(obj)
            if isinstance(obj, (np.floating, np.float64, np.float32)):
                return float(obj)
            if isinstance(obj, np.ndarray):
                return obj.tolist()
            raise TypeError(f"Object of type {type(obj)} is not JSON serializable")
        body = json.dumps(data, ensure_ascii=False, default=default_handler).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", len(body))
        self.end_headers()
        self.wfile.write(body)

    def _file(self, path: Path, mime: str):
        if not path.exists():
            self.send_response(404); self.end_headers(); return
        body = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", len(body))
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        self.end_headers()
        self.wfile.write(body)


if __name__ == "__main__":
    try:
        server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
        server.daemon_threads = True
        print(f"✅ 监控服务已启动（多线程模式）")
    except Exception:
        server = HTTPServer(("0.0.0.0", PORT), Handler)
        print(f"✅ 监控服务已启动（单线程模式）")
    print(f"   浏览器打开: http://localhost:{PORT}")
    print(f"   Ctrl+C 停止")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n停止")
