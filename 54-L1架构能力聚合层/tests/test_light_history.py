# -*- coding: utf-8 -*-
"""点亮历史快照（标定输入）：`as_of` 日历切片与快照结构（不依赖 DB）。"""

import math
import os
import sys

import pytest

_MODULE_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
if _MODULE_ROOT not in sys.path:
    sys.path.insert(0, _MODULE_ROOT)
_SCRIPTS_DIR = os.path.join(_MODULE_ROOT, "scripts")
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

from light_history import SnapshotError, build_snapshots, select_as_of_dates  # noqa: E402


def _raw():
    return {
        "BTC": {f"2026-11-{day:02d}": 100.0 + day for day in range(1, 11)},
        "ETH": {f"2026-11-{day:02d}": 50.0 + day for day in range(1, 11)},
    }


def test_select_as_of_dates_uses_base_calendar_tail():
    dates = select_as_of_dates(_raw(), "BTC", 3)
    assert dates == ["2026-11-08", "2026-11-09", "2026-11-10"]


def test_select_as_of_dates_rejects_empty_base():
    with pytest.raises(SnapshotError):
        select_as_of_dates(_raw(), "XAU", 3)
    with pytest.raises(SnapshotError):
        select_as_of_dates(_raw(), "BTC", 0)


def test_build_snapshots_one_per_as_of_without_lookahead():
    seen = []

    def entries_fn(raw, pool, *, as_of=None, base=None):
        seen.append((as_of, base))
        return [
            {
                "symbol": "BTC",
                "class": "crypto",
                "as_of": as_of,
                "axes": {"trend": 0.5, "inertia": 0.5, "cycle": 0.5, "foresight": 0.5},
            }
        ]

    def rows_fn(entries):
        return [dict(entry, projected=True) for entry in entries]

    snapshots = build_snapshots(
        _raw(), None, base="BTC", count=2, entries_fn=entries_fn, rows_fn=rows_fn
    )
    assert [as_of for as_of, _ in seen] == ["2026-11-09", "2026-11-10"]
    assert all(base == "BTC" for _, base in seen)
    assert [snapshot["as_of"] for snapshot in snapshots] == ["2026-11-09", "2026-11-10"]
    assert all(
        snapshot["lights"]["rows"][0]["as_of"] == snapshot["as_of"] for snapshot in snapshots
    )
    assert all(snapshot["lights"]["rows"][0]["projected"] for snapshot in snapshots)


def _load_visual_overview():
    """按路径加载前端编排脚本（只取纯函数，不触 DB）。"""
    import importlib.util

    repo = os.path.dirname(os.path.normpath(_MODULE_ROOT))
    script = os.path.join(repo, "3.1-FRONTEND", "scripts", "visual_overview.py")
    spec = importlib.util.spec_from_file_location("_visual_overview_for_tests", script)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_foresight_reference_prefers_base_and_never_self():
    """前瞻共振参考标的：base 优先；base 自比时取首个其他标的；无其他标的返回 None。"""
    mod = _load_visual_overview()

    raw = {"BTC": {}, "ETH": {}, "XAU": {}}
    assert mod._foresight_reference(raw, "ETH", "BTC") == "BTC"
    assert mod._foresight_reference(raw, "BTC", "BTC") == "ETH"
    assert mod._foresight_reference(raw, "XAU", None) == "BTC"
    assert mod._foresight_reference({"BTC": {}}, "BTC", "BTC") is None


def _returns_series(days=700):
    """确定性日收益（正弦 + 漂移），保证 I36 分位回归有变异、可复现。"""
    dates = [f"d{index:04d}" for index in range(days)]
    values = {}
    for index, day in enumerate(dates):
        values[day] = 0.0004 + 0.012 * math.sin(index / 6.0) + 0.004 * math.cos(index / 17.0)
    return values, dates


def test_forward_distribution_skips_when_pairs_insufficient():
    """有效对不足 `min_pairs` → None（不补造、不降级为伪分布）。"""
    mod = _load_visual_overview()
    returns, dates = _returns_series(120)
    assert mod._forward_distribution(returns, dates) is None


