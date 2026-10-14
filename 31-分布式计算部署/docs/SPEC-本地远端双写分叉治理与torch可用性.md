# SPEC — 本地/远端双写分叉治理 与 torch 可用性补齐

- 状态：设计已确认（待用户评审本文档）
- 日期：2026-10-13
- 关联：`.trae/documents/全量远端部署方案.md`（Stage 0–6 已完成）

---

## 0. 背景

远端全量部署（43.160.201.117，4C8G/120G systemd 托管）已完成，本地 Mac 并行保留运行。暴露两个遗留问题：

**问题 1（能力降级）**：远端 `venv-trading` 未安装 torch，`23-四层闭环自进化交易架构/dreambuddy_evolution` 中依赖 torch 的神经 SDE 分支触发 FAIL-OPEN 降级，神经路径静默退化为统计路径，且无显式可观测信号。

**问题 2（数据分叉）**：本地与远端同时运行，两类有状态数据存在**双向分叉**风险：
- 认知库 `4-MEMORY/data/cognitive_memory.db`（写入方：`4-MEMORY/9-工具与接口/cognitive_loop_entry.py:158`，经本地 MCP `cognitive_mcp_server.py` 与远端 `cognitive_daemon` 双向写）
- 自进化样本 `23-四层闭环自进化交易架构/dreambuddy_evolution/gene_data`（写入方：`evolution_pipeline.py`、`gene_version_manager.py:36-40`、`ftc_gene_innovation.py:110-114`、`shadow_backtest.py:646-661`）

---

## 1. 决策记录（用户已确认）

| # | 决策 | 说明 |
|---|---|---|
| D1 | **本地和远端都装上 torch** | 本地已具备（anaconda torch 2.11.0 + torchsde 0.2.6）；远端需补齐 |
| D2 | **认知库多节点聚合（非单写方）** | 本地写本地、远端写远端，同步作业按 `id` 双向聚合（上行 `INSERT OR IGNORE`，下行 `INSERT OR REPLACE` 按 `updated_at`），10min 周期 |
| D3 | **本地 MCP 写本地认知库** | 本地开发工具（MCP 记忆）写本地 `cognitive_memory.db`，经聚合脚本上行到远端，不再 SSH stdio 托管到远端 |
| D4 | **两阶段落地，Phase 2 本轮不执行** | Phase 1 过渡期本地先正常同步运行；Phase 2 影子模式**本轮不实施**，由用户自行观察一段时间后再决定是否切换 |
| D5 | **分布式三层异构协同架构** | 认知层（广义认知最大化，多节点聚合）/ 子系统层（回测竞赛择优权重参数，Competition Mode）/ 前端层（协作训练，类大模型堆算力）—— 详见 `.trae/documents/distributed-core-logic-research-report.md` |

---

## 2. 问题 1：torch 可用性补齐

### 2.1 现状证据
- 依赖 torch 的位置（均在 `23-四层闭环自进化交易架构/dreambuddy_evolution/`，**不在** `1-ARCHITECTURE/dreamos/`）：
  - `core/neural_sde_model.py:32-53`（延迟导入 + `_TORCH_AVAILABLE`/`_TORCHSDE_AVAILABLE` 探测）、`:88-107`（`_DriftNet`）
  - `engines/sde_solver.py:37-58`（`SDESolver`，降级链 `torchsde → Euler-Maruyama → GARCH(1,1) → GBM`）
  - `engines/deep_reasoning_engine.py:25-35`、`:59-68`、`:230-232`
  - `core/transfer_learner.py:35-41`
- 仓库根 `pyproject.toml:25-45` 已有 `[project.optional-dependencies]`（`dev`/`trading`），但**未声明 torch/torchsde**。

### 2.2 设计

