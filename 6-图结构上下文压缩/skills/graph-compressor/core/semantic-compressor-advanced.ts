/**
 * ============================================================
 *  🗜️  增强版 - 语义感知压缩引擎
 * ============================================================
 *
 *  核心区别于 graph-compress.ts：
 *    graph-compress.ts → 简单的关键词 + importance 评分（快速）
 *    semanic-compressor-advanced.ts → 完整 TF-IDF + 信息熵 + 语义标签（精确）
 *
 *  评分机制（100 分制）：
 *    • TF-IDF 独特度   25%  - 内容独特性（稀有词汇）
 *    • 关键词命中      25%  - 交易/风险/决策等领域关键词
 *    • 信息熵          15%  - 文本信息量（词汇多样性）
 *    • 语义标签        15%  - 内容分类（决策/分析/数据等）
 *    • 元数据加权      20%  - role/importance/tokens 等
 *
 *  输出：
 *    • 压缩后节点列表（kept）
 *    • 每个节点的详细评分 breakdown
 *    • 全局语义统计（词云 / 主题分布）
 *    • 三层图结构（Blueprint/Architecture/Chronicle）
 */

import { type CompressMessage, type CompressedNode, type CompressResult } from './graph-compress.ts';

// ============================================================
// ==================== 语义配置 ==============================
// ============================================================

// 扩展关键词桶（更多分类 + 更广覆盖）
const SEMANTIC_BUCKETS = {
  decision: {
    weight: 1.5,
    keywords: ['决策', '确认', '执行', '方案', '建议', '最终', '结论', '决定',
               '已确认', '就按', 'recommend', 'decision', 'execute', 'confirm',
               '入场', '止损', '止盈', '仓位', '买入', '卖出', 'buy', 'sell'],
  },
  risk: {
    weight: 1.3,
    keywords: ['风险', '止损', '止盈', '回撤', '杠杆', '保证金', '风控',
               '风险收益比', '夏普', '胜率', '最大回撤', '爆仓', '流动性',
               'risk', 'stop-loss', 'take-profit', 'leverage', 'margin'],
  },
  analysis: {
    weight: 1.2,
    keywords: ['分析', '研究', '调研', '行情', '趋势', '数据', '指标',
               'RSI', 'MACD', 'KDJ', '布林带', '均线', '支撑', '阻力', '背离', '突破',
               '基本面', '技术面', '估值', 'PE', 'PB', '市值', 'volume', 'price',
               'trend', 'analysis', 'market', 'signal'],
  },
  strategy: {
    weight: 1.1,
    keywords: ['策略', '设计', '优化', '回测', '参数', '信号', '触发',
               '策略验证', '策略优化', 'strategy', 'backtest', 'design',
               'pattern', '突破', '跟随', '反转', '动量', '均值回归'],
  },
  data: {
    weight: 1.0,
    keywords: ['价格', '行情', '市值', '成交量', '成交额', '数据', '实时',
               'history', 'historical', 'price', 'volume', 'market cap'],
  },
  introspect: {
    weight: 1.1,
    keywords: ['置信度', '不确定', '反思', '自省', 'recheck', 'confidence',
               '可能', '也许', '需要验证', '假设', 'uncertain'],
  },
  coding: {
    weight: 0.9,
    keywords: ['代码', '实现', '开发', 'bug', '修复', '组件', '模块',
               'code', 'implement', 'dev', 'fix', 'build', 'script', 'test'],
  },
  compression: {
    weight: 0.9,
    keywords: ['压缩', '总结', '摘要', '上下文', '图结构', '节点', '保留',
               'compress', 'summary', 'context', 'graph', 'node'],
  },
  scheduling: {
    weight: 0.9,
    keywords: ['调度', '跳过', '决策', '优先级', '执行计划', 'skip',
               'schedule', 'priority', 'gate'],
  },
} as const;

// 语义标签（自动给每个节点打标签）
const SEMANTIC_TAGS = {
  DECISION: { weight: 1.5, keywords: ['执行', '确认', '已确认', '入场', '止损', '止盈', '方案', '决定'] },
  ANALYSIS: { weight: 1.2, keywords: ['分析', '研究', 'RSI', 'MACD', '均线', '趋势', '行情'] },
  DATA: { weight: 1.0, keywords: ['数据', '行情', '价格', '市值', '成交量', '实时'] },
  QUESTION: { weight: 0.8, keywords: ['吗？', '如何', '什么', '为什么', '请问', '?', '？'] },
  STRATEGY: { weight: 1.1, keywords: ['策略', '回测', '参数', '信号', '优化'] },
  RISK: { weight: 1.3, keywords: ['风险', '止损', '杠杆', '回撤', '保证金'] },
  CONTEXT: { weight: 0.6, keywords: ['回顾', '之前', '前面', '刚刚', '之前说的'] },
} as const;

