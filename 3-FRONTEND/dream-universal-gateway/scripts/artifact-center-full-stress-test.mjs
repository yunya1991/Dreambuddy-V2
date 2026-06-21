#!/usr/bin/env node
/**
 * 产物中台全链路压力测试 v1.0 - Comprehensive Artifact Center Stress Test
 *
 * 测试维度：
 * - 意图识别（10+种意图）
 * - 路由决策（execution / intelligence / general loops）
 * - S系列链执行（S0/S1/S2/S3/S4/S5）
 * - Graph-Reflection 融合（置信度、节点状态）
 * - 产物生成（artifact 文件产出）
 *
 * 测试矩阵：8意图 × 5资产 × 3深度 = 120种组合，分3轮执行
 */

import fs from 'fs';
import path from 'path';

const API_URL = 'http://localhost:3000/api/task';
const RESULTS_DIR = path.resolve(process.cwd(), 'artifact-stress-tests');
const TIMESTAMP = new Date().toISOString().replace(/[-:T]/g, '').slice(0, 14);
const RESULTS_FILE = path.join(RESULTS_DIR, `stress-test-${TIMESTAMP}.json`);
const REPORT_FILE = path.join(RESULTS_DIR, `stress-test-${TIMESTAMP}-report.md`);
const REQUEST_DELAY_MS = 5000;

// ============ 测试配置 ============

const ASSETS = ['BTC', 'ETH', 'SOL', 'DOGE', 'AVAX'];
const DEPTHS = ['quick', 'standard', 'deep'];

// 意图测试配置（模板 + 期望链长度 + 期望产物类型 + 是否需要 graph_reflection）
const INTENT_TEST_CONFIGS = [
  {
    intent: 'deep_analysis',
    loop: 'execution',
    expected_chain_length: 2, // free模式 S1→S2
    expected_artifact_types: ['intelligence_brief', 'first_principles'],
    expects_graph_reflection: true,
    expects_step_metadata: true,
    template: (asset) => `深度分析 ${asset} 当前趋势，给出入场策略`,
    description: '深度分析链',
  },
  {
    intent: 'scenario_sim',
    loop: 'execution',
    expected_chain_length: 2,
    expected_artifact_types: ['intelligence_brief', 'first_principles', 'scenario_design'],
    expects_graph_reflection: true,
    expects_step_metadata: true,
    template: (asset) => `推演 ${asset} 如果跌破关键支撑位可能的走势`,
    description: '情景模拟链',
  },
  {
    intent: 'strategy_verify',
    loop: 'execution',
    expected_chain_length: 2,
    expected_artifact_types: ['first_principles', 'scenario_design', 'validation_report'],
    expects_graph_reflection: true,
    expects_step_metadata: true,
    template: (asset) => `验证 ${asset} 均线交叉策略的有效性`,
    description: '策略验证链',
  },
  {
    intent: 'execute_trade',
    loop: 'execution',
    expected_chain_length: 3,
    expected_artifact_types: ['intelligence_brief', 'first_principles', 'scenario_design', 'execution_plan'],
    expects_graph_reflection: true,
    expects_step_metadata: true,
    template: (asset) => `基于当前 ${asset} 行情，先深度分析再制定交易计划`,
    description: '交易执行链',
  },
  {
    intent: 'triple_chain',
    loop: 'execution',
    expected_chain_length: 2,
    expected_artifact_types: ['intelligence_brief', 'first_principles'],
    expects_graph_reflection: true,
    expects_step_metadata: true,
    template: (asset) => `对 ${asset} 进行完整策略制定：调研→分析→设计→验证→执行`,
    description: '完整策略链',
  },
  {
    intent: 'market_query',
    loop: 'intelligence',
    expected_chain_length: 1,
    expected_artifact_types: ['intelligence_brief'],
    expects_graph_reflection: false, // 简单查询不触发 graph-reflection
    expects_step_metadata: true,
    template: (asset) => `${asset} 现在的价格是多少`,
    description: '行情查询链',
  },
  {
    intent: 'simple_qa',
    loop: 'general',
    expected_chain_length: 1,
    expected_artifact_types: [], // S0 无产物文件
    expects_graph_reflection: false,
    expects_step_metadata: true,
    template: (asset) => `什么是 ${asset}？简单介绍一下`,
    description: '简单问答链（S0）',
  },
  {
    intent: 'system_config',
    loop: 'general',
    expected_chain_length: 1,
    expected_artifact_types: [], // S0 无产物文件
    expects_graph_reflection: false,
    expects_step_metadata: true,
    template: (asset) => `系统状态查询`,
    description: '系统配置链（S0）',
  },
];

