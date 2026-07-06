// 意图路由器 - Intent Router
// 前端本地意图识别 + 桥接层路由

import { IntentAPI, SkillAPI, MarketAPI, TradeAPI } from './bridge-client';

// 意图类型定义
export type IntentType =
  | 'market_analysis'
  | 'trade_execution'
  | 'risk_control'
  | 'intelligence'
  | 'strategy_design'
  | 'signal_query'
  | 'contradiction'
  | 'review'
  | 'exit'
  | 'unknown';

// 路由结果
export interface RoutingResult {
  intent: IntentType;
  confidence: number;
  symbol?: string;
  direction?: 'long' | 'short';
  skills: string[];
  action: 'market' | 'trade' | 'skill' | 'query';
  suggestion?: string;
}

// 意图描述
export const INTENT_DESCRIPTIONS: Record<IntentType, string> = {
  market_analysis: '市场分析',
  trade_execution: '交易执行',
  risk_control: '风险控制',
  intelligence: '情报监控',
  strategy_design: '策略设计',
  signal_query: '信号查询',
  contradiction: '矛盾分析',
  review: '复盘回顾',
  exit: '离场决策',
  unknown: '未知意图',
};

// 意图到动作的映射
const INTENT_ACTION_MAP: Record<IntentType, 'market' | 'trade' | 'skill' | 'query'> = {
  market_analysis: 'market',
  trade_execution: 'trade',
  risk_control: 'trade',
  intelligence: 'query',
  strategy_design: 'skill',
  signal_query: 'query',
  contradiction: 'skill',
  review: 'skill',
  exit: 'trade',
  unknown: 'query',
};

// 前端本地意图识别（快速响应）
const INTENT_PATTERNS: Record<IntentType, RegExp[]> = {
  market_analysis: [
    /行情|走势|趋势|分析|怎么看|怎么样/i,
    /BTC|ETH|SOL|比特币|以太坊/i,
  ],
  trade_execution: [
    /买入|做多|开多|买入/i,
    /卖出|做空|开空|平仓/i,
  ],
  risk_control: [
    /止损|止盈|风控|仓位/i,
    /风险|限制亏损/i,
  ],
  intelligence: [
    /监控|提醒|警报|通知/i,
    /关注|监视/i,
  ],
  strategy_design: [
    /策略|方案|计划|怎么操作/i,
  ],
  signal_query: [
    /信号|指标|MACD|RSI|均线/i,
  ],
  contradiction: [
    /矛盾|冲突|多空/i,
  ],
  review: [
    /复盘|总结|回顾|反思/i,
  ],
  exit: [
    /离场|退出|结束/i,
    /止损|止盈/i,
  ],
  unknown: [],
};

// 币种映射
const SYMBOL_MAP: Record<string, string> = {
  btc: 'BTC-USDT-SWAP',
  比特币: 'BTC-USDT-SWAP',
  eth: 'ETH-USDT-SWAP',
  以太坊: 'ETH-USDT-SWAP',
  以太: 'ETH-USDT-SWAP',
  sol: 'SOL-USDT-SWAP',
  doge: 'DOGE-USDT-SWAP',
  xrp: 'XRP-USDT-SWAP',
  ada: 'ADA-USDT-SWAP',
};

// 方向映射
const DIRECTION_PATTERNS: [RegExp, 'long' | 'short'][] = [
  [/做多|买入|买多|开多|多头|多/i, 'long'],
  [/做空|卖出|卖空|开空|空头|空/i, 'short'],
];

/**
 * 本地快速意图识别
 */
export function detectIntentLocal(text: string): Partial<RoutingResult> {
  const lowerText = text.toLowerCase();
  
  // 检测意图类型
  let maxScore = 0;
  let detectedIntent: IntentType = 'unknown';
  
  for (const [intent, patterns] of Object.entries(INTENT_PATTERNS)) {
    if (intent === 'unknown') continue;
    
    const score = patterns.filter(p => p.test(lowerText)).length;
    if (score > maxScore) {
      maxScore = score;
      detectedIntent = intent as IntentType;
    }
  }
  
  // 提取币种
  let symbol = 'BTC-USDT-SWAP';
  for (const [keyword, mapped] of Object.entries(SYMBOL_MAP)) {
    if (lowerText.includes(keyword)) {
      symbol = mapped;
      break;
    }
  }
  
  // 提取方向
  let direction: 'long' | 'short' | undefined;
  for (const [pattern, dir] of DIRECTION_PATTERNS) {
    if (pattern.test(lowerText)) {
      direction = dir;
      break;
    }
  }
  
  return {
    intent: detectedIntent,
    confidence: maxScore > 0 ? Math.min(maxScore * 0.3, 0.9) : 0,
    symbol,
    direction,
    action: INTENT_ACTION_MAP[detectedIntent],
  };
}

