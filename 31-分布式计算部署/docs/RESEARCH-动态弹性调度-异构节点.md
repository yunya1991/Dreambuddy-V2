# RESEARCH — 动态弹性调度 × 异构节点纳管

> **版本**：v1.0 | **日期**：2026-10-14
> **定位**：面向"**未来接入更多服务器**"的**动态弹性调度**方案评估——云端根据接入节点（算力悬殊、可动态加入/退出）自动分配**训练 / 回测优化 / 推理下沉**任务，提升模型训练能力与整体性能。
> **关联**：
> - [SPEC-分布式计算协同部署方案.md](./SPEC-分布式计算协同部署方案.md)（§5 通信与协同 · §9 Phase 4' · §12 D-1~D-24）
> - [RESEARCH-分布式计算核心逻辑-三层异构协同.md](./RESEARCH-分布式计算核心逻辑-三层异构协同.md)（三层架构 8.9/10）
> - [RESEARCH-框架研究-三层异构协同架构.md](./RESEARCH-框架研究-三层异构协同架构.md)（六阶段演进路径）
> - [RESEARCH-训练协同-隔离单训与突变广播同步.md](./RESEARCH-训练协同-隔离单训与突变广播同步.md)（混合同步 D-14~D-19）
> - [REVIEW-大模型分布式框架评估与评审定稿.md](./REVIEW-大模型分布式框架评估与评审定稿.md)（D-20~D-24 + 否决项）
> - [STATUS-已实现待实现清单.md](./STATUS-已实现待实现清单.md)（O1/O2/O5 待实现）
> - [SERVICE_INVENTORY.md](./SERVICE_INVENTORY.md)（本地/云端服务盘点）
> **方法**：4 维调研（AI 训练调度 / 传统金融批处理 / GitHub 成熟实现 / 本地代码现状）+ 五维交叉验证
> **实施边界（2026-10-14 更新）**：本报告为**远景设计储备**。经用户确认，当前阶段**不落地完整复杂功能**；实施顺序以 [ROADMAP-分布式计算实施路线图.md](./ROADMAP-分布式计算实施路线图.md) 为准——**阶段 0 远端主线跑通 → 阶段 1 简单训练下沉 → 阶段 2+ 才落地本报告（D-25~D-33）**。

---

## 0. 问题陈述

### 0.1 用户需求（基准口径）

> "未来我们可能接入更多服务器，云端应该需要能根据接入的服务器，动态分配计算训练任务，从而提高模型训练能力，以及整体性能。"

经确认的三项口径（本轮）：

| 项 | 确认值 |
|---|---|
| 交付物 | **调研 + 设计报告**（RESEARCH，不动代码） |
| 任务范围 | **全量**：训练 + 回测/优化 + 推理下沉 |
| 节点形态 | **异构弹性**：算力悬殊 + 动态加入/退出 |

### 0.2 边界与硬约束（承自既有定稿）

- **不引入**：K8s / Ray / Slurm / YARN / Volcano 本体（调度引擎）；NCCL / FSDP；TorchElastic rendezvous 本体；Flower 本体；MLflow Registry 服务端（见 §12.4 与 REVIEW §2.4）。**只借语义，不引本体。**
- **复用**：Redis Streams（任务 + 广播，O1）· MinIO（模型/结果/checkpoint）· NodeRegistry（节点真相源）· module_switches（默认 OFF）· D-21 内容寻址(SHA256)+atomic swap+LKG · D-17 择优+部分迁移 · D-23 硬门禁。
- **工程约束**：模块化开关默认 OFF；FAIL-OPEN；零回归（HC-1a / HC-9）。
- **数据前提**：同源异构（非 IID，D-19）；算力悬殊（4C8G CPU ↔ M3 MPS ↔ 未来节点）。

### 0.3 核心待答问题

1. 调度架构选型：中心化单调度 vs 去中心化自治 vs 中心 + 弹性混合？
2. **异构节点画像**与**能力标签**如何定义、谁声明、如何随负载更新？
3. **动态加入/退出**如何纳管（注册 / 优雅退出 / 超时驱逐 / 幂等防僵尸）？
4. **弹性 min:max** 与容错如何落地（无 rendezvous / 无 NCCL 前提下）？
5. **调度策略**如何做到"按算力/负载"而非轮询？
6. **任务优先级 / 抢占 / backfill** 如何不伤关键路径？
7. **checkpoint 断点续传**如何做（借 DCP 命名约定，不引本体）？
8. **推理下沉**的路由与热加载如何与 D-7/D-21 对齐？
9. **成本感知**如何量化并进入调度打分？

---

## 1. 三方案对比与评分

| 维度（权重） | A 中心化静态调度 | B 去中心化自治 / 竞价 | **C 中心调度 + 弹性池 + 分级抢占（混合）** |
|---|---|---|---|
| 异构适配（算力悬殊）0.15 | 5 | 7 | **9** |
| 动态加入/退出纳管 0.15 | 6 | 8 | **9** |
| 弹性与容错 0.15 | 5 | 7 | **8** |
| 成本感知 0.10 | 4 | 8 | **8** |
| 实现复杂度（越简越高）0.10 | 9 | 3 | **6** |
| 复用现有资产 0.15 | 7 | 4 | **9** |
| 可观测 / 治理 0.10 | 6 | 4 | **8** |
| 零回归 / 默认 OFF 适配 0.10 | 8 | 5 | **8** |
| **加权总分** | **6.2** | **5.9** | **8.3** |

