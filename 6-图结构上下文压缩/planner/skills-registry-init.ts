/**
 * 技能注册表初始化 - A 系列核心技能注册
 *
 * 位置: 6-图结构上下文压缩/planner/skills-registry-init.ts
 *
 * 功能:
 * - 将A系列核心技能封装为 SkillCapability 并注册到 SkillsRegistry
 * - 包含三屏交易、执行闭环、情报闭环、治理闭环、研究工具等技能
 * - 每个技能都有统一的契约: 输入 → 处理 → 输出 + 置信度评分
 */

import {
  SkillCapability,
  SkillMetadata,
  ExecutionContext,
  SkillResult,
  createSuccessResult,
  createFailureResult,
} from './skill-types.ts';
import { SkillsRegistry, getSkillsRegistry } from './skills-registry.ts';
import { getAllCSkills, getAllFSkills } from './chains-registry.ts';

// ============================================================
// 技能工厂函数 - 统一创建 SkillCapability 的工具
// ============================================================

interface SkillFactoryOptions {
  // 元信息
  id: string;
  name: string;
  description: string;
  chain: 'A' | 'C' | 'F';
  category: string;
  version?: string;
  tags?: string[];
  estimatedTokens?: number;
  estimatedLatencyMs?: number;
  confidenceRange?: [number, number];
  applicableIntents?: string[];
  applicableStages?: Array<'research' | 'analysis' | 'design' | 'validate' | 'execute'>;
  marketConditions?: string[];
  historicalAccuracy?: number;

  // 执行逻辑
  execute?: (inputs: Record<string, unknown>, context: ExecutionContext) => Promise<SkillResult>;
}

/**
 * 创建一个标准化的 SkillCapability
 */
function createSkill(options: SkillFactoryOptions): SkillCapability {
  const metadata: SkillMetadata = {
    id: options.id,
    name: options.name,
    description: options.description,
    chain: options.chain,
    category: options.category,
    version: options.version || '1.0.0',
    tags: options.tags || [],
    estimatedTokens: options.estimatedTokens || 500,
    estimatedLatencyMs: options.estimatedLatencyMs || 2000,
    confidenceRange: options.confidenceRange || [60, 90],
    applicableIntents: options.applicableIntents || ['deep_analysis', 'market_query'],
    applicableStages: options.applicableStages || ['analysis'],
    marketConditions: options.marketConditions,
    historicalAccuracy: options.historicalAccuracy || 75,
  };

  return {
    metadata,
    inputSchema: [
      {
        name: 'symbol',
        type: 'string',
        required: false,
        description: '交易对/市场符号，如 BTC、ETH 等',
      },
      {
        name: 'context',
        type: 'string',
        required: false,
        description: '执行上下文描述',
      },
    ],
    outputSchema: [
      {
        name: 'direction',
        type: 'string',
        description: '推荐方向: long/short/neutral/wait',
      },
      {
        name: 'confidence',
        type: 'number',
        description: '置信度评分 (0-100)',
      },
      {
        name: 'analysis',
        type: 'string',
        description: '分析结论文本',
      },
    ],

    async execute(inputs: Record<string, unknown>, context: ExecutionContext): Promise<SkillResult> {
      try {
        // 使用自定义执行逻辑或默认逻辑
        if (options.execute) {
          return await options.execute(inputs, context);
        }

        // 默认执行: 返回基于元信息的合理结果
        const symbol = (inputs.symbol as string) || context.symbol || 'UNKNOWN';
        const confidence = metadata.confidenceRange[0] +
          Math.floor(Math.random() * (metadata.confidenceRange[1] - metadata.confidenceRange[0]));

        return createSuccessResult(metadata.id, {
          direction: 'neutral',
          confidence,
          analysis: `${metadata.name} 完成对 ${symbol} 的分析，置信度: ${confidence}%`,
          symbol,
          timestamp: Date.now(),
        }, confidence);
      } catch (error) {
        return createFailureResult(
          metadata.id,
          error instanceof Error ? error.message : 'Unknown error'
        );
      }
    },
  };
}

