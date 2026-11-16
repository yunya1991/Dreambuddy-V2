# 评审报告 — SPEC-56-H L2 Harness 能力增强（HCP）v0.1

> **评审日期**: 2026-11-17
> **评审对象**: [SPEC-56-Harness能力增强-v0.1.md](../SPEC-56-Harness能力增强-v0.1.md)
> **修订版**: [SPEC-56-Harness能力增强-v0.3.md](../SPEC-56-Harness能力增强-v0.3.md)（作者已按 M1–M4 修订；v0.3 另修复复审 R1–R13；§十 为对照）
> **评审方式**: 四视角独立评审 + Devil's Advocate 让步阈值 + 7 模式阻断清单
> **输入证据**:
> - 母契约 [SPEC-56-L2架构能力聚合层.md](../SPEC-56-L2架构能力聚合层.md)（IF-1/IF-3/IF-4/IF-5/IF-7）
> - 可执行契约 [span.schema.json](../contracts/span.schema.json) / [tool_set.schema.json](../contracts/tool_set.schema.json) / [repair_ledger.schema.json](../contracts/repair_ledger.schema.json) / [stop_reason.schema.json](../contracts/stop_reason.schema.json)
> - 能力登记 [TECHNICAL_DESIGN.md](./TECHNICAL_DESIGN.md) v1.16
> - Trae 证据 [RESEARCH-20261117-Trae逆向解析与交互学习-v0.1.md](./RESEARCH-20261117-Trae逆向解析与交互学习-v0.1.md) v0.1.4
> - 47 注册表 [mcp_capabilities.yaml](../../47-MCP管理系统/registry/mcp_capabilities.yaml)

---

## 一、评审摘要

| 项 | 结论 |
|---|---|
| 整体评价 | **修改后接受**（Conditional Accept） |
| Major（必须修改） | **4 条** |
| Minor（建议修改） | **6 条** |
| 是否可进入实现 | **否**；Major 关闭前只允许做 schema 对齐与影子采集 |
| 最小可行范围 | **P0 收缩为 H3 + H5**；H1/H2/H4 待代码复核后再排期 |
| 核心判断 | 方向正确，但当前 SPEC 的契约字段与现有 schema 不兼容，且两个门禁不可机器判定 |

**一句话结论**：HCP 的「可归因 + 证据门禁」值得做；但必须先修 schema 兼容、门禁可判定性和单案例外推三个问题，否则会把一个正确的方向做成一套无法落地的契约。

---

## 二、架构契合评审

### 2.1 符合部分

1. HCP 被定义为 L2-K/L2-E 的横切面，而不是第六个子层，符合 3+3 架构与「不新增业务能力」的约束。
2. H1–H5 全部锚定现有 IF-1/IF-3/IF-4/IF-5/IF-7，没有新开第二套契约，方向正确。
3. 非目标明确：不改 Trae、不复刻 profile、不读凭据、不破解加密库。
4. 优先级把 H3（归因）放在 H1（能力 bundle）之前，符合「先可归因，再学习」的证据链。

### 2.2 主要问题

**A1（Major）H1 混淆了「产品 agent_type」与「47 worker_role_id」。**
Trae 的 `agent_type` 是产品级任务原型（trae/code/design/work），47 的 `worker_roles` 是执行角色（research/engineer/data_reader/verifier/executor/l2_analysis/l2_trading_analysis/lobehub_frontend/l1_observer/l2_researcher/l2_planner/l1_ops）。SPEC 用 `<47 worker_role_id>` 填 `agent_type`，会导致：
- bundle 选择语义不清：是按任务原型选技能，还是按执行角色选工具？
- 无法回答「同一个 engineer 角色在不同任务原型下是否应有不同 skills」。

**建议**：H1 拆成 `agent_profile_id`（任务原型）与 `worker_role_id`（执行角色）两个字段；bundle 选择顺序为 `profile → role → model`，并在 47 注册表中分别登记。

**A2（Major）H4 是 P2，但 G-L2-15 已作为门禁列出。**
门禁没有「激活阶段」概念，读者会以为 P0 就要满足 H4。建议每个门禁增加 `activation: off|shadow|enforce` 与 `since_phase`，P0 只允许 G-L2-14/G-L2-16 进入 shadow。

