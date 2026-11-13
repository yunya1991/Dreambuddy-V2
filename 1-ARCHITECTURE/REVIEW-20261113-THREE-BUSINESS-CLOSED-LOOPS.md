# REVIEW：三大业务闭环链 SPEC v0.1.0 评审

> **版本**: v1.0
> **更新日期**: 2026-11-13
> **评审对象**: [SPEC-20261113-THREE-BUSINESS-CLOSED-LOOPS.md](./SPEC-20261113-THREE-BUSINESS-CLOSED-LOOPS.md) v0.1.0
> **评审方式**: 静态文档 + 代码/契约抽查对照（未运行服务、未重跑云端链路）
> **评审结论**: **条件通过（Conditional Accept）**，需修订至 v0.2.0 后复评
> **复评状态**: ⏳ 待复评（SPEC 已提交 v0.2.0 修订，4 项 P0 修改点见其 §15 变更记录）
> **复评前置**: 关闭 R-P0-01 ~ R-P0-04 四项阻断问题
> **当前授权范围**: 仅可用于架构讨论与差距分析；不构成 P1/P2 实施、live 切流或 MCP 写工具上线授权

---

## 一、评审范围与方法

### 1.1 范围

| 维度 | 内容 |
|---|---|
| 评审对象 | 三大业务闭环链 SPEC v0.1.0 全文 15 章 |
| 一致性对照 | SYSTEM_ARCHITECTURE_OVERVIEW v4.2、49 SPEC v0.14.2、50 SPEC v0.2.0、48 FULL-CHAIN v1.0、48 D2-D3-CHAIN v0.1、46 DESIGN v0.2、47 L1L2-MCP-PACKAGING v0.1 |
| 实现抽查 | `l1_route_signal.py`、`task-manager.ts`、`chat/ChatPanel.tsx`、`data/query/route.ts`、`task/stream/route.ts`、`25/strategy_gen/intent.py`、`28/.../webhook.py`、`47/registry/`、`36 Signal Bus` |
| 不在范围 | 运行态压测、云端一致性、live 权限、业务代码实现质量 |

### 1.2 方法

1. 逐章核对"当前证据 / 目标态 / 待评审"三类断言是否被正确分列；
2. 对 SPEC 引用的每个权威结论回查源文档与代码；
3. 检查门禁与任务是否具备**机器可判定**的验收口径；
4. 检查是否存在越权定义领域契约（接管 49/48/46/47 的定义权）。

### 1.3 总体判断

SPEC 成功把"模块串联"提升为"业务闭环"，权限分离、三平面、能力生命周期、MCP 边界四条主线**方向正确且与既有 SSoT 不冲突**。未发现越权改写领域契约的情况。

但存在四类阻断问题：**跨文档主干口径冲突、能力包无承载、双信封幂等风险、门禁不可判定**。这四项不解决，P1/P2 无法开工，G-BCL 门禁形同虚设。

---

## 二、五项裁决（DEC-BCL-01 ~ 05）评审结果

| ID | SPEC 推荐 | 评审结论 | 附条件 |
|---|---|---|---|
| DEC-BCL-01 | 采用"三大业务闭环链"命名 | ✅ **接受** | 需补全 `chain_id` 命名空间全集（现仅给 `trading.nn` 一例），见 R-P2-04 |
| DEC-BCL-02 | 50 是 NN 链出口，23 独立对照 | ⚠️ **有条件接受** | 必须先解决 R-P0-01：48 域现写 `48→40→43→49→50`，与 SPEC `40→43→42→50` 冲突 |
| DEC-BCL-03 | 6 定位 L2 研究分析核心 | ✅ **接受** | 需补现状到目标态的迁移路径（开关/文件/双入口），见 R-P1-07 |
| DEC-BCL-04 | 25—28 拆确定性经典模式与 LLM 模式 | ⚠️ **有条件接受** | "确定性经典模式"无任何实现证据，属**新建**而非"收敛"；P1-06 口径须改写，见 R-P1-06 |
| DEC-BCL-05 | 48 管判据/实验/度量/裁决，34 与领域模块管训练与生成 | ✅ **接受** | 需补生命周期状态转移判据与具名主体，见 R-P1-09 |

**裁决合计**：接受 3 项，有条件接受 2 项，无驳回。

---

## 三、阻断问题（P0，必须在 v0.2.0 关闭）

