"""事件 reaction 计算 + 行情反查回填测试 — SPEC-D1 §2.4 / §3.2。

reaction = 事件窗口收益（event study 简化版，日粒度只用 T+24h/T+7d）。
行情反查 = 3σ 异常波动检测（复用 48 E1 anomaly_probe 思路），attribution=weak。
"""

from data_center.processing.event_reaction import (
    compute_reaction,
    detect_kline_anomalies,
)

# 10 天日线：(ts=day*N, close)
BASE_TS = 1700000000
DAY = 86400


def _series(closes):
    return [(BASE_TS + i * DAY, c) for i, c in enumerate(closes)]


def test_reaction_basic():
    """T+24h / T+7d 收益计算。"""
    prices = _series([100, 100, 110, 100, 100, 100, 100, 100, 120, 100])
    trigger = BASE_TS + 1 * DAY  # 第 1 天收盘 100
    r = compute_reaction(prices, trigger)
    assert abs(r["T+24h"] - 0.10) < 1e-6  # 110/100 - 1
    assert abs(r["T+7d"] - 0.20) < 1e-6  # 120/100 - 1


def test_reaction_window_truncated():
    """数据不足 7 天 → 该窗口缺席（不硬填）。"""
    prices = _series([100, 105])
    r = compute_reaction(prices, BASE_TS)
    assert abs(r["T+24h"] - 0.05) < 1e-6
    assert "T+7d" not in r


def test_reaction_failopen():
    """FAIL-OPEN：空序列/坏输入 → 空 dict。"""
    assert compute_reaction([], BASE_TS) == {}
    assert compute_reaction(None, BASE_TS) == {}
    assert compute_reaction(_series([100]), BASE_TS + 99 * DAY) == {}


def test_anomaly_detection_3sigma():
    """3σ 突刺检测：平稳序列中一个暴涨日被标出。"""
    closes = [100, 100.2, 99.8, 100.1, 99.9, 100.0, 100.1, 99.9, 130.0, 100.2]
    anomalies = detect_kline_anomalies(_series(closes), sigma=3.0)
    # 暴涨日（+30%）必被标出；次日回落（-23%）同为真实异常不限制
    ts_list = [a["ts"] for a in anomalies]
    assert BASE_TS + 8 * DAY in ts_list
    spike = anomalies[ts_list.index(BASE_TS + 8 * DAY)]
    assert spike["direction"] == "up"
    assert spike["attribution"] == "weak"


def test_anomaly_flat_series_none():
    """零波动序列 → 无异常，且不抛（除零护栏）。"""
    assert detect_kline_anomalies(_series([100.0] * 10)) == []


def test_anomaly_failopen():
    assert detect_kline_anomalies([]) == []
    assert detect_kline_anomalies(None) == []
    assert detect_kline_anomalies(_series([100, 101])) == []  # 太短
