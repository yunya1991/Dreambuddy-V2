/**
 * 语义感知压缩 — 基于内容的语义重要性评分
 *
 * 核心思路（不用额外依赖）：
 *   1. 对每个 Chronicle 节点提取文本（outputSummary + inputs/outputs keys）
 *   2. 构建全局 TF-IDF 词汇表（token-level）
 *   3. 计算每个节点的语义重要度：
 *        - 独特度（TF-IDF 高的词汇出现次数多 → 有独特信息）
 *        - 关键词命中（策略、止损、风险、信号 等交易领域关键词）
 *        - 信息熵（词汇多样性）
 *   4. 与原始评分（token、耗时、结构位置）融合，生成最终评分
 *
 * 相比原有 compress()：语义压缩能识别"内容稀疏但决策关键"的节点，
 * 也能识别"文本很多但都是重复上下文"的冗余节点。
 */

import {
  ChronicleGraph,
  ArchitectureGraph,
  BlueprintGraph,
  CompressionResult,
  NodeId,
} from './types';

// ============ 关键词：交易/决策/分析领域 ============
const KEYWORD_BUCKETS = {
  strategy: ['策略', '买入', '卖出', '加仓', '减仓', '平仓', '持仓', '方向', '多', '空', 'buy', 'sell', 'long', 'short'],
  risk: ['风险', '止损', '止盈', '回撤', '杠杆', '保证金', '风控', 'risk', 'stop', 'loss'],
  analysis: ['RSI', 'MACD', 'KDJ', '布林带', '趋势', '均线', '支撑', '阻力', '背离', '突破', 'signal', 'trend'],
  decision: ['决策', '结论', '建议', '最终', '结论是', 'recommend', 'decision'],
  data: ['数据', '行情', '价格', '市值', '成交量', 'volume', 'price', 'market'],
  introspect: ['自省', '反思', '置信度', '不确定', 'recheck', 'confidence'],
};

// 中文停用词（非常简化版，只过滤最常见的）
const CH_STOPWORDS = new Set([
  '的', '了', '是', '在', '我', '有', '和', '就', '不', '人', '都', '一', '一个',
  '上', '也', '很', '到', '说', '要', '去', '你', '会', '着', '没有', '看', '好',
  '自己', '这', '那', '还', '但', '与', '及', '等', '或', '等', '而', '的话',
  'the', 'a', 'an', 'is', 'are', 'was', 'were', 'be', 'to', 'of', 'and', 'in',
]);

// ============ 工具：文本提取 ============

function extractTextFromNode(node: {
  metadata: { outputSummary?: string; tags?: string[] };
  inputs: Record<string, any>;
  outputs: Record<string, any>;
  logs: string[];
}): string {
  const parts: string[] = [];
  if (node.metadata?.outputSummary) parts.push(node.metadata.outputSummary);
  if (node.metadata?.tags?.length) parts.push(node.metadata.tags.join(' '));
  const ioKeys = [
    ...Object.keys(node.inputs || {}),
    ...Object.keys(node.outputs || {}),
  ];
  ioKeys.forEach((k) => {
    const v = (node.inputs as any)[k] ?? (node.outputs as any)[k];
    if (typeof v === 'string') parts.push(v);
    else if (v && typeof v === 'object') parts.push(JSON.stringify(v).slice(0, 500));
  });
  if (node.logs?.length) parts.push(node.logs.slice(0, 3).join(' '));
  return parts.join(' ').slice(0, 2000);
}

// ============ 工具：简易分词 ============

function tokenize(text: string): string[] {
  if (!text) return [];
  const lower = text.toLowerCase();
  const tokens: string[] = [];

  // 英文/数字用 \w+ 分词
  const asciiMatches = lower.match(/[a-z0-9_]{2,}/g);
  if (asciiMatches) tokens.push(...asciiMatches);

  // 中文取 2-4 字子串（简单 n-gram 替代中文分词）
  const chineseParts = lower.match(/[\u4e00-\u9fa5]+/g) || [];
  chineseParts.forEach((part) => {
    if (part.length <= 2) tokens.push(part);
    else {
      for (let i = 0; i <= part.length - 2; i++) {
        tokens.push(part.slice(i, i + 2));
      }
    }
  });

  return tokens.filter((t) => !CH_STOPWORDS.has(t) && t.length >= 2);
}

// ============ 语义评分 ============

/** 关键词命中数 */
function scoreKeywordHits(tokens: string[]): number {
  let score = 0;
  const tokenSet = new Set(tokens);
  Object.values(KEYWORD_BUCKETS).forEach((bucket) => {
    const hit = bucket.some((kw) => tokenSet.has(kw.toLowerCase()));
    if (hit) score += 1;
  });
  // 归一化到 0-1（6 个桶 → /6）
  return Math.min(1, score / 6);
}

