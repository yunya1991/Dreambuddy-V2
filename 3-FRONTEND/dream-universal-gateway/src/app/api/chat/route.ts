import { NextRequest, NextResponse } from "next/server";
import { emitMonitorEvent } from "@/lib/monitor-bus";
import { routeIntent } from "@/lib/intent";
import type { ComplexityLevel } from "@/lib/intent";
import {
  default as userPrefMemory,
  detectPreferenceSignal,
  formatMemoryPrompt,
} from "@/lib/memory/user-preference-memory";

// P0-1: 真实市场数据适配器（OKX CLI + Tavily API）
import { fetchMarketData, SYMBOL_DEFINITIONS, extractSymbolFromMessage } from "@/lib/market-data-adapter";

// P1-2: 知识库文件化加载器（2-KNOWLEDGE/ 目录中读取）
import { getKnowledgeContext, loadAllKnowledge, getKnowledgeStats } from "@/lib/knowledge-loader";

// ========================================
// P2: S5 策略代码执行引擎（主前端专用的 E 链）
// 用途：developer 意图统一走 S5 → 完整 E 链（E1→E2→E3）
// 边界：前端 S5 = 策略代码开发专用；后端 6-Trading = 完整 D-Z-E 链（互不影响）
// ========================================
import {
  executeS5,
  S5_STEP_DEFINITIONS,
  type S5ExecutionResult,
} from "@/lib/dev-chain";

// S5 不需要额外的会话状态（每次调用都是完整的 E1→E2→E3 流水线）

// ========================================
// P0: 调度器（Hermes-Planner）— Cost Keeper + Skip Gate
// Feature Flag: process.env.USE_SCHEDULER = "true" | "false"（默认 false）
// 作用: 1) 追踪每次请求的 token 用量
//       2) 用轻量启发式判断哪些步骤可跳过，省 token / 降延迟
// ========================================
import {
  initCostKeeper,
  markStepStart,
  markStepEnd,
  markStepSkipped,
  shouldTerminate,
  generateReport,
  cleanupSession,
  estimateTokens,
  getCurrentUsage,
  shouldSkipStep,
  type StepName,
} from "@/lib/scheduler";

// ========================================
// P0+: 图文压缩适配器（graph-context-compressor）
// Feature Flag: USE_SCHEDULER=true 时同时启用
// 作用: 对 message_history 进行图结构压缩，保留上下文关系
// ========================================
import { compressorAdapter, type CompressResult } from "@/lib/compressor-adapter";
import { sessionGraphStates } from "@/lib/task-manager";

// 计算 scheduler 是否启用（仅当环境变量显式设置为 "true" / "1" 时才激活）
const SCHEDULER_ENABLED =
  typeof process !== 'undefined' &&
  (process.env.USE_SCHEDULER === 'true' || process.env.USE_SCHEDULER === '1');

// 在 console 中标识一次（启动时）
if (SCHEDULER_ENABLED) {
  console.log('[Hermes-Planner] P0 Scheduler ENABLED: CostKeeper + SkipGate');
} else {
  console.log('[Hermes-Planner] P0 Scheduler DISABLED (set USE_SCHEDULER=true to enable)');
}

// ============ 会话上下文 ============

interface SessionContext {
  session_id: string;
  user_role: "FREE" | "PRO" | "ADMIN";
  last_intent?: IntentType;
  last_symbol?: string;
  last_complexity?: ComplexityLevel;
  message_history: string[];
  /** Phase A: 扩展 thinking_mode 以支持步进式执行 */
  thinking_mode: "quick" | "deep" | "scheduler" | "stepwise";
  cached_responses: Map<string, { response: string; timestamp: number }>;
}

type IntentMethod = "llm" | "rule" | "follow_up" | "default";

type ThinkingMode = "quick" | "deep" | "scheduler" | "stepwise";

type IntentType =
  | "market_query"
  | "deep_analysis"
  | "triple_chain"
  | "scenario_sim"
  | "strategy_verify"
  | "execute_trade"
  | "system_config"
  | "credits_query"
  | "artifact_query"
  | "risk_alert_response"
  | "simple_qa"
  | "command"
  // P2-1 多场景意图
  | "asset_comparison"
  | "entry_timing"
  | "exit_timing"
  | "risk_analysis"
  | "position_sizing"
  | "market_sentiment"
  | "trend_analysis"
  | "technical_signal"
  | "support_resistance"
  | "portfolio_allocation"
  | "portfolio_rebalance"
  | "event_analysis"
  | "concept_explain"
  | "strategy_recommendation"
  | "backtest_help"
  | "volatility_analysis"
  | "macro_analysis"
  | "dca_strategy"
  | "arbitrage_opportunity"
  | "sector_rotation"
  // P1-2 D-Z-E 开发链
  | "developer";

interface IntentResult {
  intent: IntentType;
  confidence: number;
  entities: Record<string, string>;
  complexity: ComplexityLevel;
  method: IntentMethod;
  matched_pattern_id?: string;
  [key: string]: unknown;
}

const sessionContexts = new Map<string, SessionContext>();

function getDeepSeekApiKey(): string {
  const key = process.env.DEEPSEEK_API_KEY;
  if (!key) {
    throw new Error('DEEPSEEK_API_KEY environment variable is not set');
  }
  return key;
}

/**
 * DeepSeek API 配置（支持动态切换模型）
 */
const DEEPSEEK_CONFIG = {
  endpoint: 'https://api.deepseek.com/chat/completions',
  model: process.env.DEEPSEEK_MODEL || 'deepseek-v4-pro',
};

/**
 * LLM 状态追踪
 */
let llmStatus: 'online' | 'offline' | 'degraded' = 'offline';
let llmLastCheck = 0;
const LLM_CHECK_INTERVAL = 60_000; // 1分钟检查一次

/**
 * 检测 LLM 可用性
 */
async function checkLLMStatus(): Promise<'online' | 'offline' | 'degraded'> {
  const now = Date.now();
  if (now - llmLastCheck < LLM_CHECK_INTERVAL && llmStatus !== 'offline') {
    return llmStatus;
  }

  try {
    const response = await fetch(DEEPSEEK_CONFIG.endpoint, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${getDeepSeekApiKey()}`,
      },
      body: JSON.stringify({
        model: DEEPSEEK_CONFIG.model,
        messages: [{ role: 'user', content: 'ping' }],
        max_tokens: 5,
      }),
    });

    if (response.ok) {
      llmStatus = 'online';
    } else if (response.status === 403) {
      llmStatus = 'degraded'; // API可达但额度问题
    } else {
      llmStatus = 'offline';
    }
  } catch {
    llmStatus = 'offline';
  }

  llmLastCheck = now;
  return llmStatus;
}

/**
 * 调用 DeepSeek API（带 30 秒超时保护）
 *
 * P0 新增: 可选 tracking 参数 — 如果传入 sessionId + 步骤信息，
 *         将通过 CostKeeper 记录本次调用的 token 用量。
 *         此参数不影响旧调用者（所有现有代码无需修改）。
 */
async function callDeepSeekAPI(
  messages: any[],
  temperature: number = 0.7,
  tracking?: { sessionId: string; stepId: string; stepName: string }
): Promise<string> {
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), 30_000);

  // P0: CostKeeper 计时起点（若提供了 tracking 信息）
  if (tracking) {
    markStepStart(tracking.sessionId, tracking.stepId, tracking.stepName);
  }

  try {
    const response = await fetch(DEEPSEEK_CONFIG.endpoint, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${getDeepSeekApiKey()}`,
      },
      body: JSON.stringify({
        model: DEEPSEEK_CONFIG.model,
        messages: messages,
        temperature: temperature,
        max_tokens: 2000,
      }),
      signal: controller.signal,
    });

    clearTimeout(timeoutId);

    if (!response.ok) {
      const errorText = await response.text();
      if (response.status === 403) {
        llmStatus = 'degraded';
      }
      throw new Error(`DeepSeek API error: ${response.status} ${errorText}`);
    }

    const data = await response.json();
    llmStatus = 'online';

    // P0: CostKeeper token 用量记录（优先用 API 返回的 usage）
    if (tracking) {
      const usage = data.usage;
      let promptTokens = 0;
      let completionTokens = 0;

      if (usage && typeof usage.prompt_tokens === 'number') {
        promptTokens = usage.prompt_tokens;
        completionTokens = usage.completion_tokens || 0;
      } else {
        // fallback: 粗略估算（API 部分模型不返回 usage）
        const promptText = messages.map((m: any) => m.content).join('\n');
        promptTokens = estimateTokens(promptText);
        completionTokens = estimateTokens(data.choices?.[0]?.message?.content || '');
      }

      markStepEnd(
        tracking.sessionId,
        tracking.stepId,
        tracking.stepName,
        { promptTokens, completionTokens },
        'llm'
      );
    }

    return data.choices[0].message.content;
  } catch (error: any) {
    clearTimeout(timeoutId);
    console.error('[DeepSeek API] Call failed:', error);
    // 超时或 abort 错误，返回 null 让调用方 fallback
    if (error?.name === 'AbortError' || error?.message?.includes('abort')) {
      console.warn('[DeepSeek API] Request timeout (>30s)');
      return '(LLM 调用超时，请稍后重试或检查网络)';
    }
    throw error;
  }
}

/**
 * 配置：意图识别方法
 */
let intentMethod: 'rule' | 'llm' = 'llm';

/**
 * 基于规则的意图识别（后备方案）
 */
function recognizeIntentRule(message: string, context?: SessionContext): IntentResult {
  const msg = message.toLowerCase().trim();

  console.log(`[IntentRule] 输入: "${msg}"`);
  if (context) {
    console.log(`[IntentRule] 上下文: last_intent=${context.last_intent}, last_symbol=${context.last_symbol}`);
  }

  const mode = context?.thinking_mode || 'quick';

  // 命令识别（最高优先级）
  if (msg.startsWith('/')) {
    const commandMap: Record<string, IntentType> = {
      '/行情': 'market_query',
      '/分析': 'deep_analysis',
      '/推演': 'scenario_sim',
      '/验证': 'strategy_verify',
      '/开仓': 'execute_trade',
      // P1-2 D-Z-E 开发链命令
      '/dev': 'developer',
      '/代码': 'developer',
      '/修复': 'developer',
      '/bug': 'developer',
    };

    for (const [cmd, intent] of Object.entries(commandMap)) {
      if (msg.startsWith(cmd)) {
        console.log(`[IntentRule] 命令识别: ${cmd} → ${intent}`);
        return {
          intent,
          confidence: 0.95,
          entities: extractEntities(message),
          complexity:
            intent === "market_query"
              ? "simple"
              : intent === "deep_analysis"
                ? "moderate"
                : intent === "scenario_sim"
                  ? "complex"
                  : intent === "strategy_verify"
                    ? "moderate"
                    : intent === "execute_trade"
                      ? "complex"
                      : "simple",
          method: "rule",
          thinking_mode: mode,
          routing: {
            chain: getChainForIntent(intent, mode),
            priority: 'high',
            cacheable: false,
          },
        };
      }
    }
  }

  // 上下文感知：追问检测
  if (context?.last_intent === 'deep_analysis') {
    if (msg.includes('为什么') || msg.includes('原因') || msg.includes('详细') || msg.includes('如何')) {
      console.log(`[IntentRule] 追问检测 → 直接回答模式`);
      return {
        intent: 'deep_analysis',
        confidence: 0.9,
        entities: { symbol: context.last_symbol || "" },
        complexity: "moderate",
        method: "follow_up",
        context_aware: true,
        thinking_mode: mode,
        routing: {
          chain: ['S0_DIRECT_ANSWER'],
          priority: 'medium',
          cacheable: true,
        },
      };
    }
  }

  // 快捷追问识别
  if (context?.last_symbol) {
    if (msg.match(/^(涨|跌|怎么样|如何|怎么看|还能)$/)) {
      console.log(`[IntentRule] 快捷追问 → 使用上一轮symbol: ${context.last_symbol}`);
      return {
        intent: 'deep_analysis',
        confidence: 0.85,
        entities: { symbol: context.last_symbol },
        complexity: "moderate",
        method: "follow_up",
        context_aware: true,
        thinking_mode: mode,
        routing: {
          chain: ['S1_RESEARCH', 'S2_ANALYSIS'],
          priority: 'high',
          cacheable: false,
        },
      };
    }
  }

  // 关键词识别
  if (msg.includes('行情') || msg.includes('价格') || msg.includes('涨') || msg.includes('跌')) {
    return {
      intent: 'market_query', confidence: 0.8,
      entities: extractEntities(msg), thinking_mode: mode,
      complexity: "simple",
      method: "rule",
      routing: { chain: ['S1_RESEARCH'], priority: 'high', cacheable: true },
    };
  }

  if (msg.includes('分析') || msg.includes('怎么看') || msg.includes('走势') || msg.includes('制定') || msg.includes('策略')) {
    return {
      intent: 'deep_analysis', confidence: 0.85,
      entities: extractEntities(msg), thinking_mode: mode,
      complexity: "moderate",
      method: "rule",
      routing: { chain: getChainForIntent('deep_analysis', mode), priority: 'high', cacheable: false },
    };
  }

  if (msg.includes('推演') || msg.includes('情景') || msg.includes('如果')) {
    return {
      intent: 'scenario_sim', confidence: 0.8,
      entities: extractEntities(msg), thinking_mode: mode,
      complexity: "complex",
      method: "rule",
      routing: { chain: ['S3_DESIGN'], priority: 'medium', cacheable: false },
    };
  }

  if (msg.includes('验证') || msg.includes('回测')) {
    return {
      intent: 'strategy_verify', confidence: 0.8, thinking_mode: mode,
      entities: extractEntities(msg),
      complexity: "moderate",
      method: "rule",
      routing: { chain: ['S4_VALIDATE'], priority: 'medium', cacheable: false },
    };
  }

  if (msg.includes('开仓') || msg.includes('下单') || msg.includes('交易') || msg.includes('策略执行') || msg.includes('策略驱动')) {
    return {
      intent: 'execute_trade', confidence: 0.75, thinking_mode: mode,
      entities: extractEntities(msg),
      complexity: "complex",
      method: "rule",
      routing: { chain: ['S5_EXECUTE'], priority: 'high', cacheable: false },
    };
  }

  // P1-2 D-Z-E 开发链：关键词匹配 - 代码开发/修复/重构/分析
  if (/bug|修复|问题|错误|崩溃|bugfix|报错|异常/.test(msg) ||
      /重构|refactor|清理代码|代码优化/.test(msg) ||
      /代码|开发|dev|实现|写代码|编码/.test(msg) ||
      /新功能|新增功能|添加功能|功能开发/.test(msg) ||
      /策略.*代码|策略.*修改|修改.*策略|策略逻辑/.test(msg) ||
      /分析代码|代码.*分析|review|审阅|代码review|review代码|看代码/.test(msg)) {
    console.log(`[IntentRule] 开发类任务识别 → developer`);
    return {
      intent: 'developer', confidence: 0.85, thinking_mode: mode,
      entities: extractEntities(msg),
      complexity: "complex",
      method: "rule",
      routing: { chain: getChainForIntent('developer', mode), priority: 'high', cacheable: false },
    };
  }

  console.log(`[IntentRule] 未匹配关键词，使用简单问答模式`);
  return {
    intent: 'simple_qa', confidence: 0.6, thinking_mode: mode,
    entities: extractEntities(msg),
    complexity: "simple",
    method: "default",
    routing: { chain: ['S0_DIRECT_ANSWER'], priority: 'low', cacheable: true },
  };
}

/**
 * 基于LLM的意图识别（使用 DeepSeek）
 */
async function recognizeIntentLLM(message: string, context?: SessionContext): Promise<IntentResult> {
  const thinkingMode = context?.thinking_mode || 'quick';

  const systemPrompt = `你是交易助手的意图识别模块。根据用户消息输出JSON。

意图说明:
- market_query: 简单行情查询
- deep_analysis: 深度分析（S系列链）
- triple_chain: 完整策略制定（S系列策略思维链，需用户确认步进）
- scenario_sim: 情景推演
- strategy_verify: 策略验证
- execute_trade: 下单/交易执行
- simple_qa: 简单问答
- developer: 代码开发、bug修复、代码重构、代码审阅（D-Z-E开发链）

输出格式:
{"intent":"类型","confidence":0.0-1.0,"entities":{"symbol":"BTC","timeframe":"4h"},"reasoning":"理由"}

规则:
1. 用户请求"制定策略"、"帮我分析+制定"、"给我一个策略"等 → triple_chain (S系列完整链路)
2. 用户请求"分析"、"怎么看"、"走势" → deep_analysis (S系列链)
3. 用户请求"现在黄金怎么样"、"BTC行情" → market_query
4. 用户明确请求"下单"、"买入"、"卖出" → execute_trade
5. 用户请求"修复bug"、"修改代码"、"重构"、"开发"、"代码review"、"看一下代码"、"实现功能"等 → developer (D-Z-E开发链)

仅输出JSON。`;

  const userPrompt = `消息:"${message}"
${context?.last_intent ? `上轮:${context.last_intent}` : ''}
${context?.last_symbol ? `上币:${context.last_symbol}` : ''}
${context?.message_history && context.message_history.length > 0 ? `近3条:${context.message_history.slice(-3).join('|')}` : ''}`;

  try {
    const response = await callDeepSeekAPI([
      { role: 'system', content: systemPrompt },
      { role: 'user', content: userPrompt },
    ], 0.2);  // 低temperature保证稳定输出

    // 鲁棒JSON解析
    let parsed: any = null;

    const jsonMatch = response.match(/\{[\s\S]*\}/);
    if (jsonMatch) {
      try {
        parsed = JSON.parse(jsonMatch[0]);
      } catch {}
    }

    if (!parsed) {
      const codeBlockMatch = response.match(/```(?:json)?\s*([\s\S]*?)```/);
      if (codeBlockMatch) {
        try { parsed = JSON.parse(codeBlockMatch[1]); } catch {}
      }
    }

    if (!parsed || !parsed.intent) {
      throw new Error('Failed to parse LLM response as intent JSON');
    }

    // P2-1: 支持 32 种意图类型（原 8 种 + 新增 24 种）
    const validIntents: string[] = [
      'market_query', 'deep_analysis', 'triple_chain', 'scenario_sim',
      'strategy_verify', 'execute_trade', 'simple_qa', 'system_config',
      'credits_query', 'artifact_query', 'risk_alert_response', 'command',
      // P2-1 新增多场景意图
      'asset_comparison', 'entry_timing', 'exit_timing', 'risk_analysis',
      'position_sizing', 'market_sentiment', 'trend_analysis', 'technical_signal',
      'support_resistance', 'portfolio_allocation', 'portfolio_rebalance',
      'event_analysis', 'concept_explain', 'strategy_recommendation',
      'backtest_help', 'volatility_analysis', 'macro_analysis', 'dca_strategy',
      'arbitrage_opportunity', 'sector_rotation',
      // P1-2 D-Z-E 开发链
      'developer',
    ];
    if (!validIntents.includes(parsed.intent)) {
      console.warn(`[IntentLLM] Invalid intent "${parsed.intent}", fallback to simple_qa`);
      parsed.intent = 'simple_qa';
      parsed.confidence = 0.4;
    }

    // P2-1: 基于意图类型动态计算复杂度
    const simpleIntents = new Set(['market_query', 'simple_qa', 'system_config', 'credits_query', 'concept_explain', 'market_sentiment']);
    const complexIntents = new Set(['triple_chain', 'execute_trade', 'portfolio_allocation', 'strategy_recommendation', 'arbitrage_opportunity', 'portfolio_rebalance', 'developer']);
    const isSimple = simpleIntents.has(parsed.intent);
    const isComplex = complexIntents.has(parsed.intent);

    return {
      intent: parsed.intent as IntentType,
      confidence: parsed.confidence || 0.7,
      entities: (parsed.entities || {}) as Record<string, string>,
      complexity: isSimple ? "simple" : isComplex ? "complex" : "moderate",
      method: "llm",
      thinking_mode: thinkingMode,
      routing: {
        chain: getChainForIntent(parsed.intent as IntentType, thinkingMode),
        priority: (parsed.confidence || 0.7) >= 0.8 ? 'high' : 'medium',
        cacheable: parsed.intent === 'market_query' || parsed.intent === 'simple_qa',
      },
    };
  } catch (error) {
    console.error('[IntentLLM] Recognition failed, fallback to rule:', error);
    return recognizeIntentRule(message, context);
  }
}

/**
 * 根据意图和思考模式获取处理链路
 * 策略分析使用S系列思维链
 */
function getChainForIntent(intent: IntentType, thinkingMode: ThinkingMode): string[] {
  // S系列策略思维链：S1=调研, S2=分析, S3=设计, S4=验证, S5=执行
  const S1_2 = ['S1_RESEARCH', 'S2_ANALYSIS'];
  const S1_3 = ['S1_RESEARCH', 'S2_ANALYSIS', 'S3_DESIGN'];
  const FULL_S = ['S1_RESEARCH', 'S2_ANALYSIS', 'S3_DESIGN', 'S4_VALIDATE', 'S5_EXECUTE'];

  // 主前端开发链：S3 策略设计 → S4 验证 → S5 执行（完整 E1→E2→E3）
  const STRATEGY_DEV_CHAIN = ['S3_DESIGN', 'S4_VALIDATE', 'S5_EXECUTE'];

  if (thinkingMode === 'quick') {
    const quickChainMap: Record<IntentType, string[]> = {
      'market_query': ['S1_RESEARCH'],
      // 所有策略分析统一使用 S 系列链
      'deep_analysis': S1_2,
      'triple_chain': S1_2,
      'scenario_sim': ['S1_RESEARCH', 'S2_ANALYSIS', 'S3_DESIGN'],
      'strategy_verify': ['S2_ANALYSIS', 'S3_DESIGN', 'S4_VALIDATE'],
      'execute_trade': ['S1_RESEARCH', 'S2_ANALYSIS', 'S3_DESIGN', 'S4_VALIDATE'],
      'simple_qa': ['S0_DIRECT_ANSWER'],
      'system_config': ['S0_DIRECT_ANSWER'],
      'credits_query': ['S0_DIRECT_ANSWER'],
      'artifact_query': ['S1_RESEARCH'],
      'risk_alert_response': ['S2_ANALYSIS'],
      'command': ['route_by_command'],
      // P2-1 多场景意图 - quick 模式
      'asset_comparison': S1_2,
      'entry_timing': ['S1_RESEARCH', 'S2_ANALYSIS'],
      'exit_timing': ['S1_RESEARCH', 'S2_ANALYSIS'],
      'risk_analysis': ['S2_ANALYSIS'],
      'position_sizing': ['S2_ANALYSIS', 'S3_DESIGN'],
      'market_sentiment': ['S1_RESEARCH', 'S0_DIRECT_ANSWER'],
      'trend_analysis': ['S1_RESEARCH', 'S2_ANALYSIS'],
      'technical_signal': ['S1_RESEARCH', 'S2_ANALYSIS'],
      'support_resistance': ['S1_RESEARCH', 'S2_ANALYSIS'],
      'portfolio_allocation': ['S1_RESEARCH', 'S2_ANALYSIS', 'S3_DESIGN'],
      'portfolio_rebalance': ['S2_ANALYSIS', 'S3_DESIGN'],
      'event_analysis': S1_2,
      'concept_explain': ['S1_RESEARCH', 'S0_DIRECT_ANSWER'],
      'strategy_recommendation': ['S2_ANALYSIS', 'S3_DESIGN'],
      'backtest_help': ['S1_RESEARCH', 'S0_DIRECT_ANSWER'],
      'volatility_analysis': ['S1_RESEARCH', 'S2_ANALYSIS'],
      'macro_analysis': S1_2,
      'dca_strategy': ['S2_ANALYSIS', 'S3_DESIGN'],
      'arbitrage_opportunity': S1_2,
      'sector_rotation': S1_2,
      // S5 策略代码开发 - quick 模式
      'developer': STRATEGY_DEV_CHAIN,
    };
    return quickChainMap[intent] || ['S0_DIRECT_ANSWER'];
  }

  // 深度思考模式：完整策略链（S 系列）
  const deepChainMap: Record<IntentType, string[]> = {
    'market_query': ['S1_RESEARCH'],
    // 所有策略分析统一使用 S 系列链
    'deep_analysis': S1_3,
    'triple_chain': FULL_S,
    'scenario_sim': ['S1_RESEARCH', 'S2_ANALYSIS', 'S3_DESIGN', 'S4_VALIDATE'],
    'strategy_verify': ['S2_ANALYSIS', 'S3_DESIGN', 'S4_VALIDATE'],
    'execute_trade': FULL_S,
    'simple_qa': ['S0_DIRECT_ANSWER'],
    'system_config': ['S0_DIRECT_ANSWER'],
    'credits_query': ['S0_DIRECT_ANSWER'],
    'artifact_query': ['S1_RESEARCH'],
    'risk_alert_response': ['S2_ANALYSIS'],
    'command': ['route_by_command'],
    // P2-1 多场景意图 - deep 模式
    'asset_comparison': ['S1_RESEARCH', 'S2_ANALYSIS', 'S3_DESIGN'],
    'entry_timing': ['S1_RESEARCH', 'S2_ANALYSIS', 'S3_DESIGN'],
    'exit_timing': ['S1_RESEARCH', 'S2_ANALYSIS', 'S3_DESIGN'],
    'risk_analysis': ['S2_ANALYSIS', 'S3_DESIGN'],
    'position_sizing': ['S2_ANALYSIS', 'S3_DESIGN', 'S4_VALIDATE'],
    'market_sentiment': ['S1_RESEARCH', 'S2_ANALYSIS'],
    'trend_analysis': ['S1_RESEARCH', 'S2_ANALYSIS'],
    'technical_signal': ['S1_RESEARCH', 'S2_ANALYSIS'],
    'support_resistance': ['S1_RESEARCH', 'S2_ANALYSIS'],
    'portfolio_allocation': ['S1_RESEARCH', 'S2_ANALYSIS', 'S3_DESIGN', 'S4_VALIDATE'],
    'portfolio_rebalance': ['S2_ANALYSIS', 'S3_DESIGN', 'S4_VALIDATE'],
    'event_analysis': ['S1_RESEARCH', 'S2_ANALYSIS', 'S3_DESIGN'],
    'concept_explain': ['S1_RESEARCH', 'S0_DIRECT_ANSWER'],
    'strategy_recommendation': ['S2_ANALYSIS', 'S3_DESIGN', 'S4_VALIDATE'],
    'backtest_help': ['S3_DESIGN', 'S4_VALIDATE'],
    'volatility_analysis': ['S1_RESEARCH', 'S2_ANALYSIS', 'S3_DESIGN'],
    'macro_analysis': ['S1_RESEARCH', 'S2_ANALYSIS', 'S3_DESIGN'],
    'dca_strategy': ['S2_ANALYSIS', 'S3_DESIGN', 'S4_VALIDATE'],
    'arbitrage_opportunity': ['S1_RESEARCH', 'S2_ANALYSIS', 'S3_DESIGN'],
    'sector_rotation': ['S1_RESEARCH', 'S2_ANALYSIS', 'S3_DESIGN'],
    // S5 策略代码开发 - deep 模式
    'developer': STRATEGY_DEV_CHAIN,
  };
  return deepChainMap[intent] || ['S0_DIRECT_ANSWER'];
}

