# SPEC-57 — Agent 提示词工程（调研稿）

> **版本**: v0.4（P0 已落地 + P1 前置 A/B 多轮回测已出结论；未评审）
> **日期**: 2026-11-18
> **状态**: 🟡 调研 —— 只冻结「问题、结构、契约草案、裁决、路线」，不产生任何运行时改动
> **归属层**: L2（横切 L2 五子层）
> **上游 SSoT**:
> - 架构唯一事实源：[SYSTEM_ARCHITECTURE_OVERVIEW.md](../1-ARCHITECTURE/SYSTEM_ARCHITECTURE_OVERVIEW.md) v4.2
> - 模块归层口径：[3+3架构模块映射.md](../1-ARCHITECTURE/3+3架构模块映射.md) v1.3
> - L2 契约入口：[SPEC-56-L2架构能力聚合层.md](../56-L2架构能力聚合层/SPEC-56-L2架构能力聚合层.md) v0.9（ADR-01~11 / G-L2-1~11 / IF-1~7）
> - 层级暴露与配额：[SPEC-L1L2-MCP-PACKAGING-v0.1.md](../47-MCP管理系统/docs/tech/SPEC-L1L2-MCP-PACKAGING-v0.1.md)（H1–H8 / layer_quota）
> - 交易域协议：[49-交易框架协议/SPEC.md](../49-交易框架协议/SPEC.md) v0.14.2（双决策链）
> **配套文档**: [PROMPT_CONSTITUTION.md](./PROMPT_CONSTITUTION.md)（源文件宪法 constitution@1.0.0）· [RESEARCH-20261118 业界对标](./docs/RESEARCH-20261118-提示词工程业界对标.md)
> **不做什么**: 不新建生成式能力、不改 56 既有契约语义、不重写各模块自身 prompt 的业务内容、不做自动 prompt 热更新。

---

## §0 摘要

1. **问题不是写法，是承载层**。全仓存在至少 6 处 prompt 资产（32 辩论 / 1-ARCH 意图识别 / 3.1 前端 / 6-TRADING 触发词 / 33 REA / 9 基本面），但 `prompt_version` / `prompt_id` / `prompt_hash` 在 `56-`、`34-*/core`、`47-` 三个治理域**全部零命中**。
2. **56 已经提出要求，但没有落地物**。56 §5 治理表明文要求「记录 `model` + 参数摘要 + **prompt 版本**」，ADR-03 要求每个 L2 出口返回统一信封 —— 两者之间缺一个可被版本化的对象。
3. **红线只存在于契约，不存在于上下文**。`L2 对 L1 只读`（ADR-01）、`实盘永不 MCP`（H2）、`写操作 Mandate`（ADR-04）、`禁「将会/预计/必然」`（IF-3 约束 4）——模型看不到，因此无法遵守。
4. **本 SPEC 交付两件东西**：① **六层提示词架构**（P0 宪法 / P1 角色 / P2 任务 / P3 上下文 / P4 输出契约 / P5 工具，对齐 L2 五子层）；② **源文件宪法**（H0–H5 优先级 + 12 条不可违背条款 + 12 个源文件登记）。
5. **治理形态借鉴业界**：不可变注册表 + 语义化版本 + 评测门禁晋升 + 指纹对账（见 RESEARCH §5），但**拒绝**自动优化/热更新与自由探索式取证（冲突项见 RESEARCH §7）。
6. **P0 不改一句现有 prompt**：只做登记、schema、宪法发布与只读校验，先获取可观测性。
7. **六项待决已裁决**（§10）：宪法与 prompt 版本解耦、前端 prompt 纳入、golden set 复用 45、prompt 改进归 48 D2、校验器合入 56 `validate_contracts.py`、不建 `l2.constitution.mcp`。裁决原则是「单一事实源 + 入口唯一 + 工具面不虚增」。

---

## §1 定位与非目标

### 1.1 定位

SPEC-57 是 **L2 生成式调用的上下文契约入口**：回答「一次 L2 调用应该带哪些上下文、按什么优先级、由谁版本化、怎么判定违规」。

| 维度 | 56-L2 能力聚合层 | 57-Agent 提示词工程 |
|---|---|---|
| 管什么 | 能力边界、子层调用、信封、Mandate、验收 | 上下文内容、优先级、版本、评测、注入安全 |
| 不管什么 | prompt 文本与版本 | 工具面配额、路由裁决、业务能力定义 |
| 交付物 | 11 ADR + 11 门禁 + 7 接口 | 六层架构 + 注册表 + 8 门禁 + 1 宪法 |
| 关系 | 57 是 56 的**上下文侧实现规范**，不修改 56 任何 ADR | — |

