/**
 * 增强版：语义压缩 / 分片压缩 / 意图路由 / 可视化 — 端到端测试
 */

import { createCompressor, blueprintRegistry, shardedCompress, semanticCompress } from '../../../6-图结构上下文压缩/index.ts';
import { createBlueprint } from '../../../6-图结构上下文压缩/blueprint.ts';
import { expandToArchitecture } from '../../../6-图结构上下文压缩/architecture.ts';
import { expandToChronicle } from '../../../6-图结构上下文压缩/chronicle.ts';
import { compress } from '../../../6-图结构上下文压缩/compressor.ts';
import { buildVisualization } from '../../../6-图结构上下文压缩/visualization.ts';

function header(title: string) {
  console.log(`\n==================== ${title} ====================\n`);
}

// ===================== 1. 测试四种模式 =====================
async function testModes() {
  header('测试 1：4 种压缩模式');
  const modes: Array<'basic' | 'semantic' | 'sharded' | 'auto'> = ['basic', 'semantic', 'sharded', 'auto'];
  for (const mode of modes) {
    const c = createCompressor({ mode, defaultTargetRatio: 0.5 });
    console.log(`  [${mode}] 初始化成功，mode=${c.getMode()}`);

    const result = await c.compress({
      sessionId: `session-${mode}`,
      payload: [
        { id: '1', type: 'message', content: '分析比特币市场趋势，寻找入场信号' },
        { id: '2', type: 'message', content: 'RSI 指标显示超卖，MACD 有金叉迹象' },
        { id: '3', type: 'tool_call', content: '调用 K线分析工具，识别支撑阻力位' },
        { id: '4', type: 'message', content: '止损设置在 40000，止盈设置在 45000' },
        { id: '5', type: 'log', content: '当前持仓：BTC 0.5，ETH 10，USDT 10000' },
        { id: '6', type: 'tool_call', content: '计算风险指标：仓位风险、波动率、最大回撤' },
        { id: '7', type: 'message', content: '建议等待确认信号，不要急于入场' },
      ],
      targetRatio: 0.5,
    });

    console.log(
      `  [${mode}] compressionRatio=${result.compressionRatio.toFixed(3)} ` +
      `retained=${result.stats.retainedNodes} compressed=${result.stats.compressedNodes}`
    );
    console.log(`  [${mode}] strategy: ${result.report?.strategy}`);
  }
}

// ===================== 2. 测试语义压缩的评分细节 =====================
function testSemanticScoring() {
  header('测试 2：语义评分细节');
  const bp = createBlueprint('test-semantic');
  const arch = expandToArchitecture(bp);
  const chronicle = expandToChronicle(arch, 'test-semantic');

  // 注入不同语义价值的节点
  const nodes = [
    { name: 'BTC 价格分析，RSI 超卖，MACD 金叉', tokens: 50, time: 1 },
    { name: '策略风险评估：止损 40000，止盈 45000', tokens: 50, time: 2 },
    { name: '用户个人信息：昵称 张三，邮箱 zhang@example.com', tokens: 50, time: 3 },
    { name: '执行决策：建议等待确认信号后再入场', tokens: 50, time: 4 },
    { name: '日志冗余：心跳检查、连接重试、session 续期', tokens: 50, time: 5 },
    { name: '入场信号识别：突破 42000 确认买入，仓位 20%', tokens: 50, time: 6 },
  ];
  nodes.forEach((n, idx) => {
    chronicle.nodes.set(`n${idx}`, {
      id: `n${idx}`,
      architectureNodeId: `step_${idx}`,
      executionId: 'test',
      startTime: n.time,
      endTime: n.time + 1,
      metadata: {
        tokenCost: n.tokens,
        latencyMs: 50,
        status: 'completed',
        outputSummary: n.name,
        timestamp: n.time,
      },
      inputs: {},
      outputs: { content: n.name },
      logs: [],
    });
  });

  const result = semanticCompress(chronicle, arch, bp, { targetRatio: 0.5 });
  console.log(`  原始节点：${nodes.length}`);
  console.log(`  压缩比：${result.compressionRatio.toFixed(3)}`);
  console.log('\n  各节点评分与状态：');
  chronicle.nodes.forEach((node, id) => {
    const score = (result.nodeScores?.get(id) ?? 0).toFixed(3);
    const compressed = result.compressedChronicle.nodes.get(id)?.metadata.status === 'compressed' ? '✗ 压缩' : '✓ 保留';
    console.log(`    ${score}  ${compressed}  — ${node.metadata.outputSummary}`);
  });
  console.log('\n  丢弃详情：');
  result.discardedDetails.forEach((d) => {
    console.log(`    - ${d.nodeId}: ${d.reason}`);
  });
}

