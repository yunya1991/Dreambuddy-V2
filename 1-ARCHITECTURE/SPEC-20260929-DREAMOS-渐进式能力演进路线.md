# SPEC-20260929 — DreamOS 渐进式能力演进：S 层意图识别 + C 层 C-Drive-Agent 双核心训练路线

**版本**: v3.0（v2.0 被拒后重构：纠正 C 层理解——C 层不是 Reflector/Aggregator，而是 DSH 架构下的 C-Drive-Agent 驱动力；明确两大训练核心）
**日期**: 2026-09-29
**作者**: Trae + User
**状态**: Draft（待用户评审）
**关联文档**:
- [DSH_SUBAGENT_ARCHITECTURE_SPEC.md](./dream-harness-bridge/docs/DSH_SUBAGENT_ARCHITECTURE_SPEC.md)（C-Drive-Agent 四步循环 + 9 个 subagent）
- [SPEC_ALGORITHM_DRIVEN_TRAINING_LOOP.md](./dream-harness-bridge/SPEC_ALGORITHM_DRIVEN_TRAINING_LOOP.md)（三层分工：算法驱动 / Harness 评审训练 / Agent 接管）
- [SPEC.md](./dream-harness-bridge/SPEC.md)（分层嵌入 + HC-1~HC-11 边界守护）
- [TECHNICAL_DESIGN.md](./dreamos/docs/TECHNICAL_DESIGN.md)（SACG 四层）
- [dream-signal-scoring-spec](../6-TRADING/skills/dream-signal-scoring-spec/SKILL.md)

---

## Executive Summary

**核心命题（用户决策）**：DreamOS 不一下子接入大模型。五阶段演进的本质是**训练两大核心能力**，让 SACG 内核实质发挥作用：

1. **第一重点：S 层意图识别**——让 OS "听懂"用户问什么、该走哪条链
2. **第二重点：C 层编排驱动**——由 **C-Drive-Agent**（DSH 子 agent 驱动力）承载"recall 认知 → 反思 + Bull/Bear 辩论 → jeval 质量判断 → subagent 补充"四步循环，让 SACG 的执行层真正"活起来"，而非机械跑节点

**LLM 初期定位（用户明确）**：**只做内容整合汇总**——subagent 的 summary 提炼 + 图表生成，不生成原始数据，不做决策。决策权永远在 DreamOS 算法层（规则 + 领域模型 + CBR）。

**架构主轴**：DSH（DeepSeek Harness）是通用 agent runtime 基座，DreamOS 是交易领域特化 plugin。SACG 四层在 DSH 中的映射：

| SACG 层 | DSH 映射 | 职责 |
|---|---|---|
| S 层 Sense | `agent/pre-step` listener | 意图识别（三级识别器） |
| A 层 Arrange | `agent preset` composer | 静态执行图编排 |
| **C 层 Compute** | **`ctx.tools` + `agent/*` events** | **C-Drive-Agent 四步循环驱动执行** |
| G 层 GraphStore | `session log` 下游 consumer | 检查点/历史/压缩 |

**五阶段总览**：

| 阶段 | 能力载体 | S 层训练 | C 层训练 | LLM |
|---|---|---|---|---|
| P0 | 基线 + C-Drive 修复确认 | 环境验收 | recall/反思/jeval 注入验证 | 无 |
| P1 | 技术分析产出 | TREND/MEAN/BREAKOUT 意图 | C-Drive recall + 反思激活 | 无 |
| P2 | 基本面分析产出 | FUNDAMENTAL 意图 + 数据新鲜度 | C-Drive jeval + technical/sentiment subagent | 无 |
| P3 | 融合输出 | 路由决策（单链 vs 融合） | C-Drive Bull/Bear 辩论 | 无 |
| P4 | 全部 subagent + 内容汇总 | AI 触发校准 | C-Drive 四步循环完整 + 全部 9 subagent | **内容整合汇总** |
| P5 | 意图智能调度 | 全意图 SSOT + 持续训练 | C-Drive 参数自进化 | 门控汇总 |

