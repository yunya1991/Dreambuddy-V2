# -*- coding: utf-8 -*-
"""
test_gateway.py — P0-4 受理网关测试
====================================
验收（PLAN P0-4 / SPEC §13.1）：
- 合法请求受理：返回 eval_id（EV-YYYYMMDD-NNNNNN）+ spec_hash，状态 accepted
- 幂等：同 Idempotency-Key 重复提交返回同一 eval_id，不产生重复记录
- 缺 Idempotency-Key → 拒绝（§13.1 强制幂等头）
- 请求体不符合 eval_request.v1.json → 拒绝
- category 与 object_type 不匹配 → 拒绝（§13.1 受理即拒条件）
- 影子模式：config/categories.yaml 默认 gate.shadow=true（初期只受理不拦截）
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from core.gateway import (  # noqa: E402
    CategoriesConfig,
    CategoriesConfigError,
    CategoryMismatchError,
    Gateway,
    InMemoryEvalRequestStore,
    MissingIdempotencyKeyError,
    RequestValidationError,
)

MODULE_ROOT = Path(__file__).resolve().parent.parent.parent
CATEGORIES_PATH = MODULE_ROOT / "config" / "categories.yaml"

FIXED_NOW = datetime(2026, 11, 1, 12, 0, 0, tzinfo=timezone.utc)

VALID_ENV_MANIFEST = {
    "runtime": "python3.11",
    "endpoints": ["https://object.local/health"],
    "resources": ["pg://readonly"],
    "secret_refs": ["OBJ_READ_KEY"],
}

VALID_COMBOS = [
    ("finance", "strategy"),
    ("finance", "service"),
    ("ai", "model"),
    ("ai", "service"),
    ("engineering", "code_artifact"),
    ("engineering", "dataset"),
    ("engineering", "knowledge"),
]


def make_payload(category: str = "finance", object_type: str = "strategy", **overrides):
    payload = {
        "object_ref": "git://repo/strategy@abc123",
        "category": category,
        "object_type": object_type,
        "submitter": "trader-01",
        "purpose": "l0_settle",
        "priority": "normal",
        "spec_id": "EVS-20261101-0001",
        "env_manifest": dict(VALID_ENV_MANIFEST),
    }
    payload.update(overrides)
    return payload


@pytest.fixture
def store():
    return InMemoryEvalRequestStore()


@pytest.fixture
def categories():
    return CategoriesConfig.load(CATEGORIES_PATH)


@pytest.fixture
def gateway(store, categories):
    return Gateway(store=store, categories=categories, clock=lambda: FIXED_NOW)


# ---------- 受理与幂等 ----------


def test_accept_valid_request(gateway, store):
    result = gateway.submit(make_payload(), idempotency_key="key-0001")
    assert result.status == "accepted"
    assert result.eval_id == "EV-20261101-000001"
    assert len(result.spec_hash) == 64
    int(result.spec_hash, 16)  # 必须是合法 hex
    record = store.get_by_idempotency_key("key-0001")
    assert record is not None
    assert record.eval_id == result.eval_id
    assert record.status == "queued"
    assert record.category == "finance"
    assert record.object_type == "strategy"


def test_eval_id_sequence_increments(gateway):
    r1 = gateway.submit(make_payload(), idempotency_key="k1")
    r2 = gateway.submit(make_payload(), idempotency_key="k2")
    assert r1.eval_id == "EV-20261101-000001"
    assert r2.eval_id == "EV-20261101-000002"


def test_duplicate_idempotency_key_returns_same_eval_id(gateway, store):
    r1 = gateway.submit(make_payload(), idempotency_key="dup-key")
    r2 = gateway.submit(make_payload(), idempotency_key="dup-key")
    assert r2.eval_id == r1.eval_id
    assert r2.spec_hash == r1.spec_hash
    assert len(store.all()) == 1  # 不产生重复记录


def test_idempotent_replay_ignores_new_payload(gateway, store):
    """同 key 重放返回原始记录（即使 payload 字段不同）。"""
    r1 = gateway.submit(make_payload(), idempotency_key="replay-key")
    r2 = gateway.submit(
        make_payload(object_ref="git://repo/strategy@def456"), idempotency_key="replay-key"
    )
    assert r2.eval_id == r1.eval_id
    assert store.get_by_idempotency_key("replay-key").object_ref == "git://repo/strategy@abc123"


def test_spec_hash_deterministic_for_same_spec_id(gateway):
    r1 = gateway.submit(make_payload(), idempotency_key="s1")
    r2 = gateway.submit(make_payload(), idempotency_key="s2")
    assert r1.spec_hash == r2.spec_hash  # 同 spec_id → 同占位哈希


# ---------- 幂等头强制 ----------


@pytest.mark.parametrize("bad_key", [None, "", "   "])
def test_missing_idempotency_key_rejected(gateway, bad_key):
    with pytest.raises(MissingIdempotencyKeyError):
        gateway.submit(make_payload(), idempotency_key=bad_key)


def test_missing_key_does_not_touch_store(gateway, store):
    with pytest.raises(MissingIdempotencyKeyError):
        gateway.submit(make_payload(), idempotency_key=None)
    assert store.all() == []


# ---------- Schema 校验 ----------


INVALID_PAYLOADS = {
    "missing_env_manifest": lambda p: p.pop("env_manifest"),
    "missing_object_ref": lambda p: p.pop("object_ref"),
    "missing_submitter": lambda p: p.pop("submitter"),
    "bad_category_enum": lambda p: p.update(category="crypto"),
    "bad_object_type_enum": lambda p: p.update(object_type="robot"),
    "bad_purpose_enum": lambda p: p.update(purpose="production"),
    "bad_priority_enum": lambda p: p.update(priority="urgent"),
    "extra_property": lambda p: p.update(unknown_field="x"),
    "empty_endpoints": lambda p: p["env_manifest"].update(endpoints=[]),
    "missing_endpoints": lambda p: p["env_manifest"].pop("endpoints"),
    "bad_spec_id_pattern": lambda p: p.update(spec_id="SPEC-001"),
    "empty_object_ref": lambda p: p.update(object_ref=""),
    "env_manifest_extra_property": lambda p: p["env_manifest"].update(api_key="sk-xxx"),
}


@pytest.mark.parametrize("case", sorted(INVALID_PAYLOADS))
def test_schema_invalid_rejected(gateway, store, case):
    payload = make_payload()
    INVALID_PAYLOADS[case](payload)
    with pytest.raises(RequestValidationError):
        gateway.submit(payload, idempotency_key=f"invalid-{case}")
    assert store.all() == []  # 拒绝不入库


def test_non_dict_payload_rejected(gateway):
    with pytest.raises(RequestValidationError):
        gateway.submit(["not", "a", "dict"], idempotency_key="k-non-dict")


# ---------- 类别与对象类型匹配 ----------


MISMATCH_COMBOS = [
    ("finance", "model"),
    ("finance", "knowledge"),
    ("finance", "code_artifact"),
    ("ai", "strategy"),
    ("ai", "dataset"),
    ("engineering", "strategy"),
    ("engineering", "model"),
    ("engineering", "service"),
]


@pytest.mark.parametrize("category,object_type", MISMATCH_COMBOS)
def test_category_object_type_mismatch_rejected(gateway, store, category, object_type):
    with pytest.raises(CategoryMismatchError):
        gateway.submit(make_payload(category, object_type), idempotency_key="mismatch")
    assert store.all() == []


@pytest.mark.parametrize("category,object_type", VALID_COMBOS)
def test_valid_category_combos_accepted(gateway, category, object_type):
    result = gateway.submit(
        make_payload(category, object_type),
        idempotency_key=f"ok-{category}-{object_type}",
    )
    assert result.status == "accepted"


# ---------- 影子模式与配置加载 ----------


def test_shadow_gate_enabled_by_default(categories, gateway):
    """影子模式硬要求：初期只受理不拦截，gate.shadow 默认 true。"""
    assert categories.gate_shadow is True
    assert gateway.gate_shadow is True


def test_categories_config_version(categories):
    assert categories.version == "CAT-2026Q4@1"


def test_categories_config_missing_file(tmp_path):
    with pytest.raises(CategoriesConfigError):
        CategoriesConfig.load(tmp_path / "nope.yaml")


def write_cfg(tmp_path: Path, text: str) -> Path:
    p = tmp_path / "categories.yaml"
    p.write_text(text, encoding="utf-8")
    return p


def test_config_missing_version_rejected(tmp_path):
    p = write_cfg(tmp_path, "categories:\n  finance:\n    object_types: [strategy]\n")
    with pytest.raises(CategoriesConfigError):
        CategoriesConfig.load(p)


def test_config_unknown_category_rejected(tmp_path):
    p = write_cfg(
        tmp_path,
        'version: "V1"\ncategories:\n  crypto:\n    object_types: [strategy]\n',
    )
    with pytest.raises(CategoriesConfigError):
        CategoriesConfig.load(p)


def test_config_unknown_object_type_rejected(tmp_path):
    p = write_cfg(
        tmp_path,
        'version: "V1"\ncategories:\n  finance:\n    object_types: [robot]\n',
    )
    with pytest.raises(CategoriesConfigError):
        CategoriesConfig.load(p)


def test_config_empty_object_types_rejected(tmp_path):
    p = write_cfg(
        tmp_path,
        'version: "V1"\ncategories:\n  finance:\n    object_types: []\n',
    )
    with pytest.raises(CategoriesConfigError):
        CategoriesConfig.load(p)


def test_config_duplicate_object_types_rejected(tmp_path):
    p = write_cfg(
        tmp_path,
        'version: "V1"\ncategories:\n  finance:\n    object_types: [strategy, strategy]\n',
    )
    with pytest.raises(CategoriesConfigError):
        CategoriesConfig.load(p)


def test_config_missing_gate_defaults_shadow_true(tmp_path):
    """gate 段缺失时 fail-safe：默认影子模式。"""
    p = write_cfg(
        tmp_path,
        'version: "V1"\ncategories:\n  finance:\n    object_types: [strategy]\n',
    )
    cfg = CategoriesConfig.load(p)
    assert cfg.gate_shadow is True
