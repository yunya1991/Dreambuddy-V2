# 执行引擎重构设计 — A层动态编排正确化

> 日期: 2026-07-04
> 状态: 设计中（v2 — 修正动态编排理解）

## 一、问题背景

### 当前问题

前端 `task-manager.ts` 按 S1-S5 硬编码线性执行，`task/route.ts` 把 S1-S5 直接当作 A层节点塞入 `chain_trace`。

### 架构正解

架构文档 §1.5.3 和 §3.3 明确：

> A层是纯编排层，节点来自 NodeRegistry，A层不包含任何业务节点。
> A层 — Architecture（执行图/DAG）：动态可变，AI驱动，步骤级粒度，节点就是具体的SKILL调用。

**关键**：A层不固定于任何链（A/C/F），而是**动态编排**。已有基础设施完全支持：

| 组件 | 位置 | 作用 |
|------|------|------|
| `S_CHAIN_STEPS` / `C_CHAIN_STEPS` / `F_CHAIN_STEPS` | `step-types.ts` | 思维阶段定义（骨架），每阶段有 `recommendedSkillCategories` 和 `crossValidationChains` |
| `SkillsRegistry.recommend(context)` | `skills-registry.ts` | 根据意图/阶段/市场条件**动态推荐**技能，跨 A/C/F 链 |
| `SkillSelector.select()` | `skill-selector.ts` | 过滤、排序、分组（并行/串行），基于依赖关系 |
| `ExecutionPlanner.createPlan()` | `planner.ts` | 四维规划（Token预算/知识库命中/历史表现/标的覆盖）→ DAG |
| `ExecutionPlanner.executePlan()` | `planner.ts` | 动态执行：proceed/iterate/skip/insert/backtrack/terminate |

### 动态编排流程

```
S层: routeIntent → IntentResult
      ├─ 推荐主链 (A/C/F)
      ├─ 扩展节点池 (extend_nodes)
      └─ 意图置信度

A层: ExecutionPlanner.createPlan(context)
      │
      ├─ 1. 推断主链 (inferPrimaryChain)
      ├─ 2. ChainPlanner 四维规划
      │   ├─ Token预算过滤
      │   ├─ 知识库命中（可能触发快捷路径）
      │   ├─ 历史表现过滤
      │   └─ 标的覆盖检查
      │
      ├─ 3. 生成 PlannedStep[]（每步含思维阶段定义）
      │
      └─ 4. 每步内：SkillSelector.select()
          ├─ registry.recommend(context) → 候选技能（跨A/C/F链）
          ├─ filterRecommendations（过滤不适用技能）
          └─ groupByParallelism（按依赖分组，支持并行）

C层: ExecutionPlanner.executePlan()
      ├─ 逐 step 执行
      ├─ 每 step 内调用选中的 skills
      ├─ Reflector 决策（proceed/iterate/insert/backtrack/terminate）
      └─ 结果聚合
```

**核心**：同一个思维阶段（如 S2_分析）可能选中：
- `dream-regime-detector`（A链，市场状态识别）
- `RegimeHybridStrategy`（C链，经典策略匹配）
- `dream-fundamental-news`（F链，新闻聚合）

这三者**并行执行**，结果交叉验证。这就是动态编排。

## 二、设计目标

让 `task-manager.ts` 接入已有的 `ExecutionPlanner`，用动态选技能替代硬编码 S1-S5 链。

### 关键原则

1. **不建立 S→A 固定映射**：S1-S5 是思维阶段骨架，不是 A层节点
2. **A层节点 = 动态选中的技能**：来自 Registry，跨 A/C/F 链
3. **DAG 由阶段+技能+依赖构成**：非线性序列
4. **执行中可动态调整**：insert/backtrack/skip

### 数据流

```
S层: routeIntent → IntentResult (推荐主链 + 扩展节点)
     ↓
A层: ExecutionPlanner.createPlan()
     → PlannedStep[] (每步含 selectedSkills[])
     → DAG (步骤间有依赖关系，步骤内技能可并行)
     ↓
C层: ExecutionPlanner.executePlan()
     → StepExecutionResult[] (每步含 skillsCalled[])
     → 动态调整 (insert/backtrack)
     ↓
chain_trace:
  B层 = 意图蓝图 (intent + chain + complexity)
  A层 = 思维阶段 + 动态选中技能 (S1_调研: [dream-screen1-first, RegimeHybridStrategy, ...])
  C层 = 执行记录 (每技能的实际调用结果)
```

## 三、改动模块详解

### 模块1：新建 `src/lib/orchestration/` 执行桥接层

#### `llm-bridge.ts`

封装 LLM 调用，复用 task-manager 现有 LLM 逻辑：

