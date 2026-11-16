"""H1：CapabilityBundle 声明层（登记 + hash），执行仍交给 DSH。

对齐 56/SPEC-56-H v0.3 §4.1：
  - bundle 只声明 profile → role → model / skills / tools / permission
  - hash 对声明字段做 canonical JSON 哈希，不含 generated_at
  - tools 必须是 H2 tool_set 子集；read 不得 requires_mandate
  - 不改 34 route_hint，只提供增量合并字段
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

BASE = Path(__file__).parent.parent.parent  # 1-ARCHITECTURE/
sys.path.insert(0, str(BASE))

from dreamos.core.capability.capability_bundle import (  # noqa: E402
    BUNDLE_REGISTRY,
    CapabilityBundleError,
    build_bundle,
    bundle_route_hint,
    compute_bundle_hash,
    get_bundle,
    register_bundle,
)

HASH_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")


def _bundle(**overrides):
    params = {
        "agent_profile_id": "developer",
        "bundle_id": "cb-test-001",
    }
    params.update(overrides)
    return build_bundle(**params)


def test_default_bundle_declares_role_model_and_hash():
    bundle = _bundle()

    assert bundle["agent_profile_id"] == "developer"
    assert bundle["worker_role_id"] == "engineer"
    assert bundle["model_profile"]["model_id"] == "qwen-max"
    assert bundle["source"] == "registry"
    assert HASH_PATTERN.match(bundle["hash"])
    assert bundle["hash"] == compute_bundle_hash(
        agent_profile_id=bundle["agent_profile_id"],
        worker_role_id=bundle["worker_role_id"],
        model_profile=bundle["model_profile"],
        skills=bundle["skills"],
        tools=bundle["tools"],
        permission_mode=bundle["permission_mode"],
    )


def test_hash_is_order_insensitive():
    a = _bundle(tools=["l0.cognition.recall", "l0.cognition.unified_search"])
    b = _bundle(tools=["l0.cognition.unified_search", "l0.cognition.recall"])
    assert a["hash"] == b["hash"]


def test_unknown_profile_and_bad_mode_rejected():
    with pytest.raises(CapabilityBundleError):
        _bundle(agent_profile_id="hacker")
    with pytest.raises(CapabilityBundleError):
        _bundle(permission_mode="yolo")


def test_tools_must_be_subset_of_tool_set():
    with pytest.raises(CapabilityBundleError):
        _bundle(
            tools=["l0.cognition.recall", "l0.cognition.record"],
            allowed_tools=["l0.cognition.recall"],
        )


def test_worker_role_must_exist_in_registry():
    with pytest.raises(CapabilityBundleError):
        _bundle(worker_roles=["research"])
    # 合法角色不报错
    assert _bundle(worker_roles=["research", "engineer"])["worker_role_id"] == "engineer"


def test_permission_and_mandate_consistency():
    with pytest.raises(CapabilityBundleError):
        _bundle(permission_mode="read", requires_mandate=True)
    with pytest.raises(CapabilityBundleError):
        _bundle(permission_mode="write", requires_mandate=False)
    assert _bundle(permission_mode="write", requires_mandate=True)["requires_mandate"] is True


def test_register_and_get_bundle():
    BUNDLE_REGISTRY.clear()
    bundle = _bundle(bundle_id="cb-reg-001")
    assert register_bundle(bundle)["bundle_id"] == "cb-reg-001"
    assert get_bundle("cb-reg-001") == bundle


def test_register_rejects_tampered_hash_and_conflict():
    BUNDLE_REGISTRY.clear()
    bundle = _bundle(bundle_id="cb-reg-002")
    tampered = dict(bundle, tools=["l0.cognition.recall"])
    with pytest.raises(CapabilityBundleError):
        register_bundle(tampered)

    register_bundle(bundle)
    with pytest.raises(CapabilityBundleError):
        register_bundle(dict(bundle, bundle_id="cb-reg-002", agent_profile_id="reviewer"))


def test_route_hint_fields_are_declaration_only():
    bundle = _bundle(bundle_id="cb-route-001")
    hint = bundle_route_hint(bundle)
    assert hint == {"capability_bundle_id": "cb-route-001", "model_profile_id": "qwen-max"}
    assert "execution" not in hint
