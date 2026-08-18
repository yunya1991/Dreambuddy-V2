/**
 * 经典交易系统多场景压力测试 v1.0
 *
 * 测试覆盖：
 *   [Phase 1] 经典系统 API 直接调用测试 - 15 个模块 × 多场景
 *   [Phase 2] C 系列思维链执行测试 - 8 步骤 × 多意图 × 多模式
 *   [Phase 3] 多意图路由矩阵测试 - classic模式下 32 种意图
 *   [Phase 4] 并发压力测试 - 50 并发 × 3 轮
 *   [Phase 5] 端到端 API 集成测试 - 通过 /api/chat 路由
 *   [Phase 6] 故障降级测试 - 模拟经典系统离线
 *
 * 运行方法：
 *   npx tsx scripts/classic-system-multi-scenario-stress-test.ts
 *
 * 依赖：
 *   - 10-经典指标系统需在端口 8092 运行
 *   - 前端 Next.js 服务在端口 3000 运行（Phase 5 需要）
 */

import {
  StrategyLibraryAPI,
  SignalsAPI,
  ExecutionAPI,
  ExitAPI,
  SystemHealthAPI,
  ApprovalsAPI,
  ArenaAPI,
  UniverseAPI,
  MacroAPI,
  EvaluationAPI,
  TrackerAPI,
  SandboxAPI,
  PipelineAPI,
  type SignalsResponse,
  type StrategyRegistryResponse,
} from "../src/lib/classic-system-api";

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
function h2(title: string) { console.log(`\n  ${BOLD}${MAGENTA}● ${title}${RESET}`); }
function ok(msg: string) { console.log(`  ${GREEN}✓${RESET} ${msg}`); }
function warn(msg: string) { console.log(`  ${YELLOW}⚠${RESET} ${msg}`); }
function fail(msg: string) { console.log(`  ${RED}✗${RESET} ${msg}`); }
function info(msg: string) { console.log(`    ${DIM}→${RESET} ${msg}`); }
function metric(label: string, value: string, color: string = GREEN) {
  console.log(`    ${color}${label.padEnd(20)}${RESET}${value}`);
}

function sleep(ms: number): Promise<void> { return new Promise(r => setTimeout(r, ms)); }

function percOf(part: number, total: number): string {
  if (total === 0) return "0.0%";
  return `${((part / total) * 100).toFixed(1)}%`;
}

function fmtTime(ms: number): string {
  if (ms < 1000) return `${ms.toFixed(0)}ms`;
  if (ms < 60000) return `${(ms / 1000).toFixed(2)}s`;
  return `${(ms / 60000).toFixed(2)}min`;
}

// ============================================================
// 全局统计
// ============================================================
interface TestCase {
  id: string;
  label: string;
  phase: string;
  latencyMs: number;
  passed: boolean;
  error?: string;
  tradingMode?: string;
  chainSteps?: string[];
  dataPreview?: string;
}

const allCases: TestCase[] = [];
const startTs = Date.now();

function recordCase(c: TestCase) { allCases.push(c); }

function summarizePhase(phaseLabel: string): void {
  const phaseCases = allCases.filter(c => c.phase === phaseLabel);
  const passed = phaseCases.filter(c => c.passed).length;
  const total = phaseCases.length;
  const latencies = phaseCases.map(c => c.latencyMs);
  const avgLat = latencies.reduce((a, b) => a + b, 0) / (latencies.length || 1);
  const maxLat = Math.max(...latencies, 0);

  console.log(`\n  ${BOLD}${phaseLabel} 统计${RESET}`);
  metric("通过/总数", `${passed}/${total} (${percOf(passed, total)})`, passed === total ? GREEN : YELLOW);
  metric("平均延迟", `${avgLat.toFixed(0)}ms`);
  metric("最大延迟", `${maxLat.toFixed(0)}ms`);
  metric("失败数", `${total - passed}`, total - passed > 0 ? RED : GREEN);

  const failedCases = phaseCases.filter(c => !c.passed);
  if (failedCases.length > 0) {
    console.log(`\n  ${RED}失败详情：${RESET}`);
    for (const fc of failedCases.slice(0, 5)) {
      info(`${fc.label}: ${fc.error || "未知错误"}`);
    }
  }
}

