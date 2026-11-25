---
name: dreambuddy-cloud-ops
description: Connect to and operate the DreamBuddy cloud host 43.160.201.117 over SSH — deploy frontend builds, restart systemd services, verify health endpoints, and diagnose degraded APIs. Use when syncing code to cloud, deploying or restarting cloud services, or checking cloud runtime state. Do not use for local-only changes.
---

# DreamBuddy Cloud Ops — 云端连接与运维

## 一、适用与边界

触发：云端部署、云端重启、远端与云端同步、云端接口异常排查、`43.160.201.117`、`.117`、云端复验。

不触发：纯本地改动、纯文档同步、跨工作区代码修改。

边界：本 SKILL 只负责「连接 → 部署 → 重启 → 验证 → 排障」。代码改哪归哪个工作区，不在此处扩展。

## 二、连接事实（先读，避免试错）

| 项 | 值 |
|---|---|
| SSH 别名 | `dreambuddy-remote`（建议 `~/.ssh/config` 固定，主机 `43.160.201.117`） |
| SSH 用户 | `ubuntu`（有免密 sudo） |
| 仓库属主 | `luke`，仓库 `/home/luke/dreambuddy` |
| 前端目录 | `/home/luke/dreambuddy/3.1-FRONTEND`（`.next` 在此，**不在仓库根**） |
| 前端服务 | `dreambuddy-frontend@3001.service` 与 `dreambuddy-frontend@3002.service`（模板 `dreambuddy-frontend@.service`，`ExecStart=/usr/bin/pnpm exec next start -p %i -H 127.0.0.1`）；Nginx upstream `dreambuddy_next` 同时在 3001/3002 间负载均衡；不存在 `dreambuddy-frontend.service` 这个普通单元 |
| Python 解释器 | `/home/luke/venv-trading/bin/python` |
| 前端 systemd 环境 | 仅 `COGNITIVE_PYTHON=/home/luke/venv-trading/bin/python`；**未配** `DSH_API_BASE`、`NEXT_PUBLIC_BRIDGE_URL` |
| 51 venue bridge | `okx-venue-bridge.service`，`127.0.0.1:8097`，token 在 `51-OKX CLI 系统/runtime/audit/bridge_token` |
| 备份目录 | 前端构建 `/home/luke/deploy-backups/`；DAL 库 `/home/luke/dreambuddy/19-数据访问层/data/backups/`；运行时数据 `/home/luke/runtime-data-backup/daily/`；只读快照 `/home/luke/sync-snapshots/` |
| 旧模块 | `31-分布式计算部署`、`update.sh`、PM2 流程**已过时**，不要照旧文档执行 |

权限写法固定：

```bash
ssh -o ConnectTimeout=15 -o ServerAliveInterval=5 dreambuddy-remote '<cmd>'
sudo -n -u luke git -C /home/luke/dreambuddy ...
sudo -n systemctl ...
```

## 三、连接纪律（SSH 不稳定是常态）

1. 每次都带 `-o ConnectTimeout=15 -o ServerAliveInterval=5`。
2. 出现登录横幅后 `Connection closed by remote host`：属间歇性，隔几秒重试同一条命令；不要改方案、不要反复循环。
3. 单条命令尽量短；循环探测 + 长输出容易断。需要多步时拆成多次调用，先探活再执行。
4. 长任务（构建）必须后台化并落日志，稍后用日志判断成败：

```bash
sudo -n -u luke bash -lc "cd /home/luke/dreambuddy/3.1-FRONTEND && setsid nohup pnpm build > /tmp/build-<sha>.log 2>&1 < /dev/null & echo started"
```

5. **禁止**用含目标字符串的 `pkill -f "pnpm build"` / `pkill -f "next build"`：`ssh` 远端 shell 自身命令行会命中，导致自杀式中断。用 `pgrep -x` 或按已记录的 PID 精确处理。
6. SSH 中途断开时，**默认远端命令未执行**。涉及 `systemctl restart` 等关键动作，必须另起一次调用核对结果，不能凭「已发送」判定成功。

