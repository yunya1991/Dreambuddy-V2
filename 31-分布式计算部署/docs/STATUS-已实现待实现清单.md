# 31-分布式计算部署 — 已实现 / 待实现 完整清单

> **版本**：v1.0 | **更新日期**：2026-10-14
> **定位**：融合原有 Phase 1-7 部署方案 + 三层异构协同新架构（认知聚合 / 竞赛择优 / 协作训练）
> **关联文档**：
> - [SPEC-分布式计算协同部署方案.md](./SPEC-分布式计算协同部署方案.md) — 原始架构设计
> - [SPEC-本地远端双写分叉治理与torch可用性.md](./SPEC-本地远端双写分叉治理与torch可用性.md) — 认知/torch 决策
> - [RESEARCH-分布式计算核心逻辑-三层异构协同.md](./RESEARCH-分布式计算核心逻辑-三层异构协同.md) — 三层架构调研（评分 8.9/10）
> - [PLAN-本地远端双写分叉治理与torch可用性.md](./PLAN-本地远端双写分叉治理与torch可用性.md) — 实施计划

---

## 一、三层异构协同架构总览

```
┌────────────────────────────────────────────────────────────────────┐
│           认知层：远端+本地广义认知最大化（多节点聚合）              │
│   远端 live DB ←── 10min 上行汇总 ── 本地 DB（本地写本地）          │
│   分层：scope=global 全量聚合 / scope=subsystem 保留独立性          │
└──────────────────────────────┬─────────────────────────────────────┘
                               │ 子系统层读取认知层（只读视角）
┌────────────────────────────────────────────────────────────────────┐
│         子交易系统层：回测表现竞赛择优权重参数（Competition Mode）   │
│   同场景多模块/多参数并行回测 → 打分(Sharpe×0.4+Return×0.3+          │
│   (1-MaxDD)×0.2+WinRate×0.1) → 3级降级择优 → 热加载+快照回滚        │
└──────────────────────────────┬─────────────────────────────────────┘
                               │ 模型权重产物
┌────────────────────────────────────────────────────────────────────┐
│           前端应用层：协作训练，类大模型堆算力（联邦学习）            │
│   当前：线下训练 → MinIO 上传 → 云端热加载（中心化）                │
│   升级：多节点 FedAvg，仅传权重差异，不传原始数据                    │
└────────────────────────────────────────────────────────────────────┘
```

---

## 二、已实现清单（云端已运行验证）

### 2.1 云端核心上线（Phase 1）— ✅ 已实现

| 脚本 | 职责 | 云端服务 | 状态 |
|------|------|---------|------|
| `phase1/01-cloud-init.sh` | Docker + Node22 + Python3.12 + pnpm + PM2 + ufw | — | ✅ |
| `phase1/docker-compose.yml` | PG16 + Redis7 + MinIO | dreambuddy-pg/redis/minio | ✅ healthy |
| `phase1/02-deploy-data.sh` | 数据层 + MinIO bucket | — | ✅ |
| `phase1/03-deploy-frontend.sh` | Next.js 15 前端（PM2→systemd） | dreambuddy-frontend :3001 | ✅ active |
| `phase1/04-deploy-v15.sh` | V15 API + capital API + systemd timer | v15-api :8771 / v15-capital-api :8770 | ✅ |
| `phase1/05-nginx-ssl.sh` | Nginx 反代 + Let's Encrypt | nginx | ✅ |
| `phase1/06-deploy-hermes.sh` | Hermes 飞书网关 | hermes-gateway / group-poller / hermes-dashboard :9119 | ✅ active（2026-10-14 已启用，:9119 监听） |
| `phase1/healthcheck.sh` | 统一健康检查（10维度） | — | ✅ |
| `phase1/update.sh` | 滚动更新脚本 | — | ✅ |
| `phase1/logrotate-dreambuddy.conf` | 日志轮转 | — | ✅ |

