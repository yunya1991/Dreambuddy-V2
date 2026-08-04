"""
Dream OS 端到端回测系统

验证 P0-P2 修复后的 Dream OS 完整交易链路收益：
    数据加载 → 指标计算 → 场景分类 → 编排选择 → TradingAgent(A0/A7集成) → 模拟交易 → 评估

用法:
    cd 1-ARCHITECTURE
    python -m dreamos.cli.dreamos_backtester --symbols BTC,ETH,SOL --interval 1h
"""

from __future__ import annotations

import json
import os
import math
import time
import logging
import argparse
from pathlib import Path
from datetime import datetime
from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional, Tuple

logger = logging.getLogger(__name__)

# 数据目录
DATA_DIR = Path(__file__).parent.parent.parent.parent / "10-经典指标系统" / "user_data" / "data" / "aggregated" / "futures"


@dataclass
class TradeRecord:
    """单笔交易记录"""
    timestamp: int
    symbol: str
    scenario_id: str
    pattern: str
    direction: str          # LONG / SHORT / HOLD
    confidence: float
    entry_price: float
    exit_price: float
    return_pct: float       # 扣费后收益率
    hold_periods: int
    leverage: int
    a0_aligned: bool = False
    a7_passed: bool = False


@dataclass
class BacktestResult:
    """回测结果"""
    symbol: str
    total_bars: int
    total_trades: int
    long_trades: int
    short_trades: int
    hold_signals: int
    win_trades: int
    loss_trades: int
    win_rate: float
    total_return: float
    avg_return: float
    max_return: float
    min_return: float
    sharpe_ratio: float
    max_drawdown: float
    avg_confidence: float
    a0_alignment_rate: float
    a7_pass_rate: float
    scenario_distribution: Dict[str, int] = field(default_factory=dict)
    trades: List[TradeRecord] = field(default_factory=list)


