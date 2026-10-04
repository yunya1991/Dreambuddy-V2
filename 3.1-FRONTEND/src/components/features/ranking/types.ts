// ============================================
// 交易榜单推荐系统 — 类型定义
// 对齐后端 trading-ranking-service.ts 的 DecisionCard / TradingRankingItem
// ============================================

export type SignalType = 'STRONG_BUY' | 'BUY' | 'WEAK_BUY' | 'NEUTRAL' | 'WEAK_SELL' | 'SELL' | 'STRONG_SELL';
export type CategoryType = 'crypto' | 'commodity' | 'index';
export type RiskLevel = 'novice' | 'intermediate' | 'expert';

export interface DecisionCardData {
  entry: {
    price: number;
    range: [number, number];
    batches: { price: number; ratio: number }[];
  };
  stopLoss: number;
  takeProfit: number[];
  events: { date: string; name: string; impact: string }[];
  riskLevel: RiskLevel;
  historicalAnalogy: string;
  logic: {
    bullish: string[];
    bearish: string[];
    confidence: number;
  };
}

export interface TradingRankingItem {
  rank: number;
  symbol: string;
  category: CategoryType;
  score: number;
  signal: SignalType;
  confidence: number;
  decisionCard: DecisionCardData;
  date: string;
}

export interface RankingMonitorMetrics {
  date: string;
  satisfaction: number | null;
  conversionRate: number | null;
  abandonRate: number | null;
  pushReachRate: number | null;
  unsubscribeRate: number | null;
  matu: number | null;
  kFactor: number | null;
}

// ---- 信号 / 品类 / 风险 映射表 ----

export const signalConfig: Record<SignalType, { label: string; variant: 'success' | 'info' | 'default' | 'warning' | 'danger'; dot?: boolean; pulse?: boolean }> = {
  STRONG_BUY: { label: '强烈买入', variant: 'success', dot: true, pulse: true },
  BUY: { label: '买入', variant: 'success' },
  WEAK_BUY: { label: '弱买', variant: 'info' },
  NEUTRAL: { label: '中性', variant: 'default' },
  WEAK_SELL: { label: '弱卖', variant: 'warning' },
  SELL: { label: '卖出', variant: 'danger' },
  STRONG_SELL: { label: '强烈卖出', variant: 'danger', dot: true, pulse: true },
};

export const categoryConfig: Record<CategoryType, { label: string; color: string }> = {
  crypto: { label: '加密', color: 'text-orange-400' },
  commodity: { label: '大宗', color: 'text-amber-400' },
  index: { label: '指数', color: 'text-blue-400' },
};

export const riskConfig: Record<RiskLevel, { label: string; variant: 'info' | 'warning' | 'danger'; position: string }> = {
  novice: { label: '新手', variant: 'info', position: '建议仓位 10-20%' },
  intermediate: { label: '进阶', variant: 'warning', position: '建议仓位 20-40%' },
  expert: { label: '高手', variant: 'danger', position: '建议仓位 40-60%' },
};

// ---- Mock 数据（P0 开发期使用，REFACTOR 阶段替换为 API 调用） ----

export const mockRankingItems: TradingRankingItem[] = [
  {
    rank: 1,
    symbol: 'BTC/USDT',
    category: 'crypto',
    score: 0.82,
    signal: 'STRONG_BUY',
    confidence: 0.78,
    date: '2026-09-28',
    decisionCard: {
      entry: {
        price: 65200,
        range: [64800, 65600],
        batches: [
          { price: 65000, ratio: 0.4 },
          { price: 64500, ratio: 0.35 },
          { price: 64000, ratio: 0.25 },
        ],
      },
      stopLoss: 63200,
      takeProfit: [67500, 69000, 71000],
      events: [
        { date: '2026-09-30', name: 'CPI 数据公布', impact: '高' },
        { date: '2026-10-02', name: '非农就业', impact: '中' },
      ],
      riskLevel: 'intermediate',
      historicalAnalogy: '2024年2月 BTC 突破 50K 后回踩确认，随后 30 天上涨 18%',
      logic: {
        bullish: ['RSI 金叉 + MACD 零轴上穿', '链上大户净流入 +12K BTC', 'GitHub 开发活跃度 85/100'],
        bearish: ['FOMC 前观望情绪', '期货费率略偏热'],
        confidence: 0.78,
      },
    },
  },
  {
    rank: 2,
    symbol: 'ETH/USDT',
    category: 'crypto',
    score: 0.71,
    signal: 'BUY',
    confidence: 0.65,
    date: '2026-09-28',
    decisionCard: {
      entry: {
        price: 3250,
        range: [3200, 3300],
        batches: [
          { price: 3250, ratio: 0.5 },
          { price: 3200, ratio: 0.5 },
        ],
      },
      stopLoss: 3120,
      takeProfit: [3400, 3550],
      events: [
        { date: '2026-10-05', name: 'ETH ETF 资金流', impact: '高' },
      ],
      riskLevel: 'novice',
      historicalAnalogy: '2024年3月 ETH 跟随 BTC 突破，涨幅滞后但确定性高',
      logic: {
        bullish: ['布林带挤压突破在即', 'DefiLlama TVL 周增 +5.2%'],
        bearish: ['量能不足', 'Gas 费偏高'],
        confidence: 0.65,
      },
    },
  },
  {
    rank: 3,
    symbol: 'XAU/USD',
    category: 'commodity',
    score: 0.68,
    signal: 'BUY',
    confidence: 0.62,
    date: '2026-09-28',
    decisionCard: {
      entry: {
        price: 2658,
        range: [2650, 2670],
        batches: [
          { price: 2655, ratio: 0.6 },
          { price: 2650, ratio: 0.4 },
        ],
      },
      stopLoss: 2630,
      takeProfit: [2680, 2700],
      events: [
        { date: '2026-09-30', name: 'CPI 数据', impact: '高' },
      ],
      riskLevel: 'novice',
      historicalAnalogy: '2024年地缘紧张期黄金避险买盘，10 天涨 3.5%',
      logic: {
        bullish: ['实际利率下行', '央行持续增持', '避险需求升'],
        bearish: ['美元指数反弹'],
        confidence: 0.62,
      },
    },
  },
];

export const mockMonitorMetrics: RankingMonitorMetrics = {
  date: '2026-09-28',
  satisfaction: 4.2,
  conversionRate: 0.32,
  abandonRate: 0.12,
  pushReachRate: 0.91,
  unsubscribeRate: 0.03,
  matu: 1542,
  kFactor: 1.8,
};
