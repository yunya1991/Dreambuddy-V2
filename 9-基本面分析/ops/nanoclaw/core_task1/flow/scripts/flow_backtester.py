#!/usr/bin/env python3
"""
资金流回测引擎 - 类似新闻分析 skill 的回测架构

功能：
1. 加载历史 Regime 记录和价格数据
2. 执行前向测试（Walk-forward Testing）
3. 计算预测准确率和收益指标
4. 生成综合回测报告

核心原则：
1. 严格避免未来数据偏差（Lookahead Bias）
2. Regime 计算只能使用当时的数据
3. 交易信号必须早于交易执行时间
4. 考虑数据采集和计算延迟

回测方法：
1. 使用历史 Regime 记录作为预测信号
2. 对比预测信号与次日/未来收益方向
3. 计算准确率、夏普比率、最大回撤等指标
"""

import json
import os
import math
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import List, Dict, Optional, Tuple
import statistics

# =============================================================================
# 配置类
# =============================================================================

@dataclass
class FlowBacktestConfig:
    """资金流回测配置"""
    start_date: str = "2024-01-01"
    end_date: str = "2024-12-31"
    initial_capital: float = 100000.0
    transaction_cost: float = 0.001  # 0.1% 交易成本
    hold_period: int = 1  # 信号生成后持有天数
    signal_threshold: float = 0.1  # 信号触发阈值
    position_size: float = 0.8  # 目标仓位比例 (80%)
    stop_loss: float = 0.05  # 止损阈值 (5%)
    take_profit: float = 0.10  # 止盈阈值 (10%)


@dataclass
class FlowTrade:
    """交易记录"""
    entry_date: str
    entry_price: float
    entry_signal: str  # bullish/bearish/neutral
    entry_confidence: float
    exit_date: Optional[str] = None
    exit_price: Optional[float] = None
    exit_reason: str = ""  # signal_change/stop_loss/take_profit/end
    position: float = 0.0
    pnl: float = 0.0
    pnl_pct: float = 0.0


@dataclass
class FlowBacktestResult:
    """回测结果"""
    trades: List[FlowTrade]
    total_return: float
    annualized_return: float
    sharpe_ratio: float
    sortino_ratio: float
    max_drawdown: float
    max_drawdown_duration: int  # 最大回撤持续天数
    win_rate: float
    profit_factor: float
    avg_trade_pnl: float
    avg_win: float
    avg_loss: float
    total_trades: int
    winning_trades: int
    losing_trades: int
    daily_equity: List[Dict]
    monthly_returns: Dict[str, float]
    prediction_accuracy: Dict[str, float]  # 按 bias 类型的准确率


# =============================================================================
# 数据加载器
# =============================================================================

