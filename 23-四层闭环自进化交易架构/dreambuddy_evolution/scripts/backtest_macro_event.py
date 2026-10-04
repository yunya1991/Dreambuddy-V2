"""
宏观事件驱动策略回测 — 合成 FOMC 周期数据验证端到端信号流

场景：模拟一次完整 FOMC 加息周期
  - 预期积累期（prob 30%）→ 观望
  - 预期升温期（prob 55%）→ 观望/试探
  - 预期跳变期（prob 88%）→ 利空出尽信号
  - 事件落地日（加息25bp）→ 验证
  - 预期重定价期（relief rally）→ 验证多头

用法：
  cd 23-四层闭环自进化交易架构
  /usr/bin/python3 dreambuddy_evolution/scripts/backtest_macro_event.py
"""
from __future__ import annotations

import sys
import os

# 确保从架构目录运行时能导入 dreambuddy_evolution
# script 在 dreambuddy_evolution/scripts/ 下，需上溯 3 级到 23-四层闭环自进化交易架构/
_23_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, _23_dir)

# 事件驱动策略已迁移至 29-事件驱动策略系统（独立子交易系统）
_29_dir = os.path.join(os.path.dirname(_23_dir), "29-事件驱动策略系统")
if _29_dir not in sys.path:
    sys.path.insert(0, _29_dir)

import numpy as np

from event_driven.event_driven_strategy import EventDrivenStrategy
from event_driven.conviction_scorer import ConvictionScorer
from event_driven.event_dominance_controller import EventDominanceController
from dreambuddy_evolution.core.event_window_tracker import EventWindowTracker


def generate_fomc_cycle_data() -> list[dict]:
    """生成一次完整 FOMC 加息周期的合成数据（6 阶段）。"""
    np.random.seed(42)
    base_price = 2000.0  # 黄金基准价 $2000
    days = 60  # 60 天周期

    phases = [
        # (day_start, day_end, phase_name, hike_prob, trend, cpi_surprise)
        (0, 14, "expectation_build", 0.30, -0.001, None),       # 预期积累：阴跌
        (14, 28, "expectation_rise", 0.55, -0.002, None),        # 预期升温：加速跌
        (28, 42, "expectation_jump", 0.88, -0.003, 0.2),         # 预期跳变：CPI超预期+加速下跌
        (42, 43, "event", 0.93, -0.005, None),                   # 事件日：急跌
        (43, 56, "repricing", 0.10, 0.003, None),                # 重定价：relief rally
        (56, 60, "neutral", 0.05, 0.001, None),                  # 周期外
    ]

    records = []
    prices = [base_price]
    for day in range(days):
        # 确定当前阶段
        current_phase = "neutral"
        hike_prob = 0.05
        trend = 0.0
        cpi_surprise = None
        for (ds, de, name, prob, t, cs) in phases:
            if ds <= day < de:
                current_phase = name
                hike_prob = prob
                trend = t
                cpi_surprise = cs
                break

        # 生成价格
        ret = trend + np.random.normal(0, 0.008)
        # repricing 阶段 relief rally 更强
        if current_phase == "repricing":
            ret += 0.004
        new_price = prices[-1] * (1 + ret)
        prices.append(new_price)

        # 构造 K 线（最近 20 根）
        closes = prices[-20:] if len(prices) >= 20 else prices + [prices[-1]] * (20 - len(prices))
        high = [c * 1.005 for c in closes]
        low = [c * 0.995 for c in closes]
        open_ = [c * 0.999 for c in closes]

        # 跨资产数据
        if current_phase in ("expectation_jump", "repricing"):
            gold_change = 0.003 if current_phase == "repricing" else -0.002
            us10y_change = -2.0 if current_phase == "repricing" else 1.0
            dxy_change = -0.002 if current_phase == "repricing" else 0.001
        else:
            gold_change = ret
            us10y_change = -ret * 100
            dxy_change = -ret

        records.append({
            "day": day,
            "phase": current_phase,
            "price": round(new_price, 2),
            "kline_data": {
                "symbol": "GOLD",
                "close": closes,
                "high": high,
                "low": low,
                "open": open_,
                "cpi_surprise": cpi_surprise,
                "cpi_actual": 3.5,  # 通胀 3.5%（略低于名义利率 → 实际利率微正 → 预期阶段利空）
                "cpi_expected": 5.0,
                "rate_hike_prob": hike_prob,
                "monetary_cycle": "tightening" if hike_prob > 0.5 else "neutral",
                "gold_change_pct": gold_change,
                "us10y_change_bp": us10y_change,
                "dxy_change_pct": dxy_change,
                "capital_flow": 0.3 if current_phase == "repricing" else -0.2,
                # 🆕 FOMC 决议数据（事件日及之后）
                "fomc_decision": {
                    "decision": "hike" if current_phase in ("event", "repricing") else "hold",
                    "rate_change": 0.25 if current_phase in ("event", "repricing") else 0.0,
                    "dot_plot_median": 0.5 if current_phase in ("event", "repricing") else 0.0,  # 暗示更多加息 → 鹰派
                },
                "event_context": {
                    "cycle_phase": current_phase,
                    "event_window": "event" if current_phase == "event" else ("post_event" if current_phase == "repricing" else "pre_event"),
                    "in_fomc_cycle": current_phase != "neutral",
                    "hike_prob": hike_prob,
                    "probability_trend": "stable",
                    "dominant_direction": "short" if hike_prob > 0.5 else "long",
                },
            },
        })

    return records


