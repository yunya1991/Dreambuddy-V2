# -*- coding: utf-8 -*-
"""T0 延续性统计分析（persistence）单元测试。

用「已知答案序列」锁定方法与口径，不依赖真实库：
  - iid 随机游走 → H≈0.5、VR≈1、φ≈0
  - AR(1) φ=0.6 → H>0.55、φ≈0.6
  - 线性指数价格 → R²≈1、t 显著
"""

import datetime
import math
import os
import sqlite3
import sys

import pytest

_MODULE_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
if _MODULE_ROOT not in sys.path:
    sys.path.insert(0, _MODULE_ROOT)

from l1agg import persistence as P  # noqa: E402

# ---------------- 确定性数据生成（不引入 numpy） ----------------


class _LCG:
    def __init__(self, seed=42):
        self.s = seed

    def uniform(self):
        self.s = (1103515245 * self.s + 12345) % (2**31)
        return self.s / (2**31)

    def normal(self):
        u1 = max(self.uniform(), 1e-12)
        u2 = self.uniform()
        return math.sqrt(-2.0 * math.log(u1)) * math.cos(2.0 * math.pi * u2)


def _iid_returns(n=3000, seed=7):
    g = _LCG(seed)
    return [0.0005 + 0.02 * g.normal() for _ in range(n)]


def _ar1_returns(n=3000, phi=0.6, seed=11):
    g = _LCG(seed)
    out, prev = [], 0.0
    for _ in range(n):
        prev = phi * prev + 0.01 * g.normal()
        out.append(prev)
    return out


def _prices_from_returns(rets, p0=100.0):
    prices = [p0]
    for r in rets:
        prices.append(prices[-1] * math.exp(r))
    return prices


def _temp_db(tmp_path, prices, symbol="BTC"):
    db = os.path.join(str(tmp_path), "t.db")
    conn = sqlite3.connect(db)
    conn.execute(
        "CREATE TABLE mm_metrics (sub_category TEXT, metric_name TEXT, "
        "timestamp INTEGER, metric_value REAL, source TEXT)"
    )
    today = datetime.datetime.now(datetime.timezone.utc).date()
    start = today - datetime.timedelta(days=len(prices))
    rows = [
        (
            symbol,
            "close_usd",
            int(
                datetime.datetime.combine(
                    start + datetime.timedelta(days=i), datetime.time(16), datetime.timezone.utc
                ).timestamp()
            ),
            v,
            "test",
        )
        for i, v in enumerate(prices)
    ]
    conn.executemany("INSERT INTO mm_metrics VALUES (?,?,?,?,?)", rows)
    conn.commit()
    conn.close()
    return db


# ---------------- A1 Hurst ----------------


def test_hurst_random_walk_near_half():
    h = P.hurst_rs(_iid_returns())
    assert 0.35 <= h["h"] <= 0.68, h
    assert h["confidence"] == "high"  # n=3000 >= 2000
    assert h["regime"] in ("random_walk", "persistent")


def test_hurst_persistent_series_above_half():
    h = P.hurst_rs(_ar1_returns())
    assert h["h"] > 0.55, h
    assert h["regime"] == "persistent"


def test_hurst_short_sample_marked_low_confidence():
    h = P.hurst_rs(_iid_returns(n=500))
    assert h["confidence"] == "low"
    assert h["n"] == 500


def test_hurst_rejects_tiny_sample():
    with pytest.raises(P.PersistenceError):
        P.hurst_rs([0.01] * 20)


def test_hurst_chunks_capped_for_comparability():
    # B3：块上限固定，长样本不再引入 512/1024 块，保证跨期 H 可比
    h = P.hurst_rs(_iid_returns(n=3000))
    assert h["max_chunk"] == P.HURST_MAX_CHUNK
    assert max(h["chunks"]) <= P.HURST_MAX_CHUNK
    assert h["confidence"] == "high" and h["regime_displayable"] is True


def test_hurst_low_confidence_not_displayable():
    h = P.hurst_rs(_iid_returns(n=500))
    assert h["regime_displayable"] is False


# ---------------- A2 方差比 ----------------


