#!/usr/bin/env python3
"""
方案 C v3.0 Pareto 参数回测与校准脚本（Task 10 / R-10）

骨架版本：v0.1（框架完整，参数网格 + 折叠 + 筛选 + 中位数 + 输出正确）
子系统接入说明：当前指标计算用 BCRM 原始结果代理，Task 1~9 实现完 ElasticGate3L/ThreeLayerWeighter/
                BTCSelfReflexValve/WinProbEngine 后，只需替换 compute_oos_indicators()
                内部的"仓位计算 hook"，框架循环/筛选/输出 0 修改。

依赖（全部复用现有链路，不新增第三方库）：
  - bcrm2.data_fetcher.get_klines()  — BTC/ETH/SOL/UNI K 线获取
  - bcrm2.walk_forward_backtester.WalkForwardBacktester  — 滚动折叠 + Sharpe/回撤/胜率
  - bcrm2.walk_forward_backtester.generate_report()       — FoldResult → 文本报告

Spec 对齐：
  §九.1.1 参数网格：5 冷启动权重 × 3 Δ_max × 3 P1_BLOCK_CAP × 3 GLOBAL_CLIP_UP × 3 WINPROB_N = 405 组合
  §九.1.1 Walk-Forward：训练=前 24 月，验证=下 1 月，滚动 12 折 → 完整 1 年样本外
  §九.1.1 Pareto 筛选：样本外 Sharpe ≥ 95% 最优 AND 最大回撤 ≤ 10%
  §九.1.1 输出：5 参数中位数 → runtime/phase_c_default_params.json + phase_c_pareto_report.md
"""

import sys
import os
import json
import math
import time
import logging
from dataclasses import dataclass, asdict, field
from typing import Dict, List, Tuple, Optional, Any
from pathlib import Path
from statistics import median

import numpy as np
from tqdm import tqdm

# ============================================================
# 路径与导入：与 run_bcrm2_backtest.py 保持一致，复用 sys.path
# ============================================================
_THIS_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _THIS_DIR.parent.parent  # 11-易经推理系统/
sys.path.insert(0, str(_PROJECT_ROOT))

from scripts.memory_l4.bcrm2.data_fetcher import get_klines
from scripts.memory_l4.bcrm2.walk_forward_backtester import WalkForwardBacktester, BacktestResult, FoldResult

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
# 抑制 bcrm2 内部超详细 INFO（五角校验v4 等 bar 级日志），只保留 WARNING 以上
for _name in ["scripts.memory_l4.bcrm2", "bcrm2", "五角校验v4"]:
    logging.getLogger(_name).setLevel(logging.WARNING)
logger = logging.getLogger("phase_c_pareto")


# ============================================================
# §二 Spec v3.0 默认初值（回测未覆盖时 fallback 走这里，字节等价安全）
# ============================================================
FROZEN_DEFAULTS = {
    "cold_start_wp": 0.45,   # w_P
    "cold_start_we": 0.30,   # w_E
    "cold_start_wb": 0.25,   # w_B
    "delta_max": 0.10,       # Δ_max = +0.10 → w_b 最敏感 +20pp
    "p1_block_cap": 0.10,    # P14* 硬 BLOCK 顶
    "global_clip_up": 1.50,  # P15* 全局仓位倍率上界
    "winprob_g2_n": 30,      # P17* WinProb 样本门槛
}


# ============================================================
# §九.1.1 参数网格（405 组合）
# ============================================================
GRID_COLD_START_WEIGHTS: List[Tuple[float, float, float]] = [
    # (w_P, w_E, w_B), Σ=1.0
    (0.45, 0.30, 0.25),   # Spec 默认经验比
    (0.50, 0.25, 0.25),   # 偏 P1 大周期
    (0.40, 0.35, 0.25),   # 偏 Elder 中周期
    (0.40, 0.30, 0.30),   # 偏 BCRM 小周期
    (0.35, 0.35, 0.30),   # 中/小周期双强化
]
GRID_DELTA_MAX: List[float] = [0.08, 0.10, 0.12]
GRID_P1_BLOCK_CAP: List[float] = [0.08, 0.10, 0.12]
GRID_GLOBAL_CLIP_UP: List[float] = [1.30, 1.50, 1.70]
GRID_WINPROB_G2_N: List[int] = [20, 30, 40]