// 停用词（扩展版）
const STOPWORDS = new Set([
  '的', '了', '是', '在', '我', '有', '和', '就', '不', '人', '都', '一', '一个',
  '上', '也', '很', '到', '说', '要', '去', '你', '会', '着', '没有', '看', '好',
  '自己', '这', '那', '还', '但', '与', '及', '等', '或', '而', '的话', '可以',
  '可能', '应该', '这个', '那个', '然后', '但是', '就是', '我们', '你们',
  'the', 'a', 'an', 'is', 'are', 'was', 'were', 'be', 'to', 'of', 'and', 'in',
  'for', 'on', 'with', 'that', 'this', 'it', 'as', 'at', 'by', 'from', 'or',
  'can', 'could', 'should', 'would', 'will', 'may', 'might', 'must',
]);

// ============================================================
// ==================== 工具函数 ==============================
// ============================================================

interface TokenizerResult {
  tokens: string[];
  tokenFreq: Map<string, number>;
  uniqueCount: number;
  totalCount: number;
}

function tokenize(text: string): TokenizerResult {
  const tokens: string[] = [];
  const freq = new Map<string, number>();

  if (!text) return { tokens, tokenFreq: freq, uniqueCount: 0, totalCount: 0 };

  const lower = text.toLowerCase();

  // 英文/数字
  const asciiMatches = lower.match(/[a-z0-9_]{2,}/g);
  if (asciiMatches) {
    asciiMatches.forEach((t) => {
      if (!STOPWORDS.has(t)) {
        tokens.push(t);
        freq.set(t, (freq.get(t) || 0) + 1);
      }
    });
  }

  // 中文 n-gram
  const chineseParts = lower.match(/[\u4e00-\u9fa5]+/g) || [];
  chineseParts.forEach((part) => {
    if (part.length <= 2) {
      if (!STOPWORDS.has(part)) {
        tokens.push(part);
        freq.set(part, (freq.get(part) || 0) + 1);
      }
    } else {
      for (let i = 0; i <= part.length - 2; i++) {
        const token = part.slice(i, i + 2);
        if (!STOPWORDS.has(token)) {
          tokens.push(token);
          freq.set(token, (freq.get(token) || 0) + 1);
        }
      }
    }
  });

  return {
    tokens,
    tokenFreq: freq,
    uniqueCount: freq.size,
    totalCount: tokens.length,
  };
}

// ============================================================
// ==================== TF-IDF 计算 ===========================
// ============================================================

interface TfIdfResult {
  scores: Map<string, number>; // nodeId → tf-idf 总分
  perNodeTopTerms: Map<string, Array<{ term: string; score: number }>>;
  globalVocab: Array<{ term: string; idf: number; freq: number }>;
}

function computeTfIdf(
  messages: Array<{ id: string; text: string }>
): TfIdfResult {
  const scores = new Map<string, number>();
  const perNodeTop = new Map<string, Array<{ term: string; score: number }>>();

  // Step 1: 每个节点的 token + TF
  const nodeTokens: Array<{ id: string; tokenizer: TokenizerResult }> =
    messages.map((m) => ({ id: m.id, tokenizer: tokenize(m.text) }));

  // Step 2: 全局 DF（每个 token 出现在多少个节点中）
  const docFreq = new Map<string, number>();
  nodeTokens.forEach(({ tokenizer }) => {
    const unique = new Set(tokenizer.tokens);
    unique.forEach((t) => {
      docFreq.set(t, (docFreq.get(t) || 0) + 1);
    });
  });

  const totalDocs = messages.length;
  const vocab: Array<{ term: string; idf: number; freq: number }> = [];
  docFreq.forEach((freq, term) => {
    const idf = Math.log((totalDocs + 1) / (freq + 1)) + 1; // +1 平滑
    vocab.push({ term, idf, freq });
  });
  vocab.sort((a, b) => b.idf * b.freq - a.idf * a.freq);

  // Step 3: 每个节点的 TF-IDF 总分 + top terms
  nodeTokens.forEach(({ id, tokenizer }) => {
    let total = 0;
    const topTerms: Array<{ term: string; score: number }> = [];
    tokenizer.tokenFreq.forEach((tf, term) => {
      const idf = Math.log((totalDocs + 1) / ((docFreq.get(term) || 0) + 1)) + 1;
      const score = tf * idf;
      total += score;
      topTerms.push({ term, score });
    });
    topTerms.sort((a, b) => b.score - a.score);
    scores.set(id, total);
    perNodeTop.set(id, topTerms.slice(0, 5));
  });

  return { scores, perNodeTopTerms: perNodeTop, globalVocab: vocab.slice(0, 30) };
}

