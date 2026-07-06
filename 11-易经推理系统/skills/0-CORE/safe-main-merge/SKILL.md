---
name: safe-main-merge
description: 面向新手和团队成员的主干安全合并标准流程。用于“准备合并到main/主干”“发布前检查”“PR合并与回滚”场景，执行稳定的分支、校验、合并、验证、回滚步骤，避免直接推main导致风险。
---

# Safe Main Merge Skill

以“主干稳定、分支开发、小步合并、可追溯回滚”为唯一目标。  
默认采用：`feature/*` 开发 + PR 合并 + 禁止直推 `main`。

## 固定原则

1. 保持 `main` 随时可用、可发布、可回滚。
2. 在功能分支开发并频繁推送，不在本地长期堆积。
3. 通过 PR 合并，禁止直接 `git push origin main`。
4. 合并前必须通过检查清单，失败即停止（fail-closed）。
5. 每次合并只做一件事（一个主题一个 PR）。

## 触发条件

当用户出现以下意图时，立即使用本 Skill：

- “合并到主干/main”
- “准备发布”
- “帮我安全上传到 GitHub 主分支”
- “做最终合并检查”

## 标准流程（10步）

### 第1步：确认分支与工作区

```bash
git branch --show-current
git status --short
```

要求：

- 当前在 `feature/*` 或 `fix/*` 分支。
- 工作区干净或改动已明确纳入本次提交。

### 第2步：同步远端基线

```bash
git fetch origin --prune
git log --oneline --decorate -n 5
```

要求：

- 本地已看到最新 `origin/main`。

### 第3步：自检提交内容

```bash
git diff --name-only origin/main...HEAD
git diff --stat origin/main...HEAD
```

要求：

- 改动范围与本次主题一致。
- 无无关文件混入。

### 第4步：运行必要验证

最少执行以下其中之一：

- 项目测试命令（如 `pytest`, `npm test`）
- 结构/契约检查命令
- 关键脚本 dry-run

要求：

- 失败不得进入下一步。

### 第5步：提交规范化

```bash
git add -A
git commit -m "type(scope): concise summary"
```

要求：

- 使用可读提交信息。
- 不使用 `--amend` 覆盖已共享历史（除非明确要求）。

### 第6步：推送功能分支

```bash
git push -u origin <feature-branch>
```

要求：

- 分支已远端备份。

### 第7步：创建或更新 PR

```bash
gh pr create --base main --head <feature-branch> --title "<title>" --body "<body>"
# 或
gh pr view --web
```

要求：

- PR 描述包含：变更范围、验证结果、风险点、回滚方式。

### 第8步：等待门禁通过

```bash
gh pr checks <pr-number> --watch
```

要求：

- 所有必须检查项通过。
- 存在 review 评论时先修复再继续。

### 第9步：合并策略

优先使用 squash：

```bash
gh pr merge <pr-number> --squash --delete-branch
```

要求：

- 不使用 `--admin` 强行跳过检查（除紧急且已授权）。

### 第10步：合并后验证

```bash
git checkout main
git pull origin main
git log --oneline -n 3
```

然后执行一轮关键验证（测试或脚本），并记录合并结果。

## 异常处理

### 场景A：检查失败

- 停止合并。
- 在功能分支修复并重新推送。
- 重新跑检查，不可跳过。

### 场景B：发现混入无关改动

- 停止合并。
- 新建清理分支拆分提交后再发 PR。

### 场景C：合并后异常

回滚优先级：

1. 立即定位异常提交：
```bash
git log --oneline
```
2. 使用 revert 回滚（不要 reset 已共享历史）：
```bash
git revert <bad-commit>
git push origin main
```
3. 补充修复 PR。

## 新手执行模板

按顺序复制执行（把尖括号替换为真实值）：

```bash
git checkout <feature-branch>
git fetch origin --prune
git rebase origin/main
git status --short
git add -A
git commit -m "docs(merge): prepare safe merge"
git push -u origin <feature-branch>
gh pr create --base main --head <feature-branch> --title "<title>" --body "<body>"
gh pr checks <pr-number> --watch
gh pr merge <pr-number> --squash --delete-branch
git checkout main && git pull origin main
```

## 输出标准

每次执行后，输出固定四项：

1. 合并结论（成功/失败）
2. 关联 PR 与 commit
3. 验证结果摘要
4. 是否需要回滚或后续修复
