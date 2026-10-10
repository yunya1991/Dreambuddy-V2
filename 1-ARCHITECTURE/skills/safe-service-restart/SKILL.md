---
name: "safe-service-restart"
description: "服务重启硬门禁流程：commit → 验证工作区干净 → 重启 → 验证前后代码一致。Invoke whenever a backend/frontend service needs to be restarted after code changes, to prevent regression from uncommitted changes."
---

## Autonomy Boundary

可自主执行：
- 工具调用与数据转换
- 文档格式转换（Markdown/JSON/CSV）
- 通用查询与搜索操作
- 代码生成与重构建议

需用户确认：
- 执行破坏性操作（删除/覆盖重要文件）
- 修改系统核心配置

禁止：
- 未经授权执行不可逆操作
- 访问未授权的外部资源


# Safe Service Restart (服务重启硬门禁)

## 触发条件

当需要重启任何后台服务（后端 API、前端 dev server、调度器等）以加载代码变更时，**必须**调用本 SKILL。常见场景：

- 修改了后端 Python 代码后需要重启 Flask/FastAPI 服务
- 修改了前端配置后需要重启 dev server
- 修改了调度器/采集器后需要重启进程
- 用户明确要求"重启服务"

## 硬门禁流程（不可跳过、不可乱序）

### Step 1: 检查并提交所有变更

```bash
git status --short
git add -A
git commit -m "<描述本次变更>"
```

**注意**：如果工作区有其他对话框/任务的未提交变更，一并提交（用户已确认此策略）。不要选择性提交，避免遗漏。

### Step 2: 验证工作区干净

```bash
git status --short
```

- 期望输出：**空**（无任何变更）
- 如果非空 → 回到 Step 1，必须先提交干净
- **禁止**在工作区不干净时重启

### Step 3: 记录当前 HEAD commit

```bash
git log --oneline -1
```

记下 commit hash，用于重启后比对。

### Step 4: 停止旧进程

```bash
# 找到占用目标端口的 PID
lsof -ti :<PORT>

# 优雅终止（SIGTERM）
kill <PID>
```

如果 `kill` 后进程仍在，等待 2-3 秒再检查；必要时用 `kill -9 <PID>`。

### Step 5: 启动新进程

按服务的标准启动方式启动（通常在项目根目录或对应子目录）：

```bash
cd <service-dir> && <start-command>
```

启动后等待 3-5 秒，确认端口已监听。

### Step 6: 验证重启后代码一致性

```bash
git status --short          # 必须仍为空
git log --oneline -1        # 必须与 Step 3 的 commit hash 一致
```

如果发现工作区变脏或 commit 不一致 → 立即停止并排查，不要继续。

### Step 7: 验证服务功能

通过 API 调用或健康检查确认服务正常返回数据：

```bash
curl -s http://127.0.0.1:<PORT>/<health-or-snapshot-endpoint>
```

## 常见坑 & 反模式

| 反模式 | 后果 | 正确做法 |
|--------|------|----------|
| 未提交就重启 | 重启后工作区变更可能丢失或冲突 | 先 commit，确认干净再重启 |
| 重启后不验证 | 可能加载了旧代码或启动失败 | 必须比对 commit hash + 调用 API 验证 |
| 用 `kill -9` 直接杀 | 可能导致数据未落盘 | 优先 `kill`（SIGTERM），等几秒后再 -9 |
| 启动后不等待就验证 | 服务未就绪导致误判失败 | 等待 3-5 秒或直到端口监听 |
| 选择性 git add | 遗漏其他对话框的变更 | 用 `git add -A` 全部提交 |

## 环境适配

如果 shell 中缺少 `git`/`lsof`/`kill` 等命令（某些受限环境），可用以下替代：

- `git` → 用绝对路径 `/usr/bin/git` 或 `/opt/homebrew/bin/git`
- `lsof` → 用 `/usr/sbin/lsof`
- `kill`/`sleep` → 用 Python: `python -c "import os,time; os.kill(PID,15); time.sleep(3)"`

## 成功标准

- ✅ `git status --short` 重启前后均为空
- ✅ `git log --oneline -1` 重启前后 commit hash 一致
- ✅ 服务端口监听正常
- ✅ API/健康检查返回预期数据
