# SERVICE_INVENTORY — 本地/云端服务盘点清单

> **文档定位**：P0 服务盘点（本地算力"全部转训练"改造的输入依据）
> **版本**：v0.1 | **创建日期**：2026-10-14
> **状态**：P0 完成（组 1 ⚠️ 项已对齐云端）
> **关联**：[SPEC-分布式计算协同部署方案.md](./SPEC-分布式计算协同部署方案.md) · [SPEC-本地远端双写分叉治理与torch可用性.md](./SPEC-本地远端双写分叉治理与torch可用性.md) · [全量远端部署方案.md](../../.trae/documents/全量远端部署方案.md)

## 0. 盘点方法（证据级）

| 侧 | 方法 | 权威性 |
|---|---|---|
| 云端 | SSH `dreambuddy-remote`（43.160.201.117，4C8G/120G）：`systemctl list-units/list-unit-files`、`ss -tlnp`、`ps aux`、`docker ps` | **权威**（实测） |
| 本地 | `~/Library/LaunchAgents/*.plist` 全量解析 + `ps aux` + `lsof -iTCP -sTCP:LISTEN` | 实测 |

> 本次 SSH 复核期间出现 2 次 `banner exchange timeout`（属既有偶发，见 PLAN §风险）；下表云端结论以**本轮成功查询**为准，个别 unit 命名标注"待复核"。

---

## 1. 云端权威清单（实测）

### 1.1 常驻服务（systemd，active running）

| 服务 | 端口/职责 |
|---|---|
| `v15-api.service` | 8771 V15 策略 API |
| `v15-capital-api.service` | 8770 资金管理 API |
| `yijing-data-server.service` | 8765 易经数据服务 |
| `yijing-polling-trader.service` | BCRM2 + Strategy + BDSM 轮询交易 |
| `dreambuddy-frontend.service` | 3001 Next.js 15.5.26（主前端） |
| `product-hub.service` | 3456 Next.js 14.2.35（产物中台） |
| `datacenter-scheduler.service` | 18 采集调度（含 18→19 回填） |
| `cognitive-daemon.service` | 认知库文件变更守护 |
| `dreamos-scheduler.service` | DreamOS 编排 |
| `dreamos-dynamic-evaluator.service` | 动态评估（6h） |
| `fundamental.service` | 9094（`ml_trade_service_v2.py --port 9094 --no-collect`） |
| `m25-strategy-generation.service` | 8095 M25 用户策略生成 |
| `m26-strategy-lib.service` | 8093 M26 策略管理 |

### 1.2 Timer / oneshot

| 单元 | 周期 | 状态 |
|---|---|---|
| `v15-poll-light.timer` | 5min | enabled |
| `v15-orchestrator.timer` | 15min | enabled |
| `datacenter-backfill.timer` | 每小时 :15 | enabled |
| `dreambuddy-snapshot.timer` | **每 10min** | enabled |
| `dal-integrity.timer` | 6h | enabled |
| `dal-backup.timer` | 04:00 | enabled |
| `dal-rotate.timer` | 05:00 | enabled |
| `ranking-trigger.timer` | (Stage6) | **enabled** |
| `yijing-monitor.timer` | (Stage6) | **enabled** |
| `dreambuddy-continual-training.timer` | **每 30min** | **enabled**（34 训练系统已上云） |
| `screen-cleanup.service` | — | **masked** |

### 1.3 数据层（Docker）与端口

- Docker：`dreambuddy-pg`(5432) · `dreambuddy-redis`(6379) · `dreambuddy-minio`(9000/9001)
- `ss -tlnp` 实测监听：**8770 / 8771 / 8765 / 9094 / 8093 / 8094 / 8095 / 8096 / 3001 / 3456**（+ 127.0.0.1 的 5432/6379/9000）
- Nginx：`/` → 3001、`/api/v15/` → 8771、`/api/capital/` → 8770、`/api/trend/` → 8765、`/api/fundamental/` → 9094
- **Hermes**：`hermes-gateway` / `group-poller` / `hermes-dashboard` 均 **enabled + active**（:9119 监听；2026-10-14 已启用，G0-2 闭环）

---

## 2. 本地清单（LaunchAgents 实测）

### 组 A｜已被云端覆盖（本地冗余）

`v15_light_poll`(300s)、`v15_orchestrator`(900s)、`yijing_data_server`、`dreambuddy.yijing.polling-trader`、`yijing_trading`(3600s)、`yijing_live_300s`、`yijing_monitor`(4h)、`datacenter`(keepalive)、`dc-scheduler`(keepalive)、`dreamos`、`ranking-trigger`(4h)

### 组 B｜云端**部分未部署**（本地独有）— 2026-10-14 更新：`signal_scanner` / `memory_cleanup` 已补云端