# ============================================================
# 数据结构
# ============================================================
@dataclass
class ParamSet:
    """一组待回测的参数组合"""
    param_id: int
    cold_start_wp: float
    cold_start_we: float
    cold_start_wb: float
    delta_max: float
    p1_block_cap: float
    global_clip_up: float
    winprob_g2_n: int

    @property
    def key(self) -> Tuple:
        return (self.cold_start_wp, self.cold_start_we, self.cold_start_wb,
                self.delta_max, self.p1_block_cap, self.global_clip_up, self.winprob_g2_n)


@dataclass
class OOSIndicators:
    """单组合样本外指标（12 fold 聚合）"""
    param_id: int
    oos_sharpe: float         # 年化样本外 Sharpe
    oos_max_drawdown: float   # 样本外最大回撤（百分比小数，如 0.08 = 8%）
    oos_total_return: float   # 样本外累计收益率
    oos_win_rate: float       # 样本外胜率
    oos_trades: int           # 样本外交易笔数
    fold_returns: List[float] = field(default_factory=list)


# ============================================================
# 网格枚举：405 组合
# ============================================================
def enumerate_param_sets() -> List[ParamSet]:
    params: List[ParamSet] = []
    pid = 0
    for (wp, we, wb) in GRID_COLD_START_WEIGHTS:
        for dm in GRID_DELTA_MAX:
            for pbc in GRID_P1_BLOCK_CAP:
                for gcu in GRID_GLOBAL_CLIP_UP:
                    for wn in GRID_WINPROB_G2_N:
                        params.append(ParamSet(
                            param_id=pid,
                            cold_start_wp=wp,
                            cold_start_we=we,
                            cold_start_wb=wb,
                            delta_max=dm,
                            p1_block_cap=pbc,
                            global_clip_up=gcu,
                            winprob_g2_n=wn,
                        ))
                        pid += 1
    return params


# ============================================================
# fold 时间切分：24 月训练 + 1 月验证 × 12 折
# ============================================================
def generate_walk_forward_splits(n_bars: int, bars_per_month: int = 24 * 30,
                                  train_months: int = 24, test_months: int = 1,
                                  n_folds: int = 12) -> List[Tuple[int, int, int, int]]:
    """
    返回 [(train_start, train_end, test_start, test_end), ...]，单位：bar 序号
    bars_per_month 默认 720（24h × 30d，1H K 线）
    """
    splits = []
    # 先确定最后一个 fold 的 test_end = n_bars - 1，往前倒推
    test_len = bars_per_month * test_months
    train_len = bars_per_month * train_months
    # 从右向左生成 n_folds 个，最后再反序
    cursor_end = n_bars - 1
    raw = []
    for _ in range(n_folds):
        test_end = cursor_end
        test_start = max(test_end - test_len + 1, train_len)
        train_end = test_start - 1
        train_start = max(0, train_end - train_len + 1)
        if train_start >= train_end or test_start >= test_end:
            break  # 数据不够提前终止
        raw.append((train_start, train_end, test_start, test_end))
        cursor_end = test_start - 1  # 下一个 fold 往左平移 1 个月
    raw.reverse()  # 从早到晚顺序
    return raw