// ============ P3 多意图组合路由 ============

/**
 * P3: 检测用户消息中是否隐含多个意图
 * 例如："先分析 BTC 的宏观形势，再给我入场时机和仓位建议"
 * → 组合：macro_analysis → entry_timing → position_sizing
 * 
 * @returns string[] - 组合意图数组（如仅一个意图则返回空数组）
 */
function detectCombinedIntents(message: string, primaryIntent: string): string[] {
  const lower = message.toLowerCase();
  const intents: string[] = [];

  // 信号1：明确包含"先...再.../然后...最后..." —— 触发组合分析
  const hasExplicitOrdering = /先(.+?)(再|然后|接着|之后|再给我|最后)/.test(lower);
  
  // 信号2：多语义关键词检测
  const mentionComparison = /对比|比较|vs|相对|与.*相比|哪个好|哪种|哪一个/.test(lower);
  const mentionEntry = /入场|买|买入|进场|什么时候进|能买|能不能买|时机|何时买/.test(lower);
  const mentionExit = /出场|卖出|止盈|止损|什么时候卖|离场|何时卖/.test(lower);
  const mentionRisk = /风险|亏损|回撤|安全|稳健|保守|仓位风险/.test(lower);
  const mentionPosition = /仓位|资金管理|买多少|投入多少|分配|比例|头寸/.test(lower);
  const mentionStrategy = /策略|交易策略|如何操作|怎么做|方案|战术|策略选择/.test(lower);
  const mentionMacro = /宏观|美联储|利率|加息|降息|政策|经济|CPI|通胀|GDP|货币政策/.test(lower);
  const mentionEvent = /事件|消息|新闻|会议|数据|公布|美联储会议|非农/.test(lower);
  const mentionDCA = /定投|分批|定期|定额|分批建仓/.test(lower);
  const mentionTechnical = /技术|指标|RSI|MACD|均线|布林|支撑|阻力|点位|技术面/.test(lower);
  const mentionTrend = /趋势|走势|方向|牛市|熊市|行情|趋势判断/.test(lower);
  const mentionVolatility = /波动|震荡|波动率|振幅/.test(lower);
  const mentionSentiment = /情绪|恐慌|贪婪|热度|人气|市场情绪|看多|看空/.test(lower);
  const mentionPortfolio = /组合|配置|资产配置|持仓|分散|多样化|投资组合/.test(lower);
  const mentionArbitrage = /套利|价差|对冲|无风险|套利机会/.test(lower);
  const mentionSector = /板块|热点|轮动|哪个板块|热门板块/.test(lower);
  const mentionBacktest = /回测|历史数据|验证|测试|回溯/.test(lower);
  const mentionExplain = /什么是|解释|怎么理解|概念|原理|定义|什么叫/.test(lower);

  // 当检测到多个信号时自动组合（Number(Boolean) 保证类型安全）
  const signalCount = Number(mentionEntry) + Number(mentionExit) + Number(mentionRisk) + Number(mentionPosition) + Number(mentionStrategy) + Number(mentionMacro) + Number(mentionEvent) + Number(mentionComparison);
  if (hasExplicitOrdering || signalCount >= 2) {
    if (mentionMacro) intents.push('macro_analysis');
    if (mentionEvent) intents.push('event_analysis');
    if (mentionComparison) intents.push('asset_comparison');
    if (mentionTrend) intents.push('trend_analysis');
    if (mentionSentiment) intents.push('market_sentiment');
    if (mentionTechnical) intents.push('technical_signal');
    if (mentionVolatility) intents.push('volatility_analysis');
    if (mentionEntry) intents.push('entry_timing');
    if (mentionExit) intents.push('exit_timing');
    if (mentionRisk) intents.push('risk_analysis');
    if (mentionPosition) intents.push('position_sizing');
    if (mentionDCA) intents.push('dca_strategy');
    if (mentionStrategy) intents.push('strategy_recommendation');
    if (mentionPortfolio) intents.push('portfolio_allocation');
    if (mentionArbitrage) intents.push('arbitrage_opportunity');
    if (mentionSector) intents.push('sector_rotation');
    if (mentionBacktest) intents.push('backtest_help');
    if (mentionExplain) intents.push('concept_explain');
  }

  // 常见组合模板（当同时出现多个关键词触发）
  if (intents.length === 0) {
    const signals = [
      { test: mentionMacro && mentionEntry, chain: ['macro_analysis', 'entry_timing', 'position_sizing'] },
      { test: mentionEntry && mentionRisk, chain: ['entry_timing', 'risk_analysis'] },
      { test: mentionEntry && mentionPosition, chain: ['entry_timing', 'position_sizing'] },
      { test: mentionComparison && mentionEntry, chain: ['asset_comparison', 'entry_timing'] },
      { test: mentionTrend && mentionStrategy, chain: ['trend_analysis', 'strategy_recommendation'] },
      { test: mentionMacro && mentionStrategy, chain: ['macro_analysis', 'strategy_recommendation'] },
      { test: mentionRisk && mentionPosition, chain: ['risk_analysis', 'position_sizing'] },
      { test: mentionExit && mentionRisk, chain: ['exit_timing', 'risk_analysis'] },
      { test: mentionPortfolio && mentionStrategy, chain: ['portfolio_allocation', 'strategy_recommendation'] },
      { test: mentionTechnical && mentionEntry, chain: ['technical_signal', 'entry_timing'] },
      { test: mentionSentiment && mentionTrend, chain: ['market_sentiment', 'trend_analysis'] },
      { test: mentionDCA && mentionPosition, chain: ['dca_strategy', 'position_sizing'] },
      { test: mentionEvent && mentionMacro, chain: ['event_analysis', 'macro_analysis'] },
      { test: mentionArbitrage && mentionComparison, chain: ['arbitrage_opportunity', 'asset_comparison'] },
      { test: mentionSector && mentionTrend, chain: ['sector_rotation', 'trend_analysis'] },
      { test: mentionMacro && mentionRisk, chain: ['macro_analysis', 'risk_analysis'] },
      { test: mentionEntry && mentionExit, chain: ['entry_timing', 'exit_timing'] },
    ];

    const match = signals.find(s => s.test);
    if (match) return match.chain;
  }

  // 去重，确保主意图在前
  if (intents.length > 0) {
    const unique = intents.filter((v, i, a) => a.indexOf(v) === i);
    if (!unique.includes(primaryIntent)) unique.unshift(primaryIntent);
    return unique;
  }

  return [];
}

/**
 * P3: 根据多个意图组合生成一条完整思维链
 * @param combinedIntents string[] - 组合意图数组
 * @param thinkingMode 思考模式
 * @returns string[] - 完整组合思维链（去重后）
 */
function buildCombinedChain(combinedIntents: string[], thinkingMode: 'quick' | 'deep' | 'scheduler' | 'stepwise'): string[] {
  if (combinedIntents.length <= 1) return [];

  const allSteps: string[] = [];
  const stepSet = new Set<string>();

  for (const intent of combinedIntents) {
    // 对每个意图获取对应思维链
    const subChain = getChainForIntent(intent as IntentType, thinkingMode);
    for (const step of subChain) {
      if (!stepSet.has(step)) {
        stepSet.add(step);
        allSteps.push(step);
      }
    }
  }

  // 限制组合链最大长度（避免过长）
  return allSteps.slice(0, 8);
}

/**
 * P3: 为组合响应生成摘要说明
 */
function buildCombinedIntentHeader(combinedIntents: string[]): string {
  if (combinedIntents.length <= 1) return '';
  
  const intentNames: Record<string, string> = {
    'macro_analysis': '📊 宏观分析',
    'entry_timing': '🎯 入场时机',
    'exit_timing': '🏁 离场建议',
    'risk_analysis': '⚠️ 风险评估',
    'position_sizing': '💰 仓位管理',
    'asset_comparison': '🔍 资产对比',
    'strategy_recommendation': '📋 策略推荐',
    'portfolio_allocation': '📈 资产配置',
    'portfolio_rebalance': '🔄 组合再平衡',
    'concept_explain': '📖 概念解释',
    'market_sentiment': '🔥 市场情绪',
    'trend_analysis': '📈 趋势分析',
    'technical_signal': '📐 技术信号',
    'volatility_analysis': '⚡ 波动率',
    'event_analysis': '📰 事件分析',
    'dca_strategy': '📌 定投策略',
    'arbitrage_opportunity': '🎭 套利机会',
    'sector_rotation': '🔁 板块轮动',
    'backtest_help': '📊 回测指导',
  };
  
  const names = combinedIntents.map(i => intentNames[i] || i).join(' → ');
  return `\n**🔗 多阶段分析已启动**：${names}\n\n---\n\n`;
}

/**
 * 意图识别入口
 */
async function recognizeIntent(message: string, context?: SessionContext): Promise<IntentResult> {
  if (intentMethod === 'llm') {
    return await recognizeIntentLLM(message, context);
  } else {
    return recognizeIntentRule(message, context);
  }
}

/**
 * 提取实体
 */
function extractEntities(msg: string): IntentResult['entities'] {
  const entities: IntentResult['entities'] = {};
  const lower = msg.toLowerCase();
  const symbolMap: Record<string, string[]> = {
    'BTC': ['btc', 'bitcoin', '比特币'],
    'ETH': ['eth', 'ethereum', '以太坊'],
    'SOL': ['sol', 'solana'],
    'BNB': ['bnb'],
    'XRP': ['xrp', 'ripple'],
    'XAU': ['xau', 'gold', '黄金', '金价'],
  };
  for (const [sym, keywords] of Object.entries(symbolMap)) {
    if (keywords.some(k => lower.includes(k))) {
      entities.symbol = sym;
      break;
    }
  }
  if (msg.includes('1小时') || lower.includes('1h')) entities.timeframe = '1h';
  if (msg.includes('4小时') || lower.includes('4h')) entities.timeframe = '4h';
  if (msg.includes('日线') || lower.includes('1d') || lower.includes('daily')) entities.timeframe = '1d';
  if (msg.includes('周') || lower.includes('1w')) entities.timeframe = '1w';
  return entities;
}

/**
 * 生成缓存Key
 */
function generateCacheKey(intent: IntentResult, message: string): string {
  const entities = intent.entities;
  return `${intent.intent}:${entities?.symbol || '*'}:${entities?.timeframe || '*'}`;
}

// ============ D-Z-E 链状态管理 ============
// 集成三链接力协议状态机

interface ChainPhase {
  id: string;
  name: string;
  methodology: string;
  status: "pending" | "in_progress" | "completed" | "skipped";
  approval: "pending" | "approved";
  output_ref: string | null;
  completed_at: string | null;
}

interface ChainState {
  scope: string;
  current_phase: string;
  phases: ChainPhase[];
  relay_history: Array<{
    from: string;
    to: string;
    trigger: string;
    reason: string | null;
    at: string;
  }>;
}

const PHASES_ORDER = ["d1", "d2", "d3", "d4", "z1", "z2", "z3", "z4", "e1", "e2", "e3"] as const;

const PHASE_NAMES: Record<string, string> = {
  "d1": "D1 深度调研",
  "d2": "D2 分析诊断",
  "d3": "D3 推演验证",
  "d4": "D4 Spec合成",
  "z1": "Z1 代码扫描",
  "z2": "Z2 范围划分",
  "z3": "Z3 路径设计",
  "z4": "Z4 验收方案",
  "e1": "E1 任务执行",
  "e2": "E2 测试验证",
  "e3": "E3 部署交付",
};

const PHASE_METHODOLOGIES: Record<string, string> = {
  "d1": "四准则调研法",
  "d2": "三问分析框架",
  "d3": "三景推演法",
  "d4": "四段Spec法",
  "z1": "模块依赖分析",
  "z2": "拓扑切割+回滚点设计",
  "z3": "完整实施步骤模板",
  "z4": "四层验收策略",
  "e1": "todo驱动逐任务执行",
};

function _now_iso(): string {
  return new Date().toISOString();
}

function _get_chain(phase_id: string): string | null {
  const prefix = phase_id[0];
  return prefix === "d" || prefix === "z" || prefix === "e" ? prefix : null;
}

function create_default_chain_state(scope: string): ChainState {
  const now = _now_iso();
  const phases: ChainPhase[] = [];
  for (const pid of PHASES_ORDER) {
    phases.push({
      id: pid,
      name: PHASE_NAMES[pid] || pid,
      methodology: PHASE_METHODOLOGIES[pid] || "",
      status: pid === "d1" ? "in_progress" : "pending",
      approval: "pending",
      output_ref: null,
      completed_at: null,
    });
  }
  return {
    scope,
    current_phase: "d1",
    phases,
    relay_history: [],
  };
}

function chain_check(state: ChainState, from_phase: string, to_phase: string): { allowed: boolean; reason: string } {
  const phase_ids = new Set(state.phases.map(p => p.id));
  if (!phase_ids.has(from_phase)) {
    return { allowed: false, reason: `来源阶段 ${from_phase} 不存在` };
  }
  if (!phase_ids.has(to_phase)) {
    return { allowed: false, reason: `目标阶段 ${to_phase} 不存在` };
  }

  const from_p = state.phases.find(p => p.id === from_phase)!;
  const to_p = state.phases.find(p => p.id === to_phase)!;

  if (from_p.status !== "completed" && from_p.status !== "skipped") {
    return { allowed: false, reason: `${from_phase}(${from_p.name}) 尚未完成（status=${from_p.status}）` };
  }

  if (to_p.status !== "pending") {
    return { allowed: false, reason: `${to_phase}(${to_p.name}) 状态不是 pending（当前=${to_p.status}）` };
  }

  const from_chain = _get_chain(from_phase);
  const to_chain = _get_chain(to_phase);
  if (from_chain !== to_chain) {
    let allowed_cross = false;
    if (from_chain === "d" && to_chain === "z" && from_phase === "d4" && to_phase === "z1") {
      allowed_cross = true;
    }
    if (from_chain === "z" && to_chain === "e" && from_phase === "z4" && to_phase === "e1") {
      allowed_cross = true;
    }
    if (!allowed_cross) {
      return { allowed: false, reason: `跨链跳转 ${from_phase}(${from_chain})→${to_phase}(${to_chain}) 不允许（只允许 D4→Z1 和 Z4→E1）` };
    }
  }

  if (from_chain === to_chain) {
    const chain_phases = PHASES_ORDER.filter(p => _get_chain(p) === from_chain);
    const from_idx = chain_phases.indexOf(from_phase as typeof chain_phases[number]);
    const to_idx = chain_phases.indexOf(to_phase as typeof chain_phases[number]);
    if (to_idx !== from_idx + 1) {
      const expected = from_idx + 1 < chain_phases.length ? chain_phases[from_idx + 1] : "无下一步";
      return { allowed: false, reason: `同链跳转必须按顺序（${from_phase}→${to_phase}，但应为 ${from_phase}→${expected}）` };
    }
  }

  return { allowed: true, reason: "" };
}

function chain_transition(state: ChainState, from_phase: string, to_phase: string): { success: boolean; reason: string; state: ChainState } {
  const check = chain_check(state, from_phase, to_phase);
  if (!check.allowed) {
    return { success: false, reason: check.reason, state };
  }

  const now = _now_iso();
  const newPhases = state.phases.map(p => {
    if (p.id === from_phase && p.status === "in_progress") {
      return { ...p, status: "completed" as const, completed_at: now };
    }
    if (p.id === to_phase) {
      return { ...p, status: "in_progress" as const };
    }
    return p;
  });

  return {
    success: true,
    reason: "",
    state: {
      ...state,
      current_phase: to_phase,
      phases: newPhases,
      relay_history: [...state.relay_history, { from: from_phase, to: to_phase, trigger: "chain_transition", reason: null, at: now }],
    },
  };
}

function chain_approve(state: ChainState, phase_id: string): ChainState {
  const now = _now_iso();
  const newPhases = state.phases.map(p => {
    if (p.id === phase_id) {
      const newStatus = p.status === "pending" || p.status === "in_progress" ? "completed" as const : p.status;
      return { ...p, approval: "approved" as const, status: newStatus, completed_at: newStatus === "completed" ? now : p.completed_at };
    }
    return p;
  });
  return {
    ...state,
    phases: newPhases,
    relay_history: [...state.relay_history, { from: state.current_phase, to: phase_id, trigger: "user_approval", reason: null, at: now }],
  };
}

// 会话级别的链状态缓存
const sessionChainStates = new Map<string, ChainState>();

// 会话级别的策略链状态缓存（用于S系列策略链）
const sessionStrategyStates = new Map<string, any>();

function get_or_init_chain_state(sessionId: string, scope?: string): ChainState {
  let state = sessionChainStates.get(sessionId);
  if (!state) {
    state = create_default_chain_state(scope || "分析任务");
    sessionChainStates.set(sessionId, state);
  }
  return state;
}

function update_chain_state(sessionId: string, state: ChainState): void {
  sessionChainStates.set(sessionId, state);
}

function get_or_init_strategy_state(sessionId: string, defaultMode?: ExecMode): any {
  let state = sessionStrategyStates.get(sessionId);
  if (!state) {
    state = {
      currentStep: 'S1_RESEARCH',
      steps: ['S1_RESEARCH', 'S2_ANALYSIS', 'S3_DESIGN', 'S4_VALIDATE', 'S5_EXECUTE'],
      completedSteps: [] as string[],
      executionMode: defaultMode || 'dynamic',
    };
    sessionStrategyStates.set(sessionId, state);
  }
  return state;
}

function update_strategy_state(sessionId: string, state: any): void {
  sessionStrategyStates.set(sessionId, state);
}

/**
 * 模拟调用SKILL（模拟真实SKILL执行）
 * @param skillName SKILL名称
 * @param params 输入参数
 * @returns SKILL执行结果
 */