---

## 1. DSH 架构与 SACG 映射（纠正 C 层理解）

### 1.1 分层嵌入架构

```
┌─────────────────────────────────────────────────────────────┐
│  DeepSeek Harness (DSH) — 通用 agent runtime 基座            │
│  Cordis 微内核 + plugin tree + model adapter + sandbox      │
└──────────────────────┬──────────────────────────────────────┘
                       │ plugin 嵌入
                       ▼
┌─────────────────────────────────────────────────────────────┐
│  DreamOS SACG — 交易领域特化 plugin（Orchestrator，持完整上下文）│
│                                                              │
│  S 层 Sense  ←→  DSH agent/pre-step listener   (意图识别)    │
│  A 层 Arrange ←→  DSH agent preset composer    (静态图编排)   │
│  C 层 Compute ←→  DSH ctx.tools + agent/* events           │
│       │                ↑ C-Drive-Agent 四步循环驱动          │
│       │                │ (recall→反思+辩论→jeval→subagent)  │
│  G 层 GraphStore ←→ DSH session log 下游 consumer           │
└──────────────────────┬──────────────────────────────────────┘
                       │ IPC (NDJSON, FAIL-OPEN)
                       ▼
┌─────────────────────────────────────────────────────────────┐
│  DSH Subagent 层（隔离执行，驱动力，独立上下文）              │
│  C-Drive-Agent → technical / sentiment / macro / flow /     │
│  onchain / valuation / risk / portfolio 共 9 个 subagent     │
│  每个: 节点输出(已验证数据) → LLM提炼summary+图表 → 返回摘要  │
└─────────────────────────────────────────────────────────────┘
```

### 1.2 C-Drive-Agent 四步循环（C 层编排能力核心）

SACG 的 C 层（Compute）不是简单的 Reflector/Aggregator 机械执行，而是由 **C-Drive-Agent** 驱动的四步循环——这是让 SACG 实质发挥作用的核心：

```
C 层每个节点执行后，C-Drive-Agent 决策：

Step 1: recall 认知查询
   → cognitive_loop_adapter.recall(context="当前节点+意图+市场状态", top_k=5)
   → 返回历史相似场景经验（FAIL-OPEN：MCP 不可用返回 []）

Step 2: 反思推理 + Bull/Bear 辩论
   → 基于 recall 结果 + 当前节点结果，决策动作：
     CONTINUE / REDO / JUMP / SUPPLEMENT / DEBATE
   → 置信度 < 0.65 时触发 Bull/Bear 辩论（LLM 双角色，deepseek-flash 并行）
     Bull 提取利好 → bull_confidence；Bear 提取利空 → bear_confidence
     辩论结果注入 Aggregator 作为 A0 矛盾论输入

Step 3: jeval 质量判断（仅 CONTINUE 时）
   → jev_judge(state, questions) → noul 分数
     noul ≥ 0.85: 放行下一节点
     noul < 0.50: 阻止，回到 Step 2 重新反思
     0.50-0.85: 记录但放行

Step 4: subagent 补充（仅 SUPPLEMENT 时）
   → 基于 intent_type + 不足维度 路由到对应金融 subagent
     缺技术面 → technical-agent；缺基本面 → macro/flow/valuation；缺情绪 → sentiment
   → subagent 返回 SubagentOutput（summary + signals + charts）
   → 注入 market_data，重新执行当前节点
```

**分级触发（避免延迟累积，HC-2）**：

| 节点置信度 | 触发动作 | 预估延迟 |
|---|---|---|
| > 0.75 | 跳过四步循环，直接下一节点 | 0ms |
| 0.65-0.75 | 只 Step 1 recall + Step 2 反思 | ~50ms |
| 0.50-0.65 | recall + 反思 + Bull/Bear 辩论 | ~200-300ms |
| < 0.50 | 全链路四步循环（含辩论 + subagent 补充） | ~500ms-1s |

