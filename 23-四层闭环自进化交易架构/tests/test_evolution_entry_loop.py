"""23 开仓循环（entry loop）下沉测试。"""

import pytest
from dreambuddy_evolution.execution import EvolutionEntryLoop


class _Result:
    def __init__(self, executed=True, reason="", reason_code="", order_result=None):
        self.passed = executed
        self.executed = executed
        self.reason = reason
        self.reason_code = reason_code
        self.order_result = order_result or {"ord_id": "ord-open", "avg_px": 100.0}
        self.sltp_result = None


class _Gateway:
    def __init__(self, executed=True):
        self.executed = executed
        self.calls = []

    def submit(self, decision):
        self.calls.append(decision)
        return _Result(
            executed=self.executed,
            reason="" if self.executed else "gateway_reject",
            reason_code="" if self.executed else "REJECT",
        )


def _loop(tmp_path, gateway=None, **kw):
    """默认放行全部闸门；测试按需覆盖注入函数。"""
    defaults = {
        "gateway": gateway or _Gateway(),
        "runtime_dir": tmp_path,
        "log_fn": lambda *a, **k: None,
        "authority_fn": lambda tag: True,
        "blacklist_fn": lambda sym: (False, ""),
        "fuse_fn": lambda: None,
        "has_position_fn": lambda inst: False,
        "cooldown_fn": lambda inst, d: (False, ""),
        "direction_state_fn": lambda sym, d: "NEUTRAL",
        "subpool_fn": lambda: {"count": 0, "long": 0, "short": 0, "probe_count": 0},
        "short_ban_fn": lambda sym, d: {},
        "equity_fn": lambda: 1000.0,
        "track_mult_fn": lambda kline: 1.0,
        "asset_class_fn": lambda sym: "crypto_usdt",
        "macro_constraint_fn": lambda cls: {},
        "used_notional_fn": lambda: {},
        "min_sz_fn": lambda inst: 0.1,
        "price_fn": lambda inst: 100.0,
    }
    defaults.update(kw)
    return EvolutionEntryLoop(**defaults)


def _run(loop, **kw):
    args = {"symbol": "BTC", "action": "long", "u_open": 0.5, "d_star": "D2", "confidence": 0.6}
    args.update(kw)
    return loop.run(**args)


def test_open_dispatches_entry_decision_and_hook(tmp_path):
    gw = _Gateway()
    opened = []
    loop = _loop(tmp_path, gateway=gw, on_opened=lambda ctx, res: opened.append((ctx, res)))
    out = _run(loop)

    assert out["status"] == "opened"
    assert out["notional_usdt"] == pytest.approx(1000.0)  # 2000 × 1.0 × 0.5
    sig = gw.calls[0]
    assert sig["source"] == "23-evolution"
    assert sig["symbol"] == "BTC-USDT-SWAP"
    assert sig["action"] == "open"
    assert sig["direction"] == "long"
    assert sig["payload"]["notional_usdt"] == pytest.approx(1000.0)
    assert sig["payload"]["tier"] == "standard"
    assert sig["sl_px"] < 100.0 < sig["tp_px"]
    assert len(opened) == 1


def test_authority_block_writes_shadow(tmp_path):
    gw = _Gateway()
    shadows = []
    loop = _loop(
        tmp_path,
        gateway=gw,
        authority_fn=lambda tag: False,
        on_shadow=lambda ctx: shadows.append(ctx),
    )
    out = _run(loop, source_tag="event_arbitrage")

    assert out["status"] == "blocked" and out["gate"] == "execution_authority"
    assert gw.calls == []
    assert shadows[0]["source_tag"] == "event_arbitrage"


def test_blacklist_blocks(tmp_path):
    gw = _Gateway()
    loop = _loop(tmp_path, gateway=gw, blacklist_fn=lambda s: (True, "动态黑名单"))
    out = _run(loop)
    assert out["gate"] == "blacklist" and gw.calls == []


def test_u_open_cbr_coupling_blocks(tmp_path):
    loop = _loop(tmp_path)
    out = _run(loop, u_open=1.2, cbr_sim=0.2)
    assert out["gate"] == "u_open_cbr_coupling"


def test_fuse_blocks(tmp_path):
    class _Fuse:
        block_new_open = True

        def __str__(self):
            return "drawdown_fuse"

    loop = _loop(tmp_path, fuse_fn=lambda: _Fuse())
    out = _run(loop)
    assert out["gate"] == "portfolio_fuse"


def test_duplicate_position_blocks(tmp_path):
    loop = _loop(tmp_path, has_position_fn=lambda inst: inst == "BTC-USDT-SWAP")
    out = _run(loop)
    assert out["gate"] == "duplicate_position"


def test_cooldown_blocks(tmp_path):
    loop = _loop(tmp_path, cooldown_fn=lambda inst, d: (True, "8h 冷静期"))
    out = _run(loop)
    assert out["gate"] == "cooldown" and "8h" in out["reason"]


