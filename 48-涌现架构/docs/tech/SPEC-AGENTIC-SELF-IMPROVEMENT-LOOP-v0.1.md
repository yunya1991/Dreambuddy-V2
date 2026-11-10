# SPEC — Agentic Self-Improvement Loop (ASIL) v0.1

> **状态**：🟡 初稿（2026-11-10）
> **归属**：48-涌现架构（叠加层，不替代 v0.5 Phase E0-E6 与 v0.5 三维 D1/D2/D3）
> **上游**：48 v0.5 Phase E0-E6 · 48 v0.5 三维 D1/D2/D3 · 35-广义认知系统（recall/record/verify） · 47-MCP管理系统 · 23-四层闭环
> **下游**：ASIL-Orchestrator（编排器 MVP） · 48 NN 反馈网关 v0.1 · 33-REA 做梦器 · 45-评测系统
> **触发**：2026-11-10 用户提出——"广义认知系统（MCP）+ 意图涌现（D3）+ 技术架构涌现（D2）+ 大模型评估 + 测试验证 + 反馈闭环" = Agentic 自训练闭环
> **核心命题**：**把广义认知系统的贝叶斯闭环从"被动积累"变为"主动搜寻+验证+进化"，在 48 涌现架构的度量框架下，实现系统级 Agentic 自训练**

---

## §0 Executive Summary

### 0.1 一句话定位

**ASIL = 48 涌现架构的"训练编排层"**——不新增模块、不替代 Phase E0-E6、不改变三维 D1/D2/D3 的判据；只在其之上加一个编排器，把已有的广义认知 recall → 意图涌现 → 技术架构涌现 → 评测验证 → 贝叶斯 verify 串成自动化闭环。

### 0.2 为什么这是"训练"

| 传统 NN 训练 | ASIL 训练 |
|---|---|
| 训练对象：连续参数（权重） | 训练对象：离散结构（知识/SKILL/架构图/意图组合） |
| 更新方式：梯度下降 | 更新方式：贝叶斯升级 + 达尔文选择 |
| 反馈信号：scalar loss | 反馈信号：多维度 verdict（candidate/verified/rejected） |
| 收敛判据：loss 下降 | 收敛判据：E4 自纠错率↑ + E5 规模相变 |

**ASIL 训练的是系统的"认知基因"**——哪些经验值得沉淀、哪些策略值得升级、哪些架构模式值得固化、哪些意图路径是低阻力的。

### 0.3 外部成熟项目经验 × ASIL 的 7 条工程原则

| # | 原则 | 来源 | ASIL 落地方式 |
|---|---|---|---|
| **P1** | 反思必须有**即时过程奖励**，而非纯结果奖励 | Reflexion（ICLR 2023，反思使 AlfWorld↑22%、HotPotQA↑20%、HumanEval↑11%）+ OpenAI AgentPRM + Meta HiPRAG（过程奖励 > 结果奖励） | §3.2 反馈信号六维 reward component，包含中间 step 奖励 |
| **P2** | Skill Library 是终身学习的核心载体，必须**可组合、可检索、可遗忘** | Voyager（TMLR 2024，Minecraft 3.3× 物品、2.3× 距离、15.3× 里程碑）+ EvolveR 自蒸馏→原则库→检索→RL 闭环 | §2.2 广义认知记忆库（record/verify/蒸馏）= Skill Library |
| **P3** | 多 Agent 自进化必须有**独立裁判**，否则会自我强化幻觉 | Gödel Agent（2024，自引用递归改进）+ Meta-Team（2025，协作自进化需 timeout 反馈）+ CAMEL/MetaGPT 反模式（脚手架收益被误报为涌现） | §3.3 Oracle 验证层独立 cross-check + 45 LLM 裁判校准 |
| **P4** | 影子验证是金融级系统的**强制前置**，直接切流等于自杀 | FCA RTS 6（强制影子验证）+ Two Sigma/Citadel/Barclays 公开工程实践 | §5 所有 ASIL 动作默认 FAIL-OPEN / SHADOW 模式 |
| **P5** | 选择压力必须**防古德哈特陷阱**——指标不能变成目标本身 | Schaeffer 2023（LLM 涌现海市蜃楼：29 度量 25 无涌现）+古德哈特定律 + CAMEL 涌现幻觉 | §3.4 脚手架披露卡 + 数据红利消融 + novelty × value 联合评估 |
| **P6** | 漂移检测必须是**三重验证**，单一 PSI 不够 | Barclays/JPM 三重漂移检测（PSI + K-S + VaR）+ PSI 阈值 0.1/0.25 行业共识 | §3.5 三重漂移检测 + 分层 Kill Switch |
| **P7** | 自进化闭环必须有**Kill Switch 链**——Fail-closed 是底线 | EU AI Act 2026.8 + MAS SAFR（运行时治理）+ SR 11-7 贝叶斯 VaR | §6 分层 Kill Switch + 贝叶斯 VaR 拦截 |

### 0.4 已就绪 vs 需补