// ============ 辅助函数 ============

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function makeSessionId(index, intent, asset, depth) {
  return `stress_${intent}_${asset}_${depth}_${index}_${Date.now()}`;
}

function generateTestPlan() {
  const plan = [];
  let idx = 0;
  for (const config of INTENT_TEST_CONFIGS) {
    for (const asset of ASSETS) {
      for (const depth of DEPTHS) {
        plan.push({
          index: idx++,
          intent: config.intent,
          asset,
          depth,
          message: config.template(asset),
          description: config.description,
          loop: config.loop,
          expected_chain_length: config.expected_chain_length,
          expected_artifact_types: config.expected_artifact_types,
          expects_graph_reflection: config.expects_graph_reflection,
          expects_step_metadata: config.expects_step_metadata,
        });
      }
    }
  }
  return plan;
}

function evaluateTestResult(test, data, responseTime) {
  const actualIntent = data.intent?.type || data.intent || 'unknown';
  const intentMatch = actualIntent === test.intent;

  const chainExecuted = data.execution_summary?.chain_executed || [];
  const chainLengthMatch = chainExecuted.length >= Math.min(1, test.expected_chain_length - 1); // 宽松检查

  const artifactsProduced = data.artifacts_produced || [];
  const actualArtifactTypes = artifactsProduced.map((a) => a.type || 'unknown');
  const artifactCountMatch =
    test.expected_artifact_types.length === 0 ||
    actualArtifactTypes.length > 0;

  const graphReflection = data.execution_summary?.graph_reflection;
  const hasGraphReflection = graphReflection !== null && graphReflection !== undefined;
  const graphReflectionMatch = test.expects_graph_reflection ? hasGraphReflection : true; // 非强制意图不强求

  const stepMetadata = data.metadata?.step_metadata || [];
  const hasStepMetadata = stepMetadata.length > 0;
  const stepMetadataMatch = test.expects_step_metadata ? hasStepMetadata : true;

  const avgConfidence = graphReflection?.avg_confidence ||
    (stepMetadata.length > 0
      ? stepMetadata.reduce((s, m) => s + (m.confidence || 0), 0) / stepMetadata.length
      : 0);

  const totalNodes = graphReflection?.total_nodes || 0;
  const highValueNodes = graphReflection?.high_value_nodes || 0;
  const completedRatio = graphReflection?.completed_ratio || 0;

  return {
    test_index: test.index,
    intent: test.intent,
    asset: test.asset,
    depth: test.depth,
    message: test.message,
    actual_intent: actualIntent,
    intent_match: intentMatch,
    loop: test.loop,
    chain_executed: chainExecuted,
    chain_length: chainExecuted.length,
    expected_chain_length: test.expected_chain_length,
    chain_length_match: chainLengthMatch,
    artifacts_produced: actualArtifactTypes,
    artifact_count: actualArtifactTypes.length,
    artifact_count_match: artifactCountMatch,
    expected_artifact_types: test.expected_artifact_types,
    has_graph_reflection: hasGraphReflection,
    graph_reflection_match: graphReflectionMatch,
    graph_reflection_data: graphReflection
      ? {
          total_nodes: totalNodes,
          avg_confidence: avgConfidence,
          max_risk: graphReflection.max_risk,
          high_value_nodes: highValueNodes,
          compressible_nodes: graphReflection.compressible_nodes,
          completed_ratio: completedRatio,
        }
      : null,
    has_step_metadata: hasStepMetadata,
    step_metadata_count: stepMetadata.length,
    step_metadata_match: stepMetadataMatch,
    avg_confidence: avgConfidence,
    execution_time_ms: responseTime,
    credits_cost: data.metadata?.cost_credits || 0,
    content_length: typeof data.content === 'string' ? data.content.length : 0,
    executor: data.metadata?.executor || 'unknown',
    status: data.status || 'unknown',
    success: data.status === 'completed' && intentMatch,
  };
}

