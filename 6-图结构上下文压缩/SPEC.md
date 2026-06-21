# 双维度编排架构规范 (Dual-Dimension Orchestration Architecture)

> **版本**: v1.0
> **日期**: 2026-06-21
> **理念**: 思维链简化（符合人类思维逻辑）+ AI推理动态化（根据推理验证选择最佳路径）+ 技能/功能模块专业化（一旦调用能解决实际问题）
> **核心价值**: 驱动AI在复杂交易场景中做出透明、可信、可追溯的最优决策

---

## 一、设计理念

### 1.1 问题定义

当前系统存在以下问题：

| 问题 | 表现 | 根因 |
|------|------|------|
| **S链过重** | S1-S5 被硬编码实现，每步内部逻辑固定 | 将"思维框架"和"具体实现"混为一谈 |
| **能力不可复用** | A系列技能、三屏系统、经典指标模块各自独立，无法统一调度 | 缺乏统一的能力调用契约 |
| **推理黑盒** | AI 的推理过程不可追溯，用户不知道结论怎么来的 | 缺乏置信度评估和决策路径记录 |
| **链间隔离** | S/C/F 三条链互斥，无法交叉验证 | 将不同分析维度当成"替代品"而非"互补品" |
| **扩展困难** | 新增技能需要修改多处代码 | 缺乏技能注册表和动态调度机制 |

### 1.2 设计目标

```
┌─────────────────────────────────────────────────────────────────────┐
│                         设计目标                                      │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  🎯 目标1: 思维链简化                                               │
│     S/C/F 链 = 固定的五步思维顺序，不包含具体实现                     │
│     每步内部由 AI 动态决定：调用什么技能？置信度够吗？是否迭代？       │
│                                                                     │
│  🎯 目标2: AI推理动态化                                            │
│     每个思维步骤都是一个"决策点"                                      │
│     AI 在此评估：需要什么信息？有哪些可用技能？选哪个？                │
│     必须评估产出置信度，不足时迭代或降级                              │
│                                                                     │
│  🎯 目标3: 技能专业化                                               │
│     每个技能（A/C/F系列）都是独立的、可被调用的能力单元               │
│     有统一契约：输入 → 处理 → 输出 + 置信度评分                       │
│     技能可以独立优化，不影响思维框架                                  │
│                                                                     │
│  🎯 目标4: 交叉验证                                                 │
│     S/C/F 三链在关键节点做交叉验证                                   │
│     三链投票：多源印证 → 高置信度；链间冲突 → 触发深入分析           │
│                                                                     │
│  🎯 目标5: 推理透明                                                 │
│     图架构压缩模块记录完整的思考轨迹                                 │
│     用户能看到：AI 调用了什么技能、产出了什么、置信度多少             │
│     便于追溯、便于复盘、便于用户信任 AI 的决策                       │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

### 1.3 三层架构模型

```
┌────────────────────────────────────────────────────────────────────────┐
│                    LAYER 1: 思维框架 (Thinking Framework)              │
│                                                                        │
│   作用: 定义"思考的顺序"，不定义"思考的具体内容"                       │
│                                                                        │
│   S链 (通用交易思维):                                                   │
│     S1_调研 → S2_分析 → S3_设计 → S4_验证 → S5_执行                    │
│                                                                        │
│   C链 (量化技术思维):                                                   │
│     C1_扫描 → C2_识别 → C3_匹配 → C4_回测 → C5_参数                    │
│                                                                        │
│   F链 (基本面思维):                                                     │
│     F1_新闻 → F2_资金 → F3_情绪 → F4_链上 → F5_宏观                    │
│                                                                        │
│   ★ 思维链是"骨架"，内部实现由 AI 推理决定                              │
│   ★ 可以跳过某步（如果信息充分/置信度已够）                             │
│   ★ 可以迭代某步（如果置信度不足）                                      │
└────────────────────────────────┬───────────────────────────────────────┘
                                 │
                                 ▼
┌────────────────────────────────────────────────────────────────────────┐
│                  LAYER 2: AI推理引擎 (Execution Planner)                │
│                                                                        │
│   作用: 在每个思维步骤内，做动态决策                                     │
│                                                                        │
│   核心决策循环:                                                         │
│     1. 问题定义: "这步要解决什么？"                                      │
│     2. 技能选择: "从能力表中选哪些技能组合？"                            │
│     3. 并行/串行执行技能                                                │
│     4. 置信度评估: "产出可信吗？"（0-100，必须做）                       │
│     5. 分支: 高置信→下一步 / 中置信→迭代 / 低置信→警告/降级            │
│     6. 写入图架构: 记录决策过程 + 技能产出 + 置信度                      │
│                                                                        │
│   交叉验证:                                                             │
│     在关键节点进行 S/C/F 三链加权投票                                    │
│     多源印证 → 高置信度 / 链间冲突 → 深入分析                            │
└────────────────────────────────┬───────────────────────────────────────┘
                                 │
                                 ▼
┌────────────────────────────────────────────────────────────────────────┐
│                LAYER 3: 技能库 (Capability Library)                    │
│                                                                        │
│   作用: 提供具体的、可被调用的专业能力                                   │
│                                                                        │
│   A系列 (AI交易技能):                                                   │
│     三屏交易: dream-screen1/2/3 (周线/日线/实时)                       │
│     执行闭环: strategy-parser, signal-scoring, regime-detector,          │
│              risk-position-sizing, pretrade-gatekeeper,                 │
│              tactical-executor, exit-skill                               │
│     情报闭环: intelligence-monitor, master-seminar, oneirology           │
│     治理闭环: compliance, cost-control, performance-review,             │
│              dual-agent-conflict-gate                                  │
│     研究工具: strategy-research, strategy-designer, war-game-simulator,  │
│              backtest, bayesian-opt, contradiction-theory              │
│                                                                        │
│   C系列 (经典量化模块):                                                  │
│     指标库: RSI/MACD/MA/Bollinger/Ichimoku/ATR...                     │
│     策略库: 经典10策略, freqtrade策略, tradingview策略                  │
│     回测引擎: 历史数据回测, Gate评估, 参数优化                           │
│     执行引擎: Freqtrade, OKX Conditional Order                          │
│                                                                        │
│   F系列 (基本面工具):                                                    │
│     新闻聚合, 资金流向, 情绪分析, 链上指标, 宏观数据                     │
│                                                                        │
│   ★ 每个技能都有: 输入契约 + 输出契约 + 成本 + 延迟 + 历史表现            │
└────────────────────────────────────────────────────────────────────────┘
```

---

## 二、核心类型定义

### 2.1 技能能力接口 (SkillCapability)

```typescript
/**
 * 技能能力接口 - 所有技能必须实现的统一契约
 * 位置: 6-图结构上下文压缩/planner/skill-types.ts
 */

/** 技能的输入定义 */
interface SkillInput {
  name: string;
  type: 'string' | 'number' | 'boolean' | 'object' | 'array';
  required: boolean;
  description: string;
  example?: any;
}

