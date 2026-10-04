/**
 * ============================================================
 *  🗜️  图结构上下文压缩 - SKILL 核心引擎
 * ============================================================
 *
 *  在对话中直接调用，自动构建三层图并压缩：
 *    • B 层 (Blueprint)    对话意图/组件结构
 *    • A 层 (Architecture) 执行步骤与依赖
 *    • C 层 (Chronicle)    每条消息的执行记录
 *
 *  评分维度：tokens 消耗 (40%)  +  语义关键词 (40%)  +  执行耗时 (20%)
 *
 *  用法：
 *    const result = graphCompress({ messages: conversationHistory, targetRatio: 0.5 });
 *    console.log(result.summary);
 */

// ============================================================
// ==================== 类型定义 ==============================
// ============================================================

export interface CompressMessage {
  id: string;
  role: 'user' | 'assistant' | 'tool_call' | 'tool_result' | 'system';
  content: string;
  timestamp?: number;
  tokens?: number;
  toolName?: string;
  decision?: string;
  importance?: 'high' | 'medium' | 'low';
}

export interface CompressOptions {
  messages: CompressMessage[];
  targetRatio?: number;         // 默认 0.5（保留 50% 节点）
  intent?: string;              // 显式意图（可选）
  highlightKeywords?: string[]; // 领域关键词（命中加分）
  minKeepThreshold?: number;    // 强制保留的最低评分（默认 0.4）
}

export interface CompressedNode {
  id: string;
  name: string;
  role: string;
  content: string;
  score: number;
  timestamp: number;
  kept: boolean;
  reason?: string;
  keywords?: string[];
}

export interface CompressResult {
  summary: {
    totalMessages: number;
    keptCount: number;
    compressedCount: number;
    compressionRatio: number;        // 压缩率（压缩后/压缩前）
    avgKeptScore: number;
    avgCompressedScore: number;
    intentDetected: string;
    totalTokens: number;
    latencyMs: number;
  };
  kept: CompressedNode[];          // 保留的节点（按评分降序）
  compressed: CompressedNode[];    // 压缩的节点
  timeline: CompressedNode[];      // 时间线（按时间升序，含状态）
  blueprint: {
    id: string;
    name: string;
    components: string[];
    intent: string;
  };
  architecture: {
    id: string;
    steps: { id: string; name: string; type: string; score: number }[];
  };
  visualization: {
    layerBefore: { blueprint: number; architecture: number; chronicle: number };
    layerAfter: { blueprint: number; architecture: number; chronicle: number };
    nodesByStatus: { kept: number; compressed: number };
    compressionRatio: number;
  };
  textSummary: string;              // 人类可读文本摘要
}

// ============================================================
// ==================== 关键词库 ==============================
// ============================================================

// 意图关键词（用于意图检测）
const INTENT_KEYWORDS: Record<string, string[]> = {
  trading: ['买入', '卖出', '仓位', '入场', '离场', '止损', '做多', '做空',
            '开仓', '加仓', '平仓', '下单', '交易', 'buy', 'sell', 'position', 'entry', 'exit'],
  analysis: ['分析', '研究', '调研', '行情', '趋势', '市场', '数据', '指标',
              '技术面', '基本面', 'macd', 'rsi', '布林带', 'analysis', 'market', 'trend', 'research'],
  strategy: ['策略', '设计', '优化', '回测', '参数', '规则', '信号', '触发',
              'strategy', 'backtest', 'design', 'optimize', 'signal'],
  risk: ['风险', '风控', '止损', '止盈', '资金管理', '保证金', '杠杆',
         '风险收益比', '夏普', '最大回撤', '胜率', '期望收益',
         'risk', 'stop-loss', 'take-profit', 'risk-reward', 'sharpe'],
  compression: ['压缩', '总结', '摘要', '上下文', '图压缩', '保留',
                 'compress', 'summary', 'context', 'graph', '压缩上下文', '保留上下文'],
  coding: ['代码', '实现', '开发', 'bug', '修复', '组件', '模块',
            'code', 'implement', 'dev', 'fix', 'build', 'script'],
  design: ['设计', '架构', '方案', '规划', '结构', '模型',
           'design', 'architecture', 'structure', 'model', 'schema'],
};

