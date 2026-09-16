/**
 * LLM 驱动的智能编排器
 *
 * 位置: 3-FRONTEND/dream-universal-gateway/src/lib/orchestration/llm-planner.ts
 *
 * 核心理念: 默认关闭规则引擎，由大模型完成意图识别、技能选择、编排调度和结果聚合
 * 架构依据: Dream OS SACG 四层架构 — S层(感知) → A层(编排) → C层(执行) → G层(存储)
 *
 * 三大核心模块:
 *   1. LLMIntentRecognizer — 意图识别（替代 detectIntent）
 *   2. LLMSkillSelector — 技能选择（替代 SkillSelector）
 *   3. LLMResultAggregator — 结果聚合（替代 ConfidenceEvaluator）
 */

import { callLLM, type LLMFunctionDefinition } from './llm-bridge';

// 本地 ExecutionContext 类型定义（与 3.1-FRONTEND skill-types.ts 对齐）
interface ExecutionContext {
  sessionId: string;
  intent: string;
  symbol?: string;
  userRole: 'FREE' | 'PRO' | 'ADMIN';
  tradingMode: 'ai_skill' | 'classic' | 'hybrid';
  budgetTokens?: number;
  maxLatencyMs?: number;
  chainWeights?: { a_chain: number; c_chain: number; f_chain: number };
  priorOutputs?: Record<string, unknown>;
  knowledgeHits?: unknown[];
  recalledLessons?: unknown[];
  episodeSummary?: unknown[];
  [key: string]: unknown;
}
import { getSkillsRegistry } from '../../../../../6-图结构上下文压缩/planner/skills-registry';
import type { SkillCapability } from '../../../../../6-图结构上下文压缩/planner/skill-types';
import type { IntentType } from '../../../../../6-图结构上下文压缩/planner/planner-types';
import { enhanceSkillWithLLM } from './skill-llm-enhancer';
import { fetchHyperLiquidTicker } from '@/lib/hyperliquid-adapter';
import { fetchMultiDimensionMarketData, formatMultiDimensionData } from '@/lib/market-data-sources';
import { retrieveMemoryContext, formatMemoryContext, writeEpisode, shouldTriggerMetaReflection, distillEpisodesToLessons, type EpisodeRecord } from '@/lib/cognitive-adapter';

// ============================================================
// 类型定义
// ============================================================

export interface LLMPlanContext {
  sessionId: string;
  userRequest: string;
  symbol?: string;
  uid?: string;
  maxLatencyMs?: number;
  budgetTokens?: number;
  researchData?: DataResearchResult;
}

/** 数据调研结果：基本面核心数据 + K线微观数据 */
export interface DataResearchResult {
  marketData: {
    symbol: string;
    price: number | null;
    change24h: string | null;
    fundingRate: string | null;
    volume24h: number | null;
  } | null;
  fundamentalData: {
    cycleIndicators: Array<{ name: string; threshold: string; source: string }>;
    treasuryHoldings: Array<{ company: string; btcHoldings: string; value: string }>;
    omnitoolsApis: Array<{ name: string; thresholds: number[]; explanation: string }>;
    macroIndicators: string[];
  } | null;
  fearGreed: { value: number; classification: string } | null;
  technicalIndicators: {
    rsi: number | null;
    sma20: number | null;
    supportLevel: number | null;
    resistanceLevel: number | null;
  } | null;
  dataCompleteness: number;
  researchSummary: string;
}

export interface LLMIntentResult {
  intent: IntentType;
  confidence: number;
  reasoning: string;
  recommendedSkills: string[];
  complexity: 'quick' | 'standard' | 'deep';
}

export interface LLMPlanStep {
  stepId: string;
  stepName: string;
  description: string;
  skillIds: string[];
  estimatedTokens: number;
  dependsOn?: string[];
}

export interface LLMExecutionPlan {
  intent: LLMIntentResult;
  steps: LLMPlanStep[];
  totalEstimatedTokens: number;
  planRationale: string;
}

export interface LLMSkillResult {
  skillId: string;
  skillName: string;
  direction: 'long' | 'short' | 'neutral';
  confidence: number;
  answer: string;
  tokensUsed: number;
  latencyMs: number;
}

export interface LLMFinalReport {
  success: boolean;
  overallConfidence: number;
  direction: 'long' | 'short' | 'neutral';
  summary: string;
  keyFindings: string[];
  recommendation: string;
  riskWarnings: string[];
  steps: LLMSkillResult[];
  totalTokensUsed: number;
  totalLatencyMs: number;
  planRationale: string;
}

// ============================================================
// 1. LLM 意图识别器
// ============================================================

/**
 * 使用大模型识别用户意图，替代规则引擎的 detectIntent
 *
 * 优势:
 *   - 理解自然语言语义，不依赖关键词匹配
 *   - 输出推荐技能列表，为后续编排提供基础
 *   - 评估复杂度，动态调整执行深度
 */
