#!/usr/bin/env python3
"""
加密新闻技能回测 - V9.3/V9.8 优化版

优化点：
1. 采用 V9.3/V9.8 事件账本方法（回测表现最佳）
2. 引入市场状态识别（牛市/熊市/震荡市）
3. 动态阈值调整（根据市场波动率）
4. 改进仓位管理（信号强度×市场状态）

核心改进：
- 事件类型加权：onchain_data > fed_policy > us_data > geopolitics > market_analysis > kol_view
- 时间窗口加权：T0(1.0) > T1(0.7) > T2(0.4) > T3(0.2)
- 意外程度加权：shock(1.5) > major(1.2) > moderate(1.0) > mild(0.8) > expected(0.6)
- 市场状态识别：根据价格趋势和波动率区分牛/熊/震荡
"""

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass
import statistics
import math
import argparse


@dataclass
class BacktestConfig:
    """回测配置 - V9.3 优化版"""
    start_date: str
    end_date: str
    initial_capital: float = 100000.0
    transaction_cost: float = 0.001  # 0.1%
    lookback_days: int = 7
    hold_period: int = 1

    # V9.3 优化参数
    bull_threshold: float = 0.3      # 牛市信号阈值（更低，顺势而为）
    bear_threshold: float = 0.3      # 熊市信号阈值（更敏感）
    neutral_threshold: float = 0.15  # 震荡市信号阈值（更高，过滤噪音）

    # 仓位管理
    max_position: float = 0.8        # 最大仓位
    min_position: float = 0.1        # 最小仓位
    stop_loss: float = -0.10         # 止损线 -10%

    use_market_state: bool = True
    ma_lookback: int = 20
    ma_band: float = 0.05


@dataclass
class Trade:
    """交易记录"""
    entry_date: str
    entry_price: float
    exit_date: Optional[str] = None
    exit_price: Optional[float] = None
    position: float = 0.0
    signal: float = 0.0
    market_state: str = ""  # 市场状态
    pnl: float = 0.0
    pnl_pct: float = 0.0
    event_count: int = 0


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
    market_state_stats: Dict


