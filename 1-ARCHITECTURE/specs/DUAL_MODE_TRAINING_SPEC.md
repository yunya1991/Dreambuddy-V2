# SPEC-20261011 — 双模式学习训练架构（主动横向 + 被动纵深）

> **版本**: v0.2 (评审后修订)
> **日期**: 2026-10-11
> **作者**: Trae + User
> **状态**: Draft（评审通过 → 待实施）
> **关联**: SPEC-20261009-SOLUTION-PATTERN-LEARNER (SPL v0.4), 33-REA逆向解析工程, dream-completion-evolution-workflow
> **方法论**: recall → 系统调研 → 双模式设计 → SPEC v0.1 → 同行评审(Major4) → SPEC v0.2
> **v0.2 变更**:
> - M1: 被动训练重新定义为「Trae在线辅导训练」，非单案例统计训练。Trae作为教师角色，利用完整上下文监控前端训练流程、纠正辅导、评估优化
> - M2: 补充数据源质量门控——Trae案例质量高直接入库，认知C级记忆需verify升级后入库，SKILL/文档需提取结构化信号
> - M3: 增加33-REA对Trae增量代码适用性验证作为P1前置条件
> - M4: 定义被动训练专属评估指标（辅导质量分/纠正次数/训练成果提升）
> - m1-m6: 补充训练依赖顺序、资源配额依据、采集频率、CaseIngestGate校准、替代方案对比、SPL就绪度检查

---

## 0. Executive Summary

### 0.1 核心命题

前端应用系统的学习训练采用**双模式架构**：

| 模式 | 驱动方式 | 数据规模 | 训练机制 | 类比 |
|------|---------|---------|---------|------|
| **主动训练（横向）** | 算法自动扫描 | 大规模批量（Trae对话历史+认知+SKILL+文档） | 统计学习（桶满触发） | 研究生日常自学，广泛阅读积累 |
| **被动训练（纵深）** | Trae收尾触发 | 单案例（本次实际工程） | **Trae在线辅导训练**：33-REA解析+Trae监控纠正+前端训练尝试 | 导师带课题，在线讲解+纠正+考核 |

**核心原则**：
- **主动训练** = 广度覆盖：批量采集对话历史等多源数据，累积到桶满阈值后触发统计训练
- **被动训练** = 深度质量：Trae收尾后以教师角色在线，利用完整上下文对前端系统进行实时辅导训练，不依赖案例数量
- 两者互补：主动训练提供"量"的积累，被动训练提供"质"的突破

### 0.2 设计驱动力

| 编号 | 驱动力 | 来源 |
|------|--------|------|
| F1 | 收尾SKILL执行后未触发前端学习训练，存在断点 | 调研发现 |
| F2 | SPL已有5层训练器+TDR基础设施，但数据源仅限Trae记忆 | 调研发现 |
| F3 | 33-REA可逆向解析算法模式，为TDR提供结构化标注 | 调研发现 |
| F4 | 主动+被动双模式符合认知科学"广泛学习+刻意练习"原则 | 设计决策 |
| F5 | Trae案例质量高，可从历史对话大规模采集达到训练数量 | 用户确认 |
| F6 | Trae收尾时有完整上下文，适合作为教师在线辅导训练 | 用户确认 |
| F7 | 大认知系统（认知/SKILL/文档/知识库）的经验未被训练系统消费 | 调研发现 |

### 0.3 范围边界

**In Scope:**
- 主动训练数据源扩展：Trae对话历史批量采集 + 大认知系统 + 33-REA批量逆向
- 被动训练（Trae在线辅导）触发链路：收尾SKILL → 33-REA解析 → Trae在线监控前端训练
- 33-REA → TDR 数据转换管线（rea_to_tdr_adapter）
- 双模式资源分配与优先级调度
- 训练质量评估与反馈闭环

**Out of Scope:**
- 不修改SPL v0.4的5个层专属训练器内部逻辑（只扩展数据源和触发方式）
- 不修改认知系统4-MEMORY后端（只通过cognitive-client.ts接入）
- 不做LLM权重微调（SPL是非参数化CBR+轻量在线学习）
- 不修改33-REA的核心解析逻辑（只消费其输出）

---