| 维度 | 已就绪 | 需补 | 工作量 |
|---|---|---|---|
| 广义认知 recall/record/verify | ✅ 生产可用，贝叶斯蒸馏 + FOK/JOL + PoE | 48 verdict → verify 自动回写 | ~50 行 Python（回写 hook） |
| D2-D3 三维涌现实验框架 | ✅ D2-A/D2-B/D3-A/D3-B/X-A 均 candidate | D3-B 反事实代理 → 在线 shadow A/B | ~150 行（shadow runner） |
| 45 评测门禁 | ✅ D2 本地 E-H1~H5 硬项 5/5 真实执行 | D2 加权项 + 人工盲评 | 人工评审流程 |
| 编排器 | ❌ 不存在 | **ASIL-Orchestrator MVP**（核心交付物） | ~300-500 行 Python |
| 反馈信号扩维 | ⚠️ 部分（session outcome 未结构化落盘） | session accept/edit/reject 自动落盘 | ~100 行 + schema 增量 |
| Oracle 验证层 | ⚠️ 嵌在 Mandate 门控里，非独立 | Oracle 独立角色抽出（Two Sigma 四层分层） | 设计文档先 |
| 跨域迁移真实 A/B | ❌ X-A 是 proxy | T-I2E / T-E2T 在线 shadow A/B | Phase 3 才做 |

---

## §1 ASIL 核心循环

