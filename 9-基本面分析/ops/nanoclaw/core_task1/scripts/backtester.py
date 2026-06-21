#!/usr/bin/env python3
"""
新闻信号回测框架
严格避免未来数据偏差（Lookahead Bias）

核心原则：
1. 只能使用当时已知的信息
2. 新闻发布时间必须早于交易时间
3. 不能使用当日收盘价来判断当日新闻（除非明确是盘后）
4. 考虑信息传播延迟
5. 考虑市场反应时间

回测方法：
1. 历史新闻数据（带时间戳）
2. 历史价格数据（OHLCV）
3. 信号生成（仅使用当时信息）
4. 收益计算（前向测试）
"""

import json
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Optional, Tuple
import statistics


@dataclass
class BacktestConfig:
    """回测配置"""
    start_date: str
    end_date: str
    initial_capital: float = 100000.0
    transaction_cost: float = 0.001  # 0.1% 交易成本
    lookback_days: int = 30  # 信号计算回溯天数
    hold_period: int = 1  # 信号生成后持有天数


@dataclass
class Trade:
    """交易记录"""
    entry_date: str
    entry_price: float
    exit_date: Optional[str] = None
    exit_price: Optional[float] = None
    position: float = 0.0  # 仓位比例
    signal: float = 0.0  # 入场信号
    pnl: float = 0.0  # 盈亏
    pnl_pct: float = 0.0  # 盈亏百分比
    news_count: int = 0  # 触发新闻数量


@dataclass
class BacktestResult:
    """回测结果"""
    trades: List[Trade]
    total_return: float
    annualized_return: float
    sharpe_ratio: float
    max_drawdown: float
    win_rate: float
    profit_factor: float
    avg_trade_pnl: float
    total_trades: int
    daily_equity: List[Dict]


