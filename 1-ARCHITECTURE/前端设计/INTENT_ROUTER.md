# 意图识别与路由引擎 — 系统灵魂

> 版本: v2.1 | 日期: 2026-05-13 | 所属: Dream Universal Gateway
> **核心定位**: 本文档是整个通用AI入口的设计核心，所有其他文档围绕此文档展开
> **v2.1变更**: 新增策略类意图(strategy_custom/strategy_view/strategy_apply)

---

## 1. 设计哲学

### 1.1 一句话定义

**用户说什么，系统懂什么，路由到哪里。**

通用AI前端不是一个消息收发器，而是一个**意图理解+智能路由**系统。用户用自然语言表达需求，系统在后台识别意图、检索已有产物、决策处理路径，最终高效产出结果。

### 1.2 三个核心原则

| 原则 | 说明 | 对立面 |
|------|------|--------|
| **意图即路由** | 用户表达=意图识别=处理路径决策 | 用户需要手动选A1/A2/A3 |
| **产物优先** | 已有产物先检索复用，不重跑全链路 | 每次都从零开始完整链路 |
| **隐藏内部** | 用户看到的是"分析行情"，不是"A2第一性原理" | 暴露A0-A9技术术语 |

### 1.3 用户视角 vs 系统视角

```
用户说的是:                    系统做的是:
─────────────────────────────────────────────────────
"BTC现在怎么样"          →    检索最新A6情报产物 → 直接摘要返回
"帮我分析一下当前局势"    →    检索最新A1/A2产物 → 判断是否需要更新 → 增量分析或直接复用
"行情有变化吗"           →    对比最新产物与市场实时数据 → 只分析变化部分
"要不要开仓"             →    检索最新完整链路产物 → 判断是否需要重跑 → 给出建议
"帮我做一轮完整分析"      →    执行完整链路 A1→A7 → 产出全套分析
"设置止损"               →    触发风控模块 → 配置TP/SL
```

**关键差异**: 用户永远不需要知道"A1""A2"这些代号，他们用自然语言表达需求，系统在后台映射到对应的处理逻辑。

---

## 2. 意图分类体系

### 2.1 意图层级

```
┌─────────────────────────────────────────────────┐
│  Level 1: 领域识别 (Domain)                       │
│  用户在问什么领域的事？                             │
│  ┌─────────┬──────────┬──────────┬──────────┐    │
│  │ 加密市场  │ 传统金融  │ 系统配置  │ 通用对话  │    │
│  └────┬────┴────┬─────┴────┬─────┴────┬─────┘    │
│       │         │          │          │           │
│  Level 2: 任务类型 (Task Type)                    │
│  用户想做什么类型的事？                             │
│  ┌────┴────┐                                              │
│  │行情查询  │分析研判  │交易执行  │风控管理  │情报监控│    │
│  └────┬────┴────┬─────┴────┬─────┴────┬─────┘    │
│       │         │          │          │           │
│  Level 3: 处理策略 (Strategy)                     │
│  系统应该怎么处理？                                │
│  ┌────┴────┐                                              │
│  │产物直返  │增量更新  │部分链路  │完整链路  │直接执行│    │
│  └─────────────────────────────────────────┘    │
└─────────────────────────────────────────────────┘
```

### 2.2 Level 1: 领域识别

| 领域 | 触发关键词 | 判断依据 |
|------|-----------|----------|
| **加密市场** | BTC/ETH/SOL/行情/开仓/止损/费率/ETF/链上 | 包含加密品种名+金融术语 |
| **传统金融** | 股票/基金/A股/美股/汇率/CPI/GDP | 包含传统金融术语 |
| **系统配置** | API/密钥/配置/Telegram/微信/通知 | 配置类关键词 |
| **通用对话** | 其他所有 | 不匹配上述任何领域 |

### 2.3 Level 2: 任务类型

| 任务类型 | 用户表达示例 | 内部映射 |
|----------|-------------|----------|
| **行情查询** | "BTC现在多少""行情怎么样""费率多少" | 市场数据实时查询 |
| **分析研判** | "分析一下""怎么看""矛盾在哪""趋势呢" | 矛盾分析+趋势判断 |
| **交易执行** | "开多""做空""买入""开仓""下单" | 交易决策+执行 |
| **风控管理** | "设置止损""风险大吗""要不要止盈""离场" | 风控检查+离场评估 |
| **情报监控** | "有什么新消息""最新情报""宏观怎么样" | 情报检索+更新 |
| **完整分析** | "做一轮完整分析""从头分析""全面评估" | 全链路执行 |
| **策略生成** | "帮我做一个ETH策略""突破策略""套利策略" | 关键词→A系列调研→策略 | ← v2.1新增
| **策略查看** | "看看策略""推荐什么策略""当前策略" | 策略列表展示 | ← v2.1新增
| **策略应用** | "应用这个策略""启用策略""开始执行" | 策略应用+定时任务 | ← v2.1新增