### 1.3 DSH 子 agent 清单

| Subagent | 对应 DreamOS 节点 | 数据源 | 优先级 |
|---|---|---|---|
| **C-Drive-Agent** | C 层本身（驱动力） | 认知库 + jeval | P0 |
| technical-agent | C1+C2+C3 | OKX K 线 | P0 |
| sentiment-agent | F1 | 贪婪恐惧/期权 PCR | P0 |
| macro-agent | F5 | GDP/CPI/利率/流动性 | P1 |
| flow-agent | F2 | ETF/杠杆/稳定币 | P1 |
| onchain-agent | F4 | 活跃地址/算力/MVRV | P1 |
| valuation-agent | F3 | NVT/StockFlow | P1 |
| risk-agent | （新建） | VaR/相关性/压力 | P2 |
| portfolio-agent | （新建） | 仓位/再平衡 | P2 |

**Subagent 输出契约**（LLM 只做提炼+图表，不生成原始数据）：
```typescript
interface SubagentOutput {
  module: string;           // "macro" | "flow" | ...
  summary: string;          // LLM 提炼的 1-2 句人读结论（内容整合汇总）
  signals: Signal[];        // 标准化信号 [{name, value, direction, confidence}]
  charts: ChartSpec[];      // 图表配置（ECharts option）
  raw_data?: any;           // 原始数据（来自 DreamOS 节点，非 LLM 生成）
}
```

### 1.4 三层分工架构（算法驱动为主）

```
Layer 3: Agent 接管层（<10% 流量，T3 复杂任务）
   触发：算法置信度 < 0.35 或 复杂度 = T3
   执行：DSH subagent 接管处理 + 自动标注 → 反哺训练
   边界：不参与 reward（HC-5），只做难例处理+标注

Layer 2: Harness 评审训练层（20-30% 流量）
   影子评审（LLM-as-Judge）+ 纠偏 + 标注 + 训练
   边界：只评审不决策（HC-9），reward 仍由 DreamOS 内部计算（HC-5）

Layer 1: 算法驱动层（70-90% 流量，主流量）
   规则识别（0 Token）+ 领域 ML 模型 + CBR 案例检索
   难例 → Layer 2 评审；极难例 → Layer 3 接管
```

---

## 2. 两大训练核心设计

### 2.1 训练核心一：S 层意图识别

**训练对象**：三级识别器
- `RuleBasedRecognizer`（0 Token，<1ms）——规则库蒸馏
- `DynamicRecognizer`（历史反馈，<10ms）——权重更新主阵地
- `LLMBasedRecognizer`（预算门控）——P4 才启用，仅兜底

**训练数据**：`IntentSample`（每次分析产出自动生成 + 人工观察标注）

```yaml
IntentSample:
  input: { user_query, scenario_id(36场景), market_features, data_freshness }
  gold: { gold_chain: "C|F|A", gold_intent }
  recognizer_output: { predicted_intent, confidence, level }
  human_label: { confirmed: bool, corrected_intent?, corrected_chain? }  # 每次交互1布尔+最多1枚举
  dataset_split: train | eval  # 80/20
```

**训练动作**：
1. DynamicRecognizer：按 `意图 × scenario_id` 分桶统计特征分布 → 更新识别权重与推荐链路
2. RuleBased：高频模式（同桶 ≥N 且一致）蒸馏为零 Token 规则
3. OrchestrationMemory：场景→链路映射精确化（L3→L0）

**核心指标**：意图识别准确率（eval 集）、零 Token 识别占比（成本）、路由命中率。

### 2.2 训练核心二：C 层 C-Drive-Agent

**训练对象**：四步循环的决策参数与路由逻辑（当前全是硬编码常量，需通过回测+人工反馈优化）