```typescript
export interface LLMCallOptions {
  prompt: string;
  systemPrompt?: string;
  temperature?: number;
  maxTokens?: number;
  timeoutMs?: number;
}

export interface LLMCallResult {
  content: string;
  model: string;
  tokensUsed: number;
  latencyMs: number;
}

export async function callLLM(options: LLMCallOptions): Promise<LLMCallResult>;
```

- 从数据库读取用户配置的 LLM API（复用 `/api/config/api-keys` 的配置）
- 支持 OpenAI/DeepSeek/百炼/Claude 等多提供商
- 超时保护、错误降级

#### `market-data-bridge.ts`

封装市场数据获取，复用 `fetchMarketData`：

```typescript
export interface MarketDataContext {
  symbol: string;
  instId: string;
  category: string;
  displayName: string;
}

export async function getMarketData(ctx: MarketDataContext): Promise<MarketData>;
```

#### `node-prompts.ts`

各技能的 prompt 模板（按技能ID，非按节点ID）：

```typescript
// 通用 prompt 构建 — 任何技能都可调用
export function buildSkillPrompt(
  skillId: string,           // 'dream-regime-detector', 'dream-fundamental-news' 等
  stage: ThinkStage,         // 'research' | 'analysis' | ...
  inputs: Record<string, unknown>,
  context: ExecutionContext
): string;
```

### 模块2：重构 `skills-registry-init.ts` — 技能真实化

每个技能从 mock 改为真实执行。**关键**：技能可以来自 A/C/F 任何链，全部接入真实 LLM：

```typescript
// 示例：dream-regime-detector (A链, 市场状态识别)
const regimeDetectorSkill = createSkill({
  id: 'dream-regime-detector',
  name: '市场状态识别器',
  chain: 'A',
  category: 'execution',
  // ...
  async execute(inputs, context) {
    const symbol = (inputs.symbol as string) || context.symbol || 'BTC';
    const marketData = await getMarketData({ symbol, ... });
    const prompt = buildSkillPrompt('dream-regime-detector', 'research', inputs, context);
    const llmResult = await callLLM({ prompt, systemPrompt: REGIME_SYSTEM_PROMPT });
    return parseRegimeResult(llmResult.content, symbol);
  },
});

// 示例：RegimeHybridStrategy (C链, 经典策略匹配)
const regimeStrategySkill = createSkill({
  id: 'RegimeHybridStrategy',
  name: 'Regime混合策略',
  chain: 'C',
  category: 'classic-strategy',
  // ...
  async execute(inputs, context) {
    // 同样接入真实 LLM/数据
    const prompt = buildSkillPrompt('RegimeHybridStrategy', 'analysis', inputs, context);
    const llmResult = await callLLM({ prompt });
    return parseResult(llmResult.content);
  },
});

// 示例：dream-fundamental-news (F链, 新闻聚合) — 已有真实实现，保持
```

**原则**：所有链的技能平等接入真实 LLM，由 `SkillSelector` 根据上下文动态选择。

### 模块3：重构 `task-manager.ts` — 接入 ExecutionPlanner

#### 核心改动

`executeConversationTaskInline` 中，替换 S1-S5 循环为 ExecutionPlanner 调用：

```typescript
// 之前：
const depthSteps = getChainByThinkingDepth(thinkingMode, intentType);
for (const step of depthSteps) { /* 执行 S 步骤 */ }

// 之后：
import { ExecutionPlanner } from '../../../../6-图结构上下文压缩/planner/planner';
import { ensureRegistryInitialized } from '../../../../6-图结构上下文压缩/planner/skills-registry-init';

const registry = ensureRegistryInitialized();
const planner = new ExecutionPlanner(registry);

const plan = planner.createPlan({
  sessionId: task.session_id,
  userRequest: task.message,
  intent: intentType,
  complexity: thinkingMode as ComplexityLevel,  // 'quick' | 'standard' | 'deep'
  symbol: rawSymbol,
  tradingMode: task.trading_mode || 'ai_skill',
});

const execResult = await planner.execute({
  sessionId: task.session_id,
  intent: intentType,
  complexity: thinkingMode as ComplexityLevel,
  symbol: rawSymbol,
  userRequest: task.message,
  tradingMode: task.trading_mode || 'ai_skill',
});

// execResult.steps → 每步含 selectedSkills + skillsCalled
// execResult.overallConfidence → 整体置信度
// execResult.totalTokensUsed → Token 消耗
```

#### 保留的前置路由

以下逻辑保留不变：
- 意图澄清（`need_clarification`）→ 直接返回
- 非金融话题检测 → 跳过
- `developer` 意图 → 委托 S5 执行引擎
- Dynamic chain（PRO用户深度意图）→ 委托动态链
- Step confirmation（D/Z/E 链步进确认）

#### Fallback 机制

