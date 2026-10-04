/**
 * Graph-Context-Compressor —— 对话上下文压缩核心脚本
 *
 * 功能：
 *   1. 从对话消息自动构建三层图结构 (B/A/C)
 *   2. 调用通用压缩模块 (semantic-compressor + visualization)
 *   3. 输出压缩摘要 + 可视化数据
 *
 * 用法：
 *   // --- 方式1：脚本式 CLI（文件读取）
 *   npx tsx build_and_compress.ts --input conversation.json --output result.json
 *   // conversation.json = { messages: [{id, role, content, timestamp}], targetRatio: 0.5, intent?: 'trading'|'analysis'|... }
 *
 *   // --- 方式2：API 式调用
 *   import { createGraphCompressor } from './build_and_compress.ts';
 *   const result = await createGraphCompressor({
 *     messages: [...],
 *     targetRatio: 0.5,
 *     intent: 'trading',
 *     mode: 'semantic',
 *     highlightKeywords: ['BTC', 'macd', 'rsi', 'stop-loss', 'position-size'],
 *   });
 *   // result = { summary, compressionResult, visualizationData, retainedNodes, discardedNodes }
 *
 *   // --- 方式3：流式增量压缩（每收到新消息都可 append）
 *   const compressor = new StreamingCompressor({ initialMessages: [...], targetRatio: 0.5 });
 *   compressor.append(newMessage);
 *   const snapshot = compressor.getSnapshot();
 */

import * as fs from 'fs';
import * as path from 'path';
import { fileURLToPath } from 'url';

import {
  BlueprintGraph,
  ArchitectureGraph,
  ChronicleGraph,
  createCompressor,
  blueprintRegistry,
  semanticCompress,
  shardedCompress,
  buildVisualization,
  type VizNode,
  type VizLayer,
  type VizEdge,
  type TimelineItem,
  type DiffSummary,
  type VisualizationData,
} from '../../../index.ts';

// ============================================================
// ==================== 类型定义 ==============================
// ============================================================

export interface ConversationMessage {
  id: string;
  role: 'user' | 'assistant' | 'tool_call' | 'tool_result' | 'system';
  content: string;
  timestamp: number;
  tokens?: number;
  toolName?: string;
  decision?: string;
  importance?: 'high' | 'medium' | 'low';
}

export interface CompressorSkillOptions {
  messages: ConversationMessage[];
  intent?: string;
  targetRatio?: number;
  mode?: 'basic' | 'semantic' | 'sharded' | 'auto';
  highlightKeywords?: string[];
  verbose?: boolean;
}

export interface CompressionSkillSummary {
  compressionRatio: number;
  retainedContext: number;
  totalNodesBefore: number;
  totalNodesAfter: number;
  nodesByLayerBefore: { B: number; A: number; C: number };
  nodesByLayerAfter: { B: number; A: number; C: number };
  retainedNodeIds: string[];
  compressedNodeIds: string[];
  avgRetainedScore: number;
  avgCompressedScore: number;
  intentDetected: string;
  modeUsed: string;
  latencyMs: number;
  timelineSnapshot: TimelineItem[];
  retainedNodesDetail: Array<{
    id: string;
    name: string;
    layer: string;
    score: number;
    status: string;
    summary?: string;
  }>;
  discardedNodesDetail: Array<{
    nodeId: string;
    reason: string;
    originalName: string;
    score: number;
  }>;
}

export interface CompressionSkillResult {
  summary: CompressionSkillSummary;
  compressionSummary: string;          // 人类可读摘要
  visualizationData: VisualizationData; // 前端组件用
  blueprint: BlueprintGraph;            // 顶层架构
  architecture: ArchitectureGraph;      // 压缩后架构
  chronicle: ChronicleGraph;            // 压缩后执行记录
  diagnostics?: {
    nodeScores: Record<string, number>;
    topRetained: Array<{ id: string; name: string; score: number }>;
    bottomCompressed: Array<{ id: string; name: string; score: number }>;
  };
}

