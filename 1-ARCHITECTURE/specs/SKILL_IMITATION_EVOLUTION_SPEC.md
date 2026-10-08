# SKILL 模仿进化闭环 SPEC (SKILL_IMITATION_EVOLUTION_SPEC)

| 字段 | 值 |
|---|---|
| SPEC ID | SIE-SPEC |
| 版本 | v0.2 (DRAFT, 修复 3 Major + 4 Minor 后待复审) |
| 创建日期 | 2026-10-08 |
| 修改日期 | 2026-10-08 (v0.2: 修复 M-1 循环依赖/M-2 LLM计划可执行性/M-3 路径C vs HC-8 + m-1~m-4) |
| 关联 SPEC | [DREAMOS_SKILL_ORCHESTRATION_SPEC](./DREAMOS_SKILL_ORCHESTRATION_SPEC.md) (主 SPEC, §3.5-§3.9, §4.1, §8.1 F1-F20, HC-1~HC-9) |
| 状态 | 调研已完成 → SPEC 草案 → v0.1 评审完成 → v0.2 待复审 |
| 认知记忆 | VM-1791454714033 (3 条硬约束, B级) |
| 评审报告 | 3 Major (M-1/M-2/M-3) + 4 Minor, 详见评审记录 |

---

## 1. 背景与动机

### 1.1 问题陈述

当前 DSH SKILL 编排系统在 SkillSelector 未命中时（规则无命中 + TF-IDF cosine < 0.30）走 `simple_qa` 兜底。这意味着系统遇到"暂时还不具备对应 SKILL"的问题时，不具备解决能力——只能 fallback 到 LLM 通用问答，结果无法沉淀为可复用能力。

> **m-1 修复**：阈值统一为 0.30（v0.1 §1.1 写 0.15 为笔误，与 §2.1 触发条件对齐）。0.30 依据调研脚本 /tmp/eval_tfidf_vs_bge.py 显示 TF-IDF 分数分离度 0.26-0.53，0.30 处于中位，平衡召回率与误触发。该阈值为经验值，待实战数据校准（见 §3.4 N 值说明）。

### 1.2 用户诉求（原话精炼）

> "当我们不具备某种 SKILL 时，应该通过文档管理系统，去查看技术实现方法，通过模仿的方式，形成解决问题的能力。当问题解决后，按照我们的流程形成相关 SKILL，从而进入相关 SKILL 管理系统。如果系统本身还是不具备，也需要调用相关 SKILL 联网调研来解决问题。"

### 1.3 设计目标

- **能力进化闭环**：模仿 → 即兴执行 → 固化 → 沉淀，让系统在 SKILL 覆盖缺口处自我补齐
- **零回归**：不破坏既有 SKILL 命中路径（路径 A），不违反 HC-1~HC-9
- **可沉淀**：重复出现的模仿模式自动触发 skill-creator 沉淀为正式 SKILL
- **联网兜底**：模仿也失败时自动触发 dream-research-workflow 联网调研

---

## 2. 三路径架构总览

### 2.1 路径定义

| 路径 | 名称 | 触发条件 | 执行方式 | 沉淀方式 |
|---|---|---|---|---|
| **A** | 正常 | SkillSelector 命中 (规则命中 OR TF-IDF cosine ≥ 0.30) | 认知上下文 + DSH subagent 执行 | knowledge-ingest (每次) |
| **B** | 模仿 (新增) | 路径 A 返回空 OR cosine < 0.30 | 索引系统检索文档 → LLM 转执行计划 → DSH 执行 (注入文档上下文) | 重复 N 次后 skill-creator |
| **C** | 联网兜底 | 路径 B 模仿也失败 (文档检索为空 OR 执行失败) | dream-research-workflow 联网调研 → LLM 生成方案 → DSH 执行 | knowledge-ingest + skill-creator |

### 2.2 触发判定流程

```
意图识别完成
    ↓
SkillSelector.select()
    ↓
┌─ 命中(规则或 cosine≥0.30) → 路径 A
└─ 未命中(cosine<0.30 或空)
    ↓
路径 B: index_query_service.py 检索文档
    ↓
┌─ 文档命中 → LLM 转执行计划 → DSH 执行 → 成功 → 计数 → 路径 B 完成
│                       ↓执行失败
└─ 文档为空 ─────────────┘
    ↓
路径 C: dream-research-workflow 联网调研
    ↓
LLM 生成方案 → DSH 执行 → knowledge-ingest + skill-creator 沉淀
```