// ============================================================
// ==================== 信息熵计算 ============================
// ============================================================

function computeEntropy(tokenizer: TokenizerResult): number {
  if (tokenizer.totalCount === 0) return 0;

  let entropy = 0;
  tokenizer.tokenFreq.forEach((freq) => {
    const p = freq / tokenizer.totalCount;
    if (p > 0) entropy -= p * Math.log2(p);
  });

  // 归一化：最大熵是 log2(uniqueCount)，但用一个宽松上限
  const maxEntropy = Math.log2(Math.min(tokenizer.uniqueCount + 1, 100));
  return maxEntropy > 0 ? Math.min(1, entropy / maxEntropy) : 0;
}

// ============================================================
// ==================== 语义标签 ==============================
// ============================================================

function detectTags(text: string): Array<{ tag: string; score: number; matched: string[] }> {
  const results: Array<{ tag: string; score: number; matched: string[] }> = [];
  const lowerText = text.toLowerCase();

  for (const [tag, info] of Object.entries(SEMANTIC_TAGS)) {
    const matched: string[] = [];
    const tagConfig = info as { weight: number; keywords: string[] };
    tagConfig.keywords.forEach((kw) => {
      if (lowerText.includes(kw.toLowerCase())) matched.push(kw);
    });
    if (matched.length > 0) {
      results.push({
        tag,
        score: Math.min(1, matched.length * tagConfig.weight * 0.3),
        matched,
      });
    }
  }

  results.sort((a, b) => b.score - a.score);
  return results.slice(0, 3);
}

// ============================================================
// ==================== 关键词命中 ============================
// ============================================================

function computeKeywordScore(text: string): {
  score: number;
  matchedBuckets: string[];
  hitDetails: Array<{ bucket: string; hits: number; weight: number }>;
} {
  const lowerText = text.toLowerCase();
  let totalScore = 0;
  const matchedBuckets: string[] = [];
  const hitDetails: Array<{ bucket: string; hits: number; weight: number }> = [];

  for (const [bucket, info] of Object.entries(SEMANTIC_BUCKETS)) {
    const bucketConfig = info as { weight: number; keywords: string[] };
    let hits = 0;
    bucketConfig.keywords.forEach((kw) => {
      if (lowerText.includes(kw.toLowerCase())) hits += 1;
    });
    if (hits > 0) {
      const bucketScore = Math.min(1, hits * bucketConfig.weight * 0.25);
      totalScore += bucketScore;
      matchedBuckets.push(bucket);
      hitDetails.push({ bucket, hits, weight: bucketConfig.weight });
    }
  }

  return {
    score: Math.min(1, totalScore),
    matchedBuckets,
    hitDetails,
  };
}

// ============================================================
// ==================== 完整评分 ==============================
// ============================================================

export interface SemanticScoredNode extends CompressedNode {
  semanticBreakdown: {
    tfIdf: number;
    keyword: number;
    entropy: number;
    tag: number;
    metadata: number;
  };
  tags: Array<{ tag: string; score: number; matched: string[] }>;
  topTerms: Array<{ term: string; score: number }>;
}

export interface SemanticCompressResult extends CompressResult {
  semanticNodes: SemanticScoredNode[];
  globalStats: {
    totalVocab: number;
    topGlobalTerms: Array<{ term: string; idf: number; freq: number }>;
    tagDistribution: Record<string, number>;
    bucketHits: Record<string, number>;
    avgTfIdf: number;
  };
  threeLayer: {
    blueprint: {
      id: string;
      name: string;
      description: string;
      components: string[];
      topTags: string[];
    };
    architecture: Array<{
      id: string;
      name: string;
      type: string;
      score: number;
      tags: string[];
      dependsOn: string[];
    }>;
    chronicle: Array<{
      id: string;
      name: string;
      score: number;
      status: 'kept' | 'compressed';
      tag: string;
    }>;
  };
}