@pytest.mark.parametrize(
    "state,direction,expect_block",
    [
        ("FREEZE", "long", True),
        ("SHORT_ONLY", "long", True),
        ("SHORT_ONLY", "short", False),
        ("LONG_ONLY", "short", True),
        ("NEUTRAL", "short", False),
    ],
)
def test_direction_state_gate(tmp_path, state, direction, expect_block):
    loop = _loop(tmp_path, direction_state_fn=lambda s, d: state)
    out = _run(loop, action=direction)
    assert (out["status"] == "blocked") is expect_block


def test_direction_state_tuple_contract(tmp_path):
    loop = _loop(tmp_path, direction_state_fn=lambda s, d: (True, "macro_freeze"))
    out = _run(loop)
    assert out["gate"] == "direction_state" and out["reason"] == "macro_freeze"


def test_subpool_full_blocks(tmp_path):
    loop = _loop(tmp_path, subpool_fn=lambda: {"count": 5, "long": 2, "short": 3})
    out = _run(loop)
    assert out["gate"] == "subpool_full"


def test_direction_concentration_blocks_long(tmp_path):
    loop = _loop(tmp_path, subpool_fn=lambda: {"count": 4, "long": 3, "short": 1, "probe_count": 0})
    out = _run(loop, action="long")
    assert out["gate"] == "direction_concentration"


def test_trend_tier_bypasses_concentration(tmp_path):
    loop = _loop(tmp_path, subpool_fn=lambda: {"count": 4, "long": 4, "short": 0, "probe_count": 0})
    out = _run(loop, action="long", tier="trend", u_open=0.5)
    assert out["status"] == "opened"


def test_probe_cap_blocks(tmp_path):
    loop = _loop(tmp_path, subpool_fn=lambda: {"count": 1, "probe_count": 2})
    out = _run(loop, tier="probe")
    assert out["gate"] == "probe_full"


def test_short_ban_blocks(tmp_path):
    loop = _loop(
        tmp_path, short_ban_fn=lambda s, d: {"blocked": True, "reason": "SHORT_ONLY_BLACKLIST"}
    )
    out = _run(loop, action="short")
    assert out["gate"] == "short_ban"


def test_short_ban_exemption_applies_position_mult(tmp_path):
    loop = _loop(
        tmp_path,
        short_ban_fn=lambda s, d: {"blocked": False, "pos_mult": 0.5, "reason": "2因子试探"},
    )
    out = _run(loop, action="short", u_open=0.5)
    assert out["status"] == "opened"
    assert out["notional_usdt"] == pytest.approx(500.0)


def test_track_multiplier_and_clamp(tmp_path):
    loop = _loop(tmp_path, track_mult_fn=lambda k: 2.0)
    out = _run(loop, u_open=0.8)
    assert out["notional_usdt"] == pytest.approx(2000.0)  # 3200 → 钳位 2000


def test_track_multiplier_zero_blocks(tmp_path):
    loop = _loop(tmp_path, track_mult_fn=lambda k: 0.0)
    out = _run(loop)
    assert out["gate"] == "ftc_track_zero"


def test_standard_floor_rejected(tmp_path):
    loop = _loop(tmp_path)
    out = _run(loop, u_open=0.1)  # 200U < 250U
    assert out["gate"] == "floor_rejected"


def test_probe_uses_exchange_min_sz_floor(tmp_path):
    # minSz=0.1 × px=100 × 1.2 = 12U 地板；10U 被拒
    loop = _loop(tmp_path)
    out = _run(loop, tier="probe", u_open=0.005)  # 10U
    assert out["gate"] == "floor_rejected"

    out = _run(loop, tier="probe", u_open=0.01)  # 20U ≥ 12U
    assert out["status"] == "opened"


def test_quota_block_over_quota(tmp_path):
    loop = _loop(
        tmp_path,
        macro_constraint_fn=lambda cls: {
            "allocation": {"crypto_usdt": 1.0},
            "band_upper_pct": 100,
            "exposure_hint": 1.0,
        },
        used_notional_fn=lambda: {"crypto_usdt": 999999.0},
    )
    out = _run(loop)
    assert out["gate"] == "block_over_quota"


def test_gateway_reject_reports_failed(tmp_path):
    loop = _loop(tmp_path, gateway=_Gateway(executed=False))
    out = _run(loop)
    assert out["status"] == "failed" and out["reason_code"] == "REJECT"


def test_gate_exception_is_fail_open(tmp_path):
    def _boom(sym):
        raise RuntimeError("blacklist_boom")

    loop = _loop(tmp_path, blacklist_fn=_boom)
    out = _run(loop)
    assert out["status"] == "opened"


def test_cap_mode_off_does_not_compress(tmp_path):
    loop = _loop(
        tmp_path,
        macro_constraint_fn=lambda cls: {"aggregate_position_cap_pct": {"crypto_usdt": 0.2}},
    )
    out = _run(loop)
    assert out["notional_usdt"] == pytest.approx(1000.0)
