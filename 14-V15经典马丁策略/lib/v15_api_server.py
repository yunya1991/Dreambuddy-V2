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
from datetime import datetime, timezone
from pathlib import Path
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn
from urllib.parse import urlparse, parse_qs

BASE_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(BASE_DIR / "core"))
sys.path.insert(0, str(BASE_DIR / "lib"))

from v15_signal import v15_decision
from v15_backtest import run_backtest
from capital_manager_engine import CapitalManagerEngine
from capital_manager import calculate_single_position_cost, calculate_capital_allocation, get_account_balance, get_current_positions
from strategy_params import get_coin_strategy_params

# 马丁策略固定初始资金（USDT）—— 小额观测实际表现
V15_INITIAL_CAPITAL = 150.0


def _load_v15_baseline():
    """加载或创建马丁策略每日基准快照（从今天起以 150 为基准）"""
    baseline_file = BASE_DIR / "data" / "account_baseline.json"
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    baseline = None
    if baseline_file.exists():
        try:
            with open(baseline_file) as f:
                baseline = json.load(f)
        except Exception:
            baseline = None
    # 日期变更或不存在 → 初始化新基准（OKX 权益待首次成功时填充）
    if not baseline or baseline.get("baseline_date") != today:
        baseline = {
            "baseline_date": today,
            "initial_capital": V15_INITIAL_CAPITAL,
            "okx_total_eq_baseline": None,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        # 立即保存（固定基准日期为今天），OKX 恢复后补充 okx_total_eq_baseline
        _save_v15_baseline(baseline)
    return baseline


def _save_v15_baseline(baseline):
    try:
        with open(BASE_DIR / "data" / "account_baseline.json", "w") as f:
            json.dump(baseline, f, indent=2, ensure_ascii=False)
    except Exception:
        pass


def _load_v15_local_positions():
    """从 v15_state.json 读取本地持仓（OKX 不可用时降级用）"""
    state_file = BASE_DIR / "data" / "v15_state.json"
    if not state_file.exists():
        return []
    try:
        with open(state_file) as f:
            state = json.load(f)
        positions = state.get("positions", {}) or {}
        result = []
        for coin, p in positions.items():
            result.append({
                "coin": coin,
                "inst_id": p.get("inst_id", f"{coin}-USDT-SWAP"),
                "direction": p.get("direction", "LONG"),
                "entry_price": float(p.get("entry_price", 0) or 0),
                "sz": float(p.get("sz", 0) or 0),
                "open_time": p.get("open_time", ""),
                "per_coin_budget": float(p.get("per_coin_budget", 0) or 0),
                "addons": int(p.get("addons", 0) or 0),
                "source": "local",
            })
        return result
    except Exception:
        return []


class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True


class V15APIHandler(BaseHTTPRequestHandler):
    def _send_json(self, data, code=200):
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(data, indent=2, ensure_ascii=False).encode())

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

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

            elif path == "/api/v15-ct/account-overview":
                self._handle_account_overview()

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
            coin_params = get_coin_strategy_params(coin, "LONG")

            stop_loss = coin_params.get("stop_loss", {})
            vol_params = coin_params.get("vol_params", {})

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
                "stop_loss_triggered": stop_loss.get("is_triggered", False),
                "stop_loss_type": stop_loss.get("stop_type", "--"),
                "stop_loss_price": stop_loss.get("stop_loss_price"),
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

    def _handle_account_overview(self):
        """马丁策略账户总览：从今天起以 150 USDT 为基准，计算策略自身收益

        策略自身收益 = OKX 实时权益 - 基准日 OKX 权益（排除历史累计，只看今天起的变化）
          - 初始资金：V15_INITIAL_CAPITAL (150 USDT)
          - 基准 OKX 权益：今天首次成功获取的 OKX total_eq
          - 总盈亏 = 当前OKX权益 - 基准OKX权益
          - 当前虚拟余额 = 150 + 总盈亏
          - 涨跌幅 = 总盈亏 / 150 × 100%
          - 未实现盈亏 = 当前持仓 upl 之和（OKX 实时）
          - 已实现盈亏 = 总盈亏 - 未实现盈亏
        OKX 不可用时降级：用 v15_state.json 本地持仓展示，盈亏显示为待更新
        """
        try:
            baseline = _load_v15_baseline()

            # ── OKX 实时账户余额 ──
            balance = get_account_balance()
            live_ok = balance.get("ok", False)
            live_error = balance.get("error", "") if not live_ok else ""

            current_okx_eq = None
            avail_balance = None
            if live_ok:
                current_okx_eq = float(balance.get("total_eq", 0) or 0)
                avail_balance = float(balance.get("avail_balance", 0) or 0)
                # 首次成功获取 OKX 权益时，写入基准（今天起点）
                if baseline.get("okx_total_eq_baseline") is None:
                    baseline["okx_total_eq_baseline"] = current_okx_eq
                    baseline["created_at"] = datetime.now(timezone.utc).isoformat()
                    _save_v15_baseline(baseline)

            baseline_eq = baseline.get("okx_total_eq_baseline")

            # ── 持仓：优先 OKX 实时，降级用 v15_state.json ──
            okx_positions = get_current_positions() if live_ok else []
            use_local = (not live_ok) or (len(okx_positions) == 0)
            positions = okx_positions if not use_local else _load_v15_local_positions()

            open_positions_count = len(positions)
            positions_detail = []
            unrealized_pnl_sum = 0.0
            has_realtime_upl = False
            for p in positions:
                upl = float(p.get("unrealized_pnl", 0) or 0)
                is_local = p.get("source") == "local"
                if not is_local:
                    has_realtime_upl = True
                    unrealized_pnl_sum += upl
                positions_detail.append({
                    "coin": p.get("coin", p.get("symbol", "")),
                    "inst_id": p.get("inst_id", ""),
                    "direction": p.get("direction", ""),
                    "upl": upl if not is_local else None,
                    "upl_ratio": float(p.get("upl_ratio", 0) or 0) if not is_local else None,
                    "mark_px": float(p.get("mark_price", 0) or 0) if not is_local else None,
                    "entry_price": float(p.get("entry_price", 0) or 0),
                    "sz": float(p.get("pos_sz", p.get("sz", 0)) or 0),
                    "lever": p.get("lever", ""),
                    "source": p.get("source", "okx_live"),
                    "open_time": p.get("open_time", ""),
                })

            # ── 本地统计（v15_state.json）──
            total_trades = 0
            total_wins = 0
            consecutive_losses = 0
            state_file = BASE_DIR / "data" / "v15_state.json"
            if state_file.exists():
                try:
                    with open(state_file) as f:
                        state = json.load(f)
                    total_trades = int(state.get("total_trades", 0) or 0)
                    total_wins = int(state.get("total_wins", 0) or 0)
                    consecutive_losses = int(state.get("consecutive_losses", 0) or 0)
                except Exception:
                    pass

            # ── 盈亏计算（基于基准 OKX 权益差值 = 策略自身收益）──
            total_pnl = None
            current_balance = None
            pnl_pct = None
            realized_pnl = None
            if current_okx_eq is not None and baseline_eq is not None:
                total_pnl = current_okx_eq - baseline_eq
                current_balance = V15_INITIAL_CAPITAL + total_pnl
                pnl_pct = (total_pnl / V15_INITIAL_CAPITAL) * 100 if V15_INITIAL_CAPITAL > 0 else 0
                # 拆分已实现 / 未实现（需要实时持仓 upl）
                if has_realtime_upl:
                    realized_pnl = total_pnl - unrealized_pnl_sum
                # 不可用时 realized_pnl 保持 None

            win_rate = (total_wins / total_trades) if total_trades > 0 else 0.0

            # 基准状态提示
            baseline_note = ""
            if baseline_eq is None:
                baseline_note = "今日基准尚未建立（等待 OKX 首次连接）"
            else:
                baseline_note = f"基准日 {baseline.get('baseline_date')} 起 OKX 权益 {round(baseline_eq, 2)}"

            response = {
                "strategy": "v15_martin",
                "strategy_name": "V15 经典马丁策略",
                "initial_capital": V15_INITIAL_CAPITAL,
                "baseline_date": baseline.get("baseline_date"),
                "baseline_okx_eq": round(baseline_eq, 2) if baseline_eq is not None else None,
                "baseline_note": baseline_note,
                "current_balance": round(current_balance, 2) if current_balance is not None else None,
                "avail_balance": round(avail_balance, 2) if avail_balance is not None else None,
                "total_pnl": round(total_pnl, 2) if total_pnl is not None else None,
                "pnl_pct": round(pnl_pct, 2) if pnl_pct is not None else None,
                "realized_pnl": round(realized_pnl, 2) if realized_pnl is not None else None,
                "unrealized_pnl": round(unrealized_pnl_sum, 2) if has_realtime_upl else None,
                "total_trades": total_trades,
                "win_count": total_wins,
                "win_rate": round(win_rate, 4),
                "win_rate_pct": round(win_rate * 100, 2),
                "consecutive_losses": consecutive_losses,
                "open_positions": open_positions_count,
                "positions_detail": positions_detail,
                "live_ok": live_ok,
                "live_error": live_error,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            self._send_json(response)
        except Exception as e:
            self._send_json({"error": str(e), "strategy": "v15_martin",
                             "initial_capital": V15_INITIAL_CAPITAL})

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
                coin_params = get_coin_strategy_params(coin, "LONG")

                stop_loss = coin_params.get("stop_loss", {})
                vol_params = coin_params.get("vol_params", {})

                decisions.append({
                    "symbol": coin,
                    "action": result.get("action", "WAIT"),
                    "confidence": result.get("confidence", 0),
                    "stop_loss_triggered": stop_loss.get("is_triggered", False),
                    "stop_loss_type": stop_loss.get("stop_type", "--"),
                    "stop_loss_price": stop_loss.get("stop_loss_price"),
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
            allocation = calculate_capital_allocation()
            cost = calculate_single_position_cost()

            balance = allocation.get("balance", {})
            calc = allocation.get("calculations", {})
            rec = allocation.get("recommendations", {})
            params = allocation.get("parameters", {})

            addon_details = cost.get("addon_details", [])
            addon_costs = [
                {"cost_usd": addon_details[0]["cost_usd"] if len(addon_details) > 0 else 0},
                {"cost_usd": addon_details[1]["cost_usd"] if len(addon_details) > 1 else 0},
                {"cost_usd": addon_details[2]["cost_usd"] if len(addon_details) > 2 else 0},
            ]

            response = {
                "balance": {
                    "total_eq": balance.get("total_eq", 0),
                    "avail_balance": balance.get("avail_balance", 0),
                },
                "calculations": {
                    "current_positions_count": calc.get("current_positions_count", 0),
                    "margin_usage_pct": calc.get("margin_usage_pct", 0),
                },
                "recommendations": {
                    "risk_level": rec.get("risk_level", "MEDIUM"),
                    "allow_open_new_position": rec.get("allow_open_new_position", True),
                    "allow_addon": rec.get("allow_addon", True),
                    "advice": rec.get("advice", "V15经典马丁策略资金管理建议"),
                },
                "single_position_cost": {
                    "base_usd": round(cost.get("base_usd", 0), 2),
                    "addon_details": addon_costs,
                    "total_cost_usd": round(cost.get("total_cost_usd", 0), 2),
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

    server = ThreadedHTTPServer(("0.0.0.0", args.port), V15APIHandler)
    print(f"V15经典马丁策略 API服务启动: http://localhost:{args.port} (多线程模式)")
    print(f"  GET  /api/v15-ct/decision?coin=BTC - 单币种决策信号")
    print(f"  GET  /api/v15-ct/status - 策略状态")
    print(f"  GET  /api/v15-ct/backtest?coin=BTC - 回测结果")
    print(f"  GET  /api/v15-ct/decisions - 多币种决策")
    print(f"  GET  /api/v15-ct/account-overview - 账户总览（初始资金150）")
    print(f"  GET  /api/capital/allocation - 资金分配")
    print(f"  GET  /api/capital/signal-trigger - 信号触发状态")
    print(f"  GET  /health - 健康检查")
    server.serve_forever()


if __name__ == "__main__":
    main()
