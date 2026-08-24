"""V15 超时止盈 + 信号强度评估测试。

测试覆盖 _evaluate_signal_strength() 和 check_time_exit() 改造后的行为：

1. 信号强度评估：多头持仓时 Elder-ray 方向转弱 → 应判定为"信号弱化"
2. 信号强度评估：多头持仓时 Elder-ray 方向仍强 → 应判定为"信号仍强"
3. 超时+盈利+信号弱化 → 应直接止盈平仓（return True 触发平仓）
4. 超时+盈利+信号仍强 → 应提高止盈（return False，不触发平仓）
5. 超时+亏损 → 不评估信号，继续持有等反弹
6. 未超时 → 不触发任何操作
7. 止盈上限不超过 original_tp × 2.0
"""
import sys
import importlib
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

BASE_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(BASE_DIR / "lib"))
sys.path.insert(0, str(BASE_DIR / "core"))

from config_loader import load_config
load_config("v15")


# ── 信号强度评估函数的测试 ──────────────────────────────────────────


def test_signal_strong_when_elder_ray_aligned():
    """多头持仓 + Elder-ray STRONG_BULL → 信号仍强，不应触发止盈。"""
    from v15_trader import _evaluate_signal_strength

    # 多头持仓，Elder-ray 方向 STRONG_BULL，强度 80
    elder_ray = {
        "direction": "STRONG_BULL",
        "strength": 80,
        "ema_trend": "up",
        "bull_power": 10.5,
        "bear_power": 2.3,
        "both_weakening": False,
        "bull_out_of_control": False,
        "bear_out_of_control": False,
    }
    result = _evaluate_signal_strength(elder_ray, direction="LONG")
    assert result["signal_weak"] is False
    assert result["score"] >= 60


def test_signal_weak_when_elder_ray_reverses():
    """多头持仓 + Elder-ray BULL_REVERSAL → 信号弱化，应触发止盈。"""
    from v15_trader import _evaluate_signal_strength

    # 多头持仓，但 Elder-ray 出现逆转信号
    elder_ray = {
        "direction": "BULL_REVERSAL",
        "strength": 35,
        "ema_trend": "up",
        "bull_power": -1.2,  # Bull 转负 → 多头失控
        "bear_power": -3.5,
        "both_weakening": False,
        "bull_out_of_control": True,
        "bear_out_of_control": False,
    }
    result = _evaluate_signal_strength(elder_ray, direction="LONG")
    assert result["signal_weak"] is True
    assert result["score"] < 40


def test_signal_weak_when_both_weakening():
    """多头持仓 + 多空力量同时减弱 → 信号弱化。"""
    from v15_trader import _evaluate_signal_strength

    elder_ray = {
        "direction": "SIDEWAYS",
        "strength": 50,
        "ema_trend": "flat",
        "bull_power": 1.0,
        "bear_power": -1.0,
        "both_weakening": True,
        "bull_out_of_control": False,
        "bear_out_of_control": False,
    }
    result = _evaluate_signal_strength(elder_ray, direction="LONG")
    assert result["signal_weak"] is True


def test_signal_strong_for_short_position():
    """空头持仓 + Elder-ray STRONG_BEAR → 空头信号仍强。"""
    from v15_trader import _evaluate_signal_strength

    elder_ray = {
        "direction": "STRONG_BEAR",
        "strength": 20,
        "ema_trend": "down",
        "bull_power": -5.2,
        "bear_power": -3.1,
        "both_weakening": False,
        "bull_out_of_control": False,
        "bear_out_of_control": False,
    }
    # 空头持仓时，STRONG_BEAR 是方向一致的强信号
    result = _evaluate_signal_strength(elder_ray, direction="SHORT")
    assert result["signal_weak"] is False


def test_signal_weak_for_short_when_bear_reversal():
    """空头持仓 + Elder-ray BEAR_REVERSAL → 空头信号弱化。"""
    from v15_trader import _evaluate_signal_strength

    elder_ray = {
        "direction": "BEAR_REVERSAL",
        "strength": 60,
        "ema_trend": "down",
        "bull_power": -1.0,
        "bear_power": 2.5,  # Bear 转正 → 空头失控
        "both_weakening": False,
        "bull_out_of_control": False,
        "bear_out_of_control": True,
    }
    result = _evaluate_signal_strength(elder_ray, direction="SHORT")
    assert result["signal_weak"] is True