/**
 * 完整意图路由（调用桥接层）
 */
export async function routeIntent(
  text: string,
  useLocalFirst: boolean = true
): Promise<RoutingResult> {
  // 本地快速识别
  const localResult = detectIntentLocal(text);
  const localIntent = localResult.intent ?? 'unknown';
  const localConfidence = localResult.confidence ?? 0;
  
  if (useLocalFirst && localConfidence >= 0.5) {
    return {
      ...localResult,
      intent: localIntent,
      confidence: localConfidence,
      skills: getSkillsForIntent(localIntent),
    } as RoutingResult;
  }
  
  // 调用桥接层
  try {
    const response = await IntentAPI.route(text);
    
    if (response.success) {
      const remoteIntent = (response.intent?.primary_intent || 'unknown') as IntentType;
      return {
        intent: remoteIntent,
        confidence: response.intent?.confidence || 0,
        symbol: response.extracted?.symbol,
        direction: response.extracted?.direction,
        skills: response.intent?.skills || [],
        action: INTENT_ACTION_MAP[remoteIntent],
        suggestion: response.routing?.suggested_action,
      };
    }
  } catch (error) {
    console.error('Intent routing failed, using local fallback:', error);
  }
  
  // 回退到本地识别
  return {
    ...localResult,
    intent: localIntent,
    confidence: localConfidence,
    skills: getSkillsForIntent(localIntent),
  } as RoutingResult;
}

/**
 * 根据意图获取推荐SKILL
 */
export function getSkillsForIntent(intent: IntentType): string[] {
  const skillMap: Record<IntentType, string[]> = {
    market_analysis: ['A1', 'A2', 'regime'],
    trade_execution: ['A5', 'A9'],
    risk_control: ['A9', 'risk'],
    intelligence: ['A6', 'intelligence'],
    strategy_design: ['A3', 'A4', 'strategy-parser'],
    signal_query: ['signal', 'regime'],
    contradiction: ['A0', 'A1'],
    review: ['A7', 'A8', 'episodes'],
    exit: ['A9', 'exit'],
    unknown: [],
  };
  
  return skillMap[intent] || [];
}

/**
 * 执行意图对应的动作
 */
export async function executeIntentAction(result: RoutingResult): Promise<any> {
  switch (result.action) {
    case 'market':
      // 获取市场数据
      return await MarketAPI.getTicker(result.symbol);
    
    case 'trade':
      // 交易执行需要更多信息
      return {
        pending: true,
        message: `准备${result.direction || ''} ${result.symbol}`,
        requiresConfirmation: true,
      };
    
    case 'skill':
      // 执行SKILL
      const primarySkill = result.skills[0];
      if (primarySkill) {
        return await SkillAPI.executeSkill(primarySkill, {
          symbol: result.symbol,
          intent: result.intent,
        });
      }
      return { error: 'No skill available' };
    
    case 'query':
      // 查询信号
      return await MarketAPI.getTicker(result.symbol);
    
    default:
      return { error: 'Unknown action' };
  }
}

/**
 * 获取意图示例
 */
export async function getIntentExamples(): Promise<Record<IntentType, string[]>> {
  try {
    const response = await IntentAPI.getExamples();
    if (response.success) {
      return response.examples;
    }
  } catch (error) {
    console.error('Failed to get examples:', error);
  }
  
  // 默认示例
  return {
    market_analysis: ['BTC现在行情怎么样', '分析一下以太坊走势'],
    trade_execution: ['买入1手BTC', '做空ETH'],
    risk_control: ['设置止损', '止盈怎么设'],
    intelligence: ['帮我监控BTC价格', '开启警报'],
    strategy_design: ['给我一个交易策略', '制定方案'],
    signal_query: ['现在有哪些信号', 'MACD怎么看'],
    contradiction: ['多空矛盾在哪', '分析主要矛盾'],
    review: ['复盘一下', '总结这笔交易'],
    exit: ['离场', '平仓'],
    unknown: [],
  };
}

export default {
  detectIntentLocal,
  routeIntent,
  getSkillsForIntent,
  executeIntentAction,
  getIntentExamples,
};