### R-P0-01 交易主干运行节点口径跨文档冲突

**事实**

- SPEC §4.2 在线面写：`40 → 43 → 42 → 50 FinalDecisionSignal → execution_rights → 13 → 16 → 22/11`。
- 48 FULL-CHAIN v1.0-r1 变更记录写："主链口径**修正为** `48→40→43→49→50→执行器`"（第 367 行）。

**问题**

两份架构文档对同一条主干给出不同节点序列：42 与 49 的取舍、48 是否入链。49 是交易框架协议（契约 SSoT），按 SPEC §2.3 自身定位不应作为运行节点；48 是离线实验域，按 SPEC §4.2 自身约束不进入同步热路径。两者都指向"48/49 不是运行节点"，但 48 域文档仍保留旧口径。

**影响**

若不复核，任何按 48 文档实施的消费者会绕过 42 协调层，直接形成 49→50 的隐式耦合，破坏"42 只做汇聚不做判断"和"execution_rights 单出口"两条已批准约束。

**修订要求**

1. 在 SPEC §4.2 显式声明：**49 是契约层，不是运行节点；48 是离线控制面，不在同步链内**；
2. 增加"口径对照表"，列出 48 FULL-CHAIN 旧表述与本次口径的差异，并要求 48 域在下次升版时收敛；
3. 不得在本 SPEC 内直接改写 48 文档（保持领域定义权）。

---

### R-P0-02 闭环能力包无承载物与写入路径

**事实**

- SPEC §8.1 定义能力包字段：`chain_id/version/entry/nodes/contracts/authority/gates/observability/slo/exposure/rollback`。
- 47 registry 实测 schema 为 `1.2-mcp`，校验器仅覆盖 `layer / exposure / source_modules / plugin_ready / layer_quota`（`validate_mcp_registry.py` V1—V7），**无** `chain_id / nodes / authority / gates / rollback` 字段。
- `execution_rights.json` 有 `owner` 字段，但 SPEC 未引用该既有字段。
- SPEC §13 待评审问题 6 自身承认"能力包由哪个现有 Registry 承载"未定。

**问题**

§5.3 要求 `approved` 由"发布权限主体批准"，但该主体未具名；§8.2 要求"Registry 是已批准能力的消费入口"，但该 Registry 不存在。由此形成循环依赖：没有承载物 → 没有审批写入路径 → `approved/published` 状态不可达 → P2-01/P2-02 无法验收。

**修订要求**

1. 明确能力包承载方案，二选一并说明理由：
   - **方案 A**：47 registry 升 `1.3-chain`，新增 `capability_packages` 段与 V8—V11 校验；
   - **方案 B**：新建 `1-ARCHITECTURE/registry/capability_packages.yaml`，由 47 校验器交叉引用；
2. 具名 `approved` 审批主体与签发记录格式（沿用 `principal ∈ {orchestrator, verifier, admin}`）；
3. 引用而非另造 `execution_rights.owner` 字段语义。

---

### R-P0-03 跨链信封与 36 Signal Bus 存在双信封风险

**事实**

- 36 Signal Bus 已实现 `SignalEnvelope`，含 `dedupKey` 幂等键、`SignalType`、`Severity`、`DispatchChannel`（`bus.ts` emit 流程：校验→信封补全→幂等去重→订阅分发→outbox）。
- SPEC §7.2 另定义 `event_id / event_type / schema_version` 必填信封，全文未出现 `dedupKey`、`SignalType`、`DispatchChannel`。
- SPEC P1-02 要求"同一 `event_id` 幂等"，但当前本地 12 条 / 云端 3 条 TrainingEvent 未同步，两端独立生成 ID 必然不幂等。

**问题**

同一业务事件可能同时被 36 信封与跨链信封各分配一个 ID，形成两个去重域，导致：
1. 跨端同步时无法用 `event_id` 判重（正是当前 12/3 不同步的成因）；
2. 订阅方去重失效，产生重复告警或重复训练触发；
3. P1-02 验收条件在架构上不可达。

**修订要求**

1. 明确**唯一去重主键**：建议 `dedupKey` 由跨链 `event_id` 派生（或反向：`event_id = hash(source_module + business_key)`），禁止两套独立生成；
2. 补 `event_type ↔ SignalType` 映射归属声明（由 36 维护映射表，SPEC 只引用）；
3. 补 `DispatchChannel` 与跨链信封的关系（跨链信封只描述业务语义，分发通道仍归 36）；
4. 在 §7.2 增加"与 36 信封的重叠字段对照表"，逐字段说明归属。

