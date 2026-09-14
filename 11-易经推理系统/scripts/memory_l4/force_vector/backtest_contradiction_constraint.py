"""三层矛盾感知方向约束 — 阈值参数回测脚本。

目标：用历史快照信号 + 历史交易实际盈亏作为 ground truth，
网格搜索最优阈值参数组合。

评估指标：
  - TP（真阳性）：新算法拦截做多 + 实际亏损 → 避免了亏损
  - FP（假阳性）：新算法拦截做多 + 实际盈利 → 错过了盈利
  - FN（假阴性）：新算法放行做多 + 实际亏损 → 没拦住
  - TN（真阴性）：新算法放行做多 + 实际盈利 → 正确放行

净收益 = TP平均亏损金额 - FP平均盈利金额（被拦截交易的盈亏差）
最优参数 = 净收益最大化 + FN最小化
"""
from __future__ import annotations

import csv
import glob
import json
import os
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

# 路径设置
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_BASE_11 = os.path.dirname(os.path.dirname(os.path.dirname(_THIS_DIR)))
_BDSM_DIR = os.path.join(_BASE_11, ".workbuddy", "bdsm")
_REV_DIR = os.path.join(_BASE_11, ".workbuddy", "memory_l4", "reviews")
for _p in (_BDSM_DIR, _BASE_11, os.path.join(_BASE_11, "scripts", "memory_l4", "force_vector")):
    if _p not in sys.path:
        sys.path.insert(0, _p)


@dataclass
class SnapshotRecord:
    """单条快照信号记录。"""
    date: str
    coin: str
    bds_score: float
    confidence: float
    data_quality: str
    direction_old: str
    value_exit_action: str
    valuation_percentile: float


@dataclass
class TradeRecord:
    """单条历史交易记录。"""
    case_id: str
    coin: str
    trade_date: str
    direction: str  # success / failure
    pnl_pct: float = 0.0  # 盈亏百分比（正=盈利，负=亏损）


def load_snapshot_records() -> list[SnapshotRecord]:
    """加载所有历史快照中的信号记录。"""
    records = []
    for sf in sorted(glob.glob(os.path.join(_BDSM_DIR, "bdsm_snapshot_*.json"))):
        d = json.load(open(sf))
        date = os.path.basename(sf).replace("bdsm_snapshot_", "").replace(".json", "")
        for coin, c in d.get("coins", {}).items():
            ve = c.get("value_exit") or {}
            records.append(SnapshotRecord(
                date=date,
                coin=coin,
                bds_score=float(c.get("bds_score", 0.0) or 0.0),
                confidence=float(c.get("confidence", 0.0) or 0.0),
                data_quality=str(c.get("data_quality", "insufficient")),
                direction_old=str(c.get("direction_constraint", "NEUTRAL")),
                value_exit_action=str(ve.get("action", "none") or "none"),
                valuation_percentile=float(c.get("valuation_percentile", 50.0) or 50.0),
            ))
    return records


def load_trade_records() -> list[TradeRecord]:
    """加载所有历史交易 review 记录，提取实际盈亏。"""
    records = []
    for rf in sorted(glob.glob(os.path.join(_REV_DIR, "REV_*.json"))):
        d = json.load(open(rf))
        case_id = d.get("case_id", "")
        # case_id 格式: TC_live_SOL-USDT-SWAP_20260910_140612
        parts = case_id.split("_")
        if len(parts) < 5:
            continue
        coin_full = parts[2]  # SOL-USDT-SWAP
        coin = coin_full.split("-")[0] if "-" in coin_full else coin_full
        trade_date = parts[3] if len(parts) > 3 else ""
        direction = d.get("direction", "unknown")

        # 从 mistakes 中提取 PnL
        pnl_pct = 0.0
        mistakes = d.get("mistakes", [])
        if mistakes:
            what = mistakes[0].get("what", "")
            # 格式: "交易亏损 -3.5%" 或 "交易盈利 2.1%"
            import re
            m = re.search(r"(-?[\d.]+)%", what)
            if m:
                pnl_pct = float(m.group(1))
                if "亏损" in what and pnl_pct > 0:
                    pnl_pct = -pnl_pct

        records.append(TradeRecord(
            case_id=case_id,
            coin=coin,
            trade_date=trade_date,
            direction=direction,
            pnl_pct=pnl_pct,
        ))
    return records


