# SPEC-G: 反思进化与分层自更新 — 从参数演化到能力演化

> 版本：v0.4.3
> 日期：2026-11-12
> 状态：🟡 部分落地（ADR-001 脑暴出关已灰度；L2-8B 灰度部署骨架开工，默认关闭 + 影子先行）
> 变更（v0.4.2 → v0.4.3）：L2-8B 开工——新增 `core/evolution/deploy_gate.py`（mode off/shadow/auto、影子成功≥3 才允许 auto、健康检查/回滚演练/部署窗口/flock+pidfile/数据迁移人工闸门/失败冻结 7 天）、`scripts/rollback_deploy.sh`（`--env gray` / `--drill` / 目录锁 / 留痕）、`scripts/deploy_gray.py` 调用入口；生产自动部署仍为非目标
> 变更（v0.4.1 → v0.4.2）：① 吸收同行评审 M1–M5：新增 **L2-9 stateful 禁令**、**L2-10 held-out 独立性**、**L2-11 观察期统计功效 + BH-FDR**、**L2-12 change_id 归因契约**；② 新增 **§2.11.8 权限切分与发布治理**；③ 新增 **§2.11.9 测量、数据与审计契约**；④ 门禁 3、7 强化；⑤ 硬约束补第 21–26 条；⑥ 任务补 T-G16/T-G17
> 变更（v0.4.0 → v0.4.1）：① 新增 **L2-7 自动合入边界**（只合 `evo/*`，main 保护不放松）；② 新增 **L2-8 部署分层 A/B/C**，明确「生产自动部署=非目标」；③ 新增 §2.11.7 部署边界；④ §4 硬约束补第 19-20 条；⑤ 第 18 条按 ADR-001 实况更新
> 变更（v0.3.0 → v0.4.0）：① 标题从「策略晋级」扩为「分层自更新」；② 新增 **L1/L2/L3 三层变更分级**，L2 允许大模型研发代码、L3 只出 ADR/SPEC；③ 新增**迭代案例自动入库**（结构化 Case + 完成流程硬门禁）；④ 新增**调研参考账本**（外源基因 + license/适配度免疫）；⑤ 研发流水线绑定既有架构：**DreamOS（路由/编排）→ LobeHub 脑暴（双链提案）→ DSH 子 Agent（并行研发）→ L0 能力矩阵（REA/data/cognition 取证）→ SPEC-G 门禁（沙箱/影子/观察）**
> 归属：33-REA逆向解析工程（反思层）+ 4-MEMORY（认知账本）+ 47-MCP（触发通道）+ 1-ARCHITECTURE（DreamOS/DSH）+ 52-lobehub协议集成（脑暴）
> 上游：SPEC-33-D（MCP 接入）、SPEC-33-E（假设与 PoE 裁判）、SPEC-33-F（能力增强）
> 依赖：SPEC-F `T-F03`（评测 harness）、`T-F06`（约束引擎）、`T-F11`（度量门禁）

---

## §0 背景与结论

### 0.1 体检结论

闭环已建成 4 段，**断在两端**：输入端没有「使用后果」，输出端没有「策略晋级」。当前系统会记事、会反思，但**不会改自己的架构**。