| 可训练参数 | 当前硬编码值 | 训练方法 |
|---|---|---|
| 分级触发置信度阈值 | 0.75 / 0.65 / 0.50 | 回测驱动：不同阈值下的决策质量 vs 延迟权衡 |
| Bull/Bear 辩论触发阈值 | 0.65 | 辩论价值密度评估（辩论后置信度提升幅度） |
| jeval noul 阈值 | 0.85 / 0.50 | 放行/阻止决策的准确率回测 |
| REDO 重试次数 | 2 | 重试成功率 vs 延迟权衡 |
| subagent 路由表 | intent_type + 不足维度 → subagent | 路由命中率（subagent 补充后置信度提升） |
| CONFLICT_NODE_MAP | A2→A0, C2→C1... | 矛盾插入节点的有效性回测 |
| Aggregator 节点权重表 | A4=2.0, A3=1.5... | 加权投票方向准确率回测 |

**训练数据**：`CDriveTrace`（每次 C-Drive 决策的完整轨迹）

```yaml
CDriveTrace:
  cycle_id / node_id / intent_type / scenario_id
  step1_recall: { query, top_results, hit_quality }
  step2_decision: { action: CONTINUE|REDO|JUMP|SUPPLEMENT|DEBATE, confidence, debate_result? }
  step3_jeval: { noul, passed }
  step4_subagent: { routed_to, output_summary, confidence_before, confidence_after }
  final_outcome: { action, confidence, human_label }  # 人工观察标注决策是否合理
```

**训练动作**：
1. **回测驱动**：用历史交易数据回测不同参数组合，选 Pareto 最优（质量 vs 延迟 vs 成本）
2. **人工反馈**：用户观察 C-Drive 决策时标注"反思是否合理/辩论是否有价值/subagent 补充是否有用"
3. **贝叶斯优化**：`dreamos/core/compute/param_optimizer.py` 已有，调优阈值参数
4. **认知闭环**：高质量决策经验 record 进认知库，recall 时反哺 Step 1

**核心指标**：C-Drive 决策准确率（人工标注）、辩论价值密度（辩论后置信度提升均值）、subagent 补充命中率、四步循环平均延迟。

### 2.3 两大核心的协同

S 层决定"做什么"（意图+链路），C 层决定"怎么做对"（动态执行+质量把关）。两者训练数据共享 `scenario_id` 坐标系，人工观察时同时标注意图对错和 C-Drive 决策合理性，形成联合训练信号。

---

## 3. 五阶段路线设计

### 3.0 P0 — 基线 + C-Drive 修复确认

**背景**：2026-09-29 已修复 C-Drive-Agent 的 cognitive_adapter / jev_judge_fn / llm_fn 注入问题（`_plan/cdrive_fix_20260929.md`），52/52 测试通过，但 mcp_cognitive 当前环境不可用（FAIL-OPEN）。

**动作**：
- [ ] 验证价格查询基线（`/api/v1/analyze` 返回 BTC 实时价）
- [ ] 验证 C-Drive-Agent 四步循环在 FAIL-OPEN 模式下正常运行（recall 返回 [] 时降级为纯规则反思）
- [ ] run_hourly_sacg_execution.py 切换到 8000 端口统一链路，8765 标记 deprecated

**验收**：单问题"BTC 现在什么价"→ 5s 内返回；C-Drive 运行无回退（`_fallback_count=0`）。

### 3.1 P1 — 意图模块 1 + C-Drive recall/反思激活

**能力载体**：技术分析产出（C1-C3 节点委托本地引擎：10-经典指标 + 12-三屏 + 21-特征工程）。

**S 层训练**：TREND_FOLLOWING / MEAN_REVERSION / BREAKOUT 三类意图 × 36 场景特征认知。

**C 层训练**：
- 激活 C-Drive Step 1（recall）+ Step 2（反思），Step 3/4 暂跳过（jeval/subagent 未就绪）
- 收集 CDriveTrace，重点观察反思决策（CONTINUE/REDO/JUMP）的合理性
- 回测调优分级触发阈值初值

**训练数据规格**：IntentSample ≥100（三类意图各 ≥30）；CDriveTrace ≥50。