/** 技能的输出定义 */
interface SkillOutput {
  name: string;
  type: 'string' | 'number' | 'boolean' | 'object' | 'array';
  description: string;
}

/** 技能的元信息 */
interface SkillMetadata {
  id: string;                          // 唯一标识: 'dream-regime-detector'
  name: string;                        // 可读名称
  description: string;                 // 简短描述
  chain: 'A' | 'C' | 'F';            // 所属链
  category: string;                    // 分类: 'execution' | 'intelligence' | 'governance' | 'research'
  version: string;                     // 版本
  tags: string[];                     // 标签: ['trend', 'oscillation', 'volatility']

  // 成本与性能
  estimatedTokens: number;             // 预估 token 消耗
  estimatedLatencyMs: number;          // 预估延迟
  confidenceRange: [number, number];  // 典型置信度范围

  // 适用场景
  applicableIntents: string[];        // 适用的用户意图
  applicableStages: ('research' | 'analysis' | 'design' | 'validate' | 'execute')[];
  marketConditions?: string[];        // 最佳市场条件: ['trending', 'ranging', 'volatile']

  // 历史表现 (用于动态权重)
  historicalAccuracy?: number;         // 历史准确率
  historicalCalls?: number;            // 总调用次数
}

/** 技能能力接口 */
export interface SkillCapability {
  metadata: SkillMetadata;
  inputSchema: SkillInput[];
  outputSchema: SkillOutput[];

  /** 执行技能 */
  execute(inputs: Record<string, any>, context: ExecutionContext): Promise<SkillResult>;

  /** 验证输入合法性 */
  validate?(inputs: Record<string, any>): { valid: boolean; errors?: string[] };

  /** 获取降级实现 (可选) */
  getFallback?(inputs: Record<string, any>): Promise<SkillResult>;

  /** 获取技能状态 */
  getStatus?(): Promise<SkillStatus>;
}

/** 技能执行结果 */
export interface SkillResult {
  success: boolean;
  capabilityId: string;
  outputs: Record<string, any>;           // 结构化输出
  confidence: number;                    // 本次执行的置信度 (0-100)
  confidenceDimensions?: {               // 置信度分项评分
    dataCompleteness: number;
    logicalConsistency: number;
    crossValidation?: number;
    historicalPerformance?: number;
  };
  tokensUsed?: number;
  latencyMs?: number;
  error?: string;
  warnings?: string[];                  // 警告信息 (如数据质量、潜在问题)
  suggestions?: string[];               // 建议 (如下一步可以做什么)
  metadata?: Record<string, any>;        // 额外元信息
}

/** 执行上下文 */
export interface ExecutionContext {
  sessionId: string;
  intent: string;
  symbol?: string;
  userRole: 'FREE' | 'PRO' | 'ADMIN';
  tradingMode: 'ai_skill' | 'classic' | 'hybrid';
  budgetTokens?: number;
  maxLatencyMs?: number;
  chainWeights?: { s_chain: number; c_chain: number; f_chain: number };
  priorOutputs?: Record<string, SkillResult>;  // 前序技能的产出
}

/** 技能状态 */
export interface SkillStatus {
  healthy: boolean;
  lastExecutionMs?: number;
  errorRate?: number;
  avgLatencyMs?: number;
}
```

### 2.2 思维步骤接口 (ThinkingStep)

```typescript
/**
 * 思维步骤接口 - 定义每个思维阶段的契约
 * 位置: 6-图结构上下文压缩/planner/step-types.ts
 */

/** 思维阶段 */
export type ThinkStage = 'research' | 'analysis' | 'design' | 'validate' | 'execute';

/** 思维步骤定义 */
export interface ThinkingStepDefinition {
  id: string;                           // 'S1', 'S2', ... 或 'C1', 'C2', ...
  stage: ThinkStage;
  chain: 'S' | 'C' | 'F';

  // 步骤描述
  label: string;                        // 'S1_调研'
  icon: string;                         // '🔍'
  description: string;                  // '市场数据、行情、技术指标、新闻收集'

  // 核心问题 (AI 需要回答的)
  coreQuestion: string;                 // '当前市场发生了什么？趋势是什么？'

  // 期望产出
  expectedOutputs: string[];            // ['市场趋势', '关键事件', '数据质量评估']

  // 置信度要求
  confidenceThresholds: {
    high: number;                       // >= 80, 直接进入下一步
    medium: number;                    // 50-80, 迭代补充
    low: number;                        // < 50, 警告或降级
  };

  // 可选: 此步骤推荐的技能类别
  recommendedSkillCategories?: string[];

  // 可选: 此步骤强制调用的技能
  requiredSkills?: string[];

  // 可选: 步骤间的依赖关系
  dependsOn?: string[];                 // 需要先完成的步骤
}

/** 思维步骤执行结果 */
export interface StepExecutionResult {
  stepId: string;
  stage: ThinkStage;
  chain: 'S' | 'C' | 'F';

  // 执行状态
  status: 'pending' | 'running' | 'completed' | 'skipped' | 'failed' | 'iterating';

  // 核心问题 + AI 的回答
  coreQuestion: string;
  answer: string;                       // 自然语言回答

  // 调用的技能
  skillsCalled: Array<{
    skillId: string;
    skillName: string;
    result: SkillResult;
    invocationIndex: number;            // 第几次调用 (迭代时递增)
  }>;

  // 置信度评估
  confidence: number;
  confidenceDimensions?: SkillResult['confidenceDimensions'];

  // 信息缺口 (如果置信度不足)
  gaps?: Array<{
    type: 'missing-data' | 'missing-skill' | 'logical-conflict' | 'insufficient-evidence';
    description: string;
    suggestedAction: string;
    suggestedSkillId?: string;
  }>;

  // 决策
  decision: 'proceed' | 'iterate' | 'skip' | 'warn' | 'escalate';
  decisionReason: string;

  // 迭代信息 (如果有)
  iterations?: number;
  iterationReason?: string;

  // 性能指标
  tokensUsed?: number;
  latencyMs?: number;

  // 图架构节点
  architectureNode: SerializedNode;    // 写入图架构压缩模块
}
```

### 2.3 执行规划器接口 (ExecutionPlanner)

```typescript
/**
 * 执行规划器接口 - AI 推理的核心调度器
 * 位置: 6-图结构上下文压缩/planner/planner-types.ts
 */

/** 规划上下文 */
export interface PlannerContext {
  sessionId: string;
  userRequest: string;                  // 用户的自然语言请求
  intent: IntentType;                   // 识别的意图类型
  complexity: 'quick' | 'standard' | 'deep';

  // 上下文
  priorHistory?: PriorHistory;          // 历史对话摘要
  userPreferences?: UserPreferences;    // 用户偏好
  tradingMode: 'ai_skill' | 'classic' | 'hybrid';

  // 约束
  budgetTokens?: number;
  maxLatencyMs?: number;

  // 动态权重 (可被市场状态影响)
  chainWeights: ChainWeights;
}

/** 历史上下文 */
export interface PriorHistory {
  previousSteps?: StepExecutionResult[];
  previousConclusions?: string[];
  previousConfidences?: number[];
}

