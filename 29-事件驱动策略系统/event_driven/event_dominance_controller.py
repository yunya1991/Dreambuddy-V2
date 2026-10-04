"""
EventDominanceController — 宏观事件主导控制器

SPEC §5: 装饰器模式，不修改现有子系统逻辑。
当宏观事件置信度足够高时，过滤/覆盖其他子系统信号。

3 档过滤:
  - hard (conviction >= 0.85): 硬过滤，宏观信号覆盖 BCRM/BDSM/庙算
  - soft (0.70 <= conviction < 0.85): 软过滤，宏观信号作为加权 modifier (±0.10)
  - none (conviction < 0.70): 不过滤

FAIL-OPEN:
  - 数据质量问题 → 自动降级为 none
  - 手动 override → 强制某档位

安全机制 (SPEC §4.7.4):
  - 连续 3 笔亏损自动降档 (hard→soft→pass_through)
  - 1 小时置信度漂移 >0.15 立即降档
  - 降档单调（只能向下，不自动恢复；reset_downgrade() 人工重置）
"""
from __future__ import annotations

import logging
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class DominanceDecision:
    """主导控制决策。"""

    filter_level: str  # "hard" / "soft" / "none"
    macro_direction: str  # "long" / "short" / "neutral"
    modifier: float  # ±0.10-0.15
    override_subsystems: bool  # 是否覆盖子系统
    active: bool  # 宏观信号是否激活
    reason: str
    raw: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "filter_level": self.filter_level,
            "macro_direction": self.macro_direction,
            "modifier": self.modifier,
            "override_subsystems": self.override_subsystems,
            "active": self.active,
            "reason": self.reason,
        }