def run_backtest():
    """运行回测并打印每个阶段的信号。"""
    print("=" * 80)
    print("宏观事件驱动策略回测 — FOMC 加息周期（合成数据）")
    print("=" * 80)

    records = generate_fomc_cycle_data()
    strategy = EventDrivenStrategy()
    scorer = ConvictionScorer()
    edc = EventDominanceController()

    print(f"\n{'Day':>4} {'Phase':<20} {'Price':>8} {'Signal':>8} {'Conf':>6} {'Filter':>6} {'FG':>8}")
    print("-" * 80)

    trade_pnl = 0.0
    position = None  # None / "long" / "short"
    entry_price = 0.0
    position_size = 1.0

    for rec in records:
        kd = rec["kline_data"]
        day = rec["day"]
        phase = rec["phase"]
        price = rec["price"]

        # 只在关键转折点打印（每阶段首日 + 事件日）
        is_phase_start = day == 0 or records[day - 1]["phase"] != phase

        # 1. EventDrivenStrategy
        ev_signal = strategy.evaluate(kd).to_dict()

        # 2. ConvictionScorer
        conviction = scorer.score(kd, ev_signal).to_dict()

        # 3. EventDominanceController
        decision = edc.decide(
            conviction=conviction["conviction"],
            macro_direction=ev_signal["signal"],
            data_quality=conviction["factors"]["data_quality"],
            in_fomc_cycle=kd["event_context"]["in_fomc_cycle"],
        )

        if is_phase_start:
            fg = ev_signal.get("forward_guidance", "")
            print(
                f"{day:>4} {phase:<20} {price:>8.2f} "
                f"{ev_signal['signal']:>8} {conviction['conviction']:>6.2f} "
                f"{decision.filter_level:>6} {fg:>8}"
            )

        # 模拟交易：信号明确时跟随宏观方向（硬过滤全仓，软过滤半仓，其余轻仓）
        if ev_signal["signal"] in ("long", "short") and kd["event_context"]["in_fomc_cycle"]:
            if decision.override_subsystems:
                pos_mult = 1.0
            elif decision.filter_level == "soft":
                pos_mult = 0.5
            else:
                pos_mult = 0.3
            if position is None:
                position = decision.macro_direction
                entry_price = price
                position_size = pos_mult
            elif position != decision.macro_direction:
                # 平仓反向
                pnl = (price - entry_price) / entry_price if position == "long" else (entry_price - price) / entry_price
                trade_pnl += pnl * position_size
                position = decision.macro_direction
                entry_price = price
                position_size = pos_mult
        elif phase == "neutral" and position is not None:
            # 周期结束平仓
            pnl = (price - entry_price) / entry_price if position == "long" else (entry_price - price) / entry_price
            trade_pnl += pnl * position_size
            position = None

    # 最终平仓
    if position is not None:
        final_price = records[-1]["price"]
        pnl = (final_price - entry_price) / entry_price if position == "long" else (entry_price - final_price) / entry_price
        trade_pnl += pnl * position_size

    print("-" * 80)
    print(f"\n回测结果:")
    print(f"  总交易日: {len(records)}")
    print(f"  总盈亏: {trade_pnl * 100:.2f}%")
    print(f"  最终价格: ${records[-1]['price']:.2f} (起始 ${records[0]['price']:.2f})")
    print(f"  买入持有收益: {(records[-1]['price'] / records[0]['price'] - 1) * 100:.2f}%")

    # 验证关键断言
    print(f"\n关键验证:")
    # 1. 买预期阶段：高 hike_prob → SHORT（利空正在被定价）
    expectation_signals = [r for r in records if r["phase"] == "expectation_jump"]
    if expectation_signals:
        last_exp = expectation_signals[-1]["kline_data"]
        sig = strategy.evaluate(last_exp).to_dict()
        print(f"  expectation_jump 信号: {sig['signal']} (期望 short/买预期)")
        assert sig["signal"] == "short", f"expectation_jump 应输出 short，实际 {sig['signal']}"

    # 2. 卖事实阶段：事件落地后 → LONG（利空出尽）
    repricing_signals = [r for r in records if r["phase"] == "repricing"]
    if repricing_signals:
        last_repricing = repricing_signals[-1]["kline_data"]
        sig = strategy.evaluate(last_repricing).to_dict()
        print(f"  repricing 信号: {sig['signal']} (期望 long/卖事实)")
        assert sig["signal"] == "long", f"repricing 应输出 long，实际 {sig['signal']}"

    # 3. 前瞻指引：点阵图偏鹰
    if repricing_signals:
        sig = strategy.evaluate(repricing_signals[-1]["kline_data"]).to_dict()
        print(f"  forward_guidance: {sig.get('forward_guidance', '')} (期望 hawkish)")
        assert sig.get("forward_guidance") == "hawkish", f"forward_guidance 应为 hawkish"

    print("  ✓ 所有断言通过")
    return trade_pnl


if __name__ == "__main__":
    pnl = run_backtest()
    sys.exit(0 if pnl > -0.05 else 1)
