#!/usr/bin/env python3
"""
贝叶斯参数优化引擎 v3.0
========================
完全对齐 backtest_strategy.py v3.0 + backtest_engine.py v3.0

v3.0 重大修正:
  1. 参数空间对齐v3.0: 8维原参数 + 1维新增(sl_cooldown_days)
  2. 支持分批止盈 (TP 3值返回)
  3. 支持止损冷却期
  4. short_score_threshold 可优化 (方向灵敏度)
  5. stop_loss_pct 固定20%, 不可优化

参数空间 (9维):
  θ1: strong_score_threshold [55, 75]  — 强多头阈值
  θ2: weak_score_threshold   [40, 60]  — 弱多头阈值
  θ3: short_score_threshold  [25, 45]  — 空头阈值 (方向灵敏度)
  θ4: level_spacing_k        [0.3, 1.0] — 加仓间隔系数
  θ5: tp_level_1             [1.5, 4.0] — TP1 ATR倍数
  θ6: tp_level_2             [2.5, 5.0] — TP2 ATR倍数
  θ7: tp_level_3             [4.0, 8.0] — TP3 ATR倍数
  θ8: base_pos_pct           [50, 150]  — 基础仓位比例%
  θ9: sl_cooldown_days       [0, 7]    — 止损冷却天数

用法:
  python3 bayesian_opt_engine.py
  python3 bayesian_opt_engine.py --quick
  python3 bayesian_opt_engine.py --objective calmar --rounds 300
"""

import os
import sys
import json
import re
import time
import argparse
import statistics
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass

import numpy as np
from scipy.optimize import differential_evolution

SCRIPTS_DIR = Path(__file__).parent
PROJECT_DIR = SCRIPTS_DIR.parent
sys.path.insert(0, str(SCRIPTS_DIR))

from backtest_data_fetcher import (
    load_or_fetch, dt_to_ts, ts_to_dt,
    resample_to_weekly, add_technical_indicators, DATA_DIR
)
from backtest_strategy import (
    DEFAULT_STRATEGY_PARAMS, Direction, ExitReason, SignalStrength,
    run_screen2, check_exit_signals, calc_martin_add_on,
    calc_partial_close, recalc_avg_entry, TP_RATIOS,
    Position,
)
from backtest_engine import BacktestEngine


# ==================== 配置 ====================

MAILBOX_OPT_DIR = Path(os.path.expanduser(
    "~/.workbuddy/skills/boss-secretary/reports/trading/6-trading/optimization"
))
BJT = timezone(timedelta(hours=8))


# ==================== 9维参数空间 (v3.0) ====================

PARAM_NAMES = [
    "strong_score_threshold",  # θ1: 强多头阈值 [55, 75]
    "weak_score_threshold",    # θ2: 弱多头阈值 [40, 60]
    "short_score_threshold",   # θ3: 空头阈值 [25, 45]  ★方向灵敏度
    "level_spacing_k",         # θ4: 加仓间隔系数 [0.3, 1.0]
    "tp_level_1",              # θ5: TP1 ATR倍数 [1.5, 4.0]
    "tp_level_2",              # θ6: TP2 ATR倍数 [2.5, 5.0]
    "tp_level_3",              # θ7: TP3 ATR倍数 [4.0, 8.0]
    "base_pos_pct",            # θ8: 基础仓位比例% [50, 150]
    "sl_cooldown_days",        # θ9: 止损冷却天数 [0, 7] ★新增
]

BOUNDS = [
    (55.0, 75.0),     # strong_score_threshold
    (40.0, 60.0),     # weak_score_threshold
    (25.0, 45.0),     # short_score_threshold
    (0.3, 1.0),       # level_spacing_k
    (1.5, 4.0),       # tp_level_1
    (2.5, 5.0),       # tp_level_2
    (4.0, 8.0),       # tp_level_3
    (50.0, 150.0),    # base_pos_pct
    (0.0, 7.0),       # sl_cooldown_days
]

