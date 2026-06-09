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

function getQwenApiKey(): string {
  const key = process.env.DASHSCOPE_API_KEY || process.env.QWEN_API_KEY;
  if (!key) {
    throw new Error('DASHSCOPE_API_KEY (or QWEN_API_KEY) environment variable is not set');
  }
  return key;
}

/**
 * Qwen API 配置（支持动态切换模型）
 */
const QWEN_CONFIG = {
  endpoint: 'https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions',
  model: 'qwen3-30b-a3b',  // 用户指定的模型
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
    const response = await fetch(QWEN_CONFIG.endpoint, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${getQwenApiKey()}`,
      },
      body: JSON.stringify({
        model: QWEN_CONFIG.model,
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
 * 调用 Qwen API
 */
async function callQwenAPI(messages: any[], temperature: number = 0.7): Promise<string> {
  try {
    const response = await fetch(QWEN_CONFIG.endpoint, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${getQwenApiKey()}`,
      },
      body: JSON.stringify({
        model: QWEN_CONFIG.model,
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
      throw new Error(`Qwen API error: ${response.status} ${errorText}`);
    }

    const data = await response.json();
    llmStatus = 'online';
    return data.choices[0].message.content;
  } catch (error) {
    console.error('[Qwen API] Call failed:', error);
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
 * 基于LLM的意图识别（使用Qwen）
 */
async function recognizeIntentLLM(message: string, context?: SessionContext): Promise<IntentResult> {
  const thinkingMode = context?.thinking_mode || 'quick';

  const systemPrompt = `你是交易助手的意图识别模块。根据用户消息输出JSON。

意图: market_query|deep_analysis|scenario_sim|strategy_verify|execute_trade|simple_qa
思考模式: ${thinkingMode === 'quick' ? '快速(轻量SKILL)' : '深度(A1-A5闭环)'}

输出格式:
{"intent":"类型","confidence":0.0-1.0,"entities":{"symbol":"BTC","timeframe":"4h"},"reasoning":"理由"}

仅输出JSON。`;

  const userPrompt = `消息:"${message}"
${context?.last_intent ? `上轮:${context.last_intent}` : ''}
${context?.last_symbol ? `上币:${context.last_symbol}` : ''}
${context?.message_history && context.message_history.length > 0 ? `近3条:${context.message_history.slice(-3).join('|')}` : ''}`;

  try {
    const response = await callQwenAPI([
      { role: 'system', content: systemPrompt },
      { role: 'user', content: userPrompt },
    ], 0.2);  // 低temperature保证稳定输出

    // 鲁棒JSON解析：尝试多种提取方式
    let parsed: any = null;

    // 方式1: 直接匹配花括号
    const jsonMatch = response.match(/\{[\s\S]*\}/);
    if (jsonMatch) {
      try {
        parsed = JSON.parse(jsonMatch[0]);
      } catch {}
    }

    // 方式2: 提取 ```json 代码块
    if (!parsed) {
      const codeBlockMatch = response.match(/```(?:json)?\s*([\s\S]*?)```/);
      if (codeBlockMatch) {
        try { parsed = JSON.parse(codeBlockMatch[1]); } catch {}
      }
    }

    if (!parsed || !parsed.intent) {
      throw new Error('Failed to parse LLM response as intent JSON');
    }

    // 验证intent合法性
    const validIntents: IntentType[] = ['market_query', 'deep_analysis', 'scenario_sim', 'strategy_verify', 'execute_trade', 'simple_qa'];
    if (!validIntents.includes(parsed.intent)) {
      console.warn(`[IntentLLM] Invalid intent "${parsed.intent}", fallback to simple_qa`);
      parsed.intent = 'simple_qa';
      parsed.confidence = 0.4;
    }

    return {
      intent: parsed.intent,
      confidence: parsed.confidence || 0.7,
      entities: (parsed.entities || {}) as Record<string, string>,
      complexity:
        parsed.intent === "market_query" || parsed.intent === "simple_qa"
          ? "simple"
          : parsed.intent === "deep_analysis" || parsed.intent === "strategy_verify"
            ? "moderate"
            : "complex",
      method: "llm",
      thinking_mode: thinkingMode,
      routing: {
        chain: getChainForIntent(parsed.intent, thinkingMode),
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
 */
function getChainForIntent(intent: IntentType, thinkingMode: ThinkingMode): string[] {
  if (thinkingMode === 'quick') {
    const quickChainMap: Record<IntentType, string[]> = {
      'market_query': ['market_data'],
      'deep_analysis': ['A1_research', 'A2_analysis'],
      'scenario_sim': ['A3_simulation'],
      'strategy_verify': ['A4_validation'],
      'execute_trade': ['A5_execution'],
      'simple_qa': ['direct_answer'],
      'system_config': ['direct_answer'],
      'credits_query': ['direct_answer'],
      'artifact_query': ['knowledge_base'],
      'risk_alert_response': ['A6_intelligence', 'A6_alert'],
      'command': ['route_by_command'],
    };
    return quickChainMap[intent] || ['direct_answer'];
  }

  // 深度思考：完整闭环
  const deepChainMap: Record<IntentType, string[]> = {
    'market_query': ['market_data'],
    'deep_analysis': ['A1_research', 'A2_analysis', 'A3_simulation', 'A4_validation'],
    'scenario_sim': ['A1_research', 'A3_simulation'],
    'strategy_verify': ['A4_validation', 'A5_execution'],
    'execute_trade': ['A5_execution'],
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
  const symbols = ['btc', 'eth', 'sol', 'bnb', 'xrp'];
  for (const sym of symbols) {
    if (msg.includes(sym)) {
      entities.symbol = sym.toUpperCase();
      break;
    }
  }
  if (msg.includes('1小时') || msg.includes('1h')) entities.timeframe = '1h';
  if (msg.includes('4小时') || msg.includes('4h')) entities.timeframe = '4h';
  if (msg.includes('日线') || msg.includes('1d')) entities.timeframe = '1d';
  return entities;
}

/**
 * 生成缓存Key
 */
function generateCacheKey(intent: IntentResult, message: string): string {
  const entities = intent.entities;
  return `${intent.intent}:${entities?.symbol || '*'}:${entities?.timeframe || '*'}`;
}

/**
 * 模拟处理链响应
 */
function generateChainResponse(chain: string[], intent: string, entities: Record<string, string>): string {
  const symbol = entities.symbol || "BTC";
  const responses: Record<string, string> = {
    A1_research: `🔍 **A1 市场侦察**

当前${symbol}市场状态:
- 宏观环境: CPI超预期，美联储政策观望
- 链上数据: 交易所净流出趋势
- 情绪指标: 市场情绪中性偏谨慎`,
    A2_analysis: `🧠 **A2 深度分析**

- Regime: 区间震荡 (RANGE_BOUND)
- 主要矛盾: 宏观偏鹰 vs 技术面支撑
- 阻力最小方向: 横盘偏弱
- 建议: 观望防守`,
    A3_simulation: `🎲 **A3 情景推演**

| 情景 | 概率 | 操作 |
|------|------|------|
| 区间延续 | 50% | 观望 |
| 向下突破 | 20% | A4验证后SHORT |
| 向上反弹 | 18% | 轻仓BUY |
| 暴跌 | 8% | 紧急避险 |`,
    A4_validation: `✅ **A4 策略验证**

- 当前Regime与A3结论一致
- Edge衰减在阈值内
- 无P0风险事件
- 结论: 维持观望`,
    A5_execution: `⚡ **A5 执行决策**

- 操作: 暂不开仓
- 原因: 区间震荡，等待突破信号
- 风控: 已就绪`,
    A9_exit: `🚪 **A9 离场评估**

- 当前持仓: 空仓
- 离场条件: 未触发
- 状态: 正常监控中`,
    A6_intelligence: `📡 **A6 情报监控**

- 市场Regime: RANGE_BOUND
- 风险评分: 0.3 (低)
- 无L0-L1级别告警
- 持续监控中...`,
    A6_alert: `⚠️ **A6 情报告警**

- 检测到市场信号变化
- 风险等级: 待评估
- 建议: 关注关键位`,
    market_data: `📊 **${symbol} 行情数据**

- 价格: $80,630
- 24h涨跌: -0.23%
- 24h高/低: $81,500 / $79,700
- 资金费率: +0.0034%
- 恐惧指数: 42 (Fear)`,
    knowledge_base: `📚 **知识库检索**

根据历史数据，${symbol}当前处于区间震荡阶段。
- 关键支撑: $79,700
- 关键阻力: $81,500
- 建议操作: 观望等待突破`,
    tavily_search: `🌐 **联网搜索**

最新市场资讯已获取，${symbol}市场情绪偏谨慎。`,
    direct_answer: `💬 收到你的问题，正在为你处理...`,
  };

  let result = "";
  for (const step of chain) {
    if (responses[step]) {
      result += responses[step] + "\n\n";
    }
  }
  return result || "处理完成。";
}

// ============ POST /api/chat ============

export async function POST(request: NextRequest) {
  try {
    const body = await request.json();
    const { message, session_id, thinking_mode, user_role } = body;

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

      const content = upgradeMsg + "\n\n" + generateChainResponse(routing.chain, intentResult.intent, intentResult.entities);

      return NextResponse.json({
        success: true,
        data: {
          content,
          intent: intentResult.intent,
          confidence: intentResult.confidence,
          routing,
          complexity: intentResult.complexity,
          method: intentResult.method,
          llm_status: await checkLLMStatus(),
          llm_model: process.env.QWEN_MODEL || "qwen-plus",
          timestamp: new Date().toISOString(),
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
    const response = generateChainResponse(chain, intentResult.intent, intentResult.entities);

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
        content: response,
        intent: intentResult.intent,
        confidence: intentResult.confidence,
        routing,
        complexity: intentResult.complexity,
        method: intentResult.method,
        llm_status: await checkLLMStatus(),
        llm_model: process.env.QWEN_MODEL || "qwen-plus",
        timestamp: new Date().toISOString(),
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

// ============ GET /api/chat ============

export async function GET(request: NextRequest) {
  const { searchParams } = new URL(request.url);
  const action = searchParams.get("action");

  if (action === "status") {
    return NextResponse.json({
      success: true,
      data: {
        llm_status: await checkLLMStatus(),
        llm_model: process.env.QWEN_MODEL || "qwen-plus",
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
