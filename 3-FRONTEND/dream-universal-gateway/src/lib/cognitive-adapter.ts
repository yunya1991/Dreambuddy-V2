/**
 * 认知系统适配器
 *
 * 位置: 3-FRONTEND/dream-universal-gateway/src/lib/cognitive-adapter.ts
 *
 * 职责:
 *   作为 Dream OS 编排系统与 4-MEMORY 认知系统的桥接层，
 *   提供记忆检索、经验注入、Episode 写入和 Lesson 学习能力。
 *
 * 整合点:
 *   1. recognizeIntent — 注入历史经验上下文，提升意图识别精度
 *   2. enhanceSkillWithLLM — 为 T0-T5 认知技能提供 prompt 模板
 *   3. aggregateResults — 聚合后写入 Episode 记忆
 *   4. executeLLMPlan — 执行前检索类似案例
 */

import { readFileSync, existsSync, writeFileSync, mkdirSync, readdirSync } from 'fs';
import { join, dirname } from 'path';

// ============================================================
// 类型定义
// ============================================================

export interface MemoryContext {
  relevantLessons: string[];
  similarCases: string[];
  corePrinciples: string[];
  antiPatterns: string[];
}

export interface EpisodeRecord {
  episodeId: string;
  timestamp: string;
  symbol: string;
  userRequest: string;
  intent: string;
  direction: 'long' | 'short' | 'neutral';
  confidence: number;
  analysis: string;
  steps: Array<{
    skillId: string;
    skillName: string;
    direction: string;
    confidence: number;
    answer: string;
  }>;
  marketData?: {
    price: number | null;
    open24h: number | null;
    change24h: number | null;
    fundingRate: string | null;
  };
}

export interface CognitiveSkillTemplate {
  skillId: string;
  skillName: string;
  systemPrompt: string;
  userPromptTemplate: (input: CognitiveSkillInput) => string;
}

export interface CognitiveSkillInput {
  symbol: string;
  userRequest: string;
  marketData?: string;
  priorOutputs?: Record<string, unknown>;
  memoryContext?: MemoryContext;
}

// ============================================================
// 路径配置
// ============================================================

const REPO_ROOT = process.env.REPO_ROOT || '/home/ubuntu/Dreambuddy-V2-main';
const MEMORY_ROOT = join(REPO_ROOT, '4-MEMORY');
const CORE_MEMORY_PATH = join(MEMORY_ROOT, 'CORE.md');
const EPISODES_DIR = join(MEMORY_ROOT, '0-工作记忆', 'checkpoints');
const LESSONS_DIR = join(MEMORY_ROOT, '5-通用经验');
const TRADING_SKILLS_ROOT = join(MEMORY_ROOT, '0-元记忆', 'trading-cognition', 'skills');

// ============================================================
// 记忆检索
// ============================================================

/**
 * 加载核心记忆（CORE.md）
 * 包含工程原则、方法论要点、关键架构决策、通用经验 Top 10
 */
export function loadCoreMemory(): string {
  try {
    if (!existsSync(CORE_MEMORY_PATH)) return '';
    const content = readFileSync(CORE_MEMORY_PATH, 'utf-8');
    // 截取关键部分，避免过长
    const lines = content.split('\n');
    const relevantLines = lines.filter(line =>
      line.includes('工程原则') ||
      line.includes('方法论') ||
      line.includes('架构决策') ||
      line.includes('通用经验') ||
      line.startsWith('- P') ||
      line.startsWith('- ') && (line.includes('矛盾论') || line.includes('A1') || line.includes('A8'))
    );
    return relevantLines.join('\n').slice(0, 2000);
  } catch {
    return '';
  }
}

/**
 * 检索与当前请求相关的记忆上下文
 * 包括：核心原则、通用经验、反模式、类似案例
 */
