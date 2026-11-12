import { shouldVirtualize, VIRTUALIZE_THRESHOLD, VIRTUALIZED_ROW_STYLE } from '@/lib/virtualization';

describe('virtualization (T-B8)', () => {
  it('阈值以下不启用', () => {
    expect(shouldVirtualize(0)).toBe(false);
    expect(shouldVirtualize(VIRTUALIZE_THRESHOLD)).toBe(false);
  });

  it('超过阈值启用', () => {
    expect(shouldVirtualize(VIRTUALIZE_THRESHOLD + 1)).toBe(true);
    expect(shouldVirtualize(200)).toBe(true);
  });

  it('非法值不启用', () => {
    expect(shouldVirtualize(Number.NaN)).toBe(false);
    expect(shouldVirtualize(Number.POSITIVE_INFINITY)).toBe(false);
  });

  it('虚拟化行样式为 content-visibility + 估算高度', () => {
    expect(VIRTUALIZED_ROW_STYLE.contentVisibility).toBe('auto');
    expect(VIRTUALIZED_ROW_STYLE.containIntrinsicSize).toContain('120px');
  });
});