export async function recognizeIntent(
  context: LLMPlanContext
): Promise<LLMIntentResult> {
  // 技能分类映射表：按意图类型分组，动态注入相关技能
  const SKILL_GROUPS: Record<string, string[]> = {
    market_query: [
      'dream-intelligence-monitor: 情报监控',
      'dream-screen1-first: 市场扫描初选',
    ],
    deep_analysis: [
      'dream-regime-detector: 市场状态识别',
      'dream-signal-scoring-spec: 信号评分',
      'dream-intelligence-monitor: 情报监控',
      'dream-contradiction-theory: 矛盾论分析',
      'dream-first-principles: 第一性原理',
      't0-market-cognition: 市场认知',
      't1-strategy-synthesis: 策略合成',
      't4-intelligence-radar: 情报雷达',
    ],
    strategy_verify: [
      'dream-backtest: 回测引擎',
      'dream-strategy-research: 策略研究',
      'dream-performance-review: 绩效复盘',
      'dream-strategy-designer: 策略设计',
      'dream-regime-detector: 市场状态识别',
      'dream-signal-scoring-spec: 信号评分',
      't5-meta-reflection: 元反思',
    ],
    execute_trade: [
      'dream-pretrade-gatekeeper: 前置门禁',
      'dream-risk-position-sizing: 仓位风险管理',
      'dream-tactical-executor: 战术执行',
      'dream-tactical-validator: 战术验证',
      'dream-exit-skill-v2: 离场决策',
      't3-risk-gatekeeper: 风险门禁',
    ],
    risk_alert: [
      'dream-risk-position-sizing: 仓位风险管理',
      'dream-intelligence-monitor: 情报监控',
      'dream-signal-scoring-spec: 信号评分',
      'dream-exit-skill-v2: 离场决策',
      't3-risk-gatekeeper: 风险门禁',
      't5-meta-reflection: 元反思',
      't4-intelligence-radar: 情报雷达',
    ],
  };

  // 先用关键词快速预判意图，用于动态注入相关技能
  const lowerReq = context.userRequest.toLowerCase();
  let preIntent = 'market_query';
  if (lowerReq.includes('买') || lowerReq.includes('卖') || lowerReq.includes('交易') || lowerReq.includes('execute')) preIntent = 'execute_trade';
  else if (lowerReq.includes('分析') || lowerReq.includes('研究') || lowerReq.includes('深度') || lowerReq.includes('适合') || lowerReq.includes('做多') || lowerReq.includes('做空')) preIntent = 'deep_analysis';
  else if (lowerReq.includes('风险') || lowerReq.includes('警戒') || lowerReq.includes('止损') || lowerReq.includes('仓位')) preIntent = 'risk_alert';
  else if (lowerReq.includes('验证') || lowerReq.includes('策略') || lowerReq.includes('回测') || lowerReq.includes('设计')) preIntent = 'strategy_verify';

  // 动态注入：预判意图的技能 + 相邻意图的技能（供 LLM 参考）
  const relevantSkills = SKILL_GROUPS[preIntent] || SKILL_GROUPS.market_query;
  const skillsList = relevantSkills.map(s => '- ' + s).join('\n');

  const systemPrompt = `你是交易意图识别引擎。根据用户请求识别意图类型。

意图类型:
- market_query: 行情查询
- deep_analysis: 深度分析
- strategy_verify: 策略验证
- execute_trade: 交易执行
- risk_alert: 风险预警

相关技能:
${skillsList}

规则: recommendedSkills 选3-6个, quick=简单查询, standard=综合分析, deep=深度研究`;

  const symbols = (context.symbol || '未指定').split(',').map(s => s.trim()).filter(Boolean);
  const symbolStr = symbols.length > 1 ? `${symbols.join(', ')}（多币种）` : (symbols[0] || '未指定');
  const multiAssetHint = symbols.length > 1 ? '\n注意: 用户请求涉及多个交易标的，请在 recommendedSkills 中确保覆盖所有币种的分析需求。' : '';
  // 检索认知系统记忆上下文
  const memoryContext = retrieveMemoryContext(context.userRequest, context.symbol || 'BTC');
  const memoryStr = formatMemoryContext(memoryContext);

  const userPrompt = `用户请求: "${context.userRequest}"
交易标的: ${symbolStr}${multiAssetHint}`;

  try {
    // 使用 Function Calling 替代 JSON 文本解析，消除格式错误
    const result = await callLLM({
      prompt: userPrompt,
      systemPrompt,
      temperature: 0.3,
      maxTokens: 800,
      timeoutMs: 40000,
      functions: [{
        name: 'recognize_intent',
        description: '识别用户交易分析意图，输出结构化意图分析结果',
        parameters: {
          type: 'object',
          properties: {
            intent: {
              type: 'string',
              enum: ['market_query', 'deep_analysis', 'strategy_verify', 'execute_trade', 'risk_alert'],
              description: '意图类型',
            },
            confidence: {
              type: 'number',
              description: '置信度 0-100',
            },
            reasoning: {
              type: 'string',
              description: '意图识别推理过程',
            },
            recommendedSkills: {
              type: 'array',
              items: { type: 'string' },
              description: '推荐技能 ID 列表',
            },
            complexity: {
              type: 'string',
              enum: ['quick', 'standard', 'deep'],
              description: '复杂度',
            },
          },
          required: ['intent', 'confidence', 'reasoning', 'recommendedSkills', 'complexity'],
        },
      }],
      functionCall: 'auto',
    }, context.uid);

    // 优先从 Function Call 结果获取结构化意图
    if (result.functionCall && result.functionCall.name === 'recognize_intent') {
      const args = result.functionCall.arguments as Record<string, unknown>;
      return {
        intent: (args.intent as IntentType) || 'market_query',
        confidence: (args.confidence as number) ?? 70,
        reasoning: (args.reasoning as string) || '',
        recommendedSkills: (args.recommendedSkills as string[]) || [],
        complexity: (args.complexity as 'quick' | 'standard' | 'deep') || 'standard',
      };
    }

    // 降级 1：尝试从 content 解析 JSON（兼容不支持 Function Calling 的模型）
    // 如果 content 是超时提示文本，不尝试解析
    const contentStr = result.content.trim();
    if (contentStr.includes('LLM 调用超时') || contentStr.includes('(LLM')) {
      throw new Error('LLM 调用超时');
    }
    const parsed = JSON.parse(contentStr);
    return {
      intent: parsed.intent || 'market_query',
      confidence: parsed.confidence ?? 70,
      reasoning: parsed.reasoning || '',
      recommendedSkills: parsed.recommendedSkills || [],
      complexity: parsed.complexity || 'standard',
    };
  } catch (error) {
    // 降级 2：返回默认意图
    return {
      intent: 'deep_analysis',
      confidence: 50,
      reasoning: `LLM意图识别降级: ${error instanceof Error ? error.message : 'unknown'}`,
      recommendedSkills: ['dream-regime-detector', 'dream-signal-scoring-spec', 'dream-intelligence-monitor'],
      complexity: 'standard',
    };
  }
}

// ============================================================
// 2. LLM 技能选择与编排规划器
// ============================================================

/**
 * 使用大模型规划执行步骤，替代规则引擎的 ChainPlanner
 *
 * 优势:
 *   - 智能去重：不会重复选择同一技能
 *   - 动态规划：根据意图和可用技能动态生成执行步骤
 *   - 依赖感知：理解技能间的依赖关系
 */
