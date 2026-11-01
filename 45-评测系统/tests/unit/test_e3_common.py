# -*- coding: utf-8 -*-
"""
test_e3_common.py — P2-1 通用准入验证器（E3 三层）测试
======================================================
验收（PLAN P2-1 / SPEC §5.4）：
- 网络层：object_ref 可达、端点健康、依赖资源可解析
- 内容层：schema 校验、元数据规范（category 配对）、哈希一致
- 交叉层：声明与实际一致（commit / 泛化声明），未验证声明只告警
- 出分：三个 hard item（NET/CONTENT/CROSS），有致命项即 BLOCK，否则 PASS
- 预算：超时后剩余层 INCONCLUSIVE（≤60s 默认）
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from core.gateway import CategoriesConfig  # noqa: E402
from evaluators.common.e3 import (  # noqa: E402
    E3Context,
    E3Validator,
    ValidationIssue,
)

NOW = datetime(2026, 11, 1, 12, 0, 0, tzinfo=timezone.utc)

MAPPING = {
    "finance": ("strategy", "service"),
    "ai": ("model", "service"),
    "engineering": ("code_artifact", "dataset", "knowledge"),
}

VALID_REQUEST = {
    "object_ref": "git://repo/strategy@abc123",
    "category": "finance",
    "object_type": "strategy",
    "submitter": "trader-01",
    "purpose": "l0_settle",
    "spec_id": "EVS-20261101-0001",
    "env_manifest": {
        "runtime": "python3.11",
        "endpoints": ["https://object.local/health"],
        "resources": ["pg://readonly"],
        "secret_refs": ["OBJ_READ_KEY"],
    },
}


def categories(shadow: bool = True) -> CategoriesConfig:
    return CategoriesConfig(version="CAT-TEST@1", mapping=MAPPING, gate_shadow=shadow)


def make_validator(**kwargs) -> E3Validator:
    kwargs.setdefault("categories", categories())
    return E3Validator(**kwargs)


def issue_codes(issues: list[ValidationIssue], layer: str | None = None) -> list[str]:
    return [i.code for i in issues if layer is None or i.layer == layer]


# ---------- 网络层 ----------


def test_network_all_reachable_passes():
    validator = make_validator(fetcher=lambda _ref: True, prober=lambda _url: True)
    issues = validator.validate(VALID_REQUEST)
    assert issue_codes(issues, "network") == []


def test_network_object_unreachable_is_fatal():
    validator = make_validator(fetcher=lambda _ref: False, prober=lambda _url: True)
    issues = validator.validate(VALID_REQUEST)
    assert issue_codes(issues) == ["N1_object_unreachable:git://repo/strategy@abc123"]
    assert issues[0].severity == "fatal"


def test_network_endpoint_unhealthy_is_fatal():
    validator = make_validator(fetcher=lambda _ref: True, prober=lambda _url: False)
    issues = validator.validate(VALID_REQUEST)
    assert issue_codes(issues) == ["N2_endpoint_unhealthy:https://object.local/health"]


def test_network_malformed_resource_is_fatal():
    request = {
        **VALID_REQUEST,
        "env_manifest": {**VALID_REQUEST["env_manifest"], "resources": ["not a uri"]},
    }
    validator = make_validator(fetcher=lambda _ref: True, prober=lambda _url: True)
    issues = validator.validate(request)
    assert issue_codes(issues) == ["N3_resource_unresolvable:not a uri"]


def test_network_resource_resolver_failure_is_fatal():
    validator = make_validator(
        fetcher=lambda _ref: True,
        prober=lambda _url: True,
        resolver=lambda resource: resource != "pg://readonly",
    )
    issues = validator.validate(VALID_REQUEST)
    assert issue_codes(issues) == ["N3_resource_unreachable:pg://readonly"]


def test_network_local_file_exists_is_reachable(tmp_path):
    target = tmp_path / "artifact.bin"
    target.write_text("x", encoding="utf-8")
    request = {**VALID_REQUEST, "object_ref": f"file://{target}"}
    validator = make_validator(prober=lambda _url: True)
    assert issue_codes(validator.validate(request)) == []


def test_network_local_file_missing_is_fatal(tmp_path):
    request = {**VALID_REQUEST, "object_ref": f"file://{tmp_path / 'missing.bin'}"}
    validator = make_validator(prober=lambda _url: True)
    assert issue_codes(validator.validate(request)) == [
        "N1_object_unreachable:" + request["object_ref"]
    ]


def test_network_without_prober_warns_not_fatal():
    validator = make_validator(fetcher=lambda _ref: True, prober=None)
    issues = validator.validate(VALID_REQUEST)
    assert issue_codes(issues) == ["N2_probe_unconfigured"]
    assert issues[0].severity == "warn"


# ---------- 内容层 ----------


def test_content_schema_invalid_is_fatal():
    request = {**VALID_REQUEST, "purpose": "bad-purpose"}
    validator = make_validator(fetcher=lambda _ref: True, prober=lambda _url: True)
    issues = validator.validate(request)
    assert any(code.startswith("C1_schema_invalid") for code in issue_codes(issues, "content"))
    assert all(i.severity == "fatal" for i in issues if i.code.startswith("C1_"))


def test_content_category_object_type_mismatch_is_fatal():
    request = {**VALID_REQUEST, "category": "finance", "object_type": "model"}
    validator = make_validator(fetcher=lambda _ref: True, prober=lambda _url: True)
    issues = validator.validate(request)
    assert issue_codes(issues) == ["C2_category_mismatch:finance/model"]


def test_content_hash_mismatch_is_fatal():
    context = E3Context(declared_sha256="a" * 64, actual_sha256="b" * 64)
    validator = make_validator(fetcher=lambda _ref: True, prober=lambda _url: True)
    issues = validator.validate(VALID_REQUEST, context=context)
    assert issue_codes(issues) == ["C3_hash_mismatch"]


def test_content_hash_match_passes():
    context = E3Context(declared_sha256="a" * 64, actual_sha256="a" * 64)
    validator = make_validator(fetcher=lambda _ref: True, prober=lambda _url: True)
    assert validator.validate(VALID_REQUEST, context=context) == []


# ---------- 交叉层 ----------


def test_cross_commit_mismatch_is_fatal():
    context = E3Context(declared_commit="abc123", artifact_commit="def456")
    validator = make_validator(fetcher=lambda _ref: True, prober=lambda _url: True)
    issues = validator.validate(VALID_REQUEST, context=context)
    assert issue_codes(issues) == ["X1_commit_mismatch"]


def test_cross_object_ref_sha_mismatch_is_fatal():
    context = E3Context(declared_commit="abc123")
    validator = make_validator(fetcher=lambda _ref: True, prober=lambda _url: True)
    request = {**VALID_REQUEST, "object_ref": "git://repo/strategy@def456"}
    issues = validator.validate(request, context=context)
    assert issue_codes(issues) == ["X1_commit_mismatch"]


def test_cross_commit_match_passes():
    context = E3Context(declared_commit="abc123", artifact_commit="abc123")
    validator = make_validator(fetcher=lambda _ref: True, prober=lambda _url: True)
    assert validator.validate(VALID_REQUEST, context=context) == []


def test_cross_generic_claim_mismatch_is_fatal():
    context = E3Context(
        declared_claims={"model_version": "v1"},
        actual_claims={"model_version": "v2"},
    )
    validator = make_validator(fetcher=lambda _ref: True, prober=lambda _url: True)
    issues = validator.validate(VALID_REQUEST, context=context)
    assert issue_codes(issues) == ["X2_claim_mismatch:model_version"]


def test_cross_unverified_claim_warns():
    context = E3Context(declared_claims={"sbom_digest": "sha256:abc"}, actual_claims={})
    validator = make_validator(fetcher=lambda _ref: True, prober=lambda _url: True)
    issues = validator.validate(VALID_REQUEST, context=context)
    assert issue_codes(issues) == ["X3_claim_unverified:sbom_digest"]
    assert issues[0].severity == "warn"


# ---------- 出分（EvalItem） ----------


def test_build_items_all_layers_pass():
    validator = make_validator(fetcher=lambda _ref: True, prober=lambda _url: True)
    issues = validator.validate(VALID_REQUEST)
    items = validator.build_items("RUN-20261101-000001-01", issues)
    assert [i.name for i in items] == ["E3-network", "E3-content", "E3-cross"]
    assert [i.status for i in items] == ["PASS", "PASS", "PASS"]
    assert all(i.kind == "hard" for i in items)
    assert all(i.run_id == "RUN-20261101-000001-01" for i in items)


def test_build_items_block_only_failed_layer():
    validator = make_validator(fetcher=lambda _ref: False, prober=lambda _url: True)
    issues = validator.validate(VALID_REQUEST)
    items = validator.build_items("RUN-20261101-000001-01", issues)
    assert [i.status for i in items] == ["BLOCK", "PASS", "PASS"]
    assert "N1_object_unreachable" in (items[0].detail or "")


def test_build_items_carries_issue_codes_in_detail():
    validator = make_validator(fetcher=lambda _ref: True, prober=lambda _url: False)
    issues = validator.validate(VALID_REQUEST)
    items = validator.build_items("RUN-1", issues)
    assert items[0].detail == "N2_endpoint_unhealthy:https://object.local/health"


# ---------- 预算 ----------


def test_budget_exceeded_marks_remaining_layers_inconclusive():
    ticks = iter([NOW, NOW + timedelta(seconds=61), NOW + timedelta(seconds=61)])
    validator = make_validator(
        fetcher=lambda _ref: True,
        prober=lambda _url: True,
        clock=lambda: next(ticks),
        budget_ms=60000,
    )
    issues = validator.validate(VALID_REQUEST)
    assert issue_codes(issues) == ["BUDGET_EXCEEDED", "BUDGET_EXCEEDED"]
    items = validator.build_items("RUN-1", issues)
    # 网络层已完成 → PASS；内容层与交叉层超时 → INCONCLUSIVE
    assert [i.status for i in items] == ["PASS", "INCONCLUSIVE", "INCONCLUSIVE"]


def test_budget_issue_never_blocks():
    ticks = iter([NOW, NOW + timedelta(seconds=61)])
    validator = make_validator(
        fetcher=lambda _ref: True,
        prober=lambda _url: True,
        clock=lambda: next(ticks),
        budget_ms=60000,
    )
    issues = validator.validate(VALID_REQUEST)
    assert all(i.severity != "fatal" for i in issues)
