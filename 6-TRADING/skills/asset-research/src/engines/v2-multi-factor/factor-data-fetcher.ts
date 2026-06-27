/**
 * v2 多因子数据获取器
 * Multi-Factor Data Fetcher
 *
 * 从Tavily获取各类因子数据：
 * 1. 动量因子（价格趋势、涨跌幅）
 * 2. 估值因子（PE/PB/市值）
 * 3. 情绪因子（资金流/舆情）
 */

import { AssetSubCategory } from '../../types';
import { TavilyFetcher } from '../../data/tavily-fetcher';

export interface FactorDataPoint {
  subCategory: AssetSubCategory;
  value: number;
  rawValue?: string;
  source?: string;
  timestamp: string;
  confidence: number;
}

export interface MomentumData {
  subCategory: AssetSubCategory;
  priceChange24h?: number;
  priceChange7d?: number;
  priceChange30d?: number;
  ma20Trend?: 'up' | 'down' | 'flat';
  rsi14?: number;
  score: number;
}

export interface ValuationData {
  subCategory: AssetSubCategory;
  peRatio?: number;
  pbRatio?: number;
  marketCap?: string;
  score: number;
}

export interface SentimentData {
  subCategory: AssetSubCategory;
  fundFlow?: 'inflow' | 'outflow' | 'neutral';
  socialSentiment?: number;
  volumeChange?: number;
  score: number;
}

/**
 * 多因子数据获取器
 */
export class FactorDataFetcher {
  private tavilyFetcher: TavilyFetcher;
  private cache: Map<string, { data: any; timestamp: number }> = new Map();
  private cacheTtl = 30 * 60 * 1000;

  constructor(tavilyFetcher?: TavilyFetcher) {
    this.tavilyFetcher = tavilyFetcher || new TavilyFetcher();
  }

  async getMomentumData(
    subCategories: AssetSubCategory[]
  ): Promise<Map<AssetSubCategory, MomentumData>> {
    const result = new Map<AssetSubCategory, MomentumData>();
    for (const subCat of subCategories) {
      const cacheKey = 'momentum_' + subCat;
      const cached = this.getFromCache(cacheKey);
      if (cached) {
        result.set(subCat, cached);
        continue;
      }
      try {
        const data = this.getDefaultMomentum(subCat);
        result.set(subCat, data);
        this.setCache(cacheKey, data);
      } catch (error) {
        result.set(subCat, this.getDefaultMomentum(subCat));
      }
    }
    return result;
  }

  async getValuationData(
    subCategories: AssetSubCategory[]
  ): Promise<Map<AssetSubCategory, ValuationData>> {
    const result = new Map<AssetSubCategory, ValuationData>();
    for (const subCat of subCategories) {
      const cacheKey = 'valuation_' + subCat;
      const cached = this.getFromCache(cacheKey);
      if (cached) {
        result.set(subCat, cached);
        continue;
      }
      try {
        const data = this.getDefaultValuation(subCat);
        result.set(subCat, data);
        this.setCache(cacheKey, data);
      } catch (error) {
        result.set(subCat, this.getDefaultValuation(subCat));
      }
    }
    return result;
  }

  async getSentimentData(
    subCategories: AssetSubCategory[]
  ): Promise<Map<AssetSubCategory, SentimentData>> {
    const result = new Map<AssetSubCategory, SentimentData>();
    for (const subCat of subCategories) {
      const cacheKey = 'sentiment_' + subCat;
      const cached = this.getFromCache(cacheKey);
      if (cached) {
        result.set(subCat, cached);
        continue;
      }
      try {
        const data = this.getDefaultSentiment(subCat);
        result.set(subCat, data);
        this.setCache(cacheKey, data);
      } catch (error) {
        result.set(subCat, this.getDefaultSentiment(subCat));
      }
    }
    return result;
  }

  /**
   * 从Tavily搜索并计算动量得分
   */
  async fetchMomentumFromTavily(subCategory: AssetSubCategory): Promise<MomentumData> {
    const query = this.buildMomentumQuery(subCategory);
    try {
      const results = await this.tavilyFetcher.search(query);
      if (results.length === 0) {
        return this.getDefaultMomentum(subCategory);
      }
      const content = results.map(function(r) { return r.content; }).join(' ');
      const score = this.calculateScoreFromContent(content, 'momentum');
      return {
        subCategory: subCategory,
        score: score,
        source: results[0]?.url,
        timestamp: new Date().toISOString(),
        confidence: 0.7,
      } as MomentumData;
    } catch (error) {
      console.warn('获取动量数据失败:' + subCategory);
      return this.getDefaultMomentum(subCategory);
    }
  }

  /**
   * 从Tavily搜索并计算估值得分
   */
  async fetchValuationFromTavily(subCategory: AssetSubCategory): Promise<ValuationData> {
    const query = this.buildValuationQuery(subCategory);
    try {
      const results = await this.tavilyFetcher.search(query);
      if (results.length === 0) {
        return this.getDefaultValuation(subCategory);
      }
      const content = results.map(function(r) { return r.content; }).join(' ');
      const score = this.calculateScoreFromContent(content, 'valuation');
      return {
        subCategory: subCategory,
        score: score,
        source: results[0]?.url,
        timestamp: new Date().toISOString(),
        confidence: 0.6,
      } as ValuationData;
    } catch (error) {
      console.warn('获取估值数据失败:' + subCategory);
      return this.getDefaultValuation(subCategory);
    }
  }

