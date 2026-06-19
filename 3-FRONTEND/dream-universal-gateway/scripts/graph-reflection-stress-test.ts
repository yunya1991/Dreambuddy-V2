import * as fs from 'fs';
import * as path from 'path';
import axios from 'axios';
import * as crypto from 'crypto';

const API_BASE = 'http://localhost:3000';
const API_URL = `${API_BASE}/api/task`;
const RESULTS_FILE = path.join(__dirname, '../graph-reflection-stress-results.json');
const LOG_FILE = path.join(__dirname, '../graph-reflection-stress-log.md');
const TASKS_DIR = path.join(__dirname, '../.cache/tasks');

const TOTAL_TESTS = 200;
const REQUEST_DELAY_MS = 300;
const RETRY_MAX = 3;

const TEST_ASSETS = ['BTC', 'ETH', 'SOL', 'DOGE', 'AVAX'];
const TEST_DEPTHS: Array<'quick' | 'standard' | 'deep'> = ['quick', 'standard', 'deep'];

const TEMPLATES = [
  '深度分析 ${symbol} 当前趋势，给出入场策略',
  '请对 ${symbol} 做深度策略分析',
  '分析 ${symbol} 近一周走势，制定交易策略',
  '${symbol} 的技术分析和策略制定',
  '推演 ${symbol} 接下来24小时可能的走势',
  '验证 ${symbol} 的趋势跟踪策略有效性',
  '验证 ${symbol} 突破策略的回测结果',
  '基于当前 ${symbol} 行情，先给出深度分析再决策',
];

function makeMessage(asset: string): string {
  const template = TEMPLATES[Math.floor(Math.random() * TEMPLATES.length)];
  return template.replace(/\$\{symbol\}/g, asset);
}

function makeSessionId(): string {
  return `stress_test_${Date.now().toString(36)}_${crypto.randomBytes(4).toString('hex')}`;
}

interface TestResult {
  index: number;
  session_id: string;
  thinking_mode: string;
  asset: string;
  message: string;
  success: boolean;
  error?: string;
  intent?: string;
  chain?: string[];
  has_graph_reflection: boolean;
  graph_reflection?: any;
  avg_confidence?: number;
  high_value_nodes?: number;
  total_nodes?: number;
  compression_ratio?: number;
  has_step_metadata: boolean;
  step_issues_count: number;
  response_time_ms: number;
  timestamp: string;
}

async function waitForQueueReady(maxWaitMs: number = 15000): Promise<boolean> {
  const startTime = Date.now();
  while (Date.now() - startTime < maxWaitMs) {
    try {
      if (!fs.existsSync(TASKS_DIR)) return true;
      const pending = fs.readdirSync(TASKS_DIR)
        .filter(f => f.endsWith('.json'))
        .filter(f => {
          try {
            const content = fs.readFileSync(path.join(TASKS_DIR, f), 'utf-8');
            const task = JSON.parse(content);
            return task.status === 'pending';
          } catch { return false; }
        }).length;
      if (pending < 3) return true;
      await new Promise(r => setTimeout(r, 200));
    } catch {
      await new Promise(r => setTimeout(r, 200));
    }
  }
  return false;
}

