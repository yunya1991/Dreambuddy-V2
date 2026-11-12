// ============================================
// Briefing 域客户端 — 每日简报
// ============================================
// 注意：/api/briefings 返回非标准信封（{ success, briefings } / { success, briefing }），
// 无法复用 api-client 的 data 信封归一化，这里保留既有契约原样解析。

export interface BriefingListItem {
  id: string;
  type: string;
  title: string;
  generated_at: string;
  date: string;
  summary?: string;
}

/** 列表：失败抛错，由 Query 层呈现错误/重试 */
export async function fetchBriefingList(limit = 50): Promise<BriefingListItem[]> {
  const res = await fetch(`/api/briefings?limit=${limit}`);
  if (!res.ok) throw new Error(`加载简报列表失败: HTTP ${res.status}`);
  const body = (await res.json()) as { success?: boolean; briefings?: unknown };
  if (!body?.success) throw new Error('加载简报列表失败');
  return Array.isArray(body.briefings) ? (body.briefings as BriefingListItem[]) : [];
}

/** 详情：失败抛错，由 Query 层呈现错误/重试 */
export async function fetchBriefingDetail(id: string): Promise<Record<string, unknown>> {
  const res = await fetch(`/api/briefings/${id}`);
  if (!res.ok) throw new Error(`加载简报详情失败: HTTP ${res.status}`);
  const body = (await res.json()) as { success?: boolean; briefing?: unknown };
  if (!body?.success || !body.briefing) throw new Error('加载简报详情失败');
  return body.briefing as Record<string, unknown>;
}

export const briefingApi = {
  list: fetchBriefingList,
  detail: fetchBriefingDetail,
};
