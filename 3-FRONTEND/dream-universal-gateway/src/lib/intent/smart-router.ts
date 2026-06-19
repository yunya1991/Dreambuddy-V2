/**
 * Smart Router - 智能交易路由引擎
 * 基于三个闭环 + 用户角色 + 问题复杂度的动态路由
 */

import { emitMonitorEvent } from '@/lib/monitor-bus';
import { IntentType, ComplexityLevel, SessionContext } from './fallback-engine';
import { updateLastRoutingChain } from './intent-memory';
import { routeToStrategyChain, STRATEGY_COMMAND_ROUTE_MAP } from '@/lib/strategy';

// ============ 类型定义 ============

export type LoopType = 'execution' | 'intelligence' | 'governance' | 'general';

export interface RoutingDecision {
  loop_type: LoopType;
  chain: string[];
  estimated_time_ms: number;
  credits_cost: number;
  requires_confirmation: boolean;
  role_check: 'pass' | 'upgrade_required' | 'denied';
  fallback_chain: string[];
  reasoning: string;
  /** Phase 2+: 是否走动态计划-执行-反思闭环 */
  is_dynamic?: boolean;
}

// ============ 动态链配置 (Phase 2) ============

/** 环境开关：ENABLE_DYNAMIC_CHAIN=true/1 时启用；'false'/'0'/'0' 显式禁用，其余默认启用
 * 对 PRO 用户特定意图启用 Plan-Execute-Reflect 动态链
 */
const ENABLE_DYNAMIC_CHAIN = (() => {
  if (typeof process === 'undefined') return true;
  const v = (process.env.ENABLE_DYNAMIC_CHAIN || '').toLowerCase();
  if (v === 'false' || v === '0' || v === 'no' || v === 'off') return false;
  if (v === 'true' || v === '1' || v === 'yes' || v === 'on') return true;
  // 默认启用（dynamic-chain 可回退到正常执行，是纯增加的）
  return true;
})();

/** 启用动态计划-执行-反思闭环的意图列表（developer 不走动态链） */
const DYNAMIC_INTENTS: Array<Exclude<IntentType, 'command'>> = [
  'deep_analysis',
  'scenario_sim',
  'strategy_verify',
  'execute_trade',
];

// ============ 链定义 (统一链名规范) ============
//
// 重要说明（Phase 0 边界清理）：
// - S系列（S1-S5）是前端主策略思维链，由 src/lib/strategy/ 模块管理
// - D-Z-E系列是开发专用链，由 src/lib/dev-chain/ 模块管理，不在此定义
// - A系列（A1-A9）是后端 Web3 研究技能链，前端不应直接引用
// - simple/utility 步骤（direct_answer/market_data 等）统一为 S0/S1 的子步骤
//
// 最终只保留前端主链 S系列的步骤定义

export const CHAIN_STEPS: Record<string, { label: string; icon: string; loop: LoopType; credits: number; time_ms: number; chain?: 'S' }> = {
  // S0 - 快捷路径（简单问答，无需完整思维链）
  S0_DIRECT_ANSWER: { label: 'S0_快速回答', icon: '💬', loop: 'general', credits: 5, time_ms: 2000, chain: 'S' },

  // S系列 - 策略思维链（5步标准结构）
  S1_RESEARCH:    { label: 'S1_调研', icon: '🔍', loop: 'execution', credits: 30,  time_ms: 15000, chain: 'S' },
  S2_ANALYSIS:    { label: 'S2_分析', icon: '🧠', loop: 'execution', credits: 50,  time_ms: 30000, chain: 'S' },
  S3_DESIGN:      { label: 'S3_设计', icon: '🎯', loop: 'execution', credits: 60,  time_ms: 45000, chain: 'S' },
  S4_VALIDATE:    { label: 'S4_验证', icon: '✅', loop: 'execution', credits: 80,  time_ms: 60000, chain: 'S' },
  S5_EXECUTE:     { label: 'S5_执行', icon: '⚡', loop: 'execution', credits: 20,  time_ms: 10000, chain: 'S' },
};

// ============ 意图 → 路由映射表 ============

interface RouteConfig {
  loop: LoopType;
  free_chain: string[];
  pro_short_chain: string[];
  pro_full_chain: string[];
  requires_confirmation: boolean;
  fallback_chain: string[];
}