### 2.4 Level 3: 处理策略（核心创新）

**这是本系统区别于普通ChatGPT的关键设计。**

```
用户意图
    │
    ▼
┌──────────────────────────────────────┐
│          产物检索评估器                │
│                                      │
│  1. 从产物中台检索相关最新产物         │
│  2. 评估产物时效性(多久前的？)         │
│  3. 评估产物匹配度(直接相关？)         │
│  4. 评估市场变化度(产物生成后市场变了？)│
│                                      │
│  输出: 产物充足度评分 0-100           │
└───────────┬──────────────────────────┘
            │
            │ 产物充足度评分
            │
    ┌───────┼────────────────┐
    │       │                │
   ≥80     40-79            <40
    │       │                │
    ▼       ▼                ▼
┌───────┐ ┌──────────┐  ┌──────────┐
│产物直返│ │增量更新   │  │链路执行   │
│       │ │          │  │          │
│检索最新│ │复用已有   │  │从对应阶段 │
│产物摘要│ │产物+补充  │  │开始执行   │
│返回用户│ │变化部分   │  │完整链路   │
└───────┘ └──────────┘  └──────────┘
```

#### 处理策略详解

| 策略 | 条件 | 行为 | 示例 |
|------|------|------|------|
| **产物直返** | 产物充足度≥80，且时效<4h | 直接检索最新产物摘要返回，不触发链路 | 用户问"BTC怎么样"，2h前刚跑过A6情报 → 直接返回A6摘要 |
| **增量更新** | 产物充足度40-79 | 复用已有产物，只补充变化部分 | 用户问"分析一下"，昨天跑过A2但今天CPI数据更新 → 复用A1旧产物+A2增量分析 |
| **部分链路** | 产物充足度<40，但部分阶段产物可用 | 从缺失阶段开始执行，跳过已有产物阶段 | 用户问"要不要开仓"，有A1/A2产物但无A3/A4 → 只跑A3→A4→A7 |
| **完整链路** | 无可用产物，或用户显式要求完整分析 | 从头执行完整链路 | 用户说"从头分析一遍" → 执行完整A1→A7 |

---

## 3. 意图识别引擎设计

### 3.1 架构

```
用户输入
    │
    ▼
┌──────────────────────────────────────┐
│  IntentRouter (意图路由器)             │
│                                      │
│  ┌────────────────────────────────┐  │
│  │ Step 1: 领域识别               │  │
│  │  · 关键词匹配 + LLM辅助判断    │  │
│  │  · 输出: domain                │  │
│  └──────────────┬─────────────────┘  │
│                 │                     │
│  ┌──────────────▼─────────────────┐  │
│  │ Step 2: 任务类型识别            │  │
│  │  · 意图分类模型                 │  │
│  │  · 输出: taskType               │  │
│  └──────────────┬─────────────────┘  │
│                 │                     │
│  ┌──────────────▼─────────────────┐  │
│  │ Step 3: 产物检索评估            │  │
│  │  · 查询产物中台最新产物         │  │
│  │  · 评估充足度                   │  │
│  │  · 输出: sufficiency_score      │  │
│  └──────────────┬─────────────────┘  │
│                 │                     │
│  ┌──────────────▼─────────────────┐  │
│  │ Step 4: 处理策略决策            │  │
│  │  · sufficiency → strategy       │  │
│  │  · 输出: strategy + phases      │  │
│  └──────────────┬─────────────────┘  │
│                 │                     │
│  ┌──────────────▼─────────────────┐  │
│  │ Step 5: 执行编排                │  │
│  │  · 按策略执行对应处理           │  │
│  │  · 输出: SSE事件流              │  │
│  └────────────────────────────────┘  │
│                                      │
└──────────────────────────────────────┘
```

### 3.2 IntentRouter 核心逻辑

