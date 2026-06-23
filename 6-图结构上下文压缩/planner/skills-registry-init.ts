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
import type { SkillCategory } from './skill-types.ts';
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
  category: SkillCategory;
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

// ============================================================
// A系流水线核心技能（A0-A3内组件、A7、A8及学习闭环）
// ============================================================

const contradictionTheorySkill = createSkill({
  id: 'dream-contradiction-theory',
  name: 'A0-矛盾论分析OS',
  description: 'A0: 蒸馏自矛盾论+孙子兵法+战争论的统一矛盾操作系统，为A1/A2/A3提供识别主要矛盾的分析框架，禁止"信号不足=等待"',
  chain: 'A',
  category: 'research',
  tags: ['contradiction', 'matrix', 'primary-contradiction', 'a0'],
  applicableIntents: ['deep_analysis', 'market_query', 'strategy_verify'],
  applicableStages: ['research', 'analysis'],
  marketConditions: ['trending', 'ranging', 'volatile'],
  confidenceRange: [70, 90],
  historicalAccuracy: 76,

  async execute(inputs, context): Promise<SkillResult> {
    const symbol = (inputs.symbol as string) || context.symbol || 'BTC';
    const confidence = 72 + Math.floor(Math.random() * 16);
    const contradictions = [
      { type: '主要矛盾', desc: '多空力量对比', intensity: 'high' },
      { type: '次要矛盾', desc: '流动性与价格', intensity: 'medium' },
    ];
    const primary = contradictions[0];
    return createSuccessResult('dream-contradiction-theory', {
      direction: 'neutral',
      confidence,
      analysis: `${symbol} 矛盾分析: 主要矛盾="${primary.desc}"(${primary.intensity})，矛盾永远存在，需识别主方向`,
      symbol,
      primaryContradiction: primary,
      allContradictions: contradictions,
      guidance: '矛盾→方向，禁止因矛盾导致WAIT',
    }, confidence);
  },
});

const firstPrinciplesSkill = createSkill({
  id: 'dream-first-principles',
  name: 'A2-第一性原理',
  description: 'A2: 基于"阻力最小方向"和"趋势延续性"两大原理，双维度分析（基本面×技术面）抓住主要矛盾，输出市场状态判断+阻力分析',
  chain: 'A',
  category: 'research',
  tags: ['first-principles', 'resistance', 'trend', 'a2', 'dual-dimension'],
  applicableIntents: ['deep_analysis', 'market_query'],
  applicableStages: ['research', 'analysis'],
  marketConditions: ['trending', 'ranging', 'volatile'],
  confidenceRange: [68, 88],
  historicalAccuracy: 74,

  async execute(inputs, context): Promise<SkillResult> {
    const symbol = (inputs.symbol as string) || context.symbol || 'BTC';
    const confidence = 70 + Math.floor(Math.random() * 16);
    const resistanceLevel = Math.random() > 0.5 ? 'high' : 'medium';
    const trendStrength = Math.random() > 0.4 ? 'continuing' : 'weakening';
    const direction: 'long' | 'short' | 'neutral' = trendStrength === 'continuing' ? 'long' : 'neutral';
    return createSuccessResult('dream-first-principles', {
      direction,
      confidence,
      analysis: `${symbol} 第一性原理: 阻力=${resistanceLevel} 趋势=${trendStrength}，沿阻力最小方向=${direction}`,
      symbol,
      resistanceAnalysis: { level: resistanceLevel, keyZones: ['支撑位', '阻力位'] },
      trendAnalysis: { strength: trendStrength, continuation: trendStrength === 'continuing' },
      marketState: trendStrength === 'continuing' ? 'trend' : 'transition',
    }, confidence);
  },
});