export interface SemanticCompressOptions {
  messages: CompressMessage[];
  targetRatio?: number;         // 默认 0.5
  minKeepThreshold?: number;    // 默认 0.3
  weights?: {                   // 各维度权重（可覆盖）
    tfIdf: number;
    keyword: number;
    entropy: number;
    tag: number;
    metadata: number;
  };
}

export function semanticCompress(options: SemanticCompressOptions): SemanticCompressResult {
  const start = Date.now();
  const {
    messages,
    targetRatio = 0.5,
    minKeepThreshold = 0.3,
    weights = { tfIdf: 0.25, keyword: 0.25, entropy: 0.15, tag: 0.15, metadata: 0.20 },
  } = options;

  // 预处理文本
  const textItems = messages.map((m) => ({
    id: m.id,
    text: `${m.content}${m.decision ? ' | ' + m.decision : ''}${m.toolName ? ' | tool:' + m.toolName : ''}`,
  }));

  // 1. TF-IDF
  const tfIdfResult = computeTfIdf(textItems);
  const maxTfIdf = Math.max(...Array.from(tfIdfResult.scores.values()), 1);

  // 2. 所有节点的评分
  const tagDistribution: Record<string, number> = {};
  const bucketHits: Record<string, number> = {};
  const scoredNodes: SemanticScoredNode[] = messages.map((m) => {
    const text = `${m.content}${m.decision ? ' | ' + m.decision : ''}`;
    const tokenizer = tokenize(text);

    // 维度 1: TF-IDF (0-1)
    const rawTfIdf = tfIdfResult.scores.get(m.id) || 0;
    const normTfIdf = rawTfIdf / maxTfIdf;

    // 维度 2: 关键词命中 (0-1)
    const kwResult = computeKeywordScore(text);
    kwResult.hitDetails.forEach((d) => {
      bucketHits[d.bucket] = (bucketHits[d.bucket] || 0) + d.hits;
    });

    // 维度 3: 信息熵 (0-1)
    const entropy = computeEntropy(tokenizer);

    // 维度 4: 语义标签 (0-1)
    const tags = detectTags(text);
    tags.forEach((t) => {
      tagDistribution[t.tag] = (tagDistribution[t.tag] || 0) + 1;
    });
    const tagScore = tags.length > 0 ? Math.min(1, tags[0].score + tags.slice(1).reduce((s, t) => s + t.score * 0.5, 0)) : 0;

    // 维度 5: 元数据加权 (0-1)
    let metadataScore = 0.3;
    if (m.importance === 'high') metadataScore += 0.5;
    else if (m.importance === 'medium') metadataScore += 0.2;
    if (m.role === 'assistant') metadataScore += 0.1;
    if (m.decision) metadataScore += 0.2;
    if (m.toolName) metadataScore += 0.1;
    metadataScore = Math.min(1, metadataScore);

    // 加权融合
    const finalScore =
      normTfIdf * weights.tfIdf +
      kwResult.score * weights.keyword +
      entropy * weights.entropy +
      tagScore * weights.tag +
      metadataScore * weights.metadata;

    return {
      id: m.id,
      name: `${m.role}: ${m.content.slice(0, 50)}${m.content.length > 50 ? '...' : ''}`,
      role: m.role,
      content: m.content,
      score: finalScore,
      timestamp: m.timestamp || Date.now(),
      kept: false,
      keywords: kwResult.matchedBuckets,
      semanticBreakdown: {
        tfIdf: normTfIdf,
        keyword: kwResult.score,
        entropy,
        tag: tagScore,
        metadata: metadataScore,
      },
      tags,
      topTerms: tfIdfResult.perNodeTopTerms.get(m.id) || [],
    };
  });

  // 3. 排序并决定保留/压缩
  scoredNodes.sort((a, b) => b.score - a.score);
  const totalMessages = messages.length;
  const keepCount = Math.max(1, Math.round(totalMessages * (1 - targetRatio)));
  const keepThreshold = Math.max(minKeepThreshold, scoredNodes[keepCount - 1]?.score || 0.5);

  scoredNodes.forEach((node, idx) => {
    if (node.score >= keepThreshold && idx < totalMessages) node.kept = true;
    // 补充 reason
    const reasons: string[] = [];
    if (node.semanticBreakdown.keyword > 0.4) reasons.push('高关键词命中');
    if (node.semanticBreakdown.tfIdf > 0.4) reasons.push('内容独特');
    if (node.semanticBreakdown.metadata > 0.6) reasons.push('标记为重要');
    node.reason = node.kept
      ? (reasons.join('、') || '综合评分达标')
      : '低于压缩阈值';
  });

  const kept = scoredNodes.filter((n) => n.kept).sort((a, b) => a.timestamp - b.timestamp);
  const compressed = scoredNodes.filter((n) => !n.kept).sort((a, b) => a.timestamp - b.timestamp);

  // 4. 三层图结构
  const topTags = Object.entries(tagDistribution)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 5)
    .map(([tag]) => tag);

  const blueprint = {
    id: `bp_${Date.now()}`,
    name: `对话蓝图（${topTags[0] || '通用'}主题）`,
    description: `基于 ${totalMessages} 条消息的三层图结构，覆盖 ${topTags.join('、') || '多个'}主题`,
    components: topTags,
    topTags,
  };

  const architecture = kept.slice(0, 10).map((node, idx) => ({
    id: `arch_${idx}`,
    name: node.name,
    type: node.tags[0]?.tag || 'STEP',
    score: node.score,
    tags: node.tags.map((t) => t.tag),
    dependsOn: idx > 0 ? [`arch_${idx - 1}`] : [],
  }));

  const chronicle = scoredNodes.map((node, idx) => ({
    id: `chron_${idx}`,
    name: node.name,
    score: node.score,
    status: node.kept ? 'kept' as const : 'compressed' as const,
    tag: node.tags[0]?.tag || 'GENERIC',
  }));

  // 5. 全局统计
  const avgTfIdf = scoredNodes.reduce((s, n) => s + n.semanticBreakdown.tfIdf, 0) / scoredNodes.length;

  const latency = Date.now() - start;
  return {
    summary: {
      totalMessages,
      keptCount: kept.length,
      compressedCount: compressed.length,
      compressionRatio: compressed.length / totalMessages,
      avgKeptScore: kept.reduce((s, n) => s + n.score, 0) / kept.length,
      avgCompressedScore: compressed.length > 0 ? compressed.reduce((s, n) => s + n.score, 0) / compressed.length : 0,
      intentDetected: topTags[0] || 'general',
      totalTokens: messages.reduce((s, m) => s + (m.tokens || Math.ceil(m.content.length / 4)), 0),
      latencyMs: latency,
    },
    kept,
    compressed,
    timeline: [...scoredNodes].sort((a, b) => a.timestamp - b.timestamp),
    blueprint: {
      id: blueprint.id,
      name: blueprint.name,
      components: blueprint.components,
      intent: topTags[0] || 'general',
    },
    architecture: {
      id: `arch_${Date.now()}`,
      steps: architecture.map((a) => ({ id: a.id, name: a.name, type: a.type, score: a.score })),
    },
    visualization: {
      layerBefore: { blueprint: 1, architecture: architecture.length, chronicle: totalMessages },
      layerAfter: { blueprint: 1, architecture: architecture.length, chronicle: kept.length },
    },
    semanticNodes: scoredNodes,
    globalStats: {
      totalVocab: tfIdfResult.globalVocab.length,
      topGlobalTerms: tfIdfResult.globalVocab.slice(0, 15),
      tagDistribution,
      bucketHits,
      avgTfIdf,
    },
    threeLayer: {
      blueprint,
      architecture,
      chronicle,
    },
  } as SemanticCompressResult;
}

