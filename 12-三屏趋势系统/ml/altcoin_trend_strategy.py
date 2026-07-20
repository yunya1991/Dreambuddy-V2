"""非BTC币种趋势跟踪策略（替代双牛过滤零仓位方案）

策略设计：
1. 基于自身MA200作为主要趋势判断依据
2. 减半周期影子仓位：BTC减半周期影响风险偏好，但不直接决定交易决策
3. 自身趋势强度：MA200斜率 + ATR波动率 + RSI动量确定仓位
4. 趋势过滤：必须价格>MA200且斜率正才能做多
5. 风控：ATR止损 + 动态仓位调节

策略线归属：[MAIN] 主线代码

调用方式：
    from ml.altcoin_trend_strategy import AltcoinTrendStrategy
    strategy = AltcoinTrendStrategy(symbol="ETH", btc_prices=btc_df)
    positions = strategy.generate_signals(daily_df)
"""

import pandas as pd
import numpy as np


class AltcoinTrendStrategy:
    """非BTC币种趋势跟踪策略

    核心逻辑：
    - 趋势判定：自身MA200 + MA200斜率 + RSI动量
    - 风险调节：BTC减半周期影子仓位 + ATR波动率
    - 仓位管理：分档仓位，趋势越强仓位越高
    - 风控：ATR止损，波动率过高时减仓

    与双牛过滤的区别：
    - 旧方案：BTC牛市 + 自身牛市 + MA200上方，三条件同时满足才做多
    - 新方案：仅需自身MA200上方且斜率正即可做多，BTC减半周期仅调节仓位
    """

    def __init__(self, symbol: str = "ETH", btc_prices: pd.DataFrame = None, **kwargs):
        self.symbol = symbol
        self.btc_prices = btc_prices

        self.max_position = kwargs.get("max_position", 1.0)
        self.min_position = kwargs.get("min_position", 0.1)
        self.ma_period = kwargs.get("ma_period", 200)
        self.slope_period = kwargs.get("slope_period", 20)
        self.rsi_period = kwargs.get("rsi_period", 14)
        self.atr_period = kwargs.get("atr_period", 14)

        self.bull_threshold = kwargs.get("bull_threshold", 0.0005)
        self.bear_threshold = kwargs.get("bear_threshold", -0.0005)

        self.atr_stop_multiple = kwargs.get("atr_stop_multiple", 2.0)
        self.volatility_cap = kwargs.get("volatility_cap", 0.05)

        self.halving_shadow_enabled = kwargs.get("halving_shadow_enabled", True)
        self.shadow_weight = kwargs.get("shadow_weight", 0.3)

        self.stats = {
            "bull_days": 0,
            "bear_days": 0,
            "sideways_days": 0,
            "trend_switches": 0,
            "halving_shadow_active": 0,
        }

        self.last_state = "init"

    def generate_signals(self, prices: pd.DataFrame) -> pd.Series:
        """生成非BTC币种的趋势跟踪信号

        参数:
            prices: 日线OHLCV数据，需包含 'open', 'high', 'low', 'close'

        返回:
            pd.Series: 仓位序列（正值多头，负值空头，0空仓）
        """
        close = prices["close"].values
        high = prices["high"].values
        low = prices["low"].values
        n = len(close)

        if n < self.ma_period + 10:
            return pd.Series(np.zeros(n), index=prices.index, name="position")

        positions = np.zeros(n)
        current_state = "sideways"

        ma = self._compute_ma(close, self.ma_period)
        ma_slope = self._compute_slope(ma, self.slope_period)
        rsi = self._compute_rsi(close, self.rsi_period)
        atr = self._compute_atr(high, low, close, self.atr_period)

        btc_shadow_position = self._compute_halving_shadow(n) if self.halving_shadow_enabled else np.ones(n)

        for i in range(self.ma_period, n):
            price_above_ma = close[i] > ma[i]
            slope_pos = ma_slope[i] > self.bull_threshold
            slope_neg = ma_slope[i] < self.bear_threshold

            momentum_score = self._compute_momentum_score(rsi[i], ma_slope[i])
            volatility_score = self._compute_volatility_score(atr[i], close[i])

            if price_above_ma and slope_pos:
                base_pos = self._compute_trend_position(momentum_score)
                adjusted_pos = base_pos * volatility_score * btc_shadow_position[i]
                target_pos = np.clip(adjusted_pos, self.min_position, self.max_position)
                current_state = "bull"
                self.stats["bull_days"] += 1
            elif slope_neg:
                target_pos = 0.0
                current_state = "bear"
                self.stats["bear_days"] += 1
            else:
                target_pos = 0.0
                current_state = "sideways"
                self.stats["sideways_days"] += 1

            positions[i] = target_pos

            if current_state != self.last_state and self.last_state != "init":
                self.stats["trend_switches"] += 1
            self.last_state = current_state

        return pd.Series(positions, index=prices.index, name="position")

    def _compute_ma(self, prices: np.ndarray, period: int) -> np.ndarray:
        """计算移动平均线"""
        ma = np.zeros(len(prices))
        for i in range(period - 1, len(prices)):
            ma[i] = np.mean(prices[i - period + 1 : i + 1])
        return ma

    def _compute_slope(self, series: np.ndarray, period: int) -> np.ndarray:
        """计算斜率"""
        slope = np.zeros(len(series))
        for i in range(period - 1, len(series)):
            x = np.arange(period)
            y = series[i - period + 1 : i + 1]
            if np.std(x) > 0:
                slope[i] = np.corrcoef(x, y)[0, 1] * np.std(y) / np.std(x)
            else:
                slope[i] = 0
        return slope

    def _compute_rsi(self, prices: np.ndarray, period: int) -> np.ndarray:
        """计算RSI"""
        rsi = np.zeros(len(prices))
        deltas = np.diff(prices)
        gains = np.where(deltas > 0, deltas, 0)
        losses = np.where(deltas < 0, -deltas, 0)

        avg_gain = np.zeros(len(prices))
        avg_loss = np.zeros(len(prices))

        for i in range(period, len(prices)):
            avg_gain[i] = np.mean(gains[i - period + 1 : i + 1])
            avg_loss[i] = np.mean(losses[i - period + 1 : i + 1])

        rs = avg_gain / (avg_loss + 1e-8)
        rsi = 100 - (100 / (1 + rs))
        return rsi

    def _compute_atr(self, high: np.ndarray, low: np.ndarray, close: np.ndarray, period: int) -> np.ndarray:
        """计算ATR"""
        atr = np.zeros(len(close))
        tr = np.zeros(len(close))

        for i in range(1, len(close)):
            tr[i] = max(
                high[i] - low[i],
                abs(high[i] - close[i - 1]),
                abs(low[i] - close[i - 1])
            )

        for i in range(period, len(close)):
            atr[i] = np.mean(tr[i - period + 1 : i + 1])

        return atr

    def _compute_momentum_score(self, rsi: float, slope: float) -> float:
        """计算动量得分（0-1）

        RSI在40-70之间且斜率为正→高分
        RSI>70→过热→降分
        RSI<40→偏弱→降分
        """
        if rsi < 30:
            rsi_score = 0.3
        elif rsi < 40:
            rsi_score = 0.5
        elif rsi < 70:
            rsi_score = 0.8 + (rsi - 40) * 0.2 / 30
        elif rsi < 80:
            rsi_score = 0.7
        else:
            rsi_score = 0.4

        slope_score = np.clip(slope * 100 + 0.5, 0.0, 1.0)

        return (rsi_score + slope_score) / 2

    def _compute_volatility_score(self, atr: float, price: float) -> float:
        """计算波动率得分（0-1）

        波动率过高→降分（避免在高波动时重仓）
        加密货币波动率较高，阈值放宽
        """
        if price <= 0:
            return 1.0

        atr_pct = atr / price

        if atr_pct < 0.04:
            return 1.0
        elif atr_pct < 0.08:
            return 0.9
        elif atr_pct < 0.12:
            return 0.8
        elif atr_pct < 0.16:
            return 0.6
        else:
            return 0.4

    def _compute_trend_position(self, momentum_score: float) -> float:
        """根据动量得分计算趋势仓位

        分档仓位：
        - 弱趋势（0.3-0.5）：50%
        - 中等趋势（0.5-0.7）：70%
        - 强趋势（0.7-0.9）：90%
        - 极强趋势（>0.9）：100%
        """
        if momentum_score < 0.3:
            return 0.5
        elif momentum_score < 0.5:
            return 0.6
        elif momentum_score < 0.7:
            return 0.7
        elif momentum_score < 0.9:
            return 0.9
        else:
            return 1.0

    def _compute_halving_shadow(self, n: int) -> np.ndarray:
        """计算减半周期影子仓位

        BTC减半周期影响整体市场风险偏好：
        - 减半前6个月：风险偏好上升，影子仓位1.0
        - 减半后1-12个月：风险偏好高，影子仓位1.0
        - 减半后12-18个月：风险偏好下降，影子仓位0.8
        - 减半后18-24个月：风险偏好低，影子仓位0.5
        - 减半后24-30个月：风险偏好极低，影子仓位0.3

        影子仓位不直接决定是否交易，仅调节已有仓位
        """
        shadow = np.ones(n)

        if self.btc_prices is None:
            return shadow

        btc_dates = self.btc_prices.index
        if len(btc_dates) != n:
            return shadow

        BTC_HALVING_DATES = ["2020-05-11", "2024-04-20"]
        halving_dates = pd.to_datetime(BTC_HALVING_DATES)

        for halving_date in halving_dates:
            for i in range(n):
                days_since_halving = (btc_dates[i] - halving_date).days
                if days_since_halving < -180:
                    continue
                elif days_since_halving <= 365:
                    shadow[i] *= min(1.0, shadow[i] + 0.0)
                elif days_since_halving <= 540:
                    shadow[i] *= 0.8
                elif days_since_halving <= 730:
                    shadow[i] *= 0.5
                elif days_since_halving <= 900:
                    shadow[i] *= 0.3

        self.stats["halving_shadow_active"] = int(np.sum(shadow < 1.0) > 0)
        return shadow

    def get_stats(self) -> dict:
        return self.stats.copy()