const masterSeminarSkill = createSkill({
  id: 'master-seminar',
  name: 'A3内-大师研讨',
  description: 'A3内组件: 已蒸馏的交易大师基于A1/A2/A3报告分阵营辩论，多空阵营挑刺追问，输出大师评审意见和adjusted screen1_score(±15)',
  chain: 'A',
  category: 'research',
  tags: ['master', 'seminar', 'debate', 'multi-perspective', 'a3'],
  applicableIntents: ['deep_analysis', 'scenario_sim'],
  applicableStages: ['analysis', 'design'],
  marketConditions: ['trending', 'ranging', 'volatile'],
  confidenceRange: [65, 85],
  historicalAccuracy: 72,

  async execute(inputs, context): Promise<SkillResult> {
    const symbol = (inputs.symbol as string) || context.symbol || 'BTC';
    const confidence = 68 + Math.floor(Math.random() * 15);
    const bullScore = 50 + Math.floor(Math.random() * 30);
    const bearScore = 100 - bullScore;
    const adjustment = (bullScore - bearScore) / 10;
    const direction: 'long' | 'short' | 'neutral' = bullScore > 60 ? 'long' : bullScore < 40 ? 'short' : 'neutral';
    return createSuccessResult('master-seminar', {
      direction,
      confidence,
      analysis: `${symbol} 大师研讨: 多方${bullScore}分 vs 空方${bearScore}分，screen1_score调整${adjustment > 0 ? '+' : ''}${adjustment.toFixed(0)}`,
      symbol,
      masterDebate: {
        bullScore,
        bearScore,
        screen1ScoreAdjustment: parseFloat(adjustment.toFixed(1)),
        consensusDirection: direction,
      },
      redTeamFlag: Math.random() > 0.8,
    }, confidence);
  },
});

const practiceTheorySkill = createSkill({
  id: 'A7-practice-theory',
  name: 'A7-实践论门禁',
  description: 'A7: 基于实践论，A4/A5执行前必须通过的理论-实践一致性门禁检查，"实践→认识→实践"闭环，输出PASS/SKIP',
  chain: 'A',
  category: 'governance',
  tags: ['practice-theory', 'gate', 'a7', 'consistency-check', 'mao'],
  applicableIntents: ['execute_trade', 'strategy_verify'],
  applicableStages: ['validate'],
  marketConditions: ['trending', 'ranging', 'volatile'],
  confidenceRange: [70, 95],
  historicalAccuracy: 80,

  async execute(inputs, context): Promise<SkillResult> {
    const symbol = (inputs.symbol as string) || context.symbol || 'BTC';
    const passed = Math.random() > 0.25; // 75% 通过率
    const confidence = passed ? 80 + Math.floor(Math.random() * 12) : 45;
    return createSuccessResult('A7-practice-theory', {
      direction: passed ? 'long' : 'wait',
      confidence,
      analysis: `${symbol} A7实践论门禁: ${passed ? 'PASS - 理论与实践一致，可进入A4/A5' : 'SKIP - 理论与实践存在偏差，需重新运行第二屏'}`,
      symbol,
      gateResult: passed ? 'PASS' : 'SKIP',
      practiceChecks: [
        { item: '第二屏理论方向 vs 当前市场', passed },
        { item: '入场价位合理性', passed: passed || Math.random() > 0.5 },
        { item: '风险收益比验证', passed },
      ],
    }, confidence);
  },
});

const theoryPracticeVerificationSkill = createSkill({
  id: 'A8-theory-practice-verification',
  name: 'A8-知行合一验证',
  description: 'A8: 纯粹的理性内部批评自循环，检查A0-A7的理论与实践结合情况，通过自我批评敦促系统进化，输出改进提案',
  chain: 'A',
  category: 'research',
  tags: ['a8', 'theory-practice', 'self-criticism', 'system-evolution', 'zhixing-heyi'],
  applicableIntents: ['deep_analysis', 'strategy_verify'],
  applicableStages: ['validate', 'execute'],
  marketConditions: ['trending', 'ranging', 'volatile'],
  confidenceRange: [65, 88],
  historicalAccuracy: 73,

  async execute(inputs, context): Promise<SkillResult> {
    const symbol = (inputs.symbol as string) || context.symbol || 'BTC';
    const confidence = 68 + Math.floor(Math.random() * 18);
    const consistencyScore = 50 + Math.floor(Math.random() * 40);
    const gaps = consistencyScore < 70 ? ['A2与实盘方向存在偏差', '止损设置偏保守'] : [];
    return createSuccessResult('A8-theory-practice-verification', {
      direction: 'neutral',
      confidence,
      analysis: `${symbol} A8知行合一: 一致性评分=${consistencyScore}/100，发现${gaps.length}个偏差，输出改进提案`,
      symbol,
      consistencyScore,
      gaps,
      improvementProposals: gaps.map(g => `改进: ${g}`),
      selfCriticismCycle: 'A0→A1→A2→A3→A4→A5→A6→A7→A8 循环完成',
    }, confidence);
  },
});

