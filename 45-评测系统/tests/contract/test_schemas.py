# -*- coding: utf-8 -*-
"""
test_schemas.py — P0-1 契约测试
================================
验收（PLAN P0-1）：
- 字段与 SPEC §3.1/§13.1/§2.1/§12 一致
- 未知字段拒绝（additionalProperties: false）
- 必填缺失、枚举越界、模式不符、minItems 违例均拒绝
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker, ValidationError

SCHEMA_DIR = Path(__file__).resolve().parent.parent.parent / "contracts" / "schemas"

HASH64 = "a" * 64
HASH64_B = "b" * 64


def load_schema(name: str) -> Draft202012Validator:
    schema = json.loads((SCHEMA_DIR / name).read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema, format_checker=FormatChecker())


@pytest.fixture(scope="module")
def spec_validator():
    return load_schema("eval_spec.v1.json")


@pytest.fixture(scope="module")
def request_validator():
    return load_schema("eval_request.v1.json")


@pytest.fixture(scope="module")
def report_validator():
    return load_schema("eval_report.v1.json")


@pytest.fixture(scope="module")
def evidence_validator():
    return load_schema("evidence.v1.json")


def valid_spec() -> dict:
    return {
        "spec_id": "EVS-20261101-0001",
        "version": "1.0.0",
        "category": "finance",
        "object_type": "strategy",
        "dataset_ref": "DS-binance-btc-1d@1.2.0",
        "split_ref": "SPL-wf5@1.0.0",
        "evaluator_ref": "EV-finance.backtest@1.2.0",
        "scorers": [{"id": "SC-code@1.0.0", "role": "primary"}],
        "thresholds_ref": "TH-2026Q4@1",
        "determinism": {"seed": 42, "temperature": 0.0, "repeats": 1},
        "env_ref": "ENV-manifest-schema@1",
        "created_by": "tester",
        "approved_by": "evaluator-admin",
    }


def valid_request() -> dict:
    return {
        "object_ref": "git://github.com/yunya1991/Dreambuddy-V2.git#abc1234",
        "category": "finance",
        "object_type": "strategy",
        "submitter": "14-V15经典马丁策略",
        "purpose": "l0_settle",
        "priority": "normal",
        "spec_id": "EVS-20261101-0001",
        "env_manifest": {
            "runtime": "python3.12",
            "endpoints": ["https://api.binance.com"],
            "resources": ["pg://fis"],
            "secret_refs": ["BINANCE_API_KEY"],
        },
    }


def valid_report() -> dict:
    return {
        "eval_id": "EV-20261101-000001",
        "run_id": "RUN-20261101-000001-01",
        "spec_hash": HASH64,
        "verdict": "PASS",
        "score": 0.82,
        "n": 120,
        "ci": {"lower": 0.78, "upper": 0.86, "method": "wilson"},
        "items": [
            {
                "name": "F-H1",
                "kind": "hard",
                "status": "PASS",
                "score": None,
                "n": None,
                "ci_lower": None,
                "ci_upper": None,
                "weight": None,
                "evidence_id": "EVD-001",
                "detail": None,
            },
            {
                "name": "F-W3",
                "kind": "weighted",
                "status": "PASS",
                "score": 0.9,
                "n": 120,
                "ci_lower": 0.85,
                "ci_upper": 0.95,
                "weight": 0.35,
                "evidence_id": "EVD-002",
                "detail": "成本×2 稳健",
            },
        ],
        "block_reasons": [],
        "evidence": {"uri": "s3://eval-evidence/EV-20261101-000001.tar.zst", "sha256": HASH64_B},
        "thresholds_version": "TH-2026Q4@1",
        "baseline_run_id": None,
        "baseline_diff": None,
        "sla": {"budget_ms": 1800000, "elapsed_ms": 120000, "degraded": False},
        "evaluated_at": "2026-11-01T12:00:00Z",
        "expires_at": "2026-11-08T12:00:00Z",
    }


def valid_evidence() -> dict:
    return {
        "evidence_id": "EVD-001",
        "run_id": "RUN-20261101-000001-01",
        "sha256": HASH64,
        "uri": "s3://eval-evidence/EVD-001.json",
        "prev_hash": None,
        "hash": HASH64_B,
        "signed_by": None,
        "created_at": "2026-11-01T12:00:00Z",
    }


# ---------------- EvalSpec ----------------


class TestEvalSpec:
    def test_valid_full(self, spec_validator):
        spec_validator.validate(valid_spec())

    def test_valid_minimal_nullable(self, spec_validator):
        doc = valid_spec()
        doc["dataset_ref"] = None
        doc["split_ref"] = None
        doc["env_ref"] = None
        doc["approved_by"] = None
        del doc["determinism"]  # 有默认值，可省略
        spec_validator.validate(doc)

    @pytest.mark.parametrize(
        "field",
        [
            "spec_id",
            "version",
            "category",
            "object_type",
            "evaluator_ref",
            "scorers",
            "thresholds_ref",
            "created_by",
        ],
    )
    def test_missing_required(self, spec_validator, field):
        doc = valid_spec()
        del doc[field]
        with pytest.raises(ValidationError):
            spec_validator.validate(doc)

    def test_unknown_field_rejected(self, spec_validator):
        doc = valid_spec()
        doc["unexpected"] = 1
        with pytest.raises(ValidationError):
            spec_validator.validate(doc)

    def test_bad_category(self, spec_validator):
        doc = valid_spec()
        doc["category"] = "trading"
        with pytest.raises(ValidationError):
            spec_validator.validate(doc)

    def test_bad_spec_id_pattern(self, spec_validator):
        doc = valid_spec()
        doc["spec_id"] = "EVS-2026-1"
        with pytest.raises(ValidationError):
            spec_validator.validate(doc)

    def test_bad_version_pattern(self, spec_validator):
        doc = valid_spec()
        doc["version"] = "v1.0"
        with pytest.raises(ValidationError):
            spec_validator.validate(doc)

    def test_empty_scorers_rejected(self, spec_validator):
        doc = valid_spec()
        doc["scorers"] = []
        with pytest.raises(ValidationError):
            spec_validator.validate(doc)

    def test_scorer_bad_role(self, spec_validator):
        doc = valid_spec()
        doc["scorers"] = [{"id": "SC-code@1.0.0", "role": "judge"}]
        with pytest.raises(ValidationError):
            spec_validator.validate(doc)

    def test_determinism_temperature_out_of_range(self, spec_validator):
        doc = valid_spec()
        doc["determinism"]["temperature"] = 2.5
        with pytest.raises(ValidationError):
            spec_validator.validate(doc)

    def test_evaluator_ref_needs_version(self, spec_validator):
        doc = valid_spec()
        doc["evaluator_ref"] = "EV-finance.backtest"  # 缺 @version
        with pytest.raises(ValidationError):
            spec_validator.validate(doc)


# ---------------- EvalRequest ----------------


class TestEvalRequest:
    def test_valid(self, request_validator):
        request_validator.validate(valid_request())

    @pytest.mark.parametrize(
        "field",
        [
            "object_ref",
            "category",
            "object_type",
            "submitter",
            "purpose",
            "spec_id",
            "env_manifest",
        ],
    )
    def test_missing_required(self, request_validator, field):
        doc = valid_request()
        del doc[field]
        with pytest.raises(ValidationError):
            request_validator.validate(doc)

    def test_unknown_field_rejected(self, request_validator):
        doc = valid_request()
        doc["foo"] = "bar"
        with pytest.raises(ValidationError):
            request_validator.validate(doc)

    def test_env_manifest_missing_endpoints_rejected(self, request_validator):
        """§13.1 受理即拒条件：env_manifest 缺 endpoints"""
        doc = valid_request()
        del doc["env_manifest"]["endpoints"]
        with pytest.raises(ValidationError):
            request_validator.validate(doc)

    def test_env_manifest_empty_endpoints_rejected(self, request_validator):
        doc = valid_request()
        doc["env_manifest"]["endpoints"] = []
        with pytest.raises(ValidationError):
            request_validator.validate(doc)

    def test_bad_purpose(self, request_validator):
        doc = valid_request()
        doc["purpose"] = "experiment"
        with pytest.raises(ValidationError):
            request_validator.validate(doc)

    def test_category_object_type_mismatch_is_business_rule(self, request_validator):
        """类别与 object_type 匹配属于业务规则（categories.yaml），契约层只校验枚举"""
        doc = valid_request()
        doc["category"] = "ai"  # 枚举合法即可通过契约层
        request_validator.validate(doc)


# ---------------- EvalReport ----------------


class TestEvalReport:
    def test_valid_pass(self, report_validator):
        report_validator.validate(valid_report())

    def test_valid_block(self, report_validator):
        doc = valid_report()
        doc["verdict"] = "BLOCK"
        doc["block_reasons"] = ["F-H6 PBO>0.50"]
        report_validator.validate(doc)

    def test_valid_inconclusive(self, report_validator):
        doc = valid_report()
        doc["verdict"] = "INCONCLUSIVE"
        doc["score"] = None
        doc["n"] = None
        doc["ci"] = None
        report_validator.validate(doc)

    @pytest.mark.parametrize(
        "field",
        [
            "eval_id",
            "run_id",
            "spec_hash",
            "verdict",
            "items",
            "block_reasons",
            "evidence",
            "thresholds_version",
            "evaluated_at",
        ],
    )
    def test_missing_required(self, report_validator, field):
        doc = valid_report()
        del doc[field]
        with pytest.raises(ValidationError):
            report_validator.validate(doc)

    def test_unknown_field_rejected(self, report_validator):
        doc = valid_report()
        doc["extra"] = True
        with pytest.raises(ValidationError):
            report_validator.validate(doc)

    def test_score_out_of_range(self, report_validator):
        doc = valid_report()
        doc["score"] = 1.2
        with pytest.raises(ValidationError):
            report_validator.validate(doc)

    def test_bad_verdict(self, report_validator):
        doc = valid_report()
        doc["verdict"] = "UNKNOWN"
        with pytest.raises(ValidationError):
            report_validator.validate(doc)

    def test_bad_spec_hash(self, report_validator):
        doc = valid_report()
        doc["spec_hash"] = "not-a-hash"
        with pytest.raises(ValidationError):
            report_validator.validate(doc)

    def test_bad_evidence_sha256(self, report_validator):
        doc = valid_report()
        doc["evidence"]["sha256"] = "zz" * 32  # 非 hex
        with pytest.raises(ValidationError):
            report_validator.validate(doc)

    def test_item_bad_kind(self, report_validator):
        doc = valid_report()
        doc["items"][0]["kind"] = "soft"
        with pytest.raises(ValidationError):
            report_validator.validate(doc)

    def test_item_missing_status(self, report_validator):
        doc = valid_report()
        del doc["items"][0]["status"]
        with pytest.raises(ValidationError):
            report_validator.validate(doc)

    def test_bad_datetime_format(self, report_validator):
        doc = valid_report()
        doc["evaluated_at"] = "2026-11-01 12:00"
        with pytest.raises(ValidationError):
            report_validator.validate(doc)

    def test_ci_method_enum(self, report_validator):
        doc = valid_report()
        doc["ci"]["method"] = "guess"
        with pytest.raises(ValidationError):
            report_validator.validate(doc)


# ---------------- Evidence ----------------


class TestEvidence:
    def test_valid_genesis(self, evidence_validator):
        evidence_validator.validate(valid_evidence())

    def test_valid_chained(self, evidence_validator):
        doc = valid_evidence()
        doc["prev_hash"] = HASH64_B
        evidence_validator.validate(doc)

    @pytest.mark.parametrize(
        "field",
        ["evidence_id", "run_id", "sha256", "uri", "prev_hash", "hash", "created_at"],
    )
    def test_missing_required(self, evidence_validator, field):
        doc = valid_evidence()
        del doc[field]
        with pytest.raises(ValidationError):
            evidence_validator.validate(doc)

    def test_unknown_field_rejected(self, evidence_validator):
        doc = valid_evidence()
        doc["signature"] = "deadbeef"
        with pytest.raises(ValidationError):
            evidence_validator.validate(doc)

    def test_bad_prev_hash(self, evidence_validator):
        doc = valid_evidence()
        doc["prev_hash"] = "short"
        with pytest.raises(ValidationError):
            evidence_validator.validate(doc)

    def test_hash_must_be_hex64(self, evidence_validator):
        doc = valid_evidence()
        doc["hash"] = "g" * 64
        with pytest.raises(ValidationError):
            evidence_validator.validate(doc)


# ---------------- 元校验：schema 自身合法且拒绝未知字段 ----------------


def test_all_schemas_deny_additional_properties():
    for name in [
        "eval_spec.v1.json",
        "eval_request.v1.json",
        "eval_report.v1.json",
        "evidence.v1.json",
    ]:
        schema = json.loads((SCHEMA_DIR / name).read_text(encoding="utf-8"))
        assert schema.get("additionalProperties") is False, f"{name} 必须拒绝未知字段"