// ============================================================
// ==================== 启发式图构建 ===========================
// ============================================================

// --- 关键词库（用于意图识别 + 语义评分） ---
const INTENT_KEYWORDS: Record<string, string[]> = {
  trading: ['买入', '卖出', '仓位', '入场', '离场', '止损', '做多', '做空', '开仓',
            '加仓', '平仓', '持仓', '执行', '下单', 'transaction', 'buy', 'sell',
            'position', 'entry', 'exit'],
  analysis: ['分析', '研究', '调研', '行情', '趋势', '市场', '数据', '指标',
             'macd', 'rsi', '布林带', '基本面', '技术面', 'analysis', 'market',
             'trend', 'research'],
  strategy: ['策略', '设计', '优化', '回测', '参数', '规则', '信号', '触发',
             'strategy', 'backtest', 'design', 'optimize'],
  risk: ['风险', '风控', '止损', '止盈', '资金管理', '保证金', '杠杆',
         'risk', 'stop-loss', 'take-profit'],
  signal: ['信号', '监控', '触发', '通知', 'alert', 'signal', 'monitor', 'trigger'],
  compression: ['压缩', '总结', '摘要', '保留上下文', '上下文压缩', '上下文',
                '图压缩', 'graph', 'compress', 'summary'],
};

// --- 节点评分关键词（命中则提升重要性） ---
const HIGH_VALUE_KEYWORDS = [
  '决策', '确认', '最终', '关键', '重要', '结论', '建议', '推荐', '执行',
  '决定', '买入', '卖出', '入场', '止损', '止盈', '风险', 'position-size',
  'stop-loss', 'decision', 'confirm', 'final', 'key', 'important',
  '风险收益比', '夏普', '最大回撤', '胜率', '期望收益',
];

const TOOL_CALL_KEYWORDS = [
  'tool_call', '调用', '执行工具', 'execute', 'run', 'fetch', 'query',
  '搜索', '查询', '获取数据',
];

// ============================================================
// ==================== Phase 1: 意图识别 (B 层) ==============
// ============================================================

