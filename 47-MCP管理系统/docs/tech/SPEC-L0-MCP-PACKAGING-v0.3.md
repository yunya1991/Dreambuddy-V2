# SPEC:L0 六域 MCP 封装（Packaging）— 契约、边界与实施路线

> **版本**: v0.3 ｜ **更新日期**: 2026-11-02 ｜ **状态**: ✅ 决议落定——B1-B6 / G1-G3 已经 ALIGNMENT-46-47 对齐审查落定(见 §8)，可开工；文档终审(approved)按 R8 归云端签发
> **v0.3 变更**: 按 [ALIGNMENT-46-47 v1.0](./ALIGNMENT-46-47-v1.0.md) 的 Go/No-Go 决议修订：主功能禁 FAIL-OPEN、写主体=编排侧、壳实例进程级共享、能力集单一载体、45 两类评测改名、异步 job 状态登记
> **上游**: [REPORT-L0-MCP-DSH-IMPACT v1.1](../../../46-DSH架构/docs/tech/REPORT-L0-MCP-DSH-IMPACT-v1.1.md)（影响评估 v1.1，吸收本 SPEC 评审实证并修正 F1/F2/F6 三处偏差）
> **上游**: SPEC-L0-three-layer-architecture v0.5（§3.1 六 port + 统一信封，本 SPEC 是其 L0-P 的**对外协议面**）
> **定位**: 实施 SPEC。REPORT 回答"要不要做"，本 SPEC 回答"怎么做"。
> **硬约束**: 单人维护 / FAIL-OPEN / 云端 4C16G / stdio 按需拉起（不常驻、不开放网络端口）/ 零回归 / **实盘交易链路（11/yijing/v15/止损）永不暴露 MCP** / 壳零业务逻辑（训练优化载体在域内，不在壳）

---

## 0. 对上游 REPORT 的两处修正（评审结论）

| # | REPORT 原文 | 实证修正 |
|---|---|---|
| F1 | §2.1 "REA MCP：已有 adapter + 单测(218 行)" | `33-REA逆向解析工程/adapters/rea_mcp_adapter.py` 是 **MCP client**（调外部 npm 包 `rea-agents` 的 133 个二进制逆向工具），**不是 33 域自身能力的 MCP server**。33 域对外接口现状 = `dsh_nodes.py`（S33_rea_analyze/trace/compare）。REA MCP 属**新建 server 包装 dsh_nodes**，rea_mcp_adapter 方向相反、不在本 SPEC 范围 |
| F2 | §3.5/P2 "认知 MCP 本地直连为主、远端可选" | **有数据分叉风险**：认知库事实源在云端（云端=交付目标），本地 stdio 拉起将读写本地 `4-MEMORY/data/cognitive_memory.db`，与云端库形成双事实源。修正为：**ssh 云端拉起保持默认（单一事实源）；本地拉起仅作离线只读降级（写工具在本地模式禁用）**。形态：`mcp.json` 双条目 `cognitive`（默认 ssh 云端）+ `cognitive-local`（可选，本地，readonly 模式） |

另补 REPORT 未覆盖的三个实证（已代码核实）：

- F3：**39-金融语义蒸馏系统已有第 3 个 MCP server**（`39-金融语义蒸馏系统/scripts/mcp_server.py`，4 工具：distill_aliases/query_entity/training_feed/semantic_lookup，已自觉区分读写并标注"写操作需确认"）。**用户决策（2026-11-02）：39 正式纳入 L0**，工具语义归 Search 域（语义面：query_entity/semantic_lookup 读；distill_aliases/training_feed 写），**不新增 port**（上限 6 不变）；契约注册表将其登记为**存量第三面**，统一信封对齐。
- F4：**sys.path hack 普遍存在**（cognitive_mcp_server L38-43、dreambuddy_l0/facade.py load_cle L51-57、45 api/server.py L18-20、21 测试直插 18/20）。壳作为独立进程必须有统一 import 规约（§3.4）。
- F5：**19-DAL 用全局 `DB_BACKEND` env 选后端**（json_legacy/dual_write/sqlite_unified，默认 json_legacy）。壳被不同宿主拉起时 env 不一致会导致同一工具行为漂移（§3.5）。

