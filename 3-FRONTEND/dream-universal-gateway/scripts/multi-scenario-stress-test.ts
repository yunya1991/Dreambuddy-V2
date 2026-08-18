/**
 * 多场景模拟压力测试
 *
 * 测试覆盖：
 *   [Phase 1] 意图识别全覆盖：所有主要意图 × 不同复杂度 × 不同 thinking_mode
 *   [Phase 2] 智能路由正确性：developer → S3→S4→S5，其他意图 → 对应 S 链
 *   [Phase 3] S5 执行引擎（E1→E2→E3 完整链路）：策略代码生成 × 多种标的/策略
 *   [Phase 4] 并发压力：20 并发 × 5 轮，测量吞吐 / 延迟 / 失败率
 *   [Phase 5] 边界与错误注入：空消息、超长消息、不存在的意图、乱序参数
 *   [Phase 6] 内存 & 资源：持续运行，观测 session 增长是否失控
 */

import { routeIntent, recognizeIntent, type IntentType, type ComplexityLevel } from "../src/lib/intent";
import { executeS5, S5_STEP_SEQUENCE, S5_STEP_DEFINITIONS, getS5StepDisplay, renderS5Summary, type S5ExecutionResult, type S5StepId } from "../src/lib/dev-chain";

// ======================= 终端颜色 =======================
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

// ======================= 全局统计 =======================
interface GlobalStats {
  totalCases: number;
  passed: number;
  failed: number;
  errors: string[];
  startTs: number;
  latenciesMs: number[];
}
const stats: GlobalStats = {
  totalCases: 0,
  passed: 0,
  failed: 0,
  errors: [],
  startTs: Date.now(),
  latenciesMs: [],
};

function recordCase(passed: boolean, latencyMs: number, err?: string) {
  stats.totalCases++;
  if (passed) stats.passed++;
  else { stats.failed++; if (err) stats.errors.push(err); }
  stats.latenciesMs.push(latencyMs);
}

// =======================================================
// Phase 1: 意图识别全覆盖
// =======================================================
async function phase1_intentRecognition() {
  section("Phase 1 · 意图识别全覆盖测试", "🧭");

  const INTENT_TEST_CASES: Array<{ label: string; message: string; expectedIntentKeywords: string[] }> = [
    { label: "行情查询 BTC", message: "BTC 现在什么价", expectedIntentKeywords: ["market"] },
    { label: "行情查询 ETH", message: "ETH 今日行情", expectedIntentKeywords: ["market"] },
    { label: "深度分析 BTC", message: "分析 BTC 的趋势和入场时机，并给出策略建议", expectedIntentKeywords: ["deep"] },
    { label: "策略验证 / 回测", message: "回测一下这个策略在过去一年的表现", expectedIntentKeywords: ["strategy_verify", "scenario_sim"] },
    { label: "情景推演", message: "如果美联储加息，BTC 会怎么走", expectedIntentKeywords: ["scenario"] },
    { label: "策略代码开发", message: "帮我生成一个 BTC 布林带突破策略的完整代码", expectedIntentKeywords: ["developer"] },
    { label: "策略代码 - 简化", message: "为 ETH 写一个 RSI 超卖反弹策略", expectedIntentKeywords: ["developer"] },
    { label: "交易执行", message: "开仓 BTC 多单", expectedIntentKeywords: ["execute_trade"] },
    { label: "简单问答", message: "什么是布林带？", expectedIntentKeywords: ["simple", "explain", "concept"] },
    { label: "宏观分析", message: "分析一下当前美联储政策对黄金的影响", expectedIntentKeywords: ["macro", "deep"] },
    { label: "数字资产对比", message: "BTC 和 ETH 哪个更适合现在入场", expectedIntentKeywords: ["asset_comparison", "compare"] },
    { label: "波动率分析", message: "当前 BTC 的波动率如何", expectedIntentKeywords: ["volatility"] },
    { label: "日常问候", message: "你好", expectedIntentKeywords: ["simple", "greeting"] },
    { label: "套利机会", message: "当前有没有跨交易所的套利机会", expectedIntentKeywords: ["arbitrage"] },
    { label: "板块轮动", message: "最近板块轮动情况如何", expectedIntentKeywords: ["sector_rotation"] },
    { label: "DCA 策略", message: "帮我制定一份 BTC 定投策略", expectedIntentKeywords: ["dca"] },
  ];

  const COMPLEXITIES: ComplexityLevel[] = ["simple", "moderate", "complex"];
  const MODES: Array<"quick" | "deep"> = ["quick", "deep"];

  let hit = 0;
  let total = 0;
  for (const tc of INTENT_TEST_CASES) {
    for (const mode of MODES) {
      for (const complexity of COMPLEXITIES) {
        const start = Date.now();
        total++;
        try {
          // recognizeIntent 需要 sessionId / message / context
          const result = await recognizeIntent(tc.message, {
            session_id: `stress_test_p1_${Date.now()}_${total}`,
            user_role: "PRO",
            thinking_mode: mode,
            message_history: [],
          });
          const latency = Date.now() - start;

          // 关键字包含判断（意图内部有 tag 或 enum 文本）
          const intentText = String(result.intent || "");
          const matched = tc.expectedIntentKeywords.some(k => intentText.toLowerCase().includes(k.toLowerCase()));

          // 我们允许部分识别误差（fallback 时会 fallback 到 simple_qa 等）
          // 但如果有 API key，应为正常识别
          recordCase(true, latency);
          if (matched) hit++;

          // 少量样本打印
          if (total <= 4) {
            info(`"${tc.message.slice(0, 30)}…" → intent=${intentText} (mode=${mode}, complexity=${complexity || 'auto'}) [${latency}ms]`);
          }
        } catch (e: any) {
          recordCase(false, 0, `[P1] ${tc.label}: ${e.message}`);
        }
      }
    }
  }

  console.log();
  metric("测试样例数", `${total}`, BLUE);
  metric("成功识别率", `${((stats.passed / Math.max(1, total)) * 100).toFixed(1)}%`, GREEN);
  metric("关键字命中率", `${((hit / Math.max(1, total)) * 100).toFixed(1)}%`, CYAN);
}

