# SPEC — Agentic Self-Improvement Loop (ASIL) v0.2

> **状态**：🟢 评审通过（2026-11-10 Devil's Advocate 攻击 → 7 漏洞 → 全部修复）· **v0.2.1 已回写实施状态（见 §0.5）**
> **归属**：48-涌现架构（叠加层，不替代 v0.5 Phase E0-E6 与 v0.5 三维 D1/D2/D3）
> **上游**：48 v0.5 Phase E0-E6 · 48 v0.5 三维 D1/D2/D3 · 35-广义认知系统（recall/record/verify） · 47-MCP管理系统 · 23-四层闭环
> **下游**：ASIL-Orchestrator（编排器 MVP） · 48 NN 反馈网关 v0.1 · 33-REA 做梦器 · 45-评测系统
> **核心命题**：**把广义认知系统的贝叶斯闭环从"被动积累"变为"主动搜寻+验证+进化"，在 48 涌现架构的度量框架下，实现系统级 Agentic 自训练**
> **v0.1→v0.2 修订**：3 项 P0 致命漏洞修复 + 4 项 P1 严重漏洞修复 + 2 项 P2 中等漏洞修复（详见变更日志）

---

## §0 Executive Summary

### 0.1 一句话定位

**ASIL = 48 涌现架构的"训练编排层"**——不新增模块、不替代 Phase E0-E6、不改变三维 D1/D2/D3 的判据；只在其之上加一个编排器，把已有的广义认知 recall → 意图涌现 → 技术架构涌现 → 评测验证 → 贝叶斯 verify 串成自动化闭环。

### 0.2 就绪等级体系（v0.2 新增）

SPEC 引入三级就绪标记，避免笼统的 ✅/❌ 造成乐观假设：

| 等级 | 含义 | 可编排性 |
|---|---|---|
| 🟢 **生产** | 真实生产实现，LLM 或规则，稳定可调用 | 可直接作为 ASIL Pipeline 环节 |
| 🟡 **代理可用** | 规则代理/统计聚合/反事实 A/B，可跑通但非最终形态 | Phase 1 降级使用，真实版推迟到 Phase 2+ |
| 🔴 **未实现** | 不存在，需要新建 | 必须先实现才能纳入 Pipeline |

### 0.3 外部成熟项目经验 × ASIL 的 7 条工程原则

| # | 原则 | 来源 | ASIL 落地方式 |
|---|---|---|---|
| **P1** | 反思必须有**即时过程奖励**，而非纯结果奖励 | Reflexion（ICLR 2023，反思使 AlfWorld↑22%、HotPotQA↑20%、HumanEval↑11%）+ OpenAI AgentPRM + Meta HiPRAG（过程奖励 > 结果奖励） | §3.2 R5 启发式规则（Query→Search→Read→Synthesize 每步可验证子目标） |
| **P2** | Skill Library 是终身学习的核心载体，必须**可组合、可检索、可遗忘** | Voyager（TMLR 2024，Minecraft 3.3× 物品、2.3× 距离、15.3× 里程碑）+ EvolveR 自蒸馏→原则库→检索→RL 闭环 | §2.2 广义认知记忆库（record/verify/蒸馏）= Skill Library |
| **P3** | 多 Agent 自进化必须有**独立裁判**，否则会自我强化幻觉 | Gödel Agent（2024，自引用递归改进）+ Meta-Team（2025，协作自进化需 timeout 反馈）+ CAMEL/MetaGPT 反模式（脚手架收益被误报为涌现） | §3.3 Oracle Phase 1 纯静态校验器（AST + schema + py_compile），Phase 2 升级为独立 REA 交叉分析 |
| **P4** | 影子验证是金融级系统的**强制前置**，直接切流等于自杀 | FCA RTS 6（强制影子验证）+ Two Sigma/Citadel/Barclays 公开工程实践 | §5 所有 ASIL 动作默认 FAIL-OPEN / SHADOW 模式 |
| **P5** | 选择压力必须**防古德哈特陷阱**——指标不能变成目标本身 | Schaeffer 2023（LLM 涌现海市蜃楼：29 度量 25 无涌现）+古德哈特定律 + CAMEL 涌现幻觉 | §3.4 脚手架披露卡 + 数据红利消融 + novelty × value 联合评估 |
| **P6** | 漂移检测必须是**三重验证**，单一 PSI 不够 | Barclays/JPM 三重漂移检测（PSI + K-S + VaR）+ PSI 阈值 0.1/0.25 行业共识 | §3.5 三重漂移检测 + 分层 Kill Switch |
| **P7** | 自进化闭环必须有**Kill Switch 链**——Fail-closed 是底线 | EU AI Act 2026.8 + MAS SAFR（运行时治理）+ SR 11-7 贝叶斯 VaR | §6 分层 Kill Switch + 贝叶斯 VaR 拦截 |

