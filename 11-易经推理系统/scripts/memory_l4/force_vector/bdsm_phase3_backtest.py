#!/usr/bin/env python3
"""BDSM Phase 3 A/B 回测脚本 — spec §5.3 Phase 3。

A组：一次性建仓 + 固定TP 6% + SL 15%（原 BCRM 逻辑）
B组：动态CVS驱动分批建仓 + 趋势止损(MA200) + 价值发现止盈（Phase1/2 新逻辑）

验收标准：
  - MDD ≤ 120% 纯BCRM
  - 反向丢弃率 ≤ 15%
  - 胜率 ≥ 90%

数据来源与局限说明：
  - K线：OKX 公开 API（1D 周期，230根，用于 MA200 + 30日回测窗口）
  - BDS Score：今日快照作为 30 日代理值（data_center.db 无历史时序 BDS 数据，
    基本面日变化极小可接受代理；TS 技术面已日级动态，CVS = BDS×0.6 + TS×0.4
    → 40% 动态 + 60% 静态近似）
  - TS/CVS/trend_stop/value_exit：Phase 0 函数实时计算（使用历史 K 线，时序正确）

MDD 计算说明（v2 修正 2026-09-03）：
  - 旧版：per-trade 累加 PnL → 低估持仓期间最大回撤（漏 intra-trade drawdown）
  - 新版：日级 mark-to-market 权益曲线 → 正确反映每日浮动盈亏的回撤

运行：
  cd 11-易经推理系统
  PYTHONPATH="$PWD:$PWD/scripts/memory_l4:$PWD/scripts/memory_l4/force_vector" \
    python3 scripts/memory_l4/force_vector/bdsm_phase3_backtest.py
"""
from __future__ import annotations

import json
import os
import sys
import math
from pathlib import Path
from datetime import datetime, timezone

# ── 路径设置 ──────────────────────────────────────────────────────
_THIS_DIR = Path(__file__).resolve().parent
_MEM_L4_DIR = _THIS_DIR.parent  # scripts/memory_l4
_BASE_11 = _MEM_L4_DIR.parent  # 11-易经推理系统
for p in (str(_THIS_DIR), str(_MEM_L4_DIR), str(_BASE_11)):
    if p not in sys.path:
        sys.path.insert(0, p)

# ── 导入 Phase 0 函数 ─────────────────────────────────────────────
from bdsm_snapshot_writer import (  # noqa: E402
    BDSM_COINS,
    _compute_technical_assessment,
    _compute_cvs,
    _compute_trend_stop,
    _compute_value_exit,
    _DEFAULT_SNAPSHOT_DIR,
    load_today_snapshot,
)

# ── 配置 ───────────────────────────────────────────────────────────
BACKTEST_DAYS = 90  # P1-1: 30→90 日，对齐 spec §3.1「数周~数月」持仓周期
MA_LONG = 200
KLINE_LIMIT = 290  # 200(MA) + 90(回测窗口)
PROXY = os.environ.get("HTTP_PROXY", "http://127.0.0.1:7890")

# A组参数（原 BCRM 逻辑）
A_TP_PCT = 0.06  # 固定 TP 6%
A_SL_PCT = 0.15  # 固定 SL 15%
A_NOTIONAL = 167.0  # 一次性建仓名义金额

# B组参数（Phase1/2 新逻辑）
B_BUDGET = 167.0  # 子池预算


def fetch_klines(coin: str, bar: str = "1D", limit: int = KLINE_LIMIT) -> list:
    """从 OKX 公开 API 获取 K 线。FAIL-OPEN：异常 → 空列表。"""
    import requests
    inst_id = f"{coin}-USDT-SWAP"
    url = "https://www.okx.com/api/v5/market/history-candles"
    params = {"instId": inst_id, "bar": bar, "limit": str(limit)}
    proxies = {"http": PROXY, "https": PROXY}
    try:
        r = requests.get(url, params=params, proxies=proxies, timeout=15)
        data = r.json()
        if data.get("code") != "0":
            print(f"[{coin}] OKX API 错误: {data.get('msg', 'unknown')}")
            return []
        # OKX K线格式: [ts, o, h, l, c, vol, volCcy, volCcyQuote, confirm]
        raw = data.get("data", [])
        # 反转为时间正序
        klines = []
        for k in reversed(raw):
            klines.append({
                "ts": int(k[0]),
                "o": float(k[1]),
                "h": float(k[2]),
                "l": float(k[3]),
                "c": float(k[4]),
                "v": float(k[5]),
            })
        return klines
    except Exception as exc:
        print(f"[{coin}] 获取K线失败: {exc}")
        return []


