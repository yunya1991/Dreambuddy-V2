"""RegimeMapper — Phase 0 Layer 4 8 态软分配 + Consensus + Top3 + 冷启动校准
            + Phase 1 P1.3 点阵图 12×8 支持度矩阵（ECDF 查找表）

Spec §2.5 + §3.3 L4 + §2.4 Panel 2：
  输入：(level_smooth, trend_smooth) 单帧
  输出：{ regime_probs (8类 Σ=1), top3 (3 条 desc), consensus (1 - H(p)/ln8) }

冷启动 8 态中心（默认初始坐标，Phase 3 P3.1 脚本会用 BTC 真实标签统计替换）：
  Name                  (L_c,  T_c)  直觉
  TREND_UP_STRONG      (+2.0, +3.0)  中高区强势上涨（L 中上，T 极高）
  TREND_UP_MILD        (+1.0, +2.0)  中低区稳步上涨（L 略正，T 中高）
  FOMO_RALLY           (+3.0, +2.0)  高位狂热（L 最高，T 强正）
  REVERSAL             (-3.0, +2.0)  深底部反转（L 最低，T 转正回暖）
  RANGE_BOUND          ( 0.0,  0.0)  震荡，L/T 居中
  CONSOLIDATION        (-2.0,  0.0)  低位横盘（L 负，T 近 0）
  VOLATILE_DROP        ( 0.0, -3.0)  趋势骤崩暴跌（T 最负，L 中性偏低）
  DISTRIBUTION         (+3.0, -2.0)  高位派发（L 最高，T 拐向下跌）

P1.3 点阵图支持度（Spec §2.4 Panel 2 + tasks.md L295-303）：
  离线训练：对 8 态中每种标签样本，为 12 个指标构建 ECDF 查找表 cdf_lut
  在线推理：给定指标值 v → 查询在 regime X 的 ECDF 得分位数 q ∈ [0,1]
           支持度 = 1 - 2*|q - 0.5|（中位数=1.0，极端分位=0.0）
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from bcrm2.labels.regime_labeler import REGIME_ORDER

__all__ = ["RegimeMapper", "REGIME_ORDER", "REGIME_CENTERS", "DOTPLOT_INDICATORS"]


# Spec §2.4 Panel 2 点阵图行（12 指标，与 IndicatorBank.MAIN_INDICATORS 一致）
DOTPLOT_INDICATORS: List[str] = [
    "ma200_above_3d", "ma50_above", "ma20_vs_ma50_order",
    "cycle_position_365d", "ma_alignment_score", "ma200_slope_signed",
    "dow_hhhl_score", "log_ret_90d", "log_ret_30d",
    "ma_slope_wavg", "volume_trend_conf", "vol_60d_pct",
]


# Phase 0 冷启动中心（人工经验，Phase 3 P3.1 脚本会用 BTC 真实标签统计替换）
# 设计：L ∈ [-3, +3], T ∈ [-3, +3]，负 L/负 T 均有足够锚点，避免真实熊市样本全坍缩到 CONSOLIDATION。
REGIME_CENTERS: Dict[str, Tuple[float, float]] = {
    "TREND_UP_STRONG":   (+2.0, +3.0),
    "TREND_UP_MILD":     (+1.0, +2.0),
    "FOMO_RALLY":        (+3.0, +2.0),
    "REVERSAL":          (-3.0, +2.0),
    "RANGE_BOUND":       ( 0.0,  0.0),
    "CONSOLIDATION":     (-2.0,  0.0),
    "VOLATILE_DROP":     ( 0.0, -3.0),
    "DISTRIBUTION":      (+3.0, -2.0),
}

# 高斯协方差的「基宽」：Phase 3 真实 BTC 校准表明类间距更紧，默认值收紧以提高共识度。
# 人工初始值：L/T 方向 ±1.0 格（约 25% 类间距尺度）。可通过构造函数覆盖。
_DEFAULT_COV_L = 1.0
_DEFAULT_COV_T = 1.0


def _softmax(x: np.ndarray, temperature: float = 1.0) -> np.ndarray:
    """数值稳定 softmax（temperature: 低=锐利/高=平滑）。"""
    x = np.asarray(x, dtype=float)
    if temperature <= 1e-9:
        temperature = 1e-9
    z = x / temperature
    z = z - z.max()
    e = np.exp(z)
    s = e.sum()
    if s <= 1e-12:
        return np.full_like(e, 1.0 / len(e))
    return e / s


def _entropy_normed8(p: np.ndarray) -> float:
    """Consensus = 1 - H(p)/ln(8)；若不合法 → 返回 0.0。"""
    p = np.asarray(p, dtype=float)
    if p.sum() <= 1e-12:
        return 0.0
    p = p / p.sum()
    logp = np.log(np.where(p > 1e-12, p, 1.0))
    H = float(-(p * logp).sum())
    return float(max(0.0, min(1.0, 1.0 - H / np.log(8))))


class RegimeMapper:
    """Layer 4：Level-Trend → 8 态软分配（高斯 + softmax）。"""

    def __init__(self,
                 centers: Optional[Dict[str, Tuple[float, float]]] = None,
                 cov_L: float = _DEFAULT_COV_L,
                 cov_T: float = _DEFAULT_COV_T,
                 softmax_temperature: float = 0.6,
                 w_mapper: float = 0.7,
                 w_lgbm: float = 0.3,
                 lgbm_predictor: Optional[Any] = None,
                 ):
        self.centers: Dict[str, Tuple[float, float]] = dict(centers if centers is not None else REGIME_CENTERS)
        # 补齐缺失标签：用 REGIME_ORDER 中值兜底（便于冷启动数据覆盖不全时）
        for r in REGIME_ORDER:
            if r not in self.centers:
                self.centers[r] = (0.0, 0.0)

        self.cov_L = float(cov_L)
        self.cov_T = float(cov_T)
        self.softmax_temperature = float(softmax_temperature)
        self.w_mapper = float(w_mapper)
        self.w_lgbm = float(w_lgbm)
        self.lgbm = lgbm_predictor  # Phase 1 接入：对象需实现 predict_proba(feature_row:1D)->(8,)
        # 预计算有序 center 数组（加速 transform_sequence）
        self._ordered_names = list(REGIME_ORDER)
        self._Lc = np.array([self.centers[r][0] for r in self._ordered_names], dtype=float)
        self._Tc = np.array([self.centers[r][1] for r in self._ordered_names], dtype=float)
        # P1.3 点阵图 ECDF 查找表：{ regime -> { indicator -> (xs, ys) } }
        # 由 compute_dotplot_support() 构建；未构建时为 None，indicator_support 返回中性 0.5
        self.cdf_lut: Optional[Dict[str, Dict[str, Tuple[np.ndarray, np.ndarray]]]] = None
        self._dotplot_indicators: List[str] = list(DOTPLOT_INDICATORS)

    # ====================================================================
    # 单帧计算（接口最稳定）
    # ====================================================================
    def map_frame(self,
                  level_smooth: float,
                  trend_smooth: float,
                  feature_row: Optional[np.ndarray] = None,
                  ) -> Dict[str, Any]:
        """计算单帧 (L,T) → Dict。

        Args:
            level_smooth: Level ∈ [-4, 4]
            trend_smooth: Trend ∈ [-4, 4]
            feature_row: Phase 1 传递 16 维 LGBM 特征向量；Phase 0 为 None
        Returns:
            {
              "level_smooth": float,
              "trend_smooth": float,
              "regime_probs": {"TREND_UP_STRONG": v1, ... 共 8 个},
              "top3": [(regime, prob), (regime, prob), (regime, prob)],   # desc
              "consensus": float ∈ [0, 1],
            }
        """
        # 1) 高斯距离 → 负方差作为 logit → softmax（w_mapper 分支）
        Lv = float(level_smooth)
        Tv = float(trend_smooth)
        dL = (Lv - self._Lc) / max(1e-6, self.cov_L)
        dT = (Tv - self._Tc) / max(1e-6, self.cov_T)
        neg_sq_dist = -0.5 * (dL * dL + dT * dT)
        p_mapper = _softmax(neg_sq_dist, temperature=self.softmax_temperature)

        # 2) LGBM 分支（Phase 0：lgbm=None → 退化为均匀分布；加权时会被 w_mapper=0.7 覆盖）
        if self.lgbm is not None and feature_row is not None:
            try:
                p_lgbm = np.asarray(self.lgbm.predict_proba(feature_row), dtype=float).reshape(-1)
                if p_lgbm.shape != (8,):
                    p_lgbm = np.full(8, 1.0 / 8.0)
                s = p_lgbm.sum()
                if s <= 1e-12:
                    p_lgbm = np.full(8, 1.0 / 8.0)
                else:
                    p_lgbm = p_lgbm / s
            except Exception:
                p_lgbm = np.full(8, 1.0 / 8.0)
        else:
            # 未接入：用均匀分布做 "dummy"，但 w_lgbm=0.3 → 等效为把 mapper 权重稀释
            #   -> 更稳妥：让 w_mapper = 1.0 - w_lgbm_total，避免 uniform 占比。
            p_lgbm = p_mapper  # fallback: 用 mapper 自身代替，等于不加权
            # 如果未来 lgbm 明确不存在但要保持 w 加和 = 1，这里不改变结果

        # 3) 0.7 : 0.3 加权（当 p_lgbm == p_mapper 时结果 == p_mapper ）
        if self.lgbm is not None and feature_row is not None:
            total = self.w_mapper + self.w_lgbm
            w1 = self.w_mapper / total
            w2 = self.w_lgbm / total
            p_final = w1 * p_mapper + w2 * p_lgbm
        else:
            p_final = p_mapper

        # 归一化保险
        s = float(p_final.sum())
        if s <= 1e-12:
            p_final = np.full(8, 1.0 / 8.0)
        else:
            p_final = p_final / s

        probs_dict = {self._ordered_names[i]: float(p_final[i]) for i in range(8)}
        top3_idx = np.argsort(-p_final)[:3]
        top3 = [(self._ordered_names[i], float(p_final[i])) for i in top3_idx]
        consensus = _entropy_normed8(p_final)

        return {
            "level_smooth": Lv,
            "trend_smooth": Tv,
            "regime_probs": probs_dict,
            "top3": top3,
            "consensus": consensus,
        }

    # ====================================================================
    # 序列计算（批量，给 trajectory 用）
    # ====================================================================
    def transform_sequence(self,
                           level_smooth: Sequence[float],
                           trend_smooth: Sequence[float],
                           indicators: Optional[Dict[str, pd.Series]] = None,
                           feature_matrix: Optional[np.ndarray] = None,
                           hmm_state: Optional[Sequence[int]] = None,
                           bocpd_cp_prob: Optional[Sequence[float]] = None,
                           ) -> List[Dict[str, Any]]:
        """按序遍历，返回与输入等长的 frame 列表。每个 frame 包含完整字段 + hmm_state/bocpd。"""
        L_seq = np.asarray(level_smooth, dtype=float)
        T_seq = np.asarray(trend_smooth, dtype=float)
        n = len(L_seq)
        if len(T_seq) != n:
            raise ValueError(f"Level/Trend 长度不一致: {n} vs {len(T_seq)}")

        # 预取 hmm/bocpd numpy 数组（避免循环内 isinstance 检查 + Series 整数键歧义 FutureWarning）
        if hmm_state is None:
            hs_arr = None
        elif isinstance(hmm_state, pd.Series):
            hs_arr = hmm_state.values
        else:
            hs_arr = np.asarray(hmm_state, dtype=int)
        if bocpd_cp_prob is None:
            bc_arr = None
        elif isinstance(bocpd_cp_prob, pd.Series):
            bc_arr = bocpd_cp_prob.values
        else:
            bc_arr = np.asarray(bocpd_cp_prob, dtype=float)

        frames: List[Dict[str, Any]] = [None] * n
        for i in range(n):
            feat = feature_matrix[i] if feature_matrix is not None else None
            fr = self.map_frame(float(L_seq[i]), float(T_seq[i]), feature_row=feat)
            fr["hmm_state"] = int(hs_arr[i]) if hs_arr is not None else 1
            fr["bocpd_cp_prob"] = float(bc_arr[i]) if bc_arr is not None else 0.0
            frames[i] = fr
        return frames

    # ====================================================================
    # 冷启动中心校准（静态方法，Spec §3.4 — Phase 3 P3.1 脚本复用）
    # ====================================================================
    @staticmethod
    def calibrate_centers(labels: pd.Series,
                          level: pd.Series,
                          trend: pd.Series,
                          min_samples: int = 20,
                          fallback: Dict[str, Tuple[float, float]] = None,
                          ) -> Dict[str, Tuple[float, float]]:
        """用标签序列 + (L, T) 序列统计 8 类中心。

        算法：对每个 regime 在标签中出现的样本，直接取该类的 level.mean(), trend.mean()。
        样本数 < min_samples 的类 → fallback 中取值；fallback 缺失 → 用全局 (0, 0)。
        """
        fallback = dict(fallback if fallback is not None else REGIME_CENTERS)
        L_arr = np.asarray(level, dtype=float)
        T_arr = np.asarray(trend, dtype=float)
        label_arr = labels.values.astype(object)

        new_centers: Dict[str, Tuple[float, float]] = {}
        for regime in REGIME_ORDER:
            mask = label_arr == regime
            if mask.sum() >= min_samples:
                Lc = float(L_arr[mask].mean())
                Tc = float(T_arr[mask].mean())
            else:
                if regime in fallback:
                    Lc, Tc = fallback[regime]
                else:
                    Lc, Tc = (0.0, 0.0)
            new_centers[regime] = (Lc, Tc)
        return new_centers

    # ====================================================================
    # P1.3 点阵图 12×8 支持度矩阵（Spec §2.4 Panel 2 + tasks.md L295-303）
    # ====================================================================
    @staticmethod
    def _build_cdf_lut(values: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
        """构建经验累积分布函数（ECDF）查找表。

        Args:
            values: 某 regime 下某指标的所有样本值（已剔除 NaN）
        Returns:
            xs: 排序后的值（升序）
            ys: 对应的累积概率 ∈ (0, 1) — 用 (i+1)/(n+1) 避免极值 0/1
        """
        v = np.asarray(values, dtype=float)
        v = v[~np.isnan(v)]
        if len(v) == 0:
            return np.array([0.0], dtype=float), np.array([0.5], dtype=float)
        xs = np.sort(v)
        n = len(xs)
        # (i+1)/(n+1) plotting position：两端永不取 0/1，防止极端分位压死支持度
        ys = (np.arange(1, n + 1, dtype=float)) / (n + 1.0)
        return xs, ys

    @staticmethod
    def _query_cdf(value: float,
                   xs: np.ndarray,
                   ys: np.ndarray) -> float:
        """在线查询 value 在 ECDF 中的分位数 q ∈ [0, 1]。

        - value 严格小于 xs[0] → 返回 ys[0] × 0.5（保守下伸）
        - value 严格大于 xs[-1] → 返回 1 - (1 - ys[-1]) × 0.5（保守上伸）
        - value 命中 xs 中某段等值区间 [xs[lo], xs[hi-1]] → 返回 ys[lo:hi] 的中位数
          （多值并列时取中位分位，避免偏向首末；让"中位数"映射到 q=0.5）
        - value 落在两个 xs 之间：线性插值
        """
        if xs is None or len(xs) == 0:
            return 0.5
        value = float(value)
        # 等值区间 [lo, hi)
        lo = int(np.searchsorted(xs, value, side='left'))
        hi = int(np.searchsorted(xs, value, side='right'))
        if lo < hi:
            # value 命中 xs 中某些点，返回该区间分位数的中位数
            q_vals = ys[lo:hi]
            return float(np.median(q_vals))
        if value < float(xs[0]):
            return float(ys[0]) * 0.5
        if value > float(xs[-1]):
            return 1.0 - (1.0 - float(ys[-1])) * 0.5
        # value 在两个 xs 之间：线性插值
        idx = lo  # side='left' 给出插入位置
        if idx <= 0:
            return float(ys[0])
        if idx >= len(ys):
            return float(ys[-1])
        x0 = float(xs[idx - 1])
        x1 = float(xs[idx])
        y0 = float(ys[idx - 1])
        y1 = float(ys[idx])
        if x1 - x0 < 1e-12:
            return (y0 + y1) * 0.5
        return y0 + (y1 - y0) * (value - x0) / (x1 - x0)

    @staticmethod
    def _support_from_quantile(q: float) -> float:
        """分位数 → 支持度：support = 1 - 2*|q - 0.5|，clip [0, 1]。

        - q = 0.5（中位数）→ support = 1.0（最支持）
        - q = 0.05 或 0.95 → support = 0.10（弱支持）
        - q = 0 或 1（极端）→ support = 0.0（不支持）
        """
        q = float(q)
        if q < 0.0:
            q = 0.0
        elif q > 1.0:
            q = 1.0
        s = 1.0 - 2.0 * abs(q - 0.5)
        return float(max(0.0, min(1.0, s)))

    def compute_dotplot_support(self,
                                indicators: Dict[str, pd.Series],
                                regime_labels: pd.Series,
                                min_samples: int = 20,
                                target_index: Optional[int] = None,
                                ) -> Dict[str, Any]:
        """离线训练：构建 8 态 × 12 指标的 CDF LUT，并计算目标日的 12×8 支持度矩阵。

        Spec §2.4 Panel 2 + tasks.md L295-303：
          1) 对每个 regime R，对每个 indicator I：取 regime_labels==R 的样本
             对应的 indicator 值，构建 ECDF (xs, ys)；样本数 < min_samples 时
             用全样本构建（fallback）
          2) 在线：对 target_index 日（默认最后一日），每个指标值 v 查询每个
             regime 的 ECDF → 分位数 q → 支持度 = 1 - 2*|q - 0.5|
          3) marginal_probs[j] = 12 个指标对 regime_j 支持度的平均（归一化 Σ=1）

        Args:
            indicators: 12 指标字典，key ∈ DOTPLOT_INDICATORS，value 为 pd.Series
            regime_labels: 与 indicators 等长的真实 8 态标签序列
            min_samples: regime 样本数下限，不足则 fallback 到全样本 ECDF
            target_index: 计算哪一日的支持度矩阵，默认 len-1（最新一日）
        Returns:
            {
              "rows": [12 指标名],
              "cols": [8 regime 名],
              "matrix": float[12][8],          # 支持度 [0, 1]
              "marginal_probs": float[8],      # 列向归一化概率 Σ=1
              "target_index": int,
              "sample_counts": {regime: int},  # 每个 regime 样本数（诊断）
            }
        """
        # 对齐标签
        label_arr = regime_labels.values.astype(object)
        n = len(label_arr)

        # 1) 构建 cdf_lut
        cdf_lut: Dict[str, Dict[str, Tuple[np.ndarray, np.ndarray]]] = {}
        sample_counts: Dict[str, int] = {}
        for regime in self._ordered_names:
            mask = label_arr == regime
            n_regime = int(mask.sum())
            sample_counts[regime] = n_regime
            cdf_lut[regime] = {}
            for ind_name in self._dotplot_indicators:
                if ind_name not in indicators:
                    continue
                v_all = indicators[ind_name].values.astype(float)
                v = v_all[mask]
                if n_regime < min_samples:
                    # 样本不足 → 退化到全样本 ECDF（保持非空）
                    v = v_all
                cdf_lut[regime][ind_name] = self._build_cdf_lut(v)
        self.cdf_lut = cdf_lut  # 持久化到实例，供 indicator_support 在线查询

        # 2) 计算目标日支持度矩阵
        if target_index is None:
            target_index = n - 1
        if target_index < 0 or target_index >= n:
            raise ValueError(f"target_index {target_index} 超出范围 [0, {n - 1}]")

        n_rows = len(self._dotplot_indicators)
        n_cols = len(self._ordered_names)
        matrix = np.zeros((n_rows, n_cols), dtype=float)

        for i, ind_name in enumerate(self._dotplot_indicators):
            if ind_name not in indicators:
                continue
            v = float(indicators[ind_name].iloc[target_index])
            for j, regime in enumerate(self._ordered_names):
                lut = cdf_lut[regime].get(ind_name)
                if lut is None:
                    matrix[i, j] = 0.5
                    continue
                xs, ys = lut
                q = self._query_cdf(v, xs, ys)
                matrix[i, j] = self._support_from_quantile(q)

        # 3) marginal_probs: 列向归一化（每列 = 一个 regime 在 12 指标下的平均支持度）
        col_means = matrix.mean(axis=0)
        s = float(col_means.sum())
        if s > 1e-12:
            marginal_probs = col_means / s
        else:
            marginal_probs = np.full(n_cols, 1.0 / n_cols, dtype=float)

        return {
            "rows": list(self._dotplot_indicators),
            "cols": list(self._ordered_names),
            "matrix": matrix.tolist(),
            "marginal_probs": marginal_probs.tolist(),
            "target_index": int(target_index),
            "sample_counts": sample_counts,
        }

    def indicator_support(self,
                          value: float,
                          indicator_name: str,
                          regime: str) -> float:
        """在线查询：某指标值对某 regime 的支持度 ∈ [0, 1]。

        需先调用 compute_dotplot_support 构建 cdf_lut；未构建时返回中性 0.5。
        用于前端实时更新点阵图行 / 单指标诊断。
        """
        if self.cdf_lut is None:
            return 0.5
        lut = self.cdf_lut.get(regime, {}).get(indicator_name)
        if lut is None:
            return 0.5
        xs, ys = lut
        q = self._query_cdf(value, xs, ys)
        return self._support_from_quantile(q)

    def indicator_support_row(self,
                              indicators_row: Dict[str, float],
                              regime: str) -> List[float]:
        """在线查询：一整行 12 指标对指定 regime 的支持度向量。

        Args:
            indicators_row: { indicator_name: value } 一日指标字典
            regime: 目标 regime 名
        Returns:
            长度 12 的支持度列表，顺序同 DOTPLOT_INDICATORS
        """
        return [self.indicator_support(float(indicators_row.get(name, 0.0)), name, regime)
                for name in self._dotplot_indicators]

    def save_dotplot_lut(self, path: Path) -> None:
        """将 cdf_lut 持久化为 JSON 文件（xs/ys 转为 list）。

        便于 P1.5 SQLite 之外的快速离线加载，或前端直读。
        """
        if self.cdf_lut is None:
            raise RuntimeError("cdf_lut 未构建，请先调用 compute_dotplot_support()")
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        serializable: Dict[str, Dict[str, Dict[str, list]]] = {}
        for regime, ind_map in self.cdf_lut.items():
            serializable[regime] = {}
            for ind_name, (xs, ys) in ind_map.items():
                serializable[regime][ind_name] = {
                    "xs": [float(x) for x in np.asarray(xs, dtype=float).tolist()],
                    "ys": [float(y) for y in np.asarray(ys, dtype=float).tolist()],
                }
        payload = {
            "indicators": list(self._dotplot_indicators),
            "regimes": list(self._ordered_names),
            "cdf_lut": serializable,
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))

    def load_dotplot_lut(self, path: Path) -> None:
        """从 JSON 文件恢复 cdf_lut（与 save_dotplot_lut 对应）。"""
        path = Path(path)
        with open(path, "r", encoding="utf-8") as f:
            payload = json.load(f)
        cdf_lut: Dict[str, Dict[str, Tuple[np.ndarray, np.ndarray]]] = {}
        for regime, ind_map in payload.get("cdf_lut", {}).items():
            cdf_lut[regime] = {}
            for ind_name, lut in ind_map.items():
                xs = np.asarray(lut["xs"], dtype=float)
                ys = np.asarray(lut["ys"], dtype=float)
                cdf_lut[regime][ind_name] = (xs, ys)
        self.cdf_lut = cdf_lut
        # 同步指标顺序（若文件中包含）
        if "indicators" in payload and len(payload["indicators"]) == len(self._dotplot_indicators):
            self._dotplot_indicators = list(payload["indicators"])