def test_variance_ratio_iid_near_one():
    v = P.variance_ratio(_iid_returns(n=4000), 5)
    assert 0.8 <= v["vr"] <= 1.2, v
    assert abs(v["z"]) < 2.5, v


def test_variance_ratio_ar1_above_one():
    v = P.variance_ratio(_ar1_returns(), 5)
    assert v["vr"] > 1.0, v


def test_variance_ratio_p_never_zero():
    # 强均值回复 + 极小噪声 → |z| 极大 → p 下溢，必须截断而非输出 0
    rets = [0.01 + (1e-6 if i % 2 else -1e-6) for i in range(400)]
    v = P.variance_ratio(rets, 5)
    assert v["p"] is not None and v["p"] > 0, v


# ---------------- A3 AR(1) / 半衰期 ----------------


def test_ar1_recovers_phi_and_halflife():
    a = P.ar1_halflife(_ar1_returns(phi=0.6))
    assert abs(a["phi"] - 0.6) < 0.08, a
    assert 1.0 < a["halflife_days"] < 2.0, a  # ln0.5/ln0.6 ≈ 1.36


def test_ar1_iid_phi_near_zero():
    a = P.ar1_halflife(_iid_returns())
    assert abs(a["phi"]) < 0.08, a


# ---------------- A4 连胜 / A5 转移 ----------------


def test_run_length_known_sequence():
    # UUU DD U | UUU DD U | UUU DD U → 跨块 U 合并为 UUUU
    seq = [0.01, 0.01, 0.01, -0.01, -0.01, 0.01] * 3
    r = P.run_length_stats(seq)
    assert r["n_runs"] == 7
    assert r["max_run"] == 4
    assert r["max_up"] == 4
    assert r["max_down"] == 2


def test_transition_matrix_known_sequence():
    # 20 涨 + 20 跌 + 20 涨 → uu=38, ud=1, dd=19, du=1
    t = P.transition_matrix([0.01] * 20 + [-0.01] * 20 + [0.01] * 20)
    assert t["p_up_up"] == pytest.approx(38 / 39, abs=1e-4)
    assert t["p_down_down"] == pytest.approx(19 / 20, abs=1e-4)
    assert t["steady_up"] == pytest.approx((1 / 20) / (1 / 39 + 1 / 20), abs=1e-4)
    assert t["n"] == 59
    assert t["n_zero"] == 0


def test_zero_returns_skipped_and_counted():
    # I1：A4/A5 统一跳过 r==0，并把跳过的个数写进 n_zero
    seq = [0.01, 0.0, 0.0, -0.01, 0.01] * 10
    r = P.run_length_stats(seq)
    assert r["n_zero"] == 20 and r["n"] == 30
    t = P.transition_matrix(seq)
    assert t["n_zero"] == 20 and t["n"] == 29


# ---------------- A6 趋势斜率 ----------------


def test_trend_slope_exact_exponential():
    prices = [100.0 * math.exp(0.01 * i) for i in range(300)]
    s = P.trend_slope(prices)
    assert s["slope_per_day"] == pytest.approx(0.01, abs=1e-9)
    assert s["r2"] == pytest.approx(1.0, abs=1e-6)
    assert abs(s["t"]) > 100
    assert s["p"] == pytest.approx(1e-12, rel=0.0)  # 下溢截断，禁止输出 0


def test_trend_slope_rejects_non_positive():
    with pytest.raises(P.PersistenceError):
        P.trend_slope([1.0, 2.0, 0.0, 3.0] * 10)


def test_trend_slope_declares_no_hac():
    # B1：t 未做 HAC 修正必须显式声明，禁止下游当显著性证据
    s = P.trend_slope([100.0 * math.exp(0.001 * i) for i in range(200)])
    assert s["hac_corrected"] is False
    assert "HAC" in s["note"]


# ---------------- A7 IC 衰减 ----------------


