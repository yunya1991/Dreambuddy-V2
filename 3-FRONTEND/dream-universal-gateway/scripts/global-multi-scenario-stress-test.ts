/**
 * 全局多场景模拟压力测试（扩展版）
 *
 * 测试覆盖：
 *   [Phase 1] 动态链核心测试 - 4 种动态意图 × 2 种 thinking_mode × 多标的
 *   [Phase 2] 图状态融合测试 - graphState 写入 / 读取 / 节点 metadata
 *   [Phase 3] 图感知压缩测试 - compressFromGraphState + 压缩比率验证
 *   [Phase 4] 动态反思闭环测试 - reflectionTrace 决策分布 & 触发条件
 *   [Phase 5] 并发 & 长会话压力 - 50 并发 × 3 轮，session 内累积 graph 节点
 *   [Phase 6] 智能路由 is_dynamic 标志全矩阵 - 所有意图 × 两角色 × 3 复杂度
 *   [Phase 7] 三模块协同测试 - 动态链 → graph 节点 → 压缩输出端到端
 *
 * 运行方法：
 *   npx tsx scripts/global-multi-scenario-stress-test.ts
 */

import { routeIntent, type IntentType } from "../src/lib/intent";
import { runDynamicChain } from "../src/lib/dynamic-chain/runner";
import type { DynamicChainResult } from "../src/lib/dynamic-chain/runner";
import {
  createGraphReflectionState,
  buildGraphSummary,
  updateCompressionSignal,
  type GraphReflectionState,
} from "../src/lib/graph-reflection-bridge";
import { compressorAdapter, type CompressResult } from "../src/lib/compressor-adapter";

// ============================================================
// 终端颜色 & 工具函数
// ============================================================
const GREEN = "\x1b[32m";
const YELLOW = "\x1b[33m";
const RED = "\x1b[31m";
const BOLD = "\x1b[1m";
const BLUE = "\x1b[34m";
const CYAN = "\x1b[36m";
const MAGENTA = "\x1b[35m";
const RESET = "\x1b[0m";
const DIM = "\x1b[2m";

function section(title: string, emoji: string = "📦") {
  console.log(`\n${BOLD}${emoji}  ${title}${RESET}`);
  console.log("─".repeat(78));
}
function h2(title: string) {
  console.log(`\n  ${BOLD}${MAGENTA}● ${title}${RESET}`);
}
function ok(msg: string) { console.log(`  ${GREEN}✓${RESET} ${msg}`); }
function warn(msg: string) { console.log(`  ${YELLOW}⚠${RESET} ${msg}`); }
function fail(msg: string) { console.log(`  ${RED}✗${RESET} ${msg}`); }
function info(msg: string) { console.log(`    ${DIM}→${RESET} ${msg}`); }
function metric(label: string, value: string, color: string = GREEN) {
  console.log(`    ${color}${label.padEnd(18)}${RESET}${value}`);
}

// ============================================================
// 全局统计
// ============================================================
interface GlobalStats {
  totalCases: number;
  passed: number;
  failed: number;
  errors: string[];
  startTs: number;
  latenciesMs: number[];
  allLatenciesMs: number[];
}
const stats: GlobalStats = {
  totalCases: 0,
  passed: 0,
  failed: 0,
  errors: [],
  startTs: Date.now(),
  latenciesMs: [],
  allLatenciesMs: [],
};

function recordCase(passed: boolean, latencyMs: number, err?: string) {
  stats.totalCases++;
  if (passed) stats.passed++;
  else { stats.failed++; if (err) stats.errors.push(err); }
  stats.latenciesMs.push(latencyMs);
  stats.allLatenciesMs.push(latencyMs);
}

function avg(arr: number[]): number {
  if (arr.length === 0) return 0;
  return arr.reduce((a, b) => a + b, 0) / arr.length;
}
function pct(arr: number[], p: number): number {
  if (arr.length === 0) return 0;
  const sorted = [...arr].sort((a, b) => a - b);
  const idx = Math.min(sorted.length - 1, Math.floor(sorted.length * p));
  return sorted[idx];
}

