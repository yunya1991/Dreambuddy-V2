"""ExitBacktestRunner — 离场模块回测闭环

缺口D：支持 exit_engine 完整规则回测（不限于软投票），
形成"训练→回测→择优→部署"闭环。

功能：
1. run(trade): 单笔交易回测，返回 PnL/exit_reason/exit_ts
2. compare_baselines(trade, genes): 对比多组基因参数
3. run_multi(trades): 多标的并行回测

回测流程：
  对每个 kline → 构造 context → facade.decide(context) → 模拟执行
  → 直到 force_close/partial_close 或 kline 耗尽
"""
from __future__ import annotations

import copy
import logging
from typing import Any, Dict, List, Optional

from dreambuddy_evolution.engines.exit_engine.facade import ExitModuleFacade
from dreambuddy_evolution.engines.exit_engine.exit_strategy_params import (
    ExitStrategyParams,
)

logger = logging.getLogger(__name__)


class ExitBacktestRunner:
    """离场模块回测闭环

    对 exit_engine 完整规则链（0-6）进行回测验证，
    支持不同基因参数对比，形成进化择优闭环。
    """

    def __init__(self, facade: Optional[ExitModuleFacade] = None):
        """
        Args:
            facade: 已构造的 ExitModuleFacade（可选，缺省自动构造）
        """
        self._facade = facade or ExitModuleFacade()

    def run(self, trade: Dict[str, Any]) -> Dict[str, Any]:
        """单笔交易回测

        Args:
            trade: 交易数据，包含：
                - symbol/pos_side/tier/entry_price/entry_ts
                - klines: K线列表 [{ts, close, high, low}, ...]
                - initial_sl_px/initial_tp_px/atr_pct

        Returns:
            dict: {symbol, final_pnl_pct, exit_reason, exit_ts, exit_price, decisions}
        """
        symbol = trade.get("symbol", "UNKNOWN")
        pos_side = trade.get("pos_side", "long")
        tier = trade.get("tier", "standard")
        entry_price = float(trade.get("entry_price", 0.0))
        entry_ts = float(trade.get("entry_ts", 0.0))
        klines = trade.get("klines", [])
        sl_px = float(trade.get("initial_sl_px", 0.0))
        tp_px = float(trade.get("initial_tp_px", 0.0))
        atr_pct = float(trade.get("atr_pct", 0.025))

        if not klines or entry_price <= 0:
            return {
                "symbol": symbol,
                "final_pnl_pct": 0.0,
                "exit_reason": "no_klines",
                "exit_ts": entry_ts,
                "exit_price": entry_price,
                "decisions": [],
            }

        current_sl = sl_px
        current_tp = tp_px
        decisions: List[Dict] = []
        exit_reason = "kline_exhausted"
        exit_ts = klines[-1].get("ts", entry_ts)
        exit_price = float(klines[-1].get("close", entry_price))

        for i, kline in enumerate(klines):
            current_price = float(kline.get("close", entry_price))
            kline_ts = float(kline.get("ts", entry_ts + i * 3600))
            position_age_sec = max(0.0, kline_ts - entry_ts) if entry_ts > 0 else float(i * 3600)

            # 规则0：检查 SL/TP 触达
            if pos_side == "long":
                if current_price <= current_sl and current_sl > 0:
                    exit_reason = "sl_hit"
                    exit_ts = kline_ts
                    exit_price = current_sl
                    break
                if current_price >= current_tp and current_tp > 0:
                    exit_reason = "tp_hit"
                    exit_ts = kline_ts
                    exit_price = current_tp
                    break
            else:
                if current_price >= current_sl and current_sl > 0:
                    exit_reason = "sl_hit"
                    exit_ts = kline_ts
                    exit_price = current_sl
                    break
                if current_price <= current_tp and current_tp > 0:
                    exit_reason = "tp_hit"
                    exit_ts = kline_ts
                    exit_price = current_tp
                    break

            # 构造 context
            upl_pct = (current_price - entry_price) / entry_price if pos_side == "long" else (entry_price - current_price) / entry_price
            r_multiple = 0.0
            tp_distance = abs(current_tp - entry_price)
            if tp_distance > 0:
                price_gain = (current_price - entry_price) if pos_side == "long" else (entry_price - current_price)
                r_multiple = price_gain / tp_distance

            # TP 衰减计算
            tp_decayed_pct = self._calc_tp_decay(position_age_sec)

            context = {
                "symbol": symbol,
                "pos_side": pos_side,
                "tier": tier,
                "position_age_sec": position_age_sec,
                "upl_ratio": upl_pct,
                "current_price": current_price,
                "entry_price": entry_price,
                "ess": 0.6,  # 默认 ESS
                "r_vector": {},
                "current_sl_px": current_sl,
                "current_tp_px": current_tp,
                "atr_pct": atr_pct,
                "r_multiple": r_multiple,
                "tp_decayed_pct": tp_decayed_pct,
                "has_stronger_signal": False,
                "stronger_signal_info": {},
            }

            decision = self._facade.decide(context)
            decisions.append({
                "ts": kline_ts,
                "action": decision.action,
                "reason": decision.reason,
                "sl_px": decision.sl_px or current_sl,
                "tp_px": decision.tp_px or current_tp,
            })

            # 执行决策
            if decision.action == "force_close":
                exit_reason = decision.reason
                exit_ts = kline_ts
                exit_price = current_price
                break
            elif decision.action == "partial_close":
                # 分批止盈：记录但不退出
                pass
            elif decision.action == "adjust_sl_tp":
                if decision.sl_px > 0:
                    current_sl = decision.sl_px
                if decision.tp_px > 0:
                    current_tp = decision.tp_px
            elif decision.action == "trailing":
                if decision.sl_px > 0:
                    current_sl = decision.sl_px

        # 计算最终 PnL
        if pos_side == "long":
            final_pnl_pct = (exit_price - entry_price) / entry_price
        else:
            final_pnl_pct = (entry_price - exit_price) / entry_price

        return {
            "symbol": symbol,
            "final_pnl_pct": final_pnl_pct,
            "exit_reason": exit_reason,
            "exit_ts": exit_ts,
            "exit_price": exit_price,
            "decisions": decisions,
        }

    def compare_baselines(
        self, trade: Dict[str, Any], genes: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """对比多组基因参数

        Args:
            trade: 单笔交易数据
            genes: 基因参数列表，每个是 dict 如 {"trailing_arm_pct": 0.05}

        Returns:
            结果列表，每个含 gene + final_pnl_pct + exit_reason
        """
        results = []
        for gene in genes:
            # 加载基因
            import json
            self._facade.load_gene(json.dumps(gene))
            # 回测
            result = self.run(trade)
            results.append({
                "gene": gene,
                "final_pnl_pct": result["final_pnl_pct"],
                "exit_reason": result["exit_reason"],
                "exit_ts": result["exit_ts"],
            })
        return results

    def run_multi(self, trades: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """多标的并行回测

        Args:
            trades: 交易数据列表

        Returns:
            结果列表（顺序与输入一致）
        """
        results = []
        for trade in trades:
            result = self.run(trade)
            results.append(result)
        return results

    def _calc_tp_decay(self, position_age_sec: float) -> float:
        """计算 TP 时间衰减间距

        与 polling_trader L4496 公式一致：
          tp_pct(t) = max(1.5%, 6% - (6%-1.5%) × max(0, t-12)/60)
        """
        _TP_DECAY_BASE = 0.06
        _TP_DECAY_FLOOR = 0.015
        _TP_DECAY_GRACE_HOURS = 12
        _TP_DECAY_FULL_HOURS = 72
        _age_hours = float(position_age_sec) / 3600.0
        if _age_hours <= _TP_DECAY_GRACE_HOURS:
            return _TP_DECAY_BASE
        _decay_progress = min(
            1.0,
            (_age_hours - _TP_DECAY_GRACE_HOURS)
            / (_TP_DECAY_FULL_HOURS - _TP_DECAY_GRACE_HOURS),
        )
        _decayed = _TP_DECAY_BASE - (_TP_DECAY_BASE - _TP_DECAY_FLOOR) * _decay_progress
        return max(_TP_DECAY_FLOOR, _decayed)
