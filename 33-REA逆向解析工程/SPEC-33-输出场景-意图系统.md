# SPEC-33-输出场景-意图系统（REA Output Scenario: Intent System）

> 版本：v0.3（评审修订版）
> 日期：2026-10-24
> 状态：评审修订完成，待实施
> v0.2→v0.3 变更（落实 PEER-REVIEW-33 评审意见）：M1 Spec 增强两段式机制（规则证据提取 + LLM 单次组装）；M2 E-T1/E-T2 实验设计补全（周期/样本量/统计方法）；M3 策略评估双层延迟预算；m1-m4 Minor 修复；Devil's Advocate 让步（E-T1 双指标报告）
> 前置：SPEC-33-反思层.md v0.3（回放池 + 做梦评估循环 + 外部最优路径获取）
> 关联系统：34-前端应用训练系统（A 层 OKR 节点体系 + C-Drive 决策链 + 三种训练机制）

## 1. 定位与目标

REA 逆向解析工程的第一个大输出场景：**前端意图系统**。输入已确定（目标工程路径/URL），本 SPEC 定义两个输出方向与一个闭环：

- **方向一（A 层）**：意图系统的复杂任务输出 Spec 时，利用 REA 逆向解析能力增强 Spec——为 DreamOs 架构 A 层提供工程层的清晰 OKR，主要应用反思分析规划能力
- **方向二（C 层）**：C-Drive 驱动层的代码实现——每完成一个节点目标，C-Drive 进行决策并评估下一步策略，最优路径依据 REA 的最优路径解析，与 SA 两层自然衔接
- **闭环**：输出场景产物接入日常模型训练，形成『训练→输出→反思→再训练』递归闭环

## 2. 设计合理性评估结论

| 评估项 | 结论 | 依据 |
|---|---|---|
| A 层衔接可行性 | ✅ 合理 | okr_nodes.py 已预留 engineering_okr 通道且优先于 plan_items 消费，REA 输出可直接对接 |
| C 层衔接可行性 | ✅ 合理 | rea_cdrive_adapter.py（P4）已验证 REA 产物驱动 C-Drive 的链路，降级机制（FAIL-OPEN）保证不阻断 |
| 契约兼容性 | ✅ 合理 | 现有 A/C 层契约不变，REA 仅作为新增供给源接入 |
| 与反思层 v0.3 协同 | ✅ 合理 | 做梦评估循环改进的分析策略即 C-Drive 策略评估输入；外部成熟项目解析树即最优路径来源 |
| 训练闭环可行性 | ✅ 合理 | 34 系统已有三种训练机制（持续/被动/主动），REA 已注册为主动训练 Provider，闭环仅差输出产物→训练案例的接线 |

## 3. 架构设计

### 3.1 输出链路总览

```
意图系统（复杂任务）
  │
  ├─ 方向一：Spec 增强（A 层）
  │   Spec 草案 ──→ s33_rea_spec_enhance ──→ 增强 Spec（工程约束+OKR 节点+选型依据）
  │                                              │ 过 PoE 三级门禁
  │                                              ▼
  │                                    okr_nodes.decompose_okr_nodes（engineering_okr 通道）
  │
  └─ 方向二：最优路径驱动（C 层）
      节点目标完成 ──→ s33_rea_optimal_path ──→ 候选下一步策略（带证据+置信度）
                                              │
                                              ▼
                                    decision_deriver 决策推导 ──→ C-Drive 执行
                                              │
                                    （无信号时降级 P3/P2/P1，FAIL-OPEN）
```

### 3.2 与现有架构的衔接点

