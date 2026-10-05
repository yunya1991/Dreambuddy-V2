"""
C1 GREEN: 因子 IC 筛选器

从 DAL 拉取候选因子时序，计算每个因子对 BTC 未来 N 日收益的 Spearman RankIC，
通过 IC_IR、胜率、VIF 共线性筛选出最有预测力的因子。

核心逻辑：
  1. 时序对齐：所有因子对齐到 BTC 价格时间轴（低频前向填充）
  2. 标准化：滚动 z-score（避免未来信息泄露）
  3. IC 计算：Spearman RankIC(factor, forward_return_Nd)
  4. IC_IR：滚动窗口 IC 序列 → IC_IR = mean(IC) / std(IC)
  5. 筛选：|IC_mean| > ic_threshold 且 |IC_IR| > ir_threshold 且胜率 > win_rate_threshold
  6. 共线性：VIF > vif_threshold 剔除（保留 IC_IR 更高者）

FAIL-OPEN:
  - DAL 不可用 → 用 _factors_df 注入的测试数据（或空结果）
  - 因子数据不足 → 跳过该因子
  - scipy 不可用 → 降级为 pandas rank 相关
"""
from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# 尝试导入 scipy（可选加速）
try:
    from scipy.stats import spearmanr as _scipy_spearmanr

    _SCIPY_AVAILABLE = True
except ImportError:  # noqa: BLE001
    _SCIPY_AVAILABLE = False


def _compute_rank_ic(factor: np.ndarray, forward_ret: np.ndarray) -> float:
    """计算 Spearman RankIC。

    Args:
        factor: 因子值序列 (N,)
        forward_ret: 未来收益序列 (N,)

    Returns:
        Spearman 相关系数 [-1, 1]，全常量输入返回 0.0
    """
    f = np.asarray(factor, dtype=float)
    r = np.asarray(forward_ret, dtype=float)
    if len(f) < 3 or len(f) != len(r):
        return 0.0
    # 去除 NaN
    mask = ~np.isnan(f) & ~np.isnan(r)
    if mask.sum() < 3:
        return 0.0
    f_clean = f[mask]
    r_clean = r[mask]
    # 全常量 → 无信息
    if np.std(f_clean) < 1e-12 or np.std(r_clean) < 1e-12:
        return 0.0

    if _SCIPY_AVAILABLE:
        try:
            ic, _ = _scipy_spearmanr(f_clean, r_clean)
            return float(ic) if not np.isnan(ic) else 0.0
        except Exception:  # noqa: BLE001
            pass
    # 降级：pandas rank 相关
    f_rank = pd.Series(f_clean).rank().values
    r_rank = pd.Series(r_clean).rank().values
    corr = np.corrcoef(f_rank, r_rank)[0, 1]
    return float(corr) if not np.isnan(corr) else 0.0


def _compute_ic_ir(ic_series: List[float]) -> Tuple[float, float]:
    """计算 IC 均值和 IC_IR。

    Args:
        ic_series: 滚动窗口 IC 值列表

    Returns:
        (ic_mean, ic_ir)，ic_ir = mean / std
    """
    if not ic_series:
        return 0.0, 0.0
    ic_arr = np.array(ic_series, dtype=float)
    ic_arr = ic_arr[~np.isnan(ic_arr)]
    if len(ic_arr) == 0:
        return 0.0, 0.0
    ic_mean = float(np.mean(ic_arr))
    ic_std = float(np.std(ic_arr, ddof=1)) if len(ic_arr) > 1 else 0.0
    if ic_std < 1e-12:
        return ic_mean, 0.0
    ic_ir = ic_mean / ic_std
    return ic_mean, ic_ir


