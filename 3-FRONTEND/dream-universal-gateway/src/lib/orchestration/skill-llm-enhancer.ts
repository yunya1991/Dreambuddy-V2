/**
 * 技能大模型增强器
 *
 * 位置: 3-FRONTEND/dream-universal-gateway/src/lib/orchestration/skill-llm-enhancer.ts
 *
 * 职责:
 *   为每个核心技能定义专用的大模型 prompt 模板，
 *   让技能通过大模型获取真实分析结果，替代 mock 随机数据。
 *
 * 设计原则:
 *   1. 每个技能有专属 prompt，确保分析内容专业且聚焦
 *   2. 大模型返回结构化 JSON，便于程序解析
 *   3. 大模型调用失败时降级到原始 mock 数据，确保可用性
 *   4. 支持上下文注入（前序技能结果、用户请求等）
 */

import { callLLM } from './llm-bridge';
import { fetchHyperLiquidTicker } from '@/lib/hyperliquid-adapter';
import { fetchMultiDimensionMarketData, formatMultiDimensionData } from '@/lib/market-data-sources';
import { isCognitiveSkill, getCognitiveSkillTemplate, retrieveMemoryContext, formatMemoryContext, type CognitiveSkillInput } from '@/lib/cognitive-adapter';

// ============================================================
// 类型定义
// ============================================================

export interface SkillLLMInput {
  skillId: string;
  symbol: string;
  userRequest: string;
  priorOutputs?: Record<string, unknown>;
  uid?: string;
  intent?: string;
  researchData?: {
    marketData: { symbol: string; price: number | null; change24h: string | null; fundingRate: string | null; volume24h: number | null } | null;
    fundamentalData: {
      cycleIndicators: Array<{ name: string; threshold: string; source: string }>;
      treasuryHoldings: Array<{ company: string; btcHoldings: string; value: string }>;
      omnitoolsApis: Array<{ name: string; thresholds: number[]; explanation: string }>;
      macroIndicators: string[];
    } | null;
    fearGreed: { value: number; classification: string } | null;
    technicalIndicators: { rsi: number | null; sma20: number | null; supportLevel: number | null; resistanceLevel: number | null } | null;
    dataCompleteness: number;
    researchSummary: string;
  } | null;
}

export interface SkillLLMOutput {
  direction: 'long' | 'short' | 'neutral';
  confidence: number;
  analysis: string;
  data: Record<string, unknown>;
  tokensUsed: number;
  latencyMs: number;
}

// ============================================================
// 技能专用 Prompt 模板
// ============================================================

interface SkillPromptTemplate {
  systemPrompt: string;
  userPromptTemplate: (input: SkillLLMInput) => string;
  parseResult: (content: string, input: SkillLLMInput) => Partial<SkillLLMOutput>;
}

