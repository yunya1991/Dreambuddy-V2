/**
 * Smart Router - 智能交易路由引擎
 * 基于三个闭环 + 用户角色 + 问题复杂度的动态路由
 */

import { emitMonitorEvent } from '@/lib/monitor-bus';
import { IntentType, ComplexityLevel, SessionContext } from './fallback-engine';
import { updateLastRoutingChain } from './intent-memory';

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
}

// ============ 链定义 (统一链名规范) ============

export const CHAIN_STEPS: Record<string, { label: string; icon: string; loop: LoopType; credits: number; time_ms: number; chain?: 'D' | 'Z' | 'E' }> = {
  // A系列（原交易链路，保留兼容)
  A1_research:    { label: '市场侦察', icon: '🔍', loop: 'execution',    credits: 50,  time_ms: 30000 },
  A2_analysis:    { label: '深度分析', icon: '🧠', loop: 'execution',    credits: 80,  time_ms: 45000 },
  A3_simulation: { label: '情景推演', icon: '🎲', loop: 'execution',    credits: 100, time_ms: 60000 },
  A4_validation: { label: '方案验证', icon: '✅', loop: 'execution',    credits: 120, time_ms: 45000 },
  A5_execution:   { label: '决策执行', icon: '⚡', loop: 'execution',    credits: 150, time_ms: 30000 },
  A9_exit:        { label: '离场评估', icon: '🚪', loop: 'execution',    credits: 80,  time_ms: 20000 },
  A6_intelligence:{ label: '情报监控', icon: '📡', loop: 'intelligence', credits: 30,  time_ms: 15000 },
  A6_alert:       { label: '情报告警', icon: '⚠️', loop: 'intelligence', credits: 20,  time_ms: 5000 },
  A7_practice:    { label: '实践记录', icon: '📝', loop: 'governance',   credits: 60,  time_ms: 30000 },
  A8_verification:{ label: '知行验证', icon: '🔮', loop: 'governance',   credits: 70,  time_ms: 30000 },
  knowledge_base: { label: '知识库',   icon: '📚', loop: 'general',      credits: 5,   time_ms: 2000 },
  tavily_search:  { label: '联网搜索', icon: '🌐', loop: 'general',      credits: 10,  time_ms: 8000 },
  market_data:    { label: '行情数据', icon: '📊', loop: 'intelligence', credits: 5,   time_ms: 3000 },
  direct_answer:  { label: '直接回答', icon: '💬', loop: 'general',      credits: 5,   time_ms: 2000 },

  // D系列 - 调研分析链（每步需用户确认）
  D1_investigator: { label: 'D1深度调研', icon: '🔍', loop: 'execution', credits: 50, time_ms: 30000, chain: 'D' },
  D2_analyst:      { label: 'D2分析诊断', icon: '🧠', loop: 'execution', credits: 80, time_ms: 45000, chain: 'D' },
  D3_deducer:      { label: 'D3推演验证', icon: '🎲', loop: 'execution', credits: 100, time_ms: 60000, chain: 'D' },
  D4_spec_author:  { label: 'D4-Spec合成', icon: '📝', loop: 'execution', credits: 120, time_ms: 45000, chain: 'D' },

  // Z系列 - 实施规划链（每步需用户确认）
  Z1_code_scanner:         { label: 'Z1代码扫描', icon: '🏗️', loop: 'execution', credits: 60, time_ms: 35000, chain: 'Z' },
  Z2_boundary_divider:     { label: 'Z2范围划分', icon: '📐', loop: 'execution', credits: 70, time_ms: 40000, chain: 'Z' },
  Z3_path_planner:         { label: 'Z3路径设计', icon: '🗺️', loop: 'execution', credits: 80, time_ms: 45000, chain: 'Z' },
  Z4_acceptance_designer:  { label: 'Z4验收方案', icon: '✅', loop: 'execution', credits: 90, time_ms: 40000, chain: 'Z' },

  // E系列 - 执行交付链（不需要每步确认）
  E1_task_executor: { label: 'E1任务执行', icon: '⚡', loop: 'execution', credits: 100, time_ms: 60000, chain: 'E' },
  E2_tester:        { label: 'E2测试验证', icon: '🧪', loop: 'execution', credits: 80,  time_ms: 45000, chain: 'E' },
  E3_deployer:      { label: 'E3部署交付', icon: '🚀', loop: 'execution', credits: 60,  time_ms: 30000, chain: 'E' },
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
    free_chain: ['knowledge_base', 'market_data'],
    pro_short_chain: ['A6_intelligence', 'market_data'],
    pro_full_chain: ['A6_intelligence', 'market_data'],
    requires_confirmation: false,
    fallback_chain: ['market_data'],
  },
  // D/Z/E 三链模式（步进确认机制）
  triple_chain: {
    loop: 'execution',
    free_chain: ['D1_investigator', 'D2_analyst', 'D3_deducer', 'D4_spec_author'],
    pro_short_chain: ['D1_investigator', 'D2_analyst', 'D3_deducer', 'D4_spec_author'],
    pro_full_chain: ['D1_investigator', 'D2_analyst', 'D3_deducer', 'D4_spec_author', 'Z1_code_scanner', 'Z2_boundary_divider', 'Z3_path_planner', 'Z4_acceptance_designer', 'E1_task_executor', 'E2_tester', 'E3_deployer'],
    requires_confirmation: true, // D/E/Z 每步需用户确认
    fallback_chain: ['D1_investigator'],
  },
  deep_analysis: {
    loop: 'execution',
    free_chain: ['D1_investigator', 'D2_analyst'],
    pro_short_chain: ['D1_investigator', 'D2_analyst'],
    pro_full_chain: ['D1_investigator', 'D2_analyst', 'D3_deducer', 'D4_spec_author'],
    requires_confirmation: true,
    fallback_chain: ['D1_investigator', 'D2_analyst'],
  },
  scenario_sim: {
    loop: 'execution',
    free_chain: ['knowledge_base'],
    pro_short_chain: ['A3_simulation'],
    pro_full_chain: ['A1_research', 'A2_analysis', 'A3_simulation'],
    requires_confirmation: false,
    fallback_chain: ['A2_analysis'],
  },
  strategy_verify: {
    loop: 'execution',
    free_chain: ['A4_validation'],
    pro_short_chain: ['A4_validation'],
    pro_full_chain: ['A3_simulation', 'A4_validation', 'A5_execution'],
    requires_confirmation: false,
    fallback_chain: ['A2_analysis'],
  },
  execute_trade: {
    loop: 'execution',
    free_chain: [],
    pro_short_chain: ['A4_validation', 'A5_execution'],
    pro_full_chain: ['A4_validation', 'A5_execution', 'A9_exit'],
    requires_confirmation: true,
    fallback_chain: ['A4_validation'],
  },
  system_config: {
    loop: 'general',
    free_chain: ['direct_answer'],
    pro_short_chain: ['direct_answer'],
    pro_full_chain: ['direct_answer'],
    requires_confirmation: false,
    fallback_chain: ['direct_answer'],
  },
  credits_query: {
    loop: 'general',
    free_chain: ['direct_answer'],
    pro_short_chain: ['direct_answer'],
    pro_full_chain: ['direct_answer'],
    requires_confirmation: false,
    fallback_chain: ['direct_answer'],
  },
  artifact_query: {
    loop: 'general',
    free_chain: ['knowledge_base'],
    pro_short_chain: ['knowledge_base'],
    pro_full_chain: ['knowledge_base', 'tavily_search'],
    requires_confirmation: false,
    fallback_chain: ['direct_answer'],
  },
  risk_alert_response: {
    loop: 'intelligence',
    free_chain: ['A6_intelligence', 'A6_alert'],
    pro_short_chain: ['A6_intelligence', 'A6_alert'],
    pro_full_chain: ['A6_intelligence', 'A6_alert'],
    requires_confirmation: false,
    fallback_chain: ['direct_answer'],
  },
  simple_qa: {
    loop: 'general',
    free_chain: ['direct_answer'],
    pro_short_chain: ['direct_answer'],
    pro_full_chain: ['tavily_search', 'direct_answer'],
    requires_confirmation: false,
    fallback_chain: ['direct_answer'],
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
    free_chain: ['direct_answer'],
    pro_short_chain: ['direct_answer'],
    pro_full_chain: ['direct_answer'],
    requires_confirmation: false,
    fallback_chain: ['direct_answer'],
  },
};

