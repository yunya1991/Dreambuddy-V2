/**
 * CompressorAdapter 压力测试
 *
 * 测试场景：
 * 1. 模拟多轮对话（10-100轮）
 * 2. 验证压缩效果（token 节省率）
 * 3. 测试降级路径（图文模块不可用时）
 * 4. 测试性能（吞吐量、延迟）
 */

import { CompressorAdapter, createFallbackResult, estimateTokens } from '../src/lib/compressor-adapter';

// ==================== 测试数据生成 ====================

function generateMockMessages(count: number): string[] {
  const templates = [
    'BTC 当前价格是多少？',
    'ETH 最近走势如何？',
    '分析一下 BTC 的支撑位和阻力位',
    '今天的行情怎么样？',
    '帮我设计一个 BTC 入场策略',
    '验证一下这个策略的回测结果',
    'SOL 的波动率分析',
    '黄金和 BTC 的相关性',
    '我的仓位应该怎么调整？',
    '市场情绪现在是贪婪还是恐惧？',
    '帮我分析一下宏观环境对加密市场的影响',
    '这个入场点位合理吗？',
    '止损应该设置在哪里？',
    '仓位大小怎么计算？',
    '帮我做一个资产配置方案',
  ];

  const messages: string[] = [];
  for (let i = 0; i < count; i++) {
    const template = templates[i % templates.length];
    // 添加一些随机内容增加 token 数
    const extra = ` [轮次${i + 1}] ${Math.random().toString(36).slice(2, 8)}`;
    messages.push(template + extra);
  }
  return messages;
}

// ==================== 测试用例 ====================

async function testBasicCompression() {
  console.log('\n=== 测试 1: 基础压缩功能 ===');

  const adapter = new CompressorAdapter({ enabled: true });
  await adapter.initialize();

  const messages = generateMockMessages(15);
  const items = messages.map((msg, idx) => ({
    id: `msg-${idx}`,
    type: 'message' as const,
    content: msg,
    tokens: estimateTokens(msg),
  }));

  const result = await adapter.compress({
    sessionId: 'test-session-001',
    payload: items,
    targetRatio: 0.5,
  });

  console.log(`原始 tokens: ${result.originalTokens}`);
  console.log(`压缩后 tokens: ${result.compressedTokens}`);
  console.log(`压缩比: ${result.compressionRatio.toFixed(2)}`);
  console.log(`节省: ${((1 - result.compressionRatio) * 100).toFixed(1)}%`);
  console.log(`节点数: ${result.stats.totalNodes}`);
  console.log(`健康状态: ${JSON.stringify(adapter.health())}`);

  return result;
}

async function testMultipleRounds() {
  console.log('\n=== 测试 2: 多轮压缩（模拟真实对话） ===');

  const adapter = new CompressorAdapter({ enabled: true });
  await adapter.initialize();

  const rounds = [10, 20, 50, 100];
  const results: Array<{ rounds: number; ratio: number; latencyMs: number }> = [];

  for (const roundCount of rounds) {
    const messages = generateMockMessages(roundCount);
    const items = messages.map((msg, idx) => ({
      id: `msg-${idx}`,
      type: 'message' as const,
      content: msg,
      tokens: estimateTokens(msg),
    }));

    const start = Date.now();
    const result = await adapter.compress({
      sessionId: `test-rounds-${roundCount}`,
      payload: items,
      targetRatio: 0.5,
    });
    const latency = Date.now() - start;

    results.push({
      rounds: roundCount,
      ratio: result.compressionRatio,
      latencyMs: latency,
    });

    console.log(`${roundCount}轮: ${result.originalTokens} → ${result.compressedTokens} tokens | 节省${((1 - result.compressionRatio) * 100).toFixed(1)}% | ${latency}ms`);
  }

  return results;
}

async function testFallbackMode() {
  console.log('\n=== 测试 3: 降级模式（图文模块不可用） ===');

  // 强制使用降级模式（modulePath 设置为无效路径）
  const adapter = new CompressorAdapter({
    enabled: true,
    modulePath: '/nonexistent/path',
  });
  await adapter.initialize();

  console.log(`健康状态: ${JSON.stringify(adapter.health())}`);

  const messages = generateMockMessages(20);
  const items = messages.map((msg, idx) => ({
    id: `msg-${idx}`,
    type: 'message' as const,
    content: msg,
    tokens: estimateTokens(msg),
  }));

  const result = await adapter.compress({
    sessionId: 'test-fallback',
    payload: items,
    targetRatio: 0.5,
  });

  console.log(`降级模式压缩比: ${result.compressionRatio.toFixed(2)}`);
  console.log(`策略: ${result.report?.strategy}`);
}

async function testThroughput() {
  console.log('\n=== 测试 4: 吞吐量测试 ===');

  const adapter = new CompressorAdapter({ enabled: true });
  await adapter.initialize();

  const iterations = 100;
  const messages = generateMockMessages(15);
  const items = messages.map((msg, idx) => ({
    id: `msg-${idx}`,
    type: 'message' as const,
    content: msg,
    tokens: estimateTokens(msg),
  }));

  const start = Date.now();
  let totalCompressed = 0;
  let totalOriginal = 0;

  for (let i = 0; i < iterations; i++) {
    const result = await adapter.compress({
      sessionId: `throughput-${i}`,
      payload: items,
      targetRatio: 0.5,
    });
    totalOriginal += result.originalTokens;
    totalCompressed += result.compressedTokens;
  }

  const duration = Date.now() - start;
  const throughput = iterations / (duration / 1000);

  console.log(`总耗时: ${duration}ms`);
  console.log(`吞吐量: ${throughput.toFixed(1)} 次/秒`);
  console.log(`平均压缩比: ${(totalCompressed / totalOriginal).toFixed(2)}`);
  console.log(`统计: ${JSON.stringify(adapter.getStats())}`);
}

async function testDisabledMode() {
  console.log('\n=== 测试 5: 禁用模式 ===');

  const adapter = new CompressorAdapter({ enabled: false });
  await adapter.initialize();

  console.log(`健康状态: ${JSON.stringify(adapter.health())}`);

  const messages = generateMockMessages(20);
  const items = messages.map((msg, idx) => ({
    id: `msg-${idx}`,
    type: 'message' as const,
    content: msg,
    tokens: estimateTokens(msg),
  }));

  const result = await adapter.compress({
    sessionId: 'test-disabled',
    payload: items,
    targetRatio: 0.5,
  });

  console.log(`禁用模式压缩比: ${result.compressionRatio.toFixed(2)}（应为 1.0）`);
}

// ==================== 主入口 ====================

async function main() {
  console.log('========================================');
  console.log('CompressorAdapter 压力测试');
  console.log('========================================');

  try {
    await testBasicCompression();
    await testMultipleRounds();
    await testFallbackMode();
    await testThroughput();
    await testDisabledMode();

    console.log('\n========================================');
    console.log('所有测试完成 ✓');
    console.log('========================================');
  } catch (err) {
    console.error('\n测试失败:', err);
    process.exit(1);
  }
}

main();