export function retrieveMemoryContext(userRequest: string, symbol: string): MemoryContext {
  const context: MemoryContext = {
    relevantLessons: [],
    similarCases: [],
    corePrinciples: [],
    antiPatterns: [],
  };

  try {
    // 加载核心原则
    const coreMemory = loadCoreMemory();
    if (coreMemory) {
      context.corePrinciples = coreMemory.split('\n').filter(line =>
        line.startsWith('- P') || line.includes('原则')
      ).slice(0, 5);
    }

    // 加载通用经验中的反模式
    const antiPatternsPath = join(LESSONS_DIR, 'solution_paths');
    if (existsSync(antiPatternsPath)) {
      const files = readdirSync(antiPatternsPath).filter(f => f.endsWith('.json')).slice(0, 5);
      for (const file of files) {
        try {
          const content = readFileSync(join(antiPatternsPath, file), 'utf-8');
          const data = JSON.parse(content);
          if (data.anti_patterns || data.antiPatterns) {
            context.antiPatterns.push(...(data.anti_patterns || data.antiPatterns).slice(0, 3));
          }
        } catch {
          // 忽略解析错误
        }
      }
    }

    // 基于关键词匹配检索相关 lesson
    const keywords = extractKeywords(userRequest, symbol);
    const lessonsDir = join(MEMORY_ROOT, '5-通用经验');
    if (existsSync(lessonsDir)) {
      const lessonFiles = readdirSync(lessonsDir).filter(f => f.endsWith('.md')).slice(0, 10);
      for (const file of lessonFiles) {
        try {
          const content = readFileSync(join(lessonsDir, file), 'utf-8');
          const matched = keywords.some(kw => content.toLowerCase().includes(kw.toLowerCase()));
          if (matched) {
            // 提取前 200 字符作为摘要
            const summary = content.slice(0, 200).replace(/\n/g, ' ');
            context.relevantLessons.push(`[${file}] ${summary}`);
          }
        } catch {
          // 忽略读取错误
        }
      }
    }

    // 检索历史 Episode 中的类似案例
    if (existsSync(EPISODES_DIR)) {
      const episodeFiles = readdirSync(EPISODES_DIR)
        .filter(f => f.endsWith('.json'))
        .sort()
        .reverse()
        .slice(0, 20);
      for (const file of episodeFiles) {
        try {
          const content = readFileSync(join(EPISODES_DIR, file), 'utf-8');
          const episode = JSON.parse(content);
          const matched = keywords.some(kw =>
            (episode.userRequest || '').toLowerCase().includes(kw.toLowerCase()) ||
            (episode.symbol || '').toLowerCase().includes(kw.toLowerCase())
          );
          if (matched) {
            const summary = `${episode.symbol || '?'} ${episode.direction || '?'} (${episode.confidence || '?'}%) - ${(episode.analysis || '').slice(0, 100)}`;
            context.similarCases.push(summary);
          }
        } catch {
          // 忽略解析错误
        }
      }
    }
  } catch (error) {
    console.warn('[cognitive-adapter] 记忆检索失败:', error);
  }

  // 检索已蒸馏的 Lesson
  const distilledLessons = getDistilledLessons();
  if (distilledLessons.length > 0) {
    context.relevantLessons.unshift(...distilledLessons.slice(0, 3));
  }

  return context;
}

/**
 * 从用户请求中提取关键词
 */
function extractKeywords(userRequest: string, symbol: string): string[] {
  const keywords: string[] = [symbol];
  const tradingKeywords = [
    'BTC', 'ETH', '做多', '做空', '风险', '持仓', '策略', '验证',
    '趋势', '震荡', '突破', '反转', '支撑', '阻力', '资金费率',
    '市场状态', '行情', '分析', '交易', '止损', '止盈',
  ];
  for (const kw of tradingKeywords) {
    if (userRequest.includes(kw)) {
      keywords.push(kw);
    }
  }
  return keywords;
}

/**
 * 将记忆上下文格式化为 prompt 注入文本
 */
export function formatMemoryContext(memory: MemoryContext): string {
  const parts: string[] = [];

  if (memory.corePrinciples.length > 0) {
    parts.push(`\n核心原则:\n${memory.corePrinciples.map(p => `  - ${p}`).join('\n')}`);
  }

  if (memory.relevantLessons.length > 0) {
    parts.push(`\n相关经验教训:\n${memory.relevantLessons.slice(0, 3).map(l => `  - ${l}`).join('\n')}`);
  }

  if (memory.similarCases.length > 0) {
    parts.push(`\n历史类似案例:\n${memory.similarCases.slice(0, 3).map(c => `  - ${c}`).join('\n')}`);
  }

  if (memory.antiPatterns.length > 0) {
    parts.push(`\n需避免的反模式:\n${memory.antiPatterns.slice(0, 3).map(a => `  - ${a}`).join('\n')}`);
  }

  return parts.length > 0 ? parts.join('\n') : '';
}

// ============================================================
// Episode 写入
// ============================================================

/**
 * 将编排结果写入 Episode 记忆
 * 用于 T5 元反思技能的复盘闭环
 */