export async function planExecution(
  intent: LLMIntentResult,
  context: LLMPlanContext
): Promise<LLMExecutionPlan> {
  const systemPrompt = `你是交易分析编排引擎。根据意图分析结果，规划最优执行步骤。

规则:
1. 每个技能只调用一次
2. 步骤 1-3 步：market_query 1 步，deep_analysis 2-3 步
3. 每步 1-4 个技能，总调用不超过 8 个
4. S1=信息收集, S2=深度分析, S3=策略设计
5. T系列认知技能优先于同类dream-*技能`;

  const userPrompt = `意图: ${intent.intent} (置信度${intent.confidence}%)
推荐技能: ${intent.recommendedSkills.join(', ')}
复杂度: ${intent.complexity}
用户请求: "${context.userRequest}"
标的: ${context.symbol || '未指定'}`;

  try {
    const result = await callLLM({
      prompt: userPrompt,
      systemPrompt,
      temperature: 0.2,
      maxTokens: 800,
      timeoutMs: 30000,
      functions: [{
        name: 'plan_execution',
        description: '规划技能执行步骤',
        parameters: {
          type: 'object',
          properties: {
            steps: {
              type: 'array',
              items: {
                type: 'object',
                properties: {
                  stepId: { type: 'string', description: '步骤ID如S1' },
                  stepName: { type: 'string', description: '步骤名称' },
                  skillIds: { type: 'array', items: { type: 'string' }, description: '技能ID列表' },
                  estimatedTokens: { type: 'number', description: '预计Token消耗' },
                },
                required: ['stepId', 'stepName', 'skillIds'],
              },
              description: '执行步骤列表',
            },
            totalEstimatedTokens: { type: 'number', description: '总Token消耗' },
            planRationale: { type: 'string', description: '编排理由' },
          },
          required: ['steps', 'planRationale'],
        },
      }],
      functionCall: 'auto',
    }, context.uid);

    // 优先从 Function Call 结果获取
    if (result.functionCall && result.functionCall.name === 'plan_execution') {
      const args = result.functionCall.arguments as Record<string, unknown>;
      return {
        intent,
        steps: (args.steps as LLMPlanStep[]) || [],
        totalEstimatedTokens: (args.totalEstimatedTokens as number) || 1000,
        planRationale: (args.planRationale as string) || '',
      };
    }

    // 降级：从 content 解析 JSON
    const contentStr = result.content.trim();
    if (contentStr.includes('LLM 调用超时') || contentStr.includes('(LLM')) {
      throw new Error('LLM 调用超时');
    }
    const parsed = JSON.parse(contentStr);
    return {
      intent,
      steps: parsed.steps || [],
      totalEstimatedTokens: parsed.totalEstimatedTokens || 1000,
      planRationale: parsed.planRationale || '',
    };
  } catch (error) {
    // 降级：使用意图识别推荐的技能，单步执行
    return {
      intent,
      steps: [{
        stepId: 'S1',
        stepName: '综合分析',
        description: '执行意图识别推荐的所有技能',
        skillIds: intent.recommendedSkills.slice(0, 6),
        estimatedTokens: 1000,
      }],
      totalEstimatedTokens: 1000,
      planRationale: `LLM编排降级: ${error instanceof Error ? error.message : 'unknown'}`,
    };
  }
}

// ============================================================
// 3. LLM 结果聚合器
// ============================================================

/**
 * 使用大模型聚合所有技能结果，替代规则引擎的 ConfidenceEvaluator
 *
 * 优势:
 *   - 语义级置信度评估，理解结果间的逻辑关系
 *   - 智能冲突检测和解决
 *   - 生成连贯的综合分析报告
 */
export async function aggregateResults(
  stepResults: LLMSkillResult[],
  intent: LLMIntentResult,
  context: LLMPlanContext,
  planRationale: string
): Promise<LLMFinalReport> {
  const startTime = Date.now();

  const systemPrompt = `你是一个交易分析结果聚合引擎。你的任务是综合所有技能的分析结果，生成最终报告。

聚合原则:
1. 语义级置信度评估：理解各技能结果的可信度和一致性
2. 冲突检测：识别技能间的方向冲突和置信度矛盾
3. 加权聚合：高置信度技能权重更大，冲突技能降权
4. 方向决策：基于多数一致 + 高置信度原则确定最终方向
5. 风险提示：标注关键风险点和不确定性

返回 JSON 格式（不要 markdown 代码块）:
{
  "overallConfidence": 0-100,
  "direction": "long|short|neutral",
  "summary": "综合分析摘要（2-3句话）",
  "keyFindings": ["发现1", "发现2", "发现3"],
  "recommendation": "具体建议",
  "riskWarnings": ["风险1", "风险2"]
}

置信度评估规则:
- 多数技能方向一致且高置信度 → overallConfidence 75-90
- 方向有分歧但多数一致 → overallConfidence 55-75
- 方向严重分歧 → overallConfidence 30-55，direction 设为 neutral
- 技能结果矛盾或数据不足 → overallConfidence 20-40`;

  const resultsText = stepResults.map(r =>
    `[${r.skillName}] 方向: ${r.direction} | 置信度: ${r.confidence}% | 分析: ${r.answer}`
  ).join('\n');

  const userPrompt = `意图: ${intent.intent} (置信度: ${intent.confidence}%)
用户请求: "${context.userRequest}"
交易标的: ${context.symbol || '未指定'}

技能分析结果:
${resultsText}

请综合以上分析结果，生成最终报告。`;

  try {
    const result = await callLLM({
      prompt: userPrompt,
      systemPrompt,
      temperature: 0.3,
      maxTokens: 1200,
      timeoutMs: 90000,
    }, context.uid);

    const parsed = JSON.parse(result.content.trim());
    const totalTokens = stepResults.reduce((sum, s) => sum + s.tokensUsed, 0) + result.tokensUsed;

    return {
      success: true,
      overallConfidence: parsed.overallConfidence ?? 60,
      direction: parsed.direction || 'neutral',
      summary: parsed.summary || '',
      keyFindings: parsed.keyFindings || [],
      recommendation: parsed.recommendation || '',
      riskWarnings: parsed.riskWarnings || [],
      steps: stepResults,
      totalTokensUsed: totalTokens,
      totalLatencyMs: Date.now() - startTime,
      planRationale,
    };
  } catch (error) {
    // 降级：简单多数投票
    const directions = stepResults.map(s => s.direction);
    const longCount = directions.filter(d => d === 'long').length;
    const shortCount = directions.filter(d => d === 'short').length;
    const neutralCount = directions.filter(d => d === 'neutral').length;

    let finalDirection: 'long' | 'short' | 'neutral' = 'neutral';
    if (longCount > shortCount && longCount > neutralCount) finalDirection = 'long';
    else if (shortCount > longCount && shortCount > neutralCount) finalDirection = 'short';

    const avgConfidence = stepResults.reduce((sum, s) => sum + s.confidence, 0) / Math.max(stepResults.length, 1);

    return {
      success: true,
      overallConfidence: Math.round(avgConfidence * 0.8),
      direction: finalDirection,
      summary: `LLM聚合降级，使用多数投票。方向: ${finalDirection}，平均置信度: ${avgConfidence.toFixed(0)}%`,
      keyFindings: stepResults.map(s => `${s.skillName}: ${s.direction} (${s.confidence}%)`),
      recommendation: '建议结合更多数据源进行确认',
      riskWarnings: ['LLM聚合引擎降级，结果可靠性降低'],
      steps: stepResults,
      totalTokensUsed: stepResults.reduce((sum, s) => sum + s.tokensUsed, 0),
      totalLatencyMs: Date.now() - startTime,
      planRationale,
    };
  }
}