async function runSingleTest(index: number, sessionId: string, thinkingMode: string, asset: string): Promise<TestResult> {
  const message = makeMessage(asset);
  const startTime = Date.now();

  await waitForQueueReady();

  for (let attempt = 1; attempt <= RETRY_MAX; attempt++) {
    try {
      const response = await axios.post(
        API_URL,
        { message, thinking_mode: thinkingMode, session_id: sessionId, lang: 'zh' },
        { timeout: 120000, headers: { 'Content-Type': 'application/json' } },
      );

      const responseTime = Date.now() - startTime;
      const data = response.data;

      if (!data.success || !data.data) {
        await new Promise(r => setTimeout(r, REQUEST_DELAY_MS * attempt));
        continue;
      }

      const d = data.data;
      const summary = d.execution_summary || {};
      const graphReflection = summary.graph_reflection;

      return {
        index,
        session_id: sessionId,
        thinking_mode: thinkingMode,
        asset,
        message,
        success: d.status === 'completed',
        intent: typeof d.intent === 'string' ? d.intent : d.intent?.type,
        chain: summary.chain_executed || [],
        has_graph_reflection: !!graphReflection,
        graph_reflection: graphReflection,
        avg_confidence: graphReflection?.avg_confidence,
        high_value_nodes: graphReflection?.high_value_nodes,
        total_nodes: graphReflection?.total_nodes,
        compression_ratio: graphReflection?.compression_ratio,
        has_step_metadata: !!(d.metadata?.step_metadata?.length),
        step_issues_count: (d.metadata?.step_metadata || []).reduce(
          (sum: number, m: any) => sum + (m?.issues?.length || 0), 0
        ),
        response_time_ms: responseTime,
        timestamp: new Date().toISOString(),
      };
    } catch (err: any) {
      if (attempt < RETRY_MAX) {
        await new Promise(r => setTimeout(r, REQUEST_DELAY_MS * attempt));
        continue;
      }
      return {
        index,
        session_id: sessionId,
        thinking_mode: thinkingMode,
        asset,
        message,
        success: false,
        error: err.response?.data?.error || err.message || String(err),
        has_graph_reflection: false,
        has_step_metadata: false,
        step_issues_count: 0,
        response_time_ms: Date.now() - startTime,
        timestamp: new Date().toISOString(),
      };
    }
  }
  return {
    index,
    session_id: sessionId,
    thinking_mode: thinkingMode,
    asset,
    message,
    success: false,
    error: 'All retry attempts failed',
    has_graph_reflection: false,
    has_step_metadata: false,
    step_issues_count: 0,
    response_time_ms: Date.now() - startTime,
    timestamp: new Date().toISOString(),
  };
}