/** 用户偏好 */
export interface UserPreferences {
  riskTolerance: 'low' | 'medium' | 'high';
  preferredChains?: ('S' | 'C' | 'F')[];
  maxCostPerRequest?: number;
  preferredTradingStyle?: string;
}

/** 链权重 */
export interface ChainWeights {
  s_chain: number;                      // AI 技能权重
  c_chain: number;                     // 经典指标权重
  f_chain: number;                      // 基本面权重
}

/** 执行计划 */
export interface ExecutionPlan {
  planId: string;
  createdAt: number;

  // 计划的思维步骤序列
  steps: PlannedStep[];

  // 成本预估
  estimatedTokens: number;
  estimatedLatencyMs: number;

  // 交叉验证节点
  crossValidationNodes: PlannedCrossValidation[];

  // 降级计划 (如果预算不足)
  fallbackPlan?: ExecutionPlan;
}

/** 计划的单个步骤 */
export interface PlannedStep {
  stepId: string;
  chain: 'S' | 'C' | 'F';
  stage: ThinkStage;

  // AI 决定调用的技能组合
  selectedSkills: Array<{
    skillId: string;
    priority: number;
    invocationMode: 'parallel' | 'sequential';
    dependsOn?: string[];               // 串行时的依赖
  }>;

  // 预期的置信度输出
  expectedConfidence: number;
  acceptableMinConfidence: number;

  // 如果置信度不足，是否允许迭代
  allowIteration: boolean;
  maxIterations: number;
}

/** 计划的交叉验证节点 */
export interface PlannedCrossValidation {
  nodeId: string;                       // 'CV1', 'CV2', ...
  afterStep: string;                    // 在哪个步骤后进行
  participatingChains: ('S' | 'C' | 'F')[];

  // 投票权重 (对应 chainWeights)
  weights: ChainWeights;

  // 触发条件
  triggerCondition: {
    type: 'always' | 'on_conflict' | 'on_low_confidence';
    threshold?: number;                 // 低于此置信度才触发
  };

  // 降级策略
  fallback: {
    type: 'majority_vote' | 'highest_confidence' | 'weighted_average' | 'manual_override';
    requireUserConfirmation?: boolean;
  };
}
```

### 2.4 交叉验证接口 (CrossValidation)

```typescript
/**
 * 交叉验证接口 - 三链投票机制
 * 位置: 6-图结构上下文压缩/planner/cross-validation-types.ts
 */

/** 交叉验证节点 */
export interface CrossValidationNode {
  nodeId: string;
  stage: ThinkStage;                    // 'research' | 'analysis' | 'design' | 'validate' | 'execute'
  triggeredAt: number;

  // 各链的信号
  signals: {
    chain: 'S' | 'C' | 'F';
    direction: 'long' | 'short' | 'neutral' | 'wait';
    confidence: number;
    reasoning: string;
    sourceSteps: string[];             // 来源的步骤 ID
  }[];

  // 加权投票结果
  consensus: {
    direction: 'long' | 'short' | 'neutral' | 'wait';
    overallConfidence: number;         // 加权平均置信度
    agreementLevel: 'strong' | 'moderate' | 'weak' | 'conflict';

    // 投票细节
    votes: Array<{
      chain: 'S' | 'C' | 'F';
      weight: number;
      rawConfidence: number;
      weightedContribution: number;
    }>;
  };

  // 冲突检测 (如果有)
  conflicts?: Array<{
    type: 'direction_conflict' | 'confidence_gap' | 'reasoning_inconsistency';
    involvedChains: ('S' | 'C' | 'F')[];
    description: string;
    resolution?: string;
  }>;

  // 决策建议
  recommendedAction: 'proceed' | 'deep_dive' | 'pause' | 'override';
  deepDivePlan?: {
    additionalSkills: string[];
    expectedImprovement: number;
    estimatedExtraCost: number;
  };

  // 写入图架构的节点
  architectureNode: SerializedNode;
}

/** 投票计算器配置 */
export interface VotingConfig {
  // 基础权重
  weights: ChainWeights;

  // 置信度门槛
  confidenceThreshold: {
    strong: number;                     // >= 80, 强一致
    moderate: number;                   // >= 60, 中等一致
    weak: number;                      // >= 40, 弱一致
    conflict: number;                   // < 40, 冲突
  };

  // 方向映射 (将信号转为数值用于加权)
  directionMapping: {
    long: number;                      // +1
    short: number;                     // -1
    neutral: number;                   // 0
    wait: number;                      // 0 (不参与投票)
  };
}
```

---

## 三、技能注册表 (Skills Registry)

### 3.1 注册表设计

```typescript
/**
 * 技能注册表 - 所有可用技能的中心索引
 * 位置: 6-图结构上下文压缩/planner/skills-registry.ts
 */

interface SkillsRegistry {
  // 注册技能
  register(skill: SkillCapability): void;

  // 获取技能
  get(skillId: string): SkillCapability | undefined;

  // 按条件查询
  query(params: {
    chain?: ('A' | 'C' | 'F') | ('A' | 'C' | 'F')[];
    category?: string | string[];
    stage?: ThinkStage | ThinkStage[];
    intent?: string | string[];
    tag?: string | string[];
  }): SkillCapability[];

  // 推荐技能 (基于上下文)
  recommend(context: ExecutionContext): SkillCapability[];

  // 获取技能状态
  getStatus(skillId: string): Promise<SkillStatus>;

  // 获取所有技能的元信息摘要
  getManifest(): SkillMetadata[];
}
```

### 3.2 技能分类

```
技能分类结构:

├── A系列 (AI交易技能)
│   ├── 三屏交易 (screen1/screen2/screen3)
│   ├── 执行闭环 (strategy-parser, signal-scoring, regime-detector,
│   │             risk-position-sizing, pretrade-gatekeeper,
│   │             tactical-executor, tactical-validator, exit-skill)
│   ├── 情报闭环 (intelligence-monitor, master-seminar, oneirology)
│   ├── 治理闭环 (compliance, cost-control, performance-review,
│   │             operation-director, dual-agent-conflict-gate)
│   └── 研究工具 (strategy-research, strategy-designer,
│                 war-game-simulator, backtest, bayesian-opt,
│                 contradiction-theory, first-principles)
│
├── C系列 (经典量化模块)
│   ├── 技术指标 (RSI, MACD, MA, Bollinger, Ichimoku, ATR, ...)
│   ├── 经典策略 (经典10策略, freqtrade策略)
│   ├── 状态识别 (RegimeHybridStrategy)
│   ├── 回测引擎 (T11, T12, T15)
│   └── 执行引擎 (Freqtrade, OKX Conditional)
│
└── F系列 (基本面工具)
    ├── 新闻事件 (F1 - 新闻聚合)
    ├── 资金流向 (F2 - 链上/交易所资金)
    ├── 市场情绪 (F3 - 社交媒体情绪)
    ├── 链上指标 (F4 - MVRV, NUPL, 活跃地址)
    └── 宏观数据 (F5 - 利率, CPI, PMI)
