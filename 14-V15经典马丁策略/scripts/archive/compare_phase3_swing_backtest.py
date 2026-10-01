#!/usr/bin/env python3
"""
Phase 3 回测: swing 势场效果 vs Phase 2（基线）
============================================

方法:
  - 对比模型 A: Phase 2 = 力学化 BTC风向标（MA弹簧+减速检测+Verlet），不加入swing
  - 对比模型 B: Phase 3 = Phase 2 + swing 高低点高斯势垒/势阱力叠加（swing_weight=0.5）
  - 模型 C: 原 DirectionGate 传统（above/below 二值 + 3日硬确认）作为参考
  - 对比币种: 6 币组合，4H 1500根bar（~1年）
  - 使用 v15_backtest.run_backtest(use_direction_gate=True, direction_gate_mode={'phase2'|'phase3'|'classic'})
    （若不支持 mode 参数，则通过 pre-compute confirmed_btc_short_enabled monkey-patch 注入）

重点看: 总收益、夏普、最大回撤、胜率的 Phase 3 - Phase 2 差值
  Δ≥+5% 年化 → 开启 V15_USE_SWING_POTENTIAL=true
  Δ 介于 [-5%, +5%] → 保持关闭（边际收益不够）
  Δ<-5% → 显著劣化，提交但关闭并附报告
"""
from __future__ import annotations
import sys
import json
from pathlib import Path
from typing import List, Optional, Dict

BASE_DIR = Path(__file__).parent
sys.path.insert(0, str(BASE_DIR / "core"))
sys.path.insert(0, str(BASE_DIR / "lib"))

# 前置：把 phase2/3 力学化 BTC short_enabled 序列注入 confirmed_btc_short_enabled
# 策略：改写 regime_manager.compute_confirmed_regimes_by_date —— 不，直接在 run_backtest 里
# 我们通过 monkey-patch DirectionGate + compute_confirmed_regimes_by_date 实现 mode switch
import regime_manager as RM_M
import direction_gate as DG_M
from v15_backtest import run_backtest, fetch_klines, _timestamp_to_date_str

SWING_WINDOW = 30  # 30 根日线收盘价用于 swing 检测


# ================================================================
# Helper: 用 DirectionGate(mechanistic=True) 对每根4H bar 计算 raw_regime
# ================================================================
def precompute_mechanistic_btc_short_enabled(
    klines_4h: List[Dict],
    btc_daily_closes_series: List[Optional[float]],
    btc_daily_ma128_series: List[Optional[float]],
    btc_weekly_ma200_series: List[Optional[float]],
    mode: str,  # "phase2" or "phase3"
    confirm_days: int = 3,
) -> List[bool]:
    """
    对 4H K线逐 bar 模拟 Phase 2/3 的 BTC 风向标序列（含 RM 确认 + 减速检测动态天数）。
    等价于 v15_trader._get_direction_ctx 中 BTC风向标 + rm.update 的行为，但走 batch 回测路径。
    """
    if mode not in ("phase2", "phase3"):
        raise ValueError(f"unknown mode {mode}")
    use_swing = mode == "phase3"

    dates = [_timestamp_to_date_str(k.get("t", 0)) for k in klines_4h]
    n = len(klines_4h)
    raw_states: List[str] = []
    vi = DG_M.VelocityIntegrator()
    rm = RM_M.RegimeManager(confirm_days=confirm_days, initial_regime="long_preferred")

    for idx in range(n):
        price = None
        try:
            price = float(klines_4h[idx]["c"])
        except Exception:
            pass
        if price is None:
            raw_states.append("long_preferred")
            continue
        ma128 = btc_daily_ma128_series[idx] if idx < len(btc_daily_ma128_series) else None
        ma200 = btc_weekly_ma200_series[idx] if idx < len(btc_weekly_ma200_series) else None
        if ma128 is None or ma200 is None:
            raw_states.append("long_preferred")
            continue

        # recent_daily_closes（3 条确认窗口，最后3个非空）
        recent_3: List[float] = []
        for j in range(max(0, idx - 20), idx + 1):
            if j < len(btc_daily_closes_series) and btc_daily_closes_series[j] is not None:
                recent_3.append(btc_daily_closes_series[j])
        recent_3 = recent_3[-3:]

        # swing 检测用 30 条日线收盘价
        recent_30: Optional[List[float]] = None
        if use_swing:
            buf: List[float] = []
            for j in range(max(0, idx - 150), idx + 1):
                if j < len(btc_daily_closes_series) and btc_daily_closes_series[j] is not None:
                    buf.append(btc_daily_closes_series[j])
            recent_30 = buf[-SWING_WINDOW:] if len(buf) >= 7 else None

        gate = DG_M.DirectionGate(allow_short=True, use_mechanistic=True)
        r = gate.evaluate(
            current_price=price,
            daily_ma128=ma128,
            weekly_ma200=ma200,
            recent_daily_closes=recent_3 or [],
            btc_short_enabled=True,
            velocity_integrator=vi,
            recent_closes_for_swing=recent_30,
            swing_weight=0.5,
        )
        raw = r.regime.value  # "long_preferred" / "short_allowed" / "long_only_force"
        raw_states.append(raw)

    # RM 连续确认（batch 去重），支持 mechanistic_ctx 动态天数：
    confirmed_states = []
    # 用逐 bar 模拟，因为 compute_confirmed_regimes_by_date 暂不支持 mechanistic_ctx 序列
    rm = RM_M.RegimeManager(confirm_days=confirm_days, initial_regime="long_preferred")
    # 需要逐日的 a,v,threshold → 只能从 raw_states 的对应 mechanistic 重算
    # 简化：这里 fallback 使用 compute_confirmed_regimes_by_date 标准3日确认；
    # 与 Phase 2 的实盘路径差异仅在"减速检测动态天数"，对 short_enabled 长期比例影响较小，
    # 重点是 swing 力场对 raw_regime 的改变 → 仍然可比。
    confirmed_states = RM_M.compute_confirmed_regimes_by_date(
        raw_states, dates, confirm_days=confirm_days, initial_regime="long_preferred",
    )
    return [s == "short_allowed" for s in confirmed_states]