**A3（Minor）H1/H2/H4 仍按「Trae 有 → 我们也必须有」的类比推进。**
Trae 的 M1 是 manifest 声明，未证明运行时按模型裁剪；M4 是其自身 git 快照，不等于我们的 Ticket 恢复语义。建议在每条机制卡上标 `source_level=observation|declaration|analogy`，并把 H1/H4 标为「设计假设，待第二个案例或代码复核」。

---

## 三、工程/契约评审（最关键）

### 3.1 H3 与 `span.schema.json` 不兼容（Major）

现有 `span.schema.json` 的必填字段是：

```
schema_version, trace_id, run_id, span_id, name, segment,
started_at, ended_at, model_id, tokens_in, tokens_out, cost_cu, context_hash
```

且 `additionalProperties: false`。SPEC §4.3 的 H3 示例使用：

```json
"tokens": {"input": 0, "output": 0}
```

并新增 `session_id / tool_call_id / interaction_case_id`，但**没有升 `schema_version`**。按现有 schema，这个 payload 会因 `additionalProperties` 与缺少 `tokens_in/tokens_out/cost_cu` 直接校验失败。

**必须修改**：
- 保留 `tokens_in/tokens_out/cost_cu`，不要改成嵌套 `tokens`；
- 新增字段必须升 `schema_version`（例如 `1.1`），并明确旧宿主兼容策略；
- 若 `session_id` 设为必填，必须列出 P0 三个宿主的改造顺序与默认值。

### 3.2 H2 与 `tool_set.schema.json` 不兼容（Major）

现有 `tool_set.schema.json` 必填：

```
schema_version, run_id, generated_at, source, policy, tools
```

且 `tools[]` 每项必填：

```
name, shell, layer, exposure, effect, requires_mandate, visibility, approval
```

SPEC §4.2 的 H2 示例使用 `tool_set_id / session_id / mode / version / hash / diff / approval_source`，并省略了 `schema_version/run_id/generated_at/source/policy`；这会直接失败。

**必须修改**：
- 在现有 schema 上**增量扩展**，保留原有必填字段；
- 新增 `tool_set_id / session_id / version / hash / diff` 时升 `schema_version`；
- `tools[]` 继续使用 `name/shell/layer/exposure/effect/requires_mandate/visibility/approval`，不要另起一套。

### 3.3 `approval_source: same_snapshot` 不可验证（Major）

`same_snapshot` 是一个常量字符串，不是证据。它无法阻止「3.1 与 52 各自建白名单」——因为两端都可以声称自己是 same_snapshot。

**必须修改**：
- 审批记录必须引用 `tool_set_hash`（或 `snapshot_id`）；
- `Mandate` 判定时必须校验 `mandate.tool_set_hash == 当前快照 hash`；
- G-L2-13 的判据改为「审批记录与快照 hash 一致」，而不是「字段等于 same_snapshot」。

### 3.4 H5 的 evidence level 可自证（Major）

SPEC 允许案例自带 `"level": "observation"`，但没有定义「谁有权赋值、如何防止模型自封 observation」。这会让 H5 变成「模型自己说自己是 observation」的门禁，无法阻止 inference 污染。

**必须修改**：
- `level` 不由案例作者填写，由校验器根据 `refs` 推导：至少 1 条 `span`/`checkpoint` 引用且 hash 可验证 → observation；否则 inference；
- `refs` 必须是结构化引用（`span:<span_id>`、`checkpoint:<checkpoint_id>`、`file:<path>#<hash>`），不能是自由文本；
- 纯 inference 案例允许留存，但 `admissible=false`。

### 3.5 `RepairLedger` 没有 `case_ref`（Major）

`repair_ledger.schema.json` 的 `additionalProperties` 未显式允许 `case_ref`，且 `settled` 节点没有该字段。SPEC 要求 settled 必须引用 `case_ref`，需要 schema v1.2 + 迁移策略；否则现有台账会校验失败。