```

### 3.3 技能推荐算法

```typescript
/**
 * 基于上下文的技能推荐算法
 *
 * 输入: ExecutionContext (用户请求, 意图, 市场状态, 历史偏好)
 * 输出: 按优先级排序的技能推荐列表
 *
 * 推荐逻辑:
 * 1. 匹配适用的思维阶段 (S1/C1/F1 对应 research, ...)
 * 2. 匹配适用的用户意图
 * 3. 考虑市场条件适配度
 * 4. 考虑历史调用成功率
 * 5. 考虑成本预算
 * 6. 考虑并行能力 (无依赖的技能可并行)
 */

function recommendSkills(context: ExecutionContext): SkillRecommendation[] {
  // 1. 基础筛选
  let candidates = registry.query({
    stage: getStageForIntent(context.intent),
    intent: context.intent,
  });

  // 2. 市场条件过滤
  if (context.marketCondition) {
    candidates = candidates.filter(s =>
      !s.metadata.marketConditions ||
      s.metadata.marketConditions.includes(context.marketCondition)
    );
  }

  // 3. 成本过滤
  if (context.budgetTokens) {
    candidates = candidates.filter(s =>
      s.metadata.estimatedTokens <= context.budgetTokens
    );
  }

  // 4. 评分排序
  return candidates.map(skill => ({
    skill,
    score: calculateRecommendationScore(skill, context),
    reason: getRecommendationReason(skill, context),
  })).sort((a, b) => b.score - a.score);
}

function calculateRecommendationScore(
  skill: SkillCapability,
  context: ExecutionContext
): number {
  let score = 0;

  // 历史准确率权重 (30%)
  if (skill.metadata.historicalAccuracy) {
    score += skill.metadata.historicalAccuracy * 0.3;
  }

  // 成本效率权重 (20%)
  const costEfficiency = 1 - (skill.metadata.estimatedTokens / (context.budgetTokens || 10000));
  score += Math.max(0, costEfficiency) * 0.2;

  // 链权重匹配 (30%)
  const chainWeight = context.chainWeights?.[`${skill.metadata.chain.toLowerCase()}_chain`] || 0.33;
  score += chainWeight * 0.3;

  // 市场条件匹配 (20%)
  if (skill.metadata.marketConditions?.includes(context.marketCondition || '')) {
    score += 0.2;
  }

  return score;
}
```

---

## 四、AI 推理引擎 (Execution Planner)

### 4.1 核心执行循环

```
┌─────────────────────────────────────────────────────────────────────────┐
│                    AI 推理引擎 - 核心执行循环                            │
│                                                                         │
│  输入: 用户请求 + 上下文 + 能力表                                        │
│  输出: 执行结果 + 图架构数据                                             │
│                                                                         │
│  ═══════════════════════════════════════════════════════════════════════ │
│  STEP 1: 初始化规划                                                     │
│  ═══════════════════════════════════════════════════════════════════════ │
│                                                                         │
│    1.1 识别用户意图 → 确定使用哪条思维链 (S/C/F)                         │
│    1.2 查询技能注册表 → 获取适用的技能候选列表                           │
│    1.3 评估预算约束 → 修剪过高成本的技能                                 │
│    1.4 生成执行计划 → 确定步骤序列 + 交叉验证节点                         │
│                                                                         │
│  ═══════════════════════════════════════════════════════════════════════ │
│  STEP 2: 执行思维步骤 (对每个步骤 S1..S5 / C1..C5 / F1..F5)           │
│  ═══════════════════════════════════════════════════════════════════════ │
│                                                                         │
│    FOR each step IN plan.steps:                                         │
│                                                                         │
│      2.1 动态技能选择                                                   │
│          • 根据上下文选择最适合的技能组合                                 │
│          • 并行执行无依赖的技能                                          │
│          • 串行执行有依赖的技能                                          │
│                                                                         │
│      2.2 技能执行                                                       │
│          • 调用 SkillCapability.execute()                                │
│          • 收集所有技能的结果                                            │
│          • 处理超时/失败/降级                                            │
│                                                                         │
│      2.3 置信度评估 (必须做!)                                           │
│          • 综合所有技能输出的置信度                                       │
│          • 评估数据完整性、逻辑一致性、跨源印证                            │
│          • 识别信息缺口和逻辑冲突                                         │
│                                                                         │
│      2.4 分支决策                                                       │
│          ┌──────────────────────────────────────────┐                  │
│          │ IF confidence >= 80:                      │                  │
│          │   decision = 'proceed'                    │                  │
│          │   进入下一步                               │                  │
│          │                                          │                  │
│          │ ELSE IF confidence >= 50:                 │                  │
│          │   decision = 'iterate'                    │                  │
│          │   补充调用额外技能                        │                  │
│          │   重新评估置信度                          │                  │
│          │                                          │                  │
│          │ ELSE IF confidence < 50:                  │                  │
│          │   decision = 'warn'                       │                  │
│          │   标记为低置信度节点                      │                  │
│          │   询问用户是否接受 / 补充信息              │                  │
│          └──────────────────────────────────────────┘                  │
│                                                                         │
│      2.5 写入图架构                                                     │
│          • 创建 Architecture 层节点                                       │
│          • 记录: 调用的技能、产出、置信度、推理过程                       │
│          • 如果有迭代，记录所有迭代过程                                   │
│                                                                         │
│      2.6 到达交叉验证节点?                                               │
│          • 如果 stepId 在 CV 节点之后                                    │
│          • 执行交叉验证: 收集各链信号 → 加权投票 → 检测冲突               │
│          • 根据投票结果决定: proceed / deep_dive / pause                  │
│                                                                         │
│    END FOR                                                              │
│                                                                         │
│  ═══════════════════════════════════════════════════════════════════════ │
│  STEP 3: 最终融合                                                       │
│  ═══════════════════════════════════════════════════════════════════════ │
│                                                                         │
│    3.1 汇总所有步骤的执行结果                                            │
│    3.2 生成最终交易方案 / 分析报告                                       │
│    3.3 生成推理引擎增强结果                                              │
│       • 决策路径回溯                                                     │
│       • 链间一致性评估                                                   │
│       • 下一步建议                                                      │
│    3.4 更新 Blueprint 层 (如果生成了新的模板)                           │
│    3.5 更新 Chronicle 层 (记录时间线和关键决策)                         │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

### 4.2 置信度评估算法

