#!/usr/bin/env python3
"""G0 绑定门禁（SPEC §6 / contracts/gates.yaml）。

判定：run_id / model_id / phase 非空且合法；phase 必须属于 phases.yaml 的状态枚举。
不依赖 SPEC A/C 产物，可独立运行；FAIL-CLOSED（缺字段即拒开工，0 例外）。

用法：
  python3 .trae/skills/dreamos-dev/scripts/g0_check.py --run .runs/<run_id>/run.json
  python3 .trae/skills/dreamos-dev/scripts/g0_check.py --run-id <run_id>
  echo '<json>' | python3 .../g0_check.py --stdin

输出：单条 JSON 证据（gate / command / exit_code / checks），退出码 0=通过 1=拒绝 2=契约/用法错误。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

CONTRACTS_DIR = Path(__file__).resolve().parents[1] / "contracts"
SCHEMA_PATH = CONTRACTS_DIR / "run.schema.json"
PHASES_PATH = CONTRACTS_DIR / "phases.yaml"

REQUIRED = ("run_id", "model_id", "phase")
SAFE_RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_phases(path: Path) -> dict:
    import yaml  # 延迟导入：缺 pyyaml 时给出明确错误

    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _phase_ids(phases: dict) -> list[str]:
    return [s["id"] for s in phases.get("states", [])]


def _validate_with_jsonschema(payload: dict, schema: dict) -> list[str]:
    try:
        from jsonschema import Draft202012Validator
    except ImportError:  # 退化：只做必填 + 正则 + 枚举
        errors: list[str] = []
        for key in REQUIRED:
            if not payload.get(key):
                errors.append(f"{key}: 必填且非空")
        phase_enum = schema.get("properties", {}).get("phase", {}).get("enum", [])
        if payload.get("phase") and payload["phase"] not in phase_enum:
            errors.append(f"phase: {payload['phase']} 不在枚举 {phase_enum}")
        run_id = payload.get("run_id") or ""
        pattern = schema.get("properties", {}).get("run_id", {}).get("pattern")
        if run_id and pattern and not re.match(pattern, run_id):
            errors.append(f"run_id: {run_id} 不匹配 {pattern}")
        return errors

    validator = Draft202012Validator(schema)
    return [
        f"{'/'.join(str(p) for p in err.absolute_path) or '$'}: {err.message}"
        for err in sorted(validator.iter_errors(payload), key=lambda e: list(e.absolute_path))
    ]


def check(payload: dict) -> tuple[bool, list[dict], str]:
    """返回 (ok, checks, exit_reason)。"""
    checks: list[dict] = []

    schema = _load_json(SCHEMA_PATH)
    phases = _load_phases(PHASES_PATH)

    # 契约自洽：run.schema.json 的 phase 枚举必须与 phases.yaml 严格一致
    declared = schema.get("properties", {}).get("phase", {}).get("enum", [])
    actual = _phase_ids(phases)
    drift = declared != actual
    checks.append(
        {
            "id": "contract_consistency",
            "ok": not drift,
            "detail": (
                "run.schema.json phase 枚举 == phases.yaml states[].id"
                if not drift
                else f"契约漂移：schema={declared} phases={actual}"
            ),
        }
    )

    non_empty = all(str(payload.get(k) or "").strip() for k in REQUIRED)
    missing = [k for k in REQUIRED if not str(payload.get(k) or "").strip()]
    checks.append(
        {
            "id": "binding_present",
            "ok": non_empty,
            "detail": "run_id/model_id/phase 均非空" if non_empty else f"缺失或为空：{missing}",
        }
    )

    errors = _validate_with_jsonschema(payload, schema)
    checks.append(
        {
            "id": "schema_valid",
            "ok": not errors,
            "detail": "通过 run.schema.json" if not errors else "; ".join(errors),
        }
    )

    phase = payload.get("phase")
    phase_ok = phase in actual
    checks.append(
        {
            "id": "phase_legal",
            "ok": phase_ok,
            "detail": f"phase={phase} 合法" if phase_ok else f"phase={phase} 不在 phases.yaml",
        }
    )

    run_id = str(payload.get("run_id") or "")
    run_id_ok = bool(run_id) and bool(SAFE_RUN_ID.match(run_id))
    checks.append(
        {
            "id": "run_id_safe",
            "ok": run_id_ok,
            "detail": f"run_id={run_id} 可安全作为目录名" if run_id_ok else f"run_id={run_id} 非法",
        }
    )

    ok = all(c["ok"] for c in checks)
    reason = "" if ok else "G0 硬拒：绑定不完整或契约不一致，禁止开工"
    return ok, checks, reason


def _read_payload(args: argparse.Namespace) -> tuple[dict | None, str]:
    if args.stdin:
        raw = sys.stdin.read()
        return json.loads(raw), "<stdin>"
    path = Path(args.run) if args.run else Path(".runs") / args.run_id / "run.json"
    if not path.exists():
        return None, f"run 文件不存在：{path}"
    return _load_json(path), str(path)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="G0 绑定门禁")
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--run", help="run.json 路径")
    src.add_argument("--run-id", help="run 标识（解析 .runs/<run_id>/run.json）")
    src.add_argument("--stdin", action="store_true", help="从 stdin 读取 run JSON")
    args = ap.parse_args(argv)

    command = "python3 .trae/skills/dreamos-dev/scripts/g0_check.py " + " ".join(
        f"{k}={v}" for k, v in vars(args).items() if v
    )

    try:
        payload, source = _read_payload(args)
    except json.JSONDecodeError as exc:
        print(
            json.dumps(
                {
                    "gate": "G0",
                    "ok": False,
                    "command": command,
                    "exit_code": 2,
                    "checks": [{"id": "json_parse", "ok": False, "detail": str(exc)}],
                },
                ensure_ascii=False,
            )
        )
        return 2

    if payload is None:
        print(
            json.dumps(
                {
                    "gate": "G0",
                    "ok": False,
                    "command": command,
                    "exit_code": 2,
                    "checks": [{"id": "run_present", "ok": False, "detail": source}],
                },
                ensure_ascii=False,
            )
        )
        return 2

    ok, checks, reason = check(payload)
    result = {
        "gate": "G0",
        "ok": ok,
        "command": command,
        "exit_code": 0 if ok else 1,
        "source": source,
        "run_id": payload.get("run_id"),
        "model_id": payload.get("model_id"),
        "phase": payload.get("phase"),
        "checks": checks,
    }
    if reason:
        result["reason"] = reason
    print(json.dumps(result, ensure_ascii=False))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
