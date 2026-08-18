#!/usr/bin/env python3
"""
市场形态管理器 (RegimeManager)
==============================

在 DirectionGate 的瞬时形态判断之上，增加「连续3日收盘确认 + sticky_last」防护层，
避免价格在均线附近反复穿越导致形态频繁切换。

核心逻辑：
  1. DirectionGate.evaluate() 输出 raw_regime（瞬时形态）
  2. RegimeManager.update() 跟踪 raw_regime 连续出现的天数
  3. 只有连续 confirm_days 日同一新形态，才切换 confirmed_regime
  4. 切换前一直返回旧形态（sticky）

用法（实盘）:
    rm = RegimeManager(confirm_days=3)
    rm.load_state(state_dict)       # 从 state 文件恢复
    confirmed = rm.update(raw_regime, date_str="2026-08-06")

用法（回测）:
    confirmed_list = compute_confirmed_regimes(raw_list, confirm_days=3)
"""
from __future__ import annotations

from typing import List, Optional, Dict


# ===================================================================
# Phase 2: 减速检测 + 动态确认天数 (替代僵硬的3日收盘确认)
# ===================================================================

def detect_deceleration_zone(a: float, v: float, threshold: float = 0.02) -> str:
    """
    基于加速度-速度内积 (a·v) 的趋势稳定性判定。

    Args:
        a: 加速度 a = F_net / mass
        v: 速度（Verlet 积分后的市场速度）
        threshold: 速度阈值（默认 0.02，与 VelocityIntegrator 一致）

    Returns:
        "accel"   — 加速态：a·v>0 且 |v| > 2×threshold（趋势可靠，1天确认）
        "decel"   — 减速态：a·v<0 且 |v| > threshold（力反向拉速度，5天保守）
        "neutral" — 中性/支撑区：其他（默认3天）
    """
    av = a * v
    abs_v = abs(v)
    if av > 0 and abs_v > 2 * threshold:
        return "accel"
    if av < 0 and abs_v > threshold:
        return "decel"
    return "neutral"


def effective_confirm_days(zone: str, default_days: int = 3) -> int:
    """检测区 → 动态确认天数"""
    if zone == "accel":
        return 1
    if zone == "decel":
        return 5
    return default_days