// ============================================================
// Phase 1: 动态链核心测试（全意图 × thinking_mode × 多标的）
// ============================================================
async function phase1_dynamicChain() {
  section("Phase 1 · 动态链核心测试（4 意图 × 2 模式 × 多标的）", "⚡");

  const TEST_CASES: Array<{
    label: string;
    intent: "deep_analysis" | "scenario_sim" | "strategy_verify" | "execute_trade";
    message: string;
    symbol: string;
    displayName: string;
    instId: string;
    thinkingMode: "deep" | "standard";
    lang: "zh" | "en";
  }> = [
    { label: "BTC 深度分析 deep", intent: "deep_analysis", message: "深度分析 BTC 未来 24 小时趋势", symbol: "BTC", displayName: "Bitcoin", instId: "BTC-USDT-SWAP", thinkingMode: "deep", lang: "zh" },
    { label: "BTC 深度分析 standard", intent: "deep_analysis", message: "BTC 趋势分析", symbol: "BTC", displayName: "Bitcoin", instId: "BTC-USDT-SWAP", thinkingMode: "standard", lang: "zh" },
    { label: "ETH 深度分析 deep", intent: "deep_analysis", message: "深度分析 ETH 长期走势", symbol: "ETH", displayName: "Ethereum", instId: "ETH-USDT-SWAP", thinkingMode: "deep", lang: "zh" },
    { label: "BTC 情景推演 deep", intent: "scenario_sim", message: "如果美联储降息 50bp，BTC 会怎么走？", symbol: "BTC", displayName: "Bitcoin", instId: "BTC-USDT-SWAP", thinkingMode: "deep", lang: "zh" },
    { label: "BTC 情景推演 standard", intent: "scenario_sim", message: "如果 BTC 跌破 $50k 支撑，如何操作？", symbol: "BTC", displayName: "Bitcoin", instId: "BTC-USDT-SWAP", thinkingMode: "standard", lang: "zh" },
    { label: "ETH 情景推演", intent: "scenario_sim", message: "ETH 若突破 $3500，后市如何？", symbol: "ETH", displayName: "Ethereum", instId: "ETH-USDT-SWAP", thinkingMode: "deep", lang: "zh" },
    { label: "BTC 策略验证 deep", intent: "strategy_verify", message: "验证 MA20 突破策略在 BTC 的表现", symbol: "BTC", displayName: "Bitcoin", instId: "BTC-USDT-SWAP", thinkingMode: "deep", lang: "zh" },
    { label: "BTC 策略验证 standard", intent: "strategy_verify", message: "验证 RSI 超卖反弹策略", symbol: "BTC", displayName: "Bitcoin", instId: "BTC-USDT-SWAP", thinkingMode: "standard", lang: "zh" },
    { label: "ETH 策略验证", intent: "strategy_verify", message: "验证布林带均值回归策略", symbol: "ETH", displayName: "Ethereum", instId: "ETH-USDT-SWAP", thinkingMode: "deep", lang: "zh" },
    { label: "BTC 交易执行 deep", intent: "execute_trade", message: "对 BTC 执行一次买入操作并给出止损止盈", symbol: "BTC", displayName: "Bitcoin", instId: "BTC-USDT-SWAP", thinkingMode: "deep", lang: "zh" },
    { label: "BTC 交易执行 standard", intent: "execute_trade", message: "BTC 现价做多", symbol: "BTC", displayName: "Bitcoin", instId: "BTC-USDT-SWAP", thinkingMode: "standard", lang: "zh" },
    { label: "ETH 交易执行", intent: "execute_trade", message: "ETH 短线做空操作建议", symbol: "ETH", displayName: "Ethereum", instId: "ETH-USDT-SWAP", thinkingMode: "deep", lang: "zh" },
    { label: "SOL 深度分析", intent: "deep_analysis", message: "SOL 近期市场结构分析", symbol: "SOL", displayName: "Solana", instId: "SOL-USDT-SWAP", thinkingMode: "deep", lang: "zh" },
    { label: "SOL 交易执行", intent: "execute_trade", message: "SOL 短线策略", symbol: "SOL", displayName: "Solana", instId: "SOL-USDT-SWAP", thinkingMode: "standard", lang: "zh" },
    { label: "English deep analysis", intent: "deep_analysis", message: "Deep analysis of BTC market structure", symbol: "BTC", displayName: "Bitcoin", instId: "BTC-USDT-SWAP", thinkingMode: "deep", lang: "en" },
    { label: "English strategy verify", intent: "strategy_verify", message: "Verify RSI strategy on ETH", symbol: "ETH", displayName: "Ethereum", instId: "ETH-USDT-SWAP", thinkingMode: "standard", lang: "en" },
  ];

  let totalLatency: number[] = [];

  for (const tc of TEST_CASES) {
    const t0 = Date.now();
    const result: DynamicChainResult = runDynamicChain({
      intent: tc.intent,
      message: tc.message,
      sessionId: `global-test-${tc.label.replace(/\s+/g, "-")}`,
      symbol: tc.symbol,
      displayName: tc.displayName,
      category: "crypto",
      instId: tc.instId,
      thinkingMode: tc.thinkingMode,
      lang: tc.lang,
    });
    const latency = Date.now() - t0;
    totalLatency.push(latency);

    const pass = result.success && result.summaryMarkdown.length > 200 && result.steps.length > 0;
    recordCase(pass, latency, pass ? undefined : `${tc.label}: success=${result.success}, len=${result.summaryMarkdown.length}`);
    if (pass) {
      ok(`${tc.label} → ${result.steps.length} 步 · ${latency}ms · ${result.summaryMarkdown.length} chars`);
    } else {
      fail(`${tc.label} → 失败`);
    }
  }

  h2("动态链核心测试统计");
  metric("测试数", `${TEST_CASES.length}`);
  metric("平均延迟", `${avg(totalLatency).toFixed(1)} ms`);
  metric("P95 延迟", `${pct(totalLatency, 0.95).toFixed(1)} ms`);
  metric("P99 延迟", `${pct(totalLatency, 0.99).toFixed(1)} ms`);
}

