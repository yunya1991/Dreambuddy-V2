/**
 * Fallback Engine - LLM 降级保障
 * 三层降级: LLM → 经验规则 → 默认兜底
 */

import { emitMonitorEvent } from '@/lib/monitor-bus';
import { recordRecognition, loadExperienceMemory } from './intent-memory';

// ============ 类型定义 ============

export type IntentType =
  | 'market_query' | 'deep_analysis' | 'scenario_sim' | 'strategy_verify'
  | 'execute_trade' | 'simple_qa' | 'command' | 'system_config'
  | 'credits_query' | 'artifact_query' | 'risk_alert_response'
  | 'triple_chain' | 'need_clarification' | 'clarification_result'
  | 'developer';

export type ComplexityLevel = 'simple' | 'moderate' | 'complex' | 'urgent';

export interface SessionContext {
  session_id: string;
  user_role: 'FREE' | 'PRO' | 'ADMIN';
  last_intent?: IntentType;
  last_symbol?: string;
  last_complexity?: ComplexityLevel;
  last_analysis_result?: string;
  message_history: string[];
  thinking_mode: 'quick' | 'deep' | 'stepwise' | 'scheduler';
  active_strategy_id?: string;
}

export interface IntentRecognitionResult {
  intent: IntentType;
  confidence: number;
  entities: Record<string, string>;
  complexity: ComplexityLevel;
  reasoning: string;
  method: 'llm' | 'rule' | 'follow_up' | 'default';
  context_aware: boolean;
  matchedPatternId?: string;
  // 澄清相关字段（仅当 intent == 'need_clarification' 时有值）
  clarification_options?: Array<{
    key: string;        // 用户回复时可匹配的关键词
    label: string;      // 向用户展示的标签
    target_intent: IntentType;  // 用户选择该选项后应使用的意图
    entities?: Record<string, string>;  // 建议的实体
  }>;
  clarification_question?: string;  // 向用户提问的问题
  // 用户澄清后的结果字段（仅当 intent == 'clarification_result' 时有值）
  selected_option_key?: string;     // 用户实际选择的选项key
  original_message?: string;         // 用户原始的澄清回复
}

export interface ExperiencePattern {
  id: string;
  patterns: string[];
  intent: IntentType;
  confidence: number;
  entities_template: Record<string, string>;
  complexity: ComplexityLevel;
  source: string;
  usage_count: number;
}

export interface LLMConfig {
  apiKey: string;
  endpoint: string;
  model: string;
}

// 经验模式库加载已迁移到 intent-memory.ts，通过 loadExperienceMemory() 导入

// ============ LLM 状态管理 ============

const DEEPSEEK_CONFIG: LLMConfig = {
  apiKey: process.env.DEEPSEEK_API_KEY || '',
  endpoint: 'https://api.deepseek.com/v1/chat/completions',
  model: process.env.DEEPSEEK_MODEL || 'deepseek-v4-pro',
};

let llmStatusCache: 'online' | 'offline' | 'degraded' = 'offline';
let llmLastCheck = 0;
const LLM_CHECK_INTERVAL = 60_000;

async function checkLLMStatus(): Promise<'online' | 'offline' | 'degraded'> {
  const now = Date.now();
  if (now - llmLastCheck < LLM_CHECK_INTERVAL && llmStatusCache !== 'offline') {
    return llmStatusCache;
  }

  if (!DEEPSEEK_CONFIG.apiKey) {
    llmStatusCache = 'offline';
    llmLastCheck = now;
    return llmStatusCache;
  }

  try {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 5000);
    const response = await fetch(DEEPSEEK_CONFIG.endpoint, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${DEEPSEEK_CONFIG.apiKey}`,
      },
      body: JSON.stringify({
        model: DEEPSEEK_CONFIG.model,
        messages: [{ role: 'user', content: 'ping' }],
        max_tokens: 5,
      }),
      signal: controller.signal,
    });
    clearTimeout(timeout);

    if (response.ok) llmStatusCache = 'online';
    else if (response.status === 403) llmStatusCache = 'degraded';
    else llmStatusCache = 'offline';
  } catch {
    llmStatusCache = 'offline';
  }

  llmLastCheck = now;
  return llmStatusCache;
}

// ============ LLM 调用 ============

async function callLLM(messages: Array<{ role: string; content: string }>, temperature = 0.2): Promise<string> {
  if (!DEEPSEEK_CONFIG.apiKey) {
    throw new Error('QWEN_API_KEY not configured');
  }

  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 15000);

  try {
    const response = await fetch(DEEPSEEK_CONFIG.endpoint, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${DEEPSEEK_CONFIG.apiKey}`,
      },
      body: JSON.stringify({
        model: DEEPSEEK_CONFIG.model,
        messages,
        temperature,
        max_tokens: 500,
      }),
      signal: controller.signal,
    });
    clearTimeout(timeout);

    if (!response.ok) {
      const errText = await response.text();
      if (response.status === 403) llmStatusCache = 'degraded';
      throw new Error(`LLM API error ${response.status}: ${errText}`);
    }

    const data = await response.json();
    llmStatusCache = 'online';
    return data.choices?.[0]?.message?.content ?? '';
  } catch (e) {
    clearTimeout(timeout);
    throw e;
  }
}

