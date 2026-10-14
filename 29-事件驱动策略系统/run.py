#!/usr/bin/env python3
"""
29-事件驱动策略系统 — 统一入口脚本

定位：与 BCRM2.0、BDSM 平级的独立子交易系统。
核心逻辑：买预期，卖事实（离散宏观事件冲击响应，脉冲衰减离场）。

用法:
  python3 run.py signal                 用 mock 数据评估一次事件驱动信号
  python3 run.py signal --event fomc    指定事件类型 (fomc/nfp/cpi/ppi/fed_speech/...)
  python3 run.py trader                 启动事件驱动独立交易器（mock K 线循环）
  python3 run.py test                   运行事件驱动策略全部测试
  python3 run.py config                 查看当前策略配置（权重/阈值/半衰期）
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))

from event_driven.event_driven_strategy import (  # noqa: E402
    EVENT_HALF_LIFE,
    EventDrivenStrategy,
    EventDrivenTrader,
    EventSignal,
    neutral_event_signal,
)


def _mock_kline(event_type: str = "fomc") -> dict[str, Any]:
    """构造 mock K 线数据（含 event_context），用于本地信号验证。"""
    return {
        "symbol": "BTCUSDT",
        "timestamp": int(time.time() * 1000),
        "open": 67000.0,
        "high": 67500.0,
        "low": 66800.0,
        "close": 67200.0,
        "volume": 1234.5,
        "event_context": {
            "event_type": event_type,
            "event_window": "post_event",
            "in_fomc_cycle": True,
            "cycle_phase": "expansion",
            "days_since_event": 0.5,
            "actual_rate": 0.045,
            "expected_rate": 0.0425,
            "surprise": 0.0025,
        },
        "cesi": 1.8,
        "lower_shadow_pct": 0.006,
        "cross_asset_divergence": 0.3,
    }


def cmd_signal(args) -> None:
    """评估一次事件驱动信号。"""
    strategy = EventDrivenStrategy()
    kline = _mock_kline(args.event)
    signal = strategy.evaluate(kline)

    print("=" * 70)
    print(f"事件驱动策略信号评估 (event_type={args.event})")
    print("=" * 70)
    d = signal.to_dict()
    d["strength"] = round(d["strength"], 4)
    d["confidence"] = round(d["confidence"], 4)
    d["elasticity"] = round(d["elasticity"], 4)
    print(json.dumps(d, ensure_ascii=False, indent=2))


def cmd_trader(args) -> None:
    """启动事件驱动独立交易器（mock K 线循环，每 5 秒一次）。"""
    strategy = EventDrivenStrategy()
    trader = EventDrivenTrader(strategy, config={"base_position": 250.0})

    print("=" * 70)
    print("事件驱动独立交易器启动 (mock 循环, Ctrl+C 退出)")
    print("=" * 70)
    try:
        while True:
            kline = _mock_kline()
            signal = trader.on_kline_close(kline)
            print(f"[{time.strftime('%H:%M:%S')}] signal={signal.signal} "
                  f"strength={signal.strength:.3f} confidence={signal.confidence:.3f}")
            time.sleep(5)
    except KeyboardInterrupt:
        print("\n交易器已停止")


def cmd_config(args) -> None:
    """查看策略配置。"""
    s = EventDrivenStrategy()
    print("=" * 70)
    print("事件驱动策略配置")
    print("=" * 70)
    print(f"  5 维权重:")
    print(f"    priced_in     = {s.W_PRICED_IN}")
    print(f"    real_rate     = {s.W_REAL_RATE}")
    print(f"    resilience    = {s.W_RESILIENCE}")
    print(f"    lower_shadow  = {s.W_LOWER_SHADOW}")
    print(f"    cross_asset   = {s.W_CROSS_ASSET}")
    print(f"  信号阈值: LONG≥{s.LONG_THRESHOLD}, SHORT≤{s.SHORT_THRESHOLD}")
    print(f"  事件半衰期: {EVENT_HALF_LIFE} 天")
    print(f"  CESI 触发阈值: ±{s.CESI_TRIGGER_THRESHOLD}σ")
    print(f"  宏观事件类型: {s.MACRO_EVENT_TYPES}")
    print(f"  非宏观事件类型: {s.NON_MACRO_EVENT_TYPES}")


def cmd_test(args) -> None:
    """运行事件驱动策略测试套件。"""
    import subprocess
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/", "-v", "--tb=short"],
        cwd=str(BASE_DIR),
    )
    sys.exit(result.returncode)


def main() -> None:
    parser = argparse.ArgumentParser(description="29-事件驱动策略系统")
    sub = parser.add_subparsers(dest="command", required=True)

    p_signal = sub.add_parser("signal", help="评估一次事件驱动信号")
    p_signal.add_argument("--event", default="fomc",
                          help="事件类型: fomc/nfp/cpi/ppi/fed_speech/tech_upgrade/...")
    p_signal.set_defaults(func=cmd_signal)

    p_trader = sub.add_parser("trader", help="启动事件驱动独立交易器")
    p_trader.set_defaults(func=cmd_trader)

    p_config = sub.add_parser("config", help="查看策略配置")
    p_config.set_defaults(func=cmd_config)

    p_test = sub.add_parser("test", help="运行测试套件")
    p_test.set_defaults(func=cmd_test)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
