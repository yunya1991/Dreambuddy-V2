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
  SkillMetadata,
  ExecutionContext,
  SkillResult,
  createSuccessResult,
  createFailureResult,
} from './skill-types.ts';

// ============================================================
// 经典指标系统 HTTP 客户端（调用 10-经典指标系统 http://127.0.0.1:8092）
// ============================================================

const CLASSIC_API = 'http://127.0.0.1:8092';

async function fetchClassic(
  path: string,
  opts: { method?: string; body?: unknown; timeoutMs?: number } = {}
): Promise<Record<string, unknown> | null> {
  try {
    const res = await fetch(`${CLASSIC_API}${path}`, {
      method: opts.method || 'GET',
      headers: opts.body ? { 'Content-Type': 'application/json' } : undefined,
      body: opts.body ? JSON.stringify(opts.body) : undefined,
      signal: AbortSignal.timeout(opts.timeoutMs ?? 6000),
    });
    if (!res.ok) return null;
    return await res.json() as Record<string, unknown>;
  } catch {
    return null;
  }
}

// ============================================================
// C 链: 经典量化指标系统
// ============================================================

/**
 * C1 - 技术指标扫描
 * 扫描 RSI, MACD, MA, Bollinger Bands 等指标
 * 接入：GET /three_screen/daily/signal?auto_compute=true&pair={symbol}
 */
export const createC1Skill = (): SkillCapability => {
  const metadata: SkillMetadata = {
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
      const symbol = (inputs.symbol as string) || 'BTC';
      // 接入 /three_screen/daily/signal?pair=BTC&auto_compute=true
      const data = await fetchClassic(`/three_screen/daily/signal?pair=${symbol}&auto_compute=true`);
      if (data && data.ok !== false) {
        const ev = (data.event as Record<string, unknown>) || data;
        const side = (ev.side as string) || (ev.signal as string) || 'neutral';
        const conf = Math.round(Number(ev.confidence ?? ev.score ?? 72));
        const indicators = (ev.indicators as Record<string, unknown>) || {};
        const direction = side === 'long' ? 'long' : side === 'short' ? 'short' : 'neutral';
        return createSuccessResult(metadata.id, {
          direction,
          confidence: conf,
          analysis: `${symbol} 三屏日线信号: side=${side} conf=${conf} group=${ev.group_id ?? 'default'}`,
          symbol,
          indicators,
          signalSource: 'three_screen_daily',
          raw: ev,
        }, conf);
      }
      // fallback: 返回低置信度中性信号
      return createSuccessResult(metadata.id, {
        direction: 'neutral', confidence: 50,
        analysis: `${symbol} 技术指标扫描: 服务暂不可达（:8092），使用 fallback`,
        symbol, dataSource: 'fallback',
      }, 50);
    },
  };
};

/**
 * C2 - 市场状态识别
 * 识别趋势/震荡/突破等状态
 */
export const createC2Skill = (): SkillCapability => {
  const metadata: SkillMetadata = {
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
      const symbol = (inputs.symbol as string) || 'BTC';
      // 接入 POST /signals/hyperliquid/regime_hybrid { coin: symbol }
      const data = await fetchClassic('/signals/hyperliquid/regime_hybrid', {
        method: 'POST', body: { coin: symbol, emit: false },
      });
      const strategyMap: Record<string, string[]> = {
        trending: ['趋势跟踪', '动量策略', 'MA交叉'],
        ranging: ['均值回归', '网格交易', '通道'],
        volatile: ['波动率突破', '套利'],
      };
      if (data && data.ok) {
        const sig = (data.signal as Record<string, unknown>) || {};
        const diag = (data.diagnostic as Record<string, unknown>) || {};
        const side = (sig.side as string) || (diag.side as string) || 'neutral';
        const tag = (sig.tag as string) || (diag.tag as string) || '';
        const conf = Math.round(Number(sig.confidence ?? diag.confidence ?? 72));
        const regime = tag.includes('trend') ? 'trending' : tag.includes('range') ? 'ranging' : 'volatile';
        const direction = side === 'long' ? 'long' : side === 'short' ? 'short' : 'neutral';
        return createSuccessResult(metadata.id, {
          direction, confidence: conf,
          analysis: `${symbol} 市场状态: regime=${regime} side=${side} tag=${tag} conf=${conf}`,
          symbol, regime, recommendedStrategies: strategyMap[regime] ?? [],
          signalSource: 'regime_hybrid_api', raw: { sig, diag },
        }, conf);
      }
      // fallback
      return createSuccessResult(metadata.id, {
        direction: 'neutral', confidence: 52,
        analysis: `${symbol} 市场状态识别: 服务暂不可达（:8092），使用 fallback`,
        symbol, regime: 'unknown', dataSource: 'fallback',
      }, 52);
    },
  };
};

/**
 * C3 - 策略库匹配
 * 从经典策略库中匹配最优策略
 */