// ============ 实体提取 ============

function extractEntities(msg: string): Record<string, string> {
  const entities: Record<string, string> = {};

  // Symbol 检测
  const symbolMap: Record<string, string[]> = {
    'BTC': ['btc', 'bitcoin', '比特币'],
    'ETH': ['eth', 'ethereum', '以太坊'],
    'SOL': ['sol', 'solana'],
    'BNB': ['bnb'],
    'XRP': ['xrp', 'ripple'],
    'XAU': ['xau', 'gold', '黄金', '金价', '黄金价格'],
  };

  const lower = msg.toLowerCase();
  for (const [symbol, keywords] of Object.entries(symbolMap)) {
    if (keywords.some(k => lower.includes(k))) {
      entities.symbol = symbol;
      break;
    }
  }

  // Timeframe 检测
  if (msg.includes('1小时') || msg.includes('1h') || msg.includes('hour')) entities.timeframe = '1h';
  else if (msg.includes('4小时') || msg.includes('4h')) entities.timeframe = '4h';
  else if (msg.includes('日线') || msg.includes('1d') || msg.includes('daily')) entities.timeframe = '1d';
  else if (msg.includes('周') || msg.includes('1w')) entities.timeframe = '1w';

  return entities;
}

// ============ 追问检测 ============

function detectFollowUp(message: string, context?: SessionContext): { isFollowUp: boolean; intent?: IntentType } {
  if (!context?.last_intent) return { isFollowUp: false };

  const short = message.trim().length < 15;
  const followUpWords = ['为什么', '原因', '详细', '详细点', '解释', '什么意思', '如何', '还能', '然后', '接着', '呢', '为什么跌', '为什么涨'];

  if (short && followUpWords.some(w => message.includes(w))) {
    // 如果上一轮是分析类，延续分析
    if (['deep_analysis', 'scenario_sim', 'strategy_verify'].includes(context.last_intent)) {
      return { isFollowUp: true, intent: context.last_intent };
    }
    // 其他情况延续 market_query
    return { isFollowUp: true, intent: context.last_intent === 'simple_qa' ? 'market_query' : context.last_intent };
  }

  // 极短追问: "涨"/"跌"/"怎么样"
  if (short && message.trim().length < 5) {
    if (/^(涨|跌|怎么样|如何|还能|还行吗|呢)$/.test(message.trim())) {
      return { isFollowUp: true, intent: 'market_query' };
    }
  }

  return { isFollowUp: false };
}

// ============ 硬编码意图关键词规则（S系列保障层）============
/**
 * 快速关键词匹配 - 确保深度分析类请求始终能正确路由到 S 系列
 * 当经验库为空/不足时，此层保证系统的基础功能正常
 */
