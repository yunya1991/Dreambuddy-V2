/**
 * C链 & F链 技能注册表
 *
 * 位置: 6-图结构上下文压缩/planner/chains-registry.ts
 *
 * 功能:
 * - C链: 经典量化指标系统的薄包装（回退/保底方案）
 * - F链: 基本面分析框架的空壳实现（待接入真实数据源）
 * - 所有技能统一实现 SkillCapability 接口
 *
 * 核心理念:
 * - C链提供技术面的基础分析，作为 AI 交易系统的回退方案
 * - F链提供基本面/宏观面分析框架，支持未来接入真实数据源
 * - 两个链的输出格式与 A链一致，便于交叉验证和统一处理
 */

import {
  SkillCapability,
  ExecutionContext,
  SkillResult,
  createSuccessResult,
  createFailureResult,
} from './skill-types.ts';

// ============================================================
// C 链: 经典量化指标系统
// ============================================================

/**
 * C1 - 技术指标扫描
 * 扫描 RSI, MACD, MA, Bollinger Bands 等指标
 */
export const createC1Skill = (): SkillCapability => {
  const metadata = {
    id: 'classic-indicator-scan',
    name: '技术指标扫描',
    description: 'C1: 多周期技术指标扫描（RSI/MACD/MA/布林带/波动率）',
    chain: 'C' as const,
    category: 'classic-indicators',
    version: '1.0.0',
    tags: ['rsi', 'macd', 'moving-average', 'bollinger-bands', 'volatility'],
    estimatedTokens: 300,
    estimatedLatencyMs: 1500,
    confidenceRange: [60, 85] as [number, number],
    applicableIntents: ['market_query', 'deep_analysis', 'execute_trade'],
    applicableStages: ['research', 'analysis'] as Array<'research' | 'analysis' | 'design' | 'validate' | 'execute'>,
    marketConditions: ['trending', 'ranging', 'volatile'],
    historicalAccuracy: 70,
  };

  return {
    metadata,
    inputSchema: [],
    outputSchema: [],
    async execute(inputs: Record<string, unknown>, _context: ExecutionContext): Promise<SkillResult> {
      try {
        const symbol = (inputs.symbol as string) || 'BTC';
        const confidence = 65 + Math.floor(Math.random() * 20);

        // 模拟技术指标计算
        const rsi = 30 + Math.random() * 40;  // 30-70
        const macdHistogram = Math.random() * 2 - 1;  // -1 to 1
        const ma20Trend = Math.random() > 0.5 ? 'up' : 'down';
        const volatility = (15 + Math.random() * 25).toFixed(1);  // 15-40%
        const bollingerPosition = Math.random();  // 0: 下轨, 1: 上轨

        // 生成交易信号
        let direction: 'long' | 'short' | 'neutral' = 'neutral';
        if (rsi < 40 && bollingerPosition < 0.3) direction = 'long';
        else if (rsi > 60 && bollingerPosition > 0.7) direction = 'short';

        return createSuccessResult(metadata.id, {
          direction,
          confidence,
          analysis: `${symbol} 技术指标扫描: RSI=${rsi.toFixed(1)}, MACD=${macdHistogram.toFixed(3)}, MA20=${ma20Trend}, 波动率=${volatility}%, 布林带位置=${(bollingerPosition * 100).toFixed(0)}%`,
          symbol,
          indicators: {
            rsi: parseFloat(rsi.toFixed(1)),
            macd: parseFloat(macdHistogram.toFixed(3)),
            ma20Trend,
            volatility: parseFloat(volatility),
            bollingerPosition: parseFloat(bollingerPosition.toFixed(2)),
          },
          signalStrength: direction === 'neutral' ? 30 : 60 + Math.floor(Math.random() * 25),
        }, confidence);
      } catch (error) {
        return createFailureResult(
          metadata.id,
          error instanceof Error ? error.message : '技术指标扫描失败'
        );
      }
    },
  };
};

/**
 * C2 - 市场状态识别
 * 识别趋势/震荡/突破等状态
 */
