/**
 * ============================================================
 *  🧠  自动图生成 - 从自然语言自动构建三层图结构
 * ============================================================
 *
 *  核心思想：
 *    将用户消息流解析为：意图 → 步骤 → 执行记录。
 *    通过关键词识别 + 规则引擎，生成标准化的 Blueprint/Architecture/Chronicle
 *
 *  使用场景：
 *    1. 当用户提出新的请求时，自动判断该请求是"新主题"还是"旧主题延伸"
 *    2. 自动提取用户意图和关键信息，构建对应的 Blueprint
 *    3. 结合调度器的 Skip Gate 决策，记录每步是否跳过
 *
 *  工作流程：
 *    输入：用户消息数组 → 意图识别 → 蓝图生成 → 架构图展开 → 执行记录构建 → 压缩
 *    输出：CompressedContext { blueprint, architecture, compressedChronicle }
 */

import { graphCompress, type CompressMessage, type CompressResult } from './graph-compress.ts';

// 简化的蓝图 & 架构图类型（不依赖 blueprint-registry）
export interface BlueprintGraph {
  id: string;
  name: string;
  description: string;
  nodes: Map<string, { id: string; name: string; type: string; description: string; metadata: Record<string, unknown>; children?: string[] }>;
  edges: Array<{ source: string; target: string; label: string; type?: string; dataFlow?: string }>;
}

export interface ArchitectureGraph {
  id: string;
  name: string;
  parentBlueprintId: string;
  nodes: Map<string, { id: string; name: string; type: string; requires?: string[]; metadata: Record<string, unknown> }>;
  edges: Array<{ source: string; target: string; type: string; label?: string; metadata?: Record<string, unknown> }>;
  entryNodes: string[];
  exitNodes: string[];
}

// ============================================================
// ==================== 意图识别 & 路由 =======================
// ============================================================

export interface IntentMatch {
  intent: string;
  confidence: number;
  keywords: string[];
  recommendedBlueprint: string;
}

// 扩展关键词表
const INTENT_KEYWORDS: Record<string, string[]> = {
  trading: ['买入', '卖出', '入场', '离场', '止损', '做多', '做空', '开仓',
            '加仓', '平仓', '下单', 'buy', 'sell', 'position', 'entry', 'exit'],
  analysis: ['分析', '研究', '调研', '行情', '趋势', '市场', '数据', '指标',
             '技术面', '基本面', 'macd', 'rsi', '布林带', 'analysis', 'market', 'trend', 'research'],
  strategy: ['策略', '设计', '优化', '回测', '参数', '规则', '信号', '触发',
              'strategy', 'backtest', 'design', 'optimize', 'signal'],
  risk: ['风险', '风控', '止损', '止盈', '资金管理', '保证金', '杠杆',
         '风险收益比', '夏普', '最大回撤', '胜率', '期望收益',
         'risk', 'stop-loss', 'take-profit', 'risk-reward'],
  coding: ['代码', '实现', '开发', 'bug', '修复', '组件', '模块',
            'code', 'implement', 'dev', 'fix', 'build', 'script', 'test'],
  design: ['设计', '架构', '方案', '规划', '结构', '模型',
           'design', 'architecture', 'structure', 'model', 'schema'],
  compression: ['压缩', '总结', '摘要', '上下文', '图压缩', '保留上下文',
                 'compress', 'summary', 'context', 'graph'],
  scheduling: ['调度', 'skip', '跳过', '决策', '优先级', '调度器', '执行计划',
                'schedule', 'priority', 'decision', 'skip-gate'],
};

// 各意图的推荐 Blueprint 模板
const INTENT_TO_BLUEPRINT: Record<string, string> = {
  trading: 'classic-trading',
  analysis: 'deep-analysis',
  strategy: 'strategy-research',
  risk: 'risk-management',
  coding: 'coding-task',
  design: 'system-design',
  compression: 'context-compression',
  scheduling: 'scheduler-orchestration',
};

