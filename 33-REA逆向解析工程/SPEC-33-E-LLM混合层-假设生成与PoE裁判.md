# SPEC-E: 33-REA LLM 混合层 — 假设生成 + PoE 裁判

> 版本：v0.2.0
> 日期：2026-11-12
> 状态：✅ P0 + P1 + P2 全部落地（未提交）；内核仍零 LLM 调用
> 变更（v0.1.1 → v0.2.0）：T-E5 adapt_plan 契约与 submit/poll/cancel 工具；T-E6 外部源价值评分门禁；T-E7 静态复核任务级收口；T-E8 token 预算 + llm_cost.jsonl；T-E9 过 gate 认知回写载荷（写关闭挂起）；T-E10 SKILL 补假设送审流程
> 归属：33-REA逆向解析工程（裁判层） × 宿主 AI（假设生成） × 35-广义认知系统（记忆层）
> 上游：[SPEC-33-D](./SPEC-33-D-REA作为L0MCP的工程开发协作.md)、[SPEC-33-反思层](./SPEC-33-反思层.md)、[SPEC-33-输出场景-意图系统](./SPEC-33-输出场景-意图系统.md)、[COLLABORATION-CONTRACT.md](../35-广义认知系统协作模块/COLLABORATION-CONTRACT.md)
> 输入：2026-11-11 LLM 能力核查（代码事实，见 §0.2）

---

## §0 背景与结论

### 0.1 一句话结论

**33-REA 内核零 LLM 调用，这是资产而非缺陷。真正缺的不是"让 REA 去调度模型"，而是把「LLM 出假设 → 33 用 PoE/证据链裁判 → 认知系统记结论」这条线接上。本 SPEC 只做接线，不让 REA 变成 agent。**

### 0.2 现状证据（可复核）