| 现有组件 | 衔接方式 |
|---|---|
| 34/core/okr_nodes.py（decompose_okr_nodes） | 增强 Spec 的 engineering_okr 直接进入现有通道，验收方式按来源分派不变 |
| 34/core/rea_cdrive_adapter.py（P4） | 保留现有问题触发式反思；s33_rea_optimal_path 作为节点完成后的策略评估新增供给 |
| 34/core/decision_deriver.py | 候选策略的置信度对接 CONF_REDO/CONF_SUPPLEMENT 阈值语义（<0.3 REDO / <0.6 INSERT_BEFORE / >=0.6 CONTINUE） |
| 33/core/design_decision_recovery.py | 设计决策还原（ADR）作为 Spec 工程约束与技术选型依据的核心来源 |
| 33/core/architecture_pattern_detector.py | 架构模式识别结果作为 Spec 架构约束来源 |
| 反思层 v0.3 回放池 | 外部成熟项目解析树 = 最优路径来源；做梦循环改进的策略 = 策略评估输入 |
| 34/scripts/run_continual_training.py（v0.5 增量模式） | 训练案例数据到达即学习（EWMA 衰减 + S 级优先级触发） |
| 34/scripts/run_passive_training.py | 任务收尾案例触发增量训练（checkpoint→add→incremental→get_model） |
| 34/core/active_training_collector.py | REA 已注册 Provider，每日凌晨批量采集 → 质量门控 → TDR 中央训练数据仓库 |

## 4. 方向一：Spec 增强管线（A 层）

### 4.1 s33_rea_spec_enhance 节点

**输入**：
- spec_draft：意图系统的复杂任务 Spec 草案
- reference_pool（可选）：同类成熟项目解析树（反思层外部池），按任务特征匹配

**处理（v0.3 修订，落实评审 M1：两段式机制）**：

**第一段——证据提取（规则驱动，零 token）**：
1. 解析 Spec 草案的任务特征（语言/领域/架构类型）
2. 从外部池检索匹配的成熟项目解析树（无匹配时仅用内部能力，FAIL-OPEN）
3. 规则抽取证据包：设计决策（ADR：决策+背景+替代方案）、架构模式约束、演化叙事要点——全部带证据引用（来源+行号+置信度），零 LLM 调用

**第二段——Spec 组装（LLM 单次生成）**：
4. LLM 单次生成增强 Spec，输入 = Spec 草案 + 证据包，输出约束为 engineering_okr 格式
5. **token 预算上限**：单次生成 ≤ 8K token（输入+输出），超限截断证据包按置信度排序保留高置信项

**输出**：增强 Spec，包含：
- **工程约束**：带证据引用（来源+行号+置信度）
- **OKR 节点**：每节点带验收标准（对接 okr_nodes 的 verify 分派）
- **技术选型依据**：引用成熟项目设计决策及适用条件

**与零 token 设计哲学的关系**：第一段证据提取对齐 rea_cdrive_adapter 的零 token 原则（确定性、可回放）；第二段组装是生成性任务，无法零 token，以单次调用 + 预算上限 + PoE 门禁控制成本与质量。

### 4.2 Spec 质量门禁

- 增强 Spec 过 PoE 三级门禁（复用 ai_audit.compute_poe_score）
- 纸上谈兵检测：工程约束引用的证据必须真实存在（对齐反思层 R3）
- 外部依据标注适用条件，作为参考先验而非硬约束

### 4.3 验收标准

- 增强 Spec 的 engineering_okr 可被 decompose_okr_nodes 正确消费（集成测试）
- 工程约束 100% 带证据引用
- 两段式机制单元测试：证据提取零 LLM 调用验证、token 预算超限降级验证
- 实验 E-A1：Spec 增强前后 OKR 节点验收通过率对比（目标：增强后 ≥ 增强前）

## 5. 方向二：C-Drive 最优路径驱动（C 层）

### 5.1 s33_rea_optimal_path 节点

**触发（v0.3 修订，落实评审 M3：双层延迟预算）**：

- **轻量层（默认触发，每次节点完成后）**：规则检索，延迟预算 <100ms，对齐 P4 适配器模式——关键词匹配回放池索引、置信度阈值判断，无回放池全量检索
- **重量层（条件触发）**：回放池检索 + V 值排序，延迟预算 <5s，触发条件：验收失败 / 置信度 <0.6 / 用户显式调用

**输入**：
- completed_node：已完成节点的执行结果与验收状态
- task_context：当前任务 Spec 与剩余 OKR 节点
- replay_pool：回放池（内部发现树 + 外部最优路径树）

**处理**：
1. 评估已完成节点：验收状态 + 证据完整度 + 偏差分析
2. 从回放池检索相似情境的历史路径（内部：本系统过往执行轨迹；外部：成熟项目同类实现路径）
3. 生成候选下一步策略集：每条策略带依据（证据+置信度+来源标注 internal/external）
4. 按回放目标函数 V 值排序候选策略