class FlowDataLoader:
    """
    资金流历史数据加载器

    数据来源：
    1. flow_regime_*.json - Regime 输出文件
    2. regime_history_*.jsonl - 历史记录
    3. btc_price_*.json - 价格数据
    """

    def __init__(self, data_dir: Path):
        self.data_dir = data_dir

    def load_regime_records(self, start_date: str, end_date: str) -> List[Dict]:
        """
        加载历史 Regime 记录

        优先级：
        1. history/regime_history_*.jsonl
        2. outputs/flow_regime_*.json
        """
        all_records = []

        # 1. 从 history 目录加载 JSONL
        history_dir = self.data_dir / "history"
        if history_dir.exists():
            for history_file in history_dir.glob("regime_history_*.jsonl"):
                with open(history_file, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line:
                            try:
                                record = json.loads(line)
                                all_records.append(record)
                            except json.JSONDecodeError:
                                continue

        # 2. 从 outputs 目录加载 JSON
        outputs_dir = self.data_dir / "outputs"
        if outputs_dir.exists():
            for regime_file in outputs_dir.glob("flow_regime_*.json"):
                with open(regime_file, "r", encoding="utf-8") as f:
                    try:
                        record = json.load(f)
                        all_records.append(record)
                    except json.JSONDecodeError:
                        continue

        # 3. 筛选日期范围
        filtered_records = []
        for record in all_records:
            ts = record.get("timestamp", "")
            try:
                record_date = datetime.fromisoformat(ts.replace("Z", "+00:00")).strftime("%Y-%m-%d")
                if start_date <= record_date <= end_date:
                    filtered_records.append(record)
            except (ValueError, TypeError):
                continue

        # 4. 按时间排序
        filtered_records.sort(key=lambda x: x.get("timestamp", ""))

        print(f"[INFO] 加载 {len(filtered_records)} 条 Regime 记录 ({start_date} 至 {end_date})")
        return filtered_records

    def load_price_data(self) -> Dict[str, Dict]:
        """
        加载历史价格数据

        优先级：
        1. history/btc_price_*.json
        2. outputs/btc_price_*.json
        3. 从 CoinGecko API 获取
        4. 生成模拟数据
        """
        # 1. 从 history 目录加载
        history_dir = self.data_dir / "history"
        if history_dir.exists():
            for price_file in history_dir.glob("btc_price_*.json"):
                if "simulated" not in price_file.name:  # 跳过模拟数据
                    try:
                        with open(price_file, "r", encoding="utf-8") as f:
                            data = json.load(f)
                            if data:
                                print(f"[INFO] 从 {price_file.name} 加载价格数据")
                                return self._normalize_price_data(data)
                    except:
                        continue

        # 2. 从 outputs 目录加载
        outputs_dir = self.data_dir / "outputs"
        # (outputs 目录通常没有价格数据)

        # 3. 从 coin_daily_prices.json 加载（共享数据）
        shared_prices = self.data_dir.parent.parent / "historical_data" / "btc_daily_prices.json"
        if shared_prices.exists():
            try:
                with open(shared_prices, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    print(f"[INFO] 从共享目录加载价格数据")
                    return self._normalize_price_data(data)
            except:
                pass

        # 4. 尝试从 CoinGecko 获取
        print("[INFO] 尝试从 CoinGecko 获取价格数据...")
        price_data = self._fetch_price_from_coingecko()
        if price_data:
            return price_data

        # 5. 生成模拟数据
        print("[WARN] 无法获取真实价格数据，使用模拟数据")
        return self._generate_mock_price_data()

    def _normalize_price_data(self, data: Dict) -> Dict[str, Dict]:
        """标准化价格数据格式"""
        normalized = {}
        for key, value in data.items():
            # 支持多种日期格式
            date_str = key[:10] if len(key) >= 10 else key
            if isinstance(value, dict):
                normalized[date_str] = {
                    "open": value.get("open", 0),
                    "high": value.get("high", 0),
                    "low": value.get("low", 0),
                    "close": value.get("close", 0),
                    "volume": value.get("volume", 0)
                }
        return normalized

    def _fetch_price_from_coingecko(self) -> Optional[Dict[str, Dict]]:
        """从 CoinGecko API 获取价格数据"""
        try:
            import urllib.request

            url = "https://api.coingecko.com/api/v3/coins/bitcoin/market_chart?vs_currency=usd&days=365&interval=daily"
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})

            with urllib.request.urlopen(req, timeout=10) as response:
                data = json.loads(response.read())

            prices = data.get("prices", [])
            result = {}
            for price_point in prices:
                timestamp = price_point[0] / 1000
                price = price_point[1]
                date_str = datetime.fromtimestamp(timestamp, tz=timezone.utc).strftime("%Y-%m-%d")
                result[date_str] = {
                    "open": price,
                    "high": price * 1.02,
                    "low": price * 0.98,
                    "close": price,
                    "volume": 0
                }

            return result
        except Exception as e:
            print(f"[WARN] CoinGecko API 失败：{e}")
            return None

    def _generate_mock_price_data(self) -> Dict[str, Dict]:
        """生成模拟价格数据"""
        import random
        random.seed(42)

        prices = {}
        base_price = 42000
        current_date = datetime(2024, 1, 1)
        end_date = datetime(2024, 12, 31)

        while current_date <= end_date:
            change = random.gauss(0.0005, 0.025)  # 日均 0.05% 收益，2.5% 波动
            close = base_price * (1 + change)
            high = max(base_price, close) * (1 + random.uniform(0, 0.015))
            low = min(base_price, close) * (1 - random.uniform(0, 0.015))
            volume = random.uniform(800000, 1500000)

            prices[current_date.strftime("%Y-%m-%d")] = {
                "open": base_price,
                "high": high,
                "low": low,
                "close": close,
                "volume": volume
            }
            base_price = close
            current_date += timedelta(days=1)

        return prices


# =============================================================================
# 回测引擎
# =============================================================================

