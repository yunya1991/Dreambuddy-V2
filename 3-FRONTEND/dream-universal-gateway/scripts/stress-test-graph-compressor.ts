/**
 * 图架构上下文压缩模块 - 复杂场景压力测试
 *
 * 测试内容:
 * 1. 基础压缩功能
 * 2. 四种压缩模式: basic / semantic / sharded / auto
 * 3. 意图路由与 Blueprint 复用
 * 4. 可视化数据生成
 * 5. 长对话分片压缩
 * 6. 并发压缩
 * 7. 异常处理
 */

import {
  createCompressor,
  blueprintRegistry,
  buildVisualization,
  VERSION,
} from '../../../6-图结构上下文压缩/index.ts';

// ============================================================
// 测试场景定义
// ============================================================

interface CompressionScenario {
  name: string;
  sessionId: string;
  payload: Array<{
    id: string;
    type: 'message' | 'step' | 'tool_call';
    content: string;
    tokens?: number;
  }>;
  targetRatio?: number;
  mode?: 'basic' | 'semantic' | 'sharded' | 'auto';
  metadata?: Record<string, unknown>;
}

function generateLongConversation(count: number, baseContent: string) {
  const messages = [];
  const actions = [
    '正在分析市场趋势',
    '检测到 RSI 超买信号',
    'MACD 金叉形成',
    '成交量放大确认',
    '均线系统多头排列',
    '布林带收口',
    '波动率指标提示突破',
    '资金费率正向',
    '链上活跃度上升',
    '恐惧贪婪指数偏贪婪',
  ];

  for (let i = 0; i < count; i++) {
    const isUser = i % 2 === 0;
    messages.push({
      id: `msg-${i}`,
      type: isUser ? 'message' : 'step' as const,
      content: isUser
        ? `用户消息 ${i}: ${baseContent} 的第 ${i + 1} 次交互分析`
        : `${actions[i % actions.length]} - ${baseContent} - 步骤 ${i + 1} 完成，分析结论：当前处于震荡上行趋势，建议关注支撑位 95000 美元，若突破 100000 美元可考虑顺势做多，止损设置在 94000 美元。`,
      tokens: isUser ? 20 + Math.floor(Math.random() * 30) : 80 + Math.floor(Math.random() * 150),
    });
  }
  return messages;
}

