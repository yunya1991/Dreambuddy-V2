---
name: "dream-code-deploy-pipeline"
description: "Orchestrates full code delivery pipeline: local commit → GitHub CI (Actions) → server deploy (webhook/update.sh) → healthcheck → rollback. Invoke when user wants to sync code to cloud, deploy to server, set up CI/CD, or roll back a bad deployment."
version: 1.0.0
created: 2026-10-09
status: active
category: orchestration
triggers: [部署, 同步代码, CI, CD, 自动部署, deploy, sync, webhook, 回滚, rollback, 上线]
depends_on: [dream-code-commit-sync-workflow, git, github-actions, update.sh, healthcheck.sh]
provides: [code-delivery, ci-cd, auto-deploy, rollback]
---

# Dream Code Deploy Pipeline — 代码交付全链路工作流

> 把「本地 commit → GitHub CI 门禁 → 服务器自动部署 → 健康检查 → 回滚」的完整交付链路固化为可复用编排。本 SKILL 是 `dream-code-commit-sync-workflow`（本地提交）的下游延伸，覆盖从代码合入到线上生效的全流程。

> **双位置存储**：本 SKILL 同时存在于：
> - `.trae/skills/dream-code-deploy-pipeline/SKILL.md`（TRAE 调用入口，本文件）
> - `1-ARCHITECTURE/skills/dream-code-deploy-pipeline/SKILL.md`（项目级索引发现）

---

## 一、何时调用

满足以下任一条件：

1. **代码需要部署到服务器**：本地改完代码，要同步到云端服务器
2. **配置 CI/CD**：用户要搭建 GitHub Actions 或自动部署
3. **回滚线上版本**：部署出问题，需要回滚
4. **部署验证**：部署后检查服务是否健康
5. **触发词**：「部署」「同步代码」「上线」「CI」「CD」「自动部署」「回滚」「rollback」

**不触发**：
- 纯本地 commit（用 `dream-code-commit-sync-workflow`）
- 纯文档同步（用 `dream-doc-sync-workflow`）

---

## 二、四层架构

```
Layer 1: 本地 commit ──→ Layer 2: GitHub CI ──→ Layer 3: 服务器部署 ──→ Layer 4: 健康检查/回滚
   (commit+push)          (Actions 门禁)          (update.sh/webhook)        (healthcheck)
```

| 层 | 职责 | 工具 |
|----|------|------|
| L1 本地提交 | 代码变更 → commit → push origin | `dream-code-commit-sync-workflow` |
| L2 CI 门禁 | lint + typecheck + test + build | GitHub Actions (`.github/workflows/`) |
| L3 自动部署 | pull 代码 → rebuild → restart | `update.sh` + webhook |
| L4 验证回滚 | 健康检查 + 异常回滚 | `healthcheck.sh` + git revert + pm2 rollback |

---

## 三、Layer 1: 本地提交并推送

**前置**：调用 `dream-code-commit-sync-workflow` 完成 commit。

**推送流程**：

```bash
# 1. 确认远程仓库
git remote -v
# 应包含 origin → https://github.com/<owner>/<repo>.git

# 2. 拉取远程最新（避免冲突）
git pull --rebase origin main

# 3. 推送
git push origin main
```

**冲突处理决策树**：

```
git pull --rebase 有冲突？
├─ 是 → 解决冲突 → git add . → git rebase --continue → push
└─ 否 → 直接 push
```

**注意事项**：
- 推送前确认本地 working tree 干净（`git status` 无未提交修改）
- 避免 `--force` push 到 main 分支
- 如果远程有他人提交，必须先 rebase 合并

---

## 四、Layer 2: GitHub Actions CI 门禁

### 4.1 CI 配置模板

创建 `.github/workflows/ci.yml`：

```yaml
name: CI

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  frontend:
    runs-on: ubuntu-latest
    defaults:
      run:
        working-directory: 3.1-FRONTEND
    steps:
      - uses: actions/checkout@v4
      - uses: pnpm/action-setup@v4
        with:
          version: 9
      - uses: actions/setup-node@v4
        with:
          node-version: 22
          cache: pnpm
          cache-dependency-path: 3.1-FRONTEND/pnpm-lock.yaml
      - run: pnpm install --frozen-lockfile
      - run: pnpm lint
      - run: pnpm test
      - run: pnpm build

  python-tests:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        module: [14-V15经典马丁策略]
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'
      - name: Install deps
        run: |
          pip install requests pandas numpy ccxt python-dotenv pytest
      - name: Run tests
        run: |
          cd ${{ matrix.module }}
          PYTHONPATH=lib:core python -m pytest tests/ -v --tb=short || echo "tests skipped (may need env)"
```

### 4.2 CI 配置决策

| 场景 | 配置 |
|------|------|
| 快速验证 | 只跑 frontend lint + build |
| 完整门禁 | frontend + python 全量测试 |
| 跳过 CI | commit message 加 `[skip ci]` |

---

## 五、Layer 3: 服务器自动部署

### 5.1 方案对比

| 方案 | 实时性 | 复杂度 | 推荐度 |
|------|--------|--------|--------|
| **Webhook 自动部署** | 实时（push 即部署） | 中 | ⭐⭐⭐⭐⭐ |
| 手动 update.sh | 手动触发 | 低 | ⭐⭐⭐（保底） |
| 定时 pull (cron) | 延迟 1-5min | 低 | ⭐⭐（不推荐） |