export function writeEpisode(record: EpisodeRecord): boolean {
  try {
    if (!existsSync(EPISODES_DIR)) {
      mkdirSync(EPISODES_DIR, { recursive: true });
    }

    const filename = `episode_${record.episodeId}.json`;
    const filepath = join(EPISODES_DIR, filename);
    writeFileSync(filepath, JSON.stringify(record, null, 2), 'utf-8');
    return true;
  } catch (error) {
    console.warn('[cognitive-adapter] Episode 写入失败:', error);
    return false;
  }
}

// ============================================================
// T0-T5 认知技能 Prompt 模板
// ============================================================

const COGNITIVE_SKILL_TEMPLATES: Record<string, CognitiveSkillTemplate> = {
  // T0 市场认知
  't0-market-cognition': {
    skillId: 't0-market-cognition',
    skillName: '市场认知',
    systemPrompt: `你是 T0 市场认知引擎。职责是把『市场现在是什么』讲清楚，而不是『该怎么做』。

分析维度（7维信息采集）：
1. 资金面：主力资金流向、持仓量变化、资金费率
2. 情绪面：恐慌贪婪指数、社交媒体热度
3. 技术面：趋势状态、关键位、量价关系
4. 宏观：利率/通胀/政策周期
5. 地缘：风险事件、供应链冲击
6. 时序：日历效应、重要数据时点
7. 隐性：链上异动、大宗折价

核心步骤：
- 多维度冲突分析：识别多空对立力量，4维评分确定主冲突
- 阻力最小路径：成本摩擦(30%)+流动性摩擦(35%)+拥挤度摩擦(20%)+波动率摩擦(15%)
- Regime分类：TREND_STRONG/TREND_WEAK/RANGE_BOUND/FALSE_BREAKOUT_RISK/REVERSAL_RISK/LOW_LIQUIDITY/CHAOS
- 方向判定：LONG/SHORT/NEUTRAL/UNCERTAIN

返回 JSON 格式（不要 markdown 代码块）:
{
  "direction": "long|short|neutral",
  "confidence": 0-100,
  "analysis": "市场认知分析摘要",
  "regime": "TREND_STRONG|RANGE_BOUND|...",
  "primaryConflict": "主要冲突描述",
  "resistanceScore": -1到1
}`,
    userPromptTemplate: (input) => `分析 ${input.symbol} 的市场认知。
用户请求: ${input.userRequest}
${input.marketData || ''}${input.memoryContext ? formatMemoryContext(input.memoryContext) : ''}${formatPriorOutputs(input.priorOutputs)}`,
  },

  // T1 策略合成
  't1-strategy-synthesis': {
    skillId: 't1-strategy-synthesis',
    skillName: '策略合成',
    systemPrompt: `你是 T1 策略合成引擎。以 T0 市场认知报告为输入，合成可执行的交易策略。

核心步骤：
- 战略方向确认：基于 T0 的 Regime 和方向判定
- 入场条件设计：技术指标触发、价格行为确认
- 出场条件设计：止盈目标、止损位、时间退出
- 仓位管理：基于风险敞口和置信度

返回 JSON 格式（不要 markdown 代码块）:
{
  "direction": "long|short|neutral",
  "confidence": 0-100,
  "analysis": "策略合成摘要",
  "strategyType": "趋势跟踪|均值回归|套利",
  "entryConditions": ["条件1", "条件2"],
  "exitConditions": ["止盈", "止损"],
  "positionSizing": "仓位建议"
}`,
    userPromptTemplate: (input) => `为 ${input.symbol} 合成交易策略。
用户请求: ${input.userRequest}
${input.marketData || ''}${input.memoryContext ? formatMemoryContext(input.memoryContext) : ''}${formatPriorOutputs(input.priorOutputs)}`,
  },

  // T3 风险门禁
  't3-risk-gatekeeper': {
    skillId: 't3-risk-gatekeeper',
    skillName: '风险门禁',
    systemPrompt: `你是 T3 风险门禁引擎。在交易执行前进行最终风险检查。

检查维度：
1. 仓位风险：单笔风险敞口是否超限
2. 相关性风险：与现有持仓的相关性
3. 流动性风险：目标品种流动性是否充足
4. 极端事件风险：是否有未定价的黑天鹅风险
5. 知行合一：策略逻辑是否与实际执行一致

返回 JSON 格式（不要 markdown 代码块）:
{
  "direction": "long|short|neutral",
  "confidence": 0-100,
  "analysis": "风险评估摘要",
  "riskLevel": "low|medium|high|extreme",
  "riskFactors": ["风险因素1", "风险因素2"],
  "gateResult": "pass|conditional|fail"
}`,
    userPromptTemplate: (input) => `评估 ${input.symbol} 的交易风险。
用户请求: ${input.userRequest}
${input.marketData || ''}${input.memoryContext ? formatMemoryContext(input.memoryContext) : ''}${formatPriorOutputs(input.priorOutputs)}`,
  },

  // T4 情报雷达
  't4-intelligence-radar': {
    skillId: 't4-intelligence-radar',
    skillName: '情报雷达',
    systemPrompt: `你是 T4 情报雷达引擎。持续监控市场异常和情报信号。

监控维度：
1. 价格异常：闪崩、插针、异常波动
2. 资金异常：大额转账、交易所流入流出
3. 情绪异常：恐慌贪婪指数极端值
4. 新闻事件：监管动态、行业事件
5. 链上信号：巨鲸动向、异常交易

返回 JSON 格式（不要 markdown 代码块）:
{
  "direction": "long|short|neutral",
  "confidence": 0-100,
  "analysis": "情报监控摘要",
  "alerts": [{"type": "价格|资金|情绪|新闻|链上", "severity": "high|medium|low", "description": "描述"}]
}`,
    userPromptTemplate: (input) => `监控 ${input.symbol} 的市场情报。
用户请求: ${input.userRequest}
${input.marketData || ''}${input.memoryContext ? formatMemoryContext(input.memoryContext) : ''}${formatPriorOutputs(input.priorOutputs)}`,
  },

  // T5 元反思
  't5-meta-reflection': {
    skillId: 't5-meta-reflection',
    skillName: '元反思',
    systemPrompt: `你是 T5 元认知复盘引擎。对已结束的交易决策进行复盘，提炼可复用的认知资产。

四步闭环：
1. 记录：决策依据五要素（进/预期/止损/仓位/信心度）
2. 对比：实际 vs 预期（盈亏/时间/条件/执行）
3. 归因：认知偏差识别（确认偏误/损失厌恶/过度自信/情绪化执行）
4. 迭代：提炼 lesson（格式：在[条件X]下，应该[动作Y]，因为[证据Z]）

铁律：复盘必须基于实际数据，不允许凭记忆复盘。lesson 必须可执行。

返回 JSON 格式（不要 markdown 代码块）:
{
  "direction": "long|short|neutral",
  "confidence": 0-100,
  "analysis": "复盘分析摘要",
  "cognitiveBiases": ["偏差类型: 具体证据"],
  "lessons": ["在[条件]下，应该[动作]，因为[证据]"],
  "credibilityScore": 0-100
}`,
    userPromptTemplate: (input) => `复盘 ${input.symbol} 的交易决策。
用户请求: ${input.userRequest}
${input.marketData || ''}${input.memoryContext ? formatMemoryContext(input.memoryContext) : ''}${formatPriorOutputs(input.priorOutputs)}`,
  },
};

