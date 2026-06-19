#!/usr/bin/env node
/**
 * Graph-Reflection 压力测试脚本 v2 (纯 JavaScript)
 * 
 * 覆盖场景:
 * - 多种资产: BTC, ETH, SOL, DOGE, AVAX
 * - 多种思考深度: quick, standard, deep
 * - 多种意图: deep_analysis, scenario_sim, strategy_verify, market_query, execute_trade
 * - 串行执行（避免 pending 任务队列溢出）
 */

import fs from 'fs';
import path from 'path';

const API_URL = 'http://localhost:3000/api/task';
const RESULTS_FILE = path.resolve(process.cwd(), 'graph-reflection-stress-results.json');
const LOG_FILE = path.resolve(process.cwd(), 'graph-reflection-stress-log.md');
const TOTAL_TESTS = 200;
const REQUEST_DELAY_MS = 200;

// 测试数据
const ASSETS = ['BTC', 'ETH', 'SOL', 'DOGE', 'AVAX'];
const DEPTHS = ['quick', 'standard', 'deep'];

const TEMPLATES_BY_INTENT = {
  deep_analysis: [
    '深度分析 ${symbol} 当前趋势，给出入场策略',
    '请对 ${symbol} 做深度策略分析',
    '分析 ${symbol} 近一周走势，制定交易策略',
    '${symbol} 的技术分析和策略制定',
    '分析 ${symbol} 当前的市场结构和趋势方向',
    '请给出 ${symbol} 的交易策略建议',
    '${symbol} 机会分析与策略规划',
  ],
  scenario_sim: [
    '推演 ${symbol} 接下来24小时可能的走势',
    '模拟分析 ${symbol} 如果突破关键阻力会怎样',
    '情景分析 ${symbol} 在市场恐慌中的表现',
    '假设 ${symbol} 暴跌30%，应该如何应对',
    '${symbol} 极端行情情景推演',
    '如果 ${symbol} 跌破支撑，应该如何操作',
  ],
  strategy_verify: [
    '验证 ${symbol} 的趋势跟踪策略有效性',
    '检验 ${symbol} 的突破策略质量',
    '${symbol} 策略回测和验证',
    '评估 ${symbol} 当前策略的可靠性',
    '验证 ${symbol} 均线策略的信号质量',
    '对 ${symbol} 进行策略有效性评估',
  ],
  execute_trade: [
    '基于当前 ${symbol} 行情，先深度分析再开仓',
    '对 ${symbol} 制定交易策略并执行',
    '${symbol} 策略分析并执行交易',
    '根据 ${symbol} 趋势分析并执行交易',
  ],
  market_query: [
    '${symbol} 现在的价格是多少',
    '查询 ${symbol} 当前行情',
    '${symbol} 最新价格',
    '${symbol} 当前报价',
  ],
};

const INTENTS = Object.keys(TEMPLATES_BY_INTENT);

function makeMessage(asset, intent) {
  const templates = TEMPLATES_BY_INTENT[intent] || TEMPLATES_BY_INTENT.deep_analysis;
  const template = templates[Math.floor(Math.random() * templates.length)];
  return template.replace(/\$\{symbol\}/g, asset);
}

function makeSessionId(index, intent, depth, asset) {
  return `stress_${intent}_${depth}_${asset}_${index}_${Date.now().toString(36)}`;
}

async function sleep(ms) {
  return new Promise(resolve => setTimeout(resolve, ms));
}

