"""PCA 五维共振分析器（定强度）。

对应 Spec §三 Step 4-B：
  - 主要矛盾（Step 4）定方向；
  - PCA 共振分析（本模块）定强度：其他四维与主导维度的共振/冲突
    → strength_coefficient 增强/减弱最小阻力强度。

所有方法 FAIL-OPEN：异常或样本不足时返回中性默认值（不破坏下游）。
"""
from __future__ import annotations

import warnings

import numpy as np
from sklearn.decomposition import PCA

from force_vector.models import PCAResonance

# 五维固定顺序
_DIM_ORDER = ("dao", "tian", "di", "jiang", "fa")

# explained_ratio 退化阈值：低于此值视为 PCA 结构不清晰，强度额外打折
_DEGENERACY_THRESHOLD = 0.3


class PCAResonanceAnalyzer:
    """PCA 五维共振分析器。

    compute_resonance      : 五维力量 → PCAResonance（强度调整系数）
    compute_rank_stability : 连续两期排名的 Spearman 秩相关 → [0,1]
    detect_top1_shift      : top-1 特征是否在两期间发生切换
    """

    # ------------------------------------------------------------------
    # PCA 五维共振分析（定强度）
    # ------------------------------------------------------------------
    def compute_resonance(self, five_dim_powers: dict,
                          dominant_dim: str) -> PCAResonance:
        """PCA 五维共振分析（定强度）。

        Args:
            five_dim_powers: 五维力量值，如
                {"dao": 0.5, "tian": 0.3, "di": -0.2, "jiang": 0.4, "fa": 0.1}
            dominant_dim: 主导维度名（由 Step 4 特征关联度 top-1 确定，PCA 不改变）

        Returns:
            PCAResonance:
              - explained_ratio  : 第一主成分解释方差比 [0,1]
              - sign_alignment    : 其他四维与主导维度同向比例 [0,1]
              - alignment        : 共振等级枚举
              - strength_coefficient : 强度调整系数 [0.3, 1.3]
              - dominant_dimension : 原样回传主导维度

        强度系数阶梯（按 sign_alignment）：
            全共振 (1.0)        → ×1.3
            强共振 (≥0.75)      → ×1.2
            弱共振 (0.5,0.75)   → ×1.0
            冲突   (0,0.5]      → ×0.5
            全冲突 (0.0)        → ×0.3
        explained_ratio < 0.3 → PCA 退化，额外 ×0.8。
        异常时返回中性默认（strength_coefficient=1.0，无方向性调整）。
        """
        try:
            # 输入校验：主导维度必须存在且五维齐全
            if (not five_dim_powers or dominant_dim not in five_dim_powers
                    or not all(d in five_dim_powers for d in _DIM_ORDER)):
                return self._neutral_default(dominant_dim)

            powers = np.array(
                [float(five_dim_powers[d]) for d in _DIM_ORDER], dtype=float
            )
            dominant_power = float(five_dim_powers[dominant_dim])

            # 1) PCA 分解：协方差矩阵 → 特征值 → explained_ratio = λ1/Σλi
            explained_ratio = self._explained_variance_ratio(powers)

            # 2) 共振分析：其他四维与主导维度的方向一致性
            sign_alignment = self._sign_alignment(powers, dominant_dim,
                                                   dominant_power)

            # 3) 强度调整系数（按共振等级）
            alignment, strength_coefficient = self._resonance_coefficient(
                sign_alignment
            )

            # 4) PCA 退化惩罚：结构不清晰时额外打折
            if explained_ratio < _DEGENERACY_THRESHOLD:
                strength_coefficient *= 0.8

            return PCAResonance(
                explained_ratio=float(explained_ratio),
                sign_alignment=float(sign_alignment),
                alignment=alignment,
                strength_coefficient=float(strength_coefficient),
                dominant_dimension=dominant_dim,
            )
        except Exception:
            return self._neutral_default(dominant_dim)

    # ------------------------------------------------------------------
    # 排名一致性检测：Spearman 秩相关
    # ------------------------------------------------------------------
    def compute_rank_stability(self, ranks_t: list,
                               ranks_t_prev: list) -> float:
        """排名一致性检测：Spearman 秩相关(rank_t, rank_t_prev)。

        返回 [0, 1]（负相关截断到 0）。异常或样本不足时返回中性默认 0.5。
        """
        try:
            if (ranks_t is None or ranks_t_prev is None
                    or len(ranks_t) < 2 or len(ranks_t_prev) < 2
                    or len(ranks_t) != len(ranks_t_prev)):
                return 0.5
            from scipy.stats import spearmanr
            r, _p = spearmanr(ranks_t, ranks_t_prev)
            if r is None or not np.isfinite(r):
                return 0.5
            # [-1,1] → [0,1]：负相关视为完全不一致(0)
            stability = float(max(0.0, min(1.0, float(r))))
            return stability
        except Exception:
            return 0.5

    # ------------------------------------------------------------------
    # top-1 特征是否切换
    # ------------------------------------------------------------------
    def detect_top1_shift(self, ranks_t: list, ranks_t_prev: list) -> bool:
        """top-1 特征是否在两期之间切换。

        - 数值排名列表：rank=1 即最小值，top-1 = argmin；
        - 字符串列表：视为按排名排序，top-1 = 首元素。
        异常时返回 False（不轻易误报切换）。
        """
        try:
            if (not ranks_t or not ranks_t_prev
                    or len(ranks_t) == 0 or len(ranks_t_prev) == 0):
                return False
            if isinstance(ranks_t[0], str):
                top_t = ranks_t[0]
                top_prev = ranks_t_prev[0]
            else:
                top_t = int(np.argmin(np.asarray(ranks_t, dtype=float)))
                top_prev = int(np.argmin(np.asarray(ranks_t_prev, dtype=float)))
            return bool(top_t != top_prev)
        except Exception:
            return False

    # ==================================================================
    # 内部工具方法
    # ==================================================================
    def _explained_variance_ratio(self, powers: np.ndarray) -> float:
        """计算第一主成分解释方差比 λ1/Σλi。

        五维力量单快照下，将五维视为 5 个样本、1 个特征做 PCA：
        方差非零时单成分即解释 100%；方差为零（恒定）时 PCA 退化 → 0。
        """
        try:
            X = powers.reshape(-1, 1)  # (5, 1)
            if X.shape[0] < 2:
                return 1.0
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                pca = PCA(n_components=1)
                pca.fit(X)
                ratio = pca.explained_variance_ratio_
            if ratio is None or len(ratio) == 0:
                return 1.0
            r0 = float(ratio[0])
            if not np.isfinite(r0):
                return 0.0
            return max(0.0, min(1.0, r0))
        except Exception:
            return 1.0  # PCA 异常时不施加退化惩罚（保守不削弱）

    def _sign_alignment(self, powers: np.ndarray, dominant_dim: str,
                        dominant_power: float) -> float:
        """其他四维与主导维度方向一致的比例。

        sign_alignment = count(sign(dim_i) == sign(dominant)) / 4
        主导维度符号为 0 时，无其他维度可对齐 → 0.0。
        """
        dom_sign = np.sign(dominant_power)
        aligned = 0
        for d in _DIM_ORDER:
            if d == dominant_dim:
                continue
            if np.sign(float(powers[_DIM_ORDER.index(d)])) == dom_sign:
                aligned += 1
        # dom_sign == 0 时 aligned 保持 0（dom_sign 不匹配任何非零符号）
        return float(aligned) / 4.0

    @staticmethod
    def _resonance_coefficient(sign_alignment: float):
        """按共振等级返回 (alignment, strength_coefficient)。"""
        if sign_alignment >= 1.0:
            return "full_resonance", 1.3
        if sign_alignment >= 0.75:
            return "strong_resonance", 1.2
        if sign_alignment > 0.5:
            return "weak_resonance", 1.0
        if sign_alignment <= 0.0:
            return "full_conflict", 0.3
        # (0.0, 0.5] → 冲突
        return "conflict", 0.5

    @staticmethod
    def _neutral_default(dominant_dim: str) -> PCAResonance:
        """FAIL-OPEN 中性默认：强度系数 1.0（无方向性调整）。"""
        return PCAResonance(
            explained_ratio=1.0,
            sign_alignment=0.5,
            alignment="weak_resonance",
            strength_coefficient=1.0,
            dominant_dimension=dominant_dim,
        )