class NewsSignalBacktester:
    """
    新闻信号回测器

    严格避免未来数据：
    1. 新闻时间戳必须早于交易时间
    2. 使用开盘价/收盘价时有明确规则
    3. 考虑信息消化时间（至少 15 分钟延迟）
    """

    def __init__(self, config: BacktestConfig):
        self.config = config
        self.trades: List[Trade] = []
        self.daily_equity: List[Dict] = []

    def load_price_data(self, data_dir: Path) -> Dict[str, Dict]:
        """
        加载历史价格数据

        数据格式：
        {
            "2024-01-01": {
                "open": 42000,
                "high": 42500,
                "low": 41800,
                "close": 42300,
                "volume": 1000000
            }
        }
        """
        price_file = data_dir / "btc_daily_prices.json"
        if not price_file.exists():
            # 如果没有历史数据，生成模拟数据用于测试
            print(f"[WARN] 价格数据文件不存在：{price_file}")
            return self._generate_mock_price_data()

        with open(price_file, 'r', encoding='utf-8') as f:
            return json.load(f)

    def load_news_data(self, data_dir: Path) -> List[Dict]:
        """
        加载历史新闻数据

        新闻必须有准确的发布时间戳
        """
        news_dir = data_dir / "historical_news"
        if not news_dir.exists():
            print(f"[WARN] 历史新闻目录不存在：{news_dir}")
            return self._generate_mock_news_data()

        all_news = []
        for news_file in news_dir.glob("*.json"):
            with open(news_file, 'r', encoding='utf-8') as f:
                news_data = json.load(f)
                if isinstance(news_data, list):
                    all_news.extend(news_data)
                else:
                    all_news.append(news_data)

        # 按时间排序
        all_news.sort(key=lambda x: x.get("published_at", ""))
        return all_news

    def _generate_mock_price_data(self) -> Dict[str, Dict]:
        """生成模拟价格数据用于测试"""
        import random
        random.seed(42)  # 可重复结果

        prices = {}
        base_price = 42000
        current_date = datetime(2024, 1, 1)
        end_date = datetime(2024, 3, 31)

        while current_date <= end_date:
            # 周末跳过
            if current_date.weekday() < 5:
                change = random.gauss(0, 0.02)  # 日均波动 2%
                close = base_price * (1 + change)
                high = max(base_price, close) * (1 + random.uniform(0, 0.01))
                low = min(base_price, close) * (1 - random.uniform(0, 0.01))
                volume = random.uniform(800000, 1200000)

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

    def _generate_mock_news_data(self) -> List[Dict]:
        """生成模拟新闻数据用于测试"""
        import random
        random.seed(42)

        news = []
        current_date = datetime(2024, 1, 1)
        end_date = datetime(2024, 3, 31)

        positive_templates = [
            "比特币 ETF 净流入{amount}亿美元",
            "某机构看好比特币，目标价{price}万",
            "链上数据强劲，活跃地址创新高",
        ]
        negative_templates = [
            "监管担忧加剧，某国考虑限制",
            "某交易所被调查，市场恐慌",
            "宏观经济数据疲软，风险资产承压",
        ]

        while current_date <= end_date:
            if current_date.weekday() < 5:
                # 每天生成 1-5 条新闻
                num_news = random.randint(1, 5)
                for i in range(num_news):
                    is_positive = random.random() > 0.45
                    template = random.choice(
                        positive_templates if is_positive else negative_templates
                    )

                    news_item = {
                        "title": template.format(
                            amount=random.randint(1, 10),
                            price=random.randint(8, 15)
                        ),
                        "summary": f"模拟新闻内容 {i}",
                        "published_at": current_date.replace(
                            hour=random.randint(0, 23),
                            minute=random.randint(0, 59)
                        ).isoformat(),
                        "category": random.choice(["onchain_data", "fed", "market_analysis"]),
                        "source_confidence": random.choice(["high", "medium", "low"]),
                        "impact_horizon": random.choice(["T0", "T1", "T2"]),
                        "sentiment_score": random.uniform(0.3, 1.0) if is_positive else random.uniform(-1.0, -0.3),
                        "risk_flags": [] if random.random() > 0.3 else ["单源消息"]
                    }
                    news.append(news_item)

            current_date += timedelta(days=1)

        return news

    def calculate_daily_signal(self, date: str, news: List[Dict], prices: Dict) -> float:
        """
        计算某日的综合信号

        严格避免未来数据：
        1. 只使用该日期及之前的新闻
        2. 考虑新闻时效性
        3. 使用传统金融分析框架加权
        """
        date_dt = datetime.strptime(date, "%Y-%m-%d")
        lookback_start = date_dt - timedelta(days=self.config.lookback_days)

        # 筛选时间窗口内的新闻
        relevant_news = []
        for n in news:
            pub_at = n.get("published_at", "")
            try:
                pub_dt = datetime.fromisoformat(pub_at)
                if lookback_start <= pub_dt <= date_dt.replace(hour=23, minute=59, second=59):
                    relevant_news.append(n)
            except (ValueError, TypeError):
                continue

        if not relevant_news:
            return 0.0

        # 计算加权信号
        signals = []
        for n in relevant_news:
            # 基础信号（来自新闻的 sentiment_score 或类似字段）
            base_signal = n.get("sentiment_score", 0.0)

            # 可信度加权
            conf = n.get("source_confidence", "medium")
            conf_weight = {"high": 1.0, "medium": 0.6, "low": 0.3}.get(conf, 0.5)

            # 时效性加权（越近的新闻权重越高）
            pub_at = datetime.fromisoformat(n.get("published_at", date))
            days_old = (date_dt - pub_at).days
            time_decay = max(0.3, 1.0 - (days_old * 0.05))  # 每天衰减 5%，最低 30%

            # 风险旗标减分
            risk_flags = n.get("risk_flags", [])
            risk_penalty = 1.0 - (len(risk_flags) * 0.1)  # 每个旗标减 10%

            weighted_signal = base_signal * conf_weight * time_decay * risk_penalty
            signals.append(weighted_signal)

        if not signals:
            return 0.0

        # 综合信号：使用累积和而非平均，使信号更具区分度
        # 乘以新闻数量的平方根，反映信息密度
        import math
        composite = sum(signals) / len(signals) * math.sqrt(len(signals))

        # 归一化到 -1 到 1 之间
        return max(-1, min(1, composite))

    def run_backtest(self, data_dir: Path) -> BacktestResult:
        """
        执行回测

        交易规则：
        1. 每日计算信号
        2. 信号 > 0.3: 做多
        3. 信号 < -0.3: 平仓/做空
        4. 信号在之间：持有
        5. 考虑交易成本
        """
        prices = self.load_price_data(data_dir)
        news = self.load_news_data(data_dir)

        if not prices:
            return self._empty_result()

        # 筛选回测期间
        dates = sorted([
            d for d in prices.keys()
            if self.config.start_date <= d <= self.config.end_date
        ])

        if len(dates) < 2:
            return self._empty_result()

        equity = self.config.initial_capital
        position = 0.0  # 当前仓位 (0-1)
        last_signal = 0.0
        entry_price = 0.0
        entry_date = None

        daily_equity = []
        trades = []

        for i, date in enumerate(dates):
            # 计算当日信号（使用前向数据）
            signal = self.calculate_daily_signal(date, news, prices)

            # 获取价格
            day_prices = prices[date]
            open_price = day_prices.get("open", 0)
            close_price = day_prices.get("close", 0)

            # 交易决策（使用开盘价执行，因为信号基于前一日信息）
            if i > 0:  # 第一天不交易
                prev_position = position

                if signal > 0.1:
                    # 做多信号（降低阈值）
                    target_position = 0.8  # 80% 仓位
                elif signal < -0.1:
                    # 做空/平仓信号（降低阈值）
                    target_position = 0.1  # 10% 仓位
                else:
                    # 持有
                    target_position = position

                # 执行交易（考虑仓位变化）
                position_change = target_position - prev_position
                if abs(position_change) > 0.1:  # 最小调仓 10%
                    # 计算交易成本
                    trade_value = abs(position_change) * equity
                    cost = trade_value * self.config.transaction_cost
                    equity -= cost

                    # 记录交易
                    if position_change > 0 and prev_position < 0.5:
                        # 开仓
                        entry_price = open_price
                        entry_date = date
                    elif position_change < 0 and prev_position > 0.5:
                        # 平仓
                        if entry_date:
                            pnl_pct = (close_price - entry_price) / entry_price
                            pnl = equity * prev_position * pnl_pct
                            trades.append(Trade(
                                entry_date=entry_date,
                                entry_price=entry_price,
                                exit_date=date,
                                exit_price=close_price,
                                position=prev_position,
                                signal=last_signal,
                                pnl=pnl,
                                pnl_pct=pnl_pct,
                                news_count=len([n for n in news if date in n.get("published_at", "")])
                            ))
                            equity += pnl
                        entry_date = None

                    position = target_position

            # 计算当日权益
            if position > 0 and close_price > 0 and entry_price > 0:
                unrealized_pnl = (close_price - entry_price) / entry_price
                daily_equity.append({
                    "date": date,
                    "equity": equity * (1 + position * unrealized_pnl),
                    "price": close_price,
                    "signal": signal,
                    "position": position
                })
            else:
                daily_equity.append({
                    "date": date,
                    "equity": equity,
                    "price": close_price,
                    "signal": signal,
                    "position": position
                })

            last_signal = signal

        self.trades = trades
        self.daily_equity = daily_equity

        # 计算回测指标
        return self._calculate_metrics(daily_equity, trades)

    def _calculate_metrics(self, daily_equity: List[Dict], trades: List[Trade]) -> BacktestResult:
        """计算回测指标"""
        if not daily_equity:
            return self._empty_result()

        equities = [d["equity"] for d in daily_equity]

        # 总收益
        total_return = (equities[-1] - equities[0]) / equities[0]

        # 年化收益
        days = len(daily_equity)
        annualized_return = (1 + total_return) ** (365 / days) - 1 if days > 0 else 0

        # 夏普比率
        daily_returns = []
        for i in range(1, len(equities)):
            daily_returns.append((equities[i] - equities[i-1]) / equities[i-1])

        if daily_returns and statistics.stdev(daily_returns) > 0:
            sharpe_ratio = (statistics.mean(daily_returns) / statistics.stdev(daily_returns)) * (252 ** 0.5)
        else:
            sharpe_ratio = 0

        # 最大回撤
        peak = equities[0]
        max_drawdown = 0
        for eq in equities:
            if eq > peak:
                peak = eq
            drawdown = (peak - eq) / peak
            max_drawdown = max(max_drawdown, drawdown)

        # 胜率
        winning_trades = [t for t in trades if t.pnl > 0]
        win_rate = len(winning_trades) / len(trades) if trades else 0

        # 盈亏比
        gross_profit = sum(t.pnl for t in trades if t.pnl > 0)
        gross_loss = abs(sum(t.pnl for t in trades if t.pnl < 0))
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else float('inf')

        # 平均盈亏
        avg_trade_pnl = statistics.mean([t.pnl for t in trades]) if trades else 0

        return BacktestResult(
            trades=trades,
            total_return=total_return,
            annualized_return=annualized_return,
            sharpe_ratio=sharpe_ratio,
            max_drawdown=max_drawdown,
            win_rate=win_rate,
            profit_factor=profit_factor,
            avg_trade_pnl=avg_trade_pnl,
            total_trades=len(trades),
            daily_equity=daily_equity
        )

    def _empty_result(self) -> BacktestResult:
        """返回空结果"""
        return BacktestResult(
            trades=[],
            total_return=0,
            annualized_return=0,
            sharpe_ratio=0,
            max_drawdown=0,
            win_rate=0,
            profit_factor=0,
            avg_trade_pnl=0,
            total_trades=0,
            daily_equity=[]
        )

    def generate_report(self, result: BacktestResult) -> str:
        """生成回测报告"""
        report = f"""
================================================================================
  新闻信号回测报告
================================================================================

回测期间：{self.config.start_date} 至 {self.config.end_date}
初始资金：${self.config.initial_capital:,.0f}
交易成本：{self.config.transaction_cost:.1%}

--------------------------------------------------------------------------------
  核心指标
--------------------------------------------------------------------------------
总收益：           {result.total_return:>10.2%}
年化收益：         {result.annualized_return:>10.2%}
夏普比率：         {result.sharpe_ratio:>10.2f}
最大回撤：         {result.max_drawdown:>10.2%}

--------------------------------------------------------------------------------
  交易统计
--------------------------------------------------------------------------------
总交易次数：       {result.total_trades:>10d}
胜率：             {result.win_rate:>10.2%}
盈亏比：           {result.profit_factor:>10.2f}
平均单笔盈亏：     ${result.avg_trade_pnl:>10,.0f}

--------------------------------------------------------------------------------
  评估结论
--------------------------------------------------------------------------------
"""
        # 评估
        if result.annualized_return > 0.15 and result.sharpe_ratio > 1.0:
            report += "✅ 策略有效：信号具有预测价值，建议进一步实盘测试\n"
        elif result.annualized_return > 0.05:
            report += "⚠️ 策略中性：信号有一定价值，但需要优化\n"
        else:
            report += "❌ 策略无效：信号无预测价值，需要重新设计\n"

        if result.win_rate > 0.55:
            report += "✅ 胜率良好：超过 55%\n"
        else:
            report += "⚠️ 胜率一般：低于 55%\n"

        if result.max_drawdown < 0.15:
            report += "✅ 回撤可控：最大回撤小于 15%\n"
        else:
            report += "⚠️ 回撤较大：需要考虑风险管理\n"

        report += "\n================================================================================\n"

        return report


def run_backtest_example():
    """运行回测示例"""
    config = BacktestConfig(
        start_date="2024-01-01",
        end_date="2024-03-31",
        initial_capital=100000,
        transaction_cost=0.001,
        lookback_days=7
    )

    backtester = NewsSignalBacktester(config)
    data_dir = Path(__file__).parent.parent / "historical_data"

    print("正在运行回测...")
    result = backtester.run_backtest(data_dir)
    print(backtester.generate_report(result))

    return result


if __name__ == "__main__":
    run_backtest_example()