function detectIntent(messages: ConversationMessage[], explicitIntent?: string): string {
  if (explicitIntent) return explicitIntent;
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

function buildBlueprint(messages: ConversationMessage[], intent: string): BlueprintGraph {
  const detectedKeywords = Object.entries(INTENT_KEYWORDS).find(
    ([k]) => k === intent || k === detectIntent(messages),
  )?.[1] || [];

  const template = blueprintRegistry.getTemplateForIntent(intent);
  const nodeNames = [
    `意图识别 (${intent})`,
    '信息获取',
    '分析引擎',
    '决策模块',
    '执行/输出',
  ];

  const bp: BlueprintGraph = {
    id: `bp_${intent}_${Date.now()}`,
    name: `${intent} - ${template?.name || '通用对话'}`,
    description: `基于 ${messages.length} 条消息自动构建的蓝图 · 核心意图：${intent}`,
    nodes: new Map(nodeNames.map((name, i) => [
      `b_${i}`,
      {
        id: `b_${i}`,
        name,
        type: i === 0 ? 'module' : 'component',
        description: name,
        metadata: { status: 'completed', importance: i < 2 ? 'high' : 'medium' },
      },
    ])),
    edges: nodeNames.slice(0, -1).map((_, i) => ({
      source: `b_${i}`,
      target: `b_${i + 1}`,
      label: '→',
    })),
  };
  return bp;
}

// ============================================================
// ==================== Phase 2: 步骤提取 (A 层) ==============
// ============================================================

function extractArchitecture(messages: ConversationMessage[]): ArchitectureGraph {
  const steps: Array<{ id: string; name: string; type: string; score: number }> = [];

  // 启发式：基于角色 + 关键词匹配提取步骤
  messages.forEach((msg, idx) => {
    const isHighValue = HIGH_VALUE_KEYWORDS.some((kw) =>
      msg.content.toLowerCase().includes(kw.toLowerCase())
    );
    const isToolCall =
      msg.role === 'tool_call' || msg.role === 'tool_result' ||
      TOOL_CALL_KEYWORDS.some((kw) => msg.content.toLowerCase().includes(kw.toLowerCase()));

    let stepType = 'step';
    let score = 0.3;
    let stepName = '';

    if (msg.role === 'system') {
      return;
    } else if (isHighValue) {
      stepType = 'decision';
      score = 0.85;
      stepName = `决策点 ${idx + 1}: ${msg.content.slice(0, 50)}`;
    } else if (isToolCall) {
      stepType = 'step';
      score = 0.55;
      stepName = `工具调用 ${idx + 1}: ${msg.toolName || msg.content.slice(0, 30)}`;
    } else if (msg.role === 'user') {
      stepType = 'step';
      score = 0.6;
      stepName = `用户输入 ${idx + 1}: ${msg.content.slice(0, 50)}`;
    } else {
      stepType = 'step';
      score = 0.45;
      stepName = `助理回复 ${idx + 1}: ${msg.content.slice(0, 50)}`;
    }

    if (msg.importance === 'high') score = Math.min(1.0, score + 0.25);
    if (msg.importance === 'low') score = Math.max(0.1, score - 0.15);

    steps.push({
      id: `a_${idx}`,
      name: stepName,
      type: stepType,
      score,
    });
  });

  const arch: ArchitectureGraph = {
    id: 'arch_' + Date.now(),
    name: '自动架构图',
    parentBlueprintId: '',
    nodes: new Map(steps.map((s) => [
      s.id,
      {
        id: s.id,
        name: s.name,
        type: s.type,
        requires: [],
        metadata: {
          status: 'completed',
          score: s.score,
          tokenCost: msgTokens(steps.find((x) => x.id === s.id)?.id || ''),
        },
      },
    ])),
    edges: steps.slice(0, -1).map((s, i) => ({
      source: steps[i].id,
      target: steps[i + 1].id,
      type: 'sequential',
      label: '→',
    })),
    entryNodes: steps.length > 0 ? [steps[0].id] : [],
    exitNodes: steps.length > 0 ? [steps[steps.length - 1].id] : [],
  };

  // 添加依赖：按时间顺序链式
  for (let i = 1; i < steps.length; i++) {
    const step = arch.nodes.get(steps[i].id);
    if (step) step.requires = [steps[i - 1].id];
  }
  return arch;
}

function msgTokens(_id: string): number {
  // 简化估算（实际：可以取 message.tokens）
  return 0;
}

// ============================================================
// ==================== Phase 3: 执行记录 (C 层) ==============
// ============================================================

function buildChronicle(messages: ConversationMessage[]): ChronicleGraph {
  const startTime = messages[0]?.timestamp || Date.now();
  const lastTime = messages[messages.length - 1]?.timestamp || Date.now();

  const nodes: Array<{
    id: string;
    architectureNodeId: string;
    startTime: number;
    endTime: number;
    inputs: Record<string, unknown>;
    outputs: Record<string, unknown>;
    logs: string[];
    tokens: number;
    score?: number;
    status: string;
    name: string;
  }> = [];

  for (let i = 0; i < messages.length; i++) {
    const msg = messages[i];
    const tokens = msg.tokens || estimateTokens(msg.content);
    const isHighValue = HIGH_VALUE_KEYWORDS.some((kw) =>
      msg.content.toLowerCase().includes(kw.toLowerCase())
    );
    let score = 0.3 + (tokens / 2000) * 0.3;
    if (isHighValue) score += 0.3;
    if (msg.importance === 'high') score += 0.2;
    if (msg.importance === 'low') score -= 0.2;
    score = Math.max(0.1, Math.min(0.98, score));

    nodes.push({
      id: `c_${i}`,
      architectureNodeId: `a_${i}`,
      startTime: msg.timestamp,
      endTime: msg.timestamp + 1000,
      inputs: { role: msg.role, content: msg.content.slice(0, 100) },
      outputs: { content_hash: hashContent(msg.content.slice(0, 50)) },
      logs: [],
      tokens,
      score,
      status: msg.role === 'system' ? 'completed' : (isHighValue ? 'completed' : 'completed'),
      name: `${msg.role}: ${msg.content.slice(0, 60)}` + (msg.content.length > 60 ? '...' : ''),
    });
  }

  return {
    id: 'chronicle_' + Date.now(),
    architectureId: '',
    executionId: 'session-' + Date.now(),
    nodes: new Map(nodes.map((n) => [n.id, {
      id: n.id,
      architectureNodeId: n.architectureNodeId,
      startTime: n.startTime,
      endTime: n.endTime,
      inputs: n.inputs as { role?: string; content?: string; tokens?: number },
      outputs: n.outputs as { content_hash?: string },
      logs: n.logs,
      metadata: {
        tokens: n.tokens,
        score: n.score,
        status: n.status,
        role: messages[nodes.indexOf(n)].role,
      },
    }])),
    edges: nodes.slice(0, -1).map((_, i) => ({
      source: nodes[i].id,
      target: nodes[i + 1].id,
      type: 'follows',
      metadata: {},
    })),
    startTime,
    endTime: lastTime,
    totalTokens: nodes.reduce((sum, n) => sum + n.tokens, 0),
    totalLatencyMs: lastTime - startTime,
    status: 'completed',
  };
}

function estimateTokens(text: string): number {
  if (!text) return 0;
  // 英文平均 4 字符/token，中文 1.5 字符/token，简单估算
  const chineseChars = (text.match(/[\u4e00-\u9fa5]/g) || []).length;
  const otherChars = text.length - chineseChars;
  return Math.ceil(chineseChars / 1.5 + otherChars / 4);
}

function hashContent(text: string): string {
  let h = 0;
  for (let i = 0; i < text.length; i++) {
    h = ((h << 5) - h) + text.charCodeAt(i);
    h |= 0;
  }
  return String(h);
}

// ============================================================
// ==================== 主入口：createGraphCompressor =========
// ============================================================

export async function createGraphCompressor(
  options: CompressorSkillOptions
): Promise<CompressionSkillResult> {
  const t0 = Date.now();
  const {
    messages,
    intent: explicitIntent,
    targetRatio = 0.5,
    mode = 'semantic',
    highlightKeywords = [],
    verbose = false,
  } = options;

  if (!messages || messages.length === 0) {
    throw new Error('No messages provided for compression');
  }

  // --- Phase 1: 意图识别 + B 层构建 ---
  const intent = detectIntent(messages, explicitIntent);
  if (verbose) console.log(`[Phase 1] 检测到意图: ${intent}`);
  const blueprint = buildBlueprint(messages, intent);
  if (verbose) console.log(`[Phase 1] Blueprint 构建完成: ${blueprint.nodes.size} 个组件`);

  // --- Phase 2: 架构步骤提取 (A 层) ---
  const architecture = extractArchitecture(messages);
  if (verbose) console.log(`[Phase 2] Architecture 构建完成: ${architecture.nodes.size} 个步骤`);

  // --- Phase 3: 执行记录构建 (C 层) ---
  const chronicle = buildChronicle(messages);
  if (verbose) console.log(`[Phase 3] Chronicle 构建完成: ${chronicle.nodes.size} 个执行节点`);

  // --- Phase 4: 压缩评估 ---
  const effectiveMode = mode === 'auto'
    ? (messages.length > 100 ? 'sharded' : messages.length > 10 ? 'semantic' : 'basic')
    : mode;
  if (verbose) console.log(`[Phase 4] 使用模式: ${effectiveMode}, 目标压缩率: ${targetRatio}`);

  let compressResult;
  if (effectiveMode === 'sharded') {
    compressResult = shardedCompress(chronicle, architecture, blueprint, {
      targetRatio,
      shardSize: 50,
      preserveShardAnchors: true,
    });
  } else {
    compressResult = semanticCompress(chronicle, architecture, blueprint, {
      targetRatio,
      semanticWeight: 0.4,
      tokenWeight: 0.4,
      latencyWeight: 0.2,
      customKeywords: [...HIGH_VALUE_KEYWORDS, ...highlightKeywords],
    });
  }

  // --- Phase 5: 可视化数据生成 ---
  const visualizationData = buildVisualization(compressResult);

  // --- 生成 summary ---
  const retainedNodes = Array.from(compressResult.compressedChronicle.nodes.values())
    .filter((n) => n.metadata?.status !== 'compressed');
  const compressedNodes = Array.from(compressResult.compressedChronicle.nodes.values())
    .filter((n) => n.metadata?.status === 'compressed');
  const scores = compressResult.nodeScores || new Map<string, number>();
  const avgRetainedScore = retainedNodes.length > 0
    ? retainedNodes.reduce((sum, n) => sum + (scores.get(n.id) || 0), 0) / retainedNodes.length
    : 0;
  const avgCompressedScore = compressedNodes.length > 0
    ? compressedNodes.reduce((sum, n) => sum + (scores.get(n.id) || 0), 0) / compressedNodes.length
    : 0;

  const sortedByScore = Array.from(scores.entries()).sort((a, b) => b[1] - a[1]);
  const nodesById = new Map(Array.from(chronicle.nodes.entries()).map(([id, n]) => [id, n]));

  const latencyMs = Date.now() - t0;

  const retainedNodeIds = retainedNodes.map((n) => n.id);
  const compressedNodeIds = compressedNodes.map((n) => n.id);

  // --- 生成人类可读摘要 ---
  const compressionSummary = buildHumanSummary(
    messages,
    retainedNodes.map((n) => nodesById.get(n.id)!).filter(Boolean),
    compressedNodes.map((n) => nodesById.get(n.id)!).filter(Boolean),
    intent,
    targetRatio,
    compressResult.compressionRatio,
    avgRetainedScore,
    avgCompressedScore,
  );

  // --- 保留节点详情 ---
  const retainedDetail = retainedNodes.map((n) => {
    const original = nodesById.get(n.id);
    return {
      id: n.id,
      name: n.name,
      layer: 'C',
      score: scores.get(n.id) || 0,
      status: n.metadata?.status || 'completed',
      summary: (original?.inputs as any)?.content || '',
    };
  }).sort((a, b) => b.score - a.score);

  const discardedDetail = compressedNodes.map((n) => ({
    nodeId: n.id,
    reason: n.metadata?.status || 'compressed',
    originalName: n.name,
    score: scores.get(n.id) || 0,
  }));

  const summary: CompressionSkillSummary = {
    compressionRatio: compressResult.compressionRatio,
    retainedContext: compressResult.retainedContext ?? 0.5,
    totalNodesBefore: chronicle.nodes.size + architecture.nodes.size + blueprint.nodes.size,
    totalNodesAfter: compressResult.compressedChronicle.nodes.size + compressResult.compressedArchitecture.nodes.size + blueprint.nodes.size,
    nodesByLayerBefore: {
      B: blueprint.nodes.size,
      A: architecture.nodes.size,
      C: chronicle.nodes.size,
    },
    nodesByLayerAfter: {
      B: blueprint.nodes.size,
      A: compressResult.compressedArchitecture.nodes.size,
      C: compressResult.compressedChronicle.nodes.size,
    },
    retainedNodeIds,
    compressedNodeIds,
    avgRetainedScore,
    avgCompressedScore,
    intentDetected: intent,
    modeUsed: effectiveMode,
    latencyMs,
    timelineSnapshot: visualizationData.timeline,
    retainedNodesDetail: retainedDetail,
    discardedNodesDetail: discardedDetail,
  };

  return {
    summary,
    compressionSummary,
    visualizationData,
    blueprint,
    architecture: compressResult.compressedArchitecture,
    chronicle: compressResult.compressedChronicle,
    diagnostics: verbose ? {
      nodeScores: Object.fromEntries(scores),
      topRetained: sortedByScore.slice(0, 5).map(([id, score]) => ({
        id, name: nodesById.get(id)?.name || id, score,
      })),
      bottomCompressed: sortedByScore.slice(-5).reverse().map(([id, score]) => ({
        id, name: nodesById.get(id)?.name || id, score,
      })),
    } : undefined,
  };
}

// ============================================================
// ==================== 人类可读摘要生成 ======================
// ============================================================

function buildHumanSummary(
  messages: ConversationMessage[],
  retainedNodes: any[],
  compressedNodes: any[],
  intent: string,
  targetRatio: number,
  actualRatio: number,
  avgRetainedScore: number,
  avgCompressedScore: number,
): string {
  const lines = [
    '========== 📊 图压缩摘要 ==========',
    `对话消息: ${messages.length} 条`,
    `检测意图: ${intent}`,
    `目标压缩率: ${(targetRatio * 100).toFixed(0)}%`,
    `实际压缩率: ${(actualRatio * 100).toFixed(0)}% (${compressedNodes.length} 压缩 / ${retainedNodes.length} 保留)`,
    '',
    `保留节点平均分: ${(avgRetainedScore * 100).toFixed(0)}分`,
    `压缩节点平均分: ${(avgCompressedScore * 100).toFixed(0)}分`,
    '',
    '--- 🔒 保留的关键内容（高价值节点） ---',
  ];
  retainedNodes.slice(0, 8).forEach((n, i) => {
    lines.push(`  ${i + 1}. [${(n.metadata?.score * 100 || 0).toFixed(0)}分] ${n.name}`);
  });
  if (retainedNodes.length > 8) lines.push(`  ... 共 ${retainedNodes.length} 条`);
  lines.push('');
  lines.push('--- 🗜️ 压缩的次要内容（保留引用） ---');
  compressedNodes.slice(0, 5).forEach((n, i) => {
    lines.push(`  ${i + 1}. [${(n.metadata?.score * 100 || 0).toFixed(0)}分] ${n.name}`);
  });
  if (compressedNodes.length > 5) lines.push(`  ... 共 ${compressedNodes.length} 条`);
  lines.push('');
  lines.push('（可视化数据已生成，可在前端渲染为三层图对比）');
  lines.push('====================================');
  return lines.join('\n');
}

// ============================================================
// ==================== CLI 入口 ==============================
// ============================================================

function parseCliArgs(): { input?: string; output?: string; targetRatio: number; intent?: string; mode: string; verbose: boolean } {
  const args = process.argv.slice(2);
  let input: string | undefined;
  let output: string | undefined;
  let targetRatio = 0.5;
  let intent: string | undefined;
  let mode = 'auto';
  let verbose = false;

  for (let i = 0; i < args.length; i++) {
    if (args[i] === '--input' && args[i + 1]) input = args[++i];
    else if (args[i] === '--output' && args[i + 1]) output = args[++i];
    else if (args[i] === '--target-ratio' && args[i + 1]) targetRatio = parseFloat(args[++i]);
    else if (args[i] === '--intent' && args[i + 1]) intent = args[++i];
    else if (args[i] === '--mode' && args[i + 1]) mode = args[++i];
    else if (args[i] === '--verbose') verbose = true;
  }
  return { input, output, targetRatio, intent, mode, verbose };
}

async function runCli(): Promise<void> {
  const args = parseCliArgs();
  if (!args.input) {
    console.log('使用: npx tsx build_and_compress.ts --input conversation.json [--output result.json] [--target-ratio 0.5]');
    console.log('');
    console.log('示例输入 JSON:');
    const sample = {
      messages: [
        { id: '1', role: 'user', content: '帮我分析 BTC 行情', timestamp: Date.now() },
        { id: '2', role: 'assistant', content: '正在分析市场数据...', timestamp: Date.now() + 1000 },
        { id: '3', role: 'tool_call', content: 'fetch_market_data BTC/USDT', timestamp: Date.now() + 2000 },
        { id: '4', role: 'tool_result', content: '{price: 65000, rsi: 55}', timestamp: Date.now() + 3000 },
        { id: '5', role: 'user', content: '我决定在 64800 买入，止损 64500', timestamp: Date.now() + 4000 },
        { id: '6', role: 'assistant', content: '决策确认：入场 64800，止损 64500，风险收益比 1:2', timestamp: Date.now() + 5000 },
      ],
      targetRatio: 0.5,
    };
    console.log(JSON.stringify(sample, null, 2));
    return;
  }

  const inputPath = path.resolve(args.input);
  if (!fs.existsSync(inputPath)) {
    console.error(`❌ 输入文件不存在: ${inputPath}`);
    process.exit(1);
  }

  const data = JSON.parse(fs.readFileSync(inputPath, 'utf-8'));
  const messages = data.messages;
  if (!messages || !Array.isArray(messages)) {
    console.error('❌ 输入文件缺少 messages 数组');
    process.exit(1);
  }

  console.log(`📥 读取 ${messages.length} 条消息`);

  const result = await createGraphCompressor({
    messages,
    targetRatio: data.targetRatio || args.targetRatio,
    intent: data.intent || args.intent,
    mode: (data.mode || args.mode) as any,
    highlightKeywords: data.highlightKeywords || [],
    verbose: args.verbose,
  });

  console.log(result.compressionSummary);
  console.log('');

  if (args.output) {
    const outputPath = path.resolve(args.output);
    const outputData = {
      summary: result.summary,
      compressionSummary: result.compressionSummary,
      visualizationData: result.visualizationData,
    };
    fs.writeFileSync(outputPath, JSON.stringify(outputData, null, 2));
    console.log(`✅ 结果已保存到: ${outputPath}`);
  }
}

// ============================================================
// ==================== 流式增量压缩 =========================
// ============================================================

export class StreamingCompressor {
  private messages: ConversationMessage[] = [];
  private targetRatio: number;
  private lastResult: CompressionSkillResult | null = null;
  private compressCounter: number = 0;
  private compressEveryN: number;

  constructor(options: {
    initialMessages?: ConversationMessage[];
    targetRatio?: number;
    compressEveryN?: number;
  }) {
    this.messages = options.initialMessages || [];
    this.targetRatio = options.targetRatio || 0.5;
    this.compressEveryN = options.compressEveryN || 5;
  }

  append(message: ConversationMessage): void {
    this.messages.push(message);
    this.compressCounter++;
    if (this.compressCounter >= this.compressEveryN) {
      this.recompress();
      this.compressCounter = 0;
    }
  }

  async recompress(): Promise<CompressionSkillResult> {
    const result = await createGraphCompressor({
      messages: this.messages,
      targetRatio: this.targetRatio,
    });
    this.lastResult = result;
    return result;
  }

  getSnapshot(): CompressionSkillResult | null {
    return this.lastResult;
  }

  getMessages(): ConversationMessage[] {
    return this.messages;
  }
}

// ============================================================
// ==================== 执行 CLI ==============================
// ============================================================

if (import.meta.url === `file://${process.argv[1]?.replace(/\\/g, '/')}`) {
  runCli().catch((err) => {
    console.error('❌ 执行失败:', err);
    process.exit(1);
  });
}
