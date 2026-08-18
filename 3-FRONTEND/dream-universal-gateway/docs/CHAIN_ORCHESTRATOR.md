# 内部链路执行器详细设计

> 版本: v2.0 | 日期: 2026-05-13 | 所属: Dream Universal Gateway
> ⚠️ **本模块为系统内部实现，用户完全不可见**
> 所有对外展示必须经过术语映射（见INTENT_ROUTER.md §3.6）

---

## 1. 编排器架构

### 1.1 核心职责

`ChainOrchestrator` 负责管理A0-A9思维链路的执行顺序、状态流转、产物关联和异常处理。

### 1.2 状态机模型

```
                    ┌────────────────────────────────────────┐
                    │            A0 宪法校验                   │
                    │  (每次链路启动时自动执行)                 │
                    └──────────┬──────────────┬─────────────┘
                               │              │
                    宪法通过    │              │  宪法冲突
                               ▼              ▼
                    ┌──────────────┐   ┌──────────────┐
                    │   A1 侦察     │   │   A8 批评     │
                    │  发现矛盾     │   │  反思宪法冲突  │
                    └──────┬───────┘   └──────────────┘
                           │
                    矛盾明确 │
                           ▼
                    ┌──────────────┐
              ┌────►│   A2 分析     │◄───────┐
              │     │  第一性原理    │        │
              │     └──────┬───────┘        │
              │            │                 │
              │     分析完成 │                 │ A4验证失败
              │            ▼                 │ (需重侦察)
              │     ┌──────────────┐   ┌────┴───────┐
              │     │   A3 推演     │   │ 回退到A1    │
              │     │  情景+概率    │   │ (限1次/周期) │
              │     └──────┬───────┘   └────────────┘
              │            │
              │     推演完成 │
              │            ▼
              │     ┌──────────────┐
              │     │   A4 验证     │────── 验证失败 → A3(修改方案)
              │     │  实践检验     │────── 验证失败 → A1(重侦察,限1次)
              │     └──────┬───────┘
              │            │
              │     验证通过 │
              │            ▼
              │     ┌──────────────┐
              │     │   A7 门禁     │
              │     │  合规审查     │
              │     └──┬───────┬───┘
              │        │       │
              │   通过  │       │ 拦截
              │        ▼       ▼
              │  ┌──────────┐  ┌──────────┐
              │  │ A5 执行   │  │ A8 批评   │
              │  │ 决策执行  │  │ 反思原因   │
              │  └────┬─────┘  └──────────┘
              │       │
              │  执行完成 │
              │       ▼
              │  ┌──────────┐
              │  │ A6 情报   │──── 显著变化 → 重新A1
              │  │ 持续监控  │
              │  └────┬─────┘
              │       │
              │  触发离场 │
              │       ▼
              │  ┌──────────┐
              │  │ A9 离场   │
              │  │ 风险检查  │
              │  └──────────┘
              │       │
              └───────┘ (新周期 → A0)
```

### 1.3 阶段定义

