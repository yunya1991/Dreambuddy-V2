/**
 * ============================================================
 *  🚀  图结构上下文压缩系统 - 8大模块完整整合演示
 * ============================================================
 *
 *  完整系统架构:
 *
 *    1. graph-compress                 核心压缩（关键词+元数据）
 *    2. semantic-compressor-advanced    增强语义压缩（TF-IDF + 熵 + 语义标签）
 *    3. auto-graph-generator          自动图生成（Blueprint + Architecture）
 *    4. skip-gate-integration         Skip Gate 决策记录
 *    5. graph-inference-engine        图结构推理引擎
 *    6. terminal-visualizer            ASCII 终端可视化渲染
 *
 *  运行: node --experimental-strip-types complete-demo.ts
 */

import { graphCompress, type CompressMessage } from './graph-compress.ts';
import { semanticCompress } from './semantic-compressor-advanced.ts';
import { autoCompressContext, detectIntent } from './auto-graph-generator.ts';
import { SkipGateRecorder, createSkipGateRecorder } from './skip-gate-integration.ts';
import { createInferenceEngine } from './graph-inference-engine.ts';
import { renderVisualization } from './terminal-visualizer.ts';

function padCenter(str: string, len: number): string {
  if (str.length >= len) return str.slice(0, len);
  const left = Math.floor((len - str.length) / 2);
  return ' '.repeat(left) + str + ' '.repeat(len - str.length - left);
}

// 模拟对话数据
function createTradingDialog(): CompressMessage[] {
  const base = Date.now() - 1000 * 60 * 60;
  return [
    { id: 'u1', role: 'user', content: '帮我分析 BTC 的短线交易机会', timestamp: base },
    { id: 'a1', role: 'assistant', content: 'BTC 当前价格 65,200 USDT，RSI 55，MACD 金叉，均线多头排列，趋势向上。', timestamp: base + 1000 },
    { id: 'u2', role: 'user', content: '入场和止损应该怎么设置？', timestamp: base + 2000 },
    { id: 'a2', role: 'assistant', content: '建议：入场 64,800（回调支撑位），止损 64,200（近期低点下方），第一止盈 65,800。风险收益比约 1:1.67。', importance: 'high', timestamp: base + 3000 },
    { id: 'u3', role: 'user', content: '仓位呢？用多大杠杆比较合适？', timestamp: base + 4000 },
    { id: 'a3', role: 'assistant', content: '资金管理建议：仓位总资金的 3%，不超过 5x 杠杆。中等风险、胜率可接受的配置。', importance: 'high', timestamp: base + 5000 },
    { id: 'u4', role: 'user', content: '有没有历史回测？', timestamp: base + 6000 },
    { id: 'a4', role: 'assistant', content: '快速回测：过去 30 天类似信号出现 7 次，胜率 71%，平均持仓 3.2 天，最大回撤 4.2%。整体表现稳健。', timestamp: base + 7000 },
    { id: 'u5', role: 'user', content: '好的，那就按这个方案执行', importance: 'high', timestamp: base + 8000 },
    { id: 'a5', role: 'assistant', content: '已确认方案，等待 BTC 价格触发入场条件。执行参数：入场 64,800 / 止损 64,200 / 止盈 65,800 / 仓位 3%。', importance: 'high', timestamp: base + 9000 },
  ];
}

function createProblematicDialog(): CompressMessage[] {
  const base = Date.now() - 1000 * 60 * 30;
  return [
    { id: 'p1', role: 'user', content: 'BTC 现在可以做多吗？', timestamp: base },
    { id: 'p2', role: 'assistant', content: 'BTC 当前价格 65,000 USDT，可以考虑做多', timestamp: base + 1000 },
    { id: 'p3', role: 'user', content: '那做空呢？', timestamp: base + 2000 },
    { id: 'p4', role: 'assistant', content: '也可以考虑做空，近期有回调风险', timestamp: base + 3000 },
    { id: 'p5', role: 'user', content: '好，我用 10 倍杠杆', timestamp: base + 4000 },
    { id: 'p6', role: 'assistant', content: '好的，已记录', timestamp: base + 5000 },
  ];
}

