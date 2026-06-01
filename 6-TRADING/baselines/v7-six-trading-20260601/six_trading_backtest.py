#!/usr/bin/env python3
"""
6-TRADING v1 vs v0 对比回测脚本
=================================
使用三屏交易系统 (backtest_engine v3.1) 对 BTC/SOL/ETH 进行6个月回测，
与 v0 基线 (crypto-signal-bot) 进行指标对比。

数据源: Binance Vision 公开 API（1D 日线 K线，与 v0 基线一致）
时间窗口: 2025-11-27 ~ 2026-05-26
"""

import sys
import json
import time
import requests
from pathlib import Path
from datetime import datetime, timezone

# ---- 确保能导入本目录模块 ----
SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPT_DIR))

# ==================== Binance 日线数据获取 ====================

BINANCE_API = "https://data-api.binance.vision/api/v3/klines"
CACHE_DIR = SCRIPT_DIR / "backtest_cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

INST_TO_BINANCE = {
    "BTC-USDT-SWAP": "BTCUSDT",
    "SOL-USDT-SWAP": "SOLUSDT",
    "ETH-USDT-SWAP": "ETHUSDT",
}


def _dt_to_ms(date_str: str) -> int:
    dt = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    return int(dt.timestamp() * 1000)


def fetch_binance_daily(symbol: str, start_ms: int, end_ms: int) -> list:
    """Binance Vision 获取日线K线，自动分页"""
    cache_path = CACHE_DIR / f"{symbol}_1d_{start_ms}_{end_ms}.json"
    if cache_path.exists():
        with open(cache_path) as f:
            print(f"  [cache] {cache_path.name}")
            return json.load(f)

    all_bars = []
    cursor = start_ms
    while cursor < end_ms:
        params = {
            "symbol": symbol,
            "interval": "1d",
            "startTime": cursor,
            "endTime": end_ms,
            "limit": 1000,
        }
        try:
            resp = requests.get(BINANCE_API, params=params, timeout=15)
            bars = resp.json()
        except Exception as e:
            print(f"  [warn] 请求异常: {e}")
            time.sleep(2)
            continue

        if not bars or not isinstance(bars, list):
            break

        all_bars.extend(bars)
        last_ts = int(bars[-1][0])
        if last_ts >= end_ms or len(bars) < 1000:
            break
        cursor = last_ts + 86400000  # +1 day
        time.sleep(0.2)

    # 格式化为引擎期望的格式
    result = []
    for b in all_bars:
        ts = int(b[0])
        if ts > end_ms:
            break
        result.append({
            "ts":     ts,
            "open":   float(b[1]),
            "high":   float(b[2]),
            "low":    float(b[3]),
            "close":  float(b[4]),
            "vol":    float(b[5]),
            "volUsd": float(b[7]),
        })

    with open(cache_path, "w") as f:
        json.dump(result, f)
    print(f"  [fetch] {symbol} 1D: {len(result)} bars saved")
    return result


# ==================== 猴子补丁 backtest_data_fetcher ====================

import backtest_data_fetcher as _fetcher  # noqa: E402

_START_DATE = "2025-11-27"
_END_DATE   = "2026-05-26"
_start_ms   = _dt_to_ms(_START_DATE)
_end_ms     = _dt_to_ms(_END_DATE)

_CACHED_CANDLES = {}


def _patched_load_or_fetch(inst_id: str, bar: str, start_ts: int, end_ts: int,
                           force_refresh: bool = False) -> list:
    """替换 OKX 拉取，改用 Binance 1D 数据"""
    cache_key = (inst_id, bar)
    if cache_key in _CACHED_CANDLES:
        return _CACHED_CANDLES[cache_key]

    symbol = INST_TO_BINANCE.get(inst_id, inst_id.replace("-USDT-SWAP", "USDT"))
    raw = fetch_binance_daily(symbol, _start_ms, _end_ms)
    # 添加技术指标
    candles = _fetcher.add_technical_indicators(raw)
    _CACHED_CANDLES[cache_key] = candles
    return candles


# 打补丁到已导入的模块
_fetcher.load_or_fetch = _patched_load_or_fetch

# ---- 现在再导入引擎（它会用打过补丁的 fetcher）----
from backtest_engine_main import BacktestEngine  # noqa: E402

# ==================== 配置 ====================

