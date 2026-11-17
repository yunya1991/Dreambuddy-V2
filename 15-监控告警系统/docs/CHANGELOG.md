# 变更记录 — 15-监控告警系统

> **版本**: v2.4 | **更新日期**: 2026-11-17

---

## 版本变更记录

| 版本 | 日期 | 变更内容 | 影响范围 |
|------|------|----------|----------|
| v2.4 | 2026-11-17 | 告警通道接通：复用 hermes-gateway 飞书应用凭证，部署 receiver(:9098) + watchdog(5min)；联调消息已送达 Trading-Desk | 代码+运维 |
| v2.3 | 2026-11-17 | 23 切实盘（移除 `--dry-run`、开关置 on）；监控进入 14 天 alert_only（至 2026-12-01）；记录切换前权益/持仓预检 | 配置+运维 |
| v2.2 | 2026-11-17 | 一期收敛为 23 推理信号链（TD 第 12 章）：23 模块全景、v1.1 契约差异、8 步生命周期、10 条信号告警、落地审计；`monitoring.yaml` 增 signals 段、`domains.yaml` 分期调整 | 文档+配置 |
| v2.1 | 2026-11-17 | 新增 3+3 全景监控架构（TD 第 11 章）与 `config/domains.yaml` 域注册表：三层×三链矩阵、四期覆盖、M0–M5 成熟度、一格一 owner | 文档+配置 |
| v2.0 | 2026-11-17 | 新增云端全链路监控目标架构（TD 第 10 章）、调研 v0.2、API v1.1 草案；建立代码骨架 `exporter/ receiver/ deploy/ scripts/`；新增 12 条告警规则与 Pushgateway 接入模板 | 文档+骨架 |
| v1.0 (文档补建) | 2026-09-30 | 补建 `docs/API_SPEC.md`、`docs/CHANGELOG.md`，完善模块文档体系 | 文档 |
| v1.0 | 2026-08-02 | 补建 `docs/ENGINEERING_INDEX.md`、`docs/TECHNICAL_DESIGN.md`，对齐 DOC_STANDARD L3 模块文档建设规范 | 文档 |
| — | 2026-07-27 | 模块运行中，产生首个故障事件记录 `INC-20260727111511.json` | 运行数据 |

---

## 详细变更

### v2.4 — 2026-11-17

**告警通道**
- 复用 `hermes-gateway` 使用的飞书应用凭证（`~/.hermes/.env`），写入 `/etc/dreambuddy-monitoring/monitoring.env`（600 root）
- 新增 `receiver/feishu_receiver.py`：`/alert`（Alertmanager v4）、`/notify`（watchdog）、`/healthz`；按 P0/P1/P2/P3 路由到 RiskControl/Desk/Management，30min 去重
- 新增 `scripts/watchdog.py` + 5min timer：entry23/exit23 存活、entry23 日志 10min 新鲜、审计文件 24h、磁盘 90%
- 联调：`POST /notify` 返回 `{"sent": true}`，消息已送达 Trading-Desk
- 全部为 alert_only，无任何自动冻结或阻断

### v2.3 — 2026-11-17

**23 切实盘**
- `23/deploy/dreambuddy-entry23.service`：移除 `--dry-run`，`EVOLUTION_ENTRY23_ENABLED=off → on`
- 预检：权益 2118.10 USDT / 可用 919.05 / 冻结 1200.19 / 永续持仓 0；凭据库 `simulated=false,dry_run=false`
- 切换后 `expected_mode: live`；`DryRunMismatch` 语义由"实盘未开"转为"实盘被意外关闭"

**监控策略**
- 2026-11-17 至 2026-12-01 为 `alert_only`：只告警，不自动冻结/阻断
- 到期复核误报率与信号质量后，再启用 §10.7 D2 的自动动作

### v2.2 — 2026-11-17

**一期范围**
- 一期由「交易列三层」收敛为「23 推理信号链」；40 主神经网络闭环顺延二期，只保留 L0 存活探针
- `config/domains.yaml` 分期改为：一期 23 → 二期 40 → 三期训练链 → 四期产品链 → 五期横切

**23 信号监控（TD 第 12 章）**
- 模块全景、v1.1 契约字段与实测差异（23 缺 `horizon/risk_exposure_hint/mode` 及 payload 12 字段）
- 8 步生命周期：数据→生成→契约→审计→发件箱→网关→风控成交→回报反馈
- 10 条信号告警：Schema/Silence/Expired/DryRunMismatch/OutboxStuck/RejectSpike/RiskGateEmpty/Duplicate/FillJoin/ConfidenceDegenerate
- 落地审计：22 无 JSON Schema 校验、云端 entry23 为 dry-run、23 审计仅 submit 阶段、outbox 为 SQLite

**配置**
- `config/monitoring.yaml` 新增 `signals` 段；`execution_decisions_23` TTL 24h→30min
- `docs/API_SPEC.md` 增加 13 个信号级指标

### v2.1 — 2026-11-17

