# -*- coding: utf-8 -*-
"""能力层测试：manifest 校验 + 信封契约 + E 组五个端到端编排。"""

import datetime
import json
import math
import os
import random
import sys

import pytest

_MODULE_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
if _MODULE_ROOT not in sys.path:
    sys.path.insert(0, _MODULE_ROOT)

from l1agg.capabilities import (  # noqa: E402
    STATUS_EMPTY,
    STATUS_GOOD,
    STATUS_PARTIAL,
    build,
    manifest,
    quality_for,
    run_capability,
    supported,
    unavailable,
)
from l1agg.capabilities.envelope import GATE_METHOD  # noqa: E402
from l1agg.capabilities.manifest import (  # noqa: E402
    Capability,
    Manifest,
    ManifestError,
    validate,
    validate_execution,
)


def _prices(n=400, seed=5, drift=0.0005, vol=0.02):
    rng = random.Random(seed)
    out, px = [], 100.0
    for _ in range(n):
        px *= 1.0 + rng.gauss(drift, vol)
        out.append(px)
    return out


def _dates(n=400, start=datetime.date(2024, 1, 1)):
    return [(start + datetime.timedelta(days=i)).isoformat() for i in range(n)]


def _factor_prices(n=300):
    factor = [float(i) for i in range(n)]
    forward = [(value - (n - 1) / 2) * 0.0001 for value in factor]
    prices = [100.0]
    for value in forward:
        prices.append(prices[-1] * (1.0 + value))
    factor.append(float(n))
    return factor, prices


def _ar1(n=400, seed=7, phi=0.6, mu=0.001, sigma=0.01):
    """AR(1) 收益序列：自带正自相关，用于验证 HAC 标准误与 lag。"""
    rng = random.Random(seed)
    out, prev = [], 0.0
    for _ in range(n):
        prev = mu + phi * (prev - mu) + rng.gauss(0.0, sigma)
        out.append(prev)
    return out


def _portfolio_returns(n=160, seed=23):
    rng = random.Random(seed)
    return {
        "BTC": [rng.gauss(0.0002, 0.015) for _ in range(n)],
        "ETH": [rng.gauss(0.0003, 0.02) for _ in range(n)],
    }


def _ic_inputs(n=320, seed=31):
    rng = random.Random(seed)
    factor = [math.sin(i / 11.0) + rng.gauss(0.0, 0.1) for i in range(n)]
    forward = [0.01 * value + rng.gauss(0.0, 0.002) for value in factor]
    prices = [100.0]
    for value in forward[1:]:
        prices.append(prices[-1] * (1.0 + value))
    return factor, forward, prices


def _quantile_inputs(n=320):
    factor = [math.sin(i / 11.0) + 0.2 * math.cos(i / 7.0) for i in range(n)]
    forward = [0.01 * value for value in factor]
    return factor, forward


def _panel_inputs(n=320, seed=23):
    """四变量面板（D-J22 输入）：前两列与公共因子强相关，第三列为独立噪声。"""
    rng = random.Random(seed)
    base = [math.sin(i / 13.0) + 0.2 * math.cos(i / 5.0) for i in range(n)]
    return {
        "alpha": [value + rng.gauss(0.0, 0.05) for value in base],
        "beta": [0.5 * value + rng.gauss(0.0, 0.02) for value in base],
        "gamma": [rng.gauss(0.0, 1.0) for _ in range(n)],
        "delta": [0.3 * value + rng.gauss(0.0, 0.3) for value in base],
    }


def _alignment_kwargs(n=40):
    return {
        "series": {
            "BTC": [100.0 + i for i in range(n)],
            "ETH": [50.0 + 2 * i for i in range(n)],
        },
        "dates": _dates(n),
        "window": min(n, 30),
    }


def _crowding(n=300, seed=11):
    """资金费率 + 未平仓 + 基差三指标面板（D-A14 输入）。"""
    rng = random.Random(seed)
    px = 100.0
    funding, oi, basis = [], [], []
    for _ in range(n):
        px *= 1.0 + rng.gauss(0.0, 0.01)
        funding.append(rng.gauss(0.0001, 0.0002))
        oi.append(px * 1000.0)
        basis.append(rng.gauss(0.001, 0.0005))
    return {"funding": funding, "oi": oi, "basis": basis}


def _correlation_state(n=3400):
    """已压缩的一维相关状态与同步价格轴（D-E14 输入）。"""
    factor = [math.sin(i / 23.0) + 0.2 * math.cos(i / 7.0) for i in range(n)]
    return factor, _prices(n, seed=17, drift=0.0002, vol=0.01)


def _pit_inputs(n=320, seed=41):
    """PIT 指标与同步价格（D-J30 输入）：低频指标驱动价格，便于构造前瞻分布。"""
    rng = random.Random(seed)
    indicator = [math.sin(i / 17.0) + rng.gauss(0.0, 0.05) for i in range(n)]
    prices = [100.0]
    for i in range(1, n):
        prices.append(prices[-1] * (1.0 + 0.01 * indicator[i - 1]))
    return indicator, prices


def _series_inputs(n=120, seed=47):
    """连续日频单序列（D-A01 输入）。"""
    rng = random.Random(seed)
    values, level = [], 100.0
    for _ in range(n):
        level *= 1.0 + rng.gauss(0.0004, 0.008)
        values.append(level)
    return values, _dates(n)


def _g_panel(n_symbols=32, n=90, seed=11):
    """G 组横截面面板：{symbol: 取值序列}。"""
    rng = random.Random(seed)
    return {f"S{i:02d}": [rng.gauss(0.0003, 0.02) for _ in range(n)] for i in range(n_symbols)}


def _g_returns(n_symbols=8, n=90, seed=23):
    """G 组 P 族面板：{symbol: 日收益序列}。"""
    rng = random.Random(seed)
    return {f"A{i:02d}": [rng.gauss(0.0002, 0.015) for _ in range(n)] for i in range(n_symbols)}


def _g_macbeth(n_periods=260, n_assets=8, seed=41):
    """G21 输入：factor/target 两个 {symbol: 序列} 面板。"""
    rng = random.Random(seed)
    factor = {f"B{i:02d}": [rng.gauss(0.0, 1.0) for _ in range(n_periods)] for i in range(n_assets)}
    target = {
        f"B{i:02d}": [rng.gauss(0.001, 0.02) for _ in range(n_periods)] for i in range(n_assets)
    }
    return factor, target


def _j_walk(n=200, seed=7):
    """J 组单序列：带漂移随机游走（趋势/频谱/复杂度/极值共用）。"""
    rng = random.Random(seed)
    out, level = [], 100.0
    for _ in range(n):
        level *= 1.0 + rng.gauss(0.0005, 0.01)
        out.append(level)
    return out


def _j_partner(series, seed=8, noise=0.01):
    rng = random.Random(seed)
    return [v * (1.0 + rng.gauss(0.0, noise)) for v in series]


def _j_rows(n_rows=90, n_cols=4, seed=9):
    rng = random.Random(seed)
    return [[rng.gauss(0.0, 1.0) for _ in range(n_cols)] for _ in range(n_rows)]


def _j_target(rows, seed=10):
    rng = random.Random(seed)
    return [0.3 * sum(r) + rng.gauss(0.0, 0.1) for r in rows]


def _j_groups(n_groups=3, n_each=40, seed=11):
    rng = random.Random(seed)
    return [[rng.gauss(0.1 * (i + 1), 1.0) for _ in range(n_each)] for i in range(n_groups)]


def _j_survival(n=60, seed=12):
    rng = random.Random(seed)
    return {
        "time": [abs(rng.gauss(10.0, 3.0)) + 0.1 for _ in range(n)],
        "event": [rng.random() < 0.6 for _ in range(n)],
        "group": [i % 2 for i in range(n)],
        "covariate": [rng.gauss(0.0, 1.0) for _ in range(n)],
    }


def _j_coords(n=40, seed=13):
    rng = random.Random(seed)
    return [[rng.random(), rng.random()] for _ in range(n)]


def _j_spatial_values(n=40, seed=14):
    rng = random.Random(seed)
    return [rng.gauss(0.0, 1.0) for _ in range(n)]


def _j_meta(n=32, seed=15):
    rng = random.Random(seed)
    effects = [rng.gauss(0.2, 0.3) for _ in range(n)]
    se = [abs(rng.gauss(0.1, 0.02)) for _ in range(n)]
    return effects, se


def _j_missing_rows(n_rows=80, n_cols=4, seed=16):
    rng = random.Random(seed)
    return [
        [None if rng.random() < 0.1 else rng.gauss(0.0, 1.0) for _ in range(n_cols)]
        for _ in range(n_rows)
    ]


# ---------------- manifest ----------------


def test_manifest_loads_and_validates():
    m = manifest()
    assert m.version >= 1
    ids = [cap.id for cap in m.capabilities]
    assert len(ids) == len(set(ids))
    assert {
        "D-A01",
        "D-A02",
        "D-A03",
        "D-A04",
        "D-A06",
        "D-A07",
        "D-A08",
        "D-A09",
        "D-A10",
        "D-A11",
        "D-A12",
        "D-A13",
        "D-A15",
        "D-A16",
        "D-B08",
        "D-B09",
        "D-G08",
        "D-G09",
        "D-A14",
        "D-E01",
        "D-E02",
        "D-E03",
        "D-E04",
        "D-E05",
        "D-E06",
        "D-E07",
        "D-E08",
        "D-E09",
        "D-E10",
        "D-E11",
        "D-E12",
        "D-E14",
        "D-G16",
        "D-G19",
        "D-G20",
        "D-G22",
        "D-G23",
        "D-J02",
        "D-J04",
        "D-J22",
        "D-J24",
        "D-G14",
        "D-J30",
    } <= set(ids)
    assert {"M01", "M02", "M03", "M04", "M05", "M06", "M07"} <= set(m.get("D-E05").methods)
    assert set(m.get("D-G16").methods) == {"D17", "D18", "P09", "P10"}
    assert m.get("D-G16").intent == "metric_series"
    assert m.get("D-G16").min_n == 60
    assert set(m.get("D-G19").methods) == {"B13", "B14", "B15", "Q01", "Q02", "Q03"}
    assert m.get("D-G19").intent == "metric_series"
    assert m.get("D-G19").min_n == 250
    assert set(m.get("D-G20").methods) == {"B11", "B16", "Q04"}
    assert m.get("D-G20").intent == "metric_series"
    assert m.get("D-G20").min_n == 250
    assert set(m.get("D-G22").methods) == {"Q06", "Q07"}
    assert set(m.get("D-G23").methods) == {"Q10", "Q11"}
    assert set(m.get("D-E07").methods) == {"B02", "B06", "B07", "B08", "B09"}
    assert set(m.get("D-J02").methods) == {"C13", "T10", "SC91"}
    assert m.get("D-J02").min_n == 60
    assert m.get("D-J02").min_span_days == 1095
    assert set(m.get("D-J04").methods) == {"T22", "T23", "SC49", "SC50", "SC51"}
    assert set(m.get("D-J22").methods) == {"M19", "M20", "SC31", "SC32", "SC33"}
    assert m.get("D-J22").intent == "metric_series"
    assert m.get("D-J22").min_n == 60
    assert set(m.get("D-J24").methods) == {"M05", "M21", "SC71", "SC72"}
    assert m.get("D-J24").intent == "metric_series"
    assert m.get("D-J24").min_n == 60
    assert set(m.get("D-G14").methods) == {"P07", "T19"}
    assert m.get("D-G14").intent == "metric_series"
    assert m.get("D-G14").min_n == 60
    assert set(m.get("D-J30").methods) == {"SC90", "R02"}
    assert m.get("D-J30").intent == "metric_percentile"
    assert m.get("D-J30").min_n == 250
    assert m.get("D-J30").mode == "deterministic"
    assert m.get("D-A14").intent == "metric_percentile"
    assert set(m.get("D-A14").methods) == {"F26"}
    assert set(m.get("D-A01").methods) == {"S25"}
    assert m.get("D-A01").intent == "metric_series"
    assert m.get("D-A01").min_n == 30
    assert m.get("D-A01").data_scope == ("datacenter.series",)
    assert set(m.get("D-A02").methods) == {"S15", "S16"}
    assert m.get("D-A02").intent == "metric_series"
    assert m.get("D-A02").min_n == 2
    assert m.get("D-A02").data_scope == ("datacenter.series",)
    assert set(m.get("D-A03").methods) == {"S19"}
    assert m.get("D-A03").intent == "metric_series"
    assert m.get("D-A03").min_n == 2
    assert m.get("D-A03").data_scope == ("datacenter.series",)
    assert set(m.get("D-A04").methods) == {"S25"}
    assert m.get("D-A04").intent == "metric_percentile"
    assert m.get("D-A04").min_n == 30
    assert m.get("D-A04").data_scope == ("datacenter.percentile",)
    assert set(m.get("D-A06").methods) == {"F05"}
    assert m.get("D-A06").intent == "metric_series"
    assert m.get("D-A06").min_n == 30
    assert m.get("D-A06").data_scope == ("datacenter.series",)
    assert set(m.get("D-A07").methods) == {"D20", "D21"}
    assert m.get("D-A07").intent == "drawdown_query"
    assert m.get("D-A07").min_n == 250
    assert m.get("D-A07").data_scope == ("market.candles",)
    assert set(m.get("D-A08").methods) == {"S16"}
    assert m.get("D-A08").intent == "metric_series"
    assert m.get("D-A08").min_n == 13
    assert m.get("D-A08").data_scope == ("datacenter.series",)
    assert set(m.get("D-A09").methods) == {"S16"}
    assert m.get("D-A09").intent == "metric_series"
    assert m.get("D-A09").min_n == 2
    assert m.get("D-A09").data_scope == ("datacenter.series",)
    assert set(m.get("D-A10").methods) == {"S16"}
    assert m.get("D-A10").intent == "metric_derived"
    assert m.get("D-A10").min_n == 13
    assert m.get("D-A10").data_scope == ("datacenter.series",)
    assert m.get("D-A10").mode == "deterministic"
    assert set(m.get("D-A11").methods) == {"M04"}
    assert m.get("D-A11").intent == "correlation_query"
    assert m.get("D-A11").min_n == 60
    assert m.get("D-A11").data_scope == ("datacenter.correlation",)
    assert set(m.get("D-A12").methods) == {"M11", "M12"}
    assert m.get("D-A12").intent == "correlation_query"
    assert m.get("D-A12").min_n == 120
    assert m.get("D-A12").data_scope == ("datacenter.correlation",)
    assert set(m.get("D-A13").methods) == {"S11"}
    assert m.get("D-A13").intent == "metric_series"
    assert m.get("D-A13").min_n == 30
    assert m.get("D-A13").data_scope == ("datacenter.series",)
    assert set(m.get("D-A15").methods) == {"S20"}
    assert m.get("D-A15").intent == "metric_series"
    assert m.get("D-A15").min_n == 30
    assert m.get("D-A15").data_scope == ("datacenter.series",)
    assert set(m.get("D-A16").methods) == {"S16"}
    assert m.get("D-A16").intent == "metric_series"
    assert m.get("D-A16").min_n == 30
    assert m.get("D-A16").data_scope == ("datacenter.series",)
    assert set(m.get("D-B08").methods) == {"T08", "T09"}
    assert m.get("D-B08").intent == "technical_indicator"
    assert m.get("D-B08").min_n == 60
    assert m.get("D-B08").data_scope == ("market.candles",)
    assert set(m.get("D-B09").methods) == {"D20", "D21"}
    assert m.get("D-B09").intent == "technical_indicator"
    assert m.get("D-B09").min_n == 250
    assert m.get("D-B09").data_scope == ("market.candles",)
    assert set(m.get("D-G08").methods) == {"F14"}
    assert m.get("D-G08").intent == "metric_derived"
    assert m.get("D-G08").min_n == 60
    assert m.get("D-G08").data_scope == ("market.candles",)
    assert m.get("D-G08").mode == "deterministic"
    assert set(m.get("D-G09").methods) == {"P02"}
    assert m.get("D-G09").intent == "metric_derived"
    assert m.get("D-G09").min_n == 60
    assert m.get("D-G09").data_scope == ("market.candles",)
    assert m.get("D-G09").mode == "deterministic"
    for cap in m.capabilities:
        assert cap.executor.split(".")[-1] in {
            "seasonality",
            "correlation",
            "state_transition",
            "conditional_ic",
            "conditional_return",
            "conditional_distribution",
            "drawdown",
            "percentile_forward",
            "alignment_slice",
            "portfolio_risk",
            "ic_profile",
            "quantile_monotonic",
            "hac_significance",
            "crowding",
            "event_study",
            "event_car_significance",
            "seasonal_adjustment",
            "change_point",
            "tail_dependence",
            "cycle_spectrum",
            "count_series",
            "trend",
            "dimension_reduction",
            "correlation_network",
            "ewma_risk",
            "pit_alignment",
            "history_series",
            "change_rate",
            "cagr",
            "percentile_rank",
            "annualized_volatility",
            "yoy_change",
            "mom_change",
            "real_rate",
            "rolling_correlation",
            "lead_lag_correlation",
            "extreme_frequency",
            "etf_flow_rolling",
            "stablecoin_growth",
            "slope_trend",
            "ath_drawdown",
            "momentum_12_1",
            "vol_target_scale",
            "aggregate_curve",
            "class_board",
            "flow_graph",
            "lights",
            "news_digest",
            "zscore",
            "recommend_relationship",
            "discovery_query",
            "cross_section_profile",
            "group_neutralize",
            "quantile_portfolio",
            "dispersion_breadth",
            "co_movement",
            "factor_exposure",
            "sequence_operators",
            "inverse_volatility_weights",
            "equal_risk_contribution",
            "risk_contribution",
            "covariance_shrinkage",
            "pca_risk_decomposition",
            "brinson_attribution",
            "fama_macbeth",
            "factor_crowding",
            "trend_test",
            "outlier_scan",
            "smoothing_filter",
            "spectral_envelope",
            "state_space_filter",
            "coherence_analysis",
            "information_measures",
            "transfer_entropy",
            "complexity_measures",
            "long_memory",
            "tail_risk_extreme",
            "measurement_uncertainty",
            "interval_estimate",
            "power_sample_size",
            "equivalence_test",
            "group_comparison",
            "regression_diagnostics",
            "robust_regression",
            "cluster_structure",
            "spatial_autocorrelation",
            "survival_analysis",
            "reliability_metrics",
            "meta_analysis",
            "missing_data_profile",
        }


def test_manifest_every_declared_capability_is_runnable():
    assert set(supported()) == {cap.id for cap in manifest().capabilities}


def test_alignment_slice_executes_r18_and_returns_aligned_rows():
    out = run_capability("D-E12", **_alignment_kwargs())
    assert out["ok"] is True
    assert out["capability"] == "D-E12"
    assert out["intent"] == "cross_check"
    assert out["quality"]["status"] == STATUS_GOOD
    assert out["quality"]["sample_n"] == 30
    assert out["quality"]["align_method"] == "daily_last+ffill"
    block = out["data"]["capabilities"]["D-E12"]
    assert block["methods"] == ["R18"]
    assert block["window"] == "2024-01-11~2024-02-09"
    assert block["assets"] == ["BTC", "ETH"]
    rows = {row["asset"]: row for row in block["window_rows"]}
    assert rows["BTC"]["start_value"] == 110.0
    assert rows["BTC"]["end_value"] == 139.0
    assert rows["ETH"]["start_value"] == 70.0
    assert rows["ETH"]["end_value"] == 128.0


def test_alignment_slice_insufficient_history_fails_open():
    out = run_capability("D-E12", **_alignment_kwargs(10))
    assert out["ok"] is False
    assert out["quality"]["status"] == STATUS_EMPTY
    assert "样本" in out["answer"]


def test_alignment_slice_empty_window_fails_open():
    kwargs = _alignment_kwargs()
    kwargs["start"] = "2030-01-01"
    out = run_capability("D-E12", **kwargs)
    assert out["ok"] is False
    assert out["quality"]["status"] == STATUS_EMPTY
    assert "样本" in out["answer"]


# ---------------- D-G22 HAC 显著性 ----------------


def test_hac_significance_returns_newey_west_and_deflated_sharpe():
    out = run_capability("D-G22", series=_ar1(400), n_trials=10)
    assert out["ok"] is True
    assert out["capability"] == "D-G22"
    assert out["intent"] == "significance_query"
    assert out["quality"]["status"] == STATUS_GOOD
    assert out["quality"]["sample_n"] == 400
    assert out["quality"]["align_method"] == "hac_newey_west"
    block = out["data"]["capabilities"]["D-G22"]
    assert block["methods"] == ["Q06", "Q07"]
    assert block["newey_west"]["lag"] >= 1
    assert block["newey_west"]["se"] > 0
    assert 0.0 < block["deflated_sharpe"]["dsr"] < 1.0
    assert block["deflated_sharpe"]["n_trials"] == 10
    assert out["data"]["params"]["n_trials"] == 10
    assert "历史统计" in out["answer"]


def test_hac_significance_reuses_method_layer_without_recomputing():
    import l1agg.methods as methods

    series = _ar1(500, seed=11)
    out = run_capability("D-G22", series=series)
    block = out["data"]["capabilities"]["D-G22"]
    assert block["newey_west"] == methods.run("Q06", {"series": series})["result"]
    assert block["deflated_sharpe"] == methods.run("Q07", {"series": series}, n_trials=1)["result"]


def test_hac_significance_insufficient_history_fails_open():
    out = run_capability("D-G22", series=_ar1(120))
    assert out["ok"] is False
    assert out["quality"]["status"] == STATUS_EMPTY
    assert "样本" in out["answer"]