/** 构建 TF-IDF 并返回每个节点的 tf-idf 得分（0-1） */
function buildTfIdfScores(
  docs: { nodeId: string; tokens: string[] }[]
): Map<NodeId, number> {
  const docFreq = new Map<string, number>();
  const termFreq: Record<string, number[]> = {};

  // 统计 DF（有多少篇文档包含该词）
  docs.forEach((doc) => {
    const seen = new Set(doc.tokens);
    seen.forEach((t) => docFreq.set(t, (docFreq.get(t) || 0) + 1));
  });

  const N = Math.max(1, docs.length);
  const result = new Map<NodeId, number>();

  docs.forEach((doc, idx) => {
    const freq = new Map<string, number>();
    doc.tokens.forEach((t) => freq.set(t, (freq.get(t) || 0) + 1));
    let tfidf = 0;
    let uniqueTerms = 0;
    freq.forEach((count, term) => {
      const tf = count / Math.max(1, doc.tokens.length);
      const idf = Math.log(N / (docFreq.get(term) || 1));
      tfidf += tf * idf;
      uniqueTerms++;
    });
    // 归一化：除以独特 term 数，避免长文本占优
    const normalized = uniqueTerms > 0 ? tfidf / Math.sqrt(uniqueTerms) : 0;
    result.set(doc.nodeId, normalized);
  });

  // 再做 0-1 归一化（所有节点之间）
  let maxScore = 0;
  result.forEach((v) => { if (v > maxScore) maxScore = v; });
  if (maxScore > 0) {
    result.forEach((v, id) => result.set(id, v / maxScore));
  }
  return result;
}

/** 信息熵（衡量词汇多样性） */
function scoreEntropy(tokens: string[]): number {
  if (tokens.length === 0) return 0;
  const freq = new Map<string, number>();
  tokens.forEach((t) => freq.set(t, (freq.get(t) || 0) + 1));
  let entropy = 0;
  freq.forEach((count) => {
    const p = count / tokens.length;
    if (p > 0) entropy -= p * Math.log2(p);
  });
  // max entropy = log2(n)，归一化
  const maxEntropy = Math.log2(Math.max(1, freq.size));
  return maxEntropy > 0 ? entropy / maxEntropy : 0;
}

// ============ 主算法：语义感知版 compress ============

export interface SemanticCompressionOptions {
  targetRatio?: number;
  /** 语义权重占比（0-1），默认 0.4（剩下 0.6 走原元数据评分） */
  semanticWeight?: number;
  /** 关键词权重（在语义内部的权重） */
  keywordBias?: number;
  /** 最小保留节点数 */
  minNodes?: number;
  /** 是否保留所有边 */
  keepAllEdges?: boolean;
}