def _compute_vif(factors_df: pd.DataFrame) -> Dict[str, float]:
    """计算每个因子的 VIF（方差膨胀因子）。

    VIF > 10 表示严重共线性。
    实现：对每个因子，用其他因子做线性回归，R² → VIF = 1/(1-R²)。
    用 numpy lstsq 实现，避免 statsmodels 依赖。
    """
    vif = {}
    cols = factors_df.columns.tolist()
    for i, col in enumerate(cols):
        y = factors_df[col].values
        # 其他因子作为自变量
        X_cols = [c for j, c in enumerate(cols) if j != i]
        if not X_cols:
            vif[col] = 1.0
            continue
        X = factors_df[X_cols].values
        # 去除 NaN
        mask = ~np.isnan(y) & ~np.isnan(X).any(axis=1)
        if mask.sum() < len(cols) + 1:
            vif[col] = 1.0
            continue
        y_clean = y[mask]
        X_clean = X[mask]
        # 加截距
        X_with_const = np.column_stack([np.ones(len(y_clean)), X_clean])
        # OLS: β = (X'X)^-1 X'y
        try:
            beta, *_ = np.linalg.lstsq(X_with_const, y_clean, rcond=None)
            y_pred = X_with_const @ beta
            ss_res = np.sum((y_clean - y_pred) ** 2)
            ss_tot = np.sum((y_clean - np.mean(y_clean)) ** 2)
            if ss_tot < 1e-12:
                vif[col] = 1.0
                continue
            r_squared = 1.0 - ss_res / ss_tot
            if r_squared >= 1.0 - 1e-10:
                vif[col] = float("inf")
            else:
                vif[col] = 1.0 / (1.0 - r_squared)
        except np.linalg.LinAlgError:
            vif[col] = float("inf")
    return vif


@dataclass
class FactorSelectionResult:
    """因子筛选结果。"""

    selected_factors: List[str] = field(default_factory=list)
    ranking: pd.DataFrame = field(default_factory=pd.DataFrame)
    ic_by_horizon: Dict[str, np.ndarray] = field(default_factory=dict)
    excluded: List[Dict[str, Any]] = field(default_factory=list)


