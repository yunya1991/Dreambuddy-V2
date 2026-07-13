#!/usr/bin/env python3
"""
监控页面数据服务器 — 提供 /api/state 接口
启动：python3 data_server.py
访问：http://localhost:8765

优化：
  - 线程池服务器，避免慢请求阻塞
  - 内存缓存 + 后台定时刷新，页面秒开
  - 易经/三屏等慢接口异步刷新，请求直接返回缓存
  - requests 禁用系统代理，避免本地代理干扰
"""
import json, os, requests, warnings, subprocess, sys, threading, time, datetime
from pathlib import Path
from socketserver import ThreadingMixIn
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qsl

warnings.filterwarnings("ignore")
os.environ["NO_PROXY"] = "localhost,127.0.0.1"

BASE_DIR = Path(__file__).resolve().parent.parent / "experiments" / "ab-trading"
LOG_A    = BASE_DIR / "logs" / "agent_a"
LOG_B    = BASE_DIR / "logs" / "agent_b"
PORT     = 8765

BCRM_REPO = Path(os.environ.get(
    "BCRM_REPO",
    str(Path(__file__).resolve().parent),
))

sys.path.insert(0, str(BASE_DIR))
try:
    from screen_engine import get_all as get_screen_data
    SCREEN_AVAILABLE = True
except ImportError:
    SCREEN_AVAILABLE = False

USER_A = "0x93842F1ea62E7E3c71494d9EA69EfC4F2D6e9934"
USER_B = "0x6632da9c91A959eEBf1343f8AFAbf2807414004A"

_cache = {}
_cache_lock = threading.Lock()


def _cache_get(key):
    with _cache_lock:
        return _cache.get(key)


def _cache_set(key, value):
    with _cache_lock:
        _cache[key] = {"data": value, "ts": time.time()}


def _make_session():
    s = requests.Session()
    s.trust_env = False
    return s


def load_logs(log_dir: Path, limit: int = 30):
    logs = []
    if not log_dir.exists():
        return logs
    for f in sorted(log_dir.glob("*.json"))[-limit:]:
        try:
            with open(f) as fp:
                d = json.load(fp)
                if "coin" not in d and d.get("entry_price"):
                    pass
                logs.append(d)
        except Exception:
            pass
    return logs


def get_perp_state(user: str) -> dict:
    s = _make_session()
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
    return {"equity": equity, "avail": avail, "positions": positions}


def get_hl_state():
    a = get_perp_state(USER_A)
    b = get_perp_state(USER_B)
    return {
        "perp_equity":    a["equity"],
        "perp_avail":     a["avail"],
        "perp_positions": a["positions"],
        "b_equity":       b["equity"],
        "b_avail":        b["avail"],
        "b_positions":    b["positions"],
        "spot_usdc":      0,
        "total_equity":   a["equity"] + b["equity"],
    }


def get_full_state():
    hl = get_hl_state()
    return {
        **hl,
        "logs_a": load_logs(LOG_A),
        "logs_b": load_logs(LOG_B),
    }


def get_yijing_state():
    try:
        result = subprocess.run(
            ["python3", "-m", "scripts.memory_l4.ab_bridge", "yijing-status"],
            capture_output=True, text=True, timeout=45,
            cwd=str(BCRM_REPO),
            env={**os.environ, "NO_PROXY": "localhost,127.0.0.1",
                 "no_proxy": "localhost,127.0.0.1"},
        )
        if result.returncode == 0:
            return json.loads(result.stdout)
        return {"error": result.stderr[:500]}
    except Exception as e:
        return {"error": str(e)}


def get_screen_state():
    if not SCREEN_AVAILABLE:
        return {"error": "screen_engine not available"}
    try:
        return get_screen_data()
    except Exception as e:
        return {"error": str(e)}


def get_executor_state():
    try:
        from screen_executor import get_executor_state
        return get_executor_state()
    except Exception as e:
        return {"error": str(e)}


def get_orchestrator_state():
    try:
        from screen_orchestrator import get_orchestrator_state
        return get_orchestrator_state()
    except Exception as e:
        return {"error": str(e)}


def get_reports_state():
    try:
        from report_loader import get_all_reports
        return get_all_reports()
    except Exception as e:
        return {"error": str(e)}


# ── Dream OS 状态 ──────────────────────────────────────────────────────────
ARCH_DIR = "/Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/1-ARCHITECTURE"
PROJECT_ROOT = "/Users/zhangjiangtao/WorkBuddy/dreambuddy-v2"