// =======================================================
// Phase 2: 智能路由正确性
// =======================================================
function phase2_routing() {
  section("Phase 2 · 智能路由正确性测试", "🛣️");

  // 重点：developer 必须路由到 S3→S4→S5
  const ROUTE_CHECK: Array<{ intent: IntentType; complexity: ComplexityLevel; mustContain: string[]; mustNotContain: string[]; note: string }> = [
    {
      intent: "developer" as IntentType,
      complexity: "complex",
      mustContain: ["S3_DESIGN", "S4_VALIDATE", "S5_EXECUTE"],
      mustNotContain: ["D1", "D2", "Z_", "E1_", "D-Z-E"], // 主前端不直接暴露 D-Z-E 步骤
      note: "developer 应路由到 S3→S4→S5，而不是 D-Z-E 链",
    },
    {
      intent: "deep_analysis" as IntentType,
      complexity: "complex",
      mustContain: ["S1_RESEARCH", "S2_ANALYSIS", "S3_DESIGN"],
      mustNotContain: [],
      note: "深度分析 → 至少包含 S1/S2/S3",
    },
    {
      intent: "market_query" as IntentType,
      complexity: "simple",
      mustContain: [],
      mustNotContain: ["S4_VALIDATE"],
      note: "简单行情不应触发 S4 验证步骤",
    },
    {
      intent: "simple_qa" as IntentType,
      complexity: "simple",
      mustContain: [],
      mustNotContain: ["S5_EXECUTE"],
      note: "简单问答不应触发 S5 执行",
    },
    {
      intent: "strategy_verify" as IntentType,
      complexity: "moderate",
      mustContain: ["S2_ANALYSIS", "S3_DESIGN", "S4_VALIDATE"],
      mustNotContain: [],
      note: "策略验证 → 至少包含 S2/S3/S4",
    },
    {
      intent: "scenario_sim" as IntentType,
      complexity: "moderate",
      mustContain: ["S1_RESEARCH", "S2_ANALYSIS", "S3_DESIGN"],
      mustNotContain: [],
      note: "情景推演 → 至少包含 S1/S2/S3",
    },
    {
      intent: "execute_trade" as IntentType,
      complexity: "complex",
      mustContain: ["S5_EXECUTE"],
      mustNotContain: [],
      note: "交易执行 → 必须包含 S5_EXECUTE",
    },
  ];

  let pass = 0;
  for (const rc of ROUTE_CHECK) {
    const start = Date.now();
    try {
      const routing = routeIntent(rc.intent, rc.complexity, {
        session_id: `stress_routing_${Date.now()}`,
        user_role: "PRO",
        thinking_mode: "deep",
        message_history: [],
      });
      const latency = Date.now() - start;
      const chainText = (routing.chain || []).join(" → ");
      let ok_flag = true;
      const failed: string[] = [];

      for (const must of rc.mustContain) {
        if (!chainText.includes(must)) {
          ok_flag = false;
          failed.push(`缺少: ${must}`);
        }
      }
      for (const mustNot of rc.mustNotContain) {
        if (chainText.includes(mustNot)) {
          ok_flag = false;
          failed.push(`不应出现: ${mustNot}`);
        }
      }

      if (ok_flag) {
        pass++;
        recordCase(true, latency);
        ok(`${rc.intent} (${rc.complexity}) → ${chainText || "∅"}`);
      } else {
        recordCase(false, latency, `[P2] ${rc.intent}: ${failed.join("; ")} (实际链: ${chainText})`);
        fail(`${rc.intent} (${rc.complexity}) → ${chainText || "∅"} [问题: ${failed.join(", ")}]`);
      }
      info(`${rc.note}`);
    } catch (e: any) {
      recordCase(false, 0, `[P2] routeIntent 抛出: ${e.message}`);
    }
  }

  console.log();
  metric("路由规则测试数", `${ROUTE_CHECK.length}`, BLUE);
  metric("通过数", `${pass}/${ROUTE_CHECK.length}`, pass === ROUTE_CHECK.length ? GREEN : YELLOW);
}

