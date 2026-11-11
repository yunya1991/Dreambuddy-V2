/**
 * @jest-environment node
 *
 * Phase 4.6 脑暴结果格式化：路由中文映射 + 拦截提示。
 */
import {
  ROUTE_LABELS,
  formatBrainstormMessage,
  interceptHint,
  routeLabel,
} from './brainstorm-format';

describe('routeLabel', () => {
  it('五分流均有中文名', () => {
    expect(Object.keys(ROUTE_LABELS)).toEqual(
      expect.arrayContaining(['trade_deny', 'high_risk_human', 'debate', 'workers', 'direct_answer']),
    );
    expect(routeLabel('debate')).toBe('择优辩论');
    expect(routeLabel('workers')).toBe('单边规划（workers）');
  });

  it('未知/空路由回退', () => {
    expect(routeLabel('unknown_route')).toBe('unknown_route');
    expect(routeLabel(undefined)).toBe('未知路由');
  });
});

describe('interceptHint', () => {
  it('交易与高风险给出明确拦截提示', () => {
    expect(interceptHint('trade_deny')).toContain('交易执行不进辩论');
    expect(interceptHint('high_risk_human')).toContain('人工审批');
    expect(interceptHint('debate')).toBeNull();
  });
});

describe('formatBrainstormMessage', () => {
  it('渲染路由/跳过原因/胜出方案/蒸馏写入数', () => {
    const text = formatBrainstormMessage({
      ok: true,
      route: 'debate',
      skipped: false,
      mode: 'debate',
      winner: 'pc-abc',
      decision: { score: 0.84 },
      outbox_written: 2,
      trace_id: 'bs-1',
    });
    expect(text).toContain('择优辩论');
    expect(text).toContain('pc-abc');
    expect(text).toContain('score 0.84');
    expect(text).toContain('蒸馏写入：2 条');
  });

  it('交易拦截时含跳过原因与拦截提示', () => {
    const text = formatBrainstormMessage({
      ok: true,
      route: 'trade_deny',
      skipped: true,
      reason: '命中下单动作',
    });
    expect(text).toContain('已跳过');
    expect(text).toContain('已拦截：交易执行不进辩论');
  });

  it('降级时展示错误', () => {
    const text = formatBrainstormMessage({ ok: false, degraded: true, error: 'orchestrator_timeout' });
    expect(text).toContain('调用降级');
    expect(text).toContain('orchestrator_timeout');
  });
});