## 1. 调研结论（事实清单）

### 1.1 SPL现有训练架构

| 组件 | 路径 | 现状 |
|------|------|------|
| TDR中央训练数据仓库 | `scripts/case_bank_server.py` | SQLite存储，含layer_tags/baseline_output/quality/confidence |
| 5个层专属训练器 | `3.1-FRONTEND/src/lib/solution-pattern-learner/` | S层Intent/DSH ExecutionPath/C层Reflection/G层GraphStructure/LLM Prompt |
| CaseIngestGate | `1-ARCHITECTURE/dreamos/core/compute/case_ingest_gate.py` | 四维评估(novelty/significance/anomaly/reproducibility) → INGEST/DEFERRED/SKIP |
| Trae Memory Bridge | `3.1-FRONTEND/src/lib/case-bank-client.ts` | 从session_memory提取四元组(intent/actions/outcome/learned) |
| 训练依赖顺序 | SPL SPEC §4.3 | S+G并行 → DSH → C → LLM → 全链路联调 |
| 桶满触发阈值 | SPL SPEC §4.2 | S=100, DSH=50, C=50, G=30, LLM=30 |

**现有断点**：
1. TDR数据源仅限Trae记忆，大认知系统和33-REA未接入
2. 训练触发方式仅"桶满触发"，无"收尾触发的在线辅导训练"模式
3. 收尾SKILL的record tags不含`hermes反思`，不触发自进化学习

### 1.2 33-REA逆向解析能力

| 能力 | 输出 | 可转化为TDR字段 |
|------|------|----------------|
| 架构分层 | 模块依赖图 | `dependency_graph` (G层) |
| 调用链追踪 | 调用路径+行号 | `execution_path` (DSH层) |
| 关键算法还原 | 算法模式(递归/分治/DP/迭代) | `solution_pattern` (DSH/C层) |
| Evidence结构 | result/level/provenance/confidence/known_gaps/observations | `quality`/`known_gaps`/`baseline` (全层) |
| Git历史溯源 | 作者+时间+变更次数 | `provenance` (元数据) |

**33-REA DSH节点**：
- `S33_rea_analyze(target, scope)` → 整体架构分析
- `S33_rea_trace(target, feature, entry)` → 功能调用链追踪
- `S33_compare(target_a, target_b)` → 两工程对比

### 1.3 大认知系统数据资产

| 系统 | 数据 | 质量特征 | 入库策略 |
|------|------|---------|---------|
| 认知记忆 | content/quality_level/confidence/tags | C级占98%，B级以上不足2% | **B级以上直接入库，C级需verify升级后入库** |
| SKILL系统 | SKILL.md + registry + dep-graph | 结构化，质量较高 | 提取execution_template入库 |
| 文档管理 | 0-系统文档管理/INDEX.md | 参考知识，非解题案例 | 提取domain_knowledge作为G层背景 |
| 知识库 | 2-KNOWLEDGE chunks + vectors | 参考知识 | 提取knowledge_context作为LLM层上下文 |
| 索引系统 | 文档路径+标题+摘要 | 元数据 | 提取reference字段 |

### 1.4 收尾SKILL现状

| 步骤 | 行为 | 是否触发学习训练 |
|------|------|----------------|
| 1. 验收门禁 | dream-acceptance-verify五维验收 | ❌ |
| 2. 代码提交 | dream-code-commit-sync-workflow | ❌ |
| 3. 文档同步 | dream-doc-sync-workflow | ❌ |
| 4. SKILL治理 | dream-skill-index-governance | ❌ |
| 5. 认知闭环 | record(tags="wrapup,收尾,认知闭环,完成闭环,<域>") | ⚠️ 仅触发收尾SKILL本身，不触发自进化 |
| 6. 最终报告 | wrapup_report.md | ❌ |

**TAG_HOOKS映射**（cognitive_mcp_server.py L271-L291）：
- `wrapup` → dream-completion-evolution-workflow（收尾SKILL本身）
- `hermes反思` → dream-self-iteration-workflow（自进化学习）← 当前未被触发
- `SKILL` → skill-creator ← 当前未被触发

### 1.5 Trae案例质量分析

**用户确认**：Trae案例质量实质上比较高，且案例数可从历史对话中提取，数量充足。