**一句话**：56 定义「L2 能做什么」，57 定义「L2 被允许知道什么、以什么口吻、带什么证据、用哪一版」。

### 1.2 非目标

1. 不新建业务能力，不新增 LLM 调用点。
2. 不改 L0/L1 的任何 prompt（L1 零 token，无生成式提示词）。
3. 不接管 32/34/48 各自的业务 prompt 内容，只接管其**版本与约束**。
4. 不做 prompt 自动调优上线（若做，必须走 48 实验 → 45 门禁 → 人工晋升）。
5. 不把提示词注册表做成第二个 MCP 注册表：两表正交，prompt 表只引用 shell id 与 `tool_set` 指纹。

---

## §2 现状与缺口（可验证）

### 2.1 资产盘点

| 资产 | 位置 | 规模 | 现状问题 |
|---|---|---|---|
| 辩论立场锁 | [32-对抗性辩论Bot/core/prompts.py](../32-对抗性辩论Bot/core/prompts.py) | 138 行 | 设计好（立场禁止让步 + JSON 强约束），但无版本/无评测/无指纹 |
| 意图识别基线 | [1-ARCHITECTURE/intent-recognition-spec/system_prompt.md](../1-ARCHITECTURE/intent-recognition-spec/system_prompt.md) | 494 行 | 自标 v1.1，无注册；自带「intent-taxonomy 链接失效」 |
| 前端技能提示 | [3.1-FRONTEND/src/lib/orchestration/node-prompts.ts](../3.1-FRONTEND/src/lib/orchestration/node-prompts.ts) | 211 行 | BASE + 5 阶段，与后端人格/免责口径不一致 |
| 交易触发词 | [6-TRADING/docs/TRIGGER_PROMPTS.md](../6-TRADING/docs/TRIGGER_PROMPTS.md) | 362 行 | 应用层文案与 L2 生成 prompt 混居 |
| REA 解析 | [33-REA逆向解析工程/prompts/investigation_prompt.md](../33-REA逆向解析工程/prompts/investigation_prompt.md) | 单文件 | L0 内的 LLM 辅助，未纳入 L2 计量 |
| 基本面 ops | [9-基本面分析/ops/nanoclaw/prompts/](../9-基本面分析/ops/nanoclaw/prompts/) | 目录 | 同上 |

### 2.2 缺口登记

| # | 缺口 | 证据 | 影响 | 优先级 |
|---|---|---|---|---|
| GAP-P-01 | 无版本可溯 | 三域检索 `prompt_version|prompt_id|prompt_hash` = 0 命中 | 同结论无法回答「用的哪版」；采样不可复现 | **P0** |
| GAP-P-02 | 无评测门禁 | 6 处资产均无 golden set / 回归脚本 | prompt 改动即上线，退化不可发现 | **P0** |
| GAP-P-03 | 纪律未入 prompt | 56 IF-3 禁令与 G-L2-5 证据分级只在契约，6 处 prompt 均未承载 | 模型不知红线 | **P0** |
| GAP-P-04 | 架构事实缺席 | L2 只读 L1 / 实盘隔离 / Mandate / 热路径 in-process 均不在任何上下文 | 越权表达无法被 prompt 层拦截 | **P0** |
| GAP-P-05 | 人格不一致 | 32（立场锁）、3.1（口语 Markdown）、1-ARCH（Function Calling）三套风格 | 同用户不同入口口径不同 | P1 |
| GAP-P-06 | 工具面与提示词不同源 | 56 IF-7 `tool_set` 快照已冻结，但无 prompt 侧声明 | 模型可能看到已下线/未授权工具 | P1 |
| GAP-P-07 | 注入面敞开 | H5 类内容（MCP 返回、网页、文件）无隔离约定 | 间接提示注入可改目标 | P1 |
| GAP-P-08 | 前端 prompt 未纳入 | 3.1 `llm-prompt-training-loop.ts` 与 node-prompts 独立演进 | 训练回路自我强化漂移 | P2 |
| GAP-P-09 | 与 48 无闭环 | prompt 改进无度量、无实验编号 | 「优化了 prompt」无法证伪 | P2 |

---

## §3 六层提示词架构（P0–P5）

### 3.1 分层与 L2 子层映射

