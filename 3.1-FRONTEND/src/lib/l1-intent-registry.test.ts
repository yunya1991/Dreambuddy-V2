/**
 * L1 意图注册表测试 — v2 静态门控 + v3 route_confidence 信号入口 (P2.2)
 *
 * 覆盖：
 *   - v2 静态行为零回归：canHandleL1 / fallbackIntent
 *   - v3 信号门控：高置信 L1_DIRECT 放行、低置信/L2_HANDOFF 拦截、阈值边界 0.7
 *   - FAIL-OPEN：信号缺失/null/非法 → 退回静态 canHandleL1
 *   - 未注册意图：恒 false（信号不能越权放行）
 */
import {
  canHandleL1,
  canHandleL1WithSignal,
  fallbackIntent,
  isRouteConfidenceSignal,
  ROUTE_CONFIDENCE_THRESHOLD_HIGH,
  ROUTE_DECISION_L1_DIRECT,
  ROUTE_DECISION_L2_HANDOFF,
  type RouteConfidenceSignal,
} from './l1-intent-registry';

function makeSignal(partial: Partial<RouteConfidenceSignal> = {}): RouteConfidenceSignal {
  return {
    route_confidence: 0.9,
    decision: ROUTE_DECISION_L1_DIRECT,
    match_score: 0.9,
    case_density: 3,
    prediction_error: null,
    fast_path: false,
    degraded: false,
    ...partial,
  };
}

describe('l1-intent-registry v2 静态门控（零回归）', () => {
  it('requiredPattern 命中才放行通用意图', () => {
    expect(canHandleL1('data_query', '查一下 CPI 最新数据')).toBe(true);
    expect(canHandleL1('data_query', '帮我写首诗')).toBe(false);
  });

  it('fallbackPattern 意图直接可执行', () => {
    expect(canHandleL1('risk_control', '当前持仓风控状态')).toBe(true);
  });

  it('未注册意图恒 false', () => {
    expect(canHandleL1('not_an_intent', '查 CPI')).toBe(false);
  });

  it('fallbackIntent 关键词兜底', () => {
    expect(fallbackIntent('BTC 现在什么价')).toBe('price_query');
    expect(fallbackIntent('今天天气咋样')).toBe('');
  });

  it('阈值常量跨系统唯一 (SSoT §16.5)', () => {
    expect(ROUTE_CONFIDENCE_THRESHOLD_HIGH).toBe(0.7);
  });
});

describe('canHandleL1WithSignal v3 信号门控', () => {
  it('高置信 L1_DIRECT 放行（即使静态 requiredPattern 不命中）', () => {
    // 「帮我看看天」不命中 data_query 的 requiredPattern，但高置信信号以信号为准
    expect(canHandleL1WithSignal('data_query', '帮我看看天', makeSignal())).toBe(true);
  });

  it('L2_HANDOFF 信号拦截（即使静态规则放行）', () => {
    const signal = makeSignal({
      route_confidence: 0.4,
      decision: ROUTE_DECISION_L2_HANDOFF,
      degraded: true,
    });
    expect(canHandleL1WithSignal('risk_control', '当前持仓风控状态', signal)).toBe(false);
  });

  it('decision=L1_DIRECT 但置信度低于 0.7 仍拦截', () => {
    const signal = makeSignal({ route_confidence: 0.69 });
    expect(canHandleL1WithSignal('technical_analysis', '技术面', signal)).toBe(false);
  });

  it('阈值边界：route_confidence 恰好 0.7 放行', () => {
    const signal = makeSignal({ route_confidence: 0.7 });
    expect(canHandleL1WithSignal('path_insight', '最小阻力路径', signal)).toBe(true);
  });

  it('decision 与置信度不一致（L2_HANDOFF + 0.9）以 decision 为准拦截', () => {
    const signal = makeSignal({
      route_confidence: 0.9,
      decision: ROUTE_DECISION_L2_HANDOFF,
    });
    expect(canHandleL1WithSignal('price_query', 'BTC 什么价', signal)).toBe(false);
  });

  it('未注册意图即使带高置信信号也不放行', () => {
    expect(canHandleL1WithSignal('not_an_intent', '查 CPI', makeSignal())).toBe(false);
  });
});

describe('canHandleL1WithSignal FAIL-OPEN 静态兜底', () => {
  it('undefined / null 信号退回静态 canHandleL1', () => {
    expect(canHandleL1WithSignal('data_query', '查 CPI', undefined)).toBe(true);
    expect(canHandleL1WithSignal('data_query', '帮我写首诗', null)).toBe(false);
  });

  it('非法信号（缺字段/NaN/错 decision）退回静态校验', () => {
    expect(
      canHandleL1WithSignal('data_query', '查 CPI', { foo: 1 } as unknown as RouteConfidenceSignal),
    ).toBe(true);
    expect(
      canHandleL1WithSignal(
        'data_query',
        '查 CPI',
        makeSignal({ route_confidence: Number.NaN }),
      ),
    ).toBe(true);
    expect(
      canHandleL1WithSignal(
        'data_query',
        '查 CPI',
        makeSignal({ decision: 'MAYBE' as RouteConfidenceSignal['decision'] }),
      ),
    ).toBe(true);
  });
});

describe('isRouteConfidenceSignal 类型守卫', () => {
  it('合法信号', () => {
    expect(isRouteConfidenceSignal(makeSignal())).toBe(true);
  });

  it('null / 原始类型 / 残缺对象均不合法', () => {
    expect(isRouteConfidenceSignal(null)).toBe(false);
    expect(isRouteConfidenceSignal(undefined)).toBe(false);
    expect(isRouteConfidenceSignal('x')).toBe(false);
    expect(isRouteConfidenceSignal({})).toBe(false);
    expect(isRouteConfidenceSignal({ route_confidence: 0.9 })).toBe(false);
  });
});
