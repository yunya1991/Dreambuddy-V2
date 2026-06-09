#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
dual-agent-conflict-gate — 双代理协作冲突前置门禁
Version: 1.0
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

CONFIG_PATH = Path(__file__).parent.parent / "gatekeeper_config.json"


# ── helpers ──────────────────────────────────────────────────────────────────

def load_config() -> dict:
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return json.load(f)


def git_current_branch() -> str:
    try:
        result = subprocess.run(
            ["git", "branch", "--show-current"],
            capture_output=True, text=True, check=True
        )
        return result.stdout.strip()
    except subprocess.CalledProcessError:
        return ""


def git_status() -> dict[str, list[str]]:
    """Return modified / staged / untracked file lists from git status --porcelain."""
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True, text=True, check=True
        )
    except subprocess.CalledProcessError:
        return {"modified_files": [], "staged_files": [], "untracked_files": []}

    modified, staged, untracked = [], [], []
    for line in result.stdout.splitlines():
        if len(line) < 3:
            continue
        xy, path = line[:2], line[3:].strip()
        x, y = xy[0], xy[1]
        if x == "?" and y == "?":
            untracked.append(path)
        else:
            if x != " " and x != "?":
                staged.append(path)
            if y != " " and y != "?":
                modified.append(path)

    return {
        "modified_files": sorted(set(modified)),
        "staged_files": sorted(set(staged)),
        "untracked_files": sorted(set(untracked)),
    }


def milestone_has_unmerged(cfg: dict) -> bool:
    """Check if any milestone/* branch has commits not merged into current branch."""
    pattern = cfg["branch_rules"]["milestone_pattern"]
    try:
        result = subprocess.run(
            ["git", "branch", "-r"],
            capture_output=True, text=True, check=True
        )
        milestone_branches = [
            b.strip() for b in result.stdout.splitlines()
            if pattern in b
        ]
        for branch in milestone_branches:
            check = subprocess.run(
                ["git", "log", f"{branch}..HEAD", "--oneline"],
                capture_output=True, text=True
            )
            if check.stdout.strip():
                return True
    except subprocess.CalledProcessError:
        pass
    return False


def path_in_domain(file_path: str, domain_list: list[str]) -> bool:
    for domain in domain_list:
        if file_path.startswith(domain):
            return True
    return False


def opponent(agent_id: str) -> str:
    return "solo" if agent_id == "claude" else "claude"


# ── core checks ──────────────────────────────────────────────────────────────

def check_branch(agent_id: str, branch: str, cfg: dict) -> list[dict]:
    issues = []
    rules = cfg["branch_rules"]
    expected_prefix = rules[f"{agent_id}_pattern"]
    protected = rules["protected"]
    milestone_prefix = rules["milestone_pattern"]

    if branch in protected:
        issues.append({
            "code": "WRONG_BRANCH",
            "level": "BLOCK",
            "detail": f"当前在受保护分支 '{branch}'，不允许直接提交。请切换到 agent/{agent_id}/* 分支。"
        })
    elif branch.startswith(milestone_prefix):
        issues.append({
            "code": "WRONG_BRANCH",
            "level": "BLOCK",
            "detail": f"当前在里程碑分支 '{branch}'，agent 不应直接在此工作。请切换到 {expected_prefix}* 分支。"
        })
    elif not branch.startswith(expected_prefix):
        issues.append({
            "code": "WRONG_BRANCH",
            "level": "BLOCK",
            "detail": f"当前分支 '{branch}' 不符合 {agent_id} 的命名规范（应以 '{expected_prefix}' 开头）。"
        })
    return issues