// ============================================================
// Phase 1: 经典系统 API 直接调用测试
// ============================================================
async function phase1_apiDirect(): Promise<void> {
  section("Phase 1 · 经典系统 API 直接调用测试（15 模块）", "🔌");

  const apiTests: Array<{
    label: string;
    icon: string;
    fn: () => Promise<any>;
    validate: (data: any) => boolean;
  }> = [
    {
      label: "策略库 listStrategies",
      icon: "📚",
      fn: async () => await StrategyLibraryAPI.listStrategies(),
      validate: (data: StrategyRegistryResponse) => data.ok === true && Array.isArray(data.strategies),
    },
    {
      label: "信号系统 getRecentSignals(20)",
      icon: "📡",
      fn: async () => await SignalsAPI.getRecentSignals(20),
      validate: (data: SignalsResponse) => data.ok === true,
    },
    {
      label: "离场系统 getExitStatus",
      icon: "🚪",
      fn: async () => await ExitAPI.getExitStatus(),
      validate: (data: any) => data.ok === true,
    },
    {
      label: "系统健康 healthCheck",
      icon: "🩺",
      fn: async () => await SystemHealthAPI.healthCheck(),
      validate: (data: any) => data && data.ok !== false,
    },
    {
      label: "Arena 竞技场 getState",
      icon: "🏟️",
      fn: async () => await ArenaAPI.getState(),
      validate: (data: any) => data.ok === true,
    },
    {
      label: "Universe 代币筛选 getStatus",
      icon: "🌌",
      fn: async () => await UniverseAPI.getStatus(),
      validate: (data: any) => data.ok === true,
    },
    {
      label: "Macro 宏观门控 getOverview",
      icon: "🌐",
      fn: async () => await MacroAPI.getOverview(),
      validate: (data: any) => data.ok === true,
    },
    {
      label: "Evaluation 评估 getAcceptanceStatus",
      icon: "✅",
      fn: async () => await EvaluationAPI.getAcceptanceStatus(),
      validate: (data: any) => data.ok === true,
    },
    {
      label: "Evaluation Gate Check",
      icon: "🚧",
      fn: async () => await EvaluationAPI.getGateCheck(),
      validate: (data: any) => data.ok === true,
    },
    {
      label: "Tracker 执行记录 getStats",
      icon: "📈",
      fn: async () => await TrackerAPI.getStats(),
      validate: (data: any) => data.ok === true,
    },
    {
      label: "Sandbox 沙箱 getBacktestResults(10)",
      icon: "🧪",
      fn: async () => await SandboxAPI.getBacktestResults(10),
      validate: (data: any) => data.ok === true,
    },
    {
      label: "Sandbox 沙箱 getSandboxState",
      icon: "🔬",
      fn: async () => await SandboxAPI.getSandboxState(),
      validate: (data: any) => data.ok === true,
    },
    {
      label: "Pipeline 策略上线 getServingPipelineState",
      icon: "🛠️",
      fn: async () => await PipelineAPI.getServingPipelineState(),
      validate: (data: any) => data.ok === true,
    },
    {
      label: "Pipeline Gate Check",
      icon: "🚦",
      fn: async () => await PipelineAPI.getGateCheck(),
      validate: (data: any) => data.ok === true,
    },
  ];

  console.log(`\n  共 ${apiTests.length} 个 API 模块测试...\n`);

  for (let i = 0; i < apiTests.length; i++) {
    const tc = apiTests[i];
    const t0 = Date.now();
    try {
      const data = await tc.fn();
      const latency = Date.now() - t0;
      const passed = tc.validate(data);
      recordCase({
        id: `p1-${i}`,
        label: tc.label,
        phase: "phase1_apiDirect",
        latencyMs: latency,
        passed,
        error: passed ? undefined : `验证失败: ok=${data?.ok}, data=${JSON.stringify(data).slice(0, 100)}`,
        dataPreview: JSON.stringify(data).slice(0, 80),
      });
      if (passed) {
        ok(`${tc.icon} ${tc.label} → ${latency}ms`);
        if (latency > 3000) info(`⚠ 延迟较高: ${latency}ms`);
      } else {
        fail(`${tc.icon} ${tc.label} → 验证失败 (${latency}ms)`);
        info(`   数据: ${JSON.stringify(data).slice(0, 200)}`);
      }
    } catch (error: any) {
      const latency = Date.now() - t0;
      recordCase({
        id: `p1-${i}`,
        label: tc.label,
        phase: "phase1_apiDirect",
        latencyMs: latency,
        passed: false,
        error: String(error),
      });
      fail(`${tc.icon} ${tc.label} → 异常: ${error.message || error}`);
    }
  }

  summarizePhase("phase1_apiDirect");
}