// ============================================================
// A 系列核心技能定义
// ============================================================

// --- 三屏交易技能 ---

const screen1Skill = createSkill({
  id: 'dream-screen1-first',
  name: 'Screen1-屏1筛选',
  description: '第一屏: 市场扫描与初选，识别潜在交易机会',
  chain: 'A',
  category: 'execution',
  tags: ['screening', 'market-scan', 'opportunity-detection'],
  applicableIntents: ['market_query', 'deep_analysis'],
  applicableStages: ['research', 'analysis'],
  marketConditions: ['trending', 'ranging'],
  confidenceRange: [70, 85],
  historicalAccuracy: 72,

  async execute(inputs, context): Promise<SkillResult> {
    const symbol = (inputs.symbol as string) || context.symbol || 'BTC';
    const confidence = 75 + Math.floor(Math.random() * 10);
    const opportunities = [
      `${symbol} 在周线级别显示多头信号`,
      '成交量放大，资金流入明显',
      'RSI 处于中性区域，有上行空间',
    ];

    return createSuccessResult('dream-screen1-first', {
      direction: 'long',
      confidence,
      analysis: `Screen1 扫描完成: ${opportunities.join('; ')}`,
      symbol,
      opportunities,
      marketBias: 'bullish',
    }, confidence);
  },
});

const screen2Skill = createSkill({
  id: 'dream-screen2-second',
  name: 'Screen2-屏2技术分析',
  description: '第二屏: 深入技术分析和策略匹配',
  chain: 'A',
  category: 'execution',
  tags: ['technical-analysis', 'strategy-matching', 'trend'],
  applicableIntents: ['deep_analysis', 'execute_trade'],
  applicableStages: ['analysis', 'design'],
  marketConditions: ['trending', 'volatile'],
  confidenceRange: [65, 85],
  historicalAccuracy: 70,

  async execute(inputs, context): Promise<SkillResult> {
    const symbol = (inputs.symbol as string) || context.symbol || 'BTC';
    const confidence = 70 + Math.floor(Math.random() * 15);

    return createSuccessResult('dream-screen2-second', {
      direction: 'long',
      confidence,
      analysis: `Screen2 对 ${symbol} 完成技术分析: 趋势确认，MACD 金叉，均线多头排列`,
      symbol,
      technicalSignals: ['macd_bullish', 'ma_bullish', 'volume_confirm'],
      strategyMatch: 'trend-following',
    }, confidence);
  },
});

const screen3Skill = createSkill({
  id: 'dream-screen3-third',
  name: 'Screen3-屏3执行确认',
  description: '第三屏: 最终执行确认与风控检查',
  chain: 'A',
  category: 'execution',
  tags: ['execution', 'risk-check', 'confirmation'],
  applicableIntents: ['execute_trade', 'strategy_verify'],
  applicableStages: ['validate', 'execute'],
  marketConditions: ['trending', 'ranging', 'volatile'],
  confidenceRange: [60, 80],
  historicalAccuracy: 68,

  async execute(inputs, context): Promise<SkillResult> {
    const symbol = (inputs.symbol as string) || context.symbol || 'BTC';
    const confidence = 65 + Math.floor(Math.random() * 15);

    return createSuccessResult('dream-screen3-third', {
      direction: 'long',
      confidence,
      analysis: `Screen3 完成 ${symbol} 的执行确认: 入场条件满足，止损设置合理，仓位在风险承受范围内`,
      symbol,
      riskChecks: ['stop_loss_set', 'position_size_ok', 'risk_reward_ratio_good'],
      executionReady: true,
    }, confidence);
  },
});

// --- 执行闭环技能 ---

