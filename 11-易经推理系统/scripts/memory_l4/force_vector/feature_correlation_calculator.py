"""特征-价格关联度计算器 —— IC / MI / 综合排名 / 最优权重 / Beta融合。

纯 numpy + scipy + sklearn 实现，所有方法 FAIL-OPEN（异常返回中性默认值）。
对应 Spec §三 Step 4 特征关联度。
"""
from __future__ import annotations

import os as _os
import sys as _sys

# ============================================================
# 注入「9-基本面分析」到 sys.path（engines.* 导入前置）
#   定位方式：本文件 上溯 4 层到项目根，再拼「9-基本面分析」。
#   Fail-Open：目录不存在或已在 path → 静默跳过。
# ============================================================
try:  # noqa: E402
    _HERE = _os.path.dirname(_os.path.abspath(__file__))          # force_vector
    _SCRIPTS = _os.path.dirname(_HERE)                            # scripts
    _YIJING = _os.path.dirname(_SCRIPTS)                         # 11-易经推理系统
    _ROOT = _os.path.dirname(_YIJING)                             # dreambuddy-v2
    _9_FUND_PATH = _os.path.join(_ROOT, "9-基本面分析")
    if _os.path.isdir(_9_FUND_PATH) and _9_FUND_PATH not in _sys.path:
        _sys.path.insert(0, _9_FUND_PATH)
except Exception:
    pass

import numpy as np
from scipy.stats import spearmanr
from sklearn.feature_selection import mutual_info_regression

from force_vector.models import FeatureCorrelation


# 权重上下界约束（Spec §三 Step 4：每个特征权重 ∈ [0.02, 0.40]）
_W_MIN = 0.02
_W_MAX = 0.40


