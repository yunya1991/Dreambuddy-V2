#!/usr/bin/env python3
"""
回测引擎主程序 v3.0
==============
支持分批止盈、等额加仓、固定20%止损

用法:
    python3 backtest_engine.py
    python3 backtest_engine.py --inst BTC-USDT-SWAP --from 2025-01-01 --to 2026-05-16
    python3 backtest_engine.py --capital 200
"""

import os
import sys
import json
import argparse
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Dict

SCRIPTS_DIR = Path(__file__).parent
PROJECT_DIR = SCRIPTS_DIR.parent
sys.path.insert(0, str(SCRIPTS_DIR))

from backtest_data_fetcher import (
    load_or_fetch, dt_to_ts, ts_to_dt,
    resample_to_weekly, add_technical_indicators, DATA_DIR
)
from backtest_strategy import (
    Direction, SignalStrength, StrategyType, ExitReason,
    Screen1Output, Screen2Output, Position, Trade,
    run_screen1, run_screen2, check_exit_signals,
    calc_martin_add_on, recalc_avg_entry,
    DEFAULT_STRATEGY_PARAMS,
)


# ==================== 回测配置 ====================

DEFAULT_CONFIG = {
    "inst_id": "BTC-USDT-SWAP",
    "start_date": "2025-01-01",
    "end_date": "2026-05-16",
    "initial_capital": 200.0,     # 真实账户约200U
    "maker_fee": 0.0002,
    "taker_fee": 0.0005,
    "slippage": 0.0001,
    "max_drawdown": 20.0,
    "warn_drawdown": 15.0,
    "max_position_pct": 0.20,     # 单层最大仓位
    "max_total_pct": 0.60,        # 累计最大仓位
}


# ==================== 回测引擎 ====================