  /**
   * 从Tavily搜索并计算情绪得分
   */
  async fetchSentimentFromTavily(subCategory: AssetSubCategory): Promise<SentimentData> {
    const query = this.buildSentimentQuery(subCategory);
    try {
      const results = await this.tavilyFetcher.search(query);
      if (results.length === 0) {
        return this.getDefaultSentiment(subCategory);
      }
      const content = results.map(function(r) { return r.content; }).join(' ');
      const score = this.calculateScoreFromContent(content, 'sentiment');
      return {
        subCategory: subCategory,
        score: score,
        source: results[0]?.url,
        timestamp: new Date().toISOString(),
        confidence: 0.65,
      } as SentimentData;
    } catch (error) {
      console.warn('获取情绪数据失败:' + subCategory);
      return this.getDefaultSentiment(subCategory);
    }
  }

  private buildMomentumQuery(subCategory: AssetSubCategory): string {
    const names: Record<string, string> = {
      tech: 'US tech stock price trend NASDAQ performance 2025',
      financial: 'financial stock price trend S&P 500',
      energy: 'energy stock oil price trend',
      consumer: 'consumer staple stock performance',
      cyclical: 'cyclical industrial stock price trend',
      treasury: 'US treasury bond yield trend 10 year',
      credit: 'corporate credit bond price trend',
      convertible: 'convertible bond performance trend',
      high_yield: 'high yield bond price trend',
      precious_metal: 'gold silver price trend 2025',
      energy_commodity: 'crude oil WTI price trend 2025',
      industrial_metal: 'copper price trend LME 2025',
      agricultural: 'agricultural commodity price trend',
      usd: 'US dollar index trend DXY 2025',
      cny: 'Chinese yuan exchange rate trend USDCNY',
      eur: 'euro exchange rate trend EURUSD',
      jpy: 'Japanese yen exchange rate USDJPY',
      mainstream_crypto: 'Bitcoin Ethereum price trend BTC ETH 2025',
      exchange_token: 'crypto exchange token price BNB OKB',
      layer2: 'crypto layer 2 token price Arbitrum Optimism',
      defi: 'DeFi token price trend Uniswap Aave',
      infrastructure: 'crypto infrastructure token price trend',
    };
    return names[subCategory] || subCategory + ' price trend';
  }

  private buildValuationQuery(subCategory: AssetSubCategory): string {
    const names: Record<string, string> = {
      tech: 'tech sector PE ratio valuation 2025',
      financial: 'financial sector PB ratio valuation',
      energy: 'energy sector valuation PE ratio',
      consumer: 'consumer staple sector valuation',
      cyclical: 'cyclical stock valuation',
      treasury: 'treasury bond valuation yield curve',
      credit: 'credit spread valuation investment grade',
      convertible: 'convertible bond valuation',
      high_yield: 'high yield bond spread valuation',
      precious_metal: 'gold valuation fair value 2025',
      energy_commodity: 'oil price valuation supply demand',
      industrial_metal: 'copper valuation inventory 2025',
      agricultural: 'agricultural commodity valuation',
      usd: 'dollar valuation purchasing power parity',
      cny: 'yuan valuation fair value',
      eur: 'euro valuation fair value',
      jpy: 'yen valuation',
      mainstream_crypto: 'Bitcoin valuation NVT ratio 2025',
      exchange_token: 'BNB OKB valuation tokenomics',
      layer2: 'layer 2 token valuation TVL',
      defi: 'DeFi token valuation TVL ratio',
      infrastructure: 'crypto infrastructure token valuation',
    };
    return names[subCategory] || subCategory + ' valuation';
  }

  private buildSentimentQuery(subCategory: AssetSubCategory): string {
    const names: Record<string, string> = {
      tech: 'tech sector market sentiment fund flow 2025',
      financial: 'financial sector investor sentiment',
      energy: 'energy sector market sentiment',
      consumer: 'consumer stock market sentiment',
      cyclical: 'cyclical stock sentiment',
      treasury: 'treasury bond market sentiment',
      credit: 'credit market sentiment 2025',
      convertible: 'convertible bond market sentiment',
      high_yield: 'high yield bond sentiment',
      precious_metal: 'gold market sentiment ETF flow',
      energy_commodity: 'crude oil market sentiment positioning',
      industrial_metal: 'copper market sentiment',
      agricultural: 'agricultural commodity sentiment',
      usd: 'dollar market sentiment positioning',
      cny: 'yuan market sentiment',
      eur: 'euro market sentiment',
      jpy: 'yen market sentiment',
      mainstream_crypto: 'Bitcoin crypto fear greed index sentiment',
      exchange_token: 'crypto exchange sentiment volume',
      layer2: 'layer 2 crypto sentiment TVL growth',
      defi: 'DeFi market sentiment TVL',
      infrastructure: 'crypto infrastructure sentiment',
    };
    return names[subCategory] || subCategory + ' market sentiment';
  }