### 1.1 完整循环图

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                          ASIL Agentic Self-Improvement Loop                       │
│                                                                                   │
│  ① 广义认知系统 ──recall──▶ ② 意图涌现(D3) ──决策──▶ ③ 技术架构涌现(D2)          │
│  （记忆/经验库）              （D3-A 预测                   （D2-B 方案生成）       │
│                               D3-B 知识组合）                                     │
│       ▲                                                          │                │
│       │                                                          ▼                │
│  ⑦ 贝叶斯 verify ◀── ⑥ 反馈闭环 ◀── ⑤ 评测与拒绝 ◀── ④ 测试验证                   │
│  （record + verify          （E6 需求单                    （45 门禁 +             │
│   贝叶斯升级）               gap_router                    oracle 独立裁判）       │
│       │                      + gap_backfill_verify）                              │
│       ▼                                                                          │
│  ⑧ 蒸馏与沉淀                                                                      │
│  （高置信记忆→SKILL/架构模式/意图路径）                                             │
│       │                                                                          │
│       ▼                                                                          │
│  回到 ① —— 系统用"训练后"的知识/架构/意图重新进入循环                               │
└─────────────────────────────────────────────────────────────────────────────────┘
```

### 1.2 每一步的输入/输出/门禁

| # | 环节 | 输入 | 输出 | 门禁 | 已有实现 |
|---|---|---|---|---|---|
| ① | **广义认知 recall** | 用户任务 / 低置信记忆扫描 / E6 缺口 | 高相关记忆 + PoE 证据链 | trace_id 唯一 / recall_stats 记录 | ✅ 4-MEMORY recall |
| ② | **D3 意图涌现** | recall 结果 + session 历史 + task_type 时序 | IntentPrediction + IntentKnowledgeCombo | TOP1 > B0/B1 基线 / ECE ≤ 0.1 | ✅ D3-A candidate / D3-B candidate |
| ③ | **D2 技术架构涌现** | D3 预测 + 33-REA 分析器 + 45 工程知识 | ArchitectureGraph + DesignRationale + BuildPlan | 45 门禁 / 新颖度 ≥ k / 零执行权 | ✅ D2-A candidate / D2-B candidate（沙箱） |
| ④ | **测试验证** | D2 BuildPlan + D3 KnowledgeCombo | 覆盖率 / 单测 / pycg / 行为验证 | 覆盖率 ≥ 0.80 / 用例通过率 ≥ 0.95 | ✅ D2 E-H1~H5 本地执行 |
| ⑤ | **评测与拒绝** | 测试结果 + 45 LLM 裁判 + Oracle 验证 | verdict：candidate / verified / rejected / falsified | 45 七关门禁 / OOD 隔离 / 消融归因 | ✅ 48 verdict 仪表盘 |
| ⑥ | **反馈闭环** | verdict + capability_gaps.jsonl | gap_router 路由 + capability_gaps 更新 | 48h 告警 / 7 天过期 | ✅ E6 gap_router + gap_backfill_verify |
| ⑦ | **贝叶斯 verify** | verdict + 证据链 + session outcome | 记忆置信度 Beta 更新 / C→B→A→S 升级 | OOD 区间黑名单 / Mandate 写门控 | ✅ 4-MEMORY verify |
| ⑧ | **蒸馏沉淀** | 高置信（A/S 级）记忆 + PoE 证据 | SKILL / 架构模式 / 意图路径 / 40 NN 训练建议 | 脚手架披露卡 / 数据红利消融 | ✅ DynamicDistillEngine + SPEC-NN-FEEDBACK |

### 1.3 循环触发条件

ASIL-Orchestrator 每天自动扫描以下触发源：

| 触发源 | 条件 | 动作 |
|---|---|---|
| **低置信记忆** | C 级记忆占比 > 阈值（预注册冻结，建议 0.6） | 从 C 级记忆出发跑完整 ASIL 闭环 |
| **E6 需求单** | capability_gaps.jsonl 中 open 单 ≥ 1 | 从缺口出发跑 ASIL 闭环补能力 |
| **主动反思触发** | 每日 timer（建议 06:30）扫描前一天所有 session | 对 outcome=fail/correction=reject 的 session 跑 ASIL |
| **D1/D2/D3 实验 verdict** | 新 candidate 产生 | 自动触发第 ⑦ 步 verify 回写 |
| **PSI 漂移** | PSI > 0.1（轻微） | 触发 ASIL 定向反思（数据域） |
| **PSI 严重漂移** | PSI > 0.25 + KS 检验通过 | 触发 ASIL 全链反思 + Kill Switch |

---

## §2 ASIL 三层架构

### 2.1 架构图

```
┌─────────────────────────────────────────────────────────────────┐
│                    ASIL-Orchestrator（编排层）                    │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │  TriggerScanner → PipelineExecutor → VerdictRouter      │    │
│  │  FeedbackWriter → KillSwitchMonitor → MetricsCollector │    │
│  └─────────────────────────────────────────────────────────┘    │
│         │                    │                    │              │
│         ▼                    ▼                    ▼              │
│  ┌─────────────┐    ┌──────────────┐    ┌──────────────┐       │
│  │ 第 1 层      │    │ 第 2 层       │    │ 第 3 层       │       │
│  │ 广义认知系统  │    │ 48 涌现架构    │    │ 33/45/39/41  │       │
│  │              │    │ D1/D2/D3      │    │ 领域能力       │       │
│  │ recall       │    │ verdict      │    │ REA 做梦器    │       │
│  │ record       │    │ metrics      │    │ 45 门禁      │       │
│  │ verify       │    │ gap_router   │    │ 39 语义      │       │
│  │ 蒸馏         │    │ emergence_bus│    │ 41 检索      │       │
│  └─────────────┘    └──────────────┘    └──────────────┘       │
│                                                                  │
│  贯穿三层：MCP shell envelope.data（零 schema 变化）              │
│  贯穿三层：trace_id 全链路可 join                                │
│  贯穿三层：FAIL-OPEN / SHADOW 模式                               │
└─────────────────────────────────────────────────────────────────┘
```

### 2.2 三层职责

| 层 | 职责 | ASIL 不做什么 |
|---|---|---|
| **编排层 ASIL-Orchestrator** | 触发扫描 + 管道执行 + verdict 路由 + 反馈写回 + 指标收集 + Kill Switch 监控 | 不定义 D1/D2/D3 判据、不改 D2/D3 实验代码、不直接改 40 权重 |
| **48 涌现架构层** | 判据（E1-E5）、度量（M1-M7 + D2/D3 扩展）、实验协议、verdict 状态机、gap_router | 不接管 D2/D3 系统所有权（D2 归 33-REA/46-DSH，D3 归 DreamOS/35） |
| **领域能力层** | D2 架构复原/方案生成、D3 意图预测/知识组合、45 评测门禁、39 语义别名、REA 做梦器 | 不承担涌现判定权、不直接回写认知库（需经 ASIL 第 ⑦ 步） |

---

## §3 关键机制设计

### 3.1 Pipeline Schema（编排器内部管道定义）

```json
{
  "pipeline_id": "ASIL-20261110-001",
  "trigger": {
    "type": "low_confidence_memory|gap_router|active_reflection|verdict_feedback|psi_drift",
    "source": "C级记忆扫描",
    "evidence": {"n_memories": 42, "n_c_level": 28, "ratio": 0.67},
    "psi_value": null,
    "timestamp": "2026-11-10T06:30:00Z"
  },
  "steps": [
    {"seq": 1, "name": "cognitive_recall", "input": "低置信记忆列表", "output": "poe_evidence_chain"},
    {"seq": 2, "name": "intent_prediction", "input": "recall_result", "output": "intent_prediction + knowledge_combo", "domain": "D3"},
    {"seq": 3, "name": "architecture_solution", "input": "intent + E6 gaps", "output": "architecture_graph + build_plan", "domain": "D2", "mode": "shadow"},
    {"seq": 4, "name": "test_verify", "input": "build_plan", "output": "coverage + pass_rate", "gate": "45 E-H1~H5"},
    {"seq": 5, "name": "oracle_review", "input": "test_result + 45 judge", "output": "oracle_confidence + verdict", "calibration": "45 §9"},
    {"seq": 6, "name": "feedback_write", "input": "verdict", "output": "gap_router_update", "policy": "FAIL-OPEN"},
    {"seq": 7, "name": "bayesian_verify", "input": "verdict + evidence", "output": "memory_confidence_update", "policy": "OOD_隔离"},
    {"seq": 8, "name": "distill", "input": "A/S级记忆", "output": "skill / pattern / 40_training_suggestion", "gate": "脚手架披露"}
  ],
  "trace_id": "asil-20261110-001",
  "run_mode": "shadow",
  "provenance": "ASIL-Orchestrator v0.1"
}
```

### 3.2 反馈信号六维 Reward Component（P1 过程奖励原则）

ASIL 的反馈不是单一 scalar loss，而是六维向量——与项目已有 TRAIN-BASE TB3 AlphaPareto 四维对齐并扩展：

| # | 维度 | 公式 | 来源 | 落地位置 |
|---|---|---|---|---|
| R1 | **verify_success** | Beta(α, β) 置信度均值 | TRAIN-BASE TB2 | 4-MEMORY verify |
| R2 | **recall_hit** | 同类事件 recall 命中率 | TRAIN-BASE TB3 | 48 M1 / D3-B hit_rate |
| R3 | **psi_stability** | 1 − PSI（三重检测综合） | B1+B6 漂移检测 | 编排器内 drift_detector |
| R4 | **citation_diversity** | PoE known_gaps 越少越好 + 跨域引用数 | TRAIN-BASE TB3 | PoE Evidence Ledger |
| R5 | **process_reward** | 中间 step 奖励（Query→Search→Read→Synthesize 每步可验证子目标） | P1 / OpenAI AgentPRM | ASIL 每步子目标检查 |
| R6 | **oracle_confidence** | Oracle 独立 cross-check 评分（Two Sigma 四层分层） | B5 Oracle 层 | 编排器第 ⑤ 步 |

**综合评分**：用 MAP（Manifold-Aware Policy）沿 Pareto 前沿优化，**不手动加权**（AlphaPareto 共识）。

### 3.3 Oracle 验证层（P3 独立裁判原则）

ASIL 的第 ⑤ 步强制引入独立裁判——不使用"谁生成谁评审"的循环：

| Oracle 做什么 | Oracle 不做什么 | 硬约束 |
|---|---|---|
| 用不同视角 cross-check 生成结果 | 修改 D2/D3 生成物 | 纯 read-only |
| 标注 `oracle_confidence: float` 在 pipeline.meta | 触发重跑 | FAIL-OPEN（低置信只告警不阻塞） |
| 把 oracle 评分作为 R6 分量 | 绕过 45 门禁 | 自身也过 45 LLM 裁判校准 |

**Oracle 三模式**：

| 模式 | 输入 | 评估方法 | 适用场景 |
|---|---|---|---|
| **D2-Oracle** | ArchitectureGraph + BuildPlan | 逆向分析器（33-REA 独立调用）+ 45 E-H1~H5 门禁重跑 | D2-B 方案验证 |
| **D3-Oracle** | IntentPrediction + KnowledgeCombo | 第二独立 intent_engine 规则校验 + shadow A/B 反事实验证 | D3-A/D3-B 验证 |
| **Trade-Oracle** | 交易决策 + recall trace | DomainCouplingHead 反事实验证 + shadow 回测 Wilcoxon | D1 交易决策验证 |

### 3.4 防古德哈特陷阱（P5 脚手架披露卡原则）

每次生成/评测必须附脚手架披露卡——**脚手架贡献 ≠ 涌现贡献**：

```json
{
  "scaffold_disclosure": {
    "composition": ["33-REA architecture_pattern_detector", "45 E-H1 security scan", "41 RAG hybrid_search"],
    "version": "0.1",
    "expected_bias": 0.08,
    "acknowledged": true,
    "ablation_needed": true
  },
  "ablation_plan": {
    "scaffold_removed": "纯 prompt 调优无 REA 分析器",
    "expected_drop": "-10pp",
    "post_ablation_threshold": "≥ 3pp 仍高于 baseline"
  }
}
```

**门禁**：脚手架消融后仍显著高于 baseline → 才可申报涌现。

### 3.5 三重漂移检测（P6 三重验证原则）

编排器内置漂移检测，触发条件升级为三重验证：

```python
def classify_drift(psi: float, ks_drifted: bool, var_exceeded: bool) -> str:
    """三重漂移检测
    
    PSI 阈值（行业共识）：
      < 0.1  → stable
      0.1-0.25 → minor_drift  
      > 0.25  → severe_drift
      
    KS + VaR 作为第二/第三门：
      PSI minor + KS drifted → 升级 severe
      PSI severe + VaR exceeded → 确认 severe
    """
    if psi < 0.1 and not ks_drifted and not var_exceeded:
        return "stable"
    elif psi >= 0.25 or (psi >= 0.1 and ks_drifted and var_exceeded):
        return "severe_drift"
    else:
        return "minor_drift"