```typescript
interface ChainPhaseDefinition {
  id: string;                    // 'A0' ~ 'A9'
  name: string;                  // '宪法校验'
  description: string;
  color: string;                 // UI颜色
  icon: string;                  // UI图标
  estimatedDuration: number;     // 预估耗时(秒)
  
  // 输入输出
  inputs: string[];              // 依赖的前序产物
  outputs: string[];             // 生成的产物类型
  
  // 转换规则
  nextOnSuccess: string[];       // 成功后可跳转的阶段
  nextOnFailure: string[];       // 失败后可跳转的阶段
  
  // Skill映射
  skillName: string;             // 对应的Skill名称
  skillArgs: Record<string, string>; // Skill参数模板
}

const CHAIN_PHASES: Record<string, ChainPhaseDefinition> = {
  A0: {
    id: 'A0', name: '宪法校验',
    description: '加载系统宪法，校验当前决策是否符合最高指导原则',
    color: '#8b5cf6', icon: '📜',
    estimatedDuration: 5,
    inputs: [],
    outputs: ['constitution_check'],
    nextOnSuccess: ['A1'],
    nextOnFailure: ['A8'],
    skillName: 'dream-constitution',
    skillArgs: {}
  },
  A1: {
    id: 'A1', name: '侦察',
    description: '多源情报收集，发现市场主要矛盾',
    color: '#06b6d4', icon: '🔍',
    estimatedDuration: 30,
    inputs: [],
    outputs: ['a1_research'],
    nextOnSuccess: ['A2', 'A6'],
    nextOnFailure: ['A6'],
    skillName: 'dream-intelligence-monitor',
    skillArgs: { source: 'all' }
  },
  A2: {
    id: 'A2', name: '第一性原理分析',
    description: '基于矛盾论+孙子兵法+战争论，分析核心矛盾和趋势',
    color: '#3b82f6', icon: '🧠',
    estimatedDuration: 45,
    inputs: ['a1_research'],
    outputs: ['a2_first_principles'],
    nextOnSuccess: ['A3', 'A8'],
    nextOnFailure: ['A1'],
    skillName: 'dream-first-principles',
    skillArgs: {}
  },
  A3: {
    id: 'A3', name: '情景推演',
    description: '多情景概率推演，制定战略方案',
    color: '#6366f1', icon: '🎲',
    estimatedDuration: 30,
    inputs: ['a2_first_principles'],
    outputs: ['a3_strategy'],
    nextOnSuccess: ['A4'],
    nextOnFailure: ['A2'],
    skillName: 'dream-tactical-validator',
    skillArgs: {}
  },
  A4: {
    id: 'A4', name: '实践验证',
    description: '用模拟盘验证推演方案，检测假设是否成立',
    color: '#8b5cf6', icon: '🔬',
    estimatedDuration: 60,
    inputs: ['a3_strategy'],
    outputs: ['a4_validation'],
    nextOnSuccess: ['A7'],
    nextOnFailure: ['A3', 'A1'],
    skillName: 'dream-tactical-validator',
    skillArgs: { mode: 'validate' }
  },
  A5: {
    id: 'A5', name: '综合判断执行',
    description: '根据验证结果，综合判断并执行交易操作',
    color: '#f59e0b', icon: '⚡',
    estimatedDuration: 30,
    inputs: ['a4_validation', 'a6_intelligence'],
    outputs: ['a5_execution'],
    nextOnSuccess: ['A6'],
    nextOnFailure: ['A6'],
    skillName: 'dream-tactical-executor',
    skillArgs: {}
  },
  A6: {
    id: 'A6', name: '情报监控',
    description: '持续监控市场变化，检测显著信号',
    color: '#06b6d4', icon: '📡',
    estimatedDuration: 20,
    inputs: [],
    outputs: ['a6_intelligence_brief'],
    nextOnSuccess: ['A5', 'A1', 'A2', 'A9'],
    nextOnFailure: [],
    skillName: 'dream-intelligence-monitor',
    skillArgs: { mode: 'brief' }
  },
  A7: {
    id: 'A7', name: '门禁审查',
    description: '合规审查，确保执行方案符合风控规则',
    color: '#ef4444', icon: '🚧',
    estimatedDuration: 10,
    inputs: ['a4_validation'],
    outputs: ['a7_gate_result'],
    nextOnSuccess: ['A5'],
    nextOnFailure: ['A8'],
    skillName: 'A7-practice-theory',
    skillArgs: {}
  },
  A8: {
    id: 'A8', name: '理论与实践结合验证',
    description: '自我批评，检查知行合一',
    color: '#8b5cf6', icon: '⚖️',
    estimatedDuration: 30,
    inputs: [],
    outputs: ['a8_critique'],
    nextOnSuccess: ['A0', 'A2', 'A3'],
    nextOnFailure: [],
    skillName: 'A8-theory-practice-verification',
    skillArgs: {}
  },
  A9: {
    id: 'A9', name: '离场决策',
    description: '风险检查与离场评估',
    color: '#f59e0b', icon: '🚪',
    estimatedDuration: 15,
    inputs: [],
    outputs: ['a9_exit_decision'],
    nextOnSuccess: ['A6'],
    nextOnFailure: [],
    skillName: 'dream-exit-skill-v2',
    skillArgs: {}
  }
};
```