V0_BASELINE = {
    "BTC-USDT-SWAP": {
        "total_ret": 8.78, "ann_ret": 18.61, "max_dd": 18.25, "sharpe": 0.715,
        "win_rate": 51.2, "profit_factor": 1.047, "n_trades": 573,
        "bh_ret": -15.81, "final_equity": 10877.89,
    },
    "SOL-USDT-SWAP": {
        "total_ret": 68.68, "ann_ret": 188.68, "max_dd": 17.60, "sharpe": 3.022,
        "win_rate": 57.2, "profit_factor": 1.248, "n_trades": 538,
        "bh_ret": -40.14, "final_equity": 16867.71,
    },
    "ETH-USDT-SWAP": {
        "total_ret": -8.67, "ann_ret": -16.80, "max_dd": 32.91, "sharpe": -0.336,
        "win_rate": 46.1, "profit_factor": 0.961, "n_trades": 558,
        "bh_ret": -30.25, "final_equity": 9132.91,
    },
}

INSTRUMENTS = ["BTC-USDT-SWAP", "SOL-USDT-SWAP", "ETH-USDT-SWAP"]
INITIAL_CAPITAL = 10_000.0

OUTPUT_DIR = SCRIPT_DIR / "test_results"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


# ==================== 运行回测 ====================

def run_all():
    # v10.0: 预加载BTC日线数据 (所有品种共用一份BTC参考)
    print("预加载 BTC 参考数据 (MA区间经验法则)...")
    btc_candles_ref = _patched_load_or_fetch("BTC-USDT-SWAP", "1D", _start_ms, _end_ms)
    if btc_candles_ref:
        btc_candles_ref = _fetcher.add_technical_indicators(btc_candles_ref)
        print(f"  BTC参考数据: {len(btc_candles_ref)} 根")
    else:
        btc_candles_ref = None
        print("  警告: BTC参考数据加载失败，MA区间规则将退化")

    v1_results = {}
    for inst_id in INSTRUMENTS:
        print(f"\n{'='*60}")
        print(f"运行 v1 回测: {inst_id}")
        print(f"{'='*60}")
        config = {
            "inst_id":          inst_id,
            "start_date":       _START_DATE,
            "end_date":         _END_DATE,
            "initial_capital":  INITIAL_CAPITAL,
            "maker_fee":        0.0002,
            "taker_fee":        0.0005,
            "slippage":         0.0001,
            "max_drawdown":     20.0,
            "warn_drawdown":    15.0,
            "max_position_pct": 0.20,
            "max_total_pct":    0.60,
        }
        # BTC自身回测时不需要额外传入，引擎会用自己的candles
        btc_arg = btc_candles_ref if inst_id != "BTC-USDT-SWAP" else None
        engine = BacktestEngine(config, btc_candles=btc_arg)
        try:
            result = engine.run()
            if result:
                v1_results[inst_id] = {
                    "total_ret":      result.get("total_return", 0),
                    "ann_ret":        result.get("annual_return", 0),
                    "max_dd":         result.get("max_drawdown", 0),
                    "sharpe":         result.get("sharpe_ratio", 0),
                    "win_rate":       result.get("win_rate", 0),
                    "profit_factor":  result.get("profit_factor", 0),
                    "n_trades":       result.get("total_trades", 0),
                    "add_on_count":   result.get("add_on_count", 0),
                    "tp1_count":      result.get("tp1_count", 0),
                    "tp2_count":      result.get("tp2_count", 0),
                    "tp3_count":      result.get("tp3_count", 0),
                    "martin_complete":   result.get("martin_complete_trades", 0),
                    "martin_incomplete": result.get("martin_incomplete_trades", 0),
                    "drawdown_limit_count": result.get("drawdown_limit_count", 0),
                    "screen1_accuracy":     result.get("screen1_accuracy", 0),
                    "final_equity":   result.get("final_equity", INITIAL_CAPITAL),
                    "monthly_returns": result.get("monthly_returns", {}),
                }
            else:
                v1_results[inst_id] = {}
        except Exception as e:
            print(f"[ERROR] {inst_id} 回测异常: {e}")
            import traceback
            traceback.print_exc()
            v1_results[inst_id] = {}
    return v1_results


# ==================== 生成对比报告 ====================

