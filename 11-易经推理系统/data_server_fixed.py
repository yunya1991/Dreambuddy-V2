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
import json, os, requests, warnings, subprocess, sys, threading, time
from pathlib import Path
from socketserver import ThreadingMixIn
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qsl

warnings.filterwarnings("ignore")
os.environ["NO_PROXY"] = "localhost,127.0.0.1"

BASE_DIR = Path(__file__).parent / "_monitor"
LOG_A    = BASE_DIR / "logs" / "agent_a"
LOG_B    = BASE_DIR / "logs" / "agent_b"
PORT     = 8765

BCRM_REPO = Path(os.environ.get(
    "BCRM_REPO",
    "/Users/zhangjiangtao/dream-multiskill-v2",
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
        time.sleep(interval)


def _start_bg_refresh():
    threads = [
        threading.Thread(target=_bg_refresh_state, args=(5,), daemon=True),
        threading.Thread(target=_bg_refresh_yijing, args=(60,), daemon=True),
        threading.Thread(target=_bg_refresh_screen, args=(30,), daemon=True),
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

        elif path == "/" or path == "/index.html":
            self._file(BASE_DIR / "monitor.html", "text/html")
        else:
            self.send_response(404)
            self.end_headers()

    def _get_query_param(self, name: str) -> str:
        params = urlparse(self.path).query
        qs = dict(parse_qsl(params))
        return qs.get(name)

    def _json(self, data):
        body = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(200)
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
    print(f"  - /api/state        5s 刷新")
    print(f"  - /api/yijing      60s 刷新")
    print(f"  - /api/screen-*    30s 刷新")
    print(f"  Ctrl+C 停止")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n停止")
        server.shutdown()