PARAM_DESCRIPTIONS = {
    "strong_score_threshold": "强多头阈值 (score>=此值→强多头, 仓位上限60%)",
    "weak_score_threshold": "弱多头阈值 (score>=此值→弱多头, 仓位上限40%)",
    "short_score_threshold": "空头阈值 (score<=此值→空头, 仓位上限60%)",
    "level_spacing_k": "加仓间隔系数 (波动率×此值=加仓间距, 最小1%)",
    "tp_level_1": "第一档止盈 ATR倍数 (平30%)",
    "tp_level_2": "第二档止盈 ATR倍数 (平30%)",
    "tp_level_3": "第三档止盈 ATR倍数 (平40%)",
    "base_pos_pct": "基础仓位比例% (信号强度缩放的基数)",
    "sl_cooldown_days": "止损冷却天数 (止损后N天内不开新仓)",
}

# 不优化但需保留在参数字典中的固定值
FIXED_PARAMS = {
    "stop_loss_pct": 20.0,  # 硬性约束
}


# ==================== 回测报告解析 ====================

@dataclass
class BacktestReportInfo:
    file_path: str
    status: str
    max_drawdown: float = 0.0
    win_rate: float = 0.0
    profit_factor: float = 0.0
    sharpe_ratio: float = 0.0
    total_return: float = 0.0
    annual_return: float = 0.0
    total_trades: int = 0
    final_equity: float = 0.0


def parse_backtest_report(report_path: str) -> Optional[BacktestReportInfo]:
    path = Path(report_path)
    if not path.exists():
        return None
    content = path.read_text(encoding="utf-8")
    info = BacktestReportInfo(file_path=str(path), status="ERROR")

    fm_match = re.match(r"^---\s*\n(.*?)\n---", content, re.DOTALL)
    if fm_match:
        for line in fm_match.group(1).split("\n"):
            line = line.strip()
            for key, attr in [
                ("backtest_status:", "status"),
                ("max_drawdown:", "max_drawdown"),
                ("win_rate:", "win_rate"),
                ("profit_factor:", "profit_factor"),
                ("sharpe_ratio:", "sharpe_ratio"),
                ("total_return:", "total_return"),
                ("annual_return:", "annual_return"),
            ]:
                if line.startswith(key):
                    try:
                        setattr(info, attr, float(line.split(":", 1)[1].strip()))
                    except (ValueError, AttributeError):
                        pass

    for pattern, attr in [
        (r"总收益率[：:]\s*([+-]?\d+\.?\d*)", "total_return"),
        (r"最大回撤[：:]\s*(\d+\.?\d*)", "max_drawdown"),
        (r"胜率[：:]\s*(\d+\.?\d*)", "win_rate"),
        (r"夏普比率[：:]\s*(-?\d+\.?\d*)", "sharpe_ratio"),
        (r"盈亏比[：:]\s*(\d+\.?\d*)", "profit_factor"),
        (r"交易次数[：:]\s*(\d+)", None),
    ]:
        m = re.search(pattern, content)
        if m:
            val = float(m.group(1)) if "." in m.group(1) else int(m.group(1))
            if attr:
                setattr(info, attr, val)
            else:
                info.total_trades = int(val)

    if info.status == "ERROR" and info.max_drawdown > 0:
        if info.max_drawdown <= 20 and info.win_rate >= 40 and info.profit_factor >= 1.5:
            info.status = "PASS"
        elif info.max_drawdown <= 20:
            info.status = "WARN"
        else:
            info.status = "FAIL"

    return info


# ==================== 优化引擎 ====================

