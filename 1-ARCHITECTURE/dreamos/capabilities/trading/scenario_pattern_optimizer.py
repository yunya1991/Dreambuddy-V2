"""
场景化编排优化器

对每个场景分别测试5种编排模式，选出综合评分最高的，
更新编排记忆表，实现"不同场景用不同编排"的优化。

用法:
    cd 1-ARCHITECTURE
    python -m dreamos.capabilities.trading.scenario_pattern_optimizer --symbols BTC,ETH,SOL --interval 1h
"""

from __future__ import annotations

import json
import math
import time
import logging
from pathlib import Path
from typing import Dict, Any, List, Tuple
from datetime import datetime
from collections import defaultdict

logger = logging.getLogger(__name__)

# 5种编排模式
GRAPH_PATTERNS = {
    "c_chain":     ["C1", "C2", "C3"],
    "c_f_chain":   ["C1", "C2", "F1", "F3"],
    "full_chain":  ["C1", "C2", "F2", "G1"],
    "f_chain":     ["F1", "F2", "F3", "F4"],
    "c_g_chain":   ["C1", "C3", "G1"],
}


class ScenarioPatternOptimizer:
    """场景化编排优化器"""

    def __init__(self, data_dir: str = None):
        if data_dir is None:
            data_dir = str(Path(__file__).parent.parent.parent.parent.parent
                           / "10-经典指标系统" / "user_data" / "data" / "aggregated" / "futures")
        self.data_dir = data_dir
        self._agent = None
        self._classifier = None
        self._memory = None
        self._registry = None

    def get_agent(self):
        if self._agent is None:
            from dreamos.apps.trading_agent.agent import TradingAgent
            self._agent = TradingAgent(budget_mode="lean")
        return self._agent

    def get_classifier(self):
        if self._classifier is None:
            from dreamos.core.sense.scenario_classifier import ScenarioClassifier
            self._classifier = ScenarioClassifier()
        return self._classifier

    def get_memory(self):
        if self._memory is None:
            from dreamos.core.memory.orchestration_memory import OrchestrationMemory
            self._memory = OrchestrationMemory()
            self._memory.load()
        return self._memory

    def load_klines(self, symbol: str, interval: str = "1h") -> List[list]:
        filename = f"{symbol}_USDT-{interval}-futures.json"
        filepath = Path(self.data_dir) / filename
        if not filepath.exists():
            logger.warning(f"数据文件不存在: {filepath}")
            return []
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
        klines = []
        for k in data:
            if isinstance(k, list) and len(k) >= 6:
                klines.append([
                    int(k[0]), float(k[1]), float(k[2]), float(k[3]), float(k[4]), float(k[5])
                ])
        klines.sort(key=lambda x: x[0])
        return klines

    def build_market_data(self, window: List[list], symbol: str) -> Dict[str, Any]:
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
            "symbol": symbol, "price": price,
            "ema20": ema20, "ema50": ema50, "ema200": ema200,
            "change_1h": change_1h, "change_4h": change_4h, "change_24h": change_24h,
            "atr_pct": atr_pct, "rsi14": rsi14,
            "high_24h": high_24h, "low_24h": low_24h,
            "vol_ratio": vol_ratio, "fgi": 50, "funding_rate": 0.0,
        }

    def _ema(self, values, period):
        if not values or period <= 0:
            return values[-1] if values else 0
        period = min(period, len(values))
        k = 2 / (period + 1)
        ema = values[0]
        for v in values[1:period]:
            ema = v * k + ema * (1 - k)
        return ema

    def _pct_change(self, values, periods):
        if len(values) <= periods or periods <= 0:
            return 0
        old = values[-periods - 1]
        new = values[-1]
        return (new - old) / old * 100 if old != 0 else 0

    def _atr_pct(self, highs, lows, closes, period):
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

    def _rsi(self, closes, period=14):
        if len(closes) < period + 1:
            return 50.0
        deltas = [closes[i] - closes[i - 1] for i in range(-period, 0)]
        gains = [max(d, 0) for d in deltas]
        losses = [max(-d, 0) for d in deltas]
        avg_g = sum(gains) / period
        avg_l = sum(losses) / period
        if avg_l == 0:
            return 100.0
        return 100 - 100 / (1 + avg_g / avg_l)

    def backtest_pattern(self, symbol: str, pattern_name: str, pattern_nodes: List[str],
                         interval: str = "1h") -> Dict[str, Any]:
        """对单个symbol的单个pattern进行回测，返回各场景的交易结果"""
        window_size = 48
        step = 4
        hold_periods = 12
        fee_rate = 0.0008

        klines = self.load_klines(symbol, interval)
        if len(klines) < window_size + hold_periods:
            return {}

        agent = self.get_agent()
        classifier = self.get_classifier()

        # {scenario_id: [returns]}
        scenario_returns: Dict[str, List[float]] = defaultdict(list)
        total_windows = 0

        for i in range(0, len(klines) - window_size - hold_periods, step):
            total_windows += 1
            window = klines[i:i + window_size]
            future = klines[i + window_size:i + window_size + hold_periods]

            market_data = self.build_market_data(window, symbol)
            if market_data is None:
                continue

            scenario = classifier.classify(market_data)
            sid = scenario.scenario_id

            try:
                result = agent.run(
                    user_input=f"分析 {symbol} 的交易机会",
                    market_data=market_data,
                    context={
                        "symbol": symbol,
                        "scenario": scenario.to_dict(),
                        "recommended_orchestration": {
                            "pattern": pattern_name,
                            "nodes": pattern_nodes,
                            "score": 0.5,
                        },
                    },
                )
            except Exception as e:
                logger.debug(f"Agent执行失败: {e}")
                continue

            outputs = result.get("outputs", {})
            a5_out = outputs.get("A5", {})
            trade_order = a5_out.get("trade_order", {})

            if not trade_order or trade_order.get("action") == "HOLD" or not trade_order.get("entry_price"):
                continue

            direction = trade_order.get("action", "HOLD")
            entry_price = trade_order.get("entry_price", market_data["price"])
            stop_loss = trade_order.get("stop_loss", 0)
            take_profit = trade_order.get("take_profit", 0)
            exit_price = future[-1][4]

            for k in future:
                k_high, k_low = k[2], k[3]
                if direction == "LONG":
                    if stop_loss > 0 and k_low <= stop_loss:
                        exit_price = stop_loss
                        break
                    if take_profit > 0 and k_high >= take_profit:
                        exit_price = take_profit
                        break
                else:
                    if stop_loss > 0 and k_high >= stop_loss:
                        exit_price = stop_loss
                        break
                    if take_profit > 0 and k_low <= take_profit:
                        exit_price = take_profit
                        break

            if direction == "LONG":
                ret = (exit_price - entry_price) / entry_price
            else:
                ret = (entry_price - exit_price) / entry_price
            ret -= fee_rate

            scenario_returns[sid].append(ret)

        return dict(scenario_returns)

    def optimize(self, symbols: List[str], interval: str = "1h") -> Dict[str, Any]:
        """优化所有场景的编排模式

        Returns:
            {
                "scenario_optimization": {
                    scenario_id: {
                        "best_pattern": str,
                        "best_score": float,
                        "pattern_scores": {pattern: {score, win_rate, total_return, sharpe, sample_count}}
                    }
                },
                "summary": {...}
            }
        """
        # 收集每个场景每个pattern的交易收益
        # {scenario_id: {pattern_name: [returns]}}
        all_data: Dict[str, Dict[str, List[float]]] = defaultdict(lambda: defaultdict(list))

        for symbol in symbols:
            logger.info(f"优化 {symbol}...")
            for pattern_name, pattern_nodes in GRAPH_PATTERNS.items():
                logger.info(f"  测试 {pattern_name}...")
                t0 = time.time()
                scenario_returns = self.backtest_pattern(symbol, pattern_name, pattern_nodes, interval)
                elapsed = time.time() - t0
                total = sum(len(v) for v in scenario_returns.values())
                logger.info(f"    {total} 笔交易, 覆盖 {len(scenario_returns)} 场景, 耗时 {elapsed:.1f}s")
                for sid, returns in scenario_returns.items():
                    all_data[sid][pattern_name].extend(returns)

        # 计算每个场景的最优pattern
        scenario_opt = {}
        for sid, patterns in all_data.items():
            pattern_scores = {}
            for pname, returns in patterns.items():
                if len(returns) < 3:
                    continue
                score = self._calc_score(returns)
                pattern_scores[pname] = score

            if pattern_scores:
                best_pattern = max(pattern_scores, key=lambda p: pattern_scores[p]["score"])
                best_score = pattern_scores[best_pattern]["score"]
            else:
                best_pattern = "c_chain"
                best_score = 0.0

            scenario_opt[sid] = {
                "best_pattern": best_pattern,
                "best_score": round(best_score, 4),
                "pattern_scores": pattern_scores,
            }

        # 更新编排记忆表
        memory = self.get_memory()
        updated_count = 0
        for sid, opt in scenario_opt.items():
            # 无条件更新：即使 score=0 也要写入，避免记忆表永远停留在 sparse=true
            total_samples = sum(
                v.get("sample_count", 0)
                for v in opt["pattern_scores"].values()
            )
            memory.update_from_evolution(
                scenario_id=sid,
                new_pattern=opt["best_pattern"],
                nodes=GRAPH_PATTERNS[opt["best_pattern"]],
                score=opt["best_score"],
                evidence={"source": "scenario_optimization",
                          "sample_count": total_samples},
            )
            updated_count += 1
        memory.save()
        logger.info(f"更新了 {updated_count} 个场景的编排")

        return {
            "scenarios_optimized": updated_count,
            "total_scenarios": len(all_data),
            "scenario_optimization": scenario_opt,
        }

    def _calc_score(self, returns: List[float]) -> Dict[str, float]:
        n = len(returns)
        total_return = sum(returns)
        avg_return = total_return / n
        wins = sum(1 for r in returns if r > 0)
        win_rate = wins / n

        if n >= 2:
            std = math.sqrt(sum((r - avg_return) ** 2 for r in returns) / n)
            sharpe = (avg_return / std * math.sqrt(730)) if std > 0 else 0
        else:
            sharpe = 0

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

        norm_sharpe = (min(max(sharpe, -2), 3) + 2) / 5
        norm_return = (min(max(total_return, -0.5), 1.0) + 0.5) / 1.5
        norm_dd = 1 - min(max_dd, 1)
        score = norm_sharpe * 0.4 + norm_return * 0.3 + norm_dd * 0.2 + win_rate * 0.1

        return {
            "score": round(score, 4),
            "win_rate": round(win_rate, 4),
            "total_return": round(total_return, 4),
            "sharpe": round(sharpe, 2),
            "max_dd": round(max_dd, 4),
            "sample_count": n,
        }