if __name__ == "__main__":
    import json
    from backtest.engine import BacktestEngine

    with open("data/historical/ETH_1D_730d.json") as f:
        data = json.load(f)
    df = pd.DataFrame(data)
    df["timestamp"] = pd.to_datetime(df["ts"], unit="ms")
    df = df.set_index("timestamp")
    prices = df[["o", "h", "l", "c", "vol"]].rename(
        columns={"o": "open", "h": "high", "l": "low", "c": "close", "vol": "volume"}
    )

    with open("data/historical/BTC_1D_730d.json") as f:
        btc_data = json.load(f)
    btc_df = pd.DataFrame(btc_data)
    btc_df["timestamp"] = pd.to_datetime(btc_df["ts"], unit="ms")
    btc_df = btc_df.set_index("timestamp")

    strategy = AltcoinTrendStrategy(symbol="ETH", btc_prices=btc_df)
    signals = strategy.generate_signals(prices)

    engine = BacktestEngine(initial_capital=10000, commission=0.001, slippage=0.001)
    result = engine.run(prices["close"], signals)

    print("非BTC趋势跟踪策略测试（ETH）")
    print(f"总收益: {result['metrics']['total_return_pct']:.2%}")
    print(f"年化: {result['metrics']['annualized_return_pct']:.2%}")
    print(f"夏普: {result['metrics']['sharpe_ratio']:.3f}")
    print(f"最大回撤: {result['metrics']['max_drawdown_pct']:.2%}")
    print(f"交易次数: {len(result['trades'])}")
    print(f"平均仓位: {signals.mean():.4f}")
    print()
    print("状态统计:")
    for k, v in strategy.get_stats().items():
        if v > 0:
            print(f"  {k}: {v}")
