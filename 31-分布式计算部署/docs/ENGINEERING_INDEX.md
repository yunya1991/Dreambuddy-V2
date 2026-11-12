# 部署资料 — 工程索引

> **版本**：v2.0 | **更新日期**：2026-11-13
> **模块定位**：主云端 `.117` 的单机部署与运维资料；分布式架构暂时不用。

## 1. 当前有效文档

| 文档 | 说明 | 时效 |
|---|---|---|
| [README.md](../README.md) | 当前部署口径与唯一入口 | 2026-11-13 |
| [TECHNICAL_DESIGN.md](./TECHNICAL_DESIGN.md) | 单机 `systemd + Docker + Nginx` 技术结构 | 2026-11-13 |
| [SERVICE_INVENTORY.md](./SERVICE_INVENTORY.md) | `.117` 服务、端口、资源和异常快照 | 2026-11-13 实测 |
| [DEPLOYMENT_CHECKLIST.md](./DEPLOYMENT_CHECKLIST.md) | 部署前后检查与当前阻断项 | 2026-11-13 |
| [API_SPEC.md](./API_SPEC.md) | 当前部署脚本与回环接口 | 2026-11-13 |
| [CHANGELOG.md](./CHANGELOG.md) | 历史变更记录 | 持续追加 |

读取规则：涉及“当前架构、当前服务、下一步部署”时，只采用上表与云端新实测；其他文档一律按历史资料理解。

## 2. 当前部署对象

| 项 | 当前值 |
|---|---|
| 主机 | `43.160.201.117`（`dreambuddy-remote`） |
| 系统与规格 | Ubuntu 24.04.5 LTS；4C16G；178G 根盘 |
| 仓库 | `/home/luke/dreambuddy` |
| 进程管理 | systemd；不再使用 PM2 作为当前服务口径 |
| 数据容器 | `dreambuddy-pg`、`dreambuddy-redis`、`dreambuddy-minio` |
| 分布式控制面 | 未启用 |
| 本地 Worker / 自动模型回传 | 未启用 |

## 3. 历史档案（暂停执行）

| 类别 | 文件 | 当前解释 |
|---|---|---|
| 原分布式方案 | [SPEC-分布式计算协同部署方案.md](./SPEC-分布式计算协同部署方案.md) | 历史设计，不是当前架构 |
| 原实施路线 | [ROADMAP-分布式计算实施路线图.md](./ROADMAP-分布式计算实施路线图.md) | 全部阶段不再自动推进 |
| 原状态清单 | [STATUS-已实现待实现清单.md](./STATUS-已实现待实现清单.md) | 2026-10-14 快照；待实现项暂停 |
| 双写与 torch | [SPEC-本地远端双写分叉治理与torch可用性.md](./SPEC-本地远端双写分叉治理与torch可用性.md)、[PLAN-本地远端双写分叉治理与torch可用性.md](./PLAN-本地远端双写分叉治理与torch可用性.md) | 历史专项资料，实施前需重新立项 |
| 架构调研 | `RESEARCH-*.md` | 理论储备；其中硬件、节点和“当前”表述均按写作日期理解 |
| 框架评审 | [REVIEW-大模型分布式框架评估与评审定稿.md](./REVIEW-大模型分布式框架评估与评审定稿.md) | 历史评审结论，不代表当前采纳 |
| 停服评估 | [REPORT-停本地服务影响面评估.md](./REPORT-停本地服务影响面评估.md) | 历史影响面，不可直接据此停服 |
| 训练协同 | [PLAN-训练协同-N13突变检测与N14广播总线.md](./PLAN-训练协同-N13突变检测与N14广播总线.md) | 暂停 |

## 4. 脚本目录

`phase1/` 至 `phase13/` 保存当时的安装、迁移和运维脚本。目录编号不等于当前阶段，也不表示已完成当前验收。

- `phase1/update.sh`：仍是代码更新相关脚本，但有交互确认、stash 和服务重启行为，使用前必须阅读并审查云端差异。
- `phase12/`、`phase13/`：健康检查和 shadow driver 等后续单元的历史安装资料；实际状态以 systemd 为准。
- 其余 `deploy/migrate/install` 脚本：默认视为历史资料，不得因文档中的“已完成”字样直接重跑。

## 5. 暂停的分布式组件

Scheduler、HeartbeatMonitor、Degrader、FallbackLib、WorkerAgent，以及 O1-O5、N1-N14 等旧编号任务全部暂停。它们不应出现在当前部署完成度、服务数量或近期优先级中。