// ===================== 3. 测试分片压缩（长对话） =====================
function testShardedCompression() {
  header('测试 3：分片压缩（120 条记录模拟）');
  const bp = createBlueprint('test-sharded');
  const arch = expandToArchitecture(bp);
  const chronicle = expandToChronicle(arch, 'test-sharded');

  // 模拟 120 条对话记录
  for (let i = 0; i < 120; i++) {
    const types = [
      '分析市场趋势',
      '读取 K线数据',
      '计算技术指标',
      '用户个人信息',
      '执行交易决策',
      '日志记录',
      '风险评估',
    ];
    const name = `[第 ${i} 条] ${types[i % types.length]} - 关于 BTC/ETH/USDT 交易决策与风险控制`;
    chronicle.nodes.set(`shard-node-${i}`, {
      id: `shard-node-${i}`,
      architectureNodeId: `step_${i}`,
      executionId: 'test',
      startTime: i,
      endTime: i + 1,
      metadata: {
        tokenCost: 50 + i % 20,
        latencyMs: 30 + i % 30,
        status: 'completed',
        outputSummary: name,
        timestamp: i,
      },
      inputs: {},
      outputs: { content: name },
      logs: [],
    });
  }

  const shardResult = shardedCompress(chronicle, arch, bp, {
    shardSize: 50,
    targetRatio: 0.6,
    useSemantic: true,
  });

  const totalNodes = chronicle.nodes.size;
  let retained = 0;
  shardResult.compressedChronicle.nodes.forEach((node) => {
    if (node.metadata.status !== 'compressed') retained++;
  });

  console.log(`  总节点数：${totalNodes}`);
  console.log(`  保留节点：${retained}`);
  console.log(`  压缩节点：${totalNodes - retained}`);
  console.log(`  压缩比：${shardResult.compressionRatio.toFixed(3)}`);
  console.log(`  丢弃节点列表（前 5 条）：`);
  shardResult.discardedDetails.slice(0, 5).forEach((d) => {
    console.log(`    - ${d.nodeId}: ${d.reason}`);
  });

  // 对比：非分片模式
  const nonShardResult = compress(chronicle, arch, bp, { targetRatio: 0.6 });
  console.log(`\n  非分片压缩：ratio=${nonShardResult.compressionRatio.toFixed(3)} retained=${nonShardResult.compressedChronicle.nodes.size}`);
}

// ===================== 4. 测试意图路由 =====================
function testIntentRouting() {
  header('测试 4：跨 session 架构模板意图路由');
  const intents = [
    '买入 BTC 做多，分析趋势',
    '深度分析 ETH 市场，研究基本面',
    '我的持仓需要再平衡',
    '入场信号：何时买入 ETH',
  ];

  intents.forEach((intent) => {
    const matched = blueprintRegistry.routeByIntent(intent);
    if (matched) {
      const bNodes = Array.from(matched.blueprint.nodes.values());
      console.log(`  "${intent}" → ${matched.name} (${bNodes.length} 个组件)`);
    } else {
      console.log(`  "${intent}" → 无匹配（fallback）`);
    }
  });

  console.log('\n  所有模板使用计数：');
  blueprintRegistry.listAll().forEach((tpl) => {
    console.log(`    - ${tpl.name}: useCount=${tpl.useCount}`);
  });
}

