---
name: code-review-merge-assistant
description: 本地一键代码审核与合并助手。用于“代码审核合并”“一键合并到main”“检查通过后自动合并”等场景，自动执行分支检查、PR检查等待、门禁通过后 squash 合并与主干同步。
---

# Code Review Merge Assistant

目标：让你只说一句“代码审核合并”，即可按稳定工程流程自动完成合并。  
默认策略：**远端优先 + 本地兜底**。

## 触发语句

以下语句都应触发本 Skill：

- 代码审核合并
- 一键合并到 main
- 检查通过后自动合并
- 帮我走标准合并流程

## 执行流程

1. 先对远端仓库执行守卫检查（GitHub API）：
   `python3 scripts/ci/remote_repo_guard.py <repo_or_url>`。
2. 本地兜底检查：当前分支不是 `main`，工作区干净。
3. 运行一键脚本：`scripts/ci/quick_merge.sh`。
4. 等待 `PR Gate Checks` 通过。
5. 自动执行 squash merge 并同步本地 `main`。

## 标准命令

```bash
# 支持 owner/repo 或完整 GitHub URL
scripts/ci/quick_merge.sh yunya1991/dream-multiskill-v2
scripts/ci/quick_merge.sh https://github.com/yunya1991/dream-multiskill-v2
```

## 安全与策略

- 不允许在 `main` 分支直接执行合并。
- 必须通过 GitHub PR 门禁（`PR Gate Checks`）。
- 保持架构一致性、信息同步性和审计策略。
- 若门禁失败，停止并返回失败原因，不允许跳过。

## 失败处理

当出现失败时，按顺序处理：

1. 读取 `gh pr checks` 失败项。
2. 根据失败项修复代码/文档/契约同步。
3. 重新推送当前分支。
4. 重新执行 `scripts/ci/quick_merge.sh`。

## 输出格式

每次执行后必须输出：

1. 合并结论（成功/失败）
2. PR 链接
3. 合并 commit
4. 门禁结果摘要