const PROMPT_TEMPLATES: Record<string, SkillPromptTemplate> = {
  // ── 市场状态识别器 ──
  'dream-regime-detector': {
    systemPrompt: `你是一个专业的加密货币市场状态分析引擎。你的任务是分析给定交易标的的市场状态。

分析维度:
1. 趋势状态: 判断当前是趋势行情还是震荡行情
2. 波动率等级: 评估当前波动率水平（低/中/高/极端）
3. 动量方向: 评估短期动量方向和强度

返回 JSON 格式（不要 markdown 代码块）:
{
  "direction": "long|short|neutral",
  "confidence": 0-100,
  "analysis": "市场状态分析摘要",
  "regime": "trending|ranging|volatile",
  "recommendedStrategies": ["策略1", "策略2"]
}`,
    userPromptTemplate: (input) => `分析 ${input.symbol} 的当前市场状态。
用户请求: ${input.userRequest}
${formatPriorOutputs(input.priorOutputs)}`,
    parseResult: (content) => {
      const parsed = JSON.parse(content.trim());
      return {
        direction: parsed.direction || 'neutral',
        confidence: parsed.confidence || 70,
        analysis: parsed.analysis || '',
        data: {
          regime: parsed.regime || 'volatile',
          recommendedStrategies: parsed.recommendedStrategies || [],
        },
      };
    },
  },

  // ── 信号评分系统 ──
  'dream-signal-scoring-spec': {
    systemPrompt: `你是一个专业的交易信号评分引擎。你的任务是综合评估交易信号的强度、可靠性和风险收益比。

评分维度:
1. 技术面信号强度（趋势、均线、指标）
2. 资金流向信号（资金费率、大额转账）
3. 市场情绪信号（恐惧贪婪指数、社交媒体）
4. 风险收益比评估

返回 JSON 格式（不要 markdown 代码块）:
{
  "direction": "long|short|neutral",
  "confidence": 0-100,
  "analysis": "信号评分摘要",
  "signalScore": 0-100,
  "signalStrength": "strong|medium|weak",
  "riskRewardRatio": 1.0-5.0
}`,
    userPromptTemplate: (input) => `评估 ${input.symbol} 的交易信号强度。
用户请求: ${input.userRequest}
${formatPriorOutputs(input.priorOutputs)}`,
    parseResult: (content) => {
      const parsed = JSON.parse(content.trim());
      return {
        direction: parsed.direction || 'neutral',
        confidence: parsed.confidence || 65,
        analysis: parsed.analysis || '',
        data: {
          signalScore: parsed.signalScore || 50,
          signalStrength: parsed.signalStrength || 'medium',
          riskRewardRatio: parsed.riskRewardRatio || 1.5,
        },
      };
    },
  },

  // ── 情报监控 ──
  'dream-intelligence-monitor': {
    systemPrompt: `你是一个加密市场情报监控分析引擎。你的任务是分析市场情报、新闻事件和关键指标变化。

监控维度:
1. 链上数据: 大额转账、活跃地址、交易所流入流出
2. 资金费率: 永续合约资金费率方向和极端程度
3. 新闻事件: 近期重要新闻和事件影响
4. 市场情绪: 恐惧贪婪指数、社交媒体情绪

返回 JSON 格式（不要 markdown 代码块）:
{
  "direction": "long|short|neutral",
  "confidence": 0-100,
  "analysis": "情报监控摘要",
  "alerts": ["警报1", "警报2"],
  "alertSeverity": "high|medium|low"
}`,
    userPromptTemplate: (input) => `监控 ${input.symbol} 的市场情报和关键指标变化。
用户请求: ${input.userRequest}
${formatPriorOutputs(input.priorOutputs)}`,
    parseResult: (content) => {
      const parsed = JSON.parse(content.trim());
      return {
        direction: parsed.direction || 'neutral',
        confidence: parsed.confidence || 65,
        analysis: parsed.analysis || '',
        data: {
          alerts: parsed.alerts || [],
          alertSeverity: parsed.alertSeverity || 'low',
        },
      };
    },
  },

  // ── A0 矛盾论分析OS ──
  'dream-contradiction-theory': {
    systemPrompt: `你是基于矛盾论+孙子兵法+战争论的统一矛盾分析操作系统。你的任务是识别市场中的主要矛盾和次要矛盾。

分析框架:
1. 识别多空双方的主要矛盾（核心分歧点）
2. 识别次要矛盾（流动性与价格、短期与长期等）
3. 判断矛盾转化方向（哪方矛盾正在激化/缓解）
4. 基于矛盾分析给出方向判断

核心原则: 矛盾永远存在，禁止因"信号不足"而给出等待建议

返回 JSON 格式（不要 markdown 代码块）:
{
  "direction": "long|short|neutral",
  "confidence": 0-100,
  "analysis": "矛盾分析摘要",
  "primaryContradiction": {"type": "主要矛盾", "desc": "描述", "intensity": "high|medium|low"},
  "allContradictions": [{"type": "类型", "desc": "描述", "intensity": "high|medium|low"}]
}`,
    userPromptTemplate: (input) => `分析 ${input.symbol} 的市场矛盾结构。
用户请求: ${input.userRequest}
${formatPriorOutputs(input.priorOutputs)}`,
    parseResult: (content) => {
      const parsed = JSON.parse(content.trim());
      return {
        direction: parsed.direction || 'neutral',
        confidence: parsed.confidence || 72,
        analysis: parsed.analysis || '',
        data: {
          primaryContradiction: parsed.primaryContradiction || {},
          allContradictions: parsed.allContradictions || [],
        },
      };
    },
  },

  // ── A2 第一性原理 ──
  'dream-first-principles': {
    systemPrompt: `你是基于"阻力最小方向"和"趋势延续性"两大原理的第一性原理分析引擎。

分析框架:
1. 阻力最小方向: 价格沿阻力最小方向运动，分析当前阻力方向
2. 趋势延续性: 趋势倾向于延续而非反转，评估当前趋势强度
3. 双维度分析: 基本面×技术面交叉验证
4. 市场状态判断: 趋势/转换/震荡

返回 JSON 格式（不要 markdown 代码块）:
{
  "direction": "long|short|neutral",
  "confidence": 0-100,
  "analysis": "第一性原理分析摘要",
  "resistanceAnalysis": {"level": "high|medium|low", "keyZones": ["支撑位", "阻力位"]},
  "trendAnalysis": {"strength": "continuing|weakening", "continuation": true|false},
  "marketState": "trend|transition|range"
}`,
    userPromptTemplate: (input) => `从第一性原理角度分析 ${input.symbol} 的市场状态。
用户请求: ${input.userRequest}
${formatPriorOutputs(input.priorOutputs)}`,
    parseResult: (content) => {
      const parsed = JSON.parse(content.trim());
      return {
        direction: parsed.direction || 'neutral',
        confidence: parsed.confidence || 70,
        analysis: parsed.analysis || '',
        data: {
          resistanceAnalysis: parsed.resistanceAnalysis || {},
          trendAnalysis: parsed.trendAnalysis || {},
          marketState: parsed.marketState || 'transition',
        },
      };
    },
  },

  // ── 策略研究 ──
  'dream-strategy-research': {
    systemPrompt: `你是一个交易策略研究引擎。你的任务是研究和开发适合当前市场条件的交易策略。

研究维度:
1. 策略类型选择（趋势跟踪/均值回归/套利/做市等）
2. 入场条件设计（技术指标、价格行为、基本面触发）
3. 出场条件设计（止盈、止损、时间退出）
4. 仓位管理建议

返回 JSON 格式（不要 markdown 代码块）:
{
  "direction": "long|short|neutral",
  "confidence": 0-100,
  "analysis": "策略研究摘要",
  "strategyType": "策略类型",
  "entryConditions": ["入场条件1", "入场条件2"],
  "exitConditions": ["出场条件1", "出场条件2"],
  "positionSizing": "仓位建议"
}`,
    userPromptTemplate: (input) => `为 ${input.symbol} 研究适合当前市场的交易策略。
用户请求: ${input.userRequest}
${formatPriorOutputs(input.priorOutputs)}`,
    parseResult: (content) => {
      const parsed = JSON.parse(content.trim());
      return {
        direction: parsed.direction || 'neutral',
        confidence: parsed.confidence || 68,
        analysis: parsed.analysis || '',
        data: {
          strategyType: parsed.strategyType || '',
          entryConditions: parsed.entryConditions || [],
          exitConditions: parsed.exitConditions || [],
          positionSizing: parsed.positionSizing || '',
        },
      };
    },
  },

  // ── 基本面新闻 ──
  'dream-fundamental-news': {
    systemPrompt: `你是一个加密货币基本面新闻分析引擎。你的任务是聚合和分析近期重要新闻事件及其对市场的影响。

分析维度:
1. 宏观经济: 利率政策、通胀数据、就业数据
2. 监管动态: 各国监管政策变化
3. 行业事件: 交易所事件、技术升级、黑客攻击
4. 项目动态: 重大合作、产品发布

返回 JSON 格式（不要 markdown 代码块）:
{
  "direction": "long|short|neutral",
  "confidence": 0-100,
  "analysis": "基本面新闻摘要",
  "keyEvents": [{"event": "事件", "impact": "positive|negative|neutral", "severity": "high|medium|low"}]
}`,
    userPromptTemplate: (input) => `分析影响 ${input.symbol} 的近期重要新闻和基本面事件。
用户请求: ${input.userRequest}
${formatPriorOutputs(input.priorOutputs)}`,
    parseResult: (content) => {
      const parsed = JSON.parse(content.trim());
      return {
        direction: parsed.direction || 'neutral',
        confidence: parsed.confidence || 65,
        analysis: parsed.analysis || '',
        data: {
          keyEvents: parsed.keyEvents || [],
        },
      };
    },
  },
};