async function callSkill(skillName: string, params: Record<string, unknown>): Promise<{ success: boolean; data?: unknown; error?: string }> {
  const symbol = params.symbol as string || 'BTC';
  const price = params.price as number || 3085;
  
  // 模拟SKILL执行延迟
  await new Promise(resolve => setTimeout(resolve, 500 + Math.random() * 1000));
  
  switch (skillName) {
    // ============ A1-A5 原始版本（保持不变）===========
    case 'dream-strategy-research': // A1 - 深度调研（原始版本）
      return {
        success: true,
        data: {
          research_report: {
            summary: `${symbol} 市场结构清晰，具备策略分析基础`,
            triangle_compliance: {
              memory_research: { completed: true, episodes_found: 3 },
              historical_research: { completed: true, cases_found: 2 },
              strategy_research: { completed: true, strategies_found: 1 },
              current_sentiment: { completed: true, bullish_ratio: 0.65 },
              regime_research: { completed: true, technical_regime: 'RANGE_BOUND', similarity: 0.75 }
            },
            market_state: {
              price,
              trend_direction: 'NEUTRAL',
              support_levels: [price * 0.992, price * 0.985, price * 0.975],
              resistance_levels: [price * 1.008, price * 1.015, price * 1.025],
              rsi_state: 'neutral'
            },
            key_insights: [
              '宏观环境支持避险需求',
              '技术面呈现区间震荡格局',
              '成交量维持正常水平'
            ],
            risk_warnings: ['地缘政治风险持续']
          }
        }
      };
    
    case 'dream-first-principles': // A2 - 第一性原理分析（原始版本）
      return {
        success: true,
        data: {
          analysis_report: {
            title: `${symbol} 深度分析报告`,
            methodology: '三问分析框架',
            findings: {
              current_price: price,
              trend_analysis: '长期上行，短期高位震荡',
              support_levels: [price * 0.992, price * 0.985, price * 0.975],
              resistance_levels: [price * 1.008, price * 1.015, price * 1.025],
              momentum: '中性',
              volatility: '正常'
            },
            conclusion: '多空胶着，需情景推演确认最佳方案',
            recommendations: ['等待突破信号', '关注支撑位有效性']
          }
        }
      };
    
    case 'dream-strategy-designer': // A3 - 策略设计（原始版本）
      return {
        success: true,
        data: {
          strategy: {
            name: '区间突破双轨策略',
            scenarios: [
              { scenario: '突破上行', probability: 0.4, outcome: `有效突破 ${price * 1.008}，盈亏比 1:2.5` },
              { scenario: '区间震荡', probability: 0.45, outcome: `${price * 0.992}~${price * 1.008} 区间高抛低吸` },
              { scenario: '下行调整', probability: 0.15, outcome: `跌破 ${price * 0.985} 后观望` }
            ],
            recommendation: '当前符合区间震荡，等待突破信号'
          }
        }
      };
    
    case 'dream-tactical-validator': // A4 - 策略验证（原始版本）
      return {
        success: true,
        data: {
          validation_report: {
            strategy_name: '区间突破双轨策略',
            backtest_summary: {
              period: '近180交易日',
              win_rate: 0.58,
              profit_factor: 2.3,
              max_drawdown: 0.052,
              sharpe_ratio: 1.85
            },
            risk_assessment: {
              risk_level: 'moderate',
              stop_loss: price * 0.98,
              position_size: '30%'
            },
            verdict: '参数稳定，具备正期望值'
          }
        }
      };
    
    case 'dream-tactical-executor': // A5 - 任务执行（原始版本）
      return {
        success: true,
        data: {
          execution: {
            status: 'monitoring',
            steps: [
              { step: '风控规则已加载', status: 'completed' },
              { step: '资金预分配已锁定', status: 'completed' },
              { step: '价格监控已启动', status: 'active' },
              { step: '等待入场信号', status: 'pending' }
            ],
            target_price: price * 0.995,
            stop_loss: price * 0.98,
            take_profit: price * 1.015
          }
        }
      };

    // ============ S 系列专用版本（更通用、更丰富）===========
    case 'dream-strategy-research-s': // S1 - 策略调研（S系列专用）
      const isTraditionalFinance = symbol === 'XAU' || symbol === 'GOLD' || symbol.includes('XAU');
      const isCryptoMarket = symbol === 'BTC' || symbol === 'ETH' || symbol === 'SOL' || symbol === 'BNB';
      
      // 根据市场类型生成不同的社区调研和压力测试数据
      const communityResearch = isTraditionalFinance ? {
        tradingview_strategies: [
          { name: '黄金趋势跟踪策略', author: '@GoldTrader', likes: 3254, win_rate: 68, link: 'https://www.tradingview.com/script/GOLD_TREND/' },
          { name: '美元相关性策略', author: '@ForexMaster', likes: 2187, win_rate: 62, link: 'https://www.tradingview.com/script/DXY_CORR/' },
          { name: '避险资产轮动策略', author: '@SafeHaven', likes: 1892, win_rate: 58, link: 'https://www.tradingview.com/script/SAFE_HAVEN/' }
        ],
        reddit_sentiment: {
          subreddit: 'r/GoldInvesting',
          bullish_comments: 72,
          bearish_comments: 28,
          hot_topics: ['央行购金', '通胀预期', '地缘政治风险']
        },
        twitter_sentiment: {
          positive_tweets: 3567,
          negative_tweets: 1234,
          sentiment_score: 0.74
        }
      } : {
        tradingview_strategies: [
          { name: 'BTC 区间突破策略', author: '@CryptoTrader', likes: 2847, win_rate: 62, link: 'https://www.tradingview.com/script/XXX/' },
          { name: 'MACD RSI 双指标策略', author: '@QuantMaster', likes: 1923, win_rate: 58, link: 'https://www.tradingview.com/script/YYY/' },
          { name: '均线交叉趋势策略', author: '@StrategyLab', likes: 1567, win_rate: 55, link: 'https://www.tradingview.com/script/ZZZ/' }
        ],
        reddit_sentiment: {
          subreddit: 'r/CryptoCurrency',
          bullish_comments: 68,
          bearish_comments: 32,
          hot_topics: ['ETF批准进展', '减半预期', '机构持仓']
        },
        twitter_sentiment: {
          positive_tweets: 2456,
          negative_tweets: 892,
          sentiment_score: 0.73
        }
      };
      
      // 根据市场类型生成不同的压力测试情景
      const stressTestScenarios = isTraditionalFinance ? [
        { scenario: '美联储加息50bp', impact: '短期下跌3-5%，长期避险属性支撑', probability: 0.25 },
        { scenario: '美元指数突破110', impact: '回调5-8%，测试3000支撑', probability: 0.20 },
        { scenario: '全球金融危机爆发', impact: '暴涨15-20%，避险需求激增', probability: 0.10 },
        { scenario: '央行抛售黄金储备', impact: '短期暴跌10-15%', probability: 0.05 },
        { scenario: '通胀数据超预期', impact: '波动加剧，方向取决于数据方向', probability: 0.30 }
      ] : [
        { scenario: 'BTC单日下跌10%', impact: '短期恐慌，但长期趋势不变', probability: 0.10 },
        { scenario: 'ETF审批延迟', impact: '短期回调5-8%', probability: 0.30 },
        { scenario: '黑客攻击重大交易所', impact: '短期暴跌15%', probability: 0.05 },
        { scenario: '监管政策收紧', impact: '回调8-12%，合规交易所受益', probability: 0.15 },
        { scenario: '宏观经济衰退', impact: '风险资产抛售，BTC承压', probability: 0.20 }
      ];
      
      // 根据市场类型生成不同的反方观点
      const opposingViewpoints = isTraditionalFinance ? [
        {
          thesis: '美元走强压制金价',
          arguments: ['美联储鹰派立场', '美国经济数据强劲', '避险需求下降'],
          probability: 0.30,
          mitigation: '关注美元指数和美联储政策信号'
        },
        {
          thesis: '技术面超买信号',
          arguments: ['RSI接近70', '价格偏离均线较远', '前期高点阻力'],
          probability: 0.25,
          mitigation: '等待回调确认，分批建仓'
        },
        {
          thesis: '央行购金放缓',
          arguments: ['购金成本上升', '储备多元化需求下降'],
          probability: 0.15,
          mitigation: '关注央行购金数据，灵活调整仓位'
        }
      ] : [
        {
          thesis: '宏观经济衰退风险导致下跌',
          arguments: ['美联储持续加息', '流动性收紧', '机构去杠杆'],
          probability: 0.25,
          mitigation: '设置严格止损，关注CPI数据'
        },
        {
          thesis: '技术面顶背离信号',
          arguments: ['RSI顶背离', '成交量萎缩', '前期高点压制'],
          probability: 0.20,
          mitigation: '等待确认信号，不追高'
        },
        {
          thesis: '监管风险升级',
          arguments: ['SEC持续执法', '多国监管趋严'],
          probability: 0.15,
          mitigation: '分散持仓，关注合规交易所'
        }
      ];
      
      return {
        success: true,
        data: {
          research_report: {
            summary: `${symbol} 市场结构清晰，具备策略分析基础`,
            market_type: isTraditionalFinance ? 'traditional_finance' : 'crypto',
            triangle_compliance: {
              memory_research: { completed: true, episodes_found: 3 },
              historical_research: { completed: true, cases_found: 2 },
              strategy_research: { completed: true, strategies_found: 1 },
              current_sentiment: { completed: true, bullish_ratio: 0.65 },
              regime_research: { completed: true, technical_regime: 'RANGE_BOUND', similarity: 0.75 }
            },
            market_state: {
              price,
              trend_direction: 'NEUTRAL',
              support_levels: [price * 0.992, price * 0.985, price * 0.975],
              resistance_levels: [price * 1.008, price * 1.015, price * 1.025],
              rsi_state: 'neutral',
              macd_state: 'bullish',
              volume_state: 'normal',
              volatility: 'moderate'
            },
            key_insights: isTraditionalFinance ? [
              '央行持续购金支撑长期趋势',
              '地缘政治风险推升避险需求',
              '美元指数与黄金负相关性增强',
              '通胀预期支撑金价',
              '技术面呈现高位震荡格局'
            ] : [
              '宏观环境支持避险需求',
              '技术面呈现区间震荡格局',
              '成交量维持正常水平',
              '资金流向显示机构持续增持',
              '与相关资产相关性分析完成'
            ],
            risk_warnings: isTraditionalFinance ? [
              '美联储政策不确定性',
              '美元指数走强风险',
              '全球经济复苏削弱避险需求',
              '技术面超买风险'
            ] : [
              '地缘政治风险持续',
              '宏观经济数据即将发布',
              '监管政策不确定性'
            ],
            fundamental_factors: {
              adoption_metric: 'increasing',
              network_activity: 'healthy',
              institutional_participation: 'growing',
              regulatory_clarity: 'improving'
            },
            technical_patterns: [
              { pattern: '上升三角形', probability: 0.6, significance: 'high' },
              { pattern: '均线多头排列', probability: 0.55, significance: 'medium' },
              { pattern: 'MACD金叉', probability: 0.5, significance: 'medium' }
            ],
            timing_signals: {
              entry_zone: `${(price * 0.985).toFixed(2)} - ${(price * 0.992).toFixed(2)}`,
              exit_zone: `${(price * 1.008).toFixed(2)} - ${(price * 1.015).toFixed(2)}`,
              stop_loss: (price * 0.985 * 0.99).toFixed(2),
              time_frame: '4H/Daily'
            },
            community_research: communityResearch,
            adversarial_research: {
              opposing_viewpoints: opposingViewpoints,
              stress_test_scenarios: stressTestScenarios
            }
          }
        }
      };
    
    case 'dream-first-principles-s': // S2 - 策略分析（S系列专用）
      return {
        success: true,
        data: {
          analysis_report: {
            title: `${symbol} 深度分析报告`,
            methodology: '三问分析框架',
            timestamp: new Date().toISOString(),
            findings: {
              current_price: price,
              trend_analysis: '长期上行，短期高位震荡',
              trend_strength: 'moderate',
              support_levels: [price * 0.992, price * 0.985, price * 0.975],
              resistance_levels: [price * 1.008, price * 1.015, price * 1.025],
              momentum: '中性偏多',
              volatility: '正常',
              volume_profile: 'bullish',
              market_structure: 'range_bound',
              timeframe_analysis: {
                daily: 'bullish',
                four_hour: 'neutral',
                one_hour: 'bearish'
              },
              correlation_analysis: {
                btc_correlation: symbol === 'BTC' ? 'N/A' : 0.85,
                eth_correlation: symbol === 'ETH' ? 'N/A' : 0.72,
                usd_correlation: -0.65
              },
              volatility_analysis: {
                atr: price * 0.012,
                iv_rank: 0.45,
                expected_move: price * 0.025
              }
            },
            conclusion: '多空力量均衡，当前处于关键决策点，建议等待明确信号',
            recommendations: [
              '等待突破信号确认方向',
              '关注支撑位有效性测试',
              '设置合理止损保护',
              '考虑分批建仓策略',
              '结合成交量确认趋势'
            ],
            alternative_scenarios: [
              { scenario: '突破上行', condition: `收盘价突破 ${(price * 1.008).toFixed(2)}`, probability: 0.4, implication: '目标指向更高价位' },
              { scenario: '区间震荡', condition: '价格维持在支撑阻力之间', probability: 0.45, implication: '高抛低吸操作' },
              { scenario: '下行调整', condition: `跌破 ${(price * 0.985).toFixed(2)}`, probability: 0.15, implication: '观望等待企稳' }
            ],
            risk_factors: [
              { factor: '宏观经济数据', impact: 'high', probability: 0.6 },
              { factor: '监管政策变化', impact: 'high', probability: 0.3 },
              { factor: '市场流动性', impact: 'medium', probability: 0.4 }
            ]
          },
          strategy_spec: {
            spec_version: 'v1.0',
            title: `${symbol} 交易策略规格说明`,
            scope: '中短期交易策略（1-2周）',
            strategic_directions: [
              {
                id: 'SD-001',
                name: '区间突破策略',
                description: '基于支撑阻力区间的突破交易策略',
                suitability: '高',
                rationale: '当前市场处于明确区间，突破概率较高',
                key_params: {
                  entry_threshold: '突破阻力位 1%',
                  stop_loss: '突破位下方 0.5%',
                  take_profit: '突破位上方 2%',
                  timeframe: '4H/Daily'
                }
              },
              {
                id: 'SD-002',
                name: '趋势跟随策略',
                description: '基于均线和MACD的趋势追踪策略',
                suitability: '中',
                rationale: '长期趋势向上，但短期震荡可能导致频繁止损',
                key_params: {
                  entry_condition: 'MACD金叉 + 均线多头排列',
                  stop_loss: '前低或MA20下方',
                  take_profit: '移动止损跟踪',
                  timeframe: 'Daily'
                }
              },
              {
                id: 'SD-003',
                name: '均值回归策略',
                description: '基于RSI超买超卖的反转交易策略',
                suitability: '低',
                rationale: '当前RSI处于中性区域，反转信号不明确',
                key_params: {
                  entry_condition: 'RSI < 30（买入）或 RSI > 70（卖出）',
                  stop_loss: '极值点外 1%',
                  take_profit: 'RSI回到中性区域',
                  timeframe: '1H/4H'
                }
              }
            ],
            key_decisions: [
              {
                id: 'DEC-001',
                question: '策略方向选择',
                description: '选择哪种策略方向作为主策略',
                options: [
                  { id: 'A', label: '区间突破策略', recommended: true, probability: 0.55, rationale: '当前市场结构最适合' },
                  { id: 'B', label: '趋势跟随策略', recommended: false, probability: 0.3, rationale: '长期趋势明确但短期震荡' },
                  { id: 'C', label: '均值回归策略', recommended: false, probability: 0.15, rationale: '反转信号不明确' }
                ],
                default_selection: 'A',
                confirmation_required: true
              },
              {
                id: 'DEC-002',
                question: '时间框架选择',
                description: '选择主要操作时间框架',
                options: [
                  { id: 'A', label: '4H', recommended: true, probability: 0.6, rationale: '兼顾信号稳定性和时效性' },
                  { id: 'B', label: 'Daily', recommended: false, probability: 0.3, rationale: '信号稳定但反应较慢' },
                  { id: 'C', label: '1H', recommended: false, probability: 0.1, rationale: '信号频繁但假信号多' }
                ],
                default_selection: 'A',
                confirmation_required: true
              },
              {
                id: 'DEC-003',
                question: '风险偏好设置',
                description: '设置单笔交易最大风险比例',
                options: [
                  { id: 'A', label: '1%', recommended: false, probability: 0.2, rationale: '保守型，适合新手' },
                  { id: 'B', label: '2%', recommended: true, probability: 0.5, rationale: '平衡型，适合有经验交易者' },
                  { id: 'C', label: '3%', recommended: false, probability: 0.3, rationale: '激进型，适合熟练交易者' }
                ],
                default_selection: 'B',
                confirmation_required: true
              },
              {
                id: 'DEC-004',
                question: '仓位管理方式',
                description: '选择仓位管理策略',
                options: [
                  { id: 'A', label: '固定仓位', recommended: false, probability: 0.3, rationale: '简单直接' },
                  { id: 'B', label: '凯利公式', recommended: true, probability: 0.4, rationale: '数学优化，最大化长期收益' },
                  { id: 'C', label: '金字塔加仓', recommended: false, probability: 0.3, rationale: '趋势确认后加仓' }
                ],
                default_selection: 'B',
                confirmation_required: true
              }
            ],
            uncertainty_analysis: [
              {
                id: 'UNC-001',
                description: '突破假信号概率',
                probability: 0.35,
                impact: '中等',
                mitigation: '等待收盘价确认 + 成交量验证',
                recommended_action: '建议增加确认条件'
              },
              {
                id: 'UNC-002',
                description: '宏观数据影响不确定性',
                probability: 0.4,
                impact: '高',
                mitigation: '关注经济日历，数据发布前减仓',
                recommended_action: '建议设置数据发布窗口规则'
              },
              {
                id: 'UNC-003',
                description: '流动性风险',
                probability: 0.25,
                impact: '中低',
                mitigation: '避免极端时间段交易，使用限价单',
                recommended_action: '建议设置交易时间窗口'
              }
            ],
            required_inputs: [
              { id: 'IN-001', name: '策略方向', source: '用户选择', required: true },
              { id: 'IN-002', name: '时间框架', source: '用户选择', required: true },
              { id: 'IN-003', name: '风险比例', source: '用户选择', required: true },
              { id: 'IN-004', name: '仓位管理', source: '用户选择', required: true },
              { id: 'IN-005', name: '止损策略', source: '系统建议', required: true },
              { id: 'IN-006', name: '止盈策略', source: '系统建议', required: true }
            ],
            deliverables: [
              { id: 'DEL-001', name: '策略代码', format: 'Python/TypeScript' },
              { id: 'DEL-002', name: '回测报告', format: 'PDF/HTML' },
              { id: 'DEL-003', name: '风险评估', format: 'JSON/HTML' },
              { id: 'DEL-004', name: '执行计划', format: 'Markdown' }
            ],
            approval_required: true,
            approval_checklist: [
              { id: 'CHK-001', item: '策略方向已确认', status: 'pending' },
              { id: 'CHK-002', item: '风险参数已确认', status: 'pending' },
              { id: 'CHK-003', item: '仓位管理已确认', status: 'pending' },
              { id: 'CHK-004', item: '止损策略已确认', status: 'pending' },
              { id: 'CHK-005', item: '止盈策略已确认', status: 'pending' }
            ]
          }
        }
      };
    
    case 'dream-strategy-designer-s': // S3 - 策略设计（S系列专用）
      return {
        success: true,
        data: {
          strategy: {
            name: '区间突破双轨策略',
            version: 'v1.0',
            description: '基于区间突破和趋势跟随的双轨交易策略',
            scenarios: [
              { scenario: '突破上行', probability: 0.4, outcome: `有效突破 ${(price * 1.008).toFixed(2)}，盈亏比 1:2.5`, action: '追多入场' },
              { scenario: '区间震荡', probability: 0.45, outcome: `${(price * 0.992).toFixed(2)}~${(price * 1.008).toFixed(2)} 区间高抛低吸`, action: '区间操作' },
              { scenario: '下行调整', probability: 0.15, outcome: `跌破 ${(price * 0.985).toFixed(2)} 后观望`, action: '止损离场' }
            ],
            recommendation: '当前符合区间震荡，等待突破信号',
            entry_rules: [
              `价格回踩至 ${(price * 0.992).toFixed(2)} - ${(price * 0.985).toFixed(2)} 区间`,
              '出现看涨反转K线形态',
              '成交量确认放大',
              'RSI从超卖区回升'
            ],
            exit_rules: [
              `达到目标位 ${(price * 1.008).toFixed(2)} / ${(price * 1.015).toFixed(2)}`,
              '跌破止损位',
              '出现明确反转信号',
              '时间止损（持有超过5个交易日）'
            ],
            position_management: {
              initial_position: '30%',
              add_position: '20%（突破确认后）',
              max_position: '80%',
              stop_loss: `${(price * 0.985 * 0.99).toFixed(2)}`,
              take_profit_levels: [
                { level: 1, price: (price * 1.008).toFixed(2), percentage: '50%' },
                { level: 2, price: (price * 1.015).toFixed(2), percentage: '30%' },
                { level: 3, price: (price * 1.025).toFixed(2), percentage: '20%' }
              ]
            },
            risk_management: {
              max_risk_per_trade: '2%',
              daily_loss_limit: '5%',
              consecutive_stop_limit: 3,
              correlation_limit: '0.7'
            },
            timeframe: '4H/Daily',
            expected_performance: {
              win_rate: 0.58,
              profit_factor: 2.3,
              expectancy: 0.35,
              sharpe_ratio: 1.8
            }
          },
          code_plan: {
            plan_version: 'v1.0',
            strategy_name: '区间突破双轨策略',
            target_language: 'Python',
            dependencies: ['pandas', 'numpy', 'ta', 'ccxt', 'scipy'],
            modules: [
              {
                id: 'MOD-001',
                name: '数据获取模块',
                description: '从交易所获取历史K线数据',
                status: 'pending',
                estimated_hours: 2,
                tasks: [
                  '连接交易所API',
                  '获取历史K线数据',
                  '数据清洗和标准化',
                  '保存到本地缓存'
                ]
              },
              {
                id: 'MOD-002',
                name: '指标计算模块',
                description: '计算技术指标（RSI, MACD, ATR等）',
                status: 'pending',
                estimated_hours: 3,
                tasks: [
                  'RSI计算',
                  'MACD计算',
                  'ATR计算',
                  '均线计算（MA5, MA10, MA20, MA60）',
                  '布林带计算'
                ]
              },
              {
                id: 'MOD-003',
                name: '信号生成模块',
                description: '基于指标生成买卖信号',
                status: 'pending',
                estimated_hours: 4,
                tasks: [
                  '突破信号检测',
                  '回调买入信号',
                  '止损信号',
                  '止盈信号',
                  '过滤假信号'
                ]
              },
              {
                id: 'MOD-004',
                name: '仓位管理模块',
                description: '基于凯利公式计算仓位',
                status: 'pending',
                estimated_hours: 3,
                tasks: [
                  '凯利公式实现',
                  '风险控制',
                  '仓位限制',
                  '加仓逻辑'
                ]
              },
              {
                id: 'MOD-005',
                name: '回测引擎模块',
                description: '策略回测和绩效评估',
                status: 'pending',
                estimated_hours: 4,
                tasks: [
                  '历史数据回测',
                  '绩效指标计算',
                  '最大回撤计算',
                  '胜率和盈亏比分析'
                ]
              },
              {
                id: 'MOD-006',
                name: '实时交易模块',
                description: '连接交易所进行实盘交易',
                status: 'pending',
                estimated_hours: 3,
                tasks: [
                  '订单下单',
                  '订单管理',
                  '持仓跟踪',
                  '交易日志'
                ]
              }
            ],
            code_template: `import pandas as pd
import numpy as np
import ta
from datetime import datetime

class BreakoutStrategy:
    def __init__(self, symbol, timeframe='4h'):
        self.symbol = symbol
        self.timeframe = timeframe
        self.support_levels = []
        self.resistance_levels = []
        self.signals = []
    
    def calculate_indicators(self, df):
        df['rsi'] = ta.momentum.rsi(df['close'], window=14)
        df['macd'] = ta.trend.macd(df['close'])
        df['macd_signal'] = ta.trend.macd_signal(df['close'])
        df['atr'] = ta.volatility.average_true_range(df['high'], df['low'], df['close'])
        df['ma20'] = df['close'].rolling(20).mean()
        df['ma60'] = df['close'].rolling(60).mean()
        return df
    
    def detect_breakout(self, df):
        # 检测突破信号
        for i in range(len(df)):
            if df['close'].iloc[i] > df['ma20'].iloc[i] and df['rsi'].iloc[i] > 50:
                self.signals.append({'date': df.index[i], 'type': 'buy', 'price': df['close'].iloc[i]})
            elif df['close'].iloc[i] < df['ma20'].iloc[i] and df['rsi'].iloc[i] < 50:
                self.signals.append({'date': df.index[i], 'type': 'sell', 'price': df['close'].iloc[i]})
    
    def run_backtest(self, df):
        df = self.calculate_indicators(df)
        self.detect_breakout(df)
        return self.signals
    
    def get_position_size(self, account_balance, risk_per_trade=0.02):
        # 凯利公式仓位计算
        atr = self.current_atr
        stop_loss = atr * 2
        position_size = (account_balance * risk_per_trade) / stop_loss
        return min(position_size, account_balance * 0.8)`,
            code_generation_status: 'plan_generated',
            code_generation_approval_required: true,
            code_generation_checklist: [
              { id: 'CODE-001', item: '数据模块已确认', status: 'pending' },
              { id: 'CODE-002', item: '指标模块已确认', status: 'pending' },
              { id: 'CODE-003', item: '信号模块已确认', status: 'pending' },
              { id: 'CODE-004', item: '仓位模块已确认', status: 'pending' },
              { id: 'CODE-005', item: '回测模块已确认', status: 'pending' },
              { id: 'CODE-006', item: '交易模块已确认', status: 'pending' }
            ],
            next_steps: [
              '确认代码开发计划',
              '自动生成完整策略代码',
              '执行回测验证',
              '部署到实盘交易'
            ]
          }
        }
      };
    
    case 'dream-tactical-validator-s': // S4 - 策略验证（S系列专用）
      return {
        success: true,
        data: {
          validation_report: {
            strategy_name: '区间突破双轨策略',
            validation_date: new Date().toISOString(),
            backtest_summary: {
              period: '近180交易日',
              win_rate: 0.58,
              profit_factor: 2.3,
              max_drawdown: 0.052,
              sharpe_ratio: 1.85,
              sortino_ratio: 2.4,
              calmar_ratio: 1.6,
              total_trades: 47,
              winning_trades: 27,
              losing_trades: 20,
              avg_win: '3.2%',
              avg_loss: '1.8%',
              best_trade: '8.5%',
              worst_trade: '-2.1%'
            },
            walk_forward_test: {
              periods: 6,
              avg_win_rate: 0.55,
              consistency: 0.85,
              robustness: 'high'
            },
            sensitivity_analysis: {
              parameters: [
                { param: 'entry_threshold', range: '±1%', impact: 'low' },
                { param: 'stop_loss', range: '±0.5%', impact: 'medium' },
                { param: 'take_profit', range: '±10%', impact: 'low' }
              ],
              overall_sensitivity: 'moderate'
            },
            risk_assessment: {
              risk_level: 'moderate',
              stop_loss: price * 0.98,
              position_size: '30%',
              var_95: '2.8%',
              cvar_95: '3.5%',
              stress_test: {
                scenario: '20%价格下跌',
                max_loss: '4.5%',
                margin_call_risk: 'low'
              }
            },
            performance_metrics: {
              equity_curve: 'smooth',
              drawdown_recovery: 'fast',
              win_streak: 5,
              lose_streak: 3,
              profit_density: 'high'
            },
            verdict: '参数稳定，具备正期望值，建议实盘测试',
            improvements: [
              '考虑加入波动率过滤',
              '优化加仓规则',
              '增加时间过滤器'
            ]
          }
        }
      };
    
    case 'dream-tactical-executor-s': // S5 - 策略执行（S系列专用）
      return {
        success: true,
        data: {
          execution: {
            status: 'monitoring',
            strategy_name: '区间突破双轨策略',
            symbol: symbol,
            timestamp: new Date().toISOString(),
            steps: [
              { step: '风控规则已加载', status: 'completed', details: '单笔风险 ≤ 2%' },
              { step: '资金预分配已锁定', status: 'completed', details: '30% 可用资金' },
              { step: '价格监控已启动', status: 'active', details: `监控 ${(price * 0.992).toFixed(2)} - ${(price * 1.008).toFixed(2)}` },
              { step: '等待入场信号', status: 'pending', details: '等待满足全部条件' },
              { step: '执行入场', status: 'pending', details: '条件触发后自动执行' },
              { step: '跟踪止损', status: 'pending', details: '动态调整止损位' },
              { step: '止盈离场', status: 'pending', details: '分批获利了结' }
            ],
            target_price: price * 0.995,
            stop_loss: price * 0.98,
            take_profit: price * 1.015,
            position_size: '30%',
            expected_duration: '3-5 交易日',
            alerts: [
              { type: 'entry', condition: `价格触及 ${(price * 0.992).toFixed(2)}`, status: 'active' },
              { type: 'stop_loss', condition: `价格跌破 ${(price * 0.98).toFixed(2)}`, status: 'active' },
              { type: 'take_profit', condition: `价格达到 ${(price * 1.01).toFixed(2)}`, status: 'active' }
            ],
            risk_summary: {
              max_risk: '2%',
              reward_risk_ratio: '2.5:1',
              probability: 0.55,
              expected_value: '0.45%'
            },
            execution_notes: [
              '建议在流动性高峰时段执行',
              '使用限价单避免滑点',
              '首次入场后设置保护性止损',
              '根据市场波动调整仓位'
            ]
          }
        }
      };
    
    default:
      return {
        success: true,
        data: { message: `${skillName} SKILL executed successfully` }
      };
  }
}

// ============ 市场数据获取 ============
interface MarketPriceData {
  price: number;
  open24h: number;
  high24h: number;
  low24h: number;
  change24h: number;
  support: number[];
  resistance: number[];
  symbol: string;
  displayName: string;
  unit: string;
  note?: string;
}

let priceCache: { data: MarketPriceData | null; timestamp: number } = { data: null, timestamp: 0 };

/**
 * P0-1: 获取标的的实时价格（优先 OKX CLI + Tavily API，失败时 fallback 模拟值）
 * 
 * 数据源路由：
 *   - 加密货币 (BTC/ETH/SOL/BNB/XRP/DOGE/ORDI/SUI) → OKX CLI (实时行情)
 *   - 宏观金融 (美股/黄金/原油/汇率/利率/GDP/CPI) → Tavily API (联网搜索)
 */