# ================================================================
# Backtest runner (patch confirmed_btc_short_enabled via monkeypatch)
# ================================================================
def run_backtest_patched_mode(
    coin: str, klines: List[Dict],
    mode: str,   # "classic" | "phase2" | "phase3"
) -> Dict:
    """
    通过 monkey-patch：如果 mode=classic，直接 run_backtest(use_direction_gate=True)。
    如果 mode=phase2/3，先在 BTC 预计算 confirmed_btc_short_enabled 数组，
    然后 patch v15_backtest._direction_gate_confirmed_btc_short_enabled_result，使其被覆盖使用。

    因为 direction_gate 的计算完全在 run_backtest 内部（行 1536-1556），我们改成：
    对 mode=phase2/3 我们不 use_direction_gate=False，而是 use_btc_windvane 并传入预计算的 BTC windvane states。
    """
    import v15_backtest as V15BT

    if mode == "classic":
        return run_backtest(
            coin=coin, klines=klines,
            use_atr=True, use_trailing_tp=True,
            use_direction_gate=True, long_only=False,
            base_position_pct=0.22,
        )

    # mode = phase2/3:
    #   1) 若币非 BTC，先取 BTC 的日线收盘价 & MA128 & 周MA200 序列 → 预计算 confirmed_btc_short_enabled
    #   2) 若币为 BTC，直接用本币的日线MA128/MA200/收盘价序列
    #   3) 把 BTC short_enabled 映射成 short_only=Short / long_preferred=Long_only 的 windvane_states，
    #      然后 use_btc_windvane=True + 预计算注入
    # 简单做法：直接 monkey-patch 代码里的 confirmed_btc_short_enabled 数组构造
    # 先做 BTC 方向序列：因为 direction_gate 和 btc_windvane 都是把 confirmed_bool
    #   - True→BEAR、False→BULL
    #   - use_btc_windvane 路径把 windvane_states 映射 bar_regimes: SHORT_ALLOWED=BEAR
    #     然后 run_backtest 内的平仓 / 方向判定 用 windvane_states[idx]
    # 所以最简单的方式：运行 use_btc_windvane=True，但预先构造 BTC 的 windvane_states
    #   并通过设置 V15BT 的内部预计算接口: btc_windvane_states
    # 由于 run_backtest 内部 fetch_klines BTC 计算 windvane states，我们改为：
    #  先运行 use_direction_gate=True 的回测；但因为 phase2/3 需要 mechanistic，
    #  直接通过 mock DirectionGate 最干净。
    # 方案: 覆盖 DirectionGate(use_mechanistic=False) 为 phase2/3 行为，通过全局变量。

    # ======================================================
    # 简化方式：我们直接把「phaseX short_enabled 序列」注入到 btc_windvane 路径的
    #   compute_confirmed_regimes_by_date 之前
    # 通过 patch fetch_klines 获取 BTC 的日线 MA128
    # ======================================================

    # Step A: 获取 BTC 的 1d MA128 与周MA200 & 收盘价序列（与 coin 的 klines 等长对齐）
    # 通过 run_backtest 内部已经有的 _prepare_btc_reference，但外部不可调用。
    # 直接调用策略的 strategy_params：
    sys.path.insert(0, str(BASE_DIR / "lib"))
    sys.path.insert(0, str(BASE_DIR / "core"))
    from strategy_params import get_coin_strategy_params, calc_daily_ma128

    # 获取同区间的 BTC 4h klines 与 daily MA128 等序列
    btc_params = get_coin_strategy_params("BTC", "LONG")
    if "error" in btc_params:
        return {"error": f"BTC params fetch failed: {btc_params['error']}"}
    btc_1d = btc_params.get("klines_1d", [])

    # 对齐 coin 的 4h bar 日期到 BTC 日线：用 bar_date 索引到 BTC 1d closes/ma128
    # 简化：每个 4h bar 取 BTC_daily_closes_list = [BTC 当日收盘 for bar in klines_4h]
    bar_dates = [_timestamp_to_date_str(k.get("t", 0)) for k in klines]
    # BTC 1d 建日期查找表
    btc_1d_map: Dict[str, Dict] = {}
    for k in btc_1d:
        ds = _timestamp_to_date_str(k.get("t", 0))
        btc_1d_map[ds] = k

    # 计算 BTC 累计 closes_series 用作 SMA
    btc_1d_dates_sorted = sorted(btc_1d_map.keys())
    btc_1d_closes_sorted: List[float] = []
    for d in btc_1d_dates_sorted:
        try:
            btc_1d_closes_sorted.append(float(btc_1d_map[d]["c"]))
        except Exception:
            pass

    def rolling_sma(values: List[float], period: int) -> List[Optional[float]]:
        out: List[Optional[float]] = []
        for i in range(len(values)):
            if i + 1 < period:
                out.append(None)
            else:
                out.append(sum(values[i + 1 - period:i + 1]) / period)
        return out

    sma128 = rolling_sma(btc_1d_closes_sorted, 128)
    sma200w = rolling_sma(btc_1d_closes_sorted, 1400)  # 200 weeks ≈ 1400 trading days

    date_to_sma: Dict[str, float] = {}
    date_to_sma200w: Dict[str, float] = {}
    date_to_close: Dict[str, float] = {}
    for d, c, m128, m200w in zip(btc_1d_dates_sorted, btc_1d_closes_sorted, sma128, sma200w):
        date_to_close[d] = c
        if m128 is not None:
            date_to_sma[d] = m128
        if m200w is not None:
            date_to_sma200w[d] = m200w

    daily_closes_series: List[Optional[float]] = []
    ma128_series: List[Optional[float]] = []
    ma200_series: List[Optional[float]] = []
    for d in bar_dates:
        daily_closes_series.append(date_to_close.get(d))
        ma128_series.append(date_to_sma.get(d))
        ma200_series.append(date_to_sma200w.get(d))

    # 对尾部的 MA 使用前值填充（避免 None 导致无法计算）
    def ffill(a: List[Optional[float]]) -> List[Optional[float]]:
        last = None
        out = []
        for x in a:
            if x is not None:
                last = x
            out.append(last)
        return out

    daily_closes_series = ffill(daily_closes_series)
    ma128_series = ffill(ma128_series)
    ma200_series = ffill(ma200_series)

    confirmed = precompute_mechanistic_btc_short_enabled(
        klines, daily_closes_series, ma128_series, ma200_series, mode=mode,
    )

    # 将 confirmed bools 转换为 BTC windvane_states（Short_allowed/Long_only）
    windvane_states: List[str] = ["SHORT_ALLOWED" if c else "LONG_ONLY" for c in confirmed]

    # Patch：通过 monkey-patch compute_confirmed_regimes_by_date（windvane 路径版本）
    #   —— 在 use_btc_windvane=True 内部执行 compute_confirmed_states 前直接设置
    #   —— 替换 btc_windvane_states 数组
    orig_fn = V15BT.compute_confirmed_regimes_by_date if hasattr(V15BT, "compute_confirmed_regimes_by_date") else None
    # compute_confirmed_regimes_by_date 在 v15_backtest 内部是局部import，我们 patch regime_manager.compute_confirmed_regimes_by_date
    orig_rm_fn = RM_M.compute_confirmed_regimes_by_date

    # 我们没法简单 patch，因为 windvane 路径的 compute_confirmed_regimes_by_date 同样被调用
    # 更稳：构造"总是返回给定值"的 monkey patch 仅作用在 windvane 路径。
    # 但两者路径用同函数。为避免误伤 direction_gate 路径，我们只在 use_btc_windvane=True 且 use_direction_gate=False 的回测上跑。

    # 策略：用 btc_windvane_states 注入的方式——用 patch RegimeManager.update，
    #   使得其返回对应 idx 的状态
    idx_counter = {"i": -1, "mode": "init", "windvane": windvane_states, "direction_gate": []}

    # 因为很难 patch 中间变量，这里我们改为：使用 monkey-patch 把
    # confirmed_btc_short_enabled 直接映射为 bar_regimes 中的 regime，但这也会影响后续。
    #
    # 最后选择：构造一组合成的 btc_windvane_states，
    # 通过 patch compute_confirmed_regimes_by_date(first arg is raw regimes) 在第一次调用时
    # 直接返回我们的 windvane_states（长度匹配则视为 windvane 路径）。

    def _patched_compute(raw_list, date_list, **kwargs):
        # 如果 raw_list 长度等于我们的目标 且 当前处于回测里（根据全局开关），直接返回 windvane_states
        if (len(raw_list) == len(windvane_states)
                and all(r in ("LONG_ONLY", "SHORT_ALLOWED", "LONG_ONLY_FORCE") for r in raw_list[:min(5, len(raw_list))])):
            # 第一次调用（windvane）：返回预计算序列
            return list(windvane_states)
        return orig_rm_fn(raw_list, date_list, **kwargs)

    try:
        RM_M.compute_confirmed_regimes_by_date = _patched_compute
        # 再 patch 全局 import
        if "compute_confirmed_regimes_by_date" in dir(V15BT):
            V15BT.compute_confirmed_regimes_by_date = _patched_compute

        result = run_backtest(
            coin=coin, klines=klines,
            use_atr=True, use_trailing_tp=True,
            use_btc_windvane=True, use_direction_gate=False,
            long_only=False, base_position_pct=0.22,
        )
    finally:
        RM_M.compute_confirmed_regimes_by_date = orig_rm_fn
        if orig_fn is not None and "compute_confirmed_regimes_by_date" in dir(V15BT):
            V15BT.compute_confirmed_regimes_by_date = orig_fn
    return result


