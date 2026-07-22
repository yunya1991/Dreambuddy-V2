"""
回测亏损诊断分析器

深度分析每笔交易的亏损原因，输出：
1. 多空分维度胜率/收益
2. 场景维度胜率/收益
3. 止损命中率 vs 自然出场率
4. 止损过早问题（止损后价格又回来）
5. 持仓时长vs收益关系
6. 连亏模式
7. 置信度vs实际收益分布
"""

from __future__ import annotations
import json, math, logging
from pathlib import Path
from typing import Dict, Any, List
from datetime import datetime
from collections import defaultdict

logger = logging.getLogger(__name__)


class LossDiagnoser:
    def __init__(self, data_dir: str = None):
        if data_dir is None:
            data_dir = str(Path(__file__).parent.parent.parent.parent.parent
                           / "10-经典指标系统" / "user_data" / "data" / "aggregated" / "futures")
        self.data_dir = data_dir
        self._agent = None
        self._classifier = None
        self._memory = None

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
            return []
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
        klines = []
        for k in data:
            if isinstance(k, list) and len(k) >= 6:
                klines.append([int(k[0]), float(k[1]), float(k[2]), float(k[3]), float(k[4]), float(k[5])])
        klines.sort(key=lambda x: x[0])
        return klines

    def build_market_data(self, window, symbol):
        if len(window) < 24:
            return None
        closes = [k[4] for k in window]
        highs = [k[2] for k in window]
        lows = [k[3] for k in window]
        volumes = [k[5] for k in window]
        price = closes[-1]

        def ema(vals, p):
            p = min(p, len(vals))
            k = 2 / (p + 1)
            e = vals[0]
            for v in vals[1:p]:
                e = v * k + e * (1 - k)
            return e

        def atr_pct(h, l, c, p):
            p = min(p, len(c) - 1)
            if p <= 0: return 0.02
            trs = []
            for i in range(-p, 0):
                tr = max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1]))
                trs.append(tr)
            return sum(trs) / len(trs) / c[-1]

        def rsi(c, p=14):
            p = min(p, len(c) - 1)
            if p <= 0: return 50
            dels = [c[i] - c[i - 1] for i in range(-p, 0)]
            g = [max(d, 0) for d in dels]
            lo = [max(-d, 0) for d in dels]
            ag = sum(g) / p
            al = sum(lo) / p
            if al == 0: return 100
            return 100 - 100 / (1 + ag / al)

        vol_ratio = 1.0
        if len(volumes) >= 20:
            recent_vol = sum(volumes[-5:]) / 5
            avg_vol = sum(volumes[-20:]) / 20
            vol_ratio = recent_vol / avg_vol if avg_vol > 0 else 1.0

        return {
            "symbol": symbol, "price": price,
            "ema20": ema(closes, 20), "ema50": ema(closes, 50), "ema200": ema(closes, 200),
            "change_1h": self._pct(closes, 1), "change_4h": self._pct(closes, 4),
            "change_24h": self._pct(closes, min(24, len(closes) - 1)),
            "atr_pct": atr_pct(highs, lows, closes, 14),
            "rsi14": rsi(closes, 14),
            "high_24h": max(highs[-24:]), "low_24h": min(lows[-24:]),
            "vol_ratio": vol_ratio, "fgi": 50, "funding_rate": 0.0,
        }

    def _pct(self, values, periods):
        if len(values) <= periods or periods <= 0: return 0
        old = values[-periods - 1]
        new = values[-1]
        return (new - old) / old * 100 if old != 0 else 0

    def diagnose(self, symbols: List[str], interval: str = "1h") -> Dict[str, Any]:
        window_size = 48
        step = 4
        hold_periods = 12
        fee_rate = 0.0008

        agent = self.get_agent()
        classifier = self.get_classifier()
        memory = self.get_memory()

        # 逐笔交易记录
        trades = []

        for symbol in symbols:
            klines = self.load_klines(symbol, interval)
            if len(klines) < window_size + hold_periods:
                continue

            for i in range(0, len(klines) - window_size - hold_periods, step):
                window = klines[i:i + window_size]
                future = klines[i + window_size:i + window_size + hold_periods]

                market_data = self.build_market_data(window, symbol)
                if market_data is None:
                    continue

                scenario = classifier.classify(market_data)
                sid = scenario.scenario_id
                choice = memory.select(sid)

                try:
                    result = agent.run(
                        user_input=f"分析 {symbol} 的交易机会",
                        market_data=market_data,
                        context={
                            "symbol": symbol,
                            "scenario": scenario.to_dict() if hasattr(scenario, "to_dict") else {"scenario_id": sid},
                            "recommended_orchestration": choice.to_dict() if hasattr(choice, "to_dict") else {"pattern": choice.pattern},
                        },
                    )
                except Exception:
                    continue

                outputs = result.get("outputs", {})
                a5_out = outputs.get("A5", {})
                trade_order = a5_out.get("trade_order", {})

                if not trade_order or trade_order.get("action") == "HOLD" or not trade_order.get("entry_price"):
                    continue

                direction = trade_order.get("action", "HOLD")
                confidence = result.get("confidence", 0.0)
                entry_price = trade_order.get("entry_price", market_data["price"])
                stop_loss = trade_order.get("stop_loss", 0)
                take_profit = trade_order.get("take_profit", 0)
                atr_pct = market_data.get("atr_pct", 0.02)

                # 模拟持仓
                exit_price = future[-1][4]
                exit_reason = "natural"  # 自然出场
                exit_bar = len(future)

                for bi, k in enumerate(future):
                    k_high, k_low = k[2], k[3]
                    if direction == "LONG":
                        if stop_loss > 0 and k_low <= stop_loss:
                            exit_price = stop_loss
                            exit_reason = "stop_loss"
                            exit_bar = bi + 1
                            break
                        if take_profit > 0 and k_high >= take_profit:
                            exit_price = take_profit
                            exit_reason = "take_profit"
                            exit_bar = bi + 1
                            break
                    else:
                        if stop_loss > 0 and k_high >= stop_loss:
                            exit_price = stop_loss
                            exit_reason = "stop_loss"
                            exit_bar = bi + 1
                            break
                        if take_profit > 0 and k_low <= take_profit:
                            exit_price = take_profit
                            exit_reason = "take_profit"
                            exit_bar = bi + 1
                            break

                if direction == "LONG":
                    ret = (exit_price - entry_price) / entry_price
                else:
                    ret = (entry_price - exit_price) / entry_price
                ret -= fee_rate

                # 止损过早检测：止损后价格是否又回来了
                sl_premature = False
                sl_recover_pct = 0
                if exit_reason == "stop_loss" and exit_bar < len(future):
                    remaining = future[exit_bar:]
                    if direction == "LONG":
                        max_after = max(k[2] for k in remaining)
                        if max_after > entry_price:
                            sl_premature = True
                            sl_recover_pct = (max_after - entry_price) / entry_price * 100
                    else:
                        min_after = min(k[3] for k in remaining)
                        if min_after < entry_price:
                            sl_premature = True
                            sl_recover_pct = (entry_price - min_after) / entry_price * 100

                trades.append({
                    "symbol": symbol,
                    "direction": direction,
                    "confidence": round(confidence, 3),
                    "scenario": sid,
                    "entry_price": entry_price,
                    "exit_price": exit_price,
                    "stop_loss": stop_loss,
                    "take_profit": take_profit,
                    "atr_pct": atr_pct,
                    "return": round(ret, 6),
                    "win": ret > 0,
                    "exit_reason": exit_reason,
                    "exit_bar": exit_bar,
                    "sl_premature": sl_premature,
                    "sl_recover_pct": round(sl_recover_pct, 2),
                    "rr_ratio": round(abs(take_profit - entry_price) / max(abs(entry_price - stop_loss), 0.0001), 2),
                    "timestamp": window[-1][0],
                })

        # === 分析 ===
        total = len(trades)
        wins = [t for t in trades if t["win"]]
        losses = [t for t in trades if not t["win"]]

        report = {}
        report["total_trades"] = total
        report["total_wins"] = len(wins)
        report["total_losses"] = len(losses)
        report["total_return"] = round(sum(t["return"] for t in trades), 4)
        report["win_rate"] = round(len(wins) / max(total, 1), 4)

        # 1. 多空分维度
        for d in ["LONG", "SHORT"]:
            dt = [t for t in trades if t["direction"] == d]
            dw = [t for t in dt if t["win"]]
            report[f"{d}_count"] = len(dt)
            report[f"{d}_win_rate"] = round(len(dw) / max(len(dt), 1), 4)
            report[f"{d}_total_return"] = round(sum(t["return"] for t in dt), 4)
            report[f"{d}_avg_return"] = round(sum(t["return"] for t in dt) / max(len(dt), 1), 6)

        # 2. 场景维度（只列出交易数>=3的场景）
        scenario_stats = {}
        for t in trades:
            sid = t["scenario"]
            scenario_stats.setdefault(sid, []).append(t)
        scenario_report = []
        for sid, st in sorted(scenario_stats.items()):
            if len(st) < 3:
                continue
            sw = [t for t in st if t["win"]]
            sl_trades = [t for t in st if t["exit_reason"] == "stop_loss"]
            scenario_report.append({
                "scenario": sid,
                "count": len(st),
                "win_rate": round(len(sw) / len(st), 4),
                "total_return": round(sum(t["return"] for t in st), 4),
                "long_count": len([t for t in st if t["direction"] == "LONG"]),
                "short_count": len([t for t in st if t["direction"] == "SHORT"]),
                "sl_hit_rate": round(len(sl_trades) / len(st), 4),
            })
        report["scenario_analysis"] = scenario_report

        # 3. 出场原因分布
        exit_reasons = defaultdict(int)
        exit_reason_returns = defaultdict(list)
        for t in trades:
            exit_reasons[t["exit_reason"]] += 1
            exit_reason_returns[t["exit_reason"]].append(t["return"])
        report["exit_reasons"] = {k: {"count": v, "avg_return": round(sum(exit_reason_returns[k]) / v, 6)}
                                  for k, v in exit_reasons.items()}

        # 4. 止损过早问题
        sl_trades = [t for t in trades if t["exit_reason"] == "stop_loss"]
        sl_premature = [t for t in sl_trades if t["sl_premature"]]
        report["stop_loss_total"] = len(sl_trades)
        report["stop_loss_premature"] = len(sl_premature)
        report["stop_loss_premature_rate"] = round(len(sl_premature) / max(len(sl_trades), 1), 4)
        if sl_premature:
            report["sl_premature_avg_recover"] = round(sum(t["sl_recover_pct"] for t in sl_premature) / len(sl_premature), 2)

        # 5. 止损过早 - 按多空分
        for d in ["LONG", "SHORT"]:
            d_sl = [t for t in sl_trades if t["direction"] == d]
            d_sl_p = [t for t in d_sl if t["sl_premature"]]
            report[f"{d}_sl_total"] = len(d_sl)
            report[f"{d}_sl_premature"] = len(d_sl_p)
            report[f"{d}_sl_premature_rate"] = round(len(d_sl_p) / max(len(d_sl), 1), 4)

        # 6. 持仓时长vs收益
        bar_returns = defaultdict(list)
        for t in trades:
            bar_returns[t["exit_bar"]].append(t["return"])
        report["hold_period_analysis"] = {
            str(k): {"count": len(v), "avg_return": round(sum(v) / len(v), 6)}
            for k, v in sorted(bar_returns.items())
        }

        # 7. 置信度vs收益分布
        conf_bins = defaultdict(list)
        for t in trades:
            bin_key = f"{int(t['confidence'] * 10) / 10:.1f}"
            conf_bins[bin_key].append(t)
        report["confidence_analysis"] = []
        for bk in sorted(conf_bins.keys()):
            bt = conf_bins[bk]
            bw = [t for t in bt if t["win"]]
            report["confidence_analysis"].append({
                "confidence": bk,
                "count": len(bt),
                "win_rate": round(len(bw) / len(bt), 4),
                "avg_return": round(sum(t["return"] for t in bt) / len(bt), 6),
            })

        # 8. 最大连亏
        max_consec_loss = 0
        curr_loss = 0
        for t in trades:
            if not t["win"]:
                curr_loss += 1
                max_consec_loss = max(max_consec_loss, curr_loss)
            else:
                curr_loss = 0
        report["max_consecutive_losses"] = max_consec_loss

        # 9. 盈亏幅度分析
        win_returns = [t["return"] for t in wins]
        loss_returns = [t["return"] for t in losses]
        report["avg_win"] = round(sum(win_returns) / max(len(win_returns), 1), 6) if win_returns else 0
        report["avg_loss"] = round(sum(loss_returns) / max(len(loss_returns), 1), 6) if loss_returns else 0
        report["profit_factor"] = round(abs(sum(win_returns) / max(sum(loss_returns), 0.0001)), 4) if loss_returns else 0

        # 10. 止损过早的Top场景
        sl_premature_by_scenario = defaultdict(list)
        for t in sl_premature:
            sl_premature_by_scenario[t["scenario"]].append(t)
        report["sl_premature_top_scenarios"] = [
            {"scenario": sid, "count": len(st),
             "avg_recover_pct": round(sum(t["sl_recover_pct"] for t in st) / len(st), 2)}
            for sid, st in sorted(sl_premature_by_scenario.items(), key=lambda x: -len(x[1]))[:5]
        ]

        return report