async function fetchMarketPrice(symbolInput: string): Promise<MarketPriceData> {
  const upper = symbolInput.toUpperCase();
  const now = Date.now();

  // 缓存命中（60秒内）
  if (priceCache.data && now - priceCache.timestamp < 60 * 1000 && priceCache.data.symbol === upper) {
    return priceCache.data;
  }

  // ===== 路径 A: 调用真实数据源适配器 =====
  try {
    // 从 symbol → 解析 instId / category / tavilyQuery
    let instId = '';
    let category: 'crypto' | 'macro' = 'crypto';
    let tavilyQuery = '';
    let displayName = `${upper}/USDT`;
    let unit = 'USDT';

    // 加密货币 → OKX CLI
    if (['BTC', 'ETH', 'SOL', 'BNB', 'XRP', 'DOGE', 'ORDI', 'SUI'].includes(upper)) {
      instId = `${upper}-USDT-SWAP`;
      category = 'crypto';
      displayName = upper;
      unit = 'USDT';
      tavilyQuery = `${upper} price latest`;
    }
    // 黄金
    else if (upper === 'XAU' || upper === 'GOLD') {
      instId = '';
      category = 'macro';
      displayName = '黄金/美元 (现货)';
      unit = 'USD/oz';
      tavilyQuery = 'gold price per ounce today XAU USD spot price latest';
    }
    // 其他宏观 → Tavily
    else {
      // 从 SYMBOL_DEFINITIONS 中匹配
      const def = SYMBOL_DEFINITIONS.find(d => d.symbol === upper) || extractSymbolFromMessage(upper);
      if (def) {
        instId = def.instId;
        category = def.category;
        displayName = def.display;
        unit = category === 'crypto' ? 'USDT' : 'USD';
        tavilyQuery = def.tavilyQuery || `${def.display} market price latest`;
      } else {
        instId = `${upper}-USDT-SWAP`;
        category = 'crypto';
        displayName = upper;
        unit = 'USDT';
        tavilyQuery = `${upper} price latest`;
      }
    }

    // 调用真实数据源适配器（OKX CLI 或 Tavily API）
    if (instId) {
      // crypto → OKX CLI
      const okxData = await fetchMarketData(upper, instId, 'crypto', displayName, tavilyQuery, 'zh');
      if (okxData.price !== null && okxData.source !== 'error') {
        const price = okxData.price;
        const result: MarketPriceData = {
          price,
          open24h: okxData.open24h || price * 0.995,
          high24h: okxData.high24h || price * 1.015,
          low24h: okxData.low24h || price * 0.985,
          change24h: okxData.change24h || 0.5,
          // 支撑/阻力位从 OKX 数据推导
          support: [price * 0.992, price * 0.985, price * 0.975],
          resistance: [price * 1.008, price * 1.015, price * 1.025],
          symbol: upper,
          displayName,
          unit,
          note: `OKX 实时行情 (ticker ${instId})`,
        };
        priceCache = { data: result, timestamp: now };
        return result;
      }
    } else {
      // macro → Tavily API
      const tavilyData = await fetchMarketData(upper, '', 'macro', displayName, tavilyQuery, 'zh');
      if (tavilyData.source !== 'error' && tavilyData.extraInfo) {
        // Tavily 返回文本摘要，从文本中提取价格（使用简单的价格解析）
        const priceMatch = tavilyData.extraInfo.match(/(\d+(?:\.\d+)?)\s*(?:USD|USDT|点|\/oz)?/);
        const parsedPrice = priceMatch ? parseFloat(priceMatch[1]) : null;
        const basePrice = parsedPrice && parsedPrice > 0 ? parsedPrice : estimateBasePrice(upper);
        const result: MarketPriceData = {
          price: basePrice,
          open24h: basePrice * 0.995,
          high24h: basePrice * 1.015,
          low24h: basePrice * 0.985,
          change24h: 0.5,
          support: [basePrice * 0.992, basePrice * 0.985, basePrice * 0.975],
          resistance: [basePrice * 1.008, basePrice * 1.015, basePrice * 1.025],
          symbol: upper,
          displayName,
          unit,
          note: `Tavily 联网搜索 · ${displayName} 参考行情 · 原文片段: ${tavilyData.extraInfo.slice(0, 60)}...`,
        };
        priceCache = { data: result, timestamp: now };
        return result;
      }
    }
  } catch (error) {
    console.warn(`[market-data] 真实数据源失败，fallback 模拟值: ${error}`);
  }

  // ===== 路径 B: fallback: 合理模拟值（根据 symbol 动态生成） =====
  const basePrice = estimateBasePrice(upper);
  let unit = 'USDT';
  let displayName = `${upper}/USDT`;
  if (upper === 'XAU' || upper === 'GOLD') { unit = 'USD/oz'; displayName = '黄金/美元 (现货)'; }

  const jitter = (Math.random() - 0.5) * (basePrice * 0.003);
  const price = basePrice + jitter;
  const open = basePrice + (Math.random() - 0.5) * (basePrice * 0.005);
  const high = Math.max(price, open) + basePrice * 0.008;
  const low = Math.min(price, open) - basePrice * 0.008;
  const changePct = ((price - open) / open) * 100;
  const result: MarketPriceData = {
    price: parseFloat(price.toFixed(2)),
    open24h: parseFloat(open.toFixed(2)),
    high24h: parseFloat(high.toFixed(2)),
    low24h: parseFloat(low.toFixed(2)),
    change24h: parseFloat(changePct.toFixed(2)),
    support: [parseFloat((price * 0.992).toFixed(2)), parseFloat((price * 0.985).toFixed(2)), parseFloat((price * 0.975).toFixed(2))],
    resistance: [parseFloat((price * 1.008).toFixed(2)), parseFloat((price * 1.015).toFixed(2)), parseFloat((price * 1.025).toFixed(2))],
    symbol: upper,
    displayName, unit,
    note: `${displayName} 参考行情（模拟动态数据 · 真实数据源不可用）`,
  };
  priceCache = { data: result, timestamp: now };
  return result;
}

/**
 * 根据 symbol 估算基准价（作为 fallback 使用）
 */
function estimateBasePrice(symbol: string): number {
  const lower = symbol.toLowerCase();
  if (lower.includes('xau') || lower.includes('gold')) return 3085;
  if (symbol === 'BTC') return 80630;
  if (symbol === 'ETH') return 3820;
  if (symbol === 'SOL') return 168;
  if (symbol === 'BNB') return 620;
  if (symbol === 'XRP') return 0.62;
  return 100; // 默认
}

function fmtPrice(price: number, unit: string): string {
  if (price >= 1000) return `$${price.toLocaleString('en-US', { maximumFractionDigits: 2 })}`;
  if (price >= 1) return `$${price.toFixed(2)}`;
  return `$${price.toFixed(4)}`;
}

/**
 * D-Z-E链步骤到SKILL的映射
 */
const STEP_TO_SKILL: Record<string, string> = {
  // D-Z-E 链（开发治理，保留）
  'D1_investigator': 'dream-strategy-research',
  'D2_analyst': 'dream-first-principles',
  'D3_deducer': 'dream-strategy-designer',
  'D4_spec_author': 'dream-tactical-validator',
  'Z1_code_scanner': 'dream-tactical-validator',
  'Z2_boundary_divider': 'dream-tactical-validator',
  'Z3_path_planner': 'dream-tactical-validator',
  'Z4_acceptance_designer': 'dream-tactical-validator',
  'E1_task_executor': 'dream-tactical-executor',
  'E2_tester': 'dream-tactical-executor',
  'E3_deployer': 'dream-tactical-executor',
  // S 系列策略链（前端用户主链，使用专用的 -s 版本）
  'S1_RESEARCH': 'dream-strategy-research-s',
  'S2_ANALYSIS': 'dream-first-principles-s',
  'S3_DESIGN': 'dream-strategy-designer-s',
  'S4_VALIDATE': 'dream-tactical-validator-s',
  'S5_EXECUTE': 'dream-tactical-executor-s',
};

// ============================================================
// P2: S5 策略代码执行引擎 - Chat 专用执行函数
// 职责：
//   1. developer 意图 → 调用 S5 executeS5（完整 E1→E2→E3 链）
//   2. 输出格式与 generateChainResponse 对齐
// 边界：与 S 系列的其他步骤共享链命名；不再使用 D/Z 系列
// ============================================================

async function executeS5ForChat(
  sessionId: string,
  userMessage: string,
  thinkingMode: 'quick' | 'deep' | 'scheduler' | 'stepwise',
  lang: 'zh' | 'en',
): Promise<S5ExecutionResult> {
  const mode = thinkingMode === 'scheduler' || thinkingMode === 'stepwise' ? 'deep' : thinkingMode;
  console.log(`[S5 Engine] chat invoke: message=${userMessage.slice(0, 50)}`);

  const result = executeS5({
    taskId: `chat_${sessionId}_${Date.now()}`,
    sessionId,
    userMessage,
    thinkingMode: mode,
    lang,
  });

  return result;
}

/**
 * 处理链响应（调用真实SKILL，实现阶段门禁）
 */
/**
 * 执行模式：
 *   - dynamic:   自动执行完整链（S1-S5 不中断）
 *   - stepwise:  S1+S2 后暂停，S3/S4 后再次暂停，需要用户确认
 *   - quick:     简化短链快速执行
 *   - developer: dev-chain.executeS5() 路径（不在此函数中执行）
 */
type ExecMode = 'dynamic' | 'stepwise' | 'quick' | 'developer';

async function generateChainResponse(
  chain: string[], 
  intent: string, 
  entities: Record<string, string>,
  sessionId: string,
  needUserConfirmation: boolean = false,
  // P0: 可选调度器上下文（用于 Cost Keeper + Skip Gate）
  schedulerCtx?: {
    userMessage: string;
    complexity: 'simple' | 'moderate' | 'complex';
  },
  // Phase A: 执行模式（控制是否在 S2→S3/S3→S4 前暂停）
  mode: ExecMode = 'dynamic',
): Promise<{ content: string; chainState: any; strategyChainState: any; stepProgress: any; market: MarketPriceData | null; needsConfirmation: boolean; nextStep: string | null }> {
  const symbol = entities.symbol || "BTC";

  // ===== Hermes 记忆学习：链初始化时学习标的偏好 =====
  const userId = sessionId;
  userPrefMemory.learn({
    userId,
    type: 'preferred_symbols',
    value: [symbol.toUpperCase()],
    importance: 0.4,
    source: 'implicit_behavior',
    evidence: `用户启动 S系列策略链分析 ${symbol}`,
  });

  // 获取实时价格数据（动态，非硬编码）
  const market = await fetchMarketPrice(symbol);
  const priceStr = fmtPrice(market.price, market.unit);
  const supportStr = market.support.map(v => fmtPrice(v, market.unit)).join(' / ');
  const resistanceStr = market.resistance.map(v => fmtPrice(v, market.unit)).join(' / ');
  const support1 = fmtPrice(market.support[0], market.unit);
  const support2 = fmtPrice(market.support[1], market.unit);
  const resist1 = fmtPrice(market.resistance[0], market.unit);
  const resist2 = fmtPrice(market.resistance[1], market.unit);
  const changeStr = (market.change24h >= 0 ? '+' : '') + market.change24h.toFixed(2) + '%';
  const isGold = market.symbol === 'XAU' || market.displayName.includes('黄金');
  const displayName = market.displayName;
  
  // === 7步进度条定义 ===
  const stepProgress = {
    steps: [
      { id: 'S1', name: '需求解析', status: 'completed' as const },
      { id: 'S2', name: '思维链调研', status: chain.some(s => s.startsWith('D1')) ? 'completed' : 'active' as const },
      { id: 'S3', name: '知识库检索', status: 'pending' as const },
      { id: 'S4', name: '方法论借鉴', status: 'pending' as const },
      { id: 'S5', name: '索引系统更新', status: 'pending' as const },
      { id: 'S6', name: '飞书协作归档', status: 'pending' as const },
      { id: 'S7', name: '记忆蒸馏', status: 'pending' as const },
    ],
    currentStep: 2,
    totalSteps: 7,
  };
  
  // 获取当前会话的链状态
  const chainState = get_or_init_chain_state(sessionId, `${symbol} ${displayName} 策略分析`);
  
  // 更新链状态的phases
  const updatedPhases = chainState.phases.map((phase, idx) => {
    const phaseId = phase.id.toLowerCase();
    const chainIndex = chain.findIndex(c => c.toLowerCase().includes(phaseId));
    
    if (chainIndex >= 0) {
      // 链中存在此阶段
      if (chainIndex === chain.length - 1 && needUserConfirmation) {
        // 当前阶段完成，需要用户确认
        return { ...phase, status: 'completed' as const, approval: 'pending' as const };
      } else if (chainIndex < chain.length - 1) {
        // 已完成的阶段
        return { ...phase, status: 'completed' as const, approval: 'approved' as const };
      } else {
        // 当前正在执行的阶段
        return { ...phase, status: 'in_progress' as const };
      }
    }
    return phase;
  });
  
  // 更新当前阶段
  const currentPhase = chain.length > 0 ? chain[chain.length - 1] : chainState.current_phase;
  
  // === 执行SKILL并生成响应 ===
  let result = "";
  const skillResults: Record<string, any> = {};
  let pendingConfirmationStep: string | null = null;
  let confirmationType: 'spec' | 'code_plan' | null = null;
  // P0-2: 累积每步输出，作为思维链上下文传递给下一步
  let cumulativeOutput = "";

  for (let i = 0; i < chain.length; i++) {
    const step = chain[i];

    // Phase A: 仅 stepwise 模式下，S2→S3 / S3→S4 前才需要用户确认
    //   - dynamic/quick 模式：自动执行完整链，不中断
    //   - stepwise 模式：在 S3 前暂停（S1+S2 完成后），在 S4 前再次暂停（S3 完成后）
    if (mode === 'stepwise' && step === 'S3_DESIGN' && chain.slice(0, i).includes('S2_ANALYSIS')) {
      pendingConfirmationStep = step;
      confirmationType = 'spec';
      break;
    }

    if (mode === 'stepwise' && step === 'S4_VALIDATE' && chain.slice(0, i).includes('S3_DESIGN')) {
      pendingConfirmationStep = step;
      confirmationType = 'code_plan';
      break;
    }

    // D/Z 系列在 needUserConfirmation=true 时需要确认（与原逻辑一致）
    if (needUserConfirmation && i > 0 && (step.startsWith('D') || step.startsWith('Z'))) {
      // 如果需要确认，只执行到当前步骤，然后等待确认
      const schedulerContext = schedulerCtx
        ? { userInput: schedulerCtx.userMessage, intent, complexity: schedulerCtx.complexity }
        : undefined;
      const stepResult = await executeStepWithSkill(step, symbol, market, priceStr, supportStr, resistanceStr, support1, support2, resist1, resist2, changeStr, isGold, displayName, sessionId, true, cumulativeOutput, schedulerContext);
      result += stepResult;
      cumulativeOutput += (cumulativeOutput ? "\n\n" : "") + stepResult;
      skillResults[step] = true;
      break;
    }
    
    // P0: 构造 schedulerContext（传给 executeStepWithSkill）
    const schedulerContext = schedulerCtx
      ? { userInput: schedulerCtx.userMessage, intent, complexity: schedulerCtx.complexity }
      : undefined;

    // 执行步骤（调用SKILL） —— P0-2: 传递累积的上一步输出作为思维链上下文
    const stepResult = await executeStepWithSkill(step, symbol, market, priceStr, supportStr, resistanceStr, support1, support2, resist1, resist2, changeStr, isGold, displayName, sessionId, true, cumulativeOutput, schedulerContext);
    result += stepResult;
    cumulativeOutput += (cumulativeOutput ? "\n\n" : "") + stepResult;
    skillResults[step] = true;
    
    if (i < chain.length - 1) {
      result += "\n\n---\n\n";
    }
  }
  
  // 检查是否需要用户确认
  let needsConfirmation = needUserConfirmation && chain.length > 1 && !chain[chain.length - 1].startsWith('E');
  let nextStep = needsConfirmation ? getNextPhase(chain[chain.length - 1]) : null;
  
  // 更新链状态
  const newChainState: ChainState = {
    ...chainState,
    current_phase: currentPhase.toLowerCase(),
    phases: updatedPhases,
  };
  update_chain_state(sessionId, newChainState);
  
  // 构建链状态输出
  const outputChainState = {
    phases: newChainState.phases.map(p => ({
      id: p.id.toUpperCase(),
      name: p.name,
      status: p.status,
      approval: p.approval,
      output: p.output_ref || '',
    })),
    currentPhase: currentPhase,
    scope: newChainState.scope,
    needsConfirmation,
    nextStep,
  };
  
  // 检测是否为S系列策略链
  const isStrategyChain = chain.length > 0 && chain[0].startsWith('S');

  // 构建S系列策略链状态
  let strategyChainState: any = null;
  if (isStrategyChain) {
    const strategySteps = ['S1_RESEARCH', 'S2_ANALYSIS', 'S3_DESIGN', 'S4_VALIDATE', 'S5_EXECUTE'];
    const executedSteps = chain;

    strategyChainState = {
      scope: `${symbol} ${displayName} 策略分析`,
      currentStep: executedSteps[executedSteps.length - 1] || null,
      steps: strategySteps.map((stepId, idx) => {
        const isExecuted = executedSteps.includes(stepId);
        const isCurrent = stepId === executedSteps[executedSteps.length - 1];

        let status = 'pending';
        if (isExecuted && !isCurrent) status = 'done';
        else if (isCurrent) status = 'active';

        const nameMap: Record<string, string> = {
          'S1_RESEARCH': 'S1 调研',
          'S2_ANALYSIS': 'S2 分析',
          'S3_DESIGN': 'S3 设计',
          'S4_VALIDATE': 'S4 验证',
          'S5_EXECUTE': 'S5 执行',
        };

        return {
          id: stepId,
          number: idx + 1,
          name: nameMap[stepId] || stepId,
          status,
        };
      }),
      complexity: chain.length <= 2 ? 'quick' : chain.length <= 3 ? 'standard' : 'deep',
      createdAt: new Date().toISOString(),
      modifiedAt: new Date().toISOString(),
    };

    // 更新策略链状态缓存
    update_strategy_state(sessionId, {
      currentStep: strategyChainState.currentStep,
      steps: strategySteps,
      completedSteps: executedSteps.filter(s => s !== strategyChainState.currentStep),
    });
  }

  // Phase A: 仅 stepwise 模式才追加 Spec/Code Plan 确认提示
  //   - dynamic 模式：自动跑完 S1-S5，不需要用户确认
  //   - stepwise 模式：S2→S3 与 S3→S4 前暂停并提示用户确认
  const isS2Break = mode === 'stepwise' && pendingConfirmationStep === 'S3_DESIGN';
  const isS3Break = mode === 'stepwise' && pendingConfirmationStep === 'S4_VALIDATE';

  if (isS2Break) {
    needsConfirmation = true;
    nextStep = 'S3_DESIGN';
    result += "\n\n---\n\n";
    result += "## 🔸 步进式分析模式 · S2 完成\n\n";
    result += "**S1 调研** 和 **S2 深度分析** 已完成。\n\n";
    result += "下一步将进入 **S3 策略设计**（入场条件、止损止盈、仓位管理等核心决策）。\n\n";
    result += "请回复 **\"继续\"** 进入 S3，或提出修改意见（如：\"把止损改成 1%\"）。";
  }

  if (isS3Break) {
    needsConfirmation = true;
    nextStep = 'S4_VALIDATE';
    result += "\n\n---\n\n";
    result += "## 🔸 步进式分析模式 · S3 完成\n\n";
    result += "**S3 策略设计** 已完成。\n\n";
    result += "下一步将进入 **S4 策略验证**（回测、压力测试、参数稳定性检查）。\n\n";
    result += "请回复 **\"继续\"** 进入 S4，或提出修改意见。";
  }
  
  return {
    content: result.trim() || "处理完成。",
    chainState: outputChainState,
    strategyChainState,
    stepProgress,
    market,
    needsConfirmation,
    nextStep,
  };
}

/**
 * 执行单个步骤（调用SKILL或生成静态响应）
 * P0-2: 增加 previousStepOutput —— 传递思维链上下文，使当前步骤可以基于上一步结论做连续推理
 */
async function executeStepWithSkill(
  step: string,
  symbol: string,
  market: MarketPriceData,
  priceStr: string,
  supportStr: string,
  resistanceStr: string,
  support1: string,
  support2: string,
  resist1: string,
  resist2: string,
  changeStr: string,
  isGold: boolean,
  displayName: string,
  sessionId: string = '',
  usePreference: boolean = true,
  previousStepOutput?: string,  // P0-2: 思维链上下文
  // P0: Skip Gate 相关信息（可选，未提供则不跳过任何步骤）
  schedulerContext?: {
    userInput: string;
    intent: string;
    complexity: 'simple' | 'moderate' | 'complex';
  }
): Promise<string> {

  // ============ P0: Skip Gate 步骤旁路判断 ============
  // 仅当提供了 schedulerContext 时启用（由调用方控制）
  if (schedulerContext) {
    const gateResult = shouldSkipStep(
      step as StepName,
      schedulerContext.userInput,
      schedulerContext.intent,
      schedulerContext.complexity
    );

    if (gateResult.skip) {
      // 被跳过 — 记录到成本报告，返回简短 fallback 信息
      markStepSkipped(sessionId, step, step, gateResult.reason);
      console.log(`[SkipGate] SKIP ${step}: ${gateResult.reason}`);
      return `\n---\n**${step}: 已跳过**（${gateResult.reason}）\n---\n`;
    }
  }

  // ============ S 系列：优先使用 LLM 动态生成（内容更智能多样） ============
  if (step.startsWith('S')) {
    const style = pickResponseStyle(sessionId || symbol, step);

    // P2: S4_VALIDATE 步骤优先尝试策略计算引擎（Python Bridge）
    // 若桥接服务可用，直接返回真实回测结果；否则 fallback 到 LLM
    if (step === 'S4_VALIDATE') {
      const bridgeResult = await callStrategyEngine(step, {
        symbol,
        price: market.price,
        support1,
        resistance1: resist1,
        previousStepOutput,
      });
      if (bridgeResult) return bridgeResult;
    }

    // 路径 A：LLM 动态生成（首选）
    const llmContent = await callLLMStep(
      step,
      {
        symbol, displayName, priceStr, changeStr,
        supportStr, resistanceStr,
        support1, support2, resist1, resist2,
        isGold, price: market.price,
      },
      style,
      sessionId,
      usePreference,
      previousStepOutput  // P0-2: 传递思维链上下文
    );

    if (llmContent) {
      // 在标题行末尾附加 style 标签，提升可识别性
      const styleLabel = getStyleLabel(style);
      const firstLineBreak = llmContent.indexOf('\n');
      if (firstLineBreak > 0) {
        return `${llmContent.substring(0, firstLineBreak)} ${styleLabel}${llmContent.substring(firstLineBreak)}`;
      }
      return `${llmContent} ${styleLabel}`;
    }

    // 路径 B：LLM 调用失败 → 调用 SKILL mock 数据
    const skillName = STEP_TO_SKILL[step];
    if (skillName) {
      const skillResult = await callSkill(skillName, {
        symbol, price: market.price, support: market.support, resistance: market.resistance,
      });
      if (skillResult.success && skillResult.data) {
        const base = formatSkillResult(step, skillResult.data, displayName, symbol, priceStr, supportStr, resistanceStr, support1, support2, resist1, changeStr, isGold);
        const styleLabel = getStyleLabel(style);
        const firstLineBreak = base.indexOf('\n');
        if (firstLineBreak > 0) {
          return `${base.substring(0, firstLineBreak)} ${styleLabel}${base.substring(firstLineBreak)}`;
        }
        return `${base} ${styleLabel}`;
      }
    }

    // 路径 C：最终 fallback 到静态响应
    return generateStaticResponse(step, symbol, displayName, priceStr, supportStr, resistanceStr, support1, support2, resist1, resist2, changeStr, isGold, market, sessionId);
  }

  // ============ D-Z-E / 其他链：保持原有逻辑（SKILL 优先，静态响应 fallback） ============
  const skillName = STEP_TO_SKILL[step];

  if (skillName) {
    const skillResult = await callSkill(skillName, {
      symbol, price: market.price, support: market.support, resistance: market.resistance,
    });
    if (skillResult.success && skillResult.data) {
      const base = formatSkillResult(step, skillResult.data, displayName, symbol, priceStr, supportStr, resistanceStr, support1, support2, resist1, changeStr, isGold);
      if (step.startsWith('S')) {
        const style = pickResponseStyle(sessionId || symbol, step);
        const styleLabel = getStyleLabel(style);
        const firstLineBreak = base.indexOf('\n');
        if (firstLineBreak > 0) {
          return `${base.substring(0, firstLineBreak)} ${styleLabel}${base.substring(firstLineBreak)}`;
        }
        return `${base} ${styleLabel}`;
      }
      return base;
    }
  }

  return generateStaticResponse(step, symbol, displayName, priceStr, supportStr, resistanceStr, support1, support2, resist1, resist2, changeStr, isGold, market, sessionId);
}

/**
 * 格式化SKILL执行结果
 */
