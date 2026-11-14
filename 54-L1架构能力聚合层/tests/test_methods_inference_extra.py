# -*- coding: utf-8 -*-
"""H09–H12 与 R03–R18 补充原语的数值/性质验证。

覆盖：自相关、单位根、协整、正态性；日历效应、事件研究、相关 TopK、领先滞后、
状态转移、极值后表现、波动状态→收益、相关性突变、季节性一致率、时空对齐切片。
"""

from __future__ import annotations

import json
import math
import random
from datetime import date, timedelta
from typing import Any, Dict, List, Tuple

import l1agg.methods.inference  # noqa: F401  （触发注册）
from l1agg.methods import get, run

EXTRA_IDS = (
    "H09",
    "H10",
    "H11",
    "H12",
    "R03",
    "R04",
    "R05",
    "R06",
    "R07",
    "R12",
    "R13",
    "R14",
    "R15",
    "R18",
)


# ------------------------------------------------------------------ 数据构造


def _gauss(n: int = 120, seed: int = 5) -> List[float]:
    rnd = random.Random(seed)
    return [rnd.gauss(0.0, 1.0) for _ in range(n)]


def _random_walk(n: int = 120, seed: int = 6) -> List[float]:
    rnd = random.Random(seed)
    out = [0.0]
    for _ in range(n - 1):
        out.append(out[-1] + rnd.gauss(0.0, 1.0))
    return out


def _ar1(n: int = 150, phi: float = 0.8, seed: int = 11) -> List[float]:
    rnd = random.Random(seed)
    out = [0.0]
    for _ in range(n - 1):
        out.append(phi * out[-1] + rnd.gauss(0.0, 1.0))
    return out


def _daily_dates(n: int = 90, start: str = "2024-01-01") -> Tuple[List[str], List[date]]:
    d0 = date.fromisoformat(start)
    days = [d0 + timedelta(days=i) for i in range(n)]
    return [d.isoformat() for d in days], days


def _panel() -> Dict[str, List[float]]:
    return {
        "A": [float(i) for i in range(60)],
        "B": [2.0 * i for i in range(60)],
        "C": [float((i * 37) % 11) for i in range(60)],
        "D": [-float(i) for i in range(60)],
    }


def _event_prices(n: int = 120, events=(15, 25, 35, 45, 55, 65, 75, 85, 95, 105)) -> List[float]:
    prices = [100.0] * n
    for i in events:
        prices[i + 1] = 102.0  # 事件次日 +2% 冲击
    return prices


def _monthly_dates(years: int = 3) -> List[str]:
    return [
        f"{2022 + y}-{m:02d}-{d:02d}"
        for y in range(years)
        for m in range(1, 13)
        for d in (3, 10, 15, 20, 25)
    ]


def _r18_panel() -> Dict[str, Any]:
    return {
        "A": [("binance", 1700000000 + i * 86400, 100.0 + i) for i in range(40)],
        # 隔日采样 + 跨源同名日（okx 的 999.0 应被去重丢弃）
        "B": [("binance", 1700000000 + i * 86400, 50.0 + i) for i in range(0, 60, 2)]
        + [("okx", 1700000000 + 4 * 86400, 999.0)],
    }


CASES: Dict[str, Tuple[Any, Dict[str, Any]]] = {
    "H09": (_ar1(), {}),
    "H10": (_random_walk(), {}),
    "H11": (
        {
            "x": _random_walk(),
            "y": [2.0 * v + 0.1 * _gauss(120, seed=8)[i] for i, v in enumerate(_random_walk())],
        },
        {},
    ),
    "H12": (_gauss(), {}),
    "R03": (None, {}),  # 见 _case()
    "R04": ({"prices": _event_prices(), "events": list(range(15, 110, 10))}, {"pre": 2, "post": 3}),
    "R05": ({"series": _panel()}, {"k": 3}),
    "R06": (None, {"max_lag": 5}),
    "R07": (["a", "a", "b", "a", "a", "b"] * 6, {}),
    "R12": ([100.0 * (1.001**i) for i in range(100)], {"horizon": 5}),
    "R13": (
        {"vol": [float(i) for i in range(260)], "target": [0.001 * i for i in range(260)]},
        {"k": 5},
    ),
    "R14": (None, {"window": 20}),
    "R15": ({"returns": [0.01] * len(_monthly_dates()), "dates": _monthly_dates()}, {}),
    "R18": ({"series": _r18_panel()}, {}),
}


