"""WashoutSLGuard — Layer 1 SLTP 动态调节器 (洗盘判定三层防御 Layer 1).

Spec: docs/superpowers/specs/2026-09-21-washout-detector-design.md §7.3

三层防御:
  Layer 1: WashoutSLGuard (本文件) — SLTP 动态调节
  Layer 2: P3EarlyExit 洗盘感知 (exit_strategies.py)
  Layer 3: WashoutHoldStrategy priority=15 (exit_strategies.py)

硬约束 (VM-1789994567129-791d228a B 级):
  HC-15: 放宽SL不得超原SL的25% (原SL距entry间距的1.25倍)
  HC-16: 放宽后SL必须位于爆仓价+0.3%安全缓冲的安全侧 (爆仓安全优先)
  HC-17: 收紧SL不得高于当前mark price
  HC-18: 放宽窗口最长48h, 超时自动恢复原SL
  HC-19: verdict从washout变为非washout时自动恢复原SL
  HC-22: ENABLE_WASHOUT_DETECTOR=False 时降级为no_change, 链路字节等价

FAIL-OPEN 铁律: 任何异常 → no_change + 6层堆栈日志, 不抛错不阻塞.
"""
from __future__ import annotations

import logging
import time
import traceback
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from .washout_detector import WashoutLabel, WashoutVerdict

__all__ = ["WashoutSLGuard", "SLAdjustment"]

logger = logging.getLogger(__name__)


# ============================================================
# SLAdjustment 数据结构
# ============================================================
@dataclass
class SLAdjustment:
    """WashoutSLGuard 输出契约.

    Attributes:
        action: no_change | widen_sl | tighten_sl | restore_sl
        new_sl_px: 新 SL 价格 (no_change 时 = current_sl)
        reason: 触发原因摘要
        timestamp: ISO 8601 UTC
    """
    action: str
    new_sl_px: float
    reason: str
    timestamp: str = ""

    @staticmethod
    def no_change(current_sl: float, reason: str = "no_change") -> "SLAdjustment":
        return SLAdjustment(
            action="no_change",
            new_sl_px=current_sl,
            reason=reason,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )


# ============================================================
# WashoutSLGuard 主类
# ============================================================
class WashoutSLGuard:
    """SLTP 动态调节器 (Layer 1).

    在 polling_trader SLTP 检查前调用, 根据洗盘判定动态调节 SL:
      - washout+conf≥0.80 → 放宽 SL (避免被洗盘扫损)
      - weakness+conf≥0.70 → 收紧 SL (加速离场)
      - unknown/低置信度 → no_change
      - verdict 变化 (washout→非washout) → restore_sl
      - 放宽超 48h → restore_sl

    用法:
        guard = WashoutSLGuard(washout_detector=detector)
        adj = guard.adjust_sl(coin="BTC", df=df, macro_data=macro,
                              current_sl=90.0, mark_price=91.0,
                              entry_price=100.0, pos_side="long",
                              liq_price=50.0, original_sl=90.0,
                              age_hours=1.0, last_adjust_ts=0.0)
        if adj.action != "no_change":
            self._adjust_algo_sl(coin, adj.new_sl_px, reason=adj.reason)
    """

    def __init__(
        self,
        washout_detector: Optional[Any] = None,
        max_widen_pct: float = 0.25,
        safe_margin_pct: float = 0.003,
        widen_timeout_h: float = 48.0,
        weakness_conf_threshold: float = 0.70,
        washout_conf_threshold: float = 0.80,
        widen_step_pct: float = 0.20,
        tighten_step_pct: float = 0.20,
    ):
        """
        Args:
            washout_detector: WashoutDetector 实例 (None 或 enable=False → no_change)
            max_widen_pct: 放宽幅度上限 (相对原 SL 距 entry 间距, 默认 0.25=25%)
            safe_margin_pct: 爆仓安全缓冲 (默认 0.003=0.3%)
            widen_timeout_h: 放宽窗口超时 (默认 48h)
            weakness_conf_threshold: weakness 触发收紧的置信度阈值 (默认 0.70)
            washout_conf_threshold: washout 触发放宽的置信度阈值 (默认 0.80)
            widen_step_pct: 单次放宽步长 (相对原 SL 距 entry 间距, 默认 0.20=20%)
            tighten_step_pct: 单次收紧步长 (相对 current_sl 与 mark 间距, 默认 0.20=20%)
        """
        self.washout_detector = washout_detector
        self.max_widen_pct = float(max_widen_pct)
        self.safe_margin_pct = float(safe_margin_pct)
        self.widen_timeout_h = float(widen_timeout_h)
        self.weakness_conf_threshold = float(weakness_conf_threshold)
        self.washout_conf_threshold = float(washout_conf_threshold)
        self.widen_step_pct = float(widen_step_pct)
        self.tighten_step_pct = float(tighten_step_pct)

        # 每币种状态: {coin: {original_sl, last_verdict_label, last_adjust_ts, widened}}
        self._state: Dict[str, Dict[str, Any]] = {}
        # 审计日志: {coin: List[{action, new_sl_px, reason, timestamp}]}
        self._log: Dict[str, List[Dict[str, Any]]] = {}

    # ============================================================
    # 主入口
    # ============================================================
    def adjust_sl(
        self,
        coin: str,
        df: Any,
        macro_data: Dict[str, Any],
        current_sl: float,
        mark_price: float,
        entry_price: float,
        pos_side: str,
        liq_price: float,
        original_sl: float,
        age_hours: float,
        last_adjust_ts: float,
    ) -> SLAdjustment:
        """主入口: 根据洗盘判定调节 SL.

        Args:
            coin: 币种符号
            df: OHLCV DataFrame (传给 detector)
            macro_data: 宏观特征字典 (传给 detector)
            current_sl: 当前 SL 价格
            mark_price: 当前标记价格
            entry_price: 开仓价格
            pos_side: long / short
            liq_price: 爆仓价格
            original_sl: 原始 SL 价格 (用于 restore)
            age_hours: 持仓时长 (小时)
            last_adjust_ts: 上次调节时间戳 (秒, 0=未调节过)

        Returns:
            SLAdjustment (action + new_sl_px + reason)
        """
        try:
            # HC-22: detector 缺失或关闭 → no_change
            if self.washout_detector is None:
                return SLAdjustment.no_change(current_sl, "detector_none")
            if not getattr(self.washout_detector, "enable", True):
                return SLAdjustment.no_change(current_sl, "detector_disabled")

            # 获取 verdict (FAIL-OPEN)
            try:
                verdict: WashoutVerdict = self.washout_detector.run(coin, df, macro_data)
            except Exception as e:
                tb = traceback.format_exc()
                logger.error(
                    "washout_sl_guard detector FAIL-OPEN coin=%s err=%s\n%s",
                    coin, e, tb,
                )
                self._append_log(coin, "no_change", current_sl, "fail_open_exception")
                return SLAdjustment.no_change(current_sl, "fail_open_exception")

            # 获取/初始化币种状态
            state = self._state.setdefault(coin, {
                "original_sl": float(original_sl),
                "last_verdict_label": None,
                "last_adjust_ts": float(last_adjust_ts),
                "widened": False,
            })
            # 更新 original_sl (调用方可能传入新的 original)
            state["original_sl"] = float(original_sl)

            now_ts = time.time()
            prev_label = state.get("last_verdict_label")
            curr_label = verdict.label

            # HC-18: 放宽超 48h → restore_sl
            if state["widened"] and last_adjust_ts > 0:
                elapsed_h = (now_ts - float(last_adjust_ts)) / 3600.0
                if elapsed_h > self.widen_timeout_h:
                    restored = float(original_sl)
                    self._reset_state(coin, curr_label, original_sl)
                    self._append_log(coin, "restore_sl", restored,
                                     f"timeout_{elapsed_h:.1f}h")
                    return SLAdjustment(
                        action="restore_sl",
                        new_sl_px=restored,
                        reason=f"widen_timeout_{elapsed_h:.1f}h",
                    )

            # HC-19: verdict 从 washout→非 washout 且之前放宽过 → restore_sl
            if (state["widened"]
                    and prev_label == WashoutLabel.WASHOUT
                    and curr_label != WashoutLabel.WASHOUT):
                restored = float(original_sl)
                self._reset_state(coin, curr_label, original_sl)
                self._append_log(
                    coin, "restore_sl", restored,
                    f"verdict_change_{(prev_label.value if prev_label else 'none')}"
                    f"_to_{curr_label.value}",
                )
                return SLAdjustment(
                    action="restore_sl",
                    new_sl_px=restored,
                    reason="verdict_change_restore",
                )

            # 放宽 / 收紧 / no_change
            if (curr_label == WashoutLabel.WASHOUT
                    and verdict.confidence >= self.washout_conf_threshold):
                # widen_sl
                new_sl = self._compute_widen_sl(
                    current_sl=float(current_sl),
                    mark_price=float(mark_price),
                    entry_price=float(entry_price),
                    pos_side=pos_side,
                    liq_price=float(liq_price),
                    original_sl=float(original_sl),
                )
                state["last_verdict_label"] = curr_label
                state["last_adjust_ts"] = now_ts
                state["widened"] = True
                self._append_log(coin, "widen_sl", new_sl,
                                 f"washout_conf{verdict.confidence:.2f}")
                return SLAdjustment(
                    action="widen_sl",
                    new_sl_px=new_sl,
                    reason=f"washout_widen_conf{verdict.confidence:.2f}",
                )

            if (curr_label == WashoutLabel.WEAKNESS
                    and verdict.confidence >= self.weakness_conf_threshold):
                # tighten_sl
                new_sl = self._compute_tighten_sl(
                    current_sl=float(current_sl),
                    mark_price=float(mark_price),
                    entry_price=float(entry_price),
                    pos_side=pos_side,
                    original_sl=float(original_sl),
                )
                state["last_verdict_label"] = curr_label
                state["last_adjust_ts"] = now_ts
                state["widened"] = False
                self._append_log(coin, "tighten_sl", new_sl,
                                 f"weakness_conf{verdict.confidence:.2f}")
                return SLAdjustment(
                    action="tighten_sl",
                    new_sl_px=new_sl,
                    reason=f"weakness_tighten_conf{verdict.confidence:.2f}",
                )

            # no_change: unknown 或低置信度
            state["last_verdict_label"] = curr_label
            self._append_log(coin, "no_change", float(current_sl),
                             f"label_{curr_label.value}_conf{verdict.confidence:.2f}")
            return SLAdjustment.no_change(
                float(current_sl),
                f"label_{curr_label.value}_conf{verdict.confidence:.2f}",
            )

        except Exception as e:
            tb = traceback.format_exc()
            logger.error(
                "washout_sl_guard FAIL-OPEN coin=%s err=%s\n%s",
                coin, e, tb,
            )
            self._append_log(coin, "no_change", float(current_sl),
                             "fail_open_exception")
            return SLAdjustment.no_change(float(current_sl), "fail_open_exception")

    # ============================================================
    # SL 计算辅助
    # ============================================================
    def _compute_widen_sl(
        self,
        current_sl: float,
        mark_price: float,
        entry_price: float,
        pos_side: str,
        liq_price: float,
        original_sl: float,
    ) -> float:
        """计算放宽后的 SL (HC-15 + HC-16).

        放宽方向:
          - 做多 (pos_side=long): SL 下移 (远离 mark, 朝 liq 方向)
          - 做空 (pos_side=short): SL 上移 (远离 mark, 朝 liq 方向)

        HC-15: 放宽后 SL 距 entry 的间距 ≤ 原 SL 距 entry 间距 × (1 + max_widen_pct)
        HC-16: 放宽后 SL 必须在爆仓价 + safe_margin_pct 安全侧
               (做多: SL ≥ liq × (1+safe_margin); 做空: SL ≤ liq × (1-safe_margin))
        """
        is_long = (pos_side or "long").lower() == "long"

        # 原 SL 距 entry 的间距
        original_sl_dist = abs(original_sl - entry_price)
        # HC-15: 单次放宽步长 = 原间距 × widen_step_pct, 累计上限 = 原间距 × max_widen_pct
        step = original_sl_dist * self.widen_step_pct
        max_widen_total = original_sl_dist * self.max_widen_pct
        # 当前已放宽量 = |current_sl - original_sl| (做多: current < original 表示已放宽)
        if is_long:
            already_widened = max(0.0, original_sl - current_sl)
        else:
            already_widened = max(0.0, current_sl - original_sl)
        remaining = max(0.0, max_widen_total - already_widened)
        widen_abs = min(step, remaining)

        if is_long:
            new_sl = current_sl - widen_abs
        else:
            new_sl = current_sl + widen_abs

        # HC-16: 爆仓安全边际
        if is_long:
            # 做多 SL < mark, liq < mark (通常), 安全侧: SL ≥ liq × (1 + safe_margin)
            safe_floor = abs(liq_price) * (1.0 + self.safe_margin_pct)
            if new_sl < safe_floor:
                new_sl = safe_floor
            # 但放宽不得越过 mark (SL < mark for long)
            if new_sl >= mark_price:
                new_sl = mark_price * (1.0 - self.safe_margin_pct)
        else:
            # 做空 SL > mark, liq > mark (通常), 安全侧: SL ≤ liq × (1 - safe_margin)
            safe_ceil = abs(liq_price) * (1.0 - self.safe_margin_pct)
            if new_sl > safe_ceil:
                new_sl = safe_ceil
            if new_sl <= mark_price:
                new_sl = mark_price * (1.0 + self.safe_margin_pct)

        return float(new_sl)

    def _compute_tighten_sl(
        self,
        current_sl: float,
        mark_price: float,
        entry_price: float,
        pos_side: str,
        original_sl: float,
    ) -> float:
        """计算收紧后的 SL (HC-17).

        收紧方向:
          - 做多: SL 上移 (朝 mark 方向)
          - 做空: SL 下移 (朝 mark 方向)

        HC-17: 收紧后 SL 不得高于 (做多) / 不得低于 (做空) 当前 mark price.
        """
        is_long = (pos_side or "long").lower() == "long"

        # 收紧步长 = current_sl 与 mark 间距 × tighten_step_pct
        dist_to_mark = abs(mark_price - current_sl)
        tighten_abs = dist_to_mark * self.tighten_step_pct

        if is_long:
            new_sl = current_sl + tighten_abs
            # HC-17: 不得高于 mark price (做多 SL < mark)
            # 留 0.5% 安全缓冲避免恰好等于 mark
            cap = mark_price * 0.995
            if new_sl > cap:
                new_sl = cap
        else:
            new_sl = current_sl - tighten_abs
            floor = mark_price * 1.005
            if new_sl < floor:
                new_sl = floor

        return float(new_sl)

    # ============================================================
    # 状态 + 日志
    # ============================================================
    def _reset_state(self, coin: str, curr_label: Optional[WashoutLabel],
                     original_sl: float) -> None:
        """重置币种状态 (restore 后调用)."""
        self._state[coin] = {
            "original_sl": float(original_sl),
            "last_verdict_label": curr_label,
            "last_adjust_ts": 0.0,
            "widened": False,
        }

    def _append_log(self, coin: str, action: str, new_sl: float,
                    reason: str) -> None:
        """追加审计日志."""
        if coin not in self._log:
            self._log[coin] = []
        self._log[coin].append({
            "action": action,
            "new_sl_px": float(new_sl),
            "reason": reason,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

    def get_adjustment_log(self, coin: str) -> List[Dict[str, Any]]:
        """获取 SL 调整审计日志.

        Args:
            coin: 币种符号

        Returns:
            List[Dict] — 每条含 action/new_sl_px/reason/timestamp
        """
        return list(self._log.get(coin, []))