def main():
    import argparse
    parser = argparse.ArgumentParser(description="回测亏损诊断")
    parser.add_argument("--symbols", default="BTC,ETH,SOL")
    parser.add_argument("--interval", default="1h")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    symbols = [s.strip().upper() for s in args.symbols.split(",")]
    diagnoser = LossDiagnoser()

    logger.info("开始亏损诊断分析...")
    t0 = datetime.now()
    report = diagnoser.diagnose(symbols, interval=args.interval)

    # 格式化输出
    print("\n" + "=" * 60)
    print("  回测亏损诊断报告")
    print("=" * 60)
    print(f"\n币种: {', '.join(symbols)} | 周期: {args.interval}")
    print(f"总交易: {report['total_trades']} | 胜率: {report['win_rate']:.1%} | 总收益: {report['total_return']:.2%}")

    # 1. 多空分析
    print("\n── 1. 多空分维度 ──")
    for d in ["LONG", "SHORT"]:
        n = report[f"{d}_count"]
        wr = report[f"{d}_win_rate"]
        tr = report[f"{d}_total_return"]
        ar = report[f"{d}_avg_return"]
        print(f"  {d}: {n}笔 | 胜率={wr:.1%} | 总收益={tr:.2%} | 平均收益={ar:.3%}")

    # 2. 场景分析
    print("\n── 2. 场景维度（>=3笔交易）──")
    print(f"  {'场景':<35} {'笔数':>4} {'胜率':>6} {'总收益':>8} {'多/空':>8} {'止损率':>6}")
    for s in report["scenario_analysis"]:
        print(f"  {s['scenario']:<35} {s['count']:>4} {s['win_rate']:>5.1%} {s['total_return']:>7.2%} "
              f"{s['long_count']:>3}/{s['short_count']:<3} {s['sl_hit_rate']:>5.1%}")

    # 3. 出场原因
    print("\n── 3. 出场原因分布 ──")
    for reason, data in report["exit_reasons"].items():
        print(f"  {reason}: {data['count']}笔 | 平均收益={data['avg_return']:.3%}")

    # 4. 止损过早
    print("\n── 4. 止损过早分析 ──")
    print(f"  止损触发: {report['stop_loss_total']}笔")
    print(f"  止损过早（价格又回来）: {report['stop_loss_premature']}笔 ({report['stop_loss_premature_rate']:.1%})")
    if "sl_premature_avg_recover" in report:
        print(f"  过早止损后平均恢复幅度: {report['sl_premature_avg_recover']:.2f}%")
    for d in ["LONG", "SHORT"]:
        n = report[f"{d}_sl_total"]
        p = report[f"{d}_sl_premature"]
        r = report[f"{d}_sl_premature_rate"]
        print(f"  {d} 止损: {n}笔 | 过早={p}笔 ({r:.1%})")

    # 5. 持仓时长
    print("\n── 5. 持仓时长vs收益 ──")
    for bar, data in report["hold_period_analysis"].items():
        print(f"  第{bar}根K线出场: {data['count']}笔 | 平均收益={data['avg_return']:.3%}")

    # 6. 置信度
    print("\n── 6. 置信度vs收益 ──")
    for c in report["confidence_analysis"]:
        print(f"  置信度{c['confidence']}: {c['count']}笔 | 胜率={c['win_rate']:.1%} | 平均收益={c['avg_return']:.3%}")

    # 7. 盈亏比
    print("\n── 7. 盈亏幅度 ──")
    print(f"  平均盈利: {report['avg_win']:.3%}")
    print(f"  平均亏损: {report['avg_loss']:.3%}")
    print(f"  盈亏比(PF): {report['profit_factor']:.2f}")
    print(f"  最大连亏: {report['max_consecutive_losses']}笔")

    # 8. 止损过早Top场景
    if report["sl_premature_top_scenarios"]:
        print("\n── 8. 止损过早Top场景 ──")
        for s in report["sl_premature_top_scenarios"]:
            print(f"  {s['scenario']}: {s['count']}笔 | 平均恢复={s['avg_recover_pct']:.2f}%")


if __name__ == "__main__":
    main()