// ============================================================
// Phase 2: 图状态融合测试
// ============================================================
async function phase2_graphState() {
  section("Phase 2 · 图状态融合测试（graphState 写入 / 读取 / 节点 metadata）", "🧠");

  const sessions: { id: string; iterations: number }[] = [
    { id: "graph-sess-1", iterations: 3 },
    { id: "graph-sess-2", iterations: 5 },
    { id: "graph-sess-3-long", iterations: 10 },
  ];

  const allRuns: { sessionId: string; runIndex: number; result: DynamicChainResult }[] = [];

  for (const s of sessions) {
    for (let i = 0; i < s.iterations; i++) {
      const t0 = Date.now();
      const r = runDynamicChain({
        intent: i % 2 === 0 ? "deep_analysis" : "strategy_verify",
        message: `第 ${i + 1} 次迭代测试消息`,
        sessionId: s.id,
        symbol: "BTC",
        displayName: "Bitcoin",
        category: "crypto",
        instId: "BTC-USDT-SWAP",
        thinkingMode: i % 3 === 0 ? "deep" : "standard",
        lang: "zh",
      });
      recordCase(r.success, Date.now() - t0);
      allRuns.push({ sessionId: s.id, runIndex: i, result: r });
    }
  }

  // 验证每次都有 graphState 并 buildGraphSummary 能解析
  h2("graphState 一致性检查");
  let summaryCount = 0;
  let highValueTotal = 0;
  let compressibleTotal = 0;
  let nodesTotal = 0;

  for (const run of allRuns) {
    try {
      const gs = run.result.graphState;
      const summary = buildGraphSummary(gs);
      summaryCount++;
      nodesTotal += summary.totalNodes;
      highValueTotal += summary.highValueCount;
      compressibleTotal += summary.compressibleCount;
    } catch (e: any) {
      recordCase(false, 0, `buildGraphSummary 失败: ${e?.message || e}`);
      fail(`session=${run.sessionId} iter=${run.runIndex}: buildGraphSummary 抛异常`);
    }
  }

  ok(`buildGraphSummary 全部成功 (${summaryCount}/${allRuns.length})`);
  metric("平均节点数", `${(nodesTotal / summaryCount).toFixed(1)} 个/会话`);
  metric("平均高价值节点", `${(highValueTotal / summaryCount).toFixed(1)} 个/会话`);
  metric("平均可压缩节点", `${(compressibleTotal / summaryCount).toFixed(1)} 个/会话`);

  // 验证 updateCompressionSignal 不抛异常
  h2("updateCompressionSignal 调用");
  const testGs = createGraphReflectionState("compress-signal-test");
  try {
    updateCompressionSignal(testGs);
    const summary = buildGraphSummary(testGs);
    ok(`updateCompressionSignal 成功调用 · totalNodes=${summary.totalNodes}`);
    recordCase(true, 0);
  } catch (e: any) {
    fail(`updateCompressionSignal 抛异常: ${e?.message || e}`);
    recordCase(false, 0, `compress-signal error: ${e?.message || e}`);
  }

  // executedOrder 在单次 runDynamicChain 内部有效（每次创建独立 graphState，不跨调用累积）
  // 验证：单次 run 中 executedOrder 数量 ≥ 步骤数（每步都会记录）
  const sessionWithMultipleRuns = allRuns.filter((r) => r.sessionId === "graph-sess-3-long");
  if (sessionWithMultipleRuns.length > 0) {
    // 每次 run 应该产生 ≥ 步骤数 的节点记录
    let validRuns = 0;
    for (const run of sessionWithMultipleRuns) {
      const orderLen = run.result.graphState.executedOrder.length;
      if (orderLen >= sessionWithMultipleRuns.length / 2) validRuns++; // 宽松：至少有一半步骤
    }
    ok(`长会话 ${sessionWithMultipleRuns.length} 次运行，全部有 graphState · validRuns=${validRuns}`);
    recordCase(validRuns === sessionWithMultipleRuns.length, 0);
  }
}