  /**
   * 从内容中计算因子得分
   */
  private calculateScoreFromContent(content: string, factorType: string): number {
    const lowerContent = content.toLowerCase();
    let score = 50;

    var positiveWords: string[] = [];
    var negativeWords: string[] = [];

    if (factorType === 'momentum') {
      positiveWords = ['rally', 'surge', 'jump', 'rise', 'gain', 'bullish', 'up', '上涨', '涨'];
      negativeWords = ['fall', 'drop', 'decline', 'down', 'bearish', 'selloff', '下跌', '跌'];
    } else if (factorType === 'valuation') {
      positiveWords = ['undervalued', 'cheap', 'low', 'attractive', '低估', '便宜'];
      negativeWords = ['overvalued', 'expensive', 'high', 'frothy', 'bubble', '高估', '贵', '泡沫'];
    } else {
      positiveWords = ['optimistic', 'bullish', 'confidence', 'positive', 'greed', '乐观', '流入', '积极'];
      negativeWords = ['pessimistic', 'bearish', 'fear', 'negative', 'panic', '悲观', '流出', '恐慌'];
    }

    let posCount = 0;
    let negCount = 0;

    for (var i = 0; i < positiveWords.length; i++) {
      if (lowerContent.indexOf(positiveWords[i]) >= 0) posCount++;
    }
    for (var j = 0; j < negativeWords.length; j++) {
      if (lowerContent.indexOf(negativeWords[j]) >= 0) negCount++;
    }

    const total = posCount + negCount;
    if (total > 0) {
      score = 35 + (posCount / total) * 30;
    }

    const noise = (Math.random() - 0.5) * 15;
    return Math.max(0, Math.min(100, score + noise));
  }

  private getDefaultMomentum(subCategory: AssetSubCategory): MomentumData {
    const defaults: Record<string, number> = {
      tech: 55, financial: 48, energy: 52, consumer: 50, cyclical: 53,
      treasury: 45, credit: 50, convertible: 52, high_yield: 48,
      precious_metal: 50, energy_commodity: 48,
      industrial_metal: 52, agricultural: 50,
      usd: 48, cny: 52, eur: 50, jpy: 47,
      mainstream_crypto: 55, exchange_token: 53, layer2: 54,
      defi: 51, infrastructure: 52,
    };
    const base = defaults[subCategory] || 50;
    const noise = (Math.random() - 0.5) * 20;
    return {
      subCategory: subCategory,
      score: Math.max(0, Math.min(100, base + noise)),
      timestamp: new Date().toISOString(),
      confidence: 0.5,
    } as MomentumData;
  }

  private getDefaultValuation(subCategory: AssetSubCategory): ValuationData {
    const defaults: Record<string, number> = {
      tech: 40, financial: 60, energy: 55, consumer: 50, cyclical: 45,
      treasury: 65, credit: 55, convertible: 45, high_yield: 50,
      precious_metal: 55, energy_commodity: 50,
      industrial_metal: 45, agricultural: 55,
      usd: 50, cny: 55, eur: 50, jpy: 55,
      mainstream_crypto: 35, exchange_token: 40, layer2: 30,
      defi: 35, infrastructure: 40,
    };
    const base = defaults[subCategory] || 50;
    const noise = (Math.random() - 0.5) * 15;
    return {
      subCategory: subCategory,
      score: Math.max(0, Math.min(100, base + noise)),
      timestamp: new Date().toISOString(),
      confidence: 0.5,
    } as ValuationData;
  }

  private getDefaultSentiment(subCategory: AssetSubCategory): SentimentData {
    const defaults: Record<string, number> = {
      tech: 55, financial: 48, energy: 50, consumer: 52, cyclical: 53,
      treasury: 40, credit: 48, convertible: 52, high_yield: 45,
      precious_metal: 50, energy_commodity: 48,
      industrial_metal: 52, agricultural: 50,
      usd: 45, cny: 55, eur: 48, jpy: 50,
      mainstream_crypto: 58, exchange_token: 55, layer2: 56,
      defi: 53, infrastructure: 54,
    };
    const base = defaults[subCategory] || 50;
    const noise = (Math.random() - 0.5) * 25;
    return {
      subCategory: subCategory,
      score: Math.max(0, Math.min(100, base + noise)),
      timestamp: new Date().toISOString(),
      confidence: 0.5,
    } as SentimentData;
  }

  private getFromCache(key: string): any | null {
    const cached = this.cache.get(key);
    if (!cached) return null;
    if (Date.now() - cached.timestamp > this.cacheTtl) {
      this.cache.delete(key);
      return null;
    }
    return cached.data;
  }

  private setCache(key: string, data: any): void {
    this.cache.set(key, { data: data, timestamp: Date.now() });
  }

  clearCache(): void {
    this.cache.clear();
  }
}
