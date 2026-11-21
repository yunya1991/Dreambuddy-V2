"""工作流编排：YAML 步骤 → 依赖顺序 → run ledger → 人工闸门。

支持两种步骤：
- `use: <组件>.<动作>`：调用 59 组件（dry-run 只解析命令，不执行）；
- 其他内置步骤（research.render / site.blog_draft 等）：记为 pending_builtin，交给后续 P1 实现。

用法：
    python3 tools/workflow.py list
    python3 tools/workflow.py show daily-market-brief
    python3 tools/workflow.py run daily-market-brief --dry-run
    python3 tools/workflow.py approve <run_id> <step>
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

import yaml

TOOLS_DIR = Path(__file__).resolve().parent
MODULE_ROOT = TOOLS_DIR.parent
WORKFLOWS_DIR = MODULE_ROOT / "workflows"

if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

import plan  # noqa: E402


def runs_dir() -> Path:
    return plan.state_dir() / "workflows"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_workflow(workflow_id: str) -> Dict[str, Any]:
    path = WORKFLOWS_DIR / "{}.yaml".format(workflow_id)
    if not path.exists():
        raise ValueError("E_WORKFLOW：找不到 {}".format(path))
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict) or not data.get("steps"):
        raise ValueError("E_WORKFLOW：{} 缺少 steps".format(workflow_id))
    return data


def list_workflows() -> List[str]:
    if not WORKFLOWS_DIR.exists():
        return []
    return sorted(path.stem for path in WORKFLOWS_DIR.glob("*.yaml"))


def _run_path(run_id: str) -> Path:
    return runs_dir() / run_id / "run.json"


def _save(state: Dict[str, Any]) -> None:
    path = _run_path(str(state["run_id"]))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _load_run(run_id: str) -> Dict[str, Any]:
    path = _run_path(run_id)
    if not path.exists():
        raise ValueError("E_RUN：找不到运行 {}".format(run_id))
    return json.loads(path.read_text(encoding="utf-8"))


def _split_use(use: str) -> tuple[str, str]:
    if "." not in use:
        return "", use
    component, action = use.split(".", 1)
    if not (MODULE_ROOT / "components" / component / "component.yaml").exists():
        return "", use
    return component, action


def _planned_command(step: Dict[str, Any]) -> str:
    import dreambuddy

    component, action = _split_use(str(step.get("use") or ""))
    if not component:
        return "builtin:{}".format(action)
    comp = dreambuddy.find_component(component)
    script, pre, _safety, _desc, params = dreambuddy.resolve_target(comp, action)
    args = list((step.get("params") or {}).items())
    argv = [sys.executable, str(script)] + list(pre)
    for name, value in args:
        flag = "--" + str(name).replace("_", "-")
        if isinstance(value, bool):
            if value:
                argv.append(flag)
        else:
            argv.extend([flag, str(value)])
    return " ".join(argv)


def _resolve_params(params: Dict[str, Any], context: Dict[str, str]) -> Dict[str, Any]:
    resolved: Dict[str, Any] = {}
    for key, value in (params or {}).items():
        if isinstance(value, str):
            for name, path in context.items():
                value = value.replace("{{{}}}".format(name), path)
        resolved[key] = value
    return resolved


def _out_path(step: Dict[str, Any], run_id: str) -> str:
    out = str(step.get("out") or "")
    if not out:
        return ""
    if os.path.isabs(out):
        return out
    return str(runs_dir() / run_id / "artifacts" / out)


def _run_step(
    step: Dict[str, Any],
    dry_run: bool,
    run_id: str,
    context: Dict[str, str],
) -> Dict[str, Any]:
    import content
    import dreambuddy

    component, action = _split_use(str(step.get("use") or ""))
    params = _resolve_params(step.get("params") or {}, context)
    out = _out_path(step, run_id)
    record: Dict[str, Any] = {
        "use": step.get("use"),
        "status": "pending",
        "started_at": _now(),
    }
    if not component:
        if dry_run:
            record.update(status="planned", command="builtin:{}".format(action))
            return record
        try:
            built = content.run_builtin(action, params, out)
        except content.ContentError as exc:
            record.update(status="failed", detail=str(exc), finished_at=_now())
            return record
        if "pending_builtin" in built or "pending" in built:
            record.update(status="pending_builtin", detail=built)
        else:
            record.update(status="done", detail=built)
        if out:
            record["out"] = out
        record["finished_at"] = _now()
        return record
    args: List[str] = []
    for name, value in params.items():
        flag = "--" + str(name).replace("_", "-")
        if isinstance(value, bool):
            if value:
                args.append(flag)
        else:
            args.extend([flag, str(value)])
    if dry_run:
        record.update(status="planned", command=_planned_command({**step, "params": params}))
        return record
    code = dreambuddy.run_action(
        component,
        action,
        args,
        allow_write=bool(step.get("allow_write")),
        reason=str(step.get("id") or ""),
        stdout_path=out,
    )
    record.update(status="done" if code == 0 else "failed", exit_code=code)
    if out:
        record["out"] = out
    record["finished_at"] = _now()
    return record


def _ready(step: Dict[str, Any], steps: Dict[str, Any]) -> bool:
    for dep in step.get("needs") or []:
        state = steps.get(str(dep)) or {}
        if state.get("status") not in {"done", "planned", "pending_builtin"}:
            return False
    return True


def run(
    workflow_id: str,
    dry_run: bool = False,
    run_id: str = "",
    approve_step: str = "",
    forced_id: str = "",
) -> int:
    workflow = load_workflow(workflow_id)
    if run_id:
        state = _load_run(run_id)
        if approve_step:
            step_state = state["steps"].get(approve_step)
            if not step_state:
                print("E_RUN：步骤不存在 {}".format(approve_step))
                return 2
            step_state["approved_at"] = _now()
            step_state["approved_by"] = os.environ.get("DREAMBUDDY_PRINCIPAL", "local-user")
            state["status"] = "running"
            _save(state)
            plan.audit(
                "workflow.approve",
                run_id=run_id,
                workflow=workflow_id,
                step=approve_step,
            )
    else:
        run_id = forced_id or "{}-{}".format(
            datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
            workflow_id,
        )
        state = {
            "run_id": run_id,
            "workflow": workflow_id,
            "dry_run": dry_run,
            "status": "running",
            "started_at": _now(),
            "steps": {},
        }

    steps: List[Dict[str, Any]] = list(workflow.get("steps") or [])
    context: Dict[str, str] = {
        key: str(value.get("out")) for key, value in state["steps"].items() if value.get("out")
    }
    blocked = False
    progress = True
    while progress:
        progress = False
        for step in steps:
            step_id = str(step.get("id"))
            current = state["steps"].get(step_id)
            if current and current.get("status") in {"done", "planned", "pending_builtin"}:
                continue
            if not _ready(step, state["steps"]):
                continue
            if step.get("human_gate") and not dry_run:
                approved = bool((current or {}).get("approved_at"))
                if not approved:
                    if not current or current.get("status") != "awaiting_approval":
                        state["steps"][step_id] = {
                            "use": step.get("use"),
                            "status": "awaiting_approval",
                            "gate": step.get("human_gate"),
                            "since": _now(),
                        }
                        progress = True
                    blocked = True
                    continue
            state["steps"][step_id] = _run_step(
                step, dry_run=dry_run, run_id=run_id, context=context
            )
            if state["steps"][step_id].get("out"):
                context[step_id] = str(state["steps"][step_id]["out"])
            progress = True

    pending = [
        key
        for key, value in state["steps"].items()
        if value.get("status") not in {"done", "planned", "pending_builtin"}
    ]
    if blocked or pending:
        state["status"] = "awaiting_approval"
    elif any(v.get("status") == "failed" for v in state["steps"].values()):
        state["status"] = "failed"
    else:
        state["status"] = "done"
    state["finished_at"] = _now()
    _save(state)
    print(json.dumps(state, ensure_ascii=False, indent=2))
    return 0 if state["status"] in {"done", "awaiting_approval"} else 1


def main(argv: List[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="59 域工作流编排")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    p_show = sub.add_parser("show")
    p_show.add_argument("workflow")
    p_run = sub.add_parser("run")
    p_run.add_argument("workflow")
    p_run.add_argument("--dry-run", action="store_true")
    p_run.add_argument("--run-id", default="")
    p_approve = sub.add_parser("approve")
    p_approve.add_argument("run_id")
    p_approve.add_argument("step")
    args = parser.parse_args(argv)

    if args.cmd == "list":
        for name in list_workflows():
            print(name)
        return 0
    if args.cmd == "show":
        print(json.dumps(load_workflow(args.workflow), ensure_ascii=False, indent=2))
        return 0
    if args.cmd == "approve":
        state = _load_run(args.run_id)
        return run(
            str(state.get("workflow")),
            dry_run=bool(state.get("dry_run")),
            run_id=args.run_id,
            approve_step=args.step,
        )
    try:
        return run(args.workflow, dry_run=args.dry_run, run_id=args.run_id)
    except ValueError as exc:
        print(str(exc))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