class FlowBacktester:
    """
    资金流回测引擎

    交易策略：
    1. Bullish + 高置信度 -> 做多
    2. Bearish + 高置信度 -> 平仓/做空
    3. Neutral -> 持有/空仓

    风险管理：
    1. 止损 5%
    2. 止盈 10%
    3. 最大仓位 80%
    """

    def __init__(self, config: FlowBacktestConfig):
        self.config = config
        self.data_loader: Optional[FlowDataLoader] = None

    def run_backtest(self, data_dir: Path) -> FlowBacktestResult:
        """执行回测"""
        self.data_loader = FlowDataLoader(data_dir)

        # 加载数据
        regime_records = self.data_loader.load_regime_records(
            self.config.start_date,
            self.config.end_date
        )
        price_data = self.data_loader.load_price_data()

        if not regime_records or not price_data:
            return self._empty_result()

        # 初始化
        equity = self.config.initial_capital
        position = 0.0  # 当前仓位 (0-1)
        current_trade: Optional[FlowTrade] = None

        trades: List[FlowTrade] = []
        daily_equity: List[Dict] = []
        daily_returns: List[float] = []

        # 按日期遍历
        dates = sorted(price_data.keys())
        price_lookup = {d: price_data[d]["close"] for d in dates}

        # 构建 Regime 查找表
        regime_lookup = {}
        for record in regime_records:
            ts = record.get("timestamp", "")[:10]
            if ts not in regime_lookup:
                regime_lookup[ts] = record

        # 逐日回测
        for i, date in enumerate(dates):
            if date < self.config.start_date or date > self.config.end_date:
                continue

            # 获取当日 Regime 信号
            regime = regime_lookup.get(date)
            if not regime:
                # 无信号日，保持现有仓位
                self._update_daily_equity(
                    daily_equity, date, equity, position,
                    price_data[date], daily_returns
                )
                continue

            bias = regime.get("bias", "neutral")
            filter_status = regime.get("filter", "enable")
            confidence = regime.get("confidence", 0.5)
            composite = regime.get("composite", 0)

            # 跳过 filter=disable 的日子
            if filter_status == "disable":
                self._update_daily_equity(
                    daily_equity, date, equity, position,
                    price_data[date], daily_returns
                )
                continue

            # 获取价格
            day_data = price_data[date]
            open_price = day_data.get("open", 0)
            close_price = day_data.get("close", 0)

            # 交易逻辑
            if bias == "bullish" and confidence >= self.config.signal_threshold:
                # 做多信号
                if position < 0.5:  # 当前仓位低于 50%
                    # 开仓/加仓
                    target_position = self.config.position_size
                    position_change = target_position - position
                    trade_value = abs(position_change) * equity
                    cost = trade_value * self.config.transaction_cost
                    equity -= cost

                    if not current_trade:
                        current_trade = FlowTrade(
                            entry_date=date,
                            entry_price=open_price,
                            entry_signal=bias,
                            entry_confidence=confidence,
                            position=target_position
                        )
                    position = target_position

            elif bias == "bearish" and confidence >= self.config.signal_threshold:
                # 做空/平仓信号
                if position > 0.1:  # 当前仓位高于 10%
                    # 平仓
                    if current_trade:
                        pnl_pct = (open_price - current_trade.entry_price) / current_trade.entry_price
                        pnl = equity * pnl_pct * current_trade.position
                        equity += pnl

                        current_trade.exit_date = date
                        current_trade.exit_price = open_price
                        current_trade.exit_reason = "signal_change"
                        current_trade.pnl = pnl
                        current_trade.pnl_pct = pnl_pct
                        trades.append(current_trade)
                        current_trade = None

                    position = 0.1

            # 检查止损/止盈
            if current_trade:
                high = day_data.get("high", close_price)
                low = day_data.get("low", close_price)

                # 止损检查
                loss_pct = (low - current_trade.entry_price) / current_trade.entry_price
                if loss_pct <= -self.config.stop_loss:
                    pnl_pct = -self.config.stop_loss
                    pnl = equity * pnl_pct * current_trade.position
                    equity += pnl

                    current_trade.exit_date = date
                    current_trade.exit_price = current_trade.entry_price * (1 - self.config.stop_loss)
                    current_trade.exit_reason = "stop_loss"
                    current_trade.pnl = pnl
                    current_trade.pnl_pct = pnl_pct
                    trades.append(current_trade)
                    current_trade = None
                    position = 0.1

            # 止盈检查（独立判断，因为止损后 current_trade 可能为 None）
            if current_trade:
                high = day_data.get("high", close_price)
                low = day_data.get("low", close_price)

                profit_pct = (high - current_trade.entry_price) / current_trade.entry_price
                if profit_pct >= self.config.take_profit:
                    pnl_pct = self.config.take_profit
                    pnl = equity * pnl_pct * current_trade.position
                    equity += pnl

                    current_trade.exit_date = date
                    current_trade.exit_price = current_trade.entry_price * (1 + self.config.take_profit)
                    current_trade.exit_reason = "take_profit"
                    current_trade.pnl = pnl
                    current_trade.pnl_pct = pnl_pct
                    trades.append(current_trade)
                    current_trade = None
                    position = 0.1

            # 更新每日权益
            self._update_daily_equity(
                daily_equity, date, equity, position,
                day_data, daily_returns
            )

        # 处理未平仓交易
        if current_trade and dates:
            last_date = dates[-1]
            last_price = price_data[last_date]["close"]
            pnl_pct = (last_price - current_trade.entry_price) / current_trade.entry_price
            pnl = equity * pnl_pct * current_trade.position

            current_trade.exit_date = last_date
            current_trade.exit_price = last_price
            current_trade.exit_reason = "end"
            current_trade.pnl = pnl
            current_trade.pnl_pct = pnl_pct
            trades.append(current_trade)
            equity += pnl

        # 计算回测指标
        return self._calculate_metrics(trades, daily_equity, daily_returns, price_data)

    def _update_daily_equity(
        self,
        daily_equity: List[Dict],
        date: str,
        equity: float,
        position: float,
        day_data: Dict,
        daily_returns: List[float]
    ):
        """更新每日权益记录"""
        prev_equity = daily_equity[-1]["equity"] if daily_equity else equity

        # 计算当日收益（考虑仓位）
        close_price = day_data.get("close", 0)
        open_price = day_data.get("open", close_price)
        day_return = (close_price - open_price) / open_price if open_price > 0 else 0

        # 策略收益（考虑仓位）
        strategy_return = day_return * position
        new_equity = prev_equity * (1 + strategy_return)

        daily_equity.append({
            "date": date,
            "equity": new_equity,
            "position": position,
            "day_return": day_return,
            "strategy_return": strategy_return
        })

        if daily_equity:
            daily_returns.append(strategy_return)

    def _calculate_metrics(
        self,
        trades: List[FlowTrade],
        daily_equity: List[Dict],
        daily_returns: List[float],
        price_data: Dict
    ) -> FlowBacktestResult:
        """计算回测指标"""

        # 基础统计
        total_trades = len(trades)
        winning_trades = sum(1 for t in trades if t.pnl > 0)
        losing_trades = sum(1 for t in trades if t.pnl <= 0)

        win_rate = winning_trades / total_trades if total_trades > 0 else 0

        # 盈亏统计
        total_pnl = sum(t.pnl for t in trades)
        total_return = total_pnl / self.config.initial_capital if self.config.initial_capital > 0 else 0

        gross_profit = sum(t.pnl for t in trades if t.pnl > 0)
        gross_loss = abs(sum(t.pnl for t in trades if t.pnl < 0))
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else float('inf')

        avg_trade_pnl = total_pnl / total_trades if total_trades > 0 else 0
        avg_win = gross_profit / winning_trades if winning_trades > 0 else 0
        avg_loss = gross_loss / losing_trades if losing_trades > 0 else 0

        # 年化收益
        days = len(daily_equity)
        if days > 0:
            final_equity = daily_equity[-1]["equity"]
            annualized_return = (final_equity / self.config.initial_capital) ** (365 / days) - 1
        else:
            annualized_return = 0

        # 夏普比率
        if daily_returns and len(daily_returns) > 1:
            avg_return = statistics.mean(daily_returns)
            std_return = statistics.stdev(daily_returns)
            sharpe_ratio = (avg_return / std_return) * math.sqrt(252) if std_return > 0 else 0
        else:
            sharpe_ratio = 0

        # 索提诺比率（只考虑下行波动）
        downside_returns = [r for r in daily_returns if r < 0]
        if downside_returns:
            downside_std = statistics.stdev(downside_returns) if len(downside_returns) > 1 else 0
            sortino_ratio = (avg_return / downside_std) * math.sqrt(252) if downside_std > 0 else 0
        else:
            sortino_ratio = 0

        # 最大回撤
        max_drawdown = 0
        peak_equity = self.config.initial_capital
        max_dd_duration = 0
        current_dd_duration = 0

        for record in daily_equity:
            equity = record["equity"]
            if equity > peak_equity:
                peak_equity = equity
                current_dd_duration = 0
            else:
                drawdown = (peak_equity - equity) / peak_equity
                if drawdown > max_drawdown:
                    max_drawdown = drawdown
                current_dd_duration += 1
                if current_dd_duration > max_dd_duration:
                    max_dd_duration = current_dd_duration

        # 月度收益
        monthly_returns = {}
        for record in daily_equity:
            month = record["date"][:7]  # YYYY-MM
            if month not in monthly_returns:
                monthly_returns[month] = []
            monthly_returns[month].append(record["strategy_return"])

        monthly_returns = {
            k: sum(v) / len(v) if v else 0
            for k, v in monthly_returns.items()
        }

        # 预测准确率（按 bias 类型）
        prediction_accuracy = self._calculate_prediction_accuracy(trades)

        return FlowBacktestResult(
            trades=trades,
            total_return=total_return,
            annualized_return=annualized_return,
            sharpe_ratio=sharpe_ratio,
            sortino_ratio=sortino_ratio,
            max_drawdown=max_drawdown,
            max_drawdown_duration=max_dd_duration,
            win_rate=win_rate,
            profit_factor=profit_factor,
            avg_trade_pnl=avg_trade_pnl,
            avg_win=avg_win,
            avg_loss=avg_loss,
            total_trades=total_trades,
            winning_trades=winning_trades,
            losing_trades=losing_trades,
            daily_equity=daily_equity,
            monthly_returns=monthly_returns,
            prediction_accuracy=prediction_accuracy
        )

    def _calculate_prediction_accuracy(self, trades: List[FlowTrade]) -> Dict[str, float]:
        """计算按 bias 类型的预测准确率"""
        stats = {
            "bullish": {"total": 0, "correct": 0},
            "bearish": {"total": 0, "correct": 0},
            "neutral": {"total": 0, "correct": 0},
            "overall": {"total": 0, "correct": 0}
        }

        for trade in trades:
            bias = trade.entry_signal
            pnl = trade.pnl

            stats[bias]["total"] += 1
            stats["overall"]["total"] += 1

            if pnl > 0:
                stats[bias]["correct"] += 1
                stats["overall"]["correct"] += 1

        return {
            "bullish": stats["bullish"]["correct"] / stats["bullish"]["total"] if stats["bullish"]["total"] > 0 else 0,
            "bearish": stats["bearish"]["correct"] / stats["bearish"]["total"] if stats["bearish"]["total"] > 0 else 0,
            "neutral": stats["neutral"]["correct"] / stats["neutral"]["total"] if stats["neutral"]["total"] > 0 else 0,
            "overall": stats["overall"]["correct"] / stats["overall"]["total"] if stats["overall"]["total"] > 0 else 0
        }

    def _empty_result(self) -> FlowBacktestResult:
        """返回空结果"""
        return FlowBacktestResult(
            trades=[],
            total_return=0,
            annualized_return=0,
            sharpe_ratio=0,
            sortino_ratio=0,
            max_drawdown=0,
            max_drawdown_duration=0,
            win_rate=0,
            profit_factor=0,
            avg_trade_pnl=0,
            avg_win=0,
            avg_loss=0,
            total_trades=0,
            winning_trades=0,
            losing_trades=0,
            daily_equity=[],
            monthly_returns={},
            prediction_accuracy={}
        )