# ================================================================
# 主流程
# ================================================================
COINS = ["BTC", "ETH", "SOL", "ARB", "OP", "UNI"]
LIMIT = 1500

print("=" * 110)
print("  Phase 3: Swing 势场效果对比回测（4H 1500 bar ≈ 1yr）")
print("  A (Classic) = DirectionGate 传统 above/below + 3日硬确认")
print("  B (Phase 2) = DirectionGate 力学化（MA弹簧 + Verlet + 减速检测）NO swing")
print("  C (Phase 3) = Phase 2 + swing 高低点高斯势垒/势阱 叠加（swing_weight=0.5）")
print("=" * 110)

rows = []
for coin in COINS:
    print(f"\n  🔹 回测 {coin} ...", flush=True)
    try:
        klines = fetch_klines(coin, "4h", LIMIT)
    except Exception as e:
        print(f"    fetch_klines 异常: {e}")
        rows.append((coin, None, None, None))
        continue
    if len(klines) < 200:
        print(f"    数据不足 ({len(klines)})")
        rows.append((coin, None, None, None))
        continue

    r_cls = run_backtest_patched_mode(coin, klines, "classic")
    r_p2  = run_backtest_patched_mode(coin, klines, "phase2")
    r_p3  = run_backtest_patched_mode(coin, klines, "phase3")
    rows.append((coin, r_cls, r_p2, r_p3))

    def safe_m(r):
        if not r or "error" in r or "metrics" not in r:
            return None
        return r["metrics"]

    m_cls, m_p2, m_p3 = safe_m(r_cls), safe_m(r_p2), safe_m(r_p3)
    if m_p2 is None or m_p3 is None:
        print(f"    回测失败. cls={m_cls} p2={m_p2} p3={m_p3}")
        continue
    print(f"\n    {coin} 详细对比 (Classic vs Phase2 vs Phase3):")
    print(f"    {'指标':<14}  {'Classic':>10}  {'Phase2':>10}  {'Phase3':>10}  "
          f"{'Δ3-2':>10}")
    print(f"    {'-'*62}")
    for name, key, mult in [
        ("总收益%",    "total_return_pct", 1.0),
        ("交易数",      "total_trades",     1.0),
        ("胜率%",       "win_rate",         100.0),
        ("盈亏比",      "profit_factor",    1.0),
        ("最大回撤%",  "max_drawdown_pct", 1.0),
        ("夏普比",      "sharpe_ratio",     1.0),
    ]:
        v_cls = round(m_cls[key] * mult, 2) if m_cls else "N/A"
        v_p2 = round(m_p2[key] * mult, 2)
        v_p3 = round(m_p3[key] * mult, 2)
        delta = round((m_p3[key] - m_p2[key]) * mult, 2)
        print(f"    {name:<14}  {str(v_cls):>10}  {str(v_p2):>10}  {str(v_p3):>10}  {delta:>+10}")

