// ============================================
// Meta-Labeling 域客户端（非标准信封 { success, results }）
// ============================================
// 失败 / 非 2xx / 空 results 一律返回 null，页面据此保持本地 mock 降级。

export interface MetaLabelL1Signal {
  source: string;
  name: string;
  direction: 'long' | 'short' | 'neutral';
  confidence: number;
}

export interface MetaLabelResult {
  signal: MetaLabelL1Signal;
  winProbability: number;
  expectedValue: number;
  decision: 'execute' | 'observe' | 'skip';
  sizeMultiplier: number;
}

/** 拉取 L2 决策结果；不可用时返回 null 交由页面降级 */
export async function fetchMetaLabeling(): Promise<MetaLabelResult[] | null> {
  try {
    const res = await fetch('/api/meta-labeling', { cache: 'no-store' });
    if (!res.ok) return null;
    const body = (await res.json()) as { success?: boolean; results?: unknown };
    if (!body?.success || !Array.isArray(body.results)) return null;
    return body.results as MetaLabelResult[];
  } catch {
    return null;
  }
}

export const metaLabelingApi = {
  list: fetchMetaLabeling,
};