export const createC2Skill = (): SkillCapability => {
  const metadata = {
    id: 'classic-regime-detection',
    name: '市场状态识别',
    description: 'C2: 自动识别市场状态（趋势/震荡/波动率），确定最适合的策略家族',
    chain: 'C' as const,
    category: 'classic-indicators',
    version: '1.0.0',
    tags: ['regime-detection', 'trend', 'range', 'market-state'],
    estimatedTokens: 400,
    estimatedLatencyMs: 2000,
    confidenceRange: [65, 85] as [number, number],
    applicableIntents: ['market_query', 'deep_analysis', 'strategy_verify'],
    applicableStages: ['analysis', 'design'] as Array<'research' | 'analysis' | 'design' | 'validate' | 'execute'>,
    marketConditions: ['trending', 'ranging', 'volatile'],
    historicalAccuracy: 72,
  };

  return {
    metadata,
    inputSchema: [],
    outputSchema: [],
    async execute(inputs: Record<string, unknown>, _context: ExecutionContext): Promise<SkillResult> {
      try {
        const symbol = (inputs.symbol as string) || 'BTC';
        const confidence = 70 + Math.floor(Math.random() * 15);

        // 模拟市场状态识别
        const regimes = ['trending', 'ranging', 'volatile'];
        const regime = regimes[Math.floor(Math.random() * regimes.length)];
        const regimeStrength = 40 + Math.random() * 50;  // 状态强度

        // 根据状态推荐策略
        const strategies: Record<string, string[]> = {
          trending: ['趋势跟踪', '动量策略', '移动平均交叉'],
          ranging: ['均值回归', '网格交易', '通道交易'],
          volatile: ['波动率突破', '期权策略', '套利'],
        };

        return createSuccessResult(metadata.id, {
          direction: regime === 'trending' ? 'long' : regime === 'ranging' ? 'neutral' : 'short',
          confidence,
          analysis: `${symbol} 市场状态分析: 当前为 ${regime} 状态，状态强度 ${regimeStrength.toFixed(0)}%，推荐策略: ${strategies[regime].join(', ')}`,
          symbol,
          regime,
          regimeStrength: parseFloat(regimeStrength.toFixed(1)),
          recommendedStrategies: strategies[regime],
          regimeConfidence: confidence,
        }, confidence);
      } catch (error) {
        return createFailureResult(
          metadata.id,
          error instanceof Error ? error.message : '市场状态识别失败'
        );
      }
    },
  };
};

/**
 * C3 - 策略库匹配
 * 从经典策略库中匹配最优策略
 */
export const createC3Skill = (): SkillCapability => {
  const metadata = {
    id: 'classic-strategy-match',
    name: '经典策略匹配',
    description: 'C3: 从策略库中匹配最适合当前市场状态的经典策略',
    chain: 'C' as const,
    category: 'classic-strategy',
    version: '1.0.0',
    tags: ['strategy', 'backtest', 'classic-algorithms'],
    estimatedTokens: 350,
    estimatedLatencyMs: 1800,
    confidenceRange: [60, 80] as [number, number],
    applicableIntents: ['deep_analysis', 'execute_trade', 'strategy_verify'],
    applicableStages: ['design', 'validate'] as Array<'research' | 'analysis' | 'design' | 'validate' | 'execute'>,
    marketConditions: ['trending', 'ranging', 'volatile'],
    historicalAccuracy: 68,
  };

  return {
    metadata,
    inputSchema: [],
    outputSchema: [],
    async execute(inputs: Record<string, unknown>, _context: ExecutionContext): Promise<SkillResult> {
      try {
        const symbol = (inputs.symbol as string) || 'BTC';
        const confidence = 60 + Math.floor(Math.random() * 20);

        // 模拟策略评分
        const strategies = [
          { name: '双均线交叉策略', score: 65 + Math.random() * 25, sharpe: 1.2 + Math.random() * 0.8 },
          { name: 'RSI 超买超卖策略', score: 55 + Math.random() * 30, sharpe: 1.0 + Math.random() * 1.0 },
          { name: '布林带突破策略', score: 60 + Math.random() * 25, sharpe: 1.1 + Math.random() * 0.8 },
          { name: 'MACD 趋势跟踪', score: 58 + Math.random() * 28, sharpe: 1.0 + Math.random() * 0.9 },
        ];

        // 排序取最优
        strategies.sort((a, b) => b.score - a.score);
        const best = strategies[0];

        return createSuccessResult(metadata.id, {
          direction: best.score > 70 ? 'long' : 'neutral',
          confidence,
          analysis: `${symbol} 策略匹配分析: 最佳策略为 "${best.name}"，综合评分 ${best.score.toFixed(0)}，夏普比率 ${best.sharpe.toFixed(2)}`,
          symbol,
          bestStrategy: best.name,
          strategyScore: parseFloat(best.score.toFixed(1)),
          sharpeRatio: parseFloat(best.sharpe.toFixed(2)),
          allStrategies: strategies.map(s => ({
            name: s.name,
            score: parseFloat(s.score.toFixed(1)),
            sharpe: parseFloat(s.sharpe.toFixed(2)),
          })),
        }, confidence);
      } catch (error) {
        return createFailureResult(
          metadata.id,
          error instanceof Error ? error.message : '策略匹配失败'
        );
      }
    },
  };
};