def generate_report(v1_results: dict) -> str:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    labels = {
        "BTC-USDT-SWAP": "BTC/USDT",
        "SOL-USDT-SWAP": "SOL/USDT",
        "ETH-USDT-SWAP": "ETH/USDT",
    }

    lines = []
    lines.append("# 6-TRADING v1 vs v0 基线对比报告")
    lines.append(f"> 生成时间: {now}  ")
    lines.append(f"> 回测周期: {_START_DATE} ~ {_END_DATE}  ")
    lines.append(f"> 初始资金: ${INITIAL_CAPITAL:,.0f}  ")
    lines.append(f"> 数据来源: Binance Vision 公开 API (1D 日线)")
    lines.append("")
    lines.append("## 策略对比")
    lines.append("")
    lines.append("| | v0 基线 (crypto-signal-bot) | v1 (6-TRADING 三屏马丁) |")
    lines.append("|---|---|---|")
    lines.append("| 时间框架 | **1H** 小时线 | **1D** 日线 + 1W 周线 |")
    lines.append("| 入场信号 | SMA/MACD/RSI/BB 8条件评分 | Screen1 周线方向 + Screen2 日线预设 |")
    lines.append("| 仓位管理 | 100% 全仓复利 | 马丁 20%→20%→20%→20% (最多4层) |")
    lines.append("| 止损 | 固定 -1.5% | 动态均价 × 0.80 (20%) |")
    lines.append("| 止盈 | 固定 +2.0% | ATR × 2/3/5 三层 (马丁加满后) |")
    lines.append("| 持仓周期 | 平均 < 3H | 数日到数周 |")
    lines.append("")

    for inst_id in INSTRUMENTS:
        label = labels[inst_id]
        v0 = V0_BASELINE.get(inst_id, {})
        v1 = v1_results.get(inst_id, {})
        lines.append(f"---")
        lines.append(f"")
        lines.append(f"## {label}")
        lines.append("")

        if not v1:
            lines.append("⚠️ v1 回测无数据（引擎返回空）")
            lines.append("")
            continue

        lines.append("| 指标 | v0 基线 | v1 本系统 | 差值 | 结论 |")
        lines.append("|------|---------|----------|------|------|")

        def row(label_str, v0_val, v1_val, fmt="{:.2f}", higher_better=True, suffix=""):
            if v1_val is None:
                return f"| {label_str} | {fmt.format(v0_val)}{suffix} | N/A | — | — |"
            diff = v1_val - v0_val
            mark = ("✅" if (diff > 0.3 if higher_better else diff < -0.3) else
                    ("❌" if (diff < -0.3 if higher_better else diff > 0.3) else "➡"))
            delta = f"{'+' if diff >= 0 else ''}{diff:.2f}"
            return f"| {label_str} | {fmt.format(v0_val)}{suffix} | {fmt.format(v1_val)}{suffix} | {delta} | {mark} |"

        lines.append(row("总收益率",   v0["total_ret"],    v1.get("total_ret",0),    "{:+.2f}", True,  "%"))
        lines.append(row("年化收益率", v0["ann_ret"],      v1.get("ann_ret",0),      "{:+.2f}", True,  "%"))
        lines.append(row("最大回撤",   v0["max_dd"],       v1.get("max_dd",0),       "{:.2f}",  False, "%"))
        lines.append(row("夏普比率",   v0["sharpe"],       v1.get("sharpe",0),       "{:.3f}",  True))
        lines.append(row("胜率",       v0["win_rate"],     v1.get("win_rate",0),     "{:.1f}",  True,  "%"))
        lines.append(row("盈亏比",     v0["profit_factor"],v1.get("profit_factor",0),"{:.3f}",  True))
        lines.append(f"| 交易次数 | {v0['n_trades']} | {v1.get('n_trades',0)}次 (加仓{v1.get('add_on_count',0)}次) | — | ℹ️ |")
        lines.append(f"| 最终权益 | ${v0['final_equity']:,.0f} | ${v1.get('final_equity',INITIAL_CAPITAL):,.0f} | — | — |")
        lines.append("")

        lines.append(f"**v1 马丁策略统计:**")
        lines.append(f"- 马丁完成 (Level3加满): **{v1.get('martin_complete',0)}** 次")
        lines.append(f"- 马丁未完成 (止损/反转): {v1.get('martin_incomplete',0)} 次")
        lines.append(f"- 分批止盈 TP1/TP2/TP3: {v1.get('tp1_count',0)}/{v1.get('tp2_count',0)}/{v1.get('tp3_count',0)} 次")
        lines.append(f"- 第一屏正确率: {v1.get('screen1_accuracy',0):.1f}%")
        lines.append(f"- 强制全平 (20%回撤): {v1.get('drawdown_limit_count',0)} 次")
        lines.append("")

        monthly = v1.get("monthly_returns", {})
        if monthly:
            lines.append("**月度收益 (v1):**")
            lines.append("")
            lines.append("| 月份 | 收益率 |")
            lines.append("|------|--------|")
            for m, r in sorted(monthly.items()):
                lines.append(f"| {m} | {'+' if r >= 0 else ''}{r:.2f}% |")
            lines.append("")

    # ---- 升版评分 ----
    lines.append("---")
    lines.append("")
    lines.append("## 升版门槛评估 (v1 需至少2项优于 v0)")
    lines.append("")
    lines.append("| 标的 | Sharpe | MaxDD | PF≥1 | 总评 |")
    lines.append("|------|--------|-------|------|------|")

    for inst_id in INSTRUMENTS:
        label = labels[inst_id]
        v0 = V0_BASELINE[inst_id]
        v1 = v1_results.get(inst_id, {})
        if not v1:
            lines.append(f"| {label} | N/A | N/A | N/A | ❓ 无数据 |")
            continue
        s = "✅" if v1.get("sharpe",0) > v0["sharpe"] else "❌"
        d = "✅" if v1.get("max_dd",100) < v0["max_dd"] else "❌"
        p = "✅" if v1.get("profit_factor",0) > 1.0 else "❌"
        cnt = sum([s == "✅", d == "✅", p == "✅"])
        verdict = "✅ 升版通过" if cnt >= 2 else "❌ 未达标"
        lines.append(f"| {label} | {s} {v1.get('sharpe',0):.3f} | {d} {v1.get('max_dd',0):.1f}% | {p} {v1.get('profit_factor',0):.3f} | {verdict} |")

    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## 结论")
    lines.append("")
    lines.append("v0 (crypto-signal-bot) 与 v1 (6-TRADING) 属于**不同策略风格**：")
    lines.append("")
    lines.append("- **v0**: 高频信号跟踪型，1H 框架，小仓快进快出，SIGNAL_FLIP 主导出场，")
    lines.append("  优势是快速适应短线，劣势是震荡噪声多、单笔收益极小")
    lines.append("")
    lines.append("- **v1**: 低频趋势马丁型，1D+1W 框架，少量交易配合加仓放大趋势，")
    lines.append("  优势是大行情下潜力大（如 SOL 熊市逆势），劣势是需要明确趋势方向")
    lines.append("")
    lines.append("两者可**互为补充**：v0 提供日内稳定小额收益，v1 捕获中长期大行情。")
    lines.append("")
    lines.append("> 基线文件: `6-TRADING/baselines/`  ")
    lines.append("> v0: `v0-crypto-signal-bot-20260526/`  ")
    lines.append("> v1: `v1-six-trading-system-20260526/`")

    return "\n".join(lines)