// ============================================================
// 辅助函数
// ============================================================

function formatPriorOutputs(priorOutputs?: Record<string, unknown>): string {
  if (!priorOutputs || Object.keys(priorOutputs).length === 0) {
    return '';
  }
  const lines = Object.entries(priorOutputs)
    .map(([key, value]) => {
      const v = value as { answer?: string; direction?: string; confidence?: number };
      return `- ${key}: 方向=${v.direction || '?'} 置信度=${v.confidence || '?'}% 分析=${(v.answer || '').slice(0, 100)}`;
    })
    .join('\n');
  return `\n前序技能分析结果:\n${lines}`;
}

// ============================================================
// 主执行入口
// ============================================================

/**
 * 使用大模型增强技能执行
 *
 * 如果技能有对应的 prompt 模板，调用大模型获取真实分析结果
 * 如果大模型调用失败或技能没有模板，返回 null（由调用方降级到 mock）
 */
export async function enhanceSkillWithLLM(
  input: SkillLLMInput
): Promise<SkillLLMOutput | null> {
  // 检查是否为认知技能（T0-T5）
  if (isCognitiveSkill(input.skillId)) {
    const cognitiveTemplate = getCognitiveSkillTemplate(input.skillId);
    if (!cognitiveTemplate) return null;

    const startTime = Date.now();

    // 获取多维度市场数据（资金面+情绪面+技术面+流动性）
    let marketDataStr = '';
    try {
      const ticker = await fetchHyperLiquidTicker(input.symbol || 'BTC');
      const multiData = await fetchMultiDimensionMarketData(input.symbol || 'BTC', ticker);
      marketDataStr = formatMultiDimensionData(multiData);
    } catch {
      // 行情数据获取失败不影响技能执行
    }

    // 注入数据调研结果（基本面核心数据+K线微观数据）
    if (input.researchData) {
      const rd = input.researchData;
      marketDataStr += '\n\n【数据调研摘要】数据完整性: ' + rd.dataCompleteness + '%';
      marketDataStr += '\n调研结论: ' + rd.researchSummary;
      if (rd.fundamentalData) {
        const fd = rd.fundamentalData;
        if (fd.cycleIndicators.length > 0) {
          marketDataStr += '\n\n【周期判断指标】(' + fd.cycleIndicators.length + ' 个)';
          fd.cycleIndicators.slice(0, 6).forEach(ind => {
            marketDataStr += '\n- ' + ind.name + ' | 命中线: ' + ind.threshold + ' | 来源: ' + ind.source;
          });
        }
        if (fd.treasuryHoldings.length > 0) {
          marketDataStr += '\n\n【机构持仓】';
          fd.treasuryHoldings.forEach(t => {
            marketDataStr += '\n- ' + t.company + ': ' + t.btcHoldings + ' | ' + t.value;
          });
        }
        if (fd.omnitoolsApis.length > 0) {
          marketDataStr += '\n\n【DeFi/链上指标】';
          fd.omnitoolsApis.forEach(api => {
            marketDataStr += '\n- ' + api.name + ' | 阈值: ' + JSON.stringify(api.thresholds);
          });
        }
        if (fd.macroIndicators.length > 0) {
          marketDataStr += '\n\n【宏观指标】' + fd.macroIndicators.join('、');
        }
      }
    }
    const memoryContext = retrieveMemoryContext(input.userRequest, input.symbol || 'BTC');

    // 动态超时
    let timeoutMs = 60000;
    if (input.skillId === 't0-market-cognition') {
      timeoutMs = 90000;
    } else if (input.intent === 'market_query') {
      timeoutMs = 30000;
    } else if (input.intent === 'deep_analysis') {
      timeoutMs = 90000;
    }

    try {
      const cogInput: CognitiveSkillInput = {
        symbol: input.symbol,
        userRequest: input.userRequest,
        marketData: marketDataStr,
        priorOutputs: input.priorOutputs as Record<string, unknown> | undefined,
        memoryContext,
      };

      const result = await callLLM({
        prompt: cognitiveTemplate.userPromptTemplate(cogInput),
        systemPrompt: cognitiveTemplate.systemPrompt,
        temperature: 0.4,
        maxTokens: 800,
        timeoutMs,
      }, input.uid);

      const parsed = JSON.parse(result.content.trim());
      return {
        direction: parsed.direction || 'neutral',
        confidence: parsed.confidence || 60,
        analysis: parsed.analysis || result.content.slice(0, 500),
        data: parsed,
        tokensUsed: result.tokensUsed,
        latencyMs: Date.now() - startTime,
      };
    } catch (error) {
      return null;
    }
  }

  const template = PROMPT_TEMPLATES[input.skillId];
  if (!template) {
    return null;
  }

  const startTime = Date.now();

  // 获取多维度市场数据（资金面+情绪面+技术面+流动性），注入到 prompt 中
  let marketDataStr = '';
  try {
    const ticker = await fetchHyperLiquidTicker(input.symbol || 'BTC');
    const multiData = await fetchMultiDimensionMarketData(input.symbol || 'BTC', ticker);
    marketDataStr = formatMultiDimensionData(multiData);
  } catch {
    // 行情数据获取失败不影响技能执行
  }

  // 注入数据调研结果（基本面核心数据+K线微观数据）
  if (input.researchData) {
    const rd = input.researchData;
    marketDataStr += '\n\n【数据调研摘要】数据完整性: ' + rd.dataCompleteness + '%';
    marketDataStr += '\n调研结论: ' + rd.researchSummary;
    if (rd.fundamentalData) {
      const fd = rd.fundamentalData;
      if (fd.cycleIndicators.length > 0) {
        marketDataStr += '\n\n【周期判断指标】(' + fd.cycleIndicators.length + ' 个)';
        fd.cycleIndicators.slice(0, 6).forEach(ind => {
          marketDataStr += '\n- ' + ind.name + ' | 命中线: ' + ind.threshold + ' | 来源: ' + ind.source;
        });
      }
      if (fd.treasuryHoldings.length > 0) {
        marketDataStr += '\n\n【机构持仓】';
        fd.treasuryHoldings.forEach(t => {
          marketDataStr += '\n- ' + t.company + ': ' + t.btcHoldings + ' | ' + t.value;
        });
      }
      if (fd.omnitoolsApis.length > 0) {
        marketDataStr += '\n\n【DeFi/链上指标】';
        fd.omnitoolsApis.forEach(api => {
          marketDataStr += '\n- ' + api.name + ' | 阈值: ' + JSON.stringify(api.thresholds);
        });
      }
      if (fd.macroIndicators.length > 0) {
        marketDataStr += '\n\n【宏观指标】' + fd.macroIndicators.join('、');
      }
    }
  }

  // 动态超时：根据技能 ID 和意图类型调整
  let timeoutMs = 60000; // 默认 60s
  if (input.skillId === 'dream-regime-detector') {
    timeoutMs = 90000; // 市场状态识别器需要更多时间
  } else if (input.intent === 'market_query') {
    timeoutMs = 30000; // 行情查询快速响应
  } else if (input.intent === 'deep_analysis') {
    timeoutMs = 90000; // 深度分析允许更长超时
  }

  try {
    const result = await callLLM({
      prompt: template.userPromptTemplate(input) + marketDataStr,
      systemPrompt: template.systemPrompt,
      temperature: 0.4,
      maxTokens: 800,
      timeoutMs,
    }, input.uid);

    let parsed: Partial<SkillLLMOutput>;
    try {
      parsed = template.parseResult(result.content, input);
    } catch {
      // JSON 解析失败，尝试从原始文本中提取有用信息
      parsed = {
        direction: 'neutral',
        confidence: 60,
        analysis: result.content.slice(0, 500),
        data: {},
      };
    }

    return {
      direction: parsed.direction || 'neutral',
      confidence: parsed.confidence || 60,
      analysis: parsed.analysis || '',
      data: parsed.data || {},
      tokensUsed: result.tokensUsed,
      latencyMs: Date.now() - startTime,
    };
  } catch (error) {
    console.error(`[SkillLLMEnhancer] ${input.skillId} LLM 调用失败:`, error);
    return null;
  }
}

/**
 * 检查技能是否支持大模型增强
 */
export function isSkillLLMEnhanced(skillId: string): boolean {
  return skillId in PROMPT_TEMPLATES;
}