- **A 中心化静态**：实现最快、可观测好，但**无法适配算力悬殊**（轮询/静态标签 → 弱节点被派重活），无弹性、无成本感知。适合作为**冷启动最小集**。
- **B 去中心化自治/竞价**：对异构与成本最友好（节点自选活、竞价拿任务），但**实现复杂度高、可观测性差**，且与"云端是唯一权威状态源"的既有架构冲突；无中心真相源时**治理（D-23 硬门禁）无处挂载**。
- **C 中心调度 + 弹性池 + 分级抢占**：以云端 Scheduler 为唯一真相源（**关键任务与同步语义在中心**），节点侧 Worker 无状态拉取；在中心内实现"能力硬门槛 → 资源软约束 → 成本/负载打分 → 优先级抢占"四级路由。**复用 Redis/MinIO/NodeRegistry，零新增服务**。

> **结论**：推荐 **C（混合弹性）**，与 D-14「混合同步」同构——"中心负责权威与兜底，节点负责伸缩与执行"。B 的成本感知与竞价思想**内化为 C 的打分第③级**，而非另起一套去中心化体系。

**跨学科类比**：C ≈ HPC 集群的 **Slurm 中心调度 + backfill + QoS 抢占**（利用率与 SLA 兼顾），而非 Kubernetes 的声明式放置或 Bittensor 的市场竞价；调度粒度是**小时级批处理任务**，不是毫秒级容器编排。

---

## 2. 四维调研

### 2.1 维度一：AI / 分布式训练与调度

| 机制 | 成熟实现 | 对本方案的启示 |
|---|---|---|
| **三层容错** | Ray Train（worker 进程 / 节点 / driver 三层 + `checkpoint` + `max_failures`） | **直接借鉴**：任务级容错 = 重试上限 + checkpoint 恢复 + DLQ，无需进程级集合通信 |
| **弹性 min:max** | TorchElastic（`torchrun --min:max` + rendezvous c10d + snapshot reload） | 只借 **min:max + snapshot 重载语义**；**否决 rendezvous 本体**（两/多节点无同时在线同规模需求） |
| **异构感知调度** | HPC / Slurm node label + per-node feature；Roofline / profiling cost model | 能力标签 = "声明"，实测吞吐 = "打分依据"，二者分离（§3.2） |
| **QoS + 抢占 + backfill** | K8s PodPriority/Preemption、Slurm QoS/Preempt、YARN Capacity/Fair | 借**语义**（分级 QoS、可抢占标记、空闲槽 backfill），**不上引擎本体** |
| **策略抽象 / 生命周期** | Flower Strategy（select/aggregate 钩子） | D-20 已定"薄接口（4 钩子）"；调度层同理只做**单文件薄抽象** |
| **推理下沉与多版本路由** | Ray Serve / KServe / BentoML（多版本 + canary + 影子流量） | 对齐 **D-7 灰度 + D-21 内容寻址/atomic swap/LKG**；下沉节点须"能力 + digest 就绪"双重门 |
| **长时任务持久化** | Temporal / Cadence（durable execution，事件溯源 + 重试 + 补偿） | 任务生命周期状态机**持久化到 Redis/PG**，调度器重启不丢任务（防单点停摆） |
| **跨云/竞价成本编排** | SkyPilot（spot + auto-failover + 成本优化） | 成本感知：**关键路径常驻 / 可中断走竞价**，抢占时自动回退（§3.8） |
| **不适用** | Megatron TP/PP、Colossal-AI、TensorRT-LLM、vLLM 引擎本体、**gang scheduling** | 无 GPU 集群 / 无同步集合 / 无"全有全无"并行需求；任务粒度小时级，gang 无收益 |

### 2.2 维度二：传统金融 / 批处理调度

| 主题 | 方法 | 对本方案的启示 |
|---|---|---|
| **工作流编排** | Airflow / Prefect / Flyte / Argo（DAG、retry、**backfill**、SLA、pool、`priority_weight`） | 任务 = 带 **priority + pool（能力池）+ retry** 的一等公民；DLQ 兜底失败重放 |
| **任务队列** | Celery / RQ（priority、prefetch、`acks_late`、visibility timeout） | `acks_late` = 任务未确认即崩溃则**回队**（等价我们的 REQUEUE）；prefetch 防弱节点积压 |
| **量化回测农场** | 网格 / 随机 / 贝叶斯参数扫描（job array，Dask / four-pi 分布式回测） | 回测是**天然可并行、可抢占、可分片**的任务（N4 跨节点竞赛的载体） |
| **抢占与利用率** | 竞价/可中断实例（Spot/Preemptible）+ checkpoint | 抢占成本 = 丢失自上次 checkpoint 的计算 → **checkpoint 粒度需与抢占收益对齐** |
| **QoS 分级** | K8s Guaranteed / Burstable / BestEffort；金融关键/标准/可中断 | **三级 QoS**：critical（常驻、不可抢）/ standard（可排队）/ interruptible（可抢占、竞价） |
| **成本模型** | 边际成本（电费/云费）+ 抢占损失期望 + 利用率 | 打分第③级引入 **成本收益比**；backfill 提升空闲利用率 |
| **多重检验纪律** | Harvey-Liu-Zhu t>3.0 / DSR≥0.95（D-16 已定） | 调度**不得**因"多节点多跑"而放大假发现——试验计数 N_eff 仍按 D-16 归集 |