### 0.4 已就绪 vs 需补（v0.2 更新为就绪等级）

| 维度 | 就绪等级 | 需补 | 工作量 |
|---|---|---|---|
| 广义认知 recall/record/verify | 🟢 生产 | 48 verdict → verify 自动回写 | ~50 行 Python |
| **D2-A 架构复原** | 🟡 代理可用（holdout 引擎跑通，F1=1.0） | 3-5 模块人工复核 | Phase 2 |
| **D2-B 架构方案生成** | 🟡 代理可用（确定性规则引擎，非 LLM） | 真实 45 门禁 E-H1~H5 加权项 + LLM 版生成器 | Phase 2 |
| **D3-A 意图预测** | 🟡 代理可用（规则基线 TOP1=0.908，use_llm_based=False） | LLM 版 + 直接意图标签（非 task_type 代理） | Phase 2 |
| **D3-B 知识组合** | 🟡 代理可用（反事实 A/B，步降 7.10） | 在线 shadow A/B runner（~20 样本） | ~150 行 |
| **X-A 跨域迁移** | 🟡 代理可用（proxy G₁₂₃=0.080） | 真实在线 A/B（T-I2E / T-E2T） | Phase 3 |
| 45 评测门禁 | 🟢 生产（D2 本地 E-H1~H5 硬项 5/5） | D2 加权项 + 人工盲评 | 人工流程 |
| 编排器 | 🟢 已实现（v0.2.1） | ASIL-Orchestrator 8 步管道 | 见 §0.5 |
| Oracle 验证层 | 🟢 已实现（v0.2.1） | V1 纯静态校验 + V2 AST 拓扑六项 | 见 §0.5 |
| 反馈信号扩维 | 🟡 部分（v0.2.1） | session outcome 已落盘；D3-B 在线 shadow 待做 | 见 §0.5 |

---

### 0.5 实施状态回写（v0.2.1，2026-11-10）

> 本节只记录"已落地事实 + 证据"，不改动上文的判据与边界。代码位置：`48-涌现架构/asil/`。

| 项 | 状态 | 证据 |
|---|---|---|
| Phase 1 Orchestrator MVP | ✅ 已落地 | 8 步管道 + 六触发源 + 冷却/合并 + CP1/CP2 + Bootstrap fallback；`llm_tokens_used = 0` |
| Phase 2 D3/D2 真实接入 | ✅ 已落地 | D3 真实 1092 条 intent events；D2 真实 `capability_gaps.jsonl`；OracleV2 六项校验（AST/无环/复杂度/旁路） |
| P0-1 真实认知回写 | ✅ 已修复 | `asil/cognitive_writeback.py`：verdict → `record()`（幂等）+ `verify()`；生产库示例 `VM-1794286846721-c316a951`，confidence 0.5→0.75，`recall` 排名 #1；M-ASIL-1 由自报计数改为可审计事实 |
| P0-2 统计门禁 | ✅ 已落地 | `asil/stat_gate.py`：配对 bootstrap CI + Holm 校正；三段切分 train 547 / val 328 / holdout 217；holdout 仅判定不择优（有测试锁死）；首轮 family=0（候选全被 val 筛掉） |
| D2 Wilson 区间 | ✅ 已补 | 每类 gap 输出 `p/ci_low/ci_high/n/evidence_level`；冠军按 `pass_rate → CI 下界 → n` 三级择优，避免 n=1 的 100% 假象 |
| TRAE 评注闭环 | ✅ 已实证 | 文件握手 `request(tag+digest) → result.json → 重跑采纳`；D2 驳回使 `architecture_gap` 1.0→0.0、冠军切换、overall 0.6→0.4；D3 驳回被采纳且理由入历史；含防篡改绑定、无效回写显式降级、`pending_reviews` 清单暴露 |
| 单测 | ✅ 112 passed | `asil/__tests__/`（含测试库隔离 conftest，禁止污染生产记忆） |
| 跨域迁移 T-I2E/T-E2T | ⏸ 挂起 | 等交易涌现闭环重构完成后启动 |