async function runCompleteDemo(): Promise<void> {
  const width = 72;
  const messages = createTradingDialog();
  const bar = '═'.repeat(width);
  const sep = '─'.repeat(width);

  console.log('\n' + bar);
  console.log(padCenter('图结构上下文压缩系统 - 8大模块完整整合演示', width));
  console.log(bar);
  console.log(padCenter('输入: 10 条 BTC 短线交易对话 | 目标压缩率 50%', width));
  console.log(bar);

  // 模块 1: 核心压缩
  console.log('\n' + sep);
  console.log('[1/8] 模块 1/8 graph-compress - 核心压缩（快速评分）');
  console.log(sep);
  const basic = graphCompress({ messages, targetRatio: 0.5 });
  console.log('  保留 ' + basic.kept.length + ' | 压缩 ' + basic.compressed.length + ' | 意图: ' + basic.summary.intentDetected);
  console.log('  耗时: ' + basic.summary.latencyMs + 'ms | 压缩率: ' + (basic.summary.compressionRatio * 100).toFixed(0) + '%');

  // 模块 2: 增强语义压缩
  console.log('\n' + sep);
  console.log('[2/8] 模块 2/8 semantic-compressor-advanced - 增强语义压缩 (TF-IDF + 信息熵 + 语义标签 + 关键词桶)');
  console.log(sep);
  const semantic = semanticCompress({ messages, targetRatio: 0.5 });
  console.log('  词汇量: ' + semantic.globalStats.totalVocab);
  console.log('  语义标签: ' + Object.keys(semantic.globalStats.tagDistribution).join(', '));
  console.log('  关键词桶: ' + Object.keys(semantic.globalStats.bucketHits).join(', '));
  console.log('  保留节点: ' + semantic.kept.length + ' | 压缩节点: ' + semantic.compressed.length);
  console.log('  Top 3 高价值节点:');
  for (let i = 0; i < Math.min(3, semantic.kept.length); i++) {
    const node = semantic.kept[i];
    console.log('    ' + (i + 1) + '. [' + (node.score * 100).toFixed(0) + '分] ' + node.name.slice(0, 50));
  }

  // 模块 3: 自动图生成
  console.log('\n' + sep);
  console.log('[3/8] 模块 3/8 auto-graph-generator - 自动图生成（Blueprint + Architecture）');
  console.log(sep);
  const autoResult = autoCompressContext(messages, { sessionId: 'complete-demo', targetRatio: 0.5 });
  console.log('  Blueprint: ' + autoResult.blueprint.nodes.size + ' 节点');
  console.log('  意图检测: ' + autoResult.intentMatch.intent + ' | 置信度: ' + (autoResult.intentMatch.confidence * 100).toFixed(0) + '%');
  console.log('  Architecture: ' + autoResult.architecture.nodes.size + ' 节点');
  console.log('  建议步骤: ' + autoResult.blueprint.suggestedSteps.slice(0, 5).join(' → '));

  // 模块 4: Skip Gate
  console.log('\n' + sep);
  console.log('[4/8] 模块 4/8 skip-gate-integration - Skip Gate 决策记录');
  console.log(sep);
  const sg = createSkipGateRecorder('complete-demo');
  sg.startTask('btc-analysis', 'BTC 行情分析 & 决策', 1);
  sg.recordExecute('market-collect', '市场数据收集', '用户请求行情', 200, 300);
  sg.recordExecute('technical', '技术指标分析', 'RSI/MACD/均线', 350, 400);
  sg.recordSkip('deep-news', '深度新闻分析', '用户未要求新闻分析', 0.6);
  sg.recordExecute('entry-calc', '入场参数计算', '核心决策输出', 150, 120);
  sg.recordExecute('risk-setup', '风险参数设置', '仓位/止损', 180, 100);
  sg.recordSkip('backtest', '历史回测', '用户直接确认方案', 0.7);
  sg.recordExecute('signal', '生成执行信号', '最终输出', 100, 80);
  sg.completeTask();
  const sgStats = sg.getSummary();
  console.log('  总决策: ' + sgStats.total + ' | 执行: ' + sgStats.byType.EXECUTE + ' | 跳过: ' + sgStats.byType.SKIP);
  console.log('  平均置信度: ' + (sgStats.avgConfidence * 100).toFixed(0) + '%');

  // 模块 5: 推理引擎
  console.log('\n' + sep);
  console.log('[5/8] 模块 5/8 graph-inference-engine - 图结构推理引擎');
  console.log(sep);
  const engine = createInferenceEngine('complete-demo-inference');
  engine.feedMessages(messages);
  engine.setSkipGate(sg);
  const inference = engine.infer();
  console.log('  关键发现: ' + inference.summary.keyFindings.length + ' 条');
  console.log('  冲突检测: ' + inference.conflicts.length + ' 个');
  console.log('  风险评分: ' + (inference.riskScore * 100).toFixed(0) + '/100');
  console.log('  建议数: ' + inference.summary.recommendations.length + ' 条');
  console.log('  缺失信息: ' + inference.missingInfo.length + ' 项');
  console.log('  关键节点: ' + inference.summary.keyFindings.slice(0, 3).join('；'));

  // 模块 6: 终端可视化
  console.log('\n' + sep);
  console.log('[6/8] 模块 6/8 terminal-visualizer - ASCII 架构图渲染');
  console.log(sep);
  console.log('  可视化内容: 三层图结构 + 压缩对比 + 评分分布 + 关键路径 + 标签云 + 关键发现');
  console.log(sep + '\n');
  console.log(renderVisualization(semantic, { width }));

  // 对比演示
  console.log('\n' + sep);
  console.log('[对比演示] 正常对话 vs 有问题对话');
  console.log(sep);
  const problemMsgs = createProblematicDialog();
  const problemResult = semanticCompress({ messages: problemMsgs, targetRatio: 0.4 });
  console.log('');
  console.log('                       正常对话          有问题对话');
  console.log('  消息数:              ' + messages.length + '               ' + problemMsgs.length);
  console.log('  压缩率:              ' + (semantic.summary.compressionRatio * 100).toFixed(0) + '%               ' + (problemResult.summary.compressionRatio * 100).toFixed(0) + '%');
  console.log('  保留节点:            ' + semantic.kept.length + '               ' + problemResult.kept.length);
  console.log('  语义标签数:          ' + Object.keys(semantic.globalStats.tagDistribution).length + '               ' + Object.keys(problemResult.globalStats.tagDistribution).length);

  // 系统能力总览
  console.log('\n\n' + bar);
  console.log(padCenter('系统能力总览', width));
  console.log(bar);
  console.log('');
  console.log(' 1. [graph-compress]              核心压缩: 关键词 + 元数据评分 (快速)');
  console.log(' 2. [semantic-compressor-advanced] 增强语义压缩: TF-IDF + 信息熵 + 语义标签 + 关键词桶');
  console.log(' 3. [auto-graph-generator]        自动图生成: 意图识别 + Blueprint/Architecture 自动构建');
  console.log(' 4. [skip-gate-integration]       Skip Gate 集成: 调度器决策记录 + 置信度追踪');
  console.log(' 5. [graph-inference-engine]      图结构推理: 冲突检测 + 风险评分 + 智能建议');
  console.log(' 6. [terminal-visualizer]          ASCII 可视化: 三层架构图 + 评分分布 + 关键路径');
  console.log('');
  console.log(bar);
  console.log(padCenter('完整工作流程', width));
  console.log(bar);
  console.log('');
  console.log(' 用户消息 → 语义压缩 → 自动图生成 → Skip Gate 记录 → 推理引擎 → ASCII 可视化');
  console.log('');
  console.log(bar);
  console.log(' 模块文件位置: 6-图结构上下文压缩/skills/graph-compressor/core/');
  console.log('  - graph-compress.ts               [核心压缩]');
  console.log('  - semantic-compressor-advanced.ts  [增强语义压缩] *NEW');
  console.log('  - auto-graph-generator.ts         [自动图生成]');
  console.log('  - skip-gate-integration.ts         [Skip Gate 集成]');
  console.log('  - graph-inference-engine.ts      [推理引擎]');
  console.log('  - terminal-visualizer.ts         [ASCII 可视化] *NEW');
  console.log('  - complete-demo.ts               [完整整合演示]');
  console.log('');
  console.log(' 运行演示: node --experimental-strip-types complete-demo.ts');
  console.log(bar);
  console.log('');
}

runCompleteDemo();
