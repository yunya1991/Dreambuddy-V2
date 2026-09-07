"""力向量计算器 —— 五维统计 + Kalman 平滑。

纯 numpy 实现，不依赖 filterpy。所有方法 FAIL-OPEN（异常返回中性默认值）。
对应 Spec §三 五维统计 / §四 Kalman 平滑。
"""
from __future__ import annotations

import os as _os
import sys as _sys

# ============================================================
# 注入「9-基本面分析」到 sys.path（engines.* 导入前置）
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

from force_vector.models import ForceVector
from force_vector.adapters import LeastResistanceAdapter, SignalEngineAdapter


class ForceVectorCalculator:
    """五维力向量计算器。

    五维：道(dao) / 天(tian) / 地(di) / 将(jiang) / 法(fa)。
    每维返回 (direction, magnitude)；compute_all 聚合为 ForceVector 字典。
    """

    def __init__(self, signal_engine=None):
        self.lr_adapter = LeastResistanceAdapter()
        self.signal_engine = signal_engine
        self.se_adapter = SignalEngineAdapter()

    # ============================================================
    # 道维度：滚动 Z-score + OLS 斜率
    # ============================================================
    def compute_dao_dimension(self, data: list) -> tuple:
        """道维度：滚动 Z-score + OLS 斜率。

        direction = sign(OLS斜率) * min(1, |Z|/2)
        magnitude = |Z| / 2
        返回 (direction, magnitude)
        """
        try:
            arr = np.asarray(data, dtype=float)
            n = len(arr)
            if n < 2:
                return 0.0, 0.0
            mu = arr.mean()
            sigma = arr.std(ddof=1)
            z = (arr[-1] - mu) / sigma if sigma > 0 else 0.0
            # OLS 斜率：拟合 y = a + b*t
            t = np.arange(n, dtype=float)
            t_mean = t.mean()
            denom = np.sum((t - t_mean) ** 2)
            slope = np.sum((t - t_mean) * (arr - mu)) / denom if denom > 0 else 0.0
            direction = float(np.sign(slope)) * min(1.0, abs(z) / 2.0)
            magnitude = min(2.0, abs(z) / 2.0)  # 限制在 [0, 2]
            return float(direction), float(magnitude)
        except Exception:
            return 0.0, 0.0

    # ============================================================
    # 天维度：条件期望值 + 分位数
    # ============================================================
    def compute_tian_dimension(self, data: list) -> tuple:
        """天维度：条件期望值 + 分位数。

        条件期望：样本均值（简化）；分位数：末值在样本中的百分位排名。
        direction = sign(末值 - 均值) * (2 * |分位数 - 0.5|)
        magnitude = 2 * |分位数 - 0.5|
        返回 (direction, magnitude)
        """
        try:
            arr = np.asarray(data, dtype=float)
            n = len(arr)
            if n < 2:
                return 0.0, 0.0
            last = arr[-1]
            cond_exp = arr.mean()  # 条件期望（简化为全样本均值）
            percentile = float(np.mean(arr <= last))  # [0, 1]
            dev = (percentile - 0.5) * 2.0  # [-1, 1]
            sign = 1.0 if last >= cond_exp else -1.0
            direction = max(-1.0, min(1.0, sign * abs(dev)))
            magnitude = abs(dev)
            return float(direction), float(magnitude)
        except Exception:
            return 0.0, 0.0

    # ============================================================
    # 地维度：百分位排名 + MA一致性
    # ============================================================
    def compute_di_dimension(self, data: list) -> tuple:
        """地维度：百分位排名 + MA一致性。

        MA一致性：短期MA vs 长期MA 的方向。
        direction = sign(MA_short - MA_long) * (2 * |分位数 - 0.5|)
        magnitude = 2 * |分位数 - 0.5|
        返回 (direction, magnitude)
        """
        try:
            arr = np.asarray(data, dtype=float)
            n = len(arr)
            if n < 2:
                return 0.0, 0.0
            last = arr[-1]
            percentile = float(np.mean(arr <= last))  # [0, 1]
            dev = (percentile - 0.5) * 2.0  # [-1, 1]
            # MA一致性：短期窗口均值 vs 全样本均值
            short_win = max(1, n // 4)
            ma_short = arr[-short_win:].mean()
            ma_long = arr.mean()
            sign = 1.0 if ma_short >= ma_long else -1.0
            direction = max(-1.0, min(1.0, sign * abs(dev)))
            magnitude = abs(dev)
            return float(direction), float(magnitude)
        except Exception:
            return 0.0, 0.0

    # ============================================================
    # 将维度：滚动 Sharpe + 偏度
    # ============================================================
    def compute_jiang_dimension(self, data: list) -> tuple:
        """将维度：滚动 Sharpe + 偏度。

        Sharpe = 均值 / 标准差；偏度 = 三阶标准化矩。
        direction = tanh(Sharpe)
        magnitude = |偏度|（偏度为0时回退 |tanh(Sharpe)|）
        返回 (direction, magnitude)
        """
        try:
            arr = np.asarray(data, dtype=float)
            n = len(arr)
            if n < 3:
                return 0.0, 0.0
            mu = arr.mean()
            sigma = arr.std(ddof=1)
            sharpe = mu / sigma if sigma > 0 else 0.0
            skew = float(np.mean(((arr - mu) / sigma) ** 3)) if sigma > 0 else 0.0
            direction = max(-1.0, min(1.0, float(np.tanh(sharpe))))
            magnitude = abs(skew)
            if magnitude < 1e-9:  # 偏度≈0 时回退
                magnitude = abs(float(np.tanh(sharpe)))
            return direction, float(magnitude)
        except Exception:
            return 0.0, 0.0

    # ============================================================
    # 法维度：IC + IR（简化版）
    # ============================================================
    def compute_fa_dimension(self, data: list) -> tuple:
        """法维度：IC + IR（简化版）。

        IC：当前值与滞后一阶的线性相关（趋势一致性）。
        IR：一阶差分均值 / 标准差。
        无策略数据时用数据自身趋势作代理。
        direction = sign(趋势) * min(1, |IC|)
        magnitude = |IC|（IC≈0 时回退 |tanh(IR)|）
        返回 (direction, magnitude)
        """
        try:
            arr = np.asarray(data, dtype=float)
            n = len(arr)
            if n < 3:
                return 0.0, 0.0
            # IC：滞后一阶相关
            x = arr[:-1]
            y = arr[1:]
            if len(x) >= 2 and x.std() > 0 and y.std() > 0:
                ic = float(np.corrcoef(x, y)[0, 1])
            else:
                ic = 0.0
            if np.isnan(ic):
                ic = 0.0
            # IR：差分均值/标准差
            rets = np.diff(arr)
            if len(rets) >= 2 and rets.std(ddof=1) > 0:
                ir = float(rets.mean() / rets.std(ddof=1))
            else:
                ir = 0.0
            trend_sign = 1.0 if arr[-1] >= arr[0] else -1.0
            direction = max(-1.0, min(1.0, trend_sign * min(1.0, abs(ic))))
            magnitude = abs(ic)
            if magnitude < 1e-9:  # IC≈0 时回退
                magnitude = abs(float(np.tanh(ir)))
            return direction, float(magnitude)
        except Exception:
            return 0.0, 0.0

    # ============================================================
    # Kalman 平滑（纯 numpy 实现）
    # ============================================================
    def kalman_smooth(self, directions: list, magnitudes: list = None) -> tuple:
        """Kalman Filter 平滑（numpy 实现，不依赖 filterpy）。

        状态: x = [direction, direction_velocity]
        观测: z = [raw_direction]
        状态转移: F = [[1, dt], [0, 1]]
        观测矩阵: H = [[1, 0]]
        过程噪声: Q = diag(0.001, 0.0001)
        观测噪声: R = [σ²_raw]
        返回 (kalman_directions, kalman_magnitudes)
        """
        try:
            arr = np.asarray(directions, dtype=float)
            n = len(arr)
            if n == 0:
                return [], (None if magnitudes is None else [])
            dt = 1.0
            F = np.array([[1.0, dt], [0.0, 1.0]])
            H = np.array([[1.0, 0.0]])
            Q = np.diag([0.001, 0.0001])
            # 观测噪声 R = σ²_raw（样本不足时给一个合理下限，避免除零/无平滑）
            sigma = float(np.std(arr)) if n > 1 else 0.1
            R = np.array([[max(sigma ** 2, 1e-4)]])
            # 初始状态与协方差
            # 速度维度初始协方差设小（无先验理由假定存在显著速度）：
            # 否则 velocity 不确定度会经由 F 注入 P_pred[0,0]，导致增益偏高、
            # 单日跳变抑制不足（TC3）。位置维度初始协方差保留较大以快速收敛。
            x = np.array([[0.0], [0.0]])
            P = np.diag([1.0, 0.001])
            I2 = np.eye(2)
            kalman_dirs = []
            for z in arr:
                # Predict
                x_pred = F @ x
                P_pred = F @ P @ F.T + Q
                # Update
                y_innov = np.array([[float(z)]]) - H @ x_pred
                S = H @ P_pred @ H.T + R
                K = P_pred @ H.T @ np.linalg.inv(S)
                x = x_pred + K @ y_innov
                P = (I2 - K @ H) @ P_pred
                kalman_dirs.append(float(x[0, 0]))
            # 平滑 magnitudes（若提供）
            if magnitudes is None:
                return kalman_dirs, None
            kalman_mags = self._kalman_smooth_1d(magnitudes)
            return kalman_dirs, kalman_mags
        except Exception:
            return list(directions), (list(magnitudes) if magnitudes is not None else None)

    def _kalman_smooth_1d(self, series: list) -> list:
        """一维 Kalman 平滑（用于 magnitude）。纯 numpy，FAIL-OPEN。"""
        try:
            arr = np.asarray(series, dtype=float)
            n = len(arr)
            if n == 0:
                return []
            sigma = float(np.std(arr)) if n > 1 else 0.1
            R = np.array([[max(sigma ** 2, 1e-4)]])
            Q = np.array([[0.001]])
            x = np.array([[0.0]])
            P = np.array([[1.0]])
            F = np.array([[1.0]])
            H = np.array([[1.0]])
            out = []
            for z in arr:
                x_pred = F @ x
                P_pred = F @ P @ F.T + Q
                y_innov = np.array([[float(z)]]) - H @ x_pred
                S = H @ P_pred @ H.T + R
                K = P_pred @ H.T @ np.linalg.inv(S)
                x = x_pred + K @ y_innov
                P = (np.eye(1) - K @ H) @ P_pred
                out.append(float(x[0, 0]))
            return out
        except Exception:
            return list(series)

    # ============================================================
    # 聚合：计算全部五维力向量
    # ============================================================
    def compute_all(self, dao_data=None, tian_data=None, di_data=None,
                    jiang_data=None, fa_data=None) -> dict:
        """计算全部五维力向量。

        FAIL-OPEN: 样本不足（<7天）→ return None。
        返回 {dimension: ForceVector}。
        """
        try:
            data_map = {
                "dao": dao_data, "tian": tian_data, "di": di_data,
                "jiang": jiang_data, "fa": fa_data,
            }
            # FAIL-OPEN: 任一维度样本不足 (<7天) → return None
            for data in data_map.values():
                if data is None or len(data) < 7:
                    return None
            # 逐维计算 (direction, magnitude)
            dims_order = ["dao", "tian", "di", "jiang", "fa"]
            raw_dirs = {}
            raw_mags = {}
            for dim in dims_order:
                method = getattr(self, f"compute_{dim}_dimension")
                direction, magnitude = method(data_map[dim])
                raw_dirs[dim] = direction
                raw_mags[dim] = magnitude
            # Kalman 平滑（五维作为序列一起平滑）
            dirs_list = [raw_dirs[d] for d in dims_order]
            mags_list = [raw_mags[d] for d in dims_order]
            kalman_dirs, kalman_mags = self.kalman_smooth(dirs_list, mags_list)
            kalman_dir_map = dict(zip(dims_order, kalman_dirs))
            kalman_mag_map = dict(zip(dims_order, kalman_mags)) if kalman_mags else {}
            # 自适应权重：按 |magnitude| 分配；dominant：最大 magnitude 维度
            total_mag = sum(abs(raw_mags[d]) for d in dims_order)
            max_dim = max(dims_order, key=lambda d: abs(raw_mags[d]))
            result = {}
            for dim in dims_order:
                magnitude = abs(raw_mags[dim])
                weight = magnitude / total_mag if total_mag > 0 else 0.2
                # 置信度：若有 signal_engine 则用中性置信度做贝叶斯（FAIL-OPEN）
                confidence = 0.5
                fv = ForceVector(
                    dimension=dim,
                    direction=raw_dirs[dim],
                    magnitude=magnitude,
                    confidence=confidence,
                    velocity=0.0,
                    acceleration=0.0,
                    kalman_direction=kalman_dir_map.get(dim, raw_dirs[dim]),
                    kalman_magnitude=kalman_mag_map.get(dim, magnitude),
                    dominant=(dim == max_dim),
                    weight=weight,
                )
                result[dim] = fv
            return result
        except Exception:
            return None