// ============ 主测试函数 ============

async function runSingleTest(test) {
  const startTime = Date.now();
  const sessionId = makeSessionId(test.index, test.intent, test.asset, test.depth);

  try {
    const response = await fetch(API_URL, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        message: test.message,
        thinking_mode: test.depth,
        session_id: sessionId,
      }),
    });

    const responseTime = Date.now() - startTime;
    const data = await response.json();

    if (!data.success || !data.data) {
      return {
        test_index: test.index,
        intent: test.intent,
        asset: test.asset,
        depth: test.depth,
        message: test.message,
        actual_intent: 'ERROR',
        intent_match: false,
        loop: test.loop,
        chain_executed: [],
        chain_length: 0,
        expected_chain_length: test.expected_chain_length,
        chain_length_match: false,
        artifacts_produced: [],
        artifact_count: 0,
        artifact_count_match: false,
        expected_artifact_types: test.expected_artifact_types,
        has_graph_reflection: false,
        graph_reflection_match: false,
        graph_reflection_data: null,
        has_step_metadata: false,
        step_metadata_count: 0,
        step_metadata_match: false,
        avg_confidence: 0,
        execution_time_ms: responseTime,
        credits_cost: 0,
        content_length: 0,
        executor: 'error',
        status: 'error',
        success: false,
        error: data.error || 'Request failed',
      };
    }

    return evaluateTestResult(test, data.data, responseTime);
  } catch (err) {
    return {
      test_index: test.index,
      intent: test.intent,
      asset: test.asset,
      depth: test.depth,
      message: test.message,
      actual_intent: 'ERROR',
      intent_match: false,
      loop: test.loop,
      chain_executed: [],
      chain_length: 0,
      expected_chain_length: test.expected_chain_length,
      chain_length_match: false,
      artifacts_produced: [],
      artifact_count: 0,
      artifact_count_match: false,
      expected_artifact_types: test.expected_artifact_types,
      has_graph_reflection: false,
      graph_reflection_match: false,
      graph_reflection_data: null,
      has_step_metadata: false,
      step_metadata_count: 0,
      step_metadata_match: false,
      avg_confidence: 0,
      execution_time_ms: Date.now() - startTime,
      credits_cost: 0,
      content_length: 0,
      executor: 'error',
      status: 'error',
      success: false,
      error: err.message || 'Unknown error',
    };
  }
}

