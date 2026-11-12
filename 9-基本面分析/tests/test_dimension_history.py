"""SPEC-9DOMAIN-HISTORY-CONTEXT-v1.1 §8.1 — DimensionHistory 契约与统计口径。

覆盖：空序列、各统计窗口边界、Spearman 趋势、2 日确认 regime、median-gap 覆盖度、
      幂等 upsert、fail-closed 拒写、value_scale 映射、velocity_label 五档。
"""

from __future__ import annotations

import json
import os
import sys
from datetime import date, timedelta

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engines import dimension_history as dh  # noqa: E402

FLOW = "flow"


def _obs(day: date, value: float, module: str = FLOW, direction: str | None = None, **kw) -> dict:
    if direction is None:
        direction = "up" if value > 0.3 else "down" if value < -0.3 else "neutral"
    obs = {
        "date": day.isoformat(),
        "module": module,
        "value": value,
        "value_scale": dh.VALUE_SCALE.get(module, "score_neg1_pos1"),
        "direction": direction,
        "direction_score": value,
        "velocity": 0.0,
        "acceleration": 0.0,
        "velocity_label": "",
        "confidence": 0.5,
        "data_points": 1,
        "written_at": "2026-11-11T00:00:00Z",
        "schema_version": 1,
    }
    obs.update(kw)
    return obs


def _series(
    n: int, values: list[float] | None = None, start: date = date(2026, 1, 1)
) -> list[dict]:
    vals = values if values is not None else [((i % 20) - 10) / 20.0 for i in range(n)]
    return [_obs(start + timedelta(days=i), vals[i]) for i in range(n)]


# 1. 空序列
def test_empty_series_yields_none_source_and_null_stats():
    r = dh.compute_dimension_history([], FLOW)
    assert r["source"] == "none"
    assert r["availability"] == "none"
    assert r["lookback_days"] == 0
    assert set(r["stats"]) == {
        "pct_rank_1y",
        "pct_rank_3y",
        "extreme_days",
        "mean_revert_z",
        "trend_20d",
        "regime_switch_30d",
    }
    assert all(v is None for v in r["stats"].values())
    assert r["notes"]


# 2. trend_20d 窗口边界
def test_trend_20d_window_boundary():
    assert dh.compute_dimension_history(_series(1), FLOW)["stats"]["trend_20d"] is None
    assert dh.compute_dimension_history(_series(19), FLOW)["stats"]["trend_20d"] is None
    assert dh.compute_dimension_history(_series(20), FLOW)["stats"]["trend_20d"] is not None


# 3. trend_20d 用 Spearman 秩相关
def test_trend_20d_is_spearman():
    inc = dh.compute_dimension_history(_series(20, [i / 20.0 for i in range(20)]), FLOW)
    assert inc["stats"]["trend_20d"] == pytest.approx(1.0)

    dec = dh.compute_dimension_history(_series(20, [1 - i / 20.0 for i in range(20)]), FLOW)
    assert dec["stats"]["trend_20d"] == pytest.approx(-1.0)

    flat = dh.compute_dimension_history(_series(20, [0.5] * 20), FLOW)
    assert flat["stats"]["trend_20d"] == pytest.approx(0.0)

    # 一个并列对（第 5、6 位同为 5.0）→ 1 - 6*0.5/(20*399)
    tied = [1, 2, 3, 4, 5, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19]
    r = dh.compute_dimension_history(_series(20, [float(v) for v in tied]), FLOW)
    assert r["stats"]["trend_20d"] == pytest.approx(1 - 3 / 7980, abs=1e-6)


# 4. mean_revert_z / extreme_days 窗口边界
def test_z_stats_window_boundary():
    r59 = dh.compute_dimension_history(_series(59), FLOW)["stats"]
    assert r59["mean_revert_z"] is None
    assert r59["extreme_days"] is None

    r60 = dh.compute_dimension_history(_series(60), FLOW)["stats"]
    assert r60["mean_revert_z"] is not None
    assert r60["extreme_days"] is not None


# 5. std60 == 0 → null + note
def test_zero_variance_z_is_null_with_note():
    r = dh.compute_dimension_history(_series(60, [0.5] * 60), FLOW)
    assert r["stats"]["mean_revert_z"] is None
    assert any("zero_variance" in n for n in r["notes"])


# 6. winsor clamp
def test_mean_revert_z_winsor_clamped():
    vals = [0.0] * 59 + [100.0]
    r = dh.compute_dimension_history(_series(60, vals), FLOW)
    assert r["stats"]["mean_revert_z"] == pytest.approx(3.0)
    assert any("winsor_clamped" in n for n in r["notes"])


# 7. pct_rank_1y 边界 + ties 用 average rank
def test_pct_rank_1y_boundary_and_ties():
    assert dh.compute_dimension_history(_series(249), FLOW)["stats"]["pct_rank_1y"] is None
    assert dh.compute_dimension_history(_series(250), FLOW)["stats"]["pct_rank_1y"] is not None

    # 250 个观测：最后 3 个同为最大值 → 0-based 秩 247/248/249 → average 248 → 248/249
    vals = [float(i) for i in range(247)] + [999.0, 999.0, 999.0]
    r = dh.compute_dimension_history(_series(250, vals), FLOW)
    assert r["stats"]["pct_rank_1y"] == pytest.approx(248 / 249)


# 8. pct_rank_3y 边界
def test_pct_rank_3y_boundary():
    assert dh.compute_dimension_history(_series(749), FLOW)["stats"]["pct_rank_3y"] is None
    assert dh.compute_dimension_history(_series(750), FLOW)["stats"]["pct_rank_3y"] is not None