```

### 3.6 反馈信号扩维（session outcome 结构化）

当前 session outcome 未结构化落盘——ASIL 第 ⑦ 步 verify 需要它作为弱监督信号：

```json
{
  "session_id": "xxx",
  "timestamp": "ISO8601",
  "intent": {"predicted": "architecture-design", "actual": "python-development", "correction": "edit"},
  "outcome": {"success": false, "correction": true, "correction_type": "reject"},
  "recall_effectiveness": {"n_steps": 3, "n_actions": 1, "hit_rate": 0.67},
  "time_to_action_ms": 125000,
  "errors": [{"type": "hallucination", "severity": "high"}, {"type": "tool_missing", "severity": "medium"}]
}
```

---

## §4 ASIL-Orchestrator 实现规范

### 4.1 技术栈约束

| 约束 | 值 | 来源 |
|---|---|---|
| 语言 | Python 3.10+ | 项目主栈 |
| GPU | 零（H2 硬约束） | TRAIN-BASE H2 |
| 训练算法 | 贝叶斯在线学习 + GRPO 轻量 RL（冻结权重）+ 统计检验 | TRAIN-BASE H2 |
| 外部依赖 | 仅 numpy + scipy + 项目已有模块 | 极简原则 |
| 代码量预算 | MVP ≤ 500 行 Python | 单文件可审查 |

### 4.2 Orchestrator 核心模块

```
asil/
├── orchestrator.py          # 主入口 + PipelineExecutor
├── trigger_scanner.py       # 六种触发源扫描
├── drift_detector.py        # 三重漂移检测（PSI + KS + VaR）
├── pipeline_builder.py      # Pipeline schema 构造
├── verdict_router.py       # verdict → feedback → verify 路由
├── feedback_writer.py       # 自动回写 capability_gaps + 认知库 verify
├── metrics_collector.py     # E4/E5 指标自动收集
├── kill_switch.py           # 分层 Kill Switch 链
└── __tests__/
    ├── test_trigger_scanner.py
    ├── test_drift_detector.py
    ├── test_pipeline_builder.py
    └── test_verdict_router.py