const SCENARIOS: CompressionScenario[] = [
  // ===== 场景1-3: 基础功能测试 =====
  {
    name: '场景1: 基础压缩 - 简单对话',
    sessionId: 'test-basic-01',
    payload: [
      { id: '1', type: 'message', content: '分析 BTC 当前走势' },
      { id: '2', type: 'step', content: '技术指标分析: RSI=65, MACD=0.5, 均线多头排列' },
      { id: '3', type: 'message', content: '建议如何操作？' },
    ],
    targetRatio: 0.3,
    mode: 'basic',
  },
  {
    name: '场景2: 基础压缩 - 完整分析流程',
    sessionId: 'test-basic-02',
    payload: [
      { id: '1', type: 'message', content: '帮我分析 ETH' },
      { id: '2', type: 'step', content: '市场扫描: 检测到 ETH 处于上升趋势' },
      { id: '3', type: 'step', content: '技术分析: RSI=58, MACD 绿柱放大, 突破前高' },
      { id: '4', type: 'step', content: '风险评估: 波动率适中，可以考虑 15% 仓位' },
      { id: '5', type: 'step', content: '执行建议: 建议在 3500 美元附近买入，止损 3400 美元' },
      { id: '6', type: 'message', content: '好的，帮我下单' },
    ],
    targetRatio: 0.5,
    mode: 'basic',
  },
  {
    name: '场景3: 基础压缩 - 边界值',
    sessionId: 'test-basic-03',
    payload: [
      { id: '1', type: 'message', content: '单条消息测试' },
    ],
    targetRatio: 0.9,
    mode: 'basic',
  },

  // ===== 场景4-6: 语义压缩测试 =====
  {
    name: '场景4: 语义压缩 - 中等对话',
    sessionId: 'test-semantic-01',
    payload: [
      { id: '1', type: 'message', content: '深度分析 SOL 市场' },
      { id: '2', type: 'step', content: '【技术面】RSI=62, MACD=0.35, 均线 MA5>MA20>MA60 多头排列' },
      { id: '3', type: 'step', content: '【资金面】24h 净流入 1200 万美元，大户地址增持' },
      { id: '4', type: 'step', content: '【情绪面】社交媒体讨论热度上升 45%，看多情绪占比 68%' },
      { id: '5', type: 'step', content: '【综合判断】建议 20% 仓位买入，止损设置 5%' },
      { id: '6', type: 'message', content: 'SOL 现在可以买吗？' },
      { id: '7', type: 'step', content: '根据分析，SOL 处于上升趋势中的健康回调，可考虑分批建仓' },
    ],
    targetRatio: 0.4,
    mode: 'semantic',
  },
  {
    name: '场景5: 语义压缩 - 交易意图',
    sessionId: 'test-semantic-02',
    payload: [
      { id: '1', type: 'message', content: '我想做空 BTC' },
      { id: '2', type: 'step', content: '风险评估: 当前市场情绪偏多，做空风险较高' },
      { id: '3', type: 'step', content: '技术面: BTC 在 98000 美元获得支撑，RSI=45 未超卖' },
      { id: '4', type: 'step', content: '建议: 等待反弹至 102000 美元附近出现做空信号再考虑' },
    ],
    targetRatio: 0.3,
    mode: 'semantic',
    metadata: { intent: '做空 BTC 交易' },
  },
  {
    name: '场景6: 语义压缩 - 策略研究',
    sessionId: 'test-semantic-03',
    payload: [
      { id: '1', type: 'message', content: '研究双均线交叉策略' },
      { id: '2', type: 'step', content: '策略定义: 当 MA20 上穿 MA60 时买入，下穿时卖出' },
      { id: '3', type: 'step', content: '回测结果: 2023 年胜率 58%，夏普比率 1.2，最大回撤 18%' },
      { id: '4', type: 'step', content: '参数优化: 最佳参数 MA(15, 45)，胜率提升至 62%' },
      { id: '5', type: 'step', content: '实盘建议: 适合趋势行情，震荡市需配合其他指标过滤' },
    ],
    targetRatio: 0.5,
    mode: 'semantic',
  },

  // ===== 场景7-9: 分片压缩测试 =====
  {
    name: '场景7: 分片压缩 - 长对话 (50条)',
    sessionId: 'test-sharded-01',
    payload: generateLongConversation(50, 'BTC'),
    targetRatio: 0.6,
    mode: 'sharded',
  },
  {
    name: '场景8: 分片压缩 - 超长对话 (100条)',
    sessionId: 'test-sharded-02',
    payload: generateLongConversation(100, 'ETH'),
    targetRatio: 0.7,
    mode: 'sharded',
  },
  {
    name: '场景9: 分片压缩 - 极长对话 (200条)',
    sessionId: 'test-sharded-03',
    payload: generateLongConversation(200, 'SOL'),
    targetRatio: 0.8,
    mode: 'sharded',
  },

  // ===== 场景10-12: 自动模式测试 =====
  {
    name: '场景10: 自动模式 - 短对话 (5条)',
    sessionId: 'test-auto-01',
    payload: generateLongConversation(5, 'AVAX'),
    targetRatio: 0.3,
    mode: 'auto',
  },
  {
    name: '场景11: 自动模式 - 中对话 (30条)',
    sessionId: 'test-auto-02',
    payload: generateLongConversation(30, 'MATIC'),
    targetRatio: 0.5,
    mode: 'auto',
  },
  {
    name: '场景12: 自动模式 - 长对话 (80条)',
    sessionId: 'test-auto-03',
    payload: generateLongConversation(80, 'PEPE'),
    targetRatio: 0.6,
    mode: 'auto',
  },

  // ===== 场景13-15: Blueprint 意图路由测试 =====
  {
    name: '场景13: Blueprint路由 - 经典交易',
    sessionId: 'test-blueprint-01',
    payload: [
      { id: '1', type: 'message', content: '用经典指标系统分析 BTC' },
      { id: '2', type: 'step', content: 'RSI=60, MACD=0.4, 多头信号' },
    ],
    targetRatio: 0.4,
    mode: 'auto',
    metadata: { intent: '经典交易分析' },
  },
  {
    name: '场景14: Blueprint路由 - 深度分析',
    sessionId: 'test-blueprint-02',
    payload: [
      { id: '1', type: 'message', content: '进行深度市场分析报告' },
      { id: '2', type: 'step', content: '宏观分析: 利率预期下降，利好风险资产' },
      { id: '3', type: 'step', content: '技术分析: 周线级别上涨趋势' },
      { id: '4', type: 'step', content: '情绪分析: 恐惧贪婪指数 65' },
    ],
    targetRatio: 0.5,
    mode: 'auto',
    metadata: { intent: '深度分析报告' },
  },
  {
    name: '场景15: Blueprint路由 - 持仓管理',
    sessionId: 'test-blueprint-03',
    payload: [
      { id: '1', type: 'message', content: '检查我的持仓风险' },
      { id: '2', type: 'step', content: '总持仓: 3 个币种，总价值 $50,000' },
      { id: '3', type: 'step', content: '风险评估: 整体风险适中，建议做适当分散' },
    ],
    targetRatio: 0.4,
    mode: 'auto',
    metadata: { intent: '持仓风险管理' },
  },

  // ===== 场景16-18: 边界异常测试 =====
  {
    name: '场景16: 异常处理 - 空会话',
    sessionId: 'test-error-01',
    payload: [],
    targetRatio: 0.5,
    mode: 'basic',
  },
  {
    name: '场景17: 异常处理 - 超长单条消息',
    sessionId: 'test-error-02',
    payload: [
      {
        id: '1',
        type: 'message',
        content: 'A'.repeat(10000) + ' - 这是一条超长的消息内容，用于测试系统的边界处理能力，包括内存管理和字符串处理。'.repeat(100),
      },
    ],
    targetRatio: 0.9,
    mode: 'auto',
  },
  {
    name: '场景18: 异常处理 - 全空内容',
    sessionId: 'test-error-03',
    payload: [
      { id: '1', type: 'message', content: '   ' },
      { id: '2', type: 'step', content: '' },
      { id: '3', type: 'tool_call', content: '\n\n\n' },
    ],
    targetRatio: 0.5,
    mode: 'basic',
  },

  // ===== 场景19-20: 高压缩率测试 =====
  {
    name: '场景19: 高压缩 - 保留10%',
    sessionId: 'test-ratio-01',
    payload: generateLongConversation(30, 'BTC'),
    targetRatio: 0.9,
    mode: 'semantic',
  },
  {
    name: '场景20: 高压缩 - 保留50%',
    sessionId: 'test-ratio-02',
    payload: generateLongConversation(30, 'ETH'),
    targetRatio: 0.5,
    mode: 'semantic',
  },

  // ===== 场景21: 多币种轮询 =====
  {
    name: '场景21: 多币种轮询 (5个session)',
    sessionId: 'test-multi-01',
    payload: [
      { id: '1', type: 'message', content: 'BTC 分析' },
      { id: '2', type: 'step', content: 'BTC: RSI=65, 建议观望' },
      { id: '3', type: 'message', content: 'ETH 分析' },
      { id: '4', type: 'step', content: 'ETH: RSI=58, 可考虑买入' },
    ],
    targetRatio: 0.3,
    mode: 'auto',
  },
];