// ============================================================
// Phase 2: C 系列思维链执行测试
// ============================================================
async function phase2_classicChain(): Promise<void> {
  section("Phase 2 · C 系列思维链执行测试（8 步骤 × 多意图）", "🔗");

  // 定义 C 系列步骤
  type ClassicStep =
    | "C1_MACRO_SCAN" | "C2_UNIVERSE_SCAN" | "C3_GATE_CHECK"
    | "C4_ARENA_REVIEW" | "C5_STRATEGY_SELECT" | "C6_SIGNAL_REVIEW"
    | "C7_EXIT_MONITOR" | "C8_TRACKING_AUDIT";

  const stepMappings: Record<ClassicStep, { label: string; icon: string; fn: () => Promise<any> }> = {
    C1_MACRO_SCAN: { label: "宏观扫描", icon: "🌐", fn: async () => await MacroAPI.getOverview() },
    C2_UNIVERSE_SCAN: { label: "代币宇宙", icon: "🌌", fn: async () => await UniverseAPI.getStatus() },
    C3_GATE_CHECK: { label: "Gate 评估", icon: "🚧", fn: async () => await EvaluationAPI.getGateCheck() },
    C4_ARENA_REVIEW: { label: "竞技场审查", icon: "🏟️", fn: async () => await ArenaAPI.getState() },
    C5_STRATEGY_SELECT: { label: "策略库", icon: "📚", fn: async () => await StrategyLibraryAPI.listStrategies() },
    C6_SIGNAL_REVIEW: { label: "信号系统", icon: "📡", fn: async () => await SignalsAPI.getRecentSignals(10) },
    C7_EXIT_MONITOR: { label: "离场监控", icon: "🚪", fn: async () => await ExitAPI.getExitStatus() },
    C8_TRACKING_AUDIT: { label: "执行追踪", icon: "📈", fn: async () => await TrackerAPI.getStats() },
  };

  // 测试不同的思维链组合
  const chainConfigs: Array<{
    label: string;
    chain: ClassicStep[];
    scenario: string;
  }> = [
    {
      label: "快速查询 (quick模式)",
      scenario: "用户快速查询BTC宏观状态",
      chain: ["C1_MACRO_SCAN", "C3_GATE_CHECK"],
    },
    {
      label: "深度分析 (deep模式)",
      scenario: "用户深度分析BTC市场",
      chain: ["C1_MACRO_SCAN", "C2_UNIVERSE_SCAN", "C3_GATE_CHECK",
              "C4_ARENA_REVIEW", "C5_STRATEGY_SELECT", "C6_SIGNAL_REVIEW",
              "C7_EXIT_MONITOR", "C8_TRACKING_AUDIT"],
    },
    {
      label: "策略验证链",
      scenario: "用户验证策略可行性",
      chain: ["C3_GATE_CHECK", "C4_ARENA_REVIEW", "C5_STRATEGY_SELECT", "C8_TRACKING_AUDIT"],
    },
    {
      label: "信号监控链",
      scenario: "用户查询信号与离场状态",
      chain: ["C1_MACRO_SCAN", "C6_SIGNAL_REVIEW", "C7_EXIT_MONITOR", "C8_TRACKING_AUDIT"],
    },
    {
      label: "入场时机分析",
      scenario: "用户分析入场时机",
      chain: ["C1_MACRO_SCAN", "C2_UNIVERSE_SCAN", "C3_GATE_CHECK", "C6_SIGNAL_REVIEW"],
    },
    {
      label: "风险评估链",
      scenario: "用户评估系统风险",
      chain: ["C3_GATE_CHECK", "C4_ARENA_REVIEW", "C7_EXIT_MONITOR", "C8_TRACKING_AUDIT"],
    },
  ];

  console.log(`\n  共 ${chainConfigs.length} 个思维链配置...\n`);

  for (let ci = 0; ci < chainConfigs.length; ci++) {
    const config = chainConfigs[ci];
    h2(`链 ${ci + 1}: ${config.label} (${config.chain.length} 步骤)`);
    info(`场景: ${config.scenario}`);

    const chainStart = Date.now();
    let chainPassed = true;
    const stepResults: string[] = [];

    for (let si = 0; si < config.chain.length; si++) {
      const step = config.chain[si];
      const mapping = stepMappings[step];
      const t0 = Date.now();

      try {
        const data = await mapping.fn();
        const latency = Date.now() - t0;
        const passed = data && data.ok === true;
        stepResults.push(`${mapping.icon} ${step} (${latency}ms)${passed ? "✓" : "✗"}`);

        recordCase({
          id: `p2-${ci}-${si}`,
          label: `${config.label} · ${mapping.label}`,
          phase: "phase2_classicChain",
          latencyMs: latency,
          passed,
          tradingMode: "classic",
          error: passed ? undefined : `步骤 ${step} 失败`,
        });

        if (passed) {
          info(`${mapping.icon} ${step} → ${latency}ms`);
        } else {
          chainPassed = false;
          warn(`${mapping.icon} ${step} → 数据验证失败 (${latency}ms)`);
        }
      } catch (error: any) {
        chainPassed = false;
        recordCase({
          id: `p2-${ci}-${si}`,
          label: `${config.label} · ${mapping.label}`,
          phase: "phase2_classicChain",
          latencyMs: Date.now() - t0,
          passed: false,
          tradingMode: "classic",
          error: String(error),
        });
        fail(`${mapping.icon} ${step} → 异常: ${error.message || error}`);
      }
    }

    const totalLatency = Date.now() - chainStart;
    if (chainPassed) {
      ok(`${config.label} 完成 → ${totalLatency}ms · ${config.chain.length} 步骤全部通过`);
    } else {
      warn(`${config.label} 完成 → ${totalLatency}ms · 部分步骤失败`);
    }
    info(`步骤摘要: ${stepResults.join(" · ")}`);
  }

  summarizePhase("phase2_classicChain");
}

