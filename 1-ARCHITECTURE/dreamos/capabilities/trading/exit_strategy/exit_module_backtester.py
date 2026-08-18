#!/usr/bin/env python3
"""
离场模块回测器 (Exit Module Backtester)
======================================

对每个场景 × 每个可用离场模块运行回测，
对比 classic / simple / yijing 在相同开仓点下的表现，
将结果写入 ExitPerformanceMemory 供 ExitModuleSelector 选优。

架构复用:
    - 数据加载: 复用 ScenarioBacktester 的数据目录结构
    - 场景分类: 复用 ScenarioClassifier (36 场景)
    - 指标计算: 复用 ScenarioBacktester 的 _calc_metrics + 归一化
    - 离场模拟: 调用 ExitModuleAdapter 的 evaluate 方法

离场模块对比逻辑:
    1. 滑动窗口遍历 K 线
    2. 场景分类 + EMA 交叉决定开仓方向
    3. 对每个离场模块独立模拟持仓期间的离场决策
    4. 统计 sharpe/return/max_dd/win_rate → 写入 ExitPerformanceMemory

回测参数:
    - WINDOW_SIZE=48: 场景分类窗口（48 根 1h K线）
    - STEP=4: 滑动步长
    - HOLD_PERIODS=20: 最大持仓 K 线数
    - DEFAULT_BACKTEST_LEVERAGE=5.0: 回测默认杠杆（与实盘 DEFAULT_LEVERAGE 对齐）

v2.1 修复（2026-08-01）:
    - Bug1: Yijing 1h 缓存门禁导致回测 0% 触发率
      根因: YijingExitSystem 的缓存用墙钟 time.time()，回测时所有 bar 在几秒内跑完
      → 缓存命中 → 全部返回 no_intervene → HOLD
      修复: 每笔交易前清全局缓存 + 每个 bar 评估前清 coin:pos_side 级缓存
    - Bug2: leverage 硬编码 1.0 → pnl_eff 过小 → P0/P1/P2 阈值无法触发
      修复: 改用 DEFAULT_BACKTEST_LEVERAGE=5.0
    - Bug3: trailing_armed/trailing_stop_price 不传 → 跟踪止损跨 bar 状态丢失
      修复: 在 _simulate_exit_module 中维护 trailing 状态，每次 evaluate 后回写
    - Bug4: mfe_pnl_pct/max_dd_pct 用瞬时 PnL 而非累计峰值/谷值
      修复: 按 peak_price/trough_price 累计计算
    - Bug5: exit_reasons 用 action.lower() 分类 → time_limit 也被记为 "close"
      修复: 改用 reason 前缀分类（time_limit/close_stoploss/close_takeprofit/close_trailing/reduce）

使用:
    cd 1-ARCHITECTURE
    python -m dreamos.capabilities.trading.exit_strategy.exit_module_backtester
    # 或指定参数
    python -m dreamos.capabilities.trading.exit_strategy.exit_module_backtester --symbols BTC,ETH,SOL --interval 1h
"""

from __future__ import annotations

import os
import sys
import json
import math
import time
import logging
import argparse
from typing import Any, Dict, List, Optional, Tuple
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

# 回测参数（WINDOW/STEP/HOLD/FEE 与 DreamOSBacktester 对齐；CONFIDENCE_THRESHOLD 不同，见下注释）
WINDOW_SIZE = 48       # 场景分类窗口（48 根 1h K线）
STEP = 4               # 滑动步长
HOLD_PERIODS = 20      # 最大持仓 K 线数
FEE_RATE = 0.0008      # 手续费率（单边）
CONFIDENCE_THRESHOLD = 0.55  # 开仓置信度阈值（上调 0.40 → 0.55）
# 调参依据（BTC+ETH 1h 2160K 回测 v2.5）：
#   0.40 → N=801, WR=40.9%, AvgPnL=-0.044%, PnL和=-35.2%
#   0.55 → N=374, WR=42.5%, AvgPnL=+0.051%, PnL和=+19.2%
# 原理: 置信度由 EMA spread × 20 + ATR% × 5 组成，spread≥0.75% 才触发 → 过滤震荡市 EMA20/50 交织的假交叉
# 注意: 这是"开仓触发 → 才有后续离场评估"的前置过滤，不影响实盘 A0-A9 开仓链路的独立信号
# 阈值差异说明（避免误判为不一致 bug）：
#   - DreamOSBacktester 用 0.4：confidence 来自 TradingAgent A链真实输出（与实盘 auto_trader 0.4 对齐）
#   - 本回测器用 0.55：confidence 来自简化 EMA 交叉公式，0.55 是回测调优值（0.40 收益为负）
#   - EntryModuleBacktester 用 0.62：与实盘对称门槛对齐
#   三者 confidence 计算方式不同，阈值本应不同，不可强行统一
PERIODS_PER_YEAR = 8760      # 1h K线年化
DEFAULT_BACKTEST_LEVERAGE = 5.0  # 回测默认杠杆（与实盘 auto_trader DEFAULT_LEVERAGE 接近）