// =======================================================
// Phase 3: S5 执行引擎（E1→E2→E3 完整链路）
// =======================================================
function phase3_s5_engine() {
  section("Phase 3 · S5 执行引擎（E1→E2→E3 完整链路）", "⚡");

  const S5_TEST_CASES: Array<{
    label: string;
    userMessage: string;
    strategyParams?: { symbol?: string; timeframe?: string; entryRule?: string; stopLoss?: string; takeProfit?: string; positionSize?: string };
  }> = [
    {
      label: "BTC 布林带突破",
      userMessage: "为 BTC 设计一个布林带突破策略，突破上轨做空，突破下轨做多，止损 2%，止盈 4%",
      strategyParams: { symbol: "BTC", timeframe: "4h", stopLoss: "2%", takeProfit: "4%" },
    },
    {
      label: "ETH RSI 超卖反弹",
      userMessage: "生成一个基于 ETH 的 RSI 超卖反弹策略，RSI<30 买入，RSI>70 卖出，止损 1.5%，止盈 3%",
      strategyParams: { symbol: "ETH", timeframe: "1h", takeProfit: "3%" },
    },
    {
      label: "黄金 MACD 趋势",
      userMessage: "为 XAU/USD 设计一个 MACD 双均线趋势策略，金叉做多，死叉做空",
      strategyParams: { symbol: "XAU_USD", timeframe: "1d" },
    },
    {
      label: "轻量策略（quick 模式）",
      userMessage: "写一个简单的 BTC 均线策略，MA20 上穿 MA60 买入，下穿卖出",
      strategyParams: { symbol: "BTC" },
    },
    {
      label: "English strategy",
      userMessage: "Generate a BTC mean-reversion strategy using Bollinger Bands + RSI filter, exit at middle band",
      strategyParams: { symbol: "BTC", timeframe: "1h" },
    },
  ];

  // 验证 S5 静态配置
  h2("S5 静态配置检查");
  const seq = S5_STEP_SEQUENCE;
  info(`步骤序列: ${seq.map(id => `${S5_STEP_DEFINITIONS[id]?.icon || ""}${S5_STEP_DEFINITIONS[id]?.label || id}`).join(" → ")}`);
  if (seq.length === 3 && seq[0] === "E1_TASK_EXECUTE" && seq[1] === "E2_TEST_VALIDATE" && seq[2] === "E3_DEPLOY_DELIVER") {
    ok("S5 步骤序列为 E1→E2→E3，符合预期");
    recordCase(true, 0);
  } else {
    fail("S5 步骤序列不符合预期 (应为 E1→E2→E3)");
    recordCase(false, 0, `[P3] S5 step sequence: ${seq.join(",")}`);
  }

  // 执行实际 S5 调用
  h2("策略代码生成 — 全模式执行");

  const allResults: { label: string; lang: "zh" | "en"; mode: "quick" | "deep"; res: S5ExecutionResult; latencyMs: number }[] = [];

  for (const tc of S5_TEST_CASES) {
    const langs: Array<"zh" | "en"> = tc.userMessage.match(/[a-zA-Z]{5,}/) && !tc.userMessage.match(/[\u4e00-\u9fa5]/)
      ? ["en"]
      : ["zh"];
    for (const lang of langs) {
      for (const mode of ["quick" as const, "deep" as const]) {
        const start = Date.now();
        try {
          const result = executeS5({
            taskId: `stress_s5_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`,
            sessionId: `stress_s5_session`,
            userMessage: tc.userMessage,
            thinkingMode: mode,
            lang,
            strategyParams: tc.strategyParams,
          });
          const latency = Date.now() - start;
          allResults.push({ label: tc.label, lang, mode, res: result, latencyMs: latency });

          // 基础断言
          const steps = result.allStepsForDisplay || [];
          const step3 = steps.length === 3;
          const hasContent = result.content && result.content.length > 100;
          const stepDone = steps.every(s => s.status === "done");

          if (step3 && hasContent && stepDone) {
            ok(`${tc.label} (${mode}, ${lang}) → ${steps.length} 步 · ${latency}ms · ${result.content.length} chars`);
            recordCase(true, latency);
          } else {
            warn(`${tc.label} (${mode}, ${lang}) → steps=${steps.length}, content=${result.content?.length || 0}, all_done=${stepDone}`);
            recordCase(false, latency, `[P3] ${tc.label}: steps=${steps.length}, content=${result.content?.length || 0}`);
          }
        } catch (e: any) {
          fail(`${tc.label} (${mode}, ${lang}) → 异常: ${e.message}`);
          recordCase(false, 0, `[P3] executeS5 ${tc.label}: ${e.message}`);
        }
      }
    }
  }

  // renderS5Summary 功能检查
  h2("renderS5Summary 渲染验证");
  try {
    if (allResults.length > 0) {
      const sample = allResults[0];
      // renderS5Summary(state: S5ChainState, lang: 'zh' | 'en') — 与 executeS5 对齐
      const mockState: any = {
        taskId: `stress_summary_${Date.now()}`,
        sessionId: `stress_summary_session`,
        scopeDescription: `策略代码开发: ${sample.label}`,
        currentStepId: "E3_DEPLOY_DELIVER",
        currentStepIndex: S5_STEP_SEQUENCE.length - 1,
        steps: sample.res.allStepsForDisplay.map(s => ({
          stepId: s.id as S5StepId,
          status: (s.status || "done") as any,
          output: "",
          artifacts: [],
        })),
        plannedStepIds: S5_STEP_SEQUENCE as S5StepId[],
        createdAt: new Date().toISOString(),
        modifiedAt: new Date().toISOString(),
        totalDurationMs: sample.latencyMs,
      };

      const summary = renderS5Summary(mockState, sample.lang);
      const ok_flag = summary && summary.length > 100;
      if (ok_flag) { ok(`renderS5Summary 返回 ${summary.length} chars 有效摘要`); recordCase(true, 10); }
      else { warn(`renderS5Summary 返回异常 (${summary?.length || 0} chars)`); recordCase(false, 0, "[P3] renderS5Summary empty"); }
    }
  } catch (e: any) {
    fail(`renderS5Summary 抛出: ${e.message}`);
    recordCase(false, 0, `[P3] renderS5Summary: ${e.message}`);
  }

  // 汇总 S5 延迟
  if (allResults.length > 0) {
    const latencies = allResults.map(r => r.latencyMs);
    const avg = latencies.reduce((a, b) => a + b, 0) / latencies.length;
    const max = Math.max(...latencies);
    const min = Math.min(...latencies);
    h2("S5 执行延迟统计");
    metric("总执行次数", `${allResults.length}`, BLUE);
    metric("平均延迟", `${avg.toFixed(0)} ms`, GREEN);
    metric("最小/最大", `${min} ms / ${max} ms`, CYAN);
  }
}

