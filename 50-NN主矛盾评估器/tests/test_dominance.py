# R2-03: Dominance 测试（50 SPEC §4.5，成对支配 + Copeland 矩阵）。
from __future__ import annotations

from core.dominance import resolve_dominance
from core.path_synthesis import Path


def _path(source, confidence, dimension="D3", horizon="hours", intent="trend", weight=0.2):
    return Path(
        path_id=f"ev:{source}:BTC:{dimension}:{horizon}:{intent}",
        source=source,
        symbol="BTC",
        direction="long",
        confidence=confidence,
        expected_return=confidence,
        resistance=1.0 - confidence,
        continuation_score=confidence,
        dimension=dimension,
        horizon=horizon,
        intent=intent,
        metadata={"weight": weight},
    )


def test_unique_leader():
    paths = [
        _path("11-bcrm-tactical", 0.9, weight=0.35),
        _path("11-bdsm", 0.6, weight=0.2),
        _path("11-washout", 0.4, weight=0.15),
    ]
    result = resolve_dominance(paths)
    hours = result["horizons"]["hours"]
    assert hours["leader"] == "ev:11-bcrm-tactical:BTC:D3:hours:trend"
    assert hours["fallback_argmax"] is False
    # Copeland：最强者胜 2 场
    assert hours["copeland"]["ev:11-bcrm-tactical:BTC:D3:hours:trend"] == 2
    # 矩阵可解释：3x3，对角线 0
    assert len(hours["matrix"]) == 3
    assert all(hours["matrix"][i][i] == 0 for i in range(3))
    assert result["overall_leader"] == "ev:11-bcrm-tactical:BTC:D3:hours:trend"


def test_tie_falls_back_to_argmax():
    paths = [
        _path("11-bdsm", 0.5, weight=0.2),
        _path("11-washout", 0.5, weight=0.2),
    ]
    result = resolve_dominance(paths)
    hours = result["horizons"]["hours"]
    assert hours["fallback_argmax"] is True
    assert len(hours["tied_leaders"]) == 2
    # argmax 回退：取力量最大者（此处相等取第一个）
    assert hours["leader"] in hours["tied_leaders"]
    assert result["overall_fallback_argmax"] is True


def test_horizon_isolation():
    paths = [
        _path("11-bdsm", 0.9, horizon="days", weight=0.2),
        _path("11-washout", 0.2, horizon="hours", weight=0.15),
    ]
    result = resolve_dominance(paths)
    # 跨 horizon 不做 dominance：各自独立成组
    assert set(result["horizons"].keys()) == {"days", "hours"}
    days = result["horizons"]["days"]
    hours = result["horizons"]["hours"]
    assert len(days["path_ids"]) == 1
    assert len(hours["path_ids"]) == 1
    # 单元素组：无对手，Copeland=0，leader 即自身（无平局）
    assert days["leader"] == "ev:11-bdsm:BTC:D3:days:trend"
    assert days["fallback_argmax"] is False


def test_empty_input():
    result = resolve_dominance([])
    assert result["horizons"] == {}
    assert result["overall_leader"] is None
    assert result["overall_fallback_argmax"] is False