### 2.2 协同增强（Phase 2）— ✅ 已实现

| 脚本 | 职责 | 云端服务 | 状态 |
|------|------|---------|------|
| `phase2/01-deploy-yijing-data-server.sh` | 易经数据服务 | yijing-data-server :8765 | ✅ |
| `phase2/02-deploy-product-hub.sh` | 产物中台 | product-hub :3456 | ✅ |
| `phase2/05-deploy-classic-modules.sh` | 经典模块 M25-M28 | m25 :8095 / m26 :8093 / m27 :8094 / m28 :8096 | ✅ |
| `phase2/03-nginx-update.sh` | Nginx 路由更新 | nginx | ✅ |
| `phase2/04-rebuild-frontend.sh` | 前端重建 | — | ✅ |
| 基本面数据服务 | 9094 | fundamental :9094 | ✅（无独立 phase 脚本，随 `ml_trade_service_v2.py` 部署） |

### 2.3 数据管道（Phase 3）— ✅ 已实现

| 脚本 | 职责 | 云端服务 | 状态 |
|------|------|---------|------|
| `phase3/03-deploy-data-pipeline.sh` | 18 采集调度 | datacenter-scheduler | ✅ active |
| 同上 | 18→19 回填（每小时） | datacenter-backfill.timer | ✅ |
| 同上 | DAL SQLite 备份（每日04:00） | dal-backup.timer | ✅ |
| 同上 | DAL SQLite 校验（每6h） | dal-integrity.timer | ✅ |
| 同上 | DAL 备份轮转（每日05:00） | dal-rotate.timer | ✅ |

### 2.4 认知守护 + DreamOS 编排（Phase 4）— ✅ 已实现

| 脚本 | 职责 | 云端服务 | 状态 |
|------|------|---------|------|
| `phase4/04-deploy-cognitive-orchestration.sh` | 认知守护（文件变更→认知闭环） | cognitive-daemon | ✅ active |
| 同上 | DreamOS 调度（每小时全币种） | dreamos-scheduler | ✅ active |
| 同上 | 动态评估（每6h） | dreamos-dynamic-evaluator | ✅ active |

### 2.5 冗余单元（Phase 6）— ✅ 已实现

| 脚本 | 职责 | 云端服务 | 状态 |
|------|------|---------|------|
| `phase6/06-deploy-redundant-units.sh` | 易经巡检+自进化（每4h） | yijing-monitor.timer | ✅ |
| 同上 | 榜单重算触发（每4h） | ranking-trigger.timer | ✅ |

### 2.6 Torch + 快照（Phase 7）— ✅ 已实现

| 脚本 | 职责 | 云端状态 |
|------|------|---------|
| `phase7/07-deploy-torch-and-snapshots.sh` | CPU torch + torchsde + mcp + sqlite-vec | ✅ 已装 |
| `phase7/snapshot_dbs.sh` | cognitive_memory.db + dreambuddy_core.db 一致性快照 | ✅ |
| `dreambuddy-snapshot.timer` | 快照定时任务 | ✅ 每10min |

### 2.7 认知库多节点聚合 v2（Phase 7 本地）— ✅ 已实现

| 组件 | 职责 | 状态 |
|------|------|------|
| `phase7/08-local-mirror.sh` | 认知库双向聚合（上行 INSERT OR IGNORE by id / 下行 INSERT OR REPLACE by id） | ✅ |
| `phase7/com.dreambuddy.dbsync.plist` | 本地 LaunchAgent，10min 周期 | ✅ 已安装 |
| 下行取数 | rsync 拉远端一致性快照到本地（认知库+核心库） | ✅ |
| gene_data 双向 merge | 上行+下行，不加 --delete，不丢数据 | ✅ |

### 2.8 子系统竞赛择优基础设施（本地代码）— ✅ 已实现（单节点）

