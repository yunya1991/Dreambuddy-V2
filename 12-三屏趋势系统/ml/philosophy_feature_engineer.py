"""哲学贡献特征工程

从v2增强版MA200牛熊经验法则策略中提取4条核心哲学贡献，
转化为ML可学习的结构化特征向量。

四条哲学贡献：
1. 分化对待BTC和小币：BTC可以做空，小币禁止做空
2. 左侧抄底 > 右侧做空：周线MA200抄底收益贡献远大于熊市做空
3. 分层仓位管理：试探仓(3成) → 确认仓(5成) → 止盈减仓
4. 双牛过滤：小币需要BTC+自身双牛才做多

特征设计原则：
- 每条哲学贡献拆解为可量化信号（连续值优先，离散标签次之）
- 无未来函数，所有特征向前滚动计算
- 特征可被LightGBM等树模型直接消费
- 同时适用于lr_feature_engineer（日线级）和algo_ensemble（信号级）

特征清单（15维）：
=== 哲学1: BTC/小币分化 (4维) ===
- btc_regime_label:        BTC牛熊状态标签 (1=牛, 0=震荡, -1=熊)
- btc_alt_divergence:      BTC vs 当前币种强弱分化度 [-1, 1]
- is_btc_asset:            当前币种是否为BTC (1/0)
- alt_short_risk_score:    小币做空风险评分 [0, 1]，越高越不适合做空

=== 哲学2: 左侧抄底 (4维) ===
- weekly_ma200_distance:   价格相对周线MA200的距离百分比
- dip_buy_level:           当前已触发的抄底档位 (0-4)
- dip_buy_position_ratio:  抄底建议仓位比例 [0, 0.8]
- left_side_buy_signal:    左侧抄底信号强度 [0, 1]

=== 哲学3: 分层仓位 (4维) ===
- bear_short_layer:        做空档位 (0=无, 1=3成, 2=5成)
- fib_tp_remaining_ratio:  斐波那契止盈后剩余仓位比例 [0, 1]
- layered_position_target: 分层仓位目标 [-0.5, 1.0]
- position_adjustment:     仓位调整方向 (1=加仓, 0=持有, -1=减仓)

=== 哲学4: 双牛过滤 (3维) ===
- btc_bull_confirmed:      BTC牛市确认 (1/0)
- self_bull_confirmed:     自身牛市确认 (1/0)
- double_bull_score:       双牛过滤得分 [0, 1]，1=双牛，0=非双牛
"""

from typing import Dict, List, Optional, Tuple, Any
import numpy as np
import pandas as pd


def _safe_float(val, default: float = 0.0) -> float:
    """安全转换为 float"""
    try:
        if val is None or (isinstance(val, float) and np.isnan(val)):
            return default
        return float(val)
    except (ValueError, TypeError):
        return default


