# 31-分布式计算部署

> **当前定位**：主云端 `.117` 的单机部署与运维资料。
> **版本**：v1.0 | **更新日期**：2026-11-13
> **当前决策**：分布式协同架构**暂时不启用、不继续实施**；本目录名保留仅为兼容既有路径。

## 1. 当前有效口径

- **主云端**：`43.160.201.117`，SSH 别名 `dreambuddy-remote`。
- **云端仓库**：`/home/luke/dreambuddy`，仓库属主 `luke`。
- **运行方式**：一台云主机通过 `systemd + Docker + Nginx` 承载服务。
- **本地职责**：开发、评审和按需任务；不作为当前云端的热备、Worker 或分布式训练节点。
- **代码交付**：推送 GitHub 不等于部署；云端是否已接收代码必须单独核对 HEAD 和工作区。
- **实测基线**：2026-11-13，Ubuntu 24.04.5 LTS，4 vCPU、15GiB 内存、178G 根文件系统（已用 37%）。

当前**没有启用**以下分布式能力：Scheduler、WorkerAgent、HeartbeatMonitor、Degrader、FallbackLib、多节点训练、跨节点竞赛、联邦学习、弹性调度，以及“云端下发 → 本地训练 → 模型自动回传”链路。旧文档中的相关设计、优先级和路线图均不是当前任务。

## 2. 当前文档入口

| 文档 | 当前用途 |
|---|---|
| [TECHNICAL_DESIGN.md](./docs/TECHNICAL_DESIGN.md) | 当前单机部署结构、进程与网络边界 |
| [SERVICE_INVENTORY.md](./docs/SERVICE_INVENTORY.md) | 2026-11-13 云端实测服务、端口与异常 |
| [DEPLOYMENT_CHECKLIST.md](./docs/DEPLOYMENT_CHECKLIST.md) | 部署前后核对清单与当前阻断项 |
| [API_SPEC.md](./docs/API_SPEC.md) | 当前脚本和本机服务接口 |
| [ENGINEERING_INDEX.md](./docs/ENGINEERING_INDEX.md) | 当前资料与历史档案索引 |
| [CHANGELOG.md](./docs/CHANGELOG.md) | 文档变更记录 |

## 3. 历史方案边界

以下文档只用于追溯 2026-10 的设计和实施历史，**不得作为当前架构、运行状态或实施计划执行**：

- `SPEC-分布式计算协同部署方案.md`
- `ROADMAP-分布式计算实施路线图.md`
- `STATUS-已实现待实现清单.md`
- `SPEC/PLAN-本地远端双写分叉治理与torch可用性.md`
- `RESEARCH-*`、`REVIEW-*`、`REPORT-*` 及其他分布式训练协同计划
- `phase*/` 中的历史安装脚本

历史脚本可能包含当时的 PM2、服务清单、硬件规格和交互式操作。未重新评审、实测前，禁止直接重跑全量安装或迁移脚本。

## 4. 当前需要注意的云端事实

截至本次只读核查：

1. `yijing-polling-trader.service` 持续 `activating/auto-restart`，退出码为 1，不能标记为正常运行。
2. `dreambuddy-healthcheck.service` 为 `failed`；其 timer 仍在触发，不能据此认定巡检通过。
3. `v15-capital-api.service` 虽为 active，但 `/status` 返回空响应，需单独排查。
4. `dreamos-scheduler.service` 与 `hermes-dashboard.service` 均为 disabled + inactive，不再是旧清单中的 active 服务。
5. 云端 HEAD 为 `d7f94378e2b40d1b8b0924f19bdb7df5194c4cbd`，当时 `origin/main` 为 `5bfdbb5a1aabacbd3387f663b9555ca5a747c5c2`，且工作区存在运行态及源码修改；部署前必须审查差异，禁止直接 reset/clean。
6. PG、Redis、MinIO 以及各业务端口均只监听 `127.0.0.1`；公网监听仅见 SSH 22 与 Nginx 80。

异常明细见 [SERVICE_INVENTORY.md](./docs/SERVICE_INVENTORY.md)。本次仅更新文档，未修改或重启任何云端服务。