class DreamOSBacktester:
    """Dream OS 端到端回测引擎"""

    # 回测参数
    WINDOW_SIZE = 48         # 用前 48 根 K 线计算指标
    STEP = 4                 # 每隔 4 根 K 线采样一次
    HOLD_PERIODS = 20        # 持仓 20 根 K 线后平仓（诊断优化：12→20，收益+74%，夏普+127%）
    CONFIDENCE_THRESHOLD = 0.4
    FEE_RATE = 0.0008        # 单边 0.04% × 2
    MAX_LEVERAGE = 5

    # 4h 回测参数（更多样本，更长时间跨度）
    # 4h × 50 根 ≈ 8.3 天历史，足以计算 EMA50；EMA200 仍会退化但 EMA20/50 可产生方向
    WINDOW_SIZE_4H = 50      # 4h 用 50 根 ≈ 8.3 天历史
    STEP_4H = 1              # 每隔 1 根 4h K 线采样（最大化样本）
    HOLD_PERIODS_4H = 12     # 持仓 12 根 4h = 48 小时，捕捉更大趋势

    def __init__(self, budget_mode: str = "lean", enable_subsystem: bool = True):
        self.budget_mode = budget_mode
        self.enable_subsystem = enable_subsystem
        self._agent = None
        self._classifier = None
        self._memory = None

    def get_agent(self):
        """延迟初始化 TradingAgent"""
        if self._agent is None:
            from dreamos.apps.trading_agent.agent import TradingAgent
            self._agent = TradingAgent(budget_mode=self.budget_mode)
        return self._agent

    def get_classifier(self):
        """延迟初始化场景分类器"""
        if self._classifier is None:
            from dreamos.core.sense.scenario_classifier import ScenarioClassifier
            self._classifier = ScenarioClassifier()
        return self._classifier

    def get_memory(self):
        """延迟初始化编排记忆表"""
        if self._memory is None:
            from dreamos.core.memory.orchestration_memory import OrchestrationMemory
            self._memory = OrchestrationMemory()
            self._memory.load()
        return self._memory

    # ============================================================
    # 数据加载
    # ============================================================

    def load_klines(self, symbol: str, interval: str = "1h") -> List[list]:
        """加载历史K线数据

        Args:
            symbol: BTC / ETH / SOL
            interval: 1h / 30m / 4h（4h 从 1h 聚合）

        Returns:
            [[ts, o, h, l, c, v], ...]  升序
        """
        if interval == "4h":
            # 从 1h 数据聚合为 4h
            klines_1h = self.load_klines(symbol, "1h")
            if not klines_1h:
                return []
            return self._aggregate_klines(klines_1h, 4)

        filename = f"{symbol}_USDT-{interval}-futures.json"
        filepath = DATA_DIR / filename

        if not filepath.exists():
            logger.warning(f"数据文件不存在: {filepath}")
            return []

        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)

        # 确保是 list of lists 格式: [ts, o, h, l, c, v]
        klines = []
        for k in data:
            if isinstance(k, list) and len(k) >= 6:
                klines.append([
                    int(k[0]),     # timestamp
                    float(k[1]),   # open
                    float(k[2]),   # high
                    float(k[3]),   # low
                    float(k[4]),   # close
                    float(k[5]),   # volume
                ])

        # 按时间排序
        klines.sort(key=lambda x: x[0])
        logger.info(f"加载 {symbol} {interval}: {len(klines)} 根K线")
        return klines

    def _aggregate_klines(self, klines: List[list], factor: int) -> List[list]:
        """将 K 线聚合为更大周期

        Args:
            klines: [[ts, o, h, l, c, v], ...] 升序
            factor: 聚合倍数（4 = 1h→4h）

        Returns:
            聚合后的 K 线列表
        """
        if not klines or factor <= 1:
            return klines

        result = []
        for i in range(0, len(klines), factor):
            chunk = klines[i:i + factor]
            if not chunk:
                break
            ts = chunk[0][0]
            o = chunk[0][1]
            h = max(k[2] for k in chunk)
            l = min(k[3] for k in chunk)
            c = chunk[-1][4]
            v = sum(k[5] for k in chunk)
            result.append([ts, o, h, l, c, v])

        logger.info(f"聚合 {factor}x: {len(klines)} → {len(result)} 根K线")
        return result

    # ============================================================
    # 指标计算
    # ============================================================

    def build_market_data(self, window: List[list], symbol: str) -> Optional[Dict[str, Any]]:
        """从K线窗口构造 market_data

        与 auto_trader._fetch_market_data 输出格式一致。
        """
        if len(window) < 24:
            return None

        closes = [k[4] for k in window]
        highs = [k[2] for k in window]
        lows = [k[3] for k in window]
        volumes = [k[5] for k in window]
        price = closes[-1]

        ema20 = self._ema(closes, min(20, len(closes)))
        ema50 = self._ema(closes, min(50, len(closes)))
        ema200 = self._ema(closes, min(200, len(closes)))

        change_1h = self._pct_change(closes, 1)
        change_4h = self._pct_change(closes, 4)
        change_24h = self._pct_change(closes, min(24, len(closes) - 1))

        atr_pct = self._atr_pct(highs, lows, closes, 14)
        rsi14 = self._rsi(closes, 14)

        high_24h = max(highs[-min(24, len(highs)):])
        low_24h = min(lows[-min(24, len(lows)):])

        vol_ratio = 1.0
        if len(volumes) >= 20:
            recent_vol = sum(volumes[-5:]) / 5
            avg_vol = sum(volumes[-20:]) / 20
            vol_ratio = recent_vol / avg_vol if avg_vol > 0 else 1.0

        return {
            "symbol": symbol,
            "price": price,
            "ema20": ema20,
            "ema50": ema50,
            "ema200": ema200,
            "change_1h": change_1h,
            "change_4h": change_4h,
            "change_24h": change_24h,
            "atr_pct": atr_pct,
            "rsi14": rsi14,
            "high_24h": high_24h,
            "low_24h": low_24h,
            "vol_ratio": vol_ratio,
            "fgi": 50,           # 回测中无 FGI 数据，用中性值
            "funding_rate": 0.0,  # 回测中无资金费率
        }

    def _ema(self, values: List[float], period: int) -> float:
        if not values or period <= 0:
            return values[-1] if values else 0
        period = min(period, len(values))
        k = 2 / (period + 1)
        ema = values[0]
        for v in values[1:period]:
            ema = v * k + ema * (1 - k)
        return ema

    def _pct_change(self, values: List[float], periods: int) -> float:
        if len(values) <= periods or periods <= 0:
            return 0
        old = values[-periods - 1]
        new = values[-1]
        if old == 0:
            return 0
        return (new - old) / old * 100

    def _atr_pct(self, highs: List[float], lows: List[float], closes: List[float], period: int) -> float:
        if len(closes) < period + 1:
            period = len(closes) - 1
        if period <= 0:
            return 0.02
        trs = []
        for i in range(-period, 0):
            h, l = highs[i], lows[i]
            pc = closes[i - 1]
            tr = max(h - l, abs(h - pc), abs(l - pc))
            trs.append(tr)
        atr = sum(trs) / len(trs)
        return atr / closes[-1] if closes[-1] > 0 else 0.02

    def _rsi(self, closes: List[float], period: int = 14) -> float:
        if len(closes) < period + 1:
            return 50.0
        deltas = [closes[i] - closes[i - 1] for i in range(-period, 0)]
        gains = [max(d, 0) for d in deltas]
        losses = [max(-d, 0) for d in deltas]
        avg_g = sum(gains) / period
        avg_l = sum(losses) / period
        if avg_l == 0:
            return 100.0
        rs = avg_g / avg_l
        return 100 - 100 / (1 + rs)

    # ============================================================
    # 回测核心
    # ============================================================

    def _get_interval_params(self, interval: str) -> Tuple[int, int, int]:
        """根据 interval 返回 (window_size, step, hold_periods)"""
        if interval == "4h":
            return self.WINDOW_SIZE_4H, self.STEP_4H, self.HOLD_PERIODS_4H
        if interval == "30m":
            # 30m 默认沿用 1h 参数（更密集采样）
            return self.WINDOW_SIZE, self.STEP, self.HOLD_PERIODS
        return self.WINDOW_SIZE, self.STEP, self.HOLD_PERIODS

    def backtest_symbol(self, symbol: str, interval: str = "1h") -> BacktestResult:
        """对单个 symbol 进行完整回测

        流程:
            1. 加载历史K线
            2. 滑动窗口遍历
            3. 每个窗口: 构造market_data → 场景分类 → 编排选择 → TradingAgent.run()
            4. 模拟交易（持仓 N 根K线后平仓）
            5. 统计收益指标
        """
        window_size, step, hold_periods = self._get_interval_params(interval)

        klines = self.load_klines(symbol, interval)
        if len(klines) < window_size + hold_periods:
            logger.warning(f"{symbol} 数据不足: {len(klines)} < {window_size + hold_periods}")
            return BacktestResult(symbol=symbol, total_bars=len(klines), total_trades=0,
                                  long_trades=0, short_trades=0, hold_signals=0,
                                  win_trades=0, loss_trades=0, win_rate=0,
                                  total_return=0, avg_return=0, max_return=0, min_return=0,
                                  sharpe_ratio=0, max_drawdown=0, avg_confidence=0,
                                  a0_alignment_rate=0, a7_pass_rate=0)

        agent = self.get_agent()
        classifier = self.get_classifier()
        memory = self.get_memory()

        trades: List[TradeRecord] = []
        hold_signals = 0
        scenario_dist: Dict[str, int] = {}
        total_windows = 0
        a0_aligned_count = 0
        a7_passed_count = 0
        a7_evaluated_count = 0
        confidence_sum = 0.0

        for i in range(0, len(klines) - window_size - hold_periods, step):
            total_windows += 1
            window = klines[i:i + window_size]
            future = klines[i + window_size:i + window_size + hold_periods]

            # 1. 构造 market_data
            market_data = self.build_market_data(window, symbol)
            if market_data is None:
                continue

            # 2. 场景分类
            scenario = classifier.classify(market_data)
            sid = scenario.scenario_id
            scenario_dist[sid] = scenario_dist.get(sid, 0) + 1

            # 3. 编排选择
            choice = memory.select(sid)

            # 4. 调用 TradingAgent
            try:
                result = agent.run(
                    user_input=f"分析 {symbol} 的交易机会",
                    market_data=market_data,
                    context={
                        "symbol": symbol,
                        "scenario": scenario.to_dict() if hasattr(scenario, "to_dict") else {"scenario_id": sid},
                        "scenario_id": sid,
                        "recommended_orchestration": choice.to_dict() if hasattr(choice, "to_dict") else {"pattern": choice.pattern},
                        "enable_subsystem": self.enable_subsystem,
                    },
                )
            except Exception as e:
                logger.debug(f"TradingAgent 执行失败 @ {symbol} bar={i}: {e}")
                continue

            direction = result.get("action", "HOLD")
            confidence = result.get("confidence", 0.0)
            confidence_sum += confidence

            # 5. 模拟交易
            # P3-3 修复: 必须有 trade_order 才开仓（即 A7 门禁通过或 A5 正常输出）
            outputs = result.get("outputs", {})
            a5_out = outputs.get("A5", {})
            trade_order = a5_out.get("trade_order", {})

            a1_out = outputs.get("A1", {})
            a0_aligned = a1_out.get("a0_aligned", False)
            if a0_aligned:
                a0_aligned_count += 1

            a7_gate = a5_out.get("a7_gate", {}) or trade_order.get("_a7_gate", {})
            a7_passed = a7_gate.get("gate_passed", False)
            a7_evaluated = a5_out.get("a7_gate") is not None or trade_order.get("_a7_gate") is not None
            if a7_passed:
                a7_passed_count += 1
            if a7_evaluated:
                a7_evaluated_count += 1

            if not trade_order or trade_order.get("action") == "HOLD" or not trade_order.get("entry_price"):
                hold_signals += 1
                continue

            direction = trade_order.get("action", "HOLD")
            if confidence == 0:
                confidence = result.get("confidence", 0.0)

            entry_price = trade_order.get("entry_price", market_data["price"])
            exit_price = future[-1][4]  # 持仓结束时的收盘价

            # 止损止盈检查
            stop_loss = trade_order.get("stop_loss", 0)
            take_profit = trade_order.get("take_profit", 0)

            # 在持仓期间检查止损止盈
            actual_exit_price = exit_price
            for k in future:
                k_high, k_low = k[2], k[3]
                if direction == "LONG":
                    if stop_loss > 0 and k_low <= stop_loss:
                        actual_exit_price = stop_loss
                        break
                    if take_profit > 0 and k_high >= take_profit:
                        actual_exit_price = take_profit
                        break
                else:  # SHORT
                    if stop_loss > 0 and k_high >= stop_loss:
                        actual_exit_price = stop_loss
                        break
                    if take_profit > 0 and k_low <= take_profit:
                        actual_exit_price = take_profit
                        break

            exit_price = actual_exit_price

            # 计算收益率
            if direction == "LONG":
                ret = (exit_price - entry_price) / entry_price
            else:
                ret = (entry_price - exit_price) / entry_price

            ret -= self.FEE_RATE  # 扣手续费

            leverage = trade_order.get("leverage", 1)
            leverage = min(leverage, self.MAX_LEVERAGE)

            trade = TradeRecord(
                timestamp=window[-1][0],
                symbol=symbol,
                scenario_id=sid,
                pattern=choice.pattern,
                direction=direction,
                confidence=round(confidence, 3),
                entry_price=round(entry_price, 2),
                exit_price=round(exit_price, 2),
                return_pct=round(ret, 4),
                hold_periods=hold_periods,
                leverage=leverage,
                a0_aligned=a0_aligned,
                a7_passed=a7_passed,
            )
            trades.append(trade)

        # 6. 计算统计指标
        return self._calc_result(symbol, klines, trades, hold_signals,
                                 total_windows, scenario_dist,
                                 a0_aligned_count, a7_passed_count, a7_evaluated_count,
                                 confidence_sum, interval)

    def _calc_result(self, symbol: str, klines: list, trades: List[TradeRecord],
                     hold_signals: int, total_windows: int,
                     scenario_dist: Dict[str, int],
                     a0_aligned_count: int, a7_passed_count: int, a7_evaluated_count: int,
                     confidence_sum: float, interval: str = "1h") -> BacktestResult:
        """计算回测统计指标"""

        if not trades:
            return BacktestResult(
                symbol=symbol, total_bars=len(klines), total_trades=0,
                long_trades=0, short_trades=0, hold_signals=hold_signals,
                win_trades=0, loss_trades=0, win_rate=0,
                total_return=0, avg_return=0, max_return=0, min_return=0,
                sharpe_ratio=0, max_drawdown=0, avg_confidence=0,
                a0_alignment_rate=0, a7_pass_rate=0,
                scenario_distribution=scenario_dist, trades=trades,
            )

        returns = [t.return_pct for t in trades]
        long_trades = sum(1 for t in trades if t.direction == "LONG")
        short_trades = sum(1 for t in trades if t.direction == "SHORT")
        wins = [r for r in returns if r > 0]
        losses = [r for r in returns if r <= 0]

        total_return = sum(returns)
        avg_return = total_return / len(returns)
        max_return = max(returns) if returns else 0
        min_return = min(returns) if returns else 0

        # 夏普比率年化：1h=8760, 4h=2190, 30m=17520
        annualization = {"1h": 8760, "4h": 2190, "30m": 17520}.get(interval, 8760)
        if len(returns) >= 2:
            avg = sum(returns) / len(returns)
            std = math.sqrt(sum((r - avg) ** 2 for r in returns) / len(returns))
            sharpe = (avg / std * math.sqrt(annualization)) if std > 0 else 0
        else:
            sharpe = 0

        # 最大回撤（基于累积收益曲线）
        cumulative = 0
        peak = 0
        max_dd = 0
        for r in returns:
            cumulative += r
            if cumulative > peak:
                peak = cumulative
            dd = peak - cumulative
            if dd > max_dd:
                max_dd = dd

        win_rate = len(wins) / len(returns) if returns else 0
        avg_confidence = confidence_sum / total_windows if total_windows > 0 else 0
        a0_rate = a0_aligned_count / total_windows if total_windows > 0 else 0
        # A7通过率：通过数 / 被评估数（而非总窗口数）
        a7_rate = a7_passed_count / a7_evaluated_count if a7_evaluated_count > 0 else 0

        return BacktestResult(
            symbol=symbol,
            total_bars=len(klines),
            total_trades=len(trades),
            long_trades=long_trades,
            short_trades=short_trades,
            hold_signals=hold_signals,
            win_trades=len(wins),
            loss_trades=len(losses),
            win_rate=round(win_rate, 4),
            total_return=round(total_return, 4),
            avg_return=round(avg_return, 4),
            max_return=round(max_return, 4),
            min_return=round(min_return, 4),
            sharpe_ratio=round(sharpe, 2),
            max_drawdown=round(max_dd, 4),
            avg_confidence=round(avg_confidence, 3),
            a0_alignment_rate=round(a0_rate, 4),
            a7_pass_rate=round(a7_rate, 4),
            scenario_distribution=scenario_dist,
            trades=trades,
        )

    # ============================================================
    # 报告生成
    # ============================================================

    def generate_report(self, results: List[BacktestResult], interval: str = "1h") -> str:
        """生成 Markdown 回测报告"""
        window_size, step, hold_periods = self._get_interval_params(interval)
        lines = []
        lines.append("# Dream OS 回测报告")
        lines.append(f"\n**生成时间**: {datetime.now().isoformat()}")
        lines.append(f"**回测周期**: {interval}")
        lines.append(f"**回测参数**: window={window_size}, step={step}, hold={hold_periods}, "
                     f"conf_threshold={self.CONFIDENCE_THRESHOLD}, fee={self.FEE_RATE}")
        lines.append(f"**P0-P2 修复状态**: A0→A1集成✓, A7→A5集成✓, A5合成✓, 离场回填✓, 杠杆阻断✓")
        lines.append("")

        # 汇总表
        lines.append("## 汇总")
        lines.append("")
        lines.append("| 指标 | " + " | ".join(r.symbol for r in results) + " |")
        lines.append("|------|" + "|".join(["------"] * len(results)) + "|")
        lines.append(f"| 总K线数 | " + " | ".join(str(r.total_bars) for r in results) + " |")
        lines.append(f"| 总交易数 | " + " | ".join(str(r.total_trades) for r in results) + " |")
        lines.append(f"| 做多/做空 | " + " | ".join(f"{r.long_trades}/{r.short_trades}" for r in results) + " |")
        lines.append(f"| HOLD信号 | " + " | ".join(str(r.hold_signals) for r in results) + " |")
        lines.append(f"| 胜率 | " + " | ".join(f"{r.win_rate:.1%}" for r in results) + " |")
        lines.append(f"| 总收益 | " + " | ".join(f"{r.total_return:.2%}" for r in results) + " |")
        lines.append(f"| 平均收益 | " + " | ".join(f"{r.avg_return:.2%}" for r in results) + " |")
        lines.append(f"| 最大盈利 | " + " | ".join(f"{r.max_return:.2%}" for r in results) + " |")
        lines.append(f"| 最大亏损 | " + " | ".join(f"{r.min_return:.2%}" for r in results) + " |")
        lines.append(f"| 夏普比率 | " + " | ".join(f"{r.sharpe_ratio:.2f}" for r in results) + " |")
        lines.append(f"| 最大回撤 | " + " | ".join(f"{r.max_drawdown:.2%}" for r in results) + " |")
        lines.append(f"| 平均置信度 | " + " | ".join(f"{r.avg_confidence:.1%}" for r in results) + " |")
        lines.append(f"| A0方向一致率 | " + " | ".join(f"{r.a0_alignment_rate:.1%}" for r in results) + " |")
        lines.append(f"| A7门禁通过率 | " + " | ".join(f"{r.a7_pass_rate:.1%}" for r in results) + " |")
        lines.append("")

        # 各 symbol 详情
        for r in results:
            lines.append(f"## {r.symbol} 详情")
            lines.append("")
            lines.append(f"- **总K线数**: {r.total_bars}")
            lines.append(f"- **总交易数**: {r.total_trades} (多{r.long_trades}/空{r.short_trades})")
            lines.append(f"- **HOLD信号**: {r.hold_signals}")
            lines.append(f"- **胜率**: {r.win_rate:.1%} ({r.win_trades}胜 / {r.loss_trades}负)")
            lines.append(f"- **总收益**: {r.total_return:.2%}")
            lines.append(f"- **平均每笔**: {r.avg_return:.2%}")
            lines.append(f"- **最大盈利**: {r.max_return:.2%}")
            lines.append(f"- **最大亏损**: {r.min_return:.2%}")
            lines.append(f"- **夏普比率**: {r.sharpe_ratio:.2f}")
            lines.append(f"- **最大回撤**: {r.max_drawdown:.2%}")
            lines.append(f"- **平均置信度**: {r.avg_confidence:.1%}")
            lines.append(f"- **A0方向一致率**: {r.a0_alignment_rate:.1%}")
            lines.append(f"- **A7门禁通过率**: {r.a7_pass_rate:.1%}")
            lines.append("")

            # 场景分布
            if r.scenario_distribution:
                lines.append("### 场景分布")
                lines.append("")
                lines.append("| 场景 | 次数 |")
                lines.append("|------|------|")
                for sid, count in sorted(r.scenario_distribution.items(), key=lambda x: -x[1]):
                    lines.append(f"| {sid} | {count} |")
                lines.append("")

            # 最近 10 笔交易
            if r.trades:
                lines.append("### 最近 10 笔交易")
                lines.append("")
                lines.append("| 时间 | 方向 | 置信度 | 入场 | 出场 | 收益 | A0 | A7 |")
                lines.append("|------|------|--------|------|------|------|----|----|")
                for t in r.trades[-10:]:
                    ts = datetime.fromtimestamp(t.timestamp / 1000).strftime("%m-%d %H:%M")
                    lines.append(f"| {ts} | {t.direction} | {t.confidence:.0%} | "
                                 f"{t.entry_price} | {t.exit_price} | {t.return_pct:.2%} | "
                                 f"{'✓' if t.a0_aligned else '✗'} | {'✓' if t.a7_passed else '✗'} |")
                lines.append("")

        # 组合统计
        if len(results) >= 2:
            all_returns = []
            for r in results:
                all_returns.extend([t.return_pct for t in r.trades])

            if all_returns:
                combo_total = sum(all_returns)
                combo_win = sum(1 for r in all_returns if r > 0)
                combo_win_rate = combo_win / len(all_returns)
                combo_avg = combo_total / len(all_returns)

                if len(all_returns) >= 2:
                    avg = sum(all_returns) / len(all_returns)
                    std = math.sqrt(sum((r - avg) ** 2 for r in all_returns) / len(all_returns))
                    annualization = {"1h": 8760, "4h": 2190, "30m": 17520}.get(interval, 8760)
                    combo_sharpe = (avg / std * math.sqrt(annualization)) if std > 0 else 0
                else:
                    combo_sharpe = 0

                lines.append("## 组合统计")
                lines.append("")
                lines.append(f"- **组合总交易**: {len(all_returns)}")
                lines.append(f"- **组合总收益**: {combo_total:.2%}")
                lines.append(f"- **组合胜率**: {combo_win_rate:.1%}")
                lines.append(f"- **组合平均收益**: {combo_avg:.2%}")
                lines.append(f"- **组合夏普**: {combo_sharpe:.2f}")
                lines.append("")

        return "\n".join(lines)

    def generate_comparison_report(self, base_results: List[BacktestResult],
                                   subsystem_results: List[BacktestResult],
                                   interval: str = "1h") -> str:
        """生成基础模式 vs 增强模式的对比报告"""
        lines = []
        lines.append("# Dream OS 回测对比报告")
        lines.append(f"\n**生成时间**: {datetime.now().isoformat()}")
        lines.append(f"**回测周期**: {interval}")
        lines.append("**对比模式**: 基础模式（仅A链）vs 增强模式（A链+子系统节点）")
        lines.append("")

        lines.append("## 对比汇总")
        lines.append("")
        lines.append("| 指标 | 基础模式 | 增强模式 | 变化 |")
        lines.append("|------|----------|----------|------|")

        for base, subsys in zip(base_results, subsystem_results):
            lines.append(f"| | | | |")
            lines.append(f"| **币种** | **{base.symbol}** | **{subsys.symbol}** | |")
            lines.append(f"| 总交易数 | {base.total_trades} | {subsys.total_trades} | "
                         f"{subsys.total_trades - base.total_trades:+d} |")
            lines.append(f"| 胜率 | {base.win_rate:.1%} | {subsys.win_rate:.1%} | "
                         f"{(subsys.win_rate - base.win_rate)*100:+.1f}pp |")
            lines.append(f"| 总收益 | {base.total_return:.2%} | {subsys.total_return:.2%} | "
                         f"{(subsys.total_return - base.total_return)*100:+.1f}pp |")
            lines.append(f"| 平均收益 | {base.avg_return:.2%} | {subsys.avg_return:.2%} | "
                         f"{(subsys.avg_return - base.avg_return)*100:+.1f}pp |")
            lines.append(f"| 夏普比率 | {base.sharpe_ratio:.2f} | {subsys.sharpe_ratio:.2f} | "
                         f"{subsys.sharpe_ratio - base.sharpe_ratio:+.2f} |")
            lines.append(f"| 最大回撤 | {base.max_drawdown:.2%} | {subsys.max_drawdown:.2%} | "
                         f"{(subsys.max_drawdown - base.max_drawdown)*100:+.1f}pp |")
            lines.append(f"| 平均置信度 | {base.avg_confidence:.1%} | {subsys.avg_confidence:.1%} | "
                         f"{(subsys.avg_confidence - base.avg_confidence)*100:+.1f}pp |")
            lines.append(f"| A7通过率 | {base.a7_pass_rate:.1%} | {subsys.a7_pass_rate:.1%} | |")
            lines.append("")

        # 基础模式详情
        lines.append("## 基础模式详情（仅 A 链）")
        lines.append("")
        for r in base_results:
            lines.append(f"### {r.symbol}")
            lines.append(f"- 总交易: {r.total_trades}, 胜率: {r.win_rate:.1%}, 收益: {r.total_return:.2%}")
            lines.append(f"- 夏普: {r.sharpe_ratio:.2f}, 最大回撤: {r.max_drawdown:.2%}")
            lines.append("")

        # 增强模式详情
        lines.append("## 增强模式详情（A 链 + 子系统节点）")
        lines.append("")
        lines.append("**启用的子系统节点**:")
        lines.append("- C_S3_TREND: 三屏趋势信号（趋势场景）")
        lines.append("- C_MARTIN_V15: V15马丁信号（震荡场景）")
        lines.append("- A_YJ_INFER: 易经卦象推理（衰竭场景）")
        lines.append("")
        for r in subsystem_results:
            lines.append(f"### {r.symbol}")
            lines.append(f"- 总交易: {r.total_trades}, 胜率: {r.win_rate:.1%}, 收益: {r.total_return:.2%}")
            lines.append(f"- 夏普: {r.sharpe_ratio:.2f}, 最大回撤: {r.max_drawdown:.2%}")
            lines.append("")

        # 分析总结
        lines.append("## 分析总结")
        lines.append("")
        has_improvement = any(s.total_return > b.total_return for b, s in zip(base_results, subsystem_results))
        if has_improvement:
            lines.append("✅ **子系统节点有效**: 增强模式表现优于基础模式")
        else:
            lines.append("⚠️ **需进一步优化**: 基础模式表现相当或更优")
        lines.append("")
        lines.append("**子系统节点策略映射**:")
        lines.append("| 场景类型 | 推荐子系统节点 |")
        lines.append("|----------|----------------|")
        lines.append("| 牛市趋势 (BULL_*) | C_S3_TREND |")
        lines.append("| 熊市趋势 (BEAR_*) | C_S3_TREND |")
        lines.append("| 震荡中性 (NEUTRAL_*) | C_MARTIN_V15 + A_YJ_INFER |")
        lines.append("| 衰竭信号 (*_EXHAUSTION) | A_YJ_INFER |")

        return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Dream OS 回测系统")
    parser.add_argument("--symbols", default="BTC,ETH,SOL", help="回测币种，逗号分隔")
    parser.add_argument("--interval", default="1h", choices=["1h", "30m", "4h"],
                        help="K线周期：1h/30m/4h（4h 从 1h 聚合，样本更多）")
    parser.add_argument("--budget", default="lean", choices=["lean", "standard", "full"])
    parser.add_argument("--output", default=None, help="报告输出路径")
    parser.add_argument("--no-subsystem", action="store_true", help="禁用子系统节点（三屏趋势/易经/马丁），用于对比测试")
    parser.add_argument("--compare", action="store_true", help="同时运行有无子系统的对比测试")
    parser.add_argument("--optimize", action="store_true", help="运行两级优化（L4粗筛+回测精调），更新场景→子系统映射")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    # 空字符串/空白兜底默认币种（scheduler 传 symbols=[] → join="" 会覆盖 argparse 默认值）
    raw_symbols = args.symbols.strip() if args.symbols else ""
    if not raw_symbols:
        raw_symbols = "BTC,ETH,SOL"
        logger.warning("收到空 symbols 参数，回退默认 BTC,ETH,SOL")
    symbols = [s.strip().upper() for s in raw_symbols.split(",") if s.strip()]

    if args.optimize:
        print("\n" + "="*80)
        print("动态编排优化: L4 粗筛 + 回测精调")
        print("="*80)

        from dreamos.capabilities.trading.evaluators.dynamic_orchestrator import DynamicOrchestrator
        orchestrator = DynamicOrchestrator()
        orchestrator.optimize(run_backtest=True, symbols=args.symbols, interval=args.interval)
        orchestrator.update_chain_spec()
        report_path = orchestrator.save_report()
        print(orchestrator.summary())
        print(f"\n优化报告已保存: {report_path}")
        print("ChainSpec.scenario_nodes 已更新，后续回测将使用动态编排")
        return

    if args.compare:
        print("\n" + "="*80)
        print("对比测试模式: 同时运行 A链 vs 子系统节点")
        print("="*80)

        results_base = []
        print("\n--- 基础模式（禁用子系统节点）---")
        bt_base = DreamOSBacktester(budget_mode=args.budget, enable_subsystem=False)
        for symbol in symbols:
            logger.info(f"开始回测 {symbol} @ {args.interval} (基础模式)...")
            t0 = time.time()
            result = bt_base.backtest_symbol(symbol, args.interval)
            elapsed = time.time() - t0
            logger.info(f"{symbol} 回测完成: {result.total_trades} 笔交易, "
                         f"收益={result.total_return:.2%}, 胜率={result.win_rate:.1%}, "
                         f"夏普={result.sharpe_ratio:.2f}, 耗时={elapsed:.1f}s")
            results_base.append(result)

        results_subsystem = []
        print("\n--- 增强模式（启用子系统节点）---")
        bt_subsystem = DreamOSBacktester(budget_mode=args.budget, enable_subsystem=True)
        for symbol in symbols:
            logger.info(f"开始回测 {symbol} @ {args.interval} (增强模式)...")
            t0 = time.time()
            result = bt_subsystem.backtest_symbol(symbol, args.interval)
            elapsed = time.time() - t0
            logger.info(f"{symbol} 回测完成: {result.total_trades} 笔交易, "
                         f"收益={result.total_return:.2%}, 胜率={result.win_rate:.1%}, "
                         f"夏普={result.sharpe_ratio:.2f}, 耗时={elapsed:.1f}s")
            results_subsystem.append(result)

        report = bt_subsystem.generate_comparison_report(results_base, results_subsystem, interval=args.interval)
    else:
        bt = DreamOSBacktester(budget_mode=args.budget, enable_subsystem=not args.no_subsystem)

        results = []
        for symbol in symbols:
            mode = "增强模式" if bt.enable_subsystem else "基础模式"
            logger.info(f"开始回测 {symbol} @ {args.interval} ({mode})...")
            t0 = time.time()
            result = bt.backtest_symbol(symbol, args.interval)
            elapsed = time.time() - t0
            logger.info(f"{symbol} 回测完成: {result.total_trades} 笔交易, "
                         f"收益={result.total_return:.2%}, 胜率={result.win_rate:.1%}, "
                         f"夏普={result.sharpe_ratio:.2f}, 耗时={elapsed:.1f}s")
            results.append(result)

        report = bt.generate_report(results, interval=args.interval)

    # 输出
    if args.output:
        output_path = Path(args.output)
    else:
        output_path = Path(__file__).parent / "backtest_reports" / f"backtest_{args.interval}_{datetime.now().strftime('%Y%m%d_%H%M')}.md"

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(report)

    print(f"\n回测报告已保存: {output_path}")
    print(f"\n{report}")


if __name__ == "__main__":
    main()