**质量特征**：
- 每个Trae会话包含完整的intent→actions→outcome→learned四元组
- 收尾案例经过五维验收，质量更高
- Trae有完整上下文，可作为教师角色在线辅导

---

## 2. 双模式训练架构设计

### 2.1 整体架构

```
┌─────────────────────────────────────────────────────────────────┐
│                    双模式学习训练调度器                            │
│              (DualModeTrainingOrchestrator)                      │
├──────────────────────────┬──────────────────────────────────────┤
│   主动训练（横向）         │   被动训练（纵深·Trae在线辅导）        │
│   算法自动扫描             │   Trae收尾触发                        │
│   大规模批量统计训练        │   单案例·Trae教师在线辅导              │
│   桶满触发                │   不依赖案例数量                       │
├──────────────────────────┼──────────────────────────────────────┤
│ 数据源:                   │ 数据源:                               │
│  • Trae对话历史(批量采集)  │  • 本次收尾案例(验收通过)              │
│  • 认知记忆(B级以上)       │  • 33-REA逆向解析本次工程代码          │
│  • SKILL索引               │  • 收尾报告 + 验收证据                 │
│  • 文档/知识库             │  • Trae完整上下文(教师视角)            │
│  • 33-REA批量逆向          │                                        │
├──────────────────────────┼──────────────────────────────────────┤
│ 触发: 定时扫描 + 桶满      │ 触发: 收尾SKILL Step 5.5             │
│ 节奏: 每日/每周            │ 节奏: 每次收尾(Trae在线)              │
│ 资源: 后台低优先级         │ 资源: Trae在线协同(中优先级)          │
└──────────────────────────┴──────────────────────────────────────┘
                              │
                              ▼
                    ┌───────────────────┐
                    │  TDR 中央训练仓库  │
                    │  (layer_tags分层)   │
                    └─────────┬─────────┘
                              │
                              ▼
                    ┌───────────────────┐
                    │  5个层专属训练器    │
                    │  S/DSH/C/G/LLM     │
                    └─────────┬─────────┘
                              │
                              ▼
                    ┌───────────────────┐
                    │  评估与反馈闭环     │
                    │  复现/超越/辅导质量  │
                    └───────────────────┘
```

### 2.2 主动训练（横向·批量统计）

**定位**：算法驱动的广度学习，批量采集多源数据，累积到桶满阈值后触发统计训练，寻找跨案例的共同最优模式。

**数据源采集管线**：

```
主动训练采集器 (ActiveTrainingCollector)
    │
    ├─ Trae对话历史批量采集: session_memory → TDR (已有, Trae Memory Bridge)
    │   质量: 高(用户确认) → 直接入库
    │
    ├─ 认知系统采集: cognitive_memory.db → recall → 过滤 → TDR (新增)
    │   质量门控: B级以上直接入库，C级需verify升级后入库
    │
    ├─ SKILL系统采集: registry + SKILL.md → 结构化提取 → TDR (新增)
    │   转换: execution_template → DSH层训练数据
    │
    ├─ 文档知识库采集: INDEX.md + 2-KNOWLEDGE → 背景知识提取 → TDR (新增)
    │   转换: domain_knowledge → G层背景, knowledge_context → LLM层上下文
    │
    └─ 33-REA批量逆向: 扫描项目代码 → algorithm_reducer → TDR (新增)
        转换: algorithm_pattern → DSH层, dependency_graph → G层
```

**采集调度**：
- 频率：每日凌晨低峰期执行（不干扰用户操作）
- 优先级：低（后台任务）
- 增量采集：只处理上次采集后的新数据
- 质量门控：所有采集数据经过CaseIngestGate四维评估 + 数据源专属质量规则（见§1.3）

**训练触发**：
- 复用SPL现有"桶满触发"机制
- 各层桶满阈值：S=100, DSH=50, C=50, G=30, LLM=30
- 训练器按依赖顺序执行：S+G并行 → DSH → C → LLM

### 2.3 被动训练（纵深·Trae在线辅导）

**定位**：Trae收尾后以**教师角色在线**，利用完整上下文对前端系统进行实时辅导训练。不依赖案例数量，强调深度质量和纠正优化。