// ============================================================
// ==================== CLI 演示 ==============================
// ============================================================

if (typeof process !== 'undefined' && process.argv && process.argv[1]?.includes('semantic-compressor-advanced.ts')) {
  console.log('='.repeat(70));
  console.log('🗜️  增强语义感知压缩 - 演示模式');
  console.log('='.repeat(70));

  const demoMsgs: CompressMessage[] = [
    { id: 'u1', role: 'user', content: '帮我分析 BTC 的短线交易机会', timestamp: Date.now() - 10000 },
    { id: 'a1', role: 'assistant', content: 'BTC 当前价格 65,200 USDT，RSI 55，MACD 金叉，均线多头排列，趋势向上。技术面中性偏强。', timestamp: Date.now() - 9000 },
    { id: 'u2', role: 'user', content: '入场和止损应该怎么设置？', timestamp: Date.now() - 8000 },
    { id: 'a2', role: 'assistant', content: '建议：入场 64,800（回调支撑位），止损 64,200（近期低点下方），第一止盈 65,800。风险收益比约 1:1.67。', importance: 'high', timestamp: Date.now() - 7000 },
    { id: 'u3', role: 'user', content: '仓位呢？用多大杠杆比较合适？', timestamp: Date.now() - 6000 },
    { id: 'a3', role: 'assistant', content: '资金管理建议：仓位总资金的 3%，不超过 5x 杠杆。这是一个中等风险、胜率可接受的配置。', importance: 'high', timestamp: Date.now() - 5000 },
    { id: 'u4', role: 'user', content: '有没有历史回测验证？', timestamp: Date.now() - 4000 },
    { id: 'a4', role: 'assistant', content: '快速回测：过去 30 天类似信号出现 7 次，胜率 71%，平均持仓 3.2 天，最大回撤 4.2%。整体表现稳健。', timestamp: Date.now() - 3000 },
    { id: 'u5', role: 'user', content: '好的，那就按这个方案执行。', importance: 'high', timestamp: Date.now() - 2000 },
    { id: 'a5', role: 'assistant', content: '✅ 已确认方案，等待 BTC 价格触发入场条件。执行参数：入场 64,800 / 止损 64,200 / 止盈 65,800 / 仓位 3%。', importance: 'high', timestamp: Date.now() - 1000 },
  ];

  const result = semanticCompress({
    messages: demoMsgs,
    targetRatio: 0.5,
  });

  console.log(`\n📊 压缩统计:`);
  console.log(`   总消息: ${result.summary.totalMessages}`);
  console.log(`   保留: ${result.summary.keptCount} | 压缩: ${result.summary.compressedCount}`);
  console.log(`   压缩率: ${(result.summary.compressionRatio * 100).toFixed(0)}%`);
  console.log(`   平均保留评分: ${(result.summary.avgKeptScore * 100).toFixed(0)}/100`);
  console.log(`   平均压缩评分: ${(result.summary.avgCompressedScore * 100).toFixed(0)}/100`);
  console.log(`   意图: ${result.summary.intentDetected}`);
  console.log(`   耗时: ${result.summary.latencyMs}ms`);

  console.log(`\n🏷️  语义标签分布:`);
  Object.entries(result.globalStats.tagDistribution).forEach(([tag, count]) => {
    const bar = '█'.repeat(Math.min(count * 3, 40));
    console.log(`   ${tag.padEnd(12)} ${bar} ${count}`);
  });

  console.log(`\n🔑 关键词桶命中:`);
  Object.entries(result.globalStats.bucketHits).slice(0, 6).forEach(([bucket, hits]) => {
    const bar = '█'.repeat(Math.min(hits * 2, 30));
    console.log(`   ${bucket.padEnd(12)} ${bar} ${hits}`);
  });

  console.log(`\n📝 Top 10 全局高权重词汇 (TF-IDF):`);
  result.globalStats.topGlobalTerms.slice(0, 10).forEach((term, i) => {
    console.log(`   ${i + 1}. ${term.term.padEnd(15)} idf=${term.idf.toFixed(2)} freq=${term.freq}`);
  });

  console.log(`\n⭐ 保留的关键节点（带评分 breakdown）:`);
  result.kept.slice(0, 5).forEach((node, i) => {
    const bd = node.semanticBreakdown;
    console.log(`\n  ${i + 1}. [${(node.score * 100).toFixed(0)}分] ${node.name.slice(0, 60)}`);
    console.log(`     TF-IDF:${(bd.tfIdf * 100).toFixed(0)} 关键词:${(bd.keyword * 100).toFixed(0)} 熵:${(bd.entropy * 100).toFixed(0)} 标签:${(bd.tag * 100).toFixed(0)} 元数据:${(bd.metadata * 100).toFixed(0)}`);
    if (node.tags.length > 0) console.log(`     标签: ${node.tags.map((t) => t.tag).join('、')}`);
    if (node.keywords && node.keywords.length > 0) console.log(`     主题: ${node.keywords.join('、')}`);
  });

  console.log(`\n📦 压缩丢弃的节点（示例 3 个）:`);
  result.compressed.slice(0, 3).forEach((node, i) => {
    console.log(`  ${i + 1}. [${(node.score * 100).toFixed(0)}分] ${node.name.slice(0, 50)} - ${node.reason}`);
  });

  console.log('\n' + '='.repeat(70));
  console.log('✅ 语义感知压缩演示完成');
  console.log('='.repeat(70));
}