---

## 3. 详细设计

### 3.1 路径 A — 正常（既有，无改动）

保持 [DREAMOS_SKILL_ORCHESTRATION_SPEC §3.5-§3.9] 现有逻辑：
- SkillSelector 规则优先 + TF-IDF 向量兜底
- 命中后 CognitiveContextBuilder.build() 构建上下文
- DSHExecutionEngine.execute_plan() 执行
- knowledge-ingest 沉淀

**本 SPEC 不修改路径 A**。

> **m-4 修复**：路径 B/C 上线后 `simple_qa` 仍保留为最终降级——当路径 C 也失败时，按 §3.6 FAIL-OPEN 返回 `human_review_required=true` 报告；若该报告生成也失败，最终降级到原 `simple_qa`。三层降级链：路径 A → 路径 B → 路径 C → simple_qa 兜底。

### 3.2 路径 B — 模仿（新增）

#### 3.2.1 触发条件

SkillSelector 返回以下信号之一时触发：

```typescript
interface SkillSelectorResult {
  status: 'hit' | 'imitation_required';
  // hit: 原路径 A
  // imitation_required: cosine < 0.30 或规则无命中，进入路径 B
  selections: SkillSelection[];
  // 空数组表示完全无候选
}
```

**关键改动**：原 SkillSelector 在无匹配时返回 `fallback_skill: 'simple_qa'`，本 SPEC 修改为返回 `imitation_required` 信号，不再直接走 simple_qa。

#### 3.2.2 模仿执行流程

```
[Step 2.1] SkillSelector 返回 imitation_required
[Step 2.2] SkillOrchestrationExecutor 调 CognitiveContextBuilder.build()
           认知上下文照常构建（四系统并行，HC-7 只读，HC-9 超时不阻塞）
[Step 2.3] 调 index_query_service.query(
             query=用户原始消息,
             category="doc",
             top_k=5
           )
           检索 0-系统文档管理 + 2-KNOWLEDGE 下 INDEX.md（bge-small-zh 向量化）
[Step 2.4] 文档检索结果为空 → 跳转路径 C
           文档非空 → LLM 把文档转执行计划（提示词见 §3.2.3）
[Step 2.5] DSHExecutionEngine.execute_plan() 执行，document_context 注入 LLM fallback 提示词
[Step 2.6] 执行成功 → ImitationCounter.increment(query_pattern) → 计数 ≥ N 触发 skill-creator
           执行失败 → 跳转路径 C
[Step 2.7] SummaryAgent.summarize() → 返回 FinalOutput
```

#### 3.2.3 LLM 把文档转执行计划 — 提示词模板

> **M-2 修复**：LLM 生成的 `component` 必须从 DSH 已注册节点 ID + 已知 SKILL ID 白名单中选择，避免生成不存在的组件引用。白名单由 DSHExecutionEngine.get_known_components() 运行时提供，注入提示词。

```
你是一个执行计划生成器。用户问题：{user_message}

参考文档（来自文档管理系统）：
{document_context}

可调用组件白名单（仅可从此列表选择 component 字段）：
{known_components}

任务：把上述文档的技术实现方法转换为可执行的步骤计划。
要求：
1. 严格基于文档内容，不要臆造
2. 每个步骤的 component 字段**必须**从上述白名单中选择，不得生成白名单外的组件
3. 每个步骤明确：调用哪个组件 / 用什么参数 / 期望输出
4. 如果文档描述的能力不在白名单内，标记该步骤为 "manual_action"，由 DSH LLM fallback 分支处理
5. 如果文档无法完整覆盖用户问题，明确指出缺口
6. 输出 JSON 数组，每个元素: {step, component, params, expected_output, source_doc_ref}

仅当文档完全无法覆盖时返回 {"fallback": "need_research"}。
```

**映射层说明**：LLM 输出的 JSON 数组由 `DSHExecutionEngine.execute_plan()` 逐步骤执行。每步的 `component` 已确保是白名单内 ID，DSH 可直接调用对应节点或 SKILL。`manual_action` 类型的步骤由 DSH 的 LLM fallback 分支用 `document_context + expected_output` 提示 LLM 推理完成。这一映射层确保 LLM 生成的计划 100% 可被 DSH 执行，无"生成不存在的组件引用"风险。

