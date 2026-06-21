#!/usr/bin/env python3
"""
事件账本回测器 - V9.3

基于 JSONL 事件账本进行回测，支持：
- event_type: 按事件类型过滤
- window: 按时间窗口加权
- surprise_bucket: 意外程度加权
- risk_action_proposal: 模拟行动执行
"""

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Optional
from dataclasses import dataclass, asdict
import statistics
import argparse


@dataclass
class BacktestConfig:
    """回测配置"""
    start_date: str
    end_date: str
    initial_capital: float = 100000.0
    transaction_cost: float = 0.001  # 0.1%
    lookback_days: int = 7
    hold_period: int = 1


@dataclass
class Trade:
    """交易记录"""
    entry_date: str
    entry_price: float
    exit_date: Optional[str] = None
    exit_price: Optional[float] = None
    position: float = 0.0
    event_driven: str = ""  # 驱动事件 ID
    action: str = ""  # 风险行动
    pnl: float = 0.0
    pnl_pct: float = 0.0


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
    event_stats: Dict  # 事件统计


class EventLedgerBacktester:
    """事件账本回测器 - V9.3"""

    def __init__(self, config: BacktestConfig):
        self.config = config
        self.trades: List[Trade] = []
        self.daily_equity: List[Dict] = []
        self.event_stats: Dict = {}

    def _community_bucket(self, score: float) -> str:
        if score >= 0.7:
            return "high"
        if score >= 0.4:
            return "mid"
        return "low"

    def load_ledger(self, ledger_path: Path) -> List[Dict]:
        """加载 JSONL 事件账本"""
        if not ledger_path.exists():
            print(f"[ERROR] 事件账本文件不存在：{ledger_path}")
            return []

        entries = []
        with open(ledger_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        entry = json.loads(line)
                        entries.append(entry)
                    except json.JSONDecodeError as e:
                        print(f"[WARN] 解析失败：{e}")

        print(f"[INFO] 加载事件账本：{len(entries)} 条")
        return entries

    def load_prices(self, data_dir: Path) -> Dict[str, Dict]:
        """加载价格数据"""
        price_file = data_dir / "btc_daily_prices.json"
        if not price_file.exists():
            print(f"[WARN] 价格数据文件不存在")
            return {}

        with open(price_file, 'r', encoding='utf-8') as f:
            return json.load(f)

    def filter_events_by_date(self, entries: List[Dict], start: str, end: str) -> List[Dict]:
        """按日期过滤事件"""
        filtered = []
        for e in entries:
            pub_date = e.get("published_at", "")[:10]
            if start <= pub_date <= end:
                filtered.append(e)
        return filtered

    def calculate_daily_signal(self, date: str, entries: List[Dict]) -> Dict:
        """
        计算当日信号（基于事件账本）

        返回：{signal, confidence, action, event_count}
        """
        date_dt = datetime.strptime(date, "%Y-%m-%d")
        lookback_start = date_dt - timedelta(days=self.config.lookback_days)

        # 筛选时间窗口内的事件
        relevant = []
        for e in entries:
            pub_date = e.get("published_at", "")[:10]
            try:
                pub_dt = datetime.fromisoformat(e.get("published_at", ""))
                if lookback_start <= pub_dt <= date_dt.replace(hour=23, minute=59, second=59):
                    relevant.append(e)
            except (ValueError, TypeError):
                continue

        if not relevant:
            return {"signal": 0.0, "confidence": 0.0, "action": "hold", "event_count": 0}

        # 9.1: 按事件类型加权 (V9.5 优化)
        type_weights = {
            "onchain_data": 1.0,
            "fed_policy": 0.9,
            "us_data": 0.9,
            "geopolitics": 0.7,
            "us_policy": 0.6,
            "market_analysis": 0.5,
            "project_update": 0.5,
            "kol_view": 0.3,
            "security": 0.8,
            # V9.4 新增
            "jin10_news": 1.0,          # V9.5: 金十数据权重降低 (1.2→1.0)
            "tech_leader": 1.8,         # V9.5: 技术派大 V 权重提升 (1.5→1.8)
            "vc_view": 1.5,             # V9.5: 投资机构权重提升 (1.3→1.5)
            "onchain_analyst": 1.5,     # V9.5: 链上分析师权重提升 (1.3→1.5)
            "trader_view": 1.3,         # V9.5: 交易员权重提升 (1.2→1.3)
        }

        # 9.2: 按时间窗口加权
        window_weights = {
            "T0": 1.0,
            "T1": 0.7,
            "T2": 0.4,
            "T3": 0.2
        }

        # 9.3: 按意外程度加权
        surprise_weights = {
            "shock": 1.5,
            "major": 1.2,
            "moderate": 1.0,
            "mild": 0.8,
            "expected": 0.6
        }

        # V9.3: 计算加权信号（连乘）
        signals = []
        for e in relevant:
            # 基础信号（sentiment_score，有正负）
            base = e.get("sentiment_score", 0.0)

            # 9.1 权重
            type_w = type_weights.get(e.get("event_type", ""), 0.5)

            # 9.2 权重
            window_w = window_weights.get(e.get("window", "T1"), 0.5)

            # 9.3 权重
            surprise_w = surprise_weights.get(e.get("surprise_bucket", "expected"), 0.5)

            # 置信度
            conf = e.get("confidence_level", 0.5)

            # V9.4/V9.5: 影响力加权
            influencer_w = e.get("influencer_weight", 1.0)

            # V9.3 原始公式：连乘
            weighted = base * type_w * window_w * surprise_w * conf * influencer_w
            signals.append(weighted)

        if not signals:
            return {"signal": 0.0, "confidence": 0.0, "action": "hold", "event_count": 0}

        # V9.3: 综合信号（简单平均）
        avg_signal = sum(signals) / len(signals)
        max_signal = max(signals)
        min_signal = min(signals)

        # V9.3: 基于事件 proposal 众数决定 action
        action_counts = {}
        for e in relevant:
            a = e.get("risk_action_proposal", "hold")
            action_counts[a] = action_counts.get(a, 0) + 1

        dominant_action = max(action_counts, key=action_counts.get) if action_counts else "hold"

        return {
            "signal": avg_signal,
            "confidence": len(relevant) / max(len(signals), 1),
            "action": dominant_action,
            "event_count": len(relevant),
            "max_signal": max_signal,
            "min_signal": min_signal
        }

    def action_to_position(self, action: str) -> float:
        """将风险行动转换为仓位"""
        mapping = {
            "hold": 0.5,
            "reduce": 0.2,
            "increase": 0.8,
            "hedge": 0.3,
            "stop_loss": 0.0,
            "take_profit": 0.5
        }
        return mapping.get(action, 0.5)

    def signal_to_position(self, signal: float) -> float:
        """将信号转换为仓位（基于信号强度）"""
        # 信号范围通常在 -1 到 1 之间
        # 正信号→高仓位，负信号→低仓位
        if signal > 0.3:
            return 0.8  # 强烈看多
        elif signal > 0.1:
            return 0.6  # 看多
        elif signal > -0.1:
            return 0.5  # 中性
        elif signal > -0.3:
            return 0.3  # 看空
        else:
            return 0.1  # 强烈看空

    def run_backtest(self, ledger_path: Path, data_dir: Path) -> BacktestResult:
        """执行回测"""
        # 加载数据
        entries = self.load_ledger(ledger_path)
        prices = self.load_prices(data_dir)

        if not entries or not prices:
            return self._empty_result()

        # 筛选回测期间
        dates = sorted([
            d for d in prices.keys()
            if self.config.start_date <= d <= self.config.end_date
        ])

        if len(dates) < 2:
            return self._empty_result()

        equity = self.config.initial_capital
        position = 0.0
        entry_price = 0.0
        entry_date = None
        current_action = "hold"

        daily_equity = []
        trades = []

        # 事件统计
        event_stats = {
            "total_events": len(entries),
            "by_action": {},
            "by_type": {},
            "by_community_effective_bucket": {"high": 0, "mid": 0, "low": 0},
            "triggered_trades": 0
        }
        for e in entries:
            score = float(e.get("community_effective_score", 0.0) or 0.0)
            bucket = self._community_bucket(score)
            event_stats["by_community_effective_bucket"][bucket] += 1

        for i, date in enumerate(dates):
            # 计算当日信号
            signal_data = self.calculate_daily_signal(date, entries)
            signal = signal_data["signal"]
            action = signal_data["action"]

            # 获取价格
            day_prices = prices[date]
            open_price = day_prices.get("open", 0)
            close_price = day_prices.get("close", 0)

            # 统计行动
            act = signal_data.get("action", "hold")
            event_stats["by_action"][act] = event_stats["by_action"].get(act, 0) + 1

            if i > 0:  # 第一天不交易
                prev_position = position
                # 使用信号强度转换仓位（更灵敏）
                target_position = self.signal_to_position(signal)

                # 平滑调仓
                position_change = target_position - prev_position
                if abs(position_change) > 0.05:  # 最小调仓 5%
                    # 交易成本
                    trade_value = abs(position_change) * equity
                    cost = trade_value * self.config.transaction_cost
                    equity -= cost

                    # 记录交易
                    pos_eps = 0.05
                    if prev_position <= pos_eps and target_position > pos_eps:
                        # 开仓
                        entry_price = open_price
                        entry_date = date
                        current_action = action
                        event_stats["triggered_trades"] += 1

                    elif prev_position > pos_eps and target_position <= pos_eps:
                        # 平仓
                        if entry_date and entry_price > 0:
                            pnl_pct = (close_price - entry_price) / entry_price
                            pnl = equity * prev_position * pnl_pct
                            trades.append(Trade(
                                entry_date=entry_date,
                                entry_price=entry_price,
                                exit_date=date,
                                exit_price=close_price,
                                position=prev_position,
                                event_driven=action,
                                action=current_action,
                                pnl=pnl,
                                pnl_pct=pnl_pct
                            ))
                            equity += pnl
                        entry_date = None
                        current_action = "hold"
                        entry_price = 0.0

                    position = target_position

            # 计算当日权益
            if position > 0 and close_price > 0 and entry_price > 0:
                unrealized_pnl = (close_price - entry_price) / entry_price
                daily_equity.append({
                    "date": date,
                    "equity": equity * (1 + position * unrealized_pnl),
                    "price": close_price,
                    "signal": signal,
                    "position": position,
                    "action": action
                })
            else:
                daily_equity.append({
                    "date": date,
                    "equity": equity,
                    "price": close_price,
                    "signal": signal,
                    "position": position,
                    "action": action
                })

        if entry_date and entry_price > 0:
            last_date = dates[-1]
            last_close = prices.get(last_date, {}).get("close", 0) or 0
            if last_close > 0 and position > 0:
                pnl_pct = (last_close - entry_price) / entry_price
                pnl = equity * position * pnl_pct
                trades.append(
                    Trade(
                        entry_date=entry_date,
                        entry_price=entry_price,
                        exit_date=last_date,
                        exit_price=last_close,
                        position=position,
                        event_driven="end",
                        action=current_action,
                        pnl=pnl,
                        pnl_pct=pnl_pct,
                    )
                )
                equity += pnl

        self.trades = trades
        self.daily_equity = daily_equity
        self.event_stats = event_stats

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

        if daily_returns and len(daily_returns) > 1 and statistics.stdev(daily_returns) > 0:
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
            daily_equity=daily_equity,
            event_stats=self.event_stats
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
            daily_equity=[],
            event_stats={}
        )

    def generate_report(self, result: BacktestResult) -> str:
        """生成回测报告"""
        report = f"""
================================================================================
  事件账本回测报告 (V9.5 - 优化版)
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
  事件统计 (9.1/9.2/9.3)
--------------------------------------------------------------------------------
"""
        # 事件统计
        es = result.event_stats
        if es:
            report += f"""
总事件数：         {es.get('total_events', 0):>10d}
触发交易：         {es.get('triggered_trades', 0):>10d}

按行动分布:
"""
            for action, count in sorted(es.get("by_action", {}).items()):
                report += f"  {action}: {count}\n"

        report += """
--------------------------------------------------------------------------------
  评估结论
--------------------------------------------------------------------------------
"""
        if result.annualized_return > 0.15 and result.sharpe_ratio > 1.0:
            report += "✅ 策略有效：事件账本信号具有预测价值\n"
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

    def calibrate_event_windows(self, entries: List[Dict], prices: Dict[str, Dict]) -> Dict:
        candidate_days = [1, 2, 3, 5, 7]
        sorted_dates = sorted(prices.keys())
        date_index = {d: i for i, d in enumerate(sorted_dates)}
        grouped: Dict[str, List[Dict]] = {}
        grouped_table: Dict[str, List[Dict]] = {}
        fallback_asset_bucket = {
            "onchain_data": "crypto_beta",
            "project_update": "crypto_beta",
            "protocol_tech": "crypto_beta",
            "meme_culture": "crypto_beta",
            "kols_view": "crypto_beta",
            "kol_view": "crypto_beta",
            "monetary_policy": "macro_policy",
            "us_data": "macro_policy",
            "geopolitics": "macro_policy",
            "crypto_regulation": "macro_policy",
            "market_analysis": "macro_policy",
            "us_policy": "macro_policy",
            "security_incident": "security_defensive",
            "security": "security_defensive",
        }

        def resolve_asset_bucket(row: Dict) -> str:
            value = str(
                row.get("window_policy_asset_bucket")
                or row.get("asset_bucket")
                or ""
            ).strip()
            if value:
                return value
            event_type = str(row.get("event_type") or "unknown")
            return fallback_asset_bucket.get(event_type, "crypto_beta")

        def resolve_market_period(row: Dict) -> str:
            value = str(row.get("market_trend_state") or row.get("market_state") or "").strip()
            if value:
                return value
            return "neutral"

        for e in entries:
            event_type = str(e.get("event_type") or "unknown")
            grouped.setdefault(event_type, []).append(e)
            table_key = "|".join([event_type, resolve_asset_bucket(e), resolve_market_period(e)])
            grouped_table.setdefault(table_key, []).append(e)

        def forward_return(pub_date: str, horizon_days: int) -> Optional[float]:
            if pub_date not in date_index:
                return None
            i = date_index[pub_date]
            j = i + horizon_days
            if j >= len(sorted_dates):
                return None
            p0 = prices.get(sorted_dates[i], {}).get("close", 0)
            p1 = prices.get(sorted_dates[j], {}).get("close", 0)
            if not p0 or not p1:
                return None
            return float(p1 - p0) / float(p0)

        def map_window(days: int) -> str:
            if days <= 1:
                return "[0,+4h]"
            if days <= 2:
                return "[-6h,+6h]"
            if days <= 4:
                return "[-24h,+24h]"
            return "[-48h,+48h]"

        calibration_rows = []
        for event_type, rows in grouped.items():
            horizon_stats = []
            for horizon in candidate_days:
                rets = []
                for row in rows:
                    pub_date = str(row.get("published_at") or "")[:10]
                    if not pub_date:
                        continue
                    r = forward_return(pub_date, horizon)
                    if r is not None:
                        rets.append(r)
                if len(rets) < 5:
                    continue
                abs_mean = statistics.mean(abs(x) for x in rets)
                downside = [x for x in rets if x < 0]
                downside_mean = abs(statistics.mean(downside)) if downside else 0.0
                dispersion = statistics.pstdev(rets) if len(rets) > 1 else 0.0
                score = abs_mean + 0.6 * downside_mean - 0.3 * dispersion
                horizon_stats.append(
                    {
                        "horizon_days": horizon,
                        "sample_count": len(rets),
                        "avg_abs_return": round(abs_mean, 6),
                        "avg_downside_return": round(downside_mean, 6),
                        "dispersion": round(dispersion, 6),
                        "calibration_score": round(score, 6),
                    }
                )
            if not horizon_stats:
                continue
            best = sorted(horizon_stats, key=lambda x: x["calibration_score"], reverse=True)[0]
            calibration_rows.append(
                {
                    "event_type": event_type,
                    "recommended_horizon_days": best["horizon_days"],
                    "recommended_window_range": map_window(best["horizon_days"]),
                    "confidence": round(min(1.0, best["sample_count"] / 40.0), 4),
                    "stats": horizon_stats,
                }
            )
        window_version_table = []
        for table_key, rows in grouped_table.items():
            parts = table_key.split("|")
            event_type = parts[0] if len(parts) > 0 else "unknown"
            asset_bucket = parts[1] if len(parts) > 1 else "crypto_beta"
            market_period = parts[2] if len(parts) > 2 else "neutral"
            horizon_stats = []
            for horizon in candidate_days:
                rets = []
                for row in rows:
                    pub_date = str(row.get("published_at") or "")[:10]
                    if not pub_date:
                        continue
                    r = forward_return(pub_date, horizon)
                    if r is not None:
                        rets.append(r)
                if len(rets) < 5:
                    continue
                abs_mean = statistics.mean(abs(x) for x in rets)
                downside = [x for x in rets if x < 0]
                downside_mean = abs(statistics.mean(downside)) if downside else 0.0
                dispersion = statistics.pstdev(rets) if len(rets) > 1 else 0.0
                score = abs_mean + 0.6 * downside_mean - 0.3 * dispersion
                horizon_stats.append(
                    {
                        "horizon_days": horizon,
                        "sample_count": len(rets),
                        "avg_abs_return": round(abs_mean, 6),
                        "avg_downside_return": round(downside_mean, 6),
                        "dispersion": round(dispersion, 6),
                        "calibration_score": round(score, 6),
                    }
                )
            if not horizon_stats:
                continue
            best = sorted(horizon_stats, key=lambda x: x["calibration_score"], reverse=True)[0]
            version_id = "win.v03"
            window_version_table.append(
                {
                    "version_id": version_id,
                    "event_type": event_type,
                    "asset_bucket": asset_bucket,
                    "market_period": market_period,
                    "recommended_horizon_days": best["horizon_days"],
                    "recommended_window_range": map_window(best["horizon_days"]),
                    "confidence": round(min(1.0, best["sample_count"] / 40.0), 4),
                    "sample_count": int(best["sample_count"]),
                    "stats": horizon_stats,
                }
            )
        return {
            "generated_at": datetime.now().isoformat(),
            "candidate_horizon_days": candidate_days,
            "event_type_profiles": sorted(calibration_rows, key=lambda x: x["event_type"]),
            "window_version_table": sorted(
                window_version_table,
                key=lambda x: (x["event_type"], x["asset_bucket"], x["market_period"]),
            ),
        }