```

### 4.3 核心接口定义

```python
class ASILOrchestrator:
    """Agentic Self-Improvement Loop 编排器"""
    
    def run_pipeline(self, trigger: PipelineTrigger) -> PipelineResult:
        """
        执行完整 ASIL 管道（§1.2 ①-⑧）
        - 全链 FAIL-OPEN，单步失败不阻塞后续
        - trace_id 全链路传递
        - 每步结果落盘 events/asil/*.jsonl
        """
    
    def trigger_scan(self) -> list[PipelineTrigger]:
        """
        扫描六种触发源（§1.3）
        返回需要跑的触发列表
        """
    
    def auto_verify_writeback(self, verdict: ExperimentVerdict) -> None:
        """
        verdict candidate/verified → 自动触发认知库 verify 回写
        - 从 48 verdict dashboard 读取
        - 调用 cognitive verify 更新 Beta 分布
        - OOD 区间检查
        """
    
    def kill_switch_check(self, context: KillSwitchContext) -> KillSwitchAction:
        """
        分层 Kill Switch 检查（§6）
        返回 no_op / reduce_position / pause_new / halt_all
        """
```

### 4.4 Pipeline 执行状态机

```
PENDING ──scan──▶ READY ──start──▶ RUNNING ──step_done──▶ RUNNING ──all_done──▶ COMPLETE
                                         │
                                         ├──step_fail──▶ RUNNING（记录，继续）
                                         │
                                         └──severedrift──▶ ABORTED（Kill Switch 触发）

COMPLETE ──verdict──▶ feedback_write ──verify_writeback ──distill ──EVOLVED
COMPLETE ──rejected──▶ feedback_write ──record_failure ──REJECTED
COMPLETE ──falsified──▶ feedback_write ──record_falsified ──FALSIFIED
```

---

## §5 运行模式与安全

### 5.1 三模式切换

| 模式 | 行为 | 何时用 |
|---|---|---|
| **SHADOW（默认）** | 全部只读观察 + 记录 + 评估，不触发任何域内实际行为 | 所有 ASIL 管道默认 |
| **ACTIVE-LIMITED** | 只激活第 ⑦⑧ 步（verify 回写 + 蒸馏），前 ①-⑥ 保持 shadow | D2-B 已 E-H1~H5 硬项通过 + D3-B 已有 ≥20 在线 shadow A/B 样本 |
| **ACTIVE-FULL** | 全链激活（包括 D2 实际开发、D3 预测注入） | bcrm2 切流后 + 三维涌现 verified + 连续 14 天零 Kill Switch |

**从 SHADOW → ACTIVE-LIMITED → ACTIVE-FULL 的升级判据**：与 48 SPEC v0.5 §5 七关门禁一致。

### 5.2 隔离与审计

| 隔离类型 | 方式 | 来源 |
|---|---|---|
| trace_id 区分 | 影子模式 trace_id 前缀 `shadow-` | S2 约束 |
| OOD 隔离 | 沿用 48 P0-1 hooks（CaseIngestGate + BayesianMemoryUpdater） | 48 SPEC §4.0 第 9 条 |
| 数据版本化 | Pipeline 每步记录 data_snapshot sha256 | 48 SPEC §3.6 |
| 产物隔离 | ASIL 产物落 `48-涌现架构/events/asil/`，不写域内目录 | FAIL-OPEN |
| 审计链 | receipt_hash（调用方传入）+ pipeline_id + trace_id 可 join | H3 硬约束 |

---

## §6 Kill Switch 链（P7 Fail-closed 底线原则）

### 6.1 分层 Kill Switch

| 级别 | 触发条件 | 动作 | 来源 |
|---|---|---|---|
| **L0 正常** | 三重漂移检测 stable + oracle_confidence ≥ 0.5 + 无异常 | 正常运行 | 基线 |
| **L1 Warning** | PSI minor_drift 或 KS drifted 或 oracle_confidence < 0.5 | 告警日志 + ASIL 降频（每天 → 每周） | 行业标准 |
| **L2 Reduce** | PSI severe_drift + KS confirmed + VaR exceeded | ASIL 暂停所有 ACTIVE 模式，降级 SHADOW，建议触发 E3 coupling 复测 | Barclays/JPM |
| **L3 Pause** | 连续 3 天 L2 + D1 PnL 滚动窗口 Sharpe < 0.5 | D2/D3 生成物一律不准进入 45 评估 | 交易风控 |
| **L4 Halt** | 日亏 2% + PSI > 0.25 + 连续 3 次 ASIL pipeline falsified | 所有 ASIL 管道暂停，强制人工审查 | 行业标准 |

### 6.2 贝叶斯 VaR 拦截（H5 约束）

```python
def bayesian_var_intercept(decision_confidence: float, target_var: float = 0.05) -> str:
    """
    用 verify 的 Beta 分布置信度计算决策 VaR
    
    - 置信度 < 0.3 → 自动拦截（建议不生成）
    - 置信度 < 0.5 → 降为建议，不进入 45 评估
    - 置信度 ≥ 0.5 → 正常评估
    
    来源：SR 11-7 贝叶斯 VaR 回测 + H5 硬约束
    """
    if decision_confidence < 0.3:
        return "block"
    elif decision_confidence < 0.5:
        return "downgrade_to_suggestion"
    else:
        return "allow"