**验收**：① 单问题"分析 BTC 技术面"→ 报告五要素齐全；② C-Drive recall+反思在 50ms 内完成（0.65-0.75 档）；③ 10 个 IntentSample 有人工标签。

### 3.2 P2 — 意图模块 2 + C-Drive jeval + 首批 subagent

**能力载体**：基本面分析产出（F1-F5，19-DAL P0 读接口落地）。

**S 层训练**：FUNDAMENTAL_PLAY 意图 + 数据新鲜度感知；跨链误判负样本训练。

**C 层训练**：
- 激活 C-Drive Step 3（jeval 质量判断）
- 接入首批 subagent：technical-agent + sentiment-agent（经 `cordis-plugin-c-chain` / `cordis-plugin-fundamental`）
- Step 4 subagent 补充路由试运行（仅技术面/情绪面缺口）
- 回测调优 jeval noul 阈值与 subagent 路由表

**训练数据规格**：FUNDAMENTAL_PLAY 已标注 ≥50；CDriveTrace jeval/subagent 决策 ≥30。

**验收**：① 单问题"分析 BTC 基本面"→ ≥4 维真实数据；② C-Drive jeval 在 CONTINUE 时正确调用且 FAIL-OPEN 生效；③ technical/sentiment subagent 各完成 1 次补充调用，summary 为 LLM 提炼内容。

### 3.3 P3 — 路由决策 + C-Drive Bull/Bear 辩论

**能力载体**：融合输出（CF_FUSION 节点，dream-signal-scoring-spec 协议代码化）。

**S 层训练**：路由决策——"何时单链足够 / 何时需要融合"；冲突场景识别。

**C 层训练**：
- 激活 C-Drive Step 2 的 Bull/Bear 辩论（置信度 <0.65 时，deepseek-flash 并行双角色）
- 辩论结果注入 A0 矛盾论输入
- 回测调优辩论触发阈值（辩论价值密度：辩论后置信度提升幅度）
- 融合路由训练（技术/基本面背离时的 SUPPLEMENT 路由决策）

**训练数据规格**：融合判定样本 ≥100；辩论决策样本 ≥20（含辩论价值人工标注）。

**验收**：① 单问题"综合分析 BTC"→ 三维评分 + 冲突判定；② 构造背离样本验证 Bull/Bear 辩论触发且产出多空论据；③ 路由盲测：10 个混合问法，意图+链路正确 ≥7。

### 3.4 P4 — 全部 subagent + LLM 内容整合汇总

**能力载体**：9 个 subagent 全覆盖；LLM 定位明确为**内容整合汇总**。

**S 层训练**：AI 触发校准——何时值得花 LLM 成本做汇总（仅 subagent 的 summary 提炼 + 图表生成，不做决策）。

**C 层训练**：
- C-Drive 四步循环完整运行（recall + 反思+辩论 + jeval + subagent）
- 接入剩余 subagent：macro / flow / onchain / valuation / risk / portfolio
- 回测调优全套参数（分级阈值/辩论阈值/jeval 阈值/路由表/权重表）
- 贝叶斯优化器（param_optimizer）自动调参，人工确认后生效

**LLM 定位（铁律）**：
- ✅ subagent 的 summary 提炼（1-2 句人读结论）
- ✅ 图表配置生成（ECharts option）
- ✅ Bull/Bear 辩论双角色论据提取
- ❌ 生成原始数据（必须来自 DreamOS 节点已验证输出）
- ❌ 做交易决策（决策权在算法层 + Aggregator 加权投票）
- ❌ 参与 reward 计算（HC-5）

**训练数据规格**：AITriggerSample ≥50（LLM 汇总是否有价值的对照）；全 subagent 路由样本各 ≥10。

**验收**：① 9 个 subagent 均可被 C-Drive 正确路由调用；② LLM 仅出现在 summary/charts/debate 三处，决策协议无 LLM 参与；③ 全套参数完成首轮回测调优。