```typescript
/**
 * 置信度评估算法
 * 位置: 6-图结构上下文压缩/planner/confidence-evaluator.ts
 */

interface ConfidenceEvaluation {
  overallScore: number;                 // 0-100 综合置信度
  dimensions: {
    dataCompleteness: number;          // 数据完整性 (0-100)
    logicalConsistency: number;         // 逻辑自洽性 (0-100)
    crossSourceValidation: number;      // 跨源印证 (0-100)
    historicalAccuracy: number;         // 历史准确率 (0-100)
  };
  gaps: Gap[];                         // 识别的缺口
  recommendation: 'ACCEPT' | 'ITERATE' | 'WARN' | 'REJECT';
}

function evaluateConfidence(
  skillResults: SkillResult[],
  stepDefinition: ThinkingStepDefinition,
  context: ExecutionContext
): ConfidenceEvaluation {
  // 1. 收集所有技能输出的置信度
  const skillConfidences = skillResults.map(r => r.confidence);

  // 2. 计算数据完整性
  const dataCompleteness = calculateDataCompleteness(skillResults, stepDefinition);

  // 3. 计算逻辑一致性
  const logicalConsistency = calculateLogicalConsistency(skillResults);

  // 4. 计算跨源印证 (如果调用了多个技能)
  const crossSourceValidation = calculateCrossValidation(skillResults);

  // 5. 计算历史准确率
  const historicalAccuracy = calculateHistoricalAccuracy(skillResults);

  // 6. 综合计算
  const weights = { data: 0.2, logic: 0.25, cross: 0.25, history: 0.3 };
  const overallScore = Math.round(
    dataCompleteness * weights.data +
    logicalConsistency * weights.logic +
    crossSourceValidation * weights.cross +
    historicalAccuracy * weights.history
  );

  // 7. 识别缺口
  const gaps = identifyGaps(skillResults, stepDefinition);

  // 8. 决策建议
  const { recommendation, reason } = makeRecommendation(
    overallScore,
    gaps,
    stepDefinition.confidenceThresholds
  );

  return {
    overallScore,
    dimensions: {
      dataCompleteness,
      logicalConsistency,
      crossSourceValidation,
      historicalAccuracy,
    },
    gaps,
    recommendation,
  };
}

function calculateCrossValidation(results: SkillResult[]): number {
  if (results.length < 2) return 100; // 单技能直接满分

  // 检查方向一致性
  const directions = results.map(r => r.outputs.direction || 'neutral');
  const uniqueDirections = new Set(directions);

  if (uniqueDirections.size === 1) return 100; // 完全一致
  if (uniqueDirections.size === 2) return 60;  // 部分分歧

  // 计算置信度方差 (方差越小越一致)
  const confidences = results.map(r => r.confidence);
  const avg = confidences.reduce((a, b) => a + b, 0) / confidences.length;
  const variance = confidences.reduce((sum, c) => sum + Math.pow(c - avg, 2), 0) / confidences.length;

  return Math.max(0, 100 - Math.sqrt(variance));
}

function identifyGaps(
  results: SkillResult[],
  stepDef: ThinkingStepDefinition
): Gap[] {
  const gaps: Gap[] = [];

  // 检查缺失数据
  const requiredOutputs = stepDef.expectedOutputs;
  const providedOutputs = new Set(results.flatMap(r => Object.keys(r.outputs)));
  requiredOutputs.forEach(out => {
    if (!providedOutputs.has(out)) {
      gaps.push({
        type: 'missing-data',
        description: `缺少输出: ${out}`,
        suggestedAction: '调用补充技能获取该数据',
      });
    }
  });

  // 检查低置信度技能
  results.forEach(r => {
    if (r.confidence < 50) {
      gaps.push({
        type: 'low-confidence',
        description: `技能 ${r.capabilityId} 置信度过低: ${r.confidence}`,
        suggestedAction: r.suggestions?.[0] || '考虑迭代或降级',
      });
    }
  });

  // 检查逻辑冲突
  const directions = results.map(r => r.outputs.direction);
  if (new Set(directions).size > 1) {
    gaps.push({
      type: 'logical-conflict',
      description: `技能间方向冲突: ${directions.join(' vs ')}`,
      suggestedAction: '进行交叉验证或调用冲突检测技能',
      suggestedSkillId: 'dual-agent-conflict-gate',
    });
  }

  return gaps;
}
```

---

## 五、思维链定义

### 5.1 S链 (通用交易思维)

```typescript
/**
 * S链思维步骤定义
 * 位置: 6-图结构上下文压缩/chains/s-chain/steps.ts
 */

export const S_CHAIN_STEPS: ThinkingStepDefinition[] = [
  {
    id: 'S1',
    stage: 'research',
    chain: 'S',
    label: 'S1_调研',
    icon: '🔍',
    description: '市场数据、行情、技术指标、新闻收集',
    coreQuestion: '当前市场发生了什么？趋势是什么？有哪些关键事件？数据充分吗？',
    expectedOutputs: ['市场趋势', '关键事件列表', '数据质量评估', '信息完整性评分'],
    confidenceThresholds: { high: 80, medium: 50, low: 30 },
    recommendedSkillCategories: ['intelligence', 'execution'],
  },
  {
    id: 'S2',
    stage: 'analysis',
    chain: 'S',
    label: 'S2_分析',
    icon: '🧠',
    description: '多维度分析（技术面、基本面、情绪面）',
    coreQuestion: '这意味着什么？信号强度如何？市场状态是什么？有哪些风险？信息缺口？',
    expectedOutputs: ['分析结论', '信号强度评分', '市场状态', '风险评级', '信息缺口列表'],
    confidenceThresholds: { high: 80, medium: 50, low: 30 },
    recommendedSkillCategories: ['execution', 'intelligence'],
    requiredSkills: ['dream-regime-detector'], // 状态识别是 S2 的核心
  },
  {
    id: 'S3',
    stage: 'design',
    chain: 'S',
    label: 'S3_设计',
    icon: '🎯',
    description: '制定具体策略（入场点、止损、止盈、仓位）',
    coreQuestion: '应该怎么做？方向？入场点？止损？止盈？仓位？策略类型？',
    expectedOutputs: ['交易计划', '入场点位', '止损点位', '止盈策略', '仓位方案', '策略类型'],
    confidenceThresholds: { high: 75, medium: 50, low: 25 },
    recommendedSkillCategories: ['execution', 'research'],
  },
  {
    id: 'S4',
    stage: 'validate',
    chain: 'S',
    label: 'S4_验证',
    icon: '✅',
    description: '回测验证、风险评估、模拟推演',
    coreQuestion: '这个方案经得起检验吗？历史回测如何？模拟推演暴露了什么风险？',
    expectedOutputs: ['验证报告', '回测结果', '风险评估', '置信度评分', '通过/否决标记'],
    confidenceThresholds: { high: 80, medium: 55, low: 35 },
    recommendedSkillCategories: ['governance', 'research'],
    requiredSkills: ['dream-pretrade-gatekeeper'], // 门禁是 S4 的核心
  },
  {
    id: 'S5',
    stage: 'execute',
    chain: 'S',
    label: 'S5_执行',
    icon: '⚡',
    description: '生成执行计划、跟踪调整',
    coreQuestion: '怎么落地？下单指令？监控什么？离场条件？',
    expectedOutputs: ['执行指令', '监控指标', '离场条件', '应急预案'],
    confidenceThresholds: { high: 70, medium: 45, low: 25 },
    recommendedSkillCategories: ['execution'],
  },
];
```

### 5.2 C链 (量化技术思维)