---

## 2. 编排执行流程

### 2.1 单阶段执行

```typescript
async function executePhase(
  phaseId: ChainPhaseId,
  context: ChainContext,
  onEvent: (event: SSEEvent) => void
): Promise<PhaseResult> {
  const phase = CHAIN_PHASES[phaseId];
  
  // 1. 发送开始事件
  onEvent({ type: 'chain_start', phase: phaseId, sessionId: context.sessionId });
  
  // 2. 读取前置产物
  onEvent({ type: 'chain_progress', phase: phaseId, progress: 0.1, message: '读取前置产物...' });
  const inputs = await loadInputArtifacts(phase.inputs, context);
  
  // 3. 构建Prompt
  onEvent({ type: 'chain_progress', phase: phaseId, progress: 0.2, message: '构建分析上下文...' });
  const prompt = buildPhasePrompt(phaseId, inputs, context);
  
  // 4. 调用LLM（流式）
  onEvent({ type: 'chain_progress', phase: phaseId, progress: 0.3, message: '调用思维链路...' });
  let fullResponse = '';
  await callLLMStream(prompt, context.llmConfig, (delta) => {
    fullResponse += delta;
    onEvent({ type: 'text_delta', content: delta });
  });
  
  // 5. 调用对应Skill（如果需要执行操作）
  if (phase.skillName && context.enableSkillExecution) {
    onEvent({ type: 'chain_progress', phase: phaseId, progress: 0.7, message: '执行Skill...' });
    const skillResult = await invokeSkill(phase.skillName, phase.skillArgs, context);
    // 将Skill结果附加到响应
  }
  
  // 6. 保存产物
  onEvent({ type: 'chain_progress', phase: phaseId, progress: 0.9, message: '保存产物...' });
  const artifactId = await saveArtifact(phaseId, fullResponse, context);
  onEvent({ type: 'chain_artifact', phase: phaseId, artifactId, title: `${phase.name}产物` });
  
  // 7. 通知渠道
  if (shouldPush(phaseId, context)) {
    await pushToChannels(phaseId, fullResponse, context);
  }
  
  // 8. 完成
  onEvent({ type: 'chain_complete', phase: phaseId, result: 'success' });
  return { phaseId, status: 'completed', artifactId };
}
```

### 2.2 链式执行

```typescript
async function executeChain(
  startPhase: ChainPhaseId,
  context: ChainContext,
  onEvent: (event: SSEEvent) => void
): Promise<void> {
  const executionPlan = planExecution(startPhase, context);
  
  for (const phaseId of executionPlan) {
    const result = await executePhase(phaseId, context, onEvent);
    
    if (result.status === 'completed') {
      context.completedPhases.add(phaseId);
      context.artifacts.push(result.artifactId!);
    } else if (result.status === 'failed') {
      // 失败处理：检查是否可回退
      const fallback = determineFallback(phaseId, context);
      if (fallback) {
        onEvent({ type: 'chain_progress', phase: fallback, progress: 0, message: `回退到${CHAIN_PHASES[fallback].name}...` });
        await executePhase(fallback, context, onEvent);
      }
      break;
    }
    
    // 用户中断检查
    if (context.interrupted) break;
  }
}
```

---

## 3. SSE事件协议

### 3.1 客户端 → 服务端

```typescript
// POST /api/chat
interface ChatRequest {
  messages: ChatMessage[];
  sessionId: string;
  chainState?: ChainState;
  action?: 'chat' | 'execute_phase' | 'execute_chain';
  targetPhase?: ChainPhaseId;    // 当action=execute_phase时
  llmConfig: LLMConfig;
}

interface ChatMessage {
  role: 'user' | 'assistant' | 'system';
  content: string;
  metadata?: {
    artifacts?: string[];        // 引用的产物ID
    chainPhase?: ChainPhaseId;   // 关联的链路阶段
  };
}
```

