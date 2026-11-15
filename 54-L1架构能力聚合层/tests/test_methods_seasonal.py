# -*- coding: utf-8 -*-
"""C 组（季节性与日历效应）测试：C01–C18。"""

import datetime
import json
import os
import sys

import pytest

_MODULE_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
if _MODULE_ROOT not in sys.path:
    sys.path.insert(0, _MODULE_ROOT)

from l1agg.methods import get, run  # noqa: E402


def _daily(n=400, start=datetime.date(2024, 1, 1), weekend=0.002, weekday=0.001):
    dates, rets = [], []
    for i in range(n):
        d = start + datetime.timedelta(days=i)
        dates.append(d.strftime("%Y-%m-%d"))
        rets.append(weekend if d.weekday() >= 5 else weekday)
    return {"returns": rets, "dates": dates}


def test_c_batch_registered():
    ids = [f"C{i:02d}" for i in range(1, 19)]
    for mid in ids:
        spec = get(mid)
        assert spec.group == "C", mid
        assert spec.implemented is True, mid


def _business_days_case(holiday_idx=(40, 90, 140, 190), n_days=300):
    """工作日序列 + 指定节假日缺失；节前收益 0.01，其余 0.001。"""
    days = []
    cursor = datetime.date(2024, 1, 1)
    while len(days) < n_days:
        if cursor.weekday() < 5:
            days.append(cursor)
        cursor += datetime.timedelta(days=1)
    holidays = set(holiday_idx)
    dates, rets = [], []
    for i, day in enumerate(days):
        if i in holidays:
            continue
        dates.append(day.isoformat())
        rets.append(0.01 if (i + 1) in holidays else 0.001)
    return {"returns": rets, "dates": dates}


def test_c11_derives_holidays_from_date_axis():
    out = run("C11", _business_days_case())["result"]
    assert out["calendar"] == "derived"
    assert out["n_holidays"] == 4
    assert out["n_pre"] == 4
    assert out["pre_mean"] == pytest.approx(0.01)
    assert out["base_mean"] == pytest.approx(0.001)
    assert out["diff"] == pytest.approx(0.009)


def test_c11_explicit_holidays_and_long_gap_guard():
    case = _business_days_case()
    dates = case["dates"]
    last = datetime.date.fromisoformat(dates[-1])
    holiday = last + datetime.timedelta(days=1)
    while holiday.weekday() >= 5:
        holiday += datetime.timedelta(days=1)
    out = run("C11", case, holidays=[holiday.isoformat()])["result"]
    assert out["calendar"] == "explicit"
    assert out["n_holidays"] == 1
    # 连续缺失 >10 个工作日视为数据缺口，不当节假日
    brutal = _business_days_case(holiday_idx=tuple(range(50, 70)))
    guarded = run("C11", brutal)["result"]
    assert guarded["n_holidays"] == 0
    assert guarded["excluded_gaps"] == 20


def test_c11_no_gap_calendar_is_empty_effect():
    out = run("C11", _daily(400))["result"]
    assert out["n_holidays"] == 0
    assert out["pre_mean"] is None
    assert out["diff"] is None


def test_c01_month_effect_values():
    out = run("C01", _daily())["result"]
    for row in out["table"]:
        assert 0.001 <= row["mean"] <= 0.002
        assert row["win_rate"] == 1.0
    assert sum(row["n"] for row in out["table"]) == 400


def test_c02_c03_alignment():
    data = _daily()
    c02 = {r["month"]: r for r in run("C02", data)["result"]["table"]}
    c03 = {r["month"]: r for r in run("C03", data)["result"]["table"]}
    for month in c03:
        assert c02[month]["n"] == c03[month]["n"]
        assert c03[month]["up"] == c03[month]["n"]
        assert c03[month]["down"] == 0


def test_c04_ranking_sorted():
    ranking = run("C04", _daily())["result"]["ranking"]
    means = [row["mean"] for row in ranking]
    assert means == sorted(means, reverse=True)
    assert [row["rank"] for row in ranking] == list(range(1, len(ranking) + 1))


def test_c05_weekday_weekend_effect():
    out = run("C05", _daily())["result"]
    table = {row["weekday"]: row for row in out["table"]}
    assert table[5]["mean"] == pytest.approx(0.002)
    assert table[0]["mean"] == pytest.approx(0.001)
    assert table[5]["label"] == "Sat"
    assert out["n"] == 400


def test_c06_hour_not_available_on_daily():
    out = run("C06", _daily())["result"]
    assert out["hour_available"] is False


def test_c07_day_of_month_counts():
    out = run("C07", _daily())["result"]
    assert out["table"][0]["day"] == 1
    assert all(row["day"] <= 31 for row in out["table"])


def test_c08_month_edges():
    out = run("C08", _daily())["result"]
    # 月初/月末都含工作日与周末，均值应介于 weekday 与 weekend 之间
    assert 0.001 <= out["first_mean"] <= 0.002
    assert 0.001 <= out["last_mean"] <= 0.002
    assert out["n"] == 400


def test_c09_quarters():
    table = run("C09", _daily())["result"]["table"]
    assert [row["quarter"] for row in table] == [1, 2, 3, 4]


def test_c10_year_position():
    out = run("C10", _daily())["result"]
    assert out["doy"] == out["points"][-1]["doy"]
    assert 0 < out["percentile"] <= 1


def test_c12_half_year_both_sides():
    out = run("C12", _daily())["result"]
    assert out["h1_n"] > 0 and out["h2_n"] > 0
    assert out["diff"] == pytest.approx(0.0, abs=1e-4)


def test_c13_strength_zero_when_no_seasonality():
    # 全周同值 → 总方差为 0，季节强度无定义（null 而非伪造 0）
    flat = _daily(400, weekend=0.001, weekday=0.001)
    out = run("C13", flat)["result"]
    assert out["strength"] is None


def test_c14_consistency_full_when_all_up():
    table = run("C14", _daily())["result"]["table"]
    assert table and all(row["consistency"] == 1.0 for row in table)


def test_c15_transition_matrix_totals():
    out = run("C15", _daily())["result"]
    assert out["labels"] == ["up", "down"]
    assert out["transitions"] == out["months"] - 1
    assert sum(sum(row) for row in out["matrix"]) == out["transitions"]


def test_c16_same_day_percentile():
    out = run("C16", _daily())["result"]
    assert out["month"] == 2 and out["day"] == 3
    assert out["hist_n"] >= 1


def test_c17_month_to_date():
    out = run("C17", _daily())["result"]
    assert out["month"] == 2
    assert out["n_years"] >= 1
    assert out["current"] is not None


def test_c18_cycle_alignment():
    data = _daily()
    out = run("C18", {"a": data["returns"], "b": data["returns"], "dates": data["dates"]})["result"]
    assert out["ratio"] == 1.0
    assert out["months"] >= 12


def test_c18_requires_two_series():
    with pytest.raises(ValueError):
        run("C18", {"a": [0.01] * 100, "dates": _daily(100)["dates"]})


def test_c_group_requires_dates():
    # 缺日期轴属于输入契约违规，方法层直接抛错；能力层会收敛为 ok=false
    with pytest.raises(ValueError):
        run("C01", [0.01] * 100)
    with pytest.raises(ValueError):
        run("C05", [0.01] * 100)


def test_c_group_deterministic():
    data = _daily()
    for mid in ("C01", "C05", "C07", "C13", "C14", "C15"):
        a = json.dumps(run(mid, data)["result"], sort_keys=True)
        b = json.dumps(run(mid, data)["result"], sort_keys=True)
        assert a == b, mid