```typescript
/**
 * C链思维步骤定义
 * 位置: 6-图结构上下文压缩/chains/c-chain/steps.ts
 */

export const C_CHAIN_STEPS: ThinkingStepDefinition[] = [
  {
    id: 'C1',
    stage: 'research',
    chain: 'C',
    label: 'C1_扫描',
    icon: '📊',
    description: '多周期技术指标扫描',
    coreQuestion: '各周期的技术指标显示什么信号？RSI/MACD/均线/波动率状态？',
    expectedOutputs: ['多周期信号矩阵', '关键指标读数', '信号强度排序'],
    confidenceThresholds: { high: 85, medium: 60, low: 40 },
    recommendedSkillCategories: ['classic-indicators'],
  },
  {
    id: 'C2',
    stage: 'analysis',
    chain: 'C',
    label: 'C2_识别',
    icon: '🔄',
    description: '市场状态自动识别',
    coreQuestion: '当前是趋势市场还是震荡市场？应该用什么策略家族？',
    expectedOutputs: ['市场状态', '推荐策略家族', '状态置信度'],
    confidenceThresholds: { high: 80, medium: 55, low: 35 },
    recommendedSkillCategories: ['classic-regime'],
    requiredSkills: ['RegimeHybridStrategy'], // 状态混合策略是 C2 的核心
  },
  {
    id: 'C3',
    stage: 'design',
    chain: 'C',
    label: 'C3_匹配',
    icon: '📋',
    description: '从策略库中匹配最优策略',
    coreQuestion: '有哪些可用策略？哪个最适合当前市场状态？',
    expectedOutputs: ['候选策略列表', '策略评分', '推荐策略', '策略元数据'],
    confidenceThresholds: { high: 80, medium: 55, low: 35 },
    recommendedSkillCategories: ['classic-strategy'],
  },
  {
    id: 'C4',
    stage: 'validate',
    chain: 'C',
    label: 'C4_回测',
    icon: '📈',
    description: '历史数据回测验证',
    coreQuestion: '策略在历史上表现如何？胜率/夏普/最大回撤？',
    expectedOutputs: ['回测报告', '绩效指标', 'Gate评估结果', '通过/否决标记'],
    confidenceThresholds: { high: 85, medium: 60, low: 40 },
    recommendedSkillCategories: ['classic-backtest'],
  },
  {
    id: 'C5',
    stage: 'execute',
    chain: 'C',
    label: 'C5_参数',
    icon: '⚙️',
    description: '输出策略参数和信号阈值',
    coreQuestion: '具体的策略参数配置是什么？可以执行吗？',
    expectedOutputs: ['策略参数配置', '信号阈值', '执行就绪状态'],
    confidenceThresholds: { high: 80, medium: 55, low: 35 },
    recommendedSkillCategories: ['classic-execution'],
  },
];
```

### 5.3 F链 (基本面思维)

```typescript
/**
 * F链思维步骤定义
 * 位置: 6-图结构上下文压缩/chains/f-chain/steps.ts
 */

export const F_CHAIN_STEPS: ThinkingStepDefinition[] = [
  {
    id: 'F1',
    stage: 'research',
    chain: 'F',
    label: 'F1_新闻',
    icon: '📰',
    description: '新闻事件扫描与分类',
    coreQuestion: '近期有哪些重要新闻和事件？它们对市场有什么影响？',
    expectedOutputs: ['新闻列表', '事件分类', '影响评估', '情感倾向'],
    confidenceThresholds: { high: 75, medium: 50, low: 30 },
    recommendedSkillCategories: ['fundamental-news'],
  },
  {
    id: 'F2',
    stage: 'analysis',
    chain: 'F',
    label: 'F2_资金',
    icon: '💰',
    description: '链上资金流向分析',
    coreQuestion: '聪明钱在流入还是流出？大额转账有什么信号？',
    expectedOutputs: ['资金流向', '异常标记', '交易所余额变化'],
    confidenceThresholds: { high: 75, medium: 50, low: 30 },
    recommendedSkillCategories: ['fundamental-flow'],
  },
  {
    id: 'F3',
    stage: 'analysis',
    chain: 'F',
    label: 'F3_情绪',
    icon: '😀',
    description: '市场情绪聚合分析',
    coreQuestion: '市场情绪是乐观还是悲观？有没有极端信号？',
    expectedOutputs: ['情绪指数', '热度评估', '极端信号'],
    confidenceThresholds: { high: 70, medium: 45, low: 25 },
    recommendedSkillCategories: ['fundamental-sentiment'],
  },
  {
    id: 'F4',
    stage: 'analysis',
    chain: 'F',
    label: 'F4_链上',
    icon: '⛓️',
    description: '链上指标综合评估',
    coreQuestion: 'MVRV/NUPL 等链上指标显示市场处于什么周期位置？',
    expectedOutputs: ['链上指标面板', '周期位置评估', '顶部/底部信号'],
    confidenceThresholds: { high: 80, medium: 55, low: 35 },
    recommendedSkillCategories: ['fundamental-onchain'],
  },
  {
    id: 'F5',
    stage: 'design',
    chain: 'F',
    label: 'F5_宏观',
    icon: '🌍',
    description: '宏观经济环境扫描',
    coreQuestion: '利率/CPI/就业等宏观因素如何？它们如何影响交易方向？',
    expectedOutputs: ['宏观指标', '环境影响评分', '风险提示'],
    confidenceThresholds: { high: 75, medium: 50, low: 30 },
    recommendedSkillCategories: ['fundamental-macro'],
  },
];
```

---

## 六、交叉验证机制

### 6.1 交叉验证节点定义

```typescript
/**
 * 交叉验证节点配置
 * 位置: 6-图结构上下文压缩/planner/cross-validation-config.ts
 */

export const CROSS_VALIDATION_NODES: PlannedCrossValidation[] = [
  {
    nodeId: 'CV1',
    afterStep: 'S1',                    // S1/C1/F1 完成后
    participatingChains: ['S', 'C', 'F'],
    weights: { s_chain: 0.35, c_chain: 0.45, f_chain: 0.20 },
    triggerCondition: { type: 'always' },
    fallback: { type: 'majority_vote' },
  },
  {
    nodeId: 'CV2',
    afterStep: 'S2',                    // S2/C2/F2-F4 完成后
    participatingChains: ['S', 'C', 'F'],
    weights: { s_chain: 0.35, c_chain: 0.40, f_chain: 0.25 },
    triggerCondition: { type: 'always' },
    fallback: { type: 'weighted_average' },
  },
  {
    nodeId: 'CV3',
    afterStep: 'S3',                    // S3/C3/F5 完成后
    participatingChains: ['S', 'C'],
    weights: { s_chain: 0.40, c_chain: 0.60 },
    triggerCondition: { type: 'on_conflict' },
    fallback: { type: 'highest_confidence', requireUserConfirmation: true },
  },
  {
    nodeId: 'CV4',
    afterStep: 'S4',                    // S4/C4 完成后
    participatingChains: ['S', 'C'],
    weights: { s_chain: 0.30, c_chain: 0.70 },
    triggerCondition: { type: 'always' },
    fallback: { type: 'majority_vote' },
  },
  {
    nodeId: 'CV5',
    afterStep: 'S5',                    // 最终决策前
    participatingChains: ['S', 'C'],
    weights: { s_chain: 0.45, c_chain: 0.55 },
    triggerCondition: { type: 'on_low_confidence', threshold: 60 },
    fallback: { type: 'weighted_average', requireUserConfirmation: true },
  },
];
```

