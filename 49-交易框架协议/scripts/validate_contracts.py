#!/usr/bin/env python3
"""M0-02: validate frozen contract examples against JSON Schemas."""

from __future__ import annotations

import json
from pathlib import Path

CONTRACT_ROOT = Path(__file__).resolve().parents[1]
CONTRACTS_DIR = CONTRACT_ROOT / "contracts"
EXAMPLES_DIR = CONTRACTS_DIR / "examples"

EXAMPLES = [
    ("SignalSchema", "signal_schema.v1.json", "signal_schema.v1.example.json"),
    (
        "FinalDecisionSignal",
        "final_decision_signal.v1.json",
        "final_decision_signal.v1.example.json",
    ),
    (
        "FinalDecisionSignal",
        "final_decision_signal.v1.1.json",
        "final_decision_signal.v1.1.example.json",
    ),
    (
        "MacroElasticConstraint",
        "macro_elastic_constraint.v1.json",
        "macro_elastic_constraint.v1.example.json",
    ),
    (
        "UpperLayerContext",
        "upper_layer_context.v1.json",
        "upper_layer_context.v1.example.json",
    ),
]


def validate_all() -> list[str]:
    try:
        import jsonschema
    except ImportError:
        return ["jsonschema is not installed (pip install jsonschema)"]

    errors: list[str] = []
    for name, schema_file, example_file in EXAMPLES:
        schema = json.loads((CONTRACTS_DIR / schema_file).read_text(encoding="utf-8"))
        example = json.loads((EXAMPLES_DIR / example_file).read_text(encoding="utf-8"))
        try:
            jsonschema.validate(example, schema)
        except jsonschema.ValidationError as exc:
            errors.append(f"{name}: {exc.message} at {list(exc.path)}")
    return errors


def main() -> int:
    errors = validate_all()
    if errors:
        for error in errors:
            print(f"FAIL: {error}")
        return 1
    print(f"OK: {len(EXAMPLES)} contract examples validated")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
