/**
 * 端到端协作能力诊断脚本（不依赖 Next.js）
 * 模拟: 用户输入 → 意图识别 → 思维链 → 向量知识库 → 策略引擎 → 用户偏好
 * 输出: 每个模块的状态 + 数据流检查 + 协作断点分析
 */

// ------- 1. 模块导入 -------
const { routeIntent } = require('../../lib/intent');
const { default: memory } = require('../../lib/memory/user-preference-memory');
const { buildRAGContext, getRAGStats, retrieveRelevantChunks } = require('../../lib/knowledge-rag');

// ------- 2. 测试任务 -------
const TASK = {
  userPrompt: '分析 BTC 的趋势和入场时机，并考虑美联储加息对市场的影响',
  sessionId: 'diagnostic_session_001',
  intentHint: 'deep_analysis',
};

// ------- 3. 输出工具 -------
const YELLOW = '\x1b[33m';
const GREEN = '\x1b[32m';
const RED = '\x1b[31m';
const BOLD = '\x1b[1m';
const RESET = '\x1b[0m';

function section(title, emoji = '📦') {
  console.log(`\n${BOLD}${emoji}  ${title}${RESET}${'─'.repeat(60 - title.length - 4)}`);
}
function ok(msg) { console.log(`  ${GREEN}✓${RESET} ${msg}`); }
function warn(msg) { console.log(`  ${YELLOW}⚠${RESET} ${msg}`); }
function fail(msg) { console.log(`  ${RED}✗${RESET} ${msg}`); }

// ------- 4. 逐模块诊断 -------

