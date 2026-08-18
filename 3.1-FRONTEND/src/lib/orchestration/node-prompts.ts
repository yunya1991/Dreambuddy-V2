/**
 * 技能 Prompt 构建器
 *
 * 按技能ID和思维阶段构建 LLM prompt。
 * 不为每个技能写独立模板，而是按思维阶段设计通用模板，
 * 注入技能特定的元信息（名称、描述、核心问题）。
 */

import type { MarketData } from './market-data-bridge';

// ============================================================
// 类型定义
// ============================================================

export interface SkillExecutionContext {
  /** 用户请求 */
  userRequest: string;
  /** 交易标的 */
  symbol: string;
  /** 显示名 */
  displayName: string;
  /** 市场数据 */
  marketData?: MarketData;
  /** 用户偏好提示 */
  memoryNote?: string;
  /** 会话ID */
  sessionId?: string;
}

export interface SkillMeta {
  /** 技能ID */
  skillId: string;
  /** 技能名称 */
  skillName: string;
  /** 技能描述 */
  description: string;
  /** 思维阶段 */
  stage: 'research' | 'analysis' | 'design' | 'validate' | 'execute';
  /** 核心问题 */
  coreQuestion?: string;
  /** 期望产出 */
  expectedOutputs?: string[];
}

// ============================================================
// 通用 System Prompt
// ============================================================

const BASE_SYSTEM_PROMPT = `你是一个专业的量化交易策略分析师，擅长多维度市场分析、策略设计和风险管理。
你的分析应该：
1. 基于实时市场数据，避免空洞套话
2. 推理清晰，结论明确
3. 量化参数合理（入场、止损、止盈、仓位）
4. 风险意识强，标注置信度和风险等级

请用中文 Markdown 格式输出，紧凑简洁，数据自洽。`;

// ============================================================
// 按思维阶段的 Prompt 模板
// ============================================================

/**
 * 按思维阶段构建 prompt
 */
function buildStagePrompt(
  meta: SkillMeta,
  ctx: SkillExecutionContext,
  priorResults?: Map<string, string>,
): string {
  const { marketData } = ctx;
  const priceStr = marketData?.price ? `$${marketData.price.toLocaleString()}` : '未知';
  const changeStr = marketData?.change24h != null ? `${marketData.change24h >= 0 ? '+' : ''}${marketData.change24h.toFixed(2)}%` : '未知';

  // 前序结果上下文
  const chainContext = priorResults && priorResults.size > 0
    ? `\n\n【前序技能输出】\n${Array.from(priorResults.entries())
        .map(([skillId, output]) => `- ${skillId}: ${output.slice(0, 500)}...`)
        .join('\n')}\n请基于以上前序结论，做出前后自洽的分析。`
    : '';

  // 用户偏好
  const memoryNote = ctx.memoryNote || '';

  // 市场数据摘要
  const marketSummary = `已知信息：
- 标的：${ctx.displayName} (${ctx.symbol})
- 当前价格：${priceStr}
- 24h 涨跌幅：${changeStr}
- 数据来源：${marketData?.source || '未知'}`;

  // 按阶段选择模板
  const stageTemplates: Record<string, string> = {
    research: `你正在执行 **${meta.skillName}** 技能——**调研阶段**。

技能描述：${meta.description}
${meta.coreQuestion ? `核心问题：${meta.coreQuestion}` : ''}

${marketSummary}${chainContext}

请生成一份约 180-250 字的中文 Markdown 调研简报，包含：
1. **市场概况**（趋势方向 + 关键数据）
2. **关键发现**（2-3个具体观点）
3. **风险提示**（1-2个最相关风险）
4. **置信度**（0-100）${memoryNote}`,

    analysis: `你正在执行 **${meta.skillName}** 技能——**深度分析阶段**。

技能描述：${meta.description}
${meta.coreQuestion ? `核心问题：${meta.coreQuestion}` : ''}

${marketSummary}${chainContext}

请生成一份约 200-300 字的中文 Markdown 分析报告，包含：
1. **技术面分析**（趋势、指标、关键位判断）
2. **基本面/资金面分析**（资金流向、情绪、周期位置）
3. **情景推演**（3 个路径 + 概率估计）
4. **置信度**（0-100）${memoryNote}`,

    design: `你正在执行 **${meta.skillName}** 技能——**策略设计阶段**。

技能描述：${meta.description}
${meta.coreQuestion ? `核心问题：${meta.coreQuestion}` : ''}

${marketSummary}${chainContext}

请生成一份约 200-300 字的中文 Markdown 策略设计文档，包含：
1. **策略名称**（有辨识度）
2. **核心逻辑**（2-3句话）
3. **情景推演表**（3 个路径 + 概率 + 操作）
4. **交易参数**（入场 / 止损 / 止盈 / 仓位 / 盈亏比）
5. **置信度**（0-100）${memoryNote}`,

    validate: `你正在执行 **${meta.skillName}** 技能——**验证阶段**。

技能描述：${meta.description}
${meta.coreQuestion ? `核心问题：${meta.coreQuestion}` : ''}

${marketSummary}${chainContext}

请生成一份约 180-250 字的中文 Markdown 验证报告，包含：
1. **风险评估**（市场风险、策略风险、执行风险）
2. **置信度检查**（数据充分性、逻辑一致性）
3. **通过/否决判定**（明确结论）
4. **改进建议**（如有）
5. **置信度**（0-100）${memoryNote}`,

    execute: `你正在执行 **${meta.skillName}** 技能——**执行阶段**。

技能描述：${meta.description}
${meta.coreQuestion ? `核心问题：${meta.coreQuestion}` : ''}

${marketSummary}${chainContext}

请生成一份约 150-200 字的中文 Markdown 执行计划，包含：
1. **执行指令**（明确的方向、入场、止损、止盈）
2. **监控指标**（需要关注的 2-3 个指标）
3. **离场条件**
4. **应急预案**
5. **置信度**（0-100）${memoryNote}`,
  };

  return stageTemplates[meta.stage] || stageTemplates.research;
}

// ============================================================
// 对外接口
// ============================================================

/**
 * 构建技能的 LLM prompt
 *
 * 按技能ID和思维阶段生成合适的 prompt。
 * 任何技能都可调用，不需要为每个技能写独立模板。
 */
export function buildSkillPrompt(
  meta: SkillMeta,
  ctx: SkillExecutionContext,
  priorResults?: Map<string, string>,
): string {
  return buildStagePrompt(meta, ctx, priorResults);
}

/**
 * 获取技能的 system prompt
 */
export function getSkillSystemPrompt(_skillId: string): string {
  return BASE_SYSTEM_PROMPT;
}

/**
 * 从 LLM 输出中解析置信度
 */
export function parseConfidence(content: string): number {
  const match = content.match(/置信度[：:]\s*(\d+)/);
  if (match) {
    const val = parseInt(match[1], 10);
    if (val >= 0 && val <= 100) return val;
  }
  return 70; // 默认置信度
}

/**
 * 从 LLM 输出中解析交易方向
 */
export function parseDirection(content: string): 'long' | 'short' | 'neutral' | 'wait' {
  const lower = content.toLowerCase();
  if (lower.includes('做多') || lower.includes('long') || lower.includes('买入')) return 'long';
  if (lower.includes('做空') || lower.includes('short') || lower.includes('卖出')) return 'short';
  if (lower.includes('观望') || lower.includes('wait') || lower.includes('等待')) return 'wait';
  return 'neutral';
}
