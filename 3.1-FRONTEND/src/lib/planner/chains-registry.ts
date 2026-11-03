/**
 * F链 技能注册表
 *
 * 位置: 6-图结构上下文压缩/planner/chains-registry.ts
 *
 * 功能:
 * - F链: 基本面分析框架（接入 9-基本面分析）
 * - 所有技能统一实现 SkillCapability 接口
 *
 * 说明:
 * - C链（经典量化指标）已退役，技术面/策略库/回测/信号能力由 M25-M28 模块化服务提供
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
 * 获取所有 F 链技能（不包含 A 链）
 */
export function getAllChainSkills(): SkillCapability[] {
  return [...getAllFSkills()];
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
      chain: 'F',
      chainName: '基本面分析框架',
      skills: getAllFSkills().map(s => s.metadata.name),
      totalSkills: 5,
      isPlaceholder: true,
    },
  ];
}