#### 3.2.4 ImitationCounter — 模仿计数器（新增组件）

```typescript
// 3.1-FRONTEND/src/lib/imitation-counter.ts
interface ImitationRecord {
  query_pattern: string;      // 用户问题归一化模式（见下方归一化规则）
  count: number;              // 重复次数
  first_seen: number;         // 首次时间戳
  last_seen: number;          // 最近时间戳
  document_sources: string[]; // 命中过的文档路径
  execution_plan_examples: string[]; // 执行计划样例（最多保留3条）
  sedimentation_triggered: boolean; // 是否已触发沉淀（防重复触发）
}

class ImitationCounter {
  // 计数 ≥ N 时触发 skill-creator
  // N 值见 §3.4
  increment(query_pattern: string, doc_sources: string[], plan: string): {
    triggered: boolean;
    current_count: number;
  };
}
```

**存储**：本地 JSON 文件 `3.1-FRONTEND/data/imitation-counter.json`，每次 increment 后写盘。

> **M-1 修复（循环依赖隔离边界）**：ImitationCounter **独立计数**，不受 SkillSelector 索引更新影响。设计原则：
> 1. **模仿执行的 query 不写回 TF-IDF 索引**——路径 B 的模仿执行结果不更新 SkillSelector 的 TFIDFIndex，避免同类 query 第 2 次被路径 A 命中导致计数永远停在 1。
> 2. **沉淀后清理**：当 ImitationCounter 触发 skill-creator 沉淀出新 SKILL 后，该 `query_pattern` 的计数记录标记 `sedimentation_triggered=true` 并归档，不再参与后续计数。新 SKILL 注册到 registry.json 后，同类 query 自然走路径 A。
> 3. **knowledge-ingest 隔离**：路径 B 的模仿执行不调 knowledge-ingest（仅路径 A 和路径 C 调），确保 SkillSelector 的认知上下文不因模仿而改变。
> 4. **降级保护**：即使外部系统（如 knowledge-ingest 被其他流程触发）更新了索引导致同类 query 走路径 A，ImitationCounter 仍保留历史计数，下次同类 query 走路径 B 时继续累计，不会清零。

### 3.3 路径 C — 联网兜底（新增）

#### 3.3.1 触发条件

路径 B 满足以下任一条件时跳转路径 C：
- index_query_service 返回空（文档库无相关文档）
- LLM 把文档转执行计划返回 `{"fallback": "need_research"}`
- DSH 执行模仿计划失败（执行超时/返回错误）

#### 3.3.2 联网兜底流程

```
[Step 3.1] 路径 B 判定失败
[Step 3.2] SkillOrchestrationExecutor 调 dream-research-workflow SKILL
           状态机五阶段：need_analysis → multi_source_research →
           cross_validation → report → hermes_reflection
           数据源：finance + github + modular + code (4 维)
[Step 3.3] research-workflow 产出研究报告（markdown）
[Step 3.4] LLM 把研究报告转执行计划（复用 §3.2.3 提示词模板，document_context=research_report）
[Step 3.5] DSHExecutionEngine 执行
[Step 3.6] 执行成功 → knowledge-ingest 沉淀研究报告到 2-KNOWLEDGE
                      → skill-creator 沉淀为正式 SKILL（路径 C 必沉淀，不等 N 次）
                      → **沉淀的 SKILL 默认 status=proposed**（M-3 修复）
                      → **交易决策类 SKILL 必须经人工审核才升级 active**（HC-8 对齐）
[Step 3.7] 执行失败 → SummaryAgent 生成"无法解决"报告，标记 human_review_required=true
```

#### 3.3.3 联网兜底白名单

路径 C 调用 dream-research-workflow 自动联网，**突破** [VM-1786255475855] 原约束"稳定优先模式/联网唯一通道=周四 Knowledge-Update"。
理由：用户 2026-10-08 明确决策"路径 C 完全自动"（[VM-1791454714033]）。
约束：路径 C 仅在 A、B 均失败时触发，避免常态性联网。

> **M-3 修复（路径 C 沉淀 vs HC-8 边界）**：路径 C 沉淀的 SKILL 默认 `status=proposed`，不自动激活。分类处理：
> - **非交易类 SKILL**（如工具配置、文档查询）：proposed → shadow → active 按既有生命周期升级
> - **交易决策类 SKILL**（涉及买卖信号、仓位管理、风控参数）：必须经人工审核（human-in-the-loop）才升级 active，对齐 HC-8
> - **路径 C 沉淀的 SKILL 在升级 active 前不会进入 SkillSelector 候选集**（registry.json 过滤 status≠active），确保未审核的 SKILL 不影响路径 A 命中

