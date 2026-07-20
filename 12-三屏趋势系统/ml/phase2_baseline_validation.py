"""Phase 2: v2基线特征验证

用9年真实数据验证v2增强版MA200策略的四类目的表现，建立基线指标。

输出：
1. BTC/ETH/SOL/UNI 四个币种的分场景回测结果
2. 四类目的各自的基线指标
3. 结果保存到 ml/backtest_results/ 和闭环管理器
"""

import sys
import os
import json
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pandas as pd
import numpy as np

from backtest.strategy import EnhancedMA200Strategy
from ml.scenario_backtest_engine import ScenarioBacktestEngine
from ml.closed_loop_manager import ClosedLoopManager


def load_local_data(symbol):
    """加载本地历史数据"""
    filepath = f"data/historical/{symbol}_1D_730d.json"
    with open(filepath) as f:
        data = json.load(f)
    df = pd.DataFrame(data)
    df["timestamp"] = pd.to_datetime(df["ts"], unit="ms")
    df = df.set_index("timestamp")
    return df[["o", "h", "l", "c", "vol"]].rename(
        columns={"o": "open", "h": "high", "l": "low", "c": "close", "vol": "volume"}
    )


def run_phase2_baseline():
    """运行Phase 2基线验证"""
    symbols = ["BTC", "ETH", "SOL", "UNI"]

    engine = ScenarioBacktestEngine()
    loop_mgr = ClosedLoopManager()

    all_results = {}

    print("=" * 80)
    print("  Phase 2: v2基线特征验证 — 分场景回测")
    print("=" * 80)
    print()

    # 先加载BTC数据，给小币策略用
    btc_prices = load_local_data("BTC")

    for symbol in symbols:
        print(f"📊 正在处理 {symbol}...")
        try:
            prices = load_local_data(symbol)
            print(f"   数据: {len(prices)}天, {prices.index[0].date()} ~ {prices.index[-1].date()}")

            # v2策略
            is_btc = (symbol == "BTC")
            strategy_kwargs = {
                "symbol": symbol,
                "is_btc": is_btc,
                "alt_bear_no_trade": not is_btc,  # 小币熊市禁交易
            }
            if not is_btc:
                strategy_kwargs["btc_prices"] = btc_prices  # 小币需要BTC价格判断牛熊

            strategy = EnhancedMA200Strategy(**strategy_kwargs)

            result = engine.run_scenario_backtest(
                prices,
                strategy,
                strategy_name=f"EnhancedMA200_v2",
                symbol=symbol,
                experiment_name=f"v2_baseline_{symbol}",
            )

            all_results[symbol] = result

            # 保存结果
            engine.save_result(result)

            # 打印摘要
            print(f"   综合评分: {result.composite_score:.3f}")
            print(f"   夏普比率: {result.overall_sharpe:.3f}")
            print(f"   最大回撤: {result.overall_max_drawdown:.2%}")
            print(f"   总收益率: {result.overall_total_return:.2%}")
            print()

            for obj, m in result.objective_metrics.items():
                print(f"   [{obj}] {m.objective_name}:")
                print(f"     信号数: {m.total_signals} | 频率: {m.signal_freq_pct:.2f}%")
                print(f"     胜率: {m.win_rate:.2%} | 平均收益: {m.avg_return:.2%}")
                print(f"     Precision: {m.label_precision:.3f} | Recall: {m.label_recall:.3f} | F1: {m.label_f1:.3f}")
            print()

        except Exception as e:
            print(f"   ❌ 错误: {e}")
            import traceback
            traceback.print_exc()
            print()

    # 汇总表
    print("=" * 80)
    print("  汇总：四类目的基线指标")
    print("=" * 80)
    print()

    objectives = ["dip_buy", "top_exit", "bear_short", "bear_exit"]
    obj_names = {
        "dip_buy": "牛市抄底",
        "top_exit": "牛市离场",
        "bear_short": "熊市做空",
        "bear_exit": "熊市空平",
    }

    # 打印每类目的指标汇总
    for obj in objectives:
        print(f"\n📌 {obj_names[obj]} ({obj})")
        print(f"{'币种':<8} {'信号数':>8} {'频率%':>8} {'胜率':>8} {'平均收益':>10} {'Precision':>10} {'Recall':>8} {'F1':>8}")
        print("-" * 80)
        for sym in symbols:
            if sym in all_results and obj in all_results[sym].objective_metrics:
                m = all_results[sym].objective_metrics[obj]
                print(f"{sym:<8} {m.total_signals:>8} {m.signal_freq_pct:>8.2f} {m.win_rate:>8.2%} {m.avg_return:>10.2%} {m.label_precision:>10.3f} {m.label_recall:>8.3f} {m.label_f1:>8.3f}")

    # v2基线核心特征消融实验（BTC主）
    print()
    print("=" * 80)
    print("  v2核心特征消融实验（BTC）")
    print("=" * 80)
    print()

    if "BTC" in all_results:
        run_ablation_study(engine)

    # 存入闭环管理器
    print()
    print("=" * 80)
    print("  存入闭环管理器")
    print("=" * 80)

    for sym in symbols:
        if sym in all_results:
            r = all_results[sym]
            exp = loop_mgr.create_experiment(
                name=f"v2基线_{sym}",
                hypo_id="HYP-BASELINE-V2",
                objective="all",
                strategy_name="EnhancedMA200_v2",
                config={"symbol": sym},
            )
            loop_mgr.record_experiment_result(
                exp_id=exp.exp_id,
                result_data={
                    "overall": {
                        "sharpe": r.overall_sharpe,
                        "calmar": r.overall_calmar,
                        "max_drawdown": r.overall_max_drawdown,
                        "total_return": r.overall_total_return,
                        "trade_count": r.overall_trade_count,
                    },
                    "objectives": {
                        obj: {
                            "signals": m.total_signals,
                            "win_rate": m.win_rate,
                            "avg_return": m.avg_return,
                            "precision": m.label_precision,
                            "recall": m.label_recall,
                            "f1": m.label_f1,
                        }
                        for obj, m in r.objective_metrics.items()
                    }
                },
                composite_score=r.composite_score,
                conclusion=f"v2基线策略在{sym}上的分场景回测基准",
                lessons_learned=f"建立{sym}四类目的基线指标，作为后续优化的对比基准",
            )

    print("\n✅ Phase 2 基线验证完成！")
    print(f"结果保存在: {engine.result_dir}")
    return all_results