```
P0 宪法层    PROMPT_CONSTITUTION（H0–H5 + C-01..C-12）        恒定，最高优先
P1 角色层    L2-K 规划者 / L2-E Worker / L2-G 生成者 / L2-P 适配 / L2-A 应用
P2 任务层    修复 / 优化 / 研究 / 辩论 / 策略生成 / 协议适配（一任务一模板）
P3 上下文层  L0 事实 + L1 只读证据 + 24 图压缩（带锚点）+ 源文件引用
P4 输出契约  JSON Schema / evidence 分级 / 尾注纪律 / 引用格式
P5 工具层    与 56 IF-7 tool_set 快照同源，禁止自建白名单
```

| P 层 | 对标业界 | 对应 56 契约 | token 上限（建议） |
|---|---|---|---|
| P0 宪法 | Claude's Constitution / Instruction Hierarchy | 本文 §4 | ≤ 1200 |
| P1 角色 | Codex 系统提示分段（人格 / 工具 / 安全） | §2.3 子层职责 | ≤ 600 |
| P2 任务 | Gemini 提示分解 | §2.5 开发端闭环 / G 组能力 | ≤ 800 |
| P3 上下文 | Gemini grounding / GPT-5 `context_gathering` | IF-1 路由交接 + ADR-02 单一事实源 | 由预算反推 |
| P4 输出 | Gemini 结构化输出 | IF-3 L2Envelope / IF-7 四契约 | ≤ 300 |
| P5 工具 | MCP `tool.annotations` | IF-7 `tool_set` / G-L2-11 | 快照驱动 |

**总预算**：默认 `max_context_tokens = 4000`（P0+P1+P2+P4 固定段 ≤ 2900，余量给 P3）；超限必须降级（C-10），不得静默裁剪证据。

### 3.2 角色层规范（P1）

| 角色 id | 对应子层 | 允许 | 禁止 | 典型消费方 |
|---|---|---|---|---|
| `l2.planner` | L2-K | 规划、拆解、验收标准生成 | 自称已验收、直接执行 | DreamOS `sacg_orchestrator` |
| `l2.worker` | L2-E | 按 Ticket 执行只读工具、报告进度 | 持有写工具、越权改 Mandate | 34-core Router/Worker |
| `l2.debater` | L2-G | 立场锁定论证（沿用 32 实践）、JSON 强约束 | 中立化、跨立场让步 | `l2.debate.mcp` |
| `l2.trainer` | L2-G | 提出训练建议、解释度量 | 自动发版、绕过 40/50 门禁 | `l2.train.mcp` |
| `l2.emergence` | L2-G | D1/D2/D3 假设陈述与判据引用 | 把度量当结论 | `l2.emergence.mcp` |
| `l2.adapter` | L2-P | 协议翻译、能力卡生成 | 承载业务判断 | 52 / 53 |
| `l2.app` | L2-A | 面向用户的表达与引导 | 承诺收益、替代风控 | 3.1 / 6 |

**统一人格约束**（解决 GAP-P-05）：中文、紧凑、结论先行、不用营销语；不确定必须明说；任何数字必须可回溯；免责尾注统一为「历史统计/模型推断，不代表未来」。

### 3.3 任务层规范（P2）

一任务一模板，禁止万能模板。首批 6 个：

| task_id | 目标 | 必需输入 | 输出契约 |
|---|---|---|---|
| `fix.bug` | 复现→根因→修复 | 症状、复现命令、基线失败证据 | 变更引用 + 回归命令 |
| `opt.improve` | 对照优化 | 发现来源（L1/缺陷）、同测试集前后 | 指标 before/after + n + 显著性 |
| `research.topic` | 结构化调研 | 范围、源文件清单 | 结论 + 证据级别 + 待决 |
| `debate.topic` | 正反对抗 | 话题、立场分配 | 双方 JSON + 裁判 JSON |
| `strategy.generate` | 策略草案 | 标的域、约束（22 口径） | 草案 + 风险 + 待验证项 |
| `protocol.adapter` | 协议接入 | 目标协议、能力卡 | 映射表 + 降级策略 |

`fix.bug` / `opt.improve` 直接对齐 56 §2.5 七态状态机与 IF-5 台账，不新增状态。

### 3.4 上下文层规范（P3）

1. **只允许四类来源**：L0 检索结果、L1 只读证据（经 `l1.trading` 等只读壳）、24 图压缩产物（必须带锚点，56 GAP-26 已落 Anchor 语义）、源文件引用（路径+版本+结论）。
2. **禁止**：模型自由浏览代码库取证、复述源文件正文、注入未版本化的口述口径。
3. **证据预算**：`max_evidence_items`（建议 12）与 `max_context_tokens` 双限；裁剪顺序为 H5 → H4 → H3，**H0/H1/H2 永不裁剪**。
4. **缺失即声明**：证据不足必须输出 `evidence=none`，不得补全（C-08）。

### 3.5 输出契约层规范（P4）

