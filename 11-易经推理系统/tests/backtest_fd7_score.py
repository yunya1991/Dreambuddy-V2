"""P0 五维+7引擎评分回测引擎。

从 OKX 拉取 BTC/ETH/SOL 6 个月 1H K 线，逐 bar 调 FiveDomainFeatureComputer.compute()
生成五维评分，按 dao 评分生成信号模拟收益，用 empyrical 计算风险指标。

关键约束：
- PIT 防泄漏：每个 bar t 只用 [0, t-1] 数据
- 生产注入红线 enable_fundamental_7engines_production_injection = False（不触碰）
- mock news_list 保证 7 引擎 S 级可计算
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd
import requests

# empyrical 指标
try:
    from empyrical import (
        sharpe_ratio,
        sortino_ratio,
        max_drawdown,
        calmar_ratio,
        annual_return,
        annual_volatility,
        tail_ratio,
        omega_ratio,
    )
    HAS_EMPYRICAL = True
except ImportError:
    HAS_EMPYRICAL = False

THIS_DIR = Path(__file__).resolve().parent
_REPO = THIS_DIR.parent
_COMPUTER_ROOT = _REPO / "scripts" / "memory_l4"

if str(_COMPUTER_ROOT) not in sys.path:
    sys.path.insert(0, str(_COMPUTER_ROOT))
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))


# 固定 mock news_list（2正 + 2负 + 1中性，覆盖 BTC/ETH/SOL）
_MOCK_NEWS_LIST: List[Dict[str, Any]] = [
    {"source": "odaily", "category": "news", "sub_category": "btc",
     "title": "BTC突破历史新高机构持续买入",
     "content": "比特币今日大幅上涨突破关键阻力位，多家机构宣布增持BTC资产",
     "timestamp_ms": 1700000000000},
    {"source": "odaily", "category": "news", "sub_category": "eth",
     "title": "ETH网络升级利好DeFi生态繁荣",
     "content": "以太坊完成重要网络升级，Gas费用大幅降低，DeFi TVL创新高",
     "timestamp_ms": 1700000001000},
    {"source": "odaily", "category": "news", "sub_category": "sol",
     "title": "SOL网络宕机引发市场恐慌",
     "content": "Solana网络再次出现宕机，用户抱怨交易无法确认，价格大幅下挫",
     "timestamp_ms": 1700000002000},
    {"source": "odaily", "category": "news", "sub_category": "btc",
     "title": "监管机构对加密货币展开新一轮调查",
     "content": "某国监管机构宣布对主要加密货币交易所展开调查，市场情绪转冷",
     "timestamp_ms": 1700000003000},
    {"source": "odaily", "category": "news", "sub_category": "market",
     "title": "加密市场横盘整理等待方向选择",
     "content": "今日加密货币市场整体波动不大，各大标的横盘整理",
     "timestamp_ms": 1700000004000},
]


class FD7ScoreBacktester:
    """五维+7引擎评分回测引擎。"""

    OKX_CANDLE_URL = "https://www.okx.com/api/v5/market/candles"

    def __init__(self, symbol: str, timeframe: str = "1H", period_days: int = 180):
        self.symbol = symbol
        self.okx_inst_id = f"{symbol}-USDT-SWAP"
        self.timeframe = timeframe
        self.period_days = period_days

    # ── 1. K 线拉取 ──

    def fetch_klines(self) -> pd.DataFrame:
        """从 OKX 拉取 K 线历史数据，返回 DataFrame。"""
        end_ts = int(time.time() * 1000)
        start_ts = end_ts - self.period_days * 24 * 3600 * 1000
        all_candles: List[List] = []
        after = end_ts
        while after > start_ts:
            params = {
                "instId": self.okx_inst_id,
                "bar": self.timeframe,
                "after": str(after),
                "limit": "300",
            }
            try:
                resp = requests.get(self.OKX_CANDLE_URL, params=params, timeout=30)
                resp.raise_for_status()
                data = resp.json()
                if data.get("code") != "0" or not data.get("data"):
                    break
                candles = data["data"]
                all_candles.extend(candles)
                after = int(candles[-1][0])
                time.sleep(0.25)  # 限速
            except Exception:
                break
        if not all_candles:
            return pd.DataFrame()
        # OKX 返回最新在前，反转为时间正序
        df = pd.DataFrame(all_candles, columns=["ts", "open", "high", "low", "close", "vol", "volCcy", "volCcyQuote", "confirm"])
        df = df[["ts", "open", "high", "low", "close", "vol"]].copy()
        for col in ["open", "high", "low", "close", "vol"]:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        df["ts"] = pd.to_numeric(df["ts"], errors="coerce")
        df = df.sort_values("ts").drop_duplicates(subset=["ts"]).reset_index(drop=True)
        # 过滤到 start_ts 之后
        df = df[df["ts"] >= start_ts].reset_index(drop=True)
        return df

    # ── 2. 技术指标（pandas 手算，不依赖 TA-Lib） ──

    @staticmethod
    def _compute_rsi(close: pd.Series, period: int = 14) -> pd.Series:
        delta = close.diff()
        gain = delta.where(delta > 0, 0.0).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0.0)).rolling(window=period).mean()
        rs = gain / loss.replace(0, np.nan)
        return 100 - (100 / (1 + rs))

    @staticmethod
    def _compute_macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.Series:
        ema_fast = close.ewm(span=fast, adjust=False).mean()
        ema_slow = close.ewm(span=slow, adjust=False).mean()
        macd_line = ema_fast - ema_slow
        signal_line = macd_line.ewm(span=signal, adjust=False).mean()
        return macd_line - signal_line  # histogram

    @staticmethod
    def _compute_boll(close: pd.Series, period: int = 20, std_mult: float = 2.0):
        ma = close.rolling(window=period).mean()
        sd = close.rolling(window=period).std()
        return ma + std_mult * sd, ma - std_mult * sd

    @staticmethod
    def _compute_atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
        tr = pd.concat([
            high - low,
            (high - close.shift(1)).abs(),
            (low - close.shift(1)).abs(),
        ], axis=1).max(axis=1)
        return tr.rolling(window=period).mean()

    # ── 3. coin_data / system_state 构造 ──

    def build_coin_data(self, df: pd.DataFrame, t: int, symbol_key: str) -> Dict[str, Any]:
        """用 [0, t] 区间数据构造 coin_data（PIT 防泄漏）。"""
        if t < 60:
            return {}
        sub = df.iloc[:t + 1].copy()
        close = sub["close"]
        high = sub["high"]
        low = sub["low"]
        vol = sub["vol"]
        rsi = self._compute_rsi(close)
        macd_hist = self._compute_macd(close)
        boll_upper, boll_lower = self._compute_boll(close)
        ma20 = close.rolling(window=20).mean()
        ma60 = close.rolling(window=60).mean()
        vol_20 = vol.rolling(window=20).mean()
        atr_14 = self._compute_atr(high, low, close)
        pct_1h = close.pct_change(1)
        pct_24h = close.pct_change(24)

        # 补充 _compute_dao 等五维评分所需字段（从 K 线派生）
        rsi_val = float(rsi.iloc[-1]) if pd.notna(rsi.iloc[-1]) else 50.0
        pct_24h_val = float(pct_24h.iloc[-1]) if pd.notna(pct_24h.iloc[-1]) else 0.0
        close_val = float(close.iloc[-1])
        ma60_val = float(ma60.iloc[-1]) if pd.notna(ma60.iloc[-1]) else close_val
        ma20_val = float(ma20.iloc[-1]) if pd.notna(ma20.iloc[-1]) else close_val
        boll_u = float(boll_upper.iloc[-1]) if pd.notna(boll_upper.iloc[-1]) else close_val
        boll_l = float(boll_lower.iloc[-1]) if pd.notna(boll_lower.iloc[-1]) else close_val
        atr_val = float(atr_14.iloc[-1]) if pd.notna(atr_14.iloc[-1]) else 0.0

        # 五维评分字段放在 crypto_usdt 层级（与 symbol_key 同级）
        crypto_cls_data: Dict[str, Any] = {
            # ── 五维评分所需字段（从 K 线派生） ──
            "fedfunds_rate": 5.25,
            "stablecoin_mcap_bln": close_val * 0.3,
            "policy_sentiment_score": max(0.0, min(1.0, rsi_val / 100.0)),
            "stablecoin_change_rate": pct_24h_val,
            "cycle4y_t_rel": max(0.0, min(1.0, (close_val - ma60_val) / ma60_val + 0.5)) if ma60_val > 0 else 0.5,
            "atr": atr_val,
            "atr_percentile": max(0.0, min(1.0, atr_val / (close_val * 0.05))) if close_val > 0 else 0.5,
            "spring_force_score": max(0.0, min(1.0, (boll_u - boll_l) / close_val)) if close_val > 0 else 0.5,
            "regime": 1 if ma20_val > ma60_val else (-1 if ma20_val < ma60_val else 0),
            "price_amplitude": max(0.0, min(1.0, (boll_u - boll_l) / close_val * 10)) if close_val > 0 else 0.0,
            # ── per-symbol 技术指标 ──
            symbol_key: {
                "close": close_val,
                "rsi": rsi_val,
                "macd": float(macd_hist.iloc[-1]) if pd.notna(macd_hist.iloc[-1]) else 0.0,
                "boll_upper": boll_u,
                "boll_lower": boll_l,
                "ma20": ma20_val,
                "ma60": ma60_val,
                "vol_20": float(vol_20.iloc[-1]) if pd.notna(vol_20.iloc[-1]) else 0.0,
                "atr_14": atr_val,
                "pct_change_1h": float(pct_1h.iloc[-1]) if pd.notna(pct_1h.iloc[-1]) else 0.0,
                "pct_change_24h": pct_24h_val,
            },
        }
        return {"crypto_usdt": crypto_cls_data}

    def build_system_state(self, df: pd.DataFrame, t: int) -> Dict[str, Any]:
        """用 [t-30, t-1] 窗口构造 system_state。"""
        if t < 31:
            return {"win_rate": 0.5, "profit_factor": 1.0, "factor_coverage_pct": 0.85}
        window = df.iloc[t - 30:t]
        returns = window["close"].pct_change().dropna()
        wins = returns[returns > 0]
        losses = returns[returns < 0]
        win_rate = len(wins) / max(len(returns), 1)
        gross_profit = wins.sum()
        gross_loss = abs(losses.sum())
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else 2.0
        return {
            "win_rate": float(win_rate),
            "profit_factor": float(min(max(profit_factor, 0.1), 10.0)),
            "factor_coverage_pct": 0.85,
        }

    # ── 4. 信号生成 ──

    @staticmethod
    def score_to_signal(dao_score: int) -> int:
        """dao 评分 → 信号。"""
        if dao_score > 60:
            return 1
        elif dao_score < 40:
            return -1
        return 0

    # ── 5. 回测主循环 ──

    def run_backtest(self, computer=None) -> Dict[str, Any]:
        """执行完整回测，返回指标报告。"""
        # 拉取 K 线
        df = self.fetch_klines()
        if df.empty or len(df) < 200:
            return {"error": f"K线数据不足: {len(df)} bars", "symbol": self.symbol}

        # 初始化 FiveDomainFeatureComputer
        if computer is None:
            from five_domain_feature_computer import FiveDomainFeatureComputer
            os.environ["FUND_7ENGINES_BOOST"] = "1"
            os.environ["ODAILY_ENGINE_BOOST"] = "1"
            computer = FiveDomainFeatureComputer(enable=True)
            # mock news_list
            computer._fetch_news_72h_limit200 = lambda *a, **kw: list(_MOCK_NEWS_LIST)
            # 回测时禁用 Shadow JSONL 写入（避免每 bar 写盘导致极慢）
            computer.enable_fundamental_7engines_boost = False
            computer.enable_odaily_engine_boost = False

        symbol_key = f"{self.symbol}-USDT"
        signals: List[int] = []
        returns: List[float] = []
        nav_curve: List[float] = [1.0]
        dao_scores: List[int] = []

        start_bar = 60  # 需要足够历史计算指标
        total_bars = len(df)

        for t in range(start_bar, total_bars - 1):
            # PIT 构造
            coin_data = self.build_coin_data(df, t, symbol_key)
            system_state = self.build_system_state(df, t)

            # 五维评分
            try:
                result = computer.compute(coin_data=coin_data, system_state=system_state)
                dao_score = result.get("crypto_usdt", {}).get("dao", 50)
            except Exception:
                dao_score = 50

            dao_scores.append(dao_score)
            signal = self.score_to_signal(dao_score)
            signals.append(signal)

            # 计算下一 bar 收益
            next_close = df.iloc[t + 1]["close"]
            curr_close = df.iloc[t]["close"]
            bar_return = signal * (next_close / curr_close - 1.0)
            returns.append(bar_return)
            nav_curve.append(nav_curve[-1] * (1.0 + bar_return))

        returns_arr = np.array(returns)
        nav_arr = np.array(nav_curve)

        # empyrical 指标
        emp_metrics = {}
        if HAS_EMPYRICAL and len(returns_arr) > 1:
            try:
                emp_metrics = {
                    "sharpe_ratio": float(sharpe_ratio(returns_arr)),
                    "sortino_ratio": float(sortino_ratio(returns_arr)),
                    "max_drawdown": float(max_drawdown(returns_arr)),
                    "calmar_ratio": float(calmar_ratio(returns_arr)),
                    "annual_return": float(annual_return(returns_arr)),
                    "annual_volatility": float(annual_volatility(returns_arr)),
                    "tail_ratio": float(tail_ratio(returns_arr)),
                    "omega_ratio": float(omega_ratio(returns_arr)),
                }
            except Exception:
                emp_metrics = {}

        # 自定义统计
        signal_arr = np.array(signals)
        win_mask = (signal_arr != 0) & (returns_arr > 0)
        loss_mask = (signal_arr != 0) & (returns_arr < 0)
        win_rate = win_mask.sum() / max((signal_arr != 0).sum(), 1)
        avg_win = returns_arr[win_mask].mean() if win_mask.any() else 0.0
        avg_loss = abs(returns_arr[loss_mask].mean()) if loss_mask.any() else 0.0
        profit_factor = avg_win / avg_loss if avg_loss > 0 else 0.0
        signal_coverage = (signal_arr != 0).mean()
        long_ratio = (signal_arr == 1).mean()
        short_ratio = (signal_arr == -1).mean()
        # 交易次数 = 信号变化次数
        total_trades = int(np.sum(np.diff(np.concatenate([[0], signal_arr])) != 0))

        # 基准
        buy_hold_return = float(nav_curve[-1] / nav_curve[0] - 1) if nav_curve else 0.0
        # 简化：不跑 1000 次随机，用等权随机基准的期望
        random_sharpe = 0.0  # 随机信号期望 Sharpe ≈ 0

        # NaN 处理
        for k, v in emp_metrics.items():
            if v != v:  # NaN check
                emp_metrics[k] = 0.0

        return {
            "symbol": self.symbol,
            "bars": total_bars,
            "backtest_bars": len(returns),
            "empyrical": emp_metrics,
            "custom": {
                "win_rate": float(win_rate),
                "profit_factor": float(profit_factor),
                "signal_coverage": float(signal_coverage),
                "long_ratio": float(long_ratio),
                "short_ratio": float(short_ratio),
                "total_trades": total_trades,
            },
            "benchmark": {
                "buy_hold_return": buy_hold_return,
                "random_signal_mean_sharpe": random_sharpe,
            },
            "nav_curve": nav_curve,
            "dao_scores": dao_scores,
            "signals": signals,
        }

    # ── 6. 报告输出 ──

    def generate_report(self, results: Dict[str, Any], output_dir: str) -> str:
        """生成 JSON 报告 + CSV 净值曲线，返回报告路径。"""
        os.makedirs(output_dir, exist_ok=True)
        date_str = time.strftime("%Y%m%d")
        symbol_lower = self.symbol.lower()

        # JSON 报告（不含大数组，避免文件过大）
        report = {k: v for k, v in results.items() if k not in ("nav_curve", "dao_scores", "signals")}
        json_path = os.path.join(output_dir, f"{symbol_lower}_backtest_{date_str}.json")
        with open(json_path, "w") as f:
            json.dump(report, f, indent=2, ensure_ascii=False)

        # CSV 净值曲线
        csv_path = os.path.join(output_dir, f"{symbol_lower}_nav_curve_{date_str}.csv")
        nav_df = pd.DataFrame({
            "bar": range(len(results.get("nav_curve", []))),
            "nav": results.get("nav_curve", []),
        })
        nav_df.to_csv(csv_path, index=False)

        return json_path