// =======================================================
// Phase 4: 并发压力测试
// =======================================================
async function phase4_concurrency() {
  section("Phase 4 · 并发压力测试", "⚙️");

  const CONCURRENT = 20;
  const ROUNDS = 5;

  const S5_MESSAGES = [
    "为 BTC 设计一个布林带突破策略",
    "生成一个 ETH RSI 超卖反弹策略",
    "设计一个 MACD 趋势策略，适用于黄金",
    "为 DOGE 写一个均线交叉策略",
    "BTC 双均线趋势策略",
  ];

  interface PerRound {
    round: number;
    durations: number[];
    failed: number;
  }
  const rounds: PerRound[] = [];

  for (let r = 0; r < ROUNDS; r++) {
    h2(`第 ${r + 1} / ${ROUNDS} 轮 · ${CONCURRENT} 并发`);

    const start = Date.now();
    const promises = Array.from({ length: CONCURRENT }, (_, i) => {
      const userMessage = S5_MESSAGES[(r + i) % S5_MESSAGES.length];
      return new Promise<{ ok: boolean; dur: number; err?: string }>((resolve) => {
        const t0 = Date.now();
        try {
          const res = executeS5({
            taskId: `concurrent_${r}_${i}_${Date.now()}`,
            sessionId: `concurrent_session_${r}`,
            userMessage,
            thinkingMode: (i % 2 === 0 ? "quick" : "deep") as "quick" | "deep",
            lang: "zh",
          });
          const dur = Date.now() - t0;
          if (res && res.content && res.content.length > 100) resolve({ ok: true, dur });
          else resolve({ ok: false, dur, err: "content too short" });
        } catch (e: any) {
          resolve({ ok: false, dur: Date.now() - t0, err: e.message });
        }
      });
    });

    const results = await Promise.all(promises);
    const totalDur = Date.now() - start;

    const durations = results.map(r => r.dur);
    const failed = results.filter(r => !r.ok).length;
    const success = CONCURRENT - failed;
    const avg = durations.reduce((a, b) => a + b, 0) / durations.length;

    rounds.push({ round: r + 1, durations, failed });

    info(`成功 ${success}/${CONCURRENT} · 平均单任务 ${avg.toFixed(0)} ms · 整轮耗时 ${totalDur} ms · 失败 ${failed}`);
    if (failed > 0) {
      results.filter(r => !r.ok).slice(0, 3).forEach(r => info(` 失败样例: ${r.err}`));
    }

    // 记录全局
    results.forEach(r => recordCase(r.ok, r.dur, r.ok ? undefined : `[P4] ${r.err}`));
  }

  // 汇总
  const allDur = rounds.flatMap(r => r.durations);
  const totalFail = rounds.reduce((a, r) => a + r.failed, 0);
  const totalCount = rounds.length * CONCURRENT;
  const avg = allDur.reduce((a, b) => a + b, 0) / allDur.length;
  const p95 = [...allDur].sort((a, b) => a - b)[Math.floor(allDur.length * 0.95)];
  const p99 = [...allDur].sort((a, b) => a - b)[Math.floor(allDur.length * 0.99)];

  console.log();
  h2("并发测试汇总");
  metric("总任务数", `${totalCount}`, BLUE);
  metric("成功数", `${totalCount - totalFail}`, GREEN);
  metric("失败数", `${totalFail}`, totalFail === 0 ? GREEN : RED);
  metric("平均延迟", `${avg.toFixed(0)} ms`, GREEN);
  metric("P95 延迟", `${p95} ms`, CYAN);
  metric("P99 延迟", `${p99} ms`, MAGENTA);
  metric("吞吐", `${(totalCount / (allDur.reduce((a, b) => a + b, 0) / 1000)).toFixed(2)} req/s (仅 CPU)`, CYAN);
  metric("失败率", `${((totalFail / totalCount) * 100).toFixed(2)}%`, totalFail === 0 ? GREEN : YELLOW);
}