const ROUTE_MAP: Record<Exclude<IntentType, 'command'>, RouteConfig> = {
  market_query: {
    loop: 'intelligence',
    // 行情查询走 S1 调研步骤（包含 market_data 的能力）
    free_chain: ['S1_RESEARCH'],
    pro_short_chain: ['S1_RESEARCH'],
    pro_full_chain: ['S1_RESEARCH'],
    requires_confirmation: false,
    fallback_chain: ['S1_RESEARCH'],
  },
  // S系列策略思维链 - 完整策略制定
  triple_chain: {
    loop: 'execution',
    free_chain: ['S1_RESEARCH', 'S2_ANALYSIS'],
    pro_short_chain: ['S1_RESEARCH', 'S2_ANALYSIS', 'S3_DESIGN'],
    pro_full_chain: ['S1_RESEARCH', 'S2_ANALYSIS', 'S3_DESIGN', 'S4_VALIDATE', 'S5_EXECUTE'],
    requires_confirmation: true,
    fallback_chain: ['S1_RESEARCH', 'S2_ANALYSIS'],
  },
  // 深度分析 - 使用S系列链
  deep_analysis: {
    loop: 'execution',
    free_chain: ['S1_RESEARCH', 'S2_ANALYSIS'],
    pro_short_chain: ['S1_RESEARCH', 'S2_ANALYSIS', 'S3_DESIGN'],
    pro_full_chain: ['S1_RESEARCH', 'S2_ANALYSIS', 'S3_DESIGN', 'S4_VALIDATE', 'S5_EXECUTE'],
    requires_confirmation: true,
    fallback_chain: ['S1_RESEARCH', 'S2_ANALYSIS'],
  },
  // 情景模拟 - 使用S系列链
  scenario_sim: {
    loop: 'execution',
    free_chain: ['S1_RESEARCH', 'S2_ANALYSIS'],
    pro_short_chain: ['S1_RESEARCH', 'S2_ANALYSIS', 'S3_DESIGN', 'S4_VALIDATE'],
    pro_full_chain: ['S1_RESEARCH', 'S2_ANALYSIS', 'S3_DESIGN', 'S4_VALIDATE'],
    requires_confirmation: true,
    fallback_chain: ['S1_RESEARCH', 'S2_ANALYSIS'],
  },
  // 策略验证 - 使用S系列链
  strategy_verify: {
    loop: 'execution',
    free_chain: ['S2_ANALYSIS', 'S3_DESIGN'],
    pro_short_chain: ['S2_ANALYSIS', 'S3_DESIGN', 'S4_VALIDATE'],
    pro_full_chain: ['S2_ANALYSIS', 'S3_DESIGN', 'S4_VALIDATE'],
    requires_confirmation: true,
    fallback_chain: ['S2_ANALYSIS', 'S3_DESIGN'],
  },
  // 执行交易 - 使用S系列链
  execute_trade: {
    loop: 'execution',
    free_chain: ['S1_RESEARCH', 'S2_ANALYSIS', 'S3_DESIGN'],
    pro_short_chain: ['S1_RESEARCH', 'S2_ANALYSIS', 'S3_DESIGN', 'S4_VALIDATE', 'S5_EXECUTE'],
    pro_full_chain: ['S1_RESEARCH', 'S2_ANALYSIS', 'S3_DESIGN', 'S4_VALIDATE', 'S5_EXECUTE'],
    requires_confirmation: true,
    fallback_chain: ['S1_RESEARCH', 'S2_ANALYSIS'],
  },
  system_config: {
    loop: 'general',
    // 系统配置类走 S0 快速回答
    free_chain: ['S0_DIRECT_ANSWER'],
    pro_short_chain: ['S0_DIRECT_ANSWER'],
    pro_full_chain: ['S0_DIRECT_ANSWER'],
    requires_confirmation: false,
    fallback_chain: ['S0_DIRECT_ANSWER'],
  },
  credits_query: {
    loop: 'general',
    // 积分查询走 S0 快速回答
    free_chain: ['S0_DIRECT_ANSWER'],
    pro_short_chain: ['S0_DIRECT_ANSWER'],
    pro_full_chain: ['S0_DIRECT_ANSWER'],
    requires_confirmation: false,
    fallback_chain: ['S0_DIRECT_ANSWER'],
  },
  artifact_query: {
    loop: 'general',
    // 知识库查询走 S1 调研（S1 内部包含知识库检索能力）
    free_chain: ['S1_RESEARCH'],
    pro_short_chain: ['S1_RESEARCH'],
    pro_full_chain: ['S1_RESEARCH'],
    requires_confirmation: false,
    fallback_chain: ['S0_DIRECT_ANSWER'],
  },
  risk_alert_response: {
    loop: 'intelligence',
    // 风险告警走 S2 分析（快速评估风险级别）
    free_chain: ['S2_ANALYSIS'],
    pro_short_chain: ['S2_ANALYSIS'],
    pro_full_chain: ['S2_ANALYSIS'],
    requires_confirmation: false,
    fallback_chain: ['S0_DIRECT_ANSWER'],
  },
  simple_qa: {
    loop: 'general',
    // 简单问答走 S0 快速回答
    free_chain: ['S0_DIRECT_ANSWER'],
    pro_short_chain: ['S0_DIRECT_ANSWER'],
    pro_full_chain: ['S0_DIRECT_ANSWER'],
    requires_confirmation: false,
    fallback_chain: ['S0_DIRECT_ANSWER'],
  },
  need_clarification: {
    loop: 'general',
    free_chain: [],
    pro_short_chain: [],
    pro_full_chain: [],
    requires_confirmation: true,
    fallback_chain: [],
  },
  clarification_result: {
    loop: 'general',
    // 澄清结果走 S0 快速回答
    free_chain: ['S0_DIRECT_ANSWER'],
    pro_short_chain: ['S0_DIRECT_ANSWER'],
    pro_full_chain: ['S0_DIRECT_ANSWER'],
    requires_confirmation: false,
    fallback_chain: ['S0_DIRECT_ANSWER'],
  },
  // 策略代码开发：S 级策略明确后生成可执行的策略代码
  // FREE 角色也能执行完整 S3→S4→S5（策略代码开发核心链）
  developer: {
    loop: 'execution',
    free_chain: ['S3_DESIGN', 'S4_VALIDATE', 'S5_EXECUTE'],
    pro_short_chain: ['S3_DESIGN', 'S4_VALIDATE', 'S5_EXECUTE'],
    pro_full_chain: ['S3_DESIGN', 'S4_VALIDATE', 'S5_EXECUTE'],
    requires_confirmation: true,
    fallback_chain: ['S5_EXECUTE'],
  },
};