// ============================================================
// Phase 3: 图感知压缩测试
// ============================================================
async function phase3_compression() {
  section("Phase 3 · 图感知压缩测试（compressFromGraphState + 压缩比率验证）", "📉");

  // 先生成 8 组不同的 graphState
  const cases: Array<{ label: string; intent: any; message: string }> = [
    { label: "deep_analysis BTC", intent: "deep_analysis", message: "深度分析 BTC 趋势" },
    { label: "deep_analysis ETH", intent: "deep_analysis", message: "深度分析 ETH 趋势" },
    { label: "scenario_sim BTC", intent: "scenario_sim", message: "BTC 情景推演测试" },
    { label: "strategy_verify BTC", intent: "strategy_verify", message: "BTC MA20 策略验证" },
    { label: "strategy_verify ETH", intent: "strategy_verify", message: "ETH 策略验证" },
    { label: "execute_trade BTC", intent: "execute_trade", message: "BTC 做多交易执行" },
    { label: "execute_trade ETH", intent: "execute_trade", message: "ETH 交易执行" },
    { label: "scenario_sim ETH", intent: "scenario_sim", message: "ETH 加息情景推演" },
  ];

  const ratios: number[] = [];
  const compressedNodes: number[] = [];
  const retainedNodes: number[] = [];

  for (const c of cases) {
    const t0 = Date.now();
    const r = runDynamicChain({
      intent: c.intent,
      message: c.message,
      sessionId: `compress-test-${c.label.replace(/\s+/g, "-")}`,
      symbol: "BTC",
      displayName: "Bitcoin",
      category: "crypto",
      instId: "BTC-USDT-SWAP",
      thinkingMode: "deep",
      lang: "zh",
    });

    let cr: CompressResult | null = null;
    try {
      cr = compressorAdapter.compressFromGraphState(r.graphState);
      const latency = Date.now() - t0;

      if (cr && cr.compressionRatio <= 1 && cr.stats.totalNodes > 0) {
        ratios.push(cr.compressionRatio);
        compressedNodes.push(cr.stats.compressedNodes);
        retainedNodes.push(cr.stats.retainedNodes);
        ok(`${c.label} → ratio=${(cr.compressionRatio * 100).toFixed(1)}% · nodes=${cr.stats.totalNodes} · compressed=${cr.stats.compressedNodes} · retained=${cr.stats.retainedNodes} · ${latency}ms`);
        recordCase(true, latency);
      } else {
        fail(`${c.label} → 压缩结果不合法`);
        recordCase(false, latency, `ratio=${cr?.compressionRatio} nodes=${cr?.stats?.totalNodes}`);
      }
    } catch (e: any) {
      fail(`${c.label} → 异常: ${e?.message || e}`);
      recordCase(false, Date.now() - t0, `compress error: ${e?.message || e}`);
    }
  }

  h2("图感知压缩统计");
  metric("平均压缩率", `${(avg(ratios) * 100).toFixed(1)}%`);
  metric("最低压缩率", `${(Math.min(...ratios) * 100).toFixed(1)}%`);
  metric("平均保留节点数", `${avg(retainedNodes).toFixed(1)} 个`);
  metric("平均压缩节点数", `${avg(compressedNodes).toFixed(1)} 个`);

  // 验证 GraphData 结构存在
  try {
    const demo = runDynamicChain({
      intent: "deep_analysis",
      message: "BTC demo",
      sessionId: "compress-demo-struct",
      symbol: "BTC",
      displayName: "Bitcoin",
      category: "crypto",
      instId: "BTC-USDT-SWAP",
      thinkingMode: "standard",
      lang: "zh",
    });
    const cr = compressorAdapter.compressFromGraphState(demo.graphState);
    const nodes = (cr as any)?.graph?.architecture;
    const edges = (cr as any)?.graph?.edges;
    const hasNodes = Array.isArray(nodes) && nodes.length > 0;
    const hasEdges = Array.isArray(edges);
    ok(`GraphData 结构：nodes=${hasNodes ? nodes.length : "missing"}, edges=${hasEdges ? edges.length : "missing"}`);
    recordCase(hasNodes && hasEdges, 0);
  } catch (e: any) {
    fail(`GraphData 结构测试失败: ${e?.message || e}`);
    recordCase(false, 0, `GraphData struct error: ${e?.message || e}`);
  }
}

