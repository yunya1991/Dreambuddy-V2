# SPEC-33-反思层（Reflection Layer）

> 版本：v0.3（评审修订版）
> 日期：2026-10-24
> 状态：评审修订完成，待实施
> v0.2→v0.3 变更（落实 PEER-REVIEW-33 评审意见）：M1 冷启动路径重定义（发现树 Schema + 验收包降级为种子案例）；M2 策略空间定义为分析编排配置；M3 hypervolume 计算细节；m1-m4 Minor 修复；Devil's Advocate 让步（外部树动态权重）
> 前置调研：Dream-RSI 论文（arXiv 2609.14858v2）、6-TRADING 做梦部理论设计、A8 理论实践检验 SKILL 理论

## 1. 定位与目标

在 REA 现有分析能力（P0 核心层 + PoE 扩展层）之上，增加**反思层（Reflection Layer）**，采用**内外结合**的双路径自改进：

- **内部路径（Dream-RSI 适配集成）**：将 REA 的分析历史组织为可回放模拟器，在模拟器内『做梦』评估候选分析策略，以近乎零成本改进探索策略
- **外部路径（最优路径获取）**：通过 18 数据获取中心采集类似成熟项目，用 REA 逆向解析提取其设计决策与最优实现路径，经验证后注入回放池
- **SKILL 反思层**：借鉴 A8 理论实践检验的批评自循环与做梦部三屏分层，检验 REA 分析结论是否被证据支撑，形成『假说→验证→观察期→采纳/回滚』闭环
- **递归自改进**：内部做梦改进策略 + 外部最优路径注入，双轮驱动持续扩展回放池，形成自改进循环

**与 Dream-RSI 的差异点**：Dream-RSI 仅利用自身内部发现历史做梦；本方案增加外部维度——解析类似成熟项目获取『别人已走过的最优路径』，相当于为做梦器引入外部经验先验，加速策略收敛。

## 2. 核心原则

1. **Evidence-First 继承**：反思层的每条批评与改进建议必须带证据（来源+行号+置信度+局限），复用 REA 四层事实分级（observation → derivation → inference → unknown）
2. **回放优于语义归纳**（Dream-RSI §5 实验结论）：保留完整回放历史而非抽象语义摘要注入 prompt
3. **不劣化保证**（Dream-RSI 策略选择机制）：当前策略始终保留在候选集中，改进策略仅在回放评估优于当前时才采纳
4. **外部路径须经验证**：外部成熟项目提取的结论必须经验证（网络+内容+交叉三重，见 §5.3）+ REA 证据链支撑，未验证结论不得注入回放池
5. **本地只读**：反思层不执行目标程序，回放模拟器仅重放已记录的分析轨迹
6. **纸上谈兵检测**（A8 机制）：对比『声称已分析』与『实际证据链记录』，声称但无证据 → CRITICAL

## 3. 架构设计

### 3.1 四层结构

```
┌─────────────────────────────────────────────────────┐
│ 反思层（Reflection Layer）                             │
│ ├─ R1 战略反思：分析方向/范围/深度是否正确              │
│ ├─ R2 战术反思：分析成本-质量权衡是否合理                │
│ └─ R3 执行反思：具体结论的证据完整度与置信度             │
├─────────────────────────────────────────────────────┤
│ 外部最优路径获取层（External Path Acquisition）          │
│ ├─ E1 数据采集：18 中心注册成熟项目采集器                │
│ ├─ E2 逆向解析：REA 提取成熟项目设计决策与最优路径        │
│ └─ E3 真实环境验证：网络+内容+交叉三重验证               │
├─────────────────────────────────────────────────────┤
│ 回放模拟器（Replay Simulator）                          │
│ ├─ 回放池 = 内部发现树 + 外部成熟项目解析树              │
│ ├─ 确定性重放引擎（不生成新候选，只回放记录）             │
│ └─ 回放目标函数（质量-成本 Pareto hypervolume）          │
├─────────────────────────────────────────────────────┤
│ REA 现有能力（P0 核心层 + PoE 扩展层，不变）             │
└─────────────────────────────────────────────────────┘
```

### 3.2 与现有架构的衔接点