def test_ic_decay_block_trend_has_positive_short_horizon_ic():
    # 100 日一段的单边行情，20 日动量与次日方向高度同向
    rets = []
    for block in range(30):
        rets.extend([0.01] * 100 if block % 2 == 0 else [-0.01] * 100)
    d = P.ic_decay(_prices_from_returns(rets), lookback=20, horizons=(1, 5, 20))
    h1 = next(it for it in d["items"] if it["h"] == 1)
    assert h1["ric"] is not None and h1["ric"] > 0.5, h1
    assert all(-1.0 <= it["ric"] <= 1.0 for it in d["items"] if it["ric"] is not None)


def test_ic_decay_reports_all_phases():
    # B2：非重叠口径遍历 h 个相位，输出均值与极差，避免固定相位选择偏差
    rets = []
    for block in range(30):
        rets.extend([0.01] * 100 if block % 2 == 0 else [-0.01] * 100)
    d = P.ic_decay(_prices_from_returns(rets), lookback=20, horizons=(1, 5, 20))
    for it in d["items"]:
        assert it["n_phases"] == it["h"], it
        if it["ric_nonoverlap"] is not None:
            assert (
                it["ric_nonoverlap_min"] <= it["ric_nonoverlap"] <= it["ric_nonoverlap_max"] + 1e-9
            )


# ---------------- A8 单资产波动状态 → 条件前瞻分布 ----------------


def test_a8_conditional_distribution_uses_four_pit_buckets(tmp_path):
    prices = _prices_from_returns(_iid_returns(n=1600))
    db = _temp_db(tmp_path, prices)
    a8 = P.build_profile(db, "BTC", days=2000)["metrics"]["conditional_distribution"]
    assert a8["gate"] == "ok"
    assert (a8["state"], a8["state_method"], a8["method"]) == ("volatility", "I30", "R02")
    assert (a8["h"], a8["requested_buckets"], a8["buckets"]) == (1, 4, 4)
    assert a8["degraded_reason"] is None
    result = a8["result"]
    assert result["pit"] is True and result["as_of"] is not None
    current = result["by_horizon"][0]
    assert current["h"] == 1
    assert current["p10"] <= current["median"] <= current["p90"]
    assert current["effective_n"] >= current["nonoverlap_n"] >= 250
    assert len(current["by_bucket"]) == 4
    assert all(row["nonoverlap_n"] >= 250 for row in current["by_bucket"])


def test_a8_conditional_distribution_degrades_four_to_two_buckets(tmp_path):
    prices = _prices_from_returns(_iid_returns(n=1100))
    db = _temp_db(tmp_path, prices)
    prof = P.build_profile(db, "BTC", days=1500)
    a8 = prof["metrics"]["conditional_distribution"]
    assert a8["gate"] == "ok"
    assert (a8["requested_buckets"], a8["buckets"]) == (4, 2)
    assert a8["degraded_reason"] == "bucket_nonoverlap_lt_250"
    current = a8["result"]["by_horizon"][0]
    assert len(current["by_bucket"]) == 2
    assert all(row["nonoverlap_n"] >= 250 for row in current["by_bucket"])
    assert "降为 2 桶" in prof["text"]
    assert not any(word in prof["text"] for word in ("将会", "预计", "必然"))


def test_a8_short_sample_has_independent_gate(tmp_path):
    prices = _prices_from_returns(_iid_returns(n=500))
    db = _temp_db(tmp_path, prices)
    prof = P.build_profile(db, "BTC", days=800)
    a8 = prof["metrics"]["conditional_distribution"]
    assert a8["gate"] == "insufficient_samples"
    assert a8["buckets"] == 2
    assert a8["result"]["by_horizon"][0]["effective_n"] > 0
    assert a8["result"]["by_horizon"][0]["nonoverlap_n"] < 250
    # A8 是 T0.5 扩展门禁，不 retroactively 改变 A1–A7 的 good 质量语义。
    assert prof["quality"]["status"] == "good"


# ---------------- 聚合画像 ----------------