class FeatureCorrelationCalculator:
    """特征-价格关联度计算器。

    - IC：Spearman 秩相关（滞后对齐 feature[t] vs returns[t+1]），抗异常值，[-1,1]。
    - MI：互信息（同期对齐），非线性关联度，归一化到 [0,1]。
    - 综合关联度 = |IC| * w_linear + MI * w_nonlinear。
    - 最优权重 = |IC|^alpha 归一化，约束 ∈ [0.02, 0.40]。
    - Beta 融合：复用 signal_engine._adaptive_weight 做后验修正。
    所有方法 FAIL-OPEN：异常返回中性默认值。
    """

    # ============================================================
    # 信息系数 IC（Spearman 秩相关，滞后对齐）
    # ============================================================
    def compute_ic(self, feature: np.ndarray, returns: np.ndarray) -> float:
        """信息系数 IC = Spearman秩相关(feature[t], returns[t+1])

        抗异常值，返回 [-1, 1]。
        """
        try:
            f = np.asarray(feature, dtype=float)
            r = np.asarray(returns, dtype=float)
            n = min(len(f), len(r))
            if n < 3:
                return 0.0
            # 滞后对齐：feature[t] 预测 returns[t+1]
            x = f[:-1]
            y = r[1:][:len(x)]
            if len(x) < 3:
                return 0.0
            rho, _ = spearmanr(x, y)
            if rho is None or np.isnan(rho):
                return 0.0
            return float(max(-1.0, min(1.0, rho)))
        except Exception:
            return 0.0

    # ============================================================
    # 互信息 MI（非线性关联度，归一化 [0,1]）
    # ============================================================
    def compute_mi_normalized(self, feature: np.ndarray, returns: np.ndarray,
                              n_bins: int = 10) -> float:
        """互信息 MI（非线性关联度），归一化到 [0, 1]

        使用 sklearn.mutual_info_regression，然后用 max_mi（=返回值离散化熵）归一化。
        异常时返回 0.0。
        """
        try:
            f = np.asarray(feature, dtype=float).reshape(-1, 1)
            r = np.asarray(returns, dtype=float)
            n = min(len(f), len(r))
            if n < 4:  # KNN 估计器(n_neighbors=3) 需 n>3
                return 0.0
            # 同期对齐：衡量 feature[t] 与 returns[t] 的非线性关联
            f = f[:n]
            r = r[:n]
            mi = float(mutual_info_regression(f, r, n_neighbors=3,
                                              random_state=42)[0])
            # max_mi = H(returns) 离散化为 n_bins 箱（不确定性系数上界）
            r_min = float(r.min())
            r_max = float(r.max())
            if r_max - r_min <= 0:
                return 0.0  # 返回值无变异 → 无信息
            edges = np.linspace(r_min, r_max + 1e-12, n_bins + 1)
            idx = np.clip(np.searchsorted(edges[1:-1], r, side='right'),
                          0, n_bins - 1)
            counts = np.bincount(idx, minlength=n_bins).astype(float)
            total = counts.sum()
            if total <= 0:
                return 0.0
            p = counts / total
            p = p[p > 0]
            h = float(-np.sum(p * np.log(p)))  # nats，与 MI 同单位
            max_mi = h if h > 0 else 1e-9
            return float(min(1.0, max(0.0, mi / max_mi)))
        except Exception:
            return 0.0

    # ============================================================
    # 综合关联度
    # ============================================================
    def compute_combined_score(self, ic: float, mi: float,
                               w_linear: float = 0.6,
                               w_nonlinear: float = 0.4) -> float:
        """综合关联度 = |IC| * w_linear + MI * w_nonlinear"""
        try:
            return float(abs(ic) * w_linear + mi * w_nonlinear)
        except Exception:
            return 0.0

    # ============================================================
    # 排名（按 combined_score 降序，rank 从 1 开始）
    # ============================================================
    def rank_features(self, correlations: list) -> list:
        """按 combined_score 降序排名，返回排序后的列表，rank 从1开始"""
        try:
            if not correlations:
                return []
            sorted_corr = sorted(
                correlations,
                key=lambda c: getattr(c, "combined_score", 0.0),
                reverse=True,
            )
            ranked = []
            for i, c in enumerate(sorted_corr):
                ranked.append(self._copy_with_rank(c, i + 1))
            return ranked
        except Exception:
            return list(correlations) if correlations else []

    @staticmethod
    def _copy_with_rank(c, rank: int):
        """复制 FeatureCorrelation 并更新 rank（不修改原对象）。"""
        try:
            from dataclasses import replace
            return replace(c, rank=rank)
        except Exception:
            try:
                c.rank = rank
                return c
            except Exception:
                return c

    # ============================================================
    # 最优权重（|IC|^alpha 归一化，约束 ∈ [0.02, 0.40]）
    # ============================================================
    def compute_optimal_weights(self, correlations: list,
                                alpha: float = 1.0) -> dict:
        """最优权重 = |IC|^alpha 归一化

        约束：每个权重 ∈ [0.02, 0.40]
        返回 {feature_name: weight}
        """
        try:
            if not correlations:
                return {}
            items = []
            for c in correlations:
                name = getattr(c, "feature_name", None)
                ic = float(getattr(c, "ic_30d", 0.0))
                items.append((name, abs(ic) ** alpha))
            total = sum(v for _, v in items)
            if total <= 0:
                # 全部 IC=0 → 均分（仍在约束内）
                n = len(items)
                w = min(_W_MAX, max(_W_MIN, 1.0 / n))
                return {name: w for name, _ in items}
            return self._normalize_clamped(items, total)
        except Exception:
            return {}

    @staticmethod
    def _normalize_clamped(items: list, total: float) -> dict:
        """归一化到 sum=1 并约束每个权重 ∈ [0.02, 0.40]。"""
        w = {name: max(_W_MIN, min(_W_MAX, v / total)) for name, v in items}
        s = sum(w.values())
        if s > 0:
            w = {name: v / s for name, v in w.items()}
        return w

    # ============================================================
    # Beta 后验权重融合（复用 signal_engine._adaptive_weight）
    # ============================================================
    def fuse_with_beta(self, ic_weights: dict, signal_engine,
                       module_names: dict) -> dict:
        """Beta后验权重融合（复用 signal_engine._adaptive_weight）

        feature_weight_i = ic_weight_i * signal_engine._adaptive_weight(module_name_i)
        signal_engine 为 None 时直接返回 ic_weights
        module_names: {feature_name: module_name} 映射
        返回 {feature_name: final_weight}
        """
        try:
            if signal_engine is None:
                return ic_weights
            if not ic_weights:
                return {}
            items = []
            for name, ic_w in ic_weights.items():
                module = module_names.get(name) if module_names else None
                beta = self._safe_adaptive_weight(signal_engine, module)
                items.append((name, float(ic_w) * beta))
            total = sum(v for _, v in items)
            if total <= 0:
                n = len(items)
                w = min(_W_MAX, max(_W_MIN, 1.0 / n))
                return {name: w for name, _ in items}
            return self._normalize_clamped(items, total)
        except Exception:
            return ic_weights if ic_weights else {}

    @staticmethod
    def _safe_adaptive_weight(signal_engine, module_name) -> float:
        """安全调用 signal_engine._adaptive_weight，异常返回 1.0。"""
        try:
            if module_name is None:
                return 1.0
            w = float(signal_engine._adaptive_weight(module_name))
            if np.isnan(w) or w <= 0:
                return 1.0
            return w
        except Exception:
            return 1.0