def run_backtest_example(ledger_path: Optional[Path] = None, result_file: Optional[Path] = None):
    """运行回测示例"""
    data_dir = Path(__file__).parent.parent / "historical_data"
    ledger_dir = Path(__file__).parent.parent / "raw"

    # 查找最新的 JSONL 文件
    ledger_files = sorted(ledger_dir.glob("event_ledger_*.jsonl"))

    if ledger_path is None:
        if not ledger_files:
            print("[ERROR] 未找到事件账本文件，请先运行 event_ledger_generator.py")
            return None
        ledger_path = ledger_files[-1]
    print(f"[INFO] 使用事件账本：{ledger_path}")

    config = BacktestConfig(
        start_date="2025-12-09",
        end_date="2026-03-08",
        initial_capital=100000,
        transaction_cost=0.001,
        lookback_days=7
    )

    backtester = EventLedgerBacktester(config)
    result = backtester.run_backtest(ledger_path, data_dir)

    print(backtester.generate_report(result))

    # 保存结果
    result_summary = {
        "backtest_config": asdict(config),
        "results": {
            "total_return": result.total_return,
            "annualized_return": result.annualized_return,
            "sharpe_ratio": result.sharpe_ratio,
            "max_drawdown": result.max_drawdown,
            "win_rate": result.win_rate,
            "profit_factor": result.profit_factor,
            "total_trades": result.total_trades
        },
        "event_stats": result.event_stats
    }

    if result_file is None:
        stem = ledger_path.stem
        safe = stem.replace("event_ledger_", "").replace("event_ledger_backtest_", "backtest_")
        result_file = data_dir / f"backtest_result_{safe}.json"
    with open(result_file, 'w', encoding='utf-8') as f:
        json.dump(result_summary, f, indent=2, ensure_ascii=False)

    print(f"\n[✓] 回测结果已保存：{result_file}")

    return result


