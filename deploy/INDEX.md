# 🤖 部署配置 (deploy/)
> **用途**: 系统部署配置，含 Hermes skills/cron/memories、运维脚本、systemd 服务
> **最后更新**: 2026-11-26

## 目录结构

| 目录/文件 | 用途 |
|:---|:---|
| [CLOUD-OPS.md](./CLOUD-OPS.md) | **云端运维手册（SSoT）**：43.160.201.117 连接事实、`dreambuddy-frontend@3001/@3002` 双实例拓扑、部署/重启/验证/排障 |
| `hermes/skills/` | 预部署技能集（14 个 trading SKILL） |
| `hermes/cron/jobs.json` | 预部署 cron 配置 |
| `hermes/memories/` | 预部署记忆（USER.md、MEMORY.md） |
| `hermes/config.yaml` | Hermes 网关配置 |
| `hermes/SOUL.md` | Hermes Agent 灵魂定义 |
| `hermes/group_poller.py` | 群消息轮询器 |
| `hermes/sitecustomize.py` | Python 站点定制 |
| `hermes/start_gateway.sh` / `start_dashboard.sh` | 网关 / 仪表盘启动脚本 |
| `hermes/channel_directory.json` | 频道目录 |
| `ops/` | 运维：launchd plist、master_daemon.py、install_all_launchd.{sh,py} |
| `ops/state/` | 守护进程状态文件（pid/json） |
| `systemd/` | systemd 服务定义（cognitive-daemon.service、dreambuddy-backup-retention.{service,timer}、dal-backup.service、dal-integrity.service） |
| `01-install-deps.sh` ~ `04-hermes-config.sh` | 分步部署脚本 |
| `deploy.sh` | 一键部署入口 |
| `git-sync.sh` / `git-setup-tracking.sh` | Git 同步 / 追踪配置 |
| `hermes-gateway.service` / `hermes-dashboard.service` / `group-poller.service` | systemd 服务单元 |

## 脚本索引

- [02-clone-and-config.sh](02-clone-and-config.sh) — 6-TRADING 腾讯云部署 — 02 代码部署 + 配置
- [03-systemd-services.sh](03-systemd-services.sh) — 6-TRADING 腾讯云部署 — 03 systemd 服务注册
- [preflight-eval-gate.sh](preflight-eval-gate.sh) — 45 评测系统 — 部署前置门禁（P3-2 / SPEC §4 §13.4）
- [quarterly-baseline.sh](quarterly-baseline.sh) — 45 评测系统 — 季度 golden set 回归（P4-6 / SPEC §8.3 §8.5）
- [ops/cleanup-cloud-backups.sh](ops/cleanup-cloud-backups.sh) — 云端磁盘治理 — 备份轮转（daily 1 份 / core dump 1 份 / 认知库备份 1 份 / next 构建 / `.tmp` 残留 / journal），由 `dreambuddy-backup-retention.timer` 每日 04:30 调用，并作为 `dal-backup.service` 的 `ExecStartPre`
- [ops/checkpoint-wal.sh](ops/checkpoint-wal.sh) — WAL 回收 — 对 DAL 主库与认知库执行 `PRAGMA wal_checkpoint(TRUNCATE)`，作为 `dal-backup.service` / `dal-integrity.service` 的 `ExecStartPost`
- [ops/runtime-data-backup.sh](ops/runtime-data-backup.sh) — 运行时数据兜底 — `runtime-data-backup.timer` 每日 03:30 备份 memory_l4 stats / trade_cases / case_statistics / causal_candidates / 认知库（**已排除 core db**，避免 18.8G 撕裂副本）