class ExitModuleBacktester:
    """离场模块对比回测器

    对比 classic / simple 离场模块在各场景下的表现，
    结果写入 ExitPerformanceMemory。
    """

    def __init__(self, data_dir: Optional[str] = None):
        if data_dir is None:
            project_root = Path(__file__).resolve()
            for _ in range(8):
                if (project_root / "10-经典指标系统").is_dir():
                    break
                project_root = project_root.parent
            data_dir = str(project_root / "10-经典指标系统" / "user_data" / "data" / "aggregated" / "futures")
        self.data_dir = data_dir

        # 延迟加载
        self._classifier = None
        self._adapters: Dict[str, Any] = {}
        self._performance_memory = None

    # ============================================================
    # 延迟加载
    # ============================================================

    def _get_classifier(self):
        if self._classifier is None:
            from dreamos.core.sense.scenario_classifier import ScenarioClassifier
            self._classifier = ScenarioClassifier()
        return self._classifier

    def _get_adapters(self) -> Dict[str, Any]:
        if not self._adapters:
            from dreamos.capabilities.trading.exit_strategy.exit_module_adapter import get_all_adapters
            all_adapters = get_all_adapters()
            # 只保留可用模块
            self._adapters = {
                name: adapter for name, adapter in all_adapters.items()
                if adapter.is_available
            }
            logger.info(f"可用离场模块: {list(self._adapters.keys())}")
        return self._adapters

    def _get_performance_memory(self):
        if self._performance_memory is None:
            from dreamos.capabilities.trading.exit_strategy.exit_module_selector import ExitPerformanceMemory
            self._performance_memory = ExitPerformanceMemory()
        return self._performance_memory

    # ============================================================
    # 数据加载
    # ============================================================

    def _load_klines(self, symbol: str, interval: str = "1h") -> List[List]:
        """加载 K 线数据

        格式: [[ts, open, high, low, close, volume], ...]
        """
        filename = f"{symbol}_USDT-{interval}-futures.json"
        filepath = os.path.join(self.data_dir, filename)
        if not os.path.exists(filepath):
            logger.warning(f"数据文件不存在: {filepath}")
            return []
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data
        except Exception as e:
            logger.warning(f"加载数据失败 {filepath}: {e}")
            return []

    # ============================================================
    # 技术指标（复用 ScenarioBacktester 逻辑）
    # ============================================================

    def _ema(self, values: List[float], period: int) -> float:
        if not values or period <= 0:
            return values[-1] if values else 0
        period = min(period, len(values))
        k = 2 / (period + 1)
        ema = values[0]
        for v in values[1:]:
            ema = v * k + ema * (1 - k)
        return ema

    def _atr_pct(self, highs: List[float], lows: List[float], closes: List[float], period: int) -> float:
        if len(closes) < period + 1:
            period = len(closes) - 1
        if period <= 0:
            return 0.02
        trs = []
        for i in range(-period, 0):
            tr = max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1]))
            trs.append(tr)
        atr = sum(trs) / len(trs)
        price = closes[-1]
        return atr / price if price > 0 else 0.02

    def _rsi(self, closes: List[float], period: int = 14) -> float:
        if len(closes) < period + 1:
            return 50
        gains, losses = [], []
        for i in range(-period, 0):
            change = closes[i] - closes[i - 1]
            gains.append(max(change, 0))
            losses.append(max(-change, 0))
        avg_gain = sum(gains) / period
        avg_loss = sum(losses) / period
        if avg_loss == 0:
            return 100
        return 100 - (100 / (1 + avg_gain / avg_loss))

    # ============================================================
    # 场景分类
    # ============================================================

    def _classify_scenario(self, window: List[List]) -> str:
        """对窗口 K 线进行场景分类"""
        closes = [k[4] for k in window]
        highs = [k[2] for k in window]
        lows = [k[3] for k in window]

        # 字段名必须与 ScenarioClassifier.classify 期望对齐：
        # ema20/ema50/ema200（非 ema_short/ema_long）、rsi14（非 rsi）、change_1h/4h/24h
        ema20 = self._ema(closes[-20:], 20)
        ema50 = self._ema(closes[-50:], 50) if len(closes) >= 50 else self._ema(closes, len(closes))
        ema200 = self._ema(closes[-200:], 200) if len(closes) >= 200 else self._ema(closes, len(closes))
        change_1h = self._pct_change(closes, 1)
        change_4h = self._pct_change(closes, 4)
        change_24h = self._pct_change(closes, min(24, len(closes) - 1))

        market_data = {
            "closes": closes,
            "highs": highs,
            "lows": lows,
            "volumes": [k[5] for k in window],
            "price": closes[-1],
            "atr_pct": self._atr_pct(highs, lows, closes, 14),
            "ema20": ema20,
            "ema50": ema50,
            "ema200": ema200,
            "rsi14": self._rsi(closes, 14),
            "change_1h": change_1h,
            "change_4h": change_4h,
            "change_24h": change_24h,
        }

        try:
            classifier = self._get_classifier()
            result = classifier.classify(market_data)
            sid = getattr(result, "scenario_id", "")
            if sid:
                return sid
        except Exception as e:
            logger.debug(f"场景分类失败, 用简化分类: {e}")

        # 简化分类兜底
        ema_short = ema20
        ema_long = ema50
        atr_pct = market_data["atr_pct"]
        if ema_short > ema_long * 1.001:
            trend = "BULL"
        elif ema_short < ema_long * 0.999:
            trend = "BEAR"
        else:
            trend = "NEUTRAL"
        if atr_pct >= 0.04:
            vol = "EXTREME"
        elif atr_pct >= 0.02:
            vol = "HIGH"
        elif atr_pct >= 0.01:
            vol = "NORMAL"
        else:
            vol = "LOW"
        return f"{trend}_{vol}_ACCELERATING"

    def _pct_change(self, values: List[float], periods: int) -> float:
        """百分比变化（与 dreamos_backtester._pct_change 一致，返回百分数）"""
        if len(values) <= periods or periods <= 0:
            return 0.0
        old = values[-periods - 1]
        new = values[-1]
        if old == 0:
            return 0.0
        return (new - old) / old * 100

    # ============================================================
    # 开仓决策（简化：EMA 交叉 + RSI 确认）
    # ============================================================

    def _decide_entry(self, window: List[List]) -> Tuple[str, float]:
        """决定开仓方向和置信度

        Returns:
            (direction, confidence)  direction: "LONG" / "SHORT" / "HOLD"
        """
        closes = [k[4] for k in window]
        if len(closes) < 20:
            return ("HOLD", 0.0)

        ema20 = self._ema(closes[-20:], 20)
        # EMA50 在数据不足时自适应用全部数据
        ema50_period = min(50, len(closes))
        ema50 = self._ema(closes[-ema50_period:], ema50_period)
        rsi = self._rsi(closes, 14)
        atr_pct = self._atr_pct([k[2] for k in window], [k[3] for k in window], closes, 14)

        # EMA 交叉 + RSI 确认
        spread = abs(ema20 - ema50) / max(ema50, 1e-9)
        confidence = min(0.9, 0.4 + spread * 20 + (atr_pct * 5))

        if ema20 > ema50 and rsi > 45:
            return ("LONG", confidence)
        elif ema20 < ema50 and rsi < 55:
            return ("SHORT", confidence)
        return ("HOLD", confidence)

    # ============================================================
    # 离场模块模拟
    # ============================================================

    def _simulate_exit_module(
        self,
        module_name: str,
        adapter: Any,
        entry_price: float,
        direction: str,
        window: List[List],
        future_klines: List[List],
        scenario_id: str,
        atr_pct: float,
    ) -> Dict[str, Any]:
        """模拟单个离场模块在持仓期间的表现

        Returns:
            {exit_price, exit_bar, pnl, reason, action}
        """
        # Bug2 修复: 回测默认杠杆 5x，与实盘一致，确保 pnl_eff 正确影响 P0/P1/P2 阈值
        leverage = DEFAULT_BACKTEST_LEVERAGE
        entry_ts = window[-1][0]
        bars_held = 0
        exit_reason = "time_limit"
        exit_price = future_klines[-1][4]  # 默认持有到期末
        exit_bar = len(future_klines)
        action = "CLOSE"

        # Bug1 修复: Yijing 系统的 1h 缓存门禁用墙钟 time.time()，回测时必须在每笔交易前清缓存
        # 否则所有 bar 在几秒内跑完 → 缓存命中 → 全部返回 HOLD → 0% 触发率
        if hasattr(adapter, '_load_system'):
            try:
                system = adapter._load_system()
                if system is not None and hasattr(system, 'clear_cache'):
                    system.clear_cache()
            except Exception:
                pass

        # Bug3 修复: 维护 trailing 状态（跨 bar 持续累积）
        trailing_armed = False
        trailing_stop_price = 0.0
        # Bug4 修复: 维护 peak/trough 用于累计 mfe / max_dd
        peak_price = entry_price
        trough_price = entry_price
        mfe_pnl_pct = 0.0
        max_dd_pct = 0.0

        # 预计算开仓窗口 change_24h / rsi14（作为回测起点快照）
        closes_window = [k[4] for k in window]
        # 24h change ≈ 最近 24 根 1h K线的涨跌幅
        if len(closes_window) >= 25:
            change_24h = (closes_window[-1] - closes_window[-25]) / closes_window[-25]
        elif len(closes_window) >= 2:
            change_24h = (closes_window[-1] - closes_window[0]) / closes_window[0]
        else:
            change_24h = 0.0
        rsi14 = self._rsi(closes_window, 14)

        yj_system = None
        if hasattr(adapter, '_load_system'):
            try:
                yj_system = adapter._load_system()
            except Exception:
                yj_system = None
        # 缓存 key 组成: coin:pos_side，adapter 传 symbol="BACKTEST"
        yj_coin = "BACKTEST"
        yj_side = "long" if direction == "LONG" else "short"

        for i, k in enumerate(future_klines):
            # Bug1 修复增强: 每个 bar 前清 coin 级缓存，避免墙钟 time.time() < eval_interval 导致 yijing 后续 bar 全部命中缓存
            # 只影响回测；实盘 auto_trader 用真实墙钟时间，缓存是有意义的
            if yj_system is not None and hasattr(yj_system, 'clear_cache'):
                try:
                    yj_system.clear_cache(coin=yj_coin, pos_side=yj_side)
                except Exception:
                    pass

            current_price = k[4]
            bars_held = i + 1
            position_age_sec = bars_held * 3600.0

            if entry_price > 0:
                if direction == "LONG":
                    unrealized_pnl_pct = (current_price - entry_price) / entry_price
                else:
                    unrealized_pnl_pct = (entry_price - current_price) / entry_price
            else:
                unrealized_pnl_pct = 0.0

            # Bug4 修复: 累计计算 mfe_pnl_pct / max_dd_pct，而非使用瞬时 PnL
            if direction == "LONG":
                if current_price > peak_price:
                    peak_price = current_price
                    if entry_price > 0:
                        mfe_pnl_pct = max(mfe_pnl_pct, (current_price - entry_price) / entry_price)
                if entry_price > 0 and peak_price > 0:
                    dd = (peak_price - current_price) / peak_price
                    max_dd_pct = max(max_dd_pct, dd)
            else:
                if current_price < trough_price or trough_price == 0:
                    trough_price = current_price
                    if entry_price > 0:
                        mfe_pnl_pct = max(mfe_pnl_pct, (entry_price - current_price) / entry_price)
                if entry_price > 0 and trough_price > 0:
                    dd = (current_price - trough_price) / trough_price
                    max_dd_pct = max(max_dd_pct, dd)

            # 动态更新 change_24h：用窗口+未来拼接的 closes
            full_closes = closes_window + [fk[4] for fk in future_klines[:i+1]]
            if len(full_closes) >= 25:
                dyn_change_24h = (full_closes[-1] - full_closes[-25]) / full_closes[-25]
            elif len(full_closes) >= 2:
                dyn_change_24h = (full_closes[-1] - full_closes[0]) / full_closes[0]
            else:
                dyn_change_24h = change_24h
            dyn_rsi14 = self._rsi(full_closes, 14)

            # 调用离场模块评估
            try:
                decision = adapter.evaluate(
                    symbol="BACKTEST",
                    entry_price=entry_price,
                    current_price=current_price,
                    direction=direction,
                    market_data={
                        "price": current_price,
                        "atr_pct": atr_pct,
                        "change_24h": dyn_change_24h,
                        "rsi14": dyn_rsi14,
                        "candles_1h": future_klines[:i+1],
                    },
                    position_age_sec=position_age_sec,
                    unrealized_pnl_pct=unrealized_pnl_pct,
                    leverage=leverage,
                    atr_pct=atr_pct,
                    mfe_pnl_pct=mfe_pnl_pct,
                    max_dd_pct=max_dd_pct,
                    trailing_armed=trailing_armed,
                    trailing_stop_price=trailing_stop_price,
                    scenario_id=scenario_id,
                )
            except Exception as e:
                logger.debug(f"[{module_name}] evaluate 异常 bar={bars_held}: {e}")
                continue

            # Bug3 修复: 回写 trailing 状态（UnifiedExitDecision 暴露 new_trailing_armed/new_trailing_stop）
            new_armed = getattr(decision, "new_trailing_armed", None)
            new_stop = getattr(decision, "new_trailing_stop", 0.0)
            if isinstance(new_armed, bool):
                trailing_armed = new_armed
            if isinstance(new_stop, (int, float)) and new_stop > 0:
                trailing_stop_price = float(new_stop)

            # 检查是否触发离场
            if decision.action in ("CLOSE", "REDUCE"):
                exit_price = decision.exit_price if decision.exit_price > 0 else current_price
                exit_bar = bars_held
                exit_reason = decision.reason or f"{module_name}_triggered"
                action = decision.action
                break

        # 计算收益率（扣手续费）
        if direction == "LONG":
            raw_pnl = (exit_price - entry_price) / entry_price
        else:
            raw_pnl = (entry_price - exit_price) / entry_price
        pnl = raw_pnl - FEE_RATE * 2  # 开仓 + 平仓手续费

        return {
            "exit_price": exit_price,
            "exit_bar": exit_bar,
            "pnl": pnl,
            "reason": exit_reason,
            "action": action,
        }

    # ============================================================
    # 指标计算（复用 ScenarioBacktester 的归一化逻辑）
    # ============================================================

    def _calc_metrics(self, trades: List[float], exit_reasons: Dict[str, int]) -> Dict[str, Any]:
        """计算回测指标

        使用归一化评分（与 ScenarioBacktester 一致）:
            Score = norm_sharpe×0.4 + norm_return×0.3 + (1-MaxDD)×0.2 + WinRate×0.1
        """
        n = len(trades)
        if n == 0:
            return {
                "sharpe": 0, "total_return": 0, "max_drawdown": 0,
                "win_rate": 0, "total_trades": 0, "avg_pnl": 0,
                "exit_reasons": exit_reasons, "score": 0,
            }

        total_return = sum(trades)
        avg_return = total_return / n
        std_return = math.sqrt(sum((t - avg_return) ** 2 for t in trades) / n) if n > 1 else 0.001

        # 夏普年化
        sharpe = (avg_return / std_return * math.sqrt(PERIODS_PER_YEAR / HOLD_PERIODS)) if std_return > 0 else 0

        # 最大回撤
        cumulative = 0.0
        peak = 0.0
        max_dd = 0.0
        for t in trades:
            cumulative += t
            if cumulative > peak:
                peak = cumulative
            dd = peak - cumulative
            if dd > max_dd:
                max_dd = dd

        win_rate = sum(1 for t in trades if t > 0) / n

        # 归一化评分
        norm_sharpe = (min(max(sharpe, -2), 3) + 2) / 5
        norm_return = (min(max(total_return, -0.5), 1.0) + 0.5) / 1.5
        norm_dd = 1 - min(max_dd, 1)
        score = norm_sharpe * 0.4 + norm_return * 0.3 + norm_dd * 0.2 + win_rate * 0.1

        return {
            "sharpe": round(sharpe, 4),
            "total_return": round(total_return, 4),
            "max_drawdown": round(max_dd, 4),
            "win_rate": round(win_rate, 4),
            "total_trades": n,
            "avg_pnl": round(avg_return, 4),
            "exit_reasons": exit_reasons,
            "score": round(score, 4),
        }

    # ============================================================
    # 主回测入口
    # ============================================================

    def run(
        self,
        symbols: List[str] = None,
        interval: str = "1h",
        window_size: int = WINDOW_SIZE,
        step: int = STEP,
        hold_periods: int = HOLD_PERIODS,
    ) -> Dict[str, Any]:
        """运行离场模块对比回测

        Args:
            symbols: 回测币种列表
            interval: K 线周期
            window_size: 场景分类窗口
            step: 滑动步长
            hold_periods: 最大持仓 K 线数

        Returns:
            {scenario_id: {module_name: metrics}}
        """
        if symbols is None:
            symbols = ["BTC", "ETH", "SOL"]

        adapters = self._get_adapters()
        if not adapters:
            logger.error("没有可用的离场模块")
            return {}

        logger.info(f"=== 离场模块回测开始 ===")
        logger.info(f"币种: {symbols} | 周期: {interval} | 窗口: {window_size} | 步长: {step} | 持仓: {hold_periods}")
        logger.info(f"对比模块: {list(adapters.keys())}")

        # 结果收集: {scenario_id: {module_name: [trades, exit_reasons]}}
        results: Dict[str, Dict[str, Dict]] = {}

        for symbol in symbols:
            klines = self._load_klines(symbol, interval)
            if len(klines) < window_size + hold_periods:
                logger.warning(f"{symbol} 数据不足: {len(klines)} < {window_size + hold_periods}")
                continue

            logger.info(f"\n--- {symbol} ({len(klines)} 根 K线) ---")

            trade_count = 0
            for start in range(0, len(klines) - window_size - hold_periods, step):
                window = klines[start:start + window_size]
                future = klines[start + window_size:start + window_size + hold_periods]

                if len(future) < hold_periods:
                    continue

                # 场景分类
                scenario_id = self._classify_scenario(window)

                # 开仓决策
                direction, confidence = self._decide_entry(window)
                if direction == "HOLD" or confidence < CONFIDENCE_THRESHOLD:
                    continue

                entry_price = window[-1][4]
                closes = [k[4] for k in window]
                highs = [k[2] for k in window]
                lows = [k[3] for k in window]
                atr_pct = self._atr_pct(highs, lows, closes, 14)

                # 对每个离场模块独立模拟
                for mod_name, adapter in adapters.items():
                    sim = self._simulate_exit_module(
                        module_name=mod_name,
                        adapter=adapter,
                        entry_price=entry_price,
                        direction=direction,
                        window=window,
                        future_klines=future,
                        scenario_id=scenario_id,
                        atr_pct=atr_pct,
                    )

                    if scenario_id not in results:
                        results[scenario_id] = {}
                    if mod_name not in results[scenario_id]:
                        results[scenario_id][mod_name] = {"trades": [], "exit_reasons": {}}

                    results[scenario_id][mod_name]["trades"].append(sim["pnl"])
                    # Bug5 修复: 用 reason 而非 action 分类离场原因，区分模块触发 vs 超时退出
                    # _simulate_exit_module 默认 reason = "time_limit"; 模块触发时写回具体 reason
                    if sim.get("reason") and sim["reason"] != "time_limit":
                        # 按大类归集: close(模块主动平仓) / reduce(部分减仓) / tp(止盈) / sl(止损) / other
                        r_low = sim["reason"].lower()
                        if "reduce" in r_low or "减仓" in r_low:
                            reason_key = "reduce"
                        elif "stop_loss" in r_low or "sl_" in r_low or "止损" in r_low or "force_close" in r_low:
                            reason_key = "close_stoploss"
                        elif "take_profit" in r_low or "tp_" in r_low or "止盈" in r_low or "raise_tp" in r_low or "lower_tp" in r_low:
                            reason_key = "close_takeprofit"
                        elif "trailing" in r_low or "跟踪止损" in r_low:
                            reason_key = "close_trailing"
                        else:
                            reason_key = "close"
                    else:
                        reason_key = "time_limit"
                    results[scenario_id][mod_name]["exit_reasons"][reason_key] = \
                        results[scenario_id][mod_name]["exit_reasons"].get(reason_key, 0) + 1

                trade_count += 1

            logger.info(f"  {symbol}: {trade_count} 笔交易 | {len(set(s for s in [self._classify_scenario(klines[i:i+window_size]) for i in range(0, len(klines)-window_size, step)]))} 个场景")

        # 计算指标并写入 ExitPerformanceMemory
        memory = self._get_performance_memory()
        summary = {}
        for scenario_id, mod_results in results.items():
            summary[scenario_id] = {}
            for mod_name, data in mod_results.items():
                metrics = self._calc_metrics(data["trades"], data["exit_reasons"])
                summary[scenario_id][mod_name] = metrics

                # 写入持久化记忆表
                memory.update_from_backtest(
                    scenario_id=scenario_id,
                    module_name=mod_name,
                    metrics=metrics,
                )

        logger.info(f"\n=== 回测完成 ===")
        logger.info(f"覆盖场景: {len(summary)}")
        for sid, mods in sorted(summary.items()):
            best_mod = max(mods.keys(), key=lambda m: mods[m]["score"])
            best_score = mods[best_mod]["score"]
            logger.info(f"  {sid:30s} → best={best_mod:8s} (score={best_score:.4f})")

        return summary