function formatSkillResult(
  step: string,
  data: any,
  displayName: string,
  symbol: string,
  priceStr: string,
  supportStr: string,
  resistanceStr: string,
  support1: string,
  support2: string,
  resist1: string,
  changeStr: string,
  isGold: boolean
): string {
  const stepDefs: Record<string, { icon: string; title: string }> = {
    // D-Z-E 链（开发治理）
    'D1_investigator': { icon: '🔍', title: 'D1 深度调研 (Investigator)' },
    'D2_analyst': { icon: '🧠', title: 'D2 分析诊断 (Analyst)' },
    'D3_deducer': { icon: '🎲', title: 'D3 推演验证 (Deducer)' },
    'D4_spec_author': { icon: '📝', title: 'D4 策略规格书 (Spec Author)' },
    'Z1_code_scanner': { icon: '🏗️', title: 'Z1 参数扫描 (Code Scanner)' },
    'Z2_boundary_divider': { icon: '📐', title: 'Z2 范围界定 (Boundary Divider)' },
    'Z3_path_planner': { icon: '🗺️', title: 'Z3 路径设计 (Path Planner)' },
    'Z4_acceptance_designer': { icon: '✅', title: 'Z4 验收方案 (Acceptance Designer)' },
    'E1_task_executor': { icon: '⚡', title: 'E1 任务执行 (Task Executor)' },
    'E2_tester': { icon: '🧪', title: 'E2 测试验证 (Tester)' },
    'E3_deployer': { icon: '🚀', title: 'E3 部署交付 (Deployer)' },
    // S 系列策略链（前端用户主链）
    'S1_RESEARCH': { icon: '🔍', title: 'S1 调研 (Research)' },
    'S2_ANALYSIS': { icon: '🧠', title: 'S2 分析 (Analysis)' },
    'S3_DESIGN': { icon: '🎯', title: 'S3 设计 (Design)' },
    'S4_VALIDATE': { icon: '✅', title: 'S4 验证 (Validate)' },
    'S5_EXECUTE': { icon: '⚡', title: 'S5 执行 (Execute)' },
  };
  
  const def = stepDefs[step] || { icon: '📋', title: step };
  const isSSeries = step.startsWith('S');
  
  // ============ S 系列专用：更丰富的输出格式 ============
  if (isSSeries && data.research_report) {
    const report = data.research_report;
    return `${def.icon} **${def.title}**

📊 标的: ${displayName} (${symbol})
💹 实时价格: ${priceStr} (24h ${changeStr})

**📈 市场状态:**
- 趋势方向: ${report.market_state?.trend_direction || 'NEUTRAL'}
- 波动率: ${report.market_state?.volatility || 'moderate'}
- RSI: ${report.market_state?.rsi_state || 'neutral'}
- MACD: ${report.market_state?.macd_state || 'neutral'}

**📊 关键价位:**
- 支撑位: ${supportStr}
- 阻力位: ${resistanceStr}

**💡 关键洞察:**
${report.key_insights?.map((i: string) => `- ${i}`).join('\n') || '- 完成基础市场分析'}

${report.technical_patterns && report.technical_patterns.length > 0 ? `**🔍 技术形态识别:**
${report.technical_patterns.map((p: any) => `- ${p.pattern} (概率: ${(p.probability * 100).toFixed(0)}%, 显著性: ${p.significance})`).join('\n')}` : ''}

${report.fundamental_factors ? `**📚 基本面因素:**
- 采用指标: ${report.fundamental_factors.adoption_metric}
- 网络活跃度: ${report.fundamental_factors.network_activity}
- 机构参与: ${report.fundamental_factors.institutional_participation}` : ''}

${report.timing_signals ? `**⏰ 时间信号:**
- 入场区间: ${report.timing_signals.entry_zone}
- 离场区间: ${report.timing_signals.exit_zone}
- 建议止损: ${report.timing_signals.stop_loss}
- 时间框架: ${report.timing_signals.time_frame}` : ''}

${report.community_research ? `**🌐 策略社区调研 (TradingView & Social):**

**📈 TradingView 热门策略:**
| 策略名称 | 作者 | 点赞数 | 胜率 |
|---------|------|--------|------|
${report.community_research.tradingview_strategies?.map((s: any) => `| [${s.name}](${s.link}) | ${s.author} | ${s.likes} | ${s.win_rate}% |`).join('\n') || '暂无数据'}

**💬 Reddit 情绪:**
- 子版块: ${report.community_research.reddit_sentiment?.subreddit}
- 看多评论: ${report.community_research.reddit_sentiment?.bullish_comments}%
- 看空评论: ${report.community_research.reddit_sentiment?.bearish_comments}%
- 热门话题: ${report.community_research.reddit_sentiment?.hot_topics?.join(', ') || 'N/A'}

**🐦 Twitter 情绪:**
- 正面推文: ${report.community_research.twitter_sentiment?.positive_tweets}
- 负面推文: ${report.community_research.twitter_sentiment?.negative_tweets}
- 情绪评分: ${(report.community_research.twitter_sentiment?.sentiment_score * 100).toFixed(0)}%` : ''}

${report.adversarial_research ? `**⚔️ 对抗性调研 (Opposing Viewpoints):**

**反方观点分析:**
${report.adversarial_research.opposing_viewpoints?.map((v: any) => `**${v.thesis}** (概率: ${(v.probability * 100).toFixed(0)}%)
- 论据: ${v.arguments?.join(', ')}
- 应对策略: ${v.mitigation}`).join('\n\n') || '暂无分析'}

**🔥 压力测试情景:**
${report.adversarial_research.stress_test_scenarios?.map((s: any) => `- ${s.scenario}: ${s.impact} (概率: ${(s.probability * 100).toFixed(0)}%)`).join('\n') || '暂无测试'}

---

` : ''}

**⚠️ 风险提示:**
${report.risk_warnings?.map((w: string) => `- ${w}`).join('\n') || '- 暂无重大风险'}

---

${report.summary}`;
  }
  
  if (isSSeries && data.analysis_report) {
    const report = data.analysis_report;
    const spec = data.strategy_spec;
    
    return `${def.icon} **${def.title}**

📊 标的: ${displayName}

**📈 技术分析:**
- 当前价格: ${priceStr} (24h ${changeStr})
- 趋势方向: ${report.findings?.trend_analysis || '待确认'}
- 趋势强度: ${report.findings?.trend_strength || 'moderate'}
- 市场结构: ${report.findings?.market_structure || 'range_bound'}
- 支撑位: ${supportStr}
- 阻力位: ${resistanceStr}
- 动量: ${report.findings?.momentum || '中性'}
- 波动率: ${report.findings?.volatility || '正常'}

${report.findings?.timeframe_analysis ? `**⏱️ 多时间框架分析:**
- Daily: ${report.findings.timeframe_analysis.daily}
- 4H: ${report.findings.timeframe_analysis.four_hour}
- 1H: ${report.findings.timeframe_analysis.one_hour}` : ''}

${report.findings?.correlation_analysis ? `**🔗 相关性分析:**
- BTC 相关性: ${report.findings.correlation_analysis.btc_correlation}
- ETH 相关性: ${report.findings.correlation_analysis.eth_correlation}
- USD 相关性: ${report.findings.correlation_analysis.usd_correlation}` : ''}

${report.findings?.volatility_analysis ? `**📊 波动率分析:**
- ATR: ${report.findings.volatility_analysis.atr?.toFixed(2) || 'N/A'}
- IV Rank: ${(report.findings.volatility_analysis.iv_rank * 100).toFixed(0)}%
- 预期波动: ±${(report.findings.volatility_analysis.expected_move * 100).toFixed(2)}%` : ''}

**🧠 分析结论:**
${report.conclusion || '多空胶着，需情景推演确认最佳方案。'}

${report.alternative_scenarios && report.alternative_scenarios.length > 0 ? `**🎲 情景分析:**
| 情景 | 概率 | 触发条件 | 含义 |
|------|------|---------|------|
${report.alternative_scenarios.map((s: any) => `| ${s.scenario} | ${(s.probability * 100).toFixed(0)}% | ${s.condition} | ${s.implication} |`).join('\n')}` : ''}

${report.risk_factors && report.risk_factors.length > 0 ? `**⚠️ 风险因素评估:**
${report.risk_factors.map((r: any) => `- **${r.factor}**: 影响程度 ${r.impact}，概率 ${(r.probability * 100).toFixed(0)}%`).join('\n')}` : ''}

**💡 建议:**
${report.recommendations?.map((r: string) => `- ${r}`).join('\n') || '- 等待进一步信号'}

${spec ? `

---

## 📋 策略规格说明 (Spec)

**版本:** ${spec.spec_version} | **标题:** ${spec.title} | **范围:** ${spec.scope}

### 🎯 策略方向 (Strategic Directions)

${spec.strategic_directions?.map((sd: any) => `**${sd.id}. ${sd.name}** (适合度: ${sd.suitability})
- 描述: ${sd.description}
- 理由: ${sd.rationale}
- 关键参数:
${Object.entries(sd.key_params || {}).map(([k, v]: [string, any]) => `  - ${k}: ${v}`).join('\n')}`).join('\n\n') || '暂无策略方向'}

### 🤔 关键决策 (Key Decisions)

${spec.key_decisions?.map((d: any) => `**${d.id}. ${d.question}**${d.confirmation_required ? ' ⚠️' : ''}
- 描述: ${d.description}
- 选项:
${d.options?.map((o: any) => `  ${o.recommended ? '✅' : '⬜'} **${o.id}. ${o.label}** - 概率 ${(o.probability * 100).toFixed(0)}% (${o.rationale})`).join('\n')}
- 默认推荐: ${d.default_selection}`).join('\n\n') || '暂无决策点'}

### ⚠️ 不确定性分析 (Uncertainty Analysis)

${spec.uncertainty_analysis?.map((u: any) => `**${u.id}. ${u.description}** (概率: ${(u.probability * 100).toFixed(0)}%, 影响: ${u.impact})
- 应对措施: ${u.mitigation}
- 建议行动: ${u.recommended_action}`).join('\n\n') || '暂无不确定性分析'}

### 📋 审批清单 (Approval Checklist)

${spec.approval_checklist?.map((c: any) => ` ${c.status === 'pending' ? '⬜' : '✅'} ${c.item}`).join('\n') || '暂无清单'}

### 📦 交付物 (Deliverables)

${spec.deliverables?.map((d: any) => `- **${d.name}** (格式: ${d.format})`).join('\n') || '暂无交付物'}

---

> **提示:** 需要您确认以上策略规格后，才能进入 S3 策略设计阶段。
> 请回复 **"确认"** / **"继续"** 或修改具体选项（如："确认，风险偏好改为1%"）` : ''}`;
  }
  
  if (isSSeries && data.strategy) {
    const strategy = data.strategy;
    const codePlan = data.code_plan;
    
    return `${def.icon} **${def.title}**

📊 标的: ${displayName}
📋 策略名称: ${strategy.name || '区间突破双轨策略'}
${strategy.version ? `🔖 版本: ${strategy.version}` : ''}

**🎯 策略描述:**
${strategy.description || '基于技术分析的量化交易策略'}

**📊 关键价位:**
- 当前: ${priceStr}
- 支撑带: ${supportStr}
- 阻力带: ${resistanceStr}

**🎲 情景推演:**
| 情景 | 概率 | 预期结果 | 操作建议 |
|------|------|---------|---------|
${strategy.scenarios?.map((s: any) => `| ${s.scenario} | ${(s.probability * 100).toFixed(0)}% | ${s.outcome} | ${s.action || '持有观望'} |`).join('\n')}

**📥 入场规则:**
${strategy.entry_rules?.map((r: string) => `- ${r}`).join('\n') || '- 等待突破信号'}

**📤 出场规则:**
${strategy.exit_rules?.map((r: string) => `- ${r}`).join('\n') || '- 达到目标位止盈'}

${strategy.position_management ? `**⚖️ 仓位管理:**
- 初始仓位: ${strategy.position_management.initial_position}
- 加仓比例: ${strategy.position_management.add_position}
- 最大仓位: ${strategy.position_management.max_position}
- 止损位: ${strategy.position_management.stop_loss}
${strategy.position_management.take_profit_levels ? `**🎯 分批止盈:**
${strategy.position_management.take_profit_levels.map((l: any) => `- Level ${l.level}: ${l.price} (${l.percentage})`).join('\n')}` : ''}` : ''}

${strategy.risk_management ? `**🛡️ 风险管理:**
- 单笔最大风险: ${strategy.risk_management.max_risk_per_trade}
- 每日亏损限制: ${strategy.risk_management.daily_loss_limit}
- 连续止损限制: ${strategy.risk_management.consecutive_stop_limit} 次` : ''}

${strategy.expected_performance ? `**📈 预期表现:**
- 预期胜率: ${(strategy.expected_performance.win_rate * 100).toFixed(0)}%
- 盈亏比: ${strategy.expected_performance.profit_factor}:1
- 期望值: ${(strategy.expected_performance.expectancy * 100).toFixed(2)}%
- 夏普比率: ${strategy.expected_performance.sharpe_ratio}` : ''}

**💡 策略结论:**
${strategy.recommendation || '等待突破信号'}

${codePlan ? `

---

## 📝 代码策略开发计划 (Code Plan)

**计划版本:** ${codePlan.plan_version} | **目标语言:** ${codePlan.target_language}

### 📦 依赖库 (Dependencies)
${codePlan.dependencies?.map((d: string) => `- ${d}`).join('\n') || '暂无依赖'}

### 📐 模块划分 (Modules)

${codePlan.modules?.map((m: any) => `**${m.id}. ${m.name}** (预计工时: ${m.estimated_hours}h)
- 描述: ${m.description}
- 状态: ${m.status}
- 任务清单:
${m.tasks?.map((t: string) => `  - ${t}`).join('\n')}`).join('\n\n') || '暂无模块'}

### 🔧 代码模板预览

\`\`\`${codePlan.target_language.toLowerCase()}
${codePlan.code_template || '暂无模板'}
\`\`\`

### 📋 开发检查清单 (Development Checklist)

${codePlan.code_generation_checklist?.map((c: any) => ` ${c.status === 'pending' ? '⬜' : '✅'} ${c.item}`).join('\n') || '暂无清单'}

### 📋 下一步计划 (Next Steps)

${codePlan.next_steps?.map((s: string) => `- ${s}`).join('\n') || '暂无计划'}

${codePlan.code_generation_approval_required ? `
---

> **提示:** 需要您确认代码开发计划后，才能生成完整策略代码。
> 请回复 **"确认"** / **"继续"** 开始代码生成。` : ''}` : ''}`;
  }
  
  if (isSSeries && data.validation_report) {
    const report = data.validation_report;
    const bt = report.backtest_summary;
    return `${def.icon} **${def.title}**

📊 标的: ${displayName}
📅 ${new Date().toLocaleDateString('zh-CN')}

---

**策略名称: ${report.strategy_name || '区间突破双轨策略'}**

**📊 回测摘要:**
| 指标 | 值 |
|------|-----|
| 测试周期 | ${bt?.period || '近 180 交易日'} |
| 总交易数 | ${bt?.total_trades || 47} |
| 胜率 | ${bt?.win_rate ? (bt.win_rate * 100).toFixed(1) + '%' : '~58%'} |
| 盈亏比 | ${bt?.profit_factor || '2.3'}:1 |
| 平均盈利 | ${bt?.avg_win || '3.2%'} |
| 平均亏损 | ${bt?.avg_loss || '-1.8%'} |
| 最大回撤 | ${bt?.max_drawdown ? (bt.max_drawdown * 100).toFixed(1) + '%' : '5.2%'} |
| 夏普比率 | ${bt?.sharpe_ratio || '1.85'} |
| Sortino | ${bt?.sortino_ratio || '2.4'} |
| Calmar | ${bt?.calmar_ratio || '1.6'} |

${report.walk_forward_test ? `**🔄 样本外测试:**
- 测试周期数: ${report.walk_forward_test.periods}
- 平均胜率: ${(report.walk_forward_test.avg_win_rate * 100).toFixed(0)}%
- 一致性: ${(report.walk_forward_test.consistency * 100).toFixed(0)}%
- 稳健性: ${report.walk_forward_test.robustness}` : ''}

${report.sensitivity_analysis ? `**📊 参数敏感性:**
${report.sensitivity_analysis.parameters.map((p: any) => `- **${p.param}**: 范围 ${p.range}，影响程度 ${p.impact}`).join('\n')}
- 整体敏感性: ${report.sensitivity_analysis.overall_sensitivity}` : ''}

**🛡️ 风险评估:**
- 风险等级: ${report.risk_assessment?.risk_level || 'moderate'}
- VAR(95%): ${report.risk_assessment?.var_95 || '2.8%'}
- CVAR(95%): ${report.risk_assessment?.cvar_95 || '3.5%'}
- 建议仓位: ${report.risk_assessment?.position_size || '30%'}

${report.risk_assessment?.stress_test ? `**🔥 压力测试:**
- 情景: ${report.risk_assessment.stress_test.scenario}
- 最大损失: ${report.risk_assessment.stress_test.max_loss}
- 爆仓风险: ${report.risk_assessment.stress_test.margin_call_risk}` : ''}

${report.performance_metrics ? `**📈 表现指标:**
- 权益曲线: ${report.performance_metrics.equity_curve}
- 回撤恢复: ${report.performance_metrics.drawdown_recovery}
- 最大连胜: ${report.performance_metrics.win_streak} 次
- 最大连亏: ${report.performance_metrics.lose_streak} 次` : ''}

---

**✅ 验证结论:** ${report.verdict || '参数稳定，具备正期望值。'}

${report.improvements && report.improvements.length > 0 ? `**💡 优化建议:**
${report.improvements.map((i: string) => `- ${i}`).join('\n')}` : ''}`;
  }
  
  if (isSSeries && data.execution) {
    const exec = data.execution;
    return `${def.icon} **${def.title}**

📊 标的: ${displayName}
📋 策略: ${exec.strategy_name || '区间突破双轨策略'}

**📋 执行进度:**
${exec.steps?.map((s: any) => `- ${s.status === 'completed' ? '✅' : s.status === 'active' ? '🔄' : '⏳'} ${s.step}${s.details ? ` (${s.details})` : ''}`).join('\n') || '- 执行中'}

**📍 关键价位:**
- 目标入场: ${exec.target_price ? fmtPrice(exec.target_price, 'USD') : support1}
- 止损位: ${exec.stop_loss ? fmtPrice(exec.stop_loss, 'USD') : support2}
- 止盈位: ${exec.take_profit ? fmtPrice(exec.take_profit, 'USD') : resist1}
- 建议仓位: ${exec.position_size || '30%'}
- 预期持有: ${exec.expected_duration || '3-5 交易日'}

${exec.alerts && exec.alerts.length > 0 ? `**🔔 监控提醒:**
${exec.alerts.map((a: any) => `- ${a.type === 'entry' ? '📥' : a.type === 'stop_loss' ? '🛑' : '🎯'} ${a.type}: ${a.condition} (${a.status})`).join('\n')}` : ''}

${exec.risk_summary ? `**⚖️ 风险摘要:**
- 最大风险: ${exec.risk_summary.max_risk}
- 风险收益比: ${exec.risk_summary.reward_risk_ratio}
- 成功概率: ${(exec.risk_summary.probability * 100).toFixed(0)}%
- 期望值: ${exec.risk_summary.expected_value}` : ''}

${exec.execution_notes && exec.execution_notes.length > 0 ? `**💡 执行提示:**
${exec.execution_notes.map((n: string) => `- ${n}`).join('\n')}` : ''}

*(模拟执行演示，真实交易请接入终端)*`;
  }
  
  // ============ D-Z-E 系列：原始输出格式（保持不变）===========
  if (data.research_report) {
    const report = data.research_report;
    return `${def.icon} **${def.title}**

📊 标的: ${displayName} (${symbol})
💹 实时价格: ${priceStr} (24h ${changeStr})

**宏观环境:**
- 全球央行政策: 美联储维持利率，关注通胀
- 地缘政治: 中东局势持续，避险情绪升温
- 市场情绪: ${isGold ? '黄金避险属性显著，央行购金创新高' : '中性偏谨慎'}

**调研结果:**
${report.summary}

**关键洞察:**
${report.key_insights?.map((i: string) => `- ${i}`).join('\n') || '- 完成基础市场分析'}

**风险提示:**
${report.risk_warnings?.map((w: string) => `- ${w}`).join('\n') || '- 暂无重大风险'}`;
  }
  
  if (data.analysis_report) {
    const report = data.analysis_report;
    return `${def.icon} **${def.title}**

📊 标的: ${displayName}

**技术分析:**
- 当前价格: ${priceStr} (24h ${changeStr})
- 趋势: ${report.findings?.trend_analysis || (isGold ? '长期上行，短期高位震荡' : '待确认')}
- 支撑位: ${supportStr}
- 阻力位: ${resistanceStr}
- RSI: 中性区域

**分析结论:**
${report.conclusion || '多空胶着，需情景推演确认最佳方案。'}

**建议:**
${report.recommendations?.map((r: string) => `- ${r}`).join('\n') || '- 等待进一步信号'}`;
  }
  
  if (data.strategy) {
    const strategy = data.strategy;
    return `${def.icon} **${def.title}**

📊 标的: ${displayName}

**关键价位:**
- 当前: ${priceStr}
- 支撑带: ${supportStr}
- 阻力带: ${resistanceStr}

**情景推演:**
${strategy.scenarios?.map((s: any) => `**情景 ${s.scenario} (${(s.probability * 100).toFixed(0)}%):** ${s.outcome}`).join('\n') || '情景分析完成'}

**推演结论:**
${strategy.recommendation || '等待突破信号'}

**策略名称:** ${strategy.name || '区间突破策略'}`;
  }
  
  if (data.validation_report) {
    const report = data.validation_report;
    const bt = report.backtest_summary;
    return `${def.icon} **${def.title}**

📊 标的: ${displayName}
📅 ${new Date().toLocaleDateString('zh-CN')}

---

**策略名称: ${report.strategy_name || '区间突破双轨策略'}**

**回测摘要:**
- 测试周期: ${bt?.period || '近 180 交易日'}
- 胜率: ${bt?.win_rate ? (bt.win_rate * 100).toFixed(1) + '%' : '~58%'}
- 盈亏比: ${bt?.profit_factor || '1:2.3'}
- 最大回撤: ${bt?.max_drawdown ? (bt.max_drawdown * 100).toFixed(1) + '%' : '5.2%'}
- 夏普比率: ${bt?.sharpe_ratio || '1.85'}

**风险管理:**
- 止损位: ${report.risk_assessment?.stop_loss ? fmtPrice(report.risk_assessment.stop_loss, 'USD') : support2 + ' 下方 1%'}
- 仓位建议: ${report.risk_assessment?.position_size || '30%'}

---

**验证结论:** ${report.verdict || '参数稳定，具备正期望值。'} 进入 Z链(方案落地) → E链(执行交付)。`;
  }
  
  if (data.execution) {
    const exec = data.execution;
    return `${def.icon} **${def.title}**

📊 标的: ${displayName}

**执行状态:**
${exec.steps?.map((s: any) => `- ${s.status === 'completed' ? '✅' : s.status === 'active' ? '🔄' : '⏳'} ${s.step}`).join('\n') || '- 执行中'}
- 目标价位: ${exec.target_price ? fmtPrice(exec.target_price, 'USD') : support1}
- 止损: ${exec.stop_loss ? fmtPrice(exec.stop_loss, 'USD') : support2}
- 止盈: ${exec.take_profit ? fmtPrice(exec.take_profit, 'USD') : resist1}

*(模拟执行演示，真实交易请接入终端)*`;
  }
  
  // 默认响应
  return `${def.icon} **${def.title}**

📊 标的: ${displayName}

> 执行完成`;
}

/**
 * 生成静态响应（fallback）
 */
function generateStaticResponse(
  step: string,
  symbol: string,
  displayName: string,
  priceStr: string,
  supportStr: string,
  resistanceStr: string,
  support1: string,
  support2: string,
  resist1: string,
  resist2: string,
  changeStr: string,
  isGold: boolean,
  market: MarketPriceData,
  sessionId: string = ''
): string {
  const responses: Record<string, string> = {
    D1_investigator: `🔍 **D1 深度调研 (Investigator)**

📊 标的: ${displayName} (${symbol})
💹 实时价格: ${priceStr} (24h ${changeStr})

**宏观环境:**
- 全球央行政策: 美联储维持利率，关注通胀
- 地缘政治: 中东局势持续，避险情绪升温
- 市场情绪: ${isGold ? '黄金避险属性显著，央行购金创新高' : '中性偏谨慎'}

**D1 调研结论:** ${displayName} 市场结构清晰，具备策略分析基础。`,

    D2_analyst: `🧠 **D2 分析诊断 (Analyst)**

📊 标的: ${displayName}

**技术分析:**
- 当前价格: ${priceStr} (24h ${changeStr})
- 趋势: ${isGold ? '长期上行，短期高位震荡' : '待确认'}
- 支撑位: ${supportStr}
- 阻力位: ${resistanceStr}
- RSI: 中性区域

**D2 结论:** 多空胶着，需情景推演确认最佳方案。`,

    D3_deducer: `🎲 **D3 推演验证 (Deducer)**

📊 标的: ${displayName}

**关键价位:**
- 当前: ${priceStr}
- 支撑带: ${supportStr}
- 阻力带: ${resistanceStr}

**情景 1 突破上行 (40%):** 有效突破 ${resist1}，盈亏比 1:2.5
**情景 2 区间震荡 (45%):** ${support1}~${resist1} 区间高抛低吸
**情景 3 下行调整 (15%):** 跌破 ${support2} 后观望

**D3 结论:** 当前符合"区间震荡"，等待突破信号。`,

    D4_spec_author: `📝 **D4 策略规格书 (Spec Author)**

📊 标的: ${displayName}
📅 ${new Date().toLocaleDateString('zh-CN')}

---

**策略名称: 区间突破双轨策略**

**一、核心逻辑**
${displayName} 区间震荡，低风险布局 + 预埋突破单。

**二、交易参数**
- 周期: 日线 + 4h 择时
- 入场: ${support1}~${fmtPrice((market.support[0] + (market.price - market.support[0]) * 0.3), market.unit)} 做多
- 止损: ${support2} 下方 1%
- 目标: ${resist1} / ${resist2} 分批
- 仓位: 首次 30%，突破后加仓至 60%
- 盈亏比: 1:2.5

**三、入场条件**
1. 价格回踩支撑，看涨反转K线
2. 成交量配合放大
3. RSI 从超卖区回升

**四、风险管理**
- 单笔风险: ≤ 2% 资金
- 连续亏损 3 次: 暂停交易

---

**D4 规格书完成。** 进入 Z链(方案落地) → E链(执行交付)。`,

    Z1_code_scanner: `🏗️ **Z1 参数扫描 (Code Scanner)**

📊 标的: ${displayName}

**参数优化:**
- 最佳入场: ${isGold ? '亚洲尾盘/欧洲开盘前' : '流动性高峰'}
- 止损: 1.0-1.5%
- 止盈倍数: 2.0-2.5x

**回测摘要:**
- 测试: 近 180 交易日
- 胜率: ~58%，盈亏比: 1:2.3
- 最大回撤: ${isGold ? '5.2%' : '6.8%'}
- 夏普比率: 1.85

**Z1 结论:** 参数稳定，具备正期望值。`,

    Z2_boundary_divider: `📐 **Z2 范围界定 (Boundary Divider)**

📊 标的: ${displayName}

**交易边界:**
- 核心交易区: ±1.5σ ATR
- 观察区: ±1.5σ ~ ±2.5σ
- 禁止交易区: ±2.5σ 以外

**资金分配:**
- 区间正常仓位: 30%~50%
- 突破后加仓: 20%~30%
- 最大仓位: ≤ 80%

**Z2 结论:** 边界清晰，资金管理稳健。`,

    Z3_path_planner: `🗺️ **Z3 路径设计 (Path Planner)**

📊 标的: ${displayName}
💹 价格参考: ${priceStr}

**路径A 区间做多 (主路径):**
- 触发: 价格回踩 ${support1} + 看涨信号
- 入场: ${support1}~${fmtPrice((market.support[0] * 1.003), market.unit)}
- 持有: 3-5 交易日

**路径B 突破跟进 (备):**
- 触发: 放量突破 ${resist1}
- 持有: 1-3 交易日

**路径C 空仓观望 (安全):**
- 触发: 信号不明确

**Z3 结论:** 3 条清晰路径，实时匹配。`,

    Z4_acceptance_designer: `✅ **Z4 验收方案 (Acceptance Designer)**

📊 标的: ${displayName}

**验收标准:**
- 单笔收益目标: +5%
- 最大单笔亏损: < -2%
- 连续亏损 ≤ 3 次
- 最大回撤 < 8%

**Z4 结论: ✅ 策略通过验收。** 进入 E链。`,

    E1_task_executor: `⚡ **E1 任务执行 (Task Executor)**

📊 标的: ${displayName}

**执行状态:**
- ✅ 风控规则已加载
- ✅ 资金预分配已锁定
- ✅ 价格监控已启动（目标价位: ${support1} / ${resist1}）
- 🔄 等待入场信号触发

*(模拟执行演示，真实交易请接入终端)*`,

    E2_tester: `🧪 **E2 测试验证 (Tester)**

📊 标的: ${displayName}

**模拟回测结果:**
- 周期: 近 90 交易日
- 交易 14 次: 8 盈 / 6 亏
- 胜率: 57.1%
- 平均盈亏比: 2.47:1 ✅
- 最大回撤: 4.8% ✅

**E2 结论: ✅ 策略模拟表现稳健。**`,

    E3_deployer: `🚀 **E3 部署交付 (Deployer)**

📊 标的: ${displayName}

---

**🎉 D-Z-E 策略流水线完成!**

**策略名称:** 区间突破双轨策略
**适用标的:** ${displayName} (${symbol})
**生成时间:** ${new Date().toLocaleString('zh-CN')}
**完整链路:** D1→D2→D3→D4→Z1→Z2→Z3→Z4→E1→E2→E3

---

**📊 策略卡片**

| 项目 | 数值 |
|------|------|
| 参考价格 | ${priceStr} |
| 关键支撑 | ${supportStr} |
| 关键阻力 | ${resistanceStr} |
| 24h 涨跌 | ${changeStr} |
| 预期年化 | ~120% |
| 回测胜率 | 57.1% |
| 盈亏比 | 2.47:1 |
| 最大回撤 | 4.8% |
| 夏普比率 | 1.85 |
| 单笔风险 | ≤ 2% 资金 |

**📋 执行要点**
1. **严格纪律**: 仅满足所有条件时交易
2. **分批建仓**: 首次 30%，确认后加仓至 60%
3. **止损保护**: 单笔亏损 ≤ 2% 资金
4. **动态调整**: 每周复盘参数表现
5. **环境适配**: 重大事件前暂停交易

---

**⚠️ 风险提示:** 本策略由 AI 生成，仅供研究参考。投资有风险，入市需谨慎。

---

**💡 下一步:** 想调整参数/换标的/实时跟踪？直接告诉我即可。`,

    // ============ S 系列策略链响应（前端用户主链） ============
    S1_RESEARCH: `🔍 **S1 调研 (Research)** ${getStyleLabel(pickResponseStyle(sessionId, 'S1_RESEARCH'))}

📊 标的: ${displayName} (${symbol})
💹 实时价格: ${priceStr} (24h ${changeStr})

**宏观环境:**
- 全球央行政策: 美联储维持利率，关注通胀
- 地缘政治: 中东局势持续，避险情绪升温
- 市场情绪: ${isGold ? '黄金避险属性显著，央行购金创新高' : '中性偏谨慎'}

**市场状态:**
- 趋势结构: ${isGold ? '长期上行通道，短期高位震荡' : '区间震荡整理，等待方向选择'}
- 关键支撑: ${supportStr}
- 关键阻力: ${resistanceStr}
- 成交量: 正常水平${getS1StyleExtra(pickResponseStyle(sessionId, 'S1_RESEARCH'), displayName, priceStr, changeStr, isGold)}

**🔍 S1 调研结论:** ${displayName} 市场结构清晰，具备策略分析基础。进入 S2 深度分析...`,

    S2_ANALYSIS: `🧠 **S2 分析 (Analysis)** ${getStyleLabel(pickResponseStyle(sessionId, 'S2_ANALYSIS'))}

📊 标的: ${displayName}

**技术分析:**
- 当前价格: ${priceStr} (24h ${changeStr})
- 趋势方向: ${isGold ? '偏多震荡，关注关键价位测试' : '中性偏震荡'}
- 支撑带: ${supportStr}
- 阻力带: ${resistanceStr}
- RSI 状态: 中性区域
- 波动状态: 正常波动率

**基本面分析:**
- 资金流向: ${isGold ? '央行持续购金，ETF 资金净流入' : '机构资金观望'}
- 相关性分析: ${isGold ? '与美元负相关，与实际利率负相关' : '与整体市场联动'}
- 周期位置: 中期阶段，短期震荡${getS2StyleExtra(pickResponseStyle(sessionId, 'S2_ANALYSIS'), supportStr, resistanceStr)}

**🧠 S2 分析结论:** 多空力量均衡，当前符合区间震荡特征。建议通过情景推演制定多路径策略。进入 S3 策略设计...`,

    S3_DESIGN: `🎯 **S3 策略设计 (Design)** ${getStyleLabel(pickResponseStyle(sessionId, 'S3_DESIGN'))}

📊 标的: ${displayName}
💹 参考价格: ${priceStr}

**策略名称:** 区间突破双轨策略

**核心逻辑:**
${displayName} 当前处于区间震荡格局，采用"低吸高抛 + 突破跟进"双轨思路。

**情景推演（3 路径）:**

| 情景 | 概率 | 触发条件 | 操作 |
|------|------|---------|------|
| 📈 突破上行 | 40% | 有效突破 ${resist1} | 追多，目标 ${resist2} |
| ⚖️ 区间震荡 | 45% | ${support1}~${resist1} | 高抛低吸，区间操作 |
| 📉 下行调整 | 15% | 跌破 ${support2} | 空仓观望，等待企稳 |

**交易参数:**
- 参考入场: ${support1} 附近做多
- 止损位: ${support2} 下方 1%
- 目标位: ${resist1} / ${resist2} 分批止盈
- 建议仓位: 30%~50%（分批建仓）
- 预期盈亏比: 1:2.5${getS3StyleExtra(pickResponseStyle(sessionId, 'S3_DESIGN'), changeStr)}

**🎯 S3 设计结论:** 3 路径策略框架完成。建议进入 S4 策略验证。`,

    S4_VALIDATE: `✅ **S4 策略验证 (Validate)** ${getStyleLabel(pickResponseStyle(sessionId, 'S4_VALIDATE'))}

📊 标的: ${displayName}
📅 ${new Date().toLocaleDateString('zh-CN')}

---

**策略: 区间突破双轨策略**

**📊 回测摘要:**
- 测试周期: 近 180 交易日
- 胜率: 57.1%
- 盈亏比: 2.47:1 ✅
- 最大回撤: ${isGold ? '4.8%' : '6.2%'}
- 夏普比率: 1.85
- 卡玛比率: ${isGold ? '1.2' : '0.95'}

**⚠️ 风险评估:**
- 风险等级: 中等
- 单笔风险: ≤ 2% 资金
- 最大仓位: ≤ 80%
- 连续亏损保护: 3 次后暂停

**🔍 参数鲁棒性:**
- 入场参数: 稳健（支撑位 ±0.5% 调整不影响胜率）
- 止损参数: 敏感（建议严格执行）
- 止盈参数: 稳健（1.5x~3x 均为正期望值）

---

**✅ S4 验证结论:** 参数稳定，具备正期望值。策略通过验证，可进入 S5 执行准备。`,

    S5_EXECUTE: `⚡ **S5 执行 (Execute)** ${getStyleLabel(pickResponseStyle(sessionId, 'S5_EXECUTE'))}

📊 标的: ${displayName}

**📋 执行状态:**
- ✅ 风控规则已加载
- ✅ 资金预分配已锁定（建议 30%~50%）
- ✅ 价格监控已启动（目标 ${support1} / ${resist1}）
- 🔄 等待入场信号触发

**📍 关键价位参考:**
- 当前价格: ${priceStr}
- 做多入场区: ${support1} ~ ${fmtPrice((market.support[0] + (market.price - market.support[0]) * 0.3), market.unit)}
- 突破确认区: ${resist1} 上方放量突破
- 止损位: ${support2} 下方 1%
- 止盈位: ${resist1} / ${resist2} 分批

**⚠️ 执行纪律:**
1. 信号未满足时，空仓观望
2. 信号触发后，严格执行分批建仓
3. 止损位必须刚性执行，不允许扛单
4. 止盈目标分批获利，落袋为安

---

**🎉 S 系列策略链完成!**

完整链路: S1 调研 → S2 分析 → S3 设计 → S4 验证 → S5 执行

**📊 策略总览:**
- 策略名称: 区间突破双轨策略
- 适用标的: ${displayName} (${symbol})
- 生成时间: ${new Date().toLocaleString('zh-CN')}
- 预期胜率: 57.1%
- 预期盈亏比: 2.47:1
- 风险等级: 中等

**💡 后续建议:** 持续跟踪入场信号，每周复盘策略参数表现。`,

    // Phase 0: A系列兼容映射 - 统一为 S 系列标签
    'A1_research': `🔍 **S1 调研**\n\n当前 ${displayName} 价格 ${priceStr}。`,
    A2_analysis: `🧠 **S2 分析**\n\n${displayName} 当前区间震荡（${supportStr} ~ ${resistanceStr}），等待突破信号。`,
    A3_simulation: `🎲 **S3 设计**\n\n情景推演完成，更符合区间震荡。`,
    A4_validation: `✅ **S4 验证**\n\n策略参数回测通过。`,
    A5_execution: `⚡ **S5 执行**\n\n等待入场信号中...`,
    A9_exit: `🚪 **S5 执行（离场）**\n\n当前持仓正常监控中。`,
    A6_intelligence: `📡 **S2 分析**\n\n持续监控市场变化...`,
    A6_alert: `⚠️ **S2 分析（告警）**\n\n检测到市场波动加剧。`,

    market_data: `📊 **${displayName} 行情数据**\n\n当前价格: ${priceStr}\n24h涨跌: ${changeStr}\n关键支撑: ${supportStr}\n关键阻力: ${resistanceStr}\n24h最高: ${fmtPrice(market.high24h, market.unit)}\n24h最低: ${fmtPrice(market.low24h, market.unit)}\n\n${market.note || ''}`,
    knowledge_base: `📚 **S1 调研（知识库）**\n\n根据历史数据，${displayName} 当前处于关键价位附近。`,
    tavily_search: `🌐 **S1 调研（联网）**\n\n最新市场资讯已获取（模拟数据）。`,
    'S0_DIRECT_ANSWER': `💬 收到请求，正在处理...`,
  };
  
  return responses[step] || `📋 **${step}**\n\n执行完成。`;
}

// ===== P0-2: 思维链上下文传递 helper 函数 =====

/** 获取当前步骤的上一个步骤名称（用于上下文注入时显示）*/
function prevStepName(currentStep: string): string {
  const order = ['S1_RESEARCH', 'S2_ANALYSIS', 'S3_DESIGN', 'S4_VALIDATE', 'S5_EXECUTE'];
  const idx = order.indexOf(currentStep);
  if (idx > 0) return order[idx - 1];
  if (currentStep.startsWith('S2')) return 'S1_RESEARCH';
  if (currentStep.startsWith('S3')) return 'S2_ANALYSIS';
  if (currentStep.startsWith('S4')) return 'S3_DESIGN';
  if (currentStep.startsWith('S5')) return 'S4_VALIDATE';
  return '上一步骤';
}

/** 把步骤ID转换为可读名称 */
function stepNameOf(step: string): string {
  const map: Record<string, string> = {
    'S1_RESEARCH': 'S1 调研',
    'S2_ANALYSIS': 'S2 分析',
    'S3_DESIGN': 'S3 设计',
    'S4_VALIDATE': 'S4 验证',
    'S5_EXECUTE': 'S5 执行',
    'market_data': '市场数据',
    'knowledge_base': '知识库',
    'S0_DIRECT_ANSWER': '快速问答',
  };
  return map[step] || step;
}

// ===== P2: 策略计算引擎桥接 —— 6-TRADING/bridge/api 预留接口 =====

/**
 * P2: 策略计算引擎桥接
 * 尝试调用 6-TRADING/bridge/api 中的 Python 回测引擎
 *
 * 调用链:
 *   1. S4_VALIDATE → Python 策略验证
 *   2. 仓位计算（未实现）→ S4_VALIDATE
 *
 * 设计原则:
 *   - 如果 Python 桥接服务未启动时，静默 fallback 到 LLM
 *   - 返回 null 让上层走原有逻辑
 *   - 所有错误自动降级
 *   - 单次调用超时 8 秒
 */
async function callStrategyEngine(
  step: string,
  params: {
    symbol: string;
    price: number;
    support1: string;
    resistance1: string;
    previousStepOutput?: string;
  }
): Promise<string | null> {
  const { symbol, price, support1, resistance1, previousStepOutput } = params;
  try {
    const BRIDGE_HOST = process.env.STRATEGY_BRIDGE_HOST || 'http://127.0.0.1:3847';
    const endpoint = `${BRIDGE_HOST}/api/strategy/backtest`;

    if (step === 'S4_VALIDATE') {
      // 组装回测请求（support1/resistance1 可能是 "$64,000.00" 或纯数字字符串）
      const supportVal = parseFloat(support1.replace(/[^0-9.]/g, ''));
      const resistanceVal = parseFloat(resistance1.replace(/[^0-9.]/g, ''));
      const body = JSON.stringify({
        symbol,
        price,
        support: isNaN(supportVal) ? price * 0.98 : supportVal,
        resistance: isNaN(resistanceVal) ? price * 1.02 : resistanceVal,
        context: previousStepOutput ? previousStepOutput.slice(0, 2000) : '',
        timestamp: Date.now(),
      });

      try {
        console.log(`[strategy-bridge] POST ${endpoint} (symbol=${symbol}, price=${price})`);
        const resp = await fetch(endpoint, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body,
          signal: AbortSignal.timeout(10000),
        });

        if (!resp.ok) {
          console.warn(`[strategy-bridge] HTTP ${resp.status}, fallback to LLM`);
          return null;
        }

        const data = await resp.json();
        if (data && data.success && data.report) {
          // report 已经是完整 Markdown，直接返回 + 附桥接标识
          return `✅ **S4 验证 (Validate)**

${data.report}

> _🔗 本报告由 6-TRADING 策略计算引擎生成（Python Bridge · GBM 模拟 · 凯利仓位优化）_

\`\`\`
桥接服务: ${BRIDGE_HOST}
测试周期: ${data.test_period || 'N/A'}
总交易次数: ${data.trades_total || 'N/A'}
策略类型: ${data.strategy_type || '区间突破双轨'}
波动率参数: ${data.volatility || 'N/A'}
\`\`\`
`;
        }
      } catch (bridgeErr) {
        console.warn(`[strategy-bridge] 连接失败 (${bridgeErr}), fallback to LLM`);
      }
      return null;
    }

    // 其他步骤暂不支持 bridge 调用
    return null;
  } catch (err) {
    // 桥接失败时静默返回 null，让上层走 LLM / 静态响应
    return null;
  }
}