const HARDCODED_INTENT_RULES: Array<{
  intent: IntentType;
  complexity: ComplexityLevel;
  confidence: number;
  keywords: string[];
  id: string;
}> = [
  {
    id: 'hc_deep_analysis',
    intent: 'deep_analysis',
    complexity: 'moderate',
    confidence: 0.85,
    keywords: ['深度分析', '深入分析', '深度分析', '技术分析', '走势分析', '趋势分析', '入场策略', '策略分析', '分析策略', '机会分析', '制定策略', '交易策略', '策略建议', '持仓策略', '规划入场', '全面分析'],
  },
  {
    id: 'hc_scenario_sim',
    intent: 'scenario_sim',
    complexity: 'complex',
    confidence: 0.85,
    keywords: ['情景推演', '情景分析', '情景假设', '如果', '假设', '推演', '模拟', '极端行情', '压力测试', '最坏情况', '最好情况', '敏感性分析', 'hypothetical', 'scenario'],
  },
  {
    id: 'hc_strategy_verify',
    intent: 'strategy_verify',
    complexity: 'complex',
    confidence: 0.85,
    keywords: [
      '策略验证', '验证策略', '回测', '策略回测', '测试策略', '检验策略',
      '策略有效性', '策略质量', 'signal quality', '验证信号', '策略评估',
      '信号验证', '策略信号', '策略信号质量', '评估策略', '策略的有效性',
      '信号质量', 'backtest', 'validate strategy', 'strategy validation',
    ],
  },
  {
    id: 'hc_execute_trade',
    intent: 'execute_trade',
    complexity: 'complex',
    confidence: 0.9,
    keywords: ['开仓', '下单', '买入', '卖出', '做多', '做空', '止损', '止盈', '加仓', '减仓', '平仓', '执行交易', '立即交易', 'execute', 'place order', 'buy', 'sell'],
  },
  {
    id: 'hc_market_query',
    intent: 'market_query',
    complexity: 'simple',
    confidence: 0.85,
    keywords: ['行情', '价格', '现在', '当前', '实时', '最新', '查询', '多少', '报价', '实时行情', '现价'],
  },
  {
    id: 'hc_triple_chain',
    intent: 'triple_chain',
    complexity: 'complex',
    confidence: 0.9,
    keywords: ['全面规划', '完整策略', '综合分析', '从分析到执行', '全流程', '系统策略', '端到端', '一站式'],
  },
];

// ============ 规则引擎匹配 ============

function matchRuleEngine(message: string, context?: SessionContext): IntentRecognitionResult | null {
  const lower = message.toLowerCase().trim();

  // Step 0.1: 组合词匹配（避免泛化词误匹配）
  // 如果消息中同时出现"验证/检验/评估/测试/信号" + "策略/信号/回测/有效性"，优先判定为 strategy_verify
  const strategyVerifyActionTerms = ['验证', '检验', '评估', '测试', 'check', 'verify', 'test', 'validate', 'backtest', '信号质量', '信号的'];
  const strategyVerifyObjectTerms = ['策略', '信号', '回测', '有效性', '质量', 'strategy', 'signal', 'validation'];
  const hasActionTerm = strategyVerifyActionTerms.some(term => lower.includes(term));
  const hasObjectTerm = strategyVerifyObjectTerms.some(term => lower.includes(term));
  if (hasActionTerm && hasObjectTerm && lower.length < 200) {
    const entities = extractEntities(message);
    if (context?.last_symbol && !entities.symbol) {
      entities.symbol = context.last_symbol;
    }
    return {
      intent: 'strategy_verify',
      confidence: 0.82,
      entities,
      complexity: 'complex',
      reasoning: 'Composite keyword match: action+object pattern detected (strategy verification)',
      method: 'rule',
      matchedPatternId: 'hc_composite_strategy_verify',
      context_aware: !!context?.last_intent,
    };
  }

  // Step 0: 先检查硬编码规则（保障 S 系列请求能被正确识别）
  for (const rule of HARDCODED_INTENT_RULES) {
    const matched = rule.keywords.some(kw => lower.includes(kw.toLowerCase()));
    if (matched) {
      const entities = extractEntities(message);
      if (context?.last_symbol && !entities.symbol) {
        entities.symbol = context.last_symbol;
      }
      return {
        intent: rule.intent,
        confidence: rule.confidence,
        entities,
        complexity: rule.complexity,
        reasoning: `Hardcoded rule match: ${rule.id} (keyword-based fallback)`,
        method: 'rule',
        matchedPatternId: rule.id,
        context_aware: !!context?.last_intent,
      };
    }
  }

  // Step 1: 从经验记忆库中查找匹配
  const patterns = loadExperienceMemory();
  let bestMatch: ExperiencePattern | null = null;
  let bestScore = 0;

  for (const p of patterns) {
    for (const pat of p.patterns) {
      const regex = new RegExp(pat, 'i');
      if (regex.test(lower)) {
        const score = p.confidence;
        if (score > bestScore) {
          bestScore = score;
          bestMatch = p;
        }
        break;
      }
    }
  }

  if (!bestMatch) {
    return null;
  }

  const entities = extractEntities(message);

  // 填充 entities_template
  for (const [key, val] of Object.entries(bestMatch.entities_template)) {
    if (val === '{{auto_detect}}' && !entities[key]) continue;
    if (val !== '{{auto_detect}}' && !entities[key]) {
      entities[key] = val;
    }
  }

  // 上下文补全
  if (context?.last_symbol && !entities.symbol) {
    entities.symbol = context.last_symbol;
  }

  return {
    intent: bestMatch.intent,
    confidence: bestMatch.confidence,
    entities,
    complexity: bestMatch.complexity,
    reasoning: `Rule match: ${bestMatch.id} (${bestMatch.source})`,
    method: 'rule',
    matchedPatternId: bestMatch.id,
    context_aware: !!context?.last_intent,
  };
}

