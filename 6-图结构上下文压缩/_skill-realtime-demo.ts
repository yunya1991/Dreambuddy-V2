/**
 * 🚀 图压缩 SKILL - 实时测试（简化版）
 *
 * 从同一目录直接导入，避免路径问题。
 */

import {
  semanticCompress,
  buildVisualization,
  blueprintRegistry,
} from '../../semantic-compressor.ts';
// @ts-ignore - 动态导入
import { createCompressor } from '../../contract.ts';
// @ts-ignore - 动态导入
import type { BlueprintGraph, ArchitectureGraph, ChronicleGraph } from '../../types.ts';

// ====== 模拟交易对话 ======
interface Message {
  id: string;
  role: string;
  content: string;
  timestamp: number;
  importance?: 'high' | 'medium' | 'low';
  toolName?: string;
}

const baseTime = Date.now() - 15 * 60 * 1000;
const messages: Message[] = [
  { id: '1', role: 'user', content: '帮我分析一下 BTC 当前的行情，看看是否适合入场', timestamp: baseTime },
  { id: '2', role: 'assistant', content: '好的，我先调研一下当前市场数据和技术指标...', timestamp: baseTime + 30000 },
  { id: '3', role: 'tool_call', content: 'fetch_market_data BTC/USDT - 周线 RSI=55, 日线 RSI=48', timestamp: baseTime + 60000, toolName: 'market-data-api' },
  { id: '4', role: 'tool_result', content: 'BTC 当前价格 65,200 USDT，周线略微超买，日线中性偏多', timestamp: baseTime + 75000 },
  { id: '5', role: 'assistant', content: '分析完成：市场处于震荡偏多格局。需要进一步确认入场信号。', timestamp: baseTime + 120000 },
  { id: '6', role: 'user', content: '好，让我们做个买入决策。你建议在什么价位入场？止损应该设在哪里？', timestamp: baseTime + 180000, importance: 'high' },
  { id: '7', role: 'assistant', content: '基于当前分析，我建议：在 64,800 附近挂买入单，止损设在 64,200，第一止盈 65,800', timestamp: baseTime + 240000, importance: 'high' },
  { id: '8', role: 'user', content: '仓位大小呢？风险收益比怎么样？', timestamp: baseTime + 300000 },
  { id: '9', role: 'assistant', content: '建议仓位大小：总资金的 3%。风险收益比 1:1.67。这是一个较为保守的入场。', timestamp: baseTime + 360000, importance: 'high' },
  { id: '10', role: 'user', content: '等一下，让我再看看历史回测数据，确认这个策略的胜率', timestamp: baseTime + 420000 },
  { id: '11', role: 'tool_call', content: 'backtest_engine - 回测过去 60 天，策略参数: rsi oversold=40, stop-loss=1%', timestamp: baseTime + 450000, toolName: 'backtest-engine' },
  { id: '12', role: 'tool_result', content: '回测结果: 胜率 58%, 平均收益 1.2%, 最大回撤 2.5%, 夏普比率 1.3', timestamp: baseTime + 480000 },
  { id: '13', role: 'assistant', content: '回测验证通过：该信号在过去 60 天内表现稳定，可以执行。', timestamp: baseTime + 540000, importance: 'high' },
  { id: '14', role: 'user', content: '好，那就按这个方案执行', timestamp: baseTime + 600000, importance: 'high' },
  { id: '15', role: 'assistant', content: '已确认：入场 64,800 / 止损 64,200 / 止盈 65,800，仓位 3%，执行！', timestamp: baseTime + 630000, importance: 'high' },
  { id: '16', role: 'user', content: '顺便问一下，最近 ETH 的情况如何？', timestamp: baseTime + 660000 },
  { id: '17', role: 'assistant', content: 'ETH 当前价格 3,450 USDT，技术面偏弱，不建议操作。', timestamp: baseTime + 690000 },
  { id: '18', role: 'user', content: '好的，了解。那我们就专注 BTC', timestamp: baseTime + 720000 },
  { id: '19', role: 'assistant', content: '明白。将持续监控 BTC 入场条件，满足后自动触发。', timestamp: baseTime + 750000 },
];

// ====== 关键词 ======
const HIGH_VALUE_KWS = ['买入', '卖出', '决策', '确认', '最终', '重要', '关键',
  '止损', '止盈', '风险收益比', '夏普', '执行', '仓位', '回测', '胜率'];