## 四、标准前端部署流程

前置：本地工作树干净、只 stage 本工作区文件；`local HEAD = origin/main`。

1. 本地 commit + `git push origin main`。
2. 云端快进（不做 `reset --hard`）：

```bash
sudo -n -u luke git -C /home/luke/dreambuddy fetch origin main --quiet
sudo -n -u luke git -C /home/luke/dreambuddy merge --ff-only origin/main
sudo -n -u luke git -C /home/luke/dreambuddy rev-parse --short HEAD   # 必须等于新 SHA
```

3. 备份当前 `.next`：

```bash
sudo -n -u luke bash -lc "cd /home/luke/dreambuddy/3.1-FRONTEND && cp -a .next /home/luke/deploy-backups/next-<旧sha>-$(date +%Y%m%d)"
```

4. 后台构建（见 §三.4）。轮询日志，成功标志：`Compiled successfully` + `Route (app)`；失败标志：`Failed to compile`。同一时间只允许一个构建，发现多个 `next build` 先处理再重建，否则 `.next` 会被写坏。
5. 重启并**核对时间戳**：

```bash
sudo -n systemctl restart dreambuddy-frontend@3001.service dreambuddy-frontend@3002.service
systemctl is-active dreambuddy-frontend@3001.service dreambuddy-frontend@3002.service
systemctl show -p ActiveEnterTimestamp --value dreambuddy-frontend@3001.service dreambuddy-frontend@3002.service
cat /home/luke/dreambuddy/3.1-FRONTEND/.next/BUILD_ID
```

`ActiveEnterTimestamp` 必须晚于构建完成时间；否则就是「代码新、进程旧」，重新重启。

6. 端点复验（见 §五），通过后才算部署完成。

## 五、验证端点与预期结果

| 端点 | 预期 | 说明 |
|---|---|---|
| `/login` | 200 | 公共页可达 |
| `/dashboard/*` | 307 → `/login` | 生产 `AUTH_REQUIRED` 生效，属正常 |
| `/api/cognitive/health` | 200 healthy | 含 memories/distill 计数 |
| `/api/cognitive/recall?context=x&top_k=1` | 200，约 10–15s | 仅 GET；POST 返回 405 |
| `/api/product/entitlement` | 200 | 默认产品包 `active` |
| `/api/billing/balance` `/api/billing/usage` | 200 | 算力计费 |
| `/api/plugins` `/api/plugins/audit` | 200 | 插件与审计 |
| `/api/venue/health` `/api/venue/credentials` | 200 | 51 bridge 已启动 |
| `/api/venue/account/balance` | 409 `venue_credentials_missing` | 未配凭证时的正确 fail-closed |
| `/api/dsh/execute` | 503 `configured:false` | 未配 `DSH_API_BASE` 的设计行为 |

DSH 走 HTTP 不可用时，用 IPC 适配器证明链路：

```bash
cd /home/luke/dreambuddy/3.1-FRONTEND && /home/luke/venv-trading/bin/python scripts/dsh_adapter.py knowledge_search '{"query":"认知","top_k":2}'
```

返回 `{"ok": true, ... "degraded": false}` 即链路通；结果为空是索引数据问题，不是链路故障。

## 六、排障决策树

- **接口 503 `timeout_10000ms`**：先手工计时 `scripts/cognitive_adapter.py recall '{"context":"x","top_k":1}'`；若耗时 > 前端超时，属于超时配置问题，不是后端故障。
- **接口返回旧行为**：按 §四.5 核对进程启动时间与 BUILD_ID；不要只看 `git rev-parse`。
- **构建跑很久**：检查是否多个 `next build` 并存；确认后终止多余进程，`rm -rf .next` 再单进程重建。
- **认知后端降级**：`dsh_frontend_bridge.py` 的 `ssh-stdio` 在同机未配 `DSH_SSH_HOST` 时应降级 stdio；先验证 adapter 直连，再查 registry 的 transport。
- **venue 503 `bridge_token_missing`**：先 `systemctl status okx-venue-bridge.service`，再确认 token 文件存在。
- **systemd unit 写入失败**：不要用 heredoc 经 ssh 写 unit；本地生成文件 → `scp` 到 `/tmp` → `sudo -n cp` 到 `/etc/systemd/system/` → `daemon-reload`。

