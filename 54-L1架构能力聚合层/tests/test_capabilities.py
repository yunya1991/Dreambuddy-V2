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
from l1agg.capabilities.manifest import Capability, Manifest, ManifestError, validate  # noqa: E402


def _prices(n=400, seed=5, drift=0.0005, vol=0.02):
    rng = random.Random(seed)
    out, px = [], 100.0
    for _ in range(n):
        px *= 1.0 + rng.gauss(drift, vol)
        out.append(px)
    return out


def _dates(n=400, start=datetime.date(2024, 1, 1)):
    return [(start + datetime.timedelta(days=i)).isoformat() for i in range(n)]


# ---------------- manifest ----------------


def test_manifest_loads_and_validates():
    m = manifest()
    assert m.version >= 1
    ids = [cap.id for cap in m.capabilities]
    assert len(ids) == len(set(ids))
    assert {"D-E02", "D-E03", "D-E05", "D-E06", "D-E07", "D-E08", "D-E10", "D-E11"} <= set(ids)
    assert {"M01", "M02", "M03", "M04", "M05", "M06", "M07"} <= set(m.get("D-E05").methods)
    for cap in m.capabilities:
        assert cap.executor.split(".")[-1] in {
            "seasonality",
            "correlation",
            "state_transition",
            "conditional_ic",
            "drawdown",
            "percentile_forward",
        }


def test_manifest_every_declared_capability_is_runnable():
    assert set(supported()) == {cap.id for cap in manifest().capabilities}


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
    assert block["methods"] == ["D20", "D21", "F09", "F10"]
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


def test_state_transition_short_series_is_empty():
    out = run_capability("D-E07", prices=_prices(50))
    assert out["ok"] is False


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


def test_correlation_short_pair_blocks():
    out = run_capability("D-E05", x=_prices(40), y=_prices(40, seed=9))
    assert out["ok"] is False and "对齐点" in out["answer"]


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


# ---------------- D-E08 条件 IC ----------------


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


# ---------------- 契约：JSON schema + 序列化 ----------------


def test_output_validates_against_json_schema():
    jsonschema = pytest.importorskip("jsonschema")
    schema_path = os.path.join(_MODULE_ROOT, "contracts", "capability_result.schema.json")
    with open(schema_path, "r", encoding="utf-8") as fh:
        schema = json.load(fh)
    outputs = [
        run_capability("D-E10", prices=_prices(), symbol="BTC", dates=_dates()),
        run_capability("D-E03", prices=_prices(), dates=_dates()),
        run_capability("D-E07", prices=_prices()),
        run_capability("D-E05", x=_prices(), y=_prices(seed=3)),
        run_capability("D-E05", series={"BTC": _prices(), "ETH": _prices(seed=3)}, dates=_dates()),
        run_capability("D-E02", prices=_prices(1100), dates=_dates(1100)),
        run_capability("D-E08", factor=_prices(), forward=_prices(seed=4)),
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