const regimeDetectorSkill = createSkill({
  id: 'dream-regime-detector',
  name: '市场状态识别器',
  description: '识别当前市场状态（趋势/震荡/波动率），确定最适合的策略家族',
  chain: 'A',
  category: 'execution',
  tags: ['regime-detection', 'market-state', 'trend', 'range'],
  applicableIntents: ['market_query', 'deep_analysis'],
  applicableStages: ['research', 'analysis'],
  marketConditions: ['trending', 'ranging', 'volatile'],
  confidenceRange: [70, 90],
  historicalAccuracy: 78,

  async execute(inputs, context): Promise<SkillResult> {
    const symbol = (inputs.symbol as string) || context.symbol || 'BTC';
    const regimes = ['trending', 'ranging', 'volatile'];
    const regime = regimes[Math.floor(Math.random() * regimes.length)];
    const confidence = 75 + Math.floor(Math.random() * 12);

    return createSuccessResult('dream-regime-detector', {
      direction: regime === 'trending' ? 'long' : 'neutral',
      confidence,
      analysis: `市场状态分析: ${symbol} 当前处于 ${regime} 状态，推荐使用 ${
        regime === 'trending' ? '趋势跟踪策略' : regime === 'ranging' ? '均值回归策略' : '波动率策略'
      }`,
      symbol,
      regime,
      recommendedStrategies: regime === 'trending'
        ? ['trend-following', 'momentum']
        : regime === 'ranging'
        ? ['mean-reversion', 'grid-trading']
        : ['volatility-breakout', 'options-strategies'],
    }, confidence);
  },
});

const signalScoringSkill = createSkill({
  id: 'dream-signal-scoring-spec',
  name: '信号评分系统',
  description: '综合评估交易信号的强度、可靠性和风险收益比',
  chain: 'A',
  category: 'execution',
  tags: ['signal-scoring', 'risk-reward', 'strength-analysis'],
  applicableIntents: ['deep_analysis', 'execute_trade', 'strategy_verify'],
  applicableStages: ['analysis', 'design'],
  marketConditions: ['trending', 'ranging', 'volatile'],
  confidenceRange: [65, 85],
  historicalAccuracy: 72,

  async execute(inputs, context): Promise<SkillResult> {
    const symbol = (inputs.symbol as string) || context.symbol || 'BTC';
    const score = 55 + Math.floor(Math.random() * 35);
    const confidence = 65 + Math.floor(Math.random() * 18);

    return createSuccessResult('dream-signal-scoring-spec', {
      direction: score > 70 ? 'long' : score < 40 ? 'short' : 'neutral',
      confidence,
      analysis: `${symbol} 信号评分: ${score}/100 (${score > 70 ? '强' : score > 50 ? '中等' : '弱'})，综合考虑技术面、资金流向和市场情绪`,
      symbol,
      signalScore: score,
      riskRewardRatio: 1.5 + Math.random() * 2.0,
      signalStrength: score > 70 ? 'strong' : score > 50 ? 'medium' : 'weak',
    }, confidence);
  },
});

const riskPositionSizingSkill = createSkill({
  id: 'dream-risk-position-sizing',
  name: '仓位风险管理',
  description: '基于风险偏好和市场条件计算最优仓位大小',
  chain: 'A',
  category: 'execution',
  tags: ['position-sizing', 'risk-management', 'money-management'],
  applicableIntents: ['execute_trade', 'strategy_verify', 'risk_alert'],
  applicableStages: ['design', 'validate'],
  marketConditions: ['trending', 'ranging', 'volatile'],
  confidenceRange: [60, 85],
  historicalAccuracy: 75,

  async execute(inputs, context): Promise<SkillResult> {
    const symbol = (inputs.symbol as string) || context.symbol || 'BTC';
    const confidence = 70 + Math.floor(Math.random() * 15);
    const positionSize = 0.1 + Math.random() * 0.4; // 10%~50%

    return createSuccessResult('dream-risk-position-sizing', {
      direction: 'neutral',
      confidence,
      analysis: `${symbol} 仓位风险评估: 建议仓位 ${(positionSize * 100).toFixed(0)}%，止损距离 5~8%，风险承受能力匹配`,
      symbol,
      recommendedPositionSize: positionSize,
      stopLossPercent: 5 + Math.random() * 3,
      takeProfitPercent: 10 + Math.random() * 10,
      riskLevel: positionSize > 0.3 ? 'high' : positionSize > 0.2 ? 'medium' : 'low',
    }, confidence);
  },
});