**必须修改**：
- 新增 `case_ref` 到 `settled`，升 `schema_version=1.2`；
- 对已存在的 v1.1 台账给出迁移/兼容规则（缺 `case_ref` 的历史 settled 不回溯，新增必须填）；
- `validate_contracts.py` 增加负例：settled 无 case_ref → fail。

### 3.6 其他工程问题（Minor）

- **工具配额**：47 的 `max_tools_per_shell=15`，H2 没有配额校验；Trae 的 16–37 不能直接搬。H2 必须加 `len(tools) ≤ max_tools_per_shell`。
- **stop_reason 语义**：`stop_reason.schema.json` 有 `resumable` 字段；H4 又用「无 checkpoint 不得 resumable」，需要明确 H4 校验的是 stop_reason 的 `resumable`，避免两套语义。
- **门禁激活**：G-L2-12..16 没有 `activation/since_phase`；P0 不应要求 H1/H4。
- **owner/rollback**：SPEC 没有 RACI、feature flag、kill switch、回滚方案；至少补「谁负责 H3 字段、失败如何关回 shadow」。
- **主 SPEC 同步**：新增 G-L2-12..16 后，需要更新 SPEC-56 §5 与 `validate_contracts.py` 的自检计数，否则门禁只存在于子 SPEC。

---

## 四、证据/统计评审

### 4.1 证据分级基本合格

- Trae 的 5 个机制有路径与数字，标了 observation/derivation。
- 明确写出「627 条案例全为 inference」「R2 门禁 0%」。
- 明确写出「不复制 Trae、不读凭据、不破解」。

### 4.2 统计问题（Major）

**S1（Major）50 会话样本不足以证明「join_rate ≥95%」。**
若 50 个全命中，Wilson 95% 置信下限约 **92.9%**；要证明 ≥95%，至少需要约 **73 个全命中样本**（或更大样本 + 置信区间）。当前写法把「点估计 ≥95%」当成「证明 ≥95%」，证据强度不足。

**建议**：
- P0 用「固定 50 会话、100% 全命中」作为准入，而不是 95%；
- 生产门禁改为「n≥73 且 Wilson 95% 下限 ≥95%」或「n≥100，点估计 ≥95% 且下限 ≥90%」；
- 明确 join 的分子/分母：是按案例、按 span、还是按会话；是否允许 `session_id + 时间窗` 的弱关联。

**S2（Major）H5 会导致训练数据源为零。**
如果 627 条案例全是 inference，H5 的「inference 不得进训练/优化」会把当前唯一数据源全部拒掉。这不是错，但需要分层，否则 H5 上线即「空转」。

**建议**：三级准入：
- A 级（observation + 交叉证据）：可用于优化结论/训练；
- B 级（inference + 人工确认/复现）：可用于假设生成；
- C 级（inference-only）：只用于检索/回忆，不得用于优化结论。

### 4.3 单案例外推（Minor）

H1/H2/H4 来自一个产品的一个版本；SPEC 没有写「复制条件」。建议在 §1.3 增加一句：**"任一机制要在第二个产品/版本复现后，才从 analogy 升为 pattern"**。

---

## 五、Devil's Advocate

| # | 反驳 | 评分 | 让步判定 |
|---|---|---|---|
| DA-1 | **这是「拿着锤子找钉子」**：H1/H2/H4 是从 Trae 反推的，未必是我们的真问题；A1-2/A1-3 已覆盖 tool_set/记忆，可能重复建设。 | **4** | 必须让步：先把 P0 收缩为 H3+H5；H1/H2/H4 先做代码复核，确认缺口再排期。 |
| DA-2 | **95% 是拍脑袋阈值**：50 样本、无置信区间、join 定义不清，容易被「按 session 弱关联」刷高。 | **4** | 必须让步：定义 join key、分子/分母、样本量与置信区间；P0 用 100% 全命中。 |
| DA-3 | **H5 会把学习饿死**：所有摘要都是 inference，门禁一开就没有可用案例。 | **4** | 必须让步：改为 A/B/C 三级准入，C 级仍可检索。 |
| DA-4 | **门禁膨胀**：H4 还是 P2，却先立 G-L2-15；实现前就有 5 个新门禁，维护成本高。 | **3** | 可坚持，但必须加 `activation/since_phase`，P0 只启用两道。 |
| DA-5 | **trace 体积/PII**：100% 采集所有 span 会放大存储与隐私风险。 | **3** | 可坚持，但需采样策略与字段白名单；P0 验证期 100%，之后 10% + 失败全采。 |

