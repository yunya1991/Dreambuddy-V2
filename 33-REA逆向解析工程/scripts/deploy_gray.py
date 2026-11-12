#!/usr/bin/env python3
"""deploy_gray.py — L2-8B 灰度自动部署的 release_system / 运维调用入口

SPEC-33-G §2.11.4 L2-8 / §2.11.7 / §2.11.8：
  - DeployGate 是唯一闸门，本脚本是它的真实调用入口（避免孤儿模块）
  - 配置来自 `<root>/deploy/gate_config.json`（root 默认 33-REA/policy）；
    配置缺失时按安全默认处理：mode=off（部署被拒）
  - `--dry-run` 只打印 readiness（JSON），不执行任何部署命令
  - 真实执行用 config 的 deploy_cmd / health_cmd / rollback_cmd（数组，禁止 shell=True）

用法:
  python3 scripts/deploy_gray.py --change change.json --shadow-report shadow.json \
      --drill-report drill.json --stage S2 --env gray --dry-run
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, Optional, Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

DEFAULT_ROOT = PROJECT_ROOT / "policy"
DEFAULT_TIMEOUT = 300


def _print(payload: Dict[str, Any]) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))


def _fail(message: str) -> None:
    _print({"status": "error", "error": message})
    raise SystemExit(1)


def _load_json_arg(path: Optional[str], label: str) -> Optional[Dict[str, Any]]:
    if not path:
        return None
    try:
        doc = json.loads(Path(path).read_text(encoding="utf-8"))
    except OSError as exc:
        _fail(f"读取 {label} 失败：{exc}")
    except json.JSONDecodeError as exc:
        _fail(f"{label} 不是合法 JSON：{exc}")
    if not isinstance(doc, dict):
        _fail(f"{label} 顶层必须是 JSON 对象")
    return doc


def _load_config(root: Path) -> Dict[str, Any]:
    path = root / "deploy" / "gate_config.json"
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, json.JSONDecodeError) as exc:
        _fail(f"读取 gate_config.json 失败：{exc}")
    if not isinstance(doc, dict):
        _fail("gate_config.json 顶层必须是对象")
    return doc


def _run(argv: Any, *, timeout: int, label: str) -> int:
    if not isinstance(argv, list) or not argv:
        raise RuntimeError(f"{label} 未配置或不是数组（禁止 shell=True）")
    completed = subprocess.run([str(part) for part in argv], timeout=timeout, check=False)
    return completed.returncode


def _make_functions(config: Dict[str, Any], timeout: int):
    deploy_cmd = config.get("deploy_cmd")
    health_cmd = config.get("health_cmd")
    rollback_cmd = config.get("rollback_cmd")

    def deploy_fn() -> Dict[str, Any]:
        code = _run(deploy_cmd, timeout=timeout, label="deploy_cmd")
        if code != 0:
            raise RuntimeError(f"deploy_cmd 退出码 {code}")
        return {"status": "pass", "returncode": code}

    def health_fn() -> Dict[str, Any]:
        code = _run(health_cmd, timeout=timeout, label="health_cmd")
        return {"status": "pass" if code == 0 else "fail", "returncode": code}

    def rollback_fn(reason: str) -> Dict[str, Any]:
        argv = list(rollback_cmd or []) + ["--reason", reason]
        code = _run(argv, timeout=timeout, label="rollback_cmd")
        if code != 0:
            raise RuntimeError(f"rollback_cmd 退出码 {code}")
        return {"status": "pass", "returncode": code}

    return deploy_fn, health_fn, rollback_fn


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="L2-8B 灰度自动部署入口（DeployGate CLI，灰度 only，生产自动部署非目标）"
    )
    parser.add_argument(
        "--change", required=True, help="change JSON 文件（change_id/files/flags/version/commit）"
    )
    parser.add_argument("--shadow-report", help="影子验证报告 JSON（需 overall=pass）")
    parser.add_argument("--drill-report", help="回滚演练报告 JSON（需 overall=pass + checked_at）")
    parser.add_argument("--stage", choices=["S1", "S2", "S3"], help="三段式当前阶段")
    parser.add_argument("--env", default="gray", help="目标环境（默认 gray）")
    parser.add_argument(
        "--root", default=str(DEFAULT_ROOT), help="policy 根目录（含 deploy/gate_config.json）"
    )
    parser.add_argument("--dry-run", action="store_true", help="只打印 readiness，不执行部署")
    args = parser.parse_args(argv)

    from core.evolution.deploy_gate import DeployBlocked, DeployGate

    root = Path(args.root)
    config = _load_config(root)
    config["env"] = args.env
    gate = DeployGate(root, config=config)

    change = _load_json_arg(args.change, "--change")
    if not isinstance(change, dict):
        _fail("--change 必须是 JSON 对象")
    shadow_report = _load_json_arg(args.shadow_report, "--shadow-report")
    drill_report = _load_json_arg(args.drill_report, "--drill-report")
    change_id = str(change.get("change_id") or Path(args.change).stem).strip()

    if args.dry_run:
        report = gate.readiness(
            change_id=change_id,
            change=change,
            shadow_report=shadow_report,
            drill_report=drill_report,
            stage=args.stage,
        )
        _print(report)
        return 0 if report.get("allowed") else 1

    missing = [
        name
        for name in ("deploy_cmd", "health_cmd", "rollback_cmd")
        if not isinstance(config.get(name), list) or not config.get(name)
    ]
    if missing:
        _fail("gate_config.json 缺少命令配置（数组）：" + ", ".join(missing))

    timeout = int(config.get("deploy_timeout") or DEFAULT_TIMEOUT)
    deploy_fn, health_fn, rollback_fn = _make_functions(config, timeout)
    try:
        result = gate.deploy(
            change_id=change_id,
            change=change,
            deploy_fn=deploy_fn,
            health_fn=health_fn,
            rollback_fn=rollback_fn,
            shadow_report=shadow_report,
            drill_report=drill_report,
            stage=args.stage,
        )
    except DeployBlocked as exc:
        _print({"status": "blocked", "error": str(exc)})
        return 1

    _print(result)
    return 0 if result.get("status") in ("deployed", "simulated") else 3


if __name__ == "__main__":
    raise SystemExit(main())