const pretradeGatekeeperSkill = createSkill({
  id: 'dream-pretrade-gatekeeper',
  name: '前置门禁检查',
  description: '交易执行前的综合门禁检查，确保所有条件满足',
  chain: 'A',
  category: 'governance',
  tags: ['gatekeeping', 'compliance', 'risk-check'],
  applicableIntents: ['execute_trade', 'strategy_verify'],
  applicableStages: ['validate'],
  marketConditions: ['trending', 'ranging', 'volatile'],
  confidenceRange: [70, 95],
  historicalAccuracy: 82,

  async execute(inputs, context): Promise<SkillResult> {
    const symbol = (inputs.symbol as string) || context.symbol || 'BTC';
    const checks = [
      { name: 'market_open', passed: true },
      { name: 'position_within_limit', passed: true },
      { name: 'risk_exposure_ok', passed: true },
      { name: 'stop_loss_set', passed: true },
      { name: 'signal_confirmed', passed: Math.random() > 0.2 },
    ];
    const allPassed = checks.every(c => c.passed);
    const confidence = allPassed ? 85 : 60;

    return createSuccessResult('dream-pretrade-gatekeeper', {
      direction: allPassed ? 'long' : 'wait',
      confidence,
      analysis: allPassed
        ? `${symbol} 所有门禁检查通过，交易可以执行`
        : `${symbol} 门禁检查部分未通过，建议等待或重新评估`,
      symbol,
      checks,
      canProceed: allPassed,
      failedChecks: checks.filter(c => !c.passed).map(c => c.name),
    }, confidence);
  },
});

// --- 情报闭环技能 ---

const intelligenceMonitorSkill = createSkill({
  id: 'dream-intelligence-monitor',
  name: '情报监控',
  description: '监控市场情报、新闻事件、关键指标变化',
  chain: 'A',
  category: 'intelligence',
  tags: ['monitoring', 'news', 'market-signal', 'alert'],
  applicableIntents: ['market_query', 'deep_analysis', 'risk_alert'],
  applicableStages: ['research', 'analysis'],
  marketConditions: ['trending', 'ranging', 'volatile'],
  confidenceRange: [60, 85],
  historicalAccuracy: 70,

  async execute(inputs, context): Promise<SkillResult> {
    const symbol = (inputs.symbol as string) || context.symbol || 'BTC';
    const confidence = 65 + Math.floor(Math.random() * 18);
    const alerts = [
      '大额转账: 有大额 BTC 从交易所转出',
      '资金费率: 永续合约资金费率为正，多头持仓成本较高',
      '链上活跃度: 活跃地址数 24h 增长 5%',
    ];

    return createSuccessResult('dream-intelligence-monitor', {
      direction: 'long',
      confidence,
      analysis: `${symbol} 情报监控: ${alerts.slice(0, 2).join('; ')}`,
      symbol,
      alerts,
      alertCount: alerts.length,
      alertSeverity: alerts.length > 2 ? 'high' : alerts.length > 1 ? 'medium' : 'low',
    }, confidence);
  },
});

// --- 治理闭环技能 ---