```typescript
try {
  const result = await executeWithPlanner(task, context);
  return result;
} catch (error) {
  console.warn('[ExecutionPlanner] 降级到 S链执行', error);
  return executeWithSChain(task, context);  // 保留原 S1-S5 作为降级
}
```

### 模块4：重构 `task/route.ts` — chain_trace 动态构建

**关键变化**：A层节点不再是固定 ID（A1/A2...），而是动态选中的技能：

```typescript
const chain_trace = {
  intent: {
    type: task.intent.type,
    confidence: task.intent.confidence,
    method: 'llm',
    entities: task.intent.entities || {},
  },
  plan: {
    chain_id: plan.metadata.primaryChain,     // 'A' | 'C' | 'F' | 'hybrid'
    chain_name: '',                            // 从规划结果获取
    planned_steps: plan.steps.map(s => ({
      step_id: s.stepId,                       // 'S1', 'C2', 'F3' (思维阶段)
      stage: s.stage,                          // 'research' | 'analysis' | ...
      chain: s.chain,                          // 'A' | 'C' | 'F'
      selected_skills: s.selectedSkills.map(sk => sk.skillId),
    })),
    complexity: task.thinking_mode,
    total_budget: plan.estimatedTokens,
    rationale: plan.metadata.chainPlanRationale,
    pruned_nodes: plan.metadata.prunedNodes,
  },
  nodes: [
    // B层 — 意图蓝图
    { id: 'B1_intent', name: '意图识别', icon: '🎯', layer: 'B', status: 'done', confidence: task.intent.confidence },
    { id: 'B2_route', name: '链路选择', icon: '🔀', layer: 'B', status: 'done' },
    { id: 'B3_complexity', name: '复杂度评估', icon: '📏', layer: 'B', status: 'done' },

    // A层 — 动态编排的步骤+技能（跨A/C/F链）
    ...execResult.steps.flatMap((step) => {
      // 每个思维阶段是一个"步骤节点"
      const stepNode: OrchestrationNode = {
        id: step.stepId,                       // 'S1', 'C2', 'F3'
        name: step.definition?.label || step.stepId,
        icon: step.definition?.icon || '⚙️',
        layer: 'A',
        stage: step.stage,                     // 'research' | 'analysis' | ...
        status: step.status === 'completed' ? 'done' : step.status === 'running' ? 'active' : step.status,
        confidence: step.confidence / 100,     // 0-1 范围
        tokens_used: step.tokensUsed,
        reflect_action: step.decision,         // 'proceed' | 'iterate' | 'skip' | ...
      };

      // 步骤内每个选中的技能也是 A层节点（子节点）
      const skillNodes: OrchestrationNode[] = step.skillsCalled.map((skillCall) => ({
        id: skillCall.skillId,                 // 'dream-regime-detector', 'RegimeHybridStrategy', ...
        name: skillCall.skillName,
        icon: getSkillIcon(skillCall.skillId), // 根据技能链获取图标
        layer: 'A' as const,
        status: 'done' as const,
        confidence: skillCall.result.confidence / 100,
        tokens_used: skillCall.result.tokensUsed,
        latency_ms: skillCall.latencyMs,
      }));

      return [stepNode, ...skillNodes];
    }),

    // C层 — 执行记录
    { id: 'C1_execute', name: '链路执行', icon: '⚡', layer: 'C', status: 'done', latency_ms: result.execution_time_ms },
    { id: 'C2_reflect', name: '反射决策', icon: '🔄', layer: 'C', status: 'done' },
    { id: 'C3_aggregate', name: '结果聚合', icon: '📊', layer: 'C', status: 'done' },
  ],
  final: {
    execution_chain: execResult.steps.map(s => s.stepId).join(' → '),
    quality_score: execResult.overallConfidence / 100,
    risk_score: quality?.max_risk || 0.3,
    grade: quality?.overall_quality || 'good',
  },
};
```

**关键区别**：
- A层节点 = 思维阶段（S1/C2/F3）+ 动态选中的技能（dream-regime-detector / RegimeHybridStrategy / ...）
- 技能来自 A/C/F 任何链，由 SkillSelector 动态选择
- 不再有固定的 S1→A1 映射

### 模块5：前端组件适配

#### `types/index.ts`

```typescript
export interface OrchestrationNode {
  id: string;                   // 'S1' | 'dream-regime-detector' | ...
  name: string;
  icon: string;
  layer: "B" | "A" | "C";
  stage?: string;               // 'research' | 'analysis' | 'design' | 'validate' | 'execute'
  status: OrchestrationNodeStatus;
  confidence?: number;
  risk?: number;
  latency_ms?: number;
  tokens_used?: number;
  tokens_budget?: number;
  skip_reason?: string;
  reflect_action?: string;      // 'proceed' | 'iterate' | 'skip' | 'insert' | 'backtrack'
  artifact?: string;
}

export interface ChainTrace {
  // ...
  plan: {
    chain_id: string;
    chain_name: string;
    planned_steps?: Array<{     // 新增：动态规划的步骤
      step_id: string;
      stage: string;
      chain: string;
      selected_skills: string[];
    }>;
    complexity: string;
    total_budget: number;
    rationale: string;
    pruned_nodes?: Array<{ stepId: string; reason: string }>;
  };
}
```

