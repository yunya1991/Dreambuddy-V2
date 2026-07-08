# Branch Lifecycle Automation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不影响人工合并路径的前提下，实现分支/PR 生命周期自动巡检、低风险自动处置与高风险升级审计闭环。  
**Architecture:** 采用“规则分类器 + GitHub API 执行器 + 定时工作流”三层结构。分类器只负责判定与动作计划，执行器只处理远端变更，工作流负责调度与审计上传。默认 fail-closed，保护分支永不自动修改。  
**Tech Stack:** Python 3.11、GitHub Actions、`gh api`/REST、pytest

---

## 文件结构与职责

- `scripts/ci/branch_lifecycle_bot.py`：核心脚本（扫描、分类、执行、产物写盘、CLI）。
- `tests/test_ci_branch_lifecycle_bot.py`：脚本单测（规则判定、dry-run、动作执行、审计产物）。
- `.github/workflows/branch-lifecycle-automation.yml`：定时+手动触发调度工作流。
- `skills/0-CORE/branch-lifecycle-automation/SKILL.md`：技能使用说明、分层策略与人工合并共存约束。
- `constraints/workflows-spec/communication-contract-v0.1.md`：新增 branch lifecycle 审计事件契约记录。
- `constraints/workflows-spec/README.md`：补充新规范条目索引（满足 guard 同步要求）。

### Task 1: 规则分类器（TDD）

**Files:**
- Create: `tests/test_ci_branch_lifecycle_bot.py`
- Create: `scripts/ci/branch_lifecycle_bot.py`
- Test: `tests/test_ci_branch_lifecycle_bot.py`

- [ ] **Step 1: 先写失败测试（分类规则）**

```python
from scripts.ci.branch_lifecycle_bot import classify_pull_request, classify_branch


def test_classify_pr_empty_diff_returns_auto_close():
    pr = {"number": 5, "state": "open", "updated_at": "2026-05-01T00:00:00Z"}
    result = classify_pull_request(
        pr=pr,
        changed_files=[],
        has_merge_base=True,
        stale_days=7,
        now_ts="2026-05-11T00:00:00Z",
    )
    assert result["risk_level"] == "L1"
    assert result["labels"] == ["branch-bot/empty-diff"]
    assert result["actions"] == ["close_pr"]


def test_classify_pr_no_merge_base_returns_manual_review():
    pr = {"number": 8, "state": "open", "updated_at": "2026-05-10T00:00:00Z"}
    result = classify_pull_request(
        pr=pr,
        changed_files=["scripts/ci/x.py"],
        has_merge_base=False,
        stale_days=7,
        now_ts="2026-05-11T00:00:00Z",
    )
    assert result["risk_level"] == "L2"
    assert "branch-bot/no-merge-base" in result["labels"]
    assert "open_issue" in result["actions"]


def test_classify_branch_never_mutates_protected():
    branch = {"name": "main", "protected": True, "is_merged": True, "age_days": 30}
    result = classify_branch(branch=branch, retention_days=7)
    assert result["risk_level"] == "L3"
    assert result["actions"] == []
```

- [ ] **Step 2: 运行测试确认红灯**

Run: `pytest tests/test_ci_branch_lifecycle_bot.py -q`  
Expected: `FAIL`，提示 `ModuleNotFoundError` 或函数未定义。

- [ ] **Step 3: 写最小实现让测试转绿**

```python
# scripts/ci/branch_lifecycle_bot.py
from datetime import datetime, timezone
from typing import Any, Dict, List


def _parse_ts(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(timezone.utc)


def classify_pull_request(
    *,
    pr: Dict[str, Any],
    changed_files: List[str],
    has_merge_base: bool,
    stale_days: int,
    now_ts: str,
) -> Dict[str, Any]:
    labels: List[str] = []
    actions: List[str] = []
    risk_level = "L1"

    if not has_merge_base:
        labels.append("branch-bot/no-merge-base")
        actions.append("open_issue")
        risk_level = "L2"
        return {"risk_level": risk_level, "labels": labels, "actions": actions}

    if len(changed_files) == 0:
        labels.append("branch-bot/empty-diff")
        actions.append("close_pr")
        return {"risk_level": risk_level, "labels": labels, "actions": actions}

    updated = _parse_ts(pr["updated_at"])
    now = _parse_ts(now_ts)
    if (now - updated).days >= stale_days:
        labels.append("branch-bot/stale")
        actions.append("comment_reminder")

    return {"risk_level": risk_level, "labels": labels, "actions": actions}


def classify_branch(*, branch: Dict[str, Any], retention_days: int) -> Dict[str, Any]:
    if branch.get("protected") or branch.get("name") == "main":
        return {"risk_level": "L3", "labels": ["branch-bot/manual-review-required"], "actions": []}

    if branch.get("is_merged") and int(branch.get("age_days", 0)) >= retention_days:
        return {"risk_level": "L1", "labels": ["branch-bot/merged-cleanup-candidate"], "actions": ["delete_branch"]}

    return {"risk_level": "L1", "labels": [], "actions": []}
```