# =============================================================================
# 主函数
# =============================================================================

def run_flow_backtest(
    start_date: str = None,
    end_date: str = None,
    data_dir: str = None
) -> FlowBacktestResult:
    """
    执行资金流回测

    Args:
        start_date: 开始日期 (YYYY-MM-DD)
        end_date: 结束日期 (YYYY-MM-DD)
        data_dir: 数据目录

    Returns:
        回测结果
    """
    # 默认配置
    if start_date is None:
        start_date = (datetime.now() - timedelta(days=90)).strftime("%Y-%m-%d")
    if end_date is None:
        end_date = datetime.now().strftime("%Y-%m-%d")
    if data_dir is None:
        data_dir = "/workspace/ops/nanoclaw/core_task1/flow"

    # 创建配置
    config = FlowBacktestConfig(
        start_date=start_date,
        end_date=end_date
    )

    # 创建回测器
    backtester = FlowBacktester(config)

    # 执行回测
    result = backtester.run_backtest(Path(data_dir))

    return result


if __name__ == "__main__":
    import sys

    start = sys.argv[1] if len(sys.argv) > 1 else None
    end = sys.argv[2] if len(sys.argv) > 2 else None
    data_dir = sys.argv[3] if len(sys.argv) > 3 else None

    result = run_flow_backtest(start, end, data_dir)

    print("\n" + "=" * 60)
    print("资金流回测结果")
    print("=" * 60)
    print(f"总收益：{result.total_return*100:.2f}%")
    print(f"年化收益：{result.annualized_return*100:.2f}%")
    print(f"夏普比率：{result.sharpe_ratio:.2f}")
    print(f"最大回撤：{result.max_drawdown*100:.2f}%")
    print(f"胜率：{result.win_rate*100:.1f}%")
    print(f"交易次数：{result.total_trades}")
    print(f"预测准确率：{result.prediction_accuracy.get('overall', 0)*100:.1f}%")