def get_dreamos_state():
    """获取 Dream OS 状态（节点注册表 + 账户 + 记忆）"""
    try:
        sys.path.insert(0, ARCH_DIR)
        from dreamos.nodes import list_available_nodes, register_all
        from dreamos.registry import get_default_registry

        registry = get_default_registry()
        register_all(registry)
        nodes = registry.list_nodes()
        registered = [{"node_id": n.node_id, "name": getattr(n, "name", ""),
                       "chain": getattr(n, "chain", ""), "description": getattr(n, "description", "")}
                      for n in nodes]

        sys.path.insert(0, str(BASE_DIR))
        account = {"equity": 0, "positions": {}}
        memory = {}
        try:
            from execution.aster_spot import HyperliquidClient
            client = HyperliquidClient('b')
            account = client.get_account()
        except Exception:
            pass
        try:
            sys.path.insert(0, PROJECT_ROOT)
            from experiments.agent_c.agent_c import AgentC
            agent_c = AgentC(agent_id='b')
            memory = agent_c.get_memory()
        except Exception:
            pass

        return {
            "nodes": registered,
            "total_nodes": len(registered),
            "account": account,
            "memory": memory,
            "timestamp": datetime.datetime.now().isoformat(),
        }
    except Exception as e:
        return {"error": str(e)}


def get_dreamos_history():
    """获取 Dream OS 调度历史"""
    try:
        history_dir = BASE_DIR / "data" / "agent_c_b"
        logs = []
        if history_dir.exists():
            for f in sorted(history_dir.glob("*.json"))[-20:]:
                try:
                    with open(f) as fp:
                        logs.append(json.load(fp))
                except Exception:
                    pass
        return {"logs": logs, "count": len(logs)}
    except Exception as e:
        return {"error": str(e)}


def dreamos_analyze(symbol="BTC"):
    """执行一次 Dream OS 分析"""
    try:
        sys.path.insert(0, ARCH_DIR)
        sys.path.insert(0, PROJECT_ROOT)
        from experiments.agent_c.agent_c import AgentC

        agent_c = AgentC(agent_id='b')
        mkt_data = agent_c.fetch_market_data(symbol)
        if not mkt_data:
            return {"error": f"无法获取 {symbol} 的市场数据"}

        decision = agent_c.analyze(symbol, mkt_data)

        # 保存历史
        history_dir = BASE_DIR / "data" / "agent_c_b"
        history_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        history_file = history_dir / f"{ts}_{symbol}.json"
        with open(history_file, 'w') as f:
            json.dump(decision, f, indent=2, default=str)

        return decision
    except Exception as e:
        return {"error": str(e)}


