"""
方案 C v3.0 Task 6：BTCSelfReflexValve TDD 测试（12 项）
=======================================================
TDD RED 阶段：验证 BTC 自反调控闸门的 5 重门槛 + λ 公式 + 冷却/单日 cap。

测试清单（共 12 项）：
  T6.01：非 BTC 币种 / 非 LONG 方向 → 零惩罚 λ=1.0
  T6.02：enable=False 或 ctx=None → fail-open λ=1.0
  T6.03：P9 ① D_PE ≤ 0 → skip（不惩罚）
  T6.04：P9 ② BCRM BTC DOWN 连续性 < ALIGN_BASIC → skip
  T6.05：P9 ③ S_BTC_only < 0.60 → skip
  T6.06：P9 ④ 成交率 n_rev/n_windows < 60% → skip
  T6.07：P9 ⑤ 24h 内 fuse_blocked → skip
  T6.08：5 门槛全命中 → λ ∈ [0.60, 1.0]，reason="applied"
  T6.09：λ 公式精确验证：n_rev=3, s_bcrm=0.80 → λ=0.68
  T6.10：n_rev 冷却 30 分钟：30 分钟内再次调用复用上次 λ
  T6.11：单日惩罚上限 P9=0.70：累计 > 0.70 时不再额外惩罚
  T6.12：异常 ctx 触发 fail-open → λ=1.0，reason 带 fail_open: 前缀
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
def valve_enabled():
    from scripts.memory_l4.btc_self_reflex_valve import BTCSelfReflexValve
    v = BTCSelfReflexValve(enable=True)
    # 重置冷却和单日状态，避免测试间耦合
    v._state.last_n_rev_ts = 0.0
    v._state.last_trade_date = ""
    v._state.last_daily_penalty_acc = 0.0
    return v


@pytest.fixture
def full_hit_ctx():
    """P9 五门槛全命中的标准上下文"""
    return {
        "symbol": "BTCUSDT",
        "direction": "LONG",
        "d_pe_sign": +1,
        "btc_cont_grade": "ALIGN_BASIC",
        "s_btc_only": 0.65,
        "n_rev": 5,
        "n_windows": 7,           # 5/7 = 71.4% ≥ 60%
        "s_bcrm_global": 0.75,
        "fuse_blocked_24h": False,
    }


# ============================================================
# T6.01：非 BTC / 非 LONG → λ=1.0
# ============================================================
def test_t6_01_skip_non_btc_long(valve_enabled):
    """ETH LONG / BTC SHORT 都应该跳过，返回 λ=1.0"""
    # ETH 多头
    lam, sh = valve_enabled.get_lambda({
        "symbol": "ETHUSDT", "direction": "LONG",
        "d_pe_sign": +1, "btc_cont_grade": "ALIGN_FULL",
        "s_btc_only": 0.80, "n_rev": 7, "n_windows": 7,
        "s_bcrm_global": 0.90, "fuse_blocked_24h": False,
    })
    assert abs(lam - 1.0) < 1e-9 and sh["reason"].startswith("skip_")

    # BTC 空头（方向不对）
    lam2, sh2 = valve_enabled.get_lambda({
        "symbol": "BTC", "direction": "SHORT",
        "d_pe_sign": +1, "btc_cont_grade": "ALIGN_FULL",
        "s_btc_only": 0.80, "n_rev": 7, "n_windows": 7,
        "s_bcrm_global": 0.90, "fuse_blocked_24h": False,
    })
    assert abs(lam2 - 1.0) < 1e-9 and sh2["reason"].startswith("skip_")


# ============================================================
# T6.02：ctx=None → fail-open（因为 ctx={} 然后 "BTC" not in ""）
# ============================================================
# T6.02：ctx=None → skip（symbol/方向空，reason=skip_non_btc_long, λ=1.0）
def test_t6_02_ctx_none_failopen(valve_enabled):
    """ctx=None → ctx={} → symbol=""/direction="" → skip_non_btc_long λ=1.0"""
    lam, sh = valve_enabled.get_lambda(None)
    assert abs(lam - 1.0) < 1e-9
    assert sh["reason"] == "skip_non_btc_long"
    assert sh.get("symbol") == "" and sh.get("direction") == ""


# ============================================================
# T6.03：P9 ① D_PE ≤ 0 → skip
# ============================================================
def test_t6_03_p9_1_dpe_not_positive(valve_enabled, full_hit_ctx):
    full_hit_ctx["d_pe_sign"] = 0
    lam, sh = valve_enabled.get_lambda(full_hit_ctx)
    assert abs(lam - 1.0) < 1e-9
    assert "g1_dpe_not_positive" == sh["reason"]
    full_hit_ctx["d_pe_sign"] = -1
    lam2, sh2 = valve_enabled.get_lambda(full_hit_ctx)
    assert abs(lam2 - 1.0) < 1e-9 and "g1_" in sh2["reason"]


# ============================================================
# T6.04：P9 ② 连续性 < ALIGN_BASIC → skip
# ============================================================
def test_t6_04_p9_2_cont_below_align_basic(valve_enabled, full_hit_ctx):
    for g in ["NEUTRAL", "DIVERGE_BASIC", "DIVERGE_SEVERE"]:
        full_hit_ctx["btc_cont_grade"] = g
        lam, sh = valve_enabled.get_lambda(full_hit_ctx)
        assert abs(lam - 1.0) < 1e-9, f"{g} 应该 skip，得到 λ={lam}"
        assert "g2_cont_not_align_basic" == sh["reason"]


# ============================================================
# T6.05：P9 ③ S_BTC_only < 0.60 → skip
# ============================================================
def test_t6_05_p9_3_s_btc_below_threshold(valve_enabled, full_hit_ctx):
    from scripts.memory_l4 import phase_c_constants as C
    full_hit_ctx["s_btc_only"] = 0.59  # 刚好差一点到 0.60
    lam, sh = valve_enabled.get_lambda(full_hit_ctx)
    assert abs(lam - 1.0) < 1e-9
    assert "g3_s_btc_below" in sh["reason"]
    # 刚好 = 0.60，应该放行（命中门槛）
    full_hit_ctx["s_btc_only"] = C.P9_BTC_S_BTC_ONLY_MIN
    lam2, sh2 = valve_enabled.get_lambda(full_hit_ctx)
    # 不应再因为 g3 skip（可能 applied 或其他 g，但不是 g3）
    assert "g3_s_btc" not in sh2["reason"]


# ============================================================
# T6.06：P9 ④ 成交率 < 60% → skip
# ============================================================
def test_t6_06_p9_4_fill_ratio_below_60pct(valve_enabled, full_hit_ctx):
    full_hit_ctx["n_rev"] = 3
    full_hit_ctx["n_windows"] = 7  # 3/7 = 42.9% < 60%
    lam, sh = valve_enabled.get_lambda(full_hit_ctx)
    assert abs(lam - 1.0) < 1e-9
    assert "g4_fill_ratio" in sh["reason"]
    # 刚好 = 0.60：n_windows=10, n_rev=6 → 放行
    full_hit_ctx["n_rev"] = 6
    full_hit_ctx["n_windows"] = 10
    lam2, sh2 = valve_enabled.get_lambda(full_hit_ctx)
    assert "g4_fill_ratio" not in sh2["reason"]


# ============================================================
# T6.07：P9 ⑤ 24h 熔断阻塞 → skip
# ============================================================
def test_t6_07_p9_5_fuse_blocked_24h(valve_enabled, full_hit_ctx):
    full_hit_ctx["fuse_blocked_24h"] = True
    lam, sh = valve_enabled.get_lambda(full_hit_ctx)
    assert abs(lam - 1.0) < 1e-9
    assert sh["reason"] == "g5_fuse_blocked_24h"


# ============================================================
# T6.08：5 门槛全命中 → λ ∈ [0.60, 1.0]，reason=applied
# ============================================================
def test_t6_08_all_five_hit_applied(valve_enabled, full_hit_ctx):
    from scripts.memory_l4 import phase_c_constants as C
    lam, sh = valve_enabled.get_lambda(full_hit_ctx)
    assert C.BTC_REFLEX_LAMBDA_LOW - 1e-9 <= lam <= C.BTC_REFLEX_LAMBDA_HIGH + 1e-9
    assert sh["reason"] == "applied"
    assert "penalty" in sh and "lambda_final" in sh


# ============================================================
# T6.09：λ 公式精确验证
# ============================================================
def test_t6_09_lambda_formula_precision(valve_enabled, full_hit_ctx):
    """
    n_rev=3, s_bcrm=0.80:
      n_factor = min(1, 3/3) = 1.0
      penalty = 0.40 * 1.0 * 0.80 = 0.32
      λ = 1 - 0.32 = 0.68 ∈ [0.60, 1.0] ✓
    """
    full_hit_ctx["n_rev"] = 3
    full_hit_ctx["s_bcrm_global"] = 0.80
    full_hit_ctx["n_windows"] = 5  # 3/5 = 0.60 刚好命中门槛
    lam, sh = valve_enabled.get_lambda(full_hit_ctx)
    assert abs(lam - 0.68) < 1e-6, (
        f"λ={lam:.8f} 预期 0.68，sh={sh}"
    )
    assert abs(sh["penalty"] - 0.32) < 1e-6


# ============================================================
# T6.10：n_rev 冷却 30 分钟
# ============================================================
def test_t6_10_cooldown_30min_reuse_last(valve_enabled, full_hit_ctx):
    """第 1 次算 λ1；第 2 次 30 分钟内不同参数也返回 λ1"""
    full_hit_ctx["n_rev"] = 3
    full_hit_ctx["s_bcrm_global"] = 0.80
    full_hit_ctx["n_windows"] = 5
    lam1, sh1 = valve_enabled.get_lambda(full_hit_ctx)
    assert sh1["reason"] == "applied"
    # 立即第二次调用（ctx 改得更强，但冷却未过 → 复用 λ1 + cooldown reason）
    ctx2 = dict(full_hit_ctx)
    ctx2["n_rev"] = 6
    ctx2["s_bcrm_global"] = 0.99
    lam2, sh2 = valve_enabled.get_lambda(ctx2)
    assert abs(lam2 - lam1) < 1e-9, "冷却期内应复用上次 λ"
    assert sh2["reason"].startswith("cooldown_remaining_")
    # 模拟冷却过期：把 last_n_rev_ts 往前拨 31 分钟
    valve_enabled._state.last_n_rev_ts -= 31 * 60
    lam3, sh3 = valve_enabled.get_lambda(ctx2)
    assert sh3["reason"] == "applied", "冷却过后应重新计算"
    # λ3 应该比 λ1 更低（惩罚更多，因为 n_rev=6, s_bcrm=0.99）
    assert lam3 < lam1, f"λ3={lam3:.6f} 应 < λ1={lam1:.6f}"


# ============================================================
# T6.11：单日惩罚上限 0.70
# ============================================================
def test_t6_11_daily_penalty_cap_070(valve_enabled, full_hit_ctx):
    """
    连续触发多次，累计 penalty 超过 P9_BTC_PENALTY_DAILY_CAP=0.70 时，
    后续惩罚不再累加，λ 不低于 1-0.70=0.30（实际 clip 到 0.60 更严）
    """
    from scripts.memory_l4 import phase_c_constants as C
    # 先让冷却立刻过期（每次都能 applied）
    full_hit_ctx["n_rev"] = 1
    full_hit_ctx["s_bcrm_global"] = 1.0
    full_hit_ctx["n_windows"] = 1
    # 每次 penalty = 0.40 * min(1, 1/3) * 1.0 = 0.40 * 0.333 = 0.1333
    # 连开 6 次：累计 = 0.80 → 超过 0.70 → 最后一次 penalty 受限
    last_lam = None
    for i in range(7):
        valve_enabled._state.last_n_rev_ts = 0  # 每次绕过冷却
        lam, sh = valve_enabled.get_lambda(full_hit_ctx)
        last_lam = lam
        # 每次命中
        assert sh["reason"] == "applied", f"第{i}次 reason={sh['reason']}"
    acc = valve_enabled._state.last_daily_penalty_acc
    # 单日累计 ≤ 0.70 + 浮点误差
    assert acc <= C.P9_BTC_PENALTY_DAILY_CAP + 1e-9, (
        f"单日累计 penalty={acc:.6f} > cap={C.P9_BTC_PENALTY_DAILY_CAP}"
    )
    # 最终 λ ≥ 1 - 0.70 = 0.30（但实际还会 clip 到 0.60，所以肯定 ≥ 0.60）
    assert last_lam >= C.BTC_REFLEX_LAMBDA_LOW - 1e-9


# ============================================================
# T6.12：异常 ctx → fail-open λ=1.0
# ============================================================
def test_t6_12_exception_failopen(valve_enabled):
    """ctx 中的字段类型错误导致异常 → fail-open 1.0"""
    bad_ctx = {
        "symbol": "BTCUSDT",
        "direction": "LONG",
        "d_pe_sign": "not_an_int",  # int() 会报错？不，int("not_an_int") 抛 ValueError
        "btc_cont_grade": "ALIGN_BASIC",
        "s_btc_only": 0.65,
        "n_rev": 5,
        "n_windows": 7,
        "s_bcrm_global": 0.75,
        "fuse_blocked_24h": False,
    }
    lam, sh = valve_enabled.get_lambda(bad_ctx)
    # ValueError → fail-open
    assert abs(lam - 1.0) < 1e-9
    assert str(sh.get("reason", "")).startswith("fail_open:")