### 2.3 维度三：GitHub 成熟实现（只借语义）

| 仓库 / 框架 | 核心能力 | 借用方式 |
|---|---|---|
| **Ray**（`ray.train` / `ray.serve` / autoscaler） | 三层容错、checkpoint、多版本路由 | 容错与热加载**语义**（不引 Ray 本体） |
| **Slurm** | partition / QoS / priority / preempt / **backfill** | 四级路由 + 抢占 + backfill 的**语义蓝本**（本方案最贴近的参照物） |
| **Kubernetes scheduler framework** | Priority / Preemption / NodeAffinity / BinPack | 硬门槛（affinity）+ 软约束（bin-pack/spread）分层 |
| **Nomad** | bin-packing + spread + preemption + driver | 成本/负载打分（放与散）的参考 |
| **Celery / RQ** | priority / `acks_late` / visibility timeout | REQUEUE / DLQ / 幂等语义 |
| **Dask distributed** | worker 异构 + **adaptive scaling** | 弹性扩缩（按队列长度 scale）语义 |
| **Volcano / Kueue** | gang scheduling | **不适用**（无全有全无并行需求），仅记录为否决 |
| **Temporal / Cadence** | durable execution | 任务状态机持久化（防调度器单点停摆） |
| **SkyPilot** | spot + auto-failover + 成本优化 | 成本感知调度的参考实现 |
| **OpenDiLoCo** | inner/outer 双优化器 + 周期伪梯度（~180 行） | D-24 已定稿；调度需为其**让出同步窗口**（§3.9） |

### 2.4 维度四：本地代码现状与 gap

**已有可复用资产（勿重造）**：

| 组件 | 文件 | 现状 | 调度层用法 |
|---|---|---|---|
| **NodeRegistry** | `1-ARCHITECTURE/dreamos/registry/node_registry.py` | 节点单一真相源，`register/unregister/list_nodes(chain/tag)` + **`capabilities`（CapabilitySpec：category/provider_type/status）** + `find_nodes_by_capability` + `update_node_capability_status` | **能力标签的天然载体**；但**现为进程内单例**，跨节点需持久化（§3.2 gap） |
| **module_switches** | `4-MEMORY/9-工具与接口/module_switches.py` | L0-L3 独立开关，默认全 OFF | 调度器/弹性开关默认 OFF，零回归 |
| **Redis Streams** | 已用于认知聚合（`08-local-mirror.sh`）+ SPEC §5 API 草案 | 消费者组 | 任务分发 + 心跳 + 广播的**唯一总线**（O1） |
| **MinIO** | SPEC §5 presigned URL | 模型/结果直传 | 追加 **checkpoint** 桶（内容寻址 digest） |
| **GeneVersionManager** | `23-.../adapters/gene_version_manager.py` | 快照 + 一键回滚 | 版本/回滚模式复用（D-18/D-21） |
| **EntryModuleSelector** | `1-ARCHITECTURE/.../entry_module_selector.py` | 3 级降级择优 + 打分公式 | 竞赛任务（N3/N4）的打分的核心 |

**SPEC §5 已备的调度雏形（可直接扩编，不必另起）**：

- API 端点：`/api/worker/register` · `poll_task` · `report_result` · `heartbeat`（30s）· `status`
- 任务类型表：`evolution_train / bcrm2_optimize / param_sweep / bdsm_scan / backtest / feature_eng`（含 priority + timeout）
- 生命周期：`PENDING → ASSIGNED → RUNNING → COMPLETED / FAILED → REQUEUE(3) → DEAD_LETTER`
- 能力标签样例：`{"gpu":"m3_mps","mem_gb":16,"cpu_cores":8}`
- 故障判定：`now - last_heartbeat > 120s → OFFLINE → requeue`

**关键 gap（本报告要补的）**：

| # | gap | 影响 |
|---|---|---|
| G1 | 无"能力 × 负载"双维画像 | 只按静态标签路由 → 弱节点被派重活、拖慢整体 |
| G2 | 无弹性（min:max）语义 | 节点增减时任务无法伸缩，只能 1:1 派发 |
| G3 | 无优先级 / 抢占 / backfill | 关键任务可能排在长回测之后；空闲槽浪费 |
| G4 | 无 checkpoint 断点续传 | 节点掉线 → 长任务（4-8h）**从零重跑** |
| G5 | 无成本感知 | 无法区分"关键路径常驻"与"可中断竞价" |
| G6 | NodeRegistry 仅进程内 | 跨节点能力标签无**持久化真相源**（重启即失忆） |
| G7 | 调度无与同步协同（N13/N14） | 突变广播与任务调度**争抢算力/带宽** |
| G8 | 无推理下沉路由定义 | 推理落点无门禁，可能与训练抢同一节点 |