## 七、磁盘与备份治理

### 8.1 空间大户（178G 根分区 baseline）

| 路径 | 量级 | 管控方式 |
|---|---|---|
| `19-数据访问层/data/dreambuddy_core.db` | 15~20G | 主库；膨胀见 §8.4 |
| `19-数据访问层/data/backups/` | 每日 core dump + 一次性认知库备份 | `cleanup-cloud-backups.sh` 轮转 |
| `runtime-data-backup/daily/` | 每份约 12G | 只保留最新 1 份 |
| `sync-snapshots/` | 旧 core 快照 + 认知库副本 | 保留 1 份 + 清理 >1 天 `.tmp*` |

### 8.2 保留策略（`deploy/ops/cleanup-cloud-backups.sh`）

| 常量 | 值 | 含义 |
|---|---|---|
| `KEEP_DAILY` | 1 | runtime-data-backup/daily 份数 |
| `KEEP_CORE_DUMPS` | 2 | 每日 DAL core dump 份数（含 sha256） |
| `KEEP_COGNITIVE_DUMPS` | 1 | `backups/` 中一次性 `cognitive_memory*.db` 份数 |
| `KEEP_NEXT_BUILDS` | 2 | 前端可回滚构建 |
| `JOURNAL_MAX` | 200M | systemd journal 上限 |

脚本同时清理 `backups/*.db.tmp*`（>1 天且无进程占用）——**失败备份残留的主要来源**。
由 `dreambuddy-backup-retention.timer` 每日 04:30 执行；`dal-backup.service` 也会在备份前以其作为 `ExecStartPre` 先腾空间。

### 8.3 备份失败防护（2026-11-25 事故复盘）

事故链：主库涨到 18G → `VACUUM INTO` 需要额外等量空间 → 根分区剩余不足 → `sqlite3.OperationalError: database or disk is full` → 遗留 3.5G `.tmp` 残留 → 清理脚本不匹配 `.tmp` → 空间只减不增 → 分区 99%。

已落地三道防线：
1. `backup.py` 备份前做空间预检（需 `库大小 × 1.2` 可用空间），不足时明确报错并提示先跑 cleanup；
2. 备份失败时 `finally` 清理 `.tmp` 与 `-journal`，不再留垃圾；
3. `dal-backup.service` 增加 `ExecStartPre` 调用 cleanup，先按保留策略腾空间。

排障命令：

```bash
# 空间大户
sudo du -x -d1 / | sort -rn | head
sudo du -x -d1 /home/luke | sort -rn | head
# 备份失败原因
sudo tail -30 /home/luke/logs/datacenter/dal-backup.err.log
systemctl status dal-backup.service --no-pager -l
```

### 8.4 主库膨胀定位

29 张表，`PRAGMA freelist_count = 0`（非碎片问题），膨胀集中于 `mm_metric_vintages`（WITHOUT ROWID 指标历史表，全表 COUNT 超过 2 分钟）。其余表合计不足 1G。

处置方向：按 `source` 设保留窗口清理历史分区，采集侧改幂等 upsert（`observed_at` 用数据时间而非采集时间，避免重复累积），清理后执行一次 `VACUUM INTO` 重建库。

## 八、硬性禁止

- 不在云端 `git reset --hard`、`git clean -f`、`push --force`。
- 不把其他工作区的脏文件一起提交；云端不 `git add -A`。
- 不在验证前宣称「已上线」。必须给出：新 SHA、BUILD_ID、`ActiveEnterTimestamp`、端点状态码。
- 不泄露 token / 密钥内容，只报告是否存在。

## 九、与既有 SKILL 的关系

`dream-code-deploy-pipeline` 中的 PM2、`31-分布式计算部署`、`update.sh` 部分已过时；云端现状以本 SKILL 为准，该 SKILL 仅保留 GitHub CI 与回滚思路参考。
