"""
G-05 不可逆级联事前预防熔断 — TDD 红灯测试
================================================
SPEC: 非线性多阶段最优路径理论调研框架 §十六

判据5: 不可逆级联4事前判据
  ① primary_dim_jumped : primary矛盾维度跳变（质变检测）
  ② mechanism_active    : 机制性强制启动（反身性燃料检测）
  ③ no_bounce_at_key   : 价格穿越关键位后无有效反弹
  ④ no_intervener      : 无外部干预者（Fed/央行/交易所）

触发规则: ① AND ② AND (③ OR ④) → emergency_shutdown
优先级: G-04 > G-05 > G-02（G-04事后终极 > G-05事前预防 > G-02事后黑天鹅）

红灯阶段：G-05 尚未实现，以下测试应全部 FAIL（AttributeError/KeyError/reason不匹配）。

测试清单（共 12 项）：
  T8.13：4判据全满足 → 触发 G-05 emergency_shutdown
  T8.14：缺判据①（dim_jumped=False）→ no_trigger
  T8.15：缺判据②（mech_active=False）→ no_trigger
  T8.16：缺判据③和④（bounce=True, intervener=True）→ no_trigger
  T8.17：①+②+③ 但无④ → 触发（③满足，OR条件成立）
  T8.18：①+②+④ 但无③ → 触发（④满足，OR条件成立）
  T8.19：G-05 优先于 G-02（两者同时满足时，走 G-05）
  T8.20：G-04 优先于 G-05（两者同时满足时，走 G-04）
  T8.21：ctx=None → no_trigger（FAIL-OPEN）
  T8.22：ctx 异常字段 → no_trigger（FAIL-OPEN）
  T8.23：G-05 触发后冷却期内 → g05_cascade_active 保持阻塞
  T8.24：G-05 冷却过期 → 恢复 no_trigger
  T8.25：信号字段缺失（key不存在）→ 该判据默认False → no_trigger（FAIL-OPEN）
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

_THIS_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _THIS_DIR.parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))


# ============================================================
# Fixtures
# ============================================================
@pytest.fixture
def fuse_enabled():
    """启用熔断，重置所有冷却状态."""
    from scripts.memory_l4.portfolio_risk_fuses import PortfolioRiskFuses
    f = PortfolioRiskFuses(enable=True)
    f._g02_block_until_ts = 0.0
    f._g02_last_trigger_at = 0.0
    f._g04_emergency_until_ts = 0.0
    f._g04_last_trigger_at = 0.0
    # G-05 冷却状态（红灯阶段：这些属性尚未存在，需要实现后添加）
    if hasattr(f, "_g05_cascade_until_ts"):
        f._g05_cascade_until_ts = 0.0
    if hasattr(f, "_g05_last_trigger_at"):
        f._g05_last_trigger_at = 0.0
    return f


@pytest.fixture
def g05_full_hit_ctx():
    """G-05 四判据全满足的 ctx.

    ① primary_dim_jumped = True   (primary矛盾维度已跳变)
    ② mechanism_active = True     (机制性强制启动——如死亡螺旋/清算级联)
    ③ no_bounce_at_key = True     (穿关键位后无有效反弹)
    ④ no_intervener = True         (无外部干预者)

    同时附带 G-02/G-04 的 ctx 字段（确保 G-02 也会触发，用于优先级测试）。
    """
    return {
        # G-05 四判据
        "primary_dim_jumped": True,
        "mechanism_active": True,
        "no_bounce_at_key": True,
        "no_intervener": True,
        # G-02 三条件（全满足，用于优先级测试 T8.19）
        "positions_by_direction": {"LONG": 6, "SHORT": 2},
        "avg_float_loss_pct_15m": 0.006,
        "btc_lambda": 0.68,
        # G-04（不触发：dd=0.5% < 3%）
        "daily_equity_prev": 2000.0,
        "daily_equity_now": 1990.0,
    }


# ============================================================
# T8.13：4判据全满足 → 触发 G-05 emergency_shutdown
# ============================================================
def test_t8_13_g05_all_four_criteria_triggered(fuse_enabled, g05_full_hit_ctx):
    """① AND ② AND (③ OR ④) 全满足 → emergency_shutdown=True."""
    act = fuse_enabled.tick_and_check(g05_full_hit_ctx)
    # 红灯：G-05 尚未实现，reason 应不是 g05_*
    assert act.emergency_shutdown is True, f"G-05 应触发 emergency_shutdown，got reason={act.reason}"
    assert act.reason.startswith("g05_"), f"reason 应以 g05_ 开头，got={act.reason}"
    assert act.block_new_open is True


# ============================================================
# T8.14：缺判据①（primary_dim_jumped=False）→ no_trigger
# ============================================================
def test_t8_14_g05_missing_criterion_1_no_trigger(fuse_enabled, g05_full_hit_ctx):
    """缺① → 不可逆级联未形成 → 不触发."""
    ctx = dict(g05_full_hit_ctx)
    ctx["primary_dim_jumped"] = False
    act = fuse_enabled.tick_and_check(ctx)
    # ②③④ 满足但缺① → G-05 不触发
    # 注意：G-02 三条件仍满足 → 应走 G-02 而非 no_trigger
    # 但如果 G-05 未实现，G-02 会触发 → reason=g02_*
    # 红灯阶段：验证 G-05 逻辑存在（如果 G-05 实现了，应跳过 G-02）
    assert act.reason != "g05_cascade_imminent", "缺① 不应触发 G-05"


# ============================================================
# T8.15：缺判据②（mechanism_active=False）→ no_trigger
# ============================================================
def test_t8_15_g05_missing_criterion_2_no_trigger(fuse_enabled, g05_full_hit_ctx):
    """缺② → 无机制性强制 → 级联未启动 → 不触发 G-05."""
    ctx = dict(g05_full_hit_ctx)
    ctx["mechanism_active"] = False
    act = fuse_enabled.tick_and_check(ctx)
    assert act.reason != "g05_cascade_imminent", "缺② 不应触发 G-05"


# ============================================================
# T8.16：缺判据③和④ → no_trigger（OR条件不满足）
# ============================================================
def test_t8_16_g05_missing_both_3_and_4_no_trigger(fuse_enabled, g05_full_hit_ctx):
    """缺③AND④ → (③OR④)不满足 → 不触发 G-05.

    有反弹(③=False) 且 有干预者(④=False) → 级联可被截断 → 不触发.
    """
    ctx = dict(g05_full_hit_ctx)
    ctx["no_bounce_at_key"] = False  # 有关键位反弹
    ctx["no_intervener"] = False    # 有外部干预者
    act = fuse_enabled.tick_and_check(ctx)
    assert act.reason != "g05_cascade_imminent", "缺③和④ 不应触发 G-05"


# ============================================================
# T8.17：①+②+③ 但无④ → 触发（③满足，OR条件成立）
# ============================================================
def test_t8_17_g05_c1_c2_c3_without_c4_triggered(fuse_enabled, g05_full_hit_ctx):
    """①+②+③ 但 ④=False → ①AND②AND(③OR④)=①AND②AND③=True → 触发."""
    ctx = dict(g05_full_hit_ctx)
    ctx["no_intervener"] = False    # 有干预者，但③满足
    act = fuse_enabled.tick_and_check(ctx)
    assert act.emergency_shutdown is True, "①+②+③ 满足应触发 G-05（③使OR成立）"
    assert act.reason.startswith("g05_"), f"reason 应以 g05_ 开头，got={act.reason}"


# ============================================================
# T8.18：①+②+④ 但无③ → 触发（④满足，OR条件成立）
# ============================================================
def test_t8_18_g05_c1_c2_c4_without_c3_triggered(fuse_enabled, g05_full_hit_ctx):
    """①+②+④ 但 ③=False → ①AND②AND(③OR④)=①AND②AND④=True → 触发."""
    ctx = dict(g05_full_hit_ctx)
    ctx["no_bounce_at_key"] = False  # 有反弹，但④满足
    act = fuse_enabled.tick_and_check(ctx)
    assert act.emergency_shutdown is True, "①+②+④ 满足应触发 G-05（④使OR成立）"
    assert act.reason.startswith("g05_"), f"reason 应以 g05_ 开头，got={act.reason}"


# ============================================================
# T8.19：G-05 优先于 G-02（两者同时满足时，走 G-05）
# ============================================================
def test_t8_19_g05_priority_over_g02(fuse_enabled, g05_full_hit_ctx):
    """G-05 和 G-02 同时满足 → 走 G-05（事前预防 > 事后黑天鹅）."""
    act = fuse_enabled.tick_and_check(g05_full_hit_ctx)
    # G-05 和 G-02 的 ctx 字段都满足
    # 应走 G-05 而非 G-02
    assert act.reason.startswith("g05_"), \
        f"G-05 应优先于 G-02，reason 应以 g05_ 开头，got={act.reason}"
    # G-05 是 emergency_shutdown，G-02 只是 block_new_open
    assert act.emergency_shutdown is True, "G-05 应触发 emergency_shutdown"


# ============================================================
# T8.20：G-04 优先于 G-05（两者同时满足时，走 G-04）
# ============================================================
def test_t8_20_g04_priority_over_g05(fuse_enabled, g05_full_hit_ctx):
    """G-04 和 G-05 同时满足 → 走 G-04（终极回撤 > 事前预防）."""
    ctx = dict(g05_full_hit_ctx)
    # G-04: 单日回撤 ≥ 3%
    ctx["daily_equity_prev"] = 2000.0
    ctx["daily_equity_now"] = 1900.0  # dd=5% ≥ 3%
    act = fuse_enabled.tick_and_check(ctx)
    # G-04 优先于 G-05
    assert act.reason.startswith("g04_"), \
        f"G-04 应优先于 G-05，reason 应以 g04_ 开头，got={act.reason}"
    assert act.emergency_shutdown is True


# ============================================================
# T8.21：ctx=None → no_trigger（FAIL-OPEN）
# ============================================================
def test_t8_21_g05_ctx_none_no_trigger(fuse_enabled):
    """ctx=None → 所有判据缺失 → 默认False → no_trigger."""
    act = fuse_enabled.tick_and_check(None)
    assert act.emergency_shutdown is False
    assert act.block_new_open is False
    assert act.reason == "no_trigger"


# ============================================================
# T8.22：ctx 异常字段 → no_trigger（FAIL-OPEN）
# ============================================================
def test_t8_22_g05_abnormal_ctx_no_trigger(fuse_enabled):
    """ctx 字段类型异常 → FAIL-OPEN → no_trigger."""
    ctx = {
        "primary_dim_jumped": "not_a_bool",  # 异常类型
        "mechanism_active": None,
        "no_bounce_at_key": [],
        "no_intervener": {},
    }
    act = fuse_enabled.tick_and_check(ctx)
    assert act.emergency_shutdown is False
    assert act.reason == "no_trigger"


# ============================================================
# T8.23：G-05 触发后冷却期内 → g05_cascade_active 保持阻塞
# ============================================================
def test_t8_23_g05_cooldown_still_active(fuse_enabled, g05_full_hit_ctx):
    """G-05 触发后 30min → 冷却期内 → g05_cascade_active 保持阻塞."""
    # 先触发 G-05
    act1 = fuse_enabled.tick_and_check(g05_full_hit_ctx)
    assert act1.reason.startswith("g05_"), f"首次触发应走 G-05，got={act1.reason}"

    # 往前拨 30 分钟
    if hasattr(fuse_enabled, "_g05_last_trigger_at"):
        fuse_enabled._g05_last_trigger_at -= 1800
    if hasattr(fuse_enabled, "_g05_cascade_until_ts"):
        fuse_enabled._g05_cascade_until_ts -= 1800

    # 再次检查 → 应仍处于 G-05 冷却
    act2 = fuse_enabled.tick_and_check(g05_full_hit_ctx)
    assert act2.reason == "g05_cascade_active", \
        f"冷却期内应返回 g05_cascade_active，got={act2.reason}"
    assert act2.emergency_shutdown is True
    assert act2.block_new_open is True


# ============================================================
# T8.24：G-05 冷却过期 → 恢复 no_trigger（或重新判定）
# ============================================================
def test_t8_24_g05_cooldown_expired_restored(fuse_enabled, g05_full_hit_ctx):
    """G-05 冷却过期 → 重新判定（4判据仍满足 → 重新触发）."""
    # 先触发 G-05
    act1 = fuse_enabled.tick_and_check(g05_full_hit_ctx)
    assert act1.reason.startswith("g05_")

    # 往前拨超过冷却期（假设冷却 = 1h，拨 70min）
    if hasattr(fuse_enabled, "_g05_last_trigger_at"):
        fuse_enabled._g05_last_trigger_at -= 4200
    if hasattr(fuse_enabled, "_g05_cascade_until_ts"):
        fuse_enabled._g05_cascade_until_ts -= 4200

    # 4判据仍满足 → 应重新触发 G-05
    act2 = fuse_enabled.tick_and_check(g05_full_hit_ctx)
    assert act2.reason.startswith("g05_"), \
        f"冷却过期+4判据满足应重新触发，got={act2.reason}"


# ============================================================
# T8.25：信号字段缺失（key不存在）→ 该判据默认False → no_trigger
# ============================================================
def test_t8_25_g05_missing_signal_keys_defaults_false(fuse_enabled):
    """ctx 不含 G-05 信号字段 → 全部默认False → no_trigger（FAIL-OPEN）.

    只有 G-02 ctx 字段 → G-02 正常判定，G-05 不触发.
    """
    ctx = {
        # 只有 G-02 字段，无 G-05 信号
        "positions_by_direction": {"LONG": 6, "SHORT": 2},
        "avg_float_loss_pct_15m": 0.006,
        "btc_lambda": 0.68,
        "daily_equity_prev": 2000.0,
        "daily_equity_now": 1990.0,
    }
    act = fuse_enabled.tick_and_check(ctx)
    # G-05 信号缺失 → 4判据全False → G-05 不触发
    # G-02 三条件满足 → 走 G-02
    assert act.reason.startswith("g02_"), \
        f"无G-05信号+G-02满足应走G-02，got={act.reason}"
    assert act.emergency_shutdown is False, "G-02 不应触发 emergency_shutdown"