| 组件 | 内容 |
|---|---|
| ① 远端安装 | 在 `/home/luke/venv-trading` 安装 CPU 版依赖：`pip install torch --index-url https://download.pytorch.org/whl/cpu`，再 `pip install torchsde`。 |
| ② 依赖声明 | `pyproject.toml` 新增可选组：`sde = ["torch>=2.0", "torchsde>=0.2.6"]`。 |
| ③ 可观测性 | 启动时输出 `_TORCH_AVAILABLE`、`SDESolver.status()`、`DeepReasoningEngine._sde_backend_used`，使「有/无 torch」显式可见，消除隐性静默降级。 |
| ④ 测试 | 新增断言：torch 可用时 SDE 后端为 `torchsde`；torch 不可用时降级链落到预期后端。 |
| ⑤ 部署脚本 | 在 `31-分布式计算部署/phase7/` 新增安装与校验脚本（幂等）。 |

### 2.3 验收（Gate）
- 远端与本地分别执行 `SDESolver.status()` → 后端为 `torchsde`；
- `yijing-polling-trader` 日志无 torch 降级告警；
- 新增/相关测试通过。

---

## 3. 问题 2：双写分叉治理（两阶段）

### 3.1 Phase 1（过渡期）

**目标**：两侧保持一致 + 本地照常可用。

**认知库（多节点聚合 v2 — 已实施）**
- 本地 MCP **写本地** `cognitive_memory.db`，不再 SSH stdio 托管到远端。
- 同步作业 `31-分布式计算部署/phase7/08-local-mirror.sh`（LaunchAgent `com.dreambuddy.dbsync`，10min 周期）实现双向聚合：
  - **下行取数**：远端一致性快照 → 本地常驻副本（rsync 增量，仅传差异块）
  - **上行汇总**：本地独有行（`id` 不在快照）→ 远端权威 live（`INSERT OR IGNORE by id`）
  - **下行合并**：快照 → 本地（`INSERT OR REPLACE by id`，远端 `updated_at` 更新的覆盖同名行；本地独有行保留）
- 远端快照 timer `dreambuddy-snapshot.timer`：每 10 分钟执行 `sqlite3 .backup` 产出快照。
- 效果：本地写入即时持久（不依赖网络），10min 内聚合到远端；远端写入经下行合并到本地；无整文件 rsync 替换（保住本地 inode，避免 `database is locked`）。
- 已知边界：`mcp_cognitive` 进程终止后 TRAE 不会自动重启，需用户重载 MCP 配置。

**认知分层共享（P0 规划，待实施）**
- 调研结论（详见 `.trae/documents/distributed-core-logic-research-report.md`）：广义认知全量共享 vs 子系统私有保留独立性，需分层避免策略同质化。
- 方案：`memories` 表增加 `scope TEXT DEFAULT 'global'` 列；聚合脚本仅聚合 `scope='global'` 的行，`scope='subsystem'` 行不跨节点聚合。

**gene_data（过渡期双向收敛）**
- 本地照常写入；由于 `gene_data` 路径由代码位置推导（`evolution_pipeline.py:31-32` 等），过渡期不强行重定向。
- 同步作业负责收敛：**本地新增上行合并 → 远端 → 下行覆盖本地**（`rsync` merge，**不 `--delete`**），保证过渡期不丢数据。

**同步作业（新增）**
- 远端：定时（跟随小时级）对 `cognitive_memory.db` / `dreambuddy_core.db` 执行 `sqlite3 .backup`，产出快照到暂存目录（避免 WAL 半写）。
- 本地：LaunchAgent 定时 `rsync` 拉取快照到本地对应路径；gene_data 按 3.1 双向规则处理。
- 远端所有写操作以 `luke` 身份；`.git` 属主异常时按既有约定 `chown` 修复。

### 3.2 Phase 2（收敛后 → 影子模式，**本轮不执行**）

- **本轮范围外**：用户需自行观察一段时间，再决定切换时机；本 SPEC/PLAN 仅登记设计，不进入本轮实施。
- 内容（未来执行时）：本地新增开关，使 `gene_data` 写入停用（本地 `polling_trader` 转「影子」：照常读取/交易，但不写权威基因库）；
- 同步切**纯下行单向**（`rsync --delete`），本地库严格只读镜像；
- 触发条件：用户确认「本地与远端稳定一致」后自行启动。

