/**
 * tavily-service.ts — Tavily 联网搜索服务
 * 大模型访问数据访问层发现数据缺失时，主动联网获取
 * API Key 优先从环境变量读取，回退到 .env.local 文件
 */

import { readFileSync } from 'fs';
import path from 'path';

const TAVILY_URL = 'https://api.tavily.com/search';

function loadApiKey(): string {
  // 优先从 .env.local 读取（确保修改后立即生效，不依赖进程重启）
  try {
    const envPath = path.join(process.cwd(), '.env.local');
    const content = readFileSync(envPath, 'utf-8');
    const match = content.match(/^TAVILY_API_KEY=(.+)$/m);
    if (match) {
      const key = match[1].trim().replace(/^["']|["']$/g, '');
      if (key) return key;
    }
  } catch { /* ignore */ }
  // 回退：环境变量
  return process.env.TAVILY_API_KEY || '';
}

// 动态读取，避免模块级缓存导致 .env.local 修改后不生效
function getApiKey(): string {
  return loadApiKey();
}

export interface TavilySearchResult {
  title: string;
  url: string;
  content: string;
  score?: number;
  published_date?: string;
}

export interface TavilyResponse {
  results: TavilySearchResult[];
  answer?: string;
  query?: string;
}

let cache = new Map<string, { data: TavilyResponse; ts: number }>();
const CACHE_TTL = 5 * 60 * 1000; // 5分钟缓存

export async function tavilySearch(
  query: string,
  options: { maxResults?: number; searchDepth?: 'basic' | 'advanced'; includeAnswer?: boolean } = {}
): Promise<TavilyResponse> {
  const apiKey = getApiKey();
  if (!apiKey) {
    return { results: [], answer: undefined };
  }

  const cacheKey = `${query}|${options.maxResults || 5}`;
  const cached = cache.get(cacheKey);
  if (cached && Date.now() - cached.ts < CACHE_TTL) {
    return cached.data;
  }

  try {
    const res = await fetch(TAVILY_URL, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        api_key: apiKey,
        query,
        max_results: options.maxResults || 5,
        search_depth: options.searchDepth || 'basic',
        include_answer: options.includeAnswer ?? true,
      }),
    });

    if (!res.ok) throw new Error(`Tavily HTTP ${res.status}`);
    const data = (await res.json()) as TavilyResponse;
    cache.set(cacheKey, { data, ts: Date.now() });
    return data;
  } catch (e) {
    console.error('[tavily] search failed:', e);
    return { results: [], answer: undefined };
  }
}

/** 从文本中提取数值，自动识别 million/billion 单位并转换 */
export function extractNumberWithUnit(text: string): { value: number; unit: string } | null {
  // 匹配 $101.67 million / $1.74 billion / 500M / 2.5B 等格式
  const patterns = [
    /\$?([\d,]+\.?\d*)\s*(billion|bn|B)\b/i,
    /\$?([\d,]+\.?\d*)\s*(million|mn|M)\b/i,
    /\$?([\d,]+\.?\d*)\s*(thousand|k)\b/i,
  ];
  for (const p of patterns) {
    const m = text.match(p);
    if (m) {
      const num = parseFloat(m[1].replace(/,/g, ''));
      if (!isNaN(num)) {
        const unit = m[2].toLowerCase();
        let multiplier = 1;
        if (unit.startsWith('b')) multiplier = 1e9;
        else if (unit.startsWith('m')) multiplier = 1e6;
        else if (unit.startsWith('k') || unit.startsWith('thousand')) multiplier = 1e3;
        return { value: num * multiplier, unit };
      }
    }
  }
  // 无单位的纯数字
  const m = text.match(/\$?([\d,]+\.?\d*)/);
  if (m) {
    const num = parseFloat(m[1].replace(/,/g, ''));
    if (!isNaN(num)) return { value: num, unit: '' };
  }
  return null;
}

/** 从 Tavily 搜索结果中提取数值（兼容旧接口） */
export function extractNumber(text: string, pattern: RegExp): number | null {
  const match = text.match(pattern);
  if (match) {
    const num = parseFloat(match[1].replace(/,/g, ''));
    return isNaN(num) ? null : num;
  }
  return null;
}

/** 搜索并提取特定指标的数值 */
export async function fetchMetricViaTavily(
  query: string,
  pattern: RegExp,
  maxResults: number = 3
): Promise<{ value: number | null; source: string; raw: string }> {
  const result = await tavilySearch(query, { maxResults, includeAnswer: true });

  // 优先从 answer 提取（带单位识别）
  if (result.answer) {
    const withUnit = extractNumberWithUnit(result.answer);
    if (withUnit) {
      return { value: withUnit.value, source: 'tavily-answer', raw: result.answer };
    }
    const val = extractNumber(result.answer, pattern);
    if (val !== null) {
      return { value: val, source: 'tavily-answer', raw: result.answer };
    }
  }

  // 从搜索结果提取
  for (const r of result.results) {
    const withUnit = extractNumberWithUnit(r.content);
    if (withUnit) {
      return { value: withUnit.value, source: r.url, raw: r.content.slice(0, 200) };
    }
    const val = extractNumber(r.content, pattern);
    if (val !== null) {
      return { value: val, source: r.url, raw: r.content.slice(0, 200) };
    }
  }

  return { value: null, source: 'tavily-not-found', raw: '' };
}