// ============ 默认兜底 ============

function defaultFallback(message: string, context?: SessionContext): IntentRecognitionResult {
  const entities = extractEntities(message);
  if (context?.last_symbol && !entities.symbol) {
    entities.symbol = context.last_symbol;
  }

  return {
    intent: 'simple_qa',
    confidence: 0.4,
    entities,
    complexity: 'simple',
    reasoning: 'Default fallback: no pattern matched',
    method: 'default',
    context_aware: false,
  };
}

// ============ LLM 意图识别 ============

async function recognizeWithLLM(message: string, context?: SessionContext): Promise<IntentRecognitionResult> {
  const allIntents = [
    'market_query (查询行情/价格)',
    'deep_analysis (深度分析走势/机会)',
    'scenario_sim (情景推演/假设分析)',
    'strategy_verify (策略验证/回测)',
    'execute_trade (下单/交易执行)',
    'simple_qa (简单问答/问候)',
    'command (系统命令)',
    'system_config (系统配置/设置)',
    'credits_query (查询余额/积分)',
    'artifact_query (查询历史记录/产物)',
    'risk_alert_response (应对风险/告警)',
    'triple_chain (全面分析+规划+执行)',
    'need_clarification (不确定意图，需要询问用户)',
  ].join(' | ');

  const systemPrompt = `你是 Dream-MultiSkill 交易系统的意图识别模块。分析用户输入，输出结构化的意图识别结果。

## 核心规则
1. **高置信度判断(>=0.7)**：意图明确、有具体交易品种或方向 → 直接输出对应意图
2. **中等置信度(0.4-0.7)**：有部分关键词但不够明确 → 输出 need_clarification，同时提供2-3个最可能的选项让用户选择
3. **低置信度(<0.4)**：完全不相关的话题 → 输出 simple_qa

## 意图类型说明
${allIntents}

## 实体说明
- symbol: 交易品种 (BTC, ETH, SOL, BNB, XRP 等)
- timeframe: 时间周期 (1h, 4h, 1d, 1w)
- direction: 方向 (long/short)

## 输出格式 (仅输出JSON，不要其他内容)
{"intent":"类型","confidence":0.0-1.0,"entities":{"symbol":"BTC","timeframe":"4h"},"complexity":"simple|moderate|complex|urgent","reasoning":"判断理由(1句话)"

## 澄清场景示例
当用户输入模糊时，如下格式输出澄清选项：
{"intent":"need_clarification","confidence":0.5,"entities":{},"complexity":"simple","reasoning":"用户意图不明确，提供2-3个可能的选项让用户选择","clarification_options":[{"key":"analysis","label":"深度分析BTC走势","target_intent":"deep_analysis","entities":{"symbol":"BTC"}},{"key":"query","label":"查询BTC实时价格","target_intent":"market_query","entities":{"symbol":"BTC"}}],"clarification_question":"你想查询什么？"}

注意: 仅输出JSON，不要解释，不要markdown，不要代码块。`;

  const contextLines: string[] = [];
  if (context?.last_intent) contextLines.push(`上一轮意图: ${context.last_intent}`);
  if (context?.last_symbol) contextLines.push(`上一轮品种: ${context.last_symbol}`);
  if (context?.last_analysis_result) contextLines.push(`上一轮结果摘要: ${context.last_analysis_result.slice(0, 80)}`);
  if (context?.message_history && context.message_history.length > 0) {
    const lastMessages = context.message_history.slice(-3);
    contextLines.push(`对话历史: ${lastMessages.map((m, i) => `[${i + 1}] ${m.slice(0, 60)}`).join(' | ')}`);
  }

  const userPrompt = `用户消息: "${message}"\n${contextLines.length > 0 ? contextLines.join('\n') : '（无前文上下文）'}\n\n请识别意图并输出JSON：`;

  const response = await callLLM([
    { role: 'system', content: systemPrompt },
    { role: 'user', content: userPrompt },
  ], 0.3);

  // 鲁棒 JSON 解析
  let parsed: any = null;

  // 方式1: 直接匹配花括号
  const jsonMatch = response.match(/\{[\s\S]*\}/);
  if (jsonMatch) {
    try { parsed = JSON.parse(jsonMatch[0]); } catch { /* skip */ }
  }

  // 方式2: 提取 ```json 代码块
  if (!parsed) {
    const codeBlockMatch = response.match(/```(?:json)?\s*([\s\S]*?)```/);
    if (codeBlockMatch) {
      try { parsed = JSON.parse(codeBlockMatch[1].trim()); } catch { /* skip */ }
    }
  }

  // 方式3: 逐行提取
  if (!parsed) {
    for (const line of response.split('\n')) {
      const trimmed = line.trim();
      if (trimmed.startsWith('{') && trimmed.endsWith('}')) {
        try { parsed = JSON.parse(trimmed); } catch { /* skip */ }
        if (parsed) break;
      }
    }
  }

  if (!parsed || !parsed.intent) {
    throw new Error('Failed to parse LLM response as intent JSON');
  }

  const validIntents: IntentType[] = [
    'market_query', 'deep_analysis', 'scenario_sim', 'strategy_verify',
    'execute_trade', 'simple_qa', 'command', 'system_config',
    'credits_query', 'artifact_query', 'risk_alert_response',
    'triple_chain', 'need_clarification', 'clarification_result',
  ];

  // 如果输出了 need_clarification，必须有选项
  if (parsed.intent === 'need_clarification') {
    const opts = parsed.clarification_options || [];
    if (!Array.isArray(opts) || opts.length === 0) {
      // LLM没有提供选项，生成默认澄清
      parsed.clarification_options = [
        { key: 'market', label: '查询行情', target_intent: 'market_query' },
        { key: 'analyze', label: '深度分析', target_intent: 'deep_analysis' },
      ];
      parsed.clarification_question = '请问你想了解什么？';
      parsed.confidence = 0.5;
    }
    const entities = { ...extractEntities(message), ...(parsed.entities || {}) };
    if (context?.last_symbol && !entities.symbol) {
      entities.symbol = context.last_symbol;
    }
    return {
      intent: 'need_clarification',
      confidence: parsed.confidence || 0.5,
      entities,
      complexity: 'simple',
      reasoning: parsed.reasoning || '用户意图不明确',
      method: 'llm',
      context_aware: !!context?.last_intent,
      clarification_options: parsed.clarification_options,
      clarification_question: parsed.clarification_question || '请选择你想做什么？',
    };
  }

  if (!validIntents.includes(parsed.intent)) {
    console.warn(`[FallbackEngine] Invalid intent "${parsed.intent}", fallback to simple_qa`);
    parsed.intent = 'simple_qa';
    parsed.confidence = 0.4;
  }

  const entities = { ...extractEntities(message), ...(parsed.entities || {}) };
  if (context?.last_symbol && !entities.symbol) {
    entities.symbol = context.last_symbol;
  }

  return {
    intent: parsed.intent,
    confidence: parsed.confidence || 0.7,
    entities,
    complexity: parsed.complexity || 'moderate',
    reasoning: parsed.reasoning || 'LLM recognized',
    method: 'llm',
    context_aware: !!context?.last_intent,
  };
}