def run_ablation_study(engine):
    """v2核心特征消融实验（简化版）

    由于v2是规则策略，我们做"规则消融"：
    - 关闭周线MA200抄底 → 看收益变化
    - 关闭斐波那契止盈 → 看收益变化
    - 关闭BTC做空 → 看收益变化
    - 关闭双牛过滤 → 看收益变化
    """
    prices = load_local_data("BTC")

    print("🔬 规则消融实验（对比v2基线）")
    print()

    # 1. 完整v2（基线）
    full_v2 = EnhancedMA200Strategy(is_btc=True)
    base_result = engine.run_scenario_backtest(
        prices, full_v2, "v2_full", symbol="BTC",
        experiment_name="ablation_v2_full",
    )
    base_sharpe = base_result.overall_sharpe
    base_return = base_result.overall_total_return

    print(f"{'配置':<30} {'总收益':>10} {'夏普':>8} {'最大回撤':>10} {'交易次数':>10}")
    print("-" * 80)
    print(f"{'v2完整基线':<30} {base_return:>10.2%} {base_sharpe:>8.3f} {base_result.overall_max_drawdown:>10.2%} {base_result.overall_trade_count:>10}")

    # 2. 关闭周线抄底
    no_dip = EnhancedMA200Strategy(is_btc=True, weekly_ma200_dip_buy=False)
    r = engine.run_scenario_backtest(
        prices, no_dip, "v2_no_dip_buy", symbol="BTC",
        experiment_name="ablation_no_dip_buy",
    )
    delta_sharpe = r.overall_sharpe - base_sharpe
    delta_return = r.overall_total_return - base_return
    print(f"{'- 关闭周线抄底':<30} {r.overall_total_return:>10.2%} {r.overall_sharpe:>8.3f} {r.overall_max_drawdown:>10.2%} {r.overall_trade_count:>10}")
    print(f"  → 贡献: 夏普{delta_sharpe:+.3f}, 收益{delta_return:+.2%} {'✅' if delta_sharpe < 0 else '❌'}")

    # 3. 关闭做空
    no_short = EnhancedMA200Strategy(is_btc=True, bear_short_level1_pct=0.0, bear_short_level2_pct=0.0)
    r = engine.run_scenario_backtest(
        prices, no_short, "v2_no_short", symbol="BTC",
        experiment_name="ablation_no_short",
    )
    delta_sharpe = r.overall_sharpe - base_sharpe
    delta_return = r.overall_total_return - base_return
    print(f"{'- 关闭BTC做空':<30} {r.overall_total_return:>10.2%} {r.overall_sharpe:>8.3f} {r.overall_max_drawdown:>10.2%} {r.overall_trade_count:>10}")
    print(f"  → 贡献: 夏普{delta_sharpe:+.3f}, 收益{delta_return:+.2%} {'✅' if delta_sharpe < 0 else '❌'}")

    # 4. 关闭斐波那契止盈
    no_fib = EnhancedMA200Strategy(is_btc=True, fib_take_profit=False)
    r = engine.run_scenario_backtest(
        prices, no_fib, "v2_no_fib", symbol="BTC",
        experiment_name="ablation_no_fib",
    )
    delta_sharpe = r.overall_sharpe - base_sharpe
    delta_return = r.overall_total_return - base_return
    print(f"{'- 关闭斐波那契止盈':<30} {r.overall_total_return:>10.2%} {r.overall_sharpe:>8.3f} {r.overall_max_drawdown:>10.2%} {r.overall_trade_count:>10}")
    print(f"  → 贡献: 夏普{delta_sharpe:+.3f}, 收益{delta_return:+.2%} {'✅' if delta_sharpe < 0 else '❌'}")

    print()
    print("💡 说明: 关闭某规则后夏普下降越多，说明该规则贡献越大")
    print("   ✅ = 该规则有正贡献（关闭后变差）")
    print("   ❌ = 该规则贡献不明显或为负")


if __name__ == "__main__":
    run_phase2_baseline()