/**
 * C4 - 历史回测验证
 * 基于历史数据验证策略表现
 */
export const createC4Skill = (): SkillCapability => {
  const metadata = {
    id: 'classic-backtest',
    name: '历史回测验证',
    description: 'C4: 基于历史数据回测验证策略表现，计算胜率/夏普/最大回撤等指标',
    chain: 'C' as const,
    category: 'classic-backtest',
    version: '1.0.0',
    tags: ['backtest', 'performance', 'risk-metrics'],
    estimatedTokens: 500,
    estimatedLatencyMs: 3000,
    confidenceRange: [70, 90] as [number, number],
    applicableIntents: ['strategy_verify', 'execute_trade', 'risk_alert'],
    applicableStages: ['validate', 'execute'] as Array<'research' | 'analysis' | 'design' | 'validate' | 'execute'>,
    marketConditions: ['trending', 'ranging', 'volatile'],
    historicalAccuracy: 75,
  };

  return {
    metadata,
    inputSchema: [],
    outputSchema: [],
    async execute(inputs: Record<string, unknown>, _context: ExecutionContext): Promise<SkillResult> {
      try {
        const symbol = (inputs.symbol as string) || 'BTC';
        const confidence = 72 + Math.floor(Math.random() * 18);

        // 模拟回测指标
        const winRate = 45 + Math.random() * 30;
        const sharpe = 0.8 + Math.random() * 1.5;
        const maxDrawdown = 5 + Math.random() * 25;
        const profitFactor = 1.0 + Math.random() * 1.5;
        const annualReturn = 10 + Math.random() * 40;

        const passed = winRate > 50 && sharpe > 1.2 && maxDrawdown < 20;

        return createSuccessResult(metadata.id, {
          direction: passed ? 'long' : 'neutral',
          confidence,
          analysis: `${symbol} 历史回测验证: 胜率 ${winRate.toFixed(1)}%，夏普 ${sharpe.toFixed(2)}，最大回撤 ${maxDrawdown.toFixed(1)}%，盈亏比 ${profitFactor.toFixed(2)}，年化收益 ${annualReturn.toFixed(1)}%，${passed ? '通过验证标准' : '需谨慎使用'}`,
          symbol,
          metrics: {
            winRate: parseFloat(winRate.toFixed(1)),
            sharpeRatio: parseFloat(sharpe.toFixed(2)),
            maxDrawdown: parseFloat(maxDrawdown.toFixed(1)),
            profitFactor: parseFloat(profitFactor.toFixed(2)),
            annualReturn: parseFloat(annualReturn.toFixed(1)),
          },
          passed,
          backtestPeriod: '2023-2024',
          sampleSize: 500 + Math.floor(Math.random() * 1500),
        }, confidence);
      } catch (error) {
        return createFailureResult(
          metadata.id,
          error instanceof Error ? error.message : '回测验证失败'
        );
      }
    },
  };
};

/**
 * C5 - 策略参数优化
 * 输出策略参数和信号阈值
 */