def compute_direction_v2_with_params(
    bds_score: float,
    confidence: float,
    data_quality: str,
    value_exit_action: str,
    valuation_percentile: float,
    base_threshold: float = 0.3,
    conf_discount: float = 0.5,
    l2_conf_threshold: float = 0.70,
    l3_val_threshold: float = 85.0,
) -> str:
    """带可调参数的 _compute_direction_v2。"""
    if data_quality == "insufficient":
        return "NEUTRAL"

    effective_threshold = base_threshold * (1.0 - conf_discount * confidence)
    if bds_score > effective_threshold:
        return "LONG_ONLY"
    if bds_score < -effective_threshold:
        return "SHORT_ONLY"

    if (
        value_exit_action == "full_exit"
        and bds_score < 0.0
        and confidence >= l2_conf_threshold
    ):
        return "LONG_BLOCKED"

    if (
        valuation_percentile > l3_val_threshold
        and bds_score < 0.0
        and data_quality == "sufficient"
    ):
        return "LONG_BLOCKED"

    return "NEUTRAL"


def run_backtest(
    snapshots: list[SnapshotRecord],
    trades: list[TradeRecord],
    params: dict[str, float],
) -> dict[str, Any]:
    """运行单组参数的回测。"""
    # 按币种+日期索引快照
    snap_index: dict[tuple[str, str], SnapshotRecord] = {}
    for s in snapshots:
        snap_index[(s.coin, s.date)] = s

    # 按币种+日期分组交易
    trade_groups: dict[tuple[str, str], list[TradeRecord]] = defaultdict(list)
    for t in trades:
        trade_groups[(t.coin, t.trade_date)].append(t)

    tp_count = 0  # 拦截做多+实际亏损
    fp_count = 0  # 拦截做多+实际盈利
    fn_count = 0  # 放行做多+实际亏损
    tn_count = 0  # 放行做多+实际盈利
    tp_pnl_sum = 0.0  # 被拦截的亏损交易的总亏损
    fp_pnl_sum = 0.0  # 被误拦截的盈利交易的总盈利

    # 遍历所有交易
    for (coin, date), day_trades in trade_groups.items():
        snap = snap_index.get((coin, date))
        if snap is None:
            continue

        # 用新算法计算方向约束
        new_dir = compute_direction_v2_with_params(
            bds_score=snap.bds_score,
            confidence=snap.confidence,
            data_quality=snap.data_quality,
            value_exit_action=snap.value_exit_action,
            valuation_percentile=snap.valuation_percentile,
            **params,
        )

        # 判断新算法是否拦截做多
        new_blocks_long = new_dir in ("SHORT_ONLY", "LONG_BLOCKED")

        # 旧算法是否放行做多（非 SHORT_ONLY）
        old_allows_long = snap.direction_old != "SHORT_ONLY"

        # 只分析旧算法放行但新算法可能不同的交易
        if not old_allows_long:
            continue  # 旧算法已拦截，不在分析范围

        for t in day_trades:
            is_loss = t.direction == "failure" or t.pnl_pct < 0

            if new_blocks_long:
                # 新算法拦截了这笔交易
                if is_loss:
                    tp_count += 1
                    tp_pnl_sum += abs(t.pnl_pct)
                else:
                    fp_count += 1
                    fp_pnl_sum += abs(t.pnl_pct)
            else:
                # 新算法也放行
                if is_loss:
                    fn_count += 1
                else:
                    tn_count += 1

    total_intercepted = tp_count + fp_count
    total_allowed = fn_count + tn_count
    net_benefit = tp_pnl_sum - fp_pnl_sum  # 净收益 = 避免的亏损 - 错过的盈利

    precision = tp_count / total_intercepted if total_intercepted > 0 else 0.0
    recall = tp_count / (tp_count + fn_count) if (tp_count + fn_count) > 0 else 0.0

    return {
        "params": params,
        "tp": tp_count,
        "fp": fp_count,
        "fn": fn_count,
        "tn": tn_count,
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "net_benefit_pct": round(net_benefit, 2),
        "total_intercepted": total_intercepted,
        "total_allowed": total_allowed,
    }