def _case(method_id: str) -> Tuple[Any, Dict[str, Any]]:
    """补齐需要构造随机序列的用例。"""
    if method_id == "R03":
        dates, days = _daily_dates(90)
        rets = [0.02 if d.weekday() >= 5 else -0.005 for d in days]
        return {"returns": rets, "dates": dates}, {"by": "weekday"}
    if method_id == "R06":
        x = [math.sin(i * 0.7) for i in range(80)]
        return {"x": x, "y": [0.0] + x[:-1]}, {"max_lag": 5}
    if method_id == "R14":
        x = _gauss(160, seed=3)
        y = _gauss(160, seed=4)[:140] + x[140:]  # 后 20 期相关性跳到 +1
        return {"x": x, "y": y}, {"window": 20, "threshold": 2.0}
    return CASES[method_id]


def _result(method_id: str) -> Dict[str, Any]:
    data, params = _case(method_id)
    out = run(method_id, data, **params)
    assert out["gate"] == "ok", (method_id, out["gate"], out["sample_n"], out["min_n"])
    return out["result"]


def _empty_data(method_id: str) -> Any:
    kind = get(method_id).input_kind
    if kind == "panel":
        return {"series": {}}
    if kind == "pairs":
        return {"x": [], "y": []}
    return []


# ------------------------------------------------------------------ H 组


def test_h09_ljung_box_detects_autocorrelation() -> None:
    ar = _result("H09")
    assert ar["p"] < 0.05 and ar["is_significant"] is True
    assert ar["q"] > 0 and ar["df"] == 10 and ar["n"] == 150

    noise = run("H09", _gauss(200, seed=21))["result"]
    assert noise["p"] > 0.05 and noise["is_significant"] is False


def test_h10_adf_separates_walk_and_noise() -> None:
    walk = _result("H10")
    assert walk["p"] > 0.05 and walk["stationary"] is False
    assert walk["critical"]["1%"] < walk["critical"]["5%"] < 0
    assert walk["stat"] > walk["critical"]["5%"]  # 未越过 5% 临界值 → 不能拒绝单位根

    noise = run("H10", _gauss(120, seed=9))["result"]
    assert noise["p"] < 0.05 and noise["stationary"] is True
    assert noise["stat"] < noise["critical"]["5%"]


def test_h11_cointegration_detects_shared_trend() -> None:
    out = _result("H11")
    assert out["p"] < 0.05 and out["cointegrated"] is True
    assert out["stat"] < out["critical"]["5%"].__float__()

    # 两条独立随机游走不应被判为协整
    rnd = random.Random(31)
    indep_x = [0.0]
    indep_y = [0.0]
    for _ in range(119):
        indep_x.append(indep_x[-1] + rnd.gauss(0, 1))
        indep_y.append(indep_y[-1] + rnd.gauss(0, 1))
    indep = run("H11", {"x": indep_x, "y": indep_y})["result"]
    assert indep["p"] > 0.05 and indep["cointegrated"] is False


def test_h12_normality_separates_normal_and_outliers() -> None:
    normal = _result("H12")
    assert normal["p"] > 0.05 and normal["normal"] is True

    skewed = run("H12", _gauss(100, seed=13) + [50.0] * 5)["result"]
    assert skewed["p"] < 0.05 and skewed["normal"] is False
    assert skewed["stat"] > normal["stat"]


# ------------------------------------------------------------------ R 组


def test_r03_calendar_table_marks_best_and_worst() -> None:
    out = _result("R03")
    assert out["by"] == "weekday"
    assert out["best"] == 5  # 周六均值最高（周末 +2%）
    assert out["worst"] == 0  # 周一均值最低
    assert sum(out["counts"].values()) == out["n"] == 90
    table = {row["key"]: row for row in out["table"]}
    assert table[5]["mean"] > table[0]["mean"]
    assert table[5]["win_rate"] == 1.0 and table[0]["win_rate"] == 0.0


def test_r04_event_window_reports_ar_and_car() -> None:
    out = _result("R04")
    assert out["offsets"] == [-2, -1, 0, 1, 2, 3]
    assert len(out["ar"]) == 6
    assert out["n"] == 10 and out["events"] == 10
    assert out["ar"][out["offsets"].index(1)] > 0.01  # 事件次日 +2% 冲击
    assert out["car"] > 0


def test_r05_topk_keeps_sign_and_orders_by_abs_rho() -> None:
    out = _result("R05")
    pairs = {(p["a"], p["b"]): p["rho"] for p in out["pairs"]}
    assert pairs[("A", "B")] == 1.0
    assert pairs[("A", "D")] == -1.0  # 反向序列符号为负
    assert abs(out["rho"]) == 1.0
    assert [abs(p["rho"]) for p in out["pairs"]] == sorted(
        (abs(p["rho"]) for p in out["pairs"]), reverse=True
    )
    assert len(out["top"]) == 3