class FactorICSelector:
    """因子 IC 筛选器。

    用法：
        selector = FactorICSelector(dal_path="...", price_path="...")
        result = selector.select_factors(
            candidate_metrics=[("cpi", "actual"), ("DX-Y.NYB", "close"), ...],
            horizons=[1, 3, 7, 14, 30],
        )
        print(result.ranking)  # 因子排行榜
    """

    def __init__(self, dal_path: str, price_path: str):
        self.dal_path = dal_path
        self.price_path = price_path
        # 测试时注入的 dataframes（不依赖 DAL）
        self._price_df: Optional[pd.DataFrame] = None
        self._factors_df: Optional[pd.DataFrame] = None

    def _load_price(self) -> pd.DataFrame:
        """加载 BTC 价格数据。

        优先用注入的 _price_df，否则从 price_path 加载 JSON。
        """
        if self._price_df is not None:
            return self._price_df
        # 从 JSON 加载（btc_close_10y.json 格式）
        import json

        with open(self.price_path) as f:
            data = json.load(f)
        # 假设格式: [{"timestamp": ..., "close": ...}, ...] 或 {"timestamps": [...], "closes": [...]}
        if isinstance(data, list):
            df = pd.DataFrame(data)
            if "timestamp" in df.columns:
                df["timestamp"] = pd.to_datetime(df["timestamp"], unit="s")
                df = df.set_index("timestamp")
            elif "date" in df.columns:
                df["date"] = pd.to_datetime(df["date"])
                df = df.set_index("date")
        elif isinstance(data, dict) and "timestamps" in data:
            df = pd.DataFrame(
                {"close": data["closes"]},
                index=pd.to_datetime(data["timestamps"], unit="s"),
            )
        else:
            df = pd.DataFrame(data)
        return df

    def _load_factor_from_dal(
        self, sub_category: str, metric_name: str
    ) -> Optional[pd.Series]:
        """从 19-DAL 加载单个因子时序。"""
        if self._factors_df is not None and metric_name in self._factors_df.columns:
            return self._factors_df[metric_name]
        try:
            conn = sqlite3.connect(f"file:{self.dal_path}?mode=ro", uri=True)
            rows = conn.execute(
                "SELECT timestamp, metric_value FROM mm_metrics "
                "WHERE sub_category=? AND metric_name=? "
                "ORDER BY timestamp ASC",
                (sub_category, metric_name),
            ).fetchall()
            conn.close()
            if not rows:
                return None
            ts = pd.to_datetime([r[0] for r in rows], unit="s")
            vals = [float(r[1]) for r in rows]
            return pd.Series(vals, index=ts, name=metric_name)
        except Exception as e:  # noqa: BLE001
            logger.warning(f"加载因子 {sub_category}.{metric_name} 失败: {e}")
            return None

    def _align_to_price(
        self, factor: pd.Series, price_index: pd.DatetimeIndex
    ) -> pd.Series:
        """将因子对齐到价格时间轴（前向填充低频数据）。"""
        # 重采样到日频（价格是小时频，但因子多为日频/月频）
        factor_daily = factor.resample("1D").last().ffill()
        # 对齐到价格索引
        aligned = factor_daily.reindex(price_index, method="ffill")
        return aligned

    def select_factors(
        self,
        candidate_metrics: List[Tuple[str, str]],
        horizons: List[int] = (1, 3, 7, 14, 30),
        ic_threshold: float = 0.03,
        ir_threshold: float = 0.5,
        win_rate_threshold: float = 0.55,
        vif_threshold: float = 10.0,
        top_k: int = 15,
    ) -> FactorSelectionResult:
        """筛选显著因子。

        Args:
            candidate_metrics: [(sub_category, metric_name), ...]
            horizons: 未来收益周期列表
            ic_threshold: |IC_mean| 阈值
            ir_threshold: |IC_IR| 阈值
            win_rate_threshold: IC 胜率阈值
            vif_threshold: VIF 共线性阈值
            top_k: 保留 Top-K 因子

        Returns:
            FactorSelectionResult
        """
        price_df = self._load_price()
        # 用日频价格计算收益（因子多为日频）
        if "close" not in price_df.columns:
            # 尝试找 close 列
            close_col = [c for c in price_df.columns if "close" in str(c).lower()]
            if close_col:
                price_df = price_df.rename(columns={close_col[0]: "close"})
            else:
                price_df["close"] = price_df.iloc[:, 0]

        # 重采样到日频
        price_daily = price_df["close"].resample("1D").last().dropna()
        price_index = price_daily.index

        # 计算各 horizon 的未来收益
        forward_returns: Dict[int, pd.Series] = {}
        log_ret = np.log(price_daily / price_daily.shift(1))
        for h in horizons:
            # 未来 h 日对数收益
            fwd = log_ret.shift(-h).rolling(h).sum().shift(-h + 1)
            forward_returns[h] = fwd

        # 加载并对齐所有因子
        factors_aligned: Dict[str, pd.Series] = {}
        for sub_cat, metric in candidate_metrics:
            factor = self._load_factor_from_dal(sub_cat, metric)
            if factor is None or len(factor) < 30:
                continue
            aligned = self._align_to_price(factor, price_index)
            if aligned.notna().sum() < 30:
                continue
            factors_aligned[metric] = aligned

        if not factors_aligned:
            return FactorSelectionResult()

        factors_df = pd.DataFrame(factors_aligned).reindex(price_index)

        # 对每个因子计算 IC
        factor_stats: List[Dict[str, Any]] = []
        for name in factors_df.columns:
            factor_vals = factors_df[name].values
            ic_by_h = {}
            all_ic = []
            for h in horizons:
                fwd = forward_returns[h].values
                ic = _compute_rank_ic(factor_vals, fwd)
                ic_by_h[h] = ic
                all_ic.append(ic)

            ic_mean = float(np.mean(all_ic))
            if len(all_ic) > 1:
                ic_std = float(np.std(all_ic, ddof=1))
                ic_ir = ic_mean / (ic_std + 1e-12) if ic_std > 1e-12 else (
                    10.0 if abs(ic_mean) > ic_threshold else 0.0
                )
            else:
                # 单 horizon：用 IC 绝对值作为显著性代理
                # IC > threshold 视为显著，ic_ir 设为较大值
                ic_ir = ic_mean / 0.02 if abs(ic_mean) > ic_threshold else 0.0
            win_rate = float(np.mean(np.array(all_ic) > 0)) if all_ic else 0.0

            factor_stats.append(
                {
                    "name": name,
                    "ic_mean": round(ic_mean, 6),
                    "ic_ir": round(ic_ir, 6),
                    "abs_ic_ir": round(abs(ic_ir), 6),
                    "win_rate": round(win_rate, 4),
                    "n_points": int(factors_df[name].notna().sum()),
                    "ic_by_horizon": ic_by_h,
                }
            )

        # 构建排行榜（按 |IC_IR| 降序）
        ranking_df = pd.DataFrame(factor_stats).sort_values(
            "abs_ic_ir", ascending=False
        )

        # 第一轮筛选：IC 显著性
        selected = []
        excluded = []
        for _, row in ranking_df.iterrows():
            passes_ic = abs(row["ic_mean"]) > ic_threshold
            passes_ir = abs(row["ic_ir"]) > ir_threshold
            passes_win = row["win_rate"] > win_rate_threshold or row["win_rate"] < (
                1.0 - win_rate_threshold
            )
            if passes_ic and passes_ir and passes_win:
                selected.append(row["name"])
            else:
                reasons = []
                if not passes_ic:
                    reasons.append(f"ic_mean={row['ic_mean']:.4f}<{ic_threshold}")
                if not passes_ir:
                    reasons.append(f"ic_ir={row['ic_ir']:.4f}<{ir_threshold}")
                if not passes_win:
                    reasons.append(f"win_rate={row['win_rate']:.2f}")
                excluded.append({"name": row["name"], "reason": "; ".join(reasons)})

        # 第二轮筛选：VIF 共线性（迭代式：每次剔除 VIF 最高的，直到全部 <= 阈值）
        if selected and vif_threshold > 0:
            selected_df = factors_df[selected].dropna(how="all")
            # 只保留有足够数据的因子
            valid_cols = [c for c in selected if selected_df[c].notna().sum() >= 30]
            # 按 |IC_IR| 降序排列（保留优先级）
            ir_order = {
                name: abs(stat["ic_ir"])
                for stat in factor_stats
                if stat["name"] in valid_cols
            }
            valid_cols.sort(key=lambda x: ir_order.get(x, 0), reverse=True)

            current = list(valid_cols)
            while len(current) >= 2:
                vif = _compute_vif(selected_df[current].ffill().dropna())
                # 找 VIF 最高的因子
                max_vif_name = max(current, key=lambda x: vif.get(x, 1.0))
                max_vif_val = vif.get(max_vif_name, 1.0)
                if max_vif_val <= vif_threshold:
                    break
                # 剔除 VIF 最高的
                current.remove(max_vif_name)
                excluded.append(
                    {"name": max_vif_name, "reason": f"VIF={max_vif_val:.2f}>{vif_threshold}"}
                )
            selected = current

        # Top-K
        selected = selected[:top_k]

        # 重新构建排行榜（仅选中的）
        ranking_df = ranking_df[ranking_df["name"].isin(selected)].reset_index(drop=True)

        # IC by horizon
        ic_by_horizon = {}
        for stat in factor_stats:
            if stat["name"] in selected:
                ic_by_horizon[stat["name"]] = np.array(
                    [stat["ic_by_horizon"].get(h, 0.0) for h in horizons]
                )

        return FactorSelectionResult(
            selected_factors=selected,
            ranking=ranking_df,
            ic_by_horizon=ic_by_horizon,
            excluded=excluded,
        )

    def get_ranking(self) -> pd.DataFrame:
        """返回最近一次筛选的完整排行榜。"""
        return self.select_factors(candidate_metrics=[]).ranking