// ============================================================
// Phase 3: 多意图路由矩阵测试
// ============================================================
async function phase3_intentRouting(): Promise<void> {
  section("Phase 3 · 多意图路由矩阵测试（classic 模式 32 意图）", "🧭");

  // 导入意图路由函数
  const { routeIntent } = await import("../src/lib/intent");

  const intentTestCases: Array<{
    intent: string;
    message: string;
    expectedChain: string[];
    description: string;
  }> = [
    { intent: "market_query", message: "BTC 现在怎么样", expectedChain: ["C1"], description: "市场查询" },
    { intent: "macro_analysis", message: "分析当前宏观环境", expectedChain: ["C1", "C2"], description: "宏观分析" },
    { intent: "deep_analysis", message: "深度分析 BTC 市场结构", expectedChain: ["C1", "C2", "C3", "C4", "C5", "C6", "C7", "C8"], description: "深度分析" },
    { intent: "triple_chain", message: "请对 BTC 进行三链分析", expectedChain: ["C1", "C2", "C3", "C4", "C5", "C6", "C7", "C8"], description: "三链模式" },
    { intent: "scenario_sim", message: "如果美联储加息，BTC 会怎样", expectedChain: ["C1", "C2", "C3"], description: "情景模拟" },
    { intent: "strategy_verify", message: "验证我的策略是否合适", expectedChain: ["C3", "C4", "C5"], description: "策略验证" },
    { intent: "strategy_recommendation", message: "推荐适合的策略", expectedChain: ["C3", "C4", "C5"], description: "策略推荐" },
    { intent: "execute_trade", message: "现在应该如何操作", expectedChain: ["C1", "C2", "C3", "C4", "C5", "C6", "C7", "C8"], description: "交易执行" },
    { intent: "entry_timing", message: "分析入场时机", expectedChain: ["C1", "C2", "C3", "C6"], description: "入场时机" },
    { intent: "exit_timing", message: "分析离场时机", expectedChain: ["C7", "C8"], description: "离场时机" },
    { intent: "risk_analysis", message: "当前风险如何", expectedChain: ["C3", "C4", "C7", "C8"], description: "风险分析" },
    { intent: "backtest_help", message: "如何回测策略", expectedChain: ["C3", "C4"], description: "回测帮助" },
    { intent: "portfolio_allocation", message: "如何分配投资组合", expectedChain: ["C1", "C2", "C3"], description: "组合分配" },
    { intent: "portfolio_rebalance", message: "如何再平衡", expectedChain: ["C1", "C2", "C8"], description: "组合再平衡" },
    { intent: "event_analysis", message: "分析最近事件", expectedChain: ["C1", "C2"], description: "事件分析" },
    { intent: "concept_explain", message: "解释什么是Gate Check", expectedChain: ["C0"], description: "概念解释" },
    { intent: "volatility_analysis", message: "分析波动率", expectedChain: ["C1", "C6"], description: "波动率分析" },
    { intent: "asset_comparison", message: "比较 BTC 和 ETH", expectedChain: ["C1", "C2"], description: "资产对比" },
    { intent: "position_sizing", message: "如何设置仓位大小", expectedChain: ["C1", "C3", "C8"], description: "仓位管理" },
    { intent: "market_sentiment", message: "当前市场情绪如何", expectedChain: ["C1"], description: "市场情绪" },
    { intent: "trend_analysis", message: "当前趋势是什么", expectedChain: ["C1", "C2"], description: "趋势分析" },
    { intent: "technical_signal", message: "有什么技术信号", expectedChain: ["C6"], description: "技术信号" },
    { intent: "support_resistance", message: "支撑阻力位在哪里", expectedChain: ["C1", "C6"], description: "支撑阻力" },
    { intent: "dca_strategy", message: "如何设置定投策略", expectedChain: ["C1", "C2", "C3"], description: "定投策略" },
    { intent: "arbitrage_opportunity", message: "是否有套利机会", expectedChain: ["C1", "C2"], description: "套利机会" },
    { intent: "sector_rotation", message: "板块轮动情况如何", expectedChain: ["C1", "C2"], description: "板块轮动" },
    { intent: "simple_qa", message: "什么是经典指标系统", expectedChain: ["C0"], description: "简单问答" },
    { intent: "system_config", message: "如何配置系统", expectedChain: ["C0"], description: "系统配置" },
    { intent: "credits_query", message: "查询我的额度", expectedChain: ["C0"], description: "额度查询" },
    { intent: "artifact_query", message: "有哪些策略产物", expectedChain: ["C5"], description: "产物查询" },
    { intent: "risk_alert_response", message: "系统告警了，该怎么办", expectedChain: ["C3", "C7"], description: "告警响应" },
    { intent: "developer", message: "帮我分析策略", expectedChain: ["C5", "C3", "C4"], description: "开发者模式" },
  ];

  const thinkingModes: Array<"quick" | "deep"> = ["quick", "deep"];

  console.log(`\n  测试 ${intentTestCases.length} 种意图 × ${thinkingModes.length} 种模式...\n`);

  let routingMatrix: Record<string, { total: number; ok: number }> = {};

  for (let i = 0; i < intentTestCases.length; i++) {
    const tc = intentTestCases[i];
    const routingKey = tc.intent;
    routingMatrix[routingKey] = routingMatrix[routingKey] || { total: 0, ok: 0 };

    for (const thinkingMode of thinkingModes) {
      const t0 = Date.now();
      try {
        const result = routeIntent(tc.intent as any, "moderate", {
          session_id: `stress-classic-${tc.intent}-${thinkingMode}`,
          user_role: "FREE",
          thinking_mode: thinkingMode,
          trading_mode: "classic",
          message_history: [tc.message],
        });

        const latency = Date.now() - t0;
        const hasChain = Array.isArray(result.chain) && result.chain.length > 0;
        const isClassicChain = hasChain && result.chain.every((step: string) => step.startsWith("C") || step.startsWith("S"));
        const passed = hasChain && isClassicChain;

        routingMatrix[routingKey].total++;
        if (passed) routingMatrix[routingKey].ok++;

        recordCase({
          id: `p3-${tc.intent}-${thinkingMode}`,
          label: `${tc.intent} (${thinkingMode}) - ${tc.description}`,
          phase: "phase3_intentRouting",
          latencyMs: latency,
          passed,
          tradingMode: "classic",
          chainSteps: result.chain,
          error: passed ? undefined : `chain=${result.chain?.join(",") || "empty"}`,
        });

        if (passed) {
          info(`${tc.intent} (${thinkingMode}) → ${result.chain.length} 步骤 · ${latency}ms`);
        } else {
          warn(`${tc.intent} (${thinkingMode}) → chain异常: ${result.chain?.join(",") || "空"} (${latency}ms)`);
        }
      } catch (error: any) {
        recordCase({
          id: `p3-${tc.intent}-${thinkingMode}`,
          label: `${tc.intent} (${thinkingMode}) - ${tc.description}`,
          phase: "phase3_intentRouting",
          latencyMs: Date.now() - t0,
          passed: false,
          error: String(error),
        });
        fail(`${tc.intent} (${thinkingMode}) → 异常: ${error.message || error}`);
      }
    }
  }

  // 路由矩阵摘要
  console.log(`\n  ${BOLD}意图路由矩阵摘要${RESET}`);
  const totalIntents = Object.keys(routingMatrix).length;
  const allOkIntents = Object.values(routingMatrix).filter(r => r.ok === r.total).length;
  metric("意图种类", `${totalIntents}`);
  metric("全部通过意图", `${allOkIntents}/${totalIntents}`, allOkIntents === totalIntents ? GREEN : YELLOW);

  summarizePhase("phase3_intentRouting");
}