```typescript
interface IntentRoute {
  domain: 'crypto' | 'tradfi' | 'config' | 'general';
  taskType: TaskType;
  strategy: ProcessingStrategy;
  phases: string[];           // 需要执行的内部阶段(隐藏)
  contextArtifacts: string[]; // 复用的产物ID
  freshDataNeeded: boolean;   // 是否需要实时数据
}

type TaskType = 
  | 'market_query'       // 行情查询
  | 'analysis'           // 分析研判
  | 'trade_execution'    // 交易执行
  | 'risk_management'    // 风控管理
  | 'intel_monitor'      // 情报监控
  | 'full_analysis'      // 完整分析
  | 'strategy_custom'    // 自定义策略生成 ← v2.1新增
  | 'strategy_view'      // 查看策略列表 ← v2.1新增
  | 'strategy_apply'     // 应用策略 ← v2.1新增
  | 'config_setup'       // 系统配置
  | 'general_chat';      // 通用对话

type ProcessingStrategy = 
  | 'direct_return'      // 产物直返
  | 'incremental'        // 增量更新
  | 'partial_chain'      // 部分链路
  | 'full_chain'         // 完整链路
  | 'realtime_query'     // 实时查询(不经过链路)
  | 'strategy_generate'  // 策略生成(A系列调研) ← v2.1新增
  | 'strategy_operation' // 策略操作(查看/应用) ← v2.1新增
  | 'config_operation'   // 配置操作
  | 'chat_only';         // 纯对话

async function routeIntent(
  userMessage: string, 
  sessionContext: SessionContext
): Promise<IntentRoute> {
  
  // Step 1: 领域识别
  const domain = identifyDomain(userMessage, sessionContext);
  
  // 非加密市场 → 走通用对话或配置通道
  if (domain === 'config') {
    return { domain, taskType: 'config_setup', strategy: 'config_operation', phases: [], contextArtifacts: [], freshDataNeeded: false };
  }
  if (domain === 'general') {
    return { domain, taskType: 'general_chat', strategy: 'chat_only', phases: [], contextArtifacts: [], freshDataNeeded: false };
  }
  
  // Step 2: 任务类型识别
  const taskType = classifyTaskType(userMessage, domain);
  
  // Step 3: 产物检索评估
  const artifactAssessment = await assessArtifacts(taskType, sessionContext);
  
  // Step 4: 处理策略决策
  const strategy = determineStrategy(taskType, artifactAssessment);
  
  // Step 5: 映射到内部阶段
  const phases = mapToPhases(taskType, strategy, artifactAssessment);
  
  return {
    domain,
    taskType,
    strategy,
    phases,
    contextArtifacts: artifactAssessment.reusableArtifactIds,
    freshDataNeeded: strategy !== 'direct_return',
  };
}
```

### 3.3 产物检索评估器

```typescript
interface ArtifactAssessment {
  // 各阶段最新产物
  latestArtifacts: {
    intel: ArtifactSummary | null;        // 情报类(A6产物)
    research: ArtifactSummary | null;     // 侦察类(A1产物)
    analysis: ArtifactSummary | null;     // 分析类(A2产物)
    simulation: ArtifactSummary | null;   // 推演类(A3产物)
    validation: ArtifactSummary | null;   // 验证类(A4产物)
    risk_check: ArtifactSummary | null;   // 风控类(A7/A9产物)
  };
  
  // 充足度评分
  sufficiencyScore: number;              // 0-100
  
  // 可复用的产物ID
  reusableArtifactIds: string[];
  
  // 需要刷新的阶段
  stalePhases: string[];
  
  // 市场变化度评估
  marketChangeLevel: 'none' | 'minor' | 'moderate' | 'major';
}

interface ArtifactSummary {
  id: string;
  title: string;
  createdAt: string;         // ISO时间
  ageInHours: number;        // 多少小时前
  relevance: number;         // 0-1 相关度
  keyInsights: string[];     // 关键洞察摘要
}

async function assessArtifacts(
  taskType: TaskType,
  context: SessionContext
): Promise<ArtifactAssessment> {
  
  // 1. 从产物中台检索相关产物
  const recentArtifacts = await getRecentArtifacts({
    limit: 30,
    minRelevance: 0.3,
    categories: getRelevantCategories(taskType),
  });
  
  // 2. 按内部阶段分组
  const grouped = groupByInternalPhase(recentArtifacts);
  
  // 3. 评估每个阶段的产物时效性
  const staleness = evaluateStaleness(grouped, taskType);
  
  // 4. 评估市场变化度（对比产物生成时的市场状态与当前）
  const marketChange = await assessMarketChange(grouped);
  
  // 5. 计算充足度评分
  const score = calculateSufficiency(taskType, staleness, marketChange);
  
  return {
    latestArtifacts: extractSummaries(grouped),
    sufficiencyScore: score,
    reusableArtifactIds: getReusableIds(grouped, staleness),
    stalePhases: getStalePhases(staleness),
    marketChangeLevel: marketChange.level,
  };
}
```

### 3.4 充足度评分规则

