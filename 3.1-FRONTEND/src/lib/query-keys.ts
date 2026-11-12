// ============================================
// Query Key 约定（SPEC-20261111-C §3.4 / T-C4）
// ============================================
// 统一 key 形状：['domain', 'resource', params?]
// 写操作后按 domain 失效，禁止全量 invalidateQueries()。

export type QueryKey = readonly [string, string, Record<string, unknown>?];

/** 默认 staleTime 30s；行情类 5s（SPEC-C §3.4） */
export const STALE_TIME_DEFAULT = 30_000;
export const STALE_TIME_MARKET = 5_000;
export const QUERY_RETRY = 1;

export function queryKey(
  domain: string,
  resource: string,
  params?: Record<string, unknown>,
): QueryKey {
  return params ? [domain, resource, params] : [domain, resource];
}

/** 行情类 domain 的 staleTime 判定（不引额外配置层） */
export function queryStaleTime(domain: string): number {
  return domain === 'market' || domain === 'price' ? STALE_TIME_MARKET : STALE_TIME_DEFAULT;
}

/** 结构性最小接口，避免在纯函数模块里引入 React 依赖 */
export interface DomainInvalidator {
  invalidateQueries: (filters: { queryKey: readonly unknown[]; exact?: boolean }) => unknown;
}

/** 写操作后按 domain 失效（前缀匹配） */
export function invalidateDomain(client: DomainInvalidator, domain: string): unknown {
  return client.invalidateQueries({ queryKey: [domain] });
}
