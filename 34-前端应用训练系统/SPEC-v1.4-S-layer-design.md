# SPEC v1.4 — S 层完整设计：C-Drive 充分性驱动的动态规划层

> 版本: v1.4.0 | 日期: 2026-10-16 | 状态: **已批准，TDD 实现中**
> 决策点拍板（用户批准时采用 SPEC 默认假设）: 1-e 全部模块组成评估矩阵 / 2-复用 0.7/3/0.3 派生不确定区间 / 3-light·standard 永不触发开工 / 4-NEED_RESEARCH 首版打桩记录不实际执行
> 前置: SPEC-v1.2（SACG 编排 §3 S 层定义）、PLAN P3.2（S 层 hint 深化，已落地）、P3.2 遗留「开工 Skill 实质触发」注入点
> 定位: 把 S 层从「意图档案 + Spec 草案」升级为「C-Drive 充分性评估驱动的完整规划层」

---

## 1. 设计原点（用户三原则）

1. **C-Drive 驱动 + 动态提前终止**：SACG 全程由 C-Drive 驱动，C-Drive 用已有决策逻辑做**充分性评估**；评估"够了"即可停止推进，**不强制走完完整 S→A→C→G 流程**。
2. **复用现有决策模块参与评估**：不重写第二套决策，用项目内已有的决策/门控模块组成评估矩阵（候选清单见 §4，**需用户确认是哪一个/哪些**）。
3. **澄清式用户抉择**：当充分性"差不多"（不确定区间）时，列出要点提问用户，由用户抉择——复用已有澄清链路（`/api/task/stream` clarification 机制）。

## 2. 外部调研结论（规划层模式横评）

| 框架/产品 | 规划模式 | 提前终止 / 动态调整 | 用户抉择机制 | 对本设计的启示 |
|---|---|---|---|---|
| **LangGraph Plan-Execute** | Planner 产计划 → Executor 逐步执行 → **Replan 节点** | 每步后可 Replan 修订计划再入执行；DAG 计划声明依赖 | 无内建，需 interrupt | Replan = 充分性不足时的修订入口；计划可是 DAG 不必线性 |
| **Open SWE (LangChain)** | Manager → Planner → Programmer(Reviewer) 三图串联 | Manager 路由决定是否进入规划 | Manager 即用户交互路由层 | 「路由者决定是否规划」≈ 我们的 route_confidence 入口门 |
| **Claude Code plan mode** | Explore → Plan → 用户确认 → 执行 | 执行中可随时切回 plan mode | **AskUserQuestion**：执行暂停等用户回答；permission mode 分级 | 澄清是「暂停-提问-恢复」一等公民；与我们的 awaiting_clarification 机制同构 |
| **Claude Code auto mode** | 模型分类器代替用户做批准 | 低风险自动放行，高风险才问人 | 模型代理决策 + 人兜底 | C-Drive 充分性评估 = 「模型代理决策器」，只在不确定区间问人 |
| **ReAct** | 无显式计划，逐步推理 | 天然逐步停 | 无 | 反面对照：无规划层导致长任务漂移——S 层存在的理由 |

**横评结论**：主流形态 = **规划者 + 执行者 + 每步后的「继续/修订/终止/问人」四路裁决**。我们的差异化：裁决不另写，复用 C-Drive 已有五步链路与决策矩阵。

## 3. S 层完整架构设计

### 3.1 充分性状态机（核心）

```
L2_HANDOFF 请求（携带 l1_intent_hint + memories）
  ↓
【S0 入口评估】C-Drive 充分性评估 #1（规划前）
  ├─ SUFFICIENT_DIRECT  → 跳过规划，直接构造最小 plan（单节点），转 C 执行
  │                        （例：hint=price_query + recall 高密度 → 模板化直接答）
  ├─ NEED_PLAN          → 进入 S1 规划展开
  ├─ NEED_CLARIFY       → 产澄清选项，挂起为 awaiting_clarification，问用户
  └─ NEED_RESEARCH      → 触发外部调研（C-Drive 执行，SPEC-v1.2 §3-③）
  ↓
【S1 规划展开】（现状已落地：意图档案 → plan_items + Spec 草案）
  ↓ 每展开一层 / 每产出一个草案
【S2 充分性再评估】C-Drive 评估「规划是否够用」
  ├─ SUFFICIENT      → 冻结 plan，转 A 层（或按深度跳过 A 直接转 C）
  ├─ NEED_DEEPER     → 继续展开（depth: light→standard→deep）
  ├─ NEED_CLARIFY    → 列出规划要点选项，问用户抉择
  └─ EARLY_TERMINATE → 判定不值得做（recall 证伪/资源不足），礼貌退出
  ↓
【S3 开工 Skill 触发门】仅当 depth=deep 且充分性评估确认需要完整闭环时：
  触发开工 SKILL（调研→SPEC→评审→PLAN 五阶段，每阶段用户确认门）
  —— 异步重型链路，不在聊天链路同步执行
```