def grid_search(snapshots: list[SnapshotRecord], trades: list[TradeRecord]) -> list[dict]:
    """参数网格搜索。"""
    # 参数网格
    param_grid = {
        "base_threshold": [0.25, 0.30, 0.35],
        "conf_discount": [0.3, 0.5, 0.7],
        "l2_conf_threshold": [0.60, 0.65, 0.70, 0.75, 0.80],
        "l3_val_threshold": [75.0, 80.0, 85.0, 90.0],
    }

    results = []
    for bt in param_grid["base_threshold"]:
        for cd in param_grid["conf_discount"]:
            for l2c in param_grid["l2_conf_threshold"]:
                for l3v in param_grid["l3_val_threshold"]:
                    params = {
                        "base_threshold": bt,
                        "conf_discount": cd,
                        "l2_conf_threshold": l2c,
                        "l3_val_threshold": l3v,
                    }
                    result = run_backtest(snapshots, trades, params)
                    results.append(result)

    # 按 net_benefit 降序排列
    results.sort(key=lambda x: x["net_benefit_pct"], reverse=True)
    return results


def main() -> None:
    print("=" * 80)
    print("三层矛盾感知方向约束 — 阈值参数回测")
    print("=" * 80)

    # 加载数据
    snapshots = load_snapshot_records()
    trades = load_trade_records()
    print(f"\n快照记录: {len(snapshots)} 条")
    print(f"交易记录: {len(trades)} 条")

    # 统计 SOL 交易
    sol_trades = [t for t in trades if t.coin == "SOL"]
    sol_fail = [t for t in sol_trades if t.direction == "failure"]
    sol_succ = [t for t in sol_trades if t.direction == "success"]
    print(f"\nSOL 交易: {len(sol_trades)} 笔 (失败{len(sol_fail)} 成功{len(sol_succ)})")
    if sol_trades:
        sol_pnl = sum(t.pnl_pct for t in sol_trades)
        print(f"SOL 总 PnL: {sol_pnl:.2f}%")

    # 旧算法基线
    print("\n" + "-" * 80)
    print("旧算法基线（当前线上参数）")
    print("-" * 80)
    baseline_params = {
        "base_threshold": 0.3,
        "conf_discount": 0.5,
        "l2_conf_threshold": 0.70,
        "l3_val_threshold": 85.0,
    }
    baseline = run_backtest(snapshots, trades, baseline_params)
    print(f"  TP(拦截+亏损): {baseline['tp']}")
    print(f"  FP(拦截+盈利): {baseline['fp']}")
    print(f"  FN(放行+亏损): {baseline['fn']}")
    print(f"  TN(放行+盈利): {baseline['tn']}")
    print(f"  精确率: {baseline['precision']:.2%}")
    print(f"  召回率: {baseline['recall']:.2%}")
    print(f"  净收益(避免亏损-错过盈利): {baseline['net_benefit_pct']:.2f}%")

    # 网格搜索
    print("\n" + "-" * 80)
    print("参数网格搜索（180 组参数组合）")
    print("-" * 80)
    results = grid_search(snapshots, trades)

    # 输出 Top 10
    print("\nTop 10 参数组合（按净收益排序）:")
    print(f"{'排名':<4} {'base':<6} {'disc':<6} {'l2c':<6} {'l3v':<6} {'TP':<4} {'FP':<4} {'FN':<4} {'TN':<4} {'精确率':<8} {'召回率':<8} {'净收益':<10}")
    for i, r in enumerate(results[:10]):
        p = r["params"]
        print(f"{i+1:<4} {p['base_threshold']:<6} {p['conf_discount']:<6} {p['l2_conf_threshold']:<6} {p['l3_val_threshold']:<6} "
              f"{r['tp']:<4} {r['fp']:<4} {r['fn']:<4} {r['tn']:<4} {r['precision']:<8.2%} {r['recall']:<8.2%} {r['net_benefit_pct']:<10.2f}")

    # 推荐参数
    print("\n" + "=" * 80)
    best = results[0]
    p = best["params"]
    print(f"推荐参数: base={p['base_threshold']}, disc={p['conf_discount']}, "
          f"l2c={p['l2_conf_threshold']}, l3v={p['l3_val_threshold']}")
    print(f"  TP={best['tp']} FP={best['fp']} FN={best['fn']} TN={best['tn']}")
    print(f"  精确率={best['precision']:.2%} 召回率={best['recall']:.2%}")
    print(f"  净收益={best['net_benefit_pct']:.2f}%")

    # 与当前参数对比
    if best["net_benefit_pct"] > baseline["net_benefit_pct"]:
        print(f"\n✓ 推荐参数比当前参数净收益提升: {best['net_benefit_pct'] - baseline['net_benefit_pct']:.2f}%")
    else:
        print(f"\n当前参数已是最优或接近最优（差异: {best['net_benefit_pct'] - baseline['net_benefit_pct']:.2f}%）")


if __name__ == "__main__":
    main()