function generateReport(results: TestResult[]): string {
  const successCount = results.filter(r => r.success).length;
  const errorCount = results.length - successCount;
  const withGraph = results.filter(r => r.has_graph_reflection).length;
  const withStepMeta = results.filter(r => r.has_step_metadata).length;
  const sSeries = results.filter(r => (r.chain || []).some(c => c.startsWith('S'))).length;

  const responseTimes = results.filter(r => r.success).map(r => r.response_time_ms);
  const avgRespTime = responseTimes.length ? responseTimes.reduce((a, b) => a + b, 0) / responseTimes.length : 0;
  const medianRespTime = responseTimes.length ? [...responseTimes].sort((a, b) => a - b)[Math.floor(responseTimes.length / 2)] : 0;
  const maxRespTime = responseTimes.length ? Math.max(...responseTimes) : 0;

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
  const avgCompression = graphResults.length
    ? graphResults.reduce((a, r) => a + (r.compression_ratio || 0), 0) / graphResults.length
    : 0;

  const byDepth = TEST_DEPTHS.map(depth => {
    const subset = results.filter(r => r.thinking_mode === depth);
    const subsetSuccess = subset.filter(r => r.success).length;
    const subsetGraph = subset.filter(r => r.has_graph_reflection).length;
    const subsetAvgResp = subset.filter(r => r.success).length
      ? subset.filter(r => r.success).reduce((a, r) => a + r.response_time_ms, 0) / subset.filter(r => r.success).length
      : 0;
    return { depth, total: subset.length, success: subsetSuccess, graph_count: subsetGraph, avg_ms: Math.round(subsetAvgResp) };
  });

  const byAsset = TEST_ASSETS.map(asset => {
    const subset = results.filter(r => r.asset === asset);
    return { asset, total: subset.length, success: subset.filter(r => r.success).length };
  });

  const byIntent: Record<string, number> = {};
  for (const r of results) {
    if (r.intent) byIntent[r.intent] = (byIntent[r.intent] || 0) + 1;
  }

  const errorMessages = results.filter(r => !r.success).map(r => r.error).filter(Boolean);
  const errorPatterns: Record<string, number> = {};
  for (const err of errorMessages) {
    const key = String(err).slice(0, 80);
    errorPatterns[key] = (errorPatterns[key] || 0) + 1;
  }

  const reportTime = new Date().toLocaleString('zh-CN');
  let report = `# Graph-Reflection 融合压力测试报告\n\n`;
  report += `**生成时间**: ${reportTime}\n\n`;
  report += `## 一、整体统计\n\n`;
  report += `| 指标 | 值 |\n|------|-----|\n`;
  report += `| 总测试数 | **${results.length}** |\n`;
  report += `| 成功率 | **${(successCount / results.length * 100).toFixed(1)}%** (${successCount}/${results.length}) |\n`;
  report += `| 错误数 | ${errorCount} |\n`;
  report += `| 触发 S 系列 | **${sSeries}** (${(sSeries / results.length * 100).toFixed(1)}%) |\n`;
  report += `| 包含 graph_reflection | **${withGraph}** (${(withGraph / results.length * 100).toFixed(1)}%) |\n`;
  report += `| 包含 step_metadata | **${withStepMeta}** (${(withStepMeta / results.length * 100).toFixed(1)}%) |\n`;
  report += `| 平均响应时间 | ${Math.round(avgRespTime)} ms |\n`;
  report += `| 中位数响应时间 | ${Math.round(medianRespTime)} ms |\n`;
  report += `| 最大响应时间 | ${Math.round(maxRespTime)} ms |\n\n`;

  report += `## 二、Graph-Reflection 模块效果\n\n`;
  report += `| 指标 | 值 |\n|------|-----|\n`;
  report += `| graph-reflection 出现次数 | ${withGraph} |\n`;
  report += `| 平均置信度 avg_confidence | **${avgConfidence.toFixed(3)}** |\n`;
  report += `| 平均高价值节点数 | **${avgHighValue.toFixed(1)}** |\n`;
  report += `| 平均总节点数 | **${avgTotalNodes.toFixed(1)}** |\n`;
  report += `| 平均压缩比 | **${avgCompression.toFixed(2)}** |\n\n`;

  if (graphResults.length > 0) {
    report += `### 置信度分布\n\n`;
    const buckets = [0, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0];
    for (let i = 0; i < buckets.length - 1; i++) {
      const count = graphResults.filter(r => (r.avg_confidence || 0) >= buckets[i] && (r.avg_confidence || 0) < buckets[i + 1]).length;
      report += `| [${buckets[i].toFixed(1)}, ${buckets[i + 1].toFixed(1)}) | ${count} |\n`;
    }
    report += `\n`;
  }

  report += `## 三、按思考深度分类\n\n`;
  report += `| 思考深度 | 测试数 | 成功 | graph_reflection | 平均响应 |\n`;
  report += `|----------|--------|------|-----------------|----------|\n`;
  for (const item of byDepth) {
    report += `| ${item.depth} | ${item.total} | ${item.success} | ${item.graph_count} | ${item.avg_ms} ms |\n`;
  }
  report += `\n`;

  report += `## 四、按资产分类\n\n`;
  report += `| 资产 | 测试数 | 成功 |\n|------|--------|------|\n`;
  for (const item of byAsset) {
    report += `| ${item.asset} | ${item.total} | ${item.success} |\n`;
  }
  report += `\n`;

  report += `## 五、意图分布\n\n`;
  report += `| 意图 | 次数 |\n|------|------|\n`;
  for (const [intent, count] of Object.entries(byIntent)) {
    report += `| ${intent} | ${count} |\n`;
  }
  report += `\n`;

  report += `## 六、问题与优化建议\n\n`;
  if (Object.keys(errorPatterns).length > 0) {
    report += `### 6.1 常见错误模式\n\n`;
    for (const [pattern, count] of Object.entries(errorPatterns).sort((a, b) => b[1] - a[1]).slice(0, 10)) {
      report += `- **${count}次**: ${pattern}\n`;
    }
    report += `\n`;
  }

  report += `### 6.2 质量检查\n\n`;
  const sSeriesResults = results.filter(r => (r.chain || []).some(c => c.startsWith('S')));
  const sSeriesWithGraph = sSeriesResults.filter(r => r.has_graph_reflection).length;
  const sSeriesWithStepMeta = sSeriesResults.filter(r => r.has_step_metadata).length;

  report += `- S系列中缺少 graph_reflection: **${sSeriesResults.length - sSeriesWithGraph}** 次 (期望: 0)\n`;
  report += `- S系列中缺少 step_metadata: **${sSeriesResults.length - sSeriesWithStepMeta}** 次 (期望: 0)\n\n`;

  if (sSeriesWithGraph < sSeriesResults.length) {
    report += `⚠️ **问题**: 部分 S 系列请求未包含 graph_reflection，需要检查 graph-reflection-bridge 的集成状态。\n\n`;
  }
  if (avgConfidence > 0 && avgConfidence < 0.7) {
    report += `⚠️ **问题**: 平均置信度偏低 (${avgConfidence.toFixed(3)})\n`;
    report += `  - 优化自省 gate 的启发式评分\n`;
    report += `  - 增加工具验证闭环提升置信度\n\n`;
  }
  if (avgRespTime > 60000) {
    report += `⚠️ **问题**: 平均响应时间超过60秒，影响用户体验\n`;
    report += `  - 考虑在 quick 模式下缩短思考链\n`;
    report += `  - 优化市场数据预取效率\n\n`;
  }

  report += `## 七、结论\n\n`;
  report += `- **系统稳定性**: ${(successCount / results.length * 100).toFixed(1)}% 成功率 (${successCount}/${results.length})\n`;
  report += `- **Graph-Reflection 集成率**: ${withGraph > 0 ? (withGraph / results.length * 100).toFixed(1) : '0'}% (S系列中: ${sSeriesResults.length > 0 ? (sSeriesWithGraph / sSeriesResults.length * 100).toFixed(1) : '0'}%)\n`;
  report += `- **自省 gate 效果**: 平均置信度 ${avgConfidence.toFixed(3)}\n`;
  report += `- **压缩效率**: 平均保留 ${avgHighValue.toFixed(1)} 个高价值节点\n\n`;

  report += `---\n`;
  report += `*测试环境: local dev server · ${results.length} 次请求 · 共 ${(results.reduce((a, r) => a + r.response_time_ms, 0) / 1000).toFixed(1)} 秒总耗时*\n`;

  return report;
}