### 3.3 验收（Gate）
- Phase 1：`record`/`verify` 后本地 `cognitive_memory.db` 行数即时增长，10min 内上行聚合到远端（远端行数同步增长）；
- Phase 1：下行合并不丢本地独有行（`INSERT OR REPLACE by id`，本地 `id` 不在快照中的行保留）；
- Phase 1：一次同步周期后，本地与远端 gene_data 无新增丢失（merge 生效）；
- Phase 2（**本轮不验收**）：本地 `gene_data` 在本地运行周期内不再增长；下行 `--delete` 后两侧一致。

---

## 4. 风险与回滚

| 风险 | 缓解 / 回滚 |
|---|---|
| 远端 `mcp` 包与认知依赖不兼容 | 先在远端独立 venv 冒烟导入 `cognitive_mcp_server`；不兼容则改本地代理模式（回退路线 B） |
| SSH stdio 托管使本地 MCP 依赖网络 | 保留旧本地 MCP 配置为可切换回退；断网时本地记忆写入降级为「暂存待补」 |
| 过渡期双向 merge 可能引入冲突 | 仅 merge 不 `--delete`；认知库本阶段已单写方，冲突面仅 gene_data |
| torch CPU 安装体积/耗时 | CPU wheel，磁盘充足；失败不影响既有降级链（本就是 FAIL-OPEN） |
| 下行 `--delete` 误删本地未上行数据 | Phase 2 切换前强制「先对齐一次 + 留 `.bak`」 |

---

## 5. 明确不做（YAGNI）

- 不修改 `1-ARCHITECTURE/dreamos`（torch 依赖并不在其内）。
- 暂不采用路线 C（认知库迁 PostgreSQL / gene_data 迁 MinIO）。
- 不为 `gene_data` 引入远端写入 API —— 过渡期用 rsync merge，Phase 2 停写即可。
- 不重构 `gene_data` 路径推导逻辑（除非 Phase 2 需要环境变量出口，届时再评估）。

---

## 6. 实施任务（供 writing-plans 展开）

### 已完成
- **T1** `pyproject.toml` 增 `sde` 可选依赖组。
- **T2** 远端安装 CPU torch + torchsde（幂等脚本 `31-分布式计算部署/phase7/`）。
- **T3** 可观测性：启动日志打印 torch/SDE 后端状态。
- **T4** 新增 SDE 后端测试（torch 可用 → `torchsde`）。
- **T7** 远端快照 timer（10min）+ 本地 LaunchAgent 镜像作业（10min）。
- **T8** 认知库多节点聚合 v2（`08-local-mirror.sh` 按 id 双向聚合）+ gene_data 双向 merge。

### 废弃（决策变更）
- ~~**T5** 远端补装 `mcp` 包并冒烟导入认知 MCP server~~ — 改为本地写本地，不再 SSH 托管。
- ~~**T6** 免密 SSH + Trae MCP 配置改 SSH stdio 托管~~ — 改为本地 MCP 写本地库。

### 本轮新增（三层异构协同，详见调研报告）
- **T10（P0）** 认知分层共享：`memories` 表增 `scope` 列 + 聚合脚本按 `scope` 过滤。
- **T11（P0）** 子系统竞赛择优框架 `CompetitionOrchestrator`：复用 `EntryModuleSelector` 打分 + 3 级降级 + `BradleyTerryLearner` 在线权重。
- **T12（P1）** 多重检验 FDR 控制模块，防止竞赛过拟合。
- **T13（P1）** 前端协作训练轻量升级：MinIO 上传改传权重 delta（降低通信量）。
- **T14（P2）** 完整联邦学习（Flower/NVFlare FedAvg）。
- **T15（Phase 2，本轮不实施）** 本地 gene_data 停写开关 + 纯下行 `--delete` 切换脚本。

> 每步完成后按「接口/证据级」验收；新增脚本与配置写回 `31-分布式计算部署/` 并 commit+push。