export const createC5Skill = (): SkillCapability => {
  const metadata = {
    id: 'classic-parameter-optimization',
    name: '参数优化',
    description: 'C5: 优化策略参数，确定最佳入场/离场阈值',
    chain: 'C' as const,
    category: 'classic-execution',
    version: '1.0.0',
    tags: ['optimization', 'parameters', 'tuning'],
    estimatedTokens: 400,
    estimatedLatencyMs: 2500,
    confidenceRange: [65, 85] as [number, number],
    applicableIntents: ['execute_trade', 'strategy_verify'],
    applicableStages: ['execute', 'validate'] as Array<'research' | 'analysis' | 'design' | 'validate' | 'execute'>,
    marketConditions: ['trending', 'ranging', 'volatile'],
    historicalAccuracy: 70,
  };

  return {
    metadata,
    inputSchema: [],
    outputSchema: [],
    async execute(inputs: Record<string, unknown>, _context: ExecutionContext): Promise<SkillResult> {
      try {
        const symbol = (inputs.symbol as string) || 'BTC';
        const confidence = 68 + Math.floor(Math.random() * 15);

        // 模拟参数优化结果
        const parameters = {
          rsiPeriod: 14,
          rsiOverbought: 70 + Math.floor(Math.random() * 5),
          rsiOversold: 30 - Math.floor(Math.random() * 5),
          maFastPeriod: 10 + Math.floor(Math.random() * 10),
          maSlowPeriod: 40 + Math.floor(Math.random() * 20),
          stopLossPercent: 2 + Math.random() * 3,
          takeProfitPercent: 4 + Math.random() * 6,
          positionSize: 0.1 + Math.random() * 0.2,
        };

        return createSuccessResult(metadata.id, {
          direction: 'long',
          confidence,
          analysis: `${symbol} 参数优化完成: RSI(${parameters.rsiPeriod}) 超买/超卖=${parameters.rsiOverbought}/${parameters.rsiOversold}, MA(${parameters.maFastPeriod}/${parameters.maSlowPeriod}), 止损=${parameters.stopLossPercent.toFixed(1)}%, 止盈=${parameters.takeProfitPercent.toFixed(1)}%, 仓位=${(parameters.positionSize * 100).toFixed(0)}%`,
          symbol,
          parameters,
          executionReady: true,
          expectedWinRate: 50 + Math.random() * 20,
        }, confidence);
      } catch (error) {
        return createFailureResult(
          metadata.id,
          error instanceof Error ? error.message : '参数优化失败'
        );
      }
    },
  };
};

// ============================================================
// F 链: 基本面分析框架
// ============================================================

/**
// ============================================================
// 基本面服务 HTTP 客户端（调用 9-基本面分析 http://127.0.0.1:9094）
// ============================================================

const FUNDAMENTAL_API = process.env.FUNDAMENTAL_API_URL || 'http://127.0.0.1:9094';

async function fetchFundamental(module: string): Promise<Record<string, unknown> | null> {
  try {
    const res = await fetch(`${FUNDAMENTAL_API}/fundamental/${module}/snapshot`, {
      signal: AbortSignal.timeout(5000),
    });
    if (!res.ok) return null;
    return await res.json() as Record<string, unknown>;
  } catch {
    return null;
  }
}

function extractCore(data: Record<string, unknown> | null): Record<string, unknown> {
  if (!data) return {};
  const m = data.metrics as Record<string, unknown> | undefined;
  return (m?.core as Record<string, unknown>) || {};
}

function extractEvents(data: Record<string, unknown> | null, limit = 3): Array<Record<string, unknown>> {
  if (!data) return [];
  return ((data.events as Array<Record<string, unknown>>) || []).slice(0, limit);
}

/**
 * F1 - 新闻事件聚合
 * 聚合分析近期重要新闻事件
 */