---

## 1. 定位（吸收 REPORT §1.1；D1 已确认）

**MCP = L0 的对外统一出口（边界适配层），不是内部调用链改造。**

- 内部：L1/L2 继续走 in-process port（`dreambuddy_l0/ports/` 六 port Protocol **不动**）
- 外部：Trae / DSH Worker / 云端 Agent 走 MCP stdio 壳
- 热路径（L1 判定、实盘链路）**永不走 MCP**（零 token 与低延迟承诺）

## 2. 三维合理性裁决（金融 / 代码工程 / AI 发展）

### 2.1 金融维度：8.5/10，条件合理

| 依据 | 映射 |
|---|---|
| SR 11-7 模型风险管理三支柱（概念文档化/持续监控/结果验证） | 契约注册表=文档化；45 契约评测=持续监控；认知 verify 贝叶斯升级链=结果验证 |
| EU AI Act 日志可追溯 / VeritasChain VCP 防篡改审计 | trace_id 五跳透传（Router→Worker→MCP→DAL）为强制；审计落本地哈希链（复用 45 平台工程结论：Sigstore Bundle+MinIO WORM 指针，**不引外部在线依赖**） |
| 机构实践（JPMorgan Ask David=多 Agent+受控工具面；Citadel=risk as product） | 能力集按 Worker 角色裁剪（≤10 工具）；写工具=Mandate 授权单元 |
| 实盘隔离行业做法 | 实盘链路永不暴露 MCP；数据 MCP 只读经 19-DAL；库管禁裸 SQL |

**前置条件**：写工具默认禁用 + Ticket Mandate 显式授权 + 45 门禁，缺一则裁决降至 5/10。

### 2.2 代码工程维度：9/10，合理

- ports & adapters 外层加协议壳 = 六边形架构标准外延（壳=secondary adapter 的反向：driving adapter），业界同构（K8s CRI、LSP 对编辑器）
- stdio 按需拉起正确：本地智能体场景 stdio 延迟/运维/安全面均优于常驻 HTTP；与 MCP 官方 2025 演进方向一致（本地 stdio / 远端 Streamable HTTP 二分）
- **聚合 2-3 server 优于一域一 server**（工具面膨胀 R1 是最高风险）：认知+检索+语义(39)（读面聚合）/ 数据+库管只读 / 评测+REA
- **替代方案已对比（7 模式·框架锁定自查）**：单壳多工具（dreambuddy_l0 facade 直暴露）被否决——单壳使六域工具面对每个 Worker 全量暴露，正触发 R1；聚合壳按"读面/数据面/长任务面"分组，能力集裁剪粒度与 Worker 角色对齐
- schema 治理：语义化版本 + 契约注册表（§3.7）+ 漂移门禁（fakes/ golden 测试）

### 2.3 AI 发展维度：8.5/10，合理且前瞻

- MCP 生态（2024.11 发布→2025 官方 Registry + tool annotations + OAuth 2.1）已是 Agent 工具暴露事实标准；**tool annotations 的 `readOnlyHint`/`destructiveHint` 正好承载写工具治理**（声明即元数据，宿主可据此刻意拦截）
- 工具粒度最佳实践：领域语义命名（非 DB 行级）、错误语义枚举化、分页强制——与统一信封 4 新字段（version/trace_id/idempotency_key/error_code）对齐
- "按需取用+内部训练调优"载体分层：**训练在域内（port 实现体），壳只做协议映射，能力集/注册表做取用编排**——本方案三层均已有落点

## 3. 核心契约

### 3.1 壳定位与目录

