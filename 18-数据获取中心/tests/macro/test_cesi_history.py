"""CESI 历史滚动窗口测试 — 维护每个宏观指标最近 12 次 surprise 值。

SPEC-事件驱动策略P0盲区修复 §3.1.3 — CESI 标准化：Surprise=(Actual-Forecast)/σ_history
σ 维护：滚动窗口最近 12 次发布的 surprise 标准差，至少 6 次才能算 σ。

存储：JSON 文件（轻量级，无需 SQLite），格式 {indicator: [surprise1, surprise2, ...]}
"""
from data_center.collectors.macro.cesi_history import (
    get_surprise_history,
    append_surprise,
    compute_cesi,
    WINDOW_SIZE,
    MIN_HISTORY_FOR_SIGMA,
)


def test_window_size_constant():
    """窗口大小常量 = 12。"""
    assert WINDOW_SIZE == 12


def test_min_history_constant():
    """σ 计算最小历史 = 6。"""
    assert MIN_HISTORY_FOR_SIGMA == 6


def test_get_surprise_history_empty_for_new_indicator(tmp_path):
    """新指标历史为空。"""
    p = tmp_path / "cesi.json"
    assert get_surprise_history("cpi", path=p) == []


def test_append_and_get_surprise(tmp_path):
    """append_surprise 后 get_surprise_history 返回追加的值。"""
    p = tmp_path / "cesi.json"
    append_surprise("cpi", 0.2, path=p)
    append_surprise("cpi", -0.1, path=p)
    assert get_surprise_history("cpi", path=p) == [0.2, -0.1]


def test_window_size_fifo(tmp_path):
    """追加 15 次后只保留最近 12 次（FIFO）。"""
    p = tmp_path / "cesi.json"
    for i in range(15):
        append_surprise("cpi", float(i), path=p)
    history = get_surprise_history("cpi", path=p)
    assert len(history) == 12
    assert history == [3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0, 11.0, 12.0, 13.0, 14.0]


def test_compute_cesi_with_sufficient_history():
    """6+ 次历史时 CESI = (actual - forecast) / σ。"""
    history = [0.1, -0.1, 0.2, -0.2, 0.15, -0.15]  # 6 次
    cesi = compute_cesi(3.5, 3.0, history)
    assert cesi is not None
    # σ = std([0.1,-0.1,0.2,-0.2,0.15,-0.15])
    import numpy as np
    expected_sigma = float(np.std(history))
    expected_cesi = round(0.5 / expected_sigma, 3)
    assert cesi == expected_cesi


def test_compute_cesi_none_when_insufficient_history():
    """少于 6 次历史时返回 None。"""
    history = [0.1, -0.1, 0.2]  # 3 次
    assert compute_cesi(3.5, 3.0, history) is None


def test_compute_cesi_none_when_zero_sigma():
    """σ=0 时返回 None（避免除零）。"""
    history = [0.1, 0.1, 0.1, 0.1, 0.1, 0.1]  # 6 次相同值
    assert compute_cesi(3.5, 3.0, history) is None


def test_persistence_across_calls(tmp_path):
    """跨调用持久化（JSON 文件存储）。"""
    p = tmp_path / "cesi.json"
    append_surprise("cpi", 0.3, path=p)
    assert get_surprise_history("cpi", path=p) == [0.3]
    append_surprise("cpi", -0.2, path=p)
    assert get_surprise_history("cpi", path=p) == [0.3, -0.2]


def test_multiple_indicators_isolated(tmp_path):
    """不同指标历史隔离。"""
    p = tmp_path / "cesi.json"
    append_surprise("cpi", 0.2, path=p)
    append_surprise("nfp", 17.0, path=p)
    assert get_surprise_history("cpi", path=p) == [0.2]
    assert get_surprise_history("nfp", path=p) == [17.0]


def test_fail_open_when_file_corrupted(tmp_path):
    """文件损坏时 FAIL-OPEN 返回空列表。"""
    p = tmp_path / "cesi.json"
    p.write_text("not a valid json {{{", encoding="utf-8")
    assert get_surprise_history("cpi", path=p) == []
    # 追加时应重建文件
    append_surprise("cpi", 0.5, path=p)
    assert get_surprise_history("cpi", path=p) == [0.5]