def test_r06_lead_lag_sign_convention() -> None:
    out = _result("R06")
    assert out["best_lag"] == 1  # y[t]=x[t-1] → x 领先 1 期
    assert out["ccf"][out["lags"].index(1)] == 1.0
    assert out["best_rho"] == 1.0
    assert out["n"] == 80
    assert "领先" in out["phrase"]


def test_r07_transition_rows_are_stochastic() -> None:
    out = _result("R07")
    assert out["states"] == ["a", "b"]
    for row in out["matrix"]:
        assert abs(sum(v for v in row if v is not None) - 1.0) < 1e-6
    assert out["next_dist"] == {"a": 1.0, "b": 0.0}  # 最近状态 b 之后只出现过 a
    assert out["next_state"] == "a"
    assert out["n"] == 36


def test_r12_new_high_forward_distribution() -> None:
    out = _result("R12")
    assert out["events"] == 99  # 单调上涨 → 每期都是新高
    assert out["n"] == 99 - 5
    assert out["fwd_dist"]["win_rate"] == 1.0
    assert out["fwd_dist"]["mean"] > 0
    assert out["horizon"] == 5


def test_r13_vol_buckets_monotone_and_spread() -> None:
    out = _result("R13")
    assert out["k"] == 5 and len(out["buckets"]) == 5
    assert sum(b["n"] for b in out["buckets"]) == out["n"] == 260
    assert out["buckets"][0]["mean"] < out["buckets"][-1]["mean"]
    assert out["spread"] > 0


def test_r14_corr_jump_flags_anomaly() -> None:
    out = _result("R14")
    assert out["window"] == 20
    assert out["current"] > 0.99  # 末窗两序列完全同向
    assert out["z"] > 2.0
    assert out["is_anomaly"] is True
    assert abs(out["z"] - (out["current"] - out["history_avg"]) / out["history_std"]) < 0.01


def test_r15_consistency_all_up_months() -> None:
    out = _result("R15")
    assert out["years"] == 3
    assert out["consistency"] == [1.0] * 12
    assert len(out["table"]) == 12


def test_r18_dedupe_ffill_and_stale_cap() -> None:
    out = _result("R18")
    assert out["align_method"] == "daily_last+ffill"
    assert out["timezone"] == "UTC" and out["max_stale_days"] == 3
    rows = {row["asset"]: row for row in out["window_rows"]}
    assert out["assets"] == ["A", "B"]
    # A：40 个 UTC 日收盘 → 0..39 连续，末值 139
    assert rows["A"]["n_obs"] == 40 and rows["A"]["end_value"] == 139.0
    assert abs(rows["A"]["ret"] - 0.39) < 1e-9
    # B：跨源 okx 同日被去重（末值仍为 binance 序列的 108），且隔日采样产生 stale 填充
    assert rows["B"]["end_value"] == 108.0
    assert rows["B"]["n_obs"] == 30
    assert rows["B"]["stale_ratio"] > 0.4
    assert all(row["end_value"] != 999.0 for row in out["window_rows"])
    assert out["window"] == "2023-11-14~2024-01-11" and out["n"] == 59


# ------------------------------------------------------------------ 契约/确定性/门禁


def test_output_schema_matches_registry() -> None:
    for method_id in EXTRA_IDS:
        result = _result(method_id)
        spec = get(method_id)
        assert spec.implemented is True, method_id
        assert set(result) == set(spec.output_schema), (
            method_id,
            set(spec.output_schema) ^ set(result),
        )
        assert result["n"] >= 0


def test_determinism_h_group() -> None:
    for method_id in ("H09", "H10", "H11", "H12"):
        a = json.dumps(_result(method_id), sort_keys=True, ensure_ascii=False, default=str)
        b = json.dumps(_result(method_id), sort_keys=True, ensure_ascii=False, default=str)
        assert a == b, method_id


def test_determinism_r_group() -> None:
    for method_id in ("R03", "R05", "R06", "R07", "R12", "R13", "R14", "R15", "R18"):
        a = json.dumps(_result(method_id), sort_keys=True, ensure_ascii=False, default=str)
        b = json.dumps(_result(method_id), sort_keys=True, ensure_ascii=False, default=str)
        assert a == b, method_id


def test_empty_input_gate_returns_insufficient_samples() -> None:
    for method_id in EXTRA_IDS:
        out = run(method_id, _empty_data(method_id))
        assert out["gate"] == "insufficient_samples", method_id
        assert out["result"] is None and out["sample_n"] == 0
