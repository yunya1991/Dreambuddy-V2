/**
 * SPEC-52 F2 / §9.5 — AI 交易产品包 entitlement（单账户本地 owner）
 *
 * 单用户本地阶段（ADR-8）：固定 local owner，默认开通；
 * 付费墙路径先在代码中打通但不启用 —— 用 `PRODUCT_AI_TRADING_STATUS=inactive`
 * 可验证「页面可见但操作锁定 / 交易 API 全部 403」。
 *
 * 边界：服务端门禁为准，前端隐藏只做体验；本模块只做纯判断，不做 IO。
 */

export const LOCAL_OWNER_ID = 'local';
export const AI_TRADING_PRODUCT = 'ai-trading';
export const PRODUCT_NOT_ENTITLED = 'PRODUCT_NOT_ENTITLED';

export type EntitlementStatus = 'active' | 'inactive';

export interface ProductEntitlement {
  user_id: string;
  product_id: string;
  status: EntitlementStatus;
  balance_cu: number;
  source: 'env' | 'default';
  updated_at: string;
}

function readStatus(): { status: EntitlementStatus; source: ProductEntitlement['source'] } {
  const raw = (process.env.PRODUCT_AI_TRADING_STATUS || '').trim().toLowerCase();
  if (raw === 'inactive' || raw === 'disabled' || raw === 'off') {
    return { status: 'inactive', source: 'env' };
  }
  if (raw === 'active' || raw === 'on') {
    return { status: 'active', source: 'env' };
  }
  // 未显式配置：本地 owner 默认开通（付费墙代码路径保留）
  return { status: 'active', source: 'default' };
}

function readBalanceCu(): number {
  const parsed = Number(process.env.PRODUCT_AI_TRADING_BALANCE_CU ?? '1000');
  return Number.isFinite(parsed) && parsed >= 0 ? parsed : 0;
}

export function getEntitlement(userId: string = LOCAL_OWNER_ID): ProductEntitlement {
  const { status, source } = readStatus();
  return {
    user_id: userId,
    product_id: AI_TRADING_PRODUCT,
    status,
    balance_cu: readBalanceCu(),
    source,
    updated_at: new Date().toISOString(),
  };
}

export function isEntitled(userId?: string): boolean {
  return getEntitlement(userId).status === 'active';
}

/** 路由层 403 响应体（SPEC-52 §9.5：未开通时交易 API 全部 403）。 */
export function entitlementDeniedPayload() {
  return {
    ok: false,
    error: {
      code: PRODUCT_NOT_ENTITLED,
      message: 'AI 交易产品包未开通：页面可浏览，交易操作已锁定。',
    },
  };
}