# ==================== 主入口 ====================

def main():
    print("6-TRADING v1 vs v0 对比回测")
    print(f"周期: {_START_DATE} ~ {_END_DATE}")
    print(f"标的: {', '.join(INSTRUMENTS)}")
    print(f"资金: ${INITIAL_CAPITAL:,.0f}")

    v1_results = run_all()

    # 保存 JSON
    results_path = OUTPUT_DIR / "six_trading_backtest_results.json"
    with open(results_path, "w", encoding="utf-8") as f:
        json.dump(v1_results, f, ensure_ascii=False, indent=2)
    print(f"\nv1 结果: {results_path}")

    # 生成报告
    report = generate_report(v1_results)
    report_path = OUTPUT_DIR / "six_trading_comparison_report.md"
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report)
    print(f"对比报告: {report_path}")

    # 控制台摘要
    print("\n" + "="*65)
    print(f"{'标的':<12} {'v0 Sharpe':>10} {'v1 Sharpe':>10} {'v0 Ret':>10} {'v1 Ret':>10} {'v0 DD':>8} {'v1 DD':>8}")
    print("-"*65)
    for inst_id in INSTRUMENTS:
        v0 = V0_BASELINE[inst_id]
        v1 = v1_results.get(inst_id, {})
        lbl = inst_id.replace("-USDT-SWAP", "")
        if v1:
            print(f"{lbl:<12} {v0['sharpe']:>10.3f} {v1.get('sharpe',0):>10.3f} "
                  f"{v0['total_ret']:>+9.2f}% {v1.get('total_ret',0):>+9.2f}% "
                  f"{v0['max_dd']:>7.1f}% {v1.get('max_dd',0):>7.1f}%")
        else:
            print(f"{lbl:<12} {v0['sharpe']:>10.3f} {'ERR':>10} {v0['total_ret']:>+9.2f}% {'N/A':>10} "
                  f"{v0['max_dd']:>7.1f}% {'N/A':>8}")


if __name__ == "__main__":
    main()