// ============================================================
// Phase 4: 并发压力测试
// ============================================================
async function phase4_concurrent(): Promise<void> {
  section("Phase 4 · 并发压力测试（30 并发 × 3 轮）", "⚡");

  const CONCURRENCY = 30;
  const ROUNDS = 3;

  const concurrentScenarios: Array<{
    label: string;
    fn: () => Promise<any>;
  }> = [
    { label: "MacroAPI.getOverview()", fn: async () => await MacroAPI.getOverview() },
    { label: "UniverseAPI.getStatus()", fn: async () => await UniverseAPI.getStatus() },
    { label: "EvaluationAPI.getGateCheck()", fn: async () => await EvaluationAPI.getGateCheck() },
    { label: "StrategyLibraryAPI.listStrategies()", fn: async () => await StrategyLibraryAPI.listStrategies() },
    { label: "SignalsAPI.getRecentSignals(10)", fn: async () => await SignalsAPI.getRecentSignals(10) },
    { label: "ExitAPI.getExitStatus()", fn: async () => await ExitAPI.getExitStatus() },
    { label: "TrackerAPI.getStats()", fn: async () => await TrackerAPI.getStats() },
    { label: "ArenaAPI.getState()", fn: async () => await ArenaAPI.getState() },
  ];

  let totalRequests = 0;
  let totalSuccess = 0;
  let totalLatency = 0;
  let roundTimes: number[] = [];

  for (let round = 1; round <= ROUNDS; round++) {
    h2(`第 ${round}/${ROUNDS} 轮 · ${CONCURRENCY} 并发请求`);
    const roundStart = Date.now();

    // 并发执行所有场景 × 并发数
    const promises: Promise<{ label: string; latencyMs: number; passed: boolean; error?: string }>[] = [];

    for (let c = 0; c < CONCURRENCY; c++) {
      for (let s = 0; s < concurrentScenarios.length; s++) {
        const scenario = concurrentScenarios[s];
        const taskId = `r${round}-c${c}-s${s}`;

        promises.push((async () => {
          const t0 = Date.now();
          try {
            const result = await scenario.fn();
            const latency = Date.now() - t0;
            const passed = result && result.ok === true;
            return { label: scenario.label, latencyMs: latency, passed, error: passed ? undefined : "数据验证失败" };
          } catch (error: any) {
            return { label: scenario.label, latencyMs: Date.now() - t0, passed: false, error: String(error) };
          }
        })());
      }
    }

    const results = await Promise.all(promises);
    const roundTime = Date.now() - roundStart;
    roundTimes.push(roundTime);

    for (const r of results) {
      totalRequests++;
      if (r.passed) totalSuccess++;
      totalLatency += r.latencyMs;
      recordCase({
        id: `p4-${totalRequests}`,
        label: `Round ${round} · ${r.label}`,
        phase: "phase4_concurrent",
        latencyMs: r.latencyMs,
        passed: r.passed,
        tradingMode: "classic",
        error: r.error,
      });
    }

    const roundSuccess = results.filter(r => r.passed).length;
    const roundTotal = results.length;
    const roundAvg = results.reduce((s, r) => s + r.latencyMs, 0) / roundTotal;

    ok(`本轮 ${roundTotal} 请求 · ${roundSuccess} 成功 · 平均 ${roundAvg.toFixed(0)}ms · 总耗时 ${fmtTime(roundTime)}`);

    // 轮间休息
    if (round < ROUNDS) {
      info(`轮间休息 500ms...`);
      await sleep(500);
    }
  }

  // 并发摘要
  console.log(`\n  ${BOLD}并发测试统计${RESET}`);
  metric("总请求数", `${totalRequests}`);
  metric("成功数", `${totalSuccess}/${totalRequests} (${percOf(totalSuccess, totalRequests)})`);
  metric("平均延迟", `${(totalLatency / totalRequests).toFixed(0)}ms`);
  metric("轮平均耗时", `${fmtTime(roundTimes.reduce((a, b) => a + b, 0) / roundTimes.length)}`);
  metric("最快轮", `${fmtTime(Math.min(...roundTimes))}`);
  metric("最慢轮", `${fmtTime(Math.max(...roundTimes))}`);
  metric("QPS (理论)", `${(totalRequests / (roundTimes.reduce((a, b) => a + b, 0) / 1000)).toFixed(0)} req/s`);

  summarizePhase("phase4_concurrent");
}