async function main() {
  console.log(`\n=== Graph-Reflection 压力测试开始 ===`);
  console.log(`目标: ${TOTAL_TESTS} 次，延迟: ${REQUEST_DELAY_MS}ms，重试: ${RETRY_MAX} 次\n`);

  const results: TestResult[] = [];

  for (let i = 0; i < TOTAL_TESTS; i++) {
    const sessionId = makeSessionId();
    const thinkingMode = TEST_DEPTHS[i % TEST_DEPTHS.length];
    const asset = TEST_ASSETS[Math.floor(Math.random() * TEST_ASSETS.length)];

    const result = await runSingleTest(i + 1, sessionId, thinkingMode, asset);
    results.push(result);

    const successIcon = result.success ? '✓' : '✗';
    const graphIcon = result.has_graph_reflection ? '📊' : '  ';
    const intent = result.intent || 'unknown';
    const chain = (result.chain || []).join(',') || '-';
    const time = Math.round(result.response_time_ms);

    console.log(
      `  [${String(i + 1).padStart(3, '0')}/${TOTAL_TESTS}] ${successIcon} ${graphIcon} ` +
      `${thinkingMode.padEnd(8)} ${asset.padEnd(5)} ` +
      `intent=${intent.padEnd(15)} chain=${chain.padEnd(40)} ` +
      `${time}ms` +
      (result.error ? ` [ERROR: ${result.error.slice(0, 50)}]` : '')
    );

    if ((i + 1) % 50 === 0) {
      fs.writeFileSync(RESULTS_FILE, JSON.stringify(results, null, 2));
      console.log(`  → 已保存 ${results.length} 条中间结果\n`);
    }

    await new Promise(r => setTimeout(r, REQUEST_DELAY_MS));
  }

  console.log(`\n=== 测试结束，生成报告 ===`);
  const report = generateReport(results);

  fs.writeFileSync(RESULTS_FILE, JSON.stringify(results, null, 2));
  fs.writeFileSync(LOG_FILE, report, 'utf-8');

  console.log(`\n✓ 原始数据: ${RESULTS_FILE}`);
  console.log(`✓ 分析报告: ${LOG_FILE}\n`);
  console.log(report.split('---')[0]);
}

main().catch(err => {
  console.error('\n✗ 测试运行失败:', err.message || err);
  process.exit(1);
});