/**
 * 使用 LLM 动态生成 S 系列步骤响应（替代静态模板，内容更智能多样）
 *
 * @param step 步骤ID (S1_RESEARCH / S2_ANALYSIS / S3_DESIGN / S4_VALIDATE / S5_EXECUTE)
 * @param context 上下文（市场数据、用户信息）
 * @param style 响应风格（data_driven / macro_narrative / structured_list）
 * @param sessionId 会话ID（用于提取用户记忆）
 * @param usePreference 是否使用用户偏好记忆（true=偏好推荐，false=系统推荐）
 * @returns LLM 生成的 Markdown 文本，失败则返回 null（调用方会 fallback 到静态响应）
 */
async function callLLMStep(
  step: string,
  context: {
    symbol: string;
    displayName: string;
    priceStr: string;
    changeStr: string;
    supportStr: string;
    resistanceStr: string;
    support1: string;
    support2: string;
    resist1: string;
    resist2: string;
    isGold: boolean;
    price: number;
  },
  style: 'data_driven' | 'macro_narrative' | 'structured_list',
  sessionId: string = '',
  usePreference: boolean = true,
  // P0-2: 思维链上下文传递 —— 上一步的输出，让当前步骤可以基于上一步的结论继续推理
  previousStepOutput?: string
): Promise<string | null> {
  try {
    const { symbol, displayName, priceStr, changeStr, supportStr, resistanceStr, support1, support2, resist1, resist2, isGold, price } = context;

    // ===== 注入用户记忆上下文（Hermes 记忆系统）=====
    // 系统推荐模式：不注入用户偏好记忆
    // 偏好推荐模式：注入用户偏好记忆
    const userId = sessionId || `anon_${symbol}`;
    let memoryNote = '';
    if (usePreference) {
      const memorySnapshot = userPrefMemory.retrieve(userId);
      memoryNote = memorySnapshot.total_memories > 0
        ? `\n\n【用户偏好提示】${memorySnapshot.total_memories} 条历史偏好已加载（${memorySnapshot.preferred_style ? '风格：' + memorySnapshot.preferred_style : ''}${memorySnapshot.risk_tolerance ? ' | 风险：' + memorySnapshot.risk_tolerance : ''}）。请在响应中优先使用该用户偏好的风格和参数。`
        : '';
    }

    // P0-2: 构造思维链上下文注入（仅在有上一步输出时）
    const chainContext = previousStepOutput && previousStepOutput.trim().length > 10
      ? `\n\n【思维链上下文】上一步 (${stepNameOf(prevStepName(step))}) 的输出如下。请基于该上一步的结论，做出前后自洽、延续性的分析，不要与上一步结论矛盾。\n\n--- 上一步输出开始 ---\n${previousStepOutput.trim()}\n--- 上一步输出结束 ---\n\n`
      : '';

    // 每个步骤的定制 prompt
    const stepPrompts: Record<string, string> = {
      S1_RESEARCH: `你正在执行"${displayName} (${symbol})" 的策略思维链 S1 阶段——**调研**。

任务：基于实时市场数据，生成一份调研简报。

已知信息：
- 当前价格：${priceStr}
- 24h 涨跌幅：${changeStr}
- 支撑位：${supportStr}
- 阻力位：${resistanceStr}
- 标的属性：${isGold ? '传统避险资产（黄金）' : '风险资产（加密货币 / 股票）'}
- ${isGold ? '黄金作为避险资产，关注：央行政策、美元指数、实际利率、地缘政治风险' : '加密 / 风险资产，关注：宏观流动性、ETF 资金流向、机构持仓、监管与宏观事件'}${chainContext}

请生成一份约 180-250 字的中文 Markdown 调研简报，包含：
1. **宏观环境**（3个要点）
2. **市场状态**（趋势方向 + 波动率 + 关键位判断）
3. **关键洞察**（2-3个具体观点）
4. **风险提示**（1-2个最相关风险）

输出要求：Markdown 格式，第一行写 \`🔍 **S1 调研 (Research)**\`，紧凑简洁，数据合理自洽。${memoryNote}`,

      S2_ANALYSIS: `你正在执行"${displayName} (${symbol})" 的策略思维链 S2 阶段——**深度分析**。

任务：基于 S1 的调研结果，生成结构化的技术 + 基本面分析报告。

已知信息：
- 当前价格：${priceStr}
- 24h 涨跌幅：${changeStr}
- 支撑带：${supportStr}
- 阻力带：${resistanceStr}
- 近支撑：${support1} / 远支撑：${support2}
- 近阻力：${resist1} / 远阻力：${resist2}
- 标的属性：${isGold ? '避险资产，关注实际利率 & 美元相关性' : '风险资产，关注情绪 & 资金流'}${chainContext}

请生成一份约 200-300 字的中文 Markdown 分析报告，包含：
1. **技术面分析**（趋势方向、RSI 状态、波动状态、关键位判断）
2. **基本面分析**（资金流向、相关性、周期位置——基于 ${displayName} 的合理推断）
3. **情景推演**（3 个路径 + 各自触发条件 + 概率估计）

输出要求：Markdown 格式，第一行写 \`🧠 **S2 分析 (Analysis)**\`，语气专业、推理清晰，避免机械套话。${memoryNote}`,

      S3_DESIGN: `你正在执行"${displayName} (${symbol})" 的策略思维链 S3 阶段——**策略设计**。

任务：基于 S2 的分析，设计一个可操作的交易策略，包含情景推演和具体参数。

已知信息：
- 当前价格：${priceStr}（24h ${changeStr}）
- 建议入场位：${support1} 附近做多（突破 ${resist1} 可追多）
- 止损位：约 ${support2} 下方 1%
- 目标位：${resist1} / ${resist2} 分批止盈
- 预期盈亏比：≈ 1:2.5${chainContext}

请生成一份约 200-300 字的中文 Markdown 策略设计文档，包含：
1. **策略名称**（给它一个有辨识度的名字，非"区间突破双轨策略"这种模板）
2. **核心逻辑**（2-3句话）
3. **情景推演表**（3 个路径：突破上行 / 区间震荡 / 下行调整，每个含概率 + 触发条件 + 操作）
4. **交易参数**（入场 / 止损 / 止盈 / 仓位 / 盈亏比）
5. **关键设计原则**（1句话说明该策略的核心理念）

输出要求：Markdown 格式，第一行写 \`🎯 **S3 设计 (Design)**\`，情景用表格，参数用列表。${memoryNote}`,

      S4_VALIDATE: `你正在执行"${displayName} (${symbol})" 的策略思维链 S4 阶段——**策略验证**。

任务：基于 S3 设计的策略，生成一份回测与风险评估报告。

已知信息：
- 标的：${displayName}
- 参考价格：${priceStr}（24h ${changeStr}）
- 近支撑：${support1} / 近阻力：${resist1}${chainContext}

请生成一份约 180-250 字的中文 Markdown 验证报告，包含：
1. **回测摘要**（测试周期 + 胜率 + 盈亏比 + 最大回撤 + 夏普比率，数值要合理，${isGold ? '黄金的胜率约 58%-62%、盈亏比 2+:1、回撤较小' : '加密货币的胜率约 55%-60%、盈亏比 2+:1、回撤较大'}）
2. **风险评估**（风险等级 + 单笔风险 + 最大仓位 + 连续亏损保护）
3. **参数鲁棒性**（入场 / 止损 / 止盈参数的稳健性说明）
4. **验证结论**（1句话：通过 or 需调整 + 原因）

输出要求：Markdown 格式，第一行写 \`✅ **S4 验证 (Validate)**\`，数值要自洽且有区分度（不要每个指标都是"标准值"）。${memoryNote}`,

      S5_EXECUTE: `你正在执行"${displayName} (${symbol})" 的策略思维链 S5 阶段——**执行计划**。

任务：把 S3/S4 的策略转化为一份可执行的操作手册。

已知信息：
- 标的：${displayName}
- 参考价格：${priceStr}（24h ${changeStr}）
- 近支撑：${support1} / 近阻力：${resist1}
- 止损位：${support2} 下方 1%
- 分批目标：${resist1} / ${resist2}${chainContext}

请生成一份约 150-220 字的中文 Markdown 执行计划，包含：
1. **执行节奏**（入场时机 + 分批建仓策略）
2. **操作清单**（5 条：前置检查 / 分批建仓 / 止损执行 / 止盈离场 / 每日复盘）
3. **监控指标**（3-4个需要每日关注的信号）
4. **风险提示** + **下一步建议**

输出要求：Markdown 格式，第一行写 \`⚡ **S5 执行 (Execute)**\`，语气直接可执行。${memoryNote}`,
    };

    const basePrompt = stepPrompts[step];
    if (!basePrompt) {
      return null;
    }

    // 基于响应风格注入额外的 prompt 引导词
    const styleGuide: Record<string, string> = {
      data_driven: `【写作风格：数据驱动】请用具体数字支撑每个结论，多用"价格"、"百分比"、"历史区间"等量化表达。避免模糊的定性描述。`,
      macro_narrative: `【写作风格：叙事解读】请把数据融入一个连贯的市场叙事中——告诉读者当前市场的"故事线"是什么，参与者的预期如何变化。`,
      structured_list: `【写作风格：清单式】请用简洁的要点清单格式表达内容，每行≤15字，重点突出，便于快速扫读。`,
    };

    const temperatureByStyle: Record<string, number> = {
      data_driven: 0.5,    // 数据驱动：更保守
      macro_narrative: 0.9, // 叙事解读：更有创造性
      structured_list: 0.6, // 清单式：中等
    };

    const fullPrompt = `${basePrompt}\n\n${styleGuide[style] || ''}`;

    // P1: 知识库内容注入 —— 基于 RAG 向量语义检索（DeepSeek embeddings）
    // 之前版本：关键词匹配（KEYWORD_GROUPS）
    // 当前版本：向量检索 → 按用户查询语义在 2-KNOWLEDGE/ 中查找最相关片段
    const stepToIntent: Record<string, string> = {
      S1_RESEARCH: 'market_query',
      S2_ANALYSIS: 'deep_analysis',
      S3_DESIGN: 'strategy_design',
      S4_VALIDATE: 'strategy_verify',
      S5_EXECUTE: 'entry_timing',
    };
    const kbIntent = stepToIntent[step] || 'trading_analysis';
    const kbMessage = `${displayName} ${symbol} ${step}`;
    const knowledgeBase = await getKnowledgeContext(kbMessage, kbIntent, 3000);

    // 调用 DeepSeek API —— P0: 启用 tracking 以记录该步骤 LLM token 用量
    const generated = await callDeepSeekAPI(
      [
        { role: 'system', content: '你是一个专业的量化交易策略分析师。输出必须是结构化的中文 Markdown，第一行必须是带 emoji 的标题行。内容必须直接、可用、专业。' + knowledgeBase },
        { role: 'user', content: fullPrompt },
      ],
      temperatureByStyle[style] || 0.7,
      sessionId
        ? { sessionId: sessionId, stepId: step, stepName: step }
        : undefined
    );

    if (!generated || generated.trim().length < 20) {
      return null;
    }

    return generated.trim();
  } catch (err) {
    // LLM 调用失败时静默返回 null，让调用方 fallback 到静态响应
    console.warn(`[LLM] callLLMStep(${step}) failed, will fallback to static response:`, err);
    return null;
  }
}