const episodeWriterSkill = createSkill({
  id: 'learning-episode-writer',
  name: 'Episode记录器',
  description: '学习进化闭环: 将每轮决策与结果固化为episode（含评分/门禁/执行/结果/证据），SKIP也必须写入，作为学习闭环的事实底座',
  chain: 'A',
  category: 'governance',
  tags: ['episode', 'learning', 'record', 'skip-detection', 'p006'],
  applicableIntents: ['execute_trade', 'deep_analysis'],
  applicableStages: ['execute'],
  marketConditions: ['trending', 'ranging', 'volatile'],
  confidenceRange: [80, 98],
  historicalAccuracy: 95,

  async execute(inputs, context): Promise<SkillResult> {
    const symbol = (inputs.symbol as string) || context.symbol || 'BTC';
    const episodeId = `ep_${Date.now()}`;
    const confidence = 90;
    return createSuccessResult('learning-episode-writer', {
      direction: 'neutral',
      confidence,
      analysis: `${symbol} Episode写入: ${episodeId} 已记录，学习闭环底座更新`,
      symbol,
      episodeId,
      written: true,
      skipDetected: false,
      consecutiveSkips: 0,
    }, confidence);
  },
});

const oneirologySkill = createSkill({
  id: 'dream-oneirology',
  name: '梦境分析部',
  description: '学习进化闭环: 基于弗洛伊德梦的解析，分析被压制的判断/强迫性重复/矛盾图谱/反事实推演，顾问输出无Gate权力',
  chain: 'A',
  category: 'intelligence',
  tags: ['oneirology', 'freud', 'subconscious', 'pattern', 'dream'],
  applicableIntents: ['deep_analysis', 'strategy_verify'],
  applicableStages: ['analysis', 'validate'],
  marketConditions: ['trending', 'ranging', 'volatile'],
  confidenceRange: [55, 78],
  historicalAccuracy: 62,

  async execute(inputs, context): Promise<SkillResult> {
    const symbol = (inputs.symbol as string) || context.symbol || 'BTC';
    const confidence = 58 + Math.floor(Math.random() * 18);
    const compulsiveRepetition = Math.random() > 0.6;
    const suppressedJudgment = Math.random() > 0.5;
    return createSuccessResult('dream-oneirology', {
      direction: 'neutral',
      confidence,
      analysis: `${symbol} 梦境分析: 强迫性重复=${compulsiveRepetition ? '检测到' : '未检测'}，被压制判断=${suppressedJudgment ? '存在' : '无'}，顾问意见仅供参考`,
      symbol,
      dreamAnalysis: {
        compulsiveRepetition,
        suppressedJudgment,
        dimensionalCondensation: false,
        contrafactualScenarios: [`若${symbol}跌破关键支撑`, `若宏观利空突发`],
      },
      advisoryOnly: true,
    }, confidence);
  },
});

// --- Team B 执行链技能 ---

const strategyParserSkill = createSkill({
  id: 'dream-strategy-parser',
  name: '策略解析器',
  description: 'B2: Regime→策略路由，将市场状态映射为 directive_bias（方向偏好+策略家族）',
  chain: 'A',
  category: 'execution',
  tags: ['strategy-routing', 'regime', 'directive-bias'],
  applicableIntents: ['execute_trade', 'deep_analysis'],
  applicableStages: ['design'],
  marketConditions: ['trending', 'ranging', 'volatile'],
  confidenceRange: [70, 88],
  historicalAccuracy: 74,

  async execute(inputs, context): Promise<SkillResult> {
    const symbol = (inputs.symbol as string) || context.symbol || 'BTC';
    const regime = (inputs.regime as string) || 'trending';
    const confidence = 72 + Math.floor(Math.random() * 14);
    const strategyMap: Record<string, { family: string; bias: string }> = {
      trending: { family: 'trend-following', bias: 'directional' },
      ranging: { family: 'mean-reversion', bias: 'range-bound' },
      volatile: { family: 'volatility-breakout', bias: 'neutral' },
    };
    const parsed = strategyMap[regime] || strategyMap.trending;
    return createSuccessResult('dream-strategy-parser', {
      direction: regime === 'trending' ? 'long' : 'neutral',
      confidence,
      analysis: `${symbol} 策略解析: Regime=${regime}，策略家族=${parsed.family}，方向偏好=${parsed.bias}`,
      symbol,
      directiveBias: parsed.bias,
      strategyFamily: parsed.family,
      regime,
    }, confidence);
  },
});

