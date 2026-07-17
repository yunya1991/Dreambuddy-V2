"""最小阻力三维特征工程

基于三屏趋势算法内核：时间三维 × 五维阻力 → 最小阻力三维模型(D/V/A)

特征维度：
1. 五维阻力特征 (price/volume/momentum/trend/fundamental)
2. 三维动态特征 (direction/velocity/acceleration)
3. 双向驱动特征 (trend_strength/trend_duration/drive_mode)
4. 量变积累特征 (accumulation_stage/accumulation_strength)
5. 多周期层级特征 (周-日-小周期阻力差、一致性)
6. 基本面特征 (screen1六维 + 9-基本面信号/情绪)

参考：
- 最小阻力方向引擎 (core/least_resistance.py)
- 微软 QLib 特征工程最佳实践
- LightGBM 表格数据特征处理
"""

from typing import List, Dict, Optional, Tuple, Any
import pandas as pd
import numpy as np
import sys, os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from core.least_resistance import (
    compute_least_resistance,
    compute_least_resistance_3d,
    calc_trend_strength,
)
from ml.fundamental_adapter import FundamentalFeatureAdapter
from ml.philosophy_feature_engineer import PhilosophyFeatureEngineer


def _safe_float(val, default=0.0) -> float:
    """安全转换为 float"""
    try:
        if val is None or pd.isna(val):
            return default
        return float(val)
    except (ValueError, TypeError):
        return default