// ============ 命令路由 ============

const COMMAND_ROUTE_MAP: Record<string, { intent: IntentType; chain: string[]; loop: LoopType }> = {
  // 行情查询命令 - 走 S1 调研步骤
  '/行情': { intent: 'market_query', chain: ['S1_RESEARCH'], loop: 'intelligence' },
  '/hq':   { intent: 'market_query', chain: ['S1_RESEARCH'], loop: 'intelligence' },
  // 使用S系列策略思维链
  '/分析': { intent: 'deep_analysis',   chain: ['S1_RESEARCH', 'S2_ANALYSIS', 'S3_DESIGN'],       loop: 'execution' },
  '/fx':   { intent: 'deep_analysis',   chain: ['S1_RESEARCH', 'S2_ANALYSIS', 'S3_DESIGN'],       loop: 'execution' },
  '/推演': { intent: 'scenario_sim',    chain: ['S1_RESEARCH', 'S2_ANALYSIS', 'S3_DESIGN', 'S4_VALIDATE'], loop: 'execution' },
  '/验证': { intent: 'strategy_verify', chain: ['S2_ANALYSIS', 'S3_DESIGN', 'S4_VALIDATE'],                    loop: 'execution' },
  '/开仓': { intent: 'execute_trade',   chain: ['S1_RESEARCH', 'S2_ANALYSIS', 'S3_DESIGN', 'S4_VALIDATE', 'S5_EXECUTE'], loop: 'execution' },
  // 策略代码开发命令
  '/策略代码': { intent: 'developer', chain: ['S3_DESIGN', 'S4_VALIDATE', 'S5_EXECUTE'], loop: 'execution' },
  '/策略': { intent: 'developer', chain: ['S3_DESIGN', 'S4_VALIDATE', 'S5_EXECUTE'], loop: 'execution' },
};

// ============ 主路由函数 ============