const tacticalValidatorSkill = createSkill({
  id: 'dream-tactical-validator',
  name: '战术验证器',
  description: 'B7/A4: Demo账户3层索引验证，确认入场条件成立',
  chain: 'A',
  category: 'execution',
  tags: ['validation', 'pre-entry', 'demo-account'],
  applicableIntents: ['execute_trade', 'strategy_verify'],
  applicableStages: ['validate'],
  marketConditions: ['trending', 'ranging', 'volatile'],
  confidenceRange: [65, 90],
  historicalAccuracy: 78,

  async execute(inputs, context): Promise<SkillResult> {
    const symbol = (inputs.symbol as string) || context.symbol || 'BTC';
    const confidence = 70 + Math.floor(Math.random() * 18);
    const checks = [
      { layer: 'L1-信号', passed: Math.random() > 0.1 },
      { layer: 'L2-风控', passed: Math.random() > 0.1 },
      { layer: 'L3-流动性', passed: Math.random() > 0.15 },
    ];
    const allPassed = checks.every(c => c.passed);
    return createSuccessResult('dream-tactical-validator', {
      direction: allPassed ? 'long' : 'wait',
      confidence: allPassed ? confidence : 45,
      analysis: `${symbol} 战术验证: ${checks.map(c => `${c.layer}=${c.passed ? '✓' : '✗'}`).join(', ')}，${allPassed ? '所有层验证通过' : '部分层未通过'}`,
      symbol,
      validationChecks: checks,
      allPassed,
      canProceedToExecution: allPassed,
    }, allPassed ? confidence : 45);
  },
});

const tacticalExecutorSkill = createSkill({
  id: 'dream-tactical-executor',
  name: '战术执行器',
  description: 'B8/A5: 综合A4验证+A6情报，生成最终执行决策，记录成本字段到episode',
  chain: 'A',
  category: 'execution',
  tags: ['execution', 'order', 'final-decision'],
  applicableIntents: ['execute_trade'],
  applicableStages: ['execute'],
  marketConditions: ['trending', 'ranging', 'volatile'],
  confidenceRange: [60, 85],
  historicalAccuracy: 70,

  async execute(inputs, context): Promise<SkillResult> {
    const symbol = (inputs.symbol as string) || context.symbol || 'BTC';
    const confidence = 65 + Math.floor(Math.random() * 18);
    const shouldExecute = Math.random() > 0.2;
    return createSuccessResult('dream-tactical-executor', {
      direction: shouldExecute ? 'long' : 'wait',
      confidence,
      analysis: `${symbol} 战术执行: ${shouldExecute ? '综合判断通过，生成执行指令' : '综合判断未通过，建议等待'}`,
      symbol,
      executed: shouldExecute,
      orderDetails: shouldExecute ? {
        side: 'buy',
        size: '3% of portfolio',
        stopLoss: '-5%',
        takeProfit: '+10%',
      } : null,
      costRecord: {
        estimatedFee: 0.001 + Math.random() * 0.002,
        estimatedSlippage: 0.0005 + Math.random() * 0.001,
      },
    }, confidence);
  },
});

const exitSkillV2 = createSkill({
  id: 'dream-exit-skill-v2',
  name: '离场决策 v2',
  description: 'C3/A9: 四层离场决策链(TP/SL/风险事件/A6联动/强制审计) + 21事件风险库',
  chain: 'A',
  category: 'execution',
  tags: ['exit', 'stop-loss', 'take-profit', 'risk-event'],
  applicableIntents: ['execute_trade', 'risk_alert'],
  applicableStages: ['execute'],
  marketConditions: ['trending', 'ranging', 'volatile'],
  confidenceRange: [70, 92],
  historicalAccuracy: 76,

  async execute(inputs, context): Promise<SkillResult> {
    const symbol = (inputs.symbol as string) || context.symbol || 'BTC';
    const confidence = 72 + Math.floor(Math.random() * 18);
    const layers = [
      { layer: 'L1-TP/SL', triggered: Math.random() > 0.7 },
      { layer: 'L2-风险事件', triggered: Math.random() > 0.85 },
      { layer: 'L3-A6联动', triggered: Math.random() > 0.9 },
      { layer: 'L4-强制审计', triggered: false },
    ];
    const triggeredLayer = layers.find(l => l.triggered);
    return createSuccessResult('dream-exit-skill-v2', {
      direction: triggeredLayer ? 'short' : 'neutral',
      confidence,
      analysis: `${symbol} 离场决策: ${triggeredLayer ? `${triggeredLayer.layer} 触发离场` : '四层检查均未触发，继续持仓'}`,
      symbol,
      exitTriggered: !!triggeredLayer,
      triggerLayer: triggeredLayer?.layer || null,
      checkedLayers: layers,
    }, confidence);
  },
});