```typescript
function calculateSufficiency(
  taskType: TaskType,
  staleness: PhaseStaleness,
  marketChange: MarketChange
): number {
  // 基础分：根据任务类型需要的阶段覆盖度
  const requiredPhases = getRequiredPhases(taskType);
  const coveredPhases = requiredPhases.filter(p => staleness[p].hasArtifact);
  let score = (coveredPhases.length / requiredPhases.length) * 60;  // 最高60分
  
  // 时效性加/扣分
  for (const phase of coveredPhases) {
    const age = staleness[phase].ageInHours;
    if (age <= 2) score += 5;         // 2h内 +5
    else if (age <= 6) score += 2;    // 6h内 +2
    else if (age <= 24) score += 0;   // 24h内 +0
    else score -= 5;                   // >24h -5
  }
  
  // 市场变化度加/扣分
  switch (marketChange.level) {
    case 'none': score += 15; break;     // 无变化 +15
    case 'minor': score += 5; break;     // 微小变化 +5
    case 'moderate': score -= 5; break;  // 中等变化 -5
    case 'major': score -= 20; break;    // 重大变化 -20
  }
  
  return Math.max(0, Math.min(100, score));
}

// 任务类型 → 需要的内部阶段映射
function getRequiredPhases(taskType: TaskType): string[] {
  switch (taskType) {
    case 'market_query':
      return ['intel'];                                    // 只需情报
    case 'analysis':
      return ['intel', 'research', 'analysis'];            // 情报+侦察+分析
    case 'trade_execution':
      return ['research', 'analysis', 'simulation', 'validation', 'risk_check'];
    case 'risk_management':
      return ['risk_check'];                               // 只需风控
    case 'intel_monitor':
      return ['intel'];                                    // 只需情报
    case 'full_analysis':
      return ['intel', 'research', 'analysis', 'simulation', 'validation', 'risk_check'];
    default:
      return [];
  }
}
```

### 3.5 处理策略决策

```typescript
function determineStrategy(
  taskType: TaskType,
  assessment: ArtifactAssessment
): ProcessingStrategy {
  
  // 行情查询 → 总是尝试产物直返，不够就实时查询
  if (taskType === 'market_query') {
    return assessment.sufficiencyScore >= 60 ? 'direct_return' : 'realtime_query';
  }
  
  // 情报监控 → 产物直返或增量更新
  if (taskType === 'intel_monitor') {
    if (assessment.sufficiencyScore >= 80) return 'direct_return';
    return 'incremental';
  }
  
  // 分析研判 → 根据充足度分四档
  if (taskType === 'analysis') {
    if (assessment.sufficiencyScore >= 80) return 'direct_return';
    if (assessment.sufficiencyScore >= 40) return 'incremental';
    if (assessment.sufficiencyScore >= 20) return 'partial_chain';
    return 'full_chain';
  }
  
  // 交易执行 → 至少需要增量更新，产物不足则部分链路
  if (taskType === 'trade_execution') {
    if (assessment.sufficiencyScore >= 80) return 'incremental';  // 交易总是需要新鲜数据
    if (assessment.sufficiencyScore >= 40) return 'partial_chain';
    return 'full_chain';
  }
  
  // 风控管理 → 产物直返或增量
  if (taskType === 'risk_management') {
    return assessment.sufficiencyScore >= 60 ? 'incremental' : 'partial_chain';
  }
  
  // 完整分析 → 总是完整链路
  if (taskType === 'full_analysis') {
    return 'full_chain';
  }
  
  return 'chat_only';
}
```

### 3.6 内部阶段映射（隐藏映射）

**这是"用户语言→内部A系列"的翻译层，用户永远不会看到。**

```typescript
// 内部阶段 → 用户可见描述
const PHASE_USER_FACING: Record<string, UserFacingPhase> = {
  intel: {
    label: '情报更新',
    progressMessage: '正在获取最新市场情报...',
    completeMessage: '情报更新完成',
  },
  research: {
    label: '市场侦察',
    progressMessage: '正在侦察市场动态...',
    completeMessage: '市场侦察完成',
  },
  analysis: {
    label: '深度分析',
    progressMessage: '正在进行深度分析...',
    completeMessage: '分析完成',
  },
  simulation: {
    label: '情景推演',
    progressMessage: '正在推演可能情景...',
    completeMessage: '推演完成',
  },
  validation: {
    label: '方案验证',
    progressMessage: '正在验证方案可行性...',
    completeMessage: '验证完成',
  },
  risk_check: {
    label: '风控审查',
    progressMessage: '正在进行风控审查...',
    completeMessage: '审查完成',
  },
  execution: {
    label: '执行操作',
    progressMessage: '正在执行交易操作...',
    completeMessage: '操作完成',
  },
  exit_check: {
    label: '离场评估',
    progressMessage: '正在评估离场条件...',
    completeMessage: '评估完成',
  },
};

// 内部阶段 → A系列映射（系统内部使用，永远不暴露给用户）
const INTERNAL_PHASE_MAP: Record<string, string[]> = {
  intel: ['A6'],
  research: ['A1'],
  analysis: ['A2'],
  simulation: ['A3'],
  validation: ['A4'],
  risk_check: ['A7'],
  execution: ['A5'],
  exit_check: ['A9'],
};
```

