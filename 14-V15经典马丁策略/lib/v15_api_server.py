#!/usr/bin/env python3
"""
V15经典马丁策略 HTTP API服务
支持 monitor.html 的 V15CT tab 调用

API接口:
- GET /api/v15-ct/decision?coin=BTC - 获取单币种决策信号
- GET /api/v15-ct/status - 获取策略状态
- GET /api/v15-ct/backtest?coin=BTC - 获取回测结果
- GET /api/v15-ct/decisions - 获取多币种决策
- GET /api/capital/allocation - 资金分配
- GET /api/capital/signal-trigger - 信号触发状态
"""
import json, sys, threading, time
from pathlib import Path
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

BASE_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(BASE_DIR / "core"))
sys.path.insert(0, str(BASE_DIR / "lib"))

from v15_signal import v15_decision
from v15_backtest import run_backtest
from capital_manager_engine import CapitalManagerEngine
from strategy_params import get_dynamic_stop_loss, get_vol_adjusted_params


class V15APIHandler(BaseHTTPRequestHandler):
    def _send_json(self, data, code=200):
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(data, indent=2, ensure_ascii=False).encode())

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        params = parse_qs(parsed.query)

        try:
            if path == "/api/v15-ct/decision":
                coin = params.get("coin", ["BTC"])[0].upper()
                self._handle_decision(coin)

            elif path == "/api/v15-ct/status":
                self._handle_status()

            elif path == "/api/v15-ct/backtest":
                coin = params.get("coin", ["BTC"])[0].upper()
                self._handle_backtest(coin)

            elif path == "/api/v15-ct/decisions":
                self._handle_decisions()

            elif path == "/api/capital/allocation":
                self._handle_capital_allocation()

            elif path == "/api/capital/signal-trigger":
                self._handle_signal_trigger()

            elif path == "/health":
                self._send_json({"status": "ok", "service": "v15-api"})

            else:
                self._send_json({"error": "unknown endpoint"}, 404)

        except Exception as e:
            self._send_json({"error": str(e)}, 500)

    def _handle_decision(self, coin):
        try:
            result = v15_decision(f"{coin}-USDT")
            stop_loss = get_dynamic_stop_loss(f"{coin}-USDT")
            vol_params = get_vol_adjusted_params(coin)

            response = {
                "action": result.get("action", "WAIT"),
                "confidence": result.get("confidence", 0),
                "reasons": result.get("reasons", []),
                "mode": "v15",
                "vol_mult": result.get("vol_mult", 1.0),
                "position": result.get("position", "IN_ZONE"),
                "rsi": result.get("rsi"),
                "fib_zone": result.get("fib_zone"),
                "trend_signal": result.get("trend_signal"),
                "boll_signal": result.get("boll_signal"),
                "stop_loss_triggered": stop_loss.get("triggered", False),
                "stop_loss_type": stop_loss.get("type", "--"),
                "stop_loss_price": stop_loss.get("price"),
                "current_price": result.get("current_price"),
                "take_profit_pct": vol_params.get("tp_pct", 4.0),
                "addon_pct": vol_params.get("addon_pct", 8.0),
            }
            self._send_json(response)
        except Exception as e:
            self._send_json({"error": str(e), "action": "WAIT", "confidence": 0})

    def _handle_status(self):
        try:
            engine = CapitalManagerEngine()
            status = engine.get_status()

            response = {
                "auto_execute": True,
                "v15_ct_positions": [],
                "current_params": status.get("current_params", {}),
                "optimization_status": status.get("optimization_status", {}),
            }
            self._send_json(response)
        except Exception as e:
            self._send_json({"error": str(e), "auto_execute": False, "v15_ct_positions": []})

    def _handle_backtest(self, coin):
        try:
            result = run_backtest(coin)
            if "error" in result:
                self._send_json({"error": result["error"]})
            else:
                metrics = result.get("metrics", {})
                self._send_json({
                    "metrics": {
                        "total_return_pct": round(metrics.get("total_return_pct", 0), 2),
                        "total_trades": metrics.get("total_trades", 0),
                        "win_rate": metrics.get("win_rate", 0),
                        "profit_factor": round(metrics.get("profit_factor", 0), 2),
                        "max_drawdown_pct": round(metrics.get("max_drawdown_pct", 0), 2),
                        "sharpe_ratio": round(metrics.get("sharpe_ratio", 0), 4),
                        "avg_bars_held": metrics.get("avg_bars_held", 0),
                    },
                    "trades": result.get("trades", []),
                })
        except Exception as e:
            self._send_json({"error": str(e)})

    def _handle_decisions(self):
        coins = ["BTC", "ETH", "SOL", "ARB", "OP", "UNI", "HYPE", "OKB"]
        decisions = []

        for coin in coins:
            try:
                result = v15_decision(f"{coin}-USDT")
                stop_loss = get_dynamic_stop_loss(f"{coin}-USDT")
                vol_params = get_vol_adjusted_params(coin)

                decisions.append({
                    "symbol": coin,
                    "action": result.get("action", "WAIT"),
                    "confidence": result.get("confidence", 0),
                    "stop_loss_triggered": stop_loss.get("triggered", False),
                    "stop_loss_type": stop_loss.get("type", "--"),
                    "stop_loss_price": stop_loss.get("price"),
                    "take_profit_pct": vol_params.get("tp_pct", 4.0),
                    "addon_pct": vol_params.get("addon_pct", 8.0),
                    "vol_ratio": result.get("vol_mult", 1.0),
                })
            except Exception:
                decisions.append({
                    "symbol": coin,
                    "action": "WAIT",
                    "confidence": 0,
                    "stop_loss_triggered": False,
                    "stop_loss_type": "--",
                    "stop_loss_price": None,
                    "take_profit_pct": 4.0,
                    "addon_pct": 8.0,
                    "vol_ratio": 1.0,
                })

        self._send_json({"decisions": decisions})

    def _handle_capital_allocation(self):
        try:
            engine = CapitalManagerEngine()
            status = engine.get_status()
            params = status.get("current_params", {})

            response = {
                "balance": {
                    "total_eq": 0,
                    "avail_balance": 0,
                },
                "calculations": {
                    "current_positions_count": 0,
                    "margin_usage_pct": 0,
                },
                "recommendations": {
                    "risk_level": "MEDIUM",
                    "allow_open_new_position": True,
                    "allow_addon": True,
                    "advice": "V15经典马丁策略资金管理建议",
                },
                "single_position_cost": {
                    "base_usd": 0,
                    "addon_details": [
                        {"cost_usd": 0},
                        {"cost_usd": 0},
                        {"cost_usd": 0},
                    ],
                    "total_cost_usd": 0,
                },
                "parameters": {
                    "max_concurrent_positions": params.get("max_concurrent_positions", 6),
                },
            }
            self._send_json(response)
        except Exception as e:
            self._send_json({"error": str(e)})

    def _handle_signal_trigger(self):
        coins = ["BTC", "ETH", "SOL", "ARB", "OP", "UNI", "HYPE", "OKB"]
        result = {}

        for coin in coins:
            try:
                decision = v15_decision(f"{coin}-USDT")
                result[coin] = {
                    "can_trigger": decision.get("action") == "OPEN_BULL",
                    "has_position": False,
                }
            except Exception:
                result[coin] = {
                    "can_trigger": False,
                    "has_position": False,
                }

        self._send_json({"coins": result})

    def log_message(self, format, *args):
        ts = time.strftime("%Y-%m-%d %H:%M:%S")
        print(f"[{ts}] V15 API: {args[0]}")


def main():
    import argparse
    parser = argparse.ArgumentParser(description="V15经典马丁策略 HTTP API服务")
    parser.add_argument("--port", type=int, default=8771, help="API端口")
    args = parser.parse_args()

    server = HTTPServer(("0.0.0.0", args.port), V15APIHandler)
    print(f"V15经典马丁策略 API服务启动: http://localhost:{args.port}")
    print(f"  GET  /api/v15-ct/decision?coin=BTC - 单币种决策信号")
    print(f"  GET  /api/v15-ct/status - 策略状态")
    print(f"  GET  /api/v15-ct/backtest?coin=BTC - 回测结果")
    print(f"  GET  /api/v15-ct/decisions - 多币种决策")
    print(f"  GET  /api/capital/allocation - 资金分配")
    print(f"  GET  /api/capital/signal-trigger - 信号触发状态")
    print(f"  GET  /health - 健康检查")
    server.serve_forever()


if __name__ == "__main__":
    main()