def test_signal_none_elder_ray_returns_weak():
    """Elder-ray 数据缺失时，默认保守判定为弱化。"""
    from v15_trader import _evaluate_signal_strength

    result = _evaluate_signal_strength(None, direction="LONG")
    assert result["signal_weak"] is True
    assert result["score"] == 0


# ── check_time_exit 集成测试 ──────────────────────────────────────


def _make_pos(entry_price=1200.0, direction="LONG", open_time_hours_ago=50,
              take_profit_pct=0.0985, original_tp_pct=0.0985, addons=0):
    """构造测试用的持仓 dict。"""
    now = datetime.now(timezone.utc)
    open_time = (now - timedelta(hours=open_time_hours_ago)).isoformat()
    return {
        "inst_id": "SKHYNIX-USDT-SWAP",
        "direction": direction,
        "entry_price": entry_price,
        "open_price": entry_price,
        "sz": 0.078,
        "addons": addons,
        "confidence": 68,
        "open_time": open_time,
        "take_profit_pct": take_profit_pct,
        "original_tp_pct": original_tp_pct,
        "addon_pct": 0.14,
        "stop_loss_price": None,
        "stop_loss_type": None,
        "peak_price": entry_price * 1.05,
        "subregime": "BULL_STRONG",
        "tp_mult": 1.1,
        "holding_mult": 1.2,
    }


def _make_params(current_price=1263.0, elder_ray_direction="STRONG_BULL",
                 elder_ray_strength=80, direction="LONG"):
    """构造测试用的 _get_dynamic_params 返回值。"""
    return {
        "current_price": current_price,
        "take_profit_pct": 0.0985,
        "stop_loss_price": None,
        "stop_loss_type": None,
        "stop_loss_triggered": False,
        "elder_ray": {
            "direction": elder_ray_direction,
            "strength": elder_ray_strength,
            "ema_trend": "up" if "BULL" in elder_ray_direction else "down",
            "bull_power": 10.0,
            "bear_power": 2.0,
            "both_weakening": False,
            "bull_out_of_control": False,
            "bear_out_of_control": False,
        },
        "klines_4h": [],
    }


def test_timeout_profit_signal_weak_triggers_close(monkeypatch):
    """超时+盈利+信号弱化 → 应直接止盈平仓（return True）。"""
    # 重新导入确保拿到最新代码
    if "v15_trader" in sys.modules:
        del sys.modules["v15_trader"]
    import v15_trader

    pos = _make_pos(entry_price=1200, open_time_hours_ago=50, take_profit_pct=0.0985)
    state = {"positions": {"SKHYNIX": pos}}

    # mock _get_dynamic_params 返回盈利 + 弱化信号
    weak_params = _make_params(
        current_price=1263,  # 盈利 (1263-1200)/1200 = 5.25%
        elder_ray_direction="BULL_REVERSAL",
        elder_ray_strength=35,
    )
    monkeypatch.setattr(v15_trader, "_get_dynamic_params", lambda c, coin, d: weak_params)
    monkeypatch.setattr(v15_trader, "AUTO_EXECUTE", True)

    # mock 平仓函数避免真实调用
    close_called = []
    monkeypatch.setattr(v15_trader, "_execute_close_position",
                        lambda c, coin, p, s, reason="", exit_price=None: close_called.append((coin, reason)))

    result = v15_trader.check_time_exit(MagicMock(), "SKHYNIX", pos, state)
    assert result is True, "超时+盈利+信号弱化应触发平仓"
    assert len(close_called) == 1, "应调用 _execute_close_position"
    assert "signal_weak" in close_called[0][1] or "timeout" in close_called[0][1].lower()