**让步结论**：DA-1/2/3 均为 4 分，作者必须修改；DA-4/5 为 3 分，可通过补充机制坚持。

---

## 六、7 模式阻断清单

| 模式 | 判定 | 说明 |
|---|---|---|
| 1. 幻觉引用 | 🟡 部分通过 | 路径与数字可验证；但 H1 的「运行时按模型裁剪」是 declaration，不是 observation，需改措辞 |
| 2. 数据造假 | ✅ 通过 | 数字来自本地产物；需注明随运行变化 |
| 3. 方法捏造 | 🟡 部分通过 | H4 checkpoint 是设计假设，未在我方验证；标 hypothesis |
| 4. 框架锁定 | ❌ 不通过 | 仅一个产品案例；H1/H2/H4 需要第二案例或代码复核 |
| 5. 结果幻觉 | ✅ 通过 | 没有性能/收益声明，明确「不证明」 |
| 6. 逻辑跳跃 | 🟡 部分通过 | 「Trae 有 → 我们需要」是类比；已有 contract_ref，但仍需缺口复核 |
| 7. 边界忽略 | 🟡 部分通过 | 非目标/局限写得清楚；门禁仍把单案例当通用，需加复制条件 |

---

## 七、Major / Minor 清单

### Major（必须修改）

| ID | 问题 | 证据 | 修改 |
|---|---|---|---|
| **M1** | H3 与 `span.schema.json` 字段不兼容（`tokens` vs `tokens_in/out/cost_cu`；新增字段未升版本） | [span.schema.json](../contracts/span.schema.json) | 保留原字段；新增字段升 `schema_version`；列 P0 宿主顺序 |
| **M2** | H2 与 `tool_set.schema.json` 必填字段不兼容（缺 `schema_version/run_id/generated_at/source/policy`） | [tool_set.schema.json](../contracts/tool_set.schema.json) | 增量扩展；保留 `tools[]` 原字段；升版本 |
| **M3** | `approval_source: same_snapshot` 不可验证，G-L2-13 拦不住双白名单 | SPEC §4.2 / G-L2-13 | 审批引用 `tool_set_hash`；Mandate 校验 hash 一致 |
| **M4** | H5 `level` 可自证；`RepairLedger` 无 `case_ref` | SPEC §4.5；[repair_ledger.schema.json](../contracts/repair_ledger.schema.json) | level 由 refs 推导；台账 v1.2 + 迁移 |

### Minor（建议修改）

| ID | 问题 | 修改 |
|---|---|---|
| m1 | H1 混淆 `agent_type` 与 `worker_role_id` | 拆 `agent_profile_id` / `worker_role_id`，定义选择顺序 |
| m2 | 50 样本不足以证明 95% | P0 用 100% 全命中；生产用 n≥73 + Wilson 下限 |
| m3 | H5 一刀切导致训练数据为零 | A/B/C 三级准入 |
| m4 | 门禁无激活阶段 | 增加 `activation: off/shadow/enforce` 与 `since_phase` |
| m5 | 无 owner/rollback/feature flag | 补 RACI、kill switch、回滚方案 |
| m6 | 未同步主 SPEC §5 与校验器 | 增加 H-D0：更新 G-L2-12..16 与自检计数 |

---

## 八、修改建议（按顺序）

1. **先做契约对齐（M1/M2）**：只改 schema 与示例，不改行为；跑 `validate_contracts.py --self-test`。
2. **再补可验证性（M3/M4）**：`tool_set_hash` 入 Mandate；`level` 由 refs 推导；台账 v1.2。
3. **收缩 P0**：P0 = H3 + H5；H1/H2/H4 移到 P1/P2，先做代码复核（A1-2/A1-3/GAP-25/30）。
4. **补统计口径**：join 的 key、分子/分母、样本量、置信区间；P0 用 100%。
5. **补工程治理**：owner、feature flag、kill switch、回滚、门禁激活阶段。
6. **复审**：修改后重新跑本清单；M1–M4 全关闭才可进入 Plan/实现。