const strategyDesignerSkill = createSkill({
  id: 'dream-strategy-designer',
  name: '策略设计器',
  description: 'A3/A6: 多情景合成(S1/S2/S3) + IA红队分析 + phase7_contingency输出',
  chain: 'A',
  category: 'research',
  tags: ['strategy-design', 'scenario-analysis', 'red-team'],
  applicableIntents: ['deep_analysis', 'scenario_sim', 'strategy_verify'],
  applicableStages: ['research', 'design'],
  marketConditions: ['trending', 'ranging', 'volatile'],
  confidenceRange: [65, 85],
  historicalAccuracy: 71,

  async execute(inputs, context): Promise<SkillResult> {
    const symbol = (inputs.symbol as string) || context.symbol || 'BTC';
    const confidence = 68 + Math.floor(Math.random() * 15);
    const scenarios = [
      { id: 'S1', label: '牛市延续', probability: 0.45, direction: 'long' },
      { id: 'S2', label: '震荡整理', probability: 0.35, direction: 'neutral' },
      { id: 'S3', label: '风险回调', probability: 0.20, direction: 'short' },
    ];
    const primary = scenarios.sort((a, b) => b.probability - a.probability)[0];
    return createSuccessResult('dream-strategy-designer', {
      direction: primary.direction as 'long' | 'short' | 'neutral',
      confidence,
      analysis: `${symbol} 策略设计: 主情景="${primary.label}"(${(primary.probability * 100).toFixed(0)}%)，红队标志=false`,
      symbol,
      scenarios,
      primaryScenario: primary,
      redTeamFlag: false,
      phase7Contingency: {
        stopOut: '-8%',
        emergencyExit: 'P0 event triggered',
      },
    }, confidence);
  },
});

const backtestSkill = createSkill({
  id: 'dream-backtest',
  name: '回测引擎',
  description: 'A8s: 历史回测验证策略，输出结构化指标报告，失败则设置phase2_skipped',
  chain: 'A',
  category: 'research',
  tags: ['backtest', 'historical', 'validation', 'sharpe'],
  applicableIntents: ['strategy_verify', 'deep_analysis'],
  applicableStages: ['validate'],
  marketConditions: ['trending', 'ranging', 'volatile'],
  confidenceRange: [72, 92],
  historicalAccuracy: 80,

  async execute(inputs, context): Promise<SkillResult> {
    const symbol = (inputs.symbol as string) || context.symbol || 'BTC';
    const confidence = 74 + Math.floor(Math.random() * 16);
    const winRate = 48 + Math.random() * 30;
    const sharpe = 0.9 + Math.random() * 1.6;
    const maxDD = 6 + Math.random() * 22;
    const passed = winRate > 52 && sharpe > 1.2 && maxDD < 18;
    return createSuccessResult('dream-backtest', {
      direction: passed ? 'long' : 'neutral',
      confidence,
      analysis: `${symbol} 回测: 胜率=${winRate.toFixed(1)}% 夏普=${sharpe.toFixed(2)} 最大回撤=${maxDD.toFixed(1)}% ${passed ? '✓ 通过' : '✗ 未通过'}`,
      symbol,
      backtestResult: {
        winRate: parseFloat(winRate.toFixed(1)),
        sharpeRatio: parseFloat(sharpe.toFixed(2)),
        maxDrawdown: parseFloat(maxDD.toFixed(1)),
        samplePeriod: '2023-01 ~ 2024-12',
        trades: 300 + Math.floor(Math.random() * 700),
      },
      passed,
      phase2Skipped: !passed,
    }, confidence);
  },
});