`trailing-stop-runner`(`--real`,300s)、`signal_scanner`(12-三屏,300s → ✅ **已补云端** `signal-scanner.service`)、`screen_monitor`/`screen_orchestrator`/`trend_executor`(experiments/ab-trading)、`ab_monitor`/`ab_orchestrator`(4h)、`agent-b-strategy-update`(02:00)、`memory_cleanup`(02:05 → ✅ **已补云端** `memory-cleanup.timer`)、`etl-worker`(7-产物中台 → ⏸ **暂缓**)、`ai.hermes.gateway`/`ai.hermes.dashboard`(→ ✅ **云端已启用**)、`com.l3.commandcenter.*`(5)

### 组 C｜训练/自进化（保留本地）

`continual-training`(34,1800s)、`evolution_scheduler`(02:00)、按需 oneshot：`train_neural_sde` / `shadow_rl_trainer` / `distributed_backtest` / `walk_forward`

### 组 D｜本地治理/同步（保留，需改造）

`dbsync`(**600s**，plist 实测周期，非 3600s)、`cognitive-ttl`(04:00)、`cognitive_mcp_server`

---

## 3. 组 1 ⚠️ 待确认项 — 云端对齐结论（本轮核心产出）

| 本地项 | 本地实测 | 云端实测 | 结论 |
|---|---|---|---|
| `ft.dashboard.3001`（Vite preview） | 3001 监听（开发预览） | 3001 = `dreambuddy-frontend`(Next.js 15) | **覆盖**（语义不同，本地 3001 仅为开发预览，可停） |
| `ft.ml_trade_service.explore/8093` | 8093 监听 | 8093 = `m26-strategy-lib.service` | **覆盖**（端口对齐，职责需下轮语义核对） |
| `ft.ml_trade_service.pilot/8094` | 8094 监听 | 8094 监听（unit 命名按部署文档为 M27，**待复核**） | **覆盖** |
| `ft.strategy_gen.8095` | 8095 监听 | 8095 = `m25-strategy-generation.service` | **覆盖** |
| `ft.fundamental_research_sync`(600s) | 9094 监听 | 9094 = `fundamental.service` | **覆盖** |
| `ft.ml_trade_service.prod/8092` | **8092 未监听**（plist 存在但未起） | **8092 未监听** | **无需迁移**（本地亦无流量，可直接停/清理 plist） |
| `ft.ml_trade_service.explorer/8092` | **8092 未监听** | 无 | **无需迁移**（同上，与 prod 重复端口） |
| `ft.explore.ml_trade_service`(Explore) | 8093 监听 | 8093 = m26 | **覆盖**（并入上行 8093 结论） |
| `etl-worker`(7-产物中台 prisma `etl_worker.py --daemon`) | 运行中 | **未见 etl 相关 unit**（`product-hub` 已在，ETL 未独立部署） | ❌ **未覆盖 → 需补齐或废弃** |

**新增发现**：
1. 云端已有 `dreambuddy-continual-training.service + .timer(30min)` —— **34 训练系统（前端应用训练）云端已在跑**；本地 `continual-training`(1800s) 与之重复。
2. 云端 `dreambuddy-snapshot.timer` 为**每 10min**（非文档记载的每小时），快照链更密。
3. 云端无 `8092`；本地 `prod`/`explorer` 两个 8092 plist 均为**空转/未监听**，属历史遗留。
4. 本地额外多跑 **3002**（第二个 `next dev`）——纯开发用途。

---

## 4. 处置分类（汇总）

### 4.1 可停（云端已覆盖，本地冗余）

`v15_light_poll`、`v15_orchestrator`、`yijing_data_server`、`dreambuddy.yijing.polling-trader`、`yijing_trading`、`yijing_live_300s`、`yijing_monitor`、`datacenter`、`dc-scheduler`、`dreamos`、`ranking-trigger`、`continual-training`、`ft.dashboard.3001`、`ft.ml_trade_service.explore`、`ft.ml_trade_service.pilot`、`ft.strategy_gen.8095`、`ft.fundamental_research_sync`、`ft.ml_trade_service.prod`(空转)、`ft.ml_trade_service.explorer`(空转)

> 注意 **本地重复项**：`datacenter` 与 `dc-scheduler` 跑同一脚本两份；云端正本仅 1 份。

### 4.2 需先补齐云端 or 废弃（云端缺失）