| 组件 | 文件 | 职责 |
|------|------|------|
| EntryModuleSelector | `1-ARCHITECTURE/dreamos/capabilities/trading/entry_strategy/entry_module_selector.py` | 入场模块3级降级择优 + 打分公式 |
| ExitModuleSelector | `1-ARCHITECTURE/dreamos/capabilities/trading/exit_strategy/exit_module_selector.py` | 离场模块3级降级择优 |
| BradleyTerryLearner | `4-MEMORY/9-工具与接口/weight_learner.py` | 在线权重学习（pass↑/fail↓/同源降权） |
| weighted_aggregation | `4-MEMORY/9-工具与接口/weighted_aggregation.py` | 多源信号加权聚合 `p=Σ(wᵢvᵢ)/Σ(wᵢ)` |
| GeneVersionManager | `23-四层闭环自进化交易架构/dreambuddy_evolution/adapters/gene_version_manager.py` | 基因库快照+一键回滚 |
| sltp_bayesian_optimizer | `11-易经推理系统/scripts/memory_l4/bcrm2/sltp_bayesian_optimizer.py` | SL/TP 参数贝叶斯优化 |
| cognitive_backtest | `4-MEMORY/9-工具与接口/cognitive_backtest.py` | A/B 回测门禁（path_advantage≥+0.2） |
| module_switches | `4-MEMORY/9-工具与接口/module_switches.py` | L0-L3 模块化开关，默认全 OFF |
| NodeRegistry | `1-ARCHITECTURE/dreamos/registry/node_registry.py` | 节点单一真相源，动态注册/注销 |

### 2.9 云端全量运行清单（已核对 active，2026-10-14）

- **systemd 服务**（active 21个）：dreambuddy-frontend(:3001) · yijing-data-server(:8765) · product-hub(:3456) · fundamental(:9094) · m25-strategy-generation(:8095) · m26-strategy-lib(:8093) · m27-governance(:8094) · m28-signal-trigger(:8096) · v15-api(:8771) · v15-capital-api(:8770) · yijing-polling-trader · datacenter-scheduler · cognitive-daemon · dreamos-scheduler · dreamos-dynamic-evaluator · nginx · hermes-gateway · group-poller · hermes-dashboard(:9119) · signal-scanner · trailing-stop-runner(--real,300s)
- **systemd 服务**（inactive 0个）：hermes 三单元已于 2026-10-14 启用（enabled+active，:9119 监听）；组 B 的 signal_scanner / memory_cleanup 已补云端（`phase8/08-deploy-groupb-units.sh`）。memory-cleanup.service 为 oneshot，静息态 inactive 属正常
- **timers**（11个）：v15-orchestrator · v15-poll-light · datacenter-backfill · dal-backup · dal-rotate · dal-integrity · yijing-monitor · ranking-trigger · dreambuddy-snapshot · dreambuddy-continual-training · memory-cleanup
- **Docker**：dreambuddy-pg / dreambuddy-redis / dreambuddy-minio（healthy）
- **PM2**：已清空（M25 迁 systemd）

### 2.10 分布式红线补齐（Phase 8/9）— ✅ 已实现

| 脚本 | 职责 | 云端服务 | 状态 |
|------|------|---------|------|
| `phase8/08-deploy-groupb-units.sh` | 组 B 补云端（信号池扫描 300s / 记忆清理 02:05） | signal-scanner.service + memory-cleanup.timer | ✅ active |
| `phase9/09-deploy-trailing-stop-runner.sh` | **红线 G0-1a**：实盘移动止损（--real） | trailing-stop-runner.service（300s） | ✅ active（2026-10-14） |

> 统一入口：本地 launchd 与云端 systemd 共用 `16-调控系统/scripts/run_trailing_stop_runner.sh`（内部自解析仓库路径 + 加载 `14-V15经典马丁策略/config/.env.local` 凭据 + 组装 PYTHONPATH），保证两端行为一致。

### 2.11 云端监控面板对齐本地（Phase 10）— ✅ 已实现（2026-10-14）