// ============ 统一入口 ============

export async function recognizeIntent(
  message: string,
  context?: SessionContext
): Promise<IntentRecognitionResult> {
  const startTime = Date.now();
  let llmResult: IntentRecognitionResult | null = null;
  let matchedPatternId: string | undefined;

  // Step 1: 追问检测 (最快速路径)
  const followUp = detectFollowUp(message, context);
  if (followUp.isFollowUp && followUp.intent) {
    const entities = extractEntities(message);
    if (context?.last_symbol && !entities.symbol) {
      entities.symbol = context.last_symbol;
    }
    const result: IntentRecognitionResult = {
      intent: followUp.intent,
      confidence: 0.85,
      entities,
      complexity: context?.last_complexity || 'simple',
      reasoning: `Follow-up to ${context?.last_intent}`,
      method: 'follow_up',
      context_aware: true,
    };

    emitMonitorEvent({
      trace_id: `intent_${Date.now()}`,
      uid: context?.session_id || 'anonymous',
      layer: 'intent',
      phase: 'recognized',
      status: 'completed',
      intent: result.intent,
      duration_ms: Date.now() - startTime,
    });

    recordRecognition({
      input: message,
      recognized_intent: result.intent,
      recognized_confidence: result.confidence,
      recognized_method: 'follow_up',
      recognized_complexity: result.complexity,
      routing_chain: [],
      session_id: context?.session_id || 'anonymous',
      user_role: context?.user_role || 'FREE',
    });

    return result;
  }

  // Step 2: 尝试 LLM (主路径)
  const llmStatus = await checkLLMStatus();
  if (llmStatus === 'online' || llmStatus === 'degraded') {
    try {
      const llmRecognized = await recognizeWithLLM(message, context);
      llmResult = llmRecognized;

      // LLM 明确要求澄清 → 直接返回（核心增强：不确定就问用户）
      if (llmRecognized.intent === 'need_clarification') {
        emitMonitorEvent({
          trace_id: `intent_${Date.now()}`,
          uid: context?.session_id || 'anonymous',
          layer: 'intent',
          phase: 'clarification_requested',
          status: 'completed',
          intent: 'need_clarification',
          duration_ms: Date.now() - startTime,
        });

        recordRecognition({
          input: message,
          recognized_intent: 'need_clarification',
          recognized_confidence: llmRecognized.confidence,
          recognized_method: 'llm',
          recognized_complexity: llmRecognized.complexity,
          routing_chain: [],
          session_id: context?.session_id || 'anonymous',
          user_role: context?.user_role || 'FREE',
        });

        return llmRecognized;
      }

      // 低置信度 (0.4-0.6) → 用LLM生成澄清选项（而不是直接降级为规则）
      if (llmRecognized.confidence >= 0.4 && llmRecognized.confidence < 0.6) {
        const clarified = buildClarificationFromLowConfidence(message, llmRecognized, context);
        if (clarified) {
          emitMonitorEvent({
            trace_id: `intent_${Date.now()}`,
            uid: context?.session_id || 'anonymous',
            layer: 'intent',
            phase: 'low_confidence_clarification',
            status: 'completed',
            intent: 'need_clarification',
            duration_ms: Date.now() - startTime,
          });

          recordRecognition({
            input: message,
            recognized_intent: 'need_clarification',
            recognized_confidence: llmRecognized.confidence,
            recognized_method: 'llm',
            recognized_complexity: 'simple',
            routing_chain: [],
            session_id: context?.session_id || 'anonymous',
            user_role: context?.user_role || 'FREE',
          });

          return clarified;
        }
      }

      // 高置信度 (>=0.6) → 直接使用
      if (llmRecognized.confidence >= 0.6) {
        emitMonitorEvent({
          trace_id: `intent_${Date.now()}`,
          uid: context?.session_id || 'anonymous',
          layer: 'intent',
          phase: 'recognized',
          status: 'completed',
          intent: llmRecognized.intent,
          duration_ms: Date.now() - startTime,
        });

        recordRecognition({
          input: message,
          recognized_intent: llmRecognized.intent,
          recognized_confidence: llmRecognized.confidence,
          recognized_method: 'llm',
          recognized_complexity: llmRecognized.complexity,
          llm_intent: llmRecognized.intent,
          llm_confidence: llmRecognized.confidence,
          routing_chain: [],
          session_id: context?.session_id || 'anonymous',
          user_role: context?.user_role || 'FREE',
        });

        return llmRecognized;
      }

      // 置信度 < 0.4 → 尝试规则；规则不匹配时兜底但提供澄清
    } catch (e) {
      console.warn('[FallbackEngine] LLM failed, falling back to rule engine:', e);
    }
  }

  // Step 3: 规则引擎降级
  const ruleResult = matchRuleEngine(message, context);
  if (ruleResult && ruleResult.confidence >= 0.5) {
    matchedPatternId = (ruleResult as any).matchedPatternId;

    emitMonitorEvent({
      trace_id: `intent_${Date.now()}`,
      uid: context?.session_id || 'anonymous',
      layer: 'intent',
      phase: 'fallback_rule',
      status: 'completed',
      intent: ruleResult.intent,
      duration_ms: Date.now() - startTime,
    });

    recordRecognition({
      input: message,
      recognized_intent: ruleResult.intent,
      recognized_confidence: ruleResult.confidence,
      recognized_method: 'rule',
      recognized_complexity: ruleResult.complexity,
      matched_pattern_id: matchedPatternId,
      llm_intent: llmResult?.intent,
      llm_confidence: llmResult?.confidence,
      routing_chain: [],
      session_id: context?.session_id || 'anonymous',
      user_role: context?.user_role || 'FREE',
    });

    return ruleResult;
  }

  // Step 4: 默认兜底 — 但如果完全无法判断，给用户澄清机会
  const fallback = defaultFallback(message, context);

  emitMonitorEvent({
    trace_id: `intent_${Date.now()}`,
    uid: context?.session_id || 'anonymous',
    layer: 'intent',
    phase: 'fallback_default',
    status: 'completed',
    intent: fallback.intent,
    duration_ms: Date.now() - startTime,
  });

  recordRecognition({
    input: message,
    recognized_intent: fallback.intent,
    recognized_confidence: fallback.confidence,
    recognized_method: 'default',
    recognized_complexity: fallback.complexity,
    llm_intent: llmResult?.intent,
    llm_confidence: llmResult?.confidence,
    routing_chain: [],
    session_id: context?.session_id || 'anonymous',
    user_role: context?.user_role || 'FREE',
  });

  return fallback;
}

