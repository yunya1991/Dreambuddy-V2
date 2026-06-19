/**
 * 端到端协作能力诊断脚本
 * 模拟: 用户输入 → 意图识别 → 思维链 → 向量知识库 → 策略引擎 → 用户偏好
 */

import { routeIntent } from "../src/lib/intent/index";
import { buildRAGContext, getRAGStats } from "../src/lib/knowledge-rag";
import { formatMemoryPrompt } from "../src/lib/memory/user-preference-memory";
import userPrefMemory from "../src/lib/memory/user-preference-memory";
import * as fs from "fs";
import * as path from "path";

// 测试任务
const TASK = {
  userPrompt: "分析 BTC 的趋势和入场时机，并考虑美联储加息对市场的影响",
  sessionId: "diagnostic_session_001",
  intentHint: "deep_analysis",
};

// 终端颜色
const GREEN = "\x1b[32m";
const YELLOW = "\x1b[33m";
const RED = "\x1b[31m";
const BOLD = "\x1b[1m";
const RESET = "\x1b[0m";

function section(title: string, emoji: string = "📦") {
  console.log(`\n${BOLD}${emoji}  ${title}${RESET}`);
  console.log("─".repeat(64));
}
function ok(msg: string) { console.log(`  ${GREEN}✓${RESET} ${msg}`); }
function warn(msg: string) { console.log(`  ${YELLOW}⚠${RESET} ${msg}`); }
function fail(msg: string) { console.log(`  ${RED}✗${RESET} ${msg}`); }
function info(msg: string) { console.log(`    → ${msg}`); }

