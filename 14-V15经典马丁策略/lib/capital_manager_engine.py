#!/usr/bin/env python3
"""
资金管理引擎 - 马丁策略统一资金管理模块

整合三大维度：
1. 回测引擎：基于历史数据统计各层加仓的触发频率和收益特征
2. 三屏趋势过滤：周线+日线MA104双周期趋势一致性检查，熊市禁止做多
3. 贝叶斯参数优化：基于回测数据优化资金分配参数（卡尔马比率最大化）

核心策略：底仓现货思维 + 黑天鹅加仓 + 趋势过滤
- 底仓22%资金 + 5倍杠杆 ≈ 110%现货敞口
- 加仓资金用于黑天鹅时拉低成本
- 止盈固定4%（BTC基准，其他币种按波动率放大）

运行模式：
- monthly: 每月运行一次完整优化流程（回测→趋势分析→贝叶斯优化→更新配置）
- status: 查看当前资金状态和最优参数
- trend <coin>: 查看某币种的趋势过滤状态
- api: 启动HTTP API服务，供其他系统调用

API接口（默认端口8770）：
- GET /status          - 获取资金管理整体状态
- GET /trend/<coin>    - 获取某币种趋势过滤状态
- GET /params          - 获取当前最优参数
- GET /check/<coin>    - 检查某币种是否允许开仓（综合资金+趋势+止损）
- POST /optimize       - 触发手动优化
"""
import json
import sys
import os
import time
import argparse
import threading
import subprocess
from datetime import datetime, timezone, timedelta
from pathlib import Path
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse

BASE_DIR = Path(__file__).parent  # lib/ 目录
STRATEGY_DIR = BASE_DIR.parent     # 14-V15经典马丁策略/ 目录
ROOT_DIR = STRATEGY_DIR.parent    # 项目根目录

sys.path.insert(0, str(BASE_DIR))

try:
    from config_loader import load_config, get_config, get_config_float, get_config_int, get_config_list
    load_config("v15ct")
except Exception:
    pass

ARTIFACTS_DIR = STRATEGY_DIR / "data" / "capital_manager"
ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)

STATE_FILE = ARTIFACTS_DIR / "engine_state.json"
OPTIMIZATION_HISTORY = ARTIFACTS_DIR / "optimization_history.json"
CONFIG_FILE = STRATEGY_DIR / "config" / ".env.v15ct"