**核心理念**：
- Trae = 教师（有完整上下文，理解本次工程的设计意图、约束、验收标准）
- 33-REA = 教具（解析本次工程代码，提取算法模式和调用链作为教学材料）
- 前端系统 = 学生（基于33-REA解析结果进行训练尝试）
- Trae在线 = 监控训练流程，纠正错误，评估优化方向

**触发链路**：

```
收尾SKILL Step 5 (认知record)
    │
    ▼
Step 5.5 (新增) 被动训练触发 — Trae在线辅导
    │
    ├─ 1. 收尾案例价值评估 (CaseIngestGate)
    │     ├─ novelty: 与历史案例的差异度
    │     ├─ significance: SPEC完成度+验收通过等级
    │     ├─ anomaly: 是否有红旗/异常
    │     └─ reproducibility: 验收证据是否完整
    │     → 决策: INGEST(在线辅导) / DEFERRED(暂缓) / SKIP(跳过)
    │
    ├─ 2. 若INGEST: 33-REA逆向解析本次工程代码
    │     ├─ S33_rea_analyze(案例涉及的文件路径) → 架构+依赖图
    │     ├─ S33_rea_trace(关键功能) → 调用链+算法模式
    │     └─ → Evidence + 算法模式 + 调用链 (作为教学材料)
    │
    ├─ 3. rea_to_tdr_adapter: 33-REA输出 → TDR SolutionCase
    │     ├─ algorithm_pattern → layer_tags=DSH (教学材料)
    │     ├─ call_chain → execution_path
    │     ├─ dependency_graph → layer_tags=G
    │     ├─ known_gaps → C层反思材料
    │     └─ evidence_level → quality门控
    │
    ├─ 4. Trae在线辅导训练循环 (核心·非统计训练)
    │     │
    │     ├─ 4.1 前端系统基于33-REA解析结果进行训练尝试
    │     │     (不要求桶满，单案例即可启动)
    │     │
    │     ├─ 4.2 Trae实时监控训练流程
    │     │     ├─ 检查各层训练是否符合33-REA解析的算法模式
    │     │     ├─ 检查DSH执行路径是否与调用链一致
    │     │     ├─ 检查C层反思是否覆盖known_gaps
    │     │     └─ 检查G层图结构是否与依赖图匹配
    │     │
    │     ├─ 4.3 Trae纠正与辅导
    │     │     ├─ 发现训练偏差 → 给出纠正方向
    │     │     ├─ 发现遗漏 → 补充上下文提示
    │     │     ├─ 发现优质 → 强化正反馈
    │     │     └─ 记录纠正次数和类型
    │     │
    │     └─ 4.4 Trae评估训练成果
    │           ├─ 辅导质量分(0-100): 训练结果与33-REA解析的一致度
    │           ├─ 纠正次数: Trae介入纠正的次数
    │           ├─ 训练成果提升: 前端系统输出质量的前后对比
    │           └─ 改进建议: 后续训练优化方向
    │
    └─ 5. 辅导结果反馈
          ├─ 辅导质量分+纠正次数+提升幅度记录到TDR
          ├─ record认知记忆(tags="hermes反思,被动训练,在线辅导,收尾")
          ├─ 更新收尾报告训练状态
          └─ 触发dream-self-iteration-workflow (hermes反思tag)
```

**与统计训练的区别**：

| 维度 | 主动训练(统计) | 被动训练(在线辅导) |
|------|--------------|------------------|
| 数据规模 | 批量(桶满阈值) | 单案例(本次工程) |
| 训练机制 | 统计学习(模式挖掘/聚类/CBR) | Trae在线监控+纠正+评估 |
| Trae角色 | 离线(数据来源) | 在线(教师) |
| 目标 | 跨案例共同最优 | 单案例深度掌握 |
| 质量保证 | CaseIngestGate过滤 | Trae实时纠正 |

**触发条件**：
- 收尾验收通过（五维全通过或条件通过）
- CaseIngestGate评估为INGEST
- Trae在线（有完整上下文）

**资源策略**：
- 优先级：中（高于主动训练，低于用户交互）
- 超时：辅导循环总超时30分钟
- 异步：不阻塞收尾流程，收尾报告先完成，辅导后台执行
- Trae在线要求：辅导期间Trae保持上下文，可与前端训练系统交互