---

## 3. 关键设计决策（D-25~D-33 草案）

### 3.1 调度架构（中心权威 + 无状态拉取）

```
云端 Scheduler（唯一真相源：任务/指派/期望态）
   ├─ 任务表（PG/Redis 持久化：状态机）
   ├─ 节点表（NodeRegistry 持久化：能力标签 + 心跳负载）
   └─ Redis Streams（task_q / result_q / heartbeat / broadcast）
        │  节点"拉取"（pull，非推送）
        ▼
线下/异构 WorkerAgent（无状态；本地只持"实际态"）
   └─ poll_task → 下载数据(MinIO) → 执行(Conda 环境路由 D-13) → checkpoint → 上报
```

- **拉取而非推送**：Worker 无需公网暴露，防火墙友好（承 SPEC §5.1 "API 中转"结论）。
- **中心只持期望态**，节点持实际态 → 中心重启可由 PG/Redis 重放，**不产生僵尸指派**。
- **FAIL-OPEN**：Scheduler 不可用时，节点回退为"本地直跑"（不阻塞任务），对齐 HC-1a。

### 3.2 节点画像与能力标签（D-26）

**画像 = 声明能力（静态） × 实测负载（动态）**，二者严格分离（避免"自称强 / 实际弱"）：

```
┌── 静态·声明（注册时上报一次，变更需重注册）──────────────────────────────┐
│  compute_tier   T0 纯CPU轻量(4C8G) │ T1 M系列MPS(16G统一内存) │ T2 未来GPU │
│  capability[]   evolution_train / bcrm2_optimize / param_sweep /           │
│                 bdsm_scan / backtest / feature_eng / infer:<module>        │
│  hardware       cpu_cores / mem_gb / disk_gb / accel{mps|cuda|none}        │
│  environments   base / dreambuddy-torch（D-13，torch=CPU 或 MPS 需匹配）   │
│  cost_class     resident(常驻) / spot(可中断)                              │
└──────────────────────────────────────────────────────────────────────────┘
┌── 动态·实测（心跳 30s 上报，用于打分第③级）──────────────────────────────┐
│  load_avg / mem_used / disk_free / accel_util / queue_len / active_tasks[] │
│  throughput（近 N 任务实测单位时间产出）                                    │
└──────────────────────────────────────────────────────────────────────────┘
```

- **标签来源**：扩展既有 `NodeRegistry` 的 `capabilities`（`CapabilitySpec.category`）+ `tags`，**不新增注册体系**；但需**持久化**（PG 表或 Redis 哈希）以补 G6。
- **能力标签为硬门槛**（不可协商）：`evolution_train` 必须命中 `dreambuddy-torch` 环境 + `accel != none` 才可派。
- **负载为软约束 + 打分**：同能力节点间按负载/成本打分择优。

### 3.3 动态加入 / 退出纳管（D-27）

| 事件 | 触发 | 动作 |
|---|---|---|
| **加入** | `POST /api/worker/register`（能力标签 + `worker_id` + `boot_nonce`） | 写 NodeRegistry（持久化）+ 建立心跳；**幂等键防重名/僵尸** |
| **健康** | 心跳 30s 上报负载 | 更新节点表（动态画像）；连续正常 → `ONLINE` |
| **优雅退出** | Worker `draining`（收 SIGTERM） | 停止领新任务；在跑任务 checkpoint 后上报；节点标记 `DRAINING` |
| **超时驱逐** | `now - last_heartbeat > 120s` → `OFFLINE`；**2× 超时（240s）→ `EVICT`** | `OFFLINE` 即 requeue 未完成任务；`EVICT` 后从可调度池移除，等重注册 |
| **重入** | 同 `worker_id` 重新注册（`boot_nonce` 变化） | 覆盖旧记录（旧记录若已有未完成任务则先 requeue） |

- **幂等**：`worker_id + boot_nonce` 作唯一键，避免"同一物理机改了 hostname → 两个僵尸节点"。
- 与 **O2 HeartbeatMonitor** 一一对应（本报告 = O2 的设计输入）。

### 3.4 弹性范围与任务级容错（D-28）

- **每类任务声明弹性**：`elastic = {min: 1, max: N}`（N 由任务可切分粒度决定：回测/参数扫描 N 大，训练 N=1）。
- **扩缩依据**：可调度池中满足能力门槛的节点数在 `[min, max]` 内 → 按打分选 top-k。
- **容错（无 rendezvous / 无 NCCL）**：
  - 节点掉线 → 该节点任务 `REQUEUE`（最多 3 次）→ 超限入 `DEAD_LETTER`；
  - **仅在 checkpoint 后**才允许重排（否则退化为从零重跑，见 §3.6）；
  - **不引入**进程级集合通信（集合通信会等慢节点，与算力悬殊冲突，D-19 已定非 IID）。