/** 执行语义感知压缩：返回 CompressionResult（与 compress() 同接口） */
export function semanticCompress(
  chronicle: ChronicleGraph,
  architecture: ArchitectureGraph,
  blueprint: BlueprintGraph,
  options: SemanticCompressionOptions = {}
): CompressionResult {
  const targetRatio = options.targetRatio ?? 0.5;
  const semanticWeight = options.semanticWeight ?? 0.4;
  const keywordBias = options.keywordBias ?? 0.5; // 关键词/TF-IDF 的比例
  const minNodes = options.minNodes ?? 1;
  const keepAllEdges = options.keepAllEdges ?? false;

  // -------- 第一步：提取每个节点的文本/分词 --------
  const docs: { nodeId: string; tokens: string[]; node: any }[] = [];
  chronicle.nodes.forEach((node, id) => {
    const text = extractTextFromNode(node);
    docs.push({ nodeId: id, tokens: tokenize(text), node });
  });

  // -------- 第二步：计算 TF-IDF / 关键词 / 熵 --------
  const tfidfScores = buildTfIdfScores(docs);
  const keywordScores = new Map<NodeId, number>();
  const entropyScores = new Map<NodeId, number>();

  docs.forEach(({ nodeId, tokens }) => {
    keywordScores.set(nodeId, scoreKeywordHits(tokens));
    entropyScores.set(nodeId, scoreEntropy(tokens));
  });

  // -------- 第三步：计算每个节点的综合评分 --------
  // 结构 + Token（复用原逻辑，但简化）
  const maxTokenCost = Math.max(1, ...docs.map((d) => d.node.metadata?.tokenCost || 0));
  const maxLatency = Math.max(1, ...docs.map((d) => d.node.metadata?.latencyMs || 0));

  const finalScores = new Map<NodeId, number>();
  docs.forEach(({ nodeId, node }) => {
    const metaScore =
      0.5 * ((node.metadata?.tokenCost || 0) / maxTokenCost) +
      0.3 * ((node.metadata?.latencyMs || 0) / maxLatency) +
      0.2; // 结构 baseline

    const semanticScore =
      keywordBias * (keywordScores.get(nodeId) || 0) +
      (1 - keywordBias) * 0.5 * (tfidfScores.get(nodeId) || 0) +
      (1 - keywordBias) * 0.5 * (entropyScores.get(nodeId) || 0);

    const combined = semanticWeight * semanticScore + (1 - semanticWeight) * metaScore;
    finalScores.set(nodeId, combined);
  });

  // -------- 第四步：按评分排序并裁剪 --------
  const sortedIds = Array.from(chronicle.nodes.keys()).sort(
    (a, b) => (finalScores.get(b) ?? 0) - (finalScores.get(a) ?? 0)
  );
  const totalNodes = sortedIds.length;
  const keepCount = Math.max(minNodes, Math.ceil(totalNodes * (1 - targetRatio)));
  const keepIds = new Set(sortedIds.slice(0, keepCount));

  // -------- 第五步：构建压缩后的图 --------
  const compressedChronicle: ChronicleGraph = {
    ...chronicle,
    id: `${chronicle.id}_semantic_compressed`,
    nodes: new Map(),
    edges: [],
    startedAt: chronicle.startedAt,
    completedAt: chronicle.completedAt,
  };

  const discardedDetails: { nodeId: string; reason: string }[] = [];

  chronicle.nodes.forEach((node, id) => {
    if (keepIds.has(id)) {
      const keptNode = { ...node };
      if (Object.keys(node.inputs).length > 0) {
        keptNode.inputs = { summary: `[已摘要] ${node.architectureNodeId} inputs` };
      }
      if (Object.keys(node.outputs).length > 0 && !node.metadata.skipReason) {
        keptNode.outputs = { summary: node.metadata.outputSummary ?? `[已摘要] ${node.architectureNodeId} outputs` };
      }
      if (node.logs.length > 2) keptNode.logs = node.logs.slice(0, 1);
      compressedChronicle.nodes.set(id, keptNode);
    } else {
      const score = (finalScores.get(id) ?? 0).toFixed(2);
      compressedChronicle.nodes.set(id, {
        ...node,
        metadata: {
          ...node.metadata,
          status: 'compressed',
          outputSummary: `[已压缩] ${node.architectureNodeId} (语义评分: ${score})`,
          skipReason: undefined,
        },
        inputs: {},
        outputs: {},
        logs: [],
      });
      discardedDetails.push({
        nodeId: node.architectureNodeId,
        reason: `语义评分 ${score}，低于保留阈值（关键词=${(keywordScores.get(id)||0).toFixed(2)} tf-idf=${(tfidfScores.get(id)||0).toFixed(2)} entropy=${(entropyScores.get(id)||0).toFixed(2)}）`,
      });
    }
  });

  chronicle.edges.forEach((edge) => {
    const s = keepIds.has(edge.source);
    const t = keepIds.has(edge.target);
    if (keepAllEdges || s || t) {
      compressedChronicle.edges.push({
        ...edge,
        payloadSummary: s && t ? edge.payloadSummary : `${edge.payloadSummary} (端点已压缩)`,
      });
    }
  });

  // -------- 第六步：Architecture 同步裁剪 --------
  const compressedArchitecture: ArchitectureGraph = {
    ...architecture,
    id: `${architecture.id}_semantic_compressed`,
    nodes: new Map(),
    edges: [],
  };

  const keptArchIds = new Set<NodeId>();
  compressedChronicle.nodes.forEach((node) => {
    if (node.metadata.status !== 'compressed') {
      keptArchIds.add(node.architectureNodeId);
    }
  });

  architecture.nodes.forEach((node, id) => {
    if (keptArchIds.has(id)) compressedArchitecture.nodes.set(id, node);
  });
  architecture.edges.forEach((edge) => {
    if (compressedArchitecture.nodes.has(edge.source) && compressedArchitecture.nodes.has(edge.target)) {
      compressedArchitecture.edges.push(edge);
    }
  });

  // -------- 第七步：计算压缩率 --------
  const originalSize = chronicle.rawSizeBytes ?? estimateBytes(chronicle);
  const newSize = estimateBytes(compressedChronicle);
  const compressionRatio = originalSize > 0 ? newSize / originalSize : 1;

  return {
    compressedChronicle,
    compressedArchitecture,
    blueprint,
    compressionRatio,
    retainedContext: 1 - compressionRatio,
    discardedDetails,
    nodeScores: finalScores,
  };
}

function estimateBytes(g: ChronicleGraph): number {
  let size = 0;
  g.nodes.forEach((node) => { size += JSON.stringify(node).length; });
  g.edges.forEach((edge) => { size += JSON.stringify(edge).length; });
  return size || 1;
}

/** 调试辅助：打印每个节点的各维度评分 */
export function dumpSemanticScores(
  chronicle: ChronicleGraph
): string[] {
  const docs: { nodeId: string; tokens: string[]; node: any }[] = [];
  chronicle.nodes.forEach((node, id) => {
    docs.push({ nodeId: id, tokens: tokenize(extractTextFromNode(node)), node });
  });
  const tfidf = buildTfIdfScores(docs);
  const lines: string[] = [];
  docs.forEach(({ nodeId, node, tokens }) => {
    const kw = scoreKeywordHits(tokens);
    const ent = scoreEntropy(tokens);
    lines.push(
      `${node.architectureNodeId}: tf-idf=${(tfidf.get(nodeId)||0).toFixed(2)} keyword=${kw.toFixed(2)} entropy=${ent.toFixed(2)} tokens=${tokens.length}`
    );
  });
  return lines;
}