- [ ] **Step 4: 运行测试确认绿灯**

Run: `pytest tests/test_ci_branch_lifecycle_bot.py -q`  
Expected: `3 passed`.

- [ ] **Step 5: 提交**

```bash
git add scripts/ci/branch_lifecycle_bot.py tests/test_ci_branch_lifecycle_bot.py
git commit -m "feat(ci): add branch lifecycle classifier with tests"
```

### Task 2: 执行器与 dry-run 守卫（TDD）

**Files:**
- Modify: `scripts/ci/branch_lifecycle_bot.py`
- Modify: `tests/test_ci_branch_lifecycle_bot.py`
- Test: `tests/test_ci_branch_lifecycle_bot.py`

- [ ] **Step 1: 追加失败测试（dry-run 与动作执行）**

```python
from scripts.ci.branch_lifecycle_bot import execute_actions


def test_execute_actions_dry_run_has_no_remote_calls():
    calls = []

    def fake_call(method, path, payload=None):
        calls.append((method, path, payload))
        return {"ok": True}

    res = execute_actions(
        repo="yunya1991/dream-multiskill-v2",
        target={"type": "pr", "number": 5},
        actions=["close_pr", "add_label"],
        labels=["branch-bot/empty-diff"],
        dry_run=True,
        api_call=fake_call,
    )
    assert res["executed"] == []
    assert len(calls) == 0


def test_execute_actions_close_pr_and_label():
    calls = []

    def fake_call(method, path, payload=None):
        calls.append((method, path, payload))
        return {"ok": True}

    res = execute_actions(
        repo="yunya1991/dream-multiskill-v2",
        target={"type": "pr", "number": 5},
        actions=["close_pr", "add_label"],
        labels=["branch-bot/auto-closed"],
        dry_run=False,
        api_call=fake_call,
    )
    assert "close_pr" in res["executed"]
    assert "add_label" in res["executed"]
    assert len(calls) == 2
```

- [ ] **Step 2: 跑测试看红灯**

Run: `pytest tests/test_ci_branch_lifecycle_bot.py::test_execute_actions_dry_run_has_no_remote_calls -q`  
Expected: `FAIL`，提示 `execute_actions` 未定义。

- [ ] **Step 3: 实现执行器**

```python
from typing import Callable, Optional


def execute_actions(
    *,
    repo: str,
    target: Dict[str, Any],
    actions: List[str],
    labels: List[str],
    dry_run: bool,
    api_call: Callable[[str, str, Optional[Dict[str, Any]]], Dict[str, Any]],
) -> Dict[str, Any]:
    planned = list(actions)
    executed: List[str] = []
    if dry_run:
        return {"planned": planned, "executed": executed}

    if target["type"] == "pr":
        pr_number = target["number"]
        if "close_pr" in actions:
            api_call("PATCH", f"/repos/{repo}/pulls/{pr_number}", {"state": "closed"})
            executed.append("close_pr")
        if "add_label" in actions and labels:
            api_call("POST", f"/repos/{repo}/issues/{pr_number}/labels", {"labels": labels})
            executed.append("add_label")

    if target["type"] == "branch" and "delete_branch" in actions:
        branch_name = target["name"]
        api_call("DELETE", f"/repos/{repo}/git/refs/heads/{branch_name}", None)
        executed.append("delete_branch")

    return {"planned": planned, "executed": executed}
```

- [ ] **Step 4: 运行完整单测**

Run: `pytest tests/test_ci_branch_lifecycle_bot.py -q`  
Expected: 全绿通过。

- [ ] **Step 5: 提交**

```bash
git add scripts/ci/branch_lifecycle_bot.py tests/test_ci_branch_lifecycle_bot.py
git commit -m "feat(ci): add branch lifecycle action executor and dry-run guard"
```

### Task 3: CLI + 审计产物写盘（TDD）

**Files:**
- Modify: `scripts/ci/branch_lifecycle_bot.py`
- Modify: `tests/test_ci_branch_lifecycle_bot.py`
- Test: `tests/test_ci_branch_lifecycle_bot.py`

- [ ] **Step 1: 写失败测试（参数解析与产物写盘）**