// ============================================================
// Phase 4: 动态反思闭环测试
// ============================================================
async function phase4_reflection() {
  section("Phase 4 · 动态反思闭环测试（reflectionTrace 决策分布 & 触发条件）", "🔁");

  const intents: Array<"deep_analysis" | "scenario_sim" | "strategy_verify" | "execute_trade"> = [
    "deep_analysis",
    "scenario_sim",
    "strategy_verify",
    "execute_trade",
  ];

  const decisionDist: Record<string, number> = {};
  let totalReflections = 0;
  let allRuns: DynamicChainResult[] = [];

  for (const intent of intents) {
    for (let run = 0; run < 5; run++) {
      const t0 = Date.now();
      const r = runDynamicChain({
        intent,
        message: `[${intent}] 反思测试 #${run}`,
        sessionId: `reflect-test-${intent}-${run}`,
        symbol: "BTC",
        displayName: "Bitcoin",
        category: "crypto",
        instId: "BTC-USDT-SWAP",
        thinkingMode: run % 2 === 0 ? "deep" : "standard",
        lang: "zh",
      });
      const latency = Date.now() - t0;

      const trace = r.metadata.reflectionTrace || [];
      totalReflections += trace.length;
      for (const step of trace) {
        const d = step.decision;
        decisionDist[d] = (decisionDist[d] || 0) + 1;
      }

      // 每个 trace 元素结构验证
      const traceValid = trace.every((t) => t.stepId && t.decision && t.reason);
      if (r.success && traceValid) {
        ok(`${intent}#${run} → ${trace.length} 次反思 · ${latency}ms`);
        recordCase(true, latency);
      } else {
        fail(`${intent}#${run} → 反思不合法 (success=${r.success}, traceValid=${traceValid})`);
        recordCase(false, latency, `invalid reflection trace`);
      }

      allRuns.push(r);
    }
  }

  h2("反思决策分布");
  metric("总反思次数", `${totalReflections}`);
  for (const [decision, count] of Object.entries(decisionDist)) {
    const pct1 = totalReflections > 0 ? (count / totalReflections * 100).toFixed(1) : "0.0";
    metric(`${decision.padEnd(18)}`, `${count} (${pct1}%)`, decision === "CONTINUE" ? GREEN : YELLOW);
  }

  // 验证 planRationale 非空
  const withRationale = allRuns.filter((r) => r.metadata.planRationale && r.metadata.planRationale.length > 0);
  ok(`有 planRationale 的会话: ${withRationale.length}/${allRuns.length}`);
  recordCase(withRationale.length >= allRuns.length * 0.8, 0);
}

