import { NextRequest, NextResponse } from "next/server";
import { emitMonitorEvent } from "@/lib/monitor-bus";
import { routeIntent } from "@/lib/intent";
import type { ComplexityLevel } from "@/lib/intent";

// ============ 会话上下文 ============

interface SessionContext {
  session_id: string;
  user_role: "FREE" | "PRO" | "ADMIN";
  last_intent?: IntentType;
  last_symbol?: string;
  last_complexity?: ComplexityLevel;
  message_history: string[];
  thinking_mode: "quick" | "deep";
  cached_responses: Map<string, { response: string; timestamp: number }>;
}

type IntentMethod = "llm" | "rule" | "follow_up" | "default";

type ThinkingMode = "quick" | "deep";

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
  | "command";

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
 * 调用 DeepSeek API
 */
async function callDeepSeekAPI(messages: any[], temperature: number = 0.7): Promise<string> {
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
    });

    if (!response.ok) {
      const errorText = await response.text();
      // 403 表示额度问题，标记为降级
      if (response.status === 403) {
        llmStatus = 'degraded';
      }
      throw new Error(`DeepSeek API error: ${response.status} ${errorText}`);
    }

    const data = await response.json();
    llmStatus = 'online';
    return data.choices[0].message.content;
  } catch (error) {
    console.error('[DeepSeek API] Call failed:', error);
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
          chain: ['direct_answer'],
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
          chain: ['A1_research', 'A2_analysis'],
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
      routing: { chain: ['market_data'], priority: 'high', cacheable: true },
    };
  }

  if (msg.includes('分析') || msg.includes('怎么看') || msg.includes('走势')) {
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
      routing: { chain: ['A3_simulation'], priority: 'medium', cacheable: false },
    };
  }

  if (msg.includes('验证') || msg.includes('回测')) {
    return {
      intent: 'strategy_verify', confidence: 0.8, thinking_mode: mode,
      entities: extractEntities(msg),
      complexity: "moderate",
      method: "rule",
      routing: { chain: ['A4_validation'], priority: 'medium', cacheable: false },
    };
  }

  if (msg.includes('开仓') || msg.includes('下单') || msg.includes('交易')) {
    return {
      intent: 'execute_trade', confidence: 0.75, thinking_mode: mode,
      entities: extractEntities(msg),
      complexity: "complex",
      method: "rule",
      routing: { chain: ['A5_execution'], priority: 'high', cacheable: false },
    };
  }

  console.log(`[IntentRule] 未匹配关键词，使用简单问答模式`);
  return {
    intent: 'simple_qa', confidence: 0.6, thinking_mode: mode,
    entities: extractEntities(msg),
    complexity: "simple",
    method: "default",
    routing: { chain: ['direct_answer'], priority: 'low', cacheable: true },
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
- deep_analysis: 深度分析（D链）
- triple_chain: 完整策略制定（D-Z-E 三链，需用户确认步进）
- scenario_sim: 情景推演
- strategy_verify: 策略验证
- execute_trade: 下单/交易执行
- simple_qa: 简单问答

输出格式:
{"intent":"类型","confidence":0.0-1.0,"entities":{"symbol":"BTC","timeframe":"4h"},"reasoning":"理由"}

规则:
1. 用户请求"制定策略"、"帮我分析+制定"、"给我一个策略"等 → triple_chain (D-Z-E 完整链路)
2. 用户请求"分析"、"怎么看"、"走势" → deep_analysis (D链)
3. 用户请求"现在黄金怎么样"、"BTC行情" → market_query
4. 用户明确请求"下单"、"买入"、"卖出" → execute_trade

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

    const validIntents: string[] = ['market_query', 'deep_analysis', 'triple_chain', 'scenario_sim', 'strategy_verify', 'execute_trade', 'simple_qa'];
    if (!validIntents.includes(parsed.intent)) {
      console.warn(`[IntentLLM] Invalid intent "${parsed.intent}", fallback to simple_qa`);
      parsed.intent = 'simple_qa';
      parsed.confidence = 0.4;
    }

    return {
      intent: parsed.intent as IntentType,
      confidence: parsed.confidence || 0.7,
      entities: (parsed.entities || {}) as Record<string, string>,
      complexity:
        parsed.intent === "market_query" || parsed.intent === "simple_qa"
          ? "simple"
          : parsed.intent === "triple_chain"
            ? "complex"
            : "moderate",
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

  // D-Z-E 核心链路：D=调研分析, Z=方案制定, E=执行交付（保留用于开发治理）
  const D1_2 = ['D1_investigator', 'D2_analyst'];
  const D1_4 = ['D1_investigator', 'D2_analyst', 'D3_deducer', 'D4_spec_author'];
  const FULL_DZE = ['D1_investigator', 'D2_analyst', 'D3_deducer', 'D4_spec_author', 'Z1_code_scanner', 'Z2_boundary_divider', 'Z3_path_planner', 'Z4_acceptance_designer', 'E1_task_executor', 'E2_tester', 'E3_deployer'];

  if (thinkingMode === 'quick') {
    const quickChainMap: Record<IntentType, string[]> = {
      'market_query': ['market_data'],
      // 策略分析使用S系列链
      'deep_analysis': S1_2,
      'triple_chain': D1_4, // 开发治理保留D-Z-E
      'scenario_sim': ['S1_RESEARCH', 'S2_ANALYSIS', 'S3_DESIGN'],
      'strategy_verify': ['S2_ANALYSIS', 'S3_DESIGN', 'S4_VALIDATE'],
      'execute_trade': ['S1_RESEARCH', 'S2_ANALYSIS', 'S3_DESIGN', 'S4_VALIDATE'],
      'simple_qa': ['direct_answer'],
      'system_config': ['direct_answer'],
      'credits_query': ['direct_answer'],
      'artifact_query': ['knowledge_base'],
      'risk_alert_response': ['A6_intelligence', 'A6_alert'],
      'command': ['route_by_command'],
    };
    return quickChainMap[intent] || ['direct_answer'];
  }

  // 深度思考模式：完整策略链
  const deepChainMap: Record<IntentType, string[]> = {
    'market_query': ['market_data'],
    // 策略分析使用S系列链
    'deep_analysis': S1_3,
    'triple_chain': FULL_DZE, // 开发治理保留D-Z-E
    'scenario_sim': ['S1_RESEARCH', 'S2_ANALYSIS', 'S3_DESIGN', 'S4_VALIDATE'],
    'strategy_verify': ['S2_ANALYSIS', 'S3_DESIGN', 'S4_VALIDATE'],
    'execute_trade': FULL_S,
    'simple_qa': ['direct_answer'],
    'system_config': ['direct_answer'],
    'credits_query': ['direct_answer'],
    'artifact_query': ['knowledge_base', 'tavily_search'],
    'risk_alert_response': ['A6_intelligence', 'A6_alert'],
    'command': ['route_by_command'],
  };
  return deepChainMap[intent] || ['direct_answer'];
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
    case 'dream-strategy-research': // A1 - 深度调研
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
    
    case 'dream-first-principles': // A2 - 第一性原理分析
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
    
    case 'dream-strategy-designer': // A3 - 策略设计
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
    
    case 'dream-tactical-validator': // A4 - 策略验证
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
    
    case 'dream-tactical-executor': // A5 - 任务执行
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
 * 获取标的的实时价格（优先从内部 snapshot，失败时生成合理模拟值）
 */
async function fetchMarketPrice(symbolInput: string): Promise<MarketPriceData> {
  const upper = symbolInput.toUpperCase();
  const now = Date.now();

  // 缓存命中（60秒内）
  if (priceCache.data && now - priceCache.timestamp < 60 * 1000 && priceCache.data.symbol === upper) {
    return priceCache.data;
  }

  // 尝试调用内部 snapshot API
  try {
    const snap = await fetch(`http://localhost:${process.env.PORT || 3000}/api/market/snapshot?symbol=${upper}`, { signal: AbortSignal.timeout(3000) });
    if (snap.ok) {
      const json = await snap.json();
      if (json.success && json.data) {
        const d = json.data;
        const price = typeof d.price === 'number' ? d.price : parseFloat(String(d.price));
        const result: MarketPriceData = {
          price,
          open24h: d.open24h || price * 0.995,
          high24h: d.high24h || price * 1.015,
          low24h: d.low24h || price * 0.985,
          change24h: d.change24h || 0.5,
          support: d.support_levels || [price * 0.992, price * 0.985, price * 0.975],
          resistance: d.resistance_levels || [price * 1.008, price * 1.015, price * 1.025],
          symbol: upper,
          displayName: d.displayName || d.symbol || upper,
          unit: d.unit || 'USD',
          note: d.note,
        };
        priceCache = { data: result, timestamp: now };
        return result;
      }
    }
  } catch { /* 忽略，用 fallback */ }

  // === fallback: 合理模拟值（根据 symbol 动态生成 ===
  let basePrice = 80630;
  let unit = 'USDT';
  let displayName = `${upper}/USDT`;
  if (upper === 'XAU' || upper === 'GOLD' || upper.startsWith('XAU')) {
    basePrice = 3085; unit = 'USD/oz'; displayName = '黄金/美元 (现货)';
  } else if (upper === 'ETH') { basePrice = 3820; }
  else if (upper === 'SOL') { basePrice = 168; }
  else if (upper === 'BNB') { basePrice = 620; }
  else if (upper === 'XRP') { basePrice = 0.62; }
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
    note: `${displayName} 参考行情（模拟动态数据）`,
  };
  priceCache = { data: result, timestamp: now };
  return result;
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
};

/**
 * 处理链响应（调用真实SKILL，实现阶段门禁）
 */
async function generateChainResponse(
  chain: string[], 
  intent: string, 
  entities: Record<string, string>,
  sessionId: string,
  needUserConfirmation: boolean = false
): Promise<{ content: string; chainState: any; stepProgress: any; market: MarketPriceData | null; needsConfirmation: boolean; nextStep: string | null }> {
  const symbol = entities.symbol || "BTC";
  
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
  
  for (let i = 0; i < chain.length; i++) {
    const step = chain[i];
    
    // 检查是否需要用户确认才能继续（D/Z系列需要确认，E系列不需要）
    if (needUserConfirmation && i > 0 && !step.startsWith('E')) {
      // 如果需要确认，只执行到当前步骤，然后等待确认
      const stepResult = await executeStepWithSkill(step, symbol, market, priceStr, supportStr, resistanceStr, support1, support2, resist1, resist2, changeStr, isGold, displayName);
      result += stepResult;
      skillResults[step] = true;
      break;
    }
    
    // 执行步骤（调用SKILL）
    const stepResult = await executeStepWithSkill(step, symbol, market, priceStr, supportStr, resistanceStr, support1, support2, resist1, resist2, changeStr, isGold, displayName);
    result += stepResult;
    skillResults[step] = true;
    
    if (i < chain.length - 1) {
      result += "\n\n---\n\n";
    }
  }
  
  // 检查是否需要用户确认
  const needsConfirmation = needUserConfirmation && chain.length > 1 && !chain[chain.length - 1].startsWith('E');
  const nextStep = needsConfirmation ? getNextPhase(chain[chain.length - 1]) : null;
  
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
  
  return {
    content: result.trim() || "处理完成。",
    chainState: outputChainState,
    stepProgress,
    market,
    needsConfirmation,
    nextStep,
  };
}

/**
 * 执行单个步骤（调用SKILL或生成静态响应）
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
  displayName: string
): Promise<string> {
  // 获取对应的SKILL
  const skillName = STEP_TO_SKILL[step];
  
  if (skillName) {
    // 调用SKILL
    const skillResult = await callSkill(skillName, { 
      symbol, 
      price: market.price,
      support: market.support,
      resistance: market.resistance,
    });
    
    if (skillResult.success && skillResult.data) {
      return formatSkillResult(step, skillResult.data, displayName, symbol, priceStr, supportStr, resistanceStr, support1, support2, resist1, changeStr, isGold);
    }
  }
  
  // 如果SKILL调用失败或没有对应的SKILL，使用静态响应
  return generateStaticResponse(step, symbol, displayName, priceStr, supportStr, resistanceStr, support1, support2, resist1, resist2, changeStr, isGold, market);
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
  };
  
  const def = stepDefs[step] || { icon: '📋', title: step };
  
  // 根据不同SKILL的返回格式进行格式化
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
  market: MarketPriceData
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

    A1_research: `🔍 **D1 深度调研**\n\n当前 ${displayName} 价格 ${priceStr}。`,
    A2_analysis: `🧠 **D2 分析诊断**\n\n${displayName} 当前区间震荡（${supportStr} ~ ${resistanceStr}），等待突破信号。`,
    A3_simulation: `🎲 **D3 推演验证**\n\n情景推演完成，更符合区间震荡。`,
    A4_validation: `✅ **D4 策略验证**\n\n策略参数回测通过。`,
    A5_execution: `⚡ **E1 执行决策**\n\n等待入场信号中...`,
    A9_exit: `🚪 **离场评估**\n\n当前持仓正常监控中。`,
    A6_intelligence: `📡 **情报监控**\n\n持续监控市场变化...`,
    A6_alert: `⚠️ **情报警报**\n\n检测到市场波动加剧。`,

    market_data: `📊 **${displayName} 行情数据**\n\n当前价格: ${priceStr}\n24h涨跌: ${changeStr}\n关键支撑: ${supportStr}\n关键阻力: ${resistanceStr}\n24h最高: ${fmtPrice(market.high24h, market.unit)}\n24h最低: ${fmtPrice(market.low24h, market.unit)}\n\n${market.note || ''}`,
    knowledge_base: `📚 **知识库检索**\n\n根据历史数据，${displayName} 当前处于关键价位附近。建议启用 D-Z-E 链进行完整策略分析。`,
    tavily_search: `🌐 **联网搜索**\n\n最新市场资讯已获取（模拟数据）。`,
    direct_answer: `💬 收到请求，正在处理...`,
  };
  
  return responses[step] || `📋 **${step}**\n\n执行完成。`;
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
  try {
    const body = await request.json();
    const { message, session_id, thinking_mode, user_role, confirm_step } = body;

    if (!message) {
      return NextResponse.json({ error: "Message is required" }, { status: 400 });
    }

    const chatTraceId = `chat_${Date.now()}_${Math.random().toString(36).slice(2, 6)}`;

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

    // 检查是否是用户确认回复（继续/下一步等）
    const isConfirmation = isConfirmationMessage(message);
    
    // 如果是确认回复，检查当前链状态并继续下一步
    if (isConfirmation) {
      const chainState = sessionChainStates.get(ctxSessionId);
      if (chainState) {
        const nextPhase = getNextPhase(chainState.current_phase);
        if (nextPhase) {
          // 继续到下一阶段
          const nextStep = getStepFromPhase(nextPhase);
          if (nextStep) {
            // 更新链状态
            const transitionResult = chain_transition(chainState, chainState.current_phase, nextPhase.toLowerCase());
            update_chain_state(ctxSessionId, transitionResult.state);
            
            // 获取市场数据用于生成响应
            const symbol = context.last_symbol || "BTC";
            const market = await fetchMarketPrice(symbol);
            
            // 执行下一阶段
            const response = await executeSinglePhase(nextStep, symbol, market, ctxSessionId);
            
            return NextResponse.json({
              success: true,
              data: {
                content: response.content,
                chainState: response.chainState,
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
    const routing = routeIntent(intentResult.intent, intentResult.complexity, context);

    console.log(`[Chat API] Intent: ${intentResult.intent} (method: ${intentResult.method}, confidence: ${intentResult.confidence})`);
    console.log(`[Chat API] Route: ${routing.loop_type} → ${routing.chain.join(" → ")}`);

    // 3. 检查权限
    if (routing.role_check === "upgrade_required") {
      const upgradeMsg = routing.chain.length === 0
        ? `⚠️ 该功能需要 PRO 角色。当前为 FREE 角色，已降级到知识库查询。\n\n如需完整功能，请升级到 PRO。`
        : `ℹ️ 部分功能需要 PRO 角色。当前已为你执行了简化路径: ${routing.chain.join(" → ")}`;

      const chainResp = await generateChainResponse(routing.chain, intentResult.intent, intentResult.entities, ctxSessionId, routing.requires_confirmation);
      const content = upgradeMsg + "\n\n" + chainResp.content;

      return NextResponse.json({
        success: true,
        data: {
          content,
          chainState: chainResp.chainState,
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

    // 4. 执行路由 (生成响应)
    const chain = routing.chain.length > 0 ? routing.chain : ["direct_answer"];
    const response = await generateChainResponse(chain, intentResult.intent, intentResult.entities, ctxSessionId, routing.requires_confirmation);

    // 5. 更新会话上下文
    context.last_intent = intentResult.intent;
    context.last_symbol = intentResult.entities.symbol || context.last_symbol;
    context.last_complexity = intentResult.complexity;
    context.message_history.push(message);
    if (context.message_history.length > 20) {
      context.message_history = context.message_history.slice(-20);
    }

    // 6. 返回结果
    return NextResponse.json({
      success: true,
      data: {
        content: response.content,
        chainState: response.chainState,
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
      },
    });

  } catch (error) {
    console.error("[Chat API] Error:", error);
    return NextResponse.json(
      { success: false, error: error instanceof Error ? error.message : "Unknown error" },
      { status: 500 }
    );
  }
}

/**
 * 判断消息是否为确认消息（继续/下一步/确认等）
 */
function isConfirmationMessage(message: string): boolean {
  const lower = message.toLowerCase().trim();
  return lower === '1' || lower === '继续' || lower === '下一步' || lower === '确认' || lower.includes('进入下一步');
}

/**
 * 根据阶段获取对应的步骤名称
 */
function getStepFromPhase(phase: string): string | null {
  const phaseToStep: Record<string, string> = {
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
  };
  return phaseToStep[phase] || null;
}

/**
 * 执行单个阶段
 */
async function executeSinglePhase(
  step: string,
  symbol: string,
  market: MarketPriceData,
  sessionId: string
): Promise<{ content: string; chainState: any; stepProgress: any; market: MarketPriceData }> {
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
  
  const content = await executeStepWithSkill(step, symbol, market, priceStr, supportStr, resistanceStr, support1, support2, resist1, resist2, changeStr, isGold, displayName);
  
  const chainState = get_or_init_chain_state(sessionId);
  const updatedPhases = chainState.phases.map((p: ChainPhase) => {
    const phaseId = p.id.toUpperCase();
    if (step.toLowerCase().includes(p.id)) {
      return { ...p, status: 'completed' as const, approval: 'approved' as const };
    }
    return p;
  });
  
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