---

### R-P0-04 G-BCL 门禁不可机器判定

**事实**

- G-BCL-1："D1 样本可按 `decision_id` 和版本完整回放，单出口无冲突"——未定义样本量、覆盖率阈值、缺失分类。
- G-BCL-3："task/trace/Worker/验收/settle 可关联"——未定义关联率阈值。
- BCL-P1-01 验收："抽样可回放，关联覆盖率和缺失原因可审计"——"抽样"无 n，"覆盖率"无分母口径。
- BCL-P0-03 验收："可用既有事件构造样例"——未给出样例文件路径。

**问题**

四条门禁全部为定性描述，无法由脚本判定，也无法在 CI 中守住。这与 47 已有 `validate_mcp_registry.py` 的机器校验风格不一致，将成为"看起来有门禁"的装饰。

**修订要求**

为每条 G-BCL 增加可判定表达式，至少包括：

| 门禁 | 建议判定式（示例，待评审确认） |
|---|---|
| G-BCL-1 | `关联覆盖率 = 具备 decision_id+fill_id+pnl+training_event_id 的样本数 / 同期决策数 ≥ 0.95`，且 `execution_rights` 冲突计数 = 0 |
| G-BCL-2 | 每条 `published` 能力包均存在 `evidence_ref` 且可解析；不存在状态为 `verified` 但缺独立复核的条目 |
| G-BCL-3 | 抽取 N≥100 个 task，`trace_id` 贯穿率 100%，未贯穿项均带 `degraded_reason` |
| G-BCL-4 | 注册表校验零违规，且不存在 `layer=L2` 且热路径工具、不存在 `live` 暴露 |
| G-BCL-5 | 回滚演练至少 1 次成功，历史证据文件未删除 |

同时给出判定脚本位置或"待建"标注。

---

## 四、重要问题（P1，影响可执行性）

| ID | 问题 | 证据 | 修订要求 |
|---|---|---|---|
| R-P1-01 | 权限矩阵只有允许/禁止，无具名主体与 Mandate 签发者 | SPEC §4.6；47 已有 `principal ∈ {orchestrator,verifier,admin}` | 矩阵增加"主体"列，Mandate 签发者与 46 Ticket 对齐 |
| R-P1-02 | 时间语义缺失 | `occurred_at` 仅"必填"；未区分事件时间/摄入时间、时区、乱序窗口 | 补字段 `occurred_at / ingested_at`、时区约定、乱序容忍窗口 |
| R-P1-03 | 40/43 共享快照无生成者与版本 schema | SPEC §4.3 只写"带版本快照" | 定义快照生产者、存储位置、版本号格式、control 冻结的开关与校验 |
| R-P1-04 | L1 路由 SLO 与 Fail-Closed 分界未落数字 | `l1_route_signal.py` 实为 8 秒超时 + 异常 FAIL-OPEN | §6.1 补 SLO 基线（复用 8s），并明确"13 域不得继承 FAIL-OPEN"的实现点 |
| R-P1-05 | P1-03 依赖的 trace 贯穿当前不成立 | `task-manager.ts` 只有 `taskId`，无 `trace_id` 生成与传播 | 定义 `trace_id` 生成点（前端任务创建）、传播字段、与 46 span 的 DDL 前置条件 |
| R-P1-06 | 25—28 确定性模式被误标为"收敛" | `intent.py` 无 LLM 即返回 `llm_not_available`，无确定性生成实现 | P1-06 改写为"新建确定性经典模式"，补 owner、样例策略模板与验收用例 |
| R-P1-07 | 6-TRADING 缺现状→目标迁移路径 | 现状 `/api/data/query` + `/api/task/stream` 双入口、`USE_SKILL_ORCHESTRATION` 开关 | 补开关名、涉及文件、灰度与回退方式 |
| R-P1-08 | 训练触发审批与 kill-switch 未定义 | §9.2"训练触发 有条件允许" | 补审批主体、预算上限、kill-switch 入口 |
| R-P1-09 | 生命周期缺少转移判据 | §5.3 有状态无判据 | 逐维给出 `candidate→verified` 判据（D1 需 Paper 时长+样本量；D2 需人工盲评；D3 需在线标签/A-B） |
| R-P1-10 | P0—P3 任务无测试映射 | 全部任务表仅"验收"文字 | 每条任务补测试文件/命令/样例路径；P0-03 明确样例文件 |

