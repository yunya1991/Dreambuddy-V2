#!/usr/bin/env python3
"""M0-05: rollback drill for contracts and shadow switches.

Checks:
  1. contract manifest SHA256 integrity
  2. every shadow/promotion switch can be toggled and reset
  3. pure shadow switches do not change production baseline
  4. execution_rights sample defaults to paper

Usage:
  python 49-交易框架协议/scripts/rollback_drill.py
  python 49-交易框架协议/scripts/rollback_drill.py --skip-pipeline
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
CONTRACT_ROOT = SCRIPTS_DIR.parent
REPO_ROOT = CONTRACT_ROOT.parent
EVOLUTION_ROOT = REPO_ROOT / "23-四层闭环自进化交易架构"
for path in (SCRIPTS_DIR, EVOLUTION_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

DEFAULT_REPORT = CONTRACT_ROOT / "runtime" / "rollback_drill_report.json"
EXECUTION_RIGHTS_SAMPLE = (
    CONTRACT_ROOT / "contracts" / "examples" / "execution_rights.sample.json"
)

# 只增加诊断字段，不应改变 production。
SHADOW_ONLY_SWITCHES = [
    "enable_cd_shadow",
    "enable_dominance_shadow",
    "enable_event_contradiction_shadow",
    "enable_w6_monitor",
    "enable_self_vote_shadow",
]

# 打开后会改变行为，回滚动作是置回 False；演练只验证默认关闭与可回滚。
PROMOTION_SWITCHES = [
    "enable_primary_contradiction_detector",
    "enable_d2_oi_liq",
    "enable_attention_a_dim",
    "enable_a_dim_c_to_3",
    "enable_self_vote_cap",
]


def _check(check_id: str, passed: bool, **details) -> dict:
    return {"id": check_id, "passed": bool(passed), **details}


def check_contract_integrity() -> dict:
    from freeze_contracts import check_manifest

    checks = check_manifest()
    return _check(
        "contract_integrity",
        all(check["passed"] for check in checks),
        contracts=checks,
    )


def check_switch_rollback() -> dict:
    from dreambuddy_evolution.agi_config import get_switch, reset_switches, set_switch

    reset_switches()
    results = []
    for name in SHADOW_ONLY_SWITCHES + PROMOTION_SWITCHES:
        set_switch(name, True)
        switched_on = get_switch(name, False)
        set_switch(name, False)
        switched_off = get_switch(name, False)
        results.append(
            {"switch": name, "on": switched_on, "off": switched_off,
             "passed": switched_on and not switched_off}
        )
    reset_switches()
    defaults = {
        name: get_switch(name, False)
        for name in SHADOW_ONLY_SWITCHES + PROMOTION_SWITCHES
    }
    passed = all(item["passed"] for item in results) and not any(defaults.values())
    return _check("switch_rollback", passed, switches=results, defaults=defaults)


def check_production_baseline(*, skip_pipeline: bool = False) -> dict:
    import m0_paper_baseline as baseline_mod
    from dreambuddy_evolution.agi_config import reset_switches, set_switch

    mode = "shadow" if skip_pipeline else "auto"
    reset_switches()
    before = baseline_mod._build_baseline(mode=mode, symbol="BTC", seed=42)
    for name in SHADOW_ONLY_SWITCHES:
        set_switch(name, True)
    after = baseline_mod._build_baseline(mode=mode, symbol="BTC", seed=42)
    reset_switches()

    before_production = before.get("production", {})
    after_production = after.get("production", {})
    return _check(
        "production_unchanged_with_shadow_switches",
        before_production == after_production,
        mode=before.get("mode"),
        before=before_production,
        after=after_production,
    )


def check_execution_rights() -> dict:
    try:
        data = json.loads(EXECUTION_RIGHTS_SAMPLE.read_text(encoding="utf-8"))
        defaults = data.get("defaults", {})
        symbols = data.get("symbols", {})
        valid_outcomes = {"paper", "live:11-bypass", "disabled"}
        passed = (
            defaults.get("outcome") == "paper"
            and defaults.get("conflict_policy") == "reject_mcp"
            and all(
                entry.get("outcome") in valid_outcomes
                for entry in symbols.values()
            )
        )
        return _check(
            "execution_rights_default_paper",
            passed,
            sample=str(EXECUTION_RIGHTS_SAMPLE),
            defaults=defaults,
            symbols=symbols,
        )
    except Exception as exc:  # noqa: BLE001
        return _check(
            "execution_rights_default_paper",
            False,
            sample=str(EXECUTION_RIGHTS_SAMPLE),
            error=f"{type(exc).__name__}: {exc}",
        )


def run_drill(*, skip_pipeline: bool = False) -> dict:
    checks = [
        check_contract_integrity(),
        check_switch_rollback(),
        check_production_baseline(skip_pipeline=skip_pipeline),
        check_execution_rights(),
    ]
    return {
        "drill_version": "m0-rollback-drill-v1",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "checks": checks,
        "overall": "pass" if all(check["passed"] for check in checks) else "fail",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="M0-05 rollback drill")
    parser.add_argument("--json-out", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--skip-pipeline", action="store_true")
    args = parser.parse_args()

    report = run_drill(skip_pipeline=args.skip_pipeline)
    args.json_out.parent.mkdir(parents=True, exist_ok=True)
    args.json_out.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    for check in report["checks"]:
        print(f"{'OK' if check['passed'] else 'FAIL'}: {check['id']}")
    print(f"overall={report['overall']} report={args.json_out}")
    return 0 if report["overall"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())