```python
from pathlib import Path
from scripts.ci.branch_lifecycle_bot import parse_args, write_artifacts


def test_parse_args_defaults():
    args = parse_args([])
    assert args.repo == "yunya1991/dream-multiskill-v2"
    assert args.dry_run is False
    assert args.stale_days == 7
    assert args.retention_days == 14


def test_write_artifacts_creates_three_json_files(tmp_path: Path):
    out = write_artifacts(
        base_dir=tmp_path,
        scan={"prs": 1, "branches": 2},
        actions={"executed": ["close_pr"]},
        summary={"run_id": "r1", "errors": 0},
        timestamp="20260511T120000Z",
    )
    assert out["scan"].name.startswith("scan-")
    assert out["actions"].exists()
    assert out["summary"].exists()
```

- [ ] **Step 2: 运行红灯**

Run: `pytest tests/test_ci_branch_lifecycle_bot.py::test_parse_args_defaults -q`  
Expected: `FAIL`，提示函数不存在。

- [ ] **Step 3: 实现 CLI 与产物写盘**

```python
import argparse
import json
from pathlib import Path


def parse_args(argv: List[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Branch lifecycle automation bot")
    parser.add_argument("--repo", default="yunya1991/dream-multiskill-v2")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--stale-days", type=int, default=7)
    parser.add_argument("--retention-days", type=int, default=14)
    parser.add_argument("--artifacts-dir", default="artifacts/branch_lifecycle")
    return parser.parse_args(argv)


def write_artifacts(
    *,
    base_dir: Path,
    scan: Dict[str, Any],
    actions: Dict[str, Any],
    summary: Dict[str, Any],
    timestamp: str,
) -> Dict[str, Path]:
    base_dir.mkdir(parents=True, exist_ok=True)
    scan_path = base_dir / f"scan-{timestamp}.json"
    actions_path = base_dir / f"actions-{timestamp}.json"
    summary_path = base_dir / f"summary-{timestamp}.json"
    scan_path.write_text(json.dumps(scan, ensure_ascii=False, indent=2), encoding="utf-8")
    actions_path.write_text(json.dumps(actions, ensure_ascii=False, indent=2), encoding="utf-8")
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"scan": scan_path, "actions": actions_path, "summary": summary_path}
```

- [ ] **Step 4: 运行测试**

Run: `pytest tests/test_ci_branch_lifecycle_bot.py -q`  
Expected: 全部通过。

- [ ] **Step 5: 提交**

```bash
git add scripts/ci/branch_lifecycle_bot.py tests/test_ci_branch_lifecycle_bot.py
git commit -m "feat(ci): add branch lifecycle cli and audit artifact writer"
```

### Task 4: GitHub Action 定时调度

**Files:**
- Create: `.github/workflows/branch-lifecycle-automation.yml`
- Test: `.github/workflows/branch-lifecycle-automation.yml`（通过 YAML 校验 + 手动 dry-run）

- [ ] **Step 1: 先写工作流文件**

```yaml
name: Branch Lifecycle Automation

on:
  schedule:
    - cron: "17 2 * * *"
  workflow_dispatch:
    inputs:
      dry_run:
        description: "Run in dry-run mode"
        required: false
        default: "false"
      stale_days:
        description: "Stale threshold days"
        required: false
        default: "7"
      retention_days:
        description: "Merged branch retention days"
        required: false
        default: "14"

permissions:
  contents: write
  pull-requests: write
  issues: write

jobs:
  lifecycle:
    runs-on: ubuntu-latest
    steps:
      - name: Checkout
        uses: actions/checkout@v4
      - name: Setup Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - name: Run branch lifecycle bot
        env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
        run: |
          DRY_RUN="${{ github.event.inputs.dry_run || 'false' }}"
          STALE_DAYS="${{ github.event.inputs.stale_days || '7' }}"
          RETENTION_DAYS="${{ github.event.inputs.retention_days || '14' }}"
          if [ "$DRY_RUN" = "true" ]; then
            python scripts/ci/branch_lifecycle_bot.py --dry-run --stale-days "$STALE_DAYS" --retention-days "$RETENTION_DAYS"
          else
            python scripts/ci/branch_lifecycle_bot.py --stale-days "$STALE_DAYS" --retention-days "$RETENTION_DAYS"
          fi
      - name: Upload lifecycle artifacts
        uses: actions/upload-artifact@v4
        with:
          name: branch-lifecycle-${{ github.run_id }}
          path: artifacts/branch_lifecycle/*.json
          if-no-files-found: error
```

- [ ] **Step 2: 本地 YAML 静态检查**