def test_hac_significance_degenerate_series_degrades_partial():
    out = run_capability("D-G22", series=[0.0] * 300)
    assert out["ok"] is True
    assert out["quality"]["status"] == STATUS_PARTIAL
    assert out["quality"]["degraded_reason"] == "dsr_unavailable"
    assert "降级" in out["answer"]
    block = out["data"]["capabilities"]["D-G22"]
    assert block["deflated_sharpe"] is None
    assert block["newey_west"]["t_nw"] is None


# ---------------- D-G16 组合 VaR / CVaR ----------------


def test_portfolio_risk_returns_portfolio_and_per_asset_tail_risk():
    series = _portfolio_returns()
    dates = _dates(len(series["BTC"]))
    out = run_capability(
        "D-G16",
        series=series,
        weights={"BTC": 0.6, "ETH": 0.4},
        dates=dates,
        name="核心组合",
    )
    assert out["ok"] is True
    assert out["capability"] == "D-G16"
    assert out["intent"] == "metric_series"
    assert out["quality"]["status"] == STATUS_GOOD
    assert out["quality"]["sample_n"] == 160
    assert out["quality"]["align_method"] == "min_common_length"
    assert out["quality"]["span"] == [dates[0], dates[-1]]
    block = out["data"]["capabilities"]["D-G16"]
    assert block["methods"] == ["D17", "D18", "P09", "P10"]
    assert block["symbols"] == ["BTC", "ETH"]
    assert block["portfolio"]["parametric"]["var"] > 0
    assert block["portfolio"]["historical"]["cvar"] >= block["portfolio"]["historical"]["var_hist"]
    assert set(block["assets"]) == {"BTC", "ETH"}
    assert block["assets"]["BTC"]["var"]["n"] == 160
    assert block["assets"]["ETH"]["cvar"]["n"] == 160
    assert out["data"]["params"]["quantile"] == 0.05
    assert out["data"]["params"]["as_of"] == dates[-1]
    assert "损失正数口径" in out["answer"] and "历史统计" in out["answer"]


def test_portfolio_risk_reuses_methods_and_aligns_min_common_length():
    import l1agg.methods as methods

    series = _portfolio_returns(140, seed=29)
    series["ETH"].extend([0.01, -0.02, 0.03])
    weights = {"BTC": 2.0, "ETH": 1.0}
    out = run_capability("D-G16", series=series, weights=weights, quantile=0.1)
    block = out["data"]["capabilities"]["D-G16"]
    payload = {"series": series, "weights": weights}
    assert out["quality"]["sample_n"] == 140
    assert block["portfolio"]["parametric"] == methods.run("P09", payload)["result"]
    assert block["portfolio"]["historical"] == methods.run("P10", payload, quantile=0.1)["result"]
    for symbol in ("BTC", "ETH"):
        aligned = series[symbol][:140]
        assert block["assets"][symbol]["var"] == methods.run("D17", aligned, q=10.0)["result"]
        assert block["assets"][symbol]["cvar"] == methods.run("D18", aligned, q=10.0)["result"]


def test_portfolio_risk_empty_or_insufficient_history_fails_open():
    short = run_capability("D-G16", series=_portfolio_returns(59))
    assert short["ok"] is False
    assert short["quality"]["status"] == STATUS_EMPTY
    assert "60" in short["answer"]
    empty = run_capability("D-G16", series={})
    assert empty["ok"] is False
    assert empty["quality"]["status"] == STATUS_EMPTY


# ---------------- D-G19 IC / ICIR / 衰减表 ----------------


def test_ic_profile_returns_research_and_price_decay_tables():
    import l1agg.methods as methods

    factor, forward, prices = _ic_inputs()
    dates = _dates(len(factor))
    out = run_capability(
        "D-G19",
        factor=factor,
        forward=forward,
        prices=prices,
        dates=dates,
        name="TEST",
    )
    assert out["ok"] is True
    assert out["capability"] == "D-G19"
    assert out["intent"] == "metric_series"
    assert out["quality"]["status"] == STATUS_GOOD
    assert out["quality"]["sample_n"] == len(factor)
    assert out["quality"]["align_method"] == "paired_complete_case"
    assert out["quality"]["span"] == [dates[0], dates[-1]]
    block = out["data"]["capabilities"]["D-G19"]
    assert block["methods"] == ["B13", "B14", "B15", "Q01", "Q02", "Q03"]
    assert block["ic"]["ic"] > 0.5
    assert block["rank_ic"]["rank_ic"] > 0.5
    assert block["research_ic"]["ic"] == block["ic"]["ic"]
    expected_h1 = methods.run("Q01", {"factor": factor[:-1], "forward": forward[:-1]})["result"][
        "ic"
    ]
    assert block["ic_decay"]["ic_by_h"]["1"] == expected_h1
    assert block["icir"]["n_periods"] == 16
    assert block["ic_decay"]["horizons"] == [1, 3, 5, 10, 20]
    assert [item["h"] for item in block["price_ic_decay"]["items"]] == [1, 3, 5, 10, 20]
    assert out["data"]["params"]["as_of"] == dates[-1]
    assert "IC=" in out["answer"] and "ICIR=" in out["answer"]
    assert "历史统计" in out["answer"]


def test_ic_profile_reuses_all_six_methods_after_complete_case_alignment():
    import l1agg.methods as methods

    factor, forward, prices = _ic_inputs()
    dirty_factor, dirty_forward = list(factor), list(forward)
    for index, pair in {
        3: (None, forward[3]),
        41: (factor[41], "invalid"),
        127: (None, None),
    }.items():
        dirty_factor[index], dirty_forward[index] = pair
    keep = [i for i in range(len(factor)) if i not in {3, 41, 127}]
    aligned_factor = [factor[i] for i in keep]
    aligned_forward = [forward[i] for i in keep]
    pair = {"factor": aligned_factor, "target": aligned_forward}
    decay_pair = {"factor": aligned_factor, "returns": [0.0] + aligned_forward[:-1]}
    horizons = (1, 5, 20)

    out = run_capability(
        "D-G19",
        factor=dirty_factor,
        forward=dirty_forward,
        prices=prices,
        window=25,
        horizons=horizons,
    )
    block = out["data"]["capabilities"]["D-G19"]
    assert out["quality"]["sample_n"] == len(keep)
    assert block["ic"] == methods.run("B13", pair)["result"]
    assert block["rank_ic"] == methods.run("B14", pair)["result"]
    assert block["research_ic"] == methods.run("Q01", pair)["result"]
    assert block["icir"] == methods.run("Q02", pair, window=25)["result"]
    assert block["ic_decay"] == methods.run("Q03", decay_pair, horizons=horizons)["result"]
    assert (
        block["price_ic_decay"]
        == methods.run("B15", prices, lookback=20, horizons=horizons)["result"]
    )


def test_ic_profile_missing_price_degrades_and_short_pairs_fail_open():
    factor, forward, _ = _ic_inputs()
    partial = run_capability("D-G19", factor=factor, forward=forward)
    assert partial["ok"] is True
    assert partial["quality"]["status"] == STATUS_PARTIAL
    assert partial["quality"]["degraded_reason"] == "price_history_unavailable"
    block = partial["data"]["capabilities"]["D-G19"]
    assert block["methods"] == ["B13", "B14", "Q01", "Q02", "Q03"]
    assert block["price_ic_decay"] is None
    assert "B15" in partial["answer"] and "降级" in partial["answer"]

    short = run_capability("D-G19", factor=factor[:249], forward=forward[:249])
    assert short["ok"] is False
    assert short["quality"]["status"] == STATUS_EMPTY
    assert "250" in short["answer"]
    empty = run_capability("D-G19", factor=[], forward=[])
    assert empty["ok"] is False and empty["quality"]["status"] == STATUS_EMPTY


# ---------------- D-G20 分位组合 / 单调性检验 ----------------


def test_quantile_monotonic_returns_group_stats_and_spearman_test():
    factor, forward = _quantile_inputs()
    dates = _dates(len(factor))
    out = run_capability("D-G20", factor=factor, forward=forward, dates=dates, k=5, name="TEST")

    assert out["ok"] is True
    assert out["capability"] == "D-G20"
    assert out["intent"] == "metric_series"
    assert out["quality"]["status"] == STATUS_GOOD
    assert out["quality"]["sample_n"] == len(factor)
    assert out["quality"]["align_method"] == "paired_complete_case"
    assert out["quality"]["span"] == [dates[0], dates[-1]]
    block = out["data"]["capabilities"]["D-G20"]
    assert block["methods"] == ["B11", "B16", "Q04"]
    grouped = block["group_stats"]
    assert grouped["k"] == 5 and grouped["n"] == len(factor)
    assert len(grouped["table"]) == 5
    assert sum(row["n"] for row in grouped["table"]) == len(factor)
    assert grouped["spread"] > 0
    assert block["monotonic"]["monotonic"] == "increasing"
    assert block["monotonic"]["rho_bin"] == pytest.approx(1.0)
    quantile_test = block["quantile_test"]
    assert quantile_test["monotonic"] == "increasing"
    assert quantile_test["rho"] > 0.99
    assert quantile_test["p"] < 0.05
    assert quantile_test["bucket_returns"] == {
        str(row["bucket"]): row["mean"] for row in grouped["table"]
    }
    assert out["data"]["params"]["as_of"] == dates[-1]
    assert "描述性" in out["answer"] and "历史统计" in out["answer"]
    assert not any(word in out["answer"] for word in ("将会", "预计", "必然"))


def test_quantile_monotonic_reuses_methods_after_complete_case():
    import l1agg.methods as methods

    factor, forward = _quantile_inputs(300)
    dirty_factor, dirty_forward = list(factor), list(forward)
    missing = {3, 41, 127, 269}
    dirty_factor[3] = None
    dirty_forward[41] = "invalid"
    dirty_factor[127] = None
    dirty_forward[127] = None
    dirty_forward[269] = float("nan")
    keep = [i for i in range(len(factor)) if i not in missing]
    aligned_factor = [factor[i] for i in keep]
    aligned_forward = [forward[i] for i in keep]
    pair = {"factor": aligned_factor, "target": aligned_forward}

    out = run_capability("D-G20", factor=dirty_factor, forward=dirty_forward, k=4)
    block = out["data"]["capabilities"]["D-G20"]
    assert out["quality"]["sample_n"] == len(keep)
    assert block["group_stats"] == methods.run("B16", pair, k=4)["result"]
    assert block["monotonic"] == methods.run("B11", pair, k=4)["result"]
    assert block["quantile_test"] == methods.run("Q04", pair, k=4)["result"]


def test_quantile_monotonic_short_or_invalid_input_fails_open():
    factor, forward = _quantile_inputs()
    short = run_capability("D-G20", factor=factor[:249], forward=forward[:249])
    assert short["ok"] is False
    assert short["quality"]["status"] == STATUS_EMPTY
    assert "250" in short["answer"]

    empty = run_capability("D-G20", factor=[], forward=[])
    assert empty["ok"] is False and empty["quality"]["status"] == STATUS_EMPTY

    invalid_k = run_capability("D-G20", factor=factor, forward=forward, k=1)
    assert invalid_k["ok"] is False
    assert invalid_k["quality"]["status"] == STATUS_EMPTY


def _network_inputs(n=160, groups=6, size=6, seed=41, phi=0.9):
    """多簇相关网络（D-J24 输入）：每组共享独立 AR(1) 因子，组内高相关、组间近似独立。"""
    rng = random.Random(seed)
    series = {}
    for group in range(groups):
        factor = [rng.gauss(0.0, 1.0)]
        for _ in range(n - 1):
            factor.append(phi * factor[-1] + rng.gauss(0.0, 1.0))
        for member in range(size):
            weight = 1.0 - 0.08 * member
            series[f"g{group}v{member}"] = [
                weight * value + rng.gauss(0.0, 0.03) for value in factor
            ]
    return series


def _ewma_inputs(n=160, assets=3, seed=51):
    """三资产收益面板（D-G14 输入）：低频正弦 + 独立噪声，模拟日收益量级。"""
    rng = random.Random(seed)
    return {
        f"asset{index}": [
            rng.gauss(0.0, 0.012) + 0.002 * math.sin(position / 9.0 + index)
            for position in range(n)
        ]
        for index in range(assets)
    }


# ---------------- D-J22 PCA / SVD / 因子分析 ----------------

DIMENSION_METHODS = ["M19", "M20", "SC31", "SC32", "SC33"]


def test_dimension_reduction_returns_pca_svd_and_factor_results():
    series = _panel_inputs()
    dates = _dates(320)
    out = run_capability("D-J22", series=series, dates=dates, k=3, name="TEST")
    assert out["ok"] is True
    assert out["capability"] == "D-J22"
    assert out["intent"] == "metric_series"
    assert out["quality"]["status"] == STATUS_GOOD
    assert out["quality"]["sample_n"] == 320
    assert out["quality"]["align_method"] == "panel_complete_case"
    assert out["quality"]["span"] == [dates[0], dates[-1]]
    block = out["data"]["capabilities"]["D-J22"]
    assert block["methods"] == DIMENSION_METHODS
    assert block["variables"] == sorted(series)
    assert block["pca_variance"]["k"] == 3
    assert len(block["pca_variance"]["ratio"]) == 3
    assert 0.0 < block["pca_variance"]["ratio"][0] <= 1.0
    assert block["pca_variance"]["cum_ratio"][-1] >= block["pca_variance"]["ratio"][0]
    assert set(block["pca_loadings"]["loadings"][0]) == set(series)
    assert block["sklearn_pca"]["k"] == 3
    assert len(block["svd"]["s"]) == 3
    assert block["factor_analysis"]["k"] == 3
    assert out["data"]["params"]["min_n"] == 60
    assert out["data"]["params"]["as_of"] == dates[-1]
    assert "历史统计" in out["answer"] and "不构成交易信号" in out["answer"]


def test_dimension_reduction_reuses_methods_after_panel_complete_case():
    import l1agg.methods as methods

    series = _panel_inputs(260, seed=31)
    dirty = {name: list(values) for name, values in series.items()}
    missing = {3, 41, 127}
    for index in missing:
        dirty["alpha"][index] = None
        dirty["beta"][index] = "bad"
        dirty["gamma"][index] = float("nan")
        dirty["delta"][index] = None
    keep = [index for index in range(260) if index not in missing]
    cleaned = {name: [series[name][index] for index in keep] for name in sorted(series)}
    payload = {"series": cleaned}
    matrix_payload = {
        "X": [[cleaned[name][position] for name in cleaned] for position in range(len(keep))]
    }

    out = run_capability("D-J22", series=dirty, k=2)
    block = out["data"]["capabilities"]["D-J22"]
    assert out["quality"]["sample_n"] == len(keep)
    assert block["pca_variance"] == methods.run("M19", payload, k=2)["result"]
    assert block["pca_loadings"] == methods.run("M20", payload, k=2)["result"]
    assert block["sklearn_pca"] == methods.run("SC31", matrix_payload, k=2)["result"]
    assert block["svd"] == methods.run("SC32", matrix_payload, k=2)["result"]
    assert block["factor_analysis"] == methods.run("SC33", matrix_payload, k=2)["result"]


def test_dimension_reduction_short_or_invalid_input_fails_open():
    series = _panel_inputs()
    short = run_capability("D-J22", series={name: values[:59] for name, values in series.items()})
    assert short["ok"] is False
    assert short["quality"]["status"] == STATUS_EMPTY
    assert "60" in short["answer"]

    empty = run_capability("D-J22", series={})
    assert empty["ok"] is False and empty["quality"]["status"] == STATUS_EMPTY

    invalid_k = run_capability("D-J22", series=series, k=0)
    assert invalid_k["ok"] is False and invalid_k["quality"]["status"] == STATUS_EMPTY

    single = run_capability("D-J22", series={"alpha": series["alpha"]})
    assert single["ok"] is False and single["quality"]["status"] == STATUS_EMPTY


# ---------------- D-J24 相关网络与社区发现 ----------------

NETWORK_METHODS = ["M05", "M21", "SC71", "SC72"]


def test_correlation_network_returns_centrality_communities_and_clusters():
    series = _network_inputs()
    dates = _dates(160)
    out = run_capability("D-J24", series=series, dates=dates, k=6, threshold=0.5, name="TEST")
    assert out["ok"] is True
    assert out["capability"] == "D-J24"
    assert out["intent"] == "metric_series"
    assert out["quality"]["status"] == STATUS_GOOD
    assert out["quality"]["sample_n"] == 160
    assert out["quality"]["align_method"] == "panel_complete_case"
    assert out["quality"]["span"] == [dates[0], dates[-1]]
    block = out["data"]["capabilities"]["D-J24"]
    assert block["methods"] == NETWORK_METHODS
    assert block["nodes"] == sorted(series)
    assert block["n_edges"] > 0
    assert block["threshold"] == 0.5
    assert block["centrality"]["n_nodes"] == 36
    assert len(block["centrality"]["betweenness"]) == 36
    assert isinstance(block["centrality"]["top_node"], int)
    assert block["communities"]["n_communities"] == 6
    assert block["communities"]["modularity"] > 0.3
    assert len(block["hierarchical"]["labels"]) == 36
    assert block["hierarchical"]["n_clusters"] == 6
    assert out["data"]["params"]["min_n"] == 60
    assert "历史统计" in out["answer"] and "不构成交易信号" in out["answer"]


def test_correlation_network_reuses_methods_after_panel_complete_case():
    import l1agg.methods as methods

    series = _network_inputs(140, size=5, seed=43)
    dirty = {name: list(values) for name, values in series.items()}
    missing = {5, 77, 139}
    for index in missing:
        dirty["g0v0"][index] = None
        dirty["g1v0"][index] = "bad"
        dirty["g2v0"][index] = float("nan")
        dirty["g3v0"][index] = None
    keep = [index for index in range(140) if index not in missing]
    cleaned = {name: [series[name][index] for index in keep] for name in sorted(series)}
    payload = {"series": cleaned}
    matrix_result = methods.run("M05", payload)["result"]
    names = matrix_result["names"]
    adjacency = [
        [
            0.0 if left == right or abs(matrix_result["matrix"][left][right]) < 0.5 else 1.0
            for right in names
        ]
        for left in names
    ]
    graph_payload = {"adj": adjacency}

    out = run_capability("D-J24", series=dirty, k=6, threshold=0.5)
    block = out["data"]["capabilities"]["D-J24"]
    assert out["quality"]["sample_n"] == len(keep)
    assert block["correlation"] == matrix_result
    assert block["hierarchical"] == methods.run("M21", payload, k=6)["result"]
    assert block["centrality"] == methods.run("SC71", graph_payload)["result"]
    assert block["communities"] == methods.run("SC72", graph_payload)["result"]


def test_correlation_network_short_or_invalid_input_fails_open():
    series = _network_inputs()
    short = run_capability("D-J24", series={name: values[:59] for name, values in series.items()})
    assert short["ok"] is False
    assert short["quality"]["status"] == STATUS_EMPTY
    assert "60" in short["answer"]

    empty = run_capability("D-J24", series={})
    assert empty["ok"] is False and empty["quality"]["status"] == STATUS_EMPTY

    invalid_threshold = run_capability("D-J24", series=series, threshold=1.5)
    assert invalid_threshold["ok"] is False
    assert invalid_threshold["quality"]["status"] == STATUS_EMPTY

    invalid_k = run_capability("D-J24", series=series, k=0)
    assert invalid_k["ok"] is False and invalid_k["quality"]["status"] == STATUS_EMPTY


def test_correlation_network_small_graph_degrades_open():
    series = _network_inputs(n=120, groups=1, size=3, seed=47)
    out = run_capability("D-J24", series=series, k=2, threshold=0.5)
    assert out["ok"] is True
    assert out["quality"]["status"] == STATUS_PARTIAL
    assert "门禁" in out["quality"]["degraded_reason"]


# ---------------- D-G14 EWMA 波动 / 协方差 ----------------


def test_ewma_risk_returns_panel_covariance_and_volatility_series():
    panel = _ewma_inputs()
    dates = _dates(160)
    out = run_capability("D-G14", series=panel, dates=dates, lam=0.94, periods=365, name="TEST")
    assert out["ok"] is True
    assert out["capability"] == "D-G14"
    assert out["intent"] == "metric_series"
    assert out["quality"]["status"] == STATUS_GOOD
    assert out["quality"]["sample_n"] == 160
    assert out["quality"]["align_method"] == "panel_complete_case"
    assert out["quality"]["span"] == [dates[0], dates[-1]]
    block = out["data"]["capabilities"]["D-G14"]
    assert block["methods"] == ["P07", "T19"]
    assert block["lam"] == 0.94
    assert block["covariance"]["symbols"] == sorted(panel)
    assert len(block["covariance"]["cov"]) == 3
    assert len(block["covariance"]["cov"][0]) == 3
    assert set(block["covariance"]["vol"]) == set(panel)
    assert set(block["volatility_series"]) == set(panel)
    for result in block["volatility_series"].values():
        assert len(result["series"]) == 160
        assert result["lam"] == 0.94
    assert out["data"]["params"]["min_n"] == 60
    assert out["data"]["params"]["periods"] == 365
    assert "历史统计" in out["answer"] and "不构成交易信号" in out["answer"]


def test_ewma_risk_reuses_methods_after_panel_complete_case():
    import l1agg.methods as methods

    panel = _ewma_inputs(140, seed=53)
    dirty = {name: list(values) for name, values in panel.items()}
    missing = {4, 66, 139}
    for index in missing:
        dirty["asset0"][index] = None
        dirty["asset1"][index] = "bad"
        dirty["asset2"][index] = float("nan")
    keep = [index for index in range(140) if index not in missing]
    cleaned = {name: [panel[name][index] for index in keep] for name in sorted(panel)}

    out = run_capability("D-G14", series=dirty, lam=0.94, periods=365)
    block = out["data"]["capabilities"]["D-G14"]
    assert out["quality"]["sample_n"] == len(keep)
    assert (
        block["covariance"]
        == methods.run("P07", {"series": cleaned}, lam=0.94, periods=365)["result"]
    )
    for name in cleaned:
        assert (
            block["volatility_series"][name]
            == methods.run("T19", {"series": cleaned[name]}, lam=0.94)["result"]
        )


