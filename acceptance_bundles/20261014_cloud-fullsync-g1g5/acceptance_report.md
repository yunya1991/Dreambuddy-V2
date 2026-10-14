# 验收报告 — 云端全量一致性修复 (G1~G5)

- 验收对象：远端 43.160.201.117（VM-0-5-ubuntu）子系统全量部署一致性修复 G1~G5
- 验收时间：2026-10-14 12:00（UTC 04:00）
- 远端 HEAD：`610fea04ba56f98df575f32a4e6ab2c8d85def22`
- 本地 commit（代码侧）：`ae2904ab41`

## 五维证据

### 1. 症状复测（原步骤复测，症状消失）✅
| 缺口 | 复测 | 结果 |
|---|---|---|
| G1 frontend | `curl :3001/` | 307（重定向正常，非崩溃） |
| G2 yijing-data-server | `curl :8765/` | 200 |
| G5 M25 | `curl :8095/health` | 200 |
| 全量服务 | `systemctl is-active` × 19 | 全部 active |
| 全量 timers | `systemctl is-active` × 9 | 全部 active |
| 崩溃循环 | `NRestarts` | frontend/yijing/hermes-gateway/group-poller/hermes-dashboard/m25 全为 0 |

### 2. 日志证据（证明路径执行）✅
- `hermes-gateway` MainPID=3544333，`/proc/3544333/cgroup = 0::/system.slice/hermes-gateway.service`（归属 systemd 单元）
- gateway 日志：`[Lark] connected to wss://msg-frontier.feishu.cn/ws/v2...`（Feishu websocket 已连接）
- systemd：`hermes-gateway.service Active: active (running) ... enabled`

### 3. 回归证据（测试全绿）⚠️ 条件通过
- `python3 -m py_compile`：5 改动 py 文件全部通过（exit 0）
- `npx tsc --noEmit`：18 处报错，**全部为既有 Prisma 类型债**（`config/strategies`、`kyc`、`recharge`、`user/*`），**改动文件 `next.config.ts` / `module-api-client.ts` 0 报错**
- 结论：本变更集不引入新类型错误；既有 18 处为技术债（红旗 T1）

### 4. 影响面核查（diff 范围 = 声明）✅
- 提交 `ae2904ab41`：17 files changed, +586/-44；与收尾声明范围一致
- 排除的运行时数据：`12-三屏趋势系统/signal_pool/pool.json`、`23-.../gene_data/architecture_health_report.json`（每次运行自变，不入库）

### 5. 边界验证 ✅
| 边界 | 验证 | 结果 |
|---|---|---|
| 外网可达性 | `curl api.openai.com` | 401（秒回，外网正常） |
| 跨地域端点 | `curl token-plan.cn-beijing.maas.aliyuncs.com` | rc=28 超时（DNS 仅 IPv6）→ 红旗 R1 |
| 容器健康 | `docker ps` × 3 | 全 healthy |
| 进程管理一致性 | `pm2 list` | 空（M25 已迁 systemd） |

## 红旗清单
- **R1（未解决·用户决定记录）**：云端无法访问 Qwen 端点 `token-plan.cn-beijing.maas.aliyuncs.com`（DNS 仅 IPv6，curl 12s 超时 rc=28）→ Hermes 依赖 LLM 的 cron 作业失败（`GroupMentionProcessor-60s` 反复 `Connection error`，日志 5 次）。网关自身飞书消息收发不受影响。
- **R2（已消解）**：cron workdir 警告来自修复前历史日志；当前 `jobs.json` 全部 `workdir=/home/luke/dreambuddy`。
- **R3（未解决·次要）**：gateway 单元 `TimeoutStopSec=90s < drain_timeout=120s`，systemd 可能在 drain 中途 SIGKILL。建议 `hermes gateway install --force` 或缩短 `agent.restart_drain_timeout`。
- **R4（未解决·脚本漂移）**：`05-deploy-classic-modules.sh` 仍用 PM2 启动 M25~M28，与实际 systemd 部署不一致。
- **T1（技术债）**：前端 18 处既有 Prisma 类型错误（非本次引入）。

## 判定
- **核心 G1~G5：PASS**（服务/单元/端口/归属全部复现通过）
- **整体：⚠️ 条件通过**（R1 经用户确认「记录红旗、继续收尾」）