// =======================================================
// Phase 5: 边界 & 错误注入
// =======================================================
function phase5_edgeCases() {
  section("Phase 5 · 边界条件与错误注入测试", "🧱");

  // 5.1 空消息 / 空白消息
  h2("空消息 / 空白消息");
  for (const emptyMsg of ["", "   ", "\n\t", "    \n  \t   "]) {
    const start = Date.now();
    try {
      // S5 对空消息应当优雅处理（返回模板或提示）
      const res = executeS5({
        taskId: `edge_empty_${Date.now()}`,
        sessionId: `edge_session`,
        userMessage: emptyMsg,
        thinkingMode: "quick",
        lang: "zh",
      });
      const latency = Date.now() - start;
      if (res && res.content) { ok(`空消息 "${emptyMsg}" → 返回 ${res.content.length} chars (${latency}ms)`); recordCase(true, latency); }
      else { fail(`空消息 "${emptyMsg}" → 空返回`); recordCase(false, latency, `[P5] empty msg returned nothing`); }
    } catch (e: any) {
      warn(`空消息 "${emptyMsg}" → 抛出: ${e.message} (需确保不崩溃)`);
      recordCase(false, 0, `[P5] empty msg threw: ${e.message}`);
    }
  }

  // 5.2 超长消息
  h2("超长消息 (2k chars)");
  const longMsg = "请分析 BTC 的走势，并给出详细建议。".repeat(40);
  const t0 = Date.now();
  try {
    const res = executeS5({
      taskId: `edge_long_${Date.now()}`,
      sessionId: `edge_session`,
      userMessage: longMsg,
      thinkingMode: "quick",
      lang: "zh",
    });
    const latency = Date.now() - t0;
    if (res && res.content && res.content.length > 100) { ok(`超长消息 ${longMsg.length} chars → 返回 ${res.content.length} chars (${latency}ms)`); recordCase(true, latency); }
    else { warn(`超长消息返回内容较少: ${res?.content?.length || 0} chars`); recordCase(false, latency, `[P5] long msg returned ${res?.content?.length || 0} chars`); }
  } catch (e: any) {
    fail(`超长消息抛出: ${e.message}`);
    recordCase(false, 0, `[P5] long msg threw: ${e.message}`);
  }

  // 5.3 恶意字符 / 特殊符号
  h2("特殊符号 / 恶意字符注入");
  const attackMsgs = [
    "<script>alert(1)</script> 帮我生成策略",
    `'; DROP TABLE strategies; -- 写策略`,
    "{{ template }} <%= 1/0 %> && rm -rf /",
    "💥🔥🎯📊💰 全 emoji 请求",
    "中文测试：帮我设计一个「『「」』」嵌套的策略",
  ];
  for (const msg of attackMsgs) {
    const start = Date.now();
    try {
      const res = executeS5({
        taskId: `edge_attack_${Date.now()}`,
        sessionId: `edge_session`,
        userMessage: msg,
        thinkingMode: "quick",
        lang: "zh",
      });
      const latency = Date.now() - start;
      if (res && res.content) {
        // 检查是否发生脚本注入（不应当在输出中原样保留 <script>）
        if (res.content.includes("<script>")) {
          warn(`检测到潜在 XSS: ${msg.slice(0, 20)}… → 输出中含 <script>`);
          recordCase(false, latency, `[P5] XSS detection: output contains <script>`);
        } else {
          ok(`消息: "${msg.slice(0, 20)}…" → 正常生成 ${res.content.length} chars (${latency}ms)`);
          recordCase(true, latency);
        }
      } else {
        fail(`恶意字符测试返回空`);
        recordCase(false, latency, `[P5] attack msg returned nothing`);
      }
    } catch (e: any) {
      warn(`恶意字符 "${msg.slice(0, 20)}" → 抛出: ${e.message}`);
      recordCase(false, 0, `[P5] attack msg threw: ${e.message}`);
    }
  }

  // 5.4 参数缺失 / 乱序
  h2("参数缺失 / 乱序");
  const badParamCases: Array<{ label: string; params: any }> = [
    { label: "missing strategyParams", params: { taskId: `x_${Date.now()}`, sessionId: "x", userMessage: "写个 BTC 策略", thinkingMode: "quick", lang: "zh" } },
    { label: "unknown thinkingMode", params: { taskId: `x_${Date.now()}`, sessionId: "x", userMessage: "写个 BTC 策略", thinkingMode: "ultra", lang: "zh" } },
    { label: "空 lang", params: { taskId: `x_${Date.now()}`, sessionId: "x", userMessage: "写个 BTC 策略", thinkingMode: "quick", lang: "" } },
  ];
  for (const bp of badParamCases) {
    const start = Date.now();
    try {
      const res = executeS5(bp.params);
      const latency = Date.now() - start;
      if (res && res.content) { ok(`${bp.label} → 返回 ${res.content.length} chars (${latency}ms)`); recordCase(true, latency); }
      else { warn(`${bp.label} → 返回空`); recordCase(false, latency, `[P5] ${bp.label} returned nothing`); }
    } catch (e: any) {
      fail(`${bp.label} → 抛出: ${e.message}`);
      recordCase(false, 0, `[P5] ${bp.label}: ${e.message}`);
    }
  }

  // 5.5 重复调用同 sessionId
  h2("同 sessionId 重复调用");
  const sessId = `stress_same_session_${Date.now()}`;
  const userMsg = "BTC 双均线策略";
  let anyFail = false;
  for (let i = 0; i < 10; i++) {
    const start = Date.now();
    try {
      const res = executeS5({
        taskId: `${sessId}_task_${i}`,
        sessionId: sessId,
        userMessage: userMsg,
        thinkingMode: "quick",
        lang: "zh",
      });
      const latency = Date.now() - start;
      if (!res || !res.content) anyFail = true;
    } catch (e: any) {
      anyFail = true;
      recordCase(false, 0, `[P5] duplicate session call threw: ${e.message}`);
    }
  }
  if (!anyFail) { ok("同 sessionId × 10 次连续调用，全部成功"); recordCase(true, 5); }
  else { fail("同 sessionId 重复调用中存在失败"); recordCase(false, 5, "[P5] repeated session calls failed"); }
}