class CapitalManagerEngine:
    """资金管理引擎 - 统一管理回测、趋势过滤、贝叶斯优化和资金分配"""
    
    def __init__(self):
        self.state = self._load_state()
        self._klines_cache = {}
    
    # ── 状态管理 ──────────────────────────────────────────────────────────
    
    def _load_state(self) -> dict:
        if STATE_FILE.exists():
            try:
                return json.loads(STATE_FILE.read_text())
            except:
                pass
        return {
            "last_optimization": None,
            "last_backtest": None,
            "current_params": self._get_default_params(),
            "optimization_count": 0,
        }
    
    def _save_state(self):
        STATE_FILE.write_text(json.dumps(self.state, indent=2, ensure_ascii=False))
    
    def _get_default_params(self) -> dict:
        return {
            "base_position_pct": get_config_float("BASE_POSITION_PCT", 0.22),
            "leverage": get_config_float("LEVERAGE", 5.0),
            "tp_pct_btc": get_config_float("BASE_TP_PCT", 0.04),
            "trend_filter_mode": get_config("TREND_FILTER_MODE", "none"),
            "trend_filter_period": get_config_int("TREND_FILTER_PERIOD", 200),
            "addon1_pct": get_config_float("ADDON1_PCT", 0.20),
            "addon2_pct": get_config_float("ADDON2_PCT", 0.05),
            "addon3_pct": get_config_float("ADDON3_PCT", 0.10),
            "max_concurrent_positions": get_config_int("MAX_CONCURRENT_POSITIONS", 6),
            "total_budget": get_config_float("TOTAL_BUDGET", 100),
            "max_base_holding_hours": get_config_float("V15_MAX_BASE_HOLDING_HOURS", 48.0),
            "max_post_addon_hours": get_config_float("V15_MAX_POST_ADDON_HOURS", 24.0),
            "golden_window_hours": get_config_float("V15_GOLDEN_WINDOW_HOURS", 12.0),
        }
    
    # ── 回测引擎 ──────────────────────────────────────────────────────────
    
    def run_backtest(self, coins=None) -> dict:
        """运行回测，统计各层加仓的触发频率和收益特征"""
        coins = coins or get_config_list("V15CT_COINS", ["BTC", "ETH", "SOL", "ARB", "OP"])
        
        try:
            core_path = str(STRATEGY_DIR / "core")
            if core_path not in sys.path:
                sys.path.insert(0, core_path)
            from v15_backtest import run_backtest as bt_run, fetch_klines, calc_30d_volatility
        except ImportError as e:
            return {"error": f"无法导入回测模块: {e}"}
        
        params = self.state.get("current_params", self._get_default_params())
        
        level_stats = {
            1: {"count": 0, "total_pnl": 0, "wins": 0, "losses": 0},
            2: {"count": 0, "total_pnl": 0, "wins": 0, "losses": 0},
            3: {"count": 0, "total_pnl": 0, "wins": 0, "losses": 0},
            4: {"count": 0, "total_pnl": 0, "wins": 0, "losses": 0},
        }
        
        coin_results = {}
        total_trades = 0
        
        btc_vol = 0.02
        btc_klines_1d = fetch_klines("BTC", "1d", 400)
        if btc_klines_1d:
            btc_vol = calc_30d_volatility(btc_klines_1d) or 0.02
        
        for coin in coins:
            klines = fetch_klines(coin, "4h", 1500)
            if not klines or len(klines) < 200:
                continue
            
            klines_1d = fetch_klines(coin, "1d", 400)
            coin_vol = calc_30d_volatility(klines_1d) if klines_1d else btc_vol
            vol_ratio = max(0.5, min(2.0, coin_vol / btc_vol)) if btc_vol > 0 else 1.0
            tp_pct = params["tp_pct_btc"] * vol_ratio
            
            capital_per_coin = params["total_budget"] / len(coins)
            base_usd = capital_per_coin * params["base_position_pct"]
            addon_total = capital_per_coin * (params["addon1_pct"] + params["addon2_pct"] + params["addon3_pct"])
            effective_base_pct = (base_usd + addon_total) / capital_per_coin
            
            result = bt_run(
                coin=coin, klines=klines, initial_capital=capital_per_coin,
                base_position_pct=effective_base_pct, max_addons=3,
                confidence_threshold=0, long_only=True, position_tf="4h",
                custom_tp_pct=tp_pct,
                trend_filter_mode=params["trend_filter_mode"],
                trend_filter_period=params["trend_filter_period"],
            )
            
            if "error" in result:
                continue
            
            m = result["metrics"]
            coin_results[coin] = {
                "total_return_pct": m.get("total_return_pct", 0),
                "max_drawdown_pct": m.get("max_drawdown_pct", 0),
                "sharpe_ratio": m.get("sharpe_ratio", 0),
                "win_rate": m.get("win_rate", 0),
                "total_trades": m.get("total_trades", 0),
                "level_distribution": m.get("level_distribution", {}),
            }
            total_trades += m.get("total_trades", 0)
            
            for trade in result.get("trades", []):
                level = trade.get("levels_used", 1)
                pnl = trade.get("pnl_pct", 0)
                level_stats[level]["count"] += 1
                level_stats[level]["total_pnl"] += pnl
                if pnl > 0:
                    level_stats[level]["wins"] += 1
                else:
                    level_stats[level]["losses"] += 1
        
        backtest_result = {
            "level_stats": level_stats,
            "total_trades": total_trades,
            "coin_results": coin_results,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        
        self.state["last_backtest"] = backtest_result
        self._save_state()
        
        return backtest_result
    
    # ── 趋势过滤器 ────────────────────────────────────────────────────────
    
    def check_trend(self, coin: str) -> dict:
        """检查某币种的三屏趋势过滤状态"""
        try:
            from strategy_params import check_trend_filter
        except ImportError:
            sys.path.insert(0, str(BASE_DIR))
            from strategy_params import check_trend_filter
        
        try:
            core_path = str(STRATEGY_DIR / "core")
            if core_path not in sys.path:
                sys.path.insert(0, core_path)
            from v15_backtest import fetch_klines
        except ImportError as e:
            return {"error": f"无法导入回测模块: {e}"}
        
        params = self.state.get("current_params", self._get_default_params())
        
        daily_klines = fetch_klines(coin, "1d", 400)
        weekly_klines = fetch_klines(coin, "1w", 200)
        
        if not daily_klines or not weekly_klines:
            return {"error": f"无法获取{coin}的日线/周线数据"}
        
        current_price = float(daily_klines[-1]["c"])
        
        result = check_trend_filter(
            current_price, daily_klines, weekly_klines,
            mode=params["trend_filter_mode"],
            period=params["trend_filter_period"],
        )
        
        result["coin"] = coin
        result["current_price"] = current_price
        return result
    
    def check_trend_batch(self, coins=None) -> dict:
        """批量检查趋势过滤状态"""
        coins = coins or get_config_list("V15CT_COINS", ["BTC", "ETH", "SOL"])
        results = {}
        for coin in coins:
            results[coin] = self.check_trend(coin)
        return results
    
    # ── 贝叶斯优化 ────────────────────────────────────────────────────────
    
    def run_optimization(self, coins=None, init_points=5, iterations=20) -> dict:
        """运行贝叶斯参数优化
        
        流程：
        1. 先运行回测，获取各层收益特征
        2. 基于回测数据运行贝叶斯优化
        3. 更新最优参数到状态和配置文件
        """
        coins = coins or ["BTC", "ETH", "SOL", "ARB", "OP"]
        
        print("阶段1: 运行回测，收集各层收益特征...")
        backtest = self.run_backtest(coins)
        if "error" in backtest:
            return backtest
        
        print("阶段2: 运行三轮反馈迭代优化...")
        try:
            from bayesian_optimizer import V15CapitalOptimizer
        except ImportError as e:
            return {"error": f"无法导入优化器: {e}"}
        
        optimizer = V15CapitalOptimizer(coins=coins, initial_capital=10000.0)
        best_params, round_results = optimizer.iterate_optimize(
            rounds=3,
            init_points=init_points,
            n_iter=iterations,
            save=True,
        )
        
        print("阶段3: 更新配置...")
        self.state["current_params"] = best_params
        self.state["last_optimization"] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "best_score": optimizer.best_score,
            "coins": coins,
            "init_points": init_points,
            "iterations": iterations,
            "mode": "three_round_iterative",
            "rounds": len(round_results),
        }
        self.state["optimization_count"] = self.state.get("optimization_count", 0) + 1
        self._save_state()
        
        self._update_config_file(best_params)
        
        self._append_optimization_history({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "params": best_params,
            "best_score": optimizer.best_score,
            "mode": "three_round_iterative",
            "round_results": round_results,
            "backtest_summary": {
                "total_trades": backtest.get("total_trades", 0),
                "level_stats": backtest.get("level_stats", {}),
            },
        })
        
        return {
            "best_params": best_params,
            "best_score": optimizer.best_score,
            "rounds": len(round_results),
            "round_results": round_results,
            "backtest_summary": {
                "total_trades": backtest.get("total_trades", 0),
                "level_stats": backtest.get("level_stats", {}),
            },
        }
    
    def _update_config_file(self, params: dict):
        """更新 .env.v15ct 配置文件中的参数"""
        if not CONFIG_FILE.exists():
            return
        
        content = CONFIG_FILE.read_text()
        replacements = {
            "BASE_POSITION_PCT": f'{params["base_position_pct"]}',
            "LEVERAGE": f'{params["leverage"]}',
            "ADDON1_PCT": f'{params["addon1_pct"]}',
            "ADDON2_PCT": f'{params["addon2_pct"]}',
            "ADDON3_PCT": f'{params["addon3_pct"]}',
            "MAX_CONCURRENT_POSITIONS": str(params["max_concurrent_positions"]),
            "TREND_FILTER_MODE": params.get("trend_filter_mode", "none"),
            "TREND_FILTER_PERIOD": str(params.get("trend_filter_period", 200)),
            "V15_MAX_BASE_HOLDING_HOURS": str(params.get("max_base_holding_hours", 48.0)),
            "V15_MAX_POST_ADDON_HOURS": str(params.get("max_post_addon_hours", 24.0)),
            "V15_GOLDEN_WINDOW_HOURS": str(params.get("golden_window_hours", 12.0)),
        }
        
        for key, val in replacements.items():
            lines = content.split("\n")
            for i, line in enumerate(lines):
                if line.strip().startswith(f"{key}="):
                    lines[i] = f"{key}={val}"
                    break
            content = "\n".join(lines)
        
        CONFIG_FILE.write_text(content)
    
    def _append_optimization_history(self, entry: dict):
        """追加优化历史记录"""
        history = []
        if OPTIMIZATION_HISTORY.exists():
            try:
                history = json.loads(OPTIMIZATION_HISTORY.read_text())
            except:
                pass
        history.append(entry)
        if len(history) > 50:
            history = history[-50:]
        OPTIMIZATION_HISTORY.write_text(json.dumps(history, indent=2, ensure_ascii=False))
    
    # ── 资金管理状态 ──────────────────────────────────────────────────────
    
    def get_status(self) -> dict:
        """获取资金管理整体状态"""
        params = self.state.get("current_params", self._get_default_params())
        
        base_usd = params["total_budget"] * params["base_position_pct"]
        addon1_usd = params["total_budget"] * params["addon1_pct"]
        addon2_usd = params["total_budget"] * params["addon2_pct"]
        addon3_usd = params["total_budget"] * params["addon3_pct"]
        total_per_position = base_usd + addon1_usd + addon2_usd + addon3_usd
        
        try:
            from capital_manager import calculate_capital_allocation
            capital_status = calculate_capital_allocation()
        except Exception:
            capital_status = None
        
        return {
            "strategy": "底仓现货思维 + 黑天鹅加仓 + 三屏趋势过滤",
            "params": params,
            "capital_allocation": {
                "base_usd": round(base_usd, 2),
                "addon1_usd": round(addon1_usd, 2),
                "addon2_usd": round(addon2_usd, 2),
                "addon3_usd": round(addon3_usd, 2),
                "total_per_position": round(total_per_position, 2),
                "addon_total": round(addon1_usd + addon2_usd + addon3_usd, 2),
            },
            "holding_time": {
                "max_base_holding_hours": params.get("max_base_holding_hours", 48.0),
                "max_post_addon_hours": params.get("max_post_addon_hours", 24.0),
                "golden_window_hours": params.get("golden_window_hours", 12.0),
            },
            "leverage_exposure": f'{params["base_position_pct"] * params["leverage"] * 100:.0f}% 现货敞口',
            "last_optimization": self.state.get("last_optimization"),
            "last_backtest": self.state.get("last_backtest", {}).get("timestamp") if self.state.get("last_backtest") else None,
            "optimization_count": self.state.get("optimization_count", 0),
            "live_capital": capital_status,
        }
    
    def check_open_permission(self, coin: str) -> dict:
        """综合检查某币种是否允许开仓（资金+趋势+止损）"""
        result = {
            "coin": coin,
            "allowed": True,
            "reasons": [],
            "checks": {},
        }
        
        # 1. 趋势过滤检查
        trend = self.check_trend(coin)
        result["checks"]["trend_filter"] = trend
        if trend.get("blocked", False):
            result["allowed"] = False
            result["reasons"].append(f"趋势过滤: {trend.get('reason', '')}")
        
        # 2. 资金检查
        try:
            from capital_manager import calculate_capital_allocation
            cap = calculate_capital_allocation()
            result["checks"]["capital"] = {
                "can_open": cap.get("can_open_new", False),
                "available_balance": cap.get("available_balance", 0),
                "risk_level": cap.get("risk_level", "UNKNOWN"),
            }
            if not cap.get("can_open_new", False):
                result["allowed"] = False
                result["reasons"].append(f"资金不足: 余额${cap.get('available_balance', 0):.2f}")
        except Exception as e:
            result["checks"]["capital"] = {"error": str(e)}
        
        # 3. 策略参数检查（MA200止损）
        try:
            from strategy_params import get_coin_strategy_params
            params = get_coin_strategy_params(coin, "LONG")
            sl = params.get("stop_loss", {})
            result["checks"]["stop_loss"] = {
                "triggered": sl.get("triggered", False),
                "type": sl.get("type", ""),
            }
            if sl.get("triggered", False):
                result["allowed"] = False
                result["reasons"].append(f"MA200止损: {sl.get('type', '')}")
        except Exception as e:
            result["checks"]["stop_loss"] = {"error": str(e)}
        
        return result
    
    # ── 月度运行 ──────────────────────────────────────────────────────────
    
    def run_monthly(self, coins=None) -> dict:
        """月度运行入口：完整的三轮反馈优化流程
        
        流程：
        1. 回测（统计各层收益特征 + 基线数据）
        2. 趋势过滤分析（当前各币种趋势状态）
        3. 三轮反馈迭代优化（回测→贝叶斯优化→回测验证，三轮收敛）
        4. 更新配置文件
        5. 生成月度报告
        """
        print(f"\n{'='*70}")
        print(f"  资金管理引擎 - 月度运行（三轮反馈优化）")
        print(f"  时间: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
        print(f"{'='*70}\n")
        
        coins = coins or ["BTC", "ETH", "SOL", "ARB", "OP"]
        
        # 阶段1: 回测
        print("[1/4] 运行回测...")
        backtest = self.run_backtest(coins)
        
        # 阶段2: 趋势分析
        print("\n[2/4] 趋势过滤分析...")
        trend_status = self.check_trend_batch(coins[:5])
        for coin, ts in trend_status.items():
            if "error" not in ts:
                print(f"  {coin}: {'blocked' if ts.get('blocked') else 'allowed'} - {ts.get('reason', '')}")
        
        # 阶段3: 贝叶斯优化
        print("\n[3/4] 贝叶斯参数优化...")
        opt_result = self.run_optimization(coins, init_points=5, iterations=20)
        
        # 阶段4: 生成报告
        print("\n[4/4] 生成月度报告...")
        report = self._generate_monthly_report(backtest, trend_status, opt_result)
        
        report_file = ARTIFACTS_DIR / f"monthly_report_{datetime.now(timezone.utc).strftime('%Y%m%d')}.json"
        report_file.write_text(json.dumps(report, indent=2, ensure_ascii=False))
        
        print(f"\n  月度报告已保存: {report_file}")
        print(f"{'='*70}\n")
        
        return report
    
    def _generate_monthly_report(self, backtest, trend_status, opt_result):
        params = self.state.get("current_params", self._get_default_params())
        
        return {
            "report_date": datetime.now(timezone.utc).isoformat(),
            "strategy": "底仓现货思维 + 黑天鹅加仓 + 三屏趋势过滤",
            "backtest_summary": {
                "total_trades": backtest.get("total_trades", 0),
                "level_stats": backtest.get("level_stats", {}),
                "coin_results": backtest.get("coin_results", {}),
            },
            "trend_status": trend_status,
            "optimization_result": {
                "best_params": opt_result.get("best_params", params),
                "best_score": opt_result.get("best_score", 0),
            },
            "current_params": params,
            "capital_allocation": {
                "base_pct": params["base_position_pct"],
                "leverage": params["leverage"],
                "addon1_pct": params["addon1_pct"],
                "addon2_pct": params["addon2_pct"],
                "addon3_pct": params["addon3_pct"],
                "max_positions": params["max_concurrent_positions"],
                "max_base_holding_hours": params.get("max_base_holding_hours", 48.0),
                "max_post_addon_hours": params.get("max_post_addon_hours", 24.0),
                "golden_window_hours": params.get("golden_window_hours", 12.0),
            },
        }
    
    def should_run_monthly(self) -> bool:
        """检查是否应该运行月度优化（每月1号运行）"""
        now = datetime.now(timezone.utc)
        last_opt = self.state.get("last_optimization")
        
        if now.day != 1:
            return False
        
        if last_opt:
            last_date = last_opt.get("timestamp", "")[:10]
            today_str = now.strftime("%Y-%m-%d")
            if last_date == today_str:
                return False
        
        return True


# ── HTTP API 服务 ────────────────────────────────────────────────────────

class CapitalManagerAPI(BaseHTTPRequestHandler):
    """HTTP API 处理器"""
    
    engine = None
    
    def _send_json(self, data, code=200):
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.end_headers()
        self.wfile.write(json.dumps(data, indent=2, ensure_ascii=False).encode())
    
    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        
        if path == "/status":
            self._send_json(self.engine.get_status())
        
        elif path == "/params":
            params = self.engine.state.get("current_params", {})
            self._send_json(params)
        
        elif path.startswith("/trend/"):
            coin = path.split("/trend/")[-1].upper()
            self._send_json(self.engine.check_trend(coin))
        
        elif path.startswith("/check/"):
            coin = path.split("/check/")[-1].upper()
            self._send_json(self.engine.check_open_permission(coin))
        
        elif path == "/history":
            if OPTIMIZATION_HISTORY.exists():
                self._send_json(json.loads(OPTIMIZATION_HISTORY.read_text()))
            else:
                self._send_json([])
        
        else:
            self._send_json({"error": "unknown endpoint", "endpoints": [
                "/status", "/params", "/trend/<coin>", "/check/<coin>", "/history"
            ]}, 404)
    
    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path
        
        if path == "/optimize":
            self._send_json({"message": "优化已启动，请稍后查看 /status"})
            threading.Thread(target=self.engine.run_optimization, daemon=True).start()
        else:
            self._send_json({"error": "unknown endpoint"}, 404)
    
    def log_message(self, format, *args):
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        print(f"[{ts}] {args[0]}")


# ── CLI 入口 ─────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="资金管理引擎 - 马丁策略统一资金管理")
    parser.add_argument("mode", choices=["monthly", "status", "trend", "check", "api", "backtest"],
                        help="运行模式")
    parser.add_argument("--coin", type=str, default=None, help="币种（trend/check模式）")
    parser.add_argument("--coins", nargs="+", default=None, help="币种列表")
    parser.add_argument("--port", type=int, default=8770, help="API端口")
    parser.add_argument("--init-points", type=int, default=5, help="贝叶斯优化初始点数")
    parser.add_argument("--iterations", type=int, default=20, help="贝叶斯优化迭代次数")
    args = parser.parse_args()
    
    engine = CapitalManagerEngine()
    
    if args.mode == "monthly":
        result = engine.run_monthly(args.coins)
        print(json.dumps(result, indent=2, ensure_ascii=False))
    
    elif args.mode == "status":
        status = engine.get_status()
        print(json.dumps(status, indent=2, ensure_ascii=False))
    
    elif args.mode == "trend":
        if args.coin:
            result = engine.check_trend(args.coin.upper())
        else:
            result = engine.check_trend_batch(args.coins)
        print(json.dumps(result, indent=2, ensure_ascii=False))
    
    elif args.mode == "check":
        if not args.coin:
            print("请指定 --coin 参数")
            sys.exit(1)
        result = engine.check_open_permission(args.coin.upper())
        print(json.dumps(result, indent=2, ensure_ascii=False))
    
    elif args.mode == "backtest":
        result = engine.run_backtest(args.coins)
        print(json.dumps(result, indent=2, ensure_ascii=False))
    
    elif args.mode == "api":
        CapitalManagerAPI.engine = engine
        server = HTTPServer(("0.0.0.0", args.port), CapitalManagerAPI)
        print(f"资金管理API服务启动: http://localhost:{args.port}")
        print(f"  GET  /status          - 资金管理状态")
        print(f"  GET  /params          - 当前最优参数")
        print(f"  GET  /trend/<coin>    - 趋势过滤状态")
        print(f"  GET  /check/<coin>    - 开仓许可检查")
        print(f"  GET  /history         - 优化历史")
        print(f"  POST /optimize        - 触发手动优化")
        server.serve_forever()


if __name__ == "__main__":
    main()