**关键性质**：
- 充分性评估**贯穿 S 层每一步**（不是一次性门），任何一步评估"够了"即停；
- 跳层是合法路径：S 可直接到 C（light）、可经 A 到 C（standard）、可触发开工 Skill（deep）；
- EARLY_TERMINATE 是一等公民，与 C-Drive 节点决策常量对齐。

### 3.2 充分性评估矩阵（Sufficiency Matrix）

复用 C-Drive 已有信号，**不引入新阈值体系**（0.7/3/0.3 硬约束不变）：

| 输入信号 | 来源模块（现状） | 在充分性评估中的角色 |
|---|---|---|
| match_score + case_density | `cognitive_router.evaluate_match` | 高 match+高密度 → SUFFICIENT_DIRECT；双低 → NEED_RESEARCH/CLARIFY |
| route_confidence | `route_confidence.evaluate_route` | 入口门已用；S 层内部复用其纯函数做再评估 |
| **jev 裁决 + 抗振荡（决策模型核心，用户拍板 2026-10-16）** | `jev_gate.jev_gate` + `JevAntiOscillation` | **充分性候选动作一律经 jev_gate 终裁**：原始决策（CONTINUE=继续展开 / INSERT_BEFORE=补充 / JUMP_TO=跳层 / EARLY_TERMINATE=退出）→ jev 规则改写 → 抗振荡防"展开-终止"反复 |
| REA 反思决策 | `rea_cdrive_adapter` / `decision_deriver` | 零 token 反思：known_gaps 证据不足 → NEED_DEEPER/EARLY_TERMINATE |
| 决策五态 | CONTINUE/REDO/INSERT_BEFORE/JUMP_TO/EARLY_TERMINATE | 映射到 S 层动作：CONTINUE=继续展开 / JUMP_TO=跳层 / EARLY_TERMINATE=退出 |
| Reflector 6 决策 | `core/compute/reflector.py`（DreamOS 侧） | 不参与（决策模型唯一=jev，避免双裁决器冲突） |

**输出四态**：`SUFFICIENT / NEED_DEEPER / NEED_CLARIFY / EARLY_TERMINATE`（+ 入口期的 `SUFFICIENT_DIRECT / NEED_PLAN / NEED_RESEARCH`）。

### 3.3 澄清式用户抉择（复用现有链路）

- **触发（用户拍板 2026-10-16：不确定多问）**：充分性评分落入不确定区间即问——
  ① match∈[0.4,0.7) 且 density<3（原区间）；
  ② **信号矛盾**：match 与 density 方向相反（如 match≥0.7 但 density=0、或 match<0.4 但 density≥5）；
  ③ **jev 裁决改写**：jev_gate 把 CONTINUE 改写为 INSERT_BEFORE/REDO（说明证据不足但有方向）→ 与其猜不如问；
  ④ 多个 plan 分支评分接近（|Δscore| 不显著）。
- **产出**：澄清选项列表（2-4 个分支，如「快速概览 / 技术分析 / 基本面分析 / 深度报告」），任务置 `awaiting_clarification`；
- **消费**：复用 `route.ts` L84-110 澄清回复检测（数字 1-4 + 选项关键词 → 关联原任务，`effectiveMessage` 带 `[用户选择: x]`）+ `fallback-engine.ts` Step 0 数字解析；
- **新增工作**：把「澄清选项的生成」从 LLM 自由发挥改为 **S 层充分性评估结构化产出**（选项即 plan 分支），澄清恢复后直接走选中分支，不再重新规划。

### 3.5 S 层能力调用链（用户补充 2026-10-16，已落地）

S 层规划不是孤立模板展开，而是**三级能力递进调用**，前一级能解决就不进入下一级：

```
① 广义认知系统（五类四层）
   提供经验/操作流程/领域知识 → 避免踩坑、省去不必要调研
   落地: plan["cognitive_experience"] = recall top3 记忆要点（按 score 排序）
  ↓ 经验不足以形成清晰工程拆解时
② 逆向解析工程（33-REA，investigate 四阶段: Locate→Trace→Reduce→Annotate）
   提供更具体的架构拆解 → 为 A 层提供更具体清晰的工程 OKR
   落地: SLayerPlanner(rea_fn=...) 注入（FAIL-OPEN）→ plan["engineering_okr"]
        （evidence 条目 + known_gaps 补齐项）；默认 A 分解器优先消费 engineering_okr
  ↓ 前两步（认知+REA）仍无法解决（充分性 NEED_RESEARCH）
③ 开工 SKILL 开启调研（五阶段闭环）
   调研确认后 → 逆向解析工程再次拆解 → 更好的工程架构 → A 层明确 OKR
   落地: kickoff_trigger["post_research_rea"]=True 标记调研后 REA 再拆解契约
```