def load_bds_scores() -> dict:
    """从今日快照加载各币 BDS Score。FAIL-OPEN → 空 dict。"""
    try:
        snap = load_today_snapshot()
        coins = snap.get("coins") or {}
        return {k.upper(): float(v.get("bds_score", 0.0) or 0.0)
                for k, v in coins.items()}
    except Exception:
        return {}


def load_historical_bds_scores() -> dict:
    """P2: 从快照目录加载历史 BDS 数据，返回 {coin: {date_str: bds_score}}。

    读取 _DEFAULT_SNAPSHOT_DIR 下所有 bdsm_snapshot_YYYYMMDD.json 文件，
    提取每个币每日 BDS Score。FAIL-OPEN → 空 dict（无历史快照时不影响回测）。
    """
    result: dict = {}
    try:
        snap_dir = _DEFAULT_SNAPSHOT_DIR
        if not os.path.isdir(snap_dir):
            return result
        # 扫描所有历史快照文件
        for fname in sorted(os.listdir(snap_dir)):
            if not fname.startswith("bdsm_snapshot_") or not fname.endswith(".json"):
                continue
            date_str = fname.replace("bdsm_snapshot_", "").replace(".json", "")
            fpath = os.path.join(snap_dir, fname)
            try:
                with open(fpath) as f:
                    snap = json.load(f)
                coins = snap.get("coins") or {}
                for coin, data in coins.items():
                    coin_u = coin.upper()
                    bds = float(data.get("bds_score", 0.0) or 0.0)
                    if coin_u not in result:
                        result[coin_u] = {}
                    result[coin_u][date_str] = bds
            except Exception:
                continue
    except Exception:
        pass
    return result


def get_bds_for_backtest(historical: dict, today_scores: dict, coin: str) -> float:
    """P2: 优先使用历史 BDS 均值（≥7日），否则回退今日快照代理值。"""
    coin_u = coin.upper()
    hist = historical.get(coin_u, {})
    if len(hist) >= 7:
        # 有7日+历史数据 → 用历史均值
        avg = sum(hist.values()) / len(hist)
        return round(avg, 4)
    # 回退今日代理值
    return today_scores.get(coin_u, 0.0)


# ═════════════════════════════════════════════════════════════════
# A组模拟：一次性建仓 + 固定TP/SL
# ═════════════════════════════════════════════════════════════════