export function detectIntent(messages: CompressMessage[]): IntentMatch {
  if (!messages || messages.length === 0) {
    return {
      intent: 'general',
      confidence: 0,
      keywords: [],
      recommendedBlueprint: 'default-template',
    };
  }

  const content = messages.map((m) => m.content).join(' ').toLowerCase();
  const scores: Record<string, { count: number; kws: string[] }> = {};

  for (const [intent, keywords] of Object.entries(INTENT_KEYWORDS)) {
    let count = 0;
    const matched: string[] = [];
    for (const kw of keywords) {
      if (content.includes(kw.toLowerCase())) {
        count += 1;
        matched.push(kw);
      }
    }
    if (count > 0) {
      scores[intent] = { count, kws: matched };
    }
  }

  // 按关键词命中数排序
  const sorted = Object.entries(scores).sort((a, b) => b[1].count - a[1].count);
  if (sorted.length === 0) {
    return {
      intent: 'general',
      confidence: 0.1,
      keywords: [],
      recommendedBlueprint: 'default-template',
    };
  }

  const topIntent = sorted[0];
  const totalHits = Object.values(scores).reduce((s, v) => s + v.count, 0);
  return {
    intent: topIntent[0],
    confidence: totalHits > 0 ? topIntent[1].count / totalHits : 0,
    keywords: topIntent[1].kws,
    recommendedBlueprint: INTENT_TO_BLUEPRINT[topIntent[0]] || 'default-template',
  };
}

// ============================================================
// ==================== 自动蓝图生成 ===========================
// ============================================================

export interface GeneratedBlueprint extends BlueprintGraph {
  intent: string;
  confidence: number;
  matchedKeywords: string[];
  suggestedSteps: string[];
}

export function generateBlueprint(
  messages: CompressMessage[],
  options: { sessionId?: string; topicHint?: string } = {}
): GeneratedBlueprint {
  const intentMatch = detectIntent(messages);

  // 生成蓝图步骤
  let steps: string[] = [];
  switch (intentMatch.intent) {
    case 'trading':
      steps = ['市场数据分析', '信号识别', '风险评估', '入场参数设置', '执行下单'];
      break;
    case 'analysis':
      steps = ['数据收集', '技术指标分析', '基本面评估', '趋势判断', '综合分析'];
      break;
    case 'strategy':
      steps = ['需求分析', '策略框架设计', '参数优化', '历史回测', '策略验证'];
      break;
    case 'risk':
      steps = ['风险识别', '止损/止盈设置', '资金管理', '风险收益比计算', '风控策略'];
      break;
    case 'coding':
      steps = ['需求理解', '方案设计', '代码实现', '单元测试', '代码评审', '集成测试'];
      break;
    case 'design':
      steps = ['问题定义', '架构方案设计', '组件划分', '数据模型', '流程图'];
      break;
    case 'compression':
      steps = ['上下文收集', '节点评分', '压缩执行', '可视化', '持久化'];
      break;
    case 'scheduling':
      steps = ['任务队列', '优先级评估', 'Skip Gate 决策', '执行调度', '结果汇总'];
      break;
    default:
      steps = ['需求理解', '信息收集', '分析处理', '决策输出', '执行总结'];
  }

  const nodes = new Map<string, { id: string; name: string; type: string; description: string; metadata: Record<string, unknown> }>();
  nodes.set('root', {
    id: 'root',
    name: `${intentMatch.intent} - 对话`,
    type: 'module',
    description: `${intentMatch.intent} 主题的对话处理`,
    metadata: { intent: intentMatch.intent, confidence: intentMatch.confidence, status: 'active' },
  });
  steps.forEach((stepName, idx) => {
    const id = `step_${idx}`;
    nodes.set(id, {
      id,
      name: stepName,
      type: 'component',
      description: stepName,
      metadata: { order: idx, status: 'pending' },
    });
  });

  const edges: Array<{ source: string; target: string; label: string; type: string }> = [];
  // root → 第一个 step
  if (steps.length > 0) edges.push({ source: 'root', target: 'step_0', label: '→', type: 'flow' });
  // step 之间串联
  for (let i = 0; i < steps.length - 1; i++) {
    edges.push({ source: `step_${i}`, target: `step_${i + 1}`, label: '→', type: 'flow' });
  }

  return {
    id: `bp_${options.sessionId || Date.now()}`,
    name: `${intentMatch.intent} - 对话蓝图`,
    description: `基于 ${messages.length} 条消息自动生成，意图置信度: ${(intentMatch.confidence * 100).toFixed(0)}%`,
    nodes,
    edges,
    intent: intentMatch.intent,
    confidence: intentMatch.confidence,
    matchedKeywords: intentMatch.keywords,
    suggestedSteps: steps,
  };
}

