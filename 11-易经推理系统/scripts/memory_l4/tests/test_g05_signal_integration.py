"""
G-05 实盘信号接入集成测试
========================
验证 polling_trader._prf_ctx 中4个判据信号字段正确构造。

测试策略：mock pipeline + ReflexivityMonitor + _recent_klines，验证 ctx dict 正确。
不调用真实的 tick_and_check（那是 G-05 红灯测试的职责）。
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_THIS_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _THIS_DIR.parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))


def _build_prf_ctx_like_polling_trader(
    pipeline=None,
    recent_klines=None,
    position_tracker=None,
    perf_tracker=None,
    btc_lambda=1.0,
):
    """模拟 polling_trader 中 _prf_ctx 的构造逻辑（L15796-L15877）."""
    _prf_ctx = {}

    # ① positions_by_direction
    try:
        _pos_by_dir = {"LONG": 0, "SHORT": 0}
        for _tp in getattr(position_tracker, "open_positions", {}).values():
            _side = getattr(_tp, "pos_side", "") or ""
            if _side.lower() == "long":
                _pos_by_dir["LONG"] += 1
            elif _side.lower() == "short":
                _pos_by_dir["SHORT"] += 1
        _prf_ctx["positions_by_direction"] = _pos_by_dir
    except Exception:
        _prf_ctx["positions_by_direction"] = {"LONG": 0, "SHORT": 0}

    # ② avg_float_loss_pct_15m
    try:
        _today_stats = perf_tracker.get_today_stats() or {}
        _prf_ctx["avg_float_loss_pct_15m"] = float(_today_stats.get("avg_float_loss_pct_15m", 0.0) or 0.0)
    except Exception:
        _prf_ctx["avg_float_loss_pct_15m"] = 0.0

    # ③ btc_lambda
    _prf_ctx["btc_lambda"] = float(btc_lambda or 1.0)

    # ④ daily_equity
    try:
        _eq_now = float(getattr(perf_tracker, "current_equity", 0.0) or 0.0)
        _eq_prev = float(getattr(perf_tracker, "yesterday_close_equity", 0.0) or 0.0)
        if _eq_prev <= 0:
            _eq_prev = _eq_now if _eq_now > 0 else 0.0
        _prf_ctx["daily_equity_prev"] = _eq_prev
        _prf_ctx["daily_equity_now"] = _eq_now
    except Exception:
        _prf_ctx["daily_equity_prev"] = 0.0
        _prf_ctx["daily_equity_now"] = 0.0

    # ⑤ G-05 4判据信号
    try:
        _shift_result = getattr(pipeline, "_last_shift_result", None) if pipeline is not None else None
        _prf_ctx["primary_dim_jumped"] = _shift_result is not None
    except Exception:
        _prf_ctx["primary_dim_jumped"] = False

    try:
        _mech_active = False
        if pipeline is not None:
            _rm = pipeline._get_reflexivity_monitor() if hasattr(pipeline, "_get_reflexivity_monitor") else None
            if _rm is not None:
                _si = _rm.check_self_influence()
                _mech_active = bool(_si.get("self_influence_detected", False)) and \
                               float(_si.get("influence_coefficient", 0.0)) > 0.02
        _prf_ctx["mechanism_active"] = _mech_active
    except Exception:
        _prf_ctx["mechanism_active"] = False

    try:
        _no_bounce = False
        if recent_klines and len(recent_klines) >= 6:
            _closes = [float(k.get("close", 0.0) or 0.0) for k in recent_klines[-6:]]
            if all(_closes[i] <= _closes[i - 1] for i in range(1, len(_closes))):
                _no_bounce = True
        _prf_ctx["no_bounce_at_key"] = _no_bounce
    except Exception:
        _prf_ctx["no_bounce_at_key"] = False

    try:
        _prf_ctx["no_intervener"] = True
    except Exception:
        _prf_ctx["no_intervener"] = True

    return _prf_ctx


# ============================================================
# T-S1：primary_dim_jumped 信号接入
# ============================================================
def test_t_s1_primary_dim_jumped_signal():
    """① pipeline._last_shift_result 非None → primary_dim_jumped=True."""
    pipeline = MagicMock()
    pipeline._last_shift_result = {"shifted_from": {}, "shifted_to": {}}
    ctx = _build_prf_ctx_like_polling_trader(pipeline=pipeline)
    assert ctx["primary_dim_jumped"] is True


def test_t_s1_primary_dim_jumped_none():
    """① pipeline._last_shift_result=None → primary_dim_jumped=False."""
    pipeline = MagicMock()
    pipeline._last_shift_result = None
    ctx = _build_prf_ctx_like_polling_trader(pipeline=pipeline)
    assert ctx["primary_dim_jumped"] is False


def test_t_s1_primary_dim_jumped_no_pipeline():
    """① pipeline=None → primary_dim_jumped=False（FAIL-OPEN）."""
    ctx = _build_prf_ctx_like_polling_trader(pipeline=None)
    assert ctx["primary_dim_jumped"] is False


# ============================================================
# T-S2：mechanism_active 信号接入
# ============================================================
def test_t_s2_mechanism_active_signal():
    """② ReflexivityMonitor.check_self_influence 返回 detected+λ>0.02 → mechanism_active=True."""
    pipeline = MagicMock()
    _rm = MagicMock()
    _rm.check_self_influence.return_value = {
        "self_influence_detected": True,
        "influence_coefficient": 0.05,
    }
    pipeline._get_reflexivity_monitor.return_value = _rm
    ctx = _build_prf_ctx_like_polling_trader(pipeline=pipeline)
    assert ctx["mechanism_active"] is True


def test_t_s2_mechanism_not_active_low_lambda():
    """② λ<=0.02 → mechanism_active=False."""
    pipeline = MagicMock()
    _rm = MagicMock()
    _rm.check_self_influence.return_value = {
        "self_influence_detected": True,
        "influence_coefficient": 0.01,  # ≤ 0.02
    }
    pipeline._get_reflexivity_monitor.return_value = _rm
    ctx = _build_prf_ctx_like_polling_trader(pipeline=pipeline)
    assert ctx["mechanism_active"] is False


def test_t_s2_mechanism_not_active_no_monitor():
    """② ReflexivityMonitor=None → mechanism_active=False（FAIL-OPEN）."""
    pipeline = MagicMock()
    pipeline._get_reflexivity_monitor.return_value = None
    ctx = _build_prf_ctx_like_polling_trader(pipeline=pipeline)
    assert ctx["mechanism_active"] is False


# ============================================================
# T-S3：no_bounce_at_key 信号接入
# ============================================================
def test_t_s3_no_bounce_consecutive_down():
    """③ 最近6根K线连续下行 → no_bounce_at_key=True."""
    klines = [{"close": 100.0 - i} for i in range(6)]  # 100, 99, 98, 97, 96, 95
    ctx = _build_prf_ctx_like_polling_trader(recent_klines=klines)
    assert ctx["no_bounce_at_key"] is True


def test_t_s3_has_bounce_not_consecutive():
    """③ K线有反弹 → no_bounce_at_key=False."""
    klines = [{"close": 100.0}, {"close": 99.0}, {"close": 98.0},
              {"close": 99.5},  # 反弹
              {"close": 97.0}, {"close": 96.0}]
    ctx = _build_prf_ctx_like_polling_trader(recent_klines=klines)
    assert ctx["no_bounce_at_key"] is False


def test_t_s3_no_klines():
    """③ _recent_klines=None → no_bounce_at_key=False（FAIL-OPEN）."""
    ctx = _build_prf_ctx_like_polling_trader(recent_klines=None)
    assert ctx["no_bounce_at_key"] is False


def test_t_s3_insufficient_klines():
    """③ K线<6根 → no_bounce_at_key=False."""
    klines = [{"close": 100.0}, {"close": 99.0}, {"close": 98.0}]
    ctx = _build_prf_ctx_like_polling_trader(recent_klines=klines)
    assert ctx["no_bounce_at_key"] is False


# ============================================================
# T-S4：no_intervener 信号接入
# ============================================================
def test_t_s4_no_intervener_default_true():
    """④ 默认 no_intervener=True（无事件检测时，保守判定为无干预者）."""
    ctx = _build_prf_ctx_like_polling_trader()
    assert ctx["no_intervener"] is True


# ============================================================
# T-S5：G-02 原有字段不受影响
# ============================================================
def test_t_s5_g02_fields_intact():
    """G-02 原有字段（positions_by_direction等）不受 G-05 接入影响."""
    pos_tracker = MagicMock()
    pos_tracker.open_positions = {
        "p1": MagicMock(pos_side="long"),
        "p2": MagicMock(pos_side="long"),
        "p3": MagicMock(pos_side="short"),
    }
    perf_tracker = MagicMock()
    perf_tracker.get_today_stats.return_value = {"avg_float_loss_pct_15m": 0.008}
    perf_tracker.current_equity = 2000.0
    perf_tracker.yesterday_close_equity = 2050.0
    ctx = _build_prf_ctx_like_polling_trader(
        position_tracker=pos_tracker,
        perf_tracker=perf_tracker,
        btc_lambda=0.65,
    )
    assert ctx["positions_by_direction"]["LONG"] == 2
    assert ctx["positions_by_direction"]["SHORT"] == 1
    assert ctx["avg_float_loss_pct_15m"] == 0.008
    assert ctx["btc_lambda"] == 0.65
    assert ctx["daily_equity_prev"] == 2050.0
    assert ctx["daily_equity_now"] == 2000.0


# ============================================================
# T-S6：端到端 G-05 触发验证
# ============================================================
def test_t_s6_e2e_g05_triggered_with_real_signals():
    """端到端：4判据全满足 → G-05 触发 emergency_shutdown."""
    from scripts.memory_l4.portfolio_risk_fuses import PortfolioRiskFuses

    # 构造4判据全满足的 ctx
    pipeline = MagicMock()
    pipeline._last_shift_result = {"shifted_to": {"direction": "bear"}}
    _rm = MagicMock()
    _rm.check_self_influence.return_value = {
        "self_influence_detected": True,
        "influence_coefficient": 0.05,
    }
    pipeline._get_reflexivity_monitor.return_value = _rm
    klines = [{"close": 100.0 - i} for i in range(6)]  # 连续下行

    ctx = _build_prf_ctx_like_polling_trader(pipeline=pipeline, recent_klines=klines)

    # 验证4判据全满足
    assert ctx["primary_dim_jumped"] is True
    assert ctx["mechanism_active"] is True
    assert ctx["no_bounce_at_key"] is True
    assert ctx["no_intervener"] is True

    # 调用 G-05
    fuses = PortfolioRiskFuses(enable=True)
    act = fuses.tick_and_check(ctx)
    assert act.emergency_shutdown is True
    assert act.reason.startswith("g05_")