def check_file_boundaries(
    agent_id: str,
    files_to_modify: list[str],
    git_snap: dict,
    cfg: dict,
) -> list[dict]:
    issues = []
    other = opponent(agent_id)
    other_domain = cfg["ownership"].get(other, [])
    shared_approval = cfg["shared_requires_approval"]

    all_dirty = set(git_snap["modified_files"] + git_snap["staged_files"])

    for f in files_to_modify:
        # 对方主责域
        if path_in_domain(f, other_domain):
            issues.append({
                "code": "BOUNDARY_VIOLATION",
                "level": "BLOCK",
                "detail": f"文件 '{f}' 属于 {other} 主责域，{agent_id} 不得直接修改。"
            })
        # 共享文件 — 检查是否已有脏状态
        elif any(f.startswith(s) or f == s for s in shared_approval):
            if f in all_dirty:
                issues.append({
                    "code": "SHARED_FILE_CONFLICT",
                    "level": "BLOCK",
                    "detail": f"共享文件 '{f}' 当前有未提交修改，存在占用冲突。"
                })
            else:
                issues.append({
                    "code": "SHARED_FILE_CONFLICT",
                    "level": "WARNING",
                    "detail": f"文件 '{f}' 属于需申请的共享文件，请确认已在任务板中登记占用。"
                })

    # git dirty 文件中是否有对方主责域文件（对方正在修改）
    for dirty_file in all_dirty:
        if path_in_domain(dirty_file, other_domain) and dirty_file in files_to_modify:
            issues.append({
                "code": "BOUNDARY_VIOLATION",
                "level": "BLOCK",
                "detail": f"git 检测到 '{dirty_file}' 已被修改且属于 {other} 主责域——存在覆盖风险。"
            })

    return issues


def check_contracts(contracts_depended: list[str], cfg: dict) -> list[dict]:
    issues = []
    registry = cfg.get("contracts", {})

    for contract in contracts_depended:
        if contract not in registry:
            issues.append({
                "code": "CONTRACT_NOT_FROZEN",
                "level": "BLOCK",
                "detail": f"契约 '{contract}' 未在注册表中，尚未达到 L1 冻结级别，不具备并行依赖条件。"
            })
        else:
            level = registry[contract].get("level", "L0")
            if level == "L0":
                issues.append({
                    "code": "CONTRACT_LEVEL_L0",
                    "level": "WARNING",
                    "detail": f"契约 '{contract}' 当前为 L0（临时），不建议作为并行开发依据。"
                })

    return issues


def check_parallel_conditions(
    agent_id: str,
    files_to_modify: list[str],
    contracts_depended: list[str],
    git_snap: dict,
    cfg: dict,
) -> list[dict]:
    """三条并行条件综合判断（仅在前面无 BLOCK 时补充）。"""
    issues = []
    other = opponent(agent_id)
    other_domain = cfg["ownership"].get(other, [])
    all_dirty = set(git_snap["modified_files"] + git_snap["staged_files"])
    registry = cfg.get("contracts", {})

    # 条件1: 文件边界
    boundary_ok = not any(path_in_domain(f, other_domain) for f in files_to_modify)

    # 条件2: 契约达到 L1
    contracts_ok = all(
        registry.get(c, {}).get("level", "L0") in ("L1", "L2")
        for c in contracts_depended
    ) if contracts_depended else True

    # 条件3: 无同文件依赖（本次要改的文件未被对方 dirty）
    no_same_file = not any(
        f in all_dirty and path_in_domain(f, other_domain)
        for f in files_to_modify
    )

    if not (boundary_ok and contracts_ok and no_same_file):
        failed = []
        if not boundary_ok:
            failed.append("文件边界不清")
        if not contracts_ok:
            failed.append("输入输出契约未冻结")
        if not no_same_file:
            failed.append("存在同文件依赖")
        issues.append({
            "code": "PARALLEL_CONDITION_FAILED",
            "level": "BLOCK",
            "detail": f"并行三条件不满足：{', '.join(failed)}。"
        })

    return issues


# ── decision aggregation ─────────────────────────────────────────────────────