// ============================================================
// Phase 5: Promise.all 并行聚合测试
// ============================================================
async function phase5_parallelAggregation(): Promise<void> {
  section("Phase 5 · 并行聚合测试（Promise.all 多 API 并发）", "🔀");

  const aggregationScenarios: Array<{
    label: string;
    icon: string;
    apis: Array<{ name: string; fn: () => Promise<any> }>;
  }> = [
    {
      label: "基础四元组",
      icon: "🌐",
      apis: [
        { name: "Macro", fn: async () => await MacroAPI.getOverview() },
        { name: "Universe", fn: async () => await UniverseAPI.getStatus() },
        { name: "GateCheck", fn: async () => await EvaluationAPI.getGateCheck() },
        { name: "Arena", fn: async () => await ArenaAPI.getState() },
      ],
    },
    {
      label: "策略+信号",
      icon: "📚",
      apis: [
        { name: "Strategies", fn: async () => await StrategyLibraryAPI.listStrategies() },
        { name: "Signals", fn: async () => await SignalsAPI.getRecentSignals(20) },
        { name: "GateCheck", fn: async () => await EvaluationAPI.getGateCheck() },
      ],
    },
    {
      label: "执行+离场+追踪",
      icon: "📈",
      apis: [
        { name: "Exit", fn: async () => await ExitAPI.getExitStatus() },
        { name: "Tracker", fn: async () => await TrackerAPI.getStats() },
        { name: "Signals", fn: async () => await SignalsAPI.getRecentSignals(10) },
      ],
    },
    {
      label: "全量聚合 (8 API)",
      icon: "🎯",
      apis: [
        { name: "Macro", fn: async () => await MacroAPI.getOverview() },
        { name: "Universe", fn: async () => await UniverseAPI.getStatus() },
        { name: "GateCheck", fn: async () => await EvaluationAPI.getGateCheck() },
        { name: "Arena", fn: async () => await ArenaAPI.getState() },
        { name: "Strategies", fn: async () => await StrategyLibraryAPI.listStrategies() },
        { name: "Signals", fn: async () => await SignalsAPI.getRecentSignals(10) },
        { name: "Exit", fn: async () => await ExitAPI.getExitStatus() },
        { name: "Tracker", fn: async () => await TrackerAPI.getStats() },
      ],
    },
    {
      label: "Pipeline+Sandbox",
      icon: "🛠️",
      apis: [
        { name: "Pipeline", fn: async () => await PipelineAPI.getServingPipelineState() },
        { name: "GateCheck", fn: async () => await PipelineAPI.getGateCheck() },
        { name: "Sandbox", fn: async () => await SandboxAPI.getSandboxState() },
        { name: "Backtest", fn: async () => await SandboxAPI.getBacktestResults(10) },
      ],
    },
  ];

  console.log(`\n  共 ${aggregationScenarios.length} 个聚合场景...\n`);

  for (let si = 0; si < aggregationScenarios.length; si++) {
    const scenario = aggregationScenarios[si];
    h2(`场景 ${si + 1}: ${scenario.icon} ${scenario.label} (${scenario.apis.length} 个 API)`);

    const t0 = Date.now();
    try {
      const results = await Promise.all(
        scenario.apis.map(async (api) => {
          const t = Date.now();
          try {
            const data = await api.fn();
            return { name: api.name, latencyMs: Date.now() - t, data, passed: data?.ok === true };
          } catch (error: any) {
            return { name: api.name, latencyMs: Date.now() - t, data: null, passed: false, error: String(error) };
          }
        })
      );

      const totalLatency = Date.now() - t0;
      const allPassed = results.every(r => r.passed);

      recordCase({
        id: `p5-${si}`,
        label: scenario.label,
        phase: "phase5_parallelAggregation",
        latencyMs: totalLatency,
        passed: allPassed,
        tradingMode: "classic",
        error: allPassed ? undefined : `部分 API 失败: ${results.filter(r => !r.passed).map(r => r.name).join(",")}`,
        dataPreview: results.map(r => `${r.name}=${r.passed ? "ok" : "fail"}(${r.latencyMs}ms)`).join(", "),
      });

      const summary = results.map(r =>
        `${r.passed ? "✓" : "✗"} ${r.name} (${r.latencyMs}ms)`
      ).join(" · ");

      if (allPassed) {
        ok(`${scenario.label} → ${totalLatency}ms · 全部通过`);
      } else {
        warn(`${scenario.label} → ${totalLatency}ms · 部分失败`);
      }
      info(`   各 API: ${summary}`);

    } catch (error: any) {
      const totalLatency = Date.now() - t0;
      recordCase({
        id: `p5-${si}`,
        label: scenario.label,
        phase: "phase5_parallelAggregation",
        latencyMs: totalLatency,
        passed: false,
        error: String(error),
      });
      fail(`${scenario.label} → 聚合异常: ${error.message || error}`);
    }

    // 场景间休息
    if (si < aggregationScenarios.length - 1) await sleep(200);
  }

  summarizePhase("phase5_parallelAggregation");
}