---

## 4. 用户语言 → 意图映射表

### 4.1 加密市场意图映射

| 用户表达 | 领域 | 任务类型 | 典型处理策略 | 用户看到的过程 |
|----------|------|----------|-------------|---------------|
| "BTC现在怎么样" | 加密 | 行情查询 | 产物直返 | "当前BTC $80,630，RANGE_BOUND区间..." |
| "行情有变化吗" | 加密 | 行情查询 | 增量更新 | "对比2h前，费率从负转正..." |
| "帮我分析一下" | 加密 | 分析研判 | 增量更新/部分链路 | "正在获取最新数据...正在深度分析..." |
| "BTC矛盾在哪" | 加密 | 分析研判 | 增量更新 | "当前核心矛盾：宏观转鹰 vs 技术超卖..." |
| "要开仓吗" | 加密 | 交易执行 | 部分链路/完整链路 | "正在推演情景...正在验证方案...风控审查中..." |
| "做个空" | 加密 | 交易执行 | 部分链路 | "正在评估做空条件...风控审查中..." |
| "设置止损" | 加密 | 风控管理 | 增量更新 | "正在评估风控条件..." |
| "要止盈吗" | 加密 | 风控管理 | 增量更新 | "正在评估离场条件..." |
| "有什么新消息" | 加密 | 情报监控 | 产物直返 | "最新情报：CPI 3.8%落地..." |
| "宏观怎么样" | 加密 | 情报监控 | 产物直返 | "宏观面：Fed降息预期归零..." |
| "从头分析一遍" | 加密 | 完整分析 | 完整链路 | "正在侦察市场...正在深度分析...正在推演情景...正在验证方案...风控审查中..." |
| "全面评估一下ETH" | 加密 | 完整分析 | 完整链路 | (同上) |

### 4.2 配置类意图映射

| 用户表达 | 领域 | 任务类型 | 处理方式 |
|----------|------|----------|----------|
| "配置OKX API" | 配置 | 配置操作 | 打开API配置面板 |
| "连接Telegram" | 配置 | 配置操作 | 打开通信渠道配置 |
| "切换实盘" | 配置 | 配置操作 | 切换交易所环境 |
| "换个模型" | 配置 | 配置操作 | 打开LLM配置 |

### 4.3 传统金融意图映射（预留）

| 用户表达 | 领域 | 任务类型 | 处理方式 |
|----------|------|----------|----------|
| "A股怎么看" | 传统金融 | 分析研判 | 需接入传统金融数据源 |
| "美元指数" | 传统金融 | 行情查询 | 需接入外汇数据 |

---

## 5. SSE事件协议（用户可见版）

### 5.1 事件类型

**所有面向用户的事件，不包含任何A系列内部术语。**

```typescript
type UserFacingSSEEvent = 
  // 思考状态
  | { type: 'thinking'; message: string }              // "正在思考..."
  | { type: 'progress'; step: string; detail: string }  // "正在获取最新数据..."
  
  // 数据返回
  | { type: 'text_delta'; content: string }             // 流式文本
  | { type: 'data_card'; cardType: string; data: any }  // 数据卡片(行情/评分/信号)
  | { type: 'artifact_ref'; title: string; excerpt: string }  // "参考了近期分析报告"
  
  // 操作确认
  | { type: 'action_required'; action: string; details: any; riskLevel: string }
  
  // 完成
  | { type: 'done'; summary: string }
  
  // 错误
  | { type: 'error'; message: string; retryable: boolean };
```

### 5.2 用户看到的进度示例

