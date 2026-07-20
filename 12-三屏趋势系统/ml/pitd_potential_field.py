"""PITD Phase 3: 势能场层 (Potential Field)

将价格空间建模为势能场 V(s)，计算阻力最小方向。

四类关键价位：
1. 均线密集区 (MA cluster): MA50/128/200汇聚点
2. 成交密集区 (Volume profile): 历史成交量分布峰值
3. 前高前低点 (Swing highs/lows): 20/50/100日结构高低点
4. 斐波那契位 (Fibonacci): 0.382/0.5/0.618回撤位

势能场：
  V(s) = Σ w_i × φ(s - s_i)
  φ(x) = exp(-x² / 2σ²)  （高斯核）

阻力最小方向 = -∇V(s) = -dV/ds

理论4验证：市场沿阻力最小方向运动（-∇V方向与未来价格运动方向一致率 > 50%）

文件: ml/pitd_potential_field.py
"""

import numpy as np
import pandas as pd
from typing import List, Tuple, Optional


class PotentialFieldEngineer:
    """势能场层特征工程

    用法:
        engineer = PotentialFieldEngineer()
        features = engineer.extract_series(prices)
    """

    FEATURE_NAMES: List[str] = [
        # 总势能场 (3维)
        "field_potential_total",       # 总势能 V_total(s)
        "field_gradient_total",        # 总势能梯度 dV/ds （正值=上涨阻力，负值=下跌阻力）
        "field_direction",             # 阻力最小方向 sign(-dV/ds)  (+1=向上, -1=向下)
        # 分量势能梯度 (4维)
        "field_gradient_ma",           # 均线分量梯度
        "field_gradient_volume",       # 成交密集区分量梯度
        "field_gradient_swing",        # 前高前低分量梯度
        "field_gradient_fib",          # 斐波那契分量梯度
        # 距离特征 (3维)
        "field_dist_to_nearest_min",   # 距最近势能极小点距离
        "field_nearest_min_potential", # 最近极小点势能值
        "field_potential_vs_avg",      # 当前势能 / 平均势能
        # 不对称性 (2维)
        "field_up_resistance",         # 上方阻力（积分上半部分）
        "field_down_support",          # 下方支撑（积分下半部分）
    ]

    def __init__(
        self,
        ma_periods: Optional[List[int]] = None,
        swing_lookbacks: Optional[List[int]] = None,
        fib_levels: Optional[List[float]] = None,
        sigma_pct: float = 0.02,
        volume_profile_bins: int = 50,
        volume_lookback: int = 200,
    ):
        """初始化势能场引擎

        参数:
            ma_periods: 均线周期列表，默认[20, 50, 128, 200]
            swing_lookbacks: 前高前低回看周期，默认[20, 50, 100]
            fib_levels: 斐波那契位，默认[0.236, 0.382, 0.5, 0.618, 0.786]
            sigma_pct: 高斯核σ（价格百分比），默认2%
            volume_profile_bins: 成交密集区分箱数，默认50
            volume_lookback: 成交密集区回看天数，默认200
        """
        self.ma_periods = ma_periods or [20, 50, 128, 200]
        self.swing_lookbacks = swing_lookbacks or [20, 50, 100]
        self.fib_levels = fib_levels or [0.236, 0.382, 0.5, 0.618, 0.786]
        self.sigma_pct = sigma_pct
        self.volume_profile_bins = volume_profile_bins
        self.volume_lookback = volume_lookback

    def get_feature_names(self) -> List[str]:
        return self.FEATURE_NAMES.copy()

    def _gaussian_kernel(self, x: np.ndarray, sigma: float) -> np.ndarray:
        """高斯核 φ(x) = exp(-x²/2σ²)"""
        return np.exp(-(x ** 2) / (2 * sigma ** 2))

    def _gaussian_derivative(self, x: np.ndarray, sigma: float) -> np.ndarray:
        """高斯核一阶导数 φ'(x) = -x/σ² × exp(-x²/2σ²)"""
        return -(x / (sigma ** 2)) * np.exp(-(x ** 2) / (2 * sigma ** 2))

    def _calc_ma_key_levels(self, prices: pd.DataFrame, i: int) -> List[Tuple[float, float]]:
        """计算均线关键价位（在第i天）

        返回: [(price, weight), ...]
        """
        close = prices["close"].values[: i + 1]
        levels = []
        for period in self.ma_periods:
            if i < period:
                continue
            ma_val = np.mean(close[-period:])
            # 权重：与价格的接近程度（越近权重越大）
            distance = abs(close[-1] - ma_val) / close[-1]
            weight = 1.0 / (1.0 + distance * 10)  # 距离10%权重减半
            levels.append((ma_val, weight))
        return levels

    def _calc_volume_key_levels(self, prices: pd.DataFrame, i: int) -> List[Tuple[float, float]]:
        """计算成交密集区关键价位（成交量分布峰值）

        返回: [(price, weight), ...]
        """
        if i < self.volume_lookback:
            start = 0
        else:
            start = i - self.volume_lookback + 1

        close_segment = prices["close"].values[start : i + 1]
        volume_segment = prices["volume"].values[start : i + 1]

        if len(close_segment) < 20:
            return []

        # 计算成交量分布（按价格分箱）
        price_min = np.min(close_segment)
        price_max = np.max(close_segment)
        if price_max <= price_min:
            return []

        # 分箱统计成交量
        bin_edges = np.linspace(price_min, price_max, self.volume_profile_bins + 1)
        bin_centers = (bin_edges[:-1] + bin_edges[1:]) / 2
        bin_volumes = np.zeros(self.volume_profile_bins)

        for j in range(len(close_segment)):
            price = close_segment[j]
            vol = volume_segment[j]
            bin_idx = int((price - price_min) / (price_max - price_min) * self.volume_profile_bins)
            bin_idx = min(bin_idx, self.volume_profile_bins - 1)
            bin_volumes[bin_idx] += vol

        # 找峰值（局部最大值）
        levels = []
        for b in range(1, self.volume_profile_bins - 1):
            if bin_volumes[b] > bin_volumes[b - 1] and bin_volumes[b] > bin_volumes[b + 1]:
                # 权重：峰值成交量占比
                if np.sum(bin_volumes) > 0:
                    weight = bin_volumes[b] / np.sum(bin_volumes) * 5  # 缩放
                    levels.append((float(bin_centers[b]), float(weight)))

        # 按权重排序，取前5个
        levels.sort(key=lambda x: x[1], reverse=True)
        return levels[:5]

    def _calc_swing_key_levels(self, prices: pd.DataFrame, i: int) -> List[Tuple[float, float]]:
        """计算前高前低关键价位

        返回: [(price, weight), ...]
        """
        high = prices["high"].values
        low = prices["low"].values
        close = prices["close"].values[i]
        levels = []

        for lookback in self.swing_lookbacks:
            if i < lookback:
                continue
            # 前高
            swing_high = np.max(high[i - lookback : i + 1])
            # 前低
            swing_low = np.min(low[i - lookback : i + 1])

            # 权重：与当前价格距离
            dist_high = abs(close - swing_high) / close
            dist_low = abs(close - swing_low) / close

            weight_high = 1.0 / (1.0 + dist_high * 5)
            weight_low = 1.0 / (1.0 + dist_low * 5)

            levels.append((swing_high, weight_high))
            levels.append((swing_low, weight_low))

        return levels

    def _calc_fib_key_levels(self, prices: pd.DataFrame, i: int) -> List[Tuple[float, float]]:
        """计算斐波那契回撤关键价位

        基于最近一段趋势的高低点计算回撤位。

        返回: [(price, weight), ...]
        """
        lookback = 200
        if i < lookback:
            start = 0
        else:
            start = i - lookback + 1

        high_segment = prices["high"].values[start : i + 1]
        low_segment = prices["low"].values[start : i + 1]

        if len(high_segment) < 20:
            return []

        # 找区间最高和最低
        high_max = np.max(high_segment)
        low_min = np.min(low_segment)
        current_price = prices["close"].values[i]

        # 确定趋势方向：如果当前接近高点，则是下降趋势回撤，反之则上涨趋势回撤
        range_total = high_max - low_min
        if range_total <= 0:
            return []

        # 计算斐波那契位
        levels = []
        for level in self.fib_levels:
            # 回撤位 = 高点 - (高点-低点) × level
            fib_price = high_max - range_total * level
            # 权重：与当前价格距离
            distance = abs(current_price - fib_price) / current_price
            weight = 1.0 / (1.0 + distance * 5)
            levels.append((fib_price, weight))

        return levels

    def _compute_potential(
        self,
        key_levels: List[Tuple[float, float]],
        current_price: float,
        sigma: float,
    ) -> Tuple[float, float]:
        """计算给定点的势能和梯度

        参数:
            key_levels: [(price, weight), ...] 关键价位列表
            current_price: 当前价格
            sigma: 高斯核宽度

        返回:
            (potential, gradient)  势能和梯度
        """
        if not key_levels:
            return 0.0, 0.0

        s = np.log(current_price)
        potential = 0.0
        gradient = 0.0

        for price, weight in key_levels:
            if price <= 0:
                continue
            s_i = np.log(price)
            dx = s - s_i  # 注意：梯度是对s求导
            potential += weight * self._gaussian_kernel(dx, sigma)
            # dV/ds = Σ w × φ'(dx)
            gradient += weight * self._gaussian_derivative(dx, sigma)

        return potential, gradient

    def _find_nearest_minimum(
        self,
        key_levels: List[Tuple[float, float]],
        current_price: float,
        sigma: float,
        search_range_pct: float = 0.2,
        n_points: int = 100,
    ) -> Tuple[float, float]:
        """找最近的势能极小点

        返回: (min_price, min_potential)
        """
        if not key_levels:
            return current_price, 0.0

        # 在当前价格±20%范围内搜索
        price_min = current_price * (1 - search_range_pct)
        price_max = current_price * (1 + search_range_pct)

        prices = np.exp(np.linspace(np.log(price_min), np.log(price_max), n_points))
        potentials = np.zeros(n_points)

        for idx, p in enumerate(prices):
            pot, _ = self._compute_potential(key_levels, p, sigma)
            potentials[idx] = pot

        # 找局部极小值
        min_idx = 0
        min_val = float("inf")
        for idx in range(1, n_points - 1):
            if potentials[idx] < potentials[idx - 1] and potentials[idx] < potentials[idx + 1]:
                if potentials[idx] < min_val:
                    min_val = potentials[idx]
                    min_idx = idx

        # 如果没找到局部极小，取全局最小
        if min_val == float("inf"):
            min_idx = np.argmin(potentials)
            min_val = potentials[min_idx]

        # 距离（对数距离）
        min_price = float(prices[min_idx])
        distance = abs(np.log(current_price) - np.log(min_price))

        return min_price, min_val

    def _compute_asymmetry(
        self,
        key_levels: List[Tuple[float, float]],
        current_price: float,
        sigma: float,
    ) -> Tuple[float, float]:
        """计算上下不对称性（上方阻力 vs 下方支撑）

        返回: (up_resistance, down_support)
        """
        if not key_levels:
            return 0.0, 0.0

        s = np.log(current_price)
        up_resistance = 0.0
        down_support = 0.0

        for price, weight in key_levels:
            if price <= 0:
                continue
            s_i = np.log(price)
            dx = s - s_i
            pot = weight * self._gaussian_kernel(dx, sigma)
            if s_i > s:  # 价位在上方（阻力）
                up_resistance += pot
            else:  # 价位在下方（支撑）
                down_support += pot

        return up_resistance, down_support

    def extract_series(self, prices: pd.DataFrame) -> pd.DataFrame:
        """批量计算势能场特征

        参数:
            prices: 日线OHLCV

        返回:
            DataFrame, 12维势能场特征
        """
        n = len(prices)
        result = pd.DataFrame(index=prices.index, columns=self.FEATURE_NAMES, dtype=float)

        close = prices["close"].values
        sigma_log = self.sigma_pct  # σ用对数价格的百分比（近似）

        for i in range(n):
            current_price = close[i]
            if current_price <= 0:
                continue

            # 获取四类关键价位
            ma_levels = self._calc_ma_key_levels(prices, i)
            vol_levels = self._calc_volume_key_levels(prices, i)
            swing_levels = self._calc_swing_key_levels(prices, i)
            fib_levels = self._calc_fib_key_levels(prices, i)

            # 合并所有关键价位
            all_levels = ma_levels + vol_levels + swing_levels + fib_levels

            # 计算总分量势能和梯度
            total_pot, total_grad = self._compute_potential(all_levels, current_price, sigma_log)

            # 各分量梯度
            _, ma_grad = self._compute_potential(ma_levels, current_price, sigma_log)
            _, vol_grad = self._compute_potential(vol_levels, current_price, sigma_log)
            _, swing_grad = self._compute_potential(swing_levels, current_price, sigma_log)
            _, fib_grad = self._compute_potential(fib_levels, current_price, sigma_log)

            # 阻力最小方向
            direction = 1.0 if total_grad < 0 else (-1.0 if total_grad > 0 else 0.0)

            # 最近极小点
            min_price, min_potential = self._find_nearest_minimum(
                all_levels, current_price, sigma_log
            )
            dist_to_min = abs(np.log(current_price) - np.log(min_price))

            # 势能vs平均
            avg_potential = 0.0
            if total_pot != 0 and len(all_levels) > 0:
                avg_potential = total_pot / len(all_levels)
            pot_vs_avg = total_pot / (avg_potential * 2 + 1e-10)  # 归一化

            # 上下不对称性
            up_res, down_sup = self._compute_asymmetry(all_levels, current_price, sigma_log)

            # 写入结果
            result.iloc[i] = {
                "field_potential_total": total_pot,
                "field_gradient_total": total_grad,
                "field_direction": direction,
                "field_gradient_ma": ma_grad,
                "field_gradient_volume": vol_grad,
                "field_gradient_swing": swing_grad,
                "field_gradient_fib": fib_grad,
                "field_dist_to_nearest_min": dist_to_min,
                "field_nearest_min_potential": min_potential,
                "field_potential_vs_avg": pot_vs_avg,
                "field_up_resistance": up_res,
                "field_down_support": down_sup,
            }

        # 处理NaN和Inf
        result = result.fillna(0.0).replace([np.inf, -np.inf], 0.0)
        return result

    def physics_sanity_check(self, prices: pd.DataFrame, future_days: int = 5) -> dict:
        """物理意义检验

        验证理论4：市场沿阻力最小方向运动
        - 阻力最小方向 = sign(-dV/ds)
        - 正确率 = 未来N日方向与阻力最小方向一致的比例
        """
        feats = self.extract_series(prices)
        close = prices["close"].values
        n = len(close)

        # 阻力最小方向
        direction = feats["field_direction"].values
        gradient = feats["field_gradient_total"].values

        # 未来N日价格方向
        future_return = np.zeros(n)
        for i in range(n - future_days):
            future_return[i] = (close[i + future_days] - close[i]) / close[i]
        future_direction = np.sign(future_return)

        # 方向一致率
        valid = (direction != 0) & (future_direction != 0)
        if valid.sum() > 0:
            direction_match = (direction[valid] == future_direction[valid]).mean()
        else:
            direction_match = 0.5

        # 梯度强度与未来收益的关系（梯度越负，未来涨幅越大）
        neg_grad_mask = (gradient < 0) & valid
        pos_grad_mask = (gradient > 0) & valid
        if neg_grad_mask.sum() > 0 and pos_grad_mask.sum() > 0:
            return_neg_grad = future_return[neg_grad_mask].mean()
            return_pos_grad = future_return[pos_grad_mask].mean()
        else:
            return_neg_grad = 0.0
            return_pos_grad = 0.0

        # 各分量方向正确率
        component_match = {}
        for comp in ["field_gradient_ma", "field_gradient_volume", "field_gradient_swing", "field_gradient_fib"]:
            comp_grad = feats[comp].values
            comp_dir = np.where(comp_grad < 0, 1.0, np.where(comp_grad > 0, -1.0, 0.0))
            comp_valid = (comp_dir != 0) & (future_direction != 0)
            if comp_valid.sum() > 0:
                component_match[comp] = float((comp_dir[comp_valid] == future_direction[comp_valid]).mean())
            else:
                component_match[comp] = 0.5

        # 数值范围
        pot_range = (float(feats["field_potential_total"].min()), float(feats["field_potential_total"].max()))
        grad_range = (float(feats["field_gradient_total"].min()), float(feats["field_gradient_total"].max()))

        verdict = "✅ 理论4验证通过（阻力最小方向正确率>52%）" if direction_match > 0.52 else (
            "🟡 接近验证" if direction_match > 0.48 else "❌ 未验证"
        )

        return {
            "direction_match_rate": float(direction_match),
            "future_days": future_days,
            "return_neg_gradient": float(return_neg_grad),
            "return_pos_gradient": float(return_pos_grad),
            "component_match_rates": component_match,
            "potential_range": pot_range,
            "gradient_range": grad_range,
            "up_resistance_mean": float(feats["field_up_resistance"].mean()),
            "down_support_mean": float(feats["field_down_support"].mean()),
            "verdict": verdict,
        }