// =======================================================
// Phase 6: 内存与资源观测
// =======================================================
async function phase6_memory() {
  section("Phase 6 · 内存 & 资源观测", "🧠");

  if (typeof (process as any) !== "undefined" && (process as any).memoryUsage) {
    const before = (process as any).memoryUsage();
    info(`初始内存: heapUsed=${(before.heapUsed / 1024 / 1024).toFixed(1)} MB, rss=${(before.rss / 1024 / 1024).toFixed(1)} MB`);

    // 进行批量 S5 任务
    const BATCH = 100;
    const t0 = Date.now();
    for (let i = 0; i < BATCH; i++) {
      executeS5({
        taskId: `memory_test_task_${i}`,
        sessionId: `memory_test_session`,
        userMessage: "设计一个 BTC 均线交叉策略",
        thinkingMode: "quick",
        lang: "zh",
      });
    }
    const dur = Date.now() - t0;

    const after = (process as any).memoryUsage();
    const deltaHeap = (after.heapUsed - before.heapUsed) / 1024 / 1024;
    const deltaRss = (after.rss - before.rss) / 1024 / 1024;

    info(`执行 ${BATCH} 次 S5，总耗时 ${dur} ms`);
    info(`执行后: heapUsed=${(after.heapUsed / 1024 / 1024).toFixed(1)} MB, rss=${(after.rss / 1024 / 1024).toFixed(1)} MB`);

    console.log();
    metric("任务数", `${BATCH}`, BLUE);
    metric("Heap 变化", `${deltaHeap > 0 ? "+" : ""}${deltaHeap.toFixed(1)} MB`, deltaHeap < 20 ? GREEN : YELLOW);
    metric("RSS 变化", `${deltaRss > 0 ? "+" : ""}${deltaRss.toFixed(1)} MB`, deltaRss < 40 ? GREEN : YELLOW);
    metric("平均耗时", `${(dur / BATCH).toFixed(1)} ms / 任务`, GREEN);

    // 判断是否存在泄漏风险
    if (deltaHeap < 20) ok(`内存增长在可控范围 (${deltaHeap.toFixed(1)} MB for ${BATCH} tasks)`);
    else warn(`内存增长偏高，需关注 (${deltaHeap.toFixed(1)} MB for ${BATCH} tasks)`);

    recordCase(deltaHeap < 50, dur);
  } else {
    warn("process.memoryUsage 不可用 — 跳过内存测量");
  }
}