```
用户: "帮我分析一下BTC"

系统显示:
┌──────────────────────────────────────┐
│ 🤖 AI助手                            │
│                                      │
│ ⠋ 正在获取最新市场数据...             │
│ ⠋ 正在检索近期分析报告...             │
│ ✓ 发现2份近期分析产物，将在此基础上更新│
│ ⠋ 正在补充最新数据...                 │
│ ⠋ 正在进行深度分析...                 │
│                                      │
│ 根据最新数据分析：                     │
│                                      │
│ **当前BTC核心矛盾**                   │
│                                      │
│ 1. 宏观转鹰 vs 技术超卖              │
│    CPI 3.8%超预期，Fed降息预期归零，  │
│    但BTC在$79.7K支撑位反复测试...     │
│                                      │
│ 📎 基于近期分析报告更新               │
│    · 深度分析报告 (3h前)              │
│    · 情报快报 (1h前)                  │
│                                      │
│ 📊 关键指标变化                       │
│    · 费率: -0.01% → +0.003% (翻转)   │
│    · FGI: 45 → 42 (恐惧加深)         │
│    · Regime: RANGE_BOUND (维持)       │
└──────────────────────────────────────┘
```

**关键设计**: 用户看到的是"正在获取数据""正在分析"，永远不是"正在执行A1""A2分析完成"。

---

## 6. 对话引擎整体架构

### 6.1 /api/chat 处理流程

```
POST /api/chat
    │
    ▼
┌──────────────────────────────────────────┐
│  1. 接收用户消息 + 会话上下文              │
│                                          │
│  2. IntentRouter.routeIntent()            │
│     → domain, taskType, strategy, phases  │
│                                          │
│  3. 根据 strategy 执行:                   │
│     ┌───────────────────────────────┐     │
│     │ direct_return:               │     │
│     │   检索产物 → 构建摘要 → 返回  │     │
│     ├───────────────────────────────┤     │
│     │ incremental:                 │     │
│     │   加载已有产物 + 补充数据     │     │
│     │   → 增量分析 → 返回           │     │
│     ├───────────────────────────────┤     │
│     │ partial_chain:               │     │
│     │   加载可复用产物              │     │
│     │   → 执行缺失阶段 → 返回      │     │
│     ├───────────────────────────────┤     │
│     │ full_chain:                  │     │
│     │   从头执行完整链路 → 返回     │     │
│     ├───────────────────────────────┤     │
│     │ realtime_query:              │     │
│     │   直接查询API → 格式化 → 返回│     │
│     ├───────────────────────────────┤     │
│     │ config_operation:            │     │
│     │   路由到配置处理器            │     │
│     ├───────────────────────────────┤     │
│     │ chat_only:                   │     │
│     │   纯LLM对话 → 返回           │     │
│     └───────────────────────────────┘     │
│                                          │
│  4. 全程SSE流式输出                       │
│     · thinking / progress 事件            │
│     · text_delta 流式文本                 │
│     · data_card / artifact_ref 引用       │
│     · action_required 操作确认            │
│     · done 完成                           │
└──────────────────────────────────────────┘
```

### 6.2 System Prompt 设计

```
你是一个专业的金融分析AI助手。

## 核心行为规则
1. **产物优先**: 回答问题前，先检查是否已有相关分析产物可以参考
2. **增量优先**: 如果近期产物可用，优先复用并补充最新变化，不重头分析
3. **术语屏蔽**: 不使用A0/A1/A2等内部代号，用用户能理解的语言描述
4. **结论先行**: 先给结论，再展开分析过程
5. **数据驱动**: 所有观点必须有数据支撑，标注数据来源和时间

## 当前上下文
- 品种: {symbol}
- 价格: {price}
- 市场状态: {regime}
- 持仓: {position}
- 最新产物: {recent_artifacts_summary}

## 可用产物参考
{injected_artifact_context}

## 安全规则
- 交易操作必须经过风控审查
- 实盘操作必须用户二次确认
- 不提供保证性收益承诺
```

### 6.3 产物注入策略

```typescript
async function injectArtifactContext(
  route: IntentRoute,
  assessment: ArtifactAssessment
): Promise<string> {
  
  if (route.strategy === 'direct_return') {
    // 产物直返：注入完整产物内容
    const artifacts = await loadFullArtifacts(assessment.reusableArtifactIds);
    return formatArtifactContext(artifacts, 'full');
  }
  
  if (route.strategy === 'incremental') {
    // 增量更新：注入已有产物摘要 + 变化提示
    const artifacts = await loadArtifactSummaries(assessment.reusableArtifactIds);
    const changes = await getMarketChanges(assessment);
    return formatArtifactContext(artifacts, 'summary') + '\n\n## 市场变化\n' + changes;
  }
  
  if (route.strategy === 'partial_chain') {
    // 部分链路：注入可复用产物作为前置上下文
    const artifacts = await loadArtifactSummaries(assessment.reusableArtifactIds);
    return formatArtifactContext(artifacts, 'context');
  }
  
  // 完整链路或纯对话：只注入市场概况
  return await getMarketOverview();
}
```

---

## 7. 增量更新引擎

### 7.1 设计目标