// ============================================================
// ==================== 架构图自动展开 ==========================
// ============================================================

export function expandToArchitecture(
  messages: CompressMessage[],
  blueprint: GeneratedBlueprint
): ArchitectureGraph {
  const steps: Array<{ id: string; name: string; type: string; requires: string[]; metadata: Record<string, unknown> }> = [];

  // 为每条消息生成一个架构步骤
  messages.forEach((msg, idx) => {
    let stepType = 'step';
    let score = 0.5;

    // 基于内容识别步骤类型
    if (msg.importance === 'high') {
      stepType = 'decision';
      score = 0.85;
    } else if (msg.role === 'tool_call' || msg.role === 'tool_result') {
      stepType = 'parallel';
      score = 0.6;
    } else {
      const content = msg.content.toLowerCase();
      if (/建议|决策|确定|确认|方案|执行|已确认|✅|决定|重要|关键/.test(content)) {
        stepType = 'decision';
        score = 0.8;
      } else if (/分析|研究|回测|评估|计算|测试/.test(content)) {
        stepType = 'step';
        score = 0.7;
      } else {
        score = 0.5;
      }
    }

    const stepId = `a_${idx}`;
    steps.push({
      id: stepId,
      name: `${msg.role.toUpperCase()}: ${msg.content.slice(0, 50)}${msg.content.length > 50 ? '...' : ''}`,
      type: stepType,
      requires: idx > 0 ? [`a_${idx - 1}`] : [],
      metadata: {
        order: idx,
        score,
        role: msg.role,
        status: msg.importance === 'high' ? 'critical' : 'normal',
        isUserInitiated: msg.role === 'user',
      },
    });
  });

  const archNodes = new Map<string, typeof steps[0] & { requires: string[] }>();
  steps.forEach((s) => archNodes.set(s.id, s));

  const edges: Array<{ source: string; target: string; type: string; label: string; metadata: Record<string, unknown> }> = [];
  for (let i = 0; i < steps.length - 1; i++) {
    edges.push({
      source: steps[i].id,
      target: steps[i + 1].id,
      type: 'sequential',
      label: '→',
      metadata: { flowType: 'message-flow' },
    });
  }

  return {
    id: `arch_${Date.now()}`,
    name: `${blueprint.intent} - 自动架构图 (${steps.length} 步)`,
    parentBlueprintId: blueprint.id,
    nodes: archNodes,
    edges,
    entryNodes: steps.length > 0 ? [steps[0].id] : [],
    exitNodes: steps.length > 0 ? [steps[steps.length - 1].id] : [],
  };
}

// ============================================================
// ==================== 完整自动压缩 ============================
// ============================================================

export interface AutoCompressResult {
  intentMatch: IntentMatch;
  blueprint: GeneratedBlueprint;
  architecture: ArchitectureGraph;
  compressionResult: CompressResult & {
    keptMessages: CompressMessage[];
    compressedMessages: CompressMessage[];
    summaryText: string;
  };
  timeline: CompressMessage[];
  generatedAt: number;
}