```

---

## §7 度量与验收

### 7.1 ASIL 自身度量

| 度量 | 定义 | 目标 | 数据源 |
|---|---|---|---|
| **M-ASIL-0 pipeline_completion_rate** | 完整跑完 ①-⑧ 的管道数 / 触发数 | ≥ 0.95（允许单步 FAIL-OPEN） | ASIL events |
| **M-ASIL-1 verify_writeback_rate** | verdict candidate/verified → verify 回写数 / candidate 总数 | ≥ 1.0（自动回写） | ASIL verify 日志 |
| **M-ASIL-2 distill_effectiveness** | 蒸馏后 skill/pattern 被 recall 命中次数 / 总蒸馏数 | ≥ 0.3（被后续管道消费） | recall stats |
| **M-ASIL-3 feedback_latency_p50** | 触发 → feedback_write 完成的 P50 延迟 | ≤ 10min | ASIL events |
| **M-ASIL-4 kill_switch_frequency** | Kill Switch 触发次数 / 运行天数 | ≤ 0.1（每周 ≤ 0.7 次） | kill_switch 日志 |
| **M-ASIL-5 e4_self_correction_rate** | 反思→修复精确 join 成功率（E4 判据） | 持续上升趋势 | 48 E4b 数据 |
| **M-ASIL-6 e5_phase_transition_proxy** | 记忆规模/案例规模 与 recall_hit_rate 的形状检验（E5 判据） | concave = 真加速 | 48 metrics 历史 |

### 7.2 外部验收判据（48 七关门禁）

ASIL 不放宽 48 SPEC v0.5 七关门禁：

1. ✅ 双度量（连续 + 离散 0/1）
2. ✅ OOD walk-forward 隔离（P0-1 hooks）
3. ✅ 稳健性压测
4. ✅ 辩论正反方评审（dream-debate SKILL）
5. ✅ 消融归因（脚手架披露卡 + 数据红利消融）
6. ✅ 可复现（预注册 + 固定 seed）
7. ✅ 人工复核最终裁决

---

## §8 实施路径

### Phase 1：Orchestrator MVP（1-2 周）

**交付物**：
- `asil/orchestrator.py` ~500 行
- 六种触发源扫描
- 完整 Pipeline schema 构造
- verify 自动回写 hook
- 三重漂移检测
- 核心接口 TDD（≥ 20 用例）

**验收**：
- 跑通完整 ASIL 管道（8 步）至少 1 次
- verify 回写自动触发 1 次成功
- drift_detector PSI/KS/VaR 三档判定正确
- 全部单测通过

### Phase 2：反馈信号扩维 + Oracle 层（2-3 周）

**交付物**：
- session outcome 结构化落盘（schema + 自动写入）
- Oracle 验证层抽出为独立角色
- D3-B 在线 shadow A/B runner
- D2-B 真实 45 门禁 E-H1~H5 集成

**验收**：
- session outcome 结构化覆盖率 ≥ 30%
- Oracle 独立 cross-check 通过 ≥ 3 次
- D3-B 在线 shadow A/B 积累 ≥ 20 样本

### Phase 3：跨域迁移闭环 + 三维涌现验证（3-4 周）

**交付物**：
- T-I2E（意图→工程）在线 shadow A/B
- T-E2T（工程→交易）在线 shadow A/B
- X-A 三维迁移从 proxy 升级为真实在线 A/B
- 观测 G₁₂₃ 三阶交互是否稳定为正

**验收**：
- T-I2E/T-E2T 各 ≥ 30 shadow 天
- G₁₂₃ 95% CI 不含 0 且方向为正
- Ω(D1,D2,D3) > 0 通过协同复核
- 可考虑申报"三维涌现 verified"

---

## §9 边界声明（硬约束，不可突破）

| # | 约束 | 来源 | 命中关键词 |
|---|---|---|---|
| **C1** | **ASIL 不替代 48 v0.5 Phase E0-E6 和 D1/D2/D3** | §2.1 三层职责 | 不替代、叠加层 |
| **C2** | **所有 ASIL 管道默认 SHADOW/FAIL-OPEN 模式** | §5.1 三模式 | 默认、FAIL-OPEN |
| **C3** | **D2/D3 生成物零执行权，不准改生产代码** | 48 v0.5 §0.2 | 零执行权、禁止 |
| **C4** | **不引入神经网络权重微调，只用贝叶斯 + GRPO 轻量 RL** | TRAIN-BASE H2 | 不得、唯一、必须 |
| **C5** | **verify 回写必须过 OOD 隔离 + Mandate 门控** | 48 P0-1 hooks + H7 | 必须、硬门禁 |
| **C6** | **Kill Switch 链 Fail-closed 优先** | §6.1 L4 | 必须、优先 |
| **C7** | **脚手架披露卡 + 数据红利消融是门禁前置** | §3.4 + P5 | 必须、前置 |
| **C8** | **PSI 阈值硬编码 0.1/0.25，不得运行时调** | H8 | 必须、默认、阈值 |
| **C9** | **实盘风控域决策置信度 < 0.3 自动拦截** | H5 + §6.2 | 必须、自动、上限 |
| **C10** | **不新建子系统所有权，沿用 48/33/45/35 边界** | 48 SPEC §8 | 不得、边界 |

---

## §10 反模式（禁止）

| # | 反模式 | 为什么禁止 | 来源 |
|---|---|---|---|
| **X1** | 把 ASIL 循环加速到分钟级频率 | 反思/进化周期相对于主交易周期必须足够"慢"，过快蒸馏=过拟合噪声（时间尺度分离警示） | BIO §7.2 |
| **X2** | 跳过脚手架消融直接申报涌现 | 古德哈特定律——指标一旦变成目标就失效；脚手架收益被误报为涌现 | CAMEL/MetaGPT 反模式 + P5 |
| **X3** | 让单一 PSI 漂移检测决定所有 Kill Switch | 单指标不可靠，必须三重验证 | P6 三重验证原则 |
| **X4** | ASIL 生成物直接进生产链路 | 违反零执行权硬约束（C3） | 48 v0.5 硬约束 |
| **X5** | 跳过影子验证直接切 ACTIVE | FCA RTS 6 强制影子验证 + P4 原则 | 金融监管 |
| **X6** | 让生成者自己评审自己的生成物 | 会自我强化幻觉（Gödel Agent 教训） | P3 独立裁判原则 |
| **X7** | 把 scale 增长当涌现 | E5 要求相变拐点 + 幂律 + σ≈1 三件套，不是线性变好 | 48 v0.5 §1 E5 |
| **X8** | ASIL 循环没有 Kill Switch 链 | Fail-closed 是金融级系统底线 | P7 + H6 + §6 |

---

## §11 外部成熟项目参考

### 11.1 学术论文

| # | 论文 | 年份 | 核心贡献 | ASIL 映射 |
|---|---|---|---|---|
| 1 | Reflexion (Shinn et al.) | ICLR 2023 | 反思使 AlfWorld↑22%、HotPotQA↑20%、HumanEval↑11% | P1 过程奖励 + 第 ⑤ 步 Oracle 反思 |
| 2 | Voyager (Wang et al.) | TMLR 2024 | Minecraft 终身学习：3.3× 物品、2.3× 距离、15.3× 里程碑 | P2 Skill Library（广义认知记忆库） |
| 3 | RETROFORMER | ICLR 2024 | 回顾性 + replay buffer + policy gradient prompt 优化 | ASIL 第 ⑧ 步蒸馏 + prompt 进化 |
| 4 | Gödel Agent | 2024 | 自引用递归改进 | ASIL 循环结构（每步递归前一步输出） |
| 5 | AgentFactory | 2025 | 可执行 subagent 积累与复用 | D2-B 方案生成 + 复用 |
| 6 | Meta-Team | 2025 | 协作自进化 + timeout 反馈 | Oracle 层 timeout 机制 |
| 7 | Alpha-R1 | 2025 | GRPO + 市场反馈 RLHF | TRAIN-BASE TB5 GRPO + ASIL 第 ⑧ 步 |
| 8 | EvolveR | 2025 | 自蒸馏→原则库→检索→RL | ASIL 完整循环结构 |
| 9 | AlphaPareto | 2025 | 四维向量奖励 + MAP | §3.2 六维 reward component |
| 10 | ADTS | 2025 | Thompson Sampling regime gate | Phase 3 regime 感知切换 |

### 11.2 工业工程实践

| # | 来源 | 核心实践 | ASIL 映射 |
|---|---|---|---|
| 1 | **FCA RTS 6** | 强制影子验证（de facto mandatory） | P4 原则 + 5.1 SHADOW 默认 |
| 2 | **Two Sigma** | 四层 AI 角色分层（Advisory/Oracle/Operational/Agentic） | §3.3 Oracle 独立角色 |
| 3 | **Barclays/JPM** | 三重漂移检测（PSI + K-S + VaR） | §3.5 三重验证 |
| 4 | **Renaissance/Citadel** | 公开资料极少，但"版本化一切 + monitor drift"为行业共识 | P2/P6 原则 |
| 5 | **SR 11-7** | 贝叶斯 VaR 回测（比交通灯测试好） | §6.2 VaR 拦截 |
| 6 | **MAS SAFR** | Agent 运行时治理（Safeguard + Filter + Audit + Recourse） | §6 Kill Switch 链 |
| 7 | **EU AI Act 2026.8** | 风险管理 + 数据治理 + 可解释性 + 人工监督 | C5/C6/C9 硬约束对齐 |

### 11.3 反模式与争议

| # | 来源 | 反模式 | ASIL 防护 |
|---|---|---|---|
| 1 | **Schaeffer 2023**（NeurIPS） | LLM 涌现海市蜃楼：29 度量 25 无涌现 | §3.4 脚手架披露卡 + 七关门禁 |
| 2 | **CAMEL** | 多 Agent 角色扮演涌现幻觉：收益来自脚手架 | X2 反模式禁止 + C2 默认 SHADOW |
| 3 | **Sparks of AGI** | 不可复现 + 利益相关 + 数据污染 | 48 可复现门禁 + receipt_hash 审计 |
| 4 | **古德哈特定律** | 指标一旦变成目标就失效 | X2 反模式 + R1-R6 多维度 reward |

---

## §12 与现有体系的关系

### 12.1 与 48 v0.5 Phase E0-E6 的关系

| 48 Phase | ASIL 关系 |
|---|---|
| E0 基线 | ASIL 训练的前置基线 |
| E1 广播总线 | ASIL 编排器的事件通道（shadow） |
| E2 做梦器 | ASIL 第 ③ 步 D2-B 的生成器 |
| E3 coupling | ASIL 第 ⑤ 步 Oracle 的 Trade-Oracle 验证手段 |
| E4 度量面板 | ASIL 第 ⑦ ⑧ 步的指标收集基础设施 |
| E5 规模相变 | ASIL 收敛判据（M-ASIL-6） |
| E6 需求闭环 | ASIL 第 ⑥ 步 feedback 的下游路由 |

**ASIL 复用 E0-E6 全部基础设施，不改变其行为**。

### 12.2 与 48 v0.5 三维 D1/D2/D3 的关系

ASIL 的核心循环（§1.2）就是对三维的编排：

- ② 步骤 = D3（意图涌现）
- ③ 步骤 = D2（技术架构涌现）
- ⑤ + Oracle 交叉验证 = D1/D2/D3 的联合评估

三维是 ASIL 的"涌现目标"，ASIL 是三维的"训练编排"。

### 12.3 与 SPEC-NN-FEEDBACK-GATEWAY 的关系

```
ASIL（离散结构的 Agentic 训练）
    │ 蒸馏沉淀的高价值样本/度量
    ▼