def aggregate(issues: list[dict]) -> dict[str, Any]:
    if not issues:
        return {"decision": "SAFE", "reason_codes": [], "conflict_details": []}

    has_block = any(i["level"] == "BLOCK" for i in issues)
    decision = "BLOCK" if has_block else "WARNING"

    reason_codes = list(dict.fromkeys(i["code"] for i in issues))
    conflict_details = [i["detail"] for i in issues]

    action_parts = []
    if has_block:
        block_items = [i for i in issues if i["level"] == "BLOCK"]
        if any(i["code"] == "WRONG_BRANCH" for i in block_items):
            action_parts.append("切换到正确的 agent/* 分支后重新检查。")
        if any(i["code"] == "BOUNDARY_VIOLATION" for i in block_items):
            action_parts.append("联系 SOLO 重新划定文件边界或等待对方完成修改。")
        if any(i["code"] in ("CONTRACT_NOT_FROZEN", "PARALLEL_CONDITION_FAILED") for i in block_items):
            action_parts.append("等待契约冻结至 L1 后再并行，或改为接力推进。")
        if any(i["code"] == "SHARED_FILE_CONFLICT" for i in block_items):
            action_parts.append("在任务板中登记共享文件占用，由 SOLO 统一收口后再修改。")
        recommended = "停止任务。" + " ".join(action_parts)
    else:
        recommended = "可继续任务，但请在任务卡中记录 WARNING 项并保持关注。"

    return {
        "decision": decision,
        "reason_codes": reason_codes,
        "conflict_details": conflict_details,
        "recommended_action": recommended,
    }


# ── main ──────────────────────────────────────────────────────────────────────

def run_gate(
    agent_id: str,
    task_name: str,
    files_to_modify: list[str],
    contracts_depended: list[str],
    branch: str | None = None,
) -> dict[str, Any]:
    cfg = load_config()
    branch = branch or git_current_branch()
    git_snap = git_status()

    all_issues: list[dict] = []

    all_issues += check_branch(agent_id, branch, cfg)
    all_issues += check_file_boundaries(agent_id, files_to_modify, git_snap, cfg)
    all_issues += check_contracts(contracts_depended, cfg)

    # 只有前面无 BLOCK 时才做并行三检（避免重复报告）
    if not any(i["level"] == "BLOCK" for i in all_issues):
        all_issues += check_parallel_conditions(
            agent_id, files_to_modify, contracts_depended, git_snap, cfg
        )

    # milestone 分支状态检查（独立 WARNING）
    if milestone_has_unmerged(cfg):
        all_issues.append({
            "code": "MILESTONE_BRANCH_DIRTY",
            "level": "WARNING",
            "detail": "检测到 milestone/* 分支存在未合并到当前分支的变更，请关注集成进度。"
        })

    result = aggregate(all_issues)
    result["task_name"] = task_name
    result["agent_id"] = agent_id
    result["git_snapshot"] = {
        "branch": branch,
        **git_snap,
    }

    return result


def main():
    parser = argparse.ArgumentParser(
        description="dual-agent-conflict-gate: 双代理协作冲突前置门禁"
    )
    parser.add_argument("--agent", required=True, choices=["claude", "solo"],
                        help="当前 agent 身份")
    parser.add_argument("--task", required=True, help="任务名称")
    parser.add_argument("--files", default="",
                        help="计划修改的文件列表，逗号分隔")
    parser.add_argument("--contracts", default="",
                        help="依赖的契约名称列表，逗号分隔")
    parser.add_argument("--branch", default=None,
                        help="当前分支（留空则自动读取）")
    parser.add_argument("--json-only", action="store_true",
                        help="只输出 JSON，不打印摘要")
    args = parser.parse_args()

    files = [f.strip() for f in args.files.split(",") if f.strip()]
    contracts = [c.strip() for c in args.contracts.split(",") if c.strip()]

    result = run_gate(
        agent_id=args.agent,
        task_name=args.task,
        files_to_modify=files,
        contracts_depended=contracts,
        branch=args.branch,
    )

    if args.json_only:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        sys.exit(0 if result["decision"] in ("SAFE", "WARNING") else 1)

    # 人类可读摘要
    icon = {"SAFE": "✅", "WARNING": "⚠️", "BLOCK": "🚫"}[result["decision"]]
    print(f"\n{icon}  [{result['decision']}] {result['task_name']}  (agent: {result['agent_id']})")
    print(f"分支: {result['git_snapshot']['branch']}")

    if result["reason_codes"]:
        print(f"\nreason_codes: {', '.join(result['reason_codes'])}")
        print("\n冲突详情：")
        for d in result["conflict_details"]:
            print(f"  • {d}")

    print(f"\n建议操作：{result['recommended_action']}\n")

    sys.exit(0 if result["decision"] in ("SAFE", "WARNING") else 1)


if __name__ == "__main__":
    main()
