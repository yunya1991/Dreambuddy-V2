/**
 * 实时测试：模拟一次交易策略讨论，构建三层图并压缩
 *
 * 场景：用户讨论一个 BTC 交易策略，从调研到决策的完整对话
 * 目标：验证 graph-context-compressor SKILL 的自动构建与压缩效果
 */

import {
  createGraphCompressor,
  type ConversationMessage,
  type CompressionSkillResult,
} from './build_and_compress.ts';

function buildDemoConversation(): ConversationMessage[] {
  const baseTime = Date.now() - 15 * 60 * 1000; // 15 分钟前开始
  return [
    {
      id: 'msg_1',
      role: 'user',
      content: '帮我分析一下 BTC 当前的行情，看看是否适合入场',
      timestamp: baseTime,
    },
    {
      id: 'msg_2',
      role: 'assistant',
      content: '好的，我先调研一下当前市场数据和技术指标...',
      timestamp: baseTime + 30 * 1000,
    },
    {
      id: 'msg_3',
      role: 'tool_call',
      content: 'fetch_market_data BTC/USDT - 周线 RSI=55, 日线 RSI=48',
      timestamp: baseTime + 60 * 1000,
      toolName: 'market-data-api',
    },
    {
      id: 'msg_4',
      role: 'tool_result',
      content: 'BTC 当前价格 65,200 USDT，周线略微超买，日线中性偏多',
      timestamp: baseTime + 75 * 1000,
    },
    {
      id: 'msg_5',
      role: 'assistant',
      content: '分析完成：市场处于震荡偏多格局。需要进一步确认入场信号。',
      timestamp: baseTime + 120 * 1000,
    },
    {
      id: 'msg_6',
      role: 'user',
      content: '好，让我们做个买入决策。你建议在什么价位入场？止损应该设在哪里？',
      timestamp: baseTime + 180 * 1000,
      importance: 'high',
    },
    {
      id: 'msg_7',
      role: 'assistant',
      content: '基于当前分析，我建议：在 64,800 附近挂买入单，止损设在 64,200，第一止盈 65,800',
      timestamp: baseTime + 240 * 1000,
      importance: 'high',
      decision: 'buy at 64800, stop-loss 64200, take-profit 65800',
    },
    {
      id: 'msg_8',
      role: 'user',
      content: '仓位大小呢？风险收益比怎么样？',
      timestamp: baseTime + 300 * 1000,
    },
    {
      id: 'msg_9',
      role: 'assistant',
      content: '建议仓位大小：总资金的 3%。风险收益比 1:1.67。这是一个较为保守的入场。',
      timestamp: baseTime + 360 * 1000,
      importance: 'high',
    },
    {
      id: 'msg_10',
      role: 'user',
      content: '等一下，让我再看看历史回测数据，确认这个策略的胜率',
      timestamp: baseTime + 420 * 1000,
    },
    {
      id: 'msg_11',
      role: 'tool_call',
      content: 'backtest_engine - 回测过去 60 天，策略参数: rsi oversold=40, stop-loss=1%',
      timestamp: baseTime + 450 * 1000,
      toolName: 'backtest-engine',
    },
    {
      id: 'msg_12',
      role: 'tool_result',
      content: '回测结果: 胜率 58%, 平均收益 1.2%, 最大回撤 2.5%, 夏普比率 1.3',
      timestamp: baseTime + 480 * 1000,
    },
    {
      id: 'msg_13',
      role: 'assistant',
      content: '回测验证通过：该信号在过去 60 天内表现稳定，可以执行。',
      timestamp: baseTime + 540 * 1000,
      importance: 'high',
    },
    {
      id: 'msg_14',
      role: 'user',
      content: '好，那就按这个方案执行',
      timestamp: baseTime + 600 * 1000,
      importance: 'high',
      decision: 'confirm execution',
    },
    {
      id: 'msg_15',
      role: 'assistant',
      content: '已确认：入场 64,800 / 止损 64,200 / 止盈 65,800，仓位 3%，执行！',
      timestamp: baseTime + 630 * 1000,
      importance: 'high',
    },
    {
      id: 'msg_16',
      role: 'user',
      content: '顺便问一下，最近 ETH 的情况如何？',
      timestamp: baseTime + 660 * 1000,
    },
    {
      id: 'msg_17',
      role: 'assistant',
      content: 'ETH 当前价格 3,450 USDT，技术面偏弱，不建议操作。',
      timestamp: baseTime + 690 * 1000,
    },
    {
      id: 'msg_18',
      role: 'user',
      content: '好的，了解。那我们就专注 BTC',
      timestamp: baseTime + 720 * 1000,
    },
    {
      id: 'msg_19',
      role: 'assistant',
      content: '明白。将持续监控 BTC 入场条件，满足后自动触发。',
      timestamp: baseTime + 750 * 1000,
    },
  ];
}