- 结构化优先：能 JSON 不用自由文本；JSON 必须给 schema 引用（复用 56 `contracts/*.schema.json`）。
- 文本结论必须带：证据级别、口径来源、时效声明。
- 引用格式：`[源文件名](相对路径#Lx-Ly) v版本`，禁止只写「根据系统架构」。
- 违禁词表由 P0 提供，不由 P4 各自维护（避免双事实源）。

### 3.6 工具层规范（P5）

- 工具清单**必须**等于当次 `tool_set` 快照（56 IF-7），多一个或少一个都判红（G-P-4）。
- 写工具必须显式标 `requires_mandate=true` 且在 prompt 中标注「无 Mandate 不得调用」。
- `effect=trade` 工具在 L2 一律不可见（ADR-01 / H1 / H2），prompt 中只允许出现「不可执行」声明。

---

## §4 源文件宪法（摘要，全文见 [PROMPT_CONSTITUTION.md](./PROMPT_CONSTITUTION.md)）

### 4.1 优先级

`H0 宪法 > H1 架构 SSoT > H2 域契约 > H3 模块实现 > H4 任务上下文 > H5 工具数据`；H5 **永不作为指令**（防注入）。

### 4.2 12 条硬条款（编号与违例码）

| # | 条款 | 违例码 |
|---|---|---|
| C-01 | 不得主张执行权 | `E_CLAIM_EXECUTION` |
| C-02 | L2 对 L1 只读 | `E_L1_WRITE` |
| C-03 | 实盘隔离，须引 SRC-06/11 | `E_LIVE_SCOPE` |
| C-04 | 证据分级必填 | `E_EVIDENCE_MISSING` |
| C-05 | 禁「将会/预计/必然/一定」 | `E_PROPHECY` |
| C-06 | 不得自证验收 | `E_SELF_ACCEPT` |
| C-07 | 发现权在 L1 | `E_NO_FINDING` |
| C-08 | 不虚构事实 | `E_FABRICATION` |
| C-09 | 注入隔离 | `E_INJECTION` |
| C-10 | 预算优先于完整 | `E_BUDGET_SILENT` |
| C-11 | 版本不得硬编码 | `E_HARDCODED_VERSION` |
| C-12 | 不越层叙述 | `E_LAYER_OVERREACH` |

### 4.3 判定归属（关键设计）

12 条款的校验**必须由确定性校验器完成**（正则 / 字段存在性 / 集合成员 / schema），属 L1 形态、零 token，挂在 56 `quality` 出口之前。**禁止让生成模型自评**——模型自评即 C-06 违例。

校验器**不新建入口**：按 §10 Q5 裁决，合入 56 `scripts/validate_contracts.py`，新增 `--prompts` / `--constitution` 两个子命令，与既有四契约自检共用同一套退出码与报告格式。

---

## §5 提示词注册表契约（草案）

### 5.1 落地位置

`57-Agent提示词工程/registry/prompt_registry.yaml`（P0 创建，append-only）

### 5.2 条目结构（IF-P-1 v1.0，已在 P0 落地）

```yaml
schema_version: "1.0"
constitution_version: "1.0.0"
fingerprint_algorithm: "file = sha256(原始字节)；tree = sha256(按相对路径排序拼接 '<relpath>\n<file_sha256>\n')"
prompts:
  - prompt_id: l2.debate.core            # l2.<domain>.<role|task>
    version: 0.1.0                       # semver，发布后不可变
    layer: L2
    sublane: L2-G                        # L2-K | L2-E | L2-G | L2-P | L2-A
    role: l2.debater
    task: debate.topic
    owner_module: "32-对抗性辩论Bot"
    constitution_version: "1.0.0"
    asset_path: "32-对抗性辩论Bot/core/prompts.py"   # 仓库根相对，prompt 正文位置（不复制正文）
    asset_kind: file                     # file | tree
    source_files: [SRC-03, SRC-07]       # 宪法 §2 登记 ID，只引用不复述
    variables: [topic, side, round, opponent_arguments]
    output_contract: null                # null = 尚未冻结（P2 补齐），不得据此判通过
    tool_set_ref: l2.debate.mcp          # 与 47 shell id 对齐，不复制工具清单
    token_budget: {fixed: 1800, context: 2200}
    eval_suite: null                     # 指向 45 托管 golden set；null = 未评测（不得 active）
    fingerprint: "sha256:…"              # 内容指纹，运行时校验（G-P-2）
    status: draft                        # draft | gated | active | deprecated
    depends_on: [l2.constitution@^1.0.0]
    changelog: "…"
    notes: "已知缺口（可选）"
```

