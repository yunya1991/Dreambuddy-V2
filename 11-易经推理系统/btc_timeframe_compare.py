#!/usr/bin/env python3
"""
方案1：BTC 单币 1H vs 4H 周期可行性验证回测

严格复用 BCRM 2.0 原生 WalkForwardBacktester：
- Walk-Forward 5折交叉验证（防过拟合）
- 实盘同构离场：TP=3.0 ATR / SL=2.0 ATR / max_hold=60 bars
- 真实交易成本：fee=0.0005 (0.05%) / slippage=0.001 (0.1%)
- 真实 OKX K 线数据，无模拟兜底（数据不足直接报错）
"""
import sys
import json
import traceback
from pathlib import Path
from datetime import datetime

# 确保 11-易经推理系统/ 目录在 path 中（scripts/ 在此目录下）
YIJING_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(YIJING_ROOT))

from scripts.memory_l4.bcrm2.data_fetcher import get_klines
from scripts.memory_l4.bcrm2.walk_forward_backtester import (
    WalkForwardBacktester,
    generate_report,
)

# ============================================================
# 统一回测参数（1H 和 4H 完全一致，只改 timeframe）
# ============================================================
SYMBOL = "BTC"
N_FOLDS_TARGET = 5          # 目标折数，数据不足时自动向下适配
CONF_THRESHOLD = 0.40
TP_ATR = 3.0
SL_ATR = 2.0
MAX_HOLD_BARS = 60       # 1H=60小时=2.5天 / 4H=240小时=10天，对比同 bar 数
FEE_RATE = 0.0005       # 0.05% taker 手续费
SLIPPAGE_RATE = 0.001   # 0.1% 滑点
FEATURE_SELECTION = True
MAX_BARS_1H = 6000      # 1H 历史数据上限
MAX_BARS_4H = 6000      # 4H 历史数据上限（OKX 实际可能 3000 左右）

# Walk-Forward 自适应配置
# 当数据量足够时采用 HIGH（与 save_baseline 一致），不足时降级到 LOW 保底仍能回测
CFG_HIGH = {"min_train": 500, "min_test": 100}  # 每折 600 根
CFG_LOW = {"min_train": 300, "min_test": 60}    # 每折 360 根（保底）

# 触发 FeatureRegistry 所有特征模块注册（与 save_baseline.py 对齐）
def _register_all_features():
    import scripts.memory_l4.bcrm2.bagua_feature_engine  # noqa: F401
    import scripts.memory_l4.bcrm2.classic_experience_features  # noqa: F401
    import scripts.memory_l4.bcrm2.fibonacci_features  # noqa: F401
    import scripts.memory_l4.bcrm2.pivot_point_features  # noqa: F401
    import scripts.memory_l4.bcrm2.rsi_sentiment_features  # noqa: F401
    import scripts.memory_l4.bcrm2.wdh_features  # noqa: F401
    import scripts.memory_l4.bcrm2.cycle_features  # noqa: F401
    import scripts.memory_l4.bcrm2.market_cap  # noqa: F401
    import scripts.memory_l4.bcrm2.cross_asset_features  # noqa: F401
    import scripts.memory_l4.bcrm2.merrill_clock_features  # noqa: F401


def fetch_ref_df(timeframe: str, max_bars: int):
    """获取 BTC 自身参考数据（跨资产特征）；失败显式抛出，不兜底"""
    ref_df = get_klines(SYMBOL, timeframe, max_bars=max_bars + 200)
    if ref_df is None:
        raise RuntimeError(
            f"[FATAL] BTC {timeframe} 参考数据拉取失败！无法启动回测 "
            f"（请检查网络/代理或 OKX 接口限流）"
        )
    if len(ref_df) < 300:
        raise RuntimeError(
            f"[FATAL] BTC {timeframe} 参考数据不足: {len(ref_df)} 根 "
            f"（需要至少 300 根，跨资产特征无法计算）"
        )
    return ref_df