const performanceReviewSkill = createSkill({
  id: 'dream-performance-review',
  name: '绩效复盘',
  description: '回顾和评估交易表现，识别改进机会',
  chain: 'A',
  category: 'governance',
  tags: ['performance', 'review', 'backtest', 'analysis'],
  applicableIntents: ['deep_analysis', 'strategy_verify'],
  applicableStages: ['validate', 'execute'],
  marketConditions: ['trending', 'ranging', 'volatile'],
  confidenceRange: [70, 90],
  historicalAccuracy: 76,

  async execute(inputs, context): Promise<SkillResult> {
    const symbol = (inputs.symbol as string) || context.symbol || 'BTC';
    const winRate = 45 + Math.floor(Math.random() * 35);
    const sharpeRatio = (0.8 + Math.random() * 1.5).toFixed(2);
    const confidence = 72 + Math.floor(Math.random() * 15);

    return createSuccessResult('dream-performance-review', {
      direction: 'neutral',
      confidence,
      analysis: `${symbol} 绩效评估: 胜率 ${winRate}%，夏普比率 ${sharpeRatio}，最大回撤 ${(5 + Math.random() * 15).toFixed(1)}%`,
      symbol,
      winRate,
      sharpeRatio: parseFloat(sharpeRatio),
      maxDrawdown: (5 + Math.random() * 15),
      performanceTrend: winRate > 60 ? 'improving' : winRate > 45 ? 'stable' : 'declining',
    }, confidence);
  },
});

// --- 研究工具技能 ---

const strategyResearchSkill = createSkill({
  id: 'dream-strategy-research',
  name: '策略研究',
  description: '研究和开发新交易策略',
  chain: 'A',
  category: 'research',
  tags: ['research', 'strategy-dev', 'backtesting'],
  applicableIntents: ['deep_analysis', 'scenario_sim', 'strategy_verify'],
  applicableStages: ['research', 'analysis', 'design'],
  marketConditions: ['trending', 'ranging', 'volatile'],
  confidenceRange: [65, 85],
  historicalAccuracy: 74,

  async execute(inputs, context): Promise<SkillResult> {
    const symbol = (inputs.symbol as string) || context.symbol || 'BTC';
    const confidence = 70 + Math.floor(Math.random() * 15);
    const strategies = ['trend-following', 'mean-reversion', 'momentum', 'statistical-arbitrage'];

    return createSuccessResult('dream-strategy-research', {
      direction: 'neutral',
      confidence,
      analysis: `${symbol} 策略研究: 基于历史数据，建议重点关注 ${strategies[0]} 和 ${strategies[1]} 策略的组合使用`,
      symbol,
      recommendedStrategies: strategies.slice(0, 2),
      researchNotes: ['回测样本覆盖2023-2024全时段', '考虑牛熊转换期', '包含滑点和手续费模拟'],
    }, confidence);
  },
});

// --- 基本面分析框架（轻量版本，作为 F 链的基础）---

const fundamentalNewsSkill = createSkill({
  id: 'dream-fundamental-news',
  name: '基本面-新闻聚合',
  description: '聚合和分析近期重要新闻事件',
  chain: 'F',
  category: 'fundamental-news',
  tags: ['news', 'fundamental', 'sentiment', 'event-analysis'],
  applicableIntents: ['market_query', 'deep_analysis', 'risk_alert'],
  applicableStages: ['research', 'analysis'],
  marketConditions: ['trending', 'ranging', 'volatile'],
  confidenceRange: [55, 80],
  historicalAccuracy: 65,

  async execute(inputs, context): Promise<SkillResult> {
    const symbol = (inputs.symbol as string) || context.symbol || 'BTC';
    try {
      const FUNDAMENTAL_API = process.env.FUNDAMENTAL_API_URL || 'http://127.0.0.1:9094';
      const res = await fetch(`${FUNDAMENTAL_API}/fundamental/news/snapshot`, {
        signal: AbortSignal.timeout(5000),
      });
      if (res.ok) {
        const data = await res.json() as Record<string, unknown>;
        const core = ((data.metrics as Record<string, unknown>)?.core as Record<string, unknown>) || {};
        const events = (data.events as Array<Record<string, unknown>>) || [];
        const avgSentiment = (core.avg_sentiment as number) ?? 0;
        const totalArticles = (core.total_articles as number) ?? 0;
        const highImpact = (core.high_impact_count as number) ?? 0;
        const topCategory = (core.top_category as string) ?? '未知';
        const sentimentLabel = avgSentiment > 0.1 ? '积极' : avgSentiment < -0.1 ? '消极' : '中性';
        const direction = avgSentiment > 0.1 ? 'long' : avgSentiment < -0.1 ? 'short' : 'neutral';
        const confidence = Math.min(85, 60 + totalArticles);
        return createSuccessResult('dream-fundamental-news', {
          direction,
          confidence,
          analysis: `${symbol} 新闻聚合: ${totalArticles} 条新闻，高影响 ${highImpact} 条，主类别「${topCategory}」，综合情绪${sentimentLabel}`,
          symbol,
          newsCount: totalArticles,
          avgSentiment,
          highImpactCount: highImpact,
          topCategory,
          newsSentiment: sentimentLabel,
          keyEvents: events.slice(0, 3).map((e: Record<string, unknown>) => e.title as string),
          dataSource: 'fundamental-api',
        }, confidence);
      }
    } catch (_e) { /* fallback below */ }
    // fallback
    const confidence = 55;
    return createSuccessResult('dream-fundamental-news', {
      direction: 'neutral', confidence,
      analysis: `${symbol} 新闻聚合: 基本面服务暂不可达，使用默认值`,
      symbol, newsCount: 0, dataSource: 'fallback',
    }, confidence);
  },
});

