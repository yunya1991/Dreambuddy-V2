"""P1-3: 6 信任失效条件 TDD RED 测试

SPEC: 35-广义认知系统协作模块/SPEC-Unified-PoE-Framework.md §2.3 + COLLABORATION-CONTRACT.md v1.1

P1-3: 信任传递的 6 个失效条件（v2.0 关键修正）

  v1.0 的 3 个扩展为 6 个：
  1. 代码变更（git commit hash 变化） → 信任失效，需重新重型验证
  2. verify(success=False) → 声誉分下降，升级为重型验证
  3. 超时（按产出类型分级：代码 1 天 / 文档 30 天） → 降级为轻量验证
  4. 依赖指纹变化（下游代码 hash 变即失效） → 信任失效，重新重型验证
  5. scope 漂移（为目的 A 验证 ≠ 目的 B 安全） → 需重新验证
  6. 抽样重验失败（10% 概率重跑，未通过） → 信任降级，触发重型验证

设计依据（SLSA VSA periodic re-verification）：
  - 信任不是无条件的，需要跟踪 trust_state
  - 每次产出验证后记录 trust_state（first_verified_at + git_commit_hash + dependency_fp + scope）
  - 后续调用时 check_trust_validity 验证 6 个失效条件

RED 契约：
  1. trust_state 表存在
  2. record_trust_state(memory_id, git_commit_hash, dependency_fp, scope) 方法
  3. check_trust_validity(memory_id, current_git_hash, current_dependency_fp, current_scope) 方法
  4. 6 个失效条件各自有对应测试
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

_SCRIPT_DIR = Path(__file__).parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))


# ─────────────────────────────── trust_state 表 + 方法存在性 ───────────────────────────────

def test_trust_state_table_exists(tmp_path):
    """RED: 应有 trust_state 表。"""
    from evidence_ledger import EvidenceLedger
    ledger = EvidenceLedger(db_path=tmp_path / "test_p1_3.db")
    cursor = ledger._conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='trust_state'"
    )
    assert cursor.fetchone() is not None, "trust_state 表不存在"


def test_record_trust_state_method_exists(tmp_path):
    """RED: EvidenceLedger 应有 record_trust_state 方法。"""
    from evidence_ledger import EvidenceLedger
    ledger = EvidenceLedger(db_path=tmp_path / "test_p1_3.db")
    assert hasattr(ledger, "record_trust_state"), \
        "EvidenceLedger 应提供 record_trust_state(memory_id, git_commit_hash, dependency_fp, scope)"


def test_check_trust_validity_method_exists(tmp_path):
    """RED: EvidenceLedger 应有 check_trust_validity 方法。"""
    from evidence_ledger import EvidenceLedger
    ledger = EvidenceLedger(db_path=tmp_path / "test_p1_3.db")
    assert hasattr(ledger, "check_trust_validity"), \
        "EvidenceLedger 应提供 check_trust_validity(memory_id, current_git_hash, current_dependency_fp, current_scope)"


def test_check_trust_validity_no_state_returns_false(tmp_path):
    """RED: 无 trust_state 记录时，check_trust_validity 返回 (False, 'no_trust_state')。"""
    from evidence_ledger import EvidenceLedger
    ledger = EvidenceLedger(db_path=tmp_path / "test_p1_3.db")
    is_valid, reason = ledger.check_trust_validity(
        "VM-no-state", "hash1", "dep_fp1", "scope1",
    )
    assert is_valid is False
    assert reason == "no_trust_state"


def test_check_trust_validity_all_match_returns_true(tmp_path):
    """RED: 所有条件匹配时，check_trust_validity 返回 (True, 'valid')。"""
    from evidence_ledger import EvidenceLedger
    ledger = EvidenceLedger(db_path=tmp_path / "test_p1_3.db")
    ledger.record_trust_state(
        memory_id="VM-valid-test",
        git_commit_hash="abc123",
        dependency_fp="dep_fp_abc",
        scope="code_merge",
    )
    is_valid, reason = ledger.check_trust_validity(
        "VM-valid-test", "abc123", "dep_fp_abc", "code_merge",
    )
    assert is_valid is True
    assert reason == "valid"


# ─────────────────────────────── 失效条件 1: 代码变更 ───────────────────────────────

def test_failure_condition_1_code_change(tmp_path):
    """RED: 失效条件 1 — git_commit_hash 变化 → 信任失效。"""
    from evidence_ledger import EvidenceLedger
    ledger = EvidenceLedger(db_path=tmp_path / "test_p1_3.db")
    ledger.record_trust_state(
        memory_id="VM-code-change",
        git_commit_hash="abc123",
        dependency_fp="dep_fp",
        scope="scope1",
    )
    is_valid, reason = ledger.check_trust_validity(
        "VM-code-change", "different_hash", "dep_fp", "scope1",
    )
    assert is_valid is False
    assert reason == "code_change"


# ─────────────────────────────── 失效条件 2: verify 失败 ───────────────────────────────

def test_failure_condition_2_verify_failed(tmp_path):
    """RED: 失效条件 2 — verify_failures > 0 → 信任失效。"""
    from evidence_ledger import EvidenceLedger
    ledger = EvidenceLedger(db_path=tmp_path / "test_p1_3.db")
    ledger.record_trust_state(
        memory_id="VM-verify-failed",
        git_commit_hash="abc123",
        dependency_fp="dep_fp",
        scope="scope1",
    )
    # 标记 verify 失败
    ledger.mark_verify_failure("VM-verify-failed")
    is_valid, reason = ledger.check_trust_validity(
        "VM-verify-failed", "abc123", "dep_fp", "scope1",
    )
    assert is_valid is False
    assert reason == "verify_failed"


# ─────────────────────────────── 失效条件 3: 超时 ───────────────────────────────

def test_failure_condition_3_timeout_code(tmp_path):
    """RED: 失效条件 3 — 代码类产出超时（> 1 天）→ 信任失效。"""
    from evidence_ledger import EvidenceLedger
    ledger = EvidenceLedger(db_path=tmp_path / "test_p1_3.db")
    ledger.record_trust_state(
        memory_id="VM-timeout-code",
        git_commit_hash="abc123",
        dependency_fp="dep_fp",
        scope="code_merge",
    )
    # 模拟超时：直接修改 first_verified_at 为 2 天前
    two_days_ago_ns = (time.time_ns()) - 2 * 24 * 3600 * 10**9
    ledger._conn.execute(
        "UPDATE trust_state SET first_verified_at = ? WHERE memory_id = ?",
        (two_days_ago_ns, "VM-timeout-code"),
    )
    ledger._conn.commit()
    is_valid, reason = ledger.check_trust_validity(
        "VM-timeout-code", "abc123", "dep_fp", "code_merge",
    )
    assert is_valid is False
    assert reason == "timeout"


def test_failure_condition_3_timeout_doc(tmp_path):
    """RED: 失效条件 3 — 文档类产出超时阈值 30 天（比代码 1 天宽松）。"""
    from evidence_ledger import EvidenceLedger
    ledger = EvidenceLedger(db_path=tmp_path / "test_p1_3.db")
    ledger.record_trust_state(
        memory_id="VM-timeout-doc",
        git_commit_hash="abc123",
        dependency_fp="dep_fp",
        scope="doc_review",  # 文档类 scope
    )
    # 5 天前（代码超时但文档不超时）
    five_days_ago_ns = (time.time_ns()) - 5 * 24 * 3600 * 10**9
    ledger._conn.execute(
        "UPDATE trust_state SET first_verified_at = ? WHERE memory_id = ?",
        (five_days_ago_ns, "VM-timeout-doc"),
    )
    ledger._conn.commit()
    is_valid, reason = ledger.check_trust_validity(
        "VM-timeout-doc", "abc123", "dep_fp", "doc_review",
    )
    # 文档 5 天不超时（30 天阈值）
    assert is_valid is True
    assert reason == "valid"


# ─────────────────────────────── 失效条件 4: 依赖指纹变化 ───────────────────────────────

def test_failure_condition_4_dependency_changed(tmp_path):
    """RED: 失效条件 4 — 依赖指纹变化 → 信任失效。"""
    from evidence_ledger import EvidenceLedger
    ledger = EvidenceLedger(db_path=tmp_path / "test_p1_3.db")
    ledger.record_trust_state(
        memory_id="VM-dep-change",
        git_commit_hash="abc123",
        dependency_fp="original_dep_fp",
        scope="scope1",
    )
    is_valid, reason = ledger.check_trust_validity(
        "VM-dep-change", "abc123", "changed_dep_fp", "scope1",
    )
    assert is_valid is False
    assert reason == "dependency_changed"


# ─────────────────────────────── 失效条件 5: scope 漂移 ───────────────────────────────

def test_failure_condition_5_scope_drift(tmp_path):
    """RED: 失效条件 5 — scope 漂移 → 信任失效。"""
    from evidence_ledger import EvidenceLedger
    ledger = EvidenceLedger(db_path=tmp_path / "test_p1_3.db")
    ledger.record_trust_state(
        memory_id="VM-scope-drift",
        git_commit_hash="abc123",
        dependency_fp="dep_fp",
        scope="purpose_A",
    )
    is_valid, reason = ledger.check_trust_validity(
        "VM-scope-drift", "abc123", "dep_fp", "purpose_B",
    )
    assert is_valid is False
    assert reason == "scope_drift"


# ─────────────────────────────── 失效条件 6: 抽样重验失败 ───────────────────────────────

def test_failure_condition_6_sample_reverify_failed(tmp_path):
    """RED: 失效条件 6 — 抽样重验失败 → 信任失效。"""
    from evidence_ledger import EvidenceLedger
    ledger = EvidenceLedger(db_path=tmp_path / "test_p1_3.db")
    ledger.record_trust_state(
        memory_id="VM-sample-failed",
        git_commit_hash="abc123",
        dependency_fp="dep_fp",
        scope="scope1",
    )
    # 标记抽样重验失败
    ledger.mark_sample_reverify_failure("VM-sample-failed")
    is_valid, reason = ledger.check_trust_validity(
        "VM-sample-failed", "abc123", "dep_fp", "scope1",
    )
    assert is_valid is False
    assert reason == "sample_reverify_failed"


# ─────────────────────────────── FAIL-OPEN ───────────────────────────────

def test_check_trust_validity_fail_open_on_exception(tmp_path):
    """RED: check_trust_validity 异常时 FAIL-OPEN 返回 (True, 'fail_open')。"""
    from evidence_ledger import EvidenceLedger
    ledger = EvidenceLedger(db_path=tmp_path / "test_p1_3.db")
    # 传入 None 触发异常
    is_valid, reason = ledger.check_trust_validity(None, None, None, None)
    # FAIL-OPEN：返回有效（不阻塞主流程）
    assert is_valid is True
    assert reason == "fail_open"