- **不引入** TorchElastic rendezvous 本体（复核 REVIEW §2.4 否决项）；只借 `min:max` 与 **snapshot 重载**语义。

### 3.5 四级调度策略（D-29）——"按算力/负载"，而非轮询

```
任务提交（task_type, qos, resources, elastic{min,max}, checkpointable）
        │
① 能力硬门槛：capability / tag / 环境 必须命中
        │   不命中 → 直接拒绝（FAIL-OPEN：可回退本地直跑，不阻塞业务）
② 资源软约束：mem / disk / cpu 需容纳（防 OOM；取 queue_len 做门限）
        │
③ 成本/负载打分：score = w1·算力匹配度 + w2·(1/队列长度) + w3·历史吞吐 + w4·成本收益比
        │   选 top-1（可切分任务取 top-k 并行分片）
④ 优先级与抢占：见 §3.6
        │
   下发（Redis Streams task_q）→ Worker 拉取 → 执行 → checkpoint 周期落 MinIO
        │
   上报（含 digest + idempotency_key）→ 幂等去重 → 归档（result_q）
```

- 打分公式**权重可配**（默认 w1=0.4 / w2=0.2 / w3=0.3 / w4=0.1），与 EntryModuleSelector 打分**异曲同工**，但**独立实现**（不同语义，勿混用）。
- 回测类任务天然可切分 → top-k 并行分片 = **跨节点竞赛（N4）的调度载体**。

### 3.6 三级 QoS 与抢占 / backfill（D-30）

| QoS | 语义 | 抢占 | 成本类别 | 示例 |
|---|---|---|---|---|
| **critical** | 关键路径，不可抢占；空槽优先满足 | 不被抢占 | 常驻（resident） | 突变广播同步（N14）、模型热加载前验证 |
| **standard** | 常规训练/竞赛；可排队 | 可被 critical 挤压排序（不中断） | 常驻 | `evolution_train`、`bcrm2_optimize` |
| **interruptible** | 可中断、可抢占；空闲槽 backfill | 随时被抢占（checkpoint 后让位） | 竞价（spot） | 长回测、参数扫描、特征工程 |

- **抢占 = checkpoint + REQUEUE**（保存进度 → 重新入队 → 待有空闲再跑），**不是 kill -9**。
- **backfill**：interruptible 任务填补空闲槽 → **提升利用率**（HPC 经典手段）。
- **红线**：critical 一律不可抢占（防"抢掉同步任务导致协同断裂"，契合 D-23 硬门禁精神）。

### 3.7 checkpoint 与断点续传（D-31）

- **位置**：`s3://checkpoints/{task_type}/{task_id}/{step}.ckpt`，**内容寻址（SHA256 digest）**，对齐 D-21。
- **粒度**：与任务时长/抢占收益对齐（如 15–30 min 一次；由 `checkpoint_interval` 配置）。
- **恢复**：`REQUEUE` 或节点重连后 → 取最近 checkpoint → **warm-start 续跑**（对齐 D-17 warm-start，不重跑）。
- **命名约定**：借 `torch.distributed.checkpoint`（DCP）的**分片命名/重载约定**（REVIEW §1 表 #1：只借约定，**不引 DCP 本体**）。
- **幂等**：`idempotency_key = task_id + attempt_epoch`；重复上报按 digest 去重（防"重试导致重复 promote"）。

### 3.8 推理下沉的路由与热加载（D-32）

- **下沉门禁**（三重，缺一不可）：① 节点 `capability` 含 `infer:<module>`；② 该节点已就绪模型 `digest`（MinIO 拉取完成）；③ 节点 QoS 允许（critical 推理不下沉到 interruptible 节点）。
- **路由依据**：**数据亲和**（数据在哪个区域/节点） + **延迟预算**（实时推理仍留云端，水库/批推理可下沉） + **成本**（下沉到竞价节点省常态开销）。
- **热加载**：沿用 **D-21**（内容寻址 + atomic swap + last-known-good）+ **D-7**（默认直接切换；成熟期灰度比例）；下沉节点与云端用**同一 digest**，版本一致性由 digest 保证。
- **回滚**：加载失败 → atomic swap 回 last-known-good（D-18/D-21）。
- **红线**：**实时交易推理不下沉**（V15/事件驱动/BCRM2 实时信号必须在云端，承 SPEC §3.2 原则 1）。

### 3.9 成本感知调度（D-33）

- **成本模型**：`cost = 常驻边际成本(电费/云费) × 占用时长 + 竞价被抢占损失期望`。
- **分级投放**：critical/standard → 常驻节点；interruptible → 竞价/可中断节点（无竞价节点时回退常驻空闲槽）。
- **成本收益比入打分第③级**（w4）：同一任务在"快但贵"与"慢但省"节点间做权衡；**关键路径不受成本左右**（QoS 优先于成本）。
- **云成本红线**：仍守 **D-2（¥300-500/月）**——新增节点均为**线下自有机器**（M3 等），不新增云付费实例；成本感知在此语义下 = "**自有算力调度 + 电费/时长优化**"。

### 3.10 与训练协同（N13/N14）的衔接