class BacktestEngine:
    def __init__(self, config: dict = None, opt_params: dict = None, btc_candles: List[Dict] = None):
        self.cfg = {**DEFAULT_CONFIG, **(config or {})}
        self.opt_params = opt_params
        self._btc_candles_param = btc_candles
        self.btc_daily_candles: List[Dict] = []
        self.btc_date_idx: Dict = {}
        self.reset()

    def reset(self):
        self.equity = self.cfg["initial_capital"]
        self.peak_equity = self.cfg["initial_capital"]
        self.cash = self.cfg["initial_capital"]
        self.position = Position()
        self.trades: List[Trade] = []
        self.equity_curve: List[Dict] = []
        self.drawdown_curve: List[Dict] = []
        self.daily_candles: List[Dict] = []
        self.weekly_candles: List[Dict] = []
        self.trade_id_counter = 0
        self.screen1_cache: Dict = {}
        # 止损冷却期: 止损后N天内不开新仓
        self.last_sl_date: str = ""  # 最后一次止损日期 (YYYY-MM-DD)
        self.sl_cooldown_days: int = 0  # 冷却天数 (从opt_params读取)
        if self.opt_params and "sl_cooldown_days" in self.opt_params:
            self.sl_cooldown_days = int(self.opt_params["sl_cooldown_days"])
        self.stats = {
            "total_trades": 0,
            "win_trades": 0,
            "loss_trades": 0,
            "add_on_count": 0,
            "partial_close_count": 0,
            "forced_close_count": 0,
            "drawdown_limit_count": 0,
            "tp1_count": 0,
            "tp2_count": 0,
            "tp3_count": 0,
            "sl_cooldown_skip_count": 0,  # 被冷却期跳过的开仓次数
            "signal_trades": {s.value: 0 for s in SignalStrength},
            "signal_wins": {s.value: 0 for s in SignalStrength},
            "screen1_correct": 0,
            "screen1_total": 0,
            "martin_complete_trades": 0,
            "martin_incomplete_trades": 0,
        }

    def _next_trade_id(self) -> int:
        self.trade_id_counter += 1
        return self.trade_id_counter

    def _apply_slippage(self, price: float, direction: Direction, is_buy: bool) -> float:
        if direction == Direction.LONG:
            return price * (1 + self.cfg["slippage"]) if is_buy else price * (1 - self.cfg["slippage"])
        else:
            return price * (1 - self.cfg["slippage"]) if is_buy else price * (1 + self.cfg["slippage"])

    def _calc_fee(self, size_usd: float) -> float:
        return size_usd * self.cfg["taker_fee"]

    def _current_equity(self, price: float) -> float:
        if self.position.direction == Direction.WAIT:
            return self.cash
        if self.position.direction == Direction.LONG:
            unrealized = (price - self.position.entry_price) / self.position.entry_price * self.position.size_usd
        else:
            unrealized = (self.position.entry_price - price) / self.position.entry_price * self.position.size_usd
        return self.cash + self.position.size_usd + unrealized

    def _open_position(self, screen2: Screen2Output, screen1: Screen1Output, candle: Dict):
        """开仓 (v10.0: MA区间信号可覆盖Screen1方向)"""
        open_direction = screen2.ma_direction if screen2.ma_direction is not None else screen1.direction
        price = self._apply_slippage(screen2.entry_price, open_direction, is_buy=True)
        size_usd = self.equity * screen2.position_pct
        fee = self._calc_fee(size_usd)

        # 检查资金充足
        if size_usd + fee > self.cash:
            size_usd = self.cash / (1 + self.cfg["taker_fee"])
            fee = self._calc_fee(size_usd)

        if size_usd < 5:  # 最小开仓量
            return

        self.cash -= (size_usd + fee)
        dt = ts_to_dt(candle["ts"])

        if screen2.ma_direction is not None:
            print(f"      [MA-{screen2.ma_zone_gate}] 方向覆盖: {screen1.direction.value} -> {open_direction.value}")

        self.position = Position(
            direction=open_direction,
            entry_price=price,
            initial_size_usd=size_usd,
            size_usd=size_usd,
            level=0,
            add_on_levels=screen2.add_on_levels,
            tp_target=screen2.tp_target,
            highest_equity=self.equity,
            entry_date=dt.strftime("%Y-%m-%d"),
            signal_strength=screen2.signal_strength,
            screen1=screen1,
            total_cost=fee,
            is_martin_complete=False,
        )

        # v10.0: MA区间反向单标记 (用于 check_exit_signals 跳过L2, 禁止加仓)
        # v13.0: ABOVE_ALL_LONG/BELOW_ALL_SHORT 是顺势马丁, 不设此标记 (允许加仓+L2b/L2c出场)
        if screen2.ma_direction is not None and screen2.ma_zone_gate not in ("ABOVE_ALL_LONG", "BELOW_ALL_SHORT"):
            self.position.ma_zone_opened = True
            self.position.ma_zone_ref_price = screen2.ma_zone_ref_price

        trade = Trade(
            trade_id=self._next_trade_id(),
            timestamp=candle["ts"],
            date=dt.strftime("%Y-%m-%d"),
            action="open",
            direction=open_direction,
            price=price,
            size_usd=size_usd,
            fee=fee,
            signal_strength=screen2.signal_strength,
            screen1_direction=screen1.direction,
        )
        self.trades.append(trade)
        self.stats["signal_trades"][screen2.signal_strength.value] += 1

    def _add_position(self, add_price: float, add_size: float, candle: Dict,
                      vol_mult: float = 1.0, tp_pct: float = 4.0):
        """等额加仓 (v8.0: TP随均价滚动更新)"""
        price = self._apply_slippage(add_price, self.position.direction, is_buy=True)
        fee = self._calc_fee(add_size)

        self.cash -= (add_size + fee)
        recalc_avg_entry(self.position, price, add_size, self.cfg["taker_fee"],
                         vol_mult=vol_mult, tp_pct=tp_pct)
        self.position.total_cost += fee

        dt = ts_to_dt(candle["ts"])
        trade = Trade(
            trade_id=self._next_trade_id(),
            timestamp=candle["ts"],
            date=dt.strftime("%Y-%m-%d"),
            action="add_on",
            direction=self.position.direction,
            price=price,
            size_usd=add_size,
            fee=fee,
            signal_strength=self.position.signal_strength,
            screen1_direction=self.position.screen1.direction if self.position.screen1 else Direction.WAIT,
        )
        self.trades.append(trade)
        self.stats["add_on_count"] += 1

        if self.position.is_martin_complete:
            print(f"   [马丁加满] Level {self.position.level}/3 | TP目标=${self.position.tp_target:,.0f}")

    def _is_in_cooldown(self, current_date_str: str) -> bool:
        """检查是否在止损冷却期内"""
        if self.sl_cooldown_days <= 0 or not self.last_sl_date:
            return False
        try:
            from datetime import datetime as dt_cls
            last_dt = dt_cls.strptime(self.last_sl_date, "%Y-%m-%d")
            curr_dt = dt_cls.strptime(current_date_str, "%Y-%m-%d")
            days_since_sl = (curr_dt - last_dt).days
            return days_since_sl < self.sl_cooldown_days
        except (ValueError, TypeError):
            return False

    def _close_position(self, candle: Dict, exit_reason: ExitReason, price: float = None):
        """全仓平仓 (止损/信号反转/回撤限制/回测结束)"""
        if self.position.direction == Direction.WAIT:
            return

        close_price = price or candle["close"]
        close_price = self._apply_slippage(close_price, self.position.direction, is_buy=False)
        fee = self._calc_fee(self.position.size_usd)

        # 计算盈亏
        if self.position.direction == Direction.LONG:
            pnl = (close_price - self.position.entry_price) / self.position.entry_price * self.position.size_usd - fee
        else:
            pnl = (self.position.entry_price - close_price) / self.position.entry_price * self.position.size_usd - fee

        pnl -= self.position.total_cost
        pnl_pct = pnl / (self.position.total_cost + self.position.size_usd) if (self.position.total_cost + self.position.size_usd) > 0 else 0

        self.cash += self.position.size_usd + pnl - fee
        current_eq = self.cash

        # 记录统计
        self.stats["total_trades"] += 1
        if pnl > 0:
            self.stats["win_trades"] += 1
            if self.position.signal_strength:
                self.stats["signal_wins"][self.position.signal_strength.value] += 1
        else:
            self.stats["loss_trades"] += 1

        if exit_reason == ExitReason.DRAWDOWN_LIMIT:
            self.stats["forced_close_count"] += 1
            self.stats["drawdown_limit_count"] += 1
        if exit_reason == ExitReason.TAKE_PROFIT_1:
            self.stats["tp1_count"] += 1

        # 第一屏正确率
        if self.position.screen1:
            self.stats["screen1_total"] += 1
            if self.position.screen1.direction == self.position.direction and pnl > 0:
                self.stats["screen1_correct"] += 1

        # 马丁完成统计
        if self.position.is_martin_complete:
            self.stats["martin_complete_trades"] += 1
        else:
            self.stats["martin_incomplete_trades"] += 1

        dt = ts_to_dt(candle["ts"])
        date_str = dt.strftime("%Y-%m-%d")

        # 止损冷却期: 记录止损日期
        if exit_reason == ExitReason.STOP_LOSS:
            self.last_sl_date = date_str

        trade = Trade(
            trade_id=self._next_trade_id(),
            timestamp=candle["ts"],
            date=date_str,
            action="close",
            direction=self.position.direction,
            price=close_price,
            size_usd=self.position.size_usd,
            fee=fee,
            signal_strength=self.position.signal_strength,
            screen1_direction=self.position.screen1.direction if self.position.screen1 else Direction.WAIT,
            exit_reason=exit_reason,
            pnl=round(pnl, 2),
            pnl_pct=round(pnl_pct * 100, 2),
            equity_at_close=round(current_eq, 2),
        )
        self.trades.append(trade)

        self.position = Position()
        self.equity = current_eq

    def _get_weekly_screen1(self, candle: Dict) -> Screen1Output:
        """获取当日对应的周线决策 (缓存)"""
        dt = ts_to_dt(candle["ts"])
        week_key = dt.isocalendar()[:2]

        if week_key in self.screen1_cache:
            return self.screen1_cache[week_key]

        for i, wc in enumerate(self.weekly_candles):
            wc_dt = ts_to_dt(wc["ts"])
            if wc_dt.isocalendar()[:2] == week_key:
                result = run_screen1(self.weekly_candles, i, candle["close"], inst_id=self.cfg["inst_id"], opt_params=self.opt_params)
                self.screen1_cache[week_key] = result
                return result

        if self.weekly_candles:
            idx = len(self.weekly_candles) - 1
            result = run_screen1(self.weekly_candles, idx, candle["close"], inst_id=self.cfg["inst_id"], opt_params=self.opt_params)
            self.screen1_cache[week_key] = result
            return result

        return Screen1Output(
            timestamp=candle["ts"],
            direction=Direction.LONG,
            strategy_type=StrategyType.SPOT_MARTIN,
            weekly_score=50.0,
            ema_trend="neutral",
            macd_signal="none",
            market_state="观望",
            position_limit_pct=0.20,
        )

    def _record_equity(self, candle: Dict, price: float):
        eq = self._current_equity(price)
        self.equity = eq
        self.peak_equity = max(self.peak_equity, eq)

        dd = 0.0
        if self.peak_equity > 0:
            dd = (self.peak_equity - eq) / self.peak_equity * 100

        dt = ts_to_dt(candle["ts"])
        self.equity_curve.append({
            "date": dt.strftime("%Y-%m-%d"),
            "equity": round(eq, 2),
            "peak": round(self.peak_equity, 2),
        })
        self.drawdown_curve.append({
            "date": dt.strftime("%Y-%m-%d"),
            "drawdown": round(dd, 2),
        })

    def run(self) -> dict:
        """运行回测"""
        self.reset()

        print("=" * 60)
        print("Dream Systematic Trading - 回测引擎 v3.0")
        print("策略: 三屏交易体系 + 马丁策略 (对齐TRADING_WORKFLOW_SPEC_v1)")
        print("=" * 60)
        print(f"\n获取数据...")

        start_ts = dt_to_ts(self.cfg["start_date"])
        end_ts = dt_to_ts(self.cfg["end_date"])

        self.daily_candles = load_or_fetch(
            self.cfg["inst_id"], "1D", start_ts, end_ts
        )
        if not self.daily_candles:
            print("无法获取日线数据")
            return {}

        self.daily_candles = add_technical_indicators(self.daily_candles)
        self.weekly_candles = resample_to_weekly(self.daily_candles)
        self.weekly_candles = add_technical_indicators(self.weekly_candles)

        # v10.0: 构建BTC参考数据 (MA区间经验法则用)
        if self.cfg["inst_id"] == "BTC-USDT-SWAP":
            self.btc_daily_candles = self.daily_candles
        elif self._btc_candles_param:
            self.btc_daily_candles = self._btc_candles_param
        else:
            print("  [BTC参考] 单独加载BTC日线数据...")
            raw_btc = load_or_fetch("BTC-USDT-SWAP", "1D", start_ts, end_ts)
            self.btc_daily_candles = add_technical_indicators(raw_btc) if raw_btc else []

        self.btc_date_idx = {
            ts_to_dt(c["ts"]).strftime("%Y-%m-%d"): i
            for i, c in enumerate(self.btc_daily_candles)
        }

        print(f"\n数据准备完成:")
        print(f"   日线: {len(self.daily_candles)} 根")
        print(f"   周线: {len(self.weekly_candles)} 根")
        print(f"   BTC参考: {len(self.btc_daily_candles)} 根")
        print(f"   时间: {ts_to_dt(self.daily_candles[0]['ts']):%Y-%m-%d} ~ {ts_to_dt(self.daily_candles[-1]['ts']):%Y-%m-%d}")
        print(f"   初始资金: ${self.cfg['initial_capital']:,.2f}")
        print(f"   止损: 无固定SL (仅信号反转/20%回撤强制全平)")
        print(f"   加仓: 等额, 每跌8%×vol_mult, 最多3次, 信号评分≥50")
        print(f"   止盈: 单次全仓, 均价+4%×vol_mult")
        print(f"   MA区间: 涨三不追/跌四不压 (BTC全局参考)")

        print(f"\n开始回测...")
        warmup = 50

        for i in range(warmup, len(self.daily_candles)):
            candle = self.daily_candles[i]
            price = candle["close"]
            dt = ts_to_dt(candle["ts"])

            # 第一屏: 周线决策
            screen1 = self._get_weekly_screen1(candle)

            # v10.0: 查找BTC当日索引
            date_str = dt.strftime("%Y-%m-%d")
            btc_idx = self.btc_date_idx.get(date_str)

            # 第二屏: 日线预设 (v10.0: 传入BTC参考数据)
            screen2 = run_screen2(
                self.daily_candles, i, screen1, self.position,
                inst_id=self.cfg["inst_id"], opt_params=self.opt_params,
                btc_daily_candles=self.btc_daily_candles if self.btc_daily_candles else None,
                btc_idx=btc_idx,
            )

            # --- 持仓管理 ---
            if self.position.direction == Direction.WAIT:
                # 冷却期检查
                if self._is_in_cooldown(date_str):
                    self.stats["sl_cooldown_skip_count"] += 1
                # v10.0: MA区间门禁
                elif screen2.ma_zone_gate in ("BLOCKED", "BELOW_ALL_BLOCKED"):
                    pass
                # 规范: 第一屏确定方向 或 MA区间信号确定方向 -> 开仓
                elif screen1.direction in (Direction.LONG, Direction.SHORT) or screen2.ma_direction is not None:
                    self._open_position(screen2, screen1, candle)
                    open_dir = screen2.ma_direction if screen2.ma_direction is not None else screen1.direction
                    print(f"   {dt:%Y-%m-%d} 开仓: {open_dir.value} ({screen1.market_state}) "
                          f"| 信号={screen2.signal_score:.0f}({screen2.signal_strength.value}) "
                          f"| 价位=${price:,.0f} | 单层仓位={screen2.position_pct*100:.1f}% "
                          f"| TP=${screen2.tp_target:,.0f}")
            else:
                # 持仓中: 检查A9四层离场
                should_exit, exit_reason, tp_level = check_exit_signals(
                    self.position, candle, screen1,
                    self._current_equity(price), self.peak_equity,
                    len(self.trades),
                    inst_id=self.cfg["inst_id"],  # v14.0-B2
                )

                if should_exit:
                    # v8.0: 全部为全仓平仓
                    if exit_reason == ExitReason.TAKE_PROFIT_1:
                        close_price = self.position.tp_target
                    elif exit_reason == ExitReason.STOP_LOSS:
                        sl = self.position.stop_loss_price
                        close_price = sl if sl > 0 else price  # L2c无预设价时用当日收盘
                    else:
                        close_price = price
                    martin_tag = "[马丁加满]" if self.position.is_martin_complete else ""
                    print(f"   {dt:%Y-%m-%d} 全平: {exit_reason.value} {martin_tag} "
                          f"| Level={self.position.level}/3 | 价格=${close_price:,.0f}")
                    self._close_position(candle, exit_reason, close_price)

                    if exit_reason == ExitReason.DRAWDOWN_LIMIT:
                        print(f"   最大回撤触发, 强制全平!")
                        break
                else:
                    # 检查加仓 (v11.0: MA区间反向单禁止加仓; v7.0: RSI+ATR扩张跳过; v8.0: 信号评分门禁)
                    if self.position.ma_zone_opened:
                        add_info = None  # MA区间反向单: 单层持仓, 不加仓
                    elif screen2.addon_suppressed:
                        add_info = None
                    else:
                        addon_min_score = (self.opt_params or {}).get(
                            "addon_min_score", DEFAULT_STRATEGY_PARAMS["addon_min_score"]
                        )
                        add_info = calc_martin_add_on(
                            self.position, candle, self.cash, self.equity, self.cfg["taker_fee"],
                            min_score=addon_min_score, signal_score=screen2.signal_score,
                        )
                    if add_info:
                        add_price, add_size = add_info
                        dd = (self.peak_equity - self._current_equity(price)) / self.peak_equity * 100
                        if dd < self.cfg["warn_drawdown"]:
                            vol_mult = getattr(screen1, "vol_mult", 1.0)
                            tp_pct = (self.opt_params or {}).get(
                                "tp_pct", DEFAULT_STRATEGY_PARAMS["tp_pct"]
                            )
                            self._add_position(add_price, add_size, candle,
                                               vol_mult=vol_mult, tp_pct=tp_pct)
                            print(f"   {dt:%Y-%m-%d} 加仓L{self.position.level}: "
                                  f"${add_price:,.0f} x{add_size:.1f}U | TP=${self.position.tp_target:,.0f}")

            # 记录权益
            self._record_equity(candle, price)

            if (i - warmup + 1) % 100 == 0:
                eq = self.equity_curve[-1]["equity"] if self.equity_curve else 0
                print(f"   进度: {i - warmup + 1}/{len(self.daily_candles) - warmup} | 权益: ${eq:,.2f}")

        # 回测结束后如有持仓，按最后价格全平
        if self.position.direction != Direction.WAIT:
            last_candle = self.daily_candles[-1]
            self._close_position(last_candle, ExitReason.END_OF_BACKTEST)

        result = self._calc_stats()
        self._print_report(result)

        return result

    def _calc_stats(self) -> dict:
        init = self.cfg["initial_capital"]
        final = self.equity

        total_return = (final - init) / init * 100

        if self.daily_candles:
            first_dt = ts_to_dt(self.daily_candles[0]["ts"])
            last_dt = ts_to_dt(self.daily_candles[-1]["ts"])
            days = (last_dt - first_dt).days
        else:
            days = 1

        annual_return = ((1 + total_return / 100) ** (365 / max(days, 1)) - 1) * 100 if days > 0 else 0

        max_dd = 0.0
        if self.drawdown_curve:
            max_dd = max(d["drawdown"] for d in self.drawdown_curve)

        if len(self.equity_curve) > 1:
            returns = []
            for i in range(1, len(self.equity_curve)):
                r = (self.equity_curve[i]["equity"] - self.equity_curve[i-1]["equity"]) / self.equity_curve[i-1]["equity"]
                returns.append(r)
            if returns:
                avg_ret = sum(returns) / len(returns) * 252
                import statistics
                std_ret = statistics.stdev(returns) * (252 ** 0.5) if len(returns) > 1 else 0.01
                sharpe = (avg_ret - 0.02) / std_ret if std_ret > 0 else 0
            else:
                sharpe = 0
        else:
            sharpe = 0

        total_closed = self.stats["total_trades"]
        win_rate = (self.stats["win_trades"] / total_closed * 100) if total_closed > 0 else 0

        wins = [t.pnl for t in self.trades if t.action in ("close", "partial_close") and t.pnl > 0]
        losses = [t.pnl for t in self.trades if t.action in ("close", "partial_close") and t.pnl < 0]
        avg_win = sum(wins) / len(wins) if wins else 0
        avg_loss = abs(sum(losses) / len(losses)) if losses else 1
        profit_factor = avg_win / avg_loss if avg_loss > 0 else 0

        signal_analysis = {}
        for s in SignalStrength:
            count = self.stats["signal_trades"][s.value]
            wins_s = self.stats["signal_wins"][s.value]
            signal_analysis[s.value] = {
                "count": count,
                "wins": wins_s,
                "win_rate": round(wins_s / count * 100, 2) if count > 0 else 0,
            }

        monthly_returns = self._calc_monthly_returns()

        return {
            "config": self.cfg,
            "total_return": round(total_return, 2),
            "annual_return": round(annual_return, 2),
            "max_drawdown": round(max_dd, 2),
            "sharpe_ratio": round(sharpe, 2),
            "win_rate": round(win_rate, 2),
            "profit_factor": round(profit_factor, 2),
            "total_trades": total_closed,
            "win_trades": self.stats["win_trades"],
            "loss_trades": self.stats["loss_trades"],
            "add_on_count": self.stats["add_on_count"],
            "partial_close_count": self.stats["partial_close_count"],
            "tp1_count": self.stats["tp1_count"],
            "tp2_count": self.stats["tp2_count"],
            "tp3_count": self.stats["tp3_count"],
            "forced_close_count": self.stats["forced_close_count"],
            "drawdown_limit_count": self.stats["drawdown_limit_count"],
            "martin_complete_trades": self.stats["martin_complete_trades"],
            "martin_incomplete_trades": self.stats["martin_incomplete_trades"],
            "sl_cooldown_skip_count": self.stats["sl_cooldown_skip_count"],
            "sl_cooldown_days": self.sl_cooldown_days,
            "final_equity": round(final, 2),
            "initial_capital": init,
            "backtest_days": days,
            "signal_analysis": signal_analysis,
            "screen1_accuracy": round(
                self.stats["screen1_correct"] / self.stats["screen1_total"] * 100, 2
            ) if self.stats["screen1_total"] > 0 else 0,
            "monthly_returns": monthly_returns,
            "equity_curve": self.equity_curve,
            "drawdown_curve": self.drawdown_curve,
            "trades": self.trades,
        }

    def _calc_monthly_returns(self) -> Dict:
        monthly: Dict[str, float] = {}
        for i in range(1, len(self.equity_curve)):
            curr = self.equity_curve[i]
            prev = self.equity_curve[i - 1]
            month_key = curr["date"][:7]
            if month_key not in monthly:
                monthly[month_key] = prev["equity"]
            monthly[month_key] = curr["equity"]

        result = {}
        months_sorted = sorted(monthly.keys())
        prev_val = self.cfg["initial_capital"]
        for m in months_sorted:
            ret = (monthly[m] - prev_val) / prev_val * 100
            result[m] = round(ret, 2)
            prev_val = monthly[m]
        return result

    def _print_report(self, result: dict):
        c = self.cfg
        print(f"\n{'=' * 60}")
        print(f"Dream Systematic Trading - 回测报告 v3.0")
        print(f"{'=' * 60}")
        print(f"\n回测参数:")
        print(f"   交易对:     {c['inst_id']}")
        print(f"   时间范围:   {c['start_date']} ~ {c['end_date']} ({result['backtest_days']}天)")
        print(f"   初始资金:   ${c['initial_capital']:,.2f}")
        print(f"   止损:       无固定SL (信号反转/20%回撤强制全平)")
        print(f"   加仓:       等额×vol_mult, 最多3次, 信号评分≥50")
        print(f"   止盈:       单次全仓 (均价+4%×vol_mult)")

        print(f"\n性能指标:")
        print(f"   总收益率:   {result['total_return']:+.2f}%")
        print(f"   年化收益率: {result['annual_return']:+.2f}%")
        print(f"   最大回撤:   {result['max_drawdown']:.2f}% {'(<=20% OK)' if result['max_drawdown'] <= 20 else '(>20% FAIL)'}")
        print(f"   夏普比率:   {result['sharpe_ratio']:.2f}")
        print(f"   胜率:       {result['win_rate']:.2f}%")
        print(f"   盈亏比:     {result['profit_factor']:.2f}")
        print(f"   交易次数:   {result['total_trades']}次 (加仓{result['add_on_count']}次)")

        print(f"\n马丁策略统计:")
        print(f"   马丁完成:   {result['martin_complete_trades']}次 (加满3层)")
        print(f"   马丁未完成: {result['martin_incomplete_trades']}次 (信号反转/回撤)")
        print(f"   TP触发:     {result['tp1_count']}次 (单次全仓止盈)")

        print(f"\n风险控制:")
        print(f"   止损出场:   (含在总交易中)")
        print(f"   回撤强制:   {result['drawdown_limit_count']}次")
        if self.sl_cooldown_days > 0:
            print(f"   冷却期:     {self.sl_cooldown_days}天 (跳过{result['sl_cooldown_skip_count']}次开仓)")

        print(f"\n信号强度分析:")
        for s_name, s_data in result['signal_analysis'].items():
            if s_data["count"] > 0:
                print(f"   {s_name:8s}: {s_data['count']:3d}次 -> 胜率 {s_data['win_rate']:.1f}%")

        print(f"\n第一屏正确率: {result['screen1_accuracy']:.1f}%")
        print(f"\n最终权益: ${result['final_equity']:,.2f}")
        print(f"{'=' * 60}")


# ==================== 主入口 ====================

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Dream Systematic Trading 回测引擎 v3.0")
    parser.add_argument("--inst", default="BTC-USDT-SWAP", help="交易对")
    parser.add_argument("--from", dest="start", default="2025-01-01", help="开始日期")
    parser.add_argument("--to", dest="end", default="2026-05-16", help="结束日期")
    parser.add_argument("--capital", type=float, default=200, help="初始资金")
    parser.add_argument("--output", default=None, help="结果输出JSON路径")
    args = parser.parse_args()

    config = {
        "inst_id": args.inst,
        "start_date": args.start,
        "end_date": args.end,
        "initial_capital": args.capital,
    }

    engine = BacktestEngine(config)
    result = engine.run()

    if result and args.output:
        save_result = {k: v for k, v in result.items() if k not in ("equity_curve", "drawdown_curve", "trades")}
        save_result["equity_curve_count"] = len(result.get("equity_curve", []))
        save_result["drawdown_curve_count"] = len(result.get("drawdown_curve", []))
        save_result["trades_count"] = len(result.get("trades", []))
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "w") as f:
            json.dump(save_result, f, indent=2, ensure_ascii=False)
        print(f"\n结果已保存: {out_path}")