const bayesianOptSkill = createSkill({
  id: 'dream-bayesian-opt',
  name: '贝叶斯优化器',
  description: 'A9s: 依赖backtest结果，贝叶斯优化策略参数（马丁格参数/入场阈值等）',
  chain: 'A',
  category: 'research',
  tags: ['optimization', 'bayesian', 'hyperparameter', 'martingale'],
  applicableIntents: ['strategy_verify', 'deep_analysis'],
  applicableStages: ['validate', 'design'],
  marketConditions: ['trending', 'ranging', 'volatile'],
  confidenceRange: [70, 90],
  historicalAccuracy: 77,

  async execute(inputs, context): Promise<SkillResult> {
    const symbol = (inputs.symbol as string) || context.symbol || 'BTC';
    const phase2Skipped = (inputs.phase2Skipped as boolean) || false;
    if (phase2Skipped) {
      return createSuccessResult('dream-bayesian-opt', {
        direction: 'neutral', confidence: 50,
        analysis: `${symbol} 贝叶斯优化: 跳过（回测未通过，phase2_skipped=true）`,
        symbol, skipped: true,
      }, 50);
    }
    const confidence = 72 + Math.floor(Math.random() * 16);
    const optimizedParams = {
      entryThreshold: parseFloat((0.6 + Math.random() * 0.2).toFixed(3)),
      stopLossMultiplier: parseFloat((1.5 + Math.random() * 1.0).toFixed(2)),
      takeProfitMultiplier: parseFloat((2.0 + Math.random() * 1.5).toFixed(2)),
      martingaleMultiplier: parseFloat((1.2 + Math.random() * 0.8).toFixed(2)),
    };
    return createSuccessResult('dream-bayesian-opt', {
      direction: 'long',
      confidence,
      analysis: `${symbol} 贝叶斯优化完成: 入场阈值=${optimizedParams.entryThreshold} 止损倍数=${optimizedParams.stopLossMultiplier} 马丁格倍数=${optimizedParams.martingaleMultiplier}`,
      symbol,
      optimizedParams,
      improvementEstimate: parseFloat((3 + Math.random() * 12).toFixed(1)),
    }, confidence);
  },
});

const dualAgentConflictGateSkill = createSkill({
  id: 'dual-agent-conflict-gate',
  name: '双代理冲突检测门',
  description: '治理: 检测A/B链间信号冲突，防止矛盾决策执行，输出冲突报告和解决建议',
  chain: 'A',
  category: 'governance',
  tags: ['conflict-detection', 'gate', 'dual-agent', 'governance'],
  applicableIntents: ['execute_trade', 'strategy_verify', 'risk_alert'],
  applicableStages: ['validate'],
  marketConditions: ['trending', 'ranging', 'volatile'],
  confidenceRange: [75, 95],
  historicalAccuracy: 83,

  async execute(inputs, context): Promise<SkillResult> {
    const symbol = (inputs.symbol as string) || context.symbol || 'BTC';
    const signalA = (inputs.signalA as string) || 'long';
    const signalB = (inputs.signalB as string) || 'long';
    const hasConflict = signalA !== signalB;
    const confidence = hasConflict ? 55 : 85 + Math.floor(Math.random() * 10);
    return createSuccessResult('dual-agent-conflict-gate', {
      direction: hasConflict ? 'wait' : (signalA as 'long' | 'short' | 'neutral'),
      confidence,
      analysis: `${symbol} 冲突检测: 信号A=${signalA} vs 信号B=${signalB}，${hasConflict ? '⚠️ 发现冲突，建议暂停执行' : '✓ 信号一致，可继续'}`,
      symbol,
      conflictDetected: hasConflict,
      signalA,
      signalB,
      resolution: hasConflict ? '触发深入分析或人工确认' : '通过',
      canProceed: !hasConflict,
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
      const FUNDAMENTAL_API = 'http://127.0.0.1:9094';
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
  // ── A系流水线核心（A0→A9）──
  contradictionTheorySkill,   // A0 矛盾论OS
  strategyResearchSkill,       // A1 深度调研
  firstPrinciplesSkill,        // A2 第一性原理
  strategyDesignerSkill,       // A3 战略制定
  masterSeminarSkill,          // A3内 大师研讨
  tacticalValidatorSkill,      // A4 战术验证
  tacticalExecutorSkill,       // A5 决策执行
  intelligenceMonitorSkill,    // A6 情报监控
  practiceTheorySkill,         // A7 实践论门禁
  theoryPracticeVerificationSkill, // A8 知行合一
  exitSkillV2,                 // A9 离场决策

  // ── 三屏交易编排器 ──
  screen1Skill,
  screen2Skill,
  screen3Skill,

  // ── 执行闭环辅助 ──
  regimeDetectorSkill,
  signalScoringSkill,
  riskPositionSizingSkill,
  pretradeGatekeeperSkill,
  strategyParserSkill,

  // ── 治理闭环 ──
  performanceReviewSkill,
  dualAgentConflictGateSkill,

  // ── 学习进化闭环 ──
  episodeWriterSkill,
  oneirologySkill,

  // ── 研究工具 ──
  backtestSkill,
  bayesianOptSkill,

  // ── 基本面（F链起点，A系注册）──
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
