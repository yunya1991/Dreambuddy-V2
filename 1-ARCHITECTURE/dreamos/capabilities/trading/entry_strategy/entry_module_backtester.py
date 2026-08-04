#!/usr/bin/env python3
"""
入场模块回测评估器 (Entry Module Backtester)
============================================

对每个场景 × 每个可用入场模块运行回测，
对比 6 个入场模块（a2_fusion / c2_momentum / s3_trend / yj_infer / martin_v15 / scenario_ema）
在相同未来 20 根 K 线、相同离场策略（builtin ATR 时间衰减）下的表现，
将结果写入 EntryPerformanceMemory 供 EntryModuleSelector 选优。

为什么出场统一用 builtin ATR 时间衰减？
    → 出场在 DreamOS 中已通过 ExitModuleSelector 独立择优；
      本回测器目的是**仅评估入场模块本身**，避免出场差异污染入场模块打分。

入场模块（全是 DreamOS 已实现节点，不自创信号）：
    scenario_ema   — 基线: 36 场景分类 + EMA20/50 交叉 + RSI 过滤（ScenarioEmaAdapter）
    a2_fusion      — A2 综合分析节点: 技术 30% + 子系统 25% + 基本面 20% + 研究 15% + 情绪 10%
    c2_momentum    — C2 动量节点（RSI/MACD/24h涨跌）
    s3_trend       — C_S3_TREND 三屏趋势节点（周/日/H1 多周期共振）
    yj_infer       — A_YJ_INFER 易经卦象推理节点
    martin_v15     — C_MARTIN_V15 V15 马丁信号节点

与离场回测器的一致：
    - 数据加载: 复用 ScenarioBacktester data_dir
    - 场景分类: 复用 ScenarioClassifier（36 场景）
    - 指标计算: 复用 _calc_metrics + 归一化 + 相同打分公式 Score=Sharpe×0.4 + Return×0.3 + (1-MaxDD)×0.2 + WinRate×0.1
    - 离场评估: 统一用 auto_trader 内置 check_exit 的时间衰减 ATR（避免出场差异污染入场打分）

v1.0（2026-08-02）
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import os
import sys
import time
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("entry_module_backtester")

# ============================================================
# 常量（与 exit_module_backtester 对齐）
# ============================================================
WINDOW_SIZE = 48               # 场景分类窗口（48 根 1h K线）
STEP = 4                       # 滑动步长
HOLD_PERIODS = 20              # 最多持仓 20 根 bar（5 次检查 × 4 step）
FEE_RATE = 0.0004              # 单边手续费 0.04%
CONFIDENCE_THRESHOLD = 0.62    # 入场置信度阈值（与实盘 auto_trader 对称门槛=0.62 对齐，过滤 C2 动量的低置信噪声）
# 调参依据（BTC+ETH+SOL 1h v1.0）：
#   0.55 →  C2 动量 7449 笔（对每条K线都输出方向，WR 49.0%，AvgPnL +0.066%）假阳性太多
#   0.62 →  与 run_auto_trade 的对称门槛一致，c2/a2/s3/yj 各模块独立评估后才入场
DEFAULT_BACKTEST_LEVERAGE = 5.0  # 与 exit 回测器对齐（非简单累加统计）


# ============================================================
# Exit 统一（评估入场本身，所以用内置 ATR 时间衰减，避免出场差异污染）
# ============================================================
def _builtin_check_exit(entry_price, current_price, direction, atr_pct, bars_held, scenario_id):
    """完全对齐 auto_trader.py check_exit 的 fallback 路径（内置 ATR 时间衰减）"""
    if bars_held <= 20:
        time_factor = 1.5
    elif bars_held <= 50:
        time_factor = 1.5 - (bars_held - 20) * (0.5 / 30)
    else:
        time_factor = 1.0
    regime = "ranging" if ("RANGE" in scenario_id or "LOW" in scenario_id or "CHOP" in scenario_id) else (
        "trend_bull" if direction == "LONG" else "trend_bear"
    )
    regime_factor = 1.5 if regime == "ranging" else 1.0
    symbol_vol_factor = 1.0
    sl_factor = time_factor * regime_factor * symbol_vol_factor
    sl_pct = atr_pct * 1.0 * sl_factor
    tp_pct = atr_pct * 2.0
    if direction == "LONG":
        stop_loss = entry_price * (1 - sl_pct)
        take_profit = entry_price * (1 + tp_pct)
        if bars_held > 20:
            pnl_pct = (current_price - entry_price) / entry_price if entry_price else 0
            if pnl_pct > 0:
                stop_loss = max(stop_loss, entry_price * (1 + pnl_pct * 0.5))
        if current_price <= stop_loss:
            return True, "止损触发", stop_loss
        if current_price >= take_profit:
            return True, "止盈触发", take_profit
    else:
        stop_loss = entry_price * (1 + sl_pct)
        take_profit = entry_price * (1 - tp_pct)
        if bars_held > 20:
            pnl_pct = (entry_price - current_price) / entry_price if entry_price else 0
            if pnl_pct > 0:
                stop_loss = min(stop_loss, entry_price * (1 - pnl_pct * 0.5))
        if current_price >= stop_loss:
            return True, "止损触发", stop_loss
        if current_price <= take_profit:
            return True, "止盈触发", take_profit
    return False, "继续持有", 0.0


# ============================================================
# 回测器主体
# ============================================================

class EntryModuleBacktester:
    """入场模块回测评估器"""

    def __init__(
        self,
        data_dir: str = "",
        memory_path: str = "",
        intervals: Tuple[str, ...] = ("1h",),
    ):
        BASE = Path(__file__).resolve().parent.parent.parent.parent
        if not data_dir:
            data_dir = os.environ.get("DREAMOS_BACKTEST_DATA", str(BASE / "data" / "backtest_data"))
        self.data_dir = data_dir
        if not memory_path:
            memory_path = str(BASE / "core/memory/entry_performance_memory.json")
        self.memory_path = memory_path
        self.intervals = intervals
        os.makedirs(os.path.dirname(memory_path) or ".", exist_ok=True)

        self._classifier = None
        self._adapters: Dict[str, Any] = {}
        self._init_components()

    def _init_components(self):
        try:
            from dreamos.core.sense.scenario_classifier import ScenarioClassifier
            self._classifier = ScenarioClassifier()
        except Exception as e:
            logger.warning(f"场景分类器加载失败: {e}")
            self._classifier = None
        # 入场模块适配器
        try:
            from dreamos.capabilities.trading.entry_strategy.entry_module_adapter import (
                get_all_entry_modules, create_entry_adapter,
            )
            for name in get_all_entry_modules():
                ad = create_entry_adapter(name)
                if ad is not None:
                    self._adapters[name] = ad
        except Exception as e:
            logger.warning(f"入场适配器初始化失败: {e}")
        if not self._adapters:
            logger.warning("无可用入场适配器（至少应有 scenario_ema）")

    # ------------------------------------------------------------------
    # 数据加载（与 exit_module_backtester 完全对齐）
    # ------------------------------------------------------------------
    def _load_klines(self, symbol: str, interval: str, limit: int = 0) -> List[tuple]:
        """加载 K 线: 返回 [(t,o,h,l,c,v), ...] 按升序"""
        paths = [
            Path(self.data_dir) / f"{symbol}_{interval}.json",
            Path(self.data_dir) / f"klines_{symbol}_{interval}.json",
            Path(__file__).resolve().parent.parent.parent.parent / "data" / "backtest_data" / f"{symbol}_{interval}.json",
        ]
        data = None
        for p in paths:
            if p.exists():
                try:
                    with open(p, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    break
                except Exception as e:
                    logger.debug(f"读取 {p} 失败: {e}")
        if data is None:
            logger.warning(f"无 {symbol} {interval} K线数据，生成随机占位 K线（仅回测结构用）")
            import random
            random.seed(hash(f"{symbol}_{interval}") & 0xffff)
            price = {"BTC": 60000, "ETH": 3000, "SOL": 150}.get(symbol, 100)
            data = []
            t = int(time.time()) - 10000 * 3600
            for i in range(10000):
                o = price
                c = o * (1 + random.gauss(0, 0.005))
                h = max(o, c) * (1 + abs(random.gauss(0, 0.004)))
                l = min(o, c) * (1 - abs(random.gauss(0, 0.004)))
                v = random.uniform(100, 10000)
                data.append({"timestamp": t + i * 3600, "open": o, "high": h, "low": l, "close": c, "volume": v})
                price = c
        rows = []
        for d in data:
            if isinstance(d, dict):
                t = int(d.get("timestamp") or d.get("time") or d.get("t") or 0)
                o = float(d.get("open") or d.get("o") or 0)
                h = float(d.get("high") or d.get("h") or 0)
                l = float(d.get("low") or d.get("l") or 0)
                c = float(d.get("close") or d.get("c") or 0)
                v = float(d.get("volume") or d.get("v") or 0)
            elif isinstance(d, (list, tuple)) and len(d) >= 6:
                t, o, h, l, c, v = d[0], d[1], d[2], d[3], d[4], d[5]
                t, o, h, l, c, v = int(t), float(o), float(h), float(l), float(c), float(v)
            else:
                continue
            if o <= 0 or c <= 0 or h <= 0 or l <= 0:
                continue
            rows.append((t, o, h, l, c, v))
        rows.sort(key=lambda x: x[0])
        if limit and len(rows) > limit:
            rows = rows[-limit:]
        return rows

    def _classify_scenario(self, window: List[tuple]) -> str:
        """从 window K 行构造 market_data dict 后调用 ScenarioClassifier.classify（要求含 price/ema20/ema50/change_*）"""
        closes = [k[4] for k in window]
        if len(closes) < 25:
            return "NEUTRAL_NORMAL_ACCELERATING"
        # 构造与 auto_trader._fetch_market_data 对齐的 market_data 字段
        def ema(vals, n):
            if len(vals) < n:
                return vals[-1] if vals else 0
            k = 2 / (n + 1)
            e = vals[-n]
            for v in vals[-n + 1:]:
                e = v * k + e * (1 - k)
            return e
        price = closes[-1]
        ema20 = ema(closes, 20)
        ema50 = ema(closes, 50)
        ema200 = ema(closes, min(200, len(closes)))
        change_1h = (closes[-1] - closes[-2]) / closes[-2] if closes[-2] > 0 else 0
        change_4h = (closes[-1] - closes[-5]) / closes[-5] if len(closes) >= 5 and closes[-5] > 0 else 0
        change_24h = (closes[-1] - closes[-25]) / closes[-25] if len(closes) >= 25 and closes[-25] > 0 else 0
        highs = [k[2] for k in window]; lows = [k[3] for k in window]
        atr_pct_v = self._atr_pct(highs, lows, closes, 14)
        market_data = {
            "price": price, "ema20": ema20, "ema50": ema50, "ema200": ema200,
            "change_1h": change_1h, "change_4h": change_4h, "change_24h": change_24h,
            "atr_pct": atr_pct_v,
        }
        if self._classifier is not None:
            try:
                result = self._classifier.classify(market_data)
                sid = getattr(result, "scenario_id", "")
                if sid:
                    return sid
            except Exception:
                pass
        return "NEUTRAL_NORMAL_ACCELERATING"

    def _atr_pct(self, highs: List[float], lows: List[float], closes: List[float], period: int = 14) -> float:
        if len(closes) < period + 1:
            return 0.02
        trs = []
        for i in range(1, len(closes)):
            tr = max(highs[i] - lows[i], abs(highs[i] - closes[i-1]), abs(lows[i] - closes[i-1]))
            trs.append(tr)
        if not trs:
            return 0.02
        atr = sum(trs[-period:]) / min(period, len(trs))
        return atr / closes[-1] if closes[-1] > 0 else 0.02

    def _build_market_data(self, symbol, window, atr_pct_v):
        closes = [k[4] for k in window]
        if len(closes) < 50:
            return {"price": closes[-1], "atr_pct": atr_pct_v, "rsi14": 50.0}
        # 计算 C链常用特征（与 a2_fusion/c2_momentum 消费的字段对齐）
        changes_1h = (closes[-1] - closes[-2]) / closes[-2] * 100 if closes[-2] > 0 else 0
        changes_4h = (closes[-1] - closes[-5]) / closes[-5] * 100 if len(closes) >= 5 and closes[-5] > 0 else 0
        changes_24h = (closes[-1] - closes[-25]) / closes[-25] * 100 if len(closes) >= 25 and closes[-25] > 0 else 0
        # RSI 14
        gains, losses = 0.0, 0.0
        for i in range(1, 15):
            diff = closes[-i] - closes[-i-1]
            if diff >= 0: gains += diff
            else: losses -= diff
        if gains == 0 and losses == 0: rsi = 50.0
        elif losses == 0: rsi = 100.0
        elif gains == 0: rsi = 0.0
        else:
            rs = (gains / 14) / (losses / 14)
            rsi = 100 - 100 / (1 + rs)
        # MACD 粗略（12,26,9 EMA）
        def ema(arr, p):
            k = 2 / (p + 1)
            e = [arr[0]]
            for x in arr[1:]: e.append(x * k + e[-1] * (1 - k))
            return e
        ema12 = ema(closes, 12); ema26 = ema(closes, 26)
        dif = [a - b for a, b in zip(ema12, ema26)]
        dea = ema(dif, 9)
        macd_hist = (dif[-1] - dea[-1]) * 2
        return {
            "symbol": symbol, "price": closes[-1], "atr_pct": atr_pct_v, "rsi14": rsi,
            "change_1h": changes_1h, "change_4h": changes_4h, "change_24h": changes_24h,
            "macd": dif[-1], "macd_signal": dea[-1], "macd_hist": macd_hist,
            "closes": closes[-50:],
        }

    # ------------------------------------------------------------------
    # 模拟单笔（某入场模块决定入场后，统一用 builtin ATR 出场）
    # ------------------------------------------------------------------
    def _simulate_entry_module(
        self,
        module_name: str,
        adapter: Any,
        symbol: str,
        scenario_id: str,
        window: List[tuple],
        future: List[tuple],
        atr_pct_v: float,
        confidence_threshold: float,
    ) -> Dict[str, Any]:
        """返回 {pnl, entry_triggered, direction, confidence, exit_reason, exit_bar, entry_price, exit_price}"""
        md = self._build_market_data(symbol, window, atr_pct_v)
        try:
            decision = adapter.evaluate(symbol, scenario_id, window, md, {})
        except Exception as e:
            return {
                "pnl": 0.0, "entry_triggered": False, "direction": "HOLD",
                "confidence": 0.0, "exit_reason": f"adapter_error:{e}",
                "exit_bar": 0, "entry_price": 0, "exit_price": 0,
            }
        direction = (decision.direction or "HOLD").upper()
        conf = float(decision.confidence or 0.0)
        if direction not in ("LONG", "SHORT") or conf < confidence_threshold:
            return {
                "pnl": 0.0, "entry_triggered": False, "direction": direction,
                "confidence": conf, "exit_reason": f"未入场(dir={direction},conf={conf:.2f}<{confidence_threshold:.2f})",
                "exit_bar": 0, "entry_price": 0, "exit_price": 0,
            }
        entry_price = window[-1][4]
        # 统一走 builtin ATR 出场
        exit_reason = "time_limit"
        exit_price = future[-1][4]
        exit_bar = len(future)
        for i, k in enumerate(future):
            cur = k[4]
            bars_held = i + 1
            triggered, reason, ep = _builtin_check_exit(entry_price, cur, direction, atr_pct_v, bars_held, scenario_id)
            if triggered:
                exit_price = ep if ep > 0 else cur
                exit_reason = reason
                exit_bar = bars_held
                break
        if direction == "LONG":
            raw_pnl = (exit_price - entry_price) / entry_price if entry_price else 0
        else:
            raw_pnl = (entry_price - exit_price) / entry_price if entry_price else 0
        pnl = raw_pnl - FEE_RATE * 2
        return {
            "pnl": pnl, "entry_triggered": True, "direction": direction,
            "confidence": conf, "exit_reason": exit_reason, "exit_bar": exit_bar,
            "entry_price": entry_price, "exit_price": exit_price,
        }

    # ------------------------------------------------------------------
    # 指标计算（与 exit_module_backtester 完全对齐）
    # ------------------------------------------------------------------
    def _calc_metrics(self, trades: List[float], exit_reasons: Dict[str, int], exit_bars: List[int]) -> Dict[str, Any]:
        n = len(trades)
        if n == 0:
            return {"sharpe": 0, "total_return": 0, "max_dd": 0, "win_rate": 0, "trades": 0,
                    "exit_reasons": exit_reasons, "avg_hold_bars": 0, "avg_pnl": 0}
        avg_pnl = sum(trades) / n
        win_rate = sum(1 for p in trades if p > 0) / n
        # 累计 equity 曲线
        eq = [1.0]
        for p in trades:
            eq.append(eq[-1] * (1 + p))
        total_return = eq[-1] - 1.0
        peak = eq[0]
        max_dd = 0.0
        for v in eq:
            peak = max(peak, v)
            if peak > 0:
                max_dd = max(max_dd, (peak - v) / peak)
        # 夏普（用 bar-to-bar equity 收益率 std，bar=1 trade）
        rets = [(eq[i] - eq[i-1]) / max(1e-12, eq[i-1]) for i in range(1, len(eq))]
        if len(rets) < 2 or (sum((r - avg_pnl) ** 2 for r in rets) / (len(rets) - 1)) <= 0:
            sharpe = 0.0
        else:
            var = sum((r - avg_pnl) ** 2 for r in rets) / (len(rets) - 1)
            if var > 0:
                sharpe = avg_pnl / math.sqrt(var) * math.sqrt(252 * 4) if avg_pnl >= 0 else 0.0
            else:
                sharpe = 0.0
        avg_hold = (sum(exit_bars) / len(exit_bars)) if exit_bars else 0
        return {
            "sharpe": round(sharpe, 4),
            "total_return": round(total_return, 6),
            "max_dd": round(max_dd, 6),
            "win_rate": round(win_rate, 6),
            "trades": n,
            "exit_reasons": exit_reasons,
            "avg_hold_bars": round(avg_hold, 2),
            "avg_pnl": round(avg_pnl, 6),
        }

    # ------------------------------------------------------------------
    # 主运行
    # ------------------------------------------------------------------
    def run(
        self,
        symbols: Optional[List[str]] = None,
        interval: str = "1h",
        min_trades: int = 10,
        confidence_threshold: Optional[float] = None,
    ) -> Dict[str, Any]:
        symbols = symbols or ["BTC", "ETH", "SOL"]
        if confidence_threshold is None:
            confidence_threshold = CONFIDENCE_THRESHOLD
        # 内存汇总 {scenario_id: {module_name: {trades: [...], exit_reasons:{}, exit_bars:[]}}}
        memory_tmp: Dict[str, Dict[str, Dict[str, Any]]] = {}
        all_bar_count = 0

        for symbol in symbols:
            logger.info(f"加载 {symbol} {interval} K线...")
            klines = self._load_klines(symbol, interval)
            logger.info(f"  {symbol} {interval} {len(klines)} 根")
            all_bar_count += max(0, (len(klines) - WINDOW_SIZE - HOLD_PERIODS) // STEP)

            for start in range(0, len(klines) - WINDOW_SIZE - HOLD_PERIODS, STEP):
                window = klines[start:start + WINDOW_SIZE]
                future = klines[start + WINDOW_SIZE:start + WINDOW_SIZE + HOLD_PERIODS]
                if len(future) < HOLD_PERIODS:
                    continue
                sid = self._classify_scenario(window)
                closes = [k[4] for k in window]
                highs = [k[2] for k in window]
                lows = [k[3] for k in window]
                atr_pct_v = self._atr_pct(highs, lows, closes, 14)

                if sid not in memory_tmp:
                    memory_tmp[sid] = {m: {"trades": [], "exit_reasons": {}, "exit_bars": [], "skipped": 0}
                                       for m in self._adapters.keys()}

                for mod_name, adapter in self._adapters.items():
                    sim = self._simulate_entry_module(
                        mod_name, adapter, symbol, sid, window, future, atr_pct_v, confidence_threshold,
                    )
                    rec = memory_tmp[sid][mod_name]
                    if not sim.get("entry_triggered"):
                        rec["skipped"] = rec.get("skipped", 0) + 1
                        continue
                    rec["trades"].append(sim["pnl"])
                    r = sim.get("exit_reason", "")
                    key = "time_limit" if "time" in r.lower() or r == "time_limit" else r
                    rec["exit_reasons"][key] = rec["exit_reasons"].get(key, 0) + 1
                    rec["exit_bars"].append(sim.get("exit_bar") or 0)

        # 汇总为 EntryPerformanceMemory 结构并写盘
        result: Dict[str, Any] = {}
        scenario_totals = {
            m: {"trades": [], "exit_reasons": {}, "exit_bars": []} for m in self._adapters.keys()
        }
        for sid, modules in memory_tmp.items():
            result[sid] = {}
            for mod_name, rec in modules.items():
                trades_list = rec["trades"]
                if len(trades_list) < min_trades:
                    continue
                metrics = self._calc_metrics(trades_list, rec["exit_reasons"], rec["exit_bars"])
                result[sid][mod_name] = metrics
                # 汇总全量 total（跨所有场景）
                scenario_totals[mod_name]["trades"].extend(trades_list)
                for k, v in rec["exit_reasons"].items():
                    scenario_totals[mod_name]["exit_reasons"][k] = scenario_totals[mod_name]["exit_reasons"].get(k, 0) + v
                scenario_totals[mod_name]["exit_bars"].extend(rec["exit_bars"])

        # 跨所有场景聚合 TOTAL（每个模块单独一行）
        total_per_module = {}
        for mod_name, rec in scenario_totals.items():
            if len(rec["trades"]) >= min_trades:
                total_per_module[mod_name] = self._calc_metrics(rec["trades"], rec["exit_reasons"], rec["exit_bars"])
        if total_per_module:
            result["_TOTAL_"] = total_per_module

        # 打分
        scored = self._add_scores(result)

        with open(self.memory_path, "w", encoding="utf-8") as f:
            json.dump(scored, f, ensure_ascii=False, indent=2)
        logger.info(f"EntryPerformanceMemory 已写入: {self.memory_path}")

        # 打印摘要
        print(f"\n===== 入场模块回测摘要（CONFIDENCE_THRESHOLD={confidence_threshold}，出场统一builtin ATR）=====")
        print(f"{'模块':15s} {'N':>6s} {'胜率':>7s} {'平均PnL':>9s} {'Return':>8s} {'MaxDD':>7s} {'Sharpe':>7s} {'Score':>6s}")
        print("-" * 78)
        totals = scored.get("_TOTAL_", {})
        for mod in sorted(totals.keys(), key=lambda m: -totals[m].get("score", 0)):
            m = totals[mod]
            print(f"{mod:15s} {m['trades']:6d} {m['win_rate']:6.1%} {m['avg_pnl']:+8.4%} {m['total_return']:+7.4f} {m['max_dd']:6.2%} {m['sharpe']:7.3f} {m.get('score', 0):5.3f}")
        return scored

    def _add_scores(self, result: Dict[str, Any]) -> Dict[str, Any]:
        """每个场景下对各模块打分；返回结构写入 memory"""
        for sid, modules in result.items():
            if sid == "_TOTAL_":
                continue
            valid = {m: r for m, r in modules.items() if int(r.get("trades") or 0) > 0}
            if not valid:
                continue
            sharpe_vals = [r["sharpe"] for r in valid.values()]
            ret_vals = [r["total_return"] for r in valid.values()]
            dd_vals = [r["max_dd"] for r in valid.values()]
            wr_vals = [r["win_rate"] for r in valid.values()]
            def _norm(vals, higher):
                mn, mx = min(vals), max(vals)
                if abs(mx - mn) < 1e-9: return {v: 0.5 for v in vals}
                if higher: return {v: (v - mn)/(mx - mn) for v in vals}
                return {v: (mx - v)/(mx - mn) for v in vals}
            s_norm = _norm(sharpe_vals, True)
            r_norm = _norm(ret_vals, True)
            d_norm = _norm(dd_vals, False)
            w_norm = _norm(wr_vals, True)
            for m, r in valid.items():
                score = round(
                    s_norm[r["sharpe"]] * 0.4 + r_norm[r["total_return"]] * 0.3
                    + d_norm[r["max_dd"]] * 0.2 + w_norm[r["win_rate"]] * 0.1, 4
                )
                result[sid][m]["score"] = score
        # TOTAL 也打一次分（内部归一化）
        if "_TOTAL_" in result:
            t = result["_TOTAL_"]
            mods = list(t.keys())
            if mods:
                vals = {"sharpe": [], "total_return": [], "max_dd": [], "win_rate": []}
                for m in mods:
                    for k in vals: vals[k].append(t[m][k])
                norms = {}
                for k in vals:
                    higher = (k != "max_dd")
                    mn, mx = min(vals[k]), max(vals[k])
                    if abs(mx - mn) < 1e-9:
                        norms[k] = {v: 0.5 for v in vals[k]}
                    elif higher:
                        norms[k] = {v: (v - mn)/(mx - mn) for v in vals[k]}
                    else:
                        norms[k] = {v: (mx - v)/(mx - mn) for v in vals[k]}
                for m in mods:
                    r = t[m]
                    score = round(
                        norms["sharpe"][r["sharpe"]] * 0.4 + norms["total_return"][r["total_return"]] * 0.3
                        + norms["max_dd"][r["max_dd"]] * 0.2 + norms["win_rate"][r["win_rate"]] * 0.1, 4
                    )
                    result["_TOTAL_"][m]["score"] = score
        return result


def main():
    parser = argparse.ArgumentParser(description="入场模块回测评估器")
    parser.add_argument("--symbols", default=os.environ.get("DREAMOS_SYMBOLS", "BTC,ETH,SOL"), help="逗号分隔的币对")
    parser.add_argument("--interval", default="1h", help="K线周期")
    parser.add_argument("--min-trades", type=int, default=10, help="每个场景×模块最少交易笔数才写盘")
    parser.add_argument("--confidence-threshold", type=float, default=None, help=f"入场置信度阈值(默认 {CONFIDENCE_THRESHOLD})")
    args = parser.parse_args()

    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    bt = EntryModuleBacktester()
    bt.run(symbols=symbols, interval=args.interval, min_trades=args.min_trades,
           confidence_threshold=args.confidence_threshold)


if __name__ == "__main__":
    main()