### 6.2 投票计算器

```typescript
/**
 * 加权投票计算器
 * 位置: 6-图结构上下文压缩/planner/voting-calculator.ts
 */

const DIRECTION_SCORES = { long: 1, short: -1, neutral: 0, wait: 0 };

function calculateWeightedVote(
  signals: CrossValidationNode['signals'],
  weights: ChainWeights,
  directionMapping = DIRECTION_SCORES
): CrossValidationNode['consensus'] {
  // 过滤掉 'wait' 信号（不参与投票）
  const activeSignals = signals.filter(s => s.direction !== 'wait');

  if (activeSignals.length === 0) {
    return {
      direction: 'wait',
      overallConfidence: 0,
      agreementLevel: 'conflict',
      votes: [],
    };
  }

  // 计算加权投票
  let weightedSum = 0;
  let totalWeight = 0;

  const votes = activeSignals.map(signal => {
    const weight = weights[`${signal.chain}_chain` as keyof ChainWeights];
    const directionScore = directionMapping[signal.direction];
    const contribution = weight * directionScore * (signal.confidence / 100);

    weightedSum += contribution;
    totalWeight += weight * (signal.confidence / 100);

    return {
      chain: signal.chain,
      weight,
      rawConfidence: signal.confidence,
      weightedContribution: contribution,
    };
  });

  // 计算加权置信度
  const avgConfidence = activeSignals.reduce((sum, s) => sum + s.confidence, 0) / activeSignals.length;

  // 确定方向
  let direction: 'long' | 'short' | 'neutral';
  if (weightedSum > 0.3) direction = 'long';
  else if (weightedSum < -0.3) direction = 'short';
  else direction = 'neutral';

  // 计算一致性等级
  const confidences = activeSignals.map(s => s.confidence);
  const avg = confidences.reduce((a, b) => a + b, 0) / confidences.length;
  const variance = confidences.reduce((sum, c) => sum + Math.pow(c - avg, 2), 0) / confidences.length;
  const stdDev = Math.sqrt(variance);

  let agreementLevel: 'strong' | 'moderate' | 'weak' | 'conflict';
  if (stdDev < 10 && avg > 75) agreementLevel = 'strong';
  else if (stdDev < 20 && avg > 60) agreementLevel = 'moderate';
  else if (stdDev < 30) agreementLevel = 'weak';
  else agreementLevel = 'conflict';

  return {
    direction,
    overallConfidence: Math.round(avgConfidence * (1 - stdDev / 100)),
    agreementLevel,
    votes,
  };
}
```

---

## 七、图架构压缩模块扩展

### 7.1 Architecture 层扩展

```typescript
/**
 * 图架构压缩模块扩展 - 支持三链融合
 * 位置: 6-图结构上下文压缩/enhanced-compressor.ts
 */

/** 扩展的 Architecture 节点类型 */
interface ExtendedArchitectureNode extends SerializedNode {
  // 新增字段
  chain: 'S' | 'C' | 'F';              // 所属思维链
  stage: ThinkStage;                   // 思维阶段

  // 技能调用信息
  skillsInvoked: Array<{
    skillId: string;
    skillName: string;
    invocationIndex: number;
  }>;

  // 置信度评估
  confidence: number;
  confidenceDimensions?: SkillResult['confidenceDimensions'];

  // 决策信息
  decision: 'proceed' | 'iterate' | 'skip' | 'warn';
  decisionReason: string;

  // 迭代信息 (如果有)
  iterations?: number;
  iterationLog?: Array<{
    iteration: number;
    addedSkills: string[];
    newConfidence: number;
    decision: string;
  }>;

  // 信息缺口 (如果有)
  gaps?: Gap[];

  // 跨链关联
  crossChainReferences?: Array<{
    chain: 'S' | 'C' | 'F';
    stepId: string;
    relationship: 'supports' | 'conflicts' | 'complements';
  }>;
}

/** 扩展的图数据 */
interface EnhancedGraphData extends GraphData {
  // 新增的三链维度
  sChainNodes: ExtendedArchitectureNode[];
  cChainNodes: ExtendedArchitectureNode[];
  fChainNodes: ExtendedArchitectureNode[];

  // 交叉验证节点
  crossValidationNodes: CrossValidationNode[];

  // 融合决策
  finalConsensus?: {
    direction: 'long' | 'short' | 'neutral' | 'wait';
    confidence: number;
    participatingChains: ('S' | 'C' | 'F')[];
    keyDecisionPoints: string[];       // 最关键的决策节点
  };
}

/** 扩展的压缩结果 */
interface EnhancedCompressionResult extends CompressResult {
  // 新增字段
  enhancedGraphData: EnhancedGraphData;
  orchestrationInsights: {
    totalStepsExecuted: number;
    totalSkillsInvoked: number;
    totalIterations: number;
    overallConfidence: number;
    chainContributions: { s: number; c: number; f: number };
    executionPath: string[];            // 执行路径
    criticalDecisions: string[];        // 关键决策
    recommendations: string[];          // 后续建议
  };
}
```

### 7.2 推理引擎增强

```typescript
/**
 * 增强的推理引擎结果
 * 位置: 6-图结构上下文压缩/inference/enhanced-inference.ts
 */

interface EnhancedInferenceResult extends InferenceResult {
  // 思维步骤摘要
  stepSummaries: Array<{
    stepId: string;
    chain: 'S' | 'C' | 'F';
    stage: ThinkStage;
    confidence: number;
    keyFinding: string;
    skillsCalled: string[];
    iterations: number;
  }>;

  // 跨链一致性
  crossChainConsistency: {
    overallAgreement: 'strong' | 'moderate' | 'weak' | 'conflict';
    chainScores: { s: number; c: number; f: number };
    conflicts: Array<{
      chains: ('S' | 'C' | 'F')[];
      description: string;
      resolution?: string;
    }>;
  };

  // 决策路径回溯
  decisionPath: {
    nodes: Array<{
      stepId: string;
      chain: 'S' | 'C' | 'F';
      contribution: number;             // 对最终结论的贡献权重
      isCritical: boolean;              // 是否是关键节点
      reasoning: string;
    }>;
    weakestLink?: string;
    strongestLink?: string;
  };

  // 下一步建议
  nextSteps: Array<{
    action: 'EXECUTE' | 'MONITOR' | 'WAIT_FOR_SIGNAL' | 'REVISE_PLAN' | 'ASK_USER';
    reasoning: string;
    triggerConditions?: string[];
    estimatedConfidence?: number;
  }>;

  // 可视化数据 (用于前端渲染)
  visualizationData: {
    timeline: TimelineItem[];
    chainComparison: {
      s: { nodes: number; avgConfidence: number };
      c: { nodes: number; avgConfidence: number };
      f: { nodes: number; avgConfidence: number };
    };
    confidenceTrend: number[];         // 各步骤置信度变化
  };
}
```