### 3.4 沉淀门槛 N 值

**N = 3**（经验值，待实战数据校准，可配置化 `IMITATION_THRESHOLD` 环境变量）

> **m-3 修复**：N=3 为经验建议值，非数据驱动。当前无足够样本量验证 N=3 优于 N=2/N=4。落地后通过 ImitationCounter 日志统计沉淀触发率、误沉淀率，3 个月后用真实数据校准。

理由（经验判断）：
- N=1：一次性 query 即沉淀，会产生大量垃圾 SKILL（用户明确反对）
- N=2：偶发重复也会触发，仍偏激进
- N=3：要求同一模式出现 3 次才沉淀，过滤一次性需求 + 偶发重复
- N>3：沉淀过慢，无法及时固化已验证的模仿模式

**判定规则**：query_pattern 归一化后，同模式累计 ≥ 3 次 → 触发 skill-creator。

> **m-2 修复（query_pattern 归一化规则）**：采用正则替换，不引入 NER/LLM，对齐 HC-1：
> 1. 数字替换为 `{number}`：`查询比特币 69000 的支撑位` → `查询比特币{number}的支撑位`
> 2. 已知 symbol 替换为 `{symbol}`：`比特币/以太坊/BTC/ETH/...` → `{symbol}`（symbol 列表来自 18-DB 配置）
> 3. 百分比替换为 `{pct}`：`跌了 5%` → `跌了{pct}`
> 4. 时间表达式替换为 `{time}`：`昨天/2026-10-08/3 天前` → `{time}`
> 5. 转小写 + 去多余空格
> 归一化由 `imitation-counter.ts` 内的 `normalizePattern(raw: string): string` 实现，纯正则，零 LLM 依赖。

**路径 C 例外**：路径 C 必沉淀（不等 N 次），因为联网调研成本高，已验证的方案应立即固化避免重复联网。但沉淀的 SKILL 仍遵循 §3.3.3 的 proposed 默认 + 交易类人工审核规则。

### 3.5 SSE 事件设计

新增以下 SSE 事件（复用 PlannerProgressEvent 格式）：

| event | phase | payload | 说明 |
|---|---|---|---|
| `imitation_triggered` | step.2.1 | `{query_pattern, cosine_score}` | 路径 B 触发 |
| `document_retrieved` | step.2.3 | `{doc_count, top_doc_path, top_score}` | 文档检索完成 |
| `imitation_plan_generated` | step.2.4 | `{step_count, fallback_needed}` | LLM 生成执行计划 |
| `imitation_executed` | step.2.5 | `{success, execution_time_ms}` | 模仿执行结果 |
| `imitation_counter` | step.2.6 | `{current_count, threshold, triggered}` | 计数器状态 |
| `research_triggered` | step.3.2 | `{reason, research_phase}` | 路径 C 触发 |
| `research_completed` | step.3.3 | `{report_size, sources_count}` | 调研完成 |
| `skill_sedimentation` | step.2.6/3.6 | `{skill_id_draft, source_path}` | 沉淀触发 |

### 3.6 FAIL-OPEN 设计

遵循 HC-6，路径 B/C 任一环节失败均不阻塞主流程：

| 失败点 | 降级动作 |
|---|---|
| index_query_service 不可达 | 跳过路径 B，直接路径 C |
| LLM 转执行计划超时 | 路径 B 失败 → 路径 C |
| DSH 执行模仿计划失败 | 路径 C |
| dream-research-workflow 失败 | SummaryAgent 生成"无法解决"报告，`human_review_required=true` |
| skill-creator 失败 | 仅记录 warning，不影响本次执行结果 |

**主流程底线**：路径 C 也失败时，返回"无法解决 + human_review_required=true"，不抛异常给上层。

---

## 4. 与 HC-1~HC-9 对齐分析