// 高价值关键词（命中则提升评分）
const HIGH_VALUE_KWS = [
  '决策', '确认', '最终', '关键', '重要', '结论', '建议', '推荐', '执行',
  '决定', '买入', '卖出', '入场', '止损', '止盈', '风险', '仓位',
  '风险收益比', '夏普', '最大回撤', '胜率', '期望收益', '策略', '信号',
  '完成', '成功', '通过', '验证', '批准', 'confirm', 'final', 'decision', 'execute',
  '代码', '修复', '实现', '组件', '模块', 'fix', 'implement', 'component', 'module',
  '架构', '设计', '方案', '蓝图', '蓝图', 'architecture', 'design', 'blueprint',
];

// ============================================================
// ==================== 辅助函数 ==============================
// ============================================================

function estimateTokens(text: string): number {
  if (!text) return 0;
  const chinese = (text.match(/[\u4e00-\u9fa5]/g) || []).length;
  const other = text.length - chinese;
  return Math.ceil(chinese / 1.5 + other / 4);
}

function detectIntent(messages: CompressMessage[], explicitIntent?: string): string {
  if (explicitIntent && INTENT_KEYWORDS[explicitIntent]) return explicitIntent;

  const text = messages.map((m) => m.content).join(' ').toLowerCase();
  const scores: Record<string, number> = {};
  for (const [intent, keywords] of Object.entries(INTENT_KEYWORDS)) {
    scores[intent] = keywords.reduce((sum, kw) => {
      const count = (text.match(new RegExp(kw.toLowerCase(), 'gi')) || []).length;
      return sum + count;
    }, 0);
  }
  const sorted = Object.entries(scores).sort((a, b) => b[1] - a[1]);
  if (sorted.length === 0 || sorted[0][1] === 0) return 'general';
  return sorted[0][0];
}

function matchKeywords(text: string, keywords: string[]): string[] {
  const lower = text.toLowerCase();
  return keywords.filter((kw) => lower.includes(kw.toLowerCase()));
}

// ============================================================
// ==================== 节点评分 ==============================
// ============================================================

function scoreNode(
  msg: CompressMessage,
  idx: number,
  total: number,
  highlightKws: string[],
): { score: number; keywords: string[]; tokens: number } {
  const tokens = msg.tokens || estimateTokens(msg.content);
  const matchedKws = [
    ...matchKeywords(msg.content, HIGH_VALUE_KWS),
    ...matchKeywords(msg.content, highlightKws),
  ];

  // 1. Token 消耗评分 (0-0.4)：越长内容，越可能重要
  const tokenScore = Math.min(0.4, (tokens / 500) * 0.4);

  // 2. 关键词命中评分 (0-0.4)：命中越多高价值关键词，越重要
  const keywordScore = Math.min(0.4, matchedKws.length * 0.12);

  // 3. 人工标记的重要性 (0-0.2)
  let importanceScore = 0.1;
  if (msg.importance === 'high') importanceScore = 0.2;
  if (msg.importance === 'low') importanceScore = 0.0;

  // 4. 结构性加分
  let structuralScore = 0;
  if (msg.role === 'system') structuralScore -= 0.15;
  if (msg.role === 'tool_call' || msg.role === 'tool_result') structuralScore += 0.05;
  if (msg.decision) structuralScore += 0.15;

  // 5. 首尾节点加分
  if (idx === 0 || idx === total - 1) structuralScore += 0.1;

  const rawScore = tokenScore + keywordScore + importanceScore + structuralScore;
  const finalScore = Math.max(0.05, Math.min(0.98, rawScore));

  return { score: finalScore, keywords: matchedKws, tokens };
}

// ============================================================
// ==================== 主函数：graphCompress =================
// ============================================================