**遗留风险（不掩盖）**

1. D3 变体仍限于 24 格规则网格，基线已处局部最优；需扩展特征空间（session 长度 / 时段 / 文件域基数），而非继续调阈值。
2. D2 每类 gap 仅 n=1，`evidence_level = insufficient`，「pass_rate 0.6」只能作为描述性快照，不构成统计结论；真正杠杆是扩充 gap 样本并扩展 generator 覆盖类型。
3. 生产 `recall` 实测 4479ms（SLA 阈值 200ms），会成为闭环吞吐瓶颈，需单独优化。

---

## §1 ASIL 核心循环

### 1.1 完整循环图

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                          ASIL Agentic Self-Improvement Loop                       │
│                                                                                   │
│  ① 广义认知系统 ──recall──▶ ② 意图涌现(D3) ──决策──▶ ③ 技术架构涌现(D2)          │
│  🟢 生产                       🟡 代理              🟡 代理                       │
│       │                                                          │                │
│       │              [D3 降级可选]                                │                │
│       ▼                                                          ▼                │
│  ⑦ 贝叶斯 verify ◀── ⑥ 反馈闭环 ◀── ⑤ 评测与拒绝 ◀── ④ 测试验证                   │
│  🟢 生产                    🟢 生产                   🟢 生产                      │
│       │                                                          │                │
│       ▼                                                          │                │
│  ⑧ 蒸馏与沉淀 ◀───────────────────────────────────────────────────┘                │
│  🟢 生产                                                                          │
└─────────────────────────────────────────────────────────────────────────────────┘
```

### 1.2 每一步的输入/输出/门禁/就绪等级

| # | 环节 | 就绪 | 输入 | 输出 | 门禁 | FAIL-OPEN fallback |
|---|---|---|---|---|---|---|
| ① | **广义认知 recall** | 🟢 | 用户任务 / 低置信扫描 / E6 缺口 | 高相关记忆 + PoE 证据链 | trace_id 唯一 | 空 recall → 用预注册模板 |
| ② | **D3 意图涌现** | 🟡 | recall 结果 + session 历史 | IntentPrediction + KnowledgeCombo | TOP1 > B0 / ECE ≤ 0.1 | **Phase 1 降级为可选输入**（Step③ 跳过 D3，纯靠 E6 gaps）；ECE > 0.1 → 跳过 |
| ③ | **D2 技术架构涌现** | 🟡 | E6 gaps + [D3 可选] | ArchitectureGraph + BuildPlan | 45 门禁 / 新颖度 ≥ k | **Bootstrap fallback**（P0-2）：E6 gaps 空 → 用 D2-B 预注册模板（architecture_gap / doc_debt / interface_mismatch）+ recall 命中的低置信记忆作伪 gap |
| ④ | **测试验证** | 🟢 | D2 BuildPlan | 覆盖率 / 单测 / pycg | 覆盖率 ≥ 0.80 / 通过率 ≥ 0.95 | 空 BuildPlan → Pipeline 标记 DEAD（存活检查点 ①） |
| ⑤ | **评测与拒绝** | 🟢 | 测试结果 + Oracle | verdict：candidate/verified/rejected/falsified | 45 七关门禁 | 存活检查点 ②：step④ 覆盖率 < 0.5 → verdict 直接 inconclusive；Oracle FAIL-OPEN → verdict 降级为 inconclusive |
| ⑥ | **反馈闭环** | 🟢 | verdict + capability_gaps | gap_router 路由 + gaps 更新 | 48h 告警 / 7 天过期 | verdict inconclusive → 不写 gap，直接进入 Step⑦ |
| ⑦ | **贝叶斯 verify** | 🟢 | verdict + 证据链 | Beta 更新 / C→B→A→S 升级 | Mandate 门控 | **Phase 1 OOD 隔离降级**（P2-1）：基线 < 50 条 Beta 分布时跳过验证，全部 pending |
| ⑧ | **蒸馏沉淀** | 🟢 | 高置信（A/S 级）记忆 | SKILL / 架构模式 / 意图路径 | 脚手架披露卡 | 无 A/S 级 → 跳过，Pipeline 仍记为 valid |

### 1.3 循环触发条件 + 冷却时间 + 合并策略（v0.2 更新）

ASIL-Orchestrator 每日扫描以下触发源，**同一类型触发源在冷却期内合并为 1 次 Pipeline run**：

| 触发源 | 条件 | 冷却时间 | 合并策略 | Phase 1 频率上限 |
|---|---|---|---|---|
| **低置信记忆** | C 级占比 > 预注册阈值（建议 0.6） | 48h | 24h 内同类型 → 1 次 | 1 次/天 |
| **E6 需求单** | capability_gaps.jsonl 中 open 单 ≥ 1 | 72h | 48h 内新增 gap 不额外触发 | 1 次/2 天 |
| **主动反思** | 每日 06:30 扫描前一天 session | 24h | —（每日定时） | 每日 06:30 |
| **实验 verdict** | 新 candidate 产生 | — | 即时触发 Step⑦ 回写 | 不限次（轻量，只跑 Step⑦） |
| **PSI 漂移** | PSI > 0.1（轻微） | **24h** | 同漂移源冷却 | 1 次/天 |
| **PSI 严重漂移** | PSI > 0.25 + KS 通过 | 72h | — | 1 次/7 天 |

**触发频率审计**（M-ASIL-4 扩展）：每日记录各触发源触发次数，PSI 触发 > 3 次/天 → 自动进入 L1 降频。

---

## §2 ASIL 三层架构

### 2.1 架构图

（v0.1 架构图不变，略）

### 2.2 三层职责

（v0.1 不变，略）

---

## §3 关键机制设计

### 3.1 Pipeline Schema（v0.2 补 bootstrap + fallback）

```json
{
  "pipeline_id": "ASIL-20261110-001",
  "trigger": {
    "type": "low_confidence_memory|gap_router|active_reflection|verdict_feedback|psi_drift",
    "source": "C级记忆扫描",
    "evidence": {"n_memories": 42, "n_c_level": 28, "ratio": 0.67},
    "psi_value": null,
    "cooldown_until": "2026-11-11T06:30:00Z"
  },
  "bootstrap_source": {           // v0.2 新增：首次/空输入时的 bootstrap 来源
    "e6_gaps_empty": false,
    "fallback_templates": ["architecture_gap", "doc_debt", "interface_mismatch"],
    "low_confidence_seeds": ["mem_001", "mem_002"]
  },
  "steps": [
    {"seq": 1, "name": "cognitive_recall", "input": "低置信记忆列表", "output": "poe_evidence_chain", "ok": true},
    {"seq": 2, "name": "intent_prediction", "input": "recall_result", "output": "intent_prediction + knowledge_combo", "domain": "D3", "optional": true},
    {"seq": 3, "name": "architecture_solution", "input": "e6_gaps + [optional: intent]", "output": "architecture_graph + build_plan", "domain": "D2", "mode": "shadow", "bootstrap": true},
    {"seq": 4, "name": "test_verify", "input": "build_plan", "output": "coverage + pass_rate", "gate": "45 E-H1~H5", "survival_checkpoint": "build_plan_nonempty"},
    {"seq": 5, "name": "oracle_review", "input": "test_result + 45 judge", "output": "oracle_confidence + verdict", "survival_checkpoint": "verdict_exists"},
    {"seq": 6, "name": "feedback_write", "input": "verdict", "output": "gap_router_update", "policy": "FAIL-OPEN"},
    {"seq": 7, "name": "bayesian_verify", "input": "verdict + evidence", "output": "memory_confidence_update", "policy": "OOD_隔离_PHASE1_SKIP"},
    {"seq": 8, "name": "distill", "input": "A/S级记忆", "output": "skill / pattern / 40_training_suggestion", "gate": "脚手架披露"}
  ],
  "trace_id": "asil-20261110-001",
  "run_mode": "shadow",
  "provenance": "ASIL-Orchestrator v0.2",
  "llm_budget_tokens_remaining": 50000   // v0.2 新增：LLM 预算追踪
}
```

### 3.2 反馈信号六维 Reward Component（v0.2 R5 落地 + 归一化）

ASIL 的反馈不是单一 scalar loss，而是六维向量——全部约束到 `[0, 1]` 后用 MAP（Manifold-Aware Policy）沿 Pareto 前沿优化，**不手动加权**：

| # | 维度 | Phase 1 可计算公式 | 归一化方法 | 来源 |
|---|---|---|---|---|
| R1 | **verify_success** | Beta(α, β) 置信度均值 | 天然 [0, 1] | TRAIN-BASE TB2 |
| R2 | **recall_hit** | 同类事件 recall 命中率 | 天然 [0, 1] | TRAIN-BASE TB3 |
| R3 | **psi_stability** | `max(0, 1 − PSI / 0.25)`（0.25 是严重漂移阈值） | clip 到 [0, 1] | §3.5 三重漂移 |
| R4 | **citation_diversity** | `1 − known_gaps / (known_gaps + 跨域引用数 + 1)` | clip 到 [0, 1] | TRAIN-BASE TB3 |
| **R5** | **process_reward**（v0.2 落地） | **启发式规则**（预注册冻结，每步 0/1）：<br>Query: `recall 命中数 ≥ K`（K=5 冻结）<br>Search: `top3 相似度 ≥ τ`（τ=0.3 冻结）<br>Read: `至少 1 条记忆被完整读取`<br>Synthesize: `产出非空 + 含关键词`<br>总分 `sum / 4` | 天然 [0, 1] | P1 / OpenAI AgentPRM |
| R6 | **oracle_confidence**（v0.2 落地） | Phase 1：纯静态校验通过率（schema OK + py_compile OK + 无旁路痕迹）<br>Phase 2：Oracle LLM cross-check 评分 → 需与 R1 加权合并：`0.6 × R1 + 0.4 × oracle_score` | 天然 [0, 1] | P3 / B5 Oracle 层 |

### 3.3 Oracle 验证层（v0.2 Phase 1 降级 + 代码隔离硬约束）

#### Phase 1：纯静态校验器（无 LLM、无 REA 依赖）

| Oracle 做什么 | Oracle 不做什么 | 硬约束 |
|---|---|---|
| 检查 BuildPlan 的 JSON schema 完整性 | 不判断方案质量（好/坏） | 纯 read-only |
| 对 BuildPlan 中列出的模块跑 `py_compile` 验证可导入 | 不跑 33-REA 逆向分析器 | 不调用 LLM |
| 检查是否有代码旁路痕迹（subprocess / eval / exec / system） | 不修改任何生成物 | FAIL-OPEN |
| 计算 oracle_confidence = 三项通过率平均 | 不触发重跑 | 代码隔离（独立进程/模块，与生成器零 import） |

#### Phase 2+：升级为独立 REA 交叉分析

Phase 1 累积 ≥ 50 个 Pipeline 后，引入**完全不同的分析方法**：
- D2-Oracle 用独立 AST 拓扑分析器（不 import 33-REA）+ 复杂度估算
- D3-Oracle 用第二套 intent 规则引擎（独立代码路径）
- Trade-Oracle 用 DomainCouplingHead 反事实验证 + Wilcoxon

**代码隔离硬约束（P2-2）**：Oracle 评估输出（oracle_confidence）和生成器输出（BuildPlan）必须在**代码层面完全隔离**——不同 Python 模块、不同数据结构、独立进程执行、零 import 交叉。

### 3.4 防古德哈特陷阱

（v0.1 不变，略）

### 3.5 三重漂移检测

（v0.1 不变，略）

### 3.6 FAIL-OPEN 存活检查点（v0.2 新增）

Pipeline 不再"跑完 8 步就算 completion"，关键检查点必须产出有效输出：

| 检查点 | 位置 | 检查条件 | 不通过时行为 |
|---|---|---|---|
| **CP1 BuildPlan 非空** | Step④ 入口 | build_plan != null AND build_plan.modules.length > 0 | Pipeline 标记 `DEAD`，不等走完 8 步；不计入 M-ASIL-0 valid_completion_rate |
| **CP2 verdict 存在** | Step⑤ 出口 | verdict ∈ {candidate, verified, rejected, falsified, inconclusive} | verdict 降级为 `inconclusive`，继续 |

### 3.7 反馈信号扩维（session outcome 结构化）

（v0.1 不变，略）

---

## §4 ASIL-Orchestrator 实现规范

### 4.1 技术栈约束（v0.2 新增 LLM 成本声明）

| 约束 | 值 | 来源 |
|---|---|---|
| 语言 | Python 3.10+ | 项目主栈 |
| GPU | 零（H2 硬约束） | TRAIN-BASE H2 |
| LLM 调用 | **Phase 1 默认零 LLM 调用**（全部用规则代理降级）；LLM 调用仅用于 Phase 2+ 真实评测 | P0-1 漏洞修复 |
| 训练算法 | 贝叶斯在线学习 + GRPO 轻量 RL（冻结权重）+ 统计检验 | TRAIN-BASE H2 |
| 外部依赖 | 仅 numpy + scipy + 项目已有模块 | 极简原则 |
| 代码量预算 | MVP ≤ 500 行 Python | 单文件可审查 |

### 4.2 Orchestrator 核心模块（v0.2 新增 bootstrap + checkpoint）

```
asil/
├── orchestrator.py          # 主入口 + PipelineExecutor + 存活检查点
├── trigger_scanner.py       # 六种触发源扫描 + 冷却时间 + 合并策略
├── drift_detector.py        # 三重漂移检测（PSI + KS + VaR）
├── pipeline_builder.py      # Pipeline schema 构造 + bootstrap fallback
├── verdict_router.py        # verdict → feedback → verify 路由
├── feedback_writer.py       # 自动回写 capability_gaps + 认知库 verify
├── metrics_collector.py     # E4/E5 指标 + 触发频率审计
├── kill_switch.py           # 分层 Kill Switch 链
├── oracle_validator.py      # v0.2 新增：Phase 1 纯静态校验器（独立模块）
├── llm_budget_tracker.py    # v0.2 新增：LLM 调用预算追踪 + 熔断
└── __tests__/
    ├── test_trigger_scanner.py
    ├── test_drift_detector.py
    ├── test_pipeline_builder.py
    ├── test_verdict_router.py
    ├── test_oracle_validator.py
    ├── test_bootstrap_fallback.py
    └── test_llm_budget.py