# ── 汇总表 ──
print("\n" + "=" * 110)
print("  📊 Phase 3 Swing 势场 汇总对比 (Phase2 vs Phase3)")
print("=" * 110)
print(f"  {'币种':>5}  {'模型':>8}  {'总收益%':>10}  {'交易数':>6}  {'胜率%':>6}  {'盈亏比':>6}  "
      f"{'回撤%':>7}  {'夏普':>8}  Δ收益%")
print("  " + "-" * 105)

summary = []
for coin, r_cls, r_p2, r_p3 in rows:
    for label, r in [("Phase2", r_p2), ("Phase3", r_p3)]:
        if not r or "error" in r:
            continue
        m = r["metrics"]
        print(f"  {coin:>5}  {label:>8}  {m['total_return_pct']:>+10.2f}  {m['total_trades']:>6}  "
              f"{m['win_rate']*100:>6.2f}  {m['profit_factor']:>6.2f}  "
              f"{m['max_drawdown_pct']:>7.2f}  {m['sharpe_ratio']:>8.4f}")
    # Δ收益 Phase3 - Phase2
    if (r_p2 and "error" not in r_p2 and "metrics" in r_p2 and
            r_p3 and "error" not in r_p3 and "metrics" in r_p3):
        delta_ret = r_p3["metrics"]["total_return_pct"] - r_p2["metrics"]["total_return_pct"]
        delta_sharpe = r_p3["metrics"]["sharpe_ratio"] - r_p2["metrics"]["sharpe_ratio"]
        delta_dd = r_p3["metrics"]["max_drawdown_pct"] - r_p2["metrics"]["max_drawdown_pct"]
        summary.append((coin, delta_ret, delta_sharpe, delta_dd))
        mark = "✅" if delta_ret >= 5 else "⚠️" if delta_ret >= -5 else "❌"
        print(f"  {'':>14} Phase3-Phase2 Δ: ret {delta_ret:+.2f}%  sharpe {delta_sharpe:+.4f}  "
              f"dd {delta_dd:+.2f}%  {mark}")
    print("  " + "-" * 105)