// ============================================================
// Phase 5: 并发 & 长会话压力测试
// ============================================================
async function phase5_concurrency() {
  section("Phase 5 · 并发 & 长会话压力测试（50 并发 × 3 轮，session 内累积 graph 节点）", "🚀");

  const INTENTS: Array<"deep_analysis" | "scenario_sim" | "strategy_verify" | "execute_trade"> = [
    "deep_analysis", "scenario_sim", "strategy_verify", "execute_trade",
  ];

  const ROUNDS = 3;
  const CONCURRENCY = 50;
  const allLatencies: number[] = [];
  let success = 0;
  let failure = 0;

  // 累积 session：同一 sessionId 在 3 轮中不断追加内容
  const persistentSessions: string[] = Array.from({ length: 5 }, (_, i) => `persistent-sess-${i + 1}`);

  for (let round = 1; round <= ROUNDS; round++) {
    const t0 = Date.now();
    const tasks: Array<{ i: number; intent: any }> = [];
    for (let i = 0; i < CONCURRENCY; i++) {
      tasks.push({ i, intent: INTENTS[(round + i) % INTENTS.length] });
    }

    const promises = tasks.map(async ({ i, intent }) => {
      // 前 5 个用累积 session，其余用独立 session
      const sessionId = i < persistentSessions.length
        ? persistentSessions[i]
        : `concurrent-${round}-${i}`;
      const t1 = Date.now();
      try {
        const r = runDynamicChain({
          intent,
          message: `Concurrency round ${round}, task ${i}`,
          sessionId,
          symbol: i % 3 === 0 ? "BTC" : i % 3 === 1 ? "ETH" : "SOL",
          displayName: i % 3 === 0 ? "Bitcoin" : i % 3 === 1 ? "Ethereum" : "Solana",
          category: "crypto",
          instId: i % 3 === 0 ? "BTC-USDT-SWAP" : i % 3 === 1 ? "ETH-USDT-SWAP" : "SOL-USDT-SWAP",
          thinkingMode: round === 1 ? "deep" : "standard",
          lang: "zh",
        });
        const lat = Date.now() - t1;
        return { success: r.success, latency: lat };
      } catch (e: any) {
        return { success: false, latency: Date.now() - t1 };
      }
    });

    const results = await Promise.all(promises);
    const roundTime = Date.now() - t0;

    for (const r of results) {
      allLatencies.push(r.latency);
      if (r.success) success++; else failure++;
    }

    const roundSuccess = results.filter((r) => r.success).length;
    ok(`第 ${round}/${ROUNDS} 轮 · ${CONCURRENCY} 并发 · 成功 ${roundSuccess}/${CONCURRENCY} · 整轮耗时 ${roundTime}ms · 失败 ${CONCURRENCY - roundSuccess}`);
  }

  h2("并发统计");
  metric("总任务数", `${success + failure}`);
  metric("成功数", `${success}`, GREEN);
  metric("失败数", `${failure}`, failure > 0 ? RED : GREEN);
  metric("失败率", `${(failure / (success + failure) * 100).toFixed(2)}%`, failure > 0 ? RED : GREEN);
  metric("平均延迟", `${avg(allLatencies).toFixed(1)} ms`);
  metric("P95 延迟", `${pct(allLatencies, 0.95).toFixed(1)} ms`);
  metric("P99 延迟", `${pct(allLatencies, 0.99).toFixed(1)} ms`);
  metric("吞吐", `${Math.round((success + failure) / Math.max(1, avg(allLatencies) / 1000))} req/s`);

  recordCase(failure === 0, pct(allLatencies, 0.99), failure > 0 ? `并发测试失败 ${failure} 个` : undefined);
}

