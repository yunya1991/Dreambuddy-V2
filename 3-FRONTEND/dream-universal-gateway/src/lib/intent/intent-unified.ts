/**
 * intent-unified.ts — 统一意图识别管线
 * PROP-20260828B · Phase 2（Z3 §2 核心）
 *
 * 管线四级：
 *   ① command-fastpath（零 LLM）
 *   ② FC 结构化识别（callLLM + recognize_user_intent 工具）+ 修复级联
 *   ③ 规则引擎兜底（matchRuleEngine，零 LLM）
 *   ④ 默认兜底（defaultFallback）
 *
 * 所有链（chat/task/orchestrate）经此单一入口识别，返回 UnifiedIntentResult。
 * 各链适配器负责把正典结果映射回自己的视图，不在此处做任何链特有逻辑。
 */

import { callLLM } from '@/lib/orchestration/llm-bridge';
import {
  INTENT_CANON,
  IntentCanon,
  UnifiedIntentResult,
  intentLoop,
  gateAllows,
  aliasToCanon,
  canonToLegacy,
} from './intent-schema';
import { matchCommandFastpath } from './command-fastpath';
import { repairIntentArgs } from './intent-args-repair';
import { recordRecognition } from './intent-memory';
import { routeIntent } from './smart-router';
import {
  matchRuleEngine,
  defaultFallback,
  detectFollowUp,
  extractEntities,
  SessionContext,
  IntentRecognitionResult,
} from './fallback-engine';

// ============ FC 工具定义 ============

const INTENT_DESCRIPTIONS: Record<IntentCanon, string> = {
  market_query: '查询价格/行情/涨跌数据',
  deep_analysis: '要求深度分析某资产（未指定具体分析维度）',
  scenario_sim: '假设性情景推演（如果…会怎样）',
  strategy_verify: '验证/回测某策略表现',
  execute_trade: '明确下单/开平仓/买卖指令',
  simple_qa: '概念解释/知识问答',
  command: '/开头的系统命令',
  system_config: '修改系统配置/参数',
  credits_query: '查询积分/额度',
  artifact_query: '查找历史报告/产物/文档',
  risk_alert_response: '响应风险告警并给出处理意向',
  triple_chain: '要求完整三链/多阶段流程',
  need_clarification: '消息过于模糊无法判断意图',
  clarification_result: '用户对之前澄清问题的回答',
  developer: '开发/代码/系统构建类请求',
  asset_comparison: '对比多个资产强弱',
  entry_timing: '询问是否适合入场/买入时机',
  exit_timing: '询问是否该止盈/离场',
  risk_analysis: '分析风险敞口/回撤风险',
  position_sizing: '仓位大小/资金分配建议',
  market_sentiment: '市场情绪/多空倾向判断',
  trend_analysis: '趋势方向判断',
  technical_signal: '技术指标信号解读',
  support_resistance: '支撑位/阻力位分析',
  portfolio_allocation: '组合配置方案',
  portfolio_rebalance: '组合再平衡操作',
  event_analysis: '事件（议息/数据/新闻）影响分析',
  concept_explain: '交易概念名词解释',
  strategy_recommendation: '请求推荐策略',
  backtest_help: '回测工具使用帮助',
  volatility_analysis: '波动率分析',
  macro_analysis: '宏观经济分析',
  dca_strategy: '定投策略设置',
  arbitrage_opportunity: '套利机会寻找',
  sector_rotation: '板块轮动分析',
};

const FC_SYSTEM_PROMPT = `你是交易系统的意图识别器。将用户消息分类为恰好一个意图。
规则：
1. 只能从给定枚举中选择，不确定时选 need_clarification
2. 明确下单/开平仓指令才是 execute_trade；询问"该不该买/卖"是 entry_timing/exit_timing
3. 响应风险告警的消息是 risk_alert_response，不是 execute_trade
4. entities 中提取：symbol（大写，如 BTC）、timeframe、amount、leverage 等，没有则省略
5. confidence 反映判断把握（0-1）

意图定义：
${INTENT_CANON.map(i => `- ${i}: ${INTENT_DESCRIPTIONS[i]}`).join('\n')}`;