| 环节 | 现有实现 | 成熟度 |
|---|---|---|
| 观察 | `analyze / trace / compare` + Evidence | 4/5 |
| 假设 | SPEC-E `rea_audit` + `CriticProposal`（[critic_loop.py](../33-REA逆向解析工程/core/reflection/critic_loop.py)） | 3/5 |
| 裁判 | PoE gate + `DreamingLoop.replay_objective` / hypervolume（[dreaming.py](../33-REA逆向解析工程/core/reflection/dreaming.py#L97-L182)） | 4/5 |
| 保留 | `record/verify` + `distill_scheduler` + `bayesian_memory_updater` + `auto_promotion` + `TrainingCaseStore` | 4/5 |
| **案例入库** | 靠 agent 自觉 `record`，写的是自然语言 | **1/5** |
| **后果回传** | **无**（全仓无 outcome/adoption 采集） | **0/5** |
| **策略晋级** | 有 critic/verifier/gardener 调度器，无 held-out、无影子、无回滚门禁 | **2/5** |
| **功能/架构研发** | 人工触发 SKILL，无自动探索与研发流水线 | **1/5** |

### 0.2 五条断点（证据）

1. **记忆改不了行为**：认知库存的是经验文本，`recall` 只影响下一次提示，不改规则、不改权重、不改 schema。
2. **`verify(success)` 无自动来源**：成功与否靠 agent 主观填，贝叶斯置信度涨的是「agent 的自信」而非「事实的验证」。
3. **案例不可计算**：迭代经验以自然语言散落在认知库，无法聚类成模式，涌现永远空转。
4. **无 held-out 集**：SPEC-F T-F03 未落地，任何「升级」都不可证伪。
5. **写入被关**：`COGNITIVE_MCP_WRITE_ENABLED != true`，闭环今天物理上合不上。

### 0.3 演化工程映射

| 演化机制 | 本系统对应物 | 现状 |
|---|---|---|
| 变异 | hypothesis / PlanCard / ADR | ⚠️ 有，缺「预期后果」 |
| 选择 | PoE gate + held-out + 影子运行 | ⚠️ 仅离线 |
| 保留 | Case 账本 + 认知分层 + 蒸馏模板 | ⚠️ 未结构化 |
| 遗传 | Policy 账本 + 代码提交 | ❌ 无版本化晋级 |
| 适应度 | 采纳率 / 回滚率 + recall@k / 延迟 | ❌ 全缺 |
| 生态位 | 每工程架构基线快照 | ⚠️ 有快照，无漂移概念 |
| 红皇后 | 阈值随基线漂移的度量门禁 | ❌ 缺（SPEC-F T-F11） |

> **核心判断**：只有 `Policy` 或 `Code` 发生变更，才算「升级」。当前产出停在 Evidence 与文本记忆。

### 0.4 分层自更新与既有架构的映射（v0.4.0 新增）

本 SPEC 不新建研发体系，而是把**已有五层接成一条可证伪的闭环**：

| 角色 | 既有组件 | 在本 SPEC 中的职责 |
|---|---|---|
| 编排 | [node_registry.py](../1-ARCHITECTURE/dreamos/registry/node_registry.py)（DreamOS 节点唯一真相源）、[router.py](../52-lobehub协议集成/orchestrator/router.py) | 把 gap/proposal 路由到对应链与节点 |
| 脑暴 | [brainstorm_orchestrator.py](../52-lobehub协议集成/orchestrator/brainstorm_orchestrator.py)（双链 N 张 → 确定性收敛 → T1-T4 争议升级 Debate） | **组织级**提案多样性（side A/B 模型与证据路径强制不同） |
| 研发 | DSH `SubagentOutput` 契约（[subagent_types.py](../1-ARCHITECTURE/dream-harness-bridge/packages/python-server/subagent_types.py)）+ technical/macro/flow/... 子 Agent | 并行实现候选，统一输出 `signals/charts/evidence_refs/artifact_uri` |
| 取证 | L0 能力矩阵：`l0.rea.mcp`（代码事实）、`l0.data.mcp`（数据）、`l0.cognition.mcp`（记忆） | 研发前取证、研发后复核，禁止无证据改动 |
| 裁决 | 本 SPEC §2.7/§2.7.1/§2.8 门禁 | 沙箱 → 影子 → 观察期 → 晋级/回滚 |

**关键现实**：脑暴编排器当前是 **shadow 模式**（`executed` 恒为 `false`，不执行 DreamOS 执行链）。启用 L2 的前提是先让它「出关」——而这次出关本身也要走一遍本 SPEC 的门禁。这是自进化系统典型的**自举问题**，必须显式承认并单独处理（见 §2.11.6）。

### 0.5 非目标

1. **不让 LLM 直接写 main**：任何代码变更都必须经过分支 + 门禁合入。
2. **不做无证据的自动上线**：auto 必须八门禁全绿 + 已积攒 ≥30 条同域**有效** outcome（且 ≥24h，见 §2.11.9）。
3. **不做跨模块自动重构**：跨模块属 L3，只出 ADR/SPEC，不写代码。
4. **不做线上埋点平台**：遥测只落本地 JSONL。
5. **不引入常驻服务**：触发检查在 MCP 调用时惰性执行。
6. **不做生产自动部署**：自动合入 ≠ 上线；生产变更仍走人工窗口或独立 ADR（见 §2.11.7）。

---

## §1 目标与验收指标

| 目标 | 内容 | 验收指标 |
|---|---|---|
| G-G1 | 后果回传 | 每次假设可关联 `outcome{accepted, tests_pass, reverted}`；`verify` 只接受带 outcome 的调用 |
| G-G2 | 策略账本与晋级门禁 | 每次 Policy 变更都有 `policy_id` / 前后 sha256 / 八门禁逐项结论 / 回滚点 |
| G-G3 | 涌现回灌 | 方法论模板可产出候选规则，经门禁后进入 `rea_rules.yaml` |
| G-G4 | 使用遥测 | 按 section 聚合的调用量 / 命中率 / 采纳率 / 预算命中 |
| G-G5 | 漂移守卫 | 度量相对基线超阈值即降级 `review` 并产出 Evidence |
| G-G6 | 独立 held-out | ≥100 条，按 section 分桶，30% 永久保留，每周轮换 10% |
| G-G7 | 触发与 LLM 评估 | 6 类触发器；提案模型 ≠ 评估模型；`confidence` 不作门禁 |
| G-G8 | 备份/沙箱/影子/回滚 | 沙箱三组全绿；影子按 section 达标；回滚 ≤60s 且覆盖记忆污染 |
| G-G9 | 双模晋级 | S3 + 八门禁全绿自动；无 AI 告警 + 人工；断路器生效强制 manual |
| G-G10 | 无 LLM 降级通道 | MCP 返回 `pending_actions`；TRAE 启动即感知 |
| **G-G11** | **迭代案例入库率** | **近 20 次迭代 100% 产生结构化 Case；字段完整率 100%** |
| **G-G12** | **调研参考可用性** | **每条 reference 含 license / stack_fit / adapt_cost；无 license 的不得进入候选** |
| **G-G13** | **分层变更合规** | **L1 全部走门禁；L2 100% 通过沙箱+影子；L3 100% 有 ADR+SPEC 编号** |
| **G-G14** | **研发闭环率** | **进入研发队列的 proposal，≥60% 在 4 周内产出可验收产物（代码/ADR/规则）** |

---

## §2 总体架构

### 2.1 四账本（v0.4.0：新增 reference）

```
Evidence 账本（事实）   reflection_data/evidence/*.jsonl
  └ analyze/trace/audit 的结论 + provenance + confidence + policy_id
Case     账本（经验）   reflection_data/cases/*.jsonl
  └ 每次迭代的结构化三元组（goal/hypotheses/changes/verification/outcome/lessons）
Policy   账本（策略）   policy/registry.json + policy/versions/<policy_id>.json
  └ 规则 / 权重 / SKILL，带版本、证据引用、回滚点
Reference 账本（外源）  reference/*.jsonl
  └ 调研项目与方案：source_url / license / stack_fit / adapt_cost / gap_id / evidence
```

**准入规则**：Case 与 Reference 可自动写；Policy 与 Code 必须过门禁。

### 2.2 四环 + 两闸门 + 一条研发链

```
Observe(REA) → Hypothesize(脑暴) → Judge(PoE + held-out + 影子) → Retain(Case/记忆)
     ↑                                                              │
     │                    Promote（L1 策略 / L2 功能 / L3 架构）     │
     └──────────────────────────────────────────────────────────────┘
                              ↑
        DreamOS 路由 → LobeHub 双链脑暴 → DSH 子 Agent 研发 → L0 取证 → 门禁
```

### 2.3 触发阈值（`rea_evolution.yaml`）

```yaml
version: 2            # v0.4.0 升版：新增 research gap 与 case gap 触发器
window_days: 7
triggers:
  repeat_failure:        { min_occurrences: 3 }
  hypothesis_overturned: { min_consecutive: 2 }
  memory_saturation:     { min_count: 20, min_idle_days: 30 }
  metric_drift:          { cycles_pct: 30, god_components_pct: 30, fan_out_pct: 30 }
  coverage_gap:          { min_occurrences: 5 }
  adoption_drop:         { pct: 20 }
  capability_gap:        # 调研/对标发现的缺失能力（v0.4.0）
    min_references: 2    # 至少 2 个外部项目证明该能力普遍存在
    min_relevance: 0.6   # stack_fit 加权相关度
  case_pattern:          # 同类案例反复出现（v0.4.0）
    min_cases: 5
    min_distinct_iterations: 3
budget:
  max_proposals_per_week: 3
  max_policy_changes_per_week: 1
  max_l2_changes_per_week: 2
  max_explorations_per_week: 2
```

### 2.4 LLM 提案与评估（强制分离）

**提案（proposer）**：

```
输入：触发证据 + Evidence 摘要 + 最近 Case + Policy 片段（≤8KB）
输出：proposal.json
  {proposal_id, level: "L1|L2|L3", trigger, claim, expected_effect,
   blast_radius, change_draft, falsifier, proposer_model, created_at}
```

**评估（evaluator，必须是另一个模型或不同上下文）**：

```
输入：proposal.json（不含 proposer 推理过程）+ 原始 Evidence
输出：evaluation.json
  {proposal_id, verdict, rationale, confidence, evaluator_model}
```

**约束**：

1. `proposer_model != evaluator_model`，缺失即 `hold`。
2. `confidence` 只记录，不入任何门禁。
3. proposal 必须自带 `falsifier`。
4. `verdict=reject` 直接归档。

### 2.5 改进执行流水线（状态机）

```
proposed → evaluated → sandboxed → shadowed → qualified → promoted
                │           │            │           │
                ↓           ↓            ↓           ↓
              hold    sandbox_failed  shadow_failed  quota / breaker_open

promoted → observing ──(≥30 条有效 outcome 且 ≥24h，指标不降)──→ confirmed
                └────(指标下降/错误率上升)────→ rolled_back
manual：qualified → notified → (人工命令) promoted
```

L2/L3 在 `sandboxed` 前多一段 `dev`（子 Agent 研发），产物进入同一状态机。

### 2.6 备份、污染回滚与自动回滚

**备份**：

```
policy/versions/<policy_id>/           # L1
  backup/<relative_path> + manifest.json{path,sha256_before,sha256_after} + rollback.sh
branches/<change_id>/                  # L2：独立分支 + 提交前 sha
  manifest.json + revert.sh
```

- L1 打 tag `policy-<id>-pre`；L2 从 `main` 切 `evo/<change_id>` 分支
- 回滚入口：`rollback_policy.py --id` / `rollback_change.py --id`

**污染回滚**：

```
1. 按 policy_id / change_id 检索生效期间写入的 Case / Evidence
2. 标记 tainted=true（不删除，保留审计）
3. recall 对 tainted 降权 ×0.3，且不作规则候选依据
4. 由 tainted Case 触发的 verify 升级回退到上一等级
5. 产出 pollution_report.json
```

**自动回滚**：观察期（≥30 条有效 outcome 且 ≥24h；同期多变更已做 BH-FDR 校正）held-out 下降或错误率上升 → 还原 + 污染回滚 + 飞书通知。**stateful 变更另需状态恢复脚本，否则不得进入自动通道**（§2.11.4 L2-9）。

### 2.7 沙箱验证（三组）

| 组 | 内容 | 通过条件 |
|---|---|---|
| A 目标分析 | 2 个真实工程 analyze/trace（只读副本） | 无异常、预算命中、无 degraded |
| B 全量回归 | REA + MCP 壳 + 认知工具测试；L2 另加 tsc/ruff/pytest | 全绿，0 失败 |
| C held-out 评测 | 按 section 分桶 | 对应桶 recall@10 / precision 不降 |

**隔离**：`sandbox/<change_id>/` 只读工作区；禁止写认知库、禁止 git push、禁止外网。

### 2.7.1 影子运行（按 section 计数 + 归因判定）

```
门槛（按受影响 section 计数）：
  - 该 section 真实调用 ≥20 次且 ≥24h
  - held-out 对应桶：recall@10 不降、precision 不降
  - degraded 不高于前 7 天均值
  - P95 延迟增幅 ≤20%

差异判定（不设幅度上限）：
  - 抽 ≤20 条差异逐条归因
  - 归因到 expected_effect 范围 ≥80% → pass
  - 出现范围外差异 → fail
```

L2 的影子是**代码级并行**：`evo/*` 分支部署到影子通道，与在线版本同输入对跑。

### 2.8 双模晋级控制器（八门禁）

| # | 门禁 | 校验方式 |
|---|---|---|
| 1 | 备份完整 | manifest 存在且 sha256 全部可复算 |
| 2 | 沙箱三组全绿 | `sandbox_report.overall == pass` |
| 3 | 回滚演练通过 | `rollback_drill == pass`（L2 为 revert 演练；**stateful 变更须含数据/状态恢复演练**） |
| 4 | 影子期达标 | `shadow_report.overall == pass`（按 section） |
| 5 | 提案/评估分离且可证伪 | 模型不同 + falsifier 非空 + verdict=improve |
| 6 | 变更幅度合规 | L1：1 规则/1 参数/1 SKILL；L2：≤3 文件/≤200 行/单模块 |
| 7 | 证据充分 | 该 section ≥30 条**有效** outcome 且 ≥24h；held-out 对应桶 ≥20 条；同期多变更需 BH-FDR 校正（q≤0.1） |
| 8 | 配额与断路器 | 周配额未超；`breaker.json` 未开 |

> v0.4.2 强化：门禁 3、7 吸收 stateful 回滚、观察期统计功效与多重比较校正；未新增第 9/10 条，保持「八门禁」命名与全文档引用一致。审计与数据契约见 §2.11.9。

**无 AI 模式**：到 `qualified` 后 `notified`，飞书告警，人工 `approve_policy.py` / `approve_change.py`；proposal 不过期丢弃。

### 2.8.1 三段式启用

| 阶段 | 模式 | 进入条件 | 退出条件 |
|---|---|---|---|
| S1 数据积累 | manual，不启影子 | P0 完成 | 某 section ≥30 条有效 outcome 且 ≥24h |
| S2 影子校准 | manual + shadow | S1 退出 | 连续 5 次门禁建议与人工决定一致 |
| S3 自动 | auto（前 3 次留 24h 否决） | S2 退出 + 断路器未开 | 断路器触发回落 S2 |

`policy/stage.json` 记录阶段；降级立即生效，升级需 `advance_stage.py`。

### 2.8.2 断路器

```
触发：连续 2 次 auto 晋级的 observing 期被 rolled_back
动作：breaker.json open=true，冻结 auto 7 天；飞书告警；阶段回落 S2
恢复：人工 reset_breaker.py（必须填原因，写 audit log）
```

### 2.9 无 LLM 降级：MCP 感知与用户提示

1. 触发照常计算，proposal 落 `policy/proposals/pending/`
2. `analyze / trace / rea_audit` 信封带 `pending_actions[]`
3. `get_rea_snapshot(section=evolution)` 返回待办（含 diff 与回滚点）
4. TRAE 的 `dream-self-iteration-workflow` / `dream-completion-evolution-workflow` 启动即读，非空则提示
5. 飞书告警（manual 必发；auto 仅通知）

### 2.10 防退化五原则

1. 提案 / 评估 / 门禁三者独立。
2. 单步小改（L1 每周 1 次，L2 每周 ≤2 次）。
3. held-out 30% 永久保留。
4. C 级记忆不进候选池。
5. 证据不足不升级。

---

## §2.11 分层变更与研发流水线（v0.4.0 核心新增）

### 2.11.1 三层变更

| 层 | 对象 | 自动化程度 | 人工介入 | 门禁 |
|---|---|---|---|---|
| **L1 策略** | 规则 / 权重 / SKILL | S3 八门禁全绿自动 | 无（30% 抽查） | §2.8 |
| **L2 功能** | 单模块内代码、新参数、新 section | LLM 研发 → `evo/*` 分支 → 沙箱 → 影子 → 自动合并 | 每周抽审 1 次 | §2.8 + §2.11.4 |
| **L3 架构** | 跨模块、依赖方向、schema、公共契约 | 只出 **ADR + SPEC 草案** | **必须评审**（AI 评审 + 人终审） | §2.11.5 |

**分级规则**（由 `classify_change.py` 确定性判定，LLM 不得自定级）：

```
触及 ≥2 个编号目录 / 改公共契约 / 改 schema / 改依赖方向 / >3 文件或 >200 行 → L3
单模块内且 ≤3 文件 ≤200 行且不改对外契约 → L2
只改规则/权重/SKILL → L1
无法判定 → 默认 L3（保守）
```

### 2.11.2 五段流水线（组件绑定）

```
① 路由    DreamOS router.route_intent + NodeRegistry
          输入：gap / proposal；输出：目标链、受影响节点、预算
              ↓
② 脑暴    brainstorm_orchestrator（side A: 3.1 /api/agent/plan；side B: DreamOS /api/v1/intent）
          N 张 PlanCard → 确定性收敛 → 命中 T1-T4 才升级 Debate
          铁律⑤：两链 model 与 evidence_path 必须不同，否则 fail-closed
              ↓
③ 研发    DSH 子 Agent 并行（technical/flow/...，统一 SubagentOutput 契约）
          L2：产出代码 diff + 单测；L3：产出 ADR + SPEC 草案
              ↓
④ 取证    L0 能力矩阵复核：l0.rea 看结构影响面、l0.data 取真实数据、
          l0.cognition 查历史同类案例；无 Evidence 的改动直接打回
              ↓
⑤ 门禁    沙箱 → 影子 → qualified → 晋级/合并 → 观察期 → confirm / rollback
```

**产物契约**：每个 proposal 最终必须落 `research_artifact.json`（脑暴轨迹）+ `dev_artifact.json`（diff/ADR）+ `evidence_refs`（L0 取证 ID），三者缺一不得进入门禁。

### 2.11.3 双链脑暴 = 组织级的「提案/评估分离」

我们此前用「模型 A 提案、模型 B 评估」实现分离；LobeHub 双链提供了更强形态：

- **side A** 走 3.1 协议层，证据路径 `unified_search+recall`
- **side B** 走 DreamOS 意图层，证据路径 `dreamos.intent+registry`
- 两链各自发散 N 张 PlanCard，再做**确定性收敛**（非 LLM 投票）
- 仅当 T1-T4 争议触发（评分 gap、证据冲突等）才升级 Debate

这条链天然满足「生成与裁判分离」，且比单模型自我评估更难被 reward hacking。本 SPEC 的 §2.4 评估模型可直接复用 debate 的 adjudicator 输出。

### 2.11.4 L2 附加门禁（在八门禁之上）

| # | 条件 |
|---|---|
| L2-1 | 变更仅限单模块，≤3 文件 / ≤200 行 |
| L2-2 | 新增/修改的测试全部通过，且**新增测试覆盖新逻辑**；新增逻辑需 mutation score ≥60%，或 property-based / 差分测试证据 |
| L2-3 | 不新增外部依赖（新增依赖一律降级 L3） |
| L2-4 | 不修改公共契约 / schema / 依赖方向（否则降级 L3） |
| L2-5 | `dev_artifact.json` 含回滚脚本且演练通过 |
| L2-6 | 每周抽审 1 次已合并变更；抽审不通过 → 断路器 |
| L2-7 | 自动合入只允许目标分支 `evo/<proposal_id>`；CI 全绿后由 **CI 机器人**合并（编排器只发请求，不持有 push 凭据）；**main 保护规则不放松**，禁止直接 push main |
| L2-8 | 部署分层：A 自动合入（默认）→ B 自动部署到灰度（需健康检查 + 自动回滚）→ C 生产自动部署（**非目标**，须独立 ADR） |
| L2-9 | **stateful 变更禁止自动**：触及数据迁移、缓存、任务表、消息位点、外部存储状态时，必须人工 + 状态恢复演练 |
| L2-10 | **held-out 独立性**：人工构造、不进入任何 Agent 上下文、按季度冻结；同源生成或曾参与训练/提示的一律作废 |
| L2-11 | **观察期统计功效**：≥30 条有效 outcome 且 ≥24h；同期多变更用 BH-FDR（q≤0.1）校正；不满足则顺延观察 |
| L2-12 | **归因契约**：`change_id` 贯穿 CI→部署→运行时指标→outcome；变更日历 + 互斥观察窗，同 section 禁止并行 L2 |

**自动合入/部署的额外前置**（T-G1、T-G6 是必要条件但不充分）：

```
T-G1 outcome 回传 + T-G6 held-out≥20
  + L2-5 回滚演练通过 + 断路器可用
  → 阶段 A：自动合入 evo/*（CI 绿即合并，main 不放松）
  → 阶段 B：A 稳定 2-4 周 → 自动部署灰度（健康检查 + 自动回滚 + 部署窗口）
  → 阶段 C（非目标）：仅「无 DDL / 无 schema / 无 registry / 无定时任务 / 无有状态变更」的 L2，
                      且须独立 ADR + 24h 否决 + 一键回滚
```

部署侧必须具备（缺一不得开启任何自动部署）：健康检查（HTTP 200 + 核心链路冒烟）、一键回滚脚本且演练通过、部署窗口（避开交易时段与定时任务）、单实例重启的 flock + pidfile 校验、数据迁移闸门（含 DDL / schema / registry 变更一律人工）。

### 2.11.5 L3 出口（只出方案，不写代码）

L3 的唯一合法产物是 **ADR + SPEC 草案**：

```
decisions/ADR-<n>-<slug>.md
  - 背景与触发证据（引用 Case / Reference / L0 Evidence ID）
  - 候选方案 ≥2（来自双链脑暴）
  - 取舍理由与 PoE 评分
  - 影响面（模块、契约、迁移成本）
  - 回滚与灰度策略
  - 需要拆成的 L2 任务清单
```

ADR 通过人审后，按 SPEC-F/D 的既有流程立项，不再进入本 SPEC 的自动通道。

### 2.11.6 自举问题（必须显式处理）

脑暴编排器原为 `executed=false`（shadow 只记录 trace/outbox）。启用 L2 必须先让它执行 DreamOS 链，而这次「解锁」本身就是一次 L3 变更：

```
ADR-001「脑暴编排器出关」→ 人审 → 仅对 auditor 角色开放 execute
→ 灰度每周 1 次执行 → 观察期 → 提额须新增 ADR
```

**ADR-001 已通过（2026-11-11，灰度中）**，落地形态：

| 维度 | 灰度值 | 实现点 |
|---|---|---|
| 角色 | 仅 `auditor` | `live_policy.check_live_allowed` 的 role 门 |
| 路由 | `workers` / `debate` | route 白名单 |
| 额度 | 1 次/自然周 | `count_this_week` 读 append-only 账本 |
| 执行范围 | 仅 `decision.kind=dispatch` 胜方卡 | `_execute_live` |
| 失败处理 | 降级为 `execution.error`，**仍占预算** | `record_execution` 在异常分支也写 |

回退开关：`orchestrator/live_policy.json` 改 `enabled=false` 即回 shadow。提额/开放新角色须新增 ADR，不得改本 SPEC 自动放行。

ADR 正文：`52-lobehub协议集成/decisions/ADR-001-脑暴出关.md`。

**仍未解锁的部分**：L2 的「自动合入 + 自动部署」依旧关闭；当前只解锁了「执行已裁决的 PlanCard」这一跳。所有 L2 产物仍需 `dev_artifact` 人工合并，直到 T-G1（outcome 回传）与 T-G6（held-out）落地，并补齐 L2-5、断路器与部署侧能力（见 §2.11.4）。

### 2.11.7 部署边界（非目标清单）

1. **合入 ≠ 上线**：自动合入只产生可回滚的代码事实（`evo/*` 分支 + CI 绿），**不得触发任何部署**。
2. **生产自动部署 = 非目标**：生产变更仍走人工窗口或独立 ADR；本 SPEC 只批准「B 灰度自动部署」。
3. **禁止自动部署含 DDL / schema / 公共契约 / registry / 定时任务的变更，以及一切有状态变更**：一律人工。
4. **禁止自动部署交易链路**：交易域部署须经 27 治理审批。
5. **未演练不得开自动部署**：一键回滚脚本未演练通过、健康检查未覆盖核心链路时，自动部署开关必须保持关闭。
6. **部署失败即冻结**：自动部署触发回滚后，立即冻结 auto 7 天并回落 S2（与 §2.8.2 断路器同一动作）。

### 2.11.8 权限切分与发布治理（v0.4.2）

**三权分立**：编排器不得同时持有提案、合并、部署三类凭据。

| 权力 | 持有者 | 编排器可做什么 |
|---|---|---|
| 调度 / 提案 | orchestrator | 发起脑暴、生成 proposal、发出请求 |
| 合并 | CI 机器人账号（仅 `evo/* → main`） | **只能请求**，不得持有 push 凭据 |
| 部署 | 发布系统（`ops/deploy`） | **只能请求**，不得持有生产凭据 |

- 合并与部署请求必须携带 `change_id` + `proposal_id` + 门禁结论摘要；缺一拒绝。
- **分支生命周期**：`evo/*` 合并后由 CI 自动删除；未合并分支默认 14 天归档；每周校验与 main 的落后提交数，超阈值告警（阈值入配置，不写死）。
- **发布并发**：同一环境同一时刻只允许 1 个发布（分布式锁，TTL 可配）；锁未释放不得重入。
- **人工接管**：每个环境必须登记 owner 与 RTO/RPO；未声明者不得开启自动部署；冻结期内 owner 未响应则升级告警。
- **最小权限**：编排器、CI 机器人、发布系统使用独立凭据，任一失陷不得横向获取另两项权力。

### 2.11.9 测量、数据与审计契约（v0.4.2）

1. **单一事实源**：`ledger/events.jsonl` 为唯一事件源；Case / Evidence / Policy 只存 `change_id` / `policy_id` 引用 + 摘要，禁止各自复制完整正文。
2. **幂等**：outcome 写入键 = `(change_id, run_id, outcome_seq)`；重复回传覆盖不追加。
3. **change_id 贯穿**：一次 L2 变更从 proposal → `evo/*` 分支 → 合并 commit → 部署版本 → 运行时指标 → outcome 使用同一 ID；链路缺失的环节不得计入证据。
4. **schema 演进**：事件带 `schema_version`；升级走 expand-contract（先加字段、双写、切换、最后删旧），禁止原地改语义。
5. **审计链**：每条事件包含 `prev_hash` 形成哈希链；每日链头写入 Git 提交作为外部锚点，本地文件被改写可被检出；断链即冻结 auto。
6. **评估器冻结**：`evaluator_version` 固定并记录；评估器升级需先在历史 Case 上回归，一致率达标才可切换。
7. **held-out 治理**：人工构造、不进入任何 Agent 上下文、按季度冻结；换入换出记录在 `heldout_manifest.json`。
8. **测试强度**：L2-2 的 mutation score 由工具产出（如 `mutmut` / `cosmic-ray`）；无工具时以 property-based / 差分测试替代，并在 `dev_artifact.json` 声明。
9. **多重比较**：同一观察窗内 >1 个变更时，对主指标做 BH-FDR（q≤0.1）；未校正结果只能进 `hold`。
10. **归因隔离**：同 section 禁止并行 L2；无法隔离时用 switchback（时间交替）而非同时上线。

> 门禁对应关系：门禁 3 ← L2-9（stateful 状态恢复演练）；门禁 7 ← 本节第 2/3/6/9/10 条（幂等、change_id 贯穿、评估器冻结、BH-FDR、归因隔离）；门禁 8 ← 本节第 5 条（断链即冻结 auto）。L2-2 的测试强度见第 8 条。

---

## §2.12 迭代即案例（Case 契约与硬门禁）

### 2.12.1 Case 契约（结构化，非文本）

```json
{
  "case_id": "C-20261111-01",
  "iteration_id": "SPEC-33-G/T-G12",
  "goal": "功能目标（一句）",
  "hypotheses": [{"claim": "...", "falsifier": "..."}],
  "changes": {"files": 3, "loc": 120, "modules": ["33-REA"], "level": "L2"},
  "verification": {"tests": 42, "passed": 42, "duration_s": 31, "gates": ["sandbox", "shadow"]},
  "outcome": {"accepted": true, "reverted": false, "reviewer": "auto|human"},
  "defects": [{"desc": "...", "found_by": "shadow|heldout|human"}],
  "lessons": ["..."],
  "policy_id": "P-...|null",
  "evidence_refs": ["E-..."],
  "created_at": "ISO8601"
}
```

### 2.12.2 入库硬门禁

`dream-completion-evolution-workflow` 增加一步：

```
if not case_exists(iteration_id):
    FAIL("本次迭代未产生结构化 Case，不算完成")
```

- 与 `dream-acceptance-verify` 同级，属于**硬门禁**（不是 FAIL-OPEN）
- 字段完整率必须是 100%，缺字段即失败
- 写入后立即触发 `verify(outcome=...)`，不再依赖 agent 主观判断

### 2.12.3 从 Case 到涌现

```
Case 聚类（按 module × change_type × defect_type）
  → 出现 ≥5 条同类且跨 ≥3 次迭代 → 模式候选
  → MethodologyAbstractor 产出模板（需 ≥2 个项目/迭代的 Evidence）
  → 模板 → 候选规则（L1）或 ADR 候选（L3）
```

---

## §2.13 调研参考账本（外源基因的免疫）

```json
{
  "ref_id": "R-001",
  "source": "github|paper|blog|internal",
  "url": "https://github.com/...",
  "license": "MIT|Apache-2.0|GPL-3.0|unknown",
  "stack_fit": 0.0,
  "adapt_cost": "S|M|L",
  "capability": "PPR 相关性排序",
  "evidence": {"what": "...", "how_verified": "..."},
  "gap_id": "GAP-007",
  "usable": true
}
```

**准入**：

- `license=unknown` 或 GPL 系进入闭源产品 → `usable=false`，只可参考思路
- `stack_fit < 0.4` → 只可参考思路，不得直接移植
- 同一 `gap_id` 重复调研需命中缓存，不重复消耗探索预算
- 每条 Reference 必须附 `how_verified`，否则不算证据

---

## §3 分阶段实施

### P0 — 数据与案例地基（4 项）

| 任务 | 内容 | 依赖 | 验收 |
|---|---|---|---|
| T-G1 | outcome 回传：`verify` 只接受带 outcome 的调用 | 无 | G-G1 |
| T-G4 | 按 section 遥测（JSONL） | 无 | G-G4 |
| T-G6 | held-out ≥100 条、分桶、30% 保留池人工换入换出 + 季度冻结（L2-10） | T-F03 | G-G6 |
| **T-G12** | **Case 结构化契约 + 完成流程硬门禁 + 自动 verify** | 无 | **G-G11** |

### P1 — 可晋级与可研发（10 项）

| 任务 | 内容 | 依赖 | 验收 |
|---|---|---|---|
| T-G2 | Policy 账本 + 八门禁校验器 | T-G1, T-G6 | G-G2 |
| T-G7 | 触发引擎 + 双模型提案/评估 | T-G4, T-G5 | G-G7 |
| T-G8 | 执行器：backup / sandbox / shadow / 污染回滚 / 自动回滚 | T-G2 | G-G8 |
| T-G9 | 双模控制器 + 三段式阶段机 + 飞书 | T-G8 | G-G9 |
| T-G10 | 无 LLM 通道：`pending_actions` + `section=evolution` | T-G7 | G-G10 |
| T-G11 | 断路器 + 阶段回落 + 恢复审计 | T-G9 | 可演练 |
| **T-G13** | **Reference 账本 + license/适配度免疫 + gap 去重** | T-G12 | **G-G12** |
| **T-G14** | **三层分级器 + 研发流水线（DreamOS→脑暴→DSH→L0→门禁）** | T-G13, ADR-001 | **G-G13** |
| **T-G16** | **权限切分 + 发布治理**：三权分立、`evo/*` 生命周期、发布锁、owner/RTO 登记 | T-G14 | §2.11.8 可演练 |
| **T-G17** | **测量与审计契约**：change_id 贯穿、outcome 幂等、哈希链、评估器冻结、BH-FDR | T-G1, T-G4, T-G6 | §2.11.9 逐条可验 |

### P2 — 架构涌现（3 项）

| 任务 | 内容 | 依赖 | 验收 |
|---|---|---|---|
| T-G3 | 涌现回灌：模板 → 候选规则 | T-F06, T-G2 | G-G3 |
| T-G5 | 漂移守卫 | T-F11 | G-G5 |
| **T-G15** | **ADR 化：模式 → ADR 草案 → L3 评审入口 + L2 任务拆解** | T-G14 | **G-G14** |

**顺序**：`T-F03 → T-G1 → T-G4 → T-G6 → T-G12 → T-G2 → T-G7 → T-G8 → T-G9 → T-G10 → T-G11 → T-G13 → T-G16 → T-G17 → ADR-001 → T-G14 → T-G3/T-G5/T-G15`

---

## §4 硬约束

1. **分级授权**：L1 不改代码；L2 只能改单模块且过 L2-1~L2-12；L3 只出 ADR/SPEC。
2. **自动晋级仅限 S3**：`stage.json` 必须为 S3 且八门禁全绿。
3. **无 outcome 不 auto**：受影响 section 的 outcome <30 条或不足 24h 时拒绝（L2-11）。
4. **提案/评估分离**：`proposer_model != evaluator_model`；`confidence` 不入任何门禁。
5. **影子不可跳过**：无 `shadow_report.overall=pass` 不得 qualified。
6. **单步小改**：L1 每周 1 次；L2 每周 ≤2 次、每次 ≤3 文件 / ≤200 行。
7. **必有回滚点**：L1 有 backup+tag，L2 有分支+manifest+revert.sh。
8. **必须回滚记忆污染**：标记 tainted + 降权 + verify 回退。
9. **必须有断路器**：连续 2 次 auto 回滚冻结 7 天并回落 S2。
10. **沙箱隔离**：禁写认知库、禁 git push、禁外网。
11. **必有 falsifier**：缺则 `hold`。
12. **held-out 保留池不可动**：30% 永久保留。
13. **C 级记忆不进候选池**。
14. **遥测不外发**。
15. **晋级留痕**：`promotion.json` 记录门禁逐项、模式、阶段、污染条数。
16. **Case 不入库不算完成**：结构化 Case 是完成流程硬门禁。
17. **无 License 不采纳**：`license=unknown` 的 Reference 不得进入候选。
18. **脑暴实盘需 ADR + 灰度**：ADR-001 已出关（仅 `auditor`、1 次/自然周、失败也占额）；提额或开放新角色必须新增 ADR。
19. **自动合入仅 `evo/*`**：CI 全绿后由 **CI 机器人**合并（编排器只发请求），禁止直接 push main；合入不得触发部署。
20. **禁止生产自动部署**：只允许灰度自动部署；含 DDL / schema / registry / 定时任务 / 交易链路的部署一律人工或独立 ADR。
21. **stateful 不得自动**：涉数据迁移、缓存、任务表、消息位点、外部存储状态的 L2，禁止自动合入与自动部署。
22. **held-out 独立**：人工构造、不进入 Agent 上下文、季度冻结；同源污染即作废。
23. **观察期双条件**：≥30 条有效 outcome 且 ≥24h；同期多变更必须 BH-FDR 校正。
24. **三权分立**：调度在编排器、合并权在 CI 机器人、部署权在发布系统；编排器不得持有 push / 生产凭据。
25. **归因可追踪**：`change_id` 贯穿全链；outcome 幂等键唯一；缺链环节不得计入证据。
26. **审计可验证**：事件带 `prev_hash` 哈希链 + 每日 Git 锚点；断链即冻结 auto。

---

## §5 回滚

| 对象 | 方式 | 触发 |
|---|---|---|
| Policy（L1） | `rollback_policy.py --id`（manifest + sha256） | 沙箱/影子失败、观察期劣化 |
| Code（L2） | `rollback_change.py --id`（分支 revert + manifest） | 同上 |
| 记忆污染 | tainted + recall 降权 + verify 回退 | 任何回滚 |
| 自动回滚 | 观察期指标下降/错误率上升 | 自动 + 飞书 |
| 影子通道 | 丢弃 `shadow/` 或 `evo/*` 影子部署 | 影子失败 |
| 灰度部署（L2-B） | `rollback_deploy.sh --env gray`（切回上一镜像/版本） | 健康检查失败、冒烟失败、观察期劣化 |
| 有状态变更 | 代码 revert + 状态恢复脚本（须演练），二者缺一不得回滚完成 | 数据/缓存/任务表异常 |
| 审计链 | 校验 `prev_hash` 链；断链即冻结 auto 并人工介入 | 链断 / 哈希不匹配 |
| 断路器 | 冻结 auto 7 天、回落 S2 | 连续 2 次回滚 |
| 提案 | 改 `archived` | 拒绝 / reject |
| 全量 | git revert 对应 commit | 极端 |

---

## §6 风险

| 风险 | 缓解 |
|---|---|
| 自动晋级放大错误 | 八门禁 + 影子归因 + 观察期 + 断路器 |
| L2 代码引入隐蔽缺陷 | L2-1~L2-12 + 测试强度（mutation/差分）+ 每周抽审 |
| 指标涨价值不涨 | 适应度含 outcome.accepted / reverted |
| 提案/评估同源自嗨 | 模型分离 + 双链脑暴（模型与证据路径双不同） |
| held-out 用穿 | ≥100 条 + 30% 保留池人工换 + 季度冻结（L2-10） |
| 影子样本不足 | 按 section ≥20 次且 ≥24h，不足则延长 |
| 回滚不彻底 | 污染回滚 + tainted 降权 |
| 有状态变更自动上线 | L2-9 禁令 + 状态恢复演练（门禁 3） |
| 多变更并行归因失真 | change_id 贯穿 + 互斥观察窗 + BH-FDR（L2-11 / L2-12） |
| 编排器凭据过集中 | 三权分立 + 独立凭据（§2.11.8） |
| 审计记录被改写 | prev_hash 哈希链 + 每日 Git 锚点（§2.11.9） |
| 案例不入库 | 完成流程硬门禁（不算完成） |
| 外源基因水土不服 | license/stack_fit/adapt_cost 三重准入 |
| 自举失控 | 脑暴出关必须 ADR + 灰度每周 1 次（ADR-001） |
| 提案风暴 | 每周 3 提案 / L2 2 次 / 探索 2 次 |

---

## §7 与既有 SPEC / 系统关系

| 对象 | 关系 |
|---|---|
| SPEC-33-D | 复用 MCP 信封与快照；新增 `section=evolution` |
| SPEC-33-E | `rea_audit` 的 gate 与 `cognitive_hint` 是 Case 来源 |
| SPEC-33-F | 依赖 T-F03 / T-F06 / T-F11 |
| 4-MEMORY 认知系统 | `record/verify` 收紧为必须有 outcome；新增 tainted 降权 |
| DreamOS（`1-ARCHITECTURE/dreamos`） | 提供路由与 NodeRegistry；T-G14 第①段 |
| LobeHub 脑暴（`52-lobehub协议集成`） | 提供双链提案与 debate 升级；T-G14 第②段；出关需 ADR-001 |
| DSH（`1-ARCHITECTURE/dream-harness-bridge`） | 提供 `SubagentOutput` 契约与并行子 Agent；T-G14 第③段 |
| L0 能力矩阵（`47-MCP管理系统`） | rea/data/cognition 三类壳提供取证；T-G14 第④段 |
| `dream-completion-evolution-workflow` | 增加 Case 硬门禁（T-G12） |
| `dream-self-iteration-workflow` | 增加 `pending_actions` 与阶段检查（T-G10） |
| COLLABORATION-CONTRACT v1.6 | Worker 只读；L2 合并由 CI 机器人在 S3 执行，编排器只发请求（§2.11.8） |

---

## §8 落地进度

| 任务 | 状态 | 证据 |
|---|---|---|
| T-G1 outcome 回传 | ✅ 已落地 | `4-MEMORY/9-工具与接口/outcome_ledger.py` + `cognitive_mcp_server._handle_verify`；`test_t_g1_outcome.py` 13 passed、`test_p0_1_hook_wiring.py` 7 passed；幂等键 `(change_id,run_id,outcome_seq)`、`prev_hash` 链、篡改可检出；回滚开关 `COGNITIVE_VERIFY_OUTCOME_MODE=shadow` |
| T-G4 按 section 遥测 | ✅ 已落地 | `4-MEMORY/9-工具与接口/section_telemetry.py`；`test_t_g4_section_telemetry.py` 4 passed；recall/verify 已接线（FAIL-OPEN）；指标：calls/hit_rate/adoption_rate/budget_hit_rate；只落本地 JSONL |
| T-G12 Case 契约 + 硬门禁 | ✅ 已落地 | `33-REA逆向解析工程/core/evolution/case_ledger.py`；`test_t_g12_case_contract.py` 5 passed；字段完整率 100%、hypothesis 必带 falsifier、`require_case` 硬门禁、`case_to_outcome` 供 verify |
| T-G6 held-out 分桶与冻结 | ✅ 已落地 | `33-REA逆向解析工程/core/evolution/heldout.py`；`test_t_g6_heldout.py` 9 passed；≥100 条、section 分桶、保留池 ≥30%、source=human、拒绝 agent_context、季度冻结后仅新季度可人工换入换出（operator 必填） |
| T-G2 Policy 账本 + 八门禁 | ✅ 已落地 | `33-REA逆向解析工程/core/evolution/policy_ledger.py`；`test_t_g2_policy_ledger.py` 16 passed（全量 351 passed）；`PolicyLedger` 落 `registry.json` + `versions/<policy_id>.json` + `backup/` + `manifest.json` + `rollback.sh`，记录前后聚合 sha256 与回滚点；`evaluate_gates` 八门禁（门禁 5 忽略 confidence、门禁 7 校验有效 outcome/24h/held-out 桶/BH-FDR、门禁 8 配额+breaker）；`promotion.json` 留痕 mode/stage/pollution_count/gates；auto 仅限 S3 |
| T-G7 触发引擎 + 双模型 | ✅ 已落地 | `core/evolution/triggers.py` + `proposal_pipeline.py`；`test_t_g7_trigger_pipeline.py` 13 passed（全量 364 passed）；6 类触发器 + v0.4.0 `capability_gap`/`case_pattern`，阈值全来自 §2.3 配置；`proposer_model != evaluator_model` 否则 hold 且不调用评估器；缺 falsifier/违约 proposal 一律 hold；`confidence` 不参与 verdict；评估输入剔除 proposer 推理字段 |
| T-G8 执行器 | ✅ 已落地 | `core/evolution/executor.py` + `pollution.py`；`test_t_g8_executor.py` 10 passed；`SandboxRunner` A/B/C 缺一即 fail 且禁写认知库/git push/外网；`ShadowEvaluator` 按 section 校验 ≥20 次/≥24h/held-out 不降/degraded≤基线/P95≤+20%/归因≥80% 且范围外差异即 fail；`PollutionRollback` tainted+降权 0.3+verify 回退+report；`RollbackExecutor` 还原 manifest、stateful 必须状态恢复、≤60s、污染一并回滚；`evaluate_observation` confirm/rollback/continue |
| T-G9 双模控制器 | ✅ 已落地 | `core/evolution/controller.py`；`test_t_g9_controller.py` 13 passed；状态机 proposed→evaluated→sandboxed→shadowed→qualified→promoted→observing→confirmed/rolled_back，乱序事件拒绝；S1 manual 且禁影子、S2 manual+shadow、S3 auto（仅八门禁全绿，前 3 次留 24h 否决窗口）；断路器打开/阶段非 S3 一律 manual→notified 并注入 notifier 发飞书告警；连续 2 次 auto 观察期回滚 → `breaker.json` open + 冻结 7 天 + 阶段回落 S2，`reset_breaker` 必须填原因并留痕；`stage.json` 降级立即生效，升级需 S1→S2（≥30 条有效 outcome 且 ≥24h）/ S2→S3（连续 5 次一致）证据 |
| T-G10 无 LLM 降级通道 | ✅ 已落地 | `core/evolution/pending_actions.py`（`PendingActionStore`：`policy/proposals/pending/<id>.json`，强制 proposal_id/level/trigger/claim/falsifier/rollback_point）；`dsh_nodes.evolution_pending_actions` + `_with_pending_actions` 给 `S33_rea_analyze`/`S33_rea_trace`/`S33_rea_audit` 信封附加 `pending_actions[]`（FAIL-OPEN，非空才加）；`get_rea_snapshot(section=evolution)` 无 snapshot_id 直接返回待办（含 diff 与 rollback_point，支持 cursor/limit）；`test_t_g10_pending_actions.py` 8 passed；MCP `l0_rea` schema 补 `evolution` 枚举并放开 snapshot_id 必填 |
| T-G11 断路器恢复审计 | ✅ 已落地 | `controller.open_breaker/is_auto_frozen/breaker_audit`：连续 2 次 auto 回滚自动 open（freeze 7 天），阶段 >S2 时立即回落，已在 S2 则幂等；open/reset 均写 `policy/audit/breaker_audit.jsonl`；`scripts/reset_breaker.py --root --reason --actor`（reason 必填，缺失 exit≠0），reset 不自动升阶段，需补 S2→S3 证据后 auto 才恢复；`test_t_g11_breaker.py` 5 passed（含 CLI 与恢复演练） |
| T-G13 Reference 账本 | ✅ 已落地 | `core/evolution/reference_ledger.py`：`reference/references.jsonl` append-only；`usable` 由账本计算并忽略调用方自报值；license 归一化（unknown/GPL 系进闭源 → 不可用，`closed_source=False` 放行 GPL）；`stack_fit < 0.4` → 只可参考思路；缺 `evidence.how_verified` → 不算证据；`candidates()` 仅 usable 且按 stack_fit 降序；`lookup_gap/should_explore` 实现 gap 去重（重复调研命中缓存、`cache_hit=true`）；`test_t_g13_reference_ledger.py` 10 passed |
| T-G16 权限切分与发布治理 | ✅ 已落地 | `core/evolution/governance.py`：`ROLE_POWERS` 集中声明（orchestrator=propose / ci_bot=merge / release_system=deploy / operator=propose+approve）；`validate_credentials` 三权分立（同持提案+合并+部署即拒，orchestrator 持合并/部署即拒）；`request_merge` 强制 change_id + proposal_id + 8 项门禁全 pass + `evo/` 前缀；`branch_status` 14 天归档、behind_main 超阈值（默认 50）告警；`request_deploy` 强制 env/owner/RTO/RPO 且仅 release_system；`deploy_locks/<env>.json` 单环境锁 + TTL 900s（到期可重入、错 change_id 不得释放）；`test_t_g16_governance.py` 6 passed（全量 416 passed） |
| T-G17 测量与审计契约 | ✅ 已落地 | `core/evolution/event_ledger.py`（`EventLedger`）：`ledger/events.jsonl` 单一事实源，payload ≤2048 字节仅存引用+摘要；`prev_hash`/`receipt_hash` 哈希链 + `schema_version` 校验；`verify_chain` 定位 `broken_at`，`enforce_chain(controller)` 断链即 `open_breaker` 冻结 auto；`record_outcome` 幂等键 `(change_id,run_id,outcome_seq)` 覆盖不追加并重算后续链；`trace()` 校验 proposal→branch→merge→deploy→metric→outcome 全贯穿，缺环节 `counts_as_evidence=False`；`freeze_evaluator`/`request_evaluator_switch`（一致率 ≥0.8 才切换）；`requires_bh_fdr` + `bh_fdr(q=0.1)`；`acquire_section`/`release_section` 同 section 独占、冲突拒绝并行、支持 switchback；`test_t_g17_event_ledger.py` 9 passed（全量 425 passed） |
| ADR-001 脑暴出关 | 🟡 已出关（灰度） | `52-lobehub协议集成/decisions/ADR-001-脑暴出关.md`；`orchestrator/live_policy.py` + `live_policy.json`；6 条 live 单测全绿、orchestrator 84 passed；CLI 首次 `executed=true`（used 0/1），二次 `weekly budget exhausted (1/1)` exit 2 |
| T-G14 研发流水线 | ✅ 已落地 | `core/evolution/research_pipeline.py`：`ChangeClassifier`/`classify_change` 确定性分级（≥2 编号目录 / 公共契约 / schema / 依赖方向 / 新增依赖 / >3 文件 / >200 行 → L3；规则-only → L1；无法判定保守 L3；LLM 自报级别仅记 `declared_level`，`level_source` 恒为 classifier）；`ResearchPipeline` 五段编排（路由仅 workers/debate → 双链脑暴 side A/B 的 model 与 evidence_path 必不同 → DSH `SubagentOutput` 校验 → L0 `evidence_refs` 非空否则打回 → 门禁），`research_artifact.json` + `dev_artifact.json` + `evidence_refs.json` 三者缺一即拒；L3 只出 ADR/SPEC 且拒代码变更，L2 必须产出代码 diff；stateful L2 标注 L2-9 禁自动，L2 自动合入保持关闭（L2-7）；周探索/L2 配额 + `completion_rate`（G-G14）；`test_t_g14_research_pipeline.py` 22 passed（全量 447 passed，0 failed） |
| T-G15 ADR 化 | ✅ 已落地 | `core/evolution/adr_builder.py`：`AdrBuilder.build` 模式门槛（≥5 同类 Case + 跨 ≥3 迭代 + Evidence ≥2）、候选方案 ≥2、影响面/回滚必填，产出 `decisions/ADR-<n>-<slug>.md`（背景证据 / 候选方案 / PoE 取舍 / 影响面 / 回滚灰度 / L2 任务清单六段）；L2 任务复用 T-G14 `ChangeClassifier` 校验边界，判 L3 即拒并要求继续拆分，缺 acceptance 拒绝；`review_queue.jsonl` 评审入口，`record_review` 强制 AI 评审通过后才允许人终审（跳步拒绝），reject 终结、approve 后从 pending 移除；`pending_reviews()` 供 L3 评审消费；`test_t_g15_adr_builder.py` 11 passed（全量 458 passed，0 failed） |
| T-G3 涌现回灌 | ✅ 已落地 | `core/evolution/emergence.py`：`candidates_from_template` 门槛（≥5 同类 Case + 跨 ≥3 迭代 + 模板 Evidence ≥2），C/D 级记忆硬拒（硬约束 13）；候选落 `candidates/rules.jsonl`；`promote` 强制八门禁全 pass（缺项/未全绿拒绝）、候选不存在/重复回灌拒绝；`rules_registry.json` 为事实源并确定性重写 `rea_rules.yaml`（`RULE-000n` 自增，含来源模板/候选/Evidence/晋级时间）；`test_t_g3_emergence.py` 9 passed |
| T-G5 漂移守卫 | ✅ 已落地 | `core/evolution/drift_guard.py`：默认阈值 `cycles/god_components/fan_out` 涨幅 30%、`adoption` 跌幅 20%，阈值可配置且严格大于才触发；基线为 0 且当前 >0 保守判 drift；命中即 `status=review` 并 append-only 写 `reflection_data/evidence/drift_guard.jsonl`（evidence_id/verdict/baseline/current/drifts/provenance），不可只告警不留证；`test_t_g5_drift_guard.py` 9 passed（全量 476 passed，0 failed） |
| L2 自动合入（L2-7） | ✅ 已落地（代码层，待灰度开启） | `core/evolution/auto_merge.py`：`AutoMergeCoordinator.request` 只产 `merge_requested` 请求（`executor=ci_bot`、`deploy_triggered=False`、`main_protection=unchanged`），硬门禁：仅 L2、仅 `evo/*`、CI 全绿、回滚演练 pass、断路器关闭、八门禁全绿、≥30 条有效 outcome 且 ≥24h、held-out 桶 ≥20、≤3 文件 ≤200 行；stateful 拒（L2-9）、新增依赖/改契约/改 schema 拒（L2-3/L2-4）、`force_break_glass` 拒；`complete` 由 `ci_bot` 执行并二次校验 CI，编排器调用被 `Governance` 拒（三权分立），合入后分支删除且不触发部署；`test_l2_7_auto_merge.py` 17 passed（全量 493 passed，0 failed） |
| L2 自动部署灰度（L2-8 B） | 🟡 骨架已落地（默认关闭，待发布系统接入） | `core/evolution/deploy_gate.py`：默认 `mode=off`（缺失/损坏文件一律 off，fail-closed）；`off→shadow` 可切换，`shadow→auto` 需连续影子成功 ≥3 且无冻结；`readiness` 十项检查（mode/stage/shadow/health/rollback+演练时效/部署窗口/flock+pidfile/数据迁移/freeze/change_id），数据迁移类变更含「必须人工」；`deploy()` 影子模式只模拟不调用任何部署函数，auto 模式加锁→部署→健康检查，双通过才原子更新 release，失败调回滚并冻结 7 天。`scripts/rollback_deploy.sh` 支持 `--env gray/--drill/--state-dir`，目录锁兼容 macOS、交换 current/previous、健康失败 exit 3 并留痕；`scripts/deploy_gray.py` 为 release_system/运维 CLI（`--dry-run` 只出 readiness）。`tests/test_l2_8b_deploy_gate.py` 27 passed、全量回归 669 + 10 = 679 passed / 0 failed / 0 errors、ruff 全绿、`bash -n` 通过。局限：真实镜像/发布凭据未接入（`deploy_cmd/health_cmd/rollback_cmd` 由 `gate_config.json` 注入），与 `Governance.request_deploy` 的发布锁串联待接入时补 |
| L2 生产自动部署（L2-8 C） | ⛔ 非目标 | 本 SPEC 不批准；须独立 ADR（§2.11.7） |
| L2-9~L2-12 + §2.11.8/§2.11.9 | ✅ 已落地 | T-G16 覆盖 §2.11.8（三权/合并/部署/锁/分支）；T-G17 覆盖 §2.11.9（单一事实源/幂等/change_id 贯穿/schema/哈希链/评估器冻结/BH-FDR/section 隔离） |

---

## §9 开放问题

| # | 问题 | 建议 |
|---|---|---|
| Q1 | auto 模式飞书只通知？ | 是，不阻塞 |
| Q2 | held-out 题库谁维护？ | ≥100 条人工构造；30% 保留池只由人工换入换出，季度冻结（L2-10） |
| Q3 | Policy 是否独立分支？ | 是，`policy/<id>` |
| Q4 | 观察期多长？ | 已改为双条件「≥30 条有效 outcome 且 ≥24h」+ BH-FDR，见 §2.11.9 |
| Q5 | 无 LLM 能否自动升级？ | 不能 |
| Q6 | S2 退出「5 次一致」怎么计数？ | 只计 qualified 且人工决策的样本 |
| Q7 | 评估模型选谁？ | 与提案模型不同厂商/版本，留痕 |
| Q8 | 污染回滚是否删 Case？ | 不删，标 tainted |
| **Q9** | **L2 自动合并默认可否直接进 main？** | **建议先进 `evo/*` 分支并由 CI 合并；main 保护规则不放松** |
| **Q10** | **DSH 子 Agent 是否新增「研发型」Agent？** | 建议新增 `dev_agent`（遵循 SubagentOutput 契约），复用现有 IPC 注册 |
| **Q11** | **脑暴出关灰度对象？** | 仅 `auditor` 角色 + 每周 1 个 proposal，观察 2 周再扩 |
| **Q12** | **ADL 与 SPEC-F 的边界？** | SPEC-F 管「能力建设」（人工开发），本 SPEC 管「自更新流程」；两者以 ADR 交接 |