export const createC3Skill = (): SkillCapability => {
  const metadata: SkillMetadata = {
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
      const symbol = (inputs.symbol as string) || 'BTC';
      // 接入 GET /strategy/feeder/capabilities
      const data = await fetchClassic('/strategy/feeder/capabilities');
      if (data && data.ok && Array.isArray(data.strategies)) {
        const strategies = data.strategies as Array<Record<string, unknown>>;
        const best = strategies[0];
        const bestId = (best?.strategy_id as string) ?? 'RegimeHybridStrategy';
        const conf = 70;
        return createSuccessResult(metadata.id, {
          direction: 'neutral', confidence: conf,
          analysis: `${symbol} 策略匹配: 可用策略 ${strategies.length} 个，首选 ${bestId}`,
          symbol, bestStrategy: bestId,
          availableStrategies: strategies.map(s => ({
            id: s.strategy_id, canTrigger: s.can_trigger, direction: s.direction_capability,
          })),
          signalSource: 'strategy_feeder_capabilities',
        }, conf);
      }
      // fallback: 静态策略列表
      const fallback = [
        { id: 'RegimeHybridStrategy', score: 78 },
        { id: 'Strategy005', score: 70 },
        { id: 'BreakoutStrategy', score: 65 },
      ];
      return createSuccessResult(metadata.id, {
        direction: 'neutral', confidence: 55,
        analysis: `${symbol} 策略匹配: 服务暂不可达（:8092），使用静态策略列表`,
        symbol, bestStrategy: fallback[0].id,
        availableStrategies: fallback, dataSource: 'fallback',
      }, 55);
    },
  };
};

/**
 * C4 - 历史回测验证
 * 基于历史数据验证策略表现
 */
export const createC4Skill = (): SkillCapability => {
  const metadata: SkillMetadata = {
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
      const symbol = (inputs.symbol as string) || 'BTC';
      // 接入 GET /three_screen/weekly/status?pair=BTC
      const data = await fetchClassic(`/three_screen/weekly/status?pair=${symbol}`);
      if (data && data.ok !== false) {
        const ev = (data.event as Record<string, unknown>) || data;
        const metrics = (ev.metrics as Record<string, unknown>) || (ev.backtest as Record<string, unknown>) || {};
        const winRate = Number(metrics.win_rate ?? metrics.winRate ?? 55);
        const sharpe = Number(metrics.sharpe ?? metrics.sharpe_ratio ?? 1.2);
        const maxDD = Number(metrics.max_drawdown ?? metrics.maxDrawdown ?? 15);
        const passed = winRate > 50 && sharpe > 1.0 && maxDD < 25;
        const conf = Math.min(90, 65 + Math.round(winRate / 5));
        return createSuccessResult(metadata.id, {
          direction: passed ? 'long' : 'neutral', confidence: conf,
          analysis: `${symbol} 回测验证: 胜率=${winRate.toFixed(1)}% 夏普=${sharpe.toFixed(2)} 最大回撤=${maxDD.toFixed(1)}% ${passed ? '✓通过' : '✗未通过'}`,
          symbol,
          metrics: { winRate, sharpeRatio: sharpe, maxDrawdown: maxDD },
          passed, signalSource: 'three_screen_weekly_status', raw: ev,
        }, conf);
      }
      // fallback
      return createSuccessResult(metadata.id, {
        direction: 'neutral', confidence: 55,
        analysis: `${symbol} 历史回测验证: 服务暂不可达（:8092），使用 fallback`,
        symbol, passed: false, dataSource: 'fallback',
      }, 55);
    },
  };
};

/**
 * C5 - 策略参数优化
 * 输出策略参数和信号阈值
 */
export const createC5Skill = (): SkillCapability => {
  const metadata: SkillMetadata = {
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
      const symbol = (inputs.symbol as string) || 'BTC';
      // 接入 GET /three_screen/daily/signal?pair=BTC — 从信号提取当前优化参数
      const data = await fetchClassic(`/three_screen/daily/signal?pair=${symbol}&auto_compute=false`);
      if (data && data.ok !== false) {
        const ev = (data.event as Record<string, unknown>) || data;
        const params = (ev.params as Record<string, unknown>) || (ev.parameters as Record<string, unknown>) || {};
        const conf = 72;
        const stopLoss = Number(params.stoploss ?? params.stop_loss ?? 0.05);
        const roi = (params.minimal_roi as Record<string, unknown>) || {};
        return createSuccessResult(metadata.id, {
          direction: 'neutral', confidence: conf,
          analysis: `${symbol} 参数优化: 止损=${(stopLoss * 100).toFixed(1)}% roi=${JSON.stringify(roi).slice(0, 60)}`,
          symbol, parameters: { stopLoss, roi, raw: params },
          executionReady: true, signalSource: 'three_screen_daily_params',
        }, conf);
      }
      // fallback: 返回保守默认参数
      return createSuccessResult(metadata.id, {
        direction: 'neutral', confidence: 52,
        analysis: `${symbol} 参数优化: 服务暂不可达（:8092），使用默认参数`,
        symbol,
        parameters: { stopLoss: 0.05, takeProfitMultiplier: 2.0, positionSize: 0.1 },
        executionReady: false, dataSource: 'fallback',
      }, 52);
    },
  };
};

// ============================================================
// F 链: 基本面分析框架
// ============================================================

// ============================================================
// 基本面服务 HTTP 客户端（调用 9-基本面分析 http://127.0.0.1:9094）
// ============================================================

const FUNDAMENTAL_API = 'http://127.0.0.1:9094';

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
  const metadata: SkillMetadata = {
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
  const metadata: SkillMetadata = {
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
  const metadata: SkillMetadata = {
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
  const metadata: SkillMetadata = {
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
  const metadata: SkillMetadata = {
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