48 NN 反馈网关（统一样本 → 40 参数训练建议）
    │ 建议制 + 审计 + provenance 隔离
    ▼
40 主神经网络（梯度更新）
```

两个层级不冲突，互补：NN 训练连续参数，ASIL 训练离散结构。前者擅长插值，后者擅长组合泛化（E1 判据）。

### 12.4 与 TRAIN-BASE 的关系

TRAIN-BASE 的 TB1-TB5 是 ASIL 的底层训练算法：

| TRAIN-BASE | ASIL 位置 |
|---|---|
| TB1 PSI 漂移检测 + K-S 补 + Kill Switch | §3.5 三重漂移 + §6 Kill Switch |
| TB2 Beta 共轭更新 | §1.2 第 ⑦ 步 verify |
| TB3 AlphaPareto 四维 → 六维 reward | §3.2 六维 reward component |
| TB4 Thompson Sampling regime gate | Phase 3 regime 感知切换 |
| TB5 GRPO 轻量 RL loop | §1.2 第 ⑧ 步蒸馏 prompt 进化 |

---

## §13 算力预算

| 环节 | 算力需求 | 实现方式 |
|---|---|---|
| drift_detector 三重检测 | O(N) 直方图/KS/正态分布，毫秒级 | numpy + scipy，零 GPU |
| pipeline 构建 | O(1) schema 组装 | 原生 dict/json，零依赖 |
| verify 回写 | O(1) Beta 分布更新 | math.beta_inv，零依赖 |
| Oracle cross-check | O(K) K=分析器数 × 步骤数，秒级 | 已有 33-REA 分析器，壳内调用 |
| Kill Switch 链 | O(1) 阈值比较 | 常量级 |
| GRPO 轻量 RL loop | O(K) K=策略数 × 迭代次数，秒级 | 冻结 LLM 权重，只调策略输出格式 |

**结论**：零 GPU、单 CPU 4C16G 全环节可跑。所有训练算法都是贝叶斯 + 统计检验 + 策略格式调优。

---

## 变更日志

| 版本 | 日期 | 变更 |
|---|---|---|
| v0.1 | 2026-11-10 | 初稿完成：8 步核心循环 + 三层架构 + 7 条工程原则（P1-P7）+ 10 条硬约束（C1-C10）+ 8 条反模式（X1-X8）+ 10 篇论文 + 7 项工业实践 + 4 个反模式 |