// ============================================================
// 测试执行
// ============================================================

interface TestResult {
  name: string;
  mode: string;
  itemCount: number;
  originalTokens: number;
  compressedTokens: number;
  compressionRatio: number;
  retainedNodes: number;
  compressedNodes: number;
  duration: number;
  success: boolean;
  error?: string;
  blueprint?: string;
}

async function runCompressionScenario(
  scenario: CompressionScenario,
  compressor: ReturnType<typeof createCompressor>
): Promise<TestResult> {
  const startTime = Date.now();

  try {
    const result = await compressor.compress({
      sessionId: scenario.sessionId,
      payload: scenario.payload,
      targetRatio: scenario.targetRatio,
      metadata: scenario.metadata,
    });

    return {
      name: scenario.name,
      mode: scenario.mode || 'auto',
      itemCount: scenario.payload.length,
      originalTokens: result.originalTokens,
      compressedTokens: result.compressedTokens,
      compressionRatio: result.compressionRatio,
      retainedNodes: result.stats.retainedNodes,
      compressedNodes: result.stats.compressedNodes,
      duration: Date.now() - startTime,
      success: true,
      blueprint: result.graph.architecture?.[0]?.type || 'unknown',
    };
  } catch (error) {
    return {
      name: scenario.name,
      mode: scenario.mode || 'auto',
      itemCount: scenario.payload.length,
      originalTokens: 0,
      compressedTokens: 0,
      compressionRatio: 1,
      retainedNodes: 0,
      compressedNodes: 0,
      duration: Date.now() - startTime,
      success: false,
      error: error instanceof Error ? error.message : 'Unknown error',
    };
  }
}