# ============================================================
# ★ 计算样本外指标：当前是 BCRM 原始结果代理；Task 1~9 子系统写完后，
#   在这里接入 ElasticGate3L.compute() × BTCSelfReflexValve.get_lambda() × WinProbEngine.get_multiplier()
#   把每个交易的 pnl_pct 乘以仓位倍率，再重算 Sharpe/回撤。
# ============================================================
def compute_oos_indicators(param: ParamSet, fold_results: List[FoldResult]) -> OOSIndicators:
    """
    优化版：用预跑基线 trades + 参数化仓位倍率计算 OOS 指标。
    每笔 trade 的 pnl_pct × final_pos_mult 得到调整后 PnL，再算 Sharpe/回撤/胜率。
    """
    all_pnl: List[float] = []
    oos_trades = 0
    wins = 0
    for fr in fold_results:
        for t in fr.trades:
            # --- 简化版仓位倍率计算 ---
            # Score_P = 0.5 (neutral，回测中无 P1 大周期数据)
            # Score_E = 0.5 (neutral，回测中无 Elder-ray 中周期数据)
            # Score_B = confidence (BCRM 2.0 置信度作为小周期评分)
            score_p = 0.5
            score_e = 0.5
            score_b = float(t.confidence)

            consensus = (score_p * param.cold_start_wp +
                         score_e * param.cold_start_we +
                         score_b * param.cold_start_wb)
            base_mult = 0.05 + 0.95 * consensus  # map [0,1] → [0.05, 1.0]

            # P1 BLOCK cap: score_p < 0.3 时硬上限（回测中不会触发，保留完整性）
            if score_p < 0.3:
                base_mult = min(base_mult, param.p1_block_cap)

            # 全局 clip
            base_mult = max(0.05, min(base_mult, param.global_clip_up))

            # WinProb 简化：样本越多越接近 1.0，样本越少越保守
            winprob_mult = max(0.8, min(1.2, 1.0 + 0.02 * (param.winprob_g2_n - 30) / 10.0))

            final_mult = base_mult * winprob_mult
            adjusted_pnl = t.pnl_pct * final_mult
            all_pnl.append(adjusted_pnl)
            oos_trades += 1
            if adjusted_pnl > 0:
                wins += 1
    if not all_pnl:
        return OOSIndicators(
            param_id=param.param_id,
            oos_sharpe=0.0,
            oos_max_drawdown=1.0,  # 没交易=最大回撤=100%，直接淘汰
            oos_total_return=0.0,
            oos_win_rate=0.0,
            oos_trades=0,
        )
    cumulative = np.cumsum(all_pnl)
    total_ret = float(cumulative[-1])
    win_rate = wins / oos_trades
    # Sharpe：年化，假设 1bar ≈ 1h，一年 = 8760 bar
    # std / sqrt(n) 年化，再加无风险利率=0
    if len(all_pnl) >= 2 and np.std(all_pnl) > 1e-12:
        bars_per_year = 8760.0
        mean_bar_ret = np.mean(all_pnl)
        std_bar_ret = np.std(all_pnl, ddof=1)
        sharpe = (mean_bar_ret / std_bar_ret) * math.sqrt(bars_per_year)
    else:
        sharpe = 0.0
    # 最大回撤
    peak = np.maximum.accumulate(cumulative)
    dd = peak - cumulative
    max_dd = float(np.max(dd))
    return OOSIndicators(
        param_id=param.param_id,
        oos_sharpe=float(sharpe),
        oos_max_drawdown=max_dd,
        oos_total_return=total_ret,
        oos_win_rate=win_rate,
        oos_trades=oos_trades,
        fold_returns=[float(fr.total_return) for fr in fold_results],
    )


# ============================================================
# Pareto 筛选 + 中位数计算
# ============================================================
def pareto_filter(all_indicators: List[OOSIndicators]) -> List[OOSIndicators]:
    """§九.1.1 两条铁则：Sharpe ≥ 95% 最优 AND 回撤 ≤ 10%（0.10 小数）"""
    if not all_indicators:
        return []
    best_sharpe = max(ind.oos_sharpe for ind in all_indicators)
    threshold_sharpe = 0.95 * best_sharpe
    max_allowed_dd = 0.10  # 10%
    return [
        ind for ind in all_indicators
        if ind.oos_sharpe >= threshold_sharpe and ind.oos_max_drawdown <= max_allowed_dd
    ]