- 壳**不计入** SPEC-L0 §3.1 的 port 上限 6（壳是对外协议面，非 port）
- 新壳统一放 `mcp_shells/`（顶层新目录），存量三壳（认知/39/REA-client）原位保留、登记注册表
- 壳内**零业务逻辑**：只允许 协议解析→port/域入口调用→信封映射 三段
- **壳实现语言 = Python**（与六 port 同栈，宿主 TS/Python 均可 stdio 拉起；评审 DA4）
- **stdio 进程模型明文（评审 DA6）**：stdio 壳为 **1 宿主 = 1 壳进程**，N 个 Worker 并发 = N 个壳进程 = N×DB 连接——**REPORT §3.6"server 作单点连接池"论据在 stdio 模式下不成立，予以删除**；连接治理下沉到 19-DAL 层（连接上限/方言能力集声明，SPEC-L0 §3.1），壳内禁止自建连接池；连接上限具体数值以 19-DAL 治理方案定义为准，壳不感知具体数值
- **壳实例拓扑（G2 定稿）**：`宿主` = **DSH 运行时进程**。同一运行时进程内**按域共享单壳实例**，Worker 会话只持「工具调用句柄」→ 连接数 = 域数（聚合后 3），而非 Worker 数；跨进程（云端／本地）才各自拉起。此口径优先于上一条的 N× 推演

### 3.2 统一信封 ↔ MCP schema 映射（防第二事实源）

| 信封字段 | MCP 映射 |
|---|---|
| `ok` | 工具返回 `isError` 反向映射；`ok=true` 且 data=None（源可达无数据）≠ 错误 |
| `data` | 结构化 content（JSON text block） |
| `source/timestamp/degraded/meta` | content 内嵌 envelope 对象原样透传 |
| `error_code`（枚举） | 六值 `not_found/unavailable/conflict/invalid/timeout/degraded`；**禁止自由文本 reason 直出** |
| 异步任务（评测/REA 长任务） | 两段式：`submit_*` 返回 `ok+meta.job_id`；`poll_*` 返回 `state=running/success/failed` + 结果信封。**持久层强制（评审 DA1）**：壳进程按需拉起即退，job 状态必须落持久层——评测落 45 PG 八表（已有，`001_init.sql` 实测 8 个 CREATE TABLE）；**REA 落 JSONL 状态文件**（`33-REA逆向解析工程/reflection_data/mcp_jobs/<job_id>.json`，shadow 期最简载体，禁止内存态）；无持久层的域不得暴露异步工具 |
| **FAIL-OPEN 分型（B1 定稿）** | 增强型能力（recall 先验／投机预取）可 FAIL-OPEN 返回空，但 **meta 必须标 `degraded=true`**；**主功能（统一检索／数据查询／评测裁决）禁止 FAIL-OPEN**，不可用必须 `ok=false + error_code=unavailable`；壳崩溃／超时由宿主兜底并打 `degraded + error_code`，**不得等同于「无结果」** |

> **job 状态归属（B6 定稿）**：45 PG 与 33 JSONL 的 job 状态均属 **L0 域内状态**，登记于域内存储，不构成第二事实源（SSoT §1.8）。

### 3.3 工具治理（写工具 = 权限单元）

- 所有工具声明 MCP annotations：只读工具 `readOnlyHint=true`；写工具 `readOnlyHint=false + destructiveHint` 视语义
- 写工具（record/verify/distill_aliases/training_feed/…）**默认禁用**，由 Ticket Mandate 按 scope 显式授权；越权调用**明确拒绝**（非静默降级），审计留痕
- **Mandate 授予对象 = 编排侧（Router／Settle 节点／Verifier），不是 Worker（B2 定稿）**。Worker **默认只读**；`settle` 写回由编排侧 Settle 节点执行。主体×权限矩阵见 46 DESIGN ADR-9
- 幂等：写工具必接 `external_id`（沿用 C8 先例），重复调用幂等返回
- 库管域（38）**只读**（表结构/迁移状态/一致性），写走 CLI+CI，永不进 MCP

### 3.4 壳进程 import 规约（治 sys.path hack，F4）