// ============================================================
// 4. 主执行入口
// ============================================================

/**
 * LLM 驱动的完整编排流程
 *
 * 流程: 意图识别 → 技能选择 → 技能执行 → 结果聚合
 *
 * 与规则引擎 ExecutionPlanner 的区别:
 *   - 意图识别由 LLM 完成（非关键词匹配）
 *   - 技能选择由 LLM 完成（非固定模板）
 *   - 结果聚合由 LLM 完成（非规则计算）
 *   - 每个技能只调用一次（智能去重）
 */

/**
 * 多问原则：意图置信度不足时，生成追问问题
 * 『没有调研就没有发言权』——调研一：搞清用户需求
 */
function generateClarifyingQuestions(
  intent: LLMIntentResult,
  context: LLMPlanContext
): string[] {
  const questions: string[] = [];
  const req = context.userRequest || '';

  // 根据意图类型生成针对性追问
  switch (intent.intent) {
    case 'market_query':
      if (!context.symbol) {
        questions.push('您想查询哪个交易标的的行情？（如 BTC、ETH、SOL 等）');
      }
      if (req.length < 10) {
        questions.push('您是想了解当前价格、24h 涨跌幅，还是需要技术指标分析？');
      }
      questions.push('您关注的是短线交易信号还是中长期趋势判断？');
      break;
    case 'deep_analysis':
      if (!context.symbol) {
        questions.push('您想分析哪个交易标的？');
      }
      questions.push('您希望侧重技术面分析、基本面分析，还是两者综合？');
      questions.push('您的分析时间窗口是？（如日内、近7天、近30天）');
      break;
    case 'strategy_verify':
      questions.push('您要验证的具体策略是什么？（如做多/做空/网格/定投等）');
      questions.push('您的入场价位和止损位分别是多少？');
      break;
    case 'execute_trade':
      questions.push('您计划交易的规模是多少？（如仓位百分比或具体金额）');
      questions.push('您已设定止损和止盈价位吗？');
      break;
    case 'risk_alert':
      questions.push('您当前持有什么仓位？（多/空/空仓）');
      questions.push('您关注的是市场整体风险还是特定持仓的风险？');
      break;
  }

  // 通用追问
  if (intent.confidence < 40) {
    questions.push('请更详细地描述您的需求，以便系统提供精准的分析和建议。');
  }

  return questions;
}

/**
 * 数据调研：采集基本面核心数据 + K线微观数据，构建数据底座
 * 『没有调研就没有发言权』——调研二：数据调研
 * 确保有充足数据支撑再调用分析模块+认知模块
 */