def test_ewma_risk_single_asset_runs_volatility_only():
    panel = _ewma_inputs()
    out = run_capability("D-G14", series={"asset0": panel["asset0"]}, lam=0.94)
    assert out["ok"] is True
    block = out["data"]["capabilities"]["D-G14"]
    assert block["methods"] == ["T19"]
    assert "covariance" not in block
    assert len(block["volatility_series"]["asset0"]["series"]) == 160


def test_ewma_risk_short_or_invalid_input_fails_open():
    panel = _ewma_inputs()
    short = run_capability("D-G14", series={name: values[:59] for name, values in panel.items()})
    assert short["ok"] is False
    assert short["quality"]["status"] == STATUS_EMPTY
    assert "60" in short["answer"]

    empty = run_capability("D-G14", series={})
    assert empty["ok"] is False and empty["quality"]["status"] == STATUS_EMPTY

    invalid_lam = run_capability("D-G14", series=panel, lam=1.5)
    assert invalid_lam["ok"] is False
    assert invalid_lam["quality"]["status"] == STATUS_EMPTY

    invalid_periods = run_capability("D-G14", series=panel, periods=0)
    assert invalid_periods["ok"] is False
    assert invalid_periods["quality"]["status"] == STATUS_EMPTY


# ---------------- D-A01 历史序列 ----------------


def test_history_series_returns_points_span_and_percentile():
    values, dates = _series_inputs()
    out = run_capability("D-A01", values=values, dates=dates, name="恐惧贪婪", unit="分")
    assert out["ok"] is True
    assert out["capability"] == "D-A01"
    assert out["intent"] == "metric_series"
    assert out["quality"]["status"] == STATUS_GOOD
    assert out["quality"]["sample_n"] == 120
    assert out["quality"]["span"] == [dates[0], dates[-1]]
    assert out["quality"]["align_method"] == "series_last_per_daily"
    block = out["data"]["capabilities"]["D-A01"]
    assert block["methods"] == ["S25"]
    assert block["freq"] == "daily"
    assert len(block["points"]) == 120
    assert block["points"][0] == {"date": dates[0], "value": round(values[0], 6)}
    assert block["span"] == [dates[0], dates[-1]]
    assert block["unit"] == "分"
    assert block["percentile"]["value"] == round(values[-1], 6)
    assert 0.0 <= block["percentile"]["percentile"] <= 100.0
    assert out["data"]["params"]["min_n"] == 30
    assert "处于历史" in out["answer"]


def test_history_series_downsamples_week_and_month_with_last_observation():
    import l1agg.methods as methods

    values, dates = _series_inputs(n=90, seed=53)
    daily = run_capability("D-A01", values=values, dates=dates, freq="daily")
    daily_block = daily["data"]["capabilities"]["D-A01"]
    assert daily_block["percentile"] == methods.run("S25", values)["result"]

    weekly = run_capability("D-A01", values=values, dates=dates, freq="week")
    weekly_block = weekly["data"]["capabilities"]["D-A01"]
    assert weekly_block["freq"] == "weekly"
    assert 12 <= len(weekly_block["points"]) <= 14
    assert weekly_block["points"][-1]["date"] == dates[-1]
    assert weekly_block["points"][-1]["value"] == round(values[-1], 6)
    weeks = [
        datetime.date.fromisoformat(point["date"]).isocalendar()[:2]
        for point in weekly_block["points"]
    ]
    assert len(weeks) == len(set(weeks))

    monthly = run_capability("D-A01", values=values, dates=dates, freq="monthly")
    monthly_block = monthly["data"]["capabilities"]["D-A01"]
    assert [point["date"][:7] for point in monthly_block["points"]] == [
        "2024-01",
        "2024-02",
        "2024-03",
    ]
    assert monthly_block["points"][-1]["value"] == round(values[-1], 6)

    duplicated = run_capability(
        "D-A01",
        values=[10.0, 12.0] + values[2:],
        dates=["2024-01-01", "2024-01-01"] + dates[2:],
    )
    dup_block = duplicated["data"]["capabilities"]["D-A01"]
    assert dup_block["points"][0] == {"date": "2024-01-01", "value": 12.0}


def test_history_series_flags_sparse_series():
    values, dates = _series_inputs(n=40)
    start = datetime.date.fromisoformat(dates[0])
    sparse_dates = [(start + datetime.timedelta(days=3 * i)).isoformat() for i in range(40)]
    out = run_capability("D-A01", values=values, dates=sparse_dates)
    assert out["ok"] is True
    assert out["quality"]["status"] == STATUS_PARTIAL
    assert out["quality"]["degraded_reason"] == "sparse_series"
    assert out["quality"]["missing_rate"] > 0.6
    block = out["data"]["capabilities"]["D-A01"]
    assert block["gate"] == "partial"
    assert len(block["points"]) == 40
    assert "缺失率" in out["answer"]


def test_history_series_short_or_invalid_input_fails_open():
    values, dates = _series_inputs()
    short = run_capability("D-A01", values=values[:29], dates=dates[:29])
    assert short["ok"] is False
    assert short["quality"]["status"] == STATUS_EMPTY
    assert "30" in short["answer"]

    mismatch = run_capability("D-A01", values=values, dates=dates[:-1])
    assert mismatch["ok"] is False and mismatch["quality"]["status"] == STATUS_EMPTY

    bad_freq = run_capability("D-A01", values=values, dates=dates, freq="quarter")
    assert bad_freq["ok"] is False and bad_freq["quality"]["status"] == STATUS_EMPTY


# ---------------- D-A02 变化率 ----------------


def test_change_rate_returns_diff_and_pct():
    values, dates = _series_inputs(n=12, seed=67)
    out = run_capability("D-A02", values=values, dates=dates, window=5, name="持仓量", unit="手")
    assert out["ok"] is True
    assert out["capability"] == "D-A02"
    assert out["intent"] == "metric_series"
    assert out["quality"]["status"] == STATUS_GOOD
    assert out["quality"]["sample_n"] == 12
    assert out["quality"]["align_method"] == "window_endpoints"
    block = out["data"]["capabilities"]["D-A02"]
    assert block["methods"] == ["S15", "S16"]
    assert block["window"] == 5
    assert block["change"] == round(values[-1] - values[-6], 6)
    assert block["change_pct"] == round(values[-1] / values[-6] - 1.0, 6)
    assert out["data"]["params"]["min_n"] == 2
    assert "变化率" in out["answer"]


def test_change_rate_reuses_s15_and_s16():
    import l1agg.methods as methods

    values, _ = _series_inputs(n=10, seed=71)
    out = run_capability("D-A02", values=values, window=3)
    block = out["data"]["capabilities"]["D-A02"]
    assert block["change"] == methods.run("S15", values, k=3)["result"]["diff"]
    assert block["change_pct"] == methods.run("S16", values, k=3)["result"]["pct"]


def test_change_rate_degrades_when_base_value_is_zero():
    values = [0.0, 1.0, 2.0, 3.0, 4.0]
    out = run_capability("D-A02", values=values, window=4)
    assert out["ok"] is True
    assert out["quality"]["status"] == STATUS_PARTIAL
    assert out["quality"]["degraded_reason"] == "change_pct_unavailable"
    block = out["data"]["capabilities"]["D-A02"]
    assert block["gate"] == "partial"
    assert block["change"] == 4.0
    assert block["change_pct"] is None
    assert "变化率不可用" in out["answer"]


def test_change_rate_short_or_invalid_input_fails_open():
    single = run_capability("D-A02", values=[100.0])
    assert single["ok"] is False and single["quality"]["status"] == STATUS_EMPTY

    too_wide = run_capability("D-A02", values=[100.0, 101.0], window=2)
    assert too_wide["ok"] is False and too_wide["quality"]["status"] == STATUS_EMPTY
    assert "window" in too_wide["answer"]

    zero_window = run_capability("D-A02", values=[100.0, 101.0], window=0)
    assert zero_window["ok"] is False and zero_window["quality"]["status"] == STATUS_EMPTY

    invalid = run_capability("D-A02", values=[100.0, float("nan")])
    assert invalid["ok"] is False and invalid["quality"]["status"] == STATUS_EMPTY


# ---------------- D-A03 CAGR ----------------


def test_cagr_returns_annualized_growth():
    out = run_capability(
        "D-A03",
        values=[100.0, 200.0],
        dates=["2022-01-01", "2024-01-01"],
        name="净值",
    )
    assert out["ok"] is True
    assert out["capability"] == "D-A03"
    assert out["intent"] == "metric_series"
    assert out["quality"]["status"] == STATUS_GOOD
    assert out["quality"]["sample_n"] == 2
    assert out["quality"]["align_method"] == "first_last"
    assert out["quality"]["span"] == ["2022-01-01", "2024-01-01"]
    block = out["data"]["capabilities"]["D-A03"]
    assert block["methods"] == ["S19"]
    assert block["years"] == 2.0
    assert block["cagr"] == round(2.0 ** (365.0 / 730.0) - 1.0, 6)
    assert out["data"]["params"]["min_n"] == 2
    assert out["data"]["params"]["days"] == 730.0
    assert "CAGR" in out["answer"]


def test_cagr_reuses_s19():
    import l1agg.methods as methods

    values = [100.0, 80.0, 121.0]
    out = run_capability("D-A03", values=values, dates=_dates(3))
    block = out["data"]["capabilities"]["D-A03"]
    expected = methods.run("S19", values, days=2.0)["result"]
    assert block["cagr"] == expected["cagr"]
    assert block["years"] == expected["years"]
    assert block["n"] == expected["n"]


def test_cagr_degrades_for_span_under_one_year():
    out = run_capability(
        "D-A03",
        values=[100.0, 110.0],
        dates=["2024-01-01", "2024-04-10"],
    )
    assert out["ok"] is True
    assert out["quality"]["status"] == STATUS_PARTIAL
    assert out["quality"]["degraded_reason"] == "short_span"
    block = out["data"]["capabilities"]["D-A03"]
    assert block["gate"] == "partial"
    assert block["years"] < 1.0
    assert block["cagr"] > 0.0
    assert "不足 1 年" in out["answer"]


def test_cagr_invalid_input_fails_open():
    single = run_capability("D-A03", values=[100.0])
    assert single["ok"] is False and single["quality"]["status"] == STATUS_EMPTY
    assert "2" in single["answer"]

    non_positive = run_capability("D-A03", values=[0.0, 100.0])
    assert non_positive["ok"] is False
    assert non_positive["quality"]["status"] == STATUS_EMPTY

    same_day = run_capability("D-A03", values=[100.0, 110.0], dates=["2024-01-01", "2024-01-01"])
    assert same_day["ok"] is False and same_day["quality"]["status"] == STATUS_EMPTY

    bad_dates = run_capability("D-A03", values=[100.0, 110.0], dates=["2024-01-01"])
    assert bad_dates["ok"] is False and bad_dates["quality"]["status"] == STATUS_EMPTY


# ---------------- D-A04 历史分位 ----------------


def test_percentile_rank_returns_trailing_percentile():
    values, dates = _series_inputs(120, seed=91)
    out = run_capability("D-A04", values=values, dates=dates, lookback=60, name="资金费率")
    assert out["ok"] is True
    assert out["capability"] == "D-A04"
    assert out["intent"] == "metric_percentile"
    assert out["quality"]["status"] == STATUS_GOOD
    assert out["quality"]["sample_n"] == 60
    assert out["quality"]["align_method"] == "trailing_sample"
    assert out["quality"]["span"] == [dates[-60], dates[-1]]
    block = out["data"]["capabilities"]["D-A04"]
    assert block["methods"] == ["S25"]
    assert block["lookback"] == 60
    assert block["sample_n"] == 60
    assert block["value"] == round(values[-1], 6)
    assert 0.0 <= block["percentile"] <= 100.0
    assert out["data"]["params"]["min_n"] == 30
    assert out["data"]["params"]["lookback"] == 60
    assert "分位" in out["answer"]


def test_percentile_rank_reuses_s25():
    import l1agg.methods as methods

    values, _ = _series_inputs(90, seed=97)
    out = run_capability("D-A04", values=values, lookback=45)
    block = out["data"]["capabilities"]["D-A04"]
    expected = methods.run("S25", values[-45:])["result"]
    assert block["percentile"] == expected["percentile"]
    assert block["value"] == expected["value"]
    assert block["sample_n"] == expected["n"]


def test_percentile_rank_degrades_for_short_or_truncated_lookback():
    values, dates = _series_inputs(120, seed=101)
    short = run_capability("D-A04", values=values, lookback=40, dates=dates)
    assert short["ok"] is True
    assert short["quality"]["status"] == STATUS_PARTIAL
    assert short["quality"]["degraded_reason"] == "short_lookback"
    assert short["data"]["capabilities"]["D-A04"]["gate"] == "partial"
    assert "样本" in short["answer"]

    truncated = run_capability("D-A04", values=values, lookback=200)
    assert truncated["ok"] is True
    assert truncated["quality"]["status"] == STATUS_PARTIAL
    assert truncated["quality"]["degraded_reason"] == "lookback_truncated"
    assert truncated["data"]["capabilities"]["D-A04"]["lookback"] == 120
    assert "可用历史" in truncated["answer"]


def test_percentile_rank_invalid_input_fails_open():
    short = run_capability("D-A04", values=_series_inputs(29, seed=103)[0])
    assert short["ok"] is False and short["quality"]["status"] == STATUS_EMPTY
    assert "30" in short["answer"]

    small_lookback = run_capability("D-A04", values=_series_inputs(60, seed=105)[0], lookback=10)
    assert small_lookback["ok"] is False
    assert small_lookback["quality"]["status"] == STATUS_EMPTY

    bad_dates = run_capability("D-A04", values=_series_inputs(40, seed=107)[0], dates=_dates(39))
    assert bad_dates["ok"] is False and bad_dates["quality"]["status"] == STATUS_EMPTY

    invalid = run_capability("D-A04", values=[None] * 40)
    assert invalid["ok"] is False and invalid["quality"]["status"] == STATUS_EMPTY


# ---------------- D-A06 年化波动率 ----------------


def test_annualized_volatility_returns_full_envelope():
    values, dates = _series_inputs(150, seed=111)
    out = run_capability("D-A06", values=values, dates=dates, window=120, name="BTC 价格")
    assert out["ok"] is True
    assert out["capability"] == "D-A06"
    assert out["intent"] == "metric_series"
    assert out["quality"]["status"] == STATUS_GOOD
    assert out["quality"]["sample_n"] == 120
    assert out["quality"]["align_method"] == "trailing_sample"
    assert out["quality"]["span"] == [dates[-120], dates[-1]]
    block = out["data"]["capabilities"]["D-A06"]
    assert block["methods"] == ["F05"]
    assert block["window"] == 120
    assert block["sample_n"] == 120
    assert block["volatility"] > 0.0
    assert out["data"]["params"] == {"min_n": 30, "window": 120, "ann_factor": 365}
    assert "年化波动率" in out["answer"]


def test_annualized_volatility_reuses_f05():
    import l1agg.methods as methods

    values, _ = _series_inputs(100, seed=113)
    out = run_capability("D-A06", values=values, window=80)
    block = out["data"]["capabilities"]["D-A06"]
    expected = methods.run("F05", values[-80:])["result"]
    assert block["volatility"] == expected["vol"]
    assert block["mean_ret"] == expected["mean_ret"]
    assert block["sample_n"] == expected["n"]


def test_annualized_volatility_degrades_for_short_window():
    values, _ = _series_inputs(90, seed=115)
    out = run_capability("D-A06", values=values, window=40)
    assert out["ok"] is True
    assert out["quality"]["status"] == STATUS_PARTIAL
    assert out["quality"]["degraded_reason"] == "short_window"
    assert out["data"]["capabilities"]["D-A06"]["gate"] == "partial"
    assert "样本较短" in out["answer"]


def test_annualized_volatility_invalid_input_fails_open():
    short = run_capability("D-A06", values=_series_inputs(29, seed=117)[0])
    assert short["ok"] is False and short["quality"]["status"] == STATUS_EMPTY

    small_window = run_capability("D-A06", values=_series_inputs(90, seed=119)[0], window=20)
    assert small_window["ok"] is False and small_window["quality"]["status"] == STATUS_EMPTY

    bad_dates = run_capability("D-A06", values=_series_inputs(60, seed=121)[0], dates=_dates(59))
    assert bad_dates["ok"] is False and bad_dates["quality"]["status"] == STATUS_EMPTY

    invalid = run_capability("D-A06", values=[100.0] * 59 + [None])
    assert invalid["ok"] is False and invalid["quality"]["status"] == STATUS_EMPTY


# ---------------- D-A07 回撤 ----------------