| 改动 | 职责 | 云端产物 | 状态 |
|------|------|---------|------|
| `phase10/10-deploy-panel-parity-units.sh` | ab-trading 生产者上云（复活 ab_monitor/ab_orchestrator） | `ab-monitor.service`+`.timer`(4h) / `ab-orchestrator.service`+`.timer`(4h) | ✅ active |
| `data_server_fixed.py` 去硬编码（新增 `_REPO_ROOT` + 替换 15 处 macOS 绝对路径） | 两端同源面板 | yijing-data-server :8765（已重启加载新码） | ✅ |
| `polling_trader.py` agi_snapshot 写盘去硬编码 | `/api/agi/*` 数据源 | `23-四层.../dreambuddy_evolution/data/agi_snapshot.jsonl` | ✅ 已产出（重启后） |
| `experiments/ab-trading/scripts/run_agent_a.sh` 去硬编码（仓库根自推导 + `PYTHON_BIN`） | agent 生产者 | — | ✅ |
| `ab-trading` 无凭据优雅降级（`core/exit_module.py` 同步容错 + `agent_b_runner.py` `get_account` 容错） | 云端无 `config/.env` 不再整轮崩溃 | — | ✅ |

**关键事实（本轮取证）**：

- 系统性根因：面板与生产者硬编码 macOS 绝对路径 → 云端解析不到 → 返回空/兜底值（页面 HTML 两端字节一致，MD5 `bb368478a8def5f867ebc1611cf8d6ff`，差异全部来自 API 数据）。
- 云端生产者必须禁止实盘：`config/.env` 被 `.gitignore` 忽略（云端本就不存在）+ 单元显式 `Environment="AUTO_EXECUTE=false"`。
- systemd 单元内 `auto_monitor.py` 以裸 `python3` 拉起 agent runner → 单元须把 venv bin 前置 PATH（云端 `/usr/bin/python3` 缺 `dotenv/requests`）。
- 云端 git 仓库属主 `luke`、SSH 用户 `ubuntu` → 拉取需 `sudo -n -u luke -H git -C /home/luke/dreambuddy pull --ff-only`。

**验收（D4：结构 + 关键字段一致）**：

- 页面：外部 `http://43.160.201.117:8765/` → 200，MD5 与本地一致。
- `/api/state`：两端 13 键一致（`logs_a`/`logs_b`/`total_equity`/`b_*`/`c_*`/`perp_*`/`spot_usdc`）；本地 `logs_a=logs_b=30`，云端 `1/1`（随 4h 周期增长，属机器相关数值差异）。
- `/api/agi/snapshot`、`/api/agi/status`、`/api/nonlinear-path-metrics`、`/api/classic-executor`、`/api/bdsm/snapshot`、`/api/evolution-overview`：两端顶层键结构一致。
- `fuses_state.json`：全仓无生产者（仅面板读取）→ 按决策保持现状（两端皆空即视为一致）。

---

## 三、待实现清单

### 3.1 原设计待实现（SPEC Phase 2/3/4 未完成项）

> **编号说明**：SPEC 原始规划 Phase 1-4。实际部署中 phase3/4/6/7 是后加的（数据管道/认知编排/冗余/torch），与 SPEC Phase 编号不对应。下表 O1-O5 对应 **SPEC 原始 Phase 2/3/4**。

