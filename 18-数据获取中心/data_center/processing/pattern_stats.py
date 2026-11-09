"""三层防线统计原语 — SPEC-D1 §2.5 + docs/PATTERN-STATS-PREREG-v0.1（冻结口径）。

复用声明（跨域不互相 import，vendored + parity 校验）：
  - holm_adjust：算法对齐 23-四层闭环 framework_comparison.holm_bonferroni
  - cscv_pbo / deflated_sharpe：算法对齐 45-评测系统 backtest.pbo_cscv /
    deflated_sharpe_ratio（Bailey & López de Prado）
  - spa_pvalues：仓内无既有实现，按 Hansen(2005) SPA / White(2000) RC 新建

约定：
  - cscv_pbo 数据不足返回 None（insufficient_data，合法结果非错误）
  - deflated_sharpe 参数非法抛 ValueError（调用方 builder 兜底 FAIL-OPEN）
  - 其余函数对垃圾输入保守返回（1.0 / {} / 0.0），不抛
"""

from __future__ import annotations

import itertools
import logging
import math
from math import e, inf, sqrt
from statistics import NormalDist
from typing import Any

import numpy as np
from scipy import stats as _sstats

logger = logging.getLogger("data_center.processing.pattern_stats")

EULER_GAMMA = 0.577_215_664_9


# ── 第一层：Holm 批内校正 ─────────────────────────────────


def holm_adjust(p_values: Any) -> dict:
    """Holm-Bonferroni：升序第 i 个（1-indexed）校正 p = min(1, p*(m-i+1))，单调约束。"""
    if not isinstance(p_values, dict) or not p_values:
        return {}
    m = len(p_values)
    out: dict[str, float] = {}
    prev = 0.0
    for i, (key, p) in enumerate(sorted(p_values.items(), key=lambda x: x[1]), 1):
        try:
            adj = min(1.0, float(p) * (m - i + 1))
        except (TypeError, ValueError):
            adj = 1.0
        adj = max(adj, prev)
        out[key] = adj
        prev = adj
    return out


# ── 第二层：CSCV / PBO ────────────────────────────────────


def _sharpe(values: list[float]) -> float:
    n = len(values)
    if n < 2:
        return 0.0
    mean = sum(values) / n
    var = sum((v - mean) ** 2 for v in values) / (n - 1)
    if var <= 0:
        if mean > 0:
            return inf
        return -inf if mean < 0 else 0.0
    return mean / sqrt(var)


