#!/usr/bin/env python3
"""M0-04: validate switch registry against agi_config."""

from __future__ import annotations

import json
import sys
from pathlib import Path

CONTRACT_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = CONTRACT_ROOT.parent
EVOLUTION_ROOT = REPO_ROOT / "23-四层闭环自进化交易架构"
for path in (EVOLUTION_ROOT,):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

REGISTRY_PATH = CONTRACT_ROOT / "docs" / "switch_registry.v1.json"
VALID_KINDS = {"shadow", "promotion"}
VALID_IMPACTS = {"none", "may_change"}


def load_registry() -> dict:
    return json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))


def validate() -> list[str]:
    from dreambuddy_evolution.agi_config import AGI_SWITCHES

    registry = load_registry()
    errors: list[str] = []
    seen: set[str] = set()
    for entry in registry.get("switches", []):
        name = entry.get("name")
        if not name:
            errors.append("missing switch name")
            continue
        if name in seen:
            errors.append(f"duplicate switch: {name}")
        seen.add(name)
        if entry.get("kind") not in VALID_KINDS:
            errors.append(f"{name}: invalid kind {entry.get('kind')!r}")
        if entry.get("production_impact") not in VALID_IMPACTS:
            errors.append(f"{name}: invalid production_impact {entry.get('production_impact')!r}")
        if name not in AGI_SWITCHES:
            errors.append(f"{name}: not registered in AGI_SWITCHES")
        elif bool(AGI_SWITCHES[name]) != bool(entry.get("default")):
            errors.append(
                f"{name}: default mismatch registry={entry.get('default')} "
                f"agi_config={AGI_SWITCHES[name]}"
            )
        if not entry.get("rollback"):
            errors.append(f"{name}: missing rollback action")
    return errors


def main() -> int:
    errors = validate()
    if errors:
        for error in errors:
            print(f"FAIL: {error}")
        return 1
    registry = load_registry()
    print(f"OK: {len(registry['switches'])} switches validated")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