### 3.2 服务端 → 客户端

```typescript
// SSE 事件流
type SSEEvent = 
  // 链路事件
  | { type: 'chain_start'; phase: ChainPhaseId; sessionId: string }
  | { type: 'chain_progress'; phase: ChainPhaseId; progress: number; message: string }
  | { type: 'chain_artifact'; phase: ChainPhaseId; artifactId: string; title: string }
  | { type: 'chain_complete'; phase: ChainPhaseId; result: 'success' | 'skip' | 'fail' }
  
  // 文本事件
  | { type: 'text_delta'; content: string }
  | { type: 'text_done'; fullContent: string }
  
  // 产物事件
  | { type: 'artifact_ref'; artifactId: string; title: string; excerpt: string }
  
  // 推送事件
  | { type: 'push_sent'; channel: string; messageId: string }
  
  // 错误事件
  | { type: 'error'; code: string; message: string; retryable: boolean };
```

---

## 4. 斜杠命令解析

```typescript
function parseSlashCommand(input: string): ParsedCommand | null {
  const trimmed = input.trim();
  
  // 匹配 /A0 ~ /A9
  const phaseMatch = trimmed.match(/^\/(A([0-9]))\s*(.*)/i);
  if (phaseMatch) {
    return {
      type: 'execute_phase',
      phase: phaseMatch[1].toUpperCase() as ChainPhaseId,
      args: phaseMatch[3] || '',
    };
  }
  
  // 匹配 /full
  if (trimmed.match(/^\/full\s*(.*)/i)) {
    return {
      type: 'execute_chain',
      startPhase: 'A0',
      args: trimmed.replace(/^\/full\s*/i, ''),
    };
  }
  
  // 匹配 /status
  if (trimmed.match(/^\/status/i)) {
    return { type: 'query_status' };
  }
  
  // 匹配 /config
  if (trimmed.match(/^\/config\s*(.*)/i)) {
    return { type: 'open_config', args: trimmed.replace(/^\/config\s*/i, '') };
  }
  
  // 匹配 /ref
  if (trimmed.match(/^\/ref\s+(.+)/i)) {
    return { type: 'reference_artifact', args: trimmed.replace(/^\/ref\s+/i, '') };
  }
  
  return null; // 普通对话
}

interface ParsedCommand {
  type: 'execute_phase' | 'execute_chain' | 'query_status' | 'open_config' | 'reference_artifact';
  phase?: ChainPhaseId;
  startPhase?: ChainPhaseId;
  args?: string;
}
```

---

## 5. 产物自动引用

### 5.1 上下文构建

```typescript
async function buildChainContext(sessionId: string): Promise<ChainContext> {
  // 1. 读取最近产物
  const recentArtifacts = await getRecentArtifacts(limit: 20);
  
  // 2. 按A阶段分组
  const artifactsByPhase = groupBy(recentArtifacts, 'chain_phase');
  
  // 3. 构建上下文
  return {
    sessionId,
    completedPhases: new Set(),
    artifacts: [],
    recentArtifacts: artifactsByPhase,
    marketState: await getCurrentMarketState(),  // 从产物中台读取
    positionState: await getCurrentPosition(),     // 从OKX API读取
  };
}
```

### 5.2 产物注入Prompt

```
## 近期产物（按A阶段）

### A1 侦察 (最近3篇)
- a1_research_20260513_2009: "宏观CPI 3.8%超预期，费率翻转..."
- a1_research_20260512_1245: "RANGE_BOUND持续，支撑$79.7K..."

### A2 分析 (最近3篇)
- a2_first_principles_20260513_0130: "8大矛盾中C1宏观矛盾为..."
- a2_first_principles_20260512_0130: "阻力最小方向为区间震荡..."

### A6 情报 (最近2篇)
- a6_intelligence_brief_20260513_2000: "费率+0.0034%，SI_Index +9..."

## 当前市场状态
- Regime: RANGE_BOUND
- BTC价格: $80,630
- 持仓: 空仓
- FGI: 42 (Fear)
```