def run_window_calibration_example(ledger_path: Optional[Path] = None):
    data_dir = Path(__file__).parent.parent / "historical_data"
    ledger_dir = Path(__file__).parent.parent / "raw"
    ledger_files = sorted(ledger_dir.glob("event_ledger_*.jsonl"))
    if ledger_path is None:
        if not ledger_files:
            print("[ERROR] 未找到事件账本文件")
            return None
        ledger_path = ledger_files[-1]
    print(f"[INFO] 校准窗口使用账本：{ledger_path}")
    config = BacktestConfig(start_date="2025-12-09", end_date="2026-03-08")
    backtester = EventLedgerBacktester(config)
    entries = backtester.load_ledger(ledger_path)
    prices = backtester.load_prices(data_dir)
    if not entries or not prices:
        print("[ERROR] 校准输入不足")
        return None
    calibration = backtester.calibrate_event_windows(entries, prices)
    ts = datetime.now().strftime("%Y%m%d_%H%M")
    raw_out = Path(__file__).parent.parent / "raw" / f"window_calibration_{ts}.json"
    raw_out.parent.mkdir(parents=True, exist_ok=True)
    with open(raw_out, "w", encoding="utf-8") as f:
        json.dump(calibration, f, indent=2, ensure_ascii=False)
    window_version_table = list(calibration.get("window_version_table") or [])
    version_table_out = Path(__file__).parent.parent / "raw" / f"window_version_table_{ts}.json"
    with open(version_table_out, "w", encoding="utf-8") as f:
        json.dump(
            {
                "generated_at": calibration.get("generated_at"),
                "rows": window_version_table,
                "row_count": len(window_version_table),
            },
            f,
            indent=2,
            ensure_ascii=False,
        )
    profile_out = data_dir / "window_profile_v03.json"
    with open(profile_out, "w", encoding="utf-8") as f:
        json.dump(calibration, f, indent=2, ensure_ascii=False)
    print(f"[✓] 窗口校准结果已保存：{raw_out}")
    print(f"[✓] 窗口版本表已保存：{version_table_out}")
    print(f"[✓] 窗口画像已更新：{profile_out}")
    return calibration


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="事件账本回测/窗口校准工具")
    parser.add_argument("--calibrate-window", action="store_true", help="执行窗口校准并输出窗口画像")
    parser.add_argument("--ledger-path", type=str, default="", help="指定账本文件路径")
    parser.add_argument("--result-file", type=str, default="", help="指定回测结果输出 JSON 路径")
    args = parser.parse_args()
    selected_ledger = Path(args.ledger_path) if args.ledger_path else None
    selected_result = Path(args.result_file) if args.result_file else None
    if args.calibrate_window:
        run_window_calibration_example(selected_ledger)
    else:
        run_backtest_example(selected_ledger, selected_result)
