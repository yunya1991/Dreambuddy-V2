#!/usr/bin/env python3
"""M0-02: freeze or verify the four trading contracts.

Usage:
  python 49-交易框架协议/scripts/freeze_contracts.py --write
  python 49-交易框架协议/scripts/freeze_contracts.py --check
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

CONTRACT_ROOT = Path(__file__).resolve().parents[1]
CONTRACTS_DIR = CONTRACT_ROOT / "contracts"
MANIFEST_PATH = CONTRACTS_DIR / "contract_manifest.v1.json"

CONTRACTS = [
    ("SignalSchema", "v1", "signal_schema.v1.json"),
    ("FinalDecisionSignal", "v1", "final_decision_signal.v1.json"),
    ("FinalDecisionSignal", "v1.1", "final_decision_signal.v1.1.json"),
    ("MacroElasticConstraint", "v1", "macro_elastic_constraint.v1.json"),
    ("UpperLayerContext", "v1", "upper_layer_context.v1.json"),
]

CHANGE_POLICY = (
    "v1 required fields are frozen; additive optional fields require a manifest "
    "update + ADR; breaking changes require v2 + ADR"
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()


def write_manifest(
    spec_version: str = "v0.11", manifest_version: str = "contract-freeze-v1"
) -> dict:
    payload = {
        "manifest_version": manifest_version,
        "spec_version": spec_version,
        "frozen_at": datetime.now(timezone.utc).isoformat(),
        "change_policy": CHANGE_POLICY,
        "contracts": [
            {
                "name": name,
                "version": version,
                "file": filename,
                "status": "frozen",
                "sha256": sha256_file(CONTRACTS_DIR / filename),
            }
            for name, version, filename in CONTRACTS
        ],
    }
    MANIFEST_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def check_manifest() -> list[dict]:
    if not MANIFEST_PATH.exists():
        return [
            {
                "contract": name,
                "file": filename,
                "passed": False,
                "reason": "manifest missing",
            }
            for name, _, filename in CONTRACTS
        ]
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    entries = {entry.get("file"): entry for entry in manifest.get("contracts", [])}
    checks = []
    for name, version, filename in CONTRACTS:
        entry = entries.get(filename)
        actual = sha256_file(CONTRACTS_DIR / filename)
        expected = entry.get("sha256") if entry else None
        passed = (
            entry is not None
            and entry.get("name") == name
            and entry.get("version") == version
            and entry.get("status") == "frozen"
            and actual == expected
        )
        checks.append(
            {
                "contract": name,
                "version": version,
                "file": filename,
                "expected": expected,
                "actual": actual,
                "passed": passed,
            }
        )
    return checks


def main() -> int:
    parser = argparse.ArgumentParser(description="Freeze/check trading contracts")
    parser.add_argument("--write", action="store_true", help="write manifest")
    parser.add_argument("--check", action="store_true", help="verify manifest")
    parser.add_argument("--spec-version", default="v0.11")
    parser.add_argument("--manifest-version", default="contract-freeze-v1")
    args = parser.parse_args()

    if args.write:
        payload = write_manifest(args.spec_version, args.manifest_version)
        print(f"Manifest written: {MANIFEST_PATH}")
        print(f"contracts={len(payload['contracts'])} frozen_at={payload['frozen_at']}")
        return 0

    checks = check_manifest()
    failed = [check for check in checks if not check["passed"]]
    for check in checks:
        status = "OK" if check["passed"] else "FAIL"
        print(f"{status}: {check['contract']} ({check['file']})")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