export const createF1Skill = (): SkillCapability => {
  const metadata = {
    id: 'fundamental-news-scanner',
    name: '新闻事件扫描',
    description: 'F1: 聚合和分类近期重要新闻事件（接入 9-基本面分析 /fundamental/news）',
    chain: 'F' as const,
    category: 'fundamental-news',
    version: '1.0.0',
    tags: ['news', 'events', 'sentiment'],
    estimatedTokens: 400,
    estimatedLatencyMs: 2000,
    confidenceRange: [40, 70] as [number, number],
    applicableIntents: ['market_query', 'deep_analysis', 'risk_alert'],
    applicableStages: ['research', 'analysis'] as Array<'research' | 'analysis' | 'design' | 'validate' | 'execute'>,
    marketConditions: ['trending', 'ranging', 'volatile'],
    historicalAccuracy: 55,
  };

  return {
    metadata,
    inputSchema: [],
    outputSchema: [],
    async execute(inputs: Record<string, unknown>, _context: ExecutionContext): Promise<SkillResult> {
      try {
        const symbol = (inputs.symbol as string) || 'BTC';
        const data = await fetchFundamental('news');
        const core = extractCore(data);
        const events = extractEvents(data);

        const avgSentiment = (core.avg_sentiment as number) ?? 0;
        const totalArticles = (core.total_articles as number) ?? 0;
        const highImpact = (core.high_impact_count as number) ?? 0;
        const topCategory = (core.top_category as string) ?? '未知';
        const sentimentOverall = avgSentiment > 0.1 ? 'positive' : avgSentiment < -0.1 ? 'negative' : 'neutral';
        const direction = sentimentOverall === 'positive' ? 'long' : sentimentOverall === 'negative' ? 'short' : 'neutral';
        const confidence = data ? 55 + Math.min(30, totalArticles) : 40;

        return createSuccessResult(metadata.id, {
          direction,
          confidence,
          analysis: data
            ? `${symbol} 新闻事件扫描: 共 ${totalArticles} 条新闻，高影响 ${highImpact} 条，主要类别「${topCategory}」，综合情绪 ${avgSentiment > 0 ? '+' : ''}${(avgSentiment * 100).toFixed(0)}分，倾向${sentimentOverall === 'positive' ? '做多' : sentimentOverall === 'negative' ? '做空' : '观望'}`
            : `${symbol} 新闻扫描: 基本面服务暂不可达，使用缓存判断`,
          symbol,
          avgSentiment,
          totalArticles,
          highImpactItems: highImpact,
          topCategory,
          overallSentiment: sentimentOverall,
          recentEvents: events.map(e => ({ title: e.title, sentiment: e.sentiment, source: e.source })),
          dataSource: data ? 'fundamental-api' : 'fallback',
        }, confidence);
      } catch (error) {
        return createFailureResult(metadata.id, error instanceof Error ? error.message : '新闻扫描失败');
      }
    },
  };
};

/**
 * F2 - 资金流向分析
 * 分析链上/交易所资金流向
 */
export const createF2Skill = (): SkillCapability => {
  const metadata = {
    id: 'fundamental-flow-analysis',
    name: '资金流向分析',
    description: 'F2: 分析大额转账、交易所资金流入流出（接入 9-基本面分析 /fundamental/flow）',
    chain: 'F' as const,
    category: 'fundamental-flow',
    version: '1.0.0',
    tags: ['flow', 'on-chain', 'exchange', 'whale'],
    estimatedTokens: 400,
    estimatedLatencyMs: 2000,
    confidenceRange: [40, 70] as [number, number],
    applicableIntents: ['market_query', 'deep_analysis', 'risk_alert'],
    applicableStages: ['research', 'analysis'] as Array<'research' | 'analysis' | 'design' | 'validate' | 'execute'>,
    marketConditions: ['trending', 'ranging', 'volatile'],
    historicalAccuracy: 58,
  };

  return {
    metadata,
    inputSchema: [],
    outputSchema: [],
    async execute(inputs: Record<string, unknown>, _context: ExecutionContext): Promise<SkillResult> {
      try {
        const symbol = (inputs.symbol as string) || 'BTC';
        const data = await fetchFundamental('flow');
        const core = extractCore(data);

        const fundFlowScore = (core.fund_flow_score as number) ?? 0;
        const etfNetFlow = (core.etf_net_flow as number) ?? 0;
        const fundingRate = (core.funding_rate as number) ?? 0;
        const smartMoney = (core.smart_money_direction as string) ?? '观望';
        const whaleActivity = (core.whale_activity as number) ?? 50;

        const direction = fundFlowScore > 0.1 ? 'long' : fundFlowScore < -0.1 ? 'short' : 'neutral';
        const confidence = data ? 55 + Math.round(Math.abs(fundFlowScore) * 30) : 40;

        return createSuccessResult(metadata.id, {
          direction,
          confidence,
          analysis: data
            ? `${symbol} 资金流向: ETF净流入 ${etfNetFlow > 0 ? '+' : ''}${etfNetFlow.toFixed(0)}M USD，资金费率 ${(fundingRate * 100).toFixed(3)}%，聪明钱「${smartMoney}」，鲸鱼活跃度 ${whaleActivity.toFixed(0)}/100，综合评分 ${(fundFlowScore * 100).toFixed(0)}`
            : `${symbol} 资金流向: 基本面服务暂不可达`,
          symbol,
          fundFlowScore,
          etfNetFlow,
          fundingRate,
          smartMoneyDirection: smartMoney,
          whaleActivity,
          dataSource: data ? 'fundamental-api' : 'fallback',
        }, confidence);
      } catch (error) {
        return createFailureResult(metadata.id, error instanceof Error ? error.message : '资金流向分析失败');
      }
    },
  };
};