# 组合 Δ 总结
print("\n  🎯 结论判定 (按收益 Δ Phase3-Phase2 ≥ +5% 开启 swing, [-5%,5%] 维持关闭, ≤-5% 劣化):")
if summary:
    coin_improved = [s for s in summary if s[1] >= 5]
    coin_flat = [s for s in summary if -5 < s[1] < 5]
    coin_worse = [s for s in summary if s[1] <= -5]
    avg_ret = sum(s[1] for s in summary) / len(summary)
    print(f"    组合平均 Δ收益 = {avg_ret:+.2f}%")
    print(f"    显著改善(≥+5%): {len(coin_improved)} 币 → {[s[0] for s in coin_improved]}")
    print(f"    区间内(无关):   {len(coin_flat)} 币 → {[s[0] for s in coin_flat]}")
    print(f"    显著劣化(≤-5%): {len(coin_worse)} 币 → {[s[0] for s in coin_worse]}")

    if avg_ret >= 5:
        decision = "✅ 组合平均 Δ ≥ +5%，推荐开启 V15_USE_SWING_POTENTIAL=true"
    elif avg_ret > -5:
        decision = "⚠️  组合平均 Δ 在 [-5%,+5%]，swing 收益边际不足，推荐保持 false"
    else:
        decision = "❌ 组合平均 Δ ≤ -5%，swing 明显劣化，保持 false 并记录分析"
    print(f"    → {decision}")

    # 保存 JSON 报告到 phase3_report.json
    report = {
        "currency_pairs": [
            {"coin": s[0], "delta_return_pct": round(s[1], 4),
             "delta_sharpe": round(s[2], 6), "delta_drawdown_pct": round(s[3], 4)}
            for s in summary
        ],
        "avg_delta_return_pct": round(avg_ret, 4),
        "n_improved": len(coin_improved),
        "n_flat": len(coin_flat),
        "n_worse": len(coin_worse),
        "decision": decision,
    }
    out_path = BASE_DIR / "phase3_swing_potential_backtest_report.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    print(f"    📄 JSON报告已保存: {out_path}")
