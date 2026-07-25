#!/usr/bin/env python3
"""调试为什么 L0 时间硬退出在回测中不触发"""
import sys
import os
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR in sys.path: sys.path.remove(SCRIPT_DIR)
PROJECT_ROOT = os.path.dirname(os.path.dirname(SCRIPT_DIR))
sys.path.insert(0, PROJECT_ROOT)

import pandas as pd
from scripts.memory_l4.classic_exit_system import ClassicExitSystem, PositionState, ExitAction, ExitConfig

config = ExitConfig()
system = ClassicExitSystem(config=config)

# 加载 BTC 第一笔交易数据
klines = pd.read_csv(os.path.join(PROJECT_ROOT, "scripts", "data", "klines", "BTC_1H.csv"))
klines["timestamp"] = pd.to_datetime(klines["timestamp"])
klines.set_index("timestamp", inplace=True)

entry_time = pd.Timestamp("2026-04-29 03:00:00")
entry_price = 76990.3
side = "short"
kline_slice = klines[klines.index >= entry_time]

print(f"entry_time: {entry_time}")
print(f"kline_slice length: {len(kline_slice)}")
print(f"config.l0_max_hold_sec: {config.l0_max_hold_sec}")

# 检查第 30 根 K 线（age ~25h > 86400? 不，1H K线每根3600s，24根=86400s，所以第25根应该触发）
# 注意 i 从 1 开始，跳过第 0 根
for target_i in [24, 25, 30, 50, 100]:
    if target_i >= len(kline_slice):
        break
    bar = kline_slice.iloc[target_i]
    bar_time = kline_slice.index[target_i]
    current_price = float(bar["close"])
    age_sec = (bar_time - entry_time).total_seconds()
    raw_pnl = (entry_price - current_price) / entry_price

    pos = PositionState(
        coin=f"BTC_TEST", side=side, entry_price=entry_price, current_price=current_price,
        position_age_sec=age_sec, unrealized_pnl_pct=raw_pnl, leverage=3.0, atr_pct=0.02,
        mfe_pnl_pct=0.0, max_dd_pct=0.0, entry_ts=int(entry_time.timestamp()),
        trailing_armed=False, trailing_stop_price=0.0,
    )

    candles_window = []
    start_idx = max(0, target_i - 60)
    for j in range(start_idx, target_i + 1):
        b = kline_slice.iloc[j]
        candles_window.append({
            "t": int(kline_slice.index[j].timestamp()),
            "o": float(b["open"]), "h": float(b["high"]),
            "l": float(b["low"]), "c": float(b["close"]),
            "v": float(b["volume"]),
        })

    decision = system.evaluate_full(pos, candles_window, regime="trend")
    print(f"\ni={target_i}, bar_time={bar_time}, age={age_sec/3600:.1f}h, price={current_price:.1f}, pnl={raw_pnl*100:.2f}%")
    print(f"  decision.action={decision.action}, reason={decision.reason}, l0_triggered={decision.l0_triggered}")

# 检查 decision.action == HOLD 时 features 的内容
print("\n--- 检查 i=25 的 features ---")
bar = kline_slice.iloc[25]
bar_time = kline_slice.index[25]
current_price = float(bar["close"])
age_sec = (bar_time - entry_time).total_seconds()
raw_pnl = (entry_price - current_price) / entry_price
pos = PositionState(
    coin=f"BTC_TEST", side=side, entry_price=entry_price, current_price=current_price,
    position_age_sec=age_sec, unrealized_pnl_pct=raw_pnl, leverage=3.0, atr_pct=0.02,
    mfe_pnl_pct=0.0, max_dd_pct=0.0, entry_ts=int(entry_time.timestamp()),
    trailing_armed=False, trailing_stop_price=0.0,
)
candles_window = []
for j in range(0, 26):
    b = kline_slice.iloc[j]
    candles_window.append({"t": int(kline_slice.index[j].timestamp()), "o": float(b["open"]), "h": float(b["high"]), "l": float(b["low"]), "c": float(b["close"]), "v": float(b["volume"])})
decision = system.evaluate_full(pos, candles_window, regime="trend")
print(f"hold_risk={decision.features.hold_risk:.3f}, hold_value={decision.features.hold_value:.3f}, dd={decision.features.dd:.3f}")