### 2.4 双模式资源分配

| 资源维度 | 主动训练 | 被动训练(在线辅导) |
|---------|---------|------------------|
| 执行时段 | 凌晨低峰期 | 收尾后立即 |
| CPU配额 | ≤30% | ≤50% |
| 内存配额 | ≤2GB | ≤4GB |
| 超时 | 8小时 | 30分钟 |
| 优先级 | 低 | 中 |
| 失败重试 | 是(次日重试) | 否(记录失败) |
| 并发 | 单实例 | 单实例(收尾串行) |
| Trae角色 | 离线 | 在线(教师) |

> **注**：资源配额为初始假设值，P3实施时根据实测数据调整。

**调度规则**：
- 被动训练进行时，暂停主动训练
- 主动训练进行时，被动训练可抢占（用户收尾优先）
- 两者都不阻塞用户交互

---

## 3. 33-REA → TDR 数据转换管线

### 3.1 rea_to_tdr_adapter 设计

**输入**：33-REA的Evidence结构 + 算法还原结果
**输出**：TDR SolutionCase（含layer_tags）

```python
# 33-REA输出结构 (Evidence)
evidence = {
    "result": "...",              # 结论
    "level": "L1/L2/L3/L4",        # 事实分级
    "provenance": "...",          # 来源
    "confidence": 0.0-1.0,        # 置信度
    "known_gaps": [...],          # 已知局限
    "observations": [...]         # 观察
}

algorithm_result = {
    "function": "...",
    "patterns": ["recursion", "divide_conquer", ...],  # 算法模式
    "pseudocode": "...",
    "evidence": Evidence
}

trace_result = {
    "feature": "...",
    "call_chain": ["func_a", "func_b", ...],  # 调用链
    "evidence": Evidence
}
```

**转换映射**：

| 33-REA输出 | TDR字段 | layer_tags | 说明 |
|-----------|---------|-----------|------|
| algorithm_result.patterns | `solution_pattern` | DSH, C | 算法范式(递归/分治/DP/迭代/累加器) |
| trace_result.call_chain | `execution_path` | DSH | 执行序列 |
| analyze_result.dependency_graph | `dependency_graph` | G | 模块依赖图 |
| evidence.known_gaps | `known_gaps` | C | 反思材料 |
| evidence.level | `quality` | 全层 | L1=S, L2=A, L3=B, L4=C |
| evidence.confidence | `confidence` | 全层 | 贝叶斯置信度 |
| evidence.observations | `learned` | LLM | 经验提取 |

### 3.2 layer_tags推断规则

```python
def infer_layer_tags_from_rea(rea_output: dict) -> List[LayerTag]:
    tags = []
    if "patterns" in rea_output:
        tags.append(LayerTag(layer="DSH", training_data={"patterns": rea_output["patterns"]}))
        tags.append(LayerTag(layer="C", training_data={"pattern_decision": rea_output["patterns"]}))
    if "call_chain" in rea_output:
        tags.append(LayerTag(layer="DSH", training_data={"execution_path": rea_output["call_chain"]}))
    if "dependency_graph" in rea_output:
        tags.append(LayerTag(layer="G", training_data={"graph": rea_output["dependency_graph"]}))
    if "known_gaps" in rea_output:
        tags.append(LayerTag(layer="C", training_data={"reflection": rea_output["known_gaps"]}))
    if "observations" in rea_output:
        tags.append(LayerTag(layer="LLM", training_data={"learned": rea_output["observations"]}))
    return tags
```

### 3.3 33-REA适用性验证（P1前置条件）

**目的**：验证33-REA对Trae增量代码（分散文件+混合语言+单次会话改动）的解析质量。

**验证方案**：
- 选取5个历史收尾案例
- 对每个案例涉及的文件跑S33_rea_analyze + S33_rea_trace
- 评估指标：
  - algorithm_pattern还原准确率（与Trae实际设计意图对比）
  - call_chain完整度（是否覆盖关键调用路径）
  - evidence_level分布（L1/L2/L3/L4占比）