def main():
    import argparse
    parser = argparse.ArgumentParser(description="场景化编排优化器")
    parser.add_argument("--symbols", default="BTC,ETH,SOL", help="回测币种，逗号分隔")
    parser.add_argument("--interval", default="1h", choices=["1h", "30m"])
    parser.add_argument("--output", default=None, help="报告输出路径")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    symbols = [s.strip().upper() for s in args.symbols.split(",")]
    optimizer = ScenarioPatternOptimizer()

    logger.info("开始场景化编排优化...")
    t0 = time.time()
    result = optimizer.optimize(symbols, interval=args.interval)
    elapsed = time.time() - t0

    # 生成报告
    report_lines = []
    report_lines.append("# 场景化编排优化报告")
    report_lines.append(f"\n生成时间: {datetime.now().isoformat()}")
    report_lines.append(f"优化币种: {', '.join(symbols)}")
    report_lines.append(f"回测周期: {args.interval}")
    report_lines.append(f"耗时: {elapsed:.1f}s")
    report_lines.append(f"优化场景数: {result['scenarios_optimized']} / {result['total_scenarios']}")
    report_lines.append("")

    # 场景详情
    report_lines.append("## 各场景最优编排")
    report_lines.append("")
    report_lines.append("| 场景 | 最优编排 | 评分 | 胜率 | 总收益 | 夏普 | 样本数 |")
    report_lines.append("|------|---------|------|------|--------|------|--------|")
    for sid in sorted(result["scenario_optimization"].keys()):
        opt = result["scenario_optimization"][sid]
        best = opt["best_pattern"]
        scores = opt["pattern_scores"].get(best, {})
        report_lines.append(
            f"| {sid} | {best} | {opt['best_score']:.3f} | "
            f"{scores.get('win_rate', 0):.1%} | {scores.get('total_return', 0):.2%} | "
            f"{scores.get('sharpe', 0):.2f} | {scores.get('sample_count', 0)} |"
        )
    report_lines.append("")

    # 各pattern使用统计
    from collections import Counter
    pattern_counts = Counter(
        opt["best_pattern"] for opt in result["scenario_optimization"].values()
    )
    report_lines.append("## 编排模式分布")
    report_lines.append("")
    for p, c in pattern_counts.most_common():
        report_lines.append(f"- **{p}**: {c} 个场景")
    report_lines.append("")

    report = "\n".join(report_lines)

    if args.output:
        output_path = Path(args.output)
    else:
        output_path = (
            Path(__file__).parent / "reports"
            / f"scenario_opt_{args.interval}_{datetime.now().strftime('%Y%m%d_%H%M')}.md"
        )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(report)

    print(f"\n优化报告已保存: {output_path}")
    print(f"\n{report}")


if __name__ == "__main__":
    main()