def get_yijing_positions():
    """读取易经推理系统的当前持仓（本地跟踪 + OKX实盘查询）"""
    pos_dir = Path(__file__).parent / ".workbuddy" / "memory_l4" / "open_positions"
    risk_path = Path(__file__).parent / ".workbuddy" / "memory_l4" / "risk" / "risk_state.json"
    hb_path = Path(__file__).parent / ".workbuddy" / "memory_l4" / "guardian" / "heartbeat.json"
    perf_path = Path(__file__).parent / ".workbuddy" / "memory_l4" / "stats" / "performance.json"

    # ── 本地跟踪持仓 ──
    local_positions = []
    if pos_dir.exists():
        for f in sorted(pos_dir.glob("*.json")):
            try:
                with open(f) as fp:
                    d = json.load(fp)
                    local_positions.append({
                        "coin": d.get("coin", ""),
                        "inst_id": d.get("inst_id", ""),
                        "direction": d.get("direction", ""),
                        "entry_price": d.get("entry_price", 0),
                        "entry_time": d.get("entry_time", ""),
                        "confidence": d.get("confidence", 0),
                        "hexagram": d.get("hexagram", ""),
                        "pnl": d.get("pnl", 0),
                        "pnl_pct": d.get("pnl_pct", 0),
                        "trade_id": d.get("trade_id", ""),
                        "source": "local",
                    })
            except Exception:
                pass

    # ── OKX 实盘持仓查询 ──
    okx_positions = []
    okx_balance = {}
    try:
        sys.path.insert(0, str(Path(__file__).parent / "scripts" / "memory_l4"))
        from okx_simulated import OKXSimulatedClient, _load_config, CONFIG_DIR
        env_keys = ["OKX_API_KEY", "OKX_SECRET_KEY", "OKX_PASSPHRASE",
                    "OKX_BASE_URL", "OKX_SIMULATED", "OKX_DRY_RUN",
                    "OKX_DEFAULT_INST_ID", "DEFAULT_LEVERAGE"]
        saved_env = {}
        for k in env_keys:
            if k in os.environ:
                saved_env[k] = os.environ.pop(k)
        try:
            client = OKXSimulatedClient()
        finally:
            for k, v in saved_env.items():
                os.environ[k] = v

        # 查询账户余额
        bal = client.get_balance()
        if bal.get("ok"):
            okx_balance = {
                "total_eq": bal.get("total_eq", 0),
                "avail": bal.get("assets", {}).get("USDT", {}).get("avail", 0),
            }

        # 查询所有币种持仓
        coins = ["BTC", "ETH", "SOL", "BNB", "XRP", "DOGE"]
        for coin in coins:
            inst_id = f"{coin}-USDT-SWAP"
            r = client.get_positions(inst_id)
            if not r.get("ok"):
                continue
            for p in r.get("positions", []):
                okx_positions.append({
                    "coin": coin,
                    "inst_id": inst_id,
                    "direction": p.get("pos_side", ""),
                    "entry_price": p.get("avg_px", 0),
                    "pos_size": p.get("pos", 0),
                    "upl": p.get("upl", 0),
                    "upl_ratio": p.get("upl_ratio", 0),
                    "mark_px": p.get("mark_px", 0),
                    "leverage": p.get("lever", ""),
                    "source": "okx_live",
                })
    except Exception as e:
        okx_positions = [{"error": str(e)}]

    risk_state = {}
    if risk_path.exists():
        try:
            with open(risk_path) as fp:
                risk_state = json.load(fp)
        except Exception:
            pass

    heartbeat = {}
    if hb_path.exists():
        try:
            with open(hb_path) as fp:
                heartbeat = json.load(fp)
        except Exception:
            pass

    performance = {}
    if perf_path.exists():
        try:
            with open(perf_path) as fp:
                performance = json.load(fp)
        except Exception:
            pass

    return {
        "positions": local_positions,
        "okx_live_positions": okx_positions,
        "okx_balance": okx_balance,
        "count": len(okx_positions),
        "local_count": len(local_positions),
        "risk_state": risk_state,
        "heartbeat": heartbeat,
        "performance": performance,
    }


def _bg_refresh_state(interval: int = 5):
    while True:
        try:
            data = get_full_state()
            _cache_set("state", data)
        except Exception:
            pass
        time.sleep(interval)


def _bg_refresh_yijing(interval: int = 60):
    while True:
        try:
            data = get_yijing_state()
            _cache_set("yijing", data)
        except Exception:
            pass
        time.sleep(interval)


def _bg_refresh_screen(interval: int = 30):
    while True:
        try:
            _cache_set("screen_trade", get_screen_state())
        except Exception:
            pass
        try:
            _cache_set("screen_executor", get_executor_state())
        except Exception:
            pass
        try:
            _cache_set("screen_orchestrator", get_orchestrator_state())
        except Exception:
            pass
        try:
            _cache_set("reports", get_reports_state())
        except Exception:
            pass
        try:
            sys.path.insert(0, str(BASE_DIR))
            from classic_executor import get_executor_state as _get_classic_state
            _cache_set("classic_executor", _get_classic_state())
        except Exception:
            pass
        try:
            sys.path.insert(0, str(BASE_DIR))
            from mode_manager import get_current_state
            _cache_set("mode_status", get_current_state())
        except Exception:
            pass
        try:
            sys.path.insert(0, str(BASE_DIR))
            from fundamental_bridge import get_fundamental_signals
            _cache_set("fundamental_signals_BTC", get_fundamental_signals("BTC"))
        except Exception:
            pass
        time.sleep(interval)


def _bg_refresh_dreamos(interval: int = 15):
    while True:
        try:
            _cache_set("dreamos", get_dreamos_state())
        except Exception:
            pass
        try:
            _cache_set("dreamos_history", get_dreamos_history())
        except Exception:
            pass
        time.sleep(interval)


