'use client';

// ============================================
// QueryProvider — REST 缓存层（SPEC-20261111-C §3.4 / T-C4）
// ============================================
// 职责边界：REST 列表/详情/统计走 Query；SSE 实时事件走 zustand，不写 Query 缓存。

import React, { useState } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { QUERY_RETRY, STALE_TIME_DEFAULT } from '@/lib/query-keys';

export const QUERY_CLIENT_DEFAULTS = {
  staleTime: STALE_TIME_DEFAULT,
  gcTime: 5 * 60_000,
  retry: QUERY_RETRY,
  refetchOnWindowFocus: false,
} as const;

/** 独立构造，便于单测直接断言默认值 */
export function createQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: { queries: { ...QUERY_CLIENT_DEFAULTS } },
  });
}

export function QueryProvider({
  children,
  client,
}: {
  children: React.ReactNode;
  client?: QueryClient;
}) {
  const [queryClient] = useState(() => client ?? createQueryClient());
  return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
}

export default QueryProvider;