/**
 * 基于低置信度LLM结果构建澄清选项
 */
function buildClarificationFromLowConfidence(
  message: string,
  llmResult: IntentRecognitionResult,
  context?: SessionContext,
): IntentRecognitionResult | null {
  const entities = extractEntities(message);
  if (context?.last_symbol && !entities.symbol) {
    entities.symbol = context.last_symbol;
  }

  const symbol = entities.symbol || '';

  // 根据当前LLM识别结果，生成合理选项
  const primaryIntent = llmResult.intent;
  const primaryLabel = intentLabel(primaryIntent, symbol);

  // 另外两个备选意图
  const alternatives = pickAlternativeIntents(primaryIntent, symbol);

  const options = [
    { key: 'opt1', label: primaryLabel, target_intent: primaryIntent as IntentType, entities },
    ...alternatives.slice(0, 2).map((alt, i) => ({
      key: `opt${i + 2}`,
      label: alt.label,
      target_intent: alt.intent as IntentType,
      entities,
    })),
  ];

  return {
    intent: 'need_clarification',
    confidence: llmResult.confidence,
    entities,
    complexity: 'simple',
    reasoning: `意图识别置信度较低（${llmResult.confidence}），请用户澄清`,
    method: 'llm',
    context_aware: !!context?.last_intent,
    clarification_options: options,
    clarification_question: `你想做什么？请选择一个选项：`,
  };
}

function intentLabel(intent: string, symbol: string): string {
  const s = symbol ? ` ${symbol}` : '';
  switch (intent) {
    case 'market_query': return `查询${s}实时行情`;
    case 'deep_analysis': return `深度分析${s}走势`;
    case 'scenario_sim': return `情景推演${s}`;
    case 'strategy_verify': return `策略验证`;
    case 'execute_trade': return `执行交易${s}`;
    case 'triple_chain': return `全面分析规划执行${s}`;
    case 'simple_qa': return `简单问答`;
    default: return '了解更多信息';
  }
}

function pickAlternativeIntents(primaryIntent: string, symbol: string) {
  const pool = [
    { intent: 'market_query', label: intentLabel('market_query', symbol) },
    { intent: 'deep_analysis', label: intentLabel('deep_analysis', symbol) },
    { intent: 'scenario_sim', label: intentLabel('scenario_sim', symbol) },
    { intent: 'triple_chain', label: intentLabel('triple_chain', symbol) },
    { intent: 'simple_qa', label: intentLabel('simple_qa', symbol) },
  ];
  return pool.filter(p => p.intent !== primaryIntent).slice(0, 2);
}

// ============ 导出 ============

export { extractEntities, checkLLMStatus, DEEPSEEK_CONFIG };