export function routeIntent(
  intent: IntentType,
  complexity: ComplexityLevel,
  context?: SessionContext
): RoutingDecision {
  const startTime = Date.now();
  const userRole = context?.user_role || 'FREE';
  const thinkingMode = context?.thinking_mode || 'quick';

  // 命令路由
  if (intent === 'command') {
    const msg = context?.message_history?.[context.message_history.length - 1] || '';
    const cmdKey = Object.keys(COMMAND_ROUTE_MAP).find(cmd => msg.startsWith(cmd));
    if (cmdKey) {
      const cmdRoute = COMMAND_ROUTE_MAP[cmdKey];
      const decision: RoutingDecision = {
        loop_type: cmdRoute.loop,
        chain: cmdRoute.chain,
        estimated_time_ms: calcTime(cmdRoute.chain),
        credits_cost: calcCredits(cmdRoute.chain),
        requires_confirmation: cmdRoute.intent === 'execute_trade',
        role_check: cmdRoute.intent === 'execute_trade' && userRole === 'FREE' ? 'upgrade_required' : 'pass',
        fallback_chain: cmdRoute.chain.slice(0, 1),
        reasoning: `Command route: ${cmdKey}`,
      };

      emitMonitorEvent({
        trace_id: `route_${Date.now()}`,
        uid: context?.session_id || 'anonymous',
        layer: 'router',
        phase: 'routed',
        status: decision.role_check === 'denied' ? 'denied' : 'completed',
        intent,
        chain: decision.chain,
        duration_ms: Date.now() - startTime,
      });

      return decision;
    }
  }

  const routeConfig = ROUTE_MAP[intent as keyof typeof ROUTE_MAP];
  if (!routeConfig) {
    return getDefaultRoute(intent);
  }

  // 执行 trade 对 FREE 用户不可用
  if (intent === 'execute_trade' && userRole === 'FREE') {
    const decision: RoutingDecision = {
      loop_type: routeConfig.loop,
      chain: [],
      estimated_time_ms: 0,
      credits_cost: 0,
      requires_confirmation: true,
      role_check: 'upgrade_required',
      fallback_chain: routeConfig.fallback_chain,
      reasoning: 'Trade execution requires PRO role',
    };

    emitMonitorEvent({
      trace_id: `route_${Date.now()}`,
      uid: context?.session_id || 'anonymous',
      layer: 'router',
      phase: 'routed',
      status: 'denied',
      intent,
      chain: [],
      duration_ms: Date.now() - startTime,
    });

    return decision;
  }

  // scenario_sim 对 FREE 用户 complex 不可用
  if (intent === 'scenario_sim' && userRole === 'FREE' && (complexity === 'complex' || complexity === 'urgent')) {
    const decision: RoutingDecision = {
      loop_type: routeConfig.loop,
      // 降级到 S1 调研（S1 内部包含知识库检索能力）
      chain: ['S1_RESEARCH'],
      estimated_time_ms: calcTime(['S1_RESEARCH']),
      credits_cost: calcCredits(['S1_RESEARCH']),
      requires_confirmation: false,
      role_check: 'upgrade_required',
      fallback_chain: ['S1_RESEARCH'],
      reasoning: 'Scenario simulation complex requires PRO role, downgraded to S1 research',
    };
    return decision;
  }

  // 根据角色和复杂度选择路径
  let chain: string[];
  if (userRole === 'FREE') {
    chain = routeConfig.free_chain;
  } else {
    // PRO: 根据复杂度选择
    if (thinkingMode === 'deep' && complexity !== 'simple') {
      chain = routeConfig.pro_full_chain;
    } else {
      chain = routeConfig.pro_short_chain;
    }
  }

  // 紧急事件处理: 强制使用 S2 分析（快速评估）
  if (complexity === 'urgent') {
    chain = ['S2_ANALYSIS'];
  }

  // Phase 2+: 动态链分流 — 对 PRO 用户的 DYNAMIC_INTENTS 启用 Plan-Execute-Reflect 闭环
  let isDynamic = false;
  if (ENABLE_DYNAMIC_CHAIN && userRole === 'PRO' &&
      DYNAMIC_INTENTS.includes(intent as (typeof DYNAMIC_INTENTS)[number])) {
    isDynamic = true;
    // 对动态链使用完整链作为种子；真正的"动态步骤"由 task-manager 中的 runner 产生
    chain = routeConfig.pro_full_chain;
  }

  const decision: RoutingDecision = {
    loop_type: routeConfig.loop,
    chain,
    estimated_time_ms: calcTime(chain),
    credits_cost: calcCredits(chain),
    requires_confirmation: routeConfig.requires_confirmation,
    role_check: chain.length > 0 ? 'pass' : 'upgrade_required',
    fallback_chain: routeConfig.fallback_chain,
    reasoning: isDynamic
      ? `[DYNAMIC] ${userRole} + ${complexity} + ${thinkingMode} → plan-execute-reflect 闭环`
      : `${userRole} + ${complexity} + ${thinkingMode} → chain: ${chain.join(' → ')}`,
    is_dynamic: isDynamic,
  };

  emitMonitorEvent({
    trace_id: `route_${Date.now()}`,
    uid: context?.session_id || 'anonymous',
    layer: 'router',
    phase: 'routed',
    status: 'completed',
    intent,
    chain: decision.chain,
    duration_ms: Date.now() - startTime,
  });

  // 更新记忆库中的路由链
  updateLastRoutingChain(context?.session_id || 'anonymous', decision.chain);

  return decision;
}