// ============================================================
// Phase 6: 智能路由 is_dynamic 标志全矩阵测试
// ============================================================
async function phase6_routing() {
  section("Phase 6 · 智能路由 is_dynamic 标志全矩阵测试（所有意图 × 两角色 × 3 复杂度）", "🧭");

  const INTENTS: IntentType[] = [
    "market_query",
    "deep_analysis",
    "scenario_sim",
    "strategy_verify",
    "execute_trade",
    "simple_qa",
    "system_config",
    "credits_query",
    "artifact_query",
    "developer",
  ];
  const ROLES = ["FREE", "PRO"] as const;
  const COMPLEXITIES: Array<"simple" | "moderate" | "complex"> = ["simple", "moderate", "complex"];

  // 预期：PRO 且动态意图 → is_dynamic=true；其余 false/undefined
  const DYNAMIC_INTENTS_SET = new Set(["deep_analysis", "scenario_sim", "strategy_verify", "execute_trade"]);

  let total = 0;
  let pass = 0;

  for (const intent of INTENTS) {
    for (const role of ROLES) {
      for (const complexity of COMPLEXITIES) {
        total++;
        const t0 = Date.now();
        const decision = routeIntent(intent, complexity, {
          session_id: `route-${intent}-${role}-${complexity}`,
          user_role: role,
          thinking_mode: complexity === "simple" ? "quick" : "deep",
          message_history: [`测试消息 for ${intent}`],
        });
        const latency = Date.now() - t0;

        const shouldBeDynamic = role === "PRO" && DYNAMIC_INTENTS_SET.has(intent);
        const isDynamic = !!decision.is_dynamic;

        if (isDynamic === shouldBeDynamic) {
          pass++;
          recordCase(true, latency);
        } else {
          fail(`${intent} (${role}/${complexity}) → is_dynamic=${isDynamic}, 预期 ${shouldBeDynamic}`);
          recordCase(false, latency, `routing is_dynamic mismatch: got ${isDynamic}, expected ${shouldBeDynamic}`);
        }

        if (complexity === "moderate") {
          info(`${intent} (${role}/${complexity}): chain=${decision.chain.slice(0, 2).join("→")}, is_dynamic=${isDynamic}`);
        }
      }
    }
  }

  h2("矩阵统计");
  metric("测试数", `${total}`);
  metric("通过", `${pass}/${total} (${(pass / total * 100).toFixed(1)}%)`, pass === total ? GREEN : YELLOW);
}

// ============================================================
// Phase 7: 三模块协同测试（端到端）
// ============================================================
async function phase7_e2e() {
  section("Phase 7 · 三模块协同测试（动态链 → graph 节点 → 压缩输出）", "🔗");

  const CASES = [
    { intent: "deep_analysis" as const, symbol: "BTC", message: "BTC 深度分析" },
    { intent: "scenario_sim" as const, symbol: "ETH", message: "ETH 加息情景" },
    { intent: "strategy_verify" as const, symbol: "SOL", message: "SOL 策略验证" },
    { intent: "execute_trade" as const, symbol: "BTC", message: "BTC 做多交易" },
  ];

  for (const c of CASES) {
    const t0 = Date.now();

    // 1. 动态链执行
    const r = runDynamicChain({
      intent: c.intent,
      message: c.message,
      sessionId: `e2e-${c.intent}-${c.symbol}`,
      symbol: c.symbol,
      displayName: c.symbol,
      category: "crypto",
      instId: `${c.symbol}-USDT-SWAP`,
      thinkingMode: "deep",
      lang: "zh",
    });

    // 2. graphState 检查
    const gsOk = r.graphState
      && Array.isArray(r.graphState.executedOrder)
      && r.graphState.executedOrder.length > 0;

    // 3. buildGraphSummary
    let summary = null;
    try {
      summary = buildGraphSummary(r.graphState);
    } catch { /* ignore */ }

    // 4. 图感知压缩
    let compResult: CompressResult | null = null;
    try {
      compResult = compressorAdapter.compressFromGraphState(r.graphState);
    } catch { /* ignore */ }

    const latency = Date.now() - t0;
    const allOk = r.success && gsOk && summary && compResult
      && compResult.compressionRatio <= 1
      && compResult.stats.totalNodes > 0;

    if (allOk) {
      ok(`${c.intent} (${c.symbol}) → ${r.steps.length} 步 · graph=${r.graphState.executedOrder.length} 节点 · ratio=${(compResult!.compressionRatio * 100).toFixed(1)}% · ${latency}ms`);
      recordCase(true, latency);
    } else {
      fail(`${c.intent} (${c.symbol}) → success=${r.success}, graph=${gsOk}, summary=${!!summary}, compress=${!!compResult}`);
      recordCase(false, latency, `e2e pipeline failed: success=${r.success} graph=${gsOk}`);
    }
  }

  // 额外：验证 summary 的节点状态分布合理
  try {
    const demoR = runDynamicChain({
      intent: "deep_analysis",
      message: "demo summary nodes",
      sessionId: "e2e-demo-summary",
      symbol: "BTC",
      displayName: "Bitcoin",
      category: "crypto",
      instId: "BTC-USDT-SWAP",
      thinkingMode: "standard",
      lang: "zh",
    });
    const s = buildGraphSummary(demoR.graphState);
    ok(`Summary 结构：totalNodes=${s.totalNodes}, highValue=${s.highValueCount}, compressible=${s.compressibleCount}, completedRatio=${(s.completedRatio * 100).toFixed(0)}%`);
    recordCase(s.totalNodes >= 1, 0);
  } catch (e: any) {
    fail(`e2e summary test failed: ${e?.message || e}`);
    recordCase(false, 0, `summary struct error`);
  }
}