async function runSingleTest(index, sessionId, thinkingMode, asset, intent) {
  const message = makeMessage(asset, intent);
  const startTime = Date.now();

  try {
    const response = await fetch(API_URL, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message, thinking_mode: thinkingMode, session_id: sessionId, lang: 'zh' }),
    });

    const responseTime = Date.now() - startTime;
    const data = await response.json();

    if (!data.success || !data.data) {
      return {
        index,
        session_id: sessionId,
        thinking_mode: thinkingMode,
        asset,
        requested_intent: intent,
        message,
        success: false,
        error: data.error || 'Unknown error',
        has_graph_reflection: false,
        has_step_metadata: false,
        step_issues_count: 0,
        response_time_ms: responseTime,
        timestamp: new Date().toISOString(),
      };
    }

    const d = data.data;
    const summary = d.execution_summary || {};
    const graphReflection = summary.graph_reflection;
    const recognizedIntent = typeof d.intent === 'string' ? d.intent : d.intent?.type || 'unknown';

    return {
      index,
      session_id: sessionId,
      thinking_mode: thinkingMode,
      asset,
      requested_intent: intent,
      message,
      success: d.status === 'completed',
      recognized_intent: recognizedIntent,
      chain: summary.chain_executed || [],
      has_graph_reflection: !!graphReflection,
      graph_reflection: graphReflection,
      avg_confidence: graphReflection?.avg_confidence,
      high_value_nodes: graphReflection?.high_value_nodes,
      total_nodes: graphReflection?.total_nodes,
      compressible_nodes: graphReflection?.compressible_nodes,
      completed_ratio: graphReflection?.completed_ratio,
      rollback_count: graphReflection?.rollback_count,
      has_step_metadata: !!(d.metadata?.step_metadata?.length),
      step_issues_count: (d.metadata?.step_metadata || []).reduce(
        (sum, m) => sum + (m?.issues?.length || 0), 0
      ),
      response_time_ms: responseTime,
      timestamp: new Date().toISOString(),
    };
  } catch (err) {
    return {
      index,
      session_id: sessionId,
      thinking_mode: thinkingMode,
      asset,
      requested_intent: intent,
      message,
      success: false,
      error: err.message || String(err),
      has_graph_reflection: false,
      has_step_metadata: false,
      step_issues_count: 0,
      response_time_ms: Date.now() - startTime,
      timestamp: new Date().toISOString(),
    };
  }
}

