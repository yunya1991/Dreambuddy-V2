#!/usr/bin/env python3
"""
批量回测所有核心策略
按 1h 和 4h 两个周期分别回测，选择表现最好的策略
"""
import subprocess
import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

# 核心策略列表（排除模块文件和子目录策略）
CORE_STRATEGIES = [
    ("user_data.strategies.MultiGroupStrategy", "MultiGroupStrategy"),
    ("user_data.strategies.RegimeHybridStrategy", "RegimeHybridStrategy"),
    ("user_data.strategies.Bot2StrategyTrend", "Bot2StrategyTrend"),
    ("user_data.strategies.Bot2StrategyRange", "Bot2StrategyRange"),
    ("user_data.strategies.Strategy005", "Strategy005"),
    ("user_data.strategies.Strategy006", "Strategy006"),
    ("user_data.strategies.OTTStrategy", "OTTStrategy"),
    ("user_data.strategies.AdaptiveVolatilityStrategy_forced", "AdaptiveVolatilityStrategy_forced"),
    ("user_data.strategies.MarketBreadthFlowStrategy", "MarketBreadthFlowStrategy"),
    ("user_data.strategies.LongShortTripleScreenStrategy", "LongShortTripleScreenStrategy"),
    ("user_data.strategies.TrendConfirmationStrategy", "TrendConfirmationStrategy"),
    ("user_data.strategies.breakoutStrategy", "breakoutStrategy"),
]

TIMEFRAMES = ["1h", "4h"]

# 回测时间范围：最近3个月
END_DATE = datetime.now().strftime("%Y%m%d")
START_DATE = (datetime.now() - timedelta(days=90)).strftime("%Y%m%d")

FREQTRADE_BIN = "/opt/anaconda3/bin/freqtrade"
BASE_DIR = Path("/Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/10-经典指标系统")
RESULTS_FILE = BASE_DIR / "backtest_results.json"


def run_backtest(strategy_module: str, class_name: str, timeframe: str) -> dict:
    """运行单个策略回测"""
    config_path = BASE_DIR / "user_data" / "config_backtest.json"

    # 创建临时配置，修改 timeframe
    with open(config_path, "r") as f:
        config = json.load(f)

    config["timeframe"] = timeframe
    config["pairlists"] = [{"method": "StaticPairList"}]
    config["exchange"]["pair_whitelist"] = ["BTC/USDT", "ETH/USDT", "SOL/USDT"]

    tmp_config = BASE_DIR / f"user_data/tmp_config_{class_name}_{timeframe}.json"
    with open(tmp_config, "w") as f:
        json.dump(config, f, indent=2)

    cmd = [
        FREQTRADE_BIN,
        "backtesting",
        "--config", str(tmp_config),
        "--strategy", class_name,
        "--strategy-path", str(BASE_DIR / "user_data" / "strategies"),
        "--timerange", f"{START_DATE}-{END_DATE}",
        "--timeframe", timeframe,
        "--pairs", "BTC/USDT", "ETH/USDT", "SOL/USDT",
        "--export", "none",
    ]

    print(f"\n[回测] {class_name} @ {timeframe} ...")
    print(f"  命令: {' '.join(cmd)}")

    try:
        result = subprocess.run(
            cmd,
            cwd=str(BASE_DIR),
            capture_output=True,
            text=True,
            timeout=300,
        )

        # 清理临时配置
        if tmp_config.exists():
            tmp_config.unlink()

        return parse_backtest_output(result.stdout + result.stderr, class_name, timeframe)
    except subprocess.TimeoutExpired:
        print(f"  ❌ 超时")
        if tmp_config.exists():
            tmp_config.unlink()
        return {"strategy": class_name, "timeframe": timeframe, "error": "timeout"}
    except Exception as e:
        print(f"  ❌ 异常: {e}")
        if tmp_config.exists():
            tmp_config.unlink()
        return {"strategy": class_name, "timeframe": timeframe, "error": str(e)}