**输出**：候选下一步策略集（含 expected_decision 建议：CONTINUE/REDO/INSERT_BEFORE/JUMP_TO/EARLY_TERMINATE）

### 5.2 与决策链的集成

- 候选策略置信度对接 decision_deriver 阈值语义（<0.3 REDO / <0.6 INSERT_BEFORE / >=0.6 CONTINUE）
- 无信号时降级：s33_rea_optimal_path 无输出 → 现有 P4 问题触发式反思 → P3 辩论 → P2/P1（FAIL-OPEN，不阻断 C-Drive）
- 外部路径策略标注适用条件，与内部路径冲突时 R1 战略反思裁决

### 5.3 验收标准

- 轻量层延迟 <100ms、重量层延迟 <5s（性能测试）
- 节点完成后策略评估链路端到端可用（集成测试）
- 候选策略 100% 带证据与来源标注
- 实验 E-C1：最优路径驱动 vs 现有问题触发式反思，节点完成效率对比
- 实验 E-C2：外部路径注入前后，策略评估质量（V 值）对比

## 6. 日常训练闭环

### 6.1 闭环链路

```
日常任务执行（意图系统）
  ├─ A 层：s33_rea_spec_enhance 增强 Spec → OKR 节点执行
  ├─ C 层：s33_rea_optimal_path 节点完成后策略评估 → C-Drive 决策
  ▼
训练案例生成（§6.2 案例源扩展）
  ├─ Spec 增强案例：草案 vs 增强 Spec + OKR 验收结果（正/负样本）
  ├─ 策略评估案例：节点完成情境 + 候选策略 + 实际执行结果
  ▼
日常训练闭环（三种机制接线）
  ├─ 每日凌晨：主动训练采集器（REA Provider）批量采集 → 质量门控 → TDR
  ├─ 任务收尾：被动训练即时触发（增量学习 + coaching_loop 监控纠正）
  ├─ 数据到达：持续训练三层触发自动 trainIncremental（不等桶满）
  ▼
模型改进 → 意图系统输出质量提升 → 反思层回放池扩充（内部发现树）
  ▲                                        │
  └────────── 闭环（与 Dream-RSI 自改进循环同构）
```

### 6.2 训练案例源扩展

**Spec 增强案例**：
- 字段：spec_draft、enhanced_spec、okr_acceptance_results、poe_score、evidence_refs
- 标签：验收通过 = 正样本；REDO/回滚 = 负样本（负样本对训练价值更高，必须入库）

**策略评估案例**：
- 字段：node_context、candidate_strategies（含来源标注 internal/external）、chosen_decision、execution_outcome、V 值
- 标签：执行结果与预期一致 = 正样本；偏差 = 负样本

**训练案例 JSON Schema 与 TDR 字段映射（v0.3 新增，落实评审 m2）**：

```json
{
  "case_type": "spec_enhance | optimal_path",
  "intent": "任务意图描述",
  "payload": {"...": "按上述字段定义"},
  "label": "positive | negative",
  "poe_score": "float [0,1]",
  "evidence_refs": ["证据引用列表，空则不入库"],
  "created_at": "ISO8601"
}
```

TDR 映射：case_type → case.category；intent → case.title；payload → case.content；label → case.quality 标签维度；poe_score → case.quality 分值维度。具体以 case_bank_server.store_case 实际契约为准，Q6 实施时对齐校验。

**质量门控对齐**：训练案例必须带 poe_score 与验收结果标签；无证据引用的案例不入库（对齐纸上谈兵检测）。

### 6.3 三种训练机制接线

| 机制 | 接线方式 | 频率 |
|---|---|---|
| 主动训练（active_training_collector） | REA Provider 扩展案例类型（新增 spec_enhance/optimal_path 两类），质量门控后写入 TDR | 每日凌晨低峰期 |
| 被动训练（run_passive_training） | 任务收尾案例含输出场景执行结果，触发增量训练 | 每任务收尾 |
| 持续训练（run_continual_training v0.5） | 训练案例数据到达即学习，EWMA 衰减旧案例，S 级质量优先触发（注：『S 级』为 34 系统训练质量分级，非反思层『S 层』） | 数据到达时 |

