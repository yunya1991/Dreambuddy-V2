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
  | 'credits_query' | 'artifact_query' | 'risk_alert_response';

export type ComplexityLevel = 'simple' | 'moderate' | 'complex' | 'urgent';

export interface SessionContext {
  session_id: string;
  user_role: 'FREE' | 'PRO' | 'ADMIN';
  last_intent?: IntentType;
  last_symbol?: string;
  last_complexity?: ComplexityLevel;
  last_analysis_result?: string;
  message_history: string[];
  thinking_mode: 'quick' | 'deep';
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

const QWEN_CONFIG: LLMConfig = {
  apiKey: process.env.QWEN_API_KEY || '',
  endpoint: 'https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions',
  model: process.env.QWEN_MODEL || 'qwen-plus',
};

let llmStatusCache: 'online' | 'offline' | 'degraded' = 'offline';
let llmLastCheck = 0;
const LLM_CHECK_INTERVAL = 60_000;

async function checkLLMStatus(): Promise<'online' | 'offline' | 'degraded'> {
  const now = Date.now();
  if (now - llmLastCheck < LLM_CHECK_INTERVAL && llmStatusCache !== 'offline') {
    return llmStatusCache;
  }

  if (!QWEN_CONFIG.apiKey) {
    llmStatusCache = 'offline';
    llmLastCheck = now;
    return llmStatusCache;
  }

  try {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 5000);
    const response = await fetch(QWEN_CONFIG.endpoint, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${QWEN_CONFIG.apiKey}`,
      },
      body: JSON.stringify({
        model: QWEN_CONFIG.model,
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
  if (!QWEN_CONFIG.apiKey) {
    throw new Error('QWEN_API_KEY not configured');
  }

  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 15000);

  try {
    const response = await fetch(QWEN_CONFIG.endpoint, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${QWEN_CONFIG.apiKey}`,
      },
      body: JSON.stringify({
        model: QWEN_CONFIG.model,
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

// ============ 规则引擎匹配 ============

function matchRuleEngine(message: string, context?: SessionContext): IntentRecognitionResult | null {
  const patterns = loadExperienceMemory();
  const lower = message.toLowerCase().trim();
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
    'market_query', 'deep_analysis', 'scenario_sim', 'strategy_verify',
    'execute_trade', 'simple_qa', 'command', 'system_config',
    'credits_query', 'artifact_query', 'risk_alert_response',
  ].join(' | ');

  const systemPrompt = `你是 Dream-MultiSkill 交易系统的意图识别模块。分析用户输入，输出结构化的意图识别结果。

## 意图类型
${allIntents}

## 输出格式 (仅输出JSON，不要其他内容)
{"intent":"类型","confidence":0.0-1.0,"entities":{"symbol":"BTC","timeframe":"4h"},"complexity":"simple|moderate|complex|urgent","reasoning":"判断理由(1句话)"}

注意: 仅输出JSON，不要解释。`;

  const contextLines: string[] = [];
  if (context?.last_intent) contextLines.push(`上一轮意图: ${context.last_intent}`);
  if (context?.last_symbol) contextLines.push(`上一轮品种: ${context.last_symbol}`);
  if (context?.message_history && context.message_history.length > 0) {
    contextLines.push(`近3条消息: ${context.message_history.slice(-3).join(' | ')}`);
  }

  const userPrompt = `用户消息: "${message}"\n${contextLines.join('\n')}`;

  const response = await callLLM([
    { role: 'system', content: systemPrompt },
    { role: 'user', content: userPrompt },
  ], 0.2);

  // 鲁棒 JSON 解析
  let parsed: any = null;

  // 方式1: 直接匹配花括号
  const jsonMatch = response.match(/\{[\s\S]*\}/);
  if (jsonMatch) {
    try { parsed = JSON.parse(jsonMatch[0]); } catch {}
  }

  // 方式2: 提取 ```json 代码块
  if (!parsed) {
    const codeBlockMatch = response.match(/```(?:json)?\s*([\s\S]*?)```/);
    if (codeBlockMatch) {
      try { parsed = JSON.parse(codeBlockMatch[1].trim()); } catch {}
    }
  }

  if (!parsed || !parsed.intent) {
    throw new Error('Failed to parse LLM response as intent JSON');
  }

  const validIntents: IntentType[] = [
    'market_query', 'deep_analysis', 'scenario_sim', 'strategy_verify',
    'execute_trade', 'simple_qa', 'command', 'system_config',
    'credits_query', 'artifact_query', 'risk_alert_response',
  ];

  if (!validIntents.includes(parsed.intent)) {
    console.warn(`[FallbackEngine] Invalid intent "${parsed.intent}", fallback to simple_qa`);
    parsed.intent = 'simple_qa';
    parsed.confidence = 0.4;
  }

  const entities = { ...extractEntities(message), ...parsed.entities };
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

    // 记录到记忆库
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

      // 低置信度 → 降级到规则
      if (llmRecognized.confidence < 0.6) {
        const ruleResult = matchRuleEngine(message, context);
        if (ruleResult && ruleResult.confidence >= llmRecognized.confidence) {
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
            llm_intent: llmRecognized.intent,
            llm_confidence: llmRecognized.confidence,
            routing_chain: [],
            session_id: context?.session_id || 'anonymous',
            user_role: context?.user_role || 'FREE',
          });

          return ruleResult;
        }
      }

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

  // Step 4: 默认兜底
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

// ============ 导出 ============

export { extractEntities, checkLLMStatus, QWEN_CONFIG };