// ============ 辅助函数 ============

function getDefaultRoute(intent: IntentType): RoutingDecision {
  return {
    loop_type: 'general',
    chain: ['S0_DIRECT_ANSWER'],
    estimated_time_ms: 2000,
    credits_cost: 5,
    requires_confirmation: false,
    role_check: 'pass',
    fallback_chain: ['S0_DIRECT_ANSWER'],
    reasoning: `Unknown intent "${intent}", defaulting to direct answer`,
  };
}

function calcCredits(chain: string[]): number {
  return chain.reduce((sum, step) => sum + (CHAIN_STEPS[step]?.credits || 10), 0);
}

function calcTime(chain: string[]): number {
  return chain.reduce((sum, step) => sum + (CHAIN_STEPS[step]?.time_ms || 5000), 0);
}

// ============ 降级路由 ============

export function downgradeChain(chain: string[]): string[] {
  if (!chain || chain.length === 0) return ['S0_DIRECT_ANSWER'];

  const available = chain.filter(step => CHAIN_STEPS[step]);
  if (available.length === 0) return ['S0_DIRECT_ANSWER'];
  if (available.length === chain.length) return chain;

  // 部分步骤不可用，降级到可用步骤
  return available.length > 0 ? available : ['S0_DIRECT_ANSWER'];
}

// ============ 获取循环颜色 ============

export function getLoopColor(loop: LoopType): string {
  switch (loop) {
    case 'execution':   return '#3b82f6'; // blue
    case 'intelligence': return '#f59e0b'; // amber
    case 'governance':  return '#8b5cf6'; // purple
    case 'general':     return '#6b7280'; // gray
  }
}

export function getLoopLabel(loop: LoopType): string {
  switch (loop) {
    case 'execution':   return '执行环';
    case 'intelligence': return '情报环';
    case 'governance':  return '治理环';
    case 'general':     return '通用';
  }
}

// ============ 链名统一 ============

export function normalizeChainName(name: string): string {
  // 旧名 → 新名映射（Phase 0: 清理 A系列和旧 utility 步骤的别名）
  // 注意：D-Z-E 系列已在 dev-chain 模块中独立管理，此处只处理 S 系列的向后兼容
  const aliasMap: Record<string, string> = {
    // 旧 utility 步骤名 → S 系列
    'knowledge_base': 'S1_RESEARCH',
    'tavily_search': 'S1_RESEARCH',
    'market_data': 'S1_RESEARCH',
    'direct_answer': 'S0_DIRECT_ANSWER',
    // 旧 A 系列别名（兼容性保留，最终应删除）
    'A1_research': 'S1_RESEARCH',
    'A2_analysis': 'S2_ANALYSIS',
    'A2_advisor': 'S2_ANALYSIS',
    'A3_simulation': 'S3_DESIGN',
    'A3_strategy': 'S3_DESIGN',
    'A4_validation': 'S4_VALIDATE',
    'A5_execution': 'S5_EXECUTE',
    'A6_intel': 'S2_ANALYSIS',
    'A6_intelligence': 'S2_ANALYSIS',
    'A6_alert': 'S2_ANALYSIS',
    'A7_gate': 'S5_EXECUTE',
    'A7_practice': 'S5_EXECUTE',
    'A8_verification': 'S4_VALIDATE',
    'A9_exit': 'S5_EXECUTE',
  };
  return aliasMap[name] || name;
}