| 现有组件 | 衔接方式 |
|---|---|
| dsh_nodes.py（DSH_NODE_REGISTRY） | 新增 s33_rea_reflect / s33_rea_dream / s33_rea_replay / s33_rea_harvest 节点 |
| core/ai_audit.py（compute_poe_score） | poe_score 作为回放评估的质量维度；反思层批评结论过 PoE 三级门禁 |
| acceptance_bundles/ | 两个历史验收包作为**种子案例**（人工转换为最小发现树，见 §4.1 冷启动） |
| core/evidence.py | 反思层批评与改进建议复用 Evidence 结构 |
| 18-数据获取中心（BaseCollector + Dispatcher + DataRecord 契约） | 注册 rea_mature_project 采集器，采集成熟项目元数据与源码 |
| core/design_decision_recovery.py + architecture_pattern_detector.py | 对成熟项目执行设计决策还原与架构模式识别，提取最优路径 |

## 4. 阶段一：Dream-RSI 适配集成（内部路径）

### 4.1 回放模拟器（core/reflection/replay_simulator.py）

**发现树 Schema（JSON，v0.3 新增定义）**：

```json
{
  "tree_id": "string，全局唯一",
  "task": {"target": "目标工程路径", "task_type": "analyze|trace|investigate", "feature": "可选特征"},
  "nodes": [
    {
      "node_id": "string",
      "parent_id": "string|null（根节点为 null）",
      "action": "分析器调用（analyzer + 参数）",
      "evidence_refs": ["Evidence 结构引用列表"],
      "poe_score": "float [0,1]，该节点产出质量",
      "cost": {"calls": "分析器调用次数", "tokens": "可选 token 消耗"},
      "children_record": "已记录子节点结果（确定性重放数据源）"
    }
  ],
  "provenance": "internal|external",
  "created_at": "ISO8601"
}
```

- **分析历史记录**：每次 s33_rea_analyze/trace/investigate 执行时，按上述 Schema 记录发现树至历史池
- **历史池存储**：`reflection_data/replay_pool/`，分 `internal/`（内部发现树）与 `external/`（外部解析树）两个子目录
- **确定性重放**：给定候选策略 π 与历史树 T，重放返回已记录的 children_record，不调用分析器重新生成
- **冷启动路径（v0.3 修订，落实评审 M1）**：
  1. P1 首先落地发现树 Schema 与记录器，新分析任务开始增量积累发现树
  2. acceptance_bundles 两个验收包**降级为种子案例**：人工将其 wrapup_report/fix.diff/acceptance_report 转换为最小发现树（单链路径，节点=关键分析步骤），仅用于 Schema 验证与重放引擎冒烟测试，不作为策略评估的充分历史
  3. 策略评估在内部发现树数量 < 10 棵时降级为『仅记录不评估』模式，达到阈值后开启做梦评估

### 4.2 策略空间定义（v0.3 新增，落实评审 M2）

**策略 = 分析编排配置，而非分析器代码**。分析器代码（python_analyzer/call_chain_tracer 等）保持不变，符合 Dream-RSI『base agent 不变』原则。

策略配置 Schema：

```json
{
  "strategy_id": "string",
  "analyzer_sequence": ["分析器选择与执行顺序"],
  "depth_params": {"max_depth": "int", "breadth_limit": "int"},
  "stop_conditions": ["证据充分|成本超限|置信度达标"],
  "parallelism": "int，并行 worker 数",
  "budget": {"max_calls": "int", "max_tokens": "int 可选"}
}
```

- **候选策略生成**：由配置变换生成（序列重排/深度参数调整/停止条件变更/并行度调整），不做代码重写
- **策略改进**：反思层基于回放评估结果修改策略配置（JSON 变更），非代码变更

### 4.3 回放目标函数（v0.3 修订，落实评审 M3）

```
V(π, T) = 归一化 hypervolume(质量-成本点集) − λ × 并行度惩罚
```

- **点集定义**：一棵发现树的多个节点 (poe_score, 累积成本) 构成二维点集，非单点
- **参考点**：(0, 总预算 budget.max_calls)，hypervolume 为点集支配区域面积
- **归一化**：除以参考点构成的矩形面积，V ∈ [0,1]
- **并行度惩罚**：平均每次调用的串行轮数 × λ
- **λ 取值**：初始 λ=0.1，观察期内根据回放评估分布调优（记录调优依据）

### 4.4 做梦评估循环（core/reflection/dreaming.py）

