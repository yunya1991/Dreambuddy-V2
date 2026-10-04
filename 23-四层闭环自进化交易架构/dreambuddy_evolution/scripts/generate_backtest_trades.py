#!/usr/bin/env python3
"""
回测数据生成脚本 — 为 ReflectionScanner 提供回测胜率统计

策略：双 EMA 金叉/死叉 + ATR 止损止盈（趋势跟踪）
目的：快速稳定地为扫描池全部币种生成回测交易记录，
     以 source_system="backtest" 注入 TradeIndexBuilder，解决冷启动。

设计决策：
- 原方案用 walk_forward_backtester（BCRM ML 策略），但批量运行触发 segfault（TDA 拓扑检测器）
- 改用简单技术策略，速度快（几秒/币）、稳定、能覆盖全部币种
- 胜率作为"该币种趋势性强弱"的弱信号，对 reflection 层有参考价值
- 回测数据由 ReflectionScanner 打 0.85 折扣（sim-to-real gap）
"""
import sys
import time
import logging
from pathlib import Path
from datetime import datetime, timezone

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT / "23-四层闭环自进化交易架构"))
sys.path.insert(0, str(PROJECT_ROOT / "11-易经推理系统"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

# 扫描池币种（基础 24 + 常见扫描币 + 小币种）
SCAN_COINS = [
    "UNI", "PUMP", "HYPE", "AAVE", "SOL", "CRCL", "ETH", "BTC", "ZEC", "ARB",
    "MU", "SKHYNIX", "XAU", "XAG", "GOOGL", "NVDA", "AMZN", "OKB", "SNDK", "SPCX",
    "COIN", "BMNR", "MSTR", "BNB", "LINK", "DOGE", "XRP", "ADA", "DOT", "AVAX",
    "MATIC", "LTC", "TRX", "ATOM", "NEAR", "APT", "OP", "INJ", "PEPE", "WIF",
    "SHIB", "TON", "SUI", "FIL", "ETC", "IMX", "SEI", "TIA", "JUP", "RUNE",
    # 额外小币种（无真实交易记录，补充 backtest_only 覆盖）
    "VET", "FTM", "ALGO", "HBAR", "ICP", "VET", "EGLD", "XTZ", "XLM", "EOS",
    "AAVE", "CRO", "QNT", "GRT", "SNX", "COMP", "MKR", "DYDX", "GMX", "RDNT",
]

from scripts.memory_l4.bcrm2.data_fetcher import get_klines
from dreambuddy_evolution.engines.backtest_trade_adapter import (
    trade_to_index_record, write_backtest_trades,
)

TIMEFRAME = "1H"
MAX_BARS = 5000
HOLD_BARS = 24  # 持有 24h
ENTRY_INTERVAL = 48  # 每 48h 开仓一次
FEE_RATE = 0.0005
SLIPPAGE_RATE = 0.001

OUTPUT_PATH = PROJECT_ROOT / ".workbuddy/trade_index/backtest_trades.jsonl"


def compute_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """计算 ATR"""
    high = df["high"]
    low = df["low"]
    close = df["close"]
    tr1 = high - low
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low - close.shift(1)).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    return tr.rolling(period).mean()


def backtest_coin(coin: str) -> list[dict]:
    """
    双 EMA 金叉死叉 + ATR 止损止盈回测。
    返回标准化交易记录列表。
    """
    try:
        df = get_klines(coin, TIMEFRAME, max_bars=MAX_BARS)
        if df is None or len(df) < 200:
            logger.warning("%s: 数据不足 (%s)", coin, len(df) if df is not None else 0)
            return []

        # 策略：定期开仓 + 固定持有时间
        # 直接度量"该币种在任意时点买入持有 HOLD_BARS 后盈利的概率"
        # 这是最朴素的"币种盈利难易度"信号，不受策略选择偏差影响
        df = df.copy()
        closes = df["close"].values

        trades = []
        i = HOLD_BARS  # 从第 HOLD_BARS 根开始
        while i < len(closes):
            entry_price = closes[i - HOLD_BARS]
            exit_price = closes[i]
            pnl_pct = (exit_price - entry_price) / entry_price
            pnl_pct -= FEE_RATE * 2 + SLIPPAGE_RATE * 2

            trades.append({
                "entry_bar": i - HOLD_BARS,
                "exit_bar": i,
                "direction": 1,
                "entry_price": float(entry_price),
                "exit_price": float(exit_price),
                "pnl_pct": float(pnl_pct),
                "hold_bars": HOLD_BARS,
                "exit_reason": "time",
                "confidence": 0.6,
            })
            i += ENTRY_INTERVAL

        if not trades:
            logger.info("%s: 无交易记录", coin)
            return []

        # 转换为 TradeIndexBuilder 格式
        timestamps = None
        if hasattr(df, "index"):
            try:
                timestamps = [int(pd.Timestamp(t).timestamp()) for t in df.index]
            except Exception:
                timestamps = None

        records = []
        for t in trades:
            rec = trade_to_index_record(t, coin=coin, timestamps=timestamps)
            if rec:
                records.append(rec)

        logger.info("%s: %d 笔回测交易", coin, len(records))
        return records

    except Exception as e:
        logger.warning("%s: 回测失败: %s", coin, e)
        return []


def main():
    logger.info("开始回测数据生成，目标 %d 币种", len(SCAN_COINS))
    start = time.time()

    all_records = []
    success_coins = 0
    for i, coin in enumerate(SCAN_COINS):
        t0 = time.time()
        records = backtest_coin(coin)
        elapsed = time.time() - t0
        if records:
            success_coins += 1
            all_records.extend(records)
        logger.info("[%d/%d] %s: %d 笔 (%.1fs)", i + 1, len(SCAN_COINS), coin, len(records), elapsed)

    written = write_backtest_trades(all_records, OUTPUT_PATH)
    total_elapsed = time.time() - start
    logger.info(
        "完成: 成功 %d/%d 币种, %d 笔交易, 耗时 %.1fmin, 输出 %s",
        success_coins, len(SCAN_COINS), written, total_elapsed / 60, OUTPUT_PATH,
    )


if __name__ == "__main__":
    main()