class RegimeManager:
    """市场形态管理器 — 连续N日收盘确认 + sticky_last 防震荡 + Phase2 力学化动态天数"""

    def __init__(self, confirm_days: int = 3, initial_regime: str = "LONG_ONLY"):
        """
        Args:
            confirm_days: 连续确认天数（默认3日，中性态 fallback 值）
            initial_regime: 初始确认形态
        """
        self.confirm_days = confirm_days
        self.confirmed_regime = initial_regime
        self.pending_regime: Optional[str] = None
        self.pending_count = 0
        self.last_date: Optional[str] = None
        self.last_change_date: Optional[str] = None  # 形态上次切换的日期
        # Phase 2: 上次使用的检测区（诊断用）
        self.last_zone: Optional[str] = None

    def update(self, raw_regime: str, date_str: Optional[str] = None,
               mechanistic_ctx: Optional[Dict[str, float]] = None) -> str:
        """单步更新（实盘用），返回 confirmed_regime

        仅在日切（date_str 变化）时才递增 pending_count，
        确保同一天内多次调用不会误增计数。

        Args:
            raw_regime: DirectionGate 输出的瞬时形态
            date_str: 当前日期字符串（如 "2026-08-06"），None 时每次都计数
            mechanistic_ctx: Phase 2 力学化上下文，可选字段：
                {"a": acceleration, "v": velocity, "threshold": 0.02}
                存在时使用「减速检测 → 动态 confirm_days」，否则按 confirm_days 默认。

        Returns:
            confirmed_regime: 经过确认 + sticky 处理后的形态
        """
        # Phase 2: 根据 mechanistic_ctx 计算 effective confirm_days
        if mechanistic_ctx and isinstance(mechanistic_ctx, dict):
            a = float(mechanistic_ctx.get("a", 0.0) or 0.0)
            v = float(mechanistic_ctx.get("v", 0.0) or 0.0)
            t = float(mechanistic_ctx.get("threshold", 0.02) or 0.02)
            zone = detect_deceleration_zone(a, v, t)
            eff = effective_confirm_days(zone, self.confirm_days)
            self.last_zone = zone
        else:
            eff = self.confirm_days
            self.last_zone = None

        is_new_day = date_str is not None and date_str != self.last_date
        self.last_date = date_str

        if raw_regime == self.confirmed_regime:
            # 与当前确认态一致 → 重置 pending
            self.pending_regime = None
            self.pending_count = 0
        else:
            # 与确认态不同 → 检查是否和 pending 一致
            if raw_regime == self.pending_regime:
                if is_new_day or date_str is None:
                    self.pending_count += 1
            else:
                # 新的候选形态
                self.pending_regime = raw_regime
                self.pending_count = 1 if (is_new_day or date_str is None) else 0

            # 连续 eff 日同一新形态 → 切换（动态天数）
            if self.pending_count >= eff:
                self.confirmed_regime = self.pending_regime
                self.pending_regime = None
                self.pending_count = 0
                self.last_change_date = date_str or self.last_date

        return self.confirmed_regime

    def save_state(self) -> dict:
        """序列化状态用于持久化（Phase2: 额外保存 last_zone）"""
        d: Dict = {
            "confirmed_regime": self.confirmed_regime,
            "pending_regime": self.pending_regime,
            "pending_count": self.pending_count,
            "confirm_days": self.confirm_days,
            "last_date": self.last_date,
            "last_change_date": self.last_change_date,
        }
        if self.last_zone is not None:
            d["last_zone"] = self.last_zone
        return d

    def load_state(self, state: dict):
        """从持久化数据恢复状态（忽略额外字段，如 velocity_integrator_state，由调用方处理）"""
        self.confirmed_regime = state.get("confirmed_regime", "LONG_ONLY")
        self.pending_regime = state.get("pending_regime")
        self.pending_count = state.get("pending_count", 0)
        self.confirm_days = state.get("confirm_days", self.confirm_days)
        self.last_date = state.get("last_date")
        self.last_change_date = state.get("last_change_date")
        self.last_zone = state.get("last_zone")

    def is_in_cooldown(self, cooldown_days: int, today_str: Optional[str] = None) -> bool:
        """判断当前是否处于形态切换冷却期内

        Args:
            cooldown_days: 冷却天数（如 2 表示切换后2天内不开仓）
            today_str: 当前日期字符串，None 时用 last_date

        Returns:
            True 如果在冷却期内
        """
        if not self.last_change_date or cooldown_days <= 0:
            return False
        ref_date = today_str or self.last_date
        if not ref_date:
            return False
        try:
            from datetime import datetime, timedelta
            d_change = datetime.strptime(self.last_change_date, "%Y-%m-%d")
            d_now = datetime.strptime(ref_date, "%Y-%m-%d")
            return (d_now - d_change).days < cooldown_days
        except Exception:
            return False


def compute_confirmed_regimes(
    raw_regimes: List[str],
    confirm_days: int = 3,
    initial_regime: str = "LONG_ONLY",
) -> List[str]:
    """批量计算确认形态序列（回测用）

    对 raw_regimes 列表逐元素应用 RegimeManager 逻辑，
    返回等长的 confirmed_regimes 列表。

    Args:
        raw_regimes: 原始形态序列（如 DirectionGate 逐 bar 的输出）
        confirm_days: 连续确认天数
        initial_regime: 初始确认形态

    Returns:
        confirmed_regimes: 确认后的形态序列（等长）
    """
    rm = RegimeManager(confirm_days=confirm_days, initial_regime=initial_regime)
    result = []
    for raw in raw_regimes:
        # 回测中每个元素代表一个 bar（4h），需要按日去重计数
        # 这里用 date_str=None 模式，让每次不同 raw 都计一次
        # 但同一天多个 bar 可能输出相同 raw_regime，不应重复计数
        # 实际回测调用方应传入日级别的序列，或在调用前按日去重
        confirmed = rm.update(raw, date_str=None)
        result.append(confirmed)
    return result