def test_timeout_profit_signal_strong_raises_tp(monkeypatch):
    """超时+盈利+信号仍强 → 应提高止盈价，不触发平仓（return False）。"""
    if "v15_trader" in sys.modules:
        del sys.modules["v15_trader"]
    import v15_trader

    pos = _make_pos(entry_price=1200, open_time_hours_ago=50,
                   take_profit_pct=0.0985, original_tp_pct=0.0985)
    state = {"positions": {"SKHYNIX": pos}}

    strong_params = _make_params(
        current_price=1263,  # 盈利 5.25%
        elder_ray_direction="STRONG_BULL",
        elder_ray_strength=80,
    )
    monkeypatch.setattr(v15_trader, "_get_dynamic_params", lambda c, coin, d: strong_params)
    monkeypatch.setattr(v15_trader, "AUTO_EXECUTE", True)

    sync_called = []
    monkeypatch.setattr(v15_trader, "_sync_tp_sl_orders",
                        lambda c, coin, p, ep, tp, sl: sync_called.append((coin, tp)))

    result = v15_trader.check_time_exit(MagicMock(), "SKHYNIX", pos, state)
    assert result is False, "信号仍强时不应触发平仓"
    assert len(sync_called) == 1, "应调用 _sync_tp_sl_orders 更新止盈"
    # 止盈应被提高
    assert sync_called[0][1] > 0.0985, "止盈应被提高"
    # 但不超过原始 × 2
    assert sync_called[0][1] <= 0.0985 * 2.0, "止盈不应超过原始 × 2"


def test_timeout_loss_continues_holding(monkeypatch):
    """超时+亏损 → 不评估信号，继续持有。"""
    if "v15_trader" in sys.modules:
        del sys.modules["v15_trader"]
    import v15_trader

    pos = _make_pos(entry_price=1200, open_time_hours_ago=50)
    state = {"positions": {"SKHYNIX": pos}}

    loss_params = _make_params(current_price=1150)  # 亏损 -4.17%
    monkeypatch.setattr(v15_trader, "_get_dynamic_params", lambda c, coin, d: loss_params)
    monkeypatch.setattr(v15_trader, "AUTO_EXECUTE", True)

    result = v15_trader.check_time_exit(MagicMock(), "SKHYNIX", pos, state)
    assert result is False, "亏损超时应继续持有"


def test_no_timeout_no_action(monkeypatch):
    """未超时 → 不触发任何操作。"""
    if "v15_trader" in sys.modules:
        del sys.modules["v15_trader"]
    import v15_trader

    pos = _make_pos(entry_price=1200, open_time_hours_ago=10)  # 只持 10h
    state = {"positions": {"SKHYNIX": pos}}

    params = _make_params(current_price=1263)
    monkeypatch.setattr(v15_trader, "_get_dynamic_params", lambda c, coin, d: params)

    result = v15_trader.check_time_exit(MagicMock(), "SKHYNIX", pos, state)
    assert result is False, "未超时应返回 False"


def test_tp_cap_never_exceeds_original_x2(monkeypatch):
    """止盈价上限不超过原始 × 2（多次触发也不会超过）。"""
    if "v15_trader" in sys.modules:
        del sys.modules["v15_trader"]
    import v15_trader

    # 模拟已经被放大到接近上限的持仓
    pos = _make_pos(
        entry_price=1200,
        open_time_hours_ago=50,
        take_profit_pct=0.18,  # 已经接近上限 0.0985*2=0.197
        original_tp_pct=0.0985,
    )
    state = {"positions": {"SKHYNIX": pos}}

    strong_params = _make_params(current_price=1263, elder_ray_direction="STRONG_BULL")
    monkeypatch.setattr(v15_trader, "_get_dynamic_params", lambda c, coin, d: strong_params)
    monkeypatch.setattr(v15_trader, "AUTO_EXECUTE", True)

    sync_calls = []
    monkeypatch.setattr(v15_trader, "_sync_tp_sl_orders",
                        lambda c, coin, p, ep, tp, sl: sync_calls.append(tp))

    v15_trader.check_time_exit(MagicMock(), "SKHYNIX", pos, state)

    if sync_calls:
        assert sync_calls[0] <= 0.0985 * 2.0, f"止盈 {sync_calls[0]} 不应超过原始×2={0.0985*2.0}"
    # pos 中的 take_profit_pct 也不应超过
    assert pos["take_profit_pct"] <= 0.0985 * 2.0 + 1e-9, "pos 中 take_profit_pct 不应超过上限"