// ============ 命令路由 ============

const COMMAND_ROUTE_MAP: Record<string, { intent: IntentType; chain: string[]; loop: LoopType }> = {
  '/行情': { intent: 'market_query',    chain: ['market_data'],                     loop: 'intelligence' },
  '/hq':   { intent: 'market_query',    chain: ['market_data'],                     loop: 'intelligence' },
  '/分析': { intent: 'deep_analysis',   chain: ['A1_research', 'A2_analysis'],       loop: 'execution' },
  '/fx':   { intent: 'deep_analysis',   chain: ['A1_research', 'A2_analysis'],       loop: 'execution' },
  '/推演': { intent: 'scenario_sim',    chain: ['A1_research', 'A2_analysis', 'A3_simulation'], loop: 'execution' },
  '/验证': { intent: 'strategy_verify', chain: ['A4_validation'],                    loop: 'execution' },
  '/开仓': { intent: 'execute_trade',   chain: ['A4_validation', 'A5_execution', 'A9_exit'], loop: 'execution' },
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
      chain: ['knowledge_base'],
      estimated_time_ms: calcTime(['knowledge_base']),
      credits_cost: calcCredits(['knowledge_base']),
      requires_confirmation: false,
      role_check: 'upgrade_required',
      fallback_chain: ['knowledge_base'],
      reasoning: 'Scenario simulation complex requires PRO role, downgraded to knowledge base',
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

  // 紧急事件处理: 强制使用情报环
  if (complexity === 'urgent') {
    chain = ['A6_intelligence', 'A6_alert'];
  }

  const decision: RoutingDecision = {
    loop_type: routeConfig.loop,
    chain,
    estimated_time_ms: calcTime(chain),
    credits_cost: calcCredits(chain),
    requires_confirmation: routeConfig.requires_confirmation,
    role_check: chain.length > 0 ? 'pass' : 'upgrade_required',
    fallback_chain: routeConfig.fallback_chain,
    reasoning: `${userRole} + ${complexity} + ${thinkingMode} → chain: ${chain.join(' → ')}`,
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
    chain: ['direct_answer'],
    estimated_time_ms: 2000,
    credits_cost: 5,
    requires_confirmation: false,
    role_check: 'pass',
    fallback_chain: ['direct_answer'],
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
  if (!chain || chain.length === 0) return ['direct_answer'];

  const available = chain.filter(step => CHAIN_STEPS[step]);
  if (available.length === 0) return ['direct_answer'];
  if (available.length === chain.length) return chain;

  // 部分步骤不可用，降级到可用步骤
  return available.length > 0 ? available : ['direct_answer'];
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
  // 旧名 → 新名映射
  const aliasMap: Record<string, string> = {
    'A1_research': 'A1_research',
    'A2_analysis': 'A2_analysis',
    'A2_advisor': 'A2_analysis',
    'A3_simulation': 'A3_simulation',
    'A3_strategy': 'A3_simulation',
    'A4_validation': 'A4_validation',
    'A5_execution': 'A5_execution',
    'A6_intel': 'A6_intelligence',
    'A6_intelligence': 'A6_intelligence',
    'A7_gate': 'A9_exit',
    'market_data': 'market_data',
    'direct_answer': 'direct_answer',
  };
  return aliasMap[name] || name;
}

// ============ D/Z/E 步进确认机制 ============

/**
 * 判断链中是否包含需要步进确认的步骤（D/Z/E系列）
 * D系列和Z系列每步完成后需要用户确认
 * E系列不需要每步确认（执行模式）
 */
export function requiresStepConfirmation(chain: string[]): boolean {
  return chain.some(step => {
    const stepDef = CHAIN_STEPS[step];
    return stepDef?.chain === 'D' || stepDef?.chain === 'Z';
  });
}

/**
 * 判断是否为E系列步骤（执行链，不需要每步确认）
 */
export function isExecutionChainStep(step: string): boolean {
  const stepDef = CHAIN_STEPS[step];
  return stepDef?.chain === 'E';
}

/**
 * 获取链中需要确认的步骤（不包括E系列）
 */
export function getConfirmationSteps(chain: string[]): string[] {
  return chain.filter(step => {
    const stepDef = CHAIN_STEPS[step];
    return stepDef?.chain === 'D' || stepDef?.chain === 'Z';
  });
}

/**
 * 获取下一个需要确认的步骤索引
 */
export function getNextConfirmationStep(chain: string[], currentIndex: number): number {
  for (let i = currentIndex + 1; i < chain.length; i++) {
    const stepDef = CHAIN_STEPS[chain[i]];
    if (stepDef?.chain === 'D' || stepDef?.chain === 'Z') {
      return i;
    }
  }
  return -1; // 没有更多需要确认的步骤
}

/**
 * 生成步进确认提示语
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
      ? `✅ **${currentLabel} 完成**\n\n请问是否直接落地？\n\n- 回复 **(1)** 确认落地\n- 回复 **(2)** 查看完整链路并选择`
      : `✅ **${currentLabel} Complete**\n\nWould you like to finalize? (1) Confirm (2) Review full chain`;
  }

  const nextStepDef = CHAIN_STEPS[nextStep];
  const nextLabel = nextStepDef?.label || nextStep;

  return isZh
    ? `✅ **${currentLabel} 完成**\n\n请选择下一步操作：\n- **(1)** 进入下一步：**${nextLabel}**\n- **(2)** 直接落地（当前方案）\n- **(3)** 跳过后续步骤，直接落地`
    : `✅ **${currentLabel} Complete**\n\nChoose next action:\n- **(1)** Proceed to: **${nextLabel}**\n- **(2)** Finalize current solution\n- **(3)** Skip remaining steps and finalize`;
}

/**
 * 判断用户回复是否为确认继续
 */
export function parseUserConfirmation(response: string): 'continue' | 'finalize' | 'skip' | 'unknown' {
  const normalized = response.trim().toLowerCase();

  if (normalized === '1' || normalized === 'continue' || normalized.includes('继续') || normalized.includes('下一步')) {
    return 'continue';
  }
  if (normalized === '2' || normalized === 'finalize' || normalized.includes('落地')) {
    return 'finalize';
  }
  if (normalized === '3' || normalized === 'skip' || normalized.includes('跳过')) {
    return 'skip';
  }
  return 'unknown';
}
