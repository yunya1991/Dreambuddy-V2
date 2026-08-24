"""
方案 C v3.0 R-4：PortfolioRiskFuses
=====================================
组合级风险熔断（G-02 黑天鹅 + G-04 终极熔断）。

熔断定义：
  - G-02 黑天鹅 3 条件（同时命中）：
      ① 同方向持仓 ≥ 5 笔
      ② 15min 平均浮亏 ≥ 0.50%
      ③ BTC λ ≤ 0.75
    → 动作：暂停开新仓 1h + SL×0.90 + TP×1.05

  - G-04 终极熔断（单日权益回撤 ≥ 3%）：
    → 动作：emergency_shutdown=True（调用方需关断 SW-C1~C8 共 24h）

fail-open：
  - 任何异常 → FuseAction(block_new_open=False, sl_mult_adj=1.0, tp_mult_adj=1.0, emergency_shutdown=False)
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


@dataclass
class FuseAction:
    """熔断动作输出"""
    block_new_open: bool = False          # True → 下一次 _open_position 直接 return
    sl_mult_adj: float = 1.0              # 止损系数调整（<1 更近）
    tp_mult_adj: float = 1.0              # 止盈系数调整（>1 更远）
    emergency_shutdown: bool = False      # True → G-04 终极熔断（SW 全关 24h）
    reason: str = "no_trigger"
    trigger_at_ts: float = 0.0            # 触发时间戳（冷却判定使用）
    block_until_ts: float = 0.0           # block_new_open 到期时间戳

    def as_shadow_dict(self) -> Dict[str, Any]:
        return {
            "block_new_open": self.block_new_open,
            "sl_mult_adj": self.sl_mult_adj,
            "tp_mult_adj": self.tp_mult_adj,
            "emergency_shutdown": self.emergency_shutdown,
            "reason": self.reason,
            "trigger_at": datetime.fromtimestamp(self.trigger_at_ts).isoformat() if self.trigger_at_ts else "",
            "block_until": datetime.fromtimestamp(self.block_until_ts).isoformat() if self.block_until_ts else "",
        }


class PortfolioRiskFuses:
    """组合级风险熔断（G-02 + G-04）"""

    def __init__(self, enable: bool = False):
        self.enable = bool(enable)
        # G-02 block_new_open 冷却到期
        self._g02_block_until_ts: float = 0.0
        self._g02_last_trigger_at: float = 0.0
        # G-04 终极熔断：触发日期 + 关断 24h
        self._g04_emergency_until_ts: float = 0.0
        self._g04_last_trigger_at: float = 0.0
        self._last_failopen_logged_hour: str = ""

    # ---------------- 公共：主 tick ----------------
    def tick_and_check(self, ctx: Optional[Dict[str, Any]] = None) -> FuseAction:
        """
        每轮 run_once 调用一次，返回当前 FuseAction。

        ctx 字段：
          - positions_by_direction: Dict[str, int]（LONG/SHORT → 持仓笔数）
          - avg_float_loss_pct_15m: float（15min 平均浮亏，正数 = 浮亏）
          - btc_lambda: float（BTC 自反 λ，未触发=1.0）
          - daily_equity_prev: float（前日收盘权益）
          - daily_equity_now: float（当前权益）
        """
        try:
            from . import phase_c_constants as C

            ctx = ctx or {}
            now = time.time()

            # ---- G-04 终极熔断：已触发且未到期 → 直接 return emergency ----
            if now < self._g04_emergency_until_ts:
                return FuseAction(
                    block_new_open=True,
                    sl_mult_adj=1.0,
                    tp_mult_adj=1.0,
                    emergency_shutdown=True,
                    reason="g04_emergency_active",
                    trigger_at_ts=self._g04_last_trigger_at,
                    block_until_ts=self._g04_emergency_until_ts,
                )

            # ---- G-04：单日权益回撤 ≥ 3%（小数 0.03）----
            eq_prev = float(ctx.get("daily_equity_prev", 0.0) or 0.0)
            eq_now = float(ctx.get("daily_equity_now", 0.0) or 0.0)
            if eq_prev > 0 and eq_now > 0:
                dd = (eq_prev - eq_now) / eq_prev  # 正数 = 回撤
                if dd >= C.G04_DAILY_DRAWDOWN_THRESHOLD:
                    self._g04_last_trigger_at = now
                    self._g04_emergency_until_ts = now + C.G04_SHUTDOWN_HOURS * 3600
                    return FuseAction(
                        block_new_open=True,
                        sl_mult_adj=1.0,
                        tp_mult_adj=1.0,
                        emergency_shutdown=True,
                        reason=f"g04_dd_{dd:.4f}_ge_{C.G04_DAILY_DRAWDOWN_THRESHOLD}",
                        trigger_at_ts=now,
                        block_until_ts=self._g04_emergency_until_ts,
                    )

            # ---- G-02 block_new_open 冷却：未到期直接返回 ----
            if now < self._g02_block_until_ts:
                return FuseAction(
                    block_new_open=True,
                    sl_mult_adj=C.G02_SL_MULT_ADJ,
                    tp_mult_adj=C.G02_TP_MULT_ADJ,
                    emergency_shutdown=False,
                    reason="g02_cooldown",
                    trigger_at_ts=self._g02_last_trigger_at,
                    block_until_ts=self._g02_block_until_ts,
                )

            # ---- G-02：三条件 AND ----
            pos_by_dir: Dict[str, int] = ctx.get("positions_by_direction") or {}
            max_same_dir = max(int(pos_by_dir.get("LONG", 0)), int(pos_by_dir.get("SHORT", 0)))
            avg_loss = float(ctx.get("avg_float_loss_pct_15m", 0.0) or 0.0)
            btc_lambda = float(ctx.get("btc_lambda", 1.0) or 1.0)

            cond1 = max_same_dir >= C.G02_SAME_DIR_POSITION_COUNT
            cond2 = avg_loss >= C.G02_AVG_FLOAT_LOSS_PCT
            cond3 = btc_lambda <= C.G02_BTC_LAMBDA_UPPER
            if cond1 and cond2 and cond3:
                self._g02_last_trigger_at = now
                self._g02_block_until_ts = now + C.G02_BLOCK_NEW_OPEN_SECONDS
                return FuseAction(
                    block_new_open=True,
                    sl_mult_adj=C.G02_SL_MULT_ADJ,
                    tp_mult_adj=C.G02_TP_MULT_ADJ,
                    emergency_shutdown=False,
                    reason=f"g02_triggered_c1{cond1}_c2{cond2}_c3{cond3}",
                    trigger_at_ts=now,
                    block_until_ts=self._g02_block_until_ts,
                )

            # ---- 无熔断 ----
            return FuseAction(reason="no_trigger")

        except Exception as e:  # noqa: BLE001 - fail-open 兜底
            import datetime as _dt
            hour_tag = _dt.datetime.now().strftime("%Y-%m-%dT%H")
            if self._last_failopen_logged_hour != hour_tag:
                logger.warning(
                    "[PortfolioRiskFuses] fail-open（每小时最多 1 次），原因=%s，返回无熔断",
                    type(e).__name__,
                )
                self._last_failopen_logged_hour = hour_tag
            return FuseAction(reason=f"fail_open:{type(e).__name__}")
