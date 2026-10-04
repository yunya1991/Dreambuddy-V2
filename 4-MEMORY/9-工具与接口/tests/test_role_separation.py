"""N-P1b 角色分离 + 隔离区 + 验证宽限期测试（RED 阶段）。

验收标准：
- 角色分离：verifier_id == creator_id → 该信号视为 abstain
- 隔离区：新记忆标记为 quarantine，需验证通过才转正
- 宽限期：C 档记忆在 grace_verify_count 次 verify 内不因 fail 降权
- 可配置开关
"""
import pytest


def test_module_importable():
    from role_separation import (
        RolePolicy, QuarantineManager, GracePolicy,
        filter_self_verification, is_in_grace_period,
    )


# ---------------------------------------------------------------------------
# 角色分离
# ---------------------------------------------------------------------------

def test_self_verification_filtered_as_abstain():
    from role_separation import filter_self_verification
    from verification_record import VerificationSignal
    signals = [
        VerificationSignal(stage="a", verdict="pass", verifier_id="creator1"),
        VerificationSignal(stage="b", verdict="pass", verifier_id="other"),
    ]
    filtered = filter_self_verification(signals, creator_id="creator1")
    # 构造者自己的信号 → abstain
    assert filtered[0].verdict == "abstain"
    assert filtered[1].verdict == "pass"
    # 原始信号不变
    assert signals[0].verdict == "pass"


def test_no_self_verification_passes_through():
    from role_separation import filter_self_verification
    from verification_record import VerificationSignal
    signals = [
        VerificationSignal(stage="a", verdict="pass", verifier_id="other1"),
        VerificationSignal(stage="b", verdict="fail", verifier_id="other2"),
    ]
    filtered = filter_self_verification(signals, creator_id="creator1")
    assert filtered[0].verdict == "pass"
    assert filtered[1].verdict == "fail"


def test_filter_works_with_dict_signals():
    from role_separation import filter_self_verification
    signals = [
        {"stage": "a", "verdict": "pass", "verifier_id": "creator1"},
        {"stage": "b", "verdict": "pass", "verifier_id": "other"},
    ]
    filtered = filter_self_verification(signals, creator_id="creator1")
    assert filtered[0]["verdict"] == "abstain"
    assert filtered[1]["verdict"] == "pass"


# ---------------------------------------------------------------------------
# 隔离区
# ---------------------------------------------------------------------------

def test_quarantine_new_memory():
    from role_separation import QuarantineManager
    qm = QuarantineManager()
    # 未知记忆默认 released（兼容存量记忆，避免 recall 返回空）
    assert qm.is_quarantined("VM-new") is False
    qm.quarantine("VM-new")
    assert qm.is_quarantined("VM-new") is True
    qm.release("VM-new")
    assert qm.is_quarantined("VM-new") is False


def test_quarantine_release_requires_verification():
    from role_separation import QuarantineManager
    qm = QuarantineManager()
    qm.quarantine("VM-1")
    assert qm.is_quarantined("VM-1") is True
    # 未验证通过不能释放
    qm.release("VM-1", verified=False)
    assert qm.is_quarantined("VM-1") is True
    # 验证通过才释放
    qm.release("VM-1", verified=True)
    assert qm.is_quarantined("VM-1") is False


def test_quarantine_disabled():
    from role_separation import QuarantineManager
    qm = QuarantineManager(enabled=False)
    assert qm.is_quarantined("VM-anything") is False


# ---------------------------------------------------------------------------
# 验证宽限期
# ---------------------------------------------------------------------------

def test_c_tier_in_grace_period():
    from role_separation import GracePolicy
    gp = GracePolicy(grace_verify_count=3)
    # C 档 + verify_count < 3 → 在宽限期内
    assert gp.is_in_grace(quality="C", verify_count=0) is True
    assert gp.is_in_grace(quality="C", verify_count=2) is True
    assert gp.is_in_grace(quality="C", verify_count=3) is False


def test_non_c_tier_not_in_grace():
    from role_separation import GracePolicy
    gp = GracePolicy(grace_verify_count=3)
    assert gp.is_in_grace(quality="B", verify_count=0) is False
    assert gp.is_in_grace(quality="A", verify_count=0) is False


def test_grace_period_protects_from_fail_downgrade():
    """宽限期内 fail 不导致置信度下降。"""
    from role_separation import GracePolicy
    gp = GracePolicy(grace_verify_count=3)
    # 宽限期内：fail 应被保护（返回 should_downgrade=False）
    assert gp.should_downgrade(quality="C", verify_count=1, success=False) is False
    # 宽限期外：fail 正常降权
    assert gp.should_downgrade(quality="C", verify_count=5, success=False) is True
    # pass 总是允许升级
    assert gp.should_downgrade(quality="C", verify_count=1, success=True) is False
    assert gp.should_downgrade(quality="C", verify_count=5, success=True) is False


def test_grace_policy_disabled():
    from role_separation import GracePolicy
    gp = GracePolicy(enabled=False)
    assert gp.is_in_grace(quality="C", verify_count=0) is False
    assert gp.should_downgrade(quality="C", verify_count=0, success=False) is True