#### `ThinkingCard.tsx`

图标映射改为按阶段 + 技能链：

```typescript
// 思维阶段图标
const STAGE_ICONS: Record<string, string> = {
  'research': '🔍',
  'analysis': '🧠',
  'design': '📐',
  'validate': '✅',
  'execute': '⚡',
};

// 技能链图标（根据技能ID前缀）
function getSkillIcon(skillId: string): string {
  if (skillId.startsWith('dream-')) return '🤖';   // A链技能
  if (skillId.startsWith('Regime') || skillId.startsWith('Classic')) return '📊'; // C链
  if (skillId.includes('fundamental') || skillId.includes('news')) return '📰';    // F链
  return '⚙️';
}
```

#### `OrchestrationPanel.tsx`

A层展示改为两层结构：
- **第一层**：思维阶段（S1_调研, S2_分析...）
- **第二层**：每阶段内动态选中的技能（可来自 A/C/F 任何链）

```tsx
// A层节点分组：按思维阶段分组
const aStepNodes = trace.nodes.filter(n => n.layer === 'A' && STAGE_ICONS[n.stage]);
const aSkillNodes = trace.nodes.filter(n => n.layer === 'A' && !STAGE_ICONS[n.stage]);

// 展示：每个阶段 + 其选中的技能
{aStepNodes.map(step => (
  <div key={step.id}>
    <NodeBlock node={step} />  {/* 思维阶段 */}
    {/* 该阶段选中的技能（跨链） */}
    {aSkillNodes
      .filter(skill => skill.stage === step.stage)
      .map(skill => <NodeBlock node={skill} small />)}
  </div>
))}
```

## 四、实施顺序

| 阶段 | 内容 | 改动文件 | 风险 |
|------|------|---------|------|
| P1 | 新建 orchestration 桥接层 | `src/lib/orchestration/llm-bridge.ts`<br>`src/lib/orchestration/market-data-bridge.ts`<br>`src/lib/orchestration/node-prompts.ts` | 低 |
| P2 | 重构所有技能为真实执行（A/C/F全链） | `6-图结构上下文压缩/planner/skills-registry-init.ts` | 中 |
| P3 | task-manager 接入 ExecutionPlanner | `src/lib/task-manager.ts` | 高 |
| P4 | task/route.ts chain_trace 动态构建 | `src/app/api/task/route.ts` | 中 |
| P5 | 前端组件适配 | `src/types/index.ts`<br>`src/components/chat/ThinkingCard.tsx`<br>`src/components/orchestration/OrchestrationPanel.tsx` | 低 |

## 五、风险与缓解

| 风险 | 缓解措施 |
|------|---------|
| 现有功能中断 | 保留 S1-S5 执行作为 fallback；try-catch 降级 |
| LLM 调用成本增加 | BudgetAllocator 控制节点数量；ChainPlanner 预算过滤 |
| 执行时间变慢 | SkillSelector 分组并行执行无依赖技能；高置信度跳过 |
| LLM 不可用 | 技能降级为 mock；返回 fallback 结果 |
| ExecutionPlanner 接口不匹配 | P3 前先验证 planner.ts 的 createPlan/execute 接口 |

## 六、验证标准

1. `chain_trace.plan.planned_steps` 返回动态规划的步骤，每步含 `selected_skills` 数组
2. `selected_skills` 中包含跨链技能（A链 + C链 或 F链混合）
3. `chain_trace.nodes` 中 A层节点包含思维阶段 + 技能两层
4. ThinkingCard 展示思维阶段 + 每阶段选中的技能
5. OrchestrationPanel A层展示跨链技能编排
6. 现有功能（行情查询、深度分析等）正常工作
7. LLM 不可用时降级到 mock，不报错
8. 同一思维阶段可以选中不同链的技能（如 S2_分析同时调用 A链+C链技能）

## 七、与 v1 设计的关键差异

| 维度 | v1（错误） | v2（正确） |
|------|-----------|-----------|
| A层节点 | 固定 A1-A9 | 动态选中的技能（跨A/C/F链） |
| S链角色 | 映射到A1-A5 | 思维阶段骨架，不映射 |
| NODE_STAGE_MAP | 有（S1→A1） | 无（不建立固定映射） |
| 技能来源 | 仅A系列 | A/C/F 全链 Registry |
| DAG结构 | 线性 A1→A2→...→A9 | 阶段+技能+依赖的动态DAG |