- 新壳：**禁止新增 `sys.path.insert`**；统一 `PYTHONPATH=<repo root>` 由宿主 mcp.json `env` 注入，或以 `python3 -m mcp_shells.<domain>` 包方式拉起
- 存量 hack（cognitive_mcp_server 等 4 处）登记白名单，随各壳规范化逐步清零

### 3.5 环境继承规约（治 DB_BACKEND 漂移，F5）

- 壳默认**继承宿主 env**，壳内禁止改写 `DB_BACKEND` 等全局开关
- 后端选择不暴露为工具入参（防调用方越权切后端）；需要多后端验证时走独立 profile（宿主层切换）
- ssh 云端拉起模式认证沿用宿主现有 ssh 密钥机制，壳内不管理凭证；壳进程异常退出由宿主（mcp.json 拉起方）负责重启，壳内不自建守护进程

### 3.6 观测

- `trace_id` 全链路透传（Router→Worker→MCP→DAL），缺失时壳生成并标注 `meta.trace_origin=shell`
- 每次调用 = 一个 span；45 Evidence Bundle 直接引用调用链

### 3.7 契约注册表载体（评审 DA5）

- 载体 = **文件 + CI 校验**：`47-MCP管理系统/registry/mcp_capabilities.yaml`（Schema 复用 DreamOS `CapabilitySpec` 字段 + 增补 `shell_cmd/transport/envelope_version/tool_annotations`）
- **不加载进运行时注册表**（沿用 SPEC-L0 §3.2 组件①口径：进程内存态注册表与多进程现实冲突）
- CI 校验：schema 合法性 + 工具名唯一性 + 与 `mcp_shells/` 实际工具面漂移比对（复用 validate_capabilities 思路）；未登记的新壳不得上线

### 3.8 延迟 SLO 基线方法（评审 DA2）

- **时序明确（先基线，后生效）**：D4 数值为目标值，须在基线测量完成并产出基线报告后方可作为验收生效标准。P0 必须先测基线：in-process 直调 vs stdio 壳各 100 次取 P50/P95，基线报告落 `47-MCP管理系统/registry/latency_baseline.md`
- "不劣化"（V4）判定 = 壳 P50 ≤ 基线 in-process P50 + 45ms（本地 stdio 开销预算），超预算须归因报告

## 4. 分域实施路线（吸收 REPORT §6.2 并修正）

| 阶段 | 内容 | 前置 | 验收 |
|---|---|---|---|
| **P0** | ①能力集设计（Worker 角色→工具集矩阵，每角色 ≤10 工具）②契约注册表 v1（**含存量三面登记**：认知/39 语义/REA-client）③统一信封映射层（`mcp_shells/_shared/`）④认知壳读写分 scope（写默认禁） | 无 | 能力集矩阵评审通过；越权写被拒且留痕 |
| **P1** | ①数据 MCP（只读，只经 19-DAL，Collector+Store 语义）②评测 MCP（适配层复用 45 HTTP :8790，异步 submit/poll） | P0 + **19-DAL 连接上限落地（B3 前置，非 P1 内含）** | DAL 审计无旁路；两段式跑通；3 并发下连接数不超上限 |
| **P2** | ①REA MCP（新建 server 包 `dsh_nodes.py`，长任务两段式，shadow 起步）②认知壳双模改造（**ssh 云端默认 + 本地只读降级**，修正 F2） | P1 | shadow 无回归；无双事实源 |
| **P3** | ①库管只读工具（38）②45 增「**MCP 契约评测**」维度（schema 兼容性 + FAIL-OPEN 回归；与「45 业务门禁」严格区分） | P2 | 契约评测可拦截 schema 破坏 |

**优先级依据**（与 REPORT 价值分级一致）：数据/评测 ★★★★★ 先行；检索保持聚合不拆壳；库管 ★☆ 只读最后；实盘链路永不进范围。

## 5. 风险登记（吸收 R1-R8，标注修正）