| # | 任务 | SPEC 对应 | 优先级 | 说明 | 关联文档 |
|---|------|----------|--------|------|---------|
| O1 | **任务队列 + 线下 WorkerAgent** | SPEC Phase 2 | P0 | Redis Streams 任务分发、Worker 管理、能力路由、心跳。**N4 跨节点竞赛的前置依赖** | SPEC §5 |
| O2 | **HeartbeatMonitor** | SPEC Phase 2 | P0 | 线下节点健康检测、故障判定。O1 的子组件 | SPEC §6 |
| O3 | **Degrader 降级决策器** | SPEC Phase 3 | P1 | 故障时切换降级算法、恢复时切回 | SPEC §6 |
| O4 | **FallbackLib 降级算法库** | SPEC Phase 3 | P2 | 各子系统简化版推理模型 | SPEC §6 |
| O5 | **多线下机器支持** | SPEC Phase 4 | P2 | 多 Worker 节点协同 | SPEC §11 |
| O6 | **gene_data 影子模式（本地停写）** | PLAN 阶段6 | P3 | 用户决定本轮不执行，观察后再决定 | PLAN §阶段6 |

> **phase5 空缺说明**：目录无 phase5/。SPEC 原始只规划 Phase 1-4，实际后加的 phase3/4/6/7 跳号。phase5 为预留编号，无对应任务。

### 3.2 三层异构协同新架构待实现

#### 认知层（P0）

| # | 任务 | 优先级 | 预估 | 说明 |
|---|------|--------|------|------|
| N1 | **认知分层共享（scope 字段）** | P0 | 1.5天 | **影响面**：① `memories` 表 `ALTER TABLE ADD COLUMN scope TEXT DEFAULT 'global'`（两端 migration）；② `08-local-mirror.sh` COLS/COG_DDL 加 scope，上行/下行聚合加 `WHERE scope='global'` 过滤；③ `cognitive_loop_entry.py:record()` → `_vm.add()` 增加 `scope` 参数（默认 'global'）；④ 子系统私有写入处（如 gene_data 相关、模块私有参数）显式传 `scope='subsystem'`；⑤ 现有数据全部默认 global，无需回填 |
| N2 | **认知库 vec_memories 同步** | P2 | 1天 | 当前 vec0 虚表跳过，调研是否需要同步 |

#### 子交易系统层 — Competition Mode（P0-P1）

| # | 任务 | 优先级 | 预估 | 说明 |
|---|------|--------|------|------|
| N3 | **CompetitionOrchestrator（单节点）** | P0 | 2-3天 | 同场景多模块/多参数并行回测编排，复用 EntryModuleSelector 打分公式 + 3级降级。**单节点版不依赖 O1**，可先落地 |
| N4 | **跨节点竞赛** | P1 | 1天 | 竞赛任务通过 Redis Streams 分发到本地+云端 Worker，结果回传统一打分。**依赖 O1（任务队列+Worker）** |
| N5 | **FDR 控制模块** | P1 | 1天 | Benjamini-Hochberg 多重检验校正，防止过拟合（Harvey-Liu-Zhu 问题） |
| N6 | **BradleyTerryLearner 扩展** | P2 | 2天 | 从验证器权重扩展到子系统/模块权重 |
| N7 | **竞赛版本管理** | P1 | 1天 | 复用 GeneVersionManager 快照+回滚模式，管理竞赛优胜参数 |

#### 前端应用层 — 协作训练（P1-P2）

| # | 任务 | 优先级 | 预估 | 说明 |
|---|------|--------|------|------|
| N8 | **权重 delta 传输（轻量联邦）** | P1 | 1-2天 | MinIO 上传改传权重差异（类似 GradualDiff-Fed），降低通信量 |
| N9 | **完整联邦学习（Flower/NVFlare）** | P2 | 3-5天 | FedAvg 多节点协作训练，仅传梯度/权重不传原始数据 |
| N10 | **自进化模型同步机制** | P0 | 2天 | MinIO 模型仓库 + 云端热加载 + 灰度切换（SPEC Phase 4 原计划）。**独立可立即实施** |
| **N13** | **MutationDetector 突变检测器** | **P0** | 1-2天 | 隔离单训下"突变"判据（z>3 / DSR≥0.95 或 t>3.0 / 样本下限）+ 冷却窗 + 二次确认，触发即时广播。详见 [RESEARCH-训练协同-隔离单训与突变广播同步.md](./RESEARCH-训练协同-隔离单训与突变广播同步.md) · [PLAN-训练协同-N13突变检测与N14广播总线.md](./PLAN-训练协同-N13突变检测与N14广播总线.md) |
| **N14** | **广播总线 + 兜底心跳** | **P0** | 1天 | Redis Streams 广播（复用 O1）+ 固定周期兜底同步（**6h**）+ 择优+部分迁移 + last-known-good。**N13 的承载层** |