P0 登记结论：6 条存量资产全部 `status: draft`、`eval_suite: null`、`output_contract: null`，即「已入账未认证」。校验器 `--prompts` 会对此组合判绿（合法基线态），任何 `active` 而 `eval_suite=null` 的组合在 P2 起判红。

### 5.3 版本规则

| 变更类型 | 升位 | 强制动作 |
|---|---|---|
| 破坏输出 schema / 行为语义 | MAJOR | 全量 golden set + 45 门禁 |
| 新增能力或可选字段 | MINOR | 相关子集 golden set |
| 措辞/纠错（判据不变） | PATCH | 冒烟 5 例 |
| 宪法条款变更 | 提升 `constitution_version` | 全部 active prompt 重跑 |

**不可变**：已 `active` 版本禁止原地修改；任何改动开新版本。`status` 迁移只允许 `draft → gated → active → deprecated`，禁止跳级与回退（回退＝新建旧版本号副本并标 deprecated 原因）。

### 5.4 出口对账（IF-P-3）

在 56 IF-3 `L2Envelope.meta` 上做**增量字段**（按 ADR-03「升次版本、禁止各壳私加」原则）：

```json
"meta": {
  "prompt_id": "l2.debate.bull",
  "prompt_version": "1.2.0",
  "prompt_fingerprint": "sha256:…",
  "constitution_version": "1.0.0",
  "constitution_tokens": 989,
  "tool_set_fingerprint": "sha256:…",
  "reasoning_effort": "medium"
},
"quality": {
  "violations": ["E_PROPHECY"]
}
```

硬约束：`prompt_version` 与 `fingerprint` 必须同源校验（指纹不符即判 `E_CONSTITUTION_DRIFT`）；`reasoning_effort` 补齐 RESEARCH §3 指出的「同 prompt 跨档位不可复现」缺口。

---

## §6 与既有契约的接缝

| 既有契约 | 接缝方式 | 是否改语义 |
|---|---|---|
| 56 ADR-02 单一事实源 | 宪法 §2 登记表只放「路径+版本+结论」，禁止复述 | 否 |
| 56 ADR-03 统一信封 | `meta` 增 6 个字段，走次版本 | 否（增量） |
| 56 ADR-04 Mandate 三件套 | prompt 显式声明写权限边界，校验器核对 | 否 |
| 56 IF-7 `tool_set` | P5 = 快照；`tool_set_fingerprint` 对账 | 否 |
| 56 G-L2-5 证据门禁 | C-04 提供 evidence 字段源头 | 否 |
| 56 G-L2-7 发现来源门禁 | C-07 在 prompt 侧前置阻断 | 否 |
| 56 IF-5 RepairLedger | `fix.bug` / `opt.improve` 模板产出直接映射台账字段 | 否 |
| 47 H1–H8 | C-01/C-02/C-03 是 H2/H4/H5 的上下文侧表达 | 否 |
| 47 layer_quota | 注册表只记 `tool_set_ref`，不重复计工具数 | 否 |
| 45 评测 | golden set 跑分入口复用 45 框架 | 否 |
| 48 涌现 D1/D2/D3 | prompt 改进归 D2（技术架构涌现），需实验编号 + 度量 | 否 |
| 54 L1 只读 | P3 只消费 `capability_manifest.yaml` 可见出口 | 否 |
| 49 双决策链 | `l2.debater` / `research.topic` 引用 SRC-07，不重述链路 | 否 |

---

## §7 门禁

| # | 门禁 | 判据 | 失败后果 |
|---|---|---|---|
| **G-P-1** | 宪法完整性 | 每次 L2 调用均加载 H0 全文 + 对应 P1 角色；`constitution_version` 非空 | 拒绝调用（fail-closed） |
| **G-P-2** | 版本可溯 | 出口 `meta` 含 `prompt_id/version/fingerprint` 且指纹匹配注册表 | 判红，trace 不可作验收证据 |
| **G-P-3** | 评测回归 | 版本变更含对应 golden set 结果；MAJOR 需全量 | 不得晋升 `active` |
| **G-P-4** | 工具集一致 | prompt 声明工具集合 == `tool_set` 快照集合（含空集） | 拒绝执行并审计 |
| **G-P-5** | 红线与证据 | C-01~C-08、C-12 确定性校验全过 | 按 §4.3 分级：拒答 / needs_review / degraded |
| **G-P-6** | 注入隔离 | H5 内容不进入指令区；目标字段不被 H5 改写 | 剥离并重跑，仍失败则拒答 |
| **G-P-7** | 预算 | `fixed + context ≤ token_budget` 且 `tokens_used ≤ budget_remaining` | 降级输出并标 `degraded=true` |
| **G-P-8** | 输出契约 | 输出通过 `output_contract` schema 校验 | 重试一次，仍失败则 `ok=false` |

