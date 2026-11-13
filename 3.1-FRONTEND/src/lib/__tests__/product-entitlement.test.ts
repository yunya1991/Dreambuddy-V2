/**
 * SPEC-52 F2 / §9.5 — 产品包 entitlement 单测
 */
import {
  AI_TRADING_PRODUCT,
  LOCAL_OWNER_ID,
  PRODUCT_NOT_ENTITLED,
  entitlementDeniedPayload,
  getEntitlement,
  isEntitled,
} from '@/lib/product/entitlement';

const ORIGINAL = process.env.PRODUCT_AI_TRADING_STATUS;

afterEach(() => {
  if (ORIGINAL === undefined) delete process.env.PRODUCT_AI_TRADING_STATUS;
  else process.env.PRODUCT_AI_TRADING_STATUS = ORIGINAL;
});

describe('product entitlement', () => {
  it('本地 owner 默认开通', () => {
    delete process.env.PRODUCT_AI_TRADING_STATUS;
    const e = getEntitlement();
    expect(e.user_id).toBe(LOCAL_OWNER_ID);
    expect(e.product_id).toBe(AI_TRADING_PRODUCT);
    expect(e.status).toBe('active');
    expect(e.source).toBe('default');
    expect(isEntitled()).toBe(true);
  });

  it('env=inactive 时锁定', () => {
    process.env.PRODUCT_AI_TRADING_STATUS = 'inactive';
    const e = getEntitlement();
    expect(e.status).toBe('inactive');
    expect(e.source).toBe('env');
    expect(isEntitled()).toBe(false);
  });

  it('env=active 时显式开通', () => {
    process.env.PRODUCT_AI_TRADING_STATUS = 'active';
    expect(getEntitlement().status).toBe('active');
    expect(getEntitlement().source).toBe('env');
  });

  it('403 响应体使用标准错误码', () => {
    const payload = entitlementDeniedPayload();
    expect(payload.ok).toBe(false);
    expect(payload.error.code).toBe(PRODUCT_NOT_ENTITLED);
  });
});