export function autoCompressContext(
  messages: CompressMessage[],
  options: {
    sessionId?: string;
    targetRatio?: number;
    highlightKeywords?: string[];
    topicHint?: string;
  } = {}
): AutoCompressResult {
  const {
    sessionId = `auto_${Date.now()}`,
    targetRatio = 0.5,
    highlightKeywords = [],
  } = options;

  // Step 1: 意图识别
  const intentMatch = detectIntent(messages);

  // Step 2: 自动生成 Blueprint
  const blueprint = generateBlueprint(messages, { sessionId, topicHint: options.topicHint });

  // Step 3: 自动展开为 Architecture
  const architecture = expandToArchitecture(messages, blueprint);

  // Step 4: 语义压缩（基于图压缩模块）
  const compressResult = graphCompress({
    messages,
    targetRatio,
    highlightKeywords: [
      ...INTENT_KEYWORDS[intentMatch.intent] || [],
      ...highlightKeywords,
    ],
  });

  const timeline = messages.slice().sort((a, b) => (a.timestamp || 0) - (b.timestamp || 0));

  // 生成摘要文本
  const keptMsgs = compressResult.kept;
  const compressedMsgs = compressResult.compressed;
  const ratio = compressResult.summary.compressionRatio;

  const summaryLines: string[] = [];
  summaryLines.push(`📊 自动上下文压缩完成`);
  summaryLines.push(`🧠 意图: ${intentMatch.intent} (置信度: ${(intentMatch.confidence * 100).toFixed(0)}%)`);
  summaryLines.push(`🎯 推荐 Blueprint: ${intentMatch.recommendedBlueprint}`);
  summaryLines.push(`🔤 命中关键词: ${intentMatch.keywords.slice(0, 10).join(', ')}`);
  summaryLines.push(`📝 总消息: ${messages.length} | 保留: ${keptMsgs.length} | 压缩: ${compressedMsgs.length}`);
  summaryLines.push(`📉 压缩率: ${(ratio * 100).toFixed(0)}%`);
  summaryLines.push(``);
  summaryLines.push(`--- 🔒 保留的关键内容 ---`);
  keptMsgs.slice(0, 8).forEach((m, i) => {
    summaryLines.push(`  ${i + 1}. [${m.role}] ${m.content.slice(0, 80)}${m.content.length > 80 ? '...' : ''}`);
  });
  if (keptMsgs.length > 8) summaryLines.push(`  ... 共 ${keptMsgs.length} 条保留`);

  return {
    intentMatch,
    blueprint,
    architecture,
    compressionResult: {
      ...compressResult,
      keptMessages: keptMsgs,
      compressedMessages: compressedMsgs,
      summaryText: summaryLines.join('\n'),
    },
    timeline,
    generatedAt: Date.now(),
  };
}

// ============================================================
// ==================== 辅助函数 ================================
// ============================================================

// 判断是否为新主题（与之前主题的相似度是否低于阈值）
export function isNewTopic(
  previousMessages: CompressMessage[],
  newMessage: CompressMessage,
  threshold: number = 0.5
): { isNewTopic: boolean; similarity: number; reason: string } {
  if (!previousMessages || previousMessages.length === 0) {
    return { isNewTopic: true, similarity: 0, reason: '没有历史消息' };
  }

  const prevIntent = detectIntent(previousMessages);
  const newMsgIntent = detectIntent([newMessage]);

  // 简单相似度：意图相同 + 关键词重叠
  let keywordOverlap = 0;
  const prevKws = new Set(prevIntent.keywords.map((k) => k.toLowerCase()));
  for (const kw of newMsgIntent.keywords) {
    if (prevKws.has(kw.toLowerCase())) keywordOverlap += 1;
  }
  const similarity = prevIntent.intent === newMsgIntent.intent
    ? Math.min(1, 0.6 + keywordOverlap * 0.1)
    : keywordOverlap * 0.15;

  let reason: string;
  if (similarity >= threshold) {
    reason = `主题延续 (${(similarity * 100).toFixed(0)}%) - 属于"${prevIntent.intent}"主题`;
  } else {
    reason = `新主题检测 (${(similarity * 100).toFixed(0)}%) - 从"${prevIntent.intent}"转向"${newMsgIntent.intent}"`;
  }

  return {
    isNewTopic: similarity < threshold,
    similarity,
    reason,
  };
}

// 多会话上下文合并 - 保留每个会话的压缩摘要
export function mergeSessionContexts(
  sessions: Array<{ sessionId: string; messages: CompressMessage[]; name?: string }>,
  options: { targetRatio?: number } = {}
): {
  mergedSummary: string;
  sessionsSummary: Array<{
    sessionId: string;
    name?: string;
    intent: string;
    messageCount: number;
    keptCount: number;
    topMessages: CompressMessage[];
  }>;
} {
  const sessionsSummary = sessions.map((session) => {
    const intentMatch = detectIntent(session.messages);
    const result = graphCompress({
      messages: session.messages,
      targetRatio: options.targetRatio || 0.3,
    });
    return {
      sessionId: session.sessionId,
      name: session.name,
      intent: intentMatch.intent,
      messageCount: session.messages.length,
      keptCount: result.kept.length,
      topMessages: result.kept.slice(0, 3),
    };
  });

  let mergedSummary = '📚 合并上下文 - 多会话摘要\n';
  mergedSummary += '='.repeat(60) + '\n';
  sessionsSummary.forEach((sess, i) => {
    mergedSummary += `\n${i + 1}. [${sess.intent.toUpperCase()}] ${sess.name || sess.sessionId}\n`;
    mergedSummary += `   消息: ${sess.messageCount} 条 (保留 ${sess.keptCount} 条)\n`;
    sess.topMessages.forEach((m) => {
      mergedSummary += `   • ${m.content.slice(0, 80)}\n`;
    });
  });

  return {
    mergedSummary,
    sessionsSummary,
  };
}