---

## 八、API 设计

### 8.1 统一能力调用 API

```
端点: POST /api/orchestrate

请求:
{
  "userRequest": "BTC 下周应该怎么操作？",
  "intent": "deep_analysis",
  "context": {
    "sessionId": "xxx",
    "symbol": "BTC",
    "tradingMode": "hybrid",
    "userRole": "PRO",
    "chainWeights": {
      "s_chain": 0.35,
      "c_chain": 0.45,
      "f_chain": 0.20
    },
    "budgetTokens": 5000,
    "maxLatencyMs": 120000
  }
}

响应:
{
  "ok": true,
  "plan": {
    "planId": "plan_xxx",
    "steps": [...],
    "estimatedTokens": 4500,
    "estimatedLatencyMs": 95000
  },
  "results": {
    "steps": [
      {
        "stepId": "S1",
        "status": "completed",
        "confidence": 85,
        "skillsCalled": [...],
        "answer": "当前 BTC 处于..."
      },
      ...
    ],
    "crossValidationNodes": [...],
    "finalConsensus": {
      "direction": "long",
      "confidence": 78,
      "reasoning": "三链加权投票..."
    }
  },
  "orchestrationInsights": {...},
  "inferenceResult": {...},
  "compressedGraph": {...}
}
```

### 8.2 技能查询 API

```
端点: GET /api/skills/registry

查询参数:
  - chain: A|C|F
  - category: execution|intelligence|governance|research|classic-indicators|...
  - stage: research|analysis|design|validate|execute
  - intent: market_query|deep_analysis|execute_trade|...
  - tag: trend|oscillation|volatility|...

响应:
{
  "ok": true,
  "skills": [
    {
      "id": "dream-regime-detector",
      "name": "市场状态识别",
      "description": "自动识别趋势/震荡/混合状态",
      "chain": "A",
      "category": "execution",
      "estimatedTokens": 200,
      "estimatedLatencyMs": 5000,
      "applicableStages": ["research", "analysis"],
      "tags": ["regime", "trend", "oscillation"]
    },
    ...
  ],
  "total": 45
}
```

---

## 九、文件结构

```
6-图结构上下文压缩/
├── SPEC.md                              ← 本规范文档
├── IMPLEMENTATION.md                     ← 实施计划
│
├── planner/                              ← AI 推理引擎 (核心)
│   ├── skill-types.ts                   ← 技能能力接口
│   ├── step-types.ts                    ← 思维步骤接口
│   ├── planner-types.ts                 ← 规划器接口
│   ├── cross-validation-types.ts        ← 交叉验证接口
│   │
│   ├── skills-registry.ts               ← 技能注册表
│   ├── skills-registry-a.ts             ← A系列技能注册
│   ├── skills-registry-c.ts             ← C系列技能注册
│   ├── skills-registry-f.ts             ← F系列技能注册
│   │
│   ├── planner.ts                       ← 主规划器
│   ├── skill-selector.ts                ← 动态技能选择
│   ├── confidence-evaluator.ts           ← 置信度评估
│   ├── iteration-manager.ts              ← 迭代管理
│   ├── voting-calculator.ts             ← 投票计算器
│   │
│   └── index.ts                         ← 统一导出
│
├── chains/                              ← 思维链定义
│   ├── s-chain/
│   │   ├── steps.ts                     ← S1-S5 步骤定义
│   │   ├── step-wrappers.ts            ← 薄包装 (委托 planner)
│   │   └── index.ts
│   ├── c-chain/
│   │   ├── steps.ts                     ← C1-C5 步骤定义
│   │   ├── step-wrappers.ts            ← 薄包装
│   │   └── index.ts
│   └── f-chain/
│       ├── steps.ts                     ← F1-F5 步骤定义
│       ├── step-wrappers.ts            ← 薄包装
│       └── index.ts
│
├── enhanced-compressor.ts               ← 扩展的压缩模块
├── inference/
│   └── enhanced-inference.ts           ← 增强的推理引擎
│
├── api/                                 ← API 层
│   ├── orchestrate/route.ts             ← 统一编排 API
│   └── skills/registry/route.ts         ← 技能注册表 API
│
└── demo/
    ├── orchestrator-demo.ts             ← 演示脚本
    └── cross-validation-demo.ts         ← 交叉验证演示
```

---

## 十、设计原则

### 10.1 核心原则

| 原则 | 说明 |
|------|------|
| **思维链是骨架，不是实现** | S/C/F 链只定义思考的顺序，每步内部由 AI 动态决定 |
| **置信度必须评估** | 每个思维步骤完成后必须评估置信度，作为分支决策的依据 |
| **技能统一契约** | 所有技能必须实现 SkillCapability 接口，保证可替换性 |
| **降级通道必须存在** | 任何技能/链失败时，必须有降级方案，不能让系统崩溃 |
| **推理过程可追溯** | 图架构压缩模块记录完整的思考轨迹，供用户理解和复盘 |
| **渐进式扩展** | 从 P0 开始逐步实现，每步都有可工作的降级通道 |

### 10.2 不做的事

- 不在思维链步骤内部硬编码具体实现逻辑
- 不让 S/C/F 三链互斥，而是互补和交叉验证
- 不追求一步到位，而是渐进式迁移
- 不忽略成本和延迟，每步都要评估预算

---

## 附录 A: 技能 ID 速查表

```
A系列 (AI交易技能):
  dream-systematic-trading          系统交易协调器
  dream-screen1-first              第一屏·周线
  dream-screen2-second             第二屏·日线
  dream-screen3-third              第三屏·实时
  dream-strategy-parser            策略解析
  dream-signal-scoring-spec        信号评分
  dream-regime-detector            状态识别
  dream-risk-position-sizing       仓位风险
  dream-pretrade-gatekeeper        交易前门禁
  dream-tactical-executor          战术执行
  dream-tactical-validator         战术验证
  dream-exit-skill-v2              离场策略
  dream-intelligence-monitor        情报监测
  master-seminar                   大师研讨会
  dream-oneirology                 梦境分析
  ai-trading-compliance            合规检查
  dream-cost-control                成本控制
  dream-performance-review          绩效审查
  dream-operation-director         运营调度
  dual-agent-conflict-gate          冲突检测
  dream-strategy-research           策略研究
  dream-strategy-designer          策略设计
  dream-backtest                   回测引擎
  dream-bayesian-opt               贝叶斯优化
  dream-contradiction-theory       矛盾理论
  tavily                           外部搜索

C系列 (经典量化模块):
  ClassicIndicators_Scan           多周期指标扫描
  RegimeHybridStrategy              状态混合策略
  StrategyLibrary_Query            策略库查询
  ClassicBacktest                  经典回测
  StrategyApply                    策略应用
  HealthCheck                      系统健康检查
  PnlAudit                         盈亏审计

F系列 (基本面工具):
  FundamentalNews                   新闻事件
  FundFlowAnalysis                 资金流向
  MarketSentiment                  市场情绪
  OnchainMetrics                   链上指标
  MacroIndicators                  宏观指标
```