| 本地项 | 建议 |
|---|---|
| **`trailing-stop-runner`(`--real`)** | ✅ **已补云端** `trailing-stop-runner.service`（2026-10-14，phase9；与本地 launchd 共用统一入口 `16-调控系统/scripts/run_trailing_stop_runner.sh`，`--real` 常驻 300s） |
| `signal_scanner`(12-三屏) | ✅ **已补云端** `signal-scanner.service`（2026-10-14，每 300s；pool.json 实测刷新 9/9 币） |
| `screen_monitor`/`screen_orchestrator`/`trend_executor`(ab-trading) | latent，建议废弃 |
| `ab_monitor`/`ab_orchestrator` | latent，建议废弃 |
| `agent-b-strategy-update` | latent，建议废弃 |
| `etl-worker`(7-产物中台) | ⏸ **暂缓**：云端无 `events/` 数据源 + venv 缺 `psycopg2`（已复核：product-hub 未内嵌 ETL、无 cron） |
| `memory_cleanup`(02:05) | ✅ **已补云端** `memory-cleanup.timer`（每日 02:05；注：云端暂无 ab-trading 记忆文件，当前空转） |
| `ai.hermes.gateway`/`ai.hermes.dashboard` | ✅ 云端**已启用**（三单元 enabled+active，:9119 监听） |
| `com.l3.commandcenter.*`(5) | **独立项目**（L3 Command Center），不属本改造，单独决策 |

### 4.3 保留本地（训练目标）

组 C 全部（`continual-training` 若云端已覆盖可停本地、保留 `evolution_scheduler` 与 torch oneshot 训练链）。**储算目标**：`train_neural_sde` / `shadow_rl_trainer` / `distributed_backtest` / `walk_forward`。

### 4.4 保留本地（治理/同步，需改造）

`dbsync`（本地停写后切纯下行）、`cognitive-ttl`、`cognitive_mcp_server`。

---

## 5. 红线与下一步

**红线（停本地前必须闭环）**：
1. ✅ `trailing-stop-runner`(`--real`) 云端等价部署 —— **已闭环**（2026-10-14，`trailing-stop-runner.service` active；本地 launchd 与云端 systemd 共用同一可移植入口脚本，行为一致）。

**待复核（本轮 SSH 超时未取证）**：
1. 云端 `8094` / `8096` 的 systemd unit 名（端口已确认监听，命名按部署文档为 M27/M28）。
2. 云端 ETL 是否以其他形式（cron / 内嵌 product-hub）运行。

**下一步（用户已确认方向）**：
- 本地服务**全部停掉** → 本地纯训练；
- 训练编排走**云端下发 → 本地执行 → 模型回传**完整协同（需实现 [SPEC-分布式计算协同部署方案.md](./SPEC-分布式计算协同部署方案.md) Phase 2 编排层）；
- 待产出：正式 SPEC + 分阶段 PLAN（含红线补齐、编排层、模型回传/热加载、本地瘦身与验收门）。

---

## 附录：核对命令（可复现）

```bash
# 云端
ssh dreambuddy-remote 'systemctl list-units --all --no-pager --plain | grep -iE "dreambuddy|v15|yijing|cognitive|dreamos|m2[0-9]|fundamental|product"; \
  systemctl list-timers --all --no-pager --plain; ss -tlnp; ps aux'
# 本地
for f in ~/Library/LaunchAgents/*.plist; do python3 -c "import plistlib,sys;d=plistlib.load(open(sys.argv[1],'rb'));print(d.get('Label'),' '.join(map(str,d.get('ProgramArguments',[]))))" "$f"; done
lsof -nP -iTCP -sTCP:LISTEN
```

---

## 6. 本轮进展（2026-10-14 组 B 补齐）

| 项 | 动作 | 云端产物 | 状态 |
|---|---|---|---|
| hermes 三单元 | `enable --now` | hermes-gateway / group-poller / hermes-dashboard（:9119） | ✅ active（11:40 起） |
| `signal_scanner` | 补云端 | `signal-scanner.service`（12-三屏，300s） | ✅ active，pool.json 实测刷新（9/9 币） |
| `memory_cleanup` | 补云端 | `memory-cleanup.service` + `.timer`（02:05） | ✅ 部署并实测 exit 0（云端无记忆文件，暂空转） |
| `etl-worker` | 暂缓 | — | ⏸ 待云端具备 `events/` 数据源后再上 |

**代码落地**（GitHub 流水线：本地 commit/push → 云端 `git pull`）：
- `12-三屏趋势系统/signal_pool/scanner.py` 去硬编码（相对推导 `10-经典指标系统`，macOS/Linux 通用）
- `experiments/ab-trading/scripts/run_memory_cleanup.sh` 去 macOS 硬编码路径/解释器
- 新增 `31-分布式计算部署/phase8/08-deploy-groupb-units.sh`（安装上述 units）
- 云端仓库已由 `fix/okx-lsr-rate-limit`（PR #71 来源分支，落后 5 提交）切回 **`main` @ 66133903**
- 部署命令：`sudo bash /home/luke/dreambuddy/31-分布式计算部署/phase8/08-deploy-groupb-units.sh`