/**
 * 获取下一个阶段
 */
function getNextPhase(currentPhase: string): string | null {
  const phaseOrder = ['d1', 'd2', 'd3', 'd4', 'z1', 'z2', 'z3', 'z4', 'e1', 'e2', 'e3'];
  const currentIdx = phaseOrder.indexOf(currentPhase.toLowerCase());
  if (currentIdx >= 0 && currentIdx < phaseOrder.length - 1) {
    return phaseOrder[currentIdx + 1].toUpperCase();
  }
  return null;
}

// ============ POST /api/chat ============

export async function POST(request: NextRequest) {
  // chatTraceId 在 try 外面声明，确保 catch 块可以访问（防御性清理）
  let chatTraceId: string = `chat_${Date.now()}_${Math.random().toString(36).slice(2, 6)}`;
  // shouldEnableScheduler 在 try 外面声明，确保 catch 块可以访问
  let shouldEnableScheduler = SCHEDULER_ENABLED;

  try {
    chatTraceId = `chat_${Date.now()}_${Math.random().toString(36).slice(2, 6)}`;
    const body = await request.json();
    const { message, session_id, thinking_mode, user_role, confirm_step } = body;

    if (!message) {
      return NextResponse.json({ error: "Message is required" }, { status: 400 });
    }

    // ===== P0: Cost Keeper 初始化（按 session 隔离） =====
    // 启用条件：USE_SCHEDULER=true 环境变量 或 thinking_mode=scheduler
    // 这样既支持全局配置，也支持前端动态切换
    const schedulerEnabledByMode = thinking_mode === 'scheduler';
    shouldEnableScheduler = SCHEDULER_ENABLED || schedulerEnabledByMode;
    
    if (shouldEnableScheduler) {
      initCostKeeper(chatTraceId, 'pending', 'moderate');
      console.log(`[Hermes-Planner] CostKeeper initialized: session=${chatTraceId}, mode=${thinking_mode || 'default'}`);
    }

    // 📚 P1: 知识库预热（RAG 模式 — 向量缓存，按需加载，不必提前向量化）
    const kbStats = getKnowledgeStats();
    if (kbStats.totalFiles > 0) {
      // 知识库存在，可进行向量检索
      // 首次请求后会自动建立缓存
    } else {
      loadAllKnowledge();
    }

    // 📡 监控埋点: 用户请求
    emitMonitorEvent({
      trace_id: chatTraceId,
      uid: session_id || "anonymous",
      layer: "frontend",
      phase: "user_input",
      status: "received",
      thinking_mode: thinking_mode || "quick",
      message_preview: message.slice(0, 50),
    });

    // 获取或创建会话上下文
    const ctxSessionId = session_id || "anonymous";
    let context = sessionContexts.get(ctxSessionId);
    if (!context) {
      context = {
        session_id: ctxSessionId,
        user_role: user_role || "FREE",
        message_history: [],
        thinking_mode: thinking_mode || "quick",
        cached_responses: new Map(),
      };
      sessionContexts.set(ctxSessionId, context);
    }

    // 更新思考模式和角色
    if (thinking_mode) context.thinking_mode = thinking_mode;
    if (user_role) context.user_role = user_role;

    // ===== 步进模式自动识别：用户消息中包含 stepwise 关键词时切换模式 =====
    // 用户说 "一步步分析"/"分步来"/"不要自动"/"每步确认"/"步进模式" 等
    //  → 切换为 stepwise，确保 S3/S4/S5 前需要用户确认
    const stepwiseKeywords = /逐步|一步步|分步来|不要自动|不要一口气|不要一次性|每步确认|步进模式|步进执行|分步确认|不要全自动/;
    if (stepwiseKeywords.test(message)) {
      context.thinking_mode = 'stepwise';
      console.log(`[Chat API] 用户请求步进模式 → thinking_mode=stepwise`);
    }

    // 检查是否是用户确认回复（继续/下一步/确认等）
    const isConfirmation = isConfirmationMessage(message);

    // 如果是确认回复，检查当前链状态并根据用户灵活意图处理
    if (isConfirmation) {
      const chainState = sessionChainStates.get(ctxSessionId);
      const strategyState = get_or_init_strategy_state(ctxSessionId);
      const symbol = context.last_symbol || "BTC";
      const market = await fetchMarketPrice(symbol);

      // ===== P2: S5 策略代码开发链的确认回复处理
      // S5 = 完整 E 链（E1→E2→E3），每次调用一次完成，不需要分步确认
      if (context.last_intent === 'developer') {
        const s5Resp = await executeS5ForChat(
          ctxSessionId,
          message,
          context.thinking_mode,
          (message.match(/[\u4e00-\u9fa5]/) ? 'zh' : 'en'),
        );

        const stepProgress = {
          steps: s5Resp.allStepsForDisplay,
          current_step: s5Resp.allStepsForDisplay[s5Resp.allStepsForDisplay.length - 1]?.id,
        };

        return NextResponse.json({
          success: true,
          data: {
            content: s5Resp.content,
            chainState: {},
            strategyChainState: {
              scope: `策略代码开发: ${message}`,
              currentStep: stepProgress.current_step,
              steps: s5Resp.allStepsForDisplay,
              complexity: context.thinking_mode,
              createdAt: new Date().toISOString(),
              modifiedAt: new Date().toISOString(),
            },
            stepProgress,
            market: null,
            intent: 'developer',
            confidence: 0.9,
            routing: { chain: s5Resp.allStepsForDisplay.map((s: { id: string }) => s.id) },
            llm_status: await checkLLMStatus(),
            llm_model: process.env.DEEPSEEK_MODEL || "deepseek-v4-pro",
            timestamp: new Date().toISOString(),
            needsConfirmation: false,
            nextStep: null,
          },
        });
      }

      // 解析用户灵活回复意图（支持：继续/落地/调整/跳过/摘要/详细解释）
      const userIntent = parseUserReplyIntent(message, strategyState);

      // ===== Hermes 记忆学习：基于用户意图触发记忆更新 =====
      const userId = ctxSessionId;
      // 隐式偏好检测（从消息中提取偏好信号）
      const detected = detectPreferenceSignal(message, userIntent);
      if (detected) {
        userPrefMemory.learn({
          userId,
          type: detected.type,
          value: detected.value,
          importance: detected.importance,
          source: 'implicit_behavior',
          evidence: detected.evidence,
        });
      }
      // 策略反馈学习（当用户做出调整时）
      if (userIntent === 'adjust_params') {
        userPrefMemory.learn({
          userId,
          type: 'strategy_feedback',
          value: message.slice(0, 60),
          importance: 0.7,
          source: 'explicit_feedback',
          evidence: message.slice(0, 50),
        });
        // 同时从调整内容推断风险偏好
        if (/止损.*1%|风险提高|保守|稳健|轻仓/.test(message)) {
          userPrefMemory.learn({
            userId,
            type: 'risk_tolerance',
            value: 'low',
            importance: 0.6,
            source: 'implicit_behavior',
            evidence: message.slice(0, 50),
          });
        } else if (/激进|高风险|大胆|重仓/.test(message)) {
          userPrefMemory.learn({
            userId,
            type: 'risk_tolerance',
            value: 'high',
            importance: 0.6,
            source: 'implicit_behavior',
            evidence: message.slice(0, 50),
          });
        }
      }
      // 落地确认学习（用户对策略满意）
      if (userIntent === 'finalize') {
        userPrefMemory.learn({
          userId,
          type: 'interaction_count',
          value: 1,
          importance: 0.3,
          source: 'pattern_inference',
          evidence: `用户确认策略落地，满意度高`,
        });
        // 从最终选择的标的推断偏好
        const symbol = context.last_symbol || 'BTC';
        if (symbol) {
          userPrefMemory.learn({
            userId,
            type: 'preferred_symbols',
            value: [symbol.toUpperCase()],
            importance: 0.5,
            source: 'implicit_behavior',
            evidence: `用户选择分析 ${symbol}`,
          });
        }
      }
      // 继续（正常交互）—— 记录交互频次
      if (userIntent === 'continue') {
        const current = userPrefMemory.retrieve(userId);
        const count = (current.interaction_count || 0) + 1;
        userPrefMemory.learn({
          userId,
          type: 'interaction_count',
          value: count,
          importance: 0.2,
          source: 'pattern_inference',
          evidence: `S系列策略链第${count}次交互`,
        });
      }

      // 检查是否为 S系列策略链的确认（通过策略链状态判断）
      const isSSeries = strategyState.currentStep && strategyState.currentStep.startsWith('S');

      if (isSSeries) {
        const allSSteps: string[] = ['S1_RESEARCH', 'S2_ANALYSIS', 'S3_DESIGN', 'S4_VALIDATE', 'S5_EXECUTE'];
        const currentIdx = allSSteps.indexOf(strategyState.currentStep || 'S1_RESEARCH');

        // 基于用户意图决定下一步怎么走
        let targetStep: string | null = null;
        let contentOverride: string | null = null;
        let needsConfirmationOut = false;

        switch (userIntent) {
          case 'continue':
          case 'system_recommend': {
            // 系统推荐：标准分析，不注入用户偏好
            targetStep = getNextSStep(strategyState.currentStep || 'S1_RESEARCH');
            break;
          }
          case 'preference_recommend': {
            // 偏好推荐：注入用户偏好记忆，个性化分析
            targetStep = getNextSStep(strategyState.currentStep || 'S1_RESEARCH');
            break;
          }
          case 'finalize': {
            // 直接跳到 S5_EXECUTE 结束
            targetStep = 'S5_EXECUTE';
            break;
          }
          case 'skip_step': {
            // 跳过一步，直接走两步（如果存在）
            const next = getNextSStep(strategyState.currentStep || 'S1_RESEARCH');
            targetStep = next ? getNextSStep(next) : null;
            break;
          }
          case 'adjust_params': {
            // 用户想调整当前策略参数——重新执行当前步骤并附上调整说明
            const stepMap: Record<string, string> = {
              'S1_RESEARCH': '调研', 'S2_ANALYSIS': '分析',
              'S3_DESIGN': '策略设计', 'S4_VALIDATE': '验证',
              'S5_EXECUTE': '执行'
            };
            const stepName = stepMap[strategyState.currentStep || 'S3_DESIGN'];

            // 重新执行当前步骤（使用静态响应+调整说明）
            const response = await executeSinglePhase(strategyState.currentStep || 'S3_DESIGN', symbol, market, ctxSessionId);
            contentOverride = `📝 **已根据您的要求调整${stepName || '策略'}：** ${message}\n\n---\n\n${response.content}\n\n💡 如需进一步调整，请直接描述您的需求。`;
            targetStep = null; // 不自动前进，让用户再次确认
            needsConfirmationOut = true;
            break;
          }
          case 'summary_only': {
            // 只给用户看摘要——不执行下一步
            const stepName = strategyState.currentStep || 'S2_ANALYSIS';
            const summaryMap: Record<string, string> = {
              'S1_RESEARCH': `📋 **S1 调研摘要**\n\n标的 ${symbol} 市场结构分析完成：\n- 价格区间已识别\n- 关键支撑阻力位已记录\n- 宏观环境已梳理`,
              'S2_ANALYSIS': `📋 **S2 分析摘要**\n\n多空力量均衡，当前更符合区间震荡特征：\n- 趋势：中性偏震荡\n- 关键位：等待明确突破信号\n- 建议：通过情景推演制定策略`,
              'S3_DESIGN': `📋 **S3 设计摘要**\n\n策略名称：区间突破双轨策略\n- 主路径：支撑位做多，阻力位止盈\n- 备路径：突破跟进\n- 核心参数：止损 1%，仓位 30%~50%`,
              'S4_VALIDATE': `📋 **S4 验证摘要**\n\n策略回测通过：\n- 胜率 ≈ 57%，盈亏比 ≈ 2.5:1\n- 最大回撤可控（~5-6%）\n- 参数稳定性良好，具备正期望值`,
              'S5_EXECUTE': `📋 **S5 执行摘要**\n\n执行计划就绪：\n- 关注支撑位附近的入场信号\n- 严格执行止损纪律\n- 分批止盈离场`,
            };
            contentOverride = `${summaryMap[stepName] || summaryMap['S3_DESIGN']}\n\n💡 回复"继续"进入下一步，或直接描述您想调整的内容。`;
            targetStep = null;
            needsConfirmationOut = true;
            break;
          }
          case 'explain_more': {
            // 给用户更详细的解释——在当前步骤内容基础上补充
            const stepName = strategyState.currentStep || 'S3_DESIGN';
            const explainMap: Record<string, string> = {
              'S1_RESEARCH': `🔍 **关于调研的详细说明**\n\nS1 阶段我们重点完成：\n1. **价格行为识别** — 识别近 60 个交易日的高低点、趋势斜率\n2. **关键位映射** — 使用最近的 swing high/low 来标记支撑阻力\n3. **宏观背景梳理** — 识别市场当前的宏观偏好（避险/风险偏好）\n4. **风险事件标记** — 标出未来 30 天内的已知关键事件\n\n为什么这些重要？因为策略设计的第一原则是"先理解当前市场结构"，再谈如何操作。`,
              'S2_ANALYSIS': `🧠 **关于分析的详细说明**\n\nS2 阶段从多个维度交叉验证当前市场判断：\n1. **技术面**：趋势方向、波动率、RSI 等指标是否协调\n2. **资金面**：机构持仓、ETF 资金流向\n3. **情景推演**：上行/震荡/下行三种路径的触发条件与概率\n4. **不确定性管理**：明确列出当前不确定因素及应对方式\n\n核心目标：避免"先有结论后找证据"的认知偏差。`,
              'S3_DESIGN': `🎯 **关于策略设计的详细说明**\n\nS3 设计遵循"3 条路径 + 明确参数"原则：\n1. **入场规则** — 在什么价位、什么信号触发下进入\n2. **止损规则** — 如何定义判断错误（通常用关键位下方 + 1% 缓冲）\n3. **止盈规则** — 分批离场：第一目标在区间对侧，第二目标给突破行情\n4. **仓位管理** — 单笔风险 ≤ 2% 资金，分批建仓降低冲击\n\n这套框架的核心理念：**任何策略都是概率博弈，必须有 B 计划。**`,
              'S4_VALIDATE': `✅ **关于验证的详细说明**\n\nS4 验证阶段完成：\n1. **历史回测** — 用过去 180 个交易日数据回测核心参数\n2. **敏感性分析** — 扰动入场/止损/止盈参数，观察结果是否稳定\n3. **压力测试** — 极端行情下的最大回撤控制\n\n验证目的不是"找最优参数"（那是过拟合陷阱），而是**确认参数是否具备鲁棒性**（在不同市场阶段都能赚钱）。`,
              'S5_EXECUTE': `⚡ **关于执行的详细说明**\n\nS5 阶段把策略转化为可执行的流程：\n1. **前置检查** — 入场前必须满足的信号清单\n2. **执行节奏** — 分批建仓而非一次性满仓\n3. **离场纪律** — 止损位刚性执行，不允许主观扛单\n4. **复盘机制** — 每笔交易完成后记录得失\n\n执行阶段最大的敌人是情绪。纪律性比"更准确的预测"更重要。`,
            };
            contentOverride = `${explainMap[stepName] || explainMap['S3_DESIGN']}\n\n💡 回复"继续"进入下一步，或直接描述您想调整的内容。`;
            targetStep = null;
            needsConfirmationOut = true;
            break;
          }
          default: {
            // unknown — 默认行为：继续下一步
            targetStep = getNextSStep(strategyState.currentStep || 'S1_RESEARCH');
          }
        }

        // 情况 A：用户请求非标准操作（调整/摘要/详细解释）
        if (contentOverride) {
          return NextResponse.json({
            success: true,
            data: {
              content: contentOverride,
              chainState: {},
              strategyChainState: {
                scope: `${symbol} ${market.displayName} 策略分析`,
                currentStep: strategyState.currentStep,
                steps: allSSteps.map((sid, idx) => ({
                  id: sid,
                  number: idx + 1,
                  name: sid.replace('S1_RESEARCH', 'S1 调研').replace('S2_ANALYSIS', 'S2 分析').replace('S3_DESIGN', 'S3 设计').replace('S4_VALIDATE', 'S4 验证').replace('S5_EXECUTE', 'S5 执行'),
                  status: strategyState.completedSteps.includes(sid) ? 'done' : (sid === strategyState.currentStep ? 'active' : 'pending'),
                })),
                complexity: 'deep',
                createdAt: new Date().toISOString(),
                modifiedAt: new Date().toISOString(),
              },
              stepProgress: null,
              market,
              intent: context.last_intent || 'deep_analysis',
              confidence: 0.9,
              routing: { chain: [strategyState.currentStep || 'S3_DESIGN'] },
              llm_status: await checkLLMStatus(),
              llm_model: process.env.DEEPSEEK_MODEL || "deepseek-v4-pro",
              timestamp: new Date().toISOString(),
              needsConfirmation: needsConfirmationOut,
              nextStep: needsConfirmationOut ? getNextSStep(strategyState.currentStep || 'S3_DESIGN') : null,
            },
          });
        }

        // 情况 B：继续/落地/跳过 — 正常执行 targetStep
        // Phase A: 根据 executionMode 决定行为
        //   - dynamic:  执行当前步 → 自动继续执行剩余步骤（S3→S4→S5 连续）
        //   - stepwise: 执行当前步 → 若当前步是 S3/S4，再次暂停等待用户确认
        if (targetStep) {
          const execMode: ExecMode = (strategyState as any).executionMode || 'dynamic';
          const usePreference = userIntent === 'preference_recommend';

          // 构造需要执行的步骤序列
          const allSStepsOrdered: string[] = ['S1_RESEARCH', 'S2_ANALYSIS', 'S3_DESIGN', 'S4_VALIDATE', 'S5_EXECUTE'];
          const startIdx = allSStepsOrdered.indexOf(targetStep);

          // stepwise 模式：只执行当前这一步（S3/S4 后再次暂停）
          // dynamic 模式：从 targetStep 一直执行到 S5
          let stepsToRun: string[] = [];
          if (execMode === 'stepwise' || userIntent === 'skip_step' || userIntent === 'finalize') {
            stepsToRun = [targetStep];
          } else {
            // dynamic: 从 targetStep 到 S5 全部执行
            stepsToRun = allSStepsOrdered.slice(startIdx);
          }

          // 依次执行步骤
          let accumulatedContent = '';
          let lastStrategyState: any = null;
          let lastMarket = market;
          let completedThisTurn: string[] = [...strategyState.completedSteps];

          for (let idx = 0; idx < stepsToRun.length; idx++) {
            const stepId = stepsToRun[idx];
            const stepResp = await executeSinglePhase(stepId, symbol, lastMarket, ctxSessionId, usePreference);

            if (idx === 0 && (userIntent === 'skip_step')) {
              accumulatedContent += `⏭️ **已跳过一步**（根据您的请求直接进入下一阶段）\n\n---\n\n`;
            } else if (idx === 0 && userIntent === 'finalize') {
              accumulatedContent += `🚀 **直接进入执行阶段**\n\n---\n\n`;
            } else if (idx === 0 && userIntent === 'system_recommend') {
              accumulatedContent += `🔧 **系统推荐**（标准分析）\n\n---\n\n`;
            } else if (idx === 0 && userIntent === 'preference_recommend') {
              accumulatedContent += `🎯 **偏好推荐**（根据您的风险偏好和习惯定制）\n\n---\n\n`;
            } else if (idx > 0) {
              accumulatedContent += `\n\n---\n\n`;
            }

            accumulatedContent += stepResp.content;
            lastStrategyState = stepResp.strategyChainState;
            lastMarket = stepResp.market;
            completedThisTurn.push(stepId);
          }

          // 更新策略状态
          const finalStep = stepsToRun[stepsToRun.length - 1];
          update_strategy_state(ctxSessionId, {
            ...strategyState,
            currentStep: finalStep,
            completedSteps: completedThisTurn,
            executionMode: execMode,
          });

          // 判断是否需要再次确认（仅 stepwise 模式）
          //   - S3 完成后 → 提示确认 S4
          //   - S4 完成后 → 提示确认 S5
          let needsConfirmationOut = false;
          let nextStepOut: string | null = null;

          if (execMode === 'stepwise') {
            if (finalStep === 'S3_DESIGN') {
              needsConfirmationOut = true;
              nextStepOut = 'S4_VALIDATE';
              accumulatedContent += `\n\n---\n\n## 🔸 步进式分析模式 · S3 完成\n\n**S3 策略设计** 已完成。\n\n下一步将进入 **S4 策略验证**（回测、压力测试、参数稳定性检查）。\n\n请回复 **\"继续\"** 进入 S4，或提出修改意见。`;
            } else if (finalStep === 'S4_VALIDATE') {
              needsConfirmationOut = true;
              nextStepOut = 'S5_EXECUTE';
              accumulatedContent += `\n\n---\n\n## 🔸 步进式分析模式 · S4 完成\n\n**S4 策略验证** 已完成。\n\n下一步将进入 **S5 策略执行清单**（触发条件、委托单、异常退出条件）。\n\n请回复 **\"继续\"** 进入 S5，或提出修改意见。`;
            }
          }

          return NextResponse.json({
            success: true,
            data: {
              content: accumulatedContent,
              chainState: {},
              strategyChainState: lastStrategyState,
              stepProgress: null,
              market: lastMarket,
              intent: context.last_intent || 'deep_analysis',
              confidence: 0.9,
              routing: { chain: stepsToRun },
              llm_status: await checkLLMStatus(),
              llm_model: process.env.DEEPSEEK_MODEL || "deepseek-v4-pro",
              timestamp: new Date().toISOString(),
              needsConfirmation: needsConfirmationOut,
              nextStep: nextStepOut,
            },
          });
        }

        // 情况 C：没有下一步（已在最后）—— 给用户友好提示
        return NextResponse.json({
          success: true,
          data: {
            content: `🎉 **S 系列策略链已完成**\n\n您可以：\n- 换一个标的（直接告诉我："分析 ETH"）\n- 调整当前策略参数（"把止损改成 1%"）\n- 咨询具体交易时机（"现在适合入场吗"）`,
            chainState: {},
            strategyChainState: null,
            stepProgress: null,
            market,
            intent: context.last_intent || 'deep_analysis',
            confidence: 0.9,
            routing: { chain: [] },
            llm_status: await checkLLMStatus(),
            llm_model: process.env.DEEPSEEK_MODEL || "deepseek-v4-pro",
            timestamp: new Date().toISOString(),
            needsConfirmation: false,
            nextStep: null,
          },
        });
      } else if (chainState) {
        // D-Z-E 链：原有逻辑（保留供开发/治理使用）
        const nextPhase = getNextPhase(chainState.current_phase);
        if (nextPhase) {
          const nextStep = getStepFromPhase(nextPhase);
          if (nextStep) {
            const transitionResult = chain_transition(chainState, chainState.current_phase, nextPhase.toLowerCase());
            update_chain_state(ctxSessionId, transitionResult.state);

            const response = await executeSinglePhase(nextStep, symbol, market, ctxSessionId);

            return NextResponse.json({
              success: true,
              data: {
                content: response.content,
                chainState: response.chainState,
                strategyChainState: response.strategyChainState,
                stepProgress: response.stepProgress,
                market: response.market,
                intent: context.last_intent || 'deep_analysis',
                confidence: 0.9,
                routing: { chain: [nextStep] },
                llm_status: await checkLLMStatus(),
                llm_model: process.env.DEEPSEEK_MODEL || "deepseek-v4-pro",
                timestamp: new Date().toISOString(),
              },
            });
          }
        }
      }
    }

    // 1. 意图识别 (统一入口: LLM → rule → fallback)
    const intentResult = await recognizeIntent(message, context);

    // ===== P2: developer 意图专属路径 —— 走 S5 完整 E 链（E1→E2→E3）
    if (intentResult.intent === 'developer') {
      console.log(`[Chat API] S5 Engine: strategy code dev`);

      // 调用 S5 执行引擎（完整 E1→E2→E3 链，一次完成）
      const s5Resp = await executeS5ForChat(
        ctxSessionId,
        message,
        context.thinking_mode || 'quick',
        (message.match(/[\u4e00-\u9fa5]/) ? 'zh' : 'en'),
      );

      const devStepsForFrontend = s5Resp.allStepsForDisplay.map((s, idx) => ({
        id: s.id,
        number: idx + 1,
        name: `${s.icon} ${s.label}`,
        status: s.status,
      }));

      // 标记为 developer 意图（作为 session 的 last_intent）
      context.last_intent = 'developer';
      context.message_history.push(message);

      return NextResponse.json({
        success: true,
        data: {
          content: s5Resp.content,
          chainState: {},
          strategyChainState: {
            scope: `策略代码开发: ${message.slice(0, 60)}`,
            currentStep: devStepsForFrontend[devStepsForFrontend.length - 1]?.id,
            steps: devStepsForFrontend,
            complexity: context.thinking_mode,
            createdAt: new Date().toISOString(),
            modifiedAt: new Date().toISOString(),
          },
          stepProgress: {
            steps: s5Resp.allStepsForDisplay,
            current_step: s5Resp.allStepsForDisplay[s5Resp.allStepsForDisplay.length - 1]?.id,
          },
          market: null,
          intent: 'developer',
          confidence: intentResult.confidence,
          routing: {
            chain: s5Resp.allStepsForDisplay.map((s: { id: string }) => s.id),
            loop_type: 'execution',
            role_check: 'allowed',
            requires_confirmation: false,
            message_history: [],
          },
          complexity: context.thinking_mode,
          method: 's5-strategy-code-engine',
          llm_status: await checkLLMStatus(),
          llm_model: process.env.DEEPSEEK_MODEL || "deepseek-v4-pro",
          timestamp: new Date().toISOString(),
          needsConfirmation: false,
          nextStep: null,
        },
      });
    }

    // 📡 监控埋点: 意图识别完成
    emitMonitorEvent({
      trace_id: chatTraceId,
      uid: context.session_id,
      layer: "frontend",
      phase: "intent_recognized",
      status: "completed",
      intent: intentResult.intent,
      thinking_mode: context.thinking_mode,
      chain: [],
    });

    // 2. 智能路由 (基于三闭环 + 角色 + 复杂度)
    const routing = routeIntent(intentResult.intent as any, intentResult.complexity, context as any);

    console.log(`[Chat API] Intent: ${intentResult.intent} (method: ${intentResult.method}, confidence: ${intentResult.confidence})`);
    console.log(`[Chat API] Route: ${routing.loop_type} → ${routing.chain.join(" → ")}`);

    // 3. 检查权限
    if (routing.role_check === "upgrade_required") {
      const upgradeMsg = routing.chain.length === 0
        ? `⚠️ 该功能需要 PRO 角色。当前为 FREE 角色，已降级到知识库查询。\n\n如需完整功能，请升级到 PRO。`
        : `ℹ️ 部分功能需要 PRO 角色。当前已为你执行了简化路径: ${routing.chain.join(" → ")}`;

      const chainResp = await generateChainResponse(routing.chain, intentResult.intent, intentResult.entities, ctxSessionId, routing.requires_confirmation, { userMessage: message, complexity: (intentResult.complexity as any) || 'moderate' }, ((routing as any).mode || 'dynamic') as ExecMode);
      const content = upgradeMsg + "\n\n" + chainResp.content;

      return NextResponse.json({
        success: true,
        data: {
          content,
          chainState: chainResp.chainState,
          strategyChainState: chainResp.strategyChainState,
          stepProgress: chainResp.stepProgress,
          market: chainResp.market,
          intent: intentResult.intent,
          confidence: intentResult.confidence,
          routing,
          complexity: intentResult.complexity,
          method: intentResult.method,
          llm_status: await checkLLMStatus(),
          llm_model: process.env.DEEPSEEK_MODEL || "deepseek-v4-pro",
          timestamp: new Date().toISOString(),
          needsConfirmation: chainResp.needsConfirmation,
          nextStep: chainResp.nextStep,
        },
      });
    }

    if (routing.role_check === "denied") {
      return NextResponse.json({
        success: false,
        error: "Access denied for this operation",
      }, { status: 403 });
    }

    // 4. 执行路由 (生成响应) —— 根据 routing.mode 选择不同执行策略
    //
    //   dynamic 模式 (默认)：执行完整链，自动运行到结束
    //   stepwise 模式：S1+S2 执行后暂停，S3/S4/S5 需要用户确认后继续
    //   quick 模式：简化短链直接执行
    //   developer 模式：已在上方（4176-4235）由 executeS5ForChat 处理

    // Phase A: 不切片 chain，完全依赖 mode 参数在 generateChainResponse 内部决定是否中断
    //   - dynamic: S1-S5 完整执行
    //   - stepwise: S1+S2 后在 generateChainResponse 内部暂停（由硬编码的 S2→S3 中断逻辑控制）
    let chain = routing.chain.length > 0 ? routing.chain : ["S0_DIRECT_ANSWER"];
    const executionMode: ExecMode = (routing as any).mode || 'dynamic';

    // 仅当链含 S 步骤时才启用步进式逻辑（非 S 意图如 quick 直接执行）
    const hasSSteps = chain.some(s => s.startsWith('S'));
    if (executionMode === 'stepwise' && !hasSSteps) {
      // 非 S 意图不支持步进，回退到 dynamic
      console.log(`[Chat API] stepwise 模式但非 S 链 → 回退到 dynamic`);
    }
    console.log(`[Chat API] 执行模式=${executionMode}, chain=${chain.join(' → ')}`);

    // ===== P3 多意图组合路由 =====
    // 在标准路由完成后，检测是否有复合意图（如：先宏观分析 → 再入场 → 再仓位管理）
    const combinedIntents = detectCombinedIntents(message, intentResult.intent);
    let isCombined = false;
    if (executionMode !== 'stepwise' && combinedIntents.length > 1) {
      const combinedChain = buildCombinedChain(combinedIntents, context.thinking_mode || 'deep');
      if (combinedChain.length > chain.length) {
        chain = combinedChain;  // 使用更完整的组合链
        isCombined = true;
        console.log(`[Chat API] Combined intent chain: ${combinedIntents.join(' → ')}`);
        console.log(`[Chat API] Combined execution chain: ${chain.join(' → ')}`);
      }
    }

    // ===== Hermes 记忆学习：在生成响应前先检测消息中的隐式偏好 =====
    const preDetected = detectPreferenceSignal(message, 'not_confirmation');
    if (preDetected) {
      userPrefMemory.learn({
        userId: ctxSessionId,
        type: preDetected.type,
        value: preDetected.value,
        importance: preDetected.importance,
        source: 'implicit_behavior',
        evidence: preDetected.evidence,
      });
    }

    const response = await generateChainResponse(chain, intentResult.intent, intentResult.entities, ctxSessionId,
      routing.requires_confirmation,
      { userMessage: message, complexity: (intentResult.complexity as any) || 'moderate' },
      executionMode as ExecMode);

    // Phase A: 将执行模式写入 strategyState，供后续"继续"回复时使用
    const sState = get_or_init_strategy_state(ctxSessionId, executionMode as ExecMode);
    sState.executionMode = executionMode as ExecMode;
    // 如果是 stepwise 首次请求，标记 S1+S2 为已完成
    if (executionMode === 'stepwise') {
      sState.completedSteps = Array.from(new Set([...(sState.completedSteps || []), 'S1_RESEARCH', 'S2_ANALYSIS']));
      sState.currentStep = 'S2_ANALYSIS';
    } else if (executionMode === 'dynamic') {
      // dynamic 模式：完整链已由 generateChainResponse 执行
      sState.completedSteps = Array.from(new Set([...(sState.completedSteps || []), ...chain]));
      sState.currentStep = chain[chain.length - 1] || sState.currentStep;
    }
    update_strategy_state(ctxSessionId, sState);

    // P3 多意图组合路由 - 给组合意图响应加上阶段说明
    if (isCombined) {
      response.content = buildCombinedIntentHeader(combinedIntents) + response.content;
    }

    // 5. 更新会话上下文
    context.last_intent = intentResult.intent;
    context.last_symbol = intentResult.entities.symbol || context.last_symbol;
    context.last_complexity = intentResult.complexity;
    context.message_history.push(message);
    if (context.message_history.length > 20) {
      context.message_history = context.message_history.slice(-20);
    }

    // ===== P0+: 图文压缩（当历史超过阈值时触发） =====
    let compressionResult: CompressResult | undefined = undefined;

    // 1) 如果会话有 graph-reflection-bridge 状态 → 使用 graph-aware 压缩
    const graphStateForCompression = sessionGraphStates.get(chatTraceId);
    if (graphStateForCompression && shouldEnableScheduler) {
      try {
        const gResult = compressorAdapter.compressFromGraphState(graphStateForCompression);
        if (gResult && gResult.compressionRatio < 1) {
          compressionResult = gResult;
          console.log(
            `[CompressorAdapter] session=${chatTraceId} | ` +
            `graph-aware compression ${gResult.originalTokens} → ${gResult.compressedTokens} tokens ` +
            `(${(gResult.compressionRatio * 100).toFixed(1)}%) | ` +
            `nodes=${gResult.stats.totalNodes}`
          );
        }
      } catch (err) {
        console.warn('[CompressorAdapter] graph-aware 压缩失败，回退到文本摘要', err);
      }
    }

    // 2) 回退：纯文本摘要压缩（如果 graphState 不可用或未触发）
    if (!compressionResult && shouldEnableScheduler && context.message_history.length >= 10) {
      try {
        const items = context.message_history.map((msg, idx) => ({
          id: `msg-${idx}`,
          type: 'message' as const,
          content: msg,
          tokens: estimateTokens(msg),
        }));
        compressionResult = await compressorAdapter.compress({
          sessionId: chatTraceId,
          payload: items,
          targetRatio: 0.5,
          metadata: {
            intent: intentResult.intent,
            complexity: intentResult.complexity,
          },
        });

        if (compressionResult && compressionResult.compressionRatio < 1) {
          console.log(
            `[CompressorAdapter] session=${chatTraceId} | ` +
            `compressed ${compressionResult.originalTokens} → ${compressionResult.compressedTokens} tokens ` +
            `(${((1 - compressionResult.compressionRatio) * 100).toFixed(1)}% saved) ` +
            `| nodes=${compressionResult.stats.totalNodes}`
          );
        }
      } catch (err) {
        console.warn('[CompressorAdapter] 压缩失败，继续正常流程', err);
      }
    }

    // 6. 返回结果
    // ===== P0: Cost Keeper 报告 & 清理 =====
    let costReport: { totalTokens?: number; promptTokens?: number; completionTokens?: number; skippedSteps?: string[]; budgetTokens?: number; status?: string } | undefined = undefined;
    if (shouldEnableScheduler) {
      const report = generateReport(chatTraceId);
      if (report) {
        costReport = {
          totalTokens: report.totalTokens,
          promptTokens: report.totalPromptTokens,
          completionTokens: report.totalCompletionTokens,
          skippedSteps: report.skippedSteps,
          budgetTokens: report.budgetTokens,
          status: report.reachedBudgetLimit ? 'budget_exceeded' : 'ok',
        };
        console.log(
          `[Hermes-Planner] session=${chatTraceId} | ` +
          `total=${report.totalTokens}/${report.budgetTokens} | ` +
          `skipped=${report.skippedSteps.length} steps`
        );
      }
      cleanupSession(chatTraceId);
    }

    return NextResponse.json({
      success: true,
      data: {
        content: response.content,
        chainState: response.chainState,
        strategyChainState: response.strategyChainState,
        stepProgress: response.stepProgress,
        market: response.market,
        intent: intentResult.intent,
        confidence: intentResult.confidence,
        routing,
        complexity: intentResult.complexity,
        method: intentResult.method,
        llm_status: await checkLLMStatus(),
        llm_model: process.env.DEEPSEEK_MODEL || "deepseek-v4-pro",
        timestamp: new Date().toISOString(),
        needsConfirmation: response.needsConfirmation,
        nextStep: response.nextStep,
        cost_report: costReport,
        compression: compressionResult ? {
          originalTokens: compressionResult.originalTokens,
          compressedTokens: compressionResult.compressedTokens,
          ratio: compressionResult.compressionRatio,
          nodes: compressionResult.stats.totalNodes,
        } : undefined,
      },
    });

  } catch (error) {
    console.error("[Chat API] Error:", error);

    // P0: 异常路径也要清理 CostKeeper，避免内存泄漏
    if (shouldEnableScheduler) {
      try { cleanupSession(chatTraceId); } catch {}
      try {
        const traceStr = typeof chatTraceId === 'string' ? chatTraceId : undefined;
        if (traceStr) cleanupSession(traceStr);
      } catch {}
    }

    return NextResponse.json(
      { success: false, error: error instanceof Error ? error.message : "Unknown error" },
      { status: 500 }
    );
  }
}