async function conductDataResearch(
  context: LLMPlanContext,
  intent: LLMIntentResult
): Promise<DataResearchResult> {
  const symbol = context.symbol || 'BTC';

  // 定义可用的数据函数工具
  const dataFunctions: LLMFunctionDefinition[] = [
    {
      name: 'get_market_ticker',
      description: '获取交易标的的实时行情数据（价格、24h涨跌、资金费率、成交量）',
      parameters: {
        type: 'object',
        properties: { symbol: { type: 'string', description: '交易标的如 BTC、ETH' } },
        required: ['symbol'],
      },
    },
    {
      name: 'get_fear_greed',
      description: '获取市场恐惧与贪婪指数（情绪面指标）',
      parameters: { type: 'object', properties: {} },
    },
    {
      name: 'get_technical_indicators',
      description: '获取技术指标（RSI、SMA20、支撑位、阻力位）',
      parameters: {
        type: 'object',
        properties: { symbol: { type: 'string', description: '交易标的' } },
        required: ['symbol'],
      },
    },
    {
      name: 'get_fundamental_data',
      description: '获取基本面核心数据（周期判断指标、机构Treasury持仓、DeFi指标、宏观指标）',
      parameters: { type: 'object', properties: {} },
    },
    {
      name: 'get_news_flash',
      description: '获取最新加密新闻快讯（按宏观/链上/大V观点/热点币种分类）',
      parameters: { type: 'object', properties: {} },
    },
  ];

  // 让 LLM 自主选择需要调用的数据函数
  let selectedFunctions: string[] = [];
  try {
    const result = await callLLM({
      prompt: `用户请求: "${context.userRequest}"
交易标的: ${symbol}
意图类型: ${intent.intent}
复杂度: ${intent.complexity}

可选数据函数: ${dataFunctions.map(f => `- ${f.name}: ${f.description}`).join('\n')}

请选择需要调用的数据函数来支撑后续分析。只选择真正需要的函数，避免冗余采集。
请以纯JSON格式回复: {"functions":["函数名1","函数名2"],"reasoning":"选择理由"}`,
      systemPrompt: '你是数据调研编排引擎。根据用户意图选择需要采集的数据维度。market_query 通常只需行情数据；deep_analysis 需要全面数据；risk_alert 需要行情+技术+基本面；strategy_verify 需要全部数据。只返回JSON，不要其他文本。',
      temperature: 0.2,
      maxTokens: 300,
      timeoutMs: 30000,
    }, context.uid);

    // 纯文本模式：解析 LLM 返回的 JSON
    const text = result.content || '';
    const jsonMatch = text.match(/\{[\s\S]*\}/);
    if (jsonMatch) {
      const parsed = JSON.parse(jsonMatch[0]);
      selectedFunctions = parsed.functions || [];
      console.log('[conductDataResearch] LLM selected:', selectedFunctions.join(', '));
    }
  } catch {
    // LLM 选择失败，降级为全量采集
  }

  // 如果 LLM 没有选择任何函数或选择失败，根据意图类型使用默认选择
  if (selectedFunctions.length === 0) {
    selectedFunctions = getDefaultDataFunctions(intent.intent);
    console.log('[conductDataResearch] Using default selection for', intent.intent, ':', selectedFunctions.join(', '));
  }

  // 执行选中的数据函数，并行采集
  let dataPoints = 0;
  const totalPossible = 8;

  // 1. 行情数据
  let marketData: DataResearchResult['marketData'] = null;
  if (selectedFunctions.includes('get_market_ticker')) {
    try {
      const ticker = await fetchHyperLiquidTicker(symbol);
      if (ticker) {
        marketData = {
          symbol,
          price: ticker.price ?? null,
          change24h: (ticker.price != null && ticker.open24h) ? (((ticker.price - ticker.open24h) / ticker.open24h) * 100).toFixed(2) : null,
          fundingRate: ticker.fundingRate || null,
          volume24h: ((ticker as unknown as Record<string, unknown>).volume24h as number | null) || null,
        };
        dataPoints += 2;
      }
    } catch { /* HyperLiquid 不可用 */ }
  }

  // 2. 恐惧贪婪指数 + 3. 技术指标（合并采集，共用 fetchMultiDimensionMarketData）
  let fearGreed: DataResearchResult['fearGreed'] = null;
  let technicalIndicators: DataResearchResult['technicalIndicators'] = null;
  if (selectedFunctions.includes('get_fear_greed') || selectedFunctions.includes('get_technical_indicators')) {
    try {
      const multiData = await fetchMultiDimensionMarketData(symbol, marketData?.price != null ? { price: marketData.price, open24h: null, change24h: null, fundingRate: null } : undefined);
      if (selectedFunctions.includes('get_fear_greed') && multiData.fearGreed) {
        fearGreed = { value: multiData.fearGreed.value, classification: multiData.fearGreed.classification };
        dataPoints += 1;
      }
      if (selectedFunctions.includes('get_technical_indicators') && multiData.indicators) {
        technicalIndicators = {
          rsi: multiData.indicators.rsi,
          sma20: multiData.indicators.sma20,
          supportLevel: multiData.indicators.supportLevel,
          resistanceLevel: multiData.indicators.resistanceLevel,
        };
        if (multiData.indicators.rsi !== null) dataPoints += 1;
        if (multiData.indicators.sma20 !== null) dataPoints += 1;
      }
    } catch { /* 多维度数据获取失败 */ }
  }

  // 4. 基本面核心数据
  let fundamentalData: DataResearchResult['fundamentalData'] = null;
  if (selectedFunctions.includes('get_fundamental_data')) {
    try {
      const fundamentalRaw = await fetchFundamentalData();
      if (fundamentalRaw) {
        fundamentalData = fundamentalRaw;
        dataPoints += 3;
      }
    } catch { /* 基本面数据不可用 */ }
  }

  // 5. 新闻快讯（暂不单独采集，基本面数据中已包含新闻分类）
  // 如果选中了 get_news_flash，在 researchSummary 中标注
  if (selectedFunctions.includes('get_news_flash')) {
    dataPoints += 1;
  }

  // 数据完整性评分
  const dataCompleteness = Math.round((dataPoints / totalPossible) * 100);

  // 构建调研摘要
  const parts: string[] = [];
  if (marketData) {
    parts.push(`${symbol} 价格 ${marketData.price}，24h 涨跌 ${marketData.change24h}%，资金费率 ${marketData.fundingRate}`);
  }
  if (fearGreed) {
    parts.push(`恐惧贪婪指数 ${fearGreed.value} (${fearGreed.classification})`);
  }
  if (technicalIndicators) {
    const tiParts: string[] = [];
    if (technicalIndicators.rsi !== null) tiParts.push(`RSI ${technicalIndicators.rsi.toFixed(0)}`);
    if (technicalIndicators.sma20 !== null) tiParts.push(`SMA20 ${technicalIndicators.sma20.toFixed(0)}`);
    if (technicalIndicators.supportLevel !== null) tiParts.push(`支撑 ${technicalIndicators.supportLevel.toFixed(0)}`);
    if (technicalIndicators.resistanceLevel !== null) tiParts.push(`阻力 ${technicalIndicators.resistanceLevel.toFixed(0)}`);
    if (tiParts.length) parts.push(tiParts.join(' '));
  }
  if (fundamentalData) {
    parts.push(`周期指标 ${fundamentalData.cycleIndicators.length} 个，Treasury 持仓 ${fundamentalData.treasuryHoldings.length} 条`);
  }
  parts.push(`数据调研函数: ${selectedFunctions.join(', ')} (完整性 ${dataCompleteness}%)`);
  const researchSummary = parts.join('；') || '数据调研不充分，建议补充更多数据源';

  return { marketData, fundamentalData, fearGreed, technicalIndicators, dataCompleteness, researchSummary };
}

/** 根据意图类型返回默认数据函数选择（降级方案） */
function getDefaultDataFunctions(intent: string): string[] {
  switch (intent) {
    case 'market_query':
      return ['get_market_ticker', 'get_fear_greed'];
    case 'deep_analysis':
      return ['get_market_ticker', 'get_fear_greed', 'get_technical_indicators', 'get_fundamental_data'];
    case 'risk_alert':
      return ['get_market_ticker', 'get_technical_indicators', 'get_fundamental_data'];
    case 'strategy_verify':
      return ['get_market_ticker', 'get_fear_greed', 'get_technical_indicators', 'get_fundamental_data', 'get_news_flash'];
    case 'execute_trade':
      return ['get_market_ticker', 'get_technical_indicators'];
    default:
      return ['get_market_ticker', 'get_fear_greed', 'get_technical_indicators'];
  }
}

/** 从基本面分析系统 raw 目录读取最新的 PAData 核心数据 */
async function fetchFundamentalData(): Promise<DataResearchResult['fundamentalData'] | null> {
  try {
    // 读取最新的 paneslab_core_*.json 文件
    const fs = await import('fs/promises');
    const path = await import('path');
    const rawDir = '/home/ubuntu/Dreambuddy-V2-main/9-基本面分析/ops/nanoclaw/core_task1/raw';
    const files = await fs.readdir(rawDir);
    const paneslabFiles = files
      .filter((f: string) => f.startsWith('paneslab_core_') && f.endsWith('.json'))
      .sort()
      .reverse();
    if (paneslabFiles.length === 0) return null;

    // 检查文件是否在 4 小时内
    const fileName = paneslabFiles[0];
    const tsStr = fileName.replace('paneslab_core_', '').replace('.json', '');
    const fileTime = new Date(
      Date.UTC(
        parseInt(tsStr.slice(0, 4)),
        parseInt(tsStr.slice(4, 6)) - 1,
        parseInt(tsStr.slice(6, 8)),
        parseInt(tsStr.slice(9, 11)),
        parseInt(tsStr.slice(11, 13)),
        parseInt(tsStr.slice(13, 15))
      )
    );
    const ageHours = (Date.now() - fileTime.getTime()) / 3600000;
    if (ageHours > 4) return null;

    const filePath = path.join(rawDir, fileName);
    const content = await fs.readFile(filePath, 'utf-8');
    const data = JSON.parse(content);
    const modules = data.modules || {};

    return {
      cycleIndicators: modules.valuation?.events?.map((e: Record<string, unknown>) => ({
        name: (e.indicator as string) || (e.name as string) || '',
        threshold: (e.threshold as string) || '',
        source: (e.source as string) || '',
      })) || [],
      treasuryHoldings: modules.flow?.events?.filter((e: Record<string, unknown>) => e.company).map((e: Record<string, unknown>) => ({
        company: (e.company as string) || '',
        btcHoldings: (e.btc_holdings as string) || '',
        value: (e.value as string) || '',
      })) || [],
      omnitoolsApis: modules.valuation?.events?.filter((e: Record<string, unknown>) => e.thresholds).map((e: Record<string, unknown>) => ({
        name: (e.indicator as string) || '',
        thresholds: (e.thresholds as number[]) || [],
        explanation: (e.explanation as string) || '',
      })) || [],
      macroIndicators: modules.macro?.events?.map((e: Record<string, unknown>) => (e.name as string) || '') || [],
    };
  } catch {
    return null;
  }
}