- 调度器向同步层提供 **"同步窗口"**：N14 突变广播触发时，critical 同步任务**抢占 interruptible**，避免同步与长回测争抢带宽/算力（补 G7）。
- 调度**只决定"谁跑"**；**合并语义仍由 D-14~D-24 决定**（择优 + 部分迁移 + 禁全量覆盖 + 多样性硬门禁 D-23）。**调度不得绕过同步门禁**。

---

## 4. 五维交叉验证

### 4.1 评分（C 方案）

| 维度 | 评分 | 说明 |
|---|---|---|
| 完整性 | 8.5 | 覆盖训练/回测/推理下沉三类 + 节点全生命周期 |
| 可落地性 | 8.5 | 复用 NodeRegistry / Redis / MinIO；SPEC §5 已有 API 雏形可直接扩编 |
| 工程适配性 | 8.5 | 默认 OFF + FAIL-OPEN + 零回归；不引引擎本体 |
| 风险识别 | 8.0 | 识别单点、抢占成本、算力悬殊公平性、同步争抢 |
| 创新性 | 7.5 | "中心调度 + 弹性池 + 分级抢占"是成熟语义的本项目化组合（非新范式） |
| **综合** | **8.3** | 与 §1 加权一致 |

### 4.2 矛盾项清单

| # | 冲突 | 各维立场 | 倾向结论 | 验证手段 |
|---|---|---|---|---|
| C1 | 中心化效率 vs 单点风险 | AI/调度：中心权威更可观测；容错：单点即停摆 | **中心权威 + 无状态拉取 + 状态持久化 + 本地 FAIL-OPEN 回退** | 杀 Scheduler 进程 → 验证任务不丢、节点可本地直跑 |
| C2 | 弹性扩缩 vs non-IID 收敛 | 训练：参与集合变动加剧非 IID 偏差；调度：扩缩是收益 | **扩缩只影响"谁跑"，不影响"合并语义"**（合并走 D-17 择优+部分迁移，非 FedAvg 平均） | 不同集合跑同一任务，比对合并前后验证 loss |
| C3 | 抢占提利用率 vs checkpoint 成本 | 金融：utilization；训练：重跑代价高 | **仅 interruptible 可抢占 + checkpoint 粒度与抢占收益对齐** | 抢占频率 vs 重算代价曲线 |
| C4 | 算力悬殊 vs 公平/搭便车 | 反搭便车（D-23）：贡献计量；调度：弱节点拖累 | **贡献加权延伸至调度打分**（防"给弱节点派重活"） | 节点贡献度统计 vs 任务分配占比 |
| C5 | 成本感知 vs 关键路径 SLA | 成本：走竞价省；风控：关键任务不能断 | **QoS 优先于成本**：critical 一律常驻 | 抢占演练：critical 不被抢占 |

### 4.3 改进项

| 优先级 | 改进项 | 说明 |
|---|---|---|
| **P0** | 节点画像双维化（能力×负载） | 补 G1；NodeRegistry 持久化（补 G6） |
| **P0** | 弹性 min:max + 任务级容错 | 补 G2；REQUEUE/DLQ + checkpoint 前置 |
| **P0** | checkpoint 断点续传 | 补 G4；长任务（4-8h）不可从零重跑 |
| **P1** | 三级 QoS + 抢占 + backfill | 补 G3；提利用率且不伤关键路径 |
| **P1** | 推理下沉路由门禁 | 补 G8；与 D-7/D-21 对齐 |
| **P1** | 同步窗口协同 | 补 G7；调度让位于 N14 广播 |
| **P2** | 成本感知打分 | 补 G5；自有算力下为时长/电费优化 |

---

## 5. 与现有编号 / 文档的映射

| 本报告机制 | 对应既有编号 / 文档 | 关系 |
|---|---|---|
| 中心调度器（四级路由） | **O1**（SPEC Phase 2' · STATUS 3.1） | 扩编：O1 原为"任务分发+能力路由"，本报告补**四级路由 + 打分** |
| 心跳 / 动态纳管 | **O2** HeartbeatMonitor | 本报告 §3.3 = O2 的详细设计 |
| 多线下机器 / 弹性扩展 | **O5**（SPEC Phase 4'） | 扩编：O5 原为"按能力路由"，补**弹性 min:max + 抢占** |
| checkpoint / 断点续传 | 新增（原 SPEC 无） | 补 G4 |
| 三级 QoS / 抢占 / backfill | 新增（原 SPEC 无） | 补 G3 |
| 推理下沉路由 | 新增（原 SPEC 无） | 补 G8 |
| 内容寻址 / atomic swap / LKG | **D-21** | 直接复用（checkpoint 与模型同一寻址体系） |
| 择优 + 部分迁移 + 禁全量覆盖 | **D-17 / D-23** | 调度**不得绕过**；合并语义不变 |
| 同步窗口 | **N13 / N14**（PLAN 已备） | 调度让位于广播；critical 不可抢占 |
| 跨节点竞赛载体 | **N4** | 回测 top-k 分片 = 跨节点竞赛的调度实现 |
| 能力标签载体 | **NodeRegistry**（capabilities/tags） | 复用 + **持久化**（补 G6） |
| 开关 / 零回归 | **module_switches / HC-1a / HC-9** | 调度与弹性开关默认 OFF |
| 环境路由 | **D-13**（base / dreambuddy-torch） | 能力硬门槛的一部分 |