1. 从回放池取全部发现树（内部 + 外部，外部树按 §5.4 动态权重参与）
2. 对 M 个候选策略版本（含当前策略 π_t）在预算偏好参数 ρ∈{0, 0.25, 0.5, 0.75, 1} 下确定性重放
3. 计算 V^m，选 π_{t+1} = argmax V^m
4. 改进后的策略重新部署在线

### 4.5 阶段一验收标准（v0.3 修订）

- 发现树 Schema 落地，新分析任务可正确记录发现树（集成测试）
- 种子案例（验收包转换）通过重放引擎冒烟测试
- 内部发现树 ≥10 棹后，至少 1 个候选策略在回放评估中优于当前策略

## 5. 阶段二：外部最优路径获取

### 5.1 E1 数据采集（18 中心采集器）

在 18-数据获取中心注册 `rea_mature_project` 采集器（遵循 BaseCollector + DataRecord 契约）：

- **采集范围**：与 REA 分析任务同类的成熟开源项目（GitHub 仓库元数据、README、架构文档、release notes、commit 历史）
- **DataRecord 字段映射（v0.3 新增，落实评审 m3）**：source=`rea_mature_project`，category=`code_repo`；payload 字段：repo_url、default_branch、stars、language、arch_docs（架构文档列表）、commit_history_summary；metrics 字段：repo_language、repo_stars、repo_last_active_ts
- **采集触发**：分析任务执行时按目标特征（语言/领域/架构类型）检索匹配的成熟项目；支持定时批量采集扩充外部池
- **落库**：复用 18 中心 sqlite 存储与去重机制

### 5.2 E2 逆向解析（REA 现有能力复用）

对采集的成熟项目执行 REA 分析流水线：

- `s33_rea_analyze`：架构与依赖分析
- `s33_rea_recover_decisions`：设计决策还原（ADR 风格 + 替代方案推断）——**最优路径的核心来源**
- `s33_rea_narrative`：演化叙事（架构成长史 + 重构动机）——揭示路径演化过程
- 产出『外部解析树』：成熟项目的发现树（provenance=external）+ 设计决策证据链 + poe_score

### 5.3 E3 验证（v0.3 修订，落实评审 m4：裁剪为网络+内容+交叉三重）

对外部解析结论执行验证，防止幻觉路径注入：

- **网络验证**：成熟项目仓库/文档的真实可访问性、元数据与采集记录一致
- **内容验证**：解析结论引用的源码位置、文档内容真实存在
- **交叉验证**：外部结论与 REA 静态分析证据链一致；不一致 → 降级为 unknown，不注入回放池

### 5.4 E4 路径注入（v0.3 修订，落实 Devil's Advocate 让步）

- 验证通过的外部解析树写入 `reflection_data/replay_pool/external/`，标注 provenance=external、项目名、commit hash
- **外部树动态权重**：初始权重 0.5，随验证通过率动态调整（每轮验证后按通过率线性更新，上限 1.0，下限 0.1）；做梦评估中外部树的 V 值贡献按权重折算——控制自举循环风险（用未验证的分析能力生成训练数据改进自身）
- 做梦循环中外部树与内部树共同参与策略评估

### 5.5 阶段二验收标准

- rea_mature_project 采集器通过 18 中心 B7 四门禁（DUPLICATE/SCHEMA/IMPORT_FAIL/MISSING=0）
- 至少 1 个成熟项目完成『采集→解析→验证→注入』全链路
- 注入外部树后做梦评估的 V 值不低于注入前（不劣化）

## 6. 阶段三：反思层构建（基于现有 SKILL 理论）

### 6.1 R1-R3 三级反思（借鉴做梦部三屏 + A8 职能）

- **R1 战略反思**：检验分析方向选择是否被证据支撑；内外路径冲突时（内部策略 vs 外部最优路径）的裁决依据
- **R2 战术反思**：检验分析深度-成本权衡，识别过度分析/分析不足
- **R3 执行反思**：检验每条结论的证据完整度，执行纸上谈兵检测（声称分析但无证据链记录 → CRITICAL）

### 6.2 批评自循环（对齐 A8 工作流）

```
发现矛盾 → 提出假说 → 回放模拟器验证（内部树+外部树） → 观察期 → 采纳/回滚
```