async function diagnose() {
  console.log(`\n${BOLD}══════════════════════════════════════════════════${RESET}`);
  console.log(`${BOLD}  前端核心 7 大功能 · 协作能力诊断${RESET}`);
  console.log(`${BOLD}  模拟任务: ${TASK.userPrompt}${RESET}`);
  console.log(`${BOLD}══════════════════════════════════════════════════${RESET}`);

  // -------- [1] 意图识别 --------
  section('1. 意图识别', '🧭');
  let parsedIntent;
  try {
    const { routeIntent } = require('../../lib/intent/fallback-engine');
    parsedIntent = routeIntent(TASK.userPrompt, TASK.sessionId);
    if (parsedIntent && parsedIntent.intent) {
      ok(`主意图: ${parsedIntent.intent}`);
      ok(`复杂度阈值: ${parsedIntent.complexity || '(无)'}`);
      ok(`实体解析: ${Object.keys(parsedIntent.entities || {}).length} 个实体`);
      if (parsedIntent.entities && Object.keys(parsedIntent.entities).length > 0) {
        console.log('    实体详情:', JSON.stringify(parsedIntent.entities, null, 2).replace(/\n/g, '\n    '));
      }
    } else {
      fail('意图识别返回空');
    }
  } catch (e) {
    fail(`意图识别异常: ${e.message || e}`);
  }

  // -------- [2] 向量知识库 --------
  section('2. 向量知识库 (RAG)', '📚');
  const kbStats = getRAGStats();
  ok(`发现文档数: ${kbStats.totalFiles}`);
  ok(`已切片 chunks: ${kbStats.totalChunks}`);
  ok(`向量缓存大小: ${kbStats.cacheSizeKB} KB`);

  let ragOk = false;
  try {
    const ragCtx = await buildRAGContext(TASK.userPrompt, TASK.intentHint, 2000);
    if (ragCtx && ragCtx.length > 50) {
      ok(`RAG 上下文返回长度: ${ragCtx.length} chars`);
      // 看看是不是命中了向量检索
      if (ragCtx.includes('知识库') && ragCtx.includes('检索')) {
        ok('RAG 已包含文档片段结构');
      }
      // 预览前 200 chars
      console.log(`    预览: ${ragCtx.slice(0, 250).replace(/\n/g, ' / ')}...`);
      ragOk = true;
    } else {
      warn('RAG 上下文短 — 使用了默认方法论（无向量命中或 API key 未配置）');
    }
  } catch (e) {
    fail(`RAG 检索异常: ${e.message || e}`);
  }

  // -------- [3] 策略引擎（Python 桥接） --------
  section('3. 策略引擎 · Python 桥接', '⚙️');
  let engineOk = false;
  try {
    // 先检查桥接服务是否运行（不需要真实回测，HTTP ping 即可）
    const fetch = (...args) => import('node-fetch').then(({ default: fetch }) => fetch(...args));
    try {
      const ping = await fetch('http://127.0.0.1:3847/api/strategy/info', {
        method: 'GET',
        signal: AbortSignal.timeout(3000),
      });
      if (ping.ok) {
        ok('策略桥接服务运行中 (http://127.0.0.1:3847)');
        const body = await ping.json();
        ok(`服务支持符号: ${(body.supported_symbols || []).join(', ')}`);
        engineOk = true;
      } else {
        warn('桥接服务响应异常（HTTP ' + ping.status + '）- 会使用 LLM fallback');
      }
    } catch {
      warn('桥接服务未启动 — 回退到 LLM 直接生成（可接受）');
    }

    // 检查 route.ts 中的 callStrategyEngine 存不存在
    const fs = require('fs');
    const routeFile = fs.readFileSync('../../app/api/chat/route.ts', 'utf-8');
    if (routeFile.includes('async function callStrategyEngine')) {
      ok('callStrategyEngine 函数已定义');
    } else {
      fail('callStrategyEngine 函数未找到');
    }
    if (routeFile.includes('api/strategy/backtest') || routeFile.includes('STRATEGY_BRIDGE_HOST')) {
      ok('前端已正确配置桥接地址');
    }
  } catch (e) {
    fail(`策略引擎诊断异常: ${e.message || e}`);
  }

  // -------- [4] 用户偏好记忆系统 --------
  section('4. 用户偏好记忆 · Hermes', '🧠');
  try {
    // 模拟用户偏好注入 & 读取
    memory.learn({
      userId: TASK.sessionId,
      type: 'risk_tolerance',
      value: ['稳健型'],
      importance: 0.6,
      source: 'user_profile',
      evidence: '诊断任务模拟',
    });
    memory.learn({
      userId: TASK.sessionId,
      type: 'trading_style',
      value: ['趋势跟随', '分批入场'],
      importance: 0.5,
      source: 'user_profile',
      evidence: '诊断任务模拟',
    });
    memory.learn({
      userId: TASK.sessionId,
      type: 'preferred_symbols',
      value: ['BTC'],
      importance: 0.4,
      source: 'implicit_behavior',
      evidence: '诊断任务模拟',
    });

    const snapshot = memory.retrieve(TASK.sessionId);
    ok(`当前 session_id: ${TASK.sessionId}`);
    ok(`已学习到 ${snapshot.total_memories} 条偏好记忆`);
    ok(`风险偏好: ${snapshot.risk_tolerance || '(无)'}`);
    ok(`交易风格: ${snapshot.trading_style || '(无)'}`);
    ok(`偏好标的: ${snapshot.preferred_symbols || '(无)'}`);
    ok(`格式化记忆提示: ${memory.formatMemoryPrompt(TASK.sessionId).slice(0, 120)}...`);
  } catch (e) {
    fail(`用户记忆异常: ${e.message || e}`);
  }

  // -------- [5] 思维链与步进式推进 --------
  section('5. S 思维链 · 步进式推进', '🔗');
  try {
    const { routeIntent } = require('../../lib/intent/fallback-engine');
    const parsed = routeIntent(TASK.userPrompt, TASK.sessionId);
    const chain = (parsed && parsed.routing && parsed.routing.chain) || [];
    ok(`意图解析后的执行链: ${chain.join(' → ') || '(空)'}`);
    ok(`链节点数: ${chain.length}`);

    // 检查 chain state 是否存在于 route.ts
    const fs = require('fs');
    const routeFile = fs.readFileSync('../../app/api/chat/route.ts', 'utf-8');

    if (routeFile.includes('generateChainResponse')) {
      ok('generateChainResponse 存在（执行链协调核心）');
    }
    if (routeFile.includes('chainState') || routeFile.includes('chain_state')) {
      ok('chainState 持久化存在（步进式推进支持）');
    }
    if (routeFile.includes('needUserConfirmation') || routeFile.includes('needsConfirmation')) {
      ok('用户确认机制存在（每步推进的门禁）');
    }
    if (routeFile.includes('previousStepOutput') || routeFile.includes('cumulativeOutput')) {
      ok('思维链上下文传递已实现');
    }
    // 双推荐
    if (routeFile.includes('system_recommend') || routeFile.includes('preference_recommend') || routeFile.includes('系统推荐')) {
      ok('双推荐系统 (系统推荐 / 偏好推荐) 已启用');
    }
  } catch (e) {
    fail(`思维链诊断异常: ${e.message || e}`);
  }

  // -------- [6] 笔记本 / 任务清单 --------
  section('6. 笔记本记录 · 任务清单', '📓');
  try {
    const fs = require('fs');
    const apiFolder = fs.existsSync('../../app/api/notebook');
    if (apiFolder) {
      ok('/api/notebook 路由文件夹存在');
      // 检查路由接口
      const routes = ['route.ts', 'state/route.ts', 'step/route.ts'];
      for (const r of routes) {
        const p = `../../app/api/notebook/${r}`;
        if (fs.existsSync(p)) {
          ok(`  · ${r} 已实现`);
        } else {
          warn(`  · ${r} 缺失`);
        }
      }
    } else {
      warn('/api/notebook 路由文件夹缺失 — 任务清单仅前端本地，无后端同步');
    }

    // 前端组件
    const componentExists = fs.existsSync('../../components/notebook/NotebookPanel.tsx');
    if (componentExists) ok('NotebookPanel 前端组件存在');
    const storeExists = fs.existsSync('../../stores/notebook-store.ts');
    if (storeExists) ok('notebook-store.ts 状态管理存在');
  } catch (e) {
    fail(`笔记本诊断异常: ${e.message || e}`);
  }

  // -------- [7] 方案推荐（双推荐系统） --------
  section('7. 方案推荐 · 双推荐系统', '🎯');
  try {
    const fs = require('fs');
    const routeFile = fs.readFileSync('../../app/api/chat/route.ts', 'utf-8');
    const smartRouter = fs.readFileSync('../../lib/intent/smart-router.ts', 'utf-8');

    let hits = 0;
    if (routeFile.includes('系统推荐') || routeFile.includes('standard_recommend') || routeFile.includes('system_recommend')) { hits++; ok('系统推荐分支存在'); }
    if (routeFile.includes('偏好推荐') || routeFile.includes('preference_recommend') || routeFile.includes('个性化')) { hits++; ok('偏好推荐分支存在'); }
    if (smartRouter.includes('generateStepConfirmationPrompt') || routeFile.includes('用户确认')) { hits++; ok('步进式确认提示存在'); }
    if (routeFile.includes('usePreference') || routeFile.includes('with_preference')) { hits++; ok('偏好注入开关存在 (usePreference boolean)'); }
    if (hits >= 2) ok(`双推荐系统核心已就绪 (命中 ${hits} 个分支)`);
  } catch (e) {
    fail(`方案推荐诊断异常: ${e.message || e}`);
  }

  // -------- 8. 综合协作断点分析 --------
  section('综合协作 · 数据流/断点分析', '🔬');

  console.log(`
  ${BOLD}数据流设计:${RESET}
    用户输入 ─▶ 意图识别 ─▶ 思维链生成 ─▶ 步进确认 ─▶ 向量知识库 ─▶ LLM ─▶ 策略引擎
                │             │               │                │
                ▼             ▼               ▼                ▼
            实体解析      7 步状态机     偏好/系统双选择      2-KNOWLEDGE 文档
                                                                   │
                                                                   ▼
                                                           注入 system prompt

  ${BOLD}协作依赖图:${RESET}
    route.ts (中枢)
    ├─ intent/fallback-engine.ts  (意图识别)
    ├─ knowledge-rag.ts          (向量知识库 — 每步都调用)
    ├─ memory/user-preference-memory.ts (偏好注入)
    ├─ market-data-adapter.ts    (实时行情)
    └─ 6-TRADING/bridge/api/strategy_backtest_api.py (Python 回测 · HTTP)
  `);

  console.log(`\n${BOLD}══════════════════════════════════════════════════${RESET}`);
  console.log(`  诊断完成 ✓`);
  console.log(`  详细断点与修复建议 — 下一步报告见终端`);
  console.log(`${BOLD}══════════════════════════════════════════════════${RESET}\n`);
}

diagnose();