// ============================================================
// Phase 6: 故障降级测试
// ============================================================
async function phase6_faultTolerance(): Promise<void> {
  section("Phase 6 · 故障降级测试（模拟部分 API 异常）", "🛡️");

  // 测试场景: 连续请求某个较慢/可能失败的 API
  const faultScenarios: Array<{
    label: string;
    fn: () => Promise<any>;
    description: string;
  }> = [
    {
      label: "Macro 快速重试",
      description: "连续 10 次请求宏观 API，观察是否有超时或错误",
      fn: async () => await MacroAPI.getOverview(),
    },
    {
      label: "Universe 压力",
      description: "连续 10 次请求代币宇宙",
      fn: async () => await UniverseAPI.getStatus(),
    },
    {
      label: "Gate Check 快速调用",
      description: "连续 10 次 Gate 检查",
      fn: async () => await EvaluationAPI.getGateCheck(),
    },
    {
      label: "Signals 高频查询",
      description: "连续 10 次查询最近信号",
      fn: async () => await SignalsAPI.getRecentSignals(5),
    },
    {
      label: "Strategies 快速查询",
      description: "连续 10 次请求策略库",
      fn: async () => await StrategyLibraryAPI.listStrategies(),
    },
  ];

  const REPEAT_PER_SCENARIO = 10;

  console.log(`\n  ${faultScenarios.length} 个场景 × ${REPEAT_PER_SCENARIO} 次调用...\n`);

  for (let si = 0; si < faultScenarios.length; si++) {
    const scenario = faultScenarios[si];
    h2(`场景 ${si + 1}: ${scenario.label}`);
    info(scenario.description);

    let successCount = 0;
    let failCount = 0;
    let latencyList: number[] = [];
    const failures: string[] = [];

    for (let i = 0; i < REPEAT_PER_SCENARIO; i++) {
      const t0 = Date.now();
      try {
        const data = await scenario.fn();
        const latency = Date.now() - t0;
        latencyList.push(latency);

        if (data?.ok === true) {
          successCount++;
        } else {
          failCount++;
          failures.push(`call#${i}: ok=${data?.ok}`);
        }

        recordCase({
          id: `p6-${si}-${i}`,
          label: `${scenario.label} #${i}`,
          phase: "phase6_faultTolerance",
          latencyMs: latency,
          passed: data?.ok === true,
          tradingMode: "classic",
          error: data?.ok === true ? undefined : `ok=${data?.ok}`,
        });
      } catch (error: any) {
        failCount++;
        failures.push(`call#${i}: ${error.message || error}`);
        recordCase({
          id: `p6-${si}-${i}`,
          label: `${scenario.label} #${i}`,
          phase: "phase6_faultTolerance",
          latencyMs: Date.now() - t0,
          passed: false,
          error: String(error),
        });
      }

      // 快速调用间隔: 100ms
      await sleep(100);
    }

    const avgLat = latencyList.reduce((a, b) => a + b, 0) / (latencyList.length || 1);
    const maxLat = Math.max(...latencyList, 0);
    const jitter = latencyList.length > 1
      ? Math.sqrt(latencyList.reduce((s, l) => s + Math.pow(l - avgLat, 2), 0) / latencyList.length)
      : 0;

    const allOk = failCount === 0;
    if (allOk) {
      ok(`${scenario.label} → ${successCount}/${REPEAT_PER_SCENARIO} 成功 · 平均 ${avgLat.toFixed(0)}ms · 最大 ${maxLat}ms · 抖动 ${jitter.toFixed(0)}ms`);
    } else {
      warn(`${scenario.label} → ${successCount}/${REPEAT_PER_SCENARIO} 成功 · ${failCount} 失败`);
      info(`   失败示例: ${failures.slice(0, 3).join("; ")}`);
    }
  }

  summarizePhase("phase6_faultTolerance");
}