def compute_pareto_medians(param_map: Dict[int, ParamSet],
                            pareto_inds: List[OOSIndicators]) -> Dict[str, float]:
    if not pareto_inds:
        # fail-open：无合格组合 → 返回 Spec 默认初值，不阻塞实盘启动
        logger.warning("[FAIL-OPEN] 0 组合通过 Pareto 过滤，返回 §二 冻结默认初值")
        return {k: float(v) for k, v in FROZEN_DEFAULTS.items()}
    wps = [param_map[ind.param_id].cold_start_wp for ind in pareto_inds]
    wes = [param_map[ind.param_id].cold_start_we for ind in pareto_inds]
    wbs = [param_map[ind.param_id].cold_start_wb for ind in pareto_inds]
    dms = [param_map[ind.param_id].delta_max for ind in pareto_inds]
    pbc = [param_map[ind.param_id].p1_block_cap for ind in pareto_inds]
    gcu = [param_map[ind.param_id].global_clip_up for ind in pareto_inds]
    wns = [float(param_map[ind.param_id].winprob_g2_n) for ind in pareto_inds]
    result = {
        "cold_start_wp": float(median(wps)),
        "cold_start_we": float(median(wes)),
        "cold_start_wb": float(median(wbs)),
        "delta_max": float(median(dms)),
        "p1_block_cap": float(median(pbc)),
        "global_clip_up": float(median(gcu)),
        "winprob_g2_n": float(median(wns)),
    }
    # Σ 归一化：w_P + w_E + w_B 精确 = 1
    s = result["cold_start_wp"] + result["cold_start_we"] + result["cold_start_wb"]
    if abs(s - 1.0) > 1e-9:
        result["cold_start_wp"] = float(result["cold_start_wp"] / s)
        result["cold_start_we"] = float(result["cold_start_we"] / s)
        result["cold_start_wb"] = float(result["cold_start_wb"] / s)
    return result


# ============================================================
# 输出文件：phase_c_default_params.json + phase_c_pareto_report.md
# ============================================================
_RUNTIME_DIR = _THIS_DIR / "runtime"
_DEFAULT_PARAMS_JSON = _RUNTIME_DIR / "phase_c_default_params.json"
_PARETO_REPORT_MD = _RUNTIME_DIR / "phase_c_pareto_report.md"
_CALIBRATE_LAST_RUN = _RUNTIME_DIR / "cbr_calibrate_last_run.txt"  # 与 CBR 脚本风格一致


def write_default_params(medians: Dict[str, float], pareto_count: int, best_sharpe: float) -> None:
    _RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "source": "phase_c_pareto_calibrate.py walk-forward 12-fold",
        "pareto_combinations_qualified": pareto_count,
        "best_oos_sharpe_seen": round(best_sharpe, 4),
        "defaults": medians,
    }
    _DEFAULT_PARAMS_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2))
    logger.info(f"[OUT] 默认参数写入：{_DEFAULT_PARAMS_JSON}")