---

## 五、次要问题（P2）

| ID | 问题 | 建议 |
|---|---|---|
| R-P2-01 | 3+3 映射仍写"23 是矛盾裁决器+唯一最终决策出口（23链）"，易被读回旧口径 | 改为"23 为独立对照链决策出口；NN 链出口为 50" |
| R-P2-02 | 49 SPEC 内部新旧章节冲突（§595 "23 最终裁决" vs 双链增补）未在 49 域登记债务 | 在 49 域 DEBT 或 CHANGELOG 登记，由 49 owner 收敛 |
| R-P2-03 | §11 状态表未标证据时间戳与来源版本，易腐化 | 每行增加"证据来源 + 核验日期"列 |
| R-P2-04 | `chain_id` 命名空间只给 `trading.nn` 一例 | 补全全集：`trading.nn / trading.evolution / trading.strategy / emergence.d1..d3 / execution.general / execution.trading` |

---

## 六、门禁判定（G-BCL-0 ~ 5）

| 门禁 | 本次判定 | 依据 |
|---|---|---|
| G-BCL-0 语义门禁 | ❌ **未通过** | 五种易混链已隔离，但"49 是否运行节点"跨文档歧义（R-P0-01） |
| G-BCL-1 交易证据门禁 | ⏸ 未评 | 依赖 R-P0-04 判定式落地 |
| G-BCL-2 涌现验证门禁 | ⏸ 未评 | 状态机存在但缺转移判据（R-P1-09） |
| G-BCL-3 执行追踪门禁 | ⏸ 未评 | `trace_id` 贯穿当前不成立（R-P1-05） |
| G-BCL-4 对外边界门禁 | ✅ 通过 | 与 47 H1—H8 一致：热路径/live 零暴露、L2 对 L1 只读、L2 写工具三件套齐全 |
| G-BCL-5 回滚门禁 | ⏸ 未评 | 缺回滚演练记录 |

> H1—H8 已逐条核对：H1 热路径 in-process、H2 实盘永不 MCP、H3 壳内零业务逻辑、H4 L2 对 L1 只读、H5 L2 写工具 Mandate+预算+trace、H6 token 计量、H7 不直连 DB、H8 插件化三维递进。SPEC §9 与 3+3 v1.1 表述均与之兼容。

---

## 七、风险登记

| ID | 风险 | 等级 | 缓解 |
|---|---|---|---|
| RV-1 | 按 48 旧口径实施，绕过 42 直连 50 | 高 | R-P0-01 关闭前禁止任何主干接线变更 |
| RV-2 | 双信封导致重复训练触发 | 高 | R-P0-03 关闭前 P1-02 不得开工 |
| RV-3 | 门禁定性化，回归无法拦截 | 中高 | R-P0-04 补齐判定式并接入 CI |
| RV-4 | 25 确定性模式被当作存量收敛，低估工作量 | 中 | R-P1-06 改写为新建并单独排期 |
| RV-5 | 本 SPEC 与 48/49 长期并存造成口径漂移 | 中 | 在 SPEC 加"口径对照与收敛责任人"表 |

---

## 八、复评条件与行动项

**v0.2.0 必须完成（阻断）**

1. R-P0-01：明确 49/48 非运行节点，补口径对照表；
2. R-P0-02：确定能力包承载方案与审批主体；
3. R-P0-03：统一去重主键与 `event_type ↔ SignalType` 映射归属；
4. R-P0-04：为 G-BCL-1/2/3/5 补可判定表达式与判定脚本位置。

**建议同批完成（非阻断）**

5. R-P1-01 / 02 / 09：权限主体、时间语义、生命周期判据；
6. R-P2-01：修正 3+3 中 23 的措辞。

**复评通过后**才可解除对 P1 实施的限制；P2（能力包 + Registry + MCP 投影）仍需 47 域同步升版。

### 8.1 修订响应（SPEC v0.2.0，作者自检，待评审确认）