### 6.4 闭环验收标准

- 两类新案例可被主动训练采集器正确采集并通过质量门控（集成测试）
- 负样本（验收失败/回滚案例）入库率 100%（不静默丢弃）
- 实验 E-T1（v0.3 修订，落实评审 M2 与 Devil's Advocate 让步）：4 周观察窗口，按周分桶对比闭环开启前后 OKR 节点验收通过率（最终指标）与策略评估命中率（中间指标），使用比例检验（α=0.05）；若中间指标改善而最终指标无显著变化，重新评估闭环传导链路
- 实验 E-T2（v0.3 修订）：训练案例回流后，反思层回放池内部发现树规模与做梦评估 V 值的散点相关性分析，报告 Pearson 相关系数与显著性（p<0.05 为有效关联）

## 7. 实施路线

| 阶段 | 内容 | 依赖 | 备注 |
|---|---|---|---|
| Q1 | s33_rea_spec_enhance 节点（两段式）+ Spec 增强管线 | 反思层 P1（回放池） | |
| Q2 | Spec 质量门禁 + 集成测试（对接 okr_nodes） | Q1 | |
| Q3 | s33_rea_optimal_path 节点（双层延迟）+ 策略评估逻辑 | 反思层 P2（做梦循环） | |
| Q4 | C-Drive 集成 + 降级链路 + 端到端测试 | Q3 | |
| Q5 | 实验 E-A1/E-C1/E-C2 + 验收包 | Q2, Q4 | |
| Q6 | 训练案例源扩展 + 三种训练机制接线 + 闭环端到端验证 | Q5 | 含 E-T1/E-T2 共 4 周实验期 |

## 8. 测试要求

- test_spec_enhance.py：两段式管线（证据提取零 LLM 验证→LLM 组装→okr_nodes 消费）
- test_optimal_path.py：双层策略评估（轻量层延迟/重量层延迟/降级链路）
- test_training_case_sources.py：两类训练案例生成、JSON Schema、质量门控、负样本入库
- test_output_integration.py：端到端集成（意图系统→增强 Spec→OKR 执行→节点完成→策略评估）
- test_training_loop_integration.py：闭环端到端（输出产物→训练案例→采集入库→增量训练→回放池回流）

## 9. 风险与局限

- 外部路径适配性：成熟项目路径未必适配当前任务上下文，候选策略标注适用条件，由 R1 战略反思裁决冲突
- 策略评估成本：轻量层默认触发（<100ms），重量层条件触发控制成本
- 冷启动：回放池历史不足时策略评估降级为内部能力，FAIL-OPEN 不阻断
- 训练闭环噪声：负样本入库可能引入噪声，依赖质量门控（poe_score + 证据引用）与 EWMA 衰减机制控制；训练异常时 coaching_loop 自动纠正
- 闭环自增强失控：递归闭环存在自我强化偏差风险，由反思层批评自循环（观察期/回滚机制）与 A8 式独立验证加成约束
- 闭环传导链路（v0.3 新增）：『模型改进→输出质量提升』因果链较长，E-T1 双指标（中间+最终）监控传导有效性

## 10. 参考

- SPEC-33-反思层.md v0.3（回放池 + 做梦评估 + 外部最优路径获取）
- 34-前端应用训练系统/core/okr_nodes.py（A 层 OKR 节点验收体系 P3.3）
- 34-前端应用训练系统/core/rea_cdrive_adapter.py（P4 REA 反思驱动）
- 34-前端应用训练系统/core/decision_deriver.py（C 层决策推导器）
- 34-前端应用训练系统/core/active_training_collector.py（主动训练采集器，REA Provider）
- 34-前端应用训练系统/scripts/run_continual_training.py（持续训练 v0.5 增量模式）
- 34-前端应用训练系统/scripts/run_passive_training.py（被动训练端到端）
- 35-广义认知系统协作模块/SPEC-CDrive-CognitiveSystem-Integration.md
- PEER-REVIEW-33-反思层与输出场景.md（评审意见，本版修订依据）
- Dream-RSI: Recursive Self-Improvement through Evolving Worlds（arXiv 2609.14858v2）