def _drawdown_prices(n: int = 300) -> list:
    rising = [100.0 + i for i in range(n * 2 // 3)]
    falling = [rising[-1] - (i + 1) * 0.5 for i in range(n - len(rising))]
    return rising + falling


def test_drawdown_alias_returns_full_envelope():
    prices = _drawdown_prices()
    dates = _dates(len(prices))
    out = run_capability("D-A07", prices=prices, dates=dates, symbol="BTC-USDT")
    assert out["ok"] is True
    assert out["capability"] == "D-A07"
    assert out["intent"] == "drawdown_query"
    assert out["quality"]["status"] == STATUS_GOOD
    assert out["quality"]["sample_n"] == 300
    assert out["quality"]["align_method"] == "utc_daily_close"
    assert out["quality"]["span"] == [dates[0], dates[-1]]
    block = out["data"]["capabilities"]["D-A07"]
    assert block["methods"] == ["D20", "D21"]
    assert block["drawdown"] == round(1.0 - prices[-1] / max(prices), 6)
    assert block["peak_ts"] == dates[prices.index(max(prices))]
    assert block["mdd"] > 0.0
    assert out["data"]["params"]["min_n"] == 250
    assert "回撤" in out["answer"]


def test_drawdown_alias_matches_d_e10_executor():
    prices = _drawdown_prices()
    dates = _dates(len(prices))
    alias = run_capability("D-A07", prices=prices, dates=dates)
    base = run_capability("D-E10", prices=prices, dates=dates)
    alias_block = alias["data"]["capabilities"]["D-A07"]
    base_block = base["data"]["capabilities"]["D-E10"]
    assert alias_block["drawdown"] == base_block["current_drawdown"]
    assert alias_block["peak_ts"] == base_block["peak_date"]
    assert alias_block["mdd"] == base_block["mdd"]
    assert alias_block["duration_days"] == base_block["duration_days"]
    assert alias_block["drawdown_path"] == base_block["drawdown_path"]
    assert base["capability"] == "D-E10"


def test_drawdown_alias_degrades_for_short_history():
    prices = _drawdown_prices()[:100]
    out = run_capability("D-A07", prices=prices)
    assert out["ok"] is True
    assert out["quality"]["status"] == STATUS_PARTIAL
    assert out["quality"]["degraded_reason"] == "insufficient_samples"
    assert "样本不足" in out["answer"]


def test_drawdown_alias_invalid_input_fails_open():
    single = run_capability("D-A07", prices=[100.0])
    assert single["ok"] is False
    assert single["capability"] == "D-A07"
    assert single["quality"]["status"] == STATUS_EMPTY

    empty = run_capability("D-A07", prices=[])
    assert empty["ok"] is False and empty["quality"]["status"] == STATUS_EMPTY


# ---------------- D-A08 同比 ----------------


def _yoy_values(n: int = 36) -> list:
    return [100.0 + i * 2.0 for i in range(n)]


def test_yoy_change_returns_full_envelope():
    values = _yoy_values()
    dates = _dates(36)
    out = run_capability("D-A08", values=values, dates=dates, name="CPI", unit="点")
    assert out["ok"] is True
    assert out["capability"] == "D-A08"
    assert out["intent"] == "metric_series"
    assert out["quality"]["status"] == STATUS_GOOD
    assert out["quality"]["sample_n"] == 36
    assert out["quality"]["align_method"] == "period_offset"
    assert out["quality"]["span"] == [dates[-13], dates[-1]]
    block = out["data"]["capabilities"]["D-A08"]
    assert block["methods"] == ["S16"]
    assert block["period"] == 12
    assert block["yoy"] == round(values[-1] / values[-13] - 1.0, 6)
    assert block["base_ts"] == dates[-13]
    assert out["data"]["params"] == {"min_n": 13, "period": 12}
    assert "同比" in out["answer"]


def test_yoy_change_reuses_s16():
    import l1agg.methods as methods

    values = _yoy_values(30)
    out = run_capability("D-A08", values=values, period=6)
    block = out["data"]["capabilities"]["D-A08"]
    expected = methods.run("S16", values, k=6)["result"]
    assert block["yoy"] == expected["pct"]
    assert block["sample_n"] == expected["n"]
    assert block["period"] == 6


def test_yoy_change_degrades_for_short_history_or_zero_base():
    short = run_capability("D-A08", values=_yoy_values(18))
    assert short["ok"] is True
    assert short["quality"]["status"] == STATUS_PARTIAL
    assert short["quality"]["degraded_reason"] == "short_history"
    assert "2 个完整周期" in short["answer"]

    zero_base = _yoy_values(25)
    zero_base[12] = 0.0
    out = run_capability("D-A08", values=zero_base)
    assert out["ok"] is True
    assert out["quality"]["status"] == STATUS_PARTIAL
    assert out["quality"]["degraded_reason"] == "yoy_unavailable"
    assert out["data"]["capabilities"]["D-A08"]["yoy"] is None
    assert "基期值为 0" in out["answer"]


def test_yoy_change_invalid_input_fails_open():
    covered = run_capability("D-A08", values=_yoy_values(12))
    assert covered["ok"] is False and covered["quality"]["status"] == STATUS_EMPTY

    bad_period = run_capability("D-A08", values=_yoy_values(20), period=0)
    assert bad_period["ok"] is False and bad_period["quality"]["status"] == STATUS_EMPTY

    bad_dates = run_capability("D-A08", values=_yoy_values(20), dates=_dates(19))
    assert bad_dates["ok"] is False and bad_dates["quality"]["status"] == STATUS_EMPTY

    invalid = run_capability("D-A08", values=_yoy_values(20)[:-1] + [None])
    assert invalid["ok"] is False and invalid["quality"]["status"] == STATUS_EMPTY


# ---------------- D-A09 环比 ----------------


def test_mom_change_returns_full_envelope():
    values = _yoy_values(12)
    dates = _dates(12)
    out = run_capability("D-A09", values=values, dates=dates, name="社融", unit="亿元")
    assert out["ok"] is True
    assert out["capability"] == "D-A09"
    assert out["intent"] == "metric_series"
    assert out["quality"]["status"] == STATUS_GOOD
    assert out["quality"]["sample_n"] == 12
    assert out["quality"]["align_method"] == "period_offset"
    assert out["quality"]["span"] == [dates[-2], dates[-1]]
    block = out["data"]["capabilities"]["D-A09"]
    assert block["methods"] == ["S16"]
    assert block["mom"] == round(values[-1] / values[-2] - 1.0, 6)
    assert block["base_ts"] == dates[-2]
    assert out["data"]["params"] == {"min_n": 2, "period": 1}
    assert "环比" in out["answer"]


def test_mom_change_reuses_s16():
    import l1agg.methods as methods

    values = _yoy_values(8)
    out = run_capability("D-A09", values=values)
    block = out["data"]["capabilities"]["D-A09"]
    expected = methods.run("S16", values, k=1)["result"]
    assert block["mom"] == expected["pct"]
    assert block["sample_n"] == expected["n"]


def test_mom_change_degrades_for_zero_base():
    out = run_capability("D-A09", values=[100.0, 0.0, 50.0])
    assert out["ok"] is True
    assert out["quality"]["status"] == STATUS_PARTIAL
    assert out["quality"]["degraded_reason"] == "mom_unavailable"
    assert out["data"]["capabilities"]["D-A09"]["mom"] is None
    assert "基期值为 0" in out["answer"]


def test_mom_change_invalid_input_fails_open():
    single = run_capability("D-A09", values=[100.0])
    assert single["ok"] is False and single["quality"]["status"] == STATUS_EMPTY

    invalid = run_capability("D-A09", values=[100.0, None])
    assert invalid["ok"] is False and invalid["quality"]["status"] == STATUS_EMPTY

    bad_dates = run_capability("D-A09", values=_yoy_values(5), dates=_dates(4))
    assert bad_dates["ok"] is False and bad_dates["quality"]["status"] == STATUS_EMPTY


# ---------------- D-A10 实际利率 ----------------


def _real_rate_inputs(n: int = 36) -> tuple:
    nominal = [4.0 + 0.01 * i for i in range(n)]
    cpi = [100.0 + 0.2 * i for i in range(n)]
    return nominal, cpi


def test_real_rate_returns_full_envelope():
    import l1agg.methods as methods

    nominal, cpi = _real_rate_inputs()
    dates = _dates(36)
    out = run_capability("D-A10", nominal=nominal, cpi=cpi, dates=dates)
    assert out["ok"] is True
    assert out["capability"] == "D-A10"
    assert out["intent"] == "metric_derived"
    assert out["quality"]["status"] == STATUS_GOOD
    assert out["quality"]["sample_n"] == 36
    assert out["quality"]["align_method"] == "period_offset"
    assert out["quality"]["span"] == [dates[-13], dates[-1]]
    block = out["data"]["capabilities"]["D-A10"]
    assert block["methods"] == ["S16"]
    assert block["period"] == 12
    pct = methods.run("S16", cpi, k=12)["result"]["pct"]
    inflation = round(pct * 100.0, 6)
    assert block["inflation"] == inflation
    assert block["nominal"] == round(nominal[-1], 6)
    assert block["real_rate"] == round(nominal[-1] - inflation, 6)
    assert block["base_ts"] == dates[-13]
    assert out["data"]["params"] == {"min_n": 13, "period": 12, "unit": "%"}
    assert "实际利率" in out["answer"]


def test_real_rate_reuses_s16():
    import l1agg.methods as methods

    nominal, cpi = _real_rate_inputs(30)
    out = run_capability("D-A10", nominal=nominal, cpi=cpi, period=6)
    block = out["data"]["capabilities"]["D-A10"]
    expected = methods.run("S16", cpi, k=6)["result"]
    assert block["inflation"] == round(expected["pct"] * 100.0, 6)
    assert block["sample_n"] == expected["n"]
    assert block["period"] == 6


def test_real_rate_degrades_for_short_history_or_zero_base():
    nominal, cpi = _real_rate_inputs(18)
    short = run_capability("D-A10", nominal=nominal, cpi=cpi)
    assert short["ok"] is True
    assert short["quality"]["status"] == STATUS_PARTIAL
    assert short["quality"]["degraded_reason"] == "short_history"
    assert "2 个完整周期" in short["answer"]

    nominal, cpi = _real_rate_inputs(25)
    cpi[12] = 0.0
    out = run_capability("D-A10", nominal=nominal, cpi=cpi)
    assert out["ok"] is True
    assert out["quality"]["status"] == STATUS_PARTIAL
    assert out["quality"]["degraded_reason"] == "inflation_unavailable"
    assert out["data"]["capabilities"]["D-A10"]["real_rate"] is None
    assert out["data"]["capabilities"]["D-A10"]["inflation"] is None
    assert "基期值为 0" in out["answer"]


def test_real_rate_invalid_input_fails_open():
    nominal, cpi = _real_rate_inputs(12)
    covered = run_capability("D-A10", nominal=nominal, cpi=cpi)
    assert covered["ok"] is False and covered["quality"]["status"] == STATUS_EMPTY

    mismatched = run_capability(
        "D-A10", nominal=_real_rate_inputs(20)[0], cpi=_real_rate_inputs(19)[1]
    )
    assert mismatched["ok"] is False and mismatched["quality"]["status"] == STATUS_EMPTY

    bad_period = run_capability(
        "D-A10", nominal=_real_rate_inputs(20)[0], cpi=_real_rate_inputs(20)[1], period=0
    )
    assert bad_period["ok"] is False and bad_period["quality"]["status"] == STATUS_EMPTY

    bad_dates = run_capability(
        "D-A10", nominal=_real_rate_inputs(20)[0], cpi=_real_rate_inputs(20)[1], dates=_dates(19)
    )
    assert bad_dates["ok"] is False and bad_dates["quality"]["status"] == STATUS_EMPTY

    invalid = run_capability(
        "D-A10", nominal=_real_rate_inputs(20)[0][:-1] + [None], cpi=_real_rate_inputs(20)[1]
    )
    assert invalid["ok"] is False and invalid["quality"]["status"] == STATUS_EMPTY


# ---------------- D-A11 双序列滚动相关 ----------------


def _corr_pair(n: int = 80) -> tuple:
    x = [100.0 + 0.2 * i for i in range(n)]
    y = [50.0 + 0.1 * i for i in range(n)]
    return x, y


def test_rolling_correlation_returns_full_envelope():
    x, y = _corr_pair(90)
    dates = _dates(90)
    out = run_capability("D-A11", x=x, y=y, window=30, dates=dates)
    assert out["ok"] is True
    assert out["capability"] == "D-A11"
    assert out["intent"] == "correlation_query"
    assert out["quality"]["status"] == STATUS_GOOD
    assert out["quality"]["sample_n"] == 90
    assert out["quality"]["align_method"] == "paired_complete_case"
    assert out["quality"]["span"] == [dates[0], dates[-1]]
    block = out["data"]["capabilities"]["D-A11"]
    assert block["methods"] == ["M04"]
    assert block["window"] == 30
    assert block["n_windows"] == 61
    assert block["corr"] == 1.0
    assert block["mean_r"] == 1.0
    assert block["sample_n"] == 90
    assert out["data"]["params"] == {"min_n": 60, "window": 30}
    assert "滚动 Pearson 相关" in out["answer"]


def test_rolling_correlation_reuses_m04():
    import l1agg.methods as methods

    x, y = _corr_pair(70)
    out = run_capability("D-A11", x=x, y=y, window=40)
    block = out["data"]["capabilities"]["D-A11"]
    expected = methods.run("M04", {"x": x, "y": y}, window=40)["result"]
    assert block["corr"] == [value for value in expected["r"] if value is not None][-1]
    assert block["mean_r"] == expected["mean_r"]
    assert block["n_windows"] == expected["n_windows"]
    assert block["sample_n"] == expected["sample_n"]


def test_rolling_correlation_degrades_for_short_sample():
    x, y = _corr_pair(40)
    out = run_capability("D-A11", x=x, y=y, window=30)
    assert out["ok"] is True
    assert out["quality"]["status"] == STATUS_PARTIAL
    assert out["quality"]["degraded_reason"] == "insufficient_samples"
    assert "样本不足" in out["answer"]
    assert out["data"]["capabilities"]["D-A11"]["corr"] is not None


def test_rolling_correlation_invalid_input_fails_open():
    x, y = _corr_pair(20)

    single = run_capability("D-A11", x=[1.0], y=[1.0])
    assert single["ok"] is False and single["quality"]["status"] == STATUS_EMPTY

    bad_window = run_capability("D-A11", x=x, y=y, window=1)
    assert bad_window["ok"] is False and bad_window["quality"]["status"] == STATUS_EMPTY

    too_wide = run_capability("D-A11", x=x, y=y, window=30)
    assert too_wide["ok"] is False and too_wide["quality"]["status"] == STATUS_EMPTY

    bad_dates = run_capability("D-A11", x=x, y=y, dates=_dates(19))
    assert bad_dates["ok"] is False and bad_dates["quality"]["status"] == STATUS_EMPTY

    invalid = run_capability("D-A11", x=x, y=[None] * 20)
    assert invalid["ok"] is False and invalid["quality"]["status"] == STATUS_EMPTY


# ---------------- D-A12 领先滞后相关 ----------------


def test_lead_lag_correlation_returns_full_envelope():
    x, y = _corr_pair(150)
    dates = _dates(150)
    out = run_capability("D-A12", x=x, y=y, max_lag=10, dates=dates)
    assert out["ok"] is True
    assert out["capability"] == "D-A12"
    assert out["intent"] == "correlation_query"
    assert out["quality"]["status"] == STATUS_GOOD
    assert out["quality"]["sample_n"] == 150
    assert out["quality"]["align_method"] == "paired_complete_case"
    assert out["quality"]["span"] == [dates[0], dates[-1]]
    block = out["data"]["capabilities"]["D-A12"]
    assert block["methods"] == ["M11", "M12"]
    assert block["max_lag"] == 10
    assert len(block["corr_by_lag"]) == 21
    assert [row["lag"] for row in block["corr_by_lag"]] == list(range(-10, 11))
    assert block["best_lag"] in range(-10, 11)
    assert block["best_corr"] == 1.0
    assert block["sample_n"] == 150
    assert out["data"]["params"] == {"min_n": 120, "max_lag": 10}
    assert "最优 lag" in out["answer"]


def test_lead_lag_correlation_reuses_m11_m12():
    import l1agg.methods as methods

    x, y = _corr_pair(140)
    out = run_capability("D-A12", x=x, y=y, max_lag=8)
    block = out["data"]["capabilities"]["D-A12"]
    family = methods.run("M11", {"x": x, "y": y}, max_lag=8)["result"]
    optimum = methods.run("M12", {"x": x, "y": y}, max_lag=8)["result"]
    assert block["corr_by_lag"] == [
        {
            "lag": lag,
            "r": family["r"][i],
            "p": family["p"][i],
            "q": family["q"][i],
            "significant": family["significant"][i],
        }
        for i, lag in enumerate(family["lags"])
    ]
    assert block["best_lag"] == optimum["lag"]
    assert block["best_corr"] == optimum["r"]
    assert block["best_p_adj"] == optimum["q"]


def test_lead_lag_correlation_degrades_for_short_sample():
    x, y = _corr_pair(100)
    out = run_capability("D-A12", x=x, y=y, max_lag=10)
    assert out["ok"] is True
    assert out["quality"]["status"] == STATUS_PARTIAL
    assert out["quality"]["degraded_reason"] == "insufficient_history"
    assert "样本不足" in out["answer"]
    assert out["data"]["capabilities"]["D-A12"]["best_lag"] is not None


def test_lead_lag_correlation_invalid_input_fails_open():
    x, y = _corr_pair(150)

    single = run_capability("D-A12", x=[1.0], y=[1.0])
    assert single["ok"] is False and single["quality"]["status"] == STATUS_EMPTY

    bad_lag = run_capability("D-A12", x=x, y=y, max_lag=0)
    assert bad_lag["ok"] is False and bad_lag["quality"]["status"] == STATUS_EMPTY

    too_wide = run_capability("D-A12", x=x, y=y, max_lag=150)
    assert too_wide["ok"] is False and too_wide["quality"]["status"] == STATUS_EMPTY

    bad_dates = run_capability("D-A12", x=x, y=y, max_lag=10, dates=_dates(149))
    assert bad_dates["ok"] is False and bad_dates["quality"]["status"] == STATUS_EMPTY

    invalid = run_capability("D-A12", x=x, y=[None] * 150)
    assert invalid["ok"] is False and invalid["quality"]["status"] == STATUS_EMPTY


# ---------------- D-A13 极端事件频率 ----------------


def _extreme_values(n: int = 100) -> list:
    values = [0.01] * (n - 5)
    values += [0.40, -0.45, 0.50, -0.60, 0.70]
    return values


def test_extreme_frequency_returns_full_envelope():
    import l1agg.methods as methods

    values = _extreme_values(100)
    dates = _dates(100)
    out = run_capability("D-A13", values=values, dates=dates)
    assert out["ok"] is True
    assert out["capability"] == "D-A13"
    assert out["intent"] == "metric_series"
    assert out["quality"]["status"] == STATUS_GOOD
    assert out["quality"]["sample_n"] == 100
    assert out["quality"]["span"] == [dates[0], dates[-1]]
    block = out["data"]["capabilities"]["D-A13"]
    assert block["methods"] == ["S11"]
    assert block["side"] == "above"
    assert block["quantile"] == 0.95
    p95 = methods.run("S11", values)["result"]["p95"]
    assert block["threshold"] == round(p95, 6)
    days = sum(1 for value in values if value >= p95)
    assert block["days"] == days
    assert block["ratio"] == round(days / 100, 6)
    assert block["sample_n"] == 100
    assert out["data"]["params"] == {"min_n": 30, "side": "above"}
    assert "极端事件" in out["answer"]


def test_extreme_frequency_reuses_s25():
    import l1agg.methods as methods

    values = _extreme_values(120)
    out = run_capability("D-A13", values=values, quantile=0.9)
    block = out["data"]["capabilities"]["D-A13"]
    p90 = methods.run("S11", values)["result"]["p90"]
    assert block["threshold"] == round(p90, 6)
    assert block["days"] == sum(1 for value in values if value >= p90)
    assert block["quantile"] == 0.9


def test_extreme_frequency_degrades_for_short_sample_with_threshold():
    values = _extreme_values(20)
    out = run_capability("D-A13", values=values, threshold=0.3)
    assert out["ok"] is True
    assert out["quality"]["status"] == STATUS_PARTIAL
    assert out["quality"]["degraded_reason"] == "insufficient_samples"
    assert "样本不足" in out["answer"]
    block = out["data"]["capabilities"]["D-A13"]
    assert block["methods"] == []
    assert block["threshold"] == 0.3
    assert block["days"] == sum(1 for value in values if value >= 0.3)

    no_threshold = run_capability("D-A13", values=values)
    assert no_threshold["ok"] is False
    assert no_threshold["quality"]["status"] == STATUS_EMPTY


def test_extreme_frequency_invalid_input_fails_open():
    values = _extreme_values(120)

    single = run_capability("D-A13", values=[0.1])
    assert single["ok"] is False and single["quality"]["status"] == STATUS_EMPTY

    bad_side = run_capability("D-A13", values=values, side="between")
    assert bad_side["ok"] is False and bad_side["quality"]["status"] == STATUS_EMPTY

    bad_threshold = run_capability("D-A13", values=values, threshold=float("nan"))
    assert bad_threshold["ok"] is False and bad_threshold["quality"]["status"] == STATUS_EMPTY

    bad_quantile = run_capability("D-A13", values=values, quantile=1.5)
    assert bad_quantile["ok"] is False and bad_quantile["quality"]["status"] == STATUS_EMPTY

    bad_dates = run_capability("D-A13", values=values, dates=_dates(119))
    assert bad_dates["ok"] is False and bad_dates["quality"]["status"] == STATUS_EMPTY

    invalid = run_capability("D-A13", values=values[:-1] + [None])
    assert invalid["ok"] is False and invalid["quality"]["status"] == STATUS_EMPTY


# ---------------- D-B08 趋势斜率 ----------------


def _trend_prices(n: int = 120) -> list:
    return [100.0 * math.exp(0.002 * i) for i in range(n)]


def test_slope_trend_returns_full_envelope():
    prices = _trend_prices(120)
    dates = _dates(120)
    out = run_capability("D-B08", prices=prices, dates=dates)
    assert out["ok"] is True
    assert out["capability"] == "D-B08"
    assert out["intent"] == "technical_indicator"
    assert out["quality"]["status"] == STATUS_GOOD
    assert out["quality"]["sample_n"] == 90
    assert out["quality"]["span"] == [dates[30], dates[-1]]
    block = out["data"]["capabilities"]["D-B08"]
    assert block["methods"] == ["T08", "T09"]
    assert block["window"] == 90
    assert block["slope"] == pytest.approx(0.002, abs=1e-9)
    assert block["r2"] == 1.0
    assert block["hac_corrected"] is False
    assert block["sample_n"] == 90
    assert out["data"]["params"] == {"min_n": 60, "window": 90}
    assert "趋势斜率" in out["answer"]


def test_slope_trend_matches_methods():
    import l1agg.methods as methods

    prices = _trend_prices(150)
    out = run_capability("D-B08", prices=prices, window=60)
    block = out["data"]["capabilities"]["D-B08"]
    sample = prices[-60:]
    t08 = methods.run("T08", sample)["result"]
    t09 = methods.run("T09", sample)["result"]
    assert block["slope"] == t08["slope_per_day"]
    assert block["r2"] == t08["r2"]
    assert block["t"] == t09["t"]
    assert block["p"] == t09["p"]


def test_slope_trend_degrades_for_short_window():
    out = run_capability("D-B08", prices=_trend_prices(45))
    assert out["ok"] is True
    assert out["quality"]["status"] == STATUS_PARTIAL
    assert out["quality"]["degraded_reason"] == "short_window"
    assert "样本不足" in out["answer"]
    block = out["data"]["capabilities"]["D-B08"]
    assert block["sample_n"] == 45
    assert block["slope"] is not None


def test_slope_trend_invalid_input_fails_open():
    prices = _trend_prices(120)

    short = run_capability("D-B08", prices=prices[:20])
    assert short["ok"] is False and short["quality"]["status"] == STATUS_EMPTY

    bad_window = run_capability("D-B08", prices=prices, window=10)
    assert bad_window["ok"] is False and bad_window["quality"]["status"] == STATUS_EMPTY

    bad_type = run_capability("D-B08", prices=prices, window="ninety")
    assert bad_type["ok"] is False and bad_type["quality"]["status"] == STATUS_EMPTY

    bad_dates = run_capability("D-B08", prices=prices, dates=_dates(119))
    assert bad_dates["ok"] is False and bad_dates["quality"]["status"] == STATUS_EMPTY

    invalid = run_capability("D-B08", prices=prices[:-1] + [None])
    assert invalid["ok"] is False and invalid["quality"]["status"] == STATUS_EMPTY


# ---------------- D-B09 距 ATH 回撤 ----------------


def _ath_prices(n: int = 300) -> list:
    return [100.0 + i for i in range(n - 1)] + [150.0]


def test_ath_drawdown_returns_full_envelope():
    prices = _ath_prices(300)
    dates = _dates(300)
    out = run_capability("D-B09", prices=prices, dates=dates)
    assert out["ok"] is True
    assert out["capability"] == "D-B09"
    assert out["intent"] == "technical_indicator"
    assert out["quality"]["status"] == STATUS_GOOD
    assert out["quality"]["sample_n"] == 300
    assert out["quality"]["span"] == [dates[0], dates[-1]]
    block = out["data"]["capabilities"]["D-B09"]
    assert block["methods"] == ["D20", "D21"]
    assert block["ath"] == 398.0
    assert block["ath_ts"] == dates[298]
    assert block["drawdown_from_ath"] == round(1.0 - 150.0 / 398.0, 6)
    assert block["drawdown_from_ath"] == block["current_drawdown"]
    assert "回撤" in out["answer"]


def test_ath_drawdown_matches_methods():
    import l1agg.methods as methods

    prices = _ath_prices(260)
    out = run_capability("D-B09", prices=prices)
    block = out["data"]["capabilities"]["D-B09"]
    d20 = methods.run("D20", prices)["result"]
    d21 = methods.run("D21", prices)["result"]
    assert block["mdd"] == d20["mdd"]
    assert block["duration_days"] == d21["duration_days"]
    assert block["recovery_days"] == d21["recovery_days"]
    assert block["drawdown_from_ath"] == round(1.0 - prices[-1] / max(prices), 6)


def test_ath_drawdown_degrades_for_short_history():
    out = run_capability("D-B09", prices=_ath_prices(30))
    assert out["ok"] is True
    assert out["quality"]["status"] == STATUS_PARTIAL
    assert out["quality"]["degraded_reason"] == "insufficient_samples"
    assert "样本不足" in out["answer"]
    assert out["data"]["capabilities"]["D-B09"]["drawdown_from_ath"] is not None


def test_ath_drawdown_invalid_input_fails_open():
    single = run_capability("D-B09", prices=[100.0])
    assert single["ok"] is False and single["quality"]["status"] == STATUS_EMPTY

    blank = run_capability("D-B09", prices=[])
    assert blank["ok"] is False and blank["quality"]["status"] == STATUS_EMPTY

    all_none = run_capability("D-B09", prices=[None, None])
    assert all_none["ok"] is False and all_none["quality"]["status"] == STATUS_EMPTY

    short_dates = run_capability("D-B09", prices=_ath_prices(30), dates=_dates(10))
    assert short_dates["ok"] is True
    assert short_dates["data"]["capabilities"]["D-B09"]["ath_ts"] is None


# ---------------- D-G08 12-1 动量 ----------------


def _momentum_prices(n: int = 280) -> list:
    return [100.0 + i for i in range(n)]


def test_momentum_12_1_returns_full_envelope():
    prices = _momentum_prices(280)
    dates = _dates(280)
    out = run_capability("D-G08", prices=prices, dates=dates)
    assert out["ok"] is True
    assert out["capability"] == "D-G08"
    assert out["intent"] == "metric_derived"
    assert out["quality"]["status"] == STATUS_GOOD
    assert out["quality"]["sample_n"] == 253
    block = out["data"]["capabilities"]["D-G08"]
    assert block["methods"] == ["F14"]
    assert block["lookback"] == 252
    assert block["skip"] == 21
    assert block["sample_n"] == 253
    assert block["truncated"] is False
    assert block["momentum_12_1"] == round(prices[258] / prices[6] - 1.0, 6)
    assert block["window_start_ts"] == dates[6]
    assert block["window_end_ts"] == dates[258]
    assert "12-1 动量" in out["answer"]


def test_momentum_12_1_matches_methods():
    import l1agg.methods as methods

    prices = _momentum_prices(280)
    out = run_capability("D-G08", prices=prices)
    block = out["data"]["capabilities"]["D-G08"]
    f14 = methods.run("F14", prices[6:259], k=252)["result"]
    assert block["momentum_12_1"] == f14["momentum"]
    assert block["vol"] == f14["vol"]
    assert block["risk_adjusted"] == f14["ratio"]


def test_momentum_12_1_degrades_when_history_is_short():
    out = run_capability("D-G08", prices=_momentum_prices(120))
    assert out["ok"] is True
    assert out["quality"]["status"] == STATUS_PARTIAL
    assert out["quality"]["degraded_reason"] == "short_history"
    block = out["data"]["capabilities"]["D-G08"]
    assert block["truncated"] is True
    assert block["lookback"] == 120 - 21 - 1
    assert block["sample_n"] == 99
    assert "历史数据不足" in out["answer"]
    assert block["momentum_12_1"] is not None


def test_momentum_12_1_invalid_input_fails_open():
    short = run_capability("D-G08", prices=_momentum_prices(59))
    assert short["ok"] is False and short["quality"]["status"] == STATUS_EMPTY

    blank = run_capability("D-G08", prices=[])
    assert blank["ok"] is False and blank["quality"]["status"] == STATUS_EMPTY

    bad_lookback = run_capability("D-G08", prices=_momentum_prices(280), lookback=1)
    assert bad_lookback["ok"] is False

    bad_skip = run_capability("D-G08", prices=_momentum_prices(280), skip=-1)
    assert bad_skip["ok"] is False

    bad_type = run_capability("D-G08", prices=_momentum_prices(280), lookback="twelve")
    assert bad_type["ok"] is False

    bad_dates = run_capability("D-G08", prices=_momentum_prices(280), dates=_dates(10))
    assert bad_dates["ok"] is False

    invalid = run_capability("D-G08", prices=_momentum_prices(279) + [None])
    assert invalid["ok"] is False and invalid["quality"]["status"] == STATUS_EMPTY


# ---------------- D-G09 波动率目标换算 ----------------


def _vol_target_prices(n: int = 120) -> list:
    return [100.0 * math.exp(0.001 * i + 0.02 * math.sin(i / 3.0)) for i in range(n)]


def test_vol_target_scale_returns_full_envelope():
    prices = _vol_target_prices(120)
    dates = _dates(120)
    out = run_capability("D-G09", prices=prices, dates=dates)
    assert out["ok"] is True
    assert out["capability"] == "D-G09"
    assert out["intent"] == "metric_derived"
    assert out["quality"]["status"] == STATUS_GOOD
    assert out["quality"]["sample_n"] == 119
    block = out["data"]["capabilities"]["D-G09"]
    assert block["methods"] == ["P02"]
    assert block["window"] == 20
    assert block["periods"] == 365
    assert block["returns_n"] == 119
    assert block["target_vol"] == 0.1
    assert abs(block["scale"] * block["realized_vol"] - 0.1) < 1e-5
    assert "波动率目标换算" in out["answer"]


def test_vol_target_scale_matches_methods():
    import l1agg.methods as methods

    prices = _vol_target_prices(120)
    out = run_capability("D-G09", prices=prices, symbol="BTC")
    block = out["data"]["capabilities"]["D-G09"]
    rets = [prices[i] / prices[i - 1] - 1.0 for i in range(1, len(prices))]
    p02 = methods.run("P02", {"BTC": rets}, target_vol=0.1, window=20, periods=365)["result"]
    assert block["scale"] == p02["scale"]["BTC"]
    assert block["realized_vol"] == p02["realized"]["BTC"]
    assert block["target_vol"] == p02["target_vol"]
    assert block["returns_n"] == p02["n"]


def test_vol_target_scale_degrades_on_zero_vol_and_truncated_window():
    flat = run_capability("D-G09", prices=[100.0] * 120)
    assert flat["ok"] is True
    assert flat["quality"]["status"] == STATUS_PARTIAL
    assert flat["quality"]["degraded_reason"] == "zero_volatility"
    assert flat["data"]["capabilities"]["D-G09"]["scale"] == 0.0
    assert "样本不足" in flat["answer"]

    short = run_capability("D-G09", prices=_vol_target_prices(70), window=200)
    assert short["ok"] is True
    assert short["quality"]["status"] == STATUS_PARTIAL
    assert short["quality"]["degraded_reason"] == "window_truncated"
    assert short["data"]["capabilities"]["D-G09"]["window"] == 69
    assert "截断" in short["answer"]


def test_vol_target_scale_invalid_input_fails_open():
    assert (
        run_capability("D-G09", prices=_vol_target_prices(60))["quality"]["status"] == STATUS_EMPTY
    )
    assert run_capability("D-G09", prices=[])["quality"]["status"] == STATUS_EMPTY
    assert run_capability("D-G09", prices=_vol_target_prices(120), target_vol=0)["ok"] is False
    assert run_capability("D-G09", prices=_vol_target_prices(120), target_vol="x")["ok"] is False
    assert run_capability("D-G09", prices=_vol_target_prices(120), window=1)["ok"] is False
    assert run_capability("D-G09", prices=_vol_target_prices(120), periods=0)["ok"] is False
    assert run_capability("D-G09", prices=_vol_target_prices(120), dates=_dates(10))["ok"] is False
    invalid = run_capability("D-G09", prices=_vol_target_prices(119) + [None])
    assert invalid["ok"] is False and invalid["quality"]["status"] == STATUS_EMPTY


# ---------------- D-A15 净流入滚动和 ----------------


def _flow_values(n: int = 40) -> list:
    return [float((i % 9) - 4) * 10 for i in range(n)]


def test_etf_flow_rolling_returns_full_envelope():
    values = _flow_values(40)
    dates = _dates(40)
    out = run_capability("D-A15", values=values, dates=dates)
    assert out["ok"] is True
    assert out["capability"] == "D-A15"
    assert out["intent"] == "metric_series"
    assert out["quality"]["status"] == STATUS_GOOD
    assert out["quality"]["sample_n"] == 40
    assert out["quality"]["span"] == [dates[0], dates[-1]]
    block = out["data"]["capabilities"]["D-A15"]
    assert block["methods"] == ["S20"]
    assert block["windows"] == [7, 30]
    assert block["sum_7d"] == pytest.approx(sum(values[-7:]), abs=1e-4)
    assert block["sum_30d"] == pytest.approx(sum(values[-30:]), abs=1e-4)
    assert block["sample_n"] == 40
    assert out["data"]["params"] == {"min_n": 30, "windows": [7, 30]}
    assert "滚动和" in out["answer"]


def test_etf_flow_rolling_matches_s20_series():
    import l1agg.methods as methods

    values = _flow_values(50)
    out = run_capability("D-A15", values=values, windows=(5, 10))
    block = out["data"]["capabilities"]["D-A15"]
    for k in (5, 10):
        series = methods.run("S20", values, k=k)["result"]["series"]
        last = [value for value in series if value is not None][-1]
        assert block[f"sum_{k}d"] == round(last * k, 6)
    assert block["windows"] == [5, 10]


def test_etf_flow_rolling_degrades_for_short_sample_and_window():
    short = run_capability("D-A15", values=_flow_values(20), windows=(7,))
    assert short["ok"] is True
    assert short["quality"]["status"] == STATUS_PARTIAL
    assert short["quality"]["degraded_reason"] == "insufficient_samples"
    assert "样本不足" in short["answer"]
    assert short["data"]["capabilities"]["D-A15"]["sum_7d"] is not None

    narrow = run_capability("D-A15", values=_flow_values(10), windows=(7, 30))
    assert narrow["ok"] is True
    assert narrow["quality"]["status"] == STATUS_PARTIAL
    assert "short_history" in narrow["quality"]["degraded_reason"]
    block = narrow["data"]["capabilities"]["D-A15"]
    assert block["sum_7d"] is not None
    assert block["sum_30d"] is None


def test_etf_flow_rolling_invalid_input_fails_open():
    values = _flow_values(40)

    no_window = run_capability("D-A15", values=values[:5])
    assert no_window["ok"] is False and no_window["quality"]["status"] == STATUS_EMPTY

    bad_window = run_capability("D-A15", values=values, windows=(0,))
    assert bad_window["ok"] is False and bad_window["quality"]["status"] == STATUS_EMPTY

    bad_type = run_capability("D-A15", values=values, windows=("seven",))
    assert bad_type["ok"] is False and bad_type["quality"]["status"] == STATUS_EMPTY

    empty_windows = run_capability("D-A15", values=values, windows=())
    assert empty_windows["ok"] is False and empty_windows["quality"]["status"] == STATUS_EMPTY

    bad_dates = run_capability("D-A15", values=values, dates=_dates(39))
    assert bad_dates["ok"] is False and bad_dates["quality"]["status"] == STATUS_EMPTY

    invalid = run_capability("D-A15", values=values[:-1] + [None])
    assert invalid["ok"] is False and invalid["quality"]["status"] == STATUS_EMPTY


# ---------------- D-A16 稳定币规模增速 ----------------


def _supply_values(n: int = 40) -> list:
    return [1000.0 + 5.0 * i for i in range(n)]


def test_stablecoin_growth_returns_full_envelope():
    import l1agg.methods as methods

    values = _supply_values(40)
    dates = _dates(40)
    out = run_capability("D-A16", values=values, dates=dates)
    assert out["ok"] is True
    assert out["capability"] == "D-A16"
    assert out["intent"] == "metric_series"
    assert out["quality"]["status"] == STATUS_GOOD
    assert out["quality"]["sample_n"] == 40
    assert out["quality"]["span"] == [dates[0], dates[-1]]
    block = out["data"]["capabilities"]["D-A16"]
    assert block["methods"] == ["S16"]
    assert block["windows"] == [7, 30]
    for k in (7, 30):
        pct = methods.run("S16", values, k=k)["result"]["pct"]
        assert block[f"growth_{k}d"] == round(pct * 100, 6)
    assert block["sample_n"] == 40
    assert out["data"]["params"] == {"min_n": 30, "windows": [7, 30]}
    assert "增速" in out["answer"]


def test_stablecoin_growth_matches_s16_pct():
    import l1agg.methods as methods

    values = _supply_values(50)
    out = run_capability("D-A16", values=values, windows=(7, 14))
    block = out["data"]["capabilities"]["D-A16"]
    for k in (7, 14):
        pct = methods.run("S16", values, k=k)["result"]["pct"]
        assert block[f"growth_{k}d"] == round(pct * 100, 6)
    assert block["windows"] == [7, 14]


def test_stablecoin_growth_degrades_for_short_sample_and_zero_base():
    short = run_capability("D-A16", values=_supply_values(20), windows=(7,))
    assert short["ok"] is True
    assert short["quality"]["status"] == STATUS_PARTIAL
    assert short["quality"]["degraded_reason"] == "insufficient_samples"
    assert "样本不足" in short["answer"]

    narrow = run_capability("D-A16", values=_supply_values(10), windows=(7, 30))
    assert narrow["ok"] is True
    assert "short_history" in narrow["quality"]["degraded_reason"]
    block = narrow["data"]["capabilities"]["D-A16"]
    assert block["growth_7d"] is not None
    assert block["growth_30d"] is None

    zero = _supply_values(40)
    zero[-8] = 0.0
    out = run_capability("D-A16", values=zero)
    assert out["ok"] is True
    assert "base_zero" in out["quality"]["degraded_reason"]
    assert out["data"]["capabilities"]["D-A16"]["growth_7d"] is None
    assert out["data"]["capabilities"]["D-A16"]["growth_30d"] is not None


def test_stablecoin_growth_invalid_input_fails_open():
    values = _supply_values(40)

    no_window = run_capability("D-A16", values=values[:5])
    assert no_window["ok"] is False and no_window["quality"]["status"] == STATUS_EMPTY

    bad_window = run_capability("D-A16", values=values, windows=(0,))
    assert bad_window["ok"] is False and bad_window["quality"]["status"] == STATUS_EMPTY

    bad_type = run_capability("D-A16", values=values, windows=("seven",))
    assert bad_type["ok"] is False and bad_type["quality"]["status"] == STATUS_EMPTY

    empty_windows = run_capability("D-A16", values=values, windows=())
    assert empty_windows["ok"] is False and empty_windows["quality"]["status"] == STATUS_EMPTY

    bad_dates = run_capability("D-A16", values=values, dates=_dates(39))
    assert bad_dates["ok"] is False and bad_dates["quality"]["status"] == STATUS_EMPTY

    invalid = run_capability("D-A16", values=values[:-1] + [None])
    assert invalid["ok"] is False and invalid["quality"]["status"] == STATUS_EMPTY


# ---------------- D-J30 PIT / release_ts 全局校验 ----------------


def test_pit_alignment_validates_release_ts_and_returns_pit_distribution():
    indicator, prices = _pit_inputs()
    dates = _dates(len(indicator))
    out = run_capability("D-J30", indicator=indicator, prices=prices, dates=dates, name="资金费率")
    assert out["ok"] is True
    assert out["capability"] == "D-J30"
    assert out["intent"] == "metric_percentile"
    assert out["quality"]["status"] == STATUS_GOOD
    assert out["quality"]["sample_n"] == 320
    assert out["quality"]["align_method"] == "release_ts_pit"
    assert out["quality"]["span"] == [dates[0], dates[-1]]
    block = out["data"]["capabilities"]["D-J30"]
    assert block["methods"] == ["SC90", "R02"]
    assert block["pit_check"]["pass"] is True
    assert block["pit_check"]["n"] == 320
    assert block["pit_check"]["n_violations"] == 0
    assert block["r02"]["pit"] is True
    assert 0.0 <= block["r02"]["current_percentile"] <= 100.0
    assert block["r02"]["by_horizon"][0]["h"] == 1
    assert block["release_ts_applied"] is False
    assert out["data"]["params"]["min_n"] == 250
    assert out["data"]["params"]["buckets"] == 4
    assert "PIT 校验通过" in out["answer"]
    assert "历史统计" in out["answer"]


def test_pit_alignment_reuses_sc90_and_r02_without_recomputing():
    import l1agg.methods as methods

    indicator, prices = _pit_inputs(n=300, seed=43)
    dates = _dates(300)
    out = run_capability("D-J30", indicator=indicator, prices=prices, dates=dates)
    block = out["data"]["capabilities"]["D-J30"]
    assert block["pit_check"] == methods.run("SC90", {"available": dates, "used": dates})["result"]
    expected = methods.run(
        "R02",
        {
            "indicator": indicator,
            "price": prices,
            "timestamps": dates,
            "align_method": "release_ts_pit",
        },
        buckets=4,
        horizons=(1,),
        label="指标",
        pit=True,
        window=250,
    )["result"]
    assert block["r02"] == expected


def test_pit_alignment_flags_release_after_use_and_degrades():
    indicator, prices = _pit_inputs(n=300)
    dates = _dates(300)
    lagged = [
        (datetime.date.fromisoformat(day) + datetime.timedelta(days=5)).isoformat() for day in dates
    ]
    out = run_capability(
        "D-J30",
        indicator=indicator,
        prices=prices,
        dates=dates,
        release_ts=lagged,
        used_ts=dates,
    )
    assert out["ok"] is True
    assert out["quality"]["status"] == STATUS_PARTIAL
    assert out["quality"]["degraded_reason"] == "pit_violations"
    block = out["data"]["capabilities"]["D-J30"]
    assert block["pit_check"]["pass"] is False
    assert block["pit_check"]["n_violations"] == 300
    assert block["pit_check"]["max_lag"] > 0
    assert block["release_ts_applied"] is True
    assert block["r02"]["pit"] is True
    assert "前视风险" in out["answer"]

    stale = [
        (datetime.date.fromisoformat(day) + datetime.timedelta(days=60)).isoformat()
        for day in dates
    ]
    stale_out = run_capability(
        "D-J30",
        indicator=indicator,
        prices=prices,
        dates=dates,
        release_ts=stale,
        used_ts=dates,
    )
    assert stale_out["ok"] is True
    assert stale_out["quality"]["status"] == STATUS_PARTIAL
    stale_block = stale_out["data"]["capabilities"]["D-J30"]
    assert stale_block["r02"] is None
    assert "未输出前瞻分布" in stale_out["answer"]


def test_pit_alignment_short_or_invalid_input_fails_open():
    indicator, prices = _pit_inputs()
    short = run_capability("D-J30", indicator=indicator[:249], prices=prices[:249])
    assert short["ok"] is False
    assert short["quality"]["status"] == STATUS_EMPTY
    assert "250" in short["answer"]

    mismatch = run_capability("D-J30", indicator=indicator, prices=prices[:-1])
    assert mismatch["ok"] is False and mismatch["quality"]["status"] == STATUS_EMPTY

    invalid = run_capability("D-J30", indicator=indicator, prices=prices, buckets=1)
    assert invalid["ok"] is False and invalid["quality"]["status"] == STATUS_EMPTY

    bad_window = run_capability("D-J30", indicator=indicator, prices=prices, window=1)
    assert bad_window["ok"] is False and bad_window["quality"]["status"] == STATUS_EMPTY


# ---------------- D-A14 拥挤度（F26 + A 分位法 level） ----------------


def test_crowding_returns_level_with_quantile_disclosure():
    dates = _dates(300)
    out = run_capability("D-A14", series=_crowding(), dates=dates, symbol="BTC")
    assert out["ok"] is True
    assert out["capability"] == "D-A14"
    assert out["intent"] == "metric_percentile"
    assert out["quality"]["status"] == STATUS_GOOD
    assert out["quality"]["sample_n"] == 300
    block = out["data"]["capabilities"]["D-A14"]
    assert block["methods"] == ["F26"]
    assert block["level"] in {"极低", "低", "偏高", "高"}
    assert set(block["thresholds"]) == {"p20", "p60", "p80"}
    assert block["thresholds"]["p20"] <= block["thresholds"]["p60"] <= block["thresholds"]["p80"]
    assert block["level_status"] == "ok"
    params = out["data"]["params"]
    assert params["level_method"] == "A_quantile"
    assert params["level_quantiles"] == [0.2, 0.6, 0.8]
    assert params["window"] == 300
    assert params["as_of"] == dates[-1]
    assert "历史统计" in out["answer"]


def test_crowding_reuses_method_layer_without_recomputing():
    import l1agg.methods as methods

    series = _crowding(n=260, seed=3)
    out = run_capability("D-A14", series=series)
    block = out["data"]["capabilities"]["D-A14"]
    assert block["score"] == methods.run("F26", {"series": series})["result"]["score"]
    assert block["components"] == methods.run("F26", {"series": series})["result"]["components"]


def test_crowding_insufficient_history_fails_open():
    out = run_capability("D-A14", series={"a": [float(i) for i in range(40)]})
    assert out["ok"] is False
    assert out["quality"]["status"] == STATUS_EMPTY
    assert "样本" in out["answer"]


def test_crowding_degenerate_panel_degrades_without_fabricating_thresholds():
    out = run_capability("D-A14", series={"a": [5.0] * 80, "b": [7.0] * 80})
    assert out["ok"] is True
    assert out["quality"]["status"] == STATUS_PARTIAL
    assert out["quality"]["degraded_reason"] == "degenerate_distribution"
    assert "降级" in out["answer"]
    block = out["data"]["capabilities"]["D-A14"]
    assert block["level"] is None
    assert block["thresholds"] is None


# ---------------- D-E04 事件研究窗 ----------------


def _event_prices(n=300, step=0.001):
    return [100.0 * (1.0 + step) ** i for i in range(n)]


def test_event_study_returns_car_and_post_event_distribution():
    prices = _event_prices()
    dates = _dates(len(prices))
    events = [dates[i] for i in range(20, 280, 6)]
    out = run_capability("D-E04", prices=prices, events=events, dates=dates, k=5, symbol="BTC")
    assert out["ok"] is True
    assert out["capability"] == "D-E04"
    assert out["intent"] == "event_study"
    assert out["quality"]["status"] == STATUS_GOOD
    block = out["data"]["capabilities"]["D-E04"]
    assert block["methods"] == ["F19", "F21", "F23"]
    assert block["n_events"] >= 30
    assert block["car"] is not None and block["car"] > 0
    assert 0.0 <= block["win_rate"] <= 1.0
    assert block["window"] == 5
    assert out["data"]["params"]["event_gate"] == 30
    assert "历史统计" in out["answer"]


def test_event_study_degrades_when_events_below_gate():
    prices = _event_prices()
    dates = _dates(len(prices))
    events = [dates[i] for i in range(20, 50, 3)]
    out = run_capability("D-E04", prices=prices, events=events, dates=dates)
    assert out["ok"] is True
    assert out["quality"]["status"] == STATUS_PARTIAL
    assert out["quality"]["degraded_reason"] == "events_lt_30"
    assert out["data"]["capabilities"]["D-E04"]["n_events"] < 30


def test_event_study_empty_without_events_or_history():
    dates = _dates(300)
    out = run_capability("D-E04", prices=_event_prices(), dates=dates, events=[])
    assert out["ok"] is False
    assert out["quality"]["status"] == STATUS_EMPTY
    short = run_capability("D-E04", prices=_event_prices(10), events=[dates[i] for i in range(3)])
    assert short["ok"] is False
    assert short["quality"]["status"] == STATUS_EMPTY


def _holiday_case(holiday_idx=(30, 70, 110, 150, 190, 230), n_business=300):
    """仅工作日交易的序列：指定工作日为节假日，节前收益 1%，其余 0。"""
    days, cursor = [], datetime.date(2024, 1, 1)
    while len(days) < n_business:
        if cursor.weekday() < 5:
            days.append(cursor)
        cursor += datetime.timedelta(days=1)
    holidays = set(holiday_idx)
    dates, prices, px = [], [], 100.0
    for i, day in enumerate(days):
        if i in holidays:
            continue
        px *= 1.01 if (i + 1) in holidays else 1.0
        dates.append(day.isoformat())
        prices.append(px)
    return prices, dates


def test_event_study_pre_holiday_derives_calendar_from_date_axis():
    prices, dates = _holiday_case()
    out = run_capability("D-E04", prices=prices, dates=dates, pre_holiday=True, symbol="SPX")
    assert out["ok"] is True
    block = out["data"]["capabilities"]["D-E04"]
    assert block["methods"] == ["C11"]
    pre = block["pre_holiday"]
    assert pre["calendar"] == "derived"
    assert pre["n_holidays"] == 6
    assert pre["pre_mean"] == pytest.approx(0.01, abs=1e-4)
    assert pre["base_mean"] == pytest.approx(0.0, abs=1e-6)
    assert out["data"]["params"]["calendar_source"] == "derived"
    # 6 个节假日 <30 → 短样本降级，但仍给出描述
    assert out["quality"]["status"] == STATUS_PARTIAL
    assert out["quality"]["degraded_reason"] == "holiday_events_lt_30"
    assert "样本" in out["answer"] and "历史统计" in out["answer"]


def test_event_study_pre_holiday_empty_without_weekday_gap():
    prices = _event_prices(300)
    out = run_capability("D-E04", prices=prices, dates=_dates(300), pre_holiday=True)
    assert out["ok"] is False
    assert out["quality"]["status"] == STATUS_EMPTY
    assert "工作日缺口" in out["answer"]


# ---------------- D-G25 尾部相关 ----------------


def _tail_panel(n=400, seed=11):
    rng = random.Random(seed)
    btc, eth = [], []
    for _ in range(n):
        shock = rng.gauss(0.0, 0.01)
        btc.append(shock + rng.gauss(0.0, 0.004))
        eth.append(shock + rng.gauss(0.0, 0.02))
    return {"BTC": btc, "ETH": eth}


def test_tail_dependence_reports_down_and_up_tail():
    out = run_capability("D-G25", series=_tail_panel(), q=0.2)
    assert out["ok"] is True
    assert out["intent"] == "correlation_query"
    block = out["data"]["capabilities"]["D-G25"]
    assert block["methods"] == ["P13"]
    pair = block["pairs"]["BTC|ETH"]
    assert pair["rho_down"] is not None
    assert pair["rho_up"] is not None
    # 全样本正相关（共同冲击），尾部切尾后由 P13 原样给出，不在能力层修正
    assert pair["rho_full"] > 0.3
    assert block["n_tail"] >= 30
    assert block["amplification"]["BTC|ETH"] is not None
    assert out["data"]["params"]["upper_tail_by_sign_flip"] is True
    assert "共跌" in out["answer"] or "尾部" in out["answer"]


def test_tail_dependence_empty_with_single_asset():
    out = run_capability("D-G25", series={"BTC": _ar1(200)})
    assert out["ok"] is False
    assert out["quality"]["status"] == STATUS_EMPTY
    assert "≥2" in out["answer"]


# ---------------- D-J05 周期/频谱 ----------------


def _cycle_prices(n=3200, period=1000):
    return [
        100.0 * (1.0 + 0.0002 * i + 0.10 * math.sin(2 * math.pi * i / period)) for i in range(n)
    ]


def test_cycle_spectrum_reports_period_and_coverage():
    prices = _cycle_prices()
    out = run_capability("D-J05", series=prices, dates=_dates(len(prices)), symbol="BTC")
    assert out["ok"] is True
    assert out["intent"] == "cycle_query"
    block = out["data"]["capabilities"]["D-J05"]
    assert 800 <= block["period"] <= 1200
    assert block["cycles"] >= 2
    assert block["reference_days"] == 1460
    assert block["period_to_reference"] is not None
    assert out["quality"]["status"] == STATUS_GOOD
    assert "历史统计" in out["answer"]


def test_cycle_spectrum_degrades_when_history_below_two_cycles():
    prices = _cycle_prices(n=1600, period=400)
    out = run_capability("D-J05", series=prices, dates=_dates(len(prices)))
    assert out["ok"] is True
    assert out["quality"]["status"] == STATUS_PARTIAL
    assert out["quality"]["degraded_reason"] == "cycles_lt_2"
    assert out["data"]["capabilities"]["D-J05"]["span_days"] < 2920


def test_cycle_spectrum_degrades_without_dates():
    prices = _cycle_prices(n=1600, period=400)
    out = run_capability("D-J05", series=prices)
    assert out["ok"] is True
    assert out["quality"]["degraded_reason"] == "dates_missing"


# ---------------- D-G23 事件窗 CAR + Patell/BMP ----------------


def _event_car_prices(n=700, seed=11, lift=0.02):
    rng = random.Random(seed)
    indices = list(range(130, 660, 18))
    returns = [rng.gauss(0.0, 0.01) for _ in range(n)]
    for index in indices:
        for i in range(index - 5, index + 11):
            returns[i] += lift
    prices = [100.0]
    for value in returns:
        prices.append(prices[-1] * (1.0 + value))
    dates = _dates(len(prices))
    return prices, [dates[i] for i in indices], dates, indices


def test_event_car_significance_returns_q10_car_and_q11_tests():
    prices, events, dates, indices = _event_car_prices()
    out = run_capability("D-G23", prices=prices, events=events, dates=dates, symbol="BTC")
    assert out["ok"] is True
    assert out["capability"] == "D-G23"
    assert out["intent"] == "event_study"
    assert out["quality"]["status"] == STATUS_GOOD
    block = out["data"]["capabilities"]["D-G23"]
    assert block["methods"] == ["Q10", "Q11"]
    assert block["n_events"] == len(indices) == 30
    assert block["car"]["est_window"] == [-120, -20]
    assert block["car"]["event_window"] == [-5, 10]
    assert block["car"]["car"] > 0
    assert block["patell_bmp"]["n"] == len(indices)
    assert 0.0 <= block["patell_bmp"]["p"] <= 1.0
    assert out["data"]["params"]["est_window"] == [-120, -20]
    assert out["data"]["params"]["event_window"] == [-5, 10]
    assert "历史统计" in out["answer"]


def test_event_car_significance_reuses_methods_and_degrades_below_30_events():
    import l1agg.methods as methods

    prices, _events, dates, indices = _event_car_prices()
    events = [dates[i] for i in indices[:2]]
    out = run_capability("D-G23", prices=prices, events=events, dates=dates)
    assert out["ok"] is True
    assert out["quality"]["status"] == STATUS_PARTIAL
    assert out["quality"]["degraded_reason"] == "events_lt_30"
    block = out["data"]["capabilities"]["D-G23"]
    returns = [prices[i] / prices[i - 1] - 1.0 for i in range(1, len(prices))]
    return_indices = [i - 1 for i in indices[:2]]
    assert block["car"] == methods.run("Q10", {"series": returns}, events=return_indices)["result"]
    assert (
        block["patell_bmp"]
        == methods.run("Q11", {"series": returns}, events=return_indices)["result"]
    )


def test_event_car_significance_preserves_car_when_patell_bmp_is_unavailable():
    dates = _dates(400)
    events = [dates[i] for i in (150, 200, 250)]
    out = run_capability("D-G23", prices=[100.0] * 400, events=events, dates=dates)
    assert out["ok"] is True
    assert out["quality"]["status"] == STATUS_PARTIAL
    assert out["quality"]["degraded_reason"] == "patell_bmp_unavailable"
    block = out["data"]["capabilities"]["D-G23"]
    assert block["car"]["n"] == 3
    assert block["patell_bmp"] is None
    assert block["gate"] == "insufficient_samples"
    assert "降级" in out["answer"]


# ---------------- D-E09 计数与共现 ----------------


def test_count_series_reports_up_down_counts():
    values = [0.01, -0.02, 0.03, -0.01, 0.0, 0.02, -0.03] * 5
    out = run_capability("D-E09", values=values, label="CPI 后")
    assert out["ok"] is True
    assert out["capability"] == "D-E09"
    assert out["intent"] == "metric_series"
    block = out["data"]["capabilities"]["D-E09"]
    assert block["up_n"] + block["down_n"] <= block["total"]
    assert block["total"] == len(values)
    assert "上涨" in out["answer"]


def test_count_series_cooccurrence_pairs():
    pairs = {
        "a": [1, 1, 0, 0, 1, 1, 0, 1],
        "b": [1, 0, 0, 1, 1, 0, 0, 1],
    }
    out = run_capability("D-E09", pairs=pairs, label="放量且上涨")
    assert out["ok"] is True
    block = out["data"]["capabilities"]["D-E09"]
    assert block["count"] == 3
    assert block["total"] == 8
    assert block["ratio"] == pytest.approx(0.375)
    assert "同时出现" in out["answer"]


def test_count_series_insufficient_fails_open():
    out = run_capability("D-E09", values=[0.01, -0.01])
    assert out["ok"] is False
    assert out["quality"]["status"] == STATUS_EMPTY


def test_manifest_rejects_unimplemented_method():
    bad = Manifest(
        version=1,
        updated="",
        capabilities=(
            Capability(
                id="D-E99",
                intent="x",
                mode="deterministic",
                data_scope=("market.candles",),
                executor="capabilities.stats.drawdown",
                methods=("T23",),
                min_n=10,
            ),
        ),
    )
    with pytest.raises(ManifestError):
        validate(bad)


def test_manifest_rejects_min_n_below_method_gate():
    bad = Manifest(
        version=1,
        updated="",
        capabilities=(
            Capability(
                id="D-E98",
                intent="x",
                mode="deterministic",
                data_scope=("market.candles",),
                executor="capabilities.stats.conditional_ic",
                methods=("B13",),
                min_n=10,
            ),
        ),
    )
    with pytest.raises(ManifestError):
        validate(bad)


def test_manifest_rejects_mode_mix_within_intent():
    caps = (
        Capability(
            id="D-E90",
            intent="correlation_query",
            mode="deterministic",
            data_scope=("market.candles",),
            executor="capabilities.stats.correlation",
            methods=("M01",),
            min_n=60,
        ),
        Capability(
            id="D-E91",
            intent="correlation_query",
            mode="gated",
            data_scope=("market.candles",),
            executor="capabilities.stats.correlation",
            methods=("M01",),
            min_n=60,
        ),
    )
    with pytest.raises(ManifestError):
        validate(Manifest(version=1, updated="", capabilities=caps))


def test_manifest_execution_coverage_aggregates_conditional_branches():
    capability = manifest().get("D-E05")
    pair_only = Manifest(version=1, updated="", capabilities=(capability,))
    pair_calls = {"M01", "M02", "M03", "M04", "M23"}
    matrix_calls = {"M05", "M06", "M07"}

    report = validate_execution(
        pair_only, {"D-E05": pair_calls | matrix_calls}, require_complete=True
    )

    assert report["summary"]["coverage"] == 1.0
    assert report["capabilities"]["D-E05"]["missing"] == []


def test_manifest_execution_coverage_rejects_unexecuted_binding():
    capability = manifest().get("D-E05")
    pair_only = Manifest(version=1, updated="", capabilities=(capability,))
    with pytest.raises(ManifestError, match="M05"):
        validate_execution(
            pair_only,
            {"D-E05": {"M01", "M02", "M03", "M04", "M23"}},
            require_complete=True,
        )


def test_manifest_execution_coverage_rejects_unbound_runtime_call():
    capability = manifest().get("D-E05")
    pair_only = Manifest(version=1, updated="", capabilities=(capability,))
    with pytest.raises(ManifestError, match="M24"):
        validate_execution(pair_only, {"D-E05": {"M24"}}, require_complete=False)


# ---------------- 信封 ----------------


def test_envelope_rejects_empty_answer():
    with pytest.raises(ValueError):
        build(
            capability="D-E10",
            intent="drawdown_query",
            answer="  ",
            data={},
            quality_block=quality_for(10, min_n=1),
        )


def test_envelope_rejects_nested_quality():
    with pytest.raises(ValueError):
        build(
            capability="D-E10",
            intent="drawdown_query",
            answer="ok",
            data={"quality": {"status": "good"}},
            quality_block=quality_for(10, min_n=1),
        )


def test_envelope_partial_requires_reason_and_answer_disclosure():
    q = quality_for(10, min_n=100)
    assert q["status"] == STATUS_PARTIAL and q["degraded_reason"] == "insufficient_samples"
    with pytest.raises(ValueError):
        build(
            capability="D-E10", intent="drawdown_query", answer="回撤 10%", data={}, quality_block=q
        )
    out = build(
        capability="D-E10",
        intent="drawdown_query",
        answer="样本不足 100 点，回撤仅作描述",
        data={},
        quality_block=q,
    )
    assert out["ok"] is True


def test_unavailable_is_empty_and_readable():
    out = unavailable(capability="D-E10", intent="drawdown_query", reason="价格样本不足")
    assert out["ok"] is False
    assert out["quality"]["status"] == STATUS_EMPTY
    assert "不足" in out["answer"]


# ---------------- D-E10 回撤 ----------------


def test_drawdown_matches_manual_profile():
    px = _prices()
    out = run_capability("D-E10", prices=px, symbol="BTC", dates=_dates())
    assert out["ok"] is True and out["quality"]["status"] == STATUS_GOOD
    block = out["data"]["capabilities"]["D-E10"]
    peak = max(px)
    manual_mdd = max(1.0 - v / max(px[: i + 1]) for i, v in enumerate(px))
    assert block["mdd"] == pytest.approx(manual_mdd, abs=1e-6)
    assert block["current_drawdown"] == pytest.approx(1 - px[-1] / peak, abs=1e-6)
    assert block["methods"] == ["D20", "D21"]
    assert out["quality"]["sample_n"] == len(px)
    assert "历史统计" in out["answer"]


def test_drawdown_insufficient_is_partial_not_fabricated():
    out = run_capability("D-E10", prices=_prices(60))
    assert out["ok"] is True
    assert out["quality"]["status"] == STATUS_PARTIAL
    assert out["quality"]["degraded_reason"] == "insufficient_samples"


def test_drawdown_empty_on_no_price():
    out = run_capability("D-E10", prices=[100.0])
    assert out["ok"] is False and out["quality"]["status"] == STATUS_EMPTY


def test_drawdown_exposes_path_and_peak_trough_fields():
    px = _prices(800)
    out = run_capability("D-E10", prices=px, symbol="BTC", dates=_dates(800))
    block = out["data"]["capabilities"]["D-E10"]
    path = block["drawdown_path"]

    assert len(path) <= 500
    assert path[0]["drawdown"] == 0.0
    assert min(p["drawdown"] for p in path) == 0.0
    assert max(p["drawdown"] for p in path) == pytest.approx(block["mdd"], abs=1e-6)
    assert path[-1]["drawdown"] == pytest.approx(block["current_drawdown"], abs=1e-6)
    assert block["peak_price"] == max(px)
    assert block["trough_price"] == px[block["trough_index"]]
    assert block["peak_to_trough_days"] == block["trough_index"] - block["peak_index"]


# ---------------- D-E03 季节性 ----------------


def test_seasonality_detects_weekend_effect():
    dates, px = [], []
    price = 100.0
    for i in range(400):
        d = datetime.date(2024, 1, 1) + datetime.timedelta(days=i)
        price *= 1.0 + (0.01 if d.weekday() >= 5 else -0.002)
        dates.append(d.isoformat())
        px.append(price)
    out = run_capability("D-E03", prices=px, dates=dates, symbol="BTC")
    table = {
        row["weekday"]: row["mean"] for row in out["data"]["capabilities"]["D-E03"]["weekday_table"]
    }
    assert table[5] > table[0]
    assert out["quality"]["status"] == STATUS_PARTIAL
    assert out["quality"]["degraded_reason"] == "seasonality_depth_lt_5y"
    assert "样本" in out["answer"]


def test_seasonality_without_dates_is_clean_handoff():
    out = run_capability("D-E03", prices=_prices())
    assert out["ok"] is False
    assert "日期" in out["answer"]


# ---------------- D-E07 状态转移 ----------------


def test_state_transition_matrix_is_stochastic():
    out = run_capability("D-E07", prices=_prices(300), symbol="BTC")
    block = out["data"]["capabilities"]["D-E07"]
    assert block["states"] == ["q0", "q1", "q2", "q3"]
    for row in block["transition_matrix"]:
        assert sum(row) == pytest.approx(1.0, abs=1e-4)
    assert sum(block["stationary"]) == pytest.approx(1.0, abs=1e-6)
    assert all(d is not None and d >= 1.0 for d in block["dwell"])


def test_state_transition_includes_b06_joint_counts():
    out = run_capability("D-E07", prices=_prices(300), symbol="BTC")
    assert out["ok"] is True
    block = out["data"]["capabilities"]["D-E07"]
    assert block["methods"] == ["B02", "B06", "B07", "B08", "B09"]
    cross = block["crosstab"]
    assert cross["rows"] == cross["cols"] == ["q0", "q1", "q2", "q3"]
    assert cross["n"] == out["quality"]["sample_n"] - 1 == 298
    assert sum(sum(row.values()) for row in cross["table"].values()) == cross["n"]
    for state, probabilities in zip(block["states"], block["transition_matrix"], strict=True):
        counts = cross["table"][state]
        total = sum(counts.values())
        if total:
            assert [round(counts[s] / total, 6) for s in cross["cols"]] == probabilities


def test_state_transition_short_series_is_empty():
    out = run_capability("D-E07", prices=_prices(50))
    assert out["ok"] is False


# ---------------- D-J02 季节强度与调整 ----------------


def _seasonal_adjustment_series(n=120):
    return [10.0 + 0.02 * i + 2.0 * math.sin(2.0 * math.pi * i / 12.0) for i in range(n)]


def test_seasonal_adjustment_executes_methods_and_discloses_shallow_history():
    from l1agg import methods

    series = _seasonal_adjustment_series()
    dates = _dates(len(series))
    out = run_capability("D-J02", series=series, dates=dates, symbol="BTC")
    assert out["ok"] is True
    assert out["capability"] == "D-J02"
    assert out["intent"] == "seasonality_query"
    assert out["quality"]["status"] == STATUS_PARTIAL
    assert out["quality"]["degraded_reason"] == "seasonality_depth_lt_3y"
    assert out["quality"]["sample_n"] == len(series)
    block = out["data"]["capabilities"]["D-J02"]
    assert block["methods"] == ["C13", "T10", "SC91"]
    assert (
        block["results"]["C13"] == methods.run("C13", {"series": series, "dates": dates})["result"]
    )
    assert block["results"]["T10"] == methods.run("T10", series)["result"]
    assert block["results"]["SC91"] == methods.run("SC91", series)["result"]
    assert block["seasonal_strength"] == {
        "C13": block["results"]["C13"]["strength"],
        "T10": block["results"]["T10"]["seasonal_strength"],
        "SC91": block["results"]["SC91"]["seasonal_strength"],
    }
    assert out["data"]["params"]["min_span_days"] == 1095
    assert "不足 3 年" in out["answer"]


def test_seasonal_adjustment_short_series_is_empty():
    out = run_capability("D-J02", series=_seasonal_adjustment_series(59), dates=_dates(59))
    assert out["ok"] is False
    assert out["quality"]["status"] == STATUS_EMPTY


def test_seasonal_adjustment_requires_dates():
    out = run_capability("D-J02", series=_seasonal_adjustment_series())
    assert out["ok"] is False
    assert out["quality"]["status"] == STATUS_EMPTY
    assert "日期" in out["answer"]


# ---------------- D-J04 变点检测 ----------------


def _change_point_series():
    return [0.0] * 60 + [5.0] * 60


def test_change_point_executes_all_methods_and_maps_dates():
    from l1agg import methods

    series = _change_point_series()
    dates = _dates(len(series))
    out = run_capability("D-J04", series=series, dates=dates, symbol="BTC")
    assert out["ok"] is True
    assert out["capability"] == "D-J04"
    assert out["intent"] == "change_point_query"
    assert out["quality"]["status"] == STATUS_GOOD
    assert out["quality"]["sample_n"] == len(series)
    block = out["data"]["capabilities"]["D-J04"]
    method_ids = ["T22", "T23", "SC49", "SC50", "SC51"]
    assert block["methods"] == method_ids
    for method_id in method_ids:
        assert block["results"][method_id] == methods.run(method_id, series)["result"]
    assert any(abs(point - 60) <= 3 for point in block["results"]["SC49"]["breakpoints"])
    assert block["results"]["SC50"]["breakpoints"] == [60]
    assert block["results"]["SC51"]["p"] < 0.01
    assert block["breakpoint_dates"]["SC50"] == [dates[60]]
    assert block["breakpoint_dates"]["SC51"] == dates[block["results"]["SC51"]["point"]]
    assert "候选变点" in out["answer"]


def test_change_point_short_series_is_empty():
    out = run_capability("D-J04", series=_change_point_series()[:59])
    assert out["ok"] is False
    assert out["quality"]["status"] == STATUS_EMPTY


# ---------------- D-E05 / D-E06 / D-E11 相关 ----------------


def test_correlation_identical_series():
    px = _prices(300)
    out = run_capability("D-E05", x=px, y=list(px), x_name="BTC", y_name="BTC2")
    block = out["data"]["capabilities"]["D-E05"]
    assert block["pearson"]["r"] == pytest.approx(1.0)
    assert block["kendall"]["tau"] == pytest.approx(1.0)
    assert block["same_direction"]["ratio"] == 1.0
    assert "D-E11" in out["data"]["capabilities"]
    assert out["data"]["capabilities"]["D-E06"]["gate"] == "ok"


def test_shared_executor_envelope_carries_requested_capability():
    px = _prices(300)
    de05 = run_capability("D-E05", x=px, y=list(px))
    de06 = run_capability("D-E06", x=px, y=list(px), max_lag=3)
    de11 = run_capability("D-E11", x=px, y=list(px), dates=_dates(300))

    assert (de05["capability"], de05["intent"]) == ("D-E05", "correlation_query")
    assert (de06["capability"], de06["intent"]) == ("D-E06", "correlation_query")
    assert (de11["capability"], de11["intent"]) == ("D-E11", "cross_check")


def test_cycle_alignment_uses_aligned_returns_and_dates():
    n = 140
    returns = [math.sin(i / 9.0) * 0.02 for i in range(n)]
    out = run_capability("D-E11", x=returns, y=list(returns), dates=_dates(n))

    block = out["data"]["capabilities"]["D-E11"]
    assert block["cycle_alignment"]["ratio"] == 1.0
    assert block["cycle_alignment"]["months"] >= 4
    assert block["cycle_alignment"]["n"] == n
    assert "C18" in block["methods"]


def test_cycle_alignment_drops_complete_rows_and_dates_at_original_positions():
    n = 140
    x = [math.sin(i / 7.0) * 0.02 for i in range(n)]
    y = [0.4 * value + math.cos(i / 11.0) * 0.01 for i, value in enumerate(x)]
    dates = _dates(n)
    missing = {5: (None, y[5]), 17: (x[17], "invalid"), 63: (None, None), 119: (x[119], None)}
    dirty_x, dirty_y = list(x), list(y)
    for i, (x_value, y_value) in missing.items():
        dirty_x[i], dirty_y[i] = x_value, y_value
    keep = [i for i in range(n) if i not in missing]

    expected = run_capability(
        "D-E11", x=[x[i] for i in keep], y=[y[i] for i in keep], dates=[dates[i] for i in keep]
    )
    actual = run_capability("D-E11", x=dirty_x, y=dirty_y, dates=dates)

    assert actual == expected
    assert actual["data"]["capabilities"]["D-E11"]["cycle_alignment"]["n"] == n - len(missing)


def test_ccf_exposes_bh_fdr_for_complete_lag_search():
    n = 160
    x = [math.sin(i * 0.7) + 0.3 * math.cos(i * 1.3) for i in range(n)]
    y = [0.0] + x[:-1]
    out = run_capability("D-E06", x=x, y=y, max_lag=5)
    block = out["data"]["capabilities"]["D-E06"]
    lags = list(range(-5, 6))

    assert block["methods"] == ["T03", "T04", "M11", "M12"]
    assert block["lags"] == lags
    for key in ("ccf", "r", "p", "q", "p_adj", "significant", "n_by_lag"):
        assert len(block[key]) == len(lags)
    assert block["p_adj"] == block["q"]
    assert block["n_by_lag"] == [n - abs(lag) for lag in lags]
    assert block["best_lag"] == 1
    best_index = lags.index(block["best_lag"])
    assert block["best_ccf"] == block["r"][best_index]
    assert block["best_p"] == block["p"][best_index]
    assert block["best_q"] == block["q"][best_index] == block["best_p_adj"]
    assert block["best_significant"] is True
    assert block["significant"][best_index] is True
    assert block["search_space"] == {
        "pairs": 1,
        "lag": lags,
        "window": [n],
        "h": [],
        "tests": len(lags),
    }
    assert block["fdr"] == {"method": "BH-FDR", "alpha": 0.05, "m": len(lags)}
    assert "q=" in out["answer"]


def test_ccf_random_negative_does_not_promote_uncorrected_best_lag():
    for seed in range(100):
        rng = random.Random(seed)
        x = [rng.gauss(0.0, 1.0) for _ in range(160)]
        y = [rng.gauss(0.0, 1.0) for _ in range(160)]
        out = run_capability("D-E06", x=x, y=y, max_lag=10)
        block = out["data"]["capabilities"]["D-E06"]
        if block["best_p"] < 0.05 and block["best_q"] >= 0.05:
            break
    else:
        pytest.fail("确定性随机负例中未找到原始 p 显著但 BH-FDR 不显著的样本")

    best_index = block["lags"].index(block["best_lag"])
    assert block["best_significant"] is False
    assert block["significant"][best_index] is False
    assert block["p_adj"][best_index] == block["best_q"]
    assert "校正后不显著" in out["answer"]


def test_correlation_short_pair_blocks():
    out = run_capability("D-E05", x=_prices(40), y=_prices(40, seed=9))
    assert out["ok"] is False and "对齐点" in out["answer"]


def test_correlation_pair_drops_complete_rows_at_original_positions():
    n = 140
    x = [math.sin(i / 7.0) + i * 0.001 for i in range(n)]
    y = [0.4 * value + math.cos(i / 11.0) for i, value in enumerate(x)]
    missing = {5: (None, y[5]), 17: (x[17], "invalid"), 63: (None, None), 119: (x[119], None)}
    dirty_x, dirty_y = list(x), list(y)
    for i, (x_value, y_value) in missing.items():
        dirty_x[i], dirty_y[i] = x_value, y_value
    keep = [i for i in range(n) if i not in missing]

    expected = run_capability("D-E05", x=[x[i] for i in keep], y=[y[i] for i in keep])
    actual = run_capability("D-E05", x=dirty_x, y=dirty_y)

    assert actual == expected
    assert actual["quality"]["sample_n"] == n - len(missing)


def test_correlation_matrix_topk_orders_by_abs_then_name_and_preserves_sign():
    n = 120
    base = [float(i) for i in range(n)]
    panel = {
        "WAVE": [math.sin(i / 7.0) for i in range(n)],
        "NEG": [-3.0 * v for v in base],
        "ETH": [2.0 * v for v in base],
        "BTC": base,
    }
    dates = _dates(n)
    out = run_capability("D-E05", series=panel, dates=dates, k=3)
    assert out["ok"] is True and out["quality"]["status"] == STATUS_GOOD
    block = out["data"]["capabilities"]["D-E05"]
    assert block["methods"] == ["M05", "M06", "M07"]
    assert block["matrix"]["names"] == ["BTC", "ETH", "NEG", "WAVE"]
    assert block["matrix"]["matrix"]["BTC"]["NEG"] == pytest.approx(-1.0)
    assert block["average_correlation"]["n_assets"] == 4

    relationship = block["relationship_topk"]
    assert relationship["type"] == "contemporaneous"
    assert relationship["lag"] == 0 and relationship["h"] is None
    assert relationship["n"] == relationship["window"] == n
    assert relationship["as_of"] == dates[-1]
    assert relationship["align_method"] == "utc_daily_close"
    assert relationship["timezone"] == "UTC"
    assert relationship["search_space"] == {"pairs": 6, "lag": [0], "window": [n], "h": []}
    assert [(p["a"], p["b"]) for p in relationship["topk"]] == [
        ("BTC", "ETH"),
        ("BTC", "NEG"),
        ("ETH", "NEG"),
    ]
    assert [p["r"] for p in relationship["topk"]] == [1.0, -1.0, -1.0]
    assert all(p["p_adj"] == p["q"] for p in relationship["pairs"])
    assert out["quality"]["span"] == [dates[0], dates[-1]]
    assert "同期联动 TopK" in out["answer"] and "历史统计" in out["answer"]

    reversed_panel = dict(reversed(list(panel.items())))
    assert run_capability("D-E05", series=reversed_panel, dates=dates, k=3) == out


def test_correlation_matrix_requires_two_assets():
    out = run_capability("D-E05", series={"BTC": [float(i) for i in range(80)]})
    assert out["ok"] is False and "至少 2 个资产" in out["answer"]


def test_correlation_matrix_requires_60_complete_aligned_rows():
    n = 60
    btc = [float(i) for i in range(n)]
    eth = [2.0 * v for v in btc]
    eth[7] = None
    out = run_capability("D-E05", series={"BTC": btc, "ETH": eth}, dates=_dates(n))
    assert out["ok"] is False and "对齐点 59 < 60" in out["answer"]


def test_ccf_blocked_between_60_and_120():
    out = run_capability("D-E05", x=_prices(100), y=_prices(100, seed=2))
    assert out["data"]["capabilities"]["D-E05"]["gate"] == "ok"
    assert out["data"]["capabilities"]["D-E06"]["gate"] == "insufficient_history"


# ---------------- D-E01 条件收益 ----------------


def test_conditional_return_manifest_uses_method_library_contract():
    capability = next((cap for cap in manifest().capabilities if cap.id == "D-E01"), None)
    assert capability is not None
    assert capability.methods == ("B02", "B05", "F01", "H01")
    assert capability.min_n == 250


def test_conditional_return_reports_quantile_forward_returns():
    factor, prices = _factor_prices()
    out = run_capability("D-E01", factor=factor, prices=prices, k=5, name="TEST")

    assert out["ok"] is True and out["quality"]["status"] == STATUS_GOOD
    assert out["quality"]["sample_n"] == 300
    block = out["data"]["capabilities"]["D-E01"]
    assert block["methods"] == ["B02", "B05", "F01", "H01"]
    assert block["bins"]["k"] == 5
    assert [row["state"] for row in block["conditional"]["table"]] == [
        "q0",
        "q1",
        "q2",
        "q3",
        "q4",
    ]
    assert block["conditional"]["table"][0]["mean"] < 0
    assert block["conditional"]["table"][-1]["mean"] > 0
    assert block["price_returns"]["n"] == len(prices)
    assert block["baseline_t"]["n"] == 300
    assert block["horizon"] == 1


def test_conditional_return_needs_250_aligned_forward_samples():
    factor, prices = _factor_prices(200)
    out = run_capability("D-E01", factor=factor, prices=prices)
    assert out["ok"] is False and "250" in out["answer"]


# ---------------- D-E02 分位 → 前瞻收益 ----------------


def test_percentile_forward_exposes_pit_conditional_distribution():
    px = _prices(1600)
    out = run_capability("D-E02", prices=px, dates=_dates(1600), symbol="BTC")
    assert out["ok"] is True and out["quality"]["status"] == STATUS_GOOD
    block = out["data"]["capabilities"]["D-E02"]
    assert block["methods"] == ["I30", "R02"]
    a8 = block["conditional_distribution"]
    assert a8["gate"] == "ok" and a8["buckets"] == 4
    current = a8["result"]["by_horizon"][0]
    assert current["h"] == 1 and current["nonoverlap_n"] >= 250
    assert current["p10"] <= current["median"] <= current["p90"]
    assert "历史统计" in out["answer"] and "80% 历史区间" in out["answer"]
    assert not any(word in out["answer"] for word in ("将会", "预计", "必然"))


# ---------------- D-E14 相关状态条件分布 ----------------


def test_conditional_distribution_returns_pit_h1_h2_and_shared_bucket_methods():
    factor, prices = _correlation_state()
    out = run_capability(
        "D-E14",
        factor=factor,
        prices=prices,
        dates=_dates(len(prices)),
        name="平均相关度",
        symbol="BTC",
    )
    assert out["ok"] is True, out["answer"]
    assert out["quality"]["status"] == STATUS_GOOD
    block = out["data"]["capabilities"]["D-E14"]
    assert block["methods"] == ["B05", "B10", "R01", "R02", "R08"]
    assert block["pit"] is True
    assert block["requested_buckets"] == 4 and block["buckets"] == 4
    assert block["weak_horizons"] == []
    assert "states" not in block["conditional_distribution"]
    rows = block["by_horizon"]
    assert [row["h"] for row in rows] == [1, 2]
    for row in rows:
        distribution = row["distribution"]
        assert all(bucket["nonoverlap_n"] >= 250 for bucket in distribution["by_bucket"])
        assert row["conditional"] is None or row["conditional"]["n"] == row["percentiles"]["n"]
        assert row["monotonic"]["n"] == row["percentiles"]["n"]
    h1, h2 = rows
    assert h1["expression"]["state"] == str(block["conditional_distribution"]["bucket"])
    ordered_means = [
        row["mean"] for row in sorted(h1["conditional"]["table"], key=lambda row: int(row["state"]))
    ]
    assert h1["monotonic"]["bins"] == ordered_means
    assert h2["conditional"] is None and h2["expression"] is None
    assert h2["distribution"]["t"] is None and h2["distribution"]["p"] is None
    assert "历史统计" in out["answer"]
    assert not any(word in out["answer"] for word in ("将会", "预计", "必然"))


def test_conditional_distribution_degrades_four_to_two_buckets():
    factor, prices = _correlation_state(1200)
    out = run_capability("D-E14", factor=factor, prices=prices, horizons=(1,))
    assert out["ok"] is True, out["answer"]
    assert out["quality"]["status"] == STATUS_PARTIAL
    assert out["quality"]["degraded_reason"] == "bucket_nonoverlap_lt_250"
    block = out["data"]["capabilities"]["D-E14"]
    assert block["requested_buckets"] == 4 and block["buckets"] == 2
    assert all(
        bucket["nonoverlap_n"] >= 250
        for bucket in block["by_horizon"][0]["distribution"]["by_bucket"]
    )
    assert "降级" in out["answer"] and "降为 2 桶" in out["answer"]


def test_conditional_distribution_marks_only_weak_later_horizon():
    factor, prices = _correlation_state(2200)
    out = run_capability("D-E14", factor=factor, prices=prices)
    assert out["ok"] is True, out["answer"]
    assert out["quality"]["status"] == STATUS_PARTIAL
    block = out["data"]["capabilities"]["D-E14"]
    assert block["buckets"] == 4
    assert block["weak_horizons"] == [2]
    assert "降级" in out["answer"] and "h=2" in out["answer"]


def test_conditional_distribution_short_or_misaligned_input_fails_open():
    factor, prices = _correlation_state(200)
    short = run_capability("D-E14", factor=factor, prices=prices)
    assert short["ok"] is False and short["quality"]["status"] == STATUS_EMPTY
    mismatched = run_capability("D-E14", factor=factor[:-1], prices=prices)
    assert mismatched["ok"] is False and mismatched["quality"]["status"] == STATUS_EMPTY


def _two_axis_state(n=4800, seed=29):
    """二维相关状态（两轴 iid 高斯）+ 同步价格轴：PIT 滚动分位后各格近均匀。"""
    rng = random.Random(seed)
    factor = [rng.gauss(0.0, 1.0) for _ in range(n)]
    factor2 = [rng.gauss(0.0, 1.0) for _ in range(n)]
    return factor, factor2, _prices(n, seed=17, drift=0.0002, vol=0.01)


def test_conditional_distribution_two_axis_tier_a_four_by_four():
    factor, factor2, prices = _two_axis_state(4800)
    out = run_capability(
        "D-E14",
        factor=factor,
        factor2=factor2,
        prices=prices,
        dates=_dates(len(prices)),
        name="平均相关度",
        name2="波动率分位",
        horizons=(1,),
        symbol="BTC",
    )
    assert out["ok"] is True, out["answer"]
    block = out["data"]["capabilities"]["D-E14"]
    assert block["dim"] == 2
    assert block["tier"] == "A" and block["requested_tier"] == "A"
    assert block["degraded_tier"] is None
    assert block["buckets_per_axis"] == 4 and block["cells"] == 16
    assert block["min_cell_nonoverlap_n"] >= 250
    cells = block["by_horizon"][0]["distribution"]["by_cell"]
    assert len(cells) == 16
    assert all(cell["nonoverlap_n"] >= 250 for cell in cells)
    assert {(cell["axis1"], cell["axis2"]) for cell in cells} == {
        (row, column) for row in range(4) for column in range(4)
    }
    # 2D 一维序数无单调语义，不应输出 R08 单调性结论
    assert block["by_horizon"][0]["monotonic"] is None
    assert "Tier A" in out["answer"] and "历史统计" in out["answer"]
    assert not any(word in out["answer"] for word in ("将会", "预计", "必然"))


def test_conditional_distribution_two_axis_degrades_to_tier_b():
    factor, factor2, prices = _two_axis_state(2800)
    out = run_capability("D-E14", factor=factor, factor2=factor2, prices=prices, horizons=(1,))
    assert out["ok"] is True, out["answer"]
    block = out["data"]["capabilities"]["D-E14"]
    assert block["dim"] == 2
    assert block["tier"] == "B" and block["degraded_tier"] == "B"
    assert block["buckets_per_axis"] == 3 and block["cells"] == 9
    assert out["quality"]["status"] == STATUS_PARTIAL
    assert out["quality"]["degraded_reason"] == "bucket_nonoverlap_lt_250"
    assert [attempt["buckets_per_axis"] for attempt in block["tier_attempts"]] == [4, 3]
    assert block["tier_attempts"][0]["passed"] is False
    assert "降级" in out["answer"] and "Tier B" in out["answer"]


def test_conditional_distribution_two_axis_degrades_to_tier_d():
    factor, factor2, prices = _two_axis_state(1400)
    out = run_capability("D-E14", factor=factor, factor2=factor2, prices=prices, horizons=(1,))
    assert out["ok"] is True, out["answer"]
    block = out["data"]["capabilities"]["D-E14"]
    assert block["tier"] == "D" and block["degraded_tier"] == "D"
    assert block["buckets_per_axis"] == 2 and block["cells"] == 4
    assert block["min_cell_nonoverlap_n"] >= 250
    assert out["quality"]["status"] == STATUS_PARTIAL


def test_conditional_distribution_two_axis_falls_back_to_one_dimension():
    factor, factor2, prices = _two_axis_state(800)
    out = run_capability("D-E14", factor=factor, factor2=factor2, prices=prices, horizons=(1,))
    assert out["ok"] is True, out["answer"]
    block = out["data"]["capabilities"]["D-E14"]
    assert block["dim"] == 1 and block["tier"] is None
    assert block["cells"] is None
    assert block["buckets"] == 2  # 单维 4→2 桶兜底
    assert block["degraded_reason"] == "insufficient_2d"
    assert out["quality"]["status"] == STATUS_PARTIAL
    assert out["quality"]["degraded_reason"] == "insufficient_2d"
    assert "不出二维结论" in out["answer"]


def test_conditional_distribution_two_axis_misaligned_fails_open():
    factor, factor2, prices = _two_axis_state(1400)
    out = run_capability("D-E14", factor=factor, factor2=factor2[:-1], prices=prices)
    assert out["ok"] is False and out["quality"]["status"] == STATUS_EMPTY


# ---------------- D-E08 条件 IC ----------------


def test_conditional_ic_manifest_excludes_price_only_ic_decay():
    capability = manifest().get("D-E08")
    assert capability.methods == ("B11", "B13", "B14")
    assert "每桶非重叠" not in capability.notes

    out = run_capability(
        "D-E08",
        factor=[math.sin(i / 9.0) for i in range(250)],
        forward=[math.sin(i / 9.0) * 0.3 for i in range(250)],
    )
    assert out["data"]["capabilities"]["D-E08"]["methods"] == ["B11", "B13", "B14"]


def test_conditional_ic_positive_relationship():
    n = 300
    rng = random.Random(11)
    factor = [math.sin(i / 9.0) for i in range(n)]
    forward = [v * 0.3 + rng.gauss(0, 0.05) for v in factor]
    out = run_capability("D-E08", factor=factor, forward=forward, name="TEST")
    block = out["data"]["capabilities"]["D-E08"]
    assert block["ic"]["ic"] > 0.5
    assert block["monotonic"] in ("increasing", "non_monotonic")


def test_conditional_ic_needs_250():
    out = run_capability("D-E08", factor=_prices(200), forward=_prices(200, seed=8))
    assert out["ok"] is False and "250" in out["answer"]
    assert "每桶非重叠" not in out["answer"]


def test_conditional_ic_drops_complete_rows_at_original_positions():
    n = 280
    factor = [math.sin(i / 9.0) + i * 0.002 for i in range(n)]
    forward = [0.3 * value + math.cos(i / 13.0) * 0.02 for i, value in enumerate(factor)]
    missing = {
        3: (None, forward[3]),
        41: (factor[41], "invalid"),
        127: (None, None),
        269: (factor[269], None),
    }
    dirty_factor, dirty_forward = list(factor), list(forward)
    for i, (factor_value, forward_value) in missing.items():
        dirty_factor[i], dirty_forward[i] = factor_value, forward_value
    keep = [i for i in range(n) if i not in missing]

    expected = run_capability(
        "D-E08", factor=[factor[i] for i in keep], forward=[forward[i] for i in keep]
    )
    actual = run_capability("D-E08", factor=dirty_factor, forward=dirty_forward)

    assert actual == expected
    assert actual["quality"]["sample_n"] == n - len(missing)


# ---------------- 契约：JSON schema + 序列化 ----------------


def _nested_gates(node, root=True):
    """收集能力块内嵌的方法级 gate 值（跳过块自身的 gate）。"""
    found = []
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "gate" and not root and isinstance(value, str):
                found.append(value)
            found.extend(_nested_gates(value, root=False))
    elif isinstance(node, list):
        for value in node:
            found.extend(_nested_gates(value, root=False))
    return found


def test_nested_method_gates_are_declared():
    """K-09 回归：方法级 gate 必须落在 envelope.GATE_METHOD 声明集合内。"""
    cases = (
        ("D-J15", {"series": _j_walk(), "components": [0.2] * 40}),
        ("D-J20", {"X": {"X": _j_rows()}, "y": _j_target(_j_rows())}),
        ("D-J26", {"time": [i + 1 for i in range(40)], "event": [1, 0] * 20}),
    )
    for capability_id, kwargs in cases:
        out = run_capability(capability_id, **kwargs)
        block = out["data"]["capabilities"][capability_id]
        for value in _nested_gates(block):
            assert value in GATE_METHOD, (capability_id, value)


def test_every_capability_block_declares_gate():
    """K-01 回归：能力块必须带 gate（G/J 组曾整体遗漏，见 TD §7.4 A-1）。"""
    allowed = {
        "ok",
        "partial",
        "degraded",
        "insufficient_samples",
        "insufficient_history",
        "no_data",
    }
    cases = (
        ("D-G01", {"panel": _g_panel()}),
        ("D-J01", {"series": _j_walk()}),
        ("D-J20", {"X": {"X": _j_rows()}, "y": _j_target(_j_rows())}),
        ("D-A04", {"values": _prices(), "dates": _dates()}),
    )
    for capability_id, kwargs in cases:
        out = run_capability(capability_id, **kwargs)
        block = out["data"]["capabilities"][capability_id]
        assert "gate" in block, capability_id
        assert block["gate"] in allowed, (capability_id, block["gate"])


def test_output_validates_against_json_schema():
    jsonschema = pytest.importorskip("jsonschema")
    schema_path = os.path.join(_MODULE_ROOT, "contracts", "capability_result.schema.json")
    with open(schema_path, "r", encoding="utf-8") as fh:
        schema = json.load(fh)
    outputs = [
        run_capability("D-E01", **dict(zip(("factor", "prices"), _factor_prices(), strict=True))),
        run_capability("D-E10", prices=_prices(), symbol="BTC", dates=_dates()),
        run_capability("D-E03", prices=_prices(), dates=_dates()),
        run_capability("D-E07", prices=_prices()),
        run_capability("D-E05", x=_prices(), y=_prices(seed=3)),
        run_capability("D-E05", series={"BTC": _prices(), "ETH": _prices(seed=3)}, dates=_dates()),
        run_capability("D-E02", prices=_prices(1100), dates=_dates(1100)),
        run_capability(
            "D-E14",
            **dict(
                zip(("factor", "prices"), _correlation_state(1400), strict=True),
                dates=_dates(1400),
                horizons=(1,),
            ),
        ),
        run_capability("D-E12", **_alignment_kwargs()),
        run_capability("D-E08", factor=_prices(), forward=_prices(seed=4)),
        run_capability("D-G16", series=_portfolio_returns(), dates=_dates(160)),
        run_capability(
            "D-G19",
            **dict(zip(("factor", "forward", "prices"), _ic_inputs(), strict=True)),
        ),
        run_capability(
            "D-G20", **dict(zip(("factor", "forward"), _quantile_inputs(), strict=True))
        ),
        run_capability("D-J22", series=_panel_inputs(), k=3),
        run_capability("D-J24", series=_network_inputs(), k=2, threshold=0.5),
        run_capability("D-G14", series=_ewma_inputs(), lam=0.94, periods=365),
        run_capability(
            "D-J30",
            **dict(zip(("indicator", "prices"), _pit_inputs(), strict=True), dates=_dates(320)),
        ),
        run_capability(
            "D-A01",
            **dict(zip(("values", "dates"), _series_inputs(90, seed=59), strict=True)),
        ),
        run_capability("D-A02", values=_series_inputs(8, seed=73)[0], window=2),
        run_capability("D-A03", values=[100.0, 200.0], dates=["2022-01-01", "2024-01-01"]),
        run_capability("D-A04", values=_series_inputs(90, seed=67)[0], lookback=60),
        run_capability("D-A06", values=_series_inputs(90, seed=69)[0], window=60),
        run_capability("D-A07", prices=_drawdown_prices(), dates=_dates(300)),
        run_capability("D-A08", values=_yoy_values(), dates=_dates(36)),
        run_capability("D-A09", values=_yoy_values(12), dates=_dates(12)),
        run_capability(
            "D-A10",
            **dict(zip(("nominal", "cpi"), _real_rate_inputs(), strict=True), dates=_dates(36)),
        ),
        run_capability(
            "D-A11",
            **dict(zip(("x", "y"), _corr_pair(90), strict=True)),
            window=30,
            dates=_dates(90),
        ),
        run_capability(
            "D-A12",
            **dict(zip(("x", "y"), _corr_pair(150), strict=True)),
            max_lag=10,
            dates=_dates(150),
        ),
        run_capability("D-A13", values=_extreme_values(120), dates=_dates(120)),
        run_capability("D-A15", values=_flow_values(40), dates=_dates(40)),
        run_capability("D-A16", values=_supply_values(40), dates=_dates(40)),
        run_capability("D-B08", prices=_trend_prices(120), dates=_dates(120)),
        run_capability("D-B09", prices=_ath_prices(300), dates=_dates(300)),
        run_capability("D-G08", prices=_momentum_prices(280), dates=_dates(280)),
        run_capability("D-G09", prices=_vol_target_prices(120), dates=_dates(120)),
        run_capability("D-G22", series=_ar1(400)),
        run_capability("D-J02", series=_seasonal_adjustment_series(), dates=_dates(120)),
        run_capability("D-J04", series=_change_point_series(), dates=_dates(120)),
        run_capability(
            "D-G23",
            **dict(zip(("prices", "events", "dates"), _event_car_prices()[:3], strict=True)),
        ),
        run_capability("D-A14", series=_crowding(), dates=_dates(300), symbol="BTC"),
        run_capability(
            "D-E04",
            prices=_event_prices(),
            events=[_dates(300)[i] for i in range(20, 280, 6)],
            dates=_dates(300),
        ),
        run_capability("D-E09", values=[0.01, -0.02, 0.03, -0.01] * 10),
        run_capability("D-E10", prices=[100.0]),
    ]
    for out in outputs:
        jsonschema.validate(instance=out, schema=schema)


def test_outputs_are_json_serializable_and_deterministic():
    a = run_capability("D-E10", prices=_prices(), symbol="BTC", dates=_dates())
    b = run_capability("D-E10", prices=_prices(), symbol="BTC", dates=_dates())
    assert json.dumps(a, sort_keys=True, ensure_ascii=False) == json.dumps(
        b, sort_keys=True, ensure_ascii=False
    )
    for cid, kw in (
        ("D-E03", {"prices": _prices(), "dates": _dates()}),
        ("D-E07", {"prices": _prices()}),
        ("D-E05", {"x": _prices(), "y": _prices(seed=3)}),
    ):
        first = json.dumps(run_capability(cid, **kw), sort_keys=True, default=str)
        second = json.dumps(run_capability(cid, **kw), sort_keys=True, default=str)
        assert first == second, cid


def test_manifest_matches_methods_actually_executed_across_capability_branches(monkeypatch):
    import l1agg.methods as methods
    from l1agg.capabilities import institutional as capability_institutional
    from l1agg.capabilities import research_stats as capability_research_stats
    from l1agg.capabilities import stats as capability_stats

    jsonschema = pytest.importorskip("jsonschema")
    schema_path = os.path.join(_MODULE_ROOT, "contracts", "capability_result.schema.json")
    with open(schema_path, "r", encoding="utf-8") as fh:
        schema = json.load(fh)

    real_run = capability_stats.run_method
    calls = []

    def recording_run(method_id, data, **params):
        out = real_run(method_id, data, **params)
        if out.get("gate") == "ok":
            calls.append(method_id)
        return out

    monkeypatch.setattr(capability_stats, "run_method", recording_run)
    monkeypatch.setattr(capability_institutional, "run_method", recording_run)
    monkeypatch.setattr(capability_research_stats, "run_method", recording_run)
    monkeypatch.setattr(methods, "run", recording_run)
    observed = {cap.id: set() for cap in manifest().capabilities}
    scenarios = (
        ("D-E01", dict(zip(("factor", "prices"), _factor_prices(), strict=True))),
        ("D-E02", {"prices": _prices(1600), "dates": _dates(1600)}),
        (
            "D-E14",
            dict(
                zip(("factor", "prices"), _correlation_state(1400), strict=True),
                dates=_dates(1400),
                horizons=(1,),
            ),
        ),
        ("D-E03", {"prices": _prices(), "dates": _dates()}),
        ("D-E05", {"x": _prices(300), "y": _prices(300, seed=3)}),
        (
            "D-E11",
            {
                "x": [math.sin(i / 9.0) * 0.02 for i in range(140)],
                "y": [math.cos(i / 11.0) * 0.02 for i in range(140)],
                "dates": _dates(140),
            },
        ),
        (
            "D-E05",
            {
                "series": {"BTC": _prices(120), "ETH": _prices(120, seed=3)},
                "dates": _dates(120),
            },
        ),
        ("D-E07", {"prices": _prices(300)}),
        ("D-E08", {"factor": _prices(300), "forward": _prices(300, seed=4)}),
        ("D-E10", {"prices": _prices(), "dates": _dates()}),
        (
            "D-E15",
            {
                "prices": _prices(n=700),
                "dates": _dates(n=700),
                "highs": [p * 1.01 for p in _prices(n=700)],
                "lows": [p * 0.99 for p in _prices(n=700)],
            },
        ),
        ("D-E12", _alignment_kwargs()),
        ("D-G16", {"series": _portfolio_returns(), "weights": {"BTC": 0.6, "ETH": 0.4}}),
        (
            "D-G19",
            dict(zip(("factor", "forward", "prices"), _ic_inputs(), strict=True)),
        ),
        ("D-G20", dict(zip(("factor", "forward"), _quantile_inputs(), strict=True))),
        ("D-J22", {"series": _panel_inputs(), "k": 3}),
        ("D-J24", {"series": _network_inputs(), "k": 2, "threshold": 0.5}),
        ("D-G14", {"series": _ewma_inputs(), "lam": 0.94, "periods": 365}),
        (
            "D-J30",
            dict(
                zip(("indicator", "prices"), _pit_inputs(), strict=True),
                dates=_dates(320),
            ),
        ),
        (
            "D-A01",
            dict(zip(("values", "dates"), _series_inputs(90, seed=61), strict=True)),
        ),
        ("D-A02", {"values": _series_inputs(8, seed=83)[0], "window": 2}),
        ("D-A03", {"values": [100.0, 145.0], "dates": ["2021-01-01", "2023-06-01"]}),
        ("D-A04", {"values": _series_inputs(90, seed=71)[0], "lookback": 30}),
        ("D-A06", {"values": _series_inputs(90, seed=73)[0], "window": 60}),
        ("D-A07", {"prices": _drawdown_prices(), "dates": _dates(300)}),
        ("D-A08", {"values": _yoy_values(), "dates": _dates(36)}),
        ("D-A09", {"values": _yoy_values(12), "dates": _dates(12)}),
        (
            "D-A10",
            dict(zip(("nominal", "cpi"), _real_rate_inputs(), strict=True), dates=_dates(36)),
        ),
        (
            "D-A11",
            dict(
                zip(("x", "y"), _corr_pair(90), strict=True),
                window=30,
                dates=_dates(90),
            ),
        ),
        (
            "D-A12",
            dict(
                zip(("x", "y"), _corr_pair(150), strict=True),
                max_lag=10,
                dates=_dates(150),
            ),
        ),
        ("D-A13", {"values": _extreme_values(120), "dates": _dates(120)}),
        ("D-A15", {"values": _flow_values(40), "dates": _dates(40)}),
        ("D-A16", {"values": _supply_values(40), "dates": _dates(40)}),
        ("D-B08", {"prices": _trend_prices(120), "dates": _dates(120)}),
        ("D-B09", {"prices": _ath_prices(300), "dates": _dates(300)}),
        ("D-G08", {"prices": _momentum_prices(280), "dates": _dates(280)}),
        ("D-G09", {"prices": _vol_target_prices(120), "dates": _dates(120)}),
        ("D-G22", {"series": _ar1(300)}),
        ("D-J02", {"series": _seasonal_adjustment_series(), "dates": _dates(120)}),
        ("D-J04", {"series": _change_point_series(), "dates": _dates(120)}),
        (
            "D-G23",
            dict(zip(("prices", "events", "dates"), _event_car_prices()[:3], strict=True)),
        ),
        ("D-A14", {"series": _crowding(n=260)}),
        (
            "D-E04",
            {
                "prices": _event_prices(),
                "events": [_dates(300)[i] for i in range(20, 280, 6)],
                "dates": _dates(300),
            },
        ),
        (
            "D-E04",
            dict(
                zip(("prices", "dates"), _holiday_case(), strict=True),
                pre_holiday=True,
            ),
        ),
        ("D-G25", {"series": _tail_panel()}),
        ("D-J05", {"series": _cycle_prices(), "dates": _dates(len(_cycle_prices()))}),
        ("D-E09", {"values": [0.01, -0.02, 0.03, -0.01] * 10}),
        (
            "D-E09",
            {
                "pairs": {
                    "volume_up": [1, 1, 0, 0, 1, 1, 0, 1],
                    "price_up": [1, 0, 0, 1, 1, 0, 0, 1],
                }
            },
        ),
        ("D-A05", {"values": _prices(80), "dates": _dates(80)}),
        ("D-G01", {"panel": _g_panel()}),
        (
            "D-G02",
            {
                "panel": _g_panel(),
                "groups": {f"S{i:02d}": ("tech" if i % 2 == 0 else "fin") for i in range(32)},
            },
        ),
        ("D-G03", {"panel": _g_panel(), "k": 5}),
        ("D-G04", {"panel": _g_panel()}),
        ("D-G05", {"panel": _g_panel()}),
        ("D-G06", {"panel": _g_panel()}),
        ("D-G07", {"series": _prices(120), "d": 20}),
        ("D-G07", {"series": _prices(120), "other": _prices(120, seed=9), "d": 20}),
        ("D-G10", {"panel": _g_returns()}),
        ("D-G11", {"panel": _g_returns()}),
        ("D-G12", {"panel": _g_returns()}),
        ("D-G13", {"panel": _g_returns()}),
        ("D-G15", {"panel": _g_returns(), "k": 3}),
        (
            "D-G18",
            {
                "panel": _g_returns(),
                "weights": {f"A{i:02d}": float(i + 1) for i in range(8)},
                "benchmark_weights": {f"A{i:02d}": 1.0 for i in range(8)},
                "sector": {f"A{i:02d}": ("tech" if i % 2 == 0 else "fin") for i in range(8)},
            },
        ),
        ("D-G21", dict(zip(("factor", "target"), _g_macbeth(), strict=True))),
        ("D-G24", {"panel": _g_returns(), "q": 0.2}),
        # ---- J 组科研方法（D-J01…D-J29，24 个出口）----
        ("D-J01", {"series": _j_walk()}),
        ("D-J03", {"series": _j_walk(), "k": 3.0}),
        ("D-J06", {"series": _j_walk()}),
        ("D-J07", {"series": _j_walk()}),
        ("D-J08", {"series": _j_walk()}),
        ("D-J09", {"x": _j_walk(), "y": _j_partner(_j_walk())}),
        ("D-J10", {"series": _j_walk(), "other": _j_partner(_j_walk())}),
        ("D-J11", {"x": _j_walk(), "y": _j_partner(_j_walk()), "lag": 1}),
        ("D-J12", {"series": _j_walk()}),
        ("D-J13", {"series": _j_walk()}),
        ("D-J14", {"series": _j_walk()}),
        ("D-J15", {"series": _j_walk(), "components": [0.2] * 40}),
        ("D-J16", {"x": _j_walk()}),
        ("D-J16", {"x": _j_walk(), "y": _j_partner(_j_walk())}),
        ("D-J17", {"series": _j_walk(), "effect_size": 0.3}),
        ("D-J18", {"x": _j_walk(), "y": _j_partner(_j_walk())}),
        ("D-J19", {"groups": _j_groups()}),
        ("D-J20", {"X": {"X": _j_rows()}, "y": _j_target(_j_rows())}),
        ("D-J21", {"X": {"X": _j_rows()}, "y": _j_target(_j_rows())}),
        ("D-J23", {"X": {"X": _j_rows()}, "k": 3}),
        ("D-J25", {"coords": _j_coords(), "values": _j_spatial_values()}),
        ("D-J26", _j_survival()),
        ("D-J27", {"time": _j_survival()["time"], "event": _j_survival()["event"]}),
        (
            "D-J28",
            {"effects": _j_meta()[0], "se": _j_meta()[1]},
        ),
        ("D-J29", {"X": {"X": _j_missing_rows()}}),
    )

    for capability_id, kwargs in scenarios:
        calls.clear()
        out = run_capability(capability_id, **kwargs)
        assert out["ok"] is True, (capability_id, out["answer"])
        jsonschema.validate(instance=out, schema=schema)
        for gate_value in _nested_gates(out["data"]["capabilities"][capability_id]):
            assert gate_value in GATE_METHOD, (capability_id, gate_value)
        blocks = out["data"]["capabilities"]
        declared_union = set()
        for block_id, block in blocks.items():
            declared = set(manifest().get(block_id).methods)
            assert set(block["methods"]) <= declared
            observed[block_id].update(set(calls) & declared)
            declared_union.update(declared)
        assert set(calls) <= declared_union

    report = validate_execution(manifest(), observed, require_complete=True)
    assert report["summary"]["coverage"] == 1.0


# ---------------- S0：可见性外露闸（SPEC-54 §4.8 / ADR-V14） ----------------


def test_manifest_capabilities_default_to_public():
    m = manifest()
    assert m.visibility_default == "public"
    assert m.capabilities
    assert all(cap.visibility == "public" for cap in m.capabilities)


def test_validate_rejects_unknown_visibility():
    import dataclasses

    base = manifest()
    broken = dataclasses.replace(base.capabilities[0], visibility="secret")
    with pytest.raises(ManifestError, match="visibility"):
        validate(dataclasses.replace(base, capabilities=(broken,)))


def test_validate_rejects_unknown_internal_reference():
    import dataclasses

    base = manifest()
    with pytest.raises(ManifestError, match="visibility_internal"):
        validate(dataclasses.replace(base, visibility_internal=("D-Z99",)))


def test_assert_public_blocks_internal_capability(monkeypatch):
    import dataclasses
    import importlib

    # 包 __init__ 用同名函数覆盖了子模块属性，必须走 importlib 取真模块
    manifest_mod = importlib.import_module("l1agg.capabilities.manifest")

    base = manifest()
    internal = dataclasses.replace(base.capabilities[0], visibility="internal")
    patched = dataclasses.replace(
        base,
        capabilities=(internal,) + base.capabilities[1:],
        visibility_internal=(internal.id,),
    )
    monkeypatch.setattr(manifest_mod, "_CACHE", patched)
    with pytest.raises(PermissionError, match="禁止对外暴露"):
        manifest_mod.assert_public(internal.id)


def test_envelope_rejects_internal_trade_keys():
    q = quality_for(300, min_n=250)
    for leaked_key in ("signal", "order", "fill", "position", "comparison"):
        with pytest.raises(ValueError, match="内部交易字段"):
            build(
                capability="D-E10",
                intent="drawdown_query",
                answer="测试",
                data={"capabilities": {"D-E10": {"nested": [{leaked_key: 1}]}}},
                quality_block=q,
            )


# ---------------- S1：D-E15 趋势曲线（SPEC-54 §4.9） ----------------


def _trend_kwargs(n=700):
    prices = _prices(n=n)
    return {
        "prices": prices,
        "dates": _dates(n=n),
        "highs": [p * 1.01 for p in prices],
        "lows": [p * 0.99 for p in prices],
        "symbol": "BTC",
    }


def test_trend_query_shape_and_gates():
    env = run_capability("D-E15", **_trend_kwargs())
    block = env["data"]["capabilities"]["D-E15"]
    assert env["quality"]["status"] in {"good", "partial"}
    assert block["ema_order"] in {"bull", "bear", "mixed"}
    assert [row["window"] for row in block["slope_table"]] == [20, 60, 120, 250]
    assert block["slope_table"][0]["hac_corrected"] is False
    assert block["adx"]["adx"] > 0
    assert block["meta"]["smoothing"] == {"method": "EMA", "periods": [12, 26, 50]}
    assert len(block["smoothed"]) <= 500
    # 平滑曲线末点必须与 I02 方法层返回值一致（禁止能力层另写一套 EMA）
    assert block["smoothed"][-1]["ema12"] == pytest.approx(block["ema"]["12"], rel=1e-6)
    assert "建议" not in env["answer"] and "看涨" not in env["answer"]


def test_trend_query_replay_deterministic():
    first = run_capability("D-E15", **_trend_kwargs())
    second = run_capability("D-E15", **_trend_kwargs())
    assert first["data"] == second["data"]
    assert first["answer"] == second["answer"]


def test_trend_query_insufficient_history_partial():
    env = run_capability("D-E15", prices=_prices(n=120), dates=_dates(n=120), symbol="BTC")
    block = env["data"]["capabilities"]["D-E15"]
    assert env["quality"]["status"] == "partial"
    assert "sample_lt_250" in block["meta"]["degraded_reasons"]
    long_row = next(row for row in block["slope_table"] if row["window"] == 250)
    assert long_row["slope"] is None and long_row["degraded"] is True
    assert "adx_unavailable" in block["meta"]["degraded_reasons"]