```

### 4.3 核心接口定义

（v0.1 接口不变，略）

### 4.4 Pipeline 执行状态机（v0.2 新增 DEAD 状态）

```
PENDING ──scan──▶ READY ──start──▶ RUNNING ──step_done──▶ RUNNING ──all_done──▶ COMPLETE
                                         │
                                         ├──step_fail──▶ RUNNING（记录，应用 fallback，继续）
                                         │
                                         ├──CP1_failed──▶ DEAD（BuildPlan 空，不等走完 8 步）
                                         │
                                         └──severedrift──▶ ABORTED（Kill Switch 触发）

COMPLETE ──verdict──▶ feedback_write ──verify_writeback ──distill ──EVOLVED
COMPLETE ──rejected──▶ feedback_write ──record_failure ──REJECTED
COMPLETE ──falsified──▶ feedback_write ──record_falsified ──FALSIFIED
COMPLETE ──inconclusive──▶ feedback_write(skip) ──verify_writeback ──distill(skip) ──INCONCLUSIVE

DEAD ──记录──▶ REPORT（不计入 valid_completion_rate）
```

---

## §5 运行模式与安全

### 5.1 三模式切换

（v0.1 不变，略）

### 5.2 隔离与审计（v0.2 OOD Phase 1 降级）

| 隔离类型 | 方式 | Phase 1 降级 |
|---|---|---|
| trace_id 区分 | 影子模式前缀 `shadow-` | — |
| **OOD 隔离** | 48 P0-1 hooks | **Phase 1 跳过验证**：基线 < 50 条 Beta 分布时全部 pending，≥ 50 后启用真实 OOD |
| 数据版本化 | Pipeline 每步记录 sha256 | — |
| 产物隔离 | `48-涌现架构/events/asil/` | — |
| 审计链 | receipt_hash + pipeline_id + trace_id | — |

---

## §6 Kill Switch 链

（v0.1 不变，略）

---

## §7 度量与验收

### 7.1 ASIL 自身度量（v0.2 拆分 M-ASIL-0 + 新增 LLM 预算审计）

| 度量 | 定义 | 目标 | Phase 1 必达 | 数据源 |
|---|---|---|---|---|
| **M-ASIL-0a pipeline_completion_rate** | 跑完 ①-⑧ 的管道数 / 触发数 | ≥ 0.95 | —（软指标） | ASIL events |
| **M-ASIL-0b valid_completion_rate**（v0.2 新增） | 至少产出 1 个非空 BuildPlan 的管道数 / 触发数 | ≥ 0.70 | ✅ **硬指标** | ASIL events |
| **M-ASIL-1 verify_writeback_rate** | verdict → verify 回写数 / candidate 总数 | ≥ 1.0 | — | verify 日志 |
| **M-ASIL-2 distill_effectiveness** | 蒸馏后 skill/pattern 被 recall 命中数 / 总蒸馏数 | ≥ 0.3 | — | recall stats |
| **M-ASIL-3 feedback_latency_p50** | 触发 → feedback_write P50 | ≤ 10min | — | ASIL events |
| **M-ASIL-4a kill_switch_frequency** | Kill Switch 触发/天 | ≤ 0.1 | ✅ | kill_switch 日志 |
| **M-ASIL-4b trigger_freq_audit**（v0.2 新增） | 各触发源每日触发次数 | PSI ≤ 3 次/天 | ✅ | trigger_scanner 日志 |
| **M-ASIL-4c llm_budget_usage**（v0.2 新增） | LLM token 消耗 / 每日预算 | ≤ 100% | ✅（Phase 1 目标 0%） | llm_budget_tracker |
| **M-ASIL-5 e4_self_correction_rate** | 反思→修复 join 成功率 | 持续上升 | — | 48 E4b |
| **M-ASIL-6 e5_phase_transition_proxy** | 规模-命中率形状检验 | concave | — | 48 metrics |

### 7.2 外部验收判据

（v0.1 不变，略）

---

## §8 实施路径（v0.2 修订 Phase 1 交付物）

### Phase 1：Orchestrator MVP（1-2 周）✅ 已完成（2026-11-10）

**交付物**：
- `asil/orchestrator.py` + `oracle_validator.py` + `llm_budget_tracker.py`
- 六种触发源 + 冷却时间 + 合并策略
- Bootstrap fallback（E6 空时用预注册模板 + 低置信伪 gap）
- 存活检查点 CP1/CP2
- Pipeline Schema 完整构造（含 bootstrap + fallback + llm_budget）
- verify 自动回写 hook + OOD Phase 1 跳过
- 三重漂移检测
- 核心接口 TDD（≥ 25 用例，新增 bootstrap + oracle + llm_budget 用例）
- LLM 预算追踪（Phase 1 目标零消耗）

**验收**：
- ✅ 跑通完整 ASIL 管道至少 1 次，**CP1/CP2 至少 1 次通过**（valid_completion）
- ✅ 预注册模板 bootstrap 路径验证通过（E6 空时 Step③ 能产出 BuildPlan）
- ✅ 存活检查点 CP1 生效（空 BuildPlan → DEAD，不计入 valid_completion）
- ✅ verify 回写自动触发 1 次成功
- ✅ drift_detector PSI/KS/VaR 三档判定正确
- ✅ **LLM token 消耗 = 0**（Phase 1 硬要求）
- ✅ valid_completion_rate ≥ 0.70
- ✅ 全部单测通过

### Phase 2：反馈信号扩维 + Oracle 独立 REA 分析（2-3 周）🟡 部分完成（真实接入已完成；D3-B 在线 shadow 与 45 门禁加权项顺延）

**交付物**：
- session outcome 结构化落盘
- Oracle 从纯静态校验升级为独立 REA 交叉分析（代码隔离）
- D3-B 在线 shadow A/B runner
- D2-B 真实 45 门禁加权项

**验收**：
- session outcome 覆盖率 ≥ 30%
- Oracle 独立 cross-check 通过 ≥ 3 次
- LLM 预算审计 token ≤ 预算上限
- D3-B 在线 shadow A/B ≥ 20 样本

### Phase 3：跨域迁移闭环 + 三维涌现验证（3-4 周）

（v0.1 不变，略）

---

## §9 边界声明（v0.2 门禁强制等级标注）

| # | 约束 | 强制等级 | 命中关键词 |
|---|---|---|---|
| **C1** | ASIL 不替代 48 v0.5 Phase E0-E6 和 D1/D2/D3 | 🔴硬 | 不替代、叠加层 |
| **C2** | 所有 ASIL 管道默认 SHADOW/FAIL-OPEN | 🔴硬 | 默认、FAIL-OPEN |
| **C3** | D2/D3 生成物零执行权 | 🔴硬 | 零执行权、禁止 |
| **C4** | 不引入神经网络权重微调 | 🔴硬 | 不得、唯一、必须 |
| **C5** | verify 回写过 OOD 隔离 + Mandate（**Phase 1 降级跳过 OOD**） | 🔴硬 / 🟡软（Phase 1） | 必须、硬门禁 |
| **C6** | Kill Switch 链 Fail-closed 优先 | 🔴硬 | 必须、优先 |
| **C7** | 脚手架披露卡 + 数据红利消融是门禁前置 | 🔴硬 | 必须、前置 |
| **C8** | PSI 阈值硬编码 0.1/0.25 | 🔴硬 | 必须、默认、阈值 |
| **C9** | 实盘风控域置信度 < 0.3 自动拦截 | 🔴硬 | 必须、自动、上限 |
| **C10** | 不新建子系统所有权 | 🔴硬 | 不得、边界 |
| **C11** | Oracle 必须与生成器代码隔离（不同进程/模块/数据结构） | 🔴硬 | 必须、隔离 |
| **C12** | Phase 1 LLM token 消耗 = 0 | 🔴硬 | 必须、零、硬约束 |

---

## §10 反模式

（v0.1 不变，略）

---

## §11 外部成熟项目参考

（v0.1 不变，略）

---

## §12 与现有体系的关系

（v0.1 不变，略）

---

## §13 算力预算（v0.2 新增 §13.1 LLM 预算）

| 环节 | 算力需求 | Phase 1 方式 |
|---|---|---|
| drift_detector | O(N) 毫秒级 | numpy + scipy，零 GPU |
| pipeline 构建 | O(1) | 原生 dict/json |
| verify 回写 | O(1) | math.beta_inv |
| **Oracle 验证** | O(K) 秒级 | **纯静态校验器**（py_compile + schema + 旁路扫描），零 LLM |
| Kill Switch | O(1) | 常量级 |
| **D3 意图预测** | O(1) | **规则基线**（use_llm_based=False），零 Token |
| **D2 架构生成** | O(K) 秒级 | **确定性规则引擎**（预注册 gap → 模板映射），零 LLM |
| GRPO 轻量 RL loop | O(K) 秒级 | 冻结 LLM 权重，只调策略输出格式 |

**Phase 1 结论**：零 GPU、零 LLM Token、单 CPU 4C16G 全环节可跑。

### §13.1 LLM 调用预算与熔断（v0.2 新增）

| 参数 | Phase 1 默认值 | Phase 2+ 默认值 | 熔断条件 |
|---|---|---|---|
| 每日 LLM token 上限 | **0** | 50,000 | 消耗 ≥ 90% → 自动切回规则代理降级 |
| 单 Pipeline token 上限 | 0 | 10,000 | 单 Pipeline 消耗 ≥ 80% 单 Pipeline 上限 → 当前 Pipeline 切规则降级 |
| 熔断后行为 | — | 跳过 LLM 调用，用 Phase 1 规则代理继续 | — |

**预算追踪**：`llm_budget_tracker.py` 实时记录每次 LLM 调用的 token 消耗，写入 `events/asil/llm_usage.jsonl`，每分钟检查剩余预算。

---

## 变更日志

| 版本 | 日期 | 变更 |
|---|---|---|
| **v0.2.1** | **2026-11-10** | **实施状态回写（§0.5）**：Phase 1 完成；Phase 2 真实接入完成（在线 shadow 顺延）；P0-1 认知回写接通（record+verify 可审计，confidence 贝叶斯升级）；P0-2 三段切分 + 配对 bootstrap + Holm；D2 补 Wilson 区间与证据等级；TRAE 评注闭环实证（D2/D3 双向覆盖、防篡改、pending_reviews）；单测 112 passed；跨域迁移挂起 |
| **v0.2** | **2026-11-10** | **Devil's Advocate 攻击后修订（7 漏洞全部修复）**：<br>🔴 P0-1 Oracle Phase 1 降级为纯静态校验器（AST + schema + py_compile）+ C11 代码隔离硬约束<br>🔴 P0-2 Step③ bootstrap fallback（E6 空 → D2-B 预注册模板 + 低置信伪 gap）+ Pipeline Schema 新增 bootstrap_source 字段<br>🔴 P0-3 引入🟢/🟡/🔴就绪等级，降级 D2-B/D3-B/D3-Implement 为代理可用<br>🟠 P1-1 R5 落地为启发式规则（Query→Search→Read→Synthesize）+ 六维 reward 全部归一化到 [0,1]<br>🟠 P1-2 新增 §13.1 LLM 预算表 + §4.1 Phase 1 零 LLM 硬约束（C12）<br>🟠 P1-3 新增 §3.6 存活检查点 CP1/CP2 + Step④⑤ FAIL-OPEN fallback + M-ASIL-0 拆为 0a/0b（valid_completion_rate 硬指标）<br>🟠 P1-4 §1.3 新增冷却时间表 + 合并策略 + 触发频率审计（M-ASIL-4b）<br>🟡 P2-1 §5.2 OOD Phase 1 降级跳过验证 + Beta 基线 ≥ 50 后启用<br>🟡 P2-3 §9 门禁强制等级显式标注（🔴硬/🟡软）<br>状态从"初稿"升为"评审通过" |
| v0.1 | 2026-11-10 | 初稿完成 |