class PhilosophyFeatureEngineer:
    """哲学贡献特征工程

    将v2增强版MA200策略的4条哲学贡献转化为ML特征。
    可独立使用，也可作为lr_feature_engineer/algo_ensemble的特征补充。

    用法:
        engineer = PhilosophyFeatureEngineer()
        feats = engineer.extract(
            prices=daily_df,
            symbol="ETH",
            btc_prices=btc_daily_df,
        )
    """

    # 特征名列表（15维）
    FEATURE_NAMES: List[str] = [
        # 哲学1: BTC/小币分化 (4维)
        "btc_regime_label",
        "btc_alt_divergence",
        "is_btc_asset",
        "alt_short_risk_score",
        # 哲学2: 左侧抄底 (4维)
        "weekly_ma200_distance",
        "dip_buy_level",
        "dip_buy_position_ratio",
        "left_side_buy_signal",
        # 哲学3: 分层仓位 (4维)
        "bear_short_layer",
        "fib_tp_remaining_ratio",
        "layered_position_target",
        "position_adjustment",
        # 哲学4: 双牛过滤 (3维)
        "btc_bull_confirmed",
        "self_bull_confirmed",
        "double_bull_score",
    ]

    def __init__(
        self,
        ma_period: int = 200,
        slope_period: int = 5,
        warmup_periods: int = 260,
        dip_buy_max_position: float = 0.8,
        dip_buy_levels: int = 4,
        dip_buy_step_pct: float = 5.0,
        bear_short_level1_pct: float = 0.3,
        bear_short_level2_pct: float = 0.5,
        fib_levels: Optional[List[float]] = None,
    ):
        """
        参数:
            ma_period: MA周期（默认200）
            slope_period: 斜率计算周期（默认5）
            warmup_periods: 预热周期（默认260，确保周线MA200有效）
            dip_buy_*: 抄底参数（与EnhancedMA200Strategy一致）
            bear_short_*: 做空分层参数（与EnhancedMA200Strategy一致）
            fib_levels: 斐波那契止盈档位
        """
        self.ma_period = ma_period
        self.slope_period = slope_period
        self.warmup_periods = warmup_periods
        self.dip_buy_max_position = dip_buy_max_position
        self.dip_buy_levels = dip_buy_levels
        self.dip_buy_step_pct = dip_buy_step_pct
        self.bear_short_level1_pct = bear_short_level1_pct
        self.bear_short_level2_pct = bear_short_level2_pct
        self.fib_levels = fib_levels or [0.236, 0.382, 0.5, 0.618]

    # ------------------------------------------------------------------
    # 公开接口
    # ------------------------------------------------------------------

    def extract(
        self,
        prices: pd.DataFrame,
        symbol: str = "BTC",
        btc_prices: Optional[pd.DataFrame] = None,
    ) -> Dict[str, float]:
        """提取单时间点的哲学贡献特征

        参数:
            prices: 当前币种日线OHLCV（需含open/high/low/close/volume列）
            symbol: 当前币种代码
            btc_prices: BTC日线OHLCV（小币需要，BTC自身可传None）

        返回:
            15维特征字典
        """
        is_btc = symbol.upper() in ("BTC", "BITCOIN", "XBT")

        # 计算当前币种的MA200和斜率
        close = prices["close"].values
        ma = self._calc_ma(close)
        ma_slope = self._calc_slope(ma)
        weekly_ma200 = self._calc_weekly_ma200(prices) if is_btc else None

        # 计算BTC regime（小币需要）
        btc_regime_label = 0.0
        btc_bull = False
        btc_ma_slope = 0.0
        btc_ma = None
        if not is_btc and btc_prices is not None:
            btc_close = btc_prices["close"].values
            btc_ma = self._calc_ma(btc_close)
            btc_ma_slope = self._calc_slope(btc_ma)
            btc_regime_label, btc_bull = self._classify_btc_regime(btc_ma, btc_ma_slope)
        elif is_btc:
            btc_regime_label, btc_bull = self._classify_btc_regime(ma, ma_slope)

        # 当前价格和MA状态
        current_price = close[-1] if len(close) > 0 else 0.0
        current_ma = ma[-1] if len(ma) > 0 and not np.isnan(ma[-1]) else 0.0
        current_slope = ma_slope[-1] if len(ma_slope) > 0 else 0.0

        # === 哲学1: BTC/小币分化 ===
        btc_alt_div = self._calc_btc_alt_divergence(
            current_price, current_slope,
            btc_prices["close"].values[-1] if btc_prices is not None else current_price,
            btc_ma_slope,
            is_btc,
        )
        alt_short_risk = self._calc_alt_short_risk(is_btc, current_slope, btc_regime_label)

        # === 哲学2: 左侧抄底 ===
        weekly_dist = 0.0
        dip_level = 0
        dip_pos = 0.0
        left_signal = 0.0
        if is_btc and weekly_ma200 is not None and not np.isnan(weekly_ma200[-1]) and weekly_ma200[-1] > 0:
            weekly_dist = (weekly_ma200[-1] - current_price) / weekly_ma200[-1] * 100
            if weekly_dist > 0:
                dip_level = min(int(weekly_dist / self.dip_buy_step_pct), self.dip_buy_levels)
                if dip_level > 0:
                    dip_pos = (dip_level / self.dip_buy_levels) * self.dip_buy_max_position
                    left_signal = min(dip_pos / self.dip_buy_max_position, 1.0)

        # === 哲学3: 分层仓位 ===
        price_below = current_price < current_ma if current_ma > 0 else False
        slope_neg = current_slope < 0
        bear_layer = 0
        layered_target = 0.0
        if is_btc and price_below:
            if slope_neg:
                bear_layer = 2
                layered_target = -self.bear_short_level2_pct
            else:
                bear_layer = 1
                layered_target = -self.bear_short_level1_pct
        fib_remaining = 1.0
        if bear_layer > 0 and dip_pos > 0:
            fib_remaining = 1.0
            layered_target = dip_pos
        pos_adjust = self._calc_position_adjustment(
            bear_layer, dip_pos, current_slope, ma_slope
        )

        # === 哲学4: 双牛过滤 ===
        self_bull = bool(current_price > current_ma and current_slope > 0) if current_ma > 0 else False
        double_bull = self._calc_double_bull(is_btc, self_bull, btc_bull)

        return {
            # 哲学1
            "btc_regime_label": btc_regime_label,
            "btc_alt_divergence": btc_alt_div,
            "is_btc_asset": 1.0 if is_btc else 0.0,
            "alt_short_risk_score": alt_short_risk,
            # 哲学2
            "weekly_ma200_distance": weekly_dist,
            "dip_buy_level": float(dip_level),
            "dip_buy_position_ratio": dip_pos,
            "left_side_buy_signal": left_signal,
            # 哲学3
            "bear_short_layer": float(bear_layer),
            "fib_tp_remaining_ratio": fib_remaining,
            "layered_position_target": layered_target,
            "position_adjustment": pos_adjust,
            # 哲学4
            "btc_bull_confirmed": 1.0 if btc_bull else 0.0,
            "self_bull_confirmed": 1.0 if self_bull else 0.0,
            "double_bull_score": double_bull,
        }

    def extract_series(
        self,
        prices: pd.DataFrame,
        symbol: str = "BTC",
        btc_prices: Optional[pd.DataFrame] = None,
    ) -> pd.DataFrame:
        """批量计算整段历史的哲学贡献特征

        参数:
            prices: 完整日线OHLCV
            symbol: 币种
            btc_prices: BTC完整日线（小币需要）

        返回:
            DataFrame, index=prices.index, 列为15维特征
        """
        n = len(prices)
        result = pd.DataFrame(index=prices.index, columns=self.FEATURE_NAMES, dtype=float)

        is_btc = symbol.upper() in ("BTC", "BITCOIN", "XBT")
        close = prices["close"].values
        ma = self._calc_ma(close)
        ma_slope = self._calc_slope(ma)
        weekly_ma200 = self._calc_weekly_ma200(prices) if is_btc else None

        # BTC regime序列（小币需要）
        btc_ma = None
        btc_ma_slope_arr = None
        btc_regime_labels = None
        btc_bull_arr = None
        if not is_btc and btc_prices is not None:
            btc_close = btc_prices["close"].values
            btc_ma = self._calc_ma(btc_close)
            btc_ma_slope_arr = self._calc_slope(btc_ma)
            btc_regime_labels = np.zeros(len(btc_close))
            btc_bull_arr = np.zeros(len(btc_close), dtype=bool)
            for i in range(self.warmup_periods, len(btc_close)):
                if not np.isnan(btc_ma[i]):
                    label, bull = self._classify_btc_regime_at(btc_ma[i], btc_ma_slope_arr[i])
                    btc_regime_labels[i] = label
                    btc_bull_arr[i] = bull
        elif is_btc:
            btc_regime_labels = np.zeros(n)
            btc_bull_arr = np.zeros(n, dtype=bool)
            for i in range(self.warmup_periods, n):
                if not np.isnan(ma[i]):
                    label, bull = self._classify_btc_regime_at(ma[i], ma_slope[i])
                    btc_regime_labels[i] = label
                    btc_bull_arr[i] = bull

        # BTC价格序列（用于分化度计算）
        btc_close_arr = btc_prices["close"].values if btc_prices is not None else close

        for i in range(n):
            if i < self.warmup_periods or np.isnan(ma[i]) or ma[i] <= 0:
                for name in self.FEATURE_NAMES:
                    result.iloc[i][name] = 0.0
                continue

            current_price = close[i]
            current_ma = ma[i]
            current_slope = ma_slope[i]

            # BTC regime
            btc_label = 0.0
            btc_bull = False
            btc_slope_val = 0.0
            if not is_btc and btc_regime_labels is not None:
                # 对齐BTC到当前日线
                btc_idx = min(i, len(btc_regime_labels) - 1)
                btc_label = btc_regime_labels[btc_idx]
                btc_bull = btc_bull_arr[btc_idx] if btc_bull_arr is not None else False
                btc_slope_val = btc_ma_slope_arr[btc_idx] if btc_ma_slope_arr is not None else 0.0
            elif is_btc:
                btc_label = btc_regime_labels[i] if btc_regime_labels is not None else 0.0
                btc_bull = btc_bull_arr[i] if btc_bull_arr is not None else False
                btc_slope_val = current_slope

            btc_price_val = btc_close_arr[min(i, len(btc_close_arr) - 1)]

            # 哲学1
            btc_alt_div = self._calc_btc_alt_divergence(
                current_price, current_slope, btc_price_val, btc_slope_val, is_btc
            )
            alt_short_risk = self._calc_alt_short_risk(is_btc, current_slope, btc_label)

            # 哲学2
            weekly_dist = 0.0
            dip_level = 0
            dip_pos = 0.0
            left_signal = 0.0
            if is_btc and weekly_ma200 is not None and i < len(weekly_ma200):
                wma = weekly_ma200[i]
                if not np.isnan(wma) and wma > 0:
                    weekly_dist = (wma - current_price) / wma * 100
                    if weekly_dist > 0:
                        dip_level = min(int(weekly_dist / self.dip_buy_step_pct), self.dip_buy_levels)
                        if dip_level > 0:
                            dip_pos = (dip_level / self.dip_buy_levels) * self.dip_buy_max_position
                            left_signal = min(dip_pos / self.dip_buy_max_position, 1.0)

            # 哲学3
            price_below = current_price < current_ma
            slope_neg = current_slope < 0
            bear_layer = 0
            layered_target = 0.0
            if is_btc and price_below:
                if slope_neg:
                    bear_layer = 2
                    layered_target = -self.bear_short_level2_pct
                else:
                    bear_layer = 1
                    layered_target = -self.bear_short_level1_pct
            fib_remaining = 1.0
            if dip_pos > 0:
                layered_target = dip_pos
            pos_adjust = self._calc_position_adjustment(bear_layer, dip_pos, current_slope, ma_slope)

            # 哲学4
            self_bull = bool(current_price > current_ma and current_slope > 0)
            double_bull = self._calc_double_bull(is_btc, self_bull, btc_bull)

            # 写入结果
            result.iloc[i]["btc_regime_label"] = btc_label
            result.iloc[i]["btc_alt_divergence"] = btc_alt_div
            result.iloc[i]["is_btc_asset"] = 1.0 if is_btc else 0.0
            result.iloc[i]["alt_short_risk_score"] = alt_short_risk
            result.iloc[i]["weekly_ma200_distance"] = weekly_dist
            result.iloc[i]["dip_buy_level"] = float(dip_level)
            result.iloc[i]["dip_buy_position_ratio"] = dip_pos
            result.iloc[i]["left_side_buy_signal"] = left_signal
            result.iloc[i]["bear_short_layer"] = float(bear_layer)
            result.iloc[i]["fib_tp_remaining_ratio"] = fib_remaining
            result.iloc[i]["layered_position_target"] = layered_target
            result.iloc[i]["position_adjustment"] = pos_adjust
            result.iloc[i]["btc_bull_confirmed"] = 1.0 if btc_bull else 0.0
            result.iloc[i]["self_bull_confirmed"] = 1.0 if self_bull else 0.0
            result.iloc[i]["double_bull_score"] = double_bull

        return result

    def get_feature_names(self) -> List[str]:
        """获取特征名列表"""
        return self.FEATURE_NAMES.copy()

    # ------------------------------------------------------------------
    # 内部计算方法
    # ------------------------------------------------------------------

    def _calc_ma(self, close: np.ndarray) -> np.ndarray:
        """计算MA序列"""
        return pd.Series(close).rolling(
            window=self.ma_period, min_periods=self.ma_period
        ).mean().values

    def _calc_slope(self, ma: np.ndarray) -> np.ndarray:
        """计算MA斜率序列"""
        n = len(ma)
        slope = np.zeros(n)
        for i in range(self.slope_period, n):
            if not np.isnan(ma[i]) and not np.isnan(ma[i - self.slope_period]):
                slope[i] = (ma[i] / ma[i - self.slope_period] - 1) * 100
        return slope

    def _calc_weekly_ma200(self, prices: pd.DataFrame) -> np.ndarray:
        """计算周线MA200（前向填充到日线）"""
        df = prices.copy()
        df.index = pd.to_datetime(df.index)
        weekly = df.resample("W").agg({
            "open": "first", "high": "max", "low": "min",
            "close": "last", "volume": "sum",
        }).dropna()
        if len(weekly) < 200:
            return np.full(len(prices), np.nan)
        wma = pd.Series(weekly["close"].values).rolling(
            window=200, min_periods=200
        ).mean().values
        daily_wma = np.full(len(prices), np.nan)
        widx = 0
        for i in range(len(prices)):
            current_date = prices.index[i]
            while widx < len(weekly) and weekly.index[widx] <= current_date:
                widx += 1
            if widx >= 200:
                daily_wma[i] = wma[widx - 1]
        return daily_wma

    def _classify_btc_regime(
        self, ma: np.ndarray, ma_slope: np.ndarray
    ) -> Tuple[float, bool]:
        """分类当前BTC regime（取最后一个有效值）"""
        if len(ma) == 0 or np.isnan(ma[-1]):
            return 0.0, False
        return self._classify_btc_regime_at(ma[-1], ma_slope[-1] if len(ma_slope) > 0 else 0.0)

    def _classify_btc_regime_at(self, ma_val: float, slope_val: float) -> Tuple[float, bool]:
        """分类指定位置的BTC regime

        Returns:
            (label, is_bull): label=1(牛)/0(震荡)/-1(熊), is_bull=True/False
        """
        if np.isnan(ma_val) or ma_val <= 0:
            return 0.0, False
        # 这里需要价格数据，简化处理：斜率>0=牛，斜率<0=熊，其他=震荡
        # 实际使用时由extract_series传入完整数据
        if slope_val > 0:
            return 1.0, True
        elif slope_val < 0:
            return -1.0, False
        return 0.0, False

    def _calc_btc_alt_divergence(
        self,
        alt_price: float,
        alt_slope: float,
        btc_price: float,
        btc_slope: float,
        is_btc: bool,
    ) -> float:
        """计算BTC vs 小币的强弱分化度

        Returns:
            [-1, 1]: 正值=BTC强于小币, 负值=小币强于BTC
        """
        if is_btc:
            return 0.0
        # 斜率分化（主信号）
        slope_diff = btc_slope - alt_slope
        # tanh归一化到[-1, 1]
        return float(np.tanh(slope_diff / 5.0))

    def _calc_alt_short_risk(
        self, is_btc: bool, self_slope: float, btc_regime: float
    ) -> float:
        """计算小币做空风险评分

        Returns:
            [0, 1]: 越高越不适合做空
        """
        if is_btc:
            return 0.0
        # 小币做空风险 = 基础高风险 + 熊市反弹风险
        base_risk = 0.7  # 小币做空基础风险
        # BTC熊市时小币可能暴力反弹
        if btc_regime < 0:
            base_risk = min(base_risk + 0.2, 1.0)
        # 自身斜率为正时做空风险更高
        if self_slope > 0:
            base_risk = min(base_risk + 0.1, 1.0)
        return base_risk

    def _calc_double_bull(self, is_btc: bool, self_bull: bool, btc_bull: bool) -> float:
        """计算双牛过滤得分

        Returns:
            [0, 1]: 1=双牛确认, 0.5=单牛, 0=非牛
        """
        if is_btc:
            return 1.0 if self_bull else 0.0
        if self_bull and btc_bull:
            return 1.0
        elif self_bull or btc_bull:
            return 0.5
        return 0.0

    def _calc_position_adjustment(
        self,
        bear_layer: int,
        dip_pos: float,
        current_slope: float,
        ma_slope_arr: np.ndarray,
    ) -> float:
        """计算仓位调整方向

        Returns:
            1.0=加仓, 0.0=持有, -1.0=减仓
        """
        # 抄底触发 → 加仓
        if dip_pos > 0:
            return 1.0
        # 做空档位提升 → 加空仓
        if bear_layer == 2:
            return -1.0
        # 做空档位1 → 持有
        if bear_layer == 1:
            return 0.0
        return 0.0