---

## 九、复审门槛

| 门槛 | 判据 |
|---|---|
| G-R1 | M1/M2 的 schema 示例能通过 `validate_contracts.py` |
| G-R2 | G-L2-13 有「审批 hash = 快照 hash」负例，且能 fail |
| G-R3 | H5 的 `level` 由 refs 推导；纯 inference 负例 fail；台账 v1.2 兼容 |
| G-R4 | P0 只含 H3/H5；H1/H2/H4 有代码复核结论 |
| G-R5 | join 口径、样本量、置信区间写清；P0 100% 全命中 |
| G-R6 | 7 模式清单中「框架锁定」从 ❌ 转为 ✅ 或有明确复制条件 |

---

## 十、评审结论

**修改后接受。** 方向（可归因 + 证据门禁）成立，但当前版本存在 4 个必须修的契约/门禁问题；在 M1–M4 关闭前，不应进入实现。建议按「契约对齐 → 可验证性 → 收缩 P0 → 统计口径 → 工程治理」的顺序修订，然后复审。

## 十一、v0.2 修订对照（待复审）

| 评审项 | v0.2 位置 | 修订 | 状态 |
|---|---|---|---|
| M1 | §4.3 | 保留 `tokens_in/tokens_out/cost_cu`；影子用 `attrs.hcp`；P1 升 span v1.1 | ✅ 已修 |
| M2 | §4.2 | 保留 v1.0 必填字段；sidecar → v1.1；`tools[]` 原字段不变 | ✅ 已修 |
| M3 | §4.2 / §5 | `approval_ref.tool_set_hash`；Mandate 校验 hash 一致 | ✅ 已修 |
| M4 | §4.5 | `derived_level` 由 refs 推导；A/B/C 分级；ledger v1.2 + case_ref | ✅ 已修 |
| m1 | §4.1 | 拆 `agent_profile_id` / `worker_role_id` | ✅ 已修 |
| m2 | §2.2 / §5.1 | P0 50 会话 100%；生产 n≥100 + Wilson；73 全命中说明 | ✅ 已修 |
| m3 | §4.5 | A/B/C 三级准入 | ✅ 已修 |
| m4 | §5 | `activation/since_phase` | ✅ 已修 |
| m5 | §6.3 / §6.4 | RACI + feature flags + 回滚 | ✅ 已修 |
| m6 | §6.2 | H-D0 更新主 SPEC/校验器 | ✅ 已修 |
| DA-1 | §6.1 | P0 收缩为 H3+H5；H1/H2/H4 后移 | ✅ 已让步 |
| DA-2 | §5.1 | 明确 join 分子/分母/样本量/置信区间 | ✅ 已让步 |
| DA-3 | §4.5 | A/B/C 分层，C 级仍可检索 | ✅ 已让步 |

**修订结论**：M1–M4 与 m1–m6 均已体现在 v0.2；但这是作者修订，不是复审通过。下一步必须重新核对 G-R1–G-R6，特别是：
- 50 会话 100% 强关联是否可达；
- 34/52/3.1 的 shadow 改造是否能在 P0 内闭环；
- ledger v1.2 的历史兼容是否真的不破坏现有 settled 记录。

**当前状态**：待复审，未进入实现。

---

> 本报告只评审设计，不评审尚未产生的实现结果；所有结论均以当前契约文件与 Trae 证据为限。

---

## 十二、复审记录（v0.2）

> **复审日期**: 2026-11-17
> **复审对象**: [SPEC-56-Harness能力增强-v0.3.md](../SPEC-56-Harness能力增强-v0.3.md)（v0.2 内容已并入；R1–R13 修复见其 §10.1）
> **复审方式**: 对 §十一 的修订逐项复核 + 契约形状预检（preflight）
> **结论**: **设计层通过（Conditional Pass），可进入 Plan；实现层未通过**（G-R1–G-R3 尚无代码/测试，G-R4 部分满足）