export function graphCompress(options: CompressOptions): CompressResult {
  const t0 = Date.now();
  const {
    messages,
    targetRatio = 0.5,
    intent: explicitIntent,
    highlightKeywords = [],
    minKeepThreshold = 0.4,
  } = options;

  if (!messages || messages.length === 0) {
    throw new Error('[graph-compress] 未提供消息用于压缩');
  }

  // --- Phase 1: 意图检测 ---
  const intent = detectIntent(messages, explicitIntent);

  // --- Phase 2: 构建 B 层（蓝图）---
  const blueprint = {
    id: 'bp_' + t0,
    name: `${intent} - 对话蓝图`,
    components: ['意图识别', '信息获取', '分析/处理', '决策/输出', '总结与下一步'],
    intent,
  };

  // --- Phase 3: 构建 A 层（架构步骤）---
  const archSteps = messages.map((msg, i) => ({
    id: `a_${i}`,
    name: `${msg.role}: ${msg.content.slice(0, 40)}${msg.content.length > 40 ? '...' : ''}`,
    type: msg.importance === 'high' || msg.decision ? 'decision' : 'step',
    score: 0, // 稍后填充
  }));

  // --- Phase 4: 构建 C 层（执行记录）并评分 ---
  const scoredMessages = messages.map((msg, i) => {
    const scored = scoreNode(msg, i, messages.length, highlightKeywords);
    archSteps[i].score = scored.score;
    return {
      ...msg,
      id: msg.id || `msg_${i}`,
      timestamp: msg.timestamp || t0 + i * 1000,
      _score: scored.score,
      _tokens: scored.tokens,
      _keywords: scored.keywords,
    };
  });

  // --- Phase 5: 基于评分压缩 ---
  // 按评分降序排序
  const sortedByScore = [...scoredMessages].sort((a, b) => b._score - a._score);

  // 目标：保留 top-K 个节点，K = max(1, ceil(total * targetRatio))
  const targetKeepCount = Math.max(1, Math.ceil(scoredMessages.length * targetRatio));

  // 找到保留阈值：保留评分前 N 名的节点
  const keepThreshold = sortedByScore[Math.min(targetKeepCount - 1, sortedByScore.length - 1)]._score;

  // 但同时：低于 minKeepThreshold 的节点总是压缩
  // 高于阈值的节点保留
  const nodes = scoredMessages.map((msg) => {
    const shouldKeep = msg._score >= keepThreshold && msg._score >= minKeepThreshold;
    return {
      id: msg.id,
      name: msg.content.slice(0, 60) + (msg.content.length > 60 ? '...' : ''),
      role: msg.role,
      content: msg.content,
      score: msg._score,
      timestamp: msg.timestamp,
      kept: shouldKeep,
      reason: shouldKeep
        ? (msg.importance === 'high' ? '人工标记为重要' : msg.decision ? '关键决策节点' : '高价值评分')
        : '评分低于保留阈值',
      keywords: msg._keywords,
    };
  });

  const kept = nodes.filter((n) => n.kept).sort((a, b) => b.score - a.score);
  const compressed = nodes.filter((n) => !n.kept).sort((a, b) => b.score - a.score);
  const timeline = [...nodes].sort((a, b) => a.timestamp - b.timestamp);

  const avgKeptScore = kept.length > 0
    ? kept.reduce((s, n) => s + n.score, 0) / kept.length
    : 0;
  const avgCompressedScore = compressed.length > 0
    ? compressed.reduce((s, n) => s + n.score, 0) / compressed.length
    : 0;

  const totalTokens = scoredMessages.reduce((s, m) => s + m._tokens, 0);
  const actualRatio = nodes.length > 0 ? kept.length / nodes.length : 1;

  const latencyMs = Date.now() - t0;

  // --- Phase 6: 生成人类可读摘要 ---
  const summaryLines = [
    '========================================',
    '📊 图结构上下文压缩摘要',
    '========================================',
    '',
    `📝 对话消息: ${messages.length} 条`,
    `🧠 检测意图: ${intent}`,
    `💰 估算总 Token: ${totalTokens}`,
    `⚡ 压缩处理耗时: ${latencyMs}ms`,
    '',
    `🎯 目标压缩率: ${(targetRatio * 100).toFixed(0)}%`,
    `📉 实际压缩率: ${(actualRatio * 100).toFixed(0)}% (${kept.length} 保留 / ${compressed.length} 压缩)`,
    `⭐ 保留节点平均评分: ${(avgKeptScore * 100).toFixed(0)}分`,
    `⚪ 压缩节点平均评分: ${(avgCompressedScore * 100).toFixed(0)}分`,
    '',
    '--- 🔒 保留的关键内容（按评分降序，Top 8）---',
  ];
  kept.slice(0, 8).forEach((n, i) => {
    const score = (n.score * 100).toFixed(0).padStart(3, ' ');
    const name = n.name.length > 60 ? n.name.slice(0, 60) + '...' : n.name;
    summaryLines.push(`  ${i + 1}. [${score}分] ${n.role} | ${name}`);
  });
  if (kept.length > 8) summaryLines.push(`  ... 共 ${kept.length} 条保留`);

  summaryLines.push('');
  summaryLines.push('--- 🗜️ 压缩的次要内容（保留引用，Top 5）---');
  compressed.slice(0, 5).forEach((n, i) => {
    const score = (n.score * 100).toFixed(0).padStart(3, ' ');
    const name = n.name.length > 50 ? n.name.slice(0, 50) + '...' : n.name;
    summaryLines.push(`  ${i + 1}. [${score}分] ${n.role} | ${name}`);
  });
  if (compressed.length > 5) summaryLines.push(`  ... 共 ${compressed.length} 条压缩`);

  summaryLines.push('');
  summaryLines.push('--- 📅 执行时间线（节点状态）---');
  timeline.slice(0, 10).forEach((item) => {
    const status = item.kept ? '✓ KEEP   ' : '✗ COMPRESS';
    const score = (item.score * 100).toFixed(0).padStart(3, ' ');
    const name = item.name.slice(0, 50);
    summaryLines.push(`  ${status} [${score}分] ${name}`);
  });
  if (timeline.length > 10) summaryLines.push(`  ... 共 ${timeline.length} 条`);

  summaryLines.push('');
  summaryLines.push('--- 🧩 三层图结构 ---');
  summaryLines.push(`  B 层 Blueprint: ${blueprint.components.length} 个组件`);
  summaryLines.push(`     → ${blueprint.components.join(' → ')}`);
  summaryLines.push(`  A 层 Architecture: ${archSteps.length} 个步骤`);
  summaryLines.push(`  C 层 Chronicle: ${nodes.length} 个执行节点 (压缩后 ${kept.length} 个)`);

  summaryLines.push('');
  summaryLines.push('✨ 压缩完成 - 关键信息已保留，次要内容已压缩为引用');
  summaryLines.push('========================================');

  // --- Phase 7: 构建可视化数据 ---
  const viz = {
    layerBefore: {
      blueprint: blueprint.components.length,
      architecture: archSteps.length,
      chronicle: nodes.length,
    },
    layerAfter: {
      blueprint: blueprint.components.length,
      architecture: Math.max(1, Math.ceil(archSteps.length * targetRatio)),
      chronicle: kept.length,
    },
    nodesByStatus: {
      kept: kept.length,
      compressed: compressed.length,
    },
    compressionRatio: actualRatio,
  };

  return {
    summary: {
      totalMessages: messages.length,
      keptCount: kept.length,
      compressedCount: compressed.length,
      compressionRatio: actualRatio,
      avgKeptScore,
      avgCompressedScore,
      intentDetected: intent,
      totalTokens,
      latencyMs,
    },
    kept,
    compressed,
    timeline,
    blueprint,
    architecture: {
      id: 'arch_' + t0,
      steps: archSteps,
    },
    visualization: viz,
    textSummary: summaryLines.join('\n'),
  };
}

// ============================================================
// ==================== CLI 入口（可选）======================
// ============================================================

if (typeof process !== 'undefined' && process.argv && process.argv[1]?.includes('graph-compress.ts')) {
  const demoMessages: CompressMessage[] = [
    { id: '1', role: 'user', content: '帮我分析 BTC 行情，是否适合买入', timestamp: Date.now() },
    { id: '2', role: 'assistant', content: '好的，我先获取市场数据...', timestamp: Date.now() + 1000 },
    { id: '3', role: 'user', content: '关键决策：在 64800 买入，止损 64200，仓位 3%', importance: 'high', timestamp: Date.now() + 2000 },
    { id: '4', role: 'assistant', content: '已确认执行方案', timestamp: Date.now() + 3000 },
  ];
  const result = graphCompress({ messages: demoMessages, targetRatio: 0.5 });
  console.log(result.textSummary);
  console.log('\n--- DEBUG: 保留节点 ---');
  result.kept.forEach((n) => console.log(`  [${(n.score * 100).toFixed(0)}分] ${n.name}`));
  console.log('\n--- DEBUG: 压缩节点 ---');
  result.compressed.forEach((n) => console.log(`  [${(n.score * 100).toFixed(0)}分] ${n.name}`));
}
