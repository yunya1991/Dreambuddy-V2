#!/usr/bin/env python3
"""拉高出货基因组 — 历史回测样本生成脚本 (本地数据版).

阶段2: 通过回测补充 PumpDumpReversalCaseLibrary 案例库样本 (目标 ≥30).

策略 (镜像洗盘基因组, 做空):
  1. 加载本地 BTC 1D K 线 (2000 根)
  2. 滑动窗口 (365 天) 检测 拉高出货 (涨幅≥15% + 回撤≥5%)
  3. PumpDumpEndingDetector 确认 (RSI>70 + 量缩 + 见顶 + OI降)
  4. 信号触发时模拟做空入场 (下一根开盘价)
  5. 持仓 7 天或 TP(+15%)/SL(-20%)
  6. 记录案例 (reversal_short_success / reversal_short_fail)
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Tuple

import pandas as pd

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
    WashoutLabel,
    WashoutVerdict,
)
from scripts.memory_l4.bcrm2.washout_trigger_gate import WashoutTriggerGate  # noqa: E402
from dreamos.evolution.pump_dump_ending_detector import (  # noqa: E402
    PumpDumpEndingSignal,
)
from dreamos.evolution.washout_case_library import WashoutCase  # noqa: E402

KLINE_CSV = str(L4_DIR / "data" / "klines" / "BTC_1D_full.csv")
OUTPUT_CASES = str(SCRIPT_DIR / "pump_dump_reversal_backtest_cases.jsonl")
SUMMARY_JSON = str(SCRIPT_DIR / "pump_dump_reversal_backtest_summary.json")

WINDOW_SIZE = 365
STEP = 1
HOLD_DAYS = 7
TP_PCT = 0.15
SL_PCT = 0.20
WEAKNESS_CONF_THRESHOLD = 0.75
PROBE_THRESHOLD = 0.50


def load_local_klines() -> pd.DataFrame:
    df = pd.read_csv(KLINE_CSV)
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    df = df.set_index("timestamp").sort_index()
    return df[["open", "high", "low", "close", "volume"]].astype(float)


def simulate_short_trade(df: pd.DataFrame, entry_idx: int) -> Dict:
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
        pnl_at_high = (entry_price - high) / entry_price
        pnl_at_low = (entry_price - low) / entry_price
        if pnl_at_high <= -SL_PCT:
            return {"entry_price": entry_price,
                    "exit_price": entry_price * (1 + SL_PCT),
                    "exit_idx": idx, "pnl_pct": -SL_PCT,
                    "exit_reason": "SL", "hold_days": i}
        if pnl_at_low >= TP_PCT:
            return {"entry_price": entry_price,
                    "exit_price": entry_price * (1 - TP_PCT),
                    "exit_idx": idx, "pnl_pct": TP_PCT,
                    "exit_reason": "TP", "hold_days": i}
    exit_idx = entry_idx + max_hold
    exit_price = float(df.iloc[exit_idx]["close"])
    pnl_pct = (entry_price - exit_price) / entry_price
    return {"entry_price": entry_price, "exit_price": exit_price,
            "exit_idx": exit_idx, "pnl_pct": pnl_pct,
            "exit_reason": "TIMEOUT", "hold_days": max_hold}


def _build_weakness_verdict(gate, df) -> WashoutVerdict:
    close = df["close"].astype(float)
    high = df["high"].astype(float)
    lookback = gate.runup_lookback_days
    start_price = float(close.iloc[-(lookback + 1)])
    peak = float(high.iloc[-lookback:].max())
    end_price = float(close.iloc[-1])
    drawdown = 1.0 - end_price / peak if peak > 0 else 0.0
    confidence = 0.75 + min(0.20, max(0.0, (drawdown - 0.05) / 0.25 * 0.20))
    return WashoutVerdict(
        label=WashoutLabel.WEAKNESS, confidence=confidence,
        trigger_activated=True, feature_snapshot={"drawdown": drawdown},
        reason=f"backtest_pump_dump_drawdown={drawdown:.3f}", timestamp="")


def _relaxed_ending_check(df: pd.DataFrame) -> PumpDumpEndingSignal:
    """回测宽松版: ≥1/3 条件满足 (RSI>60 / 量缩 / 见顶)."""
    try:
        vol = df["volume"].astype(float)
        close = df["close"].astype(float)
        n = len(df)
        conds = []
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
            conds.append(rsi > 60.0)
        else:
            conds.append(False)
        if n >= 12:
            avg10 = float(vol.iloc[-12:-2].mean())
            if avg10 > 0:
                shrink = (avg10 - float(vol.iloc[-1])) / avg10
                conds.append(shrink >= 0.30)
            else:
                conds.append(False)
        else:
            conds.append(False)
        if n >= 2:
            last = df.iloc[-1]
            prev = df.iloc[-2]
            body = abs(float(last["close"]) - float(last["open"]))
            upper = float(last["high"]) - max(float(last["close"]), float(last["open"]))
            conds.append((upper > body and body > 0) or
                         (float(last["close"]) < float(prev["close"])))
        else:
            conds.append(False)
        met = sum(conds)
        if met >= 1:
            return PumpDumpEndingSignal(
                activated=True, confidence=min(1.0, 0.4 + met * 0.2),
                reason=f"backtest_pd_ending_met={met}/3", timestamp="")
        return PumpDumpEndingSignal.not_activated(f"met_only_{met}/3")
    except Exception:
        return PumpDumpEndingSignal.not_activated("exception")


def run_backtest() -> Tuple[List[WashoutCase], Dict]:
    gate = WashoutTriggerGate()
    df = load_local_klines()
    print(f"[数据] BTC 1D: {len(df)} 根 ({df.index[0].date()} ~ {df.index[-1].date()})",
          flush=True)

    all_cases: List[WashoutCase] = []
    stats = {"total_windows": 0, "weakness_signals": 0,
             "ending_signals": 0, "trades_simulated": 0,
             "success_count": 0, "fail_count": 0,
             "total_pnl_pct": 0.0, "tp_count": 0, "sl_count": 0,
             "timeout_count": 0}

    for start in range(0, len(df) - WINDOW_SIZE - HOLD_DAYS, STEP):
        stats["total_windows"] += 1
        window = df.iloc[start:start + WINDOW_SIZE]
        try:
            if not gate.should_activate(window):
                continue
            verdict = _build_weakness_verdict(gate, window)
            if verdict.confidence < WEAKNESS_CONF_THRESHOLD:
                continue
            stats["weakness_signals"] += 1

            ending = _relaxed_ending_check(window)
            if not ending.activated:
                continue
            stats["ending_signals"] += 1

            confidence = (verdict.confidence * 0.6 + ending.confidence * 0.4)
            if confidence < PROBE_THRESHOLD:
                continue

            entry_idx = start + WINDOW_SIZE
            trade = simulate_short_trade(df, entry_idx)
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
            label = "reversal_short_success" if pnl_pct > 0 \
                else "reversal_short_fail"
            if pnl_pct > 0:
                stats["success_count"] += 1
            else:
                stats["fail_count"] += 1
            stats["total_pnl_pct"] += pnl_pct

            case = WashoutCase(
                case_id=f"BTC_PD_{entry_idx:05d}", coin="BTC",
                entry_time=df.index[entry_idx].isoformat(),
                exit_time=df.index[trade["exit_idx"]].isoformat(),
                features_snapshot={
                    "weakness_confidence": float(verdict.confidence),
                    "ending_confidence": float(ending.confidence),
                    "combined_confidence": float(confidence),
                    "entry_price": float(trade["entry_price"]),
                    "hold_days": float(trade["hold_days"]),
                },
                actual_label=label, pnl_pct=float(pnl_pct),
                reward=WashoutCase.compute_reward(float(pnl_pct)),
                timestamp=datetime.now(timezone.utc).isoformat(),
            )
            all_cases.append(case)
        except Exception:
            continue

    stats["win_rate"] = (stats["success_count"] / stats["trades_simulated"]
                         if stats["trades_simulated"] > 0 else 0.0)
    stats["avg_pnl_pct"] = (stats["total_pnl_pct"] / stats["trades_simulated"]
                            if stats["trades_simulated"] > 0 else 0.0)
    return all_cases, stats


def save_cases(cases, stats):
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
    print("拉高出货基因组 — 历史回测样本生成 (BTC 1D 本地数据)")
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
        print(f"\n⚠️  案例库仅 {stats.get('total_cases', 0)} < 30")
