#!/usr/bin/env python3
"""
简单回测引擎 — 用于验证进化提议的有效性
基于历史K线数据进行快速回测，评估策略改进效果
"""
import json, os, time, requests, warnings
from pathlib import Path
from typing import Dict, List, Tuple, Optional
from datetime import datetime, timezone

warnings.filterwarnings("ignore")

BASE_DIR = Path(__file__).parent.parent.parent
DATA_DIR = BASE_DIR / "data" / "evolution"
DATA_DIR.mkdir(parents=True, exist_ok=True)


class SimpleBacktestEngine:
    """
    简单回测引擎
    支持：
    - 从Hyperliquid获取历史K线
    - 基于规则策略的快速回测
    - 多指标评估（胜率、盈亏比、最大回撤、夏普比率）
    """

    def __init__(self, proxies: Optional[Dict] = None):
        self.proxies = proxies
        self.cache_dir = DATA_DIR / "kline_cache"
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def fetch_historical_klines(
        self, coin: str, interval: str = "1h", limit: int = 500
    ) -> List[Dict]:
        """
        获取历史K线数据（带缓存）
        """
        cache_file = self.cache_dir / f"{coin}_{interval}_{limit}.json"

        if cache_file.exists():
            try:
                with open(cache_file) as f:
                    cached = json.load(f)
                cache_age = time.time() - cached.get("cached_at", 0)
                if cache_age < 3600:
                    return cached.get("data", [])
            except Exception:
                pass

        try:
            s = requests.Session()
            s.trust_env = False
            now_ms = int(time.time() * 1000)
            start_ms = now_ms - limit * 3600 * 1000

            r = s.post(
                "https://api.hyperliquid.xyz/info",
                json={
                    "type": "candleSnapshot",
                    "req": {
                        "coin": coin,
                        "interval": interval,
                        "startTime": start_ms,
                        "endTime": now_ms,
                    },
                },
                timeout=15,
            )
            data = r.json()

            with open(cache_file, "w") as f:
                json.dump({"cached_at": time.time(), "data": data}, f)

            return data
        except Exception as e:
            print(f"[回测] 获取K线失败: {e}")
            return []

    def run_backtest(
        self,
        coin: str,
        strategy_params: Dict,
        klines: Optional[List[Dict]] = None,
    ) -> Dict:
        """
        运行回测

        strategy_params 支持的参数：
        - momentum_threshold: 动量阈值（默认2%）
        - volume_threshold: 量比阈值（默认1.2）
        - rsi_oversold: RSI超卖阈值（默认40）
        - rsi_overbought: RSI超买阈值（默认60）
        - stop_loss_pct: 止损比例（默认0.04）
        - take_profit_pct: 止盈比例（默认0.08）
        - use_ema_cross: 是否使用EMA交叉（默认True）
        """
        if klines is None:
            klines = self.fetch_historical_klines(coin)

        if len(klines) < 50:
            return {"error": "K线数据不足", "trades": [], "metrics": {}}

        momentum_th = strategy_params.get("momentum_threshold", 0.02)
        volume_th = strategy_params.get("volume_threshold", 1.2)
        rsi_os = strategy_params.get("rsi_oversold", 40)
        rsi_ob = strategy_params.get("rsi_overbought", 60)
        sl_pct = strategy_params.get("stop_loss_pct", 0.04)
        tp_pct = strategy_params.get("take_profit_pct", 0.08)
        use_ema = strategy_params.get("use_ema_cross", True)

        closes = [float(k["c"]) for k in klines]
        volumes = [float(k["v"]) for k in klines]
        highs = [float(k["h"]) for k in klines]
        lows = [float(k["l"]) for k in klines]

        def ema(prices, n):
            if len(prices) < n:
                return [prices[0]] * len(prices)
            k = 2 / (n + 1)
            e = prices[0]
            result = []
            for p in prices:
                e = p * k + e * (1 - k)
                result.append(e)
            return result

        def rsi(prices, n=14):
            if len(prices) < n + 1:
                return [50.0] * len(prices)
            deltas = [prices[i] - prices[i - 1] for i in range(1, len(prices))]
            gains = [max(d, 0) for d in deltas]
            losses = [max(-d, 0) for d in deltas]
            result = [50.0] * n
            avg_g = sum(gains[:n]) / n
            avg_l = sum(losses[:n]) / n
            for i in range(n, len(gains)):
                avg_g = (avg_g * (n - 1) + gains[i]) / n
                avg_l = (avg_l * (n - 1) + losses[i]) / n
                if avg_l == 0:
                    result.append(100.0)
                else:
                    rs = avg_g / avg_l
                    result.append(100 - 100 / (1 + rs))
            return result

        ema20 = ema(closes, 20)
        ema50 = ema(closes, 50)
        rsi14 = rsi(closes, 14)

        avg_vol_20 = []
        for i in range(len(volumes)):
            if i < 20:
                avg_vol_20.append(sum(volumes[: i + 1]) / (i + 1))
            else:
                avg_vol_20.append(sum(volumes[i - 19 : i + 1]) / 20)

        trades = []
        position = None
        entry_price = 0
        entry_idx = 0

        for i in range(50, len(closes)):
            price = closes[i]
            vol_ratio = volumes[i] / avg_vol_20[i] if avg_vol_20[i] > 0 else 1.0
            ch24 = (closes[i] - closes[i - 24]) / closes[i - 24] if i >= 24 else 0

            if position is None:
                long_signal = False
                short_signal = False

                if abs(ch24) > momentum_th and vol_ratio > volume_th:
                    if ch24 > 0:
                        long_signal = True
                    else:
                        short_signal = True

                if use_ema and i > 0:
                    if ema20[i] > ema50[i] and ema20[i - 1] <= ema50[i - 1]:
                        long_signal = True
                    elif ema20[i] < ema50[i] and ema20[i - 1] >= ema50[i - 1]:
                        short_signal = True

                if rsi14[i] < rsi_os:
                    long_signal = True
                elif rsi14[i] > rsi_ob:
                    short_signal = True

                if long_signal:
                    position = "LONG"
                    entry_price = price
                    entry_idx = i
                elif short_signal:
                    position = "SHORT"
                    entry_price = price
                    entry_idx = i
            else:
                sl_price = entry_price * (1 - sl_pct) if position == "LONG" else entry_price * (1 + sl_pct)
                tp_price = entry_price * (1 + tp_pct) if position == "LONG" else entry_price * (1 - tp_pct)

                exit_price = None
                exit_reason = ""

                if position == "LONG":
                    if lows[i] <= sl_price:
                        exit_price = sl_price
                        exit_reason = "stop_loss"
                    elif highs[i] >= tp_price:
                        exit_price = tp_price
                        exit_reason = "take_profit"
                else:
                    if highs[i] >= sl_price:
                        exit_price = sl_price
                        exit_reason = "stop_loss"
                    elif lows[i] <= tp_price:
                        exit_price = tp_price
                        exit_reason = "take_profit"

                if exit_price:
                    pnl = (
                        (exit_price - entry_price) / entry_price
                        if position == "LONG"
                        else (entry_price - exit_price) / entry_price
                    )
                    trades.append(
                        {
                            "entry_idx": entry_idx,
                            "exit_idx": i,
                            "entry_price": entry_price,
                            "exit_price": exit_price,
                            "side": position,
                            "pnl_pct": pnl,
                            "exit_reason": exit_reason,
                            "bars_held": i - entry_idx,
                        }
                    )
                    position = None
                    entry_price = 0

        if trades:
            wins = [t for t in trades if t["pnl_pct"] > 0]
            losses = [t for t in trades if t["pnl_pct"] <= 0]
            win_rate = len(wins) / len(trades) if trades else 0

            avg_win = sum(t["pnl_pct"] for t in wins) / len(wins) if wins else 0
            avg_loss = abs(sum(t["pnl_pct"] for t in losses) / len(losses)) if losses else 0
            profit_factor = avg_win / avg_loss if avg_loss > 0 else 0

            total_pnl = sum(t["pnl_pct"] for t in trades)
            peak = 0
            current = 0
            max_dd = 0
            for t in trades:
                current += t["pnl_pct"]
                peak = max(peak, current)
                dd = peak - current
                max_dd = max(max_dd, dd)

            returns = [t["pnl_pct"] for t in trades]
            avg_return = sum(returns) / len(returns) if returns else 0
            std_return = (
                (sum((r - avg_return) ** 2 for r in returns) / len(returns)) ** 0.5
                if returns
                else 0
            )
            sharpe = (avg_return / std_return) * (len(trades) ** 0.5) if std_return > 0 else 0

            metrics = {
                "total_trades": len(trades),
                "win_rate": round(win_rate, 4),
                "profit_factor": round(profit_factor, 4),
                "avg_win_pct": round(avg_win * 100, 2),
                "avg_loss_pct": round(avg_loss * 100, 2),
                "total_pnl_pct": round(total_pnl * 100, 2),
                "max_drawdown_pct": round(max_dd * 100, 2),
                "sharpe_ratio": round(sharpe, 4),
                "avg_bars_held": round(sum(t["bars_held"] for t in trades) / len(trades), 1),
            }
        else:
            metrics = {
                "total_trades": 0,
                "win_rate": 0,
                "profit_factor": 0,
                "avg_win_pct": 0,
                "avg_loss_pct": 0,
                "total_pnl_pct": 0,
                "max_drawdown_pct": 0,
                "sharpe_ratio": 0,
                "avg_bars_held": 0,
            }

        return {
            "coin": coin,
            "strategy_params": strategy_params,
            "trades": trades[:100],
            "total_trades": len(trades),
            "metrics": metrics,
            "backtest_period": f"{len(closes)} bars",
        }

    def compare_strategies(
        self, coin: str, baseline_params: Dict, improved_params: Dict
    ) -> Dict:
        """
        对比两个策略参数的回测结果
        """
        klines = self.fetch_historical_klines(coin)

        baseline = self.run_backtest(coin, baseline_params, klines)
        improved = self.run_backtest(coin, improved_params, klines)

        bm = baseline.get("metrics", {})
        im = improved.get("metrics", {})

        comparison = {
            "coin": coin,
            "baseline": bm,
            "improved": im,
            "improvement": {
                "win_rate_change": round(im.get("win_rate", 0) - bm.get("win_rate", 0), 4),
                "profit_factor_change": round(
                    im.get("profit_factor", 0) - bm.get("profit_factor", 0), 4
                ),
                "total_pnl_change_pct": round(
                    im.get("total_pnl_pct", 0) - bm.get("total_pnl_pct", 0), 2
                ),
                "max_drawdown_change_pct": round(
                    im.get("max_drawdown_pct", 0) - bm.get("max_drawdown_pct", 0), 2
                ),
                "sharpe_change": round(
                    im.get("sharpe_ratio", 0) - bm.get("sharpe_ratio", 0), 4
                ),
                "trade_count_change": im.get("total_trades", 0) - bm.get("total_trades", 0),
            },
            "is_improvement": (
                im.get("total_pnl_pct", 0) > bm.get("total_pnl_pct", 0)
                and im.get("sharpe_ratio", 0) > bm.get("sharpe_ratio", 0)
            ),
        }

        return comparison