---

## §8 路线

| 阶段 | 范围 | 完成判据（可机器判定） |
|---|---|---|
| **P0 可观测** | 发布 constitution@1.0.0；建 `registry/prompt_registry.yaml` 并登记 6 处存量资产（只登记不改造）；56 校验器增 `--prompts` 只读模式 | 6 条登记齐全；`validate_contracts.py --prompts` 对存量返回 `0`；不改任何 prompt 文本、不改运行时 |
| **P1 信封与试点**（v0.5 已落地） | 56 `meta` 增 6 字段；32 辩论壳 + 1-ARCH 意图识别两处接入；**宪法按任务类裁剪注入**（分类/路由类仅 P4 输出契约 + C-11；分析/辩论/研究类注入 full）——依据 [EVAL-20261118](./docs/EVAL-20261118-P1-A-B多轮回测.md)：全量注入对分类任务 Δ≤0 且 +19~35% token，对分析任务证据声明 0%→100%、C-05 违例 1→0 | 两处出口 `prompt_id/version/fingerprint` 非空；旧字段不变；回归不破；`meta.constitution_tokens` 计入 G-P-7 |
| **P2 门禁闭环**（v0.6 已落地） | 每任务类 ≥20 例 golden set；G-P-1..8 接入；C-01..C-12 校验器上线 | 人为注入 12 类违例，逐条被抓；`validate_contracts.py --self-test` 扩项全绿 |
| **P3 收敛**（v0.7 已落地） | 3.1 前端 prompt 迁入注册表；废弃散落硬编码；人格统一 | 全仓 `prompt_version` 命中 >0 且仅来自注册表注入；三入口语气/免责口径一致抽检通过 |
| **P4 演进闭环**（v0.8 已落地） | 与 48 D2 打通：prompt 改进作为实验，度量达标后经 45 晋升 | 至少 1 条 prompt 完成「实验编号 → 度量 → MAJOR/MINOR 晋升」全链路留痕 |
| **P5 凭证对接**（v0.9 已落地） | 晋升报告投递 45 仓库（Request/Run/Items/Evidence/Report），由 45 `Gate.issue` 签发 deploy 凭证并 `verify` 回验；`promote_prompt.py --issue-credential` 一键串联 | 至少 1 条 prompt 的晋升记录含 45 签发且回验通过的凭证；`active` 必须持证 |

**P0 硬边界**：不得修改 `32/core/prompts.py`、`1-ARCHITECTURE/.../system_prompt.md`、`3.1/.../node-prompts.ts` 的任何字节。先有账本，再谈改造。

---

## §9 风险册

| # | 风险 | 触发条件 | 缓解 |
|---|---|---|---|
| R-1 | 宪法膨胀推高固定成本 | 条款不断追加 | P0/P1/P2/P4 固定段设 token 上限（≤2900）；新增条款须等价删减或挪入按需段 |
| R-2 | 注册表与代码双事实源 | 有人直接改文件不改注册表 | G-P-2 指纹对账；CI 校验器必跑 |
| R-3 | 宪法与 SSoT 漂移 | 56/47 升版未同步 §2 | `E_CONSTITUTION_DRIFT` + 变更程序 §5.3 |
| R-4 | 门禁误杀正常输出 | C-05 正则过严（引用历史结论也命中） | 引用块豁免；误拦率 >5% 前保持 needs_review 不硬拒 |
| R-5 | 模型自评绕过 | 把校验写成 prompt 内自检 | §4.3 硬规定：校验必须确定性实现 |
| R-6 | 前端迁移破坏体验 | P3 统一人格后口语化丢失 | 抽检 20 例用户可读性再切 |
| R-7 | 与 48 实验口径冲突 | prompt 改进无 baseline | P4 强制同测试集前后对照（同 56 G-L2-8） |

---

## §10 待决问题（v0.2 已裁决）

**裁决原则**（取自业界实践，见 RESEARCH §5/§7）：① 单一事实源优先——任何会复制一份版本序列的方案一律否决；② 入口唯一——评测与校验不得出现第二套；③ 工具面不虚增——上下文资产不为对齐命名而建壳。

