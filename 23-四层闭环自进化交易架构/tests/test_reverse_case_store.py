"""RED 测试：ReverseCaseStore — 逆向推导错误案例入库。

P2 §5.2: 错误案例入库，标注 {wrong_dim, root_cause}，
下次类似场景（相同 wrong_dim 模式）降权或避开。
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "dreambuddy_evolution"))
sys.path.insert(0, str(Path(__file__).parent.parent / "dreambuddy_evolution" / "engines"))

from reverse_case_store import ReverseCaseStore


def _make_derive_result(wrong_dims, root_cause="因子计算错误", root_cause_type="factor_error"):
    from reverse_deriver import ReverseDeriveResult
    return ReverseDeriveResult(
        per_dimension_correctness={d: False for d in wrong_dims},
        per_dimension_cs={d: -1.0 for d in wrong_dims},
        wrong_dimensions=list(wrong_dims),
        root_cause=root_cause,
        root_cause_type=root_cause_type,
        confidence=0.8,
        known_gaps=[],
        optimization_action=f"降低错误维度权重: {wrong_dims}",
    )


def test_store_error_case_with_wrong_dim(tmp_path):
    """RED: 错误案例入库后可按 wrong_dim 检索到。"""
    store = ReverseCaseStore(storage_path=str(tmp_path / "reverse_cases.json"))
    derive_result = _make_derive_result(["C1", "C3"])
    snapshot = {"symbol": "BTC", "action": "long", "dimension_predictions": {"C1": "long"}}
    outcome = {"real_direction": "short", "real_outcome": "SL"}

    case_id = store.add_case(derive_result, snapshot, outcome)

    assert case_id is not None
    # 按 wrong_dim 检索
    cases = store.query_by_wrong_dim("C1")
    assert len(cases) == 1
    assert cases[0]["wrong_dimensions"] == ["C1", "C3"]
    assert cases[0]["root_cause_type"] == "factor_error"


def test_store_only_error_cases_not_all_correct(tmp_path):
    """RED: 无错误维度时不入库（正确案例不污染错误案例库）。"""
    store = ReverseCaseStore(storage_path=str(tmp_path / "reverse_cases.json"))
    from reverse_deriver import ReverseDeriveResult
    derive_result = ReverseDeriveResult(
        per_dimension_correctness={"C1": True},
        per_dimension_cs={"C1": 1.0},
        wrong_dimensions=[],
        root_cause="",
        root_cause_type="unknown",
        confidence=1.0,
        known_gaps=[],
        optimization_action="no_adjustment",
    )
    snapshot = {"symbol": "BTC", "action": "long"}
    outcome = {"real_direction": "long", "real_outcome": "TP"}

    case_id = store.add_case(derive_result, snapshot, outcome)

    assert case_id is None  # 无错误维度，不入库
    assert store.count() == 0


def test_query_similar_by_dimension_pattern(tmp_path):
    """RED: 相似案例检索（按 wrong_dim 模式匹配）。"""
    store = ReverseCaseStore(storage_path=str(tmp_path / "reverse_cases.json"))
    # 入库两个 C1 错的案例
    store.add_case(_make_derive_result(["C1"]), {"symbol": "BTC"}, {"real_outcome": "SL"})
    store.add_case(_make_derive_result(["C1", "C2"]), {"symbol": "ETH"}, {"real_outcome": "SL"})
    store.add_case(_make_derive_result(["C3"]), {"symbol": "SOL"}, {"real_outcome": "SL"})

    # 检索含 C1 的案例
    similar = store.query_similar(wrong_dims=["C1"])
    assert len(similar) == 2
    for c in similar:
        assert "C1" in c["wrong_dimensions"]


def test_stats_aggregates_by_dimension(tmp_path):
    """RED: stats() 返回各维度错误频次统计。"""
    store = ReverseCaseStore(storage_path=str(tmp_path / "reverse_cases.json"))
    store.add_case(_make_derive_result(["C1"]), {"symbol": "BTC"}, {"real_outcome": "SL"})
    store.add_case(_make_derive_result(["C1", "C2"]), {"symbol": "ETH"}, {"real_outcome": "SL"})

    stats = store.stats()
    assert stats["total_cases"] == 2
    assert stats["dim_error_counts"]["C1"] == 2
    assert stats["dim_error_counts"]["C2"] == 1


def test_persistence_across_reload(tmp_path):
    """RED: 案例持久化，重新加载后仍可检索。"""
    path = str(tmp_path / "reverse_cases.json")
    store1 = ReverseCaseStore(storage_path=path)
    store1.add_case(_make_derive_result(["C1"]), {"symbol": "BTC"}, {"real_outcome": "SL"})

    store2 = ReverseCaseStore(storage_path=path)
    assert store2.count() == 1
    assert store2.query_by_wrong_dim("C1")[0]["symbol"] == "BTC"