/**
 * 获取认知技能模板
 */
export function getCognitiveSkillTemplate(skillId: string): CognitiveSkillTemplate | null {
  return COGNITIVE_SKILL_TEMPLATES[skillId] || null;
}

/**
 * 获取所有认知技能 ID
 */
export function getCognitiveSkillIds(): string[] {
  return Object.keys(COGNITIVE_SKILL_TEMPLATES);
}

/**
 * 判断技能是否为认知技能
 */
export function isCognitiveSkill(skillId: string): boolean {
  return skillId in COGNITIVE_SKILL_TEMPLATES;
}

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
// Episode 计数与记忆蒸馏
// ============================================================

const DISTILLED_LESSONS_DIR = join(MEMORY_ROOT, '5-通用经验', 'distilled-lessons');
const EPISODE_TRIGGER_THRESHOLD = 5; // Episode 积累到5个后自动触发蒸馏

/**
 * 统计 Episode 数量
 */
export function countEpisodes(): number {
  try {
    if (!existsSync(EPISODES_DIR)) return 0;
    return readdirSync(EPISODES_DIR).filter(f => f.startsWith('episode_') && f.endsWith('.json')).length;
  } catch {
    return 0;
  }
}

/**
 * 获取最近的 Episode 列表
 */
export function getRecentEpisodes(limit: number = 10): EpisodeRecord[] {
  try {
    if (!existsSync(EPISODES_DIR)) return [];
    const files = readdirSync(EPISODES_DIR)
      .filter(f => f.startsWith('episode_') && f.endsWith('.json'))
      .sort()
      .reverse()
      .slice(0, limit);
    const episodes: EpisodeRecord[] = [];
    for (const file of files) {
      try {
        const content = readFileSync(join(EPISODES_DIR, file), 'utf-8');
        episodes.push(JSON.parse(content));
      } catch {
        // 忽略解析错误
      }
    }
    return episodes;
  } catch {
    return [];
  }
}