const FC_TOOL = {
  name: 'recognize_user_intent',
  description: '识别用户消息的意图、置信度和实体',
  parameters: {
    type: 'object',
    properties: {
      intent: { type: 'string', enum: [...INTENT_CANON], description: '用户意图（必选其一）' },
      confidence: { type: 'number', description: '置信度 0-1' },
      entities: {
        type: 'object',
        description: '提取的实体',
        properties: {
          symbol: { type: 'string', description: '交易对/资产，大写' },
          timeframe: { type: 'string' },
          amount: { type: 'string' },
          leverage: { type: 'string' },
        },
      },
      complexity: { type: 'string', enum: ['simple', 'moderate', 'complex'] },
      reasoning: { type: 'string', description: '一句话判断依据' },
    },
    required: ['intent', 'confidence'],
  },
};

// ============ 管线入口 ============

export interface UnifiedRecognizeOptions {
  /** fc=完整管线（默认）；rule=跳过 LLM（离线/降级测试用） */
  method?: 'fc' | 'rule';
  /** FC 超时（毫秒），默认 30s */
  timeoutMs?: number;
  /** FC 调用 max_tokens 上限（默认 300；PROP-20260829-C P2 影子探针传 150——
   *  实测 FC tool_call 需 ~100 token，Z3 原设计 50 会截断，详见 shadow-probe.ts） */
  fcMaxTokens?: number;
  /** 是否双写 intent-memory（默认 true；PROP-20260829-C P2 影子探针传 false——
   *  记忆污染封闭：P3 价值过滤/隔离仓建成前，影子样本不得落记忆） */
  recordMemory?: boolean;
  /** 透传给 callLLM 的用户 id */
  uid?: string;
}

export async function recognizeIntentUnified(
  message: string,
  context?: SessionContext,
  opts?: UnifiedRecognizeOptions
): Promise<UnifiedIntentResult> {
  const role = context?.user_role ?? 'FREE';
  const method = opts?.method ?? 'fc';
  const shouldRecord = opts?.recordMemory !== false;

  // ⓪ 追问检测（最快速路径，对齐旧引擎 Step 1；零 LLM）
  // PROP-20260828B P5修复: rule 路径此前漏掉追问级，短追问被误判为规则意图
  const followUp = detectFollowUp(message, context);
  if (followUp.isFollowUp && followUp.intent) {
    const entities = extractEntities(message);
    if (context?.last_symbol && !entities.symbol) {
      entities.symbol = context.last_symbol;
    }
    const followCanon = aliasToCanon(followUp.intent) ?? (followUp.intent as IntentCanon);
    return finalize({
      intent: followCanon,
      confidence: 0.85,
      entities,
      complexity: context?.last_complexity || 'simple',
      reasoning: `Follow-up to ${context?.last_intent}`,
      method: 'follow_up',
      context_aware: true,
      loop: intentLoop(followCanon),
      gate: { role, allowed: gateAllows(role, followCanon) },
    }, message, context, shouldRecord);
  }

  // ① 命令快路径（零 LLM）
  const cmd = matchCommandFastpath(message);
  if (cmd) {
    return finalize({
      ...cmd,
      loop: 'general',
      gate: { role, allowed: gateAllows(role, 'command') },
    }, message, context);
  }

  // ② FC 结构化识别
  if (method === 'fc') {
    try {
      const res = await callLLM(
        {
          prompt: message,
          systemPrompt: FC_SYSTEM_PROMPT,
          functions: [FC_TOOL],
          functionCall: 'auto',
          temperature: 0,
          maxTokens: opts?.fcMaxTokens ?? 300,
          timeoutMs: opts?.timeoutMs ?? 30_000,
        },
        opts?.uid
      );

      if (res.functionCall && res.functionCall.name === 'recognize_user_intent') {
        const repaired = repairIntentArgs(res.functionCall.arguments);
        if (repaired.intent) {
          return finalize({
            intent: repaired.intent,
            confidence: repaired.confidence,
            entities: repaired.entities,
            complexity: repaired.complexity,
            reasoning: repaired.reasoning,
            method: 'fc',
            context_aware: false,
            loop: intentLoop(repaired.intent),
            gate: { role, allowed: gateAllows(role, repaired.intent) },
            repair_applied: repaired.repairs.length > 0 ? repaired.repairs : undefined,
          }, message, context, shouldRecord);
        }
        // FC 返回但修复失败 → 记审计，落兜底
        console.warn('[intent-unified] FC 修复失败，落规则兜底:', repaired.repairs);
      } else {
        console.warn('[intent-unified] FC 未返回 recognize_user_intent 调用，落规则兜底');
      }
    } catch (e) {
      console.warn('[intent-unified] FC 调用失败，落规则兜底:', (e as Error).message);
    }
  }

  // ③ 规则引擎兜底（零 LLM）
  const rule = matchRuleEngine(message, context);
  if (rule && rule.confidence >= 0.5) {
    return finalize(fromLegacyResult(rule, 'rule', role, message, context), message, context, shouldRecord);
  }

  // ④ 默认兜底
  const fb = defaultFallback(message, context);
  return finalize(fromLegacyResult(fb, 'default', role, message, context), message, context, shouldRecord);
}