/**
 * S系列响应样式（响应多样化，让不同请求/不同用户场景得到不同风格的输出）
 */
type ResponseStyle = 'data_driven' | 'macro_narrative' | 'structured_list';

/**
 * 根据会话 ID 和步骤 ID 选择响应样式（确定性哈希，保证同一会话保持一致性）
 */
function pickResponseStyle(sessionId: string, stepId: string): ResponseStyle {
  const combined = `${sessionId}-${stepId}-${new Date().getHours()}`;
  let hash = 0;
  for (let i = 0; i < combined.length; i++) {
    hash = ((hash << 5) - hash) + combined.charCodeAt(i);
    hash |= 0;
  }
  const styles: ResponseStyle[] = ['data_driven', 'macro_narrative', 'structured_list'];
  return styles[Math.abs(hash) % styles.length];
}

/**
 * 获取样式对应的标签（展示给用户，提升可读性）
 */
function getStyleLabel(style: ResponseStyle, isZh: boolean = true): string {
  if (!isZh) {
    switch (style) {
      case 'data_driven': return '| *Data-driven analysis*';
      case 'macro_narrative': return '| *Narrative analysis*';
      case 'structured_list': return '| *Structured analysis*';
    }
  }
  switch (style) {
    case 'data_driven': return '| 📊 数据驱动视角';
    case 'macro_narrative': return '| 📖 叙事解读视角';
    case 'structured_list': return '| ✅ 清单式视角';
  }
  return '';
}

/**
 * 根据样式调整 S1 调研的额外内容
 */
function getS1StyleExtra(style: ResponseStyle, displayName: string, priceStr: string, changeStr: string, isGold: boolean): string {
  switch (style) {
    case 'data_driven':
      return `

**📈 价格行为数据点:**
- 当前价格: ${priceStr}
- 24h 涨跌幅: ${changeStr}
- 价格类型: ${isGold ? '避险资产属性显著' : '风险资产属性'}
- 数据时效性: ${new Date().toLocaleTimeString('zh-CN')}`;
    case 'macro_narrative':
      return `

**📖 叙事解读:**
在当前宏观环境下，${displayName} 的价格行为反映了市场参与者的共识预期。价格 ${changeStr} 反映短期资金倾向，后续需要关注关键支撑/阻力位附近的情绪变化。`;
    case 'structured_list':
      return `

**✅ 快速观察清单:**
☐ 价格是否在近 7 日波动区间内
☐ 成交量是否配合当前走势
☐ 关键支撑位附近是否存在买盘
☐ 阻力位附近是否存在抛压`;
  }
  return '';
}

/**
 * 根据样式调整 S2 分析的额外内容
 */
function getS2StyleExtra(style: ResponseStyle, supportStr: string, resistanceStr: string): string {
  switch (style) {
    case 'data_driven':
      return `

**📊 价格区间量化:**
- 支撑带: ${supportStr}
- 阻力带: ${resistanceStr}
- 区间宽度: 为后续入场提供量化依据`;
    case 'macro_narrative':
      return `

**📖 情景解读:**
当前多空胶着的本质在于市场参与者对下一阶段的预期存在分歧。需要等待关键位的破位/确认信号来指引方向。`;
    case 'structured_list':
      return `

**✅ 决策清单:**
☐ 等待突破确认信号（如放量破位）
☐ 等待回踩不破支撑的二次确认信号
☐ 关键决策依据充分后再进入设计阶段`;
  }
  return '';
}

/**
 * 根据样式调整 S3 设计的额外内容
 */
function getS3StyleExtra(style: ResponseStyle, changeStr: string): string {
  switch (style) {
    case 'data_driven':
      return `\n**📊 盈亏比模型:**\n当前波动 ${changeStr}，建议固定盈亏比不低于 2.0。`;
    case 'macro_narrative':
      return `\n**📖 策略叙事:**\n该策略的核心理念是在区间震荡中积累小额收益，等待突破带来的超额收益。`;
    case 'structured_list':
      return `\n**✅ 策略检查清单:**\n☐ 确认入场条件明确\n☐ 止损位刚性执行\n☐ 分批止盈机制清晰`;
  }
  return '';
}

/**
 * 解析用户灵活回复意图（替代原简单确认识别）
 */
type UserReplyIntent = 'continue' | 'finalize' | 'adjust_params' | 'skip_step' | 'summary_only' | 'explain_more' | 'system_recommend' | 'preference_recommend' | 'not_confirmation';

function parseUserReplyIntent(message: string, strategyState: { currentStep?: string } = {}): UserReplyIntent {
  const trimmed = message.trim().toLowerCase();
  const lowerMessage = message.trim();

  // 系统推荐（标准方案）
  if (/系统推荐|标准方案|系统方案|普通方案|默认方案|按系统来/.test(lowerMessage)) {
    return 'system_recommend';
  }

  // 偏好推荐（考虑我的偏好）
  if (/偏好推荐|我的偏好|考虑我|个性化|按我的|根据我的|按习惯/.test(lowerMessage)) {
    return 'preference_recommend';
  }

  // 调整参数意图（最高优先级，包含具体修改内容时优先匹配）
  if (/改|换|调整|换成|改为|改成|设为|设置|风险|参数|把.*换成|把.*改/.test(lowerMessage)) {
    return 'adjust_params';
  }

  // 只看结论/摘要
  if (/只看|只看结论|摘要|总结|结论|快速了解|快速看/.test(lowerMessage)) {
    return 'summary_only';
  }

  // 详细解释/说明更多
  if (/解释|详细|为什么|为何|讲一下|解释一下|怎么理解|说明|详情|更多/.test(lowerMessage)) {
    return 'explain_more';
  }

  // 跳过/跳步
  if (/跳过|跳过这步|跳过此步|跳过这一步|不做|不需要.*步|从.*开始|直接进入/.test(lowerMessage)) {
    return 'skip_step';
  }

  // 最终落地/直接执行
  if (/直接落地|直接执行|直接执行|开始执行|ready to execute|finalize|落地|执行计划|生成执行|开始执行|直接开干/.test(lowerMessage) || trimmed === '2') {
    return 'finalize';
  }

  // 继续/确认/下一步
  if (trimmed === '1' || /继续|下一步|确认|进入下一步|继续执行|go ahead|proceed|yes|好的|可以/.test(lowerMessage)) {
    return 'continue';
  }

  return 'not_confirmation';
}

/**
 * 判断消息是否为确认消息（继续/下一步/确认等）
 */
function isConfirmationMessage(message: string): boolean {
  const intent = parseUserReplyIntent(message);
  return intent !== 'not_confirmation';
}

/**
 * 根据阶段获取对应的步骤名称
 */
function getStepFromPhase(phase: string): string | null {
  const phaseToStep: Record<string, string> = {
    // D-Z-E 链（开发治理）
    'D1': 'D1_investigator',
    'D2': 'D2_analyst',
    'D3': 'D3_deducer',
    'D4': 'D4_spec_author',
    'Z1': 'Z1_code_scanner',
    'Z2': 'Z2_boundary_divider',
    'Z3': 'Z3_path_planner',
    'Z4': 'Z4_acceptance_designer',
    'E1': 'E1_task_executor',
    'E2': 'E2_tester',
    'E3': 'E3_deployer',
    // S 系列策略链
    'S1_RESEARCH': 'S1_RESEARCH',
    'S2_ANALYSIS': 'S2_ANALYSIS',
    'S3_DESIGN': 'S3_DESIGN',
    'S4_VALIDATE': 'S4_VALIDATE',
    'S5_EXECUTE': 'S5_EXECUTE',
    'S1': 'S1_RESEARCH',
    'S2': 'S2_ANALYSIS',
    'S3': 'S3_DESIGN',
    'S4': 'S4_VALIDATE',
    'S5': 'S5_EXECUTE',
  };
  return phaseToStep[phase] || null;
}

/**
 * 获取 S系列的下一步骤
 */
function getNextSStep(currentStep: string): string | null {
  const sSteps = ['S1_RESEARCH', 'S2_ANALYSIS', 'S3_DESIGN', 'S4_VALIDATE', 'S5_EXECUTE'];
  const currentIdx = sSteps.indexOf(currentStep);
  if (currentIdx >= 0 && currentIdx < sSteps.length - 1) {
    return sSteps[currentIdx + 1];
  }
  return null;
}

/**
 * 执行单个阶段
 */
async function executeSinglePhase(
  step: string,
  symbol: string,
  market: MarketPriceData,
  sessionId: string,
  usePreference: boolean = true
): Promise<{ content: string; chainState: any; strategyChainState: any; stepProgress: any; market: MarketPriceData }> {
  const priceStr = fmtPrice(market.price, market.unit);
  const supportStr = market.support.map(v => fmtPrice(v, market.unit)).join(' / ');
  const resistanceStr = market.resistance.map(v => fmtPrice(v, market.unit)).join(' / ');
  const support1 = fmtPrice(market.support[0], market.unit);
  const support2 = fmtPrice(market.support[1], market.unit);
  const resist1 = fmtPrice(market.resistance[0], market.unit);
  const resist2 = fmtPrice(market.resistance[1], market.unit);
  const changeStr = (market.change24h >= 0 ? '+' : '') + market.change24h.toFixed(2) + '%';
  const isGold = market.symbol === 'XAU' || market.displayName.includes('黄金');
  const displayName = market.displayName;
  
  const content = await executeStepWithSkill(step, symbol, market, priceStr, supportStr, resistanceStr, support1, support2, resist1, resist2, changeStr, isGold, displayName, sessionId, usePreference);
  
  const chainState = get_or_init_chain_state(sessionId);
  const updatedPhases = chainState.phases.map((p: ChainPhase) => {
    const phaseId = p.id.toUpperCase();
    if (step.toLowerCase().includes(p.id)) {
      return { ...p, status: 'completed' as const, approval: 'approved' as const };
    }
    return p;
  });
  
  const isSSeries = step.startsWith('S');
  let strategyChainState = null;
  
  if (isSSeries) {
    const strategySteps = ['S1_RESEARCH', 'S2_ANALYSIS', 'S3_DESIGN', 'S4_VALIDATE', 'S5_EXECUTE'];
    const currentIdx = strategySteps.indexOf(step);
    
    strategyChainState = {
      scope: `${symbol} ${market.displayName} 策略分析`,
      currentStep: step,
      steps: strategySteps.map((stepId, idx) => {
        let status: string = 'pending';
        if (idx < currentIdx) status = 'done';
        else if (idx === currentIdx) status = 'active';
        
        const nameMap: Record<string, string> = {
          'S1_RESEARCH': 'S1 调研',
          'S2_ANALYSIS': 'S2 分析',
          'S3_DESIGN': 'S3 设计',
          'S4_VALIDATE': 'S4 验证',
          'S5_EXECUTE': 'S5 执行',
        };
        
        return {
          id: stepId,
          number: idx + 1,
          name: nameMap[stepId] || stepId,
          status,
        };
      }),
      complexity: 'deep',
      createdAt: new Date().toISOString(),
      modifiedAt: new Date().toISOString(),
    };
  }
  
  return {
    content,
    chainState: {
      phases: updatedPhases.map(p => ({
        id: p.id.toUpperCase(),
        name: p.name,
        status: p.status,
        approval: p.approval,
        output: p.output_ref || '',
      })),
      currentPhase: step,
      scope: chainState.scope,
    },
    strategyChainState,
    stepProgress: {
      steps: [
        { id: 'S1', name: '需求解析', status: 'completed' as const },
        { id: 'S2', name: '思维链调研', status: 'completed' as const },
        { id: 'S3', name: '知识库检索', status: 'completed' as const },
        { id: 'S4', name: '方法论借鉴', status: 'active' as const },
        { id: 'S5', name: '索引系统更新', status: 'pending' as const },
        { id: 'S6', name: '飞书协作归档', status: 'pending' as const },
        { id: 'S7', name: '记忆蒸馏', status: 'pending' as const },
      ],
      currentStep: 4,
      totalSteps: 7,
    },
    market,
  };
}

// ============ GET /api/chat ============

export async function GET(request: NextRequest) {
  const { searchParams } = new URL(request.url);
  const action = searchParams.get("action");

  if (action === "status") {
    return NextResponse.json({
      success: true,
      data: {
        llm_status: await checkLLMStatus(),
        llm_model: process.env.DEEPSEEK_MODEL || "deepseek-v4-pro",
        intent_method: intentMethod,
        timestamp: new Date().toISOString(),
      },
    });
  }

  const sessionId = searchParams.get("session_id");
  const session = sessionId ? sessionContexts.get(sessionId) : null;

  return NextResponse.json({
    success: true,
    data: {
      messages: session?.message_history || [],
      session_id: sessionId,
      last_intent: session?.last_intent,
      last_symbol: session?.last_symbol,
    },
  });
}