class LeastResistanceFeatureEngineer:
    """最小阻力三维特征工程

    将三屏趋势算法的输出转化为结构化特征向量，供 ML 模型训练和预测。

    特征架构：
    ┌─────────────────────────────────────────────────────┐
    │  时间三维 × 五维阻力 → 最小阻力三维模型 → 特征向量    │
    ├──────────┬──────────┬──────────┬────────────────────┤
    │  周线屏  │  日线屏  │ 小周期屏 │  跨周期交互特征      │
    └──────────┴──────────┴──────────┴────────────────────┘
    """

    def __init__(
        self,
        lookback_windows: Optional[List[int]] = None,
        enable_fundamental: bool = True,
        enable_philosophy: bool = True,
        symbol: str = "BTC",
        btc_daily_df: Optional[pd.DataFrame] = None,
    ):
        """
        参数:
            lookback_windows: 历史窗口列表，用于提取时间序列特征
                             默认 [1, 3, 5, 10, 20]
            enable_fundamental: 是否启用基本面特征（screen1 + 9-基本面）
            enable_philosophy: 是否启用哲学贡献特征（BTC/小币分化、左侧抄底、分层仓位、双牛过滤）
            symbol: 当前币种代码（用于BTC/小币分化判断）
            btc_daily_df: BTC日线数据（小币需要，用于BTC regime计算）
        """
        self.lookback_windows = lookback_windows or [1, 3, 5, 10, 20]
        self.enable_fundamental = enable_fundamental
        self.enable_philosophy = enable_philosophy
        self.symbol = symbol
        self.btc_daily_df = btc_daily_df
        self.feature_names: List[str] = []
        self._fund_adapter = FundamentalFeatureAdapter() if enable_fundamental else None
        self._philosophy_engineer = PhilosophyFeatureEngineer() if enable_philosophy else None

    def create_features(
        self,
        weekly_df: pd.DataFrame,
        daily_df: pd.DataFrame,
        small_df: Optional[pd.DataFrame] = None,
        fundamental_data: Optional[Dict] = None,
        label_lookahead: int = 7,
    ) -> pd.DataFrame:
        """从三屏数据提取最小阻力三维特征

        参数:
            weekly_df: 周线 OHLCV 数据
            daily_df: 日线 OHLCV 数据
            small_df: 小周期 OHLCV 数据（可选，4H 或 1H）
            fundamental_data: 基本面数据（可选）
            label_lookahead: 标签前瞻期（天），用于生成训练标签

        返回:
            DataFrame: index=日线时间，包含所有特征 + label 列
        """
        if len(daily_df) < 60:
            raise ValueError(f"日线数据不足，至少需要 60 根K线，当前 {len(daily_df)} 根")

        n_daily = len(daily_df)
        result = pd.DataFrame(index=daily_df.index)

        feature_cols = []

        # ===== 1. 逐行计算最小阻力特征 =====
        lr_features = []
        weekly_lr_history = []
        daily_lr_history = []

        # 预热窗口：至少需要 30 根日线 + 30 根周线
        warmup = 30

        for i in range(warmup, n_daily):
            daily_slice = daily_df.iloc[:i + 1].copy()

            # 对齐周线数据：到第 i 根日线对应的周线
            last_daily_date = daily_df.index[i]
            weekly_slice = weekly_df[weekly_df.index <= last_daily_date].copy()

            if len(weekly_slice) < 30:
                lr_features.append({})
                weekly_lr_history.append(None)
                daily_lr_history.append(None)
                continue

            # 计算日级最小阻力
            try:
                daily_lr = compute_least_resistance(daily_slice, fundamental_data)
            except Exception:
                daily_lr = {"direction": 0, "confidence": 0, "resistance": {}}

            # 计算周级最小阻力
            try:
                weekly_lr = compute_least_resistance(weekly_slice, fundamental_data)
            except Exception:
                weekly_lr = {"direction": 0, "confidence": 0, "resistance": {}}

            daily_lr_history.append(daily_lr)
            weekly_lr_history.append(weekly_lr)

            # 提取当前行的特征
            feat = self._extract_lr_features(
                daily_lr, weekly_lr,
                daily_lr_history, weekly_lr_history,
            )
            lr_features.append(feat)

        # 前 warmup 行填充 NaN
        for i in range(warmup):
            lr_features.insert(0, {})

        # 转为 DataFrame
        for i, feat in enumerate(lr_features):
            for k, v in feat.items():
                if k not in result.columns:
                    result[k] = np.nan
                    feature_cols.append(k)
                result.iloc[i, result.columns.get_loc(k)] = v

        # ===== 2. 基本面特征（如果提供）=====
        if self.enable_fundamental and fundamental_data:
            try:
                fund_feats = self._extract_fundamental_features(
                    fundamental_data, n_daily, daily_df.index
                )
                for col in fund_feats.columns:
                    result[col] = fund_feats[col].values
                    if col not in feature_cols:
                        feature_cols.append(col)
            except Exception as e:
                print(f"  [WARN] 基本面特征提取失败: {e}")

        # ===== 3. 哲学贡献特征（v2策略哲学提取）=====
        if self.enable_philosophy and self._philosophy_engineer:
            try:
                philo_feats = self._philosophy_engineer.extract_series(
                    prices=daily_df,
                    symbol=self.symbol,
                    btc_prices=self.btc_daily_df,
                )
                for col in philo_feats.columns:
                    result[col] = philo_feats[col].values
                    if col not in feature_cols:
                        feature_cols.append(col)
            except Exception as e:
                print(f"  [WARN] 哲学贡献特征提取失败: {e}")

        # ===== 4. 标签生成（仅训练时需要）=====
        if label_lookahead > 0:
            close = daily_df["close"]
            future_return = close.shift(-label_lookahead) / close - 1.0
            result["label_future_return"] = future_return
            result["label_direction"] = (future_return > 0).astype(int)
            result.loc[future_return.isna(), "label_direction"] = np.nan

        self.feature_names = [c for c in result.columns if not c.startswith("label_")]
        return result

    def _extract_lr_features(
        self,
        daily_lr: Dict,
        weekly_lr: Dict,
        daily_history: List[Dict],
        weekly_history: List[Dict],
    ) -> Dict[str, float]:
        """从单个时间点的最小阻力结果提取特征

        返回:
            特征字典，key 为特征名，value 为 float
        """
        feats = {}

        # === 1. 五维阻力特征（日线）===
        daily_resistance = daily_lr.get("dimensions", {})
        for dim in ["price", "volume", "momentum", "trend", "fundamental"]:
            key = f"daily_res_{dim}"
            feats[key] = _safe_float(daily_resistance.get(dim, {}).get("resistance_diff", 0))

        # 多空阻力差（使用 resistance_diff 数值，非 direction 字符串）
        feats["daily_res_diff"] = _safe_float(daily_lr.get("resistance_diff", 0))
        feats["daily_confidence"] = _safe_float(daily_lr.get("confidence", 0))

        # === 2. 五维阻力特征（周线）===
        weekly_resistance = weekly_lr.get("dimensions", {})
        for dim in ["price", "volume", "momentum", "trend", "fundamental"]:
            key = f"weekly_res_{dim}"
            feats[key] = _safe_float(weekly_resistance.get(dim, {}).get("resistance_diff", 0))

        feats["weekly_res_diff"] = _safe_float(weekly_lr.get("resistance_diff", 0))
        feats["weekly_confidence"] = _safe_float(weekly_lr.get("confidence", 0))

        # === 3. 跨周期一致性特征 ===
        # 方向一致性（使用 resistance_diff 数值）
        daily_dir = _safe_float(daily_lr.get("resistance_diff", 0))
        weekly_dir = _safe_float(weekly_lr.get("resistance_diff", 0))
        feats["cross_dir_consistency"] = 1.0 if daily_dir * weekly_dir > 0 else (
            -1.0 if daily_dir * weekly_dir < 0 else 0.0
        )
        feats["cross_dir_diff"] = daily_dir - weekly_dir
        feats["cross_conf_ratio"] = (
            _safe_float(daily_lr.get("confidence", 0)) /
            max(_safe_float(weekly_lr.get("confidence", 0.01)), 0.01)
        )

        # 阻力维度差异（哪一维度在周/日之间分歧最大）
        for dim in ["price", "volume", "momentum", "trend", "fundamental"]:
            d_val = _safe_float(daily_resistance.get(dim, {}).get("resistance_diff", 0))
            w_val = _safe_float(weekly_resistance.get(dim, {}).get("resistance_diff", 0))
            feats[f"cross_{dim}_diff"] = d_val - w_val

        # === 4. 历史变化特征（速度、加速度近似）===
        # 从 daily_history 中提取（使用 resistance_diff 数值）
        valid_history = [h for h in daily_history if h and h.get("resistance_diff") is not None]

        if len(valid_history) >= 2:
            # 阻力差的变化率（速度）
            current_diff = _safe_float(valid_history[-1].get("resistance_diff", 0))
            prev_diff = _safe_float(valid_history[-2].get("resistance_diff", 0))
            feats["daily_velocity"] = current_diff - prev_diff

            # 置信度变化率
            current_conf = _safe_float(valid_history[-1].get("confidence", 0))
            prev_conf = _safe_float(valid_history[-2].get("confidence", 0))
            feats["daily_conf_velocity"] = current_conf - prev_conf

        if len(valid_history) >= 3:
            # 加速度
            v1 = _safe_float(valid_history[-1].get("resistance_diff", 0)) - _safe_float(valid_history[-2].get("resistance_diff", 0))
            v0 = _safe_float(valid_history[-2].get("resistance_diff", 0)) - _safe_float(valid_history[-3].get("resistance_diff", 0))
            feats["daily_acceleration"] = v1 - v0

        # 多窗口统计
        for window in self.lookback_windows:
            if len(valid_history) >= window:
                window_data = [_safe_float(h.get("resistance_diff", 0)) for h in valid_history[-window:]]
                feats[f"daily_dir_mean_{window}"] = float(np.mean(window_data))
                feats[f"daily_dir_std_{window}"] = float(np.std(window_data))

                conf_data = [_safe_float(h.get("confidence", 0)) for h in valid_history[-window:]]
                feats[f"daily_conf_mean_{window}"] = float(np.mean(conf_data))

                # 趋势斜率
                if window >= 2:
                    x = np.arange(window)
                    y = np.array(window_data)
                    slope = np.polyfit(x, y, 1)[0]
                    feats[f"daily_dir_slope_{window}"] = float(slope)

        # 周线历史变化
        valid_weekly = [h for h in weekly_history if h and h.get("resistance_diff") is not None]
        if len(valid_weekly) >= 2:
            w_current = _safe_float(valid_weekly[-1].get("resistance_diff", 0))
            w_prev = _safe_float(valid_weekly[-2].get("resistance_diff", 0))
            feats["weekly_velocity"] = w_current - w_prev

        if len(valid_weekly) >= 3:
            v1 = _safe_float(valid_weekly[-1].get("resistance_diff", 0)) - _safe_float(valid_weekly[-2].get("resistance_diff", 0))
            v0 = _safe_float(valid_weekly[-2].get("resistance_diff", 0)) - _safe_float(valid_weekly[-3].get("resistance_diff", 0))
            feats["weekly_acceleration"] = v1 - v0

        for window in [1, 3, 5, 10]:
            if len(valid_weekly) >= window:
                w_data = [_safe_float(h.get("resistance_diff", 0)) for h in valid_weekly[-window:]]
                feats[f"weekly_dir_mean_{window}"] = float(np.mean(w_data))

        # === 5. 趋势强度估计 ===
        try:
            trend_strength = calc_trend_strength(
                weekly_dir, 0, 0,
                "LONG" if weekly_dir > 0 else ("SHORT" if weekly_dir < 0 else "NEUTRAL")
            )
            feats["trend_strength_est"] = float(trend_strength)
        except Exception:
            feats["trend_strength_est"] = 0.0

        # 阻力维度贡献度（哪一维度主导当前方向）
        res_vals = [_safe_float(daily_resistance.get(d, {}).get("resistance_diff", 0)) for d in
                    ["price", "volume", "momentum", "trend", "fundamental"]]
        if any(abs(v) > 0.001 for v in res_vals):
            max_dim_idx = int(np.argmax([abs(v) for v in res_vals]))
            feats["dominant_res_dim"] = float(max_dim_idx)
        else:
            feats["dominant_res_dim"] = -1.0

        return feats

    def get_feature_names(self) -> List[str]:
        """获取特征名列表"""
        return self.feature_names.copy()

    def _extract_fundamental_features(
        self,
        fundamental_data: Dict[str, Any],
        n_daily: int,
        daily_index: pd.Index,
    ) -> pd.DataFrame:
        """提取基本面特征并对齐到日线

        支持的 fundamental_data 格式：
        1. {"screen1": {...}, "fundamental_9": {...}}  单点数据
        2. {"screen1_history": [{date, data}, ...]}    历史序列
        3. 混合格式

        参数:
            fundamental_data: 基本面数据（多种格式）
            n_daily: 日线长度
            daily_index: 日线索引

        返回:
            DataFrame，index=daily_index，列为基本面特征
        """
        result = pd.DataFrame(index=daily_index)

        if not self._fund_adapter:
            return result

        # 处理 screen1 数据
        screen1_data = fundamental_data.get("screen1")
        if screen1_data and isinstance(screen1_data, dict):
            # 单点数据：直接广播到所有行
            feats = self._fund_adapter.adapt_screen1(screen1_data)
            for k, v in feats.items():
                result[k] = v

        # 处理 screen1 历史数据
        screen1_history = fundamental_data.get("screen1_history")
        if screen1_history and isinstance(screen1_history, list):
            self._apply_history_features(
                result, screen1_history, "screen1", daily_index
            )

        # 处理 9-基本面 数据
        fund9_data = fundamental_data.get("fundamental_9")
        if fund9_data and isinstance(fund9_data, dict):
            feats = self._fund_adapter.adapt_fundamental_9(fund9_data)
            for k, v in feats.items():
                result[k] = v

        # 处理 9-基本面 历史数据
        fund9_history = fundamental_data.get("fundamental_9_history")
        if fund9_history and isinstance(fund9_history, list):
            self._apply_history_features(
                result, fund9_history, "fundamental_9", daily_index
            )

        # 兼容旧格式：直接传入的基本面数据
        if not screen1_data and not fund9_data and not screen1_history and not fund9_history:
            # 尝试直接适配
            feats = self._fund_adapter.adapt_all(
                screen1_data=fundamental_data if "dimensions" in fundamental_data else None,
                fundamental_9_data=fundamental_data if "resistance_3d" in fundamental_data else None,
            )
            if feats:
                for k, v in feats.items():
                    result[k] = v

        return result

    def _apply_history_features(
        self,
        result: pd.DataFrame,
        history_data: List[Dict],
        source: str,
        daily_index: pd.Index,
    ) -> None:
        """将历史基本面数据应用到 result DataFrame

        history_data 格式: [{"date": "2026-01-01", "data": {...}}, ...]
        """
        if not history_data:
            return

        # 按日期排序
        sorted_history = sorted(
            history_data,
            key=lambda x: x.get("date", x.get("dt", ""))
        )

        # 逐条应用（前向填充）
        last_feats = None
        hist_idx = 0

        for i, dt in enumerate(daily_index):
            date_str = str(dt.date()) if hasattr(dt, 'date') else str(dt)[:10]

            # 检查是否有新的历史数据点
            while hist_idx < len(sorted_history):
                item = sorted_history[hist_idx]
                item_date = str(item.get("date", item.get("dt", "")))[:10]
                if item_date <= date_str:
                    data = item.get("data", item)
                    if source == "screen1":
                        last_feats = self._fund_adapter.adapt_screen1(data)
                    else:
                        last_feats = self._fund_adapter.adapt_fundamental_9(data)
                    hist_idx += 1
                else:
                    break

            # 应用特征（前向填充）
            if last_feats:
                for k, v in last_feats.items():
                    if k not in result.columns:
                        result[k] = np.nan
                    result.iloc[i, result.columns.get_loc(k)] = v