// ============ S 系列步进确认机制 ============
//
// 注意：S 系列的高风险步骤（S3_DESIGN, S4_VALIDATE, S5_EXECUTE）需要用户确认
// developer 意图 → S3→S4→S5，同样遵循这个确认机制
// D-Z-E 系列（后端完整开发链）不在前端主链中，由 6-Trading 模块独立管理

/**
 * 判断链中是否包含需要步进确认的步骤
 * S系列：S3_DESIGN, S4_VALIDATE, S5_EXECUTE 需要确认
 */
export function requiresStepConfirmation(chain: string[]): boolean {
  // S 系列中需要确认的高风险步骤
  const S_CONFIRM_STEPS = ['S3_DESIGN', 'S4_VALIDATE', 'S5_EXECUTE'];
  return chain.some(step => S_CONFIRM_STEPS.includes(step));
}

/**
 * 判断是否为可以直接执行的步骤（不需要用户确认）
 * - S0/S1/S2：直接执行
 * - S3/S4/S5：高风险步骤，需要确认
 */
export function isExecutionChainStep(step: string): boolean {
  const CONFIRM_STEPS = ['S3_DESIGN', 'S4_VALIDATE', 'S5_EXECUTE'];
  // S 系列的高风险步骤，或未识别的步骤，都需要走确认流程
  if (CONFIRM_STEPS.includes(step)) return false;
  return true;
}

/**
 * 获取链中需要确认的步骤（仅 S 系列）
 */
export function getConfirmationSteps(chain: string[]): string[] {
  return chain.filter(step => ['S3_DESIGN', 'S4_VALIDATE', 'S5_EXECUTE'].includes(step));
}

/**
 * 获取下一个需要确认的步骤索引
 */
export function getNextConfirmationStep(chain: string[], currentIndex: number): number {
  for (let i = currentIndex + 1; i < chain.length; i++) {
    const step = chain[i];
    if (['S3_DESIGN', 'S4_VALIDATE', 'S5_EXECUTE'].includes(step)) return i;
  }
  return -1;
}

/**
 * 生成步进确认提示语（S 系列的通用提示，不再提及 D-Z-E）
 */
export function generateStepConfirmationPrompt(
  currentStep: string,
  nextStep: string | null,
  lang: 'zh' | 'en' = 'zh'
): string {
  const isZh = lang === 'zh';
  const currentStepDef = CHAIN_STEPS[currentStep];
  const currentLabel = currentStepDef?.label || currentStep;

  if (!nextStep) {
    // 最后一步，询问是否落地
    return isZh
      ? `✅ **${currentLabel} 完成**\n\n请确认是否进入执行阶段落地：\n\n- 回复 **(1)** 确认并落地\n- 回复 **(2)** 先查看完整链路再决定`
      : `✅ **${currentLabel} Complete**\n\nProceed to execution? (1) Confirm & execute (2) Review full chain first`;
  }

  const nextStepDef = CHAIN_STEPS[nextStep];
  const nextLabel = nextStepDef?.label || nextStep;
  const nextChainTag = nextStepDef?.chain || '';

  return isZh
    ? `✅ **${currentLabel} 完成**\n\n策略开发链已启用，**高风险步骤需要您确认后方可继续**。\n\n请选择下一步操作：\n- **(1)** 进入下一步：**${nextLabel}** (${nextChainTag}链)\n- **(2)** 当前方案已满意，直接落地执行\n\n⚠️ **注意：系统禁止跳步。如想提前落地，请选择 (2)。**`
    : `✅ **${currentLabel} Complete**\n\nStrategy dev chain active, **confirmation required for high-risk steps.**\n\nChoose next action:\n- **(1)** Proceed to: **${nextLabel}** (${nextChainTag} chain)\n- **(2)** Satisfied with current plan, finalize and execute\n\n⚠️ **Note: Step skipping is not allowed. Choose (2) to finalize early.**`;
}

/**
 * 判断用户回复是否为确认继续
 */
export function parseUserConfirmation(response: string): 'continue' | 'finalize' | 'unknown' {
  const normalized = response.trim().toLowerCase();

  if (normalized === '1' || normalized === 'continue' || normalized.includes('继续') || normalized.includes('下一步')) {
    return 'continue';
  }
  if (normalized === '2' || normalized === 'finalize' || normalized.includes('落地') || normalized.includes('执行')) {
    return 'finalize';
  }
  return 'unknown';
}
