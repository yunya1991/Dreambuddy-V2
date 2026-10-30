#!/usr/bin/env python3
"""模块租约（Module Lease）工具 — 双端研发互斥。

SPEC: 44-三端协作架构系统/docs/tech/SPEC-dual-end-collab-governance.md §三

用法：
  lease.py claim   --module M --end local|cloud --role dev|test|review --task T [--session S] [--ttl 24]
  lease.py release --module M --task T
  lease.py status  [--module M]
  lease.py check   --module M --end E --role R --task T      # 本地预检（不写入）
  lease.py check-pr --json pr_context.json                    # CI 调用

退出码：0 SAFE / 2 CONFLICT 或 INPUT_ERROR
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
DOC_ROOT = "44-三端协作架构系统"
DEFAULT_LEASE_DIR = REPO_ROOT / DOC_ROOT / "github" / "leases"
END_ENUM = {"local", "cloud"}
ROLE_ENUM = {"dev", "test", "review"}
MAX_TTL_HOURS = 72


def lease_dir() -> Path:
    return Path(os.environ.get("DREAM_LEASE_DIR", DEFAULT_LEASE_DIR))


def now() -> datetime:
    return datetime.now(timezone.utc)


def module_slug(module: str) -> str:
    return module.replace(":", "__").replace("/", "__").replace(os.sep, "__") + ".json"


def module_for_path(path: str) -> str:
    """把仓库内文件路径映射为模块 ID（SPEC §3.1）。"""
    p = path.replace("\\", "/")
    if p.startswith("./"):
        p = p[2:]
    if p.startswith(f"{DOC_ROOT}/github/leases/"):
        return "lease"
    if p.startswith(f"{DOC_ROOT}/docs/"):
        return "docs:" + p[len(f"{DOC_ROOT}/docs/") :]
    if p.startswith(f"{DOC_ROOT}/review/"):
        return "review:" + p[len(f"{DOC_ROOT}/review/") :]
    if p.startswith(".github/"):
        return "root:ci"
    if "/" not in p:
        return "root:repo"
    return p.split("/", 1)[0]


def _read(module: str) -> dict:
    f = lease_dir() / module_slug(module)
    if not f.exists():
        return {"schema_version": "1.0", "module": module, "leases": []}
    return json.loads(f.read_text(encoding="utf-8"))


def _write(module: str, data: dict) -> None:
    d = lease_dir()
    d.mkdir(parents=True, exist_ok=True)
    f = d / module_slug(module)
    tmp = f.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(f)


def _expired(lease: dict) -> bool:
    started = datetime.fromisoformat(lease["started_at"])
    return now() > started + timedelta(hours=lease.get("ttl_hours", 24))


def _status(lease: dict) -> str:
    if lease.get("status") != "active":
        return lease.get("status", "released")
    return "expired" if _expired(lease) else "active"


def active_leases(module: str) -> list[dict]:
    return [x for x in _read(module)["leases"] if _status(x) == "active"]


def evaluate(module: str, end: str, role: str, task: str, session: str | None) -> tuple[bool, str]:
    """R1-R7 判定。返回 (是否可授予, 原因)。"""
    if role not in ROLE_ENUM:
        return False, f"role 非法：{role}"
    if end not in END_ENUM:
        return False, f"end 非法：{end}"
    if not module or not task:
        return False, "module/task 不能为空"

    # R8 终审权归云端：review/approved 只能由云端评审方写入（云端最贴近生产环境）
    if module.startswith("review:approved/") and end != "cloud":
        return False, f"R8 冲突：文档终审（review/approved）仅限云端（end=cloud），当前 end={end}"

    leases = _read(module)["leases"]
    active = [x for x in leases if _status(x) == "active"]

    same = [
        x
        for x in active
        if x["role"] == role
        and x["task_id"] == task
        and x["end"] == end
        and (session is None or x.get("session") == session)
    ]
    if same:
        return True, "已持有，按续期处理"

    if role == "dev":
        others = [x for x in active if x["role"] == "dev"]
        if others:
            o = others[0]
            return False, f"R1 冲突：模块已被 {o['end']} 持有 dev 租约（task={o['task_id']}）"
    else:
        dev_same_task = [
            x
            for x in leases
            if x["role"] == "dev" and x["task_id"] == task and _status(x) in {"active", "released"}
        ]
        if role == "test":
            if not dev_same_task:
                return False, "R2 冲突：task 没有对应的 dev 租约（active 或已释放）可继承"
        if dev_same_task:
            d = dev_same_task[-1]
            same_end = d["end"] == end
            same_session = (d.get("session") or "") == (session or "")
            if same_end and same_session:
                return False, f"R4 冲突：与 dev 同一端同一会话（{end}/{session}），禁止自审自测"
            if same_end and not session:
                return False, "R4 冲突：同端评审须显式指定独立的 --session"

    if module.startswith("root:"):
        others = [x for x in active if x["role"] != role or x["task_id"] != task]
        if others:
            o = others[0]
            return (
                False,
                f"R7 冲突：{module} 已被 {o['end']}/{o['role']} 持有（task={o['task_id']}）",
            )

    return True, "SAFE"


def cmd_claim(args) -> int:
    ttl = args.ttl
    if ttl <= 0 or ttl > MAX_TTL_HOURS:
        print(f"BLOCK  TTL 必须在 1..{MAX_TTL_HOURS} 小时")
        return 2
    ok, why = evaluate(args.module, args.end, args.role, args.task, args.session)
    if not ok:
        print(f"BLOCK  {why}")
        return 2

    data = _read(args.module)
    existing = next(
        (
            x
            for x in data["leases"]
            if x["role"] == args.role
            and x["task_id"] == args.task
            and x["end"] == args.end
            and x.get("session") == args.session
            and _status(x) == "active"
        ),
        None,
    )
    if existing:
        existing["ttl_hours"] = ttl
    else:
        data["leases"].append(
            {
                "end": args.end,
                "role": args.role,
                "task_id": args.task,
                "session": args.session,
                "base_sha": args.base_sha,
                "started_at": now().astimezone().isoformat(timespec="seconds"),
                "ttl_hours": ttl,
                "status": "active",
                "released_at": None,
            }
        )
    _write(args.module, data)
    print(
        f"SAFE   租约已授予：{args.module} / {args.end} / {args.role} / {args.task}（TTL {ttl}h）"
    )
    return 0


def cmd_release(args) -> int:
    data = _read(args.module)
    hit = None
    for x in data["leases"]:
        if x["task_id"] == args.task and _status(x) == "active":
            hit = x
    if not hit:
        print("BLOCK  未找到匹配的 active 租约")
        return 2
    hit["status"] = "released"
    hit["released_at"] = now().astimezone().isoformat(timespec="seconds")
    _write(args.module, data)
    print(f"SAFE   已释放：{args.module} / {hit['role']} / {args.task}")
    return 0


def cmd_status(args) -> int:
    d = lease_dir()
    files = sorted(d.glob("*.json")) if d.exists() else []
    rows = []
    for f in files:
        data = json.loads(f.read_text(encoding="utf-8"))
        if args.module and data.get("module") != args.module:
            continue
        for x in data.get("leases", []):
            rows.append(
                (
                    data.get("module"),
                    x["end"],
                    x["role"],
                    x["task_id"],
                    x.get("session") or "-",
                    _status(x),
                    x["started_at"],
                )
            )
    if not rows:
        print("（无租约记录）")
        return 0
    print(f"{'MODULE':32} {'END':6} {'ROLE':7} {'TASK':20} {'SESSION':16} {'STATUS':9} STARTED")
    for m, e, r, t, s, st, sa in rows:
        print(f"{str(m)[:32]:32} {e:6} {r:7} {t[:20]:20} {s[:16]:16} {st:9} {sa}")
    return 0


def cmd_check(args) -> int:
    ok, why = evaluate(args.module, args.end, args.role, args.task, args.session)
    print(("SAFE   " if ok else "BLOCK  ") + why)
    return 0 if ok else 2


def _check_files(
    files: list[str], end: str, role: str, task: str, session: str | None
) -> list[str]:
    errors = []
    modules = []
    for p in files:
        m = module_for_path(p)
        if m not in modules:
            modules.append(m)
    for m in modules:
        if m == "lease":
            continue
        ok, why = evaluate(m, end, role, task, session)
        if not ok:
            errors.append(f"{m}: {why}")
            continue
        held = [
            x
            for x in active_leases(m)
            if x["role"] == role
            and x["task_id"] == task
            and x["end"] == end
            and (session is None or x.get("session") == session)
        ]
        if not held:
            errors.append(f"{m}: 未持有效租约（{end}/{role}/{task}）")
    return errors


def cmd_check_pr(args) -> int:
    ctx = json.loads(Path(args.json).read_text(encoding="utf-8"))
    branch = (ctx.get("branch") or "").strip()
    body = ctx.get("body") or ""
    files = ctx.get("files") or []

    if branch.startswith("hotfix/"):
        print(f"SAFE   hotfix 分支免租约（{branch}），需 24h 内补审")
        return 0

    modules = sorted({module_for_path(p) for p in files})
    if modules == ["lease"]:
        print("SAFE   仅改动租约文件，豁免本门禁")
        return 0

    def field(name: str) -> str:
        for line in body.splitlines():
            if line.strip().startswith(name):
                return line.split(":", 1)[1].strip() if ":" in line else ""
        return ""

    task, end, role = field("Task ID"), field("端"), field("角色")
    session = field("会话") or None
    if not task or not end or not role:
        print("BLOCK  PR 描述缺少 [协作 PR] 四项（Task ID/端/角色/模块）")
        return 2

    if f"@{end}" not in branch:
        print(f"BLOCK  分支名须为 feat/<task-id>@{end}，实际：{branch}")
        return 2

    if args.identities and Path(args.identities).exists():
        table = json.loads(Path(args.identities).read_text(encoding="utf-8"))
        email = (ctx.get("author_email") or "").lower()
        allowed = [e.lower() for e in table.get(end, [])]
        if allowed and email not in allowed:
            print(f"BLOCK  提交身份 {email or '(空)'} 与声明端 {end} 不匹配")
            return 2

    errors = _check_files(files, end, role, task, session)
    if errors:
        for e in errors:
            print("BLOCK  " + e)
        return 2
    print(f"SAFE   {task} / {end} / {role}：{len(files)} 个文件全部被租约覆盖")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="模块租约工具")
    sub = p.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("claim")
    c.add_argument("--module", required=True)
    c.add_argument("--end", required=True)
    c.add_argument("--role", required=True)
    c.add_argument("--task", required=True)
    c.add_argument("--session", default=None)
    c.add_argument("--ttl", type=int, default=24)
    c.add_argument("--base-sha", default=None)
    c.set_defaults(func=cmd_claim)

    r = sub.add_parser("release")
    r.add_argument("--module", required=True)
    r.add_argument("--task", required=True)
    r.set_defaults(func=cmd_release)

    s = sub.add_parser("status")
    s.add_argument("--module", default=None)
    s.set_defaults(func=cmd_status)

    k = sub.add_parser("check")
    for a in ("module", "end", "role", "task"):
        k.add_argument(f"--{a}", required=True)
    k.add_argument("--session", default=None)
    k.set_defaults(func=cmd_check)

    cp = sub.add_parser("check-pr")
    cp.add_argument("--json", required=True)
    cp.add_argument("--identities", default=None)
    cp.set_defaults(func=cmd_check_pr)
    return p


def main() -> int:
    args = build_parser().parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
