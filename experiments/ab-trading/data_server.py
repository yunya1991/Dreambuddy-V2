#!/usr/bin/env python3
"""
监控页面数据服务器 — 提供 /api/state 接口
启动：python3 data_server.py
访问：http://localhost:8765
"""
import json, os, requests, warnings, subprocess, subprocess, sys
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

        # ── API: 易经推理模型状态 ────────────────────────────────────────
        elif path == "/api/yijing":
            yijing_data = get_yijing_state()
            trading_data = get_yijing_trading_state()
            self._json({**yijing_data, "trading": trading_data})

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
        body = json.dumps(data, ensure_ascii=False).encode()
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