> **定位澄清**：D-14~D-24 解决的是"**同步什么、怎么合并**"；本报告解决的是"**谁跑、跑在哪个节点、跑不完怎么办**"。二者正交，衔接点是 §3.10 的同步窗口。

---

## 6. 演进路径（接续框架研究 §5.2 六阶段）

原六阶段路线图（N1 → N3/N5 → N10 → O1/O2/N4/N7 → N8 → N9）**保持不变**；本报告将**本报告机制挂载到"阶段 4"并增设 4.5**：

| 阶段 | 内容 | 与本报告关系 | 优先级 |
|---|---|---|---|
| 阶段 1-3 | 认知分层 / 单节点竞赛 / 模型同步 | 不变 | P0 |
| **阶段 4（扩编）** | O1 任务队列 + O2 心跳 + O5 多机 | **吸收 §3.1/3.2/3.3**（架构 + 画像 + 纳管） | P1 |
| **阶段 4.5（新增）** | 弹性池 + 抢占/backfill + checkpoint 断点续传 + 推理下沉路由 | **本报告新增**（§3.4~3.8） | P1-P2 |
| 阶段 5-6 | 权重 delta / 联邦学习 | 不变（本报告只为其提供"同步窗口"） | P1-P2 |

**依赖关系**：
```
阶段1(N1) ────────────────────────────┐
阶段2(N3+N5) ─→ 阶段4(N4) ─→ 阶段6(N9) │
阶段3(N10) ─→ 阶段5(N8) ─────────────┘
阶段4 = O1 + O2 + O5 ─→ 阶段4.5（弹性/抢占/checkpoint/推理下沉）
阶段4.5 依赖 阶段4 的节点画像与心跳（§3.2/3.3）
阶段4.5 与 阶段3(N10) 共享 D-21 内容寻址
```

> **可立即启动**：NodeRegistry **持久化**（补 G6）与 checkpoint 桶定义（补 G4）**不依赖** O1/O2，可作为阶段 4 的前置独立推进。

---

## 7. 风险与对策

| 风险 | 概率 | 影响 | 对策 |
|---|---|---|---|
| Scheduler 单点（挂 = 调度停摆） | 中 | 任务积压 | 状态持久化 + 无状态拉取 + 节点 FAIL-OPEN 本地直跑 |
| 弱节点被派重活拖慢整体 | 中 | 性能反降 | 能力硬门槛 + 负载打分 + 贡献加权（C4） |
| 抢占频繁导致反复重跑 | 中 | 利用率反降 | 抢占仅限 interruptible + checkpoint 粒度对齐收益（C3） |
| non-IID 下弹性集合加剧发散 | 中 | 模型退化 | 合并走 D-17 择优+部分迁移（非平均）+ 验证门禁 |
| checkpoint 存储膨胀 | 低 | MinIO 成本 | 内容寻址去重 + LKG 最小集 + TTL 轮转 |
| 调度与突变广播争抢资源 | 中 | 同步延迟 | 同步窗口 + critical 不可抢占（§3.10） |
| 能力标签虚标（自称强实际弱） | 低 | 误派 | 声明/实测分离，打分以**实测吞吐**为准 |
| 推理下沉破坏实时性 | 低 | 交易受损 | 红线：实时推理不下沉；下沉仅限批/水库推理 |

---

## 8. 新增决策草案（D-25~D-33）与待议问题

### 8.1 决策草案（**待用户评审后并入 SPEC §12.1**）

| 编号 | 决策项 | 草案值 | 域 |
|---|---|---|---|
| **D-25** | 调度架构 | **中心权威 + 无状态拉取（pull）**；**不引入** K8s/Ray/Slurm/YARN/Volcano 本体 | 调度 |
| **D-26** | 节点画像 | **声明能力（静态，硬门槛）× 实测负载（动态，打分）** 双维；标签复用 NodeRegistry `capabilities`/`tags` 并**持久化** | 调度 |
| **D-27** | 动态纳管 | 注册（`worker_id`+`boot_nonce` 幂等）· 优雅 draining · 心跳 120s→OFFLINE / 240s→EVICT · 重入覆盖旧记录 | 调度 |
| **D-28** | 弹性与容错 | 任务声明 `min:max`；节点掉线 → checkpoint 后 REQUEUE（≤3）→ DEAD_LETTER；**不引入 rendezvous/NCCL** | 调度 |
| **D-29** | 调度策略 | **四级路由**：①能力硬门槛 → ②资源软约束 → ③成本/负载打分（w1算力/w2队列/w3吞吐/w4成本比） → ④优先级抢占 | 调度 |
| **D-30** | 优先级与抢占 | **三级 QoS**（critical 不可抢占 / standard 可排队 / interruptible 可抢占+backfill）；抢占 = checkpoint + REQUEUE | 调度 |
| **D-31** | checkpoint | MinIO **内容寻址(SHA256)** + 周期 snapshot + **warm-start 续跑**；借 DCP 命名约定，**不引 DCP 本体**；幂等键 `task_id+attempt_epoch` | 调度 |
| **D-32** | 推理下沉 | 三重门禁（能力含 `infer:<m>` + digest 就绪 + QoS 允许）；路由按数据亲和/延迟预算/成本；热加载沿用 **D-21 + D-7**；**实时推理不下沉** | 推理 |
| **D-33** | 成本感知 | **QoS 优先于成本**；critical/standard→常驻，interruptible→竞价/空闲槽；成本收益比入打分 w4；**不新增云付费实例**（守 D-2） | 成本 |