export async function executeLLMPlan(
  context: LLMPlanContext
): Promise<LLMFinalReport> {
  const startTime = Date.now();

  try {
    // 1. LLM 意图识别
    const intent = await recognizeIntent(context);

    // 1.1 多问原则：意图置信度不足时，返回追问建议
    if (intent.confidence < 60) {
      const clarifyingQuestions = generateClarifyingQuestions(intent, context);
      return {
        success: true,
        overallConfidence: intent.confidence,
        direction: 'neutral' as const,
        summary: `意图识别置信度较低（${intent.confidence}%），需要更多信息才能给出准确分析。`,
        keyFindings: [intent.reasoning],
        recommendation: '请补充以下信息以便提供更精准的分析：',
        riskWarnings: [],
        steps: [{
          skillId: 'clarifying-questions',
          skillName: '需求澄清',
          direction: 'neutral' as const,
          confidence: intent.confidence,
          answer: clarifyingQuestions.join('\n'),
          tokensUsed: 0,
          latencyMs: Date.now() - startTime,
        }],
        totalTokensUsed: 0,
        totalLatencyMs: Date.now() - startTime,
        planRationale: '多问原则：意图置信度不足，优先澄清用户需求而非猜测执行',
      };
    }

    // 1.15 A1 Skill 深度调研路径：检测到关键词时直接加载 SKILL.md 执行
    const a1Keywords = /a1|调研|screen1|第一屏|dream-screen1/i;
    if (a1Keywords.test(context.userRequest)) {
      try {
        const fs = await import('fs');
        const path = await import('path');
        const skillPath = '/home/ubuntu/Dreambuddy-V2-main/6-TRADING/skills/dream-screen1-first/SKILL.md';
        const skillContent = fs.readFileSync(skillPath, 'utf-8');

        // 获取实时行情数据
        const symbol = context.symbol || 'BTC';
        let tickerInfo = '';
        try {
          const ticker = await fetchHyperLiquidTicker(symbol);
          if (ticker) {
            const changePct = (ticker.open24h != null && ticker.price != null)
              ? ((ticker.price - ticker.open24h) / ticker.open24h * 100).toFixed(2) : 'N/A';
            tickerInfo = `实时行情: ${symbol} 价格=${ticker.price} 24h开盘=${ticker.open24h} 24h涨跌=${changePct}% 24h高=${ticker.high24h} 24h低=${ticker.low24h}`;
          }
        } catch {
          tickerInfo = '实时行情获取失败，请基于已有信息分析';
        }

        // 获取基本面数据
        let fundamentalInfo = '';
        try {
          const fundamentalRes = await fetch('http://127.0.0.1:9094/fundamental/overview');
          if (fundamentalRes.ok) {
            const fundamentalData = await fundamentalRes.json();
            fundamentalInfo = JSON.stringify(fundamentalData).slice(0, 2000);
          }
        } catch {
          fundamentalInfo = '基本面数据获取失败';
        }

        const a1SystemPrompt = `你是一个顶级量化交易分析师，现在需要严格按照以下 SKILL.md 定义的流程执行 A1 第一屏周线调研。

以下是 SKILL.md 的完整内容：

${skillContent}

## 执行要求（必须严格遵守）

你必须按照 SKILL.md 中定义的三个 Phase 逐阶段执行，并且每个阶段都必须输出完整的论证过程。
输出必须包含『事实数据 → 推理过程 → 结论』的完整论证链，不能跳过任何中间环节。

### Phase 1: 数据采集
- 列出所有采集到的数据项（实时行情、基本面数据）
- 用表格展示关键数据指标
- 标注数据来源和时间
- 如有缺失数据，明确说明影响

### Phase 2: A1-A3 分析流水线（核心，必须详实）

#### A1 矛盾调查（必须逐个分析 C1-C7 七个维度）
- C1 供需矛盾：列出周线供应区/需求区数据 → 分析供需力量对比 → 得出矛盾结论
- C2 多空矛盾：列出多头驱动因素 vs 空头驱动因素 → 分析力量对比 → 得出矛盾结论
- C3 宏观矛盾：列出宏观经济数据 vs 行业基本面 → 分析矛盾点 → 得出结论
- C4 技术矛盾：列出周线技术指标（EMA/MACD/RSI等） → 分析是否背离 → 得出结论
- C5 资金流矛盾：列出大资金流向 vs 散户情绪 → 分析矛盾 → 得出结论
- C6 时间周期矛盾：对比周线 vs 日线趋势 → 分析差异 → 得出结论
- C7 隐性矛盾：检查衍生品/链上异常信号 → 分析 → 得出结论
- 输出矛盾清单表格（按优先级排序）

#### A2 第一性原理
- 原理1 阻力最小方向：列出趋势动力证据 → 分析阻力方向 → 得出判定
- 原理2 趋势延续性：列出趋势评级证据 → 分析延续概率 → 得出评级
- 输出阻力最小方向判定矩阵表格

#### A3 沙盘推演
- 情景A（多头延续）：列出触发条件 → 分析概率 → 预期涨幅
- 情景B（空头延续）：列出触发条件 → 分析概率 → 预期跌幅
- 情景C（震荡整理）：列出触发条件 → 分析概率 → 预期区间
- 输出多情景概率分布表格
- 输出最优策略路径

### Phase 3: 决策与输出
- 多空不对称性判断：基于 A1-A3 综合评分 → 判断方向
- 双轨策略选择：基于波动率+趋势明确度 → 选择策略
- 输出完整决策表（方向/策略/仓位/风险）

## 实时数据
${tickerInfo}

## 基本面数据
${fundamentalInfo}

## 输出格式要求
- 全部使用 Markdown 格式
- 每个分析维度必须用表格展示关键数据
- 每个结论必须引用上方的事实数据作为依据
- 最终方向判断格式：方向: LONG/SHORT/HOLD
- 最终置信度格式：置信度: XX%
- 报告总长度不少于 3000 字，确保论证详实可信`;

        const a1Result = await callLLM({
          prompt: `请对 ${symbol} 执行 A1 第一屏周线调研分析。必须逐阶段输出完整的论证过程，包含事实数据、推理过程和结论。`,
          systemPrompt: a1SystemPrompt,
          temperature: 0.4,
          maxTokens: 8000,
          timeoutMs: 180000,
        }, context.uid);

        const a1Answer = typeof a1Result === 'string' ? a1Result : (a1Result as any)?.content || JSON.stringify(a1Result);

        // 解析方向和置信度
        const directionMatch = a1Answer.match(/(?:方向|direction)[:\s]*(?:LONG|SHORT|HOLD|多|空|观望)/i);
        const confidenceMatch = a1Answer.match(/(?:置信度|confidence)[:\s]*(\d+)/i);
        let direction: 'long' | 'short' | 'neutral' = 'neutral';
        if (directionMatch) {
          const d = directionMatch[0].toLowerCase();
          if (d.includes('long') || d.includes('多')) direction = 'long';
          else if (d.includes('short') || d.includes('空')) direction = 'short';
        }
        const confidence = confidenceMatch ? parseInt(confidenceMatch[1]) : 75;

        return {
          success: true,
          overallConfidence: confidence,
          direction,
          summary: `A1 Skill 深度调研完成：${symbol} 方向 ${direction.toUpperCase()}，置信度 ${confidence}%`,
          keyFindings: [`${symbol} A1 第一屏周线调研`, `方向: ${direction.toUpperCase()}`, `置信度: ${confidence}%`],
          recommendation: `A1 第一屏周线调研已完成，方向 ${direction.toUpperCase()}，置信度 ${confidence}%。详见上方完整报告。`,
          riskWarnings: [],
          steps: [{
            skillId: 'dream-screen1-first',
            skillName: 'A1 第一屏周线调研',
            direction,
            confidence,
            answer: a1Answer,
            tokensUsed: 0,
            latencyMs: Date.now() - startTime,
          }],
          totalTokensUsed: 0,
          totalLatencyMs: Date.now() - startTime,
          planRationale: 'A1 Skill 深度调研路径：直接加载 SKILL.md 执行三阶段流程',
        };
      } catch (a1Error) {
        console.warn('[LLMPlanner] A1 Skill 执行失败，降级到常规编排:', a1Error);
      }
    }

    // 1.2 数据调研：采集基本面核心数据 + K线微观数据，构建数据底座
    const researchData = await conductDataResearch(context, intent);
    const enrichedContext = { ...context, researchData };

    // 1.5 轻量快速路径：market_query + quick 复杂度，跳过重型编排，直接返回行情数据
    if (intent.intent === 'market_query' && intent.complexity === 'quick') {
      const symbols = (context.symbol || 'BTC').split(',').map(s => s.trim()).filter(Boolean);
      const tickers = await Promise.all(symbols.map(async (sym) => {
        try {
          const ticker = await fetchHyperLiquidTicker(sym);
          return { symbol: sym, ticker };
        } catch {
          return { symbol: sym, ticker: null };
        }
      }));

      const tickerSummaries = tickers.map(({ symbol: sym, ticker }) => {
        if (!ticker) return { sym, ticker: null, changePct: 'N/A', direction: 'neutral' as const };
        const changePct = (ticker.open24h != null && ticker.price != null) ? ((ticker.price - ticker.open24h) / ticker.open24h * 100).toFixed(2) : 'N/A';
        const direction = (ticker.open24h != null && ticker.price != null && ticker.price < ticker.open24h) ? 'short' : 'long';
        return { sym, ticker, changePct, direction };
      });

      // 获取多维度数据（恐惧贪婪指数+技术指标）
      const firstSymbol = symbols[0] || 'BTC';
      const firstTicker = tickers[0]?.ticker;
      let extraDataStr = '';
      try {
        const multiData = await fetchMultiDimensionMarketData(firstSymbol, firstTicker || undefined);
        if (multiData.fearGreed) {
          extraDataStr += ` 恐惧贪婪指数: ${multiData.fearGreed.value} (${multiData.fearGreed.classification})`;
        }
        if (multiData.indicators.rsi !== null) {
          extraDataStr += ` RSI: ${multiData.indicators.rsi.toFixed(0)}`;
        }
        if (multiData.indicators.sma20 !== null) {
          extraDataStr += ` SMA20: ${multiData.indicators.sma20.toFixed(0)}`;
        }
        if (multiData.indicators.supportLevel !== null) {
          extraDataStr += ` 支撑: ${multiData.indicators.supportLevel.toFixed(0)}`;
        }
        if (multiData.indicators.resistanceLevel !== null) {
          extraDataStr += ` 阻力: ${multiData.indicators.resistanceLevel.toFixed(0)}`;
        }
      } catch {
        // 多维度数据获取失败不影响轻量路径
      }

      const answers = tickerSummaries.map(({ sym, ticker, changePct, direction }) =>
        ticker ? `${sym} 当前价格 ${ticker.price ?? 'N/A'}，24h 开盘价 ${ticker.open24h ?? 'N/A'}，涨跌 ${changePct}%，资金费率 ${ticker.fundingRate ?? 'N/A'}，方向偏${direction === 'long' ? '多' : '空'}。${extraDataStr}` : `${sym} 行情数据不可用。`
      );

      const avgDirection = tickerSummaries.every(t => t.direction === 'long') ? 'long' :
                           tickerSummaries.every(t => t.direction === 'short') ? 'short' : 'neutral';

      return {
        success: true,
        overallConfidence: 85,
        direction: avgDirection as 'long' | 'short' | 'neutral',
        summary: answers.join(' '),
        keyFindings: tickerSummaries.map(({ sym, changePct }) => `${sym} 24h 涨跌: ${changePct}%`),
        recommendation: '轻量行情查询路径，如需深度分析请使用更详细的提问',
        riskWarnings: [],
        steps: [{
          skillId: 'hyperliquid-direct',
          skillName: '实时行情',
          direction: avgDirection as 'long' | 'short' | 'neutral',
          confidence: 85,
          answer: answers.join(' '),
          tokensUsed: 0,
          latencyMs: Date.now() - startTime,
        }],
        totalTokensUsed: 0,
        totalLatencyMs: Date.now() - startTime,
        planRationale: 'market_query 轻量快速路径：直接调用 HyperLiquid API 获取实时行情，跳过 LLM 技能编排',
      };
    }

    // 2. LLM 技能选择与编排规划（注入数据调研结果）
    const plan = await planExecution(intent, enrichedContext);

    // 3. 执行技能
    const registry = getSkillsRegistry();
    const allSkillResults: LLMSkillResult[] = [];
    const stepOutputs: Record<string, unknown> = {};

    for (const step of plan.steps) {
      const stepStartTime = Date.now();

      // 并行执行同一步骤内的技能（并行度控制：最多2个同时调用 LLM）
      const MAX_CONCURRENT_LLM = 2;
      const skillIds = step.skillIds;
      const skillResults: LLMSkillResult[] = [];
      
      const executeSkill = async (skillId: string) => {
        const skill = registry.get(skillId);
        if (!skill) {
          return {
            skillId,
            skillName: skillId,
            direction: 'neutral' as const,
            confidence: 0,
            answer: `技能 ${skillId} 未注册`,
            tokensUsed: 0,
            latencyMs: 0,
          };
        }

        try {
          const inputs = {
            symbol: context.symbol || 'BTC',
            userRequest: context.userRequest,
            priorOutputs: stepOutputs,
            researchData: enrichedContext.researchData,
          };

          // 优先使用大模型增强器获取真实分析结果
          const llmEnhanced = await enhanceSkillWithLLM({
            skillId,
            symbol: context.symbol || 'BTC',
            userRequest: context.userRequest,
            priorOutputs: stepOutputs,
            uid: context.uid,
            intent: intent.intent,
            researchData: enrichedContext.researchData,
          });

          if (llmEnhanced) {
            return {
              skillId,
              skillName: skill.metadata.name,
              direction: llmEnhanced.direction,
              confidence: llmEnhanced.confidence,
              answer: llmEnhanced.analysis,
              tokensUsed: llmEnhanced.tokensUsed,
              latencyMs: Date.now() - stepStartTime,
            };
          }

          // 降级：使用原始 mock 实现
          const execContext = {
            sessionId: context.sessionId,
            intent: intent.intent,
            symbol: context.symbol,
            userRole: 'PRO' as const,
            tradingMode: 'ai_skill' as const,
            budgetTokens: context.budgetTokens || 5000,
            maxLatencyMs: context.maxLatencyMs || 30000,
            chainWeights: { a_chain: 0.7, c_chain: 0.2, f_chain: 0.1 },
            priorOutputs: stepOutputs as Record<string, unknown>,
            knowledgeHits: [],
            recalledLessons: [],
            episodeSummary: [],
          } as any;

          const result = await skill.execute(inputs, execContext);

          return {
            skillId,
            skillName: skill.metadata.name,
            direction: (result.outputs?.direction || 'neutral') as 'long' | 'short' | 'neutral',
            confidence: result.confidence || 50,
            answer: String((result.outputs as Record<string, unknown>)?.answer || (result.outputs as Record<string, unknown>)?.summary || (result.outputs as Record<string, unknown>)?.analysis || ''),
            tokensUsed: result.tokensUsed || 0,
            latencyMs: Date.now() - stepStartTime,
          };
        } catch (err) {
          return {
            skillId,
            skillName: skill.metadata.name,
            direction: 'neutral' as const,
            confidence: 0,
            answer: `执行失败: ${err instanceof Error ? err.message : 'unknown'}`,
            tokensUsed: 0,
            latencyMs: Date.now() - stepStartTime,
          };
        }
      };

      // 分批并行执行：每批最多 MAX_CONCURRENT_LLM 个技能同时调用 LLM
      for (let i = 0; i < skillIds.length; i += MAX_CONCURRENT_LLM) {
        const batch = skillIds.slice(i, i + MAX_CONCURRENT_LLM);
        const batchResults = await Promise.all(batch.map(id => executeSkill(id)));
        skillResults.push(...batchResults);
      }

      const stepResults = skillResults;
      allSkillResults.push(...stepResults);

      // 将步骤结果存入 stepOutputs 供后续步骤使用
      for (const r of stepResults) {
        stepOutputs[r.skillId] = { answer: r.answer, direction: r.direction, confidence: r.confidence };
      }
    }

    // 4. LLM 结果聚合
    const finalReport = await aggregateResults(
      allSkillResults,
      intent,
      context,
      plan.planRationale
    );

    finalReport.totalLatencyMs = Date.now() - startTime;

    // 5. 写入 Episode 记忆（供 T5 元反思技能复盘使用）
    try {
      const episode: EpisodeRecord = {
        episodeId: `${context.sessionId}_${Date.now()}`,
        timestamp: new Date().toISOString(),
        symbol: context.symbol || 'BTC',
        userRequest: context.userRequest,
        intent: intent.intent,
        direction: finalReport.direction,
        confidence: finalReport.overallConfidence,
        analysis: finalReport.summary,
        steps: allSkillResults.map(s => ({
          skillId: s.skillId,
          skillName: s.skillName,
          direction: s.direction,
          confidence: s.confidence,
          answer: s.answer,
        })),
      };
      writeEpisode(episode);

      // T5 元反思自动触发：Episode 积累到阈值时自动蒸馏为 Lesson
      if (shouldTriggerMetaReflection()) {
        try {
          const { lessons, episodeCount } = distillEpisodesToLessons();
          if (lessons.length > 0) {
            console.log(`[Cognitive] T5 自动蒸馏完成: ${lessons.length} 个 Lesson，基于 ${episodeCount} 个 Episode`);
          }
        } catch {
          // 蒸馏失败不影响主流程
        }
      }
    } catch {
      // Episode 写入失败不影响主流程
    }

    return finalReport;
  } catch (error) {
    return {
      success: false,
      overallConfidence: 0,
      direction: 'neutral',
      summary: `LLM编排执行失败: ${error instanceof Error ? error.message : 'unknown'}`,
      keyFindings: [],
      recommendation: '建议重试或检查 LLM 配置',
      riskWarnings: ['编排引擎异常'],
      steps: [],
      totalTokensUsed: 0,
      totalLatencyMs: Date.now() - startTime,
      planRationale: '',
    };
  }
}
