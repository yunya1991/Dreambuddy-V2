"""TemporalSmoother — Phase 0 Layer 3 时序平滑（HMM 3 态 Viterbi + EMA 兜底）

Spec §7.2 + §2.4 Layer 3：
  输入：ScoreComposer 输出的 level_raw / trend_raw（已 clamp_delta 连续化）
  输出：SmootherOutput（level_smooth, trend_smooth, hmm_state, ema_level, bocpd_cp_prob）

流程：
  1) level / trend 的 5 日滚动均值（去除短期毛刺）作为 HMM 观测
  2) 训练 3 态 GaussianHMM（Bear=0, Neutral=1, Bull=2）
     - HMM 训练失败 → 降级只用 EMA（从不抛异常）
  3) Viterbi 解码 得到 0/1/2 三态
  4) EMA 兜底：level_smooth 以 alpha=0.25 指数平滑（与 HMM 独立）
  5) HMM soft blending：最终 level_smooth = w_HMM × HMM 平滑 + (1 - w_HMM) × EMA，
     其中 w_HMM = 0.65（若 HMM 成功训练），否则 0
  6) bocpd_cp_prob：P1.2 接入变点检测（简化 BOCPD：滚动 20 日 z-score + sigmoid）；
     变点 P>0.7 且量能≥1.5× 均量时，对 Trend 做 5 日渐进调整（每日 sign×0.06，合计 ±0.30）。
     未传 close/volume 或 bocpd_enabled=False 时保持全 0（兼容旧调用）。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

__all__ = ["TemporalSmoother", "SmootherOutput"]


@dataclass
class SmootherOutput:
    level_smooth: pd.Series      # 最终平滑后的 Level（[-4, 4]）
    trend_smooth: pd.Series      # 最终平滑后的 Trend（[-4, 4]）
    hmm_state: pd.Series         # HMM 3 态：0=Bear, 1=Neutral, 2=Bull
    ema_level: pd.Series         # EMA 兜底平滑（诊断用）
    bocpd_cp_prob: pd.Series     # BOCPD 变点概率，Phase 0=0


# 默认冷启动 HMM 3 态 → Bull/Neutral/Bear 语义映射。
# HMM 是无监督的，状态编号不直接对应语义；Phase 0 中按「该状态下 (L+T)/2 的均值」
# 进行简单重排：均值最低 = Bear(0)，中间 = Neutral(1)，最高 = Bull(2)。
def _remap_states_by_level(hmm_states: np.ndarray,
                           level: np.ndarray,
                           trend: np.ndarray,
                           n_states: int = 3) -> np.ndarray:
    """按「该状态样本的 (L+T)/2 均值」重映射：最小→Bear(0)，中间→Neutral(1)，最大→Bull(2)。"""
    score = (level + trend) / 2.0
    means = np.zeros(n_states, dtype=float)
    for s in range(n_states):
        mask = hmm_states == s
        if mask.sum() > 0:
            means[s] = float(score[mask].mean())
        else:
            means[s] = -1e9 + s  # 空状态按索引兜底，防止排序崩溃
    order = np.argsort(means)  # [min_state_idx, mid, max_state_idx]
    remap = np.empty(n_states, dtype=int)
    remap[order] = np.arange(n_states)  # state -> 0(Bear)/1(Neutral)/2(Bull)
    return remap[hmm_states]


class TemporalSmoother:
    """Layer 3：HMM Viterbi + EMA 时序平滑。"""

    def __init__(self,
                 n_hmm_states: int = 3,
                 ma_window: int = 5,
                 ema_alpha: float = 0.25,
                 hmm_blend: float = 0.65,
                 random_state: int = 42,
                 # —— P1.2 BOCPD 变点 5 日渐进调整 ——
                 bocpd_enabled: bool = True,
                 bocpd_hazard: float = 0.01,
                 bocpd_trigger_p: float = 0.7,
                 bocpd_volume_ratio_thr: float = 1.5,
                 bocpd_gradual_days: int = 5,
                 bocpd_daily_amount: float = 0.06,
                 ):
        self.n_hmm_states = int(n_hmm_states)
        self.ma_window = int(ma_window)
        self.ema_alpha = float(ema_alpha)
        self.hmm_blend = float(hmm_blend)  # 0 = 纯 EMA；1 = 纯 HMM
        self.random_state = int(random_state)
        self._hmm_model = None  # 可选诊断

        # BOCPD 参数（Spec §2.4 规则4）
        self.bocpd_enabled = bool(bocpd_enabled)
        self.bocpd_hazard = float(bocpd_hazard)
        self.bocpd_trigger_p = float(bocpd_trigger_p)
        self.bocpd_volume_ratio_thr = float(bocpd_volume_ratio_thr)
        self.bocpd_gradual_days = int(bocpd_gradual_days)
        self.bocpd_daily_amount = float(bocpd_daily_amount)

    # ====================================================================
    # Public API
    # ====================================================================
    def transform(self,
                  level_raw: pd.Series,
                  trend_raw: pd.Series,
                  close: Optional[pd.Series] = None,
                  volume: Optional[pd.Series] = None) -> SmootherOutput:
        """输入 Level/Trend（已 clamp 过），输出时序平滑结果。

        可选 close/volume：当 bocpd_enabled=True 且同时传入时，计算 BOCPD 变点概率
        并对 Trend 做 5 日渐进调整（Spec §2.4 规则4）。不传则 bocpd_cp_prob 全 0
        （兼容旧调用方 transform(level_raw, trend_raw)）。
        """
        level_arr = np.asarray(level_raw, dtype=float)
        trend_arr = np.asarray(trend_raw, dtype=float)

        # step 1: 5 日滚动均值 → 观测矩阵 obs
        L_ma = pd.Series(level_arr).rolling(self.ma_window, min_periods=1).mean().values
        T_ma = pd.Series(trend_arr).rolling(self.ma_window, min_periods=1).mean().values
        obs = np.column_stack([L_ma, T_ma])
        obs = np.nan_to_num(obs, nan=0.0, posinf=0.0, neginf=0.0)

        # step 4 first (EMA 先生成，保证兜底)：纯 python ewm 无依赖
        ema_level = self._ewma(level_arr, self.ema_alpha)
        ema_trend = self._ewma(trend_arr, self.ema_alpha)

        # step 2 + 3: HMM
        hmm_states = self._fit_predict_hmm(obs)
        if hmm_states is None:
            # 训练失败 → Neutral 状态兜底
            hmm_states = np.ones(len(level_arr), dtype=int)
            blend = 0.0
        else:
            # 重映射状态语义
            hmm_states = _remap_states_by_level(hmm_states, L_ma, T_ma, self.n_hmm_states)
            blend = float(self.hmm_blend)

        # HMM-based smoothing: 状态 2(Bull) → shift up, 0(Bear) → shift down, 1 → 中性
        # 简单方式：HMM 态对应 (L_ma 与 T_ma 在该状态的 50 分位数)与 EMA 的加权
        hmm_L = np.empty_like(L_ma)
        hmm_T = np.empty_like(T_ma)
        for s in range(self.n_hmm_states):
            mask = hmm_states == s
            if mask.sum() > 0:
                hmm_L[mask] = np.quantile(L_ma[mask], 0.50)
                hmm_T[mask] = np.quantile(T_ma[mask], 0.50)
            else:
                hmm_L[mask] = L_ma[mask]
                hmm_T[mask] = T_ma[mask]

        # step 5: soft blend
        L_final = blend * hmm_L + (1.0 - blend) * ema_level
        T_final = blend * hmm_T + (1.0 - blend) * ema_trend
        # 最后一道 [-4, +4] 保险
        L_final = np.clip(L_final, -4.0, 4.0)
        T_final = np.clip(T_final, -4.0, 4.0)

        # step 6: BOCPD 变点检测 + 5 日渐进调整（Spec §2.4 规则4）
        # 仅当 bocpd_enabled=True 且同时传入 close/volume（等长）时启用；
        # 否则 bocpd_cp_prob 保持全 0（兼容 Phase 0 旧调用）
        if (self.bocpd_enabled and close is not None and volume is not None
                and len(close) == len(level_arr)):
            bocpd_probs = self._compute_bocpd_probs(close, volume)
            T_final = self._apply_bocpd_trend_adjustment(
                T_final, close, volume, bocpd_probs)
        else:
            bocpd_probs = np.zeros(len(level_arr), dtype=float)

        idx = level_raw.index
        return SmootherOutput(
            level_smooth=pd.Series(L_final, index=idx),
            trend_smooth=pd.Series(T_final, index=idx),
            hmm_state=pd.Series(hmm_states.astype(int), index=idx),
            ema_level=pd.Series(ema_level, index=idx),
            bocpd_cp_prob=pd.Series(bocpd_probs, index=idx),
        )

    # ====================================================================
    # 内部：HMM fit + predict (hmmlearn)，失败返回 None
    # ====================================================================
    def _fit_predict_hmm(self, obs: np.ndarray) -> Optional[np.ndarray]:
        try:
            from hmmlearn.hmm import GaussianHMM
        except ImportError:
            logger.warning("hmmlearn 未安装，跳过 HMM，仅使用 EMA")
            return None

        if len(obs) < self.n_hmm_states * 8:
            logger.debug("样本数过少，跳过 HMM 训练")
            return None

        try:
            model = GaussianHMM(
                n_components=self.n_hmm_states,
                covariance_type="diag",
                n_iter=80,
                random_state=self.random_state,
                tol=1e-3,
            )
            model.fit(obs)
            states = model.predict(obs)
            self._hmm_model = model
            return states
        except Exception as e:
            logger.warning(f"HMM 训练/解码失败，降级 EMA: {e}")
            return None

    # ====================================================================
    # 内部：纯 numpy EWMA（无 pandas 依赖；等价于 pandas ewm(com) 的 mean）
    # ====================================================================
    @staticmethod
    def _ewma(x: np.ndarray, alpha: float) -> np.ndarray:
        """指数加权平均：s[0]=x[0]; s[i]=alpha*x[i] + (1-alpha)*s[i-1]"""
        out = np.empty_like(x, dtype=float)
        if len(x) == 0:
            return out
        s = float(np.nan_to_num(x[0], nan=0.0))
        out[0] = s
        one_minus = 1.0 - alpha
        for i in range(1, len(x)):
            xi = float(np.nan_to_num(x[i], nan=0.0))
            s = alpha * xi + one_minus * s
            out[i] = s
        return out

    # ====================================================================
    # 内部：BOCPD 变点检测（简化实现：滚动 20 日 z-score + sigmoid）
    # 不依赖 bocd/ruptures/scipy，仅用 numpy/pandas。
    # 注：完整 Gaussian conjugate BOCPD 的 P(r=0) 受「r=0→1 增长项与变点项共享
    #   先验预测概率」约束，上界约为 0.5，无法稳定超过 Spec 的 0.7 触发阈值；
    #   故采用 Spec 允许的简化版本（z-score sigmoid），|z|>2 时 P>0.5。
    # ====================================================================
    _BOCPD_WINDOW = 20  # 滚动均值/标准差与量能基线共用窗口

    def _compute_bocpd_probs(self, close: pd.Series,
                             volume: pd.Series) -> np.ndarray:
        """计算变点概率序列（简化 BOCPD：滚动 z-score + sigmoid）。

        观测序列：close 的 1d log-return = np.log(close[i]/close[i-1])。
        对每个 return，用「前 _BOCPD_WINDOW 日的均值/标准差」计算 z-score：
            z = |ret - prior_mean| / prior_std
            cp_prob = sigmoid(z - 2)   # |z|>2 → P>0.5
        返回与 close 等长的概率数组（第 0 个点无 return，概率=0）。
        volume 参数保留接口一致性，变点检测本身只依赖收益序列。
        """
        close_arr = np.asarray(close, dtype=float)
        n = len(close_arr)
        if n < 2:
            return np.zeros(n, dtype=float)
        log_ret = np.log(close_arr[1:] / close_arr[:-1])
        log_ret = np.nan_to_num(log_ret, nan=0.0, posinf=0.0, neginf=0.0)

        # 截至前一日（shift(1)）的滚动均值/标准差，避免 lookahead
        prior = pd.Series(log_ret).shift(1)
        roll_mean = prior.rolling(self._BOCPD_WINDOW, min_periods=2).mean().values
        roll_std = prior.rolling(self._BOCPD_WINDOW, min_periods=2).std().values

        valid = (~np.isnan(roll_mean)) & (~np.isnan(roll_std)) & (roll_std > 1e-12)
        z = np.zeros(len(log_ret), dtype=float)
        z[valid] = np.abs((log_ret[valid] - roll_mean[valid]) / roll_std[valid])
        # 变点概率 = sigmoid(|z| - 2)
        cp = 1.0 / (1.0 + np.exp(-(z - 2.0)))
        cp[~valid] = 0.0

        probs = np.zeros(n, dtype=float)
        probs[1:] = cp
        return probs

    def _apply_bocpd_trend_adjustment(self, trend_smooth,
                                     close, volume,
                                     bocpd_probs) -> np.ndarray:
        """对 trend 应用 BOCPD 触发的 5 日渐进调整。

        规则（Spec §2.4 规则4）：
          - 当 bocpd_probs[i] > trigger_p 且 量比[i] ≥ volume_thr 时触发
          - sign = 未来 gradual_days 日收益方向（离线 batch 用 lookforward；
            未来不足 gradual_days 日时用已有日数）
          - 接下来 gradual_days 个交易日渐进累加 trend：
              第 1 日 +sign×amount，第 2 日 +sign×2×amount，… ，第 gradual_days 日 +sign×amount×gradual_days
            之后保持该累计偏移（避免单日冲击式跳变，合计 ±0.30）
        """
        trend = np.array(trend_smooth, dtype=float)
        close_arr = np.asarray(close, dtype=float)
        vol_arr = np.asarray(volume, dtype=float)
        n = len(trend)
        if n == 0:
            return trend

        for i in range(n):
            if bocpd_probs[i] <= self.bocpd_trigger_p:
                continue
            # 量能门槛：当日量 / 前 _BOCPD_WINDOW 日均量（不含当日，避免 lookahead）
            if i >= 1:
                lookback = vol_arr[max(0, i - self._BOCPD_WINDOW):i]
                baseline = (float(lookback.mean())
                            if lookback.size > 0 else float(vol_arr[i]))
            else:
                baseline = float(vol_arr[i]) if vol_arr[i] > 0 else 1.0
            vol_ratio = float(vol_arr[i]) / baseline if baseline > 0 else 0.0
            if vol_ratio < self.bocpd_volume_ratio_thr:
                continue
            # sign：未来 gradual_days 日收益方向（离线 batch）
            future_idx = min(i + self.bocpd_gradual_days, n - 1)
            if future_idx > i and close_arr[i] > 0:
                future_ret = close_arr[future_idx] / close_arr[i] - 1.0
                sign = 1.0 if future_ret > 0 else (-1.0 if future_ret < 0 else 0.0)
            else:
                sign = 0.0
            if sign == 0.0:
                continue
            # 渐进累计调整：i+1 日起逐日累加，ramp 到 amount×gradual_days 后保持
            #   第 d 日（d=1..gradual_days）累计偏移 = sign × amount × d
            #   d > gradual_days 后保持 sign × amount × gradual_days
            for j in range(i + 1, n):
                d = min(j - i, self.bocpd_gradual_days)
                trend[j] += sign * self.bocpd_daily_amount * d
        return np.clip(trend, -4.0, 4.0)