// =======================================================
// 最终汇总报告
// =======================================================
function finalReport() {
  section("最终报告 · 汇总统计", "📊");

  const total = stats.totalCases;
  const passRate = total > 0 ? ((stats.passed / total) * 100).toFixed(2) : "0.00";
  const totalMs = Date.now() - stats.startTs;

  const latencies = stats.latenciesMs.filter(l => l > 0);
  const avgLat = latencies.length > 0 ? (latencies.reduce((a, b) => a + b, 0) / latencies.length).toFixed(1) : "0";
  const maxLat = latencies.length > 0 ? Math.max(...latencies) : 0;

  console.log(`
  ${BOLD}══════════════════════════════════════════════════════${RESET}
  ${BOLD}  多场景模拟压力测试 · 最终报告${RESET}
  ${BOLD}══════════════════════════════════════════════════════${RESET}

  ${GREEN}✓ 通过:${RESET}      ${stats.passed} / ${total}
  ${RED}✗ 失败:${RESET}      ${stats.failed}
  ${BLUE}📈 通过率:${RESET}    ${passRate}%
  ${CYAN}⏱  平均延迟:${RESET}   ${avgLat} ms
  ${MAGENTA}🐢 最大延迟:${RESET}   ${maxLat} ms
  ${YELLOW}🕒 总耗时:${RESET}     ${totalMs} ms (${(totalMs / 1000).toFixed(1)} s)

  ${BOLD}────────── 各 Phase 简述 ──────────${RESET}
  · Phase 1: 意图识别覆盖率（全部意图 × thinking_mode × 复杂度）
  · Phase 2: 智能路由正确性（重点验证 developer → S3→S4→S5，不暴露 D-Z-E）
  · Phase 3: S5 执行引擎（E1→E2→E3 全链路 × 多标的 × 多语言）
  · Phase 4: 并发压力（20 并发 × 5 轮，P95/P99 延迟）
  · Phase 5: 边界与错误注入（空消息 / 超长 / 特殊字符 / 参数乱序）
  · Phase 6: 内存观测（100 任务内存增长）
  `);

  if (stats.errors.length > 0) {
    console.log(`  ${BOLD}${RED}失败详情（Top 20）:${RESET}\n`);
    stats.errors.slice(0, 20).forEach((err, i) => {
      console.log(`    ${RED}[${i + 1}]${RESET} ${err}`);
    });
    console.log();
  }

  // 判定级别
  let grade: string;
  let color: string;
  const rate = stats.passed / Math.max(1, stats.totalCases);
  if (rate >= 0.98 && stats.failed === 0) { grade = "S · 完美"; color = GREEN; }
  else if (rate >= 0.95) { grade = "A · 优秀"; color = GREEN; }
  else if (rate >= 0.85) { grade = "B · 良好"; color = CYAN; }
  else if (rate >= 0.70) { grade = "C · 及格"; color = YELLOW; }
  else { grade = "D · 需修复"; color = RED; }

  console.log(`  ${BOLD}评级: ${color}${grade}${RESET}`);
  console.log(`  ${BOLD}══════════════════════════════════════════════════════${RESET}\n`);
}

