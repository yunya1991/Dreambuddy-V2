"""RED 测试：ReverseCognitiveBridge — 逆向推导认知记忆集成。

P3 §6: 逆向推导输出 ReverseDeriveResult 复用 33-REA Evidence 结构，
统一入库认知记忆系统。
"""
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "dreambuddy_evolution"))
sys.path.insert(0, str(Path(__file__).parent.parent / "dreambuddy_evolution" / "engines"))

from reverse_deriver import ReverseDeriveResult
from reverse_cognitive_bridge import ReverseCognitiveBridge


def _make_derive_result():
    return ReverseDeriveResult(
        per_dimension_correctness={"C1": False, "C2": True},
        per_dimension_cs={"C1": -1.0, "C2": 1.0},
        wrong_dimensions=["C1"],
        root_cause="C1资金流因子计算错误",
        root_cause_type="factor_error",
        confidence=0.75,
        known_gaps=["因子值可能有延迟"],
        optimization_action="审计C1因子",
    )


def test_to_evidence_has_rea_structure():
    """RED: to_evidence 输出符合 33-REA Evidence 结构。"""
    bridge = ReverseCognitiveBridge()
    derive_result = _make_derive_result()
    snapshot = {"symbol": "BTC", "cluster_id": "C001"}
    outcome = {"real_outcome": "SL"}

    evidence = bridge.to_evidence(derive_result, snapshot, outcome)

    assert evidence["level"] == "derivation"
    assert "provenance" in evidence
    assert evidence["confidence"] == 0.75
    assert evidence["known_gaps"] == ["因子值可能有延迟"]
    assert evidence["root_cause"] == "C1资金流因子计算错误"
    assert evidence["wrong_dimensions"] == ["C1"]


def test_to_evidence_provenance_contains_ids():
    """RED: provenance 含 snapshot_id / outcome_id / dimensions_checked。"""
    bridge = ReverseCognitiveBridge()
    evidence = bridge.to_evidence(_make_derive_result(), {"symbol": "BTC"}, {})

    prov = evidence["provenance"]
    assert "snapshot_id" in prov
    assert "outcome_id" in prov
    assert prov["dimensions_checked"] == ["C1", "C2"]


def test_record_evidence_calls_cognitive_record():
    """RED: record_evidence 调用认知记忆 record 并返回 memory_id。"""
    bridge = ReverseCognitiveBridge()
    mock_entry = MagicMock()
    mock_entry.record.return_value = "VM-TEST-123"
    bridge._entry = mock_entry  # 注入 mock

    memory_id = bridge.record_evidence(_make_derive_result(), {"symbol": "BTC"}, {"real_outcome": "SL"})

    assert memory_id == "VM-TEST-123"
    mock_entry.record.assert_called_once()
    # tags 应含 reverse-derive
    call_kwargs = mock_entry.record.call_args.kwargs
    assert "reverse-derive" in call_kwargs["tags"]


def test_record_evidence_fail_open_when_entry_none():
    """RED: 认知入口不可用时 FAIL-OPEN 返回 None。"""
    bridge = ReverseCognitiveBridge()
    bridge._entry = None

    memory_id = bridge.record_evidence(_make_derive_result(), {}, {})

    assert memory_id is None
