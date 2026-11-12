// ============================================
// Trading Ranking 域客户端 — 今日交易榜单
// ============================================
// /api/trading-ranking/today 返回非标准信封（{ success, items, metrics }），
// 且页面有「接口不可用则保持 mock」的降级契约，因此这里失败返回 null 而非抛错。

export interface TradingRankingPayload {
  items: unknown[];
  metrics: unknown | null;
}

/** 拉取今日榜单；不可用/失败返回 null（调用方保持 mock 降级） */
export async function fetchTradingRanking(): Promise<TradingRankingPayload | null> {
  try {
    const res = await fetch('/api/trading-ranking/today', { cache: 'no-store' });
    if (!res.ok) return null;
    const body = (await res.json()) as { success?: boolean; items?: unknown; metrics?: unknown };
    if (!body?.success) return null;
    return {
      items: Array.isArray(body.items) ? body.items : [],
      metrics: body.metrics ?? null,
    };
  } catch {
    return null;
  }
}

export const rankingApi = {
  today: fetchTradingRanking,
};
