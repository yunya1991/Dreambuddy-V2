---
name: architecture-sync-guard
description: 主干合并前的架构冲突与信息同步守卫流程。用于“检查架构一致性”“检查改一处是否需要同步其他文档/契约”“PR门禁冲突排查”等场景，确保 constraints/workflows/docs
  的联动更新完整。
category: orchestration
---

## Autonomy Boundary

可自主执行：
- 治理规则检查与合规报告
- 架构同步校验
- 代码审查与合并建议
- 知识库与记忆管理

需用户确认：
- 执行代码合并（merge 到主分支）
- 修改治理规则本身
- 执行系统级重启或部署

禁止：
- 未经审查直接合并到主分支
- 修改核心治理规则而不经过审批


# Architecture Sync Guard Skill

用于防止“改了代码或结构，但没同步架构文档、契约、索引”的隐性风险。  
该 Skill 对应自动化脚本：`scripts/ci/architecture_sync_guard.py`。

## 使用时机

当出现以下请求时使用：

- “准备合并到 main 前再检查架构一致性”
- “改动涉及多处联动，帮我检查是否漏同步”
- “PR gate 提示 architecture sync failed”

## 强制检查规则

1. 顶层目录变更必须在架构白名单内。
2. `docs/architecture.md` 与 `constraints/system-index/engineering-architecture.md` 必须同步更新。
3. 变更 `workflows/memory/` 或 `workflows/trading-decision/` 时，必须同步 `constraints/workflows-spec/communication-contract-v0.1.md`。
4. 变更 `constraints/workflows-spec/` 规范文件时，必须同步 `constraints/workflows-spec/README.md` 索引。
5. 变更 `constraints/` 时，必须同时在 `constraints/system-index/` 或 `constraints/workflows-spec/` 落信息同步。

## 本地执行

```bash
git fetch origin main --depth=1
git diff --name-only origin/main...HEAD > changed_files.txt
CHANGED_FILES_PATH=changed_files.txt python scripts/ci/architecture_sync_guard.py
```

## CI 执行

该 Skill 已接入：

- `.github/workflows/safe-main-merge-gate.yml`
- Job: `PR Gate Checks`
- Step: `Run architecture sync guard`

失败即阻断 PR 合并。

## 故障处理

当检查失败时，按下面顺序处理：

1. 读取错误信息，定位缺失的联动文件。
2. 补齐同步文档或契约更新。
3. 重新提交并等待门禁重跑。
4. 不允许通过 `--admin` 跳过门禁直接合并。
