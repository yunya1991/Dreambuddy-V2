"""三屏趋势系统 — 回测框架核心引擎

向量化回测引擎，参考 VectorBT 设计理念：
- 基于 pandas DataFrame，高效向量化计算
- 支持多周期、多资产
- 内置交易成本、滑点模拟
- 支持仓位管理
- 支持物理引擎增强（信号评估器 + jerk止损 + 动能仓位）

设计原则：
- 数据输入：OHLCV DataFrame
- 信号输入：持仓比例序列（0~1，正=多，负=空）
- 输出：净值曲线、交易记录、绩效指标
"""

from typing import Dict, Optional, Tuple, List, Union
import pandas as pd
import numpy as np


class BacktestEngine:
    """向量化回测引擎

    用法:
        engine = BacktestEngine(
            initial_capital=10000,
            commission=0.0005,  # 0.05%
            slippage=0.0005,    # 0.05%
        )
        result = engine.run(prices, position_size, symbol="BTC")
    """

    def __init__(
        self,
        initial_capital: float = 10000.0,
        commission: float = 0.0005,
        slippage: float = 0.0005,
        leverage: float = 1.0,
        physics_config=None,
    ):
        """
        参数:
            initial_capital: 初始资金（USDT）
            commission: 手续费率（单边）
            slippage: 滑点率（单边）
            leverage: 杠杆倍数（默认1倍现货）
            physics_config: 物理增强器配置 (PhysicsEnhancerConfig)，
                           None=不启用，传入配置=启用物理增强
        """
        self.initial_capital = initial_capital
        self.commission = commission
        self.slippage = slippage
        self.leverage = leverage
        self.physics_config = physics_config
        self._physics_enhancer = None

        if physics_config is not None:
            try:
                from .ml.physics_enhancer import PhysicsEnhancer
            except (ImportError, ValueError):
                from ml.physics_enhancer import PhysicsEnhancer
            self._physics_enhancer = PhysicsEnhancer(physics_config)

    def run(
        self,
        prices: pd.Series,
        position_sizes: pd.Series,
        symbol: str = "BTC",
        ohlcv: Optional[pd.DataFrame] = None,
        wave_signals: Optional[Union[np.ndarray, pd.Series]] = None,
        wave_confs: Optional[Union[np.ndarray, pd.Series]] = None,
        base_positions: Optional[Union[np.ndarray, pd.Series]] = None,
    ) -> Dict:
        """
        运行回测

        参数:
            prices: 收盘价序列（Index=时间，value=价格）
            position_sizes: 目标仓位比例序列（-1~1，正=多，负=空）
                           与 prices 对齐
            symbol: 交易对名称
            ohlcv: OHLCV DataFrame（启用物理增强时需要）
            wave_signals: 波浪信号序列（可选，物理增强用）
            wave_confs: 波浪置信度序列（可选，物理增强用）
            base_positions: 主策略（V4）仓位序列（可选）。
                           传入时，物理增强只作用于波浪仓位部分，
                           主策略仓位保持不变，避免误杀高质量信号。

        返回:
            {
                "equity_curve": pd.Series,  # 净值曲线
                "returns": pd.Series,       # 日收益率
                "trades": pd.DataFrame,     # 交易记录
                "metrics": dict,            # 绩效指标
                "position": pd.Series,      # 实际仓位
                "physics_stats": dict,      # 物理增强统计（若启用）
            }
        """
        prices = prices.copy()
        position_sizes = position_sizes.reindex(prices.index).ffill().fillna(0)

        # 物理增强：仅作用于波浪仓位，不干扰主策略仓位
        physics_stats = None
        if self._physics_enhancer is not None and ohlcv is not None:
            pos_arr = position_sizes.values.astype(float)

            ws_arr = None
            wc_arr = None
            if wave_signals is not None:
                ws_arr = np.array(wave_signals) if not isinstance(wave_signals, np.ndarray) else wave_signals
            if wave_confs is not None:
                wc_arr = np.array(wave_confs, dtype=float) if not isinstance(wave_confs, np.ndarray) else wave_confs

            if base_positions is not None:
                # 分离模式：主策略仓位 + 物理增强的波浪仓位
                base_arr = np.array(base_positions, dtype=float) if not isinstance(base_positions, np.ndarray) else base_positions
                # 波浪仓位 = 总仓位 - 主策略仓位
                wave_pos_arr = pos_arr - base_arr

                enhanced_wave, physics_stats = self._physics_enhancer.enhance_positions(
                    prices=ohlcv,
                    base_positions=wave_pos_arr,
                    wave_signals=ws_arr,
                    wave_confs=wc_arr,
                )
                # 融合：主策略仓位（不变） + 物理增强后的波浪仓位
                enhanced_pos = base_arr + enhanced_wave
            else:
                # 整体模式：物理增强作用于全部仓位
                enhanced_pos, physics_stats = self._physics_enhancer.enhance_positions(
                    prices=ohlcv,
                    base_positions=pos_arr,
                    wave_signals=ws_arr,
                    wave_confs=wc_arr,
                )

            position_sizes = pd.Series(enhanced_pos, index=prices.index)

        actual_position, trade_costs = self._calculate_position_and_costs(
            prices, position_sizes
        )

        returns = self._calculate_returns(prices, actual_position)

        equity = self._calculate_equity(returns, trade_costs)

        trades = self._extract_trades(prices, actual_position, trade_costs)

        from .metrics import calculate_performance_metrics
        metrics = calculate_performance_metrics(equity, returns, trades)

        result = {
            "symbol": symbol,
            "initial_capital": self.initial_capital,
            "final_equity": equity.iloc[-1],
            "total_return": (equity.iloc[-1] / self.initial_capital - 1) * 100,
            "equity_curve": equity,
            "returns": returns,
            "trades": trades,
            "position": actual_position,
            "metrics": metrics,
            "prices": prices,
        }

        if physics_stats is not None:
            result["physics_stats"] = physics_stats

        return result

    def _calculate_position_and_costs(
        self, prices: pd.Series, target_sizes: pd.Series
    ) -> Tuple[pd.Series, pd.Series]:
        """
        计算实际仓位和交易成本

        考虑：
        - 仓位变动 = 目标仓位 - 上一期仓位
        - 每次调仓产生手续费 + 滑点
        - 成本 = |仓位变动| × (commission + slippage)
        """
        actual_position = target_sizes.copy()

        position_changes = actual_position.diff().abs()
        position_changes.iloc[0] = abs(actual_position.iloc[0])

        total_cost_rate = self.commission + self.slippage
        trade_costs = position_changes * total_cost_rate

        return actual_position, trade_costs

    def _calculate_returns(
        self, prices: pd.Series, position: pd.Series
    ) -> pd.Series:
        """
        计算策略收益率

        当期收益 = 上一期仓位 × 当期价格涨跌幅 × 杠杆
        """
        price_returns = prices.pct_change().fillna(0)

        prev_position = position.shift(1).fillna(0)

        strategy_returns = prev_position * price_returns * self.leverage

        return strategy_returns

    def _calculate_equity(
        self, returns: pd.Series, trade_costs: pd.Series
    ) -> pd.Series:
        """
        计算净值曲线

        净值 = 初始资金 × 累乘(1 + 收益率 - 交易成本率)
        """
        net_returns = returns - trade_costs

        cumulative = (1 + net_returns).cumprod()
        equity = self.initial_capital * cumulative

        equity.iloc[0] = self.initial_capital

        return equity

    def _extract_trades(
        self,
        prices: pd.Series,
        position: pd.Series,
        trade_costs: pd.Series,
    ) -> pd.DataFrame:
        """
        提取交易记录

        返回每笔完整开仓-平仓交易的记录
        """
        trades = []
        current_side = 0
        entry_price = 0
        entry_time = None
        entry_size = 0

        for i in range(len(position)):
            pos = position.iloc[i]
            price = prices.iloc[i]
            time = position.index[i]

            if current_side == 0 and pos != 0:
                current_side = 1 if pos > 0 else -1
                entry_price = price * (1 + current_side * self.slippage)
                entry_time = time
                entry_size = abs(pos)
            elif current_side != 0 and pos == 0:
                exit_price = price * (1 - current_side * self.slippage)
                pnl_pct = current_side * (exit_price / entry_price - 1) * self.leverage

                trades.append({
                    "entry_time": entry_time,
                    "exit_time": time,
                    "side": "long" if current_side > 0 else "short",
                    "entry_price": round(entry_price, 2),
                    "exit_price": round(exit_price, 2),
                    "size": round(entry_size, 4),
                    "pnl_pct": round(pnl_pct * 100, 2),
                    "holding_bars": i - position.index.get_loc(entry_time),
                })
                current_side = 0
                entry_price = 0
                entry_time = None
            elif current_side != 0 and (pos * current_side) < 0:
                exit_price = price * (1 - current_side * self.slippage)
                pnl_pct = current_side * (exit_price / entry_price - 1) * self.leverage

                trades.append({
                    "entry_time": entry_time,
                    "exit_time": time,
                    "side": "long" if current_side > 0 else "short",
                    "entry_price": round(entry_price, 2),
                    "exit_price": round(exit_price, 2),
                    "size": round(entry_size, 4),
                    "pnl_pct": round(pnl_pct * 100, 2),
                    "holding_bars": i - position.index.get_loc(entry_time),
                })

                current_side = 1 if pos > 0 else -1
                entry_price = price * (1 + current_side * self.slippage)
                entry_time = time
                entry_size = abs(pos)

        if current_side != 0:
            exit_price = prices.iloc[-1]
            pnl_pct = current_side * (exit_price / entry_price - 1) * self.leverage
            trades.append({
                "entry_time": entry_time,
                "exit_time": position.index[-1],
                "side": "long" if current_side > 0 else "short",
                "entry_price": round(entry_price, 2),
                "exit_price": round(exit_price, 2),
                "size": round(entry_size, 4),
                "pnl_pct": round(pnl_pct * 100, 2),
                "holding_bars": len(position) - position.index.get_loc(entry_time),
                "open": True,
            })

        if trades:
            return pd.DataFrame(trades)
        return pd.DataFrame(columns=[
            "entry_time", "exit_time", "side", "entry_price",
            "exit_price", "size", "pnl_pct", "holding_bars"
        ])