function generateReport(results) {
  const successCount = results.filter(r => r.success).length;
  const withGraph = results.filter(r => r.has_graph_reflection).length;
  const withStepMeta = results.filter(r => r.has_step_metadata).length;
  const sSeries = results.filter(r => (r.chain || []).some(c => c.startsWith('S'))).length;

  const responseTimes = results.filter(r => r.success).map(r => r.response_time_ms);
  const avgRespTime = responseTimes.length ? responseTimes.reduce((a, b) => a + b, 0) / responseTimes.length : 0;
  const sortedRespTimes = [...responseTimes].sort((a, b) => a - b);
  const medianRespTime = sortedRespTimes.length ? sortedRespTimes[Math.floor(sortedRespTimes.length / 2)] : 0;
  const maxRespTime = responseTimes.length ? Math.max(...responseTimes) : 0;
  const minRespTime = responseTimes.length ? Math.min(...responseTimes) : 0;

  const graphResults = results.filter(r => r.has_graph_reflection && r.graph_reflection);
  const avgConfidence = graphResults.length
    ? graphResults.reduce((a, r) => a + (r.avg_confidence || 0), 0) / graphResults.length
    : 0;
  const avgHighValue = graphResults.length
    ? graphResults.reduce((a, r) => a + (r.high_value_nodes || 0), 0) / graphResults.length
    : 0;
  const avgTotalNodes = graphResults.length
    ? graphResults.reduce((a, r) => a + (r.total_nodes || 0), 0) / graphResults.length
    : 0;
  const avgRollback = graphResults.length
    ? graphResults.reduce((a, r) => a + (r.rollback_count || 0), 0) / graphResults.length
    : 0;

  const byDepth = DEPTHS.map(depth => {
    const subset = results.filter(r => r.thinking_mode === depth);
    const subsetTimes = subset.filter(r => r.success).map(r => r.response_time_ms);
    const subsetAvgResp = subsetTimes.length ? subsetTimes.reduce((a, b) => a + b, 0) / subsetTimes.length : 0;
    const subsetGraph = subset.filter(r => r.has_graph_reflection);
    return {
      depth,
      total: subset.length,
      success: subset.filter(r => r.success).length,
      graph_count: subsetGraph.length,
      avg_ms: Math.round(subsetAvgResp),
      avg_confidence: subsetGraph.length
        ? subsetGraph.reduce((a, r) => a + (r.avg_confidence || 0), 0) / subsetGraph.length
        : 0,
    };
  });

  const byAsset = ASSETS.map(asset => {
    const subset = results.filter(r => r.asset === asset);
    return {
      asset,
      total: subset.length,
      success: subset.filter(r => r.success).length,
      graph_count: subset.filter(r => r.has_graph_reflection).length,
    };
  });

  const byIntent = {};
  for (const r of results) {
    if (!byIntent[r.requested_intent]) {
      byIntent[r.requested_intent] = { total: 0, success: 0, graph_count: 0, s_series_count: 0 };
    }
    byIntent[r.requested_intent].total++;
    if (r.success) byIntent[r.requested_intent].success++;
    if (r.has_graph_reflection) byIntent[r.requested_intent].graph_count++;
    if ((r.chain || []).some(c => c.startsWith('S'))) byIntent[r.requested_intent].s_series_count++;
  }

  const recognizedIntentDist = {};
  for (const r of results) {
    if (r.recognized_intent) {
      recognizedIntentDist[r.recognized_intent] = (recognizedIntentDist[r.recognized_intent] || 0) + 1;
    }
  }

  const errors = results.filter(r => !r.success).map(r => r.error).filter(Boolean);
  const errorPatterns = {};
  for (const err of errors) {
    const key = String(err).slice(0, 60);
    errorPatterns[key] = (errorPatterns[key] || 0) + 1;
  }

  const sSeriesResults = results.filter(r => (r.chain || []).some(c => c.startsWith('S')));
  const sSeriesWithGraph = sSeriesResults.filter(r => r.has_graph_reflection).length;
  const sSeriesWithStepMeta = sSeriesResults.filter(r => r.has_step_metadata).length;

  const confBuckets = [
    { range: '<0.5', count: graphResults.filter(r => (r.avg_confidence || 0) < 0.5).length },
    { range: '0.5-0.6', count: graphResults.filter(r => (r.avg_confidence || 0) >= 0.5 && (r.avg_confidence || 0) < 0.6).length },
    { range: '0.6-0.7', count: graphResults.filter(r => (r.avg_confidence || 0) >= 0.6 && (r.avg_confidence || 0) < 0.7).length },
    { range: '0.7-0.8', count: graphResults.filter(r => (r.avg_confidence || 0) >= 0.7 && (r.avg_confidence || 0) < 0.8).length },
    { range: '0.8-0.9', count: graphResults.filter(r => (r.avg_confidence || 0) >= 0.8 && (r.avg_confidence || 0) < 0.9).length },
    { range: '>=0.9', count: graphResults.filter(r => (r.avg_confidence || 0) >= 0.9).length },
  ];

  const reportTime = new Date().toLocaleString('zh-CN');
  let report = `# Graph-Reflection 融合压力测试报告 v2\n\n`;
  report += `**生成时间**: ${reportTime}\n\n`;
  report += `**测试配置**: ${TOTAL_TESTS} 次请求，串行执行，间隔 ${REQUEST_DELAY_MS}ms\n\n`;

  report += `## 一、整体统计\n\n`;
  report += `| 指标 | 值 |\n|------|-----|\n`;
  report += `| 总测试数 | **${results.length}** |\n`;
  report += `| 成功率 | **${(successCount / results.length * 100).toFixed(1)}%** (${successCount}/${results.length}) |\n`;
  report += `| 触发 S 系列思维链 | **${sSeries}** (${(sSeries / results.length * 100).toFixed(1)}%) |\n`;
  report += `| 包含 graph_reflection | **${withGraph}** (${(withGraph / results.length * 100).toFixed(1)}%) |\n`;
  report += `| 包含 step_metadata (自省) | **${withStepMeta}** (${(withStepMeta / results.length * 100).toFixed(1)}%) |\n`;
  report += `| 平均响应时间 | ${Math.round(avgRespTime)} ms |\n`;
  report += `| 中位数响应时间 | ${Math.round(medianRespTime)} ms |\n`;
  report += `| 最快响应 | ${Math.round(minRespTime)} ms |\n`;
  report += `| 最慢响应 | ${Math.round(maxRespTime)} ms |\n\n`;

  report += `## 二、Graph-Reflection 模块效果\n\n`;
  report += `| 指标 | 值 |\n|------|-----|\n`;
  report += `| graph-reflection 出现次数 | ${withGraph} |\n`;
  report += `| 平均置信度 avg_confidence | **${avgConfidence.toFixed(3)}** |\n`;
  report += `| 平均高价值节点数 | **${avgHighValue.toFixed(1)}** |\n`;
  report += `| 平均总节点数 | **${avgTotalNodes.toFixed(1)}** |\n`;
  report += `| 平均回退次数 | **${avgRollback.toFixed(2)}** |\n\n`;

  report += `### 置信度分布（Graph-Reflection 激活时）\n\n`;
  report += `| 置信度范围 | 次数 |\n|------------|------|\n`;
  for (const bucket of confBuckets) {
    report += `| ${bucket.range} | ${bucket.count} |\n`;
  }
  report += `\n`;

  report += `## 三、按思考深度分类\n\n`;
  report += `| 思考深度 | 测试数 | 成功 | graph_reflection | 平均响应 | 平均置信度 |\n`;
  report += `|----------|--------|------|-----------------|----------|----------|\n`;
  for (const item of byDepth) {
    report += `| ${item.depth} | ${item.total} | ${item.success} | ${item.graph_count} | ${item.avg_ms} ms | ${item.avg_confidence.toFixed(3)} |\n`;
  }
  report += `\n`;

  report += `## 四、按资产分类\n\n`;
  report += `| 资产 | 测试数 | 成功 | graph_reflection |\n`;
  report += `|------|--------|------|-----------------|\n`;
  for (const item of byAsset) {
    report += `| ${item.asset} | ${item.total} | ${item.success} | ${item.graph_count} |\n`;
  }
  report += `\n`;

  report += `## 五、按请求意图分类（S系列触发验证）\n\n`;
  report += `| 请求意图 | 测试数 | 成功 | S系列触发 | graph_reflection |\n`;
  report += `|----------|--------|------|----------|-----------------|\n`;
  for (const [intent, stats] of Object.entries(byIntent)) {
    report += `| ${intent} | ${stats.total} | ${stats.success} | ${stats.s_series_count} | ${stats.graph_count} |\n`;
  }
  report += `\n`;

  report += `### 实际识别的意图分布\n\n`;
  report += `| 意图 | 次数 |\n|------|------|\n`;
  for (const [intent, count] of Object.entries(recognizedIntentDist)) {
    report += `| ${intent} | ${count} |\n`;
  }
  report += `\n`;

  report += `## 六、S 系列思维链详细分析\n\n`;
  report += `- S系列请求数: **${sSeriesResults.length}**\n`;
  report += `- S系列中 graph_reflection 激活: **${sSeriesWithGraph}** (期望: 100%)\n`;
  report += `- S系列中 step_metadata 激活: **${sSeriesWithStepMeta}** (期望: 100%)\n\n`;

  if (sSeriesWithGraph < sSeriesResults.length) {
    report += `⚠️ **警告**: ${sSeriesResults.length - sSeriesWithGraph} 个 S 系列请求缺少 graph_reflection\n\n`;
  }

  report += `## 七、问题与错误模式\n\n`;
  if (Object.keys(errorPatterns).length > 0) {
    report += `| 错误 | 次数 |\n|------|------|\n`;
    for (const [pattern, count] of Object.entries(errorPatterns).sort((a, b) => b[1] - a[1]).slice(0, 10)) {
      report += `| ${pattern} | ${count} |\n`;
    }
    report += `\n`;
  } else {
    report += `✅ **零错误**: 所有请求成功完成！\n\n`;
  }

  report += `### 自省 Gate 效果（step issues 统计）\n\n`;
  const totalIssues = results.reduce((a, r) => a + r.step_issues_count, 0);
  report += `- 总识别问题数: **${totalIssues}**\n`;
  report += `- 有自省 gate 的请求中平均问题数: ${withStepMeta > 0 ? (totalIssues / withStepMeta).toFixed(2) : 'N/A'}\n\n`;

  report += `### 性能分析\n\n`;
  if (avgRespTime > 60000) {
    report += `⚠️ **性能警告**: 平均响应时间超过60秒\n`;
    report += `  - deep 模式响应较慢是预期的 (完整思维链)\n`;
    report += `  - quick/standard 模式应在30秒内\n\n`;
  } else {
    report += `✅ **性能良好**: 平均响应时间 ${Math.round(avgRespTime)}ms\n\n`;
  }

  const failedResults = results.filter(r => !r.success).slice(0, 20);
  if (failedResults.length > 0) {
    report += `### 失败请求样例 (前20个)\n\n`;
    for (const r of failedResults) {
      report += `- **#${r.index}** [${r.thinking_mode}/${r.asset}] ${r.message.slice(0, 50)}...\n`;
      report += `  - 请求意图: ${r.requested_intent}\n`;
      report += `  - 错误: ${r.error}\n\n`;
    }
  }

  report += `## 八、结论与系统评估\n\n`;
  report += `- **系统稳定性**: ${(successCount / results.length * 100).toFixed(1)}% 成功率 (${successCount}/${results.length})\n`;
  report += `- **S系列触发率**: ${sSeriesResults.length > 0 ? (sSeriesResults.length / results.length * 100).toFixed(1) : '0'}% (针对深度分析/推演/验证类请求)\n`;
  report += `- **Graph-Reflection 集成率**: ${withGraph > 0 ? (withGraph / results.length * 100).toFixed(1) : '0'}% (S系列中: ${sSeriesResults.length > 0 ? (sSeriesWithGraph / sSeriesResults.length * 100).toFixed(1) : '0'}%)\n`;
  report += `- **自省 Gate 效果**: 平均置信度 ${avgConfidence.toFixed(3)}，总问题数 ${totalIssues}\n`;
  report += `- **压缩效率**: 平均保留 ${avgHighValue.toFixed(1)} 个高价值节点\n\n`;

  report += `---\n`;
  report += `*测试环境: local dev server · ${results.length} 次请求 · 共 ${(results.reduce((a, r) => a + r.response_time_ms, 0) / 1000).toFixed(1)} 秒总耗时*\n`;

  return report;
}