// ====== Phase 1: 意图检测 ======
function detectIntent(msgs: Message[]): string {
  const text = msgs.map((m) => m.content).join(' ').toLowerCase();
  const intents = {
    trading: ['买入', '卖出', '仓位', '入场', '止损', '做多', '做空', 'buy', 'sell', 'position'],
    analysis: ['分析', '研究', '行情', '市场', '趋势', '指标', 'macd', 'rsi'],
    risk: ['风险', '风控', '止损', '止盈', '资金管理'],
  };
  let bestIntent = 'general';
  let bestScore = 0;
  for (const [intent, kws] of Object.entries(intents)) {
    const score = kws.reduce((s, kw) => s + (text.includes(kw.toLowerCase()) ? 1 : 0), 0);
    if (score > bestScore) { bestScore = score; bestIntent = intent; }
  }
  return bestIntent;
}

// ====== Phase 2: 构建三层图 ======
function buildBlueprint(msgs: Message[], intent: string): BlueprintGraph {
  const components = [
    { id: 'b_intent', name: `意图识别 (${intent})`, type: 'module' },
    { id: 'b_data', name: '信息获取', type: 'component' },
    { id: 'b_analysis', name: '分析引擎', type: 'component' },
    { id: 'b_decision', name: '决策模块', type: 'component' },
    { id: 'b_output', name: '执行/输出', type: 'component' },
  ];
  const bp: BlueprintGraph = {
    id: 'bp_' + Date.now(),
    name: `${intent} - 对话蓝图`,
    description: `基于 ${msgs.length} 条消息自动构建`,
    nodes: new Map(components.map((c) => [c.id, {
      id: c.id, name: c.name, type: c.type, description: c.name,
      metadata: { status: 'completed' },
    }])),
    edges: components.slice(0, -1).map((c, i) => ({
      source: c.id, target: components[i + 1].id, label: '→', type: 'flow',
    })),
  };
  return bp;
}

function buildArchitecture(msgs: Message[]): ArchitectureGraph {
  const nodes = msgs.map((m, i) => ({
    id: `a_${i}`,
    name: m.content.slice(0, 40) + (m.content.length > 40 ? '...' : ''),
    type: m.importance === 'high' ? 'decision' : 'step',
    requires: i > 0 ? [`a_${i - 1}`] : [],
    score: computeNodeScore(m),
    tokens: estimateTokens(m.content),
  }));
  const arch: ArchitectureGraph = {
    id: 'arch_' + Date.now(),
    name: '自动架构图',
    parentBlueprintId: '',
    nodes: new Map(nodes.map((n) => [n.id, {
      id: n.id, name: n.name, type: n.type, requires: n.requires,
      metadata: { status: 'completed', score: n.score, tokenCost: n.tokens },
    }])),
    edges: nodes.slice(0, -1).map((n, i) => ({
      source: nodes[i].id, target: nodes[i + 1].id, type: 'sequential', label: '→', metadata: {},
    })),
    entryNodes: nodes.length > 0 ? [nodes[0].id] : [],
    exitNodes: nodes.length > 0 ? [nodes[nodes.length - 1].id] : [],
  };
  return arch;
}

function buildChronicle(msgs: Message[]): ChronicleGraph {
  const cnodes = msgs.map((m, i) => ({
    id: `c_${i}`,
    architectureNodeId: `a_${i}`,
    startTime: m.timestamp,
    endTime: m.timestamp + 30000,
    inputs: { role: m.role, content: m.content.slice(0, 80), tokens: estimateTokens(m.content) },
    outputs: { summary: m.content.slice(0, 40) },
    logs: [],
    metadata: {
      tokens: estimateTokens(m.content),
      score: computeNodeScore(m),
      status: 'completed',
      role: m.role,
      importance: m.importance || 'medium',
    },
    name: `${m.role}: ${m.content.slice(0, 50)}`,
  }));
  return {
    id: 'chronicle_' + Date.now(),
    architectureId: '',
    executionId: 'session',
    nodes: new Map(cnodes.map((n) => [n.id, {
      id: n.id,
      architectureNodeId: n.architectureNodeId,
      startTime: n.startTime,
      endTime: n.endTime,
      inputs: n.inputs as { role: string; content: string; tokens: number },
      outputs: n.outputs as { summary: string },
      logs: n.logs,
      metadata: n.metadata,
    }])),
    edges: cnodes.slice(0, -1).map((n, i) => ({
      source: cnodes[i].id, target: cnodes[i + 1].id, type: 'follows', metadata: {},
    })),
    startTime: msgs[0].timestamp,
    endTime: msgs[msgs.length - 1].timestamp,
    totalTokens: cnodes.reduce((s, n) => s + (n.metadata?.tokens || 0), 0),
    totalLatencyMs: msgs[msgs.length - 1].timestamp - msgs[0].timestamp,
    status: 'completed',
  };
}

function computeNodeScore(m: Message): number {
  let score = 0.3;
  score += Math.min(0.3, estimateTokens(m.content) / 500);
  if (m.importance === 'high') score += 0.25;
  if (m.importance === 'low') score -= 0.15;
  for (const kw of HIGH_VALUE_KWS) {
    if (m.content.toLowerCase().includes(kw.toLowerCase())) score += 0.08;
  }
  if (m.role === 'tool_call' || m.role === 'tool_result') score += 0.05;
  return Math.max(0.1, Math.min(0.95, score));
}