### 3.3 工程基建待实现

| # | 任务 | 优先级 | 说明 |
|---|------|--------|------|
| N11 | **mcp_cognitive 自动重启** | P1 | 当前 MCP 进程终止后 TRAE 不自动重启，需用户重载配置 |
| N12 | **健康检查扩展** | P2 | healthcheck.sh 增加认知聚合状态、竞赛结果状态检查 |

---

## 四、依赖关系与实施顺序

```
已实现层（Phase 1-7）
    │
    ├── 认知层 P0: N1（scope 分层）─ 独立，可立即实施
    │
    ├── 子系统层 P0: N3（CompetitionOrchestrator 单节点）─ 独立，可立即实施
    │       │
    │       ├── N5（FDR控制）─ 依赖 N3
    │       └── N7（竞赛版本管理）─ 依赖 N3
    │
    ├── 前端层 P0: N10（模型同步）─ 独立，可立即实施
    │       │
    │       ├── N8（权重delta）─ 依赖 N10
    │       │       │
    │       │       └── N9（联邦学习）─ 依赖 N8
    │       │
    │       └── N13（突变检测）+ N14（广播总线）─ 依赖 N8/N10；混合同步范式
    │
    └── O1+O2（任务队列+心跳）─ 独立，为跨节点打基础
            │
            └── N4（跨节点竞赛）─ 依赖 O1；N14 复用 Redis Streams
```

**推荐实施顺序**：
1. **N1**（认知分层）+ **N3**（竞赛框架单节点）+ **N10**（模型同步）— 三个独立 P0，并行启动
2. **O1+O2**（任务队列+心跳）— 为跨节点竞赛和多线下机器打基础
3. **N5**（FDR控制）+ **N7**（版本管理）— 竞赛质量保障（依赖 N3）
4. **N4**（跨节点竞赛）— 依赖 O1
5. **N8**（权重delta）— 前端层升级（依赖 N10）
6. **O3**（降级）+ **N9**（联邦学习）— 完整形态

---

## 五、关键设计决策记录

| # | 决策 | 日期 | 说明 |
|---|------|------|------|
| D1 | 本地+远端都装 torch | 2026-10-13 | 消除 SDE 静默降级 |
| D2 | 认知库多节点聚合（非单写方） | 2026-10-13 | 本地写本地，按 id 双向聚合，10min 周期 |
| D3 | 本地 MCP 写本地认知库 | 2026-10-13 | 不再 SSH stdio 托管到远端 |
| D4 | Phase 2 影子模式本轮不执行 | 2026-10-13 | 用户观察后再决定 |
| D5 | 分布式三层异构协同架构 | 2026-10-13 | 认知聚合 / 竞赛择优 / 协作训练 |
| D6 | 全量一致性：云端全量运行+本地并行保留 | 2026-10-14 | 云端存储充足，6大子系统全量上云 |

---

## 六、风险与缓解

| 风险 | 缓解 |
|------|------|
| 竞赛过拟合（多重检验） | FDR 控制（N5）+ 最低样本量门槛（L0≥30/L1≥50/L2≥100）+ path_advantage≥+0.2 |
| 策略同质化 | 认知 scope 分层（N1）+ 子系统私有参数不聚合 |
| 通信开销 | 权重 delta 传输（N8）+ 联邦学习小 batch 高 LR |
| 数据漂移/regime 变化 | 场景强降级 + Bradley-Terry 在线权重动态调整 |
| MCP 进程不自动重启 | N11 健康检查+自动拉起 |