| # | 决策点 | 裁决 | 依据 | 落实位置 |
|---|---|---|---|---|
| Q1 | 宪法与 prompt 版本关系 | **A 各自 semver（解耦）** | 宪法变更影响全部 prompt，捆绑会造成 N×M 版本爆炸；业界 prompt registry 只对 prompt 本体做不可变版本 | 宪法 `constitution@1.0.0` 独立；注册表 `constitution_version` 单向引用 |
| Q2 | 3.1 前端 prompt 归属 | **A 纳入 57** | 人格不一致是最大用户可感知问题；业界统一 brand-level system prompt 覆盖全部入口 | 注册表 `sublane: L2-A`；P3 迁移 node-prompts.ts |
| Q3 | golden set 托管 | **A 复用 45** | 避免第二套评测事实源；45 已有回测/对照/统计检验框架 | `eval_suite` 指向 45 用例集；57 只维护任务类与阈值 |
| Q4 | prompt 改进的涌现维度 | **A 归 D2 技术架构涌现** | 先归既有维度，避免维度膨胀；积累 ≥20 例后再评估独立成维 | 48 D2 登记实验编号 |
| Q5 | 校验器归属 | **B 合入 56 `validate_contracts.py`** | 入口唯一；56 已是总校验器（自检 29 项），第二个入口会造成门禁双轨 | 56 校验器增 `--prompts / --constitution` 子命令 |
| Q6 | 是否建 `l2.constitution.mcp` | **A 不建** | 宪法是上下文不是能力；L2 工具 14/30 虽有余量，但建壳会虚增工具面并诱导宿主直调 | 仅作为 P0 段注入，无壳、无工具 |

**未关闭项**：Q2 的迁移时点、Q3 的用例集归属目录，属 P1/P2 实施细节，不阻塞 P0。

---

## §11 变更记录