def compute_confirmed_regimes_by_date(
    raw_regimes: List[str],
    date_strs: List[str],
    confirm_days: int = 3,
    initial_regime: str = "LONG_ONLY",
) -> List[str]:
    """按日期去重的批量确认（回测用，4H bar → 日级确认）

    同一天内多个 bar 的 raw_regime 可能不同，
    取该日最后一个 bar 的 raw_regime 作为当日形态，
    仅在日切时递增 pending_count。

    Args:
        raw_regimes: 原始形态序列（逐 bar）
        date_strs: 对应的日期字符串序列（等长）
        confirm_days: 连续确认天数
        initial_regime: 初始确认形态

    Returns:
        confirmed_regimes: 确认后的形态序列（等长，逐 bar 填充当日确认形态）
    """
    rm = RegimeManager(confirm_days=confirm_days, initial_regime=initial_regime)
    result = []
    for raw, ds in zip(raw_regimes, date_strs):
        confirmed = rm.update(raw, date_str=ds)
        result.append(confirmed)
    return result


# ── 自检 ──────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=== RegimeManager 自检 ===\n")

    # 场景1: 3日确认 + sticky
    rm = RegimeManager(confirm_days=3, initial_regime="LONG_ONLY")
    test_data = [
        ("LONG", "D1"), ("SHORT", "D2"), ("SHORT", "D3"), ("LONG", "D4"),
        ("SHORT", "D5"), ("SHORT", "D6"), ("SHORT", "D7"), ("LONG", "D8"),
        ("LONG", "D9"), ("LONG", "D10"),
    ]
    print("场景1: 3日确认 + sticky")
    print(f"{'日期':>4} {'raw':>12} {'pending':>12} {'count':>5} {'confirmed':>12}")
    for raw, ds in test_data:
        confirmed = rm.update(raw, date_str=ds)
        print(f"{ds:>4} {raw:>12} {str(rm.pending_regime):>12} {rm.pending_count:>5} {confirmed:>12}")

    # 场景2: 同一天多次调用不重复计数
    print("\n场景2: 同一天多次调用不重复计数")
    rm2 = RegimeManager(confirm_days=3, initial_regime="LONG_ONLY")
    rm2.update("LONG", "D1")
    rm2.update("SHORT", "D2")  # 第1次
    rm2.update("SHORT", "D2")  # 同一天，不应重复计数
    rm2.update("SHORT", "D2")  # 同一天，不应重复计数
    print(f"  D2 调用3次, pending_count={rm2.pending_count} (应为1)")
    rm2.update("SHORT", "D3")  # 第2天
    print(f"  D3 调用1次, pending_count={rm2.pending_count} (应为2)")
    rm2.update("SHORT", "D4")  # 第3天 → 切换
    print(f"  D4 调用1次, pending_count={rm2.pending_count} (应为0), confirmed={rm2.confirmed_regime} (应为SHORT)")

    # 场景3: 回测批量计算
    print("\n场景3: 批量计算 compute_confirmed_regimes")
    raws = ["LONG", "SHORT", "SHORT", "LONG", "SHORT", "SHORT", "SHORT", "LONG", "LONG", "LONG"]
    confirmed = compute_confirmed_regimes(raws, confirm_days=3, initial_regime="LONG")
    for i, (r, c) in enumerate(zip(raws, confirmed)):
        marker = " ← 切换" if i > 0 and c != confirmed[i - 1] else ""
        print(f"  [{i}] raw={r:>6} → confirmed={c:>6}{marker}")

    # 场景4: 按日期去重
    print("\n场景4: 按日期去重 compute_confirmed_regimes_by_date")
    raws_4h = ["LONG", "LONG", "SHORT", "SHORT", "SHORT", "SHORT", "LONG", "SHORT", "SHORT", "SHORT"]
    dates_4h = ["D1", "D1", "D2", "D2", "D3", "D3", "D4", "D5", "D5", "D6"]
    confirmed_4h = compute_confirmed_regimes_by_date(raws_4h, dates_4h, confirm_days=3, initial_regime="LONG")
    for i, (r, d, c) in enumerate(zip(raws_4h, dates_4h, confirmed_4h)):
        print(f"  [{i}] {d} raw={r:>6} → confirmed={c:>6}")