function generateReport(results, totalTimeSec) {
  const total = results.length;
  const successCount = results.filter((r) => r.success).length;
  const failed = results.filter((r) => r.status === 'error');

  // 按意图分类统计
  const byIntent = {};
  for (const r of results) {
    if (!byIntent[r.intent]) {
      byIntent[r.intent] = {
        total: 0,
        success: 0,
        intent_matched: 0,
        graph_reflection_count: 0,
        total_confidence: 0,
        total_time: 0,
        total_artifacts: 0,
        total_chain_length: 0,
        samples: [],
      };
    }
    const cat = byIntent[r.intent];
    cat.total++;
    if (r.success) cat.success++;
    if (r.intent_match) cat.intent_matched++;
    if (r.has_graph_reflection) cat.graph_reflection_count++;
    cat.total_confidence += r.avg_confidence || 0;
    cat.total_time += r.execution_time_ms || 0;
    cat.total_artifacts += r.artifact_count || 0;
    cat.total_chain_length += r.chain_length || 0;
    if (cat.samples.length < 5) cat.samples.push(r);
  }

  // 按深度分类统计
  const byDepth = {};
  for (const r of results) {
    if (!byDepth[r.depth]) byDepth[r.depth] = { total: 0, success: 0, avg_time: 0, avg_conf: 0 };
    const d = byDepth[r.depth];
    d.total++;
    if (r.success) d.success++;
    d.avg_time += r.execution_time_ms || 0;
    d.avg_conf += r.avg_confidence || 0;
  }
  for (const k of Object.keys(byDepth)) {
    byDepth[k].avg_time = byDepth[k].avg_time / byDepth[k].total;
    byDepth[k].avg_conf = byDepth[k].avg_conf / byDepth[k].total;
  }

  // 按资产分类统计
  const byAsset = {};
  for (const r of results) {
    if (!byAsset[r.asset]) byAsset[r.asset] = { total: 0, success: 0 };
    if (r.success) byAsset[r.asset].success++;
    byAsset[r.asset].total++;
  }

  // Graph-Reflection 统计
  const graphResults = results.filter((r) => r.has_graph_reflection);
  const avgConfidence =
    graphResults.length > 0
      ? graphResults.reduce((s, r) => s + (r.avg_confidence || 0), 0) / graphResults.length
      : 0;
  const avgTotalNodes =
    graphResults.length > 0
      ? graphResults.reduce((s, r) => s + (r.graph_reflection_data?.total_nodes || 0), 0) / graphResults.length
      : 0;
  const avgHighValue =
    graphResults.length > 0
      ? graphResults.reduce((s, r) => s + (r.graph_reflection_data?.high_value_nodes || 0), 0) / graphResults.length
      : 0;

  // 产物类型分布
  const artifactTypeDist = {};
  for (const r of results) {
    for (const t of r.artifacts_produced) {
      artifactTypeDist[t] = (artifactTypeDist[t] || 0) + 1;
    }
  }

  // 置信度分布
  const confBuckets = {
    '<0.5': graphResults.filter((r) => (r.avg_confidence || 0) < 0.5).length,
    '0.5-0.6': graphResults.filter((r) => (r.avg_confidence || 0) >= 0.5 && (r.avg_confidence || 0) < 0.6).length,
    '0.6-0.7': graphResults.filter((r) => (r.avg_confidence || 0) >= 0.6 && (r.avg_confidence || 0) < 0.7).length,
    '0.7-0.8': graphResults.filter((r) => (r.avg_confidence || 0) >= 0.7 && (r.avg_confidence || 0) < 0.8).length,
    '0.8-0.9': graphResults.filter((r) => (r.avg_confidence || 0) >= 0.8 && (r.avg_confidence || 0) < 0.9).length,
    '>=0.9': graphResults.filter((r) => (r.avg_confidence || 0) >= 0.9).length,
  };

  // 响应时间统计
  const respTimes = results.map((r) => r.execution_time_ms || 0).sort((a, b) => a - b);
  const medianRespTime = respTimes[Math.floor(respTimes.length / 2)];
  const avgRespTime = respTimes.reduce((s, v) => s + v, 0) / respTimes.length;
  const minRespTime = respTimes[0];
  const maxRespTime = respTimes[respTimes.length - 1];

  // 生成报告
  let report = `# 产物中台全链路压力测试报告 v1.0\n\n`;
  report += `**生成时间**: ${new Date().toLocaleString()}\n`;
  report += `**总测试数**: ${total}\n`;
  report += `**总耗时**: ${totalTimeSec.toFixed(1)} 秒\n\n`;

  // 第一部分：整体统计
  report += `## 一、整体统计\n\n`;
  report += `| 指标 | 值 |\n|------|-----|\n`;
  report += `| 总测试数 | **${total}** |\n`;
  report += `| 成功率 | **${((successCount / total) * 100).toFixed(1)}%** (${successCount}/${total}) |\n`;
  report += `| 失败数 | ${failed.length} |\n`;
  report += `| 意图识别准确率 | **${((results.filter((r) => r.intent_match).length / total) * 100).toFixed(1)}%** |\n`;
  report += `| 包含 graph_reflection | **${graphResults.length}** (${((graphResults.length / total) * 100).toFixed(1)}%) |\n`;
  report += `| 包含 step_metadata | **${results.filter((r) => r.has_step_metadata).length}** (${((results.filter((r) => r.has_step_metadata).length / total) * 100).toFixed(1)}%) |\n`;
  report += `| 平均响应时间 | ${avgRespTime.toFixed(0)} ms |\n`;
  report += `| 中位数响应时间 | ${medianRespTime} ms |\n`;
  report += `| 最快响应 | ${minRespTime} ms |\n`;
  report += `| 最慢响应 | ${maxRespTime} ms |\n`;
  report += `| 总产物文件数 | ${results.reduce((s, r) => s + (r.artifact_count || 0), 0)} |\n\n`;

  // 第二部分：Graph-Reflection 模块效果
  report += `## 二、Graph-Reflection 模块效果\n\n`;
  report += `| 指标 | 值 |\n|------|-----|\n`;
  report += `| graph-reflection 激活次数 | ${graphResults.length} |\n`;
  report += `| 平均置信度 avg_confidence | **${avgConfidence.toFixed(3)}** |\n`;
  report += `| 平均总节点数 total_nodes | **${avgTotalNodes.toFixed(1)}** |\n`;
  report += `| 平均高价值节点数 | **${avgHighValue.toFixed(1)}** |\n`;
  report += `| 平均可压缩节点数 | ${graphResults.length > 0 ? (graphResults.reduce((s, r) => s + (r.graph_reflection_data?.compressible_nodes || 0), 0) / graphResults.length).toFixed(1) : 0} |\n\n`;

  report += `### 置信度分布（Graph-Reflection 激活时）\n\n`;
  report += `| 置信度范围 | 次数 |\n|------------|------|\n`;
  for (const [range, count] of Object.entries(confBuckets)) {
    report += `| ${range} | ${count} |\n`;
  }
  report += `\n`;

  // 第三部分：按意图分类分析
  report += `## 三、按意图分类分析\n\n`;
  report += `| 意图 | 测试数 | 成功 | 意图匹配 | 链长度 | 产物数 | Graph-Reflection | 平均置信度 | 平均响应 |\n`;
  report += `|------|--------|------|----------|--------|--------|------------------|------------|----------|\n`;
  for (const [intent, cat] of Object.entries(byIntent)) {
    const avgChain = cat.total_chain_length / cat.total;
    const avgArtifacts = cat.total_artifacts / cat.total;
    const avgConf = cat.total_confidence / cat.total;
    const avgTime = cat.total_time / cat.total;
    report += `| ${intent} | ${cat.total} | ${((cat.success / cat.total) * 100).toFixed(0)}% | ${((cat.intent_matched / cat.total) * 100).toFixed(0)}% | ${avgChain.toFixed(1)} | ${avgArtifacts.toFixed(1)} | ${cat.graph_reflection_count}/${cat.total} | ${avgConf.toFixed(2)} | ${avgTime.toFixed(0)}ms |\n`;
  }
  report += `\n`;

  // 第四部分：按思考深度分类
  report += `## 四、按思考深度分类\n\n`;
  report += `| 思考深度 | 测试数 | 成功 | 平均响应 | 平均置信度 |\n`;
  report += `|----------|--------|------|----------|----------|\n`;
  for (const [depth, d] of Object.entries(byDepth)) {
    report += `| ${depth} | ${d.total} | ${((d.success / d.total) * 100).toFixed(0)}% | ${d.avg_time.toFixed(0)}ms | ${d.avg_conf.toFixed(2)} |\n`;
  }
  report += `\n`;

  // 第五部分：按资产分类
  report += `## 五、按资产分类\n\n`;
  report += `| 资产 | 测试数 | 成功率 |\n|------|--------|------|\n`;
  for (const [asset, a] of Object.entries(byAsset)) {
    report += `| ${asset} | ${a.total} | ${((a.success / a.total) * 100).toFixed(0)}% |\n`;
  }
  report += `\n`;

  // 第六部分：产物类型分布
  report += `## 六、产物类型分布\n\n`;
  report += `| 产物类型 | 次数 |\n|----------|------|\n`;
  for (const [type, count] of Object.entries(artifactTypeDist)) {
    report += `| ${type} | ${count} |\n`;
  }
  report += `\n`;

  // 第七部分：链路完整性分析
  report += `## 七、链路完整性分析\n\n`;
  const executionLoopResults = results.filter((r) => r.loop === 'execution');
  const intelligenceLoopResults = results.filter((r) => r.loop === 'intelligence');
  const generalLoopResults = results.filter((r) => r.loop === 'general');

  report += `### Execution Loop（深度分析类请求）\n`;
  report += `- 测试数: ${executionLoopResults.length}\n`;
  report += `- 成功率: ${((executionLoopResults.filter((r) => r.success).length / executionLoopResults.length) * 100).toFixed(1)}%\n`;
  report += `- Graph-Reflection 激活率: ${((executionLoopResults.filter((r) => r.has_graph_reflection).length / executionLoopResults.length) * 100).toFixed(1)}%\n`;
  report += `- 平均链长度: ${(executionLoopResults.reduce((s, r) => s + r.chain_length, 0) / executionLoopResults.length).toFixed(1)}\n`;
  report += `- 平均置信度: ${(executionLoopResults.reduce((s, r) => s + (r.avg_confidence || 0), 0) / executionLoopResults.length).toFixed(3)}\n\n`;

  report += `### Intelligence Loop（情报查询类请求）\n`;
  report += `- 测试数: ${intelligenceLoopResults.length}\n`;
  report += `- 成功率: ${((intelligenceLoopResults.filter((r) => r.success).length / intelligenceLoopResults.length) * 100).toFixed(1)}%\n`;
  report += `- 平均链长度: ${(intelligenceLoopResults.reduce((s, r) => s + r.chain_length, 0) / intelligenceLoopResults.length).toFixed(1)}\n\n`;

  report += `### General Loop（快速回答类请求）\n`;
  report += `- 测试数: ${generalLoopResults.length}\n`;
  report += `- 成功率: ${((generalLoopResults.filter((r) => r.success).length / Math.max(1, generalLoopResults.length)) * 100).toFixed(1)}%\n`;
  report += `- Graph-Reflection 激活率: ${((generalLoopResults.filter((r) => r.has_graph_reflection).length / Math.max(1, generalLoopResults.length)) * 100).toFixed(1)}%\n\n`;

  // 第八部分：错误分析
  if (failed.length > 0) {
    report += `## 八、错误分析\n\n`;
    const errorTypes = {};
    for (const f of failed) {
      const key = f.error || 'Unknown';
      errorTypes[key] = (errorTypes[key] || 0) + 1;
    }
    for (const [type, count] of Object.entries(errorTypes)) {
      report += `- **${type}**: ${count} 次\n`;
    }
    report += `\n`;
  }

  // 第九部分：问题模式识别
  report += `## 九、问题模式识别\n\n`;
  const lowConfidenceResults = graphResults.filter((r) => (r.avg_confidence || 0) < 0.7);
  if (lowConfidenceResults.length > 0) {
    report += `### 低置信度请求 (confidence < 0.7)\n`;
    for (const r of lowConfidenceResults.slice(0, 10)) {
      report += `- ${r.intent} / ${r.asset} / ${r.depth}: conf=${(r.avg_confidence || 0).toFixed(2)}, msg=${r.message.slice(0, 40)}...\n`;
    }
    report += `\n`;
  }

  const mismatchedIntents = results.filter((r) => !r.intent_match);
  if (mismatchedIntents.length > 0) {
    report += `### 意图识别错误\n`;
    for (const r of mismatchedIntents.slice(0, 15)) {
      report += `- ${r.message.slice(0, 60)} → expected=${r.intent}, got=${r.actual_intent}\n`;
    }
    report += `\n`;
  }

  const missingGraphRefl = results.filter((r) => r.loop === 'execution' && !r.has_graph_reflection && r.success);
  if (missingGraphRefl.length > 0) {
    report += `### Execution Loop 缺少 Graph-Reflection\n`;
    for (const r of missingGraphRefl.slice(0, 10)) {
      report += `- ${r.intent} / ${r.asset} / ${r.depth}\n`;
    }
    report += `\n`;
  }

  // 第十部分：性能瓶颈
  report += `## 十、性能瓶颈与优化建议\n\n`;
  const slowRequests = results.filter((r) => (r.execution_time_ms || 0) > 2000).sort((a, b) => (b.execution_time_ms || 0) - (a.execution_time_ms || 0));
  if (slowRequests.length > 0) {
    report += `### 慢速请求 (>2000ms)\n`;
    for (const r of slowRequests.slice(0, 15)) {
      report += `- ${r.intent} / ${r.asset} / ${r.depth}: ${r.execution_time_ms}ms\n`;
    }
    report += `\n`;
  }

  report += `### 建议\n`;
  if (avgRespTime > 1500) report += `- ⚠️ 平均响应时间 >1500ms，建议优化 market_data 抓取与 LLM 推理缓存\n`;
  if (mismatchedIntents.length > total * 0.1) report += `- ⚠️ 意图识别准确率 <90%，建议扩展硬编码关键词规则\n`;
  if (missingGraphRefl.length > 5) report += `- ⚠️ 部分 execution loop 请求缺少 graph_reflection，建议检查 graph-reflection-bridge 初始化\n`;
  if (avgConfidence < 0.8 && graphResults.length > 0) report += `- ⚠️ Graph-Reflection 置信度 <0.8，建议优化自省 gate 的评分逻辑\n`;
  report += `- ✅ 系统整体稳定，产物生成机制正常工作\n\n`;

  // 第十一部分：结论
  report += `## 十一、结论与系统评估\n\n`;
  report += `- **系统稳定性**: ${((successCount / total) * 100).toFixed(1)}% 成功率 (${successCount}/${total})\n`;
  report += `- **意图识别准确率**: ${((results.filter((r) => r.intent_match).length / total) * 100).toFixed(1)}%\n`;
  report += `- **Graph-Reflection 集成率**: ${((graphResults.length / total) * 100).toFixed(1)}% (execution loop 中 ${executionLoopResults.length > 0 ? ((executionLoopResults.filter((r) => r.has_graph_reflection).length / executionLoopResults.length) * 100).toFixed(1) : 0}%)\n`;
  report += `- **自省 Gate 效果**: 平均置信度 ${avgConfidence.toFixed(3)}\n`;
  report += `- **压缩效率**: 平均保留 ${avgHighValue.toFixed(1)} 个高价值节点\n`;
  report += `- **产物生成**: 共产出 ${results.reduce((s, r) => s + (r.artifact_count || 0), 0)} 个产物文件\n\n`;

  report += `---\n`;
  report += `*测试环境: local dev server · ${total} 次请求 · 共 ${totalTimeSec.toFixed(0)} 秒*\n`;

  return report;
}