| 版本 | 日期 | 变更 |
|---|---|---|
| v0.1 | 2026-11-18 | 首版调研稿：六层架构、宪法引用、注册表契约草案、8 门禁、P0–P4 路线、9 项缺口、6 项待决 |
| v0.2 | 2026-11-18 | §10 六项待决按业界实践裁决（Q1 解耦 / Q2 纳入前端 / Q3 复用 45 / Q4 归 D2 / Q5 合入 56 校验器 / Q6 不建壳）；§4.3 与 §8 P0 同步为 56 `validate_contracts.py --prompts`；57 登记进 3+3 映射与 INDEX |
| v0.3 | 2026-11-18 | P0 落地：新建 `registry/prompt_registry.yaml`（6 条存量资产，全部 draft）与 `registry/prompt_registry.schema.json`；56 校验器新增 `--prompts` / `--constitution` 只读子命令；§5.2 升 IF-P-1 v1.0（补 `asset_path` / `asset_kind` / `notes` 与指纹算法）。未改动任何 prompt 字节 |
| v0.4 | 2026-11-18 | P1 前置验证落地：新建 `evals/run_prompt_ab.py`（A/B 多轮，宪法段现场提取），两任务类 × 3 轮实测（意图 55 例、分析 8 题）；结论写入 [EVAL-20261118](./docs/EVAL-20261118-P1-A-B多轮回测.md)：准确率无提升、证据声明 0%→100%、C-05 违例 1→0、token +19%~35%。§8 P1 据此改为「按任务类裁剪注入」 |
| v0.5 | 2026-11-18 | P1 落地（运行时注入，不改 prompt 字节）：① 新建 [runtime/prompt_context_57.py](./runtime/prompt_context_57.py) 作为注入单一来源（注册表查表 + 指纹校验 + 宪法现场提取 + meta 生成）；② 新建 `56/contracts/l2_meta.schema.json`（IF-P-3，6 字段 + `constitution_tokens`），56 校验器新增 `--l2-meta` 与 4 条自检（自检 34→38）；③ `l2.debate.core` 经 `ConstitutionLLM` 装饰器注入 full（989 tok），`l2.intent.router` 注入 lite（P4+C-11，154 tok）；④ 两处出口 `meta` 带 `prompt_id/version/fingerprint`；⑤ `--prompts` 增指纹对账与宪法 token 计入 fixed 校验（G-P-2/G-P-7）。验收：自检 38/38、`--prompts --constitution` 0 violation、`--l2-meta` OK、32 测试全绿、mcp_shells 架构/trace 测试全绿。<br>注：生产 lite = P4 输出契约 + C-11，与 EVAL 中的实验 lite（6 条款）不同，后者仅作历史对照 |
| v0.6 | 2026-11-18 | P2 落地（门禁闭环）：① 新增 [runtime/constitution_gate.py](./runtime/constitution_gate.py)——C-01..C-12 确定性校验（正则/字段/集合/schema）+ G-P-1..8 聚合，按 §4 分级 `deny / needs_review / degraded`，禁止模型自评；② 56 校验器新增 `--l2-output` 与 17 条自检（38→55），人为注入 12 类违例逐条被抓；③ 新增 [evals/golden/l2_prompts.yaml](./evals/golden/l2_prompts.yaml)：`l2.intent.router` 复用 55 例、`l2.debate.core` 20 例（D01–D20）；④ `--prompts` 增 G-P-3：`gated/active` 必须有 `eval_suite`、`active` 需冻结 `output_contract`、suite 用例 ≥20；⑤ `run_prompt_ab.py` 支持 `--suite golden`。验收：自检 55/55、`--prompts --constitution` 0 violation、`--l2-output` 正例 0 violation / 注入「预计」负例命中 3 条 |
| v0.7 | 2026-11-18 | P3 落地（收敛）：① 注册表升级 `schema_version: 1.1`，新增根级 `persona`（style / disclaimer=`历史统计/模型推断，不代表未来` / forbidden_marketing），成为三入口统一人格的单一来源；② 运行时注入块追加 `【统一人格 persona】` 尾注，32 辩论与意图识别无需改资产即获得统一免责口径；③ 3.1 前端迁入注册表：新增生成器 [emit_prompt_snapshot.py](./runtime/emit_prompt_snapshot.py) 产出 `prompt-registry.generated.json`，[node-prompts.ts](../3.1-FRONTEND/src/lib/orchestration/node-prompts.ts) 改为读快照并导出 `getSkillPromptMeta()`，BASE 人格补「结论先行/不确定明说/数字可回溯」；`l2.app.skill` 0.1.0→0.2.0；④ 清理散落硬编码：`6-TRADING/docs/TRIGGER_PROMPTS.md` 指令区去掉「v1.3」，`l2.app.trade_ops` 0.1.0→0.2.0；⑤ 校验器新增 `--persona`（三入口免责一致 + 快照版本/指纹对账 + 前端禁止自建版本字面量）。验收：`--persona` / `--prompts --constitution` 0 violation、自检 55/55、前端 `tsc --noEmit` 0 error、32 测试全绿；`prompt_version` 运行时命中仅来自 57 运行时与注册表快照 |
| v0.8 | 2026-11-18 | P4 落地（演进闭环）：① `run_prompt_ab.py` 增 `--experiment-id`（48 D2 口径 `D2B-/D3B-/XA-`），实验编号写入轮次结果；② 新增 [runtime/promote_prompt.py](./runtime/promote_prompt.py)——按 golden 阈值做 45 三值判定（PASS/BLOCK/INCONCLUSIVE，护栏含 token 涨幅 ≤40%），只允许 `draft→gated`、`gated→active`，semver 升级（MAJOR 需 `--output-contract-changed`），落账 `registry/promotion_log.jsonl` 与 45 口径报告 `eval_report.v1`；③ `--prompts` 增 P4 留痕门禁：`gated/active` 必须存在 PASS 晋升记录；④ 完成首条全链路：`D2B-P57-INT-20261118`（意图 20 例 × 2 臂真实调用）→ `joint 100%/100%、Δ0pp、p=1.0、tokens×1.169` → MINOR `0.1.0→0.2.0` + `draft→gated`，留痕 [promotion_log.jsonl](./registry/promotion_log.jsonl) + [45 口径报告](./evals/out/promotions/l2.intent.router-0.2.0.report.json)。验收：`--prompts --constitution --persona` 0 violation、自检 55/55 |
| v0.9 | 2026-11-18 | P5 落地（45 凭证在线对接）：① 新增 [runtime/issue_45_credential.py](./runtime/issue_45_credential.py)——把 45 口径报告投递进 `InMemoryRepo`（Request/Run/Items/Evidence/Report），调用 45 `Gate.issue(eval_id, "deploy")` 签发凭证并 `Gate.verify` 回验，凭证绑定 `spec_hash + evidence_sha256`；② `promote_prompt.py` 增 `--issue-credential`，晋升落账后自动投递发证；③ `--prompts` 增 P5 门禁：`active` 必须有 `credential_issued + verified=true` 记录（`gated` 仅需晋升留痕）；④ 首张凭证：`prompt.l2.intent.router @ 0.2.0`，PASS，purpose=deploy，有效期 7 天（至 2026-11-25）。证据：凭证回验通过、`promotion_log.jsonl` 2 条留痕、`--prompts --constitution --persona` 0 violation、自检 55/55。注：45 本地为 `InMemoryRepo`，凭证进程内可验，跨进程需 PgRepo/重放报告。本地完整验收脚本：[evals/local_acceptance.py](./evals/local_acceptance.py)（9/9 通过） |