| HC | 主 SPEC 约束 | 本 SPEC 对齐 | 冲突？ |
|---|---|---|---|
| HC-1 | SKILL 选择不使用 LLM | 路径 B/C 的 LLM 用于**执行阶段**（文档转计划），不是**选择阶段**。SkillSelector 仍纯规则 + TF-IDF，不调 LLM。 | 否 |
| HC-2 | DSH 执行优先调系统节点，LLM 仅兜底 | 路径 B/C 本质是"系统节点能力缺失时的兜底"，LLM 用于把文档/调研结果转计划，仍走 DSHExecutionEngine 执行。 | 否 |
| HC-3 | 交易类 SKILL 必须有 Autonomy Boundary | 路径 B/C 沉淀的交易类 SKILL 必须带 Autonomy Boundary，skill-creator 在生成时强制注入。 | 否 |
| HC-4 | C/G 层物理分离（执行/状态分离） | ImitationCounter 属 G 层（状态），DSHExecutionEngine 属 C 层（执行），物理分离。 | 否 |
| HC-5 | orchestrator_v2 渐进迁移 | 本 SPEC 是在 SkillOrchestrationExecutor 内新增分支，不废弃原路径 A。 | 否 |
| HC-6 | 降级链必须 FAIL-OPEN | §3.6 已设计完整 FAIL-OPEN 链。 | 否 |
| HC-7 | 认知上下文构建只读 | 路径 B/C 调 CognitiveContextBuilder.build() 仍只读。 | 否 |
| HC-8 | 知识沉淀只新增不修改；交易决策类知识需人工审核 | 路径 C 调研报告沉淀走 knowledge-ingest（只新增）；**路径 C 沉淀的 SKILL 默认 status=proposed，交易决策类需人工审核才升级 active（M-3 修复）**；路径 B 沉淀的 SKILL 同样适用。 | 有条件否* |
| HC-9 | 认知上下文四系统并行，任一超时不阻塞 | 路径 B/C 调用认知上下文同样享受 2s 超时不阻塞。 | 否 |

**结论**：本 SPEC 与 HC-1~HC-9 **有条件零冲突**（v0.2 修正）。
- HC-1~HC-7、HC-9：零冲突
- HC-8：有条件零冲突（\*）——路径 C 必沉淀的默认 proposed + 交易类人工审核规则确保不违反 HC-8。若未来落地时省略人工审核环节则会产生真实冲突，属落地合规责任。

关键澄清：HC-1 限制的是"SKILL 选择阶段不用 LLM"，本 SPEC 的 LLM 用于"执行阶段把文档转计划"，属于 HC-2 允许的"LLM 兜底"范畴。

---

## 5. 落地改动清单

### 5.1 修改文件（4 个）

| 文件 | 改动 | 优先级 |
|---|---|---|
| `3.1-FRONTEND/src/lib/skill-selector.ts` | 返回 `imitation_required` 信号替代 fallback `simple_qa` | P0 |
| `3.1-FRONTEND/src/lib/skill-orchestration-executor.ts` | 新增 Step 2.5 模仿分支 + 路径 C 联网兜底分支 | P0 |
| `3.1-FRONTEND/src/lib/dsh-execution-engine.ts` | LLM fallback 分支扩展：接受 `document_context` 参数注入提示词；**新增 `get_known_components()` 方法返回已注册节点 ID + SKILL ID 白名单**（M-2 修复） | P0 |
| `3.1-FRONTEND/src/lib/cognitive-context-builder.ts` | 新增 `imitation_context` 字段（注入文档检索结果） | P1 |
| `3.1-FRONTEND/src/lib/imitation-counter.ts` | **新增 `normalizePattern()` 纯正则归一化方法**（m-2 修复）；新增 `sedimentation_triggered` 防重复触发字段（M-1 修复） | P0 |

### 5.2 新增文件（2 个）

| 文件 | 作用 | 优先级 |
|---|---|---|
| `3.1-FRONTEND/src/lib/imitation-counter.ts` | 模仿计数器，达 N 次触发 skill-creator | P0 |
| `3.1-FRONTEND/data/imitation-counter.json` | 计数器持久化存储 | P0 |

### 5.3 复用已有组件（零改动）

| 组件 | 来源 | 作用 |
|---|---|---|
| `index_query_service.py` | 2-KNOWLEDGE/9-RAG-INFRA/ | 路径 B 文档检索（bge-small-zh） |
| `knowledge-ingest.ts` | 3.1-FRONTEND/src/lib/ | 路径 C 调研报告沉淀 |
| `dream-research-workflow` SKILL | .trae/skills/ | 路径 C 联网调研 |
| `skill-creator` SKILL | .trae/skills/ | 沉淀为正式 SKILL |
| `CognitiveContextBuilder` | 3.1-FRONTEND/src/lib/ | 认知上下文构建（路径 B/C 复用） |
| `DSHExecutionEngine` | 3.1-FRONTEND/src/lib/ | 执行引擎（路径 B/C 复用） |
| `SummaryAgent` | 3.1-FRONTEND/src/lib/ | 汇总（路径 B/C 复用） |