def _start_bg_refresh():
    threads = [
        threading.Thread(target=_bg_refresh_state, args=(5,), daemon=True),
        threading.Thread(target=_bg_refresh_yijing, args=(60,), daemon=True),
        threading.Thread(target=_bg_refresh_screen, args=(30,), daemon=True),
        threading.Thread(target=_bg_refresh_dreamos, args=(15,), daemon=True),
    ]
    for t in threads:
        t.start()
    return threads


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        path = urlparse(self.path).path

        if path == "/api/state":
            cached = _cache_get("state")
            data = cached["data"] if cached else get_full_state()
            self._json(data)

        elif path == "/api/yijing":
            cached = _cache_get("yijing")
            if cached:
                self._json(cached["data"])
            else:
                self._json({"error": "yijing data loading, please wait"})

        elif path == "/api/screen-trade":
            cached = _cache_get("screen_trade")
            if cached:
                self._json(cached["data"])
            else:
                self._json({"error": "screen data loading"})

        elif path == "/api/screen-executor":
            cached = _cache_get("screen_executor")
            if cached:
                self._json(cached["data"])
            else:
                self._json({"error": "executor data loading"})

        elif path == "/api/screen-orchestrator":
            cached = _cache_get("screen_orchestrator")
            if cached:
                self._json(cached["data"])
            else:
                self._json({"error": "orchestrator data loading"})

        elif path == "/api/reports":
            cached = _cache_get("reports")
            if cached:
                self._json(cached["data"])
            else:
                self._json({"error": "reports loading"})

        elif path == "/api/yijing-positions":
            self._json(get_yijing_positions())

        # ── V15-CT 马丁策略 API ────────────────────────────────────────
        elif path == "/api/v15-ct/decision":
            try:
                sys.path.insert(0, str(BASE_DIR))
                from screen_executor import _v15_real_decision
                coin = self._get_query_param("coin") or "BTC"
                screen1 = {"spot_inst": f"{coin}-USDT"}
                decision = _v15_real_decision(screen1, {})
                self._json(decision)
            except Exception as e:
                self._json({"error": str(e)})

        elif path == "/api/v15-ct/decisions":
            try:
                sys.path.insert(0, str(BASE_DIR))
                from screen_executor import _v15_real_decision
                coins_param = self._get_query_param("coins") or "BTC,ETH,SOL,ARB,OP,UNI,HYPE,OKB"
                coins = [c.strip() for c in coins_param.split(",") if c.strip()]
                decisions = []
                for coin in coins:
                    try:
                        screen1 = {"spot_inst": f"{coin}-USDT"}
                        d = _v15_real_decision(screen1, {})
                        d["symbol"] = coin
                        decisions.append(d)
                    except Exception:
                        decisions.append({"symbol": coin, "action": "WAIT", "confidence": 0, "reasons": ["获取失败"]})
                self._json({"decisions": decisions})
            except Exception as e:
                self._json({"error": str(e)})

        elif path == "/api/v15-ct/backtest":
            try:
                sys.path.insert(0, str(BASE_DIR))
                from v15_backtest import run_backtest, fetch_klines
                coin = self._get_query_param("coin") or "BTC"
                klines = fetch_klines(coin, "4h", 1500)
                result = run_backtest(coin=coin, klines=klines)
                self._json(result)
            except Exception as e:
                self._json({"error": str(e)})

        elif path == "/api/v15-ct/status":
            try:
                sys.path.insert(0, str(BASE_DIR))
                from capital_manager import calculate_capital_allocation
                from config_loader import load_config, get_config
                load_config("v15ct")
                
                allocation = calculate_capital_allocation()
                positions = allocation.get("positions", [])
                
                state_file = BASE_DIR / "data" / "v15ct_state.json"
                total_trades = 0
                win_rate = 0
                auto_execute = str(get_config("V15CT_AUTO_EXECUTE", "true")).lower() == "true"
                if state_file.exists():
                    try:
                        with open(state_file) as f:
                            state = json.load(f)
                        total_trades = state.get("total_trades", 0)
                        win_rate = state.get("win_rate", 0)
                    except Exception:
                        pass
                
                self._json({
                    "strategy_mode": "v15_ct",
                    "auto_execute": auto_execute,
                    "positions": positions,
                    "v15_ct_positions": positions,
                    "total_trades": total_trades,
                    "win_rate": win_rate,
                    "coins_monitored": allocation.get("coins_monitored", []),
                    "capital": allocation.get("balance", {}),
                    "risk_level": allocation.get("recommendations", {}).get("risk_level", "LOW"),
                })
            except Exception as e:
                self._json({"error": str(e)})

        # ── 资金管理 API ────────────────────────────────────────────────
        elif path == "/api/capital/allocation":
            try:
                sys.path.insert(0, str(BASE_DIR))
                from capital_manager import calculate_capital_allocation
                allocation = calculate_capital_allocation()
                self._json(allocation)
            except Exception as e:
                self._json({"error": str(e)})

        elif path == "/api/capital/balance":
            try:
                sys.path.insert(0, str(BASE_DIR))
                from capital_manager import get_account_balance
                balance = get_account_balance()
                self._json(balance)
            except Exception as e:
                self._json({"error": str(e)})

        elif path == "/api/capital/positions":
            try:
                sys.path.insert(0, str(BASE_DIR))
                from capital_manager import get_current_positions
                positions = get_current_positions()
                self._json(positions)
            except Exception as e:
                self._json({"error": str(e)})

        elif path == "/api/capital/signal-trigger":
            try:
                sys.path.insert(0, str(BASE_DIR))
                from capital_manager import get_signal_trigger_status
                status = get_signal_trigger_status()
                self._json(status)
            except Exception as e:
                self._json({"error": str(e)})

        # ── Dream OS API ──────────────────────────────────────────────
        elif path == "/api/dreamos":
            cached = _cache_get("dreamos")
            if cached:
                self._json(cached["data"])
            else:
                self._json(get_dreamos_state())

        elif path == "/api/dreamos/history":
            cached = _cache_get("dreamos_history")
            if cached:
                self._json(cached["data"])
            else:
                self._json(get_dreamos_history())

        elif path == "/api/dreamos/nodes":
            try:
                sys.path.insert(0, ARCH_DIR)
                from dreamos.nodes import list_available_nodes
                nodes = list_available_nodes()
                self._json(nodes)
            except Exception as e:
                self._json({"error": str(e)})

        elif path == "/api/dreamos/analyze":
            symbol = self._get_query_param("symbol") or "BTC"
            self._json(dreamos_analyze(symbol))

        elif path == "/api/screen-trigger":
            try:
                from screen_executor import check_and_execute
                result = check_and_execute()
                _cache_set("screen_executor", get_executor_state())
                self._json(result)
            except Exception as e:
                self._json({"error": str(e)})

        elif path == "/api/screen-orchestrator/trigger":
            try:
                from screen_orchestrator import main
                main()
                _cache_set("screen_orchestrator", get_orchestrator_state())
                self._json({"ok": True, "state": _cache_get("screen_orchestrator")["data"]})
            except Exception as e:
                self._json({"error": str(e)})

        # ── API: 模式状态查询 ──────────────────────────────────────────
        elif path == "/api/mode/status":
            cached = _cache_get("mode_status")
            if cached:
                self._json(cached["data"])
            else:
                try:
                    sys.path.insert(0, str(BASE_DIR))
                    from mode_manager import get_current_state
                    state = get_current_state()
                    _cache_set("mode_status", state)
                    self._json(state)
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

        # ── API: 基本面参考信号 ────────────────────────────────────────
        elif path == "/api/fundamental-signals":
            symbol = self._get_query_param("symbol") or "BTC"
            cached = _cache_get(f"fundamental_signals_{symbol}")
            if cached:
                self._json(cached["data"])
            else:
                try:
                    sys.path.insert(0, str(BASE_DIR))
                    from fundamental_bridge import get_fundamental_signals
                    data = get_fundamental_signals(symbol)
                    _cache_set(f"fundamental_signals_{symbol}", data)
                    self._json(data)
                except Exception as e:
                    self._json({"error": str(e)})

        # ── API: 经典指标执行器状态 ────────────────────────────────────
        elif path == "/api/classic-executor":
            cached = _cache_get("classic_executor")
            if cached:
                self._json(cached["data"])
            else:
                try:
                    sys.path.insert(0, str(BASE_DIR))
                    from classic_executor import get_executor_state
                    state = get_executor_state()
                    _cache_set("classic_executor", state)
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

        elif path == "/" or path == "/index.html":
            self._file(BASE_DIR / "monitor.html", "text/html")
        else:
            self.send_response(404)
            self.end_headers()

    def _get_query_param(self, name: str) -> str:
        params = urlparse(self.path).query
        qs = dict(parse_qsl(params))
        return qs.get(name)

    def _read_json_body(self):
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

        elif path == "/api/mode/check":
            try:
                sys.path.insert(0, str(BASE_DIR))
                from mode_manager import check_and_switch_mode
                result = check_and_switch_mode()
                self._json(result)
            except Exception as e:
                self._json({"error": str(e)})

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
        body = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-store")
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
        self.end_headers()
        self.wfile.write(body)


class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True


if __name__ == "__main__":
    print("正在初始化数据缓存...")
    _start_bg_refresh()
    server = ThreadedHTTPServer(("0.0.0.0", PORT), Handler)
    print(f"监控服务已启动: http://localhost:{PORT}")
    print(f"  - /api/state         5s 刷新")
    print(f"  - /api/yijing       60s 刷新")
    print(f"  - /api/screen-*     30s 刷新")
    print(f"  - /api/dreamos      15s 刷新")
    print(f"  Ctrl+C 停止")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n停止")
        server.shutdown()