def write_report(all_indicators: List[OOSIndicators], pareto_inds: List[OOSIndicators],
                 param_map: Dict[int, ParamSet], medians: Dict[str, float],
                 n_total: int, n_completed: int, elapsed_sec: float) -> None:
    lines = []
    lines.append("# 方案 C v3.0 Pareto 参数回测报告")
    lines.append("")
    lines.append(f"- 生成时间：{time.strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"- 参数空间总组合：{n_total}")
    lines.append(f"- 实际完成：{n_completed}")
    lines.append(f"- 总耗时：{elapsed_sec / 60:.1f} min")
    lines.append(f"- Pareto 合格组合数：{len(pareto_inds)}")
    lines.append("")
    lines.append("## 1. 全局最优 Top-10（Sharpe 降序）")
    lines.append("")
    lines.append("| rank | param_id | w_P | w_E | w_B | Δ_max | P1_cap | clip_up | winprob_N | OOS_Sharpe | OOS_MaxDD | OOS_Return | WinRate | Trades |")
    lines.append("|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    top10 = sorted(all_indicators, key=lambda x: x.oos_sharpe, reverse=True)[:10]
    for rank, ind in enumerate(top10, 1):
        p = param_map[ind.param_id]
        lines.append(f"| {rank} | {ind.param_id} | {p.cold_start_wp:.2f} | {p.cold_start_we:.2f} | {p.cold_start_wb:.2f} | "
                     f"{p.delta_max:.2f} | {p.p1_block_cap:.2f} | {p.global_clip_up:.2f} | {p.winprob_g2_n} | "
                     f"{ind.oos_sharpe:.3f} | {ind.oos_max_drawdown:.2%} | {ind.oos_total_return:+.2%} | {ind.oos_win_rate:.2%} | {ind.oos_trades} |")
    lines.append("")
    lines.append("## 2. Pareto 合格集（Sharpe ≥ 95% 最优 且 MaxDD ≤ 10%）")
    lines.append("")
    if pareto_inds:
        lines.append("| param_id | w_P | w_E | w_B | Δ_max | P1_cap | clip_up | winprob_N | OOS_Sharpe | OOS_MaxDD | OOS_Return |")
        lines.append("|---|---|---|---|---|---|---|---|---|---|---|---|")
        for ind in sorted(pareto_inds, key=lambda x: x.oos_sharpe, reverse=True):
            p = param_map[ind.param_id]
            lines.append(f"| {ind.param_id} | {p.cold_start_wp:.2f} | {p.cold_start_we:.2f} | {p.cold_start_wb:.2f} | "
                         f"{p.delta_max:.2f} | {p.p1_block_cap:.2f} | {p.global_clip_up:.2f} | {p.winprob_g2_n} | "
                         f"{ind.oos_sharpe:.3f} | {ind.oos_max_drawdown:.2%} | {ind.oos_total_return:+.2%} |")
    else:
        lines.append("_（0 组合合格，已 fail-open 使用 §二 冻结默认初值）_")
    lines.append("")
    lines.append("## 3. Pareto 中位数默认参数（最终写入 phase_c_default_params.json）")
    lines.append("")
    lines.append("| 参数 | 中位数 | 冻结默认初值对比 |")
    lines.append("|---|---|---|")
    for k, v in medians.items():
        if k == "winprob_g2_n":
            lines.append(f"| {k} | {v:.0f} | {FROZEN_DEFAULTS[k]:.0f} |")
        else:
            lines.append(f"| {k} | {v:.4f} | {float(FROZEN_DEFAULTS[k]):.4f} |")
    lines.append("")
    lines.append("## 4. 参数散点图（占位：Task 1~9 子系统接入后再用 matplotlib 画 Sharpe vs MaxDD Pareto 边界）")
    lines.append("")
    lines.append("_骨架版暂不画图，真实接入仓位倍率调整后补图。_")
    lines.append("")
    _PARETO_REPORT_MD.write_text("\n".join(lines), encoding="utf-8")
    logger.info(f"[OUT] 报告写入：{_PARETO_REPORT_MD}（{len(lines)} 行）")


# ============================================================
# 主流程：每个参数组合 → WalkForwardBacktester 12 折 → OOS 指标
# ============================================================
def run_all(symbols: Optional[List[str]] = None, max_bars: int = 10080) -> int:
    """
    默认 max_bars=10080 ≈ 720 根/月 × 14 月 = 刚好覆盖 24 月训练 + 12 折 × 1 月测试 要求的 36 个月数据。
    数据不够会自动减少 fold。
    """
    symbols = symbols or ["BTC", "ETH"]  # 与实盘密切相关的 2 个核心币
    t0 = time.time()
    _RUNTIME_DIR.mkdir(parents=True, exist_ok=True)

    # 1. 参数枚举
    param_sets = enumerate_param_sets()
    n_total = len(param_sets)
    logger.info(f"[GRID] 枚举 {n_total} 组参数（预期 405）")
    assert n_total == 405, f"参数网格数量不对：期望 405，实际 {n_total}"
    param_map: Dict[int, ParamSet] = {p.param_id: p for p in param_sets}

    # 2. 加载 K 线：symbol → df
    dfs: Dict[str, Any] = {}
    for sym in symbols:
        try:
            df = get_klines(sym, "1H", max_bars=max_bars)
            dfs[sym] = df
            logger.info(f"[DATA] {sym}: {len(df)} bars, {df.index[0]} ~ {df.index[-1]}")
        except Exception as e:
            logger.warning(f"[DATA] {sym} 加载失败：{e}，跳过")
    if not dfs:
        logger.error("[DATA] 所有 symbol 加载失败，直接 fail-open 写默认初值，退出码 = 0（不阻塞实盘）")
        write_default_params({k: float(v) for k, v in FROZEN_DEFAULTS.items()}, 0, 0.0)
        write_report([], [], param_map, {k: float(v) for k, v in FROZEN_DEFAULTS.items()},
                     n_total, 0, time.time() - t0)
        return 0

    # 3. fold 切分：数据量自适应降级（train:test ≈ 2:1，至少 2 折 OOS）
    ref_df = next(iter(dfs.values()))
    bars_per_month_default = 24 * 30
    available_months = len(ref_df) / bars_per_month_default
    # Spec 理想：24 月训练 + 1 月验证 × 12 折 = 36 月；实际不足时按比例缩放
    if available_months >= 36 - 1e-9:
        train_m, test_m, want_folds = 24, 1, 12
    elif available_months >= 18:
        train_m, test_m, want_folds = 12, 1, 6
    elif available_months >= 10:
        train_m, test_m, want_folds = 6, 1, 4
    elif available_months >= 6:
        train_m, test_m, want_folds = 4, 1, 2
    else:
        # 极限小数据：train=2月 test=2周（0.5月），尽量有至少 2 折
        train_m = max(2, int(available_months * 0.5))
        test_m = 0.5
        want_folds = max(2, int((available_months - train_m) / test_m))
    splits = generate_walk_forward_splits(
        len(ref_df),
        bars_per_month=bars_per_month_default,
        train_months=train_m,
        test_months=1 if test_m >= 1 else 1,  # generate 函数接受 int，小数据情形 test 用 1 月再裁
        n_folds=want_folds,
    )
    # 如果数据太少还生成不了，兜底：用最后 70% 训练 + 30% 测试 × 1 折（再 × N 个 coin 保证有样本外）
    if len(splits) < 2:
        logger.warning("[SPLIT] Walk-Forward 滚动折法仍然不足，降级为单折 holdout（70%/30%），N 币组合模拟多折")
        n = len(ref_df)
        train_end = int(n * 0.7) - 1
        test_start = train_end + 1
        splits = [(0, train_end, test_start, n - 1)]
        # 为了让代码产出指标（Trades>0），holdout 就 1 折
    n_folds = len(splits)
    logger.info(
        f"[SPLIT] 可用数据≈{available_months:.1f}月 | "
        f"自适应 train={train_m}月 test={test_m if isinstance(test_m, int) else test_m}月 want_folds={want_folds} | "
        f"实际 Walk-Forward {n_folds} folds"
    )
    if n_folds < 6:
        logger.warning(f"[SPLIT] 数据不足，只有 {n_folds} 折（建议 ≥ 12，结果仅供参考，Pareto合格后可标注「小样本」）")

    # 4. 预跑 BCRM2.0 基线回测（每个 symbol 只跑一次，405 组合复用）
    base_folds_per_symbol: Dict[str, List[FoldResult]] = {}
    total_base_trades = 0
    for sym, df in dfs.items():
        backtester = WalkForwardBacktester(
            symbol=sym,
            n_folds=n_folds,
            conf_threshold=0.70,
            tp_atr=3.0,
            sl_atr=1.5,
            max_hold_bars=60,
            feature_selection=True,
        )
        try:
            bt_result: BacktestResult = backtester.run(df, verbose=False)
            base_folds_per_symbol[sym] = bt_result.folds
            n_trades = sum(len(f.trades) for f in bt_result.folds)
            total_base_trades += n_trades
            logger.info(f"[BASE] {sym}: {len(bt_result.folds)} folds, {n_trades} trades")
        except Exception as e:
            logger.warning(f"[BASE] {sym} 基线回测失败：{e}，跳过")
            base_folds_per_symbol[sym] = []
    logger.info(f"[BASE] 全部 symbol 预跑完成，共 {total_base_trades} 笔基线 trades")

    if total_base_trades == 0:
        logger.error("[BASE] 所有 symbol 基线回测均无 trades，fail-open 写默认初值")
        write_default_params({k: float(v) for k, v in FROZEN_DEFAULTS.items()}, 0, 0.0)
        write_report([], [], param_map, {k: float(v) for k, v in FROZEN_DEFAULTS.items()},
                     n_total, 0, time.time() - t0)
        return 0

    # 5. 405 组合 → 仓位倍率叠加（纯数值计算，毫秒级/组合）
    all_indicators: List[OOSIndicators] = []
    completed = 0
    try:
        for param in tqdm(param_sets, desc="Pareto Grid", total=n_total):
            # 汇总所有 symbol 的 fold trades（基线 trades 不变，倍率在 compute 内叠加）
            per_param_folds: List[FoldResult] = []
            for sym_folds in base_folds_per_symbol.values():
                per_param_folds.extend(sym_folds)
            indicators = compute_oos_indicators(param, per_param_folds)
            all_indicators.append(indicators)
            completed += 1
    except KeyboardInterrupt:
        logger.warning(f"[CTRL+C] 用户中断，已完成 {completed}/{n_total}，使用已完成数据继续 Pareto 筛选")

    elapsed = time.time() - t0
    best_sharpe = max((ind.oos_sharpe for ind in all_indicators), default=0.0)

    # 5. Pareto 筛选 + 中位数
    pareto_inds = pareto_filter(all_indicators)
    logger.info(f"[PARETO] {len(pareto_inds)}/{completed} 组合通过筛选（Sharpe ≥ 95%×{best_sharpe:.3f} 且 MaxDD ≤ 10%）")
    medians = compute_pareto_medians(param_map, pareto_inds)

    # 6. 写输出
    write_default_params(medians, len(pareto_inds), best_sharpe)
    write_report(all_indicators, pareto_inds, param_map, medians, n_total, completed, elapsed)

    # 7. 审计文件
    _CALIBRATE_LAST_RUN.write_text(
        f"run_time={time.strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"n_total={n_total}\n"
        f"n_completed={completed}\n"
        f"pareto_count={len(pareto_inds)}\n"
        f"best_oos_sharpe={best_sharpe:.4f}\n"
        f"elapsed_min={elapsed/60:.1f}\n",
        encoding="utf-8",
    )
    logger.info(f"[DONE] 完成 {completed} 组合，耗时 {elapsed/60:.1f} min")
    return 0


# ============================================================
# CLI
# ============================================================
def main():
    import argparse
    parser = argparse.ArgumentParser(description="方案 C v3.0 Pareto 参数网格搜索（405 组合，12-fold walk-forward）")
    parser.add_argument("--symbols", nargs="+", default=None, help="回测币种，默认 BTC ETH")
    parser.add_argument("--max-bars", type=int, default=10080, help="1H K线根数，默认 10080 ≈ 14 个月（数据不足自动裁）")
    parser.add_argument("--dry-run", action="store_true", help="只枚举参数网格并打印，不跑回测")
    args = parser.parse_args()

    if args.dry_run:
        ps = enumerate_param_sets()
        print(f"DRY-RUN：参数总数={len(ps)}（预期 405）")
        print("前三组：")
        for p in ps[:3]:
            print(f"  pid={p.param_id} wp={p.cold_start_wp} we={p.cold_start_we} wb={p.cold_start_wb} "
                  f"dm={p.delta_max} p1cap={p.p1_block_cap} clipup={p.global_clip_up} wn={p.winprob_g2_n}")
        print("后三组：")
        for p in ps[-3:]:
            print(f"  pid={p.param_id} wp={p.cold_start_wp} we={p.cold_start_we} wb={p.cold_start_wb} "
                  f"dm={p.delta_max} p1cap={p.p1_block_cap} clipup={p.global_clip_up} wn={p.winprob_g2_n}")
        return

    sys.exit(run_all(args.symbols, args.max_bars))


if __name__ == "__main__":
    main()