class BayesianOptEngine:
    def __init__(self, config: dict = None):
        self.cfg = {
            "objective": "sharpe",
            "max_drawdown_limit": 20.0,
            "population_size": 15,
            "max_iterations": 15,
            "tol": 0.01,
            "seed": 42,
            "inst_id": "BTC-USDT-SWAP",
            "start_date": "2025-01-01",
            "end_date": datetime.now(BJT).strftime("%Y-%m-%d"),
            "initial_capital": 200.0,
            "quick_mode": False,
        }
        if config:
            self.cfg.update(config)
        self._daily_candles = None
        self._weekly_candles = None
        self._eval_count = 0
        self._feasible_count = 0
        self._infeasible_count = 0
        self._eval_history = []

    def _load_data(self):
        if self._daily_candles is not None:
            return self._daily_candles, self._weekly_candles

        start_date = self.cfg["start_date"]
        if self.cfg["quick_mode"]:
            start_dt = datetime.now(BJT) - timedelta(days=180)
            start_date = start_dt.strftime("%Y-%m-%d")

        start_ts = dt_to_ts(start_date)
        end_ts = dt_to_ts(self.cfg["end_date"])

        self._daily_candles = load_or_fetch(self.cfg["inst_id"], "1D", start_ts, end_ts)
        if not self._daily_candles:
            raise RuntimeError("无法获取日线数据")

        self._daily_candles = add_technical_indicators(self._daily_candles)
        self._weekly_candles = resample_to_weekly(self._daily_candles)
        self._weekly_candles = add_technical_indicators(self._weekly_candles)

        return self._daily_candles, self._weekly_candles

    def _params_array_to_dict(self, x: np.ndarray) -> dict:
        """将9维参数数组转为策略参数字典"""
        opt = {name: float(val) for name, val in zip(PARAM_NAMES, x)}
        # 合并固定参数
        opt.update(FIXED_PARAMS)
        return opt

    def _run_quick_backtest(self, opt_params: dict) -> dict:
        """
        快速回测: 使用引擎内部循环运行一次完整回测

        完全复刻 backtest_engine.run() 的逻辑, 支持分批止盈和冷却期
        """
        bt_config = {
            "inst_id": self.cfg["inst_id"],
            "start_date": self.cfg["start_date"],
            "end_date": self.cfg["end_date"],
            "initial_capital": self.cfg["initial_capital"],
        }
        if self.cfg["quick_mode"]:
            start_dt = datetime.now(BJT) - timedelta(days=180)
            bt_config["start_date"] = start_dt.strftime("%Y-%m-%d")

        engine = BacktestEngine(config=bt_config, opt_params=opt_params)
        daily, weekly = self._load_data()
        engine.daily_candles = daily
        engine.weekly_candles = weekly

        engine.reset()
        # 冷却期从opt_params读取
        if "sl_cooldown_days" in opt_params:
            engine.sl_cooldown_days = int(opt_params["sl_cooldown_days"])

        warmup = 50
        self._eval_count += 1

        for i in range(warmup, len(daily)):
            candle = daily[i]
            price = candle["close"]

            screen1 = engine._get_weekly_screen1(candle)
            screen2 = run_screen2(daily, i, screen1, engine.position, opt_params=opt_params)

            if engine.position.direction == Direction.WAIT:
                # 冷却期检查
                dt = ts_to_dt(candle["ts"])
                if engine._is_in_cooldown(dt.strftime("%Y-%m-%d")):
                    engine.stats["sl_cooldown_skip_count"] += 1
                elif screen1.direction in (Direction.LONG, Direction.SHORT):
                    engine._open_position(screen2, screen1, candle)
            else:
                # v3.0: check_exit_signals 返回3个值
                should_exit, exit_reason, tp_level = check_exit_signals(
                    engine.position, candle, screen1,
                    engine._current_equity(price), engine.peak_equity,
                    len(engine.trades)
                )

                if should_exit:
                    if tp_level >= 0:
                        # 分批止盈
                        engine._partial_close_position(candle, exit_reason, tp_level)
                    else:
                        # 全仓平仓
                        close_price = price
                        if exit_reason == ExitReason.STOP_LOSS:
                            close_price = engine.position.stop_loss_price
                        engine._close_position(candle, exit_reason, close_price)
                        if exit_reason == ExitReason.DRAWDOWN_LIMIT:
                            break
                else:
                    add_info = calc_martin_add_on(
                        engine.position, candle, engine.cash,
                        engine.equity, engine.cfg["taker_fee"]
                    )
                    if add_info:
                        dd = (engine.peak_equity - engine._current_equity(price)) / max(engine.peak_equity, 1) * 100
                        if dd < engine.cfg["warn_drawdown"]:
                            engine._add_position(add_info[0], add_info[1], candle)

            engine._record_equity(candle, price)

        # 回测结束后平仓
        if engine.position.direction != Direction.WAIT:
            engine._close_position(daily[-1], ExitReason.END_OF_BACKTEST)

        stats = self._calc_quick_stats(engine)

        self._eval_history.append({"params": {**opt_params}, **stats})

        if stats["max_drawdown"] <= self.cfg["max_drawdown_limit"]:
            self._feasible_count += 1
        else:
            self._infeasible_count += 1

        return stats

    def _objective(self, x: np.ndarray) -> float:
        """目标函数 (越小越好)"""
        opt_params = self._params_array_to_dict(x)
        stats = self._run_quick_backtest(opt_params)

        # 硬约束: max_drawdown < 20%
        if stats["max_drawdown"] > self.cfg["max_drawdown_limit"]:
            penalty = (stats["max_drawdown"] - self.cfg["max_drawdown_limit"]) * 100
            return penalty + 1000

        obj = self.cfg["objective"]
        if obj == "sharpe":
            return -stats["sharpe_ratio"]
        elif obj == "profit_factor":
            return -stats["profit_factor"]
        elif obj == "calmar":
            if stats["max_drawdown"] > 0:
                return -stats["annual_return"] / stats["max_drawdown"]
            return -999
        else:
            return -stats["sharpe_ratio"]

    def _calc_quick_stats(self, engine) -> dict:
        """从引擎状态计算统计指标"""
        init = engine.cfg["initial_capital"]
        final = engine.equity
        total_return = (final - init) / init * 100

        max_dd = 0.0
        if engine.drawdown_curve:
            max_dd = max(d["drawdown"] for d in engine.drawdown_curve)

        sharpe = 0.0
        if len(engine.equity_curve) > 1:
            returns = []
            for i in range(1, len(engine.equity_curve)):
                r = (engine.equity_curve[i]["equity"] - engine.equity_curve[i - 1]["equity"]) / max(engine.equity_curve[i - 1]["equity"], 0.01)
                returns.append(r)
            if returns:
                avg_ret = statistics.mean(returns) * 252
                std_ret = statistics.stdev(returns) * (252 ** 0.5) if len(returns) > 1 else 0.01
                sharpe = (avg_ret - 0.02) / std_ret if std_ret > 0 else 0

        total_closed = engine.stats["total_trades"]
        win_rate = (engine.stats["win_trades"] / total_closed * 100) if total_closed > 0 else 0

        # v3.0: 包含 partial_close 的盈亏统计
        wins = [t.pnl for t in engine.trades if t.action in ("close", "partial_close") and t.pnl > 0]
        losses = [t.pnl for t in engine.trades if t.action in ("close", "partial_close") and t.pnl < 0]
        avg_win = statistics.mean(wins) if wins else 0
        avg_loss = abs(statistics.mean(losses)) if losses else 1
        profit_factor = avg_win / avg_loss if avg_loss > 0 else 0

        if engine.daily_candles:
            first_dt = ts_to_dt(engine.daily_candles[0]["ts"])
            last_dt = ts_to_dt(engine.daily_candles[-1]["ts"])
            days = max((last_dt - first_dt).days, 1)
        else:
            days = 1
        annual_return = ((1 + total_return / 100) ** (365 / days) - 1) * 100

        return {
            "sharpe_ratio": round(sharpe, 4),
            "max_drawdown": round(max_dd, 2),
            "win_rate": round(win_rate, 2),
            "profit_factor": round(profit_factor, 4),
            "total_return": round(total_return, 2),
            "annual_return": round(annual_return, 2),
            "total_trades": total_closed,
            "final_equity": round(final, 2),
            "martin_complete_trades": engine.stats["martin_complete_trades"],
            "martin_incomplete_trades": engine.stats["martin_incomplete_trades"],
            "add_on_count": engine.stats["add_on_count"],
            "partial_close_count": engine.stats["partial_close_count"],
            "sl_cooldown_skip_count": engine.stats["sl_cooldown_skip_count"],
        }

    def optimize(self, report_info=None) -> dict:
        print("=" * 60)
        print("Dream Systematic Trading - 贝叶斯参数优化引擎 v3.0")
        print("  对齐 backtest_strategy v3.0 + backtest_engine v3.0")
        print("  参数空间: 9维 (含止损冷却期)")
        print("=" * 60)

        baseline_sharpe = 0.0
        baseline_stats = {}
        use_inline_baseline = False
        if report_info and report_info.sharpe_ratio != 0:
            baseline_sharpe = report_info.sharpe_ratio
            print(f"\n  基准 (回测报告):")
            print(f"    状态: {report_info.status}")
            print(f"    Sharpe: {baseline_sharpe:.4f}")
            print(f"    最大回撤: {report_info.max_drawdown:.2f}%")
            print(f"    胜率: {report_info.win_rate:.2f}%")
        else:
            # 报告无效或baseline=0, 自动跑内联基线
            use_inline_baseline = True
            print(f"\n  [基线] 运行默认参数回测 (报告无效, 自动生成基线)...")
            baseline_stats = self._run_quick_backtest(DEFAULT_STRATEGY_PARAMS)
            baseline_sharpe = baseline_stats["sharpe_ratio"]
            print(f"    Sharpe: {baseline_sharpe:.4f} | 回撤: {baseline_stats['max_drawdown']:.2f}% | 收益: {baseline_stats['total_return']:+.2f}%")

        print(f"\n  寻优配置:")
        print(f"    目标函数: {self.cfg['objective']}")
        print(f"    回撤约束: <{self.cfg['max_drawdown_limit']}%")
        print(f"    参数空间: {len(PARAM_NAMES)}维")
        for i, name in enumerate(PARAM_NAMES):
            desc = PARAM_DESCRIPTIONS.get(name, "")
            print(f"    {name}: {BOUNDS[i]} — {desc}")

        print(f"\n  开始 differential_evolution 寻优...")
        start_time = time.time()

        self._eval_count = 0
        self._feasible_count = 0
        self._infeasible_count = 0
        self._eval_history = []

        result = differential_evolution(
            self._objective,
            bounds=BOUNDS,
            maxiter=self.cfg["max_iterations"],
            popsize=self.cfg["population_size"],
            tol=self.cfg["tol"],
            seed=self.cfg["seed"],
            polish=True,
            disp=False,
            callback=self._progress_callback,
        )

        elapsed = time.time() - start_time
        print(f"\n  寻优完成! 耗时: {elapsed:.1f}秒")
        print(f"    评估次数: {self._eval_count}")
        print(f"    可行解: {self._feasible_count} | 不可行解: {self._infeasible_count}")

        best_params = self._params_array_to_dict(result.x)
        best_stats = self._run_quick_backtest(best_params)
        best_sharpe = -result.fun if result.fun < 500 else best_stats["sharpe_ratio"]

        print(f"\n  最优结果:")
        print(f"    Sharpe: {best_sharpe:.4f} (基线: {baseline_sharpe:.4f}, 提升: {(best_sharpe - baseline_sharpe) / max(abs(baseline_sharpe), 0.01) * 100:+.1f}%)")
        print(f"    最大回撤: {best_stats['max_drawdown']:.2f}%")
        print(f"    胜率: {best_stats['win_rate']:.2f}%")
        print(f"    盈亏比: {best_stats['profit_factor']:.4f}")
        print(f"    总收益率: {best_stats['total_return']:+.2f}%")
        print(f"    交易次数: {best_stats['total_trades']}")
        print(f"    冷却期跳过: {best_stats['sl_cooldown_skip_count']}次")

        sensitivity = self._sensitivity_analysis()
        confidence = self._calc_confidence_intervals()
        decision = self._make_decision(best_sharpe, baseline_sharpe, best_stats)

        print(f"\n  决策: {decision['status']}")
        print(f"    {decision['reason']}")

        return {
            "best_params": best_params,
            "best_stats": best_stats,
            "best_sharpe": best_sharpe,
            "baseline_sharpe": baseline_sharpe,
            "baseline_stats": baseline_stats,
            "improvement_pct": round((best_sharpe - baseline_sharpe) / max(abs(baseline_sharpe), 0.01) * 100, 2),
            "sensitivity": sensitivity,
            "confidence_intervals": confidence,
            "decision": decision,
            "eval_count": self._eval_count,
            "feasible_count": self._feasible_count,
            "infeasible_count": self._infeasible_count,
            "elapsed_seconds": round(elapsed, 1),
            "report_info": {
                "status": report_info.status if report_info else "N/A",
                "file": report_info.file_path if report_info else "inline",
            },
            "objective": self.cfg["objective"],
            "config": self.cfg,
        }

    def _progress_callback(self, xk, convergence):
        pct = min(convergence * 100, 100)
        print(f"    轮次 {self._eval_count:4d} | 收敛: {pct:.1f}% | "
              f"可行: {self._feasible_count} | 不可行: {self._infeasible_count}")

    def _sensitivity_analysis(self) -> List[dict]:
        if not self._eval_history:
            return []

        feasible = [h for h in self._eval_history if h["max_drawdown"] <= self.cfg["max_drawdown_limit"]]
        if len(feasible) < 5:
            return [{"param": name, "influence": "unknown", "importance": 0.0} for name in PARAM_NAMES]

        results = []
        for name in PARAM_NAMES:
            values = [h["params"][name] for h in feasible]
            scores = [-h["sharpe_ratio"] for h in feasible]

            if np.std(values) > 0 and np.std(scores) > 0:
                correlation = np.corrcoef(values, scores)[0, 1]
                importance = abs(correlation)
            else:
                importance = 0.0

            if importance > 0.5:
                influence = "高"
            elif importance > 0.2:
                influence = "中"
            elif importance > 0.05:
                influence = "低"
            else:
                influence = "极低"

            results.append({
                "param": name,
                "description": PARAM_DESCRIPTIONS.get(name, name),
                "influence": influence,
                "importance": round(importance, 4),
            })

        results.sort(key=lambda x: x["importance"], reverse=True)
        for rank, r in enumerate(results, 1):
            r["rank"] = rank

        return results

    def _calc_confidence_intervals(self) -> dict:
        feasible = [h for h in self._eval_history if h["max_drawdown"] <= self.cfg["max_drawdown_limit"]]

        if len(feasible) < 5:
            return {name: {"low": BOUNDS[i][0], "high": BOUNDS[i][1], "median": (BOUNDS[i][0] + BOUNDS[i][1]) / 2}
                    for i, name in enumerate(PARAM_NAMES)}

        result = {}
        for i, name in enumerate(PARAM_NAMES):
            values = sorted([h["params"][name] for h in feasible])
            n = len(values)
            result[name] = {
                "low": round(values[max(int(n * 0.025), 0)], 4),
                "high": round(values[min(int(n * 0.975), n - 1)], 4),
                "median": round(values[n // 2], 4),
                "mean": round(float(np.mean(values)), 4),
                "std": round(float(np.std(values)), 4),
            }

        return result

    def _make_decision(self, best_sharpe, baseline_sharpe, best_stats) -> dict:
        if self._feasible_count == 0:
            return {"status": "REJECT", "reason": "无可行解", "risk": "高"}

        # 计算改善幅度: 负Sharpe时, 绝对值减小也算改善
        if baseline_sharpe == 0:
            if best_sharpe > 0:
                improvement = 100.0  # 从0到正, 100%改善
            elif best_sharpe == 0:
                improvement = 0.0
            else:
                improvement = 0.0  # 基线为0, 无法计算
        else:
            improvement = (best_sharpe - baseline_sharpe) / abs(baseline_sharpe) * 100

        # 负Sharpe的额外考量: 绝对值越小越好
        abs_improved = abs(best_sharpe) < abs(baseline_sharpe) if baseline_sharpe != 0 else False
        total_return_positive = best_stats["total_return"] > 0
        low_drawdown = best_stats["max_drawdown"] < 10

        if improvement > 30 and best_stats["max_drawdown"] < 15:
            return {"status": "ADOPT", "reason": f"Sharpe提升{improvement:.1f}%, 回撤{best_stats['max_drawdown']:.1f}%<15%", "risk": "低"}
        elif improvement > 0 or abs_improved:
            status = "ADJUST"
            reason_parts = []
            if improvement > 0:
                reason_parts.append(f"Sharpe提升{improvement:.1f}%")
            elif abs_improved:
                reason_parts.append(f"Sharpe绝对值改善({baseline_sharpe:.3f}→{best_sharpe:.3f})")
            if total_return_positive:
                reason_parts.append(f"收益{best_stats['total_return']:+.2f}%")
            if low_drawdown:
                reason_parts.append(f"回撤{best_stats['max_drawdown']:.1f}%")
            reason = ", ".join(reason_parts) + " — 建议保守采用"
            risk = "中"
            return {"status": status, "reason": reason, "risk": risk}
        elif total_return_positive and low_drawdown:
            return {"status": "ADJUST", "reason": f"Sharpe未改善但收益{best_stats['total_return']:+.2f}%且回撤{best_stats['max_drawdown']:.1f}%", "risk": "中"}
        else:
            return {"status": "REJECT", "reason": f"优化无显著改善 (Sharpe变化{improvement:.1f}%)", "risk": "低"}


# ==================== 报告生成 ====================

def generate_optimization_report(opt_result: dict) -> str:
    now_bjt = datetime.now(BJT)
    date_str = now_bjt.strftime("%Y-%m-%d")
    iso_time = now_bjt.strftime("%Y-%m-%dT%H:%M:%S+08:00")

    d = opt_result["decision"]
    bp = opt_result["best_params"]
    bs = opt_result["best_stats"]
    sens = opt_result["sensitivity"]
    ci = opt_result["confidence_intervals"]

    lines = [
        f"---",
        f"type: bayesian_optimization",
        f"category: optimization",
        f"date: {iso_time}",
        f"source: dream-bayesian-opt",
        f"version: \"3.0\"",
        f"optimization_status: {d['status']}",
        f"total_rounds: {opt_result['eval_count']}",
        f"feasible_rounds: {opt_result['feasible_count']}",
        f"infeasible_rounds: {opt_result['infeasible_count']}",
        f"---",
        f"",
        f"# 贝叶斯参数优化报告 v3.0 {date_str}",
        f"",
        f"> 基于 backtest_strategy v3.0 (固定20%止损 + 等额加仓 + 分批止盈)",
        f"> 参数空间: 9维 (含止损冷却期)",
        f"",
        f"## 寻优概况",
        f"- 总评估次数: {opt_result['eval_count']}",
        f"- 可行解: {opt_result['feasible_count']} (max_dd<{opt_result['config']['max_drawdown_limit']}%)",
        f"- 不可行解: {opt_result['infeasible_count']}",
        f"- 基准Sharpe: {opt_result['baseline_sharpe']:.4f}",
        f"- 最优Sharpe: {opt_result['best_sharpe']:.4f}",
        f"- 预期提升: {opt_result['improvement_pct']:+.1f}%",
        f"- 目标函数: {opt_result['objective']}",
        f"- 耗时: {opt_result['elapsed_seconds']:.1f}秒",
        f"",
        f"## 推荐参数变更",
        f"| 参数 | 默认值 | 推荐值 | 变化 | 置信区间(95%) |",
        f"|------|--------|--------|------|---------------|",
    ]

    for name in PARAM_NAMES:
        current = DEFAULT_STRATEGY_PARAMS.get(name, 0)
        recommended = bp.get(name, current)
        change_pct = (recommended - current) / max(abs(current), 0.01) * 100
        ci_info = ci.get(name, {})
        ci_str = f"[{ci_info.get('low', '?')}, {ci_info.get('high', '?')}]"
        lines.append(f"| {name} | {current:.1f} | {recommended:.1f} | {change_pct:+.1f}% | {ci_str} |")

    lines.extend([
        f"| stop_loss_pct | 20.0 | **20.0** | **固定(不可优化)** | N/A |",
        f"",
        f"## 最优参数回测指标",
        f"| 指标 | 数值 |",
        f"|------|------|",
        f"| Sharpe比率 | {bs['sharpe_ratio']:.4f} |",
        f"| 最大回撤 | {bs['max_drawdown']:.2f}% |",
        f"| 胜率 | {bs['win_rate']:.2f}% |",
        f"| 盈亏比 | {bs['profit_factor']:.4f} |",
        f"| 总收益率 | {bs['total_return']:+.2f}% |",
        f"| 年化收益率 | {bs['annual_return']:+.2f}% |",
        f"| 交易次数 | {bs['total_trades']} |",
        f"| 马丁完成 | {bs['martin_complete_trades']}次 |",
        f"| 加仓次数 | {bs['add_on_count']}次 |",
        f"| 分批止盈 | {bs['partial_close_count']}次 |",
        f"| 冷却期跳过 | {bs['sl_cooldown_skip_count']}次 |",
        f"| 最终权益 | ${bs['final_equity']:.2f} |",
        f"",
        f"## 敏感性排名",
    ])

    for s in sens:
        lines.append(f"{s['rank']}. **{s['param']}** ({s['influence']}影响, 相关度={s['importance']:.3f}) — {s['description']}")

    lines.extend([
        f"",
        f"## 决策",
        f"**{d['status']}** — {d['reason']}",
        f"风险: {d['risk']}",
        f"",
        f"## 推荐参数 (JSON)",
        f"```json",
        json.dumps(bp, indent=2, ensure_ascii=False),
        f"```",
        f"",
        f"---",
        f"_Generated by dream-bayesian-opt v3.0 at {iso_time}_",
    ])

    return "\n".join(lines)


def save_report(report_md: str) -> str:
    MAILBOX_OPT_DIR.mkdir(parents=True, exist_ok=True)
    date_file = datetime.now(BJT).strftime("%Y%m%d")
    out_path = MAILBOX_OPT_DIR / f"optimization_{date_file}.md"
    out_path.write_text(report_md, encoding="utf-8")
    print(f"\n  [报告] 已保存: {out_path}")
    return str(out_path)


def find_backtest_report() -> Optional[str]:
    today = datetime.now(BJT).strftime("%Y%m%d")
    target = f"backtest_{today}.md"

    if not MAILBOX_OPT_DIR.exists():
        return None

    exact = MAILBOX_OPT_DIR / target
    if exact.exists():
        return str(exact)

    reports = sorted(MAILBOX_OPT_DIR.glob("backtest_*.md"), reverse=True)
    if reports:
        return str(reports[0])

    return None


# ==================== 主入口 ====================

def main():
    parser = argparse.ArgumentParser(description="Dream Systematic Trading - 贝叶斯参数优化引擎 v3.0")
    parser.add_argument("--report", default=None, help="回测报告路径")
    parser.add_argument("--objective", default="sharpe",
                        choices=["sharpe", "profit_factor", "calmar"], help="优化目标")
    parser.add_argument("--quick", action="store_true", help="快速模式")
    parser.add_argument("--output", default=None, help="报告输出路径")
    args = parser.parse_args()

    report_path = args.report or find_backtest_report()
    report_info = None

    if report_path:
        report_info = parse_backtest_report(report_path)
        if report_info:
            print(f"  [报告] {report_info.status} | Sharpe={report_info.sharpe_ratio} | 回撤={report_info.max_drawdown}%")
        else:
            print(f"  [报告] 解析失败!")
    else:
        print(f"  [报告] 未找到回测报告, 使用内联基线")

    if report_info and report_info.status == "FAIL":
        print(f"  回测FAIL, 跳过优化")
        return

    config = {"objective": args.objective}
    if args.quick:
        config["quick_mode"] = True
        config["population_size"] = 10
        config["max_iterations"] = 5

    engine = BayesianOptEngine(config=config)
    opt_result = engine.optimize(report_info=report_info)

    report_md = generate_optimization_report(opt_result)

    if args.output:
        out = Path(args.output)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(report_md, encoding="utf-8")
        print(f"\n  [报告] 已保存: {out}")
    else:
        save_report(report_md)

    print(f"\n  优化完成! 状态: {opt_result['decision']['status']}")
    print(f"  Sharpe: {opt_result['baseline_sharpe']:.4f} -> {opt_result['best_sharpe']:.4f}")


if __name__ == "__main__":
    main()
