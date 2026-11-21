---
name: polling-trader-reload
description: 'Reload polling_trader after code changes: kill old → wait flock release
  → start new with same config → verify pidfile + main loop. Invoke when polling_trader.py
  modified or user says ''重启/reload polling_trader''.'
category: tooling
---

# Polling Trader Reload

封装 polling_trader 修改代码后的安全重启流程，处理 fcntl.flock 单例锁约束。

## 前置条件

1. 代码修改已完成
2. **必须先 commit 再重启**（用户硬约束：代码修改完成后必须先 commit 再重启后端服务，确保重启前后代码一致）
3. 语法检查通过：`python3 -m py_compile "11-易经推理系统/scripts/memory_l4/polling_trader.py"`

## 单例锁约束（关键）

polling_trader.py `main()` 函数 L17632-17669 已加 fcntl.flock 独占锁 + `/tmp/polling_trader.pid`：

- 主进程持有 `LOCK_EX | LOCK_NB`，进程退出/异常/`kill -9` 自动释放（OS 关闭 fd）
- 第二实例启动会被 `sys.exit(1)` 拒绝并报告已运行 PID
- **无法零停机重启**：先启动新进程再 kill 旧进程会被锁拒绝
- **唯一解锁方法**：`kill -9` 持锁进程（删除 pidfile **不能**释放 flock，锁在 fd 上不在文件上）
- `--once` 模式跳过锁（一次性快照不阻塞主进程）

## 标准重启流程（5 步）

### 步骤 1：提取当前运行配置

从旧进程命令行提取参数，新进程使用相同配置（避免参数丢失）：

```bash
ps -ef | grep "scripts.memory_l4.polling_trader" | grep -v grep
```

记录：`--interval / --coins / --confidence / --max-positions / --position-pct / --initial-equity / --no-guardian`（如存在）。

### 步骤 2：语法检查 + commit

```bash
cd /Users/zhangjiangtao/WorkBuddy/dreambuddy-v2

# 语法检查
python3 -m py_compile "11-易经推理系统/scripts/memory_l4/polling_trader.py"

# 验证工作区状态
git status --short "11-易经推理系统/scripts/memory_l4/polling_trader.py"

# 如有改动，先 commit（用户硬约束）
git add "11-易经推理系统/scripts/memory_l4/polling_trader.py"
git commit -m "fix(11-易经推理系统): <改动描述>"
```

### 步骤 3：kill 旧进程 + 等待 flock 释放

> ⚠️ **pidfile 格式坑（2026-10-12 修复）**：`/tmp/polling_trader.pid` 是 JSON 格式
> `{"pid": <PID>, "pgid": <PGID>, "start_time": <ts>}`，**不是纯数字 PID**。
> 直接 `kill -9 $(cat pidfile)` 会因为参数被解析为整段 JSON 而静默失败（进程未死、flock 不释放）。
> 必须先用 `python3 -c` 或 `jq` 提取 `.pid` 字段，或用 `grep -oE '"pid": [0-9]+'` 提取。

```bash
# 从 pidfile 提取旧 PID（JSON 格式，需解析 .pid 字段）
OLD_PID=$(python3 -c "import json;print(json.load(open('/tmp/polling_trader.pid'))['pid'])" 2>/dev/null \
          || grep -oE '\"pid\": [0-9]+' /tmp/polling_trader.pid 2>/dev/null | grep -oE '[0-9]+')

if [ -z "$OLD_PID" ]; then
  echo "[warn] pidfile 为空或不存在，旧进程已异常退出，flock 已释放"
else
  echo "[info] 旧 PID=$OLD_PID, kill -9 中..."
  kill -9 $OLD_PID 2>/dev/null
  sleep 2
  ps -p $OLD_PID > /dev/null 2>&1 && echo "[error] 旧进程仍存活" || echo "[ok] 旧进程已死"
fi

# 等待 2 秒确保 fd 关闭 + flock 释放（关键：步间隔不能省）
sleep 2

# 验证 flock 已释放（lsof 应为空）
lsof /tmp/polling_trader.pid 2>/dev/null | wc -l | xargs echo "pidfile 占用 fd 数:"
# 预期：0（flock 已释放）
```

### 步骤 4：启动新进程（保持原配置）

```bash
cd "/Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/11-易经推理系统"

nohup /opt/anaconda3/bin/python3 -m scripts.memory_l4.polling_trader \
  --interval 300 \
  --coins BTC,ETH,SOL,BNB,OKB,UNI,HYPE,PUMP,ZEC,ARB,LINK,XAU,XAG,MU,SKHYNIX,GOOGL,NVDA,AMZN,SNDK,SPCX,MSTR,COIN,CRCL,BMNR \
  --confidence 0.7955 \
  --max-positions 5 \
  --position-pct 0.20 \
  --initial-equity 200.0 \
  >> logs/trading_stdout.log 2>> logs/trading_stderr.log &

NEW_PID=$!
echo "新主进程 PID=$NEW_PID"
```

**参数说明**：
- 上述 coins/confidence/max-positions 等为当前主进程的标准配置（24 币种全量）
- 如步骤 1 提取的配置与此不同，以提取的为准
- 不推荐加 `--no-guardian`（绕过 ProcessGuardian 软警告）
- `--once` 模式跳过单例锁，用于一次性快照不阻塞主进程