class EventDominanceController:
    """宏观事件主导控制器（装饰器模式）。"""

    HARD_MODIFIER = 0.15
    SOFT_MODIFIER = 0.10

    # P0-1: 连续亏损降档阈值（SPEC §4.7.4）
    DOWNGRADE_LOSS_STREAK_THRESHOLD = 3
    # P0-2: 置信度漂移监控（SPEC §4.7.4）
    DOWNGRADE_CONVICTION_DRIFT_THRESHOLD = 0.15
    DOWNGRADE_CONVICTION_DRIFT_WINDOW_SEC = 3600

    # 降档链顺序（保守度递增）：hard → soft → none(pass_through)
    _LEVEL_ORDER = {"hard": 0, "soft": 1, "none": 2}

    @staticmethod
    def is_enabled() -> bool:
        """P1-2: 双层门控检查（硬约束模式）。

        总开关 enable_contradiction_driven_layer + 子开关 enable_event_dominance
        双层都开启才返回 True。异常时 FAIL-OPEN 返回 False（安全默认）。
        """
        try:
            from dreambuddy_evolution.agi_config import is_enabled as _is_enabled
            return (
                _is_enabled("enable_contradiction_driven_layer")
                and _is_enabled("enable_event_dominance")
            )
        except Exception:
            return False  # FAIL-OPEN 安全默认

    def __init__(
        self,
        manual_override: str | None = None,
        loss_streak_threshold: int = DOWNGRADE_LOSS_STREAK_THRESHOLD,
        conviction_drift_threshold: float = DOWNGRADE_CONVICTION_DRIFT_THRESHOLD,
        conviction_drift_window_sec: int = DOWNGRADE_CONVICTION_DRIFT_WINDOW_SEC,
    ) -> None:
        """
        Args:
            manual_override: 手动覆盖档位 "hard"/"soft"/"none"/None
            loss_streak_threshold: 连续亏损降档阈值（默认 3）
            conviction_drift_threshold: 置信度漂移阈值（默认 0.15）
            conviction_drift_window_sec: 漂移监控窗口（默认 3600s = 1h）
        """
        self._manual_override = manual_override
        # P0-1 降档状态机
        self._loss_streak = 0
        self._downgrade_level: str | None = None  # None / "soft" / "none"
        self._loss_streak_threshold = loss_streak_threshold
        # P0-2 置信度漂移监控
        self._conviction_history: deque[tuple[float, float]] = deque()
        self._conviction_drift_threshold = conviction_drift_threshold
        self._conviction_drift_window_sec = conviction_drift_window_sec

    # ==========================================================================
    # P0-1: 连续亏损降档
    # ==========================================================================

    def record_outcome(self, outcome: str) -> str | None:
        """
        记录交易结果，触发连续亏损降档（SPEC §4.7.4）。

        过滤模式下连续 `loss_streak_threshold` 笔亏损 → 自动降档一级
        （hard→soft→pass_through）。TP 重置连续亏损计数，但不自动恢复
        已降档级别（需人工 reset_downgrade()）。

        Args:
            outcome: "SL" 止损 / "TP" 止盈 / 其他

        Returns:
            当前降档级别（None=无降档 / "soft" / "none"）
        """
        outcome_upper = str(outcome).upper()
        if outcome_upper == "SL":
            self._loss_streak += 1
            if self._loss_streak >= self._loss_streak_threshold:
                self._apply_downgrade(
                    reason=f"连续 {self._loss_streak} 笔亏损达阈值 {self._loss_streak_threshold}"
                )
                self._loss_streak = 0  # 重置计数，下一轮再累计
        elif outcome_upper == "TP":
            self._loss_streak = 0  # TP 重置连续亏损计数
        # 其他 outcome（如 FLAT/PARTIAL）不改变计数
        return self._downgrade_level

    def _apply_downgrade(self, reason: str = "") -> None:
        """沿降档链前进一步：None → soft → none。降档单调，已最低档保持不变。"""
        prev = self._downgrade_level
        if self._downgrade_level is None:
            self._downgrade_level = "soft"
            logger.warning("[EDC] DOWNGRADE hard → soft (%s)", reason)
        elif self._downgrade_level == "soft":
            self._downgrade_level = "none"  # pass_through
            logger.warning("[EDC] DOWNGRADE soft → pass_through (%s)", reason)
        # 已是 none（pass_through），保持
        _ = prev  # 保留用于审计

    def reset_downgrade(self) -> None:
        """人工重置降档状态，恢复子系统自主权（SPEC §4.7.4 手动覆盖）。"""
        if self._downgrade_level is not None or self._loss_streak > 0:
            logger.info(
                "[EDC] reset_downgrade: level=%s loss_streak=%d → cleared (人工重置)",
                self._downgrade_level,
                self._loss_streak,
            )
        self._downgrade_level = None
        self._loss_streak = 0
        self._conviction_history.clear()

    # ==========================================================================
    # P0-2: 置信度漂移监控
    # ==========================================================================

    def _check_conviction_drift(
        self,
        current_conviction: float,
        now: float | None = None,
    ) -> bool:
        """
        检查 1 小时内 conviction 漂移是否超过阈值（SPEC §4.7.4）。

        规则：与 1 小时窗口内的最高 conviction 比较，若下降 > 阈值 → 触发降档。

        Args:
            current_conviction: 当前置信度
            now: 当前时间戳（测试注入用），None=time.time()

        Returns:
            True = 触发降档，False = 未触发
        """
        if now is None:
            now = time.time()

        # 清理窗口外的历史记录
        window_start = now - self._conviction_drift_window_sec
        while self._conviction_history and self._conviction_history[0][0] < window_start:
            self._conviction_history.popleft()

        # 无历史记录时不触发
        if not self._conviction_history:
            return False

        max_conviction_in_window = max(c for _, c in self._conviction_history)
        drift = max_conviction_in_window - current_conviction
        if drift > self._conviction_drift_threshold:
            self._apply_downgrade(
                reason=(
                    f"置信度漂移 {drift:.3f} > {self._conviction_drift_threshold:.2f}"
                    f"（1h max={max_conviction_in_window:.3f} → now={current_conviction:.3f}）"
                )
            )
            return True
        return False

    def _apply_downgrade_override(self, base_level: str) -> tuple[str, str | None]:
        """
        应用降档覆盖：取 base 与 downgrade 中更保守的级别。

        Returns:
            (effective_level, applied_downgrade) — applied_downgrade 为 None
            表示未应用降档覆盖；非 None 表示降档生效档位。
        """
        if self._downgrade_level is None:
            return base_level, None
        base_idx = self._LEVEL_ORDER[base_level]
        downgrade_idx = self._LEVEL_ORDER[self._downgrade_level]
        if downgrade_idx > base_idx:
            return self._downgrade_level, self._downgrade_level
        return base_level, None

    # ==========================================================================
    # decide + apply_filter
    # ==========================================================================

    def decide(
        self,
        conviction: float,
        macro_direction: str,
        data_quality: float = 1.0,
        in_fomc_cycle: bool = True,
        now: float | None = None,
    ) -> DominanceDecision:
        """
        计算主导控制决策。

        Args:
            conviction: 置信度 0.0-1.0
            macro_direction: 宏观方向 "long"/"short"/"neutral"
            data_quality: 数据质量 0.0-1.0
            in_fomc_cycle: 是否在 FOMC 周期内
            now: 时间戳（测试注入），None=time.time()

        Returns DominanceDecision。
        """
        if now is None:
            now = time.time()

        # P0-2: 记录 conviction 历史 + 检查漂移（FAIL-OPEN）
        try:
            self._check_conviction_drift(conviction, now=now)
            self._conviction_history.append((now, conviction))
        except Exception as e:  # FAIL-OPEN: 漂移监控异常不阻塞
            logger.debug("[EDC] drift check FAIL-OPEN: %s", e, exc_info=False)

        # FAIL-OPEN: 不在 FOMC 周期或方向中性 → 不激活
        if not in_fomc_cycle or macro_direction == "neutral":
            return DominanceDecision(
                filter_level="none",
                macro_direction=macro_direction,
                modifier=0.0,
                override_subsystems=False,
                active=False,
                reason="不在 FOMC 周期或方向中性",
                raw={"conviction": conviction, "data_quality": data_quality, "downgrade": self._downgrade_level},
            )

        # FAIL-OPEN: 数据质量过低 → 降级
        if data_quality < 0.4:
            return DominanceDecision(
                filter_level="none",
                macro_direction=macro_direction,
                modifier=0.0,
                override_subsystems=False,
                active=False,
                reason=f"数据质量过低 ({data_quality:.2f} < 0.4)，FAIL-OPEN",
                raw={"conviction": conviction, "data_quality": data_quality, "downgrade": self._downgrade_level},
            )

        # 计算静态 base_level
        if self._manual_override:
            base_level = self._manual_override
            base_reason = f"手动覆盖为 {base_level}"
        elif conviction >= 0.85:
            base_level = "hard"
            base_reason = f"高置信度 ({conviction:.2f} >= 0.85)，硬过滤"
        elif conviction >= 0.70:
            base_level = "soft"
            base_reason = f"中置信度 ({conviction:.2f} >= 0.70)，软过滤"
        else:
            base_level = "none"
            base_reason = f"低置信度 ({conviction:.2f} < 0.70)，不过滤"

        # 应用降档覆盖（取较保守级别）
        effective_level, applied_downgrade = self._apply_downgrade_override(base_level)
        if applied_downgrade:
            reason = f"{base_reason} → 降档覆盖为 {effective_level}（连续亏损/置信度漂移）"
        else:
            reason = base_reason

        # 计算 modifier 和 override（基于 effective_level）
        direction_mult = 1.0 if macro_direction == "long" else -1.0
        if effective_level == "hard":
            modifier = self.HARD_MODIFIER * direction_mult
            override = True
            active = True
        elif effective_level == "soft":
            modifier = self.SOFT_MODIFIER * direction_mult
            override = False
            active = True
        else:
            modifier = 0.0
            override = False
            active = False

        return DominanceDecision(
            filter_level=effective_level,
            macro_direction=macro_direction,
            modifier=round(modifier, 4),
            override_subsystems=override,
            active=active,
            reason=reason,
            raw={
                "conviction": conviction,
                "data_quality": data_quality,
                "downgrade": self._downgrade_level,
                "base_level": base_level,
                "applied_downgrade": applied_downgrade,
            },
        )

    def apply_filter(
        self,
        subsystem_signal: dict[str, Any],
        decision: DominanceDecision,
        case_library: Any = None,
        event_ctx: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        对现有子系统信号应用过滤（装饰器）。

        P1-1: 传入 case_library 时记录过滤决策审计日志（SPEC §4.7.4 日志审计），
        记录 signal + event_ctx + filter_result 供回测分析。

        Args:
            subsystem_signal: 子系统原始信号 dict（含 direction/confidence 等）
            decision: DominanceDecision
            case_library: 可选，EventCaseLibrary 实例，传入则持久化过滤决策
            event_ctx: 可选，事件上下文（cycle_phase/hike_prob 等）

        Returns 过滤后的信号 dict。
        """
        if not decision.active:
            # 不激活也记录（供回测审计 pass_through 场景），FAIL-OPEN
            self._maybe_record_filter_decision(
                case_library, subsystem_signal, subsystem_signal, decision, event_ctx,
            )
            return subsystem_signal  # 不修改

        result = dict(subsystem_signal)

        if decision.override_subsystems:
            # 硬过滤：用宏观方向覆盖
            result["direction"] = decision.macro_direction
            result["macro_override"] = True
            result["macro_filter_level"] = "hard"
            logger.info(
                "[EDC] HARD filter: override %s -> %s (conviction modifier %.3f)",
                subsystem_signal.get("direction"),
                decision.macro_direction,
                decision.modifier,
            )
        else:
            # 软过滤：调整 confidence，不改变 direction
            orig_conf = float(result.get("confidence", 0.5))
            result["confidence"] = max(0.0, min(1.0, orig_conf + decision.modifier))
            result["macro_modifier"] = decision.modifier
            result["macro_filter_level"] = "soft"

        # P1-1: 持久化过滤决策（FAIL-OPEN，异常不阻塞交易热路径）
        self._maybe_record_filter_decision(
            case_library, subsystem_signal, result, decision, event_ctx,
        )

        return result

    @staticmethod
    def _maybe_record_filter_decision(
        case_library: Any,
        subsystem_signal: dict[str, Any],
        filter_result: dict[str, Any],
        decision: DominanceDecision,
        event_ctx: dict[str, Any] | None,
    ) -> None:
        """P1-1: 记录过滤决策到 case_library（FAIL-OPEN，不阻塞交易）。"""
        if case_library is None:
            return
        try:
            from datetime import datetime
            record = {
                "timestamp": datetime.now().isoformat(),
                "filter_level": decision.filter_level,
                "conviction": decision.raw.get("conviction"),
                "macro_direction": decision.macro_direction,
                "modifier": decision.modifier,
                "subsystem_signal": dict(subsystem_signal),
                "filter_result": dict(filter_result),
                "event_ctx": dict(event_ctx) if event_ctx else {},
                "downgrade": decision.raw.get("downgrade"),
                "reason": decision.reason,
            }
            case_library.add_filter_decision(record)
        except Exception as e:
            logger.debug("[EDC] record filter decision FAIL-OPEN: %s", e, exc_info=False)

    def set_manual_override(self, level: str | None) -> None:
        """设置手动覆盖档位。"""
        self._manual_override = level