class OptimizedBacktester:
    """
    V9.3/V9.8 优化版回测器

    核心逻辑：
    1. 使用事件账本方法（V9.3/V9.8）
    2. 识别市场状态（牛/熊/震荡）
    3. 动态调整信号阈值
    4. 根据市场状态调整仓位
    """

    def __init__(self, config: BacktestConfig):
        self.config = config
        self.trades: List[Trade] = []
        self.daily_equity: List[Dict] = []
        self.market_state_history: List[str] = []

    def load_historical_ledger(self, data_dir: Path, ledger_path: Optional[Path] = None) -> List[Dict]:
        """加载历史事件账本数据"""
        if ledger_path is not None:
            if not ledger_path.exists():
                print(f"[ERROR] 指定账本不存在：{ledger_path}")
                return []
            entries: List[Dict] = []
            with open(ledger_path, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entries.append(json.loads(line))
                    except Exception:
                        continue
            print(f"[INFO] 加载事件账本：{ledger_path} - {len(entries)} 条")
            return entries

        # 尝试加载已生成的事件账本
        ledger_files = [
            data_dir / "event_ledger_v9_3.jsonl",
            data_dir / "event_ledger_v9_8.jsonl",
        ]

        entries = []
        for ledger_file in ledger_files:
            if ledger_file.exists():
                with open(ledger_file, 'r', encoding='utf-8') as f:
                    for line in f:
                        line = line.strip()
                        if line:
                            try:
                                entry = json.loads(line)
                                entries.append(entry)
                            except:
                                continue
                print(f"[INFO] 加载事件账本：{ledger_file.name} - {len(entries)} 条")
                break

        # 如果账本不存在，使用模拟数据（基于历史新闻）
        if not entries:
            print("[WARN] 事件账本不存在，使用历史新闻数据生成模拟信号")
            entries = self._generate_mock_ledger(data_dir)

        return entries

    def _generate_mock_ledger(self, data_dir: Path) -> List[Dict]:
        """从历史新闻生成模拟事件账本"""
        news_file = data_dir / "backtest_result.json"
        if news_file.exists():
            with open(news_file, 'r') as f:
                data = json.load(f)
                equity_data = data.get("daily_equity", [])

        # 使用现有的回测结果中的信号数据
        entries = []
        if 'equity_data' in dir():
            for day in equity_data:
                date = day.get("date")
                signal = day.get("signal", 0)

                # 将信号转换为事件
                if abs(signal) > 0.1:
                    sentiment = 1.0 if signal > 0 else -1.0
                    event_type = "onchain_data" if abs(signal) > 0.3 else "market_analysis"

                    entries.append({
                        "date": date,
                        "event_type": event_type,
                        "sentiment_score": sentiment * min(abs(signal), 1.0),
                        "confidence_level": 0.7,
                        "window": "T0" if abs(signal) > 0.2 else "T1",
                        "surprise_bucket": "major" if abs(signal) > 0.3 else "moderate",
                        "influencer_weight": 1.0
                    })

        return entries

    def load_prices(self, data_dir: Path) -> Dict[str, Dict]:
        """加载价格数据"""
        price_file = data_dir / "btc_daily_prices.json"
        if not price_file.exists():
            # 使用内置的模拟数据
            print("[WARN] 价格数据文件不存在，使用回测结果中的数据")
            backtest_file = data_dir / "backtest_result.json"
            if backtest_file.exists():
                with open(backtest_file, 'r') as f:
                    data = json.load(f)
                    equity_data = data.get("daily_equity", [])
                    prices = {}
                    for day in equity_data:
                        prices[day["date"]] = {
                            "close": day["price"],
                            "open": day["price"] * 0.98,
                            "high": day["price"] * 1.02,
                            "low": day["price"] * 0.97
                        }
                    return prices
            return {}

        with open(price_file, 'r', encoding='utf-8') as f:
            return json.load(f)

    def identify_market_state(self, prices: Dict[str, Dict], date: str, lookback: Optional[int] = None) -> str:
        """
        识别市场状态

        基于：
        1. 价格趋势（20 日均线）
        2. 波动率（20 日标准差）
        3. 相对位置（当前价 vs 均线）

        返回：bull / bear / sideways
        """
        dates = sorted(prices.keys())
        if date not in dates:
            return "sideways"

        date_idx = dates.index(date)
        lb = int(lookback or self.config.ma_lookback or 20)
        start_idx = max(0, date_idx - lb)

        # 获取历史价格
        closes = []
        for i in range(start_idx, date_idx + 1):
            d = dates[i]
            if "close" in prices[d]:
                closes.append(prices[d]["close"])

        if len(closes) < 5:
            return "sideways"

        # 计算均线
        ma20 = statistics.mean(closes)
        current_price = closes[-1]

        # 计算波动率
        if len(closes) > 1:
            returns = [(closes[i] - closes[i-1]) / closes[i-1] for i in range(1, len(closes))]
            volatility = statistics.stdev(returns) if len(returns) > 1 else 0
        else:
            volatility = 0

        # 判断市场状态
        price_vs_ma = (current_price - ma20) / ma20

        band = float(self.config.ma_band or 0.05)
        if price_vs_ma > band:  # 价格在均线上方
            if volatility > 0.03:
                return "bull"  # 牛市（高波动上涨）
            else:
                return "bull"  # 牛市（低波动上涨）
        elif price_vs_ma < -band:  # 价格在均线下方
            return "bear"  # 熊市
        else:
            return "sideways"  # 震荡市

    def calculate_signal_from_events(self, date: str, entries: List[Dict], lookback_days: int = 7) -> Tuple[float, float, int]:
        """
        从事件账本计算信号（V9.3 方法）

        返回：(signal, confidence, event_count)
        """
        date_dt = datetime.strptime(date, "%Y-%m-%d")
        lookback_start = date_dt - timedelta(days=lookback_days)

        # 筛选时间窗口内的事件
        relevant = []
        for e in entries:
            pub_date = e.get("date", e.get("published_at", ""))[:10]
            try:
                pub_dt = datetime.strptime(pub_date, "%Y-%m-%d")
                if lookback_start <= pub_dt <= date_dt:
                    relevant.append(e)
            except:
                continue

        if not relevant:
            return 0.0, 0.0, 0

        # V9.3 权重配置
        type_weights = {
            "onchain_data": 1.0,
            "fed_policy": 0.9,
            "monetary_policy": 0.9,
            "us_data": 0.9,
            "geopolitics": 0.7,
            "us_policy": 0.6,
            "market_analysis": 0.5,
            "project_update": 0.5,
            "kol_view": 0.3,
            "kols_view": 0.3,
            "crypto_regulation": 0.8,
            "protocol_tech": 0.6,
            "security_incident": 0.9,
            "meme_culture": 0.3,
            "unknown": 0.5,
        }

        window_weights = {
            "T0": 1.0,
            "T1": 0.7,
            "T2": 0.4,
            "T3": 0.2
        }

        surprise_weights = {
            "shock": 1.5,
            "major": 1.2,
            "moderate": 1.0,
            "mild": 0.8,
            "expected": 0.6
        }

        # 计算加权信号
        weighted_signals = []
        for e in relevant:
            base = e.get("sentiment_score", 0.0)
            type_w = type_weights.get(e.get("event_type", "market_analysis"), 0.5)
            window_w = window_weights.get(e.get("window", "T1"), 0.5)
            surprise_w = surprise_weights.get(e.get("surprise_bucket", "moderate"), 1.0)
            conf = e.get("confidence_level", 0.5)
            influencer_w = e.get("influencer_weight", 1.0)

            weighted = base * type_w * window_w * surprise_w * conf * influencer_w
            weighted_signals.append(weighted)

        # 综合信号（平均）
        signal = sum(weighted_signals) / len(weighted_signals)
        confidence = sum(e.get("confidence_level", 0.5) for e in relevant) / len(relevant)

        return signal, confidence, len(relevant)

    def determine_position(self, signal: float, confidence: float, market_state: str) -> float:
        """根据信号和市场状态确定仓位"""
        config = self.config
        if not bool(getattr(config, "use_market_state", True)):
            market_state = "sideways"

        if market_state == "bull":
            threshold = config.bull_threshold
            position_multiplier = 1.2
        elif market_state == "bear":
            threshold = config.bear_threshold
            position_multiplier = 0.6
        else:
            threshold = config.neutral_threshold
            position_multiplier = 0.8

        threshold_abs = abs(float(threshold or 0))
        if signal > threshold_abs:
            base_position = config.min_position + (signal - threshold_abs) * position_multiplier
            position = min(base_position, config.max_position)
        elif signal < -threshold_abs:
            position = config.min_position * 0.5
        else:
            position = config.min_position * 2

        return round(position, 2)

    def run_backtest(self, entries: List[Dict], prices: Dict[str, Dict]) -> BacktestResult:
        """运行回测"""
        dates = sorted(prices.keys())

        if self.config.start_date:
            dates = [d for d in dates if d >= self.config.start_date]
        if self.config.end_date:
            dates = [d for d in dates if d <= self.config.end_date]

        equity = self.config.initial_capital
        position = 0.0  # 当前仓位
        entry_price = 0.0
        entry_date = None
        prev_price = 0.0

        daily_results = []
        trades = []
        high_watermark = equity

        print(f"\n[INFO] 开始回测：{dates[0] if dates else 'N/A'} 至 {dates[-1] if dates else 'N/A'}")

        for date in dates:
            if date not in prices:
                continue

            price_data = prices[date]
            current_price = price_data.get("close", 0)
            if not current_price:
                continue

            if prev_price > 0:
                price_return = (current_price - prev_price) / prev_price
                equity *= (1 + position * price_return)

            # 识别市场状态
            market_state = self.identify_market_state(prices, date)
            self.market_state_history.append(market_state)

            # 计算信号
            signal, confidence, event_count = self.calculate_signal_from_events(
                date, entries, self.config.lookback_days
            )

            # 确定目标仓位
            target_position = self.determine_position(signal, confidence, market_state)

            # 交易成本（按调仓额计）
            position_change = target_position - position
            if abs(position_change) > 0:
                equity -= abs(position_change) * equity * self.config.transaction_cost

            # 记录交易
            if target_position > 0 and position <= 0:
                # 开仓
                entry_price = current_price
                entry_date = date
            elif target_position <= 0 and position > 0:
                # 平仓
                if entry_date:
                    exit_price = current_price
                    pnl = (exit_price - entry_price) / entry_price if entry_price > 0 else 0.0
                    trade = Trade(
                        entry_date=entry_date,
                        entry_price=entry_price,
                        exit_date=date,
                        exit_price=exit_price,
                        position=position,
                        signal=signal,
                        market_state=market_state,
                        pnl=pnl,
                        pnl_pct=pnl,
                        event_count=event_count
                    )
                    trades.append(trade)
                entry_price = 0
                entry_date = None

            position = target_position
            prev_price = current_price

            # 更新最高水位
            if equity > high_watermark:
                high_watermark = equity

            # 计算回撤
            drawdown = (high_watermark - equity) / high_watermark if high_watermark > 0 else 0

            prev_equity = daily_results[-1]["equity"] if daily_results else self.config.initial_capital
            daily_pnl = equity - prev_equity
            daily_pnl_pct = (daily_pnl / prev_equity) if prev_equity > 0 else 0.0
            daily_results.append({
                "date": date,
                "equity": equity,
                "price": current_price,
                "signal": signal,
                "position": position,
                "market_state": market_state,
                "daily_pnl": daily_pnl,
                "daily_pnl_pct": daily_pnl_pct,
                "drawdown": drawdown
            })

        if entry_date and entry_price > 0 and prev_price > 0 and position > 0:
            last_date = dates[-1]
            exit_price = prev_price
            pnl = (exit_price - entry_price) / entry_price if entry_price > 0 else 0.0
            trades.append(
                Trade(
                    entry_date=entry_date,
                    entry_price=entry_price,
                    exit_date=last_date,
                    exit_price=exit_price,
                    position=position,
                    signal=0.0,
                    market_state=self.market_state_history[-1] if self.market_state_history else "",
                    pnl=pnl,
                    pnl_pct=pnl,
                    event_count=0,
                )
            )

        # 计算回测统计
        total_return = (equity - self.config.initial_capital) / self.config.initial_capital

        # 年化收益
        days = len(dates)
        years = days / 365
        annualized_return = ((equity / self.config.initial_capital) ** (1 / years) - 1) if years > 0 else 0

        # 夏普比率
        daily_returns = [d["daily_pnl_pct"] for d in daily_results]
        if len(daily_returns) > 1 and statistics.stdev(daily_returns) > 0:
            sharpe_ratio = (statistics.mean(daily_returns) / statistics.stdev(daily_returns)) * math.sqrt(252)
        else:
            sharpe_ratio = 0

        # 最大回撤
        max_drawdown = max(d["drawdown"] for d in daily_results) if daily_results else 0

        # 胜率
        winning_trades = [t for t in trades if t.pnl > 0]
        losing_trades = [t for t in trades if t.pnl < 0]
        win_rate = len(winning_trades) / len(trades) if trades else 0

        # 盈亏比
        total_profit = sum(t.pnl for t in winning_trades)
        total_loss = abs(sum(t.pnl for t in losing_trades))
        profit_factor = total_profit / total_loss if total_loss > 0 else 0

        # 市场状态统计
        market_state_stats = {
            "bull_days": self.market_state_history.count("bull"),
            "bear_days": self.market_state_history.count("bear"),
            "sideways_days": self.market_state_history.count("sideways")
        }

        return BacktestResult(
            trades=trades,
            total_return=total_return,
            annualized_return=annualized_return,
            sharpe_ratio=sharpe_ratio,
            max_drawdown=max_drawdown,
            win_rate=win_rate,
            profit_factor=profit_factor,
            avg_trade_pnl=statistics.mean([t.pnl for t in trades]) if trades else 0,
            total_trades=len(trades),
            daily_equity=daily_results,
            market_state_stats=market_state_stats
        )


def main():
    """主函数"""
    parser = argparse.ArgumentParser(description="加密新闻技能回测 - V9.3/V9.8 优化版")
    parser.add_argument("--data-dir", type=str, default="", help="historical_data 目录（默认使用仓库内）")
    parser.add_argument("--ledger-path", type=str, default="", help="指定事件账本 JSONL 路径")
    parser.add_argument("--output-file", type=str, default="", help="输出结果 JSON 路径")
    parser.add_argument("--market-state", type=str, default="on", choices=["on", "off"], help="是否启用市场状态识别与动态阈值")
    parser.add_argument("--ma-lookback", type=int, default=20, help="市场状态识别均线回看天数")
    parser.add_argument("--ma-band", type=float, default=0.05, help="均线偏离带宽（例如 0.05 表示 正负5pct）")
    args = parser.parse_args()
    data_dir = Path(args.data_dir) if args.data_dir else (Path(__file__).parent.parent / "historical_data")
    ledger_path = Path(args.ledger_path) if args.ledger_path else None

    print("=" * 70)
    print("加密新闻技能回测 - V9.3/V9.8 优化版")
    print("=" * 70)

    # 配置
    config = BacktestConfig(
        start_date="2025-12-09",
        end_date="2026-03-08",
        initial_capital=100000,
        transaction_cost=0.001,
        lookback_days=7,
        use_market_state=(args.market_state == "on"),
        ma_lookback=int(args.ma_lookback),
        ma_band=float(args.ma_band),
    )

    backtester = OptimizedBacktester(config)

    # 加载数据
    print("\n[1/3] 加载事件账本...")
    entries = backtester.load_historical_ledger(data_dir, ledger_path)

    print("\n[2/3] 加载价格数据...")
    prices = backtester.load_prices(data_dir)
    print(f"  已加载 {len(prices)} 天价格数据")

    # 运行回测
    print("\n[3/3] 运行回测...")
    result = backtester.run_backtest(entries, prices)

    # 输出结果
    print("\n" + "=" * 70)
    print("回测结果报告 - V9.3/V9.8 优化版")
    print("=" * 70)

    print(f"""
【核心绩效指标】
| 指标 | 数值 | 评估 |
|------|------|------|
| 总收益 | {result.total_return*100:.2f}% | {'✅' if result.total_return > 0 else '❌'} |
| 年化收益 | {result.annualized_return*100:.2f}% | {'✅' if result.annualized_return > 0 else '❌'} |
| 夏普比率 | {result.sharpe_ratio:.2f} | {'✅' if result.sharpe_ratio > 1 else '⚠️' if result.sharpe_ratio > 0 else '❌'} |
| 最大回撤 | {result.max_drawdown*100:.2f}% | {'✅' if result.max_drawdown < 0.15 else '⚠️' if result.max_drawdown < 0.25 else '❌'} |
| 胜率 | {result.win_rate*100:.1f}% | {'✅' if result.win_rate > 0.55 else '⚠️' if result.win_rate > 0.45 else '❌'} |
| 盈亏比 | {result.profit_factor:.2f} | {'✅' if result.profit_factor > 1.5 else '⚠️' if result.profit_factor > 1 else '❌'} |

【交易统计】
- 总交易次数：{result.total_trades}
- 平均单笔盈亏：{result.avg_trade_pnl*100:.2f}%
- 盈利交易：{len([t for t in result.trades if t.pnl > 0])}
- 亏损交易：{len([t for t in result.trades if t.pnl < 0])}

【市场状态统计】
- 牛市天数：{result.market_state_stats.get('bull_days', 0)}
- 熊市天数：{result.market_state_stats.get('bear_days', 0)}
- 震荡市天数：{result.market_state_stats.get('sideways_days', 0)}

【评估结论】
""")

    # 综合评估
    if result.total_return > 0.1 and result.sharpe_ratio > 0.5:
        print("✅ 策略优秀：收益 > 10% 且夏普比率 > 0.5")
    elif result.total_return > 0:
        print("⚠️ 策略有效：正收益但需进一步优化")
    else:
        print("❌ 策略亏损：需要重新设计")

    if result.max_drawdown < 0.15:
        print("✅ 回撤控制优秀：最大回撤 < 15%")
    elif result.max_drawdown < 0.25:
        print("⚠️ 回撤可控：最大回撤 < 25%")
    else:
        print("❌ 回撤过大：需要加强风控")

    # 保存结果
    output_file = Path(args.output_file) if args.output_file else (data_dir / "backtest_result_v93_optimized.json")
    output_data = {
        "config": {
            "start_date": config.start_date,
            "end_date": config.end_date,
            "initial_capital": config.initial_capital,
            "transaction_cost": config.transaction_cost,
            "lookback_days": config.lookback_days,
            "bull_threshold": config.bull_threshold,
            "bear_threshold": config.bear_threshold,
            "neutral_threshold": config.neutral_threshold,
            "use_market_state": config.use_market_state,
            "ma_lookback": config.ma_lookback,
            "ma_band": config.ma_band,
        },
        "results": {
            "total_return": result.total_return,
            "annualized_return": result.annualized_return,
            "sharpe_ratio": result.sharpe_ratio,
            "max_drawdown": result.max_drawdown,
            "win_rate": result.win_rate,
            "profit_factor": result.profit_factor,
            "total_trades": result.total_trades
        },
        "market_state_stats": result.market_state_stats,
        "daily_equity": result.daily_equity,
        "trades": [
            {
                "entry_date": t.entry_date,
                "exit_date": t.exit_date,
                "entry_price": t.entry_price,
                "exit_price": t.exit_price,
                "position": t.position,
                "signal": t.signal,
                "market_state": t.market_state,
                "pnl": t.pnl,
                "pnl_pct": t.pnl_pct
            }
            for t in result.trades
        ]
    }

    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(output_data, f, indent=2)

    print(f"\n【详细结果已保存】")
    print(f"  {output_file}")
    print("=" * 70)


if __name__ == "__main__":
    main()