/**
 * PROP-20260828B P3: 记忆双写 —— 统一管线所有路径的识别结果都写入
 * intent-memory（经验进化数据源）。旧引擎 matchRuleEngine/defaultFallback
 * 本身不记录，由本函数单点补录；失败不阻塞识别主流程。
 */
function finalize(
  res: UnifiedIntentResult,
  message: string,
  context?: SessionContext,
  record = true
): UnifiedIntentResult {
  try {
    if (!record) return res;  // PROP-20260829-C P2: 影子/测试路径跳过记忆双写
    const legacyIntent = canonToLegacy(res.intent);
    const routing = routeIntent(legacyIntent, res.complexity, context);
    recordRecognition({
      input: message,
      recognized_intent: legacyIntent,
      recognized_confidence: res.confidence,
      recognized_method: res.method === 'fc' ? 'llm' : res.method,
      recognized_complexity: res.complexity,
      matched_pattern_id: res.matchedPatternId,
      routing_chain: routing.chain,
      session_id: context?.session_id ?? 'unknown',
      user_role: context?.user_role ?? 'FREE',
    });
  } catch (e) {
    console.warn('[intent-unified] memory 双写失败（不阻塞）:', (e as Error).message);
  }
  return res;
}

/** 把旧引擎结果转换为统一结果（兜底路径复用） */
function fromLegacyResult(
  legacy: IntentRecognitionResult,
  method: 'rule' | 'default',
  role: SessionContext['user_role'],
  message: string,
  context?: SessionContext
): UnifiedIntentResult {
  const canon = aliasToCanon(legacy.intent) ?? (legacy.intent as IntentCanon);
  return {
    intent: canon,
    confidence: legacy.confidence,
    entities: { ...legacy.entities },
    complexity: legacy.complexity,
    reasoning: legacy.reasoning,
    method,
    context_aware: legacy.context_aware,
    loop: intentLoop(canon),
    gate: { role, allowed: gateAllows(role, canon) },
    matchedPatternId: legacy.matchedPatternId,
    clarification_options: legacy.clarification_options?.map(o => ({
      key: o.key,
      label: o.label,
      target_intent: (aliasToCanon(o.target_intent) ?? o.target_intent) as IntentCanon,
      entities: o.entities,
    })),
    clarification_question: legacy.clarification_question,
  };
}