当用户问"分析一下"，系统发现有2h前的A2分析产物，不应该重跑整个A1→A2链路，而是：

1. 复用A1侦察产物中的结构性信息（Regime、支撑阻力、ETF持仓等变化缓慢的信息）
2. 只更新实时变化的数据（价格、费率、FGI等高频指标）
3. 在旧A2分析基础上，补充最新变化带来的影响

### 7.2 增量分析流程

```typescript
async function incrementalAnalysis(
  existingArtifacts: ArtifactSummary[],
  taskType: TaskType,
  onEvent: (event: UserFacingSSEEvent) => void
): Promise<void> {
  
  // 1. 识别哪些信息需要更新
  onEvent({ type: 'progress', step: '检索', detail: '正在检索近期分析报告...' });
  const staleInfo = identifyStaleInfo(existingArtifacts);
  
  // 2. 只获取变化的数据
  onEvent({ type: 'progress', step: '更新', detail: '正在补充最新数据...' });
  const freshData = await fetchFreshData(staleInfo.neededDataTypes);
  
  // 3. 构建增量Prompt
  const prompt = buildIncrementalPrompt(existingArtifacts, freshData);
  
  // 4. LLM增量分析
  onEvent({ type: 'progress', step: '分析', detail: '正在进行深度分析...' });
  await callLLMStream(prompt, (delta) => {
    onEvent({ type: 'text_delta', content: delta });
  });
  
  // 5. 标注参考产物
  for (const artifact of existingArtifacts) {
    onEvent({ 
      type: 'artifact_ref', 
      title: artifact.title, 
      excerpt: `基于${artifact.ageInHours}h前分析更新` 
    });
  }
}
```

### 7.3 数据新鲜度分级

| 数据类型 | 新鲜度要求 | 更新频率 | 来源 |
|----------|-----------|----------|------|
| 价格/行情 | ≤1min | 实时API | OKX Ticker |
| 费率 | ≤1h | 每小时 | OKX Funding Rate |
| FGI | ≤4h | 每日 | Alternative.me |
| ETF资金流 | ≤24h | 每日 | Farside/Bloomberg |
| 宏观事件 | ≤24h | 事件驱动 | Tavily/新闻 |
| Regime判断 | ≤24h | 每日 | 产物 |
| 支撑/阻力位 | ≤48h | 重大波动时 | 产物 |
| 战略框架 | ≤7天 | Regime切换时 | 产物 |

---

## 8. 完整示例：处理流程对比

### 8.1 场景：用户问"BTC现在怎么样"

**产物充足度评估**: A6情报2h前刚更新 → 充足度 85

```
Step 1: 领域识别 → 加密市场
Step 2: 任务类型 → 行情查询
Step 3: 产物评估 → 充足度85，A6情报2h前
Step 4: 处理策略 → 产物直返
Step 5: 执行 → 检索A6产物 + 补充实时价格 → 直接返回

耗时: ~2s (无需执行链路)
资源消耗: 0次LLM调用
```

### 8.2 场景：用户问"分析一下BTC"

**产物充足度评估**: A1 6h前 + A2 5h前，CPI数据刚落地 → 充足度 55

```
Step 1: 领域识别 → 加密市场
Step 2: 任务类型 → 分析研判
Step 3: 产物评估 → 充足度55，A1/A2可用但CPI后需更新
Step 4: 处理策略 → 增量更新
Step 5: 执行 → 复用A1/A2旧产物 + 获取CPI后最新数据 → 增量分析

耗时: ~15s (1次LLM调用)
资源消耗: 1次LLM调用 (vs 完整链路5+次)
```

### 8.3 场景：用户问"要开仓吗"

**产物充足度评估**: A1/A2有但A3/A4无 → 充足度 35

```
Step 1: 领域识别 → 加密市场
Step 2: 任务类型 → 交易执行
Step 3: 产物评估 → 充足度35，有A1/A2但缺推演和验证
Step 4: 处理策略 → 部分链路 (只跑推演→验证→风控)
Step 5: 执行 → 加载A1/A2产物 → 执行推演 → 验证 → 风控审查 → 给出建议

耗时: ~60s (3次LLM调用)
资源消耗: 3次LLM调用 (vs 完整链路5+次)
```

### 8.4 场景：用户问"从头分析一遍ETH"

**产物充足度评估**: ETH无任何产物 → 充足度 0

```
Step 1: 领域识别 → 加密市场
Step 2: 任务类型 → 完整分析
Step 3: 产物评估 → 充足度0，无可用产物
Step 4: 处理策略 → 完整链路
Step 5: 执行 → 侦察→分析→推演→验证→风控 → 全套产物

耗时: ~180s (5+次LLM调用)
资源消耗: 完整链路 (最重，但用户明确要求)
```