R1 工具面膨胀（高，能力集裁剪）｜R2 并发写污染（高，Mandate+幂等）｜R3 信封语义破坏 FAIL-OPEN（高，§3.2）｜R4 热路径延迟（中高，不迁 MCP）｜R5 绕 DAL 直连（中高，§4 P1 审计）｜R6 契约漂移（中，注册表+版本）｜R7 观测断裂（中，§3.6）｜R8 ~~ssh 单点~~ → **修正为"双事实源风险"**（中，F2 双模只读降级）

## 6. 验收标准（吸收 V1-V5 + 增补）

- V1 能力集矩阵全覆盖，每角色工具 ≤10 ｜ V2 越权写明确拒绝+留痕 ｜ V3 信封三态可区分（单测覆盖）｜ V4 热路径 P50 不劣化 ｜ V5 trace_id 贯穿率 100%
- **V6（增）**：契约注册表登记全部存量 MCP 面（认知/39/REA-client），新壳未经注册不得上线
- **V7（增）**：认知壳本地模式写工具禁用有单测；云端 ssh 断连时本地只读降级可用

## 7. 决策记录（D1-D5 用户已确认 2026-11-02）

| # | 决策项 | 结论 |
|---|---|---|
| D1 | "对外出口"定位（非唯一通道） | ✅ 已确认 |
| D2 | 聚合粒度：2-3 聚合 server（认知+检索+语义 / 数据+库管只读 / 评测+REA） | ✅ 已确认 |
| D3 | 库管不做通用写（只读 + CLI/CI 保留） | ✅ 已确认 |
| D4 | 延迟 SLO（in-process P50<5ms / MCP 本地<50ms / 远端<200ms） | ✅ 已确认（数值为方向性，以 P0 基线报告校准；判据 = 壳 P50 ≤ in-process P50 + 45ms） |
| D5 | 认知壳形态：ssh 云端默认 + 本地只读降级（修正 REPORT"本地为主"） | ✅ 已确认 |
| D6 | 39-金融语义纳入 L0（归 Search 语义面，不新增 port）；建 47-MCP管理系统 为 MCP 域文档 SSoT | ✅ 已确认 |


---

## 8. 开工前对齐决议（2026-11-02，按建议默认落定）

| # | 决议 | 落点 |
|---|---|---|
| B1 | FAIL-OPEN 分型：增强型可 FAIL-OPEN（标 degraded）；**主功能禁止 FAIL-OPEN**（必须 error_code） | 本 SPEC §3.2 信封表 |
| B2 | 写主体 = 编排侧（Router／Settle／Verifier）；**Worker 默认只读**，settle 由编排侧执行 | 本 SPEC §3.3 + 46 DESIGN ADR-9 |
| B3 | 19-DAL **连接上限**升为 P1 开工前置；P0 阶段 1 Worker 试点规避 | 本 SPEC §4 P1 前置 |
| B4 | 能力集**单一载体** `47/registry/mcp_capabilities.yaml`；46 只定角色→能力标签 | 本 SPEC §3.7 + 46 DESIGN ADR-4 |
| B5 | 「45 业务门禁」≠「45 MCP 契约评测」，两维度独立登记 | 本 SPEC §4 P3 + 46 P2 术语 |
| B6 | 异步 job 状态属 **L0 域内状态**，登记后不构成第二事实源 | 本 SPEC §3.2 + SSoT §1.8 |
| G1 | 主体×权限矩阵：Worker 读／编排侧读写／Verifier 记裁决／CLI·CI admin | 46 DESIGN ADR-9 |
| G2 | 壳实例按 **DSH 运行时进程级共享**，Worker 只持句柄 | 本 SPEC §3.1 |
| G3 | Ticket `paused` 增子因 `waiting_event／waiting_job／waiting_person`，**禁止忙轮询** | 46 DESIGN ADR-3 |

> **开工条件**：以上 9 条已全部落定；剩余 `19-DAL 连接上限` 为 P1 前置（不阻塞 P0）。
