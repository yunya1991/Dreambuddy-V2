"""PITD Phase 1: 运动学层 (Kinematics)

将K线序列视为质点运动轨迹，计算多周期运动学观测量：
- 位移 s(t) = ln(P(t)/P(t₀))
- 速度 v(t) = ds/dt
- 加速度 a(t) = dv/dt = d²s/dt²
- 加加速度 j(t) = da/dt = d³s/dt³

双周期嵌套：周线(W) + 日线(D)

输出12维ML特征，接入现有LightGBM管道。

物理意义检验：
- 上涨时 v > 0，下跌时 v < 0
- 加速上涨时 a > 0，减速上涨时 a < 0
- 趋势反转点 j 出现尖峰
- 大周期趋势强时 |v_W| > |v_D|，方向一致

文件: ml/pitd_kinematics_engineer.py
作者: PITD Phase 1
创建: 2026-07-19
"""

import numpy as np
import pandas as pd
from typing import List, Optional


class KinematicsEngineer:
    """运动学层特征工程

    将价格序列转化为物理运动学量（位移/速度/加速度/加加速度），
    支持多周期嵌套计算。

    用法:
        engineer = KinematicsEngineer()
        features = engineer.extract_series(prices)
        # 返回12维运动学特征DataFrame
    """

    # 12维运动学特征名
    FEATURE_NAMES: List[str] = [
        # 日线运动学 (3维)
        "kin_velocity_D",
        "kin_acceleration_D",
        "kin_jerk_D",
        # 周线运动学 (3维)
        "kin_velocity_W",
        "kin_acceleration_W",
        "kin_jerk_W",
        # 多周期关系 (6维)
        "kin_speed_ratio_WD",               # |v_W|/|v_D| 大小周期速度比
        "kin_accel_ratio_WD",               # |a_W|/|a_D| 大小周期加速度比
        "kin_velocity_sign_consistency",    # sign(v_W)==sign(v_D) 方向一致性
        "kin_accel_sign_consistency",       # sign(a_W)==sign(a_D) 加速度方向一致性
        "kin_jerk_abs_D",                   # |j_D| 日线突变强度
        "kin_jerk_abs_W",                   # |j_W| 周线突变强度
    ]

    def __init__(
        self,
        weekly_window: int = 7,
        velocity_ema_span: int = 5,
        accel_ema_span: int = 5,
        jerk_ema_span: int = 3,
    ):
        """初始化运动学特征工程

        参数:
            weekly_window: 周线窗口大小（天），默认7
            velocity_ema_span: 速度EMA平滑窗口，默认5
            accel_ema_span: 加速度EMA平滑窗口，默认5
            jerk_ema_span: 加加速度EMA平滑窗口，默认3（更敏感）
        """
        self.weekly_window = weekly_window
        self.velocity_ema_span = velocity_ema_span
        self.accel_ema_span = accel_ema_span
        self.jerk_ema_span = jerk_ema_span

    def get_feature_names(self) -> List[str]:
        """获取特征名列表"""
        return self.FEATURE_NAMES.copy()

    def _ema(self, series: pd.Series, span: int) -> pd.Series:
        """指数移动平均平滑"""
        return series.ewm(span=span, adjust=False, min_periods=1).mean()

    def _calc_kinematics_single_period(
        self,
        close: np.ndarray,
        period: int,
    ) -> tuple:
        """计算单周期运动学量

        参数:
            close: 收盘价数组
            period: 周期长度（日线=1，周线=7）

        返回:
            (velocity, acceleration, jerk) 三个数组
        """
        n = len(close)

        # 位移 s(t) = ln(P(t)/P(t-period))
        # 速度 v(t) = ds/dt = ln(P(t)/P(t-period)) / period
        # （除以period标准化为日均速度）
        velocity = np.zeros(n)
        for i in range(period, n):
            if close[i - period] > 0 and close[i] > 0:
                velocity[i] = np.log(close[i] / close[i - period]) / period

        # 加速度 a(t) = dv/dt = v(t) - v(t-period)
        # （用相同period差分，保持时间尺度一致）
        acceleration = np.zeros(n)
        for i in range(period * 2, n):
            acceleration[i] = velocity[i] - velocity[i - period]

        # 加加速度 j(t) = da/dt = a(t) - a(t-period)
        jerk = np.zeros(n)
        for i in range(period * 3, n):
            jerk[i] = acceleration[i] - acceleration[i - period]

        return velocity, acceleration, jerk

    def extract_series(self, prices: pd.DataFrame) -> pd.DataFrame:
        """批量计算整段历史的运动学特征

        参数:
            prices: 完整日线OHLCV，必须包含close列

        返回:
            DataFrame, index=prices.index, 列为12维运动学特征
        """
        n = len(prices)
        close = prices["close"].values
        result = pd.DataFrame(index=prices.index, columns=self.FEATURE_NAMES, dtype=float)

        # === 日线运动学（period=1）===
        v_D_raw, a_D_raw, j_D_raw = self._calc_kinematics_single_period(close, 1)

        # EMA平滑
        v_D = self._ema(pd.Series(v_D_raw, index=prices.index), self.velocity_ema_span).values
        a_D = self._ema(pd.Series(a_D_raw, index=prices.index), self.accel_ema_span).values
        j_D = self._ema(pd.Series(j_D_raw, index=prices.index), self.jerk_ema_span).values

        # === 周线运动学（period=7）===
        v_W_raw, a_W_raw, j_W_raw = self._calc_kinematics_single_period(close, self.weekly_window)

        v_W = self._ema(pd.Series(v_W_raw, index=prices.index), self.velocity_ema_span).values
        a_W = self._ema(pd.Series(a_W_raw, index=prices.index), self.accel_ema_span).values
        j_W = self._ema(pd.Series(j_W_raw, index=prices.index), self.jerk_ema_span).values

        # === 写入基础特征 ===
        result["kin_velocity_D"] = v_D
        result["kin_acceleration_D"] = a_D
        result["kin_jerk_D"] = j_D
        result["kin_velocity_W"] = v_W
        result["kin_acceleration_W"] = a_W
        result["kin_jerk_W"] = j_W

        # === 多周期关系特征 ===
        eps = 1e-10

        # 速度比 |v_W|/|v_D|
        speed_ratio = np.abs(v_W) / (np.abs(v_D) + eps)
        # 裁剪极端值
        speed_ratio = np.clip(speed_ratio, 0, 20)
        result["kin_speed_ratio_WD"] = speed_ratio

        # 加速度比 |a_W|/|a_D|
        accel_ratio = np.abs(a_W) / (np.abs(a_D) + eps)
        accel_ratio = np.clip(accel_ratio, 0, 20)
        result["kin_accel_ratio_WD"] = accel_ratio

        # 方向一致性
        result["kin_velocity_sign_consistency"] = (
            (np.sign(v_W) == np.sign(v_D)) & (np.sign(v_W) != 0)
        ).astype(float)
        result["kin_accel_sign_consistency"] = (
            (np.sign(a_W) == np.sign(a_D)) & (np.sign(a_W) != 0)
        ).astype(float)

        # 突变强度
        result["kin_jerk_abs_D"] = np.abs(j_D)
        result["kin_jerk_abs_W"] = np.abs(j_W)

        # 处理NaN和Inf
        result = result.fillna(0.0).replace([np.inf, -np.inf], 0.0)

        return result

    def extract(self, prices: pd.DataFrame) -> dict:
        """单时间点计算（返回最新值）

        参数:
            prices: 日线OHLCV（至少需要 period*3+5 条数据）

        返回:
            12维特征字典
        """
        feats = self.extract_series(prices)
        return feats.iloc[-1].to_dict()

    def physics_sanity_check(self, prices: pd.DataFrame) -> dict:
        """物理意义检验

        验证运动学量的物理意义是否合理

        返回:
            检验结果字典
        """
        feats = self.extract_series(prices)
        close = prices["close"].values

        # 计算价格变化方向
        price_change = np.diff(np.log(close))
        price_direction = np.sign(price_change)

        # 检验1: 上涨时v_D > 0
        v_D = feats["kin_velocity_D"].values[1:]
        aligned_direction = price_direction
        correct_v_sign = (np.sign(v_D) == aligned_direction).mean()

        # 检验2: 加速度在趋势加强时应与速度同号
        v_D_full = feats["kin_velocity_D"].values
        a_D = feats["kin_acceleration_D"].values
        # 趋势加强: |v|增大 → sign(a)==sign(v)
        trend_accel_mask = (np.sign(v_D_full) != 0) & (np.sign(a_D) != 0)
        correct_a_sign = (
            np.sign(v_D_full[trend_accel_mask]) == np.sign(a_D[trend_accel_mask])
        ).mean() if trend_accel_mask.sum() > 0 else 0.0

        # 检验3: 周线速度与日线速度方向一致率
        v_W = feats["kin_velocity_W"].values
        both_nonzero = (np.sign(v_D_full) != 0) & (np.sign(v_W) != 0)
        direction_consistency = (
            np.sign(v_D_full[both_nonzero]) == np.sign(v_W[both_nonzero])
        ).mean() if both_nonzero.sum() > 0 else 0.0

        # 检验4: jerk在趋势反转点是否有尖峰
        j_D = feats["kin_jerk_D"].values
        j_abs = np.abs(j_D)
        # 找价格反转点（方向变化）
        # price_direction 长度 = n-1，price_change 长度 = n-1
        n_total = len(close)
        direction_change = np.zeros(n_total, dtype=bool)
        # price_direction[1:] vs price_direction[:-1] → 长度 n-2
        if len(price_direction) >= 2:
            reversal_flags = price_direction[1:] != price_direction[:-1]
            direction_change[2:] = reversal_flags  # 对齐到原时间轴
        # price_change 长度 n-1，对齐到[1:]
        large_change_mask = np.zeros(n_total, dtype=bool)
        large_change_mask[1:] = np.abs(price_change) > np.std(price_change)
        direction_change = direction_change & large_change_mask

        if direction_change.sum() > 0 and direction_change.sum() < len(j_abs):
            j_at_reversal = j_abs[direction_change]
            j_at_normal = j_abs[~direction_change]
            jerk_ratio = j_at_reversal.mean() / (j_at_normal.mean() + 1e-10)
        else:
            jerk_ratio = 1.0

        return {
            "v_sign_correct_rate": float(correct_v_sign),
            "a_sign_correct_rate": float(correct_a_sign),
            "direction_consistency_WD": float(direction_consistency),
            "jerk_reversal_ratio": float(jerk_ratio),
            "v_D_range": (float(v_D.min()), float(v_D.max())),
            "a_D_range": (float(a_D.min()), float(a_D.max())),
            "j_D_range": (float(j_D.min()), float(j_D.max())),
            "v_W_range": (float(v_W.min()), float(v_W.max())),
            "a_W_range": (float(feats['kin_acceleration_W'].min()), float(feats['kin_acceleration_W'].max())),
            "j_W_range": (float(feats['kin_jerk_W'].min()), float(feats['kin_jerk_W'].max())),
            "verdict": "✅ 物理意义合理" if (
                correct_v_sign > 0.7 and direction_consistency > 0.5
            ) else "⚠️ 需检查",
        }