**关键性质**：REA 在 ②（规划期）与 ③（调研后）两次出现——调研让 REA 的拆解有更实的输入；
REA 不可用时整条链 FAIL-OPEN（`rea_degraded=True`，流程不受影响）。

### 3.6 开工 Skill 触发策略（P3.2 遗留注入点闭合）

| 条件 | 动作 |
|---|---|
| depth=light/standard | **不触发**开工 Skill（聊天链路内完成 S→C，够用即停） |
| depth=deep 且充分性评估 NEED_RESEARCH | **由 C-Drive 驱动外部调研**（用户拍板 2026-10-16：内部认知+REA 已先消费，调研是递进末段）；异步触发开工 SKILL 五阶段闭环，聊天链路先返回「已进入深度调研流程」+ 阶段进度；调研确认后 REA 再拆解（§3.5-③） |
| 用户显式说「开工」 | 直接触发（现状 trigger 词已支持） |

落地形式：`SACGOrchestrator.__init__` 已有 `s_planner` 注入点 → 实质化为 `SLayerPlanner` 类（内含充分性状态机），`s_planner` 签名扩展返回 `{"plan": ..., "sufficiency": {...}, "action": "..."}`。

## 4. 决策点（已全部拍板 2026-10-16）

1. ~~「忘了名字」的决策模块是哪个/哪些？~~ → **决策模型就是 jev**：`jev_gate` L4 全局裁决 + `JevAntiOscillation` 抗振荡是充分性评估的唯一终裁器（§3.2）；Reflector 6 决策不参与，避免双裁决器冲突。
2. ~~澄清触发的不确定区间~~ → **复用 0.7/3/0.3 派生，且"不确定多问"**：原区间 + 信号矛盾 + jev 改写 + 分支评分接近，四类情形一律 NEED_CLARIFY（§3.3）。
3. ~~开工 Skill 触发的 depth=deep 判定~~ → **light/standard 永不触发**，维持。
4. ~~NEED_RESEARCH 的外部调研~~ → **C-Drive 驱动外部调研**（内部认知+REA 先消费，调研是递进末段）；首版打桩记录 + kickoff async_stub，调研确认后 REA 再拆解（§3.5-③）。

## 5. 实现拆解（评审通过后按 TDD 推进）

| 编号 | 任务 | 落点 | 依赖 | 状态 |
|---|---|---|---|---|
| S-1 | 充分性评估器 `sufficiency.py`（四态输出，复用 evaluate_match/evaluate_route/jev_gate 常量） | `core/sufficiency.py` 新建 | — | ✅ 已落地 |
| S-1b | **jev 终裁接入**：充分性候选动作经 `jev_gate` 改写 + `JevAntiOscillation` 抗振荡；jev 改写为 INSERT_BEFORE/REDO → NEED_CLARIFY（§3.3-③）；信号矛盾 → NEED_CLARIFY（§3.3-②） | `core/sufficiency.py`（改） | 决策点 1/2 拍板 | ✅ 已落地（2026-10-16，8 测试） |
| S-2 | `SLayerPlanner`：充分性状态机 S0→S1→S2，替换 `_default_s_planner` | `core/sacg_orchestrator.py` | S-1 | ✅ 已落地 |
| S-2b | 能力调用链（§3.5）：认知经验 top3 注入 + REA engineering_okr + post_research_rea 契约 | `core/sacg_orchestrator.py` | S-2 | ✅ 已落地 |
| S-3 | 澄清结构化产出：sufficiency=NEED_CLARIFY → 选项列表 + awaiting_clarification 对接 | `core/` + `route.ts` 对接（只读复用现有检测，前端零改或微改） | S-2 | 🔄 core 侧已落地，链路对接待续 |
| S-4 | 开工 Skill 触发门（depth=deep + NEED_RESEARCH → 异步触发记录） | `core/sacg_orchestrator.py` S3 | — | ✅ 已落地（async_stub） |
| S-5 | 回归：pytest 全量 + tsc + 十意图端到端不变 | — | 全部 | ✅ 667 passed + tsc 0 |

**TDD 顺序**：每步 RED（断言充分性四态/状态机转移）→ GREEN → 回归。

## 6. 边界与非目标

- 不改 C-Drive 节点级五步链路（run_v3）本身，只在 S 层调用其评估能力；
- 不引入新阈值常量（0.7/3/0.3 跨系统唯一硬约束不变）；
- A 层 OKR 验收（P3.3）、G 层收尾（P3.5）不在本 SPEC 范围；
- 澄清链路前端检测逻辑已存在，本 SPEC 只新增「选项由 S 层结构化产出」，不重写前端。