---

## 6. 验收用例

### 6.1 路径 A — 正常命中（回归测试）

**前置**：用户问"分析 RSI 超卖反弹"，SkillSelector 命中 `dream-science-hypothesis-verification`
**预期**：走原路径 A，不触发路径 B/C
**验证**：无 `imitation_triggered` SSE 事件

### 6.2 路径 B — 模仿成功

**前置**：用户问"如何配置 bsk 认证"（系统无对应 SKILL，但 0-系统文档管理 有 bsk 配置文档）
**预期**：
1. SkillSelector 返回 `imitation_required`
2. index_query_service 检索到 bsk 文档
3. LLM 转执行计划
4. DSH 执行成功
5. ImitationCounter 计数 +1
**验证**：SSE 事件序列 `imitation_triggered → document_retrieved → imitation_plan_generated → imitation_executed → imitation_counter`

### 6.3 路径 B — 计数达 N 次触发沉淀

**前置**：§6.2 同类 query 出现 3 次
**预期**：第 3 次执行后触发 skill-creator
**验证**：SSE 事件 `skill_sedimentation`，新增 SKILL 注册到 registry.json（status=proposed）

### 6.4 路径 C — 联网兜底

**前置**：用户问"如何集成某新开源库 X"（文档库无相关文档）
**预期**：
1. 路径 B 检索文档为空
2. 触发 dream-research-workflow
3. 调研报告生成
4. LLM 转执行计划 + DSH 执行
5. knowledge-ingest 沉淀报告
6. skill-creator 沉淀（不等 N 次）
**验证**：SSE 事件序列 `imitation_triggered → research_triggered → research_completed → skill_sedimentation`

### 6.5 FAIL-OPEN — 全链路失败

**前置**：路径 B 文档为空 + 路径 C dream-research-workflow 失败
**预期**：返回 FinalOutput，`human_review_required=true`，content="无法解决，请人工介入"
**验证**：无异常抛出，主流程不阻塞

### 6.6 HC-1 合规

**前置**：任意 query
**预期**：SkillSelector.select() 全程不调 LLM
**验证**：代码审查 skill-selector.ts 无 LLM 调用

### 6.7 M-1 循环依赖隔离（v0.2 新增）

**前置**：用户问"如何配置 bsk 认证"，路径 B 模仿成功，ImitationCounter 计数=1。之后 knowledge-ingest 被其他流程触发更新了 TF-IDF 索引。
**预期**：同类 query 第 2 次出现时，即使 SkillSelector 命中走路径 A，ImitationCounter 计数仍保留为 1（不清零）；若 SkillSelector 未命中走路径 B，计数继续累计为 2。
**验证**：检查 `imitation-counter.json` 中该 pattern 的 count 字段未被清零。

### 6.8 M-2 LLM 计划白名单约束（v0.2 新增）

**前置**：路径 B 触发，LLM 把文档转执行计划
**预期**：LLM 输出的 JSON 数组中，每个 `component` 字段值均在 `get_known_components()` 返回的白名单内
**验证**：若 LLM 输出白名单外的 component，DSH 执行时抛出 `UnknownComponentError`，FAIL-OPEN 降级到路径 C。

### 6.9 M-3 路径 C 交易类 SKILL 人工审核（v0.2 新增）

**前置**：路径 C 联网调研了一个新交易策略（如"网格交易"），skill-creator 沉淀
**预期**：新 SKILL 在 registry.json 中 `status=proposed`，SkillSelector 候选集过滤掉（status≠active），路径 A 不会命中
**验证**：registry.json 检查 status 字段；SkillSelector.select() 不会返回该 SKILL；人工审核后改为 active 才被路径 A 命中。

### 6.10 m-2 query_pattern 归一化（v0.2 新增）

**前置**：用户问"查询比特币 69000 的支撑位"和"查询以太坊 3500 的阻力位"
**预期**：归一化后均为"查询{symbol}{number}的{xxx}位"模式（不同关键词但同类模式应归一化为不同 pattern）
**验证**：ImitationCounter.normalizePattern() 输出一致的模式串。