def simulate_group_a(klines: list, bds_score: float) -> dict:
    """A组：在回测窗口第一天一次性建仓，固定 TP 6% / SL 15%。

    返回新增 daily_equity: list[(day_idx, equity)] — 日级 mark-to-market 权益曲线。
    """
    _empty = {"trades": [], "pnl_total": 0.0, "win_count": 0,
              "trade_count": 0, "daily_equity": []}
    if len(klines) < MA_LONG + 5:
        return _empty

    window = klines[-BACKTEST_DAYS:]
    pre = klines[-(BACKTEST_DAYS + MA_LONG):-BACKTEST_DAYS]

    entry_day = window[0]
    entry_px = entry_day["c"]
    # 只在 BDS >= 0.3 时建仓（价值投资条件）
    if bds_score < 0.3:
        return {**_empty, "skip_reason": "bds_below_0.3"}

    tp_px = entry_px * (1 + A_TP_PCT)
    sl_px = entry_px * (1 - A_SL_PCT)

    # 逐日检查是否触达 TP/SL
    exit_px = None
    exit_reason = ""
    exit_day_idx = len(window) - 1  # 默认到最后一天
    for i, day in enumerate(window[1:], start=1):
        if day["h"] >= tp_px:
            exit_px = tp_px
            exit_reason = "tp_hit"
            exit_day_idx = i
            break
        if day["l"] <= sl_px:
            exit_px = sl_px
            exit_reason = "sl_hit"
            exit_day_idx = i
            break

    if exit_px is None:
        exit_px = window[-1]["c"]
        exit_reason = "window_end"

    pnl_pct = (exit_px - entry_px) / entry_px
    pnl_usdt = A_NOTIONAL * pnl_pct
    win = pnl_usdt > 0

    # ── 日级权益曲线（mark-to-market）──
    daily_equity = []
    for i, day in enumerate(window):
        if i <= exit_day_idx:
            # 持仓中：equity = A_NOTIONAL × (day_close / entry_px)
            eq = A_NOTIONAL * day["c"] / entry_px
        else:
            # 已平仓：equity = A_NOTIONAL + realized_pnl（恒定）
            eq = A_NOTIONAL + pnl_usdt
        daily_equity.append((i, round(eq, 4)))

    return {
        "trades": [{"entry_px": entry_px, "exit_px": exit_px,
                     "pnl_pct": pnl_pct, "pnl_usdt": pnl_usdt,
                     "reason": exit_reason}],
        "pnl_total": pnl_usdt,
        "win_count": 1 if win else 0,
        "trade_count": 1,
        "daily_equity": daily_equity,
    }


# ═════════════════════════════════════════════════════════════════
# B组模拟：CVS驱动分批建仓 + 趋势止损 + 价值发现止盈
# ═════════════════════════════════════════════════════════════════

