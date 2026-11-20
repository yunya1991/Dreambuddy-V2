/**
 * L2 路线收敛测试（P1-1 trace 侧）。
 * 契约：SPEC-56 IF-1 / SPEC-v1.4 §3.4；前端只透传，不重新裁决。
 */
import {
  L2_ROUTE_DEEP,
  L2_ROUTE_RETRIEVAL,
  L2_ROUTE_UNSPECIFIED,
  l2RouteFromRouteSignal,
  normalizeL2Route,
} from '@/lib/l2-route';

describe('normalizeL2Route', () => {
  it('保留两个合法路线', () => {
    expect(normalizeL2Route('retrieval_augmented')).toBe(L2_ROUTE_RETRIEVAL);
    expect(normalizeL2Route('deep_reasoning')).toBe(L2_ROUTE_DEEP);
  });

  it('缺失/非法一律 unspecified', () => {
    for (const v of [undefined, null, '', 'deeper', 1, {}, []]) {
      expect(normalizeL2Route(v)).toBe(L2_ROUTE_UNSPECIFIED);
    }
  });
});

describe('l2RouteFromRouteSignal', () => {
  it('读取 cognition_signal.l2_route', () => {
    expect(
      l2RouteFromRouteSignal({
        decision: 'L2_HANDOFF',
        cognition_signal: { coverage: 0.2, verdict: 'unknown', l2_route: 'deep_reasoning' },
      }),
    ).toBe(L2_ROUTE_DEEP);
  });

  it('信号缺失（FAIL-OPEN）→ unspecified，不猜', () => {
    expect(l2RouteFromRouteSignal(null)).toBe(L2_ROUTE_UNSPECIFIED);
    expect(l2RouteFromRouteSignal({ decision: 'L1_DIRECT' })).toBe(L2_ROUTE_UNSPECIFIED);
    expect(l2RouteFromRouteSignal({ cognition_signal: { l2_route: 'bogus' } })).toBe(
      L2_ROUTE_UNSPECIFIED,
    );
  });
});
