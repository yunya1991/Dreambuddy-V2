"""M0-02 contract freeze tests."""

from __future__ import annotations

import json

import pytest
from freeze_contracts import CONTRACTS_DIR, check_manifest
from validate_contracts import validate_all


class TestContracts:
    def test_examples_validate(self):
        assert validate_all() == []

    def test_manifest_integrity(self):
        checks = check_manifest()
        assert len(checks) == 5
        assert all(check["passed"] for check in checks)

    def test_v11_accepts_50_nn(self):
        import jsonschema

        schema = json.loads(
            (CONTRACTS_DIR / "final_decision_signal.v1.1.json").read_text(encoding="utf-8")
        )
        example = json.loads(
            (CONTRACTS_DIR / "examples" / "final_decision_signal.v1.1.example.json").read_text(
                encoding="utf-8"
            )
        )
        example["source"] = "50-nn"
        jsonschema.validate(example, schema)

    def test_v1_rejects_50_nn(self):
        import jsonschema

        schema = json.loads(
            (CONTRACTS_DIR / "final_decision_signal.v1.json").read_text(encoding="utf-8")
        )
        example = json.loads(
            (CONTRACTS_DIR / "examples" / "final_decision_signal.v1.example.json").read_text(
                encoding="utf-8"
            )
        )
        example["source"] = "50-nn"
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(example, schema)

    def test_missing_required_field_fails(self):
        import jsonschema

        schema = json.loads((CONTRACTS_DIR / "signal_schema.v1.json").read_text(encoding="utf-8"))
        example = json.loads(
            (CONTRACTS_DIR / "examples" / "signal_schema.v1.example.json").read_text(
                encoding="utf-8"
            )
        )
        example.pop("signal_id")
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(example, schema)