def simulate_group_b(klines: list, bds_score: float) -> dict:
    """B组：CVS 驱动分批建仓 + 趋势止损 + 价值发现止盈。

    返回新增 daily_equity: list[(day_idx, equity)] — 日级 mark-to-market 权益曲线。
    """
    _empty = {"trades": [], "pnl_total": 0.0, "win_count": 0,
              "trade_count": 0, "daily_equity": []}
    if len(klines) < MA_LONG + 5:
        return _empty

    window = klines[-BACKTEST_DAYS:]
    pre = klines[-(BACKTEST_DAYS + MA_LONG):-BACKTEST_DAYS]

    accumulated = 0.0
    trades = []
    position_open = False
    entry_px_avg = 0.0
    total_notional = 0.0
    realized_pnl = 0.0      # 累计已实现 PnL（部分平仓产生）
    daily_equity = []
    last_entry_day = -1     # P1-2 §3.5 ⑨: 加仓间隔追踪
    WAR_STATE = "ALLOW"     # P1-2 §3.5 ⑤: 回测中默认 ALLOW（实盘由五计庙算决定）

    for i, day in enumerate(window):
        # 用 pre + window[:i+1] 作为历史数据计算技术面
        hist = pre + window[:i + 1]
        if len(hist) < MA_LONG:
            # K线不足计算MA，记录日级权益后跳过
            daily_equity.append((i, round(B_BUDGET + realized_pnl, 4)))
            continue

        # Phase 0 函数实时计算
        ta = _compute_technical_assessment("", hist, ma_long=MA_LONG, ma_short=128)
        ts_score = ta.get("ts_score", 0.0)
        cvs, ratio = _compute_cvs(bds_score, ts_score)

        # BUG-4 (P0 修复): 估值分位代理公式 — 正方向
        ma_dev = ta.get("ma200_deviation", 0.0)
        val_pct = min(100.0, max(0.0, ma_dev * 2.0 + 50.0))

        # P1-2: 始终计算 trend_stop + value_exit（供退出检查 + 入场前置检查共用）
        ts = _compute_trend_stop("", hist, ma_long=MA_LONG, ma_short=128)
        ve = _compute_value_exit(bds_score, val_pct)
        trend_action = ts.get("action", "none")
        value_action = ve.get("action", "none")

        # 趋势止损检查（已持仓时）
        if position_open:
            # 优先级合并
            _prio = {"full_exit": 5, "reduce50": 3, "reduce30": 2, "none": 0}
            best = max([trend_action, value_action], key=lambda a: _prio.get(a, 0))

            if best in ("full_exit",):
                # 全平
                pnl_pct = (day["c"] - entry_px_avg) / entry_px_avg if entry_px_avg > 0 else 0
                pnl_usdt = total_notional * pnl_pct
                realized_pnl += pnl_usdt
                trades.append({"exit_px": day["c"], "pnl_pct": pnl_pct,
                               "pnl_usdt": pnl_usdt, "reason": f"trend_value_{best}"})
                position_open = False
                accumulated = 0.0
                entry_px_avg = 0.0
                total_notional = 0.0
                daily_equity.append((i, round(B_BUDGET + realized_pnl, 4)))
                continue

            if best in ("reduce50", "reduce30"):
                reduce_ratio = 0.5 if best == "reduce50" else 0.3
                pnl_pct = (day["c"] - entry_px_avg) / entry_px_avg if entry_px_avg > 0 else 0
                pnl_usdt = total_notional * reduce_ratio * pnl_pct
                realized_pnl += pnl_usdt
                trades.append({"exit_px": day["c"], "pnl_pct": pnl_pct,
                               "pnl_usdt": pnl_usdt, "reason": f"trend_value_{best}"})
                total_notional *= (1 - reduce_ratio)
                if total_notional < 5.0:  # 剩余太少 → 全平
                    position_open = False
                    accumulated = 0.0
                    entry_px_avg = 0.0
                    total_notional = 0.0
                # 记录日级权益（平仓后 mark-to-market 剩余仓位 + cash）
                if total_notional > 0 and entry_px_avg > 0:
                    eq = B_BUDGET + realized_pnl + total_notional * (day["c"] / entry_px_avg - 1)
                else:
                    eq = B_BUDGET + realized_pnl
                daily_equity.append((i, round(eq, 4)))
                continue

        # 建仓逻辑（CVS 驱动）+ §3.5 加仓前置检查清单（9条）
        # P0 BUG-1: 叠加 spec §2.4 低估区门槛 (val_pct < 50%)
        # P1-2 §3.5 新增 5 条前置检查：
        #   ① BDS >= 0.0 (基本面未恶化)    ⑤ war_state = ALLOW
        #   ⑦ value_exit != full_exit      ⑧ trend_stop == none
        #   ⑨ 距上次加仓 >= 1 日 (日级=24h > 4h)
        #   已有: ③CVS>=0.3  ⑥可用资金>0
        entry_ok = (
            cvs >= 0.3                          # ③ CVS 达标
            and val_pct < 50.0                  # P0 BUG-1: 低估区
            and bds_score >= 0.0                # ① 基本面未恶化
            and WAR_STATE == "ALLOW"            # ⑤ 宏观允许
            and value_action != "full_exit"     # ⑦ 未触发出场信号
            and trend_action == "none"          # ⑧ 未触发趋势止损
            and (i - last_entry_day) >= 1       # ⑨ 加仓间隔 ≥ 1 日
        )
        if entry_ok:
            remaining = B_BUDGET - accumulated
            if remaining > 0:
                batch = remaining * ratio
                if cvs >= 0.8:
                    batch = remaining  # 打完子弹

                # 更新加权平均入场价
                if total_notional > 0:
                    entry_px_avg = (entry_px_avg * total_notional + day["c"] * batch) / (total_notional + batch)
                else:
                    entry_px_avg = day["c"]

                total_notional += batch
                accumulated += batch
                position_open = True
                last_entry_day = i  # ⑨ 记录加仓日

        # 记录日级权益（mark-to-market）
        if position_open and total_notional > 0 and entry_px_avg > 0:
            eq = B_BUDGET + realized_pnl + total_notional * (day["c"] / entry_px_avg - 1)
        else:
            eq = B_BUDGET + realized_pnl
        daily_equity.append((i, round(eq, 4)))

    # 回测窗口结束 → 平剩余仓位
    if position_open and total_notional > 0:
        last_px = window[-1]["c"]
        pnl_pct = (last_px - entry_px_avg) / entry_px_avg if entry_px_avg > 0 else 0
        pnl_usdt = total_notional * pnl_pct
        realized_pnl += pnl_usdt
        trades.append({"exit_px": last_px, "pnl_pct": pnl_pct,
                        "pnl_usdt": pnl_usdt, "reason": "window_end"})
        # 最后一天权益 = 预算 + 总已实现 PnL
        if daily_equity:
            daily_equity[-1] = (daily_equity[-1][0], round(B_BUDGET + realized_pnl, 4))
        else:
            daily_equity.append((len(window) - 1, round(B_BUDGET + realized_pnl, 4)))

    pnl_total = sum(t["pnl_usdt"] for t in trades)
    win_count = sum(1 for t in trades if t["pnl_usdt"] > 0)
    trade_count = len(trades)

    return {
        "trades": trades,
        "pnl_total": pnl_total,
        "win_count": win_count,
        "trade_count": trade_count,
        "daily_equity": daily_equity,
    }