def test_build_profile_good(tmp_path):
    prices = _prices_from_returns(_iid_returns(n=500))
    db = _temp_db(tmp_path, prices)
    prof = P.build_profile(db, "BTC", days=800)
    assert prof["kind"] == "persistence"
    assert prof["quality"]["status"] == "good"
    assert prof["quality"]["degraded_reason"] is None
    assert prof["sample_n"] == len(prices) - 1
    for key in ("hurst", "variance_ratio", "ar1", "runs", "transition", "trend", "ic_decay"):
        assert prof["metrics"][key] is not None, key
    assert "Hurst" in prof["text"] and P.CAVEAT in prof["text"]


def test_build_profile_partial_when_short(tmp_path):
    prices = _prices_from_returns(_iid_returns(n=120))
    db = _temp_db(tmp_path, prices)
    prof = P.build_profile(db, "BTC", days=800, min_n=250)
    assert prof["quality"]["status"] == "partial"
    assert prof["quality"]["degraded_reason"] == "insufficient_samples"
    assert "降级" in prof["text"]


def test_build_profile_records_failed_methods(tmp_path):
    # 常数价格 → 收益全 0 → 方差比/AR1 失败，但画像仍返回
    db = _temp_db(tmp_path, [100.0] * 400)
    prof = P.build_profile(db, "BTC", days=800)
    assert prof["quality"]["status"] == "degraded"
    assert "variance_ratio" in prof["quality"]["failed_methods"]
    assert prof["metrics"]["variance_ratio"] is None
    assert prof["quality"]["degraded_reason"] == "partial_methods_failed"
    assert "降级" in prof["text"]


def test_profile_text_hides_regime_when_low_confidence(tmp_path):
    # 评审 §6 反对 2：n<2000 时文本层不得出现「持续/反持续」标签
    prices = _prices_from_returns(_iid_returns(n=500))
    db = _temp_db(tmp_path, prices)
    prof = P.build_profile(db, "BTC", days=800)
    assert prof["metrics"]["hurst"]["regime_displayable"] is False
    assert "口径敏感" in prof["text"]
    assert "持续" not in prof["text"]
    assert "未做自相关修正" in prof["text"]


def test_profile_quality_declares_comparability(tmp_path):
    prices = _prices_from_returns(_iid_returns(n=500))
    db = _temp_db(tmp_path, prices)
    q = P.build_profile(db, "BTC", days=800)["quality"]
    assert q["lookback_days"] == 800
    assert q["hurst_max_chunk"] == P.HURST_MAX_CHUNK
    assert any(n.startswith("trend_t_no_hac") for n in q["notes"])


def test_report_cli_json_single_asset(tmp_path, capsys):
    import json

    from l1agg.persistence import report as R

    prices = _prices_from_returns(_iid_returns(n=500))
    db = _temp_db(tmp_path, prices)
    out_dir = os.path.join(str(tmp_path), "reports")
    rc = R.main(["--db", db, "--symbols", "BTC", "--days", "800", "--out", out_dir, "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["kind"] == "persistence" and payload["symbol"] == "BTC"
    assert not os.path.isdir(out_dir)  # --json 不落盘


def test_profile_matches_schema(tmp_path):
    jsonschema = pytest.importorskip("jsonschema")
    import json

    schema_path = os.path.join(_MODULE_ROOT, "contracts", "persistence.schema.json")
    with open(schema_path, encoding="utf-8") as fh:
        schema = json.load(fh)

    prices = _prices_from_returns(_iid_returns(n=500))
    db = _temp_db(tmp_path, prices)
    jsonschema.validate(P.build_profile(db, "BTC", days=800), schema)
    jsonschema.validate(
        {"kind": "persistence", "symbol": "NOPE", "error": "AlignError: empty", "caveat": P.CAVEAT},
        schema,
    )


# ---------------- 真实库冒烟（存在才跑） ----------------

_REAL_DB = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "..",
    "..",
    "19-数据访问层",
    "data",
    "dreambuddy_core.db",
)


@pytest.mark.skipif(not os.path.isfile(_REAL_DB), reason="本地真实库不存在")
def test_build_profile_on_real_db():
    prof = P.build_profile(_REAL_DB, "BTC", days=1200)
    assert prof["quality"]["status"] == "good"
    assert prof["sample_n"] >= 1000
    assert prof["metrics"]["hurst"]["confidence"] == "low"  # 1094 < 2000
