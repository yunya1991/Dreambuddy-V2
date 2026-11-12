import { invalidateDomain, queryKey, queryStaleTime, STALE_TIME_DEFAULT, STALE_TIME_MARKET } from '@/lib/query-keys';

describe('query-keys (T-C4)', () => {
  it('统一 key 形状 [domain, resource, params?]', () => {
    expect(queryKey('reports', 'list')).toEqual(['reports', 'list']);
    expect(queryKey('reports', 'list', { page: 1 })).toEqual(['reports', 'list', { page: 1 }]);
  });

  it('行情类 domain staleTime 5s，其余 30s', () => {
    expect(queryStaleTime('market')).toBe(STALE_TIME_MARKET);
    expect(queryStaleTime('price')).toBe(STALE_TIME_MARKET);
    expect(queryStaleTime('reports')).toBe(STALE_TIME_DEFAULT);
    expect(STALE_TIME_MARKET).toBeLessThan(STALE_TIME_DEFAULT);
  });

  it('写操作按 domain 前缀失效（非全量）', () => {
    const client = { invalidateQueries: jest.fn() };
    invalidateDomain(client, 'reports');
    expect(client.invalidateQueries).toHaveBeenCalledWith({ queryKey: ['reports'] });
  });
});