/**
 * 将 Episode 蒸馏为 Lesson
 * 
 * 蒸馏逻辑：
 * 1. 按方向（long/short/neutral）分组统计
 * 2. 提取高频模式（相同方向+相似置信度范围）
 * 3. 生成 Lesson 文件（格式：在[条件X]下，应该[动作Y]，因为[证据Z]）
 */
export function distillEpisodesToLessons(): { lessons: string[]; episodeCount: number } {
  const episodes = getRecentEpisodes(20);
  if (episodes.length === 0) {
    return { lessons: [], episodeCount: 0 };
  }

  const lessons: string[] = [];

  // 按方向分组
  const byDirection: Record<string, EpisodeRecord[]> = { long: [], short: [], neutral: [] };
  for (const ep of episodes) {
    if (byDirection[ep.direction]) {
      byDirection[ep.direction].push(ep);
    }
  }

  // 为每个方向生成 Lesson
  for (const [direction, eps] of Object.entries(byDirection)) {
    if (eps.length < 2) continue; // 至少2个同类 Episode 才蒸馏

    const avgConfidence = Math.round(eps.reduce((sum, e) => sum + e.confidence, 0) / eps.length);
    const symbols = [...new Set(eps.map(e => e.symbol))];
    const commonIntents = [...new Set(eps.map(e => e.intent))];

    // 生成 Lesson
    const condition = `${symbols.join('/')} 方向偏${direction === 'long' ? '多' : direction === 'short' ? '空' : '中性'}，置信度约${avgConfidence}%`;
    const action = direction === 'neutral' ? '保持观望，等待趋势确认' : `考虑${direction === 'long' ? '轻仓做多' : '轻仓做空'}`;
    const evidence = `基于${eps.length}个历史 Episode 的模式归纳，平均置信度${avgConfidence}%，涉及意图：${commonIntents.join(', ')}`;

    lessons.push(`在 [${condition}] 下，应该 [${action}]，因为 [${evidence}]`);
  }

  // 写入 Lesson 文件
  if (lessons.length > 0) {
    try {
      if (!existsSync(DISTILLED_LESSONS_DIR)) {
        mkdirSync(DISTILLED_LESSONS_DIR, { recursive: true });
      }
      const lessonFile = join(DISTILLED_LESSONS_DIR, `lesson_distilled_${Date.now()}.md`);
      const content = `# 蒸馏 Lesson\n\n生成时间: ${new Date().toISOString()}\n基于 Episode 数量: ${episodes.length}\n\n## Lessons\n\n${lessons.map((l, i) => `${i + 1}. ${l}`).join('\n\n')}\n`;
      writeFileSync(lessonFile, content, 'utf-8');
    } catch {
      // 写入失败不影响主流程
    }
  }

  return { lessons, episodeCount: episodes.length };
}

/**
 * 获取已蒸馏的 Lesson 列表
 */
export function getDistilledLessons(): string[] {
  try {
    if (!existsSync(DISTILLED_LESSONS_DIR)) return [];
    const files = readdirSync(DISTILLED_LESSONS_DIR)
      .filter(f => f.endsWith('.md'))
      .sort()
      .reverse()
      .slice(0, 5);
    const lessons: string[] = [];
    for (const file of files) {
      try {
        const content = readFileSync(join(DISTILLED_LESSONS_DIR, file), 'utf-8');
        // 提取 Lesson 行
        const lines = content.split('\n').filter(l => l.match(/^\d+\./));
        lessons.push(...lines.slice(0, 3));
      } catch {
        // 忽略读取错误
      }
    }
    return lessons;
  } catch {
    return [];
  }
}

/**
 * 检查是否应该触发 T5 元反思
 * 当 Episode 数量达到阈值时返回 true
 */
export function shouldTriggerMetaReflection(): boolean {
  return countEpisodes() >= EPISODE_TRIGGER_THRESHOLD;
}