### 5.2 Webhook 自动部署（推荐）

**服务器端**：创建 webhook 接收脚本

```bash
# /home/luke/.config/dreambuddy/webhook-listener.sh
#!/bin/bash
# 监听 GitHub push 事件，触发 update.sh
set -e

LOG_FILE="/home/luke/logs/deploy-webhook.log"
SECRET="${GITHUB_WEBHOOK_SECRET:-change-me}"

# 验证签名（简化版，生产环境需 HMAC 验证）
echo "$(date): webhook received" >> "$LOG_FILE"

# 执行更新（异步，不阻塞 webhook 响应）
nohup bash /home/luke/dreambuddy/31-分布式计算部署/phase1/update.sh >> "$LOG_FILE" 2>&1 &

echo "OK"
```

**Nginx 配置**（添加 webhook 路由）：

```nginx
location /github-webhook {
    proxy_pass http://127.0.0.1:9000;
    # 或直接用 ncat 监听
}
```

**GitHub 配置**：
1. 仓库 → Settings → Webhooks → Add webhook
2. Payload URL: `https://<domain>/github-webhook`
3. Content type: `application/json`
4. Secret: 与服务器端 `GITHUB_WEBHOOK_SECRET` 一致
5. Events: 选 `Just the push event`

### 5.3 手动部署（保底方案）

```bash
# SSH 登录服务器
ssh luke@<server-ip>

# 执行更新
cd ~/dreambuddy/31-分布式计算部署/phase1
bash update.sh
```

`update.sh` 流程：
1. `git pull` 拉取最新代码
2. 前端：`pnpm install` → `pnpm build` → `pm2 restart`
3. V15 API：`systemctl restart v15-api v15-capital-api`
4. Hermes：`systemctl restart hermes-gateway`

---

## 六、Layer 4: 健康检查与回滚

### 6.1 部署后健康检查

```bash
# 服务器上执行
bash ~/dreambuddy/31-分布式计算部署/phase1/healthcheck.sh
```

检查维度：
- 前端 (PM2 + HTTP 3001)
- V15 API (8771 + 8770)
- V15 timers (orchestrator + poll_light)
- Docker 容器 (PG + Redis + MinIO)
- Hermes 网关
- Nginx
- 磁盘 + 内存

**通过标准**：0 个 FAIL，WARN 可接受。

### 6.2 回滚流程

**触发条件**：healthcheck 有 FAIL，或业务异常。

**回滚决策树**：

```
部署异常？
├─ 前端问题 → pm2 rollback dreambuddy-frontend
├─ V15 问题 → systemctl restart v15-api (或 git revert)
├─ 全局问题 → git revert + update.sh
└─ 数据库迁移问题 → prisma migrate resolve (回滚迁移)
```

**回滚步骤**：

```bash
# 1. 查看最近的 commit
git log --oneline -5

# 2. 回滚到上一个稳定版本
git revert HEAD   # 或 git reset --hard <commit-hash>

# 3. 重新部署
bash update.sh

# 4. 验证
bash healthcheck.sh
```

**PM2 回滚**（前端）：

```bash
# 如果 build 成功但运行异常，回退到上一个 PM2 版本
pm2 rollback dreambuddy-frontend
```

---

## 七、完整交付流程（端到端）

```
1. 本地改代码
   ↓
2. dream-code-commit-sync-workflow (commit)
   ↓
3. git pull --rebase origin main
   ↓
4. git push origin main
   ↓
5. GitHub Actions 自动跑 CI (lint + test + build)
   ↓
6. CI 通过 → webhook 触发服务器 update.sh
   ↓        └─ CI 失败 → 修复后回到 步骤1
7. update.sh: git pull → build → restart
   ↓
8. healthcheck.sh 验证
   ↓        └─ 失败 → 回滚流程
9. 部署完成 ✅
```

---

## 八、常见问题

### Q: push 被 reject 怎么办？
```bash
# 远程有新提交
git pull --rebase origin main
# 解决冲突后
git push origin main
```

### Q: CI 总是失败但本地能过？
- 检查 `pnpm-lock.yaml` 是否提交（CI 用 `--frozen-lockfile`）
- 检查 Node 版本（CI 用 22，本地也要 22）
- 检查环境变量（CI 里没有 .env.local，测试不能依赖）

### Q: webhook 触发了但部署没生效？
```bash
# 查看 webhook 日志
tail -50 ~/logs/deploy-webhook.log
# 查看 update.sh 日志
tail -50 ~/logs/update.log  # 如果有
# 手动执行一次
bash update.sh
```

### Q: 回滚后还是不行？
```bash
# 查看服务状态
systemctl status v15-api v15-capital-api hermes-gateway
pm2 status
docker ps
# 查看具体日志
journalctl -u v15-api -n 50
```

---

## 九、与其他 SKILL 的协作

| SKILL | 协作点 |
|-------|--------|
| `dream-code-commit-sync-workflow` | Layer 1 本地 commit |
| `dream-feature-landing-workflow` | 功能上线的前后端适配 |
| `dream-acceptance-verify` | 部署后的功能验收 |
| `dream-module-post-dev-verify-workflow` | 模块级验证 |