| 问题 | 修订落点 | 自检结论 | 遗留 |
|---|---|---|---|
| R-P0-01 | SPEC §4.2 节点语义声明；新增 §4.2.1 口径对照与收敛责任 | ✅ 满足 | 48/49 域文档尚未实际收敛，已指派责任人 |
| R-P0-02 | 新增 §8.1.1（方案 B、发布权限具名到域）；落地 `registry/capability_packages.yaml`（6 条，全 draft） | ✅ 满足 | 47 `validate_mcp_registry.py` V8 交叉引用待实现，归 P2-02 前置 |
| R-P0-03 | 新增 §7.2.1（`dedupKey` 单一主键 + `business_key→event_id` 派生 + 字段归属表）、§7.2.2（时间语义） | ✅ 满足 | 36 域 `event_type↔SignalType` 映射表待建 |
| R-P0-04 | §12.1 六条门禁全部改为可判定式，指定 `bcl_gate_check.py`（待建）与 `cross_chain_event.sample.json`（待建） | ✅ 满足 | 判定脚本与 fixture 未落盘；未建成前门禁判为 `not_evaluated` |

> 自检结论：4 项 P0 的**文档层修订要求**均已闭合，未发现新增 P0。是否构成"复评通过"由评审方确认；放行 P1 前仍需判定脚本可用。

### 8.2 P1 修订响应（SPEC v0.3.0）

| 问题 | 修订落点 | 自检结论 | 遗留 |
|---|---|---|---|
| trace 贯穿（BCL-P1-03） | SPEC §12.2.1 | ✅ 规格闭合。**修正评审判断**：`api-client.ts` / `dsh-execution-engine.ts` 已实现 trace 透传，缺口是 `task-manager.ts` 无 `trace_id` 且 L1→L2 未复用同一 trace | 代码未改；需校验"同请求 trace 唯一性" |
| D2 盲评（BCL-P1-04） | SPEC §12.2.2 | ✅ 规格闭合。**修正评审判断**：45 `_validate_blind()` 已存在，缺的是实际执行批次与 `human_review_ref` | 人工盲评不可自动化；无人工则 D2 停留 `candidate` |
| D3 在线标签（BCL-P1-05） | SPEC §12.2.3 | ✅ 规格闭合，但**降级为时序前后对照**：单用户环境无 A/B 统计效力 | 禁止申报"A/B 显著"；标签采集代码未实现 |
| 25—28 确定性模式（BCL-P1-06） | SPEC §12.2.4 | ✅ 规格闭合。**修正评审判断**：`template.py` + `paramopt.py` 已有确定性部件，缺的是无 LLM 入口 `generate_from_template()` | 需登记模板版本与参数 Schema |

> 结论：P1 四项的**设计层**已闭合，四项均未实施。P1 放行后可直接按 §12.2 施工，无需再次设计澄清。

---

## 九、证据索引

| 主题 | 证据 |
|---|---|
| 主干口径冲突 | [48 FULL-CHAIN](./../48-涌现架构/docs/tech/SPEC-EMERGENCE-FULL-CHAIN-v1.0.md) 第 367 行；本 SPEC §4.2 |
| 能力包无承载 | [validate_mcp_registry.py](./../47-MCP管理系统/registry/scripts/validate_mcp_registry.py) V1—V7；[execution_rights.json](./../47-MCP管理系统/registry/execution_rights.json) |
| 双信封风险 | [36 bus.ts](./../36-通信系统层/src/bus.ts) emit 流程；本 SPEC §7.2 |
| MCP 硬约束 | [47 L1L2-MCP-PACKAGING](./../47-MCP管理系统/docs/tech/SPEC-L1L2-MCP-PACKAGING-v0.1.md) H1—H8 |
| L1 路由与 settle | [l1_route_signal.py](./../3.1-FRONTEND/scripts/l1_route_signal.py) |
| trace 缺失 | [task-manager.ts](./../3.1-FRONTEND/src/lib/task-manager.ts) |
| 25 LLM 依赖 | [intent.py](./../25-用户策略生成系统/strategy_gen/intent.py) |
| TrainingEvent 未同步 | [48 FULL-CHAIN](./../48-涌现架构/docs/tech/SPEC-EMERGENCE-FULL-CHAIN-v1.0.md) 第 183/224/264 行 |
| 双链与执行权 | [49 SPEC](./../49-交易框架协议/SPEC.md) 第 87/368/536/595 行 |