def parse_backtest_output(output: str, strategy: str, timeframe: str) -> dict:
    """解析 freqtrade backtesting 输出"""
    result = {
        "strategy": strategy,
        "timeframe": timeframe,
        "total_profit_pct": None,
        "sharpe": None,
        "sortino": None,
        "max_drawdown_pct": None,
        "total_trades": None,
        "win_rate": None,
        "avg_profit": None,
        "error": None,
    }

    lines = output.split("\n")

    for line in lines:
        line = line.strip()

        # 总收益率
        if "Total Profit %" in line or "tot profit %" in line.lower():
            try:
                val = line.split(":")[-1].strip().replace("%", "").replace("+", "")
                result["total_profit_pct"] = float(val)
            except:
                pass

        # 夏普比率
        if "Sharpe" in line:
            try:
                val = line.split(":")[-1].strip()
                result["sharpe"] = float(val)
            except:
                pass

        # Sortino
        if "Sortino" in line:
            try:
                val = line.split(":")[-1].strip()
                result["sortino"] = float(val)
            except:
                pass

        # 最大回撤
        if "Max Drawdown" in line or "drawdown" in line.lower():
            try:
                val = line.split(":")[-1].strip().replace("%", "")
                result["max_drawdown_pct"] = float(val)
            except:
                pass

        # 总交易次数
        if "Total Trades" in line or "total trades" in line.lower():
            try:
                val = line.split(":")[-1].strip()
                result["total_trades"] = int(val)
            except:
                pass

        # 胜率
        if "Win Rate" in line or "win rate" in line.lower():
            try:
                val = line.split(":")[-1].strip().replace("%", "")
                result["win_rate"] = float(val)
            except:
                pass

        # 平均利润
        if "Avg Profit" in line or "avg profit" in line.lower():
            try:
                val = line.split(":")[-1].strip().replace("%", "")
                result["avg_profit"] = float(val)
            except:
                pass

    if result["total_profit_pct"] is None:
        # 检查是否有错误
        if "error" in output.lower() or "Error" in output:
            result["error"] = "backtest_failed"
        else:
            result["error"] = "no_results"

    status = "✅" if result["total_profit_pct"] is not None else "❌"
    print(f"  {status} Profit: {result['total_profit_pct']}%, Trades: {result['total_trades']}, Sharpe: {result['sharpe']}")

    return result


def calculate_score(r: dict) -> float:
    """计算策略综合评分"""
    if r.get("error") or r.get("total_profit_pct") is None:
        return -999

    profit = r.get("total_profit_pct", 0)
    sharpe = r.get("sharpe", 0) or 0
    drawdown = abs(r.get("max_drawdown_pct", 0) or 0)
    trades = r.get("total_trades", 0) or 0

    # 综合评分：收益为主，兼顾风险调整收益和交易次数
    score = profit * 0.5 + sharpe * 10 - drawdown * 0.3 + min(trades, 50) * 0.1
    return round(score, 2)


def main():
    print("=" * 70)
    print(f"Freqtrade 策略批量回测")
    print(f"时间范围: {START_DATE} ~ {END_DATE}")
    print(f"交易对: BTC/USDT, ETH/USDT, SOL/USDT")
    print(f"周期: 1h, 4h")
    print("=" * 70)

    all_results = []

    for module, class_name in CORE_STRATEGIES:
        for tf in TIMEFRAMES:
            r = run_backtest(module, class_name, tf)
            r["score"] = calculate_score(r)
            all_results.append(r)

    # 保存结果
    with open(RESULTS_FILE, "w") as f:
        json.dump(all_results, f, indent=2, ensure_ascii=False)

    print("\n" + "=" * 70)
    print("回测结果汇总")
    print("=" * 70)

    # 按周期分类
    for tf in TIMEFRAMES:
        print(f"\n--- {tf} 周期 ---")
        tf_results = [r for r in all_results if r["timeframe"] == tf]
        tf_results.sort(key=lambda x: x["score"], reverse=True)

        for i, r in enumerate(tf_results[:5], 1):
            profit = r.get("total_profit_pct")
            if profit is not None:
                print(f"  {i}. {r['strategy']}: 收益={profit:.2f}%, 夏普={r.get('sharpe')}, 回撤={r.get('max_drawdown_pct')}%, 评分={r['score']}")
            else:
                print(f"  {i}. {r['strategy']}: 回测失败 ({r.get('error')})")

    # 输出推荐策略
    print("\n" + "=" * 70)
    print("推荐策略配置")
    print("=" * 70)

    for tf in TIMEFRAMES:
        tf_results = [r for r in all_results if r["timeframe"] == tf and r.get("total_profit_pct") is not None]
        if tf_results:
            best = max(tf_results, key=lambda x: x["score"])
            print(f"\n{tf} 最优策略: {best['strategy']}")
            print(f"  总收益: {best['total_profit_pct']:.2f}%")
            print(f"  夏普比率: {best.get('sharpe')}")
            print(f"  最大回撤: {best.get('max_drawdown_pct')}%")
            print(f"  交易次数: {best.get('total_trades')}")
            print(f"  综合评分: {best['score']}")

    print(f"\n详细结果已保存至: {RESULTS_FILE}")


if __name__ == "__main__":
    main()