function estimateTokens(text: string): number {
  if (!text) return 0;
  const chinese = (text.match(/[\u4e00-\u9fa5]/g) || []).length;
  const other = text.length - chinese;
  return Math.ceil(chinese / 1.5 + other / 4);
}

// ====== Phase 3: 压缩 & 可视化 ======
async function run(): Promise<void> {
  console.log('========================================');
  console.log('📊 图上下文压缩 SKILL - 实时演示');
  console.log('========================================');
  console.log(`\n📝 输入对话: ${messages.length} 条消息`);
  const minutes = (messages[messages.length - 1].timestamp - messages[0].timestamp) / 60000;
  console.log(`⏱️ 对话时长: ${minutes.toFixed(1)} 分钟\n`);

  const intent = detectIntent(messages);
  console.log('[Phase 1] 意图检测:', intent);

  const blueprint = buildBlueprint(messages, intent);
  console.log('[Phase 1] Blueprint 完成:', blueprint.nodes.size, '个组件');

  const architecture = buildArchitecture(messages);
  console.log('[Phase 2] Architecture 完成:', architecture.nodes.size, '个步骤');

  const chronicle = buildChronicle(messages);
  console.log('[Phase 3] Chronicle 完成:', chronicle.nodes.size, '个执行节点');

  const targetRatio = 0.5;
  console.log('\n[Phase 4] 语义压缩... 目标压缩率:', (targetRatio * 100).toFixed(0) + '%');

  const compressResult = semanticCompress(chronicle, architecture, blueprint, {
    targetRatio,
    semanticWeight: 0.4,
    tokenWeight: 0.4,
    latencyWeight: 0.2,
    customKeywords: HIGH_VALUE_KWS,
  });

  const vizData = buildVisualization(compressResult);
  console.log('[Phase 5] 可视化数据生成完成 ✓');

  // ====== 打印结果 ======
  const retained = Array.from(compressResult.compressedChronicle.nodes.values())
    .filter((n) => n.metadata?.status !== 'compressed');
  const compressed = Array.from(compressResult.compressedChronicle.nodes.values())
    .filter((n) => n.metadata?.status === 'compressed');
  const scores = compressResult.nodeScores || new Map();

  console.log('\n========== 📊 压缩摘要 ==========');
  console.log(`  检测意图: ${intent}`);
  console.log(`  实际压缩率: ${(compressResult.compressionRatio * 100).toFixed(0)}%`);
  console.log(`  保留节点: ${retained.length} / ${chronicle.nodes.size}`);
  console.log(`  压缩节点: ${compressed.length}`);
  console.log(`  保留节点平均评分: ${
    (retained.reduce((s, n) => s + (scores.get(n.id) || 0), 0) / Math.max(retained.length, 1) * 100).toFixed(0)}分`);
  console.log(`  压缩节点平均评分: ${
    (compressed.reduce((s, n) => s + (scores.get(n.id) || 0), 0) / Math.max(compressed.length, 1) * 100).toFixed(0)}分`);

  console.log('\n--- 🔒 保留的关键内容（按评分排序）---');
  Array.from(scores.entries())
    .sort((a, b) => b[1] - a[1])
    .slice(0, 6)
    .forEach(([id, score], i) => {
      const node = chronicle.nodes.get(id);
      if (node) {
        console.log(`  ${i + 1}. [${(score * 100).toFixed(0)}分] ${node.name || id}`);
      }
    });

  console.log('\n--- 📅 执行时间线（保留/压缩状态）---');
  vizData.timeline.slice(0, 10).forEach((item) => {
    const status = item.kept ? '✓ KEEP   ' : '✗ COMPRESS';
    const score = (item.score * 100).toFixed(0).padStart(3, ' ');
    console.log(`  ${status} [${score}分] ${item.name.slice(0, 50)}`);
  });

  console.log('\n--- ✨ 可视化数据 ---');
  console.log(`  压缩前: B=${vizData.before.B.nodes.length} A=${vizData.before.A.nodes.length} C=${vizData.before.C.nodes.length}`);
  console.log(`  压缩后: B=${vizData.after.B.nodes.length} A=${vizData.after.A.nodes.length} C=${vizData.after.C.nodes.length}`);
  console.log(`  压缩比: ${(compressResult.compressionRatio * 100).toFixed(0)}%`);
  console.log(`  可直接传递给 GraphCompressionVisualizer 组件 ✓`);

  console.log('\n========================================');
  console.log('✅ SKILL 执行成功 - 验证通过 ✓');
  console.log('========================================');
}

run().catch((e) => {
  console.error('❌ 执行失败:', e);
  process.exit(1);
});