---

## 9. 产物中台交互接口

### 9.1 意图路由器需要调用的产物中台接口

```typescript
// 检索最新产物
interface ArtifactQuery {
  categories?: string[];     // 产物分类
  chainPhase?: string;       // 内部阶段过滤
  symbol?: string;           // 品种过滤
  limit?: number;            // 数量限制
  minRelevance?: number;     // 最低相关度
  since?: string;            // ISO时间，只返回此时间后的
}

// GET /api/artifacts/search
async function searchArtifacts(query: ArtifactQuery): Promise<ArtifactIndex[]>

// 获取单个产物详情
// GET /api/artifacts/:slug
async function getArtifactDetail(slug: string): Promise<ArtifactDetail>

// 获取市场状态快照（用于变化度评估）
// GET /api/market/snapshot
async function getMarketSnapshot(): Promise<MarketSnapshot>
```

### 9.2 产物分类映射

```
内部阶段        产物中台分类(category)
──────────────────────────────────────
intel       →  a6_intelligence
research    →  a1_research
analysis    →  a2_first_principles
simulation  →  a3_strategy
validation  →  a4_validation
risk_check  →  a7_gate / a9_exit
execution   →  a5_execution
```

---

## 10. 斜杠命令重新设计

**原则**: 斜杠命令也不暴露A系列代号，用用户直觉的命名。

| 命令 | 功能 | 用户看到 |
|------|------|----------|
| `/行情` | 查看当前行情 | BTC行情概览 |
| `/分析` | 分析研判 | 深度分析报告 |
| `/推演` | 情景推演 | 多情景推演 |
| `/验证` | 方案验证 | 验证结果 |
| `/开仓` | 交易决策 | 开仓建议 |
| `/风控` | 风控审查 | 风控报告 |
| `/离场` | 离场评估 | 离场建议 |
| `/情报` | 最新情报 | 情报快报 |
| `/全面` | 完整分析 | 全套分析 |
| `/状态` | 当前状态 | 系统状态 |
| `/策略` | 查看策略 | 策略列表 | ← v2.1新增
| `/配置` | 打开配置 | 配置面板 |
| `/参考` | 引用产物 | 产物引用 |

**内部映射**: `/分析` → `partial_chain(['research', 'analysis'])` → 内部执行A1+A2

---

## 11. 前端UI调整

### 11.1 右侧面板（隐藏A系列）

```
┌──────────────────────┐
│  📌 分析进度          │      ← 不叫"思维链路"
│  ──────────────────  │
│                      │
│  ✅ 情报更新  完成    │      ← 不叫"A6情报"
│  ✅ 市场侦察  完成    │      ← 不叫"A1侦察"
│  🔄 深度分析  进行中  │      ← 不叫"A2分析"
│  ⏳ 情景推演  等待    │      ← 不叫"A3推演"
│  ⏳ 方案验证  等待    │      ← 不叫"A4验证"
│  ⏳ 风控审查  等待    │      ← 不叫"A7门禁"
│                      │
│  📋 市场概况          │
│  ──────────────────  │
│  品种: BTC-USDT-SWAP │
│  状态: 区间震荡       │      ← 不叫"RANGE_BOUND"
│  持仓: 空仓          │
│  恐惧指数: 42        │      ← 不叫"FGI"
│  资金费率: +0.003%   │
│                      │
│  📎 参考报告 (2)      │      ← 不叫"引用产物"
│  ──────────────────  │
│  📄 深度分析 (3h前)   │
│  📄 情报快报 (1h前)   │
│                      │
│  ──────────────────  │
│  ⚙️ API配置          │
│  📡 通信渠道          │
│                      │
└──────────────────────┘
```

### 11.2 快捷命令栏调整

```
┌──────────────────────────────────────────────┐
│  /行情  /分析  /推演  /验证  /开仓  /风控     │  ← 用户直觉命名
│  /离场  /情报  /全面  /状态  /配置  /参考     │
└──────────────────────────────────────────────┘
```

### 11.3 消息中的进度显示

```
┌──────────────────────────────────────┐
│ 🤖 AI助手                            │
│                                      │
│ ⠋ 正在获取最新市场数据...             │
│ ✓ 已找到2份近期分析报告               │
│ ⠋ 正在补充最新数据...                 │
│ ⠋ 正在进行深度分析...                 │
│                                      │
│ 分析结论：                            │
│ 当前BTC处于区间震荡...                │
│ ...                                  │
│                                      │
│ 📎 基于：深度分析报告(3h前) + 最新数据 │
└──────────────────────────────────────┘
```