async function main() {
  console.log(`\n=== Graph-Reflection 压力测试 v2 开始 ===`);
  console.log(`目标: ${TOTAL_TESTS} 次 · 间隔: ${REQUEST_DELAY_MS}ms\n`);

  const results = [];
  const startTime = Date.now();

  for (let i = 0; i < TOTAL_TESTS; i++) {
    const intent = INTENTS[i % INTENTS.length];
    const thinkingMode = DEPTHS[Math.floor(i / INTENTS.length) % DEPTHS.length];
    const asset = ASSETS[Math.floor(Math.random() * ASSETS.length)];
    const sessionId = makeSessionId(i, intent, thinkingMode, asset);

    const result = await runSingleTest(i + 1, sessionId, thinkingMode, asset, intent);
    results.push(result);

    const successIcon = result.success ? '✓' : '✗';
    const graphIcon = result.has_graph_reflection ? '📊' : '  ';
    const intentDisplay = result.recognized_intent || 'unknown';
    const chainStr = (result.chain || []).slice(0, 3).join(',') || '-';
    const time = Math.round(result.response_time_ms);

    console.log(
      `  [${String(i + 1).padStart(3, '0')}/${TOTAL_TESTS}] ${successIcon} ${graphIcon} ` +
      `${thinkingMode.padEnd(8)} ${asset.padEnd(5)} ` +
      `${intent.padEnd(15)}->${intentDisplay.padEnd(15)} ` +
      `chain=${chainStr.padEnd(35)} ` +
      `${time}ms` +
      (result.error ? ` [${result.error.slice(0, 40)}]` : '')
    );

    if ((i + 1) % 50 === 0) {
      fs.writeFileSync(RESULTS_FILE, JSON.stringify(results, null, 2));
      console.log(`  → 已保存 ${results.length} 条中间结果\n`);
    }

    await sleep(REQUEST_DELAY_MS);
  }

  const totalTime = ((Date.now() - startTime) / 1000).toFixed(1);
  console.log(`\n=== 测试结束，总耗时 ${totalTime} 秒 ===`);

  const report = generateReport(results);

  fs.writeFileSync(RESULTS_FILE, JSON.stringify(results, null, 2));
  fs.writeFileSync(LOG_FILE, report, 'utf-8');

  console.log(`\n✓ 原始数据: ${RESULTS_FILE}`);
  console.log(`✓ 分析报告: ${LOG_FILE}\n`);

  const successCount = results.filter(r => r.success).length;
  const withGraph = results.filter(r => r.has_graph_reflection).length;
  const sSeries = results.filter(r => (r.chain || []).some(c => c.startsWith('S'))).length;

  console.log('='.repeat(60));
  console.log(`  成功率: ${(successCount / results.length * 100).toFixed(1)}% (${successCount}/${results.length})`);
  console.log(`  S系列触发: ${sSeries} 次 (${(sSeries / results.length * 100).toFixed(1)}%)`);
  console.log(`  graph-reflection: ${withGraph} 次 (${(withGraph / results.length * 100).toFixed(1)}%)`);
  console.log(`  平均响应: ${Math.round(results.filter(r => r.success).reduce((a, r) => a + r.response_time_ms, 0) / Math.max(1, successCount))}ms`);
  console.log('='.repeat(60));
  console.log('\n详细报告见:', LOG_FILE);
}

main().catch(err => {
  console.error('\n✗ 测试运行失败:', err.message || err);
  process.exit(1);
});