Run: `python - <<'PY'\nimport yaml, pathlib; yaml.safe_load(pathlib.Path('.github/workflows/branch-lifecycle-automation.yml').read_text()); print('ok')\nPY`  
Expected: 输出 `ok`。

- [ ] **Step 3: 提交**

```bash
git add .github/workflows/branch-lifecycle-automation.yml
git commit -m "ci(workflow): add scheduled branch lifecycle automation job"
```

### Task 5: 新增 SKILL 与规范同步

**Files:**
- Create: `skills/0-CORE/branch-lifecycle-automation/SKILL.md`
- Modify: `constraints/workflows-spec/communication-contract-v0.1.md`
- Modify: `constraints/workflows-spec/README.md`
- Test: `scripts/ci/architecture_sync_guard.py`（通过变更同步检查）

- [ ] **Step 1: 编写 SKILL 文档**

```md
---
name: branch-lifecycle-automation
description: 分支与PR生命周期自动治理技能。用于“清理分支堆积”“自动标记状态”“定时收敛PR/分支”场景；默认低风险自动处置，高风险升级人工处理。
---

# Branch Lifecycle Automation

## 触发意图
- 清理 stale 分支
- 清理空 diff PR
- 自动标记 no-merge-base 风险

## 分级策略
- L1：自动执行（打标、评论、关闭空 diff PR、删除已合并非保护分支）
- L2：仅升级（打标 + issue）
- L3：禁止自动 destructive 操作（仅人工）

## 人工合并共存
- 不干预现有人工合并路径
- 不绕过 `safe-main-merge-gate`
- 不允许直推 main
```

- [ ] **Step 2: 同步通信契约与索引**

```md
<!-- constraints/workflows-spec/communication-contract-v0.1.md 新增条目 -->
- 2026-05-11: 新增 Branch Lifecycle Bot 审计事件（scan/actions/summary 三类 artifacts），用于分支与PR状态自动治理追溯。
```

```md
<!-- constraints/workflows-spec/README.md 新增条目 -->
- `communication-contract-v0.1.md`（2026-05-11 更新）：新增 Branch Lifecycle Bot 自动治理审计事件约定
```

- [ ] **Step 3: 跑测试与门禁检查**

Run: `pytest tests/test_ci_branch_lifecycle_bot.py -q`  
Expected: 通过。  

Run: `python scripts/ci/architecture_sync_guard.py`  
Expected: 在提供 `CHANGED_FILES_PATH` 场景下通过（CI 中验证）。

- [ ] **Step 4: 提交**

```bash
git add skills/0-CORE/branch-lifecycle-automation/SKILL.md \
  constraints/workflows-spec/communication-contract-v0.1.md \
  constraints/workflows-spec/README.md
git commit -m "docs(skill): add branch lifecycle automation skill and contract sync"
```

### Task 6: 收口验证与 PR 合并流程

**Files:**
- Modify: `scripts/ci/branch_lifecycle_bot.py`（如需修复回归）
- Modify: `tests/test_ci_branch_lifecycle_bot.py`（如需补测）

- [ ] **Step 1: 全量回归**

Run: `pytest tests/test_ci_branch_lifecycle_bot.py tests/test_ci_safe_main_merge_gate.py tests/test_ci_architecture_sync_guard.py -q`  
Expected: 全绿通过。

- [ ] **Step 2: 创建分支并推送**

```bash
git checkout -b feature/branch-lifecycle-automation
git push -u origin feature/branch-lifecycle-automation
```

- [ ] **Step 3: 创建 PR**

```bash
gh pr create --base main --head feature/branch-lifecycle-automation \
  --title "feat(ci): add branch lifecycle automation bot and workflow" \
  --body "## Summary\n- add branch lifecycle bot\n- add scheduled workflow\n- add skill and contract sync\n\n## Validation\n- pytest tests/test_ci_branch_lifecycle_bot.py -q"
```

- [ ] **Step 4: 等待门禁并合并**

Run: `gh pr checks --watch`  
Expected: `PR Gate Checks` 通过。  

Run: `gh pr merge --squash --delete-branch`  
Expected: 合并成功并删除远端开发分支。

- [ ] **Step 5: 合并后验证**

```bash
git checkout main
git pull origin main
git log --oneline -n 3
```

Expected: 包含本次 squash commit。

## 自检清单（已完成）

- Spec 覆盖：规则分层、定时触发、手动触发、审计产物、人工合并共存、回滚策略均映射到具体任务。  
- 占位符扫描：无 `TODO/TBD/implement later`。  
- 命名一致性：`classify_pull_request`、`classify_branch`、`execute_actions`、`write_artifacts` 在任务中保持一致。