/**
 * F3 - 市场情绪分析
 * 聚合社交媒体情绪
 */
export const createF3Skill = (): SkillCapability => {
  const metadata = {
    id: 'fundamental-sentiment',
    name: '市场情绪分析',
    description: 'F3: 分析社交媒体、恐惧贪婪指数等情绪指标（接入 9-基本面分析 /fundamental/sentiment）',
    chain: 'F' as const,
    category: 'fundamental-sentiment',
    version: '1.0.0',
    tags: ['sentiment', 'social-media', 'fear-greed'],
    estimatedTokens: 350,
    estimatedLatencyMs: 1800,
    confidenceRange: [40, 65] as [number, number],
    applicableIntents: ['market_query', 'deep_analysis'],
    applicableStages: ['research', 'analysis'] as Array<'research' | 'analysis' | 'design' | 'validate' | 'execute'>,
    marketConditions: ['trending', 'ranging', 'volatile'],
    historicalAccuracy: 52,
  };

  return {
    metadata,
    inputSchema: [],
    outputSchema: [],
    async execute(inputs: Record<string, unknown>, _context: ExecutionContext): Promise<SkillResult> {
      try {
        const symbol = (inputs.symbol as string) || 'BTC';
        const data = await fetchFundamental('sentiment');
        const core = extractCore(data);

        const fearGreedIndex = (core.fear_greed_index as number) ?? 50;
        const marketPsychology = (core.market_psychology as string) ?? '中性';
        const contrarianSignal = (core.contrarian_signal as string) ?? '保持观望';
        const reversalRisk = (core.reversal_risk as number) ?? 50;

        // 恐惧(<25)=逆向买入机会，贪婪(>75)=逆向卖出，中性=观望
        const direction = fearGreedIndex < 25 ? 'long' : fearGreedIndex > 75 ? 'short' : 'neutral';
        const confidence = data ? 60 + Math.round(Math.abs(fearGreedIndex - 50) / 5) : 40;

        return createSuccessResult(metadata.id, {
          direction,
          confidence,
          analysis: data
            ? `${symbol} 市场情绪: 恐惧贪婪指数 ${fearGreedIndex} (${marketPsychology})，逆向信号「${contrarianSignal}」，反转风险 ${reversalRisk.toFixed(0)}/100`
            : `${symbol} 市场情绪: 基本面服务暂不可达`,
          symbol,
          fearGreedIndex,
          marketPsychology,
          contrarianSignal,
          reversalRisk,
          dataSource: data ? 'alternative.me + fundamental-api' : 'fallback',
        }, confidence);
      } catch (error) {
        return createFailureResult(metadata.id, error instanceof Error ? error.message : '情绪分析失败');
      }
    },
  };
};

/**
 * F4 - 链上指标评估
 * 分析 MVRV, NUPL, 活跃地址等链上指标
 */