def main():
    """CLI 入口"""
    parser = argparse.ArgumentParser(description="离场模块对比回测器")
    parser.add_argument("--symbols", default="BTC,ETH,SOL", help="回测币种 (逗号分隔)")
    parser.add_argument("--interval", default="1h", choices=["1h", "30m"], help="K 线周期")
    parser.add_argument("--window", type=int, default=WINDOW_SIZE, help="场景分类窗口")
    parser.add_argument("--step", type=int, default=STEP, help="滑动步长")
    parser.add_argument("--hold", type=int, default=HOLD_PERIODS, help="最大持仓 K 线数")
    parser.add_argument("--verbose", action="store_true", help="详细日志")
    args = parser.parse_args()

    level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    bt = ExitModuleBacktester()
    results = bt.run(
        symbols=symbols,
        interval=args.interval,
        window_size=args.window,
        step=args.step,
        hold_periods=args.hold,
    )

    # 输出摘要
    print(f"\n{'='*70}")
    print(f"离场模块回测摘要")
    print(f"{'='*70}")
    print(f"{'场景':30s} | {'模块':8s} | {'Score':>6s} | {'Sharpe':>7s} | {'Return':>8s} | {'MaxDD':>7s} | {'WinRate':>7s} | {'Trades':>6s}")
    print(f"{'-'*70}")

    for sid in sorted(results.keys()):
        for mod_name in sorted(results[sid].keys()):
            m = results[sid][mod_name]
            print(f"{sid:30s} | {mod_name:8s} | {m['score']:6.4f} | {m['sharpe']:7.2f} | {m['total_return']:8.4f} | {m['max_drawdown']:7.4f} | {m['win_rate']:7.1%} | {m['total_trades']:6d}")
        print()

    # 验证 selector 选中正确
    print(f"{'='*70}")
    print("Selector 选优验证")
    print(f"{'='*70}")
    from dreamos.capabilities.trading.exit_strategy.exit_module_selector import ExitModuleSelector
    selector = ExitModuleSelector()
    for sid in sorted(results.keys()):
        choice = selector.select(sid)
        best_mod = max(results[sid].keys(), key=lambda m: results[sid][m]["score"])
        match = "✓" if choice.module_name == best_mod else "✗"
        print(f"  {sid:30s} → selector={choice.module_name:8s} (L{choice.fallback_level}) | expected={best_mod:8s} | {match}")


if __name__ == "__main__":
    main()