// ============================================================
// ==================== CLI 演示 ================================
// ============================================================

if (typeof process !== 'undefined' && process.argv && process.argv[1]?.includes('auto-graph-generator.ts')) {
  console.log('='.repeat(60));
  console.log('🧠 Auto Graph Generator - 自动图生成演示');
  console.log('='.repeat(60));

  // 模拟多主题对话
  const tradingMessages: CompressMessage[] = [
    { id: '1', role: 'user', content: '帮我分析 BTC 行情', timestamp: Date.now() },
    { id: '2', role: 'assistant', content: 'BTC 当前价格 65,200 USDT，24h 涨幅 +2.3%，RSI 55', timestamp: Date.now() + 1000 },
    { id: '3', role: 'user', content: '我想做多，入场点应该设在哪里？', timestamp: Date.now() + 2000 },
    { id: '4', role: 'assistant', content: '建议：入场 64,800，止损 64,200，第一止盈 65,800', importance: 'high', timestamp: Date.now() + 3000 },
    { id: '5', role: 'user', content: '仓位呢？', timestamp: Date.now() + 4000 },
    { id: '6', role: 'assistant', content: '保守仓位：总资金的 3%，风险收益比约 1:1.67', importance: 'high', timestamp: Date.now() + 5000 },
    { id: '7', role: 'user', content: '好的，那就按这个方案执行', importance: 'high', timestamp: Date.now() + 6000 },
    { id: '8', role: 'assistant', content: '✅ 已确认，等待 BTC 价格触发入场条件', importance: 'high', timestamp: Date.now() + 7000 },
  ];

  console.log(`\n📝 输入: ${tradingMessages.length} 条交易对话消息`);
  const result = autoCompressContext(tradingMessages, {
    sessionId: 'demo_trading',
    targetRatio: 0.5,
    highlightKeywords: ['BTC', '入场', '止损', '风险收益比', '执行', '确认'],
  });

  console.log(`\n--- 🧠 意图识别结果 ---`);
  console.log(`  意图: ${result.intentMatch.intent}`);
  console.log(`  置信度: ${(result.intentMatch.confidence * 100).toFixed(0)}%`);
  console.log(`  推荐 Blueprint: ${result.intentMatch.recommendedBlueprint}`);
  console.log(`  命中关键词: ${result.intentMatch.keywords.slice(0, 6).join(', ')}`);

  console.log(`\n--- 🏗️  生成的 Blueprint ---`);
  console.log(`  名称: ${result.blueprint.name}`);
  console.log(`  节点数: ${result.blueprint.nodes.size}`);
  console.log(`  建议步骤: ${result.blueprint.suggestedSteps.join(' → ')}`);

  console.log(`\n--- 🔀  展开的 Architecture ---`);
  console.log(`  步骤数: ${result.architecture.nodes.size}`);
  const decisionCount = Array.from(result.architecture.nodes.values()).filter((n: any) => n.type === 'decision').length;
  console.log(`  决策点: ${decisionCount} 个`);

  console.log(`\n--- 📊 压缩结果 ---`);
  console.log(`  保留: ${result.compressionResult.keptMessages.length} 条`);
  console.log(`  压缩: ${result.compressionResult.compressedMessages.length} 条`);
  console.log(`  压缩率: ${(result.compressionResult.summary.compressionRatio * 100).toFixed(0)}%`);

  console.log('\n--- 📋 LLM 上下文摘要（压缩后保留的关键消息）---');
  result.compressionResult.keptMessages.slice(0, 5).forEach((m, i) => {
    const tag = m.importance === 'high' ? '⭐' : '•';
    console.log(`  ${tag} [${m.role}] ${m.content.slice(0, 100)}`);
  });

  console.log('\n' + '='.repeat(60));
  console.log('✅ 自动图生成演示完成！');
  console.log('='.repeat(60));
}