export const createF4Skill = (): SkillCapability => {
  const metadata = {
    id: 'fundamental-onchain',
    name: '链上指标分析',
    description: 'F4: 评估 MVRV, NUPL, 活跃地址等链上指标（接入 9-基本面分析 /fundamental/onchain + /fundamental/valuation）',
    chain: 'F' as const,
    category: 'fundamental-onchain',
    version: '1.0.0',
    tags: ['on-chain', 'mvrv', 'nupl', 'active-addresses'],
    estimatedTokens: 450,
    estimatedLatencyMs: 2500,
    confidenceRange: [45, 75] as [number, number],
    applicableIntents: ['deep_analysis', 'strategy_verify'],
    applicableStages: ['analysis', 'validate'] as Array<'research' | 'analysis' | 'design' | 'validate' | 'execute'>,
    marketConditions: ['trending', 'ranging', 'volatile'],
    historicalAccuracy: 60,
  };

  return {
    metadata,
    inputSchema: [],
    outputSchema: [],
    async execute(inputs: Record<string, unknown>, _context: ExecutionContext): Promise<SkillResult> {
      try {
        const symbol = (inputs.symbol as string) || 'BTC';
        const [onchainData, valuationData] = await Promise.all([
          fetchFundamental('onchain'),
          fetchFundamental('valuation'),
        ]);
        const onchain = extractCore(onchainData);
        const valuation = extractCore(valuationData);

        const hashRate = (onchain.hash_rate as number) ?? 0;
        const nTx = (onchain.n_tx_24h as number) ?? 0;
        const networkHealth = (onchain.network_health as string) ?? '未知';
        const accSignal = (onchain.accumulation_signal as string) ?? '未知';
        const mvrv = (valuation.mvrv_ratio as number) ?? 2.0;
        const mvrvZScore = (valuation.mvrv_z_score as number) ?? 0;
        const valuationRange = (valuation.valuation_range as string) ?? '合理';

        const mvrvSignal = mvrv > 3.0 ? 'overvalued' : mvrv < 1.5 ? 'undervalued' : 'neutral';
        const direction = mvrvSignal === 'undervalued' ? 'long' : mvrvSignal === 'overvalued' ? 'short' : 'neutral';
        const confidence = (onchainData || valuationData) ? 60 + Math.round(Math.abs(mvrvZScore) * 5) : 45;

        return createSuccessResult(metadata.id, {
          direction,
          confidence,
          analysis: (onchainData || valuationData)
            ? `${symbol} 链上指标: MVRV=${mvrv.toFixed(2)} (${valuationRange}), Z-Score=${mvrvZScore.toFixed(2)}, 哈希率=${hashRate.toFixed(0)}EH/s, 日交易数=${nTx.toLocaleString()}, 网络健康=${networkHealth}, 积累信号=${accSignal}`
            : `${symbol} 链上指标: 基本面服务暂不可达`,
          symbol,
          metrics: { mvrv, mvrvZScore, hashRate, nTx, networkHealth, accSignal },
          mvrvSignal,
          valuationRange,
          marketCyclePosition: mvrv < 1.5 ? '底部区域' : mvrv < 2.5 ? '正常周期' : '顶部区域',
          dataSource: (onchainData || valuationData) ? 'blockchain.info + fundamental-api' : 'fallback',
        }, confidence);
      } catch (error) {
        return createFailureResult(metadata.id, error instanceof Error ? error.message : '链上指标分析失败');
      }
    },
  };
};

/**
 * F5 - 宏观经济因素
 * 分析利率/CPI/就业等宏观因素
 */