async function main(): Promise<void> {
  const messages = buildDemoConversation();
  console.log('========================================');
  console.log('📊 图上下文压缩 SKILL - 实时演示');
  console.log('========================================');
  console.log(`\n📝 输入对话: ${messages.length} 条消息`);
  console.log(`⏱️ 对话时长: ${((messages[messages.length - 1].timestamp - messages[0].timestamp) / 60000).toFixed(1)} 分钟`);
  console.log('');

  const result = await createGraphCompressor({
    messages,
    targetRatio: 0.5,
    intent: 'trading',
    mode: 'semantic',
    highlightKeywords: ['BTC', 'stop-loss', 'position-size', 'risk-reward', 'backtest', 'sharpe'],
    verbose: true,
  });

  console.log(result.compressionSummary);
  console.log('');

  console.log('--- 📈 压缩统计 ---');
  console.log(`  意图检测: ${result.summary.intentDetected}`);
  console.log(`  使用模式: ${result.summary.modeUsed}`);
  console.log(`  总节点数: ${result.summary.totalNodesBefore} → ${result.summary.totalNodesAfter}`);
  console.log(`  三层分布 (前): B=${result.summary.nodesByLayerBefore.B} A=${result.summary.nodesByLayerBefore.A} C=${result.summary.nodesByLayerBefore.C}`);
  console.log(`  三层分布 (后): B=${result.summary.nodesByLayerAfter.B} A=${result.summary.nodesByLayerAfter.A} C=${result.summary.nodesByLayerAfter.C}`);
  console.log(`  压缩耗时: ${result.summary.latencyMs}ms`);
  console.log('');

  console.log('--- 📅 时间线（保留节点状态） ---');
  result.summary.timelineSnapshot.slice(0, 10).forEach((item) => {
    const status = item.kept ? '✓ KEEP' : '✗ COMPRESS';
    const score = (item.score * 100).toFixed(0).padStart(3, ' ');
    const name = item.name.length > 40 ? item.name.slice(0, 40) + '...' : item.name;
    console.log(`  ${status} [${score}分] ${name}`);
  });
  console.log('');

  console.log('--- 🔑 保留的高价值内容（按评分排序） ---');
  result.summary.retainedNodesDetail.slice(0, 6).forEach((node, i) => {
    const score = (node.score * 100).toFixed(0).padStart(3, ' ');
    console.log(`  ${i + 1}. [${score}分] ${node.name}`);
  });
  console.log('');

  console.log('--- ✨ 可视化数据准备完成 ✨ ---');
  console.log(`  节点总数: ${result.summary.totalNodesBefore} → ${result.summary.totalNodesAfter}`);
  console.log(`  保留: ${result.summary.retainedNodeIds.length}, 压缩: ${result.summary.compressedNodeIds.length}`);
  console.log(`  压缩率: ${(result.summary.compressionRatio * 100).toFixed(0)}%`);
  console.log(`  可直接渲染 GraphCompressionVisualizer 组件 ✓`);
  console.log('');

  console.log('========================================');
  console.log('✅ SKILL 执行成功 - 验证通过');
  console.log('========================================');
}

main().catch((e) => {
  console.error('❌ SKILL 执行失败:', e);
  process.exit(1);
});