def test_forward_distribution_publishes_i36_summary():
    """样本充足 → I36 摘要（q10<q50<q90、dispersion=宽度、scale>0、pairs≥500）。"""
    mod = _load_visual_overview()
    returns, dates = _returns_series(700)
    forward = mod._forward_distribution(returns, dates)
    assert forward is not None
    assert forward["capability"] == "I36"
    assert forward["n"] >= 500
    assert forward["q10"] < forward["q50"] < forward["q90"]
    assert forward["dispersion"] == pytest.approx(forward["q90"] - forward["q10"], abs=1e-6)
    assert forward["scale"] and forward["scale"] > 0.0
    # `as_of` 截断（无前视）：只给前 600 天，pairs 必须相应减少
    shorter = mod._forward_distribution(returns, dates[:600])
    assert shorter is None or shorter["n"] < forward["n"]


def test_forward_dispersion_flag_boundary_and_no_scale():
    mod = _load_visual_overview()
    ref = mod.FORESIGHT_DISPERSION_REF
    assert (
        mod._forward_dispersion_flag({"dispersion": ref * 0.1, "scale": 0.1})
        == "forward_dispersion_wide"
    )
    assert mod._forward_dispersion_flag({"dispersion": ref * 0.1 - 1e-9, "scale": 0.1}) is None
    assert mod._forward_dispersion_flag({"dispersion": 0.5}) is None
    assert mod._forward_dispersion_flag({"dispersion": 0.5, "scale": 0.0}) is None
    assert mod._forward_dispersion_flag(None) is None


def test_foresight_evidence_is_disclosed_without_changing_strength():
    """I36 只进 `foresight.evidence`：强度仍等于 coherence 归一（LT-AC3 一致性契约）。"""
    from l1agg.capabilities.lights import axes_from_direction

    scored = {"axes": {"coherence": 9.0}, "axis_weights": {"coherence": 15.0}}
    facts = axes_from_direction(
        scored, foresight_evidence={"method": "I36", "dispersion": 0.36, "pairs": 699}
    )
    assert facts["foresight"]["strength"] == pytest.approx(0.6)
    assert facts["foresight"]["evidence"]["method"] == "I36"
    assert facts["trend"]["evidence"] == {}


def _flag_raw(vix_values, price_values, curve_tail=None):
    days = [f"2026-09-{day:02d}" for day in range(1, 31)] + [
        f"2026-10-{day:02d}" for day in range(1, 11)
    ]
    raw = {
        "BTC": dict(zip(days, price_values, strict=False)),
        "VIX": dict(zip(days, vix_values, strict=False)),
    }
    if curve_tail is not None:
        raw["T10Y2Y"] = dict.fromkeys(days, curve_tail)
    return raw


def test_conflict_flags_vix_high_percentile_and_divergence():
    """VIX 创历史高位 + 价格与 VIX 同向 20 日上行 → 两个旗标（无前视、无 T10Y2Y 不伪造）。"""
    mod = _load_visual_overview()
    vix = [10.0 + index * 0.5 for index in range(40)]  # 单调上行，末值为最大值 → 分位 1.0
    price = [100.0 + index for index in range(40)]
    raw = _flag_raw(vix, price)
    flags = mod._conflict_flags(raw, "BTC", as_of="2026-10-10")
    assert flags == ["vix_pct_ge_0.90", "vix_divergence"]
    # 无前视：as_of 截断到第 20 天时不看后面 20 天
    early = mod._conflict_flags(raw, "BTC", as_of="2026-09-20")
    assert "vix_divergence" not in early


def test_conflict_flags_curve_inversion_and_vix_self_exclusion():
    """T10Y2Y 末值为负 → `curve_inverted`；VIX 自身不做背离判断。"""
    mod = _load_visual_overview()
    vix = [20.0] * 39 + [10.0]  # 末值为历史最低 → 分位 0.025，不触发 VIX 两旗标
    price = [100.0 + index for index in range(40)]
    raw = _flag_raw(vix, price, curve_tail=-0.32)
    assert "curve_inverted" in mod._conflict_flags(raw, "BTC", as_of="2026-10-10")
    assert mod._conflict_flags(raw, "VIX", as_of="2026-10-10") == ["curve_inverted"]
    raw["T10Y2Y"] = dict.fromkeys(raw["T10Y2Y"], 0.41)
    assert mod._conflict_flags(raw, "BTC", as_of="2026-10-10") == []