**架构**
- `docs/TECHNICAL_DESIGN.md` 第 11 章：3+3 全景监控架构（L0/L1/L2 × 交易/训练/产品），四期覆盖，一期只要求交易列 ≥M3、其余 ≥M1
- 管理机制：`config/domains.yaml` 单点注册（owner/phase/maturity/probes/slo/runbook）、统一 `chain/layer/cell/module` 标签、3×3 热力图、月度覆盖评审

**配置**
- 新增 `config/domains.yaml`：9 格 + 横切治理，含状态机 `draft→active→paused→retired` 与命名约定

### v2.0 — 2026-11-17

**架构与调研**
- `docs/TECHNICAL_DESIGN.md` 升级 v2.0：新增第 10 章「云端全链路监控目标架构」，含云端实测基线、五层探针、TTL 矩阵、P0–P3 治理、D1–D6 决策、实施验收；第 1–9 章降级为本地 v1.0 现状
- 新增 `docs/RESEARCH-全链路监控体系调研-v0.2.md`：40 链 12 节点、23 链 9 节点、SRE/金融监控框架、GitHub 选型、云端证据

**代码骨架（未实现）**
- `exporter/`：业务只读指标导出器（probes/tests 占位）
- `receiver/`：Alertmanager→飞书 webhook 接收器（占位）
- `config/monitoring.yaml`：TTL、任务节奏、链路阈值、域名义上限、告警治理参数
- `deploy/`：Compose、Prometheus、12 条规则、Alertmanager、Grafana provisioning、blackbox、systemd unit
- `scripts/push_job.sh`：cron/systemd 任务末尾推送运行/成功/耗时/记录数

**文档**
- `docs/API_SPEC.md` v1.1：新增 §6 监控接口草案（`/metrics`、`/alert`、`/healthz`）

### v1.0 (文档补建) — 2026-09-30

**文档建设**
- 新建 `docs/API_SPEC.md`：覆盖核心层（UnifiedMonitor/MonitorAdapter/MonitorResult/MonitorStatus）、适配器层（5 个 MonitorAdapter 子类）、告警层（send_alert + 13 个 notify_* 业务函数）、持仓同步层（PositionSyncService/PositionSyncAdapter + 3 个 SyncAdapter 子类）、调度层（run_monitor/run_position_sync/main/shadow_resistance_gene_mvp）、记忆层（OpsMemoryInterface 14 个方法）的全部公开接口签名、参数表、示例、错误处理
- 新建 `docs/CHANGELOG.md`：本文件

### v1.0 — 2026-08-02

**文档建设**
- 新建 `docs/ENGINEERING_INDEX.md`：模块定位、目录地图、6 层文件清单（调度/核心/适配器/告警/持仓同步/记忆）、核心流程索引、配置参数索引、测试体系、技术债务、快速导航
- 新建 `docs/TECHNICAL_DESIGN.md`：概述、6 层架构、5 个核心算法（告警路由/健康检查优先级短路/BCRM2.0 双维度自检/双层调度/外部平仓二次确认）、数据流、接口设计、状态管理、配置管理、错误处理、扩展性设计

---

## 代码能力清单（按模块）

> 以下为当前代码已实现的能力清单，供变更追溯参考。

### 核心层（monitor_core.py）
- `MonitorStatus` 四级状态枚举（healthy/warning/critical/unknown）
- `MonitorResult` 结果对象（to_dict / is_healthy）
- `MonitorAdapter` 适配器基类（check_health + 4 个可选维度方法）
- `UnifiedMonitor` 统一管理器（三级配置回退 / 5 适配器实例化 / monitor_all / get_all_metrics / send_alerts）

### 适配器层（adapters/__init__.py）
- `YijingAdapter`：心跳 + 风控 + 性能 + BCRM2.0 双维度自检（日志扫描 6 关键字 + 模型缓存 48h 新鲜度）
- `V15Adapter`：心跳超时 + 连续亏损 ≥5 警告
- `ScreenAdapter`：心跳超时 + 三屏趋势指标
- `AgentAAdapter` / `AgentBAdapter`：日志时间戳心跳 + 记忆指标

### 告警层（feishu_alert.py）
- `send_alert` 通用入口 + 飞书 schema 2.0 卡片构建
- 13 个业务告警函数（heartbeat/process_error/trading_halted/consecutive_losses/model_error/position_close/system_error/performance_degrade/status_summary/trade_execution/system_start/system_stop）
- 四级路由（critical/error→risk, warning→trading, info→management）
- 凭证缺失降级（FEISHU_CREDENTIALS_VALID）

### 持仓同步层（position_sync.py）
- `PositionSyncService`：OKX 客户端延迟加载、外部平仓二次确认（窗口 + 次数）、API 故障保护、自动备份
- 3 个同步适配器（V15/Yijing/Screen）
- dry_run 只读模式

### 调度层（scheduler.py）
- 双层调度（60min 完整监控 + 5min 持仓同步）
- dreambuddy-v2 MVP L1×L2 影子调度（UTC 00:05，FO-7 熔断 ≥5 次失败）

### 记忆层（memory/app_memory_interface.py）
- `OpsMemoryInterface`（AM-OPS-001）：incident/playbook 增删改查、蒸馏候选、健康检查、相似案例检索

---

**文档版本**: v2.4
**最后更新**: 2026-11-17