### 8.2 待议问题（Q-8~Q-11）

| 编号 | 问题 | 建议 | 影响 |
|---|---|---|---|
| Q-8 | checkpoint 周期默认值 | 30 min（长任务）/ 任务自定 | G4 落地节奏 |
| Q-9 | 打分权重默认值（w1-w4） | 0.4 / 0.2 / 0.3 / 0.1 | 调度偏好 |
| Q-10 | 是否允许 critical 抢占 standard（非仅 interruptible） | 建议**不允许**（只对 interruptible） | 稳定性 |
| Q-11 | 推理下沉范围（仅批/水库 vs 含准实时） | 建议**仅批/水库** | 交易安全 |

### 8.3 实施建议（评审后决定是否落 PLAN）

| 优先级 | 任务 | 依赖 | 说明 |
|---|---|---|---|
| **P0** | NodeRegistry 持久化 + checkpoint 桶定义 | 无 | 可独立先做（阶段 4 前置） |
| **P0** | 节点画像（能力×负载）+ 动态纳管（= O2） | 无 | 阶段 4 核心 |
| **P1** | 四级路由 + 弹性 min:max + REQUEUE/DLQ（= O1/O5 扩编） | O2 | 阶段 4/4.5 |
| **P1** | checkpoint 断点续传 | D-21 | 阶段 4.5 |
| **P1** | 三级 QoS + 抢占 + backfill | 四级路由 | 阶段 4.5 |
| **P2** | 推理下沉路由门禁 | D-7/D-21 | 阶段 4.5 |
| **P2** | 同步窗口协同（与 N13/N14） | N14 | 阶段 4.5 |

---

## 附录 A：参考来源

### 论文 / 规范
- OpenDiLoCo, Prime Intellect（`github.com/PrimeIntellect-ai/OpenDiLoCo`）；DiLoCo, arXiv:2311.08105
- Harvey, Liu, Zhu 2016（多重检验 / t>3.0）；Deflated Sharpe Ratio（D-16 已定）
- TorchElastic（`min:max` + rendezvous c10d + snapshot）；`torch.distributed.checkpoint`（DCP 命名约定）
- Ray Train 三层容错（worker/node/driver + `max_failures` + checkpoint）

### 开源实现（借鉴语义，不引本体）
- Slurm（partition / QoS / priority / preempt / **backfill**）
- Kubernetes scheduler framework（Priority / Preemption / NodeAffinity / BinPack）
- Nomad（bin-packing / spread / preemption）
- Celery / RQ（priority / `acks_late` / visibility timeout）
- Dask distributed（worker 异构 + adaptive scaling）
- Temporal / Cadence（durable execution）
- SkyPilot（spot + auto-failover + cost optimization）
- Airflow / Prefect / Flyte / Argo（DAG / retry / backfill / pool / `priority_weight`）
- Ray Serve / KServe / BentoML（多版本路由 + canary + shadow）
- **否决**：Volcano / Kueue（gang）、Ray / K8s / Slurm 引擎本体、MLflow Registry 服务端、Flower 本体、TorchElastic rendezvous、DCP 分片

### 本仓库
- `1-ARCHITECTURE/dreamos/registry/node_registry.py`（能力标签 + 节点真相源）
- `4-MEMORY/9-工具与接口/module_switches.py`（默认 OFF）
- `31-分布式计算部署/phase7/08-local-mirror.sh`（Redis Streams / MinIO 复用）
- `31-分布式计算部署/docs/SPEC-分布式计算协同部署方案.md` §5（API 端点 + 任务类型 + 生命周期雏形）
- `23-四层闭环自进化交易架构/dreambuddy_evolution/adapters/gene_version_manager.py`（版本/回滚）

---

## 附录 B：认知闭环

- **前置 `recall`**：命中 VM-1791966930462（框架 9 机制对照，C 级）、VM-1791966949192（分布式训练框架三分类，C 级）、VM-1791851949213（SLTP floor 硬约束，C 级）、VM-1791507639893（macOS 沙箱调度，B 级）。结论与既有 D-14~D-24 自洽，**无重复调研**。
- **后置 `record`**：本报告结论（调度架构 + 画像 + 弹性 + 抢占 + checkpoint + 推理下沉 + 成本）与承继硬约束（不引引擎本体 / 默认 OFF / FAIL-OPEN / 零回归 / QoS 优先于成本 / 实时推理不下沉）以 **B 级**写入认知库，tags 含 `硬约束` + `分布式调度` + `异构节点`。