| # | 事实 | 证据位置 |
|---|---|---|
| E1 | 全工程 grep `anthropic\|openai\|dashscope\|litellm\|messages.create` **0 处真实调用**，仅 2 处命中外部源清单的 URL 字符串 | [run_wave2_harvest.py](./scripts/run_wave2_harvest.py#L41-L43) |
| E2 | prompt 资产只有 1 个文件、23 行（角色/流程/输出格式/铁律） | [investigation_prompt.md](./prompts/investigation_prompt.md) |
| E3 | `assemble_spec` 注释写"模拟单次 LLM 生成"，实现为**确定性模板拼接** | [output_scenarios.py](./core/reflection/output_scenarios.py#L121-L131) |
| E4 | `_parse_task_features` 用 `"python" in text` 之类关键词命中冒充语义解析 | [output_scenarios.py](./core/reflection/output_scenarios.py#L109-L119) |
| E5 | replay_pool 15,720 棵树 / 90,333 节点，但 analyzer 计数为 `acceptance_gate` 14,965、`code_commit` 14,965、`cognitive_record` 14,965、`doc_sync` 14,964，`ts_project_analyzer` 仅 372；15,580 棵树无 `source_label` | 2026-11-11 本地统计 |
| E6 | `external_sources.json` 登记 146 条外部源，实际带标签案例树约 140 棵 | [external_sources.json](./reflection_data/external_sources.json) |
| E7 | MCP 工具面只有 analyze/trace/compare/snapshot，反思层/审计层/方法论抽象/外部 harvest **全部未暴露** | [server.py](../mcp_shells/l0_rea/server.py) |
| E8 | 外部源语义价值评分自述未落地（Q3 待做） | [SPEC-33-外部源自动沉淀流水线](./SPEC-33-外部源自动沉淀流水线-可行性评估.md#L364) |
| E9 | 33-REA 全量 **301 passed**，PoE/反思层均有测试覆盖 | `tests/`（34 个测试文件，14 个覆盖反思/审计/方法论） |

### 0.3 问题清单

| # | 问题 | 后果 |
|---|---|---|
| P-01 | 反思层/审计层/方法论抽象对宿主不可见 | 模型只能看结构，看不到"这套代码值不值得借鉴" |
| P-02 | "单次 LLM 生成"是模板组装 | 研究→Spec 之间断裂，模板无法提出新假设 |
| P-03 | 学习语料错位：15,580/15,720 是流程执行日志 | `MethodologyAbstractor` 要求 ≥2 项目同模式，语料结构直接卡死产出 |
| P-04 | `extract_target` 靠人工，无价值评分 | 146 条外部源无法自动晋升优先级 |
| P-05 | 无 `adapt_plan` 产物 | "借鉴→改造"缺最后一环 |
| P-06 | 若直接让模型改代码，无裁判层 | 幻觉直接落地，比不做事更危险 |
| P-07 | LLM 产出没有统一证据契约 | 现有 `Evidence` 只服务静态分析，接不住假设 |
| P-08 | 若无 token 预算 | 未来真调用时成本不可控、不可审计 |

### 0.4 非目标（明确不做）

| 不做 | 原因 |
|---|---|
| 不在 33 内核实现模型客户端、不存 API key | 保持零 token 内核；模型调用由宿主承担，凭证不进仓库 |
| 不让 REA 自动改代码 / 生成补丁 / 执行迁移 | 只出 `adapt_plan`，执行权在人 |
| 不重写 PoE 公式与门禁阈值 | 已测试覆盖，改动即回归风险 |
| 不替代宿主 agent / SKILL 编排 | REA 是裁判与工具，不是调度者 |
| 不做动态/运行时分析 | 定位不变：静态只读 |

---

## §1 目标与验收指标

| 编号 | 目标 | 可测判据 |
|---|---|---|
| G-E1 | 反思/审计/方法论可被宿主调用 | `submit_rea_audit` / `get_rea_methodology` 通过 gateway 可达，返回统一信封 |
| G-E2 | 假设有可证伪契约 | 每条 Hypothesis 必含 `falsifier`，缺失即 `gate=reject` |
| G-E3 | 裁判唯一准入 | PoE `gate != pass` 的假设不得进入认知写入列表 |
| G-E4 | 语料分层 | replay_pool 按 `process_log / project_analysis / external_case` 分库；`source_label` 为空不计入案例数 |
| G-E5 | 外部源可评分 | Q3 打分结果过门禁后写入 `relevance_score`，`priority` 才有晋升路径 |
| G-E6 | 改造方案可验收 | 每条 `adapt_plan` 条目带 `evidence_ref` + 回滚点 + 验收命令 |
| G-E7 | 成本可控 | 单次生成输入 ≤8k / 输出 ≤2k token；超限降级模板并标 `degraded=true` |
| G-E8 | 认知边界不破 | 只有 observation/derivation 可写 B 级；inference 写 C；unknown/hypothesis 不写 |

---

## §2 总体设计

### 2.1 三层职责（关键约束：LLM 不在 33 内）

```
宿主 LLM（任意模型）
   │  ① 读结构：MCP analyze/trace/compare/get_rea_snapshot（已有）
   │  ② 提假设：Hypothesis[]（本 SPEC 新增契约）
   ▼
33-REA（裁判层，零 token）
   │  ③ 取证：evidence pack（静态事实 + 回放池案例）
   │  ④ 打分：PoE gate（pass / review / reject）
   │  ⑤ 出方案：adapt_plan（只出方案，不改代码）
   ▼
35-认知系统（记忆层）
      ⑥ 只接收过 gate 的结论，按 SPEC-D §2.6 等级映射写入
```

**为什么这样分工**：模型擅长提假设、不擅长判定真伪；33 的 import 图、依赖环、PoE 分、回放重放是确定性的。把两者对调（让模型当裁判）会重新引入漂移，这正是 SPEC §0 要解决的问题。

### 2.2 Hypothesis 契约（解决 P-07）

```json
{
  "hypothesis_id": "H-20261111-001",
  "claim": "3.1 前端的 12 个 zustand store 可通过 slice 合并为 5 个，减少 40% 跨 store 订阅",
  "target_refs": ["src/stores/index.ts", "src/stores/cartStore.ts"],
  "expected_effect": "订阅路径 -40%，首屏 store 初始化 <120ms",
  "falsifier": "若合并后任一 store 出现循环依赖，或 RSC 边界报错，则假设为假",
  "cost": {"tokens_in": 3200, "tokens_out": 800, "files_touched": 12},
  "level": "inference"
}
```

规则：
- `falsifier` 缺失 → 直接 `reject`，不进入打分（不可证伪即不可评审）。
- `target_refs` 必须能对上静态图节点，否则 `known_gaps` 标注"未定位"并降为 `review`。
- `level` 由 33 侧按证据来源重算，不信任模型自报。

### 2.3 PoE 裁判接线（解决 P-06）

复用 [ai_audit.py](./core/ai_audit.py#L29-L44) 现有公式与阈值，**不新增权重**：

| 假设来源 | 补充证据 | 门禁 |
|---|---|---|
| 静态结论（已有） | Evidence 链 | 原逻辑不变 |
| LLM 假设 | 假设 → 静态复核（target_refs 是否存在于图）→ 回放池是否有同类案例 | `poe_score ≥ 0.8 且 evidence_chain ≥ 0.7` 才 pass |
| 无任何复核证据 | — | 最高 `review`，禁止 pass |

`review` 的处置：允许写入认知为 **C 级**（假设级），不得作为开发依据。

### 2.4 语料分层（解决 P-03）

| 类型 | 定义 | 现有量 | 处置 |
|---|---|---|---|
| `process_log` | 验收/提交/文档同步/认知记录轮次 | ≈15,580 | 迁至 `replay_pool/_process/`，**不计入**方法论统计 |
| `project_analysis` | 对我方仓库的静态分析树 | 372（ts）+ 少量 | 保留，供回归对比 |
| `external_case` | 外部项目解析树 | ≈140 | 保留，供借鉴；`source_label` 必填 |

迁移为一次性脚本 + 校验：`source_label` 为空且 analyzer 属于流程类 → `process_log`；否则保留并补标签。

### 2.5 MCP 工具面扩展（解决 P-01）

| 工具 | 类型 | 说明 | engineer 白名单 |
|---|---|---|---|
| `submit_rea_audit` / `poll_rea_audit` | 两段式 | 输入 Hypothesis[]，输出 PoE 打分 + gate + 理由 | 是（+2 → 12，需同步扩建白名单上限） |
| `get_rea_methodology` | 同步只读 | 返回方法论模板（≥2 项目门槛不变） | 是 |
| `submit_rea_adapt_plan` / `poll_rea_adapt_plan` | 两段式 | 输出 adapt_plan（只出方案） | 是 |

**注意**：白名单上限为 10（SPEC-D §8.2 已定），新增 4 个工具意味着必须同时决定"剔除哪些"或"调整上限"。**本 SPEC 建议不动上限**：把 `data_fetch`/`data_store_read` 从 engineer 移到单独 `data` 角色，engineer 保持 ≤10。此决策待评审确认（见 §9 Q1）。

### 2.6 adapt_plan 契约（解决 P-05）

只出方案，不含 diff。每条：

```json
{
  "plan_id": "A-001",
  "target_module": "3.1-FRONTEND/src/stores",
  "source_case": "replay_pool/external/<tree_id>",
  "change": "将 12 个 store 合并为 5 个 slice",
  "evidence_ref": [{"source": "replay_pool:xxx", "node": "n12", "confidence": 0.82}],
  "risk": ["跨 store 循环依赖", "RSC 边界序列化"],
  "rollback": "git revert <commit>；store 边界恢复原 12 文件",
  "acceptance": ["pnpm tsc --noEmit", "pnpm test stores", "首屏 LCP 不回退 >10%"],
  "priority": "P1"
}
```

**硬性**：缺 `rollback` 或 `acceptance` 的方案不生成（直接丢弃并计 `known_gaps`）。

### 2.7 认知写入边界（解决 P-06 的下半段）

沿用 SPEC-D §2.6 映射，补充三条：

| 产出 | 可写等级 | 说明 |
|---|---|---|
| 静态 observation / derivation | B | 已有规则不变 |
| PoE `pass` 的 adapt_plan | B | 附 `evidence_ref` |
| PoE `review` 的假设 | C | 标注"假设级，需验证" |
| PoE `reject` / `unknown` / 无 falsifier | 不写 | 禁止污染记忆 |

### 2.8 Token 预算与降级（解决 P-08）

- 单次生成：`in ≤ 8,000`、`out ≤ 2,000`；超限先裁剪低置信证据，再不行降级模板并 `degraded=true` + `meta.reason`。
- 成本记账：每次假设生成记录 `{model, tokens_in, tokens_out, gate}` 到 `reflection_data/reports/llm_cost.jsonl`，供周度核算。
- 预算不达标不得静默继续（对齐 SPEC-D 反静默裁剪原则）。

---

## §3 分阶段实施

### P0 — 可见性与语料（本期必做）

| 任务 | 内容 | 验收 |
|---|---|---|
| T-E1 | replay_pool 三类分层迁移脚本 + `source_label` 强制 | 迁移后 `_process/` 树数 ≈15,580；方法论统计只读另外两类 |
| T-E2 | 暴露 `submit/poll_rea_audit`（先只接既有 PoE，不接 LLM） | 工具可达；对样例 Hypothesis 返回 gate + 理由 |
| T-E3 | 暴露 `get_rea_methodology` | 无 ≥2 项目时返回空 + `known_gaps`，不报错 |
| T-E4 | RED 测试：假设缺 falsifier → reject；无复核证据 → 最高 review | 测试先行，红转绿 |

### P1 — 裁判闭环与改造方案

| 任务 | 内容 | 验收 |
|---|---|---|
| T-E5 | `submit/poll_rea_adapt_plan` | 缺 rollback/acceptance 的方案被丢弃并记 `known_gaps` |
| T-E6 | Q3 价值评分接口（LLM 打分结果必须过 gate 才写 `relevance_score`） | 未过 gate 的分数不落库 |
| T-E7 | 假设→静态复核（target_refs 对齐图节点） | 对齐失败降为 review 并标注 |

### P2 — 成本与自动化

| 任务 | 内容 | 验收 |
|---|---|---|
| T-E8 | token 预算 + 成本记账 | 超限降级可复现，`llm_cost.jsonl` 有记录 |
| T-E9 | 过 gate 结论自动 `record` + `verify` | 依赖认知写入开启（当前被 `COGNITIVE_MCP_WRITE_ENABLED` 拦截） |
| T-E10 | SKILL 侧补"假设生成 → 送审 → 只采纳 pass"步骤 | 与 SPEC-D 双保险对称 |

---

## §4 硬约束

1. **禁止**在 33-REA 内核引入模型 SDK、API key 或任何网络模型调用；模型只在宿主侧。
2. LLM **只能**产出 `Hypothesis` / `AdaptPlan`，**禁止**直接产出补丁、diff 或修改文件。
3. 每条假设**必须**含 `falsifier`；缺失即 `reject`，不进入打分。
4. PoE gate 是唯一准入；`reject` 的结论**禁止**写入认知系统。
5. replay_pool **必须**三类分库；`source_label` 为空**不得**计入案例数。
6. `adapt_plan` **必须**带 `evidence_ref` + `rollback` + `acceptance`，缺一不生成。
7. token 预算超限**必须**降级为模板并标 `degraded=true`，**禁止**静默超支。
8. 新增工具**必须**先登记 `mcp_capabilities.yaml` 再上线；角色白名单**不得**突破 10。

---

## §5 回滚边界

- 代码改动集中在：`core/reflection/`（裁判接线）、新增 `core/hypothesis.py`、`dsh_nodes.py`（新节点）、`mcp_shells/l0_rea/server.py`（工具定义）、注册表与 profile 若干条。
- 数据改动：`replay_pool` 分层迁移可逆（`_process/` 目录原样搬回）。
- 回滚方式：`git revert`；既有 analyze/trace/compare/snapshot 四类工具零改动，回滚不影响 SPEC-D 已落地能力。
- `llm_cost.jsonl` 为纯产物，删除不影响正确性。

---

## §6 风险

| 风险 | 影响 | 对策 |
|---|---|---|
| LLM 假设看似合理但不可证伪 | 累积噪音 | `falsifier` 必填 + 缺失直接 reject |
| 用模型给模型打分（自评虚高） | 门禁失效 | 打分只看静态复核/回放证据；模型自评分不参与 PoE |
| 语料迁移误删案例 | 方法论产出丢失 | 迁移脚本 dry-run + 计数比对 + 目录可回搬 |
| adapt_plan 被当成任务书直接执行 | 未验证改造落地 | SKILL 强制"仅 pass 且人工确认后执行" |
| token 成本失控 | 预算超支 | 输入输出双上限 + 超限降级 + 成本台账 |
| 认知写入仍被策略拦截 | T-E9 无法闭环 | 与 SPEC-D 同因；开启 `COGNITIVE_MCP_WRITE_ENABLED` 前 T-E9 挂起 |

---

## §7 与既有 SPEC 的关系

| 文档 | 关系 |
|---|---|
| SPEC-33-D | 本 SPEC 在其工具面上扩展 audit/methodology/adapt_plan；角色白名单规则沿用（≤10） |
| SPEC-33-反思层 | 裁判复用其 replay 池与 critic loop，不改其阈值 |
| SPEC-33-输出场景-意图系统 | `assemble_spec` 的"第二段 LLM 生成"由本 SPEC 的 Hypothesis 契约承接；模板保留为 fallback |
| SPEC-33-外部真实源接入 / 自动沉淀流水线 | 本 SPEC 落实其 Q3（语义相关性评分）并加门禁 |
| SPEC-33-45条外部源评估 | 其"LLM 评分阻塞注入"的取舍由本 SPEC §2.3 门禁替代 |
| 3.1 SPEC-A/B/C | adapt_plan 可产出前端改造方案，但执行归 A/B/C 的落地流程 |
| COLLABORATION-CONTRACT v1.6 | 认知写入治理以其为准；本 SPEC 不改写入协议 |

---

## §8 落地进度

| 任务 | 状态 | 证据 |
|---|---|---|
| T-E1 replay_pool 语料三类分层 | ✅ 已完成（2026-11-11 apply + 写入侧路由） | `scripts/migrate_replay_pool_layers.py`：实迁 14,965 棵到 `_process/`（internal 16,601 → 1,636，计数守恒），复扫残留 `process_log` = 0；external 137 棵且 `source_label` 缺失 0（缺失不计入案例数，G-E4）；`ReplayPool` 实测 `eval_ready=True`；抽样回读 5 棵可解析 + `--rollback` 可整体回搬。**写入侧**：`AnalysisRecorder.commit` 用 `is_process_tree` 判定后置 `layer="process"`，`ReplayPool.save` 按 `layer` 落 `_process/`（`load` 可读、`list_trees` 排除）；直接 `pool.save`（seed/合成语料）不自动路由，避免做梦语料被搬走。`run_l1_loop` 已带 `task_type=l1_loop` 自动生效；apply 后复扫 `process_log=0`（internal 由 1,674 增至 1,729 均为架构树）；写入侧 7 + 迁移 5 = 12 passed，全量 512 passed / 0 failed |
| T-E2 Hypothesis 契约校验 | ✅ 已完成 | `core/hypothesis.py::validate_hypothesis`（缺/笼统 falsifier 均 reject） |
| T-E3 PoE 门禁与静态复核 | ✅ 已完成 | `audit_hypothesis(es)` 复用 `core/ai_audit` 公式；无命中封顶 review；`.py`/`.ts` 扩展名归一（Python 图节点是模块名） |
| T-E4 认知写入边界 | ✅ 已完成 | `build_write_hint`：pass→B / review→C / reject 与 unknown 只给 skip |
| 工具暴露 | ✅ 已完成 | `S33_rea_audit` 增 hypotheses 分流；新增 `get_rea_methodology`；壳新增 `rea_audit` / `get_rea_methodology`（同步只读）；`mcp_capabilities.yaml` 已登记 9 工具 |
| 角色重组（Q1 裁决） | ✅ 已完成 | engineer = 9 REA + recall（10 满额）；新增 `data_reader` = data_fetch/data_store_read/recall |
| T-E5 adapt_plan 契约与工具 | ✅ 已完成 | `core/adapt_plan.py`：缺 `evidence_ref`/`rollback`/`acceptance` 即丢弃并计 `known_gaps`；`S33_rea_adapt_plan` 节点 + 壳 `submit/poll/cancel_rea_adapt_plan`（每壳 15 工具，engineer 白名单仍 10）。`tests/test_t_e5_adapt_plan.py` 9 passed |
| T-E6 Q3 价值评分接口 | ✅ 已完成 | `core/relevance.py`：仅 `gate=pass` 写 `relevance_score`；未登记/越界/未过 gate 一律拒绝并计 gaps；`S33_rea_score_sources` 节点，落库为原子写、损坏文件不覆盖。`tests/test_t_e6_relevance.py` 5 passed |
| T-E7 假设→静态复核收口 | ✅ 已完成 | 复核能力由 `core/hypothesis.py` 的 `resolve_target_refs` + `audit_hypothesis` 承担（目录级 ref、扩展名归一、无命中封顶 review），任务级用例见 `tests/test_spec_e_hypothesis.py`（falsifier 缺失 reject / 全命中 derivation / 零命中 review / 部分命中不 pass） |
| T-E8 token 预算 + 成本记账 | ✅ 已完成 | `core/llm_budget.py`：in≤8000 / out≤2000，超限 `degraded=true` + `degrade_to_template`；`reflection_data/reports/llm_cost.jsonl` 逐次追加（model/tokens/gate/degraded/ts）；`S33_rea_cost_ledger` 节点 |
| T-E9 过 gate 自动回写 | ✅ 已完成（挂起语义） | `core/cognitive_writeback.py`：pass→B / review→C / reject·unknown·无 falsifier→不写；`COGNITIVE_MCP_WRITE_ENABLED` 未开启时 `status=suspended` 且保留 record+verify 载荷，禁止伪造已写入；`S33_rea_writeback` 节点 |
| T-E10 SKILL 侧补流程 | ✅ 已完成 | [dream-rea-architecture-query/SKILL.md](../.trae/skills/dream-rea-architecture-query/SKILL.md) §2.1「假设生成 → 送审 → 只采纳 pass」四步 + 三条铁律 |

> **T-E1 写入侧（已收口）**：`ReplayPool.save` 现按 `task_type=l1_loop` 或 `analyzer ∈ {acceptance_gate, code_commit, doc_sync, cognitive_record}` 路由到 `_process/`；`list_trees()` 只扫 internal/external，`load()` 可读 `_process`。常量与迁移脚本共用（`PROCESS_ANALYZERS`/`PROCESS_TASK_TYPES`），杜绝两套口径漂移。

**验收实测（2026-11-11）**

- `python3 -m pytest tests -q`（cwd=33-REA逆向解析工程）：312 passed；`ruff check core tests dsh_nodes.py`：All checks passed。
- `python3 -m pytest mcp_shells/l0_rea/test_l0_rea_server.py -q`：10 passed。
- `validate_mcp_registry.py`：10 存量壳 / 51 active 工具 / 上限 80 ✅。
- 冷启动 `l0_gateway --role engineer`：10 工具，含 `rea_audit` / `get_rea_methodology`；`eval_analyze` → `forbidden`。
- 冷启动 `l0_gateway --role data_reader`：3 工具（`data_fetch` / `data_store_read` / `recall`）。
- 端到端：`rea_audit(target=mcp_shells/l0_rea, hypotheses=[H-1 … target_refs=["server.py"]])` → `gate=pass` / `poe_score=0.84` / `level=derivation` / `resolved_refs=["server.py"]`。

**与设计的偏差（需知悉）**

1. `rea_audit` 落为**同步只读**工具，而非 SPEC §2.5 的两段式 submit/poll。理由：单目录静态分析在 0.3s 量级，无长任务必要；若后续接入大目录可再拆。
2. 首版 Python 假设全部落到 review（`server.py` 无法命中模块节点 `server`），已补扩展名归一修复并加回归用例 `test_python_ext_ref_resolves_to_module_node`。
3. 认知写入仍被策略拦截（`scope_denied`，`COGNITIVE_MCP_WRITE_ENABLED != true`），故 `cognitive_hint` 目前只产建议、由宿主决定是否落库。

---

## §9 开放问题（需评审决策）

| # | 问题 | 建议 |
|---|---|---|
| Q1 | engineer 白名单已满 10，新增 4 个 REA 工具如何安排？ | ✅ 已裁决并落地：`data_fetch`/`data_store_read` 迁到 `data_reader` 角色，engineer = 9 REA + recall |
| Q2 | 假设生成由谁触发？ | 建议宿主显式调用（模型自主判断"需要假设"），不做定时轮询 |
| Q3 | `adapt_plan` 是否允许指向 3.1 前端？ | 允许出方案，执行必须走 SPEC-A/B/C 流程，禁止 REA 直接改文件 |