---

## 7. 风险与限制

| 风险 | 等级 | 缓解措施 |
|---|---|---|
| LLM 转执行计划幻觉（基于文档臆造步骤） | 中 | 提示词明确"严格基于文档内容"，DSH 执行时校验组件存在性 |
| 路径 C 联网成本高 | 中 | 仅在 A、B 均失败时触发；联网结果立即沉淀避免重复联网 |
| N 值选 3 是否合理 | 低 | 待评审确认；可配置化 `IMITATION_THRESHOLD` 环境变量 |
| ImitationCounter 并发写 | 低 | 单线程 SkillOrchestrationExecutor 串行 increment，无并发 |
| 沉淀的 SKILL 质量参差 | 中 | skill-creator 生成 status=proposed，需实战验证才升级 shadow→active |
| query_pattern 归一化不准 | 中 | 用简单实体替换（数字/符号/symbol），复杂场景待后续优化 |

---

## 8. 评审清单（v0.1 评审完成，v0.2 待复审）

- [x] Devil's Advocate 让步阈值 ≥ 4（v0.1 评审触发 3 条 ≥4 分：M-1/M-2/M-3，v0.2 已全部让步修改）
- [x] 7 模式阻断清单（v0.1 评审：3 部分通过 + 1 不通过，v0.2 修复后待复审）：
  - [x] 模式1（幻觉引用）：通过
  - [~] 模式2（数据造假）：通过，但样本量 n=13 偏小，已在 §3.4 标注待实战校准
  - [x] 模式3（方法捏造）：v0.2 补充 §3.2.3 映射层说明 + §3.2.4 隔离边界（M-1/M-2 修复）
  - [~] 模式4（框架锁定）：未明确对比替代方案，留作后续优化
  - [x] 模式5（结果幻觉）：v0.2 §3.4 标注 N=3 为经验值待校准（m-3 修复）
  - [x] 模式6（逻辑跳跃）：通过
  - [~] 模式7（边界忽略）：部分通过，§7 风险清单覆盖但未声明"不适用场景"

**v0.1 评审结论**：修改后接受 (Major Revision Required)，3 条 Major 已修复。
**v0.2 待复审**：M-1（循环依赖隔离）/M-2（白名单映射）/M-3（路径 C HC-8 边界）+ m-1~m-4 均已修复，待 dream-science-peer-review 复审。

---

## 9. 后续阶段（评审通过后）

1. **TDD 落地**：用 `tee-red-green-progress` SKILL，RED 阶段先写 §6 验收用例的测试
2. **GREEN 阶段**：按 §5 改动清单实现 4 个修改 + 2 个新增
3. **BrowserSkill 验收**：每完成一阶段用浏览器做页面功能真实验收（用户偏好）
4. **认知闭环**：落地后 record + verify 沉淀本次经验

---

## 附录 A — 三路径可视化

```
┌──────────────────────────────────────────────────────────────────────┐
│                     意图识别完成 (S 层)                              │
└──────────────────────────────┬───────────────────────────────────────┘
                               ↓
              ┌────────────────┴────────────────┐
              │     SkillSelector.select()     │  (HC-1: 不用 LLM)
              │   规则优先 + TF-IDF 向量兜底     │
              └────────────────┬────────────────┘
                                 ↓
            ┌────────────────────┴────────────────────┐
            │ cosine≥0.30 或规则命中?                 │
            └────┬───────────────────────────┬───────┘
                 ↓ 否                          ↓ 是
    ┌────────────────────────┐    ┌────────────────────────┐
    │   路径 B: 模仿 (新增)   │    │   路径 A: 正常 (既有)  │
    │   index_query_service  │    │   CognitiveContext     │
    │   → LLM 转计划          │    │   → DSH 执行           │
    │   → DSH 执行(注入文档)  │    │   → knowledge-ingest   │
    │   → ImitationCounter   │    └────────────────────────┘
    │   → N次后skill-creator │
    └────────────┬───────────┘
                 ↓ 失败/文档空
    ┌────────────────────────┐
    │   路径 C: 联网兜底     │
    │   dream-research-wf    │
    │   → LLM 转计划         │
    │   → DSH 执行           │
    │   → knowledge-ingest   │
    │   → skill-creator(必) │
    └────────────────────────┘
```

---

*SPEC 终*