def _auto_s(min_len: int) -> int | None:
    """冻结口径：S = min(16, ⌊min_len/2⌋ 向下取偶)，下限 4。"""
    s = min(16, min_len // 2)
    s -= s % 2
    return s if s >= 4 else None


def cscv_pbo(series_list: Any, S: int | None = None) -> float | None:
    """CSCV 计算 PBO；不可算（<3 列 / 长度不齐 / 块<2）返回 None。

    轴口径：调用方保证各序列等长且按事件序号对齐（本模块不假设日历轴）。
    """
    try:
        if not isinstance(series_list, (list, tuple)) or len(series_list) < 3:
            return None
        series = [list(map(float, s)) for s in series_list]
        lengths = {len(s) for s in series}
        if len(lengths) != 1:
            return None
        n = lengths.pop()
        s_blocks = S if S is not None else _auto_s(n)
        if s_blocks is None or s_blocks < 2 or s_blocks % 2 != 0:
            return None
        block = n // s_blocks
        if block < 2:
            return None
        used = block * s_blocks
        series = [s[:used] for s in series]  # 尾部截断（冻结口径）

        blocks = [list(range(i * block, (i + 1) * block)) for i in range(s_blocks)]
        overfit = 0
        total = 0
        for is_blocks in itertools.combinations(range(s_blocks), s_blocks // 2):
            is_idx = [i for b in is_blocks for i in blocks[b]]
            oos_idx = [i for b in range(s_blocks) if b not in is_blocks for i in blocks[b]]
            is_scores = [_sharpe([s[i] for i in is_idx]) for s in series]
            best = max(range(len(is_scores)), key=lambda j: is_scores[j])
            oos_scores = [_sharpe([s[i] for i in oos_idx]) for s in series]
            rank = (
                sum(1 for sc in oos_scores if sc < oos_scores[best])
                + 0.5 * sum(1 for sc in oos_scores if sc == oos_scores[best])
            ) / len(oos_scores)
            if rank <= 0.5:
                overfit += 1
            total += 1
        return overfit / total if total else None
    except Exception as e:  # noqa: BLE003
        logger.warning("[FAIL-OPEN] cscv_pbo 异常 %s: %s", type(e).__name__, str(e)[:200])
        return None


# ── 第三层 a：SPA（Hansen 2005 重定中心 bootstrap）─────────


def _t_stats(mat: np.ndarray, mu0: float) -> np.ndarray:
    """每行 t = (mean-mu0)/(sd/√n)；sd=0 退化：mean>mu0→+inf, <mu0→-inf, ==→0。"""
    n = mat.shape[1]
    mean = mat.mean(axis=1)
    sd = mat.std(axis=1, ddof=1) if n > 1 else np.zeros(mat.shape[0])
    with np.errstate(divide="ignore", invalid="ignore"):
        t = np.where(sd > 0, (mean - mu0) / (sd / sqrt(n)), 0.0)
    degenerate = (sd == 0) | n <= 1
    if degenerate.any():
        t = np.where(degenerate & (mean > mu0), inf, t)
        t = np.where(degenerate & (mean < mu0), -inf, t)
    return t


def spa_pvalues(cells: Any, mu0: float, n_boot: int = 5000, seed: int = 42) -> dict:
    """SPA per-cell p：p_k = fraction(max_j t_j^b ≥ t_k^obs)，重定中心强加零假设。"""
    try:
        if not isinstance(cells, dict) or not cells:
            return {}
        keys = [k for k, v in cells.items() if isinstance(v, (list, tuple)) and len(v) >= 1]
        if not keys:
            return {}
        try:
            mu0 = float(mu0)
        except (TypeError, ValueError):
            mu0 = 0.0
        rng = np.random.default_rng(seed)
        obs = {k: np.asarray([float(x) for x in cells[k]], dtype=float) for k in keys}
        t_obs = {k: _t_stats(v[None, :], mu0)[0] for k, v in obs.items()}
        # 重定中心：减去自身均值 + mu0 → 零假设下分布
        centered = {k: v - v.mean() + mu0 for k, v in obs.items()}
        max_b = np.full(int(n_boot), -inf)
        for k in keys:
            c = centered[k]
            idx = rng.integers(0, len(c), size=(int(n_boot), len(c)))
            tb = _t_stats(c[idx], mu0)  # (n_boot,)  —— 每行一个 bootstrap 样本
            max_b = np.maximum(max_b, tb)
        out = {}
        for k in keys:
            to = t_obs[k]
            if to == inf:
                out[k] = 0.0
            elif to == -inf:
                out[k] = 1.0
            else:
                out[k] = float(np.mean(max_b >= to))
        return out
    except Exception as e:  # noqa: BLE003
        logger.warning("[FAIL-OPEN] spa_pvalues 异常 %s: %s", type(e).__name__, str(e)[:200])
        return {}


# ── 第三层 b：DSR（佐证，不作门禁）─────────────────────────


def _psr(sharpe: float, n_obs: int, skew: float, kurtosis: float, benchmark: float) -> float:
    if n_obs < 2:
        raise ValueError(f"n_observations 必须 ≥ 2，收到 {n_obs}")
    var = 1 - skew * sharpe + (kurtosis - 1) / 4 * sharpe**2
    if var <= 0:
        raise ValueError("PSR 方差项非正")
    return NormalDist().cdf((sharpe - benchmark) * sqrt(n_obs - 1) / sqrt(var))


def _expected_max_sharpe(n_trials: int, sr_std: float) -> float:
    if n_trials < 1:
        raise ValueError(f"n_trials 必须 ≥ 1，收到 {n_trials}")
    if sr_std <= 0:
        raise ValueError("sr_std 必须 > 0")
    nd = NormalDist()
    return sr_std * (
        (1 - EULER_GAMMA) * nd.inv_cdf(1 - 1 / n_trials)
        + EULER_GAMMA * nd.inv_cdf(1 - 1 / (n_trials * e))
    )


def deflated_sharpe(
    sharpe: float,
    n_observations: int,
    n_trials: int,
    skew: float = 0.0,
    kurtosis: float = 3.0,
    sr_std: float = 1.0,
) -> float:
    """DSR：以 E[max SR] 为基准的 PSR；n_trials=1 退化为 SR*=0。"""
    benchmark = 0.0 if n_trials <= 1 else _expected_max_sharpe(n_trials, sr_std)
    return _psr(sharpe, n_observations, skew, kurtosis, benchmark)


# ── 每 cell 原始 p 值（Holm 输入）──────────────────────────


def one_sample_pvalue(values: Any, mu0: float = 0.0) -> float:
    """单样本双侧 t 检验 H0: mean = mu0。退化口径见预注册 §1。FAIL-OPEN → 1.0。"""
    try:
        vals = [float(v) for v in values] if isinstance(values, (list, tuple)) else []
        n = len(vals)
        if n < 2:
            return 1.0
        mean = sum(vals) / n
        var = sum((v - mean) ** 2 for v in vals) / (n - 1)
        if var <= 0:
            return 1.0 if mean == mu0 else 0.0
        res = _sstats.ttest_1samp(vals, mu0)
        p = float(res.pvalue)
        return p if math.isfinite(p) else 1.0
    except Exception as e:  # noqa: BLE003
        logger.warning("[FAIL-OPEN] one_sample_pvalue 异常 %s: %s", type(e).__name__, str(e)[:200])
        return 1.0