# 9. regime_switch_30d：2 日确认
def test_regime_switch_requires_two_day_confirmation():
    seq = ["up"] * 10 + ["down"] * 10 + ["neutral"] * 11
    series = [
        _obs(date(2026, 1, 1) + timedelta(days=i), 0.0, direction=d) for i, d in enumerate(seq)
    ]
    assert dh.compute_dimension_history(series, FLOW)["stats"]["regime_switch_30d"] == 2

    jitter = ["up", "down"] * 16  # 单日抖动
    series_j = [
        _obs(date(2026, 1, 1) + timedelta(days=i), 0.0, direction=d) for i, d in enumerate(jitter)
    ]
    assert dh.compute_dimension_history(series_j, FLOW)["stats"]["regime_switch_30d"] == 0


# 10. as_of 前视截断
def test_as_of_truncates_future_observations():
    series = _series(40)
    cut = series[29]["date"]
    r = dh.compute_dimension_history(series, FLOW, as_of=cut)
    assert r["as_of"] == cut
    assert r["lookback_days"] == 30
    assert r["coverage"]["last_day"] == cut


# 11. append_observation 幂等
def test_append_is_idempotent_by_module_and_date(tmp_path):
    day = date(2026, 11, 11)
    first = _obs(day, 0.2, written_at="2026-11-11T00:00:00Z")
    newer = _obs(day, 0.7, written_at="2026-11-11T23:00:00Z")

    assert dh.append_observation(FLOW, first, base_dir=tmp_path) is True
    assert dh.append_observation(FLOW, newer, base_dir=tmp_path) is True

    path = tmp_path / "dimension_history" / f"{FLOW}.jsonl"
    lines = [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]
    assert len(lines) == 1
    assert lines[0]["value"] == pytest.approx(0.7)


# 12. 缺 date → 拒写（fail-closed）
def test_append_without_date_is_rejected(tmp_path):
    bad = _obs(date(2026, 11, 11), 0.2)
    bad.pop("date")
    assert dh.append_observation(FLOW, bad, base_dir=tmp_path) is False
    assert not (tmp_path / "dimension_history" / f"{FLOW}.jsonl").exists()


# 13. coverage 用 median-gap 推算
def test_coverage_uses_median_gap_not_calendar_days(tmp_path):
    start = date(2026, 1, 1)
    days = [start + timedelta(days=i) for i in range(8)] + [start + timedelta(days=11)]
    for d in days:
        assert dh.append_observation(FLOW, _obs(d, 0.1), base_dir=tmp_path) is True

    r = dh.get_dimension_history(FLOW, base_dir=tmp_path)
    cov = r["coverage"]
    assert cov["observed_days"] == 9
    assert cov["expected_days"] == 12  # span 11 / median_gap 1 + 1
    assert cov["missing_days"] == 3


# 14. max_gap_days + stale note
def test_max_gap_and_stale_note(tmp_path):
    start = date(2026, 1, 1)
    for i in range(5):
        assert dh.append_observation(FLOW, _obs(start + timedelta(days=i), 0.1), base_dir=tmp_path)
    assert dh.append_observation(FLOW, _obs(start + timedelta(days=15), 0.1), base_dir=tmp_path)

    r = dh.get_dimension_history(FLOW, base_dir=tmp_path)
    assert r["coverage"]["max_gap_days"] == 11
    assert any("stale_series" in n for n in r["notes"])


# 15. value_scale 映射
def test_value_scale_mapping():
    assert dh.VALUE_SCALE["flow"] == "score_neg1_pos1"
    assert dh.VALUE_SCALE["macro"] == "score_neg1_pos1"
    assert dh.VALUE_SCALE["sentiment"] == "index_0_100"
    assert dh.VALUE_SCALE["valuation"] == "ratio"
    r = dh.compute_dimension_history(_series(5), "sentiment")
    assert r["value_scale"] == "index_0_100"


# 16. velocity_label 五档
def test_velocity_label_five_buckets():
    assert dh.velocity_label_of(0.06) == "加速流入"
    assert dh.velocity_label_of(0.02) == "温和流入"
    assert dh.velocity_label_of(0.0) == "持平"
    assert dh.velocity_label_of(-0.02) == "温和流出"
    assert dh.velocity_label_of(-0.06) == "加速流出"
    assert dh.velocity_label_of(0.06, value_scale="ratio") == ""


# 17. 批量回填与单条写入共用幂等口径
def test_append_observations_bulk_is_idempotent(tmp_path):
    first = _obs(date(2026, 11, 10), 0.1)
    second = _obs(date(2026, 11, 11), 0.2)
    assert dh.append_observations(FLOW, [first, second], base_dir=tmp_path) == 2

    newer = _obs(date(2026, 11, 11), 0.8, written_at="2026-11-12T00:00:00Z")
    invalid = _obs(date(2026, 11, 12), 0.3)
    invalid.pop("date")
    assert dh.append_observations(FLOW, [newer, invalid], base_dir=tmp_path) == 1

    rows = dh.load_series(FLOW, base_dir=tmp_path)
    assert len(rows) == 2
    assert rows[-1]["value"] == pytest.approx(0.8)


# 18. 默认目录严格落在 storage/dimension_history，不多拼一层
def test_default_history_dir_matches_storage_contract(tmp_path, monkeypatch):
    monkeypatch.setattr(dh, "HISTORY_DIR", tmp_path / "dimension_history")
    assert dh.append_observation(FLOW, _obs(date(2026, 11, 11), 0.2)) is True
    assert (tmp_path / "dimension_history" / f"{FLOW}.jsonl").is_file()
    assert not (tmp_path / "dimension_history" / "dimension_history").exists()