// ===================== 5. 测试可视化数据 =====================
async function testVisualization() {
  header('测试 5：可视化数据生成');
  const c = createCompressor({ mode: 'semantic', defaultTargetRatio: 0.5 });

  const input = {
    sessionId: 'viz-test',
    payload: [
      { id: '1', type: 'message', content: 'BTC 趋势分析，RSI 超卖，MACD 金叉' },
      { id: '2', type: 'message', content: 'ETH 价格突破阻力位，建议等待确认' },
      { id: '3', type: 'tool_call', content: '调用 K线工具，识别支撑位 40000' },
      { id: '4', type: 'message', content: '止损设置：BTC 40000，ETH 2500' },
      { id: '5', type: 'message', content: '仓位建议：BTC 20%，ETH 15%' },
      { id: '6', type: 'log', content: '日志：连接重试 3 次，心跳正常' },
      { id: '7', type: 'tool_call', content: '计算风险指标：仓位风险、最大回撤' },
      { id: '8', type: 'message', content: '最终决策：等待确认信号再入场' },
    ],
    targetRatio: 0.5,
  };

  // 先执行压缩
  const compressResult = await c.compress(input);
  console.log(`  压缩完成：ratio=${compressResult.compressionRatio.toFixed(3)}`);

  // 再获取可视化数据
  const viz = await c.getVisualizationData(input);

  console.log(`\n  统计信息：`);
  console.log(`    压缩前总节点：${viz.stats.totalNodesBefore}`);
  console.log(`    压缩后总节点：${viz.stats.totalNodesAfter}`);
  console.log(`    压缩比：${viz.stats.compressionRatio.toFixed(3)}`);
  console.log(`    保留上下文比例：${viz.stats.retainedContext.toFixed(3)}`);
  console.log(`    各层分布 B/A-C: before=${viz.stats.nodesByLayerBefore.B}/${viz.stats.nodesByLayerBefore.A}/${viz.stats.nodesByLayerBefore.C}`);
  console.log(`                 after=${viz.stats.nodesByLayerAfter.B}/${viz.stats.nodesByLayerAfter.A}/${viz.stats.nodesByLayerAfter.C}`);

  console.log(`\n  时间线（保留状态）：`);
  viz.timeline.slice(0, 10).forEach((item) => {
    const icon = item.kept ? '✓' : '✗';
    console.log(`    ${icon} ${item.name} (score=${item.score.toFixed(2)}, status=${item.status})`);
  });

  console.log(`\n  差异摘要：`);
  console.log(`    保留节点数：${viz.diff.retained.length}`);
  console.log(`    压缩节点数：${viz.diff.compressed.length}`);
  console.log(`    保留节点平均得分：${viz.diff.avgRetainedScore.toFixed(3)}`);
  console.log(`    压缩节点平均得分：${viz.diff.avgCompressedScore.toFixed(3)}`);

  // 直接调用底层 buildVisualization
  console.log(`\n  [底层] buildVisualization 调用：`);
  const bp = createBlueprint('test-viz-direct');
  const arch = expandToArchitecture(bp);
  const chronicle = expandToChronicle(arch, 'test-viz-direct');
  for (let i = 0; i < 10; i++) {
    chronicle.nodes.set(`dn-${i}`, {
      id: `dn-${i}`,
      architectureNodeId: `direct-node-${i}`,
      executionId: 'test',
      startTime: i,
      endTime: i + 1,
      metadata: {
        tokenCost: 40,
        latencyMs: 30,
        status: 'completed',
        outputSummary: `节点 ${i}: 测试内容 ${i}`,
        timestamp: i,
      },
      inputs: {},
      outputs: { content: `节点 ${i}` },
      logs: [],
    });
  }
  const directResult = semanticCompress(chronicle, arch, bp, { targetRatio: 0.5 });
  const directViz = buildVisualization(directResult);
  console.log(`    before C.nodes=${directViz.before.C.nodes.length} after=${directViz.after.C.nodes.length}`);
  console.log(`    timeline items=${directViz.timeline.length}`);
}

// ===================== 6. 测试 fallback 场景 =====================
async function testFallback() {
  header('测试 6：降级场景（token 太少不压缩）');
  const c = createCompressor({ mode: 'basic' });
  const smallResult = await c.compress({
    sessionId: 'small',
    payload: [{ id: '1', type: 'message', content: '短消息（不应触发压缩）', tokens: 10 }],
  });
  console.log(`  小输入压缩结果：ratio=${smallResult.compressionRatio.toFixed(3)}（应为 1，意味着不压缩）`);
  console.log(`  stats: totalNodes=${smallResult.stats.totalNodes} retained=${smallResult.stats.retainedNodes}`);
}

// ===================== 主入口 =====================
async function main() {
  header('增强版压缩模块 — 端到端测试');
  console.log(`  模块版本: ${createCompressor().getMode ? 'OK' : 'NOT OK'}`);

  await testModes();
  testSemanticScoring();
  testShardedCompression();
  testIntentRouting();
  await testVisualization();
  await testFallback();

  header('✅ 所有测试完成');
  const stats = createCompressor({ mode: 'basic' }).getStats();
  console.log(`  totalCompressions=${stats.totalCompressions}`);
}

main().catch((err) => {
  console.error('测试失败：', err);
  process.exit(1);
});
