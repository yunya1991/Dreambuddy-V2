"""资产类别配额（配比制）测试。

覆盖：可投资本公式、按 allocation 分摊、超配额只禁该类、低于最小名义、
stale 降一档、方向偏置不 veto。
"""

from dreambuddy_evolution.adapters.asset_class_quota import (
    build_quota_plan,
    direction_policy,
    evaluate_entry,
)


def test_quota_plan_formula():
    """可投资本 = 总权益 × 杠杆 × band_upper × exposure_hint。"""
    plan = build_quota_plan(
        total_equity=1000.0,
        leverage=5.0,
        band_upper_pct=55.0,
        exposure_hint=0.5,
        allocation={"crypto_usdt": 0.5, "us_stock": 0.3, "precious_metal": 0.2},
    )
    # 1000 × 5 × 0.55 × 0.5 = 1375
    assert plan["investable_notional"] == 1375.0
    assert plan["quota"]["crypto_usdt"] == 687.5
    assert plan["quota"]["us_stock"] == 412.5
    assert plan["quota"]["precious_metal"] == 275.0


def test_quota_plan_stale_halves_exposure():
    """数据 stale → exposure_hint 减半，不转全禁。"""
    fresh = build_quota_plan(total_equity=1000.0, band_upper_pct=55.0, exposure_hint=0.5)
    stale = build_quota_plan(
        total_equity=1000.0, band_upper_pct=55.0, exposure_hint=0.5, stale=True
    )
    assert stale["investable_notional"] == fresh["investable_notional"] / 2
    assert stale["exposure_hint"] == 0.25


def test_quota_plan_missing_allocation_is_equal_weight():
    """allocation 缺失 → 均分，不阻断。"""
    plan = build_quota_plan(total_equity=900.0, leverage=1.0, band_upper_pct=100.0)
    assert abs(plan["allocation"]["crypto_usdt"] - 1 / 3) < 1e-3
    assert plan["quota"]["crypto_usdt"] == 300.0


def test_evaluate_allows_within_quota():
    plan = build_quota_plan(total_equity=1000.0, band_upper_pct=100.0)
    out = evaluate_entry(
        asset_class="crypto_usdt",
        requested_notional=100.0,
        used_notional_by_class={"crypto_usdt": 1000.0},
        plan=plan,
        min_notional=50.0,
    )
    assert out["decision"] == "allow"
    assert out["allowed_notional"] == 100.0


def test_evaluate_blocks_only_over_quota_class():
    """配额用尽 → 只锁该类，其他类仍可开。"""
    plan = build_quota_plan(total_equity=300.0, leverage=1.0, band_upper_pct=100.0)
    over = evaluate_entry(
        asset_class="crypto_usdt",
        requested_notional=100.0,
        used_notional_by_class={"crypto_usdt": 100.0},
        plan=plan,
        min_notional=50.0,
    )
    assert over["decision"] == "block_over_quota"
    assert over["allowed_notional"] == 0.0
    other = evaluate_entry(
        asset_class="us_stock",
        requested_notional=100.0,
        used_notional_by_class={"crypto_usdt": 100.0},
        plan=plan,
        min_notional=50.0,
    )
    assert other["decision"] == "allow"


def test_evaluate_clamps_to_remaining():
    plan = build_quota_plan(
        total_equity=120.0,
        leverage=1.0,
        band_upper_pct=100.0,
        allocation={"crypto_usdt": 1.0},
    )
    out = evaluate_entry(
        asset_class="crypto_usdt",
        requested_notional=100.0,
        used_notional_by_class={"crypto_usdt": 80.0},
        plan=plan,
        min_notional=10.0,
    )
    assert out["decision"] == "allow_clamped"
    assert out["allowed_notional"] == 40.0


def test_evaluate_suppressed_below_floor():
    plan = build_quota_plan(
        total_equity=120.0,
        leverage=1.0,
        band_upper_pct=100.0,
        allocation={"crypto_usdt": 1.0},
    )
    out = evaluate_entry(
        asset_class="crypto_usdt",
        requested_notional=100.0,
        used_notional_by_class={"crypto_usdt": 115.0},
        plan=plan,
        min_notional=10.0,
    )
    assert out["decision"] == "constraint_suppressed"
    assert out["allowed_notional"] == 0.0


def test_evaluate_fail_open_without_plan():
    out = evaluate_entry(
        asset_class="crypto_usdt",
        requested_notional=100.0,
        used_notional_by_class={},
        plan=None,
        min_notional=50.0,
    )
    assert out["decision"] == "allow"


def test_direction_policy_no_veto():
    aligned = direction_policy(
        "long", {"long": 0.8, "short": 0.0, "neutral": 0.2, "dominant": "long"}
    )
    assert aligned["multiplier"] == 1.24
    opposite = direction_policy(
        "long", {"long": 0.1, "short": 0.9, "neutral": 0.0, "dominant": "short"}
    )
    assert opposite["multiplier"] == 0.6
    assert opposite["probe_only"] is False
    neutral = direction_policy(
        "long", {"long": 0.01, "short": 0.0, "neutral": 0.99, "dominant": "neutral"}
    )
    assert neutral["probe_only"] is True
