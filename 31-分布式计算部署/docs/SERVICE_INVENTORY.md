# 主云端服务与端口清单

> **版本**：v1.0 | **更新日期**：2026-11-13
> **实测时间**：2026-11-13 02:03-02:05（Asia/Shanghai）
> **对象**：`dreambuddy-remote` / `43.160.201.117`
> **性质**：只读实测快照，不是“期望全部 active”的部署目标，也不代表本地服务清单。

## 1. 主机与代码

| 项 | 实测值 |
|---|---|
| 系统 | Ubuntu 24.04.5 LTS |
| CPU / 内存 | 4 vCPU / 15GiB（available 约 10GiB） |
| 根文件系统 | 178G，已用 63G（37%），可用 108G |
| Swap | 7.9GiB，已用 2.3GiB |
| 仓库 | `/home/luke/dreambuddy`，分支 `main` |
| 云端 HEAD | `d7f94378e2b40d1b8b0924f19bdb7df5194c4cbd` |
| 当时 origin/main | `5bfdbb5a1aabacbd3387f663b9555ca5a747c5c2` |
| 工作区 | 非干净；含运行态文件及 `scheduler.py`、`fundamental_snapshot.py`、`sentiment_engine.py` 等源码修改 |

结论：云端代码与 GitHub 当时不一致，且存在本地修改。更新前必须逐项查明来源，不能直接 reset/clean，也不能把 GitHub HEAD 当作云端实际运行版本。

## 2. 常驻服务实测

### 2.1 active/running

| 分类 | 服务 |
|---|---|
| 入口与数据 | `nginx.service`、`dreambuddy-frontend.service`、`product-hub.service`、`yijing-data-server.service`、`fundamental.service` |
| 经典模块 | `m25-strategy-generation.service`、`m26-strategy-lib.service`、`m27-governance.service`、`m28-signal-trigger.service` |
| V15 / 风控 | `v15-api.service`、`v15-capital-api.service`、`trailing-stop-runner.service` |
| 数据与训练 | `datacenter-scheduler.service`、`dreambuddy-continual-training.service`、`etl-worker.service`、`signal-scanner.service` |
| 认知与编排 | `cognitive-daemon.service`、`dreamos-dynamic-evaluator.service`、`yijing-emergence-shadow-probe.service` |
| 消息 | `hermes-gateway.service`、`group-poller.service` |

注意：`active/running` 不等于业务健康。`v15-capital-api.service` 的 `/status` 实测返回空响应；`hermes-gateway.service` 当前 active，但 unit 为 disabled，不能假定重启机器后会自动恢复。

### 2.2 异常或未运行

| 服务 | 实测状态 | 当前结论 |
|---|---|---|
| `yijing-polling-trader.service` | activating/auto-restart；exit 1；重启计数超过 12300 | **持续崩溃，旧文档“已上线/正常”结论失效** |
| `dreambuddy-healthcheck.service` | failed；exit 1 | 健康检查未通过，需查具体失败项 |
| `dreamos-scheduler.service` | disabled + inactive | 不再是旧清单中的 active 服务 |
| `hermes-dashboard.service` | disabled + inactive | 不再运行，未观察到 9119 监听 |
| `ab-monitor.service`、`ab-orchestrator.service` | inactive/dead | oneshot 静息态；需结合 timer 和最近结果判断，不按常驻服务计算 |

## 3. Timer 观察

实测存在 NEXT 的项目 timer 包括：

- 交易与监控：`v15-poll-light`、`v15-orchestrator`、`yijing-monitor`、`ranking-trigger`、`dreambuddy-healthcheck`。
- 数据与维护：`datacenter-backfill`、`datacenter-auto-archive`、`dal-backup`、`dal-rotate`、`dal-integrity`、`dreambuddy-snapshot`、`runtime-data-backup`。
- 训练/研究：`dreambuddy-windowed-collect`、`dreambuddy-ablation-loop`、`dreambuddy-decision-replay`、`dreambuddy-emergence-metrics`、`dreambuddy-accumulation-gate`。
- 语义与事件：`dreambuddy-aggregate-events`、`dreambuddy-atomic-events`、`dreambuddy-semantic-events`、`dreambuddy-event-lines`、`dreambuddy-trade-cases`、`dreambuddy-case-stats`、`dreambuddy-complex-semantics`、`dreambuddy-contradiction`、`dreambuddy-newsflash-weights`、`dreambuddy-spacetime`、`dreambuddy-l3-synthesis`。
- 其他：`ab-monitor`、`ab-orchestrator`、`memory-cleanup`、`dreamos-evaluator-daily-restart`、`dreambuddy-shadow-driver`、`dreambuddy-shadow-rotate`、`docs-sync`、`index-reconcile`、`job-runs-audit`。

特别偏差：

- `dreambuddy-continual-training.timer` 当时无 NEXT，最后触发停留在 2026-10-29；但同名常驻 service 为 active/running。不得再写成“每 30 分钟 timer 正常运行”。
- `dreambuddy-healthcheck.timer` 有 NEXT 且近期触发，但 service failed，说明“timer active”不等于“检查通过”。
- 完整 timer 很多且持续变化，本清单不沿用旧文档的固定数量作为健康指标。

## 4. 端口与容器

### 4.1 业务及数据端口

| 端口 | 绑定 | 归属/状态 |
|---:|---|---|
| 3001 | 127.0.0.1 | 主前端；`/` HTTP 307 |
| 3456 | 127.0.0.1 | 产物中台 |
| 8093 / 8094 / 8095 / 8096 | 127.0.0.1 | M26 / M27 / M25 / M28 |
| 8765 | 127.0.0.1 | 易经数据服务；`/` HTTP 200 |
| 8771 | 127.0.0.1 | V15 API；`/health` HTTP 200 |
| 8770 | 127.0.0.1 | V15 资金 API；`/status` 空响应 |
| 9094 | 127.0.0.1 | 基本面服务 |
| 5432 / 6379 / 9000 / 9001 | 127.0.0.1 | PG / Redis / MinIO |
| 8790 | 127.0.0.1 | 本次未核实归属，不做推断 |
| 22 / 80 | 0.0.0.0 | SSH / Nginx；本次公网监听仅见这两项 |

Docker：`dreambuddy-pg`、`dreambuddy-redis`、`dreambuddy-minio` 均为 healthy，端口只映射到回环地址。

## 5. 当前优先核对项

1. 查明 `yijing-polling-trader` exit 1 的应用日志和依赖，停止把重启计数当作运行成功。
2. 查明 `dreambuddy-healthcheck` 的失败项，再修复检查或服务本身。
3. 核对 `v15-capital-api /status` 空响应及日志，不能只看 active。
4. 审查云端与 GitHub 的版本差和工作区源码修改，明确保留、提交或回退每一项的依据。
5. 确认 `dreamos-scheduler`、`hermes-dashboard` 的停用是否为当前预期，避免旧文档误导运维。

本次未修改配置、未重启服务、未执行部署脚本。