**通过标准**：
- algorithm_pattern准确率 ≥ 70%
- call_chain覆盖关键路径 ≥ 80%
- 不通过则降级：33-REA仅作为辅助标注，主要依赖Trae文本四元组

---

## 4. 收尾SKILL集成设计

### 4.1 收尾SKILL步骤扩展

在现有步骤5（认知闭环）和步骤6（最终报告）之间，新增**Step 5.5: 被动训练触发 — Trae在线辅导**。

```
Step 5: 认知闭环 (record + verify)  [已有]
    ↓
Step 5.5: 被动训练触发 (新增)
    ├─ CaseIngestGate评估收尾案例
    ├─ 若INGEST: 33-REA逆向解析 → rea_to_tdr_adapter → TDR入库
    ├─ Trae在线辅导循环: 监控前端训练 → 纠正 → 评估
    └─ 辅导结果记录到认知 + 收尾报告
    ↓
Step 6: 最终报告 (含训练状态)  [已有, 扩展]
```

### 4.2 认知record tags扩展

收尾时的record tags从：
```
wrapup,收尾,认知闭环,完成闭环,<域>
```
扩展为（当被动训练INGEST时）：
```
wrapup,收尾,认知闭环,完成闭环,<域>,hermes反思,被动训练,在线辅导
```

**效果**：`hermes反思` tag 触发 dream-self-iteration-workflow，形成完整闭环。

### 4.3 FAIL-OPEN策略

| 异常 | 处置 |
|------|------|
| CaseIngestGate评估为SKIP | 跳过被动训练，记录原因 |
| 33-REA解析失败 | 跳过结构化标注，仅用文本四元组入库，Trae辅导基于文本进行 |
| Trae不在线/上下文丢失 | 降级为案例入库，等待下次主动训练批量处理 |
| 辅导超时 | 终止辅导循环，记录已完成的纠正和评估，不阻塞收尾 |
| TDR写入失败 | 记录到日志，下次主动训练时重试 |
| 系统资源不足 | 降级为DEFERRED，加入待训练队列 |

---

## 5. 实施计划

### 前置条件检查
- [ ] SPL v0.4的TDR + CaseRetriever已就绪
- [ ] SPL v0.4的CaseIngestGate已就绪
- [ ] 33-REA的S33_rea_analyze + S33_rea_trace已就绪
- [ ] 各训练器就绪状态确认（S/DSH/C/G/LLM）

### P0: 被动训练触发链路（最小闭环）
1. 收尾SKILL新增Step 5.5: 被动训练触发
2. CaseIngestGate接入收尾案例评估（校准significance维度：SPEC完成度+验收等级）
3. 收尾案例 → TDR入库（不绕过桶满，加入对应层训练桶）
4. Trae在线辅导循环框架（监控→纠正→评估，v0.1仅记录不自动纠正）
5. 认知record tags追加`hermes反思,被动训练`
6. 验收：收尾后TDR出现该案例，触发dream-self-iteration-workflow

### P1: 33-REA → TDR 数据管线
1. **33-REA适用性验证**（§3.3，5个案例验证）
2. 新建rea_to_tdr_adapter.py
3. 收尾时自动对案例代码跑S33_rea_analyze + S33_rea_trace
4. 33-REA输出转换为TDR SolutionCase（含layer_tags）
5. 33-REA标注数据作为被动训练的教学材料
6. 验收：TDR案例包含algorithm_pattern和dependency_graph字段

### P2: 主动训练数据源扩展
1. 新建ActiveTrainingCollector调度器
2. 认知系统采集器: cognitive_memory → B级过滤 → TDR
3. SKILL系统采集器: registry + SKILL.md → execution_template → TDR
4. 文档知识库采集器: INDEX + 2-KNOWLEDGE → 背景知识 → TDR
5. 33-REA批量逆向: 项目代码扫描 → TDR
6. 增量采集 + 质量门控
7. 验收：TDR数据源从1个(Trae记忆)扩展到5个

### P3: 双模式调度与资源管理
1. 新建DualModeTrainingOrchestrator
2. 主动/被动训练资源配额管理
3. 被动训练抢占主动训练
4. 训练队列 + 重试机制
5. 训练状态监控面板
6. 验收：双模式互不阻塞，资源使用符合配额