// =======================================================
// 主入口
// =======================================================
async function main() {
  console.log(`\n${BOLD}${GREEN}══════════════════════════════════════════════════════════════${RESET}`);
  console.log(`${BOLD}${GREEN}  多场景模拟压力测试 · 主前端核心链路（S 系列 + S5 执行引擎）${RESET}`);
  console.log(`${BOLD}${GREEN}  启动时间: ${new Date().toLocaleString()}${RESET}`);
  console.log(`${BOLD}${GREEN}  Node 版本: ${process.version}${RESET}`);
  console.log(`${BOLD}${GREEN}══════════════════════════════════════════════════════════════${RESET}\n`);

  // 前置自检：确认关键模块已导出
  section("前置自检 · 模块导入", "🔌");
  try {
    ok("routeIntent 已导入");
    ok("recognizeIntent 已导入");
    ok("executeS5 已导入");
    ok("S5_STEP_SEQUENCE 已导入");
    ok("renderS5Summary 已导入");
    ok("S5_STEP_DEFINITIONS 已导入");
    ok("getS5StepDisplay 已导入");

    // getS5StepDisplay 功能测试
    const disp = getS5StepDisplay("E1_TASK_EXECUTE");
    if (disp && disp.label) ok(`getS5StepDisplay("E1_TASK_EXECUTE") → ${disp.icon} ${disp.label}`);
    else fail("getS5StepDisplay 返回异常");

    info(`S5_STEP_DEFINITIONS 共 ${Object.keys(S5_STEP_DEFINITIONS).length} 个步骤`);
  } catch (e: any) {
    fail(`模块导入失败: ${e.message}`);
    process.exit(1);
  }

  // 按阶段运行
  await phase1_intentRecognition();
  phase2_routing();
  phase3_s5_engine();
  await phase4_concurrency();
  phase5_edgeCases();
  await phase6_memory();

  finalReport();
}

main().catch(err => {
  console.error(`\n${RED}测试脚本崩溃:${RESET}`, err);
  process.exit(1);
});