### 3.5 P5 — 意图智能调度 + 持续训练运营

**能力载体**：意图 SSOT 统一 + 智能调度全量 + 训练闭环常态化。

**S 层训练**：前后端意图 SSOT 统一（后端 types.py 6+1 主干 + 前端 30+ 子类型映射）；DynamicRecognizer 全量消费样本；零 Token 识别占比 ≥80%。

**C 层训练**：C-Drive 参数自进化（贝叶斯优化器 + 认知库 recall 反哺 + param_optimizer 周期调参）；四步循环延迟与质量 Pareto 最优。

**验收**：① 10 个未标注真实问法：意图+路由正确 ≥8，零 Token 占比 ≥80%；② 场景感知调度：同一问题在技术面行情 vs 基本面事件周分别路由 C/F 链；③ C-Drive 四步循环平均延迟 <300ms（0.50-0.65 档）；④ 连续 2 周 eval 准确率波动 <3%。

---

## 4. 评估体系

| 维度 | 指标 | P3 末目标 | P5 目标 |
|---|---|---|---|
| S 层意图 | 识别准确率（eval 集） | ≥75% | ≥85% |
| S 层意图 | 路由命中率 | ≥70% | ≥85% |
| S 层成本 | 零 Token 识别占比 | ≥50% | ≥80% |
| C 层 | C-Drive 决策准确率 | ≥70% | ≥85% |
| C 层 | 辩论价值密度（置信度提升均值） | >0 | >0.05 |
| C 层 | subagent 补充命中率 | ≥60% | ≥80% |
| C 层 | 四步循环 P95 延迟 | <500ms | <300ms |
| 全局 | LLM 调用占比（仅汇总） | <30% | <15% |

**评估节奏**：训练动作触发即跑 eval 回归门；每阶段末全量报告；P5 起周度例行（label drift 防护）。

---

## 5. 风险与边界守护

| 风险 | 缓解 |
|---|---|
| mcp_cognitive 不可用导致 recall 失效 | FAIL-OPEN：返回 []，C-Drive 降级为纯规则反思（HC-3） |
| Bull/Bear 辩论增加 LLM 调用 | 仅置信度 <0.65 触发；deepseek-flash 并行；分级触发（HC-8） |
| LLM 越权做决策 | 契约校验：LLM 输出仅限 summary/charts/debate 字段，决策字段由算法层产出（HC-9） |
| 9 个 subagent 工作量大 | 分批：P0 C-Drive，P2 technical+sentiment，P4 其余 6 个 |
| jeval 不在 C 层 | Python server 暴露 `jev_judge` IPC，C 层通过 IPC 调用（HC-4 FAIL-OPEN） |
| subagent 间通信 | HC-7 禁止，只与 C-Drive-Agent 交互 |
| DreamOS 核心代码被改 | HC-1a：训练逻辑在 harness-bridge 内，dreamos/ 零 Harness 依赖 |
| reward 边界失守 | HC-5：reward 由 DreamOS 内部计算，Harness/subagent 不参与 |

---

## 6. 待用户确认项

1. **C 层训练优先级**：C-Drive 参数回测调优，是否从 P1 就开始用历史数据回测（而非等人工样本积累）？
2. **mcp_cognitive 环境**：当前 FAIL-OPEN（recall 返回 []），是否需要先解决 MCP 可用性再推进 P1？还是接受 FAIL-OPEN 降级先跑通链路？
3. **LLM 汇总边界**：P4 的 LLM 仅做 summary+charts+debate，是否还有其他"内容整合汇总"场景需要纳入？
4. **subagent 接入顺序**：P2 technical+sentiment → P4 其余 6 个，是否同意？还是调整优先级？
5. **C-Drive 辩论阈值**：Bull/Bear 辩论触发 0.65、分级 0.75/0.65/0.50，初始值是否符合预期？
6. **三层分工流量目标**：算法层 70-90% / Harness 评审 20-30% / Agent 接管 <10%，是否接受？
