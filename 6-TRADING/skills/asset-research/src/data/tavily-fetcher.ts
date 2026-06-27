/**
 * Tavily数据获取模块
 * 使用Tavily API搜索宏观经济指标
 */

import {
  MacroIndicator,
  TavilySearchResult,
  IndicatorExtraction,
  TrendDirection,
  DataFreshness,
  Region
} from '../types';

// Tavily API配置
const TAVILY_API_URL = 'https://api.tavily.com/search';

/**
 * Tavily数据获取器
 */
export class TavilyFetcher {
  private apiKey: string;
  private maxResults: number;

  constructor(apiKey?: string, maxResults: number = 10) {
    this.apiKey = apiKey || process.env.TAVILY_API_KEY || '';
    this.maxResults = maxResults;
  }

  /**
   * 设置API密钥
   */
  setApiKey(apiKey: string): void {
    this.apiKey = apiKey;
  }

  /**
   * 搜索宏观经济指标
   */
  async searchMacroIndicators(region: Region = 'global'): Promise<TavilySearchResult[]> {
    const queries = this.buildSearchQueries(region);
    const results: TavilySearchResult[] = [];

    for (const query of queries) {
      try {
        const searchResults = await this.search(query);
        results.push(...searchResults);
      } catch (error) {
        console.error(`搜索失败 [${query}]:`, error);
      }
    }

    return results;
  }

  /**
   * 搜索指定主题
   */
  async search(query: string): Promise<TavilySearchResult[]> {
    if (!this.apiKey) {
      console.warn('Tavily API Key未设置，返回模拟数据');
      return this.getMockSearchResults(query);
    }

    try {
      const response = await fetch(TAVILY_API_URL, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          api_key: this.apiKey,
          query,
          search_depth: 'basic',
          max_results: this.maxResults,
          include_answer: true,
          include_raw_content: false,
        }),
      });

      if (!response.ok) {
        throw new Error(`Tavily API错误: ${response.status}`);
      }

      const data = await response.json();

      return (data.results || []).map((r: {
        url: string;
        title: string;
        content: string;
        published_date?: string;
      }) => ({
        url: r.url,
        title: r.title,
        content: r.content || '',
        publishedDate: r.published_date,
      }));
    } catch (error) {
      console.error('Tavily搜索失败:', error);
      return this.getMockSearchResults(query);
    }
  }

  /**
   * 构建搜索查询列表
   */
  private buildSearchQueries(region: Region): string[] {
    const baseQueries = [
      // GDP数据
      '2024 2025 GDP growth rate latest data',
      'global GDP outlook IMF World Bank',
      // CPI数据
      'CPI inflation rate latest',
      'core CPI data United States',
      // PMI数据
      'PMI manufacturing services latest',
      'ISM PMI United States',
      // 利率数据
      'Federal Reserve interest rate decision',
      'central bank monetary policy',
      // 就业数据
      'unemployment rate latest',
      'non-farm payroll employment',
      // 经济展望
      'economic outlook 2025',
      'recession risk economic forecast',
    ];

    if (region === 'cn') {
      return [
        '中国GDP 2024 2025',
        '中国CPI通胀数据',
        '中国PMI制造业',
        '中国央行货币政策',
        '中国就业形势',
        '中国经济展望',
      ];
    }

    return baseQueries;
  }

  /**
   * 从搜索结果提取指标
   */
  extractIndicators(results: TavilySearchResult[]): IndicatorExtraction[] {
    const extractions: IndicatorExtraction[] = [];

    for (const result of results) {
      // 提取GDP
      const gdpMatches = this.extractPattern(result.content, /GDP.*?(\d+\.?\d*)%/gi);
      if (gdpMatches.length > 0) {
        extractions.push({
          indicator: this.createIndicator('GDP增长率', gdpMatches[0], 'up', result.url, 'fresh'),
          rawText: result.content.substring(0, 200),
          confidence: 0.8,
        });
      }

      // 提取CPI
      const cpiMatches = this.extractPattern(result.content, /CPI.*?(\d+\.?\d*)%/gi);
      if (cpiMatches.length > 0) {
        extractions.push({
          indicator: this.createIndicator('CPI通胀率', cpiMatches[0], 'up', result.url, 'fresh'),
          rawText: result.content.substring(0, 200),
          confidence: 0.85,
        });
      }

      // 提取PMI
      const pmiMatches = this.extractPattern(result.content, /PMI.*?(\d+\.?\d*)/gi);
      if (pmiMatches.length > 0) {
        const pmiValue = parseFloat(pmiMatches[0]);
        const trend: TrendDirection = pmiValue >= 50 ? 'up' : 'down';
        extractions.push({
          indicator: this.createIndicator('PMI指数', pmiMatches[0], trend, result.url, 'fresh'),
          rawText: result.content.substring(0, 200),
          confidence: 0.9,
        });
      }

      // 提取失业率
      const unemploymentMatches = this.extractPattern(result.content, /unemployment.*?(\d+\.?\d*)%/gi);
      if (unemploymentMatches.length > 0) {
        extractions.push({
          indicator: this.createIndicator('失业率', unemploymentMatches[0], 'down', result.url, 'fresh'),
          rawText: result.content.substring(0, 200),
          confidence: 0.75,
        });
      }
    }

    return extractions;
  }

  /**
   * 提取正则匹配的数值
   */
  private extractPattern(text: string, pattern: RegExp): string[] {
    const matches = text.match(pattern);
    return matches ? matches.map(m => {
      const numMatch = m.match(/(\d+\.?\d*)/);
      return numMatch ? numMatch[1] : '';
    }).filter(Boolean) : [];
  }

  /**
   * 创建指标对象
   */
  private createIndicator(
    name: string,
    value: string,
    trend: TrendDirection,
    source: string,
    freshness: DataFreshness
  ): MacroIndicator {
    return {
      name,
      value,
      trend,
      source,
      timestamp: new Date().toISOString(),
      freshness,
    };
  }

  /**
   * 生成模拟搜索结果（无API Key时使用）
   */
  private getMockSearchResults(query: string): TavilySearchResult[] {
    return [
      {
        url: 'https://example.com/economic-data',
        title: `Economic Data Report - ${query}`,
        content: this.getMockContent(query),
        publishedDate: new Date().toISOString(),
      },
    ];
  }

  /**
   * 根据查询生成模拟内容
   */
  private getMockContent(query: string): string {
    if (query.toLowerCase().includes('gdp')) {
      return 'The global GDP growth rate is expected to be around 2.8% in 2025. US GDP grew 2.1% in Q4 2024. China GDP target is around 5% for 2025.';
    }
    if (query.toLowerCase().includes('cpi') || query.toLowerCase().includes('inflation')) {
      return 'US CPI increased 2.7% year-over-year in November 2024. Core CPI remains at 3.3%. Inflation pressures are moderating.';
    }
    if (query.toLowerCase().includes('pmi')) {
      return 'US Manufacturing PMI reached 48.4 in November 2024, below the 50 threshold indicating contraction. Services PMI is at 52.1.';
    }
    if (query.toLowerCase().includes('interest') || query.toLowerCase().includes('fed')) {
      return 'The Federal Reserve held interest rates steady at 5.25-5.50%. Markets expect two rate cuts in 2025.';
    }
    if (query.toLowerCase().includes('unemployment')) {
      return 'US unemployment rate is at 4.2%. Non-farm payrolls added 199,000 jobs in November 2024.';
    }
    return 'Economic conditions remain complex with mixed signals across different indicators. Market participants are closely monitoring Fed policy decisions and inflation data.';
  }
}
