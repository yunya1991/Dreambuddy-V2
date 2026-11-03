"""TB2 Beta 分布 verify 升级 TDD 用例 — SPEC-L0-AGENT-TRAIN-BASE v0.1 §2

RED 1-6 对应 SPEC §2.4；另加持久化/adapter 两条回归用例。
"""

import pytest


# RED 1: 升级后 legacy verify success=True 从 confidence 0.5 出发，mean ≥ 0.7（零业务回归）
def test_red1_legacy_verify_zero_regression(tmp_path):
    from cognitive_loop_entry import CognitiveLoopEntry

    cle = CognitiveLoopEntry(storage_path=str(tmp_path / "test.db"))
    try:
        memory_id = cle.record(
            content="TB2 legacy verify 零回归",
            quality_level="B",
            confidence=0.5,
            source="test_beta_verify",
        )
        result = cle.verify(memory_id, success=True)
        assert result["success"] is True
        assert result["new_confidence"] >= 0.7
        # 旧返回字段必须保留（调用方零感知）
        for key in ("memory_id", "success", "old_confidence", "new_confidence", "new_quality"):
            assert key in result
    finally:
        cle.close()


# RED 2: Beta(1,1) + success_rate=1.0 → Beta(2,1) → mean = 0.667
def test_red2_beta_full_success():
    from cognitive_interfaces import BetaState

    updated = BetaState(1.0, 1.0).update(1.0)
    assert updated.alpha == pytest.approx(2.0)
    assert updated.beta == pytest.approx(1.0)
    assert updated.mean == pytest.approx(2.0 / 3.0, abs=1e-6)


# RED 3: Beta(2,1) + success_rate=0.7 → Beta(2.7,1.3) → mean = 0.675
def test_red3_beta_partial_success():
    from cognitive_interfaces import BetaState

    updated = BetaState(2.0, 1.0).update(0.7)
    assert updated.alpha == pytest.approx(2.7)
    assert updated.beta == pytest.approx(1.3)
    assert updated.mean == pytest.approx(0.675, abs=1e-6)


# RED 4: drift_detected=True → 先验重置为 Beta(1,1)（不继承历史状态）
def test_red4_drift_resets_prior():
    from cognitive_interfaces import BetaState, verify_beta

    prior = BetaState(10.0, 1.0)
    result = verify_beta(
        "VM-drift-reset",
        success_rate=0.0,
        evidence_confidence=1.0,
        drift_detected=True,
        beta_state=prior,
    )
    # 若未重置，会得到 Beta(10,2)；重置后为 Beta(1,2)
    assert result.data["beta_alpha"] == pytest.approx(1.0)
    assert result.data["beta_beta"] == pytest.approx(2.0)
    assert result.data["drift_detected"] is True


# RED 5: PoE evidence_confidence=0.8 修正 success_rate=0.7 → adjusted_rate=0.56
def test_red5_poe_evidence_confidence_adjusts_rate():
    from cognitive_interfaces import verify_beta

    result = verify_beta(
        "VM-poe-adjust",
        success_rate=0.7,
        evidence_confidence=0.8,
    )
    assert result.data["beta_alpha"] == pytest.approx(1.56, abs=1e-9)
    assert result.data["beta_beta"] == pytest.approx(1.44, abs=1e-9)


# RED 6: envelope 返回体与旧 verify schema 兼容（data 含 confidence 键）
def test_red6_envelope_schema_compatible(tmp_path):
    from cognitive_loop_entry import CognitiveLoopEntry

    cle = CognitiveLoopEntry(storage_path=str(tmp_path / "test.db"))
    try:
        memory_id = cle.record(
            content="TB2 envelope schema 兼容",
            quality_level="C",
            confidence=0.4,
            source="test_beta_verify",
        )
        result = cle.verify(memory_id, success=True)
        assert "confidence" in result
        assert result["confidence"] == pytest.approx(result["new_confidence"], abs=1e-6)
        assert result["data_schema_version"] == "0.2-beta"
        assert "beta_alpha" in result
        assert "beta_beta" in result
        assert "drift_detected" in result
    finally:
        cle.close()


# 附加 1: Beta 状态跨 verify 持久化（第二次 verify 在第一次后验基础上累加）
def test_beta_state_persists_across_verify(tmp_path):
    from cognitive_loop_entry import CognitiveLoopEntry

    cle = CognitiveLoopEntry(storage_path=str(tmp_path / "test.db"))
    try:
        memory_id = cle.record(
            content="TB2 Beta 状态持久化",
            quality_level="C",
            confidence=0.3,
            source="test_beta_verify",
        )
        first = cle.verify(memory_id, success=True)
        second = cle.verify(memory_id, success=True)
        assert second["beta_alpha"] > first["beta_alpha"]
        assert second["new_confidence"] > first["new_confidence"]
    finally:
        cle.close()


# 附加 2: adapter 桥接旧 bool 签名 + drift 重置
def test_adapter_bridges_bool_and_drift(tmp_path):
    from cognitive_loop_entry import CognitiveLoopEntry

    cle = CognitiveLoopEntry(storage_path=str(tmp_path / "test.db"))
    try:
        memory_id = cle.record(
            content="TB2 adapter bool 桥接",
            quality_level="C",
            confidence=0.4,
            source="test_beta_verify",
        )
        result = cle._beta_verify_adapter(memory_id, success=False, drift_detected=True)
        assert result["memory_id"] == memory_id
        assert result["beta_alpha"] == pytest.approx(1.0)
        assert result["beta_beta"] == pytest.approx(2.0)
        assert result["drift_detected"] is True
        assert result["data_schema_version"] == "0.2-beta"
    finally:
        cle.close()
