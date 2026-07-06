---
name: branch-lifecycle-automation
description: 分支与 PR 生命周期自动治理技能。用于“清理分支堆积”“自动标记状态”“定时收敛 PR/分支”场景；默认低风险自动处置，高风险升级人工处理。
---

# Branch Lifecycle Automation

目标：在不影响人工合并的前提下，自动治理分支与 PR 堆积。

## 触发意图

- 清理 stale 分支或 stale PR
- 清理空 diff PR
- 自动标记 no-merge-base 风险
- 定时做分支生命周期巡检

## 分级策略

- `L1`：自动执行（关闭空 diff PR、删除已合并且过保留期的非保护分支）
- `L2`：升级人工（打标 + 评论 + issue）
- `L3`：禁止自动 destructive 操作（仅人工）

## 运行方式

- 定时任务：`.github/workflows/branch-lifecycle-automation.yml`
- 手工触发：`workflow_dispatch`
- 核心脚本：`scripts/ci/branch_lifecycle_bot.py`

## 人工合并共存

- 不干预现有人工合并路径
- 不绕过 `safe-main-merge-gate`
- 不允许直推 `main`

## 审计与回滚

- 每次运行输出三类审计产物：`scan/actions/summary`
- 自动关闭的 PR 可手工 reopen
- 自动删除分支需基于审计记录中的 SHA 进行恢复