# ═════════════════════════════════════════════════════════════════
# MDD 计算
# ═════════════════════════════════════════════════════════════════

def compute_mdd_daily(daily_equity_per_coin: list) -> float:
    """日级最大回撤（百分比）。

    Args:
        daily_equity_per_coin: list[list[(day_idx, equity)]] — 每币的日级权益曲线列表

    合并所有币的日级权益为组合权益曲线，然后计算 MDD。
    使用 mark-to-market 每日收盘价，正确反映持仓期间的最大回撤。
    """
    if not daily_equity_per_coin:
        return 0.0

    # 合并：按 day_idx 汇总所有币的权益
    merged = {}  # day_idx → total_equity
    for coin_curve in daily_equity_per_coin:
        for day_idx, eq in coin_curve:
            merged[day_idx] = merged.get(day_idx, 0.0) + eq

    if not merged:
        return 0.0

    # 按日排序，计算 MDD
    sorted_equity = [eq for _, eq in sorted(merged.items())]
    peak = sorted_equity[0]
    max_dd = 0.0
    for eq in sorted_equity:
        if eq > peak:
            peak = eq
        dd = (peak - eq) / peak * 100 if peak > 0 else 0
        if dd > max_dd:
            max_dd = dd
    return max_dd


# ═════════════════════════════════════════════════════════════════
# 主函数
# ═════════════════════════════════════════════════════════════════