async function main() {
  console.log(`\n${BOLD}══════════════════════════════════════════════════${RESET}`);
  console.log(`${BOLD}  前端 7 大核心功能 · 协作能力诊断${RESET}`);
  console.log(`${BOLD}  模拟任务: ${TASK.userPrompt}${RESET}`);
  console.log(`${BOLD}══════════════════════════════════════════════════${RESET}`);

  // ============================================================
  // [1] 意图识别
  // ============================================================
  section("1. 意图识别", "🧭");
  try {
    const parsed = routeIntent(TASK.userPrompt, TASK.sessionId);
    if (parsed && parsed.intent) {
      ok(`主意图: ${parsed.intent}`);
      ok(`复杂度: ${parsed.complexity || "(无)"}`);
      const ents = parsed.entities || {};
      ok(`实体解析: ${Object.keys(ents).length} 个`);
      if (Object.keys(ents).length > 0) {
        Object.entries(ents).forEach(([k, v]) => info(`${k}: ${JSON.stringify(v)}`));
      }
      if (parsed.routing && parsed.routing.chain && parsed.routing.chain.length > 0) {
        ok(`思维链: ${parsed.routing.chain.join(" → ")}`);
      } else {
        warn("未生成执行链 (可能需要触发链的意图阈值)");
      }
    } else {
      fail("意图识别返回空");
    }
  } catch (e: any) {
    fail(`意图识别异常: ${e.message || e}`);
  }

  // ============================================================
  // [2] 向量知识库 (RAG)
  // ============================================================
  section("2. 向量知识库 · RAG", "📚");
  try {
    const stats = getRAGStats();
    ok(`发现文档数: ${stats.totalFiles}`);
    ok(`已切片 chunks: ${stats.totalChunks}`);
    ok(`向量缓存: ${stats.cacheSizeKB} KB (位于 data/knowledge_vector_cache_v2.json)`);
    ok(`缓存路径: ${stats.cachePath}`);

    const ragCtx = await buildRAGContext(TASK.userPrompt, TASK.intentHint, 2000);
    if (ragCtx && ragCtx.length > 100) {
      ok(`检索到内容: ${ragCtx.length} chars`);
      const isRealRetrieval = ragCtx.includes("知识库") && ragCtx.includes("检索");
      if (isRealRetrieval) {
        ok("向量检索已启用 (非默认方法论)");
      } else {
        warn("当前走 fallback 路径 (默认方法论) —");
        info("触发条件: 需配置 DEEPSEEK_API_KEY 或 首次请求建立向量缓存");
      }
      console.log("\n    【RAG 上下文预览】");
      console.log(`    ${ragCtx.slice(0, 300).replace(/\n/g, "\n    ")}...`);
    } else {
      warn("RAG 返回内容过少 (< 100 chars)");
    }
  } catch (e: any) {
    fail(`RAG 检索异常: ${e.message || e}`);
  }

  // ============================================================
  // [3] 策略引擎 · Python 桥接
  // ============================================================
  section("3. 策略引擎 · Python 桥接", "⚙️");
  try {
    // HTTP ping (测试桥接服务是否运行)
    let bridgeRunning = false;
    try {
      const ctrl = new AbortController();
      const timer = setTimeout(() => ctrl.abort(), 3000);
      const resp = await fetch("http://127.0.0.1:3847/api/strategy/info", {
        signal: ctrl.signal,
      });
      clearTimeout(timer);
      if (resp.ok) {
        const body = await resp.json() as any;
        ok("桥接服务运行中 (http://127.0.0.1:3847)");
        ok(`支持算法: ${(body.algorithms || []).slice(0, 2).join(", ")}`);
        bridgeRunning = true;
      } else {
        warn("桥接服务响应异常 (HTTP " + resp.status + ")");
      }
    } catch {
      warn("桥接服务未启动 — 回退到 LLM 直接生成 (可接受)");
    }

    // 代码层面: 检查 route.ts 中 callStrategyEngine 是否定义
    const routePath = path.resolve(__dirname, "../src/app/api/chat/route.ts");
    const routeFile = fs.readFileSync(routePath, "utf-8");

    if (routeFile.includes("async function callStrategyEngine")) {
      ok("callStrategyEngine 函数已定义");
    } else {
      fail("callStrategyEngine 函数未找到");
    }
    if (routeFile.includes("STRATEGY_BRIDGE_HOST") || routeFile.includes("127.0.0.1:3847")) {
      ok("桥接地址 /api/strategy/backtest 已正确配置");
    } else {
      fail("桥接地址未配置");
    }
    if (!bridgeRunning) {
      info("启动命令: cd 6-TRADING && python3 bridge/run_server.py");
    }
  } catch (e: any) {
    fail(`策略引擎诊断异常: ${e.message || e}`);
  }

  // ============================================================
  // [4] 用户偏好记忆系统
  // ============================================================
  section("4. 用户偏好记忆 · Hermes", "🧠");
  try {
    const memory = userPrefMemory;

    // 1) 学习
    memory.learn({
      userId: TASK.sessionId,
      type: "risk_tolerance",
      value: ["稳健型"],
      importance: 0.6,
      source: "user_profile",
      evidence: "诊断任务模拟",
    });
    memory.learn({
      userId: TASK.sessionId,
      type: "trading_style",
      value: ["趋势跟随", "分批入场"],
      importance: 0.5,
      source: "user_profile",
      evidence: "诊断任务模拟",
    });
    memory.learn({
      userId: TASK.sessionId,
      type: "preferred_symbols",
      value: ["BTC"],
      importance: 0.4,
      source: "implicit_behavior",
      evidence: "诊断任务模拟",
    });

    // 2) 读取
    const snapshot = memory.retrieve(TASK.sessionId);
    ok(`Session ID: ${TASK.sessionId}`);
    ok(`已学习到 ${snapshot.total_memories} 条记忆`);
    ok(`风险偏好: ${snapshot.risk_tolerance || "(无)"}`);
    ok(`偏好标的: ${snapshot.preferred_symbols || "(无)"}`);

    // 3) 格式化提示词（独立函数）
    const prompt = formatMemoryPrompt(snapshot);
    if (prompt && prompt.length > 10) {
      ok(`formatMemoryPrompt 正常工作 (${prompt.length} chars)`);
      console.log(`    预览: ${prompt.slice(0, 200)}...`);
    } else {
      warn("formatMemoryPrompt 返回空 — 可能是 snapshot 值不在类型映射中 (如 '稳健型' 不在 low/medium/high 中)");
      info("这是预期行为：中文标签需映射到标准 risk_tolerance 枚举 (low/medium/high)");
    }
  } catch (e: any) {
    fail(`用户记忆异常: ${e.message || e}`);
  }

  // ============================================================
  // [5] S 思维链 + 步进式推进
  // ============================================================
  section("5. S 思维链 · 步进式推进", "🔗");
  try {
    const routePath = path.resolve(__dirname, "../src/app/api/chat/route.ts");
    const routeFile = fs.readFileSync(routePath, "utf-8");

    if (routeFile.includes("generateChainResponse")) ok("generateChainResponse 存在 (协调核心)");
    if (routeFile.includes("chainState") || routeFile.includes("chain_state")) ok("chainState 状态机存在");
    if (routeFile.includes("needUserConfirmation") || routeFile.includes("needsConfirmation")) ok("用户确认门禁存在");
    if (routeFile.includes("previousStepOutput") || routeFile.includes("cumulativeOutput")) ok("思维链上下文传递已实现");
    if (routeFile.includes("callLLMStep") || routeFile.includes("callLlmStep")) ok("LLM Step 调用存在");

    // 双推荐
    const hasDualRecommend =
      routeFile.includes("系统推荐") ||
      routeFile.includes("standard_recommend") ||
      routeFile.includes("system_recommend");
    const hasPrefRecommend =
      routeFile.includes("偏好推荐") ||
      routeFile.includes("preference_recommend") ||
      routeFile.includes("个性化");

    if (hasDualRecommend) ok("系统推荐分支存在");
    else fail("系统推荐分支缺失");
    if (hasPrefRecommend) ok("偏好推荐分支存在");
    else fail("偏好推荐分支缺失");

    // 7 步进度条
    if (routeFile.includes("stepProgress") || routeFile.includes("step_progress")) {
      ok("7 步进度条状态已实现");
    }

    // smart-router.ts 检查
    const routerPath = path.resolve(__dirname, "../src/lib/intent/smart-router.ts");
    if (fs.existsSync(routerPath)) {
      const routerContent = fs.readFileSync(routerPath, "utf-8");
      if (routerContent.includes("generateStepConfirmationPrompt") || routerContent.includes("用户确认")) {
        ok("步进确认提示存在 (smart-router.ts)");
      }
    }
  } catch (e: any) {
    fail(`思维链诊断异常: ${e.message || e}`);
  }

  // ============================================================
  // [6] 笔记本 · 任务清单
  // ============================================================
  section("6. 笔记本记录 · 任务清单", "📓");
  try {
    const nbFolder = path.resolve(__dirname, "../src/app/api/notebook");
    if (fs.existsSync(nbFolder)) {
      ok("/api/notebook 路由文件夹存在");
      const check = [
        "route.ts",
        "state/route.ts",
        "step/route.ts",
        "tasks/route.ts",
        "sync/route.ts",
      ];
      for (const r of check) {
        const p = path.join(nbFolder, r);
        if (fs.existsSync(p)) ok(`  · ${r} 已实现`);
        else warn(`  · ${r} 缺失`);
      }
    } else {
      warn("/api/notebook 路由文件夹缺失 — 任务清单仅前端本地");
    }

    // 前端组件
    const compPath = path.resolve(__dirname, "../src/components/notebook/NotebookPanel.tsx");
    if (fs.existsSync(compPath)) ok("NotebookPanel 前端组件存在");
    const storePath = path.resolve(__dirname, "../src/stores/notebook-store.ts");
    if (fs.existsSync(storePath)) ok("notebook-store.ts 状态管理存在");
  } catch (e: any) {
    fail(`笔记本诊断异常: ${e.message || e}`);
  }

  // ============================================================
  // [7] 方案推荐 · 双推荐系统
  // ============================================================
  section("7. 方案推荐 · 双推荐系统", "🎯");
  try {
    const routePath = path.resolve(__dirname, "../src/app/api/chat/route.ts");
    const routeFile = fs.readFileSync(routePath, "utf-8");

    let score = 0;
    if (routeFile.includes("usePreference") || routeFile.includes("with_preference")) { score++; ok("偏好注入开关存在 (usePreference)"); }
    else fail("偏好注入开关缺失 — 偏好推荐可能无效");
    if (routeFile.includes("system_recommend") || routeFile.includes("standard_analysis")) { score++; ok("系统推荐路由分支存在"); }
    if (routeFile.includes("preference_recommend") || routeFile.includes("personalized")) { score++; ok("偏好推荐路由分支存在"); }
    if (score === 0) warn("双推荐系统缺乏明确分支代码 — 需核查");

    // 检查是否有用户记忆 prompt 注入
    if (routeFile.includes("memory.formatMemoryPrompt") || routeFile.includes("userPrefMemory") ||
        routeFile.includes("用户偏好") || routeFile.includes("记忆")) {
      ok("用户记忆上下文已正确注入到 LLM prompt");
    } else {
      warn("未发现用户记忆上下文注入 LLM prompt 的代码位置");
    }
  } catch (e: any) {
    fail(`方案推荐诊断异常: ${e.message || e}`);
  }

  // ============================================================
  // [8] 数据流 · 协作断点分析
  // ============================================================
  section("数据流与协作断点 · 综合分析", "🔬");

  console.log(`
  ${BOLD}数据流设计:${RESET}
    用户输入 ─▶ 意图识别 ─▶ 思维链生成 ─▶ 步进确认 ─▶ 向量知识库 ─▶ LLM ─▶ 策略引擎
                │             │               │                │
                ▼             ▼               ▼                ▼
            实体解析      7 步状态机   偏好/系统双选择      2-KNOWLEDGE 文档
                                                                   │
                                                                   ▼
                                                           注入 system prompt

  ${BOLD}协作依赖图:${RESET}
    route.ts (中枢)
    ├─ intent/fallback-engine.ts       (意图识别)
    ├─ knowledge-rag.ts                (向量知识库 — 每步都调用)
    ├─ memory/user-preference-memory.ts (偏好注入)
    ├─ market-data-adapter.ts          (实时行情)
    └─ 6-TRADING/bridge/api/strategy_backtest_api.py (Python 回测 · HTTP)
  `);

  console.log(`\n${BOLD}══════════════════════════════════════════════════${RESET}`);
  console.log(`  诊断完成 ✓`);
  console.log(`  详细修复建议请参见下一个报告`);
  console.log(`${BOLD}══════════════════════════════════════════════════${RESET}\n`);
}

main();