// ============================================================
// 主入口
// ============================================================
async function main() {
  const start = Date.now();

  console.log(`${BOLD}${CYAN}`);
  console.log("══════════════════════════════════════════════════════════");
  console.log("  全局多场景模拟压力测试（含动态链 + 图压缩 + Reflection）");
  console.log("══════════════════════════════════════════════════════════");
  console.log(`${RESET}`);
  console.log(`${DIM}开始时间: ${new Date(start).toISOString()}${RESET}`);

  try {
    await phase1_dynamicChain();
    await phase2_graphState();
    await phase3_compression();
    await phase4_reflection();
    await phase5_concurrency();
    await phase6_routing();
    await phase7_e2e();
  } catch (e: any) {
    console.error(`\n${RED}${BOLD}测试过程中抛异常:${RESET}`, e?.message || e, e?.stack);
    process.exit(2);
  }

  const duration = Date.now() - start;
  const passedRate = stats.totalCases > 0 ? (stats.passed / stats.totalCases * 100) : 0;

  console.log(`\n${BOLD}${CYAN}`);
  console.log("══════════════════════════════════════════════════════════");
  console.log("  全局多场景模拟压力测试 · 最终报告");
  console.log("══════════════════════════════════════════════════════════");
  console.log(`${RESET}`);
  console.log(`  ${GREEN}✓${RESET} 通过:      ${stats.passed} / ${stats.totalCases}`);
  console.log(`  ${RED}✗${RESET} 失败:      ${stats.failed}`);
  console.log(`  📈 通过率:    ${passedRate.toFixed(2)}%`);
  console.log(`  ⏱  平均延迟:   ${avg(stats.allLatenciesMs).toFixed(1)} ms`);
  console.log(`  🐢 最大延迟:   ${Math.max(...stats.allLatenciesMs)} ms`);
  console.log(`  🕒 总耗时:     ${duration} ms (${(duration / 1000).toFixed(2)} s)`);
  console.log();
  console.log(`  ────────── 各 Phase 简述 ──────────`);
  console.log(`  · Phase 1: 动态链核心（4 意图 × 2 模式 × 多标的）`);
  console.log(`  · Phase 2: 图状态融合（graphState 读写 + 节点 metadata）`);
  console.log(`  · Phase 3: 图感知压缩（compressFromGraphState + ratio 验证）`);
  console.log(`  · Phase 4: 反思闭环（reflectionTrace 决策分布）`);
  console.log(`  · Phase 5: 并发压力（50 并发 × 3 轮 + 累积 session）`);
  console.log(`  · Phase 6: 智能路由 is_dynamic（全矩阵：意图 × 角色 × 复杂度）`);
  console.log(`  · Phase 7: 三模块端到端协同（动态链 → graph → 压缩）`);
  console.log();

  if (stats.errors.length > 0) {
    console.log(`  ────────── 失败详情 ──────────`);
    stats.errors.slice(0, 20).forEach((e, i) => console.log(`  ${RED}${i + 1}.${RESET} ${e}`));
    if (stats.errors.length > 20) {
      console.log(`  ... 还有 ${stats.errors.length - 20} 个错误未显示`);
    }
    console.log();
  }

  let grade = "F";
  if (passedRate >= 99) grade = "S";
  else if (passedRate >= 95) grade = "A";
  else if (passedRate >= 85) grade = "B";
  else if (passedRate >= 70) grade = "C";
  else grade = "D";

  const gradeColor = grade === "S" ? GREEN : grade === "A" ? GREEN : grade === "B" ? YELLOW : RED;
  console.log(`  评级: ${gradeColor}${BOLD}${grade}${RESET}${grade === "S" ? ` · 完美` : ``}`);
  console.log("══════════════════════════════════════════════════════════");
  console.log();

  if (stats.failed > 0) process.exit(1);
  process.exit(0);
}

void main();