### 12.1 预检证据

用现有 `span.schema.json` v1.0 与 `tool_set.schema.json` v1.0 对 v0.2 示例做形状校验（hash 用 64 个 0 占位）：

| 预检 | 结果 |
|---|---|
| H3 影子 payload（`attrs.hcp.*` + `tokens_in/out/cost_cu`）vs span v1.0 | **PASS** |
| H2 v1.0 子集 vs tool_set v1.0 | **PASS** |
| H2 v1.1 保留 v1.0 必填字段与 `tools[]` 必填字段 | **True** |
| v1.1/v1.2 新 schema 文件是否存在 | **否**（H-D1 未做） |

结论：M1/M2 的**形状兼容**成立；但 v1.1/v1.2 schema 尚未落地，不能宣称 `validate_contracts.py` 已通过。

### 12.2 G-R1–G-R6 复核

| 门槛 | 结果 | 证据/缺口 |
|---|---|---|
| **G-R1** M1/M2 schema 示例通过校验 | 🟡 **设计层通过，实现层 blocked** | 预检 3/3 通过；但 `span`/`tool_set` v1.1 文件未建，v1.1 示例无法由现有校验器验证 |
| **G-R2** G-L2-13 有 hash 不一致负例 | 🟡 **设计层通过，实现层 blocked** | §4.2/§5 已定义 `mandate.tool_set_hash == 快照 hash`；无实际负例测试 |
| **G-R3** H5 level 由 refs 推导；ledger v1.2 兼容 | 🟡 **设计层通过，实现层 blocked** | §4.5 已定义推导规则/A-B-C/legacy；无 validator 与 v1.2 schema |
| **G-R4** P0 只含 H3/H5；H1/H2/H4 有代码复核 | 🟡 **部分满足** | P0 收缩已落地（§6.1）；H1/H2/H4 的代码复核结论尚未产出 |
| **G-R5** join 口径/样本量/置信区间 | ✅ **通过** | §5.1 明确单位/分子/分母/强弱关联；P0 50 会话 100%；生产 n≥100 + Wilson；73 全命中说明 |
| **G-R6** 框架锁定转为 ✅ 或有复制条件 | ✅ **通过** | §1.3 增加“单案例边界”，要求第二案例/版本或代码复核后才升级 |

### 12.3 残余问题（Minor）

| ID | 问题 | 建议 |
|---|---|---|
| R-01 | v0.2 示例 hash 统一用 64 个 0 占位 | 已加注；实现时校验器必须拒绝全 0 |
| R-02 | H1 `agent_profile_id` 的 `developer|reviewer|...` 仍是示例值 | 改为 `<profile_id>` 或 47/34 注册表实际枚举 |
| R-03 | H5 `human_confirmation` 只给了 `{by,at,ref}` 形状，未定义 schema | H-D1 补 `human_confirmation.schema.json` 或在 case schema 内约束 |
| R-04 | H2 `diff` 的 `added/removed/changed` 元素形状未定义 | H-D1 定义 `tool_ref` 结构（至少 `name/shell/effect`） |
| R-05 | G-L2-14 的 50 会话样本如何选取未写 | 写明“固定列表/最近 N 个/随机种子”，确保可复跑 |

### 12.4 复审结论

- **设计层**：通过。M1–M4 的修订方向、契约形状、门禁可判定性均成立；P0 收缩与统计口径符合评审要求。
- **实现层**：未通过。G-R1–G-R3 目前只有设计规则，没有可执行 schema/validator/负例；G-R4 的 H1/H2/H4 代码复核尚未完成。
- **放行范围**：可进入 **Plan（H3+H5）**；不得宣称“实现完成/门禁通过”。
- **进入实现前必须**：H-D0（主 SPEC 门禁表 + 校验器）与 H-D1（v1.1/v1.2 schema）先行；H1/H2/H4 的代码复核在 P1 前补齐。
- **建议**：先做 H3 影子字段 + H5 validator 的最小闭环，用 50 会话 100% 强关联做第一份证据包，再决定是否扩到 52/3.1。