async function runVisualizationTest(
  scenario: CompressionScenario,
  compressor: ReturnType<typeof createCompressor>
): Promise<{ success: boolean; error?: string }> {
  try {
    const vizData = await compressor.getVisualizationData({
      sessionId: scenario.sessionId,
      payload: scenario.payload,
      targetRatio: scenario.targetRatio,
    });

    // 验证可视化数据结构
    const hasBefore = vizData.before && Object.keys(vizData.before).length === 3;
    const hasAfter = vizData.after && Object.keys(vizData.after).length === 3;
    const hasDiff = vizData.diff && vizData.diff.retained !== undefined;
    const hasStats = vizData.stats && vizData.stats.totalNodesBefore !== undefined;
    const hasTimeline = Array.isArray(vizData.timeline);

    return {
      success: hasBefore && hasAfter && hasDiff && hasStats && hasTimeline,
    };
  } catch (error) {
    return {
      success: false,
      error: error instanceof Error ? error.message : 'Unknown error',
    };
  }
}

async function runStressTest() {
  console.log('='.repeat(100));
  console.log('  图架构上下文压缩模块 - 复杂场景压力测试');
  console.log(`  版本: ${VERSION}`);
  console.log('='.repeat(100));
  console.log('');

  // -------------------- 初始化 --------------------
  console.log('[初始化] 创建压缩器...');
  const compressor = createCompressor({
    mode: 'auto',
    defaultTargetRatio: 0.5,
    onError: (err) => console.error('压缩错误:', err.message),
  });

  const health = await compressor.health();
  console.log(`  ✓ 健康状态: ${health.healthy ? '正常' : '异常'}`);
  console.log(`  ✓ 版本: ${health.version}`);
  console.log(`  ✓ 运行时间: ${(health.uptimeMs / 1000).toFixed(2)}s`);
  console.log('');

  // 打印 Blueprint 统计
  const blueprintList = blueprintRegistry.listAll();
  console.log(`[初始化] Blueprint 注册表: ${blueprintList.length} 个模板`);
  for (const bp of blueprintList) {
    console.log(`  - ${bp.name}: 使用 ${bp.useCount} 次，平均压缩率 ${(bp.avgRatio * 100).toFixed(1)}%`);
  }
  console.log('');

  // -------------------- 顺序执行测试 --------------------
  console.log('[测试1/4] 顺序执行所有压缩场景...');
  console.log('-'.repeat(100));

  const results: TestResult[] = [];
  for (const scenario of SCENARIOS) {
    process.stdout.write(`  ${scenario.name.slice(0, 25).padEnd(25)}`);
    const result = await runCompressionScenario(scenario, compressor);
    results.push(result);

    const status = result.success
      ? `✓ ${result.itemCount}条 ${result.originalTokens}t→${result.compressedTokens}t (${(result.compressionRatio * 100).toFixed(0)}%) ${result.duration}ms`
      : `✗ ${result.error?.slice(0, 30)}`;

    console.log(` ${status}`);
  }

  console.log('-'.repeat(100));
  console.log('');

  // -------------------- 并发测试 --------------------
  console.log('[测试2/4] 高并发压缩测试 (20 并发)...');
  console.log('-'.repeat(100));

  const concurrentScenarios = SCENARIOS.slice(0, 10).map((s, i) => ({
    ...s,
    sessionId: `concurrent-${i}-${Date.now()}`,
  }));

  const startConcurrent = Date.now();
  const concurrentResults = await Promise.all(
    concurrentScenarios.map((s) => runCompressionScenario(s, compressor))
  );
  const concurrentDuration = Date.now() - startConcurrent;

  let concurrentSuccess = 0;
  for (const r of concurrentResults) {
    if (r.success) concurrentSuccess++;
  }

  console.log(`  总耗时: ${concurrentDuration}ms`);
  console.log(`  成功率: ${concurrentSuccess}/${concurrentScenarios.length} (${(concurrentSuccess / concurrentScenarios.length * 100).toFixed(1)}%)`);
  console.log(`  平均耗时: ${(concurrentDuration / concurrentScenarios.length).toFixed(2)}ms/请求`);
  console.log('-'.repeat(100));
  console.log('');

  // -------------------- 可视化数据测试 --------------------
  console.log('[测试3/4] 可视化数据生成测试...');
  console.log('-'.repeat(100));

  const vizTestScenarios = SCENARIOS.slice(0, 5);
  let vizSuccess = 0;

  for (const scenario of vizTestScenarios) {
    const result = await runVisualizationTest(scenario, compressor);
    if (result.success) {
      vizSuccess++;
      console.log(`  ✓ ${scenario.name.slice(0, 30)} - 可视化数据生成成功`);
    } else {
      console.log(`  ✗ ${scenario.name.slice(0, 30)} - ${result.error || '数据验证失败'}`);
    }
  }

  console.log(`  可视化成功率: ${vizSuccess}/${vizTestScenarios.length}`);
  console.log('-'.repeat(100));
  console.log('');

  // -------------------- 统计汇总 --------------------
  console.log('[测试4/4] 统计汇总...');
  console.log('');

  const totalScenarios = results.length;
  const successCount = results.filter((r) => r.success).length;
  const failCount = totalScenarios - successCount;
  const avgDuration = results.reduce((sum, r) => sum + r.duration, 0) / totalScenarios;
  const maxDuration = Math.max(...results.map((r) => r.duration));
  const minDuration = Math.min(...results.map((r) => r.duration));

  // 压缩效果的真正衡量：保留节点 / 总节点
  const avgCompression = results.filter(r => r.success).reduce((sum, r) => {
    const total = r.retainedNodes + r.compressedNodes;
    return sum + (total > 0 ? r.retainedNodes / total : 1);
  }, 0) / successCount;
  const avgOriginalTokens = results.filter(r => r.success).reduce((sum, r) => sum + r.originalTokens, 0) / successCount;
  const avgCompressedTokens = results.filter(r => r.success).reduce((sum, r) => sum + r.compressedTokens, 0) / successCount;

  // 按模式分组
  const byMode: Record<string, { total: number; success: number; retained: number; compressed: number }> = {};
  for (const result of results) {
    if (!byMode[result.mode]) {
      byMode[result.mode] = { total: 0, success: 0, retained: 0, compressed: 0 };
    }
    byMode[result.mode].total++;
    if (result.success) {
      byMode[result.mode].success++;
      byMode[result.mode].retained += result.retainedNodes;
      byMode[result.mode].compressed += result.compressedNodes;
    }
  }

  // 打印统计表格
  console.log('┌─────────────────────────────────────────────────────────────────────────────┐');
  console.log('│                              总体统计                                       │');
  console.log('├─────────────────────────────────────────────────────────────────────────────┤');
  console.log(`│  总场景数: ${totalScenarios.toString().padEnd(60)}│`);
  console.log(`│  成功率:   ${(successCount / totalScenarios * 100).toFixed(1)}% (${successCount}/${totalScenarios})${' '.repeat(40)}│`);
  console.log(`│  失败数:   ${failCount}${'. '.repeat(55 - failCount.toString().length)}│`);
  console.log(`│  平均耗时: ${avgDuration.toFixed(2)}ms${' '.repeat(50)}│`);
  console.log(`│  最快耗时: ${minDuration}ms${' '.repeat(52)}│`);
  console.log(`│  最慢耗时: ${maxDuration}ms${' '.repeat(52)}│`);
  console.log('│─────────────────────────────────────────────────────────────────────────────│');
  // compressionRatio = compressed/original，所以压缩效果 = 1 - avgCompression
  const actualCompression = Math.max(0, Math.min(1, 1 - avgCompression));
  console.log(`│  节点保留率: ${(avgCompression * 100).toFixed(1)}%${' '.repeat(48)}│`);
  console.log(`│  节点压缩率: ${(100 - avgCompression * 100).toFixed(1)}%${' '.repeat(49)}│`);
  console.log('└─────────────────────────────────────────────────────────────────────────────┘');
  console.log('');

  // 按模式分组统计
  console.log('┌─────────────────────────────────────────────────────────────────────────────┐');
  console.log('│                              压缩模式分布                                    │');
  console.log('├─────────────────────────────────────────────────────────────────────────────┤');
  for (const [mode, stats] of Object.entries(byMode)) {
    const total = stats.retained + stats.compressed;
    const retainedRate = total > 0 ? stats.retained / total : 0;
    const barLen = Math.round(retainedRate * 20);
    const bar = barLen > 0 ? '█'.repeat(barLen).padEnd(20) : '░'.repeat(20);
    console.log(`│  ${mode.padEnd(12)} [${bar}] 保留率=${(retainedRate * 100).toFixed(0)}% 成功=${stats.success}/${stats.total}${' '.repeat(10)}│`);
  }
  console.log('└─────────────────────────────────────────────────────────────────────────────┘');
  console.log('');

  // 节点统计
  const totalRetained = results.reduce((sum, r) => sum + r.retainedNodes, 0);
  const totalCompressed = results.reduce((sum, r) => sum + r.compressedNodes, 0);
  const totalNodes = totalRetained + totalCompressed;

  console.log('┌─────────────────────────────────────────────────────────────────────────────┐');
  console.log('│                              节点统计                                       │');
  console.log('├─────────────────────────────────────────────────────────────────────────────┤');
  console.log(`│  总节点数: ${totalNodes}${''.padEnd(58)}│`);
  console.log(`│  保留节点: ${totalRetained} (${(totalRetained / totalNodes * 100).toFixed(1)}%)${''.padEnd(52)}│`);
  console.log(`│  压缩节点: ${totalCompressed} (${(totalCompressed / totalNodes * 100).toFixed(1)}%)${''.padEnd(52)}│`);
  console.log(`│  可视化成功率: ${vizSuccess}/${vizTestScenarios.length}${''.padEnd(44)}│`);
  console.log('└─────────────────────────────────────────────────────────────────────────────┘');
  console.log('');

  // 失败案例详情
  const failedResults = results.filter((r) => !r.success);
  if (failedResults.length > 0) {
    console.log('┌─────────────────────────────────────────────────────────────────────────────┐');
    console.log('│                              失败案例详情                                    │');
    console.log('├─────────────────────────────────────────────────────────────────────────────┤');
    for (const result of failedResults) {
      console.log(`│  ❌ ${result.name.slice(0, 35).padEnd(35)} ${result.error?.slice(0, 30) || 'Unknown'}`);
    }
    console.log('└─────────────────────────────────────────────────────────────────────────────┘');
    console.log('');
  }

  // 最终结论
  console.log('='.repeat(100));
  const successRate = successCount / totalScenarios * 100;
  if (successRate >= 95) {
    console.log('  ✅ 测试通过: 成功率 >= 95%');
  } else if (successRate >= 80) {
    console.log('  ⚠️  测试警告: 成功率 80-95%');
  } else {
    console.log('  ❌ 测试失败: 成功率 < 80%');
  }
  console.log(`  并发测试: ${concurrentSuccess}/${concurrentScenarios.length} 成功，${concurrentDuration}ms 总耗时`);
  console.log(`  可视化测试: ${vizSuccess}/${vizTestScenarios.length} 成功`);
  console.log(`  节点保留率: ${(avgCompression * 100).toFixed(1)}%`);
  console.log(`  节点压缩率: ${(100 - avgCompression * 100).toFixed(1)}%`);
  console.log('='.repeat(100));
}

// 执行
runStressTest().catch((error) => {
  console.error('压力测试失败:', error);
  process.exit(1);
});