### 步骤 5：验证（4 项必须全过）

```bash
sleep 5  # 等待初始化完成

# 5a. 进程状态（应活跃，CPU>0% 或在 sleep 期 CPU=0% 但 MEM 稳定）
ps -p $NEW_PID -o pid,etime,pcpu,pmem

# 5b. pidfile 内容（应是新 PID，未被截断）
cat /tmp/polling_trader.pid
# 预期：输出 $NEW_PID

# 5c. 主流程日志（应见 CBR/A7/持仓同步等初始化 INFO 日志）
tail -10 "/Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/11-易经推理系统/logs/trading_stdout.log"
# 预期：最近时间戳的 [INFO] [CBR] 案例检索增强已初始化 / [A7] 实践论门禁已初始化 等

# 5d. 单例锁生效测试（启动第二个实例应被拒绝并正确报告新 PID）
cd "/Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/11-易经推理系统"
(/opt/anaconda3/bin/python3 -m scripts.memory_l4.polling_trader --interval 300 --coins BTC --max-positions 1 2>&1 | head -3) &
TEST_PID=$!
sleep 4
wait $TEST_PID 2>/dev/null
# 预期输出：
#   [single-instance] polling_trader 已有进程运行 (PID=<新PID>)，本次启动退出。
#   [single-instance] 如需强制重启：kill -9 <新PID> && rm -f /tmp/polling_trader.pid
```

## 边界情况

### 卡死进程仍持锁

如果旧进程死锁/IO hang 但仍持有 fd（flock 不释放）：
- 提取 PID（JSON 格式，见步骤 3 坑说明）：`OLD_PID=$(python3 -c "import json;print(json.load(open('/tmp/polling_trader.pid'))['pid'])" 2>/dev/null || grep -oE '"pid": [0-9]+' /tmp/polling_trader.pid | grep -oE '[0-9]+')`
- `kill -9 $OLD_PID` 强制杀 → fd 关闭 → flock 自动释放
- **不要**用 `rm /tmp/polling_trader.pid` 解锁（锁在 fd 上不在文件上）
- 杀掉后 sleep 2 再启动新进程

### 新进程立即退出

排查顺序：
1. 看 stderr 日志：`tail -20 "11-易经推理系统/logs/trading_stderr.log"`
2. 确认旧进程已死：`OLD_PID=$(python3 -c "import json;print(json.load(open('/tmp/polling_trader.pid'))['pid'])" 2>/dev/null || grep -oE '"pid": [0-9]+' /tmp/polling_trader.pid | grep -oE '[0-9]+'); ps -p $OLD_PID`
3. 确认 flock 已释放：`lsof /tmp/polling_trader.pid` 应为空
4. 语法检查：`python3 -m py_compile "11-易经推理系统/scripts/memory_l4/polling_trader.py"`
5. PID 复用风险：如果新进程 PID 与 pidfile 中旧 PID 相同（OS 复用），flock 仍可能冲突 — sleep 2 后再启动

### pidfile 不存在或为空

如果 `/tmp/polling_trader.pid` 不存在或为空：
- 说明旧进程异常退出（被 `kill -9` 或崩溃）
- flock 已随 fd 关闭释放
- 直接启动新进程即可（`a+` 模式会自动创建文件）

## 关键文件路径

| 项 | 路径 |
|----|------|
| 源码 | `11-易经推理系统/scripts/memory_l4/polling_trader.py` |
| 单例锁位置 | L17632-17669（`main()` 函数 `args = parser.parse_args()` 之后） |
| pidfile | `/tmp/polling_trader.pid` |
| stdout 日志 | `11-易经推理系统/logs/trading_stdout.log` |
| stderr 日志 | `11-易经推理系统/logs/trading_stderr.log` |
| 工作目录 | `/Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/11-易经推理系统` |
| 解释器 | `/opt/anaconda3/bin/python3` |

## 认知关联

- 记忆 VM-1791380913941: polling_trader 单例锁根因修复经验（fcntl.flock + a+ 模式 + 持锁后才 truncate）
- 记忆 VM-1791369371282: 双进程并发问题（已修复，置信度 0.5）
- 记忆 VM-1791805721600: pidfile JSON 格式坑（kill -9 $(cat pidfile) 静默失败，必须解析 .pid 字段）
- commit 13855c8c29: 加 fcntl.flock 单例硬锁
- commit d79dd6e247: 修复 "w" 截断 PID 报告 bug

## 与其他 skill 的关系

- `safe-service-restart`: 通用服务重启硬门禁流程（commit → 验证工作区干净 → 重启 → 验证前后代码一致）。本 skill 是其针对 polling_trader 的具体实现，**额外处理 fcntl.flock 单例锁约束**（kill 旧 → 等 flock 释放 → 启动新）。
- `dream-code-commit-sync-workflow`: 代码变更自动提交流程。本 skill 假设 commit 已完成或同步执行 commit 步骤。

## 触发词

用户说以下任一即触发本 skill：
- "重启 polling_trader"
- "reload polling_trader"
- "加载新代码 polling_trader"
- "polling_trader 重启"
- "改完 polling_trader 代码了"
