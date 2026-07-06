/**
 * SkillLLMBridge 适配器
 *
 * 将 llm-bridge、market-data-bridge、node-prompts 组合成 SkillLLMBridge 接口。
 * 在 task-manager.ts 初始化时注入到 ExecutionContext.__skillLLMBridge。
 */

import { callLLM } from './llm-bridge';
import { getMarketData, type MarketData } from './market-data-bridge';
import {
  buildSkillPrompt,
  getSkillSystemPrompt,
  parseConfidence,
  parseDirection,
  type SkillMeta,
} from './node-prompts';
import type { SkillLLMBridge } from '.././planner/skills-registry-init';

export type { SkillLLMBridge };

/**
 * 市场数据缓存（避免同一会话内重复请求）
 */
const marketDataCache = new Map<string, MarketData>();

/**
 * 创建 SkillLLMBridge 实例
 *
 * @param uid 用户ID（用于读取 LLM 凭证）
 * @param marketDataContext 市场数据上下文（symbol/instId 等）
 */
export function createSkillLLMBridge(
  uid?: string,
  marketDataContext?: {
    symbol: string;
    instId: string;
    category: 'crypto' | 'macro';
    displayName: string;
    tavilyQuery?: string;
  },
): SkillLLMBridge {
  return {
    async analyzeSkill(params) {
      const { skillId, skillName, description, stage, symbol, userRequest, priorResults } = params;

      // 获取市场数据（带缓存）
      let marketData: MarketData | undefined;
      if (marketDataContext) {
        const cacheKey = marketDataContext.instId || marketDataContext.symbol;
        if (cacheKey && marketDataCache.has(cacheKey)) {
          marketData = marketDataCache.get(cacheKey);
        } else {
          try {
            marketData = await getMarketData({
              symbol: marketDataContext.symbol,
              instId: marketDataContext.instId,
              category: marketDataContext.category,
              displayName: marketDataContext.displayName,
              tavilyQuery: marketDataContext.tavilyQuery,
            });
            if (cacheKey) marketDataCache.set(cacheKey, marketData);
          } catch {
            // 市场数据获取失败，继续执行（prompt 中会显示"未知"）
          }
        }
      }

      // 构建 prompt
      const meta: SkillMeta = {
        skillId,
        skillName,
        description,
        stage: stage as 'research' | 'analysis' | 'design' | 'validate' | 'execute',
      };

      const priorResultsMap = priorResults
        ? new Map(Object.entries(priorResults))
        : undefined;

      const prompt = buildSkillPrompt(meta, {
        userRequest: userRequest || '',
        symbol,
        displayName: marketData?.displayName || symbol,
        marketData,
      }, priorResultsMap);

      const systemPrompt = getSkillSystemPrompt(skillId);

      // 调用 LLM
      const llmResult = await callLLM({
        prompt,
        systemPrompt,
        temperature: 0.7,
        maxTokens: 2000,
        timeoutMs: 30000,
      }, uid);

      // 解析结果
      const confidence = parseConfidence(llmResult.content);
      const direction = parseDirection(llmResult.content);

      return {
        content: llmResult.content,
        confidence,
        direction,
        tokensUsed: llmResult.tokensUsed,
      };
    },
  };
}
