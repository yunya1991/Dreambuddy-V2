/**
 * SPEC-52 F6 — 工具 profile（服务端注入）
 *
 * 规则（硬约束）：
 *  - profile 由服务端按产品开通状态决定，前端只能声明 surface，不能自选 profile；
 *  - 只暴露白名单内工具，未注册的工具自然不可见；
 *  - `trading_proposal` 只能生成 order_intent / 策略提案草稿，禁止执行下单。
 */
import type { Tool } from 'ai';

export type ToolProfileId = 'platform' | 'trading_read' | 'trading_proposal' | 'admin';

export interface ToolProfileSpec {
  id: ToolProfileId;
  label: string;
  /** 可见工具白名单（工具名精确匹配） */
  allowedTools: readonly string[];
  /** 是否允许生成 order_intent 草稿（永不执行） */
  canProposeOrders: boolean;
  /** 注入 system prompt 的边界声明 */
  boundary: string;
}

/** 认知只读壳（写工具 record/verify 永不进入任何 profile） */
const COGNITION_READ = ['recall', 'unified_search', 'stats', 'health', 'l4_status'] as const;

/** 交易产品内只读工具（12/29/42/50/14/45 对应壳；未注册则不出现） */
const TRADING_READ = [
  'read_market',
  'read_signals',
  'read_positions',
  'read_strategy_params',
  'read_decision',
  'read_eval',
] as const;

/** 提案类工具：只落草稿，不触发执行 */
const TRADING_PROPOSAL = ['propose_order_intent', 'propose_strategy_change'] as const;

/** 治理只读 */
const ADMIN_READ = ['read_governance', 'read_audit'] as const;

export const TOOL_PROFILES: Record<ToolProfileId, ToolProfileSpec> = {
  platform: {
    id: 'platform',
    label: '平台只读',
    allowedTools: [...COGNITION_READ],
    canProposeOrders: false,
    boundary:
      '当前 profile=platform：仅通用金融只读与认知检索；无交易、策略、风控写能力，不得声称可以下单。',
  },
  trading_read: {
    id: 'trading_read',
    label: '交易只读',
    allowedTools: [...COGNITION_READ, ...TRADING_READ],
    canProposeOrders: false,
    boundary:
      '当前 profile=trading_read：可读行情/信号/持仓/参数/决策解释；禁止任何写入或下单。',
  },
  trading_proposal: {
    id: 'trading_proposal',
    label: '交易提案',
    allowedTools: [...COGNITION_READ, ...TRADING_READ, ...TRADING_PROPOSAL],
    canProposeOrders: true,
    boundary:
      '当前 profile=trading_proposal：可生成 order_intent / 策略提案草稿，草稿必须由用户在界面人工确认后才可执行；你不得声称已下单。',
  },
  admin: {
    id: 'admin',
    label: '治理只读',
    allowedTools: [...COGNITION_READ, ...ADMIN_READ],
    canProposeOrders: false,
    boundary: '当前 profile=admin：仅治理/审计查询，禁止写入与任何交易动作。',
  },
};

export interface ResolveToolProfileInput {
  /** 对话来源：工作台（平台）或交易产品内 */
  surface?: 'workbench' | 'trading';
  /** 产品包是否已开通（服务端判定） */
  entitled?: boolean;
}

export function resolveToolProfile(input: ResolveToolProfileInput = {}): ToolProfileSpec {
  if (input.surface === 'trading') {
    // 未开通：降级为平台只读，不暴露交易工具与提案能力
    return input.entitled ? TOOL_PROFILES.trading_proposal : TOOL_PROFILES.platform;
  }
  return TOOL_PROFILES.platform;
}

/** 按 profile 白名单过滤（保持原对象引用，避免重建工具）。 */
export function filterToolsByProfile<T extends Tool>(
  tools: Record<string, T> | undefined,
  profile: ToolProfileSpec,
): Record<string, T> | undefined {
  if (!tools) return undefined;
  const allowed = new Set(profile.allowedTools);
  const filtered: Record<string, T> = {};
  for (const [name, value] of Object.entries(tools)) {
    if (allowed.has(name)) filtered[name] = value;
  }
  return filtered;
}

/** profile 边界声明，拼进 system prompt。 */
export function profileSystemPrompt(profile: ToolProfileSpec): string {
  return profile.boundary;
}
