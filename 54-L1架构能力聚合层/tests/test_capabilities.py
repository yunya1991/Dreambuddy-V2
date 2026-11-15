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


# ---------------- manifest ----------------


def test_manifest_loads_and_validates():
    m = manifest()
    assert m.version >= 1
    ids = [cap.id for cap in m.capabilities]
    assert len(ids) == len(set(ids))
    assert {
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
        "D-G22",
        "D-G23",
        "D-J02",
        "D-J04",
    } <= set(ids)
    assert {"M01", "M02", "M03", "M04", "M05", "M06", "M07"} <= set(m.get("D-E05").methods)
    assert set(m.get("D-G22").methods) == {"Q06", "Q07"}
    assert set(m.get("D-G23").methods) == {"Q10", "Q11"}
    assert set(m.get("D-E07").methods) == {"B02", "B06", "B07", "B08", "B09"}
    assert set(m.get("D-J02").methods) == {"C13", "T10", "SC91"}
    assert m.get("D-J02").min_n == 60
    assert m.get("D-J02").min_span_days == 1095
    assert set(m.get("D-J04").methods) == {"T22", "T23", "SC49", "SC50", "SC51"}
    assert m.get("D-A14").intent == "metric_percentile"
    assert set(m.get("D-A14").methods) == {"F26"}
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
            "hac_significance",
            "crowding",
            "event_study",
            "event_car_significance",
            "seasonal_adjustment",
            "change_point",
            "count_series",
            "trend",
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
    from l1agg.capabilities import stats as capability_stats

    real_run = capability_stats.run_method
    calls = []

    def recording_run(method_id, data, **params):
        out = real_run(method_id, data, **params)
        if out.get("gate") == "ok":
            calls.append(method_id)
        return out

    monkeypatch.setattr(capability_stats, "run_method", recording_run)
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
    )

    for capability_id, kwargs in scenarios:
        calls.clear()
        out = run_capability(capability_id, **kwargs)
        assert out["ok"] is True, (capability_id, out["answer"])
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