### P4: 评估与反馈闭环
1. 被动训练辅导质量分+纠正次数+提升幅度统计
2. 主动训练跨案例模式挖掘
3. 训练质量反馈到CaseIngestGate阈值调整
4. 训练效果可视化
5. 验收：可量化训练效果，支持阈值自动调优

---

## 6. 验收标准

| ID | 验收项 | 通过条件 |
|----|--------|---------|
| F1 | 收尾触发被动训练 | 收尾SKILL执行后，TDR中出现该案例记录 |
| F2 | Trae在线辅导循环 | 收尾后启动辅导循环，Trae可监控前端训练流程 |
| F3 | 33-REA结构化标注 | TDR案例包含algorithm_pattern和dependency_graph字段 |
| F4 | 主动训练多源采集 | TDR数据源包含认知(B级以上)/SKILL/文档/知识库 |
| F5 | 双模式资源隔离 | 被动训练不阻塞用户交互，主动训练不影响系统响应 |
| F6 | 被动训练效果可度量 | 可查询辅导质量分、纠正次数、训练成果提升 |
| F7 | FAIL-OPEN | 33-REA失败时降级为文本入库，不阻塞收尾 |

---

## 7. 风险与缓解

| 风险 | 等级 | 缓解 |
|------|------|------|
| Trae在线辅导耗时过长阻塞收尾 | 高 | 异步执行，收尾报告先完成，辅导后台运行，30分钟超时 |
| 33-REA对Trae案例代码解析质量不足 | 中 | P1适用性验证；FAIL-OPEN降级为文本四元组 |
| 主动训练数据源噪音大 | 中 | 数据源专属质量门控（C级记忆需verify升级） |
| 双模式资源竞争 | 中 | 资源配额+抢占策略，被动优先 |
| TDR数据膨胀 | 低 | 增量采集+容量规划+低质量数据淘汰 |
| Trae上下文丢失导致辅导中断 | 中 | 检测上下文完整性，丢失则降级为案例入库 |
| 辅导纠正质量依赖Trae判断 | 中 | 记录纠正日志，后续主动训练时复核 |

---

## 8. 与现有系统的关系

| 系统 | 关系 | 说明 |
|------|------|------|
| SPL v0.4 | 扩展 | 本SPEC扩展SPL的数据源和触发方式，不修改训练器内部 |
| 33-REA | 集成 | 33-REA作为被动训练的教学材料来源 + 主动训练的批量标注 |
| dream-completion-evolution-workflow | 集成 | 收尾SKILL新增Step 5.5触发被动训练 |
| dream-self-iteration-workflow | 集成 | 被动训练通过hermes反思tag触发自进化 |
| CaseIngestGate | 复用 | 收尾案例价值评估 |
| 认知系统 | 数据源 | 主动训练采集B级以上认知记忆 |
| SKILL系统 | 数据源 | 主动训练采集SKILL索引 |
| 文档/知识库 | 数据源 | 主动训练采集文档知识 |
| Trae | 双重角色 | 主动训练=离线数据来源，被动训练=在线教师 |

---

## 9. 替代方案对比

| 方案 | 优点 | 缺点 | 结论 |
|------|------|------|------|
| **33-REA结构化标注(本方案)** | 算法模式+调用链+依赖图，结构化程度高，适合分层训练 | 对增量代码适用性需验证，解析耗时 | 采用，P1验证 |
| LLM直接总结收尾案例 | 无需33-REA，直接用Trae上下文生成案例摘要 | 非结构化，难以映射到5层训练器，LLM成本高 | 备选，33-REA失败时降级 |
| 纯文本四元组入库 | 最简单，已有Trae Memory Bridge | 缺乏算法层面标注，训练信号弱 | 兜底，33-REA和LLM都失败时使用 |

---

## 10. 版本历史

| 版本 | 日期 | 变更 |
|------|------|------|
| v0.1 | 2026-10-11 | 初始版本：双模式训练架构 + 33-REA集成 + 收尾触发链路 + 实施计划P0-P4 |
| v0.2 | 2026-10-11 | 评审后修订：M1被动训练重新定义为Trae在线辅导训练；M2补充数据源质量门控；M3增加33-REA适用性验证；M4定义被动训练专属指标；m1-m6补充细节 |
