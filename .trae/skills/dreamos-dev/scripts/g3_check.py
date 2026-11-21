#!/usr/bin/env python3
"""G3 执行越界门禁（SPEC §6 / contracts/gates.yaml）。

判定：本次改动必须 ⊆ run.task.scope（影响面白名单）；越界即停。
来源优先级：--changes（changes.json 的 files）> git status --porcelain。

用法：
  python3 .trae/skills/dreamos-dev/scripts/g3_check.py --run .runs/<run_id>/run.json
  python3 .trae/skills/dreamos-dev/scripts/g3_check.py --run-id <run_id> --changes .runs/<run_id>/changes.json
  python3 .../g3_check.py --run ... --files src/a.ts src/b.ts   # 显式传改动清单

输出：单条 JSON 证据，退出码 0=未越界 1=越界/scope 未声明 2=用法或解析错误。
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import subprocess
import sys
from pathlib import Path


def _repo_root(start: Path) -> Path:
    for candidate in [start, *start.parents]:
        if (candidate / ".git").exists():
            return candidate
    return start


def _git_changed_files(root: Path) -> list[str]:
    out = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    if out.returncode != 0:
        raise RuntimeError(f"git status 失败：{out.stderr.strip()}")
    files: list[str] = []
    for line in out.stdout.splitlines():
        if len(line) < 4:
            continue
        path = line[3:]
        if " -> " in path:  # 重命名：取新路径
            path = path.split(" -> ", 1)[1]
        files.append(path.strip().strip('"'))
    return sorted(set(files))


def _matches(path: str, scope: list[str]) -> bool:
    for entry in scope:
        entry = str(entry)
        if entry in ("*", "**", "./"):
            return True
        normalized = entry[2:] if entry.startswith("./") else entry
        if normalized.endswith("/"):
            if path.startswith(normalized):
                return True
        elif path == normalized or path.startswith(normalized + "/"):
            return True
        elif fnmatch.fnmatch(path, normalized):
            return True
    return False


def check(run: dict, files: list[str]) -> tuple[bool, list[dict], dict]:
    scope = list((run.get("task") or {}).get("scope") or [])
    if not scope:
        return (
            False,
            [
                {
                    "id": "scope_declared",
                    "ok": False,
                    "detail": "run.task.scope 为空：影响面未声明，G3 无法判定（FAIL-CLOSED）",
                }
            ],
            {"violations": files, "changed_count": len(files), "scope": scope},
        )

    violations = [f for f in files if not _matches(f, scope)]
    checks = [
        {"id": "scope_declared", "ok": True, "detail": f"scope={scope}"},
        {
            "id": "changes_within_scope",
            "ok": not violations,
            "detail": (
                f"{len(files)} 个改动全部在影响面内"
                if not violations
                else f"越界 {len(violations)} 个：{violations}"
            ),
        },
    ]
    return (
        not violations,
        checks,
        {
            "violations": violations,
            "changed_count": len(files),
            "scope": scope,
        },
    )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="G3 执行越界门禁")
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--run", help="run.json 路径")
    src.add_argument("--run-id", help="run 标识（解析 .runs/<run_id>/run.json）")
    ap.add_argument("--changes", help="changes.json 路径（含 files 数组）")
    ap.add_argument("--files", nargs="*", help="显式改动清单，优先于 git status")
    ap.add_argument("--repo-root", help="仓库根，默认向上查找 .git")
    args = ap.parse_args(argv)

    run_path = Path(args.run) if args.run else Path(".runs") / args.run_id / "run.json"
    if not run_path.exists():
        print(
            json.dumps(
                {
                    "gate": "G3",
                    "ok": False,
                    "exit_code": 2,
                    "checks": [
                        {"id": "run_present", "ok": False, "detail": f"run 文件不存在：{run_path}"}
                    ],
                },
                ensure_ascii=False,
            )
        )
        return 2
    run = json.loads(run_path.read_text(encoding="utf-8"))

    root = Path(args.repo_root) if args.repo_root else _repo_root(Path.cwd())
    if args.files:
        files = sorted(set(args.files))
        source = "--files"
    elif args.changes:
        changes_path = Path(args.changes)
        if not changes_path.exists():
            print(
                json.dumps(
                    {
                        "gate": "G3",
                        "ok": False,
                        "exit_code": 2,
                        "checks": [
                            {
                                "id": "changes_present",
                                "ok": False,
                                "detail": f"changes 文件不存在：{changes_path}",
                            }
                        ],
                    },
                    ensure_ascii=False,
                )
            )
            return 2
        changes = json.loads(changes_path.read_text(encoding="utf-8"))
        files = sorted(set(changes.get("files") or []))
        source = str(changes_path)
    else:
        files = _git_changed_files(root)
        source = "git status --porcelain"

    ok, checks, stats = check(run, files)
    command = "python3 .trae/skills/dreamos-dev/scripts/g3_check.py --run " + str(run_path)
    print(
        json.dumps(
            {
                "gate": "G3",
                "ok": ok,
                "command": command,
                "exit_code": 0 if ok else 1,
                "source": source,
                "run_id": run.get("run_id"),
                "stats": stats,
                "checks": checks,
                "reason": "" if ok else "G3 停：改动越界或影响面未声明",
            },
            ensure_ascii=False,
        )
    )
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