- **批评可信度** = A8 式自评 + 独立验证加成（最高 +40%）
- **观察期（v0.3 修订，落实评审 m1）**：改进建议观察 3 个分析任务周期（对齐 A8 的 14 天/7 天分级思想，按任务周期而非自然日计量）；观察期内仅记录不部署
- **客观回滚条件**：poe_score 下降 >15 分 24h 内回滚；证据链完整度下降立即回滚；分析成本上升 >50% 48h 内回滚

### 6.3 实验论证计划（v0.3 修订，落实评审 m2）

- E1：反思层批评准确率验证——独立第二分析器交叉验证 + 抽样人工复核（抽样率 ≥20%），目标一致率 ≥70%
- E2：做梦改进有效性验证（改进策略 vs 当前策略在回放池上的 V 值对比）
- E3：纸上谈兵检测验证（注入无证据声称，检测召回率目标 100%）
- E4：端到端验证（反思层启用 vs 禁用，最终分析报告 poe_score 对比）
- E5：外部路径增益验证——仅内部树做梦 vs 内部+外部树做梦，对比策略改进收敛速度与最终 V 值

### 6.4 阶段三验收标准

- E1-E5 全部通过，实验报告存入 acceptance_bundles/
- 反思层批评结论 100% 带证据（Evidence 结构）

## 7. 阶段四：落地集成

### 7.1 DSH 节点

- `s33_rea_reflect`：对指定分析结果执行 R1-R3 反思，返回带证据的批评报告
- `s33_rea_dream`：触发做梦评估循环，返回策略改进结果
- `s33_rea_replay`：查询/重放历史分析轨迹
- `s33_rea_harvest`：触发外部路径获取全链路（采集→解析→验证→注入）

### 7.2 测试要求

- test_replay_simulator.py：发现树 Schema、确定性重放、种子案例冒烟
- test_dreaming.py：做梦循环与不劣化保证验证
- test_reflection_layer.py：R1-R3 反思与纸上谈兵检测验证
- test_external_harvest.py：采集器契约、验证门禁、注入流程、动态权重
- test_integration_reflection.py：端到端集成测试

### 7.3 验收包

- acceptance_bundles/2026xxxx_reflection_layer/：含 repro_before/repro_after、测试日志、实验报告 E1-E5

## 8. 实施路线

| 阶段 | 内容 | 依赖 |
|---|---|---|
| P1 | 发现树 Schema + 记录器 + 回放模拟器 + 种子案例 | 无 |
| P2 | 做梦评估循环 + 回放目标函数 + 策略空间 | P1（发现树 ≥10 棵） |
| P3 | 外部路径获取（18 采集器 + REA 解析 + 三重验证 + 注入 + 动态权重） | P1 |
| P4 | R1-R3 反思层 + 纸上谈兵检测 | P1 |
| P5 | 批评自循环 + 观察期/回滚机制 | P2, P4 |
| P6 | DSH 节点 + 测试 + 验收包 | P3, P5 |

## 9. 风险与局限

- 回放池冷启动：P1 起增量积累发现树，<10 棵时仅记录不评估；外部路径可部分缓解冷启动，但需控制采集成本
- 外部路径质量风险：成熟项目的设计决策未必适配本系统上下文，注入时标注适用条件，做梦评估中作为参考先验而非硬约束；动态权重控制自举循环风险
- 策略表示：策略为编排配置（JSON），分析器代码不变，无代码重写风险
- 反思层成本：反思与外部采集均消耗资源，需设置触发条件（poe_score 低于阈值、用户显式调用、定时任务）
- 18 系统耦合：外部获取层通过标准契约（DataRecord）交互，18 系统变更不阻断内部路径（FAIL-OPEN）

## 10. 参考

- Dream-RSI: Recursive Self-Improvement through Evolving Worlds（arXiv 2609.14858v2）
- 6-TRADING/docs/dream-systematic-trading-SKILL-design.md（做梦部三屏理论）
- 6-TRADING/skills/A8-theory-practice-verification/SKILL.md（A8 理论实践检验理论）
- 18-数据获取中心/docs/TECHNICAL_DESIGN.md（DataRecord 契约与采集器框架）
- PEER-REVIEW-33-反思层与输出场景.md（评审意见，本版修订依据）
- SPEC.md（REA 核心设计规格）
- DESIGN-PHILOSOPHY-PoE.md（PoE 设计哲学 v1.1）