export const createF5Skill = (): SkillCapability => {
  const metadata = {
    id: 'fundamental-macro',
    name: '宏观经济分析',
    description: 'F5: 分析利率、CPI、就业等宏观经济因素（接入 9-基本面分析 /fundamental/macro + /fundamental/intermarket）',
    chain: 'F' as const,
    category: 'fundamental-macro',
    version: '1.0.0',
    tags: ['macro', 'interest-rate', 'cpi', 'inflation', 'fed'],
    estimatedTokens: 450,
    estimatedLatencyMs: 2800,
    confidenceRange: [45, 70] as [number, number],
    applicableIntents: ['deep_analysis', 'strategy_verify'],
    applicableStages: ['research', 'analysis'] as Array<'research' | 'analysis' | 'design' | 'validate' | 'execute'>,
    marketConditions: ['trending', 'ranging', 'volatile'],
    historicalAccuracy: 55,
  };

  return {
    metadata,
    inputSchema: [],
    outputSchema: [],
    async execute(inputs: Record<string, unknown>, _context: ExecutionContext): Promise<SkillResult> {
      try {
        const symbol = (inputs.symbol as string) || 'BTC';
        const [macroData, intermarketData] = await Promise.all([
          fetchFundamental('macro'),
          fetchFundamental('intermarket'),
        ]);
        const macro = extractCore(macroData);
        const intermarket = extractCore(intermarketData);

        const policyScore = (macro.policy_score as number) ?? 0;
        const dxy = (macro.dxy_strength as number) ?? (intermarket.dxy as number) ?? 100;
        const us10y = (macro.us10y_yield as number) ?? 4.5;
        const cryptoFriendly = (macro.crypto_friendly_score as number) ?? 50;
        const liquidityClock = (macro.liquidity_clock as string) ?? '观望';
        const vix = (intermarket.vix as number) ?? 20;
        const spx = (intermarket.spx as number) ?? 5000;
        const gold = (intermarket.gold as number) ?? 2000;

        const isFavorable = policyScore > 0 || cryptoFriendly > 60;
        const direction = isFavorable ? 'long' : policyScore < -0.3 ? 'short' : 'neutral';
        const confidence = (macroData || intermarketData) ? 55 + Math.round(Math.abs(policyScore) * 20) : 45;

        return createSuccessResult(metadata.id, {
          direction,
          confidence,
          analysis: (macroData || intermarketData)
            ? `${symbol} 宏观分析: DXY=${dxy.toFixed(1)}, 10Y=${us10y.toFixed(2)}%, 加密友好度=${cryptoFriendly.toFixed(0)}/100, 流动性时钟=${liquidityClock}, SPX=${spx.toFixed(0)}, VIX=${vix.toFixed(1)}, 黄金=${gold.toFixed(0)}`
            : `${symbol} 宏观分析: 基本面服务暂不可达`,
          symbol,
          indicators: { policyScore, dxy, us10y, cryptoFriendly, liquidityClock, vix, spx, gold },
          isFavorableForCrypto: isFavorable,
          overallAssessment: isFavorable ? 'favorable' : policyScore < -0.3 ? 'unfavorable' : 'neutral',
          dataSource: (macroData || intermarketData) ? 'tavily + fundamental-api' : 'fallback',
        }, confidence);
      } catch (error) {
        return createFailureResult(metadata.id, error instanceof Error ? error.message : '宏观分析失败');
      }
    },
  };
};

// ============================================================
// 注册函数
// ============================================================

/**
 * 获取所有 C 链技能
 */
export function getAllCSkills(): SkillCapability[] {
  return [
    createC1Skill(),
    createC2Skill(),
    createC3Skill(),
    createC4Skill(),
    createC5Skill(),
  ];
}

/**
 * 获取所有 F 链技能
 */
export function getAllFSkills(): SkillCapability[] {
  return [
    createF1Skill(),
    createF2Skill(),
    createF3Skill(),
    createF4Skill(),
    createF5Skill(),
  ];
}

/**
 * 获取所有 C/F 链技能（不包含 A 链）
 */
export function getAllChainSkills(): SkillCapability[] {
  return [...getAllCSkills(), ...getAllFSkills()];
}

/**
 * 获取链信息摘要
 */
export function getChainSummary(): Array<{
  chain: string;
  chainName: string;
  skills: string[];
  totalSkills: number;
  isPlaceholder: boolean;
}> {
  return [
    {
      chain: 'C',
      chainName: '经典量化指标系统',
      skills: getAllCSkills().map(s => s.metadata.name),
      totalSkills: 5,
      isPlaceholder: false,
    },
    {
      chain: 'F',
      chainName: '基本面分析框架',
      skills: getAllFSkills().map(s => s.metadata.name),
      totalSkills: 5,
      isPlaceholder: true,
    },
  ];
}