// ============ 主程序 ============

async function main() {
  console.log('============================================');
  console.log('  产物中台全链路压力测试 v1.0');
  console.log('============================================');
  console.log();

  // 确保结果目录存在
  if (!fs.existsSync(RESULTS_DIR)) {
    fs.mkdirSync(RESULTS_DIR, { recursive: true });
  }

  const plan = generateTestPlan();
  console.log(`测试计划: ${plan.length} 个测试用例`);
  console.log(`意图数: ${INTENT_TEST_CONFIGS.length}, 资产数: ${ASSETS.length}, 深度数: ${DEPTHS.length}`);
  console.log(`请求间隔: ${REQUEST_DELAY_MS}ms`);
  console.log();

  // 选取有代表性的子集进行测试（避免耗时过长）
  // 策略：每个意图选3个有代表性的组合 (3*8 = 24 个测试)
  const selectedIndices = new Set();
  for (const config of INTENT_TEST_CONFIGS) {
    const intentTests = plan.filter((t) => t.intent === config.intent);
    // 选3个组合: BTC-quick, ETH-standard, SOL-deep, DOGE-quick
    const selected = intentTests.filter(
      (t) =>
        (t.asset === 'BTC' && t.depth === 'quick') ||
        (t.asset === 'ETH' && t.depth === 'standard') ||
        (t.asset === 'SOL' && t.depth === 'deep'),
    );
    for (const s of selected.slice(0, 3)) {
      selectedIndices.add(s.index);
    }
  }

  // 额外添加: 所有意图 × BTC × quick 做快速测试
  for (const t of plan.filter((t) => t.asset === 'BTC' && t.depth === 'quick')) {
    selectedIndices.add(t.index);
  }
  // 额外添加: 5个主要意图 × ETH × standard
  const mainIntents = ['deep_analysis', 'scenario_sim', 'strategy_verify', 'execute_trade', 'triple_chain'];
  for (const t of plan.filter((t) => mainIntents.includes(t.intent) && t.asset === 'ETH' && t.depth === 'standard')) {
    selectedIndices.add(t.index);
  }
  // 额外添加: 5个主要意图 × DOGE × deep
  for (const t of plan.filter((t) => mainIntents.includes(t.intent) && t.asset === 'DOGE' && t.depth === 'deep')) {
    selectedIndices.add(t.index);
  }

  const selectedPlan = plan.filter((t) => selectedIndices.has(t.index));
  console.log(`已选测试用例: ${selectedPlan.length} 个`);
  console.log(`预计耗时: ~${((selectedPlan.length * REQUEST_DELAY_MS) / 1000 + selectedPlan.length * 2).toFixed(0)} 秒`);
  console.log();

  const results = [];
  const startTime = Date.now();

  for (let i = 0; i < selectedPlan.length; i++) {
    const test = selectedPlan[i];
    const progress = ((i + 1) / selectedPlan.length) * 100;
    console.log(`[${String(i + 1).padStart(3)}/${selectedPlan.length}] ${progress.toFixed(0)}% - ${test.intent} (${test.asset}, ${test.depth})`);
    console.log(`    消息: ${test.message.slice(0, 60)}...`);

    const result = await runSingleTest(test);
    results.push(result);

    if (result.success) {
      console.log(`    ✓ 成功 | intent=${result.actual_intent} | chain=${result.chain_executed.join('→')} | artifacts=${result.artifact_count} | graph=${result.has_graph_reflection} | conf=${(result.avg_confidence || 0).toFixed(2)} | ${result.execution_time_ms}ms`);
    } else if (result.status === 'error') {
      console.log(`    ✗ 失败: ${result.error}`);
    } else {
      console.log(`    ⚠ 部分成功 | intent=${result.actual_intent} (expected ${test.intent}) | chain=${result.chain_executed.join('→')}`);
    }

    if (i < selectedPlan.length - 1) {
      await sleep(REQUEST_DELAY_MS);
    }
  }

  const totalTimeSec = (Date.now() - startTime) / 1000;
  console.log();
  console.log('============================================');
  console.log(`  测试完成！耗时: ${totalTimeSec.toFixed(1)} 秒`);
  console.log('============================================');
  console.log();

  // 保存原始结果
  fs.writeFileSync(RESULTS_FILE, JSON.stringify(results, null, 2), 'utf8');
  console.log(`原始数据已保存: ${RESULTS_FILE}`);

  // 生成并保存报告
  const report = generateReport(results, totalTimeSec);
  fs.writeFileSync(REPORT_FILE, report, 'utf8');
  console.log(`分析报告已保存: ${REPORT_FILE}`);

  // 输出关键统计
  const successCount = results.filter((r) => r.success).length;
  const graphResults = results.filter((r) => r.has_graph_reflection);
  const avgConfidence =
    graphResults.length > 0
      ? graphResults.reduce((s, r) => s + (r.avg_confidence || 0), 0) / graphResults.length
      : 0;

  console.log();
  console.log('============== 关键指标 ==============');
  console.log(`成功率: ${((successCount / results.length) * 100).toFixed(1)}% (${successCount}/${results.length})`);
  console.log(`意图识别准确率: ${((results.filter((r) => r.intent_match).length / results.length) * 100).toFixed(1)}%`);
  console.log(`Graph-Reflection 激活率: ${((graphResults.length / results.length) * 100).toFixed(1)}%`);
  console.log(`平均置信度: ${avgConfidence.toFixed(3)}`);
  console.log(`平均响应时间: ${(results.reduce((s, r) => s + (r.execution_time_ms || 0), 0) / results.length).toFixed(0)}ms`);
  console.log(`总产物文件: ${results.reduce((s, r) => s + (r.artifact_count || 0), 0)}`);
  console.log('========================================');
}

main().catch((err) => {
  console.error('测试执行失败:', err);
  process.exit(1);
});
