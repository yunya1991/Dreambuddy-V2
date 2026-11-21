"""写动作的两段式审批：propose → approve → execute。

设计约束（SPEC-B §3.2）：
- plan 带 15 分钟 TTL，参数哈希绑定，任何参数变化即失效；
- 无 principal 拒绝创建/批准；
- 所有 propose/approve/execute 落 JSONL 审计。
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List

DEFAULT_TTL = 900


def state_dir() -> Path:
    return Path(os.environ.get("DREAMBUDDY_STATE_DIR", Path.home() / ".local/share/dreambuddy"))


def plans_dir() -> Path:
    return state_dir() / "plans"


def audit_dir() -> Path:
    return state_dir() / "audit"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def args_hash(component: str, action: str, args: List[str], endpoint: str = "") -> str:
    payload = {
        "component": component,
        "action": action,
        "args": [str(item) for item in args],
        "endpoint": endpoint,
    }
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()


def audit(event: str, **fields: Any) -> None:
    audit_dir().mkdir(parents=True, exist_ok=True)
    record = {"event": event, "at": _now().isoformat(), **fields}
    path = audit_dir() / "audit-{}.jsonl".format(_now().strftime("%Y%m%d"))
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")


def create(
    component: str,
    action: str,
    args: List[str],
    principal: str = "",
    endpoint: str = "",
    ttl: int = DEFAULT_TTL,
    risk: str = "write",
) -> Dict[str, Any]:
    if not principal:
        raise ValueError("E_MANDATE：缺少 principal，拒绝创建写计划")
    plan_id = "plan_" + secrets.token_hex(6)
    created = _now()
    payload = {
        "plan_id": plan_id,
        "component": component,
        "action": action,
        "args": [str(item) for item in args],
        "endpoint": endpoint,
        "args_hash": args_hash(component, action, args, endpoint),
        "principal": principal,
        "risk": risk,
        "created_at": created.isoformat(),
        "expires_at": (created + timedelta(seconds=int(ttl))).isoformat(),
    }
    plans_dir().mkdir(parents=True, exist_ok=True)
    (plans_dir() / "{}.json".format(plan_id)).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    audit("plan.create", plan_id=plan_id, principal=principal, action=action, risk=risk)
    return payload


def load(plan_id: str) -> Dict[str, Any]:
    path = plans_dir() / "{}.json".format(plan_id)
    if not path.exists():
        raise ValueError("E_PLAN：找不到计划 {}".format(plan_id))
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("E_PLAN：计划格式损坏 {}".format(plan_id))
    return data


def approve(plan_id: str, principal: str = "") -> Dict[str, Any]:
    if not principal:
        raise ValueError("E_MANDATE：缺少 principal，拒绝批准写计划")
    plan = load(plan_id)
    if plan.get("principal") != principal:
        raise ValueError("E_MANDATE：principal 与计划不一致")
    expires = datetime.fromisoformat(str(plan.get("expires_at")))
    if _now() > expires:
        audit("plan.reject", plan_id=plan_id, principal=principal, reason="expired")
        raise ValueError("E_PLAN：计划已过期（{}）".format(plan.get("expires_at")))
    expected = args_hash(
        str(plan.get("component")),
        str(plan.get("action")),
        list(plan.get("args") or []),
        str(plan.get("endpoint") or ""),
    )
    if expected != plan.get("args_hash"):
        audit("plan.reject", plan_id=plan_id, principal=principal, reason="hash_mismatch")
        raise ValueError("E_PLAN：参数哈希不一致，计划已失效")
    audit("plan.approve", plan_id=plan_id, principal=principal, action=plan.get("action"))
    return plan


def pending() -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    if not plans_dir().exists():
        return items
    for path in sorted(plans_dir().glob("plan_*.json")):
        try:
            items.append(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            continue
    return items


def main(argv: List[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="写动作计划（propose/approve）")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_create = sub.add_parser("create", help="创建计划")
    p_create.add_argument("component")
    p_create.add_argument("action")
    p_create.add_argument("args", nargs="*")
    p_create.add_argument("--principal", default=os.environ.get("DREAMBUDDY_PRINCIPAL", ""))
    p_create.add_argument("--endpoint", default="")
    sub.add_parser("list", help="列出未执行计划")
    args = parser.parse_args(argv)
    if args.cmd == "list":
        for plan in pending():
            print(
                "{}  {}.{}  {}  expires={}".format(
                    plan.get("plan_id"),
                    plan.get("component"),
                    plan.get("action"),
                    " ".join(plan.get("args") or []),
                    plan.get("expires_at"),
                )
            )
        return 0
    try:
        plan = create(
            args.component,
            args.action,
            list(args.args),
            principal=args.principal,
            endpoint=args.endpoint,
        )
    except ValueError as exc:
        print(str(exc))
        return 3
    print(json.dumps(plan, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
