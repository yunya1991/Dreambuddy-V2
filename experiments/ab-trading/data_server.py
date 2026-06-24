#!/usr/bin/env python3
"""
监控页面数据服务器 — 提供 /api/state 接口
启动：python3 data_server.py
访问：http://localhost:8765
"""
import json, os, requests, warnings
from pathlib import Path
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse

warnings.filterwarnings("ignore")
BASE_DIR = Path(__file__).parent
LOG_A    = BASE_DIR / "logs" / "agent_a"
LOG_B    = BASE_DIR / "logs" / "agent_b"
PORT     = 8765
USER     = "0x93842F1ea62E7E3c71494d9EA69EfC4F2D6e9934"


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
USER_B = "0x9b56f46b0ac993bff2277cf6135f49c25c37d40b"   # Agent B 子账户


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

        # ── 静态文件服务 ────────────────────────────────────────────────
        elif path == "/" or path == "/index.html":
            self._file(BASE_DIR / "monitor.html", "text/html")
        else:
            self.send_response(404)
            self.end_headers()

    def _json(self, data):
        body = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(200)
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
        self.end_headers()
        self.wfile.write(body)


if __name__ == "__main__":
    server = HTTPServer(("0.0.0.0", PORT), Handler)
    print(f"✅ 监控服务已启动")
    print(f"   浏览器打开: http://localhost:{PORT}")
    print(f"   Ctrl+C 停止")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n停止")
