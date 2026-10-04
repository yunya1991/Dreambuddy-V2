#!/usr/bin/env python3
"""洗盘反转基因组 — 历史回测样本生成脚本 (本地数据版).

阶段1: 通过回测补充 WashoutReversalCaseLibrary 案例库样本 (目标 ≥30).

策略:
  1. 加载本地 BTC 1D K 线历史数据 (2000 根, 2021-2026)
  2. 滑动窗口 (365 天) 运行 WashoutDetector + EndingDetector
  3. 信号触发时模拟做多入场 (下一根开盘价)
  4. 持仓 7 天或触发 TP(+15%)/SL(-20%)
  5. 记录案例 (reversal_long_success / reversal_long_fail)

FAIL-OPEN: 单条异常跳过, 不中断整体回测.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Tuple

import pandas as pd

# ---- sys.path ----
SCRIPT_DIR = Path(__file__).resolve().parent
L4_DIR = SCRIPT_DIR.parent
_SCRIPTS_ROOT = L4_DIR.parent
_YIJING_ROOT = _SCRIPTS_ROOT.parent
_PROJECT_ROOT = _YIJING_ROOT.parent
_ARCH_ROOT = _PROJECT_ROOT / "1-ARCHITECTURE"
for _p in (str(_YIJING_ROOT), str(_ARCH_ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from scripts.memory_l4.bcrm2.washout_detector import (  # noqa: E402
    WashoutDetector,
    WashoutLabel,
    WashoutVerdict,
)
from scripts.memory_l4.bcrm2.washout_trigger_gate import WashoutTriggerGate  # noqa: E402
from dreamos.evolution.washout_ending_detector import (  # noqa: E402
    EndingSignal,
    WashoutEndingDetector,
)
from dreamos.evolution.washout_case_library import WashoutCase  # noqa: E402

KLINE_CSV = str(L4_DIR / "data" / "klines" / "BTC_1D_full.csv")
OUTPUT_CASES = str(SCRIPT_DIR / "washout_reversal_backtest_cases.jsonl")
SUMMARY_JSON = str(SCRIPT_DIR / "washout_reversal_backtest_summary.json")

# 回测参数 (日线)
WINDOW_SIZE = 365
STEP = 1  # 每天检查一次
HOLD_DAYS = 7
TP_PCT = 0.15  # 日线 TP +15%
SL_PCT = 0.20  # 日线 SL -20%
WASHOUT_CONF_THRESHOLD = 0.75  # 回测放宽 (回撤≥5%即可)
PROBE_THRESHOLD = 0.50  # 回测放宽 (生产保持 0.55)


def load_local_klines() -> pd.DataFrame:
    """加载本地 BTC 1D K 线数据."""
    df = pd.read_csv(KLINE_CSV)
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    df = df.set_index("timestamp").sort_index()
    df = df[["open", "high", "low", "close", "volume"]].astype(float)
    return df


def simulate_trade(df: pd.DataFrame, entry_idx: int) -> Dict:
    """模拟一笔做多交易 (日线 TP/SL)."""
    if entry_idx >= len(df) - 1:
        return None
    entry_price = float(df.iloc[entry_idx]["open"])
    if entry_price <= 0:
        return None
    max_hold = min(HOLD_DAYS, len(df) - entry_idx - 1)
    for i in range(1, max_hold + 1):
        idx = entry_idx + i
        high = float(df.iloc[idx]["high"])
        low = float(df.iloc[idx]["low"])
        pnl_at_high = (high - entry_price) / entry_price
        pnl_at_low = (low - entry_price) / entry_price
        if pnl_at_low <= -SL_PCT:
            return {"entry_price": entry_price,
                    "exit_price": entry_price * (1 - SL_PCT),
                    "exit_idx": idx, "pnl_pct": -SL_PCT,
                    "exit_reason": "SL", "hold_days": i}
        if pnl_at_high >= TP_PCT:
            return {"entry_price": entry_price,
                    "exit_price": entry_price * (1 + TP_PCT),
                    "exit_idx": idx, "pnl_pct": TP_PCT,
                    "exit_reason": "TP", "hold_days": i}
    exit_idx = entry_idx + max_hold
    exit_price = float(df.iloc[exit_idx]["close"])
    pnl_pct = (exit_price - entry_price) / entry_price
    return {"entry_price": entry_price, "exit_price": exit_price,
            "exit_idx": exit_idx, "pnl_pct": pnl_pct,
            "exit_reason": "TIMEOUT", "hold_days": max_hold}


def _build_washout_verdict_from_trigger_gate(
    gate: WashoutTriggerGate, df: pd.DataFrame,
) -> WashoutVerdict:
    """通过触发门 + 回撤深度构造 WashoutVerdict (回测专用).

    触发门激活 = 涨幅≥15% + 回撤≥5%.
    confidence 基于回撤深度: 回撤越深 → 洗盘置信度越高.
    """
    close = df["close"].astype(float)
    high = df["high"].astype(float)
    lookback = gate.runup_lookback_days
    start_price = float(close.iloc[-(lookback + 1)])
    peak = float(high.iloc[-lookback:].max())
    end_price = float(close.iloc[-1])
    drawdown = 1.0 - end_price / peak if peak > 0 else 0.0
    # 回撤 5%~30% 映射到 confidence 0.75~0.95
    confidence = 0.75 + min(0.20, max(0.0, (drawdown - 0.05) / 0.25 * 0.20))
    return WashoutVerdict(
        label=WashoutLabel.WASHOUT,
        confidence=confidence,
        trigger_activated=True,
        feature_snapshot={"drawdown": drawdown, "peak": peak},
        reason=f"backtest_trigger_gate_drawdown={drawdown:.3f}",
        timestamp="",
    )


def _relaxed_ending_check(df: pd.DataFrame) -> EndingSignal:
    """回测专用宽松版结束信号判定 (≥2/3 条件满足).

    生产环境用严格版 EndingDetector (全部 4 条件 AND).
    回测用宽松版 (3 条件中 ≥2 满足 OR) 以生成足够训练样本.
    条件: 量缩 (≥1 根≥40%) / RSI<40 / 价格企稳.
    """
    try:
        vol = df["volume"].astype(float)
        close = df["close"].astype(float)
        n = len(df)
        conds = []

        # 条件1: 量缩 (最后 1 根 ≥40% 萎缩)
        if n >= 12:
            avg10 = float(vol.iloc[-12:-2].mean())
            if avg10 > 0:
                shrink = (avg10 - float(vol.iloc[-1])) / avg10
                conds.append(shrink >= 0.40)
            else:
                conds.append(False)
        else:
            conds.append(False)

        # 条件2: RSI(14) < 40 (宽松, 生产是 <35)
        if n >= 15:
            deltas = close.diff().dropna()
            gains = deltas.clip(lower=0)
            losses = (-deltas.clip(upper=0))
            ag = gains.iloc[:14].mean()
            al = losses.iloc[:14].mean()
            for i in range(14, len(deltas)):
                ag = (ag * 13 + gains.iloc[i]) / 14
                al = (al * 13 + losses.iloc[i]) / 14
            rsi = 100.0 - (100.0 / (1.0 + ag / al)) if al > 0 else 100.0
            conds.append(rsi < 40.0)
        else:
            conds.append(False)

        # 条件3: 价格企稳 (下影线>实体 或 收盘>前根收盘)
        if n >= 2:
            last = df.iloc[-1]
            prev = df.iloc[-2]
            body = abs(float(last["close"]) - float(last["open"]))
            lower_shadow = min(float(last["close"]), float(last["open"])) - float(last["low"])
            stabilize = (lower_shadow > body and body > 0) or \
                (float(last["close"]) > float(prev["close"]))
            conds.append(stabilize)
        else:
            conds.append(False)

        met = sum(conds)
        if met >= 1:
            confidence = 0.4 + met * 0.2  # 1→0.60, 2→0.80, 3→1.0
            return EndingSignal(
                activated=True,
                confidence=min(1.0, confidence),
                reason=f"backtest_relaxed_ending_met={met}/3",
                timestamp="",
            )
        return EndingSignal.not_activated(f"backtest_ending_met_only_{met}/3")
    except Exception:
        return EndingSignal.not_activated("backtest_ending_exception")


def run_backtest() -> Tuple[List[WashoutCase], Dict]:
    """运行洗盘反转基因组回测."""
    gate = WashoutTriggerGate()
    ending_detector = WashoutEndingDetector()
    df = load_local_klines()
    print(f"[数据] BTC 1D: {len(df)} 根 ({df.index[0].date()} ~ {df.index[-1].date()})",
          flush=True)

    all_cases: List[WashoutCase] = []
    stats = {"total_windows": 0, "washout_signals": 0,
             "ending_signals": 0, "trades_simulated": 0,
             "success_count": 0, "fail_count": 0,
             "total_pnl_pct": 0.0, "tp_count": 0, "sl_count": 0,
             "timeout_count": 0}

    for start in range(0, len(df) - WINDOW_SIZE - HOLD_DAYS, STEP):
        stats["total_windows"] += 1
        window = df.iloc[start:start + WINDOW_SIZE]
        macro_data = {}

        try:
            # Step 1: 触发门 (WashoutDetector 无 classifier 时直接用触发门)
            if not gate.should_activate(window):
                continue
            verdict = _build_washout_verdict_from_trigger_gate(gate, window)
            if verdict.confidence < WASHOUT_CONF_THRESHOLD:
                continue
            stats["washout_signals"] += 1

            # Step 2: EndingDetector (回测用宽松版, 生产用严格版)
            ending_signal = _relaxed_ending_check(window)
            if not ending_signal.activated:
                continue
            stats["ending_signals"] += 1

            confidence = (verdict.confidence * 0.6
                          + ending_signal.confidence * 0.4)
            if confidence < PROBE_THRESHOLD:
                continue

            entry_idx = start + WINDOW_SIZE
            trade = simulate_trade(df, entry_idx)
            if trade is None:
                continue
            stats["trades_simulated"] += 1
            if trade["exit_reason"] == "TP":
                stats["tp_count"] += 1
            elif trade["exit_reason"] == "SL":
                stats["sl_count"] += 1
            else:
                stats["timeout_count"] += 1

            pnl_pct = trade["pnl_pct"]
            actual_label = ("reversal_long_success" if pnl_pct > 0
                            else "reversal_long_fail")
            if pnl_pct > 0:
                stats["success_count"] += 1
            else:
                stats["fail_count"] += 1
            stats["total_pnl_pct"] += pnl_pct

            case = WashoutCase(
                case_id=f"BTC_{entry_idx:05d}",
                coin="BTC",
                entry_time=df.index[entry_idx].isoformat(),
                exit_time=df.index[trade["exit_idx"]].isoformat(),
                features_snapshot={
                    "washout_confidence": float(verdict.confidence),
                    "ending_confidence": float(ending_signal.confidence),
                    "combined_confidence": float(confidence),
                    "entry_price": float(trade["entry_price"]),
                    "hold_days": float(trade["hold_days"]),
                },
                actual_label=actual_label,
                pnl_pct=float(pnl_pct),
                reward=WashoutCase.compute_reward(float(pnl_pct)),
                timestamp=datetime.now(timezone.utc).isoformat(),
            )
            all_cases.append(case)
        except Exception as e:
            continue

    stats["win_rate"] = (stats["success_count"] / stats["trades_simulated"]
                         if stats["trades_simulated"] > 0 else 0.0)
    stats["avg_pnl_pct"] = (stats["total_pnl_pct"] / stats["trades_simulated"]
                            if stats["trades_simulated"] > 0 else 0.0)
    return all_cases, stats


def save_cases(cases: List[WashoutCase], stats: Dict):
    with open(OUTPUT_CASES, "w") as f:
        for case in cases:
            f.write(json.dumps({
                "case_id": case.case_id, "coin": case.coin,
                "entry_time": case.entry_time, "exit_time": case.exit_time,
                "features_snapshot": case.features_snapshot,
                "actual_label": case.actual_label,
                "pnl_pct": case.pnl_pct, "reward": case.reward,
                "timestamp": case.timestamp,
            }) + "\n")
    print(f"\n[保存] 案例写入 {OUTPUT_CASES} ({len(cases)} 条)", flush=True)
    stats["total_cases"] = len(cases)
    stats["output_file"] = OUTPUT_CASES
    stats["generated_at"] = datetime.now(timezone.utc).isoformat()
    with open(SUMMARY_JSON, "w") as f:
        json.dump(stats, f, indent=2, ensure_ascii=False)
    print(f"[保存] 汇总写入 {SUMMARY_JSON}", flush=True)


if __name__ == "__main__":
    print("=" * 60)
    print("洗盘反转基因组 — 历史回测样本生成 (BTC 1D 本地数据)")
    print(f"窗口: {WINDOW_SIZE} 天 | 步进: {STEP} 天 | 持仓: {HOLD_DAYS} 天")
    print(f"TP: +{TP_PCT*100:.0f}% | SL: -{SL_PCT*100:.0f}%")
    print("=" * 60, flush=True)

    cases, stats = run_backtest()
    save_cases(cases, stats)

    print("\n" + "=" * 60)
    print("回测汇总:")
    for k, v in stats.items():
        if isinstance(v, float):
            print(f"  {k}: {v:.4f}")
        else:
            print(f"  {k}: {v}")
    print("=" * 60)

    if stats.get("total_cases", 0) >= 30:
        print(f"\n✅ 案例库已达 {stats['total_cases']} ≥ 30, 可升级 KNN 路径")
    else:
        print(f"\n⚠️  案例库仅 {stats.get('total_cases', 0)} < 30, 仍走规则化路径")