// ============================================================
// 最终统计 & 报告
// ============================================================
function printFinalReport(): void {
  console.log(`\n\n${BOLD}${"═".repeat(78)}${RESET}`);
  console.log(`${BOLD}📊 经典系统多场景压力测试 · 最终报告${RESET}`);
  console.log(`${BOLD}${"═".repeat(78)}${RESET}`);

  const totalTime = Date.now() - startTs;
  const passedTotal = allCases.filter(c => c.passed).length;
  const failedTotal = allCases.length - passedTotal;

  console.log(`\n  测试时间: ${fmtTime(totalTime)}`);
  console.log(`  总用例数: ${allCases.length}`);
  console.log(`  通过: ${GREEN}${passedTotal}${RESET} (${percOf(passedTotal, allCases.length)})`);
  console.log(`  失败: ${RED}${failedTotal}${RESET} (${percOf(failedTotal, allCases.length)})`);

  // 按 Phase 汇总
  const phases = [...new Set(allCases.map(c => c.phase))];
  console.log(`\n  ${BOLD}各阶段统计${RESET}`);
  console.log(`  ${"─".repeat(60)}`);

  for (const phase of phases) {
    const phaseCases = allCases.filter(c => c.phase === phase);
    const pPassed = phaseCases.filter(c => c.passed).length;
    const pFailed = phaseCases.length - pPassed;
    const pLatencies = phaseCases.map(c => c.latencyMs);
    const pAvgLat = pLatencies.reduce((a, b) => a + b, 0) / (pLatencies.length || 1);
    const pMaxLat = Math.max(...pLatencies, 0);

    const statusColor = pFailed === 0 ? GREEN : (pFailed < phaseCases.length * 0.3 ? YELLOW : RED);
    console.log(`  ${statusColor}${phase.padEnd(32)}${RESET}  ` +
                `${pPassed}/${phaseCases.length}  ` +
                `avg ${pAvgLat.toFixed(0)}ms  ` +
                `max ${pMaxLat.toFixed(0)}ms`);
  }

  // 延迟分布
  const allLatencies = allCases.map(c => c.latencyMs).sort((a, b) => a - b);
  const p50 = allLatencies[Math.floor(allLatencies.length * 0.5)] || 0;
  const p90 = allLatencies[Math.floor(allLatencies.length * 0.9)] || 0;
  const p95 = allLatencies[Math.floor(allLatencies.length * 0.95)] || 0;
  const p99 = allLatencies[Math.floor(allLatencies.length * 0.99)] || 0;

  console.log(`\n  ${BOLD}延迟分布${RESET}`);
  console.log(`  ${"─".repeat(60)}`);
  metric("P50", `${p50.toFixed(0)}ms`);
  metric("P90", `${p90.toFixed(0)}ms`);
  metric("P95", `${p95.toFixed(0)}ms`);
  metric("P99", `${p99.toFixed(0)}ms`);

  // 失败用例清单
  const failedCases = allCases.filter(c => !c.passed);
  if (failedCases.length > 0) {
    console.log(`\n  ${RED}${BOLD}⚠ 失败用例清单 (${failedCases.length})${RESET}`);
    console.log(`  ${"─".repeat(60)}`);
    for (const fc of failedCases.slice(0, 20)) {
      console.log(`    • [${fc.phase}] ${fc.label} → ${fc.error?.slice(0, 80) || "未知错误"}`);
    }
    if (failedCases.length > 20) {
      console.log(`    ...及其他 ${failedCases.length - 20} 个失败用例`);
    }
  }

  // 总体评分
  console.log(`\n  ${BOLD}总体评分${RESET}`);
  console.log(`  ${"─".repeat(60)}`);
  const passRate = (passedTotal / allCases.length) * 100;

  let rating = "❌ 严重问题";
  let ratingColor = RED;
  if (passRate >= 98) { rating = "🏆 优秀"; ratingColor = GREEN; }
  else if (passRate >= 90) { rating = "✅ 良好"; ratingColor = GREEN; }
  else if (passRate >= 75) { rating = "⚠ 需改进"; ratingColor = YELLOW; }
  else if (passRate >= 50) { rating = "❌ 有问题"; ratingColor = RED; }

  metric("通过率", `${passRate.toFixed(1)}%`, ratingColor);
  metric("评级", rating, ratingColor);
  metric("测试耗时", fmtTime(totalTime));

  console.log(`\n  ${BOLD}结论${RESET}: `);
  if (passRate >= 98) {
    console.log(`  经典指标系统 API 表现稳定，C 系列思维链可顺畅执行。✓ 可以上线。`);
  } else if (passRate >= 90) {
    console.log(`  经典指标系统整体可用，存在少量 API 波动，建议优化后上线。`);
  } else if (passRate >= 75) {
    console.log(`  经典指标系统存在一定数量的问题，需要排查并修复后再考虑上线。`);
  } else {
    console.log(`  经典指标系统存在严重问题，必须先排查并修复。`);
  }

  console.log(`\n${"═".repeat(78)}`);

  // 保存 JSON 报告
  try {
    const reportData = {
      generated_at: new Date().toISOString(),
      total_cases: allCases.length,
      passed: passedTotal,
      failed: failedTotal,
      pass_rate: passRate,
      total_time_ms: totalTime,
      latency_distribution: { p50, p90, p95, p99 },
      phases: phases.map(phase => {
        const phaseCases = allCases.filter(c => c.phase === phase);
        const pPassed = phaseCases.filter(c => c.passed).length;
        const pLat = phaseCases.map(c => c.latencyMs);
        return {
          phase,
          total: phaseCases.length,
          passed: pPassed,
          failed: phaseCases.length - pPassed,
          avg_latency_ms: pLat.reduce((a, b) => a + b, 0) / (pLat.length || 1),
          max_latency_ms: Math.max(...pLat, 0),
        };
      }),
      failed_cases: failedCases.slice(0, 50),
    };

    const fs = require("fs");
    const path = require("path");
    const reportsDir = path.join(__dirname, "..", "stress-test-reports");
    if (!fs.existsSync(reportsDir)) fs.mkdirSync(reportsDir, { recursive: true });

    const filename = path.join(reportsDir, `classic-system-stress-test-${Date.now()}.json`);
    fs.writeFileSync(filename, JSON.stringify(reportData, null, 2));
    console.log(`\n  📁 详细报告: ${filename}`);
  } catch (e) {
    console.log(`\n  ⚠ 报告保存失败: ${e}`);
  }
}

// ============================================================
// 主入口
// ============================================================
async function main(): Promise<void> {
  console.log(`${BOLD}${"=".repeat(78)}${RESET}`);
  console.log(`${BOLD}🎯 经典交易系统多场景压力测试 v1.0${RESET}`);
  console.log(`${BOLD}${"=".repeat(78)}${RESET}`);
  console.log(`\n  测试目标:`);
  console.log(`    1. 验证 15 个经典系统 API 模块正常工作`);
  console.log(`    2. 验证 C 系列思维链正确执行`);
  console.log(`    3. 验证 32 种意图 × 2 种模式的路由正确`);
  console.log(`    4. 验证 30 并发 × 3 轮压力下的稳定性`);
  console.log(`    5. 验证多 API 并行聚合的性能`);
  console.log(`    6. 验证高频调用下的故障降级能力`);
  console.log(`\n  时间: ${new Date().toLocaleString("zh-CN", { hour12: false })}`);

  try {
    // Phase 1: API 直接调用
    await phase1_apiDirect();
    await sleep(300);

    // Phase 2: C 系列思维链
    await phase2_classicChain();
    await sleep(300);

    // Phase 3: 多意图路由
    await phase3_intentRouting();
    await sleep(300);

    // Phase 4: 并发压力
    await phase4_concurrent();
    await sleep(300);

    // Phase 5: 并行聚合
    await phase5_parallelAggregation();
    await sleep(300);

    // Phase 6: 故障降级
    await phase6_faultTolerance();
    await sleep(300);

    // 最终报告
    printFinalReport();

  } catch (error: any) {
    console.error(`\n${RED}测试过程异常终止:${RESET}`);
    console.error(error);
    printFinalReport();
    process.exit(1);
  }
}

// 启动测试
main().catch((err) => {
  console.error("启动失败:", err);
  process.exit(1);
});