def data_probe(timeframe: str, max_bars: int) -> dict:
    """真实数据探针：按实际 bars 数自适应 N_FOLDS + 每折最低门槛

    自适应规则：
      - 先尝试 HIGH 配置（每折 500train+100test=600 根），向下取整折数，最大不超过 N_FOLDS_TARGET
      - 如果 HIGH 配置连 1 折都凑不齐，降级 LOW 配置（每折 300+60=360）
      - 如果 LOW 也凑不齐，显式失败（不做模拟兜底）
    """
    df = get_klines(SYMBOL, timeframe, max_bars=max_bars)
    if df is None:
        raise RuntimeError(
            f"[FATAL] BTC {timeframe} K线拉取失败（get_klines 返回 None）"
            f" — 请检查代理/网络/OKX API 可用性"
        )
    n = len(df)
    start = df.index[0]
    end = df.index[-1]
    span_days = (end - start).total_seconds() / 86400

    cfg_level = "HIGH"
    min_train, min_test = CFG_HIGH["min_train"], CFG_HIGH["min_test"]
    per_fold = min_train + min_test
    n_folds = min(N_FOLDS_TARGET, n // per_fold)

    if n_folds < 1:
        # 降级 LOW 配置
        cfg_level = "LOW"
        min_train, min_test = CFG_LOW["min_train"], CFG_LOW["min_test"]
        per_fold = min_train + min_test
        n_folds = min(N_FOLDS_TARGET, n // per_fold)

    min_needed_total = per_fold  # 至少 1 折
    enough = n_folds >= 1 and n >= min_needed_total

    probe = {
        "timeframe": timeframe,
        "n_bars": n,
        "min_needed": min_needed_total,
        "enough": enough,
        "start": str(start),
        "end": str(end),
        "span_days": round(span_days, 1),
        "n_folds": n_folds,
        "cfg_level": cfg_level,
        "min_train_bars": min_train,
        "min_test_bars": min_test,
        "per_fold_bars": per_fold,
    }

    header = f"[数据探针] BTC {timeframe}"
    status = "✅ 满足" if enough else "❌ 不足"
    print(f"{header}: {n} 根 K线 → {status}")
    print(f"  时间范围: {start} ~ {end}（共 {span_days:.1f} 天）")
    print(f"  Walk-Forward: N-Folds={n_folds} | 配置={cfg_level} "
          f"(train≥{min_train} test≥{min_test} 每折{per_fold}根)")
    return probe


def run_backtest(timeframe: str, max_bars: int, ref_df, probe_cfg: dict, verbose: bool = True):
    """执行单周期 Walk-Forward 回测（使用 probe 返回的自适应折数/门槛）"""
    df = get_klines(SYMBOL, timeframe, max_bars=max_bars)
    if df is None or len(df) < probe_cfg["per_fold_bars"]:
        raise RuntimeError(
            f"[FATAL] BTC {timeframe} K线不足（{len(df) if df else 0}/"
            f"{probe_cfg['per_fold_bars']} 需要），无法回测"
        )

    bt = WalkForwardBacktester(
        symbol=SYMBOL,
        n_folds=probe_cfg["n_folds"],
        min_train_bars=probe_cfg["min_train_bars"],
        min_test_bars=probe_cfg["min_test_bars"],
        conf_threshold=CONF_THRESHOLD,
        tp_atr=TP_ATR,
        sl_atr=SL_ATR,
        max_hold_bars=MAX_HOLD_BARS,
        fee_rate=FEE_RATE,
        slippage_rate=SLIPPAGE_RATE,
        feature_selection=FEATURE_SELECTION,
    )

    result = bt.run(df, ref_df=ref_df, verbose=verbose)

    metrics = {
        "timeframe": timeframe,
        "total_trades": result.total_trades,
        "win_rate": round(float(result.overall_win_rate), 4),
        "total_return_pct": round(float(result.total_return), 4),
        "avg_return_per_trade_pct": round(float(result.avg_return_per_trade), 4),
        "max_drawdown_pct": round(float(result.max_drawdown), 4),
        "profit_factor": round(float(result.profit_factor), 4),
        "sharpe_ratio": round(float(result.sharpe_ratio), 4),
        "avg_hold_bars": round(float(result.avg_hold_bars), 2),
        "avg_hold_days": round(float(result.avg_hold_bars) * (1 if timeframe == "1H" else 4) / 24, 2),
        "n_folds": result.n_folds,
        "cfg_level": probe_cfg["cfg_level"],
        "long_count": int(result.long_stats.get("count", 0)),
        "long_win_rate": round(float(result.long_stats.get("win_rate", 0) or 0), 4),
        "long_avg_return_pct": round(float(result.long_stats.get("avg_pnl", 0) or 0), 4),
        "short_count": int(result.short_stats.get("count", 0)),
        "short_win_rate": round(float(result.short_stats.get("win_rate", 0) or 0), 4),
        "short_avg_return_pct": round(float(result.short_stats.get("avg_pnl", 0) or 0), 4),
        "fold_results": [],
    }

    for fold in getattr(result, "fold_results", []) or []:
        metrics["fold_results"].append({
            "fold_idx": getattr(fold, "fold_idx", None),
            "total_trades": getattr(fold, "total_trades", 0),
            "win_rate": round(float(getattr(fold, "overall_win_rate", 0) or 0), 4),
            "total_return_pct": round(float(getattr(fold, "total_return", 0) or 0), 4),
            "max_drawdown_pct": round(float(getattr(fold, "max_drawdown", 0) or 0), 4),
        })

    print(f"\n✅ BTC {timeframe} 回测完成: 交易数={metrics['total_trades']} "
          f"胜率={metrics['win_rate']:.1%} "
          f"收益={metrics['total_return_pct']:+.2f}% "
          f"夏普={metrics['sharpe_ratio']:.2f} "
          f"回撤={metrics['max_drawdown_pct']:.2f}% "
          f"平均持仓={metrics['avg_hold_days']:.1f}天")

    return metrics


def print_comparison(m_1h: dict, m_4h: dict):
    """打印 1H vs 4H 对比表格，含样本量不足保护"""
    # 统计显著性门槛：少于 20 笔交易的周期结论不做优胜判断
    MIN_SIGNIFICANT_TRADES = 20
    sig_1h = m_1h["total_trades"] >= MIN_SIGNIFICANT_TRADES
    sig_4h = m_4h["total_trades"] >= MIN_SIGNIFICANT_TRADES

    def row(name, key, h_val, v_val, better=None, is_pct=False):
        diff = v_val - h_val if isinstance(h_val, (int, float)) and isinstance(v_val, (int, float)) else "N/A"
        if isinstance(diff, float):
            diff_str = f"{diff:+.4f}" + ("%" if is_pct else "")
        else:
            diff_str = diff
        # 优胜标记（只有双方均达统计门槛时才标）
        mark = ""
        if sig_1h and sig_4h and isinstance(h_val, (int, float)) and isinstance(v_val, (int, float)):
            if better == "high" and v_val > h_val:
                mark = " ⭐"
            elif better == "low" and v_val < h_val:
                mark = " ⭐"
            elif better == "high" and h_val > v_val:
                mark = " ←"
            elif better == "low" and h_val < v_val:
                mark = " ←"
        h_str = f"{h_val:.4f}" + ("%" if is_pct else "")
        v_str = f"{v_val:.4f}" + ("%" if is_pct else "")
        print(f"│ {name:<28} │ {h_str:>14} │ {v_str:>14} │ {diff_str:>12} {mark}")

    print("\n" + "=" * 78)
    print("  📊 方案1：BTC 单币 周期对比（1H vs 4H）")
    print(f"  1H: N-Folds={m_1h.get('n_folds','?')} 配置={m_1h.get('cfg_level','?')} "
          f"| 4H: N-Folds={m_4h.get('n_folds','?')} 配置={m_4h.get('cfg_level','?')}")
    print(f"  其他参数统一：TP=3.0ATR / SL=2.0ATR / max_hold=60bars / "
          f"fee={FEE_RATE:.4f} / slippage={SLIPPAGE_RATE:.4f}")
    print("=" * 78)
    print(f"│ {'指标':<28} │ {'1H (现用)':>14} │ {'4H (候选)':>14} │ {'差值(4H-1H)':>12} │")
    print("─" * 78)
    row("总交易数", "total_trades", m_1h["total_trades"], m_4h["total_trades"], better="high")
    row("整体胜率", "win_rate", m_1h["win_rate"], m_4h["win_rate"], better="high", is_pct=True)
    row("总收益率", "total_return_pct", m_1h["total_return_pct"], m_4h["total_return_pct"], better="high", is_pct=True)
    row("单笔平均收益", "avg_return_per_trade_pct", m_1h["avg_return_per_trade_pct"], m_4h["avg_return_per_trade_pct"], better="high", is_pct=True)
    row("最大回撤", "max_drawdown_pct", m_1h["max_drawdown_pct"], m_4h["max_drawdown_pct"], better="low", is_pct=True)
    row("盈亏比(ProfitFactor)", "profit_factor", m_1h["profit_factor"], m_4h["profit_factor"], better="high")
    row("夏普比率", "sharpe_ratio", m_1h["sharpe_ratio"], m_4h["sharpe_ratio"], better="high")
    row("平均持仓天数", "avg_hold_days", m_1h["avg_hold_days"], m_4h["avg_hold_days"], better="high")
    print("─" * 78)
    row("【做多】交易数", "long_count", m_1h["long_count"], m_4h["long_count"], better="high")
    row("【做多】胜率", "long_win_rate", m_1h["long_win_rate"], m_4h["long_win_rate"], better="high", is_pct=True)
    row("【做多】单均收益", "long_avg_return_pct", m_1h["long_avg_return_pct"], m_4h["long_avg_return_pct"], better="high", is_pct=True)
    row("【做空】交易数", "short_count", m_1h["short_count"], m_4h["short_count"], better="high")
    row("【做空】胜率", "short_win_rate", m_1h["short_win_rate"], m_4h["short_win_rate"], better="high", is_pct=True)
    row("【做空】单均收益", "short_avg_return_pct", m_1h["short_avg_return_pct"], m_4h["short_avg_return_pct"], better="high", is_pct=True)
    print("=" * 78)

    # 结论：先评估样本量，再比优劣
    print()
    if not sig_1h:
        print(f"⚠️  1H 交易数仅 {m_1h['total_trades']} 笔（< {MIN_SIGNIFICANT_TRADES} 笔门槛），统计显著性不足")
    if not sig_4h:
        print(f"⚠️  4H 交易数仅 {m_4h['total_trades']} 笔（< {MIN_SIGNIFICANT_TRADES} 笔门槛），统计显著性不足")

    if not (sig_1h and sig_4h):
        print("\n🎯 结论：至少一周期样本量不足（<20 笔交易），无法得出谁更优的统计结论。")
        print("  建议：① 扩展 4H K线历史数据（至少 3000 根≈1.4 年）用于 Walk-Forward；")
        print("        ② 或降低 conf_threshold 放宽信号过滤门槛，增加交易数；")
        print("        ③ 或直接启动方案2（3 币种组合：BTC + ETH + 主流币）看组合层面表现。")
        # 样本不足时仍给出"当前观察结果"（非结论）
        print("\n📝 当前观察（非结论，仅供参考）：")
        if sig_1h:
            print(f"  1H: {m_1h['total_trades']}笔 胜率{m_1h['win_rate']*100:.1f}% "
                  f"收益{m_1h['total_return_pct']:+.2f}% 夏普{m_1h['sharpe_ratio']:.2f} "
                  f"回撤{m_1h['max_drawdown_pct']:.2f}%")
        if sig_4h:
            print(f"  4H: {m_4h['total_trades']}笔 胜率{m_4h['win_rate']*100:.1f}% "
                  f"收益{m_4h['total_return_pct']:+.2f}% 夏普{m_4h['sharpe_ratio']:.2f} "
                  f"回撤{m_4h['max_drawdown_pct']:.2f}%")
        return

    win = []
    if m_4h["win_rate"] > m_1h["win_rate"]:
        win.append("✅ 胜率更高（趋势过滤有效）")
    if m_4h["total_return_pct"] > m_1h["total_return_pct"]:
        win.append("✅ 总收益更高")
    if m_4h["max_drawdown_pct"] < m_1h["max_drawdown_pct"]:
        win.append("✅ 回撤更低")
    if m_4h["profit_factor"] > m_1h["profit_factor"]:
        win.append("✅ 盈亏比更高")
    if m_4h["sharpe_ratio"] > m_1h["sharpe_ratio"]:
        win.append("✅ 风险调整收益(夏普)更高")

    if len(win) >= 3:
        print("\n🎯 结论：4H 周期在 BTC 单币上综合表现优于 1H，可考虑扩展到多币种方案2验证。")
    elif len(win) == 0:
        print("\n🎯 结论：1H 周期全面优于 4H，维持现状。")
    else:
        print("\n🎯 结论：两周期各有优劣，建议再跑方案2（3币种组合）综合判断。")
    for w in win:
        print(f"  {w}")


def main():
    print("🚀 方案1：BTC 单币 1H vs 4H 周期可行性验证 — 启动")
    print(f"   时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("   真实数据，无模拟兜底 | BCRM 2.0 Walk-Forward 回测器")
    print("-" * 78)

    _register_all_features()

    # =================== 第一步：真实数据探针 ===================
    print("\n【阶段1/4】数据探针 — 确认两个周期的实际数据量/时间范围")
    probe_1h = data_probe("1H", MAX_BARS_1H)
    probe_4h = data_probe("4H", MAX_BARS_4H)

    if not probe_1h["enough"] or not probe_4h["enough"]:
        print("\n❌ 数据探针未通过，无法启动回测：")
        if not probe_1h["enough"]:
            print(f"   - 1H: {probe_1h['n_bars']}/{probe_1h['min_needed']} 根")
        if not probe_4h["enough"]:
            print(f"   - 4H: {probe_4h['n_bars']}/{probe_4h['min_needed']} 根")
        sys.exit(1)
    print("\n✅ 两周期数据均满足 N-Folds Walk-Forward 最低要求")

    # =================== 第二步：拉取参考 ref_df ===================
    print("\n【阶段2/4】拉取 BTC 跨资产特征参考 ref_df（1H 和 4H 各自一份）")
    ref_1h = fetch_ref_df("1H", MAX_BARS_1H)
    ref_4h = fetch_ref_df("4H", MAX_BARS_4H)
    print(f"   1H ref_df: {len(ref_1h)} 根")
    print(f"   4H ref_df: {len(ref_4h)} 根")

    # =================== 第三步：1H 回测 ===================
    print(f"\n【阶段3/4】BTC 1H Walk-Forward 回测（{probe_1h['n_folds']}折，{probe_1h['cfg_level']}配置）")
    try:
        metrics_1h = run_backtest("1H", MAX_BARS_1H, ref_1h, probe_cfg=probe_1h, verbose=True)
    except Exception as e:
        print(f"\n❌ BTC 1H 回测失败: {e}")
        traceback.print_exc()
        sys.exit(2)

    # =================== 第四步：4H 回测 ===================
    print(f"\n【阶段4/4】BTC 4H Walk-Forward 回测（{probe_4h['n_folds']}折，{probe_4h['cfg_level']}配置）")
    try:
        metrics_4h = run_backtest("4H", MAX_BARS_4H, ref_4h, probe_cfg=probe_4h, verbose=True)
    except Exception as e:
        print(f"\n❌ BTC 4H 回测失败: {e}")
        traceback.print_exc()
        sys.exit(3)

    # =================== 对比报告 ===================
    print_comparison(metrics_1h, metrics_4h)

    # 保存详细结果
    out_dir = YIJING_ROOT / "reports"
    out_dir.mkdir(exist_ok=True)
    out_file = out_dir / f"btc_timeframe_compare_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump({
            "symbol": SYMBOL,
            "params": {
                "n_folds_target": N_FOLDS_TARGET,
                "conf_threshold": CONF_THRESHOLD,
                "tp_atr": TP_ATR,
                "sl_atr": SL_ATR,
                "max_hold_bars": MAX_HOLD_BARS,
                "fee_rate": FEE_RATE,
                "slippage_rate": SLIPPAGE_RATE,
            },
            "probe": {"1H": probe_1h, "4H": probe_4h},
            "metrics_1h": metrics_1h,
            "metrics_4h": metrics_4h,
            "generated_at": datetime.now().isoformat(),
        }, f, ensure_ascii=False, indent=2)
    print(f"\n💾 详细 JSON 结果已保存: {out_file}")


if __name__ == "__main__":
    main()