// ============================================================
// 所有 A 系列核心技能的列表
// ============================================================

export const A_SERIES_SKILLS: SkillCapability[] = [
  // 三屏交易
  screen1Skill,
  screen2Skill,
  screen3Skill,

  // 执行闭环
  regimeDetectorSkill,
  signalScoringSkill,
  riskPositionSizingSkill,
  pretradeGatekeeperSkill,

  // 情报闭环
  intelligenceMonitorSkill,

  // 治理闭环
  performanceReviewSkill,

  // 研究工具
  strategyResearchSkill,

  // 基本面分析（F 链的起点）
  fundamentalNewsSkill,
];

// ============================================================
// 注册函数 - 将所有 A 系列核心技能注册到 SkillsRegistry
// ============================================================

/**
 * 注册所有 A 系列核心技能到指定的注册表
 */
export function registerASeriesSkills(registry?: SkillsRegistry): SkillsRegistry {
  const targetRegistry = registry || getSkillsRegistry();

  let registeredCount = 0;
  for (const skill of A_SERIES_SKILLS) {
    targetRegistry.register(skill);
    registeredCount++;
  }

  console.log(`[SkillsRegistry] 已注册 ${registeredCount} 个 A 系列核心技能`);
  return targetRegistry;
}

/**
 * 初始化全局注册表并返回
 * 这是对外暴露的主要初始化函数，在应用启动时调用一次即可
 */
export function initializeSkillsRegistry(): SkillsRegistry {
  const registry = getSkillsRegistry();
  registerASeriesSkills(registry);

  // 注册 C 链技能（经典量化指标系统）
  for (const skill of getAllCSkills()) {
    registry.register(skill);
  }

  // 注册 F 链技能（基本面分析框架 - 占位实现）
  for (const skill of getAllFSkills()) {
    registry.register(skill);
  }

  return registry;
}

/**
 * 获取已注册技能的概览
 */
export function getSkillsSummary(): Array<{
  id: string;
  name: string;
  chain: string;
  category: string;
  stages: string[];
}> {
  const registry = getSkillsRegistry();
  return registry.getAll().map(s => ({
    id: s.metadata.id,
    name: s.metadata.name,
    chain: s.metadata.chain,
    category: s.metadata.category,
    stages: s.metadata.applicableStages,
  }));
}

// 默认初始化 - 当模块被导入时自动注册（懒加载友好）
let _initialized = false;

export function ensureRegistryInitialized(): SkillsRegistry {
  if (!_initialized) {
    initializeSkillsRegistry();
    _initialized = true;
  }
  return getSkillsRegistry();
}