def main():
    print("=" * 70)
    print("BDSM Phase 3 A/B 回测 — spec §5.3")
    print(f"回测窗口: {BACKTEST_DAYS} 日 | MA周期: {MA_LONG} | 币种: {sorted(BDSM_COINS)}")
    print("MDD算法: 日级mark-to-market权益曲线 (v2修正)")
    print("BDS数据: 今日快照代理值或历史均值(≥7日自动切换)")
    print("加仓检查: §3.5 九条前置检查 (P1-2)")
    print("=" * 70)

    # 1. 加载 BDS Score
    bds_scores = load_bds_scores()
    # P2: 尝试加载历史 BDS 数据（≥7日时用历史均值替代今日代理值）
    historical_bds = load_historical_bds_scores()
    bds_source = "今日快照代理值"
    if historical_bds:
        total_hist_days = max(len(v) for v in historical_bds.values()) if historical_bds else 0
        if total_hist_days >= 7:
            bds_source = f"历史{total_hist_days}日均值"
        else:
            bds_source = f"历史{total_hist_days}日(不足7日,仍用代理)"
    
    print(f"\nBDS Score ({bds_source} — 基本面日变化极小):")
    for coin in sorted(BDSM_COINS):
        bds = get_bds_for_backtest(historical_bds, bds_scores, coin)
        bds_scores[coin] = bds  # 更新为历史均值（如有）
        print(f"  {coin}: {bds:.4f}")

    # 2. 获取 K 线 + 模拟 A/B
    results_a = {}
    results_b = {}
    all_klines = {}

    print(f"\n获取 K 线 + 模拟交易:")
    for coin in sorted(BDSM_COINS):
        klines = fetch_klines(coin)
        all_klines[coin] = klines
        if len(klines) < MA_LONG + BACKTEST_DAYS:
            print(f"  {coin}: K线不足 ({len(klines)}/{MA_LONG + BACKTEST_DAYS})，跳过")
            continue

        bds = bds_scores.get(coin, 0.0)
        ra = simulate_group_a(klines, bds)
        rb = simulate_group_b(klines, bds)
        results_a[coin] = ra
        results_b[coin] = rb

        print(f"  {coin}: A组 PnL={ra['pnl_total']:+.2f}U 胜={ra['win_count']}/{ra['trade_count']} | "
              f"B组 PnL={rb['pnl_total']:+.2f}U 胜={rb['win_count']}/{rb['trade_count']}")

    if not results_a:
        print("\n❌ 无可用回测数据（K线获取失败或不足）")
        return

    # 3. 汇总统计
    total_pnl_a = sum(r["pnl_total"] for r in results_a.values())
    total_pnl_b = sum(r["pnl_total"] for r in results_b.values())
    total_wins_a = sum(r["win_count"] for r in results_a.values())
    total_trades_a = sum(r["trade_count"] for r in results_a.values())

    # Fix-II(2026-09-03): 胜率口径修正
    #   B组：reduce 不计入分母，仅统计 exit/window_end 等完整交易
    #   阈值：价值投资胜率 ≥ 70%（原 90% 适配 BCRM 全进全出）
    total_wins_b = 0
    total_trades_b = 0
    all_trades_b = []
    for coin in results_b:
        for t in results_b[coin].get("trades", []):
            all_trades_b.append(t)
            reason = str(t.get("reason", ""))
            pnl = float(t.get("pnl_usdt", 0.0))
            # 区分：reason == "window_end" → 完整交易（计入）
            #      reason 以 "trend_value_full_exit" → 完整交易（计入）
            #      reason 以 "trend_value_reduce" → 战术性减仓（不计入分母）
            is_reduce = ("reduce" in reason and "full_exit" not in reason)
            if is_reduce:
                continue  # 战术性减仓 → 不计入分母
            total_trades_b += 1
            if pnl > 0:
                total_wins_b += 1
    # 兜底（若无法识别则退化到旧口径）
    if total_trades_b == 0:
        for coin in results_b:
            total_wins_b += results_b[coin]["win_count"]
            total_trades_b += results_b[coin]["trade_count"]

    # MDD（日级 mark-to-market 权益曲线 — 修正旧版 per-trade 累加低估问题）
    daily_eq_a = [results_a[coin].get("daily_equity", []) for coin in results_a]
    daily_eq_b = [results_b[coin].get("daily_equity", []) for coin in results_b]
    mdd_a = compute_mdd_daily(daily_eq_a)
    mdd_b = compute_mdd_daily(daily_eq_b)

    # 反向丢弃率：BDS < 0.3 跳过的比例
    skip_count = sum(1 for coin in results_a
                     if results_a[coin].get("skip_reason") == "bds_below_0.3")
    reverse_drop_rate = skip_count / len(BDSM_COINS) * 100 if BDSM_COINS else 0

    # 胜率
    win_rate_a = total_wins_a / total_trades_a * 100 if total_trades_a > 0 else 0
    win_rate_b = total_wins_b / total_trades_b * 100 if total_trades_b > 0 else 0

    # MDD 比率（B/A）
    mdd_ratio = mdd_b / mdd_a * 100 if mdd_a > 0 else 0

    # 可建仓币数（BDS ≥ 0.3）
    tradeable_count = sum(1 for coin in results_a
                          if not results_a[coin].get("skip_reason"))

    print("\n" + "=" * 70)
    print("回测汇总")
    print("=" * 70)
    print(f"{'指标':<25} {'A组(原BCRM)':>15} {'B组(CVS+价值)':>15} {'验收标准':>15} {'结论':>8}")
    print("-" * 70)
    print(f"{'总PnL (U)':<25} {total_pnl_a:>+15.2f} {total_pnl_b:>+15.2f} {'B>A':>15} "
          f"{'✅' if total_pnl_b > total_pnl_a else '⚠️':>8}")
    print(f"{'胜率(参考)':<25} {win_rate_a:>14.1f}% {win_rate_b:>14.1f}% {'—':>15} {'—':>8}")
    print(f"{'MDD':<25} {mdd_a:>14.1f}% {mdd_b:>14.1f}% {'—':>15} {'—':>8}")
    print(f"{'MDD比率(B/A)':<25} {'—':>15} {mdd_ratio:>14.1f}% {'≤120%':>15} "
          f"{'✅' if mdd_ratio <= 120 else '⚠️':>8}")
    print(f"{'可建仓币数':<25} {'—':>15} {tradeable_count:>15} {'≥3':>15} "
          f"{'✅' if tradeable_count >= 3 else '⚠️':>8}")
    print(f"{'反向丢弃率(参考)':<25} {'—':>15} {reverse_drop_rate:>14.1f}% {'—':>15} {'—':>8}")
    print(f"{'总交易数':<25} {total_trades_a:>15} {total_trades_b:>15} {'—':>15} {'—':>8}")

    # 验收结论（v2 门槛 2026-09-03：PnL+MDD双门槛，用户确认方案A）
    all_pass = (total_pnl_b > total_pnl_a and mdd_ratio <= 120 and tradeable_count >= 3)
    print("\n" + "=" * 70)
    if all_pass:
        print("✅ Phase 3 验收通过 — 三项标准全部达标")
        print("   建议: enable_bdsm_value_scaling = True")
    else:
        print("⚠️ Phase 3 验收未完全通过 — 部分指标未达标")
        if total_pnl_b <= total_pnl_a:
            print(f"   - B组PnL {total_pnl_b:.2f} ≤ A组PnL {total_pnl_a:.2f}")
        if mdd_ratio > 120:
            print(f"   - MDD比率 {mdd_ratio:.1f}% > 120%")
        if tradeable_count < 3:
            print(f"   - 可建仓币数 {tradeable_count} < 3")
    print("=" * 70)

    # 保存详细结果
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "backtest_days": BACKTEST_DAYS,
        "ma_long": MA_LONG,
        "coins": sorted(BDSM_COINS),
        "bds_scores": bds_scores,
        "bds_data_note": "今日快照代理值 — data_center.db 无历史时序 BDS 数据；TS 技术面已日级动态",
        "mdd_algorithm": "日级 mark-to-market 权益曲线 (v2 修正 2026-09-03)",
        "group_a": {
            "total_pnl": total_pnl_a,
            "win_rate": win_rate_a,
            "mdd": mdd_a,
            "trades": total_trades_a,
            "per_coin": {k: {"pnl": v["pnl_total"], "wins": v["win_count"],
                             "trades": v["trade_count"]} for k, v in results_a.items()},
        },
        "group_b": {
            "total_pnl": total_pnl_b,
            "win_rate": win_rate_b,
            "mdd": mdd_b,
            "mdd_ratio": mdd_ratio,
            "reverse_drop_rate": reverse_drop_rate,
            "tradeable_count": tradeable_count,
            "trades": total_trades_b,
            "per_coin": {k: {"pnl": v["pnl_total"], "wins": v["win_count"],
                             "trades": v["trade_count"]} for k, v in results_b.items()},
        },
        "verdict": "PASS" if all_pass else "FAIL",
        "threshold_version": "v2 (2026-09-03): PnL B>A + MDD ratio ≤120% + tradeable ≥3",
    }
    report_path = _THIS_DIR / "bdsm_phase3_backtest_report.json"
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    print(f"\n详细报告: {report_path}")


if __name__ == "__main__":
    main()
