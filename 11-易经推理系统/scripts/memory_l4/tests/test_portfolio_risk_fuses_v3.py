"""
方案 C v3.0 Task 8：PortfolioRiskFuses TDD 测试（12 项）
======================================================
TDD RED 阶段：验证组合级熔断（G-02 黑天鹅 3 条件 + G-04 终极 3% 回撤）。

测试清单（共 12 项）：
  T8.01：ctx=None → no_trigger 默认无熔断；enable 不影响 fail-safe 默认
  T8.02：G-02 三条件缺一 → 不触发（cond1/cond2/cond3 各自缺失测试）
  T8.03：G-02 三条件全中 → 触发 block_new_open=True, SL×0.90, TP×1.05, 冷却 1h
  T8.04：G-02 冷却期内（30min 后）仍 g02_cooldown 阻塞；SL/TP 继续生效
  T8.05：G-02 冷却过期（70min > 1h）→ 恢复 no_trigger
  T8.06：G-04 单日权益回撤 ≥ 3% → emergency_shutdown=True，关断 24h
  T8.07：G-04 未到期（差 1s / 差 12h）→ g04_emergency_active 保持阻塞
  T8.08：G-04 24h 过期 → 恢复 no_trigger；新 G-02 可以触发
  T8.09：G-04 优先级高于 G-02（两个同时满足时，优先走 G-04）
  T8.10：异常 ctx → fail_open:*，无熔断（block=False/sl=1.0/tp=1.0）
  T8.11：阈值边界：G-02 cond2=0.50%刚好命中；0.499%不命中；G-04 dd=0.03刚好；0.0299不命中
  T8.12：FuseAction.as_shadow_dict() 字段完整性 + ISO 日期格式
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
    from scripts.memory_l4.portfolio_risk_fuses import PortfolioRiskFuses
    f = PortfolioRiskFuses(enable=True)
    f._g02_block_until_ts = 0.0
    f._g02_last_trigger_at = 0.0
    f._g04_emergency_until_ts = 0.0
    f._g04_last_trigger_at = 0.0
    return f


@pytest.fixture
def g02_full_hit_ctx():
    """G-02 三条件全中：同方向≥5、浮亏≥0.50%、BTC λ≤0.75"""
    return {
        "positions_by_direction": {"LONG": 6, "SHORT": 2},  # max=6 ≥ 5
        "avg_float_loss_pct_15m": 0.006,  # 0.60% ≥ 0.50%
        "btc_lambda": 0.68,  # ≤ 0.75
        "daily_equity_prev": 2000.0,
        "daily_equity_now": 1990.0,  # dd=(2000-1990)/2000=0.5% < 3%，不触发 G-04
    }


# ============================================================
# T8.01：ctx=None → no_trigger
# ============================================================
def test_t8_01_ctx_none_no_trigger(fuse_enabled):
    act = fuse_enabled.tick_and_check(None)
    assert act.block_new_open is False
    assert abs(act.sl_mult_adj - 1.0) < 1e-9
    assert abs(act.tp_mult_adj - 1.0) < 1e-9
    assert act.emergency_shutdown is False
    assert act.reason == "no_trigger"


# ============================================================
# T8.02：G-02 三条件缺一 → 不触发
# ============================================================
def test_t8_02_g02_missing_one_condition(fuse_enabled, g02_full_hit_ctx):
    from scripts.memory_l4 import phase_c_constants as C
    # 缺 cond1：LONG=4 < 5
    c1 = dict(g02_full_hit_ctx)
    c1["positions_by_direction"] = {"LONG": 4, "SHORT": 2}
    a1 = fuse_enabled.tick_and_check(c1)
    assert a1.reason == "no_trigger", f"缺 cond1 不应触发，reason={a1.reason}"

    # 缺 cond2：浮亏 0.004（0.40%）< 0.50%
    c2 = dict(g02_full_hit_ctx)
    c2["avg_float_loss_pct_15m"] = 0.004
    a2 = fuse_enabled.tick_and_check(c2)
    assert a2.reason == "no_trigger", f"缺 cond2 不应触发，reason={a2.reason}"

    # 缺 cond3：λ=0.80 > 0.75
    c3 = dict(g02_full_hit_ctx)
    c3["btc_lambda"] = 0.80
    a3 = fuse_enabled.tick_and_check(c3)
    assert a3.reason == "no_trigger", f"缺 cond3 不应触发，reason={a3.reason}"


# ============================================================
# T8.03：G-02 三条件全中 → 触发
# ============================================================
def test_t8_03_g02_all_three_hit_triggered(fuse_enabled, g02_full_hit_ctx):
    from scripts.memory_l4 import phase_c_constants as C
    act = fuse_enabled.tick_and_check(g02_full_hit_ctx)
    assert act.block_new_open is True
    assert abs(act.sl_mult_adj - C.G02_SL_MULT_ADJ) < 1e-9  # 0.90
    assert abs(act.tp_mult_adj - C.G02_TP_MULT_ADJ) < 1e-9  # 1.05
    assert act.emergency_shutdown is False
    assert act.reason.startswith("g02_triggered_")
    # 冷却 = 1h = 3600s
    assert abs((act.block_until_ts - act.trigger_at_ts) - C.G02_BLOCK_NEW_OPEN_SECONDS) < 1e-3


# ============================================================
# T8.04：G-02 冷却期内（30min 后）仍 g02_cooldown
# ============================================================
def test_t8_04_g02_cooldown_30min_still_block(fuse_enabled, g02_full_hit_ctx):
    # 先触发
    act1 = fuse_enabled.tick_and_check(g02_full_hit_ctx)
    assert act1.reason.startswith("g02_triggered_")
    # 往前拨 30 分钟（1800 秒）
    fuse_enabled._g02_last_trigger_at -= 1800
    fuse_enabled._g02_block_until_ts -= 1800
    # 再查 → cooldown
    act2 = fuse_enabled.tick_and_check(g02_full_hit_ctx)
    assert act2.reason == "g02_cooldown"
    assert act2.block_new_open is True
    # sl/tp 仍然生效（0.90/1.05）
    from scripts.memory_l4 import phase_c_constants as C
    assert abs(act2.sl_mult_adj - C.G02_SL_MULT_ADJ) < 1e-9
    assert abs(act2.tp_mult_adj - C.G02_TP_MULT_ADJ) < 1e-9


# ============================================================
# T8.05：G-02 冷却过期（> 1h）→ 风险条件已解除 → 恢复 no_trigger
# ============================================================
def test_t8_05_g02_cooldown_expired(fuse_enabled, g02_full_hit_ctx):
    act1 = fuse_enabled.tick_and_check(g02_full_hit_ctx)
    assert act1.block_new_open is True
    # 往前拨 70 分钟（4200s > 3600s）
    fuse_enabled._g02_last_trigger_at -= 4200
    fuse_enabled._g02_block_until_ts -= 4200
    # 风险条件解除：LONG 减仓到 2（cond1 不满足），浮亏收敛到 0.30%
    recovered_ctx = dict(g02_full_hit_ctx)
    recovered_ctx["positions_by_direction"] = {"LONG": 2, "SHORT": 1}  # max=2 < 5
    recovered_ctx["avg_float_loss_pct_15m"] = 0.003  # 0.30% < 0.50%
    # 再查 → no_trigger（冷却过期 + 风险解除）
    act2 = fuse_enabled.tick_and_check(recovered_ctx)
    assert act2.reason == "no_trigger"
    assert act2.block_new_open is False


# ============================================================
# T8.06：G-04 单日回撤 ≥ 3% → 触发 emergency
# ============================================================
def test_t8_06_g04_dd_ge_3pct_trigger(fuse_enabled):
    from scripts.memory_l4 import phase_c_constants as C
    # prev=2000, now=1930 → dd=70/2000=0.035 ≥ 0.03
    ctx = {
        "positions_by_direction": {"LONG": 1, "SHORT": 0},
        "avg_float_loss_pct_15m": 0.0,
        "btc_lambda": 1.0,
        "daily_equity_prev": 2000.0,
        "daily_equity_now": 1930.0,  # 3.5% 回撤
    }
    act = fuse_enabled.tick_and_check(ctx)
    assert act.block_new_open is True
    assert act.emergency_shutdown is True
    # 关断 24h
    dd_expected = (2000.0 - 1930.0) / 2000.0  # 0.035
    assert C.G04_DAILY_DRAWDOWN_THRESHOLD <= dd_expected
    assert abs((act.block_until_ts - act.trigger_at_ts) - C.G04_SHUTDOWN_HOURS * 3600) < 1
    assert "g04_dd_" in act.reason


# ============================================================
# T8.07：G-04 未到期 → 一直阻塞
# ============================================================
def test_t8_07_g04_within_24h_blocked(fuse_enabled):
    # 先触发 G-04
    ctx = {
        "daily_equity_prev": 2000.0, "daily_equity_now": 1930.0,
    }
    act1 = fuse_enabled.tick_and_check(ctx)
    assert act1.emergency_shutdown is True
    # 往前拨 12h
    fuse_enabled._g04_emergency_until_ts -= 12 * 3600
    fuse_enabled._g04_last_trigger_at -= 12 * 3600
    act2 = fuse_enabled.tick_and_check({"daily_equity_prev": 2000, "daily_equity_now": 2000})
    # 就算现在权益好了，还是被熔断（24h 内）
    assert act2.reason == "g04_emergency_active"
    assert act2.emergency_shutdown is True
    assert act2.block_new_open is True


# ============================================================
# T8.08：G-04 24h 过期 → 恢复；新 G-02 可触发
# ============================================================
def test_t8_08_g04_24h_expired_then_recover(fuse_enabled, g02_full_hit_ctx):
    from scripts.memory_l4 import phase_c_constants as C
    # 触发 G-04
    fuse_enabled.tick_and_check({
        "daily_equity_prev": 2000.0, "daily_equity_now": 1930.0,
    })
    # 往前拨 24h + 1s
    fuse_enabled._g04_emergency_until_ts -= C.G04_SHUTDOWN_HOURS * 3600 + 1
    fuse_enabled._g04_last_trigger_at -= C.G04_SHUTDOWN_HOURS * 3600 + 1
    # 先查：现在权益正常 → no_trigger
    act_n = fuse_enabled.tick_and_check({
        "daily_equity_prev": 2000, "daily_equity_now": 1995,
    })
    assert act_n.reason == "no_trigger"
    # 然后 G-02 三条件全中 → 应该能触发（不再被 G-04 挡住）
    act_g02 = fuse_enabled.tick_and_check(g02_full_hit_ctx)
    assert act_g02.reason.startswith("g02_triggered_")


# ============================================================
# T8.09：G-04 优先级高于 G-02
# ============================================================
def test_t8_09_g04_priority_over_g02(fuse_enabled, g02_full_hit_ctx):
    """同时满足 G-02 和 G-04 → 优先 G-04（因为先检查 G-04，且返回 emergency）"""
    # 把 now 的权益做的非常低（满足 G-04），同时满足 G-02 三条件
    g02_full_hit_ctx["daily_equity_prev"] = 2000.0
    g02_full_hit_ctx["daily_equity_now"] = 1800.0  # dd = 10% ≥ 3%
    act = fuse_enabled.tick_and_check(g02_full_hit_ctx)
    assert act.emergency_shutdown is True  # G-04 的标志
    assert "g04_dd_" in act.reason  # 应该是 G-04 reason，不是 G-02


# ============================================================
# T8.10：异常 ctx → fail-open 无熔断
# ============================================================
def test_t8_10_exception_failopen(fuse_enabled):
    """positions_by_direction 传字符串 → max() 报错 → fail_open:*"""
    bad = {
        "positions_by_direction": "NOT_A_DICT",  # or {} 也行，但 .get 后 max(int(str), ...) 报错
        "avg_float_loss_pct_15m": 0.01,
        "btc_lambda": 0.50,
        "daily_equity_prev": 2000.0,
        "daily_equity_now": 1999.0,
    }
    act = fuse_enabled.tick_and_check(bad)
    # 无熔断：block=False, sl=1.0, tp=1.0, emergency=False
    assert act.block_new_open is False
    assert abs(act.sl_mult_adj - 1.0) < 1e-9
    assert abs(act.tp_mult_adj - 1.0) < 1e-9
    assert act.emergency_shutdown is False
    assert str(act.reason).startswith("fail_open:")


# ============================================================
# T8.11：阈值边界精确命中
# ============================================================
def test_t8_11_threshold_boundaries(fuse_enabled, g02_full_hit_ctx):
    from scripts.memory_l4 import phase_c_constants as C
    # ---- G-02 cond2 边界 ----
    # 刚好等于：0.50% = 0.0050
    c_exact = dict(g02_full_hit_ctx)
    c_exact["avg_float_loss_pct_15m"] = C.G02_AVG_FLOAT_LOSS_PCT  # 0.0050
    a_exact = fuse_enabled.tick_and_check(c_exact)
    # 三条件都满足，应该触发
    assert a_exact.reason.startswith("g02_triggered_"), (
        f"cond2 刚好命中 {C.G02_AVG_FLOAT_LOSS_PCT} 应触发，reason={a_exact.reason}"
    )
    # 重置 fuse（清除冷却）
    fuse_enabled._g02_block_until_ts = 0.0
    fuse_enabled._g02_last_trigger_at = 0.0
    # 差 0.0001% 不命中：0.0050 - 1e-6 = 0.004999
    c_below = dict(g02_full_hit_ctx)
    c_below["avg_float_loss_pct_15m"] = C.G02_AVG_FLOAT_LOSS_PCT - 1e-6
    a_below = fuse_enabled.tick_and_check(c_below)
    assert a_below.reason == "no_trigger", "差 1ppm 不应触发 G-02"

    # ---- G-04 dd 边界 ----
    # dd 刚好 = 0.03 → 命中
    dd_exact = {
        "daily_equity_prev": 10000.0,
        "daily_equity_now": 10000.0 * (1 - C.G04_DAILY_DRAWDOWN_THRESHOLD),  # exactly 0.03
    }
    fuse_enabled._g04_emergency_until_ts = 0.0
    fuse_enabled._g04_last_trigger_at = 0.0
    a_dd_exact = fuse_enabled.tick_and_check(dd_exact)
    assert a_dd_exact.emergency_shutdown is True, "dd=0.03 刚好命中 G-04"
    # dd = 0.0299 → 不命中
    fuse_enabled._g04_emergency_until_ts = 0.0
    fuse_enabled._g04_last_trigger_at = 0.0
    dd_below = {
        "daily_equity_prev": 10000.0,
        "daily_equity_now": 10000.0 * (1 - C.G04_DAILY_DRAWDOWN_THRESHOLD + 0.0001),  # 0.0299 < 0.03
    }
    a_dd_below = fuse_enabled.tick_and_check(dd_below)
    assert a_dd_below.emergency_shutdown is False, "dd=0.0299 < 0.03 不应触发 G-04"


# ============================================================
# T8.12：as_shadow_dict 字段完整性
# ============================================================
def test_t8_12_shadow_dict_fields(fuse_enabled, g02_full_hit_ctx):
    """触发 G-02 → as_shadow_dict 输出应包含 block/sl/tp/emergency/reason/time"""
    act = fuse_enabled.tick_and_check(g02_full_hit_ctx)
    d = act.as_shadow_dict()
    # 必填字段
    for k in ["block_new_open", "sl_mult_adj", "tp_mult_adj",
              "emergency_shutdown", "reason", "trigger_at", "block_until"]:
        assert k in d, f"shadow dict 缺少字段 {k}"
    # bool 类型
    assert isinstance(d["block_new_open"], bool)
    assert isinstance(d["emergency_shutdown"], bool)
    # ISO 格式：YYYY-MM-DDTHH（包含 T）
    assert "T" in d["trigger_at"] and len(d["trigger_at"]) >= 16
    assert "T" in d["block_until"] and len(d["block_until"]) >= 16
